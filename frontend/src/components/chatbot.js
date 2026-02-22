import { api } from '../api.js'
import { marked } from 'marked'
import { formatDate } from './helpers.js'

marked.setOptions({ breaks: true, gfm: true })

export function chatbotPage() {
  return {
    messages: [],
    input: '',
    loading: false,
    runs: [],
    selectedRunId: null,
    showRunSelector: false,
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
        const saved = localStorage.getItem('or-chat')
        if (saved) {
          const parsed = JSON.parse(saved)
          this.messages = parsed.messages || []
          this.selectedRunId = parsed.selectedRunId ?? null
        }

        const [runs, status] = await Promise.all([
          api.getRuns(),
          api.chatStatus(),
        ])
        this.runs = (runs || []).filter(r => r.status === 'completed' && r.total_relevant > 0)
        if (!saved && status.loaded_run_id) {
          this.selectedRunId = status.loaded_run_id
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
      return 'Ciao! Sono **Opportunity Bot**, il tuo assistente per Opportunity Radar.\n\n' +
        'Posso aiutarti a:\n' +
        '- Comprendere il funzionamento dell\'applicazione\n' +
        '- Analizzare i risultati delle esecuzioni\n' +
        '- Rispondere a domande su bandi, eventi e opportunit\u00e0 specifiche\n' +
        '- Spiegare le configurazioni e impostazioni\n\n' +
        'Per iniziare, seleziona un\'esecuzione dal menu in alto per caricare i risultati nel contesto, oppure chiedimi qualsiasi cosa!'
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
        const resp = await api.chatMessage(text, this.selectedRunId)
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

    async selectRun(runId) {
      const id = runId ? parseInt(runId) : null
      if (id === this.selectedRunId) return
      this.selectedRunId = id
      this.showRunSelector = false
      this.messages = []
      this.loading = true

      try {
        await api.chatReset()
        const run = this.runs.find(r => r.id === id)
        if (id && run) {
          this.messages.push({
            role: 'system',
            content: 'Esecuzione #' + id + ' del ' + formatDate(run.started_at) +
              ' caricata nel contesto (' + run.total_relevant + ' risultati rilevanti)',
          })
          const resp = await api.chatMessage(
            'L\'utente ha selezionato l\'esecuzione #' + id + '. Conferma brevemente che hai i risultati nel contesto e chiedi come puoi aiutarlo.',
            id,
          )
          this.messages.push({ role: 'assistant', content: resp.reply })
        } else {
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
      this.selectedRunId = null
      this.messages.push({ role: 'assistant', content: this._welcomeMessage() })
      localStorage.removeItem('or-chat')
    },

    renderMarkdown(text) {
      if (!text) return ''
      return marked.parse(text)
    },

    selectedRunLabel() {
      if (!this.selectedRunId) return 'Nessuna esecuzione'
      const run = this.runs.find(r => r.id === this.selectedRunId)
      if (!run) return 'Run #' + this.selectedRunId
      return '#' + run.id + ' - ' + formatDate(run.started_at) + ' (' + run.total_relevant + ' rilevanti)'
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
        const runParam = this.selectedRunId ? '&run_id=' + this.selectedRunId : ''
        const wsUrl = wsProto + '//' + location.host + '/api/chat/voice?token=' + encodeURIComponent(token) + runParam

        this._ws = new WebSocket(wsUrl)
        this._ws.binaryType = 'arraybuffer'

        this._ws.onopen = () => {
          this.voiceMode = true
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
        localStorage.setItem('or-chat', JSON.stringify({
          messages: this.messages,
          selectedRunId: this.selectedRunId,
        }))
      } catch (e) { /* quota exceeded - ignore */ }
    },

    _scrollToBottom() {
      const el = this.$refs.chatMessages
      if (el) el.scrollTop = el.scrollHeight
    },

    formatDate,
  }
}
