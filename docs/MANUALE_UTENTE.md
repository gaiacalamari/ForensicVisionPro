# Manuale utente — Forensic Vision Pro 1.1

## Primo avvio

All'avvio il programma verifica da solo dipendenze e strumenti: in alto a destra compare "Sistema verificato" oppure il numero di problemi, con i dettagli in **Impostazioni → Stato del sistema**. Il tema è chiaro; il pulsante "Tema scuro" in alto lo cambia.

## 1. Creare o aprire un caso (obbligatorio, sezione Casi)

Finché non c'è un caso aperto sono attive solo **Casi** e **Impostazioni**. Inserisci operatore, Case ID, titolo ed eventuale descrizione e premi **Crea caso**, oppure seleziona un caso esistente e premi **Apri caso selezionato**. "Chiudi caso" riporta a questa pagina.

## 2. Caricare e analizzare

In **Carica e analizza**:

- **Aggiungi immagini…** per uno o più file, **Aggiungi cartella…** per una cartella intera (con "includi sottocartelle" anche le sottocartelle), oppure trascina file e cartelle nella pagina;
- con "solo immagini" attivo vengono considerati solo i file che sono davvero immagini secondo i magic bytes, qualunque sia l'estensione; disattivalo per includere video, audio WAV e altri file;
- scegli il profilo: **Completa**, **Rapida** o **Contenuti nascosti**; puoi anche selezionare i moduli uno per uno;
- **Acquisisci e analizza**: ogni file viene copiato nel caso con hash verificati e analizzato. La colonna Stato mostra l'esito file per file; un file problematico non interrompe gli altri.

Al termine, il reperto da esaminare si sceglie dal menu "Reperto" in alto.

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
- **Confronta immagini**: confronta due reperti o un reperto con un file; "Trova quasi-duplicati" usa gli hash percettivi di tutto il caso.
- **Metadati**: tutti i tag con attendibilità; ricerca, filtro ed esportazione.
- **Date e orari**: tutti gli orari in ordine; giallo se il fuso non è dichiarato.
- **Byte del file (Hex)**: contenuto binario in sola lettura; clic sulla struttura per evidenziare i byte, ricerca HEX/ASCII/UTF-16, esportazione di una selezione (registrata con hash nel caso).
- **Verifica hash**: hash di file o cartelle, confronto con un hash atteso, verifica dei reperti.
- **Casi**: reperti, valutazioni dell'operatore (finiscono nel report in una sezione separata), eventi di custodia, verifica della catena del registro.
- **Report**: report HTML stampabile, JSON completo, CSV dei risultati.

## Modalità

Basic nasconde i risultati solo informativi; Advanced ed Expert mostrano tutto.
