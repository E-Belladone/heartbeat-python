/** Mirrors heartbeat.models.PublicPresence on the proxy side. */
export interface PublicPresence {
  online: boolean
  /** M18 aggregated tier: a strong signal fired recently (active),
   *  devices merely reachable (around), or neither (away). */
  activity: 'active' | 'around' | 'away'
  last_seen: number | null
  last_seen_relative: number
  longest_absence: number
  total_beats: number
  device_count: number
  /** Strong signals (start/pulse) only: stops mark absence, not activity. */
  total_strong_signals: number
  last_strong_signal: number | null
  last_strong_signal_relative: number
  uptime: number
}

export async function fetchPresence(): Promise<PublicPresence> {
  const res = await fetch('/api/presence')
  if (!res.ok) {
    throw new Error(`presence fetch failed: ${res.status}`)
  }
  return res.json()
}

export const POLL_MS = 30_000
const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 60_000

/** Exponential backoff for websocket reconnects, capped at one minute. */
export function reconnectDelay(attempt: number): number {
  return Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS)
}

/**
 * Live presence: websocket first, polling fallback while disconnected.
 * Calls `onUpdate` for every payload and `onError` when even polling
 * fails. Returns a stop function.
 */
export function watchPresence(
  onUpdate: (p: PublicPresence) => void,
  onError: () => void,
): () => void {
  let ws: WebSocket | null = null
  let pollId: ReturnType<typeof setInterval> | null = null
  let retryId: ReturnType<typeof setTimeout> | null = null
  let attempt = 0
  let stopped = false

  async function poll() {
    try {
      onUpdate(await fetchPresence())
    } catch {
      onError()
    }
  }

  function startPolling() {
    if (pollId !== null) return
    poll()
    pollId = setInterval(poll, POLL_MS)
  }

  function stopPolling() {
    if (pollId !== null) clearInterval(pollId)
    pollId = null
  }

  function connect() {
    if (stopped) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${location.host}/api/presence/ws`)
    // reset backoff on a live handshake, not only on the first message: a
    // proxy that is up but momentarily data-starved (db blip) opens the socket
    // without sending, and that success should still clear the backoff
    ws.onopen = () => {
      attempt = 0
    }
    ws.onmessage = (ev) => {
      let payload: PublicPresence
      try {
        payload = JSON.parse(ev.data)
      } catch {
        return // a malformed frame must not throw out of the handler
      }
      stopPolling()
      onUpdate(payload)
    }
    // onerror always ends in onclose; one path for both
    ws.onclose = () => {
      if (stopped) return
      startPolling()
      retryId = setTimeout(connect, reconnectDelay(attempt++))
    }
  }

  connect()
  // first paint should not wait on the websocket handshake: race a
  // one-shot fetch; whichever answers first fills the page
  poll()
  return () => {
    stopped = true
    stopPolling()
    if (retryId !== null) clearTimeout(retryId)
    ws?.close()
  }
}

/** "42" -> "just now", "3700" -> "1 hour ago", ... */
export function relativeTime(seconds: number): string {
  if (seconds < 90) return 'just now'
  const units: [number, string][] = [
    [60 * 60 * 24, 'day'],
    [60 * 60, 'hour'],
    [60, 'minute'],
  ]
  for (const [size, name] of units) {
    if (seconds >= size) {
      const n = Math.floor(seconds / size)
      return `${n} ${name}${n === 1 ? '' : 's'} ago`
    }
  }
  return 'just now'
}
const UNITS: [number, string][] = [
  [365 * 24 * 3600, 'year'],
  [30 * 24 * 3600, 'month'],
  [7 * 24 * 3600, 'week'],
  [24 * 3600, 'day'],
  [3600, 'hour'],
  [60, 'minute'],
  [1, 'second'],
]

/** 3723 -> "1 hour, 2 minutes, and 3 seconds"; 0 -> "just now". */
export function formatDuration(seconds: number): string {
  const parts: string[] = []
  let rest = Math.max(0, Math.floor(seconds))
  for (const [size, name] of UNITS) {
    const n = Math.floor(rest / size)
    if (n > 0) {
      parts.push(`${n} ${name}${n === 1 ? '' : 's'}`)
      rest -= n * size
    }
  }
  if (parts.length === 0) return 'just now'
  if (parts.length === 1) return parts[0]
  if (parts.length === 2) return `${parts[0]} and ${parts[1]}`
  return `${parts.slice(0, -1).join(', ')}, and ${parts[parts.length - 1]}`
}

/** Unix seconds -> "2026-07-09 14:39:43" in the viewer's timezone.

    The zone parameter exists for tests; callers omit it so every visitor
    reads the timestamp in their own local time (sv-SE is the locale whose
    default format happens to be ISO-shaped). */
export function formatDateLocal(epochSeconds: number, timeZone?: string): string {
  return new Intl.DateTimeFormat('sv-SE', {
    dateStyle: 'short',
    timeStyle: 'medium',
    timeZone,
  }).format(new Date(epochSeconds * 1000))
}

const SHORT_UNITS: [number, string][] = [
  [365 * 24 * 3600, 'y'],
  [30 * 24 * 3600, 'mo'],
  [7 * 24 * 3600, 'w'],
  [24 * 3600, 'd'],
  [3600, 'h'],
  [60, 'm'],
  [1, 's'],
]

/** Compact two-unit duration: 93784 -> "1d 2h"; 0 -> "0s". */
export function formatDurationShort(seconds: number): string {
  let rest = Math.max(0, Math.floor(seconds))
  const parts: string[] = []
  for (const [size, suffix] of SHORT_UNITS) {
    if (parts.length === 2) break
    const n = Math.floor(rest / size)
    if (n > 0) {
      parts.push(`${n}${suffix}`)
      rest -= n * size
    }
  }
  return parts.length ? parts.join(' ') : '0s'
}
