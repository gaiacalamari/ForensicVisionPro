# PyInstaller spec: cartella "onedir" (avvio rapido; base per installer e versione portable).
# Uso: pyinstaller packaging/fvp.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root = Path(SPECPATH).parent
bin_dir = root / "bin"
datas = []
# Strumenti esterni scaricati e verificati da tools/fetch_tools.py (eseguibili, exiftool_files, tools.lock.json)
if bin_dir.is_dir():
    for p in bin_dir.iterdir():
        if p.name in ("README.txt", "tools.json"):
            continue
        datas.append((str(p), "bin/" + p.name if p.is_dir() else "bin"))
# Dati di OpenCV (classificatori Haar per il rilevamento dei volti)
datas += collect_data_files("cv2", includes=["data/*.xml"])
datas += [(str(root / "docs"), "docs"), (str(root / "THIRD_PARTY_NOTICES.md"), ".")]
# Licenze di terze parti: raccolte da tools/collect_licenses.py (build_windows.ps1); in mancanza, i testi del repository
lic = root / "build" / "third_party_licenses"
datas += [(str(lic if lic.is_dir() else root / "licenses"), "licenses")]

# ONNX Runtime (stima della posa): DLL native; i modelli .onnx sono in bin/ come gli altri strumenti
try:
    binaries = collect_dynamic_libs("onnxruntime")
except Exception:  # noqa: BLE001 - modulo facoltativo
    binaries = []

a = Analysis([str(root / "src" / "fvp" / "__main__.py")], pathex=[str(root / "src")], datas=datas, binaries=binaries,
             hiddenimports=["PIL.ImageCms", "PIL.JpegImagePlugin", "fvp.core.selfcheck",
                            # HEIC: modulo nativo di primo livello; le DLL (pillow_heif.libs) sono risolte
                            # dall'analisi delle dipendenze. Il self-check sull'eseguibile finito lo verifica.
                            "pillow_heif", "pillow_heif.as_plugin", "_pillow_heif",
                            "onnxruntime", "onnxruntime.capi._pybind_state"],
             excludes=["tkinter", "matplotlib", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                       "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtMultimedia",
                       "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtPositioning"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ForensicVisionPro", console=False,
          icon=str(root / "packaging" / "fvp.ico") if (root / "packaging" / "fvp.ico").exists() else None)
coll = COLLECT(exe, a.binaries, a.datas, name="ForensicVisionPro")
