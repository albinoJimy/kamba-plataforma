"""O arranque do AGR escreve pelo *logger*, e so por ele (KAM-068).

A revisao adversarial tirou o `log_config=None` do `uvicorn.run`, trocou o
`log.excepcao` por um `SystemExit(str(exc))` e deixou de chamar `instalar` — e
nenhum teste deu por isso (`docs/analises/ANALISE-11`, A10). Aqui corre-se
`main()` com o `uvicorn.run` substituido, e confere-se o que ele recebe e o que
o processo escreve.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import threading
import unittest
import warnings
from unittest import mock

from kamba_agr import __main__ as arranque
from kamba_core.logger.ponte import PonteLogging


class TestArranque(unittest.TestCase):
    def setUp(self) -> None:
        raiz = logging.getLogger()
        antes = (
            list(raiz.handlers),
            raiz.level,
            sys.excepthook,
            threading.excepthook,
            sys.unraisablehook,
            warnings.showwarning,
        )

        def repor() -> None:
            logging.captureWarnings(False)
            for manipulador in list(raiz.handlers):
                raiz.removeHandler(manipulador)
            for manipulador in antes[0]:
                raiz.addHandler(manipulador)
            raiz.setLevel(antes[1])
            sys.excepthook, threading.excepthook, sys.unraisablehook = antes[2:5]
            warnings.showwarning = antes[5]

        self.addCleanup(repor)
        self.saida, self.erros = io.StringIO(), io.StringIO()

    def _correr(self, ambiente: dict[str, str]) -> tuple[int, mock.Mock]:
        with (
            mock.patch.dict(os.environ, ambiente),
            mock.patch("sys.stdout", self.saida),
            mock.patch("sys.stderr", self.erros),
            mock.patch.object(arranque.uvicorn, "run") as correr,
        ):
            os.environ.pop("KAMBA_LOG_ESTRITO", None)
            codigo = arranque.main()
            # O que uma biblioteca escrever a partir daqui passa pela ponte.
            logging.getLogger("uvicorn.error").info("Uvicorn running on %s", "http://0.0.0.0:8000")
        return codigo, correr

    def linhas(self) -> list[dict]:
        return [json.loads(linha) for linha in self.saida.getvalue().splitlines()]

    def test_arranca_pelo_logger_e_cala_o_registo_proprio_do_uvicorn(self) -> None:
        codigo, correr = self._correr({"PORT": "8123", "HOST": "127.0.0.1"})
        self.assertEqual(codigo, 0)
        correr.assert_called_once()
        argumentos = correr.call_args.kwargs
        # Sem isto o uvicorn instalava os seus manipuladores e escrevia texto livre.
        self.assertIn("log_config", argumentos)
        self.assertIsNone(argumentos["log_config"])
        self.assertIs(argumentos["access_log"], False)
        self.assertEqual((argumentos["host"], argumentos["port"]), ("127.0.0.1", 8123))

        raiz = logging.getLogger()
        self.assertEqual([type(m) for m in raiz.handlers], [PonteLogging])
        self.assertEqual(
            [(l["level"], l["svc"], l["outcome"], l.get("error_code")) for l in self.linhas()],
            [
                ("info", "agr", "service_started", None),
                ("info", "agr", "log_biblioteca", "uvicorn.error"),
            ],
        )
        self.assertEqual(self.erros.getvalue(), "")
        self.assertNotIn("8123", self.saida.getvalue())
        self.assertNotIn("0.0.0.0", self.saida.getvalue())

    def test_uma_porta_invalida_sai_pelo_codigo_e_nunca_pelo_valor(self) -> None:
        codigo, correr = self._correr({"PORT": "abc923456789"})
        self.assertEqual(codigo, 2)
        correr.assert_not_called()
        self.assertEqual(self.erros.getvalue(), "")
        self.assertNotIn("923456789", self.saida.getvalue())
        self.assertEqual(
            [(l["level"], l["error_code"]) for l in self.linhas()][0],
            ("error", "arranque_invalido:ValueError"),
        )


if __name__ == "__main__":
    unittest.main()
