"""Decodifica HEIF/HEIC tramite pillow-heif (libheif + libde265).

ensure_registered() registra il decoder in Pillow: da quel momento Image.open() apre anche i file
.heic/.heif, e tutti i moduli d'immagine esistenti (ELA, rumore, copy-move, steganalisi, PRNU,
confronto, report) li analizzano senza modifiche. Il limite di pixel di Pillow resta attivo.

La decodifica non scrive nulla sul reperto: pillow-heif legge il file in sola lettura.
"""
from __future__ import annotations

from pathlib import Path

from ..core.findings import Category, Finding, Level

MODULE = "heif"
_STATE: dict = {"done": False, "version": None, "libheif": None, "error": None}


def ensure_registered() -> bool:
    """Registra l'opener HEIF in Pillow (idempotente). False se pillow-heif non è installato."""
    if _STATE["done"]:
        return _STATE["version"] is not None
    _STATE["done"] = True
    try:
        import pillow_heif
        # Nessuna conversione silenziosa: profondità di bit e miniature restano leggibili per l'analisi.
        pillow_heif.register_heif_opener(thumbnails=True)
        _STATE["version"] = pillow_heif.__version__
        _STATE["libheif"] = pillow_heif.libheif_version()
        return True
    except Exception as e:  # noqa: BLE001 - dipendenza opzionale
        _STATE["error"] = f"{type(e).__name__}: {e}"
        return False


def versions() -> dict:
    ensure_registered()
    return {"pillow_heif": _STATE["version"] or "non disponibile", "libheif": _STATE["libheif"] or "—"}


def details(path: str | Path) -> dict:
    """Caratteristiche della codifica lette da libheif (non dai metadati dichiarati)."""
    if not ensure_registered():
        return {"available": False, "error": _STATE["error"]}
    import pillow_heif
    h = pillow_heif.open_heif(str(path), convert_hdr_to_8bit=False)
    prim = h[h.primary_index]
    out = {"available": True, "images": len(h), "primary_index": h.primary_index,
           "size": list(prim.size), "mode": prim.mode, "bit_depth": prim.info.get("bit_depth"),
           "chroma": prim.info.get("chroma"), "has_alpha": prim.has_alpha,
           "thumbnails": list(prim.info.get("thumbnails") or []),
           "depth_images": len(prim.info.get("depth_images") or []),
           "aux": {k: len(v) for k, v in (prim.info.get("aux") or {}).items()},
           "nclx": prim.info.get("nclx_profile"), "has_icc": bool(prim.info.get("icc_profile"))}
    return out


def thumbnail_check(path: str | Path) -> Finding | None:
    """Confronta la miniatura HEIF ('thmb') con l'immagine principale, come per la miniatura EXIF dei JPEG."""
    if not ensure_registered():
        return None
    import pillow_heif
    from . import image
    meth = "Confronto miniatura HEIF / immagine principale"
    try:
        h = pillow_heif.open_heif(str(path))
        prim = h[h.primary_index]
        if not prim.info.get("thumbnails"):
            return None
        th = prim.get_thumbnail(0).to_pillow().convert("L")
    except Exception as e:  # noqa: BLE001
        return Finding(Category.IMAGE_MANIPULATION, Level.UNDETERMINED, "Miniatura HEIF non decodificabile",
                       f"{type(e).__name__}: {e}", meth, MODULE)
    return image.compare_thumbnail(th, path, meth)
