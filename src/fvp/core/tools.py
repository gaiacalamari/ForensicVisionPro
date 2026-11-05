"""Localizzazione ed esecuzione controllata di strumenti esterni (ExifTool, FFprobe).

Gli strumenti sono eseguiti senza shell, con timeout, e il loro output è trattato
come dato non attendibile. Le versioni vengono registrate per la riproducibilità.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class ToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    path: str
    version: str


def _bundled_dir() -> Path:
    # Con PyInstaller gli strumenti possono essere inclusi in <app>/bin
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return base / "bin"


def locate(name: str, configured: str = "") -> str | None:
    if configured and Path(configured).is_file():
        return configured
    exe = name + (".exe" if sys.platform == "win32" else "")
    cand = _bundled_dir() / exe
    if cand.is_file():
        return str(cand)
    return shutil.which(name)


def run(args: list[str], timeout: int = 120, max_output: int = 256 * 1024 * 1024) -> bytes:
    try:
        cp = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"{Path(args[0]).name}: timeout dopo {timeout}s") from e
    except OSError as e:
        raise ToolError(f"{Path(args[0]).name}: impossibile eseguire ({e})") from e
    if len(cp.stdout) > max_output:
        raise ToolError(f"{Path(args[0]).name}: output oltre il limite")
    if cp.returncode != 0 and not cp.stdout:
        raise ToolError(f"{Path(args[0]).name}: codice {cp.returncode}: {cp.stderr.decode(errors='replace')[:500]}")
    return cp.stdout


@lru_cache(maxsize=None)
def get_tool(name: str, configured: str = "") -> Tool | None:
    path = locate(name, configured)
    if not path:
        return None
    try:
        if name == "exiftool":
            ver = run([path, "-ver"], timeout=20).decode().strip()
        else:
            ver = run([path, "-version"], timeout=20).decode(errors="replace").splitlines()[0]
    except ToolError:
        ver = "sconosciuta"
    return Tool(name, path, ver)
