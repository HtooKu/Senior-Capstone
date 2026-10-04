"""
data.py - download daily price history from Tiingo and save it locally.

Setup (once):
    pip install requests pandas
    set your key as an environment variable - never hard-code it:
        macOS/Linux:  export TIINGO_API_KEY="your_key_here"
        Windows:      setx TIINGO_API_KEY "your_key_here"   (then reopen terminal)

Run:
    python data.py            # downloads anything not already saved
    python data.py --refresh  # re-downloads everything

Output:
    data/raw/{TICKER}_meta.json     raw metadata response
    data/raw/{TICKER}_prices.json   raw price response (kept so you never need to re-hit the API)
    data/prices/{TICKER}.csv        cleaned daily prices, all Tiingo columns
    data/tickers.csv                metadata summary (name, exchange, first/last date)

Then in backtesting.py, replace the body of load_price_data() with:
    from data import load_price_data
"""

import json
import os
import sys
import time

import pandas as pd
import requests

# ------------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------------
BASE_URL = "https://api.tiingo.com/tiingo/daily"
TICKERS = ["KO", "NVDA", "JNJ", "MSFT", "RIVN", "SPY"]   # SPY = market benchmark
START_DATE = "2016-01-01"     # RIVN will just start at its IPO (late 2021)
REQUEST_DELAY = 1.0           # seconds between calls (free tier: 50/hour)

DATA_DIR = "data"
RAW_DIR = os.path.join(DATA_DIR, "raw")
PRICE_DIR = os.path.join(DATA_DIR, "prices")
for d in (RAW_DIR, PRICE_DIR):
    os.makedirs(d, exist_ok=True)


# ------------------------------------------------------------------
# API CALLS
# ------------------------------------------------------------------
def _api_key() -> str:
    key = os.environ.get("TIINGO_API_KEY")
    if not key:
        sys.exit("TIINGO_API_KEY is not set. See the setup notes at the top of data.py.")
    return key


def fetch_json(url: str, params: dict | None = None):
    """GET a Tiingo endpoint. Key goes in a header so it never appears in URLs/logs."""
    resp = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Token {_api_key()}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        # Tiingo can return plain text (e.g. rate-limit message) with a 200 status
        raise RuntimeError(f"Non-JSON response from Tiingo: {resp.text[:200]!r}")


def download_ticker(ticker: str, refresh: bool = False):
    """Fetch metadata + prices for one ticker, saving raw JSON. Returns (meta, prices)."""
    meta_path = os.path.join(RAW_DIR, f"{ticker}_meta.json")
    price_path = os.path.join(RAW_DIR, f"{ticker}_prices.json")

    if refresh or not os.path.exists(meta_path):
        meta = fetch_json(f"{BASE_URL}/{ticker}")
        _save_json(meta, meta_path)
        time.sleep(REQUEST_DELAY)
    else:
        meta = _load_json(meta_path)

    if refresh or not os.path.exists(price_path):
        prices = fetch_json(f"{BASE_URL}/{ticker}/prices", {"startDate": START_DATE})
        if not isinstance(prices, list) or not prices:
            raise RuntimeError(f"{ticker}: unexpected price response: {str(prices)[:200]}")
        _save_json(prices, price_path)
        time.sleep(REQUEST_DELAY)
    else:
        prices = _load_json(price_path)

    return meta, prices


def _save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------
# CLEANING + VALIDATION
# ------------------------------------------------------------------
def prices_to_frame(prices: list) -> pd.DataFrame:
    """Raw Tiingo rows -> date-indexed DataFrame with every Tiingo column kept."""
    df = pd.DataFrame(prices)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    return df.set_index("date").sort_index()


def validate(ticker: str, df: pd.DataFrame) -> list:
    """Return a list of problems found (empty list = clean)."""
    problems = []
    if df.index.duplicated().any():
        problems.append(f"{df.index.duplicated().sum()} duplicate dates")
    price_cols = ["open", "high", "low", "close", "adjOpen", "adjHigh", "adjLow", "adjClose"]
    present = [c for c in price_cols if c in df.columns]
    if df[present].isna().any().any():
        problems.append("missing values in price columns")
    if (df[present] <= 0).any().any():
        problems.append("zero or negative prices")
    gaps = df.index.to_series().diff().dt.days
    if (gaps > 5).any():
        problems.append(f"{(gaps > 5).sum()} gaps longer than 5 calendar days "
                        f"(largest {int(gaps.max())} days)")
    if len(df) < 200:
        problems.append(f"only {len(df)} rows")
    return problems


# ------------------------------------------------------------------
# LOADER USED BY backtesting.py
# ------------------------------------------------------------------
def load_price_data(ticker: str) -> pd.DataFrame:
    """
    Date-indexed DataFrame in the shape generate_signals() expects.
    Uses split/dividend-ADJUSTED prices so moving averages don't jump at splits.
    Raw (unadjusted) close is kept as 'raw_close' for reference.
    """
    path = os.path.join(PRICE_DIR, f"{ticker}.csv")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return pd.DataFrame({
        "open": df["adjOpen"],
        "high": df["adjHigh"],
        "low": df["adjLow"],
        "close": df["adjClose"],
        "volume": df["adjVolume"],
        "raw_close": df["close"],
    })


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    refresh = "--refresh" in sys.argv
    summary = []

    for i, ticker in enumerate(TICKERS, start=1):
        print(f"[{i}/{len(TICKERS)}] {ticker}")
        try:
            meta, prices = download_ticker(ticker, refresh=refresh)
            df = prices_to_frame(prices)
            df.to_csv(os.path.join(PRICE_DIR, f"{ticker}.csv"))

            problems = validate(ticker, df)
            print(f"   {len(df)} rows, {df.index[0].date()} -> {df.index[-1].date()}"
                  + ("" if not problems else f"  PROBLEMS: {'; '.join(problems)}"))

            summary.append({
                "ticker": ticker,
                "name": meta.get("name"),
                "exchange": meta.get("exchangeCode"),
                "tiingo_start": meta.get("startDate"),
                "tiingo_end": meta.get("endDate"),
                "rows": len(df),
                "first_date": df.index[0].date(),
                "last_date": df.index[-1].date(),
                "problems": "; ".join(problems),
            })
        except Exception as e:
            print(f"   FAILED: {e}")
            summary.append({"ticker": ticker, "problems": f"FAILED: {e}"})

    pd.DataFrame(summary).to_csv(os.path.join(DATA_DIR, "tickers.csv"), index=False)
    print(f"\nDone. Summary saved to {os.path.join(DATA_DIR, 'tickers.csv')}")

    # >>> INSERT LATER <<< SEC EDGAR financials (filing-date keyed) and FRED (VIX, T-bill)
    # downloads go here or in a second file, following the same "save raw JSON first" pattern.


if __name__ == "__main__":
    main()