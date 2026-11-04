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
    """A leitura de cotacoes nao filtra por contacto, e isso esta fixado.

    O que esta bateria tem de garantir e o aviso: no dia em que o predicado
    aparecer, o caso fica **vermelho** e obriga quem o acrescentou a trocar a
    fixacao pela propriedade do criterio 6. Um comentario nao faz isso.
    """

    def test_hoje_a_arvore_real_nao_tem_o_predicado(self) -> None:
        self.assertEqual(
            c01_contacto._cotacoes_sem_predicado(Contexto(raiz=RAIZ), "cotacoes"),
            [],
            "a `SQL_COTACAO_VALIDA` passou a filtrar por contacto: tire "
            "'cotacoes' de SEM_PREDICADO_DE_CONTACTO e afirme a propriedade",
        )

    def test_com_o_predicado_a_fixacao_avisa(self) -> None:
        import tempfile  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            relativo, constante = c01_contacto.SQL_DA_LEITURA["cotacoes"]
            caminho = raiz / relativo
            caminho.parent.mkdir(parents=True)
            caminho.write_text(
                f"export const {constante} = `\n"
                "  SELECT id FROM platform.price_quotes\n"
                "   WHERE tenant_id = $1 AND contact_id = $2\n"
                "`;\n",
                encoding="utf-8",
            )
            achados = c01_contacto._cotacoes_sem_predicado(
                Contexto(raiz=raiz), "cotacoes"
            )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("KAM-043", achados[0])
        self.assertIn("SEM_PREDICADO_DE_CONTACTO", achados[0])

    def test_um_sql_que_desapareca_e_achado(self) -> None:
        import tempfile  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as temporario:
            achados = c01_contacto._cotacoes_sem_predicado(
                Contexto(raiz=Path(temporario)), "cotacoes"
            )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn("nao existe", achados[0])


class TestOsCasosDeFilas(unittest.TestCase):
    """Os dois casos que correm no passo a seco do *gate* 6."""

    def test_as_filas_nomeadas_passam_na_arvore_real(self) -> None:
        self.assertEqual(jobs_filas._nomeadas(Contexto(raiz=RAIZ)), [])

    def test_as_filas_de_evento_passam_na_arvore_real(self) -> None:
        self.assertEqual(jobs_filas._de_evento(Contexto(raiz=RAIZ)), [])

    def test_a_entrada_nao_pode_levar_tenant_id(self) -> None:
        """O canario do caso: o campo proibido na `wa-inbound` e o `tenant_id`.

        E a assimetria que a primeira versao do caso nao tinha — exigia
        `tenant_id` nas duas filas, e a `wa-inbound` ficou vermelha com razao: o
        CHR e o unico ponto que mapeia `phone_number_id -> tenant`
        (`docs/tecnica/08` §3.1), e o *job* da entrada e **antes** dele.
        """
        _, _, exigido, proibido = jobs_filas.CONTRATO_DA_FILA["job:wa-inbound"]
        self.assertEqual(exigido, "phone_number_id")
        self.assertEqual(proibido, "tenant_id")
        _, _, exigido_do_agr, proibido_do_agr = jobs_filas.CONTRATO_DA_FILA[
            "job:agr-inbound"
        ]
        self.assertEqual(exigido_do_agr, "tenant_id")
        self.assertIsNone(proibido_do_agr)

    def test_um_contrato_que_desapareca_e_achado(self) -> None:
        import tempfile  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as temporario:
            achados = jobs_filas._nomeadas(Contexto(raiz=Path(temporario)))
        self.assertEqual(len(achados), 2, achados)
        self.assertTrue(all("nao existe" in achado for achado in achados))


if __name__ == "__main__":
    unittest.main()
