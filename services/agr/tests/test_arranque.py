"""O arranque do AGR escreve pelo *logger*, e so por ele (KAM-068).

A revisao adversarial tirou o `log_config=None` do `uvicorn.run`, trocou o
`log.excepcao` por um `SystemExit(str(exc))` e deixou de chamar `instalar` — e
nenhum teste deu por isso (`docs/analises/ANALISE-11`, A10). Aqui corre-se
`main()` com o `uvicorn.run` substituido, e confere-se o que ele recebe e o que
o processo escreve.

**O que o KAM-025 acrescentou a este ficheiro**, e porque e que as duas
asserções originais mudaram de forma: o arranque passou a ter duas guardas do
ADR-002 antes de tudo (criterios 7 e 8) e a exigir o segredo da API interna. As
linhas de registo deixaram de ser so `service_started`, e a bateria segue-as em
vez de fixar uma lista literal que ja nao e verdade. O que **nao** mudou e o que
estes testes existem para proteger: `log_config=None`, `access_log=False`, e
nenhum valor de ambiente a aparecer no registo.
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

from apoio import CREDENCIAL
from kamba_agr import __main__ as arranque
from kamba_core.logger.ponte import PonteLogging

#: O ambiente minimo com que o AGR arranca depois do KAM-025.
AMBIENTE_BASE = {
    "PORT": "8123",
    "HOST": "127.0.0.1",
    "KAMBA_ENV": "dev",
    # O nome e `KAMBA_SECRET_` + o `id` do inventario em maiusculas (ADR-L002).
    "KAMBA_SECRET_AGR_INTERNAL_TOKEN": CREDENCIAL,
}


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

    def _correr(
        self, ambiente: dict[str, str], ligar_checkpoint: object | None = None
    ) -> tuple[int, mock.Mock]:
        # **A ligacao do checkpointer e dupla por omissao** (KAM-026). A guarda
        # do criterio 3 abre-a no arranque, e nenhum ensaio desta bateria tem
        # base de dados: sem o duplo, todos passavam a medir «nao ha Postgres»
        # em vez do que dizem medir. Quem quer medir a guarda passa um
        # `ligar_checkpoint` que levanta.
        with (
            mock.patch.dict(os.environ, ambiente),
            mock.patch("sys.stdout", self.saida),
            mock.patch("sys.stderr", self.erros),
            mock.patch.object(arranque.uvicorn, "run") as correr,
            mock.patch.object(
                arranque,
                "ligar_para_checkpoint",
                ligar_checkpoint or (lambda: mock.Mock()),
            ),
        ):
            os.environ.pop("KAMBA_LOG_ESTRITO", None)
            codigo = arranque.main()
            # O que uma biblioteca escrever a partir daqui passa pela ponte.
            logging.getLogger("uvicorn.error").info("Uvicorn running on %s", "http://0.0.0.0:8000")
        return codigo, correr

    def linhas(self) -> list[dict]:
        return [json.loads(linha) for linha in self.saida.getvalue().splitlines()]

    def erro(self) -> dict:
        """A linha de nivel `error`, procurada e nao contada pela posicao.

        A ultima linha e **sempre** a `log_biblioteca` que o `_correr` provoca
        de proposito, para confirmar que a ponte esta instalada. Fixar `[-1]`
        fazia estes dois testes afirmar sobre ela.
        """
        erros = [l for l in self.linhas() if l["level"] == "error"]
        self.assertEqual(len(erros), 1, self.saida.getvalue())
        return erros[0]

    def test_arranca_pelo_logger_e_cala_o_registo_proprio_do_uvicorn(self) -> None:
        codigo, correr = self._correr(AMBIENTE_BASE)
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
        linhas = self.linhas()
        self.assertTrue(all(l["svc"] == "agr" for l in linhas))
        desfechos = [l["outcome"] for l in linhas]
        self.assertIn("service_started", desfechos)
        self.assertEqual(desfechos[-1], "log_biblioteca")
        self.assertEqual(self.erros.getvalue(), "")
        self.assertNotIn("8123", self.saida.getvalue())
        self.assertNotIn("0.0.0.0", self.saida.getvalue())

    def test_a_credencial_nunca_aparece_no_registo(self) -> None:
        # O segredo passa pelo arranque. Se alguma linha o repetisse, a
        # *allowlist* do `docs/tecnica/08` §7.3 nao o impedia: `outcome` e
        # `error_code` aceitam identificadores, e um segredo pode ter a forma de
        # um. O que impede e nao escrever.
        self._correr(AMBIENTE_BASE)
        self.assertNotIn(CREDENCIAL, self.saida.getvalue())
        self.assertNotIn("agr_internal_token", self.saida.getvalue())

    def test_uma_porta_invalida_sai_pelo_codigo_e_nunca_pelo_valor(self) -> None:
        codigo, correr = self._correr({**AMBIENTE_BASE, "PORT": "abc923456789"})
        self.assertEqual(codigo, 2)
        correr.assert_not_called()
        self.assertEqual(self.erros.getvalue(), "")
        self.assertNotIn("923456789", self.saida.getvalue())
        self.assertEqual(self.erro()["error_code"], "arranque_invalido:ValueError")

    def test_sem_o_segredo_da_api_o_arranque_recusa(self) -> None:
        ambiente = {k: v for k, v in AMBIENTE_BASE.items()}
        del ambiente["KAMBA_SECRET_AGR_INTERNAL_TOKEN"]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KAMBA_SECRET_AGR_INTERNAL_TOKEN", None)
            codigo, correr = self._correr(ambiente)
        self.assertEqual(codigo, 2)
        correr.assert_not_called()
        self.assertEqual(self.erro()["error_code"].split(":")[0], "cofre_indisponivel")

    def test_sem_checkpointer_o_arranque_recusa(self) -> None:
        """O criterio 3 do KAM-026, e o codigo de saida e proprio."""

        def nao_liga() -> object:
            raise RuntimeError("sem base")

        codigo, correr = self._correr(AMBIENTE_BASE, nao_liga)
        self.assertEqual(codigo, arranque.SAIDA_SEM_CHECKPOINTER)
        correr.assert_not_called()
        self.assertEqual(
            self.erro()["error_code"].split(":")[0], "checkpointer_indisponivel"
        )

    def test_o_codigo_sem_checkpointer_distingue_se_dos_outros(self) -> None:
        # Num painel, «o AGR nao arranca» sem dizer porque nao se diagnostica.
        # Quatro, e nao o 2 da configuracao nem o 3 do ADR-002.
        self.assertNotIn(
            arranque.SAIDA_SEM_CHECKPOINTER, (0, 2, arranque.SAIDA_GUARDA_ADR002)
        )

    def test_a_guarda_do_checkpointer_corre_antes_do_servidor(self) -> None:
        # Um processo que aceitasse pedidos e so depois descobrisse que nao
        # consegue gravar estado perdia o primeiro handoff de cada reinicio, e
        # perdia-o em silencio.
        def nao_liga() -> object:
            raise RuntimeError("sem base")

        _codigo, correr = self._correr(AMBIENTE_BASE, nao_liga)
        correr.assert_not_called()

    def test_um_ambiente_desconhecido_recusa_em_vez_de_cair_em_dev(self) -> None:
        # A licao do `chaves.ts` do KAM-008: um `KAMBA_ENV=producao` a servir
        # segredos de `dev` e pior do que nao arrancar.
        codigo, correr = self._correr({**AMBIENTE_BASE, "KAMBA_ENV": "producao"})
        self.assertEqual(codigo, 2)
        correr.assert_not_called()


class TestGuardasDoAdr002(unittest.TestCase):
    """Criterios 7 e 8: a lista de bloqueio e a telemetria, em *runtime*."""

    def test_o_langgraph_api_importavel_impede_o_arranque(self) -> None:
        with (
            mock.patch.object(
                arranque.egresso,
                "exigir_biblioteca_mit",
                side_effect=arranque.egresso.ModuloProibidoError("langgraph_api"),
            ),
            mock.patch.object(arranque.uvicorn, "run") as correr,
            mock.patch("sys.stdout", io.StringIO()),
        ):
            codigo = arranque.main()
        self.assertEqual(codigo, arranque.SAIDA_GUARDA_ADR002)
        self.assertNotEqual(codigo, 0)
        correr.assert_not_called()

    def test_a_guarda_corre_antes_de_se_ler_variavel_nenhuma(self) -> None:
        # Com a porta invalida **e** o modulo proibido, o codigo e o da guarda:
        # ela corre primeiro. Uma guarda do ADR-002 que corresse depois da
        # configuracao era uma guarda que uma variavel errada desligava.
        with (
            mock.patch.object(
                arranque.egresso,
                "exigir_biblioteca_mit",
                side_effect=arranque.egresso.ModuloProibidoError("langgraph_api"),
            ),
            mock.patch.dict(os.environ, {"PORT": "nao-e-porta"}),
            mock.patch.object(arranque.uvicorn, "run"),
            mock.patch("sys.stdout", io.StringIO()),
        ):
            self.assertEqual(arranque.main(), arranque.SAIDA_GUARDA_ADR002)

    def test_o_arranque_deixa_a_telemetria_desligada(self) -> None:
        ambiente = {**AMBIENTE_BASE, "LANGSMITH_TRACING": "true"}
        with (
            mock.patch.dict(os.environ, ambiente),
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch.object(arranque.uvicorn, "run"),
        ):
            arranque.main()
            for variavel in arranque.egresso.VARIAVEIS_DE_TELEMETRIA:
                self.assertEqual(os.environ[variavel], "false")


if __name__ == "__main__":
    unittest.main()
