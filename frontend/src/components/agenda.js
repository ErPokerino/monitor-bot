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
    shareModalOpen: false,
    shareItemTarget: null,
    shareSearch: '',
    shareCandidates: [],
    shareSelectedUser: null,
    shareNote: '',
    shareLoadingUsers: false,
    _shareSearchTimer: null,
    _shareReqId: 0,

    // Touch tracking
    _touchStartX: 0,
    _touchItemId: null,

    async init() {
      const initialTab = new URLSearchParams(window.location.search).get('tab')
      if (['pending', 'interested', 'shared', 'past_events'].includes(initialTab)) {
        this.tab = initialTab
      }
      await this.loadAll()
    },

    async loadAll() {
      this.loading = true
      try {
        const expiringPromise = api.getAgendaExpiring(this.expiringDays)
        let items = []
        if (this.tab === 'shared') {
          const shared = await api.getSharedAgenda()
          items = shared.map(s => ({
            ...s.item,
            _shared: {
              share_id: s.share_id,
              shared_by_username: s.shared_by_username,
              shared_by_display_name: s.shared_by_display_name,
              note: s.note,
              shared_at: s.shared_at,
              is_seen: s.is_seen,
            },
          }))
          if (this.filterType) items = items.filter(i => i.opportunity_type === this.filterType)
          if (this.filterCategory) items = items.filter(i => i.category === this.filterCategory)
          if (this.search) {
            const q = this.search.toLowerCase()
            items = items.filter(i => (i.title || '').toLowerCase().includes(q) || (i.description || '').toLowerCase().includes(q))
          }
          if (this.sort === 'relevance_score') {
            items.sort((a, b) => (b.relevance_score || 0) - (a.relevance_score || 0))
          } else if (this.sort === 'deadline') {
            items.sort((a, b) => {
              if (!a.deadline && !b.deadline) return 0
              if (!a.deadline) return 1
              if (!b.deadline) return -1
              return new Date(a.deadline) - new Date(b.deadline)
            })
          } else {
            items.sort((a, b) => new Date(b.first_seen_at) - new Date(a.first_seen_at))
          }
          await api.markSharedSeen(null, true)
        } else {
          items = await api.getAgenda({
            tab: this.tab,
            type: this.filterType || undefined,
            category: this.filterCategory || undefined,
            enrolled: this.filterEnrolled,
            search: this.search || undefined,
            sort: this.sort,
          })
        }
        const expiring = await expiringPromise
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

    async openShareModal(item) {
      this.shareItemTarget = item
      this.shareSearch = ''
      this.shareCandidates = []
      this.shareSelectedUser = null
      this.shareNote = ''
      this.shareModalOpen = true
      await this.searchShareUsers('')
    },

    closeShareModal() {
      this.shareModalOpen = false
      this.shareItemTarget = null
      this.shareSearch = ''
      this.shareCandidates = []
      this.shareSelectedUser = null
      this.shareNote = ''
      if (this._shareSearchTimer) {
        clearTimeout(this._shareSearchTimer)
        this._shareSearchTimer = null
      }
    },

    onShareSearchInput() {
      if (this._shareSearchTimer) clearTimeout(this._shareSearchTimer)
      this._shareSearchTimer = setTimeout(() => {
        this.searchShareUsers(this.shareSearch)
      }, 180)
    },

    async searchShareUsers(query) {
      const reqId = ++this._shareReqId
      this.shareLoadingUsers = true
      try {
        const users = await api.searchUsers(query?.trim() || '', 30)
        if (reqId !== this._shareReqId) return
        this.shareCandidates = users
        if (
          this.shareSelectedUser
          && !users.some((u) => u.id === this.shareSelectedUser.id)
        ) {
          this.shareSelectedUser = null
        }
      } catch (e) {
        if (reqId === this._shareReqId) {
          this.shareCandidates = []
          window.toast.error(e.message || 'Errore nel caricamento utenti')
        }
      } finally {
        if (reqId === this._shareReqId) this.shareLoadingUsers = false
      }
    },

    selectShareUser(user) {
      this.shareSelectedUser = user
    },

    async confirmShareItem() {
      if (!this.shareItemTarget) return
      if (!this.shareSelectedUser) {
        window.toast.error('Seleziona un utente con cui condividere')
        return
      }
      const note = this.shareNote.trim() || null
      try {
        await api.shareAgendaItem(this.shareItemTarget.id, this.shareSelectedUser.username, note)
        window.toast.success(`Elemento condiviso con ${this.shareSelectedUser.display_name || this.shareSelectedUser.username}`)
        this.closeShareModal()
      } catch (e) {
        window.toast.error(e.message || 'Errore nella condivisione')
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
