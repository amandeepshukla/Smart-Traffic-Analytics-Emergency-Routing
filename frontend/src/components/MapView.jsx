import { colorOf, LEVEL_COLOR } from '../format'

const W = 100
const H = 70

function Ambulance({ x, y }) {
  return (
    <g transform={`translate(${x} ${y})`} className="amb">
      <circle r="4.2" className="amb-pulse" />
      <circle r="2.6" fill="#ef4444" stroke="#fff" strokeWidth="0.5" />
      <path d="M-1.4 -0.45h1v-1h0.8v1h1v0.8h-1v1h-0.8v-1h-1z" fill="#fff" />
    </g>
  )
}

export default function MapView({ state, selected, onSelect }) {
  if (!state) return <div className="map-empty">Waiting for the backend…</div>
  const nodes = Object.fromEntries(state.nodes.map((n) => [n.id, n]))
  const active = state.missions.filter((m) => m.status === 'enroute')

  return (
    <svg className="map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Live road network map">
      <defs>
        <pattern id="grid" width="5" height="5" patternUnits="userSpaceOnUse">
          <path d="M5 0H0V5" fill="none" stroke="#1b2433" strokeWidth="0.15" />
        </pattern>
      </defs>
      <rect width={W} height={H} fill="url(#grid)" />

      {/* roads: casing + congestion colour */}
      {state.edges.map((e) => {
        const a = nodes[e.a]
        const b = nodes[e.b]
        return (
          <g key={`${e.a}-${e.b}`}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#0b0f17" strokeWidth="1.9" strokeLinecap="round" />
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={colorOf(e.congestion)} strokeWidth="1.05" strokeLinecap="round" opacity="0.92" />
          </g>
        )
      })}

      {/* the naive shortest-distance route, for comparison */}
      {active.map((m) => {
        const same = m.baseline_path.join() === m.path.join()
        if (same) return null
        const pts = m.baseline_path.map((id) => `${nodes[id].x},${nodes[id].y}`).join(' ')
        return <polyline key={`b-${m.id}`} points={pts} className="route-baseline" />
      })}

      {/* planned emergency routes */}
      {active.map((m) => {
        const pts = [`${m.position.x},${m.position.y}`, ...m.path.slice(1).map((id) => `${nodes[id].x},${nodes[id].y}`)].join(' ')
        return (
          <g key={`r-${m.id}`}>
            <polyline points={pts} className="route-glow" />
            <polyline points={pts} className="route-line" />
          </g>
        )
      })}

      {/* junctions + hospitals */}
      {state.nodes.map((n) => {
        const isSel = selected === n.id
        const col = LEVEL_COLOR[n.level] || LEVEL_COLOR.unknown
        const offline = n.camera_status === 'offline'
        return (
          <g key={n.id} className="node" onClick={() => onSelect(n.id === selected ? null : n.id)} tabIndex={0}
             onKeyDown={(ev) => ev.key === 'Enter' && onSelect(n.id === selected ? null : n.id)}>
            {isSel && <circle cx={n.x} cy={n.y} r="4.6" className="sel-ring" />}
            {n.kind === 'hospital' ? (
              <>
                <rect x={n.x - 3} y={n.y - 3} width="6" height="6" rx="1.4" fill="#0f172a" stroke={col} strokeWidth="0.7" />
                <path d={`M${n.x - 0.5} ${n.y - 1.8}h1v1.3h1.3v1h-1.3v1.3h-1v-1.3h-1.3v-1h1.3z`} fill="#38bdf8" />
              </>
            ) : (
              <>
                <circle cx={n.x} cy={n.y} r="2.5" fill="#0f172a" stroke={col} strokeWidth="0.8" strokeDasharray={offline ? '0.8 0.8' : undefined} />
                <circle cx={n.x} cy={n.y} r="1.1" fill={col} opacity={offline ? 0.3 : 1} />
              </>
            )}
            {n.closed && (
              <path d={`M${n.x - 2} ${n.y - 2}l4 4m0 -4l-4 4`} stroke="#ef4444" strokeWidth="0.9" strokeLinecap="round" />
            )}
            <text x={n.x} y={n.y + 6.2} className="node-label">{n.name}</text>
            <text x={n.x} y={n.y - 4.2} className="node-id">{n.id}</text>
          </g>
        )
      })}

      {active.map((m) => (
        <Ambulance key={`a-${m.id}`} x={m.position.x} y={m.position.y} />
      ))}
    </svg>
  )
}
