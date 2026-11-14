import type { EvidenceAnalysisView } from './EvidenceAnalysis'

export const demoCandidateId = 900001
type Analysis = Pick<EvidenceAnalysisView, 'findings' | 'sources'> & { material_id: number }
export type DemoJob = { id: string; candidate_id: number; material_id: number; status: string; error_code: string | null }
const root = '/api/ai-demo/candidates/900001'
const jobPattern = /^900001a1900001a1[0-9a-f]{16}$/

function materialPath(candidateId: number, materialId: number) {
  if (candidateId !== demoCandidateId || !Number.isSafeInteger(materialId) || materialId < 1) throw new Error('Only the provisioned fictional demo project is available.')
  return `${root}/materials/${materialId}`
}
async function request<T>(path: string, method: 'GET' | 'POST', signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { method, credentials: 'same-origin', cache: 'no-store', signal })
  if (!response.ok) {
    const messages: Record<number, string> = { 401: 'The hosted application requires sign-in.', 403: 'Only the unchanged fictional demo project is available.', 404: 'The synthetic AI demo is disabled or unavailable.', 409: 'Analysis is busy. Try again later.', 429: 'Analysis is busy or cooling down. Try again later.', 503: 'The local analysis service is unavailable.' }
    throw Object.assign(new Error(messages[response.status] ?? `Analysis unavailable (${response.status}).`), { status: response.status })
  }
  return response.json() as Promise<T>
}
function checkJob(job: DemoJob, materialId: number) {
  if (!job || !jobPattern.test(job.id) || job.candidate_id !== demoCandidateId || job.material_id !== materialId || !['queued', 'running', 'completed', 'failed', 'timed_out', 'cancelled', 'interrupted'].includes(job.status)) throw new Error('Analysis response is outside the demo scope.')
}
export async function loadDemoMaterial(candidateId: number, materialId: number, signal?: AbortSignal) {
  const data = await request<{ enabled: boolean; job: DemoJob | null }>(materialPath(candidateId, materialId), 'GET', signal)
  if (!data || data.enabled !== true) throw new Error('Synthetic demo is unavailable.')
  if (data.job) checkJob(data.job, materialId)
  return data
}
export async function startDemoAnalysis(candidateId: number, materialId: number, signal?: AbortSignal) {
  const data = await request<{ job_id: string }>(`${materialPath(candidateId, materialId)}/analysis`, 'POST', signal)
  if (!data || !jobPattern.test(data.job_id)) throw new Error('Invalid demo job response.')
  return data.job_id
}
export async function loadDemoResult(candidateId: number, materialId: number, jobId: string, signal?: AbortSignal) {
  materialPath(candidateId, materialId)
  if (!jobPattern.test(jobId)) throw new Error('Invalid demo job.')
  const data = await request<{ job: DemoJob; analysis: Analysis | null }>(`${root}/analysis-jobs/${jobId}/result`, 'GET', signal)
  if (!data) throw new Error('Invalid demo result.')
  checkJob(data.job, materialId)
  if (data.analysis && (data.analysis.material_id !== materialId || !Array.isArray(data.analysis.findings) || !Array.isArray(data.analysis.sources))) throw new Error('Invalid demo result.')
  return data
}
export async function loadEmployerDemo(companyId: number, candidateId: number, signal?: AbortSignal) {
  if (companyId !== 1 || candidateId !== demoCandidateId) throw new Error('Only Employer 001 and fictional candidate 900001 are available.')
  const data = await request<{ candidate_id: number; status: string; analyses: Analysis[] }>(`${root}/employers/1/findings`, 'GET', signal)
  if (!data || data.candidate_id !== demoCandidateId || !Array.isArray(data.analyses) || data.analyses.length > 1 || data.analyses.some(analysis => !analysis || !Number.isSafeInteger(analysis.material_id) || analysis.material_id < 1 || !Array.isArray(analysis.findings) || !Array.isArray(analysis.sources))) throw new Error('Invalid demo findings.')
  return data
}
