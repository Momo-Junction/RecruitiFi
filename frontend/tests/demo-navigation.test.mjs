import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
after(() => server.close())
const { createDemoNavigation, resolveDemoRoute, demoRoleKey } = await server.ssrLoadModule('/src/demoNavigation.ts')
const { App } = await server.ssrLoadModule('/src/App.tsx')

function browser(path = '/', stored = null) {
  let value = stored
  const entries = [path]
  let index = 0
  const location = { pathname: path }
  const target = {
    location,
    sessionStorage: { getItem: () => value, setItem: (_, next) => { value = next }, removeItem: () => { value = null } },
    history: {
      pushState(_, __, next) { entries.splice(index + 1); entries.push(next); index++; location.pathname = next },
      replaceState(_, __, next) { entries[index] = next; location.pathname = next },
    },
    back() { index = Math.max(0, index - 1); location.pathname = entries[index] },
    forward() { index = Math.min(entries.length - 1, index + 1); location.pathname = entries[index] },
  }
  return target
}

test('each role selection navigates and survives a new controller on refresh', () => {
  for (const role of ['talent', 'employer', 'organizer']) {
    const target = browser()
    assert.equal(createDemoNavigation(target).select(role), role)
    assert.equal(target.location.pathname, '/' + role)
    assert.equal(target.sessionStorage.getItem(demoRoleKey), role)
    assert.equal(createDemoNavigation(target).sync(), role)
  }
})

test('direct URLs require a selected role and redirect mismatched roles', () => {
  for (const path of ['/talent', '/employer', '/organizer']) {
    assert.deepEqual(resolveDemoRoute(path, null), { role: null, path: '/' })
    assert.deepEqual(resolveDemoRoute(path, 'talent'), { role: 'talent', path: '/talent' })
  }
  const target = browser('/organizer', 'employer')
  assert.equal(createDemoNavigation(target).sync(), 'employer')
  assert.equal(target.location.pathname, '/employer')
  assert.deepEqual(resolveDemoRoute('/unknown', 'talent'), { role: null, path: '/' })
})

test('back and forward resolve routes, and exiting clears selection', () => {
  const target = browser(); const navigation = createDemoNavigation(target)
  navigation.select('talent')
  target.back(); assert.equal(navigation.sync(), null)
  target.forward(); assert.equal(navigation.sync(), 'talent')
  navigation.select(null)
  assert.equal(target.sessionStorage.getItem(demoRoleKey), null)
  target.back(); assert.equal(navigation.sync(), null)
  assert.equal(target.location.pathname, '/')
})

test('unavailable storage does not stop in-page selection or exit', () => {
  const target = browser()
  Object.defineProperty(target, 'sessionStorage', { get() { throw new Error('Storage unavailable') } })
  const navigation = createDemoNavigation(target)
  navigation.select('organizer'); assert.equal(navigation.sync(), 'organizer')
  navigation.select(null); assert.equal(navigation.sync(), null)
})

test('welcome page has three role choices and no dashboard tabs', () => {
  const html = renderToString(React.createElement(App))
  for (const role of ['Talent', 'Employer', 'Espoo Organizer']) assert.ok(html.includes('Continue as ' + role) || html.includes('Continue as <!-- -->' + role))
  assert.ok(!html.includes('aria-label="Demo roles"'))
  assert.ok(!html.includes('Switch Role'))
})

test('selected dashboard renders its header and Switch Role without role cards or tabs', () => {
  const original = globalThis.window
  try {
    for (const role of ['talent', 'employer', 'organizer']) {
      globalThis.window = browser('/' + role, role)
      const html = renderToString(React.createElement(App))
      assert.ok(html.includes('Switch Role'))
      assert.ok(!html.includes('Continue as'))
      assert.ok(!html.includes('aria-label="Demo roles"'))
    }
  } finally {
    if (original === undefined) delete globalThis.window
    else globalThis.window = original
  }
})
