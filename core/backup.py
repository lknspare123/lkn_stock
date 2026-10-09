"""
core/backup.py — database backup as ONE .db file (SQLite format), uploaded to Google Drive.

Why a SQLite .db file?  It is a single portable file that opens in "DB Browser for SQLite", Python, Excel
importers etc., and the app's Settings page can restore from it.  Every table of the Neon (Postgres) database is
copied in one consistent snapshot, plus a `_meta` table (app version, time, row counts).

Google Drive uses the OAuth *refresh-token* flow with the narrow `drive.file` scope (the app only ever sees the
files / folder it created itself, so there is no Google verification needed).  Only the Python standard library is
used — no new dependencies.

Environment variables
---------------------
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN   (see scripts/get_gdrive_token.py)
GDRIVE_FOLDER_NAME   folder created in My Drive on first use (default "LKN Stock Backups")
GDRIVE_FOLDER_ID     optional: skip the lookup and use this folder id (must have been created by this app)
BACKUP_KEEP          how many backups to keep on Drive (default 30; older ones are deleted)
"""
import json
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from core.neon_db import pool, BACKUP_TABLES
from utils.helpers import now_local

APP_VERSION_FALLBACK = "1.0.5"
FILE_PREFIX = "lkn_stock_backup_"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SQLITE_MAGIC = b"SQLite format 3\x00"

_TYPE_MAP = {"double precision": "REAL", "real": "REAL", "numeric": "REAL",
             "integer": "INTEGER", "bigint": "INTEGER", "smallint": "INTEGER", "boolean": "INTEGER"}
_run_lock = threading.Lock()


class BackupError(Exception):
    """A problem with a user-readable message (shown in Settings and returned to the cron job)."""


# ── backup_log table helpers ────────────────────────────────────────────────
def log_run(trigger, ok, message, file_name="", size_bytes=0, drive_file_id=""):
    with pool.connection() as conn:
        conn.execute(
            """INSERT INTO backup_log (ran_at, trigger, ok, message, file_name, size_bytes, drive_file_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (now_local().strftime("%Y-%m-%d %H:%M:%S"), trigger, bool(ok), (message or "")[:500],
             file_name, int(size_bytes or 0), drive_file_id))
        conn.execute("DELETE FROM backup_log WHERE id NOT IN (SELECT id FROM backup_log ORDER BY id DESC LIMIT 100)")


def recent_runs(limit=10):
    with pool.connection() as conn:
        return conn.execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT %s", (limit,)).fetchall()


def _last_ok_age_seconds():
    with pool.connection() as conn:
        r = conn.execute("SELECT ran_at FROM backup_log WHERE ok ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        return None
    try:
        from datetime import datetime
        last = datetime.strptime(r["ran_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=now_local().tzinfo)
        return (now_local() - last).total_seconds()
    except ValueError:
        return None


# ── SQLite .db file (build + read back) ─────────────────────────────────────
def build_sqlite_backup(path, app_version=APP_VERSION_FALLBACK):
    """Write every table of the Postgres database into a new SQLite file at `path`. Returns {table: rows}."""
    counts = {}
    lite = sqlite3.connect(path)
    try:
        with pool.connection() as conn:
            # one consistent snapshot even if someone is saving an invoice while the backup runs
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            for t in BACKUP_TABLES:
                cols = conn.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position", (t,)).fetchall()
                if not cols:
                    continue
                names = [c["column_name"] for c in cols]
                lite.execute(f'CREATE TABLE "{t}" (' + ", ".join(
                    f'"{c["column_name"]}" {_TYPE_MAP.get(c["data_type"], "TEXT")}' for c in cols) + ")")
                order = " ORDER BY seq" if "seq" in names else ""
                rows = conn.execute(f"SELECT * FROM {t}{order}").fetchall()
                lite.executemany(
                    f'INSERT INTO "{t}" VALUES ({", ".join("?" * len(names))})',
                    [tuple(int(r[n]) if isinstance(r[n], bool) else r[n] for n in names) for r in rows])
                counts[t] = len(rows)
        lite.execute("CREATE TABLE _meta (key TEXT PRIMARY KEY, value TEXT)")
        meta = {"app": "lknstock", "version": app_version, "created": now_local().strftime("%Y-%m-%d %H:%M:%S"),
                "timezone": "Asia/Phnom_Penh (UTC+7)", "rows": json.dumps(counts)}
        lite.executemany("INSERT INTO _meta VALUES (?, ?)", list(meta.items()))
        lite.commit()
    finally:
        lite.close()
    return counts


def make_backup_file(app_version=APP_VERSION_FALLBACK):
    """-> (file_name, bytes, counts). The file name carries the Cambodia date and time."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        counts = build_sqlite_backup(path, app_version)
        with open(path, "rb") as fh:
            raw = fh.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return FILE_PREFIX + now_local().strftime("%Y-%m-%d_%H-%M") + ".db", raw, counts


def read_sqlite_backup(raw):
    """Turn an uploaded .db backup back into {table: [row dicts]} for DB.restore_all()."""
    if not raw.startswith(SQLITE_MAGIC):
        raise ValueError("មិនមែនជាឯកសារ .db ដែលបង្កើតដោយកម្មវិធីនេះទេ។ (not a SQLite backup file)")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        with open(path, "wb") as fh:
            fh.write(raw)
        lite = sqlite3.connect(path)
        lite.row_factory = sqlite3.Row
        have = {r[0] for r in lite.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "items" not in have:
            raise ValueError("ឯកសារ .db នេះមិនមានតារាង items ទេ។ (no 'items' table in this file)")
        with pool.connection() as conn:
            bools = {(r["table_name"], r["column_name"]) for r in conn.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND data_type = 'boolean'")}
        data = {}
        for t in BACKUP_TABLES:
            if t not in have:
                data[t] = []
                continue
            rows = []
            for r in lite.execute(f'SELECT * FROM "{t}"'):
                d = dict(r)
                for k in d:
                    if (t, k) in bools and d[k] is not None:
                        d[k] = bool(d[k])
                rows.append(d)
            data[t] = rows
        lite.close()
        return data
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


# ── Google Drive (stdlib only) ──────────────────────────────────────────────
def drive_configured():
    return all(os.environ.get(k, "").strip() for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"))


def _http(method, url, data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)
    except urllib.error.URLError as e:
        raise BackupError(f"មិនអាចភ្ជាប់ទៅ Google បានទេ (network): {e.reason}")


def _json(status, body, what):
    try:
        j = json.loads(body.decode("utf-8") or "{}")
    except ValueError:
        j = {}
    if status >= 400:
        err = j.get("error")
        msg = (err.get("message") if isinstance(err, dict) else j.get("error_description") or err) or body[:200].decode("utf-8", "replace")
        raise BackupError(f"Google Drive {what} បរាជ័យ ({status}): {msg}")
    return j


def get_access_token():
    if not drive_configured():
        raise BackupError("Google Drive មិនទាន់បានកំណត់ទេ — សូមដាក់ GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN។")
    body = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"].strip(), "client_secret": os.environ["GOOGLE_CLIENT_SECRET"].strip(),
        "refresh_token": os.environ["GOOGLE_REFRESH_TOKEN"].strip(), "grant_type": "refresh_token"}).encode()
    status, raw, _ = _http("POST", TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"}, 30)
    j = {}
    try:
        j = json.loads(raw.decode("utf-8"))
    except ValueError:
        pass
    if status != 200 or "access_token" not in j:
        if j.get("error") == "invalid_grant":
            raise BackupError("Google refresh token ផុតកំណត់ ឬត្រូវបានដកហូត — សូមបង្កើតថ្មីដោយ scripts/get_gdrive_token.py "
                              "(ប្រសិនបើ OAuth consent screen នៅជា «Testing» token ផុតក្នុង ៧ ថ្ងៃ — សូមចុច Publish app)។")
        raise BackupError(f"មិនអាចយក access token ពី Google បានទេ ({status}): {j.get('error_description') or j.get('error') or raw[:150]}")
    return j["access_token"]


def _auth(token, extra=None):
    h = {"Authorization": "Bearer " + token}
    h.update(extra or {})
    return h


def _quote(s):
    return s.replace("\\", "\\\\").replace("'", "\\'")


def get_folder_id(token):
    fixed = os.environ.get("GDRIVE_FOLDER_ID", "").strip()
    if fixed:
        return fixed
    name = os.environ.get("GDRIVE_FOLDER_NAME", "").strip() or "LKN Stock Backups"
    q = f"mimeType = 'application/vnd.google-apps.folder' and name = '{_quote(name)}' and trashed = false"
    status, raw, _ = _http("GET", f"{DRIVE_API}/files?" + urllib.parse.urlencode({"q": q, "fields": "files(id,name)", "pageSize": 1}),
                           headers=_auth(token))
    files = _json(status, raw, "folder lookup").get("files", [])
    if files:
        return files[0]["id"]
    status, raw, _ = _http("POST", f"{DRIVE_API}/files?fields=id", json.dumps(
        {"name": name, "mimeType": "application/vnd.google-apps.folder"}).encode(), _auth(token, {"Content-Type": "application/json"}))
    return _json(status, raw, "folder create")["id"]


def upload_file(token, folder_id, name, raw):
    """Resumable upload (works for any size). Returns the Drive file id."""
    meta = json.dumps({"name": name, "parents": [folder_id]}).encode()
    status, body, hdr = _http("POST", f"{DRIVE_UPLOAD}?uploadType=resumable&fields=id", meta, _auth(token, {
        "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "application/octet-stream",
        "X-Upload-Content-Length": str(len(raw))}))
    _json(status, body, "upload start")
    loc = next((v for k, v in hdr.items() if k.lower() == "location"), None)
    if not loc:
        raise BackupError("Google Drive មិនបានផ្តល់ទីតាំង upload ទេ។")
    status, body, _ = _http("PUT", loc, raw, {"Content-Type": "application/octet-stream", "Content-Length": str(len(raw))}, 300)
    return _json(status, body, "upload").get("id", "")


def prune_old(token, folder_id, keep):
    """Delete the oldest backups beyond `keep` (only files this app created, named lkn_stock_backup_*)."""
    q = f"'{folder_id}' in parents and trashed = false and name contains '{FILE_PREFIX}'"
    status, raw, _ = _http("GET", f"{DRIVE_API}/files?" + urllib.parse.urlencode(
        {"q": q, "fields": "files(id,name,createdTime)", "orderBy": "createdTime desc", "pageSize": 200}), headers=_auth(token))
    files = _json(status, raw, "list").get("files", [])
    removed = 0
    for f in files[keep:]:
        s, _, _ = _http("DELETE", f"{DRIVE_API}/files/{f['id']}", headers=_auth(token))
        removed += 1 if s in (200, 204) else 0
    return removed


# ── The one entry point (cron job, Settings button and CLI all call this) ────
def run_backup(trigger="manual", app_version=APP_VERSION_FALLBACK):
    """Build the .db file and upload it to Google Drive. Never raises: returns a result dict and logs it."""
    if trigger == "cron":                     # a double-fired cron request must not make two copies
        age = _last_ok_age_seconds()
        if age is not None and age < 300:
            return {"ok": True, "skipped": True, "message": "បានបម្រុងទុកក្នុង ៥ នាទីចុងក្រោយរួចហើយ — រំលង។"}
    if not _run_lock.acquire(blocking=False):
        return {"ok": False, "error": "កំពុងបម្រុងទុកទិន្នន័យ — សូមរង់ចាំ។"}
    name, size, file_id = "", 0, ""
    try:
        started = time.time()
        raw_name, raw, counts = make_backup_file(app_version)
        name, size = raw_name, len(raw)
        token = get_access_token()
        folder = get_folder_id(token)
        file_id = upload_file(token, folder, name, raw)
        keep = max(int(os.environ.get("BACKUP_KEEP", 30) or 30), 1)
        removed = prune_old(token, folder, keep)
        msg = f"{counts.get('items', 0)} ទំនិញ · {counts.get('invoice_records', 0)} វិក្កយបត្រលក់ · " \
              f"{counts.get('purchase_invoices', 0)} ទទួលស្តុក · {counts.get('transfers', 0)} ផ្ទេរ" + \
              (f" · លុបចាស់ {removed}" if removed else "")
        log_run(trigger, True, msg, name, size, file_id)
        return {"ok": True, "file": name, "size": size, "drive_file_id": file_id, "seconds": round(time.time() - started, 1),
                "deleted_old": removed, "message": msg}
    except BackupError as e:
        log_run(trigger, False, str(e), name, size)
        return {"ok": False, "error": str(e)}
    except Exception as e:    # database / unexpected
        log_run(trigger, False, f"{type(e).__name__}: {e}", name, size)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        _run_lock.release()
