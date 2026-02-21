import { api } from '../api.js'
import { formatDuration, formatDate, statusLabel, statusColor } from './helpers.js'

export function dashboardPage() {
  return {
    loading: true,
    stats: null,
    recentRuns: [],

    async init() {
      try {
        const data = await api.getDashboard()
        this.stats = data
        this.recentRuns = data.recent_runs || []
      } catch (e) {
        window.toast.error('Errore nel caricamento della dashboard')
      } finally {
        this.loading = false
      }
    },

    formatDuration,
    formatDate,
    statusLabel,
    statusColor,
  }
}
