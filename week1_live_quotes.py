"""
Week 1 Deliverable — Automated Trading System Senior Project
Logs into the Alpaca API and prints a live quote for 5 tickers.

Setup:
1. pip install alpaca-py python-dotenv
2. Create a free paper trading account at https://alpaca.markets
3. Generate an API key + secret from your Alpaca dashboard
4. Create a file named `.env` in this same folder with:
       ALPACA_API_KEY=your_key_here
       ALPACA_SECRET_KEY=your_secret_here
   (Never commit .env to git — add it to .gitignore)
"""

import os
from dotenv import load_dotenv
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

# --- Config ---
TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]

def main():
    load_dotenv()
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")

    if not api_key or not secret_key:
        raise RuntimeError(
            "Missing ALPACA_API_KEY or ALPACA_SECRET_KEY. "
            "Add them to a .env file in this folder (see script header)."
        )

    # Authenticate — this client hits Alpaca's Market Data API
    client = StockHistoricalDataClient(api_key, secret_key)

    # Request the latest quote (best bid/ask) for all 5 tickers in one call
    request = StockLatestQuoteRequest(symbol_or_symbols=TICKERS)
    quotes = client.get_stock_latest_quote(request)

    print(f"{'Ticker':<8}{'Bid':>10}{'Ask':>10}{'Spread':>10}   Timestamp")
    print("-" * 60)
    for symbol in TICKERS:
        q = quotes[symbol]
        spread = q.ask_price - q.bid_price
        print(
            f"{symbol:<8}{q.bid_price:>10.2f}{q.ask_price:>10.2f}"
            f"{spread:>10.2f}   {q.timestamp}"
        )

if __name__ == "__main__":
    main()
