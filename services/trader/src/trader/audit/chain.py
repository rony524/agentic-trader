"""Hash-chained audit log."""
from __future__ import annotations
import hashlib, json, datetime as dt
from trader.store.models import AuditLog, SessionLocal, init_db

def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def compute_entry_hash(seq: int, ts: str, actor: str, event_type: str, payload_hash: str, prev_hash: str) -> str:
    return sha256(f"{seq}|{ts}|{actor}|{event_type}|{payload_hash}|{prev_hash}")

def append_audit(actor: str, event_type: str, payload: dict) -> AuditLog:
    init_db()
    db = SessionLocal()
    try:
        last = db.query(AuditLog).order_by(AuditLog.seq.desc()).first()
        prev_hash = last.entry_hash if last else ""
        next_seq = (last.seq + 1) if last else 1
        payload_json = canonical_json(payload)
        payload_hash = sha256(payload_json)
        now = dt.datetime.now(dt.UTC)
        # Use a fixed-format string for the hash so it's reproducible
        ts_str = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"
        entry_hash = compute_entry_hash(next_seq, ts_str, actor, event_type, payload_hash, prev_hash)
        entry = AuditLog(
            seq=next_seq, ts=now, actor=actor,
            event_type=event_type, payload_json=payload_json,
            payload_hash=payload_hash, prev_hash=prev_hash, entry_hash=entry_hash
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
    finally:
        db.close()

def verify_chain(limit: int = 1000) -> dict:
    init_db()
    db = SessionLocal()
    try:
        entries = db.query(AuditLog).order_by(AuditLog.seq.asc()).limit(limit).all()
        if not entries:
            return {"valid": True, "count": 0}
        prev_hash = ""
        for e in entries:
            expected_prev = prev_hash
            # Reconstruct the same ts string format used during append
            ts_str = e.ts.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00" if e.ts else ""
            recomputed = compute_entry_hash(
                e.seq, ts_str, e.actor, e.event_type, e.payload_hash, expected_prev
            )
            if recomputed != e.entry_hash:
                return {"valid": False, "broken_at_seq": e.seq, "count": len(entries)}
            prev_hash = e.entry_hash
        return {"valid": True, "count": len(entries)}
    finally:
        db.close()
