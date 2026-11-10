"""Interfaccia (offscreen): flusso obbligatorio, tema, caricamento, pagine."""
import os
from pathlib import Path

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
    s = Settings(operator="tester", ui_simple=False)      # vista esperta: tutte le pagine nel menu
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


def test_load_accepts_video_and_audio(ui, dataset, tmp_path):
    """I video e l'audio sono acquisiti con il filtro predefinito; i file non multimediali restano esclusi."""
    import shutil
    import wave

    import cv2
    import numpy as np
    app, st, w = ui
    cp = w.pages["Case Management"]
    cp.cid.setText("UI-VIDEO")
    cp.ctitle.setText("video")
    cp._create()
    lp = w.pages["Carica e analizza"]
    assert lp.only_img.isChecked()
    vid = tmp_path / "clip.avi"
    vw = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for i in range(10):
        vw.write(np.full((48, 64, 3), i * 20, np.uint8))
    vw.release()
    wav = tmp_path / "voce.wav"
    with wave.open(str(wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 800)
    (tmp_path / "note.txt").write_text("non multimediale")
    shutil.copy(dataset / "original.jpg", tmp_path / "foto.jpg")
    assert lp.checks["pose"].isChecked() and lp.checks["sports2d"].isChecked()   # Completa analizza tutto
    lp.preset.setCurrentText("Completa senza stima della posa (più rapida)")
    lp._add_paths([vid, wav, tmp_path / "note.txt", tmp_path / "foto.jpg"])
    kinds = {Path(q["path"]).name: q["kind"] for q in lp.queue}
    assert kinds == {"clip.avi": "video", "voce.wav": "audio", "foto.jpg": "immagine"}
    assert "Persone e movimento" in lp.msg.text()       # suggerimento per l'analisi dei movimenti
    lp.preset.setCurrentText("Persone e movimento (video)")
    assert lp.checks["pose"].isChecked() and lp.checks["video"].isChecked()


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


def test_pose_page(ui, tmp_path, monkeypatch):
    from test_pose import FakeEstimator, make_video

    from fvp.core.pipeline import analyze_exhibit
    from fvp.engines import pose_model
    monkeypatch.setattr(pose_model, "load", lambda *a, **k: FakeEstimator())
    app, st, w = ui
    cp = w.pages["Case Management"]
    cp.cid.setText("UI-POSE")
    cp.ctitle.setText("posa")
    cp._create()
    c = st.case
    ex = c.acquire(make_video(tmp_path / "taglio.avi", cut=40), "tester")
    analyze_exhibit(c, ex.id, "tester", st.settings, ["integrity", "signature", "pose"])
    st.set_case(c)
    st.set_exhibit(ex.id)
    w.go_to("Human Pose")
    app.processEvents()
    pp = w.pages["Human Pose"]
    assert w.current_name() == "Human Pose"
    assert pp.trans.rowCount() == 1 and pp.trans.item(0, 0).text() == "40" and pp.trans.item(0, 2).text() == "scena"
    assert pp.persons.rowCount() >= 1 and pp.angles.rowCount() > 10 and pp.exports.rowCount() >= 4
    assert pp.art_combo.count() == 4 and not pp.view.item.pixmap().isNull()   # + grafico degli angoli
    assert "discontinuità di scena" in pp.status.text()


def test_credits_dialog(ui):
    app, st, w = ui
    w.go_to("Settings")
    sp = w.pages["Settings"]
    sp._credits()
    app.processEvents()
    txt = sp._credits_dialog.findChild(__import__("PySide6.QtWidgets", fromlist=["QTextBrowser"]).QTextBrowser).toPlainText()
    assert "Phil Harvey" in txt and "Sports2D" in txt
    sp._credits_dialog.close()


# ------------------------------------------------------------------ vista semplice

@pytest.fixture
def simple_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("FVP_HOME", str(tmp_path))
    from PySide6.QtWidgets import QApplication

    from fvp.core.config import Settings
    from fvp.ui.main_window import MainWindow
    from fvp.ui.state import AppState
    app = QApplication.instance() or QApplication([])
    st = AppState(Settings(operator="tester"))
    w = MainWindow(st)
    yield app, st, w
    w.close()


def test_simple_view_is_default_and_minimal(simple_ui):
    from fvp.core.config import Settings
    from fvp.ui.main_window import SIMPLE_LABELS
    app, st, w = simple_ui
    assert Settings().ui_simple and w.simple
    assert set(w.items) == set(SIMPLE_LABELS)                       # solo i passi essenziali nel menu
    assert w.items["Case Management"].text().startswith("1")
    assert w.mode_btn.text() == "Passa alla vista esperta" and not w.strict.isVisible()
    for name, pg in w.pages.items():                                 # guida completa nascosta, frase breve visibile
        assert not pg.help_box.isVisibleTo(pg)
        if pg.intro:
            assert pg.help_btn.isVisibleTo(pg)
            pg.help_btn.setChecked(True)
            assert pg.help_box.isVisibleTo(pg) and pg.help_box.text() == pg.intro
            pg.help_btn.setChecked(False)
        assert len(pg.lead) <= 140, name
    lp = w.pages["Carica e analizza"]
    assert not lp.adv.isVisibleTo(lp) and not lp.only_img.isVisibleTo(lp)
    lp.adv_btn.setChecked(True)
    assert lp.adv.isVisibleTo(lp)
    dp = w.pages["Dashboard"]
    assert not dp.fv.isVisibleTo(dp) and not dp.activity_box.isVisibleTo(dp)


def test_simple_view_switch_and_hidden_pages(simple_ui, tmp_path):
    app, st, w = simple_ui
    cp = w.pages["Case Management"]
    cp.cid.setText("S-1")
    cp.ctitle.setText("semplice")
    cp._create()
    app.processEvents()
    assert w.current_name() == "Carica e analizza"
    w.go_to("Image Forensics")                      # non è nel menu semplice ma i pulsanti "Apri vista" la aprono
    assert w.current_name() == "Image Forensics" and w.current_page() is w.pages["Image Forensics"]
    w.toggle_mode()
    assert not w.simple and "Image Forensics" in w.items and w.current_name() == "Image Forensics"
    assert w.pages["Carica e analizza"].adv.isVisibleTo(w.pages["Carica e analizza"])
    pp = w.pages["Human Pose"]
    assert pp.tabs.isTabVisible(pp.tabs.indexOf(pp.engine))
    w.toggle_mode()
    assert w.simple and not pp.tabs.isTabVisible(pp.tabs.indexOf(pp.engine))
    from fvp.core.config import Settings
    assert Settings.load().ui_simple                # la scelta resta salvata


# ------------------------------------------------------------------ icona e riepilogo

def test_program_icon(ui):
    """Icona del programma (foto con lente d'ingrandimento) in tutti i formati, usata da eseguibile, installer e
    finestra; è quella prodotta da tools/make_icon.py."""
    from PIL import Image

    from fvp.ui.theme import icon_path
    app, st, w = ui
    root = Path(__file__).resolve().parents[1]
    p = icon_path()
    assert p and {16, 32, 48, 256} <= {sz[0] for sz in Image.open(p).info["sizes"]}
    im = Image.open(p)
    im.size = (256, 256)
    im.load()
    assert im.getpixel((5, 250))[3] == 0                         # angolo trasparente: niente quadrato bianco
    spec = (root / "packaging" / "fvp.spec").read_text(encoding="utf-8")
    assert "icon=str(ICON)" in spec and 'raise SystemExit(f"Icona mancante' in spec
    assert "SetupIconFile=..\\src\\fvp\\ui\\assets\\fvp.ico" in (root / "packaging" / "installer.iss").read_text(
        encoding="utf-8")
    assert not w.windowIcon().isNull()


def test_dashboard_details_on_the_right(ui, dataset):
    import shutil
    app, st, w = ui
    cp = w.pages["Case Management"]
    cp.cid.setText("UI-DET")
    cp.ctitle.setText("dettagli")
    cp._create()
    from fvp.core.pipeline import analyze_exhibit
    ex = st.case.acquire(dataset / "double_compressed.jpg", "tester")
    from fvp.ui.pages.load_page import PRESETS
    analyze_exhibit(st.case, ex.id, "tester", st.settings,
                    ["integrity"] + PRESETS["Completa senza stima della posa (più rapida)"])
    st.set_exhibit(ex.id)
    st.analysis_changed.emit()
    dp = w.pages["Dashboard"]
    dp.set_simple(True)
    dp.refresh()
    assert not dp.fv.isVisibleTo(dp)                              # elenco chiuso…
    assert dp.fv.detail.isVisibleTo(dp)                           # …ma i dettagli sono a destra
    assert dp.fv.detail.parent() is not dp.fv                     # non sotto la tabella
    from fvp.core import explain
    first = explain.attention(st.last_analysis()["findings"])[0]
    assert first.title in dp.fv.detail.toPlainText()             # primo punto da verificare già aperto
    f = next(x for x in dp.fv.findings if x.level.value == "informativo")
    dp.fv.select(f.id)
    assert f.title in dp.fv.detail.toPlainText()


def test_pages_scroll_instead_of_overlapping(simple_ui, dataset, tmp_path):
    """Con la finestra piccola (portatile, Windows al 150%) le pagine scorrono: nessun widget viene compresso sotto
    la sua dimensione minima, che è ciò che sovrapponeva i testi."""
    from fvp.core import explain
    from fvp.core.pipeline import analyze_exhibit
    from fvp.ui.main_window import NAV
    from fvp.ui.pages.load_page import PRESETS
    app, st, w = simple_ui
    w.show()
    w.resize(980, 600)
    cp = w.pages["Case Management"]
    cp.cid.setText("S-SCROLL")
    cp.ctitle.setText("finestra piccola")
    cp._create()
    ex = st.case.acquire(dataset / "double_compressed.jpg", "tester")
    analyze_exhibit(st.case, ex.id, "tester", st.settings,
                    ["integrity"] + PRESETS["Completa senza stima della posa (più rapida)"])
    st.set_exhibit(ex.id)
    st.analysis_changed.emit()
    for simple in (True, False):
        for name in NAV:
            w.go_to(name)
            for _ in range(5):
                app.processEvents()
            pg, m = w.pages[name], w.pages[name].minimumSizeHint()
            assert w.scrolls[name].widget() is pg
            assert pg.height() >= m.height() - 1 and pg.width() >= m.width() - 1, (name, pg.size(), m)
        w.toggle_mode()
    # "Apri vista" da Leggi i risultati porta alla pagina giusta anche se non è nel menu della vista semplice
    f = explain.attention(st.last_analysis()["findings"])[0]
    w.go_to("Dashboard")
    w.pages["Dashboard"]._open(explain.related_page(f), explain.related_map(f) or "")
    assert w.current_page() is w.pages[explain.related_page(f)]


def test_pose_open_view_shows_images_tab(ui, tmp_path, monkeypatch):
    """"Apri vista" su una discontinuità apre la scheda Immagini (prima apriva quella sbagliata)."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from test_pose import FakeEstimator, make_video

    from fvp.core.pipeline import analyze_exhibit
    from fvp.engines import pose_model as M
    app, st, w = ui
    monkeypatch.setattr(M, "load", lambda *a, **k: FakeEstimator())
    cp = w.pages["Case Management"]
    cp.cid.setText("POSE-VIEW")
    cp.ctitle.setText("vista")
    cp._create()
    ex = st.case.acquire(make_video(tmp_path / "cut.avi", n=50, cut=25), "tester")
    analyze_exhibit(st.case, ex.id, "tester", st.settings, ["integrity", "signature", "pose"])
    st.set_exhibit(ex.id)
    st.analysis_changed.emit()
    w.pages["Dashboard"]._open("Human Pose", "pose_jumps")
    pp = w.pages["Human Pose"]
    assert pp.tabs.currentWidget() is pp.imgs_tab and pp.art_combo.currentData() == "pose_jumps"
