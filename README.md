# LKN Stock — web edition

Flask app · **Neon** (Postgres database) · **Cloudinary** (item images) · **GitHub** (code) · **Render** (hosting)

## 1. Neon (database)
1. <https://neon.tech> → sign up → **Create project** (pick a region close to you, e.g. Singapore).
2. In the project dashboard click **Connect** → copy the connection string (keep **Connection pooling** on). It looks like
   `postgresql://user:password@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
3. That is your `DATABASE_URL`. The app creates all its tables automatically on first start — nothing to set up by hand.

## 2. Cloudinary
Dashboard → **API Keys**. Copy the *API environment variable*: `cloudinary://API_KEY:API_SECRET@CLOUD_NAME`.

## 3. Run locally (optional) — Windows PowerShell
```powershell
cd D:\LKN\lknstock-web
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:SECRET_KEY    = 'any-long-random-text'
$env:APP_PASSWORD  = 'your-login-password'
$env:DATABASE_URL  = 'postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require'
$env:CLOUDINARY_URL = 'cloudinary://API_KEY:API_SECRET@CLOUD_NAME'

python app.py            # open http://localhost:5000
```
- Use **single quotes** around values so PowerShell leaves special characters alone.
- These variables only last while that PowerShell window is open; set them again in a new window.
- If `Activate.ps1` is blocked, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

## 4. Push to GitHub — PowerShell
```powershell
git add .
git commit -m "Switch database to Neon"
git push
```
First time only (new repo):
```powershell
git init
git add .
git commit -m "LKN Stock web"
git branch -M main
git remote add origin https://github.com/YOUR-NAME/lkn-stock.git
git push -u origin main
```

## 5. Deploy on Render
1. Render → **New → Blueprint** (uses `render.yaml`) or **New → Web Service** → connect the repo.
   Build: `pip install -r requirements.txt` · Start: `gunicorn app:app --workers 2 --threads 4 --timeout 120`
2. Environment variables:
   | Key | Value |
   |---|---|
   | `APP_PASSWORD` | the login password for the app |
   | `SECRET_KEY` | long random string (Blueprint generates it) |
   | `DATABASE_URL` | the Neon connection string from step 1 |
   | `CLOUDINARY_URL` | `cloudinary://KEY:SECRET@CLOUD` |
   (`FIREBASE_CREDENTIALS_JSON` is no longer needed — you can delete it.)
3. Deploy. Free instances sleep after ~15 min idle (first load takes ~30 s). Neon's free database also sleeps when idle and wakes in about a second.

## 6. Move your existing data into Neon (one time) — PowerShell
Pick the option that matches where your data is now. Both are safe to run again, and both rebuild stock totals and list
anything skipped because of broken links.

### Option A — from your desktop `stock.db` (no Firestore needed)
```powershell
cd D:\LKN\lknstock-web
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:DATABASE_URL   = 'postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require'
$env:CLOUDINARY_URL = 'cloudinary://API_KEY:API_SECRET@CLOUD_NAME'   # only if you want item pictures uploaded

python scripts/migrate_sqlite_to_neon.py "D:\path\to\stock.db" "D:\path\to\assets\images\items"
```
The second path (your item pictures folder) is optional. Pictures are uploaded to Cloudinary; without `CLOUDINARY_URL` the items are
copied without pictures.

### Option B — from Firestore
1. Save your Firebase service-account key as `serviceAccountKey.json` inside this folder. Never commit it; delete it when done.
2. Run:
```powershell
cd D:\LKN\lknstock-web
.venv\Scripts\Activate.ps1
pip install -r requirements-migrate.txt

$env:DATABASE_URL = 'postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require'
python scripts/migrate_firestore_to_neon.py
```
If it prints `429 Quota exceeded`, wait for the Firestore daily quota to reset and run it again. Pictures stay on Cloudinary.

Do **one** of the two. If you already imported from one and run the other later, rows with the same ids are simply overwritten.

## Database layout
| Table | Holds |
|---|---|
| `items` | one row per item, including stock counters (`original_qty`, `stock_add_qty`, `transfer_qty`, `sell_qty`) |
| `item_distributors`, `item_customer_prices` | per-item supplier cost and customer special prices |
| `purchase_invoices` / `purchase_items` | stock receives (header / lines) |
| `invoice_records` / `sales` | sales (header / lines) |
| `transfers` / `transfer_items` | branch transfers (header / lines) |
| `branches`, `counters` | branch list, legacy counters (codes are now generated from the highest existing number: INV-RCV-0001, INV0001, TRF-yyyymmddHHMMSS) |

`on_hand_qty` and `remain_qty` are computed in Python. Stock counters are recalculated from the transaction lines
after every save, inside the same database transaction, so numbers never drift.

`core/firebase_db.py` is the old Firestore layer. The app no longer uses it; it is kept only so the migration script can read your old data.


## Desktop parity (v1.0.5)

This web app now mirrors the Windows (Tkinter) application page by page, with the same Khmer labels and business rules:

* **Items** – 12-column list, low-stock filter, add/edit with image, per-supplier cost and per-customer price matrices,
  purchase history, details, right-click menu. Behind a second password unlock that expires after 30 minutes
  (`ITEMS_PASSWORD`, defaults to `APP_PASSWORD`).
* **Receive / Sales / Branch transfers** – new + history tabs, partial payments (`paid_amount`), "pay in full", mark-paid,
  edit an existing document in place, delete, period summary, printable invoice (browser *Save as PDF*).
  Sales add customers (add / rename), two sender + receiver phone numbers and a discount %; transfers resolve cost
  from the latest receive → supplier price → item default → previous transfer, with per-line supplier, sell price and remark.
* **Reports** – stock, receives, sales, transfers, distributors, customers, branches (+ profit), date + paid filters, detail pop-ups, Excel export.
* **Labels** – scan queue, font size, 21 labels per A4 page (3 × 7), print / save as PDF.
* **Settings** – JSON backup / restore, reset (password + typing `DELETE`), branches, about.

New columns are added automatically on start (`ADD COLUMN IF NOT EXISTS`); nothing needs to be run by hand. Re-run
`scripts/migrate_sqlite_to_neon.py` to carry payments, discounts and transfer sell prices from the desktop database.


## Google Drive backup (daily, 6:00 PM Cambodia time)

Every backup is **one `.db` file** (SQLite format — open it with *DB Browser for SQLite*, or restore it from
Settings → Restore). It is uploaded to the folder **LKN Stock Backups** in your Google Drive (created automatically).
File names carry Cambodia time, e.g. `lkn_stock_backup_2026-10-19_18-00.db`. The newest `BACKUP_KEEP` (default 30) are kept.

**One-time setup (≈10 minutes)**

1. <https://console.cloud.google.com> → create a project → *APIs & Services → Library* → enable **Google Drive API**.
2. *OAuth consent screen* → User type **External** → fill app name + your e-mail → add scope
   `.../auth/drive.file` → add your Gmail as a *Test user* → then click **Publish app** (otherwise the token expires after 7 days;
   `drive.file` needs no Google verification).
3. *Credentials → Create credentials → OAuth client ID* → type **Desktop app** → copy the Client ID and Client secret.
4. On your PC: `python scripts/get_gdrive_token.py CLIENT_ID CLIENT_SECRET` → sign in → it prints three values.
5. In Render → *Environment* add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` and a long random `CRON_SECRET`; redeploy.
6. Open **Settings** in the app and press **☁ បម្រុងទុកទៅ Google Drive ឥឡូវនេះ** to test. The result is listed in the table below the button.

**Schedule (cron-job.org or any scheduler)**

* URL: `https://YOUR-APP.onrender.com/cron/backup`  — method GET or POST
* Header: `Authorization: Bearer YOUR_CRON_SECRET`   (or add `?key=YOUR_CRON_SECRET` to the URL)
* Time: every day **18:00**, time zone **Asia/Phnom_Penh** (= 11:00 UTC)
* The URL answers `200` on success and `500` if the backup failed, so turn on "notify on failure".
* Render free sleeps when idle: add a second job at **17:58** calling `https://YOUR-APP.onrender.com/healthz` to wake it up.

Alternative without a URL: `python scripts/backup_to_drive.py` (Render Cron Job / GitHub Actions) — needs `DATABASE_URL` + the `GOOGLE_*` variables.

## Keeping the web data identical to the Windows app

`scripts/migrate_sqlite_to_neon.py` only **adds and updates** rows, so something deleted in Windows after the last copy stays in the web.

1. **Check (changes nothing):** `python scripts/compare_with_desktop.py "D:\path\stock.db"` — prints the dashboard numbers from both sides,
   row counts per table, and the exact items / invoices that exist on only one side.
2. **Make them identical:** `python scripts/migrate_sqlite_to_neon.py "D:\path\stock.db" --mirror` — shows what will be deleted from the web
   and asks you to type `MIRROR`. Anything created only in the web is deleted, so download a `.db` backup from Settings first.
