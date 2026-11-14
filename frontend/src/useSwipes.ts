import { useEffect, useState } from 'react'
import { loadSwipes, saveSwipe, undoSwipe, type SwipeDecision } from './api'

export function useSwipes() {
  const [swipes, setSwipes] = useState<SwipeDecision[]>([])
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    setReady(false)
    loadSwipes(controller.signal).then((values) => {
      if (!controller.signal.aborted) { setSwipes(values); setReady(true) }
    }).catch(() => {
      if (!controller.signal.aborted) setError('Could not load saved likes. Retry to start discovering.')
    })
    return () => controller.abort()
  }, [attempt])
  // Mirror a decision the server already saved (for example, a meeting request).
  function record(saved: SwipeDecision) {
    setSwipes((previous) => [...previous.filter((row) => !(row.candidate_id === saved.candidate_id && row.company_id === saved.company_id && row.actor === saved.actor)), saved])
  }
  async function decide(value: SwipeDecision) {
    record(await saveSwipe(value))
  }
  async function undo(value: Pick<SwipeDecision, 'actor' | 'candidate_id' | 'company_id'>) {
    await undoSwipe(value)
    setSwipes((previous) => previous.filter((row) => !(row.candidate_id === value.candidate_id && row.company_id === value.company_id && row.actor === value.actor)))
  }
  return { undo, swipes, ready, error, retry: () => setAttempt((value) => value + 1), decide, record }
}

export type SwipeStore = ReturnType<typeof useSwipes>
