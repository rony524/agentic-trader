# 05 — Strategy Spec

## Baseline strategy v0: "AI Bottleneck Rotation"
**Idea:** each sleeve (memory/compute, equipment, hyperscalers, power, energy inputs, materials) is limited by a
different bottleneck. Hold the names whose bottleneck is tightening and whose prices confirm it, and step down
to cash when the regime turns risk-off.

### Rules
1. **Rebalance:** weekly, decided on Friday close, executed Monday at the open (after approval).
2. **Score:** composite score from `03` with the weights below.
3. **Select:** the top `top_n` tickers by score with score > `min_score`.
4. **Weight:** inverse-volatility (60-day) among the selected, then apply caps (`07`).
5. **Regime scaling:** gross exposure = `base_exposure` × regime multiplier
   - SPY > 200DMA and `vol_regime` < 1.5 → 1.0
   - one of the two conditions fails → 0.6
   - both fail → 0.3
   - The remainder goes to the cash proxy.
6. **Hold buffer:** an existing position is kept unless its rank falls below `top_n + hold_buffer` (reduces turnover).

### Default config: `config/strategy.yaml`
```yaml
version: 0.1.0
rebalance: weekly
top_n: 8
hold_buffer: 3
min_score: 0.0
weights:
  momentum: 0.50
  news: 0.10
  shock: 0.15
  fundamentals: 0.25
lookbacks:
  mom_long_days: 252
  mom_skip_days: 21
  mom_short_days: 63
  vol_days: 60
shock_half_life_days: 10
base_exposure: 1.0
regime:
  trend_ma_days: 200
  vol_threshold: 1.5
  multipliers: [1.0, 0.6, 0.3]
```

## Tunable parameters (the agent may only propose changes within these bounds)
| Parameter | Min | Max | Max change per proposal |
|-----------|-----|-----|-------------------------|
| `top_n` | 4 | 12 | ±2 |
| `hold_buffer` | 0 | 5 | ±2 |
| `weights.*` (must sum to 1) | 0.0 | 0.6 | ±0.10 each |
| `weights.news` + `weights.shock` combined | — | 0.35 | — (until 2y OOS evidence) |
| `lookbacks.mom_short_days` | 21 | 126 | ±21 |
| `lookbacks.vol_days` | 20 | 120 | ±20 |
| `shock_half_life_days` | 3 | 30 | ±5 |
| `regime.vol_threshold` | 1.2 | 2.0 | ±0.2 |
| `regime.multipliers` | ordered, each in [0.2, 1.0] | | ±0.1 each |

**Not tunable by the agent** (needs a human-authored proposal): the universe, risk limits, rebalance frequency,
new signal families, `base_exposure > 1.0` (never allowed).

## Change types the agent may propose
1. **Parameter change**: within the bounds above.
2. **Rebalance orders**: the weekly target weights → order list (the standard weekly proposal).
3. **Ad-hoc risk reduction**: lower exposure after a major shock. The agent may propose reductions but never increases outside the weekly cycle.
4. **Hypothesis note**: a research note with no immediate change (e.g., "add ERCOT price signal"), for a human to consider.

## Versioning
- Each approved config is saved as `config/strategy_history/<version>.yaml` with the approval record ID.
- Semantic versioning: patch = param tweak, minor = new signal weight / universe change, major = rule change.
