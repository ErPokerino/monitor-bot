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

const POLL_INTERVAL_MS = 3000

export function pipelineRunner() {
  return {
    state: 'loading',
    runId: null,
    _pollTimer: null,
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
          this._startPolling()
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
        this._startPolling()
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

    _startPolling() {
      this._stopPolling()
      this._pollTimer = setInterval(() => this._poll(), POLL_INTERVAL_MS)
      this._poll()
    },

    _stopPolling() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer)
        this._pollTimer = null
      }
    },

    async _poll() {
      if (!this.runId) return
      try {
        const data = await api.getRunProgress(this.runId)
        this._applyProgress(data)
      } catch {
        // ignore transient errors
      }
    },

    _applyProgress(data) {
      const p = data.progress || {}

      if (p.stages) {
        for (const s of p.stages) {
          this.stages = this.stages.map(existing =>
            existing.id === s.id
              ? { ...existing, status: s.status, summary: s.summary || s.detail || '', elapsed: s.elapsed_seconds ?? null }
              : existing
          )
        }
      }

      if (p.current_stage && p.total_stages) {
        const name = STAGE_NAMES[p.current_stage] || 'Fase ' + p.current_stage
        this.stageLabel = `${name} — ${p.stage_detail || ''}`
        const doneStages = (p.stages || []).filter(s => s.status === 'done').length
        this.overallPct = Math.round((doneStages / p.total_stages) * 100)
      }

      if (p.item_current != null) {
        this.itemCurrent = p.item_current
        this.itemTotal = p.item_total || 0
        this.itemLabel = p.item_label || ''
        if (p.current_stage === 1 && p.total_stages && p.item_total > 0) {
          const stageSpan = 100 / p.total_stages
          this.overallPct = Math.round((p.item_current / p.item_total) * stageSpan)
        }
      }

      if (p.finished || data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
        this._stopPolling()
        if (data.status === 'cancelled') {
          this.state = 'cancelled'
        } else if (data.status === 'failed') {
          this.state = 'error'
        } else {
          this.state = 'completed'
          this.overallPct = 100
        }
        this.finishSummary = p.finish_summary || ''
        this.stopping = false
      }
    },

    reset() {
      this._stopPolling()
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
