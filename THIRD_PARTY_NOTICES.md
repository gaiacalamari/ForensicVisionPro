# Componenti e opere di terze parti

## Modulo Persone e movimento

| Componente | Uso in Forensic Vision Pro | Licenza |
|---|---|---|
| [Sports2D](https://github.com/davidpagnon/Sports2D), © 2022 perfanalytics / D. Pagnon | Metodologia di riferimento: definizioni degli angoli, scelta del lato visibile, parametri di filtro e interpolazione, formati TRC/MOT. Il codice non è incluso; le definizioni degli angoli (`ANGLE_DICT`) e le funzioni `points_to_angles`/`fixed_angles` sono riprese da Pose2Sim | BSD 3-Clause |
| [Pose2Sim](https://github.com/perfanalytics/pose2sim), © D. Pagnon | Definizioni degli angoli (`Pose2Sim/common.py`), riportate in `src/fvp/engines/pose.py` | BSD 3-Clause |
| [rtmlib](https://github.com/Tau-J/rtmlib), © T. Jiang | Pre e post-elaborazione YOLOX e RTMPose, reimplementate in `src/fvp/engines/pose_model.py` | Apache-2.0 |
| Modelli YOLOX-m HumanArt e RTMPose-m Body7 HALPE-26 ([MMPose](https://github.com/open-mmlab/mmpose), OpenMMLab) | Scaricati da `tools/fetch_tools.py`, non inclusi nei sorgenti | Apache-2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime), © Microsoft | Esecuzione dei modelli | MIT |

Testo della licenza BSD 3-Clause di Sports2D e Pose2Sim (le condizioni richiedono di riprodurre la nota di copyright):

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
