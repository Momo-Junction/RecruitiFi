/** Presentation only; browser session controls live in BrowserEvidence. */
export type EvidenceAnalysisView = {
  candidateId: number
  materialId: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'unavailable'
  findings: {
    id: number; skill_name: string; finding_kind: 'semantic' | 'observation'
    source_id: number; similarity_score: number | null; observed_value?: string | null; review_status?: string
  }[]
  sources: { id: number; excerpt: string; file_path: string | null; source_reference: string | null; evidence_field: string }[]
}

function safeReference(value: string | null) {
  if (!value) return undefined
  try {
    const url = new URL(value)
    if (url.protocol === 'https:' && url.hostname === 'api.github.com' && !url.username && !url.password && !url.port && !url.search && !url.hash
      && /^\/repos\/[A-Za-z0-9-]+\/[A-Za-z0-9._-]+\/git\/blobs\/[0-9a-f]{40}$/.test(url.pathname)) return url.href
  } catch { /* Treat an unsupported reference as inert text. */ }
  return undefined
}

export function EvidenceAnalysis({ view }: { view: EvidenceAnalysisView }) {
  const labels = { pending: 'Pending', running: 'Running', completed: 'Completed', failed: 'Failed', unavailable: 'Unavailable' }
  return <section aria-label="AI evidence analysis" className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-xs">
    <p role="status" className="font-semibold">AI evidence analysis: {labels[view.status]}</p>
    {view.status === 'unavailable' && <p>Analysis access is unavailable. Sign in to your synthetic Talent account.</p>}
    {view.status === 'failed' && <p>Analysis could not complete. Findings below, if present, require review.</p>}
    <p className="mt-1 text-slate-600">Unreviewed evidence associations do not verify proficiency, authorship or hiring suitability.</p>
    {(['observation', 'semantic'] as const).map(kind => {
      const findings = view.findings.filter(f => f.finding_kind === kind)
      if (!findings.length) return null
      return <div key={kind} className="mt-2">
        <h5 className="font-semibold">{kind === 'semantic' ? 'Semantic relevance' : 'Repository observations · not verified skills'}</h5>
        <ul>{findings.map(finding => {
          const source = view.sources.find(s => s.id === finding.source_id)
          const href = safeReference(source?.source_reference ?? null)
          return <li key={finding.id} className="mt-2 break-words">
            <span className="font-semibold">{finding.skill_name}</span> <span>{`· ${finding.review_status === 'accepted' ? 'Review: accepted' : finding.review_status === 'rejected' ? 'Review: rejected' : 'Unreviewed'}`}</span>
            {kind === 'semantic' && finding.similarity_score !== null && Number.isFinite(finding.similarity_score)
              && <p>Semantic similarity (cosine): {finding.similarity_score.toFixed(3)}</p>}
            {kind === 'observation' && finding.observed_value && <p>Observed declaration or file metadata: {finding.observed_value}</p>}
            {source?.excerpt && <blockquote className="mt-1 whitespace-pre-wrap border-l-2 border-slate-300 pl-2">{source.excerpt}</blockquote>}
            {source && <p>Source: {source.file_path ?? source.evidence_field}{href && <> · <a className="text-espoo underline" href={href} target="_blank" rel="noopener noreferrer">Immutable GitHub blob</a></>}</p>}
            {!source && <p>Source reference unavailable.</p>}
          </li>
        })}</ul>
      </div>
    })}
    {view.status === 'completed' && !view.findings.length && <p>No skill associations were returned.</p>}
  </section>
}
