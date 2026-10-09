"""
Try the picture pipeline on ONE photo of yours - before you use it in the app.

    $env:BG_REMOVER = 'cloudflare'      # needs the five R2_* variables too (the photo is placed on R2 for a moment)
    # or, to run the model on this PC instead:  pip install -r requirements-rembg.txt ; $env:BG_REMOVER = 'rembg'
    python scripts/test_images.py "D:\\photos\\brake_pad.jpg"

        -> writes image_test\\before.png, after.png and thumb.png. Open them and judge the result.
           Nothing is kept. (With rembg the first run downloads the model file, ~170 MB.)

    # then, once you have set the five R2_* variables:
    python scripts/test_images.py "D:\\photos\\brake_pad.jpg" --r2

        -> also stores the (same) result on Cloudflare R2, opens the public address to prove that
           R2_PUBLIC_URL works, and deletes the test files again.

    --no-ai    skip the background removal (only test R2)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
args = [a for a in sys.argv[1:] if not a.startswith("--")]
R2, NOAI = "--r2" in sys.argv, "--no-ai" in sys.argv
if not args:
    sys.exit(__doc__)

import requests                    # noqa: E402
from core import storage           # noqa: E402

data = storage._read_bytes(args[0])
use_ai = storage.ai_enabled() and not NOAI
print(f"Background removal: {'ON - ' + storage.bg_description() if use_ai else 'OFF (' + ('--no-ai' if NOAI else 'BG_REMOVER is not set') + ')'}")
print("Processing… (a few seconds)")
original, final, ai_used, warning = storage.process_image(data, ai=use_ai)
os.makedirs("image_test", exist_ok=True)
before = original.copy()
before.thumbnail((storage.MAIN_MAX, storage.MAIN_MAX))
before.save("image_test/before.png")
final.save("image_test/after.png")
storage._make_thumb(final).save("image_test/thumb.png")
print(f"\nAI used: {ai_used}" + (f"\nWARNING: {warning}" if warning else ""))
print(f"before {original.size} -> after {final.size}   (files in the folder 'image_test')")

if R2:
    if not storage.R2_OK:
        sys.exit("\nR2 is not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET and R2_PUBLIC_URL.")
    print("\nUploading to R2…")
    res = storage.store_processed("TEST", original, final, ai_used, warning)
    try:
        for label, url in (("picture ", res["url"]), ("thumbnail", storage.thumb(res["url"])), ("original", res["url"][:-5] + "_o.webp")):
            try:
                r = requests.get(url, timeout=20)
                ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
                print(f"  {label}: {'OK ' if ok else 'FAILED'} (HTTP {r.status_code})  {url}")
            except Exception as e:
                ok = False
                print(f"  {label}: FAILED ({type(e).__name__})  {url}")
            if not ok:
                print("    -> the upload worked but the public address does not. Check R2_PUBLIC_URL and that the bucket's\n"
                      "       'Public Development URL' is enabled (or the custom domain is connected).")
    finally:
        storage.delete_image(res["pid"])
        print("Test files deleted from R2.")
