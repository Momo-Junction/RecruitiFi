import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
after(() => server.close())
const { interestedCandidates, demoPollInterval } = await server.ssrLoadModule('/src/useSwipes.ts')
const { SwipeDeck } = await server.ssrLoadModule('/src/SwipeDeck.tsx')
const { CandidateSignal } = await server.ssrLoadModule('/src/EmployerWorkspace.tsx')
const { saveSwipe, loadNotifications, markNotificationRead } = await server.ssrLoadModule('/src/api.ts')
const rows = [
  { candidate_id: 402, company_id: 1, actor: 'talent', decision: 'like' },
  { candidate_id: 406, company_id: 2, actor: 'talent', decision: 'like' },
  { candidate_id: 411, company_id: 1, actor: 'talent', decision: 'pass' },
  { candidate_id: 417, company_id: 1, actor: 'employer', decision: 'like' },
]

test('Interested is derived only from that company’s incoming talent likes', () => {
  assert.deepEqual([...interestedCandidates(rows, 1)], [402])
  assert.deepEqual([...interestedCandidates(rows, 2)], [406])
  const withdrawn = rows.map((row) => row.candidate_id === 402 ? { ...row, decision: 'pass' } : row)
  assert.deepEqual([...interestedCandidates(withdrawn, 1)], [])
  assert.deepEqual([...interestedCandidates(rows.slice(1), 1)], [])
  assert.equal(demoPollInterval, 12000)
})

const card = { id: 402, name: 'Talent #402', subtitle: 'Synthetic', monogram: '02', score: 56, eligible: false, likedYou: true, interestLabel: 'Interested', facts: [], skills: [], warnings: [] }
const deck = { cards: [card], loading: false, onRetry() {}, async onDecide() { return false }, saved: [], async onUndo() {} }
test('existing swipe card shows exact Interested badge regardless of compatibility score', () => {
  const badge = /class="rounded-full bg-emerald-100[^"]*">Interested<\/span>/
  assert.match(renderToString(React.createElement(SwipeDeck, deck)), badge)
  const html = renderToString(React.createElement(SwipeDeck, { ...deck, cards: [{ ...card, score: 100, eligible: true, likedYou: false }] }))
  assert.doesNotMatch(html, badge)
})

test('existing employer queue card shows and removes the same Interested badge', () => {
  const match = { anonymous_code: 'Talent #402', total_score: 56, must_have_skills: [], nice_to_have_skills: [], dealbreaker_reasons: [], meets_threshold: false, dealbreakers_passed: false }
  assert.match(renderToString(React.createElement(CandidateSignal, { match, companyId: 1, interested: true })), />Interested<\/span>/)
  assert.doesNotMatch(renderToString(React.createElement(CandidateSignal, { match, companyId: 1, interested: false })), />Interested<\/span>/)
})

test('client uses server mutual result, role-scoped notification URLs and read requests', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push([url, options.method ?? 'GET'])
    return new Response(JSON.stringify(options.method === 'PUT' && url.endsWith('/api/swipes') ? { ...rows[0], mutual_match: true } : { entries: [], unread_count: 0 }))
  }
  try {
    assert.equal((await saveSwipe(rows[0])).mutual_match, true)
    await loadNotifications('talent', 402, new AbortController().signal)
    await loadNotifications('employer', 1, new AbortController().signal)
    await markNotificationRead('talent', 402, 3)
    assert.ok(calls[1][0].endsWith('/api/notifications/talent/402'))
    assert.ok(calls[2][0].endsWith('/api/notifications/employer/1'))
    assert.ok(calls[3][0].endsWith('/api/notifications/talent/402/3/read'))
    assert.equal(calls[3][1], 'PUT')
  } finally { globalThis.fetch = original }
})
