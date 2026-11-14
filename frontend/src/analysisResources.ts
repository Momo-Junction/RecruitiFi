import type { SavedProfile } from './api'

export function analysisRevision(profile?: SavedProfile) {
  return JSON.stringify({ skills:profile?.candidate.skills, materials:profile?.materials })
}
export function resourceAnalysisMode(material: SavedProfile['materials'][number], publicProfiles = false) {
  if (material.category === 'github') {
    try {
      const url=new URL(material.url ?? '')
      if(url.hostname==='github.com' && url.pathname.split('/').filter(Boolean).length===1 && publicProfiles) return 'Automatically retrieves public bio and recent non-fork repository descriptions/languages; no authorship or proficiency verification'
      if(url.hostname==='github.com' && url.pathname.split('/').filter(Boolean).length===1) return material.description?.trim() ? 'Saved description only; GitHub profile is not fetched' : 'Not analyzed without a description; does not block other evidence'
    } catch { /* Server validates URLs before any retrieval. */ }
    return 'Public repository files; use an owner/repository URL'
  }
  if (material.category==='linkedin' && publicProfiles) return 'Attempts publicly accessible professional profile text; LinkedIn may block automated access'
  if (['linkedin','website'].includes(material.category) && !material.description?.trim()) return 'Not analyzed without a description; does not block other evidence'
  if (material.content_type === 'application/pdf') return 'PDF text; maximum 10 pages'
  if (material.content_type === 'image/png' || material.content_type === 'image/jpeg') return 'Saved description only; image contents have no OCR'
  return 'Saved title and description only; external page is not fetched'
}

export function sourceAnalysisNote(source:{content_status:string;detail?:string}) {
  if(source.content_status==='public_github_metadata')return 'Retrieved public GitHub bio and recent repository metadata. Not verified authorship or proficiency.'
  if(source.content_status==='public_profile_text')return 'Retrieved publicly accessible professional profile text (bounded sample).'
  if(source.content_status==='not_analyzed')return 'Not analyzed. '+(source.detail ?? 'No readable public content was available.')
  if(source.content_status==='saved_metadata_only')return 'Saved description only; external page/image contents not analyzed.'+(source.detail?' '+source.detail:'')
  if(source.content_status==='repository_files')return 'Selected public GitHub files.'
  return 'Extracted PDF text.'
}
