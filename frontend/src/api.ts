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

export interface RankedMatch extends Match {
  candidate_id: number
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

const apiUrl = (import.meta.env.VITE_API_URL || (import.meta.env.PROD ? '' : 'http://127.0.0.1:8000')).replace(/\/$/, '')

export type MaterialCategory = 'cv' | 'project' | 'certificate' | 'research' | 'linkedin' | 'github' | 'website'
export interface ProfileMaterial {
  id: number
  category: MaterialCategory
  title: string
  description: string
  skill_id: number | null
  url: string | null
  filename: string | null
}
export interface SavedProfile {
  candidate: Candidate
  materials: ProfileMaterial[]
}
export function documentUrl(candidateId: number, id: number) {
  return `${apiUrl}/api/candidates/${candidateId}/documents/${id}`
}
export async function profileRequest(candidateId: number, path = 'profile', options?: RequestInit): Promise<SavedProfile> {
  const response = await fetch(`${apiUrl}/api/candidates/${candidateId}/${path}`, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not save the profile. Check your entries and try again.')
  }
  return response.json()
}

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

export async function acceptCompanyMeeting(companyId: number, anonymousCode: string, humanReviewed = false): Promise<MeetingContact> {
  const response = await fetch(
    `${apiUrl}/api/companies/${companyId}/matches/${encodeURIComponent(anonymousCode)}/accept?human_reviewed=${humanReviewed}`,
    { method: 'POST' },
  )
  if (!response.ok) throw new Error(response.status === 409
    ? 'This candidate no longer meets the saved role requirements. Refresh the queue.'
    : 'Could not accept the meeting. Try again.')
  return response.json()
}

export interface SwipeDecision {
  candidate_id: number
  company_id: number
  actor: 'talent' | 'employer'
  decision: 'like' | 'pass'
}

export function loadSwipes(signal: AbortSignal) {
  return get<SwipeDecision[]>('swipes', signal)
}

export async function saveSwipe(swipe: SwipeDecision): Promise<SwipeDecision> {
  const response = await fetch(`${apiUrl}/api/swipes`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(swipe),
  })
  if (!response.ok) throw new Error('Could not save your swipe. Please try again.')
  return response.json()
}

export async function undoSwipe(swipe: Pick<SwipeDecision, 'actor' | 'candidate_id' | 'company_id'>) {
  const response = await fetch(`${apiUrl}/api/swipes/${swipe.actor}/${swipe.candidate_id}/${swipe.company_id}`, { method: 'DELETE' })
  if (!response.ok) throw new Error('Could not undo your swipe. Please try again.')
}
