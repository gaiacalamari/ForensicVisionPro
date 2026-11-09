# Forensic Vision Pro 1.4.0 — analisi video

Questa versione porta l'analisi dei video allo stesso livello di quella delle immagini: acquisizione di video e
audio, movimento delle persone con video annotato e grafici, Sports2D e Pose2Sim originali con modello OpenSim, e una
pagina che mostra ogni dato estratto anche quando non emergono anomalie.

## Novità

**Video e audio in Carica e analizza**
- MP4, MOV, 3GP, AVI, MKV, WebM, MPEG-PS/TS e audio (WAV, MP3, FLAC, OGG, AAC) acquisiti con il filtro predefinito,
  riconosciuti dai magic bytes e non dall'estensione.
- Il profilo *Completa* analizza tutto, compresa la stima della posa; ExifTool estrae anche i metadati incorporati
  nelle tracce video (tracce GPS, orari e sensori campione per campione).

**Persone e movimento**
- Video annotato come Sports2D: scheletro, angoli sulle articolazioni, numero di frame originale e tempo su ogni
  fotogramma.
- Lettore integrato frame per frame con grafico degli angoli sincronizzato: il cursore segue il video, un clic sul
  grafico sposta il video; discontinuità del movimento evidenziate.
- Grafici degli angoli per persona; esportazioni CSV, TRC e MOT con SHA-256.

**Sports2D e Pose2Sim originali (David Pagnon)**
- Eseguiti in un ambiente Python separato su una copia del reperto verificata con hash; comando, versioni, registro,
  SHA-256 di ogni file prodotto e dei modelli usati sono conservati nel caso.
- Modello OpenSim scalato (`.osim`) e cinematica inversa (`*_ik.mot`) da aprire con OpenSim, con istruzioni in
  `LEGGIMI_OpenSim.txt` e pulsante *Apri il modello in OpenSim*.

**Tutti i dati rinvenuti**
- Nuova pagina: anomalie in cima, poi ogni dato estratto (metadati per gruppo, date, stream, struttura, movimento,
  hash, strumenti), con ricerca ed esportazione JSON registrata nel registro del caso.

**Correzioni**
- La rianalisi dalla pagina Persone e movimento non cancella più i dati delle altre pagine.
- `--credits` funziona anche su Windows quando l'uscita è reindirizzata.

## Installazione

| File | Uso |
|---|---|
| `ForensicVisionPro-1.4.0-setup.exe` | Installer per Windows 10/11 a 64 bit |
| `ForensicVisionPro-1.4.0-portable.zip` | Versione portable: casi e impostazioni accanto all'eseguibile |
| `SHA256SUMS.txt` | Impronte SHA-256 dei file pubblicati: verificarle prima dell'uso |

Verifica su Windows (PowerShell): `Get-FileHash .\ForensicVisionPro-1.4.0-setup.exe -Algorithm SHA256` e confronto con
`SHA256SUMS.txt`.

**Sports2D, Pose2Sim e OpenSim** non sono inclusi nell'eseguibile (dipendenze incompatibili): si installano una volta
in un ambiente separato con `py -3.12 tools\install_sports2d.py` dai sorgenti (serve Internet e Python 3.11+). Per
vedere il modello `.osim` serve l'applicazione gratuita OpenSim 4.5+ (https://simtk.org/projects/opensim). Senza
questi componenti il resto del programma, compresa la stima della posa integrata, funziona normalmente.

## Limiti da conoscere

- Coordinate della posa in pixel: nessuna misura in metri senza una statura documentata. Senza statura il modello
  OpenSim usa 1,70 m e i risultati la dichiarano presunta; gli angoli articolari non ne dipendono.
- Da un solo video la profondità è stimata: rotazioni fuori dal piano della ripresa e lato non visibile sono poco
  affidabili. La ricostruzione 3D completa di Pose2Sim richiede più telecamere calibrate.
- Alla prima esecuzione RTMLib (usato da Sports2D) scarica i modelli da OpenMMLab: i loro SHA-256 sono registrati a
  posteriori in ogni analisi.
