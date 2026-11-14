export interface Skill {
  id: number
  esco_uri: string
  name: string
  category: string
}

export interface WeightedSkill {
  skill_id: number
  weight: number
}

export type CompanyRole = Pick<Company,
  'working_language' | 'relocation_support' | 'min_match_threshold' | 'must_have_skills' | 'nice_to_have_skills'
>

interface SkillSignal {
  skill_id: number
  skill_name: string
  evidence_tier: EvidenceTier | 'missing'
}

interface AuditSkill extends SkillSignal {
  weight: number
  multiplier: number
  points: number
}

export interface AuditEntry {
  id: number
  calculated_at: string
  source: 'simulation' | 'employer_queue' | 'meeting_review' | 'event_metrics'
  company_name: string
  candidate_code: string | null
  inputs: {
    scoring_version: string
    working_language: string
    minimum_language_level: string
    candidate_language_level: string | null
    has_cv: boolean
    has_portfolio: boolean
    needs_visa_sponsorship: boolean
    relocation_support: boolean
  }
  result: Omit<Match, 'improvement_hints'> & {
    must_have_skills: AuditSkill[]
    nice_to_have_skills: AuditSkill[]
  }
}

export interface EventMetrics {
  talent_count: number
  company_count: number
  pair_count: number
  average_score: number | null
  passed_dealbreakers: number
  below_threshold: number
  filtered_percent: number | null
}

export async function refreshEventMetrics(signal: AbortSignal): Promise<EventMetrics> {
  const response = await fetch(`${apiUrl}/api/audit/metrics`, { method: 'POST', signal })
  if (!response.ok) throw new Error('Could not calculate event metrics.')
  return response.json()
}

export function loadAuditLog(signal: AbortSignal, beforeId?: number) {
  const cursor = beforeId === undefined ? '' : `?before_id=${beforeId}`
  return get<{ entries: AuditEntry[]; next_before_id: number | null }>(`audit/calculations${cursor}`, signal)
}

export interface RankedMatch extends Match {
  anonymous_code: string
  must_have_skills: SkillSignal[]
  nice_to_have_skills: SkillSignal[]
}

export interface MeetingContact {
  full_name: string
  email: string
  conversation_starter: string
}

export interface Company {
  id: number
  name: string
  industry: string
  booth_number: string
  relocation_support: boolean
  working_language: string
  min_match_threshold: number
  must_have_skills: WeightedSkill[]
  nice_to_have_skills: WeightedSkill[]
}

export type EvidenceTier = 'self_declared' | 'portfolio' | 'certificate'

export interface CandidateProfile {
  has_cv: boolean
  has_portfolio: boolean
  languages: Record<string, string>
  needs_visa_sponsorship: boolean
  skills: {
    skill_id: number
    evidence_tier: EvidenceTier
  }[]
}

export interface Candidate extends CandidateProfile {
  id: number
  anonymous_code: string
  full_name: string
  email: string
}

export interface ImprovementHint {
  action: string
  point_gain: number
  kind: 'certificate' | 'cv' | 'portfolio'
  skill_id: number | null
}

export interface Match {
  company_id: number
  total_score: number
  min_match_threshold: number
  meets_threshold: boolean
  dealbreakers_passed: boolean
  dealbreaker_reasons: string[]
  must_have_points: number
  nice_to_have_points: number
  profile_proof_points: number
  improvement_hints: ImprovementHint[]
}

const apiUrl = (import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

async function get<T>(resource: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${apiUrl}/api/${resource}`, { signal })
  if (!response.ok) throw new Error(`Could not load ${resource} (${response.status}).`)
  return response.json()
}

export async function loadDirectory(signal: AbortSignal) {
  const [companies, candidates, skills] = await Promise.all([
    get<Company[]>('companies', signal),
    get<Candidate[]>('candidates', signal),
    get<Skill[]>('skills', signal),
  ])
  return { companies, candidates, skills }
}

export async function simulateMatch(companyId: number, candidate: CandidateProfile, signal: AbortSignal): Promise<Match> {
  const response = await fetch(`${apiUrl}/api/match/simulate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ company_id: companyId, candidate }),
    signal,
  })
  if (!response.ok) throw new Error(`Could not score employer ${companyId} (${response.status}).`)
  return response.json()
}

export async function loadCompanyMatches(companyId: number, signal: AbortSignal) {
  return get<RankedMatch[]>(`companies/${companyId}/matches`, signal)
}

export async function saveCompanyRole(companyId: number, role: CompanyRole): Promise<Company> {
  const response = await fetch(`${apiUrl}/api/companies/${companyId}/role`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(role),
  })
  if (!response.ok) throw new Error('Could not save the role. Check the selected skills and try again.')
  return response.json()
}

export async function acceptCompanyMeeting(companyId: number, anonymousCode: string): Promise<MeetingContact> {
  const response = await fetch(
    `${apiUrl}/api/companies/${companyId}/matches/${encodeURIComponent(anonymousCode)}/accept`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(response.status === 409
    ? 'This candidate no longer meets the saved role requirements. Refresh the queue.'
    : 'Could not accept the meeting. Try again.')
  return response.json()
}
