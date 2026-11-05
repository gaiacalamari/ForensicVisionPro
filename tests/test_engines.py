from datetime import datetime, timezone

from conftest import needs_exiftool, needs_ffmpeg

from fvp.engines import image, metadata, signature, timestamps
from fvp.parsers import isobmff, jpeg, png


def titles(fs):
    return " | ".join(f.title for f in fs)


def test_signature_identify(dataset):
    assert signature.identify(dataset / "original.jpg")["format"] == "jpeg"
    i = signature.identify(dataset / "renamed_jpeg.png")
    assert i["format"] == "jpeg" and not i["extension_matches"]
    assert "Estensione non coerente" in titles(signature.findings_for(i))
    assert signature.identify_bytes(b"\x00\x00\x00\x18ftypqt  " + b"\x00" * 8) == "mov"
    assert signature.identify_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 20 + b"webm") == "webm"


def test_signature_scan_finds_appended_zip(dataset):
    hits = signature.scan_signatures(dataset / "trailing_zip.jpg")
    zips = [h for h in hits if h["signature"] == "ZIP"]
    assert zips and zips[0]["offset"] == (dataset / "original.jpg").stat().st_size


def test_jpeg_parser_clean(dataset):
    r = jpeg.parse(dataset / "original.jpg")
    names = [c.name for c in r.root.children]
    assert names[0] == "SOI" and names[-1] == "EOI"
    assert r.extra["sof"]["width"] == 1024
    assert r.extra["qtables"]["0"]["ijg_quality"] == 92 and r.extra["qtables"]["0"]["ijg_error"] == 0
    assert not [f for f in r.findings if f.significant]


def test_jpeg_parser_trailing_and_truncated(dataset):
    r = jpeg.parse(dataset / "trailing_zip.jpg")
    t = [f for f in r.findings if "Dati dopo la fine" in f.title][0]
    assert t.significant and t.offset == (dataset / "original.jpg").stat().st_size
    r2 = jpeg.parse(dataset / "truncated.jpg")
    assert "EOI mancante" in titles(r2.findings)


def test_png_parser(dataset):
    assert not [f for f in png.parse(dataset / "clean.png").findings if f.significant]
    bad = png.parse(dataset / "bad_crc.png")
    assert any("CRC errato nel chunk IDAT" in f.title for f in bad.findings)
    ai = png.parse(dataset / "ai_params.png")
    assert ai.extra["text"][0]["key"] == "parameters"


@needs_ffmpeg
def test_isobmff_parser(dataset):
    r = isobmff.parse(dataset / "video_original.mp4")
    top = r.extra["top_level"]
    assert "moov" in top and "mdat" in top and top[0] == "ftyp"
    assert any(t["atom"] == "mvhd" and t["creation"].startswith("2026-09-12T08:15:30") for t in r.extra["times"])
    tr = isobmff.parse(dataset / "video_truncated.mp4")
    assert "oltre i limiti" in titles(tr.findings)


def test_timestamp_parsing():
    dt, tz, _ = timestamps.parse_dt("2026:09:12 10:15:30+02:00")
    assert tz and dt.astimezone(timezone.utc).hour == 8
    assert timestamps.parse_dt("0000:00:00 00:00:00")[0] is None
    assert timestamps.parse_dt("2026:13:45 10:00:00")[2].startswith("data non valida")


def test_timestamp_offset_applied_and_gps_consistent():
    tags = [{"group": "ExifIFD", "tag": "DateTimeOriginal", "value": "2026:09:12 10:15:30", "reliability": "dichiarato"},
            {"group": "ExifIFD", "tag": "OffsetTimeOriginal", "value": "+02:00", "reliability": "dichiarato"},
            {"group": "GPS", "tag": "GPSDateStamp", "value": "2026:09:12", "reliability": "dichiarato"},
            {"group": "GPS", "tag": "GPSTimeStamp", "value": "08:15:29", "reliability": "dichiarato"}]
    ev = timestamps.collect(tags)
    dto = [e for e in ev if e.source == "ExifIFD:DateTimeOriginal"][0]
    assert dto.utc.startswith("2026-09-12T08:15:30")
    f = timestamps.analyze(ev, now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert not [x for x in f if "GPS" in x.title]


def test_timestamp_timezone_deduced_without_offset():
    tags = [{"group": "ExifIFD", "tag": "DateTimeOriginal", "value": "2026:09:12 10:15:30", "reliability": "dichiarato"},
            {"group": "GPS", "tag": "GPSDateStamp", "value": "2026:09:12", "reliability": "dichiarato"},
            {"group": "GPS", "tag": "GPSTimeStamp", "value": "08:15:30", "reliability": "dichiarato"}]
    f = timestamps.analyze(timestamps.collect(tags), now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert "Fuso orario dedotto dal GPS" in titles(f)
    ded = [x for x in f if x.title == "Fuso orario dedotto dal GPS"][0]
    assert "+2.00" in ded.description


def test_timestamp_local_never_assumed_utc():
    tags = [{"group": "IFD0", "tag": "ModifyDate", "value": "2026:09:12 10:15:30", "reliability": "dichiarato"}]
    e = timestamps.collect(tags)[0]
    assert e.utc is None and e.local == "2026-09-12T10:15:30" and not e.tz_known


def test_timestamp_filesystem_before_capture():
    tags = [{"group": "ExifIFD", "tag": "DateTimeOriginal", "value": "2026:09:12 10:15:30+02:00", "reliability": "dichiarato"}]
    f = timestamps.analyze(timestamps.collect(tags, {"mtime_utc": "2025-01-01T00:00:00+00:00"}),
                           now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert "File modificato prima dello scatto" in titles(f)


@needs_exiftool
def test_metadata_classification(dataset):
    m = metadata.extract(dataset / "edited_photoshop.jpg")
    rel = {t["group"]: t["reliability"] for t in m["tags"]}
    assert rel.get("IFD0") == "dichiarato" and rel.get("File") == "calcolato" and rel.get("System") == "filesystem_copia"
    assert abs(m["gps"]["lat"] - 45.0701) < 0.001
    assert "Software di elaborazione" in titles(metadata.analyze(m))


def test_metadata_ai_markers_png(dataset):
    r = png.parse(dataset / "ai_params.png")
    f = metadata.analyze({"tags": []}, r.extra["text"])
    assert "Metadati riferiti a generazione AI" in titles(f)


def test_ela_and_noise_produce_maps(dataset, tmp_path):
    vis, f = image.ela(dataset / "original.jpg", 90, tmp_path / "ela.png")
    assert (tmp_path / "ela.png").stat().st_size > 0 and vis.shape == (768, 1024)
    assert f.level.value == "risultato_probabilistico" and f.limitations
    _, n = image.noise_residual(dataset / "original.jpg", tmp_path / "n.png")
    assert (tmp_path / "n.png").exists() and "outlier_ratio" in n.data


@needs_exiftool
def test_thumbnail_check_localizes_edit(dataset):
    assert image.thumbnail_check(dataset / "original.jpg").title == "Miniatura coerente con l'immagine"
    f = image.thumbnail_check(dataset / "edited_photoshop.jpg")
    assert f.title == "Contenuto della miniatura diverso"
    x0, y0, x1, y1 = f.data["region"]
    assert x0 <= 620 and x1 >= 800 and y0 <= 320 and y1 >= 500      # rettangolo introdotto: 600-820, 300-520


def test_decompression_bomb_limit(tmp_path):
    import pytest
    from PIL import Image
    p = tmp_path / "big.png"
    Image.new("L", (3000, 3000)).save(p)
    image.set_pixel_limit(1_000_000)
    try:
        with pytest.raises(Image.DecompressionBombError):
            image.image_info(p)
    finally:
        image.set_pixel_limit(250_000_000)


def test_pillow_fallback_aligned_with_exiftool_names(dataset):
    m = metadata._pillow_fallback(str(dataset / "modify_before_capture.jpg"), "test")
    names = {(t["group"], t["tag"]) for t in m["tags"]}
    assert ("IFD0", "ModifyDate") in names and ("ExifIFD", "CreateDate") in names
    f = timestamps.analyze(timestamps.collect(m["tags"]), now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert "ModifyDate precedente a DateTimeOriginal" in titles(f)
    g = metadata._pillow_fallback(str(dataset / "gps_mismatch.jpg"), "test")
    assert abs(g["gps"]["lat"] - 45.0701) < 0.001
    f2 = timestamps.analyze(timestamps.collect(g["tags"]), now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert "Orario GPS incoerente con lo scatto" in titles(f2)


def test_fetch_tools_from_local_archive(tmp_path):
    import hashlib
    import json
    import zipfile

    import fetch_tools
    arc = tmp_path / "pkg.zip"
    with zipfile.ZipFile(arc, "w") as z:
        z.writestr("pkg-1.0/tool(-k).exe", b"binario")
        z.writestr("pkg-1.0/tool_files/lib/a.dll", b"dll")
        z.writestr("pkg-1.0/README.txt", b"non richiesto")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    entry = {"name": "tool", "platform": "any", "urls": [arc.as_uri()],
             "sha256": hashlib.sha256(arc.read_bytes()).hexdigest(),
             "extract": {"*/tool(-k).exe": "tool.exe"}, "dirs": {"*/tool_files": "tool_files"}}
    (bin_dir / "tools.json").write_text(json.dumps({"tools": [entry]}))
    lock = fetch_tools.fetch(bin_dir, log=lambda *_: None)
    assert (bin_dir / "tool.exe").read_bytes() == b"binario"
    assert lock["tool"]["file_hashes"]["tool.exe"] == hashlib.sha256(b"binario").hexdigest()
    assert (bin_dir / "tool_files" / "lib" / "a.dll").exists() and not (bin_dir / "README.txt").exists()
    assert lock["tool"]["sha256"] == entry["sha256"]
    # hash errato: nessun file estratto
    entry["sha256"] = "0" * 64
    (bin_dir / "tools.json").write_text(json.dumps({"tools": [entry]}))
    (bin_dir / "tool.exe").unlink()
    import pytest
    with pytest.raises(fetch_tools.FetchError):
        fetch_tools.fetch(bin_dir, force=True, log=lambda *_: None)
    assert not (bin_dir / "tool.exe").exists()


# ------------------------------------------------------------------ moduli avanzati (milestone 2)
from fvp.engines import compare, image_extra, jpeg_forensics, prnu, stego  # noqa: E402


def _overlaps(box, truth, min_iou=0.4):
    ax0, ay0, ax1, ay1 = box
    bx0, by0, bx1, by1 = truth
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / union >= min_iou


def test_jpeg_ghost_localizes_splice(dataset, manifest):
    q = jpeg.parse(dataset / "splice_ghost.jpg").extra["qtables"]["0"]["ijg_quality"]
    f = jpeg_forensics.jpeg_ghost(dataset / "splice_ghost.jpg", None, q)
    assert f.data["quality"] in (55, 60, 65)
    assert _overlaps(f.data["bbox"], manifest["splice_ghost.jpg"]["region"])
    q0 = jpeg.parse(dataset / "original.jpg").extra["qtables"]["0"]["ijg_quality"]
    assert jpeg_forensics.jpeg_ghost(dataset / "original.jpg", None, q0).level.value == "informativo"


def test_double_jpeg(dataset):
    for name, expect in (("double_compressed.jpg", True), ("original.jpg", False)):
        qt = jpeg.parse(dataset / name).extra["qtables"]["0"]["values"]
        assert (jpeg_forensics.double_jpeg(dataset / name, qt).title == "Indizi di doppia compressione JPEG") == expect


def test_grid_reveals_jpeg_history_in_png(dataset):
    assert "Storia di compressione JPEG" in jpeg_forensics.grid_alignment(dataset / "jpeg_history.png", False).title
    assert jpeg_forensics.grid_alignment(dataset / "natural.png", False).level.value == "informativo"


def test_multi_ela(dataset, tmp_path):
    f = jpeg_forensics.multi_ela(dataset / "original.jpg", tmp_path / "m.png")
    assert (tmp_path / "m.png").exists() and len(f.data["qualities"]) == 8


def test_copy_move(dataset, manifest):
    f = image_extra.copy_move(dataset / "copy_move.png")
    assert f.title == "Regioni duplicate (copy-move)"
    c = f.data["clusters"][0]
    truth = manifest["copy_move.png"]["region"]
    assert _overlaps(c["bbox_src"], truth, 0.3) or _overlaps(c["bbox_dst"], truth, 0.3)
    assert image_extra.copy_move(dataset / "natural.png").title != "Regioni duplicate (copy-move)"
    assert image_extra.copy_move(dataset / "clean.png").title != "Regioni duplicate (copy-move)"


def test_median_local(dataset, manifest):
    f = image_extra.median_filter(dataset / "median_local.png", False)
    assert f.title.startswith("Regione con elaborazione diversa")
    assert _overlaps(f.data["region"], manifest["median_local.png"]["region"], 0.5)
    assert image_extra.median_filter(dataset / "natural.png", False).data["region"] is None


def test_stego(dataset):
    t = lambda n: [f.title for f in stego.analyze(dataset / n, "png")[1]]  # noqa: E731
    assert "Stima RS elevata" in t("stego_lsb_random.png")
    assert "Chi-quadro compatibile con inserimento sequenziale" in t("stego_lsb_sequential.png")
    assert t("natural.png") == ["Stima RS nella norma"]
    r, _ = stego.analyze(dataset / "stego_lsb_random.png", "png")
    assert all(0.35 < v["rs"] < 0.65 for v in r["channels"].values())      # inserito il 50%
    assert stego.analyze(dataset / "original.jpg", "jpeg")[1][0].title == "Test sui pixel non applicabili a questo formato"


def test_chi_square_pvalue():
    import numpy as np
    rng = np.random.default_rng(0)
    assert stego.chi_square_p(rng.integers(0, 256, 200000).astype(np.uint8)) > 0.01   # coppie uniformi
    skew = np.repeat(np.arange(0, 256, 2), 1000).astype(np.uint8)                     # solo valori pari
    assert stego.chi_square_p(skew) < 1e-6


def test_prnu_fingerprint_and_pce(tmp_path):
    import cv2
    import numpy as np
    from PIL import Image
    rng = np.random.default_rng(0)
    H, W = 640, 800
    KA, KB = rng.normal(0, 0.01, (H, W)), rng.normal(0, 0.01, (H, W))

    def shot(K, seed):
        r = np.random.default_rng(seed)
        sc = cv2.GaussianBlur(r.normal(0, 1, (H, W)), (0, 0), 25)
        sc = (sc - sc.min()) / (sc.max() - sc.min()) * 150 + 60
        return np.clip(np.stack([sc * (1 + K)] * 3, 2) + r.normal(0, 2, (H, W, 3)), 0, 255).astype(np.uint8)
    refs = []
    for i in range(8):
        p = tmp_path / f"r{i}.png"
        Image.fromarray(shot(KA, i)).save(p)
        refs.append(p)
    store = prnu.PrnuStore(tmp_path / "db")
    store.add("A", "Camera A", refs, "tester")
    a, b = tmp_path / "a.jpg", tmp_path / "b.png"
    Image.fromarray(shot(KA, 100)).save(a, quality=85)
    Image.fromarray(shot(KB, 101)).save(b)
    ra, fa = prnu.match(a, store)
    rb, fb = prnu.match(b, store)
    assert ra[0]["pce"] > prnu.PCE_THRESHOLD > rb[0]["pce"]
    assert fa[0].title == "Compatibile con il sensore A" and fb[0].title == "Nessuna impronta compatibile"
    # un'impronta alterata dopo la creazione viene rifiutata
    item = store.list()[0]
    k = np.load(tmp_path / "db" / f"{item['id']}.npy")
    np.save(tmp_path / "db" / f"{item['id']}.npy", k * 1.01)
    import pytest
    with pytest.raises(ValueError):
        store.load(item["id"])


def test_compare(dataset):
    r = compare.compare(dataset / "original.jpg", dataset / "original.jpg")
    assert r["identical_pixels"] and all(v == 0 for v in r["hashes"]["distance"].values())
    r2 = compare.compare(dataset / "original.jpg", dataset / "splice_ghost.jpg")
    assert r2["hashes"]["distance"]["phash"] <= 6 and 0.8 < r2["ssim"] < 1
    r3 = compare.compare(dataset / "original.jpg", dataset / "natural.png")
    assert compare.interpret(r3) == "Immagini diverse."


# ------------------------------------------------------------------ StegoIntelligence e controllo di sistema (1.0)
from fvp.engines import stegointel  # noqa: E402


def test_stegointel_extracts_hidden_content(dataset, manifest, tmp_path):
    import zipfile
    r, f = stegointel.analyze(dataset / "stego_text.png", "png", tmp_path / "x")
    h = r["hits"][0]
    assert (h["channels"], h["bits"], h["order"], h["msb_first"]) == ("RGB", 1, "xy", True)
    assert open(h["file"], encoding="ascii").read().startswith(manifest["stego_text.png"]["secret"][:40])
    r, _ = stegointel.analyze(dataset / "stego_zip.png", "png", tmp_path / "z")
    assert zipfile.ZipFile(r["hits"][0]["file"]).read("segreto.txt") == b"documento riservato"
    assert stegointel.analyze(dataset / "stego_openstego.png", "png")[1][0].title.endswith("Intestazione OpenStego")
    assert stegointel.analyze(dataset / "audio_lsb.wav", "wav")[1][0].title.endswith("Testo nascosto")


def test_stegointel_no_false_positives(dataset):
    for n, fmt in (("natural.png", "png"), ("clean.png", "png"), ("copy_move.png", "png"), ("jpeg_history.png", "png"),
                   ("stego_lsb_random.png", "png"), ("audio_clean.wav", "wav")):
        assert stegointel.analyze(dataset / n, fmt)[0]["hits"] == [], n
    assert stegointel.analyze(dataset / "original.jpg", "jpeg")[1][0].level.value == "non_determinabile"


def test_bit_plane():
    import numpy as np
    a = np.zeros((4, 4, 3), np.uint8)
    a[0, 0, 0] = 0b101
    p0, p1 = stegointel.bit_plane(a, "R", 0), stegointel.bit_plane(a, "R", 1)
    assert p0[0, 0] == 255 and p1[0, 0] == 0 and p0.sum() == 255


def test_selfcheck(tmp_path, monkeypatch):
    import json

    from fvp.core import selfcheck
    from fvp.core.config import Settings
    monkeypatch.setenv("FVP_HOME", str(tmp_path))
    checks = selfcheck.run(Settings())
    names = {c.name for c in checks}
    assert {"Qt (PySide6)", "OpenCV SIFT (copy-move)", "ExifTool", "FFprobe", "Cartella dei casi"} <= names
    selfcheck.write_report(checks, tmp_path / "r.json")
    rep = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert rep["ok"] == selfcheck.summary(checks)[0]
    assert all(c.ok for c in checks if c.name in ("Qt (PySide6)", "NumPy", "Cartella dei casi"))
    bad = Settings(exiftool_path="")
    monkeypatch.setattr("fvp.core.selfcheck.get_tool", lambda name, p="": None)
    ok, failed = selfcheck.summary(selfcheck.run(bad))
    assert not ok and {"ExifTool", "FFprobe"} <= {c.name for c in failed}


def test_selfcheck_detects_modified_bundled_binary(tmp_path, monkeypatch):
    import hashlib
    import json

    from fvp.core import selfcheck
    (tmp_path / "tool.exe").write_bytes(b"originale")
    (tmp_path / "tools.lock.json").write_text(json.dumps({"tool": {"version": "1", "file_hashes": {
        "tool.exe": hashlib.sha256(b"originale").hexdigest()}}}))
    monkeypatch.setattr(selfcheck, "_bundled_dir", lambda: tmp_path)
    assert selfcheck._bundle_integrity()[0].ok
    (tmp_path / "tool.exe").write_bytes(b"sostituito")
    c = selfcheck._bundle_integrity()[0]
    assert not c.ok and "tool.exe" in c.detail



# ------------------------------------------------------------------ 1.1: testo nascosto e verifiche
from fvp.engines import hidden_text  # noqa: E402
from fvp.parsers import bmp  # noqa: E402


def test_stegointel_bgr_length8_message(dataset, manifest, tmp_path):
    """Riproduce il file stego.bmp del caso reale: lunghezza su 8 byte, ordine BGR, MSB per primo."""
    r, f = stegointel.analyze(dataset / "stego_bgr_len8.bmp", "bmp", tmp_path)
    h = r["hits"][0]
    assert (h["channels"], h["msb_first"]) == ("BGR", True)
    assert open(h["file"], encoding="utf-8").read().strip() == manifest["stego_bgr_len8.bmp"]["secret"]


def test_stegointel_base64_and_text_anywhere():
    data = b"\x00" * 37 + b"il carico arriva al molo sette domani sera" + b"\x00" * 10
    assert stegointel.analyze_stream(data)["offset"] == 37
    import base64
    b = b"\x00\x00xx" + base64.b64encode(b"Consegna confermata domani alle nove presso il magazzino") + b"\x00"
    assert stegointel.analyze_stream(b)["detail"].endswith("Base64")
    assert stegointel.analyze_stream(b"UUUUUUUUUUUUUUUUUUUUUUUUUUUUUUI{aziN" + bytes(30)) is None


def test_hidden_text_checks(dataset):
    assert hidden_text.faint_content(dataset / "faint_text.png")[1].title == "Possibili segni quasi invisibili"
    for n in ("natural.png", "clean.png", "original.jpg", "splice_ghost.jpg", "jpeg_history.png"):
        assert hidden_text.faint_content(dataset / n)[1].level.value != "indicatore_sospetto", n
    st = jpeg.parse(dataset / "trailing_text.jpg").to_dict()
    hits, f = hidden_text.file_strings(dataset / "trailing_text.jpg", st)
    assert hits[0]["location"].startswith("Dati oltre EOI") and "password" in hits[0]["text"]
    for n, parser in (("original.jpg", jpeg), ("natural.png", png), ("stego_bgr_len8.bmp", bmp)):
        assert hidden_text.file_strings(dataset / n, parser.parse(dataset / n).to_dict())[0] == [], n
    tags = [{"group": "PNG", "tag": "Comment", "value": "Q29uc2VnbmEgY29uZmVybWF0YSBkb21hbmkgYWxsZSBub3Zl",
             "reliability": "dichiarato"}]
    assert hidden_text.metadata_text(tags)[1][0].title == "Contenuti codificati nei metadati"


def test_bmp_structure(dataset):
    titles = [f.title for f in bmp.parse(dataset / "bmp_padding.bmp").findings]
    assert "Byte di riempimento delle righe non nulli" in titles
    assert bmp.parse(dataset / "stego_bgr_len8.bmp").findings == []


def test_copy_move_ignores_repeated_text(dataset):
    f = image_extra.copy_move(dataset / "screen_text.jpg")
    assert f.title != "Regioni duplicate (copy-move)" and not f.significant
    g = image_extra.copy_move(dataset / "copy_move.png")
    assert g.title == "Regioni duplicate (copy-move)" and g.data["clusters"][0]["ncc"] > 0.9


def test_dct_chi_square_detects_jsteg_like(dataset, tmp_path):
    import cv2
    import numpy as np
    from PIL import Image
    p = dataset / "original.jpg"
    qt = jpeg.parse(p).extra["qtables"]["0"]["values"]
    assert jpeg_forensics.dct_chi_square(p, qt).level.value == "informativo"
    q = np.array(qt, np.float32).reshape(8, 8)
    y = np.asarray(Image.open(p).convert("YCbCr"))[:, :, 0].astype(np.float32)
    H, W = (y.shape[0] // 8) * 8, (y.shape[1] // 8) * 8
    qc = np.rint(jpeg_forensics._block_dct(y) / q)
    n = len(qc) // 2
    fl = qc[:n].reshape(n, 64)
    m = (fl != 0) & (fl != 1)
    m[:, 0] = False
    fl[m] = np.floor(fl[m] / 2) * 2 + np.random.default_rng(0).integers(0, 2, fl.shape)[m]
    qc[:n] = fl.reshape(n, 8, 8)
    rec = np.stack([cv2.idct((b * q).astype(np.float32)) for b in qc]) + 128
    img = rec.reshape(H // 8, W // 8, 8, 8).transpose(0, 2, 1, 3).reshape(H, W)
    Image.fromarray(np.clip(np.rint(img), 0, 255).astype(np.uint8)).save(tmp_path / "j.png")
    assert jpeg_forensics.dct_chi_square(tmp_path / "j.png", qt).title.startswith("Coefficienti DCT compatibili")


def test_signature_validation_and_audio_formats(dataset):
    assert signature.identify_bytes(bytes([0xFF, 0xFB, 0x90, 0x64]) + bytes(20)) == "mp3"
    assert signature.identify_bytes(b"ID3\x04\x00\x00" + bytes(20)) == "mp3"
    assert signature.identify_bytes(b"fLaC" + bytes(20)) == "flac"
    assert not signature.validate(b"RIFF" + (10 ** 9).to_bytes(4, "little") + b"abcd", "RIFF", 100)
    assert signature.validate(b"PK\x03\x04\x14\x00\x00\x00\x08\x00" + bytes(16) + b"\x05\x00", "ZIP", 1000)
