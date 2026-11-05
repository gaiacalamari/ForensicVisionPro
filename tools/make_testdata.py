"""Genera il dataset di test sintetico (FASE 9, prima parte).

Ogni file ha una "verità nota" documentata in testdata/MANIFEST.json, così i test
verificano che i moduli rilevino esattamente ciò che è stato introdotto.
Richiede Pillow e numpy; ExifTool e FFmpeg sono usati se presenti.
"""
from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fvp.core.tools import locate  # noqa: E402  (stessa ricerca del programma: bin/ poi PATH)

EXIFTOOL = locate("exiftool")
FFMPEG = locate("ffmpeg")


def scene(w=1024, h=768, seed=7) -> Image.Image:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    base = np.stack([(x / w) * 180 + 40, (y / h) * 160 + 50, ((x + y) / (w + h)) * 120 + 60], axis=2)
    img = Image.fromarray(np.clip(base + rng.normal(0, 6, base.shape), 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for i in range(14):
        cx, cy = rng.integers(50, w - 50), rng.integers(50, h - 50)
        r = int(rng.integers(15, 60))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    return img


SANS = ["DejaVuSans.ttf", "arial.ttf", "Arial.ttf", "LiberationSans-Regular.ttf", "Helvetica.ttc"]
MONO = ["DejaVuSansMono.ttf", "consola.ttf", "cour.ttf", "LiberationMono-Regular.ttf", "Menlo.ttc"]


def load_font(size: int, mono: bool = False):
    """Font disponibile su Linux, Windows o macOS; in mancanza, il font scalabile incluso in Pillow.
    FVP_TESTDATA_FONT=default forza il font di Pillow (usato per verificare il comportamento su altri sistemi)."""
    from PIL import ImageFont
    import os
    if os.environ.get("FVP_TESTDATA_FONT") != "default":
        for name in (MONO if mono else SANS):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)          # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def natural(w=1024, h=768, seed=11) -> np.ndarray:
    """Immagine con texture e rumore continui, statisticamente più vicina a una fotografia."""
    import cv2
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w]
    base = np.stack([(x / w) * 180 + 40 + 20 * np.sin(y / 37), (y / h) * 160 + 50 + 15 * np.cos(x / 23),
                     ((x + y) / (w + h)) * 120 + 60], axis=2)
    tex = cv2.GaussianBlur(rng.normal(0, 25, base.shape), (0, 0), 3)
    return np.clip(base + tex + rng.normal(0, 6, base.shape), 0, 255).astype(np.uint8)


def exif_bytes(dto="2026:09:12 10:15:30", modify=None, software=None, make="Canon", model="EOS 90D", offset="+02:00",
               gps=True):
    ex = Image.Exif()
    if make:
        ex[0x010F] = make
    if model:
        ex[0x0110] = model
    ex[0x0132] = modify or dto
    if software:
        ex[0x0131] = software
    sub = ex.get_ifd(0x8769)
    sub[0x9003] = dto
    sub[0x9004] = dto
    if offset:
        sub[0x9011] = offset
        sub[0x9010] = offset
    if gps:
        g = ex.get_ifd(0x8825)
        g[1], g[2] = "N", (45.0, 4.0, 12.5)
        g[3], g[4] = "E", (7.0, 41.0, 3.2)
        g[7] = (8.0, 15.0, 29.0)        # 08:15:29 UTC = 10:15:29 +02:00
        g[29] = "2026:09:12"
    return ex.tobytes()


def exiftool(*args):
    if EXIFTOOL:
        subprocess.run([EXIFTOOL, "-q", "-overwrite_original", *args], check=True)


def main(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    man: dict = {}
    img = scene()
    p = out / "original.jpg"
    img.save(p, "JPEG", quality=92, exif=exif_bytes())
    if EXIFTOOL:
        th = out / "_th.jpg"
        img.resize((160, 120)).save(th, "JPEG", quality=80)
        exiftool(f"-ThumbnailImage<={th}", str(p))
        th.unlink()
    man["original.jpg"] = {"expect": "nessuna anomalia significativa; fuso orario coerente con GPS"}

    edited = img.copy()
    ImageDraw.Draw(edited).rectangle([600, 300, 820, 520], fill=(20, 200, 30))
    p2 = out / "edited_photoshop.jpg"
    edited.save(p2, "JPEG", quality=85, exif=exif_bytes(modify="2026:09:20 18:02:11",
                                                         software="Adobe Photoshop 25.0 (Windows)"))
    if EXIFTOOL:
        th = out / "_th.jpg"
        img.resize((160, 120)).save(th, "JPEG", quality=80)   # miniatura dell'originale: non aggiornata
        exiftool(f"-ThumbnailImage<={th}", str(p2))
        th.unlink()
    man["edited_photoshop.jpg"] = {"expect": ["Software di elaborazione", "File salvato dopo lo scatto",
                                              "Contenuto della miniatura diverso"]}

    img.save(out / "future_date.jpg", "JPEG", quality=90, exif=exif_bytes(dto="2031:01:01 12:00:00", gps=False))
    man["future_date.jpg"] = {"expect": ["Data futura"]}

    img.save(out / "modify_before_capture.jpg", "JPEG", quality=90,
             exif=exif_bytes(dto="2026:09:12 10:15:30", modify="2026:09:01 08:00:00", gps=False))
    man["modify_before_capture.jpg"] = {"expect": ["ModifyDate precedente a DateTimeOriginal"]}

    img.save(out / "gps_mismatch.jpg", "JPEG", quality=90, exif=exif_bytes(dto="2026:09:12 16:47:30"))
    man["gps_mismatch.jpg"] = {"expect": ["Orario GPS incoerente con lo scatto"]}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hidden.txt", "dati nascosti")
    (out / "trailing_zip.jpg").write_bytes((out / "original.jpg").read_bytes() + buf.getvalue())
    man["trailing_zip.jpg"] = {"expect": ["Dati dopo la fine dell'immagine", "Firme di altri formati"]}

    data = (out / "original.jpg").read_bytes()
    (out / "truncated.jpg").write_bytes(data[: len(data) * 2 // 3])
    man["truncated.jpg"] = {"expect": ["EOI mancante"]}

    shutil.copy(out / "original.jpg", out / "renamed_jpeg.png")
    man["renamed_jpeg.png"] = {"expect": ["Estensione non coerente"]}

    img.save(out / "clean.png", "PNG")
    man["clean.png"] = {"expect": "nessuna anomalia strutturale"}
    raw = bytearray((out / "clean.png").read_bytes())
    i = raw.find(b"IDAT")
    raw[i + 10] ^= 0xFF
    (out / "bad_crc.png").write_bytes(bytes(raw))
    man["bad_crc.png"] = {"expect": ["CRC errato nel chunk IDAT"]}

    from PIL import PngImagePlugin
    meta = PngImagePlugin.PngInfo()
    meta.add_text("parameters", "a photo of a cat\nSteps: 30, Sampler: DPM++ 2M, CFG scale: 7, Seed: 1234")
    img.save(out / "ai_params.png", "PNG", pnginfo=meta)
    man["ai_params.png"] = {"expect": ["Metadati riferiti a generazione AI"]}

    # ---- storia di compressione, copy-move, filtro mediano, steganografia
    import cv2
    a = np.asarray(img)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    low = np.asarray(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
    sp = a.copy()
    sp[300:500, 600:820] = low[300:500, 600:820]
    Image.fromarray(sp).save(out / "splice_ghost.jpg", "JPEG", quality=92)
    man["splice_ghost.jpg"] = {"expect": ["JPEG ghost a qualità 60"], "region": [600, 300, 820, 500]}
    Image.fromarray(low).save(out / "double_compressed.jpg", "JPEG", quality=90)
    man["double_compressed.jpg"] = {"expect": ["Indizi di doppia compressione JPEG"]}
    Image.fromarray(low).save(out / "jpeg_history.png")
    man["jpeg_history.png"] = {"expect": ["Storia di compressione JPEG in un file non JPEG"]}
    rng = np.random.default_rng(3)
    cm = a.copy()
    patch = cv2.GaussianBlur(rng.integers(0, 255, (120, 120, 3)).astype(np.uint8), (5, 5), 0)
    cm[100:220, 100:220] = patch
    cm[450:570, 700:820] = patch
    Image.fromarray(cm).save(out / "copy_move.png")
    man["copy_move.png"] = {"expect": ["Regioni duplicate (copy-move)"], "region": [700, 450, 820, 570]}
    nat = natural()
    Image.fromarray(nat).save(out / "natural.png")
    man["natural.png"] = {"expect": "nessuna anomalia significativa"}
    ml = nat.copy()
    ml[200:500, 300:700] = cv2.medianBlur(nat, 3)[200:500, 300:700]
    Image.fromarray(ml).save(out / "median_local.png")
    man["median_local.png"] = {"expect": ["Regione con elaborazione diversa"], "region": [300, 200, 700, 500]}
    st = nat.copy()
    m = rng.random(st.shape) < 0.5
    st[m] = (st[m] & 0xFE) | rng.integers(0, 2, int(m.sum())).astype(np.uint8)
    Image.fromarray(st).save(out / "stego_lsb_random.png")
    man["stego_lsb_random.png"] = {"expect": ["Stima RS elevata"]}
    sq = nat.copy().reshape(-1)
    n = len(sq) // 10
    sq[:n] = (sq[:n] & 0xFE) | rng.integers(0, 2, n).astype(np.uint8)
    Image.fromarray(sq.reshape(nat.shape)).save(out / "stego_lsb_sequential.png")
    man["stego_lsb_sequential.png"] = {"expect": ["Chi-quadro compatibile con inserimento sequenziale"]}

    # ---- StegoIntelligence: contenuti in chiaro nei bit meno significativi
    import wave

    def embed(arr, payload, channels="RGB", msb=True):
        out = arr.copy()
        idx = ["RGB".index(c) for c in channels]
        bits = np.unpackbits(np.frombuffer(payload, np.uint8), bitorder="big" if msb else "little")
        flat = out.reshape(-1, 3)
        sel = flat[:, idx].reshape(-1)
        sel[:len(bits)] = (sel[:len(bits)] & 0xFE) | bits
        flat[:, idx] = sel.reshape(-1, len(idx))
        return flat.reshape(out.shape)
    secret = "Incontro confermato al porto alle ore 22, portare i documenti del carico.".encode()
    Image.fromarray(embed(nat, secret)).save(out / "stego_text.png")
    man["stego_text.png"] = {"expect": ["Contenuto nascosto estratto: Testo nascosto"], "secret": secret.decode()}
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("segreto.txt", "documento riservato")
    Image.fromarray(embed(nat, zb.getvalue(), "B", msb=False)).save(out / "stego_zip.png")
    man["stego_zip.png"] = {"expect": ["Contenuto nascosto estratto: Archivio ZIP"]}
    Image.fromarray(embed(nat, b"OPENSTEGO" + bytes([2, 0, 0, 1, 0]) + b"payload")).save(out / "stego_openstego.png")
    man["stego_openstego.png"] = {"expect": ["Contenuto nascosto estratto: Intestazione OpenStego"]}
    t = np.arange(44100 * 3)
    pcm = (np.sin(t / 20) * 8000 + np.random.default_rng(0).normal(0, 200, t.size)).astype(np.int16)
    with wave.open(str(out / "audio_clean.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(pcm.tobytes())
    man["audio_clean.wav"] = {"expect": "nessun contenuto nascosto"}
    bits = np.unpackbits(np.frombuffer(secret, np.uint8)).astype(np.int16)
    pcm2 = pcm.copy()
    pcm2[:len(bits)] = (pcm2[:len(bits)] & ~1) | bits
    with wave.open(str(out / "audio_lsb.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(pcm2.tobytes())
    man["audio_lsb.wav"] = {"expect": ["Contenuto nascosto estratto: Testo nascosto"]}

    # ---- 1.1: casi reali di testo nascosto e falsi positivi da evitare
    # messaggio con lunghezza su 8 byte, ordine BGR, bit più significativo per primo (come il file stego.bmp del caso)
    msg = b"This is a very secret message!\n"
    payload = len(msg).to_bytes(8, "big") + msg
    pb = np.unpackbits(np.frombuffer(payload, np.uint8))
    sb = nat.copy()
    flat = sb.reshape(-1, 3)
    sel = flat[:, [2, 1, 0]].reshape(-1)
    sel[:len(pb)] = (sel[:len(pb)] & 0xFE) | pb
    flat[:, [2, 1, 0]] = sel.reshape(-1, 3)
    Image.fromarray(sb).save(out / "stego_bgr_len8.bmp")
    man["stego_bgr_len8.bmp"] = {"expect": ["Contenuto nascosto estratto: Testo nascosto (preceduto dalla sua lunghezza)"],
                                 "secret": msg.decode().strip()}
    font = load_font(28)
    faint = Image.new("RGB", (900, 600), (200, 205, 210))
    ImageDraw.Draw(faint).text((60, 250), "Codice di accesso 7741 - consegna alle 22", fill=(203, 208, 213), font=font)
    faint.save(out / "faint_text.png")
    man["faint_text.png"] = {"expect": ["Possibili segni quasi invisibili"]}
    (out / "trailing_text.jpg").write_bytes((out / "original.jpg").read_bytes() +
                                            b"La password del conto e' nel secondo allegato, non perderla")
    man["trailing_text.jpg"] = {"expect": ["Testo leggibile in aree non previste del file"]}
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Comment", base64.b64encode(b"Consegna confermata domani alle nove presso il magazzino nord").decode())
    Image.fromarray(nat).save(out / "metadata_b64.png", pnginfo=meta)
    man["metadata_b64.png"] = {"expect": ["Contenuti codificati nei metadati"]}
    small = Image.fromarray(nat[:101, :101])
    small.save(out / "bmp_padding.bmp")
    raw = bytearray((out / "bmp_padding.bmp").read_bytes())
    off_px = int.from_bytes(raw[10:14], "little")
    stride = ((101 * 24 + 31) // 32) * 4
    for r_, ch_ in enumerate(b"dati nascosti nel padding"):
        raw[off_px + r_ * stride + 303] = ch_
    (out / "bmp_padding.bmp").write_bytes(bytes(raw))
    man["bmp_padding.bmp"] = {"expect": ["Byte di riempimento delle righe non nulli"]}
    # schermata di terminale fotografata: testo ripetuto che NON deve risultare copiato
    mono = load_font(34, mono=True)
    scr = Image.new("RGB", (1280, 960), (0, 0, 0))
    dr = ImageDraw.Draw(scr)
    rows = ["4096 21. Sep 15:53  bin -> usr/bin", "4096 30. Sep 2015  boot", "  19. Sep 09:31  dev",
            "  21. Sep 15:50  etc", "  30. Sep 2015  home", "4096 23. Jul 10:01  lib -> usr/lib",
            "4096  1. Aug 22:45  lib64 -> usr/lib", "  30. Sep 2015  lost+found", "4096 21. Sep 15:52  mnt",
            "  12. Aug 15:37  opt", "  30. Sep 2015  private", "4096 21. Sep 08:15  proc", "  21. Sep 15:51  root",
            "   7 30. Sep 2015  run", "4096 12. Aug 15:45  sbin -> usr/bin", "4096 23. Jul 10:25  srv",
            "  21. Sep 15:53  sys", "  30. Sep 2015  tmp", "4096 21. Sep 15:39  usr", "  12. Aug 15:45  var"]
    for i, row in enumerate(rows):
        dr.text((20, 20 + i * 46), row, fill=(60, 230, 60) if i % 3 else (80, 140, 255), font=mono)
    import cv2 as _cv2
    sa = np.asarray(scr)
    M = _cv2.getPerspectiveTransform(np.float32([[0, 0], [1280, 0], [1280, 960], [0, 960]]),
                                     np.float32([[0, -40], [1400, 60], [1220, 1000], [-30, 940]]))
    sa = _cv2.GaussianBlur(_cv2.warpPerspective(sa, M, (1280, 960)), (3, 3), 0.8)
    sa = np.clip(sa + np.random.default_rng(0).normal(0, 3, sa.shape), 0, 255).astype(np.uint8)
    Image.fromarray(sa).save(out / "screen_text.jpg", "JPEG", quality=88)
    man["screen_text.jpg"] = {"expect": "nessuna regione duplicata confermata (testo ripetuto)"}

    if FFMPEG:
        def ff(*a):
            subprocess.run([FFMPEG, "-v", "error", "-y", *a], check=True)
        ff("-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=440",
           "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
           "-metadata", "creation_time=2026-09-12T08:15:30Z", str(out / "video_original.mp4"))
        man["video_original.mp4"] = {"expect": ["Encoder dichiarato: Lavf"]}
        ff("-f", "lavfi", "-t", "4", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-t", "1.5", "-i",
           "sine=frequency=440", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
           str(out / "video_short_audio.mp4"))
        man["video_short_audio.mp4"] = {"expect": ["Durata audio e video diverse"]}
        d = (out / "video_original.mp4").read_bytes()
        (out / "video_truncated.mp4").write_bytes(d[: len(d) // 2])
        man["video_truncated.mp4"] = {"expect": ["oltre i limiti del contenitore"]}
        if EXIFTOOL:
            shutil.copy(out / "video_original.mp4", out / "video_track_dates.mp4")
            exiftool("-api", "QuickTimeUTC=0", "-Track1:TrackCreateDate=2026:09:15 10:00:00",
                     "-QuickTime:ModifyDate=2026:09:20 10:00:00", str(out / "video_track_dates.mp4"))
            man["video_track_dates.mp4"] = {"expect": ["Tempi di creazione diversi tra filmato e tracce"]}
    (out / "MANIFEST.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
    return man


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "testdata"
    print(json.dumps(main(target), indent=2, ensure_ascii=False))
