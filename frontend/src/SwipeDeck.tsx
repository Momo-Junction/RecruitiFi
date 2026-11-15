import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { AnalysisStatus } from './AnalysisStatus'
import { LoadingState } from './LoadingState'

export interface DiscoveryCard {
  id: number
  name: string
  subtitle: string
  monogram: string
  score: number | null
  scoreLabel?: string
  eligible: boolean
  likedYou: boolean
  interestLabel?: string
  facts: string[]
  skills: { name: string; matched: boolean; priority?: 'Required' | 'Preferred' }[]
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
  onDecide: (id: number, decision: 'like' | 'pass') => Promise<boolean>
  saved: { id: number; name: string; mutual: boolean; interested?: boolean; reviewId?: number }[]
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
  const pointer = useRef<{ id: number; x: number; y:number; horizontal:boolean } | null>(null)
  const locked = useRef(false)
  const stage=useRef<HTMLDivElement>(null)
  const [stageVisible,setStageVisible]=useState(false)
  const employer = side === 'employer'
  const positive = employer ? 'Short Listed' : 'Interested'
  const negative = 'Rejected'
  const savedLabel = employer ? 'Short Listed' : 'Interested'
  const card = cards[0]
  useEffect(() => {
    if (!notice) return
    const timeout = setTimeout(() => setNotice(''), 5000)
    return () => clearTimeout(timeout)
  }, [notice])
  useEffect(()=>{
    const element=stage.current
    if(!element || typeof IntersectionObserver==='undefined')return
    const observer=new IntersectionObserver(([entry])=>setStageVisible(entry.isIntersecting && entry.intersectionRatio>=.2),{threshold:.2})
    observer.observe(element)
    return ()=>observer.disconnect()
  },[card?.id,loading,tab,error])
  async function choose(decision: 'like' | 'pass') {
    if (!card || loading || locked.current) return
    locked.current = true
    setSaving(true); setFailure(''); setLeaving(decision)
    try {
      // A media-query failure must never leave mobile controls permanently locked.
      const reduced=window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
      await new Promise<void>(resolve=>window.setTimeout(resolve,reduced ? 0:180))
      const mutual = await onDecide(card.id, decision)
      setLast(card.id)
      setNotice(decision === 'like' ? mutual ? `It's a Match! You and ${card.name} are interested in each other.` : employer ? `${card.name} added to your shortlist.` : `Interested in ${card.name}. Waiting for a response.` : `Rejected ${card.name}.`)
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
    {error ? <div className="discovery-empty" role="alert"><p>{error}</p><button onClick={onRetry}>Try again</button></div> : loading ? <div className="discovery-empty" role="status"><LoadingState compact label="Finding relevant opportunities" /></div> : tab === 'likes' ? <div className="discovery-saved">
      <h3>Your next conversations</h3><p>A match happens when you both swipe right.</p>
      {!saved.length && <div className="discovery-empty"><h3>Make the first move.</h3><p>Your saved profiles will appear here.</p><button onClick={() => setTab('discover')}>Explore profiles</button></div>}
      {saved.map((item) => <div className="discovery-saved-row" key={item.id}><span className="saved-heart">♥</span><div><strong>{item.name} {item.interested && <span className="rounded-full bg-emerald-100 px-2 py-1 text-xs text-emerald-900">Interested</span>}</strong><small>{item.mutual ? '♥ Mutual match · say hello at the booth' : employer ? 'Short Listed · waiting for interest' : 'Interested · waiting for a response'}</small></div>{onReview && <button onClick={() => onReview(item.reviewId ?? item.id)}>View fit ↗</button>}</div>)}
    </div> : <>
      <div ref={stage} className="swipe-stage">
        {card ? <>
          <div className="swipe-ghost ghost-back" /><div className="swipe-ghost ghost-front" />
          <article tabIndex={0} aria-label={`${card.name}, ${card.scoreLabel ?? 'Not analyzed'}. Use left arrow for Rejected or right arrow for ${positive}.`}
            className={`swipe-card ${leaving ? `leaving-${leaving}` : ''} ${drag ? 'dragging' : ''}`}
            style={{ '--card-hue': `${(card.id * 47 + 200) % 360}`, transform: leaving ? undefined : `translateX(${drag}px) rotate(${drag / 22}deg)` } as CSSProperties}
            onKeyDown={(event) => { if (event.target !== event.currentTarget) return; if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); void choose(event.key === 'ArrowRight' ? 'like' : 'pass') } }}
            onPointerDown={(event) => {
              if(locked.current || !event.isPrimary || event.button!==0 || (event.target as Element).closest('button,a,summary,details,input,select,textarea'))return
              pointer.current={id:event.pointerId,x:event.clientX,y:event.clientY,horizontal:false}
            }}
            onPointerMove={(event) => {
              const start=pointer.current
              if(!start || start.id!==event.pointerId)return
              const dx=event.clientX-start.x,dy=event.clientY-start.y
              if(!start.horizontal && Math.abs(dy)>10 && Math.abs(dy)>Math.abs(dx)){pointer.current=null;setDrag(0);return}
              if(!start.horizontal && Math.abs(dx)>10 && Math.abs(dx)>Math.abs(dy)){
                start.horizontal=true
                event.currentTarget.setPointerCapture(event.pointerId)
              }
              if(start.horizontal)setDrag(dx)
            }}
            onPointerUp={(event) => {
              const start=pointer.current
              if(!start || start.id!==event.pointerId)return
              pointer.current=null
              const distance=event.clientX-start.x
              if(start.horizontal && Math.abs(distance)>=Math.min(85,event.currentTarget.offsetWidth*.23))void choose(distance>0?'like':'pass')
              else setDrag(0)
            }}
            onLostPointerCapture={() => {pointer.current=null;if(!locked.current)setDrag(0)}}
            onPointerCancel={() => {pointer.current=null;setDrag(0)}}>
            <AnalysisStatus label={card.scoreLabel} employer={employer} />
            <div className="swipe-art"><div className="swipe-orbit orbit-one" /><div className="swipe-orbit orbit-two" /><span className="swipe-brand">TalentMatch</span><div className="swipe-monogram">{card.monogram}<span>✦</span></div><div className="swipe-art-caption">GREAT WORK STARTS<br />WITH A CONNECTION.</div>
              {(Math.abs(drag) > 35 || leaving) && <span className={`swipe-stamp ${leaving === 'like' || (!leaving && drag > 0) ? 'stamp-like' : 'stamp-pass'}`}>{leaving === 'like' || (!leaving && drag > 0) ? 'Short Listed' : 'Rejected'}</span>}
            </div>
            <div className="swipe-body"><div className="swipe-kicker">{card.likedYou ? <span className="rounded-full bg-emerald-100 px-2 py-1 text-emerald-900">{card.interestLabel ?? 'Interested'}</span> : card.eligible ? '✓ Meets the role requirements' : 'Explore your potential'}</div><h3>{card.name}</h3><p className="swipe-subtitle">{card.subtitle}</p><div className="swipe-facts">{card.facts.map((fact) => <span key={fact}>{fact}</span>)}</div>
              <div className="swipe-skills-title">EVIDENCE RELEVANCE <span>unreviewed</span></div><div className="swipe-skills">{card.skills.map((skill) => <span key={skill.name} className={skill.matched ? 'skill-common' : ''}>{skill.matched && '✓ '}{skill.priority && `${skill.priority} · `}{skill.name}</span>)}</div>
              {card.warnings.length > 0 && <p className="swipe-warning">{card.warnings.join(' · ')}</p>}
              {onReview && <button className="swipe-detail" onClick={() => onReview(card.id)}>Why this match? <span>↗</span></button>}
            </div>
          </article>
        </> : <div className="discovery-empty"><span className="empty-spark">✦</span><h3>You're all caught up.</h3><button onClick={() => setTab('likes')}>{savedLabel}</button></div>}
      </div>
      <div className="swipe-actions-shell"><div className={`swipe-actions ${stageVisible && card ? 'is-on-screen':''}`}><button type="button" className="swipe-undo" disabled={last === undefined || saving || loading} aria-label="Undo last decision" onClick={async () => {
        if (last === undefined || locked.current) return
        locked.current = true; setSaving(true); setFailure('')
        try { await onUndo(last); setLast(undefined); setNotice('Decision undone.') }
        catch (cause) { setFailure((cause as Error).message) }
        finally { locked.current = false; setSaving(false) }
      }}><Icon kind="undo" /></button><div><button type="button" className="swipe-pass" disabled={!card || saving || loading} aria-label={negative} onClick={() => void choose('pass')}><Icon kind="close" /></button><span>{negative}</span></div><div><button type="button" className="swipe-like" disabled={!card || saving || loading} aria-label={positive} onClick={() => void choose('like')}><Icon kind="heart" /></button><span>{positive}</span></div></div></div>
    </>}
    {failure && <p role="alert" className="swipe-error">{failure}</p>}
    <p className={`swipe-notice ${notice.startsWith("It's a Match!") ? 'is-match' : ''}`} role="status">{saving ? 'Saving your choice…' : notice}</p>
    <p className="discovery-footnote">Demo accounts share these choices. Interest does not book a meeting.</p>
  </section>
}
