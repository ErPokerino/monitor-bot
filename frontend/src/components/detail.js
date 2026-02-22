import { api } from '../api.js'
import { formatDuration, formatDate, statusLabel, statusColor } from './helpers.js'

export function detailPage() {
  return {
    loading: true,
    run: null,
    results: [],
    typeFilter: 'all',
    catFilter: 'all',
    deadlineFrom: '',
    deadlineTo: '',
    notFound: false,

    async init() {
      const params = new URLSearchParams(window.location.search)
      const id = params.get('id')
      if (!id) { this.notFound = true; this.loading = false; return }
      try {
        const data = await api.getRun(id)
        this.run = data
        this.results = (data.results || []).sort((a, b) => b.relevance_score - a.relevance_score)
      } catch {
        this.notFound = true
      } finally {
        this.loading = false
      }
    },

    get filteredResults() {
      return this.results.filter(r => {
        if (this.typeFilter !== 'all' && r.opportunity_type !== this.typeFilter) return false
        if (this.catFilter !== 'all' && r.category !== this.catFilter) return false
        if (this.deadlineFrom && r.deadline && r.deadline < this.deadlineFrom) return false
        if (this.deadlineTo && r.deadline && r.deadline > this.deadlineTo) return false
        return true
      })
    },

    scoreBadge(score) {
      if (score >= 8) return 'bg-emerald-100 text-emerald-800'
      if (score >= 6) return 'bg-accent-100 text-accent-800'
      if (score >= 4) return 'bg-amber-100 text-amber-800'
      return 'bg-gray-100 text-gray-600'
    },
    typeDot(t) {
      const m = { Bando: 'bg-amber-500', Evento: 'bg-violet-500', Concorso: 'bg-blue-500' }
      return m[t] || 'bg-gray-400'
    },
    isDeadlinePast(d) {
      if (!d) return false
      return new Date(d) < new Date()
    },
    formatDeadline(d) {
      if (!d) return ''
      return new Date(d).toLocaleDateString('it-IT', {
        day: '2-digit', month: '2-digit', year: 'numeric',
      })
    },
    formatValue(v, cur) {
      if (!v) return ''
      return new Intl.NumberFormat('it-IT', {
        style: 'decimal', maximumFractionDigits: 0,
      }).format(v) + ' ' + (cur || 'EUR')
    },

    _buildRows() {
      return this.filteredResults.map(r => [
        r.title, r.opportunity_type, r.category, r.relevance_score,
        r.deadline || '', r.contracting_authority || '', r.country || '', r.source_url || '',
      ])
    },

    async exportCsv() {
      const header = ['Titolo', 'Tipo', 'Categoria', 'Score', 'Scadenza', 'Ente', 'Paese', 'URL']
      const rows = [header, ...this._buildRows()]
      const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
      const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
      this._download(blob, `risultati_run_${this.run?.id || 'export'}.csv`)
    },

    async exportHtml() {
      const rows = this._buildRows()
      const header = ['Titolo', 'Tipo', 'Categoria', 'Score', 'Scadenza', 'Ente', 'Paese', 'URL']
      const title = `Risultati del ${formatDate(this.run?.started_at)}`
      const tableRows = rows.map(r => {
        const cells = r.map((c, i) => {
          if (i === 7 && c) return `<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb"><a href="${c}" target="_blank" style="color:#0ea5e9">${c}</a></td>`
          return `<td style="padding:8px 12px;border-bottom:1px solid #e5e7eb">${c}</td>`
        }).join('')
        return `<tr>${cells}</tr>`
      }).join('\n')
      const html = `<!DOCTYPE html>
<html lang="it">
<head><meta charset="UTF-8"><title>${title} - Opportunity Radar</title>
<style>body{font-family:Inter,system-ui,sans-serif;margin:40px;color:#1e3a5f}
h1{font-size:22px;margin-bottom:8px}
.meta{color:#6b7280;font-size:14px;margin-bottom:24px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{background:#f3f4f6;padding:10px 12px;text-align:left;font-weight:600;border-bottom:2px solid #d1d5db}
tr:hover{background:#f9fafb}</style></head>
<body>
<h1>${title}</h1>
<p class="meta">${this.filteredResults.length} risultati &middot; ${this.run?.total_relevant || 0} rilevanti</p>
<table><thead><tr>${header.map(h => `<th>${h}</th>`).join('')}</tr></thead>
<tbody>${tableRows}</tbody></table>
</body></html>`
      const blob = new Blob([html], { type: 'text/html;charset=utf-8;' })
      this._download(blob, `risultati_run_${this.run?.id || 'export'}.html`)
    },

    async exportPdf() {
      try {
        const { jsPDF } = await import('jspdf')
        const { default: autoTable } = await import('jspdf-autotable')
        const doc = new jsPDF({ orientation: 'landscape' })
        const title = `Risultati del ${formatDate(this.run?.started_at)}`
        doc.setFontSize(16)
        doc.text(title, 14, 18)
        doc.setFontSize(10)
        doc.setTextColor(100)
        doc.text(`${this.filteredResults.length} risultati - Opportunity Radar`, 14, 26)
        autoTable(doc, {
          startY: 32,
          head: [['Titolo', 'Tipo', 'Cat.', 'Score', 'Scadenza', 'Ente', 'Paese']],
          body: this.filteredResults.map(r => [
            r.title?.substring(0, 60) || '',
            r.opportunity_type || '',
            r.category || '',
            r.relevance_score,
            r.deadline ? this.formatDeadline(r.deadline) : '',
            r.contracting_authority?.substring(0, 30) || '',
            r.country || '',
          ]),
          styles: { fontSize: 8, cellPadding: 3 },
          headStyles: { fillColor: [30, 58, 95], fontSize: 9 },
          alternateRowStyles: { fillColor: [248, 250, 252] },
        })
        doc.save(`risultati_run_${this.run?.id || 'export'}.pdf`)
      } catch (e) {
        console.error('PDF export failed:', e)
        window.toast.error('Errore nella generazione del PDF')
      }
    },

    _download(blob, filename) {
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    },

    formatDuration,
    formatDate,
    statusLabel,
    statusColor,
  }
}
