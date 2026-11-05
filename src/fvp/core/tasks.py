"""Primitive per operazioni lunghe: avanzamento e cancellazione cooperativa."""
from __future__ import annotations

import threading
from typing import Callable

ProgressFn = Callable[[float, str], None]


class Cancelled(Exception):
    """Sollevata quando l'operatore annulla un'operazione."""


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()

    def check(self) -> None:
        if self._ev.is_set():
            raise Cancelled()


def noop_progress(_p: float, _msg: str) -> None:
    pass
