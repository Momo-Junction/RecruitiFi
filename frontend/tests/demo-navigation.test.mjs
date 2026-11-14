import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
after(() => server.close())
const { createDemoNavigation, resolveDemoRoute, demoAccountKey } = await server.ssrLoadModule('/src/demoNavigation.ts')
const { App } = await server.ssrLoadModule('/src/App.tsx')
const accounts = [
  { demo_account_id: 'talent-001', role: 'talent', candidate_id: 402, display_name: 'Aino Lehtinen', available: true },
  { demo_account_id: 'talent-002', role: 'talent', candidate_id: 406, display_name: 'Samir Haddad', available: true },
  { demo_account_id: 'employer-001', role: 'employer', company_id: 1, display_name: 'Kide Quantum Labs', available: true },
  { demo_account_id: 'employer-002', role: 'employer', company_id: 2, display_name: 'Kallio Grid Energy', available: true },
  { demo_account_id: 'organizer-001', role: 'organizer', display_name: 'Espoo Organizer Admin', available: true },
]
function browser(path = '/', account = null) {
  const stored = new Map(account ? [[demoAccountKey, JSON.stringify(account)]] : [])
  const entries = [path]
  let index = 0
  const location = { pathname: path }
  return {
    location,
    sessionStorage: { getItem: (key) => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value), removeItem: (key) => stored.delete(key) },
    history: {
      pushState(_, __, next) { entries.splice(index + 1); entries.push(next); index++; location.pathname = next },
      replaceState(_, __, next) { entries[index] = next; location.pathname = next },
    },
    back() { index = Math.max(0, index - 1); location.pathname = entries[index] },
    forward() { index = Math.min(entries.length - 1, index + 1); location.pathname = entries[index] },
  }
}

test('each individual identity persists its account and profile IDs across refresh', () => {
  for (const account of accounts) {
    const target = browser()
    assert.deepEqual(createDemoNavigation(target).select(account), account)
    assert.equal(target.location.pathname, '/' + account.role)
    assert.deepEqual(JSON.parse(target.sessionStorage.getItem(demoAccountKey)), account)
    assert.deepEqual(createDemoNavigation(target).sync(), account)
  }
})
test('direct URLs require an account and redirect mismatched roles to the selected identity', () => {
  for (const path of ['/talent', '/employer', '/organizer']) {
    assert.deepEqual(resolveDemoRoute(path, null), { account: null, path: '/' })
    assert.deepEqual(resolveDemoRoute(path, accounts[0]), { account: accounts[0], path: '/talent' })
  }
  const target = browser('/organizer', accounts[2])
  assert.deepEqual(createDemoNavigation(target).sync(), accounts[2])
  assert.equal(target.location.pathname, '/employer')
  assert.deepEqual(resolveDemoRoute('/unknown', accounts[0]), { account: null, path: '/' })
})
test('logout clears identity; back/forward cannot resurrect a previous account', () => {
  const target = browser(); const navigation = createDemoNavigation(target)
  navigation.select(accounts[0])
  target.back(); assert.equal(navigation.sync(), null)
  target.forward(); assert.deepEqual(navigation.sync(), accounts[0])
  navigation.select(null)
  assert.equal(target.sessionStorage.getItem(demoAccountKey), null)
  target.back(); assert.equal(navigation.sync(), null)
  assert.equal(target.location.pathname, '/')
  navigation.select(accounts[1]); target.back(); navigation.sync(); target.forward()
  assert.deepEqual(navigation.sync(), accounts[1])
})
test('unavailable storage supports in-page selection/logout; corrupt storage never selects another identity', () => {
  const target = browser()
  Object.defineProperty(target, 'sessionStorage', { get() { throw new Error('Storage unavailable') } })
  const navigation = createDemoNavigation(target)
  navigation.select(accounts[4]); assert.deepEqual(navigation.sync(), accounts[4])
  navigation.select(null); assert.equal(navigation.sync(), null)
  const corrupt = browser('/talent')
  for (const value of ['{broken', '"talent"', JSON.stringify({ ...accounts[0], available: false }), JSON.stringify({ ...accounts[0], candidate_id: null })]) {
    corrupt.sessionStorage.setItem(demoAccountKey, value)
    assert.equal(createDemoNavigation(corrupt).sync(), null)
  }
  assert.throws(() => navigation.select({ ...accounts[0], available: false }), /available demo account/)
})
test('welcome preserves existing role choices and explicitly describes demo-only authorization', () => {
  const html = renderToString(React.createElement(App))
  for (const role of ['Talent', 'Employer', 'Espoo Organizer']) assert.ok(html.includes('Continue as ' + role) || html.includes('Continue as <!-- -->' + role))
  assert.match(html, /no secure account authorization/)
  assert.ok(!html.includes('Candidate persona'))
})
test('stored session waits for server account validation before any personal dashboard renders', () => {
  const original = globalThis.window
  try {
    for (const account of accounts) {
      globalThis.window = browser('/' + account.role, account)
      const html = renderToString(React.createElement(App))
      assert.match(html, /Checking your demo account/)
      assert.match(html, /Logout \/ Switch Account/)
      assert.ok(!html.includes('aria-label="Notifications'))
      assert.ok(!html.includes('Your skills'))
    }
  } finally { if (original === undefined) delete globalThis.window; else globalThis.window = original }
})

const api = await server.ssrLoadModule('/src/api.ts')
test('one shared account header scopes all requests and client guards reject mismatched writes', async () => {
  const previousWindow = globalThis.window, previousFetch = globalThis.fetch
  const calls = []
  globalThis.window = browser()
  const nav = createDemoNavigation(globalThis.window)
  globalThis.fetch = async (url, options) => {
    calls.push({ url, account: options.headers.get('X-Recruitifi-Demo-Account'), cache: options.cache })
    const id = Number(url.match(/candidates\/(\d+)/)?.[1])
    if (url.includes('/profile') || url.includes('/skills')) return new Response(JSON.stringify({ candidate: { id }, materials: [] }))
    if (url.includes('/role')) return new Response(JSON.stringify({ id: Number(url.match(/companies\/(\d+)/)[1]) }))
    return new Response(JSON.stringify({ entries: [], unread_count: 0 }))
  }
  try {
    nav.select(accounts[0])
    await api.profileRequest(402)
    await assert.rejects(api.profileRequest(406, 'skills', { method: 'PUT' }), /different demo account/)
    await assert.rejects(api.saveCompanyRole(1, {}), /different demo account/)
    await assert.rejects(api.saveSwipe({ candidate_id: 406, company_id: 1, actor: 'talent', decision: 'like' }), /different demo account/)
    await assert.rejects(api.loadNotifications('talent', 406, new AbortController().signal), /different demo account/)
    assert.equal(calls.length, 1)
    nav.select(null); nav.select(accounts[1])
    await api.profileRequest(406)
    await api.markNotificationRead('talent', 406, 2)
    nav.select(null); nav.select(accounts[2])
    await api.saveCompanyRole(1, {})
    await assert.rejects(api.saveCompanyRole(2, {}), /different demo account/)
    await assert.rejects(api.saveSwipe({ candidate_id: 402, company_id: 2, actor: 'employer', decision: 'like' }), /different demo account/)
    assert.deepEqual(calls.map((call) => call.account), ['talent-001', 'talent-002', 'talent-002', 'employer-001'])
    nav.select(null)
    await api.loadDemoAccounts(new AbortController().signal)
    assert.equal(calls.at(-1).account, null)
    assert.ok(calls.every((call) => call.cache === 'no-store'))
  } finally {
    nav.select(null)
    if (previousWindow === undefined) delete globalThis.window; else globalThis.window = previousWindow
    globalThis.fetch = previousFetch
  }
})
test('a wrong profile in a successful API response is rejected rather than rendered', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ candidate: { id: 406 }, materials: [] }))
  try { await assert.rejects(api.profileRequest(402), /different demo profile/) }
  finally { globalThis.fetch = original }
})
