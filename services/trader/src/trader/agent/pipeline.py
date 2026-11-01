"""Daily pipeline (06_AGENT): code drives, the LLM is called at fixed steps (see agent/llm.py).

ingest → classify events → shock map → digest → signals → baseline backtest → candidates → gate → proposal.
Every LLM step has a deterministic fallback so a run always completes.
"""
from __future__ import annotations
import copy, datetime as dt, hashlib, json, uuid

import pandas as pd

from trader.settings import get_strategy, get_shockmap
from trader.store.models import SessionLocal, Event, Digest, Proposal, Backtest, Signal, ServiceHeartbeat, Idea, init_db
from trader.audit.chain import append_audit
from trader.backtest.engine import run_backtest, target_weights_as_of, sleeve_map, CASH_TICKER
from trader.signals.engine import compute_composite_signals, THEME_KEYWORDS
from trader.shockmap.propagate import propagate
from trader.agent import llm

NODE_TO_THEME = {
    "memory": "dram_price", "ai_capex": "ai_accel_demand", "power": "dc_power_demand",
    "fab_supply": "foundry_capacity", "policy": "export_controls", "logistics": "supply_chain_stress",
}

# 05_STRATEGY_SPEC bounds for the parameters the backtest can evaluate: path -> (min, max, max change)
TUNABLE = {
    "top_n": (4, 12, 2),
    "hold_buffer": (0, 5, 2),
    "lookbacks.mom_short_days": (21, 126, 21),
    "lookbacks.vol_days": (20, 120, 20),
    "regime.vol_threshold": (1.2, 2.0, 0.2),
}
# per-sleeve weight multipliers: 0 = exit the sleeve, 1.5 = overweight (still capped by risk limits)
TILT_SLEEVES = [s for s in dict.fromkeys(sleeve_map().values()) if s != sleeve_map().get(CASH_TICKER)]
TUNABLE.update({f"sleeve_tilts.{s}": (0.0, 1.5, 0.5) for s in TILT_SLEEVES})
INT_PARAMS = {"top_n", "hold_buffer", "lookbacks.mom_short_days", "lookbacks.vol_days"}
MAX_DD_TOLERANCE = 0.02  # candidate test-window drawdown may be at most 2 pp worse than baseline

# ---------- events ----------

def classify_events_headlines(items: list[dict]) -> list[dict]:
    """Keyword fallback when the LLM is unavailable."""
    events = []
    for item in items:
        text = (item.get("title", "") + " " + item.get("summary", "")).lower()
        theme = next((t for t, kws in THEME_KEYWORDS.items() if any(kw in text for kw in kws)), None)
        if not theme:
            continue
        neg_words = ["cut", "fall", "drop", "slump", "weak", "slow", "down", "miss", "decline", "ban", "restrict"]
        pos_words = ["rise", "gain", "surge", "strong", "boost", "up", "record", "exceed", "raise", "grow"]
        neg = sum(1 for w in neg_words if w in text)
        pos = sum(1 for w in pos_words if w in text)
        events.append({
            "theme": theme, "node_id": NODE_TO_THEME[theme], "direction": -1 if neg > pos else 1,
            "magnitude": min(3, max(1, neg + pos)), "confidence": round(min(1.0, 0.3 + 0.2 * (neg + pos)), 2),
            "summary": item.get("title", "")[:280], "evidence_urls": [item.get("url", "")],
        })
    return events

def save_events(events: list[dict], model_id: str) -> None:
    init_db()
    db = SessionLocal()
    try:
        for ev in events:
            db.add(Event(
                theme=ev["theme"], node_id=ev["node_id"], direction=ev["direction"],
                magnitude=ev["magnitude"], confidence=ev["confidence"], summary=ev["summary"],
                evidence_urls=ev.get("evidence_urls", []), classified_at=dt.datetime.now(dt.UTC), model_id=model_id,
            ))
        db.commit()
    finally:
        db.close()
    append_audit("agent", "EVENTS_CLASSIFIED", {"count": len(events), "model": model_id})

# ---------- digest ----------

def _keyword_digest(items: list[dict]) -> dict[str, list[tuple[str, int]]]:
    groups = {
        "chips": THEME_KEYWORDS["memory"] + THEME_KEYWORDS["ai_capex"] + THEME_KEYWORDS["fab_supply"],
        "energy": THEME_KEYWORDS["power"],
        "supply": THEME_KEYWORDS["logistics"] + THEME_KEYWORDS["policy"],
    }
    out = {}
    for section, kws in groups.items():
        hits = [i for i, it in enumerate(items) if any(k in (it.get("title", "") + it.get("summary", "")).lower() for k in kws)]
        out[section] = [(items[i]["title"][:200], i) for i in hits[:5]]
    return out

def write_digest(items: list[dict]) -> dict:
    sections = llm.write_digest(items)
    model = llm.MODELS["digest"] if sections is not None else "keyword-v1"
    sections = sections or _keyword_digest(items)

    def render(bullets):
        return "\n".join(f"- [{text}]({items[i]['url']})" for text, i in bullets) or "- No major developments today."

    used = sorted({i for bullets in sections.values() for _, i in bullets})
    digest = {
        "as_of": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
        "chips_section": render(sections["chips"]),
        "energy_section": render(sections["energy"]),
        "supply_section": render(sections["supply"]),
        "sources": [items[i]["url"] for i in used],
    }
    init_db()
    db = SessionLocal()
    try:
        db.add(Digest(as_of=digest["as_of"], chips_section=digest["chips_section"],
                      energy_section=digest["energy_section"], supply_section=digest["supply_section"],
                      sources_json=digest["sources"]))
        db.commit()
    finally:
        db.close()
    append_audit("agent", "DIGEST_WRITTEN", {"as_of": digest["as_of"], "sources": len(digest["sources"]), "model": model})
    return digest

# ---------- proposal ----------

def _get(cfg: dict, path: str):
    for key in path.split("."):
        if key not in cfg and path.startswith("sleeve_tilts."):
            return 1.0  # configs written before tilts existed are neutral
        cfg = cfg[key]
    return cfg

def apply_changes(strat: dict, changes: dict[str, float]) -> dict | None:
    """Apply a candidate's changes, or return None if any change is outside 05_STRATEGY_SPEC bounds."""
    if not changes:
        return None
    cfg = copy.deepcopy(strat)
    for path, value in changes.items():
        if path not in TUNABLE:
            return None
        lo, hi, step = TUNABLE[path]
        old = _get(strat, path)
        if path in INT_PARAMS:
            value = int(round(value))
        if not (lo <= value <= hi) or abs(value - old) > step + 1e-9 or value == old:
            return None
        *parents, leaf = path.split(".")
        target = cfg
        for key in parents:
            target = target.setdefault(key, {})
        target[leaf] = value
    return cfg

def _fallback_candidates(strat: dict) -> list[dict]:
    """Deterministic candidates when the LLM is unavailable: one step each way on the main knobs."""
    out = []
    for path, delta in (("top_n", -2), ("top_n", 2), ("lookbacks.mom_short_days", -21)):
        out.append({"changes": {path: _get(strat, path) + delta},
                    "rationale": f"Sensitivity check: {path} {'+' if delta > 0 else ''}{delta}.", "article_indexes": []})
    return out

def _flat_metrics(bt: dict) -> dict:
    m = dict(bt["metrics"])
    for k in ("sharpe", "cagr", "max_drawdown"):
        m[f"test_{k}"] = bt["metrics_test"][k]
    return m

def _save_backtest(db, bt: dict, kind: str, cfg: dict) -> None:
    db.add(Backtest(
        id=bt["id"], kind=kind, config_json=cfg, config_hash=bt["config_hash"],
        metrics_json=_flat_metrics(bt), equity_curve=bt["equity_curve"],
        as_of_start=bt["as_of_start"], as_of_end=bt["as_of_end"], code_version="dev",
    ))

def passes_gate(cand: dict, base: dict) -> bool:
    c, b = cand["metrics_test"], base["metrics_test"]
    return c["sharpe"] > b["sharpe"] and c["max_drawdown"] >= b["max_drawdown"] - MAX_DD_TOLERANCE

def _test_candidates(db, closes: pd.DataFrame, strat: dict, raw: list[dict], baseline: dict) -> list[tuple]:
    """Backtest each in-bounds candidate. Returns (candidate, config, backtest, passed_gate) tuples."""
    tested = []
    for cand in raw[:3]:
        cfg = apply_changes(strat, cand["changes"])
        if cfg is None:
            append_audit("agent", "CANDIDATE_REJECTED", {"changes": cand["changes"], "reason": "out of bounds"})
            continue
        bt = run_backtest(closes, cfg)
        _save_backtest(db, bt, "candidate", cfg)
        tested.append((cand, cfg, bt, passes_gate(bt, baseline)))
    db.commit()
    return tested

def _finalize_proposal(db, *, kind: str, strat: dict, closes: pd.DataFrame, sig_df: pd.DataFrame,
                       baseline: dict, tested: list[tuple], best: tuple | None, gate_passed: bool,
                       evidence: list[dict], proposer: str, context_extra: dict,
                       fallback_title: str, fallback_rationale: str, origin: str | None = None) -> dict:
    """Target weights, risk notes, text and hash for the chosen candidate (or the unchanged baseline); saves the proposal."""
    chosen_cfg = best[1] if best else strat
    chosen_bt = best[2] if best else None

    # live targets: price score from the chosen config + today's news/shock component
    extra = sig_df["s2_news"] * strat["weights"]["news"] + sig_df["s3_shock"] * strat["weights"]["shock"]
    target_weights = {t: round(w, 4) for t, w in target_weights_as_of(closes, chosen_cfg, extra_scores=extra).items()}

    config_diff = {p: {"from": _get(strat, p), "to": v} for p, v in best[0]["changes"].items()} if best else None
    smap = sleeve_map()
    sleeves: dict[str, float] = {}
    for t, w in target_weights.items():
        sleeves[smap.get(t, "")] = sleeves.get(smap.get(t, ""), 0) + w
    top_sleeve = max(sleeves, key=sleeves.get) if sleeves else "N/A"
    gross = sum(target_weights.values())

    context = {
        **context_extra,
        "config_change": config_diff,
        "candidate_hypothesis": best[0]["rationale"] if best else None,
        "candidates_tested": [{"changes": c["changes"], "passed_gate": ok, "test_sharpe": bt["metrics_test"]["sharpe"]}
                              for c, _, bt, ok in tested],
        "chosen_candidate_passed_gate": gate_passed,
        "baseline_metrics": _flat_metrics(baseline),
        "candidate_metrics": _flat_metrics(chosen_bt) if chosen_bt else None,
        "target_weights": target_weights, "gross_exposure": round(gross, 3), "top_sleeve": top_sleeve,
        "evidence_titles": [e["quote"] for e in evidence],
    }
    text = llm.draft_proposal_text(context)
    if text is None:
        title, rationale = fallback_title, fallback_rationale
        what_could_go_wrong = [
            "Momentum reverses sharply (e.g. an AI capex pullback hits semis and power together).",
            "News/shock signals have no out-of-sample history yet; their weight is unvalidated.",
            "The universe was chosen with hindsight, so the backtest overstates what was knowable.",
        ]
        risk_summary, confidence = f"{len(target_weights)} positions, {gross:.0%} gross, largest sleeve {top_sleeve}.", "medium"
    else:
        title, rationale = text.title, text.rationale
        what_could_go_wrong, risk_summary, confidence = text.what_could_go_wrong, text.risk_summary, text.confidence
    if best and not gate_passed:
        # a change that lost to the baseline on the test window is never presented with more than low confidence
        confidence = "low"
        what_could_go_wrong = ["This change did NOT beat the baseline on the out-of-sample test window."] + list(what_could_go_wrong)

    risk_notes = {
        "summary": risk_summary,
        "concentration": {"top_position": f"{max(target_weights.values()) * 100:.1f}%" if target_weights else "N/A",
                          "top_sleeve": f"{top_sleeve} ({sleeves.get(top_sleeve, 0) * 100:.1f}%)" if sleeves else "N/A"},
        "gross_exposure": f"{gross * 100:.1f}% invested, {(1 - gross) * 100:.1f}% cash",
        "what_could_go_wrong": what_could_go_wrong,
        "gate_passed": gate_passed,
        "model_risk": f"{len(tested)} variants tested by {proposer}; universe chosen with hindsight (selection bias).",
        "reversibility": "Fully reversible at the next weekly rebalance.",
    }
    if origin:
        risk_notes["origin"] = origin

    proposal_id = f"prp_{dt.datetime.now(dt.UTC).strftime('%Y-%m-%d')}_{uuid.uuid4().hex[:4]}"
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(hours=48)
    body = {
        "id": proposal_id, "kind": kind, "title": title, "rationale": rationale,
        "evidence": evidence, "config_diff": config_diff, "target_weights": target_weights,
        "orders_preview": [{"symbol": t, "side": "buy", "weight": w} for t, w in target_weights.items()],
        "backtest_baseline_id": baseline["id"],
        "backtest_candidate_id": chosen_bt["id"] if chosen_bt else None,
        "variants_tested": len(tested), "risk_notes": risk_notes, "confidence": confidence,
        "expires_at": expires_at.isoformat(),
    }
    # the hash covers everything the approver signs off on (status is excluded: it changes)
    proposal_hash = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

    db.add(Proposal(
        id=proposal_id, kind=kind, title=title, rationale=rationale, evidence_json=evidence,
        config_diff=config_diff, target_weights=target_weights, orders_preview=body["orders_preview"],
        backtest_baseline_id=baseline["id"], backtest_candidate_id=body["backtest_candidate_id"],
        variants_tested=len(tested), risk_notes=risk_notes, confidence=confidence,
        status="PENDING_REVIEW", proposal_hash=proposal_hash, expires_at=expires_at,
    ))
    db.commit()
    append_audit("agent", "PROPOSAL_CREATED", {"proposal_id": proposal_id, "proposal_hash": proposal_hash, "kind": kind,
                                               "variants_tested": len(tested), "gate_passed": gate_passed})
    return {**body, "status": "PENDING_REVIEW", "proposal_hash": proposal_hash}

def draft_proposal(closes: pd.DataFrame, items: list[dict], events: list[dict], sig_df: pd.DataFrame) -> dict:
    strat = get_strategy()
    init_db()
    db = SessionLocal()
    try:
        baseline = run_backtest(closes, strat)
        _save_backtest(db, baseline, "baseline", strat)

        bounds = {p: list(b) for p, b in TUNABLE.items()}
        raw = llm.propose_candidates(strat, bounds, _flat_metrics(baseline), events, items)
        proposer = llm.MODELS["proposal"] if raw is not None else "sensitivity-v1"
        raw = raw if raw else _fallback_candidates(strat)
        tested = _test_candidates(db, closes, strat, raw, baseline)

        passing = [t for t in tested if t[3]]
        best = max(passing, key=lambda t: t[2]["metrics_test"]["sharpe"]) if passing else None
        changed = list(best[0]["changes"]) if best else None

        evidence_idx = (best[0]["article_indexes"] if best else []) or [
            i for i, it in enumerate(items) if any(it["url"] in ev.get("evidence_urls", []) for ev in events)][:5]
        evidence = [{"url": items[i]["url"], "published_at": items[i].get("published_at", ""),
                     "quote": items[i]["title"][:200]} for i in evidence_idx[:5]]

        return _finalize_proposal(
            db, kind="rebalance", strat=strat, closes=closes, sig_df=sig_df, baseline=baseline,
            tested=tested, best=best, gate_passed=best is not None, evidence=evidence, proposer=proposer,
            context_extra={"kind": "weekly rebalance", "events": events[:20]},
            fallback_title=(f"Weekly rebalance + {', '.join(changed)} change" if changed
                            else "Weekly rebalance to top-ranked names"),
            fallback_rationale=(
                "Weekly rebalance to the top-ranked names by momentum plus today's news/shock signals. "
                + (f"Candidate change to {', '.join(changed)} beat the baseline on the test window and is included. " if changed
                   else f"None of the {len(tested)} candidate configs beat the baseline on the test window, so the config is unchanged. ")
            ),
        )
    finally:
        db.close()

# ---------- human ideas ----------

_DOWN_WORDS = ("cut", "reduce", "trim", "less", "lower", "underweight", "avoid", "exit", "sell", "decrease")
_UP_WORDS = ("add", "increase", "more", "raise", "overweight", "boost", "buy", "grow")
_SLEEVE_ALIASES = {
    "Memory & compute": ("memory", "compute", "gpu", "nvidia", "nvda", "dram", "hbm"),
    "Semi equipment": ("equipment", "asml", "lithography", "semicap"),
    "Hyperscalers": ("hyperscaler", "cloud", "amazon", "microsoft", "google", "meta"),
    "Power & grid": ("power", "grid", "utilit", "electric", "nuclear"),
    "Energy inputs": ("energy", "oil", "gas", "uranium", "fuel"),
    "Materials / logistics": ("material", "logistic", "copper", "shipping", "freight"),
}

def keyword_idea_candidates(text: str, strat: dict) -> list[dict]:
    """Fallback when the LLM is unavailable: one tilt per sleeve the idea mentions, direction from its verbs."""
    t = text.lower()
    down = any(w in t for w in _DOWN_WORDS)
    up = any(w in t for w in _UP_WORDS)
    if down == up:  # no direction, or both: too ambiguous to guess
        return []
    out = []
    for sleeve in TILT_SLEEVES:
        if any(a in t for a in _SLEEVE_ALIASES.get(sleeve, (sleeve.lower(),))):
            path = f"sleeve_tilts.{sleeve}"
            out.append({"changes": {path: _get(strat, path) + (-0.5 if down else 0.5)},
                        "rationale": f"{'Underweight' if down else 'Overweight'} {sleeve}, as the submitted idea suggests.",
                        "article_indexes": []})
    return out[:3]

def _latest_signal_frame() -> pd.DataFrame:
    """News/shock components from the last daily run, so idea proposals use the same live signals."""
    db = SessionLocal()
    try:
        rows = db.query(Signal).all()
        return pd.DataFrame({"s2_news": {r.ticker: r.s2_news for r in rows}, "s3_shock": {r.ticker: r.s3_shock for r in rows}},
                            columns=["s2_news", "s3_shock"], dtype=float)
    finally:
        db.close()

def _set_idea(idea_id: str, **fields) -> None:
    db = SessionLocal()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        for k, v in fields.items():
            setattr(idea, k, v)
        idea.updated_at = dt.datetime.now(dt.UTC)
        db.commit()
    finally:
        db.close()

def process_idea(idea_id: str, closes: pd.DataFrame | None = None) -> None:
    """Turn a human idea into a `hypothesis` proposal: translate → backtest → draft. It still needs signed approval."""
    from trader.ingest.sources import ingest_price_history
    init_db()
    db = SessionLocal()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        if not idea or idea.status != "QUEUED":
            return
        text, evidence_url, submitted_by = idea.text, idea.evidence_url, idea.submitted_by
    finally:
        db.close()
    _set_idea(idea_id, status="PROCESSING")

    db = SessionLocal()
    try:
        closes = closes if closes is not None else ingest_price_history()
        strat = get_strategy()
        baseline = run_backtest(closes, strat)
        _save_backtest(db, baseline, "baseline", strat)

        bounds = {p: list(b) for p, b in TUNABLE.items()}
        translated = llm.translate_idea(text, strat, bounds, _flat_metrics(baseline))
        if translated is not None:
            raw, unsupported, proposer = translated["candidates"], translated["unsupported_reason"], llm.MODELS["proposal"]
        else:
            raw, unsupported, proposer = keyword_idea_candidates(text, strat), None, "keyword-v1"
        if not raw:
            note = unsupported or ("Couldn't map this idea to a backtestable change. Name a sleeve (e.g. 'Power & grid') "
                                   "and a direction (e.g. 'reduce'), or a strategy parameter.")
            _set_idea(idea_id, status="NO_PROPOSAL", note=note)
            append_audit("agent", "IDEA_NOT_PROPOSED", {"idea_id": idea_id, "reason": note[:300]})
            return

        tested = _test_candidates(db, closes, strat, raw, baseline)
        if not tested:
            note = "Every change this idea maps to is outside the strategy's allowed bounds."
            _set_idea(idea_id, status="NO_PROPOSAL", note=note)
            append_audit("agent", "IDEA_NOT_PROPOSED", {"idea_id": idea_id, "reason": note})
            return

        # the human asked for this test, so the best variant is drafted even if it lost to the baseline (flagged as such)
        passing = [t for t in tested if t[3]]
        best = max(passing or tested, key=lambda t: t[2]["metrics_test"]["sharpe"])
        gate_passed = bool(passing)
        evidence = [{"url": evidence_url, "published_at": "", "quote": "Source attached by the idea's submitter"}] if evidence_url else []
        changes = ", ".join(f"{p.split('.')[-1]} → {v:g}" for p, v in best[0]["changes"].items())

        proposal = _finalize_proposal(
            db, kind="hypothesis", strat=strat, closes=closes, sig_df=_latest_signal_frame(), baseline=baseline,
            tested=tested, best=best, gate_passed=gate_passed, evidence=evidence, proposer=proposer,
            context_extra={"kind": "test of a human-submitted idea", "submitted_idea": text},
            fallback_title=f"Idea test: {changes}",
            fallback_rationale=(
                f"An approver suggested: \"{text[:300]}\". The agent mapped it to {changes} and backtested it. "
                + ("It beat the baseline on the out-of-sample test window. " if gate_passed
                   else "It did NOT beat the baseline on the out-of-sample test window; review the comparison before approving. ")
            ),
            origin=f"Idea {idea_id} submitted by {submitted_by}",
        )
        _set_idea(idea_id, status="PROPOSED", proposal_id=proposal["id"],
                  note="Beat the baseline on the test window." if gate_passed else "Drafted, but it lost to the baseline on the test window.")
    except Exception as e:
        _set_idea(idea_id, status="FAILED", note=f"Processing failed: {str(e)[:300]}")
        append_audit("agent", "IDEA_FAILED", {"idea_id": idea_id, "error": str(e)[:300]})
    finally:
        db.close()

# ---------- pipeline ----------

def run_pipeline() -> dict:
    from trader.ingest.sources import ingest_news, ingest_price_history

    news_items = ingest_news()
    closes = ingest_price_history()

    node_ids = [n["id"] for n in get_shockmap().get("nodes", [])]
    events = llm.classify_events(news_items, node_ids) if news_items else []
    model_id = llm.MODELS["classify"] if events is not None else "heuristic-v1"
    if events is None:
        events = classify_events_headlines(news_items)
    save_events(events, model_id)

    shock_exposures = propagate(events).get("exposure", {})
    digest = write_digest(news_items)
    sig_df = compute_composite_signals(closes, shock_exposures=shock_exposures)
    proposal = draft_proposal(closes, news_items, events, sig_df)

    init_db()
    db = SessionLocal()
    try:
        db.add(ServiceHeartbeat(service="jobs", status="ok"))
        db.query(Signal).delete()
        selected = set(proposal["target_weights"])
        for ticker, row in sig_df.iterrows():
            db.add(Signal(
                as_of=digest["as_of"], ticker=ticker,
                s1_momentum=float(row.get("s1_momentum", 0)), s2_news=float(row.get("s2_news", 0)),
                s3_shock=float(row.get("s3_shock", 0)), s4_fund=float(row.get("s4_fund", 0)),
                composite=float(row.get("composite", 0)), rank=int(row.get("rank", 0)),
                vol_regime=float(row.get("vol_regime", 1.0)), market_trend=float(row.get("market_trend", 1.0)),
                selected=ticker in selected,
            ))
        db.commit()
    finally:
        db.close()

    return {"digest": digest, "events_classified": len(events), "event_model": model_id,
            "proposal_id": proposal["id"], "variants_tested": proposal["variants_tested"]}
