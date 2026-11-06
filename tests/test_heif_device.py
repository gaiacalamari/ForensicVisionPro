"""HEIF/HEIC (parser e decodifica) e coerenza con il dispositivo dichiarato."""
import numpy as np
import pytest
from PIL import Image

from fvp.engines import device, heif_support
from fvp.parsers import heif

pytestmark = pytest.mark.skipif(not heif_support.ensure_registered(), reason="pillow-heif non disponibile")


def _exif(make, model, sw, dto, host=None, lens=None, ew=None, eh=None):
    ex = Image.Exif()
    ex[0x010F], ex[0x0110], ex[0x0131], ex[0x0132] = make, model, sw, dto
    if host:
        ex[0x013C] = host
    e = ex.get_ifd(0x8769)
    e[0x9003] = e[0x9004] = dto
    e[0x9011] = "+02:00"
    if lens:
        e[0xA434], e[0xA433] = lens, make
    if ew:
        e[0xA002], e[0xA003] = ew, eh
    return ex.tobytes()


def _img(w, h, seed=3):
    rng = np.random.default_rng(seed)
    return Image.fromarray((rng.random((h, w, 3)) * 60 + 90).astype("uint8"))


@pytest.fixture(scope="module")
def heic(tmp_path_factory):
    d = tmp_path_factory.mktemp("heic")
    p = d / "IMG_0423.HEIC"
    _img(640, 480).save(p, quality=80, thumbnails=[160],
                        exif=_exif("Apple", "iPhone 13 Pro", "17.4.1", "2024:05:10 18:22:41", "iPhone 13 Pro",
                                   "iPhone 13 Pro back triple camera 5.7mm f/1.5"))
    return p


def test_heif_parser_no_video_false_positives(heic):
    r = heif.parse(heic)
    titles = [f.title for f in r.findings]
    assert "Atom 'moov' assente" not in titles
    assert not [f for f in r.findings if f.significant]
    s = r.extra["heif"]
    assert s["primary_size"] == [640, 480] and s["exif_items"] and s["thumbnails"][0]["size"] == [160, 120]


def test_heif_parser_truncated(heic, tmp_path):
    t = tmp_path / "trunc.heic"
    data = heic.read_bytes()
    t.write_bytes(data[: len(data) * 2 // 3])
    r = heif.parse(t)
    assert any(f.title == "Dati di item oltre la fine del file" and f.significant for f in r.findings)


def test_heif_decoding_and_thumbnail(heic):
    with Image.open(heic) as im:
        im.load()
        assert im.size == (640, 480)
    f = heif_support.thumbnail_check(heic)
    assert f is not None and f.title == "Miniatura coerente con l'immagine"


def _meta(**kv):
    groups = {"Make": "IFD0", "Model": "IFD0", "Software": "IFD0", "HostComputer": "IFD0", "ModifyDate": "IFD0"}
    return {"tags": [{"group": groups.get(k, "ExifIFD"), "tag": k, "value": v, "reliability": "dichiarato"}
                     for k, v in kv.items()], "limited": True}


def test_device_consistent_iphone():
    m = _meta(Make="Apple", Model="iPhone 13 Pro", Software="17.4.1", HostComputer="iPhone 13 Pro",
              LensModel="iPhone 13 Pro back triple camera 5.7mm f/1.5", DateTimeOriginal="2024:05:10 18:22:41",
              ModifyDate="2024:05:10 18:22:41", ExifImageWidth="4032", ExifImageHeight="3024")
    res, fs = device.analyze(m, "IMG_0423.HEIC", "", (4032, 3024), "heif", None)
    assert not [f for f in fs if f.significant], [f.title for f in fs]
    assert any(f.title.startswith("Risoluzione coerente") for f in fs)


def test_device_inconsistent_iphone():
    m = _meta(Make="Apple", Model="iPhone 15 Pro", Software="16.2", HostComputer="iPhone 13 Pro",
              LensModel="iPhone 13 Pro back triple camera 5.7mm f/1.5", DateTimeOriginal="2022:05:01 10:00:00",
              ExifImageWidth="4032", ExifImageHeight="3024")
    _, fs = device.analyze(m, "foto vacanze.heic", "", (3000, 2000), "heif", None)
    t = {f.title for f in fs}
    for expected in ("Campi del dispositivo in contraddizione", "Dimensioni EXIF diverse dai pixel reali",
                     "Versione di iOS anteriore al modello", "Scatto anteriore all'uscita di iPhone 15 Pro",
                     "Risoluzione non prodotta da iPhone 15 Pro", "Nome del file non tipico del dispositivo"):
        assert expected in t, t


def test_device_filename_time():
    m = _meta(Make="samsung", Model="SM-S918B", DateTimeOriginal="2024:05:10 18:25:00")
    _, fs = device.analyze(m, "20240510_182241.jpg", "", None, "jpeg", None, profiles={})
    assert any(f.title == "Ora nel nome diversa dallo scatto" and f.significant for f in fs)
    _, fs = device.analyze(_meta(Make="samsung", Model="SM-S918B", DateTimeOriginal="2024:05:10 18:22:42"),
                           "20240510_182241.jpg", "", None, "jpeg", None, profiles={})
    assert any(f.title == "Ora nel nome coerente con lo scatto" for f in fs)


def test_device_edited_and_whatsapp_names():
    m = _meta(Make="Apple", Model="iPhone 13 Pro", DateTimeOriginal="2024:05:10 18:22:41")
    _, fs = device.analyze(m, "IMG_E0423.HEIC", "", None, "heif", None, profiles={})
    assert any(f.title.startswith("Nome di una versione modificata") for f in fs)
    _, fs = device.analyze(m, "IMG-20240509-WA0007.jpg", "", None, "jpeg", None, profiles={})
    t = {f.title for f in fs}
    assert "EXIF del dispositivo in un file con nome WhatsApp" in t and "Data nel nome precedente allo scatto" in t


# ---------------------------------------------------------------- video iPhone e confronto tra reperti
from fvp.engines import case_context  # noqa: E402


def test_device_iphone_video_keys():
    tags = [("Keys", "Make", "Apple"), ("Keys", "Model", "iPhone 13 Pro"), ("Keys", "Software", "15.0"),
            ("Keys", "CreationDate", "2021:06:01 10:00:00+02:00"), ("Track1", "ImageWidth", "2000"),
            ("Track1", "ImageHeight", "1000")]
    m = {"tags": [{"group": g, "tag": t, "value": v, "reliability": "dichiarato"} for g, t, v in tags]}
    res, fs = device.analyze(m, "IMG_0001.MOV", "", None, "mov", None)
    t = {f.title for f in fs}
    assert res["raster"] == [2000, 1000]
    assert "Scatto anteriore all'uscita di iPhone 13 Pro" in t
    assert "Risoluzione video non standard per iPhone 13 Pro" in t


def _rec(i, name, model="iPhone 13 Pro", t="2024-05-10T18:00:00", utc=None, cid=None, kind="still", sha=None):
    m = case_context.RX_NUM.match(name)
    return {"id": i, "name": name, "sha256": sha or i, "make": "Apple", "model": model, "time_raw": t,
            "local": t, "utc": utc, "cid": cid, "kind": kind, "img_num": int(m.group("n")) if m else None,
            "edited": bool(m and m.group("e"))}


def test_case_live_photo_pairing():
    recs = [_rec("A", "IMG_0010.HEIC", cid="X1"), _rec("B", "IMG_0010.MOV", t="2024-05-10T17:59:59", cid="X1",
                                                       kind="video")]
    _, fs = case_context.analyze("A", recs)
    assert any(f.title == "Live Photo: componenti coerenti" for f in fs)
    recs[1] = _rec("B", "IMG_0011.MOV", model="iPhone 15", t="2024-05-10T19:00:00", cid="X1", kind="video")
    _, fs = case_context.analyze("A", recs)
    bad = [f for f in fs if f.title == "Live Photo: componenti incoerenti"]
    assert bad and bad[0].significant


def test_case_original_and_edit_share_identifier():
    recs = [_rec("A", "IMG_0010.HEIC", cid="X1"), _rec("B", "IMG_E0010.HEIC", cid="X1")]
    _, fs = case_context.analyze("A", recs)
    assert any(f.title == "Più versioni dello stesso scatto" for f in fs)


def test_case_numbering_order():
    recs = [_rec("A", "IMG_0010.HEIC", t="2024-05-10T18:00:00"), _rec("B", "IMG_0011.HEIC", t="2024-05-10T17:00:00"),
            _rec("C", "IMG_0012.HEIC", t="2024-05-10T19:00:00")]
    _, fs = case_context.analyze("B", recs)
    inv = [f for f in fs if f.title == "Numerazione incoerente con la data di scatto"]
    assert len(inv) == 1 and inv[0].confidence == "bassa"      # 1 h esatta: possibile cambio di fuso
    recs[1] = _rec("B", "IMG_0011.HEIC", t="2024-05-10T17:21:27")
    _, fs = case_context.analyze("B", recs)
    assert [f for f in fs if f.title.startswith("Numerazione") and f.significant]
    # rollover IMG_9999 -> IMG_0001
    recs = [_rec("A", "IMG_9998.HEIC", t="2024-05-10T18:00:00"), _rec("B", "IMG_0002.HEIC", t="2024-05-10T18:10:00")]
    _, fs = case_context.analyze("B", recs)
    assert not [f for f in fs if f.title.startswith("Numerazione")]
