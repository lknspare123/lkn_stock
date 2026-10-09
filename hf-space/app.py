"""LKN Stock background remover - runs on a free Hugging Face Space (Docker).

POST /remove   multipart form, field "image" (a JPG/PNG/WEBP), header  X-API-Token: <your secret>
               -> answers a PNG with a transparent background (the product is only cut out, never redrawn)
GET  /health   -> {"ok": true, ...}   (no password; also wakes the Space up when it is sleeping)

Space settings:
    Secret    API_TOKEN     a long random text; the same value goes to Render as HF_API_TOKEN  (REQUIRED)
    Variable  REMBG_MODEL   u2net (default) | u2netp (faster) | isnet-general-use (best edges, slower) | silueta
"""
import hmac
import io
import os
import threading

from flask import Flask, jsonify, request, send_file
from PIL import Image, ImageOps

MODEL = (os.environ.get("REMBG_MODEL") or "u2net").strip()
TOKEN = (os.environ.get("API_TOKEN") or "").strip()
MAX_BYTES = 15 * 1024 * 1024
MAX_SIDE = 1280

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BYTES + 1024 * 1024

_state = {"session": None, "remove": None, "error": ""}
_gate = threading.Semaphore(2)          # at most 2 pictures at once (the free Space has 2 CPU cores)


def _load():
    try:
        from rembg import new_session, remove
        _state["session"] = new_session(MODEL)
        _state["remove"] = remove
        print(f"[space] model '{MODEL}' is ready", flush=True)
    except Exception as e:               # keep the server up so /health can show the reason
        _state["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        print(f"[space] could not load the model: {_state['error']}", flush=True)


_load()


@app.get("/")
@app.get("/health")
def health():
    return jsonify(ok=_state["session"] is not None, model=MODEL, token_set=bool(TOKEN), error=_state["error"])


@app.post("/remove")
def remove_bg():
    if not TOKEN:
        return jsonify(error="API_TOKEN secret is not set in this Space (Settings -> Variables and secrets)."), 503
    if not hmac.compare_digest(request.headers.get("X-API-Token", ""), TOKEN):
        return jsonify(error="wrong or missing X-API-Token"), 401
    if _state["session"] is None:
        return jsonify(error="model not loaded: " + (_state["error"] or "still starting")), 503
    f = request.files.get("image")
    data = f.read() if f else b""
    if not data:
        return jsonify(error='send the picture as a form field named "image"'), 400
    if len(data) > MAX_BYTES:
        return jsonify(error="picture too large (limit 15 MB)"), 413
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception:
        return jsonify(error="this file is not a picture"), 400
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    try:
        with _gate:
            out = _state["remove"](img, session=_state["session"], post_process_mask=True)
    except Exception as e:
        return jsonify(error=f"rembg failed: {type(e).__name__}: {str(e)[:150]}"), 500
    buf = io.BytesIO()
    out.convert("RGBA").save(buf, "PNG", compress_level=3)
    buf.seek(0)
    return send_file(buf, mimetype="image/png")
