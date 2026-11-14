import { useEffect, useRef, useState } from 'react'
import { readDemoAccount } from './demoNavigation'

export type AiMatch = { display_score?:number; profile_bonus?:number; bonus_reason?:string|null; status: string; score: number | null; requirements: { skill_id: number; skill_name: string; status: string; excerpt: string | null; material_id: number | null; coverage: number }[] }
type Profile = { public_profile_retrieval_enabled?:boolean; status: string; matches: Record<string, AiMatch>; detail?: string | null; sources?: {material_id:number; category:string; content_status:string; detail?:string}[] }
const active = (status: string) => ['queued', 'running', 'pending'].includes(status)
export function displayAiScore(match?:AiMatch):number|null {
  const score=match?.display_score ?? match?.score
  return typeof score==='number' && Number.isFinite(score) && score>=0 && score<=100 ? score:null
}
export function aiLabel(match?: AiMatch) {
  const score=displayAiScore(match)
  return match?.status === 'completed' && score!==null ? `${score.toFixed(1)}% ${match.profile_bonus ? 'combined fit' : 'AI evidence fit'}` : ['unavailable','failed','timed_out','interrupted','cancelled'].includes(match?.status ?? '') ? 'AI score unavailable' : active(match?.status ?? '') ? 'Analyzing…' : 'Not analyzed'
}
export function AiExplanation({ match }: { match?: AiMatch }) {
  return <section className="mt-3 text-xs" aria-label="AI match explanation">
    <p className="font-semibold">{aiLabel(match)}</p>
    {match?.profile_bonus ? <p>MiniLM evidence score: {match.score?.toFixed(1)}%. LinkedIn profile-completion bonus: +{match.profile_bonus} points (capped at 100). LinkedIn content was not fetched or verified.</p> : null}
    <p>Weighted semantic evidence coverage · unreviewed. Not proficiency or a hiring probability. Analysis uses a bounded sample of approved evidence.</p>
    {(match?.requirements ?? []).map(r => <div key={r.skill_id} className="mt-2"><strong>{r.skill_name}</strong> · {r.status === 'supported' ? 'Relevant evidence' : r.status === 'claimed_only' ? 'Claimed only · no supporting evidence found' : 'Missing supporting evidence'}{r.excerpt && <blockquote className="border-l-2 pl-2">{r.excerpt}</blockquote>}{r.material_id && <p>Source material #{r.material_id}</p>}</div>)}
  </section>
}

async function boundedFetch(path: string, options: RequestInit = {}) {
  const controller = new AbortController()
  const cancel = () => controller.abort()
  const timer = setTimeout(cancel, 15000)
  if (options.signal?.aborted) cancel()
  options.signal?.addEventListener('abort', cancel, { once: true })
  try {
    const response = await fetch(path, { ...options, signal: controller.signal })
    const reader = response.body?.getReader()
    const chunks: Uint8Array[] = []; let size = 0
    if (reader) {
      try {
        while (true) {
          const chunk = await reader.read()
          if (chunk.done) break
          size += chunk.value.byteLength
          if (size > 1048576) { controller.abort(); throw new Error('Analysis response exceeds the safe size limit.') }
          chunks.push(chunk.value)
        }
      } finally { reader.releaseLock() }
    }
    const body = new Uint8Array(size); let offset = 0
    for (const chunk of chunks) { body.set(chunk,offset); offset += chunk.byteLength }
    return new Response([204,205,304].includes(response.status) ? null : body, { status: response.status, headers: response.headers })
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', cancel)
  }
}
async function errorDetail(response: Response, fallback: string) {
  try {
    const data = await response.json()
    if (typeof data.detail === 'string' && data.detail.length <= 600) return data.detail
  } catch { /* Malformed errors still use the safe explanation. */ }
  return fallback
}
export async function loadAiProfile(candidateId: number, signal?: AbortSignal): Promise<Profile> {
  const response = await boundedFetch(`/api/ai-matches/profiles/${candidateId}`, { credentials:'same-origin', cache:'no-store', signal })
  if (!response.ok) {
    if (response.status === 403) return { status:'not_analyzed', matches:{}, detail:'Sign-in expired or this profile is not shared with your account. Use Logout / Switch Account to sign in again.' }
    throw new Error(await errorDetail(response, 'AI analysis is unavailable. Check the backend connection.'))
  }
  const data = await response.json()
  if (!data || typeof data.status !== 'string' || !data.matches || typeof data.matches !== 'object' || Array.isArray(data.matches)) throw new Error('Invalid analysis response. No scores were accepted.')
  for (const match of Object.values(data.matches) as AiMatch[]) {
    if (!match || typeof match.status !== 'string' || (match.score !== null && (typeof match.score !== 'number' || !Number.isFinite(match.score) || match.score < 0 || match.score > 100)) || !Array.isArray(match.requirements) || match.requirements.length > 100) throw new Error('Invalid analysis response. No scores were accepted.')
    if(match.display_score!==undefined && (typeof match.display_score!=='number' || !Number.isFinite(match.display_score) || match.display_score<0 || match.display_score>100 || ![0,2].includes(match.profile_bonus??0) || match.score===null || Math.abs(match.display_score-Math.min(100,match.score+(match.profile_bonus??0)))>0.001))throw new Error('Invalid profile bonus response.')
    for (const r of match.requirements) {
      if (!r || !Number.isInteger(r.skill_id) || r.skill_id < 1 || typeof r.skill_name !== 'string' || typeof r.status !== 'string' || (r.excerpt !== null && (typeof r.excerpt !== 'string' || r.excerpt.length > 160)) || (r.material_id !== null && (!Number.isInteger(r.material_id) || r.material_id < 1))) throw new Error('Invalid evidence attribution. No scores were accepted.')
    }
  }
  return { ...data, detail: typeof data.detail === 'string' ? data.detail : null }
}

export async function consentToAnalysis(candidateId:number,materialIds:number[],share:boolean,csrf:string,signal?:AbortSignal) {
  const consent=await boundedFetch(`/api/ai-matches/profiles/${candidateId}/consent`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Recruitifi-CSRF':csrf},body:JSON.stringify({material_ids:materialIds,confirm:true,share_with_employer_001:share}),signal})
  if(!consent.ok)throw new Error(await errorDetail(consent,'Select one to three supported materials belonging to your profile, totaling at most 10 MiB.'))
}
export async function startProfileAnalysis(candidateId:number,materialIds?:number[],share=false,signal?:AbortSignal) {
  const session=await boundedFetch('/api/evidence-session',{credentials:'same-origin',cache:'no-store',signal})
  if(!session.ok)throw new Error('Your sign-in expired or verified login is not configured. Use Logout / Switch Account to sign in again.')
  const identity=await session.json()
  if(identity.candidate_id!==candidateId || typeof identity.csrf !== 'string')throw new Error('This is not your verified profile. Sign in to the correct Talent account.')
  if(materialIds)await consentToAnalysis(candidateId,materialIds,share,identity.csrf,signal)
  const response=await boundedFetch(`/api/ai-matches/profiles/${candidateId}/analyze`,{method:'POST',credentials:'same-origin',headers:{'X-Recruitifi-CSRF':identity.csrf},signal})
  if(response.status!==202)throw new Error(await errorDetail(response,response.status===429?'An analysis is already running. Please wait.':'Analysis could not start. Check the private model service.'))
  const job=await response.json()
  if(!job || typeof job.job_id!=='string' || !/^[0-9a-f]{32}$/.test(job.job_id) || job.status!=='queued')throw new Error('Invalid analysis job response. Refresh to check its status before retrying.')
  return job
}

export function useAiMatches(candidateIds: number[], revision = '') {
  const key=candidateIds.join(',')
  const [profiles,setProfiles]=useState<Record<number,Profile>>({})
  const [message,setMessage]=useState('')
  const [busy,setBusy]=useState(false)
  const [attempt,setAttempt]=useState(0)
  const action=useRef<AbortController | null>(null)
  useEffect(()=>()=>{ action.current?.abort(); action.current=null },[key])
  useEffect(()=>{
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>
    setProfiles({})
    async function refresh() {
      const values:Record<number,Profile>={}
      for (const id of candidateIds) {
        if(controller.signal.aborted)return
        try { values[id]=await loadAiProfile(id,controller.signal) }
        catch(error) {values[id]={status:'unavailable',matches:{},detail:(error as Error).name==='AbortError'?'The analysis status request timed out. Please retry.':(error as Error).message}}
        if(controller.signal.aborted)return
        const account=readDemoAccount()
        if(account?.role==='talent' && account.candidate_id===id) {
          const p=values[id]
          setMessage(p.detail || (p.status==='completed'?(p.sources?.some(s=>s.content_status==='not_analyzed')?'Analysis completed for readable evidence. Some links were not analyzed; see source notes.':'Analysis completed. Job cards now show MiniLM evidence coverage.'):active(p.status)?'Analysis running. Results will update automatically.':p.status==='stale'?'Evidence or job requirements changed. Review your selection and analyze again.':p.status==='unavailable'?'Analysis is unavailable. Please retry.':''))
        }
      }
      if(!controller.signal.aborted){setProfiles(values);if(Object.values(values).some(p=>active(p.status)))timer=setTimeout(refresh,1500)}
    }
    void refresh()
    return ()=>{controller.abort();clearTimeout(timer)}
  },[key,attempt,revision])
  async function analyze(candidateId:number,materialIds?:number[],share=false) {
    if(action.current)return
    const controller=new AbortController();action.current=controller;setBusy(true);setProfiles(current=>({...current,[candidateId]:{status:'not_analyzed',matches:{}}}));setMessage('Starting analysis…')
    try {
      await startProfileAnalysis(candidateId,materialIds,share,controller.signal)
      if(!controller.signal.aborted){setMessage('Analysis running. Results will update automatically.');setAttempt(x=>x+1)}
    }catch(error){if(!controller.signal.aborted)setMessage((error as Error).name==='AbortError'?'The analysis request timed out. Refresh its status before retrying.':(error as Error).message)}
    finally{if(action.current===controller){action.current=null;setBusy(false)}}
  }
  function match(candidateId:number,jobId?:number):AiMatch {
    const p=profiles[candidateId]
    return p?.matches[String(jobId)] ?? {status:p?.status??'not_analyzed',score:null,requirements:[]}
  }
  const running=Object.values(profiles).some(p=>active(p.status))
  return {match,analyze,message,busy:busy||running,publicProfilesEnabled:profiles[candidateIds[0]]?.public_profile_retrieval_enabled === true,sources:profiles[candidateIds[0]]?.sources ?? []}
}


export async function saveResourceDescription(candidateId:number,materialId:number,description:string) {
  const session=await boundedFetch('/api/evidence-session',{credentials:'same-origin',cache:'no-store'})
  if(!session.ok)throw new Error('Sign in through the application account screen to save your description.')
  const identity=await session.json()
  if(identity.candidate_id!==candidateId || typeof identity.csrf!=='string')throw new Error('This is not your verified profile.')
  const response=await boundedFetch(`/api/ai-matches/profiles/${candidateId}/materials/${materialId}/description`,{method:'PATCH',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Recruitifi-CSRF':identity.csrf},body:JSON.stringify({description})})
  if(!response.ok)throw new Error(await errorDetail(response,'Could not save the resource description.'))
  const result=await response.json()
  if(result.material_id!==materialId || result.description!==description)throw new Error('Invalid description response.')
  return result.description as string
}
