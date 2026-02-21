import { api } from '../api.js'

export function configPage() {
  return {
    tab: 'sources',
    // Sources
    sources: [],
    sourceFilter: 'all',
    showSourceModal: false,
    editingSourceId: null,
    sourceForm: { name: '', url: '', category: 'eventi', source_type: 'web_page' },
    // Queries
    queries: [],
    queryFilter: 'all',
    showQueryModal: false,
    editingQueryId: null,
    queryForm: { query_text: '', category: 'bandi', max_results: 5 },
    // Settings
    settings: {},
    settingsSaved: false,

    async init() {
      await Promise.all([
        this.loadSources(),
        this.loadQueries(),
        this.loadSettings(),
      ])
    },

    // ----- Sources -----
    async loadSources() {
      try { this.sources = await api.getSources() }
      catch { window.toast.error('Errore caricamento link diretti') }
    },
    openAddSource() {
      this.editingSourceId = null
      this.sourceForm = { name: '', url: '', category: 'eventi', source_type: 'web_page' }
      this.showSourceModal = true
    },
    openEditSource(s) {
      this.editingSourceId = s.id
      this.sourceForm = {
        name: s.name, url: s.url,
        category: s.category, source_type: s.source_type,
      }
      this.showSourceModal = true
    },
    async saveSource() {
      try {
        if (this.editingSourceId) {
          await api.updateSource(this.editingSourceId, this.sourceForm)
          window.toast.success('Link aggiornato')
        } else {
          await api.createSource(this.sourceForm)
          window.toast.success('Link aggiunto')
        }
        this.showSourceModal = false
        await this.loadSources()
      } catch (e) {
        window.toast.error(e.message || 'Errore nel salvataggio')
      }
    },
    async toggleSource(s) {
      try {
        const updated = await api.toggleSource(s.id)
        s.is_active = updated.is_active
      } catch { window.toast.error('Errore nel cambio stato') }
    },
    async deleteSource(s) {
      if (!confirm('Eliminare questo link?')) return
      try {
        await api.deleteSource(s.id)
        this.sources = this.sources.filter(x => x.id !== s.id)
        window.toast.success('Link eliminato')
      } catch { window.toast.error('Errore nell\'eliminazione') }
    },
    get filteredSources() {
      if (this.sourceFilter === 'all') return this.sources
      return this.sources.filter(s => s.category === this.sourceFilter)
    },

    // ----- Queries -----
    async loadQueries() {
      try { this.queries = await api.getQueries() }
      catch { window.toast.error('Errore caricamento ricerche') }
    },
    openAddQuery() {
      this.editingQueryId = null
      this.queryForm = { query_text: '', category: 'bandi', max_results: 5 }
      this.showQueryModal = true
    },
    openEditQuery(q) {
      this.editingQueryId = q.id
      this.queryForm = {
        query_text: q.query_text,
        category: q.category, max_results: q.max_results,
      }
      this.showQueryModal = true
    },
    async saveQuery() {
      try {
        if (this.editingQueryId) {
          await api.updateQuery(this.editingQueryId, this.queryForm)
          window.toast.success('Ricerca aggiornata')
        } else {
          await api.createQuery(this.queryForm)
          window.toast.success('Ricerca aggiunta')
        }
        this.showQueryModal = false
        await this.loadQueries()
      } catch (e) {
        window.toast.error(e.message || 'Errore nel salvataggio')
      }
    },
    async toggleQuery(q) {
      try {
        const updated = await api.toggleQuery(q.id)
        q.is_active = updated.is_active
      } catch { window.toast.error('Errore nel cambio stato') }
    },
    async deleteQuery(q) {
      if (!confirm('Eliminare questa ricerca?')) return
      try {
        await api.deleteQuery(q.id)
        this.queries = this.queries.filter(x => x.id !== q.id)
        window.toast.success('Ricerca eliminata')
      } catch { window.toast.error('Errore nell\'eliminazione') }
    },
    get filteredQueries() {
      if (this.queryFilter === 'all') return this.queries
      return this.queries.filter(q => q.category === this.queryFilter)
    },

    // ----- Settings -----
    async loadSettings() {
      try { this.settings = await api.getSettings() }
      catch { window.toast.error('Errore caricamento impostazioni') }
    },
    async saveSettings() {
      try {
        this.settings = await api.updateSettings(this.settings)
        this.settingsSaved = true
        window.toast.success('Impostazioni salvate')
        setTimeout(() => this.settingsSaved = false, 2000)
      } catch { window.toast.error('Errore nel salvataggio impostazioni') }
    },

    // ----- Helpers -----
    categoryBadge(cat) {
      const m = {
        eventi: 'bg-violet-50 text-violet-700',
        bandi: 'bg-amber-50 text-amber-700',
        fondi: 'bg-emerald-50 text-emerald-700',
      }
      return m[cat] || 'bg-gray-100 text-gray-600'
    },
    categoryLabel(cat) {
      const m = { eventi: 'Eventi', bandi: 'Bandi', fondi: 'Fondi' }
      return m[cat] || cat
    },
    sourceTypeLabel(t) {
      const m = { rss_feed: 'RSS', web_page: 'Web', tender_portal: 'Portale' }
      return m[t] || t
    },
  }
}
