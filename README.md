# Forensic Vision Pro 

Suite desktop per l'analisi forense di immagini e video (e, in parte, audio): acquisizione con hash verificati e catena di custodia, struttura dei file, metadati (compresi quelli incorporati nelle tracce video), analisi temporale, storia di compressione JPEG, copy-move, filtro mediano, PRNU, steganalisi e StegoIntelligence, persone e movimento (video annotato, angoli e discontinuità con la metodologia Sports2D; Sports2D e Pose2Sim originali con modello OpenSim), confronto tra immagini, Hex Viewer e report.

**Versione 1.4.0** — analisi video: vedi [CHANGELOG](CHANGELOG.md) e [note di rilascio](docs/RELEASE_NOTES_1.4.0.md).

## Build per Windows (consigliata)

Doppio clic su **`build_windows.bat`**. Serve solo una connessione a Internet: la build installa e verifica da sola tutto il necessario (Python 3.12, dipendenze, ExifTool, FFmpeg, Inno Setup), esegue i test e controlla l'eseguibile finito.

Risultato in `dist\`:

- `ForensicVisionPro\ForensicVisionPro.exe` — programma pronto all'uso, strumenti inclusi
- `ForensicVisionPro-1.4.0-portable.zip` — versione portable (casi e impostazioni accanto all'eseguibile)
- `installer\ForensicVisionPro-1.4.0-setup.exe` — installer
- `SHA256SUMS.txt` — hash dei file prodotti

Il registro completo è in `build\build.log`; i controlli di sistema sono in `build\selfcheck-*.json`.

## Uso

1. **Casi**: inserisci operatore, Case ID e titolo, poi crea il caso (o aprine uno esistente).
2. **Carica e analizza**: aggiungi immagini, video, audio o cartelle e avvia l'analisi (profilo *Completa*).
   Per i video: **Persone e movimento** (video annotato, angoli, modello OpenSim) e **Tutti i dati rinvenuti**.
3. Leggi il **Riepilogo** (sintesi in parole semplici e pulsanti per i dettagli) e genera il report da **Report**.

Dettagli in `docs/MANUALE_UTENTE.md`.

## Da sorgente (sviluppo)

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.lock.txt
python tools/fetch_tools.py                        # strumenti esterni su Windows; su Linux/macOS usa quelli di sistema
PYTHONPATH=src python -m fvp                       # interfaccia
PYTHONPATH=src python -m fvp --selfcheck           # controllo del sistema
PYTHONPATH=src python -m pytest -q                 # test
```

## Crediti e licenze

Forensic Vision Pro si basa su componenti di terze parti, che ringraziamo:

- **Qt for Python**: The Qt Company.
- **Pillow**: Jeffrey A. Clark e collaboratori.
- **NumPy**: NumPy Developers.
- **OpenCV**: OpenCV team.
- **pillow-heif**: Alexander Piskun, che include libheif e libde265 di struktur AG e x265 di MulticoreWare.
- **ONNX Runtime**: Microsoft.
- **ExifTool**: Phil Harvey.
- **FFmpeg**: FFmpeg developers, con build Windows di Gyan Doshi (gyan.dev).
- **Modelli YOLOX e RTMPose**: OpenMMLab.

Il programma si basa anche sulle metodologie di **Sports2D** e **Pose2Sim** di David Pagnon, su **rtmlib** di Tao Jiang e sul catalogo **StegoIntelligence** di CScorza.

Autori, licenze, sorgenti dei componenti copyleft e obblighi di ridistribuzione sono in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md); i testi integrali delle licenze sono in [`licenses/`](licenses/). Dal programma: Impostazioni → Crediti e licenze, oppure `ForensicVisionPro --credits crediti.txt`.

## Documentazione

- `docs/MANUALE_UTENTE.md` — manuale utente
- `docs/STATUS.md` — funzionalità incluse e non incluse
- `CHANGELOG.md`
