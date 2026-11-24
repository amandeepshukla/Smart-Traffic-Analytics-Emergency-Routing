import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { useTrafficStream } from './hooks'
import { LEVEL_COLOR, LEVEL_COLOR as C, pct } from './format'
import MapView from './components/MapView'
import CameraGrid from './components/CameraGrid'
import DispatchPanel from './components/DispatchPanel'
import MissionList from './components/MissionList'
import NodePanel from './components/NodePanel'

const STATUS_TEXT = {
  connecting: 'Connecting…',
  live: 'Live · websocket',
  polling: 'Live · polling',
  offline: 'Backend offline',
}

function Kpi({ label, value, sub, color }) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <strong style={color ? { color } : undefined}>{value}</strong>
      {sub && <small>{sub}</small>}
    </div>
  )
}

export default function App() {
  const { state, status } = useTrafficStream()
  const [selected, setSelected] = useState(null)
  const [origin, setOrigin] = useState('')
  const [toast, setToast] = useState(null)
  const toastTimer = useRef()

  const notify = useCallback((msg, kind = 'ok') => {
    setToast({ msg, kind })
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 3500)
  }, [])

  useEffect(() => () => clearTimeout(toastTimer.current), [])

  const nodesById = state ? Object.fromEntries(state.nodes.map((n) => [n.id, n])) : {}
  const camsById = state ? Object.fromEntries(state.cameras.map((c) => [c.node_id, c])) : {}
  const s = state?.summary

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">✚</span>
          <div>
            <h1>Smart Traffic &amp; Emergency Routing</h1>
            <p>Live congestion from camera feeds → fastest clear route for ambulances</p>
          </div>
        </div>
        <div className="top-actions">
          {state && (
            <button
              className="btn ghost"
              onClick={() => api.reset().then(() => notify('Demo reset', 'ok')).catch((e) => notify(e.message, 'err'))}
              title="Clear missions, closures, jams and restore cameras"
            >
              Reset demo
            </button>
          )}
          <span className={`pill ${status}`}>
            <i /> {STATUS_TEXT[status]}
          </span>
        </div>
      </header>

      <section className="kpis">
        <Kpi label="Cameras online" value={s ? `${s.cameras_online}/${s.cameras_total}` : '—'} sub={s && s.cameras_offline ? `${s.cameras_offline} offline` : 'all healthy'} color={s && s.cameras_offline ? C.heavy : undefined} />
        <Kpi label="City congestion" value={s ? pct(s.avg_congestion) : '—'} sub={s?.avg_level} color={s ? LEVEL_COLOR[s.avg_level] : undefined} />
        <Kpi label="Vehicles in view" value={s ? s.vehicles_in_view : '—'} sub="across all feeds" />
        <Kpi label="Active ambulances" value={s ? s.active_missions : '—'} color={s?.active_missions ? '#ef4444' : undefined} />
        <Kpi label="Closed junctions" value={s ? s.closed_junctions : '—'} />
      </section>

      {status === 'offline' && !state && (
        <div className="banner">
          Cannot reach the backend. Start it with <code>uvicorn app.main:app --port 8000</code> (or set <code>VITE_API_URL</code>).
        </div>
      )}

      <main className="layout">
        <section className="panel map-panel">
          <header className="panel-h">
            <h2>Live network map</h2>
            <div className="legend">
              {['free', 'moderate', 'heavy', 'gridlock'].map((l) => (
                <span key={l}><i style={{ background: LEVEL_COLOR[l] }} />{l}</span>
              ))}
              <span><i className="dash" />shortest route</span>
            </div>
          </header>
          <MapView state={state} selected={selected} onSelect={setSelected} />
        </section>

        <aside className="side">
          {selected && nodesById[selected] && (
            <NodePanel
              node={nodesById[selected]}
              camera={camsById[selected]}
              closed={nodesById[selected].closed}
              jammed={state.overrides[selected] != null}
              onClose={() => setSelected(null)}
              onDispatchFrom={(id) => setOrigin(id)}
              notify={notify}
            />
          )}
          {state && (
            <DispatchPanel network={state.nodes} origin={origin} setOrigin={setOrigin} closures={state.closures} notify={notify} />
          )}
          {state && <MissionList missions={state.missions} nodes={nodesById} notify={notify} />}
        </aside>
      </main>

      <section className="panel cams">
        <header className="panel-h">
          <h2>Camera status</h2>
          <span className="count">click a feed to inspect</span>
        </header>
        {state ? <CameraGrid cameras={state.cameras} selected={selected} onSelect={setSelected} /> : <p className="muted">No data yet.</p>}
      </section>

      {toast && <div className={`toast ${toast.kind}`}>{toast.msg}</div>}
    </div>
  )
}
