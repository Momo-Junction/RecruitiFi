import { useEffect, useRef, useState } from 'react'
import { loadNotifications, markNotificationRead, type NotificationInbox } from './api'
import { demoPollInterval, swipeChangeEvent } from './useSwipes'

export function NotificationBell({ recipient, identityId }: { recipient: 'talent' | 'employer'; identityId: number }) {
  // The parent keys this by the selected identity; aborts prevent old inboxes leaking across switches.
  const [open, setOpen] = useState(false)
  const [feed, setFeed] = useState<NotificationInbox>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    let controller: AbortController | undefined
    const refresh = () => {
      controller?.abort()
      const request = new AbortController()
      controller = request
      loadNotifications(recipient, identityId, request.signal).then((next) => {
        if (!request.signal.aborted) { setFeed(next); setError('') }
      }).catch(() => {
        if (!request.signal.aborted) setError('Could not refresh notifications.')
      })
    }
    refresh()
    const timer = window.setInterval(refresh, demoPollInterval)
    window.addEventListener(swipeChangeEvent, refresh)
    return () => { mounted.current = false; controller?.abort(); window.clearInterval(timer); window.removeEventListener(swipeChangeEvent, refresh) }
  }, [recipient, identityId, attempt])

  return <div className="relative shrink-0">
    <button type="button" aria-label={`Notifications${feed ? `, ${feed.unread_count} unread` : ''}`} aria-expanded={open} onClick={() => setOpen((value) => !value)} className="flex cursor-pointer items-center gap-2 rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-espoo hover:bg-mist">
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></svg>
      <span aria-live="polite">{error ? '!' : feed?.unread_count ?? '…'}</span>
    </button>
    {open && <section aria-label="Notifications" className="absolute right-0 z-30 mt-2 max-h-96 w-72 max-w-[80vw] overflow-y-auto rounded-xl border border-slate-200 bg-white p-4 shadow-lg">
      <div className="flex items-center justify-between"><h3 className="font-bold">Notifications</h3><button type="button" className="cursor-pointer text-sm text-espoo underline" onClick={() => setOpen(false)}>Close</button></div>
      <p className="mt-1 text-xs text-slate-500">{recipient === 'talent' ? `Talent #${identityId}` : `Company #${identityId}`} · shared demo inbox</p>
      {error && <p role="alert" className="mt-3 text-sm text-red-800">{error} <button type="button" className="cursor-pointer underline" onClick={() => setAttempt((value) => value + 1)}>Retry</button></p>}
      {!feed && !error && <p role="status" className="mt-3 text-sm text-slate-600">Loading notifications…</p>}
      {feed?.entries.length === 0 && <p className="mt-3 text-sm text-slate-600">No active notifications yet.</p>}
      <ul className="mt-3 space-y-2">{feed?.entries.map((item) => <li key={item.id} className={`rounded-lg border p-3 text-sm ${item.read_at ? 'border-slate-100' : 'border-blue-200 bg-mist'}`}>
        <p className={item.read_at ? '' : 'font-semibold'}>{item.message}</p>
        <time dateTime={item.created_at} className="mt-1 block text-xs text-slate-500">{new Date(item.created_at).toLocaleString()}</time>
        {!item.read_at && <button type="button" disabled={busy} className="mt-2 cursor-pointer text-xs font-semibold text-espoo underline disabled:opacity-50" onClick={async () => {
          setBusy(true)
          try {
            await markNotificationRead(recipient, identityId, item.id)
            if (mounted.current) window.dispatchEvent(new Event(swipeChangeEvent))
          } catch (cause) { if (mounted.current) setError((cause as Error).message) }
          finally { if (mounted.current) setBusy(false) }
        }}>Mark read</button>}
      </li>)}</ul>
    </section>}
  </div>
}
