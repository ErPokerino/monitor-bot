import Alpine from 'alpinejs'
import './style.css'

import { dashboardPage } from './components/dashboard.js'
import { configPage } from './components/config.js'
import { pipelineRunner } from './components/pipeline.js'
import { historyPage } from './components/history.js'
import { detailPage } from './components/detail.js'
import { toastContainer } from './components/toast.js'

Alpine.data('dashboardPage', dashboardPage)
Alpine.data('configPage', configPage)
Alpine.data('pipelineRunner', pipelineRunner)
Alpine.data('historyPage', historyPage)
Alpine.data('detailPage', detailPage)
Alpine.data('toastContainer', toastContainer)

Alpine.data('navbar', () => {
  const path = window.location.pathname
  return {
    mobileOpen: false,
    links: [
      { href: '/',                    label: 'Dashboard',      active: path === '/' || path === '/index.html' || path.startsWith('/dettaglio') },
      { href: '/configurazioni.html', label: 'Configurazioni', active: path === '/configurazioni.html' },
      { href: '/esegui.html',         label: 'Esegui',         active: path === '/esegui.html' },
    ],
  }
})

Alpine.start()
