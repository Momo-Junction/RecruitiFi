/** A compact, truthful status with optional guidance; never invent an AI score. */
export function AnalysisStatus({label='Not analyzed',employer=false}:{label?:string;employer?:boolean}) {
  const pending=label==='Not analyzed'
  const running=label==='Analyzing…'
  const unavailable=label==='AI score unavailable'
  return <details className={`analysis-status ${running ? 'is-running' : ''} ${pending ? 'is-pending' : ''}`}>
    <summary aria-label={`Analysis status: ${label}`}><span className="analysis-dot" aria-hidden="true" /><span>{pending ? 'Not analyzed yet' : label}</span><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><path d="m5 7 5 5 5-5" /></svg></summary>
    <div className="analysis-popover"><strong>{running ? 'Analyzing your evidence' : pending ? 'Evidence comes first' : unavailable ? 'Analysis is unavailable' : 'Evidence relevance'}</strong>
      <p>{running ? 'Your private model is working. Results update here when the analysis finishes.' : pending ? employer ? 'No completed analysis has been shared for this role yet.' : 'Choose resources in your profile, then use Our Own Private Model to see how your evidence relates to this role.' : unavailable ? 'No score was accepted. Check the analysis status in your profile and retry when the service is available.' : 'Based on the selected evidence. This is unreviewed relevance, not verified proficiency or a hiring probability.'}</p>
      {!employer && !running && <a href="#profile-heading">View your profile <span aria-hidden="true">↗</span></a>}
    </div>
  </details>
}
