# Agentic Trader — Chips · Energy · Supply Chain

An AI research agent that tracks news on chips, energy, and supply chains, turns it into trading signals, backtests strategies, and proposes changes — with a human approving every decision. **Paper trading only.**

Built for a hackathon. Live website deployment; trading is always on an Alpaca **paper** account.

## Non-negotiable rules
1. **Paper trading only.** The broker client is hard-wired to `paper-api.alpaca.markets`. Startup fails if `ALPACA_PAPER != true`.
2. **A human makes every decision.** The agent has no order tool. Orders come only from the executor, which accepts only proposals with valid human approval signatures.
3. **No unverifiable claims.** Every news-driven statement cites a source URL and timestamp.
4. **No look-ahead.** Every data point stores `published_at` and `retrieved_at`. Backtests use only data available at each point in time.
5. **Full audit trail.** Every proposal, backtest, approval, and order is hash-chained.

## Architecture
```
Browser (anyone)          Approver's browser + wallet
  │ read-only                 │ EIP-712 signing
  ▼                           ▼
Next.js (Vercel)  ──── HTTPS ────▶  FastAPI (Render)
                                      │
                    ┌─────────────────┼──────────────────┐
                    ▼                 ▼                  ▼
              Postgres (Neon)   Agent pipeline     Alpaca PAPER API
              + audit chain     (ingest→signals    paper-api.alpaca.markets
                                →backtest→propose)
```

## Monorepo layout
```
apps/web/                 # Next.js 14 + TypeScript + Tailwind
  app/                    # Routes: /, /proposals, /proposals/[id], /audit, /backtests
  components/             # ConnectWalletButton (client component)
  lib/api.ts              # Fetch client

services/trader/          # Python package (FastAPI + agent + executor)
  src/trader/
    api/main.py           # FastAPI app — all endpoints
    settings.py           # Env + YAML config loader
    store/models.py       # SQLAlchemy models (11 tables)
    audit/chain.py        # Hash-chained audit log
    approval/eip712.py    # EIP-712 signature verification
    execution/executor.py # Alpaca paper executor with guards
    ingest/sources.py     # yfinance + news RSS + FRED
    signals/engine.py     # S1-S5 composite signals
    backtest/engine.py    # Weekly rebalance backtest
    shockmap/propagate.py # DAG shock propagation
    agent/pipeline.py     # Full daily pipeline
  tests/test_safety.py    # 6 safety tests
  pyproject.toml

config/                   # universe.yaml, strategy.yaml, risk.yaml, shockmap.yaml, approvers.yaml
render.yaml               # Render Blueprint
docker-compose.yml        # Local dev
```

## Quick start (local)

### Prerequisites
- Python 3.12–3.14 (`eth-account`, needed to verify approval signatures, doesn't build on 3.15 yet)
- Node.js 18+
- MetaMask on the **Sepolia** network (the signing domain uses Sepolia's chain ID; the app asks MetaMask to switch)

### Backend
```bash
cd services/trader
pip install -e ".[alpaca,eth,dev]"

# Set env vars
export ADMIN_TOKEN=dev-admin-token
export ALPACA_PAPER=true
export WEB_ORIGIN=http://localhost:3000
export APPROVER_ADDRESSES=0xYourMetaMaskAddress   # nobody can approve until this (or config/approvers.yaml) lists you
export ANTHROPIC_API_KEY=...                      # optional: without it the agent uses deterministic fallbacks

# Start the API
python -m uvicorn trader.api.main:app --host 0.0.0.0 --port 8000 --app-dir src

# In another terminal, seed data:
curl -X POST http://localhost:8000/admin/run-pipeline -H "X-Admin-Token: dev-admin-token"
```

### Frontend
```bash
cd apps/web
npm install
export NEXT_PUBLIC_API_URL=http://localhost:8000
npx next dev --port 3000
```

Open http://localhost:3000

### Run safety tests
```bash
cd services/trader
python -m pytest -v
```

## API endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/status` | Paper mode, trading frozen, agent enabled, freshness |
| GET | `/digest/latest` | Today's agent digest |
| GET | `/signals` | Signal table (27 tickers) |
| GET | `/shockmap` | Shock propagation graph |
| POST | `/shockmap/what-if` | Simulate a shock |
| GET | `/proposals` | List proposals |
| GET | `/proposals/{id}` | Proposal detail with backtests, risk notes |
| GET | `/proposals/{id}/typed-data` | EIP-712 payload to sign |
| POST | `/proposals/{id}/signatures` | Submit signed approval/rejection |
| POST | `/ideas/typed-data` | EIP-712 payload for submitting an idea |
| POST | `/ideas` | Approver submits a signed idea; the agent backtests it and drafts a `hypothesis` proposal |
| GET | `/ideas` | List submitted ideas and their status |
| GET | `/universe` | Sleeves and their tickers |
| GET | `/backtests/{id}` | Backtest result |
| GET | `/portfolio` | Paper account snapshot |
| GET | `/audit` | Audit log entries |
| GET | `/audit/verify` | Verify hash chain (server-side) |
| POST | `/admin/run-pipeline` | Run the full daily pipeline (needs `X-Admin-Token`) |
| POST | `/admin/execute` | Execute approved proposals (needs `X-Admin-Token`) |
| POST | `/controls`, `/admin/approvers` | Kill switches, approver registry (need `X-Admin-Token`) |

## Safety tests
- **Paper only:** startup fails if `ALPACA_PAPER=false`; no live endpoint anywhere in the code.
- **No order without a verified approval:** pending, rejected, or "APPROVED" proposals without valid signatures place nothing — the executor re-verifies every signature itself. Frozen trading places nothing.
- **Forgery:** garbage signatures are rejected; admin endpoints refuse requests without the token.
- **Audit chain:** tampering is detected, and the browser check on `/audit` verifies the same way.
- **Backtest:** no look-ahead (results up to a date don't change when later data is added); parameters change results.
- **Agent:** candidate configs outside the `05_STRATEGY_SPEC` bounds are rejected; citations can only point at ingested articles.

## Deployment
- **API**: Render web service (Dockerfile in `services/trader/`)
- **Web**: Vercel (root dir = `apps/web`)
- **DB**: Neon Postgres (or SQLite for local dev)
- Set env vars per `.env.example` (Render: `DATABASE_URL`, Alpaca paper keys, `ANTHROPIC_API_KEY`, `APPROVER_ADDRESSES`, `WEB_ORIGIN` = your Vercel URL)

## Disclaimer
Educational paper-trading project. Nothing it produces is financial advice.
