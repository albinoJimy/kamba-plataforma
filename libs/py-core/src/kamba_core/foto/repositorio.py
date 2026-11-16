"""A persistencia de `platform.image_jobs` (KAM-120; revisao `foto_de_produtos`).

Duas implementacoes da mesma porta, como no Catalogo AI:

* `RepositorioEmMemoria`, para as baterias unitarias, com as recusas da base
  (a unicidade da chave de idempotencia, as transicoes, o `motivo` amarrado ao
  estado, o `concluido` que so muda a escolha, o custo que nao desce);
* `RepositorioDbapi`, sobre uma ligacao DB-API por chamada, dentro do
  `tenant_guard.tx`. O `tenant_id` vem do contexto da RLS **e** do predicado.

## Idempotencia

O `inserir` e `INSERT … ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`
seguido da leitura da linha que la esta: a mesma chave duas vezes da **um**
trabalho (criterio 9), mesmo com dois processos ao mesmo tempo.

## Concorrencia

O `gravar` escreve contra a `versao` lida, que e do *trigger*: dois
trabalhadores que recebam o mesmo trabalho (a fila entrega «pelo menos uma
vez») nao se sobrepoem — o segundo recebe `ConflitoDeEstado` e nao chama o
fornecedor outra vez.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol

from .. import tenant_guard
from . import estados
from .fornecedor import FORMA_DO_FORNECEDOR, GENERATIVAS, OPERACOES

#: A classe da versao no STO: `t/{tenant}/foto/…`.
CLASSE_STO: Final = "foto"

#: As classes de onde vem um original: a foto da ingestao do Catalogo AI
#: (KAM-049) e uma versao anterior (melhorar a versao melhorada).
CLASSES_DE_ORIGEM: Final = ("catalogo", CLASSE_STO)


class ConflitoDeEstado(RuntimeError):
    """A linha mudou entre a leitura e a escrita."""


class TrabalhoInvalido(ValueError):
    """A linha violaria uma restricao da revisao `foto_de_produtos`."""


@dataclass(frozen=True)
class Trabalho:
    """Uma linha de `platform.image_jobs`."""

    image_job_id: str
    tenant_id: str
    origem_ref: str
    operacao: str
    provider: str
    idempotency_key: str
    estado: str = estados.PENDENTE
    motivo: str | None = None
    versao_ref: str | None = None
    sintetica: bool = False
    escolhida: bool = False
    custo_usd: Decimal = Decimal(0)
    latencia_ms: int | None = None
    aviso_at: datetime | None = None
    versao: int = 0
    #: Do gatilho: a ultima escrita. E por ele que o `recuperar` sabe que um
    #: `a_processar` esta preso.
    atualizado_at: datetime | None = None

    @property
    def gerado_por_ia(self) -> bool:
        """A coluna gerada da base, com a mesma expressao."""
        return self.operacao in GENERATIVAS


def validar(linha: Trabalho) -> None:
    """As restricoes de linha da revisao, do lado de ca. Levanta `TrabalhoInvalido`."""
    if linha.estado not in estados.ESTADOS:
        raise TrabalhoInvalido(f"estado `{linha.estado}` fora do dominio")
    if linha.operacao not in OPERACOES:
        raise TrabalhoInvalido(f"operacao `{linha.operacao}` fora do dominio")
    if not FORMA_DO_FORNECEDOR.fullmatch(linha.provider):
        raise TrabalhoInvalido("provider fora da forma")
    if not any(linha.origem_ref.startswith(f"t/{linha.tenant_id}/{classe}/") for classe in CLASSES_DE_ORIGEM):
        # So a foto de um produto: o `image_jobs_origem_ref_ck`. Uma chave de
        # outra classe (um documento KYC, a media de um cliente) nao e foto de
        # produto e nao sai por aqui (achado da revisao adversarial).
        raise TrabalhoInvalido("origem_ref e uma foto `catalogo` ou `foto` do proprio tenant")
    if linha.versao_ref is not None and not linha.versao_ref.startswith(f"t/{linha.tenant_id}/{CLASSE_STO}/"):
        raise TrabalhoInvalido("versao_ref e uma chave `foto` do proprio tenant")
    if not 1 <= len(linha.idempotency_key) <= 200:
        raise TrabalhoInvalido("idempotency_key fora de [1, 200] caracteres")
    if not estados.motivo_valido(linha.estado, linha.motivo):
        raise TrabalhoInvalido(f"motivo `{linha.motivo}` nao cabe no estado `{linha.estado}`")
    if linha.estado == estados.CONCLUIDO and (linha.versao_ref is None or linha.latencia_ms is None):
        raise TrabalhoInvalido("concluido exige versao_ref e latencia_ms")
    if linha.escolhida and linha.estado != estados.CONCLUIDO:
        raise TrabalhoInvalido("so um concluido se escolhe")
    if linha.custo_usd < 0 or (linha.latencia_ms is not None and linha.latencia_ms < 0):
        raise TrabalhoInvalido("custo e latencia nao sao negativos")


def exigir_escrita(lido: Trabalho, nova: Trabalho) -> None:
    """O *trigger* `image_jobs_transicao`, do lado de ca."""
    if lido.estado == estados.FALHADO:
        raise estados.TransicaoRecusada(lido.estado, nova.estado)
    if lido.estado == estados.CONCLUIDO and (
        nova.estado != lido.estado
        or nova.versao_ref != lido.versao_ref
        or nova.provider != lido.provider
        or nova.custo_usd != lido.custo_usd
        or nova.latencia_ms != lido.latencia_ms
        or nova.motivo != lido.motivo
    ):
        raise estados.TransicaoRecusada(lido.estado, nova.estado)
    if nova.custo_usd < lido.custo_usd:
        raise TrabalhoInvalido("custo_usd nao desce")
    estados.exigir_transicao(lido.estado, nova.estado)


class Repositorio(Protocol):
    def inserir(self, linha: Trabalho) -> Trabalho: ...

    def ler(self, tenant_id: str, image_job_id: str) -> Trabalho | None: ...

    def tem_trabalhos(self, tenant_id: str) -> bool: ...

    def escolhida_de(self, tenant_id: str, origem_ref: str) -> Trabalho | None: ...

    def gravar(self, lido: Trabalho, nova: Trabalho) -> Trabalho: ...


def novo_id() -> str:
    return str(uuid.uuid4())


class RepositorioEmMemoria:
    """A porta em memoria, com as recusas da base."""

    def __init__(self, agora: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._linhas: dict[str, Trabalho] = {}
        #: O relogio do «gatilho»: poe o `atualizado_at` como a base.
        self.agora = agora

    def todas(self) -> tuple[Trabalho, ...]:
        return tuple(self._linhas.values())

    def inserir(self, linha: Trabalho) -> Trabalho:
        validar(linha)
        for existente in self._linhas.values():
            if existente.tenant_id == linha.tenant_id and existente.idempotency_key == linha.idempotency_key:
                return existente
        self._linhas[linha.image_job_id] = replace(linha, versao=0, atualizado_at=self.agora())
        return self._linhas[linha.image_job_id]

    def ler(self, tenant_id: str, image_job_id: str) -> Trabalho | None:
        linha = self._linhas.get(image_job_id)
        return linha if linha is not None and linha.tenant_id == tenant_id else None

    def tem_trabalhos(self, tenant_id: str) -> bool:
        return any(linha.tenant_id == tenant_id for linha in self._linhas.values())

    def escolhida_de(self, tenant_id: str, origem_ref: str) -> Trabalho | None:
        for linha in self._linhas.values():
            if linha.tenant_id == tenant_id and linha.origem_ref == origem_ref and linha.escolhida:
                return linha
        return None

    def gravar(self, lido: Trabalho, nova: Trabalho) -> Trabalho:
        actual = self.ler(lido.tenant_id, lido.image_job_id)
        if actual is None or actual.versao != lido.versao:
            raise ConflitoDeEstado("o trabalho mudou entre a leitura e a escrita")
        exigir_escrita(actual, nova)
        validar(nova)
        if nova.escolhida:
            # O `image_jobs_escolhida_uq`: uma escolhida por original.
            outra = self.escolhida_de(actual.tenant_id, actual.origem_ref)
            if outra is not None and outra.image_job_id != actual.image_job_id:
                raise ConflitoDeEstado("ja ha uma versao escolhida deste original")
        # O que o `kamba_app` nao pode actualizar fica como estava.
        self._linhas[lido.image_job_id] = replace(
            nova,
            image_job_id=actual.image_job_id,
            tenant_id=actual.tenant_id,
            origem_ref=actual.origem_ref,
            operacao=actual.operacao,
            idempotency_key=actual.idempotency_key,
            sintetica=actual.sintetica,
            aviso_at=actual.aviso_at,
            versao=actual.versao + 1,
            atualizado_at=self.agora(),
        )
        return self._linhas[lido.image_job_id]


# ---------------------------------------------------------------- DB-API

_COLUNAS = (
    "image_job_id::text, tenant_id::text, origem_ref, operacao, provider, idempotency_key, "
    "estado, motivo, versao_ref, sintetica, escolhida, custo_usd, latencia_ms, aviso_at, versao, atualizado_at"
)

SQL_INSERIR = (
    "INSERT INTO platform.image_jobs (image_job_id, tenant_id, origem_ref, operacao, provider, "
    "idempotency_key, sintetica, aviso_at) "
    "VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING "
    f"RETURNING {_COLUNAS}"
)
SQL_POR_CHAVE = (
    f"SELECT {_COLUNAS} FROM platform.image_jobs WHERE tenant_id = %s::uuid AND idempotency_key = %s"
)
SQL_LER = f"SELECT {_COLUNAS} FROM platform.image_jobs WHERE tenant_id = %s::uuid AND image_job_id = %s::uuid"
SQL_TEM = "SELECT 1 FROM platform.image_jobs WHERE tenant_id = %s::uuid LIMIT 1"
SQL_ESCOLHIDA = (
    f"SELECT {_COLUNAS} FROM platform.image_jobs "
    "WHERE tenant_id = %s::uuid AND origem_ref = %s AND escolhida"
)
SQL_GRAVAR = (
    "UPDATE platform.image_jobs SET estado = %s, motivo = %s, provider = %s, versao_ref = %s, "
    "custo_usd = %s, latencia_ms = %s, escolhida = %s "
    "WHERE tenant_id = %s::uuid AND image_job_id = %s::uuid AND versao = %s "
    f"RETURNING {_COLUNAS}"
)


def _de_linha(linha: Sequence[Any]) -> Trabalho:
    (id_, tenant, origem, operacao, provider, chave, estado, motivo, versao_ref, sintetica, escolhida, custo,
     latencia, aviso, versao, atualizado_at) = linha
    return Trabalho(
        image_job_id=str(id_),
        tenant_id=str(tenant),
        origem_ref=origem,
        operacao=operacao,
        provider=provider,
        idempotency_key=chave,
        estado=estado,
        motivo=motivo,
        versao_ref=versao_ref,
        sintetica=bool(sintetica),
        escolhida=bool(escolhida),
        custo_usd=Decimal(str(custo)),
        latencia_ms=None if latencia is None else int(latencia),
        aviso_at=aviso,
        versao=int(versao),
        atualizado_at=atualizado_at,
    )


class RepositorioDbapi:
    """A porta sobre `platform.image_jobs`, uma ligacao por chamada."""

    def __init__(self, abrir_ligacao: Callable[[], Any]) -> None:
        self._abrir = abrir_ligacao

    def _uma(self, tenant_id: str, sql: str, parametros: tuple[object, ...]) -> Sequence[Any] | None:
        ligacao = self._abrir()
        try:
            with tenant_guard.tx(ligacao, tenant_id) as cursor:
                cursor.execute(sql, parametros)
                return cursor.fetchone()
        finally:
            ligacao.close()

    def inserir(self, linha: Trabalho) -> Trabalho:
        validar(linha)
        criada = self._uma(
            linha.tenant_id,
            SQL_INSERIR,
            (
                linha.image_job_id,
                linha.tenant_id,
                linha.origem_ref,
                linha.operacao,
                linha.provider,
                linha.idempotency_key,
                linha.sintetica,
                linha.aviso_at,
            ),
        )
        if criada is not None:
            return _de_linha(criada)
        existente = self._uma(linha.tenant_id, SQL_POR_CHAVE, (linha.tenant_id, linha.idempotency_key))
        if existente is None:
            raise ConflitoDeEstado("conflito de idempotency_key sem linha visivel")
        return _de_linha(existente)

    def ler(self, tenant_id: str, image_job_id: str) -> Trabalho | None:
        linha = self._uma(tenant_id, SQL_LER, (tenant_id, image_job_id))
        return _de_linha(linha) if linha else None

    def tem_trabalhos(self, tenant_id: str) -> bool:
        return self._uma(tenant_id, SQL_TEM, (tenant_id,)) is not None

    def escolhida_de(self, tenant_id: str, origem_ref: str) -> Trabalho | None:
        linha = self._uma(tenant_id, SQL_ESCOLHIDA, (tenant_id, origem_ref))
        return _de_linha(linha) if linha else None

    def gravar(self, lido: Trabalho, nova: Trabalho) -> Trabalho:
        exigir_escrita(lido, nova)
        validar(nova)
        escrita = self._uma(
            lido.tenant_id,
            SQL_GRAVAR,
            (
                nova.estado,
                nova.motivo,
                nova.provider,
                nova.versao_ref,
                nova.custo_usd,
                nova.latencia_ms,
                nova.escolhida,
                lido.tenant_id,
                lido.image_job_id,
                lido.versao,
            ),
        )
        if escrita is None:
            raise ConflitoDeEstado("o trabalho mudou entre a leitura e a escrita")
        return _de_linha(escrita)
