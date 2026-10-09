"""
One-time copy: your desktop stock.db (SQLite)  ->  Neon (Postgres), straight in. No Firestore needed.

Windows PowerShell, from the project folder:

    $env:DATABASE_URL = 'postgresql://...neon.tech/neondb?sslmode=require'
    $env:CLOUDINARY_URL = 'cloudinary://KEY:SECRET@CLOUD'      # only if you want item pictures uploaded
    python scripts/migrate_sqlite_to_neon.py "D:\\path\\to\\stock.db" "D:\\path\\to\\assets\\images\\items"

The second argument (the pictures folder) is optional. Safe to re-run: rows are upserted by id, and
pictures already uploaded are not uploaded again. Rows are sent in batches, so thousands of items take seconds,
not minutes. Pictures are uploaded 8 at a time.

Add  --mirror  to make the web database an EXACT copy of stock.db: anything that exists only in the web (items you
deleted in Windows after the last copy, invoices created in the web...) is deleted. You see the list first and must
type MIRROR to confirm (or pass --yes). Take a backup first (Settings -> download .db).
Run scripts/compare_with_desktop.py to see the differences without changing anything.
"""
import os
import re
import sys
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import neon_db, storage                 # noqa: E402  (creates the tables if needed)
from core.neon_db import pool, _now      # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
FLAGS = {a for a in sys.argv[1:] if a.startswith("--")}
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
MIRROR, ASSUME_YES = "--mirror" in FLAGS, "--yes" in FLAGS
if len(ARGS) < 1:
    sys.exit(__doc__)
db_path = ARGS[0]
img_dir = ARGS[1] if len(ARGS) > 1 else ""
if not os.path.exists(db_path):
    sys.exit(f"Cannot find {db_path}")

src = sqlite3.connect(db_path)
src.row_factory = sqlite3.Row
T0 = time.time()


def rows(sql):
    return [dict(r) for r in src.execute(sql)]


def s(v):
    return "" if v is None else str(v)


def n(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def step(msg):
    print(f"[{time.time() - T0:5.0f}s] {msg}", flush=True)


skipped = []

# ── 1. read everything from stock.db ─────────────────────────────────────────
step("Reading stock.db…")
branches = rows("SELECT * FROM branches")
src_items = rows("SELECT * FROM items")
dist, cust = {}, {}
for r in rows("SELECT * FROM item_distributors"):
    dist.setdefault(r["item_id"], []).append(r)
for r in rows("SELECT * FROM item_customer_prices"):
    cust.setdefault(r["item_id"], []).append(r)
orig = {r["item_id"]: r["original_qty"] for r in rows("SELECT item_id, original_qty FROM main_stock")}
inv = {r["id"]: r for r in rows("SELECT * FROM purchase_invoices")}
p_lines = rows("SELECT * FROM purchase_invoice_items")
hdr = {r["sale_code"]: r for r in rows("SELECT * FROM invoice_records")}
s_lines = rows("SELECT * FROM sales")
trf = {r["id"]: r for r in rows("SELECT * FROM transfers")}
t_lines = rows("SELECT * FROM transfer_items")
step(f"{len(src_items)} items, {len(inv)} receives, {len(hdr)} sales, {len(trf)} transfers")

# ── 2. pick items, work out which pictures to upload ─────────────────────────
items, seen_codes, item_ids, jobs = [], set(), set(), []
with pool.connection() as conn:
    have_image = {r["id"]: (r["image_url"], r["image_public_id"])
                  for r in conn.execute("SELECT id, image_url, image_public_id FROM items WHERE image_url <> ''")}
for it in src_items:
    code, iid = s(it.get("item_code")).strip(), str(it["id"])
    if not code or code in seen_codes:
        skipped.append(f"item #{iid} (empty or duplicate code {code!r})")
        continue
    seen_codes.add(code)
    item_ids.add(iid)
    items.append((iid, code, it))
    fname = os.path.basename(s(it.get("image_path")).replace("\\", "/"))
    path = os.path.join(img_dir, fname) if fname and img_dir else ""
    if path and os.path.exists(path) and iid not in have_image:
        jobs.append((iid, code, path))

images = dict(have_image)          # id -> (url, public_id)
if jobs:
    if not storage.CLOUDINARY_OK:
        step(f"{len(jobs)} pictures found but CLOUDINARY_URL is not set -> items will be copied without pictures")
    else:
        step(f"Uploading {len(jobs)} pictures (8 at a time)…")
        done = 0

        def up(job):
            iid, code, path = job
            try:
                return iid, storage.upload_item_image(path, code), None
            except Exception as e:                     # keep going if one picture fails
                return iid, None, f"{os.path.basename(path)}: {e}"

        with ThreadPoolExecutor(max_workers=8) as ex:
            for iid, res, err in ex.map(up, jobs):
                done += 1
                if res:
                    images[iid] = res
                else:
                    print("  ! picture", err)
                if done % 50 == 0 or done == len(jobs):
                    step(f"  {done}/{len(jobs)} pictures")

# ── 3. build every row in memory ─────────────────────────────────────────────
b_rows = [(str(b["id"]), s(b["name"])) for b in branches]
i_rows, d_rows, c_rows = [], [], []
for iid, code, it in items:
    url, pid = images.get(iid, ("", ""))
    i_rows.append((iid, code, s(it.get("name_khmer")), s(it.get("name_english")), s(it.get("floor")),
                   s(it.get("corner")), url, pid, n(it.get("sell_price")), n(it.get("unit_price")),
                   n(orig.get(it["id"])), s(it.get("created_at")) or _now(), s(it.get("updated_at")) or _now()))
    for r in dist.get(it["id"], []):
        if s(r.get("distributor_name")).strip():
            d_rows.append((iid, s(r["distributor_name"]).strip(), n(r.get("cost_price")), s(r.get("last_price_date"))))
    for r in cust.get(it["id"], []):
        if s(r.get("customer_name")).strip():
            c_rows.append((iid, s(r["customer_name"]).strip(), n(r.get("special_sell_price")), s(r.get("last_price_date"))))

totals = {}
for l in p_lines:
    h = inv.get(l["invoice_id"])
    if h:
        totals[h["invoice_code"]] = totals.get(h["invoice_code"], 0) + n(l["qty_receive"]) * n(l["unit_price"])
pi_rows = [(h["invoice_code"], s(h.get("distributor_name")), s(h.get("receive_date")), s(h.get("notes")),
            round(totals.get(h["invoice_code"], 0), 2), s(h.get("created_at")) or s(h.get("receive_date")),
            bool(h.get("is_paid") or 0), n(h.get("paid_amount")) or (round(totals.get(h["invoice_code"], 0), 2) if h.get("is_paid") else 0.0))
           for h in inv.values()]
pl_rows = []
for l in p_lines:
    h = inv.get(l["invoice_id"])
    if not h or str(l["item_id"]) not in item_ids:
        skipped.append(f"purchase line #{l['id']} (missing invoice or item)")
        continue
    pl_rows.append((f"m{l['id']}", h["invoice_code"], str(l["item_id"]), n(l["qty_receive"]), n(l["unit_price"]),
                    s(h.get("receive_date")), s(h.get("distributor_name"))))

sh_rows = [(h["sale_code"], s(h.get("sale_date")), s(h.get("customer_name")), s(h.get("sender_tel")),
            s(h.get("receiver_tel")), n(h.get("grand_total")), s(h.get("notes")), s(h.get("sale_date")),
            bool(h.get("is_paid") or 0), n(h.get("paid_amount")) or (n(h.get("grand_total")) if h.get("is_paid") else 0.0),
            n(h.get("discount_percent")), n(h.get("discount_amount")))
           for h in hdr.values()]
sl_rows = []
for r in s_lines:
    h = hdr.get(r["sale_code"])
    if not h or str(r["item_id"]) not in item_ids:
        skipped.append(f"sale line #{r['id']} (missing sale or item)")
        continue
    sl_rows.append((f"m{r['id']}", r["sale_code"], s(h.get("sale_date")), s(h.get("customer_name")),
                    str(r["item_id"]), n(r["qty"]), n(r["unit_price"]), n(r["sell_price"])))

th_rows = [(t["transfer_code"], s(t.get("branch_name")), s(t.get("driver_name")), s(t.get("note")),
            n(t.get("total_cost")), bool(t.get("is_paid") or 0), s(t.get("created_at")),
            n(t.get("paid_amount")) or (n(t.get("total_cost")) if t.get("is_paid") else 0.0)) for t in trf.values()]
tl_rows = []
for l in t_lines:
    t = trf.get(l["transfer_id"])
    if not t or str(l["item_id"]) not in item_ids:
        skipped.append(f"transfer line #{l['id']} (missing transfer or item)")
        continue
    tl_rows.append((f"m{l['id']}", t["transfer_code"], str(l["item_id"]), n(l["qty"]), n(l["unit_cost"]),
                    s(l.get("supplier_name")), s(l.get("remark")), n(l.get("sell_price")) or n(l["unit_cost"])))

counters = []
for prefix, codes in (("RC", [h["invoice_code"] for h in inv.values()]),
                      ("SL", list(hdr)), ("TR", [t["transfer_code"] for t in trf.values()])):
    used = max([int(m.group(1)) for c in codes if (m := re.fullmatch(prefix + r"(\d+)", s(c)))] + [0])
    counters.append((prefix, used))

# ── 3b. --mirror: work out what exists only in the web, and ask before deleting it ──────────────
keep = {
    "items": [i[0] for i in items], "purchase_invoices": [h["invoice_code"] for h in inv.values()],
    "purchase_items": [r[0] for r in pl_rows], "invoice_records": list(hdr), "sales": [r[0] for r in sl_rows],
    "transfers": [t["transfer_code"] for t in trf.values()], "transfer_items": [r[0] for r in tl_rows]}
KEYCOL = {"items": "id", "purchase_invoices": "invoice_code", "purchase_items": "id", "invoice_records": "sale_code",
          "sales": "id", "transfers": "transfer_code", "transfer_items": "id"}
to_delete = {}
if MIRROR:
    step("Mirror mode: looking for rows that exist only in the web database…")
    with pool.connection() as conn:
        for table, col in KEYCOL.items():
            ids = set(keep[table])
            extra = [r for r in conn.execute(f"SELECT {col} AS k FROM {table}").fetchall() if r["k"] not in ids]
            if extra:
                to_delete[table] = [r["k"] for r in extra]
        web_only_items = to_delete.get("items", [])
        if web_only_items:
            print("\nItems that will be DELETED from the web (not in stock.db):")
            for r in conn.execute("SELECT item_code, name_khmer, name_english FROM items WHERE id = ANY(%s) ORDER BY item_code",
                                  (web_only_items,)).fetchall()[:60]:
                print("  -", r["item_code"], (r["name_khmer"] or r["name_english"] or "")[:40])
    if not to_delete:
        step("Nothing to delete - the web only contains rows that are also in stock.db.")
    else:
        print("\nRows that will be deleted from the web database:")
        for t, v in to_delete.items():
            print(f"  {t}: {len(v)}")
        if not ASSUME_YES and input("\nType MIRROR to delete them and make the web an exact copy of stock.db: ").strip() != "MIRROR":
            sys.exit("Cancelled - nothing was changed.")

# ── 4. send to Neon in batches (executemany = pipelined, not one round trip per row) ─
step("Sending to Neon…")
with pool.connection() as conn:
    cur = conn.cursor()

    def send(label, sql, data):
        if data:
            cur.executemany(sql, data)
        step(f"  {label}: {len(data)}")

    send("branches", "INSERT INTO branches (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING", b_rows)
    send("items", """INSERT INTO items (id, item_code, name_khmer, name_english, floor, corner, image_url, image_public_id,
                                        sell_price, unit_price, original_qty, stock_add_qty, transfer_qty, sell_qty,
                                        created_at, updated_at)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,%s,%s)
                     ON CONFLICT (id) DO UPDATE SET
                       item_code=EXCLUDED.item_code, name_khmer=EXCLUDED.name_khmer, name_english=EXCLUDED.name_english,
                       floor=EXCLUDED.floor, corner=EXCLUDED.corner,
                       image_url=CASE WHEN EXCLUDED.image_url <> '' THEN EXCLUDED.image_url ELSE items.image_url END,
                       image_public_id=CASE WHEN EXCLUDED.image_public_id <> '' THEN EXCLUDED.image_public_id ELSE items.image_public_id END,
                       sell_price=EXCLUDED.sell_price, unit_price=EXCLUDED.unit_price,
                       original_qty=EXCLUDED.original_qty, updated_at=EXCLUDED.updated_at""", i_rows)
    send("distributor prices", """INSERT INTO item_distributors (item_id, distributor_name, cost_price, last_price_date)
                                  VALUES (%s,%s,%s,%s)
                                  ON CONFLICT (item_id, distributor_name) DO UPDATE
                                  SET cost_price=EXCLUDED.cost_price, last_price_date=EXCLUDED.last_price_date""", d_rows)
    send("customer prices", """INSERT INTO item_customer_prices (item_id, customer_name, special_sell_price, last_price_date)
                               VALUES (%s,%s,%s,%s)
                               ON CONFLICT (item_id, customer_name) DO UPDATE
                               SET special_sell_price=EXCLUDED.special_sell_price, last_price_date=EXCLUDED.last_price_date""", c_rows)
    send("receives", """INSERT INTO purchase_invoices (invoice_code, distributor_name, receive_date, notes, total_cost, created_at,
                                                    is_paid, paid_amount)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (invoice_code) DO UPDATE SET distributor_name=EXCLUDED.distributor_name,
                          receive_date=EXCLUDED.receive_date, notes=EXCLUDED.notes, total_cost=EXCLUDED.total_cost,
                          is_paid=EXCLUDED.is_paid, paid_amount=EXCLUDED.paid_amount""", pi_rows)
    send("receive lines", """INSERT INTO purchase_items (id, invoice_code, item_id, qty_receive, unit_price, receive_date, distributor_name)
                             VALUES (%s,%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (id) DO UPDATE SET qty_receive=EXCLUDED.qty_receive, unit_price=EXCLUDED.unit_price,
                               receive_date=EXCLUDED.receive_date, distributor_name=EXCLUDED.distributor_name""", pl_rows)
    send("sales", """INSERT INTO invoice_records (sale_code, sale_date, customer_name, sender_tel, receiver_tel,
                                                  grand_total, notes, created_at, is_paid, paid_amount,
                                                  discount_percent, discount_amount)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (sale_code) DO UPDATE SET sale_date=EXCLUDED.sale_date, customer_name=EXCLUDED.customer_name,
                       sender_tel=EXCLUDED.sender_tel, receiver_tel=EXCLUDED.receiver_tel,
                       grand_total=EXCLUDED.grand_total, notes=EXCLUDED.notes, is_paid=EXCLUDED.is_paid,
                       paid_amount=EXCLUDED.paid_amount, discount_percent=EXCLUDED.discount_percent,
                       discount_amount=EXCLUDED.discount_amount""", sh_rows)
    send("sale lines", """INSERT INTO sales (id, sale_code, sale_date, customer_name, item_id, qty, unit_price, sell_price)
                          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                          ON CONFLICT (id) DO UPDATE SET qty=EXCLUDED.qty, unit_price=EXCLUDED.unit_price,
                            sell_price=EXCLUDED.sell_price, sale_date=EXCLUDED.sale_date,
                            customer_name=EXCLUDED.customer_name""", sl_rows)
    send("transfers", """INSERT INTO transfers (transfer_code, branch_name, driver_name, note, total_cost, is_paid, created_at, paid_amount)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                         ON CONFLICT (transfer_code) DO UPDATE SET branch_name=EXCLUDED.branch_name,
                           driver_name=EXCLUDED.driver_name, note=EXCLUDED.note, total_cost=EXCLUDED.total_cost,
                           is_paid=EXCLUDED.is_paid, paid_amount=EXCLUDED.paid_amount""", th_rows)
    send("transfer lines", """INSERT INTO transfer_items (id, transfer_code, item_id, qty, unit_cost, supplier_name, remark, sell_price)
                              VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                              ON CONFLICT (id) DO UPDATE SET qty=EXCLUDED.qty, unit_cost=EXCLUDED.unit_cost,
                                supplier_name=EXCLUDED.supplier_name, remark=EXCLUDED.remark,
                                sell_price=EXCLUDED.sell_price""", tl_rows)
    send("code counters", """INSERT INTO counters (prefix, n) VALUES (%s, %s)
                             ON CONFLICT (prefix) DO UPDATE SET n = GREATEST(counters.n, EXCLUDED.n)""", counters)
    if MIRROR and to_delete:
        step("Deleting rows that are not in stock.db…")
        # children first (transfer_items has no ON DELETE CASCADE), then parents
        for table in ("transfer_items", "sales", "purchase_items", "transfers", "invoice_records", "purchase_invoices"):
            if table in to_delete:
                cur.execute(f"DELETE FROM {table} WHERE {KEYCOL[table]} = ANY(%s)", (to_delete[table],))
        if "items" in to_delete:
            cur.execute("DELETE FROM transfer_items WHERE item_id = ANY(%s)", (to_delete["items"],))
            cur.execute("DELETE FROM items WHERE id = ANY(%s)", (to_delete["items"],))   # prices / purchase / sale lines cascade
        # supplier / customer price rows that were removed in Windows
        want_d = {(a, b) for a, b, _, _ in d_rows}
        want_c = {(a, b) for a, b, _, _ in c_rows}
        cur.execute("SELECT item_id, distributor_name FROM item_distributors")
        gone = [(r["item_id"], r["distributor_name"]) for r in cur.fetchall() if (r["item_id"], r["distributor_name"]) not in want_d]
        if gone:
            cur.executemany("DELETE FROM item_distributors WHERE item_id = %s AND distributor_name = %s", gone)
        cur.execute("SELECT item_id, customer_name FROM item_customer_prices")
        gone = [(r["item_id"], r["customer_name"]) for r in cur.fetchall() if (r["item_id"], r["customer_name"]) not in want_c]
        if gone:
            cur.executemany("DELETE FROM item_customer_prices WHERE item_id = %s AND customer_name = %s", gone)
    step("Rebuilding stock totals…")
    cur.execute("""UPDATE items SET
                     stock_add_qty = COALESCE((SELECT SUM(qty_receive) FROM purchase_items WHERE item_id = items.id), 0),
                     transfer_qty  = COALESCE((SELECT SUM(qty) FROM transfer_items WHERE item_id = items.id), 0),
                     sell_qty      = COALESCE((SELECT SUM(qty) FROM sales WHERE item_id = items.id), 0)""")

with pool.connection() as conn:
    counts = {t: conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()["c"] for t in
              ("branches", "items", "purchase_invoices", "purchase_items", "invoice_records", "sales",
               "transfers", "transfer_items")}
step(f"Done. Rows now in Neon: {counts}")
if skipped:
    print(f"\n{len(skipped)} record(s) were skipped (broken links in the old data):")
    for line in skipped[:50]:
        print("  -", line)
pool.close()          # stops the connection pool cleanly (no 'couldn't stop thread' warnings)