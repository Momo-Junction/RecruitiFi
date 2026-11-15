/** Loading feedback follows real requests; no artificial progress or startup delay. */
export function LoadingState({ compact=false, label='Loading TalentMatch' }: { compact?:boolean; label?:string }) {
  return <div className={`app-loading ${compact ? 'is-compact' : ''}`} role="status" aria-live="polite" aria-busy="true">
    <div className="loading-emblem" aria-hidden="true"><span /><span /><strong>T</strong></div>
    <div><p className="loading-brand">TalentMatch</p><p className="loading-caption">{label}</p></div>
    <span className="loading-track" aria-hidden="true" />
  </div>
}
