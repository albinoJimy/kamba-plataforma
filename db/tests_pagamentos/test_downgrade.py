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

import os
import tempfile
import unittest
import uuid
from pathlib import Path

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
    "payment_charge_nasce_iniciada",
    "payment_event_row_hash",
    "payment_instante",
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

#: A variavel que autoriza a perda de encomendas no `downgrade` da `0030`.
#: Ver o `_descer`.
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0030_COPIA"


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
            os.environ.pop(VARIAVEL_DA_COPIA, None)
            # Cada processo do Alembic custa segundos: so quando a base nao
            # esta em `head`.
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    def _descer(self) -> None:
        """`downgrade` ate a `0028`, com a copia logica da `0030` autorizada.

        **A autorizacao e nova, e a razao e a revisao `0035`** (KAM-055). Esta
        classe desce de `head` ate a `0028`, pelo que atravessa o `downgrade` da
        `0030` — e esse recusa-se quando a `orders_mirror` tem linhas, a menos
        que o `KAMBA_DOWNGRADE_0030_COPIA` aponte para um ficheiro novo onde a
        copia logica fique.

        Antes da `0035` a tabela estava **vazia** nesta suite e a recusa nunca
        disparava; agora o `criar_cobranca` semeia uma encomenda por cobranca
        (a FK composta exige-a) e as que o ledger referencia **ficam**, porque o
        `payment_events` nao se apaga. Medido: 145 encomendas, e o `downgrade`
        a recusar com a mensagem que a propria `0030` escreveu.
        """
        os.environ[VARIAVEL_DA_COPIA] = str(
            Path(tempfile.gettempdir()) / f"kamba-0030-{uuid.uuid4().hex}.jsonl"
        )
        try:
            alembic_ok("downgrade", ANTERIOR)
        finally:
            os.environ.pop(VARIAVEL_DA_COPIA, None)

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

    def triggers_sempre_activos(self) -> list[tuple[str, str]]:
        """Os *triggers* da `payment_events` e o seu `tgenabled`.

        `A` e `ENABLE ALWAYS`; `O` e a omissao, que o
        `session_replication_role = replica` salta.
        """
        self.cursor.execute(
            "SELECT t.tgname::text, t.tgenabled::text FROM pg_trigger t "
            "  JOIN pg_class c ON c.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'payment_events' "
            "   AND NOT t.tgisinternal ORDER BY t.tgname"
        )
        return [(str(a), str(b)) for a, b in self.cursor.fetchall()]

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
        self._descer()
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
        self._descer()
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
        self._descer()
        self.assertTrue(self.tem_papel())

    def test_o_downgrade_nao_apaga_a_funcao_da_0027(self) -> None:
        """A `assert_beneficiary` e da `0027`; o *trigger* que a liga e desta.

        O *trigger* cai com a `payment_charges`, e a funcao fica. Apaga-la aqui
        era apagar um objecto de outra revisao — e a `0027`, ao descer, faria
        `DROP FUNCTION` sobre o que ja nao existe.
        """
        self._descer()
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
        self._descer()
        self.assertEqual(self.tabelas_existentes(), [])
        alembic_ok("upgrade", "head")
        self.assertEqual(self.tabelas_existentes(), sorted(TABELAS))
        self.assertEqual(self.vistas_existentes(), sorted(VISTAS))
        self.assertEqual(self.funcoes_existentes(), sorted(FUNCOES))
        self.assertEqual(self.indices_existentes(), sorted(INDICES))
        self.assertEqual(
            self.politicas("payment_accounts"), ["pay_hooks_token", "tenant_iso"]
        )
        # **O `ENABLE ALWAYS` medido onde nenhum vizinho lhe chega.**
        #
        # Esta classe acabou de reaplicar a revisao, pelo que o que o catalogo
        # diz aqui foi escrito pela **migracao** e por mais nada. E a correccao
        # de um ensaio que passava pela razao errada: o `TestTriggersSaoAlways`
        # le o estado vivo no fim da suite, e enquanto o
        # `TestCadeiaEscritaPelaPorta` repunha o *trigger* com `ENABLE ALWAYS`
        # fixo, ele lia um `A` que tinha sido escrito por esse vizinho. A
        # mutacao «os triggers do ledger deixam de ser ALWAYS» **sobreviveu** a
        # suite inteira por causa disso.
        self.assertEqual(
            self.triggers_sempre_activos(),
            [
            # O `payment_events_g8_humano` e da revisao `0032` (KAM-054) e
            # entra nesta lista por ser o terceiro *trigger* da tabela: e o
            # G8 do §5 — um `pagamento_confirmado` com
            # `authn_method='manual'` exige uma fase de
            # `manual_confirmations` com `valor_bate` e o mesmo actor. Tem
            # `ENABLE ALWAYS` pela mesma razao que os outros dois, e aqui
            # ela e **mais** forte: sem o `ALWAYS`, um superutilizador em
            # `session_replication_role = replica` confirmava um pagamento
            # por via humana sem fase nenhuma.
                ("payment_events_g8_humano", "A"),
                ("payment_events_imutavel", "A"),
                ("payment_events_sem_truncate", "A"),
            ],
            "a revisao tem de criar os triggers com ENABLE ALWAYS: sem "
            "isso, um SET session_replication_role = replica salta-os e a "
            "imutabilidade do ledger passa a depender de ninguem o escrever",
        )

    def test_em_head_os_triggers_do_ledger_sao_always(self) -> None:
        """O mesmo no ponto de partida, antes de qualquer `downgrade`.

        Os dois juntos distinguem «a revisao escreve o `ALWAYS`» de «o `ALWAYS`
        sobrevive ao ciclo», que sao afirmacoes diferentes: um `downgrade` que
        deixasse o *trigger* pendurado e um `upgrade` que o recriasse sem o
        `ALTER` davam o mesmo resultado no ensaio de cima.
        """
        self.assertEqual(
            self.triggers_sempre_activos(),
            [
                ("payment_events_g8_humano", "A"),
                ("payment_events_imutavel", "A"),
                ("payment_events_sem_truncate", "A"),
            ],
        )

    def test_o_downgrade_nao_toca_na_auditoria_nem_no_outbox(self) -> None:
        """O que fica: o rasto e os eventos de dominio ja publicados.

        Quem desce esta revisao perde o ledger — e isso esta dito por extenso no
        `downgrade`, porque a aparencia de imutabilidade e pior do que a
        imutabilidade medida: um `DROP TABLE` nao e um `DELETE`, e o
        `deny_mutation` nao dispara. O que **nao** se perde e o que vive noutras
        revisoes, e e a ordem certa das duas perdas.
        """
        self._descer()
        for tabela in ("audit_log", "events_outbox", "payment_accounts"):
            with self.subTest(tabela=tabela):
                self.cursor.execute(
                    "SELECT count(*) FROM pg_tables "
                    " WHERE schemaname = 'platform' AND tablename = %s",
                    (tabela,),
                )
                self.assertEqual(int(self.cursor.fetchone()[0]), 1)
