"""Video Analysis Engine: FFprobe (stream, container, tempi) e controlli di coerenza."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from ..core.findings import Category, Finding, Level
from ..core.tools import ToolError, get_tool, run

MODULE = "video"


def probe(path: str | Path, ffprobe_path: str = "", timeout: int = 120) -> dict:
    tool = get_tool("ffprobe", ffprobe_path)
    if not tool:
        raise ToolError("FFprobe non trovato: installare FFmpeg o indicarne il percorso nelle impostazioni")
    raw = run([tool.path, "-v", "error", "-hide_banner", "-show_format", "-show_streams", "-show_chapters",
               "-of", "json", str(Path(path).resolve())], timeout=timeout)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    data["_tool"] = tool.version
    return data


def _frac(s: str | None) -> float | None:
    try:
        f = Fraction(s)
        return float(f) if f.denominator else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def summarize(data: dict) -> dict:
    fmt = data.get("format", {})
    out = {"container": fmt.get("format_long_name") or fmt.get("format_name"),
           "duration_s": float(fmt["duration"]) if fmt.get("duration") else None,
           "bitrate": int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
           "size": int(fmt["size"]) if fmt.get("size") else None, "tags": fmt.get("tags", {}), "streams": []}
    for s in data.get("streams", []):
        d = {"index": s.get("index"), "type": s.get("codec_type"), "codec": s.get("codec_long_name") or s.get("codec_name"),
             "profile": s.get("profile"), "level": s.get("level"), "time_base": s.get("time_base"),
             "start_time": s.get("start_time"), "duration": s.get("duration"), "nb_frames": s.get("nb_frames"),
             "bit_rate": s.get("bit_rate"), "tags": s.get("tags", {})}
        if s.get("codec_type") == "video":
            d.update({"width": s.get("width"), "height": s.get("height"), "pix_fmt": s.get("pix_fmt"),
                      "color_space": s.get("color_space"), "sar": s.get("sample_aspect_ratio"),
                      "dar": s.get("display_aspect_ratio"), "r_frame_rate": s.get("r_frame_rate"),
                      "avg_frame_rate": s.get("avg_frame_rate"),
                      "rotation": next((sd.get("rotation") for sd in s.get("side_data_list", []) if "rotation" in sd), None)})
        elif s.get("codec_type") == "audio":
            d.update({"sample_rate": s.get("sample_rate"), "channels": s.get("channels"),
                      "channel_layout": s.get("channel_layout")})
        out["streams"].append(d)
    return out


def analyze(summary: dict) -> list[Finding]:
    f: list[Finding] = []
    meth = "Analisi FFprobe"
    vids = [s for s in summary["streams"] if s["type"] == "video"]
    auds = [s for s in summary["streams"] if s["type"] == "audio"]
    for s in vids:
        r, a = _frac(s.get("r_frame_rate")), _frac(s.get("avg_frame_rate"))
        if r and a and abs(r - a) / r > 0.02:
            f.append(Finding(Category.VIDEO_INTEGRITY, Level.INFO, "Frame rate variabile",
                             f"Stream {s['index']}: frame rate nominale {r:.3f}, medio {a:.3f}.", meth, MODULE,
                             limitations="Normale per molti smartphone (VFR); rilevante se la sequenza mostra "
                                         "salti localizzati."))
    if vids and auds:
        dv = [float(s["duration"]) for s in vids if s.get("duration")]
        da = [float(s["duration"]) for s in auds if s.get("duration")]
        if dv and da and abs(max(dv) - max(da)) > 1.0:
            f.append(Finding(Category.AUDIO_INTEGRITY, Level.ANOMALY, "Durata audio e video diverse",
                             f"Video {max(dv):.2f} s, audio {max(da):.2f} s.", meth, MODULE, confidence="media",
                             limitations="Piccole differenze sono normali; differenze ampie sono compatibili con "
                                         "montaggio o sostituzione di una traccia."))
    for s in vids + auds:
        st = s.get("start_time")
        if st and abs(float(st)) > 0.5:
            f.append(Finding(Category.VIDEO_INTEGRITY, Level.INFO, f"Stream {s['index']} non inizia da zero",
                             f"start_time = {st} s.", meth, MODULE,
                             limitations="Comune nei flussi MPEG-TS e nei file tagliati senza ricodifica."))
    enc = summary["tags"].get("encoder") or next((s["tags"].get("encoder") for s in vids if s["tags"].get("encoder")), None)
    if enc:
        low = enc.lower()
        lvl = Level.SUSPICIOUS if any(k in low for k in ("lavf", "lavc", "handbrake", "premiere", "capcut", "davinci")) else Level.INFO
        # il tag è già riportato dal Metadata Engine: qui si interpreta nel contesto del contenitore
        f.append(Finding(Category.VIDEO_INTEGRITY, lvl, f"Encoder dichiarato: {enc}",
                         "Il contenitore dichiara il software di codifica o multiplexing.", meth, MODULE,
                         evidence=f"encoder = {enc}", confidence="media",
                         limitations="Lavf/Lavc indicano un passaggio da FFmpeg o librerie derivate (anche app di "
                                     "messaggistica o conversioni lecite)."))
    if not vids and auds:
        a = auds[0]
        f.append(Finding(Category.AUDIO_INTEGRITY, Level.INFO, "File audio",
                         f"Codec {a.get('codec')}, {a.get('sample_rate')} Hz, {a.get('channels')} canali, durata "
                         f"{a.get('duration') or summary.get('duration_s')} s.", meth, MODULE))
    elif not vids:
        f.append(Finding(Category.VIDEO_INTEGRITY, Level.INFO, "Nessuno stream audio o video", "Il file contiene "
                         "solo dati.", meth, MODULE))
    return f
