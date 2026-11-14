import assert from 'node:assert/strict'
import { test, after } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'
const server=await createServer({server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
after(()=>server.close())
const {EmployerEvidence}=await server.ssrLoadModule('/src/EmployerEvidence.tsx')
const {EvidenceAnalysis}=await server.ssrLoadModule('/src/EvidenceAnalysis.tsx')
test('Employer controls remain hidden until server capability is checked',()=>{
 assert.equal(renderToString(React.createElement(EmployerEvidence,{companyId:1,candidateId:402})), '')
})
test('review state is explicit and never becomes proficiency',()=>{
 const html=renderToString(React.createElement(EvidenceAnalysis,{view:{candidateId:402,materialId:7,status:'completed',sources:[],findings:[{id:1,source_id:1,skill_name:'Python',finding_kind:'semantic',similarity_score:.42,review_status:'accepted'}]}}))
 assert.match(html,/Review: accepted/);assert.match(html,/0\.420/);assert.doesNotMatch(html,/42%/)
})
