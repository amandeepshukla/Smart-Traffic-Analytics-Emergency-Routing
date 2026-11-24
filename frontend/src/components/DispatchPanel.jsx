import { useState } from 'react'
import { api } from '../api'
import { useRoutePreview } from '../hooks'
import { fmtTime } from '../format'

export default function DispatchPanel({ network, origin, setOrigin, closures, notify }) {
  const [destination, setDestination] = useState('')
  const [speed, setSpeed] = useState(6)
  const [busy, setBusy] = useState(false)
  const preview = useRoutePreview(origin, destination, closures.join(','))

  const junctions = network.filter((n) => n.kind === 'junction')
  const hospitals = network.filter((n) => n.kind === 'hospital')

  const dispatch = async () => {
    setBusy(true)
    try {
      await api.dispatch(origin, destination, speed)
      notify('Ambulance dispatched', 'ok')
    } catch (e) {
      notify(e.message, 'err')
    } finally {
      setBusy(false)
    }
  }

  const opt = preview.data?.optimal
  const saved = preview.data?.time_saved_s ?? 0

  return (
    <section className="panel">
      <header className="panel-h">
        <h2>Dispatch ambulance</h2>
      </header>

      <label className="field">
        <span>Incident location</span>
        <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
          <option value="">Select a junction…</option>
          {junctions.map((n) => (
            <option key={n.id} value={n.id}>{n.id} · {n.name}</option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Destination</span>
        <select value={destination} onChange={(e) => setDestination(e.target.value)}>
          <option value="">Auto — fastest hospital</option>
          {hospitals.map((n) => (
            <option key={n.id} value={n.id}>{n.id} · {n.name}</option>
          ))}
        </select>
      </label>

      <label className="field">
        <span>Simulation speed</span>
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          {[1, 3, 6, 12, 30].map((s) => (
            <option key={s} value={s}>{s}× {s === 1 ? '(real time)' : ''}</option>
          ))}
        </select>
      </label>

      {origin && (
        <div className="preview">
          {preview.error && <p className="err">{preview.error}</p>}
          {opt && !preview.error && (
            <>
              <div className="preview-main">
                <strong>{fmtTime(opt.eta_s)}</strong>
                <span>{opt.distance_km} km · {opt.path.length - 1} roads</span>
              </div>
              <p className="route-names">{opt.path_names.join(' → ')}</p>
              {saved > 1 && <p className="saved">⚡ {fmtTime(saved)} faster than the shortest-distance route</p>}
            </>
          )}
        </div>
      )}

      <button className="btn danger wide" disabled={!origin || busy || !!preview.error} onClick={dispatch}>
        {busy ? 'Dispatching…' : '🚑 Dispatch'}
      </button>
    </section>
  )
}
