import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const frontendRoot = path.join(repoRoot, 'frontend')
const manifestPath = path.join(frontendRoot, 'src', 'routeManifest.json')
const distIndexPath = path.join(frontendRoot, 'dist', 'index.html')
const rounds = positiveInt(process.env.CHAOS_FRONTEND_ROUNDS, 4)
const concurrency = positiveInt(process.env.CHAOS_FRONTEND_CONCURRENCY, 12)

await fs.access(distIndexPath)
const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
const routes = collectRoutes(manifest)
const port = await findFreePort(4187)
const baseUrl = `http://127.0.0.1:${port}`
const server = spawn(process.execPath, ['preview-dist.cjs'], {
  cwd: frontendRoot,
  env: { ...process.env, HOST: '127.0.0.1', PORT: String(port) },
  stdio: ['ignore', 'pipe', 'pipe'],
  windowsHide: true,
})

const logs = { stdout: '', stderr: '' }
server.stdout.on('data', (chunk) => {
  logs.stdout += String(chunk)
})
server.stderr.on('data', (chunk) => {
  logs.stderr += String(chunk)
})

try {
  await waitForHtml(`${baseUrl}/`, server)
  const jobs = []
  for (let round = 0; round < rounds; round += 1) {
    for (const route of routes) {
      jobs.push(route)
    }
  }

  let cursor = 0
  const failures = []
  const workers = Array.from({ length: Math.min(concurrency, jobs.length) }, async () => {
    while (cursor < jobs.length) {
      const route = jobs[cursor]
      cursor += 1
      try {
        await assertRoute(`${baseUrl}${route}`, route)
      } catch (error) {
        failures.push(`${route}: ${error instanceof Error ? error.message : String(error)}`)
      }
    }
  })
  await Promise.all(workers)

  if (failures.length) {
    throw new Error(`frontend route pressure failed:\n${failures.slice(0, 20).join('\n')}`)
  }

  console.log(`ok chaos frontend pressure routes=${routes.length} requests=${jobs.length} concurrency=${concurrency}`)
} finally {
  server.kill()
}

function collectRoutes(manifest) {
  const values = new Set()
  for (const group of manifest.navGroups || []) {
    for (const item of group.items || []) {
      values.add(String(item.path || '/'))
    }
  }
  for (const route of manifest.researchRoutes || []) {
    values.add(String(route))
  }
  for (const redirect of manifest.redirects || []) {
    values.add(String(redirect.from || '/'))
  }
  for (const route of manifest.legacyRoutes || []) {
    values.add(String(route || '/'))
  }
  return [...values].sort()
}

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

function findFreePort(startPort) {
  return new Promise((resolve, reject) => {
    let port = startPort
    const tryPort = () => {
      const listener = net.createServer()
      listener.once('error', () => {
        port += 1
        if (port > startPort + 100) {
          reject(new Error(`no free port from ${startPort}`))
          return
        }
        tryPort()
      })
      listener.once('listening', () => {
        listener.close(() => resolve(port))
      })
      listener.listen(port, '127.0.0.1')
    }
    tryPort()
  })
}

async function waitForHtml(url, childProcess) {
  const deadline = Date.now() + 15000
  let lastError = ''
  while (Date.now() < deadline) {
    if (childProcess.exitCode != null) {
      throw new Error(`preview exited with ${childProcess.exitCode}\nstdout:\n${logs.stdout}\nstderr:\n${logs.stderr}`)
    }
    try {
      await assertRoute(url, '/')
      return
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
      await delay(250)
    }
  }
  throw new Error(`preview not ready: ${lastError}\nstdout:\n${logs.stdout}\nstderr:\n${logs.stderr}`)
}

async function assertRoute(url, route) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetch(url, { signal: controller.signal })
    const body = await response.text()
    if (response.status !== 200) {
      throw new Error(`HTTP ${response.status}`)
    }
    if (!body.includes('id="root"')) {
      throw new Error('React root missing')
    }
  } finally {
    clearTimeout(timeout)
  }
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
