import { useEffect, useState } from 'react'
import { ProfileMaterials } from './ProfileMaterials'
import {
  simulateMatch,
  profileRequest,
  type SavedProfile,
  type Candidate,
  type CandidateProfile,
  type Company,
  type EvidenceTier,
  type Match,
  type Skill,
} from './api'

const evidenceLabels: Record<EvidenceTier, string> = {
  self_declared: 'Listed skill',
  portfolio: 'Work sample added',
  certificate: 'Certificate submitted',
}
const panel = 'rounded-2xl border border-slate-200 bg-white shadow-sm'
const select = 'min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm'
const primary = 'rounded-lg bg-espoo px-4 py-2.5 text-sm font-semibold text-white enabled:cursor-pointer enabled:hover:bg-blue-900 disabled:opacity-50'
const format = new Intl.NumberFormat('en', { maximumFractionDigits: 1 })

function MatchBreakdown({ match, busy, onClose }: {
  match: Match
  busy: boolean
  onClose: () => void
}) {
  const [requested, setRequested] = useState(false)
  const eligible = match.dealbreakers_passed && match.meets_threshold
  const status = eligible
    ? 'Eligible to Book 1:1'
    : match.meets_threshold ? 'Requirements unmet' : `Below ${match.min_match_threshold}% Threshold`
  const bars = [
    { label: 'Must-have skills', points: match.must_have_points, max: 70, color: 'bg-espoo' },
    { label: 'Nice-to-have skills', points: match.nice_to_have_points, max: 20, color: 'bg-blue-600' },
    { label: 'Profile proof', points: match.profile_proof_points, max: 10, color: 'bg-teal-600' },
  ]

  return (
    <section aria-label="Match Sync Breakdown" className="border-b border-blue-200 bg-mist/60 px-4 py-5 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold text-espoo">Match Sync Breakdown</h3>
        <button type="button" onClick={onClose} className="cursor-pointer text-sm font-semibold text-espoo underline">Close</button>
      </div>
      <p className={`mt-3 inline-block rounded-md px-2.5 py-1 text-sm font-semibold ${eligible ? 'bg-emerald-100 text-emerald-900' : 'bg-amber-100 text-amber-950'}`}>
        {format.format(match.total_score)}% — {status}
      </p>
      <p className="mt-2 text-xs text-slate-600">Minimum score {match.min_match_threshold}%</p>
      {match.dealbreaker_reasons.length > 0 && (
        <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-slate-700">
          {match.dealbreaker_reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      )}
      <div className="mt-5 grid gap-4 sm:grid-cols-3">
        {bars.map(({ label, points, max, color }) => (
          <div key={label}>
            <div className="mb-1 flex flex-wrap justify-between gap-x-2 text-xs font-semibold">
              <span>{label}</span><span className="tabular-nums">{format.format(points)}/{max}</span>
            </div>
            <div role="progressbar" aria-label={label} aria-valuenow={points} aria-valuemax={max} className="h-2 overflow-hidden rounded-full bg-blue-100">
              <div className={`h-full rounded-full transition-[width] motion-reduce:transition-none ${color}`} style={{ width: `${points / max * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      <button type="button" disabled={busy || !eligible || requested} onClick={() => setRequested(true)} className={`mt-5 ${primary}`}>
        Request 1:1 Meeting
      </button>
      {requested && <p role="status" className="mt-2 text-sm text-slate-600">Demo meeting request recorded for this preview.</p>}
    </section>
  )
}

export function TalentWorkspace({ candidates, companies, skills, onSaved }: {
  candidates: Candidate[]
  companies: Company[]
  skills: Skill[]
  onSaved: (candidate: Candidate) => void
}) {
  const [candidateId, setCandidateId] = useState(candidates[0]?.id)
  const [savedProfile, setSavedProfile] = useState<SavedProfile>()
  const [profileError, setProfileError] = useState('')
  const [profileBusy, setProfileBusy] = useState(false)
  const [profileAttempt, setProfileAttempt] = useState(0)
  const [skillToAdd, setSkillToAdd] = useState('')
  const [openCompany, setOpenCompany] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{ candidateId: number; profile: CandidateProfile; companies: Company[]; attempt: number; matches: Match[]; failed: boolean }>()
  const candidate = candidates.find(({ id }) => id === candidateId)
  const profile = savedProfile?.candidate.id === candidateId ? savedProfile.candidate : undefined
  useEffect(() => {
    if (candidateId === undefined) return
    const controller = new AbortController()
    setProfileError('')
    profileRequest(candidateId, 'profile', { signal: controller.signal }).then((saved) => {
      if (!controller.signal.aborted) setSavedProfile(saved)
    }).catch(() => {
      if (!controller.signal.aborted) setProfileError('Could not load your saved profile.')
    })
    return () => controller.abort()
  }, [candidateId, profileAttempt])
  const current = result?.profile === profile && result?.attempt === attempt && result.companies === companies ? result : undefined
  const busy = !current

  useEffect(() => {
    if (!profile || candidateId === undefined) return
    const controller = new AbortController()
    const payload: CandidateProfile = {
      has_cv: profile.has_cv,
      has_portfolio: profile.has_portfolio,
      languages: profile.languages,
      needs_visa_sponsorship: profile.needs_visa_sponsorship,
      skills: profile.skills,
    }
    Promise.all(companies.map(({ id }) => simulateMatch(id, payload, controller.signal)))
      .then((matches) => {
        if (!controller.signal.aborted) {
          matches.sort((a, b) => b.total_score - a.total_score || a.company_id - b.company_id)
          setResult({ candidateId, profile, companies, attempt, matches, failed: false })
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setResult({ candidateId, profile, companies, attempt, matches: [], failed: true })
      })
    return () => controller.abort()
  }, [profile, candidateId, companies, attempt])

  if (!candidate) return <p>No candidate profiles available.</p>
  if (!profile || !savedProfile) return <div role="status">{profileError || 'Loading your saved profile…'}{profileError && <button type="button" className="ml-3 underline" onClick={() => setProfileAttempt((value) => value + 1)}>Retry</button>}</div>

  const skillNames = new Map(skills.map(({ id, name }) => [id, name]))
  const availableSkills = skills.filter(({ id }) => !profile.skills.some((skill) => skill.skill_id === id))
  const companyById = new Map(companies.map((company) => [company.id, company]))
  const displayed = result?.candidateId === candidate.id ? result : undefined
  const rows = displayed?.matches.length
    ? displayed.matches.map((match) => ({ company: companyById.get(match.company_id)!, match }))
    : companies.map((company) => ({ company, match: undefined }))
  function acceptSaved(saved: SavedProfile) {
    setSavedProfile(saved)
    onSaved(saved.candidate)
  }
  async function saveSkills(ids: number[]) {
    setProfileBusy(true)
    setProfileError('')
    try {
      acceptSaved(await profileRequest(candidate!.id, 'skills', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ids),
      }))
    } catch (cause) { setProfileError((cause as Error).message) }
    finally { setProfileBusy(false) }
  }

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(19rem,0.8fr)_minmax(0,1.4fr)]">
      <section aria-labelledby="profile-heading" className={`${panel} min-w-0 p-5 sm:p-6`}>
        <h2 id="profile-heading" className="text-xl font-bold tracking-tight">Talent profile</h2>
        <p className="mt-1 text-sm leading-relaxed text-slate-600">Build a profile around your experience, projects and qualifications.</p>
        <label className="mt-5 grid gap-1.5 text-sm font-semibold">
          Candidate persona
          <select disabled={profileBusy} className={select} value={candidate.id} onChange={(event) => {
            setCandidateId(Number(event.target.value))
            setSkillToAdd('')
            setOpenCompany(null)
          }}>
            {candidates.map(({ id, full_name, anonymous_code }) => <option key={id} value={id}>{full_name} · {anonymous_code}</option>)}
          </select>
        </label>
        <p className="mt-3 text-sm text-slate-600">{Object.entries(profile.languages).map(([name, level]) => `${name} ${level}`).join(' · ')}</p>
        {profile.needs_visa_sponsorship && <p className="mt-1 text-sm text-slate-600">Needs visa sponsorship</p>}
        <ProfileMaterials key={candidate.id} profile={savedProfile} skills={skills} onSaved={acceptSaved} />
        {profileError && <p role="alert" className="mt-3 text-sm text-red-800">{profileError}</p>}
        <h3 className="mt-6 text-sm font-bold">Your skills</h3>
        <form className="mt-2 flex gap-2" onSubmit={(event) => {
          event.preventDefault()
          const skillId = Number(skillToAdd)
          if (!availableSkills.some(({ id }) => id === skillId)) return
          void saveSkills([...profile.skills.map(({ skill_id }) => skill_id), skillId])
          setSkillToAdd('')
        }}>
          <select aria-label="Skill to add" className={`${select} flex-1`} value={skillToAdd} onChange={(event) => setSkillToAdd(event.target.value)}>
            <option value="">Select a skill</option>
            {availableSkills.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
          </select>
          <button type="submit" className={primary} disabled={!skillToAdd || profileBusy}>Add skill</button>
        </form>
        <ul className="mt-3 divide-y divide-slate-100">
          {profile.skills.map(({ skill_id, evidence_tier }) => {
            const name = skillNames.get(skill_id) ?? `Skill #${skill_id}`
            return (
              <li key={skill_id} className="py-3">
                <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
                  <span className="font-semibold">{name}</span>
                  <button type="button" aria-label={`Remove ${name}`} className="cursor-pointer text-xs text-slate-600 underline hover:text-espoo" disabled={profileBusy || evidence_tier !== 'self_declared'} onClick={() => void saveSkills(profile.skills.filter((skill) => skill.skill_id !== skill_id).map(({ skill_id }) => skill_id))}>Remove</button>
                </div>
                <p className="text-xs text-slate-600">{evidenceLabels[evidence_tier]}{evidence_tier !== 'self_declared' && ' · Managed through your documents and projects'}</p>
              </li>
            )
          })}
        </ul>
      </section>
      <section aria-labelledby="matches-heading" className={`${panel} min-w-0 overflow-hidden`}>
        <div className="border-b border-slate-200 p-5 sm:p-6">
          <h2 id="matches-heading" className="text-xl font-bold tracking-tight">Live employer matches</h2>
          <p className="mt-1 text-sm text-slate-600">Sorted by match score. Select an employer to see the breakdown.</p>
          <p role="status" className="mt-2 min-h-5 text-xs font-semibold text-espoo">
            {busy ? 'Updating match scores…' : current.failed ? '' : `${current.matches.length} employers scored`}
          </p>
          {current?.failed && (
            <p role="alert" className="text-sm text-red-800">Could not refresh scores. <button type="button" className="cursor-pointer font-semibold underline" onClick={() => setAttempt((value) => value + 1)}>Retry</button></p>
          )}
        </div>
        {rows.map(({ company, match }) => (
          <div key={company.id}>
            <button type="button" aria-expanded={openCompany === company.id} onClick={() => setOpenCompany(openCompany === company.id ? null : company.id)}
              className={`flex w-full cursor-pointer items-center gap-3 border-b border-slate-100 px-4 py-4 text-left hover:bg-mist sm:gap-4 sm:px-6 ${openCompany === company.id ? 'bg-mist' : ''}`}>
              <span className="shrink-0 rounded-lg bg-mist px-2 py-2 text-xs font-bold text-espoo">{company.booth_number}</span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold">{company.name}</span>
                <span className="block text-xs leading-relaxed text-slate-600">{company.industry}</span>
              </span>
              <span className={`shrink-0 text-lg font-bold tabular-nums text-espoo ${busy ? 'opacity-50' : ''}`}>{match ? `${format.format(match.total_score)}%` : '—'}</span>
              <span aria-hidden="true" className="text-espoo">{openCompany === company.id ? '−' : '+'}</span>
            </button>
            {openCompany === company.id && match && (
              <MatchBreakdown key={candidate.id} match={match} busy={busy} onClose={() => setOpenCompany(null)} />
            )}
          </div>
        ))}
        {companies.length === 0 && <p className="p-5 text-sm text-slate-600">No employers available.</p>}
      </section>
    </div>
  )
}
