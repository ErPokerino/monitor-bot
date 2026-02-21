import { api } from '../api.js'
import { formatDuration } from './helpers.js'

const STAGE_NAMES = {
  1: 'Raccolta dati',
  2: 'Deduplicazione',
  3: 'Filtro scaduti',
  4: 'Classificazione AI',
  5: 'Arricchimento date',
  6: 'Finalizzazione',
}

export function pipelineRunner() {
  return {
    state: 'loading',
    runId: null,
    ws: null,
    stopping: false,
    stageLabel: 'Inizializzazione...',
    overallPct: 0,
    itemCurrent: 0,
    itemTotal: 0,
    itemLabel: '',
    finishSummary: '',
    stages: _buildStages(),

    async init() {
      try {
        const status = await api.getRunStatus()
        if (status.running) {
          this.state = 'running'
          this.runId = status.run_id
          this.connectWs()
        } else {
          this.state = 'idle'
        }
      } catch {
        this.state = 'idle'
      }
    },

    async start() {
      this.state = 'running'
      this.stopping = false
      this.resetStages()
      try {
        const data = await api.startRun()
        this.runId = data.id
        this.connectWs()
      } catch (e) {
        this.state = 'error'
        this.finishSummary = e.message || 'Errore avvio pipeline'
      }
    },

    async stop() {
      if (this.stopping) return
      this.stopping = true
      try { await api.stopRun() }
      catch { this.stopping = false }
    },

    connectWs() {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
      this.ws = new WebSocket(`${proto}//${location.host}/api/runs/ws`)
      this.ws.onmessage = (e) => this.handleWsMessage(JSON.parse(e.data))
      this.ws.onclose = () => {
        if (this.state === 'running') setTimeout(() => this.connectWs(), 2000)
      }
    },

    handleWsMessage(msg) {
      switch (msg.type) {
        case 'stage_begin':
          this.stages = this.stages.map(s =>
            s.id === msg.stage ? { ...s, status: 'running', summary: msg.detail } : s
          )
          this.stageLabel = `${STAGE_NAMES[msg.stage] || 'Fase ' + msg.stage} — ${msg.detail}`
          this.overallPct = Math.round(((msg.stage - 1) / msg.total_stages) * 100)
          this.itemCurrent = 0
          this.itemTotal = 0
          break

        case 'stage_end':
          this.stages = this.stages.map(s =>
            s.id === msg.stage
              ? { ...s, status: 'done', summary: msg.summary, elapsed: msg.elapsed_seconds }
              : s
          )
          this.overallPct = Math.round((msg.stage / msg.total_stages) * 100)
          break

        case 'item_progress':
          this.itemCurrent = msg.current
          this.itemTotal = msg.total
          this.itemLabel = msg.label
          if (this.stages.find(s => s.status === 'running')?.id === 1) {
            const base = 0
            const stageSpan = 100 / 6
            this.overallPct = Math.round(base + (msg.current / msg.total) * stageSpan)
          }
          break

        case 'finished':
          this.state = this.stopping ? 'cancelled' : 'completed'
          this.overallPct = this.stopping ? this.overallPct : 100
          this.finishSummary = msg.summary
          this.stopping = false
          if (this.ws) this.ws.close()
          break
      }
    },

    reset() {
      this.state = 'idle'
      this.runId = null
      this.overallPct = 0
      this.finishSummary = ''
      this.itemCurrent = 0
      this.itemTotal = 0
      this.resetStages()
    },

    resetStages() {
      this.stages = _buildStages()
    },

    formatDuration,
    formatStageDuration(s) {
      if (s.elapsed == null) return ''
      return formatDuration(s.elapsed)
    },
  }
}

function _buildStages() {
  return Object.entries(STAGE_NAMES).map(([id, name]) => ({
    id: parseInt(id), name, status: 'pending', summary: '', elapsed: null,
  }))
}
