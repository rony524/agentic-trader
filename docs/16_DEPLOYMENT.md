# 16 — Deployment

Goal: a public URL anyone can open, running the full daily pipeline in the cloud on **paper trading only**.

## Hosting choices (all have free or low-cost tiers. Check current pricing before you commit)
| Piece | Provider | Why |
|-------|----------|-----|
| `web` | **Vercel** | Native Next.js hosting, preview deploys per PR |
| `api` | **Render** web service | Simple Python hosting, auto-deploy from GitHub |
| `jobs` | **Render** cron jobs | Scheduled runs of `trader jobs <name>` |
| `executor` | **Render** background worker | Always-on during market hours |
| Postgres | **Neon** | Managed Postgres, free tier, branching for previews |
| Object storage | **Cloudflare R2** | S3-compatible, free egress |
| Chain | **Sepolia** via a free RPC provider | Testnet anchoring (`10`) |
| Email | Resend (or similar) | Approval notifications |

Alternatives that work the same way: Railway or Fly.io instead of Render, Supabase instead of Neon. The
architecture doesn't depend on a particular provider. Every service is a Docker image, plus the Vercel app.

Expected cost at hobby scale is roughly $10–30/month (Render worker + cron + Anthropic usage). Treat that as an estimate.

## Repository → services
```
apps/web/            → Vercel project (root dir = apps/web)
services/trader/     → one Docker image, three Render services with different start commands:
    api       : uvicorn trader.api.main:app --host 0.0.0.0 --port $PORT
    executor  : trader-executor
    jobs-*    : trader jobs ingest | signals | agent | anchor   (one cron job each)
render.yaml          → Render Blueprint defining all of the above (infrastructure as code)
```

## Environment variables per service
| Variable | web | api | jobs | executor |
|----------|:---:|:---:|:----:|:--------:|
| `NEXT_PUBLIC_API_URL` | ✓ | | | |
| `NEXT_PUBLIC_CHAIN_ID` (11155111) | ✓ | ✓ | | ✓ |
| `DATABASE_URL` | | ✓ | ✓ | ✓ |
| `SESSION_SECRET` | | ✓ | | |
| `WEB_ORIGIN` (for CORS + SIWE domain) | | ✓ | | |
| `R2_*` (endpoint, key, secret, bucket) | | ✓ (read) | ✓ | |
| `ANTHROPIC_API_KEY` | | | ✓ | |
| `EIA_API_KEY`, `FRED_API_KEY`, `SEC_USER_AGENT` | | | ✓ | |
| `SEPOLIA_RPC_URL`, `ANCHOR_PRIVATE_KEY`, `AUDIT_ANCHOR_ENABLED` | | | ✓ | |
| `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `ALPACA_PAPER=true`, `EXPECTED_PAPER_ACCOUNT` | | | | ✓ |
| `AGENT_ENABLED`, `TRADING_FROZEN` (defaults; runtime toggles live in DB) | | | ✓ | ✓ |
| `RESEND_API_KEY` | | ✓ | | |

Secrets are set in each provider's dashboard and never committed. Each service gets **only** the variables in its column.

## Database
- Schema managed by **Alembic**. Migrations run as a Render pre-deploy command for `api`.
- Separate Postgres roles:
  - `app_api`: read all, write `proposals`, `signatures`, `controls`, `sessions`. INSERT only on `audit_log`.
  - `app_jobs`: write data/signal/event/backtest/proposal tables. INSERT only on `audit_log`.
  - `app_executor`: write orders/fills/snapshots/bars and proposal execution status. INSERT only on `audit_log`.
  - No role has UPDATE/DELETE on `audit_log`, and a trigger also blocks them (`10`).
- Daily automated backups (Neon point-in-time restore).

## Security checklist (public internet)
- [ ] HTTPS everywhere (provided by Vercel/Render).
- [ ] CORS on `api` allows only `WEB_ORIGIN`.
- [ ] SIWE: server-issued single-use nonce, domain + chainId checked, 5-minute nonce expiry.
- [ ] Approver-only endpoints check the session address against the registry **and** the action is signed. The executor re-verifies signatures regardless.
- [ ] Rate limiting on `api` (e.g., 60 req/min/IP for public routes, stricter on auth).
- [ ] Security headers on `web`: CSP, HSTS, X-Frame-Options DENY, Referrer-Policy.
- [ ] Error responses never include stack traces or secret values.
- [ ] Dependabot + `pip-audit` / `npm audit` in CI.
- [ ] Anchor wallet holds testnet ETH only. Alpaca keys are paper keys only.

## CI/CD (GitHub Actions)
1. On PR: lint, type-check, tests (Python + web), OpenAPI → TS type generation check, Playwright e2e against a Neon branch DB.
2. Vercel creates a preview deploy per PR. Render preview environments are optional.
3. On merge to `main`: Vercel production deploy, Render auto-deploys `api` / `executor` / `jobs` and runs migrations.
4. Post-deploy smoke test: `GET /healthz`, `GET /status`, and the web home page renders.

## Environments
| Env | Web | Backend | DB | Alpaca |
|-----|-----|---------|----|--------|
| local | `pnpm dev` | `docker compose up` (api + executor + Postgres + MinIO) | local Postgres | paper account #2 (optional) |
| preview | Vercel preview | optional | Neon branch | none (executor disabled) |
| production | Vercel prod | Render | Neon main | paper account #1 |

## Monitoring
- Status page section in the web app driven by `service_heartbeats` and source freshness.
- Render log streams + alerts on job failure (email).
- Alerts: missed daily agent run, executor heartbeat > 5 min old during market hours, audit chain verification failure, anchoring failure 2 nights in a row.

## Launch steps (first deploy)
1. Create Neon project → run migrations locally against it → create the three DB roles.
2. Create R2 bucket + access keys.
3. Create the Alpaca paper account + keys. Note the account number.
4. Deploy `AuditAnchor` to Sepolia (`10`). Fund the anchor wallet from a faucet.
5. Push `render.yaml` → create the Render Blueprint → set env vars per service.
6. Import `apps/web` into Vercel → set `NEXT_PUBLIC_API_URL` → deploy.
7. Add approver addresses to `config/approvers.yaml` → deploy.
8. Run `trader jobs ingest` and `trader jobs agent` manually once from Render shell. Check the web app.
9. Optional: add a custom domain to Vercel (and `api.` subdomain on Render), then update `WEB_ORIGIN`.
