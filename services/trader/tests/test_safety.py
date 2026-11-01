"""Safety tests: paper-only guard, no order without verified approval, admin auth, audit chain.

conftest.py points these at a throwaway DB."""
import pytest

from trader.execution.executor import PaperOnlyViolation, assert_paper_only, PAPER_BASE_URL
from trader.settings import settings

def test_startup_fails_if_not_paper():
    """Test: if ALPACA_PAPER is not true, assertion raises."""
    original = settings.ALPACA_PAPER
    settings.ALPACA_PAPER = False
    with pytest.raises(PaperOnlyViolation):
        assert_paper_only()
    settings.ALPACA_PAPER = original

def test_paper_only_guard():
    """Test: paper-only guard passes when configured correctly."""
    settings.ALPACA_PAPER = True
    assert_paper_only()  # should not raise

def test_no_live_endpoint_in_code():
    """Test: live Alpaca endpoint is not used in execution code."""
    import pathlib
    src_dir = pathlib.Path(__file__).parent.parent / "src" / "trader"
    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text()
        if "api.alpaca.markets" in content and "paper" not in content.split("api.alpaca.markets")[0][-50:]:
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if "api.alpaca.markets" in line and "paper" not in line and "#" not in line[:line.index("api.alpaca.markets")]:
                    if "LIVE_BASE_URL" in line or "forbidden" in line.lower():
                        continue
                    raise AssertionError(f"Live endpoint found in {py_file}:{i+1}: {line}")

class FakeClient:
    """Stands in for alpaca TradingClient and records every order it is asked to place."""
    def __init__(self):
        self.submitted = []
    def get_account(self):
        return type("Acct", (), {"equity": "100000"})()
    def get_all_positions(self):
        return []
    def submit_order(self, req):
        self.submitted.append(req)
        return type("O", (), {"id": f"fake-{len(self.submitted)}", "status": "accepted"})()

def _make_proposal(pid, status):
    import datetime as dt
    from trader.store.models import SessionLocal, Proposal, Order, Signature, init_db
    init_db()
    db = SessionLocal()
    for model in (Order, Signature):
        db.query(model).filter(model.proposal_id == pid).delete()
    db.query(Proposal).filter(Proposal.id == pid).delete()
    db.add(Proposal(
        id=pid, kind="rebalance", title="test", status=status, proposal_hash="ab" * 32,
        target_weights={"NVDA": 0.5, "MU": 0.5},
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    ))
    db.commit()
    db.close()

def _orders_for(pid):
    from trader.store.models import SessionLocal, Order
    db = SessionLocal()
    try:
        return db.query(Order).filter(Order.proposal_id == pid).all()
    finally:
        db.close()

def _status(pid):
    from trader.store.models import SessionLocal, Proposal
    db = SessionLocal()
    try:
        return db.query(Proposal).filter(Proposal.id == pid).first().status
    finally:
        db.close()

@pytest.mark.parametrize("status", ["PENDING_REVIEW", "REJECTED"])
def test_unapproved_proposal_places_no_orders(status):
    """Test: pending or rejected proposals never reach the broker."""
    from trader.execution.executor import execute_approved_proposals
    pid = f"test_{status.lower()}"
    _make_proposal(pid, status)
    client = FakeClient()
    execute_approved_proposals(client=client)
    assert client.submitted == []
    assert _orders_for(pid) == []
    assert _status(pid) == status

def test_approved_status_without_valid_signature_places_no_orders():
    """Test: the executor re-verifies signatures; an APPROVED status set by anything else is not enough."""
    from trader.execution.executor import execute_approved_proposals
    pid = "test_forged_status"
    _make_proposal(pid, "APPROVED")
    client = FakeClient()
    execute_approved_proposals(client=client)
    assert client.submitted == []
    assert _orders_for(pid) == []
    assert _status(pid) == "FAILED"

def test_verified_approval_submits_and_records_orders(monkeypatch):
    """Test: once approvals verify, orders are submitted and saved with their Alpaca IDs."""
    from trader.execution import executor
    monkeypatch.setattr(executor, "verify_approvals", lambda db, prop: (True, ""))
    pid = "test_verified"
    _make_proposal(pid, "APPROVED")
    client = FakeClient()
    executor.execute_approved_proposals(client=client)
    orders = _orders_for(pid)
    assert {o.symbol for o in orders} == {"NVDA", "MU"}
    assert all(o.alpaca_order_id.startswith("fake-") for o in orders)
    assert _status(pid) == "EXECUTED"

def test_frozen_trading_places_no_orders(monkeypatch):
    from trader.execution import executor
    monkeypatch.setattr(executor, "verify_approvals", lambda db, prop: (True, ""))
    monkeypatch.setattr(executor, "is_trading_frozen", lambda db: True)
    pid = "test_frozen"
    _make_proposal(pid, "APPROVED")
    client = FakeClient()
    executor.execute_approved_proposals(client=client)
    assert client.submitted == []

def _api():
    from fastapi.testclient import TestClient
    from trader.api.main import app
    return TestClient(app)

def test_garbage_signature_is_rejected():
    pid = "test_garbage_sig"
    _make_proposal(pid, "PENDING_REVIEW")
    api = _api()
    for _ in range(2):  # twice: a repeated forgery must not reach the threshold either
        r = api.post(f"/proposals/{pid}/signatures", json={"decision": "APPROVE", "signature": "not-a-signature", "nonce": 1})
        assert r.status_code in (400, 403)
    assert _status(pid) == "PENDING_REVIEW"

@pytest.mark.parametrize("method,path,body", [
    ("post", "/admin/run-pipeline", None),
    ("post", "/admin/approvers", {"name": "x", "address": "0x0000000000000000000000000000000000000000"}),
    ("post", "/controls", {"key": "trading_frozen", "value": "false"}),
    ("post", "/admin/execute", {"proposal_id": "x"}),
])
def test_admin_endpoints_require_token(method, path, body):
    api = _api()
    assert getattr(api, method)(path, json=body).status_code == 403
    assert getattr(api, method)(path, json=body, headers={"X-Admin-Token": "wrong"}).status_code == 403

def test_real_signature_round_trip(monkeypatch):
    """Test: a wallet signature from a registered approver approves; the executor accepts it. Needs eth-account."""
    pytest.importorskip("eth_account")
    from eth_account import Account
    from eth_account.messages import encode_typed_data
    from trader.execution import executor
    acct = Account.create()
    monkeypatch.setenv("APPROVER_ADDRESSES", acct.address)
    pid = "test_real_sig"
    _make_proposal(pid, "PENDING_REVIEW")
    api = _api()
    td = api.get(f"/proposals/{pid}/typed-data", params={"decision": "APPROVE"}).json()
    sig = "0x" + Account.sign_message(encode_typed_data(full_message=td["typed_data"]), acct.key).signature.hex().removeprefix("0x")
    r = api.post(f"/proposals/{pid}/signatures", json={"decision": "APPROVE", "signature": sig, "nonce": td["nonce"]})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APPROVED"
    client = FakeClient()
    executor.execute_approved_proposals(client=client)
    assert len(client.submitted) == 2

def test_audit_chain_detects_tampering():
    """Test: audit chain verification detects modified entries."""
    # Use a fresh DB for this test to avoid interference
    from trader.store.models import Base, engine, AuditLog, SessionLocal
    from trader.audit.chain import append_audit, verify_chain, compute_entry_hash
    import sqlalchemy
    # Create all tables fresh
    Base.metadata.create_all(engine)
    # Clean existing audit entries
    db = SessionLocal()
    db.query(AuditLog).delete()
    db.commit()
    db.close()

    entry1 = append_audit("test", "TEST_EVENT_1", {"data": "original"})
    result = verify_chain()
    assert result["valid"] == True, f"Chain should be valid but got: {result}"
    # Tamper with the entry
    db = SessionLocal()
    try:
        entry = db.query(AuditLog).filter(AuditLog.seq == entry1.seq).first()
        entry.payload_json = '{"data": "tampered"}'
        entry.payload_hash = "different_hash"
        db.commit()
        result = verify_chain()
        assert result["valid"] == False, "Chain should be invalid after tampering"
        assert "broken_at_seq" in result
    finally:
        db.query(AuditLog).filter(AuditLog.seq == entry1.seq).delete()
        db.commit()
        db.close()

def test_audit_api_entries_verify_like_the_browser():
    """Replays the /audit page's in-browser check: hash the returned strings, compare, follow the chain."""
    import hashlib
    from trader.audit.chain import append_audit
    append_audit("test", "UNICODE", {"title": "SK Hynix’s record — profits"})
    append_audit("test", "PLAIN", {"n": 1})
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
    prev = ""
    entries = _api().get("/audit", params={"limit": 1000}).json()["entries"]
    assert entries
    for e in entries:
        assert sha(e["payload_json"]) == e["payload_hash"]
        assert sha(f'{e["seq"]}|{e["ts"]}|{e["actor"]}|{e["event_type"]}|{e["payload_hash"]}|{prev}') == e["entry_hash"]
        prev = e["entry_hash"]
