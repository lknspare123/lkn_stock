"""
Import the pictures stored on your PC to the cloud (Cloudflare R2) and link them to the items in Neon.

The picture file is named with the item code + "_bg", for example   12003_bg.png   ->   item 12003.
(_bg = the background is already removed, so NO AI / background remover is used and no credit is spent.)

    python scripts/import_bg_pictures.py "D:\\LKN\\bg_pictures"
    python scripts/import_bg_pictures.py "D:\\LKN\\bg_pictures" --dry-run      # only show what would happen

(or use the helper that reads your .env for you:   .\\scripts\\import_bg_pictures.ps1 -Folder "D:\\LKN\\bg_pictures")

Needs the same settings as the other scripts (in .env or as environment variables):
    DATABASE_URL, R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_URL

What it does for every  <code>_bg.<jpg|png|webp|...>  file whose <code> is an item in the database:
    - puts the product on pure white, trims the empty border and centres it on a square (same look as the other pictures)
    - uploads it to R2 (picture + small thumbnail + the untouched original) and saves the link on the item
    - deletes the item's old picture from R2, so nothing is left behind
    - the new picture is marked "background removed", so the AI scripts never spend credit on it again

Options
    --dry-run        show what would be uploaded, change nothing
    --force          also replace items that already have a background-removed picture (default: those are skipped)
    --only-missing   only items that have NO picture at all (never replace an existing one)
    --as-is          do not trim / centre: only put it on white and shrink it if it is huge
    --suffix _bg     the ending of the file names (default _bg)

Safe to run again and again. Files are searched in the folder and its sub-folders; if the same code has several files,
the newest one is used. Lists written next to where you run it:
    bg_no_item.txt     files whose code is not an item in the database
    images_failed.txt  pictures that could not be uploaded (run the same command again to retry only those)
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from PIL import Image, ImageChops  # noqa: E402

EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".jfif"}


def step(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 1. find the files ──────────────────────────────────────────────────────
def find_pictures(folder, suffix, storage):
    """Returns {code (lower case): path} for every file named <code><suffix>.<ext> (newest file wins)."""
    found, newest = {}, {}
    for root, _dirs, names in os.walk(folder):
        for name in names:
            stem, ext = os.path.splitext(name)
            if ext.lower() not in EXTS or not stem.lower().endswith(suffix.lower()):
                continue
            code = stem[: len(stem) - len(suffix)].strip()
            if not code:
                continue
            full = os.path.join(root, name)
            mt = os.path.getmtime(full)
            for key in {code.lower(), storage._public_id(code).lower()}:
                if key not in newest or mt > newest[key]:
                    newest[key], found[key] = mt, full
    return found


# ── 2. make the picture ready (it is already clean: no AI) ───────────────────
def _square_on_white(img, storage):
    w, h = img.size
    pad = max(8, int(max(w, h) * 0.07))
    side = max(w, h) + 2 * pad
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    if side > storage.MAIN_MAX:
        canvas = canvas.resize((storage.MAIN_MAX, storage.MAIN_MAX), Image.LANCZOS)
    return canvas


def finish_clean(img, storage, as_is=False):
    """img comes from storage._open (RGB, or RGBA when the file has transparency). Returns the final white square picture."""
    if img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 250:      # a real cut-out with a transparent background
        return storage._finish_plain(img) if as_is else storage._finish_ai(img)
    rgb = img.convert("RGB")                                                  # opaque picture (for example product on white)
    if as_is:
        return storage._finish_plain(rgb)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255))).convert("L")
    box = diff.point(lambda v: 255 if v > 14 else 0).getbbox()
    if not box:
        raise storage.ImageError("the picture is empty (all white).")
    return _square_on_white(rgb.crop(box), storage)


def make_and_store(job, storage, as_is):
    """Process one picture and put it on R2. Returns (url, key)."""
    data = storage._read_bytes(job["path"])
    original = storage._open(data)
    final = finish_clean(original, storage, as_is)
    res = storage.store_processed(job["code"], original, final, True)      # True = "background removed" (-ai- in the file name)
    return res["url"], res["pid"]


# ── 3. main ───────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="Import <item code>_bg pictures from this PC to R2 + Neon.", add_help=True)
    ap.add_argument("folder", help="the folder with the pictures (sub-folders are searched too)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only-missing", action="store_true")
    ap.add_argument("--as-is", action="store_true")
    ap.add_argument("--suffix", default="_bg")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.folder):
        sys.exit(f"Folder not found: {a.folder}")

    from core import storage            # noqa: E402
    from core.neon_db import pool       # noqa: E402
    from utils.helpers import now_local  # noqa: E402

    if not a.dry_run and not storage.R2_OK:
        sys.exit("Cloudflare R2 is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET and R2_PUBLIC_URL.")

    files = find_pictures(a.folder, a.suffix, storage)
    n_files = len({os.path.normcase(p) for p in files.values()})
    step(f"Folder: {n_files} picture files named <code>{a.suffix}.<ext> in {a.folder}")
    if not n_files:
        sys.exit(f"No files ending with {a.suffix} found (example: 12003{a.suffix}.png).")

    with pool.connection() as conn:
        items = conn.execute("SELECT id, item_code, image_url, image_public_id FROM items ORDER BY item_code").fetchall()
    step(f"Neon: {len(items)} items")

    todo, used, skipped_clean, skipped_has, no_file = [], set(), 0, 0, 0
    for it in items:
        code = (it["item_code"] or "").strip()
        path = ""
        for key in (code.lower(), storage._public_id(code).lower()):
            if key in files:
                path = files[key]
                break
        if not path:
            no_file += 1
            continue
        used.add(os.path.normcase(path))
        old_pid = it.get("image_public_id") or ""
        if a.only_missing and it["image_url"]:
            skipped_has += 1
        elif not a.force and storage.is_ai_cleaned(old_pid):
            skipped_clean += 1
        else:
            todo.append({"id": it["id"], "code": code, "path": path, "old_pid": old_pid})
    orphans = sorted(p for p in {os.path.normcase(v) for v in files.values()} if p not in used)

    print(f"\n  to upload:                         {len(todo)}")
    print(f"  skipped (already background-removed): {skipped_clean}   (use --force to replace them)")
    if a.only_missing:
        print(f"  skipped (already have a picture):    {skipped_has}")
    print(f"  items without a {a.suffix} file:            {no_file}   (normal, they keep what they have)")
    print(f"  files whose code is not an item:     {len(orphans)}")
    if orphans:
        with open("bg_no_item.txt", "w", encoding="utf-8") as fh:
            fh.write("\n".join(orphans) + "\n")
        print("    (list written to bg_no_item.txt; first 5:", ", ".join(os.path.basename(p) for p in orphans[:5]) + ")")
    if a.dry_run or not todo:
        print("\nDry run - nothing uploaded." if a.dry_run else "\nNothing to upload.")
        for j in todo[:10]:
            print(f"  would upload {j['code']:<14} <- {os.path.basename(j['path'])}")
        return 0

    def upload(job):
        last = None
        for attempt in range(3):
            try:
                url, pid = make_and_store(job, storage, a.as_is)
                return job, url, pid, None
            except (storage.ImageError, storage.AIError) as e:       # a bad picture: retrying will not help
                return job, "", "", f"{type(e).__name__}: {str(e)[:150]}"
            except Exception as e:                                    # network hiccup etc.
                last = e
                time.sleep(1.5 * (attempt + 1))
        return job, "", "", f"{type(last).__name__}: {str(last)[:150]}"

    step(f"Uploading {len(todo)} pictures to Cloudflare R2...")
    ok, failed, done, pending = 0, [], 0, []
    now = now_local().strftime("%Y-%m-%d %H:%M:%S")

    def flush():
        """Link the finished pictures in Neon (short connection), then delete the old pictures from R2."""
        nonlocal pending
        if not pending:
            return
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany("UPDATE items SET image_url = %s, image_public_id = %s, updated_at = %s WHERE id = %s",
                                [(u, p, now, i) for (u, p, i, _old) in pending])
        for (_u, new_pid, _i, old) in pending:
            if old and old != new_pid:
                storage.delete_image(old)
        pending = []

    with ThreadPoolExecutor(max_workers=6) as ex:
        for fut in as_completed([ex.submit(upload, j) for j in todo]):
            job, url, pid, err = fut.result()
            done += 1
            if err:
                failed.append((job["code"], err))
            else:
                pending.append((url, pid, job["id"], job["old_pid"]))
                ok += 1
            if len(pending) >= 25 or done == len(todo):
                flush()                          # keep what is finished even if the window is closed later
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
