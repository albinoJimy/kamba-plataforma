"""As partes das baterias que se medem sem base de dados e sem `node`.

O `fn` de um caso de X-03 ou de C-01 so faz sentido contra um PostgreSQL, e e
no *gate* 6 que corre. O que **se** mede aqui e o que decide se esses casos
estao certos antes de chegarem la: a uniformidade, a construcao dos argumentos
de ataque, as listas de itens (que tem de coincidir com a enumeracao real), e
os dois casos de *jobs*, que nao precisam de nada.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from isolamento import enumeracao
from isolamento.baterias import c01_contacto, jobs_filas, x01_rotas, x02_tools
from isolamento.contexto import Contexto
from isolamento.oraculo import Oraculo

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
        # O `METRICAS_DO_AGR` entrou com o KAM-080, que deu ao AGR a rota
        # `/metrics` que ele nao tinha.
        for item in (
            x01_rotas.ROTAS_INTERNAS_DO_AGR
            + x01_rotas.SONDA_DO_AGR
            + x01_rotas.METRICAS_DO_AGR
        ):
            with self.subTest(item=item):
                self.assertIn(item, self.itens)

    def test_as_rotas_de_typescript(self) -> None:
        declaradas = (
            x01_rotas.SONDAS_TS
            + x01_rotas.WEBHOOK_DO_GWY
            + x01_rotas.CANAIS_DO_GWY
            + x01_rotas.ROTAS_DA_API_INTERNA_DO_COM
            + x01_rotas.ROTAS_DA_INSCRICAO
            + x01_rotas.ROTAS_DO_GUIA
            + x01_rotas.ROTAS_DO_PAINEL
        )
        # **As tres listas do AGR subtraem-se, e nao duas.** O conjunto de
        # TypeScript deriva-se por subtraccao, pelo que uma lista nova do AGR
        # que nao entre aqui aparece como uma rota de TypeScript que ninguem
        # declarou — foi o que aconteceu ao acrescentar a `/metrics` do AGR, e
        # a mensagem do teste apontava para o lado errado.
        enumeradas = (
            {item for item in self.itens if item.startswith("rota:")}
            - set(x01_rotas.ROTAS_INTERNAS_DO_AGR)
            - set(x01_rotas.SONDA_DO_AGR)
            - set(x01_rotas.METRICAS_DO_AGR)
        )
        self.assertEqual(set(declaradas), enumeradas)

    def test_as_onze_superficies_da_api_interna_do_com(self) -> None:
        """As onze (KAM-178 e KAM-099) sao **exactamente** as que a enumeracao da ao COM.

        A lista de cima ja apanharia uma divergencia, mas apanha-a somada as
        outras tres. Esta diz o que importa dizer: no dia em que uma decima rota
        entrar na constante `ROTAS` de `services/com/src/api/interna.ts`, e este
        ensaio que fica vermelho e nomeia o sitio.
        """
        do_com = {item for item in self.itens if item.startswith("rota:com:")}
        # As sondas do COM pertencem ao caso das sondas, nao a este. Sao **tres**
        # desde o KAM-055: o processo do consumidor de pagamentos serve o seu
        # proprio `/healthz` e `/metrics`, numa `criarApp` de
        # `payments/arranque.ts`.
        #
        # **Literais e nao filtradas do `SONDAS_TS`**, pela doutrina que aquele
        # ficheiro escreve: derivar esta lista da outra fazia uma sonda nova do
        # COM nascer coberta aqui. Quem apanha a divergencia entre a enumeracao
        # e a lista declarada e o `test_as_rotas_de_typescript`; o que este
        # ensaio prende e as **onze** superficies da API interna.
        esperadas = set(x01_rotas.ROTAS_DA_API_INTERNA_DO_COM) | {
            "rota:com:app:createApp:GET:/healthz",
            "rota:com:payments/arranque:criarApp:GET:/healthz",
            "rota:com:payments/arranque:criarApp:GET:/metrics",
        }
        self.assertEqual(do_com, esperadas)
        self.assertEqual(len(x01_rotas.ROTAS_DA_API_INTERNA_DO_COM), 11)
        self.assertEqual(len(set(x01_rotas.ROTAS_DA_API_INTERNA_DO_COM)), 11)

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


class TestOsAceitaveisPorItem(unittest.TestCase):
    """Os onze itens do COM nao respondem todos a mesma coisa.

    O `GET /metrics` responde **200** e o `ALL /internal/*` responde **503**; as
    nove `POST /internal/*` respondem recusa. A sobreposicao e por item, e e
    isso que estes dois canarios fixam: alargar o `RECUSAS_ACEITAVEIS` global
    para acomodar o 200 fazia **todos** os outros casos deixar de apanhar um 200
    a um identificador de outro tenant, que e a falha que a bateria existe para
    apanhar.
    """

    CANARIO = "canario_b_" + "0" * 32

    def entrada(self, item: str, estado: int) -> dict:
        return {
            "item": item,
            "estado": estado,
            "corpo": "{}",
            "cabecalhos": {},
            "executado": True,
            "nota": "",
        }

    def relatorio(self, estados: dict[str, int]) -> dict:
        """Um relatorio de ensaio com as nove superficies, tres ataques cada.

        O `/metrics` leva uma entrada so, como o condutor o reporta. Os estados
        de omissao sao os que o grupo mede hoje; `estados` sobrepoe-nos.
        """
        omissao = {
            **{item: 404 for item in x01_rotas.ROTAS_POST_DA_API_INTERNA_DO_COM},
            x01_rotas.ITEM_DAS_METRICAS_DO_COM: 200,
            x01_rotas.ITEM_SEM_API_DO_COM: 503,
        }
        rotas = []
        for item, estado in {**omissao, **estados}.items():
            vezes = 1 if item == x01_rotas.ITEM_DAS_METRICAS_DO_COM else 3
            rotas.extend(self.entrada(item, estado) for _ in range(vezes))
        return {"rotas": rotas, "contacto": []}

    def achados(self, estados: dict[str, int]) -> list[str]:
        # Sem `afirmacoes`: o que este ensaio mede e a tabela de estados, e as
        # marcas da `nota` tem canario proprio nos ensaios do condutor.
        fn = x01_rotas._caso_ts(
            "com-interna",
            x01_rotas.ROTAS_DA_API_INTERNA_DO_COM,
            com_idor=True,
            aceitaveis_por_item=x01_rotas.ACEITAVEIS_DA_API_INTERNA_DO_COM,
        )
        relatorio = self.relatorio(estados)
        return fn(
            Contexto(
                raiz=RAIZ,
                oraculo=Oraculo({"tenant_id": self.CANARIO}),
                node=lambda _grupo: relatorio,
            )
        )

    def test_o_metrics_a_200_nao_da_achado(self) -> None:
        self.assertEqual(self.achados({}), [])

    def test_uma_rota_post_a_200_da_achado(self) -> None:
        alvo = x01_rotas.ROTAS_POST_DA_API_INTERNA_DO_COM[3]
        achados = self.achados({alvo: 200})
        self.assertEqual(len(achados), 1, achados)
        self.assertIn(alvo, achados[0])
        self.assertIn("nao e uma recusa", achados[0])

    def test_o_metrics_a_404_da_achado(self) -> None:
        """O 200 do `/metrics` e o estado dele, nao uma excepcao de conveniencia."""
        achados = self.achados({x01_rotas.ITEM_DAS_METRICAS_DO_COM: 404})
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("nao mediu o que diz medir", achados[0])

    def test_a_sobreposicao_nao_toca_nos_outros_casos(self) -> None:
        """O `RECUSAS_ACEITAVEIS` global continua sem o 200."""
        self.assertNotIn(200, x01_rotas.RECUSAS_ACEITAVEIS)
        self.assertNotIn(200, x01_rotas.ESTADOS_DOS_CANAIS)


class TestAsMarcasDaApiInternaDoCom(unittest.TestCase):
    """As medicoes que vem na `nota` do condutor, e que o oraculo nao ve.

    O `ctx` com que a porta foi chamada mede-se em `node` e viaja numa marca;
    sem estes canarios, uma marca que deixasse de ser escrita passava a nao ser
    exigida — e a afirmacao central do caso ficava verde por nao vir.
    """

    POST = x01_rotas.ROTAS_POST_DA_API_INTERNA_DO_COM[0]
    CONFORME = (
        "ctx=a sonda=viva fecho-sem-credencial=401 fecho-sem-tenant=400 "
        "ids-de-b=tenant-b canario-de-b=presente"
    )

    def entradas(self, nota: str, quantas: int = 3) -> list[dict]:
        return [{"nota": nota} for _ in range(quantas)]

    def afirmar(self, item: str, entradas: list[dict]) -> list[str]:
        return x01_rotas._afirmacoes_da_api_interna_do_com(item, entradas)

    def test_as_marcas_conformes_nao_dao_achado(self) -> None:
        self.assertEqual(self.afirmar(self.POST, self.entradas(self.CONFORME)), [])

    def test_o_ctx_deslocado_e_achado(self) -> None:
        nota = self.CONFORME.replace("ctx=a", "ctx=outro-tenant")
        achados = self.afirmar(self.POST, self.entradas(nota))
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("afirmacao central", achados[0])

    def test_uma_marca_em_falta_e_achado_e_nao_silencio(self) -> None:
        """Uma afirmacao que nao veio e uma afirmacao nao medida."""
        achados = self.afirmar(self.POST, self.entradas(""))
        self.assertEqual(len(achados), 6, achados)
        for achado in achados:
            self.assertIn("(em falta)", achado)

    def test_a_sonda_morta_e_achado(self) -> None:
        nota = self.CONFORME.replace("sonda=viva", "sonda=sem-chamada")
        achados = self.afirmar(self.POST, self.entradas(nota))
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("sonda positiva", achados[0])

    def test_um_ataque_a_menos_e_achado(self) -> None:
        achados = self.afirmar(self.POST, self.entradas(self.CONFORME, quantas=2))
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("3 ataques", achados[0])

    def test_as_metricas_sobre_populacao_vazia_sao_achado(self) -> None:
        """«Sem rotulo por tenant» passa sobre uma serie a zero: e o achado do KAM-178."""
        entradas = [{"nota": "metricas=limpa series=a-zero contadores=subidos"}]
        achados = self.afirmar(x01_rotas.ITEM_DAS_METRICAS_DO_COM, entradas)
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("populacao vazia", achados[0])

    def test_o_corpo_que_distingue_tenants_sem_api_e_achado(self) -> None:
        entradas = self.entradas("sem-api=corpos-distintos-3")
        achados = self.afirmar(x01_rotas.ITEM_SEM_API_DO_COM, entradas)
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("distingue tenants", achados[0])


class TestAPonteEOCondutorConcordam(unittest.TestCase):
    """Um grupo que so exista num dos lados e um caso que nunca corre."""

    def test_os_grupos_do_condutor_sao_os_da_ponte(self) -> None:
        from isolamento.condutor import ponte  # noqa: PLC0415

        guiao = (RAIZ / ponte.GUIAO).read_text(encoding="utf-8")
        inicio = guiao.index("const GRUPOS: Record<")
        corpo = guiao[inicio : guiao.index("};", inicio)]
        no_condutor = set(re.findall(r'^\s*"?([a-z-]+)"?:\s*grupo', corpo, re.M))
        self.assertEqual(no_condutor, set(ponte.GRUPOS))


class TestAFixacaoDasCotacoes(unittest.TestCase):
    """A fixacao e sobre o que a leitura devolveu, nao sobre o texto do SQL.

    A revisao adversarial mostrou a cadeia que a versao por texto permitia: um
    ticket acrescenta `contact_id` a **projeccao** (sem predicado), a fixacao
    anuncia «o credor pagou a divida», quem le tira a leitura de
    `SEM_PREDICADO_DE_CONTACTO`, e a asserção que passa a correr fica verde por
    outra razao. Estas tres baterias fecham as tres direccoes.

    **O mecanismo deixou de estar em uso e os ensaios ficam**, porque o
    `SEM_PREDICADO_DE_CONTACTO` continua a existir para a proxima divida: o
    KAM-179 pagou a das cotacoes, e o dia em que outra leitura por contacto
    nascer sem predicado e o dia em que isto volta a correr. Um ensaio apagado
    com o uso e um mecanismo que ninguem verifica quando voltar.
    """

    X = "11111111-1111-1111-1111-111111111111"
    Y = "22222222-2222-2222-2222-222222222222"

    def fixar(self, texto_de_x: str) -> list[str]:
        # **O credor injecta-se, porque o dicionario esta vazio.** O KAM-179
        # pagou a divida das cotacoes e o `SEM_PREDICADO_DE_CONTACTO` ficou sem
        # entradas; o mecanismo fica, e estes ensaios verificam-no com uma
        # entrada de ensaio. Sem a injeccao, eles levantavam `KeyError` e a
        # tentacao era apaga-los — o que deixava o mecanismo sem canario para o
        # dia em que a proxima leitura por contacto nascer sem predicado.
        c01_contacto.SEM_PREDICADO_DE_CONTACTO["cotacoes"] = "KAM-179"
        self.addCleanup(
            c01_contacto.SEM_PREDICADO_DE_CONTACTO.pop, "cotacoes", None
        )
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
