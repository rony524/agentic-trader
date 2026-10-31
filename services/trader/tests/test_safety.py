"""Safety tests: paper-only guard, no order without approval, rejected → no orders, audit chain."""
import pytest
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Ensure paper mode for tests
os.environ["ALPACA_PAPER"] = "true"

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

def test_no_order_without_approval():
    """Test: executor refuses proposals not in APPROVED status."""
    from trader.store.models import SessionLocal, Proposal, Order, init_db
    init_db()
    db = SessionLocal()
    try:
        p = Proposal(
            id="test_no_approval", kind="rebalance", title="test",
            status="PENDING_REVIEW",
            target_weights={"NVDA": 0.5, "MU": 0.5}
        )
        db.add(p)
        db.commit()
        from trader.execution.executor import execute_approved_proposals
        results = execute_approved_proposals()
        orders = db.query(Order).filter(Order.proposal_id == "test_no_approval").all()
        assert len(orders) == 0
    finally:
        existing = db.query(Proposal).filter(Proposal.id == "test_no_approval").first()
        if existing:
            db.delete(existing)
            db.commit()
        db.close()

def test_rejected_proposal_places_no_orders():
    """Test: rejected proposal results in zero orders."""
    from trader.store.models import SessionLocal, Proposal, Order, init_db
    init_db()
    db = SessionLocal()
    try:
        p = Proposal(
            id="test_rejected", kind="rebalance", title="test",
            status="REJECTED",
            target_weights={"NVDA": 0.5, "MU": 0.5}
        )
        db.add(p)
        db.commit()
        from trader.execution.executor import execute_approved_proposals
        results = execute_approved_proposals()
        orders = db.query(Order).filter(Order.proposal_id == "test_rejected").all()
        assert len(orders) == 0
    finally:
        existing = db.query(Proposal).filter(Proposal.id == "test_rejected").first()
        if existing:
            db.delete(existing)
            db.commit()
        db.close()

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
