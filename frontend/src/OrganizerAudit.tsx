import { Fragment, useEffect, useState } from 'react'
import { loadAuditLog, refreshEventMetrics, type AuditEntry, type EventMetrics } from './api'

const panel = 'rounded-2xl border border-slate-200 bg-white shadow-sm'
const button = 'rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-espoo enabled:cursor-pointer enabled:hover:bg-mist disabled:opacity-50'
const format = new Intl.NumberFormat('en', { maximumFractionDigits: 1 })
const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Europe/Helsinki' })
const sourceLabels = {
  simulation: 'Talent simulation', employer_queue: 'Employer queue', meeting_review: 'Meeting review', event_metrics: 'Event metrics',
}
const tiers = { missing: 'Missing', self_declared: 'Self-declared', portfolio: 'Portfolio', certificate: 'Certificate' }
const percent = (value: number | null) => value === null ? '—' : `${format.format(value)}%`

function CalculationDetails({ entry }: { entry: AuditEntry }) {
  const { inputs, result } = entry
  const groups = [
    { label: 'Must-have', skills: result.must_have_skills, points: result.must_have_points, max: 70 },
    { label: 'Nice-to-have', skills: result.nice_to_have_skills, points: result.nice_to_have_points, max: 20 },
  ]
  return (
    <div className="space-y-4 p-4 sm:p-5">
      <p className="font-semibold text-espoo">
        {result.must_have_points} must-have + {result.nice_to_have_points} nice-to-have + {result.profile_proof_points} proof = {result.total_score} / 100
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        {groups.map(({ label, skills, points, max }) => (
          <section key={label} className="rounded-xl border border-blue-100 bg-white p-3">
            <h4 className="mb-2 font-semibold">{label} · {points}/{max}</h4>
            <ul className="divide-y divide-slate-100">
              {skills.map((skill) => (
                <li key={skill.skill_id} className="flex flex-wrap justify-between gap-x-3 py-1.5 text-sm">
                  <span>{skill.skill_name} <span className="text-slate-600">· {tiers[skill.evidence_tier]}</span></span>
                  <span className="font-mono text-xs leading-5">{skill.weight} × {skill.multiplier.toFixed(1)} = {skill.points}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div><dt className="font-semibold">Profile proof</dt><dd>CV {inputs.has_cv ? '+5' : '+0'} · Portfolio {inputs.has_portfolio ? '+5' : '+0'}</dd></div>
        <div><dt className="font-semibold">Working language</dt><dd>{inputs.working_language} {inputs.candidate_language_level ?? 'unlisted'} · Minimum {inputs.minimum_language_level}</dd></div>
        <div><dt className="font-semibold">Visa compatibility</dt><dd>Sponsorship needed: {inputs.needs_visa_sponsorship ? 'yes' : 'no'} · Relocation support: {inputs.relocation_support ? 'yes' : 'no'}</dd></div>
        <div><dt className="font-semibold">Eligibility</dt><dd>{result.dealbreakers_passed ? 'Dealbreakers passed' : 'Dealbreaker failed'} · {result.min_match_threshold}% threshold · Rules v{inputs.scoring_version}</dd></div>
      </dl>
      {result.dealbreaker_reasons.length > 0 && <ul className="list-disc pl-5 text-sm">{result.dealbreaker_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
    </div>
  )
}

export function OrganizerAudit() {
  const [metrics, setMetrics] = useState<EventMetrics>()
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [page, setPage] = useState(0)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    // Defer the write-producing refresh until after React's development mount check.
    const timer = window.setTimeout(async () => {
      try {
        const totals = await refreshEventMetrics(controller.signal)
        const log = await loadAuditLog(controller.signal)
        if (controller.signal.aborted) return
        setMetrics(totals)
        setEntries(log.entries)
        setCursor(log.next_before_id)
        setOpenId(null)
        setPage(0)
      } catch {
        if (!controller.signal.aborted) setError('Could not refresh the audit dashboard. Try again.')
      } finally {
        if (!controller.signal.aborted) setBusy(false)
      }
    }, 0)
    return () => { window.clearTimeout(timer); controller.abort() }
  }, [refresh])

  async function loadPage(beforeId?: number) {
    setBusy(true)
    setError('')
    try {
      const log = await loadAuditLog(AbortSignal.timeout(10000), beforeId)
      setEntries(log.entries)
      setCursor(log.next_before_id)
      setOpenId(null)
      setPage(beforeId === undefined ? 0 : page + 1)
    } catch {
      setError('Could not load the audit log. Try again.')
    } finally {
      setBusy(false)
    }
  }

  const cards = [
    { label: 'Total Active Talent', value: metrics?.talent_count, detail: 'Registered event profiles' },
    { label: 'Participating Espoo Companies', value: metrics?.company_count, detail: 'Companies with a saved role' },
    { label: 'Avg Match Signal Score', value: percent(metrics?.average_score ?? null), detail: metrics ? `Across ${metrics.pair_count} candidate–company pairs` : 'Across all candidate–company pairs' },
    { label: 'Irrelevant Noise Filtered Out', value: percent(metrics?.filtered_percent ?? null), detail: metrics ? `${metrics.below_threshold} of ${metrics.passed_dealbreakers} pairs passing dealbreakers fell below threshold` : 'Below threshold among pairs passing dealbreakers' },
  ]

  return (
    <div className="space-y-6">
      <section aria-labelledby="metrics-heading" aria-busy={busy && !metrics}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 id="metrics-heading" className="text-xl font-bold tracking-tight">Live Event Metrics</h2>
          <button type="button" className={button} disabled={busy} onClick={() => { setBusy(true); setError(''); setRefresh((value) => value + 1) }}>Refresh metrics</button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {cards.map(({ label, value, detail }) => (
            <article key={label} className={`${panel} border-t-4 border-t-espoo p-4`}>
              <h3 className="text-sm font-semibold">{label}</h3>
              <p className="my-2 text-3xl font-bold tabular-nums text-espoo">{value ?? '—'}</p>
              <p className="text-xs leading-relaxed text-slate-600">{detail}</p>
            </article>
          ))}
        </div>
      </section>
      <section aria-label="Responsible recruitment controls" className={`${panel} grid gap-4 p-5 sm:grid-cols-3`}>
        <div><h2 className="font-bold">Deterministic scoring</h2><p className="mt-1 text-sm text-slate-600">Role weight × evidence multiplier, plus CV and portfolio proof. The calculation uses a fixed formula.</p></div>
        <div><h2 className="font-bold">Blind-first review</h2><p className="mt-1 text-sm text-slate-600">Scoring uses skills, proof, language level and visa compatibility. Name, email and demographic fields are excluded from scoring.</p></div>
        <div><h2 className="font-bold">Human decisions</h2><p className="mt-1 text-sm text-slate-600">Employers set role requirements and choose whether to accept meetings.</p></div>
        <p className="text-xs leading-relaxed text-slate-600 sm:col-span-3">
          Synthetic pilot demo for reviewing recruitment controls. Formal compliance requires a separate assessment.
          {' '}<a className="font-semibold text-espoo underline" href="https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng">EU AI Act</a>
          {' · '}<a className="font-semibold text-espoo underline" href="https://www.espoo.fi/en/working-life/working-espoo/how-we-recruit">Espoo recruitment practices</a>
        </p>
      </section>
      <section aria-labelledby="audit-heading" className={`${panel} min-w-0 overflow-hidden`}>
        <div className="flex flex-wrap items-start justify-between gap-3 p-4 sm:p-5">
          <div>
            <h2 id="audit-heading" className="text-xl font-bold tracking-tight">Algorithmic Transparency &amp; Audit Log</h2>
            <p className="mt-1 text-sm text-slate-600">Expand a calculation to inspect the recorded inputs and points. Times shown in Helsinki time.</p>
          </div>
          <button type="button" className={button} disabled={busy} onClick={() => void loadPage()}>Latest calculations</button>
        </div>
        {busy && <p role="status" className="px-5 pb-4 text-sm text-slate-600">Loading audit data…</p>}
        {error && <p role="alert" className="px-5 pb-4 text-sm text-red-800">{error}</p>}
        {!busy && !error && entries.length === 0 && <p className="border-t border-slate-200 p-5 text-sm text-slate-600">No calculations recorded yet.</p>}
        {entries.length > 0 && (
          <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Scrollable audit calculations">
            <table className="w-full min-w-[38rem] text-left text-sm">
              <thead className="bg-mist text-espoo"><tr>{['Calculation', 'Employer / candidate', 'Score', 'Outcome', 'Inputs'].map((label) => <th scope="col" key={label} className="px-4 py-3">{label}</th>)}</tr></thead>
              <tbody>
                {entries.map((entry) => {
                  const { result } = entry
                  const outcome = !result.dealbreakers_passed ? 'Dealbreaker' : result.meets_threshold ? 'Eligible' : 'Below threshold'
                  return (
                    <Fragment key={entry.id}>
                      <tr className="border-b border-slate-200">
                        <td className="px-4 py-3"><p className="font-semibold">{sourceLabels[entry.source]}</p><time className="text-xs text-slate-600" dateTime={entry.calculated_at}>{date.format(new Date(entry.calculated_at))}</time></td>
                        <td className="px-4 py-3">{entry.company_name}<p className="text-xs text-slate-600">{entry.candidate_code ?? 'Temporary profile'}</p></td>
                        <td className="px-4 py-3 font-semibold tabular-nums">{percent(result.total_score)}</td>
                        <td className="px-4 py-3">{outcome}</td>
                        <td className="px-4 py-3"><button type="button" aria-expanded={openId === entry.id} className="cursor-pointer font-semibold text-espoo underline" onClick={() => setOpenId(openId === entry.id ? null : entry.id)}>{openId === entry.id ? 'Hide formula' : 'View formula'}</button></td>
                      </tr>
                      {openId === entry.id && <tr className="bg-mist/70"><td colSpan={5}><CalculationDetails entry={entry} /></td></tr>}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {entries.length > 0 && (
          <div className="flex items-center justify-between gap-3 p-4 text-sm">
            <span className="text-slate-600">Page {page + 1}</span>
            <button type="button" className={button} disabled={busy || cursor === null} onClick={() => cursor !== null && void loadPage(cursor)}>Older calculations</button>
          </div>
        )}
      </section>
    </div>
  )
}
