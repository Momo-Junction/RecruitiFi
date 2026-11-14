import { useState } from 'react'
import type { IndustryCategory, IndustryId, JobOpening, Skill } from './api'

export function industryFilterKey(candidateId: number) { return `recruitifi.industries.${candidateId}` }
export function readIndustryFilters(candidateId: number): IndustryId[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(industryFilterKey(candidateId)) ?? '[]')
    const known = new Set(['it', 'business_services', 'logistics', 'health_sector', 'restaurant', 'cleaning', 'engineering'])
    return Array.isArray(saved) ? [...new Set(saved.filter((value): value is IndustryId => typeof value === 'string' && known.has(value)))] : []
  } catch { return [] }
}
export function saveIndustryFilters(candidateId: number, selected: IndustryId[]) {
  try { sessionStorage.setItem(industryFilterKey(candidateId), JSON.stringify(selected)) } catch { /* In-memory filters still work. */ }
}
export function JobEmptyState({ hasJobs }: { hasJobs: boolean }) {
  return <p role="status" className="mb-4 rounded-lg bg-mist p-4 text-sm">{hasJobs ? 'No active jobs match your selected industries. Clear Filters to explore all jobs.' : 'No active job openings yet. Ask the demo operator to initialize jobs.'}</p>
}
export function useIndustryFilters(candidateId: number) {
  const [selected, setSelected] = useState(() => readIndustryFilters(candidateId))
  function update(next: IndustryId[]) {
    setSelected(next)
    saveIndustryFilters(candidateId, next)
  }
  return { selected, update }
}
export function filterJobs(jobs: JobOpening[], selected: IndustryId[]) {
  return jobs.filter((job) => job.active && (!selected.length || selected.includes(job.industry)))
}
export function jobCompanyId(jobs: JobOpening[], jobId: number) {
  const job = jobs.find((item) => item.id === jobId)
  if (!job) throw new Error('This job is no longer available. Refresh discovery before swiping.')
  return job.company_id
}
export function IndustryFilters({ categories, selected, onChange }: {
  categories: IndustryCategory[]; selected: IndustryId[]; onChange: (next: IndustryId[]) => void
}) {
  return <fieldset className="mb-4 rounded-xl border border-slate-200 bg-white p-4">
    <legend className="px-1 text-sm font-bold">Filter jobs by industry</legend>
    <div className="flex flex-wrap gap-2">{categories.map(({ id, label }) => <button key={id} type="button" aria-pressed={selected.includes(id)}
      className={`cursor-pointer rounded-full border px-3 py-1.5 text-sm ${selected.includes(id) ? 'border-espoo bg-espoo text-white' : 'border-blue-200 text-espoo hover:bg-mist'}`}
      onClick={() => onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id])}>{label}</button>)}</div>
    <button type="button" disabled={!selected.length} onClick={() => onChange([])} className="mt-3 cursor-pointer text-xs font-semibold text-espoo underline disabled:opacity-50">Clear Filters</button>
    <p className="mt-2 text-xs text-slate-500">{selected.length ? 'Showing any selected industry.' : 'Showing all active jobs.'} Synthetic demo openings only.</p>
  </fieldset>
}
export function JobRequirements({ job, skills }: { job: JobOpening; skills: Skill[] }) {
  const names = new Map(skills.map((skill) => [skill.id, skill.name]))
  return <div className="mt-3 space-y-2 text-sm text-slate-600">
    <p>{job.industry_label}</p>
    <p>{job.description}</p>
    <p><strong>Required:</strong> {job.must_have_skills.map((skill) => `${names.get(skill.skill_id) ?? `Skill #${skill.skill_id}`} (${skill.weight})`).join(' · ')}</p>
    <p><strong>Preferred:</strong> {job.nice_to_have_skills.map((skill) => `${names.get(skill.skill_id) ?? `Skill #${skill.skill_id}`} (${skill.weight})`).join(' · ') || 'None'}</p>
    <p>{job.working_language} B2+ · {job.min_match_threshold}% threshold · {job.relocation_support ? 'Relocation support' : 'No visa sponsorship'}{job.active ? '' : ' · Inactive opening'}</p>
    <p className="text-xs">Synthetic demo opening · likes and passes apply to the company across its openings.</p>
  </div>
}
