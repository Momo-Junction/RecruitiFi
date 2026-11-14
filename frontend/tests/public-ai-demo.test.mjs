import assert from 'node:assert/strict'
import { test, after, mock } from 'node:test'
import { readFile } from 'node:fs/promises'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
after(() => server.close())
const api = await server.ssrLoadModule('/src/demoEvidenceApi.ts')
const id = '900001a1900001a1' + 'a'.repeat(16)
const job = { id, candidate_id: 900001, material_id: 7, status: 'queued', error_code: null }

test('direct trigger and 202 polling use relative demo routes without passwords, CSRF or tokens', async () => {
  const calls = []
  const fetch = mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push([url, init])
    return new Response(JSON.stringify(url.endsWith('/analysis') ? { job_id: id } : { job, analysis: null }), { status: 202 })
  })
  try {
    assert.equal(await api.startDemoAnalysis(900001, 7), id)
    assert.equal((await api.loadDemoResult(900001, 7, id)).job.status, 'queued')
    assert.equal(calls[0][0], '/api/ai-demo/candidates/900001/materials/7/analysis')
    assert.equal(calls[0][1].method, 'POST')
    for (const [path, init] of calls) {
      assert.ok(path.startsWith('/api/ai-demo/'))
      assert.equal(init.credentials, 'same-origin')
      assert.equal(init.headers, undefined); assert.equal(init.body, undefined)
      assert.doesNotMatch(path, /https?:|token|password|embed/)
    }
  } finally { fetch.mock.restore() }
})
test('candidate, company, material and job scopes fail before any request', async () => {
  const fetch = mock.method(globalThis, 'fetch', () => { throw new Error('Unexpected request') })
  try {
    for (const candidate of [402, 406, 900002]) await assert.rejects(api.startDemoAnalysis(candidate, 7), /fictional/)
    await assert.rejects(api.startDemoAnalysis(900001, -1), /fictional/)
    await assert.rejects(api.loadDemoResult(900001, 7, 'https://private.invalid'), /Invalid/)
    await assert.rejects(api.loadEmployerDemo(2, 900001), /Employer/)
    await assert.rejects(api.loadEmployerDemo(1, 402), /Employer/)
    assert.equal(fetch.mock.callCount(), 0)
  } finally { fetch.mock.restore() }
})
test('API denial and service failures stay errors instead of fabricated results', async () => {
  for (const status of [401, 403, 404, 409, 429, 503]) {
    const fetch = mock.method(globalThis, 'fetch', async () => new Response('{}', { status }))
    try { await assert.rejects(api.startDemoAnalysis(900001, 7), error => error.status === status) }
    finally { fetch.mock.restore() }
  }
})
test('Employer reads the same synthetic findings and mismatched responses are rejected', async () => {
  let reply = { candidate_id: 900001, status: 'completed', analyses: [] }
  const fetch = mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify(reply)))
  try {
    assert.equal((await api.loadEmployerDemo(1, 900001)).status, 'completed')
    reply = { candidate_id: 402, status: 'completed', analyses: [] }
    await assert.rejects(api.loadEmployerDemo(1, 900001), /Invalid/)
    reply = { job: { ...job, candidate_id: 402 }, analysis: null }
    await assert.rejects(api.loadDemoResult(900001, 7, id), /scope/)
  } finally { fetch.mock.restore() }
})
test('aborted polling is propagated and both panels have no AI login implementation', async () => {
  const controller = new AbortController(); controller.abort()
  const fetch = mock.method(globalThis, 'fetch', async (_url, init) => {
    assert.equal(init.signal, controller.signal)
    throw new DOMException('Aborted', 'AbortError')
  })
  try { await assert.rejects(api.loadDemoResult(900001, 7, id, controller.signal), { name: 'AbortError' }) }
  finally { fetch.mock.restore() }
  for (const filename of ['BrowserEvidence.tsx', 'EmployerEvidence.tsx']) {
    const source = await readFile(new URL('../src/' + filename, import.meta.url), 'utf8')
    assert.doesNotMatch(source, /evidence-session|csrf|type="password"|setPassword|TALENTMATCH_EMBED|recruitifi-ai:8080/i)
    assert.match(source, /controller\.abort\(\)/)
  }
})
test('malformed successful API bodies fail clearly rather than becoming render state', async () => {
  for (const reply of [null, {}, { job: null }, { job: { ...job, status: 'unexpected' } }]) {
    const fetch = mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify(reply)))
    try { await assert.rejects(api.loadDemoResult(900001, 7, id), /Invalid|scope/) }
    finally { fetch.mock.restore() }
  }
})
