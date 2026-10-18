"""Criterio 4 do KAM-009: a mesma chave nao consome duas vezes — e o que a nega nao a gasta.

Duas afirmacoes, e a segunda e a que interessa:

1. «Repetir a mesma `idempotencyKey` nao consome duas vezes (10 repeticoes,
   uso = 1)», que e a letra do criterio;
2. uma chamada **negada pelo tecto** nao pode deixar a chave no livro.
   Repeti-la a seguir, com espaco no tecto, tem de **consumir**.

A segunda e a que mede o desenho. A revisao 0007 regista a chave **antes** de
contar, para que uma chamada repetida nao conte duas vezes na janela entre as
duas escritas; isso significa que a chave de uma chamada que o tecto acaba por
recusar chegou a ser escrita. O desfazer nao e um `DELETE` — a aplicacao nao
tem `DELETE` em tabela nenhuma — e sim o *rollback* da subtransaccao que o
bloco `EXCEPTION` do plpgsql abre. Se esse *rollback* nao levasse a chave, um
cliente que retentasse depois de um `429` recebia «ja foi consumido» para um
consumo que nunca aconteceu, e ficava sem o servico para sempre.

A funcao tem **dois** caminhos de recusa, e os dois tem de desfazer:

* `p_quantidade > v_limite` — o pedido nao cabe no tecto, nem numa conta
  vazia;
* o `WHERE` do `ON CONFLICT DO UPDATE` sem linha devolvida — cabia no tecto,
  mas nao no que resta dele.

Cada um tem aqui o seu teste, porque sao duas instrucoes diferentes a levantar
o mesmo `KA001`.

**E a ordem das duas escritas tem um teste so para ela**
(`test_repetir_uma_chave_gasta_com_a_conta_cheia_diz_repetido`). A ordem
inversa — contar primeiro, registar a chave depois — passa em todos os
outros, porque o *rollback* da subtransaccao desfaz as duas escritas seja qual
for a ordem. O que a ordem inversa parte e a **resposta**: com a conta cheia,
a repeticao de uma chave ja gasta bate no tecto antes de bater na chave, e
devolve «negado» onde devia devolver «repetido». E a diferenca entre um
cliente que repete um pedido e recebe o resultado que ja tinha, e um que
recebe um `429` por um consumo que foi dele.
"""

from __future__ import annotations

import unittest

from tests_ten.base import ComUso

#: Os dois instantes servem para provar o desfazer no caminho em que a conta
#: ja esta cheia: o periodo seguinte e a unica forma de abrir espaco sem
#: apagar nada (e nada nesta base se apaga para abrir espaco).
NOVEMBRO = "2026-11-15T12:00:00+01:00"
DEZEMBRO = "2026-12-15T12:00:00+01:00"


class TestRepeticao(ComUso):
    """O contrato da repeticao, medido: `aceite = true` **e** `repetido = true`.

    Nao e obvio e merece ficar escrito, porque a leitura ingenua («nao
    consumiu, logo nao aceitou») leva ao contrario. A funcao devolve
    `v_repetido` tambem na coluna `aceite`, e e o que o chamador precisa: um
    cliente que repete um pedido por nao ter visto a resposta **teve** o seu
    consumo aplicado, e a resposta certa e a mesma que teria tido da primeira
    vez — nao um `429`. O `repetido` e que lhe diz que nao houve consumo novo,
    para as metricas o saberem.

    As recusas, essas, trazem `aceite = false` e `repetido = false`: estao em
    `TestNegarNaoGastaAChave`.
    """

    def test_dez_repeticoes_da_mesma_chave_dao_uso_um(self) -> None:
        """A letra do criterio 4."""
        tenant = self.tenant_com_limite(100)

        primeira = self.consumir(tenant, quantidade=1, idempotency_key="k")
        self.assertEqual(
            (primeira.aceite, int(primeira.valor), primeira.repetido), (True, 1, False)
        )
        for tentativa in range(2, 11):
            with self.subTest(tentativa=tentativa):
                repetida = self.consumir(tenant, quantidade=1, idempotency_key="k")
                self.assertTrue(repetida.repetido)
                self.assertTrue(repetida.aceite, "uma repeticao nao e uma recusa")
                self.assertEqual(int(repetida.valor), 1)

        self.assertEqual(self.uso(tenant), 1)
        self.assertEqual(self.livro(tenant), [("k", self.periodos(tenant)[0][0], 1)])

    def test_a_quantidade_da_repeticao_e_ignorada(self) -> None:
        """A chave e a identidade do pedido; o que vem com ela nao a altera."""
        tenant = self.tenant_com_limite(100)
        self.consumir(tenant, quantidade=3, idempotency_key="k")
        repetida = self.consumir(tenant, quantidade=50, idempotency_key="k")
        self.assertTrue(repetida.repetido)
        self.assertEqual(self.uso(tenant), 3)

    def test_dois_tenants_podem_usar_a_mesma_chave(self) -> None:
        """A chave e por tenant: quem a escolhe e quem chama, e nao se coordena."""
        a = self.tenant_com_limite(100)
        b = self.tenant_com_limite(100)
        for tenant in (a, b):
            with self.subTest(tenant=tenant):
                self.assertTrue(
                    self.consumir(tenant, quantidade=1, idempotency_key="k").aceite
                )
        self.assertEqual((self.uso(a), self.uso(b)), (1, 1))


class TestNegarNaoGastaAChave(ComUso):
    """Os dois caminhos de recusa desfazem a chave que acabaram de escrever."""

    def test_recusa_por_pedido_maior_que_o_tecto_nao_gasta_a_chave(self) -> None:
        """`p_quantidade > v_limite`: o pedido nao cabe nem numa conta vazia.

        Aperta-se o tecto com o `p_limite` do chamador e nao com o
        entitlement, para que a segunda tentativa possa ter espaco sem
        ninguem escrever em `entitlements` a meio do teste.
        """
        tenant = self.tenant_com_limite(100)

        negada = self.consumir(
            tenant, quantidade=50, idempotency_key="k", limite=10
        )
        self.assertFalse(negada.aceite)
        self.assertFalse(negada.repetido)
        self.assertEqual(int(negada.limite), 10)
        self.assertFalse(self.no_livro(tenant, "k"))
        self.assertEqual(self.uso(tenant), 0)

        segunda = self.consumir(tenant, quantidade=50, idempotency_key="k")
        self.assertTrue(segunda.aceite, "a chave ficou no livro de uma recusa")
        self.assertEqual(int(segunda.valor), 50)
        self.assertEqual(self.uso(tenant), 50)

    def test_recusa_por_conta_cheia_nao_gasta_a_chave(self) -> None:
        """O `WHERE` do `ON CONFLICT DO UPDATE` sem linha devolvida.

        Cabia no tecto (1 <= 10) e nao cabe no que resta dele (10 + 1 > 10).
        O espaco para a segunda tentativa vem do **periodo seguinte**, que e a
        unica forma de o abrir: nada nesta base se apaga para libertar tecto.
        """
        tenant = self.tenant_com_limite(10)
        self.assertTrue(
            self.consumir(
                tenant, quantidade=10, idempotency_key="cheia", agora=NOVEMBRO
            ).aceite
        )

        negada = self.consumir(
            tenant, quantidade=1, idempotency_key="k", agora=NOVEMBRO
        )
        self.assertFalse(negada.aceite)
        self.assertFalse(negada.repetido)
        self.assertEqual(int(negada.valor), 10)
        self.assertFalse(self.no_livro(tenant, "k"))

        segunda = self.consumir(
            tenant, quantidade=1, idempotency_key="k", agora=DEZEMBRO
        )
        self.assertTrue(segunda.aceite, "a chave ficou no livro de uma recusa")
        self.assertEqual(
            self.periodos(tenant), [("2026-11-01", 10), ("2026-12-01", 1)]
        )
        self.assertEqual(
            self.livro(tenant),
            [("cheia", "2026-11-01", 10), ("k", "2026-12-01", 1)],
        )

    def test_repetir_uma_chave_gasta_com_a_conta_cheia_diz_repetido(self) -> None:
        """A ordem das duas escritas, e o unico teste que a ve.

        Com a conta exactamente cheia, repete-se uma chave **ja gasta**. A
        chave esta no livro, pelo que a resposta certa e «repetido»: o
        consumo que o cliente esta a repetir aconteceu, e o valor que se lhe
        devolve e o que ele ja tinha.

        Contar primeiro e registar a chave depois inverte isto: a contagem
        bate no tecto antes de a chave bater na unicidade, e a funcao
        responde «negado» — um `429` por um consumo que foi do proprio
        cliente. Os outros testes desta suite nao distinguem as duas ordens,
        porque o *rollback* da subtransaccao desfaz as duas escritas seja
        qual for a ordem em que foram feitas.
        """
        tenant = self.tenant_com_limite(10)
        primeira = self.consumir(tenant, quantidade=10, idempotency_key="k")
        self.assertEqual((primeira.aceite, int(primeira.valor)), (True, 10))

        repetida = self.consumir(tenant, quantidade=10, idempotency_key="k")
        self.assertTrue(
            repetida.repetido,
            "com a conta cheia, repetir uma chave ja gasta devolveu «negado»: "
            "a chave esta a ser registada depois da contagem",
        )
        self.assertTrue(
            repetida.aceite,
            "a repeticao de um consumo que aconteceu devolveu uma recusa",
        )
        self.assertEqual(int(repetida.valor), 10)
        self.assertEqual(self.uso(tenant), 10)
        self.assertEqual(self.livro(tenant), [("k", self.periodos(tenant)[0][0], 10)])


if __name__ == "__main__":
    unittest.main()
