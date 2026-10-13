"""
logs.py - central logging for the trading bot.

Import the logger you need instead of using print():

    from logs import decision_logger, trade_logger, risk_logger, error_logger, data_logger

What goes where:
    decision_logger  WHY the strategy wanted to act: ticker, date, signal, indicator values.
                     (Strategy.py already calls this.)
    risk_logger      Risk.py checks: trade blocked/allowed, which rule, the numbers involved.
    trade_logger     ORDERS: submitted, filled, rejected, cancelled - with order id, side,
                     qty, price, and the account state afterwards.
    data_logger      Data problems: missing days, failed downloads, validation warnings.
    error_logger     Exceptions and anything unexpected (use logger.exception(...)).

Files are written to log_files/ (add that folder to .gitignore). Each file rotates at
~1 MB and keeps 3 old copies, so logs can never fill your disk.

NEVER log secrets: no API keys, no .env contents, no full request headers.
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = "log_files"          # not named "logs" so it can't be confused with this module
os.makedirs(LOG_DIR, exist_ok=True)

_FORMAT = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")


def _make_logger(name: str, filename: str, level=logging.INFO, to_console: bool = False):
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # Guard so re-importing (or running under tests) doesn't add duplicate handlers
    if logger.handlers:
        return logger

    file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, filename), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(_FORMAT)
    logger.addHandler(file_handler)

    if to_console:
        console = logging.StreamHandler()
        console.setFormatter(_FORMAT)
        logger.addHandler(console)
    return logger


# Decisions are very chatty during a backtest, so they go to file only.
decision_logger = _make_logger("decisions", "decisions.log")
risk_logger = _make_logger("risk", "risk.log", to_console=True)
trade_logger = _make_logger("trades", "trades.log", to_console=True)
data_logger = _make_logger("data", "data.log", to_console=True)
error_logger = _make_logger("errors", "errors.log", level=logging.WARNING, to_console=True)


# Example usage (delete once you've seen the pattern):
#   decision_logger.info("KO 2024-03-04 BUY (sma_short=61.20, sma_long=60.85)")
#   risk_logger.warning("KO BUY blocked: position would be 32% of equity (limit 25%)")
#   trade_logger.info("order submitted id=abc123 BUY 10 KO @ market")
#   trade_logger.info("order filled id=abc123 10 KO @ 61.35, cash=9386.50")
#   try: ...
#   except Exception: error_logger.exception("order submission failed for KO")