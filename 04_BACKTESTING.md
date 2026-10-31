# 04 — Backtesting

## Purpose
1. Re-test the **current approved strategy** on the latest data every day, to detect decay.
2. Evaluate **candidate changes** proposed by the agent, using an identical methodology.

The engine is **deterministic, with no LLM involved**. The agent can only call it with parameters. It cannot
change the code or the results.

## Engine
- Daily bars, end-of-day signals, trades at the **next day's open** (no same-bar execution).
- Rebalance frequency set by the strategy (default weekly, Monday open).
- Inputs: `StrategyConfig` (pydantic), `as_of_start`, `as_of_end`, `universe`.
- Output: `BacktestResult` with equity curve, trades, daily weights, metrics, `config_hash`, `data_snapshot_hash`, `code_version` (git SHA).

## Realism assumptions
| Item | Default |
|------|---------|
| Commission | $0 (Alpaca) |
| Slippage | 5 bps per side for large caps/ETFs, 10 bps for others |
| Spread | Included in slippage |
| Fractional shares | Allowed (Alpaca supports fractional orders on many symbols) |
| Cash yield | SGOV/BIL return when held, else 0 |
| Corporate actions | Use split/dividend-adjusted closes |
| Survivorship | The universe is fixed by hand and small. Document that this introduces bias |

## Methodology: walk-forward
- History: as long as data allows (target 2015+ for price signals; shorter for news, since GDELT tone data is limited and LLM events exist only from project start).
- **Walk-forward:** train window 3 years, test window 6 months, step 6 months. Parameters are chosen in-sample and evaluated out-of-sample only.
- **Holdout:** the most recent 12 months are a **locked holdout**. They are used only for the final check on a proposal and are never used to tune.
- Signals with short history (S2/S3) get a separate "recent period" report. Their weight is capped until they have ≥2 years of out-of-sample evidence.

## LLM look-ahead (training cutoff)
An LLM that classifies a headline from before its training cutoff may already know what happened afterwards.
So events produced by the LLM are only valid as point-in-time data if they were classified live, at ingestion.
- Backtests that use LLM events include only events where `classified_at` ≤ the bar date. These are events
  ingested live since project start.
- Events backfilled from historical news (`in_sample_llm=true`) are excluded from walk-forward, holdout and
  acceptance-gate runs. They may appear only in exploratory reports, labelled as contaminated.
- Every `BacktestResult` that uses LLM events records the `model_id` values involved and their training cutoff dates.
- Details in `06_AGENT.md` → "Training-cutoff look-ahead".

## Metrics (reported for both baseline and candidate)
- CAGR, annualized volatility, Sharpe, Sortino, max drawdown, Calmar
- Turnover (annual), average holding period, hit rate
- Exposure by sleeve over time
- Benchmark comparison: SPY, SMH, equal-weight universe
- **Deflated Sharpe Ratio** (adjusts for the number of variants tried; the agent logs every variant it tested)
- Rolling 6-month Sharpe & drawdown chart

## Acceptance thresholds for a proposal
A candidate may be submitted for human review only if **all** of these hold:
1. Out-of-sample Sharpe ≥ baseline OOS Sharpe + 0.10, **or** max drawdown improves by ≥ 20% at a similar Sharpe (±0.05).
2. Deflated Sharpe probability > 0.90.
3. Holdout period is not worse than baseline by more than 0.2 Sharpe.
4. Turnover ≤ 1.5× baseline.
5. All risk limits (`07`) are respected at every rebalance.
6. Parameter change stays within the bounds in `05_STRATEGY_SPEC.md`.

Proposals that fail can still be logged as "rejected by gate", so the human can see what was tried.

## Decay monitoring (daily)
Compare the live paper P&L with the backtest replayed over the same period:
- Tracking error > 3% over 20 days → flag "execution drift".
- Rolling 6-month OOS Sharpe < 0 → flag "strategy decay", and the agent should investigate.

## Reproducibility
- Each result stores `config_hash`, `data_snapshot_hash` and `git_sha`. Re-running with the same three must give identical output (tested).
- Results are saved to R2 at `backtests/<id>/` (parquet + `report.json`). Summary metrics go to the Postgres
  `backtests` table, and the result hash is written to the audit log (`10`). The web app renders charts from these.
