"""Case Management, acquisizione dei reperti e catena di custodia.

Struttura di un caso su disco:
    <cases_dir>/<case_id>/case.db           database SQLite del caso
    <cases_dir>/<case_id>/evidence/<EXH>/   copia di lavoro in sola lettura
    <cases_dir>/<case_id>/artifacts/        prodotti dell'analisi (heatmap, ...)
    <cases_dir>/<case_id>/reports/          report generati

Il file originale viene solo letto: mai aperto in scrittura, mai rinominato.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import __version__
from ..core.audit import AuditLog, utc_now
from ..core.findings import Finding
from ..core.tasks import CancelToken, ProgressFn, noop_progress
from ..engines.hashing import ALGORITHMS, CHUNK, hash_file

SCHEMA = """
CREATE TABLE IF NOT EXISTS case_info (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS exhibits (
    id TEXT PRIMARY KEY, label TEXT, source_path TEXT, original_name TEXT, size INTEGER,
    acquired_utc TEXT, operator TEXT, source_hashes TEXT, working_path TEXT,
    working_hashes TEXT, source_stat TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, exhibit_id TEXT, started_utc TEXT, finished_utc TEXT,
    operator TEXT, modules TEXT, findings TEXT, results TEXT, pre_hashes TEXT, post_hashes TEXT,
    integrity_ok INTEGER, tools TEXT, app_version TEXT
);
CREATE TABLE IF NOT EXISTS operator_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, exhibit_id TEXT, ts_utc TEXT, operator TEXT, text TEXT
);
"""

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class CaseError(RuntimeError):
    pass


def safe_name(s: str) -> str:
    s = _SAFE.sub("_", s).strip("._")
    return s[:120] or "item"


def _stat_dict(p: Path) -> dict:
    st = p.stat()
    def iso(t: float) -> str:
        return datetime.fromtimestamp(t, timezone.utc).isoformat()
    d = {"size": st.st_size, "mtime_utc": iso(st.st_mtime), "atime_utc": iso(st.st_atime),
         "ctime_utc": iso(st.st_ctime),
         "ctime_meaning": "creazione (Windows)" if os.name == "nt" else "cambio inode/metadati (POSIX)"}
    birth = getattr(st, "st_birthtime", None)
    if birth:
        d["birthtime_utc"] = iso(birth)
    return d


@dataclass
class Exhibit:
    id: str
    label: str
    source_path: str
    original_name: str
    size: int
    acquired_utc: str
    operator: str
    source_hashes: dict
    working_path: str
    working_hashes: dict
    source_stat: dict
    notes: str = ""


class Case:
    def __init__(self, root: Path):
        self.root = Path(root)
        db = self.root / "case.db"
        if not db.exists():
            raise CaseError(f"Nessun caso in {root}")
        self.conn = sqlite3.connect(db, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        self.audit = AuditLog(self.conn)

    # ---------- creazione / apertura ----------
    @classmethod
    def create(cls, cases_dir: Path, case_id: str, title: str, operator: str, description: str = "") -> "Case":
        if not case_id.strip() or not operator.strip():
            raise CaseError("Case ID e operatore sono obbligatori")
        root = Path(cases_dir) / safe_name(case_id)
        if (root / "case.db").exists():
            raise CaseError(f"Il caso {case_id} esiste già")
        for sub in ("evidence", "artifacts", "reports"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(root / "case.db")
        conn.executescript(SCHEMA)
        with conn:
            for k, v in {"case_id": case_id, "title": title, "description": description, "operator": operator,
                         "opened_utc": utc_now(), "app_version": __version__}.items():
                conn.execute("INSERT INTO case_info VALUES (?,?)", (k, v))
        conn.close()
        case = cls(root)
        case.audit.append(operator, "caso_creato", {"case_id": case_id, "title": title}, kind="custody")
        return case

    @classmethod
    def open(cls, root: Path, operator: str = "") -> "Case":
        c = cls(root)
        c.audit.append(operator or c.info.get("operator", ""), "caso_aperto", {"path": str(root)})
        return c

    @staticmethod
    def list_cases(cases_dir: Path) -> list[dict]:
        out = []
        if not Path(cases_dir).is_dir():
            return out
        for d in sorted(Path(cases_dir).iterdir()):
            db = d / "case.db"
            if db.is_file():
                try:
                    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                    info = dict(conn.execute("SELECT key, value FROM case_info").fetchall())
                    n_ex = conn.execute("SELECT COUNT(*) FROM exhibits").fetchone()[0]
                    n_an = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
                    findings = conn.execute("SELECT findings FROM analyses").fetchall()
                    conn.close()
                    n_anom = sum(sum(1 for f in json.loads(r[0] or "[]")
                                     if f["level"] in ("evidenza_certa", "anomalia_tecnica", "indicatore_sospetto"))
                                 for r in findings)
                    out.append({**info, "path": str(d), "exhibits": n_ex, "analyses": n_an, "anomalies": n_anom})
                except sqlite3.Error:
                    continue
        return out

    @property
    def info(self) -> dict:
        return dict(self.conn.execute("SELECT key, value FROM case_info").fetchall())

    def close(self) -> None:
        self.conn.close()

    # ---------- reperti ----------
    def _next_exhibit_id(self) -> str:
        n = self.conn.execute("SELECT COUNT(*) FROM exhibits").fetchone()[0]
        return f"EXH-{n + 1:04d}"

    def acquire(self, source: str | Path, operator: str, label: str = "", algorithms=tuple(ALGORITHMS),
                progress: ProgressFn = noop_progress, cancel: CancelToken | None = None) -> Exhibit:
        """Acquisisce un file: stat dell'originale, copia con hash in un solo passaggio,
        verifica della copia con una seconda lettura indipendente, copia resa read-only."""
        src = Path(source)
        if not src.is_file():
            raise CaseError(f"Il reperto non è un file leggibile: {src}")
        src_stat = _stat_dict(src)       # prima della lettura: la lettura può aggiornare l'atime
        ex_id = self._next_exhibit_id()
        dest_dir = self.root / "evidence" / ex_id
        dest_dir.mkdir(parents=True, exist_ok=False)
        dest = dest_dir / safe_name(src.name)
        hs = {a: hashlib.new(a) for a in algorithms}
        size, done = src_stat["size"] or 1, 0
        try:
            with open(src, "rb") as fi, open(dest, "xb") as fo:
                while True:
                    if cancel:
                        cancel.check()
                    buf = fi.read(CHUNK)
                    if not buf:
                        break
                    for h in hs.values():
                        h.update(buf)
                    fo.write(buf)
                    done += len(buf)
                    progress(0.5 * done / size, "Copia del reperto")
                fo.flush()
                os.fsync(fo.fileno())
        except BaseException:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise
        src_h = {a: h.hexdigest() for a, h in hs.items()}
        work_h = hash_file(dest, algorithms, lambda p, m: progress(0.5 + 0.5 * p, "Verifica della copia"), cancel)
        os.chmod(dest, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        if src_h != work_h:
            self.audit.append(operator, "acquisizione_fallita", {"exhibit": ex_id, "source": str(src),
                                                                   "source_hashes": src_h, "copy_hashes": work_h},
                              kind="custody")
            raise CaseError("La copia di lavoro non corrisponde all'originale: acquisizione non valida")
        ex = Exhibit(ex_id, label or src.name, str(src.resolve()), src.name, src_stat["size"], utc_now(), operator,
                     src_h, str(dest), work_h, src_stat)
        with self.conn:
            self.conn.execute("INSERT INTO exhibits VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                              (ex.id, ex.label, ex.source_path, ex.original_name, ex.size, ex.acquired_utc,
                               ex.operator, json.dumps(src_h), ex.working_path, json.dumps(work_h),
                               json.dumps(src_stat), ""))
        self.audit.append(operator, "acquisizione", {"exhibit": ex_id, "source": ex.source_path, "size": ex.size,
                                                     "hashes": src_h, "working_copy": str(dest),
                                                     "source_stat": src_stat}, kind="custody")
        return ex

    def exhibits(self) -> list[Exhibit]:
        rows = self.conn.execute("SELECT * FROM exhibits ORDER BY id").fetchall()
        return [self._row_to_ex(r) for r in rows]

    def exhibit(self, ex_id: str) -> Exhibit:
        r = self.conn.execute("SELECT * FROM exhibits WHERE id = ?", (ex_id,)).fetchone()
        if not r:
            raise CaseError(f"Reperto {ex_id} non trovato")
        return self._row_to_ex(r)

    @staticmethod
    def _row_to_ex(r) -> Exhibit:
        return Exhibit(r[0], r[1], r[2], r[3], r[4], r[5], r[6], json.loads(r[7]), r[8], json.loads(r[9]),
                       json.loads(r[10]), r[11] or "")

    def verify_exhibit(self, ex_id: str, operator: str, check_source: bool = False) -> dict:
        ex = self.exhibit(ex_id)
        algs = list(ex.working_hashes)
        res: dict = {"exhibit": ex_id, "working_copy_ok": False, "source_checked": False}
        try:
            cur = hash_file(ex.working_path, algs)
            res["working_copy_hashes"] = cur
            res["working_copy_ok"] = cur == ex.working_hashes
        except OSError as e:
            res["error"] = str(e)
        if check_source and Path(ex.source_path).is_file():
            res["source_checked"] = True
            res["source_hashes"] = hash_file(ex.source_path, algs)
            res["source_ok"] = res["source_hashes"] == ex.source_hashes
        self.audit.append(operator, "verifica_integrita", res, kind="custody")
        return res

    def record_custody(self, operator: str, action: str, details: dict) -> None:
        """Eventi manuali di custodia (trasferimento, consegna, sigillatura...)."""
        self.audit.append(operator, action, details, kind="custody")

    # ---------- analisi ----------
    def save_analysis(self, ex_id: str, operator: str, started: str, modules: list[str], findings: list[Finding],
                      results: dict, pre: dict, post: dict, tools: dict) -> int:
        ok = int(pre == post)
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO analyses (exhibit_id, started_utc, finished_utc, operator, modules, findings, results,"
                " pre_hashes, post_hashes, integrity_ok, tools, app_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (ex_id, started, utc_now(), operator, json.dumps(modules),
                 json.dumps([f.to_dict() for f in findings], ensure_ascii=False),
                 json.dumps(results, ensure_ascii=False, default=str), json.dumps(pre), json.dumps(post), ok,
                 json.dumps(tools), __version__))
        aid = cur.lastrowid
        self.audit.append(operator, "analisi_completata", {"exhibit": ex_id, "analysis_id": aid, "modules": modules,
                                                           "findings": len(findings), "integrity_ok": bool(ok)})
        return aid

    def analyses(self, ex_id: str | None = None) -> list[dict]:
        q = "SELECT id, exhibit_id, started_utc, finished_utc, operator, modules, findings, results, pre_hashes," \
            " post_hashes, integrity_ok, tools, app_version FROM analyses"
        args: tuple = ()
        if ex_id:
            q += " WHERE exhibit_id = ?"
            args = (ex_id,)
        out = []
        for r in self.conn.execute(q + " ORDER BY id", args).fetchall():
            out.append({"id": r[0], "exhibit_id": r[1], "started_utc": r[2], "finished_utc": r[3], "operator": r[4],
                        "modules": json.loads(r[5]), "findings": [Finding.from_dict(f) for f in json.loads(r[6])],
                        "results": json.loads(r[7]), "pre_hashes": json.loads(r[8]), "post_hashes": json.loads(r[9]),
                        "integrity_ok": bool(r[10]), "tools": json.loads(r[11]), "app_version": r[12]})
        return out

    def add_note(self, ex_id: str, operator: str, text: str) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO operator_notes (exhibit_id, ts_utc, operator, text) VALUES (?,?,?,?)",
                              (ex_id, utc_now(), operator, text))
        self.audit.append(operator, "nota_operatore", {"exhibit": ex_id, "sha256": hashlib.sha256(text.encode()).hexdigest()})

    def notes(self, ex_id: str | None = None) -> list[dict]:
        q = "SELECT exhibit_id, ts_utc, operator, text FROM operator_notes"
        rows = self.conn.execute(q + (" WHERE exhibit_id = ?" if ex_id else "") + " ORDER BY id",
                                 (ex_id,) if ex_id else ()).fetchall()
        return [dict(zip(["exhibit_id", "ts_utc", "operator", "text"], r)) for r in rows]

    def artifacts_dir(self, ex_id: str) -> Path:
        p = self.root / "artifacts" / ex_id
        p.mkdir(parents=True, exist_ok=True)
        return p
