import { lazy, Suspense } from 'react'
import { Navigate, Routes, Route, useLocation } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { ToastContainer } from './components/common/ToastContainer'
import { ErrorBoundary } from './components/common/ErrorBoundary'
import { LoadingState } from './components/common/LoadingState'
import { RequireAuth } from './guards/RequireAuth'
import routeManifest from './routeManifest.json'

const DashboardPage = lazy(() => import('./components/dashboard/DashboardPage').then((module) => ({ default: module.DashboardPage })))
const GlobalMarketPage = lazy(() => import('./components/globalMarket/GlobalMarketPage').then((module) => ({ default: module.GlobalMarketPage })))
const NewTaskPage = lazy(() => import('./components/task/NewTaskPage').then((module) => ({ default: module.NewTaskPage })))
const LiveRunConsole = lazy(() => import('./components/live/LiveRunConsole').then((module) => ({ default: module.LiveRunConsole })))
const AgentDagPage = lazy(() => import('./components/dag/AgentDagPage').then((module) => ({ default: module.AgentDagPage })))
const AgentDebatePage = lazy(() => import('./components/debate/AgentDebatePage').then((module) => ({ default: module.AgentDebatePage })))
const PortfolioPage = lazy(() => import('./components/portfolio/PortfolioPage').then((module) => ({ default: module.PortfolioPage })))
const DataReliabilityPage = lazy(() => import('./components/dataReliability/DataReliabilityPage').then((module) => ({ default: module.DataReliabilityPage })))
const RunComparePage = lazy(() => import('./components/compare/RunComparePage').then((module) => ({ default: module.RunComparePage })))
const PermissionMatrixPage = lazy(() => import('./components/permission/PermissionMatrixPage').then((module) => ({ default: module.PermissionMatrixPage })))
const GuardrailHubPage = lazy(() => import('./components/guardrail/GuardrailHubPage').then((module) => ({ default: module.GuardrailHubPage })))
const QuantCorePage = lazy(() => import('./components/quantCore/QuantCorePage').then((module) => ({ default: module.QuantCorePage })))
const ExecutionPage = lazy(() => import('./components/execution/ExecutionPage').then((module) => ({ default: module.ExecutionPage })))
const AntiConclusionPage = lazy(() => import('./components/final/AntiConclusionPage').then((module) => ({ default: module.AntiConclusionPage })))
const SignalOpsPage = lazy(() => import('./components/signalops/SignalOpsPage').then((module) => ({ default: module.SignalOpsPage })))
const AuditLogPage = lazy(() => import('./components/audit/AuditLogPage').then((module) => ({ default: module.AuditLogPage })))
const FinalWriterPage = lazy(() => import('./components/final/FinalWriterPage').then((module) => ({ default: module.FinalWriterPage })))
const BackendStatusPage = lazy(() => import('./components/backend/BackendStatusPage').then((module) => ({ default: module.BackendStatusPage })))
const BackendTuningPage = lazy(() => import('./components/tuning/BackendTuningPage').then((module) => ({ default: module.BackendTuningPage })))
const ConfigVersionsPage = lazy(() => import('./components/config/ConfigVersionsPage').then((module) => ({ default: module.ConfigVersionsPage })))
const SettingsPage = lazy(() => import('./components/settings/SettingsPage').then((module) => ({ default: module.SettingsPage })))
const PluginRegistryPage = lazy(() => import('./components/plugins/PluginRegistryPage').then((module) => ({ default: module.PluginRegistryPage })))
const ResearchLabPage = lazy(() => import('./components/research/ResearchLabPage').then((module) => ({ default: module.ResearchLabPage })))

function PageLoading() {
  return <LoadingState label="加载中..." helper="正在加载页面模块。" />
}

function RedirectWithSearch({ to }: { to: string }) {
  const location = useLocation()
  return <Navigate to={`${to}${location.search}${location.hash}`} replace />
}

function App() {
  return (
    <>
      <ToastContainer />
      <ErrorBoundary>
        <AppShell>
          <Suspense fallback={<PageLoading />}>
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/global-market" element={<GlobalMarketPage />} />
              <Route path="/new-task" element={<NewTaskPage />} />
              <Route path="/live-run" element={<LiveRunConsole />} />
              <Route path="/dag" element={<AgentDagPage />} />
              <Route path="/debate" element={<AgentDebatePage />} />
              <Route path="/portfolio" element={<PortfolioPage />} />
              <Route path="/data-reliability" element={<DataReliabilityPage />} />
              <Route path="/run-compare" element={<RunComparePage />} />
              <Route path="/permission" element={<RequireAuth role="admin"><PermissionMatrixPage /></RequireAuth>} />
              <Route path="/guardrail-hub" element={<GuardrailHubPage />} />
              <Route path="/dvg-gate" element={<GuardrailHubPage />} />
              <Route path="/risk" element={<GuardrailHubPage />} />
              <Route path="/trade-micro" element={<GuardrailHubPage />} />
              <Route path="/quant-core" element={<QuantCorePage />} />
              <Route path="/execution" element={<ExecutionPage />} />
              <Route path="/anti-conclusion" element={<AntiConclusionPage />} />
              <Route path="/signalops" element={<SignalOpsPage />} />
              <Route path="/audit" element={<AuditLogPage />} />
              <Route path="/final" element={<FinalWriterPage />} />
              <Route path="/backend" element={<BackendStatusPage />} />
              <Route path="/research-lab/*" element={<ResearchLabPage />} />
              {routeManifest.redirects.map((redirect) => (
                <Route key={redirect.from} path={redirect.from} element={<RedirectWithSearch to={redirect.to} />} />
              ))}
              <Route path="/tuning" element={<RequireAuth role="admin"><BackendTuningPage /></RequireAuth>} />
              <Route path="/config-versions" element={<RequireAuth role="admin"><ConfigVersionsPage /></RequireAuth>} />
              <Route path="/settings" element={<RequireAuth role="admin"><SettingsPage /></RequireAuth>} />
              <Route path="/plugins" element={<RequireAuth role="admin"><PluginRegistryPage /></RequireAuth>} />
            </Routes>
          </Suspense>
        </AppShell>
      </ErrorBoundary>
    </>
  )
}

export default App
