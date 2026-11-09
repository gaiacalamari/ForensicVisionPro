# Forensic Vision Pro — Architettura

## Principi

1. **Preservazione delle evidenze.** L'originale viene solo letto (`open(..., "rb")`), una volta, durante l'acquisizione. Tutte le analisi lavorano su una copia di lavoro resa di sola lettura, con hash verificati prima e dopo ogni analisi.
2. **Trasparenza dei risultati.** Ogni risultato (`Finding`) dichiara livello (evidenza certa, anomalia tecnica, indicatore sospetto, risultato probabilistico, non determinabile, informativo), metodo, evidenza, posizione nel file, confidenza e limiti. Non esiste un punteggio di autenticità.
3. **Riproducibilità.** Ogni analisi registra versione dell'applicazione e degli strumenti esterni, moduli eseguiti, parametri e hash.
4. **Isolamento dai file malevoli.** Parser con limiti espliciti (numero di nodi, profondità, dimensione), strumenti esterni senza shell e con timeout, limite di pixel contro le decompression bomb, nessuna esecuzione di contenuti incorporati.
5. **Moduli indipendenti.** Ogni engine è una funzione pura su un percorso di file che restituisce dati e `Finding`; l'interfaccia non contiene logica forense.

## Componenti

```mermaid
flowchart LR
  subgraph UI[UI PySide6]
    P[Pagine] --> S[AppState + worker in background]
  end
  S --> PL[Pipeline di analisi]
  S --> CM[Case Management]
  PL --> HE[Hash Engine]
  PL --> SG[Signature / Scanner]
  PL --> FP[Parser: JPEG, PNG, ISO BMFF]
  PL --> ME[Metadata Engine]
  PL --> TE[Timestamp Engine]
  PL --> IE[Image Engine]
  PL --> VE[Video Engine]
  ME -.-> XT[(ExifTool)]
  VE -.-> FF[(FFprobe)]
  CM --> DB[(case.db SQLite)]
  CM --> AL[Audit log a catena di hash]
  PL --> CM
  RE[Reporting Engine] --> CM
  S --> RE
```

| Livello | Package | Responsabilità |
|---|---|---|
| Core | `fvp.core` | modello `Finding` e stato per categoria, audit log, configurazione, strumenti esterni, cancellazione, pipeline |
| Engine | `fvp.engines` | hashing, firme, metadati, analisi temporale, immagine, video, posa e cinematica |
| Parser | `fvp.parsers` | struttura binaria dei formati; registro estendibile (`registry.register`) |
| Casi | `fvp.cases` | casi, reperti, acquisizione, analisi salvate, note dell'operatore, custodia |
| Report | `fvp.reporting` | HTML autocontenuto, JSON completo, CSV dei risultati |
| UI | `fvp.ui` | finestra, pagine, widget (Hex Viewer, viste sincronizzate, risultati) |

## Fondamenti scientifici dei moduli d'immagine

| Modulo | Riferimento |
|---|---|
| JPEG ghost | H. Farid, *Exposing digital forgeries from JPEG ghosts*, IEEE TIFS 2009 |
| Doppia quantizzazione | A. Popescu, H. Farid, *Statistical tools for digital forensics*, IH 2004; Z. Lin et al., *Fast, automatic and fine-grained tampered JPEG image detection via DCT coefficient analysis*, Pattern Recognition 2009 |
| Copy-move | I. Amerini et al., *A SIFT-based forensic method for copy-move attack detection*, IEEE TIFS 2011 |
| Steganalisi RS | J. Fridrich, M. Goljan, R. Du, *Reliable detection of LSB steganography in color and grayscale images*, ACM MM&Sec 2001 |
| Chi-quadro | A. Westfeld, A. Pfitzmann, *Attacks on steganographic systems*, IH 1999 |
| Stima della posa | T. Jiang et al., *RTMPose: Real-Time Multi-Person Pose Estimation based on MMPose*, arXiv:2303.07399, 2023; Z. Ge et al., *YOLOX: Exceeding YOLO Series in 2021*, arXiv:2107.08430 |
| Cinematica 2D (angoli, filtri, formati TRC/MOT) | D. Pagnon, H. Kim, *Sports2D: Compute 2D human pose and angles from a video or a webcam*, Journal of Open Source Software 9(101), 6849, 2024; D. Pagnon et al., *Pose2Sim*, JOSS 2022 |
| Filtro Butterworth a fase zero | D. A. Winter, *Biomechanics and Motor Control of Human Movement*, 4ª ed., Wiley 2009, cap. 2 |
| PRNU | J. Lukáš, J. Fridrich, M. Goljan, *Digital camera identification from sensor pattern noise*, IEEE TIFS 2006; M. Goljan, J. Fridrich, T. Filler, *Large scale test of sensor fingerprint camera identification*, SPIE 2009 |
| SSIM | Z. Wang et al., *Image quality assessment: from error visibility to structural similarity*, IEEE TIP 2004 |
| Rumore | J. Immerkær, *Fast noise variance estimation*, CVIU 1996 |

Il modulo StegoIntelligence implementa le tecniche elencate dal progetto StegoIntelligence di CScorza, che è un catalogo di tecniche e strumenti senza codice. Nessuno strumento esterno di steganografia viene eseguito sui reperti.

L'elenco delle funzioni della milestone 2 prende spunto da PixIntelligence (licenza CC BY-NC-SA 4.0): nessuna parte del suo codice è stata copiata, così il progetto non eredita il vincolo di uso non commerciale.

## Modulo Persone e movimento (metodologia Sports2D)

Sports2D non è incluso come pacchetto: dipende da Pose2Sim, che porta con sé OpenSim, OpenVINO, pandas, scipy,
matplotlib, `opencv-python` (in conflitto con `opencv-python-headless`) e `PySide6-essentials` (in conflitto con
PySide6). La metodologia è reimplementata in `engines/pose.py` e `engines/pose_model.py`:

1. **Inferenza** (`pose_model.py`): rilevamento delle persone con YOLOX e stima top-down di 26 keypoint HALPE con
   RTMPose, gli stessi modelli della modalità *balanced* di Sports2D. Pre e post-elaborazione seguono rtmlib e sono
   verificate contro il suo codice. I modelli sono file locali: nessun download a runtime. Ogni modello registrato in
   `tools.lock.json` deve corrispondere all'impronta, altrimenti non viene caricato; lo SHA-256 di entrambi è salvato
   in ogni analisi e nella sezione strumenti del report.
2. **Tracciamento**: associazione greedy per distanza mediana dei keypoint normalizzata sull'altezza della persona;
   rilevamento ogni 4 frame (come `det_frequency` di Sports2D), anticipato se la confidenza cala.
3. **Cinematica** (come Sports2D): angoli con le definizioni, gli offset e il lato visibile di Pose2Sim (verificati
   identici al codice originale), interpolazione dei buchi fino a 10 frame, Butterworth di 4° ordine a 6 Hz in
   avanti e all'indietro (coefficienti e risultato identici a `scipy.signal`). Esportazione in CSV (grezzo), TRC
   (pixel, Y verso l'alto) e MOT, con SHA-256 di ogni file.
4. **Indicatori forensi**, calcolati sui keypoint **grezzi**, perché il filtro attenuerebbe i salti:
   - *salto cinematico*: spostamento mediano dei keypoint affidabili oltre 8 altezze/s e almeno 0,15 altezze tra due
     frame adiacenti;
   - *salto di scala*: rapporto di altezza oltre 1,33 con persona intera visibile in entrambi i frame;
   - *sostituzione*: tutte le persone del frame precedente scompaiono e ne compaiono altre;
   - *conferme indipendenti*: intervallo tra i timestamp oltre 1,8 volte la mediana, differenza globale del frame
     (64×64 in scala di grigi) oltre 4 volte la mediana.
   Una discontinuità è **di scena** se coinvolge tutte le persone presenti e almeno una conferma, più persone o un salto
   netto (≥ 0,5 altezze con confidenza ≥ 0,6), oppure in caso di sostituzione; altrimenti è **isolata**, livello
   probabilistico. Solo le discontinuità di scena confermate sono marcate come significative.
5. **Descrittori**: cadenza del passo dallo spettro della separazione delle caviglie (banda 0,4–1,6 Hz per falcata,
   prominenza ≥ 4); iperestensioni oltre 25° di ginocchio o gomito con persona di profilo, persistenti per almeno 5
   frame nei video.

Nessuna misura è in metri: senza calibrazione della camera non si stimano statura, distanze o velocità assolute.

## Flusso di un'analisi

1. `Case.acquire`: stat dell'originale (prima della lettura, che può aggiornare l'atime) → copia in un solo passaggio con hash multipli → seconda lettura della copia e confronto → `chmod` sola lettura → voce di custodia.
2. `analyze_exhibit`: hash iniziale e confronto con l'acquisizione (se diverso l'analisi si ferma) → firma → struttura → metadati → tempi → immagine o video → scansione delle firme → hash finale.
3. Un errore in un modulo produce un `Finding` "non determinabile" con il motivo e non interrompe gli altri.
4. Risultati, hash e versioni degli strumenti sono salvati nella tabella `analyses`; l'evento è nel registro.

## Registro delle operazioni

Tabella `audit_log`: ogni voce contiene `prev_hash` e `entry_hash = SHA-256(seq, ts, attore, azione, tipo, dettagli, prev_hash)`. I trigger SQLite bloccano UPDATE e DELETE dall'applicazione; chi rimuovesse i trigger con accesso diretto al file renderebbe la modifica rilevabile da `verify()`. L'hash di testa è riportato nel report come ancora esterna: conservarlo fuori dal caso (es. nel verbale) rende rilevabile anche la sostituzione dell'intero registro.

## Controllo del sistema e build

`core/selfcheck.py` verifica pacchetti Python, SIFT, classificatori Haar, ExifTool (lettura reale di un JPEG generato), FFprobe (lettura reale di un WAV generato), integrità dei binari inclusi rispetto a `bin/tools.lock.json` e scrivibilità delle cartelle di lavoro. Viene eseguito all'avvio dell'interfaccia, da Settings e dalla build, prima sui sorgenti e poi sull'eseguibile finito con `ForensicVisionPro.exe --selfcheck report.json`. La build si interrompe se un componente essenziale non funziona.

## Struttura delle cartelle

```
ForensicVisionPro/
├── src/fvp/
│   ├── core/        findings.py, audit.py, pipeline.py, config.py, tools.py, tasks.py, selfcheck.py
│   ├── engines/     hashing.py, signature.py, metadata.py, timestamps.py, image.py, video.py,
│   │                jpeg_forensics.py, image_extra.py, stego.py, stegointel.py, prnu.py, compare.py,
│   │                pose.py (cinematica e indicatori), pose_model.py (inferenza ONNX)
│   ├── parsers/     base.py, jpeg.py, png.py, isobmff.py, registry.py
│   ├── cases/       store.py
│   ├── reporting/   report.py
│   (plugins/ previsto nella milestone 5)
│   └── ui/          app.py, main_window.py, state.py, theme.py, pages/, widgets/
├── tests/           unità, integrazione su dataset a verità nota, UI offscreen
├── tools/           make_testdata.py (dataset sintetico con MANIFEST.json)
├── packaging/       fvp.spec, installer.iss, build_windows.ps1
├── bin/             ExifTool e FFmpeg da includere nella build
└── docs/
```

Ogni caso su disco: `case.db`, `evidence/EXH-NNNN/` (copie di lavoro), `artifacts/EXH-NNNN/` (mappe ELA e rumore), `reports/`.

## Dipendenze

| Componente | Uso | Note |
|---|---|---|
| Python ≥ 3.10 | runtime | testato con 3.12 |
| PySide6 | interfaccia | LGPL |
| Pillow, NumPy, OpenCV (headless) | decodifica e analisi raster | |
| ExifTool ≥ 12.70 | metadati | esterno; fallback limitato su Pillow |
| FFmpeg / FFprobe ≥ 6 | video | esterno |
| ONNX Runtime ≥ 1.17 | stima della posa | facoltativo; solo CPUExecutionProvider |
| Modelli YOLOX-m HumanArt e RTMPose-m HALPE-26 | stima della posa | facoltativi, Apache-2.0; installati in `bin/` da `fetch_tools.py` con SHA-256 fissato, verificati a ogni caricamento |
| pytest, PyInstaller, Inno Setup | test e packaging | solo sviluppo |

Dipendenze previste nelle milestone successive: PyAV (frame), modelli ONNX per AI e deepfake (il runtime è già incluso), ReportLab (PDF), `c2pa-python` (validazione C2PA).

## Strategia di test

- **Unità:** hash confrontati con `hashlib`; manomissione e cancellazione nel registro; acquisizione che non altera originale né mtime; regole di stato per categoria; parsing date e fusi orari.
- **Integrazione:** `tools/make_testdata.py` genera file con una verità nota (modifica localizzata, date future, GPS incoerente, dati accodati, troncamenti, CRC errato, parametri AI, tracce video con date diverse) descritta in `MANIFEST.json`; i test verificano che ogni risultato atteso venga rilevato e che i file puliti non producano risultati significativi.
- **UI:** costruzione di tutte le pagine in modalità offscreen, ricerca nell'Hex Viewer.
- I test che richiedono ExifTool o FFmpeg vengono saltati, con motivazione, se lo strumento manca.
