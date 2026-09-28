# Tool Contract 工具/API 契约

## 1. 总原则

1. 工具没有返回，不得由 LLM 补数据。
2. 工具失败时，对应字段标记为 [U] / MISSING / FAILED。
3. 盘中执行数据必须有 timestamp。
4. 过期数据不得用于盘中执行判断。
5. 计算类任务必须交给 Python / API / 规则引擎。
6. LLM 不得口算复杂 EV、概率、动态权重、滑点、盘口队列。

## 2. 基础行情工具

- get_realtime_quote(symbol)
- get_limit_status(symbol)
- get_intraday_volume_distribution(symbol)
- get_intraday_money_flow_distribution(symbol)
- get_volume_price_distribution(symbol)
- get_turnover_distribution(symbol)

## 3. A 股微结构工具

- check_t_plus_one_inventory(account_id, symbol)
- get_orderbook_depth(symbol)
- get_limit_order_queue(symbol)
- detect_flash_crash(symbol)
- run_slippage_curve_simulation(symbol, order_size)
- estimate_slippage(symbol, order_size)

## 4. 公告与基本面工具

- verify_exchange_announcement(symbol)
- get_financial_report(symbol)
- check_shareholder_changes(symbol)
- check_unlock_and_reduction(symbol)
- get_block_trade_and_reduction_history(symbol)

## 5. 资金与筹码工具

- get_money_flow_by_source(symbol)
- get_shareholder_count_history(symbol)
- get_institutional_holding_history(symbol)
- get_northbound_holding_history(symbol)
- get_margin_financing_history(symbol)

## 6. 市场与题材工具

- calculate_market_temperature()
- get_theme_crowding_index(theme)
- get_attention_heat_index(symbol)
- get_research_report_density(symbol)
- get_limit_open_board_history(symbol)

## 7. 因子和情景工具

- calculate_factor_slicing(symbol, data)
- calculate_factor_score(symbol, data)
- calculate_dynamic_weights(market_regime)
- calculate_scenario_ev(symbol, cases)
- calculate_risk_reward_ratio(symbol, plan)
- run_factor_slicing_backtest(factor_id)

## 8. DVG 工具

- validate_data_integrity(data)
- validate_source_integrity(data_sources)
- validate_data_freshness(data)
- calculate_hallucination_risk_score(context)
- validate_model_registry(model_id)
- validate_model_identity(model_id)
- check_model_out_of_sample_status(model_id)

## 9. QIAM 工具

- run_walk_forward_validation(model_id)
- detect_distribution_drift(model_id, current_data)
- calculate_regime_fit(symbol, market_regime)
- calculate_volatility_condition(symbol)
- calculate_liquidity_adjusted_momentum(symbol)
- calculate_bayesian_view_fusion(inputs)
- calculate_conformal_prediction_interval(model_id, inputs)
- run_lob_microstructure_model(symbol)
- run_time_series_forecast_model(symbol)
- calculate_probability_of_backtest_overfitting(model_id)
- calculate_deflated_sharpe_ratio(model_id)
- calculate_qiam_buy_suitability(inputs)

## 10. SignalOps 工具

- create_signal_record(signal)
- update_signal_status(signal_id, status)
- query_signal_ledger(filters)
- get_auto_paper_trading_config()
- update_auto_paper_trading_config(config)
- run_auto_paper_trading_tick(force=false)
- run_auto_paper_trading_command(symbol, command, reason)
- generate_ai_trigger_conditions(signal_id, market_context)
- generate_ai_invalidation_conditions(signal_id, market_context)
- record_sim_action(signal_id, action, price, quantity, reason)
- fill_sim_order(signal_id, paper_order_id, fill)
- calculate_paper_trade_metrics(signal_id)
- calculate_max_favorable_excursion(signal_id)
- calculate_max_adverse_excursion(signal_id)
- generate_signal_review_summary(signal_id)
- write_signal_error_tags(signal_id, tags)
- update_signal_reputation_score(signal_id)
- run_watchlist_heartbeat(watchlist)
- trigger_signal_patch_review(signal_id)

## 11. Meta / 复盘工具

- write_error_ledger_entry(entry)
- retrieve_memory_cases(query)
- search_similar_market_regimes(query)
- run_counterfactual_simulation(inputs)
- run_sensitivity_stress_test(inputs)
- generate_candidate_rule_patch(error_case)
- backtest_candidate_rule_patch(patch_id)
- run_anti_overfitting_check(patch_id)
- generate_system_state_blob(context)
- validate_system_state_blob(blob)

## 12. 工具返回标准

所有工具建议统一返回：

```json
{
  "tool_name": "",
  "status": "SUCCESS|PARTIAL|FAILED",
  "data": {},
  "missing_fields": [],
  "timestamp": "",
  "source": "",
  "calculation_method": "",
  "model_version": "",
  "audit_id": ""
}
```
