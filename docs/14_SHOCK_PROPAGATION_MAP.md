# 14 — Shock Propagation Map

## Purpose
News describes a shock in one place ("DRAM contract prices up 15%"). Prices react across a chain of related
companies, often with delays and opposite signs. The shock map is a **directed, weighted graph** that turns
classified events into per-ticker exposures. It is explicit, inspectable and human-editable.

## Graph model (`config/shockmap.yaml`)
- **Nodes** are economic factors or companies.
- **Edges** `A → B` with `weight ∈ [-1, 1]` mean that "a +1 shock to A implies a `weight` shock to B", with optional `lag_days`.
- **Ticker nodes** are leaves (or near-leaves) that map into the universe.

### Factor nodes (v0)
| node_id | Description |
|---------|-------------|
| `dram_price` | DRAM/HBM contract & spot prices |
| `nand_price` | NAND prices |
| `ai_accel_demand` | Demand for GPUs/accelerators |
| `hyperscaler_capex` | Combined AMZN/MSFT/GOOGL/META capex |
| `hyperscaler_margins` | Hyperscaler operating margins (pressured by memory/component costs) |
| `foundry_capacity` | TSMC leading-edge & advanced packaging capacity |
| `litho_equipment_demand` | Demand for lithography/deposition/etch tools |
| `export_controls` | US/allied restrictions on chips/tools to China (+ = tighter) |
| `dc_power_demand` | Data-center electricity demand |
| `power_prices` | Wholesale/retail electricity prices |
| `natgas_price` | Henry Hub |
| `uranium_price` | Uranium spot/term |
| `grid_equipment_demand` | Transformers, switchgear, cooling |
| `copper_price` | Copper |
| `supply_chain_stress` | GSCPI / logistics disruptions |

### Example edges
```yaml
edges:
  - {from: hyperscaler_capex, to: ai_accel_demand,         weight:  0.8}
  - {from: hyperscaler_capex, to: dc_power_demand,         weight:  0.6, lag_days: 60}
  - {from: hyperscaler_capex, to: litho_equipment_demand,  weight:  0.4, lag_days: 30}
  - {from: ai_accel_demand,   to: dram_price,              weight:  0.6}   # HBM pull
  - {from: dram_price,        to: MU,                      weight:  0.9}
  - {from: dram_price,        to: hyperscaler_margins,     weight: -0.4}   # the Amazon capex story
  - {from: hyperscaler_margins, to: AMZN,                  weight:  0.5}
  - {from: hyperscaler_margins, to: MSFT,                  weight:  0.4}
  - {from: ai_accel_demand,   to: NVDA,                    weight:  0.9}
  - {from: ai_accel_demand,   to: TSM,                     weight:  0.6}
  - {from: foundry_capacity,  to: ai_accel_demand,         weight:  0.3}
  - {from: litho_equipment_demand, to: ASML,               weight:  0.8}
  - {from: litho_equipment_demand, to: AMAT,               weight:  0.7}
  - {from: export_controls,   to: ASML,                    weight: -0.5}
  - {from: export_controls,   to: AMAT,                    weight: -0.5}
  - {from: export_controls,   to: NVDA,                    weight: -0.3}
  - {from: dc_power_demand,   to: power_prices,            weight:  0.5}
  - {from: dc_power_demand,   to: grid_equipment_demand,   weight:  0.7}
  - {from: power_prices,      to: VST,                     weight:  0.7}
  - {from: power_prices,      to: CEG,                     weight:  0.6}
  - {from: dc_power_demand,   to: uranium_price,           weight:  0.3, lag_days: 90}
  - {from: uranium_price,     to: CCJ,                     weight:  0.8}
  - {from: grid_equipment_demand, to: GEV,                 weight:  0.7}
  - {from: grid_equipment_demand, to: ETN,                 weight:  0.6}
  - {from: grid_equipment_demand, to: VRT,                 weight:  0.7}
  - {from: grid_equipment_demand, to: copper_price,        weight:  0.3}
  - {from: copper_price,      to: FCX,                     weight:  0.8}
  - {from: natgas_price,      to: power_prices,            weight:  0.5}
  - {from: natgas_price,      to: XLE,                     weight:  0.5}
  - {from: supply_chain_stress, to: foundry_capacity,      weight: -0.4}
```
(Edge weights are **priors** set by hand. Phase 5+ may fit them from data, but any change goes through a proposal.)

## Propagation algorithm
```
input: events (node_id, direction, magnitude, confidence, ts)
for each event:
    s0 = direction * magnitude * confidence
    BFS/DFS from node_id up to max_depth = 3
    shock(child) += shock(parent) * edge.weight * damping (0.7 per hop)
    effective_date = event.ts + sum(lag_days on path)
exposure[ticker, t] = Σ shocks with effective_date ≤ t, decayed by half-life (05: shock_half_life_days)
```
- No cycles are allowed (validate the DAG on load). If feedback loops are needed later, cap iterations.
- Output: `shock_exposure[ticker]` (S3 in `03`) + an explanation trace (the path list) for the dashboard and proposals.

## Explainability
Every exposure comes with its paths, e.g.:
`AMZN: -0.29 ← hyperscaler_margins (-0.58) ← dram_price (+1.62) ← event evt_123 "DRAM contract prices +15% QoQ" [url]`

## Validation
- Event study: for historical events (hand-labeled set of ~30, e.g., export control announcements, major capex
  guidance changes), check whether the sign of the predicted exposure matches the 5-day abnormal return. Report the hit rate per edge.
- Edges with consistently wrong signs are flagged in the weekly digest as candidates for human review.
