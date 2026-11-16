"""Os pedidos que o recalculo da confianca le, contra encomendas reais (KAM-096).

O `SQL_PEDIDOS_ENTREGUES` e o `SQL_FACTOS_NEGATIVOS` de
`packages/core-ts/src/confianca/sql.ts`, executados tal como estao escritos e
como `kamba_batch`, sobre encomendas levadas a cada estado **pelo caminho do
grafo** (o `levar_a` desta suite). O que se prova:

* so as `entregue` do tenant, acima do valor minimo, entram — nem as de outro
  tenant (o lote tem `BYPASSRLS`, e o filtro e o `$1`), nem uma reembolsada;
* o comprador e o contacto **canonico**: dois contactos fundidos sao um
  comprador (a cadeia de `merged_into`, que o lote passa a ler pela revisao);
* uma entrada em `em_disputa` dentro da janela marca o pedido, mesmo que a
  disputa tenha sido recusada e a encomenda voltado a `entregue`;
* a disputa aceite contra o dono (`em_disputa -> reembolso_pendente`) e um
  facto negativo com data.

A regra de quem conta — a janela movel, a confirmacao do cliente, a
independencia do KAM-097 — e funcao pura e mede-se em
`packages/core-ts/tests/confianca.test.ts`.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from tests.base import ConsultaDoTypeScript
from tests_encomendas.base import ComEncomendas

SQL_TS = Path(__file__).resolve().parents[2] / "packages" / "core-ts" / "src" / "confianca" / "sql.ts"

#: 10 000 Kz, o valor minimo *proposta* do criterio 3.
MINIMO = 1_000_000


class TestPedidosEntregues(ComEncomendas):
    def entregue(self, tenant: str, contacto: str, total: int) -> str:
        encomenda = self.criar_encomenda(tenant, contacto, total=total)
        self.levar_a(tenant, encomenda, "entregue")
        return encomenda

    def ler(self, sql: str, *args) -> list[list]:
        q = ConsultaDoTypeScript(sql, SQL_TS)
        self.ensaio.execute("SET LOCAL ROLE kamba_batch")
        self.ensaio.execute(q.sql, q.args(*args))
        linhas = [list(x) for x in self.ensaio.fetchall()]
        self._ensaio.rollback()
        return linhas

    def test_entregues_do_tenant_com_o_comprador_canonico_e_a_disputa_na_janela(self) -> None:
        a = self.criar_tenant()
        b = self.criar_tenant()
        c1 = self.criar_contacto(a)
        c2 = self.criar_contacto(a)
        # c2 e o mesmo cliente que c1, fundido pela resolucao de identidade.
        self.semente.execute(
            "UPDATE platform.contacts SET merged_into = %s, merged_at = now() "
            "WHERE tenant_id = %s AND contact_id = %s",
            (c1, a, c2),
        )
        o1 = self.entregue(a, c1, 1_200_000)
        o2 = self.entregue(a, c2, 1_500_000)
        self.entregue(a, c1, MINIMO - 1)
        o4 = self.criar_encomenda(a, c1, total=1_300_000)
        versao = self.levar_a(a, o4, "em_disputa")
        self.transitar(a, o4, "em_disputa", "entregue", versao, "disputa_recusada")
        o5 = self.criar_encomenda(a, c1, total=1_400_000)
        versao = self.levar_a(a, o5, "em_disputa")
        self.transitar(a, o5, "em_disputa", "reembolso_pendente", versao, "disputa_aceite")
        self.entregue(b, self.criar_contacto(b), 9_000_000)

        desde = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)
        linhas = self.ler("SQL_PEDIDOS_ENTREGUES", a, desde, str(MINIMO), 14)
        vistos = {l[0]: (l[1], l[2], l[5], l[6]) for l in linhas}
        self.assertEqual(
            vistos,
            {
                o1: (c1, "1200000", True, False),
                o2: (c1, "1500000", True, False),
                o4: (c1, "1300000", True, True),
            },
        )

        disputa, sinal = self.ler("SQL_FACTOS_NEGATIVOS", a)[0]
        self.assertIsNotNone(disputa)
        self.assertIsNone(sinal)
        self.assertEqual(self.ler("SQL_FACTOS_NEGATIVOS", b)[0], [None, None])

    def test_uma_disputa_depois_da_janela_nao_marca_o_pedido(self) -> None:
        """A disputa conta **so** dentro dos 14 dias depois da entrega.

        A entrega recua-se 20 dias pelo administrador (o `entregue_at` nao tem
        *trigger* que o prenda), e a disputa entra agora: 20 > 14, logo `False`.
        A disputa recusada devolve a encomenda a `entregue` com um `entregue_at`
        novo, que se recua outra vez.
        """
        a = self.criar_tenant()
        c = self.criar_contacto(a)
        o = self.entregue(a, c, 1_200_000)
        recuar = (
            "UPDATE platform.orders_mirror SET entregue_at = now() - interval '20 days' "
            "WHERE tenant_id = %s AND id = %s"
        )
        self.semente.execute(recuar, (a, o))
        self.semente.execute("SELECT version FROM platform.orders_mirror WHERE id = %s", (o,))
        versao = int(self.semente.fetchone()[0])
        versao = self.transitar(a, o, "entregue", "em_disputa", versao, "reclamacao")
        self.transitar(a, o, "em_disputa", "entregue", versao, "disputa_recusada")
        self.semente.execute(recuar, (a, o))
        desde = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)
        linhas = self.ler("SQL_PEDIDOS_ENTREGUES", a, desde, str(MINIMO), 14)
        self.assertEqual([(l[0], l[6]) for l in linhas], [(o, False)])
        # E com uma janela de 30 dias a mesma disputa ja cai dentro dela.
        linhas = self.ler("SQL_PEDIDOS_ENTREGUES", a, desde, str(MINIMO), 30)
        self.assertEqual([(l[0], l[6]) for l in linhas], [(o, True)])

    def test_um_pedido_entregue_antes_do_desde_nao_e_lido(self) -> None:
        a = self.criar_tenant()
        self.entregue(a, self.criar_contacto(a), 1_200_000)
        depois = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=1)
        self.assertEqual(self.ler("SQL_PEDIDOS_ENTREGUES", a, depois, str(MINIMO), 14), [])
