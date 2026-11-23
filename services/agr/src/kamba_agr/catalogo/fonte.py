"""A fonte da foto do dono: a `platform.media_assets` e o STO (KAM-231).

## O caminho de uma foto, do canal ao pipeline

```text
CHR    image do dono --MED (KAM-020)--> media_assets (armazenado) + objecto no STO
painel foto do dono -----------------> media_assets (armazenado) + objecto no STO
       --agent_invocation com asset_id, persona dono-->  AGR
AGR    o no do catalogo passa o asset_id ao create_product_draft
TLS    le a linha pelo asset_id (`ler_asset`), no tenant da invocacao
       servico.receber(tenant, media_id da linha)  -- a idempotencia do KAM-049
       FonteDoMed.descarregar(tenant, media_id)   -- os bytes do STO
```

**O `agent_invocation` leva o `asset_id` e nunca os bytes nem o `media_id` da
Meta**: os detalhes da Meta nao saem do CHR. O executor e que le o `media_id` da
linha, e e por ele que o pipeline e idempotente (`catalog_ingestions_media_uq`,
`UNIQUE (tenant_id, media_id_meta)`): a mesma foto da Meta entregue duas vezes
da **uma** ingestao, que e a letra do criterio 1. Uma foto do painel nao tem
`media_id` da Meta, e o painel grava um proprio (`painel.{uuid}`), pela forma do
`wamid` de um turno do painel.

## Tudo no tenant da invocacao, e duas vezes

As duas consultas correm como `kamba_app`, com o `app.tenant_id` da invocacao
(`tenant_guard.tx`), e com o `tenant_id` no predicado: a RLS `FORCE` da `0012`
e a primeira barreira e o predicado e a segunda. O STO e a terceira: o `get`
recusa uma chave fora do prefixo do tenant (`ChaveForaDoTenantError`).

**So uma linha `armazenado` da classe `media_imagem`** vira fonte. Um
`pendente`, um `rejeitado` ou um `falhou` nao tem objecto, e um audio ou um
documento nao e uma foto de produto: os dois recusam como uma foto que nao
chegou (`FotoIndisponivelError`), e o dono e avisado.

**O tecto de bytes e o do MED** (`media_imagem`, 5 MiB, *proposta* do KAM-020):
o objecto ja passou por ele a entrada, e aqui e a segunda barreira, que corta a
leitura em vez de materializar um objecto que alguem tenha posto no STO por
outro caminho.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from kamba_core import tenant_guard
from kamba_core.storage.port import Ctx, ObjectRef, StorageProvider

from .montagem import FotoPorLigarError

#: A classe de uma foto na `media_assets` (dicionario §3.16).
CLASSE_DA_FOTO: Final = "media_imagem"

#: O estado de uma linha com objecto no STO.
ARMAZENADO: Final = "armazenado"

#: O tecto do MED para a classe `media_imagem` (`packages/core-ts/src/med/classes.ts`).
BYTES_MAXIMOS: Final = 5 * 1024 * 1024

#: A linha de uma foto pelo `asset_id` que a invocacao trouxe.
SQL_ASSET: Final = (
    "SELECT media_id, estado, classe, storage_ref FROM platform.media_assets "
    "WHERE tenant_id = %s::uuid AND asset_id = %s::uuid"
)

#: O objecto de um `media_id`. Varias linhas podem ter o mesmo `media_id` (uma
#: por `wamid`): sao o mesmo objecto da Meta, e a primeira armazenada serve.
SQL_OBJECTO_DA_MEDIA: Final = (
    "SELECT storage_ref FROM platform.media_assets "
    "WHERE tenant_id = %s::uuid AND media_id = %s "
    "AND estado = 'armazenado' AND classe = 'media_imagem' AND storage_ref IS NOT NULL "
    "ORDER BY criado_at, asset_id LIMIT 1"
)


class FotoIndisponivelError(FotoPorLigarError):
    """A foto nao esta no STO: a linha nao existe, nao esta armazenada ou nao e uma imagem."""


@dataclass(frozen=True)
class AssetDaFoto:
    """O que o executor precisa de uma linha da `media_assets`."""

    media_id: str
    storage_ref: str


def ler_asset(ligacao: Any, tenant_id: str, asset_id: str) -> AssetDaFoto:
    """A foto de um `asset_id` **deste** tenant, ou `FotoIndisponivelError`."""
    with tenant_guard.tx(ligacao, tenant_id) as cursor:
        cursor.execute(SQL_ASSET, (tenant_id, asset_id))
        linha = cursor.fetchone()
    if linha is None:
        raise FotoIndisponivelError("a foto nao existe neste tenant")
    media_id, estado, classe, storage_ref = linha
    if estado != ARMAZENADO or classe != CLASSE_DA_FOTO or not storage_ref:
        raise FotoIndisponivelError("a foto nao esta armazenada como imagem")
    return AssetDaFoto(media_id=str(media_id), storage_ref=str(storage_ref))


@dataclass(frozen=True)
class FonteDoMed:
    """A `FonteDeMedia` do KAM-049 sobre o MED: a `media_assets` e o STO.

    Uma por invocacao, sobre a ligacao dela (`PortasDoCatalogo.fonte_sobre`).
    """

    ligacao: Any
    storage: StorageProvider
    bytes_maximos: int = BYTES_MAXIMOS

    def descarregar(self, tenant_id: str, media_id: str) -> bytes:
        with tenant_guard.tx(self.ligacao, tenant_id) as cursor:
            cursor.execute(SQL_OBJECTO_DA_MEDIA, (tenant_id, media_id))
            linha = cursor.fetchone()
        if linha is None:
            raise FotoIndisponivelError("a foto nao esta armazenada como imagem")
        partes: list[bytes] = []
        lidos = 0
        for parte in self.storage.get(Ctx(tenant_id), ObjectRef(key=str(linha[0]), tamanho=0)):
            lidos += len(parte)
            if lidos > self.bytes_maximos:
                raise FotoIndisponivelError("a foto passa o tecto do MED")
            partes.append(parte)
        if lidos == 0:
            raise FotoIndisponivelError("a foto esta vazia")
        return b"".join(partes)


__all__ = [
    "ARMAZENADO",
    "AssetDaFoto",
    "BYTES_MAXIMOS",
    "CLASSE_DA_FOTO",
    "FonteDoMed",
    "FotoIndisponivelError",
    "SQL_ASSET",
    "SQL_OBJECTO_DA_MEDIA",
    "ler_asset",
]
