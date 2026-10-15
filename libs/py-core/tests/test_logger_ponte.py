"""A ponte: o que nao passa pelo *logger* tambem nao leva conteudo (KAM-068).

Um servico escreve por mais quatro caminhos alem do seu *logger* — o `logging`
das bibliotecas, os `warnings`, e as excepcoes por tratar no fio principal, em
fios e em destrutores. `instalar` liga os quatro. Aqui prova-se, com canarios,
que nenhum deles deixa passar a mensagem, os argumentos, o `extra`, a pilha ou
o *traceback*.

`instalar` mexe em estado global do processo; cada teste repoe-o.
"""

from __future__ import annotations

import datetime
import io
import json
import logging
import sys
import threading
import unittest
import warnings
from unittest import mock

from kamba_core.logger import CONTADORES, METRICA_ESCRITA_FALHADA, Logger, instalar, ponte

PARADO = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)

CANARIOS = (
    "+244 923 456 789",
    "923456789",
    "5417123456",
    "joaquina.canario@exemplo.co.ao",
    "Bom dia, queria encomendar duas pizzas para o Kilamba",
    "Joaquina Canario dos Santos",
    "Bearer " + "tk" + "9z" * 14,
    "AO06004000001234567890123",
    "00123 456 789 012",
)


class _ComPonte(unittest.TestCase):
    def setUp(self) -> None:
        raiz = logging.getLogger()
        self._antes = (
            list(raiz.handlers),
            raiz.level,
            sys.excepthook,
            threading.excepthook,
            sys.unraisablehook,
            warnings.showwarning,
        )
        CONTADORES.repor()
        self.saida = io.StringIO()
        self.erros = io.StringIO()
        self._stderr = mock.patch("sys.stderr", self.erros)
        self._stderr.start()
        self.registo = instalar("agr", destino=self.saida, relogio=lambda: PARADO, estrito=True)

    def tearDown(self) -> None:
        self._stderr.stop()
        raiz = logging.getLogger()
        logging.captureWarnings(False)
        for manipulador in list(raiz.handlers):
            raiz.removeHandler(manipulador)
        for manipulador in self._antes[0]:
            raiz.addHandler(manipulador)
        raiz.setLevel(self._antes[1])
        sys.excepthook, threading.excepthook, sys.unraisablehook = self._antes[2:5]
        warnings.showwarning = self._antes[5]
        CONTADORES.repor()

    def linhas(self) -> list[dict]:
        return [json.loads(linha) for linha in self.saida.getvalue().splitlines()]

    def sem_canarios(self) -> None:
        for texto in (self.saida.getvalue(), self.erros.getvalue()):
            for canario in CANARIOS:
                self.assertNotIn(canario, texto)
            self.assertNotIn("923456789", texto)
            self.assertNotIn("Traceback", texto)


class TestLoggingDaBibliotecaPadrao(_ComPonte):
    def test_instalar_devolve_o_logger_do_servico(self) -> None:
        self.assertIsInstance(self.registo, Logger)
        self.assertEqual(self.registo.svc, "agr")
        self.assertTrue(self.registo.estrito)

    def test_a_raiz_fica_so_com_a_ponte_em_info(self) -> None:
        raiz = logging.getLogger()
        self.assertEqual(len(raiz.handlers), 1)
        self.assertIsInstance(raiz.handlers[0], ponte.PonteLogging)
        self.assertEqual(raiz.level, logging.INFO)

    def test_um_logger_que_ja_tinha_manipulador_proprio_perde_o(self) -> None:
        """Achado A8: com `propagate=False`, escrevia por ele ao lado da ponte."""
        proprio = logging.getLogger("biblioteca.com_manipulador")
        captura = io.StringIO()
        manipulador = logging.StreamHandler(captura)
        proprio.addHandler(manipulador)
        proprio.propagate = False
        self.addCleanup(proprio.removeHandler, manipulador)
        instalar("agr", destino=self.saida, relogio=lambda: PARADO)
        for canario in CANARIOS:
            proprio.error("GET /pedido?telefone=%s", canario)
        self.assertEqual(captura.getvalue(), "")
        self.assertEqual(len(self.linhas()), len(CANARIOS))
        self.sem_canarios()

    def test_instalar_duas_vezes_nao_duplica_a_ponte(self) -> None:
        instalar("agr", destino=self.saida, relogio=lambda: PARADO)
        logging.getLogger("x").error("uma vez")
        self.assertEqual(len(self.linhas()), 1)

    def test_a_mensagem_e_os_argumentos_nao_saem(self) -> None:
        biblioteca = logging.getLogger("uvicorn.error")
        for canario in CANARIOS:
            biblioteca.info("pedido de %s recebido", canario)
            biblioteca.warning(canario)
            biblioteca.error("falhou: %(quem)s", {"quem": canario})
        self.sem_canarios()
        self.assertEqual(len(self.linhas()), 3 * len(CANARIOS))
        self.assertEqual(
            self.linhas()[0],
            {
                "ts": "2026-01-01T00:00:00.000Z",
                "level": "info",
                "svc": "agr",
                "outcome": "log_biblioteca",
                "error_code": "uvicorn.error",
            },
        )

    def test_uma_mensagem_com_cara_de_identificador_tambem_nao_sai(self) -> None:
        """Primeira revisao: a ponte a por `record.msg` num campo so se via com
        uma mensagem que a forma do campo aceitasse. Os outros testes usam
        frases, que a forma recusava por si."""
        biblioteca = logging.getLogger("lib")
        for mensagem in ("timeout", "pizza", "recusado", "TimeoutError", "ok"):
            biblioteca.error(mensagem)
            biblioteca.warning("%s", mensagem)
        texto = self.saida.getvalue()
        for mensagem in ("timeout", "pizza", "recusado", "TimeoutError"):
            self.assertNotIn(mensagem, texto)
        self.assertEqual(len(self.linhas()), 10)
        for linha in self.linhas():
            self.assertEqual(
                {k: v for k, v in linha.items() if k not in ("ts", "level")},
                {"svc": "agr", "outcome": "log_biblioteca", "error_code": "lib"},
            )

    def test_campos_validos_no_extra_nao_passam_para_a_linha(self) -> None:
        """O `extra` de uma biblioteca nao e uma chamada ao *logger*: mesmo com
        nomes e valores que a *allowlist* aceitaria, nao sai."""
        logging.getLogger("lib").error(
            "x",
            extra={
                "tool": "criar_pedido",
                "tenant_id": "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4",
                "latency_ms": 42,
                "wa_type": "text",
                "msg_id": "11111111-2222-4333-8444-555555555555",
                "turn_id": "11111111-2222-4333-8444-555555555555",
                "contact_hmac_prefix": "a1b2c3d4",
            },
        )
        self.assertEqual(
            self.linhas(),
            [
                {
                    "ts": "2026-01-01T00:00:00.000Z",
                    "level": "error",
                    "svc": "agr",
                    "outcome": "log_biblioteca",
                    "error_code": "lib",
                }
            ],
        )

    def test_o_extra_e_a_pilha_nao_saem(self) -> None:
        biblioteca = logging.getLogger("httpx")
        for canario in CANARIOS:
            biblioteca.error(
                "com contexto",
                extra={
                    "telefone": canario,
                    "contexto": {"headers": {"Authorization": canario}},
                    "lista": [canario],
                },
                stack_info=True,
            )
        self.sem_canarios()
        for linha in self.linhas():
            self.assertEqual(set(linha), {"ts", "level", "svc", "outcome", "error_code"})

    def test_uma_excepcao_sai_pela_classe_sem_traceback(self) -> None:
        biblioteca = logging.getLogger("asyncio")
        for canario in CANARIOS:
            try:
                raise ValueError(f"nao foi possivel tratar {canario}")
            except ValueError:
                biblioteca.exception("Task exception was never retrieved: %s", canario)
        self.sem_canarios()
        self.assertEqual(
            {linha["error_code"] for linha in self.linhas()}, {"asyncio:ValueError"}
        )

    def test_os_niveis(self) -> None:
        biblioteca = logging.getLogger("x")
        biblioteca.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
        biblioteca.debug("d")
        biblioteca.info("i")
        biblioteca.warning("w")
        biblioteca.error("e")
        biblioteca.critical("c")
        self.assertEqual(
            [linha["level"] for linha in self.linhas()],
            ["debug", "info", "warn", "error", "error"],
        )

    def test_abaixo_de_info_nao_sai_por_omissao(self) -> None:
        logging.getLogger("x").debug("ruido")
        self.assertEqual(self.linhas(), [])

    def test_um_nome_de_logger_com_conteudo_fica_de_fora(self) -> None:
        """A ponte usa o *logger* tolerante: nao levanta dentro do `logging`."""
        for canario in CANARIOS:
            logging.getLogger(canario).error("x")
        self.sem_canarios()
        # A linha sai na mesma, sem o nome: o servico e estrito (`setUp`), e se a
        # ponte herdasse isso cada uma destas chamadas levantava la dentro.
        self.assertEqual(len(self.linhas()), len(CANARIOS))
        self.assertEqual(CONTADORES.ler(), {"log_field_rejected_total:valor_invalido": len(CANARIOS)})
        for linha in self.linhas():
            self.assertEqual(linha["outcome"], "log_biblioteca")
            self.assertNotIn("error_code", linha)

    def test_um_registo_mal_formado_nao_imprime_o_registo(self) -> None:
        """O `handleError` de origem escrevia a mensagem e os argumentos no `stderr`."""
        for canario in CANARIOS:
            logging.getLogger("x").error("faltam argumentos para %s e %s", canario)
        self.sem_canarios()
        self.assertEqual(self.erros.getvalue(), "")

    def test_se_a_ponte_falhar_conta_e_nao_escreve_no_stderr(self) -> None:
        manipulador = logging.getLogger().handlers[0]
        with mock.patch.object(manipulador, "_registo", None):
            for canario in CANARIOS:
                logging.getLogger("x").error("pedido de %s", canario)
        self.sem_canarios()
        self.assertEqual(self.erros.getvalue(), "")
        self.assertEqual(CONTADORES.ler(), {METRICA_ESCRITA_FALHADA: len(CANARIOS)})

    def test_os_warnings_passam_pela_ponte(self) -> None:
        for canario in CANARIOS:
            with warnings.catch_warnings():
                warnings.simplefilter("always")
                warnings.warn(f"valor em desuso: {canario}", DeprecationWarning, stacklevel=1)
        self.sem_canarios()
        self.assertEqual(len(self.linhas()), len(CANARIOS))
        self.assertEqual(
            {(linha["level"], linha["error_code"]) for linha in self.linhas()},
            {("warn", "py.warnings")},
        )


class TestExcepcoesPorTratar(_ComPonte):
    def test_no_fio_principal(self) -> None:
        for canario in CANARIOS:
            try:
                raise KeyError(canario)
            except KeyError:
                sys.excepthook(*sys.exc_info())
        self.sem_canarios()
        self.assertEqual(
            self.linhas()[0],
            {
                "ts": "2026-01-01T00:00:00.000Z",
                "level": "error",
                "svc": "agr",
                "outcome": "excepcao_nao_tratada",
                "error_code": "excepcao_nao_tratada:KeyError",
            },
        )
        self.assertEqual(len(self.linhas()), len(CANARIOS))

    def test_noutro_fio(self) -> None:
        for canario in CANARIOS:

            def rebenta(valor: str = canario) -> None:
                raise RuntimeError(f"num fio, com {valor}")

            fio = threading.Thread(target=rebenta)
            fio.start()
            fio.join()
        self.sem_canarios()
        self.assertEqual(
            [linha["error_code"] for linha in self.linhas()],
            ["excepcao_nao_tratada:RuntimeError"] * len(CANARIOS),
        )

    def test_um_fio_que_sai_de_proposito_nao_e_um_erro(self) -> None:
        fio = threading.Thread(target=lambda: sys.exit(0))
        fio.start()
        fio.join()
        self.assertEqual(self.linhas(), [])

    def test_num_destrutor(self) -> None:
        for canario in CANARIOS:

            class Rebenta:
                def __init__(self, valor: str) -> None:
                    self.valor = valor

                def __del__(self) -> None:
                    raise OSError(f"ao destruir, com {self.valor}")

            objecto = Rebenta(canario)
            del objecto
        self.sem_canarios()
        self.assertEqual(
            {linha["error_code"] for linha in self.linhas()}, {"excepcao_nao_tratada:OSError"}
        )
        self.assertEqual(len(self.linhas()), len(CANARIOS))

    def test_uma_classe_com_conteudo_no_nome_fica_so_o_codigo(self) -> None:
        classe = type("E244923456789", (Exception,), {})
        try:
            raise classe("x")
        except classe:
            sys.excepthook(*sys.exc_info())
        self.assertEqual(self.linhas()[0]["error_code"], "excepcao_nao_tratada")

    def test_um_gancho_chamado_sem_classe_nao_levanta(self) -> None:
        sys.excepthook(None, None, None)
        self.assertEqual(self.linhas()[0]["error_code"], "excepcao_nao_tratada")


if __name__ == "__main__":
    unittest.main()
