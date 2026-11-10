# Changelog

## 1.5.1 — 2026-11-10

- Nuova icona del programma: una foto con davanti una lente d'ingrandimento. È un file del progetto
  (`src/fvp/ui/assets/fvp.ico`, da 16 a 256 px), disegnato da `tools/make_icon.py` e usato da eseguibile, finestra
  e barra delle applicazioni, installer e voce di disinstallazione. Prima l'eseguibile usava l'icona predefinita di
  PyInstaller perché `packaging/fvp.ico` non era nel repository; ora la build si ferma se l'icona manca.
- Corretto: testi sovrapposti o tagliati quando la finestra è più piccola dello spazio richiesto dalla pagina
  (portatili, Windows con ridimensionamento al 125-150%), per esempio dopo «Apri vista». Ogni pagina ora scorre
  invece di comprimere i suoi elementi; la finestra si può ridurre fino a 980×600.
- Corretto: «Apri vista» su un risultato di Persone e movimento apriva la scheda sbagliata invece delle immagini.
- Corretto: su Windows, dopo «Apri vista», restavano visibili sotto la nuova pagina i testi di una pagina precedente
  (per esempio «Casi» sotto «Contenuti nascosti»). Le pagine avevano lo sfondo trasparente: ora area di scorrimento,
  viewport e pagina hanno lo sfondo pieno del tema e a ogni cambio di pagina l'area viene ridisegnata per intero e
  riportata in cima.
- Carica e analizza: le singole analisi su due colonne, leggibili anche su schermi stretti.
- Leggi i risultati: i dettagli del risultato scelto (cosa significa, cosa fare, dati tecnici) sono nel riquadro
  «Dettagli» a destra, già aperto sul primo punto da verificare; «Esito per area» passa a sinistra, sotto il file.
- Corretto: «Dettagli» non aggiornava il riquadro se il risultato era già selezionato.

## 1.5.0 — 2026-11-10

Interfaccia più semplice, pensata anche per chi non è del mestiere.

- Nuova **vista semplice**, predefinita: il menu mostra i quattro passi numerati (1 Apri un caso, 2 Aggiungi i
  file, 3 Leggi i risultati, 4 Crea il report) più «Tutti i dati del file» e «Persone nei video». Il pulsante in alto
  a destra passa alla **vista esperta** con tutte le analisi e gli strumenti; la scelta resta salvata.
- Ogni pagina mostra una sola frase in linguaggio semplice; la spiegazione completa (metodo, limiti, come leggere i
  risultati) è dietro il pulsante «Come funziona».
- Carica e analizza: area di trascinamento più grande, «Tipo di analisi» e pulsante «Avvia l'analisi»; le singole
  analisi e le opzioni tecniche sono dietro «Scegli le singole analisi».
- Riepilogo: in vista semplice mostra solo le aree effettivamente esaminate e ciò che merita attenzione; l'elenco
  completo dei controlli si apre con un pulsante. Le attività recenti restano nella vista esperta.
- Persone e movimento: in vista semplice cinque schede (video e angoli, cosa è stato trovato, immagini,
  discontinuità, modello 3D OpenSim); i dettagli sul metodo sono nella guida della pagina. Sul video annotato
  compaiono solo gli angoli articolari.
- Casi: etichette in italiano («Numero del caso», «File del caso», «Registro delle operazioni»).
- Impostazioni: «Risultati negli elenchi» al posto di Basic/Advanced/Expert.

## 1.4.1 — 2026-11-09

- Corretto: Sports2D 0.8.x si interrompeva prima di salvare il video annotato e di eseguire la cinematica inversa
  (`AttributeError: 'list' object has no attribute 'close'` con `show_graphs=false`), quindi non creava il modello
  OpenSim (.osim). Ora viene avviato con `--save_graphs false`; verificato con Sports2D 0.8.34, Pose2Sim 0.10.49 e
  OpenSim 4.6 reali: modello scalato con 30 corpi e 318 muscoli, movimento IK caricabile da OpenSim.
- Le ossa del modello (cartella `Geometry` di Pose2Sim, 215 file .vtp) sono copiate accanto al .osim, con
  `Geometry_SHA256SUMS.txt`: OpenSim mostra lo scheletro anche senza la sua libreria di geometrie.
- Errore dei marcatori della cinematica inversa (RMS medio e peggiore, in cm) nei risultati, nell'interfaccia e in
  `LEGGIMI_OpenSim.txt`, come indicatore di qualità del modello.
- Se Sports2D si interrompe, la scheda Sports2D / Pose2Sim mostra in rosso il codice di uscita e le ultime righe del
  registro.
- Test facoltativo con i programmi reali (`FVP_TEST_SPORTS2D_PY`).

## 1.4.0 — 2026-11-09

Analisi video: acquisizione di video e audio, persone e movimento con video annotato e grafici degli angoli,
Sports2D e Pose2Sim originali con modello OpenSim, pagina con tutti i dati rinvenuti.

- Sports2D/Pose2Sim: modello OpenSim scalato (.osim) e cinematica inversa (*_ik.mot) creati di default, con
  LEGGIMI_OpenSim.txt accanto ai file, pulsante "Apri il modello in OpenSim" e curve della cinematica inversa nel
  lettore (fonte "OpenSim"). Statura e massa documentate impostabili; senza statura il modello usa 1,70 m e i
  risultati la dichiarano presunta.
- Persone e movimento: video annotato come Sports2D (scheletro, angoli sulle articolazioni, numero di frame e tempo
  su ogni fotogramma), attivo di default; lettore integrato frame per frame con grafico degli angoli sincronizzato e
  discontinuità evidenziate; grafici PNG degli angoli per persona con SHA-256.
- Nuovo modulo "sports2d": Sports2D e Pose2Sim originali (D. Pagnon) eseguiti in un ambiente Python separato su una
  copia verificata del reperto; comando, versioni, log, hash di ogni file prodotto e dei modelli RTMLib registrati.
  Installazione con tools/install_sports2d.py (eseguito anche dalla build).
- Nuova pagina "Tutti i dati rinvenuti": anomalie in alto, poi ogni dato estratto (anche senza anomalie), con
  ricerca ed esportazione JSON registrata nel registro del caso.
- Profilo "Completa" con stima della posa e Sports2D; ExifTool estrae anche i metadati incorporati nei video (-ee3).
- Corretto: la rianalisi dalla pagina Persone e movimento eseguiva solo 3 moduli e cancellava dalle altre pagine i
  dati dell'analisi precedente.
- Build: impronte dei modelli della posa fissate automaticamente se le due sorgenti coincidono; modelli inclusi.
- Carica e analizza: video (MP4, MOV, 3GP, AVI, MKV, WebM, MPEG-PS/TS) e audio sono acquisiti con il filtro
  predefinito, che ora esclude solo i file non multimediali (sempre sui magic bytes). Selettore file con filtri
  Immagini/Video/Audio, colonna "Tipo" nell'elenco e suggerimento del profilo "Persone e movimento" per i video.
- Nuovo modulo "pose" e pagina **Persone e movimento**, con la metodologia di Sports2D (D. Pagnon) reimplementata
  senza le sue dipendenze: stima della posa YOLOX + RTMPose HALPE-26 con ONNX Runtime (solo CPU, modelli locali
  verificati con SHA-256), tracciamento, angoli articolari e segmentali di Sports2D/Pose2Sim, Butterworth a fase zero,
  esportazioni CSV/TRC/MOT. Indicatori forensi sui dati grezzi: discontinuità di scena (salti di posizione o di
  scala, sostituzione delle persone, confermati da timestamp e differenza del frame), salti isolati, cadenza del
  passo, posture insolite. Mappe: scheletro, velocità tra frame, coppie di fotogrammi prima/dopo.
- Nuova categoria "Persone e movimento" nel riepilogo e nel report; voci nel glossario.
- fetch_tools.py: voci facoltative che non bloccano la build e `--pin` per fissare lo SHA-256 di un download solo se
  tutte le sorgenti restituiscono lo stesso file.
- Self-check: controllo facoltativo della stima della posa con un'inferenza reale.
- Nuova dipendenza: onnxruntime.
- Crediti e licenze di terze parti: registro unico (`fvp/core/credits.py`) con autori, uso, licenza e sorgenti di
  ogni componente; `THIRD_PARTY_NOTICES.md` completo; testi integrali in `licenses/` (GPL-1/2/3, LGPL-2.1/3, Apache-2.0,
  Artistic, BSD di Sports2D/Pose2Sim); sezione nel README; finestra Impostazioni → Crediti e licenze; comando
  `--credits [file]`; tabella degli strumenti e metodologie di terze parti nel report HTML (Metodo e limiti).
- Build: `tools/collect_licenses.py` raccoglie le licenze dei pacchetti effettivamente inclusi (comprese le librerie
  native delle wheel di OpenCV, pillow-heif e ONNX Runtime) e ferma la build se un componente ne è privo; note e
  licenze sono distribuite accanto all'eseguibile, nella versione portable e nell'installer (con collegamenti nel menu).
- fetch_tools.py: `extract_optional` per estrarre il testo di licenza di FFmpeg dall'archivio.
- Note di copyright nei file con codice derivato (Pose2Sim BSD-3, rtmlib Apache-2.0 con elenco delle modifiche).
- Test: ogni pacchetto di requirements.txt e ogni strumento di tools.json deve avere un credito documentato.

## 1.3.0

- Tag pubblicato sullo stesso codice della 1.2.0 (il programma riportava la versione 1.2.0).

## 1.2.0

- HEIC/HEIF: decodifica con pillow-heif; i file iPhone passano per tutte le analisi dei pixel (prima erano esclusi).
- Nuovo parser HEIF: item, iloc, iref, proprietà, griglia di tile, miniature, Exif/XMP, immagini ausiliarie
  (gain map HDR, matte del Ritratto), extent oltre la fine del file, byte non referenziati in mdat.
- Corretto: i file HEIC ricevevano sempre "Atom 'moov' assente" come evidenza certa (controllo valido solo per i video).
- Nuovo modulo "device": coerenza del file con il dispositivo dichiarato (nome, ora nel nome, campi del modello,
  versione di iOS, data di uscita, risoluzione, dimensioni EXIF, MakerNotes, struttura HEIF).
- Self-check: decodifica HEIC reale; la build si ferma se il decoder manca.
- Modulo "device" esteso ai video iPhone (chiavi QuickTime com.apple.quicktime.*): modello, iOS, date, risoluzione.
- Nuovo modulo "case_context": abbinamento Live Photo (ContentIdentifier) con verifica di numero, modello e orario;
  più versioni dello stesso scatto; numerazione IMG_xxxx coerente con l'ordine delle date (con rollover 9999→0001
  e riconoscimento dei cambi di fuso). Cache per SHA-256 nel caso.
- Carica e analizza: acquisisce tutto il lotto prima di analizzarlo, così il confronto tra reperti non dipende
  dall'ordine dei file.
- Aggiunto .gitignore.

## 1.1.0

**Report HTML 1.1**
- Sintesi iniziale in linguaggio naturale: file analizzati, integrità, contenuti nascosti trovati (citati testualmente), file che richiedono attenzione, file senza elementi da segnalare.
- Elenco dei punti di attenzione di tutto il caso, dal più rilevante, con pulsanti *Dettagli* e *Scheda file*.
- Panoramica dei reperti con miniature ed esito. Per ogni file: riepilogo discorsivo, elementi da verificare con *Dettagli* e *Vedi mappa*, riquadro dei contenuti nascosti, esito per area, mappe con spiegazione, tutti i controlli con «Cosa significa» e «Cosa fare» prima dei dati tecnici.
- Indice laterale, filtro «solo ciò che richiede attenzione», espandi e comprimi, ingrandimento delle immagini, stampa con le sezioni aperte, glossario.
- Immagini incorporate in JPEG ridotto: report circa 5 volte più leggero.

**Contenuti e testo nascosti**
- Estrazione LSB: testo cercato in qualunque punto del flusso, lunghezze su 2, 4 e 8 byte, testo in Base64. Corregge il caso reale di un messaggio con lunghezza su 8 byte in ordine BGR, che la 1.0 non estraeva.
- Nuovo modulo «Testo nascosto»:
  - campi descrittivi dei metadati (dati codificati, indirizzi, testo);
  - frasi leggibili nei byte del file fuori dalle aree di metadati;
  - segni quasi invisibili su zone uniformi, con mappa a contrasto esaltato.
- Parser BMP: byte riservati, spazio tra intestazione e pixel, riempimento delle righe, dati dopo i pixel.
- JPEG: chi-quadro sui coefficienti DCT (inserimenti di tipo JSteg).
- La stima RS viene declassata quando l'immagine ha molte zone perfettamente uniformi, che la falsano.

**Accuratezza**
- Copy-move: ogni gruppo viene confermato confrontando i pixel e scartato se la zona è testuale. Elimina i falsi positivi su schermate e documenti.
- Scanner di firme incorporate: ogni firma viene verificata sulla struttura che la segue, riducendo i falsi positivi nei dati audio.
- Riconoscimento di MP3 (anche senza ID3), FLAC, OGG e AAC, analizzati con FFprobe.
- Controllo della griglia JPEG escluso sulle immagini quasi uniformi.

**Build Windows**
- Il dataset di prova non dipende più dai font del sistema. Prima richiedeva DejaVu Sans Mono, assente su Windows, e i test fallivano. Ora usa i font disponibili (DejaVu, Arial, Consolas…) o quello incluso in Pillow, e i test sono verificati con entrambi.
- L'output dei test e di pip finisce nel registro `build\build.log`; il dettaglio dei test è anche in `build\test-output.txt` e `build\test-results.xml`.
- ExifTool viene scaricato prima da SourceForge (exiftool.org conserva solo l'ultima versione).

**Copy-move**
- Anche una singola parola ripetuta viene riconosciuta come testo. Le scritte identiche pixel per pixel, normali in schermate e documenti, sono elencate come «da verificare solo se quel testo non dovrebbe ripetersi» e non sono mai confermate come copia.

**Interfaccia**
- Voci del menu in italiano semplice, con descrizione al passaggio del mouse.
- Riepilogo con sintesi del caso, racconto del file selezionato ed elementi da verificare con *Dettagli* e *Apri vista*.
- Risultati con esiti comprensibili («Da verificare», «Fatto accertato»…), spiegazione e collegamento alla vista utile.
- Pagina Contenuti nascosti con il testo trovato in evidenza; dati statistici spostati nella scheda avanzata.

## 1.0.0

- **Interfaccia chiara** predefinita, con passaggio al tema scuro dalla barra in alto o da Settings; la scelta viene ricordata.
- **Flusso obbligatorio**: Case Management è la prima voce e l'unica attiva (insieme a Settings) finché non si crea o apre un caso. L'operatore si indica nel modulo del caso. Aggiunto "Chiudi caso".
- **Carica e analizza**: una o più immagini, cartelle intere (con o senza sottocartelle) e trascinamento. Filtro "solo immagini" basato sui magic bytes, coda con stato per file, profili di analisi (completa, rapida, steganografia).
- **StegoIntelligence**: tecniche del catalogo StegoIntelligence implementate in modo nativo. Comprende piani di bit, estrazione del flusso LSB in 56 combinazioni su immagini e 4 su audio WAV, ricerca di file, testo, messaggi con prefisso di lunghezza e intestazioni OpenStego. I contenuti estratti vengono ritagliati alla loro fine strutturale e salvati con SHA-256.
- **Controllo automatico del sistema** all'avvio, in Settings e da riga di comando (`--selfcheck`). Ogni strumento esterno viene provato davvero, non solo cercato, e gli eseguibili inclusi sono confrontati con gli hash registrati.
- **Build Windows autonoma**: installa Python 3.12 e Inno Setup se mancano, verificandone la firma digitale. Usa versioni fissate delle dipendenze e scarica ExifTool e FFmpeg con SHA-256. Esegue il self-check sull'eseguibile finito prima di creare versione portable, installer e `SHA256SUMS.txt`.

## 0.2.0

Analisi avanzate delle immagini: ELA multi-qualità, JPEG ghost, doppia compressione, griglia 8x8, filtro mediano, copy-move, steganalisi RS e chi-quadro, PRNU, hash percettivi, Comparison Tool, analisi di cartelle.

## 0.1.x

Fondamenta: acquisizione e catena di custodia, struttura dei file, metadati, analisi temporale, ELA, video, Hex Viewer, report, download verificato degli strumenti.
