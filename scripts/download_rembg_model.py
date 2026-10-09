"""
Only for BG_REMOVER=rembg: download the rembg model file ONCE so the first picture is not slow.

    python scripts/download_rembg_model.py            # uses REMBG_MODEL (default u2netp) and U2NET_HOME
    python scripts/download_rembg_model.py u2netp     # or name the model

Does nothing when BG_REMOVER is not rembg.
"""
import os
import sys

on = os.environ.get("BG_REMOVER", "").strip().lower() in ("rembg", "1", "true", "yes", "on")
if not on and len(sys.argv) < 2:
    print("BG_REMOVER is not rembg - model download skipped.")
    sys.exit(0)
name = sys.argv[1] if len(sys.argv) > 1 else (os.environ.get("REMBG_MODEL", "").strip() or "u2netp")
try:
    from rembg import new_session
    new_session(name)
    print(f"rembg model '{name}' is ready in {os.environ.get('U2NET_HOME', '~/.u2net')}")
except Exception as e:           # never break the deployment because of this
    print(f"Could not download the model now ({type(e).__name__}: {e}); it will be downloaded on first use instead.")
