"""Crea l'ambiente Python separato con Sports2D e Pose2Sim originali, usato dal modulo "sports2d".

Uso (serve Internet e Python 3.11 o successivo a 64 bit):
    py -3.12 tools\\install_sports2d.py                 # Windows, ambiente in <utente>\\ForensicVisionPro\\sports2d-env
    python3 tools/install_sports2d.py --target DIR      # cartella diversa (indicarla poi nelle Impostazioni)

Forensic Vision Pro cerca l'ambiente in <home>/sports2d-env (la stessa cartella dei casi e delle impostazioni;
con la versione portable è data\\sports2d-env accanto all'eseguibile) oppure nel percorso indicato in Impostazioni.
L'elenco esatto dei pacchetti installati è salvato in <ambiente>/pip-freeze.txt per la documentazione.
Alla prima analisi RTMLib scarica i modelli di stima della posa da OpenMMLab; i loro SHA-256 vengono registrati
nei risultati di ogni analisi. Pose2Sim installa anche il pacchetto Python di OpenSim, che produce il modello
scalato (.osim) e la cinematica inversa (.mot); per visualizzarli serve l'applicazione OpenSim
(https://simtk.org/projects/opensim).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def default_target() -> Path:
    base = os.environ.get("FVP_HOME")
    return (Path(base) if base else Path.home() / "ForensicVisionPro") / "sports2d-env"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=Path, default=default_target())
    ap.add_argument("--version", default="", help="versione di Sports2D da installare (es. 0.8.34); vuoto = ultima")
    a = ap.parse_args()
    if sys.version_info < (3, 11):
        print(f"Sports2D richiede Python 3.11 o successivo (in uso {sys.version.split()[0]}).")
        return 1
    if sys.maxsize <= 2 ** 32:
        print("Serve un Python a 64 bit.")
        return 1
    tgt = a.target.resolve()
    py = tgt / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    pkg = f"sports2d=={a.version}" if a.version else "sports2d"
    steps = []
    if not py.is_file():
        steps.append([sys.executable, "-m", "venv", str(tgt)])
    steps += [[str(py), "-m", "pip", "install", "--upgrade", "pip", "--disable-pip-version-check"],
              [str(py), "-m", "pip", "install", "--upgrade", pkg, "--disable-pip-version-check"]]
    for cmd in steps:
        print("$", subprocess.list2cmdline(cmd), flush=True)
        if subprocess.call(cmd):
            print("\nInstallazione non riuscita: vedere i messaggi sopra.")
            return 1
    frz = subprocess.run([str(py), "-m", "pip", "freeze", "--disable-pip-version-check"], capture_output=True,
                         text=True)
    (tgt / "pip-freeze.txt").write_text(frz.stdout, encoding="utf-8")
    chk = subprocess.run([str(py), "-c", "import importlib.metadata as m; "
                                        "print('Sports2D', m.version('sports2d'), '- Pose2Sim', m.version('pose2sim'))"],
                         capture_output=True, text=True)
    print("\n" + (chk.stdout.strip() or chk.stderr.strip()))
    osim = subprocess.run([str(py), "-c", "import opensim; print(opensim.GetVersion())"], capture_output=True,
                          text=True)
    if osim.returncode == 0:
        print(f"OpenSim {osim.stdout.strip()}: modello .osim e cinematica inversa disponibili")
    else:
        print("ATTENZIONE: il pacchetto opensim non si importa, quindi niente modello .osim.\n"
              + (osim.stderr.strip().splitlines() or [""])[-1]
              + f"\nProvare: {py} -m pip install --force-reinstall opensim")
    print(f"Ambiente pronto: {tgt}")
    if tgt != default_target().resolve():
        print(f"Indicare questo interprete in Impostazioni > Sports2D: {py}")
    return 0 if chk.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
