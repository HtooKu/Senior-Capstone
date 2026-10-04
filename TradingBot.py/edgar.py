"""
edgar.py - download company financials from SEC EDGAR (free, no API key).

Setup (once):
    pip install requests pandas
    The SEC requires you to identify yourself. Set a User-Agent with your
    name and email:
        macOS/Linux:  export SEC_USER_AGENT="Your Name your.email@example.com"
        Windows:      setx SEC_USER_AGENT "Your Name your.email@example.com"   (reopen terminal)

Run:
    python edgar.py            # downloads anything not already saved
    python edgar.py --refresh  # re-downloads everything

Output:
    data/raw/edgar_company_tickers.json   ticker -> CIK map
    data/raw/{TICKER}_companyfacts.json   raw SEC response (kept so you never re-hit the API)
    data/fundamentals/{TICKER}.csv        flattened table, one row per reported value

POINT-IN-TIME RULE: every row has a 'filed' date = when the SEC received it.
In a backtest, a value may only be used on or after its 'filed' date - NOT its
period 'end' date. Restatements appear as extra rows with later 'filed' dates;
we keep them all on purpose.
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
TICKERS = ["KO", "NVDA", "JNJ", "MSFT", "RIVN"]   # SPY is an ETF: it has no company financials
REQUEST_DELAY = 0.5        # SEC allows up to 10 requests/second; this is well under
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Metric name -> XBRL tag(s) to look for under 'us-gaap'.
# Companies don't all use the same tag (and some switch over time), so we list
# candidates and keep every one that exists. The 'tag' column records which was used.
METRICS = {
    "revenue": ["Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "SalesRevenueNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "equity": ["StockholdersEquity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
}

# Keep only annual/quarterly reports (and their amendments); skip 8-Ks etc.
FORM_PREFIXES = ("10-K", "10-Q")

DATA_DIR = "data"
RAW_DIR = os.path.join(DATA_DIR, "raw")
FUND_DIR = os.path.join(DATA_DIR, "fundamentals")
for d in (RAW_DIR, FUND_DIR):
    os.makedirs(d, exist_ok=True)


# ------------------------------------------------------------------
# API CALLS
# ------------------------------------------------------------------
def _user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT")
    if not ua:
        sys.exit("SEC_USER_AGENT is not set. See the setup notes at the top of edgar.py.")
    return ua


def fetch_json(url: str):
    resp = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=30)
    if resp.status_code == 403:
        raise RuntimeError("403 Forbidden - check your SEC_USER_AGENT (name + email) "
                           "and that you're not sending requests too fast.")
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        raise RuntimeError(f"Non-JSON response from SEC: {resp.text[:200]!r}")


def _save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_cik_map(refresh: bool = False) -> dict:
    """Return {TICKER: 10-digit zero-padded CIK string}."""
    path = os.path.join(RAW_DIR, "edgar_company_tickers.json")
    if refresh or not os.path.exists(path):
        _save_json(fetch_json(TICKER_MAP_URL), path)
        time.sleep(REQUEST_DELAY)
    raw = _load_json(path)
    # Format: {"0": {"cik_str": 789019, "ticker": "MSFT", "title": "..."}, ...}
    return {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}


def download_facts(ticker: str, cik: str, refresh: bool = False) -> dict:
    path = os.path.join(RAW_DIR, f"{ticker}_companyfacts.json")
    if refresh or not os.path.exists(path):
        _save_json(fetch_json(FACTS_URL.format(cik=cik)), path)
        time.sleep(REQUEST_DELAY)
    return _load_json(path)


# ------------------------------------------------------------------
# FLATTEN
# ------------------------------------------------------------------
def flatten_facts(ticker: str, facts: dict) -> pd.DataFrame:
    """Company-facts JSON -> one row per reported value for the metrics we care about."""
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    rows = []
    for metric, tags in METRICS.items():
        for tag in tags:
            if tag not in us_gaap:
                continue
            for unit, entries in us_gaap[tag].get("units", {}).items():
                for e in entries:
                    form = e.get("form", "")
                    if not form.startswith(FORM_PREFIXES):
                        continue
                    rows.append({
                        "ticker": ticker,
                        "metric": metric,
                        "tag": tag,
                        "unit": unit,
                        "val": e.get("val"),
                        "start": e.get("start"),     # absent for balance-sheet items
                        "end": e.get("end"),         # period the number describes
                        "filed": e.get("filed"),     # <- when it became public (use this!)
                        "form": form,
                        "fy": e.get("fy"),
                        "fp": e.get("fp"),
                        "accn": e.get("accn"),
                    })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("start", "end", "filed"):
        df[col] = pd.to_datetime(df[col])
    # Length of the reporting window. ~90 days = a single quarter; ~180/270 = cumulative
    # year-to-date figures inside 10-Qs; ~365 = full year. NaN for balance-sheet items.
    df["period_days"] = (df["end"] - df["start"]).dt.days
    df = df.drop_duplicates(subset=["metric", "tag", "unit", "start", "end", "filed", "val", "accn"])
    return df.sort_values(["metric", "end", "filed"]).reset_index(drop=True)


# ------------------------------------------------------------------
# LOADERS FOR YOUR BACKTEST
# ------------------------------------------------------------------
def load_fundamentals(ticker: str) -> pd.DataFrame:
    """Full long-format table for one ticker (all restatements included)."""
    return pd.read_csv(os.path.join(FUND_DIR, f"{ticker}.csv"),
                       parse_dates=["start", "end", "filed"])


def known_as_of(df: pd.DataFrame, as_of, metric: str):
    """
    Point-in-time lookup: the most recent value of `metric` that was PUBLIC on `as_of`.
    Only rows with filed <= as_of are considered; among those, the latest period wins,
    and if that period was restated, the latest filing of it wins.
    Returns the row (a Series) or None if nothing was public yet.

    Note: for flow items (revenue, net_income) 10-Q rows include cumulative
    year-to-date figures; filter on df['period_days'] (about 90 for a quarter,
    about 365 for a year) if you want a specific window.
    """
    sub = df[(df["metric"] == metric) & (df["filed"] <= pd.Timestamp(as_of))]
    if sub.empty:
        return None
    sub = sub.sort_values(["end", "filed"])
    return sub.iloc[-1]


# ------------------------------------------------------------------
# MAIN
# ------------------------------------------------------------------
def main():
    refresh = "--refresh" in sys.argv
    cik_map = get_cik_map(refresh=refresh)

    for i, ticker in enumerate(TICKERS, start=1):
        print(f"[{i}/{len(TICKERS)}] {ticker}")
        cik = cik_map.get(ticker)
        if not cik:
            print(f"   FAILED: {ticker} not found in SEC ticker map")
            continue
        try:
            facts = download_facts(ticker, cik, refresh=refresh)
            df = flatten_facts(ticker, facts)
            if df.empty:
                print("   no matching facts found")
                continue
            df.to_csv(os.path.join(FUND_DIR, f"{ticker}.csv"), index=False)

            found = sorted(df["metric"].unique())
            missing = [m for m in METRICS if m not in found]
            print(f"   CIK {cik}: {len(df)} rows, filings {df['filed'].min().date()} "
                  f"-> {df['filed'].max().date()}")
            print(f"   metrics found:   {', '.join(found)}")
            if missing:
                print(f"   metrics MISSING: {', '.join(missing)}  (company may use a different tag)")
        except Exception as e:
            print(f"   FAILED: {e}")

    print(f"\nDone. Files in {FUND_DIR}/")

    # >>> INSERT LATER <<< FRED downloads (VIX, Treasury bill yield) following the same pattern.


if __name__ == "__main__":
    main()