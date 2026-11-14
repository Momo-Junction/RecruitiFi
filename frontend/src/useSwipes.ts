import { useEffect, useRef, useState } from 'react'
import { loadHiringTasks, loadSwipes, saveSwipe, undoSwipe, writeHiringTask, type HiringTask, type SwipeDecision } from './api'

export function useSwipes() {
  const [swipes, setSwipes] = useState<SwipeDecision[]>([])
  const [tasks, setTasks] = useState<HiringTask[]>([])
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const revision = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    let loading = false

    async function refresh() {
      if (loading) return
      loading = true
      const version = revision.current
      try {
        const [decisions, assignments] = await Promise.all([
          loadSwipes(controller.signal), loadHiringTasks(controller.signal),
        ])
        if (controller.signal.aborted || revision.current !== version) return
        setSwipes(decisions)
        setTasks(assignments)
        setReady(true)
        setError('')
      } catch {
        if (!controller.signal.aborted) setError('Could not refresh hiring updates.')
      } finally {
        loading = false
      }
    }

    void refresh()
    const interval = window.setInterval(refresh, 15000)
    window.addEventListener('focus', refresh)
    return () => {
      controller.abort()
      window.clearInterval(interval)
      window.removeEventListener('focus', refresh)
    }
  }, [attempt])

  async function decide(value: SwipeDecision) {
    const saved = await saveSwipe(value)
    revision.current += 1
    setSwipes((previous) => [...previous.filter((row) => !(row.candidate_id === saved.candidate_id && row.company_id === saved.company_id && row.actor === saved.actor)), saved])
  }

  async function undo(value: Pick<SwipeDecision, 'actor' | 'candidate_id' | 'company_id'>) {
    await undoSwipe(value)
    revision.current += 1
    setSwipes((previous) => previous.filter((row) => !(row.candidate_id === value.candidate_id && row.company_id === value.company_id && row.actor === value.actor)))
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
