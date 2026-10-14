"""
app.py — LKN Stock web app (Flask + Firestore + Cloudinary), deployable on Render.
"""
import os
import hmac
from datetime import datetime, timedelta

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, abort, send_from_directory)

from core.firebase_db import DB
from core import storage
from utils.helpers import (fmt_currency, fmt_qty, fmt_date, safe_float,
                           today_str, calc_profit)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=14)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"



application = app  # lets Render's default "gunicorn app:application" work too

db = DB()

# (label, icon, endpoint, endpoint-prefix used to highlight the active tab)
NAV = [
    ("Dashboard", "⬛", "dashboard", "dashboard"),
    ("Items", "📦", "items", "item"),
    ("Main Stock", "🗄", "stock", "stock"),
    ("Stock Receive", "📥", "receive_list", "receive"),
    ("Print Labels", "🏷", "labels", "label"),
    ("Sales", "💰", "sales_list", "sale"),
    ("Branch Transfer", "🚚", "transfers_list", "transfer"),
    ("Reports", "📊", "reports", "report"),
    ("Settings", "⚙", "settings", "setting"),
]

app.jinja_env.filters["currency"] = fmt_currency
app.jinja_env.filters["qty"] = fmt_qty
app.jinja_env.filters["dmy"] = fmt_date
app.jinja_env.filters["thumb"] = storage.thumb


@app.context_processor
def inject_nav():
    return {"nav": NAV, "current": request.endpoint or "", "today": today_str()}


# ── Auth ─────────────────────────────────────────────────────────────────────
@app.before_request
def require_login():
    if request.endpoint in ("login", "static", "healthz", "favicon"):
        return
    if not session.get("auth"):
        return redirect(url_for("login", next=request.path))


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static"),
                               "favicon.ico", mimetype="image/vnd.microsoft.icon")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        expected = os.environ.get("APP_PASSWORD", "")
        given = request.form.get("password", "")
        if expected and hmac.compare_digest(given.encode(), expected.encode()):
            session.clear()
            session["auth"] = True
            session.permanent = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Wrong password.", "error")
    return render_template("login.html")


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Helpers ──────────────────────────────────────────────────────────────────
def f(name, default=""):
    return (request.form.get(name) or default).strip()


def items_payload(items):
    return [{
        "id": i["id"], "code": i["item_code"], "kh": i.get("name_khmer", ""),
        "en": i.get("name_english", ""), "sell_price": i["sell_price"],
        "unit_price": i["unit_price"], "min_cost": i["min_unit_price"] or 0,
        "remain": i["remain_qty"], "image": storage.thumb(i.get("image_url", ""), 120),
        "floor": i.get("floor", ""), "corner": i.get("corner", ""),
        "distributors": [{"name": x["distributor_name"], "cost": x["cost_price"]} for x in i["distributors"]],
        "customers": [{"name": x["customer_name"], "price": x["special_sell_price"]} for x in i["customer_prices"]],
    } for i in items]


def date_range():
    start = request.args.get("start") or today_str()[:8] + "01"
    end = request.args.get("end") or today_str()
    return start, end


# ── Dashboard ────────────────────────────────────────────────────────────────
@app.get("/")
def dashboard():
    return render_template("dashboard.html", s=db.dashboard_stats())


# ── Items ────────────────────────────────────────────────────────────────────
@app.get("/items")
def items():
    q = (request.args.get("q") or "").strip().lower()
    rows = db.get_all_items()
    if q:
        rows = [r for r in rows if q in " ".join([r["item_code"], r.get("name_khmer", ""),
                                                  r.get("name_english", ""), r.get("floor", ""),
                                                  r.get("corner", "")]).lower()]
    return render_template("items.html", rows=rows, q=q)


def _save_item_form(item=None):
    code = item["item_code"] if item else f("item_code")
    if not code:
        raise ValueError("Item code is required")
    url = item.get("image_url", "") if item else ""
    pid = item.get("image_public_id", "") if item else ""
    file = request.files.get("image")
    if item and request.form.get("remove_image"):
        storage.delete_image(pid)
        url = pid = ""
    if file and file.filename:
        new_url, new_pid = storage.upload_item_image(file, code)
        if pid and pid != new_pid:
            storage.delete_image(pid)
        url, pid = new_url, new_pid
    args = (f("name_khmer"), f("name_english"), f("floor"), f("corner"), url, pid,
            safe_float(request.form.get("sell_price")), safe_float(request.form.get("unit_price")))
    if item:
        db.update_item(item["id"], *args)
        return item["id"]
    try:
        return db.insert_item(code, *args)
    except ValueError:
        storage.delete_image(pid)
        raise


@app.route("/items/new", methods=["GET", "POST"])
def item_new():
    if request.method == "POST":
        try:
            item_id = _save_item_form()
            flash("Item created.", "ok")
            return redirect(url_for("item_edit", item_id=item_id))
        except ValueError as e:
            flash(str(e), "error")
        return render_template("item_form.html", item=dict(request.form), is_new=True, history=[])
    return render_template("item_form.html", item={}, is_new=True, history=[])


@app.route("/items/<item_id>", methods=["GET", "POST"])
def item_edit(item_id):
    item = db.get_item(item_id) or abort(404)
    if request.method == "POST":
        try:
            _save_item_form(item)
            flash("Item saved.", "ok")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("item_edit", item_id=item_id))
    return render_template("item_form.html", item=item, is_new=False,
                           history=db.get_item_purchase_history(item_id),
                           suppliers=db.get_all_suppliers(), customers=db.get_all_customers())


@app.post("/items/<item_id>/delete")
def item_delete(item_id):
    item = db.get_item(item_id) or abort(404)
    try:
        db.delete_item(item_id)
        storage.delete_image(item.get("image_public_id", ""))
        flash("Item deleted.", "ok")
        return redirect(url_for("items"))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("item_edit", item_id=item_id))


@app.post("/items/<item_id>/distributor")
def item_distributor_save(item_id):
    name = f("name")
    if name:
        db.save_item_distributor(item_id, name, safe_float(request.form.get("cost_price")))
    return redirect(url_for("item_edit", item_id=item_id) + "#prices")


@app.post("/items/<item_id>/distributor/delete")
def item_distributor_delete(item_id):
    db.delete_item_distributor(item_id, f("name"))
    return redirect(url_for("item_edit", item_id=item_id) + "#prices")


@app.post("/items/<item_id>/customer")
def item_customer_save(item_id):
    name = f("name")
    if name:
        db.save_item_customer_price(item_id, name, safe_float(request.form.get("price")))
    return redirect(url_for("item_edit", item_id=item_id) + "#prices")


@app.post("/items/<item_id>/customer/delete")
def item_customer_delete(item_id):
    db.delete_item_customer_price(item_id, f("name"))
    return redirect(url_for("item_edit", item_id=item_id) + "#prices")


# ── Main stock ───────────────────────────────────────────────────────────────
@app.get("/stock")
def stock():
    q = (request.args.get("q") or "").strip().lower()
    rows = db.get_all_items()
    if q:
        rows = [r for r in rows if q in (r["item_code"] + r.get("name_khmer", "") + r.get("name_english", "")).lower()]
    return render_template("stock.html", rows=rows, q=q)


@app.post("/stock/<item_id>/original")
def stock_set_original(item_id):
    db.set_original_qty(item_id, safe_float(request.form.get("original_qty")))
    flash("Opening quantity updated.", "ok")
    return redirect(url_for("stock", q=request.form.get("q", "")))


# ── Stock receive (purchase invoices) ────────────────────────────────────────
@app.get("/receive")
def receive_list():
    start, end = date_range()
    rows = db.get_purchase_receives(start, end)
    return render_template("receive_list.html", rows=rows, start=start, end=end,
                           total=sum(r.get("total_cost", 0) for r in rows))


@app.route("/receive/new", methods=["GET", "POST"])
def receive_new():
    if request.method == "POST":
        d = request.get_json(force=True)
        lines = [{"item_id": x["item_id"], "qty": safe_float(x["qty"]), "price": safe_float(x["price"])}
                 for x in d.get("items", []) if safe_float(x.get("qty")) > 0]
        if not (d.get("distributor") or "").strip():
            return jsonify(error="Distributor / supplier is required."), 400
        if not lines:
            return jsonify(error="Add at least one item with quantity."), 400
        code = db.next_code("RC")
        db.insert_purchase_invoice(code, d["distributor"], d.get("date") or today_str(),
                                   (d.get("notes") or "").strip(), lines)
        flash(f"Receive {code} saved.", "ok")
        return jsonify(ok=True, redirect=url_for("receive_detail", code=code))
    items = db.get_all_items()
    return render_template("receive_new.html", items=items_payload(items),
                           suppliers=db.get_all_suppliers(items))


@app.route("/receive/<code>", methods=["GET", "POST"])
def receive_detail(code):
    inv = db.get_purchase_invoice(code) or abort(404)
    if request.method == "POST":
        ids = request.form.getlist("line_id")
        qtys = request.form.getlist("qty")
        prices = request.form.getlist("price")
        lines = [{"id": i, "qty": safe_float(q), "price": safe_float(p)} for i, q, p in zip(ids, qtys, prices)]
        db.update_purchase_invoice(code, f("receive_date") or inv["receive_date"],
                                   f("distributor_name"), f("notes"), lines)
        flash("Invoice updated.", "ok")
        return redirect(url_for("receive_detail", code=code))
    return render_template("receive_detail.html", inv=inv, lines=db.get_invoice_items(code),
                           suppliers=db.get_all_suppliers())


@app.post("/receive/<code>/delete")
def receive_delete(code):
    db.delete_purchase_invoice(code)
    flash(f"Receive {code} deleted.", "ok")
    return redirect(url_for("receive_list"))


@app.post("/receive/line/<line_id>/delete")
def receive_line_delete(line_id):
    code = request.values.get("code", "")
    db.delete_purchase_invoice_item(line_id)
    flash("Line removed.", "ok")
    return redirect(url_for("receive_detail", code=code) if db.get_purchase_invoice(code) else url_for("receive_list"))


# ── Sales ────────────────────────────────────────────────────────────────────
@app.get("/sales")
def sales_list():
    start, end = date_range()
    rows = db.get_sales(start, end)
    return render_template("sales_list.html", rows=rows, start=start, end=end,
                           total=sum(r.get("grand_total", 0) for r in rows))


@app.route("/sales/new", methods=["GET", "POST"])
def sale_new():
    if request.method == "POST":
        d = request.get_json(force=True)
        cart = {}
        for x in d.get("items", []):
            qty = safe_float(x.get("qty"))
            if qty <= 0:
                continue
            if x["item_id"] in cart:
                cart[x["item_id"]]["qty"] += qty
            else:
                cart[x["item_id"]] = {"qty": qty, "unit_price": safe_float(x.get("unit_price")),
                                      "sell_price": safe_float(x.get("sell_price"))}
        if not cart:
            return jsonify(error="Add at least one item with quantity."), 400
        total = sum(v["qty"] * v["sell_price"] for v in cart.values())
        code = db.next_code("SL")
        db.insert_batch_sales(code, d.get("date") or today_str(), (d.get("customer") or "").strip(),
                              (d.get("sender_tel") or "").strip(), (d.get("receiver_tel") or "").strip(),
                              total, cart, (d.get("notes") or "").strip())
        flash(f"Sale {code} saved.", "ok")
        return jsonify(ok=True, redirect=url_for("sale_detail", code=code))
    items = db.get_all_items()
    return render_template("sale_new.html", items=items_payload(items),
                           customers=db.get_all_customers(items))


@app.get("/sales/<code>")
def sale_detail(code):
    sale = db.get_sale(code) or abort(404)
    return render_template("sale_detail.html", sale=sale, lines=db.get_sale_items(code))


@app.post("/sales/<code>/delete")
def sale_delete(code):
    db.delete_sale(code)
    flash(f"Sale {code} deleted and stock restored.", "ok")
    return redirect(url_for("sales_list"))


# ── Branch transfers ─────────────────────────────────────────────────────────
@app.get("/transfers")
def transfers_list():
    start, end = date_range()
    branch = request.args.get("branch", "")
    rows = db.get_transfers_history(start, end, branch)
    return render_template("transfers_list.html", rows=rows, start=start, end=end, branch=branch,
                           branches=db.get_branches(), total=sum(r.get("total_cost", 0) for r in rows))


@app.route("/transfers/new", methods=["GET", "POST"])
def transfer_new():
    if request.method == "POST":
        d = request.get_json(force=True)
        lines = [{"item_id": x["item_id"], "qty": safe_float(x["qty"]),
                  "unit_cost": safe_float(x.get("unit_cost")),
                  "supplier": x.get("supplier", ""), "remark": x.get("remark", "")}
                 for x in d.get("items", []) if safe_float(x.get("qty")) > 0]
        if not (d.get("branch") or "").strip():
            return jsonify(error="Choose a destination branch."), 400
        if not lines:
            return jsonify(error="Add at least one item with quantity."), 400
        total = sum(l["qty"] * l["unit_cost"] for l in lines)
        code = db.next_code("TR")
        db.insert_transfer(code, d["branch"].strip(), (d.get("driver") or "").strip(),
                           (d.get("note") or "").strip(), total, lines)
        flash(f"Transfer {code} saved.", "ok")
        return jsonify(ok=True, redirect=url_for("transfer_detail", code=code))
    items = db.get_all_items()
    return render_template("transfer_new.html", items=items_payload(items),
                           branches=db.get_branches(), suppliers=db.get_all_suppliers(items))


@app.get("/transfers/<code>")
def transfer_detail(code):
    t = db.get_transfer(code) or abort(404)
    return render_template("transfer_detail.html", t=t, lines=db.get_transfer_items(code))


@app.post("/transfers/<code>/delete")
def transfer_delete(code):
    db.delete_transfer(code)
    flash(f"Transfer {code} deleted and stock restored.", "ok")
    return redirect(url_for("transfers_list"))


# ── Labels ───────────────────────────────────────────────────────────────────
@app.get("/labels")
def labels():
    return render_template("labels.html", items=items_payload(db.get_all_items()))


# ── Reports ──────────────────────────────────────────────────────────────────
@app.get("/reports")
def reports():
    start, end = date_range()
    lines = db.sales_report(start, end)
    revenue = sum(l["qty"] * l["sell_price"] for l in lines)
    cost = sum(l["qty"] * l["unit_price"] for l in lines)
    profit, margin = calc_profit(revenue, cost)
    top = {}
    for l in lines:
        t = top.setdefault(l["item_id"], {"code": l["item_code"], "name": l["name"], "qty": 0, "revenue": 0, "cost": 0})
        t["qty"] += l["qty"]
        t["revenue"] += l["qty"] * l["sell_price"]
        t["cost"] += l["qty"] * l["unit_price"]
    top_rows = sorted(top.values(), key=lambda r: r["revenue"], reverse=True)[:20]
    purchases = sum(r.get("total_cost", 0) for r in db.get_purchase_receives(start, end))
    transfers = sum(r.get("total_cost", 0) for r in db.get_transfers_history(start, end))
    return render_template("reports.html", start=start, end=end, revenue=revenue, cost=cost,
                           profit=profit, margin=margin, top=top_rows,
                           purchases=purchases, transfers=transfers)


# ── Settings ─────────────────────────────────────────────────────────────────
@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        try:
            db.add_branch(f("name"))
            flash("Branch added.", "ok")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("settings"))
    return render_template("settings.html", branches=db.get_branches())


@app.post("/settings/branch/<branch_id>/delete")
def branch_delete(branch_id):
    db.delete_branch(branch_id)
    flash("Branch removed.", "ok")
    return redirect(url_for("settings"))


@app.errorhandler(413)
def too_large(_):
    flash("Image is too large (max 8 MB).", "error")
    return redirect(request.referrer or url_for("items"))


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))