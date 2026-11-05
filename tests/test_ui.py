"""Interfaccia (offscreen): flusso obbligatorio, tema, caricamento, pagine."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv("FVP_HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    from fvp.core.config import Settings
    from fvp.ui import theme
    from fvp.ui.main_window import MainWindow
    from fvp.ui.state import AppState
    app = QApplication.instance() or QApplication([])
    s = Settings(operator="tester")
    theme.apply(app, s.ui_theme)
    st = AppState(s)
    w = MainWindow(st)
    yield app, st, w
    w.close()


def _wait(app, st):
    import time
    t = time.time()
    while st.busy and time.time() - t < 300:
        app.processEvents()
        time.sleep(0.02)


def test_case_first_flow(ui):
    from PySide6.QtCore import Qt

    from fvp.ui.main_window import ALWAYS, NAV
    app, st, w = ui
    assert NAV[0] == "Case Management" and w.current_name() == "Case Management"
    for name in NAV:
        enabled = bool(w.items[name].flags() & Qt.ItemFlag.ItemIsEnabled)
        assert enabled == (name in ALWAYS)
    w.go_to("Image Forensics")
    assert w.current_name() == "Case Management"         # non raggiungibile senza caso
    cp = w.pages["Case Management"]
    cp.cid.setText("UI-1")
    cp.ctitle.setText("prova")
    cp._create()
    app.processEvents()
    assert st.case is not None and w.current_name() == "Carica e analizza"
    assert all(w.items[n].flags() & Qt.ItemFlag.ItemIsEnabled for n in NAV)
    cp._close_case()
    app.processEvents()
    assert st.case is None and w.current_name() == "Case Management"


def test_theme_toggle(ui):
    from fvp.ui import theme
    app, st, w = ui
    assert st.settings.ui_theme == "light" and theme.C["base"] == theme.LIGHT["base"]
    w.toggle_theme()
    assert st.settings.ui_theme == "dark" and theme.C["base"] == theme.DARK["base"]
    assert theme.DARK["base"] in app.styleSheet()
    w.toggle_theme()
    assert theme.C["base"] == theme.LIGHT["base"]


def test_load_single_and_folder(ui, dataset, tmp_path):
    import shutil
    app, st, w = ui
    cp = w.pages["Case Management"]
    cp.cid.setText("UI-2")
    cp.ctitle.setText("caricamento")
    cp._create()
    lp = w.pages["Carica e analizza"]
    lp.preset.setCurrentText("Rapida: struttura, metadati, tempi, ELA")
    lp._add_paths([dataset / "original.jpg"])
    folder = tmp_path / "cartella"
    (folder / "sub").mkdir(parents=True)
    shutil.copy(dataset / "clean.png", folder / "a.png")
    shutil.copy(dataset / "renamed_jpeg.png", folder / "sub" / "b.png")
    (folder / "note.txt").write_text("non è un'immagine")
    lp._add_paths([folder])
    assert len(lp.queue) == 3                            # il .txt è escluso dal filtro sui magic bytes
    lp._start()
    _wait(app, st)
    assert all(q["status"].startswith("analizzato") for q in lp.queue), [q["status"] for q in lp.queue]
    assert len(st.case.exhibits()) == 3


def test_all_pages_render(ui, dataset):
    from fvp.core.pipeline import analyze_exhibit
    from fvp.ui.main_window import NAV
    app, st, w = ui
    cp = w.pages["Case Management"]
    cp.cid.setText("UI-3")
    cp.ctitle.setText("pagine")
    cp._create()
    c = st.case
    for n in ("original.jpg", "stego_text.png"):
        ex = c.acquire(dataset / n, "tester")
        analyze_exhibit(c, ex.id, "tester", st.settings)
    st.set_case(c)
    for name in NAV:
        w.go_to(name)
        app.processEvents()
    st.set_exhibit("EXH-0001")
    hp = w.pages["Hex Viewer"]
    hp._open_exhibit()
    hp.mode.setCurrentText("ASCII")
    hp.query.setText("Exif")
    hp._find()
    a, n = hp.hex.selection()
    assert n == 4 and hp.hex.data(a, 4) == b"Exif"
    tags = c.analyses("EXH-0001")[-1]["results"]["metadata"]["tags"]
    w.go_to("Metadata Analyzer")
    assert w.pages["Metadata Analyzer"].table.rowCount() == len(tags) > 10
    st.set_exhibit("EXH-0002")
    w.go_to("Steganalysis")
    sp = w.pages["Steganalysis"]
    assert sp.hits.rowCount() >= 1
    sp.hits.selectRow(0)
    sp._open_hit()
    assert w.current_name() == "Hex Viewer" and hp.hex.data(0, 9) == b"Incontro "
    w.go_to("Steganalysis")
    sp.chan.setCurrentIndex(0)
    sp.bit.setValue(0)
    assert not sp.sync.views[1].item.pixmap().isNull()
