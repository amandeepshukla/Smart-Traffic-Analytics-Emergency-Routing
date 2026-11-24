import { useState } from 'react'
import { api, streamUrl } from '../api'
import { LEVEL_COLOR, pct } from '../format'

export default function NodePanel({ node, camera, closed, jammed, onClose, onDispatchFrom, notify }) {
  const [busy, setBusy] = useState(false)
  if (!node) return null

  const run = async (fn, okMsg) => {
    setBusy(true)
    try {
      await fn()
      okMsg && notify(okMsg, 'ok')
    } catch (e) {
      notify(e.message, 'err')
    } finally {
      setBusy(false)
    }
  }

  const isJunction = node.kind === 'junction'
  const col = LEVEL_COLOR[camera?.level] || LEVEL_COLOR.unknown
  const offline = camera?.status === 'offline'

  return (
    <section className="panel node-panel">
      <header className="panel-h">
        <h2>
          {node.id} · {node.name}
        </h2>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          ✕
        </button>
      </header>

      <div className="stream">
        {offline ? <div className="thumb-placeholder">camera offline</div> : <img src={streamUrl(node.id)} alt={`Live feed ${node.id}`} />}
      </div>

      {camera && (
        <dl className="metrics">
          <div><dt>Vehicles</dt><dd>{camera.count ?? '—'}</dd></div>
          <div><dt>Congestion</dt><dd style={{ color: col }}>{pct(camera.congestion)}</dd></div>
          <div><dt>Flow</dt><dd>{camera.flow_per_min != null ? `${camera.flow_per_min}/min` : '—'}</dd></div>
          <div><dt>Detector</dt><dd className="small">{camera.detector}</dd></div>
        </dl>
      )}

      {camera?.lane_density && (
        <div className="lanes">
          {camera.lane_density.map((d, i) => (
            <div key={i} className="lane">
              <span>Lane {i + 1}</span>
              <div className="lane-bar"><i style={{ width: `${d * 100}%`, background: d > 0.8 ? LEVEL_COLOR.gridlock : d > 0.5 ? LEVEL_COLOR.heavy : LEVEL_COLOR.free }} /></div>
              <span>{camera.lane_counts[i]}</span>
            </div>
          ))}
        </div>
      )}

      <div className="btn-row">
        {isJunction && (
          <button className="btn danger" disabled={busy} onClick={() => onDispatchFrom(node.id)}>
            🚑 Dispatch from here
          </button>
        )}
        {isJunction && (
          <button className="btn" disabled={busy} onClick={() => run(() => (closed ? api.reopenJunction(node.id) : api.closeJunction(node.id)), closed ? 'Junction reopened' : 'Junction closed — routes will avoid it')}>
            {closed ? 'Reopen junction' : 'Close junction'}
          </button>
        )}
        <button className="btn" disabled={busy} onClick={() => run(() => api.setCongestion(node.id, jammed ? null : 0.95), jammed ? 'Jam cleared' : 'Simulated jam started')}>
          {jammed ? 'Clear jam' : 'Simulate jam'}
        </button>
        <button className="btn" disabled={busy} onClick={() => run(() => api.setCamera(node.id, offline), offline ? 'Camera back online' : 'Camera taken offline')}>
          {offline ? 'Restore camera' : 'Kill camera'}
        </button>
      </div>
    </section>
  )
}
