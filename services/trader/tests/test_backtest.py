"""Backtest correctness: no look-ahead, sane metrics, parameters actually change results."""
import copy
import numpy as np
import pandas as pd
import pytest

from trader.backtest.engine import run_backtest, target_weights_as_of, all_tickers
from trader.settings import get_strategy, get_risk

@pytest.fixture(scope="module")
def closes():
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2019-01-01", periods=900)
    tickers = all_tickers() + ["SPY"]
    drift = rng.normal(0.0004, 0.0004, len(tickers))
    rets = rng.normal(drift, 0.02, (len(dates), len(tickers)))
    return pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=tickers)

def test_no_look_ahead(closes):
    """Equity up to a date must not change when later data is added."""
    cut = closes.index[-150]
    truncated = {p["date"]: p["equity"] for p in run_backtest(closes.loc[:cut])["equity_curve"]}
    full = {p["date"]: p["equity"] for p in run_backtest(closes)["equity_curve"]}
    # the truncated run treats its last day as a week end, so compare strictly before the cut
    common = [d for d in truncated if d in full and d < str(closes.index[-151].date())]
    assert len(common) > 50
    assert all(truncated[d] == full[d] for d in common)

def test_metrics_are_sane(closes):
    m = run_backtest(closes)["metrics"]
    assert -1.0 <= m["max_drawdown"] <= 0.0
    assert m["final_equity"] > 0
    assert 0 < m["volatility"] < 2

def test_parameters_change_results(closes):
    base = get_strategy()
    cand = copy.deepcopy(base)
    cand["top_n"] = base["top_n"] - 2
    assert run_backtest(closes, base)["metrics"] != run_backtest(closes, cand)["metrics"]

def test_target_weights_respect_limits(closes):
    w = target_weights_as_of(closes)
    limits = get_risk()["limits"]
    assert sum(w.values()) <= limits["max_gross_exposure"] + 1e-9
    assert all(v <= limits["max_etf_position"] + 1e-9 for v in w.values())
    assert "SPY" not in w
