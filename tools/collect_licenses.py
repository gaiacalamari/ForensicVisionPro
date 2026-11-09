"""Raccoglie in una cartella le licenze di tutto ciò che viene distribuito con l'eseguibile.

- testi integrali di licenses/ (GPL, LGPL, Apache, Artistic, BSD di Sports2D/Pose2Sim);
- file di licenza e di note dei pacchetti Python installati (dist-info e, dove presenti, le note sulle librerie
  native incluse nelle wheel: cv2/LICENSE-3RD-PARTY.txt, pillow-heif LICENSES_bundled.txt, onnxruntime
  ThirdPartyNotices.txt);
- licenza dell'interprete Python;
- file di licenza degli strumenti in bin/ (es. ffmpeg-LICENSE.txt);
- INDEX.md con componente, versione, licenza dichiarata e file copiati.

Esce con codice 1 se un pacchetto di runtime elencato in fvp.core.credits non è installato o non ha nessun testo
di licenza disponibile: la build non deve produrre un pacchetto senza le licenze dei componenti inclusi.

Uso:  python tools/collect_licenses.py [cartella_di_uscita]   (predefinita: build/third_party_licenses)
"""
from __future__ import annotations

import shutil
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fvp.core.credits import CREDITS, RUNTIME, TOOL  # noqa: E402

KEYS = ("LICEN", "COPYING", "NOTICE", "THIRDPARTY", "AUTHORS")
MAX_FILE = 2 * 1024 * 1024


def _dist_license_files(dist: metadata.Distribution) -> list[Path]:
    out = []
    for f in dist.files or []:
        pth = Path(str(f))
        if pth.suffix.lower() not in ("", ".txt", ".md", ".rst"):     # solo testi (esclude sorgenti e test)
            continue
        name = pth.name.upper().replace("_", "").replace("-", "")
        if any(name.startswith(k) or f"-{k}" in pth.name.upper() or f"_{k}" in pth.name.upper() for k in KEYS) \
                or any(name.startswith(x) for x in ("THIRDPARTYNOTICES", "LICENSESBUNDLED", "LICENSE3RDPARTY")):
            p = Path(dist.locate_file(f))
            if p.is_file() and p.stat().st_size <= MAX_FILE:
                out.append(p)
    return out


def _python_license() -> Path | None:
    for c in (Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_paths()["stdlib"]) / "LICENSE.txt"):
        if c.is_file():
            return c
    return None


def collect(out: Path, bin_dir: Path | None = None, log=print) -> list[str]:
    bin_dir = bin_dir or ROOT / "bin"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    problems: list[str] = []
    rows: list[tuple[str, str, str, str]] = []
    for f in sorted((ROOT / "licenses").glob("*.txt")):
        shutil.copy2(f, out / f.name)
    rows.append(("Testi integrali delle licenze", "-", "-", ", ".join(sorted(p.name for p in out.glob("*.txt")))))
    py = _python_license()
    if py:
        shutil.copy2(py, out / "Python-LICENSE.txt")
        rows.append(("Python", sys.version.split()[0], "PSF-2.0", "Python-LICENSE.txt"))
    else:
        log("  avviso: licenza di Python non trovata (https://docs.python.org/3/license.html)")
    for c in CREDITS:
        if c.kind != RUNTIME or not c.packages:
            continue
        for pkg in c.packages:
            try:
                dist = metadata.distribution(pkg)
            except metadata.PackageNotFoundError:
                problems.append(f"{pkg}: non installato")
                continue
            dest = out / f"{dist.metadata['Name']}-{dist.version}"
            files = _dist_license_files(dist)
            # PySide6 è diviso in più distribuzioni: le licenze possono trovarsi nelle altre
            if pkg == "PySide6":
                for extra in ("PySide6_Essentials", "PySide6_Addons", "shiboken6"):
                    try:
                        files += _dist_license_files(metadata.distribution(extra))
                    except metadata.PackageNotFoundError:
                        pass
            copied = []
            if files:
                dest.mkdir(exist_ok=True)
                for f in files:
                    name = f.name if not (dest / f.name).exists() else f"{f.parent.name}-{f.name}"
                    shutil.copy2(f, dest / name)
                    copied.append(f"{dest.name}/{name}")
            for lf in c.license_files:                    # testi integrali di riferimento (es. LGPL per Qt)
                if (out / lf).is_file():
                    copied.append(lf)
            if not copied:
                problems.append(f"{pkg}: nessun testo di licenza disponibile")
            lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or c.license
            rows.append((c.name, dist.version, lic.splitlines()[0][:80], ", ".join(dict.fromkeys(copied))))
    for c in CREDITS:
        if c.kind != TOOL:
            continue
        found = [p for t in c.tools for p in sorted(bin_dir.glob(f"{t}*")) if any(k in p.name.upper() for k in KEYS)]
        for p in found:
            shutil.copy2(p, out / p.name)
        rows.append((c.name, "bin/", c.license, ", ".join([p.name for p in found] + list(c.license_files))))
    idx = ["# Licenze dei componenti distribuiti con Forensic Vision Pro", "",
           "Generato da tools/collect_licenses.py. Crediti completi e sorgenti dei componenti copyleft: "
           "THIRD_PARTY_NOTICES.md.", "", "| Componente | Versione | Licenza dichiarata | File |", "|---|---|---|---|"]
    idx += [f"| {a} | {b} | {c_} | {d} |" for a, b, c_, d in rows]
    (out / "INDEX.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", out / "THIRD_PARTY_NOTICES.md")
    for pr in problems:
        log(f"  ERRORE: {pr}")
    log(f"Licenze raccolte in {out} ({sum(1 for _ in out.rglob('*') if _.is_file())} file)")
    return problems


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "third_party_licenses"
    return 1 if collect(out) else 0


if __name__ == "__main__":
    sys.exit(main())
