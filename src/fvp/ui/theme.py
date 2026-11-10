"""Temi chiaro (predefinito) e scuro.

I dizionari C, LEVEL_COLORS e STATUS_COLORS vengono aggiornati sul posto quando si cambia tema, così i
widget che li leggono al momento del disegno o dell'aggiornamento seguono il tema senza essere ricreati.
I colori di stato sono riservati ai risultati e scelti per un contrasto sufficiente su entrambi gli sfondi.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

LIGHT = {
    "base": "#f3f5f7", "panel": "#ffffff", "panel2": "#eef1f4", "rule": "#d3d9e0", "text": "#1d2732",
    "muted": "#5c6977", "accent": "#2a6a98", "accent_fg": "#ffffff", "accent_soft": "#dbe8f3", "select": "#cfe2f2",
    "sidebar": "#e9edf1", "zero": "#a3adb8",
    "green": "#2e7d4f", "yellow": "#a87a05", "red": "#bd3a2e", "grey": "#7a8592", "orange": "#c0620f",
    "blue": "#2f69ad",
}
DARK = {
    "base": "#1b2027", "panel": "#232a33", "panel2": "#2a323d", "rule": "#36404d", "text": "#d9dfe6",
    "muted": "#8f9aa7", "accent": "#6aa9cf", "accent_fg": "#0f1720", "accent_soft": "#2b4458", "select": "#2f4a5f",
    "sidebar": "#20262e", "zero": "#5c6672",
    "green": "#4f9d69", "yellow": "#d1aa3a", "red": "#cf5246", "grey": "#76808c", "orange": "#d9822b",
    "blue": "#5b8fd0",
}
C: dict[str, str] = dict(LIGHT)
LEVEL_COLORS: dict[str, str] = {}
STATUS_COLORS: dict[str, str] = {}
CURRENT = {"mode": "light"}


def _derive() -> None:
    LEVEL_COLORS.update({"evidenza_certa": C["red"], "anomalia_tecnica": C["orange"],
                         "indicatore_sospetto": C["yellow"], "risultato_probabilistico": C["blue"],
                         "non_determinabile": C["grey"], "informativo": C["muted"]})
    STATUS_COLORS.update({"verde": C["green"], "giallo": C["yellow"], "rosso": C["red"], "grigio": C["grey"]})


_derive()


def set_mode(mode: str) -> None:
    CURRENT["mode"] = "dark" if mode == "dark" else "light"
    C.clear()
    C.update(DARK if CURRENT["mode"] == "dark" else LIGHT)
    _derive()


def span(color_key: str, text: str, bold: bool = False) -> str:
    t = f"<b>{text}</b>" if bold else text
    return f"<span style='color:{C[color_key]}'>{t}</span>"


def mono_font(size: int = 10) -> QFont:
    for fam in ("JetBrains Mono", "Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Menlo"):
        if fam in QFontDatabase.families():
            f = QFont(fam, size)
            break
    else:
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setPointSize(size)
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


def palette() -> QPalette:
    p = QPalette()
    for role, key in ((QPalette.ColorRole.Window, "base"), (QPalette.ColorRole.WindowText, "text"),
                      (QPalette.ColorRole.Base, "panel"), (QPalette.ColorRole.AlternateBase, "panel2"),
                      (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "panel2"),
                      (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "select"),
                      (QPalette.ColorRole.HighlightedText, "text"), (QPalette.ColorRole.ToolTipBase, "panel"),
                      (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.PlaceholderText, "muted")):
        p.setColor(role, QColor(C[key]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(C["grey"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(C["grey"]))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(C["grey"]))
    return p


def qss() -> str:
    c = C
    return f"""
QWidget {{ color:{c['text']}; font-size:10pt; }}
QMainWindow, QStackedWidget > QWidget {{ background:{c['base']}; }}
#Sidebar {{ background:{c['sidebar']}; border:none; border-right:1px solid {c['rule']}; outline:0; padding-top:6px; }}
#Sidebar::item {{ padding:8px 16px; border-left:3px solid transparent; }}
#Sidebar::item:selected {{ background:{c['panel']}; border-left:3px solid {c['accent']}; color:{c['text']}; }}
#Sidebar::item:hover:!selected:enabled {{ background:{c['panel2']}; }}
#Sidebar::item:disabled {{ color:{c['grey']}; }}
#Brand {{ background:{c['sidebar']}; border-right:1px solid {c['rule']}; }}
#BrandName {{ font-size:13pt; font-weight:600; }}
#ContextBar {{ background:{c['panel']}; border-bottom:1px solid {c['rule']}; }}
#PageTitle {{ font-size:15pt; font-weight:600; }}
#PageIntro, #Muted {{ color:{c['muted']}; }}
#Strict {{ color:{c['green']}; border:1px solid {c['green']}; border-radius:3px; padding:1px 6px; }}
#StrictOff {{ color:{c['yellow']}; border:1px solid {c['yellow']}; border-radius:3px; padding:1px 6px; }}
#Stat {{ background:{c['panel']}; border:1px solid {c['rule']}; border-radius:4px; }}
#StatValue {{ font-size:20pt; font-weight:600; }}
#NotImpl {{ background:{c['panel']}; border:1px dashed {c['rule']}; border-radius:4px; padding:12px; color:{c['muted']}; }}
QScrollArea#PageScroll, QWidget#PageViewport, QWidget#PageViewport > QWidget {{ background:{c['base']}; border:none; }}
#HelpBox {{ background:{c['panel']}; border:1px solid {c['rule']}; border-left:3px solid {c['accent']}; border-radius:4px; padding:10px 12px; }}
#HelpButton {{ padding:3px 10px; }}
#ModeButton {{ padding:4px 12px; font-weight:600; }}
#Lead {{ font-size:11pt; }}
#BigDrop {{ border:2px dashed {c['accent']}; border-radius:8px; padding:28px; font-size:12pt; color:{c['accent']}; background:{c['accent_soft']}; }}
#Notice {{ background:{c['accent_soft']}; border:1px solid {c['accent']}; border-radius:4px; padding:10px; }}
#DropZone {{ background:{c['panel']}; border:2px dashed {c['rule']}; border-radius:6px; padding:18px; color:{c['muted']}; }}
#ImageView {{ background:{c['panel']}; border:1px solid {c['rule']}; }}
QGroupBox {{ border:1px solid {c['rule']}; border-radius:4px; margin-top:14px; padding-top:6px; background:{c['panel']}; }}
QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 4px; color:{c['muted']}; }}
QPushButton {{ background:{c['panel2']}; border:1px solid {c['rule']}; border-radius:3px; padding:5px 12px; }}
QPushButton:hover {{ border-color:{c['accent']}; }}
QPushButton:pressed {{ background:{c['select']}; }}
QPushButton:disabled {{ color:{c['grey']}; background:{c['base']}; }}
QPushButton#Primary {{ background:{c['accent']}; border-color:{c['accent']}; color:{c['accent_fg']}; font-weight:600; }}
QPushButton#Primary:disabled {{ background:{c['panel2']}; border-color:{c['rule']}; color:{c['grey']}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{ background:{c['panel']}; border:1px solid {c['rule']};
  border-radius:3px; padding:4px; selection-background-color:{c['select']}; selection-color:{c['text']}; }}
QComboBox:disabled {{ color:{c['muted']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color:{c['accent']}; }}
QComboBox QAbstractItemView {{ background:{c['panel']}; selection-background-color:{c['select']}; }}
QTableView, QTreeView, QListView, QTextBrowser {{ background:{c['panel']}; border:1px solid {c['rule']};
  gridline-color:{c['rule']}; selection-background-color:{c['select']}; selection-color:{c['text']};
  alternate-background-color:{c['panel2']}; }}
QHeaderView::section {{ background:{c['panel2']}; border:none; border-right:1px solid {c['rule']};
  border-bottom:1px solid {c['rule']}; padding:4px 6px; color:{c['muted']}; }}
QTabWidget::pane {{ border:1px solid {c['rule']}; background:{c['panel']}; }}
QTabBar::tab {{ background:{c['panel2']}; padding:6px 14px; border:1px solid {c['rule']}; border-bottom:none; }}
QTabBar::tab:selected {{ background:{c['panel']}; border-top:2px solid {c['accent']}; }}
QProgressBar {{ background:{c['panel2']}; border:1px solid {c['rule']}; border-radius:3px; text-align:center; height:14px; }}
QProgressBar::chunk {{ background:{c['accent']}; }}
QSplitter::handle {{ background:{c['rule']}; }}
QScrollBar:vertical {{ background:{c['base']}; width:11px; }} QScrollBar:horizontal {{ background:{c['base']}; height:11px; }}
QScrollBar::handle {{ background:{c['rule']}; border-radius:4px; min-height:24px; min-width:24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
QToolTip {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['rule']}; padding:4px; }}
QStatusBar {{ background:{c['panel']}; border-top:1px solid {c['rule']}; }}
QCheckBox::indicator {{ width:14px; height:14px; }}
"""


def apply(app, mode: str) -> None:
    set_mode(mode)
    app.setPalette(palette())
    app.setStyleSheet(qss())


def icon_path():
    """Icona del programma: accanto al pacchetto (sorgenti) o nella cartella dell'eseguibile (PyInstaller)."""
    import sys
    from pathlib import Path
    for base in (Path(__file__).parent, Path(getattr(sys, "_MEIPASS", "")) / "fvp" / "ui"):
        p = base / "assets" / "fvp.ico"
        if p.is_file():
            return p
    return None


def app_icon():
    from PySide6.QtGui import QIcon
    p = icon_path()
    return QIcon(str(p)) if p else QIcon()
