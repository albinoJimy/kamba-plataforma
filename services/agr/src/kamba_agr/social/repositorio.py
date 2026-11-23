"""O estado do modulo social: o perfil, os calendarios e os itens (KAM-121).

O contrato (`RepositorioSocial`) e a versao em memoria, que os ensaios do AGR
usam; a versao contra o PostgreSQL e a `tls/social.py`, porque a ToolLayer e a
unica via de escrita dos agentes no `platform` (§6.1, ADR-015, `lint_arch`).

## A idempotencia do calendario e da base

* **«IDEIAS» duas vezes da o mesmo calendario** (criterio 2): ha um calendario
  `activo` por `(tenant, semana_iso)` — a chave do criterio —, e o `abrir`
  devolve-o.
* **So «NOVA» o regenera**, e uma vez por toque: o `abrir` com `nova` recebe a
  geracao que o chamador leu, e so cria a seguinte se a activa ainda for essa.
  Dois «NOVA» concorrentes dao **uma** geracao nova; o segundo le-a.
* O calendario anterior fica `substituido`, e os itens dele ainda por aprovar
  passam a `expirado` — o estado que o `CHECK` do bloco ja tinha.

## O consumo de `posts_mes` vai com a legenda

`gravar_legenda` consome **um** `posts_mes` na mesma transaccao em que grava, com
a chave `social:{content_item_id}` (decisao 3 do fundador, 2026-11-20): regerar a legenda do
mesmo item nao conta outra vez, e um limite esgotado nao grava nada.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Protocol

from .regras import Perfil

# Os estados de um `content_item` (o `CHECK` do bloco). Lista **fechada**.
RASCUNHO: Final = "rascunho"
PENDENTE_APROVACAO: Final = "pendente_aprovacao"
APROVADO: Final = "aprovado"
ENTREGUE: Final = "entregue"
REJEITADO: Final = "rejeitado"
EXPIRADO: Final = "expirado"
ESTADOS_DO_ITEM: Final = (RASCUNHO, PENDENTE_APROVACAO, APROVADO, ENTREGUE, REJEITADO, EXPIRADO)

#: Os estados que um «NOVA» expira: os que ainda nao foram aprovados.
POR_APROVAR: Final = (RASCUNHO, PENDENTE_APROVACAO)

#: As arestas da maquina do item (KAM-122), as mesmas do gatilho
#: `content_items_transicao` da `0085` (o ensaio confronta as duas).
TRANSICOES: Final = (
    (RASCUNHO, PENDENTE_APROVACAO),
    (RASCUNHO, REJEITADO),
    (RASCUNHO, EXPIRADO),
    (PENDENTE_APROVACAO, APROVADO),
    (PENDENTE_APROVACAO, REJEITADO),
    (PENDENTE_APROVACAO, EXPIRADO),
    (APROVADO, ENTREGUE),
    (APROVADO, PENDENTE_APROVACAO),
    (APROVADO, REJEITADO),
)
FINAIS: Final = (ENTREGUE, REJEITADO, EXPIRADO)

#: Os estados de onde o dono pede (ou volta a pedir) a aprovacao.
APROVAVEIS: Final = (RASCUNHO, PENDENTE_APROVACAO, APROVADO)

#: Os estados em que a arte se (re)gera. Num `pendente_aprovacao`, uma arte nova
#: apaga o `hash`: o botao da arte antiga deixa de aprovar.
COM_ARTE_NOVA: Final = (RASCUNHO, PENDENTE_APROVACAO)

#: As tentativas de arte de um item (criterio 9, *proposta*).
MAXIMO_DE_TENTATIVAS: Final = 3

#: O contador do TEN que um fundo gerado consome (`kamba_core/foto`).
CHAVE_DAS_IMAGENS: Final = "imagens_mes"

# Os estados de um calendario.
ACTIVO: Final = "activo"
SUBSTITUIDO: Final = "substituido"

#: O contador do TEN que uma legenda consome (`kamba_core/modulos/uso.py`).
CHAVE_DE_LIMITE: Final = "posts_mes"
MODULO: Final = "social"


#: Uma copia com campos mudados. **Nao e o `dataclasses.replace`**: a politica AST
#: do KAM-112 (`tests/politica_llm_ast.py`) recusa-o em toda a fonte do AGR,
#: porque e a forja do `MinimisedText`. Estes objectos nao sao texto minimizado.
def _com(objecto: Any, **mudancas: Any) -> Any:
    return type(objecto)(**{**vars(objecto), **mudancas})


def chave_de_consumo(content_item_id: str) -> str:
    return f"social:{content_item_id}"


def chave_da_imagem(content_item_id: str, tentativa: int) -> str:
    """Uma por tentativa de arte: regerar a arte e outra imagem, repetir a mesma nao e."""
    return f"arte:{content_item_id}:{tentativa}"


def transicao_permitida(de: str, para: str) -> bool:
    if de == para:
        return de not in FINAIS
    return (de, para) in TRANSICOES


class PerfilMudouError(RuntimeError):
    """O perfil mudou entre a leitura e a escrita (outra resposta concorrente)."""


class ItemMudouError(RuntimeError):
    """O item mudou entre a leitura e a escrita."""


class SemPublicacoesError(RuntimeError):
    """O `posts_mes` do plano esta esgotado: nada se gravou."""


class SemImagensError(RuntimeError):
    """O `imagens_mes` do plano esta esgotado: o fundo gerado nao se pede."""


class TentativasEsgotadasError(RuntimeError):
    """O item ja teve as tres tentativas de arte."""


class AprovacaoInvalidadaError(RuntimeError):
    """O `hash` da accao ja nao e o do item: houve uma edicao depois do botao."""


@dataclass(frozen=True)
class Item:
    content_item_id: str
    tenant_id: str
    calendar_id: str
    semana_iso: str
    tipo: str
    tema: str
    agendado_at: datetime.datetime
    legenda: str | None = None
    estado: str = RASCUNHO
    is_ai_generated: bool = True
    revisao_reforcada: bool = False
    versao_politica: str | None = None
    versao: int = 1
    # A arte e a aprovacao (KAM-122, `0085`).
    arte_ref: str | None = None
    arte_sha256: str | None = None
    arte_fundo: str | None = None
    #: O texto e o formato que estao na imagem (as linhas por `\n`).
    arte_texto: str | None = None
    arte_formato: str | None = None
    arte_tentativas: int = 0
    arte_custo_usd: Decimal = Decimal(0)
    aprovacao_hash: str | None = None
    aprovado_at: datetime.datetime | None = None
    entregue_at: datetime.datetime | None = None


@dataclass(frozen=True)
class Arte:
    """O que o `generate_art` grava no item."""

    arte_ref: str
    arte_sha256: str
    fundo: str
    custo_usd: Decimal
    texto: str
    formato: str


@dataclass(frozen=True)
class EventoAprovado:
    """O `content.approved` v1: so o `id` e a versao, sem conteudo (dicionario §3.5)."""

    content_item_id: str
    versao: int


@dataclass(frozen=True)
class Calendario:
    calendar_id: str
    tenant_id: str
    semana_iso: str
    geracao: int
    decisao: str
    versao_politica: str
    itens: tuple[Item, ...]
    estado: str = ACTIVO


@dataclass(frozen=True)
class ItemNovo:
    """Um item a criar, ja com o tema que passou o screening."""

    content_item_id: str
    tipo: str
    tema: str
    agendado_at: datetime.datetime
    revisao_reforcada: bool
    versao_politica: str


class RepositorioSocial(Protocol):
    def ler_perfil(self, tenant_id: str) -> Perfil | None: ...

    def gravar_perfil(self, perfil: Perfil, versao_lida: int | None) -> Perfil: ...

    def calendario(self, tenant_id: str, semana: str) -> Calendario | None: ...

    def abrir(
        self,
        tenant_id: str,
        semana: str,
        calendar_id: str,
        geracao: int,
        decisao: str,
        versao_politica: str,
        itens: Sequence[ItemNovo],
    ) -> tuple[Calendario, bool]: ...

    def itens_por_prefixo(self, tenant_id: str, prefixo: str) -> tuple[Item, ...]: ...

    def gravar_legenda(
        self,
        item: Item,
        legenda: str,
        revisao_reforcada: bool,
        versao_politica: str,
    ) -> Item: ...

    def rejeitar(self, item: Item, versao_politica: str) -> Item: ...

    # KAM-122: a arte, a aprovacao e a entrega.

    def item(self, tenant_id: str, content_item_id: str) -> Item | None: ...

    def consumir_imagem(self, tenant_id: str, chave: str) -> None: ...

    def gravar_arte(self, item: Item, arte: Arte) -> Item: ...

    def pedir_aprovacao(self, item: Item, legenda: str, hash_: str, reforcada: bool = False) -> Item: ...

    def aprovar(self, item: Item, hash_: str, agora: datetime.datetime) -> tuple[Item, EventoAprovado | None]: ...

    def rejeitar_pelo_dono(self, item: Item) -> Item: ...

    def entregar(self, item: Item, agora: datetime.datetime) -> tuple[Item, bool]: ...


class RepositorioEmMemoria:
    """O `RepositorioSocial` em memoria, para os ensaios. Isola por tenant como a RLS."""

    def __init__(self, *, limite_de_posts: int | None = 12, limite_de_imagens: int | None = 20) -> None:
        self.perfis: dict[str, Perfil] = {}
        self.calendarios: dict[str, Calendario] = {}
        self.itens: dict[str, Item] = {}
        self.consumos: dict[str, set[str]] = {}
        self.imagens: dict[str, set[str]] = {}
        self.eventos: list[tuple[str, EventoAprovado]] = []
        self.termos: dict[str, datetime.datetime] = {}
        self.limite_de_posts = limite_de_posts
        self.limite_de_imagens = limite_de_imagens

    # ---------------------------------------------------------- o perfil

    def ler_perfil(self, tenant_id: str) -> Perfil | None:
        return self.perfis.get(tenant_id)

    def gravar_perfil(self, perfil: Perfil, versao_lida: int | None) -> Perfil:
        actual = self.perfis.get(perfil.tenant_id)
        if (actual.versao if actual is not None else None) != versao_lida:
            raise PerfilMudouError("perfil mudou")
        self.perfis[perfil.tenant_id] = perfil
        return perfil

    # ---------------------------------------------------------- o calendario

    def _do_tenant(self, tenant_id: str, semana: str) -> list[Calendario]:
        return [c for c in self.calendarios.values() if c.tenant_id == tenant_id and c.semana_iso == semana]

    def _com_itens(self, calendario: Calendario) -> Calendario:
        itens = tuple(
            sorted(
                (i for i in self.itens.values() if i.calendar_id == calendario.calendar_id),
                key=lambda i: (i.agendado_at, i.content_item_id),
            )
        )
        return _com(calendario, itens=itens)

    def calendario(self, tenant_id: str, semana: str) -> Calendario | None:
        activos = [c for c in self._do_tenant(tenant_id, semana) if c.estado == ACTIVO]
        return self._com_itens(activos[0]) if activos else None

    def abrir(
        self,
        tenant_id: str,
        semana: str,
        calendar_id: str,
        geracao: int,
        decisao: str,
        versao_politica: str,
        itens: Sequence[ItemNovo],
    ) -> tuple[Calendario, bool]:
        activo = self.calendario(tenant_id, semana)
        if activo is not None and activo.geracao >= geracao:
            # Outro pedido ja abriu esta geracao (ou uma mais nova): e essa.
            return activo, False
        if activo is not None:
            self.calendarios[activo.calendar_id] = _com(activo, estado=SUBSTITUIDO, itens=())
            for item in activo.itens:
                if item.estado in POR_APROVAR:
                    self.itens[item.content_item_id] = _com(
                        item, estado=EXPIRADO, versao=item.versao + 1
                    )
        novo = Calendario(calendar_id, tenant_id, semana, geracao, decisao, versao_politica, ())
        self.calendarios[calendar_id] = novo
        for n in itens:
            self.itens[n.content_item_id] = Item(
                content_item_id=n.content_item_id,
                tenant_id=tenant_id,
                calendar_id=calendar_id,
                semana_iso=semana,
                tipo=n.tipo,
                tema=n.tema,
                agendado_at=n.agendado_at,
                revisao_reforcada=n.revisao_reforcada,
                versao_politica=n.versao_politica,
            )
        return self._com_itens(novo), True

    # ---------------------------------------------------------- os itens

    def itens_por_prefixo(self, tenant_id: str, prefixo: str) -> tuple[Item, ...]:
        return tuple(
            i
            for i in self.itens.values()
            if i.tenant_id == tenant_id and uuid.UUID(i.content_item_id).hex.startswith(prefixo)
        )

    def _exigir_versao(self, item: Item) -> None:
        actual = self.itens.get(item.content_item_id)
        if actual is None or actual.tenant_id != item.tenant_id or actual.versao != item.versao:
            raise ItemMudouError("item mudou")

    def gravar_legenda(self, item: Item, legenda: str, revisao_reforcada: bool, versao_politica: str) -> Item:
        self._exigir_versao(item)
        if item.estado != RASCUNHO:
            raise ItemMudouError("item mudou")
        consumidas = self.consumos.setdefault(item.tenant_id, set())
        chave = chave_de_consumo(item.content_item_id)
        if chave not in consumidas:
            if self.limite_de_posts is not None and len(consumidas) >= self.limite_de_posts:
                raise SemPublicacoesError("posts_mes esgotado")
            consumidas.add(chave)
        novo = _com(
            item,
            legenda=legenda,
            revisao_reforcada=item.revisao_reforcada or revisao_reforcada,
            versao_politica=versao_politica,
            versao=item.versao + 1,
        )
        self.itens[item.content_item_id] = novo
        return novo

    def rejeitar(self, item: Item, versao_politica: str) -> Item:
        self._exigir_versao(item)
        if item.estado != RASCUNHO:
            raise ItemMudouError("item mudou")
        novo = _com(item, estado=REJEITADO, versao_politica=versao_politica, versao=item.versao + 1)
        self.itens[item.content_item_id] = novo
        return novo

    # ---------------------------------------------------------- a arte e a aprovacao

    def _mudar(self, item: Item, **mudancas: Any) -> Item:
        """A escrita de um item com a guarda que o gatilho da `0085` faz na base."""
        self._exigir_versao(item)
        novo = _com(item, versao=item.versao + 1, **mudancas)
        if not transicao_permitida(item.estado, novo.estado):
            raise ItemMudouError("transicao recusada")
        if novo.estado in (APROVADO, ENTREGUE) and any(
            getattr(novo, c) != getattr(item, c) for c in ("legenda", "arte_ref", "arte_sha256", "aprovacao_hash")
        ):
            raise ItemMudouError("aprovado nao muda")
        self.itens[item.content_item_id] = novo
        return novo

    def item(self, tenant_id: str, content_item_id: str) -> Item | None:
        achado = self.itens.get(content_item_id.lower())
        return achado if achado is not None and achado.tenant_id == tenant_id else None

    def consumir_imagem(self, tenant_id: str, chave: str) -> None:
        consumidas = self.imagens.setdefault(tenant_id, set())
        if chave not in consumidas:
            if self.limite_de_imagens is not None and len(consumidas) >= self.limite_de_imagens:
                raise SemImagensError("imagens_mes esgotado")
            consumidas.add(chave)

    def gravar_arte(self, item: Item, arte: Arte) -> Item:
        if item.estado not in COM_ARTE_NOVA:
            raise ItemMudouError("item mudou")
        if item.arte_tentativas >= MAXIMO_DE_TENTATIVAS:
            raise TentativasEsgotadasError("tentativas esgotadas")
        return self._mudar(
            item,
            arte_ref=arte.arte_ref,
            arte_sha256=arte.arte_sha256,
            arte_fundo=arte.fundo,
            arte_texto=arte.texto,
            arte_formato=arte.formato,
            arte_tentativas=item.arte_tentativas + 1,
            arte_custo_usd=item.arte_custo_usd + arte.custo_usd,
            aprovacao_hash=None,
        )

    def pedir_aprovacao(self, item: Item, legenda: str, hash_: str, reforcada: bool = False) -> Item:
        if item.estado not in APROVAVEIS:
            raise ItemMudouError("item mudou")
        return self._mudar(
            item,
            estado=PENDENTE_APROVACAO,
            legenda=legenda,
            aprovacao_hash=hash_,
            aprovado_at=None,
            revisao_reforcada=item.revisao_reforcada or reforcada,
        )

    def aprovar(self, item: Item, hash_: str, agora: datetime.datetime) -> tuple[Item, EventoAprovado | None]:
        actual = self.item(item.tenant_id, item.content_item_id) or item
        if actual.estado in (APROVADO, ENTREGUE) and actual.aprovacao_hash == hash_:
            return actual, None
        if actual.estado != PENDENTE_APROVACAO or actual.aprovacao_hash != hash_:
            raise AprovacaoInvalidadaError("aprovacao invalidada")
        novo = self._mudar(actual, estado=APROVADO, aprovado_at=agora)
        evento = EventoAprovado(novo.content_item_id, novo.versao)
        self.eventos.append((novo.tenant_id, evento))
        return novo, evento

    def rejeitar_pelo_dono(self, item: Item) -> Item:
        return self._mudar(item, estado=REJEITADO)

    def entregar(self, item: Item, agora: datetime.datetime) -> tuple[Item, bool]:
        novo = self._mudar(item, estado=ENTREGUE, entregue_at=agora)
        primeira = item.tenant_id not in self.termos
        if primeira:
            self.termos[item.tenant_id] = agora
        return novo, primeira


def vista_do_item(item: Item, referencia: str) -> dict[str, Any]:
    return {
        "content_item_id": item.content_item_id,
        "referencia": referencia,
        "tipo": item.tipo,
        "tema": item.tema,
        "agendado_at": item.agendado_at.astimezone(datetime.UTC).isoformat(),
        "legenda": item.legenda,
        "estado": item.estado,
        "is_ai_generated": item.is_ai_generated,
        "revisao_reforcada": item.revisao_reforcada,
        "versao_politica": item.versao_politica,
        "arte_fundo": item.arte_fundo,
        "arte_formato": item.arte_formato,
        "arte_tentativas": item.arte_tentativas,
    }
