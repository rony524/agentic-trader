# 07 — Risk

Even in paper trading, risk limits are enforced as if the money were real. They are what makes the backtest meaningful.

## Portfolio limits (`config/risk.yaml`, only changeable by a human-authored proposal)
| Limit | Value |
|-------|-------|
| Leverage | None. Gross exposure ≤ 100% of equity |
| Shorting | Not allowed (v0) |
| Max single position | 15% of equity (ETFs: 25%) |
| Max sleeve weight | 40% |
| Min positions when invested | 4 |
| Max single-day turnover | 50% of equity (except an approved risk_reduction) |
| Max orders per day | 30 |
| Order size floor | $50 (skip dust) |
| Allowed order types | Market-on-open / limit within 1% of last price. No stop-market in v0 |

## Kill switches
| Trigger | Action |
|---------|--------|
| Paper equity drawdown ≥ 15% from peak | Freeze new buys. Only risk_reduction proposals are allowed until a human resets |
| Daily paper loss ≥ 5% | Flag the dashboard as red. The agent must write an incident note |
| Data staleness: >2 core sources stale | Agent cannot draft rebalance proposals |
| Backtest/live tracking error > 5% (20d) | Pause proposals, investigate |
| Manual | "Freeze trading" toggle in the web app (approvers only, audited) or `TRADING_FROZEN=true` on the executor. The executor refuses all orders |

## Pre-trade checks (executor, `09`)
Run on the **final order list** immediately before submission:
1. The proposal is APPROVED, its signatures are valid (`15`) and it has not expired.
2. Account is a paper account (`account.account_number` starts with `PA` / API base URL check).
3. Post-trade weights respect all limits above.
4. Price drift since approval ≤ 3% per ticker. Otherwise skip that ticker and log it.
5. Market is open (Alpaca clock API).
6. The proposal has not been executed before (idempotency key = proposal ID).

## Risk notes (required section in every proposal)
```yaml
risk_notes:
  summary: "One paragraph in plain English."
  concentration: {top_position: "VST 14.8%", top_sleeve: "Power 38%"}
  factor_exposure: "High beta to SMH (β≈1.3), moderate rate sensitivity via utilities"
  scenario_tests:            # computed by code, not invented by LLM
    - name: "2022 semis drawdown replay"     # Jan–Oct 2022
      candidate_return: -0.21
      baseline_return: -0.24
    - name: "Aug 2024 vol spike"
      ...
    - name: "Memory price shock −20% (shock map)"
      ...
  what_could_go_wrong:
    - "Capex guidance cuts at next earnings would hit equipment + power together"
    - "News signal has <2y of OOS history"
  liquidity: "All names > $500M ADV; no issue at paper size"
  model_risk: "Agent tested 4 variants; DSR prob 0.93"
  reversibility: "Fully reversible next rebalance"
```
Scenario numbers are produced by the backtest engine/shock map. The LLM only writes the prose around them.

## Risk reporting
- Daily: VaR (95%, historical 1y) and expected shortfall of current paper portfolio, exposure by sleeve, beta to SPY/SMH.
- Weekly: risk report attached to the rebalance proposal.
