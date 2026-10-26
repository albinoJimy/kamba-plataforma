"""O cliente do gateway de LLM (KAM-030): criterios 4, 5, 6 e 8.

**O que esta bateria existe para impedir, dito a frente:** um teste de orcamento
que nao conte chamadas recusadas passa com o orcamento apagado, e um teste de
registo que so confirme «houve uma linha» passa com os valores todos a nulo. Por
isso cada classe aqui tem um canario — um caso que falha se a propriedade for
removida — e esta nomeado na *docstring* dela.

A ligacao e um duplo que **grava o SQL**, como a do `test_tls.py`, e pela mesma
razao: e assim que se prova que o `SET LOCAL app.tenant_id` saiu com o tenant do
contexto, e que os catorze valores da linha sao os que se esperam.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Any

from kamba_agr import metricas as metricas_mod
from kamba_agr.llm import aliases as aliases_mod
from kamba_agr.llm import destinos as destinos_mod
from kamba_agr.llm import precos as precos_mod
from kamba_agr.llm import registo as registo_mod
from kamba_agr.llm.cliente import ClienteDeLlm, ContextoDeChamada
from kamba_agr.llm.erros import (
    RESULTADO_BUDGET,
    RESULTADO_DESTINO,
    RESULTADO_ERRO,
    RESULTADO_OK,
    RESULTADO_OK_FALLBACK,
    RESULTADO_TIMEOUT,
    DestinoNegado,
    FornecedorFalhou,
    OrcamentoEsgotado,
    TempoEsgotado,
)

TENANT = "11111111-1111-1111-1111-111111111111"

CTX = ContextoDeChamada(
    tenant_id=TENANT,
    trace_id="0af7651916cd43dd8448eb211c80319c",
    vertical="vendedor",
    no_grafo="compose",
    graph_version="1.0.0",
)


class _Cursor:
    def __init__(self, ligacao: "_Ligacao") -> None:
        self._ligacao = ligacao

    def execute(self, sql: str, parametros: Any = ()) -> None:
        if self._ligacao.levantar:
            raise RuntimeError("base indisponivel (ensaio)")
        self._ligacao.sql.append((sql, tuple(parametros or ())))

    def __enter__(self) -> "_Cursor":
        # O `tenant_guard.tx` real **reserva a ligacao** e recusa uma segunda
        # entrada com `LigacaoEmUso`. O duplo faz o mesmo, porque sem isso uma
        # ligacao partilhada entre turnos concorrentes passava nos ensaios e
        # perdia linhas em producao — foi o que aconteceu.
        if self._ligacao.em_uso:
            raise RuntimeError("LigacaoEmUso (ensaio): ja ha uma transaccao aberta")
        self._ligacao.em_uso += 1
        return self

    def __exit__(self, *_: object) -> None:
        self._ligacao.em_uso -= 1

    def fetchone(self) -> tuple[Any, ...]:
        return tuple(True for _ in registo_mod.COLUNAS)

    def close(self) -> None:
        return None


class _Ligacao:
    def __init__(self, levantar: bool = False) -> None:
        self.autocommit = False
        self.sql: list[tuple[str, tuple[Any, ...]]] = []
        self.levantar = levantar
        self.fechada = 0
        #: Quantas transaccoes estao abertas **agora**. E isto que denuncia uma
        #: ligacao partilhada: o `tenant_guard` real recusa a segunda com
        #: `LigacaoEmUso`, e este duplo faz o mesmo.
        self.em_uso = 0

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.fechada += 1

    # ------------------------------------------------------------- leituras
    def linhas(self) -> list[dict[str, Any]]:
        """As linhas de `dat.llm_call_log` que esta ligacao recebeu."""
        saida = []
        for sql, parametros in self.sql:
            if "INSERT INTO dat.llm_call_log" in sql:
                saida.append(dict(zip(registo_mod.COLUNAS, parametros, strict=True)))
        return saida

    def tenants_do_contexto(self) -> list[Any]:
        """Os valores que o `SET LOCAL app.tenant_id` levou."""
        return [
            parametros[0]
            for sql, parametros in self.sql
            if "app.tenant_id" in sql and parametros
        ]


ALIAS_CHAT = aliases_mod.Alias(
    nome="kamba-chat",
    papel="chat",
    timeout=20,
    fornecedores=("anthropic", "openai"),
    modelos=("claude-haiku-5-5", "gpt-6-luna"),
)
ALIAS_ROUTER = aliases_mod.Alias(
    nome="kamba-router",
    papel="router",
    timeout=8,
    fornecedores=("anthropic",),
    modelos=("claude-haiku-5-5",),
)
ALIASES = {"chat": ALIAS_CHAT, "router": ALIAS_ROUTER}

PRECOS = {
    ("anthropic", "claude-haiku-5-5"): precos_mod.Preco(
        "anthropic", "claude-haiku-5-5",
        Decimal("0.10"), Decimal("0.01"), Decimal("0.50"), "CONFIRMADO", "E4 3.1",
    ),
    ("openai", "gpt-6-luna"): precos_mod.Preco(
        "openai", "gpt-6-luna",
        Decimal("0.10"), Decimal("0.01"), Decimal("0.50"), "CONFIRMADO", "E4 3.2",
    ),
}


def _resposta(modelo: str = "anthropic/claude-haiku-5-5", entrada: int = 3000,
              saida: int = 300, cache: int = 0) -> dict[str, Any]:
    return {
        "model": modelo,
        "choices": [{"message": {"content": "ola"}}],
        "usage": {
            "prompt_tokens": entrada,
            "completion_tokens": saida,
            "prompt_tokens_details": {"cached_tokens": cache},
        },
    }


class _Transporte:
    """Um transporte de ensaio que grava o que recebeu."""

    def __init__(self, *respostas: tuple[int, Any, dict[str, str]]) -> None:
        self.respostas = list(respostas)
        self.chamadas: list[tuple[str, dict[str, str], dict[str, Any], float]] = []
        self.levantar: BaseException | None = None

    def __call__(self, url: str, cabecalhos: dict[str, str], corpo: dict[str, Any],
                 timeout: float) -> tuple[int, Any, dict[str, str]]:
        self.chamadas.append((url, cabecalhos, corpo, timeout))
        if self.levantar is not None:
            raise self.levantar
        return self.respostas.pop(0) if self.respostas else (200, _resposta(), {})


def _cliente(
    transporte: Any = None,
    ambiente: str = destinos_mod.AMBIENTE_STAGING,
    ligacao: _Ligacao | None = None,
    metricas: metricas_mod.MetricasDoAgr | None = None,
) -> tuple[ClienteDeLlm, _Ligacao, metricas_mod.MetricasDoAgr]:
    lig = ligacao or _Ligacao()
    met = metricas or metricas_mod.MetricasDoAgr()
    relogio = iter([0.0, 0.25] + [0.0] * 50)
    cliente = ClienteDeLlm(
        aliases=ALIASES,
        tabela_de_precos=PRECOS,
        porta_de_destinos=destinos_mod.arrancar(ambiente),
        # **Uma fabrica e nao uma ligacao.** A primeira versao passava a ligacao
        # e o cliente guardava-a; aqui devolve-se sempre a mesma instancia, para
        # as baterias poderem ler o SQL, mas o cliente **abre e fecha** por
        # chamada — e e isso que o `TestDuasChamadasConcorrentes` mede.
        abrir_ligacao=lambda: lig,
        chave_virtual=lambda t: f"sk-virtual-{t}",
        url_do_proxy="http://litellm:4000",
        metricas=met,
        transporte=transporte or _Transporte(),
        agora=lambda: next(relogio, 0.25),
    )
    return cliente, lig, met


class TestUmaLinhaPorChamada(unittest.TestCase):
    """Criterio 5: «cada chamada grava 1 linha, **sem conteudo**».

    Canario: `test_a_linha_leva_os_valores_e_nao_nulos`. Sem ele, um registo que
    escrevesse catorze nulos passava o «grava 1 linha».
    """

    def test_uma_chamada_uma_linha(self) -> None:
        cliente, lig, _ = _cliente()
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(len(lig.linhas()), 1)

    def test_a_linha_leva_os_valores_e_nao_nulos(self) -> None:
        cliente, lig, _ = _cliente()
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        linha = lig.linhas()[0]
        self.assertEqual(linha["tenant_id"], TENANT)
        self.assertEqual(linha["trace_id"], CTX.trace_id)
        self.assertEqual(linha["vertical"], "vendedor")
        self.assertEqual(linha["no_grafo"], "compose")
        self.assertEqual(linha["papel"], "chat")
        self.assertEqual(linha["graph_version"], "1.0.0")
        self.assertEqual(linha["modelo"], "claude-haiku-5-5")
        self.assertEqual(linha["fornecedor"], "anthropic")
        self.assertEqual(linha["tokens_in"], 3000)
        self.assertEqual(linha["tokens_out"], 300)
        self.assertEqual(linha["resultado"], RESULTADO_OK)
        # O numero do criterio 5, agora pelo caminho inteiro e nao so na formula.
        self.assertEqual(linha["custo_usd"], Decimal("0.00045"))
        self.assertIsNotNone(linha["latencia_ms"])

    def test_a_linha_nao_leva_conteudo(self) -> None:
        """O *prompt* e a resposta nao aparecem em valor nenhum da linha.

        **Com canarios**, e nao a olhar para a lista de colunas: a lista nao
        prova que ninguem escreveu texto do cliente num campo de texto.
        """
        canario_pedido = "SAPATOS-VERMELHOS-CANARIO-42"
        canario_resposta = "RESPOSTA-CANARIO-99"
        transporte = _Transporte(
            (200, {"model": "anthropic/claude-haiku-5-5",
                   "choices": [{"message": {"content": canario_resposta}}],
                   "usage": {"prompt_tokens": 10, "completion_tokens": 2}}, {})
        )
        cliente, lig, _ = _cliente(transporte)
        cliente.chamar("chat", [{"role": "user", "content": canario_pedido}], CTX)
        tudo = " ".join(str(v) for linha in lig.linhas() for v in linha.values())
        self.assertNotIn(canario_pedido, tudo)
        self.assertNotIn(canario_resposta, tudo)
        self.assertNotIn("SAPATOS", tudo.upper())

    def test_o_contexto_de_tenant_e_o_do_pedido(self) -> None:
        cliente, lig, _ = _cliente()
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(lig.tenants_do_contexto(), [TENANT])

    def test_o_registo_que_falha_nao_rebenta_a_chamada(self) -> None:
        """Repetir a chamada custava uma segunda transferencia e um segundo custo."""
        cliente, lig, met = _cliente(ligacao=_Ligacao(levantar=True))
        resposta = cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(resposta.resultado, RESULTADO_OK)
        self.assertEqual(
            met.ler().get(metricas_mod.METRICA_LLM_REGISTO_FALHOU), 1,
            "a perda tem de ser visivel numa metrica",
        )


class TestDuasChamadasConcorrentes(unittest.TestCase):
    """O canario do achado 4 da revisao adversarial.

    Com uma ligacao **por processo**, o `tenant_guard.tx` recusava a segunda
    entrada (`LigacaoEmUso`), o `escrever` engolia-a e a segunda chamada saía,
    consumia *tokens*, transferia dados e **nao gravava linha**. O criterio 5 e
    o registo de transferencia do ADR-008 falhavam exactamente sob carga, e o
    duplo sequencial da primeira versao desta bateria nao o via.
    """

    def test_duas_chamadas_ao_mesmo_tempo_gravam_duas_linhas(self) -> None:
        import threading

        lig = _Ligacao()
        met = metricas_mod.MetricasDoAgr()
        # Uma ligacao **nova** por chamada, como o `ligar_para_llm` faz em
        # producao; todas escrevem no mesmo registo para a bateria o poder ler.
        abertas: list[_Ligacao] = []

        def abrir() -> _Ligacao:
            nova = _Ligacao()
            nova.sql = lig.sql
            abertas.append(nova)
            return nova

        a_meio = threading.Barrier(2, timeout=5)

        def transporte(url, cabecalhos, corpo, timeout):
            # As duas chamadas chegam ao registo **ao mesmo tempo**: sem a
            # barreira, a segunda podia comecar depois de a primeira acabar e o
            # ensaio nao media concorrencia nenhuma.
            a_meio.wait()
            return 200, _resposta(), {}

        cliente = ClienteDeLlm(
            aliases=ALIASES, tabela_de_precos=PRECOS,
            porta_de_destinos=destinos_mod.arrancar(destinos_mod.AMBIENTE_STAGING),
            abrir_ligacao=abrir, chave_virtual=lambda t: "sk-x",
            metricas=met, transporte=transporte,
        )
        erros: list[BaseException] = []

        def correr() -> None:
            try:
                cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
            except BaseException as excepcao:  # noqa: BLE001
                erros.append(excepcao)

        fios = [threading.Thread(target=correr) for _ in range(2)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(timeout=10)

        self.assertEqual(erros, [])
        self.assertEqual(len(lig.linhas()), 2, "uma linha por chamada, sob carga")
        self.assertIsNone(met.ler().get(metricas_mod.METRICA_LLM_REGISTO_FALHOU))
        self.assertEqual(len(abertas), 2, "uma ligacao por chamada")
        self.assertTrue(all(l.fechada for l in abertas), "e fechada no fim")


class TestOPrecoExpirado(unittest.TestCase):
    """O canario do achado 5 da revisao adversarial.

    O `custo()` **levanta** numa tarifa expirada, e era chamado no caminho de
    sucesso **antes** de se gravar a linha: a chamada saía, zero linhas ficavam
    na tabela, e escapava um `ValueError` que nao e `ErroDeLlm` — pelo que o
    turno falhava, o *job* voltava a fila e a chamada **repetia-se**: segunda
    transferencia e segundo custo.
    """

    def test_uma_tarifa_expirada_grava_a_linha_com_custo_nulo(self) -> None:
        import datetime as dt

        expirado = {
            ("anthropic", "claude-haiku-5-5"): precos_mod.Preco(
                "anthropic", "claude-haiku-5-5",
                Decimal("0.10"), Decimal("0.01"), Decimal("0.50"),
                "CONFIRMADO", "ensaio", valido_ate=dt.date(2020, 1, 1),
            )
        }
        lig = _Ligacao()
        met = metricas_mod.MetricasDoAgr()
        cliente = ClienteDeLlm(
            aliases=ALIASES, tabela_de_precos=expirado,
            porta_de_destinos=destinos_mod.arrancar(destinos_mod.AMBIENTE_STAGING),
            abrir_ligacao=lambda: lig, chave_virtual=lambda t: "sk-x",
            metricas=met, transporte=_Transporte(),
        )
        resposta = cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(resposta.resultado, RESULTADO_OK)
        self.assertIsNone(resposta.custo_usd)
        self.assertEqual(len(lig.linhas()), 1, "a linha nao se perde")
        self.assertIsNone(lig.linhas()[0]["custo_usd"])
        self.assertEqual(met.ler().get(metricas_mod.METRICA_LLM_SEM_PRECO), 1)

    def test_o_arranque_recusa_uma_tarifa_expirada(self) -> None:
        """A metade preventiva: chegar ao caminho acima e a rede, nao a regra."""
        import datetime as dt
        import pathlib

        tabela = precos_mod.carregar(
            pathlib.Path(__file__).resolve().parents[3] / "llm"
        )
        promocional = {("google", "gemini-3.8-flash")}
        precos_mod.sem_expirados(tabela, promocional, hoje=dt.date(2026, 12, 31))
        with self.assertRaises(precos_mod.PrecoExpirado):
            precos_mod.sem_expirados(tabela, promocional, hoje=dt.date(2027, 1, 1))
        # **E o canario**: a mesma tabela, na mesma data, com os pares que os
        # aliases usam **hoje** (nenhum tem preco) passa — e e isso que impede
        # o arranque de recusar subir por um candidato que ninguem escolheu.
        precos_mod.sem_expirados(
            tabela, {("anthropic", "por_decidir")}, hoje=dt.date(2030, 1, 1)
        )


class TestOMapeamentoDoOrcamento(unittest.TestCase):
    """Criterio 4: `BUDGET_EXHAUSTED` com orcamento esgotado.

    **O ticket diz «mapeado do 400» e a versao fixada responde 422** com
    `type: budget_exceeded` (`docs/evidencia/KAM-030-litellm.md` §4). Estas
    baterias medem a forma real e o canario e
    `test_um_400_de_outra_coisa_nao_e_orcamento`: sem ele, um mapeamento por
    estado passava e dizia «sem orcamento» a um erro de provisionamento.
    """

    def test_o_422_de_budget_exceeded_da_orcamento_esgotado(self) -> None:
        corpo = {"error": {"message": "Budget has been exceeded! Key=tenant-x",
                           "type": "budget_exceeded", "code": "422"}}
        cliente, lig, met = _cliente(_Transporte((422, corpo, {})))
        with self.assertRaises(OrcamentoEsgotado):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(lig.linhas()[0]["resultado"], RESULTADO_BUDGET)
        self.assertEqual(
            met.ler().get(f"{metricas_mod.METRICA_LLM_ERROS}:{RESULTADO_BUDGET}"), 1
        )

    def test_um_400_de_outra_coisa_nao_e_orcamento(self) -> None:
        """O canario. O proxy usa o 400 para «alias repetido», medido."""
        corpo = {"error": {"message": "Key with alias 'tenant-x' already exists.",
                           "type": "bad_request_error", "code": "400"}}
        cliente, _, _ = _cliente(_Transporte((400, corpo, {})))
        with self.assertRaises(FornecedorFalhou) as apanhado:
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertNotIsInstance(apanhado.exception, OrcamentoEsgotado)

    def test_a_recusa_por_orcamento_conta_como_chamada(self) -> None:
        """Um teste de orcamento que nao conte recusas passa com o budget apagado."""
        corpo = {"error": {"type": "budget_exceeded", "message": "Budget has been exceeded!"}}
        cliente, lig, _ = _cliente(_Transporte((422, corpo, {})))
        with self.assertRaises(OrcamentoEsgotado):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        linha = lig.linhas()[0]
        self.assertEqual(len(lig.linhas()), 1, "uma recusa e uma chamada (criterio 5)")
        self.assertIsNone(linha["custo_usd"], "nao houve consumo a cobrar")
        self.assertIsNone(linha["tokens_in"])


class TestOGateDeDestino(unittest.TestCase):
    """Criterio 8: em `prod` falha **fechada** (ADR-008), sem KAM-069.

    Canario: `test_em_prod_nao_sai_pedido_nenhum`. Sem ele, um *gate* que
    levantasse **depois** de a chamada sair passava a dizer que negou.
    """

    def test_em_prod_nega(self) -> None:
        cliente, lig, met = _cliente(ambiente=destinos_mod.AMBIENTE_PROD)
        with self.assertRaises(DestinoNegado):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(lig.linhas()[0]["resultado"], RESULTADO_DESTINO)
        self.assertEqual(met.ler().get(metricas_mod.METRICA_LLM_DESTINO_NEGADO), 1)

    def test_em_prod_nao_sai_pedido_nenhum(self) -> None:
        """O canario: o *gate* corre **antes** da chamada, nao depois."""
        transporte = _Transporte()
        cliente, _, _ = _cliente(transporte, ambiente=destinos_mod.AMBIENTE_PROD)
        with self.assertRaises(DestinoNegado):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(transporte.chamadas, [], "nada saiu para o proxy")

    def test_um_ambiente_desconhecido_e_tratado_como_prod(self) -> None:
        cliente, _, _ = _cliente(ambiente="producao")
        with self.assertRaises(DestinoNegado):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)

    def test_em_staging_passa(self) -> None:
        cliente, _, _ = _cliente(ambiente=destinos_mod.AMBIENTE_STAGING)
        resposta = cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(resposta.resultado, RESULTADO_OK)

    def test_a_recusa_nao_leva_custo_nem_tokens(self) -> None:
        """O `CHECK llm_call_log_negado_sem_consumo` da revisao `0023` recusa-a se levar."""
        cliente, lig, _ = _cliente(ambiente=destinos_mod.AMBIENTE_PROD)
        with self.assertRaises(DestinoNegado):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        linha = lig.linhas()[0]
        for coluna in ("tokens_in", "tokens_out", "tokens_cache", "custo_usd"):
            self.assertIsNone(linha[coluna], coluna)

    def test_o_gate_corre_para_todos_os_fornecedores_do_alias(self) -> None:
        """O que impede o *fallback* de sair para um destino nao autorizado.

        Autorizar so o de `ordem: 1` deixava o router comutar para o segundo sem
        o *gate* ter sido consultado por ele.
        """
        consultados: list[str] = []

        class _Porta:
            nome = "ensaio"

            def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
                consultados.append(fornecedor)

        lig = _Ligacao()
        cliente = ClienteDeLlm(
            aliases=ALIASES, tabela_de_precos=PRECOS, porta_de_destinos=_Porta(),
            abrir_ligacao=lambda: lig, chave_virtual=lambda t: "sk-x",
            metricas=metricas_mod.MetricasDoAgr(), transporte=_Transporte(),
        )
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(consultados, ["anthropic", "openai"])

    def test_um_papel_sem_finalidade_nega_e_grava(self) -> None:
        """Esta recusa vinha de fora do `try` e saia sem linha nem metrica."""
        alias = aliases_mod.Alias("kamba-x", "chat", 20, ("anthropic",), ("m",))
        lig = _Ligacao()
        met = metricas_mod.MetricasDoAgr()
        cliente = ClienteDeLlm(
            aliases={"papel_invalido": alias}, tabela_de_precos=PRECOS,
            porta_de_destinos=destinos_mod.arrancar(destinos_mod.AMBIENTE_STAGING),
            abrir_ligacao=lambda: lig, chave_virtual=lambda t: "sk-x",
            metricas=met, transporte=_Transporte(),
        )
        with self.assertRaises(DestinoNegado):
            cliente.chamar("papel_invalido", [{"role": "user", "content": "x"}], CTX)
        self.assertEqual(len(lig.linhas()), 1)
        self.assertEqual(met.ler().get(metricas_mod.METRICA_LLM_DESTINO_NEGADO), 1)


class TestAMensagemDoFornecedorNaoVaza(unittest.TestCase):
    """O achado 16 da revisao adversarial, e e uma fuga de conteudo.

    O proxy devolve o pedido recusado **dentro** da mensagem de erro. A primeira
    versao do `classificar` copiava 200 caracteres dela para `str(erro)`; o
    `/internal/turn` nao apanha `ErroDeLlm`, pelo que o *traceback* do uvicorn a
    escrevia no *stdout* do contentor — com um telefone de cliente. ADR-010.
    """

    CANARIO = "Bom dia, o meu numero e 923000000"

    def test_o_corpo_do_erro_nao_entra_na_excepcao(self) -> None:
        corpo = {
            "error": {
                "type": "invalid_request_error",
                "message": f"Invalid value for 'messages[0].content': '{self.CANARIO}'",
            }
        }
        cliente, _, _ = _cliente(_Transporte((400, corpo, {})))
        with self.assertRaises(FornecedorFalhou) as apanhado:
            cliente.chamar("chat", [{"role": "user", "content": self.CANARIO}], CTX)
        texto = str(apanhado.exception)
        self.assertNotIn("923000000", texto)
        self.assertNotIn("Bom dia", texto)
        # O que **fica** e o diagnostico: o estado e o tipo.
        self.assertIn("400", texto)
        self.assertIn("invalid_request_error", texto)

    def test_um_tipo_que_nao_e_identificador_nao_passa(self) -> None:
        """Um fornecedor que ponha prosa no `type` nao a passa por ali."""
        corpo = {"error": {"type": f"recusado: {self.CANARIO}", "message": "x"}}
        cliente, _, _ = _cliente(_Transporte((400, corpo, {})))
        with self.assertRaises(FornecedorFalhou) as apanhado:
            cliente.chamar("chat", [{"role": "user", "content": "x"}], CTX)
        self.assertNotIn("923000000", str(apanhado.exception))
        self.assertIn("sem_tipo", str(apanhado.exception))

    def test_um_corpo_que_nao_e_json_nao_devolve_texto(self) -> None:
        cliente, _, _ = _cliente(
            _Transporte((502, {"error": {"type": "resposta_nao_json"}}, {}))
        )
        with self.assertRaises(FornecedorFalhou) as apanhado:
            cliente.chamar("chat", [{"role": "user", "content": "x"}], CTX)
        self.assertIn("resposta_nao_json", str(apanhado.exception))


class TestQuemServiu(unittest.TestCase):
    """Criterio 6: o *fallback* aparece no registo como tal.

    Canario: `test_nao_se_assume_o_primeiro`. Sem ele, um registo que escrevesse
    sempre o fornecedor de `ordem: 1` passava o «uma linha por chamada» e
    apontava para o destino errado — pior do que nao ter registo.
    """

    def test_o_primeiro_da_ok(self) -> None:
        cliente, lig, _ = _cliente(
            _Transporte((200, _resposta("anthropic/claude-haiku-5-5"), {}))
        )
        resposta = cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(resposta.resultado, RESULTADO_OK)
        self.assertFalse(resposta.usou_fallback)
        self.assertEqual(lig.linhas()[0]["fornecedor"], "anthropic")

    def test_nao_se_assume_o_primeiro(self) -> None:
        """O canario: servido pelo segundo, registado como `ok_fallback`."""
        cliente, lig, _ = _cliente(
            _Transporte((200, _resposta("openai/gpt-6-luna"), {}))
        )
        resposta = cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(resposta.resultado, RESULTADO_OK_FALLBACK)
        self.assertTrue(resposta.usou_fallback)
        linha = lig.linhas()[0]
        self.assertEqual(linha["fornecedor"], "openai")
        self.assertEqual(linha["modelo"], "gpt-6-luna")

    def test_pelo_cabecalho_do_grupo_quando_o_modelo_nao_diz(self) -> None:
        cliente, lig, _ = _cliente(
            _Transporte((200, _resposta("por_decidir"),
                         {"x-litellm-model-group": "kamba-chat-fallback2"}))
        )
        resposta = cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(resposta.fornecedor, "openai")
        self.assertEqual(lig.linhas()[0]["resultado"], RESULTADO_OK_FALLBACK)

    def test_sem_nenhuma_das_duas_vias_conta_a_incerteza(self) -> None:
        cliente, _, met = _cliente(_Transporte((200, _resposta("por_decidir"), {})))
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(
            met.ler().get(metricas_mod.METRICA_LLM_SERVIDOR_DESCONHECIDO), 1
        )


class TestOsOutrosDesfechos(unittest.TestCase):
    def test_o_tempo_esgotado(self) -> None:
        transporte = _Transporte()
        transporte.levantar = TimeoutError("sem resposta")
        cliente, lig, _ = _cliente(transporte)
        with self.assertRaises(TempoEsgotado):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(lig.linhas()[0]["resultado"], RESULTADO_TIMEOUT)

    def test_o_proxy_inalcancavel(self) -> None:
        transporte = _Transporte()
        transporte.levantar = OSError("ligacao recusada")
        cliente, lig, _ = _cliente(transporte)
        with self.assertRaises(FornecedorFalhou):
            cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(lig.linhas()[0]["resultado"], RESULTADO_ERRO)

    def test_um_papel_que_nao_existe(self) -> None:
        cliente, _, _ = _cliente()
        with self.assertRaises(FornecedorFalhou):
            cliente.chamar("embed", [{"role": "user", "content": "ola"}], CTX)

    def test_o_tecto_do_cliente_excede_o_do_proxy(self) -> None:
        """Desistir antes do proxy fazia o *fallback* do criterio 6 nunca acontecer."""
        transporte = _Transporte()
        cliente, _, _ = _cliente(transporte)
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        _, _, _, timeout = transporte.chamadas[0]
        self.assertGreater(timeout, ALIAS_CHAT.timeout)
        self.assertGreaterEqual(timeout, ALIAS_CHAT.timeout * 3)

    def test_a_chave_virtual_do_tenant_vai_no_cabecalho(self) -> None:
        transporte = _Transporte()
        cliente, _, _ = _cliente(transporte)
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        _, cabecalhos, corpo, _ = transporte.chamadas[0]
        self.assertEqual(cabecalhos["Authorization"], f"Bearer sk-virtual-{TENANT}")
        self.assertEqual(corpo["model"], "kamba-chat", "chama-se o alias, nao o modelo")

    def test_sem_preco_o_custo_e_nulo_e_conta(self) -> None:
        """E o caso de **hoje**: todos os modelos sao `por_decidir` (KAM-040).

        O modelo que vai para a linha e o **declarado** no alias e nao a cadeia
        que o proxy devolveu — `_quem_servio` usa a resposta so para saber *que
        fornecedor* respondeu. Por isso a ausencia de preco exercita-se com um
        alias cujo modelo declarado nao esta na tabela, que e o que acontece
        enquanto for `por_decidir`.
        """
        alias = aliases_mod.Alias(
            "kamba-chat", "chat", 20, ("anthropic",), ("por_decidir",)
        )
        lig = _Ligacao()
        met = metricas_mod.MetricasDoAgr()
        cliente = ClienteDeLlm(
            aliases={"chat": alias}, tabela_de_precos=PRECOS,
            porta_de_destinos=destinos_mod.arrancar(destinos_mod.AMBIENTE_STAGING),
            abrir_ligacao=lambda: lig, chave_virtual=lambda t: "sk-x",
            metricas=met,
            transporte=_Transporte((200, _resposta("anthropic/por_decidir"), {})),
        )
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(met.ler().get(metricas_mod.METRICA_LLM_SEM_PRECO), 1)
        self.assertIsNone(
            lig.linhas()[0]["custo_usd"], "nulo e nao zero: zero dizia que foi gratis"
        )


class TestAsContagensDeTokens(unittest.TestCase):
    """O cache esta **dentro** do `prompt_tokens` no esquema do proxy."""

    def test_o_cache_sai_da_entrada(self) -> None:
        cliente, lig, _ = _cliente(
            _Transporte((200, _resposta(entrada=3000, saida=300, cache=1000), {}))
        )
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        linha = lig.linhas()[0]
        self.assertEqual(linha["tokens_in"], 2000, "3000 menos os 1000 de cache")
        self.assertEqual(linha["tokens_cache"], 1000)
        # 2000 a 0,10 + 1000 a 0,01 + 300 a 0,50 = 0,0002 + 0,00001 + 0,00015
        self.assertEqual(linha["custo_usd"], Decimal("0.00036"))

    def test_um_cache_maior_do_que_a_entrada_nao_da_negativo(self) -> None:
        """O `CHECK llm_call_log_tokens_ck` recusaria a linha, no caminho que nao levanta.

        **E conta-se**, que e o achado 12 da revisao adversarial: `cache >
        entrada` e o sinal inequivoco de que o fornecedor reporta o cache **ao
        lado** e nao dentro, e nesse caso a subtraccao subavalia o custo em
        toda a linha. Cortar para zero em silencio deixava uma diferenca de 43%
        invisivel.
        """
        cliente, lig, met = _cliente(
            _Transporte((200, _resposta(entrada=100, saida=10, cache=500), {}))
        )
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertEqual(lig.linhas()[0]["tokens_in"], 0)
        self.assertEqual(
            met.ler().get(metricas_mod.METRICA_LLM_CONTAGEM_INCOERENTE), 1
        )

    def test_um_cache_normal_nao_conta_incoerencia(self) -> None:
        """O canario pelo outro lado: nao se inventa o sinal."""
        cliente, _, met = _cliente(
            _Transporte((200, _resposta(entrada=3000, saida=300, cache=1000), {}))
        )
        cliente.chamar("chat", [{"role": "user", "content": "ola"}], CTX)
        self.assertIsNone(met.ler().get(metricas_mod.METRICA_LLM_CONTAGEM_INCOERENTE))


class TestAParidadeComARevisao0023(unittest.TestCase):
    """As catorze colunas do `registo.py` e as do `GRANT` da revisao `0023`.

    Se divergirem, o `INSERT` rebenta por privilegio e **nao** em silencio — mas
    rebenta em producao. Isto compara-as aqui.
    """

    def test_as_colunas_sao_as_mesmas(self) -> None:
        # A revisao importa `alembic` e `rls`, que nao estao no caminho desta
        # bateria; so se precisa das constantes, e por isso le-se o **AST** em
        # vez de executar o modulo.
        import ast
        import pathlib

        caminho = (
            pathlib.Path(__file__).resolve().parents[3]
            / "db" / "migrations" / "versions" / "0023_llm_call_log.py"
        )
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        colunas = None
        for no in arvore.body:
            if isinstance(no, ast.Assign) and getattr(no.targets[0], "id", "") == "COLUNAS_DO_CHAMADOR":
                colunas = tuple(e.value for e in no.value.elts)
        self.assertIsNotNone(colunas, "a revisao 0023 declara COLUNAS_DO_CHAMADOR")
        self.assertEqual(colunas, registo_mod.COLUNAS)

    def test_os_resultados_sao_os_mesmos(self) -> None:
        """O dominio fechado do `CHECK` e a lista do codigo."""
        import ast
        import pathlib

        from kamba_agr.llm.erros import RESULTADOS

        caminho = (
            pathlib.Path(__file__).resolve().parents[3]
            / "db" / "migrations" / "versions" / "0023_llm_call_log.py"
        )
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        resultados = None
        for no in arvore.body:
            if isinstance(no, ast.Assign) and getattr(no.targets[0], "id", "") == "RESULTADOS":
                resultados = tuple(e.value for e in no.value.elts)
        self.assertEqual(resultados, RESULTADOS)


if __name__ == "__main__":
    unittest.main()
