import assert from 'node:assert/strict'
import { test, after, mock } from 'node:test'
import { createServer } from 'vite'
const server=await createServer({server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'})
after(()=>server.close())
const {loginAccount}=await server.ssrLoadModule('/src/accountSession.ts')
test('application entry verifies existing HttpOnly cookie before accepting account',async()=>{
 const calls=[]
 const fetch=mock.method(globalThis,'fetch',async(path,options)=>{
  calls.push([path,options])
  return new Response(JSON.stringify({account_id:'talent-ai-001',candidate_id:900001}))
 })
 try {
  await loginAccount('talent-ai-001','synthetic-test-password')
  assert.equal(calls.length,2)
  assert.equal(calls[0][1].credentials,'same-origin')
  assert.equal(calls[0][0],'/api/evidence-session')
  assert.equal(calls[1][1].cache,'no-store')
 } finally{fetch.mock.restore()}
})
test('bad credentials and mismatched cookie cannot enter verified dashboard',async()=>{
 for(const response of [()=>new Response('{}',{status:403}),()=>new Response(JSON.stringify({account_id:'another-account'}))]){
  const fetch=mock.method(globalThis,'fetch',async()=>response())
  try{await assert.rejects(loginAccount('talent-ai-001','synthetic-test-password'),/failed|verified/)}finally{fetch.mock.restore()}
 }
})
test('all role aliases use the same password-verified account session',async()=>{
 for(const account of ['talent-015','employer-005','organizer-001']){
  const calls=[]
  const fetch=mock.method(globalThis,'fetch',async(path,options)=>{calls.push([path,options]);return new Response(JSON.stringify({account_id:account}))})
  try {
   await loginAccount(account,'synthetic-distinct-password')
   assert.equal(JSON.parse(calls[0][1].body).account,account)
   assert.equal(calls[0][1].method,'POST')
   assert.equal(calls[1][1].credentials,'same-origin')
  }finally{fetch.mock.restore()}
 }
})
test('password-free mode establishes a server cookie without sending a password or token',async()=>{
 const calls=[]
 const fetch=mock.method(globalThis,'fetch',async(path,options)=>{calls.push([path,options]);return new Response(JSON.stringify({account_id:'employer-005'}))})
 try{
  await loginAccount('employer-005')
  assert.deepEqual(JSON.parse(calls[0][1].body),{account:'employer-005',password:''})
  assert.equal(calls[0][1].credentials,'same-origin')
  assert.equal(calls.length,2)
 }finally{fetch.mock.restore()}
})
test('password-free configuration still requires a signed selection and rejects invalid flags',async()=>{
 const {loadAccountConfiguration}=await server.ssrLoadModule('/src/accountSession.ts')
 for(const [value,expected] of [
  [{verified_login_required:true,password_free_demo:true},{sessionRequired:true,passwordFree:true}],
  [{verified_login_required:true},{sessionRequired:true,passwordFree:false}],
  [{verified_login_required:false,password_free_demo:true},null],
  [{verified_login_required:true,password_free_demo:'true'},null],
 ]){
  const fetch=mock.method(globalThis,'fetch',async()=>new Response(JSON.stringify(value)))
  try{
   if(expected)assert.deepEqual(await loadAccountConfiguration(),expected)
   else await assert.rejects(loadAccountConfiguration(),/Invalid account/)
  }finally{fetch.mock.restore()}
 }
})
