# livetrading.py
# livetrading.py
import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient

def ready_to_trade(client):
    "Checking if the account is ready to trade"

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


if __name__ == "__main__":
    main()