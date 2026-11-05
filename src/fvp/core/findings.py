"""Modello dei risultati forensi.

Ogni risultato dichiara esplicitamente il proprio livello di affidabilità.
Nessun modulo produce un verdetto di autenticità: il riepilogo per categoria
indica solo se i test eseguiti hanno rilevato qualcosa da approfondire.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable


class Level(str, Enum):
    EVIDENCE = "evidenza_certa"            # fatto verificabile (es. hash diverso, CRC errato)
    ANOMALY = "anomalia_tecnica"           # deviazione dallo standard o dall'atteso
    SUSPICIOUS = "indicatore_sospetto"     # compatibile con manipolazione, non la prova
    PROBABILISTIC = "risultato_probabilistico"  # esito di un algoritmo statistico/ML
    UNDETERMINED = "non_determinabile"     # il test non può concludere
    INFO = "informativo"                   # dato utile, nessuna anomalia

    @property
    def label(self) -> str:
        return {
            "evidenza_certa": "Evidenza certa",
            "anomalia_tecnica": "Anomalia tecnica",
            "indicatore_sospetto": "Indicatore sospetto",
            "risultato_probabilistico": "Risultato probabilistico",
            "non_determinabile": "Non determinabile",
            "informativo": "Informativo",
        }[self.value]


class Category(str, Enum):
    INTEGRITY = "Integrity"
    METADATA = "Metadata"
    TEMPORAL = "Temporal Consistency"
    IMAGE_MANIPULATION = "Image Manipulation"
    AI_GENERATION = "AI Generation"
    DEEPFAKE = "Deepfake"
    VIDEO_INTEGRITY = "Video Integrity"
    AUDIO_INTEGRITY = "Audio Integrity"
    FILE_STRUCTURE = "File Structure"
    STEGANOGRAPHY = "Steganography"
    SENSOR = "Sensor / Source"


class Status(str, Enum):
    GREEN = "verde"     # nessuna anomalia rilevata dai test eseguiti
    YELLOW = "giallo"   # elemento da approfondire
    RED = "rosso"       # anomalia significativa
    GREY = "grigio"     # test non eseguito o inconcludente


@dataclass
class Finding:
    category: Category
    level: Level
    title: str
    description: str
    method: str
    module: str
    evidence: str = ""
    offset: int | None = None
    confidence: str = ""          # testo esplicito: "alta", "media", "n/a", o valore numerico motivato
    limitations: str = ""
    significant: bool = False     # True solo per anomalie che il modulo ritiene rilevanti
    source: str = "automatico"    # "automatico" | "operatore"
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["level"] = self.level.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Finding":
        d = dict(d)
        d["category"] = Category(d["category"])
        d["level"] = Level(d["level"])
        return cls(**d)


def category_status(findings: Iterable[Finding], executed: set[Category]) -> dict[Category, Status]:
    """Stato per categoria. Grigio se nessun test della categoria è stato eseguito."""
    out: dict[Category, Status] = {}
    fl = list(findings)
    for cat in Category:
        if cat not in executed:
            out[cat] = Status.GREY
            continue
        items = [f for f in fl if f.category == cat]
        if any(f.significant and f.level in (Level.EVIDENCE, Level.ANOMALY, Level.SUSPICIOUS) for f in items):
            out[cat] = Status.RED
        elif any(f.level in (Level.EVIDENCE, Level.ANOMALY, Level.SUSPICIOUS) for f in items):
            out[cat] = Status.YELLOW
        elif any(f.level == Level.PROBABILISTIC and f.significant for f in items):
            out[cat] = Status.YELLOW
        elif items and all(f.level in (Level.UNDETERMINED, Level.PROBABILISTIC) for f in items) and \
                any(f.level == Level.UNDETERMINED for f in items):
            out[cat] = Status.GREY
        else:
            out[cat] = Status.GREEN
    return out
