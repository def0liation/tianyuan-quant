import { useMemo } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  Activity,
  BarChart3,
  Beaker,
  BookOpenCheck,
  BrainCircuit,
  ClipboardCheck,
  Cpu,
  Database,
  Gauge,
  GitBranch,
  LayoutDashboard,
  Layers,
  LineChart,
  ListChecks,
  Menu,
  Play,
  Plug,
  Router,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Target,
} from 'lucide-react'
import routeManifest from '../../routeManifest.json'

const GUARDRAIL_HUB_PATH = '/guardrail-hub'
const LEGACY_GUARDRAIL_PATHS = ['/dvg-gate', '/risk', '/trade-micro'] as const

const iconMap = {
  Activity,
  BarChart3,
  Beaker,
  BookOpenCheck,
  BrainCircuit,
  ClipboardCheck,
  Cpu,
  Database,
  Gauge,
  GitBranch,
  LayoutDashboard,
  Layers,
  LineChart,
  ListChecks,
  Play,
  Plug,
  Router,
  Settings,
  ShieldAlert,
  ShieldCheck,
  SlidersHorizontal,
  Target,
}

function getActivePath(pathname: string) {
  if (pathname.startsWith('/research-lab')) return '/research-lab'
  if (LEGACY_GUARDRAIL_PATHS.includes(pathname as (typeof LEGACY_GUARDRAIL_PATHS)[number])) return GUARDRAIL_HUB_PATH
  const redirect = routeManifest.redirects.find((item) => item.from === pathname)
  if (redirect?.to.startsWith('/research-lab')) return '/research-lab'
  return redirect?.to ?? pathname
}

function getIcon(name: string) {
  return iconMap[name as keyof typeof iconMap] ?? LayoutDashboard
}

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const activePath = getActivePath(location.pathname)
  const items = useMemo(() => routeManifest.navGroups.flatMap((group) => group.items), [])
  const guardrailHubTitle = '统一护栏：DVG / 风险熔断 / 交易微观'

  return (
    <>
      <div className="border-b border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface)] px-4 py-3 lg:hidden">
        <div className="mb-3 flex items-center gap-2 text-[var(--md-sys-color-on-surface)]">
          <Menu size={20} />
          <div className="font-semibold">天元量化 Agent</div>
        </div>
        <select
          value={activePath}
          onChange={(event) => navigate(event.target.value)}
          className="material-select w-full px-3 py-2 text-sm"
        >
          {items.map((item) => (
            <option key={item.path} value={item.path}>
              {item.label}
            </option>
          ))}
        </select>
      </div>

      <aside className="hidden h-screen w-[68px] shrink-0 border-r border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface)] px-2 py-3 lg:sticky lg:top-0 lg:flex lg:flex-col lg:items-center">
        <div className="mb-4 grid h-10 w-10 place-items-center rounded-[var(--institution-radius-md)] bg-[var(--md-sys-color-primary)] text-xs font-black text-[var(--md-sys-color-on-primary)]">
          TY
        </div>

        <nav className="min-h-0 flex-1 space-y-5 overflow-y-auto">
          {routeManifest.navGroups.map((group) => (
            <div key={group.title} className="space-y-1.5" aria-label={group.title}>
              {group.items.map((item) => {
                const Icon = getIcon(item.icon)
                const isResearchActive = activePath === '/research-lab' && item.path === '/research-lab'
                const isGuardrailHub = item.path === GUARDRAIL_HUB_PATH
                const itemTitle = isGuardrailHub ? guardrailHubTitle : item.label
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    title={itemTitle}
                    aria-label={itemTitle}
                    data-testid={isGuardrailHub ? 'sidebar-guardrail-hub' : undefined}
                    className={({ isActive }) =>
                      `group relative grid h-11 w-11 place-items-center rounded-[var(--institution-radius-md)] border text-[var(--md-sys-color-on-surface-variant)] transition ${
                        isActive || isResearchActive || activePath === item.path
                          ? 'border-[var(--md-sys-color-primary)] bg-[var(--md-sys-color-primary-container)] text-[var(--md-sys-color-on-primary-container)]'
                          : 'border-transparent hover:border-[var(--md-sys-color-outline-variant)] hover:bg-[var(--md-sys-color-surface-container-low)] hover:text-[var(--md-sys-color-on-surface)]'
                      }`
                    }
                  >
                    {activePath === item.path ? (
                      <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-[var(--md-sys-color-primary)]" />
                    ) : null}
                    <Icon size={18} className="shrink-0" />
                    {isGuardrailHub ? (
                      <span className="absolute bottom-1.5 flex items-center gap-0.5" aria-hidden="true">
                        <span className="h-1 w-1 rounded-full bg-[var(--institution-data-accent)]" />
                        <span className="h-1 w-1 rounded-full bg-[var(--md-sys-color-error)]" />
                        <span className="h-1 w-1 rounded-full bg-[var(--md-sys-color-warning)]" />
                      </span>
                    ) : null}
                    <span className="sr-only">{item.label}</span>
                  </NavLink>
                )
              })}
            </div>
          ))}
        </nav>
      </aside>
    </>
  )
}
