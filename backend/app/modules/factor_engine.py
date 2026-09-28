from __future__ import annotations
from typing import Any, Dict

from ..core.quant_engine_modes import quant_engine_profile_from_run
from .base_agent import BaseAgent, AgentResult


class FactorEngineAgent(BaseAgent):
    node = "factor_engine"
    name = "Factor Engine"
    stage = "analysis"

    def process(self, run_context: Dict[str, Any], prior_outputs: Dict[str, Any]) -> AgentResult:
        quant_profile = quant_engine_profile_from_run(run_context)
        required_names = set((quant_profile.get("parameterProfile") or {}).get("requiredFactorNames") or [])
        factor = run_context.get("factorSlicing", {})
        factors = factor.get("factors", [])
        factor_clusters = factor.get("factorClusters", [])
        stability = factor.get("factorStability", 0.72)
        missing_factor_data = factor.get("missingFactorData", [])

        reasons = []
        warnings = []
        missing = list(missing_factor_data)

        if not factors:
            status = "WARN"
            reasons.append("无可用因子数据，因子引擎无法运行")
            warnings.append("因子数据缺失，无法评估多因子表现")
        else:
            reasons.append(f"已加载 {len(factors)} 个因子, {len(factor_clusters)} 个因子簇")

            has_value = any(f.get("name", "") == "Value" for f in factors)
            has_momentum = any(f.get("name", "") == "Momentum" for f in factors)
            has_liquidity = any(f.get("name", "") == "Liquidity" for f in factors)
            has_volatility = any(f.get("name", "") == "Volatility" for f in factors)
            factor_names = {str(f.get("name", "")) for f in factors if f.get("confidence", 0) > 0}

            if required_names:
                engine_status = "FULL" if required_names.issubset(factor_names) else ("LITE" if factor_names else "DEGRADED")
            else:
                engine_status = "FULL" if (has_value or has_volatility) and has_momentum and has_liquidity else ("LITE" if has_value or has_momentum or has_volatility else "DEGRADED")

            reasons.append(f"因子引擎运行模式: {engine_status}")

            if engine_status == "DEGRADED":
                status = "WARN"
                warnings.append("核心因子缺失严重，因子引擎能力降级")
            elif engine_status == "LITE":
                status = "PASS"
                reasons.append("运行于 LITE 模式，部分因子不可用")
            else:
                status = "PASS"

        if stability < 0.6:
            warnings.append(f"因子稳定性过低 ({stability:.2f})，建议关闭因子引擎")
            status = "WARN"

        if "回测数据" in str(missing_factor_data):
            warnings.append("缺少回测数据，因子历史表现无法验证")

        data = {
            "engineMode": "FULL" if status == "PASS" else "LITE",
            "quantEngineMode": quant_profile["mode"],
            "parameterProfile": quant_profile["parameterProfile"],
            "factorCount": len(factors),
            "clusterCount": len(factor_clusters),
            "factorStability": stability,
            "missingFactorData": missing_factor_data,
            "validationEnabled": status == "PASS",
        }

        return AgentResult(
            node=self.node,
            status=status,
            confidence="HIGH" if status == "PASS" else "MEDIUM",
            reasons=reasons,
            missing_data=missing,
            warnings=warnings,
            data=data,
            audit_id=self._audit(),
        )
