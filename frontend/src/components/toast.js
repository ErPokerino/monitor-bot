/**
 * Lightweight toast notification system.
 * Usage: window.toast.success('Message') / window.toast.error('Message')
 */

let _toasts = []
let _nextId = 0
let _alpine = null

export function toastContainer() {
  return {
    toasts: _toasts,
    init() { _alpine = this },
    dismiss(id) {
      this.toasts = this.toasts.filter(t => t.id !== id)
      _toasts = this.toasts
    },
  }
}

function _push(type, message, duration = 4000) {
  const id = ++_nextId
  const t = { id, type, message, leaving: false }
  _toasts.push(t)
  if (_alpine) _alpine.toasts = [..._toasts]
  setTimeout(() => {
    t.leaving = true
    if (_alpine) _alpine.toasts = [..._toasts]
    setTimeout(() => {
      _toasts = _toasts.filter(x => x.id !== id)
      if (_alpine) _alpine.toasts = [..._toasts]
    }, 300)
  }, duration)
}

export const toast = {
  success: (msg) => _push('success', msg),
  error:   (msg) => _push('error', msg, 6000),
  info:    (msg) => _push('info', msg),
}

window.toast = toast
