"""Avvio dell'applicazione desktop e controllo di sistema da riga di comando."""
from __future__ import annotations

import sys

from .. import APP_NAME


def selfcheck_cli(argv: list[str]) -> int:
    """--selfcheck [report.json]: verifica dipendenze e strumenti, codice di uscita 0 se tutto l'essenziale è ok."""
    from ..core import selfcheck
    checks = selfcheck.run()
    out = argv[argv.index("--selfcheck") + 1] if len(argv) > argv.index("--selfcheck") + 1 else None
    if out:
        selfcheck.write_report(checks, out)
    ok, failed = selfcheck.summary(checks)
    if sys.stdout:
        for c in checks:
            print(f"[{'OK' if c.ok else 'KO'}] {c.name}: {c.detail} {c.version}")
    return 0 if ok else 1


def main() -> int:
    if "--selfcheck" in sys.argv:
        return selfcheck_cli(sys.argv)
    if "--credits" in sys.argv:
        from ..core.credits import credits_cli
        return credits_cli(sys.argv)
    from PySide6.QtWidgets import QApplication

    from ..core.config import Settings
    from . import theme
    from .main_window import MainWindow
    from .state import AppState
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    settings = Settings.load()
    theme.apply(app, settings.ui_theme)
    settings.cases_path.mkdir(parents=True, exist_ok=True)
    w = MainWindow(AppState(settings))
    w.show()
    w.start_selfcheck()
    return app.exec()
