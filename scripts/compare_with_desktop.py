"""
Read-only check: does the web database (Neon) match your Windows app's stock.db?  Nothing is changed.

    $env:DATABASE_URL = 'postgresql://...'
    python scripts/compare_with_desktop.py "D:\\path\\to\\stock.db"

It prints (1) the row count of every table on both sides, (2) the three dashboard numbers worked out from
each side with the web's formulas, and (3) the exact items / invoices that exist on only one side.
To make the web match the desktop, run scripts/migrate_sqlite_to_neon.py with --mirror.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from core.neon_db import pool, DB   # noqa: E402

LOW = float(os.environ.get("LOW_STOCK_THRESHOLD", 5))
if len(sys.argv) < 2 or not os.path.exists(sys.argv[1]):
    sys.exit(__doc__)
src = sqlite3.connect(sys.argv[1])
src.row_factory = sqlite3.Row


def q(sql):
    return [dict(r) for r in src.execute(sql)]


def kpis(rows):
    """rows: [{remain, cost_min, cost_max}] -> the dashboard's three numbers"""
    value = sum(r["remain"] * ((r["cost_min"] + r["cost_max"]) / 2) for r in rows if r["cost_min"] is not None)
    return {"items": len(rows), "stock_value": value, "low": sum(1 for r in rows if r["remain"] <= LOW),
            "out_of_stock": sum(1 for r in rows if r["remain"] <= 0)}


# ── desktop side (from stock.db) ──
d_items = {str(r["id"]): r for r in q("SELECT * FROM items")}
orig = {str(r["item_id"]): r["original_qty"] or 0 for r in q("SELECT item_id, original_qty FROM main_stock")}
add, sold, trf, costs = {}, {}, {}, {}
for r in q("SELECT item_id, SUM(qty_receive) s FROM purchase_invoice_items GROUP BY item_id"):
    add[str(r["item_id"])] = r["s"] or 0
for r in q("SELECT item_id, SUM(qty) s FROM sales GROUP BY item_id"):
    sold[str(r["item_id"])] = r["s"] or 0
for r in q("SELECT item_id, SUM(qty) s FROM transfer_items GROUP BY item_id"):
    trf[str(r["item_id"])] = r["s"] or 0
for r in q("SELECT item_id, cost_price FROM item_distributors"):
    costs.setdefault(str(r["item_id"]), []).append(r["cost_price"] or 0)
d_rows = []
for iid in d_items:
    c = costs.get(iid)
    d_rows.append({"id": iid, "remain": orig.get(iid, 0) + add.get(iid, 0) - sold.get(iid, 0) - trf.get(iid, 0),
                   "cost_min": min(c) if c else None, "cost_max": max(c) if c else None})
d_k = kpis(d_rows)

# ── web side (from Neon) ──
web_items = DB().get_all_items()
w_rows = [{"id": i["id"], "remain": i["remain_qty"], "cost_min": i["min_unit_price"], "cost_max": i["max_unit_price"]} for i in web_items]
w_k = kpis(w_rows)

print("\n=== Dashboard numbers (same formulas on both sides) ===")
print(f"{'':22}{'Windows stock.db':>20}{'Web (Neon)':>20}")
for label, key, fmt in (("Items", "items", "{:,.0f}"), ("Stock value (mid-range)", "stock_value", "${:,.2f}"),
                        (f"Low stock (<= {LOW:g})", "low", "{:,.0f}"), ("Out of stock", "out_of_stock", "{:,.0f}")):
    a, b = fmt.format(d_k[key]), fmt.format(w_k[key])
    print(f"{label:22}{a:>20}{b:>20}{'' if a == b else '   <-- differs'}")

print("\n=== Rows per table ===")
pairs = (("items", "items", "SELECT COUNT(*) c FROM items"), ("receive invoices", "purchase_invoices", "SELECT COUNT(*) c FROM purchase_invoices"),
         ("receive lines", "purchase_items", "SELECT COUNT(*) c FROM purchase_invoice_items"), ("sales invoices", "invoice_records", "SELECT COUNT(*) c FROM invoice_records"),
         ("sale lines", "sales", "SELECT COUNT(*) c FROM sales"), ("transfers", "transfers", "SELECT COUNT(*) c FROM transfers"),
         ("transfer lines", "transfer_items", "SELECT COUNT(*) c FROM transfer_items"),
         ("supplier prices", "item_distributors", "SELECT COUNT(*) c FROM item_distributors"), ("customer prices", "item_customer_prices", "SELECT COUNT(*) c FROM item_customer_prices"))
with pool.connection() as conn:
    for label, table, sql in pairs:
        a = q(sql)[0]["c"]
        b = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
        print(f"{label:22}{a:>20,}{b:>20,}{'' if a == b else '   <-- differs'}")

    print("\n=== Items on only ONE side ===")
    web_only = [i for i in web_items if i["id"] not in d_items]
    desk_only = [r for k, r in d_items.items() if k not in {i["id"] for i in web_items}]
    d_codes = {str(r["item_code"]).strip() for r in d_items.values()}
    if web_only:
        print(f"\nIn the WEB only ({len(web_only)}) - deleted from Windows after the last copy, or created in the web:")
        for i in web_only:
            n_tx = sum(conn.execute(f"SELECT COUNT(*) AS c FROM {t} WHERE item_id = %s", (i['id'],)).fetchone()["c"]
                       for t in ("purchase_items", "sales", "transfer_items"))
            same = "  (same code exists in Windows under another id)" if i["item_code"] in d_codes else ""
            print(f"  {i['item_code']:<16} {(i.get('name_khmer') or i.get('name_english') or '')[:34]:<36} remain {i['remain_qty']:>8g}   transactions: {n_tx}{same}")
    if desk_only:
        print(f"\nIn WINDOWS only ({len(desk_only)}) - not copied yet:")
        for r in desk_only[:40]:
            print(f"  {str(r['item_code']):<16} {(r.get('name_khmer') or r.get('name_english') or '')[:40]}")
    if not web_only and not desk_only:
        print("  none - both sides have exactly the same items")

    print("\n=== Invoices on only ONE side ===")
    for label, table, col, sql in (("sales", "invoice_records", "sale_code", "SELECT sale_code c FROM invoice_records"),
                                   ("receives", "purchase_invoices", "invoice_code", "SELECT invoice_code c FROM purchase_invoices"),
                                   ("transfers", "transfers", "transfer_code", "SELECT transfer_code c FROM transfers")):
        a = {str(r["c"]) for r in q(sql)}
        b = {r["c"] for r in conn.execute(f"SELECT {col} AS c FROM {table}").fetchall()}
        if a != b:
            print(f"  {label}: web-only {sorted(b - a)[:15]}  windows-only {sorted(a - b)[:15]}")
        else:
            print(f"  {label}: identical")
print("\nTo make the web an exact copy of the Windows data:  python scripts/migrate_sqlite_to_neon.py \"<stock.db>\" --mirror\n")
