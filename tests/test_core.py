import hashlib
import os
import sqlite3
import stat

import pytest

from fvp.cases.store import Case, CaseError
from fvp.core.audit import AuditLog
from fvp.core.findings import Category, Finding, Level, Status, category_status
from fvp.core.tasks import Cancelled, CancelToken
from fvp.engines import hashing


def test_hash_matches_hashlib(tmp_path):
    p = tmp_path / "f.bin"
    data = os.urandom(9 * 1024 * 1024 + 7)      # più blocchi
    p.write_bytes(data)
    h = hashing.hash_file(p, hashing.ALGORITHMS)
    for alg, val in h.items():
        assert val == hashlib.new(alg, data).hexdigest()


def test_hash_cancel(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"x" * 10)
    tok = CancelToken()
    tok.cancel()
    with pytest.raises(Cancelled):
        hashing.hash_file(p, ["sha256"], cancel=tok)


def test_hash_directory(tmp_path):
    (tmp_path / "a").write_bytes(b"a")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b").write_bytes(b"b")
    r = hashing.hash_directory(tmp_path, ["md5"])
    assert {x["hashes"]["md5"] for x in r} == {hashlib.md5(b"a").hexdigest(), hashlib.md5(b"b").hexdigest()}


def test_audit_chain_detects_tampering(tmp_path):
    conn = sqlite3.connect(tmp_path / "a.db")
    log = AuditLog(conn)
    for i in range(5):
        log.append("op", f"azione{i}", {"i": i})
    assert log.verify().ok
    with pytest.raises(sqlite3.DatabaseError):
        with conn:
            conn.execute("UPDATE audit_log SET actor='x' WHERE seq=2")
    # un attaccante con accesso al file rimuove i trigger e altera una voce
    conn.execute("DROP TRIGGER audit_no_update")
    with conn:
        conn.execute("UPDATE audit_log SET details='{\"i\": 99}' WHERE seq=3")
    v = log.verify()
    assert not v.ok and v.broken_at == 3


def test_audit_chain_detects_deletion(tmp_path):
    conn = sqlite3.connect(tmp_path / "a.db")
    log = AuditLog(conn)
    for i in range(4):
        log.append("op", "a", {"i": i})
    conn.execute("DROP TRIGGER audit_no_delete")
    with conn:
        conn.execute("DELETE FROM audit_log WHERE seq=2")
    assert not log.verify().ok


def test_acquisition_preserves_original(case, tmp_path):
    src = tmp_path / "evidence.jpg"
    src.write_bytes(os.urandom(100_000))
    before = (src.read_bytes(), src.stat().st_mtime_ns)
    ex = case.acquire(src, "tester")
    assert (src.read_bytes(), src.stat().st_mtime_ns) == before
    assert ex.source_hashes == ex.working_hashes
    assert ex.source_hashes["sha256"] == hashlib.sha256(before[0]).hexdigest()
    mode = os.stat(ex.working_path).st_mode
    assert not mode & stat.S_IWUSR
    assert "mtime_utc" in ex.source_stat
    assert case.verify_exhibit(ex.id, "tester", check_source=True)["working_copy_ok"]
    assert [e["action"] for e in case.audit.entries("custody")][-1] == "verifica_integrita"


def test_verify_detects_modified_working_copy(case, tmp_path):
    src = tmp_path / "e.bin"
    src.write_bytes(b"abc" * 1000)
    ex = case.acquire(src, "tester")
    os.chmod(ex.working_path, stat.S_IWUSR | stat.S_IRUSR)
    with open(ex.working_path, "r+b") as fh:
        fh.write(b"X")
    assert not case.verify_exhibit(ex.id, "tester")["working_copy_ok"]


def test_case_requires_operator(tmp_path):
    with pytest.raises(CaseError):
        Case.create(tmp_path, "X", "t", "")


def test_case_reopen_and_list(case):
    root = case.root
    case.close()
    c2 = Case.open(root, "altro")
    assert c2.info["case_id"] == "T-001"
    assert Case.list_cases(root.parent)[0]["case_id"] == "T-001"
    assert c2.audit.verify().ok
    c2.close()


def test_category_status_rules():
    mk = lambda cat, lv, sig=False: Finding(cat, lv, "t", "d", "m", "x", significant=sig)  # noqa: E731
    f = [mk(Category.METADATA, Level.SUSPICIOUS), mk(Category.FILE_STRUCTURE, Level.EVIDENCE, True),
         mk(Category.INTEGRITY, Level.INFO)]
    st = category_status(f, {Category.METADATA, Category.FILE_STRUCTURE, Category.INTEGRITY, Category.TEMPORAL})
    assert st[Category.METADATA] == Status.YELLOW
    assert st[Category.FILE_STRUCTURE] == Status.RED
    assert st[Category.INTEGRITY] == Status.GREEN
    assert st[Category.TEMPORAL] == Status.GREEN
    assert st[Category.DEEPFAKE] == Status.GREY


def test_finding_roundtrip():
    f = Finding(Category.TEMPORAL, Level.ANOMALY, "t", "d", "m", "mod", offset=12, data={"a": 1})
    assert Finding.from_dict(f.to_dict()) == f
