"""
Portfolio.py - backtest all tickers together in ONE account, with Risk.py
approving every order.

Same timing as Backtest.py: a signal from day t's close becomes an order that
fills at day t+1's open, with slippage. Differences:
  * one shared $10,000 account instead of $10,000 per stock
  * Risk.py sizes every BUY (position cap, exposure cap, cash reserve, max positions)
  * Risk.py's stop-loss and daily-loss halt are active
  * the benchmark is SPY buy-and-hold

Run from the outer project folder (the one containing data/).
"""

import logging

import pandas as pd

from Backtest import TICKERS, compute_metrics
from Data import load_price_data
from logs import risk_logger
from Risk import AccountState, Position, RiskLimits, check_order, stops_to_execute
from Strategy import generate_signals

# 5 positions x 18% = 90% invested, 10% cash
LIMITS = RiskLimits(max_position_pct=0.18, max_total_exposure_pct=0.90,
                    min_cash_reserve_pct=0.10, max_open_positions=5)


def _trade_row(ticker, pos, entry_date, exit_date, exit_price, note=""):
    return {
        "ticker": ticker, "entry_date": entry_date, "exit_date": exit_date,
        "entry_price": pos.entry_price, "exit_price": exit_price,
        "shares": pos.shares,
        "pnl": pos.shares * (exit_price - pos.entry_price),
        "return_pct": (exit_price / pos.entry_price - 1) * 100,
        "note": note,
    }


def run_portfolio(initial_cash=10_000.0, slippage_bps=5.0, limits=LIMITS):
    slip = slippage_bps / 10_000
    data = {t: generate_signals(load_price_data(t), ticker=t) for t in TICKERS}
    dates = sorted(set().union(*[d.index for d in data.values()]))

    state = AccountState(cash=initial_cash, day_start_equity=initial_cash)
    entry_dates = {}
    pending = {}          # ticker -> "BUY"/"SELL", decided yesterday, fills today
    trades, rows = [], []

    for date in dates:
        today = {t: d.loc[date] for t, d in data.items() if date in d.index}

        # 1) Mark held positions at today's open
        for t, pos in state.positions.items():
            if t in today:
                pos.last_price = today[t]["open"]

        # 2a) Fill SELLs first so the cash is available for BUYs
        for t in [t for t, side in pending.items() if side == "SELL"]:
            if t in state.positions and t in today:
                pos = state.positions[t]
                price = today[t]["open"] * (1 - slip)
                decision = check_order("SELL", t, price, state)
                if decision.allowed:
                    state.cash += decision.shares * price
                    trades.append(_trade_row(t, pos, entry_dates.pop(t), date, price))
                    del state.positions[t]

        # 2b) Fill BUYs - Risk.py decides how many shares (if any)
        for t in [t for t, side in pending.items() if side == "BUY"]:
            if t in today and t not in state.positions:
                price = today[t]["open"] * (1 + slip)
                decision = check_order("BUY", t, price, state, limits=limits)
                if decision.allowed:
                    state.cash -= decision.shares * price
                    state.positions[t] = Position(decision.shares, price, today[t]["open"])
                    entry_dates[t] = date
        pending.clear()

        # 3) Mark everything at today's close
        for t, pos in state.positions.items():
            if t in today:
                pos.last_price = today[t]["close"]
        equity = state.equity
        rows.append((date, equity, len(state.positions)))

        # 4) Stop-losses and today's signals -> orders for tomorrow
        for t in stops_to_execute(state, limits):
            pending[t] = "SELL"
        for t, row in today.items():
            if t in pending:
                continue
            if row["signal"] == "SELL" and t in state.positions:
                pending[t] = "SELL"
            elif row["signal"] == "BUY" and t not in state.positions:
                pending[t] = "BUY"

        state.day_start_equity = equity   # reference point for tomorrow's loss halt

    # Close anything still open at the final close so it counts in the stats
    for t, pos in list(state.positions.items()):
        price = data[t]["close"].iloc[-1] * (1 - slip)
        state.cash += pos.shares * price
        trades.append(_trade_row(t, pos, entry_dates.pop(t), data[t].index[-1],
                                 price, "closed at end of test"))
        del state.positions[t]
    rows[-1] = (rows[-1][0], state.cash, 0)

    equity = pd.DataFrame(rows, columns=["date", "equity", "shares"]).set_index("date")
    spy = load_price_data("SPY")["close"].reindex(equity.index).ffill().bfill()
    equity["benchmark"] = initial_cash * spy / spy.iloc[0]
    return equity, pd.DataFrame(trades)


def main():
    # keep Risk.py's lines in log_files/risk.log but off the console
    for h in risk_logger.handlers:
        if type(h) is logging.StreamHandler:
            h.setLevel(logging.ERROR)

    equity, trades = run_portfolio()
    metrics = compute_metrics(equity, trades)

    print("\n=== PORTFOLIO (shared account, Risk.py rules) ===")
    print("(buy_hold_* below = SPY buy-and-hold)")
    for k, v in metrics.items():
        print(f"{k:<24}{v:>12.2f}" if isinstance(v, float) else f"{k:<24}{v:>12}")

    print("\nBy ticker (trade count, total $ P&L):")
    print(trades.groupby("ticker")["pnl"].agg(["count", "sum"]).round(2).to_string())


if __name__ == "__main__":
    main()