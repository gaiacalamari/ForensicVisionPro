"""Integrazione: l'intera pipeline sul dataset a verità nota (MANIFEST.json)."""
import html as html_mod
import json
import os

import pytest
from conftest import HAS_EXIFTOOL, HAS_FFMPEG

from fvp.cases.store import Case
from fvp.core.findings import Category, Status
from fvp.core.pipeline import analyze_exhibit
from fvp.reporting import report
from fvp.ui.widgets.findings_view import status_for


@pytest.fixture(scope="module")
def analysed(dataset, manifest, tmp_path_factory):
    c = Case.create(tmp_path_factory.mktemp("c"), "INT-1", "integrazione", "tester")
    out = {}
    for name in manifest:
        ex = c.acquire(dataset / name, "tester")
        analyze_exhibit(c, ex.id, "tester")
        out[name] = (ex, c.analyses(ex.id)[-1])
    yield c, out
    c.close()


def test_expected_findings(analysed, manifest):
    _c, out = analysed
    for name, exp in manifest.items():
        if not isinstance(exp["expect"], list):
            continue
        if name.startswith("video") and not HAS_FFMPEG:
            continue
        if name == "edited_photoshop.jpg" and not HAS_EXIFTOOL:
            continue
        got = " | ".join(f.title for f in out[name][1]["findings"])
        for e in exp["expect"]:
            assert e in got, f"{name}: atteso '{e}' in: {got}"


def test_clean_files_have_no_significant_findings(analysed):
    _c, out = analysed
    for name in ("original.jpg", "clean.png", "natural.png", "audio_clean.wav", "screen_text.jpg"):
        sig = [f.title for f in out[name][1]["findings"] if f.significant]
        assert not sig, f"{name}: {sig}"


def test_integrity_pre_post(analysed):
    _c, out = analysed
    for ex, an in out.values():
        assert an["integrity_ok"] and an["pre_hashes"] == an["post_hashes"] == ex.working_hashes


def test_no_module_crash_on_valid_files(analysed):
    _c, out = analysed
    for name, (_ex, an) in out.items():
        if name in ("truncated.jpg", "bad_crc.png", "video_truncated.mp4"):
            continue
        crashed = [f.description for f in an["findings"] if f.title.startswith("Modulo ")]
        assert not crashed, f"{name}: {crashed}"


def test_ai_category_grey_without_indicators(analysed):
    _c, out = analysed
    assert status_for(out["original.jpg"][1])[Category.AI_GENERATION] == Status.GREY
    assert status_for(out["ai_params.png"][1])[Category.AI_GENERATION] == Status.RED
    assert status_for(out["original.jpg"][1])[Category.DEEPFAKE] == Status.GREY


def test_reports(analysed, tmp_path, manifest):
    import re
    c, out = analysed
    c.add_note("EXH-0001", "tester", "valutazione <b>operatore</b>")
    p = report.write_html(c, tmp_path / "r.html")
    h = p.read_text(encoding="utf-8")
    assert "Valutazioni dell'operatore" in h and "&lt;b&gt;operatore&lt;/b&gt;" in h   # testo sempre escapato
    assert "Catena di custodia" in h and "Metodo e limiti" in h and "Glossario" in h
    assert "<h2 style='margin-top:18px'>Sintesi</h2>" in h and "id='attenzione'" in h
    secret = manifest["stego_bgr_len8.bmp"]["secret"]
    assert html_mod.escape(secret, quote=True) in h            # il messaggio nascosto compare in chiaro nel report
    # ogni pulsante "Dettagli" porta a un controllo esistente
    targets = set(re.findall(r"href='#(f-[^']+)'", h))
    ids = set(re.findall(r"id='(f-[^']+)'", h))
    assert targets and targets <= ids
    maps = set(re.findall(r"href='#(map-[^']+)'", h))
    assert maps <= set(re.findall(r"id='(map-[^']+)'", h))
    assert p.stat().st_size < 25 * 1024 * 1024
    j = json.loads(report.write_json(c, tmp_path / "r.json").read_text(encoding="utf-8"))
    assert j["audit_verification"]["ok"] and len(j["exhibits"]) >= 10
    assert report.write_csv_findings(c, tmp_path / "r.csv").stat().st_size > 0
    assert c.audit.entries()[-1]["action"] == "report_generato"
    assert c.audit.verify().ok


def test_working_copies_untouched_and_readonly(analysed):
    _c, out = analysed
    for ex, _ in out.values():
        assert not os.access(ex.working_path, os.W_OK) or os.geteuid() == 0



def test_plain_language_summaries(analysed):
    from fvp.core import explain
    c, out = analysed
    pairs = [(ex, an) for ex, an in out.values()]
    cs = explain.case_summary(pairs)
    assert "This is a very secret message!" in cs["text"]
    assert cs["hidden_files"] >= 5 and cs["integrity_ok"]
    ex, an = out["stego_bgr_len8.bmp"]
    s = explain.exhibit_summary(ex, an)
    assert "immagine BMP" in s and "This is a very secret message!" in s
    ex, an = out["natural.png"]
    assert "non hanno evidenziato elementi da segnalare" in explain.exhibit_summary(ex, an)
    # ogni elemento da verificare del dataset ha una spiegazione semplice dedicata
    missing = {f.title for _e, a in pairs if a for f in explain.attention(a["findings"]) if not explain.rule_for(f)}
    assert not missing, missing
