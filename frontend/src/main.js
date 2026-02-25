import Alpine from 'alpinejs'
import './style.css'

import { agendaPage } from './components/agenda.js'
import { configPage } from './components/config.js'
import { pipelineRunner } from './components/pipeline.js'
import { esecuzioniPage } from './components/esecuzioni.js'
import { historyPage } from './components/history.js'
import { detailPage } from './components/detail.js'
import { chatbotPage } from './components/chatbot.js'
import { toastContainer } from './components/toast.js'

Alpine.data('agendaPage', agendaPage)
Alpine.data('configPage', configPage)
Alpine.data('pipelineRunner', pipelineRunner)
Alpine.data('esecuzioniPage', esecuzioniPage)
Alpine.data('historyPage', historyPage)
Alpine.data('detailPage', detailPage)
Alpine.data('chatbotPage', chatbotPage)
Alpine.data('toastContainer', toastContainer)

const _icons = {
  agenda: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>',
  esecuzioni: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
  settings: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>',
  search: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>',
  bot: '<svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>',
}

const isLoginPage = window.location.pathname === '/login.html'
if (!isLoginPage && !localStorage.getItem('or-token')) {
  window.location.href = '/login.html'
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
      const dest = localStorage.getItem('or-onboarding-done') ? '/' : '/?onboarding=1'
      window.location.href = dest
    } catch (e) {
      this.error = 'Credenziali non valide'
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
  return {
    mobileOpen: false,
    links: [
      { href: '/',                    label: 'Agenda',      mobileLabel: 'Agenda',      icon: _icons.agenda,      active: path === '/' || path === '/index.html' },
      { href: '/esecuzioni.html',     label: 'Esecuzioni',  mobileLabel: 'Esecuzioni',  icon: _icons.esecuzioni,  active: path === '/esecuzioni.html' || path.startsWith('/dettaglio') },
      { href: '/configurazioni.html', label: 'Settings',     mobileLabel: 'Settings',    icon: _icons.settings,    active: path === '/configurazioni.html' },
      { href: '/esegui.html',         label: 'Ricerca',      mobileLabel: 'Ricerca',     icon: _icons.search,      active: path === '/esegui.html' },
      { href: '/chatbot.html',        label: 'Bot',          mobileLabel: 'Bot',         icon: _icons.bot,         active: path === '/chatbot.html' },
    ],
  }
})

Alpine.data('notificationBell', () => ({
  count: 0,
  pulse: false,
  _interval: null,
  _prevCount: 0,

  async init() {
    await this.refresh()
    this._interval = setInterval(() => this.refresh(), 60000)
  },

  async refresh() {
    try {
      const { api } = await import('./api.js')
      const stats = await api.getAgendaStats()
      this._prevCount = this.count
      this.count = stats.unseen_count
      if (this.count > this._prevCount && this._prevCount >= 0) {
        this.pulse = true
        setTimeout(() => { this.pulse = false }, 2000)
      }
    } catch { /* silent */ }
  },

  goToAgenda() {
    if (window.location.pathname === '/' || window.location.pathname === '/index.html') {
      import('./api.js').then(({ api }) => api.markSeen(null, true))
      this.count = 0
    } else {
      window.location.href = '/'
    }
  },

  destroy() {
    if (this._interval) clearInterval(this._interval)
  },
}))

Alpine.start()
