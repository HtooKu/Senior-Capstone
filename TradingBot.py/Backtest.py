"""
backtesting.py - long-only backtester for the MA-crossover strategy.

Runs today with NO database and NO other project files (it falls back to
stand-ins). Every spot you must fill in later is marked:

    >>> INSERT LATER <<<

Execution model (keeps it free of look-ahead bias):
  * A signal is generated from the CLOSE of day t.
  * The order fills on day t+1 (at the open if an 'open' column exists,
    otherwise that day's close) - never on the bar that produced the signal.
  * Slippage and commission are applied to every fill.

Usage:
    python backtesting.py
"""

import sys
import types
import numpy as np
import pandas as pd

# ==================================================================
# >>> INSERT LATER <<<  config.py and logging_setup.py
# ------------------------------------------------------------------
# strategy.py imports SHORT_WINDOW/LONG_WINDOW from config.py and
# decision_logger from logging_setup.py. You don't have those files yet,
# so this block creates temporary stand-ins so strategy.py can load.
# Once you create the real config.py and logging_setup.py, DELETE this
# whole block (the real files will be picked up automatically).
# ==================================================================
try:
    import config  # noqa: F401
except ImportError:
    config = types.ModuleType("config")
    config.SHORT_WINDOW = 20
    config.LONG_WINDOW = 50
    sys.modules["config"] = config

try:
    import logging_setup  # noqa: F401
except ImportError:
    import logging
    logging_setup = types.ModuleType("logging_setup")
    logging_setup.decision_logger = logging.getLogger("decisions")
    sys.modules["logging_setup"] = logging_setup
# ==================== end of temporary stand-ins ==================

# >>> INSERT LATER <<< If your strategy file isn't named strategy.py,
# change the module name on this line.
from strategy import generate_signals

TRADING_DAYS = 252

# Tickers from the project
TICKERS = ["KO", "NVDA", "JNJ", "MSFT", "RIVN"]


# ==================================================================
# DATA LOADING
# ==================================================================
def load_price_data(ticker: str) -> pd.DataFrame:
    """
    Must return a DataFrame that is:
      * indexed by date (DatetimeIndex), sorted ascending
      * has a 'close' column (required) and an 'open' column (recommended)

    >>> INSERT LATER <<<  your real historical database.
    Replace the body of this function with a query against your data
    source (e.g. the SEC EDGAR + Tiingo pipeline in data.py, a SQLite/
    Postgres query, or pd.read_csv(f"data/{ticker}.csv")).

    POINT-IN-TIME REMINDER: only return data that was actually known on
    each date. Prices should be split/dividend adjusted consistently, and
    any fundamentals must be keyed to the FILING date, not the fiscal
    period end date, or the backtest will peek into the future.

    Example of what the replacement might look like:
        # from data import get_prices            # <-- your future data.py
        # return get_prices(ticker, start="2018-01-01")
    """
    # ---- TEMPORARY: synthetic random-walk data so the file runs today ----
    # DELETE everything below once real data is wired in.
    seed = abs(hash(ticker)) % (2**32)
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=750, freq="B")
    close = 100 + np.cumsum(rng.normal(0.05, 1, size=750))
    open_ = close + rng.normal(0, 0.3, size=750)
    return pd.DataFrame({"open": open_, "close": close}, index=idx)


USING_SYNTHETIC_DATA = True  # >>> INSERT LATER <<< set to False once load_price_data uses real data


# ==================================================================
# CORE SIMULATION
# ==================================================================
def run_backtest(
    df: pd.DataFrame,
    ticker: str = "",
    initial_cash: float = 10_000.0,
    commission_bps: float = 0.0,   # Alpaca is commission-free
    slippage_bps: float = 5.0,     # 5 bps = fills 0.05% worse than quoted
):
    """Returns (equity_curve: DataFrame, trades: DataFrame)."""
    data = generate_signals(df, ticker=ticker)
    fill_col = "open" if "open" in data.columns else "close"

    cash = initial_cash
    shares = 0
    pending = None      # 'BUY'/'SELL' decided yesterday, fills today
    entry = None        # (date, price, shares, cost) of the open trade
    trades, equity_rows = [], []

    slip = slippage_bps / 10_000
    comm = commission_bps / 10_000

    for date, row in data.iterrows():
        # 1) Fill yesterday's order at today's open
        if pending == "BUY" and shares == 0:
            price = row[fill_col] * (1 + slip)
            qty = int(cash // (price * (1 + comm)))
            if qty > 0:
                cost = qty * price * (1 + comm)
                cash -= cost
                shares = qty
                entry = (date, price, qty, cost)
        elif pending == "SELL" and shares > 0:
            price = row[fill_col] * (1 - slip)
            proceeds = shares * price * (1 - comm)
            cash += proceeds
            trades.append(_trade(entry, date, price, proceeds))
            shares, entry = 0, None
        pending = None

        # 2) Mark to market at today's close
        equity_rows.append((date, cash + shares * row["close"], shares))

        # 3) Read today's close-based signal -> order for tomorrow
        if row["signal"] == "BUY" and shares == 0:
            pending = "BUY"
        elif row["signal"] == "SELL" and shares > 0:
            pending = "SELL"

    # Liquidate any open position at the final close so it counts in stats
    if shares > 0:
        last_date, last_row = data.index[-1], data.iloc[-1]
        price = last_row["close"] * (1 - slip)
        proceeds = shares * price * (1 - comm)
        cash += proceeds
        t = _trade(entry, last_date, price, proceeds)
        t["note"] = "closed at end of test"
        trades.append(t)
        equity_rows[-1] = (last_date, cash, 0)

    equity = pd.DataFrame(equity_rows, columns=["date", "equity", "shares"]).set_index("date")
    equity["benchmark"] = initial_cash * data["close"] / data["close"].iloc[0]
    return equity, pd.DataFrame(trades)


def _trade(entry, exit_date, exit_price, proceeds):
    entry_date, entry_price, qty, cost = entry
    return {
        "entry_date": entry_date, "entry_price": entry_price,
        "exit_date": exit_date, "exit_price": exit_price,
        "shares": qty, "pnl": proceeds - cost,
        "return_pct": (proceeds / cost - 1) * 100, "note": "",
    }


# ==================================================================
# METRICS
# ==================================================================
def _max_drawdown(series: pd.Series) -> float:
    return (series / series.cummax() - 1).min()


def compute_metrics(equity: pd.DataFrame, trades: pd.DataFrame) -> dict:
    rets = equity["equity"].pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    total = equity["equity"].iloc[-1] / equity["equity"].iloc[0] - 1
    bench = equity["benchmark"].iloc[-1] / equity["benchmark"].iloc[0] - 1
    sharpe = rets.mean() / rets.std() * np.sqrt(TRADING_DAYS) if rets.std() > 0 else np.nan

    m = {
        "total_return_pct": total * 100,
        "cagr_pct": ((1 + total) ** (1 / years) - 1) * 100,
        "sharpe": sharpe,
        "max_drawdown_pct": _max_drawdown(equity["equity"]) * 100,
        "buy_hold_return_pct": bench * 100,
        "buy_hold_max_dd_pct": _max_drawdown(equity["benchmark"]) * 100,
        "days_in_market_pct": (equity["shares"] > 0).mean() * 100,
        "num_trades": len(trades),
        "win_rate_pct": np.nan,
        "avg_trade_return_pct": np.nan,
    }
    if len(trades):
        m["win_rate_pct"] = (trades["pnl"] > 0).mean() * 100
        m["avg_trade_return_pct"] = trades["return_pct"].mean()
    return m


def print_report(ticker: str, metrics: dict, trades: pd.DataFrame):
    print(f"\n=== Backtest: {ticker} ===")
    for k, v in metrics.items():
        print(f"{k:<24}{v:>12.2f}" if isinstance(v, float) else f"{k:<24}{v:>12}")
    if len(trades):
        cols = ["entry_date", "exit_date", "entry_price", "exit_price", "return_pct"]
        print("\nTrades:")
        print(trades[cols].to_string(index=False, float_format=lambda x: f"{x:.2f}"))


# ==================================================================
# MAIN
# ==================================================================
def main():
    if USING_SYNTHETIC_DATA:
        print("!" * 60)
        print("WARNING: using SYNTHETIC random data - results are meaningless.")
        print("Wire real data into load_price_data() first.")
        print("!" * 60)

    summary = []
    for ticker in TICKERS:
        prices = load_price_data(ticker)
        equity, trades = run_backtest(prices, ticker=ticker)
        metrics = compute_metrics(equity, trades)
        print_report(ticker, metrics, trades)
        summary.append({"ticker": ticker, **metrics})

    print("\n=== SUMMARY ===")
    cols = ["ticker", "total_return_pct", "buy_hold_return_pct",
            "sharpe", "max_drawdown_pct", "num_trades"]
    print(pd.DataFrame(summary)[cols].to_string(index=False, float_format=lambda x: f"{x:.2f}"))

    # >>> INSERT LATER <<< optional: save results for your report, e.g.
    #     pd.DataFrame(summary).to_csv("backtest_summary.csv", index=False)
    #     equity.to_csv(f"equity_{ticker}.csv")

    # >>> INSERT LATER <<< Alpaca paper trading is NOT used here on purpose.
    # The same generate_signals() function feeds your live/paper-trading
    # file (tradingbot.py) - keep order placement out of this backtester.


if __name__ == "__main__":
    main()