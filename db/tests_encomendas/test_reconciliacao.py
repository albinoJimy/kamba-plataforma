"""Criterio 7: as cinco regras de §10.3 do lado da base.

**A decisao das cinco regras e funcao pura e mede-se em TypeScript**
(`services/com/tests/orders.reconcile.test.ts`): recebe as duas fotografias e
devolve as divergencias, sem base de dados e sem Registo — que e o que a torna
mediavel, porque **nao ha Medusa em `infra/compose/`** (o KAM-042 registou-o ao
deixar o `RegistoAdmin` sem cliente HTTP, e o KAM-043 repetiu-o).

O que se mede aqui e o que e da base e so da base:

```text
a linha da divergencia              os cinco tipos, o `detalhe`, o fecho
a causa `reconciliacao`             toda a correccao a grava (§10.3, fim)
a reconciliacao nao escreve `paga`  o espelho nao se auto-autoriza
a metrica «abertas > 5 min»         a consulta que a le
```

## A reconciliacao nao pode levar uma encomenda a `paga`, e isso e a regra

O espelho e **a autoridade do ciclo de vida** (§10.1) e `paga` so e alcancavel
por evento autenticado do PAY (ADR-013, criterio 3). Um Registo a dizer «esta
encomenda esta paga» nao e um pagamento autenticado — e uma projeccao, e a
matriz de §10.1 diz que o estado de pagamento e do PAY e que «o COM so aplica».

Por isso a correccao da regra 1 completa o espelho ate onde o grafo a deixa com
causa `reconciliacao` e, se o Registo reclamar `paga`, deixa a divergencia
aberta. As duas metades medem-se abaixo.
"""

from __future__ import annotations

import json

import pg8000.dbapi
from tests.base import VIOLACAO_DE_CHECK, sqlstate
from tests_encomendas.base import PAGA_SEM_EVENTO, ComEncomendas
from tests_encomendas.consultas import (
    SQL_DIVERGENCIAS_ABERTAS,
    SQL_FECHAR_DIVERGENCIA,
)

#: Os **cinco** tipos, um por regra e pela ordem em que o §10.3 as escreve.
TIPOS = (
    "orfao_no_registo",
    "espelho_sem_encomenda",
    "divergencia_de_linhas",
    "reserva_sem_encomenda",
    "estado_divergente",
)



class TestAsCincoRegras(ComEncomendas):
    """Uma linha por regra, pela consulta do modulo."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.encomenda = self.criar_encomenda(self.tenant)
        self.conexao, self.cursor = self.ligar_app(self.tenant)

    def _abrir(self, tipo: str, encomenda: str | None, detalhe: dict) -> str:
        """Abre a divergencia. **O `INSERT` e desta suite e nao do modulo.**

        O `aplicar` do `reconcile.ts` abre por `repo.inserirNoTenant`, que
        constroi o `INSERT` com a coluna do filtro — nao ha constante para ler.
        Ver a nota do `consultas.py`.
        """
        self.cursor.execute(
            "INSERT INTO platform.order_reconciliation_issues "
            "       (tenant_id, order_id, tipo, detalhe) "
            "VALUES (%s, %s, %s, %s::jsonb) RETURNING id",
            (self.tenant, encomenda, tipo, json.dumps(detalhe)),
        )
        return str(self.cursor.fetchone()[0])

    def test_as_cinco_regras_tem_tipo_e_abrem_divergencia(self) -> None:
        for tipo in TIPOS:
            with self.subTest(tipo=tipo):
                # A regra 1 e a 4 podem nao ter encomenda no espelho: e a razao
                # de a coluna ser anulavel.
                encomenda = None if tipo in TIPOS[:1] else self.encomenda
                issue = self._abrir(tipo, encomenda, {"vence": "lines_snapshot"})
                self.assertTrue(issue)

        self.cursor.execute(
            SQL_DIVERGENCIAS_ABERTAS.sql,
            SQL_DIVERGENCIAS_ABERTAS.args(self.tenant),
        )
        abertas = [tuple(linha) for linha in self.cursor.fetchall()]
        self.assertEqual(
            sorted(linha[2] for linha in abertas),
            sorted(TIPOS),
            "as cinco regras, uma linha cada: e a metrica do bloco "
            "(«divergencias abertas > 5 min = 0») a ter o que ler",
        )

    def test_um_tipo_fora_das_cinco_e_recusado(self) -> None:
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self._abrir("inventado", self.encomenda, {})
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)
        self.conexao.rollback()

    def test_a_divergencia_fecha_se_e_so_uma_vez(self) -> None:
        issue = self._abrir("estado_divergente", self.encomenda, {})
        self.cursor.execute(
            SQL_FECHAR_DIVERGENCIA.sql,
            SQL_FECHAR_DIVERGENCIA.args(self.tenant, issue),
        )
        self.assertIsNotNone(self.cursor.fetchone(), "fecha a primeira vez")
        self.cursor.execute(
            SQL_FECHAR_DIVERGENCIA.sql,
            SQL_FECHAR_DIVERGENCIA.args(self.tenant, issue),
        )
        self.assertIsNone(
            self.cursor.fetchone(),
            "o predicado `estado = 'aberta'` torna o segundo fecho um no-op: "
            "sem ele, o `resolvida_at` era reescrito e a metrica dos 5 min "
            "media a ultima passagem em vez da primeira",
        )

    def test_uma_divergencia_resolvida_tem_instante_e_vice_versa(self) -> None:
        """Nos dois sentidos, que e o `..._resolvida_ck`."""
        issue = self._abrir("estado_divergente", self.encomenda, {})
        for estado, instante in (("resolvida", None), ("aberta", "now()")):
            with self.subTest(estado=estado):
                self.cursor.execute("SAVEPOINT meio")
                try:
                    self.cursor.execute(
                        "UPDATE platform.order_reconciliation_issues "
                        f"   SET estado = %s, resolvida_at = {instante or 'NULL'} "
                        " WHERE tenant_id = %s AND id = %s",
                        (estado, self.tenant, issue),
                    )
                    self.fail(f"`{estado}` com o instante trocado nao devia passar")
                except pg8000.dbapi.DatabaseError as erro:
                    self.assertEqual(sqlstate(erro), VIOLACAO_DE_CHECK)
                finally:
                    self.cursor.execute("ROLLBACK TO SAVEPOINT meio")

    def test_a_divergencia_de_a_nao_se_le_do_contexto_de_b(self) -> None:
        self._abrir("estado_divergente", self.encomenda, {})
        outro = self.criar_tenant()
        _, cursor_b = self.ligar_app(outro)
        cursor_b.execute(
            SQL_DIVERGENCIAS_ABERTAS.sql, SQL_DIVERGENCIAS_ABERTAS.args(outro)
        )
        self.assertEqual(list(cursor_b.fetchall()), [])


class TestACausaDaReconciliacao(ComEncomendas):
    """§10.3, ultima frase: «todas as correccoes gravadas com `reconciliacao`»."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()

    def test_uma_correccao_grava_causa_reconciliacao(self) -> None:
        encomenda = self.criar_encomenda(self.tenant)
        self.transitar(
            self.tenant,
            encomenda,
            "criada",
            "aguarda_pagamento",
            1,
            "reconciliacao",
            actor_kind="sistema",
        )
        self.assertEqual(
            self.consultar(
                "SELECT de, para, causa, actor_kind FROM platform.order_state_log "
                " WHERE order_id = %s",
                (encomenda,),
            ),
            [("criada", "aguarda_pagamento", "reconciliacao", "sistema")],
        )

    def test_a_reconciliacao_nao_leva_uma_encomenda_a_paga(self) -> None:
        """Ver a nota do modulo: o espelho nao se auto-autoriza.

        E a metade que importa das duas: sem esta, a regra 1 completava o
        espelho de uma encomenda que o Registo diz estar paga, e o estado
        `paga` passava a ser alcancavel por uma projeccao do Registo — contra o
        ADR-013 e contra a matriz de §10.1.
        """
        encomenda = self.criar_encomenda(self.tenant)
        versao = self.levar_a(self.tenant, encomenda, "aguarda_pagamento")
        self.assertEqual(
            self.tentar_transicao(
                self.tenant,
                encomenda,
                "aguarda_pagamento",
                "paga",
                versao,
                "reconciliacao",
                actor_kind="sistema",
                evento_id="reconciliacao-sem-evento-do-pay",
            ),
            PAGA_SEM_EVENTO,
        )
