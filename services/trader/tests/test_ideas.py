"""Human ideas: sleeve tilts, idea → candidate mapping, signed submission, and idea → hypothesis proposal."""
import copy, datetime as dt
import numpy as np
import pandas as pd
import pytest

from trader.agent.pipeline import apply_changes, keyword_idea_candidates, process_idea
from trader.backtest.engine import target_weights_as_of, all_tickers, sleeve_map
from trader.settings import get_strategy, get_risk, settings

POWER = "sleeve_tilts.Power & grid"

@pytest.fixture(scope="module")
def closes():
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2019-01-01", periods=700)
    tickers = all_tickers() + ["SPY"]
    rets = rng.normal(rng.normal(0.0004, 0.0004, len(tickers)), 0.02, (len(dates), len(tickers)))
    return pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=tickers)

@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_ENABLED", False)

def _api():
    from fastapi.testclient import TestClient
    from trader.api.main import app
    return TestClient(app)

# ---------- tilts ----------

def test_tilt_changes_are_bounded():
    strat = get_strategy()
    assert apply_changes(strat, {POWER: 0.5})["sleeve_tilts"]["Power & grid"] == 0.5
    assert apply_changes(strat, {POWER: 0.0}) is None  # step > 0.5
    assert apply_changes(strat, {POWER: 2.0}) is None  # above max
    assert apply_changes(strat, {"sleeve_tilts.Cash proxy": 0.5}) is None  # cash is not tiltable

def test_tilt_works_on_configs_without_tilts():
    strat = copy.deepcopy(get_strategy())
    strat.pop("sleeve_tilts", None)
    assert apply_changes(strat, {POWER: 0.5})["sleeve_tilts"] == {"Power & grid": 0.5}

def test_zero_tilt_removes_sleeve_and_overweight_adds_no_leverage(closes):
    smap, strat = sleeve_map(), copy.deepcopy(get_strategy())
    strat["sleeve_tilts"] = {s: 0.0 for s in strat["sleeve_tilts"]}
    strat["sleeve_tilts"]["Memory & compute"] = 1.0
    w = target_weights_as_of(closes, strat)
    assert all(smap[t] == "Memory & compute" for t in w)

    strat["sleeve_tilts"] = {s: 1.5 for s in strat["sleeve_tilts"]}
    w = target_weights_as_of(closes, strat)
    assert sum(w.values()) <= strat["base_exposure"] + 1e-9
    assert max(w.values()) <= get_risk()["limits"]["max_single_position"] + 1e-9

# ---------- keyword fallback ----------

def test_keyword_fallback_maps_sleeve_and_direction():
    strat = get_strategy()
    down = keyword_idea_candidates("Reduce power and grid exposure, utilities look stretched", strat)
    assert down and down[0]["changes"] == {POWER: 0.5}
    up = keyword_idea_candidates("Overweight memory, HBM pricing is tight", strat)
    assert up[0]["changes"] == {"sleeve_tilts.Memory & compute": 1.5}

def test_keyword_fallback_refuses_ambiguous_ideas():
    strat = get_strategy()
    assert keyword_idea_candidates("Something about power", strat) == []  # no direction
    assert keyword_idea_candidates("Cut power, add memory", strat) == []  # both directions

# ---------- submission ----------

def test_idea_validation_and_garbage_signature():
    api = _api()
    assert api.post("/ideas/typed-data", json={"text": "too short"}).status_code == 400
    assert api.post("/ideas/typed-data", json={"text": "Reduce power exposure now", "evidence_url": "ftp://x"}).status_code == 400
    now = int(dt.datetime.now(dt.UTC).timestamp())
    r = api.post("/ideas", json={"text": "Reduce power exposure now", "issued_at": now, "signature": "0xdeadbeef"})
    assert r.status_code == 400
    r = api.post("/ideas", json={"text": "Reduce power exposure now", "issued_at": now - 3600, "signature": "0xdeadbeef"})
    assert r.status_code == 400 and "too old" in r.text

def _signed(acct, text, url=""):
    from eth_account.messages import encode_typed_data
    from eth_account import Account
    td = _api().post("/ideas/typed-data", json={"text": text, "evidence_url": url}).json()
    sig = "0x" + Account.sign_message(encode_typed_data(full_message=td["typed_data"]), acct.key).signature.hex().removeprefix("0x")
    return {"text": text, "evidence_url": url, "issued_at": td["issued_at"], "signature": sig}

def test_only_registered_approvers_can_submit(monkeypatch):
    pytest.importorskip("eth_account")
    from eth_account import Account
    from trader.agent import pipeline
    calls = []
    monkeypatch.setattr(pipeline, "process_idea", lambda idea_id: calls.append(idea_id))
    approver, stranger = Account.create(), Account.create()
    monkeypatch.setenv("APPROVER_ADDRESSES", approver.address)
    api = _api()

    assert api.post("/ideas", json=_signed(stranger, "Reduce power exposure now")).status_code == 403
    body = _signed(approver, "Reduce power exposure now")
    r = api.post("/ideas", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "QUEUED" and calls == [r.json()["id"]]
    assert api.post("/ideas", json=body).status_code == 409  # replay
    assert api.post("/ideas", json=_signed(approver, "Overweight memory names")).status_code == 429  # one at a time

    tampered = _signed(approver, "Reduce power exposure now")
    tampered["text"] = "Exit every sleeve immediately"
    r = api.post("/ideas", json=tampered)
    assert r.status_code in (403, 429)  # recovers a different signer, so it is never attributed to the approver

# ---------- processing ----------

def _queue_idea(text):
    from trader.store.models import SessionLocal, Idea, init_db
    import uuid
    init_db()
    db = SessionLocal()
    iid = f"idea_test_{uuid.uuid4().hex[:6]}"
    db.add(Idea(id=iid, text=text, submitted_by="0xabc", signature=iid, status="QUEUED"))
    db.commit()
    db.close()
    return iid

def _idea(iid):
    from trader.store.models import SessionLocal, Idea
    db = SessionLocal()
    try:
        return db.query(Idea).filter(Idea.id == iid).first()
    finally:
        db.close()

def test_idea_becomes_pending_hypothesis_proposal(closes):
    from trader.store.models import SessionLocal, Proposal
    iid = _queue_idea("Reduce power and grid exposure, utilities look stretched")
    process_idea(iid, closes=closes)
    idea = _idea(iid)
    assert idea.status == "PROPOSED", idea.note
    db = SessionLocal()
    try:
        p = db.query(Proposal).filter(Proposal.id == idea.proposal_id).first()
    finally:
        db.close()
    assert p.kind == "hypothesis" and p.status == "PENDING_REVIEW"  # still needs a signed human approval
    assert p.config_diff == {POWER: {"from": 1.0, "to": 0.5}}
    assert iid in p.risk_notes["origin"]
    if not p.risk_notes["gate_passed"]:
        assert p.confidence == "low"

def test_unmappable_idea_gets_no_proposal(closes):
    iid = _queue_idea("I have a feeling about the market this week")
    process_idea(iid, closes=closes)
    idea = _idea(iid)
    assert idea.status == "NO_PROPOSAL" and idea.proposal_id is None
