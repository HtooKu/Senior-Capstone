# livetrading.py
import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce  # noqa: F401


def place_order(client, symbol, side, qty, ref_price, dry_run=True):
    "Checking if the account is ready to trade"
    clock = client.get_clock()
    if clock.is_open:
        return False, "Market is open. Wait until market closes to trade."
    today = clock.timestamp.date()
    calendar = client.get_calendar(GetCalendarRequest(start=today, end=today))
    if not calendar:
        return False, "No trading calendar for today. Market is closed."

    if clock.next_open.date() <= today:
       return False, "Market is closed, but next open is today. Wait until market opens to trade."
    return True, "Market is closed. Ready to trade another day."


def ready_to_trade(client):
    "Checking if the account is ready to trade"
    clock = client.get_clock()
    if clock.is_open:
        return False, "Market is open. Wait until market closes to trade."
    today = clock.timestamp.date()
    calendar = client.get_calendar(GetCalendarRequest(start=today, end=today))
    if not calendar:
        return False, "No trading calendar for today. Market is closed."

    if clock.next_open.date() <= today:
       return False, "Market is closed, but next open is today. Wait until market opens to trade."
    return True, "Market is closed. Ready to trade another day."



def get_trading_client():
    """Load keys from .env and return a paper-trading client."""
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        raise RuntimeError(
            "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY in .env"
        )

    # paper=True points the client at Alpaca's paper endpoint
    return TradingClient(api_key, secret_key, paper=True)


def show_account(client):
    account = client.get_account()
    # Alpaca returns these as strings, so convert before doing math
    equity = float(account.equity)
    buying_power = float(account.buying_power)
    print(f"Account status: {account.status}")
    print(f"Equity:         ${equity:,.2f}")
    print(f"Buying power:   ${buying_power:,.2f}")


def show_positions(client):
    positions = client.get_all_positions()
    if not positions:
        print("No open positions.")
        return
    print(f"{'Symbol':<8}{'Qty':>8}{'Avg Entry':>12}{'Mkt Value':>12}{'Unreal P/L':>12}")
    for p in positions:
        print(
            f"{p.symbol:<8}{float(p.qty):>8.2f}"
            f"{float(p.avg_entry_price):>12.2f}"
            f"{float(p.market_value):>12.2f}"
            f"{float(p.unrealized_pl):>12.2f}"
        )


def main():
    client = get_trading_client()
    show_account(client)
    show_positions(client)

    ok, reason = ready_to_trade(client)
    print(f"\nGate: {reason}")
    if not ok:
        return

if __name__ == "__main__":
    main()