"""Crediti e licenze: ogni componente ha una voce, ogni voce è documentata e i testi di licenza esistono."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from fvp.core import credits  # noqa: E402

# pacchetti usati solo per sviluppo o già coperti da un'altra voce
DEV_ONLY = set()


def _norm(s: str) -> str:
    return re.sub(r"[-_.]+", "-", s).lower()


def _requirements() -> set[str]:
    out = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if line:
            out.add(_norm(re.split(r"[<>=!~\[ ]", line)[0]))
    return out


def test_every_requirement_is_credited():
    credited = {_norm(p) for c in credits.CREDITS for p in c.packages}
    missing = _requirements() - credited - DEV_ONLY
    assert not missing, f"pacchetti senza credito in fvp/core/credits.py: {sorted(missing)}"


def test_every_bundled_tool_is_credited():
    tools = {t["name"] for t in json.loads((ROOT / "bin" / "tools.json").read_text(encoding="utf-8"))["tools"]}
    credited = {t for c in credits.CREDITS for t in c.tools}
    assert tools <= credited, f"strumenti senza credito: {sorted(tools - credited)}"


def test_every_credit_is_in_notices_and_has_license_texts():
    notes = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for c in credits.CREDITS:
        assert c.name in notes, f"{c.name} manca in THIRD_PARTY_NOTICES.md"
        assert c.authors and c.license and c.url.startswith("https://"), c.name
        for lf in c.license_files:
            assert (ROOT / "licenses" / lf).is_file(), f"{c.name}: manca licenses/{lf}"


def test_copyleft_components_declare_source():
    for c in credits.CREDITS:
        if re.search(r"\bL?GPL", c.license) and c.kind in (credits.RUNTIME, credits.TOOL):
            assert c.source, f"{c.name}: componente copyleft senza indicazione del sorgente"


def test_derived_sources_keep_notices():
    pose = (ROOT / "src/fvp/engines/pose.py").read_text(encoding="utf-8")
    model = (ROOT / "src/fvp/engines/pose_model.py").read_text(encoding="utf-8")
    assert "Copyright (c) 2022, perfanalytics" in pose and "BSD-3-Clause-perfanalytics.txt" in pose
    assert "Apache-2.0" in model and "modificato" in model and "Open-MMLab" in model


def test_credits_cli(tmp_path):
    out = tmp_path / "crediti.txt"
    env = {"PYTHONPATH": str(ROOT / "src"), "QT_QPA_PLATFORM": "offscreen", "PATH": ""}
    r = subprocess.run([sys.executable, "-m", "fvp", "--credits", str(out)], env=env, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    txt = out.read_text(encoding="utf-8")
    for name in ("Phil Harvey", "Gyan Doshi", "Sports2D", "CScorza", "The Qt Company", "Copyright (c) 2022, perfanalytics"):
        assert name in txt
    r = subprocess.run([sys.executable, "-m", "fvp", "--credits"], env=env, capture_output=True, timeout=60)
    assert r.returncode == 0 and b"ExifTool" in r.stdout


def test_collect_licenses(tmp_path):
    sys.path.insert(0, str(ROOT / "tools"))
    import collect_licenses
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg-LICENSE.txt").write_text("GPLv3")
    problems = collect_licenses.collect(tmp_path / "out", bin_dir, log=lambda *_: None)
    assert problems == []
    idx = (tmp_path / "out" / "INDEX.md").read_text(encoding="utf-8")
    for name in ("Pillow", "NumPy", "OpenCV", "pillow-heif", "ONNX Runtime", "ExifTool", "FFmpeg"):
        assert name in idx
    assert (tmp_path / "out" / "ffmpeg-LICENSE.txt").is_file() and (tmp_path / "out" / "GPL-3.0.txt").is_file()
    assert not list((tmp_path / "out").rglob("*.f90"))          # solo testi di licenza


def test_report_lists_third_party_tools(case, tmp_path):
    from fvp.reporting import report
    html = report.write_html(case, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Strumenti e metodologie di terze parti" in html and "Phil Harvey" in html and "Sports2D" in html
