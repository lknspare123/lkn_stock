"""
Upload the item pictures stored on your PC to Cloudinary and link them to the items in Neon.

Use it after a migration / --mirror, which copy the DATA but not the picture files.

    $env:DATABASE_URL   = 'postgresql://...neon.tech/neondb?sslmode=require'
    $env:CLOUDINARY_URL = 'cloudinary://API_KEY:API_SECRET@CLOUD_NAME'

    # A) best: use stock.db, because it knows which picture belongs to which item
    python scripts/upload_local_images.py "D:\\LKN\\stock.db" "D:\\LKN\\assets\\images\\items"

    # B) folder only: picture file names must be the item code, e.g. 10001.jpg -> item 10001
    python scripts/upload_local_images.py "D:\\LKN\\assets\\images\\items"

Options
    --dry-run   show what would be uploaded, upload nothing
    --force     also re-upload items that already have a picture (default: they are skipped)

Safe to run again and again: items that already have a picture are skipped, and a re-upload of the same item
replaces its old picture (the Cloudinary name is always lknstock/items/<item code>). Pictures are uploaded 8 at a time
and a failed picture is retried. Items whose picture file cannot be found are listed in images_missing.txt.
"""
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FLAGS = {a for a in sys.argv[1:] if a.startswith("--")}
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
DRY, FORCE = "--dry-run" in FLAGS, "--force" in FLAGS
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".jfif"}

if not ARGS:
    sys.exit(__doc__)
if len(ARGS) == 1 and os.path.isdir(ARGS[0]):
    db_path, img_dir = "", ARGS[0]
elif len(ARGS) >= 2:
    db_path, img_dir = ARGS[0], ARGS[1]
else:
    sys.exit("Give the pictures FOLDER (and, better, your stock.db first).\n\n" + __doc__)
if not os.path.isdir(img_dir):
    sys.exit(f"Pictures folder not found: {img_dir}")
if db_path and not os.path.isfile(db_path):
    sys.exit(f"stock.db not found: {db_path}")

from core import storage            # noqa: E402
from core.neon_db import pool       # noqa: E402
from utils.helpers import now_local  # noqa: E402

if not DRY and not storage.CLOUDINARY_OK:
    sys.exit("CLOUDINARY_URL is missing or invalid.\nFormat: cloudinary://API_KEY:API_SECRET@CLOUD_NAME  (Cloudinary dashboard -> API Keys)")


def step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 1. what is on this PC ──────────────────────────────────────────────────
files_by_name, files_by_stem = {}, {}
for name in os.listdir(img_dir):
    full = os.path.join(img_dir, name)
    stem, ext = os.path.splitext(name)
    if os.path.isfile(full) and ext.lower() in EXTS:
        files_by_name[name.lower()] = full
        files_by_stem.setdefault(stem.lower(), full)
        files_by_stem.setdefault(storage._public_id(stem).lower(), full)
step(f"Pictures folder: {len(files_by_name)} image files in {img_dir}")

desktop = {}                       # item id (str) -> picture file name recorded in stock.db
if db_path:
    src = sqlite3.connect(db_path)
    src.row_factory = sqlite3.Row
    for r in src.execute("SELECT id, image_path FROM items"):
        p = (r["image_path"] or "").replace("\\", "/")
        if p.strip():
            desktop[str(r["id"])] = os.path.basename(p)
    step(f"stock.db: {len(desktop)} items have a picture recorded")

# ── 2. match them to the items in Neon ─────────────────────────────────────
with pool.connection() as conn:
    items = conn.execute("SELECT id, item_code, image_url FROM items ORDER BY item_code").fetchall()
step(f"Neon: {len(items)} items")

todo, has_pic, missing = [], 0, []
for it in items:
    path = ""
    fname = desktop.get(it["id"], "")
    if fname:
        path = files_by_name.get(fname.lower(), "")                     # the name stock.db recorded
    if not path:                                                          # fall back to <item code>.jpg
        code = it["item_code"].strip()
        path = files_by_stem.get(code.lower()) or files_by_stem.get(storage._public_id(code).lower()) or ""
    if it["image_url"] and not FORCE:
        has_pic += 1
        continue
    if path:
        todo.append((it["id"], it["item_code"], path))
    elif fname or not db_path or it["id"] in desktop:
        missing.append((it["item_code"], fname))

print(f"\n  to upload:                 {len(todo)}")
print(f"  already have a picture:    {has_pic}{'' if FORCE else '  (skipped - use --force to re-upload)'}")
print(f"  {'picture file not found:   ' if db_path else 'no file named by item code:'} {len(missing)}"
      + ("" if db_path else "  (normal if those items have no picture)"))
if missing:
    with open("images_missing.txt", "w", encoding="utf-8") as fh:
        fh.write("item_code\tpicture file name recorded in stock.db\n")
        fh.writelines(f"{c}\t{n}\n" for c, n in missing)
    print("    (full list written to images_missing.txt; first 8:", ", ".join(c for c, _ in missing[:8]) + ")")
if DRY or not todo:
    print("\nDry run - nothing uploaded." if DRY else "\nNothing to upload.")
    for iid, code, path in todo[:10]:
        print(f"  would upload {code:<14} <- {os.path.basename(path)}")
    sys.exit(0)


# ── 3. upload (8 at a time, 3 tries each) and link ──────────────────────────
def upload(job):
    iid, code, path = job
    last = None
    for attempt in range(3):
        try:
            url, pid = storage.upload_item_image(path, code)
            return iid, code, url, pid, None
        except Exception as e:          # network hiccup, file too large (>10 MB on the free plan), bad image...
            last = e
            time.sleep(1.5 * (attempt + 1))
    return iid, code, "", "", f"{type(last).__name__}: {str(last)[:150]}"


step(f"Uploading {len(todo)} pictures to Cloudinary…")
ok, failed, done, pending = 0, [], 0, []
now = now_local().strftime("%Y-%m-%d %H:%M:%S")


def flush():
    """Write finished pictures to Neon with a short-lived connection (Neon closes idle ones)."""
    global pending
    if pending:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany("UPDATE items SET image_url = %s, image_public_id = %s, updated_at = %s WHERE id = %s", pending)
        pending = []


with ThreadPoolExecutor(max_workers=8) as ex:
    for fut in as_completed([ex.submit(upload, j) for j in todo]):
        iid, code, url, pid, err = fut.result()
        done += 1
        if err:
            failed.append((code, err))
        else:
            pending.append((url, pid, now, iid))
            ok += 1
        if len(pending) >= 25 or done == len(todo):
            flush()                      # keep what is finished even if the window is closed later
        if done % 25 == 0 or done == len(todo):
            step(f"  {done}/{len(todo)}  uploaded {ok}, failed {len(failed)}")

print(f"\nDone. Uploaded and linked: {ok}   Failed: {len(failed)}")
if failed:
    with open("images_failed.txt", "w", encoding="utf-8") as fh:
        fh.write("item_code\terror\n")
        fh.writelines(f"{c}\t{e}\n" for c, e in failed)
    print("Failed pictures are listed in images_failed.txt - run the same command again to retry only those:")
    for c, e in failed[:5]:
        print(f"  {c}: {e}")
