# 09 — Paper Trading (Alpaca)

## Account setup
1. Create a free account at alpaca.markets and open the **Paper Trading** dashboard.
2. Generate **paper** API keys (they are different from live keys).
3. Set them **only on the `executor` service** in Render (and in a local `.env` for development, never committed):
   ```
   ALPACA_API_KEY_ID=...
   ALPACA_API_SECRET_KEY=...
   ALPACA_PAPER=true
   EXPECTED_PAPER_ACCOUNT=PA...
   ```
   Optional: create a second paper account for local development so it never touches the production paper portfolio.
4. Optional: reset the paper account to $100,000 so results are easy to compare.

## Paper-only enforcement (defense in depth)
1. `execution/broker.py` constructs `TradingClient(key, secret, paper=True)`. The `paper` argument is a constant, not configurable.
2. On startup, the executor asserts that the client's base URL is `https://paper-api.alpaca.markets`, and aborts otherwise.
3. It asserts that `ALPACA_PAPER == "true"`, and aborts otherwise.
4. It fetches `/v2/account` and logs the account number. Any mismatch with `EXPECTED_PAPER_ACCOUNT` in config aborts.
5. A CI test greps the codebase for `api.alpaca.markets` (the live host) and fails if found outside this doc.
6. Only the `executor` service has the Alpaca secrets in its environment. `api`, `jobs` and `web` never receive them (`16`).
7. The web app shows a permanent PAPER MODE badge, and there is no setting anywhere that changes this.

## Market data duty
The executor also ingests Alpaca bars and news on schedule and writes them to Postgres, so no other service
needs Alpaca keys.

## Executor flow
```
loop every 60s during market hours:
  for proposal in queue.where(status == APPROVED and kind in {rebalance, risk_reduction}):
      verify signatures + threshold (15)         else → FAILED("bad signature")
      verify not expired                          else → EXPIRED
      verify not TRADING_FROZEN                   else → skip, alert
      fetch positions + latest prices
      recompute order list from target_weights   (sells first, then buys)
      run pre-trade checks (07)
      mark EXECUTING (audit)
      submit orders with client_order_id = f"{proposal_id}:{symbol}:{n}"
      poll until filled/canceled (timeout 10 min)
      mark EXECUTED / PARTIALLY_EXECUTED (audit, include fills)
```
- **Idempotency:** `client_order_id` prevents duplicate orders if the executor restarts.
- **Order type:** `market` with `time_in_force=day` for liquid names. Fractional quantities use `notional`.
- **Sells before buys** to free buying power.
- **No retries** after the proposal expires.

## Reconciliation (end of day)
- Pull positions/orders/activities from Alpaca, compare with the expected state from executed proposals and flag differences.
- Snapshot to `portfolio_snapshots(date, equity, cash, positions_json)`.
- Feed paper P&L into decay monitoring (`04`).

## Notes and limits of paper trading
- Paper fills are simulated: they don't reflect true market impact, queue position or some borrow/halts. Document this in reports.
- Free market data is the IEX feed (a subset of volume). Fine for daily strategy, not for microstructure.
- Paper trading has no real money at risk, but we keep all live-grade controls because building that discipline is part of the project.
