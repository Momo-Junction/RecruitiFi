import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
after(() => server.close())
const { EvidenceAnalysis } = await server.ssrLoadModule('/src/EvidenceAnalysis.tsx')
const { ProfileMaterials } = await server.ssrLoadModule('/src/ProfileMaterials.tsx')
const view = { candidateId: 402, materialId: 7, status: 'completed',
  findings: [{ id: 1, skill_name: 'Python', finding_kind: 'semantic', source_id: 1, similarity_score: 0.42 },
    { id: 2, skill_name: 'React', finding_kind: 'observation', source_id: 1, similarity_score: null, observed_value: 'react' }],
  sources: [{ id: 1, excerpt: '<script>untrusted</script>', file_path: 'README.md', evidence_field: 'readme_text', source_reference: 'https://api.github.com/repos/Owner/Repo/git/blobs/' + 'a'.repeat(40) }] }
const render = value => renderToString(React.createElement(EvidenceAnalysis, { view: value }))
test('separates observations and relevance without proficiency percentages', () => {
  const html = render(view)
  assert.match(html, /Semantic relevance/)
  assert.match(html, /Repository observations/)
  assert.match(html, /0\.420/)
  assert.doesNotMatch(html, /42%|proficiency percentage/)
  assert.equal((html.match(/· Unreviewed/g) ?? []).length, 2)
  assert.match(html, /Immutable GitHub blob/)
})
test('renders all statuses and escapes untrusted excerpts', () => {
  for (const status of ['pending', 'running', 'completed', 'failed', 'unavailable']) {
    assert.match(render({ ...view, status }), new RegExp(status, 'i'))
  }
  assert.doesNotMatch(render(view), /<script>/)
  assert.match(render(view), /&lt;script&gt;/)
})
test('unsafe references never become clickable links', () => {
  for (const source_reference of ['javascript:alert(1)', 'https://api.github.com.evil.com/file', 'http://localhost/private']) {
    assert.doesNotMatch(render({ ...view, sources: [{ ...view.sources[0], source_reference }] }), /href=/)
  }
})
test('materials default hides analysis and rejects other candidate results', () => {
  const props = { profile: { candidate: { id: 402 }, materials: [{ id: 7, category: 'project', title: 'Synthetic', url: 'https://example.invalid' }] }, skills: [], onSaved() {} }
  const html = renderToString(React.createElement(ProfileMaterials, props))
  assert.doesNotMatch(html, /Analyze Evidence|AI evidence analysis/)
  assert.match(html, /Remove/)
  assert.doesNotMatch(renderToString(React.createElement(ProfileMaterials, { ...props, analysisViews: [{ ...view, candidateId: 403 }] })), /AI evidence analysis/)
  assert.match(renderToString(React.createElement(ProfileMaterials, { ...props, analysisViews: [view] })), /AI evidence analysis/)
})
