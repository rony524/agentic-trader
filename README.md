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
- Python 3.12+ (3.15 tested)
- Node.js 18+

### Backend
```bash
cd services/trader
pip install -e . --no-deps
pip install fastapi uvicorn sqlalchemy pydantic pydantic-settings pandas numpy requests python-dotenv yfinance feedparser networkx httpx ruamel.yaml anthropic

# Set env vars
set ADMIN_TOKEN=dev-admin-token
set ALPACA_PAPER=true
set WEB_ORIGIN=http://localhost:3000

# Run the pipeline once to seed data
python -m uvicorn trader.api.main:app --host 0.0.0.0 --port 8000 --app-dir src

# In another terminal, seed data:
curl -X POST http://localhost:8000/admin/run-pipeline -H "Content-Type: application/json" -d "{\"token\":\"dev-admin-token\"}"
```

### Frontend
```bash
cd apps/web
npm install
set NEXT_PUBLIC_API_URL=http://localhost:8000
npx next dev --port 3000
```

Open http://localhost:3000

### Run safety tests
```bash
cd services/trader
python -m pytest tests/test_safety.py -v
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
| GET | `/backtests/{id}` | Backtest result |
| GET | `/portfolio` | Paper account snapshot |
| GET | `/audit` | Audit log entries |
| GET | `/audit/verify` | Verify hash chain (server-side) |
| POST | `/admin/run-pipeline` | Run the full daily pipeline |
| POST | `/admin/execute` | Execute an approved proposal |

## Safety tests (6/6 passing)
1. **Startup fails if not paper** — `ALPACA_PAPER=false` → `PaperOnlyViolation`
2. **Paper-only guard** — correct config passes assertion
3. **No live endpoint in code** — `api.alpaca.markets` only appears as a forbidden reference
4. **No order without approval** — `PENDING_REVIEW` proposal → 0 orders
5. **Rejected proposal → no orders** — `REJECTED` proposal → 0 orders
6. **Audit chain detects tampering** — modifying any entry → verification fails

## Deployment
- **API**: Render web service (Dockerfile in `services/trader/`)
- **Web**: Vercel (root dir = `apps/web`)
- **DB**: Neon Postgres (or SQLite for local dev)
- Set env vars per `.env.example`

## Disclaimer
Educational paper-trading project. Nothing it produces is financial advice.
