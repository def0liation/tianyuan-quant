import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath, pathToFileURL } from 'node:url'

let chromium
try {
  ;({ chromium } = await import('playwright'))
} catch {
  const scriptDir = path.dirname(fileURLToPath(import.meta.url))
  const playwrightUrl = pathToFileURL(path.join(scriptDir, '..', 'frontend', 'node_modules', 'playwright', 'index.mjs')).href
  ;({ chromium } = await import(playwrightUrl))
}

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const frontendRoot = path.join(repoRoot, 'frontend')
const manifestPath = path.join(frontendRoot, 'src', 'routeManifest.json')
const distIndexPath = path.join(frontendRoot, 'dist', 'index.html')

const viewports = [
  { name: 'desktop-1440', width: 1440, height: 1000 },
  { name: 'laptop-1280', width: 1280, height: 900 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'mobile-390', width: 390, height: 844 },
]

await fs.access(distIndexPath)
const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
const routes = limitRoutes(collectRoutes(manifest))
const port = await findFreePort(Number(process.env.FRONTEND_RESPONSIVE_PORT || 4191))
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

const failures = []
let checked = 0

try {
  await waitForHtml(`${baseUrl}/`, server)
  const browser = await launchBrowser()
  try {
    const page = await browser.newPage()
    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      for (const route of routes) {
        const routeFailures = await checkRoute(page, `${baseUrl}${route}`, route, viewport)
        checked += 1
        failures.push(...routeFailures)
      }
    }
  } finally {
    await browser.close()
  }

  if (failures.length) {
    throw new Error(`frontend responsive smoke failed:\n${failures.slice(0, 60).join('\n')}`)
  }

  console.log(`ok frontend responsive viewports=${viewports.map((viewport) => `${viewport.width}x${viewport.height}`).join(',')} routes=${routes.length} checks=${checked}`)
} finally {
  server.kill()
}

function collectRoutes(currentManifest) {
  const values = new Set()
  for (const group of currentManifest.navGroups || []) {
    for (const item of group.items || []) {
      values.add(String(item.path || '/'))
    }
  }
  for (const route of currentManifest.researchRoutes || []) {
    values.add(String(route || '/'))
  }
  for (const redirect of currentManifest.redirects || []) {
    values.add(String(redirect.from || '/'))
  }
  for (const route of currentManifest.legacyRoutes || []) {
    values.add(String(route || '/'))
  }
  return [...values].sort()
}

function limitRoutes(allRoutes) {
  const routeFilter = String(process.env.FRONTEND_RESPONSIVE_ROUTES || '').trim()
  if (routeFilter) {
    const wanted = new Set(routeFilter.split(',').map((route) => route.trim()).filter(Boolean))
    return allRoutes.filter((route) => wanted.has(route))
  }
  const limit = Number.parseInt(String(process.env.FRONTEND_RESPONSIVE_ROUTE_LIMIT || ''), 10)
  if (Number.isFinite(limit) && limit > 0) {
    return allRoutes.slice(0, limit)
  }
  return allRoutes
}

async function checkRoute(page, url, route, viewport) {
  const routeFailures = []
  const pageErrors = []
  const consoleErrors = []

  const onPageError = (error) => {
    pageErrors.push(error.message || String(error))
  }
  const onConsole = (message) => {
    if (message.type() === 'error') {
      const text = message.text()
      if (!isIgnoredConsoleError(text)) {
        consoleErrors.push(text)
      }
    }
  }

  page.on('pageerror', onPageError)
  page.on('console', onConsole)

  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 })
    await page.locator('#root').waitFor({ state: 'attached', timeout: 10000 })
    await page.waitForTimeout(500)

    const layoutFailures = await page.evaluate(({ width }) => {
      const failures = []
      const doc = document.documentElement
      const body = document.body
      const root = document.querySelector('#root')
      const rootText = root?.textContent?.replace(/\s+/g, ' ').trim() || ''
      const documentWidth = Math.max(doc.scrollWidth, body.scrollWidth)
      const viewportWidth = Math.max(doc.clientWidth, window.innerWidth)
      const overflow = documentWidth - viewportWidth

      if (!root || rootText.length < 24) {
        failures.push('React root is blank or near blank')
      }
      if (overflow > 4) {
        failures.push(`unexpected document horizontal overflow ${overflow}px (scrollWidth=${documentWidth}, viewport=${viewportWidth}); offenders=${findOverflowOffenders(width).join(' | ') || 'none'}`)
      }

      for (const selector of ['.institution-command-bar', '.institution-secondary-nav']) {
        const element = document.querySelector(selector)
        if (!isVisible(element)) {
          failures.push(`${selector} is missing or hidden`)
          continue
        }
        const rect = element.getBoundingClientRect()
        if (rect.left < -4 || rect.right > width + 4) {
          failures.push(`${selector} extends outside viewport (${Math.round(rect.left)}..${Math.round(rect.right)} of ${width})`)
        }
      }

      for (const table of Array.from(document.querySelectorAll('table.institution-table'))) {
        if (!table.closest('.material-table-shell')) {
          failures.push('institution-table is not wrapped by material-table-shell')
          break
        }
      }

      for (const element of Array.from(document.querySelectorAll('button, .material-button, .institution-nav-pill, .institution-chip, .material-status-pill'))) {
        if (!isVisible(element)) continue
        const rect = element.getBoundingClientRect()
        if (rect.width < 16 || rect.height < 16) {
          failures.push(`visible control is too small: ${describeElement(element)}`)
          break
        }
        if (element.scrollWidth > element.clientWidth + 3 && !hasScrollableAncestor(element)) {
          failures.push(`control text overflows without scroll container: ${describeElement(element)}`)
          break
        }
      }

      const overlayText = rootText.toLowerCase()
      if (overlayText.includes('vite') && overlayText.includes('error') && overlayText.includes('stack')) {
        failures.push('framework error overlay is visible')
      }

      return failures

      function isVisible(element) {
        if (!element) return false
        const rect = element.getBoundingClientRect()
        const style = window.getComputedStyle(element)
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'
      }

      function hasScrollableAncestor(element) {
        let current = element.parentElement
        while (current && current !== document.body) {
          const style = window.getComputedStyle(current)
          if (/(auto|scroll)/.test(`${style.overflowX} ${style.overflow}`)) return true
          current = current.parentElement
        }
        return false
      }

      function describeElement(element) {
        const label = element.getAttribute('aria-label') || element.getAttribute('title') || element.textContent?.trim() || element.tagName.toLowerCase()
        return label.replace(/\s+/g, ' ').slice(0, 80)
      }

      function findOverflowOffenders(width) {
        return Array.from(document.querySelectorAll('body *'))
          .filter((element) => isVisible(element) && !hasScrollableAncestor(element))
          .map((element) => {
            const rect = element.getBoundingClientRect()
            const overflowRight = Math.max(0, rect.right - width)
            const overflowLeft = Math.max(0, -rect.left)
            return { element, overflow: Math.max(overflowRight, overflowLeft), rect }
          })
          .filter((item) => item.overflow > 4)
          .sort((a, b) => b.overflow - a.overflow)
          .slice(0, 4)
          .map((item) => `${describeElement(item.element)} @${Math.round(item.rect.left)}..${Math.round(item.rect.right)}`)
      }
    }, { width: viewport.width })

    routeFailures.push(...layoutFailures)
    routeFailures.push(...pageErrors.map((error) => `pageerror: ${error}`))
    routeFailures.push(...consoleErrors.slice(0, 3).map((error) => `console error: ${error}`))
  } catch (error) {
    routeFailures.push(error instanceof Error ? error.message : String(error))
  } finally {
    page.off('pageerror', onPageError)
    page.off('console', onConsole)
  }

  return routeFailures.map((failure) => `${viewport.width}x${viewport.height} ${route}: ${failure}`)
}

function isIgnoredConsoleError(text) {
  return [
    'Failed to load resource',
    'ERR_CONNECTION_REFUSED',
    'API proxy error',
    'NetworkError',
  ].some((marker) => text.includes(marker))
}

async function launchBrowser() {
  const candidates = [
    { channel: 'chrome', headless: true },
    { channel: 'msedge', headless: true },
    { headless: true },
  ]
  let lastError
  for (const candidate of candidates) {
    try {
      return await chromium.launch(candidate)
    } catch (error) {
      lastError = error
    }
  }
  throw lastError
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
      const response = await fetch(url)
      const body = await response.text()
      if (response.status === 200 && body.includes('id="root"')) return
      lastError = `HTTP ${response.status}`
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error)
    }
    await delay(250)
  }
  throw new Error(`preview not ready: ${lastError}\nstdout:\n${logs.stdout}\nstderr:\n${logs.stderr}`)
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
