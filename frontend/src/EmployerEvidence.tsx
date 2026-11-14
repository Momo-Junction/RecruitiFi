import { useEffect, useState } from 'react'
import { EvidenceAnalysis, type EvidenceAnalysisView } from './EvidenceAnalysis'
import { readDemoAccount } from './demoNavigation'
import { demoCandidateId, loadEmployerDemo } from './demoEvidenceApi'

export function EmployerEvidence({ companyId, candidateId }: { companyId: number; candidateId: number }) {
  const [enabled, setEnabled] = useState(false)
  const [message, setMessage] = useState('')
  const [views, setViews] = useState<EvidenceAnalysisView[]>([])
  const [refresh, setRefresh] = useState(0)
  const account = readDemoAccount()
  const selected = companyId === 1 && candidateId === demoCandidateId && account?.demo_account_id === 'employer-001' && account.role === 'employer' && account.company_id === 1
  useEffect(() => {
    const controller = new AbortController()
    setViews([]); setMessage(''); setEnabled(false)
    if (selected) void loadEmployerDemo(companyId, candidateId, controller.signal).then(data => {
      if (controller.signal.aborted) return
      setEnabled(true)
      setMessage(data.status === 'missing' ? 'No completed fictional demo findings yet.' : ['pending', 'running'].includes(data.status) ? 'Analysis is pending or running. Refresh later.' : data.status === 'completed' ? 'Fictional demo findings · semantic relevance, not proficiency.' : 'The latest demo analysis failed or was interrupted.')
      setViews(data.analyses.map(analysis => ({ candidateId, materialId: analysis.material_id, status: 'completed', findings: analysis.findings, sources: analysis.sources })))
    }).catch(cause => { if (!controller.signal.aborted && cause.status !== 404) { setEnabled(true); setMessage(cause.message) } })
    return () => controller.abort()
  }, [companyId, candidateId, refresh, selected])
  if (!selected || !enabled) return null
  return <section className="mt-3 rounded-xl border border-slate-200 p-3" aria-label="Talent AI evidence">
    <h4 className="text-sm font-semibold">AI Evidence Analysis · read only</h4>
    <button className="text-xs text-espoo underline" onClick={() => setRefresh(value => value+1)}>View AI evidence findings</button>
    {message && <p role="status" className="mt-1 text-xs">{message}</p>}
    {views.map(view => <EvidenceAnalysis key={view.materialId} view={view} />)}
  </section>
}
