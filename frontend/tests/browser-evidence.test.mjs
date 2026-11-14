import assert from 'node:assert/strict'
import { test, after } from 'node:test'
import React from 'react'
import { renderToString } from 'react-dom/server'
import { createServer } from 'vite'
const server = await createServer({ server:{middlewareMode:true,hmr:false,ws:false},appType:'custom' })
after(()=>server.close())
const { BrowserEvidence } = await server.ssrLoadModule('/src/BrowserEvidence.tsx')
test('browser controls remain hidden until server session capability is checked',()=>{
 const html=renderToString(React.createElement(BrowserEvidence,{candidateId:402,materialId:7}))
 assert.equal(html,'')
 assert.doesNotMatch(html,/token|password|Analyze Evidence/i)
})
