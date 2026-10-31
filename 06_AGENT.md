# 06 — Agent

## Role
A **research analyst, not a trader.** It reads, summarizes, classifies, tests hypotheses through the backtest
engine and writes proposals. It **cannot** place orders, change configs, approve anything or edit history.

## Model
- Anthropic Claude via the plain `anthropic` Python SDK with tool use. **Not** the Claude Agent SDK or Claude Code:
  they ship shell/file tools, which this agent must not have. No LangChain or similar framework — the tool set is
  small and a framework makes the audit trail harder to follow.
- Model per task (defaults, all in config):
  | Task | Default | Notes |
  |------|---------|-------|
  | News classification (step 2) | `claude-haiku-5-5` | Promote to `claude-sonnet-5-5` only if it fails the eval set (below) |
  | Daily digest (step 4) | `claude-sonnet-5-5` | |
  | Hypotheses, proposal, risk notes (steps 7–8) | `claude-opus-5-5` | Low volume, highest stakes |
- Config stores, per model: ID and **training cutoff date** (needed for the look-ahead rule in `04`).
- Log the model ID, token usage (incl. cache reads) and cost with every call.
- **Provider-neutral interface.** All LLM calls go through `agent/llm.py` with three functions:
  `classify_events()`, `write_digest()`, `draft_proposal()`. Nothing else imports the SDK. Swapping a model or
  provider means re-running the eval set (below) and changing config, not code elsewhere.

## Orchestration: code drives, the LLM is called
The daily loop is a **Python pipeline**, not an autonomous agent. The LLM is called only at the steps marked
**[LLM]**. Every other step is deterministic, so the model cannot skip, reorder or repeat steps, and a run is
reproducible apart from the LLM outputs (which are logged).
```
1. load context: current strategy config, positions, last 7 digests, open proposals      (code)
2. [LLM] classify new news → events (pre-filtered, Batch API, structured output)
3. update shock map exposures (14)                                                       (code)
4. [LLM] write daily digest (what changed in chips / energy / supply, with citations)
5. run baseline backtest on latest data → decay checks (04)                              (code)
6. decide whether a trigger fires:                                                       (code)
     - weekly rebalance day
     - strategy decay flag
     - large shock event (magnitude 3, confidence ≥ 0.7)
     - a signal's behavior changed materially (e.g., news signal coverage jump)
7. if triggered: [LLM, tool-use loop] propose ≤ 5 candidate configs within bounds (05);
   code runs walk-forward on each, applies acceptance gate (04), picks best passing candidate
8. [LLM] draft proposal (schema below); code validates → approval queue (PENDING_REVIEW)
9. write everything to audit log                                                         (code)
```
Step 7 is the only open-ended tool-use loop, and it is capped (≤ 5 `run_backtest` calls, ≤ 20 turns). It is
**hypothesis-driven, not a grid search**. Each candidate must include a one-sentence rationale linked to
evidence (e.g., "memory export YoY turned negative; reduce momentum lookback to react faster"). Every candidate
tested is logged, so that the Deflated Sharpe calculation counts it.

## News pre-filter (before step 2)
Cheap deterministic filtering so the LLM only sees plausibly relevant items:
- Drop duplicates (same URL or near-identical title).
- Keep an item only if it matches theme keywords or a shock-map node alias, **or** its embedding similarity to
  a theme description is above a threshold (in config).
- Log the counts of dropped and kept items. Each week, sample 20 dropped items by hand to check recall.

## Cost controls
- **Batch API** for step 2: the daily job is not latency-sensitive, and batch requests are billed at a discount.
  If the batch has not finished by the deadline in config, fall back to synchronous calls for that day.
- **Prompt caching** for the stable prefix: system prompt, tool definitions, list of shock-map nodes, current
  strategy config. Put volatile content (news, dates) after the cache breakpoint.
- **Strict tool schemas** generated from the pydantic models, so outputs are schema-valid at generation time;
  pydantic validation stays as the backstop.

## Tools exposed to the LLM
| Tool | Type | Description |
|------|------|-------------|
| `query_signals(as_of, tickers?, signals?)` | read | Signal values |
| `query_news(theme?, since, limit)` | read | Normalized news (title, summary, url, published_at) |
| `query_macro(series_id, since)` | read | Macro series (point-in-time) |
| `get_shock_map(node?)` | read | Graph nodes, edges, current exposures |
| `get_portfolio()` | read | Paper positions and P&L (read-only snapshot, no broker keys) |
| `get_strategy_config(version?)` | read | Current/historical config |
| `run_backtest(config, mode)` | compute | `mode ∈ {baseline, walk_forward, holdout}`. Returns metrics + result_id |
| `record_events(events[])` | write (own table) | Classified events, schema-validated |
| `create_proposal(proposal)` | write (queue) | Creates proposal in PENDING_REVIEW. Cannot set any other status |

**Deliberately absent:** `place_order`, `approve`, `edit_config`, `delete_*`, shell, arbitrary web fetch.

## Output schemas (pydantic)
```python
class Event(BaseModel):
    theme: Literal["memory","ai_capex","power","fab_supply","policy","logistics"]
    node_id: str                 # must exist in shock map
    direction: Literal[1, -1]
    magnitude: Literal[1, 2, 3]
    confidence: float            # 0..1
    summary: str                 # ≤ 280 chars
    evidence_urls: list[HttpUrl] # ≥ 1, must be URLs present in the input batch

class Proposal(BaseModel):
    kind: Literal["rebalance","param_change","risk_reduction","hypothesis"]
    title: str
    rationale: str                   # plain English, ≤ 300 words
    evidence: list[Citation]         # url + published_at + quote ≤ 40 words
    config_diff: dict | None         # JSON patch vs current config
    target_weights: dict[str, float] | None
    orders_preview: list[OrderPreview] | None
    backtest_baseline_id: str
    backtest_candidate_id: str | None
    variants_tested: int
    risk_notes: RiskNotes            # see 07
    confidence: Literal["low","medium","high"]
    expires_at: datetime             # default: next market close
```

## Prompting principles
- The system prompt states the agent's role, the hard rules (paper only, human decides, cite sources) and its tool list.
- Numbers in proposals must come from tool outputs. Code checks that every metric quoted in `rationale` matches the backtest result ±rounding.
- Ask for **counter-arguments**: each proposal includes "what would make this wrong".

## Guardrails
- **Prompt injection:** news/filing text is wrapped in `<untrusted_document>` tags. The system prompt says to treat it only as data. No tool can do anything harmful even if an injection succeeds, because there is no order tool and writes are schema-limited.
- **Citation check:** every `evidence_urls` entry must match a URL from the tool results in that run. Otherwise the event or proposal is rejected.
- **Bounds check:** `config_diff` is validated against `05` bounds before it reaches the queue.
- **Rate limits:** ≤ 3 proposals per day. ≤ 5 backtest variants per proposal.
- **Cost cap:** daily token budget in config. If it is exceeded, the agent writes a minimal digest and stops.
- **Kill switch:** `AGENT_ENABLED=false` stops all LLM calls. Ingestion and dashboard keep running.

## Training-cutoff look-ahead
The model has read news and price history up to its training cutoff. If it classifies a pre-cutoff headline, it
may already "know" the outcome, which biases direction, magnitude and confidence. Rules:
- Events are classified **once, at ingestion time**, and are immutable. Each one stores `model_id` and
  `classified_at`. Never re-classify historical news (not even after a model upgrade); new models apply only going forward.
- Never backfill events by running old news through the LLM. If it is done for a one-off experiment, the
  results are marked `in_sample_llm=true` and cannot be used for an acceptance gate (see `04`).
- Approved-vs-rejected shadow-portfolio comparisons (below) count only periods after the proposal's `created_at`.

## Evaluation of the agent itself
- Weekly: share of proposals approved, OOS performance of approved vs rejected proposals (tracked as shadow portfolios), citation validity rate, classifier agreement with a 50-headline hand-labeled set.
- **Model selection uses the eval set, not reputation.** Before changing the model for any task (including
  another provider's), run the candidate on the hand-labeled set and compare agreement, schema-failure
  rate and cost per run. Record the result in the audit log. The labeled set should include headlines published
  **after** every candidate's training cutoff, so the scores are not inflated by memorization.
