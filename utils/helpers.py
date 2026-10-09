"""utils/helpers.py — Formatting and math utilities (image helpers moved to core/storage.py)."""
import os
from datetime import datetime, timedelta, timezone

# Cambodia time (UTC+7, no daylight saving). Render servers run in UTC, so we
# never use naive datetime.now(); everything goes through now_local().
LOCAL_TZ = timezone(timedelta(hours=float(os.environ.get("TZ_OFFSET_HOURS", 7))))


def now_local():
    return datetime.now(LOCAL_TZ)


def fmt_currency(value, symbol="$", decimals=2):
    try:
        return f"{symbol}{float(value or 0):,.{decimals}f}"
    except (TypeError, ValueError):
        return f"{symbol}0.00"


def fmt_qty(value):
    try:
        v = float(value or 0)
        return f"{int(v):,}" if v == int(v) else f"{v:,.2f}"
    except (TypeError, ValueError):
        return "0"


def calc_total(qty, price):
    try:
        return round(float(qty or 0) * float(price or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def calc_profit(sell_total, cost_total):
    sell, cost = float(sell_total or 0), float(cost_total or 0)
    profit = sell - cost
    margin = (profit / sell * 100) if sell > 0 else 0.0
    return round(profit, 2), round(margin, 1)


def safe_float(text, default=0.0):
    try:
        return float(str(text).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def today_str():
    return now_local().strftime("%Y-%m-%d")


def now_str():
    return now_local().strftime("%Y-%m-%d %H:%M:%S")


def fmt_date(date_str):
    try:
        return datetime.strptime(str(date_str)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return date_str or ""
