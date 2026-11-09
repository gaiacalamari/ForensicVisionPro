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
    # Persone e movimento (stima della posa, metodologia Sports2D)
    pose_det_model: str = ""           # vuoto = bin/ o <home>/models
    pose_model: str = ""
    pose_max_frames: int = 3600        # frame analizzati al massimo per video
    pose_frame_step: int = 1           # 1 = ogni frame (necessario per le discontinuità tra frame)
    pose_det_every: int = 4            # rilevamento delle persone ogni N frame (Sports2D: det_frequency)
    pose_annotated_video: bool = True  # video con scheletro, angoli e numero di frame (come Sports2D)
    # Sports2D e Pose2Sim originali (D. Pagnon), eseguiti in un ambiente Python separato
    sports2d_python: str = ""          # vuoto = <home>/sports2d-env
    sports2d_timeout_s: int = 7200
    sports2d_person_height_m: float = 0.0   # statura documentata (m); 0 = non nota
    sports2d_person_mass_kg: float = 0.0     # massa documentata (kg); 0 = non nota (influisce solo sulle forze)
    sports2d_opensim: bool = True      # modello OpenSim scalato (.osim) e cinematica inversa (.mot) via Pose2Sim
    sports2d_simple_model: bool = False  # modello OpenSim semplificato: IK 10 volte più rapida, senza muscoli
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
