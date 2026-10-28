"""A `platform.draft_decisions` contra um PostgreSQL real (KAM-114).

    TestOEsquemaEAsColunas  as treze colunas da `0024` e os indices
    TestOCompareAndSet      o CAS `pendente -> decidido`, e duas sessoes
    TestRestricoes          os `CHECK` da revisao, um a um
    TestPrivilegios         o `GRANT` por coluna morde; sem `DELETE`
    TestIsolamento          X-03 e X-04, com canarios
    TestPrivacidade         o varrimento **dos dados**, nao do DDL
    TestAVista              a `v_draft_metrics` e o `security_invoker`

O que **so** aqui se prova, e nao se prova com uma base falsa:

| Propriedade | Porque precisa da base |
|---|---|
| o *compare-and-set* | quem decide se um `UPDATE ... WHERE decisao IS NULL` casa e o servidor. Uma base falsa compara SQL por texto e nunca o interpreta: um `%s` fora de ordem, um predicado a mais — nada disso o *gate* 4 ve |
| duas decisoes concorrentes | precisam de **duas sessoes**. Em serie a segunda nem chega ao predicado, e um ensaio com uma ligacao diz «passou» sem ter medido a corrida |
| o `UPDATE` por coluna | o `GRANT` e por coluna; um `UPDATE` do `tenant_id` da `42501`, e num duplo nao se ve |
| a RLS | a politica e da base. O `WITH CHECK` e o que impede gravar a decisao de um rascunho no nome de outro *tenant* |
| os `CHECK` | o par `decisao`/`decidido_at`, a `razao_edicao` so no `editado`, o `edicao_numero_livre` so no `editado`, o SemVer do `graph_version`, a forma hexadecimal do `draft_id` — os seis sao do servidor |
| o varrimento de privacidade | **e sobre os dados**, nao sobre o DDL. E a licao do KAM-026: o varrimento dele dava zero por procurar texto num campo `msgpack` |
| o `security_invoker` da vista | sem ele a vista corre com os privilegios do dono e ve as linhas de todos os *tenants*. Isso le-se no catalogo, nao no codigo |
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

from tests import factories
from tests.base import TABELAS, TABELAS_ATE_0023, alembic_ok
from tests_agr.base import ComAgr

_RAIZ = Path(__file__).resolve().parents[2]
for _caminho in (
    _RAIZ / "libs" / "py-core" / "src",
    _RAIZ / "services" / "agr" / "src",
):
    if str(_caminho) not in sys.path:
        sys.path.insert(0, str(_caminho))

from kamba_agr.concierge import consultas  # noqa: E402
from kamba_agr.concierge.maquina import (  # noqa: E402
    DECISOES,
    MOTIVOS,
    draft_id as derivar_draft_id,
)

TABELA = "platform.draft_decisions"
VISTA = "platform.v_draft_metrics"

#: As treze colunas da `0024`, pela ordem do `CREATE TABLE`.
COLUNAS = (
    "draft_id",
    "tenant_id",
    "thread_id",
    "turn_seq",
    "turn_id",
    "graph_version",
    "decisao",
    "motivo",
    "razao_edicao",
    "edicao_numero_livre",
    "latencia_ms",
    "criado_at",
    "decidido_at",
)


class _ComRascunhos(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.tenant = factories.tenant(self.semente)
        self._tenants.append(self.tenant)
        self.contacto = str(uuid.uuid4())
        self.thread = f"{self.tenant}:{self.contacto}"
        self.ligacao_app = self.ligar("app")
        # Corre **antes** do `_limpar` do `ComAgr` (LIFO), pelo que as linhas
        # saem antes dos *tenants* que elas referenciam pela FK. E a mesma via
        # do `_ComLlm` do KAM-030.
        self.addCleanup(self._limpar_rascunhos)

    def _limpar_rascunhos(self) -> None:
        """Como `admin`: a tabela nao e *append-only*, mas o `kamba_app` nao tem
        `DELETE` — e de propósito (a retencao e do `kamba_batch`).
        """
        try:
            self.semente.execute(f"DELETE FROM {TABELA}")
        except Exception:  # noqa: BLE001 — a limpeza nao decide o veredicto
            pass

    def abrir(self, *, tenant=None, thread=None, turn_seq=1, **trocas):
        """Semeia um rascunho `pendente` como `admin`. Devolve o `draft_id`."""
        tenant = tenant or self.tenant
        thread = thread or self.thread
        campos = {
            "draft_id": derivar_draft_id(thread, turn_seq),
            "tenant_id": tenant,
            "thread_id": thread,
            "turn_seq": turn_seq,
            "turn_id": f"wamid.{uuid.uuid4().hex[:12]}",
            "graph_version": "1.1.0",
        }
        campos.update(trocas)
        nomes = ", ".join(campos)
        marcas = ", ".join(["%s"] * len(campos))
        self.semente.execute(
            f"INSERT INTO {TABELA} ({nomes}) VALUES ({marcas})", tuple(campos.values())
        )
        return campos["draft_id"]

    def como_auditor(self, sql, parametros=()):
        """Corre `sql` como `kamba_audit`, com contexto do *tenant* do ensaio.

        **Com contexto**, e e isso que prova o `security_invoker`: o
        `kamba_audit` e `NOBYPASSRLS`, pelo que sem contexto a vista devolvia
        zero linhas — e e exactamente o defeito que a revisao adversarial mediu
        no `golden-candidates`, que corria como este papel e sem contexto.
        """
        ligacao = self.ligar("audit")
        cursor = ligacao.cursor()
        factories.contexto(cursor, self.tenant)
        cursor.execute(sql, parametros)
        return cursor

    def como_app(self, tenant, sql, parametros=()):
        """Corre `sql` com contexto de `tenant`, no papel da aplicacao."""
        cursor = self.ligacao_app.cursor()
        factories.contexto(cursor, tenant)
        cursor.execute(sql, parametros)
        return cursor


class TestOEsquemaEAsColunas(_ComRascunhos):
    def test_as_treze_colunas_sao_as_da_revisao(self) -> None:
        self.semente.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'draft_decisions' "
            "ORDER BY ordinal_position"
        )
        lidas = tuple(linha[0] for linha in self.semente.fetchall())
        self.assertEqual(lidas, COLUNAS)

    def test_nao_ha_coluna_de_texto_sem_dominio_nem_forma(self) -> None:
        """A afirmacao em que a prova do criterio 7 assenta, medida.

        As colunas `text` desta tabela sao **seis**, e **nenhuma** e livre:
        quatro tem forma (`draft_id` hexadecimal, `graph_version` SemVer, e o
        `thread_id`/`turn_id` exigem nao-vazio) e duas tem dominio fechado
        (`decisao`, `motivo`). O `graph_version` **ganhou** a sua na revisao
        adversarial: ele e o unico que sai na exportacao, e sem forma era um
        campo livre a atravessar para fora.

        (Eram «cinco» na primeira versao deste ensaio, que se esqueceu do
        `draft_id` — e a base corrigiu a contagem, que e o ponto de a ler do
        `information_schema` em vez de a escrever a mao.)
        """
        self.semente.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'draft_decisions' "
            "AND data_type = 'text' ORDER BY column_name"
        )
        texto = sorted(linha[0] for linha in self.semente.fetchall())
        self.assertEqual(
            texto,
            [
                "decisao",
                "draft_id",
                "graph_version",
                "motivo",
                "thread_id",
                "turn_id",
            ],
        )
        self.semente.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = %s::regclass AND contype = 'c'",
            (TABELA,),
        )
        restricoes = " ".join(linha[0] for linha in self.semente.fetchall())
        for coluna in texto:
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, restricoes)

    def test_os_tres_indices_existem_e_dois_sao_parciais(self) -> None:
        self.semente.execute(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE schemaname = 'platform' AND tablename = 'draft_decisions' "
            "ORDER BY indexname"
        )
        indices = dict(self.semente.fetchall())
        self.assertIn("draft_decisions_pendentes_idx", indices)
        self.assertIn("draft_decisions_tenant_versao_idx", indices)
        self.assertIn("draft_decisions_thread_idx", indices)
        # Parciais: um indice total crescia com as decididas para sempre.
        self.assertIn("WHERE (decisao IS NULL)", indices["draft_decisions_pendentes_idx"])
        self.assertIn("WHERE (decisao IS NULL)", indices["draft_decisions_thread_idx"])

    def test_os_dominios_do_check_sao_os_do_codigo(self) -> None:
        """Sem isto as listas divergiam e o codigo escrevia um valor que a base
        recusa com `23514` — um 500 em producao e nenhum teste vermelho.
        """
        self.semente.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'draft_decisions_decisao_ck'"
        )
        definicao = self.semente.fetchone()[0]
        for valor in DECISOES:
            self.assertIn(f"'{valor}'", definicao)
        self.semente.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'draft_decisions_motivo_ck'"
        )
        definicao = self.semente.fetchone()[0]
        for valor in MOTIVOS:
            self.assertIn(f"'{valor}'", definicao)


class TestOCompareAndSet(_ComRascunhos):
    """Criterio 2: `pendente -> decidido`, e **uma** decisao."""

    def test_o_cas_vence_uma_vez_e_a_segunda_nao_casa_linha(self) -> None:
        draft_id = self.abrir()
        parametros = ("aprovado", None, None, False, self.tenant, draft_id, self.thread)
        cursor = self.como_app(
            self.tenant, consultas.SQL_DECIDIR_RASCUNHO, parametros
        )
        self.assertEqual(list(cursor.fetchone()), [1])
        self.ligacao_app.commit()

        cursor = self.como_app(
            self.tenant, consultas.SQL_DECIDIR_RASCUNHO, parametros
        )
        self.assertIsNone(cursor.fetchone(), "o segundo pedido casou linha")
        self.ligacao_app.commit()

    def test_duas_sessoes_concorrentes_dao_uma_decisao(self) -> None:
        """**Duas ligacoes**, que e a unica forma de provocar a corrida.

        Em serie a segunda nem chega ao predicado: a primeira ja confirmou.
        """
        draft_id = self.abrir()
        outra = self.ligar("app")
        parametros = ("aprovado", None, None, False, self.tenant, draft_id, self.thread)

        c1 = self.ligacao_app.cursor()
        factories.contexto(c1, self.tenant)
        c1.execute(consultas.SQL_DECIDIR_RASCUNHO, parametros)
        venceu_primeiro = c1.fetchone() is not None

        c2 = outra.cursor()
        factories.contexto(c2, self.tenant)
        self.ligacao_app.commit()
        c2.execute(consultas.SQL_DECIDIR_RASCUNHO, parametros)
        venceu_segundo = c2.fetchone() is not None
        outra.commit()

        self.assertTrue(venceu_primeiro)
        self.assertFalse(venceu_segundo, "as duas sessoes decidiram")

    def test_a_latencia_e_calculada_pela_base(self) -> None:
        """Com dois relogios a diferenca media o desvio entre eles."""
        draft_id = self.abrir()
        self.semente.execute(
            f"UPDATE {TABELA} SET criado_at = now() - interval '5 seconds' "
            "WHERE draft_id = %s",
            (draft_id,),
        )
        self.como_app(
            self.tenant,
            consultas.SQL_DECIDIR_RASCUNHO,
            ("aprovado", None, None, False, self.tenant, draft_id, self.thread),
        )
        self.ligacao_app.commit()
        self.semente.execute(
            f"SELECT latencia_ms FROM {TABELA} WHERE draft_id = %s", (draft_id,)
        )
        latencia = self.semente.fetchone()[0]
        self.assertGreaterEqual(latencia, 4_500)
        self.assertLess(latencia, 60_000)

    def test_o_rascunho_de_outro_contacto_do_mesmo_tenant_nao_decide(self) -> None:
        """A licao do KAM-034: o `draft_id` e irreversivel, pelo que o
        `tenant_id` sozinho nao chega — decidia-se a mensagem de outra pessoa.
        """
        draft_id = self.abrir()
        outro_thread = f"{self.tenant}:{uuid.uuid4()}"
        cursor = self.como_app(
            self.tenant,
            consultas.SQL_DECIDIR_RASCUNHO,
            ("aprovado", None, None, False, self.tenant, draft_id, outro_thread),
        )
        self.assertIsNone(cursor.fetchone())
        self.ligacao_app.commit()
        self.semente.execute(
            f"SELECT decisao FROM {TABELA} WHERE draft_id = %s", (draft_id,)
        )
        self.assertIsNone(self.semente.fetchone()[0])

    def test_a_reversao_devolve_o_rascunho_a_pendente(self) -> None:
        draft_id = self.abrir()
        self.como_app(
            self.tenant,
            consultas.SQL_DECIDIR_RASCUNHO,
            ("aprovado", None, None, False, self.tenant, draft_id, self.thread),
        )
        self.ligacao_app.commit()
        cursor = self.como_app(
            self.tenant,
            __import__(
                "kamba_agr.concierge.consultas", fromlist=["SQL_REVERTER_DECISAO"]
            ).SQL_REVERTER_DECISAO,
            (self.tenant, draft_id, self.thread, "aprovado"),
        )
        self.assertEqual(list(cursor.fetchone()), [1])
        self.ligacao_app.commit()
        self.semente.execute(
            f"SELECT decisao, decidido_at, latencia_ms FROM {TABELA} "
            "WHERE draft_id = %s",
            (draft_id,),
        )
        self.assertEqual(list(self.semente.fetchone()), [None, None, None])

    def test_a_insercao_e_idempotente_por_draft_id(self) -> None:
        """Criterio 2: re-executar o no 5x cria **1** rascunho."""
        for _ in range(5):
            cursor = self.como_app(
                self.tenant,
                consultas.SQL_ABRIR_RASCUNHO,
                (
                    derivar_draft_id(self.thread, 7),
                    self.tenant,
                    self.thread,
                    7,
                    "wamid.repetido",
                    "1.1.0",
                ),
            )
            cursor.fetchone()
            self.ligacao_app.commit()
        self.semente.execute(
            f"SELECT count(*) FROM {TABELA} WHERE thread_id = %s AND turn_seq = 7",
            (self.thread,),
        )
        self.assertEqual(self.semente.fetchone()[0], 1)


class TestRestricoes(_ComRascunhos):
    """Os `CHECK` da `0024`, um a um, contra o servidor."""

    def _recusa(self, sql, parametros=()):
        import pg8000.dbapi

        with self.assertRaises(pg8000.dbapi.DatabaseError):
            self.semente.execute(sql, parametros)

    def test_uma_decisao_fora_do_dominio_e_recusada(self) -> None:
        self._recusa(
            f"UPDATE {TABELA} SET decisao = 'talvez', decidido_at = now() "
            "WHERE draft_id = %s",
            (self.abrir(),),
        )

    def test_uma_decisao_sem_instante_e_recusada(self) -> None:
        """O par `decisao`/`decidido_at` nao pode divergir.

        **E e por isto que a receita do X-03 altera o `motivo` e nao a
        `decisao`**: um `SET decisao = <valor>` sozinho viola **para qualquer
        valor**, e um `UPDATE` que rebenta com `23514` nao mede isolamento.
        """
        self._recusa(
            f"UPDATE {TABELA} SET decisao = 'aprovado' WHERE draft_id = %s",
            (self.abrir(),),
        )

    def test_um_instante_sem_decisao_e_recusado(self) -> None:
        self._recusa(
            f"UPDATE {TABELA} SET decidido_at = now() WHERE draft_id = %s",
            (self.abrir(),),
        )

    def test_uma_razao_de_edicao_fora_do_editado_e_recusada(self) -> None:
        self._recusa(
            f"UPDATE {TABELA} SET decisao = 'rejeitado', decidido_at = now(), "
            "razao_edicao = 0.4, motivo = 'tom' WHERE draft_id = %s",
            (self.abrir(),),
        )

    def test_um_editado_sem_razao_de_edicao_e_recusado(self) -> None:
        self._recusa(
            f"UPDATE {TABELA} SET decisao = 'editado', decidido_at = now(), "
            "motivo = 'tom' WHERE draft_id = %s",
            (self.abrir(),),
        )

    def test_uma_razao_de_edicao_fora_do_intervalo_e_recusada(self) -> None:
        self._recusa(
            f"UPDATE {TABELA} SET decisao = 'editado', decidido_at = now(), "
            "motivo = 'tom', razao_edicao = 1.5 WHERE draft_id = %s",
            (self.abrir(),),
        )

    def test_um_numero_livre_fora_do_editado_e_recusado(self) -> None:
        self._recusa(
            f"UPDATE {TABELA} SET decisao = 'rejeitado', decidido_at = now(), "
            "motivo = 'tom', edicao_numero_livre = true WHERE draft_id = %s",
            (self.abrir(),),
        )

    def test_um_graph_version_sem_semver_e_recusado(self) -> None:
        """A forma que fecha o buraco do criterio 7: esta coluna **sai** na
        exportacao, e sem forma era um campo de texto livre a atravessar.
        """
        self._recusa(
            f"UPDATE {TABELA} SET graph_version = 'o nome do cliente' "
            "WHERE draft_id = %s",
            (self.abrir(),),
        )

    def test_um_draft_id_que_nao_e_hexadecimal_e_recusado(self) -> None:
        self._recusa(
            f"INSERT INTO {TABELA} "
            "(draft_id, tenant_id, thread_id, turn_seq, turn_id) "
            "VALUES ('nao-e-um-sha256', %s, %s, 1, 'wamid.x')",
            (self.tenant, self.thread),
        )

    def test_um_turn_seq_negativo_e_recusado(self) -> None:
        self._recusa(
            f"INSERT INTO {TABELA} "
            "(draft_id, tenant_id, thread_id, turn_seq, turn_id) "
            "VALUES (%s, %s, %s, -1, 'wamid.x')",
            ("f" * 64, self.tenant, self.thread),
        )


class TestPrivilegios(_ComRascunhos):
    def test_o_kamba_app_nao_pode_reescrever_o_tenant(self) -> None:
        """O `GRANT UPDATE` e por coluna; sem isso o papel da aplicacao
        reescrevia o `tenant_id` de uma linha ja gravada.
        """
        import pg8000.dbapi

        draft_id = self.abrir()
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.como_app(
                self.tenant,
                f"UPDATE {TABELA} SET tenant_id = %s WHERE draft_id = %s",
                (str(uuid.uuid4()), draft_id),
            )
        self.assertIn("permission denied", str(capturado.exception).lower())
        self.ligacao_app.rollback()

    def test_o_kamba_app_nao_pode_apagar(self) -> None:
        """A retencao e do `kamba_batch` (KAM-071), e uma decisao gravada nao se
        apaga a pedido de quem a produziu.
        """
        import pg8000.dbapi

        draft_id = self.abrir()
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            self.como_app(
                self.tenant, f"DELETE FROM {TABELA} WHERE draft_id = %s", (draft_id,)
            )
        self.ligacao_app.rollback()


class TestIsolamento(_ComRascunhos):
    """X-03 e X-04: o tenant A nao le nem escreve o rascunho de B."""

    def setUp(self) -> None:
        super().setUp()
        self.outro = factories.tenant(self.semente)
        self._tenants.append(self.outro)
        self.thread_de_b = f"{self.outro}:{uuid.uuid4()}"
        self.draft_de_a = self.abrir()
        self.draft_de_b = self.abrir(tenant=self.outro, thread=self.thread_de_b)

    def test_o_contexto_de_a_nao_ve_o_rascunho_de_b(self) -> None:
        cursor = self.como_app(
            self.tenant, f"SELECT draft_id FROM {TABELA} ORDER BY draft_id"
        )
        vistos = {linha[0] for linha in cursor.fetchall()}
        self.ligacao_app.commit()
        self.assertIn(self.draft_de_a, vistos)
        self.assertNotIn(self.draft_de_b, vistos)

    def test_o_contexto_de_a_nao_decide_o_rascunho_de_b(self) -> None:
        cursor = self.como_app(
            self.tenant,
            consultas.SQL_DECIDIR_RASCUNHO,
            (
                "aprovado",
                None,
                None,
                False,
                self.outro,
                self.draft_de_b,
                self.thread_de_b,
            ),
        )
        self.assertIsNone(cursor.fetchone())
        self.ligacao_app.commit()
        self.semente.execute(
            f"SELECT decisao FROM {TABELA} WHERE draft_id = %s", (self.draft_de_b,)
        )
        self.assertIsNone(self.semente.fetchone()[0])

    def test_sem_contexto_nenhum_nao_se_ve_nada(self) -> None:
        """X-04: a RLS falha **fechada**."""
        cursor = self.ligacao_app.cursor()
        cursor.execute("SELECT count(*) FROM platform.draft_decisions")
        self.assertEqual(cursor.fetchone()[0], 0)
        self.ligacao_app.rollback()

    def test_o_with_check_impede_gravar_no_nome_de_outro(self) -> None:
        import pg8000.dbapi

        cursor = self.ligacao_app.cursor()
        factories.contexto(cursor, self.tenant)
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            cursor.execute(
                f"INSERT INTO {TABELA} "
                "(draft_id, tenant_id, thread_id, turn_seq, turn_id) "
                "VALUES (%s, %s, %s, 1, 'wamid.x')",
                ("a" * 64, self.outro, self.thread_de_b),
            )
        self.ligacao_app.rollback()


class TestPrivacidade(_ComRascunhos):
    """O varrimento e **sobre os dados**, nao sobre o DDL.

    E a licao do KAM-026: o varrimento dele dava zero por procurar texto num
    campo `msgpack`. Aqui semeia-se um canario em **todas** as colunas de texto
    que o aceitem e exige-se que ele apareca — senao o varrimento nao procurou
    onde devia.
    """

    def test_nenhuma_coluna_aceita_o_texto_de_um_cliente(self) -> None:
        import pg8000.dbapi

        canario = "O meu nome e Ana e o meu numero e 923000111"
        draft_id = self.abrir()
        recusadas = []
        for coluna in ("graph_version", "decisao", "motivo"):
            try:
                self.semente.execute(
                    f"UPDATE {TABELA} SET {coluna} = %s WHERE draft_id = %s",
                    (canario, draft_id),
                )
            except pg8000.dbapi.DatabaseError:
                recusadas.append(coluna)
        self.assertEqual(
            sorted(recusadas),
            ["decisao", "graph_version", "motivo"],
            "uma coluna aceitou texto de cliente",
        )

    def test_o_varrimento_encontra_um_canario_onde_ele_cabe(self) -> None:
        """O controlo positivo: sem ele, um varrimento que nao procura nada
        passava o teste de cima.

        O `turn_id` e o `thread_id` **aceitam** texto (sao identificadores, so
        exigem nao-vazio) e por isso sao `identificador` na classificacao do
        `golden_candidates.py` — nunca saem. O varrimento tem de os ver.
        """
        canario = "canario-de-privacidade"
        self.abrir(turn_seq=9, turn_id=canario)
        self.semente.execute(
            f"SELECT count(*) FROM {TABELA} WHERE turn_id = %s", (canario,)
        )
        self.assertEqual(self.semente.fetchone()[0], 1)


class TestAVista(_ComRascunhos):
    def test_a_vista_tem_security_invoker(self) -> None:
        """Sem ele a vista corre com os privilegios do dono e ve tudo.

        O `verificar_vistas` do *gate* 6 ja o exige para **todas** as vistas;
        aqui mede-se nesta, porque e a que este ticket acrescenta.
        """
        self.semente.execute(
            "SELECT COALESCE(c.reloptions, '{}') FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'platform' AND c.relname = 'v_draft_metrics'"
        )
        opcoes = [str(o).replace(" ", "").lower() for o in self.semente.fetchone()[0]]
        self.assertIn("security_invoker=true", opcoes)

    def test_o_kamba_app_nao_le_a_vista(self) -> None:
        """Quem produz as decisoes nao e quem le as metricas.

        A `0024` concede `SELECT` na vista ao `kamba_audit` e ao `kamba_batch` e
        **nao** ao `kamba_app`. Medido aqui porque a primeira versao deste
        ensaio lia a vista como a aplicacao e levou `42501` — e o defeito era do
        ensaio, nao da revisao.
        """
        import pg8000.dbapi

        with self.assertRaises(pg8000.dbapi.DatabaseError):
            self.como_app(self.tenant, f"SELECT 1 FROM {VISTA}")
        self.ligacao_app.rollback()

    def test_as_razoes_contam_so_as_decididas(self) -> None:
        """Incluir pendentes no denominador fazia a taxa de aprovacao descer so
        por haver rascunhos a espera, que nao e informacao sobre a qualidade.
        """
        aprovado = self.abrir(turn_seq=1)
        self.abrir(turn_seq=2)  # fica pendente
        self.semente.execute(
            f"UPDATE {TABELA} SET decisao = 'aprovado', decidido_at = now(), "
            "latencia_ms = 1000 WHERE draft_id = %s",
            (aprovado,),
        )
        total, pendentes, razao = self.como_auditor(
            f"SELECT draft_total, draft_pendentes, draft_approved_ratio FROM {VISTA} "
            "WHERE tenant_id = %s",
            (self.tenant,),
        ).fetchone()
        self.assertEqual((total, pendentes), (2, 1))
        self.assertEqual(Decimal(str(razao)), Decimal("1"))

    def test_sem_decisoes_a_razao_e_nula_e_nao_zero(self) -> None:
        """Um *tenant* sem decisoes nao tem taxa — e nao tem taxa **zero**."""
        self.abrir()
        cursor = self.como_auditor(
            f"SELECT draft_approved_ratio FROM {VISTA} WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertIsNone(cursor.fetchone()[0])


class TestCicloDaRevisao(ComAgr):
    """O `downgrade` da `0024` e o `upgrade` de volta (DoD: migrações reversíveis).

    **O `downgrade` tem de levar a vista e a tabela, e por esta ordem.** A vista
    depende da tabela: um `DROP TABLE` sem ela sairia com «dependent objects
    still exist» ou, com `CASCADE`, levava-a em silencio — e um `CASCADE` numa
    revisao e o que apaga o que ninguem mandou apagar.

    **Nao ha assimetria declarada neste `downgrade`**, ao contrario do da `0022`:
    a `0024` nao faz crescer dominio nenhum de outra revisao, pelo que reverter
    deixa a base exactamente como ela estava na `0023`. Isto mede-se em vez de se
    afirmar.
    """

    def _tabelas(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                nome
                for (nome,) in self.consultar(
                    "SELECT table_name FROM information_schema.tables "
                    " WHERE table_schema = 'platform' AND table_type = 'BASE TABLE'"
                )
            )
        )

    def _vistas(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                nome
                for (nome,) in self.consultar(
                    "SELECT table_name FROM information_schema.views "
                    " WHERE table_schema = 'platform'"
                )
            )
        )

    def test_desce_para_a_0023_e_volta(self) -> None:
        self.assertEqual(self._tabelas(), TABELAS)
        self.assertIn("v_draft_metrics", self._vistas())

        alembic_ok("downgrade", "0023")
        self.assertEqual(self._tabelas(), TABELAS_ATE_0023)
        self.assertNotIn(
            "v_draft_metrics",
            self._vistas(),
            "o downgrade deixou a vista para tras",
        )

        alembic_ok("upgrade", "head")
        self.assertEqual(self._tabelas(), TABELAS)
        self.assertIn("v_draft_metrics", self._vistas())
        # E a politica volta com a tabela: um `downgrade` que deixasse a tabela
        # sem RLS ao subir era pior do que nao descer, porque nada o dizia.
        self.assertEqual(
            self.consultar(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                " WHERE oid = 'platform.draft_decisions'::regclass"
            ),
            [(True, True)],
        )
        # E o `security_invoker` da vista tambem: sem ele, ao subir, a vista
        # passava a ver as linhas de todos os tenants.
        opcoes = self.consultar(
            "SELECT COALESCE(c.reloptions, '{}') FROM pg_class c "
            " JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'v_draft_metrics'"
        )[0][0]
        self.assertIn(
            "security_invoker=true",
            [str(o).replace(" ", "").lower() for o in opcoes],
        )


if __name__ == "__main__":
    unittest.main()
