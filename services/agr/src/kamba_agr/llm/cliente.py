"""O cliente do gateway: o AGR fala por **papeis**, nunca por modelo (KAM-030).

    cliente.chamar("chat", mensagens, ctx)   -> Resposta

## O que este modulo garante, e e a razao de ele existir

**Nenhum SDK de fornecedor entra no AGR.** O bloco di-lo («nenhum import de SDK
de fornecedor no AGR (lint)») e aqui cumpre-se por construcao: isto fala HTTP
com o proxy, no esquema OpenAI-compativel, com `httpx` — que ja esta no fecho de
`services/agr/requirements/runtime.in` desde o KAM-026, pelo que **o gateway nao
acrescenta dependencia nenhuma**. O pacote `litellm` nao entra no AGR: o LiteLLM
e uma imagem por digest, nao uma biblioteca nossa, e isso tambem o poupa ao
*gate* 11 (o `psycopg` LGPL do KAM-026 e o precedente do que acontece quando uma
biblioteca de terceiros entra pelo fecho).

**O grafo nao sabe que modelo correu.** Pede `router` ou `chat`; qual modelo esta
atras disso e `llm/aliases.yaml`, que tem SemVer e *lock* (criterio 7).

## O *gate* de destino corre **antes** da chamada, e para **todos** os fornecedores

E a parte menos obvia e a mais importante. O *fallback* e do router do proxy
(`docs/evidencia/KAM-030-litellm.md` §4): o cliente chama `kamba-chat` e o proxy
pode servir pelo fornecedor de `ordem: 1` **ou** pelo de `ordem: 2`, e o cliente
nao escolhe nem fica a saber de antemao.

Logo, autorizar so o fornecedor de `ordem: 1` deixava o *fallback* mandar dados
para o segundo **sem o *gate* ter sido consultado por ele** — uma transferencia
para um destino que ninguem autorizou, pela porta que este modulo existe para
fechar. Por isso autoriza-se **o conjunto**: se algum fornecedor que o alias pode
alcancar nao estiver autorizado, a chamada **nao sai**. Falha fechada sobre a
uniao, nao sobre a escolha.

A alternativa pesada — o cliente a fazer o *fallback*, consultando o *gate* a
cada tentativa — foi recusada: punha o cliente a reimplementar o que o router faz
(contagem de falhas, *cooldown* de 30 s, `allowed_fails`), e o criterio 3 manda
configurar exactamente esses tres numeros no proxy. Dois disjuntores para o mesmo
backend nunca abrem a horas, que e a licao que o `tls/disjuntor.py` escreveu.

## Sem *streaming*, e isso e deliberado

O `docs/tecnica/02` §15 fala de latencia e o WhatsApp nao mostra texto a aparecer:
uma mensagem sai inteira. *Streaming* obrigava a somar `usage` de *chunks* — que
e onde a contagem de *tokens* se perde — para nenhum ganho visivel ao cliente.
"""

from __future__ import annotations

import dataclasses
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Final

from .. import metricas as metricas_mod
from . import aliases as aliases_mod
from . import destinos as destinos_mod
from . import precos as precos_mod
from . import registo as registo_mod
from .erros import (
    RESULTADO_OK,
    RESULTADO_OK_FALLBACK,
    ErroDeLlm,
    FornecedorFalhou,
    TempoEsgotado,
    classificar,
)

#: A pasta com `aliases.yaml` e `precos.yaml`. Mesmo desenho do
#: `KAMBA_REGISTRY_DIR` do KAM-027: o servico nao sabe onde a arvore esta.
VARIAVEL_DA_PASTA: Final = "KAMBA_LLM_DIR"

#: Onde o proxy escuta, na rede interna. **Nunca um FQDN de fornecedor**: o
#: `services/agr/egress.yaml` tem `destinos: []` e o AGR nao fala com nenhum.
VARIAVEL_DO_PROXY: Final = "KAMBA_LLM_PROXY_URL"
PROXY_POR_OMISSAO: Final = "http://litellm:4000"

#: A referencia da chave virtual do tenant, no cofre (KAM-010). O
#: `ops/secrets-inventory.yaml` declara-a com `instancias: tenant`.
REF_CHAVE_VIRTUAL: Final = "litellm_virtual_key"

#: Margem sobre o tecto do alias, em segundos. O `timeout` de `llm/aliases.yaml`
#: e o que o **proxy** da ao fornecedor; o cliente tem de esperar um pouco mais
#: do que isso, senao desiste antes de o proxy poder comutar e o *fallback* do
#: criterio 6 nunca acontece. E a mesma licao do `MARGEM_DO_TECTO_MS` que a
#: revisao adversarial do KAM-028 obrigou a acrescentar, pelo lado oposto.
#:
#: O valor cobre o pior caso do proxy: tentativa, 1 *retry* (`num_retries: 1`) e
#: o grupo de *fallback* — tres tectos — mais o trajecto na rede interna.
MARGEM_SEGUNDOS: Final = 2.0
TENTATIVAS_DO_PROXY: Final = 3


@dataclasses.dataclass(frozen=True, slots=True)
class ContextoDeChamada:
    """O que a linha de `dat.llm_call_log` precisa de saber, e nada mais.

    **Nao e o `ToolContext`.** Aquele tem oito campos e inclui `contact_id` e
    `conversation_id`; aqui nenhum dos dois entra, porque nenhum entra na tabela.
    Um contexto mais largo do que a tabela era um convite a guardar o que nao se
    deve.
    """

    tenant_id: str
    trace_id: str
    vertical: str | None = None
    no_grafo: str | None = None
    graph_version: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Resposta:
    """O que o grafo recebe. Sem cabecalhos, sem corpo cru."""

    texto: str
    modelo: str
    fornecedor: str
    tokens_in: int
    tokens_out: int
    tokens_cache: int
    custo_usd: Decimal | None
    latencia_ms: int
    resultado: str

    @property
    def usou_fallback(self) -> bool:
        return self.resultado == RESULTADO_OK_FALLBACK


#: O `Alias` e o leitor vivem em `aliases.py`, com o teste de paridade que
#: impede a copia de divergir do `tools/llm_config`.
Alias = aliases_mod.Alias
ler_aliases = aliases_mod.ler


class ClienteDeLlm:
    """O unico caminho do AGR para um modelo (ADR-005).

    `transporte` existe para as baterias: recebe (url, cabecalhos, corpo,
    timeout) e devolve (estado, corpo interpretado, cabecalhos). A omissao usa
    `httpx`, e importa-se **dentro** da funcao para que importar este modulo nao
    exija a dependencia instalada — o mesmo padrao do `ligacao.py` com o
    `pg8000`.
    """

    def __init__(
        self,
        aliases: dict[str, Alias],
        tabela_de_precos: dict[tuple[str, str], precos_mod.Preco],
        porta_de_destinos: destinos_mod.PortaDeDestinos,
        ligacao_do_registo: Any,
        chave_virtual: Callable[[str], str],
        url_do_proxy: str = PROXY_POR_OMISSAO,
        metricas: metricas_mod.MetricasDoAgr | None = None,
        transporte: Callable[..., tuple[int, Any, dict[str, str]]] | None = None,
        agora: Callable[[], float] = time.monotonic,
    ) -> None:
        self._aliases = aliases
        self._precos = tabela_de_precos
        self._destinos = porta_de_destinos
        self._ligacao = ligacao_do_registo
        self._chave_virtual = chave_virtual
        self._url = url_do_proxy.rstrip("/")
        self._metricas = metricas or metricas_mod.METRICAS
        self._transporte = transporte or _transporte_httpx
        self._agora = agora

    def papeis(self) -> tuple[str, ...]:
        return tuple(sorted(self._aliases))

    def chamar(
        self,
        papel: str,
        mensagens: list[dict[str, str]],
        ctx: ContextoDeChamada,
    ) -> Resposta:
        """Chama o modelo do papel. Levanta `ErroDeLlm`; grava sempre uma linha."""
        try:
            alias = self._aliases[papel]
        except KeyError:
            raise FornecedorFalhou(
                f"papel `{papel}` nao esta em `llm/aliases.yaml` "
                f"(ha {sorted(self._aliases)})",
                papel,
            ) from None

        inicio = self._agora()
        # 1. O *gate* de destino, para **todos** os fornecedores que o alias pode
        #    alcancar. Ver a nota do modulo: autorizar so o primeiro deixava o
        #    *fallback* sair para um destino nao autorizado.
        try:
            # O `finalidade_de` tambem levanta `DestinoNegado` — um papel sem
            # finalidade declarada nao tem linha de `tenant_destinations` a
            # consultar —, pelo que tem de estar **dentro** deste `try`: fora
            # dele, essa recusa saia sem linha de registo e sem metrica, que e
            # precisamente o caminho que o criterio 5 fecha.
            finalidade = destinos_mod.finalidade_de(papel)
            for fornecedor in alias.fornecedores:
                self._destinos.autorizar(ctx.tenant_id, fornecedor, finalidade)
        except ErroDeLlm as erro:
            self._metricas.contar(metricas_mod.METRICA_LLM_DESTINO_NEGADO)
            self._falhou(alias, ctx, erro, inicio)
            raise

        # 2. A chamada.
        try:
            estado, corpo, cabecalhos = self._transporte(
                f"{self._url}/chat/completions",
                {
                    "Authorization": f"Bearer {self._chave_virtual(ctx.tenant_id)}",
                    "Content-Type": "application/json",
                },
                {"model": alias.nome, "messages": mensagens},
                alias.timeout * TENTATIVAS_DO_PROXY + MARGEM_SEGUNDOS,
            )
        except TimeoutError as excepcao:
            erro = TempoEsgotado(
                f"o proxy nao respondeu em "
                f"{alias.timeout * TENTATIVAS_DO_PROXY + MARGEM_SEGUNDOS:.0f} s: "
                f"{excepcao}",
                papel,
            )
            self._falhou(alias, ctx, erro, inicio)
            raise erro from excepcao
        except Exception as excepcao:  # noqa: BLE001 — a razao vai na mensagem
            erro = FornecedorFalhou(f"nao se alcancou o proxy: {excepcao}", papel)
            self._falhou(alias, ctx, erro, inicio)
            raise erro from excepcao

        if estado >= 400:
            erro = classificar(estado, corpo, papel)
            self._falhou(alias, ctx, erro, inicio)
            raise erro

        return self._conseguiu(alias, ctx, corpo, cabecalhos, inicio)

    # ------------------------------------------------------------- internos

    def _conseguiu(
        self,
        alias: Alias,
        ctx: ContextoDeChamada,
        corpo: Any,
        cabecalhos: dict[str, str],
        inicio: float,
    ) -> Resposta:
        servido, modelo = self._quem_servio(alias, corpo, cabecalhos)
        tokens_in, tokens_out, tokens_cache = _contagens(corpo)
        preco = self._precos.get((servido, modelo))
        if preco is None:
            self._metricas.contar(metricas_mod.METRICA_LLM_SEM_PRECO)
        custo = precos_mod.custo(preco, tokens_in, tokens_out, tokens_cache)
        resultado = (
            RESULTADO_OK if servido == alias.fornecedores[0] else RESULTADO_OK_FALLBACK
        )
        latencia = self._latencia(inicio)
        resposta = Resposta(
            texto=_texto(corpo),
            modelo=modelo,
            fornecedor=servido,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_cache=tokens_cache,
            custo_usd=custo,
            latencia_ms=latencia,
            resultado=resultado,
        )
        self._metricas.contar(metricas_mod.METRICA_LLM_CHAMADAS, alias.papel)
        self._metricas.medir(metricas_mod.METRICA_LLM_LATENCIA, latencia)
        self._escrever(
            registo_mod.LinhaDeChamada(
                tenant_id=ctx.tenant_id,
                trace_id=ctx.trace_id,
                papel=alias.papel,
                modelo=modelo,
                fornecedor=servido,
                resultado=resultado,
                vertical=ctx.vertical,
                no_grafo=ctx.no_grafo,
                graph_version=ctx.graph_version,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                tokens_cache=tokens_cache,
                custo_usd=custo,
                latencia_ms=latencia,
            )
        )
        return resposta

    def _falhou(
        self,
        alias: Alias,
        ctx: ContextoDeChamada,
        erro: ErroDeLlm,
        inicio: float,
    ) -> None:
        """A linha de uma chamada que nao deu resposta. **Uma por chamada**."""
        self._metricas.contar(metricas_mod.METRICA_LLM_ERROS, erro.resultado)
        # Sem *tokens* e sem custo: nao houve consumo a contar, e numa recusa de
        # destino o `CHECK llm_call_log_negado_sem_consumo` da revisao `0023`
        # recusa a linha se levar algum dos quatro.
        self._escrever(
            registo_mod.LinhaDeChamada(
                tenant_id=ctx.tenant_id,
                trace_id=ctx.trace_id,
                papel=alias.papel,
                # O modelo e o fornecedor **pretendidos**: nao houve chamada,
                # pelo que nao ha servido. Sao os de `ordem: 1`, que e por onde
                # teria comecado.
                modelo=alias.modelos[0],
                fornecedor=alias.fornecedores[0],
                resultado=erro.resultado,
                vertical=ctx.vertical,
                no_grafo=ctx.no_grafo,
                graph_version=ctx.graph_version,
                latencia_ms=self._latencia(inicio),
            )
        )

    def _escrever(self, linha: registo_mod.LinhaDeChamada) -> None:
        if not registo_mod.escrever(self._ligacao, linha):
            # Nao levanta: ver o ponto 2 da nota do `registo.py`. O que fica e a
            # metrica, para que a perda seja visivel num painel.
            self._metricas.contar(metricas_mod.METRICA_LLM_REGISTO_FALHOU)

    def _latencia(self, inicio: float) -> int:
        return max(0, int((self._agora() - inicio) * 1000))

    def _quem_servio(
        self, alias: Alias, corpo: Any, cabecalhos: dict[str, str]
    ) -> tuple[str, str]:
        """Que fornecedor respondeu, e com que modelo.

        **Nao se adivinha pelo `ordem: 1`.** Com o *fallback* do router, assumir o
        primeiro fazia uma chamada servida pelo segundo aparecer no registo como
        tendo ido para o primeiro — um registo de transferencia a apontar para o
        destino errado, que e pior do que nao ter registo.

        Duas vias, por esta ordem, e as duas medidas: o `model` da resposta, que
        o proxy devolve com o prefixo do fornecedor; e o cabecalho
        `x-litellm-model-group`, que nomeia o grupo
        (`kamba-chat` ou `kamba-chat-fallback2`). Nenhuma das duas disponivel, a
        chamada conta em `agr_llm_servidor_desconhecido_total` e registra-se o
        `ordem: 1` — a unica coisa que se pode dizer — com o contador a tornar
        isso visivel.
        """
        prefixos = {
            aliases_mod.prefixo_de(f): (f, m)
            for f, m in zip(alias.fornecedores, alias.modelos, strict=True)
        }
        modelo_bruto = ""
        if isinstance(corpo, dict):
            modelo_bruto = str(corpo.get("model") or "")
        prefixo = modelo_bruto.split("/", 1)[0] if "/" in modelo_bruto else ""
        if prefixo in prefixos:
            return prefixos[prefixo]

        grupo = cabecalhos.get("x-litellm-model-group", "")
        for indice, fornecedor in enumerate(alias.fornecedores, start=1):
            if grupo and grupo == aliases_mod.nome_do_grupo(alias.nome, indice):
                return fornecedor, alias.modelos[indice - 1]

        self._metricas.contar(metricas_mod.METRICA_LLM_SERVIDOR_DESCONHECIDO)
        return alias.fornecedores[0], alias.modelos[0]


def _texto(corpo: Any) -> str:
    if not isinstance(corpo, dict):
        return ""
    escolhas = corpo.get("choices") or []
    if not escolhas or not isinstance(escolhas[0], dict):
        return ""
    mensagem = escolhas[0].get("message") or {}
    return str(mensagem.get("content") or "") if isinstance(mensagem, dict) else ""


def _contagens(corpo: Any) -> tuple[int, int, int]:
    """`(tokens_in, tokens_out, tokens_cache)`, com o cache **subtraido** da entrada.

    O OpenAI reporta `cached_tokens` **dentro** de `prompt_tokens`; a Anthropic
    reporta `cache_read_input_tokens` **ao lado** de `input_tokens`. O proxy
    normaliza para o esquema do OpenAI, pelo que o cache esta dentro — e por isso
    subtrai-se, senao o custo contava os mesmos *tokens* a duas tarifas.

    A subtraccao e **defensiva** (`max(0, ...)`): esta assimetria por fornecedor
    esta NAO VERIFICADA (nao ha modelo escolhido nem chave para medir), e um
    `prompt_tokens` menor do que o cache dava um negativo que o
    `CHECK llm_call_log_tokens_ck` recusaria — a linha de registo perdia-se por
    uma conta, no caminho que nao pode levantar. Declarado em
    `docs/dividas-documentais.md`, credor KAM-040.
    """
    if not isinstance(corpo, dict):
        return 0, 0, 0
    uso = corpo.get("usage") or {}
    if not isinstance(uso, dict):
        return 0, 0, 0
    entrada = int(uso.get("prompt_tokens") or 0)
    saida = int(uso.get("completion_tokens") or 0)
    detalhe = uso.get("prompt_tokens_details") or {}
    cache = int(detalhe.get("cached_tokens") or 0) if isinstance(detalhe, dict) else 0
    return max(0, entrada - cache), saida, cache


def _transporte_httpx(
    url: str, cabecalhos: dict[str, str], corpo: dict[str, Any], timeout: float
) -> tuple[int, Any, dict[str, str]]:
    """O transporte por omissao. `httpx` ja esta no fecho desde o KAM-026."""
    import httpx

    try:
        resposta = httpx.post(url, headers=cabecalhos, json=corpo, timeout=timeout)
    except httpx.TimeoutException as excepcao:
        raise TimeoutError(str(excepcao)) from excepcao
    try:
        interpretado: Any = resposta.json()
    except ValueError:
        interpretado = resposta.text[:500]
    return (
        resposta.status_code,
        interpretado,
        {chave.lower(): valor for chave, valor in resposta.headers.items()},
    )
