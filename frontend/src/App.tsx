import { useEffect, useState } from 'react'
import { loadDemoAccounts, loadDirectory, type DemoCatalog } from './api'
import { TalentWorkspace } from './TalentWorkspace'
import { EmployerWorkspace } from './EmployerWorkspace'
import { OrganizerWorkspace } from './OrganizerWorkspace'
import { useSwipes } from './useSwipes'
import { useDemoNavigation, type DemoAccount, type DemoRole } from './demoNavigation'
import { loginAccount } from './accountSession'

const roles = [
  { id: 'talent', label: 'Talent View' },
  { id: 'employer', label: 'Employer View' },
  { id: 'organizer', label: 'Espoo Organizer' },
] as const

const card = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6'

function DemoDashboard({ account, catalog, logout }: { account: DemoAccount; catalog: DemoCatalog; logout: () => void }) {
  const role = account.role
  const swipeStore = useSwipes(role === 'talent' || role === 'employer')
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
              <span className="text-sm font-semibold text-espoo">{account.display_name} · {roles.find(({ id }) => id === role)?.label}</span>
              <button type="button" onClick={logout} className="cursor-pointer rounded-lg border border-blue-200 px-4 py-2 text-sm font-semibold text-espoo hover:bg-mist">Logout / Switch Account</button>
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
                <p className="text-sm text-slate-600"><strong className="block text-3xl font-semibold text-espoo">{catalog.company_count}</strong>Employers to meet</p>
                <p className="text-sm text-slate-600"><strong className="block text-3xl font-semibold text-espoo">{catalog.candidate_count}</strong>Talent profiles</p>
              </div>
              <a href="#workspace" className="mt-6 flex items-center justify-between rounded-lg bg-espoo px-4 py-3 font-semibold text-white">Explore your workspace <span aria-hidden="true">→</span></a>
            </aside>
          </div>
        </div>}
      </header>
      <main id="workspace" className="mx-auto max-w-6xl scroll-mt-6 px-5 py-8 sm:px-8 sm:py-10">
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
        {account.role === 'talent' && directory && (
          <div><TalentWorkspace candidateId={account.candidate_id} {...directory} swipeStore={swipeStore} onSaved={(candidate) => setDirectory((current) => current && {
            ...current, candidates: current.candidates.map((previous) => previous.id === candidate.id ? candidate : previous),
          })} /></div>
        )}
        {account.role === 'employer' && directory && (
          <div>
            <EmployerWorkspace companyId={account.company_id} swipeStore={swipeStore} companies={directory.companies} skills={directory.skills} candidates={directory.candidates} onCompanySaved={(company) => {
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


export function App() {
  const { account, selectAccount } = useDemoNavigation()
  const [catalog, setCatalog] = useState<DemoCatalog>()
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [role, setRole] = useState<DemoRole | null>(null)
  const [choice, setChoice] = useState('')
  const [privateLogin, setPrivateLogin] = useState<boolean>()
  const [verified, setVerified] = useState('')
  const [password, setPassword] = useState('')
  const [signingIn, setSigningIn] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/evidence-session/config', { credentials: 'same-origin', cache: 'no-store', signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Account verification configuration is unavailable.')
      const data = await response.json()
      if (typeof data.verified_login_required !== 'boolean') throw new Error('Invalid account verification configuration.')
      if (!controller.signal.aborted) setPrivateLogin(data.verified_login_required)
    }).catch(cause => { if (!controller.signal.aborted) setError(cause.message) })
    return () => controller.abort()
  }, [attempt])
  useEffect(() => {
    if (!privateLogin || !account || account.role === 'organizer') return
    const controller = new AbortController()
    fetch('/api/evidence-session', { credentials: 'same-origin', cache: 'no-store', signal: controller.signal }).then(async response => {
      const identity = response.ok ? await response.json() : null
      if (controller.signal.aborted) return
      if (identity?.account_id === account.demo_account_id) setVerified(identity.account_id)
      else { selectAccount(null); setError('Sign in to verify your selected account.') }
    }).catch(() => { if (!controller.signal.aborted) { selectAccount(null); setError('Account verification failed.') } })
    return () => controller.abort()
  }, [privateLogin, account?.demo_account_id])
  useEffect(() => {
    const controller = new AbortController()
    setError('')
    loadDemoAccounts(controller.signal).then((next) => {
      if (!controller.signal.aborted) setCatalog(next)
    }).catch(() => { if (!controller.signal.aborted) setError('Could not load demo accounts. Check that the API is running.') })
    return () => controller.abort()
  }, [attempt])
  const selected = catalog?.accounts.find((item) => item.demo_account_id === account?.demo_account_id)
  const valid = selected?.available && selected.role === account?.role
    && (selected.role !== 'talent' || (account?.role === 'talent' && selected.candidate_id === account.candidate_id))
    && (selected.role !== 'employer' || (account?.role === 'employer' && selected.company_id === account.company_id))
  function logout() { selectAccount(null); setRole(null); setChoice(''); setPassword(''); setVerified('') }
  // Key the whole dashboard, including directory, pending profiles and swipe state.
  // No personal requests are made until the stored identity matches the server catalog.
  if (privateLogin !== undefined && account && valid && selected && catalog && (!privateLogin || selected.role === 'organizer' || verified === selected.demo_account_id)) return <DemoDashboard key={selected.demo_account_id} account={selected} catalog={catalog} logout={logout} />
  const choices = catalog?.accounts.filter((item) => item.role === role) ?? []
  const chosen = choices.find((item) => item.demo_account_id === choice)
  return <div className="min-h-screen bg-[#f6f8fc] text-ink">
    <header className="border-b border-slate-200 bg-white"><div className="mx-auto flex max-w-6xl items-center gap-4 px-5 py-6 sm:px-8"><span className="brand-orbit" aria-hidden="true" /><p className="text-xl font-bold tracking-tight text-espoo">TalentMatch<span className="block text-xs font-medium tracking-wide text-slate-500">City of Espoo · Event demo</span></p></div></header>
    <main className="mx-auto max-w-6xl px-5 py-8 sm:px-8 sm:py-10">
      <section aria-labelledby="welcome-heading" className="py-6 sm:py-12">
        <p className="text-sm font-semibold text-espoo">Espoo TalentMatch · Hackathon demo</p>
        <h1 id="welcome-heading" className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">Welcome to RecruitiFi</h1>
        <p className="mt-4 max-w-xl text-slate-600">Choose a role and an individual demo account to explore the existing dashboards.</p>
        {account ? <div className={`mt-6 ${card}`}>
          <p role={catalog ? 'alert' : 'status'}>{catalog ? selected?.error ?? 'The saved demo account is unavailable or no longer matches its profile. Log out to choose again.' : 'Checking your demo account…'}</p>
          <button type="button" className="mt-3 font-semibold text-espoo underline" onClick={logout}>Logout / Switch Account</button>
        </div> : <>
          <div className="mt-8 grid gap-5 md:grid-cols-3">{roles.map(({ id }) => <article key={id} className={card}>
            <h2 className="text-xl font-bold text-espoo">{id === 'organizer' ? 'Espoo Organizer Login' : id === 'talent' ? 'Talent Login' : 'Employer Login'}</h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">{id === 'talent' ? 'Build your profile and discover employers that fit your skills.' : id === 'employer' ? 'Explore candidate skills and find people for your team.' : 'Plan introductions and support employers across the event.'}</p>
            <button type="button" aria-pressed={role === id} onClick={() => { setRole(id); setChoice('') }} className="mt-6 w-full cursor-pointer rounded-lg bg-espoo px-4 py-3 text-sm font-semibold text-white hover:bg-blue-900">Continue as {id === 'talent' ? 'Talent' : id === 'employer' ? 'Employer' : 'Espoo Organizer'}</button>
          </article>)}</div>
          {role && catalog && <form className={`mt-6 ${card}`} onSubmit={async (event) => {
            event.preventDefault()
            if (!chosen?.available || privateLogin === undefined || signingIn) return
            setSigningIn(true); setError('')
            try {
              if (privateLogin && chosen.role !== 'organizer') { await loginAccount(chosen.demo_account_id, password); setVerified(chosen.demo_account_id) }
              selectAccount(chosen)
            } catch (cause) { setError((cause as Error).message) }
            finally { setPassword(''); setSigningIn(false) }
          }}>
            <label className="grid gap-2 text-sm font-semibold">Demo account
              <select required value={choice} onChange={(event) => setChoice(event.target.value)} className="rounded-lg border border-slate-300 bg-white px-3 py-2">
                <option value="">Select your demo account</option>
                {choices.map((item) => <option key={item.demo_account_id} value={item.demo_account_id} disabled={!item.available}>{item.display_name} · {item.demo_account_id}{!item.available ? ' · Profile missing' : ''}</option>)}
              </select>
            </label>
            {choices.filter((item) => !item.available).map((item) => <p key={item.demo_account_id} role="alert" className="mt-2 text-sm text-red-800">{item.error}</p>)}
            {privateLogin && role !== 'organizer' && <label className="mt-3 grid gap-2 text-sm font-semibold">Account password<input required type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} className="rounded-lg border border-slate-300 px-3 py-2" /></label>}
            <button type="submit" disabled={!chosen?.available || privateLogin === undefined || signingIn} className="mt-4 rounded-lg bg-espoo px-4 py-3 font-semibold text-white enabled:cursor-pointer disabled:opacity-50">{signingIn ? 'Signing in…' : 'Enter Dashboard'}</button>
          </form>}
        </>}
        {!catalog && !error && !account && <p role="status" className="mt-4">Loading demo accounts…</p>}
        {error && <p role="alert" className="mt-4">{error} <button type="button" className="underline" onClick={() => setAttempt((value) => value + 1)}>Retry</button></p>}
        <p className="mt-6 text-xs text-slate-500">{privateLogin ? 'Server-verified synthetic demo accounts. AI access reuses this sign-in.' : 'Password-free demo navigation only — no secure account authorization.'} Use synthetic information only.</p>
      </section>
    </main>
  </div>
}
