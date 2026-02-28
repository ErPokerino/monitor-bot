import { api } from '../api.js'

export function adminPage() {
  return {
    loading: true,
    creating: false,
    actioningUserId: null,
    users: [],
    overview: null,
    form: {
      username: '',
      name: '',
      password: '',
      role: 'user',
      must_reset_password: false,
    },

    async init() {
      this.loading = true
      try {
        const me = await api.authMe()
        if (me.role !== 'admin') {
          window.location.href = '/'
          return
        }
        await Promise.all([this.loadOverview(), this.loadUsers()])
      } catch {
        window.location.href = '/login.html'
      } finally {
        this.loading = false
      }
    },

    async loadOverview() {
      try {
        this.overview = await api.getAdminOverview()
      } catch {
        window.toast.error('Errore caricamento overview admin')
      }
    },

    async loadUsers() {
      try {
        this.users = await api.getAdminUsers()
      } catch {
        window.toast.error('Errore caricamento utenti')
      }
    },

    async createUser() {
      if (this.creating) return
      this.creating = true
      try {
        const payload = {
          username: this.form.username.trim(),
          name: this.form.name.trim() || null,
          password: this.form.password,
          role: this.form.role,
          must_reset_password: !!this.form.must_reset_password,
        }
        await api.createAdminUser(payload)
        window.toast.success('Utente creato con successo')
        this.form = {
          username: '',
          name: '',
          password: '',
          role: 'user',
          must_reset_password: false,
        }
        await Promise.all([this.loadOverview(), this.loadUsers()])
      } catch (e) {
        window.toast.error(e.message || 'Errore creazione utente')
      } finally {
        this.creating = false
      }
    },

    async deactivateUser(user) {
      if (this.actioningUserId) return
      if (!confirm(`Disattivare l'utente ${user.username}?`)) return
      this.actioningUserId = user.id
      try {
        await api.deleteAdminUser(user.id)
        window.toast.success('Utente disattivato')
        await Promise.all([this.loadOverview(), this.loadUsers()])
      } catch (e) {
        window.toast.error(e.message || 'Errore disattivazione utente')
      } finally {
        this.actioningUserId = null
      }
    },

    async activateUser(user) {
      if (this.actioningUserId) return
      this.actioningUserId = user.id
      try {
        await api.activateAdminUser(user.id)
        window.toast.success('Utente riattivato')
        await Promise.all([this.loadOverview(), this.loadUsers()])
      } catch (e) {
        window.toast.error(e.message || 'Errore riattivazione utente')
      } finally {
        this.actioningUserId = null
      }
    },

    async hardDeleteUser(user) {
      if (this.actioningUserId) return
      const confirmed = confirm(
        `Eliminare definitivamente ${user.username}? Questa azione rimuove utente, sessioni e dati associati.`,
      )
      if (!confirmed) return
      this.actioningUserId = user.id
      try {
        await api.hardDeleteAdminUser(user.id)
        window.toast.success('Utente eliminato definitivamente')
        await Promise.all([this.loadOverview(), this.loadUsers()])
      } catch (e) {
        window.toast.error(e.message || 'Errore eliminazione utente')
      } finally {
        this.actioningUserId = null
      }
    },

    roleBadge(role) {
      return role === 'admin' ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-600'
    },

    formatDate(value) {
      if (!value) return 'Mai'
      const d = new Date(value)
      return d.toLocaleString('it-IT')
    },
  }
}
