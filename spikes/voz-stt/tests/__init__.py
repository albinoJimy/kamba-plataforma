"""Ensaios do spike de voz. O spike é uma pasta de módulos soltos, como o `spikes/h3`;
esta linha põe-na no caminho para que `python -m unittest discover -s spikes/voz-stt/tests
-t spikes/voz-stt` corra de qualquer sítio, sem depender do `PYTHONPATH` (que nesta
máquina não chega ao `python.exe` pela forma com dois-pontos)."""

import sys
from pathlib import Path

_SPIKE = str(Path(__file__).resolve().parents[1])
if _SPIKE not in sys.path:
    sys.path.insert(0, _SPIKE)
