import { useEffect, useState } from 'react'
import { loadSwipes, saveSwipe, undoSwipe, type SwipeDecision } from './api'

export const swipeChangeEvent = 'recruitifi:swipe-change'
export const demoPollInterval = 12000

export function interestedCandidates(swipes: SwipeDecision[], companyId: number) {
  return new Set(swipes.filter((row) => row.company_id === companyId && row.actor === 'talent' && row.decision === 'like').map((row) => row.candidate_id))
}

export function useSwipes(active = true) {
  const [swipes, setSwipes] = useState<SwipeDecision[]>([])
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!active) return
    let controller: AbortController | undefined
    setReady(false)
    const refresh = () => {
      controller?.abort()
      const request = new AbortController()
      controller = request
      loadSwipes(request.signal).then((values) => {
        if (!request.signal.aborted) { setSwipes(values); setReady(true); setError('') }
      }).catch(() => {
        if (!request.signal.aborted) setError('Could not load saved likes. Retry to start discovering.')
      })
    }
    refresh()
    const timer = window.setInterval(refresh, demoPollInterval)
    window.addEventListener(swipeChangeEvent, refresh)
    return () => { controller?.abort(); window.clearInterval(timer); window.removeEventListener(swipeChangeEvent, refresh) }
  }, [attempt, active])
  async function decide(value: SwipeDecision) {
    const saved = await saveSwipe(value)
    setSwipes((previous) => [...previous.filter((row) => !(row.candidate_id === saved.candidate_id && row.company_id === saved.company_id && row.actor === saved.actor)), saved])
    window.dispatchEvent(new Event(swipeChangeEvent))
    return saved.mutual_match
  }
  async function undo(value: Pick<SwipeDecision, 'actor' | 'candidate_id' | 'company_id'>) {
    await undoSwipe(value)
    setSwipes((previous) => previous.filter((row) => !(row.candidate_id === value.candidate_id && row.company_id === value.company_id && row.actor === value.actor)))
    window.dispatchEvent(new Event(swipeChangeEvent))
  }
  return { undo, swipes, ready, error, retry: () => setAttempt((value) => value + 1), decide }
}

export type SwipeStore = ReturnType<typeof useSwipes>
