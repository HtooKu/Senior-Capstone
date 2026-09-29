"""
Strategy A: Moving-Average Crossover

Pure function: takes a DataFrame of price data in, returns a DataFrame
of signals out. No side effects, no order placement here — that
separation matters so this exact function works identically in
backtesting (Week 7) and live paper trading (Week 11).

Rule:
  BUY  when short SMA crosses above long SMA (short was <= long, now >)
  SELL when short SMA crosses below long SMA (short was >= long, now <)
  HOLD otherwise
"""

import pandas as pd
from config import SHORT_WINDOW, LONG_WINDOW
from logging_setup import decision_logger


def generate_signals(df: pd.DataFrame, ticker: str = "") -> pd.DataFrame:
    """
    df must have a 'close' column, sorted by date ascending, indexed by date.
    Returns df with 'sma_short', 'sma_long', and 'signal' columns added.
    signal is one of: 'BUY', 'SELL', 'HOLD'
    """
    df = df.copy()

    # Rolling averages — min_periods ensures we don't produce a signal
    # before we actually have enough history (avoids look-ahead / garbage
    # signals in the first N rows).
    df["sma_short"] = df["close"].rolling(window=SHORT_WINDOW, min_periods=SHORT_WINDOW).mean()
    df["sma_long"] = df["close"].rolling(window=LONG_WINDOW, min_periods=LONG_WINDOW).mean()

    df["signal"] = "HOLD"

    # Detect the crossover itself, not just "short > long" (which would
    # re-trigger BUY every single day the short stays above the long).
    above = df["sma_short"] > df["sma_long"]
    prev_above = above.shift(1)

    crossed_up = above & (prev_above == False)     # noqa: E712
    crossed_down = (above == False) & (prev_above == True)  # noqa: E712

    df.loc[crossed_up, "signal"] = "BUY"
    df.loc[crossed_down, "signal"] = "SELL"

    # Log every non-HOLD decision with the reasoning
    for date, row in df[df["signal"] != "HOLD"].iterrows():
        decision_logger.info(
            f"{ticker} {date} {row['signal']} "
            f"(sma_short={row['sma_short']:.2f}, sma_long={row['sma_long']:.2f})"
        )

    return df


if __name__ == "__main__":
    # Quick smoke test with synthetic data so you can run this file
    # directly and see it work before wiring in real historical data.
    import numpy as np

    dates = pd.date_range("2023-01-01", periods=200, freq="B")
    rng = np.random.default_rng(seed=42)
    prices = 100 + np.cumsum(rng.normal(0, 1, size=200))

    df = pd.DataFrame({"close": prices}, index=dates)
    result = generate_signals(df, ticker="TEST")

    print(result[result["signal"] != "HOLD"][["close", "sma_short", "sma_long", "signal"]])
    print(f"\nTotal signals: {(result['signal'] != 'HOLD').sum()}")