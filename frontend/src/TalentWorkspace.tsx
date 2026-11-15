import { analysisRevision, resourceAnalysisMode, sourceAnalysisNote, materialDisplayName } from './analysisResources'
import { useAiMatches, aiLabel, AiExplanation, displayAiScore } from './useAiMatches'
import { filterJobs, IndustryFilters, JobEmptyState, JobRequirements, jobCompanyId, useIndustryFilters } from './Jobs'
import { NotificationBell } from './NotificationBell'
import { SwipeDeck, type DiscoveryCard } from './SwipeDeck'
import { CandidateUpdates } from './HiringTasks'
import type { SwipeStore } from './useSwipes'
import { useEffect, useState } from 'react'
import { ProfileMaterials } from './ProfileMaterials'
import {
  loadJobDirectory,
  loadCandidateJobMatches,
  profileRequest,
  type SavedProfile,
  type Candidate,
  type JobMatch,
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
const select = 'workspace-select'
const primary = 'rounded-lg bg-espoo px-4 py-2.5 text-sm font-semibold text-white enabled:cursor-pointer enabled:hover:bg-blue-900 disabled:opacity-50'
const format = new Intl.NumberFormat('en', { maximumFractionDigits: 1 })

function MatchBreakdown({ match, busy, onClose }: {
  match: Match
  busy: boolean
  onClose: () => void
}) {
  const [requested, setRequested] = useState(false)
  const eligible = match.dealbreakers_passed && match.ai?.score != null && match.ai.score >= match.min_match_threshold


  return (
    <section aria-label="Match Sync Breakdown" className="border-b border-blue-200 bg-mist/60 px-4 py-5 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold text-espoo">Match Sync Breakdown</h3>
        <button type="button" onClick={onClose} className="cursor-pointer text-sm font-semibold text-espoo underline">Close</button>
      </div>
      <AiExplanation match={match.ai} />
      <button type="button" disabled={busy || !eligible || requested} onClick={() => setRequested(true)} className={`mt-5 ${primary}`}>
        Request 1:1 Meeting
      </button>
      {requested && <p role="status" className="mt-2 text-sm text-slate-600">Demo meeting request recorded for this preview.</p>}
    </section>
  )
}

export function TalentWorkspace({ candidateId, candidates, companies, skills, onSaved, swipeStore }: {
  swipeStore: SwipeStore
  candidateId: number
  candidates: Candidate[]
  companies: Company[]
  skills: Skill[]
  onSaved: (candidate: Candidate) => void
}) {
  const [analysisMaterials,setAnalysisMaterials]=useState<number[]>([])
  const [analysisConsent,setAnalysisConsent]=useState(false)
  const [shareAnalysis,setShareAnalysis]=useState(false)
  useEffect(() => {setAnalysisMaterials([]);setAnalysisConsent(false);setShareAnalysis(false)},[candidateId])
  const [view, setView] = useState<'swipe' | 'list' | 'updates'>('swipe')
  const [filtersOpen,setFiltersOpen]=useState(false)
  const [savedProfile, setSavedProfile] = useState<SavedProfile>()
  const ai = useAiMatches([candidateId], analysisRevision(savedProfile))
  useEffect(() => {
    const current = new Set(savedProfile?.materials.map(m => m.id) ?? [])
    setAnalysisMaterials(ids => ids.filter(id => current.has(id)))
    setAnalysisConsent(false)
  },[JSON.stringify(savedProfile?.materials)])
  const [profileError, setProfileError] = useState('')
  const [profileBusy, setProfileBusy] = useState(false)
  const [profileAttempt, setProfileAttempt] = useState(0)
  const [skillToAdd, setSkillToAdd] = useState('')
  const [openJob, setOpenJob] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)
  const filters = useIndustryFilters(candidateId)
  const [jobDirectory, setJobDirectory] = useState<Awaited<ReturnType<typeof loadJobDirectory>>>()
  const [jobError, setJobError] = useState('')
  const [result, setResult] = useState<{ profile: Candidate; attempt: number; matches: JobMatch[]; failed: boolean }>()
  useEffect(() => {
    const controller = new AbortController()
    setJobError('')
    loadJobDirectory(controller.signal).then((directory) => {
      if (!controller.signal.aborted) setJobDirectory(directory)
    }).catch(() => { if (!controller.signal.aborted) setJobError('Could not load job openings.') })
    return () => controller.abort()
  }, [attempt])
  const candidate = candidates.find(({ id }) => id === candidateId)
  const profile = savedProfile && savedProfile.candidate.id === candidateId ? savedProfile.candidate : undefined
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
  const current = result?.profile === profile && result?.attempt === attempt ? result : undefined
  const busy = !current

  useEffect(() => {
    if (!profile || candidateId === undefined) return
    const controller = new AbortController()
    loadCandidateJobMatches(candidateId, controller.signal).then((matches) => {
      if (!controller.signal.aborted) setResult({ profile, attempt, matches, failed: false })
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ profile, attempt, matches: [], failed: true })
    })
    return () => controller.abort()
  }, [profile, candidateId, attempt])

  if (!candidate) return <p>Your demo candidate profile is unavailable. Log out and contact the demo operator.</p>
  if (!profile || !savedProfile) return <div role="status">{profileError || 'Loading your saved profile…'}{profileError && <button type="button" className="ml-3 underline" onClick={() => setProfileAttempt((value) => value + 1)}>Retry</button>}</div>

  const skillNames = new Map(skills.map(({ id, name }) => [id, name]))
  const availableSkills = skills.filter(({ id }) => !profile.skills.some((skill) => skill.skill_id === id))
  const companyById = new Map(companies.map((company) => [company.id, company]))
  const jobs = jobDirectory?.jobs ?? []
  const matchByJob = new Map(current?.matches.map((match) => [match.job_id, { ...match, ai: ai.match(candidateId, match.job_id) }]))
  const visibleJobs = filterJobs(jobs, filters.selected).sort((a, b) => {
    const x = matchByJob.get(a.id), y = matchByJob.get(b.id)
    return Number(y?.dealbreakers_passed ?? false) - Number(x?.dealbreakers_passed ?? false) || (y?.ai?.score ?? -1) - (x?.ai?.score ?? -1) || a.id - b.id
  })
  const rows = visibleJobs.map((job) => ({ job, company: companyById.get(job.company_id), match: matchByJob.get(job.id) }))
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
  const decisions = swipeStore.swipes.filter((row) => row.candidate_id === candidate.id)
  const own = decisions.filter((row) => row.actor === 'talent')
  const likedBy = new Set(decisions.filter((row) => row.actor === 'employer' && row.decision === 'like').map((row) => row.company_id))
  const discoveryCards: DiscoveryCard[] = rows.filter(({ job, match }) => match && !own.some((row) => row.company_id === job.company_id)).map(({ job, company, match }) => ({
    id: job.id, name: job.title, subtitle: `${job.company_name} · ${job.industry_label}`,
    monogram: job.company_name.split(' ').slice(0, 2).map((word) => word[0]).join(''),
    score: displayAiScore(match!.ai), scoreLabel: aiLabel(match!.ai), eligible: match!.dealbreakers_passed && match!.ai?.score != null && match!.ai.score >= job.min_match_threshold,
    likedYou: likedBy.has(job.company_id),
    facts: [`Booth ${company?.booth_number ?? '—'}`, `${job.working_language} B2+`, job.relocation_support ? 'Relocation support' : 'No visa sponsorship'],
    skills: [...job.must_have_skills.map((skill) => ({ ...skill, priority: 'Required' as const })), ...job.nice_to_have_skills.map((skill) => ({ ...skill, priority: 'Preferred' as const }))].map(({ skill_id, priority }) => ({ name: skillNames.get(skill_id) ?? `Skill #${skill_id}`, matched: match!.ai?.requirements.some(r => r.skill_id === skill_id && r.status === 'supported') ?? false, priority })),
    warnings: match!.dealbreaker_reasons,
  }))

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(19rem,0.8fr)_minmax(0,1.4fr)]">
      <section aria-labelledby="profile-heading" className={`${panel} talent-profile min-w-0 p-4 sm:p-6`}>
        <div className="flex items-center justify-between gap-3"><h2 id="profile-heading" className="text-xl font-bold tracking-tight">Talent profile</h2><NotificationBell key={candidate.id} recipient="talent" identityId={candidate.id} /></div>
        <p className="mt-4 text-sm font-semibold">{candidate.full_name}<span className="mt-1 block text-xs font-normal text-slate-500">{candidate.anonymous_code}</span></p>
        <p className="mt-3 text-sm text-slate-600">{Object.entries(profile.languages).map(([name, level]) => `${name} ${level}`).join(' · ')}</p>
        {profile.needs_visa_sponsorship && <p className="mt-1 text-sm text-slate-600">Needs visa sponsorship</p>}
        <fieldset className="my-4 rounded-xl border border-slate-200 p-3 text-sm"><legend className="px-1 font-semibold">Our Own Private Model</legend>
          <p className="text-xs text-slate-600">Choose up to 3 resources to analyze.</p>
          <details className="mt-2 text-xs text-slate-600"><summary className="cursor-pointer text-espoo">How it works</summary><p className="mt-2">PDFs provide text; other links and images use saved descriptions. GitHub uses public retrieval. LinkedIn adds a +2 profile-completion bonus; its page is not fetched. Results show evidence relevance, not verified proficiency.</p></details>
          {savedProfile.materials.map(m => <label key={m.id} className="resource-option"><input type="checkbox" checked={analysisMaterials.includes(m.id)} onChange={e => setAnalysisMaterials(ids => e.target.checked ? [...ids,m.id].slice(0,3) : ids.filter(id => id!==m.id))} /><span className="min-w-0 break-words">{materialDisplayName(m)}<span className="sr-only">. {resourceAnalysisMode(m,ai.publicProfilesEnabled)}</span></span></label>)}
          {!savedProfile.materials.length && <p className="mt-2">Add a document or link below to get started.</p>}
          <label className="consent-row"><input type="checkbox" checked={analysisConsent} onChange={e => setAnalysisConsent(e.target.checked)} /><span>I have permission to analyze these resources with the private model.</span></label>
          <label className="consent-row"><input type="checkbox" checked={shareAnalysis} onChange={e => setShareAnalysis(e.target.checked)} /><span>Share scores and short evidence excerpts with Employer 001.</span></label>
          <button type="button" className={`${primary} mt-3 w-full`} disabled={ai.busy || (candidateId!==900001 && (!analysisConsent || analysisMaterials.length===0))} onClick={() => void ai.analyze(candidateId,analysisMaterials.length && analysisConsent ? analysisMaterials : undefined,shareAnalysis)}>{ai.busy ? 'Analyzing…' : 'Analyze My Profile'}</button>
        </fieldset>
        {ai.message && <p role="status" className="mt-2 text-sm">{ai.message}</p>}
        {ai.sources.length>0 && <details className="mt-3 text-xs text-slate-600"><summary className="cursor-pointer text-espoo">Source details ({ai.sources.length})</summary>{ai.sources.map(source => <p key={source.material_id} className="mt-2">Source #{source.material_id}: {sourceAnalysisNote(source)}</p>)}</details>}
        <details className="mt-5 border-t border-slate-200 pt-4"><summary className="cursor-pointer text-sm font-semibold">Documents & links <span className="font-normal text-slate-500">({savedProfile.materials.length})</span></summary><ProfileMaterials key={candidate.id} profile={savedProfile} skills={skills} onSaved={acceptSaved} /></details>
        {profileError && <p role="alert" className="mt-3 text-sm text-red-800">{profileError}</p>}
        <h3 className="mt-6 text-sm font-bold">Your skills</h3><p className="mt-1 text-xs text-slate-600">Self-declared skills. Analyze supporting evidence to check relevance.</p>
        <form className="skill-picker" onSubmit={(event) => {
          event.preventDefault()
          const skillId = Number(skillToAdd)
          if (!availableSkills.some(({ id }) => id === skillId)) return
          void saveSkills([...profile.skills.map(({ skill_id }) => skill_id), skillId])
          setSkillToAdd('')
        }}>
          <select aria-label="Skill to add" className={select} value={skillToAdd} onChange={(event) => setSkillToAdd(event.target.value)}>
            <option value="">Select a skill</option>
            {availableSkills.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}
          </select>
          <button type="submit" className={primary + ' min-h-11 shrink-0'} disabled={!skillToAdd || profileBusy}>Add skill</button>
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
      <div className="order-first min-w-0 lg:order-none">
        {jobDirectory && <section className="industry-controls"><button type="button" aria-expanded={filtersOpen} aria-controls={`industry-options-${candidate.id}`} onClick={()=>setFiltersOpen(value=>!value)}>Filter by industry <span>{filters.selected.length ? `${filters.selected.length} selected`:'All industries'} <span aria-hidden="true">⌄</span></span></button><div id={`industry-options-${candidate.id}`} className={`industry-filter-body ${filtersOpen?'is-open':''}`}><IndustryFilters categories={jobDirectory.industries} selected={filters.selected} onChange={filters.update} /></div></section>}
        <p className="mb-3 text-xs text-slate-500">Your choice applies to the company across all its job openings.</p>
        <div className="talent-view-toggle" aria-label="Job discovery mode">
          <button type="button" aria-pressed={view === 'swipe'} onClick={() => setView('swipe')}>✦ Swipe & connect</button>
          <button type="button" aria-pressed={view === 'list'} onClick={() => setView('list')}>All jobs</button>
          <button type="button" aria-pressed={view === 'updates'} onClick={() => setView('updates')}>
            Hiring updates ({swipeStore.swipes.filter((row) => row.actor === 'employer' && row.candidate_id === candidate.id).length
              + swipeStore.tasks.filter((task) => task.candidate_id === candidate.id && !task.submission_url).length})
          </button>
        </div>
        {!jobDirectory && !jobError && <p role="status">Loading job openings…</p>}
        {jobDirectory && !visibleJobs.length && !jobError && <JobEmptyState hasJobs={jobs.length > 0} />}
        {view === 'swipe' && <SwipeDeck side="talent" key={candidate.id} cards={discoveryCards} loading={busy || !jobDirectory || !swipeStore.ready} error={jobError || swipeStore.error || (current?.failed ? 'Could not calculate your matches.' : '')}
          onRetry={() => { swipeStore.retry(); setAttempt((value) => value + 1) }}
          onUndo={(jobId) => swipeStore.undo({ candidate_id: candidate.id, company_id: jobCompanyId(jobs, jobId), actor: 'talent' })}
          onDecide={(jobId, decision) => swipeStore.decide({ candidate_id: candidate.id, company_id: jobCompanyId(jobs, jobId), actor: 'talent', decision })}
          saved={own.filter((row) => row.decision === 'like').map((row) => ({ id: row.company_id, name: companyById.get(row.company_id)?.name ?? 'Employer', mutual: likedBy.has(row.company_id), reviewId: jobs.find((job) => job.company_id === row.company_id)?.id }))}
          onReview={(id) => { setOpenJob(jobs.some((job) => job.id === id) ? id : null); if (!visibleJobs.some((job) => job.id === id)) filters.update([]); setView('list') }} />}
        {view === 'updates' && <CandidateUpdates key={candidate.id} candidateId={candidate.id} companies={companies} store={swipeStore} />}
      <section hidden={view !== 'list'} aria-labelledby="matches-heading" className={`${panel} min-w-0 overflow-hidden`}>
        <div className="border-b border-slate-200 p-5 sm:p-6">
          <h2 id="matches-heading" className="text-xl font-bold tracking-tight">Live job matches</h2>
          <p className="mt-1 text-sm text-slate-600">Sorted by match score. Select a job to see the breakdown.</p>
          <p role="status" className="mt-2 min-h-5 text-xs font-semibold text-espoo">
            {busy ? 'Updating match scores…' : current.failed ? '' : `${visibleJobs.length} jobs shown`}
          </p>
          {current?.failed && (
            <p role="alert" className="text-sm text-red-800">Could not refresh scores. <button type="button" className="cursor-pointer font-semibold underline" onClick={() => setAttempt((value) => value + 1)}>Retry</button></p>
          )}
        </div>
        {rows.map(({ job, company, match }) => (
          <div key={job.id}>
            <button type="button" aria-expanded={openJob === job.id} onClick={() => setOpenJob(openJob === job.id ? null : job.id)}
              className={`group flex w-full cursor-pointer items-center gap-3 border-b border-slate-100 px-4 py-4 text-left transition-colors hover:bg-mist focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-espoo motion-reduce:transition-none sm:gap-4 sm:px-6 ${openJob === job.id ? 'bg-mist' : ''}`}>
              <span className="shrink-0 rounded-lg bg-mist px-2 py-2 text-xs font-bold text-espoo">{company?.booth_number ?? '—'}</span>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold">{job.title}</span>
                <span className="block text-xs leading-relaxed text-slate-600">{job.company_name} · {job.industry_label}</span>
              </span>
              <span className={`shrink-0 text-lg font-bold tabular-nums text-espoo ${busy ? 'opacity-50' : ''}`}>{aiLabel(match?.ai)}</span>
              <span aria-hidden="true" className={`grid size-8 shrink-0 place-items-center rounded-full border text-espoo transition-colors group-hover:border-blue-200 group-hover:bg-blue-100 motion-reduce:transition-none ${openJob === job.id ? 'border-blue-200 bg-blue-100' : 'border-blue-100 bg-white'}`}>
                <svg viewBox="0 0 20 20" fill="none" className={`size-4 transition-transform motion-reduce:transition-none ${openJob === job.id ? 'rotate-180' : ''}`}>
                  <path d="m5 8 5 5 5-5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </span>
            </button>
            {openJob === job.id && match && (
              <div><div className="px-5"><JobRequirements job={job} skills={skills} /></div><MatchBreakdown key={job.id} match={match} busy={busy} onClose={() => setOpenJob(null)} /></div>
            )}
          </div>
        ))}
        {jobError && <p role="alert" className="p-5 text-sm text-red-800">{jobError} <button onClick={() => setAttempt((value) => value + 1)} className="underline">Retry</button></p>}
      </section>
      </div>
    </div>
  )
}
