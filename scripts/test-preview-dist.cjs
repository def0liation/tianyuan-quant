const assert = require('node:assert/strict')
const { test } = require('node:test')
const { once } = require('node:events')
const fs = require('node:fs/promises')
const os = require('node:os')
const path = require('node:path')
const http = require('node:http')
const net = require('node:net')
const { spawn } = require('node:child_process')

async function freePort() {
  const server = net.createServer()
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const port = server.address().port
  await new Promise((resolve) => server.close(resolve))
  return port
}

function request(port, urlPath, method = 'GET') {
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, path: urlPath, method }, (response) => {
      const chunks = []
      response.on('data', (chunk) => chunks.push(chunk))
      response.on('end', () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks).toString() }))
      response.on('error', reject)
    })
    req.setTimeout(3000, () => req.destroy(new Error('request timeout')))
    req.on('error', reject)
    req.end()
  })
}

async function fixture(t, options = {}) {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'tianyuan-preview-test-'))
  await fs.mkdir(path.join(directory, 'dist'))
  await fs.mkdir(path.join(directory, 'dist-private'))
  if (options.index !== false) await fs.writeFile(path.join(directory, 'dist', 'index.html'), '<title>audit page</title>')
  await fs.writeFile(path.join(directory, 'dist-private', 'secret.txt'), 'outside fixture')
  await fs.writeFile(path.join(directory, 'dist', 'vanish.js'), 'temporary asset')
  await fs.copyFile(path.resolve(__dirname, '../frontend/preview-dist.cjs'), path.join(directory, 'preview-dist.cjs'))
  const args = []
  if (options.vanish) {
    const preload = path.join(directory, 'preload.cjs')
    await fs.writeFile(preload, "const fs=require('node:fs');const stat=fs.statSync;fs.statSync=function(p,...args){const result=stat.call(this,p,...args);if(String(p).endsWith('vanish.js'))fs.unlinkSync(p);return result}")
    args.push('--require', preload)
  }
  const port = await freePort()
  const child = spawn(process.execPath, [...args, path.join(directory, 'preview-dist.cjs')], {
    env: { ...process.env, HOST: '127.0.0.1', PORT: String(port), API_PROXY_TARGET: options.proxy || '', VITE_API_PROXY_TARGET: '' },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let errors = ''
  child.stderr.on('data', (data) => { errors += data.toString() })
  t.after(async () => {
    if (child.exitCode === null) { child.kill(); await once(child, 'exit') }
    const relative = path.relative(path.resolve(os.tmpdir()), path.resolve(directory))
    assert.ok(relative && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative))
    assert.ok(path.basename(directory).startsWith('tianyuan-preview-test-'))
    await fs.rm(directory, { recursive: true, force: true })
  })
  await Promise.race([
    once(child.stdout, 'data'),
    once(child, 'exit').then(() => { throw new Error(`preview exited before listening: ${errors}`) }),
    new Promise((_, reject) => setTimeout(() => reject(new Error('preview start timeout')), 5000).unref()),
  ])
  return { port, child }
}

test('malformed request paths return 400 and preserve the server', async (t) => {
  const { port, child } = await fixture(t)
  for (const url of ['/%ZZ', '/%E0%A4%A', '/%00']) {
    const response = await request(port, url)
    assert.equal(response.status, 400)
    assert.equal((await request(port, '/')).status, 200)
    assert.equal(child.exitCode, null)
  }
  assert.equal((await request(port, '/?q=%ZZ')).status, 200)
  assert.equal((await request(port, '/literal%25value')).status, 200)
})

test('encoded traversal cannot serve a same-prefix sibling', async (t) => {
  const { port } = await fixture(t)
  for (const url of ['/%2e%2e/dist-private/secret.txt', '/%2e%2e%5cdist-private%5csecret.txt']) {
    const response = await request(port, url)
    assert.equal(response.status, 403)
    assert.ok(!response.body.includes('outside fixture'))
  }
  assert.equal((await request(port, '/a/client/route')).status, 200)
})

test('missing index is a request failure and does not exit preview', async (t) => {
  const { port, child } = await fixture(t, { index: false })
  assert.equal((await request(port, '/missing')).status, 404)
  assert.equal(child.exitCode, null)
})

test('an asset disappearing after stat cannot crash preview', async (t) => {
  const { port, child } = await fixture(t, { vanish: true })
  assert.equal((await request(port, '/vanish.js')).status, 404)
  assert.equal((await request(port, '/')).status, 200)
  assert.equal(child.exitCode, null)
})

test('normal proxy responses preserve status, headers and body', async (t) => {
  const upstream = http.createServer((_req, response) => {
    response.writeHead(201, { 'Content-Type': 'application/json', 'X-Audit': 'fixture' })
    response.end('{"ok":true}')
  })
  upstream.listen(0, '127.0.0.1')
  await once(upstream, 'listening')
  t.after(() => new Promise((resolve) => upstream.close(resolve)))
  const { port } = await fixture(t, { proxy: `http://127.0.0.1:${upstream.address().port}` })
  const response = await request(port, '/api/check?q=1')
  assert.equal(response.status, 201)
  assert.equal(response.headers['x-audit'], 'fixture')
  assert.equal(response.body, '{"ok":true}')
})
