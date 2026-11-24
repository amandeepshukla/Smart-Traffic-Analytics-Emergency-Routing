export const LEVEL_COLOR = {
  free: '#22c55e',
  moderate: '#eab308',
  heavy: '#f97316',
  gridlock: '#ef4444',
  unknown: '#64748b',
}

export const levelOf = (c) => {
  if (c == null) return 'unknown'
  if (c < 0.3) return 'free'
  if (c < 0.6) return 'moderate'
  if (c < 0.85) return 'heavy'
  return 'gridlock'
}

export const colorOf = (c) => LEVEL_COLOR[levelOf(c)]

export const fmtTime = (s) => {
  if (s == null) return '—'
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return m > 0 ? `${m}m ${String(sec).padStart(2, '0')}s` : `${sec}s`
}

export const pct = (c) => (c == null ? '—' : `${Math.round(c * 100)}%`)
