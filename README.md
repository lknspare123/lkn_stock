# LKN Stock — web edition

Flask app · **Neon** (Postgres database) · **Cloudflare R2** (item images) · **Cloudflare Images** (removes the image background) · **GitHub** (code) · **Render** (hosting)

## 1. Neon (database)
1. <https://neon.tech> → sign up → **Create project** (pick a region close to you, e.g. Singapore).
2. In the project dashboard click **Connect** → copy the connection string (keep **Connection pooling** on). It looks like
   `postgresql://user:password@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`
3. That is your `DATABASE_URL`. The app creates all its tables automatically on first start — nothing to set up by hand.

## 2. Cloudflare R2 (picture storage) + background removal

### 2a. Cloudflare R2
1. <https://dash.cloudflare.com> → **R2 object storage** → **Create bucket** (e.g. `lknstock`; location *Automatic* or *Asia-Pacific*).
2. Make the pictures viewable: open the bucket → **Settings** → **Public access**.
   * Quick start: **Public Development URL → Enable** → copy the `https://pub-xxxx.r2.dev` address. (Cloudflare limits r2.dev and calls it
     a development URL - fine to test.)
   * Recommended for the real shop: **Custom Domains → Connect domain** (a domain/subdomain such as `img.yourdomain.com` on Cloudflare).
     Pictures are then cached by Cloudflare's network.
3. R2 **Overview** page → right side → copy your **Account ID**.
4. R2 **Overview** → **Manage API tokens** → **Create API token** → permission **Object Read & Write** → limit it to your bucket →
   **Create** → copy the **Access Key ID** and **Secret Access Key** (the secret is shown only once).

You now have five values: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL`
(the public address from step 2, **without** a trailing `/`).

### 2b. Background removal with Cloudflare Images (optional)
Cloudflare Images can cut the product out of a photo (`segment=foreground`, the open-source BiRefNet model). It runs **at Cloudflare**, so it
needs no RAM on Render and works on the free plan. It is billed as a normal Images transformation: **5,000 unique transformations per month
are free**, and when they are used up Cloudflare stops (you are not charged) and the app simply stores plain pictures until next month. Each
picture processed uses 1. It only removes the background - the product is never redrawn.

**You need a domain that is added to your Cloudflare account** (the bucket's public address must be your own domain; the `r2.dev` address
does not work for this):

1. Cloudflare → **R2** → your bucket → **Settings** → **Custom Domains** → **Connect Domain** → e.g. `img.yourdomain.com`.
2. Cloudflare → **Images** → **Transformations** → select your domain → turn transformations **on** for it (*Enable for zone*).
3. Use that address as `R2_PUBLIC_URL` (`https://img.yourdomain.com`, no trailing `/`).
4. **Check it in 30 seconds:** upload any photo named `test.jpg` into the bucket (R2 → bucket → Objects → Upload), then open this in your
   browser. You should see the product on a **transparent/checkered** background:
   `https://img.yourdomain.com/cdn-cgi/image/segment=foreground,format=webp,quality=100/test.jpg`
5. Render → Environment → add `BG_REMOVER` = `cloudflare` → redeploy. The **✨ AI** checkbox now appears when you add or edit an item.

What happens: `upload → the photo is placed on R2 for a moment → Cloudflare returns the cut-out → pure white background + small clean-up →
trim and centre on a white square → WebP → R2`. Three files are kept for every picture: the picture shown in the app (max 1000 px), a 360 px
thumbnail, and your **untouched original** (`…_o.webp`). If anything fails the item is still saved with the plain picture and you get a
warning that says why - nothing is lost.

| Warning says | What to do |
|---|---|
| `HTTP 404 / 403 … and no picture` | Step 2 not done (transformations off), or `R2_PUBLIC_URL` is the `r2.dev` address, or Cloudflare **Bot Fight Mode** / a firewall rule blocks Render. Turn Bot Fight Mode off for the domain (Security → Bots) or add a WAF rule that skips it for `/cdn-cgi/image/`. |
| `without a transparent background` | Same checks as above; do the 30-second test in step 4. |
| `free monthly limit of 5,000 … used up` | Wait for next month, or buy the Images Paid plan (the docs list $0.50 per extra 1,000). |
| `R2 … not configured` | One of the five `R2_*` variables is missing. |

> A blurry photo gives a rough edge, and very thin or transparent parts can lose some outline. A plain background in the original photo gives
> the best result. Untick **✨ AI** for a picture that must stay exactly as photographed.

**Alternative without a domain: `BG_REMOVER=rembg`** runs the model on the machine itself (free, no domain). It needs 0.55-1 GB+ of RAM, so it
is **not** for Render's free 512 MB plan - use it on your PC (`pip install -r requirements.txt -r requirements-rembg.txt`, then
`$env:BG_REMOVER = 'rembg'`; `REMBG_MODEL` = `u2net` default, `u2netp` lighter, `isnet-general-use` best).

## 3. Run locally (optional) — Windows PowerShell
```powershell
cd D:\LKN\lknstock-web
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:SECRET_KEY    = 'any-long-random-text'
$env:APP_PASSWORD  = 'your-login-password'
$env:DATABASE_URL  = 'postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require'
$env:R2_ACCOUNT_ID        = 'your-account-id'
$env:R2_ACCESS_KEY_ID     = 'your-access-key-id'
$env:R2_SECRET_ACCESS_KEY = 'your-secret-access-key'
$env:R2_BUCKET            = 'lknstock'
$env:R2_PUBLIC_URL        = 'https://pub-xxxx.r2.dev'
$env:BG_REMOVER           = 'cloudflare'           # optional - background removal (README step 2b)

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
   Build: `pip install -r requirements.txt` · Start: `gunicorn app:app --workers 2 --threads 4 --timeout 180`
2. Environment variables:
   | Key | Value |
   |---|---|
   | `APP_PASSWORD` | the login password for the app |
   | `SECRET_KEY` | long random string (Blueprint generates it) |
   | `DATABASE_URL` | the Neon connection string from step 1 |
   | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | from step 2a |
   | `R2_BUCKET` | your bucket name |
   | `R2_PUBLIC_URL` | public address of the bucket (step 2a), no trailing `/` |
   | `BG_REMOVER` | `cloudflare` to switch background removal on (step 2b); leave out = off |
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
# plus the five R2_* variables from step 2a - only if you want item pictures uploaded

python scripts/migrate_sqlite_to_neon.py "D:\path\to\stock.db" "D:\path\to\assets\images\items"
```
The second path (your item pictures folder) is optional. Pictures are uploaded to Cloudflare R2; without the `R2_*` variables the items are
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
If it prints `429 Quota exceeded`, wait for the Firestore daily quota to reset and run it again. Pictures keep their old address until you run `scripts/migrate_images_to_r2.py` (see below).

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

## Uploading item pictures from your PC to R2

The migration / `--mirror` copy the data only. To upload the picture files (item pictures) and link them to the items in Neon:

```powershell
$env:DATABASE_URL = 'postgresql://...'
# + the five R2_* variables (and BG_REMOVER=cloudflare if you use --ai)
python scripts/upload_local_images.py "D:\path\to\stock.db" "D:\path\to\assets\images\items" --dry-run   # preview
python scripts/upload_local_images.py "D:\path\to\stock.db" "D:\path\to\assets\images\items"             # upload
python scripts/upload_local_images.py "D:\path\to\stock.db" "D:\path\to\assets\images\items" --ai        # upload + remove backgrounds
```

Items that already have a picture are skipped (`--force` re-uploads them). Missing files are listed in `images_missing.txt`,
failed uploads in `images_failed.txt`; running the same command again retries only what is still missing.


## Moving the old Cloudinary pictures to R2 / removing backgrounds of existing pictures

Pictures that are still on Cloudinary keep working (the app still understands their addresses), but new uploads go to R2. To move the
old ones - and optionally remove the background of every picture - run:

```powershell
$env:DATABASE_URL = 'postgresql://...'
# + the five R2_* variables (and BG_REMOVER=cloudflare for --ai)
python scripts/migrate_images_to_r2.py --dry-run            # how many pictures, what would happen
python scripts/migrate_images_to_r2.py --limit 5 --ai       # test on 5, then LOOK at them in the Items page
python scripts/migrate_images_to_r2.py --ai                 # everything (moves to R2 + removes backgrounds)
python scripts/migrate_images_to_r2.py                      # or only move, no AI
```

Failed pictures are listed in `images_failed.txt`; run the same command again to retry only those. Old Cloudinary pictures are never
deleted by the script - once the app shows everything correctly you can delete them in the Cloudinary dashboard.

**One picture:** on the **Items** page, right-click (or press and hold) the item → **✨ AI លុបផ្ទៃខាងក្រោយ (ពណ៌ស)**. It redoes the
background removal from the stored original and replaces the picture (only shown when `BG_REMOVER` is on).

## Customer phone + delivery sticker (Sales)

* **Customer phone:** the Sales form has a "ទូរស័ព្ទអតិថិជន" box. Choosing a customer fills in their saved number; the number you type is saved on the
  invoice (`invoice_records.customer_tel`) and on the customer (`customers.phone`), and is printed on the invoice. A blank box never erases a saved number;
  use ✏ next to the customer to change or clear it. The phone also shows in the sales history and the sales Excel export.
* **Sticker sheets (print now, stick later):** two buttons on the Sales page (new-sale sidebar, and in the history for the selected invoice).
  "🏷 ស្ទីគ័រអតិថិជន ×១០" prints one A4 page with the customer's name + phone number(s) and the **sender's phone number(s)** repeated 10 times (2 × 5).
  The dialog is filled in from the sale (customer name, customer phone, and the sender numbers "លេខអ្នកផ្ញើ ១/២" of the sale; in the new-sale sidebar it
  uses what is typed in the form, otherwise the sender number you used last time). You can change every field before printing; leave the sender
  box empty to print the sticker without the FROM strip.
  "⚠ ស្ទីគ័របាក់បែក ×១០" prints one A4 page with "ប្រយ័ត្នបាក់បែក" repeated 10 times (red outline or solid black, optional FRAGILE line) -
  printed separately because not every order is fragile. Choose 1-20 pages, the paper margin (mm) and whether to show cutting lines.
  In the print window use Paper A4, Margins None, Scale 100 %.

**Customer sticker design:** a coloured card per sticker - header band with your logo + shop name ("ជូនដល់ · TO"), the customer name in large type, the customer's phone
numbers in coloured (filled) pills, and at the bottom a **"អ្នកផ្ញើ · FROM" strip with the sender's number(s) in outlined pills** (up to 2 numbers). Choose the colour (blue, red, green, orange, purple, black) and whether to show the logo/shop name. Text sizes are fitted automatically;
when space is short (2 or more customer numbers + the FROM strip, or a very long name) the header band is dropped automatically so the name and numbers stay large. Set `SHOP_NAME` in Render -> Environment to change the shop name
(default `LKN SPARE PART`). In the print window tick **Background graphics** so the colours print.
