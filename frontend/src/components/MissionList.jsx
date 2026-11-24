import { api } from '../api'
import { fmtTime } from '../format'

export default function MissionList({ missions, nodes, notify }) {
  const name = (id) => nodes[id]?.name || id

  const cancel = async (id) => {
    try {
      await api.cancelMission(id)
    } catch (e) {
      notify(e.message, 'err')
    }
  }

  return (
    <section className="panel">
      <header className="panel-h">
        <h2>Missions</h2>
        <span className="count">{missions.filter((m) => m.status === 'enroute').length} active</span>
      </header>

      {missions.length === 0 && <p className="muted">No ambulances on the road. Dispatch one to see live re-routing.</p>}

      <ul className="missions">
        {missions.map((m) => (
          <li key={m.id} className={`mission ${m.status}`}>
            <div className="mission-top">
              <span className="mission-route">
                {name(m.origin)} <i>→</i> {m.destination_name}
              </span>
              <button className="icon-btn" onClick={() => cancel(m.id)} aria-label="Remove mission">✕</button>
            </div>

            {m.status === 'arrived' ? (
              <p className="arrived">✔ Arrived in {fmtTime(m.elapsed_s)} (sim time)</p>
            ) : (
              <div className="mission-stats">
                <div><b>{fmtTime(m.eta_s)}</b><span>ETA</span></div>
                <div><b>{m.remaining_km} km</b><span>left</span></div>
                <div><b>{m.reroutes}</b><span>reroutes</span></div>
                <div><b>{m.waiting_s > 0 ? `${Math.ceil(m.waiting_s)}s` : '—'}</b><span>at signal</span></div>
              </div>
            )}

            {m.time_saved_s > 1 && <p className="saved">⚡ saved {fmtTime(m.time_saved_s)} vs shortest route</p>}

            <ul className="events">
              {m.events.slice(-3).map((e, i) => (
                <li key={i}>{e.msg}</li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  )
}
