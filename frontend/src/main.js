import Alpine from 'alpinejs'
import './style.css'

import { agendaPage } from './components/agenda.js'
import { configPage } from './components/config.js'
import { pipelineRunner } from './components/pipeline.js'
import { esecuzioniPage } from './components/esecuzioni.js'
import { detailPage } from './components/detail.js'
import { chatbotPage } from './components/chatbot.js'
import { adminPage } from './components/admin.js'
import { toastContainer } from './components/toast.js'

Alpine.data('agendaPage', agendaPage)
Alpine.data('configPage', configPage)
Alpine.data('pipelineRunner', pipelineRunner)
Alpine.data('esecuzioniPage', esecuzioniPage)
Alpine.data('detailPage', detailPage)
Alpine.data('chatbotPage', chatbotPage)
Alpine.data('adminPage', adminPage)
Alpine.data('toastContainer', toastContainer)

const _icons = {
  agenda: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>',
  esecuzioni: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
  settings: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>',
  search: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>',
  bot: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>',
  admin: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 11c0 1.657-1.79 3-4 3S4 12.657 4 11s1.79-3 4-3 4 1.343 4 3zM20 11c0 1.657-1.79 3-4 3s-4-1.343-4-3 1.79-3 4-3 4 1.343 4 3zM4 19c0-2.21 1.79-4 4-4h1c2.21 0 4 1.79 4 4v1H4v-1zM11 20v-1c0-1.023.304-1.975.826-2.771A3.99 3.99 0 0115 15h1c2.21 0 4 1.79 4 4v1h-9z"/></svg>',
}

const isLoginPage = window.location.pathname === '/login.html'
const isAdminPage = window.location.pathname === '/admin.html'
const token = localStorage.getItem('or-token')
if (!isLoginPage && !token) {
  window.location.href = '/login.html'
}
if (!isLoginPage && token) {
  import('./api.js').then(async ({ api }) => {
    try {
      const me = await api.authMe()
      localStorage.setItem('or-user', JSON.stringify(me))
      if (isAdminPage && me.role !== 'admin') {
        window.location.href = '/'
      }
    } catch {
      localStorage.removeItem('or-token')
      localStorage.removeItem('or-user')
      window.location.href = '/login.html'
    }
  })
}

Alpine.data('loginPage', () => ({
  username: '',
  password: '',
  error: '',
  loading: false,
  async submit() {
    this.error = ''
    this.loading = true
    try {
      const { api } = await import('./api.js')
      const resp = await api.login(this.username, this.password)
      localStorage.setItem('or-token', resp.token)
      if (resp.username) {
        localStorage.setItem('or-user', JSON.stringify({
          username: resp.username,
          display_name: resp.display_name,
          role: resp.role,
          must_reset_password: !!resp.must_reset_password,
        }))
      } else {
        const me = await api.authMe()
        localStorage.setItem('or-user', JSON.stringify(me))
      }
      const dest = localStorage.getItem('or-onboarding-done') ? '/' : '/?onboarding=1'
      window.location.href = dest
    } catch (e) {
      this.error = e?.message || 'Credenziali non valide'
    } finally {
      this.loading = false
    }
  },
}))

Alpine.data('onboardingCarousel', () => ({
  step: 0,
  visible: new URLSearchParams(window.location.search).has('onboarding') && !localStorage.getItem('or-onboarding-done'),
  slides: [
    {
      icon: '<svg class="h-16 w-16" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>',
      title: 'Benvenuto in Opportunity Radar',
      desc: 'La tua piattaforma enterprise per monitorare bandi di gara, finanziamenti e opportunit\u00e0 di business in modo automatizzato.'
    },
    {
      icon: '<svg class="h-16 w-16" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>',
      title: 'Agenda',
      desc: 'Nell\'Agenda trovi tutte le opportunit\u00e0 trovate. Valuta con pollice su/gi\u00f9, segna le iscrizioni agli eventi e monitora le scadenze.'
    },
    {
      icon: '<svg class="h-16 w-16" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>',
      title: 'Settings e Configurazioni',
      desc: 'In Settings configuri le fonti da monitorare, le query di ricerca, il profilo aziendale, la schedulazione e le notifiche email.'
    },
    {
      icon: '<svg class="h-16 w-16" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>',
      title: 'Bot e Voice Mode',
      desc: 'Usa Opportunity Bot per analizzare risultati, ottenere insight e avviare ricerche tramite chat testuale o conversazione vocale con AI nativa.'
    },
  ],
  next() { if (this.step < this.slides.length - 1) this.step++ },
  prev() { if (this.step > 0) this.step-- },
  dismiss() {
    localStorage.setItem('or-onboarding-done', '1')
    this.visible = false
    const url = new URL(window.location)
    url.searchParams.delete('onboarding')
    window.history.replaceState({}, '', url)
  },
}))

Alpine.data('navbar', () => {
  const path = window.location.pathname
  const user = (() => {
    try { return JSON.parse(localStorage.getItem('or-user') || 'null') } catch { return null }
  })()
  const isAdmin = user?.role === 'admin'
  const links = [
    { href: '/',                    label: 'Agenda',      mobileLabel: 'Agenda',      icon: _icons.agenda,      active: path === '/' || path === '/index.html' },
    { href: '/esecuzioni.html',     label: 'Esecuzioni',  mobileLabel: 'Esecuzioni',  icon: _icons.esecuzioni,  active: path === '/esecuzioni.html' || path.startsWith('/dettaglio') },
    { href: '/configurazioni.html', label: 'Settings',     mobileLabel: 'Settings',    icon: _icons.settings,    active: path === '/configurazioni.html' },
    { href: '/esegui.html',         label: 'Ricerca',      mobileLabel: 'Ricerca',     icon: _icons.search,      active: path === '/esegui.html' },
    { href: '/chatbot.html',        label: 'Bot',          mobileLabel: 'Bot',         icon: _icons.bot,         active: path === '/chatbot.html' },
  ]
  if (isAdmin) {
    links.push({ href: '/admin.html', label: 'Admin', mobileLabel: 'Admin', icon: _icons.admin, active: path === '/admin.html' })
  }
  return {
    mobileOpen: false,
    links,
    userName: user?.display_name || user?.username || '',
    userRole: user?.role || '',
    async logout() {
      try {
        const { api } = await import('./api.js')
        await api.logout()
      } catch { /* noop */ }
      localStorage.removeItem('or-token')
      localStorage.removeItem('or-user')
      window.location.href = '/login.html'
    },
  }
})

Alpine.data('notificationBell', () => ({
  count: 0,
  pulse: false,
  open: false,
  loading: false,
  agendaUnseen: [],
  sharedUnseen: [],
  _interval: null,
  _prevCount: 0,
  _outsideClickHandler: null,

  async init() {
    await this.refresh()
    this._interval = setInterval(() => this.refresh(), 60000)
    this._outsideClickHandler = (event) => {
      if (!this.$el.contains(event.target)) this.open = false
    }
    document.addEventListener('click', this._outsideClickHandler)
  },

  async refresh() {
    try {
      const { api } = await import('./api.js')
      const stats = await api.getAgendaStats()
      this._prevCount = this.count
      this.count = (stats.unseen_count || 0) + (stats.shared_unseen_count || 0)
      if (this.count > this._prevCount && this._prevCount >= 0) {
        this.pulse = true
        setTimeout(() => { this.pulse = false }, 2000)
      }
      if (this.open) await this.loadNotifications(false)
    } catch { /* silent */ }
  },

  async toggleDropdown() {
    this.open = !this.open
    if (this.open) {
      await this.loadNotifications(true)
    }
  },

  async loadNotifications(showLoading = true) {
    if (showLoading) this.loading = true
    try {
      const { api } = await import('./api.js')
      const payload = await api.getAgendaNotifications(12)
      this.agendaUnseen = payload.agenda_unseen || []
      this.sharedUnseen = payload.shared_unseen || []
    } catch {
      this.agendaUnseen = []
      this.sharedUnseen = []
    } finally {
      this.loading = false
    }
  },

  get hasNotifications() {
    return this.agendaUnseen.length > 0 || this.sharedUnseen.length > 0
  },

  async markAllAsSeen() {
    try {
      const { api } = await import('./api.js')
      await Promise.all([
        api.markSeen(null, true),
        api.markSharedSeen(null, true),
      ])
      await this.refresh()
      await this.loadNotifications(false)
    } catch { /* silent */ }
  },

  async openAgendaNotification(item) {
    try {
      const { api } = await import('./api.js')
      await api.markSeen([item.id], false)
    } catch { /* noop */ }
    this.open = false
    await this.refresh()
    window.location.href = '/?tab=pending'
  },

  async openSharedNotification(share) {
    try {
      const { api } = await import('./api.js')
      await api.markSharedSeen([share.share_id], false)
    } catch { /* noop */ }
    this.open = false
    await this.refresh()
    window.location.href = '/?tab=shared'
  },

  formatWhen(value) {
    if (!value) return ''
    const dt = new Date(value)
    if (Number.isNaN(dt.getTime())) return ''
    return dt.toLocaleString('it-IT', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  },

  destroy() {
    if (this._interval) clearInterval(this._interval)
    if (this._outsideClickHandler) {
      document.removeEventListener('click', this._outsideClickHandler)
    }
  },
}))

Alpine.start()
