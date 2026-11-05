# PyInstaller spec: cartella "onedir" (avvio rapido; base per installer e versione portable).
# Uso: pyinstaller packaging/fvp.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

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
datas += [(str(root / "docs"), "docs")]

a = Analysis([str(root / "src" / "fvp" / "__main__.py")], pathex=[str(root / "src")], datas=datas,
             hiddenimports=["PIL.ImageCms", "PIL.JpegImagePlugin", "fvp.core.selfcheck"],
             excludes=["tkinter", "matplotlib", "pytest", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                       "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtMultimedia",
                       "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtPositioning"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ForensicVisionPro", console=False,
          icon=str(root / "packaging" / "fvp.ico") if (root / "packaging" / "fvp.ico").exists() else None)
coll = COLLECT(exe, a.binaries, a.datas, name="ForensicVisionPro")
