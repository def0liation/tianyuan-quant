export const LEGACY_AGENT_CANONICAL: Record<string, string> = {
  state_validation: 'orchestrator',
  data_fetch: 'data_reliability_engine',
  data_engine: 'data_reliability_engine',
  chip_kb: 'data_reliability_engine',
  memory_agent: 'data_reliability_engine',
  hallucination_guardrail: 'guardrail_hub',
  dvg_evidence_gate: 'guardrail_hub',
  dvg_gate: 'guardrail_hub',
  risk_firewall: 'guardrail_hub',
  atrade: 'guardrail_hub',
  trade_micro: 'guardrail_hub',
  flash_crash: 'guardrail_hub',
  portfolio: 'guardrail_hub',
  market_regime: 'quant_core',
  technical_kline_analyst: 'quant_core',
  market_technical_analyst: 'quant_core',
  bottom_research: 'quant_core',
  factor_slicing: 'quant_core',
  factor_engine: 'quant_core',
  calculation_authority: 'quant_core',
  qiam: 'quant_core',
  quant_engine: 'quant_core',
  scenario_engine: 'quant_core',
  simulation_agent: 'quant_core',
}

export function canonicalAgentFor(nodeId?: string | null) {
  const normalized = String(nodeId || '').trim()
  return normalized ? LEGACY_AGENT_CANONICAL[normalized] : undefined
}
