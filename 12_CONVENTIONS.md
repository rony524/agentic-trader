# 12 — Conventions

## Repository layout (monorepo)
```
agentic-trader/
├── apps/
│   └── web/                    # Next.js 15 + TypeScript (Vercel)
│       ├── app/                # routes per 11_DASHBOARD
│       ├── components/
│       ├── lib/api/            # generated OpenAPI types + fetch client
│       └── lib/wallet/         # wagmi config, SIWE, EIP-712 helpers
├── services/
│   └── trader/                 # Python package, one Docker image
│       ├── pyproject.toml      # uv-managed
│       ├── Dockerfile
│       ├── alembic/
│       └── src/trader/
│           ├── api/            # FastAPI app, routers, auth (SIWE)
│           ├── ingest/  store/  signals/  shockmap/  backtest/
│           ├── agent/   approval/  execution/  audit/
│           ├── jobs.py         # `trader jobs <name>` entry points
│           ├── cli.py          # `trader` CLI (typer)
│           └── settings.py     # pydantic-settings
├── config/                     # universe, strategy (+history), risk, sources, shockmap, approvers (YAML)
├── contracts/                  # AuditAnchor.sol
├── docs/                       # these 00–16 spec files
├── docker-compose.yml          # local: postgres, minio (S3), api, executor
├── render.yaml                 # Render Blueprint (api, executor, cron jobs)
└── .github/workflows/
```

## Python
- Python 3.12, type hints everywhere, `mypy --strict` on `approval/`, `execution/`, `audit/`, `api/auth`.
- `ruff` lint + format, line length 100.
- Pure functions for signals/backtest. I/O at the edges.
- pydantic models for every cross-module structure, all API request/response bodies and all LLM I/O.
- SQLAlchemy 2 (typed ORM) + Alembic. Every schema change is a migration.
- No bare `except`. Errors are logged with context and re-raised or converted to a typed failure state.

## TypeScript / web
- Strict TypeScript, ESLint + Prettier, `pnpm`.
- API types are generated from FastAPI's OpenAPI (`openapi-typescript`). Never hand-write API types.
- Server components for data fetching. Client components only for interactivity (charts, wallet, forms).
- No secrets in the web app. Only `NEXT_PUBLIC_*` variables, which are public by definition.
- Accessibility: keyboard navigable, color is never the only signal (icons/labels on red/green).

## Time & money
- All timestamps are timezone-aware **UTC** in storage and in the API (ISO 8601). Convert only for display and NYSE calendar logic (`pandas_market_calendars`).
- Floats in research/backtests. `Decimal` at the order boundary, rounded to the broker's precision. Money is serialized as strings in the API.

## Config & secrets
- All Python settings come from `settings.py` (env + YAML). There are no magic constants elsewhere.
- The per-service secret allocation in `16_DEPLOYMENT.md` is mandatory. Each service loads only the settings it needs, and startup fails if it finds secrets it shouldn't have (e.g., `api` refuses to start if `ALPACA_*` is set).
- `.env.example` lists every variable, grouped by service. `.env` is gitignored.
- Runtime toggles (`TRADING_FROZEN`, `AGENT_ENABLED`) live in the `controls` table. Env vars are only boot-time defaults.

## Logging
- `structlog` JSON to stdout (collected by Render). Every line has `service`, `run_id`, and `proposal_id` where relevant.
- Never log secrets, session cookies or signatures' private material. LLM prompts/responses go to R2 (`llm_logs/`), not to stdout.

## Testing
- `pytest`. Coverage target 80% overall, **100% branch coverage** on `approval/`, `execution/guards.py`, `api/auth`.
- Required test categories:
  - **Look-ahead tests** for every signal (`03`).
  - **Reproducibility test** for the backtest (`04`).
  - **Safety tests:** the executor refuses unapproved, expired, tampered, under-threshold or already-executed proposals, and a non-paper URL. No module except `execution/` imports `TradingClient` (import-linter).
  - **Auth tests:** SIWE nonce reuse, wrong domain/chain, non-registry address → rejected. Approver endpoints are inaccessible without a session.
  - **Audit chain tests:** tampering with any row is detected (server and browser verifiers agree).
  - **Web e2e (Playwright):** visitor can browse every page. An approver (test wallet via a mock provider) can sign and see the threshold progress.
- External APIs are mocked with recorded fixtures (`respx` / `vcrpy`). Integration tests run against a disposable Postgres (docker or Neon branch).

## Git & CI
- Conventional commits. PRs need green CI: lint, types, tests (Python + web), generated-types check, e2e.
- Changes to `execution/`, `approval/`, `api/auth`, `config/risk.yaml`, `config/approvers.yaml` require a second reviewer (CODEOWNERS), or an explicit self-review note when working solo.

## Docs
- These spec files are the source of truth. Update the relevant spec in the same PR as any behavior change.
