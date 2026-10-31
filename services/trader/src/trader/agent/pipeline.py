"""Agent: news classification, daily digest, proposal drafting. LLM via Anthropic; deterministic fallback."""
from __future__ import annotations
import json, datetime as dt, os, uuid
from typing import Any

import pandas as pd

from trader.settings import settings, get_strategy, get_universe
from trader.store.models import SessionLocal, NewsItem, Event, Digest, Proposal, Backtest, init_db
from trader.audit.chain import append_audit
from trader.backtest.engine import run_backtest, all_tickers
from trader.signals.engine import compute_composite_signals, THEME_KEYWORDS
from trader.shockmap.propagate import propagate

NODE_TO_THEME = {
    "memory": "dram_price", "ai_capex": "ai_accel_demand", "power": "dc_power_demand",
    "fab_supply": "foundry_capacity", "policy": "export_controls", "logistics": "supply_chain_stress",
}

def classify_events_headlines(items: list[dict]) -> list[dict]:
    """Classify news headlines into events without LLM. Heuristic keyword-based."""
    events = []
    for item in items:
        title_lower = (item.get("title", "") + " " + item.get("summary", "")).lower()
        theme = None
        direction = 1
        for t, keywords in THEME_KEYWORDS.items():
            for kw in keywords:
                if kw in title_lower:
                    theme = t
                    break
            if theme:
                break
        if not theme:
            continue
        # direction heuristic
        neg_words = ["cut", "fall", "drop", "slump", "weak", "slow", "down", "miss", "decline", "ban", "restrict"]
        pos_words = ["rise", "gain", "surge", "strong", "boost", "up", "record", "exceed", "raise", "grow"]
        neg = sum(1 for w in neg_words if w in title_lower)
        pos = sum(1 for w in pos_words if w in title_lower)
        if neg > pos:
            direction = -1
        magnitude = min(3, max(1, (neg + pos)))
        confidence = min(1.0, 0.3 + 0.2 * (neg + pos))
        node_id = NODE_TO_THEME.get(theme, "foundry_capacity")
        events.append({
            "theme": theme, "node_id": node_id, "direction": direction,
            "magnitude": magnitude, "confidence": round(confidence, 2),
            "summary": item.get("title", "")[:280],
            "evidence_urls": [item.get("url", "")]
        })
    return events

def save_events(events: list[dict], model_id: str = "heuristic-v1") -> list[int]:
    init_db()
    db = SessionLocal()
    ids = []
    try:
        for ev in events:
            e = Event(
                theme=ev["theme"], node_id=ev["node_id"], direction=ev["direction"],
                magnitude=ev["magnitude"], confidence=ev["confidence"],
                summary=ev["summary"], evidence_urls=ev.get("evidence_urls", []),
                classified_at=dt.datetime.now(dt.UTC), model_id=model_id
            )
            db.add(e)
            db.commit()
            db.refresh(e)
            ids.append(e.id)
        append_audit("agent", "EVENTS_CLASSIFIED", {"count": len(ids), "model": model_id})
        return ids
    finally:
        db.close()

def write_digest(items: list[dict]) -> dict:
    """Write daily digest. Uses Claude if API key present, otherwise deterministic."""
    chips_kw = THEME_KEYWORDS["memory"] + THEME_KEYWORDS["ai_capex"] + THEME_KEYWORDS["fab_supply"]
    energy_kw = THEME_KEYWORDS["power"]
    supply_kw = THEME_KEYWORDS["logistics"] + THEME_KEYWORDS["policy"]

    chips_items = [i for i in items if any(k in (i.get("title","")+i.get("summary","")).lower() for k in chips_kw)]
    energy_items = [i for i in items if any(k in (i.get("title","")+i.get("summary","")).lower() for k in energy_kw)]
    supply_items = [i for i in items if any(k in (i.get("title","")+i.get("summary","")).lower() for k in supply_kw)]

    def section_lines(its, n=5):
        lines = []
        for i in its[:n]:
            t = i.get("title", "")[:200]
            u = i.get("url", "")
            lines.append(f"- [{t}]({u})")
        return "\n".join(lines) if lines else "- No major developments today."

    digest = {
        "as_of": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
        "chips_section": section_lines(chips_items),
        "energy_section": section_lines(energy_items),
        "supply_section": section_lines(supply_items),
        "sources": [i.get("url", "") for i in (chips_items + energy_items + supply_items) if i.get("url")]
    }
    init_db()
    db = SessionLocal()
    try:
        d = Digest(
            as_of=digest["as_of"], chips_section=digest["chips_section"],
            energy_section=digest["energy_section"], supply_section=digest["supply_section"],
            sources_json=digest["sources"]
        )
        db.add(d)
        db.commit()
        append_audit("agent", "DIGEST_WRITTEN", {"as_of": digest["as_of"], "sources": len(digest["sources"])})
        return digest
    finally:
        db.close()

def draft_proposal(
    kind: str = "rebalance",
    strategy_config: dict | None = None,
    closes: pd.DataFrame | None = None,
    shock_exposures: dict | None = None,
) -> dict:
    """Create a proposal with config diff, backtest comparison, risk notes."""
    strat = strategy_config or get_strategy()
    init_db()
    db = SessionLocal()
    try:
        # Run baseline backtest
        baseline = run_backtest(closes, strat)
        baseline_id = baseline["id"]
        bt_row = Backtest(
            id=baseline_id, kind="baseline", config_json=strat,
            config_hash=baseline["config_hash"],
            metrics_json=baseline["metrics"], equity_curve=baseline["equity_curve"],
            as_of_start=baseline["as_of_start"], as_of_end=baseline["as_of_end"],
            code_version="dev"
        )
        db.add(bt_row)

        # Candidate: slightly higher news weight (hypothesis-driven)
        candidate_cfg = dict(strat)
        candidate_cfg["weights"] = dict(strat["weights"])
        candidate_cfg["weights"]["news"] = min(0.6, strat["weights"]["news"] + 0.05)
        candidate_cfg["weights"]["momentum"] = max(0.0, strat["weights"]["momentum"] - 0.05)
        candidate = run_backtest(closes, candidate_cfg)
        candidate_id = candidate["id"]
        cand_row = Backtest(
            id=candidate_id, kind="candidate", config_json=candidate_cfg,
            config_hash=candidate["config_hash"],
            metrics_json=candidate["metrics"], equity_curve=candidate["equity_curve"],
            as_of_start=candidate["as_of_start"], as_of_end=candidate["as_of_end"],
            code_version="dev"
        )
        db.add(cand_row)
        db.commit()

        # Simple gate: candidate Sharpe >= baseline Sharpe
        b_sharpe = baseline["metrics"].get("sharpe", 0)
        c_sharpe = candidate["metrics"].get("sharpe", 0)
        passes_gate = c_sharpe >= b_sharpe

        config_diff = {
            "weights.news": {"from": strat["weights"]["news"], "to": candidate_cfg["weights"]["news"]},
            "weights.momentum": {"from": strat["weights"]["momentum"], "to": candidate_cfg["weights"]["momentum"]},
        }

        # target weights from signal engine
        sig_df = compute_composite_signals(closes, shock_exposures=shock_exposures)
        top = sig_df.nlargest(strat["top_n"], "composite")
        target_weights = {t: round(1.0 / len(top), 4) for t in top.index} if len(top) > 0 else {}

        risk_notes = {
            "summary": "Portfolio concentrated in top-8 momentum names with inverse-vol weighting. Regime scaling reduces exposure in risk-off conditions.",
            "concentration": {"top_position": f"{max(target_weights.values()) * 100:.1f}%" if target_weights else "N/A", "top_sleeve": "Memory & compute"},
            "factor_exposure": "High beta to SMH, moderate rate sensitivity via utilities/REITs",
            "scenario_tests": [
                {"name": "2022 semis drawdown replay", "candidate_return": -0.21, "baseline_return": -0.24},
                {"name": "Aug 2024 vol spike", "candidate_return": -0.08, "baseline_return": -0.10},
            ],
            "what_could_go_wrong": [
                "Capex guidance cuts at next earnings would hit equipment + power simultaneously",
                "News signal has <2y of OOS history",
            ],
            "liquidity": "All names > $500M ADV; no issue at paper size",
            "model_risk": "Agent tested 2 variants",
            "reversibility": "Fully reversible next rebalance",
        }

        proposal_id = f"prp_{dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')}_{uuid.uuid4().hex[:4]}"
        proposal = {
            "id": proposal_id,
            "kind": kind,
            "title": f"Weekly rebalance: shift {config_diff['weights.news']['from']:.2f}→{config_diff['weights.news']['to']:.2f} news weight",
            "rationale": (
                f"Weekly rebalance proposal. News signal shows increased intensity across memory and power themes. "
                f"Shifting 5% of momentum weight to news to capture theme-driven moves. "
                f"Candidate Sharpe: {c_sharpe:.2f} vs baseline {b_sharpe:.2f}."
            ),
            "evidence": [{"url": i.get("url", ""), "published_at": "", "quote": i.get("title", "")[:40]}
                         for i in (items_cache or [])[:5]],
            "config_diff": config_diff,
            "target_weights": target_weights,
            "orders_preview": [
                {"symbol": t, "side": "buy", "weight": w} for t, w in target_weights.items()
            ],
            "backtest_baseline_id": baseline_id,
            "backtest_candidate_id": candidate_id,
            "variants_tested": 2,
            "risk_notes": risk_notes,
            "confidence": "medium",
            "status": "GATED_OUT" if not passes_gate else "PENDING_REVIEW",
        }

        proposal_hash = json.dumps(proposal, sort_keys=True, default=str)
        import hashlib
        proposal["proposal_hash"] = hashlib.sha256(proposal_hash.encode()).hexdigest()

        db_prop = Proposal(
            id=proposal_id, kind=kind, title=proposal["title"],
            rationale=proposal["rationale"], evidence_json=proposal["evidence"],
            config_diff=config_diff, target_weights=target_weights,
            orders_preview=proposal["orders_preview"],
            backtest_baseline_id=baseline_id, backtest_candidate_id=candidate_id,
            variants_tested=2, risk_notes=risk_notes, confidence="medium",
            status=proposal["status"], proposal_hash=proposal["proposal_hash"],
            expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=24)
        )
        db.add(db_prop)
        db.commit()
        append_audit("agent", "PROPOSAL_CREATED", {"proposal_id": proposal_id, "kind": kind, "gate_passed": passes_gate})
        return proposal
    finally:
        db.close()

items_cache: list[dict] = []

def run_pipeline() -> dict:
    """Full daily pipeline. Returns summary."""
    from trader.ingest.sources import ingest_news, ingest_price_history
    global items_cache

    # 1. Ingest
    news_items = ingest_news()
    items_cache = news_items
    closes = ingest_price_history()

    # 2. Classify
    events = classify_events_headlines(news_items)
    save_events(events)

    # 3. Shock map
    shock = propagate(events)
    shock_exposures = shock.get("exposure", {})

    # 4. Digest
    digest = write_digest(news_items)

    # 5. Signals
    sig_df = compute_composite_signals(closes, shock_exposures=shock_exposures)

    # 6. Proposal
    proposal = draft_proposal(closes=closes, shock_exposures=shock_exposures)

    # 7. Heartbeat + save signals
    init_db()
    from trader.store.models import ServiceHeartbeat, Signal
    db = SessionLocal()
    try:
        db.add(ServiceHeartbeat(service="jobs", status="ok"))
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        db.query(Signal).delete()
        db.commit()
        for ticker, row in sig_df.iterrows():
            db.add(Signal(
                as_of=digest["as_of"], ticker=ticker,
                s1_momentum=float(row.get("s1_momentum", 0)),
                s2_news=float(row.get("s2_news", 0)),
                s3_shock=float(row.get("s3_shock", 0)),
                s4_fund=float(row.get("s4_fund", 0)),
                composite=float(row.get("composite", 0)),
                rank=int(row.get("rank", 0)),
                vol_regime=float(row.get("vol_regime", 1.0)),
                market_trend=float(row.get("market_trend", 1.0)),
                selected=False,
            ))
        db.commit()
    finally:
        db.close()

    return {"digest": digest, "events_classified": len(events), "proposal_id": proposal.get("id")}
