import { Chart, BarController, LineController, BarElement, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Legend, Filler } from 'chart.js'
import { api } from '../api.js'
import { formatDuration, formatDate, statusLabel, statusColor } from './helpers.js'

Chart.register(BarController, LineController, BarElement, LineElement, PointElement, CategoryScale, LinearScale, Tooltip, Legend, Filler)

export function dashboardPage() {
  return {
    loading: true,
    stats: null,
    recentRuns: [],
    allRuns: [],
    _chart: null,
    selectedIds: new Set(),
    selectAll: false,

    async init() {
      try {
        const [data, runs] = await Promise.all([
          api.getDashboard(),
          api.getRuns(),
        ])
        this.stats = data
        this.recentRuns = data.recent_runs || []
        this.allRuns = runs || []
        this.$nextTick(() => this._renderChart())
      } catch (e) {
        window.toast.error('Errore nel caricamento della dashboard')
      } finally {
        this.loading = false
      }
    },

    toggleSelectAll() {
      if (this.selectAll) {
        this.selectedIds = new Set(this.allRuns.map(r => r.id))
      } else {
        this.selectedIds = new Set()
      }
    },
    toggleSelect(id) {
      const next = new Set(this.selectedIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      this.selectedIds = next
      this.selectAll = next.size === this.allRuns.length
    },
    isSelected(id) { return this.selectedIds.has(id) },
    get selectionCount() { return this.selectedIds.size },

    async deleteSelected() {
      if (!this.selectionCount) return
      if (!confirm(`Eliminare ${this.selectionCount} esecuzione/i?`)) return
      try {
        const ids = Array.from(this.selectedIds)
        await api.deleteRunsBatch(ids)
        this.allRuns = this.allRuns.filter(r => !this.selectedIds.has(r.id))
        this.recentRuns = this.recentRuns.filter(r => !this.selectedIds.has(r.id))
        window.toast.success(`${ids.length} esecuzione/i eliminate`)
        this.selectedIds = new Set()
        this.selectAll = false
        this.$nextTick(() => this._renderChart())
      } catch {
        window.toast.error("Errore nell'eliminazione")
      }
    },

    _aggregateByDay(runs) {
      const map = new Map()
      for (const r of runs) {
        const key = new Date(r.started_at).toLocaleDateString('it-IT', { day: '2-digit', month: '2-digit', year: 'numeric' })
        if (!map.has(key)) {
          map.set(key, { label: key, collected: 0, relevant: 0, runCount: 0 })
        }
        const bucket = map.get(key)
        bucket.collected += r.total_collected
        bucket.relevant += r.total_relevant
        bucket.runCount += 1
      }
      return [...map.values()]
    },

    _renderChart() {
      const canvas = this.$refs.activityChart
      if (!canvas || this.recentRuns.length === 0) return

      const days = this._aggregateByDay([...this.recentRuns].reverse())

      const accent = '#0ea5e9'
      const navy   = '#d9dbed'

      if (this._chart) this._chart.destroy()

      this._chart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels: days.map(d => d.label),
          datasets: [
            {
              label: 'Non rilevanti',
              data: days.map(d => d.collected - d.relevant),
              backgroundColor: navy,
              borderRadius: 4,
              stack: 'stack0',
              barPercentage: 0.5,
            },
            {
              label: 'Rilevanti',
              data: days.map(d => d.relevant),
              backgroundColor: accent,
              borderRadius: 4,
              stack: 'stack0',
              barPercentage: 0.5,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { position: 'top', align: 'end', labels: { boxWidth: 12, usePointStyle: true, pointStyle: 'rectRounded', padding: 16, font: { size: 12 } } },
            tooltip: {
              backgroundColor: '#1e293b',
              cornerRadius: 8,
              padding: 10,
              titleFont: { size: 12 },
              bodyFont: { size: 12 },
              callbacks: {
                afterBody: (items) => {
                  const day = days[items[0].dataIndex]
                  const rate = day.collected > 0 ? Math.round((day.relevant / day.collected) * 100) : 0
                  return [`Pertinenza: ${rate}%`, `Esecuzioni: ${day.runCount}`]
                },
              },
            },
          },
          scales: {
            x: { grid: { display: false }, ticks: { font: { size: 11 } } },
            y: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { font: { size: 11 }, stepSize: 1 } },
          },
        },
      })
    },

    get avgRelevanceRate() {
      const completed = this.recentRuns.filter(r => r.status === 'completed' && r.total_collected > 0)
      if (completed.length === 0) return 0
      const sum = completed.reduce((a, r) => a + (r.total_relevant / r.total_collected), 0)
      return Math.round((sum / completed.length) * 100)
    },

    get totalRelevant() {
      return this.recentRuns.reduce((a, r) => a + r.total_relevant, 0)
    },

    destroy() {
      if (this._chart) this._chart.destroy()
    },

    formatDuration,
    formatDate,
    statusLabel,
    statusColor,
  }
}
