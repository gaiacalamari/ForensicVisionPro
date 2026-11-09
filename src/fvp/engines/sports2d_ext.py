"""Sports2D e Pose2Sim originali (David Pagnon, BSD-3-Clause) eseguiti sul reperto.

Il modulo "pose" di Forensic Vision Pro riproduce la metodologia di Sports2D con modelli verificati da hash. Questo
modulo esegue invece i programmi originali, così i risultati si possono confrontare e presentare con gli stessi
strumenti usati in biomeccanica:

- Sports2D (https://github.com/davidpagnon/Sports2D): posa 2D con RTMLib, video annotato, angoli (.mot),
  traiettorie (.trc), conversione pixel -> metri;
- Pose2Sim (https://github.com/perfanalytics/pose2sim), dipendenza di Sports2D: filtri, conversione in metri,
  scalatura di un modello muscoloscheletrico OpenSim (.osim) e cinematica inversa (.mot), da aprire con OpenSim
  (https://simtk.org/projects/opensim) per vedere il modello 3D che ripete il movimento del video.

I due programmi girano in un ambiente Python separato (vedi tools/install_sports2d.py): hanno dipendenze proprie
(PyQt, OpenSim, OpenVINO) incompatibili con l'eseguibile e non modificano l'ambiente di Forensic Vision Pro.

Precauzioni forensi:
- Sports2D lavora su una copia della copia di lavoro, in una cartella degli artifacts del caso, con hash verificato
  prima dell'esecuzione: il reperto non viene mai passato al programma esterno;
- comando, versioni dei pacchetti, durata, codice di uscita e registro completo sono conservati;
- ogni file prodotto è registrato con SHA-256;
- RTMLib scarica i modelli alla prima esecuzione senza un'impronta fissata: dopo l'esecuzione vengono registrati gli
  SHA-256 dei modelli presenti nella sua cache, così la verifica resta possibile a posteriori.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from ..core.config import default_home
from ..core.findings import Category, Finding, Level
from ..core.tasks import CancelToken

MODULE = "sports2d"
METHOD = "Sports2D / Pose2Sim originali (D. Pagnon), ambiente Python separato"
PACKAGES = ("sports2d", "pose2sim", "rtmlib", "onnxruntime", "openvino", "opencv-python", "opensim", "numpy")
VIDEO_EXT = (".mp4", ".avi", ".mov", ".mkv")
DEFAULT_HEIGHT_M = 1.70        # Sports2D: default_height; usata solo se la statura non è documentata

OPENSIM_README = """Modello OpenSim prodotto da Sports2D/Pose2Sim (Forensic Vision Pro)

Come vederlo:
1. Installare OpenSim (gratuito): https://simtk.org/projects/opensim  (versione 4.5 o successiva)
2. OpenSim > File > Open Model...      scegliere il file .osim (modello scalato sulla persona)
3. OpenSim > File > Load Motion...     scegliere il file *_ik.mot della stessa persona
4. Premere Play nella barra in basso: il modello ripete il movimento del video.

Il file *_m_*.trc (marcatori in metri) si può sovrapporre con File > Preview Experimental Data.

{height_note}
Gli SHA-256 di tutti i file sono registrati nell'analisi del caso (Forensic Vision Pro, pagina Persone e movimento).
"""


class Sports2DUnavailable(RuntimeError):
    pass


def env_dir() -> Path:
    return default_home() / "sports2d-env"


def _env_python(d: Path) -> Path:
    return d / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def find_python(settings=None) -> Path | None:
    """Interprete dell'ambiente con Sports2D: impostazioni, poi <home>/sports2d-env."""
    cand = []
    if settings is not None and getattr(settings, "sports2d_python", ""):
        cand.append(Path(settings.sports2d_python))
    cand.append(_env_python(env_dir()))
    for c in cand:
        if c.is_dir():
            c = _env_python(c)
        if c.is_file():
            return c
    return None


def _no_window() -> dict:
    return {"creationflags": 0x08000000} if os.name == "nt" else {}       # CREATE_NO_WINDOW


def versions(py: Path, timeout: int = 120) -> dict[str, str]:
    code = ("import json, importlib.metadata as m\n"
            "out = {}\n"
            f"for p in {list(PACKAGES)!r}:\n"
            "    try: out[p] = m.version(p)\n"
            "    except Exception: out[p] = ''\n"
            "import sys; out['python'] = sys.version.split()[0]\n"
            "print(json.dumps(out))")
    r = subprocess.run([str(py), "-c", code], capture_output=True, timeout=timeout, **_no_window())
    if r.returncode:
        raise Sports2DUnavailable(f"l'interprete {py} non risponde: {r.stderr.decode(errors='replace')[-400:]}")
    return json.loads(r.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])


def status(settings=None) -> dict:
    """Per l'interfaccia: interprete trovato e versioni di Sports2D/Pose2Sim."""
    py = find_python(settings)
    if not py:
        return {"ok": False, "detail": f"ambiente non trovato (atteso in {env_dir()})"}
    try:
        v = versions(py)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "python": str(py), "detail": str(e)}
    if not v.get("sports2d"):
        return {"ok": False, "python": str(py), "versions": v, "detail": "Sports2D non installato nell'ambiente"}
    return {"ok": True, "python": str(py), "versions": v,
            "detail": f"Sports2D {v['sports2d']} · Pose2Sim {v.get('pose2sim') or '—'} · "
                      f"OpenSim {v.get('opensim') or 'non installato (niente modello .osim)'}"}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _entry(p: Path, base: Path) -> dict:
    return {"path": str(p), "rel": p.relative_to(base).as_posix(), "sha256": _sha256(p), "size": p.stat().st_size}


def height_for(settings=None) -> tuple[float, bool]:
    """(statura in metri, True se presunta). Serve a Sports2D per la conversione pixel -> metri e quindi al modello
    OpenSim: senza statura documentata si usa quella predefinita di Sports2D, dichiarandolo nei risultati."""
    h = float(getattr(settings, "sports2d_person_height_m", 0.0) or 0.0)
    return (h, False) if h > 0 else (DEFAULT_HEIGHT_M, True)


def build_command(py: Path, video: Path, result_dir: Path, settings=None) -> list[str]:
    """Riga di comando di Sports2D: nessuna finestra interattiva, tutte le persone. Con OpenSim attivo (predefinito)
    converte in metri e chiede a Pose2Sim scalatura e cinematica inversa; altrimenti resta in pixel salvo statura
    documentata."""
    h, _assumed = height_for(settings)
    opensim = bool(getattr(settings, "sports2d_opensim", True)) if settings is not None else True
    documented = float(getattr(settings, "sports2d_person_height_m", 0.0) or 0.0) > 0
    cmd = [str(py), "-m", "Sports2D.Sports2D",
           "--video_dir", str(video.parent), "--video_input", video.name, "--result_dir", str(result_dir),
           "--nb_persons_to_detect", "all", "--person_ordering_method", "highest_likelihood",
           "--show_realtime_results", "false", "--show_graphs", "false",
           "--save_vid", "true", "--save_img", "false", "--save_pose", "true",
           "--calculate_angles", "true", "--save_angles", "true", "--mode", "balanced"]
    if opensim:
        cmd += ["--to_meters", "true", "--first_person_height", f"{h:g}", "--default_height", f"{h:g}",
                "--do_ik", "true", "--do_augmentation", "false",
                "--use_simple_model", "true" if getattr(settings, "sports2d_simple_model", False) else "false"]
        m = float(getattr(settings, "sports2d_person_mass_kg", 0.0) or 0.0)
        if m > 0:
            cmd += ["--participant_mass", f"{m:g}"]
    elif documented:
        cmd += ["--to_meters", "true", "--first_person_height", f"{h:g}", "--do_ik", "false"]
    else:
        cmd += ["--to_meters", "false", "--do_ik", "false"]
    return cmd


def _rtmlib_models() -> list[dict]:
    """Modelli nella cache di RTMLib (scaricati da OpenMMLab alla prima esecuzione), con SHA-256."""
    out = []
    for d in {Path.home() / ".cache" / "rtmlib", Path(os.environ.get("XDG_CACHE_HOME", "")) / "rtmlib"}:
        if str(d).strip() and d.is_dir():
            for f in sorted(d.rglob("*.onnx")):
                out.append({"file": f.name, "path": str(f), "sha256": _sha256(f), "size": f.stat().st_size})
    return out


ProgressFn = Callable[[float, str], None]


def run(working_copy: str | Path, out_dir: Path, settings=None, progress: ProgressFn | None = None,
        cancel: CancelToken | None = None, expected_sha256: str = "") -> tuple[dict, list[Finding]]:
    progress = progress or (lambda _f, _m: None)
    py = find_python(settings)
    if not py:
        raise Sports2DUnavailable(f"ambiente Sports2D non trovato (atteso in {env_dir()} o nelle impostazioni)")
    ver = versions(py)
    if not ver.get("sports2d"):
        raise Sports2DUnavailable(f"Sports2D non è installato nell'ambiente {py.parent.parent}")
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir, onerror=lambda f, p, _e: (os.chmod(p, stat.S_IWRITE), f(p)))
    inp, res_dir = out_dir / "input", out_dir / "risultati"
    inp.mkdir(parents=True)
    res_dir.mkdir()
    src = Path(working_copy)
    # nome ASCII: Sports2D non salva immagini se il percorso contiene caratteri non ASCII
    video = inp / ("reperto" + (src.suffix.lower() if src.suffix.isascii() else ".mp4"))
    shutil.copyfile(src, video)
    in_hash = _sha256(video)
    if expected_sha256 and in_hash != expected_sha256:
        raise RuntimeError("la copia passata a Sports2D non corrisponde all'hash della copia di lavoro")
    os.chmod(video, stat.S_IREAD)
    cmd = build_command(py, video, res_dir, settings)
    env = dict(os.environ, MPLBACKEND="Agg", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    log_path = out_dir / "sports2d.log"
    timeout = int(getattr(settings, "sports2d_timeout_s", 7200) or 7200)
    progress(0.05, f"Sports2D {ver['sports2d']}: stima della posa in corso")
    t0 = time.time()
    with open(log_path, "wb") as log:
        log.write(("$ " + subprocess.list2cmdline(cmd) + "\n\n").encode("utf-8"))
        log.flush()
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(out_dir), env=env, **_no_window())
        try:
            while proc.poll() is None:
                if cancel:
                    try:
                        cancel.check()
                    except BaseException:
                        proc.kill()
                        raise
                el = time.time() - t0
                if el > timeout:
                    proc.kill()
                    raise TimeoutError(f"Sports2D non ha terminato entro {timeout} s")
                progress(min(0.9, 0.05 + el / max(timeout, 1) * 4), f"Sports2D in esecuzione da {el:.0f} s")
                time.sleep(0.5)
        finally:
            if proc.poll() is None:
                proc.kill()
    dur = round(time.time() - t0, 1)
    progress(0.92, "Sports2D: registrazione dei file prodotti")
    outputs = {}
    for f in sorted(res_dir.rglob("*")):
        if f.is_file():
            e = _entry(f, out_dir)
            outputs[e["rel"]] = e
    log_e = _entry(log_path, out_dir)
    tail = log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
    vids = [e for e in outputs.values() if e["rel"].lower().endswith(VIDEO_EXT)]
    mots = [e for e in outputs.values() if e["rel"].lower().endswith(".mot")]
    trcs = [e for e in outputs.values() if e["rel"].lower().endswith(".trc")]
    pngs = [e for e in outputs.values() if e["rel"].lower().endswith(".png")]
    osims = [e for e in outputs.values() if e["rel"].lower().endswith(".osim")]
    iks = [e for e in mots if e["rel"].lower().endswith("_ik.mot")]
    mots = [e for e in mots if e not in iks]
    want_osim = "--do_ik" in cmd and cmd[cmd.index("--do_ik") + 1] == "true"
    h, assumed = height_for(settings)
    if osims:      # istruzioni accanto ai file, per chi riceve la cartella
        note = (f"ATTENZIONE: statura non documentata, usata quella predefinita di {h:g} m. Le dimensioni del modello e "
                "gli spostamenti in metri sono in scala arbitraria; gli angoli articolari non dipendono dalla statura."
                if assumed else f"Statura documentata indicata dall'operatore: {h:g} m.")
        rd = Path(osims[0]["path"]).parent / "LEGGIMI_OpenSim.txt"
        rd.write_text(OPENSIM_README.format(height_note=note), encoding="utf-8")
        e = _entry(rd, out_dir)
        outputs[e["rel"]] = e
    res = {"python": str(py), "versions": ver, "command": cmd, "returncode": proc.returncode, "duration_s": dur,
           "input": {"path": str(video), "sha256": in_hash}, "outputs": outputs, "log": log_e,
           "video": vids[0]["path"] if vids else "", "mot": [e["path"] for e in mots],
           "trc": [e["path"] for e in trcs], "models_cache": _rtmlib_models(), "artifacts": {},
           "opensim": {"requested": want_osim, "model": [e["path"] for e in osims], "motion": [e["path"] for e in iks],
                       "height_m": h if (want_osim or not assumed) else None, "height_assumed": assumed and want_osim,
                       "opensim_version": ver.get("opensim", "")}}
    if pngs:
        res["artifacts"]["sports2d_angles"] = pngs[0]["path"]
    after = _sha256(video)
    findings = []
    ev = (f"Sports2D {ver.get('sports2d')}, Pose2Sim {ver.get('pose2sim') or '—'}, RTMLib {ver.get('rtmlib') or '—'}, "
          f"Python {ver.get('python')}\nComando: {subprocess.list2cmdline(cmd)}")
    if after != in_hash:
        findings.append(Finding(Category.HUMAN_POSE, Level.UNDETERMINED, "Sports2D ha modificato il file di input",
                                "La copia passata a Sports2D è cambiata durante l'esecuzione: i risultati non vanno "
                                "usati.", METHOD, MODULE, evidence=f"prima {in_hash}\ndopo {after}"))
    if proc.returncode != 0 or not (mots or trcs or vids):
        findings.append(Finding(Category.HUMAN_POSE, Level.UNDETERMINED,
                                "Sports2D originale non completato",
                                f"Codice di uscita {proc.returncode}, {len(outputs)} file prodotti. Le ultime righe del "
                                "registro sono riportate come evidenza.", METHOD, MODULE, evidence=tail[-1500:],
                                limitations="Alla prima esecuzione RTMLib scarica i modelli: serve Internet. Il "
                                            "registro completo è sports2d.log negli artifacts."))
    else:
        findings.append(Finding(
            Category.HUMAN_POSE, Level.INFO,
            f"Sports2D originale eseguito: {len(vids)} video annotato, {len(mots)} file di angoli, {len(trcs)} di "
            "traiettorie",
            f"Analisi indipendente con i programmi originali in {dur} s. I risultati sono affiancati a quelli di "
            "Forensic Vision Pro nella pagina Persone e movimento per il confronto.", METHOD, MODULE, evidence=ev,
            confidence="n/a",
            limitations="RTMLib scarica i modelli senza un'impronta fissata: gli SHA-256 dei modelli in cache sono "
                        "registrati nei risultati. L'ordine e la numerazione delle persone possono differire da "
                        "quelli di Forensic Vision Pro." + (
                            f" Statura documentata: {h:g} m." if not assumed else
                            f" Statura non documentata: per il modello OpenSim è usata quella predefinita ({h:g} m)."
                            if want_osim else " Nessuna conversione in metri: statura non indicata."),
            data={"outputs": {k: v["sha256"] for k, v in outputs.items()}}))
    if want_osim and proc.returncode == 0:
        if osims and iks:
            findings.append(Finding(
                Category.HUMAN_POSE, Level.INFO,
                f"Modello OpenSim creato: {len(osims)} modello scalato (.osim), {len(iks)} movimento (.mot)",
                "Pose2Sim ha scalato un modello muscoloscheletrico OpenSim sulle proporzioni della persona e calcolato "
                "la cinematica inversa: aprendo il .osim e poi il *_ik.mot con OpenSim il modello 3D ripete il "
                "movimento del video (istruzioni in LEGGIMI_OpenSim.txt).", "Pose2Sim: scaling + inverse kinematics "
                f"OpenSim {ver.get('opensim') or ''}".strip(), MODULE,
                evidence="\n".join(f"{Path(e['path']).name}  SHA-256 {e['sha256']}" for e in osims + iks),
                confidence="n/a",
                limitations=("Statura non documentata: usata quella predefinita di Sports2D "
                             f"({h:g} m), quindi dimensioni e spostamenti in metri sono in scala arbitraria; gli angoli "
                             "articolari non ne dipendono. " if assumed else f"Statura documentata: {h:g} m. ")
                            + "Da un solo video la profondità è stimata (modello 2D proiettato): rotazioni fuori dal "
                              "piano della ripresa e lato non visibile sono poco affidabili. Non è una misura "
                              "antropometrica.",
                data={"model": [e["sha256"] for e in osims], "motion": [e["sha256"] for e in iks]}))
        else:
            findings.append(Finding(
                Category.HUMAN_POSE, Level.UNDETERMINED, "Modello OpenSim non prodotto",
                "Sports2D è terminato ma Pose2Sim non ha prodotto il modello .osim o il movimento *_ik.mot. Cause "
                "frequenti: OpenSim non installato nell'ambiente, persona non visibile per intero, meno di 4 frame "
                "validi, lato visibile non determinabile.", METHOD, MODULE, evidence=tail[-1500:],
                limitations="Il registro completo è sports2d.log negli artifacts."
                            + ("" if ver.get("opensim") else " Il pacchetto 'opensim' non risulta installato.")))
    progress(1.0, "Sports2D completato")
    return res, findings


def install_command(python: str | Path, target: Path | None = None) -> list[list[str]]:
    """Comandi per creare l'ambiente separato e installare Sports2D (che installa Pose2Sim)."""
    target = target or env_dir()
    py = _env_python(target)
    return [[str(python), "-m", "venv", str(target)],
            [str(py), "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check"],
            [str(py), "-m", "pip", "install", "sports2d", "--disable-pip-version-check"]]


if __name__ == "__main__":   # pragma: no cover - diagnostica manuale
    print(json.dumps(status(), indent=2, ensure_ascii=False))
    sys.exit(0)
