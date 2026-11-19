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
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from ..orcamento import regras
from . import orcamento as repositorio
from .erros import LIMIT_EXCEEDED, NOT_FOUND, TENANT_MISMATCH, VALIDATION_ERROR
from .especificacoes import ErroDeBackend, Executor, Pedido, Resposta

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


def executores(
    relogio: Callable[[], datetime.datetime] | None = None,
) -> dict[str, Executor]:
    """Os dois executores, com o relogio do processo (ou o de um ensaio)."""
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
        instante = agora()
        try:
            valor_minor = regras.ler_valor_do_dono(args.valor)
            quote_id = repositorio.por_referencia(pedido.ligacao, pedido.ctx.tenant_id, args.referencia)
            if quote_id is None:
                # Nenhum, ou mais de um, aberto **deste** tenant com aquela
                # referencia: o dono escolhe pela lista, e nada se grava.
                raise repositorio.OrcamentoRecusadoError(repositorio.DESCONHECIDO)
            resposta = repositorio.responder(
                pedido.ligacao,
                pedido.ctx.tenant_id,
                pedido.ctx.contact_id,
                quote_id,
                valor_minor,
                args.validade_ate,
                args.condicoes,
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
