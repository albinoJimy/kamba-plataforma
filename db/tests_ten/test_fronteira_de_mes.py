"""Criterio 5 do KAM-009: o mes fecha as 00:00 de `Africa/Luanda`, com relogio fixo.

«Com relogio fixo em `2026-11-30T23:59:59+01:00` o consumo conta para
Novembro; em `2026-12-01T00:00:00+01:00` para Dezembro.» O `p_agora` existe na
assinatura da `ten_consumir` exactamente para isto: sem ele, provar a fronteira
obrigava a esperar pelo fim de um mes, ou a mexer no relogio da maquina.

**E prova-se que o fuso e `Africa/Luanda` e nao UTC.** Os dois instantes do
criterio estao, os dois, do mesmo lado nos dois fusos — `+01:00` e meia-noite
sao o mesmo dia em UTC e em Luanda a um segundo de distancia — pelo que
passariam com a funcao escrita em UTC. O caso que **distingue** e um instante
que caia em meses diferentes nos dois fusos, e esta aqui:

    2026-11-30T23:30:00Z  ==  2026-12-01T00:30:00+01:00

Em UTC e Novembro; em Luanda e Dezembro. A `ten_periodo` tem de dizer
Dezembro.

**E nao pode depender do fuso da sessao.** `date_trunc('month', x)` sobre um
`timestamptz` sem `AT TIME ZONE` usa o `TimeZone` da sessao, e a resposta
passava a depender de quem liga. As mesmas perguntas correm aqui com a sessao
em UTC e com a sessao em `Pacific/Kiritimati` (+14), e tem de dar o mesmo.
"""

from __future__ import annotations

import unittest

import pg8000.dbapi

from tests.base import sqlstate
from tests_ten.base import CHAVE, SQL_PERIODO, ComUso

#: Os dois instantes do criterio, a letra.
FIM_DE_NOVEMBRO = "2026-11-30T23:59:59+01:00"
INICIO_DE_DEZEMBRO = "2026-12-01T00:00:00+01:00"

#: O instante que distingue Luanda de UTC: 23:30 de 30 de Novembro em UTC e
#: 00:30 de 1 de Dezembro em Luanda. Escrito nas duas formas, que sao o mesmo
#: instante — e o teste confirma que o sao.
VIRAGEM_EM_UTC = "2026-11-30T23:30:00+00:00"
VIRAGEM_EM_LUANDA = "2026-12-01T00:30:00+01:00"

#: Fusos de sessao com que tudo isto corre. `Pacific/Kiritimati` e +14: nao ha
#: fuso mais longe de Luanda, e e o que torna o teste desagradavel de passar
#: por acaso.
FUSOS_DA_SESSAO = ("UTC", "Africa/Luanda", "Pacific/Kiritimati")


class TestPeriodo(ComUso):
    """`platform.ten_periodo`, sozinha, antes de a usar para consumir.

    **E pelo `SQL_PERIODO` da biblioteca**, e nao por um `SELECT` escrito
    aqui. Era escrito aqui, e a revisao adversarial mostrou o que isso
    escondia: o `SQL_PERIODO` nao tinha `coalesce`, pelo que `periodo()` sem
    instante devolvia `NULL` — `None` em silencio do lado Python, excepcao do
    lado TypeScript. O texto que a biblioteca envia passa a ser o texto que o
    gate 8 corre contra uma base.
    """

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("app").cursor()

    def periodo(self, instante: str | None) -> str:
        self.cursor.execute(SQL_PERIODO, (instante,))
        return str(self.cursor.fetchone()[0])

    def test_os_dois_instantes_do_criterio(self) -> None:
        self.assertEqual(self.periodo(FIM_DE_NOVEMBRO), "2026-11-01")
        self.assertEqual(self.periodo(INICIO_DE_DEZEMBRO), "2026-12-01")

    def test_sem_instante_o_periodo_e_o_corrente_e_nao_nulo(self) -> None:
        """O defeito do `SQL_PERIODO` sem `coalesce`, medido contra a base."""
        self.cursor.execute("SELECT platform.ten_periodo()::text")
        corrente = str(self.cursor.fetchone()[0])
        self.assertEqual(self.periodo(None), corrente)

    def test_as_duas_escritas_da_viragem_sao_o_mesmo_instante(self) -> None:
        """Sem isto, o teste seguinte podia estar a comparar duas coisas."""
        self.cursor.execute(
            "SELECT %s::timestamptz = %s::timestamptz",
            (VIRAGEM_EM_UTC, VIRAGEM_EM_LUANDA),
        )
        self.assertTrue(self.cursor.fetchone()[0])

    def test_a_viragem_e_de_luanda_e_nao_de_utc(self) -> None:
        """O caso que distingue os dois fusos, e o unico que o faz."""
        self.cursor.execute(
            "SELECT date_trunc('month', %s::timestamptz AT TIME ZONE 'UTC')::date::text",
            (VIRAGEM_EM_UTC,),
        )
        self.assertEqual(
            str(self.cursor.fetchone()[0]),
            "2026-11-01",
            "o instante escolhido ja nao cai em meses diferentes nos dois fusos",
        )
        self.assertEqual(self.periodo(VIRAGEM_EM_UTC), "2026-12-01")

    def test_o_fuso_da_sessao_nao_muda_a_resposta(self) -> None:
        for fuso in FUSOS_DA_SESSAO:
            with self.subTest(fuso=fuso):
                self.cursor.execute(f"SET LOCAL TimeZone = '{fuso}'")
                self.assertEqual(self.periodo(FIM_DE_NOVEMBRO), "2026-11-01")
                self.assertEqual(self.periodo(INICIO_DE_DEZEMBRO), "2026-12-01")
                self.assertEqual(self.periodo(VIRAGEM_EM_UTC), "2026-12-01")

    def test_o_periodo_e_sempre_o_primeiro_dia_do_mes(self) -> None:
        """E o que o `CHECK` de `tenant_usage.periodo` exige da coluna."""
        self.cursor.execute(
            "SELECT bool_and(platform.ten_periodo(d) "
            "                = date_trunc('month', platform.ten_periodo(d))::date) "
            "  FROM generate_series('2026-01-01T00:00:00+01:00'::timestamptz, "
            "                       '2026-12-31T23:00:00+01:00'::timestamptz, "
            "                       interval '7 hours') AS d"
        )
        self.assertTrue(self.cursor.fetchone()[0])


class TestConsumoNaFronteira(ComUso):
    """O que o criterio pede: o **consumo** conta para o mes certo."""

    def test_o_consumo_de_cada_lado_cai_no_seu_mes(self) -> None:
        tenant = self.tenant_com_limite(100)

        antes = self.consumir(
            tenant, quantidade=7, idempotency_key="nov", agora=FIM_DE_NOVEMBRO,
            papel="batch",
        )
        depois = self.consumir(
            tenant, quantidade=3, idempotency_key="dez", agora=INICIO_DE_DEZEMBRO,
            papel="batch",
        )
        self.assertEqual((antes.aceite, int(antes.valor)), (True, 7))
        self.assertEqual(
            (depois.aceite, int(depois.valor)),
            (True, 3),
            "o consumo de Dezembro somou ao de Novembro: o periodo nao virou",
        )
        self.assertEqual(
            self.periodos(tenant), [("2026-11-01", 7), ("2026-12-01", 3)]
        )
        self.assertEqual(
            self.livro(tenant),
            [("dez", CHAVE, "2026-12-01", 3), ("nov", CHAVE, "2026-11-01", 7)],
        )

    def test_o_tecto_e_por_periodo_e_nao_acumulado(self) -> None:
        """Encher Novembro nao deixa Dezembro sem nada."""
        tenant = self.tenant_com_limite(10)
        self.assertTrue(
            self.consumir(
                tenant, quantidade=10, idempotency_key="n", agora=FIM_DE_NOVEMBRO,
                papel="batch",
            ).aceite
        )
        de_dezembro = self.consumir(
            tenant, quantidade=10, idempotency_key="d", agora=INICIO_DE_DEZEMBRO,
            papel="batch",
        )
        self.assertTrue(de_dezembro.aceite)
        self.assertEqual(int(de_dezembro.valor), 10)

    def test_a_viragem_de_luanda_conta_para_dezembro(self) -> None:
        """O instante que em UTC ainda e Novembro. Com o fuso da sessao em UTC."""
        tenant = self.tenant_com_limite(100)
        consumo = self.consumir(
            tenant, quantidade=4, idempotency_key="v", agora=VIRAGEM_EM_UTC,
            fuso="UTC", papel="batch",
        )
        self.assertTrue(consumo.aceite)
        self.assertEqual(self.periodos(tenant), [("2026-12-01", 4)])
        self.assertEqual(self.livro(tenant), [("v", CHAVE, "2026-12-01", 4)])


class TestORelogioSoSeFixaDeRetaguarda(ComUso):
    """O `p_agora` nas maos de quem corre como a aplicacao (revisao adversarial).

    O `p_agora` existe para a fronteira de mes se poder provar e para a
    reconciliacao poder reprocessar um periodo fechado. Nao e alcancavel pelo
    cliente — as bibliotecas passam `coalesce($6, now())` — mas `kamba_app`
    tem `EXECUTE` na assinatura de seis argumentos, e isso chegava: medido
    pelo revisor, `p_agora = '2020-01-15'` com o mes corrente esgotado
    devolvia `[True, 10, False, 10]` e abria uma linha em `2020-01-01`.

    Um balde novo por cada mes do calendario nao e um limite mensal. A guarda
    e por papel e nao por janela de tempo: qualquer janela deixava passar os
    outros onze meses, e so o papel distingue «a aplicacao a consumir» de «a
    retaguarda a reprocessar».
    """

    #: Um mes que nao e o corrente, aconteca este teste em que dia acontecer.
    PASSADO = "2020-01-15T12:00:00+01:00"
    FUTURO = "2099-06-15T12:00:00+01:00"

    def test_a_aplicacao_e_recusada_num_periodo_que_nao_e_o_corrente(self) -> None:
        tenant = self.tenant_com_limite(10)
        for instante in (self.PASSADO, self.FUTURO):
            with self.subTest(instante=instante):
                erro = self.assertConsumoLevanta(
                    "22023",
                    tenant,
                    quantidade=1,
                    idempotency_key=f"fora-{instante}",
                    agora=instante,
                )
                self.assertIn("so o kamba_batch fixa o relogio", str(erro))
        self.assertEqual(self.periodos(tenant), [], "ficou linha de outro periodo")
        self.assertEqual(self.livro(tenant), [])

    def test_a_aplicacao_consome_no_periodo_corrente(self) -> None:
        """O controlo positivo: a guarda nao pode fechar o caminho normal.

        Passa-se o `agora` **explicito** e igual ao instante corrente, que e o
        caso em que a guarda e exercitada e tem de deixar passar.
        """
        tenant = self.tenant_com_limite(10)
        consumo = self.consumir(
            tenant, quantidade=1, idempotency_key="agora", agora="now"
        )
        self.assertTrue(consumo.aceite)

    def test_a_retaguarda_fixa_o_relogio(self) -> None:
        tenant = self.tenant_com_limite(10)
        consumo = self.consumir(
            tenant, quantidade=1, idempotency_key="passado",
            agora=self.PASSADO, papel="batch",
        )
        self.assertTrue(consumo.aceite)
        self.assertEqual(self.periodos(tenant), [("2020-01-01", 1)])

    def test_um_p_agora_nulo_levanta_em_vez_de_escrever_um_periodo_nulo(self) -> None:
        """`coalesce($6, now())` protege as bibliotecas; quem chama a mao, nao.

        Sem esta guarda o `NULL` chegava ao `date_trunc`, o periodo saia nulo
        e a insercao morria num `NOT NULL` que nao diz nada a quem le o erro.
        """
        tenant = self.tenant_com_limite(10)
        cursor = self.cursor_app(tenant)
        cursor.execute("SAVEPOINT caso_negativo")
        try:
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                cursor.execute(
                    "SELECT aceite FROM platform.ten_consumir("
                    "  %s::uuid, %s, 1::bigint, 'nulo', NULL::bigint, NULL::timestamptz)",
                    (tenant, CHAVE),
                )
        finally:
            cursor.execute("ROLLBACK TO SAVEPOINT caso_negativo")
        self.assertEqual(sqlstate(capturado.exception), "22023")
        self.assertIn("p_agora nulo", str(capturado.exception))


if __name__ == "__main__":
    unittest.main()
