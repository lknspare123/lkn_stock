"""
One-time copy: Firestore  ->  Neon (Postgres).

Run on your own computer from the project root:

    pip install -r requirements-migrate.txt
    export DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require"
    export FIREBASE_CREDENTIALS_JSON='{"type":"service_account", ...}'    # or put serviceAccountKey.json in the project folder
    python scripts/migrate_firestore_to_neon.py

Safe to re-run (rows are upserted by id). Reads every Firestore document once, so run it
when your Firestore daily read quota is available. Item images stay on Cloudinary (only URLs are copied).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.firebase_db import fs            # noqa: E402  (old Firestore connection)
from core import neon_db                   # noqa: E402  (creates the tables if needed)
from core.neon_db import pool, _recalc, _now  # noqa: E402


def docs(name):
    return [{**d.to_dict(), "_id": d.id} for d in fs.collection(name).stream()]


def s(v):
    return "" if v is None else str(v)


def n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


skipped = []

print("Reading Firestore…")
branches = docs("branches")
items = docs("items")
p_inv, p_items = docs("purchase_invoices"), docs("purchase_items")
s_inv, sales = docs("invoice_records"), docs("sales")
transfers, t_items = docs("transfers"), docs("transfer_items")
counters = {d["_id"]: int(d.get("n", 0)) for d in docs("counters")}
print(f"  {len(branches)} branches, {len(items)} items, {len(p_inv)} receives ({len(p_items)} lines), "
      f"{len(s_inv)} sales ({len(sales)} lines), {len(transfers)} transfers ({len(t_items)} lines)")

with pool.connection() as conn:
    cur = conn.cursor()

    print("Branches…")
    for b in branches:
        cur.execute("INSERT INTO branches (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (b["_id"], s(b.get("name"))))

    print("Items + price lists…")
    seen_codes, item_ids = set(), set()
    for it in items:
        code = s(it.get("item_code")).strip()
        if not code or code in seen_codes:
            skipped.append(f"item {it['_id']} (empty or duplicate code {code!r})")
            continue
        seen_codes.add(code)
        item_ids.add(it["_id"])
        cur.execute(
            """INSERT INTO items (id, item_code, name_khmer, name_english, floor, corner, image_url, image_public_id,
                                  sell_price, unit_price, original_qty, stock_add_qty, transfer_qty, sell_qty,
                                  created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET
                 item_code=EXCLUDED.item_code, name_khmer=EXCLUDED.name_khmer, name_english=EXCLUDED.name_english,
                 floor=EXCLUDED.floor, corner=EXCLUDED.corner, image_url=EXCLUDED.image_url,
                 image_public_id=EXCLUDED.image_public_id, sell_price=EXCLUDED.sell_price,
                 unit_price=EXCLUDED.unit_price, original_qty=EXCLUDED.original_qty,
                 updated_at=EXCLUDED.updated_at""",
            (it["_id"], code, s(it.get("name_khmer")), s(it.get("name_english")), s(it.get("floor")),
             s(it.get("corner")), s(it.get("image_url")), s(it.get("image_public_id")),
             n(it.get("sell_price")), n(it.get("unit_price")), n(it.get("original_qty")), 0, 0, 0,
             s(it.get("created_at")) or _now(), s(it.get("updated_at")) or _now()))
        for x in it.get("distributors") or []:
            if s(x.get("distributor_name")).strip():
                cur.execute(
                    """INSERT INTO item_distributors (item_id, distributor_name, cost_price, last_price_date)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (item_id, distributor_name) DO UPDATE
                       SET cost_price=EXCLUDED.cost_price, last_price_date=EXCLUDED.last_price_date""",
                    (it["_id"], s(x["distributor_name"]).strip(), n(x.get("cost_price")), s(x.get("last_price_date"))))
        for x in it.get("customer_prices") or []:
            if s(x.get("customer_name")).strip():
                cur.execute(
                    """INSERT INTO item_customer_prices (item_id, customer_name, special_sell_price, last_price_date)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (item_id, customer_name) DO UPDATE
                       SET special_sell_price=EXCLUDED.special_sell_price, last_price_date=EXCLUDED.last_price_date""",
                    (it["_id"], s(x["customer_name"]).strip(), n(x.get("special_sell_price")), s(x.get("last_price_date"))))

    print("Receives…")
    inv_codes = set()
    for r in p_inv:
        inv_codes.add(r["_id"])
        cur.execute(
            """INSERT INTO purchase_invoices (invoice_code, distributor_name, receive_date, notes, total_cost, created_at)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (invoice_code) DO UPDATE SET distributor_name=EXCLUDED.distributor_name,
                 receive_date=EXCLUDED.receive_date, notes=EXCLUDED.notes, total_cost=EXCLUDED.total_cost""",
            (r["_id"], s(r.get("distributor_name")), s(r.get("receive_date")), s(r.get("notes")),
             n(r.get("total_cost")), s(r.get("created_at"))))
    for r in p_items:
        if r.get("invoice_code") not in inv_codes or r.get("item_id") not in item_ids:
            skipped.append(f"purchase line {r['_id']} (missing invoice or item)")
            continue
        cur.execute(
            """INSERT INTO purchase_items (id, invoice_code, item_id, qty_receive, unit_price, receive_date, distributor_name)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET qty_receive=EXCLUDED.qty_receive, unit_price=EXCLUDED.unit_price,
                 receive_date=EXCLUDED.receive_date, distributor_name=EXCLUDED.distributor_name""",
            (r["_id"], r["invoice_code"], r["item_id"], n(r.get("qty_receive")), n(r.get("unit_price")),
             s(r.get("receive_date")), s(r.get("distributor_name"))))

    print("Sales…")
    sale_codes = set()
    for r in s_inv:
        sale_codes.add(r["_id"])
        cur.execute(
            """INSERT INTO invoice_records (sale_code, sale_date, customer_name, sender_tel, receiver_tel,
                                            grand_total, notes, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (sale_code) DO UPDATE SET sale_date=EXCLUDED.sale_date, customer_name=EXCLUDED.customer_name,
                 sender_tel=EXCLUDED.sender_tel, receiver_tel=EXCLUDED.receiver_tel,
                 grand_total=EXCLUDED.grand_total, notes=EXCLUDED.notes""",
            (r["_id"], s(r.get("sale_date")), s(r.get("customer_name")), s(r.get("sender_tel")),
             s(r.get("receiver_tel")), n(r.get("grand_total")), s(r.get("notes")), s(r.get("created_at"))))
    for r in sales:
        if r.get("sale_code") not in sale_codes or r.get("item_id") not in item_ids:
            skipped.append(f"sale line {r['_id']} (missing sale or item)")
            continue
        cur.execute(
            """INSERT INTO sales (id, sale_code, sale_date, customer_name, item_id, qty, unit_price, sell_price)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET qty=EXCLUDED.qty, unit_price=EXCLUDED.unit_price,
                 sell_price=EXCLUDED.sell_price, sale_date=EXCLUDED.sale_date, customer_name=EXCLUDED.customer_name""",
            (r["_id"], r["sale_code"], s(r.get("sale_date")), s(r.get("customer_name")), r["item_id"],
             n(r.get("qty")), n(r.get("unit_price")), n(r.get("sell_price"))))

    print("Transfers…")
    tr_codes = set()
    for r in transfers:
        tr_codes.add(r["_id"])
        cur.execute(
            """INSERT INTO transfers (transfer_code, branch_name, driver_name, note, total_cost, is_paid, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (transfer_code) DO UPDATE SET branch_name=EXCLUDED.branch_name,
                 driver_name=EXCLUDED.driver_name, note=EXCLUDED.note, total_cost=EXCLUDED.total_cost,
                 is_paid=EXCLUDED.is_paid""",
            (r["_id"], s(r.get("branch_name")), s(r.get("driver_name")), s(r.get("note")),
             n(r.get("total_cost")), bool(r.get("is_paid")), s(r.get("created_at"))))
    for r in t_items:
        if r.get("transfer_code") not in tr_codes or r.get("item_id") not in item_ids:
            skipped.append(f"transfer line {r['_id']} (missing transfer or item)")
            continue
        cur.execute(
            """INSERT INTO transfer_items (id, transfer_code, item_id, qty, unit_cost, supplier_name, remark)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET qty=EXCLUDED.qty, unit_cost=EXCLUDED.unit_cost,
                 supplier_name=EXCLUDED.supplier_name, remark=EXCLUDED.remark""",
            (r["_id"], r["transfer_code"], r["item_id"], n(r.get("qty")), n(r.get("unit_cost")),
             s(r.get("supplier_name")), s(r.get("remark"))))

    print("Code counters…")
    for prefix, codes in (("RC", inv_codes), ("SL", sale_codes), ("TR", tr_codes)):
        used = max([int(m.group(1)) for c in codes if (m := re.search(r"(\d+)$", c))] + [0])
        cur.execute(
            """INSERT INTO counters (prefix, n) VALUES (%s, %s)
               ON CONFLICT (prefix) DO UPDATE SET n = GREATEST(counters.n, EXCLUDED.n)""",
            (prefix, max(counters.get(prefix, 0), used)))

    print("Rebuilding stock totals…")
    _recalc(conn, item_ids)

with pool.connection() as conn:
    counts = {t: conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"] for t in
              ("branches", "items", "purchase_invoices", "purchase_items", "invoice_records", "sales",
               "transfers", "transfer_items")}
print("\nDone. Rows now in Neon:", counts)
if skipped:
    print(f"\n{len(skipped)} record(s) were skipped (broken links in the old data):")
    for line in skipped[:50]:
        print("  -", line)
