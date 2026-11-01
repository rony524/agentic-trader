"""Hash-chained audit log."""
from __future__ import annotations
import hashlib, json, datetime as dt
from trader.store.models import AuditLog, SessionLocal, init_db

def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def ts_string(ts: dt.datetime | None) -> str:
    """The exact timestamp text that goes into an entry's hash (the DB may hand back a naive datetime)."""
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00" if ts else ""

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
        ts_str = ts_string(now)
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
            ts_str = ts_string(e.ts)
            if sha256(e.payload_json) != e.payload_hash:
                return {"valid": False, "broken_at_seq": e.seq, "count": len(entries)}
            recomputed = compute_entry_hash(
                e.seq, ts_str, e.actor, e.event_type, e.payload_hash, expected_prev
            )
            if recomputed != e.entry_hash:
                return {"valid": False, "broken_at_seq": e.seq, "count": len(entries)}
            prev_hash = e.entry_hash
        return {"valid": True, "count": len(entries)}
    finally:
        db.close()
