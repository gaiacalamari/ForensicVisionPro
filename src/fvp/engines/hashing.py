"""Hash Engine: calcolo a blocchi di più algoritmi in una sola lettura."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, Iterator

from ..core.tasks import CancelToken, ProgressFn, noop_progress

ALGORITHMS = {
    "md5": "MD5",
    "sha1": "SHA-1",
    "sha256": "SHA-256",
    "sha512": "SHA-512",
    "sha3_256": "SHA3-256",
    "blake2b": "BLAKE2b-512",
}
CHUNK = 4 * 1024 * 1024


def _new(alg: str):
    if alg not in ALGORITHMS:
        raise ValueError(f"Algoritmo non supportato: {alg}")
    return hashlib.new(alg)


def hash_file(path: str | Path, algorithms: Iterable[str] = ("sha256",), progress: ProgressFn = noop_progress,
              cancel: CancelToken | None = None) -> dict[str, str]:
    algs = list(algorithms)
    hs = {a: _new(a) for a in algs}
    size = os.path.getsize(path) or 1
    done = 0
    with open(path, "rb") as fh:
        while True:
            if cancel:
                cancel.check()
            buf = fh.read(CHUNK)
            if not buf:
                break
            for h in hs.values():
                h.update(buf)
            done += len(buf)
            progress(min(done / size, 1.0), f"Hash {Path(path).name}")
    return {a: h.hexdigest() for a, h in hs.items()}


def iter_files(root: str | Path) -> Iterator[Path]:
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            yield Path(dirpath) / f


def hash_directory(root: str | Path, algorithms: Iterable[str] = ("sha256",), progress: ProgressFn = noop_progress,
                   cancel: CancelToken | None = None) -> list[dict]:
    files = list(iter_files(root))
    out = []
    for i, p in enumerate(files):
        if cancel:
            cancel.check()
        try:
            out.append({"path": str(p), "size": p.stat().st_size, "hashes": hash_file(p, algorithms, cancel=cancel)})
        except OSError as e:
            out.append({"path": str(p), "error": str(e)})
        progress((i + 1) / max(len(files), 1), str(p.name))
    return out


def compare(a: dict[str, str], b: dict[str, str]) -> dict[str, bool]:
    return {k: a[k].lower() == b[k].lower() for k in a.keys() & b.keys()}
