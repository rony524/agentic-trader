"""Agentic Trader — FastAPI application."""
from __future__ import annotations
import datetime as dt, json, os, uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Depends, Request, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from trader.settings import settings, get_strategy, get_risk, get_approvers, get_universe
from trader.store.models import (
    init_db, get_db, as_utc, AuditLog, Backtest, Proposal, Signature, Order,
    NewsItem, Signal, Digest, Event, PortfolioSnapshot, ServiceHeartbeat, Control, Idea,
    Passkey, PasskeyInvite,
)
from trader.audit.chain import append_audit, verify_chain, canonical_json, sha256, ts_string
from trader.approval.eip712 import (
    compute_proposal_hash, build_typed_data, SignatureError,
    DECISIONS, threshold_for, build_idea_typed_data,
)
from trader.approval.passkeys import (
    verify_any, person, registration_options, verify_registration, b64url, from_b64url,
    request_options as passkey_request_options, PASSKEY_SIGNER,
)
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

def require_admin(x_admin_token: str = Header(default="")):
    """Admin endpoints need the ADMIN_TOKEN env var to be set and sent as X-Admin-Token."""
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    if not admin_token or x_admin_token != admin_token:
        raise HTTPException(403, "Invalid admin token")

def _verify_approver(typed: dict, signature: str, db: Session, approvers_cfg: dict) -> str:
    """Wallet (EIP-712) or passkey (WebAuthn) signature → registered approver's signer id, else 400/403."""
    try:
        return verify_any(typed, signature, db, approvers_cfg)
    except SignatureError as e:
        raise HTTPException(400, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))

def _passkey_options(typed: dict, db: Session) -> dict:
    return passkey_request_options(typed, [p.credential_id for p in db.query(Passkey).all()])

def expires_ts(p: Proposal) -> int:
    return int(as_utc(p.expires_at).timestamp()) if p.expires_at else 0

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

# ---------- Universe ----------

@app.get("/universe")
def universe():
    return {"sleeves": [{"sleeve": s["sleeve"], "tickers": s["tickers"]}
                        for s in get_universe().get("universe", [])]}

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
        "candidate_metrics": candidate.metrics_json if candidate else None,
        "baseline_curve": baseline.equity_curve if baseline else [],
        "candidate_curve": candidate.equity_curve if candidate else [],
    }

@app.get("/proposals/{proposal_id}/typed-data")
def get_typed_data(proposal_id: str, decision: str = "APPROVE", db: Session = Depends(get_db)):
    if decision not in DECISIONS:
        raise HTTPException(400, f"decision must be one of {DECISIONS}")
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p:
        raise HTTPException(404, "Proposal not found")
    nonce = int(uuid.uuid4().int % 10**9)
    typed = build_typed_data(
        proposal_id=p.id, proposal_hash=p.proposal_hash,
        decision=decision, kind=p.kind, expires_at=expires_ts(p), nonce=nonce
    )
    return {"typed_data": typed, "nonce": nonce, "passkey": _passkey_options(typed, db)}

class SignatureRequest(BaseModel):
    decision: str  # APPROVE | REJECT
    signature: str
    comment: str = ""
    nonce: int = 0

@app.post("/proposals/{proposal_id}/signatures")
def submit_signature(proposal_id: str, req: SignatureRequest, db: Session = Depends(get_db)):
    if req.decision not in DECISIONS:
        raise HTTPException(400, f"decision must be one of {DECISIONS}")
    if req.decision == "REJECT" and not req.comment.strip():
        raise HTTPException(400, "A rejection requires a comment")
    p = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    if not p:
        raise HTTPException(404, "Proposal not found")
    if p.status != "PENDING_REVIEW":
        raise HTTPException(409, f"Proposal is {p.status}; only PENDING_REVIEW proposals can be signed")
    if p.expires_at and as_utc(p.expires_at) < dt.datetime.now(dt.UTC):
        raise HTTPException(409, "Proposal has expired")

    # Reconstruct the typed data for verification
    typed = build_typed_data(
        proposal_id=p.id, proposal_hash=p.proposal_hash,
        decision=req.decision, kind=p.kind, expires_at=expires_ts(p), nonce=req.nonce
    )
    approvers_cfg = get_approvers()
    signer = _verify_approver(typed, req.signature, db, approvers_cfg)
    if db.query(Signature).filter(Signature.signature == req.signature).first():
        raise HTTPException(409, "This signature has already been submitted")

    db.add(Signature(
        proposal_id=proposal_id, proposal_hash=p.proposal_hash,
        decision=req.decision, approver=signer, signature=req.signature,
        nonce=str(req.nonce)
    ))
    db.flush()  # make the new signature visible to the threshold count below

    audit_events = []
    if req.decision == "REJECT":
        p.status = "REJECTED"
        audit_events.append(("REJECTION_SIGNED", {"proposal_id": proposal_id, "comment": req.comment}))
        audit_events.append(("STATE_CHANGE", {"proposal_id": proposal_id, "from": "PENDING_REVIEW", "to": "REJECTED"}))
    else:
        approvals = db.query(Signature).filter(Signature.proposal_id == proposal_id, Signature.decision == "APPROVE").all()
        threshold = threshold_for(approvers_cfg, p.kind)
        distinct_signers = {person(s.approver, approvers_cfg) for s in approvals}
        threshold_met = len(distinct_signers) >= threshold
        audit_events.append(("APPROVAL_SIGNED", {"proposal_id": proposal_id, "signers": len(distinct_signers),
                                                 "threshold": threshold, "threshold_met": threshold_met}))
        if threshold_met:
            p.status = "APPROVED"
            audit_events.append(("STATE_CHANGE", {"proposal_id": proposal_id, "from": "PENDING_REVIEW", "to": "APPROVED"}))

    db.commit()
    # append_audit uses its own session, so write after our commit releases the lock
    for event_type, payload in audit_events:
        append_audit(signer, event_type, payload)
    return {"status": p.status, "signer": signer, "message": "Signature recorded"}

# ---------- Ideas (human hypotheses → agent-drafted proposals) ----------

IDEA_MIN_CHARS, IDEA_MAX_CHARS = 15, 2000
IDEA_SIGNATURE_MAX_AGE_S = 600

class IdeaDraft(BaseModel):
    text: str
    evidence_url: str = ""

class IdeaSubmission(IdeaDraft):
    issued_at: int
    signature: str

def _clean_idea(draft: IdeaDraft) -> tuple[str, str]:
    text, url = draft.text.strip(), draft.evidence_url.strip()
    if not IDEA_MIN_CHARS <= len(text) <= IDEA_MAX_CHARS:
        raise HTTPException(400, f"Idea must be {IDEA_MIN_CHARS}-{IDEA_MAX_CHARS} characters")
    if url and not url.startswith(("https://", "http://")):
        raise HTTPException(400, "Evidence URL must start with http:// or https://")
    return text, url

def _idea_json(i: Idea) -> dict:
    return {"id": i.id, "text": i.text, "evidence_url": i.evidence_url, "submitted_by": i.submitted_by,
            "status": i.status, "proposal_id": i.proposal_id, "note": i.note,
            "created_at": i.created_at.isoformat() if i.created_at else "",
            "updated_at": i.updated_at.isoformat() if i.updated_at else ""}

@app.post("/ideas/typed-data")
def idea_typed_data(draft: IdeaDraft, db: Session = Depends(get_db)):
    text, url = _clean_idea(draft)
    issued_at = int(dt.datetime.now(dt.UTC).timestamp())
    typed = build_idea_typed_data(text, url, issued_at)
    return {"typed_data": typed, "issued_at": issued_at, "passkey": _passkey_options(typed, db)}

@app.post("/ideas")
def submit_idea(req: IdeaSubmission, background: BackgroundTasks, db: Session = Depends(get_db)):
    """An approver submits a signed idea; the agent backtests it in the background and drafts a proposal."""
    text, url = _clean_idea(req)
    age = dt.datetime.now(dt.UTC).timestamp() - req.issued_at
    if not 0 <= age <= IDEA_SIGNATURE_MAX_AGE_S:
        raise HTTPException(400, "Signature is too old or from the future; sign again")
    signer = _verify_approver(build_idea_typed_data(text, url, req.issued_at), req.signature, db, get_approvers())
    if db.query(Idea).filter(Idea.signature == req.signature).first():
        raise HTTPException(409, "This signature has already been used")
    # one at a time per approver; a run older than 30 min was lost (e.g. a restart) and no longer blocks
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)
    active = db.query(Idea).filter(Idea.submitted_by == signer, Idea.status.in_(["QUEUED", "PROCESSING"])).all()
    if any(as_utc(i.created_at) > cutoff for i in active):
        raise HTTPException(429, "You already have an idea being processed; wait for it to finish")

    idea = Idea(id=f"idea_{uuid.uuid4().hex[:8]}", text=text, evidence_url=url, submitted_by=signer,
                signature=req.signature, status="QUEUED")
    db.add(idea)
    db.commit()
    append_audit(signer, "IDEA_SUBMITTED", {"idea_id": idea.id, "text": text, "evidence_url": url})

    from trader.agent import pipeline
    background.add_task(pipeline.process_idea, idea.id)
    return _idea_json(idea)

@app.get("/ideas")
def list_ideas(limit: int = 50, db: Session = Depends(get_db)):
    ideas = db.query(Idea).order_by(Idea.created_at.desc()).limit(limit).all()
    return {"ideas": [_idea_json(i) for i in ideas]}

@app.get("/ideas/{idea_id}")
def get_idea(idea_id: str, db: Session = Depends(get_db)):
    i = db.query(Idea).filter(Idea.id == idea_id).first()
    if not i:
        raise HTTPException(404, "Idea not found")
    return _idea_json(i)

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
        # ts and payload_json are the exact strings that were hashed, so a browser can re-verify them
        "seq": e.seq, "ts": ts_string(e.ts),
        "actor": e.actor, "event_type": e.event_type,
        "payload_hash": e.payload_hash, "prev_hash": e.prev_hash,
        "entry_hash": e.entry_hash, "payload_json": e.payload_json, "payload": json.loads(e.payload_json),
    } for e in entries]}

@app.get("/audit/verify")
def verify_audit():
    return verify_chain()

# ---------- Admin / Controls ----------

@app.post("/admin/run-pipeline", dependencies=[Depends(require_admin)])
def run_pipeline_endpoint():
    from trader.agent.pipeline import run_pipeline
    result = run_pipeline()
    return result

class ControlRequest(BaseModel):
    key: str
    value: str

@app.post("/controls", dependencies=[Depends(require_admin)])
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

@app.post("/admin/approvers", dependencies=[Depends(require_admin)])
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

# ---------- Passkeys (no-wallet approvers) ----------

PASSKEY_INVITE_HOURS = 24

class PasskeyInviteRequest(BaseModel):
    name: str

class PasskeyCode(BaseModel):
    code: str

class PasskeyRegistration(PasskeyCode):
    credential: dict

def _open_invite(code: str, db: Session) -> PasskeyInvite:
    inv = db.query(PasskeyInvite).filter(PasskeyInvite.code_hash == sha256(code)).first()
    if not inv or inv.used_at or as_utc(inv.expires_at) < dt.datetime.now(dt.UTC):
        raise HTTPException(404, "This enrollment link is invalid, used or expired; ask an admin for a new one")
    return inv

@app.post("/admin/passkey-invites", dependencies=[Depends(require_admin)])
def create_passkey_invite(req: PasskeyInviteRequest, db: Session = Depends(get_db)):
    """One-time link that lets the named approver register a passkey. Same name as a wallet approver = same person."""
    name = req.name.strip()
    if not name or len(name) > 64 or name == "env":
        raise HTTPException(400, "Name must be 1-64 characters")
    code = uuid.uuid4().hex + uuid.uuid4().hex
    expires = dt.datetime.now(dt.UTC) + dt.timedelta(hours=PASSKEY_INVITE_HOURS)
    db.add(PasskeyInvite(code_hash=sha256(code), name=name, expires_at=expires))
    db.commit()
    append_audit("admin", "PASSKEY_INVITE_CREATED", {"name": name, "expires_at": expires.isoformat()})
    return {"name": name, "enroll_url": f"{settings.WEB_ORIGIN.rstrip('/')}/approvers?code={code}",
            "expires_at": expires.isoformat()}

@app.post("/passkeys/register/options")
def passkey_register_options(req: PasskeyCode, db: Session = Depends(get_db)):
    inv = _open_invite(req.code, db)
    challenge = os.urandom(32)
    inv.challenge = b64url(challenge)
    db.commit()
    existing = [p.credential_id for p in db.query(Passkey).filter(Passkey.name == inv.name).all()]
    try:
        return {"name": inv.name, "options": registration_options(inv.name, challenge, existing)}
    except SignatureError as e:
        raise HTTPException(503, str(e))

@app.post("/passkeys/register")
def passkey_register(req: PasskeyRegistration, db: Session = Depends(get_db)):
    inv = _open_invite(req.code, db)
    if not inv.challenge:
        raise HTTPException(400, "Request registration options first")
    try:
        cred_id, public_key, count = verify_registration(req.credential, from_b64url(inv.challenge))
    except SignatureError as e:
        raise HTTPException(400, str(e))
    if db.query(Passkey).filter(Passkey.credential_id == cred_id).first():
        raise HTTPException(409, "This passkey is already registered")
    db.add(Passkey(credential_id=cred_id, name=inv.name, public_key=public_key, sign_count=count))
    inv.used_at = dt.datetime.now(dt.UTC)
    db.commit()
    # the public key goes into the hash-chained log, so anyone can re-verify this approver's signatures later
    append_audit("admin", "PASSKEY_REGISTERED", {"name": inv.name, "credential_id": cred_id, "public_key": public_key})
    return {"status": "ok", "name": inv.name, "signer": PASSKEY_SIGNER + inv.name}

@app.get("/passkeys")
def list_passkeys(db: Session = Depends(get_db)):
    """Public: public keys are not secrets, and publishing them lets anyone verify passkey approvals."""
    return {"passkeys": [{"name": p.name, "credential_id": p.credential_id, "public_key": p.public_key,
                          "created_at": p.created_at.isoformat() if p.created_at else ""}
                         for p in db.query(Passkey).order_by(Passkey.created_at).all()]}

@app.delete("/admin/passkeys/{credential_id}", dependencies=[Depends(require_admin)])
def revoke_passkey(credential_id: str, db: Session = Depends(get_db)):
    p = db.query(Passkey).filter(Passkey.credential_id == credential_id).first()
    if not p:
        raise HTTPException(404, "Passkey not found")
    db.delete(p)
    db.commit()
    append_audit("admin", "PASSKEY_REVOKED", {"name": p.name, "credential_id": credential_id})
    return {"status": "ok"}

# ---------- Orders (manual execution for testing) ----------

class ExecuteRequest(BaseModel):
    proposal_id: str

@app.post("/admin/execute", dependencies=[Depends(require_admin)])
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
