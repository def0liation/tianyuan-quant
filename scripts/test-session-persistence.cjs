const assert = require('node:assert/strict')
const { test } = require('node:test')
const { once } = require('node:events')
const { createRequire } = require('node:module')
const path = require('node:path')
const http = require('node:http')
const frontendRequire = createRequire(path.resolve(__dirname, '../frontend/package.json'))
const { build } = frontendRequire('esbuild')
const { chromium } = frontendRequire('playwright')

test('browser refresh preserves the session token and clears it permanently', async (t) => {
  const bundle = await build({
    entryPoints: [path.resolve(__dirname, '../frontend/src/store/operatorContext.ts')],
    bundle: true, write: false, format: 'esm', platform: 'browser',
  })
  const html = '<title>session fixture</title><script type="module">import * as session from "/session.js";window.sessionFixture=session;</script>'
  const server = http.createServer((request, response) => {
    if (request.url === '/session.js') {
      response.writeHead(200, { 'Content-Type': 'text/javascript' })
      response.end(bundle.outputFiles[0].text)
    } else {
      response.writeHead(200, { 'Content-Type': 'text/html' })
      response.end(html)
    }
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise((resolve) => server.close(resolve)))
  const browser = await chromium.launch({ headless: true, channel: 'chromium' })
  t.after(() => browser.close())
  const page = await browser.newPage()
  await page.goto(`http://127.0.0.1:${server.address().port}`)
  await page.waitForFunction(() => Boolean(window.sessionFixture))
  await page.evaluate(() => {
    window.sessionFixture.setOperatorContext({ id: 'audit-viewer', role: 'viewer' })
    window.sessionFixture.setOperatorApiToken('synthetic-session-fixture')
  })
  await page.reload()
  await page.waitForFunction(() => Boolean(window.sessionFixture))
  const restored = await page.evaluate(() => ({
    context: window.sessionFixture.getOperatorContext(),
    headers: window.sessionFixture.getOperatorHeaders(),
  }))
  assert.equal(restored.context.role, 'viewer')
  assert.equal(restored.context.apiTokenSet, true)
  assert.equal(restored.headers.Authorization, 'Bearer synthetic-session-fixture')
  await page.evaluate(() => window.sessionFixture.clearOperatorApiToken())
  await page.reload()
  await page.waitForFunction(() => Boolean(window.sessionFixture))
  const cleared = await page.evaluate(() => ({
    context: window.sessionFixture.getOperatorContext(),
    headers: window.sessionFixture.getOperatorHeaders(),
  }))
  assert.equal(cleared.context.apiTokenSet, false)
  assert.equal(cleared.headers.Authorization, undefined)
})
