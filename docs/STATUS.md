# Stato del progetto — versione 1.4.0

## Incluso e verificato

| Area | Dettaglio |
|---|---|
| Flusso di lavoro | Caso obbligatorio, caricamento di immagini singole, multiple o cartelle, trascinamento, profili di analisi |
| Interfaccia | Tema chiaro predefinito e tema scuro, 16 pagine, operazioni in background con avanzamento e annullamento |
| Preservazione delle evidenze | Copia verificata in sola lettura, hash pre/post analisi, audit log a catena di hash, catena di custodia |
| Struttura dei file | JPEG, PNG, ISO BMFF (MP4/MOV), HEIF/HEIC (item, iloc, griglia di tile, miniature, immagini ausiliarie, byte non referenziati), firme incorporate, dati accodati |
| HEIC/HEIF | Decodifica con pillow-heif (libheif): tutte le analisi dei pixel, miniatura HEIF confrontata con l'immagine, anteprime e report |
| Dispositivo | Convenzioni di nome dei file (iPhone, Samsung, Pixel, Android, WhatsApp/Telegram/Signal), ora nel nome, coerenza Model/HostComputer/LensModel, versione di iOS rispetto a modello e date, risoluzione rispetto al modello, dimensioni EXIF/raster, MakerNotes, struttura HEIF tipica dell'iPhone. Profili in `engines/device_db.py`, estendibili con `device_profiles.json` |
| Confronto tra reperti | Abbinamento Live Photo (foto + MOV), più versioni dello stesso scatto, numerazione IMG_xxxx rispetto alle date sullo stesso modello |
| Metadati e tempi | ExifTool con classificazione di attendibilità, timeline, coerenza EXIF/XMP/GPS/contenitore/filesystem |
| Manipolazione | ELA singola e multi-qualità, JPEG ghost, doppia quantizzazione, griglia 8x8, residuo di rumore, filtro mediano, copy-move, miniatura EXIF |
| Contenuti nascosti | Estrazione LSB (testo in qualunque punto, lunghezze 2/4/8 byte, Base64, file, OpenStego, audio WAV), testo nei metadati e nei byte del file, spazi non standard dei BMP, segni quasi invisibili, RS e chi-quadro sui pixel, chi-quadro DCT per i JPEG |
| Sensore | PRNU con archivio delle impronte e PCE |
| Confronto | SSIM, PSNR, differenze, allineamento con omografia, hash percettivi, quasi-duplicati nel caso |
| Video | FFprobe, coerenza stream, encoder, atom |
| Persone e movimento | Stima della posa (YOLOX + RTMPose HALPE-26, ONNX Runtime), angoli e filtri come Sports2D, esportazioni CSV/TRC/MOT, discontinuità di scena e isolate, sostituzione delle persone, cadenza, posture insolite. Modelli facoltativi da installare con `fetch_tools.py --pin`/`--only pose-models` |
| Report | HTML 1.1 con sintesi in linguaggio naturale, punti di attenzione collegati ai dettagli e glossario; JSON completo; CSV con spiegazioni |
| Sistema | Self-check all'avvio e in build, download verificato degli strumenti, build Windows autonoma |

Test automatici: 93 (unità, integrazione su un dataset di 34 file a verità nota, video sintetici con tagli noti, micro-modelli ONNX, interfaccia).

## Non incluso nella 1.0

Questi elementi sono indicati come tali anche nell'interfaccia:

- analisi dei singoli frame video e dell'audio (forma d'onda, spettrogramma, giunzioni);
- modelli neurali per immagini generate da AI, deepfake e localizzazione delle manipolazioni; analisi di illuminazione e ombre;
- validazione crittografica dei manifest C2PA;
- estrazione di contenuti cifrati o protetti da password e rilevamento di Steghide, F5 e OutGuess;
- lettura automatica (OCR) del testo nelle immagini: le scritte quasi invisibili sono evidenziate ma non trascritte;
- report PDF (il report HTML si stampa in PDF dal browser);
- per la posa: calibrazione della camera e misure in metri (statura, distanze), analisi 3D, confronto biometrico
  dell'andatura tra soggetti.

Scelte deliberate: nessun punteggio unico di manipolazione in percentuale. Inoltre Steghide non viene incluso, perché è fermo dal 2003, ha vulnerabilità note e non va eseguito su reperti non attendibili.
