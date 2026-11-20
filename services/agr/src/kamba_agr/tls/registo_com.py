"""A `PortaDoRegisto` do Catalogo AI sobre a API interna do COM (KAM-119).

O pipeline do KAM-049 escreve o produto no Registo por uma porta de dois
metodos (`rascunho`, `publicar`), e o Registo e do COM, em TypeScript. Este
adaptador fala com as duas rotas que o KAM-119 acrescentou a API interna, pelo
mesmo `ClienteDoCom` das tools de comercio (o `com_internal_token` e o
`x-kamba-tenant`):

| Metodo | Rota | No COM |
|---|---|---|
| `rascunho` | `POST /internal/upsert-product-draft` | `upsertProductDraft` da porta — **nunca publica** |
| `publicar` | `POST /internal/publish-product` | `assertPublishable` do KAM-088 sobre a categoria do tenant e o `nome`, e so depois `publishProduct` |

## Preco e stock sao do dono, e chegam aqui ja lidos

Os campos que o pipeline passa sao os da ingestao, confirmados pelo dono no
resumo. O `preco` e o valor em centimos que o eco gravou (`catalogo/regras.py`);
vai ao COM como cadeia de digitos, a forma canonica do `emMinor` da API
interna, e so quando o `preco_tipo` leva numero — o `sob_consulta` vai com
`null`, que e o que o `offer_terms_preco_ck` exige. A **quantidade** em stock
nao tem campo no rascunho da porta (`ProductDraft`): fica na ingestao e no
resumo, e o limite esta escrito no bloco.

## *Fail-closed*

Qualquer recusa do COM sobe como `ErroDeBackend` com o codigo canonico, e o
pipeline nao a engole: um rascunho que o Registo recusou nao e um rascunho, e
uma publicacao que o `assertPublishable` recusou nao e uma publicacao.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from kamba_core.catalogo.completude import PRECO_TIPOS, PRECO_TIPOS_COM_NUMERO, STOCK_MODOS
from kamba_core.catalogo.extraccao import Campo
from kamba_core.catalogo.pipeline import ConfirmacaoDoDono

from .com import ClienteDoCom
from .erros import VALIDATION_ERROR
from .especificacoes import ErroDeBackend

#: As duas rotas. Iguais as da constante `ROTAS` de `services/com/src/api/interna.ts`.
ROTA_DO_RASCUNHO: Final = "/internal/upsert-product-draft"
ROTA_DA_PUBLICACAO: Final = "/internal/publish-product"

#: O tecto de uma chamada. *Proposta*: as duas sao escritas curtas na base.
TEMPO_MAXIMO_MS: Final = 5_000


@dataclass(frozen=True, slots=True)
class _Ctx:
    """O `ctx` que o `ClienteDoCom.chamar` le: tenant, vertical e o fio do pedido."""

    tenant_id: str
    vertical: str
    turn_id: str


def _texto(campos: Mapping[str, Campo], nome: str) -> str | None:
    campo = campos.get(nome)
    return campo.valor if campo is not None and isinstance(campo.valor, str) else None


def corpo_do_rascunho(sku: str, campos: Mapping[str, Campo]) -> dict[str, object]:
    """O corpo do `upsert-product-draft`, ou levanta `ErroDeBackend(VALIDATION_ERROR)`.

    Recusa **antes** da rede o que o COM recusaria: sem nome, sem `preco_tipo`
    conhecido, um preco que nao e digitos quando o tipo o pede.
    """
    nome = _texto(campos, "nome")
    preco_tipo = _texto(campos, "preco_tipo")
    if not nome or preco_tipo not in PRECO_TIPOS:
        raise ErroDeBackend(VALIDATION_ERROR, "rascunho_incompleto")
    preco_minor: str | None = None
    if preco_tipo in PRECO_TIPOS_COM_NUMERO:
        preco = _texto(campos, "preco")
        if preco is None or not preco.isdigit() or int(preco) <= 0:
            raise ErroDeBackend(VALIDATION_ERROR, "rascunho_sem_preco")
        preco_minor = preco
    corpo: dict[str, object] = {
        "sku": sku,
        "nome": nome,
        "preco_tipo": preco_tipo,
        "preco_minor": preco_minor,
    }
    stock_modo = _texto(campos, "stock_modo")
    if stock_modo in STOCK_MODOS:
        corpo["stock_modo"] = stock_modo
    return corpo


@dataclass(frozen=True, slots=True)
class RegistoPeloCom:
    """A `PortaDoRegisto` do KAM-049 sobre o COM."""

    cliente: ClienteDoCom
    #: A vertical que o `actor` do COM nomeia (`grafo-<vertical>`).
    vertical: str = "dono"
    timeout_ms: int = TEMPO_MAXIMO_MS

    def _ctx(self, tenant_id: str) -> _Ctx:
        return _Ctx(tenant_id=tenant_id, vertical=self.vertical, turn_id=uuid.uuid4().hex)

    def rascunho(self, tenant_id: str, sku: str, campos: Mapping[str, Campo]) -> None:
        self.cliente.chamar(ROTA_DO_RASCUNHO, self._ctx(tenant_id), corpo_do_rascunho(sku, campos), self.timeout_ms)

    def publicar(self, tenant_id: str, sku: str, confirmacao: ConfirmacaoDoDono) -> None:
        if confirmacao.em.tzinfo is None:
            raise ErroDeBackend(VALIDATION_ERROR, "confirmacao_sem_fuso")
        corpo = {
            "sku": sku,
            "confirmacao": {"actor_id": confirmacao.actor, "em": confirmacao.em.isoformat()},
        }
        self.cliente.chamar(ROTA_DA_PUBLICACAO, self._ctx(tenant_id), corpo, self.timeout_ms)


class RegistoPorLigar:
    """A porta sem COM configurado (`KAMBA_COM_URL` vazio). **Levanta sempre**."""

    def rascunho(self, tenant_id: str, sku: str, campos: Mapping[str, Campo]) -> None:
        raise ErroDeBackend("UPSTREAM_DOWN", "registo_por_ligar")

    def publicar(self, tenant_id: str, sku: str, confirmacao: ConfirmacaoDoDono) -> None:
        raise ErroDeBackend("UPSTREAM_DOWN", "registo_por_ligar")


__all__ = [
    "ROTA_DA_PUBLICACAO",
    "ROTA_DO_RASCUNHO",
    "RegistoPeloCom",
    "RegistoPorLigar",
    "corpo_do_rascunho",
]
