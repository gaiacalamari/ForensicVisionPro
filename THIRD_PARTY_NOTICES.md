# Crediti e licenze di terze parti

Forensic Vision Pro esiste grazie al lavoro degli autori dei componenti elencati qui. Questo file è distribuito con
il programma (accanto all'eseguibile e in Impostazioni → Crediti e licenze) ed è stampabile con
`ForensicVisionPro --credits crediti.txt` oppure, dai sorgenti, `python -m fvp --credits`.

I testi integrali delle licenze sono nella cartella `licenses/`. Nella build Windows la cartella contiene anche i file
di licenza estratti da ogni pacchetto installato, con l'indice `INDEX.md` generato da `tools/collect_licenses.py`.

## Componenti inclusi nel programma

| Componente | Autori | Uso | Licenza |
|---|---|---|---|
| [Python](https://www.python.org/) | Python Software Foundation | Interprete incluso nell'eseguibile | PSF-2.0 |
| [Qt for Python (PySide6, Shiboken6) e Qt](https://www.qt.io/qt-for-python) | The Qt Company | Interfaccia grafica | LGPL-3.0-only |
| [Pillow](https://python-pillow.github.io/) | Jeffrey A. Clark e collaboratori; PIL di Fredrik Lundh | Decodifica delle immagini, ELA, miniature | MIT-CMU (HPND) |
| [NumPy](https://numpy.org/) | NumPy Developers | Calcolo numerico | BSD-3-Clause (con componenti 0BSD, MIT, Zlib, CC0) |
| [OpenCV (opencv-python-headless)](https://opencv.org/) | OpenCV team e collaboratori | SIFT, volti, frame video, elaborazioni d'immagine | Apache-2.0; le librerie incluse nella wheel (tra cui FFmpeg, LGPL-2.1) sono elencate in `LICENSE-3RD-PARTY.txt` |
| Classificatori Haar di OpenCV | Intel Corporation | Rilevamento dei volti | Intel License Agreement (testo nell'intestazione di ogni file XML, conservato) |
| [pillow-heif](https://github.com/bigcat88/pillow_heif) | Alexander Piskun e collaboratori | Decodifica HEIC/HEIF | BSD-3-Clause (sorgente); wheel binarie GPL-2.0 perché includono x265 |
| [libheif](https://github.com/strukturag/libheif) | struktur AG e collaboratori | Decodifica HEIF (dentro pillow-heif) | LGPL-3.0 |
| [libde265](https://github.com/strukturag/libde265) | struktur AG e collaboratori | Decodifica HEVC (dentro pillow-heif) | LGPL-3.0 |
| [x265](https://www.x265.org/) | MulticoreWare Inc. e collaboratori | Codifica HEVC (dentro pillow-heif; usata solo dal self-check) | GPL-2.0 |
| [ONNX Runtime](https://onnxruntime.ai/) | Microsoft Corporation e collaboratori | Esecuzione dei modelli di stima della posa | MIT |

## Strumenti esterni inclusi (scaricati e verificati da `tools/fetch_tools.py`)

| Componente | Autori | Uso | Licenza |
|---|---|---|---|
| [ExifTool](https://exiftool.org/) | Phil Harvey | Estrazione dei metadati, miniature, tag QuickTime | Stessi termini di Perl (Artistic License o GPL-1.0-or-later); il pacchetto Windows include l'interprete Perl, con la stessa licenza |
| [FFmpeg / FFprobe](https://ffmpeg.org/) | FFmpeg developers; build Windows di Gyan Doshi (gyan.dev) | Lettura di stream, contenitori e tempi dei video | GPL-3.0 (build statica con `--enable-gpl --enable-version3`) |

ExifTool e FFprobe sono eseguiti come programmi separati, senza shell e con timeout: non sono collegati al codice di
Forensic Vision Pro.

## Modelli (facoltativi)

| Componente | Autori | Uso | Licenza |
|---|---|---|---|
| [YOLOX-m HumanArt e RTMPose-m Body7 HALPE-26](https://github.com/open-mmlab/mmpose/tree/main/projects/rtmpose) | OpenMMLab (MMPose); YOLOX di Megvii | Rilevamento delle persone e stima dei 26 punti del corpo | Apache-2.0 |

## Metodologie e fonti

| Progetto | Autori | Cosa ne deriva | Licenza |
|---|---|---|---|
| [Sports2D](https://github.com/davidpagnon/Sports2D) | David Pagnon (perfanalytics) | Metodologia di Persone e movimento: angoli, lato visibile, interpolazione e filtri, formati TRC/MOT. Il codice di Sports2D non è incluso | BSD-3-Clause |
| [Pose2Sim](https://github.com/perfanalytics/pose2sim) | David Pagnon (perfanalytics) | `ANGLE_DICT`, `points_to_angles`, `fixed_angle` e la scelta del lato visibile, ripresi in `src/fvp/engines/pose.py` | BSD-3-Clause (testo in `licenses/BSD-3-Clause-perfanalytics.txt`) |
| [rtmlib](https://github.com/Tau-J/rtmlib) | Tao Jiang; Open-MMLab | Pre e post-elaborazione YOLOX/RTMPose, reimplementate e modificate in `src/fvp/engines/pose_model.py` (modifiche elencate nell'intestazione del file) | Apache-2.0 |
| [StegoIntelligence](https://github.com/CScorza/StegoIntelligence) | CScorza | Catalogo di tecniche e strumenti di steganografia, implementate in modo nativo; nessun codice copiato | Nessuna licenza dichiarata; usato solo come fonte di consultazione |
| [PixIntelligence](https://github.com/jacobobb/pixintelligence) | jacobobb | Spunto per l'elenco delle funzioni della milestone 2; nessun codice copiato | CC BY-NC-SA 4.0 / licenza commerciale |

Gli articoli scientifici su cui si basano i singoli algoritmi sono citati in `docs/ARCHITECTURE.md`.

## Strumenti di sviluppo e build

| Componente | Autori | Uso | Licenza |
|---|---|---|---|
| [PyInstaller](https://pyinstaller.org/) | PyInstaller Development Team | Creazione dell'eseguibile; il bootloader è incluso nell'eseguibile | GPL-2.0-or-later con eccezione per il bootloader, che ne consente l'uso in programmi con qualsiasi licenza |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Jordan Russell e Martijn Laan | Creazione dell'installer Windows | Inno Setup License |
| [pytest](https://pytest.org/) | Holger Krekel e collaboratori | Test automatici (non distribuito) | MIT |

## Sorgenti dei componenti copyleft

Le licenze GPL e LGPL richiedono che il codice sorgente corrispondente sia disponibile a chi riceve i binari:

| Componente | Sorgente |
|---|---|
| FFmpeg (build gyan.dev) | https://www.gyan.dev/ffmpeg/builds/ (sorgente di ogni build) e https://github.com/GyanD/codexffmpeg; FFmpeg: https://ffmpeg.org/download.html |
| Qt / PySide6 | https://download.qt.io/official_releases/QtForPython/ e https://code.qt.io/ |
| Librerie FFmpeg (LGPL-2.1) incluse nella wheel di OpenCV | https://github.com/opencv/opencv-python (script di build e versioni) e https://ffmpeg.org/download.html |
| libheif, libde265, x265 (versioni in `LICENSES_bundled.txt` di pillow-heif) | https://github.com/strukturag/libheif, https://github.com/strukturag/libde265, https://github.com/Multicorewareinc/x265 |
| ExifTool e Perl | https://exiftool.org/ |

Le librerie LGPL (Qt, libheif, libde265, FFmpeg di OpenCV) sono caricate come librerie dinamiche separate nella cartella del programma
(build "onedir" di PyInstaller): l'utente può sostituirle con versioni modificate compatibili.

## Testo della licenza BSD 3-Clause di Sports2D e Pose2Sim

La licenza richiede di riprodurre la nota di copyright, le condizioni e l'esclusione di garanzia:

```
Copyright (c) 2022, perfanalytics
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted provided that the
following conditions are met:
1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following
   disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following
   disclaimer in the documentation and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote
   products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Per chi mantiene il progetto

Ogni nuovo componente va aggiunto in `src/fvp/core/credits.py` e in questo file: i test (`tests/test_credits.py`)
falliscono se un pacchetto di `requirements.txt` o uno strumento di `bin/tools.json` non ha una voce, o se una voce
non compare qui.
