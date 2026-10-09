"""
core/firebase_db.py — Firestore data layer (replaces core/database.py).

Collections
-----------
branches            {name}
items               {item_code, name_khmer, name_english, floor, corner,
                     image_url, image_public_id, sell_price, unit_price,
                     distributors:[{distributor_name, cost_price, last_price_date}],
                     customer_prices:[{customer_name, special_sell_price, last_price_date}],
                     original_qty, stock_add_qty, transfer_qty, sell_qty,   <- was main_stock
                     created_at, updated_at}
purchase_invoices   doc id = invoice_code {distributor_name, receive_date, notes, total_cost, created_at}
purchase_items      {invoice_code, item_id, qty_receive, unit_price, receive_date, distributor_name}
invoice_records     doc id = sale_code {sale_date, customer_name, sender_tel, receiver_tel, grand_total, notes}
sales               {sale_code, sale_date, customer_name, item_id, qty, unit_price, sell_price}
transfers           doc id = transfer_code {branch_name, driver_name, note, total_cost, created_at}
transfer_items      {transfer_code, item_id, qty, unit_cost, supplier_name, remark}
counters            doc id = prefix {n}   <- sequential codes (RC0001, SL0001 ...)

on_hand_qty and remain_qty were GENERATED columns in SQLite; here they are
computed in Python by _enrich().
"""
import os
import json
import time
from datetime import datetime, timedelta

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from utils.helpers import now_local


def _load_credentials_info(raw):
    """Parse the service-account JSON, tolerating common copy/paste damage."""
    raw = raw.strip()
    info = json.loads(raw, strict=False)          # strict=False allows real newlines in strings
    if isinstance(info, str):                      # value was wrapped in quotes and escaped
        info = json.loads(info, strict=False)
    pk = info.get("private_key", "")
    pk = pk.replace("\\n", "\n")                  # literal backslash-n -> newline
    if "\n" not in pk.strip():                     # newlines were turned into spaces: rebuild PEM
        body = pk.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "")
        body = "".join(body.split())
        pk = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) \
             + "\n-----END PRIVATE KEY-----\n"
    info["private_key"] = pk
    return info


def _init_app():
    if firebase_admin._apps:
        return
    raw = os.environ.get("FIREBASE_CREDENTIALS_JSON", "")
    if raw.strip():
        info = _load_credentials_info(raw)
        print(f"[firebase] project={info.get('project_id')} account={info.get('client_email')} "
              f"key_id={str(info.get('private_key_id', ''))[:8]}", flush=True)
        cred = credentials.Certificate(info)
    else:
        cred = credentials.Certificate(os.environ.get("FIREBASE_CREDENTIALS_FILE", "serviceAccountKey.json"))
    firebase_admin.initialize_app(cred)


_init_app()
fs = firestore.client()

LOW_STOCK = float(os.environ.get("LOW_STOCK_THRESHOLD", 5))
_CACHE = {"t": 0.0, "data": None}      # dashboard cache (saves Firestore reads)


def _bust():
    _CACHE["t"] = 0.0


DEFAULT_BRANCHES = ["សាខាខេត្តសៀមរាប", "សាខាខេត្តបាត់ដំបង", "សាខាក្រុងព្រះសីហនុ", "សាខាភ្នំពេញថ្មី"]


# ── small helpers ────────────────────────────────────────────────────────────
def _now():
    return now_local().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return now_local().strftime("%Y-%m-%d")


def _eq(field, value):
    return FieldFilter(field, "==", value)


def _query(col, *filters):
    q = fs.collection(col)
    for f in filters:
        q = q.where(filter=f)
    return [{**d.to_dict(), "id": d.id} for d in q.stream()]


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _commit(ops):
    """ops: list of ('set', ref, data) | ('delete', ref). Chunked under the 500 limit."""
    for i in range(0, len(ops), 400):
        batch = fs.batch()
        for op in ops[i:i + 400]:
            if op[0] == "set":
                batch.set(op[1], op[2])
            else:
                batch.delete(op[1])
        batch.commit()


def _enrich(d):
    """Add the values SQLite used to compute with generated columns / subqueries."""
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
    return d


class DB:
    def close(self):  # kept for API compatibility with the desktop version
        pass

    # ── Codes ────────────────────────────────────────────────────────────────
    def next_code(self, prefix):
        ref = fs.collection("counters").document(prefix)

        @firestore.transactional
        def _tx(tx):
            snap = ref.get(transaction=tx)
            n = (snap.to_dict().get("n", 0) if snap.exists else 0) + 1
            tx.set(ref, {"n": n})
            return n

        return f"{prefix}{_tx(fs.transaction()):04d}"

    # ── Branches ─────────────────────────────────────────────────────────────
    def get_branches(self):
        rows = _query("branches")
        if not rows:
            for n in DEFAULT_BRANCHES:
                fs.collection("branches").add({"name": n})
            rows = _query("branches")
        return sorted(rows, key=lambda r: r["name"])

    def add_branch(self, name):
        name = name.strip()
        if not name:
            raise ValueError("Branch name is required")
        if _query("branches", _eq("name", name)):
            raise ValueError("Branch already exists")
        fs.collection("branches").add({"name": name})

    def delete_branch(self, branch_id):
        fs.collection("branches").document(branch_id).delete()

    # ── Items ────────────────────────────────────────────────────────────────
    def get_all_items(self):
        rows = [_enrich({**d.to_dict(), "id": d.id}) for d in fs.collection("items").stream()]
        return sorted(rows, key=lambda r: r.get("item_code", ""))

    def items_map(self):
        return {i["id"]: i for i in self.get_all_items()}

    def get_item(self, item_id):
        snap = fs.collection("items").document(item_id).get()
        return _enrich({**snap.to_dict(), "id": snap.id}) if snap.exists else None

    def insert_item(self, code, kh, en, floor, corner, image_url="", image_public_id="",
                    sell_price=0.0, unit_price=0.0):
        if _query("items", _eq("item_code", code)):
            raise ValueError(f"Item code '{code}' already exists")
        ref = fs.collection("items").document()
        ref.set({
            "item_code": code, "name_khmer": kh, "name_english": en,
            "floor": floor, "corner": corner,
            "image_url": image_url, "image_public_id": image_public_id,
            "sell_price": sell_price, "unit_price": unit_price,
            "distributors": [], "customer_prices": [],
            "original_qty": 0.0, "stock_add_qty": 0.0, "transfer_qty": 0.0, "sell_qty": 0.0,
            "created_at": _now(), "updated_at": _now(),
        })
        _bust()
        return ref.id

    def update_item(self, item_id, kh, en, floor, corner, image_url, image_public_id,
                    sell_price, unit_price):
        fs.collection("items").document(item_id).update({
            "name_khmer": kh, "name_english": en, "floor": floor, "corner": corner,
            "image_url": image_url, "image_public_id": image_public_id,
            "sell_price": sell_price, "unit_price": unit_price, "updated_at": _now(),
        })
        _bust()

    def delete_item(self, item_id):
        if _query("transfer_items", _eq("item_id", item_id)):
            raise ValueError("This item is used in branch transfers and cannot be deleted.")
        ops = [("delete", fs.collection("items").document(item_id))]
        for col in ("purchase_items", "sales"):
            for r in _query(col, _eq("item_id", item_id)):
                ops.append(("delete", fs.collection(col).document(r["id"])))
        _commit(ops)
        _bust()

    def set_original_qty(self, item_id, qty):
        fs.collection("items").document(item_id).update({"original_qty": qty})
        _bust()

    # ── Pricing matrices ─────────────────────────────────────────────────────
    def _upsert_price(self, item_id, field, key, name, value_key, value, price_date):
        ref = fs.collection("items").document(item_id)
        snap = ref.get()
        if not snap.exists:
            return
        rows = snap.to_dict().get(field, [])
        entry = {key: name, value_key: value, "last_price_date": price_date or _today()}
        for i, r in enumerate(rows):
            if r.get(key) == name:
                rows[i] = entry
                break
        else:
            rows.append(entry)
        ref.update({field: rows})

    def save_item_distributor(self, item_id, distributor_name, cost_price, price_date=None):
        if distributor_name:
            self._upsert_price(item_id, "distributors", "distributor_name", distributor_name,
                               "cost_price", cost_price, price_date)

    def delete_item_distributor(self, item_id, distributor_name):
        self._remove_price(item_id, "distributors", "distributor_name", distributor_name)

    def save_item_customer_price(self, item_id, customer_name, special_sell_price, price_date=None):
        if customer_name:
            self._upsert_price(item_id, "customer_prices", "customer_name", customer_name,
                               "special_sell_price", special_sell_price, price_date)

    def delete_item_customer_price(self, item_id, customer_name):
        self._remove_price(item_id, "customer_prices", "customer_name", customer_name)

    def _remove_price(self, item_id, field, key, name):
        ref = fs.collection("items").document(item_id)
        snap = ref.get()
        if snap.exists:
            ref.update({field: [r for r in snap.to_dict().get(field, []) if r.get(key) != name]})

    def get_item_purchase_history(self, item_id):
        rows = _query("purchase_items", _eq("item_id", item_id))
        return sorted(rows, key=lambda r: r.get("receive_date", ""), reverse=True)

    # ── Stock recalculation (same logic as the SQLite engine) ────────────────
    def recalculate_item_stock(self, item_id):
        ref = fs.collection("items").document(item_id)
        if not ref.get().exists:
            return
        add = sum(_num(r.get("qty_receive")) for r in _query("purchase_items", _eq("item_id", item_id)))
        trf = sum(_num(r.get("qty")) for r in _query("transfer_items", _eq("item_id", item_id)))
        sold = sum(_num(r.get("qty")) for r in _query("sales", _eq("item_id", item_id)))
        ref.update({"stock_add_qty": add, "transfer_qty": trf, "sell_qty": sold})
        _bust()

    # ── Purchases / Stock receive ────────────────────────────────────────────
    def get_purchase_receives(self, start_date=None, end_date=None):
        q = fs.collection("purchase_invoices")
        if start_date and end_date:
            q = q.where(filter=FieldFilter("receive_date", ">=", start_date)) \
                 .where(filter=FieldFilter("receive_date", "<=", end_date))
        rows = [{**d.to_dict(), "id": d.id, "invoice_code": d.id} for d in q.stream()]
        return sorted(rows, key=lambda r: (r.get("receive_date", ""), r["invoice_code"]), reverse=True)

    def get_purchase_invoice(self, code):
        snap = fs.collection("purchase_invoices").document(code).get()
        return {**snap.to_dict(), "invoice_code": snap.id} if snap.exists else None

    def get_invoice_items(self, code):
        items = self.items_map()
        out = []
        for r in _query("purchase_items", _eq("invoice_code", code)):
            it = items.get(r["item_id"], {})
            r.update(item_code=it.get("item_code", "?"), name_khmer=it.get("name_khmer", ""),
                     name_english=it.get("name_english", ""),
                     total_cost=_num(r["qty_receive"]) * _num(r["unit_price"]))
            out.append(r)
        return sorted(out, key=lambda r: r["item_code"])

    def insert_purchase_invoice(self, code, distributor_name, receive_date, notes, items_list):
        ref = fs.collection("purchase_invoices").document(code)
        if ref.get().exists:
            raise ValueError("Invoice code already exists")
        distributor_name = distributor_name.strip()
        total = sum(_num(i["qty"]) * _num(i["price"]) for i in items_list)
        ops = [("set", ref, {"distributor_name": distributor_name, "receive_date": receive_date,
                             "notes": notes, "total_cost": round(total, 2), "created_at": _now()})]
        for i in items_list:
            ops.append(("set", fs.collection("purchase_items").document(), {
                "invoice_code": code, "item_id": i["item_id"], "qty_receive": _num(i["qty"]),
                "unit_price": _num(i["price"]), "receive_date": receive_date,
                "distributor_name": distributor_name}))
        _commit(ops)
        for i in items_list:
            self.save_item_distributor(i["item_id"], distributor_name, _num(i["price"]), receive_date)
            self.recalculate_item_stock(i["item_id"])
        return True

    def update_purchase_invoice(self, code, date, distributor_name, notes, lines):
        """lines: [{'id': line_id, 'qty': x, 'price': y}]"""
        distributor_name = distributor_name.strip()
        existing = {r["id"]: r for r in _query("purchase_items", _eq("invoice_code", code))}
        ops, total = [], 0.0
        for ln in lines:
            row = existing.get(ln["id"])
            if not row:
                continue
            row.update(qty_receive=_num(ln["qty"]), unit_price=_num(ln["price"]),
                       receive_date=date, distributor_name=distributor_name)
            total += row["qty_receive"] * row["unit_price"]
            data = {k: v for k, v in row.items() if k != "id"}
            ops.append(("set", fs.collection("purchase_items").document(row["id"]), data))
        ops.append(("set", fs.collection("purchase_invoices").document(code), {
            "distributor_name": distributor_name, "receive_date": date, "notes": notes,
            "total_cost": round(total, 2),
            "created_at": (self.get_purchase_invoice(code) or {}).get("created_at", _now())}))
        _commit(ops)
        for row in existing.values():
            self.save_item_distributor(row["item_id"], distributor_name, row["unit_price"], date)
            self.recalculate_item_stock(row["item_id"])

    def delete_purchase_invoice(self, code):
        rows = _query("purchase_items", _eq("invoice_code", code))
        ops = [("delete", fs.collection("purchase_items").document(r["id"])) for r in rows]
        ops.append(("delete", fs.collection("purchase_invoices").document(code)))
        _commit(ops)
        for r in rows:
            self.recalculate_item_stock(r["item_id"])
        return True

    def delete_purchase_invoice_item(self, line_id):
        ref = fs.collection("purchase_items").document(line_id)
        snap = ref.get()
        if not snap.exists:
            return
        row = snap.to_dict()
        ref.delete()
        left = _query("purchase_items", _eq("invoice_code", row["invoice_code"]))
        inv = fs.collection("purchase_invoices").document(row["invoice_code"])
        if not left:
            inv.delete()
        else:
            inv.update({"total_cost": round(sum(_num(r["qty_receive"]) * _num(r["unit_price"]) for r in left), 2)})
        self.recalculate_item_stock(row["item_id"])

    # ── Sales ────────────────────────────────────────────────────────────────
    def insert_batch_sales(self, sale_code, sale_date, customer_name, sender_tel, receiver_tel,
                           grand_total, cart_items, notes=""):
        ref = fs.collection("invoice_records").document(sale_code)
        if ref.get().exists:
            raise ValueError("Sale code already exists")
        ops = [("set", ref, {"sale_date": sale_date, "customer_name": customer_name,
                             "sender_tel": sender_tel, "receiver_tel": receiver_tel,
                             "grand_total": round(grand_total, 2), "notes": notes,
                             "created_at": _now()})]
        for item_id, it in cart_items.items():
            ops.append(("set", fs.collection("sales").document(), {
                "sale_code": sale_code, "sale_date": sale_date, "customer_name": customer_name,
                "item_id": item_id, "qty": _num(it["qty"]),
                "unit_price": _num(it["unit_price"]), "sell_price": _num(it["sell_price"])}))
        _commit(ops)
        for item_id in cart_items:
            self.recalculate_item_stock(item_id)

    def get_sales(self, start_date=None, end_date=None):
        q = fs.collection("invoice_records")
        if start_date and end_date:
            q = q.where(filter=FieldFilter("sale_date", ">=", start_date)) \
                 .where(filter=FieldFilter("sale_date", "<=", end_date))
        rows = [{**d.to_dict(), "sale_code": d.id} for d in q.stream()]
        return sorted(rows, key=lambda r: (r.get("sale_date", ""), r["sale_code"]), reverse=True)

    def get_sale(self, code):
        snap = fs.collection("invoice_records").document(code).get()
        return {**snap.to_dict(), "sale_code": snap.id} if snap.exists else None

    def get_sale_items(self, code):
        items = self.items_map()
        out = []
        for r in _query("sales", _eq("sale_code", code)):
            it = items.get(r["item_id"], {})
            r.update(item_code=it.get("item_code", "?"), name_khmer=it.get("name_khmer", ""),
                     name_english=it.get("name_english", ""),
                     line_total=_num(r["qty"]) * _num(r["sell_price"]))
            out.append(r)
        return sorted(out, key=lambda r: r["item_code"])

    def delete_sale(self, code):
        rows = _query("sales", _eq("sale_code", code))
        ops = [("delete", fs.collection("sales").document(r["id"])) for r in rows]
        ops.append(("delete", fs.collection("invoice_records").document(code)))
        _commit(ops)
        for r in rows:
            self.recalculate_item_stock(r["item_id"])

    # ── Branch transfers ─────────────────────────────────────────────────────
    def insert_transfer(self, transfer_code, branch_name, driver_name, note, total_cost, items_list):
        ref = fs.collection("transfers").document(transfer_code)
        if ref.get().exists:
            raise ValueError("Transfer code already exists")
        ops = [("set", ref, {"branch_name": branch_name, "driver_name": driver_name, "note": note,
                             "total_cost": round(total_cost, 2), "is_paid": False,
                             "created_at": _now()})]
        for i in items_list:
            ops.append(("set", fs.collection("transfer_items").document(), {
                "transfer_code": transfer_code, "item_id": i["item_id"], "qty": _num(i["qty"]),
                "unit_cost": _num(i["unit_cost"]),
                "supplier_name": (i.get("supplier") or "").strip(),
                "remark": (i.get("remark") or "").strip()}))
        _commit(ops)
        for i in items_list:
            self.recalculate_item_stock(i["item_id"])
        return True

    def get_transfers_history(self, start_date=None, end_date=None, branch_name=None):
        q = fs.collection("transfers")
        if start_date and end_date:
            q = q.where(filter=FieldFilter("created_at", ">=", start_date)) \
                 .where(filter=FieldFilter("created_at", "<=", end_date + " 23:59:59"))
        rows = [{**d.to_dict(), "transfer_code": d.id} for d in q.stream()]
        if branch_name and branch_name.strip():
            rows = [r for r in rows if r.get("branch_name") == branch_name.strip()]
        return sorted(rows, key=lambda r: (r.get("created_at", ""), r["transfer_code"]), reverse=True)

    def get_transfer(self, code):
        snap = fs.collection("transfers").document(code).get()
        return {**snap.to_dict(), "transfer_code": snap.id} if snap.exists else None

    def set_transfer_paid(self, code, paid):
        fs.collection("transfers").document(code).update({"is_paid": bool(paid)})
        _bust()

    def get_transfer_items(self, code):
        items = self.items_map()
        out = []
        for r in _query("transfer_items", _eq("transfer_code", code)):
            it = items.get(r["item_id"], {})
            r.update(item_code=it.get("item_code", "?"), name_khmer=it.get("name_khmer", ""),
                     name_english=it.get("name_english", ""), floor=it.get("floor", ""),
                     corner=it.get("corner", ""),
                     total_cost=_num(r["qty"]) * _num(r["unit_cost"]))
            out.append(r)
        return sorted(out, key=lambda r: r["item_code"])

    def delete_transfer(self, code):
        rows = _query("transfer_items", _eq("transfer_code", code))
        ops = [("delete", fs.collection("transfer_items").document(r["id"])) for r in rows]
        ops.append(("delete", fs.collection("transfers").document(code)))
        _commit(ops)
        for r in rows:
            self.recalculate_item_stock(r["item_id"])
        return True

    # ── Lookups ──────────────────────────────────────────────────────────────
    def get_all_suppliers(self, items=None):
        names = set()
        for it in (items if items is not None else self.get_all_items()):
            names.update(x["distributor_name"] for x in it["distributors"] if x.get("distributor_name"))
        for d in fs.collection("purchase_invoices").select(["distributor_name"]).stream():
            n = (d.to_dict().get("distributor_name") or "").strip()
            if n:
                names.add(n)
        return sorted(names)

    def get_all_customers(self, items=None):
        names = set()
        for it in (items if items is not None else self.get_all_items()):
            names.update(x["customer_name"] for x in it["customer_prices"] if x.get("customer_name"))
        for d in fs.collection("invoice_records").select(["customer_name"]).stream():
            n = (d.to_dict().get("customer_name") or "").strip()
            if n:
                names.add(n)
        return sorted(names)

    # ── Dashboard / reports ──────────────────────────────────────────────────
    def dashboard_stats(self):
        items = self.get_all_items()
        stock_value = sum(i["remain_qty"] * i["avg_unit_price"] for i in items)
        sell_value = sum(_num(s.to_dict().get("qty")) * _num(s.to_dict().get("sell_price"))
                         for s in fs.collection("sales").stream())
        low = [i for i in items if i["remain_qty"] <= 5][:15]
        return {"total_items": len(items), "total_stock_value": stock_value,
                "total_sell_value": sell_value, "low_stock": low}

    def dashboard_data(self, force=False):
        """Everything the dashboard needs in ONE pass (items + sales streamed once), cached 30 s."""
        if not force and _CACHE["data"] and time.time() - _CACHE["t"] < 30:
            return _CACHE["data"]
        items = self.get_all_items()
        imap = {i["id"]: i for i in items}
        today = _today()
        month = today[:7]
        days = [(now_local() - timedelta(days=n)).strftime("%Y-%m-%d") for n in range(29, -1, -1)]
        daily = {d: 0.0 for d in days}
        per_item, total_sales, today_rev, month_rev, month_cost = {}, 0.0, 0.0, 0.0, 0.0
        for snap in fs.collection("sales").stream():
            r = snap.to_dict()
            q = _num(r.get("qty"))
            rev, cost = q * _num(r.get("sell_price")), q * _num(r.get("unit_price"))
            day = r.get("sale_date", "")
            total_sales += rev
            e = per_item.setdefault(r.get("item_id"), {"qty": 0.0, "revenue": 0.0})
            e["qty"] += q
            e["revenue"] += rev
            if day in daily:
                daily[day] += rev
            if day == today:
                today_rev += rev
            if day[:7] == month:
                month_rev += rev
                month_cost += cost
        paid_transfers = sum(_num(t.get("total_cost")) for t in _query("transfers", _eq("is_paid", True)))
        best = []
        for iid, e in sorted(per_item.items(), key=lambda kv: kv[1]["qty"], reverse=True):
            it = imap.get(iid)
            if it and e["qty"] > 0:
                best.append({"id": iid, "code": it["item_code"], "name": it.get("name_english") or it.get("name_khmer"),
                             "qty": e["qty"], "revenue": e["revenue"]})
            if len(best) == 10:
                break
        low = sorted([i for i in items if i["remain_qty"] <= LOW_STOCK], key=lambda i: (i["remain_qty"], i["item_code"]))
        dead = sorted([i for i in items if i["remain_qty"] > 0], key=lambda i: (i["sell_qty"], -i["remain_qty"]))[:10]
        recent_sales = [{**d.to_dict(), "sale_code": d.id} for d in
                        fs.collection("invoice_records").order_by("created_at", direction="DESCENDING").limit(5).stream()]
        recent_transfers = [{**d.to_dict(), "transfer_code": d.id} for d in
                            fs.collection("transfers").order_by("created_at", direction="DESCENDING").limit(5).stream()]
        data = {
            "updated": now_local().strftime("%H:%M:%S"), "threshold": LOW_STOCK,
            "total_items": len(items), "out_of_stock": sum(1 for i in items if i["remain_qty"] <= 0),
            "stock_value": sum(i["remain_qty"] * i["avg_unit_price"] for i in items),
            "sales_total": total_sales, "paid_transfers": paid_transfers, "revenue_total": total_sales + paid_transfers,
            "today_rev": today_rev, "month_rev": month_rev, "month_profit": month_rev - month_cost,
            "month_margin": ((month_rev - month_cost) / month_rev * 100) if month_rev else 0.0,
            "daily": [(d, daily[d]) for d in days], "best": best, "dead": dead,
            "low": low, "recent_sales": recent_sales, "recent_transfers": recent_transfers,
        }
        _CACHE.update(t=time.time(), data=data)
        return data

    def sales_report(self, start_date, end_date):
        """Line-level sales between two dates, joined with item names."""
        q = fs.collection("sales") \
            .where(filter=FieldFilter("sale_date", ">=", start_date)) \
            .where(filter=FieldFilter("sale_date", "<=", end_date))
        items = self.items_map()
        out = []
        for d in q.stream():
            r = d.to_dict()
            it = items.get(r["item_id"], {})
            r["item_code"] = it.get("item_code", "?")
            r["name"] = it.get("name_english") or it.get("name_khmer") or r["item_code"]
            out.append(r)
        return out
