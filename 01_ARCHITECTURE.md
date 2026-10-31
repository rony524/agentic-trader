# 01 — Architecture

The system is a **public web application** deployed to the cloud (see `16_DEPLOYMENT.md`). "Live" means the
website is live. Trading stays **paper only** (`09`).

## Deployed topology
```
                         Browser (anyone)                     Approver's browser + wallet
                               │  read-only                            │ SIWE login, EIP-712 signing
                               ▼                                       ▼
                    ┌──────────────────────────────────────────────────────────┐
                    │  web  — Next.js on Vercel  (no secrets)                  │
                    └───────────────────────────┬──────────────────────────────┘
                                                │ HTTPS / JSON
                                                ▼
                    ┌──────────────────────────────────────────────────────────┐
                    │  api  — FastAPI (Render web service)                     │
                    │  reads everything · stores proposals & signatures        │
                    │  holds: DB creds only (no Alpaca, no LLM keys)           │
                    └───────────────────────────┬──────────────────────────────┘
                                                │
          ┌─────────────────────────────────────┼─────────────────────────────────────┐
          ▼                                     ▼                                     ▼
┌───────────────────────┐          ┌─────────────────────────┐          ┌───────────────────────────┐
│ Postgres (Neon)       │◀────────▶│ jobs — Render cron      │          │ executor — Render worker  │
│ all tables + audit    │          │ ingest · signals · agent│          │ ONLY service with Alpaca  │
└───────────────────────┘          │ backtests · anchoring   │          │ keys: orders, bars, news, │
          ▲                        │ holds: LLM + data keys  │          │ account snapshots         │
          │                        └───────────┬─────────────┘          └────────────┬──────────────┘
          │                                    ▼                                     ▼
          │                        ┌─────────────────────────┐          ┌───────────────────────────┐
          └────────────────────────│ Object storage (R2)     │          │ Alpaca PAPER API          │
                                   │ raw data · backtest     │          │ paper-api.alpaca.markets  │
                                   │ artifacts · reports     │          └───────────────────────────┘
                                   └─────────────────────────┘
                                   Sepolia testnet ◀── nightly Merkle root (jobs, optional, 10)
```

## Services
| Service | Runtime | Responsibility | Secrets it holds | Can trade? |
|---------|---------|----------------|------------------|------------|
| `web` | Next.js on Vercel | UI, wallet connect, signing (`11`, `15`) | none (public API URL only) | No |
| `api` | FastAPI on Render | REST API, SIWE auth, proposal & signature storage, kill-switch toggles | DB URL, session secret | No |
| `jobs` | Python on Render cron | Ingest (non-Alpaca), signals, shock map, agent, backtests, anchoring | DB, R2, Anthropic, EIA, FRED, SEC UA, anchor key | **No order tool exists** |
| `executor` | Python on Render background worker | Alpaca bars/news ingest, approved order execution, reconciliation, snapshots | DB, Alpaca **paper** keys | Paper only, signed approval required |
| Postgres | Neon (managed) | All structured data + append-only audit log | — | — |
| Object storage | Cloudflare R2 (S3 API) | Raw payloads, backtest parquet, report files | — | — |

**Isolation rules**
- Only `executor` holds Alpaca keys. All Alpaca calls, including market data, go through it, and it writes results to Postgres.
- The `api` cannot approve anything by itself. It stores signatures, and the `executor` **re-verifies them independently**
  (`15`). A compromised API or a stolen session therefore cannot make the executor trade.
- The `agent` (inside `jobs`) never sees Alpaca or approver keys.

## Python code organization
The Python services share one package (`trader`) with modules:
`ingest/ store/ signals/ shockmap/ backtest/ agent/ approval/ execution/ audit/ api/`.
Each service has its own entry point (`trader-api`, `trader jobs <name>`, `trader-executor`). An import-linter
rule forbids every module except `execution/` from importing the Alpaca trading client.

## Tech stack
| Concern | Choice |
|---------|--------|
| Frontend | Next.js 15 (App Router) + TypeScript, Tailwind, shadcn/ui |
| Charts | Recharts (time series), react-flow or Cytoscape.js (shock map) |
| Wallet | wagmi + viem (connect, SIWE, `signTypedData`) |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, pydantic v2 |
| Broker | `alpaca-py`, `TradingClient(paper=True)` |
| Data | pandas, `yfinance` (long history fallback), Postgres, parquet on R2 |
| LLM | Anthropic Claude via `anthropic` SDK (tool use) |
| Signing/chain | `eth-account`, `web3.py`, `siwe` |
| Graph | networkx |
| Testing | pytest, hypothesis, Playwright (web e2e) |

## Daily schedule (Render cron, times US/Eastern, cron in UTC)
| Time | Service | Job |
|------|---------|-----|
| 06:30 | jobs | `ingest` — news, macro, filings |
| 06:35 | executor | refresh bars + Alpaca news |
| 07:00 | jobs | `signals` — signals + shock map |
| 07:15 | jobs | `agent` — digest, baseline re-test, triggers, proposals |
| 07:45 | api | notify approvers (email / web push) for new PENDING_REVIEW |
| 09:35–15:30 | executor | poll every 60 s for APPROVED proposals |
| 16:30 | executor | reconciliation + portfolio snapshot |
| 23:00 | jobs | `anchor` — Merkle root to Sepolia (optional) |

## Failure handling
- Ingestor failure → the source is marked `stale` (visible in the web status bar) and the jobs continue.
- Backtest failure → no proposal is drafted that day.
- Executor failure mid-batch → stop, log and alert. It retries only while the approval is still valid (`09`).
- Health endpoints: `api /healthz`. `executor` and `jobs` write heartbeats to the `service_heartbeats` table, which the web shows.
