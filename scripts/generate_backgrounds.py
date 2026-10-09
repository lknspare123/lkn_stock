"""
Make the AI background for pictures that are ALREADY in Cloudinary / your items.

    $env:DATABASE_URL         = 'postgresql://...'
    $env:CLOUDINARY_URL       = 'cloudinary://API_KEY:API_SECRET@CLOUD_NAME'
    $env:CLOUDINARY_TEMPLATE  = 'your_template_name'          # the name after t_ in the template's URL
    #   or:  $env:CLOUDINARY_BG_PROMPT = 'Light blue background with soft reflections'

    python scripts/generate_backgrounds.py --dry-run          # see how many pictures would be processed
    python scripts/generate_backgrounds.py --limit 5          # try 5 first and look at the result
    python scripts/generate_backgrounds.py                    # everything that has no AI background yet

Options
    --limit N        process only N pictures
    --only A,B,C     only these item codes
    --force          also redo pictures that already have an AI background
    --dry-run        change nothing
    --yes            do not ask for confirmation

Each picture uses Cloudinary generative-AI credits, so test with --limit first. The plain original stays in Cloudinary;
the new picture is saved next to it as <code>_bg and the item is switched to it. Safe to run again: pictures that already
have a background are skipped. Failed ones are listed in backgrounds_failed.txt - run again to retry only those.
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
args = sys.argv[1:]
DRY, FORCE, YES = "--dry-run" in args, "--force" in args, "--yes" in args


def opt(name):
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""


LIMIT = int(opt("--limit") or 0)
ONLY = {c.strip().lower() for c in opt("--only").split(",") if c.strip()}

from core import storage          # noqa: E402
from core.neon_db import DB       # noqa: E402

if not storage.CLOUDINARY_OK:
    sys.exit("CLOUDINARY_URL is missing or invalid.")
if not storage.bg_enabled():
    sys.exit("Set CLOUDINARY_TEMPLATE (your template name) or CLOUDINARY_BG_PROMPT first.\n\n" + __doc__)

db = DB()
items = [i for i in db.get_all_items() if i.get("image_url")]
todo, done_already = [], 0
for i in items:
    pid = i.get("image_public_id", "")
    if ONLY and i["item_code"].lower() not in ONLY:
        continue
    if pid.endswith("_bg") and not FORCE:
        done_already += 1
        continue
    todo.append(i)
if LIMIT:
    todo = todo[:LIMIT]

print(f"Using {storage.bg_description()}")
print(f"  pictures in total:        {len(items)}")
print(f"  already have a background: {done_already}")
print(f"  will be processed:        {len(todo)}")
if DRY or not todo:
    print("\nDry run - nothing changed." if DRY else "\nNothing to do.")
    for i in todo[:10]:
        print("  would process", i["item_code"])
    sys.exit(0)
if not YES and input(f"\nThis uses Cloudinary AI credits for {len(todo)} pictures. Type YES to continue: ").strip() != "YES":
    sys.exit("Cancelled - nothing was changed.")


def work(it):
    pid = it.get("image_public_id", "")
    original = pid[:-3] if pid.endswith("_bg") else (pid or storage.original_public_id(it["item_code"]))
    try:
        url, new_pid = storage.bake_background(it["item_code"], source_public_id=original)
        db.set_item_image(it["id"], url, new_pid)
        return it["item_code"], None
    except Exception as e:
        return it["item_code"], f"{type(e).__name__}: {str(e)[:160]}"


ok, failed, n = 0, [], 0
t0 = time.time()
with ThreadPoolExecutor(max_workers=3) as ex:
    for fut in as_completed([ex.submit(work, i) for i in todo]):
        code, err = fut.result()
        n += 1
        if err:
            failed.append((code, err))
        else:
            ok += 1
        if n % 5 == 0 or n == len(todo):
            print(f"[{time.strftime('%H:%M:%S')}] {n}/{len(todo)}  ok {ok}, failed {len(failed)}", flush=True)
print(f"\nDone in {time.time() - t0:.0f}s. Backgrounds made: {ok}   Failed: {len(failed)}")
if failed:
    with open("backgrounds_failed.txt", "w", encoding="utf-8") as fh:
        fh.write("item_code\terror\n")
        fh.writelines(f"{c}\t{e}\n" for c, e in failed)
    print("Failed pictures are in backgrounds_failed.txt - run the same command again to retry them.")
    for c, e in failed[:5]:
        print(f"  {c}: {e}")
