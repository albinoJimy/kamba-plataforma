"""As quatro tools do modulo `catalogo` ligadas na ToolLayer (KAM-119, `docs/tecnica/02` §21.3).

O dominio e o pipeline do KAM-049 (`kamba_core.catalogo`), montado em
`catalogo/montagem.py`; o que este modulo acrescenta e o que a ToolLayer pede a
uma tool **ligada**: o modelo dos argumentos, com `extra="forbid"`, e o executor.
Cada uma passa pelos oito passos do §6.1 — o entitlement `catalogo` no passo 2,
os argumentos no 3, a `tool_audit` no 7.

| Tool | Classe | O que faz |
|---|---|---|
| `create_product_draft` | `write`, passo 4 dispensado | uma foto nova (`receber`), uma resposta do dono (`responder`), «e o mesmo produto?» (`mesmo_produto`) |
| `ask_missing_fields` | `read` | as perguntas em aberto de uma ingestao, sem as contar |
| `publish_product` | `write`, botao `confirm:{action_id}` | a etapa 9 do KAM-049 (`confirmar`), com o screening da publicacao e o `assertPublishable` do COM |
| `get_catalog_status` | `read` | as contagens, como *facts* `count`, e os rascunhos a espera do dono |

## O que o modelo nunca escreve

**O preco.** O `create_product_draft` nao aceita `preco` nas `respostas` (o
modelo recusa-o no passo 3): o preco entra so por `preco_confirmado`, um inteiro
em centimos que **so o no do grafo** preenche, e so a partir do botao
`preco:{ingestao}:{centimos}` do eco (`catalogo/regras.py`). Nenhum no deste
grafo pede argumentos a um modelo — o grafo do dono e deterministico —, mas a
barreira esta no esquema e nao na disciplina de quem chama.

**A declaracao «sintetica»** do KAM-049 tambem nao: e da composicao do processo
(`PortasDoCatalogo.sintetica`).

## O botao de publicar e o da `owner_actions`

Decisao do fundador (opcao A, como no KAM-123): o `publish_product` cita o
`action_id` de uma accao `aprovar_conteudo` da `owner_actions` do KAM-118, cujo
`ref` e `{ingestao}:{versao_texto}`. O `create_product_draft` propoe-na quando a
ingestao chega a `rascunho`; a versao do resumo vai no `ref`, pelo que uma
correccao depois do resumo pede botao novo (a `UNIQUE (tenant_id, tipo, ref)`
devolveria a accao antiga a um `ref` repetido — achado 7 do KAM-118). O passo 4
confere que o botao cita o `action_id` dos argumentos; o executor confere que a
accao esta `confirmada`, e deste contacto, e e do tipo certo.

## Os codigos

| Recusa | Codigo |
|---|---|
| ingestao ou accao inexistente neste tenant | `NOT_FOUND` |
| confirmacao fora de estado, de outra versao, com campos em falta | `VALIDATION_ERROR` (`confirmacao_recusada`) |
| o screening da publicacao nao permitiu | `VALIDATION_ERROR` (`categoria_bloqueada`) |
| o screening nao respondeu | `UPSTREAM_DOWN` (`screening_indisponivel`) |
| a foto nao tem por onde entrar (porta por ligar) | `UPSTREAM_DOWN` (`foto_indisponivel`) |
| limitacao de T&S em vigor | `VALIDATION_ERROR` (`loja_limitada`) |
| accao de outro contacto | `TENANT_MISMATCH` |

O `detalhe` e o codigo do dominio, e nunca um valor nem o texto do dono.
"""

from __future__ import annotations

import datetime
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Any, Final

from kamba_core import tenant_guard
from kamba_core.catalogo import estados
from kamba_core.catalogo.extraccao import DONO_TEXTO, DONO_VOZ
from kamba_core.catalogo.pipeline import (
    MOTIVO_CATEGORIA,
    SUGESTAO,
    ConfirmacaoDoDono,
    ConfirmacaoRecusada,
    IngestaoInexistente,
    PublicacaoRecusada,
    Resultado,
    ServicoDeIngestao,
    resumo,
    versao_do_texto,
)
from kamba_core.catalogo.repositorio import ConflitoDeEstado, Ingestao, LojaLimitada
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..catalogo import regras
from ..catalogo.montagem import FotoPorLigarError, PortasDoCatalogo
from ..dono import accoes
from .erros import NOT_FOUND, TENANT_MISMATCH, UPSTREAM_DOWN, UPSTREAM_TIMEOUT, VALIDATION_ERROR, Fact
from .especificacoes import ErroDeBackend, Executor, Pedido, Resposta

#: O tipo da accao sensivel que publica um produto (`owner_actions.tipo`, §21.2).
TIPO_DA_ACCAO: Final = "aprovar_conteudo"

#: Os campos que uma resposta do dono pode ter. **Sem `preco`**: ver o cabecalho.
_CAMPO: Final = r"^(?!preco$)[a-z_]{2,20}$"

_UUID: Final = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

#: Quantos rascunhos a espera do dono o `get_catalog_status` devolve. *Proposta*:
#: cobre o lote de dez fotos do criterio 4 com folga, e e com esta lista que o
#: grafo resolve uma referencia `PRD-…` (a mensagem ao dono mostra so cinco).
LIMITE_DE_PENDENTES: Final = 20

#: Os estados de cada contagem do criterio 9.
RASCUNHOS: Final = (estados.A_PERGUNTAR, estados.RASCUNHO)
PUBLICADOS: Final = (estados.PUBLICADA,)
BLOQUEADOS: Final = (estados.BLOQUEADA_CATEGORIA, estados.BLOQUEADA_GATE)

SQL_CONTAGENS: Final = (
    "SELECT estado, count(*) FROM platform.catalog_ingestions "
    "WHERE tenant_id = %s::uuid GROUP BY estado"
)

#: Os rascunhos a espera do dono, os mais recentes primeiro.
SQL_PENDENTES: Final = (
    "SELECT id::text, estado FROM platform.catalog_ingestions "
    "WHERE tenant_id = %s::uuid AND estado IN ('a_perguntar', 'rascunho') "
    "ORDER BY atualizado_at DESC, id LIMIT %s"
)

#: A accao do botao de publicar, lida no tenant da invocacao.
SQL_ACCAO: Final = (
    "SELECT tipo, ref, estado, contact_id::text, confirmada_at FROM platform.owner_actions "
    "WHERE tenant_id = %s::uuid AND action_id = %s::uuid"
)


# Sem *docstrings*: a de um modelo Pydantic vai ao esquema e, por ele, ao modelo
# de linguagem (a licao do `get_store_info.py`).
class ArgumentosDeCreateProductDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    ingestao: str | None = Field(default=None, pattern=_UUID)
    respostas: dict[str, str] | None = Field(default=None, max_length=3)
    preco_confirmado: int | None = Field(default=None, ge=100, le=10**14)
    mesmo_produto: bool | None = None
    voz: bool = False

    @model_validator(mode="after")
    def _uma_operacao(self) -> ArgumentosDeCreateProductDraft:
        if (self.media_id is None) == (self.ingestao is None):
            raise ValueError("ou uma foto, ou uma ingestao")
        operacoes = [x for x in (self.respostas, self.preco_confirmado, self.mesmo_produto) if x is not None]
        if self.media_id is not None and operacoes:
            raise ValueError("uma foto nova nao leva respostas")
        if self.ingestao is not None and len(operacoes) != 1:
            raise ValueError("uma ingestao leva uma operacao so")
        for campo, texto in (self.respostas or {}).items():
            if not re.fullmatch(_CAMPO, campo) or not texto or len(texto) > 500:
                raise ValueError("resposta fora da forma")
        return self


class ArgumentosDeAskMissingFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ingestao: str = Field(pattern=_UUID)


class ArgumentosDePublishProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(pattern=_UUID)


class ArgumentosDeGetCatalogStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ a vista


def _produto(linha: Ingestao) -> dict[str, Any]:
    return {n: c for n, c in linha.campos.items() if n != SUGESTAO}


def _sugestao(linha: Ingestao) -> str | None:
    c = linha.campos.get(SUGESTAO)
    return c.valor if c is not None and isinstance(c.valor, str) else None


def _iso(instante: datetime.datetime) -> str:
    return instante.astimezone(datetime.UTC).isoformat()


def vista(linha: Ingestao, *, motivo: str | None = None, mesmo_produto_que: str | None = None) -> dict[str, Any]:
    """O que o grafo precisa de uma ingestao para falar com o dono. Sem texto da foto em registos."""
    dados: dict[str, Any] = {
        "ingestao": linha.id,
        "referencia": regras.referencia_do_produto(linha.id),
        "estado": linha.estado,
        "motivo": motivo,
        "mesmo_produto_que": mesmo_produto_que,
        "perguntas": [],
        "resumo": None,
        "versao_texto": None,
    }
    if linha.estado == estados.A_PERGUNTAR:
        dados["perguntas"] = [
            {"campo": p.campo, "texto": p.texto, "sugestao": p.sugestao}
            for p in regras.perguntas_em_aberto(_produto(linha), linha.perguntas_feitas, _sugestao(linha))
        ]
    if linha.estado in (estados.RASCUNHO, estados.PUBLICADA):
        texto = resumo(_produto(linha))
        dados["resumo"] = texto
        dados["versao_texto"] = versao_do_texto(texto)
    return dados


def _facts_do_produto(linha: Ingestao, agora: datetime.datetime) -> tuple[Fact, ...]:
    """O preco e o stock que o resumo mostra, como *facts*: os numeros sao do dono."""
    produto = _produto(linha)
    facts: list[Fact] = []
    preco = produto.get("preco")
    if preco is not None and isinstance(preco.valor, str) and preco.valor.isdigit():
        facts.append(Fact(str(uuid.uuid4()), "price", int(preco.valor), _iso(agora), linha.sku))
    stock = produto.get("stock")
    if stock is not None and isinstance(stock.valor, str) and stock.valor.isdigit():
        facts.append(Fact(str(uuid.uuid4()), "stock", int(stock.valor), _iso(agora), linha.sku))
    return tuple(facts)


# ------------------------------------------------------------------ os executores


def _exigir_ligacao(pedido: Pedido) -> None:
    if pedido.ligacao is None:
        raise RuntimeError(
            "as tools do catalogo escrevem na `platform.catalog_ingestions` e precisam "
            "de ligacao: uma especificacao `plataforma` sem tomada e defeito de registo"
        )


def ler_accao(ligacao: Any, tenant_id: str, action_id: str) -> tuple[str, str, str, str, Any] | None:
    """`(tipo, ref, estado, contact_id, confirmada_at)` de uma accao **deste** tenant, ou `None`."""
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_ACCAO, (tenant_id, action_id))
        linha = cursor.fetchone()
    if linha is None:
        return None
    tipo, ref, estado, contacto, confirmada_at = linha
    return str(tipo), str(ref), str(estado), str(contacto).lower(), confirmada_at


def ler_estado(ligacao: Any, tenant_id: str) -> tuple[dict[str, int], list[tuple[str, str]]]:
    """As contagens por estado e os rascunhos a espera do dono, numa transaccao so."""
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_CONTAGENS, (tenant_id,))
        por_estado = {str(e): int(n) for e, n in cursor.fetchall()}
        cursor.execute(SQL_PENDENTES, (tenant_id, LIMITE_DE_PENDENTES))
        pendentes = [(str(i), str(e)) for i, e in cursor.fetchall()]
    return por_estado, pendentes


def _ref_da_accao(ingestao_id: str, versao_texto: str) -> str:
    return f"{ingestao_id}:{versao_texto}"


def _ler_ref(ref: str) -> tuple[str, str] | None:
    casado = re.fullmatch(r"([0-9a-f-]{36}):([0-9a-f]{16})", ref)
    return (casado.group(1), casado.group(2)) if casado else None


def executores(
    portas: PortasDoCatalogo,
    relogio: Callable[[], datetime.datetime] | None = None,
) -> dict[str, Executor]:
    """Os quatro executores, sobre as portas do processo (ou as de um ensaio)."""
    agora = relogio or (lambda: datetime.datetime.now(datetime.UTC))

    def _depois(pedido: Pedido, servico: ServicoDeIngestao, resultado: Resultado) -> Resposta:
        linha = resultado.ingestao
        dados = vista(linha, motivo=resultado.motivo, mesmo_produto_que=resultado.mesmo_produto_que)
        instante = agora()
        if linha.estado == estados.RASCUNHO and dados["versao_texto"]:
            # O botao de publicar nasce com o resumo (opcao A do fundador). Um
            # contacto que nao e o dono nao chega aqui (o grafo do dono so corre
            # para `papel='dono'`), e se chegasse o `propor` recusava.
            dados["action_id"] = accoes.propor(
                pedido.ligacao,
                pedido.ctx.tenant_id,
                pedido.ctx.contact_id,
                TIPO_DA_ACCAO,
                _ref_da_accao(linha.id, dados["versao_texto"]),
                instante,
            )
            dados["melhorar_foto"] = bool(portas.enhance.disponivel(pedido.ctx.tenant_id))
            return Resposta(data=dados, facts=_facts_do_produto(linha, instante))
        return Resposta(data=dados)

    def create_product_draft(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeCreateProductDraft)
        tenant = pedido.ctx.tenant_id
        servico = portas.servico(pedido.ligacao)
        respostas: dict[str, str] = dict(args.respostas or {})
        if args.preco_confirmado is not None:
            try:
                respostas = {"preco": regras.texto_canonico(args.preco_confirmado)}
            except ValueError:
                # A forma canonica nao se le de volta ao valor do eco: nada se grava.
                raise ErroDeBackend(VALIDATION_ERROR, "preco_recusado") from None
        try:
            if args.media_id is not None:
                resultado = servico.receber(tenant, args.media_id, sintetica=portas.sintetica)
            elif args.mesmo_produto is not None:
                assert args.ingestao is not None
                resultado = servico.mesmo_produto(
                    tenant, args.ingestao, e_o_mesmo=args.mesmo_produto, sintetica=portas.sintetica
                )
            else:
                assert args.ingestao is not None
                resultado = servico.responder(
                    tenant,
                    args.ingestao,
                    respostas,
                    # O `turn_id` e o `wamid`: a mesma mensagem entregue duas
                    # vezes nao conta duas respostas (KAM-049).
                    mensagem_id=pedido.ctx.turn_id,
                    fonte=DONO_VOZ if args.voz else DONO_TEXTO,
                )
        except IngestaoInexistente:
            raise ErroDeBackend(NOT_FOUND, "ingestao_desconhecida") from None
        except FotoPorLigarError:
            raise ErroDeBackend(UPSTREAM_DOWN, "foto_indisponivel") from None
        except LojaLimitada:
            raise ErroDeBackend(VALIDATION_ERROR, "loja_limitada") from None
        except ConflitoDeEstado:
            raise ErroDeBackend(UPSTREAM_TIMEOUT, "ingestao_mudou") from None
        except ErroDeBackend:
            # O Registo recusou ou caiu **depois** de a ingestao ser gravada
            # (`rascunho` grava-se primeiro). A ingestao diz a verdade, e a
            # publicacao volta a sincronizar o Registo (`_sincronizar_registo`).
            assert args.ingestao is not None or args.media_id is not None
            linha = (
                servico.repositorio.ler(tenant, args.ingestao)
                if args.ingestao is not None
                else servico.repositorio.por_media(tenant, args.media_id or "")
            )
            if linha is None:
                raise
            return _depois(pedido, servico, Resultado(linha))
        return _depois(pedido, servico, resultado)

    def ask_missing_fields(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeAskMissingFields)
        linha = portas.repositorio(pedido.ligacao).ler(pedido.ctx.tenant_id, args.ingestao)
        if linha is None:
            raise ErroDeBackend(NOT_FOUND, "ingestao_desconhecida")
        return Resposta(data=vista(linha))

    def publish_product(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDePublishProduct)
        accao = ler_accao(pedido.ligacao, pedido.ctx.tenant_id, args.action_id)
        if accao is None:
            raise ErroDeBackend(NOT_FOUND, "accao_desconhecida")
        tipo, ref, estado, contacto, confirmada_at = accao
        if contacto != pedido.ctx.contact_id.lower():
            raise ErroDeBackend(TENANT_MISMATCH, "accao_de_outro_contacto")
        lido = _ler_ref(ref)
        if tipo != TIPO_DA_ACCAO or lido is None:
            raise ErroDeBackend(NOT_FOUND, "accao_nao_e_de_produto")
        if estado != "confirmada" or confirmada_at is None:
            raise ErroDeBackend(VALIDATION_ERROR, "accao_por_confirmar")
        ingestao_id, versao_texto = lido
        servico = portas.servico(pedido.ligacao)
        confirmacao = ConfirmacaoDoDono(
            # O dono, e nao a mensagem: o `actor` tem de ser o mesmo quando o
            # mesmo botao repete uma publicacao que o Registo nao recebeu
            # (o caminho de recuperacao do `confirmar`).
            actor=pedido.ctx.contact_id,
            em=confirmada_at,
            versao_texto=versao_texto,
        )
        try:
            resultado = servico.confirmar(pedido.ctx.tenant_id, ingestao_id, confirmacao)
        except IngestaoInexistente:
            raise ErroDeBackend(NOT_FOUND, "ingestao_desconhecida") from None
        except PublicacaoRecusada as recusa:
            if recusa.motivo == MOTIVO_CATEGORIA:
                raise ErroDeBackend(VALIDATION_ERROR, "categoria_bloqueada") from None
            raise ErroDeBackend(UPSTREAM_DOWN, "screening_indisponivel") from None
        except ConfirmacaoRecusada:
            raise ErroDeBackend(VALIDATION_ERROR, "confirmacao_recusada") from None
        except LojaLimitada:
            raise ErroDeBackend(VALIDATION_ERROR, "loja_limitada") from None
        except ConflitoDeEstado:
            raise ErroDeBackend(UPSTREAM_TIMEOUT, "ingestao_mudou") from None
        linha = resultado.ingestao
        return Resposta(data=vista(linha), facts=_facts_do_produto(linha, agora()))

    def get_catalog_status(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        por_estado, lidos = ler_estado(pedido.ligacao, pedido.ctx.tenant_id)
        pendentes = [
            {"ingestao": i, "referencia": regras.referencia_do_produto(i), "estado": e} for i, e in lidos
        ]
        contagens = {
            "rascunhos": sum(por_estado.get(e, 0) for e in RASCUNHOS),
            "publicados": sum(por_estado.get(e, 0) for e in PUBLICADOS),
            "bloqueados": sum(por_estado.get(e, 0) for e in BLOQUEADOS),
        }
        instante = _iso(agora())
        facts = tuple(Fact(str(uuid.uuid4()), "count", valor, instante) for valor in contagens.values())
        return Resposta(data={**contagens, "pendentes": pendentes}, facts=facts)

    return {
        "create_product_draft": create_product_draft,
        "ask_missing_fields": ask_missing_fields,
        "publish_product": publish_product,
        "get_catalog_status": get_catalog_status,
    }


MODELOS: Final[Mapping[str, type[BaseModel]]] = {
    "create_product_draft": ArgumentosDeCreateProductDraft,
    "ask_missing_fields": ArgumentosDeAskMissingFields,
    "publish_product": ArgumentosDePublishProduct,
    "get_catalog_status": ArgumentosDeGetCatalogStatus,
}
