"""O `transcodificar.sh` com áudio sintético, quando há `ffmpeg` e `sh` no caminho.

Nesta máquina não há `ffmpeg` no anfitrião e o ensaio salta; a medição que conta
corre dentro do contentor `jrottenberg/ffmpeg:7.1-alpine` e está registada no
`README.md` e no bloco do ticket.
"""

import shutil
import subprocess
import unittest
from decimal import Decimal
from pathlib import Path

from tests.apoio import pasta_temporaria, tom

SCRIPT = Path(__file__).resolve().parents[1] / "transcodificar.sh"
TEM = shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("sh")


@unittest.skipUnless(TEM, "sem ffmpeg, ffprobe ou sh no caminho")
class TestTranscodificar(unittest.TestCase):
    def sh(self, *args, cwd):
        return subprocess.run(["sh", str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True)

    def test_opus_juntar_duracao(self):
        with pasta_temporaria() as d:
            (Path(d) / "a.wav").write_bytes(tom(440, segundos=7, taxa=48000))
            (Path(d) / "b c.wav").write_bytes(tom(660, segundos=9, taxa=44100))
            self.assertEqual(self.sh("opus", "a.wav", "a.ogg", cwd=d).returncode, 0)
            self.assertEqual(self.sh("opus", "b c.wav", "b.ogg", cwd=d).returncode, 0)
            sonda = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,channels", "-of", "csv=p=0", "a.ogg"],
                cwd=d, capture_output=True, text=True,
            )
            self.assertEqual(sonda.stdout.strip(), "opus,1")
            self.assertEqual(self.sh("juntar", "j.ogg", "15", "a.ogg", "b.ogg", cwd=d).returncode, 0)
            dur = Decimal(self.sh("duracao", "j.ogg", cwd=d).stdout.strip())
            self.assertLessEqual(abs(dur - 15), Decimal("0.5"))
            self.assertEqual(self.sh("juntar", "k.ogg", "30", "a.ogg", "b.ogg", cwd=d).returncode, 1)
            self.assertEqual(self.sh("juntar", "k.ogg", "7", "a.ogg", cwd=d).returncode, 2)


if __name__ == "__main__":
    unittest.main()
