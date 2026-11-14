import { useState, type FormEvent } from 'react'
import type { Company, HiringTask } from './api'
import type { SwipeStore } from './useSwipes'

const card = 'rounded-xl border border-slate-200 bg-white p-4'
const input = 'w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm'
const button = 'rounded-lg bg-espoo px-4 py-2 text-sm font-semibold text-white enabled:cursor-pointer enabled:hover:bg-blue-900 disabled:opacity-50'

export function EmployerTasks({ name, score, mutual, candidateId, companyId, store }: {
  name: string; score?: number; mutual: boolean; candidateId: number; companyId: number; store: SwipeStore
}) {
  const [assigning, setAssigning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const tasks = store.tasks.filter((task) => task.company_id === companyId && task.candidate_id === candidateId)

  async function save(operation: () => Promise<void>, message: string) {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await operation()
      setNotice(message)
    } catch (cause) {
      setError((cause as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const title = String(form.get('title') ?? '').trim()
    const description = String(form.get('description') ?? '').trim()
    if (!title || !description) {
      setError('Enter a task title and description.')
      return
    }
    await save(async () => {
      await store.saveTask('', 'POST', { candidate_id: candidateId, company_id: companyId, title, description })
      setAssigning(false)
    }, 'Task assigned. The candidate can see it in Hiring updates.')
  }

  return <article className={card}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="font-bold">{name}</h3>
      {score !== undefined && <span className="rounded-lg bg-mist px-2 py-1 text-sm font-semibold text-espoo">{Number(score.toFixed(1))}% fit</span>}
    </div>
    {mutual && <p className="mt-1 text-sm font-semibold text-emerald-800">Mutual match</p>}
    {tasks.length > 0 && <ul className="mt-4 space-y-3">
      {tasks.map((task) => <li key={task.id} className="rounded-lg bg-slate-50 p-3">
        <TaskDetails task={task} />
        {task.submission_url && !task.verified && <button type="button" className={button + ' mt-3'} disabled={busy} onClick={() => {
          void save(() => store.saveTask('/' + task.id + '/verification/' + companyId, 'PUT', { url: task.submission_url }), 'Submission verified.')
        }}>Mark verified</button>}
      </li>)}
    </ul>}
    {assigning ? <form className="mt-4" onSubmit={assign}>
      <fieldset disabled={busy} className="grid gap-3">
        <label className="grid gap-1 text-sm font-semibold">Task title
          <input className={input} name="title" maxLength={120} required />
        </label>
        <label className="grid gap-1 text-sm font-semibold">Task description
          <textarea className={input} name="description" rows={4} maxLength={4000} required />
        </label>
        <div className="flex flex-wrap gap-3">
          <button className={button}>{busy ? 'Saving…' : 'Send task'}</button>
          <button type="button" className="cursor-pointer text-sm text-espoo underline" onClick={() => { setAssigning(false); setError('') }}>Cancel</button>
        </div>
      </fieldset>
    </form> : <button type="button" className={button + ' mt-4'} disabled={busy} onClick={() => { setAssigning(true); setNotice('') }}>Assign task</button>}
    {notice && <p role="status" className="mt-3 text-sm text-emerald-800">{notice}</p>}
    {error && <p role="alert" className="mt-3 text-sm text-red-800">{error}</p>}
  </article>
}

function TaskDetails({ task }: { task: HiringTask }) {
  return <>
    <h4 className="break-words text-sm font-bold">{task.title}</h4>
    <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-700">{task.description}</p>
    <p className="mt-2 text-sm font-semibold text-espoo">{task.verified ? 'Verified' : task.submission_url ? 'Submitted · awaiting verification' : 'Awaiting submission'}</p>
    {task.submission_url && <a className="mt-1 inline-block text-sm font-semibold text-espoo underline"
      href={task.submission_url} target="_blank" rel="noopener noreferrer">Open submitted work ↗</a>}
  </>
}

function CandidateTask({ task, candidateId, store }: { task: HiringTask; candidateId: number; store: SwipeStore }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  return <li className="rounded-lg bg-slate-50 p-3">
    <TaskDetails task={task} />
    {!task.verified && <form className="mt-3" onSubmit={async (event) => {
      event.preventDefault()
      const url = new FormData(event.currentTarget).get('url')
      setBusy(true)
      setError('')
      try { await store.saveTask('/' + task.id + '/submission/' + candidateId, 'PUT', { url }) }
      catch (cause) { setError((cause as Error).message) }
      finally { setBusy(false) }
    }}>
      <fieldset disabled={busy} className="grid gap-2">
        <label className="grid gap-1 text-sm font-semibold">Link to your completed work
          <input className={input} name="url" type="url" pattern="https?://.+" maxLength={2083}
            defaultValue={task.submission_url ?? ''} placeholder="https://…" required />
        </label>
        <button className={button + ' justify-self-start'}>{busy ? 'Submitting…' : task.submission_url ? 'Update link' : 'Submit work'}</button>
      </fieldset>
    </form>}
    {error && <p role="alert" className="mt-2 text-sm text-red-800">{error}</p>}
  </li>
}

export function CandidateUpdates({ candidateId, companies, store }: {
  candidateId: number; companies: Company[]; store: SwipeStore
}) {
  const decisions = store.swipes.filter((row) => row.actor === 'employer' && row.candidate_id === candidateId)
  const interestedIn = new Set(store.swipes.filter((row) => row.candidate_id === candidateId && row.actor === 'talent' && row.decision === 'like').map((row) => row.company_id))
  const tasks = store.tasks.filter((task) => task.candidate_id === candidateId)
  const companiesWithUpdates = companies.filter(({ id }) =>
    decisions.some((row) => row.company_id === id) || tasks.some((task) => task.company_id === id))

  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" aria-labelledby="updates-heading">
    <h2 id="updates-heading" className="text-xl font-bold">Hiring updates</h2>
    {store.error && <p role="alert" className="mt-3 text-sm text-red-800">{store.error} <button type="button" className="cursor-pointer underline" onClick={store.retry}>Retry</button></p>}
    {!store.ready && !store.error && <p role="status" className="mt-3 text-sm">Loading updates…</p>}
    {store.ready && companiesWithUpdates.length === 0 && <p className="mt-3 text-sm text-slate-600">Employer decisions and assigned tasks will appear here.</p>}
    <div className="mt-4 space-y-4">
      {companiesWithUpdates.map(({ id, name }) => {
        const decision = decisions.find((row) => row.company_id === id)
        const assignments = tasks.filter((task) => task.company_id === id)
        return <article className={card} key={id}>
          <h3 className="font-bold">{name}</h3>
          {decision && <p className="mt-1 text-sm text-slate-700">{decision.decision === 'like'
            ? name + ' shortlisted you and may contact you about next steps.'
            : name + ' decided to move forward with other candidates.'}</p>}
          {decision?.decision === 'like' && interestedIn.has(id) && <p className="mt-1 text-sm font-semibold text-emerald-800">Mutual match</p>}
          {assignments.length > 0 && <ul className="mt-3 space-y-3">
            {assignments.map((task) => <CandidateTask key={task.id + '-' + (task.submission_url ?? '')} task={task} candidateId={candidateId} store={store} />)}
          </ul>}
        </article>
      })}
    </div>
  </section>
}
