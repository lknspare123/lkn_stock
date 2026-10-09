"""core/storage.py - item pictures: the background is removed, THEN the picture is stored on Cloudflare R2.

Pipeline for every new picture
    upload -> Pillow (rotate, size) -> cut the product out (Cloudflare Images "segment", or rembg)
           -> Pillow (pure white background, trim, centre on a square, small clean-up) -> WebP -> Cloudflare R2

The cut-out only REMOVES the background - the product is never redrawn, so printed text and part numbers stay as photographed.

Three files are written to R2 for each picture (unique name each time, so browsers never show a stale picture):
    lknstock/items/<code>-ai-1a2b3c4d.webp      the picture the app shows   (max 1000 px; "-ai-" = background removed)
    lknstock/items/<code>-ai-1a2b3c4d_t.webp    360 px square thumbnail     (lists, small previews)
    lknstock/items/<code>-ai-1a2b3c4d_o.webp    your original, untouched    (kept so the step can be redone)
The key of the main file is saved in items.image_public_id (the same column Cloudinary used).

Environment variables (Render -> Environment)
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_URL     (required)
    R2_ENDPOINT        optional - only if your bucket is in a special jurisdiction (e.g. EU)
    BG_REMOVER         cloudflare  -> Cloudflare Images "segment" (BiRefNet model). Runs at Cloudflare: NO server RAM needed, works on
                                      Render's free plan. 5,000 pictures/month free. Needs R2_PUBLIC_URL to be a domain of YOUR Cloudflare
                                      account (R2 "Custom Domain") with Images -> Transformations enabled for it.
                       clearbackdrop -> ClearBackdrop API (free key: 80 pictures a day, 40 an hour). Runs outside Render, so no RAM, no domain,
                                      works from the phone. Needs CLEARBACKDROP_API_KEY (https://clearbackdrop.com/signup?next=/account).
                                      Your photos are sent to that company's server.
                       rembg       -> runs the model on this machine (free, no domain needed, but needs 0.55-1 GB+ of RAM; see below)
                       (empty)     -> off: pictures are only resized and stored.
    REMBG_MODEL        (rembg only) u2netp (default, fastest) | silueta | u2net (better edges, ~3x slower) | isnet-general-use (best)
    REMBG_THREADS      (rembg only) CPU threads used by the model (default: number of CPU cores, 2-8)
    REMBG_SIZE         (rembg only) longest side of the picture given to the model (default 768; smaller = faster)

MEMORY (rembg only): measured peak use on top of the ~100 MB of the web app: u2netp ~0.55 GB, u2net ~0.8 GB, isnet-general-use ~1 GB+.
"""
from __future__ import annotations

import io
import os
import re
import threading
import time
import uuid

import requests
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

Image.MAX_IMAGE_PIXELS = 120_000_000          # refuse "decompression bombs" (Pillow also warns at half of this)


def _clean(v):
    return (v or "").strip().strip("\"'").strip()


# ── Cloudflare R2 settings ────────────────────────────────────────────────────
R2_ACCOUNT_ID = _clean(os.environ.get("R2_ACCOUNT_ID"))
R2_ACCESS_KEY_ID = _clean(os.environ.get("R2_ACCESS_KEY_ID"))
R2_SECRET_ACCESS_KEY = _clean(os.environ.get("R2_SECRET_ACCESS_KEY"))
R2_BUCKET = _clean(os.environ.get("R2_BUCKET"))
R2_ENDPOINT = _clean(os.environ.get("R2_ENDPOINT")) or (f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else "")
R2_PUBLIC_URL = _clean(os.environ.get("R2_PUBLIC_URL")).rstrip("/")
if R2_PUBLIC_URL and "://" not in R2_PUBLIC_URL:
    R2_PUBLIC_URL = "https://" + R2_PUBLIC_URL
R2_OK = all([R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_URL])
if not R2_OK:
    _missing = [n for n, v in (("R2_ACCOUNT_ID", R2_ENDPOINT), ("R2_ACCESS_KEY_ID", R2_ACCESS_KEY_ID),
                               ("R2_SECRET_ACCESS_KEY", R2_SECRET_ACCESS_KEY), ("R2_BUCKET", R2_BUCKET),
                               ("R2_PUBLIC_URL", R2_PUBLIC_URL)) if not v]
    print(f"[storage] WARNING: Cloudflare R2 is not configured (missing: {', '.join(_missing)}). "
          "Image uploads are disabled until it is fixed.", flush=True)

# ── Background removal settings ───────────────────────────────────────────────
_bg_setting = _clean(os.environ.get("BG_REMOVER")).lower()
if _bg_setting in ("cloudflare", "cf"):
    BG_ENGINE = "cloudflare"
elif _bg_setting in ("clearbackdrop", "cb", "api"):
    BG_ENGINE = "clearbackdrop"
elif _bg_setting in ("rembg", "1", "true", "yes", "on"):
    BG_ENGINE = "rembg"
else:
    BG_ENGINE = ""
BG_ENABLED = bool(BG_ENGINE)
CB_API_KEY = _clean(os.environ.get("CLEARBACKDROP_API_KEY"))
CB_URL = "https://clearbackdrop.com/api/v1"          # use the non-www host: www redirects and drops the picture
try:
    CB_TIMEOUT = max(30, int(_clean(os.environ.get("CLEARBACKDROP_TIMEOUT")) or 90))   # total seconds to wait for one picture
except ValueError:
    CB_TIMEOUT = 90
REMBG_MODEL = _clean(os.environ.get("REMBG_MODEL")) or "u2netp"      # u2netp = fastest; u2net = better edges; isnet-general-use = best
_cores = os.cpu_count() or 2
try:
    REMBG_THREADS = max(1, int(_clean(os.environ.get("REMBG_THREADS")) or min(8, max(2, _cores))))
except ValueError:
    REMBG_THREADS = min(8, max(2, _cores))

FOLDER = "lknstock/items"
MAIN_MAX = 1000         # longest side of the picture the app shows
THUMB = 360             # square thumbnail
ORIG_MAX = 1600         # the untouched original is kept at this size at most
CUT_INPUT_MAX = 1024    # the model works on a picture of at most this size (saves memory and time)
try:
    REMBG_SIZE = max(320, int(_clean(os.environ.get("REMBG_SIZE")) or 768))   # rembg only: smaller = faster
except ValueError:
    REMBG_SIZE = 768
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_CACHE = "public, max-age=31536000, immutable"


class ImageError(ValueError):
    """The uploaded file is not a usable picture (the app shows the message to the person)."""


class AIError(RuntimeError):
    """The background could not be removed."""


class AILimitError(AIError):
    """The free daily / hourly limit of the background-removal service is used up (batch scripts stop and can be run again later)."""


def ai_enabled() -> bool:
    return BG_ENABLED


bg_enabled = ai_enabled          # old name, kept so older code keeps working


def bg_description() -> str:
    if BG_ENGINE == "cloudflare":
        return "Cloudflare Images (segment=foreground)"
    if BG_ENGINE == "clearbackdrop":
        return "ClearBackdrop API (free key: 80 pictures a day, 40 an hour)"
    return f"rembg model '{REMBG_MODEL}'"


# ── names ─────────────────────────────────────────────────────────────────────
def _public_id(item_code: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", item_code or "").strip("_")
    return safe or uuid.uuid4().hex[:10]


def _new_key(item_code: str, ai_used: bool) -> str:
    return f"{FOLDER}/{_public_id(item_code)}-{'ai-' if ai_used else ''}{uuid.uuid4().hex[:8]}.webp"


def _thumb_key(key: str) -> str:
    return key[:-5] + "_t.webp"


def _orig_key(key: str) -> str:
    return key[:-5] + "_o.webp"


def is_r2_key(pid: str) -> bool:
    """True for a picture stored on R2 (old Cloudinary pictures have no .webp key)."""
    return bool(pid) and pid.startswith(FOLDER + "/") and pid.endswith(".webp")


def is_ai_cleaned(pid: str) -> bool:
    return bool(re.search(r"-ai-[0-9a-f]{8}\.webp$", pid or ""))


def public_url(key: str) -> str:
    return f"{R2_PUBLIC_URL}/{key}"


def thumb(url: str, size=80) -> str:
    """URL of the small version of a picture (used by the {{ url|thumb(120) }} template filter)."""
    if not url:
        return ""
    if "/upload/" in url:            # a picture that is still on Cloudinary (not moved to R2 yet)
        return url.replace("/upload/", f"/upload/c_fill,w_{size},h_{size},q_auto,f_auto/", 1)
    if url.endswith(".webp") and f"/{FOLDER}/" in url and not url.endswith(("_t.webp", "_o.webp")):
        return url[:-5] + "_t.webp"
    return url


# ── Cloudflare R2 ─────────────────────────────────────────────────────────────
_client_lock = threading.Lock()
_client_obj = None


def _client():
    global _client_obj
    if not R2_OK:
        raise ValueError("Image storage is not configured: set the R2_* environment variables on Render "
                         "(R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_URL).")
    with _client_lock:
        if _client_obj is None:
            import boto3
            from botocore.config import Config
            _client_obj = boto3.client(
                "s3", endpoint_url=R2_ENDPOINT, aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY, region_name="auto",
                config=Config(signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"},
                              connect_timeout=10, read_timeout=30,
                              request_checksum_calculation="when_required",
                              response_checksum_validation="when_required"))
        return _client_obj


def _put(key: str, data: bytes):
    _client().put_object(Bucket=R2_BUCKET, Key=key, Body=data, ContentType="image/webp", CacheControl=_CACHE)


def _get(key: str) -> bytes:
    return _client().get_object(Bucket=R2_BUCKET, Key=key)["Body"].read()


def delete_image(public_id: str, with_original: bool = True):
    """Delete a picture from R2 (main + thumbnail + original). Old Cloudinary pictures are left alone."""
    if not R2_OK or not is_r2_key(public_id):
        return
    keys = [public_id, _thumb_key(public_id)] + ([_orig_key(public_id)] if with_original else [])
    try:
        _client().delete_objects(Bucket=R2_BUCKET, Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True})
    except Exception as e:
        print(f"[storage] could not delete {public_id}: {e}", flush=True)


# ── reading / preparing the picture ───────────────────────────────────────────
def _read_bytes(file_or_path) -> bytes:
    if isinstance(file_or_path, (bytes, bytearray)):
        data = bytes(file_or_path)
    elif isinstance(file_or_path, (str, os.PathLike)):
        with open(file_or_path, "rb") as fh:
            data = fh.read()
    else:
        try:
            file_or_path.seek(0)
        except Exception:
            pass
        data = file_or_path.read()
    if not data:
        raise ImageError("The picture file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError(f"The picture is too large ({len(data) // 1024 // 1024} MB, the limit is 25 MB).")
    return data


def download_bytes(url: str) -> bytes:
    """Download a picture that is already online (for example from Cloudinary) - used to move it to R2."""
    r = requests.get(url, timeout=(10, 40))
    r.raise_for_status()
    if len(r.content) > MAX_UPLOAD_BYTES:
        raise ImageError("The picture is too large to process.")
    return r.content


def _open(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        try:
            img.draft("RGB", (ORIG_MAX, ORIG_MAX))           # JPEG: decode at reduced size - a 48 MP phone photo would waste RAM
        except Exception:
            pass
        img.load()
    except Exception:
        raise ImageError("This file is not a picture I can read (use JPG, PNG, WEBP, GIF or BMP).")
    img = ImageOps.exif_transpose(img)                       # phone photos: honour the rotation flag
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
    else:
        img = img.convert("RGB")
    img.thumbnail((ORIG_MAX, ORIG_MAX), Image.LANCZOS)       # nothing bigger than this is ever stored or needed
    return img


def _on_white(img: Image.Image) -> Image.Image:
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.getchannel("A"))
        return bg
    return img.convert("RGB")


def _webp(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue()


# ── Background removal (rembg) ────────────────────────────────────────────────
_cut_lock = threading.Lock()          # one picture at a time: the model needs a lot of memory
_cut_state = {}


def _rembg_session():
    """Load rembg and the model ONCE (the first picture is slower; it may download the model file)."""
    if "session" not in _cut_state:
        try:
            import onnxruntime as ort
            from rembg import new_session, remove
        except ImportError as e:
            raise AIError(f"rembg is not installed or could not be loaded (pip install rembg onnxruntime): {str(e)[:100]}")
        so = ort.SessionOptions()
        so.intra_op_num_threads = REMBG_THREADS
        so.inter_op_num_threads = 1
        so.enable_cpu_mem_arena = False                   # much lower memory use
        so.enable_mem_pattern = False
        _cut_state["session"] = new_session(REMBG_MODEL, sess_opts=so)
        _cut_state["remove"] = remove
    return _cut_state["session"], _cut_state["remove"]


def _rembg_cut(img: Image.Image) -> Image.Image:
    """Cut the product out of the photo. Returns an RGBA picture (transparent where the background was)."""
    src = _on_white(img)
    src.thumbnail((REMBG_SIZE, REMBG_SIZE), Image.LANCZOS)
    try:
        with _cut_lock:
            session, remove = _rembg_session()
            out = remove(src, session=session, post_process_mask=True)
    except AIError:
        raise
    except MemoryError:
        raise AIError("the server ran out of memory (use REMBG_MODEL=u2netp or a plan with more RAM).")
    except Exception as e:
        raise AIError(f"rembg failed: {type(e).__name__}: {str(e)[:150]}")
    return out.convert("RGBA")


# ── Background removal: Cloudflare Images "segment" ───────────────────────────
CF_TRANSFORM = "segment=foreground,format=webp,quality=100"     # webp keeps the transparency; quality=100 = lossless
_CF_HELP = ("(1) Images -> Transformations is not enabled for this domain, (2) R2_PUBLIC_URL is not a domain of your Cloudflare "
            "account (the r2.dev address cannot be used), or (3) Bot Fight Mode / a firewall rule blocks this server.")


def _cloudflare_cut(img: Image.Image) -> Image.Image:
    """Cut the product out with Cloudflare Images (BiRefNet). The picture is put on R2 for a moment, Cloudflare is asked for
    <domain>/cdn-cgi/image/segment=foreground/<that picture>, and the answer (transparent background) is returned as RGBA."""
    _client()                                                   # R2 must be configured (the picture is placed there first)
    src = _on_white(img)
    src.thumbnail((CUT_INPUT_MAX, CUT_INPUT_MAX), Image.LANCZOS)
    buf = io.BytesIO()
    src.save(buf, "JPEG", quality=92)
    tmp = f"lknstock/tmp/{uuid.uuid4().hex}.jpg"
    url = f"{R2_PUBLIC_URL}/cdn-cgi/image/{CF_TRANSFORM}/{tmp}"
    try:
        _client().put_object(Bucket=R2_BUCKET, Key=tmp, Body=buf.getvalue(), ContentType="image/jpeg", CacheControl="no-store")
        last = "no answer"
        r = None
        for attempt in range(2):                                # one retry for temporary problems
            try:
                r = requests.get(url, timeout=(10, 60), headers={"User-Agent": "lknstock/1.0"})
            except requests.RequestException as e:
                last = f"network problem talking to Cloudflare: {type(e).__name__}"
                r = None
                time.sleep(2)
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                break
            code = (r.headers.get("cf-resized") or "").strip()
            if "9422" in code or r.status_code == 429:
                raise AIError("the free monthly limit of 5,000 Cloudflare transformations is used up (it resets next month).")
            last = f"Cloudflare answered HTTP {r.status_code}" + (f" ({code})" if code else "")
            if "text/html" in r.headers.get("content-type", "") or r.status_code in (403, 404):
                raise AIError(f"{last} and no picture. Check: {_CF_HELP}")
            if r.status_code in (500, 502, 503, 504):
                time.sleep(3 * (attempt + 1))
                r = None
                continue
            raise AIError(last)
        else:
            raise AIError(last)
        try:
            out = Image.open(io.BytesIO(r.content))
            out.load()
        except Exception:
            raise AIError("Cloudflare returned a picture that cannot be read.")
        if not (out.mode in ("RGBA", "LA") or (out.mode == "P" and "transparency" in out.info)):
            raise AIError("Cloudflare returned the picture without a transparent background (segment is not active). Check: " + _CF_HELP)
        return out.convert("RGBA")
    finally:
        try:
            _client().delete_object(Bucket=R2_BUCKET, Key=tmp)  # the temporary picture is always removed
        except Exception:
            pass


# ── Background removal: ClearBackdrop API (free key: 80 pictures a day, 40 an hour) ───────────────
_CB_HELP = ("Check CLEARBACKDROP_API_KEY (create a free key at https://clearbackdrop.com/signup?next=/account) and BG_REMOVER=clearbackdrop.")


def _cb_check_config():
    if not CB_API_KEY:
        raise AIError("CLEARBACKDROP_API_KEY is not set. " + _CB_HELP)


def _cb_headers():
    return {"X-API-Key": CB_API_KEY, "User-Agent": "lknstock/1.0"}


def warm_up(max_wait: int = 240):
    """Get the engine ready (batch scripts call this once): loads the rembg model, or checks the ClearBackdrop key."""
    if BG_ENGINE == "clearbackdrop":
        _cb_check_config()
        try:
            r = requests.get(CB_URL + "/quota", headers=_cb_headers(), timeout=(10, 20))
        except requests.RequestException:
            return                                              # not fatal - the real request will report problems
        if r.status_code in (401, 403):
            raise AIError(f"ClearBackdrop refused the key (HTTP {r.status_code}). " + _CB_HELP)
        if r.status_code == 200:
            print(f"[storage] ClearBackdrop quota: {r.text.strip()[:200]}", flush=True)
        return
    if BG_ENGINE != "rembg":
        return
    with _cut_lock:
        _rembg_session()


def _cb_cut(img: Image.Image) -> Image.Image:
    """Cut the product out with the ClearBackdrop API. Returns RGBA (transparent where the background was)."""
    _cb_check_config()
    src = _on_white(img)
    src.thumbnail((CUT_INPUT_MAX, CUT_INPUT_MAX), Image.LANCZOS)
    buf = io.BytesIO()
    src.save(buf, "JPEG", quality=92)
    payload = buf.getvalue()
    end = time.time() + CB_TIMEOUT
    last, r, attempt = "no answer", None, 0
    while True:
        attempt += 1
        try:
            r = requests.post(CB_URL + "/remove-background", files={"image": ("p.jpg", payload, "image/jpeg")},
                              headers=_cb_headers(), timeout=(10, max(20, min(60, int(end - time.time())))))
        except requests.RequestException as e:
            last, r = f"network problem talking to ClearBackdrop: {type(e).__name__}", None
        if r is not None:
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and ctype.startswith("image/"):
                break
            try:
                msg = (r.json().get("message") or r.json().get("error") or "")[:160]
            except Exception:
                msg = ""
            if r.status_code in (401, 403):
                raise AIError(f"ClearBackdrop refused the key (HTTP {r.status_code}). " + _CB_HELP)
            if r.status_code == 429:
                wait = (r.headers.get("X-RateLimit-Reset") or "").strip()
                raise AILimitError("the free ClearBackdrop limit is used up (80 pictures a day, 40 an hour)"
                                   + (f" - resets in about {wait} s" if wait.isdigit() else "") + (f". {msg}" if msg else ""))
            if r.status_code in (400, 413, 415, 422):
                raise AIError(f"ClearBackdrop did not accept the picture (HTTP {r.status_code}) {msg}".strip())
            last = f"ClearBackdrop answered HTTP {r.status_code} {msg}".strip()
        if time.time() + 5 >= end:
            raise AIError(f"{last}; gave up after {CB_TIMEOUT}s.")
        time.sleep(min(8, 2 * attempt))
    try:
        out = Image.open(io.BytesIO(r.content))
        out.load()
    except Exception:
        raise AIError("ClearBackdrop returned a picture that cannot be read.")
    if not (out.mode in ("RGBA", "LA") or (out.mode == "P" and "transparency" in out.info)):
        raise AIError("ClearBackdrop returned the picture without a transparent background.")
    return out.convert("RGBA")


def _cut_out(img: Image.Image) -> Image.Image:
    """Cut the product out with the engine chosen in BG_REMOVER."""
    if BG_ENGINE == "cloudflare":
        return _cloudflare_cut(img)
    if BG_ENGINE == "clearbackdrop":
        return _cb_cut(img)
    return _rembg_cut(img)


def _finish_ai(cut: Image.Image) -> Image.Image:
    """Put the cut-out product on pure white, tidy it up, trim it and centre it on a white square."""
    alpha = cut.getchannel("A")
    solid = alpha.point(lambda v: 255 if v > 128 else 0)
    if (solid.histogram()[255] / float(cut.width * cut.height)) < 0.01:
        raise AIError("no product was found in the picture.")
    # a 1 px shave + soft edge removes the thin halo of the old background colour around the product
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
    rgb = cut.convert("RGB")
    rgb = ImageOps.autocontrast(rgb, cutoff=0.5, mask=solid, preserve_tone=True)      # fix flat / dull photos
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.15)
    out = Image.new("RGB", cut.size, (255, 255, 255))
    out.paste(rgb, mask=alpha)
    box = alpha.point(lambda v: 255 if v > 24 else 0).getbbox()
    img = out.crop(box)
    w, h = img.size
    pad = max(8, int(max(w, h) * 0.07))
    side = max(w, h) + 2 * pad
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    if side > MAIN_MAX:
        canvas = canvas.resize((MAIN_MAX, MAIN_MAX), Image.LANCZOS)
    return canvas


def _finish_plain(img: Image.Image) -> Image.Image:
    out = _on_white(img)
    out.thumbnail((MAIN_MAX, MAIN_MAX), Image.LANCZOS)
    return out


def _make_thumb(img: Image.Image) -> Image.Image:
    t = img.copy()
    t.thumbnail((THUMB, THUMB), Image.LANCZOS)
    canvas = Image.new("RGB", (THUMB, THUMB), (255, 255, 255))
    canvas.paste(t, ((THUMB - t.width) // 2, (THUMB - t.height) // 2))
    return canvas


# ── public API ────────────────────────────────────────────────────────────────
def process_image(data: bytes, ai: bool = True, require_ai: bool = False):
    """Prepare a picture WITHOUT storing it. Returns (original, final, ai_used, warning).
    ai=True removes the background; if that fails the plain picture is used and `warning` says why
    (unless require_ai=True, then AIError is raised)."""
    original = _open(data)
    final, ai_used, warning = None, False, ""
    if ai or require_ai:
        try:
            if not ai_enabled():
                raise AIError("background removal is switched off (set BG_REMOVER=clearbackdrop or cloudflare).")
            final = _finish_ai(_cut_out(original))
            ai_used = True
        except Exception as e:
            err = e if isinstance(e, AIError) else AIError(f"{type(e).__name__}: {e}")
            if require_ai:
                raise err
            warning = f"Background removal skipped - {err}"
            print(f"[storage] {warning}", flush=True)
    if final is None:
        final = _finish_plain(original)
    return original, final, ai_used, warning


def store_processed(item_code: str, original: Image.Image, final: Image.Image, ai_used: bool, warning: str = "") -> dict:
    """Store an already processed picture (see process_image) on R2. Returns {"url", "pid", "ai_used", "warning"}."""
    key = _new_key(item_code, ai_used)
    orig_small = original.copy()
    orig_small.thumbnail((ORIG_MAX, ORIG_MAX), Image.LANCZOS)
    try:
        _put(key, _webp(final, 88))
        _put(_thumb_key(key), _webp(_make_thumb(final), 80))
        _put(_orig_key(key), _webp(orig_small, 90))
    except Exception:
        delete_image(key)                                     # do not leave half a picture behind
        raise
    return {"url": public_url(key), "pid": key, "ai_used": ai_used, "warning": warning}


def store_image(data: bytes, item_code: str, ai: bool = True, require_ai: bool = False) -> dict:
    """Process a picture and store it on R2. Returns {"url", "pid", "ai_used", "warning"}."""
    _client()                                                 # fail early (before doing the slow AI step) if R2 is not set up
    original, final, ai_used, warning = process_image(data, ai=ai, require_ai=require_ai)
    return store_processed(item_code, original, final, ai_used, warning)


def store_upload(file_or_path, item_code: str, ai: bool = True) -> dict:
    """Store an uploaded file (Flask FileStorage, path or bytes). See store_image."""
    return store_image(_read_bytes(file_or_path), item_code, ai=ai)


def upload_item_image(file_or_path, item_code: str, background: bool = False, ai=None):
    """Old-style helper for the scripts: returns (url, public_id). `background=True` (or ai=True) removes the background first."""
    res = store_image(_read_bytes(file_or_path), item_code, ai=background if ai is None else ai)
    return res["url"], res["pid"]


def reprocess(url: str, pid: str, item_code: str, ai: bool = True, require_ai: bool = True) -> dict:
    """Run the pipeline again on a picture that is already stored (the original is used when R2 still has it).
    Returns the same dict as store_image; the CALLER saves it to the database and then deletes the old picture."""
    data = None
    if is_r2_key(pid) and R2_OK:
        try:
            data = _get(_orig_key(pid))
        except Exception:
            data = None
    if data is None:
        data = download_bytes(url)
    return store_image(data, item_code, ai=ai, require_ai=require_ai)
