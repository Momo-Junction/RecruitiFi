import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

// Exercise the actual TSX component and its initial hook state, without a DOM mock.
const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
after(() => server.close())
const { TalentWorkspace } = await server.ssrLoadModule('/src/TalentWorkspace.tsx')
const { profileRequest } = await server.ssrLoadModule('/src/api.ts')
const props = {
  candidateId: 402, candidates: [], companies: [], skills: [], onSaved() {},
  swipeStore: { swipes: [], ready: true, error: '', retry() {}, async decide() {}, async undo() {} },
}

test('empty API directory renders the existing empty state before a profile is loaded', () => {
  const html = renderToString(React.createElement(TalentWorkspace, props))
  assert.match(html, /demo candidate profile is unavailable/)
})

test('seeded directory renders loading state while saved profile request is pending', () => {
  const candidate = { id: 402, anonymous_code: 'Talent #402', full_name: 'Synthetic test', email: 'test@example.com', has_cv: false, has_portfolio: false, languages: {}, needs_visa_sponsorship: false, skills: [] }
  const html = renderToString(React.createElement(TalentWorkspace, { ...props, candidates: [candidate] }))
  assert.match(html, /Loading your saved profile/)
})

test('profile API failures reject instead of fabricating a saved candidate', async () => {
  const originalFetch = globalThis.fetch
  try {
    for (const status of [401, 503]) {
      globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Synthetic API failure' }), { status, headers: { 'Content-Type': 'application/json' } })
      await assert.rejects(profileRequest(402), /Synthetic API failure/)
    }
    globalThis.fetch = async () => { throw new TypeError('Synthetic network failure') }
    await assert.rejects(profileRequest(402), /Synthetic network failure/)
  } finally { globalThis.fetch = originalFetch }
})
