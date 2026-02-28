import { api } from '../api.js'
import { marked } from 'marked'

marked.setOptions({ breaks: true, gfm: true })

export function chatbotPage() {
  return {
    messages: [],
    input: '',
    loading: false,
    useAgenda: true,
    voiceMode: false,
    voiceConnected: false,
    _ws: null,
    _audioCtx: null,
    _mediaStream: null,
    _processor: null,
    _playQueue: [],
    _playing: false,

    async init() {
      try {
        const saved = localStorage.getItem(this._storageKey())
        if (saved) {
          const parsed = JSON.parse(saved)
          this.messages = parsed.messages || []
          this.useAgenda = parsed.useAgenda ?? true
        }

        const status = await api.chatStatus()
        if (!saved && status.use_agenda !== undefined) {
          this.useAgenda = status.use_agenda
        }
        if (this.messages.length === 0 && status.message_count === 0) {
          this.messages.push({
            role: 'assistant',
            content: this._welcomeMessage(),
          })
        }
        this._persist()
      } catch (e) {
        console.error('Chat init failed:', e)
      }
    },

    _welcomeMessage() {
      let name = ''
      try {
        const u = JSON.parse(localStorage.getItem('or-user') || 'null')
        name = u?.display_name || u?.username || ''
      } catch { /* noop */ }
      const greeting = name ? `Ciao **${name}**! ` : 'Ciao! '
      return greeting + 'Sono **Opportunity Bot**, il tuo assistente per Opportunity Radar.\n\n' +
        'Posso aiutarti a:\n' +
        '- Analizzare le opportunit\u00e0 presenti nella tua Agenda\n' +
        '- Confrontare bandi, eventi e finanziamenti\n' +
        '- Rispondere a domande su singole opportunit\u00e0\n' +
        '- Comprendere il funzionamento dell\'applicazione\n\n' +
        'Attiva il toggle **Contesto Agenda** per caricare tutte le opportunit\u00e0 nella conversazione, oppure chiedimi qualsiasi cosa!'
    },

    async send() {
      const text = this.input.trim()
      if (!text || this.loading) return
      this.input = ''
      this.messages.push({ role: 'user', content: text })
      this.loading = true
      this._persist()
      this.$nextTick(() => this._scrollToBottom())

      try {
        const resp = await api.chatMessage(text, { useAgenda: this.useAgenda })
        const msg = { role: 'assistant', content: resp.reply }
        if (resp.action === 'start_run') msg.action = 'start_run'
        this.messages.push(msg)
      } catch (e) {
        this.messages.push({
          role: 'assistant',
          content: 'Mi dispiace, si \u00e8 verificato un errore. Riprova tra qualche istante.',
          error: true,
        })
      } finally {
        this.loading = false
        this._persist()
        this.$nextTick(() => this._scrollToBottom())
      }
    },

    async confirmRun(msgIdx) {
      if (this.messages[msgIdx]) this.messages[msgIdx].action = null
      this.messages.push({ role: 'system', content: 'Avvio nuova ricerca in corso...' })
      this.loading = true
      this._persist()
      this.$nextTick(() => this._scrollToBottom())
      try {
        await api.startRun()
        this.messages.push({
          role: 'assistant',
          content: 'La ricerca \u00e8 stata avviata con successo! Puoi monitorare il progresso dalla sezione **Ricerca** oppure attendere il completamento.',
        })
      } catch (e) {
        this.messages.push({
          role: 'assistant',
          content: 'Non \u00e8 stato possibile avviare la ricerca: ' + (e.message || 'errore sconosciuto'),
          error: true,
        })
      } finally {
        this.loading = false
        this._persist()
        this.$nextTick(() => this._scrollToBottom())
      }
    },

    declineRun(msgIdx) {
      if (this.messages[msgIdx]) this.messages[msgIdx].action = null
      this.messages.push({
        role: 'assistant',
        content: 'Nessun problema, la ricerca non \u00e8 stata avviata. Posso aiutarti con qualcos\'altro?',
      })
      this._persist()
      this.$nextTick(() => this._scrollToBottom())
    },

    async toggleAgenda() {
      this.useAgenda = !this.useAgenda
      this.messages = []
      this.loading = true
      this._persist()

      try {
        await api.chatReset()
        if (this.useAgenda) {
          this.messages.push({
            role: 'system',
            content: 'Contesto Agenda attivato \u2014 tutte le opportunit\u00e0 sono disponibili nella conversazione',
          })
          const resp = await api.chatMessage(
            'L\'utente ha attivato il contesto Agenda. Conferma brevemente che hai accesso a tutte le opportunit\u00e0 dell\'agenda e chiedi come puoi aiutarlo.',
            { useAgenda: true },
          )
          this.messages.push({ role: 'assistant', content: resp.reply })
        } else {
          this.messages.push({
            role: 'system',
            content: 'Contesto Agenda disattivato',
          })
          this.messages.push({ role: 'assistant', content: this._welcomeMessage() })
        }
      } catch (e) {
        this.messages.push({ role: 'assistant', content: 'Errore nel cambio contesto.', error: true })
      } finally {
        this.loading = false
        this._persist()
        this.$nextTick(() => this._scrollToBottom())
      }
    },

    async resetChat() {
      try {
        await api.chatReset()
      } catch (e) { /* ignore */ }
      this.messages = []
      this.useAgenda = true
      this.messages.push({ role: 'assistant', content: this._welcomeMessage() })
      localStorage.removeItem(this._storageKey())
    },

    renderMarkdown(text) {
      if (!text) return ''
      return marked.parse(text)
    },

    toggleVoiceMode() {
      if (this.voiceMode) {
        this._disconnectVoice()
      } else {
        this._connectVoice()
      }
    },

    async _connectVoice() {
      try {
        this._audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 })
        this._mediaStream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: { ideal: 16000 }, channelCount: 1, echoCancellation: true, noiseSuppression: true }
        })

        const source = this._audioCtx.createMediaStreamSource(this._mediaStream)
        this._processor = this._audioCtx.createScriptProcessor(4096, 1, 1)

        const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:'
        const token = localStorage.getItem('or-token') || ''
        const q = new URLSearchParams()
        if (this.useAgenda) q.set('use_agenda', 'true')
        const wsUrl = wsProto + '//' + location.host + '/api/chat/voice' + (q.toString() ? '?' + q.toString() : '')

        this._ws = new WebSocket(wsUrl)
        this._ws.binaryType = 'arraybuffer'

        this._ws.onopen = () => {
          this.voiceMode = true
          this._ws.send(JSON.stringify({ type: 'auth', token }))
        }

        this._ws.onmessage = (event) => {
          if (event.data instanceof ArrayBuffer) {
            this._playQueue.push(event.data)
            this._drainPlayQueue()
          } else {
            try {
              const msg = JSON.parse(event.data)
              if (msg.type === 'connected') {
                this.voiceConnected = true
                this.messages.push({ role: 'system', content: 'Voice mode attivato' })
                this._persist()
              } else if (msg.type === 'transcript' && msg.text) {
                this.messages.push({ role: msg.role || 'assistant', content: msg.text })
                this._persist()
                const el = this.el_chatMessages()
                if (el) el.scrollTop = el.scrollHeight
              } else if (msg.type === 'error') {
                this.messages.push({ role: 'assistant', content: msg.message || 'Errore vocale', error: true })
                this._persist()
              }
            } catch (e) { /* ignore non-JSON */ }
          }
        }

        this._ws.onclose = () => {
          this._cleanupVoice()
        }

        this._ws.onerror = () => {
          this.messages.push({ role: 'assistant', content: 'Impossibile connettersi al servizio vocale.', error: true })
          this._persist()
          this._cleanupVoice()
        }

        this._processor.onaudioprocess = (e) => {
          if (this._ws && this._ws.readyState === WebSocket.OPEN) {
            const input = e.inputBuffer.getChannelData(0)
            const pcm16 = new Int16Array(input.length)
            for (let i = 0; i < input.length; i++) {
              const s = Math.max(-1, Math.min(1, input[i]))
              pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF
            }
            this._ws.send(pcm16.buffer)
          }
        }

        source.connect(this._processor)
        this._processor.connect(this._audioCtx.destination)
      } catch (e) {
        console.error('Voice connect failed:', e)
        this.messages.push({ role: 'assistant', content: 'Impossibile accedere al microfono.', error: true })
        this._persist()
        this._cleanupVoice()
      }
    },

    _disconnectVoice() {
      if (this._ws && this._ws.readyState === WebSocket.OPEN) {
        try { this._ws.send(JSON.stringify({ type: 'close' })) } catch (e) { /* */ }
        this._ws.close()
      }
      this._cleanupVoice()
      this.messages.push({ role: 'system', content: 'Voice mode disattivato' })
      this._persist()
    },

    _cleanupVoice() {
      if (this._processor) { try { this._processor.disconnect() } catch (e) { /* */ } this._processor = null }
      if (this._mediaStream) { this._mediaStream.getTracks().forEach(t => t.stop()); this._mediaStream = null }
      if (this._audioCtx && this._audioCtx.state !== 'closed') { try { this._audioCtx.close() } catch (e) { /* */ } }
      this._audioCtx = null
      this._ws = null
      this._playQueue = []
      this._playing = false
      this.voiceMode = false
      this.voiceConnected = false
    },

    async _drainPlayQueue() {
      if (this._playing || !this._playQueue.length) return
      this._playing = true
      while (this._playQueue.length > 0) {
        const buf = this._playQueue.shift()
        try {
          const playCtx = this._audioCtx
          if (!playCtx || playCtx.state === 'closed') break
          const pcm16 = new Int16Array(buf)
          const float32 = new Float32Array(pcm16.length)
          for (let i = 0; i < pcm16.length; i++) {
            float32[i] = pcm16[i] / 32768
          }
          const audioBuf = playCtx.createBuffer(1, float32.length, 24000)
          audioBuf.getChannelData(0).set(float32)
          const src = playCtx.createBufferSource()
          src.buffer = audioBuf
          src.connect(playCtx.destination)
          await new Promise(resolve => { src.onended = resolve; src.start() })
        } catch (e) { /* playback error */ }
      }
      this._playing = false
    },

    el_chatMessages() {
      try { return document.querySelector('[x-ref="chatMessages"]') } catch (e) { return null }
    },

    _persist() {
      try {
        localStorage.setItem(this._storageKey(), JSON.stringify({
          messages: this.messages,
          useAgenda: this.useAgenda,
        }))
      } catch (e) { /* quota exceeded - ignore */ }
    },

    _storageKey() {
      try {
        const user = JSON.parse(localStorage.getItem('or-user') || 'null')
        const username = user?.username || 'default'
        return `or-chat-${username}`
      } catch {
        return 'or-chat-default'
      }
    },

    _scrollToBottom() {
      const el = this.$refs.chatMessages
      if (el) el.scrollTop = el.scrollHeight
    },

  }
}
