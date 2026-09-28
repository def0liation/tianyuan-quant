import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const baseUrl = process.env.RESEARCH_CLOSURE_FRONTEND_URL || process.env.FRONTEND_URL
const backendUrl = process.env.RESEARCH_CLOSURE_BACKEND_URL
const browserRequired = process.env.RESEARCH_CLOSURE_BROWSER_REQUIRED === '1'
const scriptDir = path.dirname(fileURLToPath(import.meta.url))

if (!baseUrl) {
  console.log('skip browser smoke: RESEARCH_CLOSURE_FRONTEND_URL is not set.')
  process.exit(0)
}

if (!backendUrl) {
  console.log('skip browser smoke: RESEARCH_CLOSURE_BACKEND_URL is not set.')
  process.exit(0)
}

let chromium
try {
  ;({ chromium } = await import('playwright'))
} catch {
  try {
    const playwrightUrl = pathToFileURL(path.join(scriptDir, '..', 'frontend', 'node_modules', 'playwright', 'index.mjs')).href
    ;({ chromium } = await import(playwrightUrl))
  } catch {
    const message = 'browser smoke requires Playwright. Install it locally before running smoke:research-closure:browser.'
    if (browserRequired) {
      console.error(message)
      process.exit(1)
    }
    console.log(`skip browser smoke: ${message}`)
    process.exit(0)
  }
}

const consoleErrors = []
let currentRoute = ''
let lastApi = ''
let lastApiResponse = ''
let lastBrowserApi = ''
let lastBrowserApiResponse = ''
const createdRunIds = new Set()

function urlFor(path, root = baseUrl) {
  return new URL(path, root).toString()
}

async function api(method, path, body) {
  const url = urlFor(path, backendUrl)
  lastApi = `${method} ${url}`
  const response = await fetch(url, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Operator-ID': 'research-closure-browser-smoke',
      'X-Operator-Role': 'admin',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  lastApiResponse = text
  const payload = text ? JSON.parse(text) : {}
  if (!response.ok) {
    throw new Error(`API ${method} ${url} returned ${response.status}: ${text}`)
  }
  return payload
}

async function expectText(page, text, label) {
  await page.waitForFunction((expected) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    let node = walker.nextNode()
    while (node) {
      const value = node.textContent || ''
      const element = node.parentElement
      if (element && value.includes(expected) && element.tagName !== 'OPTION') {
        const style = window.getComputedStyle(element)
        const visible = style.display !== 'none'
          && style.visibility !== 'hidden'
          && element.getClientRects().length > 0
        if (visible) return true
      }
      node = walker.nextNode()
    }
    return false
  }, text, { timeout: 15000 })
  console.log(`ok browser ${label}`)
}

async function verifyTopBarCurrentRun(page, runId, label) {
  await page.waitForFunction((expectedRunId) => {
    const renderedRunId = document.querySelector('[data-testid="topbar-current-run-id"]')?.textContent?.trim()
    return renderedRunId === expectedRunId
  }, runId, { timeout: 15000 })
  console.log(`ok browser ${label} topbar current run id`)
}

async function waitForCurrentResearchIteration(page, loopId, iterationId, label) {
  try {
    await page.waitForFunction(({ loopId: expectedLoopId, iterationId: expectedIterationId }) => {
      const loopText = document.querySelector('[data-testid="current-loop-id"]')?.textContent || ''
      const iterationText = document.querySelector('[data-testid="current-iteration-id"]')?.textContent || ''
      return loopText.includes(expectedLoopId) && iterationText.includes(expectedIterationId)
    }, {
      loopId,
      iterationId,
    }, { timeout: 45000 })
  } catch (error) {
    const loopText = await page.getByTestId('current-loop-id').innerText().catch(() => '<missing>')
    const iterationText = await page.getByTestId('current-iteration-id').innerText().catch(() => '<missing>')
    throw new Error(`${label} did not select expected research iteration. expected loop=${loopId} iteration=${iterationId}; current loop="${loopText}" iteration="${iterationText}"`)
  }
  console.log(`ok browser ${label}`)
}

function isIgnorableConsoleError(text, route = '') {
  if (text.includes('Failed to load resource: the server responded with a status of 502 (Bad Gateway)')) {
    return true
  }
  return route === '/audit' && /TypeError:\s*(Failed to fetch|network error)/i.test(text)
}

function browserApiMatches(url, apiPath) {
  try {
    const parsed = new URL(url)
    return parsed.pathname === `/api${apiPath}`
  } catch {
    return false
  }
}

async function waitForBrowserApi(page, method, apiPath, label) {
  const response = await page.waitForResponse((candidate) => {
    return candidate.request().method() === method && browserApiMatches(candidate.url(), apiPath)
  }, { timeout: 30000 })
  const text = await response.text()
  if (!response.ok()) {
    throw new Error(`browser API ${method} ${apiPath} returned ${response.status()}: ${text}`)
  }
  console.log(`ok browser ${label} ${response.status()}`)
  return text
}

function isStartRunBrowserResponse(response) {
  try {
    const parsed = new URL(response.url())
    return response.request().method() === 'POST'
      && parsed.pathname.startsWith('/api/analysis/runs/')
      && parsed.pathname.endsWith('/start')
  } catch {
    return false
  }
}

function parseJsonText(text) {
  if (!text) return {}
  try {
    return JSON.parse(text)
  } catch {
    return { message: text }
  }
}

function asRecord(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
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

function collectStartRunBrowserResponses(page) {
  const records = []
  const handler = async (response) => {
    if (!isStartRunBrowserResponse(response)) return
    try {
      const text = await response.text()
      records.push({
        url: response.url(),
        status: response.status(),
        ok: response.ok(),
        text,
        payload: parseJsonText(text),
      })
    } catch (error) {
      records.push({
        url: response.url(),
        status: response.status(),
        ok: response.ok(),
        text: error instanceof Error ? error.message : String(error),
        payload: {},
      })
    }
  }
  page.on('response', handler)
  return {
    records,
    stop: () => page.off('response', handler),
  }
}

async function waitForCollectedStartRun(records, runId, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const exactOk = records.find((record) => record.ok && record.url.includes(`/api/analysis/runs/${runId}/start`))
    if (exactOk) return exactOk
    const exactAny = records.find((record) => record.url.includes(`/api/analysis/runs/${runId}/start`))
    if (exactAny) return exactAny
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  return null
}

async function verifyAuditDirectLoad(page, runId) {
  currentRoute = '/audit'
  const runResponse = waitForBrowserApi(page, 'GET', `/analysis/runs/${runId}`, 'audit direct-load run hydrate')
  const auditResponse = waitForBrowserApi(page, 'GET', `/analysis/runs/${runId}/audit`, 'audit direct-load audit client')
  await page.goto(urlFor(`/audit?run_id=${encodeURIComponent(runId)}`), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('#root', { timeout: 10000 })
  await runResponse
  const auditText = await auditResponse
  const auditEvents = auditText ? JSON.parse(auditText) : []
  if (!Array.isArray(auditEvents) || auditEvents.length === 0) {
    throw new Error(`audit direct-load returned no events for ${runId}: ${auditText}`)
  }
  const visibleEvent = auditEvents.find((event) => String(event?.message || '').trim())
    ?? auditEvents.find((event) => String(event?.node || '').trim())
    ?? auditEvents[0]
  const eventMarker = String(visibleEvent.message || visibleEvent.node || visibleEvent.audit_id || visibleEvent.auditId || '').trim()
  if (!eventMarker) {
    throw new Error(`audit direct-load returned events without a visible marker for ${runId}: ${auditText}`)
  }
  await expectText(page, eventMarker, 'audit direct-load event')
}

async function verifyQuantCoreDirectLoad(page, runId, symbol) {
  currentRoute = '/quant-core'
  const runResponse = waitForBrowserApi(page, 'GET', `/analysis/runs/${runId}`, 'quant-core direct-load run hydrate')
  await page.goto(urlFor(`/quant-core?run_id=${encodeURIComponent(runId)}`), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('#root', { timeout: 10000 })
  await runResponse
  await expectText(page, '量化核心', 'quant-core direct-load page title')
  await expectText(page, symbol, 'quant-core direct-load current run symbol')
}

async function verifyCurrentRunDirectLoad(page, route, runId, symbol, testId, label) {
  currentRoute = route
  const runResponse = waitForBrowserApi(page, 'GET', `/analysis/runs/${runId}`, `${label} direct-load run hydrate`)
  await page.goto(urlFor(`${route}?run_id=${encodeURIComponent(runId)}`), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('#root', { timeout: 10000 })
  await runResponse
  await page.getByTestId(testId).waitFor({ state: 'visible', timeout: 15000 })
  await verifyTopBarCurrentRun(page, runId, `${label} direct-load`)
  await expectText(page, symbol, `${label} direct-load current run symbol`)
}

async function verifyRunContextWritePageDirectLoad(page, route, runId, testId, label) {
  currentRoute = route
  const runResponse = waitForBrowserApi(page, 'GET', `/analysis/runs/${runId}`, `${label} direct-load run hydrate`)
  await page.goto(urlFor(`${route}?run_id=${encodeURIComponent(runId)}`), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('#root', { timeout: 10000 })
  await runResponse
  await verifyTopBarCurrentRun(page, runId, `${label} direct-load`)
  await page.waitForFunction(({ testId, runId }) => {
    const renderedRunId = document.querySelector(`[data-testid="${testId}"]`)?.textContent?.trim()
    return Boolean(renderedRunId && renderedRunId.includes(runId))
  }, { testId, runId }, { timeout: 15000 })
  console.log(`ok browser ${label} direct-load write run context`)
}

function productionHealthWindow(window, overrides = {}) {
  return {
    window,
    runSuccessRate: { total: 10, succeeded: 8, successRate: 0.8, ...(overrides.runSuccessRate || {}) },
    llmCallFailureRate: { total: 10, failed: 1, failureRate: 0.1, ...(overrides.llmCallFailureRate || {}) },
    marketDataFallbackRate: { total: 10, fallbackOrMock: 2, fallbackRate: 0.2, ...(overrides.marketDataFallbackRate || {}) },
    signalOpsTickSuccessRate: { total: 5, succeeded: 4, successRate: 0.8, ...(overrides.signalOpsTickSuccessRate || {}) },
    staleJobs: { currentCount: 1, jobTotal: 5, ...(overrides.staleJobs || {}) },
    errorBudget: { status: 'warning', consumedPercent: 42.5, remainingPercent: 57.5, ...(overrides.errorBudget || {}) },
  }
}

async function verifyBackendStatusProductionHealth(page) {
  currentRoute = '/backend'
  const metricsFixture = {
    service: 'browser-smoke',
    generatedAt: '2026-05-31T00:00:00Z',
    productionHealth: {
      status: 'warning',
      generatedAt: '2026-05-31T00:00:00Z',
      externalCalls: false,
      windows: {
        '24h': productionHealthWindow('24h', {
          runSuccessRate: { total: 12, succeeded: 11, successRate: 0.916 },
          llmCallFailureRate: {
            total: 12,
            succeeded: 11,
            failed: 1,
            skipped: 1,
            failureRate: 0.083,
            totalTokens: 128,
            failureReasons: [{ reason: 'browser smoke provider timeout token=[REDACTED]', count: 1 }],
            sampleFailures: [
              { runId: 'RUN_BROWSER_PROD_HEALTH', node: 'final_writer', status: 'FAILED', reason: 'browser smoke provider timeout token=[REDACTED]' },
            ],
          },
          marketDataFallbackRate: { total: 12, fallbackOrMock: 2, fallbackRate: 0.166 },
          signalOpsTickSuccessRate: { total: 6, succeeded: 6, successRate: 1 },
          staleJobs: { currentCount: 0, jobTotal: 4 },
          errorBudget: { status: 'ok', consumedPercent: 18.4, remainingPercent: 81.6 },
        }),
        '7d': productionHealthWindow('7d', {
          runSuccessRate: { total: 50, succeeded: 42, successRate: 0.84 },
          llmCallFailureRate: { total: 50, failed: 4, failureRate: 0.08 },
          marketDataFallbackRate: { total: 50, fallbackOrMock: 6, fallbackRate: 0.12 },
          signalOpsTickSuccessRate: { total: 20, succeeded: 17, successRate: 0.85 },
          staleJobs: { currentCount: 2, jobTotal: 9 },
          errorBudget: { status: 'warning', consumedPercent: 71.2, remainingPercent: 28.8 },
        }),
      },
      alerts: [
        {
          severity: 'warning',
          window: '7d',
          metric: 'runSuccessRate',
          message: 'browser smoke alert for visible health trend',
        },
      ],
      errorBudget: { status: 'warning', consumedPercent: 71.2, remainingPercent: 28.8 },
      sourceErrors: {
        analysisJobs: 'browser smoke injected source warning',
      },
    },
  }

  await page.route('**/api/metrics', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(metricsFixture),
    })
  })
  try {
    const metricsResponse = page.waitForResponse((response) => response.url().includes('/api/metrics'), { timeout: 30000 })
    await page.goto(urlFor('/backend'), { waitUntil: 'domcontentloaded', timeout: 30000 })
    await page.waitForSelector('#root', { timeout: 10000 })
    const response = await metricsResponse
    if (!response.ok()) {
      throw new Error(`backend production health fixture returned ${response.status()}: ${await response.text()}`)
    }
    const trendTable = page.getByTestId('backend-production-health-trends')
    await trendTable.waitFor({ state: 'visible', timeout: 15000 })
    await trendTable.getByText('24h', { exact: true }).waitFor({ state: 'visible', timeout: 10000 })
    await trendTable.getByText('7d', { exact: true }).waitFor({ state: 'visible', timeout: 10000 })
    await trendTable.getByText('91.6%', { exact: true }).waitFor({ state: 'visible', timeout: 10000 })
    await trendTable.getByText('84.0%', { exact: true }).waitFor({ state: 'visible', timeout: 10000 })
    const llmFailureReasons = page.getByTestId('backend-production-health-llm-failure-reasons')
    await llmFailureReasons.waitFor({ state: 'visible', timeout: 10000 })
    const llmFailureReasonText = await llmFailureReasons.innerText()
    if (
      !llmFailureReasonText.includes('browser smoke provider timeout token=[REDACTED]')
      || !llmFailureReasonText.includes('RUN_BROWSER_PROD_HEALTH')
      || llmFailureReasonText.includes('unit-secret')
    ) {
      throw new Error(`Backend Status LLM failure reasons did not render the redacted fixture: ${llmFailureReasonText}`)
    }
    console.log('ok browser backend production health LLM failure reasons')

    const sourceErrors = page.getByTestId('backend-production-health-source-errors')
    await sourceErrors.waitFor({ state: 'visible', timeout: 10000 })
    const sourceErrorText = await sourceErrors.innerText()
    if (!sourceErrorText.includes('analysisJobs') || !sourceErrorText.includes('browser smoke injected source warning')) {
      throw new Error(`Backend Status source errors did not render injected fixture text: ${sourceErrorText}`)
    }
    console.log('ok browser backend production health trends')
  } finally {
    await page.unroute('**/api/metrics').catch(() => undefined)
  }
}

async function expectRetryDisabledReason(page) {
  const locator = page.getByTestId('mfe-mae-retry-disabled-reason').first()
  await locator.waitFor({ state: 'visible', timeout: 15000 })
  try {
    await page.waitForFunction(() => {
      const element = document.querySelector('[data-testid="mfe-mae-retry-disabled-reason"]')
      const text = element?.textContent?.trim() || ''
      const hasPrefix = text.startsWith('Retry disabled:') || text.startsWith('重试已禁用：')
      return hasPrefix
        && text !== 'Retry disabled:'
        && text !== '重试已禁用：'
        && !text.includes('still loading')
        && !text.includes('正在加载')
        && !text.includes('No linked run is loaded')
        && !text.includes('failed to load')
        && !text.includes('加载失败')
    }, { timeout: 30000 })
  } catch (error) {
    const text = await locator.innerText().catch(() => '<missing>')
    throw new Error(`MFE/MAE linked run did not finish loading before retry assertion. current="${text}"`)
  }
  const text = (await locator.innerText()).trim()
  const hasPrefix = text.startsWith('Retry disabled:') || text.startsWith('重试已禁用：')
  if (!hasPrefix || text === 'Retry disabled:' || text === '重试已禁用：') {
    throw new Error(`MFE/MAE retry disabled reason was not populated: ${text}`)
  }
  if (text.includes('still loading') || text.includes('正在加载') || text.includes('No linked run is loaded') || text.includes('failed to load') || text.includes('加载失败')) {
    throw new Error(`MFE/MAE linked run was not loaded before retry disabled assertion: ${text}`)
  }
  console.log(`ok browser MFE/MAE retry disabled reason ${text}`)
}

async function runScenario(page) {
  const suffix = Date.now().toString(36)

  await verifyBackendStatusProductionHealth(page)

  currentRoute = '/portfolio'
  await page.goto(urlFor(currentRoute), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('#root', { timeout: 10000 })
  await page.getByTestId('portfolio-create-sample').click()
  await page.getByTestId('portfolio-broker-template').first().waitFor({ state: 'visible', timeout: 15000 })
  const snapshotLocator = page.getByTestId('portfolio-snapshot-id').first()
  await snapshotLocator.waitFor({ state: 'visible', timeout: 15000 })
  const snapshotId = (await snapshotLocator.innerText()).trim()
  if (!snapshotId || !snapshotId.startsWith('PF_')) {
    throw new Error(`portfolio UI did not create a PF_ snapshot id: ${snapshotId}`)
  }
  console.log(`ok browser portfolio snapshot ${snapshotId}`)

  await page.getByTestId('portfolio-use-new-task').first().click()
  await page.waitForURL(/\/new-task\?portfolio_snapshot_id=/, { timeout: 15000 })
  currentRoute = '/new-task'
  await page.getByTestId('new-task-portfolio-context').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('new-task-portfolio-risk-preflight').waitFor({ state: 'visible', timeout: 15000 })
  await expectText(page, snapshotId, 'new-task portfolio snapshot id')
  await expectText(page, '组合风险', 'new-task portfolio risk preflight')
  await expectText(page, '导入模板', 'new-task portfolio import template')
  await page.waitForFunction(() => {
    const input = document.querySelector('[data-testid="new-task-symbol"]')
    return input && 'value' in input && String(input.value || '').trim().length > 0
  }, { timeout: 15000 })
  const uiSymbol = (await page.getByTestId('new-task-symbol').inputValue()).trim()
  if (!uiSymbol) throw new Error('new-task symbol input did not contain a target symbol')

  const createRunResponse = page.waitForResponse((response) => {
    return response.request().method() === 'POST'
      && response.url().includes('/api/analysis/runs')
      && !response.url().includes('/start')
      && !response.url().includes('/retry')
  }, { timeout: 30000 })
  const startRunResponses = collectStartRunBrowserResponses(page)
  await page.getByTestId('new-task-submit').click()
  const createPayload = await (await createRunResponse).json()
  const uiRunId = createPayload.run_id
  if (!uiRunId) throw new Error('new-task create response did not include run_id')
  createdRunIds.add(uiRunId)
  const startRecord = await waitForCollectedStartRun(startRunResponses.records, uiRunId)
  startRunResponses.stop()
  if (startRecord) {
    if (!startRecord.ok) {
      throw new Error(`new-task start returned ${startRecord.status}: ${startRecord.text}`)
    }
    const startStatus = String(startRecord.payload.status)
    if (!['QUEUED', 'RUNNING'].includes(startStatus)) {
      throw new Error(`new-task start returned unexpected status ${startRecord.payload.status}`)
    }
  }
  try {
    await page.waitForURL(/\/live-run/, { waitUntil: 'domcontentloaded', timeout: 30000 })
  } catch (error) {
    await page.goto(urlFor(`/live-run?run_id=${encodeURIComponent(uiRunId)}`), { waitUntil: 'domcontentloaded', timeout: 30000 })
    console.log(`ok browser new-task live-run direct fallback ${uiRunId}`)
  }
  currentRoute = '/live-run'
  await expectText(page, uiRunId, 'live-run id from new-task')
  if (!startRecord) {
    const runDetail = await api('GET', `/api/analysis/runs/${uiRunId}`)
    const detailRunId = runDetail.run_id || runDetail.runId
    if (detailRunId !== uiRunId) {
      throw new Error(`new-task live-run fallback loaded wrong run detail: ${JSON.stringify(runDetail).slice(0, 500)}`)
    }
    console.log(`ok browser new-task start observed via live-run ${uiRunId}`)
  }
  console.log(`ok browser new-task live-run ${uiRunId} ${startRecord?.payload?.status || 'OBSERVED'}`)

  await verifyAuditDirectLoad(page, uiRunId)
  await verifyCurrentRunDirectLoad(page, '/', uiRunId, uiSymbol, 'dashboard-page', 'dashboard')
  await verifyQuantCoreDirectLoad(page, uiRunId, uiSymbol)
  await verifyCurrentRunDirectLoad(page, '/dag', uiRunId, uiSymbol, 'agent-dag-page', 'dag')
  await page.getByTestId('agent-dag-selected-node-governance').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-selected-node-context-id').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-selected-node-evidence-strength').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-selected-node-blocker').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-selected-node-next-action').waitFor({ state: 'visible', timeout: 15000 })
  await page.getByTestId('agent-dag-selected-node-simulation-boundary').waitFor({ state: 'visible', timeout: 15000 })
  console.log('ok browser dag selected node governance')
  await verifyCurrentRunDirectLoad(page, '/debate', uiRunId, uiSymbol, 'agent-debate-page', 'debate')
  await verifyCurrentRunDirectLoad(page, '/final', uiRunId, uiSymbol, 'final-writer-page', 'final')
  await verifyCurrentRunDirectLoad(page, '/signalops', uiRunId, uiSymbol, 'signalops-console', 'signalops')
  const signalOpsRunId = (await page.getByTestId('signalops-current-run-id').innerText()).trim()
  if (signalOpsRunId !== uiRunId) {
    throw new Error(`signalops direct-load rendered current run ${signalOpsRunId || 'EMPTY'} instead of ${uiRunId}`)
  }
  console.log('ok browser signalops direct-load current run id')
  await verifyRunContextWritePageDirectLoad(page, '/case-library', uiRunId, 'case-library-current-run-id', 'case-library')
  await verifyRunContextWritePageDirectLoad(page, '/knowledge', uiRunId, 'knowledge-current-run-id', 'knowledge')

  const loop = await api('POST', '/api/research/loops', {
    title: `Browser Smoke MFE/MAE Closure ${suffix}`,
    objective: 'Exercise Research Lab closure UI with API-created evidence.',
    hypothesis: 'Browser smoke should show warning, disabled retry reason, health summary, and backtest deep link.',
    target_modules: ['mfe_mae_path_research', 'research_lab'],
  })
  const loopId = loop.loop?.loop_id || loop.loop_id
  if (!loopId) throw new Error('created loop did not include loop_id')
  const iterationId = loop.iterations?.[0]?.iteration_id
  if (!iterationId) throw new Error('created loop did not include iteration_id')

  const start = await api('POST', `/api/research/iterations/${iterationId}/start-run`, {
    symbol: 'SMOKEBR001.SZ',
    task_type: 'mfe_mae_path_research',
    run_mode: 'STANDARD_MODE',
    auto_start: false,
    bottom_research_config: {
      repair_probability_threshold: 0.25,
    },
  })
  const createdRunId = start.run_id
  if (!createdRunId) throw new Error('start-run did not return run_id')
  createdRunIds.add(createdRunId)

  const retry = await api('POST', `/api/research/iterations/${iterationId}/mfe-mae/backtest`, {
    run_id: createdRunId,
    force_new: false,
    reviewer: 'research-closure-browser-smoke',
  })
  const warning = retry.metrics?.mfe_mae_research_backtest_warning ?? retry.metrics?.bottom_research_backtest_warning
  if (!warning) throw new Error('MFE/MAE retry did not return warning metrics')

  const backtest = await api('POST', '/api/research/backtest/runs', {
    symbol: 'SMOKEBR001.SZ',
    stock_name: 'Browser Smoke',
    start_date: '2026-01-01',
    end_date: '2026-01-05',
    scenario_label: 'Browser smoke closure deep link',
    parameters: {
      data_source: 'MOCK',
      signal_source: 'NONE',
      simulation_only: true,
      is_real_trade: false,
    },
    reuse_existing: true,
    force_new: false,
  })
  const backtestId = backtest.run_id
  if (!backtestId) throw new Error('backtest creation did not return run_id')

  await api('POST', `/api/research/iterations/${iterationId}/attach-backtest`, {
    backtest_run_id: backtestId,
    reviewer: 'research-closure-browser-smoke',
    note: 'Attached by browser smoke for deep-link verification.',
  })

  currentRoute = '/research-lab/research'
  await page.goto(urlFor(currentRoute), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('#root', { timeout: 10000 })
  await page.locator(`[data-loop-id="${loopId}"]`).first().click()
  await waitForCurrentResearchIteration(page, loopId, iterationId, 'selected research loop id')
  const attachRunId = (await page.getByTestId('research-attach-run-id').inputValue()).trim()
  if (attachRunId !== createdRunId) {
    throw new Error(`Research attach run default used ${attachRunId || 'EMPTY'} instead of linked run ${createdRunId}; current UI run was ${uiRunId}`)
  }
  console.log('ok browser research attach run defaults to linked run id')
  const health = page.locator('[data-testid="closure-health-summary"]')
  await health.waitFor({ state: 'visible', timeout: 15000 })
  console.log('ok browser closure health summary')
  await expectText(page, createdRunId, 'linked run id')
  await expectText(page, warning, 'MFE/MAE retry warning')
  await expectRetryDisabledReason(page)

  await health.getByText('Usable MFE/MAE', { exact: false }).waitFor({ state: 'visible', timeout: 10000 })
  await health.getByText(backtestId, { exact: false }).first().waitFor({ state: 'visible', timeout: 10000 })

  const deepLink = page.locator(`a[href*="${encodeURIComponent(backtestId)}"]`).first()
  await deepLink.waitFor({ state: 'visible', timeout: 10000 })
  await deepLink.click()
  await page.waitForURL(/\/research-lab\/backtest\?run_id=/, { timeout: 15000 })
  if (!page.url().includes(encodeURIComponent(backtestId))) {
    throw new Error(`backtest deep link did not preserve run_id=${backtestId}`)
  }
  console.log(`ok browser backtest deep link ${backtestId}`)

  currentRoute = '/research-lab/research'
  await page.goto(urlFor(currentRoute), { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForSelector('#root', { timeout: 10000 })
  const closedLoopResponse = page.waitForResponse((response) => {
    return response.request().method() === 'POST'
      && browserApiMatches(response.url(), '/research/p2/closed-loop-sample')
  }, { timeout: 60000 })
  const closedLoopButton = page.getByTestId('research-create-closed-loop-sample').first()
  await closedLoopButton.waitFor({ state: 'visible', timeout: 15000 })
  await closedLoopButton.click()
  const closedLoopHttpResponse = await closedLoopResponse
  const closedLoop = await closedLoopHttpResponse.json()
  if (!closedLoopHttpResponse.ok()) {
    throw new Error(`UI P2 closed-loop sample failed ${closedLoopHttpResponse.status()}: ${JSON.stringify(closedLoop)}`)
  }
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
    if (!closedLoop[key]) throw new Error(`P2 closed-loop sample did not return ${key}`)
  }
  assertP2ClosedLoopReviewBoundary(closedLoop, 'P2 closed-loop sample')
  createdRunIds.add(closedLoop.run_id)
  console.log('ok browser research one-click closed-loop sample')

  await page.locator(`[data-loop-id="${closedLoop.loop_id}"]`).waitFor({ state: 'visible', timeout: 30000 })
  await page.locator(`[data-loop-id="${closedLoop.loop_id}"]`).click()
  await waitForCurrentResearchIteration(page, closedLoop.loop_id, closedLoop.iteration_id, 'closed-loop current iteration selection')
  await expectText(page, closedLoop.loop_id, 'research loop id')
  await expectText(page, closedLoop.iteration_id, 'research iteration id')
  await expectText(page, closedLoop.run_id, 'closed-loop run id')
  await expectText(page, closedLoop.backtest_run_id, 'closed-loop backtest id')
  await expectText(page, closedLoop.case_id, 'closed-loop case id')
  await expectText(page, closedLoop.knowledge_item_id, 'closed-loop knowledge id')
  await expectText(page, closedLoop.evaluation_id, 'closed-loop evaluation id')
  await expectText(page, closedLoop.knowledge_version_id, 'closed-loop knowledge version id')

  const blockingReasons = await page.getByTestId('workflow-blocking-reason').allInnerTexts()
  if (blockingReasons.length === 0) {
    throw new Error('research workflow did not expose blocking reasons for weak/supporting evidence')
  }
  const joinedBlockingReasons = blockingReasons.join(' / ')
  if (!/supporting-only|mock|fallback|out-of-sample|benchmark|样本外|支撑材料|mock|fallback/i.test(joinedBlockingReasons)) {
    throw new Error(`research workflow blocking reasons did not mention weak evidence: ${joinedBlockingReasons}`)
  }
  console.log(`ok browser closed-loop ids ${JSON.stringify({
    snapshotId,
    uiRunId,
    runId: closedLoop.run_id,
    backtestId: closedLoop.backtest_run_id,
    loopId: closedLoop.loop_id,
    iterationId: closedLoop.iteration_id,
    caseId: closedLoop.case_id,
    knowledgeId: closedLoop.knowledge_item_id,
    evaluationId: closedLoop.evaluation_id,
    knowledgeVersionId: closedLoop.knowledge_version_id,
  })}`)
}

async function launchBrowser() {
  const candidates = [
    { channel: 'chrome' },
    { channel: 'msedge' },
    {},
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
  const page = await browser.newPage()
  page.on('console', (message) => {
    if (message.type() === 'error') {
      const text = message.text()
      const route = currentRoute || page.url()
      if (!isIgnorableConsoleError(text, route)) {
        consoleErrors.push(`${route}: ${text}`)
      }
    }
  })
  page.on('pageerror', (error) => {
    const route = currentRoute || page.url()
    if (!isIgnorableConsoleError(error.message, route)) {
      consoleErrors.push(`${route}: ${error.message}`)
    }
  })
  page.on('response', async (response) => {
    try {
      const request = response.request()
      const url = response.url()
      if (
        request.method() === 'GET' &&
        url.includes('/api/analysis/runs/RUN_') &&
        !url.includes('/stream')
      ) {
        lastBrowserApi = `${request.method()} ${url} ${response.status()}`
        lastBrowserApiResponse = (await response.text()).slice(0, 2000)
      }
    } catch {
      // Best-effort diagnostics only.
    }
  })

  await runScenario(page)

  if (consoleErrors.length > 0) {
    throw new Error(`browser console errors:\n${consoleErrors.join('\n')}`)
  }
} catch (error) {
  console.error('browser smoke failure diagnostics')
  console.error(`url=${baseUrl}`)
  console.error(`backend=${backendUrl}`)
  console.error(`current_route=${currentRoute}`)
  console.error(`last_api=${lastApi}`)
  console.error(`last_api_response=${lastApiResponse}`)
  console.error(`last_browser_api=${lastBrowserApi}`)
  console.error(`last_browser_api_response=${lastBrowserApiResponse}`)
  if (consoleErrors.length > 0) {
    console.error(`console_errors=\n${consoleErrors.join('\n')}`)
  }
  throw error
} finally {
  for (const runId of createdRunIds) {
    try {
      await api('DELETE', `/api/analysis/runs/${runId}`)
      console.log(`ok browser cleanup run ${runId}`)
    } catch (error) {
      console.warn(`unable to delete browser smoke run ${runId}: ${error.message}`)
    }
  }
  await browser.close()
}
