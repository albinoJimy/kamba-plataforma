"""A persistencia de `platform.catalog_ingestions` (KAM-049; revisao `catalogo_ai`).

Duas implementacoes da mesma porta, e o ensaio corre o pipeline sobre as duas:

* `RepositorioEmMemoria`, para as baterias unitarias. **Comporta-se**: recusa a
  segunda linha do mesmo `(tenant_id, media_id_meta)`, recusa uma transicao
  fora da tabela, recusa mais de doze perguntas e uma `publicada` sem
  confirmacao — as mesmas recusas do `CHECK` e do *trigger* da revisao `catalogo_ai`;
* `RepositorioDbapi`, sobre uma ligacao DB-API por chamada, dentro do
  `tenant_guard.tx` (a disciplina do KAM-030 e do KAM-069). O `tenant_id` vem
  sempre do contexto da RLS **e** do predicado: com a `FORCE`, uma linha de
  outro tenant nao se le nem com o `id` certo.

## Idempotencia por `media_id`

O `inserir` e `INSERT … ON CONFLICT (tenant_id, media_id_meta) DO NOTHING`
seguido da leitura da linha que la esta: reprocessar o mesmo `media_id`
devolve a ingestao existente e nao cria nada (criterio 1). A verificacao antes
de descarregar e a do `ServicoDeIngestao`; esta e a que vale com dois
processos a correr ao mesmo tempo.

## Concorrencia

O `gravar` recebe a linha **lida** e escreve com `AND versao = %s`. A `versao`
e da base: o *trigger* sobe-a em cada escrita, e nenhum papel tem `UPDATE`
nela. Duas escritas a partir da mesma leitura — duas respostas do dono em
paralelo, ou uma correccao a meio de uma confirmacao — nao se sobrepoem em
silencio, **mesmo sem mudar de estado**: a segunda recebe `ConflitoDeEstado`.
A primeira versao escrevia com `AND estado = %s`, e a revisao adversarial
mostrou o que isso deixava passar (`a_perguntar -> a_perguntar` perdia a
primeira resposta).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from .. import tenant_guard
from . import estados
from .completude import MAXIMO_DE_PERGUNTAS
from .extraccao import Campo
from .screening import FORMA_DA_CATEGORIA


class ConflitoDeEstado(RuntimeError):
    """A linha mudou de estado entre a leitura e a escrita."""


class IngestaoInvalida(ValueError):
    """A linha violaria uma restricao da revisao `catalogo_ai`."""


@dataclass(frozen=True)
class Ingestao:
    """Uma linha de `platform.catalog_ingestions`."""

    id: str
    tenant_id: str
    media_ref: str
    media_id_meta: str | None
    estado: str = estados.RECEBIDA
    phash: bytes | None = None
    campos: Mapping[str, Campo] = field(default_factory=dict)
    campos_em_falta: tuple[str, ...] = ()
    perguntas_feitas: int = 0
    categoria_restrita: str | None = None
    sku: str | None = None
    custo_llm_usd: Decimal = Decimal(0)
    confirmado_at: datetime | None = None
    confirmado_por: str | None = None
    ultima_mensagem_id: str | None = None
    versao: int = 0

    def extraido(self) -> dict[str, Any]:
        """O `jsonb` da coluna: campo -> {valor, confianca, fonte, confirmado, corrigido}."""
        return {nome: campo.como_dict() for nome, campo in self.campos.items()}


def validar(linha: Ingestao) -> None:
    """As restricoes de linha da revisao `catalogo_ai`, do lado de ca. Levanta `IngestaoInvalida`."""
    if linha.estado not in estados.ESTADOS:
        raise IngestaoInvalida(f"estado `{linha.estado}` fora do dominio")
    # O `catalog_ingestions_media_ref_ck`: a chave do STO **do proprio tenant**.
    # Nem uma URL da Meta nem a chave de outro tenant cabem.
    if not linha.media_ref.startswith(f"t/{linha.tenant_id}/catalogo/"):
        raise IngestaoInvalida("media_ref e uma chave do STO do proprio tenant, nunca uma URL")
    if not 0 <= linha.perguntas_feitas <= MAXIMO_DE_PERGUNTAS:
        raise IngestaoInvalida("perguntas_feitas fora de [0, 12]")
    if linha.phash is not None and len(linha.phash) != 8:
        raise IngestaoInvalida("phash tem oito bytes")
    if linha.categoria_restrita is not None and not FORMA_DA_CATEGORIA.fullmatch(linha.categoria_restrita):
        raise IngestaoInvalida("categoria_restrita fora da forma")
    if linha.estado == estados.BLOQUEADA_CATEGORIA and linha.categoria_restrita is None:
        raise IngestaoInvalida("bloqueada_categoria sem categoria_restrita")
    if linha.estado == estados.PUBLICADA and (
        linha.categoria_restrita is not None
        or linha.confirmado_at is None
        or not linha.confirmado_por
        or not linha.sku
    ):
        raise IngestaoInvalida("publicada exige confirmacao do dono, sku e nenhuma categoria restrita")
    if linha.custo_llm_usd < 0:
        raise IngestaoInvalida("custo_llm_usd negativo")
    # Os comprimentos dos `CHECK` de coluna, por paridade: um valor que a base
    # recusaria tem de ser recusado **antes** de qualquer efeito fora dela.
    for nome, valor, maximo in (
        ("media_id_meta", linha.media_id_meta, 256),
        ("sku", linha.sku, 64),
        ("confirmado_por", linha.confirmado_por, 200),
        ("ultima_mensagem_id", linha.ultima_mensagem_id, 256),
    ):
        if valor is not None and not 1 <= len(valor) <= maximo:
            raise IngestaoInvalida(f"{nome} fora de [1, {maximo}] caracteres")


class Repositorio(Protocol):
    """A porta de persistencia do `ServicoDeIngestao`."""

    def inserir(self, linha: Ingestao) -> Ingestao: ...

    def por_media(self, tenant_id: str, media_id_meta: str) -> Ingestao | None: ...

    def ler(self, tenant_id: str, ingestao_id: str) -> Ingestao | None: ...

    def com_phash(self, tenant_id: str, phash: bytes, excepto: str) -> Ingestao | None: ...

    def gravar(self, lido: Ingestao, nova: Ingestao) -> Ingestao: ...


def novo_id() -> str:
    return str(uuid.uuid4())


#: Os estados que nao contam para «e o mesmo produto?»: uma foto rejeitada ou
#: descartada nao e um produto que ja exista.
_FORA_DO_DUPLICADO = frozenset({estados.REJEITADA_QUALIDADE, estados.DESCARTADA})


class RepositorioEmMemoria:
    """A porta em memoria, com as recusas da base."""

    def __init__(self) -> None:
        self._linhas: dict[str, Ingestao] = {}

    def todas(self) -> tuple[Ingestao, ...]:
        return tuple(self._linhas.values())

    def inserir(self, linha: Ingestao) -> Ingestao:
        validar(linha)
        if linha.media_id_meta is not None:
            existente = self.por_media(linha.tenant_id, linha.media_id_meta)
            if existente is not None:
                return existente
        self._linhas[linha.id] = linha
        return linha

    def por_media(self, tenant_id: str, media_id_meta: str) -> Ingestao | None:
        for linha in self._linhas.values():
            if linha.tenant_id == tenant_id and linha.media_id_meta == media_id_meta:
                return linha
        return None

    def ler(self, tenant_id: str, ingestao_id: str) -> Ingestao | None:
        linha = self._linhas.get(ingestao_id)
        return linha if linha is not None and linha.tenant_id == tenant_id else None

    def com_phash(self, tenant_id: str, phash: bytes, excepto: str) -> Ingestao | None:
        for linha in self._linhas.values():
            if (
                linha.tenant_id == tenant_id
                and linha.phash == phash
                and linha.id != excepto
                and linha.estado not in _FORA_DO_DUPLICADO
            ):
                return linha
        return None

    def gravar(self, lido: Ingestao, nova: Ingestao) -> Ingestao:
        actual = self.ler(lido.tenant_id, lido.id)
        if actual is None or actual.versao != lido.versao:
            raise ConflitoDeEstado("a ingestao mudou entre a leitura e a escrita")
        if lido.estado in estados.FINAIS:
            # O *trigger* da base: uma linha final nao muda.
            raise estados.TransicaoRecusada(lido.estado, nova.estado)
        estados.exigir_transicao(lido.estado, nova.estado)
        if nova.perguntas_feitas < lido.perguntas_feitas:
            raise IngestaoInvalida("perguntas_feitas nao desce")
        validar(nova)
        self._linhas[nova.id] = replace(
            nova,
            tenant_id=lido.tenant_id,
            media_ref=lido.media_ref,
            media_id_meta=lido.media_id_meta,
            versao=lido.versao + 1,
        )
        return self._linhas[nova.id]


# ---------------------------------------------------------------- DB-API

_COLUNAS = (
    "id::text, tenant_id::text, media_ref, media_id_meta, estado, phash, extraido::text, "
    "campos_em_falta, perguntas_feitas, categoria_restrita, sku, custo_llm_usd, "
    "confirmado_at, confirmado_por, ultima_mensagem_id, versao"
)

SQL_INSERIR = (
    "INSERT INTO platform.catalog_ingestions (id, tenant_id, media_ref, media_id_meta, phash) "
    "VALUES (%s::uuid, %s::uuid, %s, %s, %s) "
    "ON CONFLICT (tenant_id, media_id_meta) DO NOTHING "
    f"RETURNING {_COLUNAS}"
)
SQL_POR_MEDIA = (
    f"SELECT {_COLUNAS} FROM platform.catalog_ingestions "
    "WHERE tenant_id = %s::uuid AND media_id_meta = %s"
)
SQL_LER = f"SELECT {_COLUNAS} FROM platform.catalog_ingestions WHERE tenant_id = %s::uuid AND id = %s::uuid"
SQL_COM_PHASH = (
    f"SELECT {_COLUNAS} FROM platform.catalog_ingestions "
    "WHERE tenant_id = %s::uuid AND phash = %s AND id <> %s::uuid "
    "AND estado NOT IN ('rejeitada_qualidade', 'descartada') "
    "ORDER BY criado_at, id LIMIT 1"
)
SQL_GRAVAR = (
    "UPDATE platform.catalog_ingestions SET estado = %s, phash = %s, extraido = %s::jsonb, "
    "campos_em_falta = %s::text[], perguntas_feitas = %s, categoria_restrita = %s, sku = %s, "
    "custo_llm_usd = %s, confirmado_at = %s, confirmado_por = %s, ultima_mensagem_id = %s "
    "WHERE tenant_id = %s::uuid AND id = %s::uuid AND versao = %s "
    f"RETURNING {_COLUNAS}"
)


def _de_linha(linha: Sequence[Any]) -> Ingestao:
    (id_, tenant, media_ref, media_id, estado, phash, extraido, falta, feitas, restrita, sku, custo, conf_at, conf_por,
     ultima, versao) = linha
    bruto = json.loads(extraido) if isinstance(extraido, str) else (extraido or {})
    return Ingestao(
        id=str(id_),
        tenant_id=str(tenant),
        media_ref=media_ref,
        media_id_meta=media_id,
        estado=estado,
        phash=bytes(phash) if phash is not None else None,
        campos={nome: Campo.de_dict(dados) for nome, dados in bruto.items()},
        campos_em_falta=tuple(falta or ()),
        perguntas_feitas=int(feitas),
        categoria_restrita=restrita,
        sku=sku,
        custo_llm_usd=Decimal(str(custo)),
        confirmado_at=conf_at,
        confirmado_por=conf_por,
        ultima_mensagem_id=ultima,
        versao=int(versao),
    )


class RepositorioDbapi:
    """A porta sobre `platform.catalog_ingestions`, uma ligacao por chamada."""

    def __init__(self, abrir_ligacao: Callable[[], Any]) -> None:
        self._abrir = abrir_ligacao

    def _uma(self, tenant_id: str, sql: str, parametros: tuple[object, ...]) -> Ingestao | None:
        ligacao = self._abrir()
        try:
            with tenant_guard.tx(ligacao, tenant_id) as cursor:
                cursor.execute(sql, parametros)
                linha = cursor.fetchone()
                return _de_linha(linha) if linha else None
        finally:
            ligacao.close()

    def inserir(self, linha: Ingestao) -> Ingestao:
        validar(linha)
        criada = self._uma(
            linha.tenant_id,
            SQL_INSERIR,
            (linha.id, linha.tenant_id, linha.media_ref, linha.media_id_meta, linha.phash),
        )
        if criada is not None:
            return criada
        # So o conflito do `(tenant_id, media_id_meta)` devolve vazio.
        existente = (
            self.por_media(linha.tenant_id, linha.media_id_meta)
            if linha.media_id_meta is not None
            else None
        )
        if existente is None:
            raise ConflitoDeEstado("conflito de media_id sem linha visivel")
        return existente

    def por_media(self, tenant_id: str, media_id_meta: str) -> Ingestao | None:
        return self._uma(tenant_id, SQL_POR_MEDIA, (tenant_id, media_id_meta))

    def ler(self, tenant_id: str, ingestao_id: str) -> Ingestao | None:
        return self._uma(tenant_id, SQL_LER, (tenant_id, ingestao_id))

    def com_phash(self, tenant_id: str, phash: bytes, excepto: str) -> Ingestao | None:
        return self._uma(tenant_id, SQL_COM_PHASH, (tenant_id, phash, excepto))

    def gravar(self, lido: Ingestao, nova: Ingestao) -> Ingestao:
        estados.exigir_transicao(lido.estado, nova.estado)
        validar(nova)
        escrita = self._uma(
            lido.tenant_id,
            SQL_GRAVAR,
            (
                nova.estado,
                nova.phash,
                json.dumps(nova.extraido(), ensure_ascii=False, sort_keys=True),
                list(nova.campos_em_falta),
                nova.perguntas_feitas,
                nova.categoria_restrita,
                nova.sku,
                nova.custo_llm_usd,
                nova.confirmado_at,
                nova.confirmado_por,
                nova.ultima_mensagem_id,
                lido.tenant_id,
                lido.id,
                lido.versao,
            ),
        )
        if escrita is None:
            raise ConflitoDeEstado("a ingestao mudou entre a leitura e a escrita")
        return escrita


def agora_utc() -> datetime:
    return datetime.now(UTC)
