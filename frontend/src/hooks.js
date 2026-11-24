import { useEffect, useRef, useState } from 'react'
import { api, wsUrl } from './api'

/**
 * Live traffic state. Uses the websocket; if it is unavailable (some hosts block
 * websockets) it transparently falls back to polling /api/state every 2 s.
 * status: 'connecting' | 'live' | 'polling' | 'offline'
 */
export function useTrafficStream() {
  const [state, setState] = useState(null)
  const [status, setStatus] = useState('connecting')

  useEffect(() => {
    let ws
    let pollTimer
    let retryTimer
    let closed = false
    let retries = 0

    const poll = async () => {
      try {
        setState(await api.state())
        setStatus('polling')
      } catch {
        setStatus('offline')
      }
    }
    const startPolling = () => {
      if (pollTimer) return
      poll()
      pollTimer = setInterval(poll, 2000)
    }
    const stopPolling = () => {
      clearInterval(pollTimer)
      pollTimer = undefined
    }

    const connect = () => {
      if (closed) return
      try {
        ws = new WebSocket(wsUrl())
      } catch {
        startPolling()
        return
      }
      ws.onopen = () => {
        retries = 0
        stopPolling()
        setStatus('live')
      }
      ws.onmessage = (e) => {
        try {
          setState(JSON.parse(e.data))
          setStatus('live')
        } catch {
          /* ignore malformed frame */
        }
      }
      ws.onclose = () => {
        if (closed) return
        startPolling()
        retries += 1
        retryTimer = setTimeout(connect, Math.min(15000, 1000 * 2 ** retries))
      }
      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      closed = true
      clearTimeout(retryTimer)
      stopPolling()
      ws && ws.close()
    }
  }, [])

  return { state, status }
}

/** Debounced route preview for the dispatch panel. */
export function useRoutePreview(origin, destination, refreshKey) {
  const [preview, setPreview] = useState({ loading: false, data: null, error: null })
  const seq = useRef(0)

  useEffect(() => {
    if (!origin) return undefined
    const id = ++seq.current
    setPreview((p) => ({ ...p, loading: true }))
    const t = setTimeout(async () => {
      try {
        const data = await api.route(origin, destination)
        if (id === seq.current) setPreview({ loading: false, data, error: null })
      } catch (e) {
        if (id === seq.current) setPreview({ loading: false, data: null, error: e.message })
      }
    }, 250)
    return () => clearTimeout(t)
  }, [origin, destination, refreshKey])

  return preview
}
