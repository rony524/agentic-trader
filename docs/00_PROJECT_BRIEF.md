# 00 — Project Brief: Agentic Trader (Chips · Energy · Supply Chain)

## Why now
Amazon raised its 2026 capital spending plan to **$220B**, citing the cost of memory chips (per the challenge prompt).
AI buildout is now limited by three physical things: **chips** (especially memory), **energy** (power for data centers)
and **supply chains** (fabs, equipment, shipping, materials). News about these moves markets quickly, and the
effects spread unevenly across related companies. A system that keeps watching that news and keeps checking whether
a trading strategy still works is useful, as long as a human stays in control.

## What we are building
An **AI research agent** that:
1. **Tracks** public news and data on chips, energy and supply chains (see `02_DATA_SOURCES.md`).
2. **Turns** that information into structured signals and maps how a shock spreads (see `03`, `14`).
3. **Re-tests** a paper-trading strategy on fresh data on a schedule (see `04`, `05`).
4. **Proposes** changes to the strategy, each with a backtest, a diff and risk notes (see `06`, `07`).
5. **Waits** for a human to approve or reject every proposal and every order (see `08`, `15`).
6. **Executes** approved orders on an **Alpaca paper account only** (see `09`).
7. **Records** every step in a tamper-evident audit log (see `10`).
8. **Shows** everything in a public web app, deployed live (see `11`, `16`). Anyone can view it, and only
   registered approvers can act.

> "Live" refers to the **website**. Trading is always on an Alpaca **paper** account.

## Non-negotiable rules
| # | Rule | How it is enforced |
|---|------|--------------------|
| R1 | **Paper trading only.** No live brokerage, ever. | The broker client is hard-wired to `paper-api.alpaca.markets`. Startup fails if `ALPACA_PAPER != true` or the endpoint is not the paper one. There is no code path to a live endpoint. |
| R2 | **A human makes every decision.** | The agent has no order tool. Orders come only from the executor, which accepts only proposals that carry valid human approval signatures (`08`, `15`). |
| R3 | **No unverifiable claims.** | Every news-driven statement in a proposal cites a source URL and timestamp. |
| R4 | **No look-ahead.** | Every data point stores `published_at` and `retrieved_at`. Backtests use only data that was available at each point in time (`04`). |
| R5 | **Full audit trail.** | Every proposal, backtest, approval and order is hash-chained (`10`). |

## Users
- **Operator / approver** (you): signs in with a wallet, reads the daily digest, reviews proposals and signs approvals or rejections.
- **Co-approver(s)** (optional): give the second signature in multisig mode (`15`).
- **Visitor / judge**: opens the public URL without logging in, and should be able to follow the reasoning behind any trade
  and verify the approvals and audit log themselves.

## Success criteria (MVP)
- A daily run, completed end to end, that ingests ≥5 sources, updates signals, re-runs the baseline backtest and
  produces a digest.
- At least one agent proposal containing: the parameter diff, walk-forward backtest metrics compared with the baseline,
  risk notes and cited sources.
- An approval flow in which an approved proposal places paper orders on Alpaca and a rejected one places none.
- A **publicly deployed web app** showing signals, the shock map, proposals, the paper portfolio and the audit log,
  with approvals signed in the browser.
- The daily pipeline runs on a schedule in the cloud with no laptop involved.
- Zero code paths that place an order without a verified approval (checked by tests).

## Out of scope
- Live trading, margin, options, shorting (v0 is long-only and unlevered), crypto trading.
- Paid data feeds (we use free and public sources only).
- Investment advice. This is a research and educational tool.

## Document map
| File | Purpose |
|------|---------|
| 01_ARCHITECTURE | Components, data flow, tech stack |
| 02_DATA_SOURCES | What we ingest, from where, how often |
| 03_SIGNALS_AND_UNIVERSE | Tradable tickers and the signals derived from data |
| 04_BACKTESTING | Engine, methodology, anti-overfitting rules |
| 05_STRATEGY_SPEC | Baseline strategy and the parameters the agent may tune |
| 06_AGENT | Agent loop, tools, prompts, guardrails |
| 07_RISK | Portfolio limits, kill switches, risk notes format |
| 08_HUMAN_APPROVAL | Proposal lifecycle and approval UX |
| 09_PAPER_TRADING | Alpaca paper integration and the execution guardrails |
| 10_BLOCKCHAIN | Tamper-evident audit log and testnet anchoring |
| 11_DASHBOARD | Web app: pages, access model, API contract |
| 12_CONVENTIONS | Code style, layout, config, testing |
| 13_BUILD_PLAN | Phased plan with acceptance criteria |
| 14_SHOCK_PROPAGATION_MAP | Graph of how shocks spread across the universe |
| 15_MULTISIG_APPROVAL | M-of-N signed approvals |
| 16_DEPLOYMENT | Hosting, env vars, security, CI/CD, launch steps |

## Disclaimer
This is an educational paper-trading project. Nothing it produces is financial advice.
