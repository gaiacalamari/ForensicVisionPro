# Changelog

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
