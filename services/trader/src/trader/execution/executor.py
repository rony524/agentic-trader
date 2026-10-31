"""Alpaca paper trading executor — paper-only enforced at every level."""
from __future__ import annotations
import os, datetime as dt
from trader.settings import settings
from trader.store.models import SessionLocal, Proposal, Order, PortfolioSnapshot, init_db
from trader.audit.chain import append_audit

# Hard-coded paper endpoint — no way to change this
PAPER_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_BASE_URL = "https://api.alpaca.markets"  # forbidden

class PaperOnlyViolation(Exception): pass

def assert_paper_only():
    """Defense in depth: verify paper-only config before any broker call."""
    if not settings.ALPACA_PAPER:
        raise PaperOnlyViolation("ALPACA_PAPER must be true — live trading is forbidden")
    if LIVE_BASE_URL in str(settings.ALPACA_API_KEY_ID):
        raise PaperOnlyViolation("live endpoint detected in config")
    if settings.EXPECTED_PAPER_ACCOUNT and not settings.EXPECTED_PAPER_ACCOUNT.startswith("PA"):
        raise PaperOnlyViolation("EXPECTED_PAPER_ACCOUNT must start with PA (paper account)")

def get_trading_client():
    """Constructs TradingClient with paper=True constant."""
    assert_paper_only()
    try:
        from alpaca.trading.client import TradingClient
    except ImportError:
        raise PaperOnlyViolation("alpaca-py not installed — cannot construct trading client")
    client = TradingClient(
        settings.ALPACA_API_KEY_ID,
        settings.ALPACA_API_SECRET_KEY,
        paper=True  # constant, not from env
    )
    # verify base URL
    base = getattr(client, "_base_url", None) or getattr(client, "base_url", None)
    if base and "paper" not in str(base):
        raise PaperOnlyViolation(f"TradingClient base URL is not paper: {base}")
    return client

def get_data_client():
    assert_paper_only()
    try:
        from alpaca.data.historical import StockHistoricalDataClient
    except ImportError:
        raise PaperOnlyViolation("alpaca-py not installed — cannot construct data client")
    return StockHistoricalDataClient(settings.ALPACA_API_KEY_ID, settings.ALPACA_API_SECRET_KEY)

def execute_approved_proposals() -> list[dict]:
    """Executor loop: execute all APPROVED proposals via Alpaca paper."""
    if not settings.ALPACA_API_KEY_ID:
        return []
    assert_paper_only()
    init_db()
    db = SessionLocal()
    try:
        pending = db.query(Proposal).filter(Proposal.status == "APPROVED").all()
        if not pending:
            return []

        client = get_trading_client()
        results = []

        for prop in pending:
            if prop.expires_at and prop.expires_at < dt.datetime.now(dt.UTC):
                prop.status = "EXPIRED"
                db.commit()
                continue

            prop.status = "EXECUTING"
            db.commit()
            append_audit("executor", "STATE_CHANGE", {"proposal_id": prop.id, "from": "APPROVED", "to": "EXECUTING"})

            target_weights = prop.target_weights or {}
            if not target_weights:
                prop.status = "FAILED"
                db.commit()
                continue

            try:
                account = client.get_account()
                equity = float(account.equity)
                orders = []

                # sells first, then buys
                positions = {p.symbol: float(p.qty) * float(p.current_price) for p in client.get_all_positions()}
                sells = {sym: w for sym, w in target_weights.items() if w < 0.001}
                buys = {sym: w for sym, w in target_weights.items() if w > 0.001}

                for sym in sells:
                    if sym in positions:
                        notional = abs(positions[sym])  # sell all
                        if notional > 50:
                            from alpaca.trading.requests import MarketOrderRequest
                            req = MarketOrderRequest(
                                symbol=sym, notional=round(notional, 2),
                                side="sell", time_in_force="day",
                                client_order_id=f"{prop.id}:{sym}:sell"
                            )
                            o = client.submit_order(req)
                            orders.append({"symbol": sym, "side": "sell", "alpaca_id": str(o.id)})
                            append_audit("executor", "ORDER_SUBMITTED", {"proposal_id": prop.id, "symbol": sym, "side": "sell", "alpaca_id": str(o.id)})

                for sym in buys:
                    notional = target_weights[sym] * equity
                    if notional < 50:
                        continue
                    from alpaca.trading.requests import MarketOrderRequest
                    req = MarketOrderRequest(
                        symbol=sym, notional=round(notional, 2),
                        side="buy", time_in_force="day",
                        client_order_id=f"{prop.id}:{sym}:buy"
                    )
                    o = client.submit_order(req)
                    orders.append({"symbol": sym, "side": "buy", "alpaca_id": str(o.id)})
                    append_audit("executor", "ORDER_SUBMITTED", {"proposal_id": prop.id, "symbol": sym, "side": "buy", "alpaca_id": str(o.id)})

                prop.status = "EXECUTED"
                db.commit()
                append_audit("executor", "STATE_CHANGE", {"proposal_id": prop.id, "from": "EXECUTING", "to": "EXECUTED"})
                results.append({"proposal_id": prop.id, "orders": orders})
            except Exception as e:
                prop.status = "FAILED"
                db.commit()
                append_audit("executor", "STATE_CHANGE", {"proposal_id": prop.id, "from": "EXECUTING", "to": "FAILED", "error": str(e)})

        return results
    finally:
        db.close()

def get_account_snapshot() -> dict:
    if not settings.ALPACA_API_KEY_ID:
        return {"equity": 100000, "cash": 100000, "positions": [], "status": "mock"}
    assert_paper_only()
    client = get_trading_client()
    acct = client.get_account()
    positions = [{
        "symbol": p.symbol, "qty": str(p.qty), "market_value": str(p.market_value),
        "avg_entry_price": str(p.avg_entry_price), "unrealized_pl": str(p.unrealized_pl)
    } for p in client.get_all_positions()]
    return {
        "equity": float(acct.equity), "cash": float(acct.cash),
        "buying_power": float(acct.buying_power), "positions": positions,
        "status": "paper"
    }
