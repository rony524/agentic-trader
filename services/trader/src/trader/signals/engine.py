"""Signals engine: momentum, news, shock, regime."""
from __future__ import annotations
import datetime as dt
import pandas as pd
import numpy as np

from trader.backtest.engine import all_tickers, sleeve_map
from trader.settings import get_strategy

THEME_KEYWORDS = {
    "memory": ["dram", "hbm", "memory", "nand", "micron", "mu ", "flash"],
    "ai_capex": ["capex", "data center", "ai ", "gpu", "accelerator", "hyperscaler", "cloud spend"],
    "power": ["power", "electricity", "grid", "utility", "nuclear", "uranium", "energ"],
    "fab_supply": ["fab", "foundry", "tsmc", "wafer", "litho", "equipment", "asml", "semiconductor"],
    "policy": ["export control", "tariff", "sanction", "regulation", "chip act"],
    "logistics": ["shipping", "supply chain", "logistics", "port", "freight"],
}

def compute_composite_signals(
    closes: pd.DataFrame,
    news_scores: dict[str, float] | None = None,
    shock_exposures: dict[str, float] | None = None,
    strategy: dict | None = None,
) -> pd.DataFrame:
    strat = strategy or get_strategy()
    weights = strat["weights"]
    lb = strat["lookbacks"]
    tickers = [t for t in closes.columns if t != "SGOV"]
    returns = closes.pct_change()

    # S1 momentum
    mom_long = ((closes.shift(lb["mom_skip_days"]) / closes.shift(lb["mom_long_days"])) - 1).iloc[-1]
    mom_short = ((closes / closes.shift(lb["mom_short_days"])) - 1).iloc[-1]
    s1_raw = 0.6 * mom_long.rank(pct=True) + 0.4 * mom_short.rank(pct=True)
    s1 = s1_raw * 2 - 1

    # S2 news
    s2 = pd.Series(news_scores or {}, dtype=float)
    if len(s2) > 0:
        s2 = s2.clip(-3, 3)
    else:
        s2 = pd.Series(0.0, index=tickers)

    # S3 shock
    s3 = pd.Series(shock_exposures or {}, dtype=float).clip(-3, 3)
    if len(s3) == 0:
        s3 = pd.Series(0.0, index=tickers)

    # S5 regime
    vol60 = returns.rolling(lb["vol_days"]).std().iloc[-1]
    spy_vol = vol60.get("SPY", 0.02)
    vol_regime = 1.0 if spy_vol < strat["regime"]["vol_threshold"] * 0.015 else 0.0

    # Composite
    all_tickers_list = all_tickers()
    composite = pd.Series(0.0, index=all_tickers_list)
    for t in all_tickers_list:
        v = 0.0
        v += weights["momentum"] * s1.get(t, 0)
        v += weights["news"] * s2.get(t, 0)
        v += weights["shock"] * s3.get(t, 0)
        v += weights["fundamentals"] * 0  # dropped for hackathon
        composite[t] = v

    df = pd.DataFrame({
        "s1_momentum": [s1.get(t, 0) for t in all_tickers_list],
        "s2_news": [s2.get(t, 0) for t in all_tickers_list],
        "s3_shock": [s3.get(t, 0) for t in all_tickers_list],
        "s4_fund": [0.0 for _ in all_tickers_list],
        "composite": [composite[t] for t in all_tickers_list],
        "vol_regime": [vol_regime for _ in all_tickers_list],
        "market_trend": [1.0 for _ in all_tickers_list],
    }, index=all_tickers_list)

    df["rank"] = df["composite"].rank(ascending=False, na_option="bottom").fillna(len(all_tickers_list)).astype(int)
    df = df.sort_values("rank")
    return df
