import create from 'zustand'
import { ConfigProfile, ConfigSchemaItem, ConfigDraft, PolicyCheckResult } from '../types'
import { getCurrentConfig, getConfigSchema, patchRuntimeConfig, validateConfigChange, createConfigDraft, applyConfigDraft, rollbackConfig, type ConfigChangePayload } from '../api/configClient'

interface TuningState {
  configProfile?: ConfigProfile
  configSchema: ConfigSchemaItem[]
  configDraft?: ConfigDraft
  policyCheckResult?: PolicyCheckResult
  configVersions: Array<{ version: number; created_at: string; created_by: string; change_summary: string; audit_id: string; status: string; rollback_available: boolean }>
  selectedConfigVersion?: number
  loadConfig: () => Promise<void>
  saveRuntimeConfig: (payload: ConfigChangePayload) => Promise<void>
  validateConfig: (payload: ConfigChangePayload) => Promise<void>
  submitConfigDraft: (payload: { changes: Record<string, any>; reason: string }) => Promise<void>
  applyConfigDraft: (draftId: string) => Promise<void>
  rollbackConfig: (payload: { target_version: number; reason: string }) => Promise<void>
}

export const useTuningStore = create<TuningState>((set) => ({
  configSchema: [],
  configVersions: [],
  loadConfig: async () => {
    const profile = await getCurrentConfig()
    const schema = await getConfigSchema()
    set({ configProfile: profile, configSchema: schema })
  },
  saveRuntimeConfig: async (payload) => {
    const response = await patchRuntimeConfig(payload)
    set((state) => ({ configProfile: state.configProfile ? { ...state.configProfile, version: response.version } : undefined }))
  },
  validateConfig: async (payload) => {
    const result = await validateConfigChange(payload)
    set({ policyCheckResult: result })
  },
  submitConfigDraft: async (payload) => {
    const draft = await createConfigDraft(payload)
    set({ configDraft: draft })
  },
  applyConfigDraft: async (draftId) => {
    const result = await applyConfigDraft(draftId)
    set((state) => (state.configProfile ? { configProfile: { ...state.configProfile, version: result.version } } : {}))
  },
  rollbackConfig: async (payload) => {
    const result = await rollbackConfig(payload)
    set((state) => (state.configProfile ? { configProfile: { ...state.configProfile, version: result.current_version } } : {}))
  },
}))
