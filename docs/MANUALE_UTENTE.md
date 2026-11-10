# Manuale utente — Forensic Vision Pro 1.5

## In breve: i quattro passi

Il programma si apre nella **vista semplice**. Nel menu a sinistra ci sono i passi da seguire in ordine:

1. **Apri un caso**: scrivi il tuo nome, un numero e un titolo, poi *Crea caso* (oppure apri un caso esistente).
2. **Aggiungi i file**: trascina foto, video o cartelle nel riquadro, lascia il tipo di analisi *Completa* e premi
   *Avvia l'analisi*.
3. **Leggi i risultati**: in alto la sintesi in parole semplici, sotto ciò che merita attenzione. I colori indicano
   dove guardare, non se un file è falso.
4. **Crea il report**: il documento finale da consegnare.

*Tutti i dati del file* mostra ogni informazione estratta; *Persone nei video* il video con lo scheletro, gli angoli
e il modello 3D. In ogni pagina il pulsante **Come funziona** spiega metodo e limiti. Per tutte le analisi e gli
strumenti tecnici: **Passa alla vista esperta**, in alto a destra.

## Primo avvio

All'avvio il programma verifica da solo dipendenze e strumenti: in alto a destra compare "Sistema verificato" oppure il numero di problemi, con i dettagli in **Impostazioni → Stato del sistema**. Il tema è chiaro; il pulsante "Tema scuro" in alto lo cambia.

## 1. Creare o aprire un caso (obbligatorio, sezione Casi)

Finché non c'è un caso aperto sono attive solo **Casi** e **Impostazioni**. Inserisci operatore, Case ID, titolo ed eventuale descrizione e premi **Crea caso**, oppure seleziona un caso esistente e premi **Apri caso selezionato**. "Chiudi caso" riporta a questa pagina.

## 2. Caricare e analizzare

In **Carica e analizza**:

- **Aggiungi file…** per una o più immagini, video o audio, **Aggiungi cartella…** per una cartella intera (con "includi sottocartelle" anche le sottocartelle), oppure trascina file e cartelle nella pagina;
- con "solo immagini, video e audio" attivo vengono considerati solo i file che sono davvero immagini (JPEG, PNG, TIFF, BMP, GIF, WebP, HEIC/HEIF, AVIF), video (MP4, MOV, 3GP, AVI, MKV, WebM, MPEG-PS/TS) o audio (WAV, MP3, FLAC, OGG, AAC) secondo i magic bytes, qualunque sia l'estensione; disattivalo per includere qualsiasi altro file;
- sui video il profilo *Completa* esegue struttura del contenitore (atom MP4/MOV), metadati ExifTool (QuickTime, Keys, XMP, GPS), coerenza temporale e FFprobe; per l'analisi dei movimenti scegli il profilo *Persone e movimento (video)* (richiede i modelli, vedi sotto);
- scegli il profilo: **Completa**, **Rapida** o **Contenuti nascosti**; puoi anche selezionare i moduli uno per uno;
- **Acquisisci e analizza**: ogni file viene copiato nel caso con hash verificati e analizzato. La colonna Stato mostra l'esito file per file; un file problematico non interrompe gli altri.

Al termine, il reperto da esaminare si sceglie dal menu "Reperto" in alto.

### File HEIC e coerenza con il dispositivo

I file HEIC/HEIF degli iPhone sono analizzati come gli altri formati di immagine (decodifica con libheif). Il modulo **Coerenza con il dispositivo** confronta nome del file, ora nel nome, versione di iOS, data di uscita del modello e risoluzione con quanto dichiarato in Make/Model; i profili dei modelli sono in `engines/device_db.py` e si possono correggere o ampliare con `device_profiles.json` nella cartella dati. I profili inclusi vanno validati con file campione del laboratorio.

Il modulo **Confronto con gli altri reperti** abbina foto e filmato delle Live Photo, segnala più versioni dello stesso scatto e verifica che la numerazione IMG_xxxx segua l'ordine delle date di scatto sullo stesso modello. Per questo conviene caricare insieme tutti i file dello stesso dispositivo: il programma li acquisisce tutti prima di analizzarli. Se si aggiungono reperti in un secondo momento, rianalizzare i precedenti con il solo modulo di confronto.

## Leggere i risultati

La pagina **Riepilogo** è il punto di partenza. In alto c'è la sintesi del caso in parole semplici. Sotto ci sono il racconto del file selezionato (menu "File" in alto) e l'elenco di **ciò che merita attenzione**:

- **Dettagli** apre, nell'elenco sottostante, la spiegazione completa: «Cosa significa», «Cosa fare» e i dati tecnici;
- **Apri vista** porta alla sezione utile, ad esempio la mappa giusta in *Analisi visiva* o il testo estratto in *Contenuti nascosti*.

Esiti dei singoli controlli: **Fatto accertato** (oggettivo e ripetibile), **Anomalia**, **Da verificare** (compatibile con una modifica ma con spiegazioni anche normali), **Indicazione statistica** (una mappa o un calcolo da interpretare), **Non verificabile**, **Informazione**.

## Il report

*Report → Genera report HTML* crea un file che si apre con qualsiasi browser:

- in alto la **Sintesi** e i **Punti di attenzione**, ciascuno con il pulsante *Dettagli*;
- per ogni file una scheda con riepilogo, elementi da verificare, contenuti nascosti, mappe (clic per ingrandire) e tutti i controlli;
- l'opzione «Mostra solo ciò che richiede attenzione» nasconde i controlli senza esito;
- *Stampa / PDF* stampa il report con tutte le sezioni aperte;
- il glossario spiega i termini tecnici.

## Come leggere i colori

Verde: i test eseguiti non hanno rilevato anomalie. Giallo: elementi da approfondire. Rosso: anomalia significativa. Grigio: test non eseguito o inconcludente. Nessun colore è un giudizio di autenticità.

## Livelli dei risultati

- **Evidenza certa**: un fatto verificabile, ad esempio un CRC errato o un file troncato.
- **Anomalia tecnica**: una deviazione dallo standard o dall'atteso.
- **Indicatore sospetto**: compatibile con una modifica, ma con spiegazioni anche lecite.
- **Risultato probabilistico**: esito di un algoritmo statistico da interpretare (ELA, rumore).
- **Non determinabile**: il test non può concludere, con il motivo.

## Pagine principali

- **Analisi visiva**: immagine e due mappe a scelta (ELA, ELA multi-qualità, JPEG ghost, residuo di rumore, filtro mediano, copy-move, piani LSB, volti, correlazione PRNU); la rotella fa zoom su tutte le viste insieme.
- **Possibili modifiche**: tutti i risultati sulla storia di compressione, filtro mediano, copy-move, miniatura e struttura.
- **Contenuti nascosti** (steganografia e testo nascosto): in alto è riportato ciò che è stato trovato, con il testo leggibile. Le schede:
  - *Tutti i controlli*: estrazione dai pixel, testo nei metadati e nei byte del file, scritte quasi invisibili.
  - *Contenuti estratti*: testo, file o intestazioni trovati da StegoIntelligence nei bit meno significativi, con SHA-256, apribili nell'Hex Viewer.
  - *Esplora i bit (avanzato)*: test statistici per canale e ogni canale e bit come immagine, alla maniera di Stegsolve.
  - *Strumenti e tecniche*: cosa è coperto rispetto al catalogo StegoIntelligence.
- **Fotocamera di origine**: crea un'impronta da almeno 5 immagini (meglio 20+) dello stesso dispositivo, alla stessa risoluzione e non ridimensionate; poi confronta il reperto. PCE oltre 60 indica compatibilità con il sensore, non un'attribuzione certa.
- **Persone e movimento**: si attiva con il profilo *Persone e movimento (video)*, con la casella del modulo o con il
  pulsante *Analizza persone e movimento* della pagina. Non fa parte del profilo *Completa* perché sui video richiede
  molto calcolo (circa 3–10 frame al secondo su CPU; al massimo 3.600 frame per video, modificabile).
  - *Risultati*: le discontinuità **di scena** sono punti in cui tutte le persone cambiano posizione, dimensione o
    identità da un frame al successivo, confermati da un salto nei tempi o da un cambio dell'immagine: compatibili con
    tagli, frame mancanti o inseriti, ma anche con cambi di inquadratura. Quelle **isolate** riguardano una sola persona
    e di solito sono errori di riconoscimento.
  - *Immagini*: scheletro sovrapposto, grafico della velocità tra frame con la soglia, coppie di fotogrammi prima e
    dopo ogni discontinuità.
  - *Persone*, *Angoli*: tracce, copertura, altezza in pixel, cadenza; angoli con le definizioni di Sports2D.
  - *Esportazioni*: keypoint grezzi (CSV), traiettorie (TRC) e angoli (MOT) apribili in Sports2D, OpenSim, Blender o in
    un foglio di calcolo, ciascuno con SHA-256.
  - I keypoint sono in pixel: non sono misure in centimetri né stime di statura. La cadenza non identifica una persona.
- **Confronta immagini**: confronta due reperti o un reperto con un file; "Trova quasi-duplicati" usa gli hash percettivi di tutto il caso.
- **Metadati**: tutti i tag con attendibilità; ricerca, filtro ed esportazione.
- **Date e orari**: tutti gli orari in ordine; giallo se il fuso non è dichiarato.
- **Byte del file (Hex)**: contenuto binario in sola lettura; clic sulla struttura per evidenziare i byte, ricerca HEX/ASCII/UTF-16, esportazione di una selezione (registrata con hash nel caso).
- **Verifica hash**: hash di file o cartelle, confronto con un hash atteso, verifica dei reperti.
- **Casi**: reperti, valutazioni dell'operatore (finiscono nel report in una sezione separata), eventi di custodia, verifica della catena del registro.
- **Report**: report HTML stampabile, JSON completo, CSV dei risultati.

## Modalità

Basic nasconde i risultati solo informativi; Advanced ed Expert mostrano tutto.

## Installare i modelli per Persone e movimento

I modelli (circa 150 MB) non sono inclusi nei sorgenti. La prima volta, su un computer collegato a Internet:

```bash
python tools/fetch_tools.py --pin pose-models     # scarica da OpenMMLab e dal mirror Hugging Face, confronta
                                                  # le impronte e le scrive in bin/tools.json
python tools/fetch_tools.py --only pose-models    # installa i modelli in bin/ e li registra in tools.lock.json
```

Controllare e conservare il diff di `bin/tools.json` (le due impronte SHA-256): da quel momento ogni build scarica e
accetta solo quei file. In Impostazioni → Stato del sistema la voce *Stima della posa* deve risultare OK. In
alternativa i file `pose_det_yolox_m_humanart.onnx` e `pose_rtmpose_m_halpe26.onnx` possono essere copiati in
`<cartella utente>/ForensicVisionPro/models` o indicati in `settings.json` (`pose_det_model`, `pose_model`).

## Video annotato, angoli e Sports2D / Pose2Sim originali

Nella pagina **Persone e movimento**, scheda *Video e angoli*: il video annotato mostra scheletro, angoli e numero di
frame originale su ogni fotogramma. I pulsanti *◀ frame* / *frame ▶* avanzano di un fotogramma; il grafico sotto mostra
gli angoli scelti della persona selezionata, il cursore rosso segue il video e un clic sul grafico sposta il video.
Le linee tratteggiate sono le discontinuità (rosse: di scena, arancio: isolate).

I programmi originali di David Pagnon si installano una volta, con Internet e Python 3.11+:

```bat
py -3.12 tools\install_sports2d.py
```

L'ambiente viene creato in `<utente>\ForensicVisionPro\sports2d-env` (la build lo fa da sola). Poi, scheda
*Sports2D / Pose2Sim originali* → *Esegui Sports2D originale sul reperto*, oppure modulo omonimo in Carica e analizza.
Sports2D lavora su una copia verificata del reperto; i suoi risultati compaiono in *Video e angoli* scegliendo la
fonte "Sports2D originale". Senza statura indicata in Impostazioni non viene fatta alcuna conversione in metri.
Pose2Sim viene usato tramite Sports2D (filtri, metri, OpenSim): la ricostruzione 3D di Pose2Sim richiede più telecamere
calibrate e non si applica a un video singolo.

La pagina **Tutti i dati rinvenuti** riporta ogni dato estratto dall'ultima analisi del reperto, anche quando non ci
sono anomalie, con le anomalie in cima.

### Modello OpenSim (.osim)

Con Sports2D installato, l'analisi crea anche un modello muscoloscheletrico OpenSim scalato sulla persona (`.osim`)
e il suo movimento (`*_ik.mot`), calcolati da Pose2Sim con la cinematica inversa. Per vederli serve l'applicazione
gratuita OpenSim 4.5+ (https://simtk.org/projects/opensim): *File > Open Model* sul `.osim`, poi *File > Load Motion*
sul `*_ik.mot` e *Play*. Il pulsante *Apri il modello in OpenSim* (scheda Sports2D / Pose2Sim originali) apre il
modello con OpenSim se è installato; le stesse istruzioni sono in `LEGGIMI_OpenSim.txt` accanto ai file.

Indicare in Impostazioni la statura (e, se serve, la massa) solo se documentate. Senza statura il modello usa 1,70 m:
dimensioni e spostamenti in metri sono allora in scala arbitraria e i risultati lo dichiarano; gli angoli articolari
non dipendono dalla statura. Da un solo video la profondità è stimata: le rotazioni fuori dal piano della ripresa e il
lato non visibile sono poco affidabili.
