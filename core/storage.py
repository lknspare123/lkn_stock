"""core/storage.py — Cloudinary image storage (replaces local assets/images/items)."""
import re
import uuid
import os

# ── Sanitise CLOUDINARY_URL BEFORE the cloudinary library reads it ──────────
# A malformed value would otherwise crash the whole app at import time.
_raw = os.environ.get("CLOUDINARY_URL", "").strip().strip("\"'").strip()
if _raw.upper().startswith("CLOUDINARY_URL="):
    _raw = _raw.split("=", 1)[1].strip().strip("\"'").strip()
if _raw and "://" not in _raw and "@" in _raw:      # scheme missing -> add it
    _raw = "cloudinary://" + _raw
CLOUDINARY_OK = bool(re.match(r"^cloudinary://[^:/\s]+:[^@\s]+@[^\s/]+$", _raw))
if CLOUDINARY_OK:
    os.environ["CLOUDINARY_URL"] = _raw
else:
    os.environ.pop("CLOUDINARY_URL", None)          # let the app boot anyway
    print(f"[storage] WARNING: CLOUDINARY_URL is missing/invalid (starts with {_raw[:8]!r}, "
          f"length {len(_raw)}). Expected: cloudinary://API_KEY:API_SECRET@CLOUD_NAME. "
          "Image uploads are disabled until it is fixed.", flush=True)

import cloudinary  # noqa: E402
import cloudinary.uploader  # noqa: E402

cloudinary.config(secure=True)

FOLDER = "lknstock/items"


def _public_id(item_code: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", item_code or "").strip("_")
    return safe or uuid.uuid4().hex[:10]


def upload_item_image(file_or_path, item_code: str):
    """Upload an image; returns (secure_url, public_id)."""
    if not CLOUDINARY_OK:
        raise ValueError("Image storage is not configured: fix the CLOUDINARY_URL environment variable on Render.")
    res = cloudinary.uploader.upload(
        file_or_path,
        folder=FOLDER,
        public_id=_public_id(item_code),
        overwrite=True,
        invalidate=True,
        resource_type="image",
        transformation=[{"width": 900, "height": 900, "crop": "limit",
                         "quality": "auto", "fetch_format": "auto"}],
    )
    return res["secure_url"], res["public_id"]


def delete_image(public_id: str):
    if not public_id or not CLOUDINARY_OK:
        return
    try:
        cloudinary.uploader.destroy(public_id, invalidate=True)
    except Exception:
        pass


def thumb(url: str, size=80) -> str:
    """Insert a Cloudinary resize transform into a delivery URL."""
    if url and "/upload/" in url:
        return url.replace("/upload/", f"/upload/c_fill,w_{size},h_{size},q_auto,f_auto/", 1)
    return url or ""
