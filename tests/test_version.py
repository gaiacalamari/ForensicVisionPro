"""La versione deve coincidere in tutti i punti in cui compare (programma, pacchetto, installer, build, changelog)."""
import re
from pathlib import Path

from fvp import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_version_consistent():
    txt = lambda p: (ROOT / p).read_text(encoding="utf-8")  # noqa: E731
    assert re.search(r'^version = "([^"]+)"', txt("pyproject.toml"), re.M).group(1) == __version__
    assert re.search(r'#define AppVersion "([^"]+)"', txt("packaging/installer.iss")).group(1) == __version__
    assert re.search(r'\$Version = "([^"]+)"', txt("packaging/build_windows.ps1")).group(1) == __version__
    assert re.search(r"^## (\S+)", txt("CHANGELOG.md"), re.M).group(1) == __version__
