"""Backtest engine: weekly rebalance, inverse-vol weights, caps, regime scaling.

Point-in-time: weights chosen at a rebalance date use only closes up to and including that date,
and are first applied to the *next* day's returns.

News/shock signals only exist from the day we started collecting them, so they have no history and
are 0 in the backtest. Only price-based parameters (top_n, hold_buffer, lookbacks, regime) can be tested.
"""
from __future__ import annotations
import hashlib, json, uuid
from typing import Any
import numpy as np
import pandas as pd

from trader.settings import get_universe, get_strategy, get_risk

SLIPPAGE_BPS = 5  # per side for large caps/ETFs
CASH_YIELD = 0.04  # annual, earned on the unallocated remainder
ETFS = {"SMH", "XLU", "XLE", "XLB", "URA", "SGOV"}
CASH_TICKER = "SGOV"
TEST_FRACTION = 0.3  # last 30% of the period is reported separately as the test window

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

def momentum_score(closes: pd.DataFrame, lb: dict) -> pd.DataFrame:
    """S1 for every date: 0.6 * rank(12-1 momentum) + 0.4 * rank(3m momentum), scaled to [-1, 1]."""
    mom_long = closes.shift(lb["mom_skip_days"]) / closes.shift(lb["mom_long_days"]) - 1
    mom_short = closes / closes.shift(lb["mom_short_days"]) - 1
    raw = 0.6 * mom_long.rank(axis=1, pct=True) + 0.4 * mom_short.rank(axis=1, pct=True)
    return raw * 2 - 1

def regime_multiplier(closes: pd.DataFrame, strat: dict) -> pd.Series:
    """Per date: multipliers[0] if SPY > its MA and SMH vol is calm, [1] if one fails, [2] if both fail."""
    reg = strat["regime"]
    mults = reg["multipliers"]
    fails = pd.Series(0, index=closes.index)
    if "SPY" in closes:
        spy = closes["SPY"]
        fails += (spy <= spy.rolling(reg["trend_ma_days"]).mean()).astype(int)
    if "SMH" in closes:
        vol20 = closes["SMH"].pct_change().rolling(20).std()
        fails += (vol20 / vol20.rolling(252, min_periods=60).median() >= reg["vol_threshold"]).astype(int)
    return fails.clip(0, 2).map(lambda f: mults[f])

def select_weights(scores: pd.Series, vol: pd.Series, held: set[str], strat: dict, risk: dict,
                   multiplier: float, smap: dict[str, str]) -> dict[str, float]:
    """Top-N by score (with hold buffer) → inverse-vol → regime scaling → position and sleeve caps.
    Whatever is left over stays in cash."""
    scores = scores.drop(CASH_TICKER, errors="ignore").dropna()
    scores = scores[vol.reindex(scores.index).notna()]
    ranked = scores.sort_values(ascending=False)
    top_n, buffer = strat["top_n"], strat["hold_buffer"]
    selected = [t for t in ranked.index[:top_n] if ranked[t] > strat["min_score"]]
    keep_zone = set(ranked.index[:top_n + buffer])
    selected += [t for t in held if t in keep_zone and t not in selected and ranked.get(t, -np.inf) > strat["min_score"]]
    if len(selected) < risk["limits"]["min_positions_when_invested"]:
        return {}

    inv_vol = 1.0 / vol[selected].clip(lower=1e-4)
    gross = strat["base_exposure"] * multiplier
    w = inv_vol / inv_vol.sum() * gross
    tilts = strat.get("sleeve_tilts") or {}
    if tilts:
        w = w * pd.Series({t: float(tilts.get(smap.get(t, ""), 1.0)) for t in w.index})
        if w.sum() > gross:  # an overweight tilt reshuffles weight between sleeves, never adds leverage
            w *= gross / w.sum()
    limits = risk["limits"]
    w = w.clip(upper=pd.Series({t: limits["max_etf_position"] if t in ETFS else limits["max_single_position"] for t in w.index}))
    sleeve_tot = w.groupby(lambda t: smap.get(t, "")).transform("sum")
    over = sleeve_tot > limits["max_sleeve_weight"]
    w[over] *= limits["max_sleeve_weight"] / sleeve_tot[over]
    return {t: float(v) for t, v in w.items() if v > 1e-6}

def target_weights_as_of(closes: pd.DataFrame, strategy: dict | None = None,
                         extra_scores: pd.Series | None = None, held: set[str] | None = None) -> dict[str, float]:
    """Live target weights at the last date in `closes`. `extra_scores` (news/shock part of the composite) is added on top."""
    strat = strategy or get_strategy()
    tradable = [t for t in all_tickers() if t in closes.columns]
    scores = momentum_score(closes[tradable], strat["lookbacks"]).iloc[-1] * strat["weights"]["momentum"]
    if extra_scores is not None:
        scores = scores.add(extra_scores.reindex(scores.index).fillna(0), fill_value=0)
    vol = closes[tradable].pct_change().rolling(strat["lookbacks"]["vol_days"]).std().iloc[-1]
    mult = float(regime_multiplier(closes, strat).iloc[-1])
    return select_weights(scores, vol, held or set(), strat, get_risk(), mult, sleeve_map())

def _metrics(equity: pd.Series, turnover: list[float]) -> dict[str, float]:
    rets = equity.pct_change().dropna()
    if len(rets) < 2:
        return {"cagr": 0.0, "volatility": 0.0, "sharpe": 0.0, "max_drawdown": 0.0, "avg_turnover": 0.0}
    growth = equity.iloc[-1] / equity.iloc[0]
    years = len(rets) / 252
    vol = rets.std() * np.sqrt(252)
    return {
        "cagr": round(float(growth ** (1 / years) - 1), 4),
        "volatility": round(float(vol), 4),
        "sharpe": round(float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0.0, 4),
        "max_drawdown": round(float((equity / equity.cummax() - 1).min()), 4),
        "avg_turnover": round(float(np.mean(turnover)) if turnover else 0.0, 4),
    }

def run_backtest(closes: pd.DataFrame, strategy: dict | None = None, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """Weekly rebalance on the last trading day of each week, executed from the next day's returns."""
    strat = strategy or get_strategy()
    risk = get_risk()
    smap = sleeve_map()
    lb = strat["lookbacks"]

    closes = closes.sort_index()
    tradable = [t for t in all_tickers() if t in closes.columns and t != CASH_TICKER]
    # indicators use the whole history (each row only looks backwards); the test window is trimmed afterwards
    scores = momentum_score(closes[tradable], lb) * strat["weights"]["momentum"]
    rets = closes[tradable].pct_change()
    vol = rets.rolling(lb["vol_days"]).std()
    mult = regime_multiplier(closes, strat)

    warmup = max(lb["mom_long_days"], lb["vol_days"], strat["regime"]["trend_ma_days"]) + 1
    dates = closes.index[warmup:]
    if start:
        dates = dates[dates >= pd.Timestamp(start)]
    if end:
        dates = dates[dates <= pd.Timestamp(end)]
    if len(dates) < 30:
        raise ValueError(f"Not enough history to backtest: {len(dates)} days after warm-up")

    week = pd.Series(dates, index=dates).dt.to_period("W")
    rebalance_days = set(week[week != week.shift(-1)].index)  # last trading day of each week

    equity, holdings = 1.0, {}  # holdings: ticker -> current weight (drifts with returns)
    curve, turnover = [], []
    daily_cash = CASH_YIELD / 252
    for d in dates:
        # 1) apply today's returns to yesterday's holdings
        r = rets.loc[d]
        invested = sum(holdings.values())
        day_ret = sum(w * (0.0 if np.isnan(r.get(t, np.nan)) else r[t]) for t, w in holdings.items())
        day_ret += (1 - invested) * daily_cash
        equity *= 1 + day_ret
        if holdings:
            holdings = {t: w * (1 + (0.0 if np.isnan(r.get(t, np.nan)) else r[t])) / (1 + day_ret) for t, w in holdings.items()}
        # 2) at the close of a rebalance day, pick new weights using data up to today only
        if d in rebalance_days:
            target = select_weights(scores.loc[d], vol.loc[d], set(holdings), strat, risk, float(mult.loc[d]), smap)
            tv = sum(abs(target.get(t, 0) - holdings.get(t, 0)) for t in set(target) | set(holdings))
            equity *= 1 - tv * SLIPPAGE_BPS / 10_000
            turnover.append(tv)
            holdings = target
        curve.append((d, equity))

    eq = pd.Series([e for _, e in curve], index=[d for d, _ in curve])
    split = eq.index[int(len(eq) * (1 - TEST_FRACTION))]
    full = _metrics(eq, turnover)
    full["final_equity"] = round(float(eq.iloc[-1]), 4)

    config_hash = hashlib.sha256(json.dumps(strat, sort_keys=True).encode()).hexdigest()[:12]
    step = max(1, len(curve) // 500)
    return {
        "id": f"bt_{uuid.uuid4().hex[:8]}",
        "kind": "baseline",
        "config_hash": config_hash,
        "metrics": full,
        "metrics_train": _metrics(eq[eq.index < split], []),
        "metrics_test": _metrics(eq[eq.index >= split], []),
        "test_start": str(split.date()),
        "equity_curve": [{"date": d.strftime("%Y-%m-%d"), "equity": round(float(e), 5)} for d, e in curve[::step]],
        "as_of_start": str(dates[0].date()),
        "as_of_end": str(dates[-1].date()),
        "config": strat,
    }
