import { api } from '../api.js'

function daysUntil(dateStr) {
  if (!dateStr) return null
  const d = new Date(dateStr + 'T00:00:00')
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  return Math.ceil((d - now) / 86400000)
}

function deadlineLabel(dateStr) {
  const days = daysUntil(dateStr)
  if (days === null) return ''
  if (days < 0) return 'Scaduto'
  if (days === 0) return 'Scade oggi'
  if (days === 1) return 'Scade domani'
  return `Scade tra ${days}gg`
}

function deadlineColor(dateStr) {
  const days = daysUntil(dateStr)
  if (days === null) return ''
  if (days <= 0) return 'bg-red-100 text-red-700'
  if (days <= 7) return 'bg-red-50 text-red-600'
  if (days <= 14) return 'bg-amber-50 text-amber-600'
  if (days <= 30) return 'bg-yellow-50 text-yellow-700'
  return 'bg-gray-100 text-gray-600'
}

function typeColor(type) {
  const m = {
    Bando: 'bg-blue-100 text-blue-700',
    Evento: 'bg-purple-100 text-purple-700',
    Concorso: 'bg-teal-100 text-teal-700',
  }
  return m[type] || 'bg-gray-100 text-gray-600'
}

function categoryColor(cat) {
  const m = {
    SAP: 'bg-blue-50 text-blue-600',
    Data: 'bg-emerald-50 text-emerald-600',
    AI: 'bg-violet-50 text-violet-600',
    Cloud: 'bg-sky-50 text-sky-600',
    Other: 'bg-gray-50 text-gray-500',
  }
  return m[cat] || 'bg-gray-50 text-gray-500'
}

function formatDeadline(dateStr) {
  if (!dateStr) return 'Nessuna scadenza'
  return new Date(dateStr + 'T00:00:00').toLocaleDateString('it-IT', {
    day: '2-digit', month: 'long', year: 'numeric',
  })
}

function formatColor(fmt) {
  const m = {
    'In presenza': 'bg-orange-50 text-orange-700',
    'Streaming': 'bg-cyan-50 text-cyan-700',
    'On demand': 'bg-indigo-50 text-indigo-700',
  }
  return m[fmt] || 'bg-gray-100 text-gray-600'
}

function costColor(cost) {
  const m = {
    'Gratuito': 'bg-green-50 text-green-700',
    'A pagamento': 'bg-rose-50 text-rose-700',
    'Su invito': 'bg-amber-50 text-amber-700',
  }
  return m[cost] || 'bg-gray-100 text-gray-600'
}

function isUrlLike(s) {
  if (!s) return false
  if (/^https?:\/\//.test(s)) return true
  return !s.includes(' ') && s.includes('.')
}

export function agendaPage() {
  return {
    loading: true,
    items: [],
    expiring: [],
    tab: 'pending',
    filterType: '',
    filterCategory: '',
    filterEnrolled: null,
    search: '',
    sort: 'first_seen_at',
    expiringDays: 30,
    animatingId: null,
    animatingDir: null,

    // Touch tracking
    _touchStartX: 0,
    _touchItemId: null,

    async init() {
      await this.loadAll()
    },

    async loadAll() {
      this.loading = true
      try {
        const [items, expiring] = await Promise.all([
          api.getAgenda({
            tab: this.tab,
            type: this.filterType || undefined,
            category: this.filterCategory || undefined,
            enrolled: this.filterEnrolled,
            search: this.search || undefined,
            sort: this.sort,
          }),
          api.getAgendaExpiring(this.expiringDays),
        ])
        this.items = items
        this.expiring = expiring
      } catch {
        window.toast.error('Errore nel caricamento dell\'agenda')
      } finally {
        this.loading = false
      }
    },

    async switchTab(t) {
      this.tab = t
      await this.loadAll()
    },

    async applyFilters() {
      await this.loadAll()
    },

    async evaluate(id, evaluation) {
      this.animatingId = id
      this.animatingDir = evaluation === 'interested' ? 'right' : 'left'
      await new Promise(r => setTimeout(r, 300))
      try {
        await api.evaluateItem(id, evaluation)
        this.items = this.items.filter(i => i.id !== id)
        window.toast.success(evaluation === 'interested' ? 'Aggiunto ai preferiti' : 'Elemento scartato')
      } catch {
        window.toast.error('Errore nella valutazione')
      } finally {
        this.animatingId = null
        this.animatingDir = null
      }
    },

    async toggleEnroll(item) {
      try {
        const updated = await api.enrollItem(item.id, !item.is_enrolled)
        Object.assign(item, updated)
        window.toast.success(updated.is_enrolled ? 'Iscrizione registrata' : 'Iscrizione rimossa')
      } catch {
        window.toast.error('Errore nell\'aggiornamento')
      }
    },

    async submitFeedback(item, recommend, returnNextYear) {
      try {
        const updated = await api.feedbackItem(item.id, recommend, returnNextYear)
        Object.assign(item, updated)
        window.toast.success('Feedback salvato')
      } catch {
        window.toast.error('Errore nel salvataggio del feedback')
      }
    },

    handleTouchStart(e, id) {
      this._touchStartX = e.touches[0].clientX
      this._touchItemId = id
    },

    handleTouchEnd(e) {
      if (this._touchItemId === null) return
      const dx = e.changedTouches[0].clientX - this._touchStartX
      if (Math.abs(dx) > 80) {
        this.evaluate(this._touchItemId, dx > 0 ? 'interested' : 'rejected')
      }
      this._touchItemId = null
    },

    daysUntil,
    deadlineLabel,
    deadlineColor,
    typeColor,
    categoryColor,
    formatDeadline,
    formatColor,
    costColor,
    isUrlLike,
  }
}
