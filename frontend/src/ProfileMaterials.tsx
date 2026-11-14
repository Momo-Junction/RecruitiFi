import { useState } from 'react'
import { EvidenceAnalysis, type EvidenceAnalysisView } from './EvidenceAnalysis'
import { saveResourceDescription } from './useAiMatches'
import { BrowserEvidence } from './BrowserEvidence'
import { documentUrl, profileRequest, type MaterialCategory, type SavedProfile, type Skill } from './api'

const sections: { category: MaterialCategory; label: string; help: string; upload: boolean }[] = [
  { category: 'cv', label: 'CV', help: 'Your experience, education and contact details.', upload: true },
  { category: 'project', label: 'Projects & portfolio', help: 'Show something you built and explain your contribution.', upload: true },
  { category: 'certificate', label: 'Courses & certificates', help: 'Add the course name, issuer and certificate.', upload: true },
  { category: 'research', label: 'Research & publications', help: 'Share a paper, thesis or published article.', upload: true },
  { category: 'linkedin', label: 'LinkedIn', help: 'Your professional profile.', upload: false },
  { category: 'github', label: 'GitHub', help: 'Your repositories and contributions.', upload: false },
  { category: 'website', label: 'Personal website', help: 'Your own place on the web.', upload: false },
]
const field = 'w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm'
const button = 'min-h-11 rounded-lg bg-espoo px-3 py-2 text-sm font-semibold text-white transition-colors enabled:cursor-pointer enabled:hover:bg-blue-900 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-espoo disabled:opacity-50 motion-reduce:transition-none'

export function ProfileMaterials({ profile, skills, onSaved, analysisViews = [] }: {
  profile: SavedProfile; skills: Skill[]; onSaved: (profile: SavedProfile) => void
  analysisViews?: EvidenceAnalysisView[]
}) {
  const [category, setCategory] = useState<MaterialCategory | null>(null)
  const [mode, setMode] = useState<'upload' | 'link'>('upload')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const selected = sections.find((section) => section.category === category)
  const candidateId = profile.candidate.id

  return (
    <section className="mt-6" aria-label="Documents and professional profiles">
      <h3 className="text-lg font-bold">Your work & experience</h3>
      <p className="mt-1 text-xs leading-relaxed text-slate-600">Saved to your profile. Submitted certificates are available for review.</p>
      <div className="mt-3 space-y-2">
        {sections.map((section) => {
          const materials = profile.materials.filter((item) => item.category === section.category)
          return (
            <div key={section.category} className="rounded-xl border border-slate-200 bg-white p-3">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-sm font-bold">{section.label}</h4>
                <button type="button" disabled={busy} aria-label={section.upload ? 'Add ' + section.label : 'Connect ' + section.label} aria-expanded={category === section.category} className={button + ' w-24 shrink-0'} onClick={() => {
                  setCategory(section.category); setMode(section.upload ? 'upload' : 'link'); setError(''); setNotice('')
                }}>{section.upload ? 'Add' : 'Connect'}</button>
              </div>
              <p className="mt-1 text-xs text-slate-600">{section.help}</p>
              <ul className="mt-2 space-y-2">
                {materials.map((item) => (
                  <li key={item.id} className="rounded-lg bg-mist p-2 text-sm">
                    <a href={item.url ?? documentUrl(candidateId, item.id)} target="_blank" rel="noopener noreferrer" className="break-words font-semibold text-espoo underline">{item.title}</a>
                    {item.description && <p className="mt-1 whitespace-pre-wrap break-words text-xs text-slate-600">{item.description}</p>}
                    {item.url && <details className="mt-2 text-xs"><summary className="cursor-pointer text-espoo underline">Add / edit analysis description</summary>
                      <form className="mt-2 space-y-2" onSubmit={async event => {
                        event.preventDefault()
                        const description=String(new FormData(event.currentTarget).get('description') ?? '')
                        setBusy(true);setError('')
                        try {
                          const saved=await saveResourceDescription(candidateId,item.id,description)
                          onSaved({...profile,materials:profile.materials.map(m=>m.id===item.id?{...m,description:saved}:m)})
                          setNotice('Description saved. Select this resource and confirm consent to analyze again.')
                        } catch(cause){setError((cause as Error).message)}
                        finally{setBusy(false)}
                      }}>
                        <p>Optional: add your own experience or project summary. Public-profile retrieval may be blocked by the source website.</p>
                        <textarea aria-label={`Analysis description for ${item.title}`} name="description" defaultValue={item.description} maxLength={1500} className={field} />
                        <button type="submit" disabled={busy} className={button}>Save description</button>
                      </form>
                    </details>}

                    {item.skill_id && <p className="mt-1 text-xs text-slate-600">{skills.find(({ id }) => id === item.skill_id)?.name}</p>}
                    {(item.category === 'project' || item.category === 'github') && <BrowserEvidence key={`${candidateId}-${item.id}`} candidateId={candidateId} materialId={item.id} />}
                    {(item.category === 'project' || item.category === 'github') && analysisViews
                      .filter(view => view.candidateId === candidateId && view.materialId === item.id)
                      .map(view => <EvidenceAnalysis key={`${view.candidateId}-${view.materialId}`} view={view} />)}
                    <button type="button" disabled={busy} className="mt-1 text-xs text-espoo underline enabled:cursor-pointer" aria-label={`Remove ${item.title}`} onClick={async () => {
                      setBusy(true); setError('')
                      try {
                        onSaved(await profileRequest(candidateId, `materials/${item.id}`, { method: 'DELETE' }))
                        setNotice('Removed from your profile.')
                      } catch (cause) { setError((cause as Error).message) }
                      finally { setBusy(false) }
                    }}>Remove</button>
                  </li>
                ))}
              </ul>
              {selected?.category === section.category && (
                <form key={category} aria-label={`Add ${selected.label}`} className="mt-3 space-y-3 rounded-xl border-2 border-blue-200 bg-mist/40 p-3" onSubmit={async (event) => {
                  event.preventDefault()
                  if (busy) return
                  const data = new FormData(event.currentTarget)
                  const metadata = {
                    category: selected.category,
                    title: String(data.get('title') ?? selected.label).trim(),
                    description: String(data.get('description') ?? ''),
                    skill_id: data.get('skill') ? Number(data.get('skill')) : null,
                  }
                  setBusy(true); setError(''); setNotice('')
                  try {
                    let saved: SavedProfile
                    if (mode === 'upload') {
                      const file = data.get('file') as File
                      if (!file?.size || file.size > 10 * 1024 * 1024) throw new Error('Choose a PDF, PNG or JPEG file up to 10 MB.')
                      const params = new URLSearchParams({
                        category: metadata.category, title: metadata.title, description: metadata.description, filename: file.name,
                      })
                      if (metadata.skill_id) params.set('skill_id', String(metadata.skill_id))
                      saved = await profileRequest(candidateId, `documents?${params}`, {
                        method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
                      })
                    } else {
                      saved = await profileRequest(candidateId, 'links', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ...metadata, url: data.get('url') }),
                      })
                    }
                    onSaved(saved); setCategory(null); setNotice('Saved to your profile.')
                  } catch (cause) { setError((cause as Error).message) }
                  finally { setBusy(false) }
                }}>
                  <fieldset disabled={busy} className="min-w-0 space-y-3">
                    {selected.upload && selected.category !== 'cv' && (
                      <div className="flex flex-wrap gap-2">{(['upload', 'link'] as const).map((option) => <button key={option} type="button" aria-pressed={mode === option}
                        onClick={() => setMode(option)} className={`rounded-lg px-3 py-1.5 text-sm ${mode === option ? 'bg-espoo text-white' : 'bg-white text-espoo'}`}>{option === 'upload' ? 'Upload a file' : 'Add a link'}</button>)}</div>
                    )}
                    {['project', 'research', 'certificate'].includes(selected.category) && (
                      <label className="grid gap-1 text-xs font-semibold">{selected.category === 'certificate' ? 'Course or certificate name' : selected.category === 'research' ? 'Publication title' : 'Project name'}
                        <input required name="title" maxLength={120} className={field} />
                      </label>
                    )}
                    {mode === 'upload' ? <label className="grid gap-2 rounded-lg border border-dashed border-blue-300 bg-white p-3 text-xs font-semibold">
                      Choose a document
                      <input required type="file" name="file" accept=".pdf,.png,.jpg,.jpeg" className="w-full min-w-0 text-xs file:mr-2 file:rounded file:border-0 file:bg-mist file:p-2 file:text-espoo" />
                      <span className="font-normal text-slate-600">PDF, PNG or JPEG · up to 10 MB</span>
                    </label> : <label className="grid gap-1 text-xs font-semibold">Web address<input required name="url" type="url" maxLength={2048} placeholder="https://" className={field} /></label>}
                    {['project', 'research', 'certificate'].includes(selected.category) && <>
                      <label className="grid gap-1 text-xs font-semibold">{selected.category === 'certificate' ? 'Issuer, date and what you learned' : 'What did you contribute?'}
                        <textarea name="description" rows={3} maxLength={1500} className={field} />
                      </label>
                      <label className="grid gap-1 text-xs font-semibold">Skill demonstrated
                        <select name="skill" className={field}><option value="">Choose a skill (optional)</option>{skills.map(({ id, name }) => <option key={id} value={id}>{name}</option>)}</select>
                      </label>
                    </>}
                    <div className="flex flex-wrap gap-3"><button type="submit" className={button}>{busy ? 'Saving…' : mode === 'upload' ? 'Upload and save' : 'Save profile'}</button>
                      <button type="button" className="min-h-11 rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-espoo transition-colors enabled:cursor-pointer enabled:hover:border-blue-400 enabled:hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-espoo active:bg-blue-100 motion-reduce:transition-none" onClick={() => setCategory(null)}>Cancel</button></div>
                  </fieldset>
                </form>
              )}
            </div>
          )
        })}
      </div>
      {error && <p role="alert" className="mt-2 text-sm text-red-800">{error}</p>}
      {notice && <p role="status" className="mt-2 text-sm text-emerald-800">{notice}</p>}
    </section>
  )
}
