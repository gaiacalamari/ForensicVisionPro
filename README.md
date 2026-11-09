# Forensic Vision Pro 

Suite desktop per l'analisi forense di immagini (e, in parte, video e audio): acquisizione con hash verificati e catena di custodia, struttura dei file, metadati, analisi temporale, storia di compressione JPEG, copy-move, filtro mediano, PRNU, steganalisi e StegoIntelligence, persone e movimento (stima della posa e discontinuità, metodologia Sports2D), confronto tra immagini, Hex Viewer e report.

## Build per Windows (consigliata)

Doppio clic su **`build_windows.bat`**. Serve solo una connessione a Internet: la build installa e verifica da sola tutto il necessario (Python 3.12, dipendenze, ExifTool, FFmpeg, Inno Setup), esegue i test e controlla l'eseguibile finito.

Risultato in `dist\`:

- `ForensicVisionPro\ForensicVisionPro.exe` — programma pronto all'uso, strumenti inclusi
- `ForensicVisionPro-1.1.0-portable.zip` — versione portable (casi e impostazioni accanto all'eseguibile)
- `installer\ForensicVisionPro-1.1.0-setup.exe` — installer
- `SHA256SUMS.txt` — hash dei file prodotti

Il registro completo è in `build\build.log`; i controlli di sistema sono in `build\selfcheck-*.json`.

## Uso

1. **Casi**: inserisci operatore, Case ID e titolo, poi crea il caso (o aprine uno esistente).
2. **Carica e analizza**: aggiungi immagini o cartelle e avvia l'analisi.
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

## Documentazione

- `docs/MANUALE_UTENTE.md` — manuale utente
- `docs/STATUS.md` — funzionalità incluse e non incluse
- `CHANGELOG.md`
