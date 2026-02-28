import { api } from '../api.js'

export function configPage() {
  return {
    tab: 'sources',
    isAdmin: false,
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
    competencyTags: [],
    newCompetency: '',

    async init() {
      try {
        const user = JSON.parse(localStorage.getItem('or-user') || 'null')
        this.isAdmin = user?.role === 'admin'
      } catch { this.isAdmin = false }
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
    get allSourcesActive() {
      return this.sources.length > 0 && this.sources.every(s => s.is_active)
    },
    async toggleAllSources(active) {
      try {
        await api.toggleAllSources(active)
        this.sources.forEach(s => s.is_active = active)
        window.toast.success(active ? 'Tutti i link attivati' : 'Tutti i link disattivati')
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
    get allQueriesActive() {
      return this.queries.length > 0 && this.queries.every(q => q.is_active)
    },
    async toggleAllQueries(active) {
      try {
        await api.toggleAllQueries(active)
        this.queries.forEach(q => q.is_active = active)
        window.toast.success(active ? 'Tutte le ricerche attivate' : 'Tutte le ricerche disattivate')
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
      try {
        this.settings = await api.getSettings()
        if (this.settings.scheduler_enabled == null) this.settings.scheduler_enabled = '1'
        this._syncTagsFromSettings()
      } catch { window.toast.error('Errore caricamento impostazioni') }
    },
    _syncTagsFromSettings() {
      const raw = this.settings.company_competencies || ''
      this.competencyTags = raw.split(',').map(t => t.trim()).filter(Boolean)
    },
    _syncSettingsFromTags() {
      this.settings.company_competencies = this.competencyTags.join(',')
    },
    addCompetency() {
      const val = this.newCompetency.trim()
      if (!val) return
      if (!this.competencyTags.includes(val)) {
        this.competencyTags.push(val)
        this._syncSettingsFromTags()
      }
      this.newCompetency = ''
    },
    removeCompetency(idx) {
      this.competencyTags.splice(idx, 1)
      this._syncSettingsFromTags()
    },
    async saveSettings() {
      try {
        this._syncSettingsFromTags()
        this.settings.scheduler_enabled = this.schedulerEnabled ? '1' : '0'
        const payload = {}
        const userKeys = [
          'relevance_threshold',
          'company_name',
          'company_sector',
          'company_competencies',
          'company_budget_min',
          'company_budget_max',
          'company_regions',
          'company_description',
          'search_scope_description',
        ]
        if (this.isAdmin) {
          Object.assign(payload, this.settings)
        } else {
          for (const key of userKeys) payload[key] = this.settings[key]
        }
        this.settings = await api.updateSettings(payload)
        this._syncTagsFromSettings()
        this.settingsSaved = true
        window.toast.success('Impostazioni salvate')
        setTimeout(() => this.settingsSaved = false, 2000)
      } catch { window.toast.error('Errore nel salvataggio impostazioni') }
    },

    get schedulerEnabled() {
      const value = String(this.settings.scheduler_enabled ?? '1').trim().toLowerCase()
      return !['0', 'false', 'off', 'no', ''].includes(value)
    },

    toggleSchedulerEnabled() {
      this.settings.scheduler_enabled = this.schedulerEnabled ? '0' : '1'
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
    schedulerDays: [
      { value: '1', label: 'Lunedì' },
      { value: '2', label: 'Martedì' },
      { value: '3', label: 'Mercoledì' },
      { value: '4', label: 'Giovedì' },
      { value: '5', label: 'Venerdì' },
      { value: '6', label: 'Sabato' },
      { value: '0', label: 'Domenica' },
    ],
    schedulerHours: Array.from({ length: 24 }, (_, i) => ({
      value: String(i),
      label: String(i).padStart(2, '0') + ':00',
    })),
  }
}
