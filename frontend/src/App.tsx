import { useEffect, useState } from 'react'
import { loadDirectory } from './api'
import { TalentWorkspace } from './TalentWorkspace'
import { EmployerWorkspace } from './EmployerWorkspace'
import { OrganizerWorkspace } from './OrganizerWorkspace'
import { useSwipes } from './useSwipes'
import { useDemoNavigation } from './demoNavigation'

const roles = [
  { id: 'talent', label: 'Talent View' },
  { id: 'employer', label: 'Employer View' },
  { id: 'organizer', label: 'Espoo Organizer' },
] as const

const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6'

export function App() {
  const swipeStore = useSwipes()
  const { role, selectRole } = useDemoNavigation()
  const [directory, setDirectory] = useState<Awaited<ReturnType<typeof loadDirectory>>>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!role) return
    setError('')
    const controller = new AbortController()
    loadDirectory(controller.signal).then(setDirectory).catch(() => {
      if (!controller.signal.aborted) setError('Could not load the directory. Check that the API is running.')
    })
    return () => controller.abort()
  }, [attempt, role])


  return (
    <div className="min-h-screen bg-[#f6f8fc] text-ink">
      <header>
        <div className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-6 sm:px-8">
            <div className="flex items-center gap-4"><span className="brand-orbit" aria-hidden="true" /><p className="text-xl font-bold tracking-tight text-espoo">TalentMatch<span className="block text-xs font-medium tracking-wide text-slate-500">City of Espoo · Event demo</span></p></div>
            {role && <div className="flex items-center gap-4">
              <span className="text-sm font-semibold text-espoo">{roles.find(({ id }) => id === role)?.label}</span>
              <button type="button" onClick={() => selectRole(null)} className="cursor-pointer rounded-lg border border-blue-200 px-4 py-2 text-sm font-semibold text-espoo hover:bg-mist">Switch Role</button>
            </div>}
          </div>
        </div>
        {role && <div className="event-hero relative isolate overflow-hidden text-white">
          <div className="relative z-10 mx-auto grid max-w-6xl items-center gap-8 px-5 py-10 sm:px-8 sm:py-14 lg:grid-cols-[1.2fr_1fr]">
            <div>
            <p className="mb-4 text-sm font-medium text-blue-100">Working life in Espoo</p>
            <h1 className="max-w-lg text-4xl font-medium leading-tight tracking-tight sm:text-5xl">{role === 'talent' ? 'Your next opportunity starts with a conversation.' : role === 'employer' ? 'Meet the people behind the skills.' : 'Make every introduction count.'}</h1>
            <p className="mt-4 max-w-md text-base leading-relaxed text-blue-100 sm:text-lg">
              {role === 'talent' && 'Bring your experience. Discover employers. Find something worth talking about.'}
              {role === 'employer' && 'Describe what you need and explore people who could help you build it.'}
              {role === 'organizer' && 'Plan introductions and see which employers need a hand.'}
            </p>
            </div>
            <aside className="hero-event-card">
              <p className="text-xs font-bold uppercase tracking-widest text-espoo">Espoo TalentMatch</p>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight text-ink">Local opportunities.<br />International talent.</h2>
              <div className="mt-6 grid grid-cols-2 gap-4 border-t border-blue-100 pt-5">
                <p className="text-sm text-slate-600"><strong className="block text-3xl font-semibold text-espoo">{directory?.companies.length ?? '—'}</strong>Employers to meet</p>
                <p className="text-sm text-slate-600"><strong className="block text-3xl font-semibold text-espoo">{directory?.candidates.length ?? '—'}</strong>Talent profiles</p>
              </div>
              <a href="#workspace" className="mt-6 flex items-center justify-between rounded-lg bg-espoo px-4 py-3 font-semibold text-white">Explore your workspace <span aria-hidden="true">→</span></a>
            </aside>
          </div>
        </div>}
      </header>
      <main id="workspace" className="mx-auto max-w-6xl scroll-mt-6 px-5 py-8 sm:px-8 sm:py-10">
        {!role && <section aria-labelledby="welcome-heading" className="py-6 sm:py-12">
          <p className="text-sm font-semibold text-espoo">Espoo TalentMatch · Hackathon demo</p>
          <h1 id="welcome-heading" className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">Welcome to RecruitiFi</h1>
          <p className="mt-4 max-w-xl text-slate-600">Choose a demo role to explore local opportunities, meet talent or plan introductions.</p>
          <div className="mt-8 grid gap-5 md:grid-cols-3">
            {roles.map(({ id }) => <article key={id} className={card}>
              <h2 className="text-xl font-bold text-espoo">{id === 'organizer' ? 'Espoo Organizer Login' : id === 'talent' ? 'Talent Login' : 'Employer Login'}</h2>
              <p className="mt-3 text-sm leading-relaxed text-slate-600">{id === 'talent' ? 'Build your profile and discover employers that fit your skills.' : id === 'employer' ? 'Explore candidate skills and find people for your team.' : 'Plan introductions and support employers across the event.'}</p>
              <button type="button" onClick={() => selectRole(id)} className="mt-6 w-full cursor-pointer rounded-lg bg-espoo px-4 py-3 text-sm font-semibold text-white hover:bg-blue-900">Continue as {id === 'talent' ? 'Talent' : id === 'employer' ? 'Employer' : 'Espoo Organizer'}</button>
            </article>)}
          </div>
          <p className="mt-6 text-xs text-slate-500">Demo role selection only — no accounts or secure role permissions. Use synthetic information only.</p>
        </section>}
        {role === 'organizer' && directory && <OrganizerWorkspace companies={directory.companies} />}
        {role && error && (
          <div className={card}>
            <p role="alert">{error}</p>
            <button type="button" className="mt-3 cursor-pointer font-semibold text-espoo underline" onClick={() => {
              setError('')
              setAttempt(attempt + 1)
            }}>Retry</button>
          </div>
        )}
        {role && !directory && !error && <p role="status">Loading directory…</p>}
        {role === 'talent' && directory && (
          <div><TalentWorkspace {...directory} swipeStore={swipeStore} onSaved={(candidate) => setDirectory((current) => current && {
            ...current, candidates: current.candidates.map((previous) => previous.id === candidate.id ? candidate : previous),
          })} /></div>
        )}
        {role === 'employer' && directory && (
          <div>
            <EmployerWorkspace swipeStore={swipeStore} companies={directory.companies} skills={directory.skills} candidates={directory.candidates} onCompanySaved={(company) => {
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

