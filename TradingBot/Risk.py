"""
Risk.py - risk rules that sit BETWEEN the strategy and order placement.

    Strategy.py  ->  "I want to BUY KO"
    Risk.py      ->  "OK, but only 40 shares" / "No, blocked because ..."
    Alpaca code  ->  places whatever Risk.py approved

Like Strategy.py, everything here is a pure function: state in, decision out. It
places no orders, so the SAME checks work in the backtest and in paper trading.
Every decision is written to risk_logger (see logs.py) with the reason.

The numbers in RiskLimits are reasonable STARTING POINTS, not magic values.
Pick yours deliberately - you'll want to justify them in your project write-up.

Rules (long-only):
  1. Position size cap     - no single stock above X% of total equity
  2. Total exposure cap    - stocks combined can't exceed Y% of equity
  3. Cash reserve          - always keep Z% of equity in cash
  4. Max open positions    - limit how many stocks are held at once
  5. Stop-loss             - exit a position that falls W% below its entry price
  6. Daily loss halt       - stop opening new positions after a bad day
  Exits (SELLs) are never blocked by these rules, only checked for sanity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor

try:
    from logs import risk_logger
except ImportError:  # lets this file run before logs.py is set up
    import logging
    risk_logger = logging.getLogger("risk")


# ------------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------------
@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.20      # one stock <= 20% of equity
    max_total_exposure_pct: float = 0.80  # all stocks <= 80% of equity
    min_cash_reserve_pct: float = 0.10  # keep >= 10% of equity in cash
    max_open_positions: int = 5
    stop_loss_pct: float = 0.08         # exit if price is 8% below entry
    max_daily_loss_pct: float = 0.03    # halt new buys if equity drops 3% in a day


# ------------------------------------------------------------------
# ACCOUNT STATE (what Risk.py needs to know)
# ------------------------------------------------------------------
@dataclass
class Position:
    shares: int
    entry_price: float
    last_price: float          # most recent price, for current value

    @property
    def market_value(self) -> float:
        return self.shares * self.last_price


@dataclass
class AccountState:
    cash: float
    day_start_equity: float    # equity at the start of today (for the daily loss rule)
    positions: dict = field(default_factory=dict)   # {"KO": Position(...)}

    @property
    def exposure(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    @property
    def equity(self) -> float:
        return self.cash + self.exposure


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    shares: int        # shares approved (0 if blocked)
    reason: str


# ------------------------------------------------------------------
# CHECKS
# ------------------------------------------------------------------
def trading_halted(state: AccountState, limits: RiskLimits = RiskLimits()) -> bool:
    """True if today's loss has hit the daily limit (blocks NEW buys only)."""
    if state.day_start_equity <= 0:
        return False
    loss = 1 - state.equity / state.day_start_equity
    return loss >= limits.max_daily_loss_pct


def stop_loss_triggered(position: Position, limits: RiskLimits = RiskLimits()) -> bool:
    return position.last_price <= position.entry_price * (1 - limits.stop_loss_pct)


def stops_to_execute(state: AccountState, limits: RiskLimits = RiskLimits()) -> list:
    """Tickers whose stop-loss has been hit. Call once per day/bar; SELL each one."""
    hits = [t for t, p in state.positions.items() if stop_loss_triggered(p, limits)]
    for t in hits:
        p = state.positions[t]
        risk_logger.warning(f"{t} STOP-LOSS: last {p.last_price:.2f} vs entry {p.entry_price:.2f} "
                            f"(limit {limits.stop_loss_pct:.0%})")
    return hits


def check_order(side: str, ticker: str, price: float, state: AccountState,
                requested_shares: int | None = None,
                limits: RiskLimits = RiskLimits()) -> RiskDecision:
    """
    Decide whether an order may go out, and for how many shares.
    requested_shares=None on a BUY means "as many as the rules allow".
    """
    side = side.upper()
    if price <= 0:
        return _decide(False, 0, f"{ticker} {side} blocked: invalid price {price}")

    # ---------------- SELL: only sanity checks ----------------
    if side == "SELL":
        held = state.positions.get(ticker)
        if held is None or held.shares <= 0:
            return _decide(False, 0, f"{ticker} SELL blocked: no position held")
        qty = held.shares if requested_shares is None else min(requested_shares, held.shares)
        return _decide(True, qty, f"{ticker} SELL {qty} approved")

    if side != "BUY":
        return _decide(False, 0, f"{ticker}: unknown side {side!r}")

    # ---------------- BUY: apply every rule ----------------
    if trading_halted(state, limits):
        return _decide(False, 0, f"{ticker} BUY blocked: daily loss limit "
                                 f"({limits.max_daily_loss_pct:.0%}) reached")
    if ticker in state.positions:
        return _decide(False, 0, f"{ticker} BUY blocked: already holding a position")
    if len(state.positions) >= limits.max_open_positions:
        return _decide(False, 0, f"{ticker} BUY blocked: {len(state.positions)} open positions "
                                 f"(max {limits.max_open_positions})")

    equity = state.equity
    by_position = floor(equity * limits.max_position_pct / price)
    by_exposure = floor((equity * limits.max_total_exposure_pct - state.exposure) / price)
    by_cash = floor((state.cash - equity * limits.min_cash_reserve_pct) / price)

    caps = {"position cap": by_position, "exposure cap": by_exposure, "cash reserve": by_cash}
    limit_name, max_shares = min(caps.items(), key=lambda kv: kv[1])
    if max_shares < 1:
        return _decide(False, 0, f"{ticker} BUY blocked: {limit_name} leaves room for 0 shares")

    qty = max_shares if requested_shares is None else min(requested_shares, max_shares)
    if requested_shares is not None and qty < requested_shares:
        return _decide(True, qty, f"{ticker} BUY reduced {requested_shares} -> {qty} by {limit_name}")
    return _decide(True, qty, f"{ticker} BUY {qty} approved (${qty * price:,.0f}, "
                              f"{qty * price / equity:.1%} of equity)")


def _decide(allowed: bool, shares: int, reason: str) -> RiskDecision:
    (risk_logger.info if allowed and "reduced" not in reason else risk_logger.warning)(reason)
    return RiskDecision(allowed, shares, reason)


# ------------------------------------------------------------------
# DEMO - run `python Risk.py` to see the rules fire
# ------------------------------------------------------------------
if __name__ == "__main__":
    state = AccountState(cash=10_000, day_start_equity=10_000)

    print(check_order("BUY", "KO", 60.0, state))                       # sized by position cap
    print(check_order("BUY", "NVDA", 120.0, state, requested_shares=500))  # reduced by a cap

    state.cash, state.positions = 4_000, {"KO": Position(100, 60.0, 60.0)}
    print(check_order("BUY", "KO", 60.0, state))                       # already held
    print(check_order("SELL", "MSFT", 400.0, state))                   # nothing to sell

    state.positions["KO"].last_price = 54.0                            # -10% from entry
    print("stops:", stops_to_execute(state))

    state.day_start_equity = 11_000                                    # equity now ~9,400 (-14%)
    print(check_order("BUY", "JNJ", 150.0, state))                     # daily halt