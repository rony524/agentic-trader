# 13 — Build Plan

**Hackathon mode:** the deadline is **Sun Nov 1, 14:00**. The full phased plan (≈ 13–20 days) is kept below as the
post-hackathon roadmap. Until the deadline, only the **Hackathon plan** applies. Where it conflicts with docs
`00`–`16`, it wins.

---

## Hackathon plan (Sat 12:00 → Sun 14:00)

### What the demo must show (the "golden path")
Open the public URL → today's digest with cited sources → an agent proposal (config diff + backtest vs baseline +
risk notes + citations) → approver signs **approve** with MetaMask → executor verifies the signature and submits
Alpaca **paper** orders → the audit log shows the hash chain verifying in the browser. A **rejected** proposal places nothing.

Everything that doesn't serve this path is cut or deferred.

### ⚠️ Market is closed all weekend
Sat Oct 31 and Sun Nov 1 are not trading days. Alpaca paper accepts orders but **won't fill them until Monday's open**.
In the demo, show the Alpaca order ID with status `accepted`/`new` ("queued for Monday open"), not a fill.
Use `time_in_force=day` market orders, or `opg` if you want to say "executes at the open". Prices and news are
static for the weekend, so run the pipeline once Saturday and treat that run as "today's".

### Simplifications (vs. the full docs)
| Full spec | Hackathon version |
|-----------|-------------------|
| 4 services (api, jobs, executor, web) on Render + Vercel | **One** FastAPI app on Render (jobs + executor as modules/endpoints) + Next.js on Vercel. Keep the module boundary: only `execution/` imports the Alpaca client. |
| Render crons for the daily schedule | A `POST /admin/run-pipeline` endpoint (admin token) + a CLI command. One Render cron only if there's spare time. |
| Neon + Alembic + R2 | Neon only. `SQLAlchemy create_all`, no migrations. Backtest results stored as JSON in Postgres. |
| 5+ data sources | **3:** yfinance prices (universe from `03`), news via GDELT DOC API or Google News RSS per theme, 1–2 FRED series (e.g. GSCPI). |
| Signals S1–S5 | S1 momentum + S5 regime + S2/S3 news/event score. Drop S4 fundamentals (weight → 0, redistribute to momentum). |
| Walk-forward, Deflated Sharpe, holdout | Weekly-rebalance vectorized backtest, **one** train/test split, metrics: CAGR, Sharpe, max DD, turnover. Simple gate: candidate beats baseline on the test window and max DD isn't worse by > 2 pp. |
| Batch API, caching, eval set, embedding pre-filter | Synchronous calls, keyword pre-filter only. Keep: structured outputs, citation check, bounds check (`05`), no order tool. |
| SIWE sessions + multisig M-of-N | Wallet signs an **EIP-712** approval/rejection. Server and executor verify the signer against an allowlist in env. Threshold = 1. (2-of-3 is a stretch goal.) |
| Sepolia anchoring | Stretch goal. Hash-chained audit table + in-browser verification is the must-have. |
| 8 web pages, mobile, notifications | **4 pages:** `/` (digest + signals table + portfolio), `/proposals/[id]`, `/backtests/[id]` (can be a section of the proposal page), `/audit`. PAPER banner on every page. |
| Full test suite + Playwright | Only the tests a judge would ask about: (1) startup fails if not paper endpoint, (2) no order without a valid approval signature, (3) rejected proposal → zero orders, (4) audit chain detects tampering. |

### Timeline
Times are approximate. If a block overruns by > 45 min, cut scope from that block and move on. Don't push into sleep.

| When | Block | Done when |
|------|-------|-----------|
| **Sat 12:00–13:30** | **0. Skeleton + deploy.** Repo, FastAPI `/healthz` + `/status`, Next.js shell + PAPER banner, Neon DB, deploy to Render + Vercel. Alpaca paper client with the paper-only guard. | Public URL shows the paper account equity. Paper-guard test passes. |
| **13:30–16:00** | **1. Data + signals.** yfinance history for the universe, GDELT/RSS news per theme (store `url`, `published_at`, `retrieved_at`), FRED series. Momentum + regime + news score → composite → top-N. | Signals table renders on `/` from the DB. |
| **16:00–18:30** | **2. Backtest.** Weekly rebalance, inverse-vol weights, caps from `07`, regime scaling, train/test split, metrics. Baseline run stored and shown. | Baseline metrics + equity curve visible on the site. |
| 18:30–19:00 | Break / food | |
| **19:00–22:30** | **3. Agent.** `agent/llm.py`: `classify_events()` (with citation check), `write_digest()`, `draft_proposal()`. Proposal step: Claude suggests ≤ 3 candidate configs within `05` bounds → code backtests each → gate → best one becomes a `PENDING_REVIEW` proposal with diff, metrics vs baseline, risk notes, citations, target weights + orders preview. Prompt-injection wrapping (`<untrusted_document>`). | Running the pipeline produces a digest and one valid proposal on the site. |
| **22:30–01:30** | **4. Approve → execute → audit.** Hash-chained `audit_log` table (every proposal, backtest, signature, order). Proposal page with MetaMask EIP-712 approve/reject. API stores the signature. Executor re-verifies signer + proposal hash + expiry, runs pre-trade checks (`07`/`09`), submits paper orders. `/audit` page recomputes the chain in the browser. | End to end on production: approve → Alpaca order IDs; reject → nothing. Safety tests pass. |
| **01:30–07:30** | **Sleep.** Seriously. | |
| **Sun 07:30–10:00** | **5. One differentiator** (pick the one judges will value most): **(a)** shock map: static `shockmap.yaml`, 1–2 hop propagation, react-flow view of exposures; **(b)** 2-of-3 multisig approvals; **(c)** Sepolia `AuditAnchor` + "verify on Etherscan" link. Default: **(a)**, since it's the most visible and fits the chips/energy/supply-chain theme. | It works on production. |
| **10:00** | **Feature freeze.** No new features after this. | |
| 10:00–12:00 | **6. Polish + demo prep.** Fix golden-path bugs, empty/error states, seed one approved and one rejected proposal so the site looks alive. README (setup + architecture diagram + safety rules). Write the demo script. **Record a backup video** of the full golden path. | Demo video saved. |
| 12:00–13:30 | Buffer + rehearse the demo twice. | |
| **13:30** | **Submit.** (30 min of margin before 14:00.) | |

### If you fall behind, cut in this order
1. Block 5 differentiator (the core loop is already a complete story).
2. FRED / macro data.
3. News signal in the score (keep news for the digest + citations only).
4. Train/test split → single in-sample backtest, labeled as such.
5. Wallet signing → approve/reject button with a server-side admin token. **Last resort**, since signed approvals are a key selling point.

Never cut: paper-only guard, "no order without approval", citations on news claims, the audit chain.

### Demo script (≈ 3 min)
1. **Problem (20 s):** AI buildout is limited by chips, energy and supply chains. News moves these names, but an
   autonomous trading bot is dangerous. We built an agent that researches and proposes, and a human decides.
2. **Digest (30 s):** today's Chips · Energy · Supply chain summary. Click a citation to show it's real.
3. **Proposal (60 s):** config diff, backtest vs baseline, risk notes, "what would make this wrong", sources.
4. **Approve (40 s):** sign in MetaMask → executor verifies → Alpaca paper order IDs (queued for Monday's open).
   Show a rejected proposal placed no orders.
5. **Trust (30 s):** `/audit` verifies the hash chain in the browser. Mention: the agent has no order tool,
   paper endpoint is hard-wired, tests prove both. (+ shock map / Sepolia if built.)

### Prep checklist (do now, in parallel with Block 0)
- [ ] Alpaca paper account + API keys
- [ ] Anthropic API key with credit
- [ ] Neon project, Render account, Vercel account, all linked to the GitHub repo
- [ ] FRED API key (free, instant)
- [ ] MetaMask installed, approver address noted (no real funds needed, nothing on-chain unless 5c)
- [ ] Sepolia RPC + faucet ETH only if you'll attempt 5c

---

## Post-hackathon roadmap (original full plan)

Each phase ends with something you can demo **at the public URL**. Deploy from day one so hosting problems
surface early. Don't start a phase until the previous one's acceptance criteria pass.

### Phase 0: Skeleton + first deploy (1 day)
- Monorepo layout (`12`), `uv` + `pnpm`, lint/type/test tooling, GitHub Actions CI.
- FastAPI with `/healthz` and `/status`. Next.js app with the layout shell + PAPER banner.
- Neon DB + Alembic baseline migration. `render.yaml`. Vercel project.
- Executor stub that connects to Alpaca paper and writes an account snapshot + heartbeat.
- **Accept:** the public URL shows the paper account equity and service heartbeats. CI is green and the paper-only guard tests pass.

### Phase 1: Data (1–2 days)
- Ingestors: FRED, EIA, GDELT, SEC EDGAR, RSS (jobs). Alpaca bars/news (executor). yfinance history backfill.
- Raw payloads to R2, normalized tables in Postgres. Publication-lag metadata.
- **Accept:** cron jobs populate every table in production, and the source freshness dots in the web app are green.

### Phase 2: Signals + baseline backtest (2 days)
- S1 momentum, S4 fundamentals, S5 regime (news/shock weights = 0 for now).
- Backtest engine, walk-forward, metrics, artifacts to R2.
- `/signals` and `/backtests` pages.
- **Accept:** the baseline report is visible on the site. Look-ahead and reproducibility tests pass.

### Phase 3: Audit + approval + execution (2–3 days)
- Append-only audit log in Postgres, `/audit` page with in-browser chain verification.
- SIWE login, approver registry, EIP-712 signing in the browser (threshold 1).
- Proposal state machine. Executor verification + all pre-trade checks.
- A manually created rebalance proposal gets signed in the web app and fills on paper.
- **Accept:** end-to-end on production, an approved proposal fills and a rejected one places nothing. Safety tests pass.

### Phase 4: Agent (2–3 days)
- Claude integration, tools, schemas, citation validation, news → events, daily digest on `/`.
- Weekly rebalance proposals, param-change proposals with gate (`04`) + risk notes (`07`).
- **Accept:** a scheduled daily run produces a digest and a valid proposal on the site. A prompt-injection test item has no effect.

### Phase 5: Shock map + news signals (1–2 days)
- `shockmap.yaml`, propagation, S2/S3 in the score (within caps). `/shock-map` page with what-if.
- **Accept:** propagation is correct on fixtures, and live events change the exposures shown on the site.

### Phase 6: Web polish + portfolio/risk (2 days)
- `/portfolio`, risk panel, `/proposals/[id]` full review UX, mobile layout, `/about`, notifications.
- **Accept:** the full workflow can be done on a phone with a mobile wallet. Playwright e2e passes.

### Phase 7: Multisig + anchoring (1–2 days)
- M-of-N thresholds (`15`). Deploy `AuditAnchor` to Sepolia. Nightly anchor job. Merkle proof viewer.
- **Accept:** a 2-of-3 approval is enforced in production, and an anchored entry is verifiable on the Sepolia explorer from the site.

### Phase 8: Hardening & demo (1–2 days)
- Security checklist in `16`. Rate limits, headers, alerts.
- Run daily for ≥ 1 week. Fix issues.
- Demo script: open the URL → digest → proposal → review → sign with wallet → paper fill → audit proof on Sepolia.
- README: local setup in ≤ 10 commands + deployment guide link.

### Stretch ideas
- ERCOT/PJM price signals. Earnings-call parsing for "memory cost" mentions.
- Shadow portfolios for rejected proposals.
- Public read-only RSS/email of the daily digest.
