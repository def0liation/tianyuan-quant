from app.core.backtest_engine import run_backtest, run_comparison
from app.models.backtest import BacktestReport


def test_backtest_final_capital_marks_open_position_once():
    report = run_backtest(
        symbol="M5TEST",
        stock_name="M5 Smoke",
        start_date="2026-01-01",
        end_date="2026-01-03",
        initial_capital=100000,
        market_data=[
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
            {"date": "2026-01-02", "open": 11, "close": 11, "prev_close": 10},
            {"date": "2026-01-03", "open": 12, "close": 12, "prev_close": 11},
        ],
        signals=[
            {
                "timestamp": "2026-01-01",
                "signal_type": "BUY",
                "direction": "BUY",
                "strength": 1.0,
                "source_node": "quant_engine",
            }
        ],
        patch_params={
            "slippage_bps": 0,
            "signal_min_strength": 0.1,
            "trade_quantity_pct": 0.5,
        },
    )

    assert report.total_trades == 1
    assert report.final_capital == 110000
    assert report.total_pnl == 10000
    assert report.total_return_pct == 10
    assert report.equity_curve[-1]["capital"] == 110000


def test_backtest_blocks_same_day_sell_when_t_plus_one_enabled():
    report = run_backtest(
        symbol="M5TEST",
        stock_name="M5 Smoke",
        start_date="2026-01-01",
        end_date="2026-01-01",
        initial_capital=100000,
        market_data=[
            {"date": "2026-01-01", "open": 10, "close": 10, "prev_close": 10},
        ],
        signals=[
            {
                "timestamp": "2026-01-01",
                "signal_type": "BUY",
                "direction": "BUY",
                "strength": 1.0,
                "source_node": "quant_engine",
            },
            {
                "timestamp": "2026-01-01",
                "signal_type": "SELL",
                "direction": "SELL",
                "strength": 1.0,
                "source_node": "risk_firewall",
            },
        ],
        patch_params={
            "slippage_bps": 0,
            "signal_min_strength": 0.1,
            "trade_quantity_pct": 0.5,
            "t_plus_one": True,
        },
    )

    assert report.total_trades == 1
    assert report.t_plus_one_blocked == 1


def test_backtest_comparison_classifies_improved_patch():
    before = BacktestReport(hit_rate=0.4, max_drawdown_pct=0.1, false_positive_rate=0.2, total_pnl=1000, total_return_pct=1)
    after = BacktestReport(hit_rate=0.6, max_drawdown_pct=0.05, false_positive_rate=0.1, total_pnl=3000, total_return_pct=3)

    comparison = run_comparison(before, after)

    assert comparison.verdict == "IMPROVED"
    assert comparison.hit_rate_delta == 0.2
    assert comparison.drawdown_delta == -0.05
