import { AnalysisRun, AgentResult, AgentNode, DagEvent, AgentDebateTurn, TokenUsageSummary } from '../types'

const STANDARD_DAG_ORDER = [
  'orchestrator', 'data_reliability_engine', 'guardrail_hub', 'quant_core',
  'execution', 'anti_conclusion', 'signalops', 'final_writer',
]

const AGENT_NAMES: Record<string, string> = {
  orchestrator: 'Orchestrator',
  data_reliability_engine: '数据可靠性引擎',
  guardrail_hub: 'Guardrail Hub',
  dvg_gate: 'DVG Gate',
  risk_firewall: 'Risk Firewall',
  trade_micro: 'Trade Micro',
  quant_core: '量化核心',
  market_technical_analyst: 'Market Technical Analyst',
  market_regime: 'Market Regime',
  bottom_research: 'MFE/MAE Path Research',
  quant_engine: 'Quant Engine',
  scenario_engine: 'Scenario Engine',
  execution: 'Execution',
  anti_conclusion: 'Anti-Conclusion',
  signalops: 'SignalOps',
  final_writer: 'Final Writer',
}

function buildAgentResults(runId: string, overrides: Record<string, Partial<AgentResult>> = {}): AgentResult[] {
  return STANDARD_DAG_ORDER.map((node) => {
    const base: AgentResult = {
      node,
      name: AGENT_NAMES[node] || node,
      status: 'PASS',
      allowed_actions: [],
      blocked_actions: [],
      hard_stop: false,
      final_decision_cap: null,
      confidence: 'HIGH',
      reasons: [`${AGENT_NAMES[node] || node} 正常完成`],
      missing_data: [],
      warnings: [],
      data: {},
      audit_id: `AUD_${runId}_${node}`,
      elapsed_ms: 120 + Math.floor(Math.random() * 300),
    }
    if (overrides[node]) {
      return { ...base, ...overrides[node] }
    }
    return base
  })
}

function buildNodes(agentResults: AgentResult[]): AgentNode[] {
  return agentResults.map((ar) => {
    const isSkipped = ar.status === 'SKIPPED'
    const isBlocked = ar.status === 'BLOCK' || ar.hard_stop
    const evidenceStrength = isSkipped || isBlocked || ar.missing_data.length > 0 || ar.warnings.length > 0 ? 'LOW' : 'MEDIUM'
    return {
      id: ar.node,
      name: ar.name,
      status: (ar.status === 'BLOCK' ? 'BLOCK_BUY' : ar.status === 'ERROR' ? 'FAIL' : ar.status) as AgentNode['status'],
      isRunning: false,
      isSkipped,
      isBlocked,
      duration: ar.elapsed_ms,
      auditId: ar.audit_id,
      inputSummary: ar.reasons[0] || '',
      outputSummary: ar.warnings[0] || ar.reasons[0] || '',
      missingData: ar.missing_data,
      downgradeReasons: ar.warnings,
      blockedPaths: ar.blocked_actions,
      allowedNextActions: ar.allowed_actions,
      evidenceUsage: 'simulation_only',
      evidenceStrength,
      simulationOnly: true,
      isRealTrade: false,
      strongConclusionAllowed: false,
    }
  })
}

function buildDagEvents(runId: string, agentResults: AgentResult[]): DagEvent[] {
  return agentResults.map((ar, index) => ({
    event_type: 'NODE_FINISHED' as const,
    run_id: runId,
    node: ar.node,
    order: index + 1,
    status: ar.status,
    message: ar.reasons[0] || `${ar.name} 完成`,
    elapsed_ms: ar.elapsed_ms,
    audit_id: ar.audit_id,
    timestamp: new Date(Date.now() - (agentResults.length - index) * 2000).toISOString(),
  }))
}

interface DebateNarrative {
  claim: string
  evidence: string[]
  counterpoints: string[]
  decision_impact: string
}

const BASE_DEBATE_NARRATIVES: Record<string, DebateNarrative> = {
  orchestrator: {
    claim: '经过分析用户输入和运行模式，我已编排本次"持仓复核"标准模式分析链。路由、输入校验、tool budget、kill switch 规则已就位。12 个 Agent 将按 DAG 顺序依次执行，每个关键节点之间设有门禁检查点，任何 Guardrail Agent 触发 hard_stop 时将立即截断下游正向链路。',
    evidence: ['用户提供标的代码 603663 和持仓比例 12%，任务类型自动识别为持仓复核', '运行模式确认为 STANDARD_MODE，已配置全部核心 Agent', 'kill_switch 规则已就位：任何 Guardrail 触发 hard_stop 时自动截断买入链路'],
    counterpoints: ['若任何 Guardrail Agent 触发 hard_stop，后续买入链路将被自动跳过', '不得让 Quant Engine raw favorable 绕过 DVG/Risk 直接进入最终报告', 'Final Writer 必须忠实转述上游判断，不能重新推理或引入新论据'],
    decision_impact: '编排计划已生效，12 个 Agent 按序执行，门禁截断规则明确。',
  },
  data_reliability_engine: {
    claim: '我已从多个数据源拉取标的 603663 的行情、财务、资金流、公告和筹码数据。整体数据覆盖度约 72%，其中行情数据实时可用，但 Level-2 逐笔成交和盘口深度缺失，筹码分布仅有第三方估算值（置信度 82%）。近 30 日无重大利空公告，无历史分析记录（首轮分析）。',
    evidence: ['行情数据：最新价、涨跌幅、成交量均已成功获取，时间戳有效', '财务数据：最近一期季报数据完整，ROE、PE、PB 等关键指标可读取', '筹码分布来自第三方估算模型，置信度约 82%', '公告数据：近 30 日无重大利空公告'],
    counterpoints: ['Level-2 逐笔成交不可用 — 无法判断封单强弱和盘口真实性', '筹码分布为第三方估算，不能作为主力控盘判断的依据', '无历史分析记录，缺少趋势对比基准', '行业估值对比数据缺失，无资金流数据无法判断主力动向'],
    decision_impact: '数据已整理完毕并提交 DVG Gate 进行可靠性审查，缺失项已标记。',
  },
  guardrail_hub: {
    claim: '我已将 DVG、Risk Firewall、Kill Switch 和 Trade Micro 合并为本轮唯一活跃护栏判断。数据可靠性为 MEDIUM，Level-2 与盘口深度缺失，未触发合规硬红线，但执行权限被限制为 REVIEW_ONLY，买入、加仓和追涨路径被阻断。',
    evidence: ['DVG：数据可靠性 MEDIUM，幻觉风险评分 38', 'Risk：未触发 ST、退市、财务造假或监管处罚等硬红线', 'Trade Micro：Level-2 和盘口深度不可用，单票仓位接近上限', 'Kill Switch：SOFT，final writer 保守输出'],
    counterpoints: ['旧 dvg_gate / risk_firewall / trade_micro 只能作为兼容字段读取，不再是活跃 DAG 节点', '缺少 Level-2 不能判断封单强弱，缺少盘口深度不能推导执行确定性', 'Quant Core 只能基于护栏上限做折扣，不能恢复被阻断的买入路径'],
    decision_impact: '护栏中枢输出 REVIEW_ONLY，后续仅允许 WAIT、HOLD、REVIEW_ONLY 和 SIGNAL_ONLY。',
  },
  dvg_gate: {
    claim: '经过对数据可靠性引擎提交的数据逐项审查，我评定本轮数据可靠性为中等水平。确认数据（C级）占比约 72%，推断数据（I级）17%，未知数据（U级）11%。幻觉风险评分 38 分，已触发 REVIEW_ONLY 限制。综合评估后，下游权限限制为审查级别，Quant Engine 必须在应用折扣因子后运行，执行路径仅保留观察和审查行为。',
    evidence: ['确认数据（C级）：行情基础数据、财务季报、近 30 日公告', '推断数据（I级）：筹码分布来自第三方估算模型', '未知数据（U级）：Level-2 逐笔成交、行业可比估值、主力资金流向'],
    counterpoints: ['缺少 Level-2 意味着无法验证盘口挂单真实性，追板策略无依据', '缺乏资金流数据无法判断主力动向，存在信息不对称风险', '幻觉风险评分 38 分，已触发 REVIEW_ONLY 限制', '无 Level-2 不得判断封单强弱，无 moneyflow 不得判断主力控盘'],
    decision_impact: '下游权限限制为 REVIEW_ONLY，Quant Engine 需折扣后运行，禁止买入和加仓。',
  },
  risk_firewall: {
    claim: '本轮审查未触发合规红线和个股硬性风险，也未检测到闪崩真空或流动性陷阱信号。标的 603663 不存在 ST、退市、财务造假或监管处罚等重大风险。波动率指数 52 处于常态区间，流动性指数 58 正常。但用户未提供完整持仓约束（最大回撤容忍度、计划周期），建议后续采用保守路径。',
    evidence: ['合规审查通过：未触发行业监管限仓、内幕交易等红线', '个股硬风险检查通过：无 ST/退市/财务造假/监管处罚', '闪崩检测：波动率正常，未出现真空或极端条件', '系统性风险：波动率 52 处于 30-70 的常态区间'],
    counterpoints: ['用户未提供最大回撤容忍度，按保守原则假设为 8%', '用户未提供计划持仓周期，无法精确评估时间维度风险敞口', '虽然未触发硬性风险，但用户约束不完整限制了激进操作空间'],
    decision_impact: '合规和硬风险通过，闪崩检测无异常，但由于用户约束不完整，后续应采用保守路径。',
  },
  trade_micro: {
    claim: '我检查了标的 603663 的 A 股微观结构和持仓组合约束。T+1 正常，未处于涨跌停，可卖底仓存在。但 Level-2 和盘口深度不可用，成交为有条件可达，存在滑点和流动性不确定性。持仓组合方面：当前单票仓位 12%，距离 15% 上限仅剩 3% 空间，行业集中度偏高（金融板块 50%），不建议继续加仓。',
    evidence: ['T+1 状态正常，价格限制正常，可卖底仓存在', '持仓组合：单票 12%/15%，行业敞口金融 50%，集中度偏高', '主题集中度 28%，同质风险因子集中度 17%'],
    counterpoints: ['Level-2 不可用：无法判断封单强弱和盘口挂单真实性', '加仓空间仅剩 3%，容错率极低，任何小幅下行就可能触及回撤上限', '即使其他 Agent 给出正向信号，也不应突破仓位上限和集中度约束'],
    decision_impact: '成交为有条件可达，禁止加仓，维持当前仓位观察，关注行业集中度风险。',
  },
  market_regime: {
    claim: '当前市场整体处于中性偏震荡格局。市场情绪中性，机构和散户情绪平稳。板块轮动集中在金融和科技领域，风格偏向价值。波动率 52 处于中位，宏观层面 CPI 2.8%、GDP 4.5%，政策环境相对稳定。板块轮动监测：金融板块维持强势，科技板块资金持续流入，风格延续价值偏好。',
    evidence: ['市场情绪中性，波动率 52 处于 30-70 常态区间', '机构资金活跃度中等，无明显单边净流入流出', '板块轮动方向：金融和科技板块资金流入居前，风格偏价值', '宏观指标：CPI 2.8%、GDP 4.5%，政策环境稳定'],
    counterpoints: ['震荡市环境下单边行情确定性低，不适合追涨或趋势跟随', '若宏观政策超预期变动（加息、监管收紧），可能打破当前平衡', '行业估值数据缺失，难以判断金融和科技板块是否处于高估区间'],
    decision_impact: '整体环境适合审慎操作，不建议激进加仓或追涨。',
  },
  quant_engine: {
    claim: '我从因子切割、因子稳定性、计算校验和量化适宜性四个维度对标的进行了全面量化分析。因子模型识别出价值(0.30)、动量(0.25)、流动性(0.20)为主要驱动因子，稳定性 0.72。计算工具可用性检查通过。QIAM 原始买入适宜性为"有利"（FAVORABLE），但需要应用 DVG 折扣：Level-2 缺失 ×0.60，盘口深度不足 ×0.70，综合折扣因子 0.52。折扣后最终买入适宜性降为"中性"（NEUTRAL），不构成买入信号。',
    evidence: ['因子分析：价值(0.30)、动量(0.25)、流动性(0.20)为主驱动，稳定性 0.72', '计算校验：计算工具可用，禁止 LLM 心算推测', 'QIAM 原始评分：FAVORABLE', 'Level-2 缺失折扣 ×0.60，盘口深度折扣 ×0.70，综合 0.52'],
    counterpoints: ['QIAM raw favorable 不等于买入信号，折扣后的 NEUTRAL 才是可引用结论', 'Quant Engine 不能提高仓位上限，不能绕过 DVG/Risk/Trade Micro 直接发号施令', '换手率和风格轮动数据缺失，因子暴露估计可能偏差', '因子稳定性 0.72 意味着 28% 概率因子结构会变化'],
    decision_impact: '最终买入适宜性为"中性"，不形成买入信号，下游环节应以中性态度处理。',
  },
  scenario_engine: {
    claim: '基于上游数据和门禁结果，我为标的设定了三个情景并评估了赔率质量。乐观情景：补齐 Level-2 和盘口数据 + 行业估值回归合理 → 正面催化剂。基准情景：维持当前震荡格局，标的跟随大盘波动。悲观情景：数据缺失持续 + 资金流出 + 情绪转冷 → 回调压力。已运行蒙特卡洛模拟：基准情景概率最高(约 60%)，乐观约 22%，悲观约 18%。',
    evidence: ['乐观情景前提：Level-2 补齐 + 行业估值合理 + 资金面改善', '基准情景前提：震荡延续，标的跟随大盘波动', '悲观情景前提：数据持续缺失 + 资金流出 + 情绪转冷', '蒙特卡洛模拟：基准情景 60% 概率，乐观 22%，悲观 18%'],
    counterpoints: ['情景分析为定性参考框架，不能作为交易决策的直接依据', '蒙特卡洛模拟依赖参数假设，实际分布可能与假设有偏差', '乐观情景需要三个条件同时满足，实际实现概率通常低于直觉判断'],
    decision_impact: '三情景框架 + 蒙特卡洛模拟已建立，为执行层提供了不确定性参考。',
  },
  execution: {
    claim: '综合上游所有门禁结果，当前执行路径受到显著限制。DVG Gate 将权限限制为 REVIEW_ONLY，Quant Engine 最终买入适宜性为 NEUTRAL，Trade Micro 明确禁止加仓。因此只开放 WAIT 和 REVIEW_ONLY 两个执行动作，禁止买入候选、加仓候选和自动执行计划。所有动作需人工复核确认。',
    evidence: ['DVG Gate 权限：REVIEW_ONLY', 'Quant Engine 适宜性：NEUTRAL', 'Trade Micro 加仓允许：false', '上游软性限制已大幅收窄执行空间'],
    counterpoints: ['禁止生成买入执行计划、加仓指令、追涨操作', '禁止自动下单、市价追涨、流动性不足时执行大额订单', '所有交易相关动作必须经过人工确认，mock 模式不生成真实交易计划'],
    decision_impact: '执行路径限制为仅观察和人工复核，不生成买入或加仓执行计划。',
  },
  anti_conclusion: {
    claim: '我审查了候选的最终输出结论，逐条比对上游门禁结果。确认没有"后门推理"或"结论漂移"问题。Final Writer 输出与上游门禁一致，未在 Risk 阻断后寻找买入理由，未使用 Quant Engine raw favorable 代替折扣后结果。若检测到任何对门禁的语义绕过，将触发 REWRITE_REQUIRED 或 BLOCK_OUTPUT。',
    evidence: ['已逐项核对 DVG/Risk/Trade Micro/Quant Engine 的门禁结果与 Final Writer 输出', '未发现硬风险阻断后继续输出买入/加仓/追涨建议', 'Final Writer 使用的买入适宜性为 NEUTRAL（折扣后）'],
    counterpoints: ['确认 raw favorable 未被泄露到最终报告中', '若检测到语义绕过上游门禁，将立即触发 REWRITE_REQUIRED', '所有与门禁状态不一致的输出将被标记为 BLOCK_OUTPUT'],
    decision_impact: '结论一致性检查通过，未触发重写或阻止输出。',
  },
  signalops: {
    claim: '我将当前分析结果映射为观察信号。由于 DVG Gate 未通过审查级别，Quant Engine 适宜性为中性，信号状态停留在 WATCH 阶段，无法进入 QUALIFIED 或 TRADE_PLAN。已记录触发条件、失效条件和审查周期。纸面测试已启动：观察期 14 天，入场假设"行情不破支撑 + 政策面稳定"，失效条件"跌破 10% 止损或流动性大幅收缩"。当前仅用于信息跟踪，不创建交易计划。',
    evidence: ['DVG Gate 未通过 → 信号无法进入 QUALIFIED', 'Quant Engine 适宜性 NEUTRAL → 不满足买入信号条件', 'Risk 通过，Trade Micro 禁止加仓', '纸面测试：14 天观察期，入场条件已设定'],
    counterpoints: ['信号被阻塞在 WATCH 阶段，不会创建交易计划', '纸面测试仅在沙盒环境中运行，不触发任何实际交易', '若后续数据补齐且门禁通过，信号可自动升级'],
    decision_impact: '创建观察信号 + 纸面测试沙盒，不创建交易计划，待数据条件改善后评估。',
  },
  final_writer: {
    claim: '综合以上全部 Agent 的分析结果，给出本轮最终结论。标的 603663 数据可靠性中等，缺少 Level-2 和盘口深度等关键数据。门禁系统将结论限制为保守输出。DVG Gate REVIEW_ONLY，Quant Engine NEUTRAL，Trade Micro 禁止加仓，Execution 仅保留 WAIT/REVIEW_ONLY。Meta-review 一致性检查通过，状态快照已序列化。综合建议：保持观察，不建议买入或加仓。待数据补齐后重新评估。全程未进行自动下单，所有动作需人工确认。',
    evidence: ['DVG Gate：可靠性 MEDIUM，REVIEW_ONLY', 'Quant Engine：FAVORABLE→NEUTRAL（折扣后）', 'Risk Firewall：合规和硬风险通过', 'Trade Micro：有条件可达 + 禁止加仓', 'Meta-review：一致性检查通过，无未解决的错误账本条目'],
    counterpoints: ['最终结论不能超出上游门禁设定的决策上限', '不能在最终报告中重新推理或引入上游未讨论的新论据', '必须明确告知用户数据缺失和门禁限制，不得以模糊措辞掩盖风险'],
    decision_impact: '给出保守结论，明确提示数据不足和门禁限制，建议保持观察等待数据补齐。',
  },
}

function buildDebateTurns(agentResults: AgentResult[]): AgentDebateTurn[] {
  const stanceMap: Record<string, AgentDebateTurn['stance']> = {
    PASS: 'support',
    WARN: 'challenge',
    REVIEW_ONLY: 'challenge',
    BLOCK: 'block',
    ERROR: 'block',
    SKIPPED: 'observe',
  }
  return agentResults.map((ar, index) => {
    const narrative = BASE_DEBATE_NARRATIVES[ar.node]
    const stance = stanceMap[ar.status] || 'observe'

    if (ar.status === 'SKIPPED') {
      return {
        order: index + 1,
        node: ar.node,
        name: ar.name,
        stance: 'observe' as const,
        claim: ar.skipped_reason
          ? `本轮该 Agent 因上游触发阻断条件而未执行。具体原因：${ar.skipped_reason}。这意味着该环节的检查职责未能履行，下游环节应注意这一缺口可能带来的风险。`
          : '本轮该 Agent 因上游门禁触发被跳过，未参与本次辩论。其职责范围内的检查未能执行，下游 Agent 需要关注这一缺口。',
        evidence: ['因上游阻断条件满足，本轮该 Agent 被编排器跳过'],
        counterpoints: ['该 Agent 被跳过意味着其职责范围内的检查未能执行，可能留下分析盲区', '若后续重新运行，建议先补齐触发阻断的条件，再重新启用该环节'],
        decision_impact: '该 Agent 被跳过，没有直接影响本轮决策，但其职责范围内的检查缺失需要在下游注意。',
        status: ar.status as AgentDebateTurn['status'],
        confidence: 'UNKNOWN' as const,
        token_total: 0,
        latency_ms: ar.elapsed_ms,
        audit_id: ar.audit_id,
      }
    }

    const claim = narrative?.claim
      || ar.reasons[0]
      || `${AGENT_NAMES[ar.node] || ar.node} 已完成分析，未产生明确的辩论主张。`
    const evidence = narrative?.evidence?.length
      ? narrative.evidence
      : ar.missing_data.length
        ? [`缺失数据：${ar.missing_data.join('、')}，这些数据的缺失影响判断的完整性。`]
        : [`${AGENT_NAMES[ar.node] || ar.node} 在分析中未发现缺失关键数据。`]
    const counterpoints = narrative?.counterpoints?.length
      ? narrative.counterpoints
      : ar.warnings.length
        ? ar.warnings
        : ['当前环节未产生额外反驳意见']
    const decisionImpact = narrative?.decision_impact
      || (ar.hard_stop
        ? '该 Agent 对后续正向交易路径形成约束或阻断，下游买入相关环节将受到影响。'
        : '该 Agent 允许流程在上游约束内继续推进。')

    return {
      order: index + 1,
      node: ar.node,
      name: ar.name,
      stance,
      claim,
      evidence,
      counterpoints,
      decision_impact: decisionImpact,
      status: ar.status as AgentDebateTurn['status'],
      confidence: ar.confidence,
      token_total: 0,
      latency_ms: ar.elapsed_ms,
      audit_id: ar.audit_id,
    }
  })
}

function buildTokenUsage(agentResults: AgentResult[]): TokenUsageSummary {
  const rows = agentResults.map((ar) => {
    const promptTokens = 200 + Math.floor(Math.random() * 800)
    const completionTokens = 100 + Math.floor(Math.random() * 400)
    return {
      node: ar.node,
      name: ar.name,
      status: ar.status,
      provider: 'deepseek',
      model: 'deepseek-v4-flash',
      profile_id: 'default_llm',
      prompt_tokens: promptTokens,
      completion_tokens: completionTokens,
      total_tokens: promptTokens + completionTokens,
      latency_ms: ar.elapsed_ms,
      finish_reason: 'stop',
      error: '',
      audit_id: ar.audit_id,
    }
  })
  const totals = rows.reduce(
    (acc, row) => ({
      prompt_tokens: acc.prompt_tokens + row.prompt_tokens,
      completion_tokens: acc.completion_tokens + row.completion_tokens,
      total_tokens: acc.total_tokens + row.total_tokens,
      latency_ms: acc.latency_ms + row.latency_ms,
    }),
    { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, latency_ms: 0 }
  )
  return {
    rows,
    totals,
    top_agent: rows.length > 0 ? rows.reduce((a, b) => (a.total_tokens > b.total_tokens ? a : b)) : null,
    metering_status: 'AVAILABLE',
    note: 'Mock 模式 - Token 用量为占位估算值',
  }
}

function buildDefaultAgentOverrides(): Record<string, Partial<AgentResult>> {
  return {
    guardrail_hub: {
      status: 'WARN',
      confidence: 'MEDIUM',
      reasons: ['Guardrail Hub 汇总 DVG/Risk/Trade Micro 后限制为 REVIEW_ONLY'],
      missing_data: ['Level-2 成交量', '行业估值数据'],
      warnings: ['DVG REVIEW_ONLY 限制后续权限', '旧护栏节点仅作为兼容字段读取'],
      final_decision_cap: 'REVIEW_ONLY',
    },
    quant_core: {
      status: 'WARN',
      confidence: 'MEDIUM',
      reasons: ['raw FAVORABLE 已折扣至 NEUTRAL，因子数据部分缺失'],
      missing_data: ['Level-2', '盘口深度', '换手率'],
      warnings: ['缺少 Level-2 折扣 *0.60', '盘口深度不足折扣 *0.70'],
      allowed_actions: ['REVIEW_ONLY'],
    },
    execution: {
      status: 'REVIEW_ONLY',
      confidence: 'MEDIUM',
      reasons: ['上游门禁限制执行路径'],
      allowed_actions: ['WAIT', 'REVIEW_ONLY'],
      blocked_actions: ['BUY_CANDIDATE', 'ADD_CANDIDATE', 'EXECUTION_BUY'],
      warnings: ['mock 模式不生成真实交易计划'],
    },
    signalops: {
      status: 'WARN',
      confidence: 'MEDIUM',
      reasons: ['DVG 未通过，限制 SIGNAL_QUALIFIED'],
      warnings: ['DVG REVIEW_ONLY 阻断 QUALIFIED'],
      blocked_actions: ['QUALIFIED'],
    },
    final_writer: {
      status: 'PASS',
      confidence: 'HIGH',
      reasons: ['根据上游门禁结果保守输出，meta-review 一致性通过'],
      final_decision_cap: 'UPSTREAM_ONLY',
    },
  }
}

function createBaseRun(id: string, overrides: Record<string, Partial<AgentResult>> = {}): AnalysisRun {
  const runId = `RUN_MOCK_${id}`
  const baseOverrides = buildDefaultAgentOverrides()
  const merged: Record<string, Partial<AgentResult>> = {}
  for (const key of STANDARD_DAG_ORDER) {
    merged[key] = { ...baseOverrides[key], ...overrides[key] }
  }
  const agentResults = buildAgentResults(runId, merged)
  const nodes = buildNodes(agentResults)
  const dagEvents = buildDagEvents(runId, agentResults)
  const debateTurns = buildDebateTurns(agentResults)
  const tokenUsage = buildTokenUsage(agentResults)

  const sections = [
    {
      title: '当前结论',
      content: '当前研究建议保持观察，等待更完整的 Level-2 和盘口深度信息。',
      riskLevel: 'MEDIUM' as const,
      requiresConfirmation: true,
    },
    {
      title: '数据与风险说明',
      content: 'QIAM raw FAVORABLE 已折扣至 NEUTRAL；DVG REVIEW_ONLY 与 Kill Switch SOFT 共同限制买卖候选。',
      riskLevel: 'MEDIUM' as const,
      requiresConfirmation: true,
    },
  ]

  return {
    runId,
    runMode: 'STANDARD_MODE',
    environment: 'API_ORCHESTRATED',
    stockCode: '603663',
    stockName: '柯利达',
    taskType: '持仓复核',
    userPosition: { currentPositionRatio: 0.12, costPrice: 18.5, sellableBottomWarehouse: true, plannedPeriod: 30, maxAcceptableDrawdown: 0.08 },
    nodes,
    guardrailHub: {
      status: 'WARN',
      finalDecisionCap: 'WAIT',
      killSwitch: { active: true, level: 'SOFT', triggerNode: 'guardrail_hub', triggerRule: 'data_reliability <= MEDIUM', blockedPaths: ['BUY_CANDIDATE', 'ADD_CANDIDATE', 'CHASE'], allowedPaths: ['WAIT', 'REVIEW_ONLY', 'HOLD', 'SIGNAL_ONLY'], finalWriterMode: 'CONSERVATIVE', auditId: 'AUD_KS_001' },
      dvg: { status: 'WARN', dataReliability: 'MEDIUM', confirmedRatio: 0.72, inferredRatio: 0.17, unknownRatio: 0.11, coreUnknownCount: 3, freshnessStatus: 'MODERATE', sourceIntegrity: 'PARTIAL', hallucinationRiskScore: 38, hallucinationRiskLevel: 'MEDIUM', criticalMissingData: ['Level-2 成交量', '行业估值数据'], dataConflicts: ['财务报表与市场预期不一致'], allowedOutputLevel: 'REVIEW_ONLY', qiamPermission: 'ALLOW_WITH_DISCOUNT', scenarioPermission: 'ALLOW', executionPermission: 'REVIEW_ONLY', finalDecisionCap: 'WAIT', hardStop: false },
      risk: { complianceRedLines: [], f0IndividualHardRisks: [], f1ExtremeChipCollapse: [], f4ThreePartyFundResonanceOutflow: [], l0AbsoluteLiquidityRedLine: [], m0SystemicRisk: [], aStockMicrostructureUnexecutable: [], qiamBlockBuy: [], portfolioRiskOverLimit: [], executionUnreachable: [] },
      atrade: { t1Status: true, sellableBottomWarehouse: true, priceLimitStatus: 'NORMAL', stDelistingRisk: false, level2Available: false, depthAvailable: false, executionReachability: 'REACHABLE', liquidityRisk: 'MEDIUM', flashCrashVacuumStatus: false, slippageLimit: 0.005, participationLimit: 0.1 },
      gateResults: { dvg: 'REVIEW_ONLY', risk: 'PASS', tradeMicro: 'WARN' },
      warnings: ['Level-2 和盘口深度缺失，旧护栏节点仅作为兼容字段保留'],
      auditId: 'AUD_GUARDRAIL_001',
    },
    dvg: { status: 'WARN', dataReliability: 'MEDIUM', confirmedRatio: 0.72, inferredRatio: 0.17, unknownRatio: 0.11, coreUnknownCount: 3, freshnessStatus: 'MODERATE', sourceIntegrity: 'PARTIAL', hallucinationRiskScore: 38, hallucinationRiskLevel: 'MEDIUM', criticalMissingData: ['Level-2 成交量', '行业估值数据'], dataConflicts: ['财务报表与市场预期不一致'], allowedOutputLevel: 'REVIEW_ONLY', qiamPermission: 'ALLOW_WITH_DISCOUNT', scenarioPermission: 'ALLOW', executionPermission: 'REVIEW_ONLY', finalDecisionCap: 'WAIT', hardStop: false },
    risk: { complianceRedLines: [], f0IndividualHardRisks: [], f1ExtremeChipCollapse: [], f4ThreePartyFundResonanceOutflow: [], l0AbsoluteLiquidityRedLine: [], m0SystemicRisk: [], aStockMicrostructureUnexecutable: [], qiamBlockBuy: [], portfolioRiskOverLimit: [], executionUnreachable: [] },
    atrade: { t1Status: true, sellableBottomWarehouse: true, priceLimitStatus: 'NORMAL', stDelistingRisk: false, level2Available: false, depthAvailable: false, executionReachability: 'REACHABLE', liquidityRisk: 'MEDIUM', flashCrashVacuumStatus: false, slippageLimit: 0.005, participationLimit: 0.1 },
    market: { marketSentiment: 'NEUTRAL', volatilityIndex: 52, liquidityIndex: 58, institutionalActivity: 'MEDIUM', retailSentiment: 'NEUTRAL', sectorRotation: ['金融', '科技'], macroIndicators: { cpi: 2.8, gdp: 4.5, policyRate: 3.65 } },
    factorSlicing: { mode: 'AUTO', factors: [{ name: 'Value', weight: 0.3, contribution: 0.12, confidence: 0.8 }, { name: 'Momentum', weight: 0.25, contribution: 0.09, confidence: 0.7 }, { name: 'Liquidity', weight: 0.2, contribution: 0.06, confidence: 0.75 }], factorClusters: ['基本面', '情绪'], regimeClassification: '震荡', factorStability: 0.72, missingFactorData: ['换手率', '风格轮动'] },
    chipKb: { currentPool: 'B', suggestedPool: 'D', migrationDirection: 'DOWNGRADE', hitRiskPatches: ['F-4', 'F-0'], hitPositivePatches: ['H-2', 'D-5'], dataConfidenceLevel: 0.82, coreMissingData: ['主力流入数据'], signalOpsMappingStatus: 'MAPPED', triggerConditions: ['资金面回撤', '消息面不确定'], invalidationConditions: ['行业减速'], reviewCycle: 30 },
    qiam: { calculationMode: 'STANDARD', dvgPermission: true, rawBuySuitability: 'FAVORABLE', discountFactor: 0.52, finalBuySuitability: 'NEUTRAL', probabilityBandUp: 0.3, probabilityBandSideways: 0.4, probabilityBandDown: 0.3, expectedPayoffQuality: 0.65, regimeFit: 0.7, momentumQuality: 0.55, volatilityCondition: 0.6, liquidityAdjustedSignal: 0.58, modelConfidenceRaw: 0.75, modelConfidenceFinal: 0.62, overfitRisk: 0.2, distributionDrift: 0.15, decisionEffect: 0.8, missingData: ['Level-2', '盘口深度'], downgradeReasons: ['缺少 Level-2', '样本外验证不足'] },
    portfolio: { currentTotalPosition: 0.12, singleStockPosition: 0.12, industryExposure: { 银行: 0.35, 证券: 0.15, 科技: 0.1 }, styleExposure: { 价值: 0.5, 成长: 0.2 }, themeConcentration: 0.28, sameRiskFactorConcentration: 0.17, maxDrawdownConstraint: 0.08, singleStockPositionCap: 0.15, allowAddPosition: false, allowHeavyPosition: false, restrictionReasons: ['已有单票仓位接近上限', '风险偏好保守'] },
    execution: { allowedActions: ['WAIT', 'REVIEW_ONLY'], prohibitedActions: ['BUY_CANDIDATE', 'ADD_CANDIDATE', 'EXECUTION_BUY'], executionReachability: 'REACHABLE', batchPaths: ['限价单', '分批买入'], slippageLimit: 0.005, participationLimit: 0.1, manualConfirmationItems: ['所有执行动作需要人工复核'], forbiddenActions: ['自动下单', '市价追涨'] },
    signalOps: { signalStatus: 'WATCH', riskPassed: true, dvgPassed: false, qiamPassed: true, executionReachable: true, triggerConditions: ['数据可信度提升'], invalidationConditions: ['市场短期波动加大'], reviewFields: ['财务数据', '市场环境'], blockedReason: 'DVG REVIEW_ONLY 阻断 QUALIFIED', auditId: 'AUD_SIG_001' },
    paperTrading: { status: 'ACTIVE', observationPeriod: 14, entryAssumptions: ['行情不破支撑', '政策面稳定'], invalidationConditions: ['跌破 10% 止损', '流动性大幅收缩'], simulatedProfit: 0.03, maxDrawdown: 0.06, triggeredInvalidation: false, writtenToLedger: false, triggeredErrorLedger: false, simulation_only: true, is_real_trade: false, allowed_order_namespace: 'SIM_*', latest_action: 'SIM_HOLD' },
    finalAction: 'WAIT',
    killSwitch: { active: true, level: 'SOFT', triggerNode: 'guardrail_hub', triggerRule: 'data_reliability <= MEDIUM', blockedPaths: ['BUY_CANDIDATE', 'ADD_CANDIDATE', 'CHASE'], allowedPaths: ['WAIT', 'REVIEW_ONLY', 'HOLD', 'SIGNAL_ONLY'], finalWriterMode: 'CONSERVATIVE', auditId: 'AUD_KS_001' },
    auditLog: [{ timestamp: '2026-05-09T10:00:00Z', runId, node: 'orchestrator', eventType: 'RUN_CREATED', message: '创建 mock 分析任务', statusBefore: 'WAIT', statusAfter: 'PASS', inputHash: 'hash-input-0001', outputHash: 'hash-output-0001', auditId: 'AUD_0001' }],
    finalWriter: { mode: 'CONSERVATIVE', finalAction: 'WAIT', humanConfirmationRequired: true, auditId: 'AUD_FW_001', sections },
    createdAt: '2026-05-09T09:58:00Z',
    updatedAt: '2026-05-09T09:58:00Z',
    status: 'CREATED',
    dataSources: {
      sources: {
        realtime_quote: { name: '实时行情', provider: 'tushare', icon: 'BarChart3', status: 'READY' as const, detail: 'Tushare SDK realtime_quote 成功返回', fetchedAt: '2026-05-09T10:00:00Z', available: true, error: '', category: '行情' },
        fundamentals: { name: '财务数据', provider: 'tushare', icon: 'FileText', status: 'NOT_CONFIGURED' as const, detail: '暂未接入 tushare 财务接口 (income/balance/cashflow)，当前使用模拟数据', available: false, category: '基本面' },
        announcements: { name: '公告数据', provider: 'tushare', icon: 'Clock', status: 'NOT_CONFIGURED' as const, detail: '暂未接入 tushare 公告接口 (disclosure)，当前使用 Mock 模拟近 30 日公告', available: false, category: '消息面' },
        moneyflow: { name: '资金流向', provider: 'tushare', icon: 'Layers', status: 'NOT_CONFIGURED' as const, detail: '暂未接入 tushare 资金流接口 (moneyflow)，缺少主力/散户/大单资金流向数据', available: false, category: '资金面' },
        chip: { name: '筹码分布', provider: 'tushare', icon: 'Target', status: 'NOT_CONFIGURED' as const, detail: '暂未启用 tushare cyq_perf/cyq_chips；无权限或失败时仅使用 K 线代理估算', available: false, category: '筹码面' },
      },
      summary: { availableCount: 1, totalCount: 5, availableRatio: '1/5', overallStatus: 'PARTIAL' as const, generatedAt: '2026-05-09T10:00:00Z' },
    },
    agentResults,
    dagEvents,
    debateArtifacts: {
      run_id: runId,
      final_action: 'WAIT',
      final_decision_cap: 'UPSTREAM_ONLY',
      kill_switch: { active: true, level: 'SOFT', triggerNode: 'guardrail_hub', triggerRule: 'data_reliability <= MEDIUM', blockedPaths: ['BUY_CANDIDATE', 'ADD_CANDIDATE', 'CHASE'], allowedPaths: ['WAIT', 'REVIEW_ONLY', 'HOLD', 'SIGNAL_ONLY'], finalWriterMode: 'CONSERVATIVE', auditId: 'AUD_KS_001' },
      turns: debateTurns,
      summary: {
        support_count: debateTurns.filter((t) => t.stance === 'support').length,
        challenge_count: debateTurns.filter((t) => t.stance === 'challenge').length,
        block_count: debateTurns.filter((t) => t.stance === 'block').length,
        dominant_constraint: '数据可靠性不足与仓位上限',
        final_action: 'WAIT',
        human_confirmation_required: true,
      },
      audit_id: `AUD_DEBATE_${runId}`,
    },
    tokenUsage,
    orchestratorPlan: {
      mode: 'STANDARD_MODE',
      mandatory_nodes: ['orchestrator', 'data_reliability_engine', 'guardrail_hub', 'final_writer'],
      conditional_nodes: ['quant_core', 'execution', 'anti_conclusion'],
      kill_switch_rules: ['guardrail_hub hard_stop -> skip BUY/ADD'],
    },
  }
}

function cloneBaseWithOverrides(
  id: string,
  overrides: Record<string, Partial<AgentResult>> = {},
  extraPatch?: (run: AnalysisRun) => AnalysisRun
): AnalysisRun {
  const run = createBaseRun(id, overrides)
  if (extraPatch) {
    return extraPatch(run)
  }
  return run
}

export const scenarios: Record<string, AnalysisRun> = {
  standard: createBaseRun('STANDARD'),
  qiam_discounted: createBaseRun('STANDARD'),
  review_only: cloneBaseWithOverrides('REVIEW_ONLY', {}, (run) => {
    run.finalAction = 'WAIT'
    run.killSwitch.level = 'SOFT'
    return run
  }),
  hard_stop: cloneBaseWithOverrides('HARD_STOP', {
    guardrail_hub: { status: 'BLOCK', hard_stop: true, reasons: ['触发硬风险阻断'], blocked_actions: ['BUY_CANDIDATE', 'ADD_CANDIDATE'] },
  }, (run) => {
    run.finalAction = 'WAIT'
    run.killSwitch.level = 'HARD'
    run.killSwitch.triggerNode = 'guardrail_hub'
    run.killSwitch.triggerRule = 'hard_stop triggered'
    if (run.guardrailHub) {
      run.guardrailHub.status = 'BLOCK'
      run.guardrailHub.finalDecisionCap = 'BLOCK_BUY'
      run.guardrailHub.killSwitch = run.killSwitch
    }
    return run
  }),
  skip_qiam: cloneBaseWithOverrides('SKIP_QIAM', {
    quant_core: { status: 'SKIPPED', skipped_reason: '上游 Guardrail Hub 触发 REVIEW_ONLY，Quant Core 被编排器跳过' },
  }),
  all_pass: cloneBaseWithOverrides('ALL_PASS', {
    guardrail_hub: { status: 'PASS', confidence: 'HIGH', reasons: ['数据完整性和护栏检查通过'], missing_data: [], warnings: [], final_decision_cap: null },
    quant_core: { status: 'PASS', confidence: 'HIGH', reasons: ['原始 FAVORABLE 无需折扣，因子数据完整'], missing_data: [], warnings: [], allowed_actions: [] },
    execution: { status: 'PASS', confidence: 'HIGH', reasons: ['执行路径正常'], allowed_actions: [], blocked_actions: [], warnings: [] },
    signalops: { status: 'PASS', confidence: 'HIGH', reasons: ['信号已升级至 QUALIFIED'], warnings: [], blocked_actions: [] },
  }, (run) => {
    run.finalAction = 'HOLD'
    run.killSwitch.active = false
    if (run.guardrailHub) {
      run.guardrailHub.status = 'PASS'
      run.guardrailHub.finalDecisionCap = 'NO_CAP'
      run.guardrailHub.killSwitch = run.killSwitch
      run.guardrailHub.warnings = []
    }
    run.dvg.allowedOutputLevel = 'FULL'
    run.dvg.dataReliability = 'HIGH'
    run.dvg.hardStop = false
    run.signalOps.signalStatus = 'QUALIFIED'
    run.signalOps.dvgPassed = true
    run.signalOps.blockedReason = ''
    return run
  }),
}

export const mockScenarios: Record<string, AnalysisRun> = {
  ...scenarios,
  normal_pass: scenarios.all_pass,
  dvg_review_only: scenarios.review_only,
  hard_kill_switch: scenarios.hard_stop,
  compliance_block: scenarios.hard_stop,
  execution_not_reachable: scenarios.skip_qiam,
}
