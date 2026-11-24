// All backend access lives here. VITE_API_URL is empty in dev (proxy) and set in production.
export const API = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

export const wsUrl = () => {
  const base = API || window.location.origin
  return base.replace(/^http/, 'ws') + '/ws'
}

async function request(path, options) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail || detail
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.status === 204 ? null : res.json()
}

const post = (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  state: () => request('/api/state'),
  route: (source, destination) =>
    request(`/api/route?source=${encodeURIComponent(source)}${destination ? `&destination=${encodeURIComponent(destination)}` : ''}`),
  dispatch: (origin, destination, sim_speed) => post('/api/dispatch', { origin, destination: destination || null, sim_speed }),
  cancelMission: (id) => request(`/api/missions/${id}`, { method: 'DELETE' }),
  closeJunction: (node_id) => post('/api/closures', { node_id }),
  reopenJunction: (node_id) => request(`/api/closures/${node_id}`, { method: 'DELETE' }),
  setCongestion: (node_id, level) => post('/api/simulate/congestion', { node_id, level }),
  setCamera: (node_id, online) => post('/api/simulate/camera', { node_id, online }),
  reset: () => post('/api/simulate/reset', {}),
}

export const snapshotUrl = (id, t) => `${API}/api/cameras/${id}/snapshot.jpg?t=${t}`
export const streamUrl = (id) => `${API}/api/cameras/${id}/stream`
