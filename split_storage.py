"""Create independent SQLite copies for the SDB storage migration."""
import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import db

CORE_TABLES = ("tokens", "rewards", "launches", "cycles", "verified_creators", "terminal_prices", "asset_feeds", "asset_prices", "api_keys")
ONCHAIN_TABLES = ("holders", "token_events", "pools", "burns")
HISTORY_TABLES = ("snapshots", "distributions")


def _schema(source, table):
    row = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"missing table schema: {table}")
    return row[0]


def _copy_table(source, target, table, batch_size=2000):
    target.execute(_schema(source, table))
    indexes = source.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)).fetchall()
    columns = [r[1] for r in source.execute(f'PRAGMA table_info("{table}")')]
    quoted = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join("?" for _ in columns)
    rows = source.execute(f'SELECT {quoted} FROM "{table}"')
    while True:
        batch = rows.fetchmany(batch_size)
        if not batch:
            break
        target.executemany(f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})', batch)
    for (sql,) in indexes:
        target.execute(sql)
    target.commit()
    return target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def _copy_group(source, path, tables):
    if path.exists():
        path.unlink()
    target = sqlite3.connect(path)
    target.execute("PRAGMA journal_mode=OFF")
    counts = {}
    for table in tables:
        if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            counts[table] = _copy_table(source, target, table)
    result = target.execute("PRAGMA quick_check(1)").fetchone()[0]
    if result != "ok":
        target.close()
        raise RuntimeError(f"quick_check failed for {path}: {result}")
    target.close()
    return counts


def _sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def migrate(source_path, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    history_dir = output_dir / "history"
    history_dir.mkdir(exist_ok=True)
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    core_counts = _copy_group(source, output_dir / "core.db", CORE_TABLES)
    onchain_counts = _copy_group(source, output_dir / "onchain.db", ONCHAIN_TABLES)
    month = time.strftime("%Y-%m")
    history_counts = _copy_group(source, history_dir / f"history-{month}.db", HISTORY_TABLES)
    source_counts = {table: source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in CORE_TABLES + ONCHAIN_TABLES + HISTORY_TABLES if source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()}
    source.close()
    manifest = {
        "source": str(source_path),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sourceCounts": source_counts,
        "coreCounts": core_counts,
        "onchainCounts": onchain_counts,
        "historyCounts": history_counts,
        "files": [],
    }
    for path in [output_dir / "core.db", output_dir / "onchain.db", history_dir / f"history-{month}.db"]:
        manifest["files"].append({"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)})
    (output_dir / "split-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=db.DB_PATH)
    parser.add_argument("--output", default=os.path.join(db.DATA_DIR, "split-staging"))
    args = parser.parse_args()
    result = migrate(Path(args.source), Path(args.output))
    print(json.dumps(result, indent=2))
