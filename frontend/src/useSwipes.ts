import { useEffect, useRef, useState } from 'react'
import { loadHiringTasks, loadSwipes, saveSwipe, undoSwipe, writeHiringTask, type HiringTask, type SwipeDecision } from './api'

export const swipeChangeEvent = 'recruitifi:swipe-change'
export const demoPollInterval = 12000

export function interestedCandidates(swipes: SwipeDecision[], companyId: number) {
  return new Set(swipes.filter((row) => row.company_id === companyId && row.actor === 'talent' && row.decision === 'like').map((row) => row.candidate_id))
}

export function useSwipes(active = true) {
  const [swipes, setSwipes] = useState<SwipeDecision[]>([])
  const [tasks, setTasks] = useState<HiringTask[]>([])
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const revision = useRef(0)

  useEffect(() => {
    if (!active) return
    let controller: AbortController | undefined
    setReady(false)
    const refresh = () => {
      const version = revision.current
      controller?.abort()
      const request = new AbortController()
      controller = request
      Promise.all([loadSwipes(request.signal), loadHiringTasks(request.signal)]).then(([values, assignments]) => {
        if (!request.signal.aborted && version === revision.current) { setTasks(assignments); setSwipes(values); setReady(true); setError('') }
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
    revision.current += 1
    setSwipes((previous) => [...previous.filter((row) => !(row.candidate_id === saved.candidate_id && row.company_id === saved.company_id && row.actor === saved.actor)), saved])
    window.dispatchEvent(new Event(swipeChangeEvent))
    return saved.mutual_match
  }

  async function undo(value: Pick<SwipeDecision, 'actor' | 'candidate_id' | 'company_id'>) {
    await undoSwipe(value)
    revision.current += 1
    setSwipes((previous) => previous.filter((row) => !(row.candidate_id === value.candidate_id && row.company_id === value.company_id && row.actor === value.actor)))
    window.dispatchEvent(new Event(swipeChangeEvent))
  }

  async function saveTask(path: string, method: 'POST' | 'PUT', body: object) {
    const saved = await writeHiringTask(path, method, body)
    revision.current += 1
    setTasks((previous) => previous.some(({ id }) => id === saved.id)
      ? previous.map((task) => task.id === saved.id ? saved : task)
      : [saved, ...previous])
  }

  return { undo, swipes, tasks, saveTask, ready, error, retry: () => setAttempt((value) => value + 1), decide }
}

export type SwipeStore = ReturnType<typeof useSwipes>
