"""As tools do modulo `social` ligadas na ToolLayer (KAM-121, `docs/tecnica/02` §21.3).

| Tool | Classe | O que faz |
|---|---|---|
| `get_brand_profile` | `read` | o perfil, se esta completo, e a proxima pergunta |
| `update_brand_profile` | `write`, passo 4 dispensado | uma resposta do dono a uma pergunta do perfil (decisao 2 do fundador, 2026-11-20) |
| `generate_calendar` | `write`, passo 4 dispensado | o calendario da semana seguinte, 3 a 7 itens; «NOVA» regenera |
| `generate_caption` | `write`, passo 4 dispensado | a legenda de um item, pelas quatro barreiras e pelo screening |
| `generate_art` | `write`, passo 4 dispensado | a arte de um item em JPEG, gravada no STO (KAM-122) |
| `request_approval` | `write`, passo 4 dispensado | a pre-visualizacao e a accao `aprovar_conteudo` (o botao Aprovar); com `legenda`, a edicao do dono |
| `approve_content` | `write`, botao `confirm:{action_id}` | a aprovacao: `aprovado` e o `content.approved` na mesma transaccao |
| `reject_content` | `write`, passo 4 dispensado | o dono rejeita o item |
| `deliver_content` | `write`, passo 4 dispensado | o item aprovado passa a `entregue` e devolve as partes da entrega ao dono |

As tres de escrita **so gravam** rascunhos na nossa base e nada sai para fora
— nem para o cliente, nem para uma rede social: a dispensa do passo 4 e a dos
precedentes do KAM-220 e do KAM-119, com a razao escrita na especificacao. A
aprovacao do dono e a entrega sao do KAM-122 (`request_approval`, com o botao
`confirm:{action_id}` da accao `aprovar_conteudo`).

## Nao ha tool de publicacao, e isso e criterio

O modulo tem as quatro do KAM-121 e as cinco do KAM-122. Nenhuma publica,
agenda numa rede ou envia a terceiros: o dono publica manualmente (D13), e o
`deliver_content` so devolve as partes da mensagem que o no `send` do grafo
manda **ao proprio dono**. O `test_nao_ha_tool_de_publicacao_no_social`
enumera o catalogo pelo modulo e recusa um nome com cara de publicacao.

## A aprovacao (KAM-122, criterio 5)

O `request_approval` grava o `hash(legenda, arte, versao)` no item e propoe a
accao `aprovar_conteudo` com `ref = {content_item_id}/{hash}` (decisao D4 do
fundador, 2026-11-21): o botao Aprovar e o `confirm:{action_id}` dela, e o
`approve_content` corre com esse botao no passo 4. Uma edicao muda o `hash`, e o
botao antigo recusa com `aprovacao_invalidada`. Pedir a aprovacao duas vezes
sem mudar nada devolve a mesma accao (a `UNIQUE (tenant_id, tipo, ref)`), e
aprovar duas vezes da **um** `aprovado` e **um** `content.approved`.

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
| a arte nao se compoe | `VALIDATION_ERROR` (`faltam_factos`, `texto_nao_cabe`, `perfil_incompleto`) |
| tres tentativas de arte | `LIMIT_EXCEEDED` (`tentativas_esgotadas`) |
| aprovacao sem arte ou sem legenda | `VALIDATION_ERROR` (`sem_arte`, `sem_legenda`) |
| a legenda editada recusada | `VALIDATION_ERROR` (`faltam_factos`, `alegacao`, `categoria_bloqueada`) |
| o botao de uma versao antiga | `VALIDATION_ERROR` (`aprovacao_invalidada`) |
| entrega de um item nao aprovado | `VALIDATION_ERROR` (`por_aprovar`) |
| o STO ou as fontes nao estao ligados | `UPSTREAM_DOWN` (`arte_por_ligar`, `fontes_em_falta`) |

O `detalhe` e um codigo, nunca texto do dono.
"""

from __future__ import annotations

import datetime
import hashlib
from decimal import Decimal

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from kamba_core.catalogo.screening import PERMITIDA, PortaDeScreening
from kamba_core.storage.chave import nova_chave
from kamba_core.storage.port import Ctx, ObjectMeta, StorageProvider
from pydantic import BaseModel, ConfigDict, Field

from ..dono import accoes
from ..social import arte as arte_mod
from ..social import regras
from ..social.aprovacao import hash_da_aprovacao, ler_ref, ref_da_accao
from ..social.desenho import FontesEmFaltaError, RenderizadorPillow
from ..social.fundos import GRADIENTE, Escolha, GeradorDeFundos, PedidoDeFundo, escolher_fundo
from ..social.fundos import GeradorPorLigar as FundoPorLigar
from ..social.fundos import PortaDeDestinos
from ..social.geracao import GeradorDeLegendas, GeradorPorLigar, GeradorPorLigarError, PedidoDeLegenda, Recusa, gerar_legenda
from ..social.numeros import numeros_fora_dos_factos
from ..social.ocr import TesseractOcr, VerificadorDeTexto
from ..social.politicas import Alegacoes, Lexico, PoliticaIndisponivelError
from ..social.publicacao import ManualDelivery, PedidoDeEntrega
from ..social.repositorio import (
    APROVADO,
    APROVAVEIS,
    COM_ARTE_NOVA,
    ENTREGUE,
    MAXIMO_DE_TENTATIVAS,
    PENDENTE_APROVACAO,
    RASCUNHO,
    AprovacaoInvalidadaError,
    Arte,
    ItemMudouError,
    ItemNovo,
    PerfilMudouError,
    RepositorioSocial,
    SemImagensError,
    SemPublicacoesError,
    TentativasEsgotadasError,
    chave_da_imagem,
    vista_do_item,
)
from .erros import LIMIT_EXCEEDED, NOT_FOUND, TENANT_MISMATCH, UPSTREAM_DOWN, UPSTREAM_TIMEOUT, VALIDATION_ERROR
from .especificacoes import ErroDeBackend, Executor, Pedido, Resposta

BLOQUEADA: Final = "bloqueada"
CONDICIONAL: Final = "condicional"
#: As decisoes por ordem de restricao (a do `DECISOES` do KAM-088).
_RESTRICAO: Final = (PERMITIDA, CONDICIONAL, BLOQUEADA)


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


class ArgumentosDeGenerateArt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referencia: str = Field(pattern=regras.FORMA_DA_REFERENCIA)
    formato: Literal["quadrado", "retrato"] = "quadrado"
    nova: bool = False


class ArgumentosDeRequestApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referencia: str = Field(pattern=regras.FORMA_DA_REFERENCIA)
    legenda: str | None = Field(default=None, min_length=1, max_length=1000)


class ArgumentosDeApproveContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ArgumentosDeRejectContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referencia: str = Field(pattern=regras.FORMA_DA_REFERENCIA)


class ArgumentosDeDeliverContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referencia: str = Field(pattern=regras.FORMA_DA_REFERENCIA)


MODELOS: Final[Mapping[str, type[BaseModel]]] = {
    "get_brand_profile": ArgumentosDeGetBrandProfile,
    "update_brand_profile": ArgumentosDeUpdateBrandProfile,
    "generate_calendar": ArgumentosDeGenerateCalendar,
    "generate_caption": ArgumentosDeGenerateCaption,
    "generate_art": ArgumentosDeGenerateArt,
    "request_approval": ArgumentosDeRequestApproval,
    "approve_content": ArgumentosDeApproveContent,
    "reject_content": ArgumentosDeRejectContent,
    "deliver_content": ArgumentosDeDeliverContent,
}

#: O tipo da accao sensivel do botao Aprovar (`owner_actions.tipo`, §21.2).
TIPO_DA_ACCAO: Final = "aprovar_conteudo"

#: Quantas accoes se tentam para o mesmo `hash`, quando a anterior expirou ou e
#: de outro contacto (o `TENTATIVAS_DO_BOTAO` do catalogo). *Proposta*.
TENTATIVAS_DO_BOTAO: Final = 50

#: A classe do STO e o prazo da arte (*proposta*, o da versao do KAM-120).
CLASSE_DA_ARTE: Final = "arte"
RETENCAO_DA_ARTE: Final = datetime.timedelta(days=90)

#: A partir de que tentativa o dono e avisado do custo (criterio 9): a penultima.
ALERTA_DE_CUSTO_A_PARTIR_DE: Final = MAXIMO_DE_TENTATIVAS - 1

SQL_ACCAO: Final = (
    "SELECT tipo, ref, estado, contact_id::text, confirmada_at, expira_at FROM platform.owner_actions "
    "WHERE tenant_id = %s::uuid AND action_id = %s::uuid"
)


def _lexico_por_omissao() -> Lexico:
    return Lexico.carregar()


def _alegacoes_por_omissao() -> Alegacoes:
    return Alegacoes.carregar()


class StoragePorLigar:
    """O STO da arte sem adaptador (o do AGR, como o da foto do KAM-119): falha fechada."""

    def __getattr__(self, nome: str) -> Any:
        raise ArtePorLigarError("o armazenamento das artes nao esta ligado")


class ArtePorLigarError(RuntimeError):
    """Sem STO ligado, a arte nao se grava."""


class DestinosPorLigar:
    """A porta de destinos sem adaptador: **nada** esta autorizado."""

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        raise PermissionError("destino nao autorizado")


def _ler_accao_sql(ligacao: Any, tenant_id: str, action_id: str) -> tuple[str, str, str, str, Any, Any] | None:
    from kamba_core import tenant_guard

    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_ACCAO, (tenant_id, action_id))
        linha = cursor.fetchone()
    if linha is None:
        return None
    tipo, ref, estado, contacto, confirmada_at, expira_at = linha
    return str(tipo), str(ref), str(estado), str(contacto).lower(), confirmada_at, expira_at


@dataclass(frozen=True)
class PortasDoSocial:
    """O que as tools sociais precisam do processo, ou de um ensaio."""

    repositorio: Callable[[Any], RepositorioSocial]
    screening: PortaDeScreening
    gerador: GeradorDeLegendas = field(default_factory=GeradorPorLigar)
    lexico: Callable[[], Lexico] = _lexico_por_omissao
    alegacoes: Callable[[], Alegacoes] = _alegacoes_por_omissao
    # KAM-122: a arte e a aprovacao.
    renderizador: Any = field(default_factory=RenderizadorPillow)
    fundos: GeradorDeFundos = field(default_factory=FundoPorLigar)
    ocr: VerificadorDeTexto = field(default_factory=TesseractOcr)
    destinos: PortaDeDestinos = field(default_factory=DestinosPorLigar)
    storage: StorageProvider = field(default_factory=StoragePorLigar)  # type: ignore[assignment]
    #: A `owner_actions` do KAM-118: `propor` e a leitura de uma accao.
    propor: Callable[..., str] = accoes.propor
    ler_accao: Callable[[Any, str, str], tuple[str, str, str, str, Any, Any] | None] = _ler_accao_sql


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


def _do_perfil(perfil: regras.Perfil) -> list[str]:
    """A categoria e o nome do perfil, que vao em **todo** o screen do social.

    Nem todo o modelo de tema cita a categoria («Os bastidores de {nome}»), e
    uma categoria bloqueada disfarcada no perfil («Revolver de coleccao», com a
    categoria declarada «moda») so era vista nos temas que a citam — os outros
    nasciam (achado I7 da revisao adversarial). Com o texto do perfil em cada
    pedido, a mesma categoria bloqueia todos os itens.
    """
    return [x for x in (perfil.categoria, perfil.nome) if x]


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
        # **Um screen por tema**, com o `content_item_id` como sujeito (decisao 1
        # do fundador, 2026-11-20): um tema `bloqueada` nao gera o item, e uma
        # `condicional` marca-o com revisao reforcada (criterio 5). Se um screen
        # falha, nada se grava. O tecto de uma `write` (8 s, §6.5) e mais curto
        # do que varios screens com o classificador: um calendario que o passe
        # acaba na *thread*, e o «IDEIAS» seguinte le-o (a limitacao do KAM-119).
        novos: list[ItemNovo] = []
        decisoes: list[str] = []
        versao_politica = ""
        for tema in temas:
            content_item_id = str(uuid.uuid4())
            decisao = _screen(portas, tenant, content_item_id, [tema.tema, *_do_perfil(perfil)])
            decisoes.append(decisao.decisao)
            versao_politica = decisao.versao_politica
            if decisao.decisao == BLOQUEADA:
                continue
            novos.append(
                ItemNovo(
                    content_item_id=content_item_id,
                    tipo=tema.tipo,
                    tema=tema.tema,
                    agendado_at=tema.agendado_at,
                    revisao_reforcada=decisao.decisao != PERMITIDA,
                    versao_politica=decisao.versao_politica,
                )
            )
        # A decisao do calendario e a mais restritiva dos temas.
        pior = max(decisoes, key=_RESTRICAO.index) if decisoes else PERMITIDA
        calendario, novo = repositorio.abrir(tenant, semana, calendar_id, geracao, pior, versao_politica, novos)
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
        decisao = _screen(portas, tenant, item.content_item_id, [item.tema, resultado.texto, *_do_perfil(perfil)])
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
        **_executores_da_arte(portas, agora),
    }


# ------------------------------------------------------------------ a arte e a aprovacao (KAM-122)


def _o_item(repositorio: RepositorioSocial, tenant: str, referencia: str) -> Any:
    prefixo = regras.prefixo_da_referencia(referencia)
    achados = repositorio.itens_por_prefixo(tenant, prefixo or "-")
    if len(achados) != 1:
        raise ErroDeBackend(NOT_FOUND, "item_desconhecido")
    return achados[0]


def _perfil_completo(repositorio: RepositorioSocial, tenant: str) -> regras.Perfil:
    perfil = repositorio.ler_perfil(tenant)
    if perfil is None or not perfil.completo or perfil.nome is None:
        raise ErroDeBackend(VALIDATION_ERROR, "perfil_incompleto")
    return perfil


def _composicao(perfil: regras.Perfil, item: Any, formato: str, tentativa: int) -> Any:
    """A composicao da arte: o *template* roda a cada tentativa, o texto e o dos factos."""
    dia = regras.dia_local(item.agendado_at)
    dados = arte_mod.dados_da_arte(perfil, item.tipo, dia)
    templates = arte_mod.templates_do_tipo(arte_mod.tipo_de_negocio(perfil.categoria))
    template = templates[(tentativa - 1) % len(templates)]
    composicao = arte_mod.compor(dados, template, formato)
    assert perfil.nome is not None
    arte_mod.verificar_numeros(composicao, perfil.factos_validos(dia), perfil.nome)
    return composicao


def vista_da_arte(item: Any, referencia: str, composicao: Any | None = None, **extra: Any) -> dict[str, Any]:
    """A vista do item com a arte. **O texto da arte e o que esta na imagem** (`arte_texto`)."""
    dados = vista_do_item(item, referencia)
    dados["tentativas_restantes"] = max(MAXIMO_DE_TENTATIVAS - item.arte_tentativas, 0)
    dados["formato"] = item.arte_formato
    dados["texto_da_arte"] = item.arte_texto.split("\n") if item.arte_texto else []
    # A chave do STO da arte (KAM-246): o turno pede-a como imagem da resposta.
    # E a chave e nunca um URL; o consumidor confere-a antes de a ler.
    dados["arte_ref"] = item.arte_ref
    if composicao is not None:
        dados["template_id"] = composicao.template.template_id
    dados.update(extra)
    return dados


def _arte_ainda_vale(perfil: regras.Perfil, item: Any) -> None:
    """O texto **guardado** da arte contra os factos validos de agora (criterios 2 e 5).

    Um facto que mudou ou expirou depois da arte deixa-a com um numero que ja
    nao tem fonte: a aprovacao recusa, e o dono pede outra arte.
    """
    if not item.arte_texto or perfil.nome is None:
        raise ErroDeBackend(VALIDATION_ERROR, "sem_arte")
    dia = regras.dia_local(item.agendado_at)
    linhas = tuple(arte_mod.Linha("texto", t) for t in item.arte_texto.split("\n"))
    composicao = arte_mod.Composicao(arte_mod.TEMPLATES[next(iter(arte_mod.TEMPLATES))], item.arte_formato or "quadrado", linhas)
    try:
        arte_mod.verificar_numeros(composicao, perfil.factos_validos(dia), perfil.nome)
    except arte_mod.Recusa:
        raise ErroDeBackend(VALIDATION_ERROR, "arte_desactualizada") from None


def _serve(accao: Any, contacto: str, instante: datetime.datetime) -> bool:
    """A accao ainda serve ao dono deste turno: a dele, e pendente no prazo ou ja confirmada."""
    if accao is None:
        return False
    _tipo, _ref, estado, dono, _confirmada_at, expira_at = accao
    if dono != contacto.lower():
        return False
    if estado == "confirmada":
        return True
    return estado == "pendente" and expira_at is not None and expira_at > instante


def _legenda_do_dono(portas: PortasDoSocial, perfil: regras.Perfil, item: Any, legenda: str) -> str:
    """A legenda editada pelo dono pelas barreiras do criterio 6: numeros e alegacoes.

    Os numeros da legenda tem de estar nos factos do dono (a guarda do KAM-121):
    um numero novo entra primeiro como facto («FACTOS: …», com o eco do
    perfil), e so depois na legenda. O screening corre a seguir, no executor.
    """
    # As quebras de linha do dono ficam; os espacos a mais de cada linha, nao.
    texto = "\n".join(" ".join(linha.split()) for linha in legenda.strip().splitlines()).strip()
    factos = perfil.factos_validos(regras.dia_local(item.agendado_at))
    assert perfil.nome is not None
    if numeros_fora_dos_factos(texto, [f.texto for f in factos] + [perfil.nome]):
        raise ErroDeBackend(VALIDATION_ERROR, "faltam_factos")
    try:
        alegacoes = portas.alegacoes()
    except PoliticaIndisponivelError:
        raise ErroDeBackend(UPSTREAM_DOWN, "politica_indisponivel") from None
    if alegacoes.avaliar(texto, [f.texto for f in factos]) is not None:
        raise ErroDeBackend(VALIDATION_ERROR, "alegacao")
    return texto


def _partes(item: Any, primeira: bool) -> dict[str, Any]:
    """As partes da mensagem de entrega, pela `ManualDelivery` (D13)."""
    assert item.legenda is not None
    entrega = ManualDelivery().deliver(
        PedidoDeEntrega(
            content_item_id=item.content_item_id,
            tenant_id=item.tenant_id,
            legenda=item.legenda,
            arte_ref=item.arte_ref,
            is_ai_generated=item.is_ai_generated,
            primeira_entrega=primeira,
        )
    )
    return {"legenda": entrega.legenda, "nota": entrega.nota, "termos": entrega.termos, "arte_ref": entrega.arte_ref}


def _propor_botao(portas: PortasDoSocial, pedido: Pedido, item: Any, instante: datetime.datetime, *, reforcada: bool) -> str:
    """A accao `aprovar_conteudo` do `hash` do item que ainda serve a este dono."""
    assert item.aprovacao_hash is not None
    tenant = pedido.ctx.tenant_id
    for tentativa in range(1, TENTATIVAS_DO_BOTAO + 1):
        action_id = portas.propor(
            pedido.ligacao,
            tenant,
            pedido.ctx.contact_id,
            TIPO_DA_ACCAO,
            ref_da_accao(item.content_item_id, item.aprovacao_hash, tentativa, reforcada=reforcada),
            instante,
        )
        accao = portas.ler_accao(pedido.ligacao, tenant, action_id)
        # **Num item reforcado, uma accao ja confirmada nao serve** (achado 3 da
        # revisao): o passo 5 guarda o resultado dela, e o toque seguinte
        # devolvia-o sem aprovar. Propoe-se a tentativa seguinte, por confirmar.
        if item.revisao_reforcada and accao is not None and accao[2] == "confirmada":
            continue
        if _serve(accao, pedido.ctx.contact_id, instante):
            return action_id
    raise ErroDeBackend(VALIDATION_ERROR, "botoes_esgotados")


def _executores_da_arte(portas: PortasDoSocial, agora: Callable[[], datetime.datetime]) -> dict[str, Executor]:
    def generate_art(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeGenerateArt)
        repositorio = portas.repositorio(pedido.ligacao)
        tenant = pedido.ctx.tenant_id
        item = _o_item(repositorio, tenant, args.referencia)
        referencia = regras.referencia_do_item(item.content_item_id)
        if item.estado not in COM_ARTE_NOVA:
            raise ErroDeBackend(VALIDATION_ERROR, "item_fechado")
        if isinstance(portas.storage, StoragePorLigar):
            # Antes de pedir um fundo que se pagava e nao tinha onde ficar.
            raise ErroDeBackend(UPSTREAM_DOWN, "arte_por_ligar")
        perfil = _perfil_completo(repositorio, tenant)
        if item.arte_ref is not None and not args.nova:
            # **Renderizar duas vezes da uma arte** (idempotencia do bloco): sem
            # `nova`, a arte que o item ja tem — o texto e o formato **guardados**
            # com ela, e nao uma composicao refeita dos factos de agora (achado 1
            # da revisao adversarial) —, e nenhuma tentativa conta.
            return Resposta(data=vista_da_arte(item, referencia, nova=False))
        if item.arte_tentativas >= MAXIMO_DE_TENTATIVAS:
            raise ErroDeBackend(LIMIT_EXCEEDED, "tentativas_esgotadas")
        tentativa = item.arte_tentativas + 1
        try:
            composicao = _composicao(perfil, item, args.formato, tentativa)
        except arte_mod.Recusa as recusa:
            raise ErroDeBackend(VALIDATION_ERROR, recusa.motivo) from None
        # **O texto cabe antes de se pagar o fundo** (achado 4 da revisao): o
        # desenho sobre o fundo do *template* mede as linhas em pixeis e confere
        # as fontes. So depois sai o pedido ao gerador.
        try:
            jpeg = portas.renderizador.desenhar(composicao, perfil.cores or (), None)
        except arte_mod.Recusa as recusa:
            raise ErroDeBackend(VALIDATION_ERROR, recusa.motivo) from None
        except FontesEmFaltaError:
            raise ErroDeBackend(UPSTREAM_DOWN, "fontes_em_falta") from None
        tipo = arte_mod.tipo_de_negocio(perfil.categoria)
        try:
            escolha = escolher_fundo(
                tenant,
                PedidoDeFundo(tipo, args.formato),
                portas.fundos,
                portas.ocr,
                portas.destinos,
                antes_de_pedir=lambda: repositorio.consumir_imagem(
                    tenant, chave_da_imagem(item.content_item_id, tentativa)
                ),
            )
        except SemImagensError:
            # O `imagens_mes` esgotado nao impede a arte: impede o fundo gerado.
            escolha = Escolha(None, GRADIENTE, Decimal(0), 0, "sem_imagens")
        if escolha.imagem is not None:
            try:
                jpeg = portas.renderizador.desenhar(composicao, perfil.cores or (), escolha.imagem)
            except Exception:  # noqa: BLE001 — uma cena ilegivel nao perde a arte paga
                escolha = Escolha(None, GRADIENTE, escolha.custo_usd, escolha.pedidos, "cena_ilegivel")
        instante = agora()
        ctx = Ctx(tenant)
        try:
            chave = nova_chave(ctx, CLASSE_DA_ARTE, instante)
            guardada = portas.storage.put(
                ctx, chave, jpeg, ObjectMeta("image/jpeg", CLASSE_DA_ARTE, instante + RETENCAO_DA_ARTE)
            )
        except ArtePorLigarError:
            raise ErroDeBackend(UPSTREAM_DOWN, "arte_por_ligar") from None
        sha256 = guardada.sha256 or hashlib.sha256(jpeg).hexdigest()
        try:
            gravado = repositorio.gravar_arte(
                item,
                Arte(chave, sha256, escolha.fundo, escolha.custo_usd, arte_mod.texto_composto(composicao), args.formato),
            )
        except TentativasEsgotadasError:
            raise ErroDeBackend(LIMIT_EXCEEDED, "tentativas_esgotadas") from None
        except ItemMudouError:
            raise ErroDeBackend(UPSTREAM_TIMEOUT, "item_mudou") from None
        return Resposta(
            data=vista_da_arte(
                gravado,
                referencia,
                composicao,
                nova=True,
                motivo_do_fundo=escolha.motivo,
                alerta_de_custo=tentativa >= ALERTA_DE_CUSTO_A_PARTIR_DE,
                custo_usd=str(gravado.arte_custo_usd),
            )
        )

    def request_approval(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeRequestApproval)
        repositorio = portas.repositorio(pedido.ligacao)
        tenant = pedido.ctx.tenant_id
        item = _o_item(repositorio, tenant, args.referencia)
        referencia = regras.referencia_do_item(item.content_item_id)
        if item.estado not in APROVAVEIS:
            raise ErroDeBackend(VALIDATION_ERROR, "item_fechado")
        if item.arte_ref is None or item.arte_sha256 is None:
            raise ErroDeBackend(VALIDATION_ERROR, "sem_arte")
        perfil = _perfil_completo(repositorio, tenant)
        _arte_ainda_vale(perfil, item)
        legenda = item.legenda
        reforcada = False
        if args.legenda is not None:
            legenda = _legenda_do_dono(portas, perfil, item, args.legenda)
            # O screening corre outra vez sobre a legenda do dono (criterio 6).
            decisao = _screen(portas, tenant, item.content_item_id, [item.tema, legenda, *_do_perfil(perfil)])
            if decisao.decisao == BLOQUEADA:
                raise ErroDeBackend(VALIDATION_ERROR, "categoria_bloqueada")
            # Uma `condicional` na edicao reforca o item, como na legenda gerada
            # (achado 2 da revisao): a confirmacao a mais nao se salta editando.
            reforcada = decisao.decisao != PERMITIDA
        if not legenda:
            raise ErroDeBackend(VALIDATION_ERROR, "sem_legenda")
        if item.estado == APROVADO and legenda == item.legenda:
            raise ErroDeBackend(VALIDATION_ERROR, "ja_aprovado")
        if (
            item.estado == PENDENTE_APROVACAO
            and legenda == item.legenda
            and item.aprovacao_hash is not None
            and not (reforcada and not item.revisao_reforcada)
        ):
            # **Pedir duas vezes sem mudar nada nao escreve**: o mesmo `hash`, a
            # mesma `ref`, a mesma accao.
            gravado = item
        else:
            hash_ = hash_da_aprovacao(legenda, item.arte_sha256, item.versao + 1)
            try:
                gravado = repositorio.pedir_aprovacao(item, legenda, hash_, reforcada)
            except ItemMudouError:
                raise ErroDeBackend(UPSTREAM_TIMEOUT, "item_mudou") from None
        assert gravado.aprovacao_hash is not None
        action_id = _propor_botao(portas, pedido, gravado, agora(), reforcada=False)
        return Resposta(data=vista_da_arte(gravado, referencia, action_id=action_id, legenda=gravado.legenda))

    def approve_content(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeApproveContent)
        repositorio = portas.repositorio(pedido.ligacao)
        tenant = pedido.ctx.tenant_id
        accao = portas.ler_accao(pedido.ligacao, tenant, args.action_id)
        if accao is None:
            raise ErroDeBackend(NOT_FOUND, "accao_desconhecida")
        tipo, ref, estado, contacto, confirmada_at, _expira_at = accao
        lido = ler_ref(ref)
        if tipo != TIPO_DA_ACCAO or lido is None:
            # Uma accao de outro modulo (a ref do catalogo tem dois pontos): quem
            # fala e a frase da confirmacao.
            raise ErroDeBackend(NOT_FOUND, "accao_nao_e_de_conteudo")
        if contacto != pedido.ctx.contact_id.lower():
            raise ErroDeBackend(TENANT_MISMATCH, "accao_de_outro_contacto")
        if estado != "confirmada" or confirmada_at is None:
            raise ErroDeBackend(VALIDATION_ERROR, "accao_por_confirmar")
        content_item_id, hash_, reforcada = lido
        item = repositorio.item(tenant, content_item_id)
        if item is None:
            raise ErroDeBackend(NOT_FOUND, "item_desconhecido")
        # **A integridade do hash**: o que esta no item tem de dar o hash que o
        # botao cita. Uma linha mexida por fora da tool nao se aprova.
        if (
            item.estado == PENDENTE_APROVACAO
            and item.legenda is not None
            and item.arte_sha256 is not None
            and hash_da_aprovacao(item.legenda, item.arte_sha256, item.versao) != hash_
        ):
            raise ErroDeBackend(VALIDATION_ERROR, "aprovacao_invalidada")
        if item.estado == PENDENTE_APROVACAO:
            perfil = _perfil_completo(repositorio, tenant)
            _arte_ainda_vale(perfil, item)
        if item.revisao_reforcada and not reforcada and item.estado == PENDENTE_APROVACAO:
            # **A confirmacao a mais da revisao reforcada** (KAM-121, criterio 5):
            # o primeiro botao nao aprova; propoe o segundo, do mesmo `hash`.
            extra = _propor_botao(portas, pedido, item, agora(), reforcada=True)
            referencia = regras.referencia_do_item(item.content_item_id)
            return Resposta(data=vista_da_arte(item, referencia, confirmacao_extra=True, action_id=extra))
        try:
            aprovado, evento = repositorio.aprovar(item, hash_, confirmada_at)
        except AprovacaoInvalidadaError:
            raise ErroDeBackend(VALIDATION_ERROR, "aprovacao_invalidada") from None
        except ItemMudouError:
            raise ErroDeBackend(UPSTREAM_TIMEOUT, "item_mudou") from None
        referencia = regras.referencia_do_item(aprovado.content_item_id)
        return Resposta(data=vista_da_arte(aprovado, referencia, ja_aprovado=evento is None))

    def reject_content(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeRejectContent)
        repositorio = portas.repositorio(pedido.ligacao)
        item = _o_item(repositorio, pedido.ctx.tenant_id, args.referencia)
        referencia = regras.referencia_do_item(item.content_item_id)
        if item.estado == "rejeitado":
            return Resposta(data=vista_da_arte(item, referencia))
        if item.estado not in APROVAVEIS:
            raise ErroDeBackend(VALIDATION_ERROR, "item_fechado")
        try:
            gravado = repositorio.rejeitar_pelo_dono(item)
        except ItemMudouError:
            raise ErroDeBackend(UPSTREAM_TIMEOUT, "item_mudou") from None
        return Resposta(data=vista_da_arte(gravado, referencia))

    def deliver_content(pedido: Pedido) -> Resposta:
        _exigir_ligacao(pedido)
        args = pedido.args
        assert isinstance(args, ArgumentosDeDeliverContent)
        repositorio = portas.repositorio(pedido.ligacao)
        tenant = pedido.ctx.tenant_id
        item = _o_item(repositorio, tenant, args.referencia)
        referencia = regras.referencia_do_item(item.content_item_id)
        if item.estado == ENTREGUE:
            # **Entregar duas vezes da uma entrega**: o item nao muda e os termos
            # nao se repetem. Mas a legenda volta, so para o dono: a entrega grava
            # antes de a mensagem sair, e um envio que falhou nao a deixava
            # chegar nunca (achado 6 da revisao).
            return Resposta(data=vista_da_arte(item, referencia, ja_entregue=True, entrega=_partes(item, False)))
        if item.estado != APROVADO:
            raise ErroDeBackend(VALIDATION_ERROR, "por_aprovar")
        try:
            entregue, primeira = repositorio.entregar(item, agora())
        except ItemMudouError:
            relido = repositorio.item(tenant, item.content_item_id)
            if relido is not None and relido.estado == ENTREGUE:
                return Resposta(data=vista_da_arte(relido, referencia, ja_entregue=True))
            raise ErroDeBackend(UPSTREAM_TIMEOUT, "item_mudou") from None
        return Resposta(data=vista_da_arte(entregue, referencia, ja_entregue=False, entrega=_partes(entregue, primeira)))

    return {
        "generate_art": generate_art,
        "request_approval": request_approval,
        "approve_content": approve_content,
        "reject_content": reject_content,
        "deliver_content": deliver_content,
    }

