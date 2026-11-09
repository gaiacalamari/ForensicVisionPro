"""Video annotato e grafici degli angoli (stile Sports2D), lettura .mot/.trc, esecuzione di Sports2D/Pose2Sim originali
in un ambiente separato (simulato con un pacchetto finto) e pagine che mostrano tutti i dati."""
import hashlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import cv2
import numpy as np
import pytest

from fvp.core.findings import Category, Level
from fvp.engines import pose as P
from fvp.engines import pose_model as M
from fvp.engines import sports2d_ext as S
from test_pose import FakeEstimator, make_video


# ------------------------------------------------------------------ video annotato e angoli

def test_annotated_video_and_angle_plots(tmp_path):
    v = make_video(tmp_path / "v.avi", n=40, people=2)
    res, _fs = P.analyze(v, "video", tmp_path / "out", estimator=FakeEstimator())
    vid = res["artifacts"]["pose_video"]
    cap = cv2.VideoCapture(vid)
    assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == res["frames"]["analyzed"]
    cap.release()
    assert res["exports"]["pose_overlay.mp4"]["sha256"] == hashlib.sha256(open(vid, "rb").read()).hexdigest()
    assert Path(res["artifacts"]["pose_angles"]).is_file()
    for p in res["persons"]:
        assert p["mot"] in res["exports"] and p["trc"] in res["exports"] and p["angles_plot"] in res["exports"]
        t, cols = P.read_mot(res["exports"][p["mot"]]["path"])
        assert len(t) >= 30 and "right knee" in cols and np.isfinite(cols["right knee"]).any()
        tt, names, xyz = P.read_trc(res["exports"][p["trc"]]["path"])
        assert names == P.HALPE26 and xyz.shape == (len(tt), 26, 3)


def test_annotated_video_can_be_disabled(tmp_path):
    class S_:
        pose_max_frames, pose_frame_step, pose_det_every, pose_annotated_video = 100, 1, 4, False
    res, _ = P.analyze(make_video(tmp_path / "v.avi", n=20), "video", tmp_path / "o", settings=S_(),
                       estimator=FakeEstimator())
    assert "pose_video" not in res["artifacts"]


def test_read_mot_sports2d_format(tmp_path):
    f = tmp_path / "x_angles_person00.mot"
    f.write_text("Coords\nversion=1\nnRows=2\nnColumns=3\ninDegrees=yes\n\nUnits are S.I.\nendheader\n"
                 "time\tright_knee\ttrunk\n0.0\t170.5\t3.1\n0.04\tnan\t3.3\n", encoding="utf-8")
    t, cols = P.read_mot(f)
    assert list(t) == [0.0, 0.04] and cols["right knee"][0] == 170.5 and np.isnan(cols["right knee"][1])


# ------------------------------------------------------------------ Sports2D originale (ambiente finto)

FAKE_S2D = '''
import argparse, shutil, sys
from pathlib import Path

def main():
    ap = argparse.ArgumentParser()
    for a in ("video_dir", "result_dir", "nb_persons_to_detect", "person_ordering_method", "show_realtime_results",
              "show_graphs", "save_vid", "save_img", "save_pose", "calculate_angles", "save_angles", "mode",
              "to_meters", "do_ik", "first_person_height", "default_height", "do_augmentation", "use_simple_model"):
        ap.add_argument("--" + a)
    ap.add_argument("--video_input", nargs="*")
    ap.add_argument("--participant_mass", nargs="*")
    a = ap.parse_args()
    assert a.show_realtime_results == "false" and a.show_graphs == "false"
    src = Path(a.video_dir) / a.video_input[0]
    out = Path(a.result_dir) / (src.stem + "_Sports2D")
    out.mkdir(parents=True)
    shutil.copyfile(src, out / (src.stem + "_Sports2D.avi"))
    (out / (src.stem + "_Sports2D_angles_person00.mot")).write_text(
        "x\\nversion=1\\nendheader\\ntime\\tright_knee\\n0.0\\t170\\n0.04\\t165\\n")
    (out / (src.stem + "_Sports2D_px_person00.trc")).write_text("PathFileType\\t4\\n")
    if a.do_ik == "true":          # come Sports2D: modello scalato e movimento IK nella cartella dei risultati
        assert a.to_meters == "true" and float(a.first_person_height) > 0
        (out / (src.stem + "_Sports2D_m_person00_scaled.osim")).write_text("<OpenSimDocument/>")
        (out / (src.stem + "_Sports2D_m_person00_ik.mot")).write_text(
            "Coordinates\\nversion=1\\ninDegrees=yes\\nendheader\\ntime\\tknee_angle_r\\tpelvis_tx\\n"
            "0.0\\t-5.0\\t0.1\\n0.04\\t-12.0\\t0.12\\n")
    print("Sports2D finto: argomenti", sys.argv[1:])
    import os, stat
    print("input in sola lettura:", "ok" if not os.stat(src).st_mode & stat.S_IWRITE else "NO")
    if os.environ.get("FAKE_S2D_TAMPER") == "1":
        os.chmod(src, stat.S_IWRITE | stat.S_IREAD)
        src.write_bytes(b"alterato")

if __name__ == "__main__":
    main()
'''


@pytest.fixture(scope="module")
def fake_env(tmp_path_factory):
    d = tmp_path_factory.mktemp("s2denv")
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(d)], check=True)
    py = S._env_python(d)
    site = Path(subprocess.run([str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                               capture_output=True, text=True, check=True).stdout.strip())
    (site / "Sports2D").mkdir(parents=True, exist_ok=True)
    (site / "Sports2D" / "__init__.py").write_text("")
    (site / "Sports2D" / "Sports2D.py").write_text(textwrap.dedent(FAKE_S2D))
    for name, ver in (("sports2d", "0.8.34"), ("pose2sim", "0.10.49"), ("opensim", "4.6")):
        di = site / f"{name}-{ver}.dist-info"
        di.mkdir(exist_ok=True)
        (di / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {ver}\n")
    return py


class Cfg:
    sports2d_timeout_s = 120
    sports2d_person_height_m = 0.0
    sports2d_person_mass_kg = 0.0
    sports2d_opensim = False
    sports2d_simple_model = False

    def __init__(self, py):
        self.sports2d_python = str(py)


def test_sports2d_command(tmp_path):
    arg = lambda c, k: c[c.index(k) + 1]  # noqa: E731
    cmd = S.build_command(Path("py"), tmp_path / "reperto.mp4", tmp_path / "r", Cfg("py"))   # OpenSim disattivato
    assert arg(cmd, "--to_meters") == "false" and "--first_person_height" not in cmd
    c = Cfg("py")
    c.sports2d_opensim = True                                   # predefinito: modello OpenSim, statura presunta
    cmd = S.build_command(Path("py"), tmp_path / "reperto.mp4", tmp_path / "r", c)
    assert arg(cmd, "--do_ik") == "true" and arg(cmd, "--to_meters") == "true"
    assert arg(cmd, "--first_person_height") == "1.7" and "--participant_mass" not in cmd
    assert S.height_for(c) == (1.7, True)
    c.sports2d_person_height_m, c.sports2d_person_mass_kg, c.sports2d_simple_model = 1.82, 80, True
    cmd = S.build_command(Path("py"), tmp_path / "reperto.mp4", tmp_path / "r", c)
    assert arg(cmd, "--first_person_height") == "1.82" and arg(cmd, "--participant_mass") == "80"
    assert arg(cmd, "--use_simple_model") == "true" and S.height_for(c) == (1.82, False)
    from fvp.core.config import Settings
    assert Settings().sports2d_opensim                          # l'utente vuole il .osim di default


def test_sports2d_status_and_run(fake_env, tmp_path):
    st = S.status(Cfg(fake_env))
    assert st["ok"] and st["versions"]["sports2d"] == "0.8.34" and st["versions"]["pose2sim"] == "0.10.49"
    v = make_video(tmp_path / "clip.avi", n=10)
    sha = hashlib.sha256(v.read_bytes()).hexdigest()
    res, fs = S.run(v, tmp_path / "out", Cfg(fake_env), expected_sha256=sha)
    assert res["returncode"] == 0 and res["input"]["sha256"] == sha
    assert res["video"].endswith("_Sports2D.avi") and len(res["mot"]) == 1 and len(res["trc"]) == 1
    for e in res["outputs"].values():
        assert hashlib.sha256(open(e["path"], "rb").read()).hexdigest() == e["sha256"]
    log = Path(res["log"]["path"]).read_text(encoding="utf-8")
    assert "input in sola lettura: ok" in log and "--to_meters false" in log
    assert fs[0].level == Level.INFO and fs[0].title.startswith("Sports2D originale eseguito")
    assert hashlib.sha256(v.read_bytes()).hexdigest() == sha          # il file analizzato non cambia
    t, cols = P.read_mot(res["mot"][0])
    assert list(cols["right knee"]) == [170.0, 165.0]


def test_sports2d_opensim_model(fake_env, tmp_path):
    c = Cfg(fake_env)
    c.sports2d_opensim = True
    v = make_video(tmp_path / "clip.avi", n=10)
    res, fs = S.run(v, tmp_path / "out", c)
    osm = res["opensim"]
    assert osm["requested"] and osm["height_assumed"] and osm["height_m"] == 1.7 and osm["opensim_version"] == "4.6"
    assert len(osm["model"]) == 1 and osm["model"][0].endswith(".osim") and osm["motion"][0].endswith("_ik.mot")
    assert osm["motion"][0] not in res["mot"]                  # gli angoli Sports2D restano separati dall'IK
    readme = Path(osm["model"][0]).parent / "LEGGIMI_OpenSim.txt"
    assert "Load Motion" in readme.read_text(encoding="utf-8") and "presunta" not in res["command"]
    assert any(e["rel"].endswith("LEGGIMI_OpenSim.txt") for e in res["outputs"].values())
    f = next(x for x in fs if x.title.startswith("Modello OpenSim creato"))
    assert f.level == Level.INFO and "non documentata" in f.limitations and ".osim" in f.evidence
    t, cols = P.read_mot(osm["motion"][0])
    assert list(cols["knee angle r"]) == [-5.0, -12.0]


def test_sports2d_tampering_is_reported(fake_env, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_S2D_TAMPER", "1")
    v = make_video(tmp_path / "clip.avi", n=5)
    res, fs = S.run(v, tmp_path / "out", Cfg(fake_env))
    assert any(f.title == "Sports2D ha modificato il file di input" and f.level == Level.UNDETERMINED for f in fs)


def test_sports2d_rejects_mismatching_input(fake_env, tmp_path):
    v = make_video(tmp_path / "clip.avi", n=5)
    with pytest.raises(RuntimeError):
        S.run(v, tmp_path / "out", Cfg(fake_env), expected_sha256="0" * 64)


def test_pipeline_sports2d(case, tmp_path, fake_env, monkeypatch):
    from fvp.core.config import Settings
    from fvp.core.pipeline import analyze_exhibit
    monkeypatch.setattr(M, "load", lambda *a, **k: FakeEstimator())
    ex = case.acquire(make_video(tmp_path / "cut.avi", n=50, cut=25), "tester")
    s = Settings(sports2d_python=str(fake_env))           # OpenSim attivo di default
    aid = analyze_exhibit(case, ex.id, "tester", s, ["integrity", "signature", "pose", "sports2d"])
    an = next(a for a in case.analyses(ex.id) if a["id"] == aid)
    r = an["results"]
    assert "sports2d" in r["executed"] and r["sports2d"]["returncode"] == 0
    assert an["tools"]["sports2d_env_sports2d"] == "0.8.34" and an["integrity_ok"]
    assert "pose_video" in r["artifacts"]
    assert r["sports2d"]["opensim"]["model"] and any(x.title.startswith("Modello OpenSim creato")
                                                     for x in an["findings"])


def test_pipeline_sports2d_missing_is_informative(case, tmp_path, monkeypatch):
    from fvp.core.config import Settings
    from fvp.core.pipeline import analyze_exhibit
    monkeypatch.setenv("FVP_HOME", str(tmp_path / "home"))
    ex = case.acquire(make_video(tmp_path / "v.avi", n=5), "tester")
    aid = analyze_exhibit(case, ex.id, "tester", Settings(), ["integrity", "signature", "sports2d"])
    an = next(a for a in case.analyses(ex.id) if a["id"] == aid)
    f = next(x for x in an["findings"] if x.module == "sports2d")
    assert f.level == Level.INFO and "non installati" in f.title
    assert Category.HUMAN_POSE.value not in an["results"]["executed_categories"]


# ------------------------------------------------------------------ interfaccia

@pytest.fixture
def ui(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
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


def _analyzed_video(st, w, tmp_path, monkeypatch):
    from fvp.core.pipeline import analyze_exhibit
    monkeypatch.setattr(M, "load", lambda *a, **k: FakeEstimator())
    cp = w.pages["Case Management"]
    cp.cid.setText("MOV-1")
    cp.ctitle.setText("movimento")
    cp._create()
    ex = st.case.acquire(make_video(tmp_path / "cut.avi", n=50, cut=25, people=2), "tester")
    analyze_exhibit(st.case, ex.id, "tester", st.settings,
                    ["integrity", "signature", "structure", "metadata", "timestamps", "video", "pose"])
    st.set_exhibit(ex.id)
    st.analysis_changed.emit()
    return ex


def test_pose_page_video_and_chart(ui, tmp_path, monkeypatch):
    app, st, w = ui
    _analyzed_video(st, w, tmp_path, monkeypatch)
    pp = w.pages["Human Pose"]
    pp.refresh()
    assert pp.src.count() == 1 and pp.player.count > 0
    assert pp.person.count() >= 2 and pp.angle_list.count() > 5
    assert pp.chart.visible and len(pp.chart.times) > 10 and pp.chart.marks      # discontinuità sul grafico
    pp.player.seek_frame(10)
    assert abs(pp.chart.cursor - 10 / pp.player.fps) < 1e-6
    pp.chart.seek.emit(1.0)
    assert pp.player.index == int(round(1.0 * pp.player.fps))
    pp.chart.grab()                                        # il disegno non solleva eccezioni
    pp.player.grab()


def test_pose_page_rerun_keeps_other_modules(ui, tmp_path, monkeypatch):
    app, st, w = ui
    _analyzed_video(st, w, tmp_path, monkeypatch)
    before = set(st.last_analysis()["modules"])
    pp = w.pages["Human Pose"]
    pp._run()
    import time
    t = time.time()
    while st.busy and time.time() - t < 120:
        app.processEvents()
        time.sleep(0.02)
    assert before <= set(st.last_analysis()["modules"])


def test_all_data_page_shows_everything(ui, tmp_path, monkeypatch):
    app, st, w = ui
    _analyzed_video(st, w, tmp_path, monkeypatch)
    pg = w.pages["All Data"]
    pg.refresh()
    tops = [pg.tree.topLevelItem(i).text(0) for i in range(pg.tree.topLevelItemCount())]
    assert tops[0] == "Anomalie e punti di attenzione"
    for t in ("Tutti i risultati dei moduli", "Integrità e acquisizione", "Persone e movimento (Forensic Vision Pro)",
              "Formato del file", "Strumenti e versioni"):
        assert t in tops, tops
    assert pg.tree.topLevelItem(0).childCount() >= 1
    pg.search.setText("pose_overlay.mp4")
    visible = [pg.tree.topLevelItem(i).text(0) for i in range(pg.tree.topLevelItemCount())
               if not pg.tree.topLevelItem(i).isHidden()]
    assert "Persone e movimento (Forensic Vision Pro)" in visible and "Integrità e acquisizione" not in visible


def test_pose_page_opensim_source_and_button(ui, tmp_path, monkeypatch, fake_env):
    from fvp.core.pipeline import analyze_exhibit
    app, st, w = ui
    monkeypatch.setattr(M, "load", lambda *a, **k: FakeEstimator())
    cp = w.pages["Case Management"]
    cp.cid.setText("OSIM-1")
    cp.ctitle.setText("opensim")
    cp._create()
    st.settings.sports2d_python = str(fake_env)
    ex = st.case.acquire(make_video(tmp_path / "v.avi", n=30), "tester")
    analyze_exhibit(st.case, ex.id, "tester", st.settings, ["integrity", "signature", "pose", "sports2d"])
    st.set_exhibit(ex.id)
    st.analysis_changed.emit()
    pp = w.pages["Human Pose"]
    pp.refresh()
    assert [pp.src.itemData(i) for i in range(pp.src.count())] == ["fvp", "sports2d", "opensim"]
    assert pp.osim_open.isEnabled() and "Modello OpenSim pronto" in pp.osim_info.text()
    assert "presunta" in pp.osim_info.text()
    pp.src.setCurrentIndex(2)
    assert "knee angle r" in pp.chart.visible and pp.player.count > 0
