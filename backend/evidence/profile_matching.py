"""Private, consent-scoped profile/job coverage using the existing bounded worker."""
import hashlib
import json
import os
import time
from pydantic import BaseModel,ConfigDict,Field
from fastapi import Depends

from fastapi import APIRouter, Request, Response
from ..database import connect
from . import demo_boundary, job_relevance, public_profiles
from .embedding_client import EmbeddingClient, EmbeddingServiceError
from .extractor import extract_project_material, MAX_INPUT_BYTES
from .github_fetcher import fetch_github_repositories
from .github_validator import validate_github_repository_url, validate_github_repository_or_profile_url

router = APIRouter(prefix='/api/ai-matches')
MATERIAL_CATEGORIES=('cv','project','certificate','research','linkedin','github','website')


ERROR_MESSAGES = {
    'no_extractable_text':'This PDF has no readable text. Upload a text-based PDF; scanned PDFs require OCR, which is not supported.',
    'malformed_pdf':'This PDF could not be read. Export a new text-based PDF and upload it again.',
    'encrypted_pdf':'Password-protected PDFs are not supported. Upload an unencrypted copy.',
    'page_limit_exceeded':'PDF analysis supports at most 10 pages.',
    'resource_limit_exceeded':'The PDF exceeds safe extraction limits.',
    'extraction_failed':'PDF text extraction failed. Try a new text-based PDF.',
    'no_relevant_text':'No readable evidence was found. Add a project description or a repository README.',
    'unavailable':'The private model service is unavailable. Check that it is running and retry.',
    'unauthorized':'The private model service rejected its server credentials. Ask the operator to check the configuration.',
    'timeout':'Analysis timed out. Try fewer or shorter materials.',
    'worker_interrupted':'Analysis was interrupted by a server restart. Please retry.',
    'analysis_failed':'Analysis could not complete. Retry or use a smaller supported material.',
    'invalid_response':'The private model returned an invalid response. No scores were accepted.',
    'model_not_ready':'The private model is still starting. Please retry shortly.',
    'rate_limited':'GitHub rate-limited public retrieval. Wait and retry.',
    'not_found':'The GitHub repository is missing, private or inaccessible.',
    'unavailable_or_private':'The GitHub repository is missing, private or inaccessible. Use a public repository.',
    'network_error':'GitHub could not be reached. Check the network connection and retry.',
    'github_unavailable':'GitHub is temporarily unavailable. Please retry later.',
    'empty_repository':'The GitHub repository is empty.',
    'forbidden':'GitHub refused access to this repository.',
    'analysis_limit_reached':'Repository retrieval exceeded the bounded analysis budget. Try a smaller repository.',
    'no_supported_files':'The repository has no supported readable files.',
    'overloaded':'The private model is busy. Wait for the current analysis to finish, then retry.',
    'input_rejected':'The model rejected an input that exceeds its token or text limits. Try shorter evidence.',
    'unsafe_configuration':'The private model connection is not configured correctly. Ask the operator to check it.',
    'profile_access_blocked':'The site blocked automated profile access (even public profiles can require login or approved API access). No blocked page was analyzed. Try a profile PDF export instead.',
    'profile_unreadable':'The public page did not expose readable professional profile text. No profile content was invented.',
    'profile_unavailable':'The public profile could not be retrieved. Try again later or use a profile PDF export.',
    'no_public_text':'No public professional bio or repository descriptions were returned for this GitHub profile.',
    'file_too_large':'Selected evidence exceeds the 10 MiB file limit.',
}

class AnalysisInputError(ValueError):
    def __init__(self,code):
        self.code=code
        super().__init__(ERROR_MESSAGES.get(code,ERROR_MESSAGES['analysis_failed']))


def validate_materials(materials):
    repositories=set()
    for row in materials:
        if row['category']=='github':
            try:repository=validate_github_repository_or_profile_url(row['url'])
            except ValueError:raise ValueError('Use an HTTPS GitHub profile or public repository URL: https://github.com/owner or https://github.com/owner/repository.') from None
            if repository is None:continue
            name=repository['canonical_url'].casefold()
            if name in repositories:raise ValueError('Select each GitHub repository only once.')
            repositories.add(name)
        elif row['url'] is None and row['content_type'] in ('image/png','image/jpeg'):
            if not row['description'].strip():raise ValueError('Image contents cannot be read without OCR. Add a description to analyze saved metadata, or upload a text-based PDF.')
        elif row['url'] is None and (row['content_type']!='application/pdf' or not (row['filename'] or '').lower().endswith('.pdf')):
            raise ValueError('Use a text-based PDF, or an image with a saved description. Image contents are not analyzed.')



def repository_material(material):
    return material['category']=='github' and validate_github_repository_or_profile_url(material['url']) is not None


def public_profile_enabled():
    return os.environ.get('TALENTMATCH_AI_FETCH_PUBLIC_PROFILES')=='1'


def partition_materials(materials):
    usable=[];skipped=[]
    for material in materials:
        profile=material['category']=='github' and not repository_material(material)
        if public_profile_enabled() and public_profiles.supported(material):
            usable.append(material);continue
        if (material['category'] in ('linkedin','website') or profile) and not material['description'].strip():
            skipped.append({'material_id':material['id'],'category':material['category'],'content_status':'not_analyzed','detail':'No description supplied. This profile/page is not fetched; add a description or choose a public GitHub repository.'})
        else:usable.append(material)
    return usable,skipped


def extracted(material):
    evidence=extract_project_material({**material,'category':'project'})
    metadata_image=material['content_type'] in ('image/png','image/jpeg') and bool(material['description'].strip())
    if material['url'] is None and not metadata_image and evidence['extraction_status'] not in ('extracted','text_limit_reached'):
        raise AnalysisInputError(evidence['extraction_status'])
    if material['category']=='cv' and not metadata_image:
        # CV labels/descriptions are not evidence of its document contents.
        evidence={**evidence,'project_title':'','project_description':''}
    elif material['category'] in ('linkedin','website') or (material['category']=='github' and not repository_material(material)):
        evidence={**evidence,'project_title':''}
    return evidence


def retrieve(materials):
    repository_materials=[m for m in materials if repository_material(m)]
    repositories=[validate_github_repository_url(m['url']) for m in repository_materials]
    from . import github_fetcher
    budget=github_fetcher._Budget(time.monotonic()+30)
    budget.profile_repositories_left=max(0,3-len(repositories))
    results=fetch_github_repositories(repositories,_budget=budget) if repositories else []
    found={m['id']:r for m,r in zip(repository_materials,results)}
    remaining=100000-sum(f.get('decoded_bytes',0) for r in results for f in r['files'])
    if public_profile_enabled():
        for material in materials:
            if public_profiles.supported(material):
                response=public_profiles.fetch_profile(material,budget=budget)
                text=response['text'].encode('utf-8')[:max(0,remaining)].decode('utf-8',errors='ignore');remaining-=len(text.encode('utf-8'))
                found[material['id']]={**response,'text':text,'public_profile':True}
    return found


def profile_report(material,retrieval,connection,consented):
    from .semantic_matching import match_evidence_fragments
    text=retrieval['text'] if retrieval['status']=='retrieved' else ''
    if not text:return None
    fragments=[{'material_id':material['id'],'source_type':'public_github_profile' if material['category']=='github' else 'public_linkedin_profile','field':'public_profile_text','start':i,'end':min(len(text),i+200),'text':text[i:i+200]} for i in range(0,min(len(text),1200),200) if text[i:i+200].strip()]
    report=match_evidence_fragments(fragments,connection=connection,synthetic_data=not consented,consent_verified=consented,top_k=3)
    report.update(material_id=material['id'],extraction_status='public_profile_text',coverage_limited=True)
    return report


def digest_material(material):
    return hashlib.sha256(json.dumps({**dict(material),'content':hashlib.sha256(material['content']).hexdigest() if material['content'] is not None else None},sort_keys=True).encode()).hexdigest()


def enabled():
    return os.environ.get('TALENTMATCH_AI_JOB_MATCHING') == '1'


def material_ids(connection, candidate_id):
    from .jobs import allowed
    if not enabled() or not allowed(candidate_id):
        raise ValueError('Profile analysis is not approved.')
    consent=connection.execute('SELECT material_id FROM ai_material_consents WHERE candidate_id=? ORDER BY material_id',(candidate_id,)).fetchall()
    if candidate_id == 900001 and (not consent or os.environ.get('TALENTMATCH_AI_CONSENTED_MODE')!='1'):
        return [demo_boundary.material(connection)['id']]
    if consent:
        if len(consent)>3:raise ValueError('Too many approved materials.')
        return [r['material_id'] for r in consent]
    approvals=json.loads(os.environ.get('TALENTMATCH_AI_MATCH_MATERIALS','{}'))
    if not isinstance(approvals,dict):raise ValueError('Invalid material consent configuration.')
    ids=approvals.get(str(candidate_id),[])
    if not isinstance(ids,list) or not 1<=len(ids)<=3 or any(type(i) is not int or i<1 for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('Explicit material consent is required.')
    return ids


def snapshot(connection,candidate_id):
    from ..jobs import read_jobs
    ids=material_ids(connection,candidate_id); materials=[]; total=0
    for identifier in ids:
        size=connection.execute('SELECT length(content) FROM profile_materials WHERE id=? AND candidate_id=?',(identifier,candidate_id)).fetchone()
        if size is None:raise ValueError('Approved source no longer exists.')
        total+=size[0] or 0
        if total>MAX_INPUT_BYTES:raise ValueError('Approved evidence exceeds 10 MiB total.')
        row=connection.execute('SELECT * FROM profile_materials WHERE id=? AND candidate_id=?',(identifier,candidate_id)).fetchone()
        consent=connection.execute('SELECT digest FROM ai_material_consents WHERE material_id=? AND candidate_id=?',(identifier,candidate_id)).fetchone()
        legacy_fixture=candidate_id==900001 and not consent and row['id']==demo_boundary.material(connection)['id']
        if os.environ.get('TALENTMATCH_AI_CONSENTED_MODE')=='1' and not legacy_fixture and (not consent or consent['digest']!=digest_material(row)):
            raise ValueError('Changed material needs renewed consent.')
        if row['category'] not in MATERIAL_CATEGORIES:raise ValueError('Unsupported evidence category.')
        materials.append(dict(row))
    openings=read_jobs(connection)
    if len(openings)>32:raise ValueError('Demo budget supports at most 32 active jobs.')
    names={r['id']:r['name'] for r in connection.execute('SELECT id,name FROM skills ORDER BY id')}
    claims=json.loads(connection.execute('SELECT skills FROM candidates WHERE id=?',(candidate_id,)).fetchone()[0])
    canonical=[{**m,'content':hashlib.sha256(m['content']).hexdigest() if m['content'] is not None else None} for m in materials]
    payload={'evidence_version':'public-profiles-v4','fetch_public_profiles':public_profile_enabled(),'materials':canonical,'jobs':[j.model_dump() for j in openings],'catalog':names,'claims':claims,'version':job_relevance.VERSION,'revision':job_relevance.MODEL_REVISION}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    return digest,materials,openings,names,claims


def compute(connection,candidate_id,*,retrieved=None):
    fingerprint,materials,openings,names,claims=snapshot(connection,candidate_id)
    validate_materials(materials)
    retrieved=retrieve(materials) if retrieved is None else retrieved
    usable,skipped=partition_materials(materials)
    groups=[];sources=[]
    for material in usable:
        public=retrieved.get(material['id'],{})
        if public.get('public_profile'):
            if public['status']=='retrieved' and public['text'].strip():
                texts=[public['text']]
                sources.append({'material_id':material['id'],'category':material['category'],'content_status':'public_github_metadata' if material['category']=='github' else 'public_profile_text','references':public['references'],'external_content_analyzed':True})
            elif material['description'].strip():
                texts=[material['description']]
                sources.append({'material_id':material['id'],'category':material['category'],'content_status':'saved_metadata_only','external_content_analyzed':False,'detail':ERROR_MESSAGES.get(public['status'],'Public profile retrieval failed; only the saved description was analyzed.')})
            else:
                skipped.append({'material_id':material['id'],'category':material['category'],'content_status':'not_analyzed','reason':public['status'],'detail':ERROR_MESSAGES.get(public['status'],'Public profile retrieval failed. No page content was analyzed.')});continue
        elif repository_material(material):
            repository=retrieved[material['id']]
            if repository['retrieval_status'] not in ('retrieved','partial_limit_reached'):
                raise AnalysisInputError(repository['retrieval_status'])
            texts=[f['text'] for f in repository['files'] if f['path'].lower().endswith('readme.md')]
            if not texts and material['description'].strip():texts=[material['description']]
        else:
            evidence=extracted(material)
            texts=[evidence['pdf_text']] if material['category']=='cv' and evidence['pdf_text'] else [evidence['pdf_text'],evidence['project_description'],evidence['project_title']]
        if not public.get('public_profile'):
            sources.append({'material_id':material['id'],'category':material['category'],'content_status':'repository_files' if repository_material(material) else 'saved_metadata_only' if material['url'] is not None or material['content_type'] in ('image/png','image/jpeg') else 'pdf_text','external_content_analyzed':repository_material(material)})
        parts=[]
        for text in texts:
            for offset in range(0,len(text),200):
                part=text[offset:offset+200]
                if part.strip() and len(parts)<6:
                    parts.append({'candidate_id':candidate_id,'material_id':material['id'],'text':part})
        groups.append(parts)
    fragments=[]
    for index in range(6):
        for group in groups:
            if index<len(group) and len(fragments)<6:fragments.append(group[index])
    if not fragments:raise AnalysisInputError(next((s['reason'] for s in skipped if s.get('reason')),'no_relevant_text'))
    requirements={}
    for job in openings:
        weights={}
        for r in job.must_have_skills+job.nice_to_have_skills:weights[r.skill_id]=weights.get(r.skill_id,0)+r.weight
        requirements[job.id]=[{'skill_id':i,'name':names[i],'text':names[i],'weight':w} for i,w in weights.items()]
    texts=sorted({r['text'] for rs in requirements.values() for r in rs}|{f['text'] for f in fragments})
    if len(texts)>106:raise ValueError('Embedding budget exceeded.')
    client=EmbeddingClient();deadline=time.monotonic()+120;client.check_ready(deadline=deadline);vectors={}
    for start in range(0,len(texts),3):
        batch=texts[start:start+3]
        if time.monotonic()>deadline:raise EmbeddingServiceError('timeout')
        vectors.update(zip(batch,client.embed(batch,deadline=deadline)))
    class Cached:
        def check_ready(self,**_):pass
        def embed(self,texts,**_):return [vectors[t] for t in texts]
    matches={str(job.id):job_relevance.score(candidate_id,requirements[job.id],fragments,claimed_skill_ids=[s['skill_id'] for s in claims],client=Cached())
             if requirements[job.id] else {'status':'not_analyzed','score':None,'requirements':[]} for job in openings}
    return {'fingerprint':fingerprint,'matches':matches,'status':'completed','coverage_limited':True,'sources':sources+skipped}


def save(connection,candidate_id,run_id,result):
    if snapshot(connection,candidate_id)[0]!=result['fingerprint']:raise ValueError('Evidence/job changed during analysis.')
    connection.execute('INSERT INTO ai_profile_matches(candidate_id,run_id,fingerprint,result) VALUES(?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET run_id=excluded.run_id,fingerprint=excluded.fingerprint,result=excluded.result,updated_at=strftime(\'%Y-%m-%dT%H:%M:%fZ\',\'now\')',
                       (candidate_id,run_id,result['fingerprint'],json.dumps(result)))


def cached(connection,candidate_id):
    try:fingerprint=snapshot(connection,candidate_id)[0]
    except (ValueError,KeyError,TypeError):return {'status':'not_analyzed','matches':{}}
    row=connection.execute('SELECT fingerprint,result FROM ai_profile_matches WHERE candidate_id=?',(candidate_id,)).fetchone()
    if not row:return {'status':'not_analyzed','matches':{}}
    if row['fingerprint']!=fingerprint:return {'status':'stale','matches':{}}
    return json.loads(row['result'])


def identity(request):
    from .sessions import session
    return session(request)[1]


class Consent(BaseModel):
    model_config=ConfigDict(extra='forbid')
    material_ids:list[int]=Field(min_length=1,max_length=3)
    confirm:bool
    share_with_employer_001:bool=False


async def consent_body(request:Request):
    from .api import fail
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>1024:fail(413,'Consent request too large.')
        body.extend(chunk)
    try:return Consent.model_validate_json(body,strict=True)
    except ValueError:fail(422,'Select up to three materials and confirm permission to analyze.')


@router.post('/profiles/{candidate_id}/consent')
def consent(candidate_id:int,request:Request,chosen:Consent=Depends(consent_body)):
    from .sessions import session
    from .api import fail
    from .jobs import allowed
    _,account=session(request,write=True)
    if account.get('candidate_id')!=candidate_id or not allowed(candidate_id) or not chosen.confirm:fail(403,'Only the verified profile owner can consent.')
    if len(set(chosen.material_ids))!=len(chosen.material_ids) or any(i<1 for i in chosen.material_ids):fail(422,'Invalid material selection.')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE');materials=[];total=0
        if chosen.share_with_employer_001 and not c.execute('SELECT 1 FROM companies WHERE id=1').fetchone():fail(404,'Employer unavailable.')
        for i in chosen.material_ids:
            row=c.execute('SELECT category,length(content) AS size FROM profile_materials WHERE id=? AND candidate_id=?',(i,candidate_id)).fetchone()
            if not row or row['category'] not in MATERIAL_CATEGORIES:fail(403,'Material is not supported or does not belong to your profile.')
            total+=row['size'] or 0
            if total>MAX_INPUT_BYTES:fail(413,'Selected files exceed 10 MiB total.')
            materials.append(c.execute('SELECT * FROM profile_materials WHERE id=? AND candidate_id=?',(i,candidate_id)).fetchone())
        try:validate_materials(materials)
        except ValueError as error:fail(422,str(error))
        c.execute('DELETE FROM ai_material_consents WHERE candidate_id=?',(candidate_id,))
        for row in materials:c.execute('INSERT INTO ai_material_consents(material_id,candidate_id,digest,share_company_id) VALUES(?,?,?,?)',(row['id'],candidate_id,digest_material(row),1 if chosen.share_with_employer_001 else None))
    return {'consented':True,'materials':len(materials)}


@router.get('/profiles/{candidate_id}')
def read(candidate_id:int,request:Request,response:Response):
    from .sessions import employer_grants
    from .jobs import configuration
    from .api import fail,recover
    account=identity(request)
    if account.get('candidate_id')!=candidate_id:
        try:grants=employer_grants(configuration()[1])
        except ValueError:fail(403,'Sharing unavailable.')
        permitted=candidate_id in grants.get(str(account.get('company_id')),[])
        if account.get('role')=='employer':
            with connect() as c:
                rows=c.execute('SELECT share_company_id FROM ai_material_consents WHERE candidate_id=?',(candidate_id,)).fetchall()
                if rows:permitted=all(r['share_company_id']==account['company_id'] for r in rows)
        if account.get('role')!='employer' or not permitted:fail(403,'Profile not shared with your account.')
    response.headers['Cache-Control']='no-store'
    with connect() as c:
        recover(c)
        result=cached(c,candidate_id)
        active=c.execute('SELECT id,status,error_code FROM evidence_analysis_jobs WHERE candidate_id=? ORDER BY created_at DESC,id DESC LIMIT 1',(candidate_id,)).fetchone()
        if active and active['status'] in ('queued','running'):result={**result,'status':active['status']}
        elif active and active['status'] in ('failed','timed_out','interrupted','cancelled'):
            result={'status':'unavailable','matches':{},'reason':active['error_code'] or 'analysis_failed'}
        if account.get('role')=='employer':
            from ..jobs import read_jobs
            permitted={str(j.id) for j in read_jobs(c,company_id=account['company_id'])}
            result={**result,'matches':{k:v for k,v in result['matches'].items() if k in permitted}}
        return {'status':result['status'],'matches':result['matches'],'coverage_limited':True,'reason':result.get('reason'),'detail':ERROR_MESSAGES.get(result.get('reason'),ERROR_MESSAGES['analysis_failed']) if result.get('reason') else None,'sources':result.get('sources',[]),'public_profile_retrieval_enabled':public_profile_enabled()}


@router.post('/profiles/{candidate_id}/analyze',status_code=202)
def trigger(candidate_id:int,request:Request):
    from .sessions import session
    from .api import fail,trigger as start,Options
    _,account=session(request,write=True)
    if account.get('candidate_id')!=candidate_id:fail(403,'Only the profile owner can request analysis.')
    with connect() as c:
        try:
            materials=snapshot(c,candidate_id)[1]
            usable,skipped=partition_materials(materials)
            identifier=usable[0]['id'] if usable else None
        except (ValueError,TypeError):fail(403,'Evidence has not been explicitly approved for analysis.')
        try:validate_materials(materials)
        except ValueError as error:fail(422,str(error))
    if identifier is None:fail(422,'These links contain no analyzable text. Add a profile description, select a public GitHub repository, or select a text-based PDF. No linked profiles were fetched.')
    return start(candidate_id,identifier,request,Options())


class DescriptionEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    description:str=Field(max_length=1500)


async def description_body(request:Request):
    from .api import fail
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>8192:fail(413,'Description request too large.')
        body.extend(chunk)
    try:return DescriptionEdit.model_validate_json(body,strict=True)
    except ValueError:fail(422,'Enter a description of at most 1500 characters.')


@router.patch('/profiles/{candidate_id}/materials/{material_id}/description')
def edit_description(candidate_id:int,material_id:int,request:Request,edit:DescriptionEdit=Depends(description_body)):
    from .sessions import session
    from .jobs import allowed
    from .api import fail
    _,account=session(request,write=True)
    if not enabled() or not allowed(candidate_id) or account.get('candidate_id')!=candidate_id:fail(403,'Only the verified profile owner can edit this description.')
    if not 1<=material_id<=2**63-1:fail(422,'Invalid material identifier.')
    if '\x00' in edit.description:fail(422,'Description contains an unsupported control character.')
    with connect() as c:
        row=c.execute('SELECT category,url FROM profile_materials WHERE id=? AND candidate_id=?',(material_id,candidate_id)).fetchone()
        if row is None:fail(404,'Material not found for this profile.')
        if row['url'] is None:fail(422,'This editor supports saved links only.')
        c.execute('UPDATE profile_materials SET description=? WHERE id=? AND candidate_id=?',(edit.description,material_id,candidate_id))
    return {'material_id':material_id,'description':edit.description}
