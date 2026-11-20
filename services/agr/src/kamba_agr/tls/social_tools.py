"""As tools do modulo `social` ligadas na ToolLayer (KAM-121, `docs/tecnica/02` §21.3).

| Tool | Classe | O que faz |
|---|---|---|
| `get_brand_profile` | `read` | o perfil, se esta completo, e a proxima pergunta |
| `update_brand_profile` | `write`, passo 4 dispensado | uma resposta do dono a uma pergunta do perfil (decisao 2 do bloco) |
| `generate_calendar` | `write`, passo 4 dispensado | o calendario da semana seguinte, 3 a 7 itens; «NOVA» regenera |
| `generate_caption` | `write`, passo 4 dispensado | a legenda de um item, pelas quatro barreiras e pelo screening |

As tres de escrita **so gravam** rascunhos na nossa base e nada sai para fora
— nem para o cliente, nem para uma rede social: a dispensa do passo 4 e a dos
precedentes do KAM-220 e do KAM-119, com a razao escrita na especificacao. A
aprovacao do dono e a entrega sao do KAM-122 (`request_approval`, com o botao
`confirm:{action_id}` da accao `aprovar_conteudo`).

## Nao ha tool de publicacao, e isso e criterio

O modulo tem estas quatro, mais as duas do KAM-122 (`generate_art`,
`request_approval`). Nenhuma publica, agenda numa rede ou envia a terceiros:
o dono publica manualmente (D13). O `test_nao_ha_tool_de_publicacao_no_social`
enumera o catalogo pelo modulo e recusa um nome com cara de publicacao.

## O tenant e o do contexto, e a categoria e a do tenant

O screening (KAM-088) corre com `categoria_declarada` `None`, que e a categoria
**declarada no onboarding** do tenant, e nao a do perfil de marca: o perfil e
texto do dono, e um dono nao desce a propria categoria escrevendo outra.

## Os codigos

| Recusa | Codigo |
|---|---|
| resposta ao perfil fora da forma | `VALIDATION_ERROR` (o motivo do `regras`) |
| perfil incompleto | `VALIDATION_ERROR` (`perfil_incompleto`) |
| item inexistente neste tenant | `NOT_FOUND` (`item_desconhecido`) |
| item ja fora de rascunho | `VALIDATION_ERROR` (`item_fechado`) |
| legenda recusada pelas barreiras | `VALIDATION_ERROR` (`faltam_factos`, `alegacao`, `pt_br`, `fora_da_forma`) |
| o screening bloqueou a legenda | `VALIDATION_ERROR` (`categoria_bloqueada`) |
| `posts_mes` esgotado | `LIMIT_EXCEEDED` (`sem_publicacoes`) |
| o screening, o gerador ou a politica nao responderam | `UPSTREAM_DOWN` (`screening_indisponivel`, `legendas_por_ligar`, `gerador_indisponivel`, `politica_indisponivel`) |
| outra escrita concorrente | `UPSTREAM_TIMEOUT` (`perfil_mudou`, `item_mudou`) |

O `detalhe` e um codigo, nunca texto do dono.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from kamba_core.catalogo.screening import PERMITIDA, PortaDeScreening
from pydantic import BaseModel, ConfigDict, Field

from ..social import regras
from ..social.geracao import GeradorDeLegendas, GeradorPorLigar, GeradorPorLigarError, PedidoDeLegenda, Recusa, gerar_legenda
from ..social.politicas import Alegacoes, Lexico, PoliticaIndisponivelError
from ..social.repositorio import (
    RASCUNHO,
    ItemMudouError,
    ItemNovo,
    PerfilMudouError,
    RepositorioSocial,
    SemPublicacoesError,
    vista_do_item,
)
from .erros import LIMIT_EXCEEDED, NOT_FOUND, UPSTREAM_DOWN, UPSTREAM_TIMEOUT, VALIDATION_ERROR
from .especificacoes import ErroDeBackend, Executor, Pedido, Resposta

BLOQUEADA: Final = "bloqueada"
CONDICIONAL: Final = "condicional"


# Sem *docstrings*: a de um modelo Pydantic vai ao esquema e, por ele, ao modelo.
class ArgumentosDeGetBrandProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArgumentosDeUpdateBrandProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campo: Literal["nome", "categoria", "tom", "cores", "publico", "slots", "factos"] | None = None
    resposta: str | None = Field(default=None, min_length=1, max_length=1500)


class ArgumentosDeGenerateCalendar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nova: bool = False


class ArgumentosDeGenerateCaption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referencia: str = Field(pattern=regras.FORMA_DA_REFERENCIA)
    instrucao: str | None = Field(default=None, min_length=1, max_length=300)


MODELOS: Final[Mapping[str, type[BaseModel]]] = {
    "get_brand_profile": ArgumentosDeGetBrandProfile,
    "update_brand_profile": ArgumentosDeUpdateBrandProfile,
    "generate_calendar": ArgumentosDeGenerateCalendar,
    "generate_caption": ArgumentosDeGenerateCaption,
}


def _lexico_por_omissao() -> Lexico:
    return Lexico.carregar()


def _alegacoes_por_omissao() -> Alegacoes:
    return Alegacoes.carregar()


@dataclass(frozen=True)
class PortasDoSocial:
    """O que as tools sociais precisam do processo, ou de um ensaio."""

    repositorio: Callable[[Any], RepositorioSocial]
    screening: PortaDeScreening
    gerador: GeradorDeLegendas = field(default_factory=GeradorPorLigar)
    lexico: Callable[[], Lexico] = _lexico_por_omissao
    alegacoes: Callable[[], Alegacoes] = _alegacoes_por_omissao


# ------------------------------------------------------------------ a vista


def proxima(perfil: regras.Perfil | None) -> dict[str, Any] | None:
    """A proxima pergunta do perfil, com os botoes do tom quando e a do tom."""
    campo = regras.CAMPOS_OBRIGATORIOS[0] if perfil is None else perfil.proxima_pergunta()
    if campo is None:
        return None
    botoes = [regras.botao_do_tom(t) for t in regras.TONS] if campo == "tom" else []
    return {"campo": campo, "texto": regras.PERGUNTAS[campo], "botoes": botoes}


def vista_do_perfil(perfil: regras.Perfil | None) -> dict[str, Any]:
    return {
        "existe": perfil is not None,
        "perfil": perfil.vista() if perfil is not None else None,
        "completo": perfil is not None and perfil.completo,
        "em_falta": list(perfil.em_falta() if perfil is not None else regras.CAMPOS_OBRIGATORIOS),
        "proxima": proxima(perfil),
    }


def vista_do_calendario(calendario: Any, novo: bool) -> dict[str, Any]:
    return {
        "calendar_id": calendario.calendar_id,
        "semana_iso": calendario.semana_iso,
        "geracao": calendario.geracao,
        "decisao": calendario.decisao,
        "novo": novo,
        "itens": [vista_do_item(i, regras.referencia_do_item(i.content_item_id)) for i in calendario.itens],
    }


# ------------------------------------------------------------------ os executores


def _exigir_ligacao(pedido: Pedido) -> None:
    if pedido.ligacao is None:
        raise RuntimeError(
            "as tools do social escrevem na nossa base e precisam de ligacao: uma "
            "especificacao `plataforma` sem tomada e defeito de registo"
        )


def _screen(portas: PortasDoSocial, tenant: str, sujeito_ref: str, textos: list[str]) -> Any:
    try:
        return portas.screening.screen(tenant, sujeito_ref, None, textos)
    except Exception:  # noqa: BLE001 — qualquer falha e fechada, e sem texto
        raise ErroDeBackend(UPSTREAM_DOWN, "screening_indisponivel") from None


def executores(
    portas: PortasDoSocial,
    relogio: Callable[[], datetime.datetime] | None = None,
) -> dict[str, Executor]:
    """Os quatro executores, sobre as portas do processo (ou as de um ensaio)."""
    agora = relogio or (lambda: datetime.datetime.now(datetime.UTC))

    def get_brand_profile(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        perfil = portas.repositorio(pedido.ligacao).ler_perfil(pedido.ctx.tenant_id)
        return Resposta(data=vista_do_perfil(perfil))

    def update_brand_profile(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeUpdateBrandProfile)
        if (args.campo is None) != (args.resposta is None):
            raise ErroDeBackend(VALIDATION_ERROR, "campo_e_resposta_juntos")
        repositorio = portas.repositorio(pedido.ligacao)
        tenant = pedido.ctx.tenant_id
        lido = repositorio.ler_perfil(tenant)
        base = lido if lido is not None else regras.Perfil(tenant_id=tenant)
        if args.campo is None:
            # Comecar a conversa: o perfil existe, vazio, e a primeira pergunta
            # e a do nome. Idempotente: um perfil que ja existe nao muda.
            if lido is None:
                try:
                    base = repositorio.gravar_perfil(base, None)
                except PerfilMudouError:
                    base = repositorio.ler_perfil(tenant) or base
            return Resposta(data=vista_do_perfil(base))
        assert args.resposta is not None
        try:
            valor = regras.ler_resposta(args.campo, args.resposta, regras.dia_local(agora()))
            novo = regras.com_resposta(base, args.campo, valor)
        except regras.RespostaRecusadaError as recusa:
            raise ErroDeBackend(VALIDATION_ERROR, recusa.motivo) from None
        try:
            gravado = repositorio.gravar_perfil(novo, lido.versao if lido is not None else None)
        except PerfilMudouError:
            raise ErroDeBackend(UPSTREAM_TIMEOUT, "perfil_mudou") from None
        return Resposta(data=vista_do_perfil(gravado))

    def generate_calendar(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeGenerateCalendar)
        repositorio = portas.repositorio(pedido.ligacao)
        tenant = pedido.ctx.tenant_id
        perfil = repositorio.ler_perfil(tenant)
        if perfil is None or not perfil.completo:
            raise ErroDeBackend(VALIDATION_ERROR, "perfil_incompleto")
        semana = regras.semana_do_calendario(agora())
        activo = repositorio.calendario(tenant, semana)
        if activo is not None and not args.nova:
            return Resposta(data=vista_do_calendario(activo, novo=False))
        geracao = activo.geracao + 1 if activo is not None else 1
        temas = regras.temas(perfil, semana, geracao)
        calendar_id = str(uuid.uuid4())
        # **Um screen por calendario**, com os temas todos: o tecto de uma
        # `write` (8 s, §6.5) nao cabe sete chamadas ao classificador. A decisao
        # vale para todos os itens, e uma restritiva nao gera nenhum (criterio 5).
        decisao = _screen(portas, tenant, calendar_id, [t.tema for t in temas])
        if decisao.decisao == BLOQUEADA:
            novos: list[ItemNovo] = []
        else:
            reforcada = decisao.decisao != PERMITIDA
            novos = [
                ItemNovo(
                    content_item_id=str(uuid.uuid4()),
                    tipo=t.tipo,
                    tema=t.tema,
                    agendado_at=t.agendado_at,
                    revisao_reforcada=reforcada,
                    versao_politica=decisao.versao_politica,
                )
                for t in temas
            ]
        calendario, novo = repositorio.abrir(
            tenant, semana, calendar_id, geracao, decisao.decisao, decisao.versao_politica, novos
        )
        return Resposta(data=vista_do_calendario(calendario, novo=novo))

    def generate_caption(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeGenerateCaption)
        repositorio = portas.repositorio(pedido.ligacao)
        tenant = pedido.ctx.tenant_id
        prefixo = regras.prefixo_da_referencia(args.referencia)
        achados = repositorio.itens_por_prefixo(tenant, prefixo or "-")
        if len(achados) != 1:
            raise ErroDeBackend(NOT_FOUND, "item_desconhecido")
        item = achados[0]
        if item.estado != RASCUNHO:
            raise ErroDeBackend(VALIDATION_ERROR, "item_fechado")
        perfil = repositorio.ler_perfil(tenant)
        if perfil is None or not perfil.completo:
            raise ErroDeBackend(VALIDATION_ERROR, "perfil_incompleto")
        assert perfil.nome is not None and perfil.tom is not None and perfil.publico is not None
        factos = perfil.factos_validos(regras.dia_local(item.agendado_at))
        try:
            lexico, alegacoes = portas.lexico(), portas.alegacoes()
        except PoliticaIndisponivelError:
            raise ErroDeBackend(UPSTREAM_DOWN, "politica_indisponivel") from None
        pedido_de_legenda = PedidoDeLegenda(
            tema=item.tema,
            tipo=item.tipo,
            nome=perfil.nome,
            tom=perfil.tom,
            publico=perfil.publico,
            factos=tuple(f.texto for f in factos),
            instrucao=args.instrucao,
        )
        try:
            resultado = gerar_legenda(portas.gerador, pedido_de_legenda, lexico, alegacoes, factos)
        except GeradorPorLigarError:
            raise ErroDeBackend(UPSTREAM_DOWN, "legendas_por_ligar") from None
        except Exception:  # noqa: BLE001 — o gerador em baixo e fechado, e sem texto
            raise ErroDeBackend(UPSTREAM_DOWN, "gerador_indisponivel") from None
        if isinstance(resultado, Recusa):
            raise ErroDeBackend(VALIDATION_ERROR, resultado.motivo)
        decisao = _screen(portas, tenant, item.content_item_id, [item.tema, resultado.texto])
        try:
            if decisao.decisao == BLOQUEADA:
                repositorio.rejeitar(item, decisao.versao_politica)
                raise ErroDeBackend(VALIDATION_ERROR, "categoria_bloqueada")
            gravado = repositorio.gravar_legenda(
                item, resultado.texto, decisao.decisao != PERMITIDA, decisao.versao_politica
            )
        except ItemMudouError:
            raise ErroDeBackend(UPSTREAM_TIMEOUT, "item_mudou") from None
        except SemPublicacoesError:
            raise ErroDeBackend(LIMIT_EXCEEDED, "sem_publicacoes") from None
        return Resposta(data=vista_do_item(gravado, regras.referencia_do_item(gravado.content_item_id)))

    return {
        "get_brand_profile": get_brand_profile,
        "update_brand_profile": update_brand_profile,
        "generate_calendar": generate_calendar,
        "generate_caption": generate_caption,
    }
