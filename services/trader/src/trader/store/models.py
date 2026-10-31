"""SQLAlchemy 2 models for all tables."""
from __future__ import annotations
import datetime as dt
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, JSON, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker
from trader.settings import settings

Base = declarative_base()
engine = create_engine(settings.DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

class AuditLog(Base):
    __tablename__ = "audit_log"
    seq = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    actor = Column(String, default="system")
    event_type = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    payload_hash = Column(String, nullable=False)
    prev_hash = Column(String, default="")
    entry_hash = Column(String, nullable=False)

class Backtest(Base):
    __tablename__ = "backtests"
    id = Column(String, primary_key=True)
    kind = Column(String, default="baseline")  # baseline | candidate
    config_json = Column(JSON, default={})
    config_hash = Column(String, default="")
    metrics_json = Column(JSON, default={})
    equity_curve = Column(JSON, default=[])
    weights_curve = Column(JSON, default=[])
    as_of_start = Column(String, default="")
    as_of_end = Column(String, default="")
    code_version = Column(String, default="dev")
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))

class Proposal(Base):
    __tablename__ = "proposals"
    id = Column(String, primary_key=True)
    kind = Column(String, default="rebalance")  # rebalance|param_change|risk_reduction|hypothesis
    title = Column(String, default="")
    rationale = Column(Text, default="")
    evidence_json = Column(JSON, default=[])
    config_diff = Column(JSON, default=None)
    target_weights = Column(JSON, default=None)
    orders_preview = Column(JSON, default=None)
    backtest_baseline_id = Column(String, default="")
    backtest_candidate_id = Column(String, default=None)
    variants_tested = Column(Integer, default=1)
    risk_notes = Column(JSON, default={})
    confidence = Column(String, default="medium")
    status = Column(String, default="PENDING_REVIEW")  # PENDING_REVIEW|REJECTED|APPROVED|EXPIRED|EXECUTING|EXECUTED|GATED_OUT
    proposal_hash = Column(String, default="")
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    expires_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC) + dt.timedelta(hours=24))

class Signature(Base):
    __tablename__ = "signatures"
    id = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(String, nullable=False)
    proposal_hash = Column(String, nullable=False)
    decision = Column(String, nullable=False)  # APPROVE | REJECT
    approver = Column(String, nullable=False)
    signed_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    nonce = Column(String, default="0")
    signature = Column(Text, nullable=False)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    proposal_id = Column(String, nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    qty = Column(String, default="")
    notional = Column(String, default="")
    order_type = Column(String, default="market")
    tif = Column(String, default="day")
    status = Column(String, default="pending")
    alpaca_order_id = Column(String, default="")
    submitted_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))

class NewsItem(Base):
    __tablename__ = "news_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String, default="")
    summary = Column(Text, default="")
    url = Column(String, nullable=False)
    source = Column(String, default="")
    theme = Column(String, default="")
    published_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    retrieved_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))

class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    as_of = Column(String, nullable=False)
    ticker = Column(String, nullable=False)
    s1_momentum = Column(Float, default=0)
    s2_news = Column(Float, default=0)
    s3_shock = Column(Float, default=0)
    s4_fund = Column(Float, default=0)
    composite = Column(Float, default=0)
    rank = Column(Integer, default=0)
    vol_regime = Column(Float, default=1.0)
    market_trend = Column(Float, default=1.0)
    selected = Column(Boolean, default=False)

class Digest(Base):
    __tablename__ = "digests"
    id = Column(Integer, primary_key=True, autoincrement=True)
    as_of = Column(String, nullable=False)
    chips_section = Column(Text, default="")
    energy_section = Column(Text, default="")
    supply_section = Column(Text, default="")
    sources_json = Column(JSON, default=[])
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    theme = Column(String, nullable=False)
    node_id = Column(String, nullable=False)
    direction = Column(Integer, default=1)
    magnitude = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)
    summary = Column(String, default="")
    evidence_urls = Column(JSON, default=[])
    classified_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))
    model_id = Column(String, default="")

class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, nullable=False)
    equity = Column(Float, default=100000)
    cash = Column(Float, default=100000)
    positions_json = Column(JSON, default=[])

class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"
    id = Column(Integer, primary_key=True, autoincrement=True)
    service = Column(String, nullable=False)
    status = Column(String, default="ok")
    ts = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC))

class Control(Base):
    __tablename__ = "controls"
    key = Column(String, primary_key=True)
    value = Column(String, default="")

def init_db():
    Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
