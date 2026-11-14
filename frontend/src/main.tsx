import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { loadDirectory } from './api'
import { TalentWorkspace } from './TalentWorkspace'
import { EmployerWorkspace } from './EmployerWorkspace'
import { OrganizerAudit } from './OrganizerAudit'
import './index.css'
import { useSwipes } from './useSwipes'

const roles = [
  { id: 'talent', label: 'Talent View' },
  { id: 'employer', label: 'Employer View' },
  { id: 'organizer', label: 'Espoo Organizer Audit' },
] as const

const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6'

function App() {
  const swipeStore = useSwipes()
  const [role, setRole] = useState<(typeof roles)[number]['id']>('talent')
  const [directory, setDirectory] = useState<Awaited<ReturnType<typeof loadDirectory>>>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    loadDirectory(controller.signal).then(setDirectory).catch(() => {
      if (!controller.signal.aborted) setError('Could not load the directory. Check that the API is running.')
    })
    return () => controller.abort()
  }, [attempt])


  return (
    <div className="min-h-screen bg-[#f6f8fc] text-ink">
      <header>
        <div className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-5 py-4 sm:px-8">
            <p className="font-bold text-espoo">City of Espoo <span className="ml-2 font-medium text-slate-500">/ TalentMatch</span></p>
            <nav aria-label="Demo roles" className="flex flex-wrap gap-1 rounded-xl bg-mist p-1">
              {roles.map(({ id, label }) => (
                <button key={id} type="button" aria-pressed={role === id} onClick={() => setRole(id)}
                  className={`cursor-pointer rounded-lg px-3 py-2 text-sm font-semibold ${role === id ? 'bg-espoo text-white' : 'text-espoo hover:bg-white'}`}>
                  {label}
                </button>
              ))}
            </nav>
          </div>
        </div>
        <div className="event-hero relative isolate overflow-hidden text-white">
          <div className="relative z-10 mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-10">
            <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">{roles.find(({ id }) => id === role)?.label}</h1>
            <p className="mt-4 max-w-md text-base leading-relaxed text-blue-100 sm:text-lg">
              {role === 'talent' && 'See how your skills and evidence match Espoo employers.'}
              {role === 'employer' && 'Set role requirements and review eligible candidate signals.'}
              {role === 'organizer' && 'Review event metrics, scoring inputs and meeting controls.'}
            </p>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-10">
        {role === 'organizer' && <OrganizerAudit />}
        {error && role !== 'organizer' && (
          <div className={card}>
            <p role="alert">{error}</p>
            <button type="button" className="mt-3 cursor-pointer font-semibold text-espoo underline" onClick={() => {
              setError('')
              setAttempt(attempt + 1)
            }}>Retry</button>
          </div>
        )}
        {role !== 'organizer' && !directory && !error && <p role="status">Loading directory…</p>}
        {directory && (
          <div hidden={role !== 'talent'}><TalentWorkspace {...directory} swipeStore={swipeStore} /></div>
        )}
        {directory && (
          <div hidden={role !== 'employer'}>
            <EmployerWorkspace swipeStore={swipeStore} companies={directory.companies} skills={directory.skills} onCompanySaved={(company) => {
              setDirectory((current) => current && {
                ...current,
                companies: current.companies.map((previous) => previous.id === company.id ? company : previous),
              })
            }} />
          </div>
        )}
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
