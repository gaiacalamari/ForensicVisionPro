"""Registro dei parser di struttura: nuovi formati si aggiungono registrando una funzione."""
from __future__ import annotations

from typing import Callable

from . import bmp, isobmff, jpeg, png
from .base import ParseResult

PARSERS: dict[str, Callable[[str], ParseResult]] = {
    "jpeg": jpeg.parse, "png": png.parse, "bmp": bmp.parse,
    "mp4": isobmff.parse, "mov": isobmff.parse, "3gp": isobmff.parse, "heif": isobmff.parse, "avif": isobmff.parse,
}


def register(format_key: str, fn: Callable[[str], ParseResult]) -> None:
    PARSERS[format_key] = fn


def parser_for(format_key: str | None):
    return PARSERS.get(format_key or "")
