import { useRef, useState, type CSSProperties } from 'react'

export interface DiscoveryCard {
  id: number
  name: string
  subtitle: string
  monogram: string
  score: number
  eligible: boolean
  likedYou: boolean
  facts: string[]
  skills: { name: string; matched: boolean }[]
  warnings: string[]
}

function Icon({ kind }: { kind: 'heart' | 'close' | 'undo' }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {kind === 'heart' ? <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" /> : kind === 'close' ? <path d="m6 6 12 12M18 6 6 18" /> : <path d="M3 10h11a7 7 0 1 1-6.5 9M3 10l5-5M3 10l5 5" />}
  </svg>
}

export function SwipeDeck({ cards, loading, error, onRetry, onDecide, saved, onReview, onUndo, side }: {
  side: 'employer' | 'talent'
  cards: DiscoveryCard[]; loading: boolean; error?: string; onRetry: () => void
  onDecide: (id: number, decision: 'like' | 'pass') => Promise<void>
  saved: { id: number; name: string; mutual: boolean }[]
  onUndo: (id: number) => Promise<void>
  onReview?: (id: number) => void
}) {
  const [tab, setTab] = useState<'discover' | 'likes'>('discover')
  const [drag, setDrag] = useState(0)
  const [leaving, setLeaving] = useState<'like' | 'pass' | null>(null)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState('')
  const [notice, setNotice] = useState('')
  const [last, setLast] = useState<number>()
  const pointer = useRef<{ id: number; x: number } | null>(null)
  const locked = useRef(false)
  const employer = side === 'employer'
  const positive = employer ? 'Shortlist' : 'Interested'
  const negative = employer ? 'Reject' : 'Skip'
  const savedLabel = employer ? 'Shortlisted' : 'Your interest'
  const card = cards[0]
  async function choose(decision: 'like' | 'pass') {
    if (!card || loading || locked.current) return
    locked.current = true
    setSaving(true); setFailure(''); setLeaving(decision)
    // Animate first, then commit. A failed save keeps the same card available.
    await new Promise<void>((resolve) => { window.setTimeout(resolve, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 310) })
    try {
      await onDecide(card.id, decision)
      setLast(card.id)
      if (decision === 'like' && card.likedYou) setNotice('Mutual match with ' + card.name + '!')
      else if (decision === 'like') setNotice(employer ? 'Shortlisted ' + card.name + '.' : 'Interest sent to ' + card.name + '.')
      else setNotice(employer ? 'Rejected ' + card.name + '.' : 'Skipped ' + card.name + '.')
    } catch (cause) { setFailure((cause as Error).message) }
    finally { setLeaving(null); setDrag(0); setSaving(false); locked.current = false }
  }
  return <section className="discovery" aria-label="Swipe discovery">
    <div className="discovery-top"><div><h2>{employer ? 'Discover candidates' : 'Discover employers'}</h2></div><span className="discovery-spark" aria-hidden="true">✦</span></div>
    <div className="discovery-tabs" aria-label="Discovery views">
      <button type="button" aria-pressed={tab === 'discover'} onClick={() => setTab('discover')}>Discover <span>{cards.length}</span></button>
      <button type="button" aria-pressed={tab === 'likes'} onClick={() => setTab('likes')}>{savedLabel} <span>{saved.length}</span></button>
    </div>
    <p className="discovery-intro">Review profiles ranked by skill fit.</p>
    {error ? <div className="discovery-empty" role="alert"><p>{error}</p><button onClick={onRetry}>Try again</button></div> : loading ? <div className="discovery-empty" role="status"><span className="discovery-loader" /><h3>Finding your people…</h3><p>Comparing skills, evidence and role requirements.</p></div> : tab === 'likes' ? <div className="discovery-saved">
      <h3>{savedLabel}</h3><p>A match appears when a candidate shows interest and the employer shortlists them.</p>
      {!saved.length && <div className="discovery-empty"><h3>{employer ? 'No shortlisted candidates yet' : 'No interest sent yet'}</h3><button onClick={() => setTab('discover')}>Explore profiles</button></div>}
      {saved.map((item) => <div className="discovery-saved-row" key={item.id}><span className="saved-heart">♥</span><div><strong>{item.name}</strong><small>{item.mutual ? 'Mutual match' : employer ? 'Shortlisted' : 'Interest sent'}</small></div>{onReview && <button onClick={() => onReview(item.id)}>View fit ↗</button>}</div>)}
    </div> : <>
      <div className="swipe-stage">
        {card ? <>
          <div className="swipe-ghost ghost-back" /><div className="swipe-ghost ghost-front" />
          <article key={card.id} tabIndex={0} aria-label={`${card.name}, ${card.score}% fit. Use left arrow to ${negative.toLowerCase()} or right arrow to ${positive.toLowerCase()}.`}
            className={`swipe-card ${leaving ? `leaving-${leaving}` : ''} ${drag ? 'dragging' : ''}`}
            style={{ '--card-hue': `${(card.id * 47 + 200) % 360}`, transform: leaving ? undefined : `translateX(${drag}px) rotate(${drag / 22}deg)` } as CSSProperties}
            onKeyDown={(event) => { if (event.target !== event.currentTarget) return; if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); void choose(event.key === 'ArrowRight' ? 'like' : 'pass') } }}
            onPointerDown={(event) => { if (locked.current || !event.isPrimary || (event.target as HTMLElement).closest('button') || event.button !== 0) return; pointer.current = { id: event.pointerId, x: event.clientX }; event.currentTarget.setPointerCapture(event.pointerId) }}
            onPointerMove={(event) => { if (pointer.current?.id === event.pointerId) setDrag(event.clientX - pointer.current.x) }}
            onPointerUp={(event) => { if (pointer.current?.id !== event.pointerId) return; const distance = event.clientX - pointer.current.x; pointer.current = null; if (Math.abs(distance) >= Math.min(85, event.currentTarget.offsetWidth * 0.23)) void choose(distance > 0 ? 'like' : 'pass'); else setDrag(0) }}
            onLostPointerCapture={() => { pointer.current = null; if (!locked.current) setDrag(0) }}
            onPointerCancel={() => { pointer.current = null; setDrag(0) }}>
            <div className="swipe-art"><div className="swipe-orbit orbit-one" /><div className="swipe-orbit orbit-two" /><span className="swipe-brand">TALENTMATCH</span><span className="swipe-fit"><i />{Number(card.score.toFixed(1))}% fit</span><div className="swipe-monogram">{card.monogram}<span>✦</span></div>
              {(Math.abs(drag) > 35 || leaving) && <span className={`swipe-stamp ${leaving === 'like' || (!leaving && drag > 0) ? 'stamp-like' : 'stamp-pass'}`}>{leaving === 'like' || (!leaving && drag > 0) ? positive : negative}</span>}
            </div>
            <div className="swipe-body"><div className="swipe-kicker">{card.likedYou ? (employer ? 'Candidate is interested' : 'Employer shortlisted you') : card.eligible ? '✓ Meets the role requirements' : 'Explore your potential'}</div><h3>{card.name}</h3><p className="swipe-subtitle">{card.subtitle}</p><div className="swipe-facts">{card.facts.map((fact) => <span key={fact}>{fact}</span>)}</div>
              <div className="swipe-skills-title">THE SKILL CONNECTION <span>✓ in common</span></div><div className="swipe-skills">{card.skills.map((skill) => <span key={skill.name} className={skill.matched ? 'skill-common' : ''}>{skill.matched && '✓ '}{skill.name}</span>)}</div>
              {card.warnings.length > 0 && <p className="swipe-warning">{card.warnings.join(' · ')}</p>}
              {onReview && <button className="swipe-detail" onClick={() => onReview(card.id)}>Why this match? <span>↗</span></button>}
            </div>
          </article>
        </> : <div className="discovery-empty"><span className="empty-spark">✦</span><h3>You're all caught up.</h3><button onClick={() => setTab('likes')}>{savedLabel}</button></div>}
      </div>
      <div className="swipe-actions"><button type="button" className="swipe-undo" disabled={last === undefined || saving || loading} aria-label="Undo last decision" onClick={async () => {
        if (last === undefined || locked.current) return
        locked.current = true; setSaving(true); setFailure('')
        try { await onUndo(last); setLast(undefined); setNotice('Decision undone.') }
        catch (cause) { setFailure((cause as Error).message) }
        finally { locked.current = false; setSaving(false) }
      }}><Icon kind="undo" /></button><div><button type="button" className="swipe-pass" disabled={!card || saving || loading} aria-label={negative} onClick={() => void choose('pass')}><Icon kind="close" /></button><span>{negative}</span></div><div><button type="button" className="swipe-like" disabled={!card || saving || loading} aria-label={employer ? positive : "Show interest"} onClick={() => void choose('like')}><Icon kind="heart" /></button><span>{positive}</span></div></div>
    </>}
    {failure && <p role="alert" className="swipe-error">{failure}</p>}
    <p className={`swipe-notice ${notice.startsWith('Mutual match') ? 'is-match' : ''}`} role="status">{saving ? 'Saving your choice…' : notice}</p>

  </section>
}
