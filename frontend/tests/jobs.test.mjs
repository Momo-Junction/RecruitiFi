import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
after(() => server.close())
const { filterJobs, readIndustryFilters, saveIndustryFilters, industryFilterKey, jobCompanyId, IndustryFilters, JobEmptyState, JobRequirements } = await server.ssrLoadModule('/src/Jobs.tsx')
const { CandidateSignal } = await server.ssrLoadModule('/src/EmployerWorkspace.tsx')
const api = await server.ssrLoadModule('/src/api.ts')
const categories = [
  ['it', 'IT'], ['business_services', 'Business (Services)'], ['logistics', 'Logistics'],
  ['health_sector', 'Health Sector'], ['restaurant', 'Restaurant'], ['cleaning', 'Cleaning'], ['engineering', 'Engineering'],
].map(([id, label]) => ({ id, label }))
const jobs = categories.map((category, index) => ({
  id: 1001 + index, company_id: index < 2 ? 1 : 2, company_name: 'Synthetic employer', title: `Synthetic ${category.label} job`,
  industry: category.id, industry_label: category.label, description: 'Synthetic demo only', active: true,
  working_language: 'English', relocation_support: false, min_match_threshold: 75,
  must_have_skills: [{ skill_id: 1, weight: 70 }], nice_to_have_skills: [{ skill_id: 2, weight: 20 }],
}))

test('industry filters use OR, clear to all active jobs, and handle unknown/empty results', () => {
  assert.deepEqual(filterJobs(jobs, ['it']).map((job) => job.id), [1001])
  assert.deepEqual(filterJobs(jobs, ['it', 'engineering']).map((job) => job.id), [1001, 1007])
  assert.deepEqual(filterJobs(jobs, []), jobs)
  assert.deepEqual(filterJobs(jobs, ['healthcare']), [])
  assert.deepEqual(filterJobs([], []), [])
  assert.deepEqual(filterJobs([{ ...jobs[0], active: false }], []), [])
})
test('industry chips preserve exact labels, multiple selected state, clear and honest empty states', () => {
  const html = renderToString(React.createElement(IndustryFilters, { categories, selected: ['it', 'engineering'], onChange() {} }))
  for (const { label } of categories) assert.ok(html.includes(label))
  assert.equal((html.match(/aria-pressed="true"/g) ?? []).length, 2)
  assert.match(html, /Clear Filters/)
  assert.match(renderToString(React.createElement(JobEmptyState, { hasJobs: true })), /No active jobs match/)
  assert.match(renderToString(React.createElement(JobEmptyState, { hasJobs: false })), /initialize jobs/)
})
test('filters persist per Talent session without changing the selected account', () => {
  const original = globalThis.sessionStorage
  const values = new Map([['recruitifi.demoAccount', '{"demo_account_id":"talent-001"}']])
  globalThis.sessionStorage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
  try {
    saveIndustryFilters(402, ['it', 'engineering'])
    assert.deepEqual(readIndustryFilters(402), ['it', 'engineering'])
    assert.deepEqual(readIndustryFilters(406), [])
    saveIndustryFilters(406, ['restaurant'])
    assert.deepEqual(readIndustryFilters(402), ['it', 'engineering'])
    assert.equal(values.get('recruitifi.demoAccount'), '{"demo_account_id":"talent-001"}')
    values.set(industryFilterKey(402), '["it","unknown","it"]')
    assert.deepEqual(readIndustryFilters(402), ['it'])
    values.set(industryFilterKey(402), '{broken')
    assert.deepEqual(readIndustryFilters(402), [])
    saveIndustryFilters(402, [])
    assert.deepEqual(readIndustryFilters(402), [])
  } finally { if (original === undefined) delete globalThis.sessionStorage; else globalThis.sessionStorage = original }
  assert.deepEqual(readIndustryFilters(402), [])
})
test('job details display required/preferred weights, language, industry and company-level interest semantics', () => {
  const html = renderToString(React.createElement(JobRequirements, { job: jobs[0], skills: [{ id: 1, name: 'Python' }, { id: 2, name: 'SQL' }] }))
  for (const text of ['Required:', 'Preferred:', 'Python (70)', 'SQL (20)', 'English', 'IT', 'likes and passes apply to the company']) assert.ok(html.includes(text))
})
test('job selection and filtering use job scoring endpoints but preserve company-level swipe keys', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, body: options.body })
    return new Response(JSON.stringify(url.endsWith('/api/swipes') ? { ...JSON.parse(options.body), mutual_match: true } : []))
  }
  try {
    const signal = new AbortController().signal
    await api.loadJobs(signal, ['it', 'engineering'])
    await api.loadJobMatches(1001, signal)
    await api.loadJobMatches(1002, signal)
    await api.loadCompanyJobs(1, signal)
    await api.loadCandidateJobMatches(402, signal)
    const filtered = filterJobs(jobs, ['business_services'])
    const selected = filtered[0]
    const companyId = jobCompanyId(jobs, selected.id)
    const saved = await api.saveSwipe({ candidate_id: 402, company_id: companyId, actor: 'talent', decision: 'like' })
    assert.equal(saved.mutual_match, true)
    assert.equal(companyId, 1)
    assert.throws(() => jobCompanyId(jobs, 99999), /no longer available/)
    assert.ok(calls[0].url.endsWith('/api/jobs?industry=it&industry=engineering'))
    assert.ok(calls[1].url.endsWith('/api/jobs/1001/matches'))
    assert.ok(calls[2].url.endsWith('/api/jobs/1002/matches'))
    assert.ok(calls[3].url.endsWith('/api/companies/1/jobs'))
    assert.ok(calls[4].url.endsWith('/api/candidates/402/job-matches'))
    assert.deepEqual(JSON.parse(calls[5].body), { candidate_id: 402, company_id: 1, actor: 'talent', decision: 'like' })
    assert.ok(!('job_id' in JSON.parse(calls[5].body)))
  } finally { globalThis.fetch = original }
})
test('job-fit queue requires existing explicit human review before company-level meeting acceptance', () => {
  const match = { anonymous_code: 'Talent #402', total_score: 90, must_have_skills: [], nice_to_have_skills: [], dealbreaker_reasons: [], meets_threshold: true, dealbreakers_passed: true }
  const html = renderToString(React.createElement(CandidateSignal, { match, companyId: 1, interested: true, jobContext: true }))
  assert.match(html, /Job fit is shown/)
  assert.match(html, /type="checkbox"/)
  assert.match(html, /disabled=""/)
  assert.match(html, />Interested<\/span>/)
})
