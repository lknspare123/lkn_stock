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


# ── Payments & discounts (mirrors the desktop app's rules) ───────────────────
# Money comparisons use a small epsilon so floating-point noise (499.99999999
# vs 500.0) never leaves a fully-paid record owing a fraction of a cent.
MONEY_EPS = 0.005

# The built-in walk-in customer. It is fixed: it can't be renamed.
GENERAL_CUSTOMER = "អតិថិជនទូទៅ (លក់រាយ)"


def payment_state(total, paid):
    """'paid' | 'partial' | 'unpaid'."""
    total, paid = safe_float(total), safe_float(paid)
    if paid <= MONEY_EPS:
        return "unpaid"
    if paid >= total - MONEY_EPS:
        return "paid"
    return "partial"


def payment_label(total, paid):
    state = payment_state(total, paid)
    if state == "paid":
        return "✅ បានទូទាត់"
    if state == "partial":
        return "🟡 បង់ខ្លះ"
    return "❌ មិនទាន់ទូទាត់"


def outstanding_balance(total, paid):
    """Still owed (never negative, even on an overpayment)."""
    return max(safe_float(total) - safe_float(paid), 0.0)


def clamp_discount_percent(pct):
    pct = safe_float(pct)
    return 0.0 if pct < 0 else 100.0 if pct > 100 else pct


def compute_discounted_total(subtotal, discount_percent):
    """-> (discount_percent, discount_amount, grand_total)"""
    subtotal = safe_float(subtotal)
    pct = clamp_discount_percent(discount_percent)
    amount = subtotal * pct / 100.0
    return pct, amount, max(subtotal - amount, 0.0)


def fmt_pct(v):
    """5 -> '5%', 7.5 -> '7.5%'"""
    return f"{safe_float(v):g}%"
