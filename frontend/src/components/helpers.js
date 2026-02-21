/**
 * Shared formatting helpers used across multiple components.
 */

export function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return '-'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return s > 0 ? `${m}m ${s}s` : `${m}m`
}

export function formatDate(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return d.toLocaleDateString('it-IT', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function formatDateShort(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return d.toLocaleDateString('it-IT', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  })
}

export function statusLabel(status) {
  const map = {
    completed: 'Completato',
    running: 'In corso',
    failed: 'Errore',
    cancelled: 'Annullato',
  }
  return map[status] || status
}

export function statusColor(status) {
  const map = {
    completed: 'bg-emerald-50 text-emerald-700',
    running: 'bg-accent-50 text-accent-700',
    failed: 'bg-red-50 text-red-700',
    cancelled: 'bg-amber-50 text-amber-700',
  }
  return map[status] || 'bg-gray-100 text-gray-600'
}
