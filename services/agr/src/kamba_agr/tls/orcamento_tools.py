"""O `request_quote` e o `submit_quote` ligados na ToolLayer (KAM-220).

O dominio e o SQL sao do KAM-123 (`tls/orcamento.py`); o que este modulo
acrescenta e o que a ToolLayer pede a uma tool **ligada**: o modelo dos
argumentos, com `extra="forbid"` e sem os parametros proibidos, e o executor que
fala com a base. A tool passa entao pelos oito passos do §6.1 — o entitlement
`orcamento` no passo 2, os argumentos no 3, a `tool_audit` com os *facts* no 7.

## O que o modelo ve, e o que nunca ve

* `request_quote`: a `oferta`, o `sku` e a quantidade. A `oferta` e o
  identificador opaco que o botao `confirm:{oferta}` cita, um por oferta, e e
  ela que entra na chave do passo 5: com o `sku` na chave, um segundo pedido do
  mesmo artigo nos trinta dias da retencao devolvia o primeiro, e nunca chegava
  ao dono (achado 1 da revisao adversarial do KAM-220). O contacto e a conversa sao os do
  `ToolContext`, e nunca argumentos: um `contact_id` no esquema era um cliente a
  pedir orcamento em nome de outro.
* `submit_quote`: a **referencia** `ORC-…` do pedido, o **texto** do valor tal
  como o dono o escreveu, a validade e as condicoes. **Nao o `quote_id`**: o
  modelo nunca o ve, e e o executor que o resolve dentro do tenant do contexto
  (`por_referencia`), pelo que um `quote_id` forjado nao tem por onde entrar. E o
  `quote_id` e o `fact_id` do `quote_price` (§3.79): num argumento, a guarda da
  `tool_audit` recusava o *fact* por derivar dele. **O valor vai em texto, e nao em centimos**: quem o
  le e o *parser* deterministico do KAM-123 (`regras.ler_valor_do_dono`), e um
  inteiro no esquema era um numero que o modelo podia calcular — «cento e vinte
  mil vezes doze» — e entregar ja feito. Com o texto, uma conta recusa-se no
  *parser* (`valor_com_varios_numeros`).

## Os codigos

A `tool_audit.error_code` tem um `CHECK` fechado (`erros.CODIGOS`), e as recusas
do dominio traduzem-se para ele **sem perder a razao**, que vai no `detalhe`:

| Recusa do dominio | Codigo |
|---|---|
| `fora_do_catalogo`, `desconhecido` | `NOT_FOUND` |
| `sem_orcamentos` | `LIMIT_EXCEEDED` |
| `nao_e_dono` | `TENANT_MISMATCH` |
| `fechado`, `validade_no_passado`, valor e condicoes recusados | `VALIDATION_ERROR` |

O `detalhe` e o codigo do dominio, e nunca um valor nem o texto do dono.

## A porta do *screening* das condicoes (KAM-228)

O `submit_quote` passa ao `responder` um `ScreeningPeloCom` com o sujeito das
condicoes, sobre o `ClienteDoCom` do `KAMBA_COM_URL` — o mesmo cliente das tools
de comercio. Sem COM com quem falar nao ha porta, e o `responder` usa a
`ScreeningPorLigar`, que recusa: umas condicoes nao passam sem ponte.

**As condicoes tem finalidade de transferencia propria**, por decisao do
fundador de 2026-11-20 (opcao B): a `classificacao_de_condicoes`
(`FINALIDADE_DAS_CONDICOES`, KAM-230). O adaptador manda-a ao COM, o COM
confere-a com o sujeito e passa-a ao classificador, e a rota do classificador
consulta o *gate* de destino com ela, e nao com a do papel. Um tenant sem
destino autorizado para ela recusa as condicoes, mesmo com o do catalogo.

**O executor ja corre numa *thread*.** A ToolLayer corre todo o executor em
`asyncio.to_thread` (`camada.py`, `invoke`), e e isso que deixa o ciclo de
eventos do AGR livre para servir o `POST /internal/screening` que o COM chama
durante o `screen`. Com o ciclo preso, o classificador saia por tempo e as
condicoes recusavam sempre. O `test_condicoes_limpas_seguem_pelo_com_e_pelo_classificador`
mede isto pela ToolLayer, com um COM que chama o AGR do ciclo do ensaio, e o
`test_com_o_ciclo_preso_as_condicoes_recusam` e o canario.

**O `screen` cabe no prazo da ToolLayer**, e nao nos 20 s do adaptador. A
ToolLayer corta um `write` aos 8 s (mais a margem): um `screen` de 20 s dava ao
dono um `UPSTREAM_TIMEOUT` com a *thread* ainda viva, e a resposta gravava-se
depois, sem eco nem botao. O tecto do `screen` e o que sobra do **prazo
absoluto** da invocacao (`Pedido.prazo`, que conta do inicio da ToolLayer e nao
do executor, KAM-230) depois da reserva da transaccao; se nao sobrar nada, nao
ha porta, e as condicoes recusam. O prazo viaja com o pedido ao COM e a rota do
classificador.

**O `screen` corre sem a tomada** (KAM-230): o executor larga a ligacao da
ToolLayer enquanto espera pelo COM (`Pedido.sem_tomada`), e outra invocacao
pode usa-la. Volta a toma-la para a transaccao.
"""

from __future__ import annotations

import datetime
import time
from collections.abc import Callable
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from kamba_core.catalogo.screening import PortaDeScreening, ScreeningPorLigar

from ..orcamento import regras
from . import orcamento as repositorio
from . import screening as ponte
from .com import ClienteDoCom
from .erros import LIMIT_EXCEEDED, NOT_FOUND, TENANT_MISMATCH, UPSTREAM_TIMEOUT, VALIDATION_ERROR
from .especificacoes import ErroDeBackend, Executor, Pedido, Resposta

#: O sujeito da `screening_decision` das condicoes (revisao `0074`, KAM-222).
SUJEITO_DAS_CONDICOES: Final = "condicoes"

#: A finalidade de transferencia das condicoes (ADR-008). **Decisao do fundador
#: de 2026-11-20, opcao B** (bloco do KAM-228): as condicoes tem finalidade
#: propria, e **nao** vao ao modelo com a `classificacao_de_catalogo`. A tabela e
#: a do adaptador (`ponte.FINALIDADE_DO_SUJEITO`), que a manda ao COM; o COM
#: confere-a, e a rota do classificador consulta o *gate* com ela (KAM-230).
FINALIDADE_DAS_CONDICOES: Final = ponte.FINALIDADE_DO_SUJEITO[SUJEITO_DAS_CONDICOES]

#: O que fica do prazo da invocacao para retomar a tomada e para a transaccao,
#: depois do `screen`. *Proposta*: a transaccao do `responder` sao tres
#: instrucoes numa linha trancada, e nao se mediu o p99 dela em producao. Baixou
#: de 1,5 s para 1 s com o KAM-230, para que sobre ao classificador folga acima
#: do minimo da rota (`llm/screening.py`, `minimo_s`).
RESERVA_DA_TRANSACCAO_MS: Final = 1_000

_CODIGO_DA_RECUSA: Final = {
    repositorio.FORA_DO_CATALOGO: NOT_FOUND,
    repositorio.DESCONHECIDO: NOT_FOUND,
    repositorio.SEM_ORCAMENTOS: LIMIT_EXCEEDED,
    repositorio.NAO_E_DONO: TENANT_MISMATCH,
}


# Sem *docstring*: a de um modelo Pydantic vai ao esquema e, por ele, ao modelo de
# linguagem (a licao do `get_store_info.py`).
class ArgumentosDeRequestQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oferta: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    quantidade: int | None = Field(default=None, ge=1, le=repositorio.QUANTIDADE_MAXIMA)


class ArgumentosDeSubmitQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referencia: str = Field(pattern=r"^ORC-[A-HJ-NP-R]{8}$")
    valor: str = Field(min_length=1, max_length=64)
    validade_ate: datetime.date | None = None
    condicoes: str | None = Field(default=None, max_length=regras.CONDICOES_MAX)


def _exigir_ligacao(pedido: Pedido) -> None:
    if pedido.ligacao is None:
        raise RuntimeError(
            "as tools do orcamento escrevem na `platform.quote_requests` e precisam "
            "de ligacao: uma especificacao `plataforma` sem tomada e defeito de registo"
        )


def _traduzir(codigo: str) -> ErroDeBackend:
    return ErroDeBackend(_CODIGO_DA_RECUSA.get(codigo, VALIDATION_ERROR), codigo)


def restante_ms(pedido: Pedido, inicio: float) -> float:
    """O que sobra a invocacao, em milissegundos.

    Pelo **prazo absoluto** do `Pedido` (KAM-230), que conta do inicio da
    ToolLayer: os passos 1 a 5 tambem o gastam. Sem prazo — um `Pedido` feito a
    mao num ensaio —, o tecto conta do `inicio` do executor, como antes.
    """
    agora = time.monotonic()
    if pedido.prazo is not None:
        return (pedido.prazo - agora) * 1000
    return pedido.timeout_ms - (agora - inicio) * 1000


def porta_das_condicoes(
    cliente: ClienteDoCom | None, pedido: Pedido, restante: float
) -> PortaDeScreening | None:
    """A porta do `screen` para as condicoes deste pedido, ou `None` (fecha).

    `None` sem cliente, e `None` quando o que sobra a invocacao (`restante`, em
    milissegundos) ja nao deixa tempo ao `screen` depois da reserva da
    transaccao: o `responder` usa entao a `ScreeningPorLigar`, e as condicoes
    recusam com `screening_indisponivel`. A vertical do `actor` e a do turno, e
    nao uma fixa.
    """
    if cliente is None:
        return None
    tecto = int(min(ponte.TEMPO_MAXIMO_MS, restante - RESERVA_DA_TRANSACCAO_MS))
    if tecto <= 0:
        return None
    return ponte.ScreeningPeloCom(
        cliente=cliente,
        sujeito_tipo=SUJEITO_DAS_CONDICOES,
        vertical=pedido.ctx.vertical,
        timeout_ms=tecto,
    )


def executores(
    relogio: Callable[[], datetime.datetime] | None = None,
    *,
    cliente_do_com: ClienteDoCom | None = None,
) -> dict[str, Executor]:
    """Os dois executores, com o relogio do processo (ou o de um ensaio).

    O `cliente_do_com` e o do `KAMBA_COM_URL` (KAM-228): sem ele, as condicoes
    de uma resposta recusam, e uma resposta sem condicoes segue.
    """
    agora = relogio or (lambda: datetime.datetime.now(datetime.UTC))

    def request_quote(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeRequestQuote)
        try:
            resultado = repositorio.pedir(
                pedido.ligacao,
                pedido.ctx.tenant_id,
                pedido.ctx.contact_id,
                pedido.ctx.conversation_id,
                args.sku,
                args.quantidade,
                agora(),
            )
        except repositorio.OrcamentoRecusadoError as erro:
            raise _traduzir(erro.codigo) from None
        # **Sem *facts***: o pedido nao tem numero nenhum que o cliente possa
        # ler — o valor e do dono, e chega noutra mensagem. A referencia `ORC-…`
        # nao tem digitos.
        return Resposta(
            data={
                "quote_id": resultado.quote_id,
                "referencia": regras.referencia_interna(resultado.quote_id),
                "novo": resultado.novo,
            }
        )

    def submit_quote(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeSubmitQuote)
        inicio = time.monotonic()
        instante = agora()
        try:
            valor_minor = regras.ler_valor_do_dono(args.valor)
            quote_id = repositorio.por_referencia(pedido.ligacao, pedido.ctx.tenant_id, args.referencia)
            if quote_id is None:
                # Nenhum, ou mais de um, aberto **deste** tenant com aquela
                # referencia: o dono escolhe pela lista, e nada se grava.
                raise repositorio.OrcamentoRecusadoError(repositorio.DESCONHECIDO)
            porta = porta_das_condicoes(cliente_do_com, pedido, restante_ms(pedido, inicio))
            # O `screen` corre **sem a tomada** (KAM-230): o executor larga a
            # ligacao enquanto espera pelo COM e pelo classificador, e retoma uma
            # para a transaccao. Sem condicoes nao ha `screen`, e nada se larga.
            limpas, ligacao = pedido.sem_tomada(
                lambda: regras.conferir_condicoes(
                    args.condicoes,
                    screening=porta if porta is not None else ScreeningPorLigar(),
                    tenant_id=pedido.ctx.tenant_id,
                    quote_id=quote_id,
                )
            ) if regras.ha_condicoes(args.condicoes) else (None, pedido.ligacao)
            if (
                pedido.prazo is not None
                and time.monotonic() >= pedido.prazo - RESERVA_DA_TRANSACCAO_MS / 2000
            ):
                # Sem metade da reserva para a transaccao, a resposta arriscava
                # gravar-se depois de a ToolLayer dar `UPSTREAM_TIMEOUT` ao dono,
                # sem eco nem botao (KAM-230). **Estreita a janela, e nao a
                # fecha**: uma transaccao mais lenta do que o que sobra mais a
                # margem da camada ainda grava depois (achado 8 da revisao).
                raise ErroDeBackend(UPSTREAM_TIMEOUT, "o screen das condicoes passou do prazo")
            resposta = repositorio.gravar_a_resposta_do_dono(
                ligacao,
                pedido.ctx.tenant_id,
                pedido.ctx.contact_id,
                quote_id,
                valor_minor,
                args.validade_ate,
                limpas,
                instante,
            )
        except repositorio.OrcamentoRecusadoError as erro:
            raise _traduzir(erro.codigo) from None
        except regras.ValorRecusadoError as erro:
            raise ErroDeBackend(VALIDATION_ERROR, erro.codigo) from None
        except ValueError as erro:
            # O `conferir_condicoes` levanta `ValueError(codigo)`. Um `ValueError`
            # que nao seja uma das tres recusas e defeito, e sobe.
            codigo = erro.args[0] if erro.args else ""
            if codigo not in regras.RECUSAS_DAS_CONDICOES:
                raise
            raise ErroDeBackend(VALIDATION_ERROR, codigo) from None
        sku = resposta.sku
        return Resposta(
            data={
                "quote_id": resposta.quote_id,
                "referencia": regras.referencia_interna(resposta.quote_id),
                "action_id": resposta.action_id,
                "previsao": resposta.previsao,
            },
            # O `quote_price` e a validade: e o que a `tool_audit` guarda e o que
            # sustenta o valor da pre-visualizacao no validador (ADR-007).
            facts=repositorio.facts_da_proposta(
                resposta.quote_id, sku, resposta.valor_minor, resposta.validade_ate, instante
            ),
        )

    return {"request_quote": request_quote, "submit_quote": submit_quote}


MODELOS: Final = {
    "request_quote": ArgumentosDeRequestQuote,
    "submit_quote": ArgumentosDeSubmitQuote,
}
