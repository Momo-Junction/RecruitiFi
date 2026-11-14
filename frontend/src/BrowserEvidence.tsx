import { useEffect, useRef, useState } from 'react'
import { EvidenceAnalysis, type EvidenceAnalysisView } from './EvidenceAnalysis'
import { readDemoAccount } from './demoNavigation'
import { demoCandidateId, loadDemoMaterial, loadDemoResult, startDemoAnalysis } from './demoEvidenceApi'

export function BrowserEvidence({ candidateId, materialId }: { candidateId: number; materialId: number }) {
  const [available, setAvailable] = useState(false)
  const [error, setError] = useState('')
  const [job, setJob] = useState('')
  const [starting, setStarting] = useState(false)
  const [view, setView] = useState<EvidenceAnalysisView>()
  const action = useRef<AbortController | null>(null)
  const account = readDemoAccount()
  const selected = candidateId === demoCandidateId && account?.demo_account_id === 'talent-ai-001' && account.role === 'talent' && account.candidate_id === candidateId
  useEffect(() => {
    const controller = new AbortController()
    setAvailable(false); setJob(''); setView(undefined); setError(''); setStarting(false)
    if (selected) void loadDemoMaterial(candidateId, materialId, controller.signal).then(data => {
      if (controller.signal.aborted) return
      setAvailable(true)
      if (data.job) setJob(data.job.id)
    }).catch(cause => { if (!controller.signal.aborted && cause.status !== 404) setError(cause.message) })
    return () => { controller.abort(); action.current?.abort() }
  }, [candidateId, materialId, selected])
  useEffect(() => {
    if (!job || !selected) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      try {
        const data = await loadDemoResult(candidateId, materialId, job, controller.signal)
        if (controller.signal.aborted) return
        const active = ['queued', 'running'].includes(data.job.status)
        setView({ candidateId, materialId, status: active ? data.job.status === 'queued' ? 'pending' : 'running' : data.job.status === 'completed' ? 'completed' : 'failed', findings: data.analysis?.findings ?? [], sources: data.analysis?.sources ?? [] })
        if (!active && data.job.error_code) setError(['unavailable', 'model_not_ready', 'unauthorized'].includes(data.job.error_code) ? 'The private inference service is unavailable.' : 'Analysis failed. You can retry later.')
        if (active) timer = setTimeout(poll, 1500)
        else setJob('')
      } catch (cause) {
        if (!controller.signal.aborted) { setError((cause as Error).message); setView({ candidateId, materialId, status: 'unavailable', findings: [], sources: [] }); setJob('') }
      }
    }
    void poll()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [job, candidateId, materialId, selected])
  if (!selected || (!available && !error)) return null
  return <div className="mt-2 text-xs">
    {available && <button disabled={!!job || starting} className="text-espoo underline disabled:opacity-50" onClick={async () => {
      action.current?.abort(); const controller = new AbortController(); action.current = controller
      setError(''); setStarting(true)
      try {
        const identifier = await startDemoAnalysis(candidateId, materialId, controller.signal)
        if (controller.signal.aborted) return
        setView({ candidateId, materialId, status: 'pending', findings: [], sources: [] }); setJob(identifier)
      } catch (cause) { if (!controller.signal.aborted) setError((cause as Error).message) }
      finally { if (!controller.signal.aborted) setStarting(false) }
    }}>Analyze Evidence</button>}
    {error && <p role="alert">{error}</p>}
    {view && <EvidenceAnalysis view={view} />}
  </div>
}
