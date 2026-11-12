"""O CAS do painel do dono contra um PostgreSQL real (KAM-099).

A bateria do COM (`services/com/tests/produtos.painel.test.ts`) mede o modulo
sobre uma base de ensaio que le o predicado do texto. O que ela **nao** pode medir
e o motor: que a versao volta com microssegundos e casa o `$5::timestamptz` com
outro `TimeZone` na sessao, que duas escritas seguidas nunca deixam a mesma versao
(o `clock_timestamp()` e nao o `now()`), e que o `$6` decide o
`preco_atualizado_at` e o `preco_valido_ate`. Foi o achado da revisao adversarial:
quatro mutacoes do SQL sobreviviam com a bateria do COM verde.
"""

from __future__ import annotations

import datetime
import re

from tests_produtos import consultas
from tests_produtos.base import PRECO, SKU_PARTILHADO, ComOfertas

#: A forma da versao: o `to_char` das duas leituras do painel.
FORMA_DA_VERSAO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


class TestOCasDoPainel(ComOfertas):
    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.criar_oferta(
            self.tenant,
            preco_valido_ate=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        )
        self.cursor = self.cursor_app(self.tenant)
        self.addCleanup(self.cursor.connection.rollback)

    def versao(self, cursor=None) -> str:
        c = cursor or self.cursor
        q = consultas.SQL_OFERTA_DO_PAINEL
        c.execute(q.sql, q.args(self.tenant, SKU_PARTILHADO))
        linha = c.fetchone()
        self.assertIsNotNone(linha)
        colunas = [d[0] for d in c.description]
        return linha[colunas.index("versao")]

    def alterar(self, versao: str, mudou: bool, preco: int = PRECO + 100, cursor=None) -> int:
        c = cursor or self.cursor
        q = consultas.SQL_ALTERAR_OFERTA
        c.execute(q.sql, q.args(self.tenant, SKU_PARTILHADO, "fixo", preco, versao, mudou))
        return len(c.fetchall())

    def coluna(self, nome: str):
        self.cursor.execute(
            f"SELECT {nome} FROM platform.offer_terms WHERE tenant_id = %s AND sku = %s",
            (self.tenant, SKU_PARTILHADO),
        )
        return self.cursor.fetchone()[0]

    def test_a_versao_volta_com_microssegundos_e_casa_o_predicado_noutro_fuso(self) -> None:
        # Um `TimeZone` que nao e UTC: sem o `AT TIME ZONE 'UTC'` do `to_char`, a
        # versao saia em hora de Luanda com um `Z` falso e nunca mais casava.
        self.cursor.execute("SET LOCAL TimeZone = 'Africa/Luanda'")
        v = self.versao()
        self.assertRegex(v, FORMA_DA_VERSAO)
        self.assertEqual(self.alterar(v, True), 1)
        # A mesma versao, outra vez: ja nao e a da linha.
        self.assertEqual(self.alterar(v, True), 0)

    def test_duas_escritas_seguidas_na_mesma_transaccao_dao_versoes_diferentes(self) -> None:
        # Com `now()` as tres versoes eram iguais: e o instante de inicio da
        # transaccao. E a escrita perdida que o CAS deixava passar.
        stock = consultas.SQL_AJUSTAR_STOCK
        v0 = self.versao()
        self.cursor.execute(stock.sql, stock.args(self.tenant, SKU_PARTILHADO, "indicativo"))
        v1 = self.versao()
        self.assertEqual(self.alterar(v1, True), 1)
        v2 = self.versao()
        self.assertEqual(len({v0, v1, v2}), 3, (v0, v1, v2))
        # E a versao do ajuste de stock ja nao serve.
        self.assertEqual(self.alterar(v1, True), 0)

    def test_sem_mudanca_de_preco_o_instante_e_a_validade_ficam(self) -> None:
        antes_instante = self.coluna("preco_atualizado_at")
        antes_validade = self.coluna("preco_valido_ate")
        self.assertIsNotNone(antes_validade)
        self.assertEqual(self.alterar(self.versao(), False, preco=PRECO), 1)
        self.assertEqual(self.coluna("preco_atualizado_at"), antes_instante)
        self.assertEqual(self.coluna("preco_valido_ate"), antes_validade)

    def test_com_mudanca_de_preco_o_instante_avanca_e_a_validade_limpa(self) -> None:
        antes_instante = self.coluna("preco_atualizado_at")
        self.assertEqual(self.alterar(self.versao(), True), 1)
        self.assertNotEqual(self.coluna("preco_atualizado_at"), antes_instante)
        self.assertIsNone(self.coluna("preco_valido_ate"))
        self.assertEqual(self.coluna("preco_minor"), PRECO + 100)

    def test_uma_oferta_arquivada_nao_se_altera(self) -> None:
        self.semente.execute(
            "UPDATE platform.offer_terms SET estado = 'arquivado' WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.alterar(self.versao(), True), 0)

    def test_o_tenant_b_nao_le_nem_altera_a_oferta_de_a_com_a_versao_certa(self) -> None:
        v = self.versao()
        outro = self.criar_tenant()
        c = self.cursor_app(outro)
        self.addCleanup(c.connection.rollback)
        lista = consultas.SQL_LISTAR_OFERTAS
        c.execute(lista.sql, lista.args(outro, 10))
        self.assertEqual(len(c.fetchall()), 0)
        # O `$1` e o tenant do contexto; a RLS e o predicado recusam os dois.
        q = consultas.SQL_ALTERAR_OFERTA
        c.execute(q.sql, q.args(outro, SKU_PARTILHADO, "fixo", 1, v, True))
        self.assertEqual(len(c.fetchall()), 0)
        self.assertEqual(self.coluna("preco_minor"), PRECO)
