"""A revisao 0038 contra a base: os direitos do titular (KAM-070).

As listas fechadas do *gate* 8 — o inventario, as restricoes por nome, os
indices parciais, as FK, a matriz de privilegios — afirmam que a revisao
**declarou** o que devia. Esta bateria mede coisa diferente: que o declarado
**morde**. Sao duas perguntas, e a segunda nao sai da primeira:

1. **O pedido aberto e um por tipo e titular, e o indice e parcial.** O critero 8
   pede «um pedido em curso nao duplica *jobs*», e a forma disso e um `23505` no
   segundo pedido **aberto** do mesmo tipo — e **nenhum** erro no segundo pedido
   depois de o primeiro fechar. As duas metades precisam das duas: um indice
   **nao** parcial passava a primeira e reprovava a segunda, e nenhuma lista
   fechada distingue os dois casos, porque as duas formas aparecem na lista de
   indices parciais como um booleano que alguem escreveu.

2. **O `prazo_interno_at > recebido_at` e a unica coisa que a base garante sobre
   o prazo**, e por isso tem de ser verdade. A igualdade dos 30 dias vive no
   modulo (`timestamptz + interval` e `STABLE`, nao `IMMUTABLE` — a revisao
   explica), pelo que esta e a metade que o PostgreSQL defende.

3. **A unicidade `(tenant_id, dsar_id, escopo)` e o que faz o criterio 3
   significar algo.** Seis entregas do **mesmo** escopo tem de dar `23505` na
   segunda, e nao seis linhas: com seis linhas, um `count(*) = 6` fechava um
   pedido com cinco escopos por aplicar — titulares que a plataforma diz ter
   apagado e nao apagou.

4. **O `erasure_ledger` e *append-only* por privilegio, e isso e medivel.** Nao
   ha `deny_mutation` por baixo: a ausencia de `DELETE` e a **unica** coisa que o
   faz ser o que e. Logo mede-se com o papel que o escreve a tentar apaga-lo —
   `42501` —, e nao pela matriz, que ja afirma o `GRANT` e nao o efeito dele.

5. **O dominio de `audit_log.action` aceita as duas accoes novas**, e o
   `downgrade` recusa-se com elas escritas. E a parte da revisao que mexe numa
   tabela de **outra**, e a unica onde um `NO FORCE` esquecido nao da erro
   nenhum: a validacao do `ADD CONSTRAINT` corre como dono da tabela, e com
   `FORCE` o dono ve **zero linhas** e valida o vazio. Mede-se escrevendo a
   linha e descendo.

## O que esta bateria nao cobre, e fica dito

A politica `tenant_iso` das duas tabelas e medida pelo X-05 do *gate* 6, pela
receita de sementes da `dsar_requests` — e a `erasure_ledger` fica **fora** dessa
bateria, com razao escrita no `db/tests_isolamento/sementes.py`: e *append-only*,
e uma receita fazia daquela bateria o unico sitio do repositorio onde uma linha
do *ledger* e apagada. O caso de leitura cruzada dela nao esta medido em lado
nenhum, e isso esta na caixa 3 da DoD do bloco com credor.
"""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
_NUCLEO = str(_RAIZ / "libs" / "py-core" / "src")
if _NUCLEO not in sys.path:
    sys.path.insert(0, _NUCLEO)

from tests import factories
from tests.base import (
    TABELAS,
    TABELAS_ATE_0037,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

PEDIDOS = "platform.dsar_requests"
LEDGER = "platform.erasure_ledger"

#: `insufficient_privilege`. E o SQLSTATE que prova «append-only por
#: privilegio»: sem `GRANT DELETE`, a instrucao nem chega a olhar para a linha.
PRIVILEGIO_INSUFICIENTE = "42501"

#: Os seis escopos do criterio 3, pela ordem em que ele os escreve.
ESCOPOS = ("cofre", "agr", "sto", "dat", "idx", "chatwoot")


def _criar_pedido(cursor, tenant, contacto, tipo="eliminacao", estado="recebido"):
    """Insere um pedido e devolve o `dsar_id`.

    O `prazo_interno_at` entra **calculado aqui** e nao por `DEFAULT`: a base nao
    tem a aritmetica, de proposito, e um auxiliar que a escondesse fazia esta
    bateria medir um `DEFAULT` que a revisao nao tem.
    """
    cursor.execute(
        f"""
        INSERT INTO {PEDIDOS}
               (tenant_id, contact_id, tipo, estado, papel_kamba,
                recebido_at, prazo_dias, prazo_interno_at)
        VALUES (%s, %s, %s, %s, 'subcontratada',
                now(), 30, now() + interval '30 days')
        RETURNING dsar_id
        """,
        (tenant, contacto, tipo, estado),
    )
    return str(cursor.fetchone()[0])


class TestOPedidoDoTitular(ComBase):
    """Criterios 1 e 8: a linha do pedido e a unicidade do pedido aberto."""

    def contexto(self):
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        tenant = factories.tenant(cursor)
        factories.contexto(cursor, tenant)
        contacto = factories.contacto(cursor, tenant)
        return cursor, tenant, contacto

    def test_um_pedido_nasce_recebido_com_o_prazo_na_linha(self) -> None:
        cursor, tenant, contacto = self.contexto()
        dsar_id = _criar_pedido(cursor, tenant, contacto)
        cursor.execute(
            f"SELECT estado, prazo_dias, prazo_interno_at - recebido_at "
            f"FROM {PEDIDOS} WHERE dsar_id = %s",
            (dsar_id,),
        )
        estado, prazo_dias, intervalo = cursor.fetchone()
        self.assertEqual(estado, "recebido")
        self.assertEqual(prazo_dias, 30)
        self.assertEqual(intervalo, timedelta(days=30))

    def test_o_segundo_pedido_aberto_do_mesmo_tipo_colide(self) -> None:
        """Criterio 8: «um pedido em curso nao duplica *jobs*»."""
        cursor, tenant, contacto = self.contexto()
        _criar_pedido(cursor, tenant, contacto)
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE,
            cursor,
            f"""
            INSERT INTO {PEDIDOS}
                   (tenant_id, contact_id, tipo, estado, papel_kamba,
                    recebido_at, prazo_dias, prazo_interno_at)
            VALUES (%s, %s, 'eliminacao', 'recebido', 'subcontratada',
                    now(), 30, now() + interval '30 days')
            """,
            (tenant, contacto),
        )

    def test_um_pedido_de_outro_tipo_nao_colide(self) -> None:
        """A chave e por tipo: opor-se nao impede pedir a exportacao."""
        cursor, tenant, contacto = self.contexto()
        _criar_pedido(cursor, tenant, contacto, tipo="eliminacao")
        self.assertIsNotNone(
            _criar_pedido(cursor, tenant, contacto, tipo="exportacao")
        )

    def test_depois_de_concluir_o_mesmo_tipo_pede_se_outra_vez(self) -> None:
        """**O caso que distingue um indice parcial de uma unicidade.**

        Dois pedidos do mesmo tipo pelo mesmo titular sao legitimos ao longo do
        tempo — um apagamento em Marco e outro em Setembro, depois de o BSUID
        voltar a escrever. Um indice **nao** parcial passava o ensaio de cima e
        reprovava este, e **nenhuma lista fechada do *gate* 8 distingue os
        dois**: as duas formas aparecem na lista de indices parciais como um
        booleano que alguem escreveu a mao.
        """
        cursor, tenant, contacto = self.contexto()
        primeiro = _criar_pedido(cursor, tenant, contacto)
        cursor.execute(
            f"UPDATE {PEDIDOS} SET estado = 'concluido', concluido_at = now() "
            f"WHERE dsar_id = %s",
            (primeiro,),
        )
        self.assertIsNotNone(_criar_pedido(cursor, tenant, contacto))

    def test_o_prazo_nao_pode_ser_anterior_a_recepcao(self) -> None:
        cursor, tenant, contacto = self.contexto()
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            f"""
            INSERT INTO {PEDIDOS}
                   (tenant_id, contact_id, tipo, estado, papel_kamba,
                    recebido_at, prazo_dias, prazo_interno_at)
            VALUES (%s, %s, 'exportacao', 'recebido', 'subcontratada',
                    now(), 30, now() - interval '1 day')
            """,
            (tenant, contacto),
        )

    def test_concluido_sem_data_e_data_sem_concluido_falham_os_dois(self) -> None:
        """O `CHECK` e uma equivalencia, e as duas direccoes tem de morder."""
        cursor, tenant, contacto = self.contexto()
        dsar_id = _criar_pedido(cursor, tenant, contacto)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            f"UPDATE {PEDIDOS} SET estado = 'concluido' WHERE dsar_id = %s",
            (dsar_id,),
        )
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            f"UPDATE {PEDIDOS} SET concluido_at = now() WHERE dsar_id = %s",
            (dsar_id,),
        )

    def test_o_papel_da_kamba_nao_tem_omissao(self) -> None:
        """A D9 esta aberta: a coluna e `NOT NULL` **sem** `DEFAULT`.

        Um `DEFAULT` fazia a decisao aberta parecer decidida a quem le o
        esquema, e o `23502` e a prova de que nao ha nenhum.
        """
        cursor, tenant, contacto = self.contexto()
        self.assertErroSql(
            "23502",
            cursor,
            f"""
            INSERT INTO {PEDIDOS}
                   (tenant_id, contact_id, tipo, estado,
                    recebido_at, prazo_dias, prazo_interno_at)
            VALUES (%s, %s, 'exportacao', 'recebido',
                    now(), 30, now() + interval '30 days')
            """,
            (tenant, contacto),
        )


class TestOLedgerDeApagamento(ComBase):
    """Criterios 3 e 6: a unicidade por escopo e o `append-only`."""

    def contexto(self):
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        tenant = factories.tenant(cursor)
        factories.contexto(cursor, tenant)
        contacto = factories.contacto(cursor, tenant)
        dsar_id = _criar_pedido(cursor, tenant, contacto)
        return cursor, tenant, contacto, dsar_id

    def aplicar(self, cursor, tenant, contacto, dsar_id, escopo):
        cursor.execute(
            f"INSERT INTO {LEDGER} (tenant_id, dsar_id, contact_id, escopo) "
            f"VALUES (%s, %s, %s, %s) RETURNING erasure_id",
            (tenant, dsar_id, contacto, escopo),
        )
        return str(cursor.fetchone()[0])

    def test_os_seis_escopos_escrevem_seis_linhas(self) -> None:
        cursor, tenant, contacto, dsar_id = self.contexto()
        for escopo in ESCOPOS:
            self.aplicar(cursor, tenant, contacto, dsar_id, escopo)
        cursor.execute(
            f"SELECT count(*) FROM {LEDGER} WHERE dsar_id = %s", (dsar_id,)
        )
        self.assertEqual(cursor.fetchone()[0], len(ESCOPOS))

    def test_o_mesmo_escopo_duas_vezes_colide(self) -> None:
        """**O ensaio que impede um pedido de fechar sem ter apagado.**

        Sem esta unicidade, seis entregas do mesmo componente escreviam seis
        linhas e um `count(*) = 6` fechava o pedido com cinco escopos por
        aplicar — titulares que a plataforma diz ter apagado e nao apagou.
        """
        cursor, tenant, contacto, dsar_id = self.contexto()
        self.aplicar(cursor, tenant, contacto, dsar_id, "cofre")
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE,
            cursor,
            f"INSERT INTO {LEDGER} (tenant_id, dsar_id, contact_id, escopo) "
            f"VALUES (%s, %s, %s, 'cofre')",
            (tenant, dsar_id, contacto),
        )

    def test_um_escopo_fora_do_dominio_e_recusado(self) -> None:
        cursor, tenant, contacto, dsar_id = self.contexto()
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            f"INSERT INTO {LEDGER} (tenant_id, dsar_id, contact_id, escopo) "
            f"VALUES (%s, %s, %s, 'medusa')",
            (tenant, dsar_id, contacto),
        )

    def test_uma_linha_sem_pedido_e_recusada(self) -> None:
        """A FK e composta com o `tenant_id`: um *ledger* de A nao aponta para B."""
        cursor, tenant, contacto, _ = self.contexto()
        self.assertErroSql(
            "23503",
            cursor,
            f"INSERT INTO {LEDGER} (tenant_id, dsar_id, contact_id, escopo) "
            f"VALUES (%s, %s, %s, 'cofre')",
            (tenant, str(uuid.uuid4()), contacto),
        )

    def test_quem_escreve_no_ledger_nao_o_consegue_apagar(self) -> None:
        """«*Append-only* por privilegio», medido pelo efeito e nao pela matriz.

        Nao ha `deny_mutation` por baixo desta tabela: a ausencia de
        `GRANT DELETE` e a **unica** coisa que a faz ser o que e. A matriz de
        privilegios afirma o `GRANT`; isto afirma que ele morde.
        """
        # `"app"` e nao `"kamba_app"`: o `db/ligacao.py` indexa o `PAPEIS` pela
        # **identidade** e nao pelo nome do papel no PostgreSQL, e passar o nome
        # do papel levanta `ValueError: identidade desconhecida` — um erro que se
        # le como defeito do ensaio e nao da base. Custou uma corrida de Docker.
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, cursor, f"DELETE FROM {LEDGER}"
        )

    def test_quem_escreve_no_ledger_nao_o_consegue_emendar(self) -> None:
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            cursor,
            f"UPDATE {LEDGER} SET aplicado_at = now()",
        )


class TestODominioDaAccaoDeAuditoria(ComBase):
    """A parte da revisao que mexe numa tabela de **outra** (a `0006`)."""

    def test_as_duas_accoes_novas_entram_no_audit_log(self) -> None:
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        tenant = factories.tenant(cursor)
        factories.contexto(cursor, tenant)
        for accao in ("privacy.dsar_recusado", "privacy.dsar_rectificado"):
            with self.subTest(accao=accao):
                cursor.execute(
                    "SELECT platform.audit_append("
                    "  %s, 'contact', 'c-1', %s, 'dsar', 'c-1', NULL, sha256('x'::bytea)"
                    ")",
                    (tenant, accao),
                )

    def test_uma_accao_de_dsar_inventada_continua_recusada(self) -> None:
        """O dominio cresceu de sete para nove, e continua **fechado**."""
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        tenant = factories.tenant(cursor)
        factories.contexto(cursor, tenant)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            "SELECT platform.audit_append("
            "  %s, 'contact', 'c-1', 'privacy.dsar_exportado', 'dsar', 'c-1',"
            "  NULL, sha256('x'::bytea)"
            ")",
            (tenant,),
        )


class TestDowngradeDa0038(ComBase):
    """O `downgrade` leva a base para a `0036` e recusa-se quando nao pode.

    Herda do `ComBase` para garantir papeis e `head`, e **repoe o `head` no
    `tearDown`**: uma suite que deixasse a base na `0036` fazia falhar tudo o
    que corresse depois dela, e a ordem dos modulos do `unittest` e alfabetica
    e nao uma garantia.
    """

    def tearDown(self) -> None:
        super().tearDown()
        if not em_head():
            alembic_ok("upgrade", "head")

    def test_desce_e_as_duas_tabelas_desaparecem(self) -> None:
        exigir_base_descartavel()
        alembic_ok("downgrade", "0036")
        presentes = {
            nome
            for (nome,) in self.consultar(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'platform'"
            )
        }
        self.assertEqual(presentes, set(TABELAS_ATE_0037))
        self.assertNotIn("dsar_requests", presentes)
        self.assertNotIn("erasure_ledger", presentes)

    def test_sobe_outra_vez_e_volta_a_cabeca(self) -> None:
        exigir_base_descartavel()
        alembic_ok("downgrade", "0036")
        alembic_ok("upgrade", "head")
        presentes = {
            nome
            for (nome,) in self.consultar(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'platform'"
            )
        }
        self.assertEqual(presentes, set(TABELAS))

    def test_o_dominio_da_accao_volta_as_sete(self) -> None:
        exigir_base_descartavel()
        alembic_ok("downgrade", "0036")
        definicao = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'audit_log_action'"
        )[0][0]
        self.assertNotIn("privacy.dsar_recusado", definicao)
        self.assertIn("audit.read", definicao)

    def test_com_uma_linha_de_dsar_escrita_o_downgrade_recusa_se(self) -> None:
        """**O ensaio onde um `NO FORCE` esquecido nao dava erro nenhum.**

        O `audit_log` tem `FORCE ROW LEVEL SECURITY`, e a contagem que decide
        esta recusa corre como dono da tabela: **com** `FORCE`, o dono ve zero
        linhas, a contagem sai zero, o passo segue e o `ADD CONSTRAINT` valida
        tambem zero — duas medicoes vacuas a concordar, e uma linha
        `privacy.dsar_*` ficava debaixo de um `CHECK` que diz que ela nao
        existe. E a armadilha que a `0003` mediu contra o PostgreSQL 18.6.

        ## Porque e que este ensaio desliga um *trigger*, e porque e que a
        ## alternativa era pior

        A linha tem de ser **confirmada** — o `alembic` corre noutro processo e
        nao veria uma escrita por confirmar — e o `audit_log` e append-only de
        **duas** formas: nenhum papel leva `DELETE` **e** o *trigger*
        `audit_log_sem_update_nem_delete` recusa `UPDATE` e `DELETE` ao dono
        tambem. Logo a linha fica na base para sempre, e **a primeira versao
        deste ensaio envenenava os outros tres**: medido contra PostgreSQL
        18.6, 14 dos 19 ensaios passaram e os cinco que falharam eram todos
        esta causa — tres `downgrade` que ja nao conseguiam descer, mais dois
        `tearDown`.

        As alternativas que nao servem, e porque: **ordenar os ensaios** para
        este ser o ultimo reprova o alvo `ordem-dos-ensaios` do *gate* 4, que
        corre as suites pela ordem inversa de propósito (KAM-173); e **tirar o
        ensaio da suite** deixava a unica medicao da recusa a ser uma corrida a
        mao, fora do CI.

        Por isso o passo desliga o *trigger*, apaga a linha e a cabeca da
        cadeia desse tenant, e volta a ligar — numa base **descartavel**, que o
        `exigir_base_descartavel` confirma. O que isto nao e: uma via para
        apagar auditoria em producao. Nenhum papel da aplicacao consegue
        `ALTER TABLE`, e a prova disso e o
        `test_kamba_app_nao_altera_nem_apaga_tabelas` do `test_catalogo.py`.
        """
        exigir_base_descartavel()
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        tenant = factories.tenant(cursor)
        factories.contexto(cursor, tenant)
        cursor.execute(
            "SELECT platform.audit_append("
            "  %s, 'contact', 'c-1', 'privacy.dsar_recusado', 'dsar', 'c-1',"
            "  NULL, sha256('x'::bytea)"
            ")",
            (tenant,),
        )
        conexao.commit()
        try:
            resultado = alembic("downgrade", "0036")
            self.assertNotEqual(
                resultado.returncode,
                0,
                "o downgrade tem de recusar: o audit_log e append-only e nao ha "
                "forma de retirar a linha",
            )
            self.assertIn("append-only", resultado.stderr + resultado.stdout)
        finally:
            self._limpar_a_linha_de_auditoria(tenant)

    def _limpar_a_linha_de_auditoria(self, tenant: str) -> None:
        """Apaga a linha e a cabeca da cadeia, com o *trigger* desligado.

        Num `finally`, e confirmado: se o ensaio falhar a meio, a linha sai de
        qualquer maneira — senao a falha de um ensaio fazia falhar os tres
        seguintes, que e precisamente o defeito que este metodo corrige.
        """
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        factories.contexto(cursor, tenant)
        cursor.execute(
            "ALTER TABLE platform.audit_log "
            "DISABLE TRIGGER audit_log_sem_update_nem_delete"
        )
        try:
            cursor.execute(
                "DELETE FROM platform.audit_log WHERE tenant_id = %s", (tenant,)
            )
            cursor.execute(
                "DELETE FROM platform.audit_heads WHERE tenant_id = %s", (tenant,)
            )
        finally:
            cursor.execute(
                "ALTER TABLE platform.audit_log "
                "ENABLE TRIGGER audit_log_sem_update_nem_delete"
            )
        conexao.commit()
