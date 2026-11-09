"""Scarica e verifica gli strumenti esterni elencati in bin/tools.json.

- Ogni archivio è verificato con SHA-256 (valore fisso nel manifest o pubblicato dal fornitore)
  prima di estrarre qualsiasi file: se l'hash non corrisponde, non viene scritto nulla.
- Vengono estratti solo i file e le cartelle indicati, con nomi fissi dentro bin/ (nessun percorso
  preso dall'archivio può uscire dalla cartella).
- bin/tools.lock.json registra URL, hash, dimensione, data e output di verifica di ogni strumento,
  per documentare nei report quali binari sono stati usati.
- Uno strumento già presente con lo stesso hash non viene riscaricato (usare --force per farlo).
- Le voci con "optional": true (es. i modelli della stima della posa) non bloccano la build: un errore o un'impronta
  non ancora fissata produce solo un avviso.
- --pin NOME fissa l'impronta di una voce: scarica il file da tutte le sorgenti elencate e scrive lo SHA-256 in
  tools.json solo se tutte restituiscono lo stesso file (con --allow-single basta una sorgente).

Uso:  python tools/fetch_tools.py [--force] [--only nome|gruppo] [--bin cartella]
      python tools/fetch_tools.py --pin nome|gruppo [--allow-single]
Solo libreria standard: funziona prima che le dipendenze siano installate.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "ForensicVisionPro-fetch/1.0"}


class FetchError(RuntimeError):
    pass


def _platform_ok(p: str) -> bool:
    return p in ("any", "", None) or sys.platform.startswith(p)


def _get(url: str, dest: Path | None = None, timeout: int = 120) -> bytes | None:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if dest is None:
            return r.read(1024 * 1024)
        with open(dest, "wb") as fh:
            shutil.copyfileobj(r, fh, 1024 * 1024)
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _expected_hash(tool: dict) -> str:
    if tool.get("sha256"):
        return tool["sha256"].lower()
    if tool.get("sha256_url"):
        txt = _get(tool["sha256_url"]).decode("ascii", errors="replace")
        m = re.search(r"\b[0-9a-fA-F]{64}\b", txt)
        if m:
            return m.group(0).lower()
        raise FetchError(f"{tool['name']}: nessun SHA-256 in {tool['sha256_url']}")
    raise FetchError(f"{tool['name']}: il manifest deve indicare sha256 o sha256_url")


def _safe_name(name: str) -> str:
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or len(p.parts) != 1:
        raise FetchError(f"nome di destinazione non valido: {name}")
    return name


def _extract(zf: zipfile.ZipFile, tool: dict, bin_dir: Path) -> list[str]:
    names = zf.namelist()
    written: list[str] = []
    done: set[str] = set()
    for pattern, dest in tool.get("extract", {}).items():
        dest = _safe_name(dest)
        if dest in done:
            continue
        match = next((n for n in names if fnmatch.fnmatch(n, pattern) and not n.endswith("/")), None)
        if match:
            with zf.open(match) as src, open(bin_dir / dest, "wb") as out:
                shutil.copyfileobj(src, out)
            done.add(dest)
            written.append(dest)
    wanted = {_safe_name(d) for d in tool.get("extract", {}).values()}
    if wanted - done:
        raise FetchError(f"{tool['name']}: file non trovati nell'archivio: {', '.join(sorted(wanted - done))}")
    for pattern, dest in tool.get("dirs", {}).items():
        dest = _safe_name(dest)
        prefix = next((n for n in names if n.endswith("/") and fnmatch.fnmatch(n.rstrip("/"), pattern)), None)
        if prefix is None:   # archivi senza voci di directory esplicite
            cand = {n.split("/")[0] + "/" + n.split("/")[1] + "/" for n in names if n.count("/") >= 2}
            prefix = next((c for c in sorted(cand) if fnmatch.fnmatch(c.rstrip("/"), pattern)), None)
        if prefix is None:
            raise FetchError(f"{tool['name']}: cartella {pattern} non trovata nell'archivio")
        target = bin_dir / dest
        if target.exists():
            shutil.rmtree(target)
        for n in names:
            if not n.startswith(prefix) or n.endswith("/"):
                continue
            rel = PurePosixPath(n[len(prefix):])
            if rel.is_absolute() or ".." in rel.parts:
                raise FetchError(f"percorso non sicuro nell'archivio: {n}")
            out = target.joinpath(*rel.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(n) as src, open(out, "wb") as fh:
                shutil.copyfileobj(src, fh)
        written.append(dest + "/")
    return written


def _check(tool: dict, bin_dir: Path) -> str:
    args = tool.get("check")
    if not args:
        return ""
    exe = bin_dir / args[0]
    try:
        cp = subprocess.run([str(exe), *args[1:]], capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    except OSError as e:
        raise FetchError(f"{tool['name']}: impossibile eseguire {exe.name} ({e})") from e
    out = (cp.stdout or cp.stderr).decode(errors="replace").strip().splitlines()
    if cp.returncode != 0:
        raise FetchError(f"{tool['name']}: {exe.name} termina con codice {cp.returncode}")
    return out[0] if out else ""


def fetch(bin_dir: Path, force: bool = False, only: str | None = None, log=print) -> dict:
    manifest = json.loads((bin_dir / "tools.json").read_text(encoding="utf-8"))
    lock_path = bin_dir / "tools.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
    errors = []
    for tool in manifest.get("tools", []):
        name = tool["name"]
        if only and only not in (name, tool.get("group")):
            continue
        if not _platform_ok(tool.get("platform", "any")):
            log(f"- {name}: non previsto per {sys.platform}, si userà quello di sistema (PATH)")
            continue
        if tool.get("optional") and not (tool.get("sha256") or tool.get("sha256_url")):
            log(f"- {name}: facoltativo, impronta non ancora fissata: eseguire "
                f"'python tools/fetch_tools.py --pin {tool.get('group') or name}' e verificare il valore")
            continue
        try:
            expected = _expected_hash(tool)
            prev = lock.get(name)
            present = prev and all((bin_dir / f.rstrip("/")).exists() for f in prev.get("files", []))
            if present and prev.get("sha256") == expected and not force:
                log(f"- {name}: già presente e verificato ({prev.get('check_output', '')})")
                continue
            with tempfile.TemporaryDirectory() as td:
                arc = Path(td) / "download.zip"
                last = None
                for url in tool["urls"]:
                    try:
                        log(f"- {name}: download da {url}")
                        _get(url, arc, timeout=600)
                        got = _sha256(arc)
                        if got != expected:
                            last = FetchError(f"hash diverso da {url}: atteso {expected}, ottenuto {got}")
                            log(f"  {last}")
                            continue
                        break
                    except OSError as e:
                        last = e
                        log(f"  non riuscito: {e}")
                else:
                    raise FetchError(f"{name}: nessun download valido ({last})")
                with zipfile.ZipFile(arc) as zf:
                    files = _extract(zf, tool, bin_dir)
                size = arc.stat().st_size
            out = _check(tool, bin_dir)
            file_hashes = {f: _sha256(bin_dir / f) for f in files if not f.endswith("/")}
            lock[name] = {"version": tool.get("version", ""), "url": url, "sha256": expected, "size": size,
                          "files": files, "file_hashes": file_hashes, "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                          "check_output": out}
            lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")
            log(f"  installato in {bin_dir}: {', '.join(files)} — {out}")
        except (FetchError, OSError, zipfile.BadZipFile, ValueError) as e:
            if tool.get("optional"):
                log(f"  AVVISO {name} (facoltativo, non installato): {e}")
                continue
            errors.append(f"{name}: {e}")
            log(f"  ERRORE {name}: {e}")
    if errors:
        raise FetchError("; ".join(errors))
    return lock


def pin(bin_dir: Path, target: str, allow_single: bool = False, log=print) -> dict[str, str]:
    """Calcola lo SHA-256 da tutte le sorgenti di una voce (o di un gruppo) e lo scrive in tools.json."""
    path = bin_dir / "tools.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    pinned: dict[str, str] = {}
    sel = [t for t in manifest.get("tools", []) if target in (t["name"], t.get("group"))]
    if not sel:
        raise FetchError(f"nessuna voce '{target}' in {path}")
    for tool in sel:
        hashes: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as td:
            for i, url in enumerate(tool["urls"]):
                arc = Path(td) / f"src{i}"
                try:
                    log(f"- {tool['name']}: download da {url}")
                    _get(url, arc, timeout=600)
                    hashes[url] = _sha256(arc)
                    zipfile.ZipFile(arc).close()          # deve essere un archivio valido
                    log(f"  SHA-256 {hashes[url]}")
                except (OSError, zipfile.BadZipFile) as e:
                    log(f"  non riuscito: {e}")
                    hashes.pop(url, None)
        if not hashes:
            raise FetchError(f"{tool['name']}: nessuna sorgente raggiungibile")
        if len(set(hashes.values())) != 1:
            raise FetchError(f"{tool['name']}: le sorgenti restituiscono file diversi: {hashes}")
        if len(hashes) < len(tool["urls"]) and not allow_single:
            raise FetchError(f"{tool['name']}: solo {len(hashes)} sorgenti su {len(tool['urls'])} raggiungibili; "
                             "impronta non confermata (usare --allow-single per accettarla)")
        tool["sha256"] = next(iter(hashes.values()))
        tool["pinned_from"] = sorted(hashes)
        pinned[tool["name"]] = tool["sha256"]
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"Impronte scritte in {path}: verificare il diff prima del commit.")
    return pinned


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bin", default=str(ROOT / "bin"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--pin", metavar="NOME")
    ap.add_argument("--allow-single", action="store_true")
    a = ap.parse_args()
    try:
        if a.pin:
            pin(Path(a.bin), a.pin, a.allow_single)
            return 0
        fetch(Path(a.bin), a.force, a.only)
    except FetchError as e:
        print(f"\nStrumenti non installati: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
