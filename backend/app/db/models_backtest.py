from sqlalchemy import Column, String, Integer, Float, Boolean, JSON, Text
from .session import Base
from .models_case_library import utcnow


class BacktestRunDB(Base):
    __tablename__ = "backtest_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(128), unique=True, nullable=False, index=True)
    patch_id = Column(String(128), nullable=True, index=True)
    case_id = Column(String(128), nullable=True, index=True)
    symbol = Column(String(32), nullable=False)
    stock_name = Column(String(64), default="")
    scenario_label = Column(String(128), default="")
    status = Column(String(32), default="PENDING")
    start_date = Column(String(32), default="")
    end_date = Column(String(32), default="")
    initial_capital = Column(Float, default=100000.0)
    parameters = Column(JSON, default=dict)
    report = Column(JSON, default=dict)
    comparison = Column(JSON, default=dict)
    error = Column(Text, nullable=True)
    elapsed_ms = Column(Integer, default=0)
    created_at = Column(String(64), default=utcnow)
    updated_at = Column(String(64), default=utcnow)


class BacktestTradeDB(Base):
    __tablename__ = "backtest_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_id = Column(String(128), unique=True, nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    direction = Column(String(8), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    slippage = Column(Float, default=0.0)
    timestamp = Column(String(32), nullable=False)
    reason = Column(String(256), default="")
    realized_pnl = Column(Float, nullable=True)
    created_at = Column(String(64), default=utcnow)


class BacktestSignalDB(Base):
    __tablename__ = "backtest_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(String(128), unique=True, nullable=False, index=True)
    run_id = Column(String(128), nullable=False, index=True)
    signal_type = Column(String(32), nullable=False)
    direction = Column(String(8), nullable=False)
    strength = Column(Float, default=0.0)
    price = Column(Float, nullable=False)
    timestamp = Column(String(32), nullable=False)
    source_node = Column(String(64), default="")
    metadata_json = Column(JSON, default=dict)
    created_at = Column(String(64), default=utcnow)
