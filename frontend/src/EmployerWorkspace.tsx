import { SwipeDeck, type DiscoveryCard } from './SwipeDeck'
import { EmployerTasks } from './HiringTasks'
import type { SwipeStore } from './useSwipes'
import { useEffect, useState } from 'react'
import {
  acceptCompanyMeeting, loadCompanyMatches, saveCompanyRole,
  type Candidate, type Company, type CompanyRole, type MeetingContact, type RankedMatch, type Skill, type WeightedSkill,
} from './api'

const panel = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6'
const input = 'min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm'
const button = 'rounded-lg bg-espoo px-4 py-2 text-sm font-semibold text-white enabled:cursor-pointer enabled:hover:bg-blue-900 disabled:opacity-50'
const link = 'cursor-pointer text-sm font-semibold text-espoo underline'
const format = new Intl.NumberFormat('en', { maximumFractionDigits: 1 })

function distributeSkillWeights(ids: number[], total: number): WeightedSkill[] {
  if (ids.length === 0) return []
  const share = Math.floor(total / ids.length)
  const remainder = total % ids.length
  return [...ids].sort((a, b) => a - b).map((skill_id, index) => ({
    skill_id,
    weight: share + Number(index < remainder),
  }))
}

function SkillPicker({ title, max, values, available, names, onChange }: {
  title: string; max: number; values: WeightedSkill[]; available: Skill[]
  names: Map<number, string>; onChange: (values: WeightedSkill[]) => void
}) {
  const [selection, setSelection] = useState('')
  const selectedId = Number(selection)
  const limitReached = values.length >= max
  return (
    <fieldset className="mt-5 border-t border-slate-200 pt-3">
      <legend className="pr-2 text-sm font-bold">{title}</legend>
      {values.length === 0 && <p className="text-sm text-slate-600">No skills selected.</p>}
      <ul className="flex flex-wrap gap-2">
        {values.map(({ skill_id }) => {
          const name = names.get(skill_id) ?? `Skill #${skill_id}`
          return (
            <li key={skill_id} className="flex flex-wrap items-center gap-x-2 rounded-lg bg-mist px-3 py-1.5 text-sm">
              <span>{name}</span>
              <button type="button" aria-label={`Remove ${name}`} className={link}
                onClick={() => onChange(distributeSkillWeights(values.map((skill) => skill.skill_id).filter((id) => id !== skill_id), max))}>Remove</button>
            </li>
          )
        })}
      </ul>
      <div className="mt-3 flex gap-2">
        <select aria-label={`Add ${title.toLowerCase()} skill`} disabled={limitReached} className={`${input} flex-1`} value={selection} onChange={(event) => setSelection(event.target.value)}>
          <option value="">Select a skill</option>
          {available.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
        </select>
        <button type="button" className={button} disabled={limitReached || !available.some(({ id }) => id === selectedId)} onClick={() => {
          onChange(distributeSkillWeights([...values.map(({ skill_id }) => skill_id), selectedId], max))
          setSelection('')
        }}>Add</button>
      </div>
      {limitReached && <p className="mt-2 text-sm text-slate-600">Up to {max} skills in this group.</p>}
    </fieldset>
  )
}

function QuickRoleBuilder({ company, skills, onSave, onClose }: {
  company: Company; skills: Skill[]; onSave: (company: Company) => void; onClose: () => void
}) {
  const [role, setRole] = useState<CompanyRole>(() => ({
    working_language: company.working_language,
    relocation_support: company.relocation_support,
    min_match_threshold: company.min_match_threshold,
    must_have_skills: company.must_have_skills,
    nice_to_have_skills: company.nice_to_have_skills,
  }))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const names = new Map(skills.map(({ id, name }) => [id, name]))
  const used = new Set([...role.must_have_skills, ...role.nice_to_have_skills].map(({ skill_id }) => skill_id))
  const available = skills.filter(({ id }) => !used.has(id))
  const groups = [
    { field: 'must_have_skills', title: 'Must-have', max: 70 },
    { field: 'nice_to_have_skills', title: 'Nice-to-have', max: 20 },
  ] as const
  const valid = groups.every(({ field }) => role[field].length > 0)

  return (
    <form aria-label="Quick Role Builder" className={`${panel} mt-4`} onSubmit={async (event) => {
      event.preventDefault()
      if (!valid || saving) return
      setSaving(true)
      setError('')
      try { onSave(await saveCompanyRole(company.id, role)) }
      catch (cause) { setError((cause as Error).message); setSaving(false) }
    }}>
      <h2 className="text-lg font-bold">Quick Role Builder</h2>
      <p className="mt-1 text-sm text-slate-600">Choose the skills for this role. Match scoring is automatic.</p>
      <fieldset disabled={saving} className="min-w-0 disabled:opacity-70">
        {groups.map(({ field, title, max }) => (
          <SkillPicker key={field} title={title} max={max} values={role[field]} available={available} names={names}
            onChange={(values) => setRole({ ...role, [field]: values })} />
        ))}
        <fieldset className="mt-5 space-y-3 border-t border-slate-200 pt-3">
          <legend className="pr-2 text-sm font-bold">Hard dealbreakers</legend>
          <label className="grid gap-1 text-sm">
            Working language (B2 or higher)
            <select className={input} value={role.working_language} onChange={(event) => setRole({ ...role, working_language: event.target.value })}>
              {['English', 'Finnish', 'Swedish'].map((language) => <option key={language}>{language}</option>)}
            </select>
          </label>
          <label className="flex items-center justify-between gap-2 rounded-lg bg-mist p-3 text-sm">
            Relocation support
            <input type="checkbox" role="switch" checked={role.relocation_support} className="accent-espoo" onChange={(event) => setRole({ ...role, relocation_support: event.target.checked })} />
          </label>
        </fieldset>
        <label className="mt-5 grid gap-2 text-sm font-semibold">
          Minimum match threshold · {role.min_match_threshold}%
          <input type="range" min={50} max={90} value={role.min_match_threshold} className="w-full accent-espoo"
            onChange={(event) => setRole({ ...role, min_match_threshold: Number(event.target.value) })} />
        </label>
        <div aria-hidden="true" className="flex justify-between text-xs text-slate-600"><span>50%</span><span>90%</span></div>
        {!valid && <p className="mt-3 text-sm text-amber-900">Choose at least one skill in each group to save.</p>}
        <div className="mt-5 flex items-center gap-4">
          <button type="submit" disabled={!valid || saving} className={button}>{saving ? 'Saving…' : 'Save role'}</button>
          <button type="button" className={link} onClick={onClose}>Cancel</button>
        </div>
      </fieldset>
      {error && <p role="alert" className="mt-3 text-sm text-red-800">{error}</p>}
    </form>
  )
}

function CandidateSignal({ match, companyId }: { match: RankedMatch; companyId: number }) {
  const [contact, setContact] = useState<MeetingContact>()
  const [accepting, setAccepting] = useState(false)
  const [reviewed, setReviewed] = useState(false)
  const [error, setError] = useState('')
  const signals = [...match.must_have_skills, ...match.nice_to_have_skills].filter(({ evidence_tier }) => evidence_tier !== 'missing')
  return (
    <li className="rounded-xl border border-slate-200 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold">{match.anonymous_code}</h3>
        <strong className="rounded-lg bg-mist px-2.5 py-1 text-lg tabular-nums text-espoo">{format.format(match.total_score)}%</strong>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs font-semibold text-emerald-800">
        <span>{match.dealbreakers_passed ? '✓ Role requirements met' : 'Requirements to discuss'}</span>
      </div>
      <ul aria-label="Overlapping skill evidence" className="mt-3 flex flex-wrap gap-2">
        {signals.map(({ skill_id, skill_name, evidence_tier }) => (
          <li key={skill_id} className={`rounded-md px-2 py-1 text-xs ${evidence_tier === 'certificate' ? 'bg-emerald-100 text-emerald-900' : 'bg-slate-100 text-slate-700'}`}>
            {skill_name} · {evidence_tier === 'certificate' ? 'Certificate submitted' : evidence_tier === 'portfolio' ? 'Work sample' : 'Listed skill'}
          </li>
        ))}
      </ul>
      {(!match.dealbreakers_passed || !match.meets_threshold) && (
        <div className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
          {match.dealbreaker_reasons.map((reason) => <p key={reason}>{reason}</p>)}
          {!match.meets_threshold && <p>Below the role’s suggested match level.</p>}
          <label className="mt-2 flex items-start gap-2"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />I have reviewed this profile and would like a conversation.</label>
        </div>
      )}
      {contact ? (
        <div className="mt-4 rounded-lg border border-blue-100 bg-mist/60 p-3 text-sm" aria-live="polite">
          <p className="font-bold">{contact.full_name}</p>
          <a href={`mailto:${contact.email}`} className="break-all text-espoo underline">{contact.email}</a>
          <p className="mt-2 font-semibold text-espoo">{contact.conversation_starter}</p>
        </div>
      ) : (
        <button type="button" disabled={accepting || ((!match.dealbreakers_passed || !match.meets_threshold) && !reviewed)} className={`mt-4 ${button}`} onClick={async () => {
          setAccepting(true)
          setError('')
          try { setContact(await acceptCompanyMeeting(companyId, match.anonymous_code, reviewed)) }
          catch (cause) { setError((cause as Error).message) }
          finally { setAccepting(false) }
        }}>{accepting ? 'Accepting…' : 'Accept 1:1 Meeting'}</button>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-red-800">{error}</p>}
    </li>
  )
}

export function EmployerWorkspace({ companies, skills, candidates, onCompanySaved, swipeStore }: {
  companies: Company[]; skills: Skill[]; candidates: Candidate[]; onCompanySaved: (company: Company) => void
  swipeStore: SwipeStore
}) {
  const [view, setView] = useState<'swipe' | 'queue' | 'shortlist'>('swipe')
  const [companyId, setCompanyId] = useState(companies[0]?.id)
  const [editing, setEditing] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [notice, setNotice] = useState('')
  const [result, setResult] = useState<{ company: Company; attempt: number; matches: RankedMatch[]; failed: boolean }>()
  const company = companies.find(({ id }) => id === companyId)
  const current = result?.company === company && result?.attempt === attempt ? result : undefined

  useEffect(() => {
    if (!company) return
    const controller = new AbortController()
    loadCompanyMatches(company.id, controller.signal).then((matches) => {
      if (!controller.signal.aborted) setResult({
        company, attempt, matches, failed: false,
      })
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ company, attempt, matches: [], failed: true })
    })
    return () => controller.abort()
  }, [company, attempt, candidates])

  if (!company) return <p>No employers available.</p>
  const visibleMatches = current?.matches.filter((match) => showAll || (match.dealbreakers_passed && match.meets_threshold)) ?? []
  const own = swipeStore.swipes.filter((row) => row.company_id === company.id && row.actor === 'employer')
  const interested = new Set(swipeStore.swipes.filter((row) => row.company_id === company.id && row.actor === 'talent' && row.decision === 'like').map((row) => row.candidate_id))
  const shortlisted = own.filter((row) => row.decision === 'like')
  const cards: DiscoveryCard[] = (current?.matches ?? []).filter((match) => !own.some((row) => row.candidate_id === match.candidate_id)).map((match) => ({
    id: match.candidate_id, name: match.anonymous_code, subtitle: 'Talent in Espoo · identity stays private',
    monogram: match.anonymous_code.slice(-2), score: match.total_score,
    eligible: match.dealbreakers_passed && match.meets_threshold, likedYou: interested.has(match.candidate_id),
    facts: [match.dealbreakers_passed ? 'Language & visa compatible' : 'Check role requirements', `${company.min_match_threshold}% meeting threshold`],
    skills: [...match.must_have_skills, ...match.nice_to_have_skills].map((skill) => ({ name: skill.skill_name, matched: skill.evidence_tier !== 'missing' })),
    warnings: [...match.dealbreaker_reasons, ...(!match.meets_threshold ? ['Below your meeting threshold'] : [])],
  }))
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(21rem,0.9fr)_minmax(0,1.3fr)]">
      <div className="min-w-0">
        <section className={panel} aria-label="Employer role">
          <label className="grid gap-2 text-sm font-semibold">
            Company
            <select className={input} value={company.id} disabled={editing} onChange={(event) => {
              setCompanyId(Number(event.target.value)); setEditing(false); setNotice('')
            }}>
              {companies.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
            </select>
          </label>
          <p className="mt-3 text-sm text-slate-600">Booth {company.booth_number} · {company.industry}</p>
          <p className="mt-1 text-sm text-slate-600">{company.working_language} B2+ · {company.min_match_threshold}% threshold</p>
          {!editing && <button type="button" className={`mt-4 ${button}`} onClick={() => { setNotice(''); setEditing(true) }}>Quick Role Builder</button>}
          {notice && <p role="status" className="mt-3 text-sm font-semibold text-emerald-800">{notice}</p>}
        </section>
        {editing && <QuickRoleBuilder key={company.id} company={company} skills={skills} onClose={() => setEditing(false)} onSave={(saved) => {
          onCompanySaved(saved)
          setEditing(false)
          setNotice('Role saved.')
        }} />}
      </div>
      <div className="order-first min-w-0 lg:order-none">
        <div className="talent-view-toggle" aria-label="Talent discovery mode">
          <button type="button" aria-pressed={view === 'swipe'} onClick={() => setView('swipe')}>Discover talent</button>
          <button type="button" aria-pressed={view === 'queue'} onClick={() => { setView('queue') }}>Eligible queue</button>
          <button type="button" aria-pressed={view === 'shortlist'} onClick={() => setView('shortlist')}>Shortlisted ({shortlisted.length})</button>
        </div>
        {view === 'swipe' && <SwipeDeck side="employer" key={company.id} cards={cards} loading={!current || !swipeStore.ready} error={swipeStore.error || (current?.failed ? 'Could not load candidate scores.' : '')}
          onRetry={() => { swipeStore.retry(); setAttempt((value) => value + 1) }}
          onUndo={(candidate_id) => swipeStore.undo({ candidate_id, company_id: company.id, actor: 'employer' })}
          onDecide={(candidate_id, decision) => swipeStore.decide({ candidate_id, company_id: company.id, actor: 'employer', decision })}
          saved={shortlisted.map(({ candidate_id }) => ({
            id: candidate_id,
            name: candidates.find(({ id }) => id === candidate_id)?.anonymous_code ?? 'Candidate',
            mutual: interested.has(candidate_id),
          }))}
          onReview={() => { setShowAll(true); setView('queue') }} />}
        {view === 'shortlist' && <section className={panel} aria-labelledby="shortlist-heading">
          <h2 id="shortlist-heading" className="text-xl font-bold">Shortlisted candidates</h2>
          {swipeStore.error ? <p role="alert" className="mt-3 text-sm">{swipeStore.error} <button type="button" className={link} onClick={swipeStore.retry}>Retry</button></p> :
            !swipeStore.ready ? <p role="status" className="mt-3 text-sm">Loading shortlist…</p> :
            shortlisted.length === 0 ? <p className="mt-3 text-sm">Shortlist a candidate from Discover talent to see them here.</p> :
            <div className="mt-4 space-y-4">
              {shortlisted.map(({ candidate_id }) => <EmployerTasks key={company.id + '-' + candidate_id}
                name={candidates.find(({ id }) => candidate_id === id)?.anonymous_code ?? 'Candidate'}
                score={current?.matches.find((match) => match.candidate_id === candidate_id)?.total_score}
                mutual={interested.has(candidate_id)} candidateId={candidate_id} companyId={company.id} store={swipeStore} />)}
            </div>}
        </section>}
      <section hidden={view !== 'queue'} className={`${panel} min-w-0`} aria-labelledby="queue-heading">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="queue-heading" className="text-xl font-bold tracking-tight">People to meet</h2>
          <span className="rounded-full bg-mist px-3 py-1 text-xs font-semibold text-espoo">Blind Privacy Mode · ON</span>
        </div>
        <p className="mt-2 text-sm text-slate-600">Explore shared skills and choose who you want to speak with.</p>
        <label className="mt-4 flex items-center gap-2 text-sm font-semibold text-espoo"><input type="checkbox" checked={showAll} onChange={(event) => setShowAll(event.target.checked)} />Explore all talent</label>
        {!current && <p role="status" className="mt-4 text-sm text-slate-600">Refreshing candidate scores…</p>}
        {current?.failed && <p role="alert" className="mt-4 text-sm text-red-800">Could not load the queue. <button type="button" className={link} onClick={() => setAttempt((value) => value + 1)}>Retry</button></p>}
        {current && !current.failed && (
          <div className="mt-4">
            <p role="status" className="text-sm font-semibold text-espoo">{visibleMatches.length} {showAll ? 'profiles to explore' : 'suggested conversations'}</p>
            {visibleMatches.length === 0 && <p className="mt-3 rounded-lg bg-mist p-4 text-sm">No suggestions yet. Explore all talent to find potential beyond the role requirements.</p>}
            <ul className="mt-3 space-y-3">
              {visibleMatches.map((match) => <CandidateSignal key={match.anonymous_code} match={match} companyId={company.id} />)}
            </ul>
          </div>
        )}
      </section>
      </div>
    </div>
  )
}
