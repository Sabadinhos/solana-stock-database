"""Create a verified SQLite backup with safe retention and free-space guards."""
import os
import shutil
import sqlite3
import time

import db

KEEP = int(os.environ.get("BACKUP_KEEP", "3"))
MIN_FREE_PCT = float(os.environ.get("BACKUP_MIN_FREE_PCT", "10"))
TEMP_MAX_AGE = int(os.environ.get("BACKUP_TEMP_MAX_AGE", str(24 * 60 * 60)))


def _integrity_check(path):
    with sqlite3.connect(path, timeout=30) as con:
        result = con.execute("PRAGMA quick_check(1)").fetchone()[0]
    if result != "ok":
        raise RuntimeError(f"backup integrity check failed: {result}")


def _copy_database(src, dst):
    with sqlite3.connect(src, timeout=60) as con, sqlite3.connect(dst) as target:
        target.execute("PRAGMA journal_mode=OFF")
        target.execute("PRAGMA synchronous=OFF")
        con.backup(target, pages=128, sleep=0.05)
        target.commit()


def _free_pct(path):
    usage = shutil.disk_usage(path)
    return (usage.free / usage.total) * 100 if usage.total else 0


def _remove_stale_temps(bdir, now=None):
    now = time.time() if now is None else now
    removed = []
    for name in os.listdir(bdir):
        if not name.startswith(".sdb-") or ".db.tmp" not in name:
            continue
        path = os.path.join(bdir, name)
        try:
            age = now - os.path.getmtime(path)
            if age >= TEMP_MAX_AGE:
                os.remove(path)
                removed.append(path)
        except FileNotFoundError:
            continue
    return removed


def _retained_backups(bdir):
    return sorted(
        (os.path.join(bdir, name) for name in os.listdir(bdir)
         if name.startswith("sdb-") and name.endswith(".db")
         and os.path.isfile(os.path.join(bdir, name))),
        key=os.path.getmtime,
        reverse=True,
    )


def backup():
    src = db.DB_PATH
    bdir = os.path.join(db.DATA_DIR, "backups")
    os.makedirs(bdir, exist_ok=True)
    _remove_stale_temps(bdir)
    free_pct = _free_pct(bdir)
    if free_pct < MIN_FREE_PCT:
        raise RuntimeError(f"backup skipped: only {free_pct:.1f}% disk free")

    ts = time.strftime("%Y%m%d-%H%M%S")
    tmp = os.path.join(bdir, f".sdb-{ts}.db.tmp")
    dst = os.path.join(bdir, f"sdb-{ts}.db")
    try:
        _copy_database(src, tmp)
        _integrity_check(tmp)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    files = _retained_backups(bdir)
    for old in files[KEEP:]:
        os.remove(old)
    _remove_stale_temps(bdir)
    return dst, os.path.getsize(dst), free_pct


if __name__ == "__main__":
    path, size, free_pct = backup()
    print(f"backup ok: {path} ({size} bytes), disk free {free_pct:.1f}%")
    if free_pct < 20:
        print("WARNING: disk free below 20%")
