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
  const needsHelp = plan.filter(({ match }) => match === undefined)

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-2xl font-bold tracking-tight">Meeting plan</h2>
        <button type="button" className={button} disabled={!queues && !error} onClick={() => {
          setQueues(undefined)
          setError(false)
          setRefresh((value) => value + 1)
        }}>Refresh booth status</button>
      </div>
      {error && <p role="alert" className={panel}>Couldn’t load employer matches. Refresh booth status to try again.</p>}
      {!queues && !error && <p role="status" className={panel}>Checking employer support needs…</p>}
      {queues && (
        <div className="space-y-5">
          <section aria-labelledby="support" className={panel}>
            <h3 id="support" className="text-lg font-bold">Booths that may need help ({needsHelp.length})</h3>
            {needsHelp.length === 0 && <p className="mt-3 text-sm text-slate-600">{companies.length ? 'No booths need extra support right now.' : 'No employers have joined the event yet.'}</p>}
            <ul className="mt-3 space-y-3">
              {needsHelp.map(({ company, hasEligible }) => (
                <li key={company.id} className="rounded-xl bg-mist p-3 text-sm">
                  <p className="font-semibold">{company.name} · {company.booth_number}</p>
                  <p className="mt-1 text-slate-600">{hasEligible ? 'Eligible candidates are available. Coordinate a meeting with the employer.' : 'No eligible candidates yet. Check in with the employer about the role.'}</p>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  )
}
