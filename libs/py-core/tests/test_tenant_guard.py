"""`tenant_guard`: o helper de transaccao, sem base de dados.

A prova contra um PostgreSQL real — que o contexto isola de facto, e que nao
vaza entre transaccoes na mesma ligacao — esta no gate 6 (`db/tests_isolamento`).
Aqui verifica-se o que o helper faz **a ligacao**: a ordem das chamadas, o que
recusa antes de tocar na base, e o que nao escreve em lado nenhum.

Este modulo esta no estrato `critico` de `ci/thresholds.yaml` (90%).
"""

from __future__ import annotations

import ast
import gc
import logging
import re
import threading
import unittest
import uuid
import weakref
from pathlib import Path

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

RAIZ = Path(__file__).resolve().parents[3]
#: Os dois lados da **mesma** guarda. O teste de paridade prende-os como texto.
GUARDA_PY = RAIZ / "libs" / "py-core" / "src" / "kamba_core" / "tenant_guard" / "__init__.py"
GUARDA_TS = RAIZ / "packages" / "core-ts" / "src" / "tenant_guard" / "index.ts"


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
        # `len`, e nao `== set()`: desde o KAM-163 o registo e uma
        # `weakref.WeakSet`, que nao se compara por igualdade com um `set`. O
        # que se afirma e o mesmo — o registo ficou vazio.
        self.assertEqual(len(tenant_guard._EM_USO), 0)

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


class _LimpezaNaoCorreu(RuntimeError):
    """Sinal deste ensaio: o `finally` da guarda nao chegou ao `discard`."""


class _TrincoQueFalhaAoLargar:
    """Um trinco que rebenta na **segunda** tomada, e so nela.

    E a condicao que o bloco do KAM-163 nomeia por extenso — «o `discard` do
    `finally` nao correu» — posta de pe sem tocar no modulo: a entrada entra
    pelo caminho verdadeiro (`tx` → `_exclusiva`) e a limpeza nao chega a
    acontecer. O registo (`_EM_USO`) fica o **verdadeiro**: e dele que se quer
    saber se uma entrada sobrevive ao seu dono, e substitui-lo por um duplo era
    medir o duplo.
    """

    def __init__(self) -> None:
        self._real = threading.Lock()
        self.tomadas = 0

    def __enter__(self):
        self.tomadas += 1
        if self.tomadas > 1:
            raise _LimpezaNaoCorreu("o `finally` da guarda nao chegou ao `discard`")
        return self._real.__enter__()

    def __exit__(self, *erro):
        return self._real.__exit__(*erro)


class TestChaveDoRegisto(unittest.TestCase):
    """A chave do registo e o objecto, e nao o seu endereco (KAM-163).

    O `id()` de um objecto libertado volta a ser atribuido a outro. Um registo
    que guarde o numero e nao o objecto nao tem como saber que o dono do
    endereco mudou, e passa a recusar uma ligacao **genuinamente livre**. O
    gemeo TypeScript da mesma guarda nunca teve o problema: a entrada e o
    objecto, e desaparece com ele.

    O ensaio **forca** a reutilizacao do endereco em vez de esperar por ela:
    «de vez em quando falha» nao se consegue provar, e por isso nao e o
    criterio deste ticket.
    """

    def setUp(self) -> None:
        # Uma entrada deixada para tras por este ensaio nao pode seguir para o
        # teste seguinte: a guarda e estado de modulo.
        self.addCleanup(tenant_guard._EM_USO.clear)

    def _registar_e_perder_a_ligacao(self) -> int:
        """Registar uma ligacao, nao a limpar, perde-la; devolve o endereco.

        A entrada entra pela `tx` e fica para tras porque o `finally` rebenta
        antes do `discard`. Nada em `_EM_USO` e simulado.
        """
        real = tenant_guard._TRINCO_EM_USO
        tenant_guard._TRINCO_EM_USO = _TrincoQueFalhaAoLargar()
        try:
            conexao = _Conexao()
            endereco = id(conexao)
            try:
                with tx(conexao, TENANT):
                    pass
            except _LimpezaNaoCorreu:
                # Sem `as`: a excepcao guardava o *traceback*, o *traceback*
                # guardava a *frame* da `_exclusiva`, e a *frame* guardava a
                # ligacao — que tem de morrer para o endereco vagar.
                pass
            else:
                self.fail("a limpeza correu: o ensaio nao pos a entrada para tras")
        finally:
            tenant_guard._TRINCO_EM_USO = real
        self.assertEqual(len(tenant_guard._EM_USO), 1, "a entrada tinha de ficar")
        del conexao
        gc.collect()
        return endereco

    def _ligacao_no_endereco(self, endereco: int) -> _Conexao:
        """Uma ligacao **nova** no endereco que vagou.

        O CPython devolve o bloco libertado a proxima instancia do mesmo
        tamanho; a candidata que nao acerte larga-se, para nao ficar com ele.
        """
        for _ in range(100):
            candidata = _Conexao()
            if id(candidata) == endereco:
                return candidata
            del candidata
        self.fail(
            "o interpretador nao reutilizou o endereco em 100 tentativas: este "
            "ensaio nao mediu nada, e um verde dele nao prova a correccao"
        )

    def test_uma_ligacao_livre_nao_e_recusada_por_reutilizacao_de_endereco(self) -> None:
        endereco = self._registar_e_perder_a_ligacao()
        nova = self._ligacao_no_endereco(endereco)
        # A ligacao e outra: nunca esteve dentro de transaccao nenhuma. So o
        # endereco e o mesmo — e o endereco nao e a identidade.
        with tx(nova, TENANT):
            pass
        self.assertEqual(nova.verbos().count("commit"), 1)

    def test_a_entrada_nao_sobrevive_a_ligacao_que_a_pediu(self) -> None:
        """A mesma propriedade, sem depender do alocador do interpretador."""
        self._registar_e_perder_a_ligacao()
        self.assertEqual(len(tenant_guard._EM_USO), 0)


class TestSemanticaDaChave(unittest.TestCase):
    """O que a `WeakSet` indexa, e o que isso custa (KAM-163).

    A troca fechou o defeito do endereco e abriu uma diferenca com o gemeo que
    **nao se esconde**: o `WeakSet` do JavaScript indexa por identidade, o
    `weakref.WeakSet` do Python indexa por `__eq__`/`__hash__`. Os dois lados
    indexam «pelo objecto» e nao tem a mesma semantica, e o teste de paridade
    do ficheiro — que compara texto — passaria sem ver isto. Estes ensaios sao
    o que o ve.

    A decisao de ficar com a `WeakSet` e de quem escreveu o ticket: a falha e
    *fail-closed* (recusa uma ligacao livre, nunca deixa passar uma ocupada), e
    a janela e incomparavelmente mais estreita do que a do `id()`, que se
    reutiliza sozinho. O que estes ensaios garantem e que a premissa em que
    essa decisao assenta — ninguem redefinir a igualdade de uma ligacao — deixa
    de ser uma afirmacao de quem escreveu e passa a ser medida.
    """

    #: As pastas com codigo Python deste repositorio. A copia da prova por
    #: mutacao leva as quatro, pelo que o varrimento mede lá o mesmo.
    PASTAS = ("libs", "services", "db", "tools")
    #: O `tenant_guard` exige de uma ligacao exactamente isto. Uma classe que
    #: defina os tres **e** uma ligacao DB-API, chame-se ela como se chamar — e
    #: varrer por forma e o que torna este teste independente dos nomes.
    FORMA_DB_API = frozenset({"cursor", "commit", "rollback"})

    def setUp(self) -> None:
        self.addCleanup(tenant_guard._EM_USO.clear)

    def test_a_weakset_indexa_por_igualdade_e_nao_por_identidade(self) -> None:
        """A diferenca com o gemeo, medida em vez de suposta.

        Nao e a propriedade que se quer: e a que se tem, e esta aqui para que
        ninguem a redescubra a pensar que os dois lados sao equivalentes.
        """

        class ComIgualdade:
            def __init__(self, nome: str) -> None:
                self.nome = nome

            def __eq__(self, outro: object) -> bool:
                return isinstance(outro, ComIgualdade) and self.nome == outro.nome

            def __hash__(self) -> int:
                return hash(self.nome)

        registo = weakref.WeakSet()
        primeira = ComIgualdade("x")
        registo.add(primeira)
        segunda = ComIgualdade("x")
        self.assertIsNot(primeira, segunda)
        # O `WeakSet` do JavaScript daria `False` aqui, e o `set[int]` com
        # `id()` que isto substituiu tambem.
        self.assertIn(segunda, registo)
        self.assertNotIn(id(segunda), {id(primeira)})

    def _ligacoes_db_api(self) -> list[tuple[str, str, bool, bool]]:
        """As classes deste repositorio que tem a forma de uma ligacao DB-API."""
        achadas = []
        for pasta in self.PASTAS:
            raiz = RAIZ / pasta
            if not raiz.is_dir():
                continue
            for caminho in raiz.rglob("*.py"):
                if any(p in {".venv", "__pycache__", "node_modules"} for p in caminho.parts):
                    continue
                try:
                    arvore = ast.parse(caminho.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for no in ast.walk(arvore):
                    if not isinstance(no, ast.ClassDef):
                        continue
                    metodos = {
                        m.name
                        for m in no.body
                        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                    }
                    if not self.FORMA_DB_API <= metodos:
                        continue
                    achadas.append((
                        f"{caminho.relative_to(RAIZ).as_posix()}:{no.lineno}",
                        no.name,
                        "__eq__" in metodos,
                        "__hash__" in metodos,
                    ))
        return achadas

    def test_o_varrimento_das_ligacoes_morde(self) -> None:
        """Sem isto, um varrimento que nao encontrasse nada saía verde."""
        achadas = self._ligacoes_db_api()
        nomes = {nome for _, nome, _, _ in achadas}
        self.assertIn(
            "_Conexao", nomes, "o varrimento nao encontrou o duplo deste ficheiro"
        )
        self.assertGreaterEqual(len(achadas), 2, achadas)

    def test_nenhuma_ligacao_db_api_deste_repositorio_redefine_a_igualdade(self) -> None:
        """A premissa em que a escolha da `WeakSet` assenta, medida.

        O que isto **nao** cobre: uma ligacao vinda de uma biblioteca de
        terceiros, que nao se define aqui. Dessas, a unica que este repositorio
        usa e a `pg8000`, e tem ensaio proprio a seguir.
        """
        culpadas = [
            (onde, nome)
            for onde, nome, tem_eq, tem_hash in self._ligacoes_db_api()
            if tem_eq or tem_hash
        ]
        self.assertEqual(
            culpadas,
            [],
            "uma ligacao DB-API deste repositorio passou a redefinir a igualdade: "
            "na `weakref.WeakSet` do `_EM_USO` duas ligacoes distintas que se "
            "digam iguais colidem, e a guarda recusa uma ligacao livre",
        )

    def test_o_controlador_real_nao_redefine_a_igualdade(self) -> None:
        """A `pg8000` do `db/ligacao.py` — a unica ligacao real deste repositorio.

        Salta sem a biblioteca, que e o caso do `make test-py` com um Python
        pelado; no *gate* 4 corre, porque a cobertura usa o `.venv` e a
        `pg8000==1.31.5` esta fixada em `db/requirements/migrations.txt` e em
        `services/agr/requirements/runtime.txt`.
        """
        try:
            import pg8000.dbapi
        except ImportError:  # pragma: no cover - medido pela ausencia
            self.skipTest("pg8000 nao instalada neste interpretador")
        ligacao = pg8000.dbapi.Connection
        self.assertIs(ligacao.__eq__, object.__eq__)
        self.assertIs(ligacao.__hash__, object.__hash__)
        self.assertTrue(hasattr(ligacao, "__weakref__"), "nao e fracamente referenciavel")

    def test_uma_ligacao_que_o_registo_nao_pode_indexar_levanta_e_nao_suja(self) -> None:
        """O `TypeError` e alto, e a guarda fica fechada e limpa.

        Sao os dois unicos modos em que a `WeakSet` recusa indexar, e nenhum e
        silencioso: um `tx` que nao consiga reservar a ligacao nao abre
        transaccao nenhuma.
        """

        class SemHash:
            """`__eq__` sem `__hash__`: o Python poe o `__hash__` a `None`."""

            def __eq__(self, outro: object) -> bool:
                return True

            def cursor(self):  # pragma: no cover - nunca se chega aqui
                raise AssertionError("a guarda nao podia ter aberto cursor")

        for ligacao, fragmento in (
            ((), "weak reference"),          # um tuplo nao e fracamente referenciavel
            (SemHash(), "unhashable"),
        ):
            with self.subTest(ligacao=type(ligacao).__name__):
                with self.assertRaises(TypeError) as capturado:
                    with tx(ligacao, TENANT):
                        self.fail("a transaccao nao podia ter aberto")
                self.assertIn(fragmento, str(capturado.exception))
                self.assertEqual(len(tenant_guard._EM_USO), 0)


def _so_codigo(texto: str, *marcas: str) -> str:
    """O texto sem as linhas que sao **so** comentario.

    A paridade e sobre o codigo. Sem isto, um comentario que explique a chave
    antiga falhava o teste — e o comentario do modulo explica-a, porque e a
    razao do KAM-163. Um teste que proibisse documentar o defeito que fechou
    estava a medir a prosa.
    """
    return "\n".join(
        linha for linha in texto.splitlines() if not linha.lstrip().startswith(marcas)
    )


class TestParidadeDoTypeScript(unittest.TestCase):
    """As duas implementacoes da mesma guarda indexam pelo objecto (KAM-163).

    O padrao e o do `TestParidadeDoTypeScript` de `test_ten.py` e o das
    paridades de `test_logger.py`: duas implementacoes do mesmo contrato so se
    mantem honestas se houver uma maquina a confronta-las. O que se prende aqui
    e a **chave do registo** — foi nela que divergiram, e e para la que
    qualquer dos dois lados pode voltar sem que mais nada se queixe.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.py = _so_codigo(GUARDA_PY.read_text(encoding="utf-8"), "#")
        cls.ts = _so_codigo(GUARDA_TS.read_text(encoding="utf-8"), "//", "*", "/*")

    def test_os_dois_ficheiros_existem(self) -> None:
        for ficheiro in (GUARDA_PY, GUARDA_TS):
            with self.subTest(ficheiro=ficheiro.name):
                self.assertTrue(ficheiro.is_file(), ficheiro)

    def test_os_dois_lados_declaram_um_registo_de_referencias_fracas(self) -> None:
        self.assertRegex(
            self.py, r"_EM_USO:\s*weakref\.WeakSet\s*=\s*weakref\.WeakSet\(\)"
        )
        self.assertRegex(self.ts, r"const EM_USO = new WeakSet<object>\(\);")

    def test_nenhum_dos_lados_indexa_por_identidade_numerica(self) -> None:
        """A divergencia que este ticket fechou, e o caminho de volta a ela."""
        for proibido in ("id(conexao)", "set[int]", "dict[int", "WeakValueDictionary"):
            with self.subTest(lado="python", proibido=proibido):
                self.assertNotIn(proibido, self.py)
        for proibido in ("WeakSet<number>", "Set<number>", "Map<number"):
            with self.subTest(lado="typescript", proibido=proibido):
                self.assertNotIn(proibido, self.ts)

    def test_os_dois_lados_dao_a_ligacao_ao_registo_e_nao_uma_chave(self) -> None:
        for esperado in (
            "conexao in _EM_USO",
            "_EM_USO.add(conexao)",
            "_EM_USO.discard(conexao)",
        ):
            with self.subTest(lado="python", esperado=esperado):
                self.assertIn(esperado, self.py)
        for esperado in (
            "EM_USO.has(cliente)",
            "EM_USO.add(cliente)",
            "EM_USO.delete(cliente)",
        ):
            with self.subTest(lado="typescript", esperado=esperado):
                self.assertIn(esperado, self.ts)

    def test_o_registo_e_mesmo_uma_weakset_em_execucao(self) -> None:
        """O texto diz o que esta escrito; isto diz o que esta a correr."""
        self.assertIsInstance(tenant_guard._EM_USO, weakref.WeakSet)

    def test_a_corrida_entre_threads_continua_a_ter_quem_a_resolva(self) -> None:
        """A `WeakSet` resolve a identidade, **nao** a corrida: o trinco fica.

        Do lado TypeScript nao ha trinco por nao haver *threads*: o que o
        substitui e a marcacao acontecer antes do primeiro `await`, e e essa
        adjacencia que se prende.
        """
        self.assertIn("_TRINCO_EM_USO = threading.Lock()", self.py)
        self.assertRegex(
            self.ts,
            r"if \(EM_USO\.has\(cliente\)\) \{\s*throw new LigacaoEmUsoError\(\);"
            r"\s*\}\s*EM_USO\.add\(cliente\);",
        )


if __name__ == "__main__":
    unittest.main()
