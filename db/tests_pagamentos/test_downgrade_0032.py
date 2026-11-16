"""O `downgrade` da `0032` leva o que ela criou e **repoe o que ela substituiu**.

«Migracao reversivel» e caixa da Definition of Done, e o ciclo
`upgrade -> downgrade -> upgrade` ja corre no *gate* 8
(`tests/test_migracao.TestCiclo`). O que esse ciclo **nao** ve e a parte que faz
desta revisao um caso diferente de todas as anteriores:

    tabelas     as quatro de `docs/tecnica/04` §6.2-6.3. Caem, e com elas as
                politicas, os indices e a restricao de idempotencia
    funcoes     quatro `SECURITY DEFINER` e uma `STABLE`. Caem
    *trigger*   o `payment_events_g8_humano` e sobre uma tabela que esta revisao
                **nao** apaga — a `payment_events` e da `0029`. Deixa-lo
                pendurado nao impede o `upgrade` seguinte; impede o `downgrade`
                da `0029`, que corre `DROP TABLE` sem `CASCADE`. E a mesma
                classe da `pay_hooks_token` do `TestDowngradeDa0029`: a revisao
                que fica estragada e a **anterior**
    `next_state` **nao se apaga: repoe-se.** Esta revisao altera-a por
                `CREATE OR REPLACE`, e um `downgrade` que a largasse deixava a
                `0029` sem a funcao que ela criou — e, pior, deixava-a sem os
                `GRANT` que a `0029` lhe deu, porque um `DROP ... CASCADE`
                leva-os consigo

As duas ultimas sao o que o ciclo do *gate* 8 nao distingue: um objecto a mais ou
uma funcao com o corpo errado nao impedem o `upgrade`, a base volta a parecer
certa em `head`, e o que fica errado e invisivel ate alguem tentar descer.

**Afirma-se sobre os objectos e nao sobre a cadeia de revisoes**, para que a falha
diga **qual** deles nao voltou. Um ensaio que so comparasse o `alembic current`
ficava verde com a `next_state` a dar `reembolso_pendente` depois do `downgrade`.

Esta classe **nao** herda de `ComLedger`: controla ela propria a revisao em que a
base esta, como o `TestDowngradeDa0029` e o `TestDowngradeDa0028`. Repoe `head` no
fim, corra bem ou mal.
"""

from __future__ import annotations

import unittest

import bootstrap
import ligacao
from tests.base import alembic_ok, em_head, exigir_base_descartavel

#: As quatro tabelas que a revisao cria, e que o `downgrade` tem de levar.
TABELAS = (
    "fraud_signals",
    "manual_confirmations",
    "payment_confirmers",
    "refund_cases",
)

#: As cinco funcoes. Quatro `SECURITY DEFINER` (as de fase) e a `manual_janela`,
#: que le e nao escreve. A `exigir_fase_manual` entra tambem: e a do *trigger*.
FUNCOES = (
    "exigir_fase_manual",
    "manual_confirmar",
    "manual_declarar",
    "manual_expirar_confirmacao",
    "manual_janela",
    "manual_reverter",
)

#: Os indices proprios. Caem com as tabelas, e e isso que se afirma.
INDICES = (
    "fraud_signals_tenant_idx",
    "manual_confirmations_charge_idx",
    "manual_confirmations_janela_idx",
    "refund_cases_tenant_idx",
)

#: A restricao de idempotencia do criterio 9, afirmada **pelo nome** e nao pelo
#: indice que a serve: e uma restricao e nao um indice parcial, e as duas coisas
#: aparecem em catalogos diferentes.
RESTRICAO_DE_IDEMPOTENCIA = "manual_confirmations_msg_uq"

#: O *trigger* do G8, sobre a tabela da `0029`.
TRIGGER_DO_G8 = "payment_events_g8_humano"

#: A revisao anterior. O `downgrade` desta volta aqui.
ANTERIOR = "0031"


class TestDowngradeDa0032(unittest.TestCase):
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

    def tem_restricao_de_idempotencia(self) -> bool:
        self.cursor.execute(
            "SELECT count(*) FROM pg_constraint "
            " WHERE connamespace = 'platform'::regnamespace AND conname = %s "
            "   AND contype = 'u'",
            (RESTRICAO_DE_IDEMPOTENCIA,),
        )
        return int(self.cursor.fetchone()[0]) == 1

    def politicas(self, tabela: str) -> list[str]:
        self.cursor.execute(
            "SELECT policyname::text FROM pg_policies "
            " WHERE schemaname = 'platform' AND tablename = %s ORDER BY 1",
            (tabela,),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def triggers_do_ledger(self) -> list[tuple[str, str]]:
        self.cursor.execute(
            "SELECT t.tgname::text, t.tgenabled::text FROM pg_trigger t "
            "  JOIN pg_class c ON c.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'payment_events' "
            "   AND NOT t.tgisinternal ORDER BY t.tgname"
        )
        return [(str(a), str(b)) for a, b in self.cursor.fetchall()]

    def aresta_da_reversao(self):
        """O que a `next_state` devolve para a aresta que esta revisao acrescenta.

        E a leitura que distingue «a funcao existe» de «a funcao e a certa». Um
        `downgrade` que largasse a `next_state` dava erro aqui; um que a
        deixasse como `head` devolvia `reembolso_pendente`, e a cadeia de
        revisoes nao dizia nada.
        """
        self.cursor.execute(
            "SELECT platform.next_state("
            "  'paga', 'confirmacao_manual_revertida', 'rejeitada')"
        )
        return self.cursor.fetchone()[0]

    def grants_do_next_state(self) -> list[str]:
        """Quem tem `EXECUTE` na `next_state`, por nome de papel.

        O `downgrade` repoe a funcao por `CREATE OR REPLACE` **precisamente**
        para nao tocar nisto: um `DROP ... CASCADE` levava os `GRANT` da `0029`
        consigo, e a base ficava a correr com privilegios diferentes dos que ela
        escreveu — o que nao e um `downgrade`, e um estado novo.
        """
        self.cursor.execute(
            "SELECT DISTINCT a.grantee::text FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            "  CROSS JOIN aclexplode(p.proacl) AS a "
            " WHERE n.nspname = 'platform' AND p.proname = 'next_state' "
            "   AND a.privilege_type = 'EXECUTE' ORDER BY 1"
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    # ----------------------------------------------------------------- casos

    def test_em_head_esta_tudo(self) -> None:
        """O ponto de partida. **Sem isto, os casos seguintes nao dizem nada.**

        E a sonda positiva do ficheiro: se a leitura do catalogo estivesse
        errada — um nome de indice trocado, um `contype` errado —, os ensaios do
        `downgrade` ficavam verdes por lerem zero dos dois lados.
        """
        self.assertEqual(self.tabelas_existentes(), sorted(TABELAS))
        self.assertEqual(self.funcoes_existentes(), sorted(FUNCOES))
        self.assertEqual(self.indices_existentes(), sorted(INDICES))
        self.assertTrue(self.tem_restricao_de_idempotencia())
        for tabela in TABELAS:
            with self.subTest(tabela=tabela):
                self.assertEqual(self.politicas(tabela), ["tenant_iso"])
        self.assertIn(TRIGGER_DO_G8, [nome for nome, _ in self.triggers_do_ledger()])
        self.assertEqual(self.aresta_da_reversao(), "reembolso_pendente")

    def test_o_downgrade_leva_tabelas_funcoes_indices_e_a_restricao(self) -> None:
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.tabelas_existentes(), [])
        self.assertEqual(self.funcoes_existentes(), [])
        self.assertEqual(self.indices_existentes(), [])
        self.assertFalse(self.tem_restricao_de_idempotencia())

    def test_o_downgrade_leva_as_politicas_com_as_tabelas(self) -> None:
        """As quatro politicas caem **com** as tabelas, e nao por si.

        Afirma-se a parte porque o `ci/rls_exceptions.yaml` esta vazio e tem de
        continuar vazio: uma politica pendurada numa tabela que ja nao existe
        nao e possivel, mas uma tabela **sem** politica e — e e isso que o X-05
        do *gate* 6 recusa no `upgrade` seguinte.
        """
        alembic_ok("downgrade", ANTERIOR)
        for tabela in TABELAS:
            with self.subTest(tabela=tabela):
                self.assertEqual(self.politicas(tabela), [])

    def test_o_downgrade_tira_o_trigger_da_tabela_da_0029(self) -> None:
        """A parte que o ciclo do *gate* 8 e cego para ver.

        O `payment_events_g8_humano` e sobre a `payment_events`, que esta
        revisao **nao** apaga. Deixa-lo pendurado nao impede o `upgrade`
        seguinte — impede o `downgrade` da `0029`, que corre `DROP TABLE` sem
        `CASCADE` e encontra um *trigger* que nao criou. E a mesma classe da
        `pay_hooks_token` do `TestDowngradeDa0029`.
        """
        alembic_ok("downgrade", ANTERIOR)
        nomes = [nome for nome, _ in self.triggers_do_ledger()]
        self.assertNotIn(TRIGGER_DO_G8, nomes)
        self.assertEqual(
            nomes,
            ["payment_events_imutavel", "payment_events_sem_truncate"],
            "ficam os dois da 0029, e so eles",
        )

    def test_o_downgrade_repoe_a_next_state_e_nao_a_apaga(self) -> None:
        """A condicao do `CREATE OR REPLACE`, medida pelo **corpo** da funcao.

        Duas afirmacoes, e sao diferentes: a funcao **continua a existir** (um
        `DROP` deixava a `0029` sem a funcao que ela criou) e a aresta da
        reversao **desaparece** (um `downgrade` que a deixasse como `head`
        passava um ciclo inteiro sem ninguem dar por nada).
        """
        alembic_ok("downgrade", ANTERIOR)
        self.cursor.execute(
            "SELECT count(*) FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = 'next_state'"
        )
        self.assertEqual(
            int(self.cursor.fetchone()[0]),
            1,
            "a next_state e da 0029: o downgrade da 0032 repoe-a, nao a apaga",
        )
        self.assertIsNone(
            self.aresta_da_reversao(),
            "a aresta paga -> reembolso_pendente e desta revisao e tem de sair",
        )

    def test_e_os_grants_da_next_state_sobrevivem_ao_ciclo(self) -> None:
        """O que um `DROP ... CASCADE` teria levado consigo.

        Mede-se o conjunto de papeis com `EXECUTE` em `head`, desce-se, sobe-se,
        e exige-se o **mesmo** conjunto. Sem isto, um `downgrade` por `DROP`
        deixava a base a correr com privilegios que a `0029` nao escreveu, e
        nenhum ensaio da cadeia de revisoes o veria.
        """
        antes = self.grants_do_next_state()
        self.assertNotEqual(antes, [], "em head alguem tem EXECUTE na next_state")
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(
            self.grants_do_next_state(),
            antes,
            "o downgrade repoe a funcao por CREATE OR REPLACE e nao toca nos GRANT",
        )
        alembic_ok("upgrade", "head")
        self.assertEqual(self.grants_do_next_state(), antes)

    def test_depois_de_voltar_a_subir_tudo_volta(self) -> None:
        """O ciclo inteiro, e com a aresta de volta.

        **O `upgrade` corre aqui e nao no `tearDown`**, porque o que se afirma e
        o estado **depois** dele: esta classe acabou de reaplicar a revisao,
        pelo que o que o catalogo diz foi escrito pela **migracao** e por mais
        nada. E a correccao da classe de defeito que o `TestDowngradeDa0029`
        nomeia: um ensaio que leia o estado vivo no fim da suite pode estar a
        ler o que um vizinho repôs.
        """
        alembic_ok("downgrade", ANTERIOR)
        alembic_ok("upgrade", "head")
        self.assertEqual(self.tabelas_existentes(), sorted(TABELAS))
        self.assertEqual(self.funcoes_existentes(), sorted(FUNCOES))
        self.assertEqual(self.indices_existentes(), sorted(INDICES))
        self.assertTrue(self.tem_restricao_de_idempotencia())
        for tabela in TABELAS:
            with self.subTest(tabela=tabela):
                self.assertEqual(self.politicas(tabela), ["tenant_iso"])
        self.assertEqual(self.aresta_da_reversao(), "reembolso_pendente")
        self.assertEqual(
            [nome for nome, _ in self.triggers_do_ledger()],
            [
                # KAM-059: os dois do billing, que a cabeca tem.
                "payment_events_billing_papel",
                TRIGGER_DO_G8,
                "payment_events_g8_ops",
                "payment_events_imutavel",
                "payment_events_sem_truncate",
            ],
        )

    def test_e_o_trigger_do_g8_volta_com_enable_always(self) -> None:
        """O `ALWAYS` tem de ser escrito pela **migracao**, e nao por um vizinho.

        Um *trigger* recriado nasce na omissao (`O`), que o
        `session_replication_role = replica` salta. Esta classe reaplica a
        revisao, pelo que o `A` que se le aqui so pode vir do `ALTER TABLE ...
        ENABLE ALWAYS` dela — e e a mutacao «os triggers deixam de ser ALWAYS»
        que isto apanha.
        """
        alembic_ok("downgrade", ANTERIOR)
        alembic_ok("upgrade", "head")
        self.assertIn(
            (TRIGGER_DO_G8, "A"),
            self.triggers_do_ledger(),
            "'A' e ENABLE ALWAYS; 'O' seria a omissao, que o replica salta",
        )


if __name__ == "__main__":
    unittest.main()
