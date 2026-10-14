"""SDB scheduler: incremental ingestion with durable operational heartbeat."""
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("SDB_DATA_DIR", os.path.join(HERE, "data"))
HEARTBEAT_FILE = os.path.join(DATA_DIR, "heartbeat.json")
SCAN = os.path.join(HERE, "ingestor", "scan.py")
INGEST = os.path.join(HERE, "ingest.py")
ONCHAIN = os.path.join(HERE, "onchain.py")
REPORT = os.path.join(HERE, "report.py")
DISK_CHECK = os.path.join(HERE, "disk_check.sh")
BACKUP = os.path.join(HERE, "backup.py")
PYTH = os.path.join(HERE, "pyth.py")
DBC_COLLECT = os.path.join(HERE, "dbc_collect.py")


def rpc_today():
    """Today's RPC totals from data/rpc-stats.json, without secrets."""
    try:
        with open(os.path.join(DATA_DIR, "rpc-stats.json"), encoding="utf-8") as f:
            day = json.load(f).get("days", {}).get(time.strftime("%Y-%m-%d", time.gmtime()), {})
    except (OSError, ValueError):
        return None
    return {"calls": sum(v.get("calls", 0) for v in day.values()),
            "credits": sum(v.get("credits", 0) for v in day.values())}


def write_heartbeat(cycle, elapsed, status, error=None, steps=None):
    os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
    payload = {
        "lastCycle": cycle,
        "lastCycleElapsed": round(elapsed, 1),
        "lastAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ts": time.time(),
        "status": status,
        "error": error,
        "steps": steps or {},
        "rpcToday": rpc_today(),
    }
    directory = os.path.dirname(HEARTBEAT_FILE)
    fd, tmp = tempfile.mkstemp(prefix=".heartbeat-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, HEARTBEAT_FILE)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def run(path):
    name = os.path.basename(path)
    if not os.path.exists(path):
        print(f"[scheduler] {name} not present, skipped", flush=True)
        return 0
    print(f"[scheduler] {name} ...", flush=True)
    started = time.time()
    command = ["bash", path] if path.endswith(".sh") else [sys.executable, path]
    timeout = int(os.environ.get("SDB_STEP_TIMEOUT_SEC", "1800"))
    if name == "scan.py":
        timeout = int(os.environ.get("SDB_SCAN_TIMEOUT_SEC", str(timeout)))
    try:
        result = subprocess.run(command, cwd=HERE, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or exc.stderr or "").strip().splitlines()
        for line in output[-3:]:
            print(f"    {line}", flush=True)
        print(f"[scheduler] {name} timed out after {timeout}s", flush=True)
        return 124
    output = (result.stdout or result.stderr or "").strip().splitlines()
    for line in output[-3:]:
        print(f"    {line}", flush=True)
    elapsed = time.time() - started
    print(f"[scheduler] {name} finished ({elapsed:.0f}s, rc={result.returncode})", flush=True)
    return result.returncode


def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 15 * 60
    print(f"[scheduler] SDB ingestor: cycle every {interval}s.", flush=True)
    cycle = 0
    while True:
        cycle += 1
        started = time.time()
        steps = {}
        errors = []
        write_heartbeat(cycle, 0, "running", None, steps)
        try:
            steps["scan"] = run(SCAN)
            if steps["scan"] != 0:
                errors.append(f"scan rc={steps['scan']}")
            write_heartbeat(cycle, time.time() - started, "running", "; ".join(errors) if errors else None, steps)
            steps["ingest"] = run(INGEST)
            if steps["ingest"] != 0:
                errors.append(f"ingest rc={steps['ingest']}")
            try:
                steps["pyth"] = run(PYTH)
            except Exception as exc:
                steps["pyth"] = 0
                print(f"[scheduler] pyth unavailable: {type(exc).__name__}", flush=True)
            write_heartbeat(cycle, time.time() - started, "running", "; ".join(errors) if errors else None, steps)
            if cycle % 6 == 0:
                steps["onchain"] = run(ONCHAIN)
                if steps["onchain"] != 0:
                    errors.append(f"onchain rc={steps['onchain']}")
                steps["disk"] = run(DISK_CHECK)
                if steps["disk"] != 0:
                    errors.append(f"disk rc={steps['disk']}")
                if steps["disk"] == 0:
                    steps["backup"] = run(BACKUP)
                    if steps["backup"] != 0:
                        errors.append(f"backup rc={steps['backup']}")
                else:
                    steps["backup"] = -1
                    errors.append("backup skipped because disk check failed")
            dbc_enabled = os.environ.get("DBC_ENABLED", "1").lower() not in ("0", "false", "no")
            dbc_every = max(1, int(os.environ.get("DBC_EVERY_CYCLES", "6")))
            if dbc_enabled and cycle % dbc_every == 0:
                steps["dbc"] = run(DBC_COLLECT)
                if steps["dbc"] != 0:
                    errors.append(f"dbc rc={steps['dbc']}")
            steps["report"] = run(REPORT)
            if steps["report"] != 0:
                errors.append(f"report rc={steps['report']}")
        except Exception as exc:
            errors.append(f"scheduler exception: {type(exc).__name__}: {exc}")
        elapsed = time.time() - started
        status = "ok" if not errors else "degraded"
        write_heartbeat(cycle, elapsed, status, "; ".join(errors) if errors else None, steps)
        nap = max(60, interval - elapsed)
        print(f"[scheduler] cycle completed in {elapsed:.0f}s, next in {nap:.0f}s ({status})", flush=True)
        time.sleep(nap)


if __name__ == "__main__":
    main()
