"""
One-time migration: your desktop stock.db  ->  Firestore (+ item images -> Cloudinary).

Run from the project root, with the same env vars the web app uses
(FIREBASE_CREDENTIALS_JSON or serviceAccountKey.json, and CLOUDINARY_URL):

    python scripts/migrate_sqlite_to_firestore.py path/to/stock.db [path/to/assets/images/items]

Safe to re-run: documents are written with fixed ids (items use the old numeric id).
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.firebase_db import fs, DB, _commit  # noqa: E402
from core import storage  # noqa: E402

if len(sys.argv) < 2:
    sys.exit(__doc__)
db_path = sys.argv[1]
img_dir = sys.argv[2] if len(sys.argv) > 2 else ""

src = sqlite3.connect(db_path)
src.row_factory = sqlite3.Row
rows = lambda sql: [dict(r) for r in src.execute(sql)]
col = fs.collection
ops = []

print("Branches…")
for b in rows("SELECT * FROM branches"):
    ops.append(("set", col("branches").document(str(b["id"])), {"name": b["name"]}))

print("Items…")
dist, cust = {}, {}
for r in rows("SELECT * FROM item_distributors"):
    dist.setdefault(r["item_id"], []).append({"distributor_name": r["distributor_name"],
        "cost_price": r["cost_price"], "last_price_date": r.get("last_price_date", "")})
for r in rows("SELECT * FROM item_customer_prices"):
    cust.setdefault(r["item_id"], []).append({"customer_name": r["customer_name"],
        "special_sell_price": r["special_sell_price"], "last_price_date": r.get("last_price_date", "")})
orig = {r["item_id"]: r["original_qty"] for r in rows("SELECT item_id, original_qty FROM main_stock")}

for it in rows("SELECT * FROM items"):
    url = pid = ""
    fname = os.path.basename(it.get("image_path") or "")
    if fname and img_dir and os.path.exists(os.path.join(img_dir, fname)):
        try:
            url, pid = storage.upload_item_image(os.path.join(img_dir, fname), it["item_code"])
            print(f"  uploaded {fname}")
        except Exception as e:
            print(f"  ! image {fname}: {e}")
    ops.append(("set", col("items").document(str(it["id"])), {
        "item_code": it["item_code"], "name_khmer": it["name_khmer"], "name_english": it["name_english"],
        "floor": it["floor"], "corner": it["corner"], "image_url": url, "image_public_id": pid,
        "sell_price": it["sell_price"], "unit_price": it["unit_price"],
        "distributors": dist.get(it["id"], []), "customer_prices": cust.get(it["id"], []),
        "original_qty": orig.get(it["id"], 0.0), "stock_add_qty": 0.0, "transfer_qty": 0.0, "sell_qty": 0.0,
        "created_at": it["created_at"], "updated_at": it["updated_at"]}))
_commit(ops); ops = []

print("Purchases…")
inv = {r["id"]: r for r in rows("SELECT * FROM purchase_invoices")}
totals = {}
for l in rows("SELECT * FROM purchase_invoice_items"):
    h = inv[l["invoice_id"]]
    totals[h["invoice_code"]] = totals.get(h["invoice_code"], 0) + l["qty_receive"] * l["unit_price"]
    ops.append(("set", col("purchase_items").document(f"m{l['id']}"), {
        "invoice_code": h["invoice_code"], "item_id": str(l["item_id"]), "qty_receive": l["qty_receive"],
        "unit_price": l["unit_price"], "receive_date": h["receive_date"], "distributor_name": h["distributor_name"]}))
for h in inv.values():
    ops.append(("set", col("purchase_invoices").document(h["invoice_code"]), {
        "distributor_name": h["distributor_name"], "receive_date": h["receive_date"], "notes": h["notes"],
        "total_cost": round(totals.get(h["invoice_code"], 0), 2), "created_at": h["created_at"]}))

print("Sales…")
sales_hdr = {r["sale_code"]: r for r in rows("SELECT * FROM invoice_records")}
for h in sales_hdr.values():
    ops.append(("set", col("invoice_records").document(h["sale_code"]), {
        "sale_date": h["sale_date"], "customer_name": h["customer_name"], "sender_tel": h["sender_tel"] or "",
        "receiver_tel": h["receiver_tel"] or "", "grand_total": h["grand_total"], "notes": h["notes"] or "",
        "created_at": h["sale_date"]}))
for s in rows("SELECT * FROM sales"):
    h = sales_hdr.get(s["sale_code"], {})
    ops.append(("set", col("sales").document(f"m{s['id']}"), {
        "sale_code": s["sale_code"], "sale_date": h.get("sale_date", ""), "customer_name": h.get("customer_name", ""),
        "item_id": str(s["item_id"]), "qty": s["qty"], "unit_price": s["unit_price"], "sell_price": s["sell_price"]}))

print("Transfers…")
trf = {r["id"]: r for r in rows("SELECT * FROM transfers")}
for t in trf.values():
    ops.append(("set", col("transfers").document(t["transfer_code"]), {
        "branch_name": t["branch_name"], "driver_name": t["driver_name"], "note": t["note"],
        "total_cost": t["total_cost"], "created_at": t["created_at"]}))
for l in rows("SELECT * FROM transfer_items"):
    ops.append(("set", col("transfer_items").document(f"m{l['id']}"), {
        "transfer_code": trf[l["transfer_id"]]["transfer_code"], "item_id": str(l["item_id"]), "qty": l["qty"],
        "unit_cost": l["unit_cost"], "supplier_name": l.get("supplier_name", ""), "remark": l.get("remark", "")}))
_commit(ops)

print("Counters…")
for prefix, table, column in (("RC", "purchase_invoices", "invoice_code"), ("SL", "invoice_records", "sale_code"),
                              ("TR", "transfers", "transfer_code")):
    nums = [int(r[column][len(prefix):]) for r in rows(f"SELECT {column} FROM {table}")
            if r[column].startswith(prefix) and r[column][len(prefix):].isdigit()]
    col("counters").document(prefix).set({"n": max(nums, default=0)})

print("Recalculating stock…")
d = DB()
for it in d.get_all_items():
    d.recalculate_item_stock(it["id"])
print("Done ✔")
