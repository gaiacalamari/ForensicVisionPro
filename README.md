# Forensic Vision Pro 

Suite desktop per l'analisi forense di immagini e video (e, in parte, audio): acquisizione con hash verificati e catena di custodia, struttura dei file, metadati (compresi quelli incorporati nelle tracce video), analisi temporale, storia di compressione JPEG, copy-move, filtro mediano, PRNU, steganalisi e StegoIntelligence, persone e movimento (video annotato, angoli e discontinuità con la metodologia Sports2D; Sports2D e Pose2Sim originali con modello OpenSim), confronto tra immagini, Hex Viewer e report.

**Versione 1.5.0** — interfaccia semplice a quattro passi, anche per chi non è del mestiere; analisi video dalla 1.4. Vedi il [CHANGELOG](CHANGELOG.md).

## Build per Windows (consigliata)

Doppio clic su **`build_windows.bat`**. Serve solo una connessione a Internet: la build installa e verifica da sola tutto il necessario (Python 3.12, dipendenze, ExifTool, FFmpeg, Inno Setup), esegue i test e controlla l'eseguibile finito.

Risultato in `dist\`:

- `ForensicVisionPro\ForensicVisionPro.exe` — programma pronto all'uso, strumenti inclusi
- `ForensicVisionPro-1.5.0-portable.zip` — versione portable (casi e impostazioni accanto all'eseguibile)
- `installer\ForensicVisionPro-1.5.0-setup.exe` — installer
- `SHA256SUMS.txt` — hash dei file prodotti

Il registro completo è in `build\build.log`; i controlli di sistema sono in `build\selfcheck-*.json`.

## Uso

Il programma si apre nella vista semplice, con quattro passi nel menu:

1. **Apri un caso**: nome dell'operatore, numero e titolo del caso.
2. **Aggiungi i file**: trascina foto, video o cartelle e premi *Avvia l'analisi*.
3. **Leggi i risultati**: sintesi in parole semplici e ciò che merita attenzione.
4. **Crea il report**: HTML, JSON o CSV.

*Come funziona*, in ogni pagina, spiega metodo e limiti; *Passa alla vista esperta* mostra tutte le analisi e gli strumenti.

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
