# 03 — Signals and Universe

## Universe (v0, US-listed, liquid, long-only)
Stored in `config/universe.yaml`. Changing it requires a proposal (`08`).

| Sleeve | Tickers | Rationale |
|--------|---------|-----------|
| **Memory & compute** | MU, NVDA, AMD, AVGO, TSM, SMH (ETF) | Direct beneficiaries/victims of chip pricing & AI demand |
| **Semi equipment** | ASML, AMAT, LRCX, KLAC | Fab capex cycle, export-control exposure |
| **Hyperscalers** | AMZN, MSFT, GOOGL, META | Capex spenders. Memory costs pressure margins |
| **Power & grid** | VST, CEG, NRG, GEV, ETN, VRT, XLU (ETF) | Data-center electricity demand |
| **Energy inputs** | XLE (ETF), CCJ, URA (ETF) | Natgas/uranium for generation |
| **Materials / logistics** | FCX, XLB (ETF) | Copper for grid, supply stress |
| **Cash proxy** | SGOV or BIL | Parking when signals are weak |

Liquidity filter: 20-day average dollar volume > $50M. Price > $5.

## Signal families
Each signal is computed **point-in-time** (only data with `published_at <= t`), z-scored over a rolling 252-day
window and clipped to [-3, 3].

### S1. Price momentum (baseline)
- `mom_12_1`: 12-month return excluding the latest month.
- `mom_3m`: 63-day return.
- Cross-sectional rank within the universe.

### S2. Theme news intensity
- `news_vol_z[theme]`: z-score of the 7-day GDELT/RSS article count for the theme vs. its 90-day baseline.
- `news_tone[theme]`: mean tone over the 7 days.
- Mapped to tickers through theme→ticker exposures from the shock map (`14`).

### S3. Event shocks (LLM-classified)
- From the `events` table: each event has `node_id`, `direction ∈ {+1,-1}`, `magnitude ∈ {1,2,3}`, `confidence ∈ [0,1]`.
- Propagated through the shock map to give `shock_exposure[ticker]`, which decays with a half-life (default 10 trading days).

### S4. Fundamental nowcasts
- `memory_cycle`: YoY change in Korea semiconductor exports (and TSMC monthly revenue YoY), lagged by publication.
- `capex_revision`: + when a hyperscaler raises capex guidance in an 8-K/earnings release, − when it cuts.
  Affects equipment/power (+) and the spender's own margin risk (small −).
- `power_tightness`: z-score of EIA retail electricity price YoY + natgas price change.
- `supply_stress`: GSCPI level and its 3-month change.

### S5. Risk/regime
- `vol_regime`: 20-day realized volatility of SMH vs. its 1-year median.
- `market_trend`: SPY above/below its 200-day moving average.

## Composite score
```
score[ticker] = w_mom * S1 + w_news * S2 + w_shock * S3 + w_fund * S4_mapped
```
Weights live in `config/strategy.yaml` (see `05`). The regime signals (S5) **scale exposure**. They are not added to the score.

## Signal requirements
- Every signal function is pure: `f(store, as_of: datetime) -> pd.Series`.
- Unit test: the value computed at `as_of` must not change when data with `published_at > as_of` is added (look-ahead test).
- Each signal records a `coverage` metric (share of tickers with valid values). Signals with coverage < 80% are excluded that day.
