"""Stato condiviso dell'applicazione ed esecuzione in background."""
from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..cases.store import Case
from ..core.config import Settings
from ..core.tasks import Cancelled, CancelToken


class AppState(QObject):
    case_changed = Signal()
    exhibit_changed = Signal()
    analysis_changed = Signal()
    settings_changed = Signal()
    busy_changed = Signal(bool)
    progress = Signal(float, str)
    open_hex = Signal(str)          # percorso da aprire nell'Hex Viewer
    theme_changed = Signal()
    navigate = Signal(str)
    show_map = Signal(str)          # mappa da mostrare in Analisi visiva

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.case: Case | None = None
        self.exhibit_id: str | None = None
        self.pool = QThreadPool.globalInstance()
        self._token: CancelToken | None = None
        self._workers: set = set()
        self.selfcheck: list = []

    @property
    def operator(self) -> str:
        return self.settings.operator or (self.case.info.get("operator", "") if self.case else "")

    def set_case(self, case: Case | None) -> None:
        if self.case and self.case is not case:
            self.case.close()
        self.case = case
        exs = case.exhibits() if case else []
        self.exhibit_id = exs[-1].id if exs else None
        self.case_changed.emit()
        self.exhibit_changed.emit()

    def set_exhibit(self, ex_id: str | None) -> None:
        self.exhibit_id = ex_id
        self.exhibit_changed.emit()

    def last_analysis(self) -> dict | None:
        if not (self.case and self.exhibit_id):
            return None
        an = self.case.analyses(self.exhibit_id)
        return an[-1] if an else None

    @property
    def busy(self) -> bool:
        return self._token is not None

    def cancel(self) -> None:
        if self._token:
            self._token.cancel()

    def run(self, fn: Callable[[Callable[[float, str], None], CancelToken], Any],
            done: Callable[[Any], None], failed: Callable[[str], None] | None = None) -> bool:
        """Esegue fn(progress, cancel) in un thread del pool; i callback tornano sul thread della GUI."""
        if self._token:
            return False
        tok = CancelToken()
        self._token = tok
        w = _Worker(fn, tok)
        self._workers.add(w)

        def finish():
            self._token = None
            self._workers.discard(w)
            self.busy_changed.emit(False)
        w.signals.progress.connect(self.progress)
        w.signals.done.connect(lambda r: (finish(), done(r)))
        w.signals.failed.connect(lambda m: (finish(), (failed or (lambda _m: None))(m)))
        self.busy_changed.emit(True)
        self.pool.start(w)
        return True


class _Signals(QObject):
    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)


class _Worker(QRunnable):
    def __init__(self, fn, token: CancelToken):
        super().__init__()
        self.setAutoDelete(False)
        self.fn, self.token, self.signals = fn, token, _Signals()

    def run(self) -> None:
        try:
            r = self.fn(lambda p, m: self.signals.progress.emit(float(p), m), self.token)
            self.signals.done.emit(r)
        except Cancelled:
            self.signals.failed.emit("Operazione annullata dall'operatore.")
        except Exception as e:  # noqa: BLE001
            self.signals.failed.emit(f"{type(e).__name__}: {e}\n\n{traceback.format_exc(limit=4)}")
