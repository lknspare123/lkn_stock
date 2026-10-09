"""
Run one Google Drive backup from the command line (same code the /cron/backup URL uses).

    python scripts/backup_to_drive.py

Needs DATABASE_URL and the GOOGLE_* variables in the environment. Exit code 0 = OK, 1 = failed.
Handy for a Render "Cron Job" service or a GitHub Actions schedule instead of the URL.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from core import backup  # noqa: E402

result = backup.run_backup("cron")
print(json.dumps(result, ensure_ascii=False, indent=2))
sys.exit(0 if result.get("ok") else 1)
