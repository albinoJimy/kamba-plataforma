"""`tenant_guard`: o helper de transaccao, sem base de dados.

A prova contra um PostgreSQL real — que o contexto isola de facto, e que nao
vaza entre transaccoes na mesma ligacao — esta no gate 6 (`db/tests_isolamento`).
Aqui verifica-se o que o helper faz **a ligacao**: a ordem das chamadas, o que
recusa antes de tocar na base, e o que nao escreve em lado nenhum.

Este modulo esta no estrato `critico` de `ci/thresholds.yaml` (90%).
"""

from __future__ import annotations

import logging
import threading
import unittest
import uuid

from kamba_core import tenant_guard
from kamba_core.tenant_guard import (
    CONTADORES,
    METRICA_BATCH,
    METRICA_SEM_CONTEXTO,
    SQL_DEFINIR_CONTEXTO,
    ContextoEmFalta,
    JobSemNome,
    LigacaoEmAutocommit,
    LigacaoEmUso,
    TenantInvalido,
    normalizar_tenant,
    tx,
    tx_batch,
)

TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4"


class _Cursor:
    def __init__(self, registo: list) -> None:
        self._registo = registo

    def execute(self, sql, parametros=()) -> None:
        self._registo.append(("execute", sql, tuple(parametros)))

    def fetchone(self):
        return ("",)

    def close(self) -> None:
        self._registo.append(("close",))


class _Conexao:
    def __init__(self, autocommit: bool = False) -> None:
        self.autocommit = autocommit
        self.registo: list = []

    def cursor(self) -> _Cursor:
        self.registo.append(("cursor",))
        return _Cursor(self.registo)

    def commit(self) -> None:
        self.registo.append(("commit",))

    def rollback(self) -> None:
        self.registo.append(("rollback",))

    def verbos(self) -> list[str]:
        return [entrada[0] for entrada in self.registo]


class TestNormalizar(unittest.TestCase):
    def setUp(self) -> None:
        CONTADORES.repor()

    def test_aceita_uuid_e_texto_canonico(self) -> None:
        self.assertEqual(normalizar_tenant(TENANT), TENANT)
        self.assertEqual(normalizar_tenant(uuid.UUID(TENANT)), TENANT)
        self.assertEqual(normalizar_tenant(TENANT.upper()), TENANT)

    def test_sem_tenant_levanta_e_conta(self) -> None:
        for valor in (None, ""):
            with self.subTest(valor=valor):
                with self.assertRaises(ContextoEmFalta):
                    normalizar_tenant(valor)
        self.assertEqual(CONTADORES.ler()[METRICA_SEM_CONTEXTO], 2)

    def test_recusa_o_que_nao_e_uuid_canonico(self) -> None:
        for valor in (
            "nao-e-um-uuid",
            TENANT.replace("-", ""),      # sem hifenes: outra escrita do mesmo tenant
            "{" + TENANT + "}",
            TENANT + " ",
            " " + TENANT,
            "' OR '1'='1",
            42,
            b"0b6f1d2e",
            ["x"],
        ):
            with self.subTest(valor=repr(valor)):
                with self.assertRaises(TenantInvalido):
                    normalizar_tenant(valor)

    def test_a_mensagem_nao_repete_o_valor_recebido(self) -> None:
        """Um valor que nao e um UUID pode ser conteudo de um cliente."""
        segredo = "mensagem-privada-de-um-cliente-123"
        with self.assertRaises(TenantInvalido) as capturado:
            normalizar_tenant(segredo)
        mensagem = str(capturado.exception)
        self.assertNotIn(segredo, mensagem)
        self.assertIn(str(len(segredo)), mensagem)

    def test_invalido_nao_conta_como_sem_contexto(self) -> None:
        with self.assertRaises(TenantInvalido):
            normalizar_tenant("x")
        self.assertNotIn(METRICA_SEM_CONTEXTO, CONTADORES.ler())


class TestTx(unittest.TestCase):
    def setUp(self) -> None:
        CONTADORES.repor()

    def test_define_o_contexto_antes_de_tudo_e_confirma_no_fim(self) -> None:
        conexao = _Conexao()
        with tx(conexao, TENANT) as cursor:
            cursor.execute("SELECT 1")
        self.assertEqual(
            conexao.registo,
            [
                ("cursor",),
                ("execute", SQL_DEFINIR_CONTEXTO, (TENANT,)),
                ("execute", "SELECT 1", ()),
                ("commit",),
                ("close",),
            ],
        )

    def test_o_contexto_e_local_a_transaccao(self) -> None:
        """`set_config(..., true)` e o `SET LOCAL`. Nunca de sessao."""
        self.assertIn("set_config('app.tenant_id', %s, true)", SQL_DEFINIR_CONTEXTO)
        self.assertNotIn("false", SQL_DEFINIR_CONTEXTO)

    def test_o_tenant_vai_como_parametro_e_nunca_interpolado(self) -> None:
        conexao = _Conexao()
        with tx(conexao, TENANT):
            pass
        _, sql, parametros = conexao.registo[1]
        self.assertNotIn(TENANT, sql)
        self.assertEqual(parametros, (TENANT,))

    def test_erro_desfaz_e_propaga(self) -> None:
        conexao = _Conexao()
        with self.assertRaises(ZeroDivisionError):
            with tx(conexao, TENANT):
                1 / 0
        self.assertEqual(conexao.verbos(), ["cursor", "execute", "rollback", "close"])

    def test_sem_tenant_nao_toca_na_ligacao(self) -> None:
        conexao = _Conexao()
        with self.assertRaises(ContextoEmFalta):
            with tx(conexao, None):
                self.fail("nao devia entrar")
        self.assertEqual(conexao.registo, [])
        self.assertEqual(CONTADORES.ler()[METRICA_SEM_CONTEXTO], 1)

    def test_tenant_invalido_nao_toca_na_ligacao(self) -> None:
        conexao = _Conexao()
        with self.assertRaises(TenantInvalido):
            with tx(conexao, "nao-e-uuid"):
                self.fail("nao devia entrar")
        self.assertEqual(conexao.registo, [])

    def test_autocommit_e_recusado(self) -> None:
        """Em autocommit o contexto expirava antes da primeira consulta."""
        conexao = _Conexao(autocommit=True)
        with self.assertRaises(LigacaoEmAutocommit):
            with tx(conexao, TENANT):
                self.fail("nao devia entrar")
        self.assertEqual(conexao.registo, [])

    def test_o_cursor_fecha_se_mesmo_quando_o_commit_falha(self) -> None:
        class _FalhaNoCommit(_Conexao):
            def commit(self) -> None:
                raise RuntimeError("ligacao perdida")

        conexao = _FalhaNoCommit()
        with self.assertRaises(RuntimeError):
            with tx(conexao, TENANT):
                pass
        self.assertEqual(conexao.verbos()[-2:], ["rollback", "close"])

    def test_duas_transaccoes_definem_o_contexto_duas_vezes(self) -> None:
        """Nada fica guardado no helper entre chamadas: nao ha estado para vazar."""
        conexao = _Conexao()
        outro = "11111111-2222-4333-8444-555555555555"
        with tx(conexao, TENANT):
            pass
        with tx(conexao, outro):
            pass
        definidos = [e[2][0] for e in conexao.registo if e[0] == "execute"]
        self.assertEqual(definidos, [TENANT, outro])


class TestLigacaoEmUso(unittest.TestCase):
    """Reentrancia e ligacao partilhada: o achado 1 da revisao do KAM-004.

    Contra um PostgreSQL real, `tx(c, A)` com `tx(c, B)` la dentro punha o cursor
    de fora a ler as linhas de B, e o `commit` de dentro confirmava o trabalho de
    fora. A segunda entrada na mesma ligacao tem de levantar, sem tocar nela.
    """

    OUTRO = "11111111-2222-4333-8444-555555555555"

    def test_tx_dentro_de_tx_na_mesma_ligacao_levanta(self) -> None:
        conexao = _Conexao()
        with self.assertRaises(LigacaoEmUso):
            with tx(conexao, TENANT):
                antes = list(conexao.registo)
                with tx(conexao, self.OUTRO):
                    self.fail("a segunda transaccao nao podia abrir")
        # A de dentro nao tocou na ligacao: nem cursor, nem set_config, nem commit.
        self.assertEqual(conexao.registo[: len(antes)], antes)
        definidos = [e[2][0] for e in conexao.registo if e[0] == "execute"]
        self.assertEqual(definidos, [TENANT])
        # E a de fora desfez-se: o erro propagou-se por ela.
        self.assertEqual(conexao.verbos()[-2:], ["rollback", "close"])
        self.assertNotIn("commit", conexao.verbos())

    def test_todas_as_combinacoes_de_tx_e_tx_batch_levantam(self) -> None:
        def fora_tx(c):
            return tx(c, TENANT)

        def fora_batch(c):
            return tx_batch(c, "retencao_mensal")

        for nome_fora, fora in (("tx", fora_tx), ("tx_batch", fora_batch)):
            for nome_dentro, dentro in (("tx", fora_tx), ("tx_batch", fora_batch)):
                with self.subTest(fora=nome_fora, dentro=nome_dentro):
                    conexao = _Conexao()
                    with self.assertRaises(LigacaoEmUso):
                        with fora(conexao):
                            with dentro(conexao):
                                pass
                    self.assertNotIn("commit", conexao.verbos())

    def test_a_ligacao_fica_livre_depois_de_sair_com_ou_sem_erro(self) -> None:
        conexao = _Conexao()
        with tx(conexao, TENANT):
            pass
        with self.assertRaises(RuntimeError):
            with tx(conexao, TENANT):
                raise RuntimeError("falhou a meio")
        with self.assertRaises(LigacaoEmUso):
            with tx(conexao, TENANT):
                with tx(conexao, TENANT):
                    pass
        with tx(conexao, self.OUTRO):
            pass
        self.assertEqual(tenant_guard._EM_USO, set())

    def test_ligacoes_diferentes_nao_se_bloqueiam(self) -> None:
        a, b = _Conexao(), _Conexao()
        with tx(a, TENANT):
            with tx(b, self.OUTRO):
                pass
        self.assertEqual(a.verbos().count("commit"), 1)
        self.assertEqual(b.verbos().count("commit"), 1)

    def test_duas_threads_na_mesma_ligacao_so_uma_entra(self) -> None:
        conexao = _Conexao()
        dentro = threading.Event()
        largar = threading.Event()
        recusadas: list[BaseException] = []

        def primeira() -> None:
            with tx(conexao, TENANT):
                dentro.set()
                largar.wait(timeout=10)

        def segunda() -> None:
            try:
                with tx(conexao, self.OUTRO):
                    pass
            except LigacaoEmUso as erro:
                recusadas.append(erro)

        t1 = threading.Thread(target=primeira)
        t1.start()
        self.assertTrue(dentro.wait(timeout=10))
        t2 = threading.Thread(target=segunda)
        t2.start()
        t2.join(timeout=10)
        largar.set()
        t1.join(timeout=10)
        self.assertEqual(len(recusadas), 1)
        definidos = [e[2][0] for e in conexao.registo if e[0] == "execute"]
        self.assertEqual(definidos, [TENANT])

    def test_a_mensagem_nao_repete_o_tenant(self) -> None:
        conexao = _Conexao()
        with self.assertRaises(LigacaoEmUso) as capturado:
            with tx(conexao, TENANT):
                with tx(conexao, self.OUTRO):
                    pass
        self.assertNotIn(TENANT, str(capturado.exception))
        self.assertNotIn(self.OUTRO, str(capturado.exception))


class TestTxBatch(unittest.TestCase):
    def setUp(self) -> None:
        CONTADORES.repor()

    def test_nao_define_contexto_e_conta_o_job(self) -> None:
        conexao = _Conexao()
        with tx_batch(conexao, "retencao_mensal") as cursor:
            cursor.execute("SELECT 1")
        self.assertEqual(
            conexao.registo,
            [("cursor",), ("execute", "SELECT 1", ()), ("commit",), ("close",)],
        )
        self.assertEqual(CONTADORES.ler(), {f"{METRICA_BATCH}:retencao_mensal": 1})

    def test_sem_nome_de_job_nao_ha_transaccao(self) -> None:
        for job in ("", None, "X", "ab", "Com Espaco", "com-hifen", "9inicio", 7,
                    "a" * 64):
            with self.subTest(job=repr(job)):
                conexao = _Conexao()
                with self.assertRaises(JobSemNome):
                    with tx_batch(conexao, job):
                        self.fail("nao devia entrar")
                self.assertEqual(conexao.registo, [])
        self.assertEqual(CONTADORES.ler(), {})

    def test_erro_desfaz(self) -> None:
        conexao = _Conexao()
        with self.assertRaises(KeyError):
            with tx_batch(conexao, "faturacao"):
                raise KeyError("x")
        self.assertEqual(conexao.verbos(), ["cursor", "rollback", "close"])

    def test_autocommit_e_recusado(self) -> None:
        with self.assertRaises(LigacaoEmAutocommit):
            with tx_batch(_Conexao(autocommit=True), "faturacao"):
                self.fail("nao devia entrar")


class TestNaoRegistaNada(unittest.TestCase):
    """DoD: o helper nao regista `tenant_id` associado a conteudo."""

    def test_nenhum_registo_em_nenhum_caminho(self) -> None:
        with self.assertNoLogs(level=logging.DEBUG):
            with tx(_Conexao(), TENANT) as cursor:
                cursor.execute("SELECT 'conteudo de um cliente'")
            with tx_batch(_Conexao(), "retencao_mensal"):
                pass
            for invalido in (None, "x"):
                with self.assertRaises((ContextoEmFalta, TenantInvalido)):
                    with tx(_Conexao(), invalido):
                        pass

    def test_o_modulo_nao_importa_logging(self) -> None:
        self.assertFalse(hasattr(tenant_guard, "logging"))
        self.assertFalse(hasattr(tenant_guard, "logger"))


class TestContadores(unittest.TestCase):
    def test_sao_seguros_entre_threads(self) -> None:
        contadores = tenant_guard.Contadores()

        def trabalhar() -> None:
            for _ in range(500):
                contadores.incrementar("x")

        fios = [threading.Thread(target=trabalhar) for _ in range(8)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join()
        self.assertEqual(contadores.ler(), {"x": 4000})

    def test_ler_devolve_uma_copia(self) -> None:
        contadores = tenant_guard.Contadores()
        contadores.incrementar("x")
        copia = contadores.ler()
        copia["x"] = 99
        self.assertEqual(contadores.ler(), {"x": 1})
        contadores.repor()
        self.assertEqual(contadores.ler(), {})


if __name__ == "__main__":
    unittest.main()
