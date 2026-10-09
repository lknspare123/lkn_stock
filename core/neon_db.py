"""
core/neon_db.py — Neon (PostgreSQL) data layer for the LKN Stock web app.

Mirrors the behaviour of the desktop app's core/database.py: payments (partial / full) on
purchase invoices, sales and transfers, percentage discounts on sales, customers, edit-in-place saves,
the multi-source cost resolver used by branch transfers, period reports and backup / restore.

Tables
------
branches / customers
items                 id, item_code, names, floor, corner, image_url, image_public_id, sell_price, unit_price,
                      original_qty, stock_add_qty, transfer_qty, sell_qty ...
item_distributors     (item_id, distributor_name) -> cost_price, last_price_date
item_customer_prices  (item_id, customer_name)    -> special_sell_price, last_price_date
purchase_invoices     invoice_code (PK) ... paid_amount, is_paid     purchase_items   lines
invoice_records       sale_code (PK) ... discount_percent/amount, paid_amount, is_paid     sales   lines
transfers             transfer_code (PK) ... paid_amount, is_paid    transfer_items   lines (unit_cost + sell_price)

Dates stay TEXT ('YYYY-MM-DD' / 'YYYY-MM-DD HH:MM:SS') so old data copies across 1:1. Every date filter compares
LEFT(col, 10), which works for both date-only and date-time values.
Tables / new columns are created automatically on start (CREATE TABLE / ADD COLUMN IF NOT EXISTS).
"""
import os
import re
import time
import uuid
from datetime import timedelta

from psycopg import errors, OperationalError
from psycopg.rows import dict_row
from psycopg_pool import NullConnectionPool, PoolTimeout

from utils.helpers import (now_local, safe_float, payment_state, MONEY_EPS, GENERAL_CUSTOMER)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip().strip("\"'")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy the connection string from the Neon dashboard "
        "(postgresql://user:pass@ep-xxxx.neon.tech/dbname?sslmode=require) into the "
        "DATABASE_URL environment variable.")

# prepare_threshold=None -> works with Neon's pooled (PgBouncer) connection string.
# check=... -> silently replaces connections Neon closed while the database was asleep.
# connect_timeout / keepalives / max_idle -> a dead or sleeping Neon compute fails fast instead of
# hanging, and idle sockets are recycled before Neon (or Render's network) silently drops them.
import logging
logging.getLogger("psycopg.pool").setLevel(logging.WARNING)   # shows the REAL connect error in Render logs

class _FreshPool(NullConnectionPool):
    """Opens a fresh connection per request (no idle connections to go stale while Neon sleeps)
    and retries a few times so the first request after a Neon sleep waits for the wake-up instead of failing."""

    def getconn(self, timeout=None):
        last = None
        for n in range(3):
            try:
                return super().getconn(timeout=timeout)
            except (PoolTimeout, OperationalError) as e:
                last = e
                logging.getLogger("lkn.db").warning("connect attempt %d failed: %s", n + 1, str(e).splitlines()[0][:200])
                time.sleep(1.5)
        raise last


pool = _FreshPool(
    DATABASE_URL,
    min_size=0,
    max_size=int(os.environ.get("DB_POOL_MAX", 5)),
    kwargs={
        "row_factory": dict_row,
        "prepare_threshold": None,
        "connect_timeout": 15,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    },
    reconnect_timeout=20,
    timeout=20,
    max_waiting=0,
    open=False,
    name="neon",
)
pool.open()

SCHEMA = """
CREATE TABLE IF NOT EXISTS branches (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS customers (
    name TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,
    item_code       TEXT NOT NULL UNIQUE,
    name_khmer      TEXT NOT NULL DEFAULT '',
    name_english    TEXT NOT NULL DEFAULT '',
    floor           TEXT NOT NULL DEFAULT '',
    corner          TEXT NOT NULL DEFAULT '',
    image_url       TEXT NOT NULL DEFAULT '',
    image_public_id TEXT NOT NULL DEFAULT '',
    sell_price      DOUBLE PRECISION NOT NULL DEFAULT 0,
    unit_price      DOUBLE PRECISION NOT NULL DEFAULT 0,
    original_qty    DOUBLE PRECISION NOT NULL DEFAULT 0,
    stock_add_qty   DOUBLE PRECISION NOT NULL DEFAULT 0,
    transfer_qty    DOUBLE PRECISION NOT NULL DEFAULT 0,
    sell_qty        DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS item_distributors (
    seq              BIGSERIAL,
    item_id          TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    distributor_name TEXT NOT NULL,
    cost_price       DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_price_date  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (item_id, distributor_name)
);
CREATE TABLE IF NOT EXISTS item_customer_prices (
    seq                BIGSERIAL,
    item_id            TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    customer_name      TEXT NOT NULL,
    special_sell_price DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_price_date    TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (item_id, customer_name)
);
CREATE TABLE IF NOT EXISTS purchase_invoices (
    invoice_code     TEXT PRIMARY KEY,
    distributor_name TEXT NOT NULL DEFAULT '',
    receive_date     TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    total_cost       DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS purchase_items (
    id               TEXT PRIMARY KEY,
    invoice_code     TEXT NOT NULL REFERENCES purchase_invoices(invoice_code) ON DELETE CASCADE,
    item_id          TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    qty_receive      DOUBLE PRECISION NOT NULL DEFAULT 0,
    unit_price       DOUBLE PRECISION NOT NULL DEFAULT 0,
    receive_date     TEXT NOT NULL DEFAULT '',
    distributor_name TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS invoice_records (
    sale_code     TEXT PRIMARY KEY,
    sale_date     TEXT NOT NULL DEFAULT '',
    customer_name TEXT NOT NULL DEFAULT '',
    sender_tel    TEXT NOT NULL DEFAULT '',
    receiver_tel  TEXT NOT NULL DEFAULT '',
    grand_total   DOUBLE PRECISION NOT NULL DEFAULT 0,
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sales (
    id            TEXT PRIMARY KEY,
    sale_code     TEXT NOT NULL REFERENCES invoice_records(sale_code) ON DELETE CASCADE,
    sale_date     TEXT NOT NULL DEFAULT '',
    customer_name TEXT NOT NULL DEFAULT '',
    item_id       TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    qty           DOUBLE PRECISION NOT NULL DEFAULT 0,
    unit_price    DOUBLE PRECISION NOT NULL DEFAULT 0,
    sell_price    DOUBLE PRECISION NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transfers (
    transfer_code TEXT PRIMARY KEY,
    branch_name   TEXT NOT NULL DEFAULT '',
    driver_name   TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    total_cost    DOUBLE PRECISION NOT NULL DEFAULT 0,
    is_paid       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS transfer_items (
    id            TEXT PRIMARY KEY,
    transfer_code TEXT NOT NULL REFERENCES transfers(transfer_code) ON DELETE CASCADE,
    item_id       TEXT NOT NULL REFERENCES items(id),
    qty           DOUBLE PRECISION NOT NULL DEFAULT 0,
    unit_cost     DOUBLE PRECISION NOT NULL DEFAULT 0,
    supplier_name TEXT NOT NULL DEFAULT '',
    remark        TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS backup_log (
    id            BIGSERIAL PRIMARY KEY,
    ran_at        TEXT NOT NULL DEFAULT '',
    trigger       TEXT NOT NULL DEFAULT '',
    ok            BOOLEAN NOT NULL DEFAULT FALSE,
    message       TEXT NOT NULL DEFAULT '',
    file_name     TEXT NOT NULL DEFAULT '',
    size_bytes    BIGINT NOT NULL DEFAULT 0,
    drive_file_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS counters (
    prefix TEXT PRIMARY KEY,
    n      INTEGER NOT NULL DEFAULT 0
);

-- columns added for payments / discounts / transfer sell price (safe to run on every start)
ALTER TABLE purchase_invoices ADD COLUMN IF NOT EXISTS is_paid          BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE purchase_invoices ADD COLUMN IF NOT EXISTS paid_amount      DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE invoice_records   ADD COLUMN IF NOT EXISTS is_paid          BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE invoice_records   ADD COLUMN IF NOT EXISTS paid_amount      DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE invoice_records   ADD COLUMN IF NOT EXISTS discount_percent DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE invoice_records   ADD COLUMN IF NOT EXISTS discount_amount  DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transfers         ADD COLUMN IF NOT EXISTS paid_amount      DOUBLE PRECISION NOT NULL DEFAULT 0;
ALTER TABLE transfer_items    ADD COLUMN IF NOT EXISTS sell_price       DOUBLE PRECISION NOT NULL DEFAULT 0;

-- back-fill: records previously flagged Paid but with no amount were paid in full
UPDATE purchase_invoices SET paid_amount = total_cost WHERE is_paid AND paid_amount <= 0;
UPDATE invoice_records   SET paid_amount = grand_total WHERE is_paid AND paid_amount <= 0;
UPDATE transfers         SET paid_amount = total_cost WHERE is_paid AND paid_amount <= 0;

CREATE INDEX IF NOT EXISTS ix_purchase_items_item    ON purchase_items(item_id);
CREATE INDEX IF NOT EXISTS ix_purchase_items_invoice ON purchase_items(invoice_code);
CREATE INDEX IF NOT EXISTS ix_sales_item             ON sales(item_id);
CREATE INDEX IF NOT EXISTS ix_sales_code             ON sales(sale_code);
CREATE INDEX IF NOT EXISTS ix_sales_date             ON sales(sale_date);
CREATE INDEX IF NOT EXISTS ix_transfer_items_item    ON transfer_items(item_id);
CREATE INDEX IF NOT EXISTS ix_transfer_items_code    ON transfer_items(transfer_code);
CREATE INDEX IF NOT EXISTS ix_invoice_records_date   ON invoice_records(sale_date);
CREATE INDEX IF NOT EXISTS ix_purchase_invoices_date ON purchase_invoices(receive_date);
CREATE INDEX IF NOT EXISTS ix_transfers_created      ON transfers(created_at);
"""


def ensure_schema(attempts=8):
    """Create tables / columns if missing. The advisory lock stops two gunicorn workers racing.

    Neon's free compute sleeps when idle and the very first connection after a sleep can be dropped
    ("SSL connection has been closed unexpectedly"). So we retry with a growing pause while it wakes up,
    instead of crashing the whole app on the first failure."""
    last = None
    for n in range(1, attempts + 1):
        try:
            with pool.connection() as conn:
                conn.execute("SELECT pg_advisory_xact_lock(727274)")
                conn.execute(SCHEMA)
            return
        except (OperationalError, PoolTimeout) as e:
            last = e
            wait = min(2 * n, 10)
            print(f"[db] database not ready (attempt {n}/{attempts}): {str(e).splitlines()[0][:140]} - retrying in {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Could not connect to the database after {attempts} attempts. Check DATABASE_URL. Last error: {last}")


ensure_schema()

LOW_STOCK = float(os.environ.get("LOW_STOCK_THRESHOLD", 5))
_CACHE = {"t": 0.0, "data": None}      # dashboard cache (30 s)

DEFAULT_BRANCHES = ["សាខាខេត្តសៀមរាប", "សាខាខេត្តបាត់ដំបង", "សាខាក្រុងព្រះសីហនុ", "សាខាភ្នំពេញថ្មី"]

# Backup / restore / reset. Parents first (restore order); reversed for deleting.
BACKUP_TABLES = ["branches", "customers", "items", "item_distributors", "item_customer_prices",
                 "purchase_invoices", "purchase_items", "invoice_records", "sales",
                 "transfers", "transfer_items", "counters"]
RESET_TABLES = ["sales", "invoice_records", "item_customer_prices", "item_distributors", "transfer_items",
                "transfers", "purchase_items", "purchase_invoices", "items", "customers", "counters"]


def _bust():
    _CACHE["t"] = 0.0


# ── small helpers ────────────────────────────────────────────────────────────
def _now():
    return now_local().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return now_local().strftime("%Y-%m-%d")


def _new_id():
    return uuid.uuid4().hex[:20]


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _enrich(d):
    """Add the values the UI expects (on-hand / remaining qty, min/max/avg prices)."""
    for k in ("original_qty", "stock_add_qty", "transfer_qty", "sell_qty", "sell_price", "unit_price"):
        d[k] = _num(d.get(k))
    d["on_hand_qty"] = d["original_qty"] + d["stock_add_qty"]
    d["remain_qty"] = d["on_hand_qty"] - d["sell_qty"] - d["transfer_qty"]
    d.setdefault("distributors", [])
    d.setdefault("customer_prices", [])
    costs = [_num(x.get("cost_price")) for x in d["distributors"]]
    sells = [_num(x.get("special_sell_price")) for x in d["customer_prices"]]
    d["min_unit_price"] = min(costs) if costs else None
    d["max_unit_price"] = max(costs) if costs else None
    d["avg_unit_price"] = (sum(costs) / len(costs)) if costs else 0.0
    d["min_sell_price"] = min(sells) if sells else None
    d["max_sell_price"] = max(sells) if sells else None
    # Valuation basis used by Main Stock / Dashboard / Reports: remaining x midpoint of the price range.
    d["mid_unit_price"] = ((d["min_unit_price"] + d["max_unit_price"]) / 2) if costs else 0.0
    d["mid_sell_price"] = ((d["min_sell_price"] + d["max_sell_price"]) / 2) if sells else 0.0
    return d


def _fetch_items(conn, item_id=None):
    """Items with their distributor / customer price lists attached (3 queries, any size)."""
    where, params = ("WHERE id = %s", (item_id,)) if item_id else ("", ())
    items = conn.execute(f"SELECT * FROM items {where}", params).fetchall()
    where2 = "WHERE item_id = %s" if item_id else ""
    dist, cust = {}, {}
    for r in conn.execute(
            f"SELECT item_id, distributor_name, cost_price, last_price_date "
            f"FROM item_distributors {where2} ORDER BY seq", params):
        dist.setdefault(r["item_id"], []).append(
            {"distributor_name": r["distributor_name"], "cost_price": r["cost_price"],
             "last_price_date": r["last_price_date"]})
    for r in conn.execute(
            f"SELECT item_id, customer_name, special_sell_price, last_price_date "
            f"FROM item_customer_prices {where2} ORDER BY seq", params):
        cust.setdefault(r["item_id"], []).append(
            {"customer_name": r["customer_name"], "special_sell_price": r["special_sell_price"],
             "last_price_date": r["last_price_date"]})
    for it in items:
        it["distributors"] = dist.get(it["id"], [])
        it["customer_prices"] = cust.get(it["id"], [])
        _enrich(it)
    return items


def _recalc(conn, item_ids):
    """Rebuild stock counters from the transaction lines."""
    for iid in set(item_ids):
        conn.execute(
            """UPDATE items SET
                 stock_add_qty = COALESCE((SELECT SUM(qty_receive) FROM purchase_items WHERE item_id = %(i)s), 0),
                 transfer_qty  = COALESCE((SELECT SUM(qty) FROM transfer_items WHERE item_id = %(i)s), 0),
                 sell_qty      = COALESCE((SELECT SUM(qty) FROM sales WHERE item_id = %(i)s), 0)
               WHERE id = %(i)s""", {"i": iid})
    _bust()


def _upsert_distributor(conn, item_id, name, cost, price_date):
    if not name or not conn.execute("SELECT 1 FROM items WHERE id = %s", (item_id,)).fetchone():
        return
    conn.execute(
        """INSERT INTO item_distributors (item_id, distributor_name, cost_price, last_price_date)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (item_id, distributor_name)
           DO UPDATE SET cost_price = EXCLUDED.cost_price, last_price_date = EXCLUDED.last_price_date""",
        (item_id, name, _num(cost), price_date or _today()))


def _is_paid(total, paid):
    return _num(paid) >= _num(total) - MONEY_EPS and _num(paid) > MONEY_EPS


def _date_clause(col, start, end, where, params):
    """Append an inclusive date-range filter on the first 10 chars of `col` (works for date and datetime text)."""
    if start and end and start > end:
        start, end = end, start          # a reversed range is swapped, never returns nothing
    if start:
        where.append(f"LEFT({col}, 10) >= %s")
        params.append(start)
    if end:
        where.append(f"LEFT({col}, 10) <= %s")
        params.append(end)


def _filter_paid(rows, total_key, paid_key, paid_filter):
    """paid_filter: '' / 'all' | 'paid' | 'partial' | 'unpaid'"""
    if not paid_filter or paid_filter == "all":
        return rows
    return [r for r in rows if payment_state(r[total_key], r[paid_key]) == paid_filter]


class DB:
    def close(self):  # kept for API compatibility with the desktop version
        pass

    # ── Codes ────────────────────────────────────────────────────────────────
    def next_code(self, prefix, table, column):
        """Next sequential code: highest existing '<prefix><digits>' + 1, e.g. INV-RCV-0007 -> INV-RCV-0008."""
        pattern = "^" + re.escape(prefix) + "([0-9]{1,12})$"
        with pool.connection() as conn:
            n = conn.execute(
                f"SELECT COALESCE(MAX(substring({column} from %s)::bigint), 0) AS n FROM {table} WHERE {column} ~ %s",
                (pattern, pattern)).fetchone()["n"]
        return f"{prefix}{int(n) + 1:04d}"

    # ── Branches ─────────────────────────────────────────────────────────────
    def get_branches(self):
        with pool.connection() as conn:
            rows = conn.execute("SELECT id, name FROM branches").fetchall()
            if not rows:
                for n in DEFAULT_BRANCHES:
                    conn.execute("INSERT INTO branches (id, name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                                 (_new_id(), n))
                rows = conn.execute("SELECT id, name FROM branches").fetchall()
        return sorted(rows, key=lambda r: r["name"])

    def add_branch(self, name):
        name = name.strip()
        if not name:
            raise ValueError("Branch name is required")
        with pool.connection() as conn:
            if conn.execute("SELECT 1 FROM branches WHERE name = %s", (name,)).fetchone():
                raise ValueError("សាខានេះមានរួចរាល់ហើយ!")
            conn.execute("INSERT INTO branches (id, name) VALUES (%s, %s)", (_new_id(), name))

    def delete_branch(self, branch_id):
        with pool.connection() as conn:
            conn.execute("DELETE FROM branches WHERE id = %s", (branch_id,))

    # ── Items ────────────────────────────────────────────────────────────────
    def get_all_items(self):
        with pool.connection() as conn:
            rows = _fetch_items(conn)
        return sorted(rows, key=lambda r: r.get("item_code", ""))

    def items_map(self):
        return {i["id"]: i for i in self.get_all_items()}

    def get_item(self, item_id):
        with pool.connection() as conn:
            rows = _fetch_items(conn, item_id)
        return rows[0] if rows else None

    def insert_item(self, code, kh, en, floor, corner, image_url="", image_public_id="",
                    sell_price=0.0, unit_price=0.0, original_qty=0.0):
        item_id = _new_id()
        try:
            with pool.connection() as conn:
                if conn.execute("SELECT 1 FROM items WHERE item_code = %s", (code,)).fetchone():
                    raise ValueError(f"Item code '{code}' already exists")
                conn.execute(
                    """INSERT INTO items (id, item_code, name_khmer, name_english, floor, corner,
                                          image_url, image_public_id, sell_price, unit_price, original_qty,
                                          created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (item_id, code, kh, en, floor, corner, image_url, image_public_id,
                     _num(sell_price), _num(unit_price), _num(original_qty), _now(), _now()))
        except errors.UniqueViolation:
            raise ValueError(f"Item code '{code}' already exists")
        _bust()
        return item_id

    def update_item(self, item_id, kh, en, floor, corner, image_url, image_public_id,
                    sell_price, unit_price, original_qty=None):
        with pool.connection() as conn:
            conn.execute(
                """UPDATE items SET name_khmer=%s, name_english=%s, floor=%s, corner=%s,
                                    image_url=%s, image_public_id=%s, sell_price=%s, unit_price=%s,
                                    original_qty=COALESCE(%s, original_qty), updated_at=%s
                   WHERE id=%s""",
                (kh, en, floor, corner, image_url, image_public_id,
                 _num(sell_price), _num(unit_price), None if original_qty is None else _num(original_qty),
                 _now(), item_id))
        _bust()

    def delete_item(self, item_id):
        with pool.connection() as conn:
            if conn.execute("SELECT 1 FROM transfer_items WHERE item_id = %s LIMIT 1", (item_id,)).fetchone():
                raise ValueError("ទំនិញនេះត្រូវបានប្រើក្នុងប័ណ្ណផ្ទេរទំនិញ មិនអាចលុបបានទេ។")
            # purchase lines, sales lines and price lists are removed by ON DELETE CASCADE
            conn.execute("DELETE FROM items WHERE id = %s", (item_id,))
        _bust()

    def set_original_qty(self, item_id, qty):
        with pool.connection() as conn:
            conn.execute("UPDATE items SET original_qty = %s WHERE id = %s", (_num(qty), item_id))
        _bust()

    # ── Pricing matrices ─────────────────────────────────────────────────────
    def save_item_distributor(self, item_id, distributor_name, cost_price, price_date=None):
        if distributor_name:
            with pool.connection() as conn:
                _upsert_distributor(conn, item_id, distributor_name, cost_price, price_date)
            _bust()

    def delete_item_distributor(self, item_id, distributor_name):
        with pool.connection() as conn:
            conn.execute("DELETE FROM item_distributors WHERE item_id = %s AND distributor_name = %s",
                         (item_id, distributor_name))
        _bust()

    def save_item_customer_price(self, item_id, customer_name, special_sell_price, price_date=None):
        if not customer_name:
            return
        with pool.connection() as conn:
            if not conn.execute("SELECT 1 FROM items WHERE id = %s", (item_id,)).fetchone():
                return
            conn.execute(
                """INSERT INTO item_customer_prices (item_id, customer_name, special_sell_price, last_price_date)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (item_id, customer_name)
                   DO UPDATE SET special_sell_price = EXCLUDED.special_sell_price,
                                 last_price_date = EXCLUDED.last_price_date""",
                (item_id, customer_name, _num(special_sell_price), price_date or _today()))
        _bust()

    def delete_item_customer_price(self, item_id, customer_name):
        with pool.connection() as conn:
            conn.execute("DELETE FROM item_customer_prices WHERE item_id = %s AND customer_name = %s",
                         (item_id, customer_name))
        _bust()

    def get_customer_price(self, item_id, customer_name):
        with pool.connection() as conn:
            r = conn.execute("SELECT special_sell_price FROM item_customer_prices WHERE item_id=%s AND customer_name=%s",
                             (item_id, customer_name)).fetchone()
        return r["special_sell_price"] if r else None

    def get_item_purchase_history(self, item_id):
        with pool.connection() as conn:
            return conn.execute(
                "SELECT * FROM purchase_items WHERE item_id = %s ORDER BY receive_date DESC, id DESC",
                (item_id,)).fetchall()

    def get_suppliers_for_item(self, item_id):
        """Suppliers this item has been bought from (most recent first)."""
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT distributor_name AS n, MAX(receive_date) AS d FROM purchase_items
                   WHERE item_id = %s AND distributor_name <> '' GROUP BY distributor_name
                   UNION ALL
                   SELECT distributor_name, last_price_date FROM item_distributors WHERE item_id = %s
                   ORDER BY d DESC""", (item_id, item_id)).fetchall()
        out = []
        for r in rows:
            if r["n"] and r["n"] not in out:
                out.append(r["n"])
        return out

    # ── Stock recalculation ──────────────────────────────────────────────────
    def recalculate_item_stock(self, item_id):
        with pool.connection() as conn:
            _recalc(conn, [item_id])

    # ── Purchases / Stock receive ────────────────────────────────────────────
    def get_receive_history(self):
        """Every purchase invoice with its line count, total cost and amount paid (newest first)."""
        with pool.connection() as conn:
            return conn.execute(
                """SELECT pi.invoice_code, pi.distributor_name, pi.receive_date, pi.notes,
                          pi.is_paid, pi.paid_amount,
                          COUNT(p.id) AS item_count,
                          COALESCE(SUM(p.qty_receive), 0) AS total_qty,
                          COALESCE(SUM(p.qty_receive * p.unit_price), 0) AS total_cost
                   FROM purchase_invoices pi LEFT JOIN purchase_items p ON p.invoice_code = pi.invoice_code
                   GROUP BY pi.invoice_code
                   ORDER BY pi.receive_date DESC, pi.invoice_code DESC""").fetchall()

    def get_purchase_invoice(self, code):
        with pool.connection() as conn:
            return conn.execute(
                """SELECT pi.*, COALESCE((SELECT SUM(qty_receive * unit_price) FROM purchase_items
                                          WHERE invoice_code = pi.invoice_code), 0) AS total_cost_calc
                   FROM purchase_invoices pi WHERE invoice_code = %s""", (code,)).fetchone()

    def get_invoice_items(self, code):
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT p.*, i.item_code, i.name_khmer, i.name_english,
                          p.qty_receive * p.unit_price AS total_cost
                   FROM purchase_items p JOIN items i ON i.id = p.item_id
                   WHERE p.invoice_code = %s""", (code,)).fetchall()
        return sorted(rows, key=lambda r: r["item_code"])

    def _write_purchase(self, conn, code, distributor_name, receive_date, notes, items_list, paid_amount, created_at=None):
        total = sum(_num(i["qty"]) * _num(i["price"]) for i in items_list)
        paid = max(_num(paid_amount), 0.0)
        conn.execute(
            """INSERT INTO purchase_invoices (invoice_code, distributor_name, receive_date, notes,
                                              total_cost, created_at, paid_amount, is_paid)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (code, distributor_name, receive_date, notes, round(total, 2), created_at or _now(),
             paid, _is_paid(total, paid)))
        for i in items_list:
            conn.execute(
                """INSERT INTO purchase_items (id, invoice_code, item_id, qty_receive, unit_price,
                                               receive_date, distributor_name)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (_new_id(), code, i["item_id"], _num(i["qty"]), _num(i["price"]), receive_date, distributor_name))
            _upsert_distributor(conn, i["item_id"], distributor_name, i["price"], receive_date)

    def save_purchase_invoice(self, code, distributor_name, receive_date, notes, items_list,
                              paid_amount=0.0, editing_code=None):
        """Create a purchase invoice, or (editing_code given) replace an existing one — the old lines are
        reversed and the new ones inserted in one transaction, then every touched item's stock is rebuilt."""
        code, distributor_name = code.strip(), distributor_name.strip()
        with pool.connection() as conn:
            touched = [i["item_id"] for i in items_list]
            created_at = None
            if editing_code:
                old = conn.execute("SELECT created_at FROM purchase_invoices WHERE invoice_code = %s",
                                   (editing_code,)).fetchone()
                if not old:
                    raise ValueError("រកមិនឃើញវិក្កយបត្រនេះនៅក្នុងទិន្នន័យឡើយ។")
                created_at = old["created_at"]
                touched += [r["item_id"] for r in conn.execute(
                    "SELECT item_id FROM purchase_items WHERE invoice_code = %s", (editing_code,))]
                conn.execute("DELETE FROM purchase_invoices WHERE invoice_code = %s", (editing_code,))
            if conn.execute("SELECT 1 FROM purchase_invoices WHERE invoice_code = %s", (code,)).fetchone():
                raise ValueError(f"លេខវិក្កយបត្រ '{code}' មានរួចរាល់ហើយ។")
            self._write_purchase(conn, code, distributor_name, receive_date, notes, items_list, paid_amount, created_at)
            _recalc(conn, touched)
        return True

    def set_purchase_payment(self, code, paid_total):
        paid_total = max(_num(paid_total), 0.0)
        with pool.connection() as conn:
            row = conn.execute("SELECT COALESCE(SUM(qty_receive * unit_price), 0) AS t FROM purchase_items "
                               "WHERE invoice_code = %s", (code,)).fetchone()
            conn.execute("UPDATE purchase_invoices SET paid_amount = %s, is_paid = %s WHERE invoice_code = %s",
                         (paid_total, _is_paid(row["t"], paid_total), code))

    def mark_purchase_paid(self, codes):
        """Settle every given invoice in full (never lowers an existing overpayment). Returns how many changed."""
        done = 0
        with pool.connection() as conn:
            for code in codes:
                r = conn.execute(
                    """SELECT pi.paid_amount, COALESCE(SUM(p.qty_receive * p.unit_price), 0) AS t
                       FROM purchase_invoices pi LEFT JOIN purchase_items p ON p.invoice_code = pi.invoice_code
                       WHERE pi.invoice_code = %s GROUP BY pi.invoice_code""", (code,)).fetchone()
                if not r or payment_state(r["t"], r["paid_amount"]) == "paid":
                    continue
                conn.execute("UPDATE purchase_invoices SET paid_amount = %s, is_paid = TRUE WHERE invoice_code = %s",
                             (max(r["t"], r["paid_amount"]), code))
                done += 1
        return done

    def delete_purchase_invoices(self, codes):
        with pool.connection() as conn:
            for code in codes:
                ids = [r["item_id"] for r in conn.execute(
                    "SELECT item_id FROM purchase_items WHERE invoice_code = %s", (code,))]
                conn.execute("DELETE FROM purchase_invoices WHERE invoice_code = %s", (code,))  # lines cascade
                _recalc(conn, ids)
        return True

    # ── Customers ────────────────────────────────────────────────────────────
    def get_all_customers(self, items=None):
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT customer_name AS n FROM item_customer_prices
                   UNION SELECT name FROM customers
                   UNION SELECT customer_name FROM invoice_records""").fetchall()
        names = {(r["n"] or "").strip() for r in rows if (r["n"] or "").strip()}
        names.discard(GENERAL_CUSTOMER)
        return sorted(names)

    def add_customer(self, name):
        name = (name or "").strip()
        if not name:
            raise ValueError("សូមបំពេញឈ្មោះអតិថិជន។")
        if name == GENERAL_CUSTOMER or name in self.get_all_customers():
            raise ValueError("ឈ្មោះអតិថិជននេះមានរួចរាល់នៅក្នុងប្រព័ន្ធហើយ។")
        with pool.connection() as conn:
            conn.execute("INSERT INTO customers (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))

    def rename_customer(self, old, new, update_invoices=True):
        old, new = (old or "").strip(), (new or "").strip()
        if not old or old == GENERAL_CUSTOMER:
            raise ValueError(f"'{GENERAL_CUSTOMER}' ជាអតិថិជនលំនាំដើមរបស់ប្រព័ន្ធ មិនអាចកែឈ្មោះបានទេ។")
        if not new:
            raise ValueError("សូមបំពេញឈ្មោះអតិថិជន។")
        if new == GENERAL_CUSTOMER:
            raise ValueError(f"'{GENERAL_CUSTOMER}' ត្រូវបានរក្សាទុកសម្រាប់អតិថិជនលំនាំដើម។")
        if new != old and new in self.get_all_customers():
            raise ValueError("ឈ្មោះអតិថិជននេះមានរួចរាល់នៅក្នុងប្រព័ន្ធហើយ។")
        if new == old:
            return
        with pool.connection() as conn:
            conn.execute("UPDATE item_customer_prices SET customer_name = %s WHERE customer_name = %s", (new, old))
            conn.execute("DELETE FROM customers WHERE name = %s", (old,))
            conn.execute("INSERT INTO customers (name) VALUES (%s) ON CONFLICT DO NOTHING", (new,))
            if update_invoices:
                conn.execute("UPDATE invoice_records SET customer_name = %s WHERE customer_name = %s", (new, old))
                conn.execute("UPDATE sales SET customer_name = %s WHERE customer_name = %s", (new, old))
        _bust()

    # ── Sales ────────────────────────────────────────────────────────────────
    def save_sale(self, sale_code, sale_date, customer_name, sender_tel, receiver_tel, notes,
                  cart_items, discount_percent=0.0, discount_amount=0.0, grand_total=0.0,
                  paid_amount=0.0, editing=False):
        """Insert a sale (editing=False) or replace the lines/header of an existing one in place.
        cart_items: {item_id: {qty, unit_price, sell_price}}. Raises ValueError if stock would go negative."""
        paid = max(_num(paid_amount), 0.0)
        with pool.connection() as conn:
            old_qty = {}
            if editing:
                if not conn.execute("SELECT 1 FROM invoice_records WHERE sale_code = %s", (sale_code,)).fetchone():
                    raise ValueError("រកមិនឃើញវិក្កយបត្រនេះនៅក្នុងទិន្នន័យឡើយ។")
                for r in conn.execute("SELECT item_id, qty FROM sales WHERE sale_code = %s", (sale_code,)):
                    old_qty[r["item_id"]] = old_qty.get(r["item_id"], 0) + r["qty"]
            elif conn.execute("SELECT 1 FROM invoice_records WHERE sale_code = %s", (sale_code,)).fetchone():
                raise ValueError("Sale code already exists")

            # stock guard: what is left, plus what this invoice already took
            for iid, it in cart_items.items():
                row = conn.execute("SELECT item_code, original_qty + stock_add_qty - sell_qty - transfer_qty AS remain "
                                   "FROM items WHERE id = %s", (iid,)).fetchone()
                if not row:
                    raise ValueError("រកមិនឃើញទំនិញមួយចំនួនក្នុងប្រព័ន្ធ។")
                allowed = row["remain"] + old_qty.get(iid, 0)
                if _num(it["qty"]) > allowed + 1e-9:
                    raise ValueError(f"ស្តុកមិនគ្រប់គ្រាន់សម្រាប់ {row['item_code']} (សល់ {allowed:g})")

            if editing:
                conn.execute("DELETE FROM sales WHERE sale_code = %s", (sale_code,))
                conn.execute(
                    """UPDATE invoice_records SET sale_date=%s, customer_name=%s, sender_tel=%s, receiver_tel=%s,
                              notes=%s, grand_total=%s, discount_percent=%s, discount_amount=%s,
                              paid_amount=%s, is_paid=%s WHERE sale_code=%s""",
                    (sale_date, customer_name, sender_tel, receiver_tel, notes, round(grand_total, 2),
                     _num(discount_percent), round(_num(discount_amount), 2), paid,
                     _is_paid(grand_total, paid), sale_code))
            else:
                conn.execute(
                    """INSERT INTO invoice_records (sale_code, sale_date, customer_name, sender_tel, receiver_tel,
                                                    grand_total, notes, created_at, discount_percent,
                                                    discount_amount, paid_amount, is_paid)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (sale_code, sale_date, customer_name, sender_tel, receiver_tel, round(grand_total, 2), notes,
                     _now(), _num(discount_percent), round(_num(discount_amount), 2), paid,
                     _is_paid(grand_total, paid)))
            for iid, it in cart_items.items():
                conn.execute(
                    """INSERT INTO sales (id, sale_code, sale_date, customer_name, item_id, qty, unit_price, sell_price)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (_new_id(), sale_code, sale_date, customer_name, iid, _num(it["qty"]),
                     _num(it["unit_price"]), _num(it["sell_price"])))
            _recalc(conn, list(cart_items) + list(old_qty))

    def get_sales_history(self, search="", start=None, end=None, paid_filter="all"):
        where, params = ["1=1"], []
        if search:
            where.append("sale_code ILIKE %s")
            params.append(f"%{search}%")
        _date_clause("sale_date", start, end, where, params)
        with pool.connection() as conn:
            rows = conn.execute(f"SELECT * FROM invoice_records WHERE {' AND '.join(where)} "
                                f"ORDER BY sale_date DESC, sale_code DESC", params).fetchall()
        return _filter_paid(rows, "grand_total", "paid_amount", paid_filter)

    def get_sale(self, code):
        with pool.connection() as conn:
            return conn.execute("SELECT * FROM invoice_records WHERE sale_code = %s", (code,)).fetchone()

    def get_sale_items(self, code):
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT s.*, i.item_code, i.name_khmer, i.name_english, i.original_qty + i.stock_add_qty
                          - i.sell_qty - i.transfer_qty AS remain_qty, s.qty * s.sell_price AS line_total
                   FROM sales s JOIN items i ON i.id = s.item_id
                   WHERE s.sale_code = %s ORDER BY s.id""", (code,)).fetchall()
        return rows

    def set_sale_payment(self, code, paid_total):
        paid_total = max(_num(paid_total), 0.0)
        with pool.connection() as conn:
            r = conn.execute("SELECT grand_total FROM invoice_records WHERE sale_code = %s", (code,)).fetchone()
            if not r:
                raise ValueError("រកមិនឃើញវិក្កយបត្រនេះនៅក្នុងទិន្នន័យឡើយ។")
            conn.execute("UPDATE invoice_records SET paid_amount = %s, is_paid = %s WHERE sale_code = %s",
                         (paid_total, _is_paid(r["grand_total"], paid_total), code))

    def mark_sales_paid(self, codes):
        done = 0
        with pool.connection() as conn:
            for code in codes:
                r = conn.execute("SELECT grand_total, paid_amount FROM invoice_records WHERE sale_code = %s",
                                 (code,)).fetchone()
                if not r or payment_state(r["grand_total"], r["paid_amount"]) == "paid":
                    continue
                conn.execute("UPDATE invoice_records SET paid_amount = %s, is_paid = TRUE WHERE sale_code = %s",
                             (max(r["grand_total"], r["paid_amount"]), code))
                done += 1
        return done

    def delete_sale(self, code):
        with pool.connection() as conn:
            ids = [r["item_id"] for r in conn.execute("SELECT item_id FROM sales WHERE sale_code = %s", (code,))]
            conn.execute("DELETE FROM invoice_records WHERE sale_code = %s", (code,))  # lines cascade
            _recalc(conn, ids)

    # ── Branch transfers ─────────────────────────────────────────────────────
    def save_transfer(self, transfer_code, branch_name, driver_name, note, created_at, items_list,
                      paid_amount=0.0, editing=False):
        """items_list: [{item_id, qty, unit_cost, sell_price, supplier, remark}]"""
        total = sum(_num(i["qty"]) * _num(i["unit_cost"]) for i in items_list)
        paid = max(_num(paid_amount), 0.0)
        with pool.connection() as conn:
            old_qty = {}
            if editing:
                if not conn.execute("SELECT 1 FROM transfers WHERE transfer_code = %s", (transfer_code,)).fetchone():
                    raise ValueError("រកមិនឃើញប័ណ្ណផ្ទេរនេះនៅក្នុងទិន្នន័យឡើយ។")
                for r in conn.execute("SELECT item_id, qty FROM transfer_items WHERE transfer_code = %s", (transfer_code,)):
                    old_qty[r["item_id"]] = old_qty.get(r["item_id"], 0) + r["qty"]
            elif conn.execute("SELECT 1 FROM transfers WHERE transfer_code = %s", (transfer_code,)).fetchone():
                raise ValueError("Transfer code already exists")

            need = {}
            for i in items_list:
                need[i["item_id"]] = need.get(i["item_id"], 0) + _num(i["qty"])
            for iid, qty in need.items():
                row = conn.execute("SELECT item_code, original_qty + stock_add_qty - sell_qty - transfer_qty AS remain "
                                   "FROM items WHERE id = %s", (iid,)).fetchone()
                if not row:
                    raise ValueError("រកមិនឃើញទំនិញមួយចំនួនក្នុងប្រព័ន្ធ។")
                allowed = row["remain"] + old_qty.get(iid, 0)
                if qty > allowed + 1e-9:
                    raise ValueError(f"ស្តុកមិនគ្រប់គ្រាន់សម្រាប់ {row['item_code']} (សល់ {allowed:g})")

            if editing:
                conn.execute("DELETE FROM transfer_items WHERE transfer_code = %s", (transfer_code,))
                conn.execute(
                    """UPDATE transfers SET branch_name=%s, driver_name=%s, note=%s, total_cost=%s,
                              paid_amount=%s, is_paid=%s, created_at=COALESCE(%s, created_at)
                       WHERE transfer_code=%s""",
                    (branch_name, driver_name, note, round(total, 2), paid, _is_paid(total, paid),
                     created_at, transfer_code))
            else:
                conn.execute(
                    """INSERT INTO transfers (transfer_code, branch_name, driver_name, note, total_cost,
                                              is_paid, paid_amount, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (transfer_code, branch_name, driver_name, note, round(total, 2), _is_paid(total, paid),
                     paid, created_at or _now()))
            for i in items_list:
                conn.execute(
                    """INSERT INTO transfer_items (id, transfer_code, item_id, qty, unit_cost, sell_price,
                                                   supplier_name, remark)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (_new_id(), transfer_code, i["item_id"], _num(i["qty"]), _num(i["unit_cost"]),
                     _num(i.get("sell_price", i["unit_cost"])), (i.get("supplier") or "").strip(),
                     (i.get("remark") or "").strip()))
            _recalc(conn, list(need) + list(old_qty))
        return total

    def get_transfers_history(self, search="", start=None, end=None, paid_filter="all", branch_name=None):
        where, params = ["1=1"], []
        if search:
            where.append("transfer_code ILIKE %s")
            params.append(f"%{search}%")
        if branch_name and branch_name.strip():
            where.append("branch_name = %s")
            params.append(branch_name.strip())
        _date_clause("created_at", start, end, where, params)
        with pool.connection() as conn:
            rows = conn.execute(f"SELECT * FROM transfers WHERE {' AND '.join(where)} "
                                f"ORDER BY created_at DESC, transfer_code DESC", params).fetchall()
        return _filter_paid(rows, "total_cost", "paid_amount", paid_filter)

    def get_transfer(self, code):
        with pool.connection() as conn:
            return conn.execute("SELECT * FROM transfers WHERE transfer_code = %s", (code,)).fetchone()

    def get_transfer_items(self, code):
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT t.*, i.item_code, i.name_khmer, i.name_english, i.floor, i.corner,
                          i.original_qty + i.stock_add_qty - i.sell_qty - i.transfer_qty AS remain_qty,
                          t.qty * t.unit_cost AS total_cost
                   FROM transfer_items t JOIN items i ON i.id = t.item_id
                   WHERE t.transfer_code = %s ORDER BY t.id""", (code,)).fetchall()
        return rows

    def set_transfer_payment(self, code, paid_total):
        paid_total = max(_num(paid_total), 0.0)
        with pool.connection() as conn:
            r = conn.execute("SELECT total_cost FROM transfers WHERE transfer_code = %s", (code,)).fetchone()
            if not r:
                raise ValueError("រកមិនឃើញប័ណ្ណផ្ទេរនេះនៅក្នុងទិន្នន័យឡើយ។")
            conn.execute("UPDATE transfers SET paid_amount = %s, is_paid = %s WHERE transfer_code = %s",
                         (paid_total, _is_paid(r["total_cost"], paid_total), code))
        _bust()

    def mark_transfers_paid(self, codes):
        done = 0
        with pool.connection() as conn:
            for code in codes:
                r = conn.execute("SELECT total_cost, paid_amount FROM transfers WHERE transfer_code = %s",
                                 (code,)).fetchone()
                if not r or payment_state(r["total_cost"], r["paid_amount"]) == "paid":
                    continue
                conn.execute("UPDATE transfers SET paid_amount = %s, is_paid = TRUE WHERE transfer_code = %s",
                             (max(r["total_cost"], r["paid_amount"]), code))
                done += 1
        _bust()
        return done

    def delete_transfer(self, code):
        with pool.connection() as conn:
            ids = [r["item_id"] for r in conn.execute(
                "SELECT item_id FROM transfer_items WHERE transfer_code = %s", (code,))]
            conn.execute("DELETE FROM transfers WHERE transfer_code = %s", (code,))  # lines cascade
            _recalc(conn, ids)
        return True

    # ── Cost resolver (used by branch transfers) ─────────────────────────────
    def resolve_cost(self, item_id, distributor=None):
        """Best known cost for an item. A price of 0 is never accepted while another source has a real one.
        Order: latest receive line -> distributor price list -> item default cost -> latest earlier transfer.
        With `distributor` given, only that supplier's receive history / price entry is used.
        Returns (cost, supplier_name, source)."""
        with pool.connection() as conn:
            q = ("SELECT p.unit_price, p.distributor_name FROM purchase_items p "
                 "JOIN purchase_invoices pi ON pi.invoice_code = p.invoice_code "
                 "WHERE p.item_id = %s AND p.unit_price > 0")
            args = [item_id]
            if distributor:
                q += " AND pi.distributor_name = %s"
                args.append(distributor)
            row = conn.execute(q + " ORDER BY pi.receive_date DESC, pi.created_at DESC, pi.invoice_code DESC LIMIT 1",
                               args).fetchone()
            if row:
                return row["unit_price"], row["distributor_name"] or "", "receive"

            q = ("SELECT cost_price, distributor_name FROM item_distributors "
                 "WHERE item_id = %s AND cost_price > 0")
            args = [item_id]
            if distributor:
                q += " AND distributor_name = %s"
                args.append(distributor)
            row = conn.execute(q + " ORDER BY last_price_date DESC, seq DESC LIMIT 1", args).fetchone()
            if row:
                return row["cost_price"], row["distributor_name"], "distributor"
            if distributor:
                return 0.0, "", "none"

            it = conn.execute("SELECT unit_price FROM items WHERE id = %s", (item_id,)).fetchone()
            if it and it["unit_price"] > 0:
                return it["unit_price"], "", "item"

            row = conn.execute(
                """SELECT ti.unit_cost, ti.supplier_name FROM transfer_items ti
                   JOIN transfers t ON t.transfer_code = ti.transfer_code
                   WHERE ti.item_id = %s AND ti.unit_cost > 0
                   ORDER BY t.created_at DESC, t.transfer_code DESC LIMIT 1""", (item_id,)).fetchone()
            if row:
                return row["unit_cost"], row["supplier_name"] or "", "transfer"
        return 0.0, "", "none"

    # ── Lookups ──────────────────────────────────────────────────────────────
    def get_all_suppliers(self, items=None):
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT distributor_name AS n FROM item_distributors
                   UNION SELECT distributor_name FROM purchase_invoices""").fetchall()
        return sorted({(r["n"] or "").strip() for r in rows if (r["n"] or "").strip()})

    # ── Dashboard ────────────────────────────────────────────────────────────
    def dashboard_data(self, force=False):
        """Everything the dashboard needs, aggregated in SQL, cached 30 s."""
        if not force and _CACHE["data"] and time.time() - _CACHE["t"] < 30:
            return _CACHE["data"]
        try:
            return self._dashboard_data()
        except PoolTimeout:
            if _CACHE["data"]:            # DB unreachable: show the last good numbers rather than a 500
                return _CACHE["data"]
            raise

    def _dashboard_data(self):
        items = self.get_all_items()
        today = _today()
        month = today[:7]
        days = [(now_local() - timedelta(days=n)).strftime("%Y-%m-%d") for n in range(29, -1, -1)]
        with pool.connection() as conn:
            tot = conn.execute(
                """SELECT COALESCE(SUM(grand_total), 0) AS total_rev,
                          COALESCE(SUM(CASE WHEN LEFT(sale_date, 10) = %(today)s THEN grand_total END), 0) AS today_rev,
                          COALESCE(SUM(CASE WHEN LEFT(sale_date, 7) = %(month)s THEN grand_total END), 0) AS month_rev
                   FROM invoice_records""", {"today": today, "month": month}).fetchone()
            month_cost = conn.execute(
                """SELECT COALESCE(SUM(s.qty * s.unit_price), 0) AS c FROM sales s
                   JOIN invoice_records r ON r.sale_code = s.sale_code WHERE LEFT(r.sale_date, 7) = %s""",
                (month,)).fetchone()["c"]
            daily = {d: 0.0 for d in days}
            for r in conn.execute(
                    """SELECT LEFT(sale_date, 10) AS d, SUM(grand_total) AS rev FROM invoice_records
                       WHERE LEFT(sale_date, 10) >= %s AND LEFT(sale_date, 10) <= %s GROUP BY 1""",
                    (days[0], days[-1])):
                daily[r["d"]] = r["rev"]
            paid_transfers = conn.execute(
                "SELECT COALESCE(SUM(total_cost), 0) AS v FROM transfers WHERE is_paid").fetchone()["v"]
            best = [{"id": r["item_id"], "code": r["item_code"],
                     "name": r["name_english"] or r["name_khmer"],
                     "qty": r["tot_qty"], "revenue": r["tot_rev"]}
                    for r in conn.execute(
                        """SELECT s.item_id, i.item_code, i.name_english, i.name_khmer,
                                  SUM(s.qty) AS tot_qty, SUM(s.qty * s.sell_price) AS tot_rev
                           FROM sales s JOIN items i ON i.id = s.item_id
                           GROUP BY s.item_id, i.item_code, i.name_english, i.name_khmer
                           HAVING SUM(s.qty) > 0
                           ORDER BY tot_qty DESC, i.item_code
                           LIMIT 10""")]
            recent_sales = conn.execute(
                "SELECT * FROM invoice_records ORDER BY created_at DESC, sale_code DESC LIMIT 5").fetchall()
            recent_transfers = conn.execute(
                "SELECT * FROM transfers ORDER BY created_at DESC, transfer_code DESC LIMIT 5").fetchall()
        total_sales, today_rev = tot["total_rev"], tot["today_rev"]
        month_rev = tot["month_rev"]
        low = sorted([i for i in items if i["remain_qty"] <= LOW_STOCK], key=lambda i: (i["remain_qty"], i["item_code"]))
        dead = sorted([i for i in items if i["remain_qty"] > 0], key=lambda i: (i["sell_qty"], -i["remain_qty"]))[:10]
        data = {
            "updated": now_local().strftime("%H:%M:%S"), "threshold": LOW_STOCK,
            "total_items": len(items), "out_of_stock": sum(1 for i in items if i["remain_qty"] <= 0),
            "stock_value": sum(i["remain_qty"] * i["mid_unit_price"] for i in items),
            "sales_total": total_sales, "paid_transfers": paid_transfers,
            "revenue_total": total_sales + paid_transfers,
            "today_rev": today_rev, "month_rev": month_rev, "month_profit": month_rev - month_cost,
            "month_margin": ((month_rev - month_cost) / month_rev * 100) if month_rev else 0.0,
            "daily": [(d, daily[d]) for d in days], "best": best, "dead": dead,
            "low": low, "recent_sales": recent_sales, "recent_transfers": recent_transfers,
        }
        _CACHE.update(t=time.time(), data=data)
        return data

    # ── Reports ──────────────────────────────────────────────────────────────
    def report_receives(self):
        with pool.connection() as conn:
            return conn.execute(
                """SELECT pi.invoice_code AS code, pi.distributor_name, pi.receive_date AS date, pi.notes,
                          pi.is_paid, pi.paid_amount, COUNT(p.id) AS num_items,
                          COALESCE(SUM(p.qty_receive), 0) AS total_qty,
                          COALESCE(SUM(p.qty_receive * p.unit_price), 0) AS total_cost
                   FROM purchase_invoices pi LEFT JOIN purchase_items p ON p.invoice_code = pi.invoice_code
                   GROUP BY pi.invoice_code ORDER BY pi.receive_date DESC, pi.invoice_code DESC""").fetchall()

    def report_sales(self):
        with pool.connection() as conn:
            return conn.execute(
                """SELECT r.sale_code AS code, r.customer_name, r.sale_date AS date, r.notes, r.sender_tel, r.receiver_tel,
                          r.is_paid, r.paid_amount, r.discount_percent, r.discount_amount,
                          COUNT(s.id) AS num_items, COALESCE(SUM(s.qty), 0) AS total_qty,
                          COALESCE(NULLIF(r.grand_total, 0), SUM(s.qty * s.sell_price), 0) AS total_cost
                   FROM invoice_records r LEFT JOIN sales s ON s.sale_code = r.sale_code
                   GROUP BY r.sale_code ORDER BY r.sale_date DESC, r.sale_code DESC""").fetchall()

    def report_transfers(self):
        with pool.connection() as conn:
            return conn.execute(
                """SELECT t.transfer_code AS code, t.branch_name, t.driver_name, t.note, t.created_at AS date,
                          t.is_paid, t.paid_amount, COUNT(ti.id) AS num_items,
                          COALESCE(SUM(ti.qty), 0) AS total_qty,
                          COALESCE(SUM(ti.qty * ti.unit_cost), 0) AS total_cost
                   FROM transfers t LEFT JOIN transfer_items ti ON ti.transfer_code = t.transfer_code
                   GROUP BY t.transfer_code ORDER BY t.created_at DESC, t.transfer_code DESC""").fetchall()

    def report_invoice_lines(self, kind, code):
        """Normalised lines {item_code, name_khmer, name_english, qty, price} for one invoice / transfer / receive."""
        q = {"customers": "SELECT s.qty, s.sell_price AS price, i.item_code, i.name_khmer, i.name_english "
                          "FROM sales s JOIN items i ON i.id = s.item_id WHERE s.sale_code = %s ORDER BY s.id",
             "branches": "SELECT t.qty, t.unit_cost AS price, i.item_code, i.name_khmer, i.name_english "
                         "FROM transfer_items t JOIN items i ON i.id = t.item_id WHERE t.transfer_code = %s ORDER BY t.id",
             "distributors": "SELECT p.qty_receive AS qty, p.unit_price AS price, i.item_code, i.name_khmer, i.name_english "
                             "FROM purchase_items p JOIN items i ON i.id = p.item_id WHERE p.invoice_code = %s ORDER BY p.id"}[kind]
        with pool.connection() as conn:
            return conn.execute(q, (code,)).fetchall()

    def sales_report(self, start_date, end_date):
        """Line-level sales between two dates (by invoice date), joined with item names."""
        with pool.connection() as conn:
            return conn.execute(
                """SELECT s.*, i.item_code,
                          COALESCE(NULLIF(i.name_english, ''), NULLIF(i.name_khmer, ''), i.item_code) AS name
                   FROM sales s JOIN items i ON i.id = s.item_id
                   JOIN invoice_records r ON r.sale_code = s.sale_code
                   WHERE LEFT(r.sale_date, 10) >= %s AND LEFT(r.sale_date, 10) <= %s""",
                (start_date, end_date)).fetchall()

    def sales_report_totals(self, start_date, end_date):
        with pool.connection() as conn:
            return conn.execute(
                """SELECT COALESCE(SUM(grand_total), 0) AS revenue, COALESCE(SUM(discount_amount), 0) AS discount
                   FROM invoice_records WHERE LEFT(sale_date, 10) >= %s AND LEFT(sale_date, 10) <= %s""",
                (start_date, end_date)).fetchone()

    # ── Backup / restore / reset ─────────────────────────────────────────────
    def export_all(self):
        """Every table as {name: [rows]} — the JSON backup."""
        out = {}
        with pool.connection() as conn:
            for t in BACKUP_TABLES:
                order = " ORDER BY seq" if t in ("item_distributors", "item_customer_prices") else ""
                out[t] = conn.execute(f"SELECT * FROM {t}{order}").fetchall()
        return out

    def restore_all(self, data):
        """Replace the whole database with a backup produced by export_all(). All-or-nothing."""
        if not isinstance(data, dict) or "items" not in data:
            raise ValueError("ឯកសារបម្រុងមិនត្រឹមត្រូវ។ (not an LKN Stock backup file)")
        with pool.connection() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(727275)")
            for t in reversed(BACKUP_TABLES):
                conn.execute(f"DELETE FROM {t}")
            for t in BACKUP_TABLES:
                rows = data.get(t) or []
                if not rows:
                    continue
                cols = [c for c in rows[0].keys() if c != "seq"]
                sql = f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
                with conn.cursor() as cur:
                    cur.executemany(sql, [tuple(r.get(c) for c in cols) for r in rows])
        _bust()
        return {t: len(data.get(t) or []) for t in BACKUP_TABLES}

    def reset_all(self):
        """Clear every transactional table (branches are kept, like the desktop app). Returns the tables cleared."""
        with pool.connection() as conn:
            for t in RESET_TABLES:
                conn.execute(f"DELETE FROM {t}")
        _bust()
        return list(RESET_TABLES)
