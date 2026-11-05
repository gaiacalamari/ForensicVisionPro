"""Audit log a catena di hash (append-only).

Ogni voce include l'hash della precedente: qualsiasi modifica, inserimento o
cancellazione di una voce rompe la catena ed è rilevata da verify().
I trigger SQLite impediscono UPDATE/DELETE dall'applicazione; chi ha accesso
diretto al file potrebbe rimuoverli, ma l'alterazione resterebbe rilevabile.
L'hash di testa va riportato nei report come ancora esterna.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

GENESIS = "0" * 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'audit',
    details TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log è append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log è append-only'); END;
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _entry_hash(seq: int, ts: str, actor: str, action: str, kind: str, details: str, prev: str) -> str:
    payload = json.dumps([seq, ts, actor, action, kind, details, prev], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class VerifyResult:
    ok: bool
    entries: int
    head: str
    broken_at: int | None = None
    reason: str = ""


class AuditLog:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        conn.executescript(SCHEMA)

    def append(self, actor: str, action: str, details: dict | None = None, kind: str = "audit") -> str:
        details_s = json.dumps(details or {}, ensure_ascii=False, sort_keys=True, default=str)
        with self.conn:
            row = self.conn.execute("SELECT seq, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
            seq = (row[0] + 1) if row else 1
            prev = row[1] if row else GENESIS
            ts = utc_now()
            h = _entry_hash(seq, ts, actor, action, kind, details_s, prev)
            self.conn.execute("INSERT INTO audit_log VALUES (?,?,?,?,?,?,?,?)",
                              (seq, ts, actor, action, kind, details_s, prev, h))
        return h

    def entries(self, kind: str | None = None) -> list[dict]:
        q = "SELECT seq, ts_utc, actor, action, kind, details, prev_hash, entry_hash FROM audit_log"
        args: tuple = ()
        if kind:
            q += " WHERE kind = ?"
            args = (kind,)
        rows = self.conn.execute(q + " ORDER BY seq", args).fetchall()
        keys = ["seq", "ts_utc", "actor", "action", "kind", "details", "prev_hash", "entry_hash"]
        out = []
        for r in rows:
            d = dict(zip(keys, r))
            d["details"] = json.loads(d["details"])
            out.append(d)
        return out

    def verify(self) -> VerifyResult:
        rows = self.conn.execute(
            "SELECT seq, ts_utc, actor, action, kind, details, prev_hash, entry_hash FROM audit_log ORDER BY seq").fetchall()
        prev = GENESIS
        expected_seq = 1
        for seq, ts, actor, action, kind, details, prev_h, h in rows:
            if seq != expected_seq:
                return VerifyResult(False, len(rows), prev, seq, f"sequenza interrotta: atteso {expected_seq}, trovato {seq}")
            if prev_h != prev:
                return VerifyResult(False, len(rows), prev, seq, "collegamento con la voce precedente non valido")
            if _entry_hash(seq, ts, actor, action, kind, details, prev_h) != h:
                return VerifyResult(False, len(rows), prev, seq, "contenuto della voce alterato")
            prev = h
            expected_seq += 1
        return VerifyResult(True, len(rows), prev)
