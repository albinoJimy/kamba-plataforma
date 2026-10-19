"""O tecto: de onde vem, quem o pode apertar, e o que acontece quando nao ha nenhum.

Nada disto esta na lista dos quatro casos do bloco do ticket, e e tudo
decisao da revisao 0007 — escrita na sua docstring e em nenhum documento do
conjunto. Uma decisao sem teste e uma decisao que a proxima revisao desfaz
sem ninguem reparar:

* **o tecto vem de `entitlements`**, e e o **minimo** entre os modulos activos
  que declaram a chave. E a regra que o dicionario §3.2 escreve para o par
  `valor_max_pedido_minor` / `manual_max_minor`, aplicada ao caso geral;
* **sem linha activa que declare a chave, nega.** Falha fechada, criterio 2
  do bloco. E nega **antes** de olhar para o `p_limite`: um argumento nao
  substitui uma linha;
* **o `p_limite` so desce.** Existe para um tecto de confianca (`EPIC-09`)
  poder ser mais apertado do que o do plano, nunca mais largo;
* **uma quantidade que nao seja positiva levanta**, em vez de ser tratada
  como zero: consumir `-5` seria devolver tecto.
"""

from __future__ import annotations

import unittest

from tests.base import VIOLACAO_DE_CHECK
from tests_ten.base import CHAVE, ComUso


class TestDeOndeVemOTecto(ComUso):
    def test_sem_entitlement_nenhum_nega(self) -> None:
        """Criterio 2: «devolve negado se nao houver linha»."""
        tenant = self.criar_tenant()
        consumo = self.consumir(tenant, quantidade=1, idempotency_key="k")
        self.assertFalse(consumo.aceite)
        self.assertFalse(consumo.repetido)
        self.assertIsNone(consumo.limite)
        self.assertEqual(int(consumo.valor), 0)
        self.assertEqual(self.uso(tenant), 0)
        self.assertEqual(self.livro(tenant), [])

    def test_sem_entitlement_o_p_limite_nao_inventa_um_tecto(self) -> None:
        """O argumento do chamador nao substitui a linha que nao existe.

        E o defeito que a revisao adversarial da 0007 apanhou: a primeira
        versao fazia `least(coalesce(v_limite, p_limite), p_limite)`, e um
        chamador com `p_limite` passava onde o canon manda negar.
        """
        tenant = self.criar_tenant()
        consumo = self.consumir(
            tenant, quantidade=1, idempotency_key="k", limite=1000
        )
        self.assertFalse(consumo.aceite)
        self.assertIsNone(consumo.limite)
        self.assertEqual(self.uso(tenant), 0)

    def test_entitlement_inactivo_nega(self) -> None:
        tenant = self.criar_tenant()
        self.dar_entitlement(tenant, {CHAVE: 100}, ativo=False)
        consumo = self.consumir(tenant, quantidade=1, idempotency_key="k")
        self.assertFalse(consumo.aceite)
        self.assertIsNone(consumo.limite)
        self.assertEqual(self.uso(tenant), 0)

    def test_um_entitlement_que_declara_outra_chave_nega_esta(self) -> None:
        """Ter modulo activo nao e ter tecto para a chave que se pede."""
        tenant = self.criar_tenant()
        self.dar_entitlement(tenant, {"marcacoes_mes": 100})
        consumo = self.consumir(tenant, quantidade=1, idempotency_key="k")
        self.assertFalse(consumo.aceite)
        self.assertIsNone(consumo.limite)

    def test_o_tecto_e_o_minimo_entre_os_modulos_que_declaram_a_chave(self) -> None:
        tenant = self.criar_tenant()
        self.dar_entitlement(tenant, {CHAVE: 50}, modulo="catalogo")
        self.dar_entitlement(tenant, {CHAVE: 10}, modulo="agenda")

        negada = self.consumir(tenant, quantidade=20, idempotency_key="a")
        self.assertFalse(negada.aceite)
        self.assertEqual(int(negada.limite), 10, "o tecto nao foi o do modulo mais apertado")

        aceite = self.consumir(tenant, quantidade=10, idempotency_key="b")
        self.assertTrue(aceite.aceite)
        self.assertEqual(int(aceite.limite), 10)

    def test_um_modulo_inactivo_nao_entra_no_minimo(self) -> None:
        """Desligar um modulo nao pode apertar o tecto dos que ficam."""
        tenant = self.criar_tenant()
        self.dar_entitlement(tenant, {CHAVE: 50}, modulo="catalogo")
        self.dar_entitlement(tenant, {CHAVE: 10}, modulo="agenda", ativo=False)
        consumo = self.consumir(tenant, quantidade=20, idempotency_key="k")
        self.assertTrue(consumo.aceite)
        self.assertEqual(int(consumo.limite), 50)


class TestOTectoDeQuemChamaSoDesce(ComUso):
    def test_um_p_limite_mais_alto_nao_levanta_o_do_plano(self) -> None:
        """`least` e nao `greatest`: 150 nao cabe em 100, mesmo pedindo 1000."""
        tenant = self.tenant_com_limite(100)
        consumo = self.consumir(
            tenant, quantidade=150, idempotency_key="k", limite=1000
        )
        self.assertFalse(
            consumo.aceite,
            "o `p_limite` levantou o tecto do plano: 150 passou contra um tecto de 100",
        )
        self.assertEqual(int(consumo.limite), 100)
        self.assertEqual(self.uso(tenant), 0)

    def test_um_p_limite_mais_baixo_aperta(self) -> None:
        tenant = self.tenant_com_limite(100)
        aceite = self.consumir(tenant, quantidade=10, idempotency_key="a", limite=10)
        self.assertTrue(aceite.aceite)
        self.assertEqual(int(aceite.limite), 10)

        negada = self.consumir(tenant, quantidade=1, idempotency_key="b", limite=10)
        self.assertFalse(negada.aceite)
        self.assertEqual(int(negada.limite), 10)
        self.assertEqual(self.uso(tenant), 10)

    def test_o_aperto_e_por_chamada_e_nao_fica(self) -> None:
        """O tecto de confianca e de quem chama, e nao um estado do tenant."""
        tenant = self.tenant_com_limite(100)
        self.consumir(tenant, quantidade=10, idempotency_key="a", limite=10)
        depois = self.consumir(tenant, quantidade=80, idempotency_key="b")
        self.assertTrue(depois.aceite)
        self.assertEqual((int(depois.valor), int(depois.limite)), (90, 100))


class TestAFronteiraDoTecto(ComUso):
    def test_encher_o_tecto_ate_ao_ultimo_e_aceite(self) -> None:
        """`<=` e nao `<`: o centesimo cabe num tecto de cem.

        Duas chamadas, e nao uma: a primeira insere a linha e nao passa pelo
        `WHERE` do `ON CONFLICT DO UPDATE`. E nesse `WHERE` que a comparacao
        vive, e so uma segunda chamada lhe chega.
        """
        tenant = self.tenant_com_limite(100)
        self.assertTrue(self.consumir(tenant, quantidade=60, idempotency_key="a").aceite)
        exacta = self.consumir(tenant, quantidade=40, idempotency_key="b")
        self.assertTrue(exacta.aceite, "40 + 60 = 100 foi recusado num tecto de 100")
        self.assertEqual(int(exacta.valor), 100)

        depois = self.consumir(tenant, quantidade=1, idempotency_key="c")
        self.assertFalse(depois.aceite)
        self.assertEqual(self.uso(tenant), 100)

    def test_o_tecto_cheio_de_uma_vez_tambem_e_aceite(self) -> None:
        """O caminho da primeira insercao, onde nao ha `ON CONFLICT`."""
        tenant = self.tenant_com_limite(100)
        consumo = self.consumir(tenant, quantidade=100, idempotency_key="k")
        self.assertTrue(consumo.aceite)
        self.assertEqual(int(consumo.valor), 100)

    def test_uma_quantidade_maior_que_o_tecto_nega_sem_contar(self) -> None:
        """E sem deixar linha nenhuma: nem contador, nem livro."""
        tenant = self.tenant_com_limite(100)
        consumo = self.consumir(tenant, quantidade=101, idempotency_key="k")
        self.assertFalse(consumo.aceite)
        self.assertEqual(int(consumo.valor), 0)
        self.assertEqual(int(consumo.limite), 100)
        self.assertEqual(self.periodos(tenant), [])
        self.assertEqual(self.livro(tenant), [])


class TestQuantidadeInvalida(ComUso):
    """Zero e negativo levantam. Nao sao «nada a consumir»: sao um erro de quem chama."""

    def test_zero_negativo_e_nulo_levantam(self) -> None:
        """E **pela guarda da funcao**, que e o que a mensagem confirma.

        Sem a guarda, um `0` ainda assim rebentava — no `CHECK (quantidade >
        0)` do livro, com o mesmo SQLSTATE e mais a dentro. O teste ficava
        verde sobre uma funcao que ja nao validava nada e deixava a recusa a
        uma restricao de coluna que existe para outra coisa. Confere-se a
        mensagem, que so a guarda escreve.
        """
        tenant = self.tenant_com_limite(100)
        for quantidade in (0, -1, -100, None):
            with self.subTest(quantidade=quantidade):
                erro = self.assertConsumoLevanta(
                    VIOLACAO_DE_CHECK,
                    tenant,
                    quantidade=quantidade,
                    idempotency_key=f"q{quantidade}",
                )
                self.assertIn("quantidade tem de ser positiva", str(erro))
        self.assertEqual(self.uso(tenant), 0)
        self.assertEqual(self.livro(tenant), [])


class TestUmTectoQueNaoSeSabeLer(ComUso):
    """Um valor que nao e um inteiro em `limites` (revisao adversarial, m1/m2).

    Era um `22P02` cru — `invalid_text_representation` do `::bigint` —
    levantado **dentro** do bloco com `EXCEPTION`, que so trata
    `unique_violation` e `KA001`. Saia da funcao e abortava a transaccao de
    quem chama, sem dizer que chave nem que tenant.

    Agora e um erro nomeado e **falha fechada**. Nao se ignora a linha
    ilegivel: ignora-la tirava um modulo do minimo, e o minimo de menos
    modulos e **maior**. Um tecto que nao se sabe ler nao e um tecto.
    """

    #: O que o `jsonb` deixa pôr num valor de limite e nao e um inteiro nao
    #: negativo que caiba num `bigint`. O ultimo e o transbordo.
    MAUS = (
        '"dez"',
        "1.5",
        "true",
        "null",
        "[10]",
        '{"max": 10}',
        "-1",
        "999999999999999999999999999999",
    )

    def test_cada_valor_ilegivel_levanta_com_nome(self) -> None:
        for valor in self.MAUS:
            with self.subTest(valor=valor):
                tenant = self.criar_tenant()
                self.semente.execute(
                    "INSERT INTO platform.entitlements (tenant_id, modulo, limites) "
                    "VALUES (%s::uuid, 'catalogo', %s::jsonb)",
                    (tenant, '{"' + CHAVE + '": ' + valor + "}"),
                )
                erro = self.assertConsumoLevanta(
                    "22023", tenant, quantidade=1, idempotency_key="k"
                )
                self.assertIn("nao e um inteiro", str(erro))
                self.assertEqual(self.uso(tenant), 0)

    def test_um_modulo_ilegivel_nao_deixa_passar_pelo_minimo_dos_outros(self) -> None:
        """Falha fechada: dois modulos, um legivel e apertado, outro ilegivel."""
        tenant = self.criar_tenant()
        self.dar_entitlement(tenant, {CHAVE: 10}, modulo="catalogo")
        self.semente.execute(
            "INSERT INTO platform.entitlements (tenant_id, modulo, limites) "
            "VALUES (%s::uuid, 'agenda', %s::jsonb)",
            (tenant, '{"' + CHAVE + '": "sem limite"}'),
        )
        self.assertConsumoLevanta("22023", tenant, quantidade=1, idempotency_key="k")

    def test_um_tecto_enorme_mas_legivel_continua_a_funcionar(self) -> None:
        """Dezoito algarismos cabem, e a soma do contador nao transborda.

        **E e o tecto de algarismos que o garante, e nao um cast.** A
        primeira correccao punha a soma do `ON CONFLICT DO UPDATE` em
        `numeric` contra o `22003`, e a prova por mutacao mostrou que a
        mutacao que a devolvia a `bigint` **nao morria**: com limites ate
        10^18, `valor + quantidade` nunca passa de 2 x 10^18 e o `bigint` vai
        ate 9,2 x 10^18. O cast saiu — era defesa sobre uma porta ja fechada,
        e uma linha que nenhuma mutacao consegue partir nao esta a defender
        nada. Quem fecha a porta e o `length <= 18` da `ten_tecto`, e e esse
        que tem mutacao.
        """
        enorme = 999_999_999_999_999_999
        tenant = self.tenant_com_limite(enorme)
        primeira = self.consumir(tenant, quantidade=enorme - 1, idempotency_key="a")
        self.assertTrue(primeira.aceite)
        self.assertEqual(int(primeira.limite), enorme)

        cabe = self.consumir(tenant, quantidade=1, idempotency_key="b")
        self.assertTrue(cabe.aceite)
        self.assertEqual(int(cabe.valor), enorme)

        nao_cabe = self.consumir(tenant, quantidade=1, idempotency_key="c")
        self.assertFalse(nao_cabe.aceite)
        self.assertEqual(self.uso(tenant), enorme)


class TestOAvisoDaOrdemDasChaves(ComUso):
    """m3: duas chaves em ordens opostas bloqueiam-se, e nao havia aviso.

    A revisao adversarial mediu um `40P01` entre duas transaccoes que
    consomem duas chaves de limite na mesma transaccao, por ordens opostas. A
    funcao **nao pode** impor a ordem: ve uma chave de cada vez. A ordem e de
    quem chama, e o unico sitio onde isso se diz a quem liga a base e o
    `COMMENT` da funcao.

    Um aviso que se pode apagar em silencio nao e um aviso: este teste le o
    comentario do catalogo e falha se ele deixar de nomear a regra.
    """

    def test_o_comentario_da_funcao_nomeia_a_ordem_e_o_isolamento(self) -> None:
        self.semente.execute(
            "SELECT obj_description(p.oid, 'pg_proc') "
            "  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = 'ten_consumir'"
        )
        linha = self.semente.fetchone()
        self.assertIsNotNone(linha, "a funcao nao tem COMMENT nenhum")
        comentario = str(linha[0] or "")
        for esperado in (
            "ORDEM DAS CHAVES",
            "chave_limite",
            "deadlock",
            "40P01",
            "READ COMMITTED",
            "KA002",
        ):
            with self.subTest(esperado=esperado):
                self.assertIn(esperado, comentario)


class TestAssinatura(ComUso):
    """Os valores por omissao da assinatura, e quem pode executar a funcao."""

    def test_a_chamada_com_quatro_argumentos_usa_as_omissoes(self) -> None:
        """`p_limite` nulo e `p_agora` a valer `now()`: o caso da biblioteca."""
        tenant = self.tenant_com_limite(100)
        cursor = self.cursor_app(tenant)
        cursor.execute(
            "SELECT aceite, valor, repetido, limite "
            "  FROM platform.ten_consumir(%s::uuid, %s, 3::bigint, 'omissoes')",
            (tenant, CHAVE),
        )
        aceite, valor, repetido, limite = cursor.fetchone()
        self.assertEqual((aceite, int(valor), repetido, int(limite)), (True, 3, False, 100))
        cursor.execute(
            "SELECT periodo = platform.ten_periodo() FROM platform.tenant_usage "
            " WHERE tenant_id = %s::uuid",
            (tenant,),
        )
        self.assertEqual([tuple(l) for l in cursor.fetchall()], [(True,)])

    def test_a_funcao_e_executavel_pela_aplicacao_e_pelo_batch(self) -> None:
        self.assertEqual(
            self.consultar(
                "SELECT has_function_privilege(%s, "
                "  'platform.ten_consumir(uuid, text, bigint, text, bigint, timestamptz)', "
                "  'EXECUTE'), "
                "  has_function_privilege(%s, 'platform.ten_periodo(timestamptz)', 'EXECUTE')",
                ("kamba_app", "kamba_app"),
            ),
            [(True, True)],
        )
        self.assertEqual(
            self.consultar(
                "SELECT has_function_privilege(%s, "
                "  'platform.ten_consumir(uuid, text, bigint, text, bigint, timestamptz)', "
                "  'EXECUTE')",
                ("kamba_batch",),
            ),
            [(True,)],
        )


if __name__ == "__main__":
    unittest.main()
