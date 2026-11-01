"""Alpaca paper trading executor — paper-only enforced at every level."""
from __future__ import annotations
import os, datetime as dt
from trader.settings import settings, get_approvers
from trader.store.models import SessionLocal, Proposal, Order, Signature, Control, PortfolioSnapshot, init_db, as_utc
from trader.audit.chain import append_audit
from trader.approval.eip712 import build_typed_data, SignatureError, threshold_for
from trader.approval.passkeys import verify_any, person

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
    # verify base URL; alpaca-py stores it as a BaseURL enum whose str() is "BaseURL.TRADING_PAPER", so compare .value
    base = getattr(client, "_base_url", None) or getattr(client, "base_url", None)
    base_url = str(getattr(base, "value", base) or "").rstrip("/")
    if base is not None and base_url != PAPER_BASE_URL:
        raise PaperOnlyViolation(f"TradingClient base URL is not paper: {base_url}")
    return client

def get_data_client():
    assert_paper_only()
    try:
        from alpaca.data.historical import StockHistoricalDataClient
    except ImportError:
        raise PaperOnlyViolation("alpaca-py not installed — cannot construct data client")
    return StockHistoricalDataClient(settings.ALPACA_API_KEY_ID, settings.ALPACA_API_SECRET_KEY)

def is_trading_frozen(db) -> bool:
    c = db.query(Control).filter(Control.key == "trading_frozen").first()
    value = c.value if c else str(settings.TRADING_FROZEN)
    return value.lower() == "true"

def verify_approvals(db, prop: Proposal) -> tuple[bool, str]:
    """Independently re-verify the signatures on a proposal; never trust its status alone."""
    approvers_cfg = get_approvers()
    expires_ts = int(as_utc(prop.expires_at).timestamp()) if prop.expires_at else 0
    signers = set()
    for sig in db.query(Signature).filter(Signature.proposal_id == prop.id, Signature.decision == "APPROVE").all():
        if sig.proposal_hash != prop.proposal_hash:
            continue
        typed = build_typed_data(prop.id, prop.proposal_hash, "APPROVE", prop.kind, expires_ts, int(sig.nonce))
        try:
            signer = verify_any(typed, sig.signature, db, approvers_cfg, check_counter=False)
        except (SignatureError, PermissionError):
            continue
        if signer == sig.approver:
            signers.add(person(signer, approvers_cfg))  # a wallet and a passkey of one approver count once
    threshold = threshold_for(approvers_cfg, prop.kind)
    if len(signers) < threshold:
        return False, f"{len(signers)} valid approval signature(s), {threshold} required"
    return True, ""

def _submit(client, db, prop: Proposal, symbol: str, side: str, *, qty: float | None = None, notional: float | None = None) -> dict:
    from alpaca.trading.requests import MarketOrderRequest
    req = MarketOrderRequest(
        symbol=symbol, side=side, time_in_force="day",
        qty=qty, notional=notional,
        client_order_id=f"{prop.id}:{symbol}:{side}",
    )
    o = client.submit_order(req)
    db.add(Order(
        proposal_id=prop.id, symbol=symbol, side=side,
        qty="" if qty is None else str(qty), notional="" if notional is None else str(notional),
        status=str(getattr(o, "status", "submitted")), alpaca_order_id=str(o.id),
    ))
    db.commit()
    append_audit("executor", "ORDER_SUBMITTED", {"proposal_id": prop.id, "symbol": symbol, "side": side,
                                                 "qty": qty, "notional": notional, "alpaca_id": str(o.id)})
    return {"symbol": symbol, "side": side, "alpaca_id": str(o.id)}

def execute_approved_proposals(client=None) -> list[dict]:
    """Executor loop: execute all APPROVED proposals via Alpaca paper. `client` is injectable for tests."""
    if client is None and not settings.ALPACA_API_KEY_ID:
        return []
    assert_paper_only()
    init_db()
    db = SessionLocal()
    try:
        pending = db.query(Proposal).filter(Proposal.status == "APPROVED").all()
        if not pending or is_trading_frozen(db):
            return []

        client = client or get_trading_client()
        results = []

        for prop in pending:
            if prop.expires_at and as_utc(prop.expires_at) < dt.datetime.now(dt.UTC):
                prop.status = "EXPIRED"
                db.commit()
                append_audit("executor", "STATE_CHANGE", {"proposal_id": prop.id, "from": "APPROVED", "to": "EXPIRED"})
                continue

            ok, reason = verify_approvals(db, prop)
            if not ok:
                prop.status = "FAILED"
                db.commit()
                append_audit("executor", "VERIFICATION_FAILED", {"proposal_id": prop.id, "reason": reason})
                continue

            target_weights = prop.target_weights or {}
            if not target_weights:
                prop.status = "FAILED"
                db.commit()
                append_audit("executor", "STATE_CHANGE", {"proposal_id": prop.id, "from": "APPROVED", "to": "FAILED", "error": "no target weights"})
                continue

            prop.status = "EXECUTING"
            db.commit()
            append_audit("executor", "STATE_CHANGE", {"proposal_id": prop.id, "from": "APPROVED", "to": "EXECUTING"})

            try:
                equity = float(client.get_account().equity)
                positions = {p.symbol: float(p.qty) for p in client.get_all_positions()}
                orders = []

                # sells first (positions not in the target are closed), then buys
                for sym, qty in positions.items():
                    if target_weights.get(sym, 0) < 0.001 and qty > 0:
                        orders.append(_submit(client, db, prop, sym, "sell", qty=qty))

                for sym, w in target_weights.items():
                    notional = round(w * equity, 2)
                    if w > 0.001 and notional >= 50 and sym not in positions:
                        orders.append(_submit(client, db, prop, sym, "buy", notional=notional))

                prop.status = "EXECUTED"
                db.commit()
                append_audit("executor", "STATE_CHANGE", {"proposal_id": prop.id, "from": "EXECUTING", "to": "EXECUTED", "orders": len(orders)})
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
