# 11 — Web App

A Next.js app deployed on Vercel at a public URL (see `16_DEPLOYMENT.md`). It talks only to the `api` service.

## Access model
| Role | How they get in | Can do |
|------|-----------------|--------|
| **Visitor** (judges, public) | No login | View every page read-only: digest, signals, shock map, proposals (incl. decisions), backtests, paper portfolio, audit log |
| **Approver** | Connect wallet → **Sign-In With Ethereum (SIWE)** → address must be in `approvers` registry (`15`) | Everything above + approve / reject / request changes (by signing), toggle freeze / agent kill switch |

- No passwords. The session is an httpOnly, Secure, SameSite=strict cookie issued by `api` after SIWE verification (8 h expiry).
- Visitors never see secrets, raw LLM prompts or anything outside public data and the project's own records.
- A banner on every page reads: **"PAPER TRADING · Educational project · Not financial advice"**.

## Global layout
- **Top bar:** PAPER MODE badge · trading frozen? · agent enabled? · data freshness dots per source · service heartbeats · "Connect wallet" button.
- **Inbox badge** (approvers): count of PENDING_REVIEW proposals.
- Responsive: usable on a phone, so an approver can review and sign from a mobile wallet browser.

## Pages (routes)
### `/` Pulse
- Today's agent digest in three sections (Chips · Energy · Supply chain). Each bullet links to its source.
- Theme heat strip: news intensity z-score and tone per theme, last 30 days.
- Macro tiles: Korea chip exports YoY, TSMC revenue YoY, Henry Hub, EIA retail power price YoY, GSCPI.

### `/shock-map`
- Interactive graph of `14`. Node color = current exposure (diverging). Edge width = weight.
- Click a node to see its recent events, evidence links and downstream tickers.
- What-if panel: apply a hypothetical shock and see the propagated exposures (computed by `api`, read-only).

### `/signals`
- Ticker × signal z-score table, composite score, rank, selected flag. Click a ticker to see its signal-vs-price chart.
- Coverage and staleness indicators.

### `/proposals` and `/proposals/[id]`
- List filtered by status.
- The detail page implements `08_HUMAN_APPROVAL.md` § What the approver sees.
- Approvers get the checklist → 60 s timer → **Sign approval** (wallet EIP-712 prompt, `15`) → progress toward the threshold (e.g., "1 of 2 signatures").
- Reject / request changes require a comment, and a reject is also signed.

### `/backtests` and `/backtests/[id]`
- Latest baseline re-test: equity curve, rolling Sharpe, drawdown.
- Compare two results side by side. Decay monitor: paper vs replayed backtest.

### `/portfolio`
- Paper equity curve (from snapshots), positions, sleeve weights, P&L, orders and fills.
- Risk panel: VaR/ES, beta, limit utilization bars (`07`).

### `/audit`
- Paginated, searchable audit log. Entry detail shows the payload and its hash links.
- "Verify chain" button: runs in the browser over the downloaded entries (so the visitor doesn't have to trust the server's answer).
- Anchors list with Sepolia explorer links. Merkle proof viewer for any entry.

### `/about`
- What the project is, the two non-negotiable rules, how to verify approvals and anchors yourself, and a link to the source repo.

### `/settings` (approvers only)
- Current strategy/risk config versions and the approval that activated each.
- Freeze-trading and agent kill-switch toggles (audited). There is no live-trading toggle anywhere.

## API contract (consumed by web)
Defined by FastAPI's OpenAPI schema. TypeScript types are generated with `openapi-typescript` in CI, so the front
and back ends can't drift apart. The main endpoints:
```
GET  /digest/latest            GET  /signals?as_of=
GET  /shockmap                 POST /shockmap/what-if
GET  /proposals?status=        GET  /proposals/{id}
GET  /proposals/{id}/typed-data            # EIP-712 payload to sign
POST /proposals/{id}/signatures            # {decision, signature, comment}  (approver)
GET  /backtests/{id}           GET  /portfolio   GET /risk
GET  /audit?after_seq=&limit=  GET  /audit/{seq}/proof   GET /anchors
GET  /auth/nonce   POST /auth/verify (SIWE)   POST /auth/logout
POST /controls/freeze   POST /controls/agent   (approver, audited)
GET  /healthz   GET /status
```

## Design notes
- Every number links to its origin (backtest ID, source URL, event ID).
- Consistent sleeve colors across all charts. Supports light and dark themes.
- Timestamps are shown in the viewer's local time with UTC on hover.
- Data is fetched with server components and cached for 60 s. Proposal and inbox views are always fetched fresh.
