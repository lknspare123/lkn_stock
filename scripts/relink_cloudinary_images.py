"""
Re-link item pictures that are ALREADY on Cloudinary to the items in Neon (no re-upload needed).

Put this file in  scripts/  (or the project root), then from the project folder, in PowerShell:

    $env:DATABASE_URL   = 'postgresql://...neon.tech/neondb?sslmode=require'
    $env:CLOUDINARY_URL = 'cloudinary://API_KEY:API_SECRET@CLOUD_NAME'
    python scripts/relink_cloudinary_images.py            # preview only
    python scripts/relink_cloudinary_images.py --apply    # write to Neon

How it works: the app uploaded every picture as  lknstock/items/<item_code>  (unsafe characters -> "_").
This script lists those pictures with the Cloudinary Admin API, matches them to item codes,
and fills image_url + image_public_id for items whose image_url is empty. Safe to re-run.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import storage, neon_db            # noqa: E402
from core.neon_db import pool                # noqa: E402
import cloudinary.api                        # noqa: E402

APPLY = "--apply" in sys.argv

if not storage.CLOUDINARY_OK:
    sys.exit("CLOUDINARY_URL is missing/invalid. Format: cloudinary://API_KEY:API_SECRET@CLOUD_NAME")

# 1) list every picture in the folder
found = {}                                   # public_id -> secure_url
cursor = None
while True:
    res = cloudinary.api.resources(type="upload", prefix=storage.FOLDER + "/",
                                   max_results=500, next_cursor=cursor)
    for r in res.get("resources", []):
        found[r["public_id"]] = r["secure_url"]
    cursor = res.get("next_cursor")
    if not cursor:
        break
print(f"Cloudinary: {len(found)} pictures in '{storage.FOLDER}/'")

# 2) match to items with an empty image_url
matched, missing = [], []
with pool.connection() as conn:
    items = conn.execute("SELECT id, item_code FROM items WHERE COALESCE(image_url,'') = ''").fetchall()
    print(f"Neon: {len(items)} items have no image_url")
    for it in items:
        pid = f"{storage.FOLDER}/{storage._public_id(it['item_code'])}"
        if pid in found:
            matched.append((found[pid], pid, it["id"], it["item_code"]))
        else:
            missing.append(it["item_code"])

    print(f"Matched: {len(matched)} | no picture on Cloudinary: {len(missing)}")
    for url, pid, _id, code in matched[:5]:
        print(f"  e.g. {code} -> {url}")
    if missing:
        print("  items without a picture (first 10):", ", ".join(missing[:10]))

    if APPLY and matched:
        for url, pid, _id, _code in matched:
            conn.execute("UPDATE items SET image_url=%s, image_public_id=%s WHERE id=%s", (url, pid, _id))
        print(f"Updated {len(matched)} items.")
    elif not APPLY:
        print("\nPreview only. Run again with --apply to save.")
