"""Engine di analisi. All'import registra il decoder HEIF in Pillow, così ogni engine apre anche HEIC/HEIF."""
from .heif_support import ensure_registered as _ensure_heif

_ensure_heif()
