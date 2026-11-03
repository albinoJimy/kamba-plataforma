"""Criterios 4 e 5: o `lines_snapshot` imutavel e o `numero_publico`.

O que so aqui se prova: que a imutabilidade e do *trigger* e nao do modulo (com
o `UPDATE` concedido, um caminho qualquer reescrevia as linhas de uma encomenda
que o cliente ja confirmou), e que o gerador do numero nao colide em dez mil
geracoes — que e aritmetica, mas aritmetica sobre o gerador que corre e nao
sobre o que se pensa que ele faz.
"""

from __future__ import annotations

import json
import re

import pg8000.dbapi
from tests.base import (
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    sqlstate,
)
from tests_encomendas.base import (
    LINHAS,
    SNAPSHOT_IMUTAVEL,
    TOTAL,
    ComEncomendas,
)


#: O alfabeto base32 de Crockford: os dez digitos e as vinte e duas letras que
#: ficam depois de sair `I`, `L`, `O` e `U`.
ALFABETO = re.compile(r"^[0-9A-HJKMNP-TV-Z]{1,8}$")

#: Quantas geracoes o criterio 5 pede.
GERACOES = 10_000


class TestSnapshotImutavel(ComEncomendas):
    """Criterio 4: imutavel depois de `aguarda_pagamento`."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()

    def test_em_criada_as_linhas_ainda_mudam(self) -> None:
        """O criterio diz «depois de `aguarda_pagamento`», e e so depois.

        E o sentido que uma leitura apressada deixa cair: em `criada` o KAM-046
        ainda resolve precos e linhas contra o Registo, e congelar aqui tornava
        esse ticket impossivel.
        """
        encomenda = self.criar_encomenda(self.tenant)
        outras = [dict(LINHAS[0], qty=2)]
        self.semente.execute(
            "UPDATE platform.orders_mirror SET lines_snapshot = %s, "
            "       total_minor = %s WHERE tenant_id = %s AND id = %s",
            (json.dumps(outras), TOTAL * 2, self.tenant, encomenda),
        )
        self.assertEqual(
            self.consultar(
                "SELECT total_minor FROM platform.orders_mirror WHERE id = %s",
                (encomenda,),
            ),
            [(TOTAL * 2,)],
        )

    def test_depois_de_aguarda_pagamento_as_linhas_nao_mudam(self) -> None:
        encomenda = self.criar_encomenda(self.tenant)
        self.levar_a(self.tenant, encomenda, "aguarda_pagamento")
        for coluna, valor in (
            ("lines_snapshot", json.dumps([dict(LINHAS[0], qty=9)])),
            ("total_minor", TOTAL * 3),
            ("currency", "AOA"),
        ):
            with self.subTest(coluna=coluna):
                try:
                    self.semente.execute(
                        f"UPDATE platform.orders_mirror SET {coluna} = %s "
                        " WHERE tenant_id = %s AND id = %s",
                        (valor, self.tenant, encomenda),
                    )
                    if coluna == "currency":
                        # A moeda **nao** muda porque o valor novo e o mesmo: a
                        # unica moeda do dominio e `AOA`, pelo que o `UPDATE`
                        # passa sem alterar nada. O ensaio da coluna esta no
                        # `test_a_moeda_fora_do_dominio_e_recusada`.
                        return
                    self.fail(f"{coluna} nao devia mudar depois de criada")
                except pg8000.dbapi.DatabaseError as erro:
                    self.assertEqual(sqlstate(erro), SNAPSHOT_IMUTAVEL)

    def test_o_total_congela_com_as_linhas_e_nao_sozinho(self) -> None:
        """Deixar mudar um sem o outro era o espelho a desmentir-se.

        E precisamente a divergencia que a regra 3 do §10.3 manda resolver a
        favor do `lines_snapshot`: um total que as proprias linhas nao somam.
        """
        encomenda = self.criar_encomenda(self.tenant)
        self.levar_a(self.tenant, encomenda, "aguarda_pagamento")
        try:
            self.semente.execute(
                "UPDATE platform.orders_mirror SET total_minor = total_minor + 1 "
                " WHERE tenant_id = %s AND id = %s",
                (self.tenant, encomenda),
            )
            self.fail("o total nao devia mudar sozinho")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), SNAPSHOT_IMUTAVEL)

    def test_as_outras_colunas_continuam_a_mudar(self) -> None:
        """A imutabilidade e das tres e nao da linha: a encomenda ainda vive."""
        encomenda = self.criar_encomenda(self.tenant)
        self.levar_a(self.tenant, encomenda, "aguarda_pagamento")
        self.semente.execute(
            "UPDATE platform.orders_mirror "
            "   SET expira_at = now() + interval '24 hours', "
            "       medusa_order_id = 'ord_123' "
            " WHERE tenant_id = %s AND id = %s",
            (self.tenant, encomenda),
        )
        self.assertEqual(
            self.consultar(
                "SELECT medusa_order_id FROM platform.orders_mirror WHERE id = %s",
                (encomenda,),
            ),
            [("ord_123",)],
        )

    def test_o_total_negativo_e_recusado(self) -> None:
        """Criterio 4: `total_minor >= 0`."""
        try:
            self.criar_encomenda(self.tenant, total=-1)
            self.fail("um total negativo nao devia passar")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), VIOLACAO_DE_CHECK)

    def test_a_moeda_fora_do_dominio_e_recusada(self) -> None:
        """Criterio 4: «`currency` explicita». Dominio de um valor (§3.4)."""
        try:
            self.criar_encomenda(self.tenant, currency="USD")
            self.fail("`USD` nao devia passar")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), VIOLACAO_DE_CHECK)

    def test_a_moeda_tem_omissao_e_nao_fica_por_dizer(self) -> None:
        encomenda = self.criar_encomenda(self.tenant)
        self.assertEqual(
            self.consultar(
                "SELECT currency FROM platform.orders_mirror WHERE id = %s",
                (encomenda,),
            ),
            [("AOA",)],
        )

    def test_um_snapshot_que_nao_e_lista_e_recusado(self) -> None:
        """Um objecto nao e uma lista de linhas, e quebrava quem o projecta."""
        try:
            self.semente.execute(
                "INSERT INTO platform.orders_mirror "
                "       (tenant_id, contact_id, intent_key, total_minor, "
                "        lines_snapshot) "
                "VALUES (%s, %s, 'ik-forma', 1, %s)",
                (self.tenant, self.criar_contacto(self.tenant), '{"sku": "x"}'),
            )
            self.fail("um objecto nao devia passar como `lines_snapshot`")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), VIOLACAO_DE_CHECK)


class TestNumeroPublico(ComEncomendas):
    """Criterio 5: base32 sem ambiguos, <= 8, unico por tenant."""

    def test_dez_mil_geracoes_sem_colisao(self) -> None:
        """O criterio a letra. Uma consulta e nao dez mil idas a base.

        `generate_series` dentro da base: dez mil chamadas em Python levavam a
        suite ao limite de tempo do *gate* por nenhuma razao — o que se mede e o
        gerador, e ele corre la.
        """
        linhas = self.consultar(
            "SELECT count(*), count(DISTINCT n) FROM ("
            "  SELECT platform.order_numero_publico() AS n "
            "    FROM generate_series(1, %s)) AS g",
            (GERACOES,),
        )
        self.assertEqual(
            linhas,
            [(GERACOES, GERACOES)],
            "dez mil geracoes e dez mil valores distintos. Com **seis** "
            "caracteres em vez de oito a probabilidade de colisao seria 4,6% "
            "(32^6 = 1 073 741 824; 1 - exp(-49 995 000 / 32^6)), e este "
            "ensaio reprovaria uma vez em vinte e duas sem haver defeito "
            "nenhum — e a razao de serem oito, e esta aqui para que a escolha "
            "nao se perca",
        )

    def test_o_alfabeto_nao_tem_ambiguos(self) -> None:
        """Nem `I`, nem `L`, nem `O`, nem `U` — e o `0` deixa de ser ambiguo."""
        linhas = self.consultar(
            "SELECT DISTINCT n FROM ("
            "  SELECT platform.order_numero_publico() AS n "
            "    FROM generate_series(1, 2000)) AS g"
        )
        self.assertTrue(linhas)
        for (numero,) in linhas:
            with self.subTest(numero=numero):
                self.assertEqual(len(numero), 8)
                self.assertRegex(numero, ALFABETO)

    def test_os_trinta_e_dois_simbolos_aparecem_todos(self) -> None:
        """Nos dois sentidos: um gerador que use so metade do alfabeto colidia
        mais do que a conta de cima diz, e passava os dois ensaios acima."""
        linhas = self.consultar(
            "SELECT DISTINCT regexp_split_to_table(n, '') FROM ("
            "  SELECT platform.order_numero_publico() AS n "
            "    FROM generate_series(1, 5000)) AS g"
        )
        self.assertEqual(
            len({simbolo for (simbolo,) in linhas}),
            32,
            "os trinta e dois simbolos de Crockford aparecem em cinco mil "
            "geracoes de oito caracteres (40 000 simbolos): um alfabeto "
            "efectivo menor era um gerador com menos entropia do que declara",
        )

    def test_e_unico_por_tenant_e_nao_global(self) -> None:
        """Criterio 5: «unico por tenant». Dois tenants podem ter o mesmo."""
        a, b = self.criar_tenant(), self.criar_tenant()
        encomenda = self.criar_encomenda(a)
        self.semente.execute(
            "SELECT numero_publico FROM platform.orders_mirror WHERE id = %s",
            (encomenda,),
        )
        numero = str(self.semente.fetchone()[0])
        # No outro tenant, o mesmo numero passa.
        self.criar_encomenda(b, numero_publico=numero)
        # No mesmo, nao.
        try:
            self.criar_encomenda(a, numero_publico=numero)
            self.fail("o mesmo numero no mesmo tenant nao devia passar")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), VIOLACAO_DE_UNICIDADE)

    def test_um_numero_com_caracter_ambiguo_e_recusado(self) -> None:
        """O `CHECK` da forma, nos dois sentidos com o gerador."""
        tenant = self.criar_tenant()
        for numero in ("K7H3Q9I", "LLLL", "OOOO", "UUUU", "K7H3Q9AB1", "k7h3q9"):
            with self.subTest(numero=numero):
                try:
                    self.criar_encomenda(tenant, numero_publico=numero)
                    self.fail(f"`{numero}` nao devia passar o CHECK")
                except pg8000.dbapi.DatabaseError as erro:
                    self.assertEqual(sqlstate(erro), VIOLACAO_DE_CHECK)

    def test_o_exemplo_do_criterio_passa(self) -> None:
        """`K7H3Q9`, que e o exemplo escrito no §5.4 e no criterio 5."""
        self.criar_encomenda(self.criar_tenant(), numero_publico="K7H3Q9")
