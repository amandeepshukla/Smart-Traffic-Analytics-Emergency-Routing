import { useEffect, useState } from 'react'
import { snapshotUrl } from '../api'
import { LEVEL_COLOR, pct } from '../format'

/** Image that refreshes in the background and swaps only once the new frame has loaded (no flicker). */
export function LiveImage({ nodeId, everyMs = 1500, alt }) {
  const [src, setSrc] = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      const img = new Image()
      const url = snapshotUrl(nodeId, Date.now())
      img.onload = () => !cancelled && setSrc(url)
      img.src = url
    }
    load()
    const t = setInterval(load, everyMs)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [nodeId, everyMs])

  return src ? <img src={src} alt={alt} loading="lazy" /> : <div className="thumb-placeholder">connecting…</div>
}

const STATUS_LABEL = { online: 'LIVE', calibrating: 'CALIBRATING', offline: 'OFFLINE' }

export default function CameraGrid({ cameras, selected, onSelect }) {
  return (
    <div className="cam-grid">
      {cameras.map((c) => {
        const col = LEVEL_COLOR[c.level] || LEVEL_COLOR.unknown
        return (
          <button
            key={c.node_id}
            className={`cam-card ${selected === c.node_id ? 'is-selected' : ''} st-${c.status}`}
            onClick={() => onSelect(c.node_id === selected ? null : c.node_id)}
          >
            <div className="cam-thumb">
              <LiveImage nodeId={c.node_id} alt={`Camera ${c.node_id}`} />
              <span className={`cam-badge ${c.status}`}>{STATUS_LABEL[c.status] || c.status}</span>
            </div>
            <div className="cam-meta">
              <span className="cam-name">
                <b>{c.node_id}</b> {c.name}
              </span>
              <span className="cam-stat" style={{ color: col }}>
                {c.count == null ? '—' : `${c.count} veh`} · {pct(c.congestion)}
              </span>
            </div>
            <div className="cam-bar">
              <i style={{ width: `${Math.round((c.congestion ?? 0) * 100)}%`, background: col }} />
            </div>
          </button>
        )
      })}
    </div>
  )
}
