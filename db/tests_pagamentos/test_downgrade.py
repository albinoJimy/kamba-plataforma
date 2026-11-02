"""O `downgrade` da `0029` leva o que ela criou, e **deixa o que nao criou**.

«Migracao reversivel» e uma caixa da Definition of Done do KAM-053. O ciclo
`upgrade -> downgrade -> upgrade` ja corre no *gate* 8
(`tests/test_migracao.TestCiclo`), e o que esse ciclo **nao** ve sao as tres
partes desta revisao que o tornam peculiar:

    o papel       o `kamba_pay_hooks` **nao** se apaga: nasce no
                  `db/bootstrap.py`, e uma revisao que o apagasse deixava a base
                  sem um papel que o bootstrap desta versao declara
    a politica    a `pay_hooks_token` e sobre a `payment_accounts`, que e da
                  `0027` — esta revisao nao apaga a tabela, pelo que a politica
                  tem de cair a mao. Deixa-la pendurada fazia o `downgrade` da
                  `0027` encontrar uma politica que nao criou
    o *trigger*   o `payment_charges_beneficiario` liga a funcao da `0027` a
                  tabela desta revisao. Cai com a tabela, e a funcao **fica** —
                  e dela

As duas primeiras sao do tipo que o ciclo do *gate* 8 e cego para ver: um objecto
que fica pendurado nao impede o `upgrade` seguinte, a base volta a parecer certa
em `head`, e o que fica errado e a revisao **anterior**, que ja nao se consegue
descer.

Esta classe **nao** herda de `ComLedger`: controla ela propria a revisao em que a
base esta, como o `TestDowngradeDa0028` do KAM-043. Repoe `head` no fim, corra
bem ou mal.
"""

from __future__ import annotations

import unittest

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

#: As quatro tabelas que a revisao cria, e que o `downgrade` tem de levar.
TABELAS = (
    "payment_callbacks_inbox",
    "payment_charges",
    "payment_events",
    "payment_outbox_map",
)

#: As duas vistas.
VISTAS = ("v_payment_events_audit", "v_payment_ledger_heads")

#: As sete funcoes.
FUNCOES = (
    "append_payment_event",
    "deny_mutation",
    "next_state",
    "payment_event_row_hash",
    "rebuild_charge_state",
    "resolve_webhook_token",
    "verify_ledger_chain",
)

#: Os indices que ela cria. Caem com as tabelas, e e isso que se afirma.
INDICES = (
    "payment_callbacks_inbox_conta_idx",
    "payment_callbacks_inbox_pendentes",
    "payment_charges_activa_uq",
    "payment_charges_ref_uq",
    "payment_charges_tenant_idx",
    "payment_events_charge_idx",
    "payment_events_entrega_uq",
    "payment_events_tenant_idx",
)

#: A revisao anterior. O `downgrade` desta volta aqui.
ANTERIOR = "0028"


class TestDowngradeDa0029(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()

    def tearDown(self) -> None:
        try:
            # Cada processo do Alembic custa segundos: so quando a base nao
            # esta em `head`.
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    # -------------------------------------------------------------- leituras

    def tabelas_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT tablename::text FROM pg_tables "
            " WHERE schemaname = 'platform' AND tablename = ANY(%s) ORDER BY 1",
            (list(TABELAS),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def vistas_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT viewname::text FROM pg_views "
            " WHERE schemaname = 'platform' AND viewname = ANY(%s) ORDER BY 1",
            (list(VISTAS),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def funcoes_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT p.proname::text FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = ANY(%s) ORDER BY 1",
            (list(FUNCOES),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def indices_existentes(self) -> list[str]:
        self.cursor.execute(
            "SELECT indexname::text FROM pg_indexes "
            " WHERE schemaname = 'platform' AND indexname = ANY(%s) ORDER BY 1",
            (list(INDICES),),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def politicas(self, tabela: str) -> list[str]:
        self.cursor.execute(
            "SELECT policyname::text FROM pg_policies "
            " WHERE schemaname = 'platform' AND tablename = %s ORDER BY 1",
            (tabela,),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def tem_papel(self) -> bool:
        self.cursor.execute(
            "SELECT count(*) FROM pg_roles WHERE rolname = 'kamba_pay_hooks'"
        )
        return int(self.cursor.fetchone()[0]) == 1

    # ----------------------------------------------------------------- casos

    def test_em_head_esta_tudo(self) -> None:
        """O ponto de partida. **Sem isto, os casos seguintes nao dizem nada.**"""
        self.assertEqual(self.tabelas_existentes(), sorted(TABELAS))
        self.assertEqual(self.vistas_existentes(), sorted(VISTAS))
        self.assertEqual(self.funcoes_existentes(), sorted(FUNCOES))
        self.assertEqual(self.indices_existentes(), sorted(INDICES))
        self.assertEqual(self.politicas("payment_charges"), ["tenant_iso"])
        self.assertEqual(self.politicas("payment_events"), ["tenant_iso"])
        self.assertEqual(
            self.politicas("payment_accounts"), ["pay_hooks_token", "tenant_iso"]
        )
        self.assertTrue(self.tem_papel())

    def test_o_downgrade_leva_tabelas_vistas_funcoes_indices_e_politicas(self) -> None:
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas_existentes(), [])
        self.assertEqual(self.vistas_existentes(), [])
        self.assertEqual(self.funcoes_existentes(), [])
        self.assertEqual(self.indices_existentes(), [])

    def test_o_downgrade_tira_a_politica_da_tabela_da_0027(self) -> None:
        """A parte que o ciclo do *gate* 8 e cego para ver.

        A `pay_hooks_token` e sobre uma tabela que esta revisao **nao** apaga.
        Deixa-la pendurada nao impede o `upgrade` seguinte — impede o
        `downgrade` da `0027`, que corre `DROP POLICY tenant_iso` e depois
        `DROP TABLE` sem `CASCADE` e encontra uma politica que nao criou. Isto
        e, a revisao que fica estragada e a **anterior**.
        """
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(
            self.politicas("payment_accounts"),
            ["tenant_iso"],
            "a pay_hooks_token ficou pendurada numa tabela da 0027",
        )

    def test_o_downgrade_nao_apaga_o_papel(self) -> None:
        """O papel vive fora de schema nenhum, e nasce no `db/bootstrap.py`.

        E a mesma regra que os outros sete seguem desde o KAM-003: «o
        `downgrade base` nao os remove — o criterio de aceitacao mede objectos em
        `platform`, e um papel nao vive em schema nenhum». Apaga-lo aqui deixava
        a base sem um papel que o bootstrap desta versao declara, e o `aplicar()`
        seguinte recria-o com uma palavra-passe nova — isto e, a credencial que o
        servico `pay` tem deixava de servir, por causa de um `downgrade` de
        base de dados.
        """
        alembic_ok("downgrade", ANTERIOR)
        self.assertTrue(self.tem_papel())

    def test_o_downgrade_nao_apaga_a_funcao_da_0027(self) -> None:
        """A `assert_beneficiary` e da `0027`; o *trigger* que a liga e desta.

        O *trigger* cai com a `payment_charges`, e a funcao fica. Apaga-la aqui
        era apagar um objecto de outra revisao — e a `0027`, ao descer, faria
        `DROP FUNCTION` sobre o que ja nao existe.
        """
        alembic_ok("downgrade", ANTERIOR)
        self.cursor.execute(
            "SELECT count(*) FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = 'assert_beneficiary'"
        )
        self.assertEqual(int(self.cursor.fetchone()[0]), 1)

    def test_depois_de_voltar_a_subir_tudo_volta(self) -> None:
        """O ciclo inteiro numa classe que controla a revisao.

        O que este caso acrescenta ao `TestCiclo` do *gate* 8 e a afirmacao sobre
        **estes** objectos, para que a falha diga qual deles nao voltou em vez de
        «a cadeia nao reaplica».
        """
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas_existentes(), [])
        alembic_ok("upgrade", "head")
        self.assertEqual(self.tabelas_existentes(), sorted(TABELAS))
        self.assertEqual(self.vistas_existentes(), sorted(VISTAS))
        self.assertEqual(self.funcoes_existentes(), sorted(FUNCOES))
        self.assertEqual(self.indices_existentes(), sorted(INDICES))
        self.assertEqual(
            self.politicas("payment_accounts"), ["pay_hooks_token", "tenant_iso"]
        )

    def test_o_downgrade_nao_toca_na_auditoria_nem_no_outbox(self) -> None:
        """O que fica: o rasto e os eventos de dominio ja publicados.

        Quem desce esta revisao perde o ledger — e isso esta dito por extenso no
        `downgrade`, porque a aparencia de imutabilidade e pior do que a
        imutabilidade medida: um `DROP TABLE` nao e um `DELETE`, e o
        `deny_mutation` nao dispara. O que **nao** se perde e o que vive noutras
        revisoes, e e a ordem certa das duas perdas.
        """
        alembic_ok("downgrade", ANTERIOR)
        for tabela in ("audit_log", "events_outbox", "payment_accounts"):
            with self.subTest(tabela=tabela):
                self.cursor.execute(
                    "SELECT count(*) FROM pg_tables "
                    " WHERE schemaname = 'platform' AND tablename = %s",
                    (tabela,),
                )
                self.assertEqual(int(self.cursor.fetchone()[0]), 1)
