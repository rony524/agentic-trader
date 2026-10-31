"""Backtest engine: weekly rebalance, inverse-vol weights, regime scaling."""
from __future__ import annotations
import hashlib, json, uuid, datetime as dt
from typing import Any
import numpy as np
import pandas as pd

from trader.settings import get_universe, get_strategy, get_risk

SLIPPAGE_BPS = 5  # per side for large caps/ETFs

def all_tickers() -> list[str]:
    uni = get_universe()
    out = []
    for sleeve in uni["universe"]:
        out.extend(sleeve["tickers"])
    return out

def sleeve_map() -> dict[str, str]:
    uni = get_universe()
    m = {}
    for sleeve in uni["universe"]:
        for t in sleeve["tickers"]:
            m[t] = sleeve["sleeve"]
    return m

def compute_signals(closes: pd.DataFrame, strategy: dict | None = None) -> pd.DataFrame:
    """Compute S1 momentum + S5 regime from daily closes. Index=ticker, columns=signal values."""
    strat = strategy or get_strategy()
    lb = strat["lookbacks"]
    long_lb = lb["mom_long_days"]
    skip = lb["mom_skip_days"]
    short_lb = lb["mom_short_days"]
    vol_days = lb["vol_days"]

    returns = closes.pct_change()
    mom_long = (closes.shift(skip) / closes.shift(long_lb)) - 1
    mom_short = (closes / closes.shift(short_lb)) - 1
    vol = returns.rolling(vol_days).std() * np.sqrt(252)

    df = pd.DataFrame({
        "mom_12_1": mom_long.iloc[-1],
        "mom_3m": mom_short.iloc[-1],
        "vol": vol.iloc[-1],
    })
    # rank momentum cross-sectionally
    df["s1"] = df["mom_12_1"].rank(pct=True) * 2 - 1  # -1..1

    # Regime: SPY above 200DMA and vol < threshold
    regime_cfg = strat["regime"]
    spy_vol = df.loc["SPY", "vol"] if "SPY" in df.index else 1.0
    vol_regime = 1.0 if spy_vol < regime_cfg["vol_threshold"] else 0.0
    return df, vol_regime

def run_backtest(closes: pd.DataFrame, strategy: dict | None = None, start: str = "2020-01-01", end: str | None = None) -> dict[str, Any]:
    """Weekly rebalance, inverse-vol weights, regime scaling. Returns metrics + equity curve."""
    strat = strategy or get_strategy()
    risk = get_risk()
    smap = sleeve_map()
    top_n = strat["top_n"]
    hold_buffer = strat["hold_buffer"]
    min_score = strat["min_score"]
    base_exposure = strat["base_exposure"]
    multipliers = strat["regime"]["multipliers"]
    vol_threshold = strat["regime"]["vol_threshold"]

    if end is None:
        end = str(closes.index.max().date())

    closes = closes.loc[start:end]
    returns = closes.pct_change().fillna(0)

    sig_df, _ = compute_signals(closes, strat)

    # weekly rebalance on Mondays
    rebalance_dates = closes.resample("W-MON").last().index
    rebalance_dates = [d for d in rebalance_dates if d in closes.index]

    cash = 1.0
    weights: dict[str, float] = {}
    equity_curve = []
    holdings = set()
    daily_equity = pd.Series(dtype=float)
    prev_weights = {}

    for i, rd in enumerate(rebalance_dates):
        # compute target weights from signals
        scores = sig_df["s1"].copy()
        selected = scores.nlargest(top_n)
        selected = selected[selected > min_score]
        # hold buffer: keep existing positions in top_n+hold_buffer
        ranked = scores.nlargest(top_n + hold_buffer)
        for h in holdings:
            if h in ranked.index and h not in selected.index:
                selected[h] = scores.get(h, 0)

        if len(selected) < 2:
            target = {"SGOV": base_exposure}
        else:
            inv_vol = 1.0 / sig_df.loc[selected.index, "vol"].clip(lower=0.01)
            w = inv_vol / inv_vol.sum()
            gross = base_exposure * 1.0  # simplified regime: 1.0 if conditions pass
            target = {t: float(v * gross) for t, v in w.items()}
            # apply caps
            for t in target:
                sleeve = smap.get(t, "")
                cap = risk["limits"]["max_etf_position"] if t in ("SMH","XLU","XLE","XLB","URA","SGOV") else risk["limits"]["max_single_position"]
                target[t] = min(target[t], cap)

        # turnover
        total_turnover = sum(abs(target.get(t, 0) - weights.get(t, 0)) for t in set(list(target) + list(weights)))

        # simulate forward returns from this rebalance to next
        start_idx = closes.index.get_loc(rd)
        end_idx = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else closes.index[-1]
        end_idx = closes.index.get_loc(end_idx) if isinstance(end_idx, pd.Timestamp) else start_idx

        port_ret = 0.0
        for j in range(start_idx, min(end_idx, len(closes) - 1) + 1):
            day = closes.index[j]
            day_ret = 0.0
            for t, w in target.items():
                if t in returns.columns:
                    day_ret += w * returns.iloc[j][t]
            cash_yield = target.get("SGOV", 0) * 0.05 / 252
            port_ret += day_ret + cash_yield
            equity_curve.append({"date": day.strftime("%Y-%m-%d"), "equity": float(port_ret)})

        weights = target
        holdings = set(target.keys())
        prev_weights = target

    final_equity = equity_curve[-1]["equity"] if equity_curve else 1.0

    # metrics
    eq_series = pd.Series([e["equity"] for e in equity_curve])
    daily_rets = eq_series.pct_change().dropna()
    cagr = (final_equity ** (252 / max(len(daily_rets), 1))) - 1 if len(daily_rets) > 0 else 0
    vol = daily_rets.std() * np.sqrt(252) if len(daily_rets) > 0 else 0
    sharpe = cagr / vol if vol > 0 else 0
    cummax = eq_series.cummax()
    dd = (eq_series - cummax) / cummax
    max_dd = float(dd.min()) if len(dd) > 0 else 0
    turnover = total_turnover if 'total_turnover' in dir() else 0

    config_hash = hashlib.sha256(json.dumps(strat, sort_keys=True).encode()).hexdigest()[:12]

    return {
        "id": f"bt_{uuid.uuid4().hex[:8]}",
        "kind": "baseline",
        "config_hash": config_hash,
        "metrics": {
            "cagr": round(float(cagr), 4),
            "volatility": round(float(vol), 4),
            "sharpe": round(float(sharpe), 4),
            "max_drawdown": round(float(max_dd), 4),
            "turnover": round(float(turnover), 4),
            "final_equity": round(float(final_equity), 6),
        },
        "equity_curve": equity_curve[::max(1, len(equity_curve)//500)],  # downsample
        "as_of_start": start,
        "as_of_end": end,
        "config": strat,
    }
