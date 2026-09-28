import { ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { TopBar } from './TopBar'
import { useCurrentRunHydration } from '../../hooks/useCurrentRunHydration'

interface AppShellProps {
  children: ReactNode
}

export function AppShell({ children }: AppShellProps) {
  useCurrentRunHydration()

  return (
    <div className="material-app-shell">
      <div className="lg:flex lg:items-start">
        <Sidebar />
        <div className="min-w-0 flex-1">
          <TopBar />
          <main className="material-page-frame">
            {children}
          </main>
        </div>
      </div>
    </div>
  )
}
