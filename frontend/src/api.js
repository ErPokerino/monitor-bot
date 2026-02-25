/**
 * Centralised API client for all backend communication.
 * Every fetch call goes through this module for consistent
 * error handling and DRY request logic.
 */

class ApiError extends Error {
  constructor(status, detail) {
    super(detail)
    this.status = status
  }
}

async function request(method, path, body = null) {
  const opts = { method, headers: {} }
  const token = localStorage.getItem('or-token')
  if (token) opts.headers['Authorization'] = `Bearer ${token}`
  if (body !== null) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(body)
  }
  const resp = await fetch(`/api${path}`, opts)
  if (resp.status === 401 && !path.startsWith('/auth/')) {
    localStorage.removeItem('or-token')
    window.location.href = '/login.html'
    throw new ApiError(401, 'Not authenticated')
  }
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const data = await resp.json()
      detail = data.detail || detail
    } catch { /* ignore parse errors */ }
    throw new ApiError(resp.status, detail)
  }
  if (resp.status === 204) return null
  return resp.json()
}

export const api = {
  getAgenda:     (params = {}) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) { if (v != null && v !== '') q.set(k, v) }
    return request('GET', `/agenda?${q}`)
  },
  getAgendaStats:()            => request('GET', '/agenda/stats'),
  getAgendaExpiring:(days=30)  => request('GET', `/agenda/expiring?days=${days}`),
  getAgendaPastEvents:()       => request('GET', '/agenda/past-events'),
  evaluateItem:  (id, evaluation) => request('PATCH', `/agenda/${id}/evaluate`, { evaluation }),
  enrollItem:    (id, is_enrolled) => request('PATCH', `/agenda/${id}/enroll`, { is_enrolled }),
  feedbackItem:  (id, recommend, return_next_year) => request('PATCH', `/agenda/${id}/feedback`, { recommend, return_next_year }),
  markSeen:      (ids = null, all = false) => request('POST', '/agenda/mark-seen', { ids, all }),

  getSources:    ()            => request('GET', '/sources'),
  createSource:  (d)           => request('POST', '/sources', d),
  updateSource:  (id, d)       => request('PATCH', `/sources/${id}`, d),
  toggleSource:  (id)          => request('POST', `/sources/${id}/toggle`),
  toggleAllSources: (active)   => request('POST', '/sources/toggle-all', { active }),
  deleteSource:  (id)          => request('DELETE', `/sources/${id}`),

  getQueries:    ()            => request('GET', '/queries'),
  createQuery:   (d)           => request('POST', '/queries', d),
  updateQuery:   (id, d)       => request('PATCH', `/queries/${id}`, d),
  toggleQuery:   (id)          => request('POST', `/queries/${id}/toggle`),
  toggleAllQueries: (active)   => request('POST', '/queries/toggle-all', { active }),
  deleteQuery:   (id)          => request('DELETE', `/queries/${id}`),

  getRuns:       (limit = 50)  => request('GET', `/runs?limit=${limit}`),
  getRun:        (id)          => request('GET', `/runs/${id}`),
  getRunStatus:  ()            => request('GET', '/runs/status'),
  getRunProgress:(id)          => request('GET', `/runs/${id}/progress`),
  startRun:      ()            => request('POST', '/runs/start'),
  stopRun:       ()            => request('POST', '/runs/stop'),
  deleteRun:     (id)          => request('DELETE', `/runs/${id}`),
  deleteRunsBatch: (ids)       => request('POST', '/runs/delete-batch', { ids }),

  getSettings:   ()            => request('GET', '/settings'),
  updateSettings:(d)           => request('PUT', '/settings', d),

  chatMessage:   (message, { useAgenda = false, runId = null } = {}) => request('POST', '/chat/message', { message, run_id: runId, use_agenda: useAgenda }),
  chatReset:     ()            => request('DELETE', '/chat/history'),
  chatStatus:    ()            => request('GET', '/chat/status'),

  login:         (username, password) => request('POST', '/auth/login', { username, password }),
  authMe:        ()            => request('GET', '/auth/me'),
}

export { ApiError }
