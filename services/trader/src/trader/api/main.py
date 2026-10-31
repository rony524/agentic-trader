"""Agentic Trader — FastAPI application."""
from __future__ import annotations
import datetime as dt, json, os, uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from trader.settings import settings, get_strategy, get_risk, get_approvers, get_universe
from trader.store.models import (
    init_db, get_db, AuditLog, Backtest, Proposal, Signature, Order,
    NewsItem, Signal, Digest, Event, PortfolioSnapshot, ServiceHeartbeat, Control
)
from trader.audit.chain import append_audit, verify_chain, canonical_json, sha256
from trader.approval.eip712 import compute_proposal_hash, build_typed_data, verify_signature
from trader.signals.engine import compute_composite_signals, THEME_KEYWORDS
from trader.backtest.engine import run_backtest, all_tickers
from trader.shockmap.propagate import propagate, load_graph

app = FastAPI(
    title="Agentic Trader API",
    description="AI research agent for chips, energy & supply chains. Paper trading only.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.WEB_ORIGIN, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

# ---------- Health / Status ----------

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "api", "ts": dt.datetime.now(dt.UTC).isoformat()}

@app.get("/status")
def status(db: Session = Depends(get_db)):
    heartbeats = db.query(ServiceHeartbeat).order_by(ServiceHeartbeat.ts.desc()).limit(10).all()
    controls = {c.key: c.value for c in db.query(Control).all()}
    frozen = controls.get("trading_frozen", str(settings.TRADING_FROZEN)).lower() == "true"
    agent_enabled = controls.get("agent_enabled", str(settings.AGENT_ENABLED)).lower() == "true"
    return {
        "paper_mode": True,
        "trading_frozen": frozen,
        "agent_enabled": agent_enabled,
        "heartbeats": [{"service": h.service, "status": h.status, "ts": h.ts.isoformat() if h.ts else ""} for h in heartbeats],
        "freshness": {"news": True, "prices": True, "fred": True},
    }

# ---------- Digest ----------

@app.get("/digest/latest")
def latest_digest(db: Session = Depends(get_db)):
    d = db.query(Digest).order_by(Digest.created_at.desc()).first()
    if not d:
        raise HTTPException(404, "No digest available. Run the pipeline first.")
    return {
        "as_of": d.as_of, "chips_section": d.chips_section,
        "energy_section": d.energy_section, "supply_section": d.supply_section,
        "sources": d.sources_json, "created_at": d.created_at.isoformat() if d.created_at else ""
    }

# ---------- Signals ----------

@app.get("/signals")
def get_signals(as_of: str | None = None, db: Session = Depends(get_db)):
    signals = db.query(Signal).order_by(Signal.rank.asc()).all()
    if not signals:
        return {"signals": [], "coverage": 0.0}
    return {
        "signals": [{
            "ticker": s.ticker, "s1_momentum": round(s.s1_momentum, 4), "s2_news": round(s.s2_news, 4),
            "s3_shock": round(s.s3_shock, 4), "s4_fund": round(s.s4_fund, 4),
            "composite": round(s.composite, 4), "rank": s.rank, "selected": s.selected,
            "vol_regime": s.vol_regime, "market_trend": s.market_trend,
        } for s in signals],
        "count": len(signals)
    }

# ---------- Shock Map ----------

@app.get("/shockmap")
def get_shockmap():
    g = load_graph()
    return {
        "nodes": [{"id": nid, "label": n.get("label", nid), "type": n.get("type", "factor")}
                  for nid, n in g["nodes"].items()],
        "edges": g["edges"],
    }

@app.post("/shockmap/what-if")
def shockmap_what_if(body: dict):
    events = body.get("events", [])
    result = propagate(events)
    return {"exposure": result["exposure"], "explanations": result.get("explanations", {})}

# ---------- Proposals ----------

@app.get("/proposals")
def list_proposals(status_filter: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Proposal)
    if status_filter:
        q = q.filter(Proposal.status == status_filter.upper())
    props = q.order_by(Proposal.created_at.desc()).all()
    return {"proposals": [{
        "id": p.id, "kind": p.kind, "title": p.title, "confidence": p.confidence,
        "status": p.status, "created_at": p.created_at.isoformat() if p.created_at else "",
        "expires_at": p.expires_at.isoformat() if p.expires_at else "",
    } for p in props]}

@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str, db: Session = Depends(get_db)):
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p:
        raise HTTPException(404, "Proposal not found")
    sigs = db.query(Signature).filter(Signature.proposal_id == proposal_id).all()
    baseline = db.query(Backtest).filter(Backtest.id == p.backtest_baseline_id).first()
    candidate = db.query(Backtest).filter(Backtest.id == p.backtest_candidate_id).first() if p.backtest_candidate_id else None
    return {
        "id": p.id, "kind": p.kind, "title": p.title, "rationale": p.rationale,
        "evidence": p.evidence_json, "config_diff": p.config_diff,
        "target_weights": p.target_weights, "orders_preview": p.orders_preview,
        "backtest_baseline_id": p.backtest_baseline_id,
        "backtest_candidate_id": p.backtest_candidate_id,
        "variants_tested": p.variants_tested, "risk_notes": p.risk_notes,
        "confidence": p.confidence, "status": p.status,
        "proposal_hash": p.proposal_hash,
        "created_at": p.created_at.isoformat() if p.created_at else "",
        "expires_at": p.expires_at.isoformat() if p.expires_at else "",
        "signatures": [{
            "decision": s.decision, "approver": s.approver,
            "signed_at": s.signed_at.isoformat() if s.signed_at else "",
        } for s in sigs],
        "baseline_metrics": baseline.metrics_json if baseline else {},
        "candidate_metrics": candidate.metrics_json if candidate else {},
        "baseline_curve": baseline.equity_curve if baseline else [],
        "candidate_curve": candidate.equity_curve if candidate else [],
    }

@app.get("/proposals/{proposal_id}/typed-data")
def get_typed_data(proposal_id: str, decision: str = "APPROVE", db: Session = Depends(get_db)):
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p:
        raise HTTPException(404, "Proposal not found")
    expires_ts = int(p.expires_at.timestamp()) if p.expires_at else int(dt.datetime.now(dt.UTC).timestamp()) + 86400
    nonce = int(uuid.uuid4().int % 10**9)
    typed = build_typed_data(
        proposal_id=p.id, proposal_hash=p.proposal_hash,
        decision=decision, kind=p.kind, expires_at=expires_ts, nonce=nonce
    )
    return {"typed_data": typed, "nonce": nonce}

class SignatureRequest(BaseModel):
    decision: str  # APPROVE | REJECT
    signature: str
    comment: str = ""
    nonce: int = 0

@app.post("/proposals/{proposal_id}/signatures")
def submit_signature(proposal_id: str, req: SignatureRequest, db: Session = Depends(get_db)):
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p:
        raise HTTPException(404, "Proposal not found")

    # Reconstruct the typed data for verification
    expires_ts = int(p.expires_at.timestamp()) if p.expires_at else 0
    typed = build_typed_data(
        proposal_id=p.id, proposal_hash=p.proposal_hash,
        decision=req.decision, kind=p.kind, expires_at=expires_ts, nonce=req.nonce
    )
    try:
        signer = verify_signature(typed, req.signature)
    except Exception as e:
        raise HTTPException(400, f"Invalid signature: {e}")

    approvers_cfg = get_approvers()
    registry = {a["address"].lower() for a in approvers_cfg.get("approvers", [])}
    if registry and signer not in registry:
        raise HTTPException(403, f"Signer {signer} not in approver registry")

    sig = Signature(
        proposal_id=proposal_id, proposal_hash=p.proposal_hash,
        decision=req.decision, approver=signer, signature=req.signature,
        nonce=str(req.nonce)
    )
    db.add(sig)

    if req.decision == "REJECT":
        p.status = "REJECTED"
        append_audit(signer, "STATE_CHANGE", {"proposal_id": proposal_id, "from": p.status, "to": "REJECTED"})
    else:
        # check threshold
        approvals = db.query(Signature).filter(Signature.proposal_id == proposal_id, Signature.decision == "APPROVE").all()
        threshold = approvers_cfg.get("threshold", {}).get(p.kind, 1)
        distinct_signers = {s.approver for s in approvals}
        if len(distinct_signers) >= threshold:
            p.status = "APPROVED"
            append_audit(signer, "APPROVAL_SIGNED", {"proposal_id": proposal_id, "decision": "APPROVE", "threshold_met": True})

    db.commit()
    return {"status": p.status, "signer": signer, "message": "Signature recorded"}

# ---------- Backtests ----------

@app.get("/backtests/{bt_id}")
def get_backtest(bt_id: str, db: Session = Depends(get_db)):
    bt = db.query(Backtest).filter(Backtest.id == bt_id).first()
    if not bt:
        raise HTTPException(404, "Backtest not found")
    return {
        "id": bt.id, "kind": bt.kind, "config_hash": bt.config_hash,
        "metrics": bt.metrics_json, "equity_curve": bt.equity_curve,
        "as_of_start": bt.as_of_start, "as_of_end": bt.as_of_end,
        "created_at": bt.created_at.isoformat() if bt.created_at else "",
    }

# ---------- Portfolio ----------

@app.get("/portfolio")
def get_portfolio(db: Session = Depends(get_db)):
    from trader.execution.executor import get_account_snapshot
    snapshot = get_account_snapshot()
    snaps = db.query(PortfolioSnapshot).order_by(PortfolioSnapshot.date.desc()).limit(30).all()
    orders = db.query(Order).order_by(Order.submitted_at.desc()).limit(50).all()
    return {
        "account": snapshot,
        "snapshots": [{"date": s.date, "equity": s.equity} for s in snaps],
        "orders": [{"id": o.id, "proposal_id": o.proposal_id, "symbol": o.symbol,
                    "side": o.side, "status": o.status,
                    "alpaca_order_id": o.alpaca_order_id} for o in orders],
    }

# ---------- Audit ----------

@app.get("/audit")
def get_audit(after_seq: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    entries = db.query(AuditLog).filter(AuditLog.seq > after_seq).order_by(AuditLog.seq.asc()).limit(limit).all()
    return {"entries": [{
        "seq": e.seq, "ts": e.ts.isoformat() if e.ts else "",
        "actor": e.actor, "event_type": e.event_type,
        "payload_hash": e.payload_hash, "prev_hash": e.prev_hash,
        "entry_hash": e.entry_hash, "payload": json.loads(e.payload_json),
    } for e in entries]}

@app.get("/audit/verify")
def verify_audit():
    return verify_chain()

# ---------- Admin / Controls ----------

class RunPipelineRequest(BaseModel):
    token: str = ""

@app.post("/admin/run-pipeline")
def run_pipeline_endpoint(req: RunPipelineRequest):
    admin_token = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
    if req.token != admin_token:
        raise HTTPException(403, "Invalid admin token")
    from trader.agent.pipeline import run_pipeline
    result = run_pipeline()
    return result

class ControlRequest(BaseModel):
    key: str
    value: str

@app.post("/controls")
def set_control(req: ControlRequest, db: Session = Depends(get_db)):
    c = db.query(Control).filter(Control.key == req.key).first()
    if c:
        c.value = req.value
    else:
        db.add(Control(key=req.key, value=req.value))
    db.commit()
    append_audit("admin", "CONTROL_SET", {"key": req.key, "value": req.value})
    return {"status": "ok"}

# ---------- Approver Management ----------

class ApproverRequest(BaseModel):
    name: str
    address: str
    roles: list[str] = ["operator"]

@app.post("/admin/approvers")
def add_approver(req: ApproverRequest):
    """Add an approver to the registry (hackathon: direct write)."""
    from trader.settings import load_yaml, save_yaml
    cfg = load_yaml("approvers.yaml")
    cfg["approvers"].append({"name": req.name, "address": req.address, "roles": req.roles})
    save_yaml("approvers.yaml", cfg)
    append_audit("admin", "APPROVER_ADDED", {"name": req.name, "address": req.address})
    return {"status": "ok", "approvers": cfg["approvers"]}

@app.get("/admin/approvers")
def list_approvers():
    return get_approvers()

# ---------- Orders (manual execution for testing) ----------

class ExecuteRequest(BaseModel):
    proposal_id: str

@app.post("/admin/execute")
def execute_proposal(req: ExecuteRequest, db: Session = Depends(get_db)):
    """Manually trigger execution of an APPROVED proposal."""
    from trader.execution.executor import execute_approved_proposals
    p = db.query(Proposal).filter(Proposal.id == req.proposal_id).first()
    if not p:
        raise HTTPException(404, "Proposal not found")
    if p.status != "APPROVED":
        raise HTTPException(400, f"Proposal is {p.status}, must be APPROVED to execute")
    results = execute_approved_proposals()
    return {"results": results}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
