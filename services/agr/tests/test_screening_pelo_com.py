"""A ponte Python -> TypeScript do `screen` do KAM-088 (KAM-222).

O adaptador `ScreeningPeloCom` com um transporte em duplo: o que vai ao COM, o
que se le da resposta, e o que levanta. O lado TypeScript da rota (a validacao
do corpo e o `screen` real com a politica) e medido em
`services/com/tests/screening.test.ts` e `services/com/tests/api.interna.test.ts`.
O que liga os dois lados aqui e o contrato por texto: a rota e os quatro campos
do corpo tem de ser os que o `api/interna.ts` le.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from kamba_agr.tls.com import CABECALHO_INTERNO, CABECALHO_TENANT, ClienteDoCom, RespostaDoCom
from kamba_core.catalogo.screening import REGRA_REVISAO_PENDENTE, categoria_restrita
from kamba_agr.tls.screening import (
    ROTA,
    SUJEITOS,
    ScreeningIndisponivelError,
    ScreeningPeloCom,
)
from kamba_core.catalogo.screening import PortaDeScreening, ResultadoDoScreen

RAIZ = Path(__file__).resolve().parents[3]
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
QUOTE = "0000000a-0000-4000-8000-00000000000a"
TEXTO = "entrega combinada consigo, cerveja gelada"

VALOR_OK = {"decisao": "permitida", "regras": ["moda"], "versao_politica": "2026.11.0", "confianca": 0.95}


class Transporte:
    """Regista cada chamada e devolve a resposta dada, ou levanta."""

    def __init__(self, resposta: RespostaDoCom | Exception) -> None:
        self.resposta = resposta
        self.chamadas: list[tuple[str, dict, dict, float]] = []

    def __call__(self, url, cabecalhos, corpo, timeout):  # noqa: ANN001
        self.chamadas.append((url, cabecalhos, corpo, timeout))
        if isinstance(self.resposta, Exception):
            raise self.resposta
        return self.resposta


def adaptador(resposta: RespostaDoCom | Exception, sujeito: str = "condicoes") -> tuple[ScreeningPeloCom, Transporte]:
    transporte = Transporte(resposta)
    cliente = ClienteDoCom(base="http://com:3002/", credencial=lambda: "c", transporte=transporte)
    return ScreeningPeloCom(cliente=cliente, sujeito_tipo=sujeito, vertical="dono"), transporte


class TestOPedido(unittest.TestCase):
    def test_e_uma_porta_de_screening(self) -> None:
        porta, _ = adaptador(RespostaDoCom(200, {"tipo": "ok", "valor": VALOR_OK}))
        self.assertIsInstance(porta, PortaDeScreening)

    def test_vai_a_rota_com_os_dois_cabecalhos_e_o_corpo(self) -> None:
        porta, transporte = adaptador(RespostaDoCom(200, {"tipo": "ok", "valor": VALOR_OK}), "condicoes")
        resultado = porta.screen(TENANT, QUOTE, None, [TEXTO])
        self.assertEqual(
            resultado,
            ResultadoDoScreen(decisao="permitida", regras=("moda",), versao_politica="2026.11.0", confianca=0.95),
        )
        (url, cabecalhos, corpo, timeout), = transporte.chamadas
        self.assertEqual(url, "http://com:3002/internal/screen")
        self.assertEqual(cabecalhos[CABECALHO_INTERNO], "c")
        self.assertEqual(cabecalhos[CABECALHO_TENANT], TENANT)
        self.assertEqual(corpo["sujeito_tipo"], "condicoes")
        self.assertEqual(corpo["sujeito_ref"], QUOTE)
        # `None` vai como `null`: o COM usa a categoria declarada do tenant.
        self.assertIsNone(corpo["categoria_declarada"])
        self.assertEqual(corpo["textos"], [TEXTO])
        self.assertEqual(corpo["actor"], {"kind": "agente", "id": "grafo-dono"})
        self.assertRegex(corpo["trace_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(timeout, 20.0)

    def test_so_as_condicoes_e_o_produto_se_montam(self) -> None:
        # A `categoria` mudava a do tenant (nota do `screening/index.ts` do COM).
        # O `produto` abriu com o KAM-119, quando a re-analise passou a comparar
        # o `conteudo_sha256`.
        for sujeito in ("categoria", "outro", ""):
            with self.subTest(sujeito=sujeito):
                with self.assertRaises(ValueError):
                    adaptador(RespostaDoCom(200, {}), sujeito)
        for sujeito in ("condicoes", "produto"):
            with self.subTest(sujeito=sujeito):
                adaptador(RespostaDoCom(200, {}), sujeito)


class TestOProduto(unittest.TestCase):
    """KAM-119: no `produto`, o `publicavel` do COM decide se a `permitida` vale."""

    def test_uma_permitida_publicavel_passa(self) -> None:
        porta, transporte = adaptador(
            RespostaDoCom(200, {"tipo": "ok", "valor": {**VALOR_OK, "publicavel": True}}), "produto"
        )
        resultado = porta.screen(TENANT, "cat-0123", None, ["Camisa polo"])
        self.assertEqual(resultado.decisao, "permitida")
        self.assertEqual(transporte.chamadas[0][2]["sujeito_tipo"], "produto")

    def test_uma_permitida_nao_publicavel_chega_condicional_com_a_revisao_pendente(self) -> None:
        porta, _ = adaptador(RespostaDoCom(200, {"tipo": "ok", "valor": {**VALOR_OK, "publicavel": False}}), "produto")
        resultado = porta.screen(TENANT, "cat-0123", None, ["Camisa polo"])
        self.assertEqual((resultado.decisao, resultado.regras[-1]), ("condicional", REGRA_REVISAO_PENDENTE))
        # E a razao que a ingestao guarda, e nao a categoria que passou.
        self.assertEqual(categoria_restrita(resultado), REGRA_REVISAO_PENDENTE)

    def test_sem_o_publicavel_o_produto_fecha(self) -> None:
        for valor in ({**VALOR_OK}, {**VALOR_OK, "publicavel": "sim"}, {**VALOR_OK, "publicavel": 1}):
            with self.subTest(valor=valor):
                porta, _ = adaptador(RespostaDoCom(200, {"tipo": "ok", "valor": valor}), "produto")
                with self.assertRaises(ScreeningIndisponivelError):
                    porta.screen(TENANT, "cat-0123", None, ["Camisa polo"])

    def test_as_condicoes_nao_pedem_o_publicavel(self) -> None:
        porta, _ = adaptador(RespostaDoCom(200, {"tipo": "ok", "valor": VALOR_OK}), "condicoes")
        self.assertEqual(porta.screen(TENANT, QUOTE, None, [TEXTO]).decisao, "permitida")


class TestFalhaFechada(unittest.TestCase):
    """Tudo o que nao seja um 200 com a forma fechada levanta, e sem o texto."""

    CASOS = {
        "400 do COM (o sujeito ainda fora do CHECK, ou corpo invalido)": RespostaDoCom(
            400, {"tipo": "erro", "erro": "VALIDATION_ERROR"}
        ),
        "503 do COM (o escritor falhou)": RespostaDoCom(503, {"tipo": "erro", "erro": "UPSTREAM_DOWN"}),
        "401 (credencial)": RespostaDoCom(401, {"error": "unauthorized"}),
        "timeout": TimeoutError("lento"),
        "200 sem valor": RespostaDoCom(200, {"tipo": "ok"}),
        "decisao fora do dominio": RespostaDoCom(200, {"tipo": "ok", "valor": {**VALOR_OK, "decisao": "aprovada"}}),
        "regra que nao e cadeia": RespostaDoCom(200, {"tipo": "ok", "valor": {**VALOR_OK, "regras": [1]}}),
        "sem versao": RespostaDoCom(200, {"tipo": "ok", "valor": {**VALOR_OK, "versao_politica": ""}}),
        "confianca booleana": RespostaDoCom(200, {"tipo": "ok", "valor": {**VALOR_OK, "confianca": True}}),
    }

    def test_cada_caso_levanta_sem_o_texto(self) -> None:
        for nome, resposta in self.CASOS.items():
            with self.subTest(nome):
                porta, _ = adaptador(resposta, "condicoes")
                with self.assertRaises(ScreeningIndisponivelError) as caso:
                    porta.screen(TENANT, QUOTE, None, [TEXTO])
                self.assertNotIn("cerveja", str(caso.exception))
                self.assertNotIn("cerveja", repr(caso.exception))
                self.assertIsNone(caso.exception.__cause__)


class TestOContratoComOTypeScript(unittest.TestCase):
    """A rota e os campos do corpo sao os que o `api/interna.ts` le."""

    def setUp(self) -> None:
        self.interna = (RAIZ / "services/com/src/api/interna.ts").read_text(encoding="utf-8")

    def test_a_rota_esta_nas_rotas_do_com(self) -> None:
        bloco = re.search(r"export const ROTAS = \[(.*?)\] as const;", self.interna, re.S)
        self.assertIsNotNone(bloco)
        self.assertIn(f'"{ROTA}"', bloco.group(1))

    def test_os_quatro_campos_sao_os_que_a_rota_le(self) -> None:
        funcao = re.search(r"function pedidoDeScreenDoCorpo\(.*?\n}\n", self.interna, re.S)
        self.assertIsNotNone(funcao)
        for campo in ("sujeito_tipo", "sujeito_ref", "categoria_declarada", "textos"):
            self.assertIn(f'corpo["{campo}"]', funcao.group(0), campo)

    def test_o_sujeito_do_adaptador_e_o_do_com(self) -> None:
        # KAM-119: o `produto` abriu com a re-analise a comparar o conteudo.
        # KAM-121: o `conteudo` do social (decisao 1 do bloco).
        self.assertEqual(SUJEITOS, ("condicoes", "produto", "conteudo"))
        indice = (RAIZ / "services/com/src/screening/index.ts").read_text(encoding="utf-8")
        self.assertIn('export const SUJEITO_DAS_CONDICOES = "condicoes";', indice)
        self.assertIn('export const SUJEITO_DO_PRODUTO = "produto";', indice)
        self.assertIsNotNone(re.search(r"SUJEITOS_DA_ROTA[^;]*SUJEITO_DO_PRODUTO", indice, re.S))
        self.assertIn('export const SUJEITO_DO_CONTEUDO = "conteudo";', indice)
        self.assertIsNotNone(re.search(r"SUJEITOS_DA_ROTA[^;]*SUJEITO_DO_CONTEUDO", indice, re.S))


if __name__ == "__main__":
    unittest.main()
