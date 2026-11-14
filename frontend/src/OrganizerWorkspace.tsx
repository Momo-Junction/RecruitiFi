import { useEffect, useState } from 'react'
import { loadCompanyMatches, type Company, type RankedMatch } from './api'

const panel = 'rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6'
const button = 'cursor-pointer rounded-lg border border-blue-200 px-3 py-2 text-sm font-semibold text-espoo hover:bg-mist disabled:cursor-default disabled:opacity-50'

type Queue = { company: Company; eligible: RankedMatch[] }

function planIntroductions(queues: Queue[]) {
  const assigned = new Set<string>()
  // Try employers with fewer options first so a busy booth doesn't get first pick by default.
  return [...queues]
    .sort((a, b) => a.eligible.length - b.eligible.length || a.company.id - b.company.id)
    .map(({ company, eligible }) => {
      const match = eligible.find(({ anonymous_code }) => !assigned.has(anonymous_code))
      if (match) assigned.add(match.anonymous_code)
      return { company, match, hasEligible: eligible.length > 0 }
    })
}

export function OrganizerWorkspace({ companies }: { companies: Company[] }) {
  const [queues, setQueues] = useState<Queue[]>()
  const [error, setError] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [shortlist, setShortlist] = useState<Set<string>>(new Set())

  useEffect(() => {
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      Promise.all(companies.map(async (company) => {
        const matches = await loadCompanyMatches(company.id, controller.signal)
        return { company, eligible: matches.filter((match) => match.dealbreakers_passed && match.meets_threshold) }
      })).then((next) => {
        if (!controller.signal.aborted) setQueues(next)
      }).catch(() => {
        if (!controller.signal.aborted) setError(true)
      })
    }, 0)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [companies, refresh])

  const plan = planIntroductions(queues ?? [])
  const introductions = plan.filter(({ match }) => match !== undefined)
  const needsHelp = plan.filter(({ match }) => match === undefined)
  const keyFor = (company: Company, match: RankedMatch) => `${company.id}:${match.anonymous_code}`

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-bold tracking-tight">Meeting plan</h2>
        <button type="button" className={button} disabled={!queues && !error} onClick={() => {
          setQueues(undefined)
          setError(false)
          setRefresh((value) => value + 1)
        }}>Refresh suggestions</button>
      </div>
      {error && <p role="alert" className={panel}>Couldn’t load employer matches. Refresh suggestions to try again.</p>}
      {!queues && !error && <p role="status" className={panel}>Finding introductions across the event…</p>}
      {queues && (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)]">
          <section aria-labelledby="introductions" className={panel}>
            <h3 id="introductions" className="text-lg font-bold">Suggested introductions ({introductions.length})</h3>
            <p className="mt-1 text-sm text-slate-600">One suggestion per employer and candidate, starting with employers who have fewer options. Shortlist the conversations you want to follow up on.</p>
            {introductions.length === 0 && <p className="mt-4 rounded-lg bg-mist p-3 text-sm">No eligible introductions yet.</p>}
            <ul className="mt-4 space-y-3">
              {introductions.map(({ company, match }) => {
                if (!match) return null
                const key = keyFor(company, match)
                const selected = shortlist.has(key)
                const topics = [...match.must_have_skills, ...match.nice_to_have_skills]
                  .filter(({ evidence_tier }) => evidence_tier !== 'missing')
                  .slice(0, 2).map(({ skill_name }) => skill_name)
                return (
                  <li key={key} className="rounded-xl border border-slate-200 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-xs font-semibold text-espoo">Booth {company.booth_number} · {match.anonymous_code}</p>
                        <h4 className="mt-1 font-bold">{company.name}</h4>
                      </div>
                      <button type="button" className={button} aria-pressed={selected} aria-label={`Shortlist ${company.name} and ${match.anonymous_code}`} onClick={() => setShortlist((previous) => {
                        const next = new Set(previous)
                        if (next.has(key)) next.delete(key)
                        else next.add(key)
                        return next
                      })}>{selected ? '✓ Shortlisted' : 'Shortlist'}</button>
                    </div>
                    <p className="mt-3 text-sm text-slate-600">{topics.length ? `Talk about ${topics.join(' and ')}.` : 'Ask about a recent project relevant to this role.'}</p>
                  </li>
                )
              })}
            </ul>
          </section>
          <section aria-labelledby="support" className={panel}>
            <h3 id="support" className="text-lg font-bold">Booths that may need help ({needsHelp.length})</h3>
            {needsHelp.length === 0 && <p className="mt-3 text-sm text-slate-600">{companies.length ? 'Every booth has a suggested introduction.' : 'No employers have joined the event yet.'}</p>}
            <ul className="mt-3 space-y-3">
              {needsHelp.map(({ company, hasEligible }) => (
                <li key={company.id} className="rounded-xl bg-mist p-3 text-sm">
                  <p className="font-semibold">{company.name} · {company.booth_number}</p>
                  <p className="mt-1 text-slate-600">{hasEligible ? 'Eligible candidates are already suggested elsewhere. Try a later meeting round.' : 'No eligible candidates yet. Check in with the employer about the role.'}</p>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  )
}
