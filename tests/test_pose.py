"""Modulo Persone e movimento (metodologia Sports2D): angoli, filtri, tracciamento, indicatori forensi, inferenza
ONNX, integrazione nella pipeline. I modelli reali non sono necessari: uno stimatore finto 'vede' le sagome bianche
dei video sintetici e micro-modelli ONNX generati al volo verificano la catena di inferenza."""
import hashlib
import json
import math
import zipfile

import cv2
import numpy as np
import pytest

from fvp.core.findings import Category, Level
from fvp.engines import pose as P
from fvp.engines import pose_model as M

# posa di profilo verso destra in coordinate relative al riquadro (x, y in [0, 1])
TEMPLATE = {"Nose": (.6, .06), "LEye": (.58, .04), "REye": (.62, .04), "LEar": (.5, .05), "REar": (.55, .05),
            "LShoulder": (.48, .2), "RShoulder": (.52, .2), "LElbow": (.42, .35), "RElbow": (.6, .35),
            "LWrist": (.42, .48), "RWrist": (.64, .48), "LHip": (.48, .5), "RHip": (.52, .5), "LKnee": (.46, .72),
            "RKnee": (.56, .72), "LAnkle": (.44, .95), "RAnkle": (.55, .95), "Head": (.55, 0.), "Neck": (.5, .17),
            "Hip": (.5, .5), "LBigToe": (.5, 1.), "RBigToe": (.62, 1.), "LSmallToe": (.48, 1.), "RSmallToe": (.6, 1.),
            "LHeel": (.4, .98), "RHeel": (.52, .98)}


def person(x0, y0, w, h, score=0.9):
    k = np.array([[x0 + TEMPLATE[n][0] * w, y0 + TEMPLATE[n][1] * h] for n in P.HALPE26], np.float32)
    return k, np.full(26, score, np.float32)


class FakeEstimator:
    """Ogni componente bianca del frame è una persona; i keypoint seguono TEMPLATE nel suo riquadro."""

    def describe(self):
        return {"runtime": "test", "detector": {"role": "detector", "file": "fake", "sha256": "0" * 64},
                "pose": {"role": "pose", "file": "fake", "sha256": "1" * 64}}

    def detect(self, img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) > 200
        n, _lab, st, _c = cv2.connectedComponentsWithStats(g.astype(np.uint8))
        return np.array([[x, y, x + w, y + h, 0.9] for x, y, w, h, a in st[1:] if a > 200], np.float32).reshape(-1, 5)

    def keypoints(self, img, boxes):
        boxes = self.detect(img)          # sempre dal contenuto reale del frame
        if len(boxes) == 0:
            return np.zeros((0, 26, 2), np.float32), np.zeros((0, 26), np.float32)
        ks, ss = zip(*[person(b[0], b[1], b[2] - b[0], b[3] - b[1]) for b in boxes])
        return np.stack(ks), np.stack(ss)


def make_video(path, n=80, cut=None, people=1, fps=25):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (320, 240))
    assert vw.isOpened()
    for i in range(n):
        f = np.full((240, 320, 3), 40, np.uint8)
        for j in range(people):
            x = 20 + i + 70 * j
            if cut is not None and i >= cut:
                x += 120
            cv2.rectangle(f, (x, 90 + 5 * j), (x + 24, 190 + 5 * j), (255, 255, 255), -1)
        vw.write(f)
    vw.release()
    return path


# ------------------------------------------------------------------ angoli e filtri

def test_angle_conventions_match_sports2d():
    xy = np.full((26, 2), np.nan)
    for n, v in {"Neck": (100, 100), "Hip": (100, 200), "RHip": (100, 200), "RKnee": (100, 300),
                 "RAnkle": (100, 400), "RHeel": (95, 410), "RBigToe": (130, 410)}.items():
        xy[P.KP[n]] = v
    a, side = P.compute_angles(xy)
    assert side == "right" and abs(a["right knee"]) < 1e-9 and abs(a["right hip"]) < 1e-9
    xy[P.KP["RAnkle"]] = (30, 370)                       # tibia all'indietro: flessione
    assert P.compute_angles(xy)[0]["right knee"] == pytest.approx(45.0)
    mirrored = xy.copy()
    mirrored[:, 0] = 400 - mirrored[:, 0]                # stessa posa rivolta a sinistra
    a2, side2 = P.compute_angles(mirrored)
    assert side2 == "left" and a2["right knee"] == pytest.approx(45.0)
    assert "right wrist" not in a and "right hand" not in a   # richiedono Index, assente in HALPE-26


def test_butterworth_and_filtfilt():
    b, a = P.butter_lowpass(2, 6, 30)
    assert b.sum() / a.sum() == pytest.approx(1.0)       # guadagno unitario in continua
    t = np.arange(300) / 30
    assert np.allclose(P.filtfilt(b, a, np.full(300, 7.0)), 7.0)
    slow, fast = np.sin(2 * np.pi * 1 * t), np.sin(2 * np.pi * 12 * t)
    assert np.std(P.filtfilt(b, a, slow)[30:-30]) / np.std(slow) > 0.98
    assert np.std(P.filtfilt(b, a, fast)[30:-30]) / np.std(fast) < 0.1


def test_interpolate_gaps_only_short():
    x = np.array([0, 1, np.nan, np.nan, 4, np.nan, np.nan, np.nan, np.nan, 9.0])
    y = P.interpolate_gaps(x, 2)
    assert y[2:4].tolist() == [2.0, 3.0] and np.isnan(y[5:9]).all()


# ------------------------------------------------------------------ tracciamento e indicatori

def _run_tracks(frames, fps=30.0):
    p = P.Params()
    tr = P.Tracker(p)
    for i, people in enumerate(frames):
        if people:
            k, s = zip(*people)
            tr.update(i, np.stack(k), np.stack(s))
        else:
            tr.update(i, np.zeros((0, 26, 2)), np.zeros((0, 26)))
    return tr.all_tracks(), np.arange(len(frames)) / fps, p


def test_tracker_keeps_identities():
    frames = [[person(50 + i, 50, 40, 160), person(250 - i, 60, 40, 150)] for i in range(30)]
    tracks, _t, _p = _run_tracks(frames)
    assert len(tracks) == 2 and all(len(t.frames) == 30 for t in tracks)


def test_scene_cut_vs_isolated_jump():
    frames = []
    for i in range(60):
        dx = 120 if i >= 30 else 0                       # taglio: entrambe le persone saltano al frame 30
        frames.append([person(20 + i + dx, 40, 40, 160), person(320 + i - dx, 50, 40, 150)])
    tracks, times, p = _run_tracks(frames)
    vis = np.full(60, 1.0)
    vis[30] = 10.0
    ev = P.transitions(tracks, times, vis, p)
    assert [e["frame"] for e in ev if e["class"] == "scena"] == [30]
    # salto di una sola persona (0,44 altezze in 1/30 s), sotto la soglia del salto netto e senza conferme: isolato
    frames = [[person(20 + i + (70 if i == 30 else 0), 40, 40, 160), person(320 + i, 50, 40, 150)]
              for i in range(60)]
    tracks, times, p = _run_tracks(frames)
    ev = P.transitions(tracks, times, np.ones(60), p)
    assert ev and all(e["class"] == "isolata" for e in ev) and 30 in [e["frame"] for e in ev]


def test_fast_but_plausible_motion_is_not_a_jump():
    # 0,25 altezze in 1/30 s = 7,5 altezze/s: corsa veloce, sotto la soglia di 8
    frames = [[person(20 + i + (40 if i == 30 else 0), 40, 40, 160)] for i in range(60)]
    tracks, times, p = _run_tracks(frames)
    assert P.transitions(tracks, times, np.ones(60), p) == []


def test_continuous_motion_has_no_transitions():
    frames = [[person(20 + 3 * i, 40 + math.sin(i / 5) * 4, 40, 160)] for i in range(90)]
    tracks, times, p = _run_tracks(frames)
    assert P.transitions(tracks, times, np.ones(90), p) == []


def test_scale_jump_detected():
    frames = [[person(100, 40, 40, 100 if i < 20 else 160)] for i in range(40)]
    tracks, times, p = _run_tracks(frames)
    ev = P.transitions(tracks, times, np.ones(40), p)
    assert any(e["frame"] == 20 and e["scale"] for e in ev)


def test_cadence_from_ankle_oscillation():
    fps, stride_hz = 30.0, 0.9
    t = P.Track(1)
    for i in range(int(fps * 8)):
        k, s = person(20 + i * 1.5, 40, 40, 160)
        sw = 25 * math.sin(2 * math.pi * stride_hz * i / fps)
        k[P.KP["LAnkle"], 0] += sw
        k[P.KP["RAnkle"], 0] -= sw
        t.frames.append(i)
        t.kpts.append(k)
        t.scores.append(s)
    c = P.cadence(t, np.arange(len(t.frames)) / fps, P.Params())
    assert c["steps_per_min"] == pytest.approx(stride_hz * 120, abs=c["resolution_steps_min"])


# ------------------------------------------------------------------ analisi completa (stimatore finto)

def test_video_analysis_detects_cut(tmp_path):
    v = make_video(tmp_path / "cut.avi", cut=40)
    res, fs = P.analyze(v, "video", tmp_path / "out", estimator=FakeEstimator())
    scene = [e for e in res["transitions"] if e["class"] == "scena"]
    assert [e["source_frame"] for e in scene] == [40]
    f = next(x for x in fs if x.title.startswith("Discontinuità del movimento"))
    assert f.level == Level.SUSPICIOUS and f.category == Category.HUMAN_POSE and "frame 40" in f.evidence
    for name, e in res["exports"].items():                # ogni esportazione con hash corretto
        assert hashlib.sha256(open(e["path"], "rb").read()).hexdigest() == e["sha256"], name
    assert {"pose", "pose_motion", "pose_jumps"} <= set(res["artifacts"])
    json.dumps(res)                                       # serializzabile per il database del caso
    json.dumps([x.to_dict() for x in fs])
    trc = next(e["path"] for n, e in res["exports"].items() if n.endswith(".trc"))
    assert open(trc).readline().startswith("PathFileType\t4")


def test_continuous_video_no_discontinuity(tmp_path):
    v = make_video(tmp_path / "ok.avi", n=60, people=2)
    res, fs = P.analyze(v, "video", tmp_path / "out", estimator=FakeEstimator())
    assert len(res["persons"]) == 2
    assert not [x for x in fs if x.title.startswith("Discontinuità")]


def test_frame_limit_reported(tmp_path):
    v = make_video(tmp_path / "long.avi", n=50)

    class S:
        pose_max_frames, pose_frame_step, pose_det_every, pose_annotated_video = 20, 1, 4, False
    res, fs = P.analyze(v, "video", tmp_path / "out", settings=S(), estimator=FakeEstimator())
    assert res["frames"]["analyzed"] == 20 and res["frames"]["limited"]
    assert any(x.title.startswith("Analisi della posa limitata") for x in fs)


def test_image_analysis(tmp_path):
    img = np.full((300, 300, 3), 40, np.uint8)
    cv2.rectangle(img, (100, 50), (140, 250), (255, 255, 255), -1)
    p = tmp_path / "persona.png"
    cv2.imwrite(str(p), img)
    res, fs = P.analyze(p, "image", tmp_path / "out", estimator=FakeEstimator())
    assert len(res["persons"]) == 1 and fs[0].title == "Persone rilevate: 1"
    assert res["persons"][0]["angles"]["right knee"]["n"] == 1


# ------------------------------------------------------------------ pipeline

@pytest.fixture
def fake_models(monkeypatch):
    monkeypatch.setattr(M, "load", lambda *a, **k: FakeEstimator())


def test_pipeline_video_with_pose(case, tmp_path, fake_models):
    from fvp.core.pipeline import analyze_exhibit
    v = make_video(tmp_path / "cut.avi", cut=40)
    ex = case.acquire(v, "tester")
    aid = analyze_exhibit(case, ex.id, "tester", modules=["integrity", "signature", "pose"])
    an = next(a for a in case.analyses(ex.id) if a["id"] == aid)
    r = an["results"]
    assert "pose" in r["executed"] and Category.HUMAN_POSE.value in r["executed_categories"]
    assert r["pose"]["transitions"] and "pose_jumps" in r["artifacts"]
    assert an["integrity_ok"]
    from fvp.core import explain
    from fvp.core.findings import Status
    assert explain.status_of(an)[Category.HUMAN_POSE] == Status.RED          # taglio confermato dall'immagine
    from fvp.reporting import report
    html = report.write_html(case, tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Persone e movimento" in html and "Discontinuità del movimento" in html


def test_pipeline_without_models_is_undetermined(case, tmp_path, monkeypatch):
    monkeypatch.setenv("FVP_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(M, "_bundled_dir", lambda: tmp_path / "nobin")
    from fvp.core.pipeline import analyze_exhibit
    v = make_video(tmp_path / "v.avi", n=10)
    ex = case.acquire(v, "tester")
    aid = analyze_exhibit(case, ex.id, "tester", modules=["integrity", "signature", "pose"])
    an = next(a for a in case.analyses(ex.id) if a["id"] == aid)
    f = next(x for x in an["findings"] if x.category == Category.HUMAN_POSE)
    assert f.level == Level.UNDETERMINED and f.title == "Stima della posa non disponibile"


# ------------------------------------------------------------------ inferenza ONNX reale (micro-modelli)

def _micro_models(d):
    onnx = pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    from onnx import TensorProto, helper, numpy_helper

    def model(name, in_shape, outs):
        inp = helper.make_tensor_value_info("input", TensorProto.FLOAT, in_shape)
        nodes, outputs = [helper.make_node("ReduceMean", ["input"], ["m"], keepdims=0),
                          helper.make_node("Mul", ["m", "zero"], ["z"])], []
        inits = [numpy_helper.from_array(np.array(0, np.float32), "zero")]
        for oname, arr in outs:
            inits.append(numpy_helper.from_array(arr, oname + "_c"))
            nodes.append(helper.make_node("Add", [oname + "_c", "z"], [oname]))
            outputs.append(helper.make_tensor_value_info(oname, TensorProto.FLOAT, list(arr.shape)))
        g = helper.make_graph(nodes, name, [inp], outputs, inits)
        m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
        m.ir_version = 8
        p = d / name
        onnx.save(m, str(p))
        return p
    dets = np.array([[[64, 32, 192, 288, 0.95]]], np.float32)            # riquadro nello spazio 640x640
    det = model(M.DET_FILE, [1, 3, 640, 640], [("dets", dets)])
    sx = np.zeros((1, 26, 384), np.float32)
    sy = np.zeros((1, 26, 512), np.float32)
    sx[0, :, 192] = 1.0                                                    # centro del ritaglio
    sy[0, :, 256] = 1.0
    pose = model(M.POSE_FILE, [1, 3, 256, 192], [("simcc_x", sx), ("simcc_y", sy)])
    return det, pose


def test_onnx_micro_models_end_to_end(tmp_path):
    det, pose = _micro_models(tmp_path)
    est = M.load(str(det), str(pose), threads=1)
    assert est.det_hw == (640, 640) and est.pose_wh == (192, 256)
    frame = np.zeros((320, 320, 3), np.uint8)                              # letterbox: rapporto 2
    boxes = est.detect(frame)
    assert boxes[:, :4].tolist() == [[32, 16, 96, 144]]
    k, s = est.keypoints(frame, boxes[:, :4])
    assert k.shape == (1, 26, 2) and np.allclose(k[0], [64, 80]) and np.allclose(s, 1.0)
    d = est.describe()
    assert d["detector"]["sha256"] == hashlib.sha256(det.read_bytes()).hexdigest()


def test_model_must_match_lock(tmp_path, monkeypatch):
    det, pose = _micro_models(tmp_path)
    monkeypatch.setattr(M, "_bundled_dir", lambda: tmp_path)
    (tmp_path / "tools.lock.json").write_text(json.dumps({"pose-detector": {"file_hashes": {M.DET_FILE: "0" * 64}}}))
    M._sha256_cached.cache_clear()
    with pytest.raises(M.PoseUnavailable, match="tools.lock.json"):
        M.locate_models()


# ------------------------------------------------------------------ fetch_tools: voci facoltative e --pin

def test_fetch_tools_optional_and_pin(tmp_path):
    import fetch_tools
    arc = tmp_path / "m.zip"
    with zipfile.ZipFile(arc, "w") as z:
        z.writestr("rtmpose/end2end.onnx", b"modello")
    copy = tmp_path / "mirror.zip"
    copy.write_bytes(arc.read_bytes())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    entry = {"name": "pose-x", "group": "pose-models", "optional": True, "platform": "any", "sha256": "",
             "urls": [arc.as_uri(), copy.as_uri()], "extract": {"*end2end.onnx": "x.onnx"}}
    broken = {**entry, "name": "pose-y", "sha256": "0" * 64}
    (bin_dir / "tools.json").write_text(json.dumps({"tools": [entry, broken]}))
    fetch_tools.fetch(bin_dir, log=lambda *_: None)                        # non fissata e hash errato: solo avvisi
    assert not (bin_dir / "x.onnx").exists()
    pinned = fetch_tools.pin(bin_dir, "pose-x", log=lambda *_: None)
    assert pinned["pose-x"] == hashlib.sha256(arc.read_bytes()).hexdigest()
    lock = fetch_tools.fetch(bin_dir, only="pose-x", log=lambda *_: None)
    assert (bin_dir / "x.onnx").read_bytes() == b"modello" and "x.onnx" in lock["pose-x"]["file_hashes"]
    copy.write_bytes(b"PK\x05\x06" + b"\x00" * 18)                         # sorgente diversa: impronta rifiutata
    with pytest.raises(fetch_tools.FetchError, match="diversi"):
        fetch_tools.pin(bin_dir, "pose-x", log=lambda *_: None)
