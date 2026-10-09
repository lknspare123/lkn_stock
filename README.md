# LKN Stock — web edition

Flask app · **Firestore** (database) · **Cloudinary** (item images) · **GitHub** (code) · **Render** (hosting)

## 1. Firebase (Firestore)
1. <https://console.firebase.google.com> → *Add project* → **Build → Firestore Database → Create database** (production mode, pick a region near you, e.g. `asia-southeast1`).
2. **Project settings → Service accounts → Generate new private key**. You get a JSON file.
3. Keep it secret. Never commit it. (Admin SDK bypasses security rules, so the default locked rules are fine — only your server talks to Firestore.)

## 2. Cloudinary
Dashboard → **API Keys**. Copy the *API environment variable*: `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`.

## 3. Run locally (optional)
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env     # fill it in, then load it: export $(grep -v '^#' .env | xargs)
# or simply: put the JSON file next to app.py as serviceAccountKey.json and export APP_PASSWORD + CLOUDINARY_URL
python app.py            # http://localhost:5000
```

## 4. Push to GitHub
```bash
git init && git add . && git commit -m "LKN Stock web"
git branch -M main
git remote add origin https://github.com/<you>/lkn-stock.git
git push -u origin main
```

## 5. Deploy on Render
1. Render → **New → Blueprint** (uses `render.yaml`) or **New → Web Service** → connect the repo.
   Build: `pip install -r requirements.txt` · Start: `gunicorn app:app --workers 2 --threads 4 --timeout 120`
2. Add environment variables:
   | Key | Value |
   |---|---|
   | `APP_PASSWORD` | the login password for the app |
   | `SECRET_KEY` | long random string (Blueprint generates it) |
   | `FIREBASE_CREDENTIALS_JSON` | paste the **entire** service-account JSON |
   | `CLOUDINARY_URL` | `cloudinary://KEY:SECRET@CLOUD` |
3. Deploy. Free instances sleep after ~15 min idle (first load takes ~30 s) — use a paid instance for always-on.

## 6. Move your existing desktop data (optional, one time)
```bash
python scripts/migrate_sqlite_to_firestore.py path/to/stock.db path/to/assets/images/items
```
Copies branches, items, prices, purchases, sales, transfers, uploads images to Cloudinary, and rebuilds stock totals.

## How the SQLite structure maps to Firestore
| SQLite | Firestore |
|---|---|
| items + main_stock + item_distributors + item_customer_prices | one `items` doc (stock counters and price lists embedded) |
| purchase_invoices / purchase_invoice_items | `purchase_invoices` (id = code) / `purchase_items` |
| invoice_records / sales | `invoice_records` (id = code) / `sales` |
| transfers / transfer_items | `transfers` (id = code) / `transfer_items` |
| branches | `branches` |
| `on_hand_qty`, `remain_qty` (generated columns) | computed in Python |
| AUTOINCREMENT codes (`next_code`) | `counters` collection (atomic transaction) |
| local `image_path` | Cloudinary `image_url` + `image_public_id` |

Stock is still **recalculated from the transaction lines** after every save, exactly like `_recalculate_item_stock`, so numbers never drift.
