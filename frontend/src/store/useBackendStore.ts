import create from 'zustand'
import { getBackendHealth, getStartupStatus } from '../api/analysisClient'
import type { BackendHealth, StartupStatus } from '../types'

interface BackendState {
  backendStatus?: BackendHealth
  startupStatus?: StartupStatus
  isBackendConnected: boolean
  isCoreReady: boolean
  connectionMode: 'MOCK' | 'BACKEND'
  setConnectionMode: (mode: 'MOCK' | 'BACKEND') => void
  checkBackendHealth: () => Promise<void>
}

let backendHealthCheckSequence = 0

export const useBackendStore = create<BackendState>((set) => ({
  isBackendConnected: false,
  isCoreReady: false,
  connectionMode: 'MOCK',
  setConnectionMode: (mode) => set({ connectionMode: mode }),
  checkBackendHealth: async () => {
    const sequence = ++backendHealthCheckSequence
    try {
      const health = await getBackendHealth()
      if (sequence !== backendHealthCheckSequence) return
      const isBackendConnected = health.status === 'ok'
      set({
        backendStatus: health,
        isBackendConnected,
        isCoreReady: false,
      })
      try {
        const startupStatus = await getStartupStatus({ timeoutMs: 3000 })
        if (sequence !== backendHealthCheckSequence) return
        set({ startupStatus, isCoreReady: isBackendConnected && startupStatus.coreReady })
      } catch {
        if (sequence !== backendHealthCheckSequence) return
        set({ startupStatus: undefined, isCoreReady: false })
      }
    } catch {
      if (sequence !== backendHealthCheckSequence) return
      set({ backendStatus: undefined, startupStatus: undefined, isBackendConnected: false, isCoreReady: false })
    }
  },
}))
