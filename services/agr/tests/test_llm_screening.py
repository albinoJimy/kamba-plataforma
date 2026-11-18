"""O classificador de screening do GOV pelo cliente do AGR (KAM-195), criterio 1.

Tres coisas, e cada classe tem o seu canario:

* **sem destino autorizado para a `classificacao_de_catalogo`, nada sai e a
  linha grava-se** — o fornecedor tem `conversa` autorizada e nao a finalidade
  do screening, que e o caso que separa as duas. Canario: o controlo `router`
  do mesmo cliente, que sai; sem ele, um transporte partido passava o «nada
  sai»;
* **com o destino autorizado, a chamada passa o *gate* e a linha leva o custo**
  — a finalidade e a real (`FINALIDADE_DO_PAPEL`, KAM-195, criterio 2) e a
  porta e a do nucleo (`PortaSobreDestinos`); so o leitor da tabela e um duplo.
  O resto e o caminho de producao: o `ClienteDeLlm`, o `minimise`, a tabela de
  precos e o registo;
* **a rota** autentica antes de ler o corpo, le-o por forma fechada com o tecto
  do contrato, nao chama o modelo quando ja nao ha tempo, e nunca devolve 200
  sem texto.

E o arranque (`TestALigacaoDoArranque`): a credencial e a chave que o
`__main__` liga, que os ensaios da rota nao veem porque as injectam.

E dois ensaios de paridade com o TypeScript, que leem o `classificador.ts`: o
orcamento de tempo do GOV tem de caber as duas tentativas do proxy, e os tectos
do pedido sao os mesmos dos dois lados.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import unittest
from decimal import Decimal
from typing import Any

from apoio import pedir
from kamba_agr import metricas as metricas_mod
from kamba_agr.app import create_app
from kamba_agr.llm import aliases as aliases_mod
from kamba_agr.llm import destinos as destinos_mod
from kamba_agr.llm import precos as precos_mod
from kamba_agr.llm import screening
from kamba_agr.llm.cliente import ClienteDeLlm
from kamba_agr.llm.erros import RESULTADO_DESTINO, RESULTADO_OK, DestinoNegado
from kamba_core.destinos import FINALIDADE_CLASSIFICACAO, FINALIDADE_CONVERSA
from kamba_core.destinos import PortaSobreDestinos
from kamba_yaml import load_file
from test_llm_cliente import _Ligacao, _Transporte

RAIZ = pathlib.Path(__file__).resolve().parents[3]
REAIS = aliases_mod.ler(RAIZ / "llm")

TENANT = "22222222-2222-2222-2222-222222222222"
TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"

#: O alias real do papel, com um modelo inventado (o ficheiro diz `por_decidir`)
#: para a tabela de precos ter linha. O `timeout` e o `max_tokens` sao os do
#: ficheiro: sao eles que o tecto e o corpo leem.
ALIAS = aliases_mod.Alias(
    nome=REAIS["screening"].nome,
    papel="screening",
    timeout=REAIS["screening"].timeout,
    fornecedores=("anthropic",),
    modelos=("claude-haiku-5-5",),
    max_tokens=REAIS["screening"].max_tokens,
)
ROUTER = aliases_mod.Alias(
    "kamba-router", "router", 8, ("anthropic",), ("claude-haiku-5-5",), 16
)
PRECOS = {
    ("anthropic", "claude-haiku-5-5"): precos_mod.Preco(
        "anthropic", "claude-haiku-5-5",
        Decimal("0.10"), Decimal("0.01"), Decimal("0.50"), "CONFIRMADO", "E4 3.1",
    ),
}

PEDIDO = screening.PedidoDeScreening(
    tenant_id=TENANT,
    trace_id=TRACE,
    categoria_declarada="moda",
    textos=("camisola de algodao", "liga 999000111 para encomendar"),
)


#: Os pares `(fornecedor, finalidade)` com destino autorizado e `apd_ref`.
SO_CONVERSA = frozenset({("anthropic", FINALIDADE_CONVERSA)})
COM_A_CLASSIFICACAO = SO_CONVERSA | {("anthropic", FINALIDADE_CLASSIFICACAO)}


def _porta(autorizados: frozenset[tuple[str, str]]) -> destinos_mod.PortaDoNucleo:
    """A porta do nucleo, com um leitor que devolve uma linha global por par.

    Um par autorizado devolve uma linha `autorizado` com `apd_ref`; um par fora
    da lista devolve zero linhas — que a porta nega, como «destino nao
    registado». E a mesma forma do `test_llm_destinos.py`.
    """

    def ler(_tenant: str, fornecedor: str, finalidade: str) -> list[dict[str, Any]]:
        if (fornecedor, finalidade) not in autorizados:
            return []
        return [
            {"especifica": False, "status": "autorizado", "tem_apd_ref": True, "country": "US"}
        ]

    return destinos_mod.PortaDoNucleo(PortaSobreDestinos(ler))


def _cliente(
    transporte: _Transporte,
    autorizados: frozenset[tuple[str, str]] = COM_A_CLASSIFICACAO,
) -> tuple[ClienteDeLlm, _Ligacao, Any]:
    lig = _Ligacao()
    met = metricas_mod.MetricasDoAgr()
    cliente = ClienteDeLlm(
        aliases={"screening": ALIAS, "router": ROUTER},
        tabela_de_precos=PRECOS,
        porta_de_destinos=_porta(autorizados),
        abrir_ligacao=lambda: lig,
        chave_virtual=lambda _t: "chave-de-ensaio-do-screening",
        url_do_proxy="http://litellm:4000",
        metricas=met,
        transporte=transporte,
    )
    return cliente, lig, met


def _resposta_do_modelo() -> dict[str, Any]:
    return {
        "model": "anthropic/claude-haiku-5-5",
        "choices": [{"message": {"content": '{"decisao":"permitida","confianca":0.9}'}}],
        "usage": {"prompt_tokens": 400, "completion_tokens": 12},
    }


class TestComODestinoNegado(unittest.TestCase):
    """Sem destino autorizado para a finalidade do screening, o *gate* nega.

    O fornecedor tem a `conversa` autorizada: e isso que prova que a recusa vem
    da finalidade do papel, e nao de o fornecedor estar todo negado.

    Canario: `test_o_controlo_router_sai`. Sem ele, um transporte que nunca
    chamasse nada passava o «nada sai para o proxy».
    """

    def test_a_finalidade_do_papel_e_a_classificacao(self) -> None:
        """A decisao do fundador (2026-11-18): finalidade propria."""
        self.assertEqual(destinos_mod.finalidade_de("screening"), "classificacao_de_catalogo")

    def test_nada_sai_e_grava_a_linha(self) -> None:
        transporte = _Transporte()
        cliente, lig, met = _cliente(transporte, SO_CONVERSA)
        with self.assertRaises(DestinoNegado):
            screening.ClassificadorDeScreening(cliente, ALIAS)(PEDIDO)
        self.assertEqual(transporte.chamadas, [])
        (linha,) = lig.linhas()
        self.assertEqual(linha["papel"], "screening")
        self.assertEqual(linha["resultado"], RESULTADO_DESTINO)
        self.assertEqual(linha["tenant_id"], TENANT)
        self.assertEqual(linha["trace_id"], TRACE)
        self.assertEqual(linha["no_grafo"], screening.NO_DO_GRAFO)
        # O `CHECK llm_call_log_negado_sem_consumo` da `0023`: os quatro nulos.
        for coluna in ("tokens_in", "tokens_out", "tokens_cache", "custo_usd"):
            self.assertIsNone(linha[coluna], coluna)
        self.assertEqual(met.ler().get(metricas_mod.METRICA_LLM_DESTINO_NEGADO), 1)

    def test_o_controlo_router_sai(self) -> None:
        transporte = _Transporte()
        cliente, _, _ = _cliente(transporte, SO_CONVERSA)
        cliente.chamar("router", [], screening_ctx())
        self.assertEqual(len(transporte.chamadas), 1)

    def test_a_rota_responde_503_com_o_resultado(self) -> None:
        transporte = _Transporte()
        cliente, lig, _ = _cliente(transporte, SO_CONVERSA)
        app = _app(screening.ClassificadorDeScreening(cliente, ALIAS))
        estado, _, corpo = _pedir(app, _corpo_valido())
        self.assertEqual(estado, 503)
        self.assertEqual(json.loads(corpo), {"outcome": RESULTADO_DESTINO})
        self.assertEqual(transporte.chamadas, [])
        self.assertEqual(len(lig.linhas()), 1)


def screening_ctx():  # noqa: ANN201 — so para o controlo
    from kamba_agr.llm.cliente import ContextoDeChamada

    return ContextoDeChamada(tenant_id=TENANT, trace_id=TRACE)


class TestComODestinoAutorizado(unittest.TestCase):
    """Com o destino autorizado para a `classificacao_de_catalogo`, a chamada sai.

    Canario: `test_a_linha_leva_o_custo`. Sem a tabela de precos, o custo
    sairia nulo e a linha continuava a existir.
    """

    def _chamar(self) -> tuple[_Transporte, _Ligacao, str]:
        transporte = _Transporte((200, _resposta_do_modelo(), {}))
        cliente, lig, _ = _cliente(transporte)
        texto = screening.ClassificadorDeScreening(cliente, ALIAS)(PEDIDO)
        return transporte, lig, texto

    def test_a_linha_leva_o_custo(self) -> None:
        _, lig, _ = self._chamar()
        (linha,) = lig.linhas()
        self.assertEqual(linha["papel"], "screening")
        self.assertEqual(linha["resultado"], RESULTADO_OK)
        self.assertEqual(linha["tokens_in"], 400)
        self.assertEqual(linha["tokens_out"], 12)
        # 400 x 0,10 / 1M + 12 x 0,50 / 1M = 0,000040 + 0,000006.
        self.assertEqual(linha["custo_usd"], Decimal("0.000046"))

    def test_devolve_o_texto_do_modelo(self) -> None:
        _, _, texto = self._chamar()
        self.assertEqual(texto, '{"decisao":"permitida","confianca":0.9}')

    def test_o_corpo_leva_o_alias_o_esquema_e_o_tecto(self) -> None:
        transporte, _, _ = self._chamar()
        ((url, cabecalhos, corpo, timeout),) = transporte.chamadas
        self.assertTrue(url.endswith("/chat/completions"))
        self.assertEqual(cabecalhos["Authorization"], "Bearer chave-de-ensaio-do-screening")
        self.assertEqual(corpo["model"], "screening-nano")
        self.assertEqual(corpo["max_tokens"], REAIS["screening"].max_tokens)
        self.assertEqual(corpo["temperature"], 0)
        self.assertEqual(corpo["response_format"], screening.ESQUEMA_DA_RESPOSTA)
        self.assertEqual(timeout, screening.tecto_s(ALIAS))

    def test_o_texto_do_produto_vai_como_dado_e_minimizado(self) -> None:
        transporte, _, _ = self._chamar()
        ((_, _, corpo, _),) = transporte.chamadas
        sistema, utilizador = corpo["messages"]
        self.assertEqual(sistema, {"role": "system", "content": screening.INSTRUCOES})
        self.assertNotIn("camisola", sistema["content"])
        self.assertEqual(utilizador["role"], "user")
        dados = json.loads(utilizador["content"])
        self.assertEqual(sorted(dados), ["categoria_declarada", "textos"])
        self.assertIn("camisola de algodao", dados["textos"][0])
        # O telefone passou pelo `minimise` (KAM-112), e o tenant nao vai.
        self.assertNotIn("999000111", utilizador["content"])
        self.assertNotIn(TENANT, utilizador["content"])

    def test_a_rota_devolve_200_com_o_texto(self) -> None:
        transporte = _Transporte((200, _resposta_do_modelo(), {}))
        cliente, lig, _ = _cliente(transporte)
        app = _app(screening.ClassificadorDeScreening(cliente, ALIAS))
        estado, _, corpo = _pedir(app, _corpo_valido())
        self.assertEqual(estado, 200)
        self.assertEqual(
            json.loads(corpo),
            {"outcome": "classificado", "conteudo": '{"decisao":"permitida","confianca":0.9}'},
        )
        self.assertEqual(len(lig.linhas()), 1)


class TestOCorpoExtraEFechado(unittest.TestCase):
    """O `corpo_extra` nao reescreve o alias nem as mensagens."""

    def test_um_campo_fora_da_lista_levanta_e_nada_sai(self) -> None:
        transporte = _Transporte()
        cliente, lig, _ = _cliente(transporte)
        for campo in ("model", "messages", "max_tokens", "tools"):
            with self.subTest(campo=campo), self.assertRaises(ValueError):
                cliente.chamar("router", [], screening_ctx(), corpo_extra={campo: "x"})
        self.assertEqual(transporte.chamadas, [])
        self.assertEqual(lig.linhas(), [])


# ------------------------------------------------------------------- a rota

CREDENCIAL = "credencial-do-ensaio-do-screening"


class _Registador:
    def __init__(self, devolver: str = '{"decisao":"condicional","confianca":0.5}') -> None:
        self.pedidos: list[screening.PedidoDeScreening] = []
        self._devolver = devolver

    def __call__(self, pedido: screening.PedidoDeScreening) -> str:
        self.pedidos.append(pedido)
        return self._devolver


def _app(
    classificar: Any,
    credencial: Any = lambda: CREDENCIAL,
    # Larga de proposito: a guarda da fila tem os seus ensaios, e numa maquina
    # carregada os 2 s de producao punham os outros a falhar por tempo.
    folga_s: float = 3600.0,
) -> Any:
    return create_app(
        rotas_internas=screening.rotas(credencial, classificar, folga_s=folga_s)
    )


def _corpo_valido(**sobrepor: Any) -> dict[str, Any]:
    corpo = {
        "tenant_id": TENANT,
        "trace_id": TRACE,
        "categoria_declarada": "moda",
        "textos": ["camisola"],
    }
    corpo.update(sobrepor)
    return corpo


def _pedir(app: Any, corpo: Any, cabecalhos: dict[str, str] | None = None) -> tuple[int, dict, bytes]:
    return asyncio.run(
        pedir(
            app,
            screening.ROTA,
            "POST",
            json.dumps(corpo).encode(),
            {"x-kamba-interno": CREDENCIAL} if cabecalhos is None else cabecalhos,
        )
    )


class TestARota(unittest.TestCase):
    """Canario: `test_um_corpo_valido_chega_ao_classificador`. Sem ele, as
    recusas abaixo passavam com uma rota que recusa tudo."""

    def test_um_corpo_valido_chega_ao_classificador(self) -> None:
        duplo = _Registador()
        estado, _, corpo = _pedir(_app(duplo), _corpo_valido())
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(corpo)["outcome"], "classificado")
        self.assertEqual(
            duplo.pedidos,
            [screening.PedidoDeScreening(TENANT, TRACE, "moda", ("camisola",))],
        )

    def test_sem_credencial_ou_errada_e_401_e_nao_le_o_corpo(self) -> None:
        duplo = _Registador()
        for cabecalhos in ({}, {"x-kamba-interno": "outra"}):
            with self.subTest(cabecalhos=cabecalhos):
                estado, _, _ = _pedir(_app(duplo), _corpo_valido(), cabecalhos)
                self.assertEqual(estado, 401)
        self.assertEqual(duplo.pedidos, [])

    def test_uma_credencial_por_configurar_fecha_a_porta(self) -> None:
        def sem_segredo() -> str:
            raise KeyError("agr_screening_token")

        duplo = _Registador()
        estado, _, _ = _pedir(_app(duplo, sem_segredo), _corpo_valido())
        self.assertEqual(estado, 401)
        self.assertEqual(duplo.pedidos, [])

    def test_corpos_fora_da_forma_sao_400(self) -> None:
        duplo = _Registador()
        casos = {
            "campo_a_mais": _corpo_valido(model="outro-alias"),
            "campo_a_menos": {k: v for k, v in _corpo_valido().items() if k != "trace_id"},
            "tenant_nao_uuid": _corpo_valido(tenant_id="tenant-a"),
            "trace_curto": _corpo_valido(trace_id="abc"),
            "categoria_grande": _corpo_valido(categoria_declarada="x" * 201),
            "textos_a_mais": _corpo_valido(textos=["x"] * 21),
            "texto_grande": _corpo_valido(textos=["x" * 1001]),
            "texto_nao_cadeia": _corpo_valido(textos=[1]),
            "lista": [],
        }
        for nome, corpo in casos.items():
            with self.subTest(nome=nome):
                estado, _, resposta = _pedir(_app(duplo), corpo)
                self.assertEqual(estado, 400, resposta)
                self.assertEqual(json.loads(resposta)["outcome"], "corpo_invalido")
        self.assertEqual(duplo.pedidos, [])

    def test_sem_classificador_e_503(self) -> None:
        estado, _, corpo = _pedir(_app(None), _corpo_valido())
        self.assertEqual(estado, 503)
        self.assertEqual(json.loads(corpo), {"outcome": "classificador_por_ligar"})

    def test_o_pedido_no_tecto_do_contrato_chega_ao_classificador(self) -> None:
        """Achado 1 da revisao adversarial: o `CORPO_MAXIMO` de 8 KiB recusava-o.

        Vinte textos de mil caracteres e a categoria de duzentos, com o pior
        caso de octetos que o `json.dumps` produz (um caracter de controlo e o
        escape de seis octetos). Com o tecto das outras rotas, dava 400.
        """
        duplo = _Registador()
        corpo = _corpo_valido(
            categoria_declarada="\x01" * screening.CARACTERES_DA_CATEGORIA,
            textos=["\x01" * screening.CARACTERES_POR_TEXTO] * screening.TEXTOS_MAXIMOS,
        )
        self.assertGreater(len(json.dumps(corpo).encode()), 8 * 1024)
        estado, _, resposta = _pedir(_app(duplo), corpo)
        self.assertEqual(estado, 200, resposta)
        self.assertEqual(len(duplo.pedidos), 1)

    def test_um_corpo_acima_do_tecto_e_400(self) -> None:
        duplo = _Registador()
        cru = b'{"x": "' + b"a" * screening.CORPO_MAXIMO + b'"}'
        estado, _, resposta = asyncio.run(
            pedir(_app(duplo), screening.ROTA, "POST", cru, {"x-kamba-interno": CREDENCIAL})
        )
        self.assertEqual(estado, 400)
        self.assertEqual(json.loads(resposta)["error_code"], "corpo_grande")
        self.assertEqual(duplo.pedidos, [])

    def test_um_sucedaneo_solto_e_400_e_nao_chega_ao_classificador(self) -> None:
        """Achado 6: um emoji partido pelo `slice` do TypeScript."""
        duplo = _Registador()
        estado, _, resposta = _pedir(_app(duplo), _corpo_valido(textos=["camisola \ud83d"]))
        self.assertEqual(estado, 400)
        self.assertEqual(json.loads(resposta)["error_code"], "texto_nao_utf8")
        self.assertEqual(duplo.pedidos, [])

    def test_sem_tempo_na_fila_nao_chama_o_modelo(self) -> None:
        """Achado 4: um pedido que ja nao acaba no prazo do GOV nao paga chamada."""
        duplo = _Registador()
        estado, _, resposta = _pedir(_app(duplo, folga_s=-1.0), _corpo_valido())
        self.assertEqual(estado, 503)
        self.assertEqual(json.loads(resposta), {"outcome": "sem_tempo"})
        self.assertEqual(duplo.pedidos, [])

    def test_a_folga_e_o_prazo_menos_o_tecto_e_a_margem(self) -> None:
        self.assertEqual(screening.folga_de_fila_s(REAIS["screening"]), 15.0 - 12.0 - 1.0)
        self.assertGreater(screening.folga_de_fila_s(REAIS["screening"]), 0)

    def test_um_modelo_sem_texto_nao_da_200(self) -> None:
        """Achado 5: o `_texto` do cliente devolve "" com o `content` nulo."""
        estado, _, resposta = _pedir(_app(_Registador(devolver="")), _corpo_valido())
        self.assertEqual(estado, 503)
        self.assertEqual(json.loads(resposta), {"outcome": "sem_conteudo"})


class TestALigacaoDoArranque(unittest.TestCase):
    """Achado 2: os ensaios da rota injectam a credencial e a chave, e por isso
    nenhum deles via o `__main__` ligar a credencial do turno a esta rota, ou a
    chave do tenant ao classificador. Estes leem o que o arranque passa.

    Canario: trocar `llm_screening.SEGREDO_DA_ROTA` por `SEGREDO_DA_API` na
    ligacao da rota avermelha `test_a_rota_le_a_sua_credencial`.
    """

    MAIN = RAIZ / "services/agr/src/kamba_agr/__main__.py"

    def _chamada(self, inicio: str, fecho: str) -> str:
        """Os argumentos de uma chamada, ate a linha que a fecha (`fecho`)."""
        texto = self.MAIN.read_text(encoding="utf-8")
        (trecho,) = re.findall(re.escape(inicio + "(") + "(.*?)" + re.escape(fecho), texto, re.S)
        return trecho

    def test_a_rota_le_a_sua_credencial(self) -> None:
        trecho = self._chamada("*llm_screening.rotas", "\n            ),")
        self.assertIn("segredos.get(llm_screening.SEGREDO_DA_ROTA)", trecho)  # kamba:secrets-inventory dinamico o texto do __main__ que o ensaio procura, e nao um pedido
        self.assertNotIn("SEGREDO_DA_API", trecho)

    def test_o_classificador_usa_a_chave_da_plataforma(self) -> None:
        trecho = self._chamada("llm_screening.ClassificadorDeScreening", "\n    )")
        self.assertIn("llm_screening.REF_CHAVE_DO_SCREENING", trecho)
        self.assertNotIn("REF_CHAVE_VIRTUAL", trecho)

    def test_as_duas_referencias_sao_outras_e_estao_no_inventario(self) -> None:
        from kamba_agr.api_interna import SEGREDO_DA_API
        from kamba_agr.llm.cliente import REF_CHAVE_VIRTUAL

        self.assertNotEqual(screening.SEGREDO_DA_ROTA, SEGREDO_DA_API)
        self.assertNotEqual(screening.REF_CHAVE_DO_SCREENING, REF_CHAVE_VIRTUAL)
        # Por expressao regular e nao pelo `kamba_yaml`: o inventario usa listas
        # em estilo de fluxo que o subconjunto desta casa nao le, e quem o le a
        # serio e o `tools/secrets_inventory`, com o seu leitor.
        texto = (RAIZ / "ops" / "secrets-inventory.yaml").read_text(encoding="utf-8")
        ids = set(re.findall(r"^  - id: (\w+)$", texto, re.M))
        self.assertIn("agr_internal_token", ids)  # o controlo: a leitura le
        self.assertIn(screening.SEGREDO_DA_ROTA, ids)
        self.assertIn(screening.REF_CHAVE_DO_SCREENING, ids)


# --------------------------------------------------------------- paridade

CLASSIFICADOR_TS = RAIZ / "packages/core-ts/src/screening/classificador.ts"
TIPOS_TS = RAIZ / "packages/core-ts/src/screening/tipos.ts"


class TestOTectoCabeAsDuasTentativas(unittest.TestCase):
    """Detalhes Tecnicos do KAM-195: «a nova tentativa cabe no orcamento de quem chama».

    Canario: baixar o `TEMPO_MAXIMO_MS` do TypeScript para 5000 avermelha
    `test_o_orcamento_do_gov_e_maior_do_que_o_tecto`.
    """

    def test_as_premissas_do_tecto_estao_no_ficheiro(self) -> None:
        dados = load_file(RAIZ / "llm" / "aliases.yaml")
        self.assertEqual(dados["router_settings"]["num_retries"], screening.TENTATIVAS - 1)
        fornecedores = [f for f in dados["fornecedores"] if f["alias"] == "screening-nano"]
        self.assertEqual(len(fornecedores), 1, "um grupo de fallback e uma terceira tentativa")

    def test_o_tecto_sao_duas_tentativas_mais_a_margem(self) -> None:
        self.assertEqual(screening.tecto_s(REAIS["screening"]), 12.0)

    def test_o_orcamento_do_gov_e_maior_do_que_o_tecto(self) -> None:
        texto = CLASSIFICADOR_TS.read_text(encoding="utf-8")
        (valor,) = re.findall(r"export const TEMPO_MAXIMO_MS = ([\d_]+);", texto)
        # Igualdade com o `PRAZO_DO_GOV_S`, de que a folga da fila depende, e
        # desigualdade com o tecto, que e o que o criterio pede.
        self.assertEqual(int(valor.replace("_", "")), screening.PRAZO_DO_GOV_S * 1000)
        self.assertGreater(int(valor.replace("_", "")), screening.tecto_s(REAIS["screening"]) * 1000)


class TestParidadeComOTypeScript(unittest.TestCase):
    def test_os_tectos_do_pedido_sao_os_mesmos(self) -> None:
        texto = CLASSIFICADOR_TS.read_text(encoding="utf-8")
        (linha,) = re.findall(r"export const LIMITES_DO_PEDIDO = \{([^}]*)\}", texto)
        valores = dict(re.findall(r"(\w+): (\d+)", linha))
        self.assertEqual(
            valores,
            {
                "textos": str(screening.TEXTOS_MAXIMOS),
                "caracteresPorTexto": str(screening.CARACTERES_POR_TEXTO),
                "caracteresDaCategoria": str(screening.CARACTERES_DA_CATEGORIA),
            },
        )

    def test_as_decisoes_sao_as_mesmas(self) -> None:
        texto = TIPOS_TS.read_text(encoding="utf-8")
        (lista,) = re.findall(r"export const DECISOES = \[([^\]]*)\]", texto)
        self.assertEqual(tuple(re.findall(r'"(\w+)"', lista)), screening.DECISOES)


if __name__ == "__main__":
    unittest.main()
