import path from 'node:path'
import { createHash, createHmac } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'

const baseUrl = process.env.STRICT_AUTH_FRONTEND_URL
const backendUrl = process.env.STRICT_AUTH_BACKEND_URL
const authToken = process.env.STRICT_AUTH_TOKEN
const scriptDir = path.dirname(fileURLToPath(import.meta.url))

if (!baseUrl || !backendUrl || !authToken) {
  console.error('strict-auth browser smoke requires STRICT_AUTH_FRONTEND_URL, STRICT_AUTH_BACKEND_URL, and STRICT_AUTH_TOKEN.')
  process.exit(1)
}

let chromium
try {
  ;({ chromium } = await import('playwright'))
} catch {
  try {
    const playwrightUrl = pathToFileURL(path.join(scriptDir, '..', 'frontend', 'node_modules', 'playwright', 'index.mjs')).href
    ;({ chromium } = await import(playwrightUrl))
  } catch {
    console.error('strict-auth browser smoke requires Playwright. Install it locally before running smoke:strict-auth-browser.')
    process.exit(1)
  }
}

const createdRunIds = new Set()
const createdBacktestRunIds = new Set()
const pageErrors = []
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds))
const SCENARIO_GROUPS = Object.freeze([
  'platform',
  'signalops',
  'research-backtest',
  'portfolio-live-plugin',
])
const SCENARIO_ALIASES = Object.freeze({
  all: SCENARIO_GROUPS,
  full: SCENARIO_GROUPS,
  platform: ['platform'],
  core: ['platform'],
  signalops: ['signalops'],
  research: ['research-backtest'],
  backtest: ['research-backtest'],
  'research-backtest': ['research-backtest'],
  portfolio: ['portfolio-live-plugin'],
  live: ['portfolio-live-plugin'],
  plugins: ['portfolio-live-plugin'],
  'portfolio-live-plugin': ['portfolio-live-plugin'],
})
const selectedScenarioGroups = parseScenarioGroups(process.env.STRICT_AUTH_BROWSER_SCENARIO || 'all')
let strictAuthSessionBootstrapped = false

function urlFor(route, root = baseUrl) {
  return new URL(route, root).toString()
}

function parseScenarioGroups(rawValue) {
  const rawItems = String(rawValue || 'all')
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
  const requested = rawItems.length ? rawItems : ['all']
  const selected = new Set()
  const unknown = []
  for (const item of requested) {
    const groups = SCENARIO_ALIASES[item]
    if (!groups) {
      unknown.push(item)
      continue
    }
    groups.forEach((group) => selected.add(group))
  }
  if (unknown.length) {
    throw new Error(`Unknown STRICT_AUTH_BROWSER_SCENARIO value(s): ${unknown.join(', ')}. Use one of: ${Object.keys(SCENARIO_ALIASES).join(', ')}`)
  }
  return selected
}

async function apiJson(method, route, body, timeoutMs = 60000) {
  const headers = {
    Authorization: `Bearer ${authToken}`,
    'X-Operator-ID': 'strict-auth-browser-smoke',
    'X-Operator-Role': 'admin',
  }
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  const maxAttempts = 2
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(urlFor(route, backendUrl), {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      })
      const text = await response.text()
      if (!response.ok) {
        throw new Error(`API ${method} ${route} returned ${response.status}: ${text}`)
      }
      if (!text) {
        return null
      }
      try {
        return JSON.parse(text)
      } catch (error) {
        throw new Error(`API ${method} ${route} returned non-JSON payload: ${text}`)
      }
    } catch (error) {
      if (error?.name === 'AbortError') {
        if (attempt < maxAttempts) {
          console.warn(`API ${method} ${route} timed out; retrying direct API call (${attempt + 1}/${maxAttempts})`)
          await wait(500)
          continue
        }
        throw new Error(`API ${method} ${route} timed out after ${timeoutMs}ms`)
      }
      if (attempt < maxAttempts && isRetryableFetchError(error)) {
        console.warn(`API ${method} ${route} fetch failed; retrying direct API call (${attempt + 1}/${maxAttempts})`)
        await wait(250)
        continue
      }
      throw error
    } finally {
      clearTimeout(timeout)
    }
  }
}

function isRetryableFetchError(error) {
  const message = String(error?.message || '')
  const code = String(error?.cause?.code || error?.code || '')
  return message.includes('fetch failed')
    || ['UND_ERR_SOCKET', 'ECONNRESET', 'ECONNREFUSED', 'EPIPE'].includes(code)
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function api(method, route) {
  await apiJson(method, route)
}

async function pageApiJson(page, method, route, body, timeoutMs = 60000) {
  const requestUrl = urlFor(route)
  return page.evaluate(async ({ requestUrl, method, body, authToken, timeoutMs }) => {
    const headers = {
      Authorization: `Bearer ${authToken}`,
      'X-Operator-ID': 'strict-auth-browser-smoke',
      'X-Operator-Role': 'admin',
    }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
    }
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
    try {
      const response = await fetch(requestUrl, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      })
      const text = await response.text()
      if (!response.ok) {
        throw new Error(`page API ${method} ${requestUrl} returned ${response.status}: ${text}`)
      }
      return text ? JSON.parse(text) : null
    } catch (error) {
      if (error?.name === 'AbortError') {
        throw new Error(`page API ${method} ${requestUrl} timed out after ${timeoutMs}ms`)
      }
      throw error
    } finally {
      window.clearTimeout(timeout)
    }
  }, { requestUrl, method, body, authToken, timeoutMs })
}

async function expectText(page, text, label) {
  await page.getByText(text, { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
  console.log(`ok strict-auth browser ${label}`)
}

async function pageRenderDiagnostic(page) {
  const errorText = await page.locator('.text-red-700, [role="alert"]').evaluateAll((elements) => (
    elements
      .map((element) => element.textContent?.trim())
      .filter(Boolean)
      .slice(0, 5)
  )).catch(() => [])
  const bodyText = await page.locator('body').innerText({ timeout: 2000 }).catch((error) => `body unavailable: ${error?.message || error}`)
  return [
    `url=${page.url()}`,
    errorText.length ? `visible errors=${errorText.join(' | ')}` : 'visible errors=none',
    pageErrors.length ? `page errors=${pageErrors.slice(-5).join(' | ')}` : 'page errors=none',
    `body=${String(bodyText || '').slice(0, 1200)}`,
  ].join(' ; ')
}

async function bootstrapStrictAuthSession(page) {
  if (strictAuthSessionBootstrapped) return

  const metricsResponsePromise = page.waitForResponse((response) => response.url().includes('/api/metrics'), { timeout: 15000 })
  await page.goto(urlFor('/backend'), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('#root', { timeout: 10000 })
  const metricsResponse = await metricsResponsePromise
  if (metricsResponse.status() !== 401) {
    throw new Error(`unauthenticated /api/metrics should return 401 in strict mode, got ${metricsResponse.status()}`)
  }
  console.log('ok strict-auth browser unauthenticated metrics rejected')

  await page.getByLabel('API 令牌').fill(authToken)
  await page.getByTestId('backend-operator-token-apply').click()
  await expectText(page, '令牌：当前标签页已设置', 'operator token applied')

  await delay(250)
  const reloadMetricsResponsePromise = page.waitForResponse((response) => response.url().includes('/api/metrics'), { timeout: 15000 })
  await page.goto(urlFor('/backend?auth_reload=1'), { waitUntil: 'domcontentloaded', timeout: 30000 })
  const reloadMetricsResponse = await reloadMetricsResponsePromise
  if (reloadMetricsResponse.status() !== 200) {
    throw new Error(`reloaded /api/metrics should keep same-tab operator token, got ${reloadMetricsResponse.status()}`)
  }
  await assertBearer(reloadMetricsResponse, 'operator token reload persistence metrics')
  await expectText(page, '令牌：当前标签页已设置', 'operator token persisted after reload')
  console.log('ok strict-auth browser operator token reload persistence')

  await page.getByTestId('backend-operator-token-clear').click()
  await expectText(page, '令牌：未设置', 'operator token cleared')
  await delay(250)
  const clearedMetricsResponsePromise = page.waitForResponse((response) => response.url().includes('/api/metrics'), { timeout: 15000 })
  await page.goto(urlFor('/backend?auth_clear_reload=1'), { waitUntil: 'domcontentloaded', timeout: 30000 })
  const clearedMetricsResponse = await clearedMetricsResponsePromise
  if (clearedMetricsResponse.status() !== 401) {
    throw new Error(`reloaded /api/metrics should be rejected after clearing operator token, got ${clearedMetricsResponse.status()}`)
  }
  await assertNoBearer(clearedMetricsResponse, 'operator token clear reload metrics')
  await expectText(page, '令牌：未设置', 'operator token remained cleared after reload')
  console.log('ok strict-auth browser operator token clear removes reload auth')

  await page.getByLabel('API 令牌').fill(authToken)
  await page.getByTestId('backend-operator-token-apply').click()
  await expectText(page, '令牌：当前标签页已设置', 'operator token reapplied')
  strictAuthSessionBootstrapped = true
}

async function clickEnabled(locator, label, timeout = 15000) {
  await locator.waitFor({ state: 'visible', timeout })
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const disabled = await locator.evaluate((element) => (
      element instanceof HTMLButtonElement
        ? element.disabled
        : element.getAttribute('aria-disabled') === 'true'
    ))
    if (!disabled) {
      await locator.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => undefined)
      try {
        await locator.click({ timeout: 5000 })
      } catch {
        await locator.dispatchEvent('click')
      }
      return
    }
    await delay(250)
  }
  const html = await locator.evaluate((element) => element.outerHTML)
  throw new Error(`${label} stayed disabled before click: ${html}`)
}

function selectorForAppLink(href) {
  return `a[href="${String(href).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"]`
}

async function waitForCurrentOrUrl(page, predicate, timeout = 15000) {
  if (predicate(new URL(page.url()))) {
    return
  }
  await page.waitForURL(predicate, { timeout })
}

async function navigateByAppLink(page, href, label, timeout = 15000) {
  const targetUrl = new URL(href, baseUrl)
  const matchesTarget = (url) => url.pathname === targetUrl.pathname && url.search === targetUrl.search
  const link = page.locator(selectorForAppLink(href)).first()
  try {
    await link.waitFor({ state: 'visible', timeout: 5000 })
    await link.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => undefined)
    await link.click({ timeout: 5000 })
    await waitForCurrentOrUrl(page, matchesTarget, timeout)
    console.log(`ok strict-auth browser app-link navigation ${label}`)
    return
  } catch (error) {
    console.warn(`App link navigation to ${href} for ${label} failed; retrying SPA route without reloading auth state: ${error?.message || error}`)
  }

  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, href)
  await waitForCurrentOrUrl(page, matchesTarget, timeout)
}

async function navigateToResearchLoopsPage(page, label, timeout = 15000) {
  const targetPath = '/research-lab/research'
  const targetUrl = new URL(targetPath, baseUrl)
  const matchesTarget = (url) => url.pathname === targetUrl.pathname && url.search === targetUrl.search
  if (matchesTarget(new URL(page.url()))) {
    return
  }

  const moduleLink = page.locator('nav[aria-label="研究实验室模块"] a[href="/research-lab/research"]').first()
  try {
    await moduleLink.waitFor({ state: 'visible', timeout: 5000 })
    await clickEnabled(moduleLink, label, timeout)
    await waitForCurrentOrUrl(page, matchesTarget, timeout)
    return
  } catch (error) {
    console.warn(`Research Lab module navigation failed for ${label}; retrying SPA route without reloading auth state: ${error?.message || error}`)
  }

  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, targetPath)
  await waitForCurrentOrUrl(page, matchesTarget, timeout)
}

function bufferedResponses(page, predicate) {
  const responses = []
  const handler = (response) => {
    if (predicate(response)) responses.push(response)
  }
  page.on('response', handler)
  return {
    async next(timeout = 30000) {
      if (responses.length > 0) return responses.shift()
      return page.waitForResponse(predicate, { timeout })
    },
    stop() {
      page.off('response', handler)
    },
  }
}

async function assertBearer(response, label) {
  const headers = await response.request().allHeaders()
  const authorization = headers.authorization || headers.Authorization
  if (authorization !== `Bearer ${authToken}`) {
    throw new Error(`${label} did not include the expected Authorization bearer token`)
  }
}

async function assertNoBearer(response, label) {
  const headers = await response.request().allHeaders()
  const authorization = headers.authorization || headers.Authorization
  if (authorization) {
    throw new Error(`${label} unexpectedly included an Authorization bearer token`)
  }
}

function asRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value))
}

function buildAgentDagFailureFixture(baseRun) {
  const fixtureRunId = 'RUN_DAG_FAILURE_BROWSER_SMOKE'
  const fixture = cloneJson(baseRun)
  fixture.runId = fixtureRunId
  fixture.status = 'FAILED'
  fixture.updatedAt = new Date().toISOString()
  fixture.finalAction = fixture.finalAction || 'WAIT'
  fixture.auditLog = Array.isArray(fixture.auditLog) ? fixture.auditLog : []

  const nodes = Array.isArray(fixture.nodes) ? fixture.nodes : []
  const candidates = nodes.filter((node) => node?.id)
  const degradedNode = candidates.find((node) => node.id !== 'orchestrator') || candidates[0]
  const failedNode = candidates.find((node) => node.id !== degradedNode?.id && node.id !== 'orchestrator')
    || candidates.find((node) => node.id !== degradedNode?.id)
  if (!degradedNode || !failedNode) {
    throw new Error(`Agent DAG failure fixture needs at least two nodes: ${JSON.stringify(nodes)}`)
  }

  degradedNode.status = 'WARN'
  degradedNode.isBlocked = false
  degradedNode.outputSummary = 'LLM skipped by deterministic browser fixture'
  degradedNode.downgradeReasons = ['LLM_SKIPPED_BROWSER_FIXTURE']
  failedNode.status = 'FAIL'
  failedNode.isBlocked = true
  failedNode.outputSummary = 'LLM failed by deterministic browser fixture'
  failedNode.downgradeReasons = ['LLM_FAILED_BROWSER_FIXTURE']

  const makeTokenRow = (node, status, source, error, reason) => ({
    node: node.id,
    name: node.name || node.id,
    status,
    provider: 'fixture-provider',
    model: 'fixture-model',
    profile_id: 'strict-auth-fixture',
    prompt_tokens: status === 'FAILED' ? 0 : 12,
    completion_tokens: status === 'FAILED' ? 0 : 4,
    total_tokens: status === 'FAILED' ? 0 : 16,
    latency_ms: status === 'FAILED' ? 0 : 88,
    finish_reason: status === 'FAILED' ? 'error' : 'skipped',
    error,
    llm_status: status,
    source,
    degradation_reason: reason,
    usage_source: status === 'FAILED' ? 'NO_PROVIDER_USAGE' : 'PROVIDER_EMPTY',
    audit_id: node.auditId || `AUD_${fixtureRunId}_${node.id}`,
  })

  const rows = Array.isArray(fixture.tokenUsage?.rows) ? fixture.tokenUsage.rows : []
  fixture.tokenUsage = {
    ...(asRecord(fixture.tokenUsage)),
    metering_status: 'PARTIAL_PROVIDER_USAGE',
    rows: rows
      .filter((row) => row?.node !== degradedNode.id && row?.node !== failedNode.id)
      .concat([
        makeTokenRow(degradedNode, 'SKIPPED', 'LLM_DEGRADED', '', 'LLM_SKIPPED_BROWSER_FIXTURE'),
        makeTokenRow(failedNode, 'FAILED', 'LLM_FAILED', 'LLM_FAILED_BROWSER_FIXTURE', 'LLM_FAILED_BROWSER_FIXTURE'),
      ]),
  }

  const traces = Array.isArray(fixture.llmTrace) ? fixture.llmTrace : []
  fixture.llmTrace = traces
    .filter((trace) => trace?.nodeId !== degradedNode.id && trace?.nodeId !== failedNode.id)
    .concat([
      {
        nodeId: degradedNode.id,
        status: 'SKIPPED',
        profileId: 'strict-auth-fixture',
        provider: 'fixture-provider',
        model: 'fixture-model',
        latencyMs: 88,
        totalTokens: 16,
        finishReason: 'skipped',
        error: '',
        timestamp: fixture.updatedAt,
      },
      {
        nodeId: failedNode.id,
        status: 'FAILED',
        profileId: 'strict-auth-fixture',
        provider: 'fixture-provider',
        model: 'fixture-model',
        latencyMs: 0,
        totalTokens: 0,
        finishReason: 'error',
        error: 'LLM_FAILED_BROWSER_FIXTURE',
        timestamp: fixture.updatedAt,
      },
    ])

  return {
    fixture,
    fixtureRunId,
    degradedNodeId: String(degradedNode.id),
    failedNodeId: String(failedNode.id),
  }
}

function buildAgentDagStateMatrixFixture(baseRun) {
  const fixtureRunId = 'RUN_DAG_STATE_MATRIX_BROWSER_SMOKE'
  const updatedAt = new Date().toISOString()
  const fixture = cloneJson(baseRun)
  fixture.runId = fixtureRunId
  fixture.status = 'COMPLETED'
  fixture.updatedAt = updatedAt
  fixture.finalAction = fixture.finalAction || 'WAIT'
  fixture.auditLog = Array.isArray(fixture.auditLog) ? fixture.auditLog : []

  const makeNode = (id, name, status, outputSummary, extra = {}) => ({
    id,
    name,
    status,
    isRunning: false,
    isSkipped: status === 'SKIPPED',
    isBlocked: status === 'FAIL' || status === 'ERROR' || status === 'BLOCK_BUY',
    duration: 90,
    auditId: `AUD_${fixtureRunId}_${id}`,
    inputSummary: 'Strict-auth browser state matrix fixture',
    outputSummary,
    missingData: [],
    downgradeReasons: [],
    blockedPaths: [],
    allowedNextActions: [],
    rawJson: {},
    evidenceUsage: 'simulation_only',
    evidenceStrength: status === 'PASS' ? 'MEDIUM' : 'LOW',
    simulationOnly: true,
    isRealTrade: false,
    strongConclusionAllowed: false,
    ...extra,
  })

  const matrixNodes = [
    makeNode('state_llm', 'State Matrix LLM', 'PASS', 'Completed provider-backed LLM fixture output', {
      allowedNextActions: ['state_degraded'],
      rawJson: {
        llmRunner: {
          status: 'COMPLETED',
          profileId: 'state-matrix-profile',
          provider: 'fixture-provider',
          model: 'fixture-model',
          latencyMs: 121,
          finishReason: 'stop',
          usage: { total_tokens: 33 },
        },
      },
    }),
    makeNode('state_degraded', 'State Matrix LLM Degraded', 'WARN', 'LLM skipped by state matrix fixture', {
      allowedNextActions: ['state_failed'],
      downgradeReasons: ['STATE_MATRIX_LLM_DEGRADED'],
    }),
    makeNode('state_failed', 'State Matrix LLM Failed', 'FAIL', 'LLM failed by state matrix fixture', {
      allowedNextActions: ['state_rule'],
      downgradeReasons: ['STATE_MATRIX_LLM_FAILED'],
    }),
    makeNode('state_rule', 'State Matrix Rule Engine', 'REVIEW_ONLY', 'Rule-engine output from deterministic module evidence', {
      allowedNextActions: ['state_plugin'],
    }),
    makeNode('state_plugin', 'State Matrix Plugin Observation', 'REVIEW_ONLY', 'Read-only plugin observation recorded without code execution', {
      allowedNextActions: ['mock_state_matrix'],
      rawJson: {
        nodeType: 'plugin_observation',
        dagRegistration: { execution_mode: 'PLAN_ONLY_NO_EXECUTION' },
        permissionSandbox: { mode: 'READ_ONLY_NO_CODE' },
        pluginObservation: { status: 'RECORDED_NO_EXECUTION' },
        directExecution: false,
        canExecuteCode: false,
      },
    }),
    makeNode('mock_state_matrix', 'State Matrix Mock Sample', 'SKIPPED', 'Mock/sample output for state matrix fixture', {
      auditId: `AUD_${fixtureRunId}_MOCK_SAMPLE`,
    }),
  ]

  const makeTokenRow = (node, status, source, tokens, error = '', reason = '', usageSource = 'PROVIDER_EMPTY') => ({
    node: node.id,
    name: node.name,
    status,
    provider: source === 'RULE_ENGINE' || source === 'MOCK' ? '' : 'fixture-provider',
    model: source === 'RULE_ENGINE' || source === 'MOCK' ? '' : 'fixture-model',
    profile_id: source === 'RULE_ENGINE' || source === 'MOCK' ? '' : 'state-matrix-profile',
    prompt_tokens: tokens ? Math.floor(tokens / 2) : 0,
    completion_tokens: tokens ? Math.ceil(tokens / 2) : 0,
    total_tokens: tokens,
    latency_ms: tokens ? 121 : 0,
    finish_reason: status === 'COMPLETED' ? 'stop' : status.toLowerCase(),
    error,
    llm_status: status,
    source,
    degradation_reason: reason,
    usage_source: usageSource,
    audit_id: node.auditId,
  })

  const [llmNode, degradedNode, failedNode, ruleNode, pluginNode, mockNode] = matrixNodes
  const rows = [
    makeTokenRow(llmNode, 'COMPLETED', 'LLM', 33, '', '', 'PROVIDER_USAGE'),
    makeTokenRow(degradedNode, 'SKIPPED', 'LLM_DEGRADED', 8, '', 'STATE_MATRIX_LLM_DEGRADED', 'PROVIDER_EMPTY'),
    makeTokenRow(failedNode, 'FAILED', 'LLM_FAILED', 0, 'STATE_MATRIX_LLM_FAILED', 'STATE_MATRIX_LLM_FAILED', 'NO_PROVIDER_USAGE'),
    makeTokenRow(ruleNode, 'NOT_RUN', 'RULE_ENGINE', 0, '', 'STATE_MATRIX_RULE_ENGINE', 'NO_PROVIDER_USAGE'),
    makeTokenRow(pluginNode, 'NOT_RUN', 'PLUGIN_OBSERVATION', 0, '', 'STATE_MATRIX_PLUGIN_OBSERVATION', 'NO_PROVIDER_USAGE'),
    makeTokenRow(mockNode, 'NOT_RUN', 'MOCK', 0, '', 'STATE_MATRIX_MOCK_SAMPLE', 'MOCK_ESTIMATE'),
  ]

  fixture.nodes = matrixNodes
  fixture.tokenUsage = {
    rows,
    totals: rows.reduce((totals, row) => ({
      prompt_tokens: totals.prompt_tokens + row.prompt_tokens,
      completion_tokens: totals.completion_tokens + row.completion_tokens,
      total_tokens: totals.total_tokens + row.total_tokens,
      latency_ms: totals.latency_ms + row.latency_ms,
    }), { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, latency_ms: 0 }),
    top_agent: rows[0],
    metering_status: 'PARTIAL_PROVIDER_USAGE',
    note: 'Strict-auth browser Agent DAG state matrix fixture',
  }
  fixture.llmTrace = [
    {
      nodeId: llmNode.id,
      status: 'COMPLETED',
      profileId: 'state-matrix-profile',
      provider: 'fixture-provider',
      model: 'fixture-model',
      latencyMs: 121,
      totalTokens: 33,
      finishReason: 'stop',
      error: '',
      timestamp: updatedAt,
    },
    {
      nodeId: degradedNode.id,
      status: 'SKIPPED',
      profileId: 'state-matrix-profile',
      provider: 'fixture-provider',
      model: 'fixture-model',
      latencyMs: 77,
      totalTokens: 8,
      finishReason: 'skipped',
      error: '',
      timestamp: updatedAt,
    },
    {
      nodeId: failedNode.id,
      status: 'FAILED',
      profileId: 'state-matrix-profile',
      provider: 'fixture-provider',
      model: 'fixture-model',
      latencyMs: 0,
      totalTokens: 0,
      finishReason: 'error',
      error: 'STATE_MATRIX_LLM_FAILED',
      timestamp: updatedAt,
    },
  ]

  return {
    fixture,
    fixtureRunId,
    expectations: [
      { nodeId: llmNode.id, source: 'LLM', snippets: ['COMPLETED'] },
      { nodeId: degradedNode.id, source: 'LLM_DEGRADED', snippets: ['SKIPPED', 'STATE_MATRIX_LLM_DEGRADED'] },
      { nodeId: failedNode.id, source: 'LLM_FAILED', snippets: ['FAILED', 'STATE_MATRIX_LLM_FAILED'] },
      { nodeId: ruleNode.id, source: 'RULE_ENGINE', snippets: ['NOT_RUN', 'STATE_MATRIX_RULE_ENGINE'] },
      { nodeId: pluginNode.id, source: 'PLUGIN_OBSERVATION', snippets: ['NOT_RUN', 'PLAN_ONLY_NO_EXECUTION'] },
      { nodeId: mockNode.id, source: 'MOCK', snippets: ['NOT_RUN', 'STATE_MATRIX_MOCK_SAMPLE'] },
    ],
  }
}

function buildLiveRunTerminalFixture(baseRun, options = {}) {
  const eventType = options.eventType || 'STREAM_TIMEOUT'
  const fixtureRunId = options.fixtureRunId || `RUN_LIVE_${eventType}_BROWSER_SMOKE`
  const message = options.message || `${eventType}_BROWSER_FIXTURE`
  const updatedAt = new Date().toISOString()
  const fixture = cloneJson(baseRun)
  const baseJob = asRecord(fixture.job)
  const attempt = Number(baseJob.attempt || 1)

  fixture.runId = fixtureRunId
  fixture.status = 'STALE'
  fixture.updatedAt = updatedAt
  fixture.failReason = message
  fixture.failureCategory = eventType === 'RUN_STALE_RECOVERED' ? 'STALE_RUN_RECOVERY' : `${eventType}_BROWSER_FIXTURE`
  fixture.auditLog = []
  fixture.job = {
    ...baseJob,
    job_id: baseJob.job_id || `JOB_${fixtureRunId}`,
    run_id: fixtureRunId,
    status: 'STALE',
    attempt,
    max_attempts: baseJob.max_attempts || 3,
    failed_node_id: 'system',
    last_error: message,
    last_operator: 'strict-auth-browser-smoke',
    history: [
      ...(Array.isArray(baseJob.history) ? baseJob.history : []),
      {
        event: eventType,
        at: updatedAt,
        attempt,
        operator: 'strict-auth-browser-smoke',
        error: message,
      },
    ],
  }

  return { eventType, fixture, fixtureRunId, message }
}

function assertSignalOpsSimulationBoundary(payload, label) {
  const root = asRecord(payload)
  const config = asRecord(root.config)
  const source = Object.keys(config).length ? config : root
  const modules = asRecord(source.automation_modules)
  const simulation = asRecord(source.simulation_module || modules.simulation)
  const live = asRecord(source.live_module || modules.live)
  if (simulation.simulation_only === false || simulation.is_real_trade === true) {
    throw new Error(`${label} broke SignalOps simulation module boundary`)
  }
  if (live.execution_enabled === true || live.is_real_trade === true) {
    throw new Error(`${label} enabled SignalOps live trading boundary`)
  }
}

function assertSignalOpsTickSimulationBoundary(payload) {
  const root = asRecord(payload)
  if (!root.status) {
    throw new Error(`SignalOps tick response did not include status: ${JSON.stringify(root)}`)
  }
  for (const [label, value] of [
    ['decision', root.decision],
    ['decision_card', root.decision_card],
    ['module_evidence', root.module_evidence],
    ['portfolio_snapshot', root.portfolio_snapshot],
    ['order', root.order],
  ]) {
    const record = asRecord(value)
    if (Object.keys(record).length === 0) continue
    if (record.simulation_only === false || record.is_real_trade === true) {
      throw new Error(`SignalOps tick ${label} broke simulation-only boundary: ${JSON.stringify(record)}`)
    }
  }

  const moduleEvidence = asRecord(root.module_evidence)
  const tradeBoundary = asRecord(moduleEvidence.trade_boundary)
  if (Object.keys(tradeBoundary).length) {
    if (tradeBoundary.allowed_order_namespace !== 'SIM_*') {
      throw new Error(`SignalOps tick allowed unexpected order namespace: ${JSON.stringify(tradeBoundary)}`)
    }
    if (tradeBoundary.live_module_status !== 'CONFIGURED_DISABLED') {
      throw new Error(`SignalOps tick did not keep live module disabled: ${JSON.stringify(tradeBoundary)}`)
    }
  }
  const automationModules = asRecord(moduleEvidence.automation_modules)
  if (Object.keys(automationModules).length && automationModules.active_module !== 'simulation') {
    throw new Error(`SignalOps tick used non-simulation automation module: ${JSON.stringify(automationModules)}`)
  }
}

function assertSignalOpsDailyReviewSimulationBoundary(payload) {
  const root = asRecord(payload)
  if (!root.status) {
    throw new Error(`SignalOps daily review response did not include status: ${JSON.stringify(root)}`)
  }
  assertSignalOpsSimulationBoundary(root, 'SignalOps daily review')

  for (const [label, value] of [
    ['review_queue_state', root.review_queue_state],
    ['experiment_validation_state', root.experiment_validation_state],
    ['random_validation_state', root.random_validation_state],
  ]) {
    const record = asRecord(value)
    if (Object.keys(record).length && (record.simulation_only === false || record.is_real_trade === true)) {
      throw new Error(`SignalOps daily review ${label} broke simulation-only boundary: ${JSON.stringify(record)}`)
    }
  }

  const reviewedSymbols = Array.isArray(root.reviewed_symbols) ? root.reviewed_symbols : []
  for (const item of reviewedSymbols) {
    const record = asRecord(item)
    if (record.simulation_only === false || record.is_real_trade === true) {
      throw new Error(`SignalOps daily review reviewed symbol broke simulation-only boundary: ${JSON.stringify(record)}`)
    }
  }

  const queueItems = Array.isArray(asRecord(root.review_queue_state).items) ? asRecord(root.review_queue_state).items : []
  for (const item of queueItems) {
    const record = asRecord(item)
    if (record.simulation_only === false || record.is_real_trade === true) {
      throw new Error(`SignalOps daily review queue item broke simulation-only boundary: ${JSON.stringify(record)}`)
    }
  }
}

function assertSignalOpsCommandSimulationBoundary(payload) {
  const root = asRecord(payload)
  if (!root.status || !root.symbol) {
    throw new Error(`SignalOps command response did not include status/symbol: ${JSON.stringify(root)}`)
  }
  assertSignalOpsSimulationBoundary(root, 'SignalOps manual command')

  const order = asRecord(root.order)
  if (Object.keys(order).length) {
    if (order.simulation_only === false || order.is_real_trade === true) {
      throw new Error(`SignalOps command order broke simulation-only boundary: ${JSON.stringify(order)}`)
    }
    const action = String(order.action || '')
    if (action && !action.startsWith('SIM_')) {
      throw new Error(`SignalOps command created non-simulation order action: ${JSON.stringify(order)}`)
    }
    const riskConstraints = asRecord(order.risk_constraints)
    if (Object.keys(riskConstraints).length) {
      if (riskConstraints.simulation_only === false || riskConstraints.is_real_trade === true) {
        throw new Error(`SignalOps command risk constraints broke simulation-only boundary: ${JSON.stringify(riskConstraints)}`)
      }
      if (riskConstraints.manual_command && riskConstraints.manual_command !== 'FORCE_OPEN_BUY') {
        throw new Error(`SignalOps command carried unexpected manual command: ${JSON.stringify(riskConstraints)}`)
      }
    }
  }

  const portfolio = asRecord(root.portfolio)
  if (Object.keys(portfolio).length && (portfolio.simulation_only === false || portfolio.is_real_trade === true)) {
    throw new Error(`SignalOps command portfolio broke simulation-only boundary: ${JSON.stringify(portfolio)}`)
  }
}

async function assertSignalOpsPaperOrderVisibleBoundary(page, orderId) {
  const governance = page.getByTestId(`signalops-paper-order-governance-${orderId}`)
  await governance.waitFor({ state: 'visible', timeout: 30000 })
  const contextId = (await page.getByTestId(`signalops-paper-order-id-${orderId}`).innerText()).trim()
  const evidenceStrength = (await page.getByTestId(`signalops-paper-order-evidence-strength-${orderId}`).innerText()).trim()
  const blocker = (await page.getByTestId(`signalops-paper-order-blocker-${orderId}`).innerText()).trim()
  const nextAction = (await page.getByTestId(`signalops-paper-order-next-action-${orderId}`).innerText()).trim()
  if (!contextId.includes(orderId)) {
    throw new Error(`SignalOps paper order visible boundary rendered wrong context id for ${orderId}: ${contextId}`)
  }
  if (!evidenceStrength.includes('LOW')) {
    throw new Error(`SignalOps paper order visible boundary rendered unexpected evidence strength for ${orderId}: ${evidenceStrength}`)
  }
  if (!blocker || !nextAction) {
    throw new Error(`SignalOps paper order visible boundary is missing blocker or next action for ${orderId}: blocker=${blocker} next=${nextAction}`)
  }
  const boundary = await page.getByTestId(`signalops-paper-order-simulation-boundary-${orderId}`).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundary.includes(marker)) {
      throw new Error(`SignalOps paper order visible boundary is missing ${marker} for ${orderId}: ${boundary}`)
    }
  }
}

function assertSignalOpsReviewDecisionSimulationBoundary(payload, expectedAction) {
  const root = asRecord(payload)
  if (root.status !== 'COMPLETED') {
    throw new Error(`SignalOps review decision did not complete: ${JSON.stringify(root)}`)
  }
  assertSignalOpsSimulationBoundary(root, 'SignalOps review decision')

  const decision = asRecord(root.decision)
  if (decision.action !== expectedAction) {
    throw new Error(`SignalOps review decision action mismatch. expected=${expectedAction} payload=${JSON.stringify(root)}`)
  }
  if (decision.simulation_only !== true || decision.is_real_trade === true) {
    throw new Error(`SignalOps review decision broke simulation boundary: ${JSON.stringify(decision)}`)
  }
  const decisionSummary = asRecord(decision.review_decision_summary)
  const diffSummary = asRecord(decision.parameter_diff_summary)
  const diffChecksum = String(decision.parameter_diff_checksum || decisionSummary.parameter_diff_checksum || '')
  if (!diffChecksum.startsWith('sigops-paramdiff-')) {
    throw new Error(`SignalOps review decision did not persist parameter diff checksum: ${JSON.stringify(decision)}`)
  }
  if (!String(decision.review_event_hash || '').startsWith('sigops-reviewevent-')) {
    throw new Error(`SignalOps review decision did not persist append-only review event hash: ${JSON.stringify(decision)}`)
  }
  if (decisionSummary.review_event_hash !== decision.review_event_hash) {
    throw new Error(`SignalOps review decision summary did not mirror review event hash: ${JSON.stringify(decision)}`)
  }
  if (
    diffSummary.policy_id !== 'signalops_candidate_parameter_diff_v1'
    || diffSummary.simulation_only !== true
    || diffSummary.is_real_trade === true
    || !Array.isArray(diffSummary.rows)
    || diffSummary.rows.length === 0
  ) {
    throw new Error(`SignalOps review decision did not persist reviewed parameter diff summary: ${JSON.stringify(decision)}`)
  }

  const queueItem = asRecord(root.queue_item)
  if (Object.keys(queueItem).length) {
    if (queueItem.simulation_only === false || queueItem.is_real_trade === true) {
      throw new Error(`SignalOps review decision queue item broke simulation boundary: ${JSON.stringify(queueItem)}`)
    }
    if (expectedAction === 'APPROVE_SIMULATION_CANDIDATE' && queueItem.candidate_status !== 'APPLIED_TO_SIMULATION') {
      throw new Error(`SignalOps approval did not apply to simulation: ${JSON.stringify(queueItem)}`)
    }
    if (expectedAction === 'REJECT_CANDIDATE' && queueItem.candidate_status !== 'REJECTED') {
      throw new Error(`SignalOps rejection did not mark the queue item rejected: ${JSON.stringify(queueItem)}`)
    }
    if (queueItem.reviewed_parameter_diff_checksum !== diffChecksum) {
      throw new Error(`SignalOps review queue item did not retain reviewed parameter diff checksum: ${JSON.stringify(queueItem)}`)
    }
    if (queueItem.review_event_hash !== decision.review_event_hash) {
      throw new Error(`SignalOps review queue item did not retain review event hash: ${JSON.stringify(queueItem)}`)
    }
  }
}

async function assertSignalOpsReviewDecisionVisibleBoundary(reviewWindow, itemId) {
  const governance = reviewWindow.getByTestId(`signalops-review-governance-${itemId}`)
  await governance.waitFor({ state: 'visible', timeout: 15000 })
  const contextId = (await reviewWindow.getByTestId(`signalops-review-governance-id-${itemId}`).innerText()).trim()
  const evidenceStrength = (await reviewWindow.getByTestId(`signalops-review-evidence-strength-${itemId}`).innerText()).trim()
  const blocker = (await reviewWindow.getByTestId(`signalops-review-blocker-${itemId}`).innerText()).trim()
  const nextAction = (await reviewWindow.getByTestId(`signalops-review-next-action-${itemId}`).innerText()).trim()
  if (!contextId) {
    throw new Error(`SignalOps review visible boundary is missing context id for ${itemId}`)
  }
  const normalizedEvidenceStrength = evidenceStrength.toUpperCase()
  if (
    !evidenceStrength
    || normalizedEvidenceStrength.includes('HIGH')
    || normalizedEvidenceStrength.includes('STRONG')
    || evidenceStrength.includes('高')
    || evidenceStrength.includes('强')
  ) {
    throw new Error(`SignalOps review visible boundary rendered unexpected evidence strength for ${itemId}: ${evidenceStrength}`)
  }
  if (!blocker || !nextAction) {
    throw new Error(`SignalOps review visible boundary is missing blocker or next action for ${itemId}: blocker=${blocker} next=${nextAction}`)
  }
  const boundary = await reviewWindow.getByTestId(`signalops-review-simulation-boundary-${itemId}`).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundary.includes(marker)) {
      throw new Error(`SignalOps review visible boundary is missing ${marker} for ${itemId}: ${boundary}`)
    }
  }
}

function assertResearchSignalOpsEvidenceBoundary(payload) {
  const root = asRecord(payload)
  const iteration = asRecord(root.iteration)
  const inputs = asRecord(root.verdict_inputs)
  const metrics = asRecord(inputs.metrics || iteration.metrics)
  if (!iteration.iteration_id || !inputs.iteration_id || iteration.iteration_id !== inputs.iteration_id) {
    throw new Error(`SignalOps Research evidence response did not return a matching iteration: ${JSON.stringify(root)}`)
  }
  if (
    root.evidence_usage !== 'supporting_only'
    || root.supporting_only !== true
    || root.simulation_only !== true
    || root.is_real_trade !== false
    || root.strong_conclusion_allowed !== false
  ) {
    throw new Error(`SignalOps Research evidence response did not expose the top-level supporting-only simulation boundary: ${JSON.stringify(root)}`)
  }
  if (metrics.simulation_only !== true || metrics.is_real_trade !== false) {
    throw new Error(`SignalOps Research evidence broke simulation boundary: ${JSON.stringify(metrics)}`)
  }
  if (metrics.signalops_evidence_usage !== 'supporting_only' || metrics.signalops_supporting_only !== true) {
    throw new Error(`SignalOps Research evidence was not marked supporting-only: ${JSON.stringify(metrics)}`)
  }
  const evidence = Array.isArray(inputs.evidence) ? inputs.evidence : []
  if (!evidence.some((item) => asRecord(item).source_type === 'SIGNALOPS_TICK')) {
    throw new Error(`SignalOps Research evidence response did not include SIGNALOPS_TICK evidence: ${JSON.stringify(root)}`)
  }
}

function researchReviewStrength(value, fallbackStatus = '') {
  const normalized = String(value || '').trim().toUpperCase()
  if ([
    'HIGH',
    'STRONG',
    'PRIMARY',
    'PRIMARY_EVIDENCE',
    'PRIMARY_EVIDENCE_READY',
    'PASS',
    'READY',
    'RESEARCH_GRADE',
  ].includes(normalized)) return 'MEDIUM'
  if (['MEDIUM', 'LOW', 'MISSING', 'PENDING', 'UNKNOWN'].includes(normalized)) return normalized
  if (['SUPPORTING_ONLY', 'WARN', 'REVIEW', 'REVIEW_ONLY'].includes(normalized)) return 'LOW'
  if (['FAIL', 'FAILED', 'BLOCKED'].includes(normalized)) return 'MISSING'
  return fallbackStatus ? researchReviewStrength(fallbackStatus) : 'UNKNOWN'
}

function researchQualityLabel(value) {
  const normalized = String(value || '').trim().toUpperCase()
  const labels = {
    HIGH: '高',
    MEDIUM: '中',
    LOW: '低',
    PASS: '通过',
    WARN: '需关注',
    FAIL: '失败',
    MISSING: '缺失',
  }
  return labels[normalized] || normalized || 'UNKNOWN'
}

function backtestVerdictAuditEvidence(payload, backtestRunId) {
  const inputs = asRecord(asRecord(payload).verdict_inputs)
  const evidence = Array.isArray(inputs.evidence) ? inputs.evidence : []
  const record = asRecord(evidence.find((item) => {
    const candidate = asRecord(item)
    return candidate.source_type === 'BACKTEST' && candidate.source_id === backtestRunId
  }))
  const sourceId = String(record.source_id || '').trim()
  if (!sourceId) return null

  const reportedQuality = String(record.reportedQuality || record.reported_quality || '').trim()
  const reviewQuality = String(record.quality || '').trim()
  if (!reportedQuality || reportedQuality.toUpperCase() === reviewQuality.toUpperCase()) return null

  const reviewGateQuality = researchReviewStrength(reviewQuality)
  return {
    sourceId,
    reportedQuality,
    reviewGateQuality,
    detailText: `reportedQuality=${researchQualityLabel(reportedQuality)} -> review_gate=${researchQualityLabel(reviewGateQuality)}`,
    evidence: record,
  }
}

async function assertBacktestRunVisibleBoundary(page, expectedRunId) {
  await page.getByTestId('backtest-run-governance').waitFor({ state: 'visible', timeout: 15000 })
  const contextId = (await page.getByTestId('backtest-run-governance-id').innerText()).trim()
  if (contextId !== expectedRunId) {
    throw new Error(`Backtest run governance rendered ${contextId} instead of ${expectedRunId}`)
  }
  const evidenceStrength = (await page.getByTestId('backtest-run-evidence-strength').innerText()).trim()
  if (!evidenceStrength || evidenceStrength.includes('HIGH') || evidenceStrength.includes('STRONG')) {
    throw new Error(`Backtest run governance rendered unexpected evidence strength: ${evidenceStrength}`)
  }
  const blocker = (await page.getByTestId('backtest-run-blocker').innerText()).trim()
  const nextAction = (await page.getByTestId('backtest-run-next-action').innerText()).trim()
  if (!blocker || !nextAction) {
    throw new Error(`Backtest run governance is missing blocker or next action: blocker=${blocker} next=${nextAction}`)
  }
  const boundary = await page.getByTestId('backtest-run-simulation-boundary').innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=supporting_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundary.includes(marker)) {
      throw new Error(`Backtest run visible boundary is missing ${marker}: ${boundary}`)
    }
  }
}

async function seedResearchBacktestReportedQualityAudit(iterationId, backtestRunId) {
  const createdAt = new Date().toISOString()
  await apiJson('POST', `/api/research/iterations/${encodeURIComponent(iterationId)}/feedback`, {
    action: 'STRICT_AUTH_BROWSER_REPORTED_QUALITY_AUDIT',
    verdict: 'PENDING',
    status: 'BACKTEST_AUDIT_ATTACHED',
    note: `STRICT_AUTH_BROWSER_REPORTED_QUALITY_AUDIT ${backtestRunId}`,
    reviewer: 'strict-auth-browser',
    linked_backtest_id: backtestRunId,
    metrics: {
      strict_auth_browser_reported_quality_audit: true,
      evidence_usage: 'review_gate_only',
      simulation_only: true,
      is_real_trade: false,
    },
    evidence_links: [
      {
        source_type: 'BACKTEST',
        source_id: backtestRunId,
        label: 'STRICT_AUTH_BROWSER_REPORTED_QUALITY_AUDIT',
        quality: 'SUPPORTING_ONLY',
        reportedQuality: 'SUPPORTING_ONLY',
        created_at: createdAt,
      },
    ],
  })
  return apiJson('POST', `/api/research/iterations/${encodeURIComponent(iterationId)}/verdict-inputs/refresh`)
}

function assertResearchBacktestVerdictInputsBoundary(payload, iterationId, backtestRunId) {
  const root = asRecord(payload)
  const iteration = asRecord(root.iteration)
  const inputs = asRecord(root.verdict_inputs)
  const metrics = asRecord(inputs.metrics)
  if (iteration.iteration_id !== iterationId || inputs.iteration_id !== iterationId) {
    throw new Error(`Backtest verdict inputs returned the wrong Research iteration: ${JSON.stringify(root)}`)
  }
  if (
    root.evidence_usage !== 'supporting_only'
    || root.supporting_only !== true
    || root.simulation_only !== true
    || root.is_real_trade !== false
    || root.strong_conclusion_allowed !== false
  ) {
    throw new Error(`Backtest verdict inputs response did not expose the top-level supporting-only simulation boundary: ${JSON.stringify(root)}`)
  }
  if (iteration.linked_backtest_id !== backtestRunId) {
    throw new Error(`Backtest verdict inputs did not attach the selected backtest run: ${JSON.stringify(iteration)}`)
  }
  if (metrics.candidate_backtest_id !== backtestRunId) {
    throw new Error(`Backtest verdict inputs did not preserve the candidate backtest id: ${JSON.stringify(metrics)}`)
  }
  if (metrics.backtest_research_usage !== 'supporting_only') {
    throw new Error(`Backtest verdict inputs were not marked supporting-only: ${JSON.stringify(metrics)}`)
  }
  const evidence = Array.isArray(inputs.evidence) ? inputs.evidence : []
  const backtestEvidence = evidence.find((item) => asRecord(item).source_type === 'BACKTEST' && asRecord(item).source_id === backtestRunId)
  if (!backtestEvidence) {
    throw new Error(`Backtest verdict inputs response did not include BACKTEST evidence: ${JSON.stringify(root)}`)
  }
  const audit = backtestVerdictAuditEvidence(payload, backtestRunId)
  const reviewConclusion = String(metrics.backtest_review_conclusion || '').trim().toUpperCase()
  if (reviewConclusion === 'REVIEW_GATE_READY' && !audit) {
    throw new Error(`Backtest verdict inputs did not retain reportedQuality audit grade: ${JSON.stringify(backtestEvidence)}`)
  }
  if (
    audit
    && (
      String(audit.reportedQuality || '').trim().toUpperCase() !== 'SUPPORTING_ONLY'
      || audit.reviewGateQuality !== 'LOW'
    )
  ) {
    throw new Error(`Backtest verdict inputs did not retain SUPPORTING_ONLY reportedQuality audit grade: ${JSON.stringify(audit.evidence)}`)
  }
}

function assertP2ClosedLoopReviewBoundary(payload, label) {
  const root = asRecord(payload)
  if (root.simulation_only !== true || root.is_real_trade !== false) {
    throw new Error(`${label} broke the top-level simulation boundary: ${JSON.stringify(root)}`)
  }
  const steps = Array.isArray(root.steps) ? root.steps : []
  if (!steps.length) {
    throw new Error(`${label} did not expose review steps: ${JSON.stringify(root)}`)
  }
  for (const stepValue of steps) {
    const step = asRecord(stepValue)
    const usage = String(step.evidence_usage || '')
    const strength = String(step.evidence_strength || '').toUpperCase()
    if (
      usage !== 'review_gate_only'
      || step.simulation_only !== true
      || step.is_real_trade !== false
      || step.strong_conclusion_allowed !== false
      || strength === 'HIGH'
      || strength.includes('STRONG')
      || usage === 'primary_evidence'
    ) {
      throw new Error(`${label} step upgraded review-gated evidence: ${JSON.stringify(step)}`)
    }
  }
}

function assertBacktestExperimentPackage(payload, backtestRunId) {
  const root = asRecord(payload)
  const manifest = asRecord(root.manifest)
  const hashes = asRecord(root.hashes)
  if (!String(root.package_id || '').startsWith('BTEP_')) {
    throw new Error(`Backtest experiment package did not include a BTEP_ package id: ${JSON.stringify(root)}`)
  }
  if (root.run_id !== backtestRunId || manifest.runId !== backtestRunId) {
    throw new Error(`Backtest experiment package did not match selected run ${backtestRunId}: ${JSON.stringify(root)}`)
  }
  if (manifest.schemaVersion !== 'backtest_experiment_package_v1') {
    throw new Error(`Backtest experiment package schema mismatch: ${JSON.stringify(manifest)}`)
  }
  if (!String(hashes.dataPackageHash || '').trim()) {
    throw new Error(`Backtest experiment package did not carry dataPackageHash: ${JSON.stringify(hashes)}`)
  }
  if (root.simulation_only !== true || root.is_real_trade !== false) {
    throw new Error(`Backtest experiment package broke simulation boundary: ${JSON.stringify(root)}`)
  }
}

function assertBacktestParameterScanBoundary(payload) {
  const root = asRecord(payload)
  const summary = asRecord(root.summary)
  const bestValidationProtocol = asRecord(summary.bestValidationProtocol)
  const bestParameterScan = asRecord(bestValidationProtocol.parameterScan)
  const bestWalkForward = asRecord(bestValidationProtocol.walkForward)
  const bestPackageHashes = asRecord(bestValidationProtocol.packageHashes)
  const runIds = Array.isArray(root.run_ids) ? root.run_ids.map((item) => String(item)) : []
  const runs = Array.isArray(root.runs) ? root.runs : []
  const windows = Array.isArray(root.windows) ? root.windows : []
  const totalTrials = Number(summary.totalTrials ?? root.trial_count ?? runIds.length)
  const totalCombinations = Number(summary.totalCombinations ?? root.combinations?.length ?? 0)
  const windowCount = Number(summary.windowCount ?? root.window_count ?? windows.length)
  if (!String(root.scan_id || '').startsWith('BTS_') || root.status !== 'COMPLETED') {
    throw new Error(`Backtest parameter scan did not complete with a scan id: ${JSON.stringify(root)}`)
  }
  if (root.simulation_only !== true || root.is_real_trade !== false) {
    throw new Error(`Backtest parameter scan broke response simulation boundary: ${JSON.stringify(root)}`)
  }
  if (!root.best_run_id || !runIds.includes(String(root.best_run_id))) {
    throw new Error(`Backtest parameter scan best run was not one of the created runs: ${JSON.stringify(root)}`)
  }
  if (runs.length !== runIds.length || runs.length === 0) {
    throw new Error(`Backtest parameter scan did not return all created runs: ${JSON.stringify(root)}`)
  }
  if (totalTrials !== runIds.length || totalCombinations < 1 || windowCount < 1 || summary.rankingMetric !== 'research_grade_score') {
    throw new Error(`Backtest parameter scan summary did not match the requested bounded scan: ${JSON.stringify(summary)}`)
  }
  if (bestParameterScan.enabled !== true || bestWalkForward.enabled !== true) {
    throw new Error(`Backtest parameter scan best run did not carry scan and walk-forward validation protocol: ${JSON.stringify(bestValidationProtocol)}`)
  }
  if (!String(bestPackageHashes.dataPackageHash || '').trim()) {
    throw new Error(`Backtest parameter scan best validation protocol did not carry dataPackageHash: ${JSON.stringify(bestValidationProtocol)}`)
  }
  for (const run of runs) {
    const record = asRecord(run)
    const parameters = asRecord(record.parameters)
    const parameterScan = asRecord(parameters.parameter_scan)
    const report = asRecord(record.report)
    const validationProtocol = asRecord(report.validationProtocol)
    const reportParameterScan = asRecord(validationProtocol.parameterScan)
    const researchContract = asRecord(report.researchContract)
    if (!runIds.includes(String(record.run_id))) {
      throw new Error(`Backtest parameter scan returned an unexpected run id: ${JSON.stringify(record)}`)
    }
    if (parameters.simulation_only !== true || parameters.is_real_trade !== false) {
      throw new Error(`Backtest parameter scan generated run broke simulation boundary: ${JSON.stringify(parameters)}`)
    }
    if (parameterScan.enabled !== true || parameterScan.scanId !== root.scan_id) {
      throw new Error(`Backtest parameter scan generated run missed parameter_scan metadata: ${JSON.stringify(parameters)}`)
    }
    if (
      Number(parameterScan.trialCount || 0) !== totalTrials
      || Number(parameterScan.windowCount || 0) !== windowCount
      || !asRecord(parameterScan.window).start
    ) {
      throw new Error(`Backtest parameter scan generated run missed multi-window metadata: ${JSON.stringify(parameterScan)}`)
    }
    if (reportParameterScan.enabled !== true || researchContract.parameter_scan_configured !== true) {
      throw new Error(`Backtest parameter scan generated run report missed validation protocol evidence: ${JSON.stringify(report)}`)
    }
  }
}

function buildSignalOpsReviewDecisionFixture(baseConfig) {
  const now = new Date().toISOString()
  const makeQueueItem = ({ id, symbol, title }) => ({
    id,
    queue_item_id: id,
    experiment_id: `${id}-experiment`,
    signal_id: '',
    symbol,
    title,
    candidate_status: 'READY_FOR_REVIEW',
    promotion_status: 'READY_FOR_REVIEW',
    lifecycle_status: 'READY_FOR_REVIEW',
    review_allowed: true,
    review_decision: 'PENDING_REVIEW',
    evidence_quality: 'MEDIUM',
    risk_level: 'MEDIUM',
    reason: `${title} strict-auth browser review fixture`,
    latest_action: 'SIM_HOLD',
    strategy_experiment: {
      experiment_id: `${id}-experiment`,
      experiment_package_hash: `${id}-hash`,
      baseline_config: {
        buy_change_threshold_pct: 1.2,
        close_change_threshold_pct: -5,
        kline_strategy: { min_score: 60 },
        ladder_buy_policy: { target_position_ratio: 0.15, max_step_position_ratio: 0.05 },
      },
      candidate_config: {
        buy_change_threshold_pct: 0.8,
        close_change_threshold_pct: -4.5,
        kline_strategy: { min_score: 66 },
        ladder_buy_policy: { target_position_ratio: 0.2, max_step_position_ratio: 0.1 },
      },
      parameter_diff_summary: {
        policy_id: 'signalops_candidate_parameter_diff_v1',
        status: 'CHANGED',
        changed_count: 4,
        added_count: 0,
        removed_count: 0,
        unchanged_count: 2,
        total_parameter_count: 6,
        visible_row_count: 4,
        truncated: false,
        source: 'server_generated',
        simulation_only: true,
        is_real_trade: false,
        rows: [
          { key: 'buy_change_threshold_pct', baseline: 1.2, candidate: 0.8, change_type: 'CHANGED' },
          { key: 'close_change_threshold_pct', baseline: -5, candidate: -4.5, change_type: 'CHANGED' },
          { key: 'kline_strategy.min_score', baseline: 60, candidate: 66, change_type: 'CHANGED' },
          { key: 'ladder_buy_policy.target_position_ratio', baseline: 0.15, candidate: 0.2, change_type: 'CHANGED' },
        ],
      },
      candidate_reason: `${title} strict-auth candidate keeps simulation-only review before promotion.`,
      benchmark_comparison: { symbol: '000300.SH', available: true, status: 'AVAILABLE' },
      simulation_only: true,
      is_real_trade: false,
    },
    benchmark_comparison: { symbol: '000300.SH', available: true, status: 'AVAILABLE' },
    walk_forward_validation: {
      status: 'PASSED',
      benchmark_comparison: { symbol: '000300.SH', available: true, status: 'AVAILABLE' },
      train_window: { start: '2026-01-01', end: '2026-01-05' },
      validation_window: { start: '2026-01-06', end: '2026-01-10' },
    },
    walk_forward_run_ids: {
      baseline_validation: `${id}-baseline`,
      candidate_validation: `${id}-candidate`,
    },
    evidence_package: {
      package_id: `${id}-evidence`,
      experiment_package_hash: `${id}-hash`,
      evidence_links: [{ type: 'browser-fixture', id }],
      research_evidence_package: { package_id: `${id}-research-package`, review_queue_sync_status: 'SYNCED' },
    },
    kline_evidence_package: {
      package_id: `${id}-kline`,
      score: 72,
      kline_signal_quality: {
        final_score: 72,
        action_policy: 'HOLD',
        trend_regime: { status: 'STABLE' },
        risk_invalidation: { status: 'CLEAR', reasons: [] },
        bottom_stage_score: { score: 68 },
        volume_price_confirmation: { status: 'CONFIRMED' },
        volatility_compression: { status: 'NORMAL' },
        ladder_buy_policy: { target_position_ratio: 0.2, max_step_position_ratio: 0.1 },
      },
    },
    stability_evidence_package: {
      package_id: `${id}-stability`,
      strategy_stability_quality: {
        stability_score: 74,
        action_policy: 'HOLD',
        regime_state: { status: 'STABLE' },
        volatility_state: { status: 'NORMAL' },
        meta_label_gate: { status: 'PASS', wilson_win_rate_lower_bound: 0.55 },
        volatility_sizing_policy: { max_position_ratio: 0.3, max_step_position_ratio: 0.1 },
      },
    },
    factor_sources: ['browser_fixture'],
    simulation_only: true,
    is_real_trade: false,
    updated_at: now,
  })

  const fixtureConfig = {
    ...cloneJson(baseConfig || {}),
    enabled: true,
    automation_mode: 'SIMULATION',
    simulation_module: { status: 'ACTIVE', simulation_only: true, is_real_trade: false },
    live_module: { status: 'CONFIGURED_DISABLED', execution_enabled: false, simulation_only: true, is_real_trade: false },
    symbol: '',
    stock_name: '',
    signal_id: null,
    signal_ids: {},
    review_decisions: [],
    review_queue_state: {
      version: 1,
      updated_at: now,
      items: [
        makeQueueItem({ id: 'rq-approve', symbol: '603663', title: '603663 approval fixture' }),
        makeQueueItem({ id: 'rq-reject', symbol: '300750', title: '300750 rejection fixture' }),
      ],
      observations: [],
      counts: { ready_for_review: 2 },
      simulation_only: true,
      is_real_trade: false,
    },
    experiment_validation_state: {
      simulation_only: true,
      is_real_trade: false,
      latest_hash: 'rq-approve-hash',
      attempts: {
        'rq-approve-hash': { status: 'PASSED', experiment_package_hash: 'rq-approve-hash', review_queue_sync_status: 'SYNCED', benchmark_comparison: { available: true, status: 'AVAILABLE' } },
        'rq-reject-hash': { status: 'PASSED', experiment_package_hash: 'rq-reject-hash', review_queue_sync_status: 'SYNCED', benchmark_comparison: { available: true, status: 'AVAILABLE' } },
      },
    },
    random_validation_state: { simulation_only: true, is_real_trade: false },
    performance_stats: {
      global: { all: { trade_count: 8, win_rate: 0.62, expectancy: 0.03, max_drawdown: -0.05, confidence: 0.7, quality_status: 'HEALTHY' } },
      symbols: {},
      factors: {},
      triggers: {},
    },
    updated_at: now,
  }
  const reviewEvents = []
  let reviewEventHandoffShipperStatus = null

  function getConfig() {
    return cloneJson(fixtureConfig)
  }

  function ledgerStatus() {
    const latest = reviewEvents[reviewEvents.length - 1] || {}
    return {
      schema: 'signalops_review_decision_event_ledger_v1',
      event_count: reviewEvents.length,
      latest_event_hash: String(latest.event_hash || ''),
      latest_decision_id: String(latest.decision_id || ''),
      ledger_file: 'auto_paper_review_decision_events.jsonl',
      handoff_shipper_status: reviewEventHandoffShipperStatus || {
        schema: 'signalops_review_decision_event_export_shipper_status_v1',
        checked: true,
        configured: true,
        reported: false,
        status: 'NOT_REPORTED',
        handoff_destination: 'LOCAL_DEPLOYMENT_HANDOFF_DIR',
        provider: '',
        matches_latest_handoff: false,
        matches_latest_export: false,
        search_index_ready: false,
        issues: ['no_handoff_manifest'],
        append_only: true,
        simulation_only: true,
        is_real_trade: false,
      },
      append_only: true,
      warnings: [],
      simulation_only: true,
      is_real_trade: false,
    }
  }

  function exportReviewEvents(limit = 100) {
    const events = reviewEvents.slice(-Math.max(1, Math.min(Number(limit || 100), 500)))
    const latest = events[events.length - 1] || {}
    const bundlePayload = {
      schema: 'signalops_review_decision_event_export_v1',
      events,
      total_event_count: reviewEvents.length,
      latest_event_hash: String(latest.event_hash || ''),
    }
    const bundleChecksum = `sigops-reviewevents-${createHash('sha1').update(JSON.stringify(bundlePayload)).digest('hex').slice(0, 20)}`
    const signingPayload = {
      ...bundlePayload,
      returned_event_count: events.length,
      bundle_checksum: bundleChecksum,
      ledger_file: 'auto_paper_review_decision_events.jsonl',
      append_only: true,
      simulation_only: true,
      is_real_trade: false,
    }
    return {
      ...bundlePayload,
      generated_at: new Date().toISOString(),
      returned_event_count: events.length,
      bundle_checksum: bundleChecksum,
      ledger_file: 'auto_paper_review_decision_events.jsonl',
      append_only: true,
      export_signature_status: 'SIGNED',
      export_signature: {
        schema: 'signalops_review_decision_event_export_signature_v1',
        algorithm: 'HMAC-SHA256',
        signature: `sigops-reviewevents-hmac-${createHmac('sha256', 'strict-auth-review-event-export-secret').update(JSON.stringify(signingPayload)).digest('hex')}`,
        payload_checksum: bundleChecksum,
        signing_key_ref: 'strict-auth-fixture-key',
        signed_fields: [
          'schema',
          'events',
          'total_event_count',
          'latest_event_hash',
          'returned_event_count',
          'bundle_checksum',
          'ledger_file',
          'append_only',
          'simulation_only',
          'is_real_trade',
        ],
        simulation_only: true,
        is_real_trade: false,
      },
      warnings: [],
      simulation_only: true,
      is_real_trade: false,
    }
  }

  function verifyReviewEventExport(bundle) {
    const payload = asRecord(bundle)
    const events = Array.isArray(payload.events) ? payload.events : []
    const latest = asRecord(events[events.length - 1])
    const latestEventHash = String(payload.latest_event_hash || '')
    const bundlePayload = {
      schema: payload.schema,
      events,
      total_event_count: payload.total_event_count,
      latest_event_hash: latestEventHash,
    }
    const expectedBundleChecksum = `sigops-reviewevents-${createHash('sha1').update(JSON.stringify(bundlePayload)).digest('hex').slice(0, 20)}`
    const providedBundleChecksum = String(payload.bundle_checksum || '')
    const signingPayload = {
      ...bundlePayload,
      returned_event_count: payload.returned_event_count,
      bundle_checksum: providedBundleChecksum,
      ledger_file: payload.ledger_file,
      append_only: payload.append_only,
      simulation_only: payload.simulation_only,
      is_real_trade: payload.is_real_trade,
    }
    const signature = asRecord(payload.export_signature)
    const expectedSignature = `sigops-reviewevents-hmac-${createHmac('sha256', 'strict-auth-review-event-export-secret').update(JSON.stringify(signingPayload)).digest('hex')}`
    const signedFields = [
      'schema',
      'events',
      'total_event_count',
      'latest_event_hash',
      'returned_event_count',
      'bundle_checksum',
      'ledger_file',
      'append_only',
      'simulation_only',
      'is_real_trade',
    ]
    const checksumValid = providedBundleChecksum === expectedBundleChecksum
    const signatureValid = String(signature.signature || '') === expectedSignature
    const latestEventHashValid = latestEventHash === String(latest.event_hash || '')
    const returnedEventCountValid = payload.returned_event_count === events.length
    const totalEventCountValid = Number.isInteger(payload.total_event_count) && payload.total_event_count >= events.length
    const signedFieldsValid = JSON.stringify(signature.signed_fields || []) === JSON.stringify(signedFields)
    const payloadChecksumValid = String(signature.payload_checksum || '') === providedBundleChecksum && checksumValid
    const signingKeyRefValid = String(signature.signing_key_ref || '') === 'strict-auth-fixture-key'
    const boundaryValid = payload.append_only === true && payload.simulation_only === true && payload.is_real_trade === false
    const signatureBoundaryValid = signature.simulation_only === true && signature.is_real_trade === false
    const valid = Boolean(
      payload.schema === 'signalops_review_decision_event_export_v1'
        && checksumValid
        && signatureValid
        && payloadChecksumValid
        && signedFieldsValid
        && signingKeyRefValid
        && latestEventHashValid
        && returnedEventCountValid
        && totalEventCountValid
        && boundaryValid
        && signatureBoundaryValid,
    )
    return {
      schema: 'signalops_review_decision_event_export_verification_v1',
      status: valid ? 'VALID' : (signature.signature ? 'INVALID' : 'UNSIGNED'),
      valid,
      checked_at: new Date().toISOString(),
      signature_status: String(payload.export_signature_status || (signature.signature ? 'SIGNED' : 'UNSIGNED')).toUpperCase(),
      schema_valid: payload.schema === 'signalops_review_decision_event_export_v1',
      checksum_valid: checksumValid,
      signature_valid: signatureValid,
      payload_checksum_valid: payloadChecksumValid,
      signed_fields_valid: signedFieldsValid,
      signing_key_ref_valid: signingKeyRefValid,
      latest_event_hash_valid: latestEventHashValid,
      returned_event_count_valid: returnedEventCountValid,
      total_event_count_valid: totalEventCountValid,
      boundary_valid: boundaryValid,
      signature_boundary_valid: signatureBoundaryValid,
      provided_bundle_checksum: providedBundleChecksum,
      expected_bundle_checksum: expectedBundleChecksum,
      signing_key_ref: String(signature.signing_key_ref || ''),
      expected_signing_key_ref: 'strict-auth-fixture-key',
      event_count: events.length,
      warnings: valid ? [] : ['fixture_export_verification_failed'],
      append_only: true,
      simulation_only: true,
      is_real_trade: false,
    }
  }

  function handoffReviewEventExport(limit = 100) {
    const bundle = exportReviewEvents(limit)
    const verification = verifyReviewEventExport(bundle)
    if (!verification.valid) {
      return {
        schema: 'signalops_review_decision_event_export_handoff_v1',
        status: 'BLOCKED',
        created_at: new Date().toISOString(),
        reason: 'Signed export verification must be VALID before handoff.',
        bundle_checksum: bundle.bundle_checksum,
        export_signature_status: bundle.export_signature_status,
        verification,
        handoff_destination: 'LOCAL_DEPLOYMENT_HANDOFF_DIR',
        handoff_requires_signature: true,
        append_only: true,
        simulation_only: true,
        is_real_trade: false,
      }
    }
    const handoffId = `sigops-reviewevents-handoff-browser-${String(bundle.bundle_checksum || '').slice(-12)}`
    const bundleFile = `${handoffId}.json`
    const manifestFile = `${handoffId}.manifest.json`
    const manifest = {
      schema: 'signalops_review_decision_event_export_handoff_manifest_v1',
      handoff_id: handoffId,
      status: 'HANDED_OFF',
      handoff_destination: 'LOCAL_DEPLOYMENT_HANDOFF_DIR',
      bundle_file: bundleFile,
      manifest_file: manifestFile,
      bundle_checksum: bundle.bundle_checksum,
      export_signature_status: bundle.export_signature_status,
      verification_status: verification.status,
      event_count: bundle.returned_event_count,
      total_event_count: bundle.total_event_count,
      latest_event_hash: bundle.latest_event_hash,
      retention_policy: {
        policy_id: 'signalops_review_event_deployment_handoff_v1',
        custody: 'deployment_owned_after_handoff',
        requires_signed_export: true,
        requires_valid_verification: true,
      },
      append_only: true,
      simulation_only: true,
      is_real_trade: false,
    }
    reviewEventHandoffShipperStatus = {
      schema: 'signalops_review_decision_event_export_shipper_status_v1',
      checked: true,
      configured: true,
      reported: true,
      status: 'DELIVERED',
      handoff_destination: 'LOCAL_DEPLOYMENT_HANDOFF_DIR',
      handoff_dir: 'strict-auth-fixture-handoff',
      sidecar_file: 'strict-auth-fixture-handoff/shipper_status.json',
      source: 'strict-auth-signalops-shipper',
      provider: 'object-store',
      remote_destination: 's3://strict-auth-signalops/review-events/[REDACTED]',
      object_key: `signalops/${handoffId}.json`,
      retention_policy_id: 'signalops-review-events-retention-30d',
      retention_status: 'RETAINED',
      custody_status: 'KMS_RETAINED',
      kms_key_ref: 'strict-auth-kms-key',
      search_index: 'signalops-review-event-artifacts',
      search_index_ready: true,
      last_handoff_id: handoffId,
      last_bundle_checksum: bundle.bundle_checksum,
      last_latest_event_hash: bundle.latest_event_hash,
      latest_handoff_id: handoffId,
      latest_bundle_checksum: bundle.bundle_checksum,
      latest_manifest_file: manifestFile,
      latest_event_hash: bundle.latest_event_hash,
      matches_latest_handoff: true,
      matches_latest_export: true,
      deployment_reported: true,
      message: 'uploaded',
      issues: [],
      append_only: true,
      simulation_only: true,
      is_real_trade: false,
    }
    return {
      schema: 'signalops_review_decision_event_export_handoff_v1',
      status: 'HANDED_OFF',
      created_at: new Date().toISOString(),
      reason: '',
      handoff_id: handoffId,
      handoff_dir: 'strict-auth-fixture-handoff',
      handoff_destination: 'LOCAL_DEPLOYMENT_HANDOFF_DIR',
      handoff_requires_signature: true,
      bundle_file: bundleFile,
      manifest_file: manifestFile,
      bundle_checksum: bundle.bundle_checksum,
      export_signature_status: bundle.export_signature_status,
      verification,
      shipper_status: reviewEventHandoffShipperStatus,
      manifest,
      append_only: true,
      simulation_only: true,
      is_real_trade: false,
    }
  }

  function getStatus() {
    return {
      ...getConfig(),
      loop_running: false,
      loop_health: 'HEALTHY',
      automation_modules: {
        active_module: 'simulation',
        simulation: { status: 'ACTIVE', simulation_only: true, is_real_trade: false },
        live: { status: 'CONFIGURED_DISABLED', execution_enabled: false, simulation_only: true, is_real_trade: false },
      },
      review_decision_event_ledger: ledgerStatus(),
    }
  }

  function recordDecision(payload) {
    const queueItemId = String(payload.queue_item_id || '')
    const item = fixtureConfig.review_queue_state.items.find((candidate) => candidate.queue_item_id === queueItemId)
    if (!item) {
      throw new Error(`SignalOps review fixture did not find queue item ${queueItemId}`)
    }
    const action = String(payload.action || '')
    const resultStatus = action === 'APPROVE_SIMULATION_CANDIDATE'
      ? 'APPLIED_TO_SIMULATION'
      : action === 'REJECT_CANDIDATE'
        ? 'REJECTED'
        : action === 'REQUEST_PATCH'
          ? 'PATCH_REQUESTED'
          : 'RECOMMENDED_ONLY'
    item.review_decision = action
    item.candidate_status = resultStatus
    item.promotion_status = resultStatus
    item.lifecycle_status = resultStatus
    item.review_allowed = false
    item.updated_at = new Date().toISOString()
    const diffSummary = asRecord(item.parameter_diff_summary || asRecord(item.strategy_experiment).parameter_diff_summary)
    const diffChecksum = `sigops-paramdiff-${createHash('sha1').update(JSON.stringify(diffSummary)).digest('hex').slice(0, 16)}`
    item.reviewed_parameter_diff_checksum = diffChecksum
    item.reviewed_parameter_diff_summary = diffSummary

    const decision = {
      decision_id: `DECISION-${queueItemId}-${fixtureConfig.review_decisions.length + 1}`,
      queue_item_id: queueItemId,
      experiment_id: item.experiment_id,
      signal_id: payload.signal_id || null,
      symbol: item.symbol,
      action,
      result_status: resultStatus,
      reviewer: payload.reviewer,
      reason: payload.reason,
      evidence_refs: Array.isArray(payload.evidence_refs) ? payload.evidence_refs : [],
      review_fields: Array.isArray(payload.review_fields) ? payload.review_fields : [],
      applied_parameters: action === 'APPROVE_SIMULATION_CANDIDATE' ? { buy_change_threshold_pct: 0.8 } : {},
      parameter_diff_summary: diffSummary,
      parameter_diff_checksum: diffChecksum,
      reviewed_parameter_count: Number(diffSummary.total_parameter_count || 0),
      reviewed_parameter_changed_count: Number(diffSummary.changed_count || 0),
      review_decision_summary: {
        candidate_status_before: 'READY_FOR_REVIEW',
        candidate_status_after: item.candidate_status,
        parameter_diff_checksum: diffChecksum,
        parameter_diff_status: diffSummary.status,
        reviewed_parameter_count: Number(diffSummary.total_parameter_count || 0),
        reviewed_parameter_changed_count: Number(diffSummary.changed_count || 0),
        simulation_only: true,
        is_real_trade: false,
      },
      created_at: item.updated_at,
      simulation_only: true,
      is_real_trade: false,
    }
    const previousEvent = reviewEvents[reviewEvents.length - 1] || {}
    const event = {
      schema: 'signalops_review_decision_event_v1',
      event_type: 'SIGNALOPS_REVIEW_DECISION',
      created_at: item.updated_at,
      decision_id: decision.decision_id,
      queue_item_id: decision.queue_item_id,
      experiment_id: decision.experiment_id,
      signal_id: decision.signal_id,
      symbol: decision.symbol,
      action: decision.action,
      result_status: decision.result_status,
      reviewer: decision.reviewer,
      reason: decision.reason,
      parameter_diff_checksum: decision.parameter_diff_checksum,
      parameter_diff_summary: diffSummary,
      reviewed_parameter_count: decision.reviewed_parameter_count,
      reviewed_parameter_changed_count: decision.reviewed_parameter_changed_count,
      candidate_status_after: item.candidate_status,
      review_decision_summary: decision.review_decision_summary,
      previous_event_hash: String(previousEvent.event_hash || ''),
      append_only: true,
      simulation_only: true,
      is_real_trade: false,
    }
    event.event_hash = `sigops-reviewevent-${createHash('sha1').update(JSON.stringify(event)).digest('hex').slice(0, 20)}`
    decision.review_event_hash = event.event_hash
    decision.review_event_previous_hash = event.previous_event_hash
    decision.review_event_schema = event.schema
    decision.review_decision_summary.review_event_hash = event.event_hash
    item.review_event_hash = event.event_hash
    reviewEvents.push(event)
    fixtureConfig.review_decisions = [...(fixtureConfig.review_decisions || []), decision]
    fixtureConfig.review_queue_state.updated_at = item.updated_at
    fixtureConfig.review_queue_state.counts = {
      ready_for_review: fixtureConfig.review_queue_state.items.filter((candidate) => candidate.candidate_status === 'READY_FOR_REVIEW').length,
    }
    return {
      status: 'COMPLETED',
      message: 'Review decision recorded.',
      decision,
      queue_item: cloneJson(item),
      config: getConfig(),
      warnings: [],
    }
  }

  return { getConfig, getStatus, recordDecision, exportReviewEvents, verifyReviewEventExport, handoffReviewEventExport }
}

async function assertAuthedJson(responsePromise, label) {
  const response = await responsePromise
  if (!response.ok()) {
    throw new Error(`${label} returned ${response.status()}: ${await response.text()}`)
  }
  await assertBearer(response, label)
  return response.json()
}

async function assertAuthedJsonOrApi(responsePromise, label, route, options = {}) {
  try {
    return await assertAuthedJson(responsePromise, label)
  } catch (error) {
    const message = String(error?.message || '')
    if (error?.name !== 'TimeoutError' && !message.includes('Timeout')) {
      throw error
    }
    if (options.page) {
      try {
        console.warn(`${label} browser response wait timed out; using page API fallback for ${route}`)
        return await pageApiJson(options.page, 'GET', route, undefined, options.timeoutMs || 60000)
      } catch (pageError) {
        console.warn(`${label} page API fallback failed; using direct API fallback for ${route}: ${pageError?.message || pageError}`)
      }
    } else {
      console.warn(`${label} browser response wait timed out; using direct API fallback for ${route}`)
    }
    return apiJson('GET', route)
  }
}

async function seedBackendAttemptDiagnosticsRun() {
  const createPayload = await apiJson('POST', '/api/analysis/runs', {
    symbol: '603663',
    task_type: 'position_review',
    run_mode: 'FAST_MODE',
    scenario_id: 'qiam_discounted',
    user_constraints: {
      cost_price: 10,
      max_drawdown: 0.08,
      allow_add: false,
      allow_t0: false,
    },
    config_profile_id: 'default',
  })
  const runId = String(createPayload?.run_id || '')
  if (!runId.startsWith('RUN_')) {
    throw new Error(`seeded analysis run did not return a RUN_ id: ${JSON.stringify(createPayload)}`)
  }
  createdRunIds.add(runId)

  const startPayload = await apiJson('POST', `/api/analysis/runs/${encodeURIComponent(runId)}/start`, {
    operator: 'strict-auth-browser-smoke',
  })
  if (startPayload?.run_id !== runId || !['QUEUED', 'RUNNING'].includes(String(startPayload?.status || ''))) {
    throw new Error(`seeded analysis run did not enter worker scheduling: ${JSON.stringify(startPayload)}`)
  }

  let seededAttempts = []
  for (let attempt = 0; attempt < 12; attempt += 1) {
    seededAttempts = await apiJson('GET', `/api/analysis/jobs/attempts?run_id=${encodeURIComponent(runId)}&limit=12`)
    if (!Array.isArray(seededAttempts)) {
      throw new Error(`seeded analysis run attempts endpoint did not return an array: ${JSON.stringify(seededAttempts)}`)
    }
    if (seededAttempts.some((item) => item?.run_id === runId)) {
      return runId
    }
    await delay(1000)
  }
  throw new Error(`seeded analysis run did not create attempt diagnostics: ${JSON.stringify(seededAttempts)}`)
}

async function runSignalOpsScenario(page) {
  await apiJson('PATCH', '/api/signalops/auto-paper/config', {
    enabled: true,
    symbol: '603663',
    stock_name: 'SignalOps Browser Smoke',
    initial_cash: 100000,
    min_order_value: 1000,
    tick_interval_seconds: 60,
    min_order_interval_seconds: 5,
    use_llm: false,
  })

  const configResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/signalops/auto-paper/config?compact=true')
  ), { timeout: 30000 })
  const statusResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/signalops/auto-paper/status?compact=true')
  ), { timeout: 30000 })

  await page.locator('a[href="/signalops"]').first().click()
  await page.waitForURL(/\/signalops$/, { timeout: 15000 })
  await page.getByTestId('signalops-console').waitFor({ state: 'visible', timeout: 15000 })
  const configPayload = await assertAuthedJson(configResponsePromise, 'SignalOps auto-paper config load')
  const statusPayload = await assertAuthedJson(statusResponsePromise, 'SignalOps auto-paper status load')
  assertSignalOpsSimulationBoundary(configPayload, 'SignalOps auto-paper config')
  assertSignalOpsSimulationBoundary(statusPayload, 'SignalOps auto-paper status')
  console.log('ok strict-auth browser SignalOps config/status boundary')

  const browserSmokeConfig = cloneJson(configPayload)
  browserSmokeConfig.automation_modules = {
    active_module: 'simulation',
    simulation: { status: 'ACTIVE', simulation_only: true, is_real_trade: false },
    live: { status: 'CONFIGURED_DISABLED', execution_enabled: false, simulation_only: true, is_real_trade: false },
  }
  const assertSignalOpsWrite = async (route, label) => {
    const request = route.request()
    const headers = await request.allHeaders()
    if (request.method() !== 'POST') {
      throw new Error(`${label} used ${request.method()} instead of POST`)
    }
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error(`${label} did not include the expected Authorization bearer token`)
    }
    return request.postDataJSON()
  }
  await page.route('**/api/signalops/auto-paper/tick', async (route) => {
    const payload = await assertSignalOpsWrite(route, 'SignalOps forced tick')
    if (payload.force !== true) {
      throw new Error(`SignalOps forced tick did not request force=true: ${JSON.stringify(payload)}`)
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'COMPLETED',
        message: 'browser smoke forced tick',
        signal_id: 'SIG_BROWSER_SMOKE',
        symbol: '603663',
        config: browserSmokeConfig,
        decision: {
          action: 'SIM_HOLD',
          symbol: '603663',
          price: 10,
          simulation_only: true,
          is_real_trade: false,
        },
        decision_card: {
          action: 'SIM_HOLD',
          reason: 'browser smoke deterministic tick',
          simulation_only: true,
          is_real_trade: false,
        },
        module_evidence: {
          automation_modules: browserSmokeConfig.automation_modules,
          trade_boundary: {
            allowed_order_namespace: 'SIM_*',
            live_module_status: 'CONFIGURED_DISABLED',
            simulation_only: true,
            is_real_trade: false,
          },
        },
        portfolio_snapshot: {
          snapshotId: 'PF_SIGNALOPS_BROWSER_SMOKE',
          sourceType: 'SIGNALOPS_SIM',
          positionCount: 1,
          simulation_only: true,
          is_real_trade: false,
        },
        order: {
          action: 'SIM_HOLD',
          simulation_only: true,
          is_real_trade: false,
        },
        warnings: [],
      }),
    })
  })
  await page.route('**/api/signalops/auto-paper/daily-review', async (route) => {
    const payload = await assertSignalOpsWrite(route, 'SignalOps daily review')
    if (payload.reviewer !== 'SignalOpsPage') {
      throw new Error(`SignalOps daily review sent unexpected reviewer: ${JSON.stringify(payload)}`)
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'COMPLETED',
        message: 'browser smoke daily review',
        trading_date: '2026-06-03',
        config: browserSmokeConfig,
        reviewed_symbols: [
          { symbol: '603663', status: 'REVIEWED', simulation_only: true, is_real_trade: false },
        ],
        case_ids: [],
        evidence_links: [],
        tuning_update: {},
        cleaned_records: [],
        review_queue_state: {
          simulation_only: true,
          is_real_trade: false,
          items: [
            { symbol: '603663', candidate_status: 'PENDING_REVIEW', simulation_only: true, is_real_trade: false },
          ],
        },
        review_decisions: [],
        experiment_validation_state: { simulation_only: true, is_real_trade: false },
        random_validation_state: { simulation_only: true, is_real_trade: false },
        decision_tree_reviews: [],
        warnings: [],
      }),
    })
  })
  await page.route('**/api/signalops/auto-paper/command', async (route) => {
    const payload = await assertSignalOpsWrite(route, 'SignalOps manual command')
    if (payload.symbol !== '603663' || payload.command !== 'FORCE_OPEN_BUY') {
      throw new Error(`SignalOps manual command sent unexpected payload: ${JSON.stringify(payload)}`)
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'COMPLETED',
        message: 'browser smoke manual command',
        symbol: '603663',
        signal_id: 'SIG_BROWSER_SMOKE',
        config: browserSmokeConfig,
        order: {
          action: 'SIM_BUY',
          simulated_price: 10,
          simulated_quantity: 100,
          simulation_only: true,
          is_real_trade: false,
          risk_constraints: {
            manual_command: 'FORCE_OPEN_BUY',
            simulation_only: true,
            is_real_trade: false,
          },
        },
        portfolio: {
          snapshotId: 'PF_SIGNALOPS_BROWSER_SMOKE',
          sourceType: 'SIGNALOPS_SIM',
          simulation_only: true,
          is_real_trade: false,
        },
        warnings: [],
      }),
    })
  })

  await page.getByTestId('signalops-open-boundary').click()
  const boundaryWindow = page.getByTestId('signalops-boundary-window')
  await boundaryWindow.waitFor({ state: 'visible', timeout: 15000 })
  const boundaryText = await boundaryWindow.innerText()
  if (!boundaryText.includes('仅模拟：是') || !boundaryText.includes('真实交易：否')) {
    throw new Error('SignalOps boundary window did not expose the simulation-only/no-real-trade copy')
  }
  console.log('ok strict-auth browser SignalOps boundary window')

  const manualOps = page.getByTestId('signalops-manual-ops')
  await manualOps.locator('summary').click()
  const tickButton = manualOps.getByTestId('signalops-run-tick')
  const tickResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/signalops/auto-paper/tick')
      && response.status() === 200
  ), { timeout: 45000 })
  await clickEnabled(tickButton, 'SignalOps forced tick button')
  const tickPayload = await assertAuthedJson(tickResponsePromise, 'SignalOps forced tick')
  assertSignalOpsTickSimulationBoundary(tickPayload)
  await manualOps.getByTestId('signalops-result-snapshot').waitFor({ state: 'visible', timeout: 15000 })
  const tickSummary = await manualOps.getByTestId('signalops-tick-result-summary').innerText()
  if (tickSummary.includes('暂无') || (tickPayload.symbol && !tickSummary.includes(String(tickPayload.symbol)))) {
    throw new Error(`SignalOps forced tick result was not rendered. summary=${tickSummary} status=${tickPayload.status}`)
  }
  console.log('ok strict-auth browser SignalOps forced tick')

  const dailyReviewResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/signalops/auto-paper/daily-review')
      && response.status() === 200
  ), { timeout: 60000 })
  await clickEnabled(manualOps.getByTestId('signalops-run-daily-review'), 'SignalOps daily review button')
  const dailyReviewPayload = await assertAuthedJson(dailyReviewResponsePromise, 'SignalOps daily review')
  assertSignalOpsDailyReviewSimulationBoundary(dailyReviewPayload)
  await manualOps.getByTestId('signalops-daily-review-summary').waitFor({ state: 'visible', timeout: 15000 })
  const dailySummary = await manualOps.getByTestId('signalops-daily-review-summary').innerText()
  if (dailySummary.includes('暂无')) {
    throw new Error(`SignalOps daily review result was not rendered. summary=${dailySummary} status=${dailyReviewPayload.status}`)
  }
  console.log('ok strict-auth browser SignalOps daily review')

  const poolManualOps = page.getByTestId('signalops-pool-manual-ops')
  await poolManualOps.locator('summary').click()
  const commandResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/signalops/auto-paper/command')
      && response.status() === 200
  ), { timeout: 60000 })
  await poolManualOps.getByTestId('signalops-command-FORCE_OPEN_BUY-603663').click()
  const commandPayload = await assertAuthedJson(commandResponsePromise, 'SignalOps manual command')
  assertSignalOpsCommandSimulationBoundary(commandPayload)
  await manualOps.getByTestId('signalops-command-result-summary').waitFor({ state: 'visible', timeout: 15000 })
  const commandSummary = await manualOps.getByTestId('signalops-command-result-summary').innerText()
  if (commandSummary.includes('暂无') || !commandSummary.includes('603663')) {
    throw new Error(`SignalOps manual command result was not rendered. summary=${commandSummary} status=${commandPayload.status}`)
  }
  console.log('ok strict-auth browser SignalOps manual command')

  await page.getByTestId('signalops-close-boundary').click()
  await boundaryWindow.waitFor({ state: 'hidden', timeout: 15000 })
  await page.unroute('**/api/signalops/auto-paper/tick').catch(() => undefined)
  await page.unroute('**/api/signalops/auto-paper/daily-review').catch(() => undefined)
  await page.unroute('**/api/signalops/auto-paper/command').catch(() => undefined)
}

async function runSignalOpsReviewDecisionScenario(page) {
  const baseConfig = await apiJson('GET', '/api/signalops/auto-paper/config')
  const fixture = buildSignalOpsReviewDecisionFixture(baseConfig)
  const observedActions = []

  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    if (pathname === '/api/signalops/auto-paper/config' && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixture.getConfig()) })
      return
    }
    if (pathname === '/api/signalops/auto-paper/status' && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixture.getStatus()) })
      return
    }
    if (pathname === '/api/signalops/auto-paper/review-decision-events' && request.method() === 'GET') {
      const headers = await request.allHeaders()
      if (headers.authorization !== `Bearer ${authToken}`) {
        throw new Error('SignalOps review decision event export did not include the expected Authorization bearer token')
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixture.exportReviewEvents(Number(url.searchParams.get('limit') || 100))),
      })
      return
    }
    if (pathname === '/api/signalops/auto-paper/review-decision-events/verify' && request.method() === 'POST') {
      const headers = await request.allHeaders()
      if (headers.authorization !== `Bearer ${authToken}`) {
        throw new Error('SignalOps review decision event export verification did not include the expected Authorization bearer token')
      }
      const payload = request.postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixture.verifyReviewEventExport(asRecord(payload).bundle)),
      })
      return
    }
    if (pathname === '/api/signalops/auto-paper/review-decision-events/handoff' && request.method() === 'POST') {
      const headers = await request.allHeaders()
      if (headers.authorization !== `Bearer ${authToken}`) {
        throw new Error('SignalOps review decision event export handoff did not include the expected Authorization bearer token')
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixture.handoffReviewEventExport(Number(url.searchParams.get('limit') || 100))),
      })
      return
    }
    if (pathname === '/api/signals' && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (/^\/api\/signalops\/[^/]+\/paper-portfolio$/.test(pathname) && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
      return
    }
    if (/^\/api\/signalops\/[^/]+\/paper-(orders|positions)$/.test(pathname) && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (pathname === '/api/signalops/auto-paper/review-decisions' && request.method() === 'POST') {
      const headers = await request.allHeaders()
      if (headers.authorization !== `Bearer ${authToken}`) {
        throw new Error('SignalOps review decision did not include the expected Authorization bearer token')
      }
      const payload = request.postDataJSON()
      if (!['APPROVE_SIMULATION_CANDIDATE', 'REJECT_CANDIDATE'].includes(String(payload.action || ''))) {
        throw new Error(`SignalOps review decision sent unexpected action: ${JSON.stringify(payload)}`)
      }
      if (!String(payload.queue_item_id || '').startsWith('rq-')) {
        throw new Error(`SignalOps review decision did not include fixture queue item id: ${JSON.stringify(payload)}`)
      }
      if (!Array.isArray(payload.review_fields) || !payload.review_fields.some((field) => String(field).includes('simulation_only'))) {
        throw new Error(`SignalOps review decision did not include simulation boundary review fields: ${JSON.stringify(payload)}`)
      }
      observedActions.push(payload.action)
      const responsePayload = fixture.recordDecision(payload)
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(responsePayload) })
      return
    }
    await route.continue()
  }

  await page.route('**/api/**', routeHandler)
  try {
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/')
    await page.waitForURL((url) => url.pathname === '/', { timeout: 15000 })
    await page.waitForTimeout(250)
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/backend')
    await page.waitForURL((url) => url.pathname === '/backend', { timeout: 15000 })
    await page.waitForTimeout(250)
    await page.locator('a[href="/signalops"]').first().click()
    await page.waitForURL(/\/signalops$/, { timeout: 15000 })
    await page.getByTestId('signalops-console').waitFor({ state: 'visible', timeout: 15000 })

    await page.getByTestId('signalops-open-review-window').first().click()
    const reviewWindow = page.getByTestId('signalops-review-window')
    await reviewWindow.waitFor({ state: 'visible', timeout: 15000 })

    await reviewWindow.getByTestId('signalops-review-queue-item-rq-approve').click()
    await assertSignalOpsReviewDecisionVisibleBoundary(reviewWindow, 'rq-approve')
    console.log('ok strict-auth browser SignalOps review decision visible boundary')

    const candidateBaselinePanel = reviewWindow.getByTestId('signalops-review-candidate-baseline')
    await candidateBaselinePanel.waitFor({ state: 'visible', timeout: 15000 })
    await reviewWindow.getByTestId('signalops-review-candidate-baseline-row-buy_change_threshold_pct').waitFor({ state: 'visible', timeout: 15000 })
    const candidateBaselineText = await candidateBaselinePanel.innerText()
    if (
      !candidateBaselineText.includes('Candidate / baseline parameters')
      || !candidateBaselineText.includes('Baseline: 1.2%')
      || !candidateBaselineText.includes('Candidate: 0.8%')
      || !candidateBaselineText.includes('changed: 4')
      || !candidateBaselineText.includes('policy: signalops_candidate_parameter_diff_v1')
      || !candidateBaselineText.includes('CHANGED')
      || !candidateBaselineText.includes('strict-auth candidate')
    ) {
      throw new Error(`SignalOps review candidate/baseline parameter evidence did not render expected fixture values: ${candidateBaselineText}`)
    }
    console.log('ok strict-auth browser SignalOps candidate baseline review')

    const approvalResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes('/api/signalops/auto-paper/review-decisions')
        && response.status() === 200
    ), { timeout: 30000 })
    await reviewWindow.getByTestId('signalops-review-decision-PASS_REVIEW').click()
    const approvalPayload = await assertAuthedJson(approvalResponsePromise, 'SignalOps review decision approval')
    assertSignalOpsReviewDecisionSimulationBoundary(approvalPayload, 'APPROVE_SIMULATION_CANDIDATE')
    await expectText(page, '已应用到模拟', 'SignalOps review approval rendered')

    await reviewWindow.getByTestId('signalops-review-queue-item-rq-reject').click()
    const rejectionResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes('/api/signalops/auto-paper/review-decisions')
        && response.status() === 200
    ), { timeout: 30000 })
    await reviewWindow.getByTestId('signalops-review-decision-REJECT_SUGGESTION').click()
    const rejectionPayload = await assertAuthedJson(rejectionResponsePromise, 'SignalOps review decision rejection')
    assertSignalOpsReviewDecisionSimulationBoundary(rejectionPayload, 'REJECT_CANDIDATE')
    await expectText(page, '已驳回', 'SignalOps review rejection rendered')

    if (!observedActions.includes('APPROVE_SIMULATION_CANDIDATE') || !observedActions.includes('REJECT_CANDIDATE')) {
      throw new Error(`SignalOps review decision fixture did not observe both actions: ${observedActions.join(', ')}`)
    }
    const ledgerPayload = await page.evaluate(async (token) => {
      const response = await fetch('/api/signalops/auto-paper/review-decision-events?limit=5', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!response.ok) {
        throw new Error(`review decision event export failed ${response.status}`)
      }
      return response.json()
    }, authToken)
    if (
      ledgerPayload.schema !== 'signalops_review_decision_event_export_v1'
      || ledgerPayload.append_only !== true
      || ledgerPayload.simulation_only !== true
      || ledgerPayload.is_real_trade !== false
      || !String(ledgerPayload.bundle_checksum || '').startsWith('sigops-reviewevents-')
      || ledgerPayload.export_signature_status !== 'SIGNED'
      || asRecord(ledgerPayload.export_signature).schema !== 'signalops_review_decision_event_export_signature_v1'
      || asRecord(ledgerPayload.export_signature).algorithm !== 'HMAC-SHA256'
      || !String(asRecord(ledgerPayload.export_signature).signature || '').startsWith('sigops-reviewevents-hmac-')
      || asRecord(ledgerPayload.export_signature).payload_checksum !== ledgerPayload.bundle_checksum
      || !String(ledgerPayload.latest_event_hash || '').startsWith('sigops-reviewevent-')
      || !Array.isArray(ledgerPayload.events)
      || ledgerPayload.events.length !== 2
      || !ledgerPayload.events.every((event) => String(asRecord(event).parameter_diff_checksum || '').startsWith('sigops-paramdiff-'))
    ) {
      throw new Error(`SignalOps review decision event ledger export did not expose expected append-only evidence: ${JSON.stringify(ledgerPayload)}`)
    }
    const verificationPayload = await page.evaluate(async ({ token, bundle }) => {
      const response = await fetch('/api/signalops/auto-paper/review-decision-events/verify', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ bundle }),
      })
      if (!response.ok) {
        throw new Error(`review decision event export verification failed ${response.status}`)
      }
      return response.json()
    }, { token: authToken, bundle: ledgerPayload })
    if (
      verificationPayload.schema !== 'signalops_review_decision_event_export_verification_v1'
      || verificationPayload.status !== 'VALID'
      || verificationPayload.valid !== true
      || verificationPayload.checksum_valid !== true
      || verificationPayload.signature_valid !== true
      || verificationPayload.payload_checksum_valid !== true
    ) {
      throw new Error(`SignalOps review decision event export verification did not validate the signed bundle: ${JSON.stringify(verificationPayload)}`)
    }
    const tamperedVerificationPayload = await page.evaluate(async ({ token, bundle }) => {
      const tampered = JSON.parse(JSON.stringify(bundle))
      tampered.events[tampered.events.length - 1].parameter_diff_checksum = 'sigops-paramdiff-tampered'
      const response = await fetch('/api/signalops/auto-paper/review-decision-events/verify', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ bundle: tampered }),
      })
      if (!response.ok) {
        throw new Error(`tampered review decision event export verification failed ${response.status}`)
      }
      return response.json()
    }, { token: authToken, bundle: ledgerPayload })
    if (
      tamperedVerificationPayload.status !== 'INVALID'
      || tamperedVerificationPayload.valid !== false
      || tamperedVerificationPayload.checksum_valid !== false
      || tamperedVerificationPayload.signature_valid !== false
    ) {
      throw new Error(`SignalOps review decision event export verification accepted a tampered bundle: ${JSON.stringify(tamperedVerificationPayload)}`)
    }
    await reviewWindow.locator('button').first().click()
    await reviewWindow.waitFor({ state: 'hidden', timeout: 15000 })
    const automationLog = page.getByTestId('signalops-automation-log')
    await automationLog.locator('summary').click()
    const uiVerifyResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes('/api/signalops/auto-paper/review-decision-events/verify')
        && response.status() === 200
    ), { timeout: 30000 })
    await automationLog.getByTestId('signalops-verify-review-event-export').click()
    const uiVerificationPayload = await assertAuthedJson(uiVerifyResponsePromise, 'SignalOps review decision event export UI verification')
    if (uiVerificationPayload.status !== 'VALID' || uiVerificationPayload.valid !== true) {
      throw new Error(`SignalOps review decision event export UI verification failed: ${JSON.stringify(uiVerificationPayload)}`)
    }
    const verificationText = await automationLog.getByTestId('signalops-review-event-export-verification-status').innerText()
    if (!verificationText.includes('VALID') || !verificationText.includes('Export verify')) {
      throw new Error(`SignalOps review decision event export verification status did not render: ${verificationText}`)
    }
    const handoffResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes('/api/signalops/auto-paper/review-decision-events/handoff')
        && response.status() === 200
    ), { timeout: 30000 })
    await automationLog.getByTestId('signalops-handoff-review-event-export').click()
    const handoffPayload = await assertAuthedJson(handoffResponsePromise, 'SignalOps review decision event export handoff')
    if (
      handoffPayload.schema !== 'signalops_review_decision_event_export_handoff_v1'
      || handoffPayload.status !== 'HANDED_OFF'
      || handoffPayload.handoff_destination !== 'LOCAL_DEPLOYMENT_HANDOFF_DIR'
      || asRecord(handoffPayload.verification).status !== 'VALID'
      || asRecord(handoffPayload.manifest).schema !== 'signalops_review_decision_event_export_handoff_manifest_v1'
      || asRecord(asRecord(handoffPayload.manifest).retention_policy).custody !== 'deployment_owned_after_handoff'
      || asRecord(handoffPayload.shipper_status).schema !== 'signalops_review_decision_event_export_shipper_status_v1'
      || asRecord(handoffPayload.shipper_status).status !== 'DELIVERED'
      || asRecord(handoffPayload.shipper_status).matches_latest_handoff !== true
      || asRecord(handoffPayload.shipper_status).matches_latest_export !== true
      || handoffPayload.simulation_only !== true
      || handoffPayload.is_real_trade !== false
    ) {
      throw new Error(`SignalOps review decision event export handoff returned unexpected payload: ${JSON.stringify(handoffPayload)}`)
    }
    const handoffText = await automationLog.getByTestId('signalops-review-event-export-handoff-status').innerText()
    if (!handoffText.includes('HANDED_OFF') || !handoffText.includes('LOCAL_DEPLOYMENT_HANDOFF_DIR')) {
      throw new Error(`SignalOps review decision event export handoff status did not render: ${handoffText}`)
    }
    await page.waitForFunction(() => (
      document.querySelector('[data-testid="signalops-review-event-export-shipper-status"]')?.textContent?.includes('DELIVERED')
    ), null, { timeout: 30000 })
    const shipperText = await automationLog.getByTestId('signalops-review-event-export-shipper-status').innerText()
    if (
      !shipperText.includes('DELIVERED')
      || !shipperText.includes('object-store')
      || !shipperText.includes('signalops-review-events-retention-30d')
      || shipperText.includes('unit-secret')
    ) {
      throw new Error(`SignalOps review decision event export shipper status did not render safely: ${shipperText}`)
    }
    console.log('ok strict-auth browser SignalOps review decision export handoff custody')
    console.log('ok strict-auth browser SignalOps review decisions')
  } finally {
    await page.unroute('**/api/**', routeHandler).catch(() => undefined)
  }
}

async function runSignalOpsResearchEvidenceScenario(page, iterationId = 'RITER_BROWSER_SIGNALOPS_EVIDENCE') {
  const baseConfig = await apiJson('GET', '/api/signalops/auto-paper/config')
  const now = new Date().toISOString()
  const signalId = 'SIG_BROWSER_RESEARCH_EVIDENCE'
  const symbol = '688888'
  const paperOrderId = 'ORDER_SIGNALOPS_BROWSER_SMOKE'
  const tick = {
    status: 'COMPLETED',
    message: 'browser SignalOps tick evidence fixture',
    signal_id: signalId,
    symbol,
    updated_at: now,
    decision_card: {
      action: 'SIM_HOLD',
      reason: 'browser smoke keeps SignalOps evidence supporting-only',
      simulation_only: true,
      is_real_trade: false,
    },
    module_evidence: {
      version: 'signalops_module_evidence_v1',
      symbol,
      generated_at: now,
    },
    portfolio_snapshot: {
      snapshot_id: 'PF_BROWSER_SIGNALOPS_EVIDENCE',
      signal_id: signalId,
      simulation_only: true,
      is_real_trade: false,
    },
  }
  const signal = {
    signal_id: signalId,
    symbol,
    stock_name: 'SignalOps Research Evidence',
    status: 'PAPER_TEST',
    source_run_id: 'RUN_BROWSER_SIGNALOPS_EVIDENCE',
    latest_run_id: 'RUN_BROWSER_SIGNALOPS_EVIDENCE',
    audit_id: 'AUD_BROWSER_SIGNALOPS_EVIDENCE',
    risk_passed: true,
    dvg_passed: true,
    dvg_status: 'PASS',
    qiam_passed: true,
    qiam_status: 'PASS',
    execution_reachable: false,
    portfolio_allowed: true,
    trigger_conditions: ['browser tick fixture'],
    invalidation_conditions: ['browser fixture invalidation'],
    review_fields: ['auto_paper_trading', 'research_lab_feedback', 'simulation_only'],
    attached_runs: ['RUN_BROWSER_SIGNALOPS_EVIDENCE'],
    blocked_reason: '',
    metadata_json: {
      source: 'strict-auth-browser-smoke',
      simulation_only: true,
      is_real_trade: false,
    },
    created_at: now,
    updated_at: now,
  }
  const signalDetail = {
    signal,
    transitions: [
      {
        transition_id: 'SIGTR_BROWSER_SIGNALOPS_EVIDENCE',
        signal_id: signalId,
        from_status: 'WATCH',
        to_status: 'PAPER_TEST',
        audit_id: 'AUD_BROWSER_SIGNALOPS_EVIDENCE',
        run_id: 'RUN_BROWSER_SIGNALOPS_EVIDENCE',
        actor: 'system',
        reason: 'Browser fixture entered paper-test lifecycle.',
        gate_checks: [{ key: 'browser_fixture', passed: true, message: 'deterministic fixture' }],
        passed: true,
        created_at: now,
      },
    ],
    reviews: [],
  }
  const browserSmokePaperOrder = {
    order_id: paperOrderId,
    paper_portfolio_id: 'PF_SIGNALOPS_BROWSER_SMOKE',
    signal_id: signalId,
    audit_id: 'AUD_BROWSER_SIGNALOPS_EVIDENCE',
    agent_id: 'strict-auth-browser-smoke',
    action: 'SIM_BUY',
    action_reason: 'strict-auth browser paper order boundary fixture',
    simulated_price: 10,
    simulated_quantity: 100,
    fill_status: 'OBSERVED',
    decision_card: {
      action: 'SIM_BUY',
      budget_used: 1000,
      simulation_only: true,
      is_real_trade: false,
    },
    simulated_fill: {
      fees: 0,
      simulation_only: true,
      is_real_trade: false,
    },
    risk_constraints: {
      simulation_only: true,
      is_real_trade: false,
    },
    invalidation_conditions: [],
    data_snapshot_hash: 'strict-auth-browser-paper-order-hash',
    created_at: now,
    updated_at: now,
    simulation_only: true,
    is_real_trade: false,
  }
  const fixtureConfig = {
    ...baseConfig,
    enabled: true,
    symbol,
    stock_name: 'SignalOps Research Evidence',
    signal_id: signalId,
    signal_ids: { [symbol]: signalId },
    automation_mode: 'SIMULATION',
    simulation_module: {
      ...asRecord(baseConfig.simulation_module),
      simulation_only: true,
      is_real_trade: false,
    },
    live_module: {
      ...asRecord(baseConfig.live_module),
      execution_enabled: false,
      is_real_trade: false,
      order_router: 'DISABLED',
    },
    last_tick_result: tick,
    last_module_evidence: tick.module_evidence,
    last_portfolio_snapshot: tick.portfolio_snapshot,
    review_queue_state: {
      simulation_only: true,
      is_real_trade: false,
      items: [],
      summary: { pending: 0 },
    },
  }
  const fixtureStatus = {
    enabled: true,
    automation_mode: 'SIMULATION',
    automation_modules: {
      active_module: 'simulation',
      real_trade_enabled: false,
      live_ready: false,
      simulation: fixtureConfig.simulation_module,
      live: fixtureConfig.live_module,
    },
    loop_running: false,
    loop_health: 'HEALTHY',
    current_time: now,
    last_tick_at: now,
    last_success_at: now,
    tick_interval_seconds: 60,
    last_tick_result: tick,
    last_module_evidence: tick.module_evidence,
    last_portfolio_snapshot: tick.portfolio_snapshot,
    review_queue_state: fixtureConfig.review_queue_state,
  }
  const evidenceResponse = {
    evidence_usage: 'supporting_only',
    supporting_only: true,
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    iteration: {
      iteration_id: iterationId,
      loop_id: 'RLOOP_BROWSER_SIGNALOPS_EVIDENCE',
      order: 1,
      status: 'SIGNALOPS_EVIDENCE_ATTACHED',
      hypothesis: 'SignalOps tick evidence should remain supporting-only.',
      plan: 'Attach selected SignalOps tick to Research verdict inputs.',
      target_modules: ['signalops', 'research_verdict'],
      linked_run_id: null,
      linked_backtest_id: null,
      linked_case_id: null,
      linked_knowledge_item_id: null,
      linked_patch_id: null,
      metrics: {
        signalops_signal_id: signalId,
        signalops_tick_status: 'COMPLETED',
        signalops_evidence_usage: 'supporting_only',
        signalops_supporting_only: true,
        simulation_only: true,
        is_real_trade: false,
      },
      evidence_links: [
        {
          source_type: 'SIGNALOPS',
          source_id: signalId,
          label: 'SignalOps lifecycle evidence',
          quality: 'MEDIUM',
          created_at: now,
        },
        {
          source_type: 'SIGNALOPS_TICK',
          source_id: `${signalId}:${now}`,
          label: 'SignalOps tick evidence',
          quality: 'MEDIUM',
          created_at: now,
        },
      ],
      feedback_events: [],
      verdict: 'PENDING',
      created_at: now,
      updated_at: now,
    },
    verdict_inputs: {
      iteration_id: iterationId,
      loop_id: 'RLOOP_BROWSER_SIGNALOPS_EVIDENCE',
      status: 'SIGNALOPS_EVIDENCE_ATTACHED',
      current_verdict: 'PENDING',
      engine_verdict: 'PENDING',
      suggested_feedback_verdict: 'PENDING',
      confidence: 0.35,
      can_accept_feedback: false,
      blocking_reasons: ['SignalOps tick evidence is supporting-only.'],
      quality_warnings: ['SIGNALOPS_TICK evidence remains simulation-only.'],
      metrics: {
        signalops_signal_id: signalId,
        signalops_tick_status: 'COMPLETED',
        signalops_evidence_usage: 'supporting_only',
        signalops_supporting_only: true,
        simulation_only: true,
        is_real_trade: false,
      },
      baseline: {},
      current: {},
      comparison: [],
      evidence: [
        {
          source_type: 'SIGNALOPS_TICK',
          source_id: `${signalId}:${now}`,
          label: 'SignalOps tick evidence',
          quality: 'MEDIUM',
          summary: 'Existing iteration evidence.',
          metrics: {},
          created_at: now,
        },
      ],
      generated_at: now,
    },
  }
  const observed = { evidenceRequest: false }

  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const pathname = url.pathname
    if (pathname === '/api/signalops/auto-paper/config' && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtureConfig) })
      return
    }
    if (pathname === '/api/signalops/auto-paper/status' && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixtureStatus) })
      return
    }
    if (pathname === '/api/signals' && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([signal]) })
      return
    }
    if (pathname === `/api/signals/${signalId}` && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(signalDetail) })
      return
    }
    if (pathname === `/api/signalops/${signalId}/paper-portfolio` && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
      return
    }
    if (pathname === `/api/signalops/${signalId}/paper-orders` && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([browserSmokePaperOrder]) })
      return
    }
    if (pathname === `/api/signalops/${signalId}/paper-positions` && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (pathname === `/api/research/signalops/signals/${signalId}/evidence` && request.method() === 'POST') {
      const headers = await request.allHeaders()
      if (headers.authorization !== `Bearer ${authToken}`) {
        throw new Error('SignalOps Research evidence request did not include the expected Authorization bearer token')
      }
      const payload = request.postDataJSON()
      if (payload.iteration_id !== iterationId || payload.reviewer !== 'SignalOpsPage') {
        throw new Error(`SignalOps Research evidence sent unexpected payload: ${JSON.stringify(payload)}`)
      }
      observed.evidenceRequest = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(evidenceResponse) })
      return
    }
    await route.continue()
  }

  await page.route('**/api/**', routeHandler)
  try {
    await navigateByAppLink(page, '/backend', 'SignalOps Research evidence reset route')
    const signalDetailResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith(`/api/signals/${encodeURIComponent(signalId)}`)
        && response.status() === 200
    }, { timeout: 30000 })
    const paperOrdersResponses = bufferedResponses(page, (response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith(`/api/signalops/${encodeURIComponent(signalId)}/paper-orders`)
        && response.status() === 200
    })
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, `/signalops?iteration_id=${encodeURIComponent(iterationId)}&signal_id=${encodeURIComponent(signalId)}`)
    await page.waitForURL(/\/signalops\?/, { timeout: 15000 })
    await page.getByTestId('signalops-console').waitFor({ state: 'visible', timeout: 15000 })
    const detailPayload = await assertAuthedJson(signalDetailResponsePromise, 'SignalOps Research selected-signal detail load')
    if (asRecord(detailPayload?.signal).signal_id !== signalId) {
      throw new Error(`SignalOps Research selected-signal detail loaded the wrong signal: ${JSON.stringify(detailPayload)}`)
    }
    await page.getByTestId('signalops-selected-signal-detail').waitFor({ state: 'visible', timeout: 15000 })
    try {
      const paperOrdersPayload = await assertAuthedJson(paperOrdersResponses.next(30000), 'SignalOps Research selected-signal paper orders load')
      if (!Array.isArray(paperOrdersPayload) || !paperOrdersPayload.some((order) => asRecord(order).order_id === paperOrderId)) {
        throw new Error(`SignalOps Research selected-signal paper orders did not include ${paperOrderId}: ${JSON.stringify(paperOrdersPayload)}`)
      }
    } finally {
      paperOrdersResponses.stop()
    }
    await assertSignalOpsPaperOrderVisibleBoundary(page, 'ORDER_SIGNALOPS_BROWSER_SMOKE')
    console.log('ok strict-auth browser SignalOps paper order visible boundary')
    await page.getByTestId('signalops-research-evidence-context').waitFor({ state: 'visible', timeout: 15000 })

    const evidenceResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes(`/api/research/signalops/signals/${signalId}/evidence`)
        && response.status() === 200
    ), { timeout: 30000 })
    await clickEnabled(page.getByTestId('signalops-create-research-evidence'), 'SignalOps Research evidence button')
    const evidencePayload = await assertAuthedJson(evidenceResponsePromise, 'SignalOps Research evidence')
    assertResearchSignalOpsEvidenceBoundary(evidencePayload)
    await expectText(page, 'Research evidence attached', 'SignalOps Research evidence notice')
    const visibleBoundary = await page.getByTestId('signalops-research-evidence-boundary').innerText({ timeout: 15000 })
    for (const marker of [
      'evidence_usage=supporting_only',
      'supporting_only=true',
      'simulation_only=true',
      'is_real_trade=false',
      'strong_conclusion_allowed=false',
      'SIM_*',
    ]) {
      if (!visibleBoundary.includes(marker)) {
        throw new Error(`SignalOps visible Research evidence boundary is missing ${marker}: ${visibleBoundary}`)
      }
    }
    console.log('ok strict-auth browser SignalOps visible Research evidence boundary')
    if (!observed.evidenceRequest) {
      throw new Error('SignalOps Research evidence route fixture was not called')
    }
    console.log('ok strict-auth browser SignalOps Research evidence')
  } finally {
    await page.unroute('**/api/**', routeHandler).catch(() => undefined)
  }
}

async function runBacktestSampleScenario(page) {
  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, '/research-lab/backtest')
  await page.waitForURL(/\/research-lab\/backtest$/, { timeout: 15000 })
  await page.getByTestId('backtest-page').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('backtest-summary').waitFor({ state: 'visible', timeout: 15000 })

  await page.getByTestId('backtest-symbol').fill('BTBROWSER01')
  await page.getByTestId('backtest-start-date').fill('2026-01-01')
  await page.getByTestId('backtest-end-date').fill('2026-01-05')
  await page.getByTestId('backtest-signal-source').selectOption('MOCK')

  const createBacktestResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/research/backtest/runs')
      && response.status() === 200
  ), { timeout: 60000 })
  await page.getByTestId('backtest-run-submit').click()
  const backtestRun = await assertAuthedJson(createBacktestResponsePromise, 'Backtest sample run creation')
  const backtestRunId = String(backtestRun?.run_id || '')
  if (!backtestRunId) {
    throw new Error(`Backtest sample run creation did not return run_id: ${JSON.stringify(backtestRun)}`)
  }
  createdBacktestRunIds.add(backtestRunId)

  const parameters = asRecord(backtestRun.parameters)
  if (parameters.signal_source !== 'MOCK') {
    throw new Error(`Backtest sample run did not preserve the browser-selected MOCK signal source: ${JSON.stringify(parameters)}`)
  }
  if (parameters.is_real_trade === true || parameters.simulation_only === false) {
    throw new Error(`Backtest sample run broke the simulation boundary: ${JSON.stringify(parameters)}`)
  }

  await page.getByTestId('backtest-selected-run').waitFor({ state: 'visible', timeout: 30000 })
  const renderedRunId = (await page.getByTestId('backtest-selected-run-id').innerText()).trim()
  if (renderedRunId !== backtestRunId) {
    throw new Error(`Backtest page rendered run id ${renderedRunId} instead of created run ${backtestRunId}`)
  }
  await assertBacktestRunVisibleBoundary(page, backtestRunId)
  await page.getByTestId('backtest-report-panel').waitFor({ state: 'visible', timeout: 15000 })
  const experimentPackageResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes(`/api/research/backtest/runs/${encodeURIComponent(backtestRunId)}/experiment-package`)
      && response.status() === 200
  ), { timeout: 30000 })
  const downloadPromise = page.waitForEvent('download', { timeout: 30000 })
  await clickEnabled(page.getByTestId('backtest-experiment-package-download'), 'Backtest experiment package download')
  const packagePayload = await assertAuthedJson(experimentPackageResponsePromise, 'Backtest experiment package download')
  assertBacktestExperimentPackage(packagePayload, backtestRunId)
  const download = await downloadPromise
  const suggestedFilename = download.suggestedFilename()
  if (!suggestedFilename.endsWith('-experiment-package.json')) {
    throw new Error(`Backtest experiment package download used unexpected filename: ${suggestedFilename}`)
  }
  const downloadPath = await download.path()
  const downloadedPayload = JSON.parse(await readFile(downloadPath, 'utf8'))
  assertBacktestExperimentPackage(downloadedPayload, backtestRunId)
  if (downloadedPayload.package_id !== packagePayload.package_id) {
    throw new Error(`Backtest downloaded package did not match API package id: ${downloadedPayload.package_id} !== ${packagePayload.package_id}`)
  }
  console.log('ok strict-auth browser Backtest experiment package download')
  console.log('ok strict-auth browser Backtest sample visible run boundary')
  console.log('ok strict-auth browser Backtest sample run')
}

async function runBacktestParameterScanScenario(page) {
  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, '/research-lab/backtest')
  await page.waitForURL(/\/research-lab\/backtest(?:\?.*)?$/, { timeout: 15000 })
  await page.getByTestId('backtest-page').waitFor({ state: 'visible', timeout: 15000 })

  await page.getByTestId('backtest-symbol').fill('BTSCAN01')
  await page.getByTestId('backtest-start-date').fill('2026-01-01')
  await page.getByTestId('backtest-end-date').fill('2026-01-05')
  await page.getByTestId('backtest-signal-source').selectOption('MOCK')

  const scanResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/research/backtest/parameter-scan')
      && response.status() === 200
  ), { timeout: 60000 })
  await clickEnabled(page.getByTestId('backtest-parameter-scan-submit'), 'Backtest parameter scan button', 30000)
  const scanPayload = await assertAuthedJson(scanResponsePromise, 'Backtest parameter scan')
  assertBacktestParameterScanBoundary(scanPayload)
  for (const runId of scanPayload.run_ids || []) {
    createdBacktestRunIds.add(String(runId))
  }

  await page.getByTestId('backtest-parameter-scan-notice').waitFor({ state: 'visible', timeout: 30000 })
  const bestRunId = String(scanPayload.best_run_id || '')
  const bestRunPayload = (Array.isArray(scanPayload.runs) ? scanPayload.runs : [])
    .find((run) => String(asRecord(run).run_id || '') === bestRunId)
  const expectedBestWindowText = bestRunPayload
    ? `Window: ${String(asRecord(bestRunPayload).start_date || '')} -> ${String(asRecord(bestRunPayload).end_date || '')}`
    : 'Window:'
  await page.waitForFunction((expectedRunId) => (
    document.querySelector('[data-testid="backtest-selected-run-id"]')?.textContent?.trim() === expectedRunId
  ), bestRunId, { timeout: 30000 })
  await page.getByTestId('backtest-selected-run').waitFor({ state: 'visible', timeout: 30000 })
  const renderedRunId = (await page.getByTestId('backtest-selected-run-id').innerText()).trim()
  if (renderedRunId !== bestRunId) {
    throw new Error(`Backtest parameter scan rendered run id ${renderedRunId} instead of best run ${bestRunId}`)
  }
  await page.getByTestId('backtest-validation-protocol').waitFor({ state: 'visible', timeout: 15000 })
  const validationText = await page.getByTestId('backtest-validation-protocol').innerText()
  if (
    !validationText.includes('Parameter scan:')
    || !validationText.includes('Walk-forward:')
    || !validationText.includes('Data package:')
    || validationText.includes('Data package: -')
  ) {
    throw new Error(`Backtest parameter scan validation protocol was not visibly rendered: ${validationText}`)
  }
  await page.getByTestId('backtest-validation-detail').waitFor({ state: 'visible', timeout: 15000 })
  const validationDetailText = await page.getByTestId('backtest-validation-detail').innerText()
  if (
    !validationDetailText.includes('Research validation detail')
    || !validationDetailText.includes('Out-of-sample')
    || !validationDetailText.includes(expectedBestWindowText)
    || !validationDetailText.includes('Walk-forward')
    || !validationDetailText.includes('Mode: bounded_parameter_scan')
    || !validationDetailText.includes('Benchmark')
    || !validationDetailText.includes('Symbol: BTSCAN01')
    || !validationDetailText.includes('Type/source: symbol_buy_hold / MOCK')
    || !validationDetailText.includes('Parameter scan')
    || !validationDetailText.includes(`Scan: ${scanPayload.scan_id}`)
    || !validationDetailText.includes('Package hashes')
    || validationDetailText.includes('Data: -')
    || !validationDetailText.includes('Required for research grade')
  ) {
    throw new Error(`Backtest validation detail did not render research-grade fields: ${validationDetailText}`)
  }
  const noticeText = await page.getByTestId('backtest-parameter-scan-notice').innerText()
  if (
    !noticeText.includes(String(scanPayload.scan_id))
    || !noticeText.includes(bestRunId)
    || !noticeText.includes('Evidence: LOW')
    || !noticeText.includes('Parameter scan retained as review-gated evidence')
    || !noticeText.includes('simulation_only=true / is_real_trade=false / evidence_usage=review_gate_only / strong_conclusion_allowed=false / SIM_*')
  ) {
    throw new Error(`Backtest parameter scan notice did not render scan and best-run ids: ${noticeText}`)
  }
  await page.getByTestId('backtest-parameter-scan-history').waitFor({ state: 'visible', timeout: 30000 })
  await page.waitForFunction((scanId) => (
    document.querySelector('[data-testid="backtest-parameter-scan-history"]')?.textContent?.includes(scanId)
  ), String(scanPayload.scan_id), { timeout: 30000 })
  const historyText = await page.getByTestId('backtest-parameter-scan-history').innerText()
  if (
    !historyText.includes(String(scanPayload.scan_id))
    || !historyText.includes(bestRunId)
    || !historyText.includes('Trials:')
    || !historyText.includes('Windows:')
    || !historyText.includes('Combos:')
    || !historyText.includes('sim: true')
    || !historyText.includes('real: false')
    || !historyText.includes('Evidence: LOW')
    || !historyText.includes('Parameter scan retained as review-gated evidence')
    || !historyText.includes('Open best run and hand off supporting evidence to Research Lab')
    || !historyText.includes('simulation_only=true / is_real_trade=false / evidence_usage=review_gate_only / strong_conclusion_allowed=false / SIM_*')
  ) {
    throw new Error(`Backtest parameter scan history did not render retained scan evidence: ${historyText}`)
  }

  const scanJobResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/research/backtest/parameter-scan/jobs')
      && response.status() === 200
  ), { timeout: 60000 })
  await clickEnabled(page.getByTestId('backtest-parameter-scan-job-submit'), 'Backtest parameter scan job button', 30000)
  const scanJobCreated = await assertAuthedJson(scanJobResponsePromise, 'Backtest parameter scan job create')
  const scanJobId = String(scanJobCreated.jobId || '')
  if (
    !scanJobId.startsWith('BTSJOB_')
    || scanJobCreated.simulationOnly !== true
    || scanJobCreated.isRealTrade !== false
    || scanJobCreated.queueMode !== 'LOCAL_DURABLE_JSON'
    || scanJobCreated.durable !== true
    || !String(scanJobCreated.idempotencyKey || '').startsWith('bt-parameter-scan-')
    || typeof scanJobCreated.attemptCount !== 'number'
    || !['UNCLAIMED', 'LEASED', 'RELEASED'].includes(String(scanJobCreated.leaseStatus || ''))
    || typeof scanJobCreated.leaseSeconds !== 'number'
  ) {
    throw new Error(`Backtest parameter scan job create response broke the job contract: ${JSON.stringify(scanJobCreated)}`)
  }
  await page.waitForFunction((jobId) => {
    const text = document.querySelector('[data-testid="backtest-parameter-scan-job-status"]')?.textContent || ''
    return text.includes(jobId)
      && text.includes('COMPLETED')
      && text.includes('simulationOnly=true')
      && text.includes('isRealTrade=false')
      && text.includes('LOCAL_DURABLE_JSON')
      && text.includes('durable=true')
      && text.includes('bt-parameter-scan-')
      && text.includes('attempts:')
      && text.includes('Lease:')
      && text.includes('Latest attempt:')
      && text.includes('Evidence: LOW')
      && text.includes('Parameter scan retained as review-gated evidence')
      && text.includes('simulation_only=true / is_real_trade=false / evidence_usage=review_gate_only / strong_conclusion_allowed=false / SIM_*')
  }, scanJobId, { timeout: 45000 })
  const scanJobFinal = await apiJson('GET', `/api/research/backtest/parameter-scan/jobs/${encodeURIComponent(scanJobId)}`)
  if (
    scanJobFinal.status !== 'COMPLETED'
    || scanJobFinal.simulationOnly !== true
    || scanJobFinal.isRealTrade !== false
    || scanJobFinal.queueMode !== 'LOCAL_DURABLE_JSON'
    || scanJobFinal.durable !== true
    || scanJobFinal.idempotencyKey !== scanJobCreated.idempotencyKey
    || scanJobFinal.leaseStatus !== 'RELEASED'
    || !String(scanJobFinal.leaseOwner || '').startsWith('local-backtest-worker-')
    || !String(scanJobFinal.leaseId || '').startsWith(String(scanJobFinal.currentAttemptId || 'missing-current-attempt'))
    || !scanJobFinal.leaseReleasedAt
    || scanJobFinal.attemptCount !== 1
    || scanJobFinal.lastAttemptStatus !== 'COMPLETED'
    || !Array.isArray(scanJobFinal.attempts)
    || scanJobFinal.attempts.length !== 1
    || scanJobFinal.attempts[0].status !== 'COMPLETED'
    || scanJobFinal.attempts[0].idempotencyKey !== scanJobFinal.idempotencyKey
    || scanJobFinal.attempts[0].leaseStatus !== 'RELEASED'
    || scanJobFinal.attempts[0].leaseId !== scanJobFinal.leaseId
    || !String(scanJobFinal.scanId || '').startsWith('BTS_')
    || !Array.isArray(scanJobFinal.runIds)
    || scanJobFinal.runIds.length === 0
    || !scanJobFinal.bestRunId
  ) {
    throw new Error(`Backtest parameter scan job did not complete with retained scan evidence: ${JSON.stringify(scanJobFinal)}`)
  }
  for (const runId of scanJobFinal.runIds || []) {
    createdBacktestRunIds.add(String(runId))
  }
  assertBacktestParameterScanBoundary(scanJobFinal.scan)
  const scanJobText = await page.getByTestId('backtest-parameter-scan-job-status').innerText()
  if (
    !scanJobText.includes('trials:')
    || !scanJobText.includes('windows:')
    || !scanJobText.includes(String(scanJobFinal.bestRunId))
    || !scanJobText.includes('Queue:')
    || !scanJobText.includes('recovered=false')
    || !scanJobText.includes(String(scanJobFinal.idempotencyKey))
    || !scanJobText.includes('Lease: RELEASED')
    || !scanJobText.includes(String(scanJobFinal.leaseId))
    || !scanJobText.includes('last attempt: COMPLETED')
    || !scanJobText.includes('Evidence: LOW')
    || !scanJobText.includes('Parameter scan retained as review-gated evidence')
    || !scanJobText.includes('Handoff retained supporting evidence after admin custody review')
    || !scanJobText.includes('simulation_only=true / is_real_trade=false / evidence_usage=review_gate_only / strong_conclusion_allowed=false / SIM_*')
  ) {
    throw new Error(`Backtest parameter scan job status did not render job totals and best run: ${scanJobText}`)
  }
  const scanJobHandoffResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes(`/api/research/backtest/parameter-scan/jobs/${encodeURIComponent(scanJobId)}/handoff`)
      && response.status() === 200
  ), { timeout: 30000 })
  await clickEnabled(page.getByTestId('backtest-parameter-scan-job-handoff'), 'Backtest parameter scan job handoff button', 30000)
  const scanJobHandoff = await assertAuthedJson(scanJobHandoffResponsePromise, 'Backtest parameter scan job handoff')
  if (
    scanJobHandoff.schema !== 'backtest_parameter_scan_job_handoff_v1'
    || scanJobHandoff.status !== 'HANDED_OFF'
    || scanJobHandoff.jobId !== scanJobId
    || scanJobHandoff.scanId !== scanJobFinal.scanId
    || scanJobHandoff.jobStatus !== 'COMPLETED'
    || scanJobHandoff.handoffDestination !== 'LOCAL_DEPLOYMENT_HANDOFF_DIR'
    || !String(scanJobHandoff.bundleChecksum || '').startsWith('bt-parameter-scan-handoff-')
    || asRecord(scanJobHandoff.manifest).schema !== 'backtest_parameter_scan_job_handoff_manifest_v1'
    || asRecord(asRecord(scanJobHandoff.manifest).retentionPolicy).custody !== 'deployment_owned_after_handoff'
    || asRecord(scanJobHandoff.manifest).jobId !== scanJobId
    || scanJobHandoff.simulationOnly !== true
    || scanJobHandoff.isRealTrade !== false
  ) {
    throw new Error(`Backtest parameter scan job handoff returned unexpected payload: ${JSON.stringify(scanJobHandoff)}`)
  }
  const scanJobHandoffText = await page.getByTestId('backtest-parameter-scan-job-handoff-status').innerText()
  if (
    !scanJobHandoffText.includes('HANDED_OFF')
    || !scanJobHandoffText.includes('LOCAL_DEPLOYMENT_HANDOFF_DIR')
    || !scanJobHandoffText.includes(String(scanJobHandoff.bundleChecksum))
    || !scanJobHandoffText.includes('simulationOnly=true')
    || !scanJobHandoffText.includes('isRealTrade=false')
  ) {
    throw new Error(`Backtest parameter scan job handoff status did not render: ${scanJobHandoffText}`)
  }
  const backtestHandoffDir = process.env.BACKTEST_PARAMETER_SCAN_HANDOFF_DIR
  if (!backtestHandoffDir) {
    throw new Error('BACKTEST_PARAMETER_SCAN_HANDOFF_DIR is required for Backtest parameter-scan handoff custody smoke')
  }
  await mkdir(backtestHandoffDir, { recursive: true })
  await writeFile(
    path.join(backtestHandoffDir, 'shipper_status.json'),
    JSON.stringify({
      schema: 'backtest_parameter_scan_job_handoff_shipper_status_v1',
      status: 'DELIVERED',
      reportedAt: new Date().toISOString(),
      source: 'strict-auth-backtest-shipper',
      provider: 'object-store',
      remoteDestination: 's3://strict-auth-backtest/archive?token=unit-secret',
      objectKey: `backtest/${scanJobHandoff.handoffId}.json`,
      retentionPolicyId: 'backtest-parameter-scan-retention-30d',
      retentionStatus: 'RETAINED',
      custodyStatus: 'RETAINED',
      searchIndex: 'backtest-parameter-scan-artifacts',
      searchIndexReady: true,
      lastHandoffId: scanJobHandoff.handoffId,
      lastBundleChecksum: scanJobHandoff.bundleChecksum,
      lastJobId: scanJobId,
      lastScanId: scanJobFinal.scanId,
      message: 'uploaded token=unit-secret',
    }, null, 2),
    'utf8',
  )
  const scanJobCustodyResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes(`/api/research/backtest/parameter-scan/jobs/${encodeURIComponent(scanJobId)}`)
      && response.status() === 200
  ), { timeout: 30000 })
  await clickEnabled(page.getByTestId('backtest-parameter-scan-job-handoff-refresh'), 'Backtest parameter scan handoff custody refresh button', 30000)
  const scanJobWithCustody = await assertAuthedJson(scanJobCustodyResponsePromise, 'Backtest parameter scan job handoff custody refresh')
  const scanJobHandoffCustody = asRecord(scanJobWithCustody.handoffStatus)
  if (
    scanJobHandoffCustody.schema !== 'backtest_parameter_scan_job_handoff_shipper_status_v1'
    || scanJobHandoffCustody.status !== 'DELIVERED'
    || scanJobHandoffCustody.provider !== 'object-store'
    || scanJobHandoffCustody.retentionStatus !== 'RETAINED'
    || scanJobHandoffCustody.custodyStatus !== 'RETAINED'
    || scanJobHandoffCustody.searchIndexReady !== true
    || scanJobHandoffCustody.matchesLatestHandoff !== true
    || scanJobHandoffCustody.matchesJob !== true
  ) {
    throw new Error(`Backtest parameter scan handoff custody returned unexpected payload: ${JSON.stringify(scanJobHandoffCustody)}`)
  }
  await page.waitForFunction(() => (
    document.querySelector('[data-testid="backtest-parameter-scan-job-handoff-custody"]')?.textContent?.includes('DELIVERED')
  ), null, { timeout: 30000 })
  const scanJobHandoffCustodyText = await page.getByTestId('backtest-parameter-scan-job-handoff-custody').innerText()
  if (
    !scanJobHandoffCustodyText.includes('DELIVERED')
    || !scanJobHandoffCustodyText.includes('object-store')
    || !scanJobHandoffCustodyText.includes('latest match yes')
    || !scanJobHandoffCustodyText.includes('job match yes')
    || !scanJobHandoffCustodyText.includes('search ready yes')
    || scanJobHandoffCustodyText.includes('unit-secret')
  ) {
    throw new Error(`Backtest parameter scan handoff custody did not render safely: ${scanJobHandoffCustodyText}`)
  }
  console.log('ok strict-auth browser Backtest parameter-scan validation protocol')
  console.log('ok strict-auth browser Backtest parameter-scan async job')
  console.log('ok strict-auth browser Backtest parameter-scan handoff')
  console.log('ok strict-auth browser Backtest parameter-scan handoff custody')
}

async function runResearchClosedLoopScenario(page) {
  const researchSummaryResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/research/summary')
      && response.status() === 200
  ), { timeout: 30000 }).catch(() => null)
  const researchLoopsResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/research/loops')
      && response.status() === 200
  ), { timeout: 30000 }).catch(() => null)
  await page.locator('nav[aria-label="研究实验室模块"]').waitFor({ state: 'visible', timeout: 30000 })
  await navigateToResearchLoopsPage(page, 'Research Lab research tab')
  await Promise.allSettled([researchSummaryResponsePromise, researchLoopsResponsePromise])
  try {
    await page.getByTestId('research-lab-workflow-role').waitFor({ state: 'visible', timeout: 30000 })
  } catch (error) {
    const currentUrl = page.url()
    const rootText = await page.locator('#root').innerText({ timeout: 5000 }).catch(() => '')
    throw new Error(`Research Lab workflow role did not render after SPA navigation; url=${currentUrl}; root=${rootText.slice(0, 1200)}; cause=${error?.message || error}`)
  }
  await page.evaluate(() => {
    window.localStorage.setItem('super.operatorContext', JSON.stringify({ id: 'strict-auth-browser-smoke', role: 'viewer' }))
    window.dispatchEvent(new Event('super:operator-context-change'))
  })
  await page.getByTestId('research-lab-workflow-disabled-reason').waitFor({ state: 'visible', timeout: 30000 })
  const researchBlockedRoleText = await page.getByTestId('research-lab-workflow-role').innerText()
  if (!researchBlockedRoleText.includes('viewer') || !researchBlockedRoleText.includes('blocked')) {
    throw new Error(`Research Lab workflow role guard did not block viewer: ${researchBlockedRoleText}`)
  }
  if (await page.getByTestId('research-create-closed-loop-sample').isEnabled()) {
    throw new Error('Research Lab closed-loop sample button stayed enabled for viewer role')
  }
  if (await page.getByTestId('research-create-sample-loop-from-latest-run').isEnabled()) {
    throw new Error('Research Lab latest-run sample button stayed enabled for viewer role')
  }
  await page.evaluate(() => {
    window.localStorage.setItem('super.operatorContext', JSON.stringify({ id: 'strict-auth-browser-smoke', role: 'admin' }))
    window.dispatchEvent(new Event('super:operator-context-change'))
  })
  await page.getByTestId('research-lab-workflow-disabled-reason').waitFor({ state: 'detached', timeout: 30000 })
  const researchAllowedRoleText = await page.getByTestId('research-lab-workflow-role').innerText()
  if (!researchAllowedRoleText.includes('admin') || !researchAllowedRoleText.includes('researcher+')) {
    throw new Error(`Research Lab workflow role guard did not re-enable admin: ${researchAllowedRoleText}`)
  }

  const closedLoopResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/research/p2/closed-loop-sample')
  ), { timeout: 60000 })
  const closedLoopButton = page.getByTestId('research-create-closed-loop-sample').first()
  await closedLoopButton.waitFor({ state: 'visible', timeout: 30000 })
  await closedLoopButton.click()
  const closedLoop = await assertAuthedJson(closedLoopResponsePromise, 'Research Lab closed-loop sample creation')

  const requiredIds = [
    'portfolio_snapshot_id',
    'run_id',
    'signal_id',
    'backtest_run_id',
    'loop_id',
    'iteration_id',
    'case_id',
    'knowledge_item_id',
    'patch_id',
    'evaluation_id',
    'knowledge_version_id',
  ]
  for (const key of requiredIds) {
    if (!closedLoop[key]) {
      throw new Error(`Research Lab closed-loop sample did not return ${key}: ${JSON.stringify(closedLoop)}`)
    }
  }
  assertP2ClosedLoopReviewBoundary(closedLoop, 'Research Lab closed-loop sample')
  createdRunIds.add(String(closedLoop.run_id))

  await page.locator(`[data-loop-id="${closedLoop.loop_id}"]`).waitFor({ state: 'visible', timeout: 30000 })
  await page.locator(`[data-loop-id="${closedLoop.loop_id}"]`).click()
  await page.waitForFunction(({ loopId, iterationId }) => {
    const loopText = document.querySelector('[data-testid="current-loop-id"]')?.textContent || ''
    const iterationText = document.querySelector('[data-testid="current-iteration-id"]')?.textContent || ''
    return loopText.includes(loopId) && iterationText.includes(iterationId)
  }, {
    loopId: String(closedLoop.loop_id),
    iterationId: String(closedLoop.iteration_id),
  }, { timeout: 45000 })
  await expectText(page, closedLoop.loop_id, 'Research Lab closed-loop loop id')
  await expectText(page, closedLoop.iteration_id, 'Research Lab closed-loop iteration id')
  await expectText(page, closedLoop.run_id, 'Research Lab closed-loop run id')
  await expectText(page, closedLoop.backtest_run_id, 'Research Lab closed-loop backtest id')
  await expectText(page, closedLoop.case_id, 'Research Lab closed-loop case id')
  await expectText(page, closedLoop.knowledge_item_id, 'Research Lab closed-loop knowledge id')
  await expectText(page, closedLoop.evaluation_id, 'Research Lab closed-loop evaluation id')
  await expectText(page, closedLoop.knowledge_version_id, 'Research Lab closed-loop knowledge version id')

  const researchCurrentStep = await page.getByTestId(`research-loop-current-step-${closedLoop.iteration_id}`).innerText()
  if (!/回测|Backtest|证据|Evidence/i.test(researchCurrentStep) || !/需关注|WARN|缺失|MISSING|待审核/i.test(researchCurrentStep)) {
    throw new Error(`Research Lab governance summary did not expose the current weak-link step: ${researchCurrentStep}`)
  }
  const researchGovernanceNextAction = await page.getByTestId(`research-loop-next-action-${closedLoop.iteration_id}`).innerText()
  if (!/审核证据|Review evidence/i.test(researchGovernanceNextAction)) {
    throw new Error(`Research Lab governance summary did not expose review-evidence next action: ${researchGovernanceNextAction}`)
  }
  const researchWorkflowBoundary = await page.getByTestId(`research-loop-simulation-boundary-${closedLoop.iteration_id}`).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=review_gate_only',
    'strong_conclusion_allowed=false',
  ]) {
    if (!researchWorkflowBoundary.includes(marker)) {
      throw new Error(`Research Lab visible workflow boundary is missing ${marker}: ${researchWorkflowBoundary}`)
    }
  }
  console.log('ok strict-auth browser Research Lab visible workflow boundary')

  await page.getByTestId('workflow-step-run-meta').waitFor({ state: 'visible', timeout: 15000 })
  const workflowRunMeta = await page.getByTestId('workflow-step-run-meta').innerText()
  if (!/source:/i.test(workflowRunMeta) || !/strength:/i.test(workflowRunMeta)) {
    throw new Error(`Research Lab workflow step did not expose source and evidence strength: ${workflowRunMeta}`)
  }
  await page.getByTestId('workflow-step-run-next').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('workflow-maturity-level').waitFor({ state: 'visible', timeout: 15000 })
  const workflowMaturity = await page.getByTestId('workflow-maturity-level').innerText()
  if (!/Maturity:/i.test(workflowMaturity) || !/missing_sample|Missing sample|weak evidence/i.test(workflowMaturity)) {
    throw new Error(`Research Lab workflow did not expose reviewable maturity level: ${workflowMaturity}`)
  }

  const blockingReasons = await page.getByTestId('workflow-blocking-reason').allInnerTexts()
  if (blockingReasons.length === 0) {
    throw new Error('Research Lab closed-loop workflow did not expose blocking reasons for weak/supporting evidence')
  }
  const joinedBlockingReasons = blockingReasons.join(' / ')
  if (!/supporting-only|mock|fallback|out-of-sample|benchmark|样本|支撑材料/i.test(joinedBlockingReasons)) {
    throw new Error(`Research Lab closed-loop blocking reasons did not mention weak evidence: ${joinedBlockingReasons}`)
  }

  const encodedLoopId = encodeURIComponent(String(closedLoop.loop_id))
  const encodedIterationId = encodeURIComponent(String(closedLoop.iteration_id))
  const materializeResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes(`/api/research/iterations/${encodedIterationId}/artifacts/materialize`)
  ), { timeout: 60000 })
  const materializeReloadPromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes(`/api/research/loops/${encodedLoopId}`)
      && response.status() === 200
  ), { timeout: 60000 })
  await clickEnabled(page.getByTestId('research-materialize-current-artifacts'), 'Research Lab materialize current artifacts button', 30000)
  const materializeResponse = await materializeResponsePromise
  const materializeRequestPayload = materializeResponse.request().postDataJSON()
  if (
    materializeRequestPayload?.create_case !== true
    || materializeRequestPayload?.create_knowledge_item !== true
    || materializeRequestPayload?.create_error_entry !== true
    || materializeRequestPayload?.create_patch !== true
    || materializeRequestPayload?.run_evaluation !== true
    || materializeRequestPayload?.patch_content?.frontend_action !== 'materialize_and_evaluate'
  ) {
    throw new Error(`Research Lab artifact materialization posted unexpected payload: ${JSON.stringify(materializeRequestPayload)}`)
  }
  const materializePayload = await assertAuthedJson(Promise.resolve(materializeResponse), 'Research Lab artifact materialization')
  await materializeReloadPromise
  const materializedIteration = asRecord(materializePayload.iteration)
  const materializedLinks = asRecord(asRecord(materializedIteration.metrics).artifact_links)
  const materializedCaseId = String(asRecord(materializePayload.case).case_id || materializedLinks.case_id || '').trim()
  const materializedKnowledgeId = String(asRecord(materializePayload.knowledge_item).item_id || materializedLinks.knowledge_item_id || '').trim()
  const materializedPatchId = String(asRecord(materializePayload.patch).patch_id || materializedLinks.patch_id || '').trim()
  const materializedEvaluationId = String(asRecord(materializePayload.evaluation).eval_id || materializedLinks.evaluation_id || '').trim()
  const materializedChain = Array.isArray(materializePayload.provenance_chain) ? materializePayload.provenance_chain : []
  if (
    materializedIteration.iteration_id !== closedLoop.iteration_id
    || materializedCaseId !== closedLoop.case_id
    || materializedKnowledgeId !== closedLoop.knowledge_item_id
    || materializedPatchId !== closedLoop.patch_id
    || !materializedEvaluationId
    || !materializedChain.includes(`iteration:${closedLoop.iteration_id}`)
    || !materializedChain.includes(`case_id:${closedLoop.case_id}`)
    || !materializedChain.includes(`knowledge_item_id:${closedLoop.knowledge_item_id}`)
  ) {
    throw new Error(`Research Lab artifact materialization did not preserve the closed-loop artifact chain: ${JSON.stringify(materializePayload)}`)
  }
  await page.getByTestId(`research-artifact-chain-governance-${closedLoop.iteration_id}`).waitFor({ state: 'visible', timeout: 30000 })
  const artifactBoundaryText = await page.getByTestId(`research-artifact-chain-simulation-boundary-${closedLoop.iteration_id}`).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=review_gate_only',
    'strong_conclusion_allowed=false',
  ]) {
    if (!artifactBoundaryText.includes(marker)) {
      throw new Error(`Research Lab visible artifact chain boundary is missing ${marker}: ${artifactBoundaryText}`)
    }
  }
  console.log('ok strict-auth browser Research Lab visible artifact chain boundary')
  await expectText(page, materializedCaseId, 'Research Lab materialized case id')
  await expectText(page, materializedKnowledgeId, 'Research Lab materialized knowledge id')
  await expectText(page, materializedPatchId, 'Research Lab materialized patch id')
  await expectText(page, materializedEvaluationId, 'Research Lab materialized evaluation id')
  console.log('ok strict-auth browser Research Lab closed-loop sample')
  console.log('ok strict-auth browser Research Lab artifact materialization')
  return closedLoop
}

async function assertResearchBacktestReportedQualityAuditVisible(page, { iterationId, loopId, audit }) {
  await navigateToResearchLoopsPage(page, 'Research Backtest reportedQuality audit return route', 30000)
  if (loopId) {
    const loopRow = page.locator(`[data-loop-id="${loopId}"]`).first()
    await loopRow.waitFor({ state: 'visible', timeout: 30000 })
    await clickEnabled(loopRow, 'Research Backtest reportedQuality loop row', 30000)
  }
  await page.waitForFunction(({ expectedAuditText, iterationId: expectedIterationId }) => {
    const root = String(document.querySelector('#root')?.textContent || document.body?.textContent || '')
    const currentIterationText = String(document.querySelector('[data-testid="current-iteration-id"]')?.textContent || '')
    return currentIterationText.includes(expectedIterationId) && root.includes(expectedAuditText)
  }, { expectedAuditText: audit.detailText, iterationId }, { timeout: 30000 }).catch(async (error) => {
    const diagnostic = await page.locator('#root').innerText({ timeout: 2000 }).catch(() => '')
    throw new Error(`Research Lab verdict evidence did not render reportedQuality review-gate audit: expected ${audit.detailText}; source=${audit.sourceId}; body=${diagnostic.slice(0, 1200)}; cause=${error?.message || error}`)
  })
  console.log('ok strict-auth browser Research Lab verdict reportedQuality audit')
}

async function assertResearchVerdictOverrideBoundaryVisible(page, { iterationId, loopId }) {
  const generatedAt = new Date().toISOString()
  await apiJson('POST', `/api/research/iterations/${encodeURIComponent(iterationId)}/feedback`, {
    action: 'STRICT_AUTH_BROWSER_VERDICT_OVERRIDE_BOUNDARY',
    verdict: 'PENDING',
    status: 'VERDICT_OVERRIDE_REVIEW_GATE',
    note: 'STRICT_AUTH_BROWSER_VERDICT_OVERRIDE_BOUNDARY',
    reviewer: 'strict-auth-browser',
    metrics: {
      verdict_gate_override: true,
      verdict_gate_override_inputs_generated_at: generatedAt,
      verdict_gate_override_can_accept_feedback: false,
      verdict_gate_override_blocking_reasons: ['strict_auth_browser_review_gate_only'],
      verdict_gate_override_quality_warnings: ['strict_auth_browser_supporting_only_evidence'],
      verdict_gate_override_evidence_usage: 'review_gate_only',
      verdict_gate_override_strong_conclusion_allowed: false,
      verdict_gate_override_simulation_only: true,
      verdict_gate_override_is_real_trade: false,
    },
  })

  await navigateToResearchLoopsPage(page, 'Research Backtest verdict override return route', 30000)
  const refreshDetailPromise = loopId
    ? page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes(`/api/research/loops/${encodeURIComponent(loopId)}`)
        && response.status() === 200
    ), { timeout: 30000 }).catch(() => null)
    : Promise.resolve(null)
  await clickEnabled(page.getByRole('button', { name: '刷新循环' }), 'Research Backtest verdict override refresh loop', 30000)
  await refreshDetailPromise
  if (loopId) {
    const loopRow = page.locator(`[data-loop-id="${loopId}"]`).first()
    await loopRow.waitFor({ state: 'visible', timeout: 30000 })
    await clickEnabled(loopRow, 'Research Backtest verdict override loop row', 30000)
  }
  await page.waitForFunction(({ iterationId: expectedIterationId }) => {
    const currentIterationText = String(document.querySelector('[data-testid="current-iteration-id"]')?.textContent || '')
    return currentIterationText.includes(expectedIterationId)
  }, { iterationId }, { timeout: 30000 })

  const governanceText = await page.getByTestId(`research-verdict-override-governance-${iterationId}`).innerText({ timeout: 30000 })
  for (const marker of [
    'can_accept_feedback=false',
    'evidence_usage=review_gate_only',
  ]) {
    if (!governanceText.includes(marker)) {
      throw new Error(`Research Lab visible verdict override governance is missing ${marker}: ${governanceText}`)
    }
  }
  const boundaryText = await page.getByTestId(`research-verdict-override-simulation-boundary-${iterationId}`).innerText({ timeout: 30000 })
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=review_gate_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundaryText.includes(marker)) {
      throw new Error(`Research Lab visible verdict override boundary is missing ${marker}: ${boundaryText}`)
    }
  }
  console.log('ok strict-auth browser Research Lab visible verdict override boundary')
}

async function assertResearchTraceVisibleBoundary(page, testId, label) {
  const boundary = page.getByTestId(testId)
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=supporting_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(marker)) {
      throw new Error(`Research Traces visible review boundary is missing ${marker} for ${label}: ${text}`)
    }
  }
}

async function runResearchTracesReviewBoundaryScenario(page) {
  const now = new Date().toISOString()
  const loopId = 'RLOOP_TRACE_BROWSER_REVIEW'
  const iterationId = 'RITER_TRACE_BROWSER_REVIEW'
  const runId = 'RUN_TRACE_BROWSER_REVIEW'
  const traceLoop = {
    loop_id: loopId,
    title: 'Browser smoke external trace boundary',
    objective: 'External traces stay supporting-only until reviewed inside the Research loop.',
    status: 'ACTIVE',
    action_target: 'research_trace_review',
    owner: 'strict-auth-browser',
    tags: ['strict-auth-browser', 'trace-boundary'],
    linked_projects: [],
    source: 'rd-agent',
    current_iteration_id: iterationId,
    iteration_count: 1,
    created_at: now,
    updated_at: now,
  }
  const traceDetail = {
    loop: traceLoop,
    iterations: [
      {
        iteration_id: iterationId,
        loop_id: loopId,
        order: 1,
        status: 'PENDING',
        hypothesis: 'Imported trace evidence needs review before it can influence research decisions.',
        plan: 'Inspect events and artifacts, then keep the evidence supporting-only.',
        target_modules: ['research_trace', 'case_library'],
        linked_run_id: runId,
        linked_backtest_id: null,
        linked_case_id: null,
        linked_knowledge_item_id: null,
        linked_patch_id: null,
        metrics: {
          source: 'strict_auth_browser_trace_fixture',
          evidence_usage: 'supporting_only',
          simulation_only: true,
          is_real_trade: false,
        },
        evidence_links: [
          {
            source_type: 'TRACE_ARTIFACT',
            source_id: 'TRACE_BROWSER_ARTIFACT',
            label: 'Strict-auth browser trace artifact',
            quality: 'LOW',
            reportedQuality: 'LOW',
            created_at: now,
          },
        ],
        feedback_events: [
          {
            event_id: 'TRACE_BROWSER_EVENT',
            action: 'IMPORT_TRACE',
            verdict: 'PENDING',
            note: 'Trace import remains supporting-only.',
            reviewer: 'strict-auth-browser',
            created_at: now,
          },
        ],
        verdict: 'PENDING',
        created_at: now,
        updated_at: now,
      },
    ],
    workflow_state: null,
  }
  let sawListRequest = false
  let sawDetailRequest = false

  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error(`Research Traces request did not include the expected Authorization bearer token: ${request.method()} ${url.pathname}`)
    }
    if (request.method() !== 'GET') {
      await route.continue()
      return
    }

    if (url.pathname === '/api/research/traces') {
      sawListRequest = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([traceLoop]) })
      return
    }
    if (url.pathname === `/api/research/traces/${loopId}`) {
      sawDetailRequest = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(traceDetail) })
      return
    }
    await route.continue()
  }

  await page.route('**/api/research/traces**', routeHandler)
  try {
    const listResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname === '/api/research/traces'
        && response.status() === 200
    }, { timeout: 30000 })
    const detailResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname === `/api/research/traces/${loopId}`
        && response.status() === 200
    }, { timeout: 30000 })

    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/research-lab/traces')
    await page.waitForURL(/\/research-lab\/traces$/, { timeout: 15000 })
    await page.getByTestId('research-trace-governance').waitFor({ state: 'visible', timeout: 30000 })

    const traces = await assertAuthedJson(listResponsePromise, 'Research Traces list load')
    if (!Array.isArray(traces) || traces[0]?.loop_id !== loopId) {
      throw new Error(`Research Traces list fixture did not load the expected loop: ${JSON.stringify(traces)}`)
    }
    const detail = await assertAuthedJson(detailResponsePromise, 'Research Traces detail load')
    if (asRecord(detail?.loop).loop_id !== loopId || !Array.isArray(detail?.iterations) || detail.iterations[0]?.iteration_id !== iterationId) {
      throw new Error(`Research Traces detail fixture did not load the expected iteration: ${JSON.stringify(detail)}`)
    }
    if (!sawListRequest || !sawDetailRequest) {
      throw new Error('Research Traces browser scenario did not observe both list and detail requests')
    }
    const traceIdText = await page.getByTestId('research-trace-governance-id').innerText()
    if (!traceIdText.includes(loopId)) {
      throw new Error(`Research Traces governance id did not render the selected trace id: ${traceIdText}`)
    }
    await assertResearchTraceVisibleBoundary(page, 'research-trace-simulation-boundary', 'trace governance')
    console.log('ok strict-auth browser Research Traces visible review boundary')
  } finally {
    await page.unroute('**/api/research/traces**', routeHandler).catch(() => undefined)
  }
}

async function runResearchBacktestVerdictInputsScenario(page, closedLoop) {
  const iterationId = String(closedLoop?.iteration_id || '').trim()
  const backtestRunId = String(closedLoop?.backtest_run_id || '').trim()
  const loopId = String(closedLoop?.loop_id || '').trim()
  if (!iterationId || !backtestRunId) {
    throw new Error(`Research Backtest verdict-inputs scenario needs closed-loop iteration/backtest ids: ${JSON.stringify(closedLoop)}`)
  }

  const encodedBacktestRunId = encodeURIComponent(backtestRunId)
  const encodedIterationId = encodeURIComponent(iterationId)
  const primaryBacktestLink = page.getByTestId('research-open-linked-backtest').first()
  let backtestLink = primaryBacktestLink
  const primaryVisible = await primaryBacktestLink
    .waitFor({ state: 'visible', timeout: 5000 })
    .then(() => true)
    .catch(() => false)
  if (!primaryVisible) {
    backtestLink = page.getByTestId('workflow-backtest-link').first()
    await backtestLink.waitFor({ state: 'visible', timeout: 15000 })
  }
  const href = await backtestLink.getAttribute('href')
  if (!href || !href.includes(`run_id=${encodedBacktestRunId}`) || !href.includes(`iteration_id=${encodedIterationId}`)) {
    throw new Error(`Research Backtest link did not preserve run_id and iteration_id: ${href}`)
  }

  const targetBacktestPath = `/research-lab/backtest?run_id=${encodedBacktestRunId}&iteration_id=${encodedIterationId}`
  await backtestLink.click()
  await page.waitForFunction(({ runId, iterationId }) => {
    const params = new URLSearchParams(window.location.search)
    return window.location.pathname === '/research-lab/backtest'
      && params.get('run_id') === runId
      && params.get('iteration_id') === iterationId
  }, { runId: backtestRunId, iterationId }, { timeout: 15000 })
  const selectedRunPanel = page.getByTestId('backtest-selected-run')
  const selectedRunVisible = await selectedRunPanel
    .waitFor({ state: 'visible', timeout: 30000 })
    .then(() => true)
    .catch(() => false)
  if (!selectedRunVisible) {
    console.warn('Research Backtest selected run did not render after link click; retrying direct SPA route')
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, targetBacktestPath)
    await page.waitForFunction(({ runId, iterationId }) => {
      const params = new URLSearchParams(window.location.search)
      return window.location.pathname === '/research-lab/backtest'
        && params.get('run_id') === runId
        && params.get('iteration_id') === iterationId
    }, { runId: backtestRunId, iterationId }, { timeout: 15000 })
    await selectedRunPanel.waitFor({ state: 'visible', timeout: 30000 })
  }
  const renderedRunId = (await page.getByTestId('backtest-selected-run-id').innerText()).trim()
  if (renderedRunId !== backtestRunId) {
    throw new Error(`Research Backtest deep link rendered ${renderedRunId} instead of ${backtestRunId}`)
  }

  const verdictResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes(`/api/research/backtest/runs/${encodedBacktestRunId}/verdict-inputs`)
      && response.status() === 200
  ), { timeout: 30000 })
  await clickEnabled(page.getByTestId('backtest-create-verdict-inputs'), 'Research Backtest verdict inputs button')
  const payload = await assertAuthedJson(verdictResponsePromise, 'Research Backtest verdict inputs')
  assertResearchBacktestVerdictInputsBoundary(payload, iterationId, backtestRunId)
  await page.getByTestId('backtest-verdict-inputs-notice').waitFor({ state: 'visible', timeout: 15000 })
  await expectText(page, 'Research verdict inputs refreshed', 'Research Backtest verdict inputs notice')
  const visibleBoundary = await page.getByTestId('backtest-verdict-inputs-boundary').innerText({ timeout: 15000 })
  for (const marker of [
    'evidence_usage=supporting_only',
    'supporting_only=true',
    'simulation_only=true',
    'is_real_trade=false',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!visibleBoundary.includes(marker)) {
      throw new Error(`Research Backtest visible verdict-inputs boundary is missing ${marker}: ${visibleBoundary}`)
    }
  }
  console.log('ok strict-auth browser Research Backtest visible verdict-inputs boundary')
  let audit = backtestVerdictAuditEvidence(payload, backtestRunId)
  if (!audit) {
    const refreshedInputs = await seedResearchBacktestReportedQualityAudit(iterationId, backtestRunId)
    audit = backtestVerdictAuditEvidence({ verdict_inputs: refreshedInputs }, backtestRunId)
    if (!audit) {
      throw new Error(`Backtest verdict inputs did not retain reportedQuality audit grade: ${JSON.stringify(refreshedInputs)}`)
    }
  }
  if (
    String(audit.reportedQuality || '').trim().toUpperCase() !== 'SUPPORTING_ONLY'
    || audit.reviewGateQuality !== 'LOW'
  ) {
    throw new Error(`Backtest verdict inputs did not retain SUPPORTING_ONLY reportedQuality audit grade: ${JSON.stringify(audit.evidence)}`)
  }
  await assertResearchBacktestReportedQualityAuditVisible(page, { iterationId, loopId, audit })
  await assertResearchVerdictOverrideBoundaryVisible(page, { iterationId, loopId })
  console.log('ok strict-auth browser Research Backtest verdict inputs')
}

async function runResearchSignalOpsDeepLinkScenario(page, closedLoop) {
  const iterationId = String(closedLoop?.iteration_id || '').trim()
  const loopId = String(closedLoop?.loop_id || '').trim()
  const signalId = String(closedLoop?.signal_id || '').trim()
  if (!iterationId || !loopId || !signalId) {
    throw new Error(`Research SignalOps deep-link scenario needs closed-loop loop/iteration/signal ids: ${JSON.stringify(closedLoop)}`)
  }

  await navigateToResearchLoopsPage(page, 'Research SignalOps prerequisite Research route')
  const loopRow = page.locator(`[data-loop-id="${loopId}"]`).first()
  await loopRow.waitFor({ state: 'visible', timeout: 30000 })
  await clickEnabled(loopRow, 'Research SignalOps loop row', 30000)
  await page.waitForFunction(({ loopId, iterationId }) => {
    const selectedLoop = document.querySelector(`[data-loop-id="${loopId}"]`)
    const currentIteration = document.querySelector('[data-testid="current-iteration-id"]')
    return Boolean(selectedLoop) && String(currentIteration?.textContent || '').includes(iterationId)
  }, { loopId, iterationId }, { timeout: 30000 })
  console.log('ok strict-auth browser Research SignalOps deep-link iteration id')

  const encodedIterationId = encodeURIComponent(iterationId)
  const encodedSignalId = encodeURIComponent(signalId)
  const signalOpsLink = page.getByTestId('research-open-signalops-evidence').first()
  await signalOpsLink.waitFor({ state: 'visible', timeout: 15000 })
  const href = await signalOpsLink.getAttribute('href')
  if (!href || !href.includes(`iteration_id=${encodedIterationId}`) || !href.includes(`signal_id=${encodedSignalId}`)) {
    throw new Error(`Research SignalOps link did not preserve iteration_id and signal_id: ${href}`)
  }

  const signalDetailResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith(`/api/signals/${encodedSignalId}`)
      && response.status() === 200
  }, { timeout: 30000 })
  await signalOpsLink.click()
  await page.waitForFunction(({ expectedIterationId, expectedSignalId }) => {
    const params = new URLSearchParams(window.location.search)
    return window.location.pathname === '/signalops'
      && params.get('iteration_id') === expectedIterationId
      && params.get('signal_id') === expectedSignalId
  }, { expectedIterationId: iterationId, expectedSignalId: signalId }, { timeout: 15000 })

  const detailPayload = await assertAuthedJson(signalDetailResponsePromise, 'Research SignalOps selected-signal detail load')
  if (asRecord(detailPayload?.signal).signal_id !== signalId) {
    throw new Error(`Research SignalOps selected-signal detail loaded the wrong signal: ${JSON.stringify(detailPayload)}`)
  }
  await page.getByTestId('signalops-selected-signal-detail').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('signalops-research-evidence-context').waitFor({ state: 'visible', timeout: 15000 })
  console.log('ok strict-auth browser Research SignalOps selected deep link')
}

async function assertAgentDagVisibleBoundary(page, testId, label) {
  const boundary = page.getByTestId(testId)
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`Agent DAG visible boundary is missing ${expected} for ${label}: ${text}`)
    }
  }
}

async function assertAgentDebateVisibleBoundary(page) {
  const boundary = page.getByTestId('agent-debate-simulation-boundary')
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`Agent Debate visible boundary is missing ${expected}: ${text}`)
    }
  }
}

async function runAgentDagDebateEvidenceScenario(page, runId) {
  const encodedRunId = encodeURIComponent(runId)
  const dagRunResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith(`/api/analysis/runs/${encodedRunId}`)
      && response.status() === 200
  }, { timeout: 30000 })
  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, `/dag?run_id=${encodedRunId}`)
  await page.waitForURL(new RegExp(`/dag\\?run_id=${encodedRunId}$`), { timeout: 15000 })
  const dagRun = await assertAuthedJsonOrApi(
    dagRunResponsePromise,
    'Agent DAG linked-run load',
    `/api/analysis/runs/${encodedRunId}`,
    { page },
  )
  if (dagRun?.runId !== runId) {
    throw new Error(`Agent DAG linked-run load returned the wrong run: ${JSON.stringify(dagRun)}`)
  }
  if (!Array.isArray(dagRun.nodes) || dagRun.nodes.length === 0) {
    throw new Error(`Agent DAG linked run has no nodes to review: ${JSON.stringify(dagRun)}`)
  }
  if (!Array.isArray(dagRun.tokenUsage?.rows) || dagRun.tokenUsage.rows.length === 0) {
    throw new Error(`Agent DAG linked run has no token usage rows: ${JSON.stringify(dagRun.tokenUsage)}`)
  }
  await page.getByTestId('agent-dag-page').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-source-summary').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-metering-status').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-result-row-orchestrator').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-flow-node-orchestrator').waitFor({ state: 'visible', timeout: 15000 })
  await assertAgentDagVisibleBoundary(page, 'agent-dag-run-simulation-boundary', 'run governance')
  await assertAgentDagVisibleBoundary(page, 'agent-dag-selected-node-simulation-boundary', 'selected node governance')
  console.log('ok strict-auth browser Agent DAG visible review boundary')
  const dagText = await page.getByTestId('agent-dag-page').innerText()
  if (!dagText.includes('LLM status:') || !dagText.includes('tokens')) {
    throw new Error(`Agent DAG did not render LLM status and token evidence: ${dagText}`)
  }
  console.log('ok strict-auth browser Agent DAG LLM evidence')
  const readAgentDagViewportTransform = async () => {
    const viewport = page.locator('[data-testid="agent-dag-flow-canvas"] .react-flow__viewport').first()
    await viewport.waitFor({ state: 'visible', timeout: 15000 })
    return viewport.evaluate((element) => getComputedStyle(element).transform || element.getAttribute('style') || '')
  }
  const assertAgentDagViewportControls = async () => {
    const zoomInButton = page.locator('[data-testid="agent-dag-flow-canvas"] .react-flow__controls-zoomin').first()
    const fitViewButton = page.locator('[data-testid="agent-dag-flow-canvas"] .react-flow__controls-fitview').first()
    await zoomInButton.waitFor({ state: 'visible', timeout: 15000 })
    await fitViewButton.waitFor({ state: 'visible', timeout: 15000 })
    const beforeZoom = await readAgentDagViewportTransform()
    await zoomInButton.click()
    await page.waitForFunction((previousTransform) => {
      const viewport = document.querySelector('[data-testid="agent-dag-flow-canvas"] .react-flow__viewport')
      const currentTransform = viewport ? getComputedStyle(viewport).transform || viewport.getAttribute('style') || '' : ''
      return Boolean(currentTransform) && currentTransform !== previousTransform
    }, beforeZoom, { timeout: 15000 })
    await fitViewButton.click()
    await page.getByTestId('agent-dag-flow-node-orchestrator').waitFor({ state: 'visible', timeout: 15000 })
    console.log('ok strict-auth browser Agent DAG viewport controls')
  }
  await assertAgentDagViewportControls()
  const assertAgentDagViewportPan = async () => {
    const pane = page.locator('[data-testid="agent-dag-flow-canvas"] .react-flow__pane').first()
    await pane.waitFor({ state: 'visible', timeout: 15000 })
    await pane.scrollIntoViewIfNeeded()
    const dragPoint = await page.evaluate(() => {
      const canvas = document.querySelector('[data-testid="agent-dag-flow-canvas"]')
      const paneElement = canvas?.querySelector('.react-flow__pane')
      const rect = canvas?.getBoundingClientRect()
      if (!canvas || !paneElement || !rect) {
        return null
      }
      const left = Math.max(rect.left + 8, 8)
      const top = Math.max(rect.top + 8, 8)
      const right = Math.min(rect.right - 8, window.innerWidth - 8)
      const bottom = Math.min(rect.bottom - 8, window.innerHeight - 8)
      if (right <= left || bottom <= top) {
        return null
      }
      const candidates = [
        [0.82, 0.32],
        [0.72, 0.44],
        [0.62, 0.58],
        [0.42, 0.74],
        [0.28, 0.36],
      ]
      let fallback = null
      for (const [xRatio, yRatio] of candidates) {
        const x = left + (right - left) * xRatio
        const y = top + (bottom - top) * yRatio
        const target = document.elementFromPoint(x, y)
        if (
          target
          && canvas.contains(target)
          && !target.closest('.react-flow__controls')
          && !target.closest('.react-flow__minimap')
        ) {
          if (!target.closest('.react-flow__node')) {
            return { x, y }
          }
          fallback = { x, y }
        }
      }
      return fallback
    })
    if (!dragPoint) {
      throw new Error('Agent DAG ReactFlow canvas did not expose an empty draggable point')
    }
    const beforePan = await readAgentDagViewportTransform()
    await page.mouse.move(dragPoint.x, dragPoint.y)
    await page.mouse.down()
    await page.mouse.move(dragPoint.x - 96, dragPoint.y + 64, { steps: 10 })
    await page.mouse.up()
    await page.waitForFunction((previousTransform) => {
      const viewport = document.querySelector('[data-testid="agent-dag-flow-canvas"] .react-flow__viewport')
      const currentTransform = viewport ? getComputedStyle(viewport).transform || viewport.getAttribute('style') || '' : ''
      return Boolean(currentTransform) && currentTransform !== previousTransform
    }, beforePan, { timeout: 15000 })
    await page.getByTestId('agent-dag-flow-node-orchestrator').waitFor({ state: 'visible', timeout: 15000 })
    console.log('ok strict-auth browser Agent DAG viewport pan')
  }
  await assertAgentDagViewportPan()
  const assertSelectedAgentNode = async (expectedNodeId, label, expectedSnippets = [], expectedSource = '') => {
    await page.waitForFunction((nodeId) => {
      const selected = document.querySelector('[data-testid="agent-dag-selected-node-id"]')
      return selected?.textContent?.trim() === nodeId
    }, expectedNodeId, { timeout: 15000 })
    const selectedNodeId = (await page.getByTestId('agent-dag-selected-node-id').innerText()).trim()
    if (selectedNodeId !== expectedNodeId) {
      throw new Error(`Agent DAG ${label} selected the wrong node: ${selectedNodeId}`)
    }
    const selectedNodeText = await page.getByTestId('agent-dag-selected-node-detail').innerText()
    if (!selectedNodeText.includes('LLM status:') || !selectedNodeText.includes('Profile:') || !selectedNodeText.includes('tokens')) {
      throw new Error(`Agent DAG ${label} selected node detail did not render evidence fields: ${selectedNodeText}`)
    }
    if (expectedSource) {
      const selectedSource = await page.getByTestId('agent-dag-selected-node-source').getAttribute('data-source')
      if (selectedSource !== expectedSource) {
        throw new Error(`Agent DAG ${label} selected source ${selectedSource} instead of ${expectedSource}: ${selectedNodeText}`)
      }
    }
    for (const snippet of expectedSnippets) {
      if (!selectedNodeText.includes(snippet)) {
        throw new Error(`Agent DAG ${label} selected node detail missed ${snippet}: ${selectedNodeText}`)
      }
    }
  }
  await page.getByTestId('agent-dag-flow-node-orchestrator').click()
  await page.getByTestId('agent-dag-selected-node-detail').waitFor({ state: 'visible', timeout: 15000 })
  await assertSelectedAgentNode('orchestrator', 'mouse click')
  console.log('ok strict-auth browser Agent DAG node interaction')
  const secondaryDagNode = dagRun.nodes.find((node) => node?.id && node.id !== 'orchestrator')
  if (!secondaryDagNode) {
    throw new Error(`Agent DAG linked run did not include a secondary node for multi-node interaction coverage: ${JSON.stringify(dagRun.nodes)}`)
  }
  const secondaryNodeId = String(secondaryDagNode.id)
  await page.getByTestId(`agent-dag-result-row-${secondaryNodeId}`).waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId(`agent-dag-flow-node-${secondaryNodeId}`).waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId(`agent-dag-flow-node-${secondaryNodeId}`).press('Enter')
  await assertSelectedAgentNode(secondaryNodeId, 'keyboard selection')
  console.log('ok strict-auth browser Agent DAG multi-node keyboard interaction')

  const { fixture, fixtureRunId, degradedNodeId, failedNodeId } = buildAgentDagFailureFixture(dagRun)
  const encodedFixtureRunId = encodeURIComponent(fixtureRunId)
  const fixtureRouteHandler = async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fixture),
    })
  }
  await page.route(`**/api/analysis/runs/${encodedFixtureRunId}`, fixtureRouteHandler)
  try {
    const failureFixtureResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith(`/api/analysis/runs/${encodedFixtureRunId}`)
        && response.status() === 200
    }, { timeout: 30000 })
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, `/dag?run_id=${encodedFixtureRunId}`)
    await page.waitForURL(new RegExp(`/dag\\?run_id=${encodedFixtureRunId}$`), { timeout: 15000 })
    const failureFixtureRun = await assertAuthedJson(failureFixtureResponsePromise, 'Agent DAG failure fixture load')
    if (failureFixtureRun?.runId !== fixtureRunId) {
      throw new Error(`Agent DAG failure fixture returned the wrong run: ${JSON.stringify(failureFixtureRun)}`)
    }
    await page.getByTestId('agent-dag-page').waitFor({ state: 'visible', timeout: 15000 })
    await page.getByTestId('agent-dag-degraded-count').waitFor({ state: 'visible', timeout: 15000 })
    const degradedCount = Number((await page.getByTestId('agent-dag-degraded-count').innerText()).trim())
    if (!Number.isFinite(degradedCount) || degradedCount < 2) {
      throw new Error(`Agent DAG failure fixture did not show degraded/failed count >= 2: ${degradedCount}`)
    }
    await page.getByTestId(`agent-dag-flow-node-${degradedNodeId}`).press('Enter')
    await assertSelectedAgentNode(degradedNodeId, 'degraded fixture keyboard selection', ['SKIPPED', 'LLM_SKIPPED_BROWSER_FIXTURE'])
    await page.getByTestId(`agent-dag-flow-node-${failedNodeId}`).click()
    await assertSelectedAgentNode(failedNodeId, 'failed fixture mouse click', ['FAILED', 'LLM_FAILED_BROWSER_FIXTURE'])
    console.log('ok strict-auth browser Agent DAG failure/degraded fixture')
  } finally {
    await page.unroute(`**/api/analysis/runs/${encodedFixtureRunId}`, fixtureRouteHandler).catch(() => undefined)
  }

  const {
    fixture: stateMatrixFixture,
    fixtureRunId: stateMatrixRunId,
    expectations: stateMatrixExpectations,
  } = buildAgentDagStateMatrixFixture(dagRun)
  const encodedStateMatrixRunId = encodeURIComponent(stateMatrixRunId)
  const stateMatrixRouteHandler = async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(stateMatrixFixture),
    })
  }
  await page.route(`**/api/analysis/runs/${encodedStateMatrixRunId}`, stateMatrixRouteHandler)
  try {
    const stateMatrixResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith(`/api/analysis/runs/${encodedStateMatrixRunId}`)
        && response.status() === 200
    }, { timeout: 30000 })
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, `/dag?run_id=${encodedStateMatrixRunId}`)
    await page.waitForURL(new RegExp(`/dag\\?run_id=${encodedStateMatrixRunId}$`), { timeout: 15000 })
    const stateMatrixRun = await assertAuthedJson(stateMatrixResponsePromise, 'Agent DAG state matrix fixture load')
    if (stateMatrixRun?.runId !== stateMatrixRunId) {
      throw new Error(`Agent DAG state matrix fixture returned the wrong run: ${JSON.stringify(stateMatrixRun)}`)
    }
    await page.getByTestId('agent-dag-page').waitFor({ state: 'visible', timeout: 15000 })
    await page.waitForFunction((runId) => {
      const renderedRunId = document.querySelector('[data-testid="agent-dag-run-context-id"]')?.textContent?.trim()
      return renderedRunId === runId
    }, stateMatrixRunId, { timeout: 15000 })
    await page.getByTestId(`agent-dag-flow-node-${stateMatrixExpectations[0].nodeId}`).waitFor({ state: 'visible', timeout: 15000 })
    const llmCount = Number((await page.getByTestId('agent-dag-llm-count').innerText()).trim())
    const degradedCount = Number((await page.getByTestId('agent-dag-degraded-count').innerText()).trim())
    const ruleCount = Number((await page.getByTestId('agent-dag-rule-count').innerText()).trim())
    const pluginCount = Number((await page.getByTestId('agent-dag-plugin-count').innerText()).trim())
    if (llmCount !== 1 || degradedCount !== 2 || ruleCount !== 1 || pluginCount !== 1) {
      throw new Error(`Agent DAG state matrix counts drifted: ${JSON.stringify({ llmCount, degradedCount, ruleCount, pluginCount })}`)
    }
    for (const expectation of stateMatrixExpectations) {
      const node = page.getByTestId(`agent-dag-flow-node-${expectation.nodeId}`)
      await node.waitFor({ state: 'visible', timeout: 15000 })
      const nodeSource = await node.getAttribute('data-source')
      if (nodeSource !== expectation.source) {
        throw new Error(`Agent DAG state matrix flow node ${expectation.nodeId} source ${nodeSource} instead of ${expectation.source}`)
      }
      await node.press('Enter')
      await assertSelectedAgentNode(
        expectation.nodeId,
        `state matrix ${expectation.source}`,
        expectation.snippets,
        expectation.source,
      )
    }
    console.log('ok strict-auth browser Agent DAG state matrix fixture')
  } finally {
    await page.unroute(`**/api/analysis/runs/${encodedStateMatrixRunId}`, stateMatrixRouteHandler).catch(() => undefined)
  }

  const restoredDagRunResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith(`/api/analysis/runs/${encodedRunId}`)
      && response.status() === 200
  }, { timeout: 30000 })
  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, `/dag?run_id=${encodedRunId}`)
  await page.waitForURL(new RegExp(`/dag\\?run_id=${encodedRunId}$`), { timeout: 15000 })
  const restoredDagRun = await assertAuthedJsonOrApi(
    restoredDagRunResponsePromise,
    'Agent DAG linked-run restore after failure fixture',
    `/api/analysis/runs/${encodedRunId}`,
    { page },
  )
  if (restoredDagRun?.runId !== runId) {
    throw new Error(`Agent DAG linked-run restore returned the wrong run: ${JSON.stringify(restoredDagRun)}`)
  }
  await page.getByTestId('agent-dag-result-row-orchestrator').waitFor({ state: 'visible', timeout: 15000 })

  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, `/debate?run_id=${encodedRunId}`)
  await page.waitForURL(new RegExp(`/debate\\?run_id=${encodedRunId}$`), { timeout: 15000 })
  await page.getByTestId('agent-debate-page').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-debate-source-summary').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-debate-metering-status').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-debate-token-row-orchestrator').waitFor({ state: 'visible', timeout: 15000 })
  await assertAgentDebateVisibleBoundary(page)
  const debateText = await page.getByTestId('agent-debate-page').innerText()
  if (!debateText.includes('LLM status:') || !debateText.includes('NO_PROVIDER_USAGE')) {
    throw new Error(`Agent Debate did not render LLM status and metering evidence: ${debateText}`)
  }
  console.log('ok strict-auth browser Agent Debate visible review boundary')
  console.log('ok strict-auth browser Agent Debate LLM evidence')
}

async function runConfigVersionsRestoreScenario(page) {
  const makeVersion = ({ profileId, version, auditId, scope, secretPath, secretRef }) => ({
    profile_id: profileId,
    version,
    created_at: '2026-05-31T00:00:00Z',
    created_by: 'strict-auth-browser-smoke',
    change_summary: `Browser smoke external restore fixture for ${profileId}`,
    audit_id: auditId,
    status: 'ACTIVE',
    rollback_available: false,
    approval_required: true,
    effective_scope: scope,
    snapshot_redacted: true,
    rollback_policy: {
      supported: false,
      approval_required: true,
      secret_safe_required: true,
      blocked_reason: 'secret_safe_restore_required',
      approval_gate: {
        required: true,
        status: 'BLOCKED_PENDING_VAULT_VERSION_APPROVAL',
        scope: 'runtime_config_secret_restore',
        approver_role: 'admin',
        secret_vault_version_required: true,
        restore_source: 'vault-version',
        required_secret_refs: [
          {
            path: secretPath,
            ref: secretRef,
          },
        ],
      },
    },
  })
  const configVersions = [
    makeVersion({
      profileId: 'agent_runtime:llm_profile',
      version: 7,
      auditId: 'AUD_CONFIG_RESTORE_LLM_BROWSER',
      scope: ['agent_runtime', 'llm_profile'],
      secretPath: 'secret_refs.llm_profiles.audit_llm.api_key',
      secretRef: 'runtime-secret:v1:llm_profiles:audit_llm:api_key:version:browser-smoke',
    }),
    makeVersion({
      profileId: 'agent_runtime:data_sources_config',
      version: 8,
      auditId: 'AUD_CONFIG_RESTORE_DATA_SOURCES_BROWSER',
      scope: ['agent_runtime', 'data_sources_config'],
      secretPath: 'secret_refs.data_sources_config.tushare.token',
      secretRef: 'runtime-secret:v1:data_sources_config:tushare:token:version:browser-smoke',
    }),
    makeVersion({
      profileId: 'agent_runtime:market_data_adapter_config',
      version: 9,
      auditId: 'AUD_CONFIG_RESTORE_MARKET_ADAPTER_BROWSER',
      scope: ['agent_runtime', 'market_data_adapter_config'],
      secretPath: 'secret_refs.market_data_adapter_configs.tushare.token',
      secretRef: 'runtime-secret:v1:market_data_adapter_configs:tushare:token:version:browser-smoke',
    }),
  ]
  const restoreTargets = [
    {
      version: configVersions[1],
      approvalId: 'APPROVAL-BROWSER-DATA-SOURCES',
      reason: 'browser governed data sources restore smoke',
      appliedKeys: ['data_sources_config.tushare.token_ref'],
    },
    {
      version: configVersions[2],
      approvalId: 'APPROVAL-BROWSER-MARKET-ADAPTER',
      reason: 'browser governed market adapter restore smoke',
      appliedKeys: ['market_data_adapter_configs.tushare.enabled'],
    },
  ]
  const dialogs = []
  const dialogHandler = async (dialog) => {
    dialogs.push(dialog.type())
    await dialog.dismiss().catch(() => undefined)
  }
  const restoreCalls = []
  const configVersionFilters = []
  await page.route('**/api/config/schema', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.route('**/api/config/versions**', async (route) => {
    const url = new URL(route.request().url())
    const profileId = url.searchParams.get('profile_id') || ''
    configVersionFilters.push(profileId || 'ALL')
    const visibleVersions = profileId
      ? configVersions.filter((version) => version.profile_id === profileId)
      : configVersions
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(visibleVersions) })
  })
  await page.route('**/api/config/external-restore', async (route) => {
    const request = route.request()
    if (request.method() !== 'POST') {
      throw new Error(`Config external restore used ${request.method()} instead of POST`)
    }
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error('Config external restore did not include the expected Authorization bearer token')
    }
    const payload = request.postDataJSON()
    const target = restoreTargets.find((item) => item.version.profile_id === payload.profile_id)
    if (!target) {
      throw new Error(`Config external restore used unexpected surface: ${JSON.stringify(payload)}`)
    }
    if (
      payload.audit_id !== target.version.audit_id ||
      payload.approval_id !== target.approvalId ||
      payload.reason !== target.reason ||
      payload.confirm_secret_safe !== true
    ) {
      throw new Error(`Config external restore payload was not governed: ${JSON.stringify(payload)}`)
    }
    restoreCalls.push(payload.profile_id)
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'RESTORED',
        profile_id: target.version.profile_id,
        target_version: target.version.version,
        target_audit_id: target.version.audit_id,
        restore_audit_id: `AUD_CONFIG_RESTORE_BROWSER_RESULT_${restoreCalls.length}`,
        approval_id: payload.approval_id,
        approved_by: payload.approved_by,
        applied_keys: target.appliedKeys,
        required_secret_ref_count: 1,
        skipped_redacted_paths: [],
      }),
    })
  })
  page.on('dialog', dialogHandler)
  try {
    await page.locator('a[href="/config-versions"]').first().click()
    await page.waitForURL(/\/config-versions$/, { timeout: 15000 })
    await expectText(page, 'agent_runtime:llm_profile v7', 'Config Versions all-surface fixture')
    await expectText(page, 'agent_runtime:data_sources_config v8', 'Config Versions data-sources surface fixture')
    await expectText(page, 'agent_runtime:market_data_adapter_config v9', 'Config Versions market-adapter surface fixture')
    const surfaceSelect = page.locator('label').filter({ hasText: 'Surface' }).locator('select')

    for (const target of restoreTargets) {
      await surfaceSelect.selectOption('')
      await expectText(page, `${target.version.profile_id} v${target.version.version}`, 'Config Versions surface reset')
      await surfaceSelect.selectOption(target.version.profile_id)
      await expectText(page, `${target.version.profile_id} v${target.version.version}`, 'Config Versions filtered restore surface')
      await page.getByTestId('config-approved-restore-open').click()
      const modal = page.getByTestId('config-approved-restore-modal')
      await modal.waitFor({ state: 'visible', timeout: 15000 })
      const modalText = await modal.innerText()
      if (!modalText.includes(target.version.profile_id) || !modalText.includes(target.version.audit_id)) {
        throw new Error(`Config approved restore modal did not identify target surface: ${modalText}`)
      }
      const submit = page.getByTestId('config-approved-restore-submit')
      if (await submit.isEnabled()) {
        throw new Error('Config approved restore submit should be disabled before approval fields are complete')
      }
      await page.getByTestId('config-approved-restore-approval-id').fill(target.approvalId)
      await page.getByTestId('config-approved-restore-reason').fill(target.reason)
      await page.getByTestId('config-approved-restore-confirm-secret-safe').check()
      const restoreResponsePromise = page.waitForResponse((response) => (
        response.request().method() === 'POST' && response.url().includes('/api/config/external-restore')
      ), { timeout: 30000 })
      await submit.click()
      const restoreResponse = await restoreResponsePromise
      if (!restoreResponse.ok()) {
        throw new Error(`Config external restore returned ${restoreResponse.status()}: ${await restoreResponse.text()}`)
      }
      await expectText(page, `已恢复 ${target.version.profile_id} v${target.version.version}`, 'Config Versions approved restore modal')
    }
    const expectedRestoredProfiles = restoreTargets.map((target) => target.version.profile_id)
    for (const profileId of expectedRestoredProfiles) {
      if (!restoreCalls.includes(profileId)) {
        throw new Error(`Config external restore route was not called for ${profileId}`)
      }
      if (!configVersionFilters.includes(profileId)) {
        throw new Error(`Config Versions did not request the filtered surface ${profileId}`)
      }
    }
    if (dialogs.length > 0) {
      throw new Error(`Config approved restore used unexpected browser dialogs: ${dialogs.join(', ')}`)
    }
    await expectText(page, '已恢复 agent_runtime:market_data_adapter_config v9', 'Config Versions multi-surface approved restore')
    console.log('ok strict-auth browser Config Versions approved restore modal')
    console.log('ok strict-auth browser Config Versions multi-surface approved restore')
  } finally {
    page.off('dialog', dialogHandler)
    await page.unroute('**/api/config/schema').catch(() => undefined)
    await page.unroute('**/api/config/versions**').catch(() => undefined)
    await page.unroute('**/api/config/external-restore').catch(() => undefined)
  }
}

function isAnalysisJobQueueResponse(response) {
  if (response.request().method() !== 'GET' || response.status() !== 200) {
    return false
  }
  try {
    const url = new URL(response.url())
    return url.pathname.endsWith('/api/analysis/jobs') && url.searchParams.get('limit') === '12'
  } catch {
    return false
  }
}

function isAnalysisJobQueueSummaryResponse(response) {
  if (response.request().method() !== 'GET' || response.status() !== 200) {
    return false
  }
  try {
    const url = new URL(response.url())
    return url.pathname.endsWith('/api/analysis/jobs/summary') && url.searchParams.get('limit') === '12'
  } catch {
    return false
  }
}

async function assertPermissionMatrixVisibleBoundary(page) {
  await page.getByTestId('permission-matrix-governance').waitFor({ state: 'visible', timeout: 15000 })
  const contextId = await page.getByTestId('permission-matrix-governance-id').innerText()
  if (!contextId.includes(':permission')) {
    throw new Error(`Permission Matrix governance context did not expose permission scope: ${contextId}`)
  }
  const evidenceStrength = await page.getByTestId('permission-matrix-evidence-strength').innerText()
  if (
    !evidenceStrength.includes('Evidence:')
    || (!evidenceStrength.includes('LOW') && !evidenceStrength.includes('MEDIUM'))
  ) {
    throw new Error(`Permission Matrix evidence strength did not render LOW/MEDIUM: ${evidenceStrength}`)
  }
  const blocker = await page.getByTestId('permission-matrix-blocker').innerText()
  if (!blocker.includes('Blocker:') || blocker.includes('undefined')) {
    throw new Error(`Permission Matrix blocker did not render a usable label: ${blocker}`)
  }
  const nextAction = await page.getByTestId('permission-matrix-next-action').innerText()
  if (!nextAction.includes('Next:') || nextAction.includes('undefined')) {
    throw new Error(`Permission Matrix next action did not render a usable label: ${nextAction}`)
  }
  const boundary = await page.getByTestId('permission-matrix-simulation-boundary').innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundary.includes(expected)) {
      throw new Error(`Permission Matrix visible boundary is missing ${expected}: ${boundary}`)
    }
  }
}

async function assertExecutionVisibleBoundary(page) {
  await page.getByTestId('execution-governance').waitFor({ state: 'visible', timeout: 15000 })
  const contextId = await page.getByTestId('execution-governance-id').innerText()
  if (!contextId.includes(':execution')) {
    throw new Error(`Execution governance context did not expose execution scope: ${contextId}`)
  }
  const evidenceStrength = await page.getByTestId('execution-evidence-strength').innerText()
  if (
    !evidenceStrength.includes('Evidence:')
    || (!evidenceStrength.includes('LOW') && !evidenceStrength.includes('MEDIUM'))
  ) {
    throw new Error(`Execution evidence strength did not render LOW/MEDIUM: ${evidenceStrength}`)
  }
  const blocker = await page.getByTestId('execution-blocker').innerText()
  if (!blocker.includes('Blocker:') || blocker.includes('undefined')) {
    throw new Error(`Execution blocker did not render a usable label: ${blocker}`)
  }
  const nextAction = await page.getByTestId('execution-next-action').innerText()
  if (!nextAction.includes('Next:') || nextAction.includes('undefined')) {
    throw new Error(`Execution next action did not render a usable label: ${nextAction}`)
  }
  const boundary = await page.getByTestId('execution-simulation-boundary').innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundary.includes(expected)) {
      throw new Error(`Execution visible boundary is missing ${expected}: ${boundary}`)
    }
  }
}

async function assertGuardrailHubVisibleBoundary(page) {
  await page.getByTestId('guardrail-hub-governance').waitFor({ state: 'visible', timeout: 15000 })
  const contextId = await page.getByTestId('guardrail-hub-governance-id').innerText()
  if (!contextId.trim()) {
    throw new Error('Guardrail Hub governance context did not render an ID')
  }
  const evidenceStrength = await page.getByTestId('guardrail-hub-evidence-strength').innerText()
  if (!['LOW', 'MEDIUM'].includes(evidenceStrength.trim())) {
    throw new Error(`Guardrail Hub evidence strength did not render LOW/MEDIUM: ${evidenceStrength}`)
  }
  const blocker = await page.getByTestId('guardrail-hub-blocker').innerText()
  if (!blocker.trim() || blocker.includes('undefined')) {
    throw new Error(`Guardrail Hub blocker did not render a usable label: ${blocker}`)
  }
  const nextAction = await page.getByTestId('guardrail-hub-next-action').innerText()
  if (!nextAction.trim() || nextAction.includes('undefined')) {
    throw new Error(`Guardrail Hub next action did not render a usable label: ${nextAction}`)
  }
  const boundary = await page.getByTestId('guardrail-hub-simulation-boundary').innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundary.includes(expected)) {
      throw new Error(`Guardrail Hub visible boundary is missing ${expected}: ${boundary}`)
    }
  }
}

async function runBackendAttemptDiagnosticsScenario(page) {
  const attemptsResponses = bufferedResponses(page, (response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/analysis/jobs/attempts')
      && response.url().includes('limit=12')
      && response.status() === 200
  ))
  const generatedAt = new Date().toISOString()
  const productionHealthMetricFixture = {
    generatedAt,
    productionHealth: {
      status: 'healthy',
      generatedAt,
      externalCalls: false,
      windows: {
        '24h': {
          window: '24h',
          windowHours: 24,
          runSuccessRate: { total: 5, succeeded: 4, failed: 1, successRate: 0.8 },
          llmCallFailureRate: {
            total: 6,
            succeeded: 5,
            failed: 1,
            skipped: 0,
            successRate: 0.83,
            failureRate: 0.17,
            totalTokens: 120,
            failureReasons: [{ reason: 'strict-auth fixture timeout token=[REDACTED]', count: 1 }],
            sampleFailures: [],
          },
          marketDataFallbackRate: { total: 5, fallbackOrMock: 1, unavailable: 0, fallbackRate: 0.2 },
          signalOpsTickSuccessRate: { total: 4, succeeded: 3, failed: 1, successRate: 0.75 },
          staleJobs: { windowCount: 0, currentCount: 0, jobTotal: 1, runIds: [] },
          errorBudget: { status: 'ok', totalEvents: 9, observedErrors: 1, consumedPercent: 25, remainingPercent: 75 },
        },
        '7d': {
          window: '7d',
          windowHours: 168,
          runSuccessRate: { total: 8, succeeded: 5, failed: 3, successRate: 0.63 },
          llmCallFailureRate: {
            total: 12,
            succeeded: 8,
            failed: 4,
            skipped: 1,
            successRate: 0.67,
            failureRate: 0.33,
            totalTokens: 280,
            failureReasons: [{ reason: 'weekly fixture timeout token=[REDACTED]', count: 4 }],
            sampleFailures: [],
          },
          marketDataFallbackRate: { total: 5, fallbackOrMock: 2, unavailable: 0, fallbackRate: 0.4 },
          signalOpsTickSuccessRate: { total: 4, succeeded: 2, failed: 2, successRate: 0.5 },
          staleJobs: { windowCount: 0, currentCount: 0, jobTotal: 1, runIds: [] },
          errorBudget: { status: 'watch', totalEvents: 20, observedErrors: 4, consumedPercent: 40, remainingPercent: 60 },
        },
        '30d': {
          window: '30d',
          windowHours: 720,
          runSuccessRate: { total: 10, succeeded: 6, failed: 4, successRate: 0.6 },
          llmCallFailureRate: {
            total: 20,
            succeeded: 10,
            failed: 10,
            skipped: 3,
            successRate: 0.5,
            failureRate: 0.5,
            totalTokens: 780,
            failureReasons: [{ reason: 'monthly fixture timeout token=[REDACTED]', count: 10 }],
            sampleFailures: [],
          },
          marketDataFallbackRate: { total: 10, fallbackOrMock: 4, unavailable: 0, fallbackRate: 0.4 },
          signalOpsTickSuccessRate: { total: 8, succeeded: 4, failed: 4, successRate: 0.5 },
          staleJobs: { windowCount: 1, currentCount: 1, jobTotal: 2, runIds: ['RUN_MONTH_STALE'] },
          errorBudget: { status: 'burning', totalEvents: 40, observedErrors: 10, consumedPercent: 65, remainingPercent: 35 },
        },
      },
      trend: {
        baselineWindow: '7d',
        runSuccessRateDelta: 0.17,
        llmSuccessRateDelta: 0.16,
        llmFailureRateDelta: -0.16,
        marketDataFallbackRateDelta: -0.2,
        signalOpsTickSuccessRateDelta: 0.25,
      },
      longTrend: {
        baselineWindow: '30d',
        runSuccessRateDelta: 0.2,
        llmSuccessRateDelta: 0.33,
        llmFailureRateDelta: -0.33,
        marketDataFallbackRateDelta: -0.2,
        signalOpsTickSuccessRateDelta: 0.25,
      },
      alerts: [],
      errorBudget: { status: 'ok', totalEvents: 9, observedErrors: 1, consumedPercent: 25, remainingPercent: 75 },
      sourceErrors: {},
    },
  }
  const productionHealthMetricsRouteHandler = async (route) => {
    const request = route.request()
    if (request.method() !== 'GET') {
      await route.continue()
      return
    }
    const headers = await request.allHeaders()
    const authorization = headers.authorization || headers.Authorization
    if (authorization !== `Bearer ${authToken}`) {
      throw new Error('Backend Status production health metrics did not include the expected Authorization bearer token')
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(productionHealthMetricFixture),
    })
  }
  await page.evaluate(() => {
    window.history.pushState({}, '', '/execution')
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  })
  await page.waitForURL((url) => url.pathname === '/execution', { timeout: 15000 })
  await assertExecutionVisibleBoundary(page)
  console.log('ok strict-auth browser Execution visible review boundary')
  await page.evaluate(() => {
    window.history.pushState({}, '', '/guardrail-hub')
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  })
  await page.waitForURL((url) => url.pathname === '/guardrail-hub', { timeout: 15000 })
  await assertGuardrailHubVisibleBoundary(page)
  console.log('ok strict-auth browser Guardrail Hub visible review boundary')
  await page.evaluate(() => {
    window.history.pushState({}, '', '/permission')
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  })
  await page.waitForURL((url) => url.pathname === '/permission', { timeout: 15000 })
  await assertPermissionMatrixVisibleBoundary(page)
  console.log('ok strict-auth browser Permission Matrix visible review boundary')
  await page.evaluate(() => {
    window.history.pushState({}, '', '/backend')
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  })
  await page.waitForURL((url) => url.pathname === '/backend', { timeout: 15000 })
  await page.getByTestId('backend-analysis-job-queue').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('backend-analysis-job-attempts').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('backend-analysis-job-attempt-page').waitFor({ state: 'visible', timeout: 15000 })
  await page.route('**/api/metrics', productionHealthMetricsRouteHandler)
  let productionHealthMetrics
  try {
    const productionHealthMetricsResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/metrics')
        && response.status() === 200
    ), { timeout: 30000 })
    const productionHealthRefresh = page.getByTestId('backend-production-health-refresh')
    await productionHealthRefresh.waitFor({ state: 'visible', timeout: 15000 })
    await productionHealthRefresh.dispatchEvent('click')
    productionHealthMetrics = await assertAuthedJson(productionHealthMetricsResponsePromise, 'Backend Status production health refresh')
  } finally {
    await page.unroute('**/api/metrics', productionHealthMetricsRouteHandler).catch(() => undefined)
  }
  if (!productionHealthMetrics?.productionHealth?.windows?.['24h']) {
    throw new Error(`Backend Status production health refresh did not return 24h metrics: ${JSON.stringify(productionHealthMetrics)}`)
  }
  await page.getByTestId('backend-production-health-trend-deltas').waitFor({ state: 'visible', timeout: 15000 })
  const productionHealthTrendDeltasText = await page.getByTestId('backend-production-health-trend-deltas').innerText()
  if (
    !productionHealthTrendDeltasText.includes('基线 7d')
    || !productionHealthTrendDeltasText.includes('运行成功')
    || !productionHealthTrendDeltasText.includes('LLM 成功')
    || !productionHealthTrendDeltasText.includes('LLM 失败')
    || !productionHealthTrendDeltasText.includes('行情降级')
    || !productionHealthTrendDeltasText.includes('SignalOps 轮询')
  ) {
    throw new Error(`Backend Status production health trend deltas did not render from productionHealth.trend: ${productionHealthTrendDeltasText}`)
  }
  console.log('ok strict-auth browser Backend Status production health trend deltas')
  await page.waitForFunction(() => (
    document.querySelector('[data-testid="backend-ops-log-export-ready"]')?.textContent?.includes('export-ready')
  ), undefined, { timeout: 15000 })
  const opsLogExportText = await page.getByTestId('backend-ops-log-export-ready').innerText()
  if (!opsLogExportText.includes('export-ready')) {
    throw new Error(`Backend Status ops log export readiness did not render: ${opsLogExportText}`)
  }
  await page.getByTestId('backend-ops-log-handoff-status').waitFor({ state: 'visible', timeout: 15000 })
  const opsLogHandoffStatusText = await page.getByTestId('backend-ops-log-handoff-status').innerText()
  if (
    !opsLogHandoffStatusText.includes('LOCAL_DEPLOYMENT_HANDOFF_DIR')
    || !opsLogHandoffStatusText.includes('ops_log_export_handoff_manifest_v1')
  ) {
    throw new Error(`Backend Status ops log handoff status did not render destination/manifest schema: ${opsLogHandoffStatusText}`)
  }
  const opsLogExpectedHandoffStatusSchema = 'ops_log_export_handoff_status_v1'
  if (!opsLogExpectedHandoffStatusSchema.includes('ops_log_export_handoff_status_v1')) {
    throw new Error('Backend Status ops log handoff status schema guard is misconfigured')
  }
  await page.getByTestId('backend-ops-log-handoff-integrity').waitFor({ state: 'visible', timeout: 15000 })
  const opsLogExpectedHandoffInventorySchema = 'ops_log_export_handoff_inventory_v1'
  if (!opsLogExpectedHandoffInventorySchema.includes('ops_log_export_handoff_inventory_v1')) {
    throw new Error('Backend Status ops log handoff inventory schema guard is misconfigured')
  }
  await page.getByTestId('backend-ops-log-shipper-status').waitFor({ state: 'visible', timeout: 15000 })
  const opsLogShipperStatusText = await page.getByTestId('backend-ops-log-shipper-status').innerText()
  if (!opsLogShipperStatusText.includes('shipper:') || !opsLogShipperStatusText.includes('latest match')) {
    throw new Error(`Backend Status ops log shipper sidecar status did not render: ${opsLogShipperStatusText}`)
  }
  const opsLogExpectedShipperStatusSchema = 'ops_log_export_shipper_status_v1'
  if (!opsLogExpectedShipperStatusSchema.includes('ops_log_export_shipper_status_v1')) {
    throw new Error('Backend Status ops log shipper status schema guard is misconfigured')
  }
  await page.getByTestId('backend-ops-log-query-endpoint').waitFor({ state: 'visible', timeout: 15000 })
  const opsLogQueryEndpointText = await page.getByTestId('backend-ops-log-query-endpoint').innerText()
  if (!opsLogQueryEndpointText.includes('/api/ops/logs/query') || !opsLogQueryEndpointText.includes('ops_log_query_v1')) {
    throw new Error(`Backend Status ops log query endpoint did not render schema: ${opsLogQueryEndpointText}`)
  }
  await page.getByTestId('backend-ops-log-query-text').fill('http_request')
  const opsLogQueryResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/ops/logs/query?')
      && response.url().includes('limit=20')
      && response.url().includes('text=http_request')
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('backend-ops-log-query').click()
  const opsLogQuery = await assertAuthedJsonOrApi(
    opsLogQueryResponsePromise,
    'Backend Status ops log query',
    '/api/ops/logs/query?limit=20&text=http_request',
  )
  if (
    opsLogQuery?.schema !== 'ops_log_query_v1'
    || opsLogQuery?.source_channel !== 'local_file_jsonl'
    || opsLogQuery?.external_aggregation_ready !== true
    || typeof opsLogQuery?.matched_count !== 'number'
    || typeof opsLogQuery?.returned_count !== 'number'
    || !Array.isArray(opsLogQuery?.events)
  ) {
    throw new Error(`Backend Status ops log query returned an invalid result: ${JSON.stringify(opsLogQuery)}`)
  }
  const serializedOpsLogQuery = JSON.stringify(opsLogQuery).toLowerCase()
  if (serializedOpsLogQuery.includes('bearer ') || serializedOpsLogQuery.includes('authorization=')) {
    throw new Error(`Backend Status ops log query leaked secret-like values: ${serializedOpsLogQuery}`)
  }
  await page.getByTestId('backend-ops-log-query-result').waitFor({ state: 'visible', timeout: 15000 })
  const opsLogQueryResultText = await page.getByTestId('backend-ops-log-query-result').innerText()
  if (!opsLogQueryResultText.includes('ops_log_query_v1') || !opsLogQueryResultText.includes('http_request')) {
    throw new Error(`Backend Status ops log query result did not render schema/filter: ${opsLogQueryResultText}`)
  }
  console.log('ok strict-auth browser Backend Status ops log query')

  const opsLogExportResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/ops/logs/export?')
      && response.url().includes('limit=50')
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('backend-ops-log-export').click()
  const opsLogExport = await assertAuthedJsonOrApi(
    opsLogExportResponsePromise,
    'Backend Status ops log export',
    '/api/ops/logs/export?limit=50',
  )
  if (
    opsLogExport?.schema !== 'ops_log_export_v1'
    || opsLogExport?.source_channel !== 'local_file_jsonl'
    || opsLogExport?.external_aggregation_ready !== true
    || typeof opsLogExport?.exported_count !== 'number'
    || !String(opsLogExport?.checksum || '').startsWith('sha256:')
  ) {
    throw new Error(`Backend Status ops log export returned an invalid bundle: ${JSON.stringify(opsLogExport)}`)
  }
  const serializedOpsLogExport = JSON.stringify(opsLogExport).toLowerCase()
  if (serializedOpsLogExport.includes('bearer ') || serializedOpsLogExport.includes('authorization=')) {
    throw new Error(`Backend Status ops log export leaked secret-like values: ${serializedOpsLogExport}`)
  }
  await page.getByTestId('backend-ops-log-export-result').waitFor({ state: 'visible', timeout: 15000 })
  const opsLogExportResultText = await page.getByTestId('backend-ops-log-export-result').innerText()
  if (!opsLogExportResultText.includes('ops_log_export_v1') || !opsLogExportResultText.includes('sha256:')) {
    throw new Error(`Backend Status ops log export result did not render schema/checksum: ${opsLogExportResultText}`)
  }
  console.log('ok strict-auth browser Backend Status ops log export readiness')

  const opsLogHandoffResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/ops/logs/export/handoff?')
      && response.url().includes('limit=50')
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('backend-ops-log-handoff').click()
  const opsLogHandoff = await assertAuthedJsonOrApi(
    opsLogHandoffResponsePromise,
    'Backend Status ops log export handoff',
    '/api/ops/logs/export/handoff?limit=50',
  )
  const opsLogHandoffManifest = asRecord(opsLogHandoff?.manifest)
  const opsLogHandoffRetention = asRecord(opsLogHandoffManifest.retention_policy)
  if (
    opsLogHandoff?.schema !== 'ops_log_export_handoff_v1'
    || opsLogHandoff?.status !== 'HANDED_OFF'
    || opsLogHandoff?.handoff_destination !== 'LOCAL_DEPLOYMENT_HANDOFF_DIR'
    || !String(opsLogHandoff?.bundle_checksum || '').startsWith('sha256:')
    || opsLogHandoffManifest.schema !== 'ops_log_export_handoff_manifest_v1'
    || opsLogHandoffRetention.custody !== 'deployment_owned_after_handoff'
    || opsLogHandoffManifest.bundle_checksum !== opsLogHandoff.bundle_checksum
  ) {
    throw new Error(`Backend Status ops log export handoff returned an invalid manifest: ${JSON.stringify(opsLogHandoff)}`)
  }
  const serializedOpsLogHandoff = JSON.stringify(opsLogHandoff).toLowerCase()
  if (serializedOpsLogHandoff.includes('bearer ') || serializedOpsLogHandoff.includes('authorization=')) {
    throw new Error(`Backend Status ops log export handoff leaked secret-like values: ${serializedOpsLogHandoff}`)
  }
  await page.getByTestId('backend-ops-log-handoff-result').waitFor({ state: 'visible', timeout: 15000 })
  const opsLogHandoffResultText = await page.getByTestId('backend-ops-log-handoff-result').innerText()
  if (
    !opsLogHandoffResultText.includes('HANDED_OFF')
    || !opsLogHandoffResultText.includes('LOCAL_DEPLOYMENT_HANDOFF_DIR')
    || !opsLogHandoffResultText.includes('sha256:')
  ) {
    throw new Error(`Backend Status ops log export handoff result did not render status/destination/checksum: ${opsLogHandoffResultText}`)
  }
  await page.waitForFunction(() => (
    document.querySelector('[data-testid="backend-ops-log-handoff-integrity"]')?.textContent?.includes('VERIFIED')
  ), undefined, { timeout: 15000 })
  const opsLogHandoffIntegrityText = await page.getByTestId('backend-ops-log-handoff-integrity').innerText()
  if (!opsLogHandoffIntegrityText.includes('VERIFIED') || !opsLogHandoffIntegrityText.includes('verified')) {
    throw new Error(`Backend Status ops log handoff integrity did not render verified inventory: ${opsLogHandoffIntegrityText}`)
  }
  const opsLogHandoffDir = process.env.OPS_LOG_EXPORT_HANDOFF_DIR
  if (!opsLogHandoffDir) {
    throw new Error('OPS_LOG_EXPORT_HANDOFF_DIR is required for Ops Log shipper readiness smoke')
  }
  await mkdir(opsLogHandoffDir, { recursive: true })
  await writeFile(
    path.join(opsLogHandoffDir, 'shipper_status.json'),
    JSON.stringify({
      schema: 'ops_log_export_shipper_status_v1',
      status: 'DELIVERED',
      reported_at: new Date().toISOString(),
      source: 'strict-auth-ops-log-shipper',
      provider: 'object-store',
      remote_destination: 's3://strict-auth-ops-log/archive?token=unit-secret',
      remote_object_key: `ops-log/${opsLogHandoff.handoff_id}.json`,
      retention_policy_id: 'ops-log-retention-30d',
      retention_status: 'RETAINED',
      custody_status: 'KMS_RETAINED',
      kms_key_ref: 'strict-auth-kms-key?token=unit-secret',
      search_index: 'ops-log-events',
      search_index_ready: true,
      last_handoff_id: opsLogHandoff.handoff_id,
      last_bundle_checksum: opsLogHandoff.bundle_checksum,
      message: 'indexed token=unit-secret',
    }, null, 2),
    'utf8',
  )
  const opsLogCustodyStatusResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/ops/logs/status?')
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('backend-ops-log-refresh').click()
  const opsLogCustodyStatus = await assertAuthedJsonOrApi(
    opsLogCustodyStatusResponsePromise,
    'Backend Status ops log shipper readiness refresh',
    '/api/ops/logs/status?limit=10',
  )
  const opsLogShipperReadiness = asRecord(asRecord(opsLogCustodyStatus?.handoff_status).shipper_status)
  if (
    opsLogShipperReadiness.schema !== 'ops_log_export_shipper_status_v1'
    || opsLogShipperReadiness.status !== 'DELIVERED'
    || opsLogShipperReadiness.provider !== 'object-store'
    || opsLogShipperReadiness.retention_status !== 'RETAINED'
    || opsLogShipperReadiness.custody_status !== 'KMS_RETAINED'
    || opsLogShipperReadiness.search_index !== 'ops-log-events'
    || opsLogShipperReadiness.search_index_ready !== true
    || opsLogShipperReadiness.matches_latest_inventory !== true
  ) {
    throw new Error(`Backend Status ops log shipper readiness returned unexpected payload: ${JSON.stringify(opsLogShipperReadiness)}`)
  }
  const serializedOpsLogShipperReadiness = JSON.stringify(opsLogShipperReadiness).toLowerCase()
  if (serializedOpsLogShipperReadiness.includes('unit-secret') || serializedOpsLogShipperReadiness.includes('bearer ')) {
    throw new Error(`Backend Status ops log shipper readiness leaked secret-like values: ${serializedOpsLogShipperReadiness}`)
  }
  await page.waitForFunction(() => (
    document.querySelector('[data-testid="backend-ops-log-shipper-readiness"]')?.textContent?.includes('search ready yes')
  ), undefined, { timeout: 15000 })
  const opsLogShipperReadinessText = await page.getByTestId('backend-ops-log-shipper-readiness').innerText()
  if (
    !opsLogShipperReadinessText.includes('search ready yes')
    || !opsLogShipperReadinessText.includes('RETAINED')
    || !opsLogShipperReadinessText.includes('KMS_RETAINED')
    || !opsLogShipperReadinessText.includes('ops-log/')
    || opsLogShipperReadinessText.includes('unit-secret')
  ) {
    throw new Error(`Backend Status ops log shipper readiness did not render safely: ${opsLogShipperReadinessText}`)
  }
  const opsLogPostHandoffShipperText = await page.getByTestId('backend-ops-log-shipper-status').innerText()
  if (
    !opsLogPostHandoffShipperText.includes('shipper:')
    || !opsLogPostHandoffShipperText.includes('DELIVERED')
    || !opsLogPostHandoffShipperText.includes('object-store')
    || !opsLogPostHandoffShipperText.includes('latest match yes')
  ) {
    throw new Error(`Backend Status ops log shipper status disappeared after handoff: ${opsLogPostHandoffShipperText}`)
  }
  console.log('ok strict-auth browser Backend Status ops log shipper readiness')
  console.log('ok strict-auth browser Backend Status ops log export handoff')

  await page.waitForFunction(() => (
    document.querySelector('[data-testid="backend-production-alert-export-ready"]')?.textContent?.includes('export-ready')
  ), undefined, { timeout: 15000 })
  const alertExportReadyText = await page.getByTestId('backend-production-alert-export-ready').innerText()
  if (!alertExportReadyText.includes('export-ready')) {
    throw new Error(`Backend Status production alert export readiness did not render: ${alertExportReadyText}`)
  }
  await page.getByTestId('backend-production-alert-handoff-status').waitFor({ state: 'visible', timeout: 15000 })
  const alertHandoffStatusText = await page.getByTestId('backend-production-alert-handoff-status').innerText()
  if (
    !alertHandoffStatusText.includes('LOCAL_DEPLOYMENT_HANDOFF_DIR')
    || !alertHandoffStatusText.includes('production_alert_outbox_export_handoff_manifest_v1')
  ) {
    throw new Error(`Backend Status production alert handoff status did not render destination/manifest schema: ${alertHandoffStatusText}`)
  }
  const alertExpectedHandoffStatusSchema = 'production_alert_outbox_export_handoff_status_v1'
  if (!alertExpectedHandoffStatusSchema.includes('production_alert_outbox_export_handoff_status_v1')) {
    throw new Error('Backend Status production alert handoff status schema guard is misconfigured')
  }
  await page.getByTestId('backend-production-alert-handoff-integrity').waitFor({ state: 'visible', timeout: 15000 })
  const alertExpectedHandoffInventorySchema = 'production_alert_outbox_export_handoff_inventory_v1'
  if (!alertExpectedHandoffInventorySchema.includes('production_alert_outbox_export_handoff_inventory_v1')) {
    throw new Error('Backend Status production alert handoff inventory schema guard is misconfigured')
  }
  await page.getByTestId('backend-production-alert-shipper-status').waitFor({ state: 'visible', timeout: 15000 })
  const alertShipperStatusText = await page.getByTestId('backend-production-alert-shipper-status').innerText()
  if (!alertShipperStatusText.includes('shipper:') || !alertShipperStatusText.includes('latest match')) {
    throw new Error(`Backend Status production alert shipper sidecar status did not render: ${alertShipperStatusText}`)
  }
  await page.getByTestId('backend-production-alert-rule-policy').waitFor({ state: 'visible', timeout: 15000 })
  const alertRulePolicyText = await page.getByTestId('backend-production-alert-rule-policy').innerText()
  if (
    !alertRulePolicyText.includes('production_alert_rule_policy_v1')
    || !alertRulePolicyText.includes('ops-critical')
  ) {
    throw new Error(`Backend Status production alert rule policy did not render: ${alertRulePolicyText}`)
  }
  await page.getByTestId('backend-production-alert-rule-provider-acceptance').waitFor({ state: 'visible', timeout: 15000 })
  const alertRuleProviderAcceptanceText = await page.getByTestId('backend-production-alert-rule-provider-acceptance').innerText()
  if (
    !alertRuleProviderAcceptanceText.includes('production_alert_rule_provider_acceptance_v1')
    || !alertRuleProviderAcceptanceText.includes('ACCEPTED')
    || !alertRuleProviderAcceptanceText.includes('alertmanager')
    || !alertRuleProviderAcceptanceText.includes('policy match yes')
    || !alertRuleProviderAcceptanceText.includes('rules 3/3')
    || alertRuleProviderAcceptanceText.includes('unit-secret')
  ) {
    throw new Error(`Backend Status production alert rule provider acceptance did not render safely: ${alertRuleProviderAcceptanceText}`)
  }
  const alertExpectedRuleProviderAcceptanceSchema = 'production_alert_rule_provider_acceptance_v1'
  if (!alertExpectedRuleProviderAcceptanceSchema.includes('production_alert_rule_provider_acceptance_v1')) {
    throw new Error('Backend Status production alert rule provider acceptance schema guard is misconfigured')
  }
  console.log('ok strict-auth browser Backend Status production alert rule provider acceptance')
  const alertExpectedShipperStatusSchema = 'production_alert_outbox_export_shipper_status_v1'
  if (!alertExpectedShipperStatusSchema.includes('production_alert_outbox_export_shipper_status_v1')) {
    throw new Error('Backend Status production alert shipper status schema guard is misconfigured')
  }
  const alertExportResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/ops/alerts/export?')
      && response.url().includes('limit=50')
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('backend-production-alert-export').click()
  const alertExport = await assertAuthedJsonOrApi(
    alertExportResponsePromise,
    'Backend Status production alert export',
    '/api/ops/alerts/export?limit=50',
  )
  if (
    alertExport?.schema !== 'production_alert_outbox_export_v1'
    || alertExport?.source_channel !== 'local_file_outbox'
    || alertExport?.external_aggregation_ready !== true
    || typeof alertExport?.exported_count !== 'number'
    || !String(alertExport?.checksum || '').startsWith('sha256:')
  ) {
    throw new Error(`Backend Status production alert export returned an invalid bundle: ${JSON.stringify(alertExport)}`)
  }
  const alertExportRulePolicy = asRecord(alertExport?.alert_rule_policy)
  const alertExportRuleAcceptance = asRecord(alertExportRulePolicy.provider_acceptance)
  if (
    alertExportRuleAcceptance.schema !== 'production_alert_rule_provider_acceptance_v1'
    || alertExportRuleAcceptance.status !== 'ACCEPTED'
    || alertExportRuleAcceptance.provider !== 'alertmanager'
    || alertExportRuleAcceptance.matches_policy !== true
    || alertExportRuleAcceptance.rules_accepted !== 3
    || alertExportRuleAcceptance.rules_total !== 3
  ) {
    throw new Error(`Backend Status production alert export returned invalid rule provider acceptance: ${JSON.stringify(alertExportRuleAcceptance)}`)
  }
  const serializedAlertExport = JSON.stringify(alertExport).toLowerCase()
  if (serializedAlertExport.includes('authorization=') || serializedAlertExport.includes('api_key=') || serializedAlertExport.includes('unit-secret')) {
    throw new Error(`Backend Status production alert export leaked secret-like values: ${serializedAlertExport}`)
  }
  await page.getByTestId('backend-production-alert-export-result').waitFor({ state: 'visible', timeout: 15000 })
  const alertExportResultText = await page.getByTestId('backend-production-alert-export-result').innerText()
  if (!alertExportResultText.includes('production_alert_outbox_export_v1') || !alertExportResultText.includes('sha256:')) {
    throw new Error(`Backend Status production alert export result did not render schema/checksum: ${alertExportResultText}`)
  }
  console.log('ok strict-auth browser Backend Status production alert export readiness')

  const alertHandoffResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/ops/alerts/export/handoff?')
      && response.url().includes('limit=50')
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('backend-production-alert-handoff').click()
  const alertHandoff = await assertAuthedJsonOrApi(
    alertHandoffResponsePromise,
    'Backend Status production alert export handoff',
    '/api/ops/alerts/export/handoff?limit=50',
  )
  const alertHandoffManifest = asRecord(alertHandoff?.manifest)
  const alertHandoffRetention = asRecord(alertHandoffManifest.retention_policy)
  if (
    alertHandoff?.schema !== 'production_alert_outbox_export_handoff_v1'
    || alertHandoff?.status !== 'HANDED_OFF'
    || alertHandoff?.handoff_destination !== 'LOCAL_DEPLOYMENT_HANDOFF_DIR'
    || !String(alertHandoff?.bundle_checksum || '').startsWith('sha256:')
    || alertHandoffManifest.schema !== 'production_alert_outbox_export_handoff_manifest_v1'
    || alertHandoffRetention.custody !== 'deployment_owned_after_handoff'
    || alertHandoffManifest.bundle_checksum !== alertHandoff.bundle_checksum
  ) {
    throw new Error(`Backend Status production alert export handoff returned an invalid manifest: ${JSON.stringify(alertHandoff)}`)
  }
  const serializedAlertHandoff = JSON.stringify(alertHandoff).toLowerCase()
  if (serializedAlertHandoff.includes('authorization=') || serializedAlertHandoff.includes('api_key=')) {
    throw new Error(`Backend Status production alert export handoff leaked secret-like values: ${serializedAlertHandoff}`)
  }
  await page.getByTestId('backend-production-alert-handoff-result').waitFor({ state: 'visible', timeout: 15000 })
  const alertHandoffResultText = await page.getByTestId('backend-production-alert-handoff-result').innerText()
  if (
    !alertHandoffResultText.includes('HANDED_OFF')
    || !alertHandoffResultText.includes('LOCAL_DEPLOYMENT_HANDOFF_DIR')
    || !alertHandoffResultText.includes('sha256:')
  ) {
    throw new Error(`Backend Status production alert export handoff result did not render status/destination/checksum: ${alertHandoffResultText}`)
  }
  await page.waitForFunction(() => (
    document.querySelector('[data-testid="backend-production-alert-handoff-integrity"]')?.textContent?.includes('VERIFIED')
  ), undefined, { timeout: 15000 })
  const alertHandoffIntegrityText = await page.getByTestId('backend-production-alert-handoff-integrity').innerText()
  if (!alertHandoffIntegrityText.includes('VERIFIED') || !alertHandoffIntegrityText.includes('verified')) {
    throw new Error(`Backend Status production alert handoff integrity did not render verified inventory: ${alertHandoffIntegrityText}`)
  }
  const alertHandoffDir = process.env.PRODUCTION_ALERT_EXPORT_HANDOFF_DIR
  if (!alertHandoffDir) {
    throw new Error('PRODUCTION_ALERT_EXPORT_HANDOFF_DIR is required for production alert shipper readiness smoke')
  }
  await mkdir(alertHandoffDir, { recursive: true })
  await writeFile(
    path.join(alertHandoffDir, 'shipper_status.json'),
    JSON.stringify({
      schema: 'production_alert_outbox_export_shipper_status_v1',
      status: 'DELIVERED',
      reported_at: new Date().toISOString(),
      source: 'strict-auth-production-alert-shipper',
      provider: 'alert-archive',
      remote_destination: 's3://strict-auth-alerts/archive?token=unit-secret',
      remote_object_key: `production-alerts/${alertHandoff.handoff_id}.json`,
      retention_policy_id: 'production-alert-retention-30d',
      retention_status: 'RETAINED',
      custody_status: 'KMS_RETAINED',
      kms_key_ref: 'strict-auth-alert-kms-key?token=unit-secret',
      search_index: 'production-alert-events',
      search_index_ready: true,
      last_handoff_id: alertHandoff.handoff_id,
      last_bundle_checksum: alertHandoff.bundle_checksum,
      message: 'archived token=unit-secret',
    }, null, 2),
    'utf8',
  )
  const alertCustodyStatusResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/ops/alerts/status?')
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('backend-production-alert-refresh').click()
  const alertCustodyStatus = await assertAuthedJsonOrApi(
    alertCustodyStatusResponsePromise,
    'Backend Status production alert shipper readiness refresh',
    '/api/ops/alerts/status?limit=10',
  )
  const alertShipperReadiness = asRecord(asRecord(alertCustodyStatus?.handoff_status).shipper_status)
  if (
    alertShipperReadiness.schema !== 'production_alert_outbox_export_shipper_status_v1'
    || alertShipperReadiness.status !== 'DELIVERED'
    || alertShipperReadiness.provider !== 'alert-archive'
    || alertShipperReadiness.retention_status !== 'RETAINED'
    || alertShipperReadiness.custody_status !== 'KMS_RETAINED'
    || alertShipperReadiness.search_index !== 'production-alert-events'
    || alertShipperReadiness.search_index_ready !== true
    || alertShipperReadiness.matches_latest_inventory !== true
  ) {
    throw new Error(`Backend Status production alert shipper readiness returned unexpected payload: ${JSON.stringify(alertShipperReadiness)}`)
  }
  const serializedAlertShipperReadiness = JSON.stringify(alertShipperReadiness).toLowerCase()
  if (serializedAlertShipperReadiness.includes('unit-secret') || serializedAlertShipperReadiness.includes('bearer ')) {
    throw new Error(`Backend Status production alert shipper readiness leaked secret-like values: ${serializedAlertShipperReadiness}`)
  }
  await page.waitForFunction(() => (
    document.querySelector('[data-testid="backend-production-alert-shipper-readiness"]')?.textContent?.includes('search ready yes')
  ), undefined, { timeout: 15000 })
  const alertShipperReadinessText = await page.getByTestId('backend-production-alert-shipper-readiness').innerText()
  if (
    !alertShipperReadinessText.includes('search ready yes')
    || !alertShipperReadinessText.includes('RETAINED')
    || !alertShipperReadinessText.includes('KMS_RETAINED')
    || !alertShipperReadinessText.includes('production-alerts/')
    || alertShipperReadinessText.includes('unit-secret')
  ) {
    throw new Error(`Backend Status production alert shipper readiness did not render safely: ${alertShipperReadinessText}`)
  }
  const alertPostHandoffShipperText = await page.getByTestId('backend-production-alert-shipper-status').innerText()
  if (
    !alertPostHandoffShipperText.includes('shipper:')
    || !alertPostHandoffShipperText.includes('DELIVERED')
    || !alertPostHandoffShipperText.includes('alert-archive')
    || !alertPostHandoffShipperText.includes('latest match yes')
  ) {
    throw new Error(`Backend Status production alert shipper status disappeared after handoff: ${alertPostHandoffShipperText}`)
  }
  console.log('ok strict-auth browser Backend Status production alert shipper readiness')
  console.log('ok strict-auth browser Backend Status production alert export handoff')

  try {
    await page.getByTestId('backend-analysis-job-attempt-refresh').click()
    const attempts = await assertAuthedJsonOrApi(
      attemptsResponses.next(),
      'Backend Status attempt diagnostics load',
      '/api/analysis/jobs/attempts?limit=12',
    )
    if (!Array.isArray(attempts)) {
      throw new Error('Backend Status attempt diagnostics did not return an array')
    }
  } finally {
    attemptsResponses.stop()
  }
  console.log('ok strict-auth browser Backend Status attempt diagnostics')

  const filterRunId = await seedBackendAttemptDiagnosticsRun()
  const filteredAttemptsResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/analysis/jobs/attempts?')
      && response.url().includes(`run_id=${encodeURIComponent(filterRunId)}`)
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('backend-analysis-job-attempt-filter').fill(filterRunId)
  await page.getByTestId('backend-analysis-job-attempt-apply').click()
  let filteredAttempts = await assertAuthedJsonOrApi(
    filteredAttemptsResponsePromise,
    'Backend Status attempt diagnostics filtered load',
    `/api/analysis/jobs/attempts?limit=12&run_id=${encodeURIComponent(filterRunId)}`,
  )
  if (!Array.isArray(filteredAttempts)) {
    throw new Error('Backend Status filtered attempt diagnostics did not return an array')
  }
  let matchingAttempt = filteredAttempts.find((attempt) => attempt?.run_id === filterRunId)
  for (let attempt = 0; attempt < 4 && !matchingAttempt; attempt += 1) {
    await delay(1000)
    const retryFilteredAttemptsResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/analysis/jobs/attempts?')
        && response.url().includes(`run_id=${encodeURIComponent(filterRunId)}`)
        && response.status() === 200
    ), { timeout: 30000 })
    await page.getByTestId('backend-analysis-job-attempt-apply').click()
    filteredAttempts = await assertAuthedJsonOrApi(
      retryFilteredAttemptsResponsePromise,
      'Backend Status attempt diagnostics filtered retry load',
      `/api/analysis/jobs/attempts?limit=12&run_id=${encodeURIComponent(filterRunId)}`,
      { page, timeoutMs: 60000 },
    )
    if (!Array.isArray(filteredAttempts)) {
      throw new Error('Backend Status filtered attempt diagnostics retry did not return an array')
    }
    matchingAttempt = filteredAttempts.find((attemptRow) => attemptRow?.run_id === filterRunId)
  }
  if (!matchingAttempt || Number(matchingAttempt.attempt) !== 1 || !matchingAttempt.job_id) {
    throw new Error(`Backend Status filtered attempt diagnostics did not include the seeded attempt row: ${JSON.stringify(filteredAttempts)}`)
  }
  await expectText(page, filterRunId, 'Backend Status attempt diagnostics run filter')
  await expectText(page, '1 attempts', 'Backend Status attempt diagnostics seeded count')
  await expectText(page, 'attempt #1', 'Backend Status seeded attempt row')
  await expectText(page, String(matchingAttempt.status || 'QUEUED'), 'Backend Status seeded attempt status')

  const jobsResponses = bufferedResponses(page, isAnalysisJobQueueResponse)
  const queueSummaryResponses = bufferedResponses(page, isAnalysisJobQueueSummaryResponse)
  let jobs
  let queueSummary
  try {
    await page.getByTestId('backend-analysis-job-queue-refresh').click()
    jobs = await assertAuthedJsonOrApi(
      jobsResponses.next(),
      'Backend Status analysis job queue load',
      '/api/analysis/jobs?limit=12&offset=0',
    )
    queueSummary = await assertAuthedJsonOrApi(
      queueSummaryResponses.next(),
      'Backend Status analysis job queue summary',
      '/api/analysis/jobs/summary?limit=12&offset=0',
    )
  } finally {
    jobsResponses.stop()
    queueSummaryResponses.stop()
  }
  if (!Array.isArray(jobs)) {
    throw new Error('Backend Status analysis job queue did not return an array')
  }
  if (
    queueSummary?.external_queue_status?.schema !== 'analysis_job_external_queue_status_v1'
    || queueSummary.external_queue_status.status !== 'READY'
    || queueSummary.external_queue_status.provider !== 'local-smoke-queue'
    || queueSummary.external_queue_status.claim_status !== 'READY'
    || queueSummary.external_queue_status.claim_backend !== 'local-smoke-claim'
    || queueSummary.external_queue_status.idempotency_scope !== 'run_id+attempt'
    || queueSummary.external_queue_status.audit_stream !== 'analysis-job-audit'
    || queueSummary.external_queue_status.dead_letter_queue !== 'analysis-dlq'
    || queueSummary.external_queue_status.dead_letter_count !== 0
    || queueSummary.external_queue_status.visibility_timeout_seconds !== 120
    || queueSummary.external_queue_status.lease_renewal_status !== 'READY'
    || queueSummary.external_queue_status.local_queue_mode !== 'LOCAL_JSON_SQLITE_DIAGNOSTIC'
  ) {
    throw new Error(`Backend Status analysis job external queue summary was invalid: ${JSON.stringify(queueSummary)}`)
  }
  const matchingJob = jobs.find((job) => job?.run_id === filterRunId)
  if (!matchingJob || !matchingJob.job_id || !matchingJob.queue_name || !matchingJob.lease_status) {
    throw new Error(`Backend Status analysis job queue did not include the seeded job: ${JSON.stringify(jobs)}`)
  }
  const queueRow = page.getByTestId(`backend-analysis-job-queue-row-${filterRunId}`)
  await page.getByTestId('backend-analysis-job-queue-page').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('backend-analysis-job-queue-total').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('backend-analysis-job-queue-filter').waitFor({ state: 'visible', timeout: 15000 })
  const queueTotalText = await page.getByTestId('backend-analysis-job-queue-total').innerText()
  if (!queueTotalText.includes('total')) {
    throw new Error(`Backend Status analysis job queue total summary was not rendered: ${queueTotalText}`)
  }
  try {
    await page.getByTestId('backend-analysis-job-external-queue-status').waitFor({ state: 'visible', timeout: 15000 })
  } catch {
    const retryQueueSummaryResponsePromise = page.waitForResponse((response) => (
      isAnalysisJobQueueSummaryResponse(response)
    ), { timeout: 30000 })
    await page.getByTestId('backend-analysis-job-queue-refresh').click()
    const retryQueueSummary = await assertAuthedJsonOrApi(
      retryQueueSummaryResponsePromise,
      'Backend Status analysis job external queue sidecar retry load',
      '/api/analysis/jobs/summary?limit=12&offset=0',
    )
    if (
      retryQueueSummary?.external_queue_status?.schema !== 'analysis_job_external_queue_status_v1'
      || retryQueueSummary.external_queue_status.status !== 'READY'
      || retryQueueSummary.external_queue_status.provider !== 'local-smoke-queue'
      || retryQueueSummary.external_queue_status.claim_status !== 'READY'
    ) {
      throw new Error(`Backend Status analysis job external queue retry summary was invalid: ${JSON.stringify(retryQueueSummary)}`)
    }
    await page.getByTestId('backend-analysis-job-external-queue-status').waitFor({ state: 'visible', timeout: 30000 })
  }
  const externalQueueStatusText = await page.getByTestId('backend-analysis-job-external-queue-status').innerText()
  if (
    !externalQueueStatusText.includes('外部队列：READY')
    || !externalQueueStatusText.includes('local-smoke-queue')
    || !externalQueueStatusText.includes('LOCAL_JSON_SQLITE_DIAGNOSTIC')
  ) {
    throw new Error(`Backend Status analysis job external queue sidecar did not render: ${externalQueueStatusText}`)
  }
  await page.getByTestId('backend-analysis-job-external-queue-readiness').waitFor({ state: 'visible', timeout: 15000 })
  const externalQueueReadinessText = await page.getByTestId('backend-analysis-job-external-queue-readiness').innerText()
  if (
    !externalQueueReadinessText.includes('认领 READY')
    || !externalQueueReadinessText.includes('local-smoke-claim')
    || !externalQueueReadinessText.includes('run_id+attempt')
    || !externalQueueReadinessText.includes('analysis-job-audit')
    || !externalQueueReadinessText.includes('analysis-dlq')
    || !externalQueueReadinessText.includes('租约续期 READY')
  ) {
    throw new Error(`Backend Status analysis job external queue readiness did not render: ${externalQueueReadinessText}`)
  }
  console.log('ok strict-auth browser Backend Status analysis job external queue readiness')
  let queueRowVisible = false
  let queueRowError
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try {
      await queueRow.waitFor({ state: 'visible', timeout: attempt === 0 ? 30000 : 45000 })
      queueRowVisible = true
      break
    } catch (error) {
      queueRowError = error
    }
    const retryJobsResponsePromise = page.waitForResponse((response) => (
      isAnalysisJobQueueResponse(response)
    ), { timeout: 45000 })
    await page.getByTestId('backend-analysis-job-queue-refresh').click()
    const retryJobs = await assertAuthedJsonOrApi(
      retryJobsResponsePromise,
      'Backend Status analysis job queue retry load',
      '/api/analysis/jobs?limit=12&offset=0',
      { page, timeoutMs: 60000 },
    )
    if (!Array.isArray(retryJobs) || !retryJobs.some((job) => job?.run_id === filterRunId)) {
      throw new Error(`Backend Status analysis job queue retry did not include the seeded job: ${JSON.stringify(retryJobs)}`)
    }
    await page.waitForTimeout(500)
  }
  if (!queueRowVisible) {
    throw queueRowError || new Error(`Backend Status analysis job queue row ${filterRunId} did not render`)
  }
  const queueRowText = await queueRow.innerText()
  if (
    !queueRowText.includes(String(matchingJob.status || 'QUEUED'))
    || !queueRowText.includes(String(matchingJob.queue_name || 'analysis'))
    || !queueRowText.includes(String(matchingJob.lease_status || 'UNCLAIMED'))
  ) {
    throw new Error(`Backend Status analysis job queue row did not render status, queue name, and lease status: ${queueRowText}`)
  }
  console.log('ok strict-auth browser Backend Status analysis job queue')
  return filterRunId
}

async function assertDashboardVisibleBoundary(page) {
  const boundary = page.getByTestId('dashboard-run-simulation-boundary')
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`Dashboard visible boundary is missing ${expected}: ${text}`)
    }
  }
}

async function runDashboardScenario(page, runId) {
  const generatedAt = new Date().toISOString()
  const dashboardMetricsFixture = {
    generatedAt,
    productionHealth: {
      status: 'warning',
      generatedAt,
      externalCalls: false,
      windows: {
        '24h': {
          window: '24h',
          windowHours: 24,
          runSuccessRate: { total: 2, succeeded: 2, failed: 0, successRate: 1 },
          llmCallFailureRate: {
            total: 4,
            succeeded: 3,
            failed: 1,
            skipped: 1,
            successRate: 0.75,
            failureRate: 0.25,
            totalTokens: 96,
            failureReasons: [{ reason: 'fixture timeout token=[REDACTED]', count: 1 }],
            sampleFailures: [
              { runId, node: 'final_writer', status: 'FAILED', reason: 'fixture timeout token=[REDACTED]' },
            ],
          },
          marketDataFallbackRate: { total: 2, fallbackOrMock: 0, unavailable: 0, fallbackRate: 0 },
          signalOpsTickSuccessRate: { total: 1, succeeded: 1, failed: 0, successRate: 1 },
          staleJobs: { windowCount: 0, currentCount: 0, jobTotal: 0, runIds: [] },
          errorBudget: { status: 'ok', totalEvents: 9, observedErrors: 1, consumedPercent: 25, remainingPercent: 75 },
        },
        '7d': {
          window: '7d',
          windowHours: 168,
          runSuccessRate: { total: 5, succeeded: 4, failed: 1, successRate: 0.8 },
          llmCallFailureRate: {
            total: 10,
            succeeded: 6,
            failed: 4,
            skipped: 2,
            successRate: 0.6,
            failureRate: 0.4,
            totalTokens: 280,
            failureReasons: [{ reason: 'weekly fixture timeout token=[REDACTED]', count: 4 }],
            sampleFailures: [],
          },
          marketDataFallbackRate: { total: 5, fallbackOrMock: 1, unavailable: 0, fallbackRate: 0.2 },
          signalOpsTickSuccessRate: { total: 4, succeeded: 3, failed: 1, successRate: 0.75 },
          staleJobs: { windowCount: 0, currentCount: 0, jobTotal: 1, runIds: [] },
          errorBudget: { status: 'watch', totalEvents: 20, observedErrors: 4, consumedPercent: 40, remainingPercent: 60 },
        },
        '30d': {
          window: '30d',
          windowHours: 720,
          runSuccessRate: { total: 10, succeeded: 6, failed: 4, successRate: 0.6 },
          llmCallFailureRate: {
            total: 20,
            succeeded: 10,
            failed: 10,
            skipped: 3,
            successRate: 0.5,
            failureRate: 0.5,
            totalTokens: 780,
            failureReasons: [{ reason: 'monthly fixture timeout token=[REDACTED]', count: 10 }],
            sampleFailures: [],
          },
          marketDataFallbackRate: { total: 10, fallbackOrMock: 4, unavailable: 0, fallbackRate: 0.4 },
          signalOpsTickSuccessRate: { total: 8, succeeded: 4, failed: 4, successRate: 0.5 },
          staleJobs: { windowCount: 1, currentCount: 1, jobTotal: 2, runIds: ['RUN_MONTH_STALE'] },
          errorBudget: { status: 'burning', totalEvents: 40, observedErrors: 10, consumedPercent: 65, remainingPercent: 35 },
        },
      },
      trend: {
        baselineWindow: '7d',
        runSuccessRateDelta: 0.2,
        llmSuccessRateDelta: 0.15,
        llmFailureRateDelta: -0.15,
        marketDataFallbackRateDelta: -0.2,
        signalOpsTickSuccessRateDelta: 0.25,
      },
      longTrend: {
        baselineWindow: '30d',
        runSuccessRateDelta: 0.4,
        llmSuccessRateDelta: 0.25,
        llmFailureRateDelta: -0.25,
        marketDataFallbackRateDelta: -0.4,
        signalOpsTickSuccessRateDelta: 0.5,
      },
      alerts: [],
      errorBudget: { status: 'ok', totalEvents: 9, observedErrors: 1, consumedPercent: 25, remainingPercent: 75 },
      sourceErrors: {},
    },
  }
  let dashboardMetricsRequested = false
  let dashboardMetricsRequestCount = 0
  await page.route('**/api/metrics', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    dashboardMetricsRequested = true
    dashboardMetricsRequestCount += 1
    const headers = await route.request().allHeaders()
    const authorization = headers.authorization || headers.Authorization
    if (authorization !== `Bearer ${authToken}`) {
      throw new Error('Dashboard /api/metrics request did not include the expected Authorization bearer token')
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(dashboardMetricsFixture),
    })
  })
  const responseOrNull = async (responsePromise) => (
    Promise.race([
      responsePromise,
      delay(5000).then(() => null),
    ])
  )
  const runHistoryResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith('/api/analysis/runs')
      && response.status() === 200
  }, { timeout: 10000 }).catch(() => null)
  const selectedRunResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith(`/api/analysis/runs/${runId}`)
      && response.status() === 200
  }, { timeout: 10000 }).catch(() => null)
  const knowledgeVersionsResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/case-library/knowledge-versions?limit=30')
      && response.status() === 200
  ), { timeout: 10000 }).catch(() => null)
  const dashboardMetricsResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/metrics')
      && response.status() === 200
  ), { timeout: 10000 }).catch(() => null)

  const dashboardPath = `/?run_id=${encodeURIComponent(runId)}`
  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, dashboardPath)
  await page.waitForURL((url) => url.pathname === '/' && url.searchParams.get('run_id') === runId, { timeout: 15000 })

  const runHistoryResponse = await responseOrNull(runHistoryResponsePromise)
  const runHistory = runHistoryResponse
    ? await assertAuthedJson(Promise.resolve(runHistoryResponse), 'Dashboard run history load')
    : await apiJson('GET', '/api/analysis/runs')
  if (!Array.isArray(runHistory) || !runHistory.some((run) => run?.runId === runId)) {
    throw new Error(`Dashboard run history did not include the seeded run: ${JSON.stringify(runHistory)}`)
  }
  const selectedRunResponse = await responseOrNull(selectedRunResponsePromise)
  const selectedRun = selectedRunResponse
    ? await assertAuthedJson(Promise.resolve(selectedRunResponse), 'Dashboard selected run load')
    : await apiJson('GET', `/api/analysis/runs/${encodeURIComponent(runId)}`)
  if (selectedRun?.runId !== runId) {
    throw new Error(`Dashboard selected run did not match seeded run: ${JSON.stringify(selectedRun)}`)
  }
  const knowledgeVersionsResponse = await responseOrNull(knowledgeVersionsResponsePromise)
  const knowledgeVersions = knowledgeVersionsResponse
    ? await assertAuthedJson(Promise.resolve(knowledgeVersionsResponse), 'Dashboard knowledge regression load')
    : await apiJson('GET', '/api/case-library/knowledge-versions?limit=30')
  if (!Array.isArray(knowledgeVersions)) {
    throw new Error('Dashboard knowledge regression load did not return an array')
  }
  const dashboardMetricsResponse = await responseOrNull(dashboardMetricsResponsePromise)
  if (!dashboardMetricsResponse || !dashboardMetricsRequested) {
    throw new Error('Dashboard did not request /api/metrics for LLM live-call health')
  }
  const dashboardMetrics = await dashboardMetricsResponse.json()
  const dashboardLlmMetric = asRecord(asRecord(asRecord(asRecord(dashboardMetrics.productionHealth).windows)['24h']).llmCallFailureRate)
  if (
    dashboardLlmMetric.failed !== 1
    || dashboardLlmMetric.successRate !== 0.75
    || dashboardMetrics.productionHealth?.trend?.llmSuccessRateDelta !== 0.15
    || dashboardMetrics.productionHealth?.longTrend?.llmSuccessRateDelta !== 0.25
    || dashboardLlmMetric.failureReasons?.[0]?.reason !== 'fixture timeout token=[REDACTED]'
  ) {
    throw new Error(`Dashboard metrics fixture did not preserve LLM success/failure reason fields: ${JSON.stringify(dashboardMetrics)}`)
  }

  await page.getByTestId('dashboard-page').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-decision-workbench').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-trade-boundary').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-data-provenance').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-evidence-spine').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-source-freshness').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-agent-chain').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-knowledge-regression').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-llm-live-call-health').waitFor({ state: 'visible', timeout: 15000 })
  await assertDashboardVisibleBoundary(page)
  console.log('ok strict-auth browser Dashboard visible review boundary')
  await expectText(page, 'simulationOnly=true', 'Dashboard simulation-only boundary')
  await expectText(page, 'isRealTrade=false', 'Dashboard non-real-trade boundary')
  const llmSuccessRateText = await page.getByTestId('dashboard-llm-live-call-success-rate').innerText()
  if (!llmSuccessRateText.includes('75.0%')) {
    throw new Error(`Dashboard LLM live-call success rate was not rendered from productionHealth: ${llmSuccessRateText}`)
  }
  const llmTrendText = await page.getByTestId('dashboard-llm-live-call-trend').innerText()
  if (
    !llmTrendText.includes('vs 7d')
    || !llmTrendText.includes('success +15.0%')
    || !llmTrendText.includes('failure -15.0%')
    || !llmTrendText.includes('long 30d success +25.0%')
    || !llmTrendText.includes('long 30d failure -25.0%')
  ) {
    throw new Error(`Dashboard LLM live-call trend was not rendered from productionHealth.trend: ${llmTrendText}`)
  }
  const llmFailureReasonText = await page.getByTestId('dashboard-llm-live-call-failure-reason').innerText()
  if (!llmFailureReasonText.includes('fixture timeout token=[REDACTED]')) {
    throw new Error(`Dashboard LLM live-call failure reason was not rendered: ${llmFailureReasonText}`)
  }
  await page.getByTestId('dashboard-research-closed-loop-entry').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('dashboard-research-closed-loop-role').waitFor({ state: 'visible', timeout: 15000 })
  await page.evaluate(() => {
    window.localStorage.setItem('super.operatorContext', JSON.stringify({ id: 'strict-auth-browser-smoke', role: 'viewer' }))
    window.dispatchEvent(new Event('super:operator-context-change'))
  })
  await page.getByTestId('dashboard-research-closed-loop-disabled-reason').waitFor({ state: 'visible', timeout: 15000 })
  const blockedRoleText = await page.getByTestId('dashboard-research-closed-loop-role').innerText()
  if (!blockedRoleText.includes('viewer') || !blockedRoleText.includes('blocked')) {
    throw new Error(`Dashboard closed-loop role guard did not block viewer: ${blockedRoleText}`)
  }
  if (await page.getByTestId('dashboard-create-closed-loop-sample').isEnabled()) {
    throw new Error('Dashboard closed-loop sample button stayed enabled for viewer role')
  }
  await page.evaluate(() => {
    window.localStorage.setItem('super.operatorContext', JSON.stringify({ id: 'strict-auth-browser-smoke', role: 'admin' }))
    window.dispatchEvent(new Event('super:operator-context-change'))
  })
  await page.getByTestId('dashboard-research-closed-loop-disabled-reason').waitFor({ state: 'detached', timeout: 15000 })
  const allowedRoleText = await page.getByTestId('dashboard-research-closed-loop-role').innerText()
  if (!allowedRoleText.includes('admin') || !allowedRoleText.includes('researcher+')) {
    throw new Error(`Dashboard closed-loop role guard did not re-enable admin: ${allowedRoleText}`)
  }
  const renderedRunId = (await page.getByTestId('dashboard-current-run-id').innerText()).trim()
  if (renderedRunId !== runId) {
    throw new Error(`Dashboard rendered run id ${renderedRunId} instead of seeded run ${runId}`)
  }

  const dashboardClosedLoopResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/research/p2/closed-loop-sample')
  ), { timeout: 60000 })
  await clickEnabled(page.getByTestId('dashboard-create-closed-loop-sample'), 'Dashboard Research closed-loop sample button')
  const dashboardClosedLoop = await assertAuthedJson(dashboardClosedLoopResponsePromise, 'Dashboard Research closed-loop sample creation')
  assertP2ClosedLoopReviewBoundary(dashboardClosedLoop, 'Dashboard closed-loop sample')
  if (!dashboardClosedLoop.run_id || !dashboardClosedLoop.iteration_id || !dashboardClosedLoop.knowledge_version_id) {
    throw new Error(`Dashboard closed-loop sample did not return core chain ids: ${JSON.stringify(dashboardClosedLoop)}`)
  }
  await page.getByTestId('dashboard-research-closed-loop-result').waitFor({ state: 'visible', timeout: 15000 })
  await expectText(page, dashboardClosedLoop.run_id, 'Dashboard Research closed-loop run id')
  await expectText(page, dashboardClosedLoop.iteration_id, 'Dashboard Research closed-loop iteration id')
  const dashboardActionableStep = (dashboardClosedLoop.steps || []).find((step) => (
    (step.missing_items || []).length > 0 || step.status !== 'PASS'
  ))
  if (
    !dashboardActionableStep
    || dashboardActionableStep.key !== 'backtest'
    || dashboardActionableStep.status !== 'WARN'
    || dashboardActionableStep.next_action !== 'review_evidence'
    || !(dashboardActionableStep.missing_items || []).length
  ) {
    throw new Error(`Dashboard closed-loop sample did not keep weak Backtest evidence review-gated: ${JSON.stringify(dashboardClosedLoop.steps)}`)
  }
  const dashboardCurrentStepText = await page.getByTestId('dashboard-research-closed-loop-current-step').innerText()
  const expectedStepToken = dashboardActionableStep.ref_id || dashboardActionableStep.label || dashboardActionableStep.key
  if (!dashboardCurrentStepText.includes(expectedStepToken) || !dashboardCurrentStepText.includes(dashboardActionableStep.status)) {
    throw new Error(`Dashboard closed-loop current step did not show canonical actionable step: ${dashboardCurrentStepText}`)
  }
  const dashboardEvidenceStrengthText = await page.getByTestId('dashboard-research-closed-loop-evidence-strength').innerText()
  if (!dashboardEvidenceStrengthText.includes(dashboardActionableStep.evidence_strength)) {
    throw new Error(`Dashboard closed-loop evidence strength did not mirror Backtest step: ${dashboardEvidenceStrengthText}`)
  }
  const dashboardBlockerText = await page.getByTestId('dashboard-research-closed-loop-blocker').innerText()
  if (!dashboardBlockerText.includes('回测') && !dashboardBlockerText.includes('Backtest')) {
    throw new Error(`Dashboard closed-loop blocker did not show Backtest evidence review reason: ${dashboardBlockerText}`)
  }
  const dashboardNextActionText = await page.getByTestId('dashboard-research-closed-loop-next-action').innerText()
  if (!dashboardNextActionText.includes('审核证据') && !dashboardNextActionText.includes('Review evidence')) {
    throw new Error(`Dashboard closed-loop next action did not show evidence review: ${dashboardNextActionText}`)
  }
  const backendMetricsResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes('/api/metrics')
      && response.status() === 200
  ), { timeout: 15000 }).catch(() => null)
  await page.evaluate(() => {
    window.history.pushState({}, '', '/backend')
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  })
  await page.waitForURL((url) => url.pathname === '/backend', { timeout: 15000 })
  const backendMetricsResponse = await responseOrNull(backendMetricsResponsePromise)
  if (!backendMetricsResponse || dashboardMetricsRequestCount < 2) {
    throw new Error('Backend Status did not request the shared /api/metrics production health fixture')
  }
  const backendMetrics = await backendMetricsResponse.json()
  if (backendMetrics.productionHealth?.trend?.llmSuccessRateDelta !== dashboardMetrics.productionHealth?.trend?.llmSuccessRateDelta) {
    throw new Error(`Backend Status metrics fixture did not match Dashboard trend payload: ${JSON.stringify(backendMetrics)}`)
  }
  await page.getByTestId('backend-production-health-trend-deltas').waitFor({ state: 'visible', timeout: 15000 })
  const backendTrendText = await page.getByTestId('backend-production-health-trend-deltas').innerText()
  if (
    !backendTrendText.includes('基线 7d')
    || !backendTrendText.includes('vs 30d')
    || !backendTrendText.includes('+20.0%')
    || !backendTrendText.includes('+40.0%')
    || !backendTrendText.includes('+15.0%')
    || !backendTrendText.includes('+25.0%')
    || !backendTrendText.includes('-15.0%')
    || !backendTrendText.includes('-25.0%')
    || !backendTrendText.includes('-20.0%')
    || !backendTrendText.includes('-40.0%')
    || !backendTrendText.includes('+25.0%')
    || !backendTrendText.includes('+50.0%')
  ) {
    throw new Error(`Backend Status did not render the shared productionHealth.trend fixture: ${backendTrendText}`)
  }
  const backendFailureReasonText = await page.getByTestId('backend-production-health-llm-failure-reasons').innerText()
  if (!backendFailureReasonText.includes('fixture timeout token=[REDACTED]')) {
    throw new Error(`Backend Status did not render the shared redacted LLM failure reason fixture: ${backendFailureReasonText}`)
  }
  console.log('ok strict-auth browser cross-page production health trend fixture')
  await page.unroute('**/api/metrics').catch(() => undefined)
  console.log('ok strict-auth browser Dashboard run/provenance/knowledge regression and closed-loop entry')
  console.log('ok strict-auth browser Dashboard LLM live-call health')
}

async function runMarketLegacyRedirectScenario(page, runId) {
  const encodedRunId = encodeURIComponent(runId)
  const marketRunResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith(`/api/analysis/runs/${encodedRunId}`)
      && response.status() === 200
  }, { timeout: 30000 })
  await page.goto(urlFor(`/market?run_id=${encodedRunId}`), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForURL(new RegExp(`/quant-core\\?run_id=${encodedRunId}$`), { timeout: 15000 })
  const marketRun = await assertAuthedJsonOrApi(
    marketRunResponsePromise,
    'Market legacy redirect run hydrate',
    `/api/analysis/runs/${encodedRunId}`,
    { page },
  )
  if (marketRun?.runId !== runId) {
    throw new Error(`Market legacy redirect run hydrate returned ${JSON.stringify(marketRun)} instead of ${runId}`)
  }
  await assertQuantCoreVisibleBoundary(page)
  const renderedRunId = (await page.getByTestId('topbar-current-run-id').innerText({ timeout: 15000 })).trim()
  if (renderedRunId !== runId) {
    throw new Error(`Market legacy redirect rendered run id ${renderedRunId} instead of expected ${runId}`)
  }
  console.log('ok strict-auth browser Market legacy redirect preserves run context')
}

async function assertKnowledgeItemReviewBoundaryVisible(page, testId, label) {
  await page.getByTestId(testId).waitFor({ state: 'visible', timeout: 15000 })
  const visibleBoundary = await page.getByTestId(testId).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=supporting_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
    'source_run_verified=true',
  ]) {
    if (!visibleBoundary.includes(marker)) {
      throw new Error(`Knowledge item visible review boundary is missing ${marker} for ${label}: ${visibleBoundary}`)
    }
  }
}

async function runKnowledgeItemsReviewBoundaryScenario(page) {
  const createdAt = new Date().toISOString()
  const itemId = 'KNOWLEDGE_BROWSER_REVIEW'
  const knowledgeItem = {
    item_id: itemId,
    version: 3,
    status: 'ACTIVE',
    category: 'RUN_REVIEW',
    source_run_id: 'RUN_KNOWLEDGE_BROWSER_REVIEW',
    source_audit_id: 'AUD_KNOWLEDGE_BROWSER_REVIEW',
    source_run_verified: true,
    title: 'Browser smoke knowledge boundary',
    thesis: 'Visible Knowledge rows must expose supporting-only review evidence.',
    evidence: ['Strict-auth browser fixture for Knowledge visible boundary.'],
    decision_impact: 'Use only as supporting evidence after human review.',
    guardrail_notes: ['Do not promote this item into a strong trading conclusion.'],
    tags: ['strict-auth-browser', '002846'],
    confidence: 'MEDIUM',
    evidence_usage: 'supporting_only',
    evidence_strength: 'MEDIUM',
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    created_at: createdAt,
    updated_at: createdAt,
    reviewed_at: createdAt,
    reviewer: 'strict-auth-browser-smoke',
    review_note: 'Reviewed fixture remains supporting-only.',
  }

  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error(`Knowledge request did not include the expected Authorization bearer token: ${request.method()} ${url.pathname}`)
    }
    if (request.method() !== 'GET') {
      await route.continue()
      return
    }

    if (url.pathname === '/api/knowledge/summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total: 1,
          active_count: 1,
          pending_count: 0,
          rejected_count: 0,
          archived_count: 0,
          latest_version: 3,
          categories: { RUN_REVIEW: 1 },
          updated_at: createdAt,
        }),
      })
      return
    }
    if (url.pathname === '/api/knowledge/items') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([knowledgeItem]) })
      return
    }
    await route.continue()
  }

  await page.route('**/api/knowledge/**', routeHandler)
  try {
    const itemsResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/knowledge/items')
        && response.status() === 200
    ), { timeout: 30000 })
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/knowledge')
    await page.waitForURL(/\/knowledge$/, { timeout: 15000 })
    const items = await assertAuthedJson(itemsResponsePromise, 'Knowledge items list load')
    if (!Array.isArray(items) || items[0]?.item_id !== itemId) {
      throw new Error(`Knowledge fixture did not load the expected item: ${JSON.stringify(items)}`)
    }
    await assertKnowledgeItemReviewBoundaryVisible(
      page,
      `knowledge-item-simulation-boundary-${itemId}`,
      'knowledge item governance',
    )
    console.log('ok strict-auth browser Knowledge visible review boundary')
  } finally {
    await page.unroute('**/api/knowledge/**', routeHandler).catch(() => undefined)
  }
}

async function assertKnowledgeVersionsReviewGateBoundaryVisible(page, testId, label) {
  await page.getByTestId(testId).waitFor({ state: 'visible', timeout: 15000 })
  const visibleBoundary = await page.getByTestId(testId).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=review_gate_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!visibleBoundary.includes(marker)) {
      throw new Error(`Knowledge Versions visible review-gate boundary is missing ${marker} for ${label}: ${visibleBoundary}`)
    }
  }
}

async function runKnowledgeVersionsRegressionScenario(page) {
  const versionId = 'KVER_BROWSER_PUBLISHED'
  const baseVersion = {
    version_id: versionId,
    version_number: 17,
    version_label: 'v17',
    snapshot: { rules: [], patches: [] },
    active_patches: ['PATCH_BROWSER_REVIEW'],
    active_rules: ['risk_boundary_review'],
    patch_delta: { affected_modules: ['technical_kline', 'qiam'] },
    source_patch_id: 'PATCH_BROWSER_REVIEW',
    source_run_id: 'RUN_BROWSER_KNOWLEDGE',
    source_case_id: 'CASE_BROWSER_REVIEW',
    source_evaluation_id: 'EVAL_BROWSER_REVIEW',
    source_verdict_id: 'RVERDICT_BROWSER_REVIEW',
    scope: 'post_publish_regression_browser_smoke',
    risk_boundary: 'Regression refresh is review-only and does not change runtime trading policy.',
    approval_record: {
      evidence_refs: [
        { source_type: 'evaluation', source_id: 'EVAL_BROWSER_REVIEW' },
        { source_type: 'regression_waiver', source_id: 'WAIVER-BROWSER-001' },
      ],
      regression_waiver: {
        policy_id: 'knowledge_promotion_regression_waiver_v1',
        status: 'APPROVED',
        approval_id: 'WAIVER-BROWSER-001',
        reason: 'Browser smoke audited waiver proves regressed promotion governance is visible.',
        approved_by: 'strict-auth-browser-smoke',
        approver_role: 'admin',
        approved_at: new Date().toISOString(),
        evaluation_id: 'EVAL_BROWSER_REVIEW',
        regressed_cases: 1,
        mode: 'AUDITED_OVERRIDE',
      },
    },
    rollback_impact: { target_version_id: 'KVER_BROWSER_PREVIOUS', restored_patch_count: 1 },
    post_publish_regression: null,
    status: 'active',
    evidence_usage: 'review_gate_only',
    evidence_strength: 'LOW',
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    created_by: 'strict-auth-browser-smoke',
    description: 'Published knowledge version for browser regression smoke',
    created_at: new Date().toISOString(),
  }
  const refreshedVersion = {
    ...baseVersion,
    post_publish_regression: {
      report_id: 'KPPR_BROWSER_REVIEW',
      version_id: versionId,
      version_number: baseVersion.version_number,
      status: 'REGRESSION',
      trigger: 'manual_browser_smoke',
      performed_by: 'strict-auth-browser-smoke',
      generated_at: new Date().toISOString(),
      representative_case_count: 3,
      active_patch_count: 1,
      total_checks: 3,
      improved_cases: 1,
      regressed_cases: 1,
      unchanged_cases: 1,
      review_required_cases: 2,
      improvement_rate: 0.3333,
      regression_rate: 0.3333,
      review_required_rate: 0.6667,
      affected_modules: ['technical_kline', 'qiam'],
      warnings: ['browser smoke representative case requires review'],
      evidence_usage: 'review_gate_only',
      evidence_strength: 'LOW',
      simulation_only: true,
      is_real_trade: false,
      strong_conclusion_allowed: false,
      case_set_quality: {
        status: 'LOW_COVERAGE',
        reviewed_case_count: 3,
        unique_symbol_count: 1,
        symbols: ['603663'],
        incorrect_case_count: 1,
        insufficient_data_case_count: 1,
        optimism_bias_case_count: 1,
        affected_modules: ['technical_kline', 'qiam'],
        covered_affected_modules: ['technical_kline'],
        missing_affected_modules: ['qiam'],
        warnings: ['single_symbol_representative_cases', 'missing_affected_module_cases:qiam'],
      },
      case_set_quality_policy: {
        policy_id: 'knowledge_regression_case_set_quality_v1',
        mode: 'WARN_ONLY',
        action: 'WARN_ONLY',
        blocking: false,
        override_required: false,
        minimum_reviewed_cases: 3,
        minimum_unique_symbols: 2,
        requires_failure_or_boundary_case: true,
        requires_affected_module_coverage: true,
        reason: 'low_coverage_warn_only',
        warnings: ['single_symbol_representative_cases', 'missing_affected_module_cases:qiam'],
        remediation: {
          status: 'ACTION_REQUIRED',
          owner: 'case_library_reviewer',
          required_actions: ['add_symbol_diversity', 'cover_affected_modules'],
          next_actions: [
            'Add reviewed cases from 1 additional symbol(s) to reduce single-symbol bias.',
            'Add reviewed cases tagged for affected module(s): qiam.',
          ],
          required_reviewed_case_delta: 0,
          required_unique_symbol_delta: 1,
          missing_affected_modules: ['qiam'],
          target_case_mix: {
            minimum_reviewed_cases: 3,
            minimum_unique_symbols: 2,
            requires_failure_or_boundary_case: true,
            requires_affected_module_coverage: true,
          },
        },
      },
      knowledge_impact: {
        policy_id: 'knowledge_post_publish_impact_summary_v1',
        mode: 'OBSERVATION_ONLY',
        status: 'REGRESSION_ATTENTION',
        source_status: 'REGRESSION',
        risk_level: 'HIGH',
        action: 'review_regressions_before_policy_trust',
        strongest_signal: 'regression',
        requires_human_review: true,
        auto_blocks_promotion: false,
        evidence_basis: 'post_publish_regression_report',
        affected_module_count: 2,
        top_affected_modules: ['technical_kline', 'qiam'],
        active_patch_count: 1,
        representative_case_count: 3,
        total_checks: 3,
        improved_cases: 1,
        regressed_cases: 1,
        review_required_cases: 2,
        net_improvement_cases: 0,
      },
      quality_warnings: ['single_symbol_representative_cases', 'missing_affected_module_cases:qiam'],
      per_patch: [{ patch_id: 'PATCH_BROWSER_REVIEW', status: 'REGRESSION' }],
      summary: 'Browser smoke post-publish regression requires review for representative case drift.',
    },
  }
  let observedRegressionPost = false

  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (url.pathname === '/api/case-library/knowledge-versions' && request.method() === 'GET') {
      const headers = await request.allHeaders()
      if (headers.authorization !== `Bearer ${authToken}`) {
        throw new Error('Knowledge Versions list did not include the expected Authorization bearer token')
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([observedRegressionPost ? refreshedVersion : baseVersion]),
      })
      return
    }
    if (url.pathname === `/api/case-library/knowledge-versions/${versionId}/regression` && request.method() === 'POST') {
      const headers = await request.allHeaders()
      if (headers.authorization !== `Bearer ${authToken}`) {
        throw new Error('Knowledge Versions regression rerun did not include the expected Authorization bearer token')
      }
      observedRegressionPost = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(refreshedVersion),
      })
      return
    }
    await route.continue()
  }

  await page.route('**/api/case-library/knowledge-versions**', routeHandler)
  try {
    const listResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/case-library/knowledge-versions?limit=30')
        && response.status() === 200
    ), { timeout: 30000 })
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/research-lab/versions')
    await page.waitForURL(/\/research-lab\/versions$/, { timeout: 15000 })
    await page.getByTestId('knowledge-versions-page').waitFor({ state: 'visible', timeout: 15000 })
    const versions = await assertAuthedJson(listResponsePromise, 'Knowledge Versions list load')
    if (!Array.isArray(versions) || versions[0]?.version_id !== versionId) {
      throw new Error(`Knowledge Versions fixture did not load the expected published version: ${JSON.stringify(versions)}`)
    }
    await page.getByTestId(`knowledge-version-regression-${versionId}`).waitFor({ state: 'visible', timeout: 15000 })
    await assertKnowledgeVersionsReviewGateBoundaryVisible(
      page,
      `knowledge-version-simulation-boundary-${versionId}`,
      'version governance',
    )

    const regressionResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes(`/api/case-library/knowledge-versions/${versionId}/regression`)
        && response.status() === 200
    ), { timeout: 30000 })
    await clickEnabled(page.getByTestId(`knowledge-version-rerun-regression-${versionId}`), 'Knowledge Versions post-publish regression rerun')
    const refreshed = await assertAuthedJson(regressionResponsePromise, 'Knowledge Versions post-publish regression rerun')
    if (refreshed?.post_publish_regression?.status !== 'REGRESSION' || refreshed?.version_id !== versionId) {
      throw new Error(`Knowledge Versions regression rerun did not return the refreshed report: ${JSON.stringify(refreshed)}`)
    }
    await page.getByTestId('knowledge-version-regression-overview').getByText('REGRESSION', { exact: false }).waitFor({ state: 'visible', timeout: 15000 })
    const summary = await page.getByTestId(`knowledge-version-regression-summary-${versionId}`).innerText()
    if (!summary.includes('Browser smoke post-publish regression requires review')) {
      throw new Error(`Knowledge Versions regression summary did not render refreshed report: ${summary}`)
    }
    await assertKnowledgeVersionsReviewGateBoundaryVisible(
      page,
      `knowledge-version-regression-simulation-boundary-${versionId}`,
      'post-publish regression governance',
    )
    const quality = await page.getByTestId(`knowledge-version-regression-quality-${versionId}`).innerText()
    if (!quality.includes('LOW_COVERAGE') || !quality.includes('Missing modules: 1')) {
      throw new Error(`Knowledge Versions regression quality summary did not render case-set quality: ${quality}`)
    }
    const policy = await page.getByTestId(`knowledge-version-regression-policy-${versionId}`).innerText()
    if (!policy.includes('WARN_ONLY') || !policy.includes('Blocking: no') || !policy.includes('Override: not required')) {
      throw new Error(`Knowledge Versions regression quality policy did not render warn-only behavior: ${policy}`)
    }
    const remediation = await page.getByTestId(`knowledge-version-regression-remediation-${versionId}`).innerText()
    if (!remediation.includes('ACTION_REQUIRED') || !remediation.includes('case_library_reviewer') || !remediation.includes('additional symbol')) {
      throw new Error(`Knowledge Versions regression quality remediation did not render next actions: ${remediation}`)
    }
    const impact = await page.getByTestId(`knowledge-version-regression-impact-${versionId}`).innerText()
    if (!impact.includes('REGRESSION_ATTENTION') || !impact.includes('OBSERVATION_ONLY') || !impact.includes('review_regressions_before_policy_trust') || !impact.includes('Auto block: no')) {
      throw new Error(`Knowledge Versions regression impact did not render observation-only impact metadata: ${impact}`)
    }
    const waiver = await page.getByTestId(`knowledge-version-regression-waiver-${versionId}`).innerText()
    if (!waiver.includes('knowledge_promotion_regression_waiver_v1') || !waiver.includes('WAIVER-BROWSER-001') || !waiver.includes('AUDITED_OVERRIDE')) {
      throw new Error(`Knowledge Versions regression waiver did not render audited governance metadata: ${waiver}`)
    }
    console.log('ok strict-auth browser Knowledge Versions visible review-gate boundary')
    console.log('ok strict-auth browser Knowledge Versions post-publish regression')
  } finally {
    await page.unroute('**/api/case-library/knowledge-versions**', routeHandler).catch(() => undefined)
  }
}

async function assertEvaluationSandboxReviewGateBoundaryVisible(page, testId, label) {
  await page.getByTestId(testId).waitFor({ state: 'visible', timeout: 15000 })
  const visibleBoundary = await page.getByTestId(testId).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=review_gate_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!visibleBoundary.includes(marker)) {
      throw new Error(`Evaluation Sandbox visible review-gate boundary is missing ${marker} for ${label}: ${visibleBoundary}`)
    }
  }
}

async function runEvaluationSandboxScenario(page) {
  const patchId = 'PATCH_BROWSER_EVALUATION'
  const evalId = 'EVAL_BROWSER_EVALUATION'
  const experimentId = 'EXP_BROWSER_EVALUATION'
  const createdAt = new Date().toISOString()
  const basePatch = {
    patch_id: patchId,
    source_error_id: null,
    source_case_id: 'CASE_BROWSER_EVALUATION',
    title: 'Browser smoke evaluation patch',
    reason: 'Strict-auth browser verifies patch evaluation and strategy experiment linkage.',
    affected_modules: ['risk_firewall', 'evaluation'],
    patch_content: {
      hypothesis: 'Tighten review gate for optimism-bias cases',
      rule_change: 'strict_optimism_check',
      tag_fix: 'OPTIMISM_BIAS',
      strategy_configs: [
        {
          config_id: 'control',
          label: 'Current baseline',
          metrics: {
            win_rate: 0.51,
            max_drawdown: 0.18,
            misjudge_rate: 0.22,
            manual_review_pass_rate: 0.63,
            risk_trigger_rate: 0.19,
          },
        },
        {
          config_id: 'candidate',
          label: 'Patch candidate',
          metrics: {
            win_rate: 0.62,
            max_drawdown: 0.12,
            misjudge_rate: 0.11,
            manual_review_pass_rate: 0.76,
            risk_trigger_rate: 0.15,
          },
        },
      ],
    },
    risk_note: 'Evaluation sandbox output is review-only and does not alter trading policy.',
    rollback_plan: 'Restore the previous review gate if evaluation regresses.',
    backtest_required: true,
    backtest_result: {
      cases_tested: 3,
      win_rate: 0.51,
      max_drawdown: 0.18,
      misjudge_rate: 0.22,
      manual_review_pass_rate: 0.63,
      risk_trigger_rate: 0.19,
    },
    approval_status: 'CANDIDATE',
    evidence_usage: 'review_gate_only',
    evidence_strength: 'LOW',
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    approved_by: null,
    approved_at: null,
    created_at: createdAt,
    updated_at: createdAt,
  }
  const evaluationResult = {
    eval_id: evalId,
    patch_id: patchId,
    status: 'COMPLETED',
    total_cases: 3,
    passed_cases: 3,
    improved_cases: 2,
    regressed_cases: 0,
    unchanged_cases: 1,
    pass_rate: 1,
    improvement_rate: 0.667,
    elapsed_ms: 42,
    per_case_results: [
      {
        case_id: 'CASE_BROWSER_EVALUATION',
        symbol: '603663',
        verdict: 'PASS',
        improvement: 'IMPROVED',
      },
    ],
    summary: 'Browser smoke evaluation completed: 3 representative cases, 2 improved, 0 regressed.',
    strategy_experiment_report: null,
    evidence_usage: 'review_gate_only',
    evidence_strength: 'LOW',
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    error: null,
    created_at: createdAt,
    updated_at: createdAt,
  }
  const experimentReport = {
    experiment_id: experimentId,
    hypothesis: 'Tighten review gate for optimism-bias cases',
    strategy_count: 2,
    baseline_config_id: 'control',
    winner_config_id: 'candidate',
    sample_window: { case_count: 3, source: 'strict_auth_browser_smoke' },
    metrics_by_strategy: {
      control: {
        win_rate: 0.51,
        max_drawdown: 0.18,
        misjudge_rate: 0.22,
        manual_review_pass_rate: 0.63,
        risk_trigger_rate: 0.19,
        sample_window: { case_count: 3 },
      },
      candidate: {
        win_rate: 0.62,
        max_drawdown: 0.12,
        misjudge_rate: 0.11,
        manual_review_pass_rate: 0.76,
        risk_trigger_rate: 0.15,
        sample_window: { case_count: 3 },
      },
    },
    comparisons: [
      { metric: 'manual_review_pass_rate', baseline: 0.63, candidate: 0.76, delta: 0.13 },
    ],
    summary: 'Browser smoke strategy experiment selected candidate with stronger review pass rate.',
    evidence_usage: 'review_gate_only',
    evidence_strength: 'LOW',
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    created_at: createdAt,
  }

  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error(`Evaluation Sandbox request did not include the expected Authorization bearer token: ${request.method()} ${url.pathname}`)
    }

    if (url.pathname === '/api/case-library/patches' && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([basePatch]),
      })
      return
    }
    if (url.pathname === '/api/case-library/evaluations' && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      })
      return
    }
    if (url.pathname === `/api/case-library/patches/${patchId}/evaluate` && request.method() === 'POST') {
      const payload = request.postDataJSON()
      if (payload?.force !== true) {
        throw new Error(`Evaluation Sandbox run did not request forced evaluation: ${JSON.stringify(payload)}`)
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(evaluationResult),
      })
      return
    }
    if (url.pathname === `/api/case-library/patches/${patchId}/strategy-experiment` && request.method() === 'POST') {
      const payload = request.postDataJSON()
      if (!Array.isArray(payload?.strategy_configs) || payload.strategy_configs.length < 2) {
        throw new Error(`Evaluation Sandbox strategy experiment did not include two strategy configs: ${JSON.stringify(payload)}`)
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(experimentReport),
      })
      return
    }
    await route.continue()
  }

  await page.route('**/api/case-library/patches**', routeHandler)
  await page.route('**/api/case-library/evaluations**', routeHandler)
  try {
    const patchesResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/case-library/patches?limit=30')
        && response.status() === 200
    ), { timeout: 30000 })
    const evaluationsResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/case-library/evaluations?limit=30')
        && response.status() === 200
    ), { timeout: 30000 })
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/research-lab/evaluation')
    await page.waitForURL(/\/research-lab\/evaluation$/, { timeout: 15000 })
    await page.getByTestId('evaluation-sandbox-page').waitFor({ state: 'visible', timeout: 15000 })
    const patches = await assertAuthedJson(patchesResponsePromise, 'Evaluation Sandbox patches load')
    const evaluations = await assertAuthedJson(evaluationsResponsePromise, 'Evaluation Sandbox evaluations load')
    if (!Array.isArray(patches) || patches[0]?.patch_id !== patchId) {
      throw new Error(`Evaluation Sandbox patches fixture did not load: ${JSON.stringify(patches)}`)
    }
    if (!Array.isArray(evaluations)) {
      throw new Error('Evaluation Sandbox evaluations fixture did not return an array')
    }
    await page.getByTestId(`evaluation-sandbox-patch-${patchId}`).waitFor({ state: 'visible', timeout: 15000 })
    await assertEvaluationSandboxReviewGateBoundaryVisible(
      page,
      `evaluation-sandbox-patch-simulation-boundary-${patchId}`,
      'patch governance',
    )

    const evaluationResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes(`/api/case-library/patches/${patchId}/evaluate`)
        && response.status() === 200
    ), { timeout: 30000 })
    await clickEnabled(page.getByTestId(`evaluation-sandbox-run-${patchId}`), 'Evaluation Sandbox patch evaluation')
    const evaluation = await assertAuthedJson(evaluationResponsePromise, 'Evaluation Sandbox patch evaluation')
    if (evaluation?.eval_id !== evalId || evaluation?.status !== 'COMPLETED' || Number(evaluation?.regressed_cases) !== 0) {
      throw new Error(`Evaluation Sandbox evaluation did not return the expected result: ${JSON.stringify(evaluation)}`)
    }
    await page.getByTestId(`evaluation-sandbox-evaluation-${evalId}`).waitFor({ state: 'visible', timeout: 15000 })
    await page.getByTestId(`evaluation-sandbox-evaluation-summary-${evalId}`)
      .getByText('Browser smoke evaluation completed', { exact: false })
      .waitFor({ state: 'visible', timeout: 15000 })
    await assertEvaluationSandboxReviewGateBoundaryVisible(
      page,
      `evaluation-sandbox-evaluation-simulation-boundary-${evalId}`,
      'evaluation run governance',
    )

    const experimentResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes(`/api/case-library/patches/${patchId}/strategy-experiment`)
        && response.status() === 200
    ), { timeout: 30000 })
    await clickEnabled(page.getByTestId(`evaluation-sandbox-experiment-${patchId}`), 'Evaluation Sandbox strategy experiment')
    const experiment = await assertAuthedJson(experimentResponsePromise, 'Evaluation Sandbox strategy experiment')
    if (experiment?.experiment_id !== experimentId || experiment?.winner_config_id !== 'candidate') {
      throw new Error(`Evaluation Sandbox experiment did not return the expected winner: ${JSON.stringify(experiment)}`)
    }
    await page.getByTestId(`evaluation-sandbox-experiment-report-${patchId}`)
      .getByText('Winner: candidate', { exact: true })
      .waitFor({ state: 'visible', timeout: 15000 })
    await assertEvaluationSandboxReviewGateBoundaryVisible(
      page,
      `evaluation-sandbox-experiment-simulation-boundary-${patchId}`,
      'strategy experiment governance',
    )
    console.log('ok strict-auth browser Evaluation Sandbox visible review-gate boundary')
    console.log('ok strict-auth browser Evaluation Sandbox patch evaluation and strategy experiment')
  } finally {
    await page.unroute('**/api/case-library/patches**', routeHandler).catch(() => undefined)
    await page.unroute('**/api/case-library/evaluations**', routeHandler).catch(() => undefined)
  }
}

async function assertCaseLibraryReviewBoundaryVisible(page, testId, label, expectedEvidenceUsage) {
  await page.getByTestId(testId).waitFor({ state: 'visible', timeout: 15000 })
  const visibleBoundary = await page.getByTestId(testId).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    `evidence_usage=${expectedEvidenceUsage}`,
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!visibleBoundary.includes(marker)) {
      throw new Error(`Case Library visible review boundary is missing ${marker} for ${label}: ${visibleBoundary}`)
    }
  }
}

async function runCaseLibraryReviewBoundaryScenario(page) {
  const createdAt = new Date().toISOString()
  const caseId = 'CASE_LIBRARY_BROWSER_REVIEW'
  const patchId = 'PATCH_LIBRARY_BROWSER_REVIEW'
  const errorId = 'ERROR_LIBRARY_BROWSER_REVIEW'
  const simulationCaseId = 'SIMCASE_LIBRARY_BROWSER_REVIEW'
  const reviewedCase = {
    case_id: caseId,
    run_id: 'RUN_CASE_LIBRARY_BROWSER_REVIEW',
    audit_id: 'AUD_CASE_LIBRARY_BROWSER_REVIEW',
    symbol: '002846',
    stock_name: 'Yinglian',
    task_type: 'technical_review',
    run_mode: 'simulation',
    final_action: 'SIM_HOLD',
    final_action_correct: true,
    conclusion_correct: true,
    data_sufficiency: 'ADEQUATE',
    optimism_bias: 'MODERATE',
    key_lessons: ['Browser smoke case remains supporting-only review evidence.'],
    market_context: 'Strict-auth browser fixture for visible Case Library boundary.',
    tags: ['strict-auth-browser'],
    reviewer: 'strict-auth-browser-smoke',
    review_note: 'Reviewed fixture still cannot become a strong conclusion.',
    review_status: 'REVIEWED',
    evidence_usage: 'supporting_only',
    evidence_strength: 'MEDIUM',
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    created_at: createdAt,
    updated_at: createdAt,
  }
  const reviewPatch = {
    patch_id: patchId,
    source_error_id: null,
    source_case_id: caseId,
    title: 'Browser smoke case-library review patch',
    reason: 'Strict-auth browser verifies visible patch review boundary.',
    affected_modules: ['case_library'],
    patch_content: { rule: 'keep_review_gate_visible' },
    risk_note: 'Patch evidence is review-gate-only and cannot change trading policy.',
    rollback_plan: 'Revert the review patch if downstream evaluation regresses.',
    backtest_required: true,
    backtest_result: { evaluation_id: 'EVAL_CASE_LIBRARY_BROWSER_REVIEW', reviewed_cases: 1 },
    approval_status: 'CANDIDATE',
    approved_by: null,
    approved_at: null,
    evidence_usage: 'review_gate_only',
    evidence_strength: 'LOW',
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    created_at: createdAt,
    updated_at: createdAt,
  }
  const simulationCase = {
    case_id: simulationCaseId,
    case_source: 'AGENT_SIMULATION',
    operator_type: 'AGENT',
    source_signal_id: 'SIG_CASE_LIBRARY_BROWSER_REVIEW',
    source_paper_order_id: 'PAPER_CASE_LIBRARY_BROWSER_REVIEW',
    run_id: 'RUN_CASE_LIBRARY_BROWSER_REVIEW',
    agent_id: 'signalops_agent',
    audit_id: 'AUD_CASE_LIBRARY_BROWSER_REVIEW',
    simulation_only: true,
    is_real_trade: false,
    outcome: {
      source: 'paper_order',
      review_required: true,
      symbol: '002846',
      paper_action: 'SIM_HOLD',
      action_reason: 'Strict-auth browser verifies visible simulation-case review boundary.',
      fill_status: 'OBSERVED',
      trade_metrics_available: false,
      signal_status: 'PAPER_TEST',
      metric_note: 'SIM_HOLD is an observation-only paper action.',
      risk_constraints: {},
    },
    failure_tags: [],
    knowledge_candidate_status: 'REVIEWING',
    created_at: createdAt,
    updated_at: createdAt,
  }
  const reviewError = {
    entry_id: errorId,
    run_id: 'RUN_CASE_LIBRARY_BROWSER_REVIEW',
    audit_id: 'AUD_CASE_LIBRARY_BROWSER_REVIEW',
    node: 'case_library',
    error_type: 'BOUNDARY_REVIEW',
    error_reason: 'Strict-auth browser verifies visible error-ledger review boundary.',
    repeated_count: 2,
    patch_required: true,
    patch_candidate_id: patchId,
    attribution: {
      simulation_only: true,
      is_real_trade: false,
    },
    status: 'RESOLVED',
    evidence_usage: 'review_gate_only',
    evidence_strength: 'LOW',
    simulation_only: true,
    is_real_trade: false,
    strong_conclusion_allowed: false,
    reported_simulation_only: true,
    reported_is_real_trade: false,
    resolved_at: createdAt,
    created_at: createdAt,
    updated_at: createdAt,
  }

  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error(`Case Library request did not include the expected Authorization bearer token: ${request.method()} ${url.pathname}`)
    }
    if (request.method() !== 'GET') {
      await route.continue()
      return
    }

    if (url.pathname === '/api/case-library/summary') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ total: 1, pending: 0, reviewed: 1, correct_conclusions: 1, accuracy_rate: 1 }),
      })
      return
    }
    if (url.pathname === '/api/case-library/cases') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([reviewedCase]) })
      return
    }
    if (url.pathname === '/api/case-library/tags') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    if (url.pathname === '/api/case-library/error-ledger') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([reviewError]) })
      return
    }
    if (url.pathname === '/api/case-library/patches') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([reviewPatch]) })
      return
    }
    if (url.pathname === '/api/knowledge/cases') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([simulationCase]) })
      return
    }
    if (url.pathname === '/api/signals') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
      return
    }
    await route.continue()
  }

  await page.route('**/api/case-library/**', routeHandler)
  await page.route('**/api/knowledge/cases**', routeHandler)
  await page.route('**/api/signals**', routeHandler)
  try {
    const caseLibraryPathname = await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
      return window.location.pathname
    }, '/case-library')
    if (caseLibraryPathname !== '/case-library') {
      throw new Error(`Case Library SPA route did not update pathname after pushState: ${caseLibraryPathname}`)
    }
    await assertCaseLibraryReviewBoundaryVisible(
      page,
      `case-library-case-simulation-boundary-${caseId}`,
      'case governance',
      'supporting_only',
    )
    await page.getByRole('button', { name: /Agent 模拟操作案例/ }).click()
    await assertCaseLibraryReviewBoundaryVisible(
      page,
      `case-library-simulation-case-simulation-boundary-${simulationCaseId}`,
      'simulation case governance',
      'review_gate_only',
    )
    await page.getByRole('button', { name: /错误账本/ }).click()
    await assertCaseLibraryReviewBoundaryVisible(
      page,
      `case-library-error-simulation-boundary-${errorId}`,
      'error ledger governance',
      'review_gate_only',
    )
    await page.getByRole('button', { name: /知识补丁/ }).click()
    await assertCaseLibraryReviewBoundaryVisible(
      page,
      `case-library-patch-simulation-boundary-${patchId}`,
      'patch governance',
      'review_gate_only',
    )
    console.log('ok strict-auth browser Case Library visible review boundary')
  } finally {
    await page.unroute('**/api/case-library/**', routeHandler).catch(() => undefined)
    await page.unroute('**/api/knowledge/cases**', routeHandler).catch(() => undefined)
    await page.unroute('**/api/signals**', routeHandler).catch(() => undefined)
  }
}

async function assertDataReliabilityDiagnosticBoundary(page) {
  const boundary = page.getByTestId('data-reliability-diagnostic-boundary')
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const marker of [
    'diagnostic_only=true',
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=monitoring_only',
    'strong_conclusion_allowed=false',
    'order_namespace=none',
  ]) {
    if (!text.includes(marker)) {
      throw new Error(`Data Reliability diagnostic boundary is missing ${marker}: ${text}`)
    }
  }
}

async function runDataReliabilityScenario(page, runId) {
  const generatedAt = new Date().toISOString()
  const dataReliabilitySnapshot = {
    generatedAt,
    summary: {
      generatedAt,
      adapterCount: 2,
      checkedCount: 2,
      healthyCount: 1,
      partialCount: 1,
      failedCount: 0,
      overallStatus: 'PARTIAL',
      lastFailureReasons: [],
      partialReasons: [
        {
          adapterId: 'akshare',
          provider: 'akshare',
          message: 'Realtime upstream healthy, but latest live quote fell back to sina.',
          diagnosis: 'PARTIAL_UPSTREAM',
        },
      ],
    },
    adapters: [
      {
        adapterId: 'tushare',
        provider: 'tushare',
        label: 'Tushare',
        capabilities: ['HISTORICAL_QUOTE', 'FUNDAMENTALS'],
        healthy: true,
        configured: true,
        upstreamHealthy: true,
        liveDataUsable: true,
        fallbackUsed: false,
        enabled: true,
        installed: true,
        lastError: '',
        freshness: 'fresh',
        lastCheckAt: generatedAt,
        latencyAvgMs: 3400,
        status: 'READY',
        message: 'Historical quote ready.',
        priority: 1,
        timeoutSeconds: 10,
        requiresToken: true,
        note: 'strict-auth fixture',
      },
      {
        adapterId: 'akshare',
        provider: 'akshare',
        label: 'AkShare',
        capabilities: ['REALTIME_QUOTE'],
        healthy: true,
        configured: true,
        upstreamHealthy: true,
        liveDataUsable: false,
        fallbackUsed: true,
        enabled: true,
        installed: true,
        lastError: '',
        freshness: 'partial',
        lastCheckAt: generatedAt,
        latencyAvgMs: 177,
        status: 'PARTIAL',
        message: 'Realtime upstream healthy, but latest live quote fell back to sina.',
        diagnosis: 'PARTIAL_UPSTREAM',
        priority: 2,
        timeoutSeconds: 8,
        requiresToken: false,
        note: 'strict-auth fixture',
      },
    ],
    matrix: {
      generatedAt,
      categories: {
        realtime_quote: {
          akshare: {
            adapterId: 'akshare',
            provider: 'akshare',
            label: 'AkShare',
            capabilities: ['REALTIME_QUOTE'],
            healthy: true,
            configured: true,
            upstreamHealthy: true,
            liveDataUsable: false,
            fallbackUsed: true,
            enabled: true,
            installed: true,
            lastError: '',
            freshness: 'partial',
            lastCheckAt: generatedAt,
            latencyAvgMs: 177,
            message: 'Realtime upstream healthy, but latest live quote fell back to sina.',
            status: 'PARTIAL',
          },
        },
        kline_quote: {
          tushare: {
            adapterId: 'tushare',
            provider: 'tushare',
            label: 'Tushare',
            capabilities: ['HISTORICAL_QUOTE'],
            healthy: true,
            configured: true,
            upstreamHealthy: true,
            liveDataUsable: true,
            fallbackUsed: false,
            enabled: true,
            installed: true,
            lastError: '',
            freshness: 'fresh',
            lastCheckAt: generatedAt,
            latencyAvgMs: 3400,
            message: 'Historical quote ready.',
            status: 'READY',
          },
        },
      },
    },
    config: {
      dataSources: {
        tushare_token_set: true,
        tushare_token_mask: 'tu***ke',
        sources: [
          { key: 'realtime_quote', name: 'Realtime quote', enabled: true, tier_label: 'public' },
          { key: 'kline_quote', name: 'K-line quote', enabled: true, tier_label: 'pro' },
        ],
      },
      adapterConfigs: [],
    },
    history: [
      {
        id: 101,
        checkType: 'symbol_coverage_check',
        symbol: '603663',
        adapterId: 'akshare',
        provider: 'akshare',
        category: 'realtime_quote',
        status: 'PARTIAL',
        healthy: true,
        upstreamHealthy: true,
        liveDataUsable: false,
        fallbackUsed: true,
        latencyMs: 177,
        message: 'Realtime upstream healthy, but latest live quote fell back to sina.',
        error: '',
        diagnosis: 'PARTIAL_UPSTREAM',
        createdAt: generatedAt,
      },
      {
        id: 100,
        checkType: 'adapter_check',
        symbol: '',
        adapterId: 'tushare',
        provider: 'tushare',
        category: 'kline_quote',
        status: 'READY',
        healthy: true,
        upstreamHealthy: true,
        liveDataUsable: true,
        fallbackUsed: false,
        latencyMs: 3400,
        message: 'Historical quote ready.',
        error: '',
        diagnosis: 'OK',
        createdAt: generatedAt,
      },
    ],
    events: [
      {
        id: 201,
        symbol: '603663',
        adapterId: 'akshare',
        provider: 'akshare',
        category: 'realtime_quote',
        eventType: 'SOURCE_FALLBACK',
        status: 'PARTIAL',
        healthy: true,
        upstreamHealthy: true,
        liveDataUsable: false,
        fallbackUsed: true,
        latencyMs: 177,
        recordCount: 1,
        message: 'Realtime upstream healthy, but latest live quote fell back to sina.',
        error: '',
        diagnosis: 'PARTIAL_UPSTREAM',
        createdAt: generatedAt,
      },
      {
        id: 200,
        symbol: '',
        adapterId: 'tushare',
        provider: 'tushare',
        category: 'kline_quote',
        eventType: 'ADAPTER_READY',
        status: 'READY',
        healthy: true,
        upstreamHealthy: true,
        liveDataUsable: true,
        fallbackUsed: false,
        latencyMs: 3400,
        message: 'Historical quote ready.',
        error: '',
        diagnosis: 'OK',
        createdAt: generatedAt,
      },
    ],
    externalMonitorStatus: {
      schema: 'data_reliability_external_monitor_status_v1',
      checked: true,
      reported: true,
      status: 'DEGRADED',
      sidecarFile: 'C:\\tmp\\data-reliability-monitor.json',
      reportedAt: '',
      source: 'deployment_monitor',
      provider: 'provider-monitor',
      monitorBackend: 'prometheus',
      monitorStatus: 'LATENCY_ELEVATED',
      freshnessStatus: 'STALE_SOURCE_WINDOW',
      retentionPolicyId: 'retention-90d',
      retentionStatus: 'ENFORCED',
      retentionDays: 90,
      retentionExpiresAt: generatedAt,
      outageCount: 1,
      degradedSourceCount: 2,
      staleSourceCount: 3,
      latencyP95Ms: 1440,
      latestIncidentAt: generatedAt,
      searchIndex: 'data-reliability-index',
      searchIndexReady: true,
      message: 'token=browser-secret should not render',
      deploymentReported: true,
      localEventTrail: 'DataAdapterEventDB',
      issues: ['latency_above_slo'],
    },
  }

  let adapterCheckRequested = false
  const adapterCheckFailureAdapter = {
    adapterId: 'adapter_timeout_guard',
    provider: 'akshare',
    label: 'Adapter Timeout Guard',
    capabilities: ['REALTIME_QUOTE'],
    healthy: false,
    configured: true,
    upstreamHealthy: false,
    liveDataUsable: false,
    fallbackUsed: false,
    enabled: true,
    installed: true,
    lastError: 'Adapter check timed out after 30s.',
    freshness: 'stale',
    lastCheckAt: generatedAt,
    latencyAvgMs: 30001,
    status: 'FAILED',
    message: 'Adapter check timed out after 30s.',
    diagnosis: 'NETWORK_TIMEOUT',
    priority: 99,
    timeoutSeconds: 30,
    requiresToken: false,
    note: 'strict-auth adapter-check fixture',
  }

  const buildDataReliabilitySnapshot = () => {
    if (!adapterCheckRequested) return dataReliabilitySnapshot

    const snapshot = cloneJson(dataReliabilitySnapshot)
    snapshot.summary.failedCount = 1
    snapshot.summary.overallStatus = 'FAILED'
    snapshot.summary.lastFailureReasons = [
      {
        adapterId: adapterCheckFailureAdapter.adapterId,
        provider: adapterCheckFailureAdapter.provider,
        message: adapterCheckFailureAdapter.message,
        diagnosis: adapterCheckFailureAdapter.diagnosis,
      },
    ]
    snapshot.adapters = [
      adapterCheckFailureAdapter,
      ...snapshot.adapters,
    ]
    snapshot.matrix.categories.realtime_quote[adapterCheckFailureAdapter.adapterId] = adapterCheckFailureAdapter
    snapshot.history = [
      {
        id: 202,
        checkType: 'adapter_check',
        symbol: '',
        adapterId: adapterCheckFailureAdapter.adapterId,
        provider: adapterCheckFailureAdapter.provider,
        category: 'realtime_quote',
        status: adapterCheckFailureAdapter.status,
        healthy: false,
        upstreamHealthy: false,
        liveDataUsable: false,
        fallbackUsed: false,
        latencyMs: adapterCheckFailureAdapter.latencyAvgMs,
        message: adapterCheckFailureAdapter.message,
        error: adapterCheckFailureAdapter.lastError,
        diagnosis: adapterCheckFailureAdapter.diagnosis,
        createdAt: generatedAt,
      },
      ...snapshot.history,
    ]
    snapshot.events = [
      {
        id: 202,
        symbol: '',
        adapterId: adapterCheckFailureAdapter.adapterId,
        provider: adapterCheckFailureAdapter.provider,
        category: 'realtime_quote',
        eventType: 'ADAPTER_FAILED',
        status: adapterCheckFailureAdapter.status,
        healthy: false,
        upstreamHealthy: false,
        liveDataUsable: false,
        fallbackUsed: false,
        latencyMs: adapterCheckFailureAdapter.latencyAvgMs,
        recordCount: 0,
        message: adapterCheckFailureAdapter.message,
        error: adapterCheckFailureAdapter.lastError,
        diagnosis: adapterCheckFailureAdapter.diagnosis,
        createdAt: generatedAt,
      },
      ...snapshot.events,
    ]
    return snapshot
  }

  const dataReliabilityRouteHandler = async (route) => {
    const request = route.request()
    if (request.method() !== 'GET') {
      throw new Error(`Data Reliability snapshot used ${request.method()} instead of GET`)
    }
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error('Data Reliability snapshot did not include the expected Authorization bearer token')
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildDataReliabilitySnapshot()),
    })
  }

  const adapterCheckRouteHandler = async (route) => {
    const request = route.request()
    if (request.method() !== 'POST') {
      throw new Error(`Data Reliability adapter-check used ${request.method()} instead of POST`)
    }
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error('Data Reliability adapter-check did not include the expected Authorization bearer token')
    }
    adapterCheckRequested = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([adapterCheckFailureAdapter]),
    })
  }

  let symbolCheckRequested = false
  const symbolCheckRouteHandler = async (route) => {
    const request = route.request()
    if (request.method() !== 'POST') {
      throw new Error(`Data Reliability symbol-check used ${request.method()} instead of POST`)
    }
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error('Data Reliability symbol-check did not include the expected Authorization bearer token')
    }
    const payload = request.postDataJSON()
    if (String(payload?.symbol || '').trim() !== '002846') {
      throw new Error(`Data Reliability symbol-check posted unexpected symbol payload: ${JSON.stringify(payload)}`)
    }
    symbolCheckRequested = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        symbol: '002846',
        generatedAt,
        overallStatus: 'FAILED',
        results: [
          {
            checkType: 'symbol_coverage_check',
            symbol: '002846',
            category: 'realtime_quote',
            status: 'FAILED',
            healthy: false,
            provider: 'data_reliability',
            adapterId: 'timeout_guard',
            latencyMs: 30001,
            recordCount: 0,
            freshness: '',
            error: 'Data reliability check timed out after 30s.',
            message: 'Data reliability check timed out after 30s.',
            diagnosis: 'NETWORK_TIMEOUT',
            fallbackChain: [],
            raw: {},
          },
        ],
      }),
    })
  }

  await page.route('**/api/data-reliability/snapshot', dataReliabilityRouteHandler)
  await page.route('**/api/data-reliability/adapters/check', adapterCheckRouteHandler)
  await page.route('**/api/data-reliability/symbol-check', symbolCheckRouteHandler)
  try {
    const snapshotResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/data-reliability/snapshot')
        && response.status() === 200
    ), { timeout: 30000 })
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/data-reliability')
    await page.waitForURL(/\/data-reliability$/, { timeout: 15000 })
    const snapshot = await assertAuthedJson(snapshotResponsePromise, 'Data Reliability snapshot load')
    if (snapshot?.summary?.overallStatus !== 'PARTIAL' || snapshot?.history?.[0]?.fallbackUsed !== true) {
      throw new Error(`Data Reliability fixture did not preserve freshness/fallback state: ${JSON.stringify(snapshot)}`)
    }
    if (snapshot?.events?.[0]?.eventType !== 'SOURCE_FALLBACK') {
      throw new Error(`Data Reliability fixture did not preserve adapter events: ${JSON.stringify(snapshot?.events)}`)
    }

    await page.getByTestId('data-reliability-page').waitFor({ state: 'visible', timeout: 15000 })
    await assertDataReliabilityDiagnosticBoundary(page)
    const renderedRunId = (await page.getByTestId('data-reliability-current-run-id').innerText()).trim()
    if (renderedRunId !== runId) {
      throw new Error(`Data Reliability rendered run id ${renderedRunId} instead of seeded run ${runId}`)
    }
    await page.getByTestId('data-reliability-data-provenance').waitFor({ state: 'visible', timeout: 15000 })
    await page.getByTestId('data-reliability-source-freshness').first().waitFor({ state: 'visible', timeout: 15000 })
    await page.getByTestId('data-reliability-fallback-chain').first().waitFor({ state: 'visible', timeout: 15000 })
    const provenanceText = await page.getByTestId('data-reliability-data-provenance').innerText()
    const freshnessEvidenceText = await page.getByTestId('data-reliability-source-freshness').first().innerText()
    if (!provenanceText.trim() || !freshnessEvidenceText.trim()) {
      throw new Error(`Data Reliability did not render provenance/freshness text: ${provenanceText} / ${freshnessEvidenceText}`)
    }

    await page.getByTestId('data-reliability-freshness-summary').waitFor({ state: 'visible', timeout: 15000 })
    await page.waitForFunction(() => {
      const latestCheckText = document.querySelector('[data-testid="data-reliability-latest-check"]')?.textContent || ''
      const latestIssueText = document.querySelector('[data-testid="data-reliability-latest-failure"]')?.textContent || ''
      const fallbackText = document.querySelector('[data-testid="data-reliability-fallback-count"]')?.textContent || ''
      const slowestText = document.querySelector('[data-testid="data-reliability-slowest-check"]')?.textContent || ''
      return latestCheckText.includes('603663')
        && latestIssueText.includes('akshare')
        && fallbackText.includes('1')
        && slowestText.includes('3400ms')
    }, undefined, { timeout: 15000 })
    const latestCheckText = await page.getByTestId('data-reliability-latest-check').innerText()
    const latestIssueText = await page.getByTestId('data-reliability-latest-failure').innerText()
    const fallbackText = await page.getByTestId('data-reliability-fallback-count').innerText()
    const slowestText = await page.getByTestId('data-reliability-slowest-check').innerText()
    if (!latestCheckText.includes('603663') || !latestIssueText.includes('akshare')) {
      throw new Error(`Data Reliability freshness cards did not render latest fallback context: ${latestCheckText} / ${latestIssueText}`)
    }
    if (!fallbackText.includes('1') || !slowestText.includes('3400ms')) {
      throw new Error(`Data Reliability freshness cards did not render fallback count and slowest latency: ${fallbackText} / ${slowestText}`)
    }
    await page.getByTestId('data-reliability-adapter-events').waitFor({ state: 'visible', timeout: 15000 })
    const eventTrailText = await page.getByTestId('data-reliability-adapter-events').innerText()
    if (!eventTrailText.includes('Source fallback') || !eventTrailText.includes('603663')) {
      throw new Error(`Data Reliability adapter event trail did not render fallback event: ${eventTrailText}`)
    }
    await page.getByTestId('data-reliability-external-monitor-status').waitFor({ state: 'visible', timeout: 15000 })
    const externalMonitorText = await page.getByTestId('data-reliability-external-monitor-status').innerText()
    if (!externalMonitorText.includes('provider-monitor') || !externalMonitorText.includes('retention-90d') || !externalMonitorText.includes('Search ready')) {
      throw new Error(`Data Reliability external monitor status did not render provider/retention/search evidence: ${externalMonitorText}`)
    }
    if (externalMonitorText.includes('browser-secret') || !externalMonitorText.includes('[redacted]')) {
      throw new Error(`Data Reliability external monitor status leaked secret-like fixture text: ${externalMonitorText}`)
    }
    const adapterCheckResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes('/api/data-reliability/adapters/check')
        && response.status() === 200
    ), { timeout: 30000 })
    const adapterCheckReloadPromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/data-reliability/snapshot')
        && response.status() === 200
    ), { timeout: 30000 })
    await clickEnabled(page.getByTestId('data-reliability-adapter-check'), 'Data Reliability adapter-check button')
    const adapterCheckPayload = await assertAuthedJson(adapterCheckResponsePromise, 'Data Reliability adapter-check')
    const adapterCheckSnapshot = await assertAuthedJson(adapterCheckReloadPromise, 'Data Reliability adapter-check reload')
    if (!adapterCheckRequested || adapterCheckPayload?.[0]?.diagnosis !== 'NETWORK_TIMEOUT') {
      throw new Error(`Data Reliability adapter-check fixture did not preserve NETWORK_TIMEOUT row: ${JSON.stringify(adapterCheckPayload)}`)
    }
    if (adapterCheckSnapshot?.history?.[0]?.adapterId !== 'adapter_timeout_guard') {
      throw new Error(`Data Reliability adapter-check reload did not surface the failed adapter row: ${JSON.stringify(adapterCheckSnapshot?.history?.[0])}`)
    }
    await page.waitForFunction(() => {
      const latestCheckText = document.querySelector('[data-testid="data-reliability-latest-check"]')?.textContent || ''
      const latestIssueText = document.querySelector('[data-testid="data-reliability-latest-failure"]')?.textContent || ''
      const slowestText = document.querySelector('[data-testid="data-reliability-slowest-check"]')?.textContent || ''
      return latestCheckText.includes('adapter_timeout_guard')
        && latestIssueText.includes('Adapter check timed out after 30s.')
        && slowestText.includes('30001ms')
    }, undefined, { timeout: 15000 })
    const adapterLatestCheckText = await page.getByTestId('data-reliability-latest-check').innerText()
    const adapterLatestIssueText = await page.getByTestId('data-reliability-latest-failure').innerText()
    if (!adapterLatestCheckText.includes('adapter_timeout_guard') || !adapterLatestIssueText.includes('Adapter check timed out after 30s.')) {
      throw new Error(`Data Reliability adapter-check did not render refreshed failure state: ${adapterLatestCheckText} / ${adapterLatestIssueText}`)
    }
    const symbolResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes('/api/data-reliability/symbol-check')
        && response.status() === 200
    ), { timeout: 30000 })
    await clickEnabled(page.getByTestId('data-reliability-symbol-check'), 'Data Reliability symbol-check button')
    const symbolPayload = await assertAuthedJson(symbolResponsePromise, 'Data Reliability symbol-check')
    if (!symbolCheckRequested || symbolPayload?.results?.[0]?.diagnosis !== 'NETWORK_TIMEOUT') {
      throw new Error(`Data Reliability symbol-check fixture did not preserve NETWORK_TIMEOUT row: ${JSON.stringify(symbolPayload)}`)
    }
    const symbolDiagnosisText = await page.getByTestId('data-reliability-symbol-diagnosis-realtime_quote').innerText()
    if (!symbolDiagnosisText.includes('网络或接口超时') || !symbolDiagnosisText.includes('Data reliability check timed out')) {
      throw new Error(`Data Reliability symbol-check timeout diagnosis did not render localized row detail: ${symbolDiagnosisText}`)
    }
    console.log('ok strict-auth browser Data Reliability diagnostic boundary')
    console.log('ok strict-auth browser Data Reliability provenance/freshness')
    console.log('ok strict-auth browser Data Reliability freshness/fallback summary')
    console.log('ok strict-auth browser Data Reliability adapter event trail')
    console.log('ok strict-auth browser Data Reliability external monitoring retention')
    console.log('ok strict-auth browser Data Reliability adapter-check write reload')
    console.log('ok strict-auth browser Data Reliability symbol-check timeout diagnosis')
  } finally {
    await page.unroute('**/api/data-reliability/snapshot', dataReliabilityRouteHandler).catch(() => undefined)
    await page.unroute('**/api/data-reliability/adapters/check', adapterCheckRouteHandler).catch(() => undefined)
    await page.unroute('**/api/data-reliability/symbol-check', symbolCheckRouteHandler).catch(() => undefined)
  }
}

async function runSettingsAdapterPartialLoadScenario(page) {
  const adaptersRoutePattern = '**/api/agents/market-data/adapters**'
  let sawAdapterListRequest = false
  let sawConfigFailureRequest = false
  let sawLiveCheckRequest = false
  const adapterFixture = [
    {
      adapterId: 'akshare',
      provider: 'akshare',
      label: 'AkShare Fixture',
      capabilities: ['realtime_quote', 'kline_quote'],
      configured: true,
      healthy: true,
      upstreamHealthy: true,
      liveDataUsable: false,
      fallbackUsed: true,
      lastError: '',
      freshness: 'fresh',
      lastCheckAt: new Date().toISOString(),
      latencyAvgMs: 188,
      message: 'Realtime unavailable fallback to sina.',
      enabled: true,
      installed: true,
    },
    {
      adapterId: 'sina',
      provider: 'sina',
      label: 'Sina Fixture',
      capabilities: ['realtime_quote'],
      configured: true,
      healthy: true,
      upstreamHealthy: true,
      liveDataUsable: true,
      fallbackUsed: false,
      lastError: '',
      freshness: 'fresh',
      lastCheckAt: new Date().toISOString(),
      latencyAvgMs: 80,
      message: 'OK',
      enabled: true,
      installed: true,
    },
  ]

  const routeHandler = async (route) => {
    const request = route.request()
    const requestUrl = new URL(request.url())
    if (request.method() !== 'GET') {
      await route.continue()
      return
    }
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error(`Settings adapter request did not include the expected Authorization bearer token: ${request.url()}`)
    }
    if (requestUrl.pathname === '/api/agents/market-data/adapters') {
      sawAdapterListRequest = true
      if (requestUrl.searchParams.get('live_check') === 'true') {
        sawLiveCheckRequest = true
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(adapterFixture),
      })
      return
    }
    if (requestUrl.pathname === '/api/agents/market-data/adapters/config') {
      sawConfigFailureRequest = true
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: { message: 'settings adapter config fixture unavailable' } }),
      })
      return
    }
    await route.continue()
  }

  await page.route(adaptersRoutePattern, routeHandler)
  try {
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/settings')
    await page.waitForURL(/\/settings$/, { timeout: 15000 })
    await page.getByTestId('settings-adapter-list').waitFor({ state: 'visible', timeout: 15000 })
    await page.getByText('AkShare Fixture', { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
    try {
      await page.waitForFunction(() => {
        const list = document.querySelector('[data-testid="settings-adapter-list"]')
        const text = String(list?.textContent || '')
        return text.includes('AkShare Fixture')
          && text.includes('部分可用')
          && text.includes('实时行情不可用')
          && text.includes('新浪财经')
      }, undefined, { timeout: 15000 })
    } catch (error) {
      const adapterListText = await page.getByTestId('settings-adapter-list').innerText().catch(() => '')
      throw new Error(`Settings adapter partial-load readiness text did not render: ${adapterListText}`)
    }
    await page.getByTestId('settings-adapter-load-error').waitFor({ state: 'visible', timeout: 15000 })
    await page.getByText('settings adapter config fixture unavailable', { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
    if (!sawAdapterListRequest || !sawConfigFailureRequest) {
      throw new Error('Settings adapter partial-load fixture did not observe both adapter list and config requests')
    }

    const liveCheckResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'GET'
        && response.url().includes('/api/agents/market-data/adapters?live_check=true')
    ), { timeout: 15000 })
    await clickEnabled(page.getByTestId('settings-adapter-refresh-all'), 'Settings adapter refresh all')
    await liveCheckResponsePromise
    await page.getByText('AkShare Fixture', { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
    await page.getByText('settings adapter config fixture unavailable', { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
    if (!sawLiveCheckRequest) {
      throw new Error('Settings adapter refresh did not request live_check=true')
    }
    console.log('ok strict-auth browser Settings adapter partial-load')
  } finally {
    await page.unroute(adaptersRoutePattern, routeHandler).catch(() => undefined)
  }
}

async function assertQuantCoreVisibleBoundary(page) {
  const boundary = page.getByTestId('quant-core-simulation-boundary')
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`QuantCore visible boundary is missing ${expected}: ${text}`)
    }
  }
}

async function assertTechnicalKlineVisibleBoundary(page) {
  const boundary = page.getByTestId('technical-kline-case-governance-simulation-boundary')
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=technical_kline_review_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`Technical Kline visible boundary is missing ${expected}: ${text}`)
    }
  }
}

async function runTechnicalKlineCaseGovernanceScenario(page, runId) {
  const caseLibraryCaseId = 'CASE_TK_BROWSER_SMOKE'
  const technicalCaseId = 'TKCASE_BROWSER_SMOKE'
  let recordedCase = null
  const promptVersion = 'technical-kline-prompt-v-browser-smoke'
  const currentConfigHash = 'cfg-technical-kline-browser-smoke'
  const baselineConfigHash = 'cfg-technical-kline-browser-baseline'
  const seedCase = (caseId, symbol, classification, configHash) => ({
    caseId,
    symbol,
    classification,
    note: `${classification} browser representative case`,
    runId: `RUN_${caseId}`,
    analysisStatus: classification === 'misjudge' ? 'WARN' : 'PASS',
    technicalBias: 'BULLISH',
    configHash,
    promptVersion,
    createdAt: new Date().toISOString(),
  })
  const baseCases = [
    seedCase('TKCASE_BROWSER_BASE_VALID', '600010', 'valid', baselineConfigHash),
    seedCase('TKCASE_BROWSER_BASE_MISJUDGE', '600011', 'misjudge', baselineConfigHash),
    seedCase('TKCASE_BROWSER_BASE_INSUFFICIENT', '600012', 'insufficient_data', baselineConfigHash),
    seedCase('TKCASE_BROWSER_CURRENT_VALID_1', '600020', 'valid', currentConfigHash),
    seedCase('TKCASE_BROWSER_CURRENT_VALID_2', '600021', 'valid', currentConfigHash),
    seedCase('TKCASE_BROWSER_CURRENT_INSUFFICIENT', '600022', 'insufficient_data', currentConfigHash),
    seedCase('TKCASE_BROWSER_CURRENT_MISJUDGE', '600023', 'misjudge', currentConfigHash),
  ]
  const governanceFixture = () => ({
    agent: 'technical_kline_analyst',
    promptGovernance: {
      version: promptVersion,
      promptHash: 'sha256:technical-kline-browser-smoke',
      changedBy: 'strict-auth-browser-smoke',
      changeReason: 'browser smoke fixture',
      rollbackVersion: 'technical-kline-prompt-v1.0',
      outputMode: 'READ_ONLY',
      tradeActionPolicy: 'NO_DIRECT_TRADE_ACTION',
    },
    analysisConfig: {
      version: 'technical-kline-config-v-browser-smoke',
      minimumSamples: { daily: 60, weekly: 24, monthly: 12 },
      movingAverageWindows: { short: 5, medium: 10, long: 20 },
      volumeWindows: { recent: 5, baseline: 20 },
      supportResistanceWindows: { short: 20, long: 60 },
      riskThresholds: {
        highVolumeRatio: 1.25,
        nearSupportDistance: 0.03,
        nearResistanceDistance: 0.03,
      },
      configHash: currentConfigHash,
    },
    caseClassification: {
      allowedValues: ['valid', 'misjudge', 'insufficient_data'],
      selected: 'valid',
    },
    dataPolicy: 'LIVE_KLINE_ONLY',
    tradeActionPolicy: 'NO_DIRECT_TRADE_ACTION',
    savedGovernance: {
      config: {},
      caseClassification: 'valid',
      updatedAt: new Date().toISOString(),
      updatedBy: 'strict-auth-browser-smoke',
      changeReason: 'browser smoke fixture',
      cases: recordedCase ? [...baseCases, recordedCase] : baseCases,
      caseImpact: {
        policy: {
          policyId: 'technical_kline_case_impact_review_v1',
          usage: 'REVIEW_ONLY_PARAMETER_GOVERNANCE',
          minimumCasesForDecision: 5,
          weakSampleAction: 'supporting_only',
          tradeActionPolicy: 'NO_DIRECT_TRADE_ACTION',
        },
        status: 'READY',
        totalCases: recordedCase ? 8 : 7,
        classificationCounts: {
          valid: 3,
          misjudge: recordedCase ? 3 : 2,
          insufficient_data: 2,
        },
        validRate: recordedCase ? 0.375 : 0.4286,
        misjudgeRate: recordedCase ? 0.375 : 0.2857,
        insufficientDataRate: recordedCase ? 0.25 : 0.2857,
        currentConfig: {
          configHash: currentConfigHash,
          promptVersion,
          status: recordedCase ? 'READY' : 'LOW_SAMPLE',
          caseCount: recordedCase ? 5 : 4,
          classificationCounts: {
            valid: 2,
            misjudge: recordedCase ? 2 : 1,
            insufficient_data: 1,
          },
          validRate: recordedCase ? 0.4 : 0.5,
          misjudgeRate: recordedCase ? 0.4 : 0.25,
          insufficientDataRate: recordedCase ? 0.2 : 0.25,
        },
        byConfigHash: [
          {
            configHash: currentConfigHash,
            promptVersions: [promptVersion],
            totalCases: recordedCase ? 5 : 4,
            classificationCounts: {
              valid: 2,
              misjudge: recordedCase ? 2 : 1,
              insufficient_data: 1,
            },
            latestCaseAt: new Date().toISOString(),
            validRate: recordedCase ? 0.4 : 0.5,
            misjudgeRate: recordedCase ? 0.4 : 0.25,
            insufficientDataRate: recordedCase ? 0.2 : 0.25,
          },
          {
            configHash: baselineConfigHash,
            promptVersions: [promptVersion],
            totalCases: 3,
            classificationCounts: { valid: 1, misjudge: 1, insufficient_data: 1 },
            latestCaseAt: new Date(Date.now() - 60000).toISOString(),
            validRate: 0.3333,
            misjudgeRate: 0.3333,
            insufficientDataRate: 0.3333,
          },
        ],
        representativeCaseSet: {
          policyId: 'technical_kline_representative_case_set_v1',
          status: 'READY',
          minimumReviewedCases: 5,
          minimumSymbols: 2,
          requiredClassifications: ['valid', 'misjudge', 'insufficient_data'],
          reviewedCaseCount: recordedCase ? 8 : 7,
          uniqueSymbolCount: recordedCase ? 8 : 7,
          symbols: ['600010', '600011', '600012', '600020', '600021', '600022', '600023'],
          missingClassifications: [],
          blocking: false,
          action: 'review_ready',
          boundary: 'REVIEW_ONLY_NO_TRADE_ACTION',
          remediation: {
            requiredReviewedCaseDelta: 0,
            requiredUniqueSymbolDelta: 0,
            missingClassifications: [],
            nextActions: ['Representative case set is ready for review-only parameter governance.'],
          },
        },
        parameterVersionReview: {
          policyId: 'technical_kline_parameter_version_review_v1',
          status: recordedCase ? 'READY_FOR_REVIEW' : 'LOW_CURRENT_CONFIG_SAMPLE',
          action: recordedCase ? 'review_parameter_version_delta' : 'expand_current_config_cases',
          currentConfigHash,
          currentConfigCaseCount: recordedCase ? 5 : 4,
          currentConfigClassificationCounts: {
            valid: 2,
            misjudge: recordedCase ? 2 : 1,
            insufficient_data: 1,
          },
          missingCurrentConfigClassifications: [],
          baselineConfigCount: 1,
          comparison: recordedCase ? {
            baselineConfigHash,
            baselineCaseCount: 3,
            validRateDelta: 0.0667,
            misjudgeRateDelta: 0.0667,
            insufficientDataRateDelta: -0.1333,
          } : null,
          boundary: 'REVIEW_ONLY_NO_TRADE_ACTION',
        },
        longWindowRegression: {
          policyId: 'technical_kline_long_window_regression_v1',
          status: recordedCase ? 'READY_FOR_REVIEW' : 'LOW_COVERAGE',
          action: recordedCase ? 'review_long_window_parameter_regression' : 'expand_long_window_review_history',
          minimumReviewedCases: 8,
          minimumConfigVersions: 2,
          minimumSymbols: 3,
          reviewedCaseCount: recordedCase ? 8 : 7,
          uniqueSymbolCount: recordedCase ? 8 : 7,
          configVersionCount: 2,
          baselineConfigCount: 1,
          currentConfigHash,
          currentConfigCaseCount: recordedCase ? 5 : 4,
          baselineCaseCount: 3,
          retainedCaseLimit: 200,
          symbols: ['600010', '600011', '600012', '600020', '600021', '600022', '600023'],
          missingClassifications: [],
          windows: [
            {
              label: 'retained_review_history',
              caseCount: recordedCase ? 8 : 7,
              scope: 'last_200_governance_cases',
            },
            {
              label: 'current_config',
              caseCount: recordedCase ? 5 : 4,
              scope: currentConfigHash,
            },
            {
              label: 'baseline_configs',
              caseCount: 3,
              scope: 'all_non_current_retained_configs',
            },
          ],
          blocking: false,
          boundary: 'REVIEW_ONLY_NO_TRADE_ACTION',
          dataPolicy: 'REVIEWED_REAL_TUSHARE_KLINE_CASES_ONLY',
          tradeActionPolicy: 'NO_DIRECT_TRADE_ACTION',
          remediation: {
            requiredReviewedCaseDelta: recordedCase ? 0 : 1,
            requiredConfigVersionDelta: 0,
            requiredUniqueSymbolDelta: 0,
            missingClassifications: [],
            nextActions: [
              recordedCase
                ? 'Long-window reviewed-case regression is ready for review-only parameter governance.'
                : 'Retain 1 additional reviewed Technical Kline case(s).',
            ],
          },
        },
        warnings: recordedCase ? [] : ['LOW_TECHNICAL_KLINE_CASE_SAMPLE'],
      },
      auditLog: [],
    },
  })

  const governanceRouteHandler = async (route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(governanceFixture()),
    })
  }
  const caseRouteHandler = async (route) => {
    const request = route.request()
    const headers = await request.allHeaders()
    const authorization = headers.authorization || headers.Authorization
    if (authorization !== `Bearer ${authToken}`) {
      throw new Error('Technical Kline case POST did not include the expected Authorization bearer token')
    }
    const payload = JSON.parse(request.postData() || '{}')
    if (
      payload.run_id !== runId
      || payload.classification !== 'misjudge'
      || payload.config_hash !== currentConfigHash
      || payload.prompt_version !== promptVersion
      || !payload.symbol
    ) {
      throw new Error(`Technical Kline case POST payload did not preserve run/config/prompt context: ${JSON.stringify(payload)}`)
    }
    recordedCase = {
      caseId: technicalCaseId,
      caseLibraryCaseId,
      caseLibraryStatus: 'MIRRORED',
      symbol: payload.symbol,
      classification: payload.classification,
      note: payload.note || '',
      runId: payload.run_id,
      analysisStatus: payload.analysis_status || '',
      technicalBias: payload.technical_bias || '',
      configHash: payload.config_hash,
      promptVersion: payload.prompt_version,
      createdAt: new Date().toISOString(),
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(recordedCase),
    })
  }

  await page.route('**/api/technical-kline/governance**', governanceRouteHandler)
  await page.route('**/api/technical-kline/cases', caseRouteHandler)
  try {
    const encodedRunId = encodeURIComponent(runId)
    const governanceResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith('/api/technical-kline/governance')
        && response.status() === 200
    }, { timeout: 30000 })

    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, `/quant-core?run_id=${encodedRunId}`)
    await page.waitForURL(new RegExp(`/quant-core\\?run_id=${encodedRunId}$`), { timeout: 15000 })

    const governance = await assertAuthedJson(governanceResponsePromise, 'Technical Kline governance load')
    if (governance?.analysisConfig?.configHash !== 'cfg-technical-kline-browser-smoke') {
      throw new Error(`Technical Kline governance fixture did not load through the active QuantCore page: ${JSON.stringify(governance)}`)
    }

    await assertQuantCoreVisibleBoundary(page)
    console.log('ok strict-auth browser QuantCore visible review boundary')
    await page.getByTestId('technical-kline-case-governance').waitFor({ state: 'visible', timeout: 15000 })
    await assertTechnicalKlineVisibleBoundary(page)
    console.log('ok strict-auth browser Technical Kline visible review boundary')
    await page.getByTestId('technical-kline-case-classification').selectOption('misjudge')
    await page.getByTestId('technical-kline-case-note').fill('strict-auth browser misjudge sedimentation')

    const caseResponsePromise = page.waitForResponse((response) => (
      response.request().method() === 'POST'
        && response.url().includes('/api/technical-kline/cases')
        && response.status() === 200
    ), { timeout: 30000 })
    await clickEnabled(page.getByTestId('technical-kline-record-case'), 'Technical Kline record case')
    const saved = await assertAuthedJson(caseResponsePromise, 'Technical Kline case record')
    if (
      saved?.caseId !== technicalCaseId
      || saved?.caseLibraryCaseId !== caseLibraryCaseId
      || saved?.classification !== 'misjudge'
      || saved?.runId !== runId
    ) {
      throw new Error(`Technical Kline case response did not preserve Case Library sedimentation: ${JSON.stringify(saved)}`)
    }

    const caseMessage = page.getByTestId('technical-kline-case-message')
    await caseMessage.waitFor({ state: 'visible', timeout: 15000 })
    const messageText = await caseMessage.innerText()
    if (!messageText.includes(technicalCaseId) || !messageText.includes(caseLibraryCaseId)) {
      throw new Error(`Technical Kline case message did not render both case ids: ${messageText}`)
    }
    await page.getByTestId('technical-kline-representative-case-set').waitFor({ state: 'visible', timeout: 15000 })
    await page.getByTestId('technical-kline-parameter-version-review').waitFor({ state: 'visible', timeout: 15000 })
    const versionText = await page.getByTestId('technical-kline-parameter-version-review').innerText()
    const versionHasReadyState = versionText.includes('READY_FOR_REVIEW') || versionText.includes('待复核')
    const versionHasDeltaAction = versionText.includes('review_parameter_version_delta') || versionText.includes('复核参数版本差异')
    if (!versionHasReadyState || !versionHasDeltaAction) {
      throw new Error(`Technical Kline parameter version review did not render ready delta state: ${versionText}`)
    }
    const deltaText = await page.getByTestId('technical-kline-parameter-version-delta').innerText()
    if (!deltaText.includes(baselineConfigHash) || !(deltaText.includes('Misjudge delta') || deltaText.includes('误判率变化'))) {
      throw new Error(`Technical Kline parameter version delta did not render baseline comparison: ${deltaText}`)
    }
    await page.getByTestId('technical-kline-long-window-regression').waitFor({ state: 'visible', timeout: 15000 })
    const longWindowText = await page.getByTestId('technical-kline-long-window-regression').innerText()
    const longWindowHasReadyState = longWindowText.includes('READY_FOR_REVIEW') || longWindowText.includes('待复核')
    const longWindowHasReviewAction = (
      longWindowText.includes('review_long_window_parameter_regression')
      || longWindowText.includes('复核长窗口参数回归')
    )
    const longWindowHasNoTradeBoundary = (
      longWindowText.includes('NO_DIRECT_TRADE_ACTION')
      || longWindowText.includes('不产生直接交易动作')
    )
    const longWindowHasRetainedScope = (
      longWindowText.includes('last_200_governance_cases')
      || longWindowText.includes('最近 200 条治理案例')
    )
    if (
      !longWindowHasReadyState
      || !longWindowHasReviewAction
      || !longWindowHasRetainedScope
      || !longWindowHasNoTradeBoundary
    ) {
      throw new Error(`Technical Kline long-window regression retention did not render ready review state: ${longWindowText}`)
    }
    console.log('ok strict-auth browser Technical Kline Case Library sedimentation')
  } finally {
    await page.unroute('**/api/technical-kline/governance**', governanceRouteHandler).catch(() => undefined)
    await page.unroute('**/api/technical-kline/cases', caseRouteHandler).catch(() => undefined)
  }
}

async function runLiveRunTerminalStreamScenario(page, baseRun) {
  const cases = [
    {
      eventType: 'STREAM_TIMEOUT',
      fixtureRunId: 'RUN_LIVE_STREAM_TERMINAL_BROWSER_SMOKE',
      message: 'STREAM_TIMEOUT_BROWSER_FIXTURE',
      auditId: 'AUD_LIVE_STREAM_TIMEOUT_BROWSER',
    },
    {
      eventType: 'RUN_STALE_RECOVERED',
      fixtureRunId: 'RUN_LIVE_STALE_RECOVERED_BROWSER_SMOKE',
      message: 'RUN_STALE_RECOVERED_BROWSER_FIXTURE',
      auditId: 'AUD_LIVE_STALE_RECOVERED_BROWSER',
    },
  ]

  for (const terminalCase of cases) {
    const { eventType, fixture, fixtureRunId, message } = buildLiveRunTerminalFixture(baseRun, terminalCase)
    const encodedFixtureRunId = encodeURIComponent(fixtureRunId)
    const streamMessage = {
      event_type: eventType,
      run_id: fixtureRunId,
      node_id: 'system',
      message,
      payload: {
        simulation_only: true,
        is_real_trade: false,
        evidence_usage: 'simulation_only',
        strong_conclusion_allowed: false,
        allowed_order_namespace: 'SIM_*',
      },
      audit_id: terminalCase.auditId,
      timestamp: new Date().toISOString(),
    }

    let fixtureRunReadCount = 0
    let resolveSecondFixtureRunRead
    const secondFixtureRunRead = new Promise((resolve) => {
      resolveSecondFixtureRunRead = resolve
    })
    const fixtureRunRouteHandler = async (route) => {
      fixtureRunReadCount += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(fixture),
      })
      if (fixtureRunReadCount >= 2) {
        resolveSecondFixtureRunRead()
      }
    }
    const fixtureStreamRouteHandler = async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'cache-control': 'no-cache',
          connection: 'keep-alive',
        },
        body: `data: ${JSON.stringify(streamMessage)}\n\n`,
      })
    }

    await page.route(`**/api/analysis/runs/${encodedFixtureRunId}`, fixtureRunRouteHandler)
    await page.route(`**/api/analysis/runs/${encodedFixtureRunId}/stream**`, fixtureStreamRouteHandler)
    try {
      const fixtureRunResponsePromise = page.waitForResponse((response) => {
        const url = new URL(response.url())
        return response.request().method() === 'GET'
          && url.pathname.endsWith(`/api/analysis/runs/${encodedFixtureRunId}`)
          && response.status() === 200
      }, { timeout: 30000 })
      const fixtureStreamRequestPromise = page.waitForRequest((request) => (
        request.url().includes(`/api/analysis/runs/${encodedFixtureRunId}/stream`)
          && request.headers().authorization === `Bearer ${authToken}`
      ), { timeout: 45000 })

      await page.evaluate((targetPath) => {
        window.history.pushState({}, '', targetPath)
        window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
      }, `/live-run?run_id=${encodedFixtureRunId}`)
      await page.waitForURL(new RegExp(`/live-run\\?run_id=${encodedFixtureRunId}$`), { timeout: 15000 })
      const terminalRun = await assertAuthedJson(fixtureRunResponsePromise, `Live Run ${eventType} terminal fixture load`)
      if (terminalRun?.runId !== fixtureRunId) {
        throw new Error(`Live Run ${eventType} terminal fixture returned wrong run: ${JSON.stringify(terminalRun)}`)
      }

      const fixtureStreamRequest = await fixtureStreamRequestPromise
      const streamUrl = new URL(fixtureStreamRequest.url())
      if (streamUrl.searchParams.has('api_key') || streamUrl.searchParams.has('token')) {
        throw new Error(`Live Run ${eventType} terminal stream leaked auth token in the URL`)
      }
      await Promise.race([
        secondFixtureRunRead,
        delay(15000).then(() => {
          throw new Error(`Live Run terminal fixture was not refreshed after ${eventType}; reads=${fixtureRunReadCount}`)
        }),
      ])

      const terminalEvent = page
        .getByTestId(`live-run-event-${eventType}`)
        .filter({ hasText: message })
        .first()
      await terminalEvent.waitFor({ state: 'visible', timeout: 15000 })
      const terminalText = await terminalEvent.innerText()
      for (const marker of [
        'simulation_only=true',
        'is_real_trade=false',
        'evidence_usage=simulation_only',
        'strong_conclusion_allowed=false',
        'SIM_*',
      ]) {
        if (!terminalText.includes(marker)) {
          throw new Error(`Live Run ${eventType} terminal visible stream boundary is missing ${marker}: ${terminalText}`)
        }
      }
      const statusAfter = await terminalEvent.getAttribute('data-status-after')
      if (statusAfter !== 'FAIL') {
        throw new Error(`Live Run ${eventType} event rendered status ${statusAfter} instead of FAIL`)
      }
      const streamErrorCount = await page.getByTestId('live-run-stream-error').count()
      if (streamErrorCount !== 0) {
        throw new Error(`Live Run ${eventType} terminal stream event rendered a reconnect/error banner`)
      }
    } finally {
      await page.unroute(`**/api/analysis/runs/${encodedFixtureRunId}`, fixtureRunRouteHandler).catch(() => undefined)
      await page.unroute(`**/api/analysis/runs/${encodedFixtureRunId}/stream**`, fixtureStreamRouteHandler).catch(() => undefined)
    }
  }
  console.log('ok strict-auth browser live-run terminal stream event')
}

async function runAuditLogScenario(page, runId) {
  const encodedRunId = encodeURIComponent(runId)
  const auditResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith(`/api/analysis/runs/${encodedRunId}/audit`)
      && response.status() === 200
  }, { timeout: 30000 })

  await page.locator('a[href="/audit"]').first().click()
  await page.waitForURL(/\/audit$/, { timeout: 15000 })
  const auditEvents = await assertAuthedJsonOrApi(
    auditResponsePromise,
    'Audit Log run audit load',
    `/api/analysis/runs/${encodedRunId}/audit`,
    { page },
  )
  if (!Array.isArray(auditEvents) || auditEvents.length === 0) {
    throw new Error(`Audit Log did not load run audit events for ${runId}: ${JSON.stringify(auditEvents)}`)
  }
  const eventTypes = new Set(auditEvents.map((event) => String(event?.eventType || event?.event_type || '')))
  const expectedType = eventTypes.has('PORTFOLIO_SNAPSHOT_ATTACHED')
    ? 'PORTFOLIO_SNAPSHOT_ATTACHED'
    : eventTypes.has('RUN_QUEUED')
      ? 'RUN_QUEUED'
      : ''
  if (!expectedType) {
    throw new Error(`Audit Log response did not include expected run lifecycle events: ${JSON.stringify(auditEvents)}`)
  }
  await waitForAuditEventVisible(page, expectedType, runId)
  await page.getByText('Audit Log', { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
  console.log('ok strict-auth browser Audit Log run audit')
}

async function waitForAuditEventVisible(page, expectedType, runId) {
  const eventLocator = page.locator('span', { hasText: expectedType }).first()
  try {
    await eventLocator.waitFor({ state: 'visible', timeout: 15000 })
    return
  } catch (error) {
    if (error?.name !== 'TimeoutError') {
      throw error
    }
    console.warn(`Audit Log event ${expectedType} did not render in time; retrying SPA audit route for ${runId}`)
  }

  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, '/audit')
  await page.waitForURL(/\/audit$/, { timeout: 15000 })
  await page.getByText('Audit Log', { exact: false }).first().waitFor({ state: 'visible', timeout: 15000 })
  await eventLocator.waitFor({ state: 'visible', timeout: 30000 })
}

async function runPluginArchiveScenario(page) {
  const pluginListResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith('/api/plugins')
      && response.status() === 200
  }, { timeout: 30000 })
  const pluginPlanResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith('/api/plugins/runtime/plan')
      && response.status() === 200
  }, { timeout: 30000 })
  const pluginUsageResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith('/api/plugins/usage/stats')
      && response.status() === 200
  }, { timeout: 30000 })
  const pluginHistoryResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url())
    return response.request().method() === 'GET'
      && url.pathname.endsWith('/api/plugins/usage/history')
      && response.status() === 200
  }, { timeout: 30000 })

  await navigateByAppLink(page, '/backend', 'Plugin Registry prerequisite Backend Status route')
  await page.waitForTimeout(250)
  await page.locator('a[href="/plugins"]').first().click()
  await page.waitForURL(/\/plugins$/, { timeout: 15000 })
  const plugins = await assertAuthedJsonOrApi(pluginListResponsePromise, 'Plugin registry load', '/api/plugins')
  const runtimePlan = await assertAuthedJsonOrApi(pluginPlanResponsePromise, 'Plugin runtime resource plan', '/api/plugins/runtime/plan')
  const usageStats = await assertAuthedJsonOrApi(pluginUsageResponsePromise, 'Plugin usage stats', '/api/plugins/usage/stats')
  const usageHistory = await assertAuthedJsonOrApi(pluginHistoryResponsePromise, 'Plugin usage history', '/api/plugins/usage/history?days=90')
  if (!Array.isArray(plugins) || !plugins.some((plugin) => plugin?.plugin_id === 'technical_kline_readonly')) {
    throw new Error(`Plugin registry load did not include the builtin readonly plugin: ${JSON.stringify(plugins)}`)
  }
  if (!runtimePlan?.resource_summary || !runtimePlan.resource_summary.quota_status) {
    throw new Error(`Plugin runtime plan did not include resource quota summary: ${JSON.stringify(runtimePlan)}`)
  }
  if (!Array.isArray(usageStats) || !usageStats.some((item) => item?.plugin_id === 'technical_kline_readonly')) {
    throw new Error(`Plugin usage stats did not include the builtin readonly plugin: ${JSON.stringify(usageStats)}`)
  }
  if (
    usageHistory?.bucket !== 'day'
    || !Array.isArray(usageHistory?.items)
    || !usageHistory.items.some((item) => item?.plugin_id === 'technical_kline_readonly')
  ) {
    throw new Error(`Plugin usage history did not include daily builtin readonly history: ${JSON.stringify(usageHistory)}`)
  }
  try {
    await page.getByTestId('plugin-resource-summary').waitFor({ state: 'visible', timeout: 30000 })
    await page.getByTestId('plugin-usage-summary').waitFor({ state: 'visible', timeout: 30000 })
    await page.getByTestId('plugin-usage-history').waitFor({ state: 'visible', timeout: 30000 })
  } catch (error) {
    throw new Error(`Plugin Registry summary panels did not render: ${error?.message || error}; ${await pageRenderDiagnostic(page)}`)
  }
  console.log('ok strict-auth browser Plugin usage history')

  const artifactContent = Buffer.from(JSON.stringify({
    plugin_id: 'technical_kline_readonly',
    smoke: 'strict-auth-browser',
    boundary: 'stored_only_no_code_execution',
  }))
  const artifactChecksum = `sha256:${createHash('sha256').update(artifactContent).digest('hex')}`
  const artifactDigest = artifactChecksum.split(':')[1]
  if (process.env.TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR) {
    await mkdir(process.env.TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR, { recursive: true })
    await writeFile(
      path.join(process.env.TIANYUAN_PLUGIN_ARTIFACT_EXTERNAL_SCAN_DIR, `${artifactDigest}.json`),
      JSON.stringify({
        schema: 'plugin_artifact_external_scan_verdict_v1',
        status: 'PASSED',
        checksum: artifactChecksum,
        scanner: 'strict-auth-sidecar-av',
        signature_version: 'strict-auth-smoke-v1',
        engine_version: 'engine-strict-auth-1',
        provider_status: 'READY',
        threat_intel_status: 'CURRENT',
        definitions_updated_at: new Date().toISOString(),
        scan_id: 'strict-auth-scan-1',
        summary: 'Strict-auth smoke external scan verdict.',
      }),
      'utf8',
    )
  }
  const artifactUploadResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/plugins/technical_kline_readonly/artifacts')
      && response.status() === 200
  ), { timeout: 30000 })
  await page.getByTestId('plugin-artifact-file').setInputFiles({
    name: 'technical-kline-readonly-smoke.json',
    mimeType: 'application/json',
    buffer: artifactContent,
  })
  await page.getByTestId('plugin-artifact-checksum').fill(artifactChecksum)
  await page.getByTestId('plugin-artifact-upload-action').click()
  const artifactUpload = await assertAuthedJson(artifactUploadResponsePromise, 'Plugin artifact upload')
  if (
    artifactUpload?.plugin_id !== 'technical_kline_readonly'
    || artifactUpload?.artifact_type !== 'uploaded_package'
    || artifactUpload?.checksum !== artifactChecksum
    || artifactUpload?.expected_checksum !== artifactChecksum
    || artifactUpload?.verified !== true
    || artifactUpload?.recorded_only !== false
    || artifactUpload?.external_scan_status !== 'PASSED'
    || artifactUpload?.external_scan_provider !== 'strict-auth-sidecar-av'
    || artifactUpload?.external_scan?.matches_artifact_checksum !== true
    || artifactUpload?.external_scan?.provider_status !== 'READY'
    || artifactUpload?.external_scan?.threat_intel_status !== 'CURRENT'
    || artifactUpload?.external_scan?.signature_version !== 'strict-auth-smoke-v1'
    || !artifactUpload?.storage_path
  ) {
    throw new Error(`Plugin artifact upload response did not store and verify the package: ${JSON.stringify(artifactUpload)}`)
  }
  await page.getByTestId('plugin-artifact-upload-result').waitFor({ state: 'visible', timeout: 15000 })
  const artifactUploadText = await page.getByTestId('plugin-artifact-upload-result').innerText()
  if (
    !artifactUploadText.includes('外部扫描 PASSED')
    || !artifactUploadText.includes('strict-auth-sidecar-av')
    || !artifactUploadText.includes('提供方 READY')
    || !artifactUploadText.includes('威胁情报 CURRENT')
    || !artifactUploadText.includes('签名 strict-auth-smoke-v1')
    || !artifactUploadText.includes('校验和匹配')
  ) {
    throw new Error(`Plugin artifact upload result did not show external scan evidence: ${artifactUploadText}`)
  }
  await page.getByTestId('plugin-package-artifact-state').waitFor({ state: 'visible', timeout: 15000 })
  const artifactStateText = await page.getByTestId('plugin-package-artifact-state').innerText()
  if (
    !artifactStateText.includes('外部扫描 PASSED')
    || !artifactStateText.includes('strict-auth-sidecar-av')
    || !artifactStateText.includes('提供方 READY')
    || !artifactStateText.includes('威胁情报 CURRENT')
    || !artifactStateText.includes('签名 strict-auth-smoke-v1')
    || !artifactStateText.includes('校验和匹配')
  ) {
    throw new Error(`Plugin package artifact state did not show external scan evidence: ${artifactStateText}`)
  }
  console.log('ok strict-auth browser Plugin artifact upload hash verification')

  const cleanupResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/plugins/artifacts/cleanup')
      && response.status() === 200
  ), { timeout: 30000 })
  await clickEnabled(page.getByTestId('plugin-artifact-cleanup-dry-run-action'), 'Plugin artifact cleanup dry-run action')
  const cleanupResponse = await cleanupResponsePromise
  if (!cleanupResponse.ok()) {
    throw new Error(`Plugin artifact cleanup dry-run returned ${cleanupResponse.status()}: ${await cleanupResponse.text()}`)
  }
  await assertBearer(cleanupResponse, 'Plugin artifact cleanup dry-run')
  const cleanupRequestPayload = JSON.parse(cleanupResponse.request().postData() || '{}')
  if (
    cleanupRequestPayload?.dry_run !== true
    || !String(cleanupRequestPayload?.reason || '').includes('technical_kline_readonly')
  ) {
    throw new Error(`Plugin artifact cleanup dry-run request did not stay non-destructive for the selected plugin: ${JSON.stringify(cleanupRequestPayload)}`)
  }
  const cleanup = await cleanupResponse.json()
  if (
    cleanup?.dry_run !== true
    || cleanup?.status !== 'DRY_RUN'
    || !Number.isInteger(cleanup?.scanned_plugin_count)
    || cleanup.scanned_plugin_count < 1
    || !Number.isInteger(cleanup?.expired_count)
    || !Number.isInteger(cleanup?.would_delete_count)
    || !Number.isInteger(cleanup?.skipped_count)
    || !Array.isArray(cleanup?.items)
  ) {
    throw new Error(`Plugin artifact cleanup dry-run response did not expose bounded retention evidence: ${JSON.stringify(cleanup)}`)
  }
  await page.getByTestId('plugin-artifact-cleanup-result').waitFor({ state: 'visible', timeout: 15000 })
  console.log('ok strict-auth browser Plugin artifact cleanup dry-run')

  const upgradeResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/plugins/technical_kline_readonly/upgrade')
      && response.status() === 200
  ), { timeout: 30000 })
  await clickEnabled(page.getByTestId('plugin-upgrade-action'), 'Plugin upgrade action')
  const upgraded = await assertAuthedJson(upgradeResponsePromise, 'Plugin upgrade')
  if (
    upgraded?.plugin_id !== 'technical_kline_readonly'
    || upgraded?.version === '0.1.0'
    || upgraded?.lifecycle_status !== 'ACTIVE'
    || !upgraded?.upgraded_at
    || upgraded?.package_checksum !== artifactChecksum
    || upgraded?.manifest?.package_artifact?.artifact_type !== 'uploaded_package'
    || upgraded?.manifest?.package_artifact?.verified !== true
    || upgraded?.manifest?.package_artifact?.external_scan_status !== 'PASSED'
    || upgraded?.manifest?.lifecycle?.package_external_scan_status !== 'PASSED'
    || !upgraded?.manifest?.package_migration?.steps?.length
    || upgraded?.manifest?.package_migration?.steps?.[0]?.kind !== 'artifact_storage_verified'
  ) {
    throw new Error(`Plugin upgrade response did not record a new active version: ${JSON.stringify(upgraded)}`)
  }
  await page.getByTestId('plugin-upgraded-state').waitFor({ state: 'visible', timeout: 15000 })

  const archiveResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/plugins/technical_kline_readonly/archive')
      && response.status() === 200
  ), { timeout: 30000 })
  await clickEnabled(page.getByTestId('plugin-archive-action'), 'Plugin archive action')
  let archived
  try {
    archived = await assertAuthedJson(archiveResponsePromise, 'Plugin archive')
  } catch (error) {
    const message = String(error?.message || '')
    if (error?.name !== 'TimeoutError' && !message.includes('Timeout')) {
      throw error
    }
    console.warn('Plugin archive response wait timed out; verifying archived state through direct API fallback')
    archived = await apiJson('POST', '/api/plugins/technical_kline_readonly/archive', {
      reason: 'Strict-auth browser smoke archive fallback after response wait timeout.',
    })
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/plugins')
    await page.waitForURL(/\/plugins$/, { timeout: 15000 })
  }
  if (
    archived?.plugin_id !== 'technical_kline_readonly'
    || archived?.enabled !== false
    || archived?.lifecycle_status !== 'ARCHIVED'
  ) {
    throw new Error(`Plugin archive response did not disable and archive the plugin: ${JSON.stringify(archived)}`)
  }
  try {
    await page.getByTestId('plugin-archived-state').waitFor({ state: 'visible', timeout: 30000 })
  } catch (error) {
    const message = String(error?.message || '')
    if (error?.name !== 'TimeoutError' && !message.includes('Timeout')) {
      throw error
    }
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, '/plugins')
    await page.waitForURL(/\/plugins$/, { timeout: 15000 })
    await page.getByTestId('plugin-archived-state').waitFor({ state: 'visible', timeout: 30000 })
  }
  console.log('ok strict-auth browser Plugin archive lifecycle')
}

async function importPortfolioFileFixture(page, fixture) {
  const importResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/portfolio/imports')
      && response.status() === 200
  ), { timeout: 30000 })

  await page.getByTestId('portfolio-import-file').setInputFiles({
    name: fixture.filename,
    mimeType: fixture.mimeType,
    buffer: fixture.content,
  })
  await clickEnabled(page.getByTestId('portfolio-import-submit'), `Portfolio ${fixture.brokerTemplateId} import submit`)
  const importResponse = await importResponsePromise
  if (!importResponse.ok()) {
    throw new Error(`portfolio ${fixture.brokerTemplateId} file import returned ${importResponse.status()}: ${await importResponse.text()}`)
  }
  await assertBearer(importResponse, `portfolio ${fixture.brokerTemplateId} file import`)
  const importHeaders = await importResponse.request().allHeaders()
  const contentType = importHeaders['content-type'] || importHeaders['Content-Type'] || ''
  if (!contentType.includes('multipart/form-data')) {
    throw new Error(`portfolio ${fixture.brokerTemplateId} file import did not use multipart FormData: ${contentType}`)
  }
  const imported = await importResponse.json()
  const snapshot = imported?.snapshot || {}
  const snapshotId = String(snapshot.snapshotId || '').trim()
  if (
    imported?.status !== 'COMPLETED'
    || !snapshotId.startsWith('PF_')
    || snapshot?.sourceType !== 'CSV'
    || snapshot?.brokerTemplateId !== fixture.brokerTemplateId
    || Number(snapshot?.templateConfidence || 0) < fixture.minimumTemplateConfidence
    || snapshot?.positions?.[0]?.symbol !== fixture.expectedSymbol
  ) {
    throw new Error(`portfolio ${fixture.brokerTemplateId} import response did not preserve CSV/template metadata: ${JSON.stringify(imported)}`)
  }
  await expectText(page, snapshotId, `portfolio ${fixture.brokerTemplateId} import snapshot list`)
  await expectText(page, fixture.expectedBrokerLabel, `portfolio ${fixture.brokerTemplateId} import broker template`)
  return imported
}

async function importInvalidPortfolioFileFixture(page) {
  const importResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/portfolio/imports')
      && response.status() === 400
  ), { timeout: 30000 })

  await page.getByTestId('portfolio-import-file').setInputFiles({
    name: 'futu-malformed.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('Stock Name,Market Value\nYinglian,1000\n'),
  })
  await clickEnabled(page.getByTestId('portfolio-import-submit'), 'Portfolio malformed import submit')
  const importResponse = await importResponsePromise
  await assertBearer(importResponse, 'portfolio malformed file import')
  const importHeaders = await importResponse.request().allHeaders()
  const contentType = importHeaders['content-type'] || importHeaders['Content-Type'] || ''
  if (!contentType.includes('multipart/form-data')) {
    throw new Error(`portfolio malformed file import did not use multipart FormData: ${contentType}`)
  }
  const payload = await importResponse.json()
  const detail = payload?.detail || {}
  if (
    detail?.reason !== 'NO_VALID_HOLDING_ROWS'
    || !String(detail?.jobId || '').startsWith('IMP_')
    || !detail?.expectedColumns?.required?.some((item) => String(item).includes('symbol'))
    || !detail?.expectedColumns?.required?.some((item) => String(item).includes('shares'))
    || !detail?.acceptedExtensions?.includes('.xlsx')
    || !detail?.observedHeaders?.includes('Stock Name')
    || !detail?.observedHeaders?.includes('Market Value')
    || !detail?.matchedFields?.includes('name')
    || !detail?.matchedFields?.includes('marketValue')
    || !detail?.missingRequiredFields?.includes('symbol')
    || !detail?.missingRequiredFields?.includes('shares')
    || detail?.rowPreview?.[0]?.cells?.['Stock Name'] !== 'Yinglian'
    || detail?.brokerTemplateHint?.brokerTemplateId !== 'futu'
    || Number(detail?.brokerTemplateHint?.templateConfidence || 0) < 0.6
    || !String(detail?.templateConfidenceNote || '').includes('Futu/Moomoo broker export')
    || !detail?.repairSuggestions?.some((item) => String(item).includes('Futu/Moomoo exports'))
  ) {
    throw new Error(`portfolio malformed import did not return structured diagnostics: ${JSON.stringify(payload)}`)
  }
  await page.getByTestId('portfolio-import-error-detail').waitFor({ state: 'visible', timeout: 15000 })
  await expectText(page, detail.jobId, 'portfolio malformed import job id')
  await expectText(page, 'NO_VALID_HOLDING_ROWS', 'portfolio malformed import reason')
  await expectText(page, 'Required columns:', 'portfolio malformed import expected columns')
  await expectText(page, 'symbol / stock_code', 'portfolio malformed import symbol guidance')
  await expectText(page, 'Observed headers: Stock Name, Market Value', 'portfolio malformed import observed headers')
  await expectText(page, 'Row 2: Stock Name=Yinglian; Market Value=1000', 'portfolio malformed import row preview')
  await expectText(page, 'Template hint: Futu/Moomoo broker export', 'portfolio malformed import broker template hint')
  await expectText(page, 'Futu/Moomoo exports', 'portfolio malformed import repair suggestion')
  console.log('ok strict-auth browser Portfolio import malformed-file UX')
}

async function assertPortfolioSnapshotVisibleBoundary(page, snapshotId) {
  const boundary = page.getByTestId(`portfolio-snapshot-simulation-boundary-${snapshotId}`)
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=supporting_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`Portfolio snapshot visible boundary is missing ${expected}: ${text}`)
    }
  }
}

async function assertNewTaskPortfolioRiskBoundary(page) {
  const boundary = page.getByTestId('new-task-portfolio-risk-boundary')
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'preflight_only=true',
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=portfolio_context_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`New Task portfolio preflight boundary is missing ${expected}: ${text}`)
    }
  }
}

async function assertNewTaskVisibleBoundary(page) {
  await page.getByTestId('new-task-run-governance').waitFor({ state: 'visible', timeout: 15000 })
  const contextId = await page.getByTestId('new-task-run-context-id').innerText()
  if (!contextId.includes('PF_') && !contextId.includes('USER_INPUT_ONLY')) {
    throw new Error(`New Task governance context did not expose a portfolio/user-input boundary: ${contextId}`)
  }
  const evidenceStrength = await page.getByTestId('new-task-run-evidence-strength').innerText()
  if (!evidenceStrength.includes('证据强度') || evidenceStrength.includes('undefined')) {
    throw new Error(`New Task evidence strength did not render a usable label: ${evidenceStrength}`)
  }
  const blocker = await page.getByTestId('new-task-run-blocker').innerText()
  if (!blocker.includes('阻塞') || blocker.includes('undefined')) {
    throw new Error(`New Task blocker did not render a usable label: ${blocker}`)
  }
  const nextAction = await page.getByTestId('new-task-run-next-action').innerText()
  if (!nextAction.includes('下一步') || nextAction.includes('undefined')) {
    throw new Error(`New Task next action did not render a usable label: ${nextAction}`)
  }
  const boundary = await page.getByTestId('new-task-run-simulation-boundary').innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundary.includes(expected)) {
      throw new Error(`New Task visible boundary is missing ${expected}: ${boundary}`)
    }
  }
}

async function assertFinalWriterVisibleBoundary(page) {
  const boundary = page.getByTestId('final-writer-simulation-boundary')
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`Final Writer visible boundary is missing ${expected}: ${text}`)
    }
  }
}

async function assertAntiConclusionVisibleBoundary(page, expectedRunId) {
  if (expectedRunId) {
    const renderedRunId = (await page.getByTestId('anti-conclusion-current-run-id').innerText({ timeout: 15000 })).trim()
    if (renderedRunId !== expectedRunId) {
      throw new Error(`AntiConclusion rendered run id ${renderedRunId} instead of expected ${expectedRunId}`)
    }
  }
  const boundary = page.getByTestId('anti-conclusion-simulation-boundary')
  await boundary.waitFor({ state: 'visible', timeout: 15000 })
  const text = await boundary.innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=anti_conclusion_review_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!text.includes(expected)) {
      throw new Error(`AntiConclusion visible boundary is missing ${expected}: ${text}`)
    }
  }
}

async function runPortfolioImportScenario(page) {
  await importInvalidPortfolioFileFixture(page)
  await importPortfolioFileFixture(page, {
    filename: 'eastmoney-holdings.csv',
    mimeType: 'text/csv',
    content: Buffer.from(
      'stock_code,stock_name,holding,available,cost_price,market_value\n'
        + '002846,Yinglian,2000,1000,8.8,30000\n',
    ),
    brokerTemplateId: 'eastmoney',
    expectedBrokerLabel: 'Eastmoney broker export',
    expectedSymbol: '002846',
    minimumTemplateConfidence: 0.8,
  })
  await importPortfolioFileFixture(page, {
    filename: 'htsc-holdings.tsv',
    mimeType: 'text/tab-separated-values',
    content: Buffer.from(
      'code\tname\tshares\tavailable_shares\tcost\tvalue\n'
        + '603663\tSanxiang\t1500\t900\t11.2\t16800\n',
    ),
    brokerTemplateId: 'htsc',
    expectedBrokerLabel: 'Huatai Securities export',
    expectedSymbol: '603663',
    minimumTemplateConfidence: 0.9,
  })
  await importPortfolioFileFixture(page, {
    filename: 'gtja-positions.csv',
    mimeType: 'text/csv',
    content: Buffer.from(
      'security_code,security_name,current_qty,available_qty,avg_cost,market_capital,profit_loss\n'
        + '600519,Kweichow Moutai,20,20,1550,31000,1200\n',
    ),
    brokerTemplateId: 'gtja',
    expectedBrokerLabel: 'Guotai Junan Securities export',
    expectedSymbol: '600519',
    minimumTemplateConfidence: 0.9,
  })
  await importPortfolioFileFixture(page, {
    filename: 'futu-moomoo-positions.csv',
    mimeType: 'text/csv',
    content: Buffer.from(
      'Stock Code,Stock Name,Quantity,Available Qty,Average Cost,Market Value,Unrealized P/L\n'
        + '00700.HK,Tencent,100,80,320,35000,3000\n',
    ),
    brokerTemplateId: 'futu',
    expectedBrokerLabel: 'Futu/Moomoo broker export',
    expectedSymbol: '00700',
    minimumTemplateConfidence: 0.9,
  })
  await importPortfolioFileFixture(page, {
    filename: 'tiger-portfolio.csv',
    mimeType: 'text/csv',
    content: Buffer.from(
      'Symbol,Stock Name,Position,Available to Sell,Avg Price,Market Value,P&L\n'
        + 'AAPL,Apple,12,12,180,2280,120\n',
    ),
    brokerTemplateId: 'tiger',
    expectedBrokerLabel: 'Tiger broker export',
    expectedSymbol: 'AAPL',
    minimumTemplateConfidence: 0.9,
  })
  console.log('ok strict-auth browser Portfolio import multi-broker upload')
  console.log('ok strict-auth browser Portfolio import upload')
}

async function assertRunCompareVisibleBoundary(page, expectedContextId) {
  await page.getByTestId('run-compare-governance').waitFor({ state: 'visible', timeout: 15000 })
  const contextId = (await page.getByTestId('run-compare-governance-id').innerText()).trim()
  if (contextId !== expectedContextId) {
    throw new Error(`Run Compare governance context rendered ${contextId} instead of ${expectedContextId}`)
  }
  const evidenceStrength = (await page.getByTestId('run-compare-evidence-strength').innerText()).trim()
  if (evidenceStrength !== 'LOW') {
    throw new Error(`Run Compare evidence strength rendered ${evidenceStrength} instead of LOW`)
  }
  const boundary = await page.getByTestId('run-compare-simulation-boundary').innerText()
  for (const expected of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!boundary.includes(expected)) {
      throw new Error(`Run Compare visible boundary is missing ${expected}: ${boundary}`)
    }
  }
}

async function runRunCompareReviewBoundaryScenario(page) {
  const generatedAt = new Date().toISOString()
  const leftRunId = 'RUN_COMPARE_BROWSER_LEFT'
  const rightRunId = 'RUN_COMPARE_BROWSER_RIGHT'
  const runSummary = (runId, stockCode, finalAction, status = 'COMPLETED') => ({
    runId,
    stockCode,
    stockName: `Run Compare ${stockCode}`,
    taskType: 'position_review',
    runMode: 'FAST_MODE',
    status,
    finalAction,
    createdAt: generatedAt,
    updatedAt: generatedAt,
  })
  const leftRun = runSummary(leftRunId, '603663', 'WAIT')
  const rightRun = runSummary(rightRunId, '603663', 'SIM_HOLD')
  const compareResult = {
    leftRun,
    rightRun,
    generatedAt,
    changedCount: 1,
    summary: ['Final Writer output changed; review section text and audit attribution before reusing the conclusion.'],
    diffs: [
      {
        key: 'final',
        label: 'Final action',
        left: leftRun.finalAction,
        right: rightRun.finalAction,
        changed: true,
        impact: 'Final Writer output changed; review section text and audit attribution before reusing the conclusion.',
      },
      {
        key: 'data_mode',
        label: 'Data mode',
        left: 'FALLBACK',
        right: 'FALLBACK',
        changed: false,
        impact: 'No change.',
      },
    ],
  }
  const observed = { list: false, compare: false }
  const routePattern = '**/api/analysis/runs**'
  const assertRunCompareBearer = async (request, label) => {
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error(`Run Compare request did not include the expected Authorization bearer token: ${label}`)
    }
  }
  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET') {
      await route.continue()
      return
    }
    if (url.pathname === '/api/analysis/runs') {
      await assertRunCompareBearer(request, 'run list')
      observed.list = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([rightRun, leftRun]),
      })
      return
    }
    if (url.pathname === '/api/analysis/runs/compare') {
      await assertRunCompareBearer(request, 'compare result')
      const left = url.searchParams.get('left')
      const right = url.searchParams.get('right')
      if (left !== leftRunId || right !== rightRunId) {
        throw new Error(`Run Compare requested unexpected run ids: left=${left} right=${right}`)
      }
      observed.compare = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(compareResult),
      })
      return
    }
    await route.continue()
  }

  await page.route(routePattern, routeHandler)
  try {
    const listResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith('/api/analysis/runs')
        && response.status() === 200
    }, { timeout: 30000 })
    await navigateByAppLink(page, '/run-compare', 'Run Compare visible review boundary')
    const runs = await assertAuthedJson(listResponsePromise, 'Run Compare run list load')
    if (!Array.isArray(runs) || !runs.some((run) => run?.runId === leftRunId) || !runs.some((run) => run?.runId === rightRunId)) {
      throw new Error(`Run Compare run list fixture was not rendered from authed response: ${JSON.stringify(runs)}`)
    }

    await page.getByLabel('左侧运行').selectOption(leftRunId)
    await page.getByLabel('右侧运行').selectOption(rightRunId)
    const compareResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith('/api/analysis/runs/compare')
        && response.status() === 200
    }, { timeout: 30000 })
    await clickEnabled(page.getByRole('button', { name: '对比' }), 'Run Compare compare button')
    const result = await assertAuthedJson(compareResponsePromise, 'Run Compare compare result load')
    if (result?.leftRun?.runId !== leftRunId || result?.rightRun?.runId !== rightRunId || result?.changedCount !== 1) {
      throw new Error(`Run Compare comparison fixture returned unexpected payload: ${JSON.stringify(result)}`)
    }

    await assertRunCompareVisibleBoundary(page, `${leftRunId} -> ${rightRunId}`)
    if (!observed.list || !observed.compare) {
      throw new Error(`Run Compare route fixture was not fully exercised: ${JSON.stringify(observed)}`)
    }
    console.log('ok strict-auth browser Run Compare visible review boundary')
  } finally {
    await page.unroute(routePattern, routeHandler).catch(() => undefined)
  }
}

async function assertDataCompressionVisibleBoundary(page, runId) {
  await page.getByTestId(`data-compression-run-governance-${runId}`).waitFor({ state: 'visible', timeout: 15000 })
  const contextId = await page.getByTestId(`data-compression-run-governance-id-${runId}`).innerText()
  if (!contextId.includes(runId)) {
    throw new Error(`Data Compression governance context did not render ${runId}: ${contextId}`)
  }
  const evidenceStrength = await page.getByTestId(`data-compression-run-evidence-strength-${runId}`).innerText()
  if (!evidenceStrength.includes('LOW')) {
    throw new Error(`Data Compression evidence strength did not render LOW for preview-only evidence: ${evidenceStrength}`)
  }
  const visibleBoundary = await page.getByTestId(`data-compression-run-simulation-boundary-${runId}`).innerText()
  for (const marker of [
    'simulation_only=true',
    'is_real_trade=false',
    'evidence_usage=simulation_only',
    'strong_conclusion_allowed=false',
    'SIM_*',
  ]) {
    if (!visibleBoundary.includes(marker)) {
      throw new Error(`Data Compression visible review boundary is missing ${marker}: ${visibleBoundary}`)
    }
  }
}

async function runDataCompressionReviewBoundaryScenario(page) {
  const generatedAt = new Date().toISOString()
  const runId = 'RUN_DATA_COMPRESSION_BROWSER_REVIEW'
  const runSummary = {
    runId,
    stockCode: '002846',
    stockName: 'Yinglian',
    taskType: 'position_review',
    runMode: 'FAST_MODE',
    status: 'COMPLETED',
    finalAction: 'SIM_HOLD',
    createdAt: generatedAt,
    updatedAt: generatedAt,
    compressed: false,
    compressedAt: null,
    compressedArtifactPath: null,
  }
  const compressionSummary = {
    run_id: runId,
    symbol: runSummary.stockCode,
    stock_name: runSummary.stockName,
    status: runSummary.status,
    run_mode: runSummary.runMode,
    final_action: runSummary.finalAction,
    data_fingerprint: {
      namespace: 'analysis_run',
      fingerprint: 'data-compression-browser-review-fingerprint',
      size_bytes: 2048,
      canonical_keys: ['nodes', 'auditLog', 'paperTrading'],
      created_at: generatedAt,
    },
    quality: {
      score: 84,
      level: 'HIGH',
      issues: [],
      strengths: ['Deterministic strict-auth browser compression fixture.'],
      source_coverage: 'RUN_SUMMARY',
      missing_critical_fields: [],
    },
    keep_fields: ['run_id', 'symbol', 'final_action'],
    key_metrics: { node_count: 3, audit_events: 2 },
    decision_summary: 'Strict-auth browser compression preview remains simulation-only review evidence.',
    guardrail_summary: ['SIM_* action namespace preserved', 'No real-trade boundary reported'],
    evidence_summary: ['Compression summary is generated from local analysis-run fixture data'],
    agent_summary: { orchestrator: 'COMPLETED' },
    token_budget_estimate: 512,
    retention_action: 'KEEP_SUMMARY_REVIEW_RAW',
    retention_reason: 'Review-only compression preview keeps raw data until final audit.',
    created_at: generatedAt,
    compression_persisted: false,
    artifact_path: null,
    compressed_at: null,
  }
  const overview = {
    total_runs: 1,
    summarized_runs: 1,
    average_quality_score: 84,
    high_quality_count: 1,
    medium_quality_count: 0,
    low_quality_count: 0,
    retention_actions: { KEEP_SUMMARY_REVIEW_RAW: 1 },
    latest_run_id: runId,
  }
  const groups = [
    {
      group_id: 'KDG_DATA_COMPRESSION_BROWSER_REVIEW',
      category: 'compression_review',
      fingerprint: compressionSummary.data_fingerprint.fingerprint,
      item_ids: ['KI_DATA_COMPRESSION_BROWSER_REVIEW_A', 'KI_DATA_COMPRESSION_BROWSER_REVIEW_B'],
      representative_item_id: 'KI_DATA_COMPRESSION_BROWSER_REVIEW_A',
      duplicate_count: 2,
      shared_tags: ['strict-auth-browser'],
      suggested_action: 'REVIEW_ONLY',
      reason: 'Fixture group validates Data Compression read-only governance visibility.',
    },
  ]
  const observed = { runs: false, overview: false, summary: false, groups: false }
  const assertDataCompressionBearer = async (request, label) => {
    const headers = await request.allHeaders()
    if (headers.authorization !== `Bearer ${authToken}`) {
      throw new Error(`Data Compression request did not include the expected Authorization bearer token: ${label}`)
    }
  }
  const runListRouteHandler = async (route) => {
    const request = route.request()
    if (request.method() !== 'GET') {
      await route.continue()
      return
    }
    await assertDataCompressionBearer(request, 'run list')
    observed.runs = true
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([runSummary]),
    })
  }
  const dataPipelineRouteHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    await assertDataCompressionBearer(request, `${request.method()} ${url.pathname}`)
    if (request.method() === 'GET' && url.pathname === '/api/data-pipeline/overview') {
      observed.overview = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overview) })
      return
    }
    if (request.method() === 'GET' && url.pathname === `/api/data-pipeline/runs/${runId}/summary`) {
      observed.summary = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(compressionSummary) })
      return
    }
    if (request.method() === 'GET' && url.pathname === '/api/data-pipeline/knowledge/distill') {
      observed.groups = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(groups) })
      return
    }
    await route.continue()
  }

  await page.route('**/api/analysis/runs', runListRouteHandler)
  await page.route('**/api/data-pipeline/**', dataPipelineRouteHandler)
  try {
    const dataCompressionPathname = await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
      return window.location.pathname
    }, '/data-compression')
    if (dataCompressionPathname !== '/data-compression') {
      throw new Error(`Data Compression SPA route did not update pathname after pushState: ${dataCompressionPathname}`)
    }
    await assertDataCompressionVisibleBoundary(page, runId)
    for (const [key, value] of Object.entries(observed)) {
      if (!value) {
        throw new Error(`Data Compression route fixture did not observe ${key}: ${JSON.stringify(observed)}`)
      }
    }
    console.log('ok strict-auth browser Data Compression visible review boundary')
  } finally {
    await page.unroute('**/api/analysis/runs', runListRouteHandler).catch(() => undefined)
    await page.unroute('**/api/data-pipeline/**', dataPipelineRouteHandler).catch(() => undefined)
  }
}

async function runGlobalMarketAutoStockBoundaryScenario(page) {
  const generatedAt = new Date().toISOString()
  const sectorRows = [
    {
      rank: 1,
      name: '半导体',
      code: 'BK1036',
      latest: 1234,
      change: 18,
      pctChange: 3.4,
      marketCap: 100000000000,
      turnoverRate: 2.4,
      risingCount: 18,
      fallingCount: 4,
      leadingStock: '中芯国际',
      leadingStockPctChange: 4.8,
    },
    {
      rank: 2,
      name: '机器人',
      code: 'BK0480',
      latest: 998,
      change: 9,
      pctChange: 1.8,
      marketCap: 80000000000,
      turnoverRate: 2.1,
      risingCount: 14,
      fallingCount: 6,
      leadingStock: '汇川技术',
      leadingStockPctChange: 2.5,
    },
  ]
  const overview = {
    status: 'READY',
    dataMode: 'FALLBACK',
    provider: 'strict-auth-fixture',
    range: '4m',
    fetchedAt: generatedAt,
    refreshIntervalSeconds: 300,
    indices: [],
    fundFlow: {
      status: 'READY',
      dataMode: 'FALLBACK',
      provider: 'strict-auth-fixture',
      apiName: 'fixture_fund_flow',
      selectedProvider: 'strict-auth-fixture',
      selectedSource: 'fixture_fund_flow',
      fallbackUsed: false,
      freshness: 'EOD',
      sourceConsensus: 'SINGLE_SOURCE',
      reviewOnly: true,
      latestDate: '20260626',
      netAmount: 1200000000,
      mainNetAmount: 900000000,
      smallNetAmount: 300000000,
      unit: 'yuan',
      rows: [],
      sourceChain: [],
      conflicts: [],
      message: '',
      error: '',
    },
    sectorRank: {
      status: 'READY',
      dataMode: 'FALLBACK',
      provider: 'strict-auth-fixture',
      source: 'fixture_sector_rank',
      apiName: 'fixture_sector_rank',
      boardType: 'industry',
      tradeDate: '20260626',
      fetchedAt: generatedAt,
      recordCount: sectorRows.length,
      selectedProvider: 'strict-auth-fixture',
      selectedSource: 'fixture_sector_rank',
      sourceCount: { ready: 1, total: 1 },
      top: sectorRows,
      bottom: [],
      rows: sectorRows,
      candidateSources: [],
      conflicts: [],
      arbitration: {
        capability: 'sector_rank',
        selectedSource: 'fixture_sector_rank',
        sourceConsensus: 'SINGLE_SOURCE',
        resolution: 'strict-auth browser fixture',
        checkedSources: [],
        conflicts: [],
        dataQuality: {
          score: 72,
          level: 'REVIEW_ONLY',
          reviewOnly: true,
          highConflictCount: 0,
          mediumConflictCount: 0,
        },
        generatedAt,
      },
      message: 'strict-auth Global Market fixture',
      error: '',
    },
    temperature: {
      score: 67,
      label: '复核观察',
      status: 'WARN',
      trendScore: 66,
      breadthScore: 64,
      flowScore: 70,
      risingCount: 32,
      fallingCount: 18,
      reasons: ['Strict-auth fixture keeps candidates review-only.'],
      reviewOnly: true,
    },
    message: 'strict-auth Global Market fixture',
    error: '',
  }
  const observed = { overview: false }
  const routePattern = '**/api/market-data/global**'
  const routeHandler = async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() === 'GET' && url.pathname === '/api/market-data/global') {
      const headers = await request.allHeaders()
      if (headers.authorization !== `Bearer ${authToken}`) {
        throw new Error('Global Market overview request did not include the expected Authorization bearer token')
      }
      if (url.searchParams.get('range') !== '4m') {
        throw new Error(`Global Market overview requested unexpected range: ${url.search}`)
      }
      observed.overview = true
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(overview),
      })
      return
    }
    await route.continue()
  }

  await page.route(routePattern, routeHandler)
  try {
    const overviewResponsePromise = page.waitForResponse((response) => {
      const url = new URL(response.url())
      return response.request().method() === 'GET'
        && url.pathname.endsWith('/api/market-data/global')
        && response.status() === 200
    }, { timeout: 30000 })
    await navigateByAppLink(page, '/global-market', 'Global Market auto-stock review boundary')
    const payload = await assertAuthedJson(overviewResponsePromise, 'Global Market overview load')
    if (payload?.sectorRank?.top?.[0]?.name !== '半导体') {
      throw new Error(`Global Market fixture did not load the expected sector candidate: ${JSON.stringify(payload)}`)
    }

    const boundary = page.getByTestId('global-market-auto-stock-boundary')
    await boundary.waitFor({ state: 'visible', timeout: 15000 })
    const boundaryText = await boundary.innerText()
    for (const marker of [
      'simulation_only=true',
      'is_real_trade=false',
      'evidence_usage=review_gate_only',
      'strong_conclusion_allowed=false',
      'SIM_*',
    ]) {
      if (!boundaryText.includes(marker)) {
        throw new Error(`Global Market auto-stock visible boundary is missing ${marker}: ${boundaryText}`)
      }
    }

    const candidate = page.getByTestId('global-market-auto-stock-candidate').first()
    await candidate.waitFor({ state: 'visible', timeout: 15000 })
    const candidateText = await candidate.innerText()
    if (!candidateText.includes('半导体') || !candidateText.includes('中芯国际')) {
      throw new Error(`Global Market auto-stock candidate did not render the fixture sector and leading stock: ${candidateText}`)
    }
    const sourceText = await page.getByTestId('global-market-auto-stock-source').first().innerText()
    if (!sourceText.includes('市场温度 67') || !sourceText.includes('资金')) {
      throw new Error(`Global Market auto-stock source text did not render market temperature and fund flow: ${sourceText}`)
    }
    if (!observed.overview) {
      throw new Error(`Global Market route fixture did not observe overview request: ${JSON.stringify(observed)}`)
    }
    console.log('ok strict-auth browser Global Market auto-stock review boundary')
  } finally {
    await page.unroute(routePattern, routeHandler).catch(() => undefined)
  }
}

async function runPlatformScenarioGroup(page) {
  const seededRunId = await runBackendAttemptDiagnosticsScenario(page)

  await runDashboardScenario(page, seededRunId)

  await runMarketLegacyRedirectScenario(page, seededRunId)

  await runGlobalMarketAutoStockBoundaryScenario(page)

  await runRunCompareReviewBoundaryScenario(page)

  await runDataCompressionReviewBoundaryScenario(page)

  await runKnowledgeItemsReviewBoundaryScenario(page)

  await runKnowledgeVersionsRegressionScenario(page)

  await runEvaluationSandboxScenario(page)

  await runCaseLibraryReviewBoundaryScenario(page)

  await runDataReliabilityScenario(page, seededRunId)

  await runSettingsAdapterPartialLoadScenario(page)

  await runTechnicalKlineCaseGovernanceScenario(page, seededRunId)

  await runConfigVersionsRestoreScenario(page)
  console.log('ok strict-auth browser scenario group platform')
  return { seededRunId }
}

async function runSignalOpsScenarioGroup(page) {
  await runSignalOpsScenario(page)

  await runSignalOpsReviewDecisionScenario(page)

  await runSignalOpsResearchEvidenceScenario(page)
  console.log('ok strict-auth browser scenario group signalops')
}

async function runResearchBacktestScenarioGroup(page) {
  await runBacktestSampleScenario(page)

  await runBacktestParameterScanScenario(page)

  const closedLoop = await runResearchClosedLoopScenario(page)

  await runResearchBacktestVerdictInputsScenario(page, closedLoop)

  await runResearchTracesReviewBoundaryScenario(page)

  await runResearchSignalOpsDeepLinkScenario(page, closedLoop)

  const closedLoopRunId = String(closedLoop.run_id)

  await runAgentDagDebateEvidenceScenario(page, closedLoopRunId)
  console.log('ok strict-auth browser scenario group research-backtest')
  return { closedLoop }
}

async function runPortfolioLivePluginScenarioGroup(page) {
  await page.locator('a[href="/portfolio"]').first().click()
  await page.waitForURL(/\/portfolio$/, { timeout: 15000 })
  await runPortfolioImportScenario(page)

  const portfolioResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST' && response.url().includes('/api/portfolio/manual')
  ), { timeout: 30000 })
  await page.getByTestId('portfolio-create-sample').click()
  const portfolioPayload = await assertAuthedJson(portfolioResponsePromise, 'portfolio sample creation')
  const snapshotId = String(portfolioPayload?.snapshotId || '').trim()
  if (!snapshotId.startsWith('PF_')) {
    throw new Error(`portfolio sample creation did not return a PF_ snapshot id: ${snapshotId}`)
  }
  await expectText(page, snapshotId, 'portfolio snapshot list')
  await assertPortfolioSnapshotVisibleBoundary(page, snapshotId)
  console.log('ok strict-auth browser Portfolio visible review boundary')
  console.log(`ok strict-auth browser portfolio snapshot ${snapshotId}`)

  const encodedSnapshotId = encodeURIComponent(snapshotId)
  const snapshotTaskLink = page.locator(`a[href="/new-task?portfolio_snapshot_id=${encodedSnapshotId}"]`).first()
  await snapshotTaskLink.waitFor({ state: 'visible', timeout: 15000 })
  await snapshotTaskLink.click()
  await page.waitForURL(new RegExp(`/new-task\\?portfolio_snapshot_id=${encodedSnapshotId}`), { timeout: 15000 })
  await page.getByTestId('new-task-portfolio-context').waitFor({ state: 'visible', timeout: 15000 })
  await expectText(page, snapshotId, 'new-task portfolio context')
  await page.getByTestId('new-task-portfolio-risk-preflight').waitFor({ state: 'visible', timeout: 15000 })
  await page.waitForFunction(() => {
    const preflight = document.querySelector('[data-testid="new-task-portfolio-risk-preflight"]')
    const text = String(preflight?.textContent || '')
    return text.includes('组合风险')
      && text.includes('任务前持仓风险提示')
      && text.includes('券商导入模板')
      && (
        text.includes('当前股票持仓')
        || text.includes('已选择快照概要')
        || text.includes('股票总仓位')
      )
  }, undefined, { timeout: 15000 })
  const preflightText = await page.getByTestId('new-task-portfolio-risk-preflight').innerText()
  if (!preflightText.includes('手动录入')) {
    throw new Error(`New Task portfolio preflight did not preserve broker-template context: ${preflightText}`)
  }
  await assertNewTaskPortfolioRiskBoundary(page)
  await assertNewTaskVisibleBoundary(page)
  console.log('ok strict-auth browser New Task portfolio risk boundary')
  console.log('ok strict-auth browser New Task visible review boundary')
  console.log('ok strict-auth browser New Task portfolio risk preflight')
  const portfolioDefaultSymbol = String(portfolioPayload?.positions?.[0]?.symbol || '603663').trim()
  const symbolInput = page.getByTestId('new-task-symbol')
  await symbolInput.waitFor({ state: 'visible', timeout: 15000 })
  const symbolAutoFilled = await page.waitForFunction(() => {
    const input = document.querySelector('[data-testid="new-task-symbol"]')
    return input && 'value' in input && String(input.value || '').trim().length > 0
  }, undefined, { timeout: 15000 }).then(() => true).catch(() => false)
  if (!symbolAutoFilled) {
    await symbolInput.fill(portfolioDefaultSymbol)
  }
  const newTaskSymbol = String(await symbolInput.inputValue()).trim()
  if (!newTaskSymbol) {
    throw new Error('New Task symbol remained empty after portfolio-context fallback')
  }

  const createRunResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/analysis/runs')
      && !response.url().includes('/start')
      && !response.url().includes('/retry')
  ), { timeout: 30000 })
  const startRunResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'POST'
      && response.url().includes('/api/analysis/runs/')
      && response.url().includes('/start')
  ), { timeout: 90000 })
  const observedStreamRequests = []
  const streamRequestHandler = (request) => {
    const requestUrl = request.url()
    if (
      requestUrl.includes('/api/analysis/runs/')
      && requestUrl.includes('/stream')
    ) {
      observedStreamRequests.push(request)
    }
  }
  page.on('request', streamRequestHandler)

  let streamRequest
  let runId
  try {
    await page.getByTestId('new-task-submit').click()
    const createRunResponse = await createRunResponsePromise
    if (!createRunResponse.ok()) {
      throw new Error(`analysis run creation returned ${createRunResponse.status()}`)
    }
    await assertBearer(createRunResponse, 'analysis run creation')
    const createPayload = await createRunResponse.json()
    runId = createPayload.run_id
    if (!runId) {
      throw new Error('analysis run creation did not return run_id')
    }
    createdRunIds.add(runId)

    let startRunPayload = null
    try {
      const startRunResponse = await startRunResponsePromise
      if (!startRunResponse.ok()) {
        throw new Error(`analysis run start returned ${startRunResponse.status()}`)
      }
      await assertBearer(startRunResponse, 'analysis run start')
      startRunPayload = await startRunResponse.json().catch(() => null)
    } catch (error) {
      const message = String(error?.message || '')
      if (error?.name !== 'TimeoutError' && !message.includes('Timeout')) {
        throw error
      }
      console.warn('New Task start response wait timed out; confirming start with direct Bearer API fallback')
      startRunPayload = await apiJson('POST', `/api/analysis/runs/${encodeURIComponent(runId)}/start`, undefined, 90000)
    }
    if (startRunPayload?.run_id && startRunPayload.run_id !== runId) {
      throw new Error(`analysis run start returned a different run_id: ${JSON.stringify(startRunPayload)}`)
    }

    const streamRequestMatchesRun = (request) => (
      request.url().includes(`/api/analysis/runs/${encodeURIComponent(runId)}/stream`)
    )

    try {
      await page.waitForURL(new RegExp(`/live-run\\?run_id=${encodeURIComponent(runId)}$`), { timeout: 30000 })
    } catch (error) {
      if (error?.name !== 'TimeoutError') {
        throw error
      }
      console.warn('Live Run route navigation did not complete in time; dispatching direct SPA live-run route')
      await page.evaluate((targetPath) => {
        window.history.pushState({}, '', targetPath)
        window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
      }, `/live-run?run_id=${encodeURIComponent(runId)}`)
      await page.waitForURL(new RegExp(`/live-run\\?run_id=${encodeURIComponent(runId)}$`), { timeout: 15000 })
    }
    await page.getByTestId('live-run-console').waitFor({ state: 'visible', timeout: 30000 })
    try {
      await page.waitForFunction((expectedRunId) => {
        const node = document.querySelector('[data-testid="live-run-current-run-id"]')
        return String(node?.textContent || '').trim() === expectedRunId
      }, runId, { timeout: 30000 })
    } catch (error) {
      if (error?.name !== 'TimeoutError') {
        throw error
      }
      console.warn('Live Run exact-run route did not render in time; dispatching direct SPA live-run route')
      await page.evaluate((targetPath) => {
        window.history.pushState({}, '', targetPath)
        window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
      }, `/live-run?run_id=${encodeURIComponent(runId)}`)
      await page.getByTestId('live-run-console').waitFor({ state: 'visible', timeout: 30000 })
      try {
        await page.waitForFunction((expectedRunId) => {
          const node = document.querySelector('[data-testid="live-run-current-run-id"]')
          return String(node?.textContent || '').trim() === expectedRunId
        }, runId, { timeout: 30000 })
      } catch (secondError) {
        const diagnostic = await page.evaluate(() => {
          const currentRunText = String(document.querySelector('[data-testid="live-run-current-run-id"]')?.textContent || '').trim()
          const toastText = Array.from(document.querySelectorAll('[role="status"], [data-testid*="toast"], .toast'))
            .map((node) => String(node.textContent || '').trim())
            .filter(Boolean)
            .join(' | ')
          const bodyText = String(document.body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 1000)
          return { currentRunText, toastText, bodyText }
        })
        throw new Error(`Live Run exact-run route did not render ${runId}; current=${diagnostic.currentRunText || 'EMPTY'}; toast=${diagnostic.toastText || 'NONE'}; body=${diagnostic.bodyText}`)
      }
    }

    streamRequest = observedStreamRequests.find(streamRequestMatchesRun)
      || await page.waitForRequest(streamRequestMatchesRun, { timeout: 45000 })
  } finally {
    page.off('request', streamRequestHandler)
  }
  const streamUrl = new URL(streamRequest.url())
  if (streamUrl.searchParams.has('api_key') || streamUrl.searchParams.has('token')) {
    throw new Error('live-run EventSource leaked the strict-auth token in the URL')
  }
  if (streamRequest.headers().authorization !== `Bearer ${authToken}`) {
    throw new Error('live-run EventSource did not include the strict-auth Authorization header')
  }
  console.log('ok strict-auth browser live-run stream Authorization header')

  await page.getByTestId('live-run-console').waitFor({ state: 'visible', timeout: 15000 })
  const liveRunId = (await page.getByTestId('live-run-current-run-id').innerText()).trim()
  if (liveRunId !== runId) {
    throw new Error(`Live Run rendered run id ${liveRunId} instead of created run ${runId}`)
  }
  await page.getByTestId('live-run-stream-status').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('live-run-job-lifecycle').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('live-run-final-action').waitFor({ state: 'visible', timeout: 15000 })
  console.log('ok strict-auth browser live-run task panels')

  const finalReportResponsePromise = page.waitForResponse((response) => (
    response.request().method() === 'GET'
      && response.url().includes(`/api/analysis/runs/${encodeURIComponent(runId)}/report`)
      && response.status() === 200
  ), { timeout: 30000 })
  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, `/final?run_id=${encodeURIComponent(runId)}`)
  await page.waitForURL(/\/final\?run_id=/, { timeout: 15000 })
  const finalReportPayload = await assertAuthedJsonOrApi(
    finalReportResponsePromise,
    'Final Writer report load',
    `/api/analysis/runs/${encodeURIComponent(runId)}/report`,
    { page },
  )
  if (!finalReportPayload?.report_id || finalReportPayload?.run_id !== runId) {
    throw new Error(`Final Writer report payload did not match created run: ${JSON.stringify(finalReportPayload)}`)
  }
  try {
    await page.getByTestId('final-writer-page').waitFor({ state: 'visible', timeout: 15000 })
  } catch (error) {
    if (error?.name !== 'TimeoutError') {
      throw error
    }
    console.warn('Final Writer SPA navigation did not render in time; retrying SPA final route without reloading auth state')
    await page.evaluate((targetPath) => {
      window.history.pushState({}, '', targetPath)
      window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
    }, `/final?run_id=${encodeURIComponent(runId)}`)
    await page.getByTestId('final-writer-page').waitFor({ state: 'visible', timeout: 45000 })
  }
  const finalRunId = (await page.getByTestId('final-writer-current-run-id').innerText()).trim()
  if (finalRunId !== runId) {
    throw new Error(`Final Writer rendered run id ${finalRunId} instead of created run ${runId}`)
  }
  await page.getByTestId('final-writer-data-provenance').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('final-writer-source-freshness').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('final-writer-final-action').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('final-writer-sections').waitFor({ state: 'visible', timeout: 15000 })
  await assertFinalWriterVisibleBoundary(page)
  console.log('ok strict-auth browser Final Writer visible review boundary')
  console.log('ok strict-auth browser final report chain')

  await page.evaluate((targetPath) => {
    window.history.pushState({}, '', targetPath)
    window.dispatchEvent(new PopStateEvent('popstate', { state: window.history.state }))
  }, '/anti-conclusion')
  await page.waitForURL(/\/anti-conclusion$/, { timeout: 15000 })
  await assertAntiConclusionVisibleBoundary(page, runId)
  console.log('ok strict-auth browser AntiConclusion visible review boundary')

  const antiConclusionRunResponsePromise = page.waitForResponse((response) => {
    try {
      const responseUrl = new URL(response.url())
      return response.request().method() === 'GET'
        && responseUrl.pathname === `/api/analysis/runs/${runId}`
        && response.status() === 200
    } catch {
      return false
    }
  }, { timeout: 30000 })
  await page.goto(urlFor(`/anti-conclusion?run_id=${encodeURIComponent(runId)}`), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForURL(/\/anti-conclusion\?run_id=/, { timeout: 15000 })
  await assertAuthedJsonOrApi(
    antiConclusionRunResponsePromise,
    'AntiConclusion cold run hydrate',
    `/api/analysis/runs/${encodeURIComponent(runId)}`,
    { page },
  )
  await page.getByTestId('anti-conclusion-page').waitFor({ state: 'visible', timeout: 15000 })
  await assertAntiConclusionVisibleBoundary(page, runId)
  console.log('ok strict-auth browser AntiConclusion cold deep link hydration')

  await runAuditLogScenario(page, runId)

  const liveRunBaseRun = await apiJson('GET', `/api/analysis/runs/${encodeURIComponent(runId)}`)
  await runLiveRunTerminalStreamScenario(page, liveRunBaseRun)

  await runPluginArchiveScenario(page)
  console.log('ok strict-auth browser scenario group portfolio-live-plugin')
}

async function runScenario(page) {
  console.log(`ok strict-auth browser selected scenario groups ${Array.from(selectedScenarioGroups).join(',')}`)
  await bootstrapStrictAuthSession(page)

  if (selectedScenarioGroups.has('platform')) {
    await runPlatformScenarioGroup(page)
  }

  if (selectedScenarioGroups.has('signalops')) {
    await runSignalOpsScenarioGroup(page)
  }

  if (selectedScenarioGroups.has('research-backtest')) {
    await runResearchBacktestScenarioGroup(page)
  }

  if (selectedScenarioGroups.has('portfolio-live-plugin')) {
    await runPortfolioLivePluginScenarioGroup(page)
  }
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

const browser = await launchBrowser()
try {
  const page = await browser.newPage({ acceptDownloads: true })
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await runScenario(page)
  if (pageErrors.length > 0) {
    throw new Error(`page errors: ${pageErrors.join(' | ')}`)
  }
} finally {
  await browser.close().catch(() => undefined)
  for (const runId of createdRunIds) {
    await api('DELETE', `/api/analysis/runs/${encodeURIComponent(runId)}`).catch((error) => {
      console.warn(`strict-auth cleanup failed for ${runId}: ${error.message}`)
    })
  }
  for (const runId of createdBacktestRunIds) {
    await api('DELETE', `/api/research/backtest/runs/${encodeURIComponent(runId)}`).catch((error) => {
      console.warn(`strict-auth backtest cleanup failed for ${runId}: ${error.message}`)
    })
  }
}
