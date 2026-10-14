"""Atomic persistence for generic launchpad activity envelopes."""
import json

MAX_EVENTS = 5000


def ingest(conn, payload):
    if not isinstance(payload, dict) or payload.get("version") != 1 or payload.get("complete") is not True:
        raise ValueError("invalid or incomplete launchpad envelope")
    events = payload.get("events")
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("invalid or oversized event list")
    normalized = []
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        source = event.get("source")
        program = event.get("programId")
        signature = event.get("signature")
        if not all(isinstance(x, str) and x for x in (source, program, signature)):
            raise ValueError("event source, programId and signature are required")
        if signature in seen:
            raise ValueError("duplicate signature in envelope")
        seen.add(signature)
        slot = event.get("slot")
        if slot is not None and (not isinstance(slot, int) or slot < 0):
            raise ValueError("invalid event slot")
        normalized.append((source, program, signature, slot, event.get("blockTime"),
                           json.dumps(event.get("err"), separators=(",", ":")),
                           event.get("confirmationStatus"), event.get("capturedAt") or payload.get("capturedAt")))
    conn.execute("BEGIN IMMEDIATE")
    try:
        before = conn.execute("SELECT COUNT(*) FROM launchpad_events").fetchone()[0]
        conn.executemany("""INSERT INTO launchpad_events
            (source, program_id, signature, slot, block_time, err_json,
             confirmation_status, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(signature) DO UPDATE SET
              source=excluded.source, program_id=excluded.program_id,
              slot=excluded.slot, block_time=excluded.block_time,
              err_json=excluded.err_json,
              confirmation_status=excluded.confirmation_status,
              captured_at=excluded.captured_at""", normalized)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    after = conn.execute("SELECT COUNT(*) FROM launchpad_events").fetchone()[0]
    return {"insertedOrUpdated": len(normalized), "newEvents": after - before, "totalEvents": after}


def sources(conn):
    rows = conn.execute("SELECT slug, name, status, evidence, docs_url, updated_at FROM launchpad_sources ORDER BY name").fetchall()
    return [dict(row) for row in rows]


def event_stats(conn):
    rows = conn.execute("""SELECT source, COUNT(*) event_count,
        MAX(slot) latest_slot FROM launchpad_events GROUP BY source ORDER BY source""").fetchall()
    return [dict(row) for row in rows]
