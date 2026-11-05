"""Configurazione applicativa (JSON nella cartella utente)."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_home() -> Path:
    base = os.environ.get("FVP_HOME")
    if base:
        return Path(base)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / "portable.flag").exists():     # versione portable: dati accanto all'eseguibile
            return exe_dir / "data"
    return Path.home() / "ForensicVisionPro"


@dataclass
class Settings:
    strict_forensic: bool = True
    cases_dir: str = ""
    prnu_dir: str = ""
    operator: str = ""
    exiftool_path: str = ""
    ffprobe_path: str = ""
    ffmpeg_path: str = ""
    tool_timeout_s: int = 120
    max_image_pixels: int = 250_000_000
    ui_mode: str = "Advanced"          # Basic | Advanced | Expert
    ui_theme: str = "light"            # light | dark
    hash_algorithms: list[str] = field(default_factory=lambda: ["md5", "sha1", "sha256", "sha512", "sha3_256", "blake2b"])

    @property
    def cases_path(self) -> Path:
        return Path(self.cases_dir) if self.cases_dir else default_home() / "cases"

    @property
    def prnu_path(self) -> Path:
        return Path(self.prnu_dir) if self.prnu_dir else default_home() / "prnu"

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or default_home() / "settings.json"
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except (OSError, ValueError, TypeError):
                pass
        return cls()

    def save(self, path: Path | None = None) -> None:
        path = path or default_home() / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
