# Scheduling.py
# pip install schedule pytz
import time
from datetime import datetime
from pathlib import Path

import schedule

from livetrading import main as run_bot

RUN_TIME = "16:30"                 # after the 4:00 PM ET close
TIMEZONE = "America/New_York"      # so it doesn't depend on your PC's timezone
KILL_FILE = Path(__file__).parent / "STOP"   # if this file exists, don't trade


def job():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if KILL_FILE.exists():
        print(f"[{now}] STOP file found. Skipping run.")
        return
    print(f"[{now}] Starting daily run...")
    try:
        run_bot()   # the gate inside decides whether today is a trading day
    except Exception as e:
        # one bad run shouldn't kill the scheduler
        print(f"[{now}] Run failed: {e}")


def main():
    schedule.every().day.at(RUN_TIME, TIMEZONE).do(job)
    print(f"Scheduler running. Next run: {schedule.next_run()}")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()