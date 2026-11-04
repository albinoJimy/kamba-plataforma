"""As partes das baterias que se medem sem base de dados e sem `node`.

O `fn` de um caso de X-03 ou de C-01 so faz sentido contra um PostgreSQL, e e
no *gate* 6 que corre. O que **se** mede aqui e o que decide se esses casos
estao certos antes de chegarem la: a uniformidade, a construcao dos argumentos
de ataque, as listas de itens (que tem de coincidir com a enumeracao real), e
os dois casos de *jobs*, que nao precisam de nada.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from isolamento import enumeracao
from isolamento.baterias import c01_contacto, jobs_filas, x01_rotas, x02_tools
from isolamento.contexto import Contexto

RAIZ = Path(__file__).resolve().parents[3]


class TestUniformidade(unittest.TestCase):
    """A uniformidade e o que distingue uma recusa de um oraculo de existencia."""

    def test_estados_iguais_e_de_recusa_passam(self) -> None:
        self.assertEqual(x01_rotas._uniformidade("r", [404, 404, 404]), [])

    def test_estados_diferentes_sao_achado(self) -> None:
        achados = x01_rotas._uniformidade("r", [403, 404])
        self.assertEqual(len(achados), 1)
        self.assertIn("oraculo de existencia", achados[0])

    def test_um_2xx_e_achado_mesmo_sendo_uniforme(self) -> None:
        achados = x01_rotas._uniformidade("r", [200, 200])
        self.assertEqual(len(achados), 1)
        self.assertIn("nao e uma recusa", achados[0])

    def test_um_200_e_um_404_dao_os_dois_achados(self) -> None:
        self.assertEqual(len(x01_rotas._uniformidade("r", [200, 404])), 2)


class TestOsArgumentosDeAtaque(unittest.TestCase):
    """Os argumentos derivam do **esquema**, para uma tool nova ser atacada sozinha."""

    class _Oraculo:
        def __init__(self) -> None:
            self.proibidos = {"t": "canario_b_" + "0" * 32}

    class _Tenant:
        id = "22222222-2222-2222-2222-222222222222"

    def contexto(self) -> Contexto:
        return Contexto(b=self._Tenant(), oraculo=self._Oraculo())

    def test_um_esquema_sem_campos_da_um_ataque_vazio(self) -> None:
        self.assertEqual(
            x02_tools._argumentos_de_b(self.contexto(), {"properties": {}}),
            [{}],
        )

    def test_um_campo_de_texto_recebe_o_canario_e_o_tenant(self) -> None:
        tentativas = x02_tools._argumentos_de_b(
            self.contexto(), {"properties": {"sku": {"type": "string"}}}
        )
        valores = {tentativa["sku"] for tentativa in tentativas}
        self.assertIn("canario_b_" + "0" * 32, valores)
        self.assertIn(self._Tenant.id, valores)

    def test_os_campos_que_nao_sao_texto_levam_valores_validos(self) -> None:
        tentativas = x02_tools._argumentos_de_b(
            self.contexto(),
            {
                "properties": {
                    "sku": {"type": "string"},
                    "qty": {"type": "integer"},
                    "tudo": {"type": "boolean"},
                    "itens": {"type": "array"},
                }
            },
        )
        self.assertTrue(tentativas)
        for tentativa in tentativas:
            self.assertIsInstance(tentativa["qty"], int)
            self.assertIs(tentativa["tudo"], True)
            self.assertEqual(tentativa["itens"], [])

    def test_sem_esquema_tambem_se_invoca(self) -> None:
        """Uma entrada `declarada` nao tem modelo, e tem de ser invocada."""
        self.assertEqual(x02_tools._argumentos_de_b(self.contexto(), None), [{}])


class TestAsListasCoincidemComAEnumeracao(unittest.TestCase):
    """Uma lista literal que divirja da enumeracao e um caso morto a nascer.

    A cobertura ja o apanharia — um `enumeravel` que a enumeracao nao encontra e
    um caso morto —, mas apanha-o com uma mensagem sobre um identificador. Estes
    testes dizem **qual** lista e que divergiu, que e o que poupa a busca.
    """

    def setUp(self) -> None:
        self.itens = {item.id for item in enumeracao.enumerar(RAIZ)}

    def test_as_rotas_do_agr(self) -> None:
        for item in x01_rotas.ROTAS_INTERNAS_DO_AGR + x01_rotas.SONDA_DO_AGR:
            with self.subTest(item=item):
                self.assertIn(item, self.itens)

    def test_as_rotas_de_typescript(self) -> None:
        declaradas = (
            x01_rotas.SONDAS_TS + x01_rotas.WEBHOOK_DO_GWY + x01_rotas.CANAIS_DO_GWY
        )
        enumeradas = {
            item for item in self.itens if item.startswith("rota:")
        } - set(x01_rotas.ROTAS_INTERNAS_DO_AGR) - set(x01_rotas.SONDA_DO_AGR)
        self.assertEqual(set(declaradas), enumeradas)

    def test_as_onze_tools(self) -> None:
        declaradas = set(x02_tools.TOOLS_LIGADAS) | set(x02_tools.TOOLS_DECLARADAS)
        self.assertEqual(
            declaradas, {item for item in self.itens if item.startswith("tool:")}
        )

    def test_as_quatro_filas(self) -> None:
        declaradas = set(jobs_filas.FILAS_NOMEADAS) | set(jobs_filas.FILAS_DE_EVENTO)
        self.assertEqual(
            declaradas, {item for item in self.itens if item.startswith("job:")}
        )

    def test_as_tres_leituras_do_contacto(self) -> None:
        for mapa in (
            c01_contacto.TABELA_DA_LEITURA,
            c01_contacto.MARCA_DA_LEITURA,
            c01_contacto.SQL_DA_LEITURA,
        ):
            with self.subTest(mapa=sorted(mapa)):
                self.assertEqual(set(c01_contacto.LEITURAS), set(mapa))


class TestAFixacaoDasCotacoes(unittest.TestCase):
    """A fixacao e sobre o que a leitura devolveu, nao sobre o texto do SQL.

    A revisao adversarial mostrou a cadeia que a versao por texto permitia: o
    KAM-043 acrescenta `contact_id` a **projeccao** (sem predicado), a fixacao
    anuncia «o credor pagou a divida», quem le tira a leitura de
    `SEM_PREDICADO_DE_CONTACTO`, e a asserção que passa a correr fica verde por
    outra razao. Estas tres baterias fecham as tres direccoes.
    """

    X = "11111111-1111-1111-1111-111111111111"
    Y = "22222222-2222-2222-2222-222222222222"

    def fixar(self, texto_de_x: str) -> list[str]:
        return c01_contacto._fixacao_das_cotacoes(
            Contexto(raiz=RAIZ), "cotacoes", texto_de_x, self.X, self.Y
        )

    def test_a_leitura_de_x_a_devolver_y_e_o_estado_fixado(self) -> None:
        """Hoje: com o `(sku, qty)` partilhado, X recebe a linha de Y."""
        self.assertEqual(self.fixar(f'{{"id":"{self.Y}"}}'), [])

    def test_a_leitura_de_x_a_devolver_x_avisa_e_diz_o_que_fazer(self) -> None:
        """O predicado apareceu: o caso fica vermelho e nomeia o credor."""
        achados = self.fixar(f'{{"id":"{self.X}"}}')
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("KAM-043", achados[0])
        self.assertIn("SEM_PREDICADO_DE_CONTACTO", achados[0])

    def test_uma_leitura_vazia_e_achado_e_nao_silencio(self) -> None:
        """Sem nenhuma das duas marcas, a bateria nao mediu nada."""
        achados = self.fixar('{"id":null}')
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("nao mediu nada", achados[0])


class TestOSkuPartilhado(unittest.TestCase):
    """O `(sku, qty)` tem de ser o mesmo nos dois contactos, ou o cenario nao ocorre."""

    def test_a_semente_partilha_o_sku_e_a_qty(self) -> None:
        from isolamento import semente  # noqa: PLC0415

        self.assertTrue(semente.SKU_PARTILHADO)
        self.assertEqual(semente.QTY_PARTILHADA, 1)

    def test_a_marca_das_cotacoes_e_o_id_e_nao_o_canario(self) -> None:
        """Com o `sku` partilhado, o canario naquela coluna nao distinguia nada."""
        self.assertEqual(c01_contacto.MARCA_DA_LEITURA["cotacoes"], "id")
        self.assertEqual(
            semente_coluna_do_canario()[("platform", "price_quotes")], "id"
        )


def semente_coluna_do_canario() -> dict:
    from isolamento.semente import COLUNA_DO_CANARIO  # noqa: PLC0415

    return COLUNA_DO_CANARIO


class TestOsConsumidoresDoEvt(unittest.TestCase):
    """As marcas de consumo usam os `consumer` **reais**, ou a contagem e vazia."""

    def test_os_consumidores_da_semente_sao_os_que_a_enumeracao_encontra(self) -> None:
        from isolamento import semente  # noqa: PLC0415

        enumerados = {
            item.id.split(":")[1] for item in enumeracao.consumidores(RAIZ)
        }
        self.assertEqual(set(semente.CONSUMIDORES), enumerados)


if __name__ == "__main__":
    unittest.main()
