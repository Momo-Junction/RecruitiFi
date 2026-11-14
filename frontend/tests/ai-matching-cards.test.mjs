import assert from 'node:assert/strict'
import { test,after,mock } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'
const server=await createServer({server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
after(()=>server.close())
const {aiLabel,AiExplanation}=await server.ssrLoadModule('/src/useAiMatches.tsx')
const {SwipeDeck}=await server.ssrLoadModule('/src/SwipeDeck.tsx')
test('missing/offline evidence never falls back to a legacy percentage',()=>{
 assert.equal(aiLabel(), 'Not analyzed')
 assert.equal(aiLabel({status:'unavailable',score:null}), 'AI score unavailable')
 const html=renderToString(React.createElement(SwipeDeck,{cards:[{id:1,name:'Fictional',score:24.5,monogram:'F',subtitle:'Test',facts:[],skills:[],warnings:[]}],loading:false,saved:[],onRetry(){},onDecide(){},onUndo(){}}))
 assert.match(html,/Not analyzed/);assert.doesNotMatch(html,/24\.5%/)
})
test('computed model coverage and attributed explanations are distinct from proficiency',()=>{
 const match={status:'completed',score:77.8,requirements:[{skill_id:1,skill_name:'Python',status:'supported',excerpt:'Fabricated REST API project',material_id:7,coverage:1},{skill_id:3,skill_name:'React',status:'claimed_only',excerpt:null,material_id:null,coverage:0}]}
 const html=renderToString(React.createElement(AiExplanation,{match}))
 assert.match(html,/77\.8% AI evidence fit/);assert.match(html.replaceAll('<!-- -->',''),/Source material #7/)
 assert.match(html,/Claimed only/);assert.match(html,/Not proficiency/)
})

test('material consent sends only selected IDs, explicit sharing and session CSRF',async()=>{
 const {consentToAnalysis}=await server.ssrLoadModule('/src/useAiMatches.tsx')
 const calls=[]
 const fetch=mock.method(globalThis,'fetch',async(path,options)=>{calls.push([path,options]);return new Response('{}')})
 try {
  await consentToAnalysis(402,[7,8],false,'test-csrf')
  assert.equal(calls[0][0],'/api/ai-matches/profiles/402/consent')
  assert.equal(calls[0][1].credentials,'same-origin')
  assert.equal(calls[0][1].headers['X-Recruitifi-CSRF'],'test-csrf')
  assert.deepEqual(JSON.parse(calls[0][1].body),{material_ids:[7,8],confirm:true,share_with_employer_001:false})
 } finally {fetch.mock.restore()}
})
test('rejected material consent never reports success',async()=>{
 const {consentToAnalysis}=await server.ssrLoadModule('/src/useAiMatches.tsx')
 const fetch=mock.method(globalThis,'fetch',async()=>new Response('{}',{status:403}))
 try{await assert.rejects(consentToAnalysis(402,[9],true,'test-csrf'),/belonging/)}finally{fetch.mock.restore()}
})

test('validation and model errors remain actionable rather than generic success',async()=>{
 const {consentToAnalysis,loadAiProfile,startProfileAnalysis}=await server.ssrLoadModule('/src/useAiMatches.tsx')
 let fetch=mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({detail:'Use a public GitHub repository URL: https://github.com/owner/repository.'}),{status:422}))
 try{await assert.rejects(consentToAnalysis(402,[1],false,'csrf'),/owner\/repository/)}finally{fetch.mock.restore()}
 fetch=mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify({status:'unavailable',matches:{},reason:'no_extractable_text',detail:'This PDF has no readable text.'})))
 try{assert.equal((await loadAiProfile(402)).detail,'This PDF has no readable text.')}finally{fetch.mock.restore()}
 fetch=mock.method(globalThis,'fetch',async()=>new Response('{}',{status:403}))
 try{await assert.rejects(startProfileAnalysis(402),/sign-in expired/)}finally{fetch.mock.restore()}
})
test('malformed score responses cannot crash rendering or fabricate percentages',async()=>{
 const {loadAiProfile}=await server.ssrLoadModule('/src/useAiMatches.tsx')
 for(const body of [{status:'completed',matches:{1:{status:'completed',requirements:[]}}},{status:'completed',matches:[]},{status:'completed',matches:{1:{status:'completed',score:101,requirements:[]}}}]){
  const fetch=mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify(body)))
  try{await assert.rejects(loadAiProfile(402),/Invalid analysis response/)}finally{fetch.mock.restore()}
 }
 assert.equal(aiLabel({status:'completed',score:undefined,requirements:[]}), 'Not analyzed')
})
test('successful trigger requires a real queued job and retains CSRF',async()=>{
 const {startProfileAnalysis}=await server.ssrLoadModule('/src/useAiMatches.tsx')
 const calls=[]
 const fetch=mock.method(globalThis,'fetch',async(path,options)=>{
  calls.push([path,options]);return calls.length===1?new Response(JSON.stringify({candidate_id:402,csrf:'test-csrf'})):new Response(JSON.stringify({job_id:'a'.repeat(32),status:'queued'}),{status:202})
 })
 try{assert.equal((await startProfileAnalysis(402)).status,'queued');assert.equal(calls[1][1].headers['X-Recruitifi-CSRF'],'test-csrf')}finally{fetch.mock.restore()}
})

test('oversized responses and another Talent session are rejected before analysis',async()=>{
 const {loadAiProfile,startProfileAnalysis}=await server.ssrLoadModule('/src/useAiMatches.tsx')
 let fetch=mock.method(globalThis,'fetch',async()=>new Response('x'.repeat(1048577)))
 try{await assert.rejects(loadAiProfile(402),/safe size limit/)}finally{fetch.mock.restore()}
 let calls=0
 fetch=mock.method(globalThis,'fetch',async()=>{calls++;return new Response(JSON.stringify({candidate_id:406,csrf:'test-csrf'}))})
 try{await assert.rejects(startProfileAnalysis(402,[1]),/not your verified profile/);assert.equal(calls,1)}finally{fetch.mock.restore()}
})


test('all saved resource categories describe the actual analysis capability',async()=>{
 const {resourceAnalysisMode,analysisRevision}=await server.ssrLoadModule('/src/analysisResources.ts')
 for(const category of ['cv','project','certificate','research'])assert.match(resourceAnalysisMode({category,content_type:'application/pdf'}),/PDF text/)
 for(const category of ['linkedin','website','certificate','research','project'])assert.match(resourceAnalysisMode({category,url:'https://example.invalid',description:'Synthetic description'}),/external page is not fetched/)
 assert.match(resourceAnalysisMode({category:'certificate',content_type:'image/png'}),/no OCR/)
 assert.match(resourceAnalysisMode({category:'github'}),/owner\/repository/)
 const profile={candidate:{skills:[]},materials:[{id:1,description:'Synthetic Python API'}]}
 const initial=analysisRevision(profile)
 assert.notEqual(analysisRevision({...profile,candidate:{skills:[{skill_id:3,evidence_tier:'self_declared'}]}}),initial)
 assert.notEqual(analysisRevision({...profile,materials:[{id:1,description:'Edited synthetic API'}]}),initial)
 assert.notEqual(analysisRevision({...profile,materials:[]}),initial)
})


test('bare profiles are labelled as skipped rather than repository retrieval',async()=>{
 const {resourceAnalysisMode}=await server.ssrLoadModule('/src/analysisResources.ts')
 assert.match(resourceAnalysisMode({category:'linkedin',url:'https://www.linkedin.com/in/synthetic',description:''}),/Not analyzed.*does not block/)
 assert.match(resourceAnalysisMode({category:'github',url:'https://github.com/SyntheticOwner',description:''}),/Not analyzed/)
 assert.match(resourceAnalysisMode({category:'github',url:'https://github.com/SyntheticOwner',description:'Synthetic Python project'}),/Saved description only/)
 assert.match(resourceAnalysisMode({category:'github',url:'https://github.com/SyntheticOwner/Repository',description:''}),/Public repository files/)
})
test('description editor uses the existing verified session and CSRF',async()=>{
 const {saveResourceDescription}=await server.ssrLoadModule('/src/useAiMatches.tsx')
 const calls=[]
 const fetch=mock.method(globalThis,'fetch',async(path,options)=>{
  calls.push([path,options]);return new Response(JSON.stringify(calls.length===1?{candidate_id:402,csrf:'test-csrf'}:{material_id:7,description:'Synthetic Python project'}))
 })
 try{
  assert.equal(await saveResourceDescription(402,7,'Synthetic Python project'),'Synthetic Python project')
  assert.equal(calls[1][0],'/api/ai-matches/profiles/402/materials/7/description')
  assert.equal(calls[1][1].method,'PATCH')
  assert.equal(calls[1][1].headers['X-Recruitifi-CSRF'],'test-csrf')
 }finally{fetch.mock.restore()}
})

test('automatic profile retrieval is labelled separately from saved descriptions',async()=>{
 const {resourceAnalysisMode,sourceAnalysisNote}=await server.ssrLoadModule('/src/analysisResources.ts')
 assert.match(resourceAnalysisMode({category:'github',url:'https://github.com/SyntheticOwner',description:''},true),/Automatically retrieves public bio/)
 assert.match(resourceAnalysisMode({category:'linkedin',url:'https://www.linkedin.com/in/synthetic',description:''},true),/publicly accessible professional profile text/)
 assert.match(sourceAnalysisNote({content_status:'public_github_metadata'}),/Retrieved public GitHub/)
 assert.match(sourceAnalysisNote({content_status:'public_profile_text'}),/Retrieved publicly accessible/)
 assert.match(sourceAnalysisNote({content_status:'not_analyzed',detail:'LinkedIn blocked access'}),/blocked access/)
})
