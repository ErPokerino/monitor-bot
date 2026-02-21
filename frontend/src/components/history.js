import { api } from '../api.js'
import { formatDuration, formatDate, statusLabel, statusColor } from './helpers.js'

export function historyPage() {
  return {
    loading: true,
    runs: [],
    selectedIds: new Set(),
    selectAll: false,

    async init() {
      try {
        this.runs = await api.getRuns()
      } catch {
        window.toast.error('Errore nel caricamento dello storico')
      } finally {
        this.loading = false
      }
    },

    toggleSelectAll() {
      if (this.selectAll) {
        this.selectedIds = new Set(this.runs.map(r => r.id))
      } else {
        this.selectedIds = new Set()
      }
    },
    toggleSelect(id) {
      const next = new Set(this.selectedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      this.selectedIds = next
      this.selectAll = next.size === this.runs.length
    },
    isSelected(id) {
      return this.selectedIds.has(id)
    },
    get selectionCount() {
      return this.selectedIds.size
    },

    async deleteSelected() {
      if (!this.selectionCount) return
      if (!confirm(`Eliminare ${this.selectionCount} esecuzione/i?`)) return
      try {
        const ids = Array.from(this.selectedIds)
        await api.deleteRunsBatch(ids)
        this.runs = this.runs.filter(r => !this.selectedIds.has(r.id))
        window.toast.success(`${ids.length} esecuzione/i eliminate`)
        this.selectedIds = new Set()
        this.selectAll = false
      } catch {
        window.toast.error('Errore nell\'eliminazione')
      }
    },

    formatDuration,
    formatDate,
    statusLabel,
    statusColor,
  }
}
