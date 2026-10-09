"""
Move the item pictures from Cloudinary to Cloudflare R2 - and, if you want, remove their background on the way
(white background). Also use it later to run that over pictures that are already on R2.

    $env:DATABASE_URL = 'postgresql://...neon.tech/neondb?sslmode=require'
    $env:R2_ACCOUNT_ID = '...'; $env:R2_ACCESS_KEY_ID = '...'; $env:R2_SECRET_ACCESS_KEY = '...'
    $env:R2_BUCKET = 'lknstock'; $env:R2_PUBLIC_URL = 'https://pub-xxxx.r2.dev'
    $env:BG_REMOVER = 'clearbackdrop'; $env:CLEARBACKDROP_API_KEY = '...'   # only needed with --ai   (free key: 80 pictures a day, 40 an hour; or 'cloudflare' / 'rembg')

    python scripts/migrate_images_to_r2.py --dry-run             # see what would happen
    python scripts/migrate_images_to_r2.py --limit 5 --ai        # try 5 first and LOOK at the result in the app
    python scripts/migrate_images_to_r2.py                       # move everything to R2 as it is
    python scripts/migrate_images_to_r2.py --ai                  # move everything AND remove the backgrounds

What it does
    without --ai   every picture that is not on R2 yet is downloaded from where it is now (Cloudinary) and stored on R2.
    with --ai      every picture whose background has not been removed yet is processed first - also pictures that are
                   already on R2. A picture that cannot be processed is left unchanged and listed in images_failed.txt,
                   so you can simply run the same command again to retry only those.

Options
    --limit N      process only N pictures          --only A,B,C   only these item codes
    --force        with --ai: also redo pictures that were already processed
    --dry-run      change nothing                   --yes          do not ask for confirmation

Your old Cloudinary pictures are NOT deleted - check the app first, then delete them in the Cloudinary dashboard.
Each picture takes a few seconds. With cloudflare every picture uses 1 of your 5,000 free transformations per month. Test with --limit first.
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
args = sys.argv[1:]
AI, DRY, FORCE, YES = "--ai" in args, "--dry-run" in args, "--force" in args, "--yes" in args


def opt(name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""


LIMIT = int(opt("--limit") or 0)
ONLY = {c.strip().lower() for c in opt("--only").split(",") if c.strip()}

from core import storage          # noqa: E402
from core.neon_db import DB       # noqa: E402

if not storage.R2_OK:
    sys.exit("Cloudflare R2 is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET and R2_PUBLIC_URL.")
if AI and not storage.ai_enabled():
    sys.exit("--ai needs BG_REMOVER=clearbackdrop (or cloudflare / rembg) to be set first.")

if AI:
    print("Getting the background remover ready...", flush=True)
    try:
        storage.warm_up()
    except storage.AIError as e:
        sys.exit(f"Background remover is not ready: {e}")
db = DB()
items = [i for i in db.get_all_items() if i.get("image_url")]
todo, on_r2_done = [], 0
for i in items:
    pid = i.get("image_public_id", "")
    if ONLY and i["item_code"].lower() not in ONLY:
        continue
    needs_move = not storage.is_r2_key(pid)
    needs_ai = AI and (FORCE or not storage.is_ai_cleaned(pid))
    if needs_move or needs_ai:
        todo.append(i)
    else:
        on_r2_done += 1
if LIMIT:
    todo = todo[:LIMIT]

n_move = sum(1 for i in todo if not storage.is_r2_key(i.get("image_public_id", "")))
print(f"  pictures in total:                 {len(items)}")
print(f"  nothing to do (already finished):  {on_r2_done}")
print(f"  will be processed:                 {len(todo)}   ({n_move} moved from Cloudinary, {len(todo) - n_move} already on R2)")
print(f"  Background removal:                {'YES - ' + storage.bg_description() if AI else 'no (add --ai to turn on)'}")
if DRY or not todo:
    print("\nDry run - nothing changed." if DRY else "\nNothing to do.")
    for i in todo[:10]:
        print("  would process", i["item_code"])
    sys.exit(0)
if not YES and input(f"\nProcess {len(todo)} pictures? Type YES to continue: ").strip() != "YES":
    sys.exit("Cancelled - nothing was changed.")


LIMIT_HIT = threading.Event()


def work(it):
    code, url, old_pid = it["item_code"], it["image_url"], it.get("image_public_id", "")
    if LIMIT_HIT.is_set():
        return code, "skipped - the free limit was reached (nothing was changed)"
    last = None
    for attempt in range(2):
        try:
            if storage.is_r2_key(old_pid):                 # already on R2: redo from the stored original
                res = storage.reprocess(url, old_pid, code, ai=True, require_ai=True)
            else:                                          # still on Cloudinary: download it, store on R2
                res = storage.store_image(storage.download_bytes(url), code, ai=AI, require_ai=AI)
            db.set_item_image(it["id"], res["url"], res["pid"])
            storage.delete_image(old_pid)                  # old R2 copy only; Cloudinary is never touched
            return code, None
        except storage.AILimitError as e:
            LIMIT_HIT.set()
            return code, f"limit reached: {e}"
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    return code, f"{type(last).__name__}: {str(last)[:200]}"


ok, failed, n = 0, [], 0
t0 = time.time()
with ThreadPoolExecutor(max_workers=3 if AI else 6) as ex:
    for fut in as_completed([ex.submit(work, i) for i in todo]):
        code, err = fut.result()
        n += 1
        if err:
            failed.append((code, err))
        else:
            ok += 1
        if n % 5 == 0 or n == len(todo):
            print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(todo)}  ok {ok}, failed {len(failed)}", flush=True)
print(f"\nDone in {time.time() - t0:.0f}s. Processed: {ok}   Failed: {len(failed)}")
if LIMIT_HIT.is_set():
    print("\nThe free limit of the background remover was reached, so the script stopped. Nothing is lost: wait (an hour or until tomorrow) and run the SAME command again - it continues with the pictures that are not done.")
if failed:
    with open("images_failed.txt", "w", encoding="utf-8") as fh:
        fh.write("item_code\terror\n")
        fh.writelines(f"{c}\t{e}\n" for c, e in failed)
    print("Failed pictures are in images_failed.txt - run the same command again to retry only those.")
    for c, e in failed[:5]:
        print(f"  {c}: {e}")
