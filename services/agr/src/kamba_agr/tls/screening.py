"""A ponte Python -> TypeScript para o `screen` do KAM-088 (KAM-222).

O motor do screening so existe em `packages/core-ts/src/screening/`, e a porta
Python (`PortaDeScreening` de `kamba_core.catalogo.screening`) e o contrato
dele. **Nao ha segundo motor em Python.** Este adaptador chama o `screen` pela
12.a rota da API interna do COM (`POST /internal/screen`, nota em
`services/com/src/screening/index.ts`), pelo mesmo `ClienteDoCom` das tools de
comercio, com o `com_internal_token` e o `x-kamba-tenant`.

## O sujeito e do adaptador

O `PortaDeScreening` nao tem sujeito na assinatura: foi escrito para o produto
do Catalogo AI. O sujeito e do adaptador, e a rota aceita dois: o das condicoes
de um orcamento (KAM-123, `CHECK` desde a revisao `0074`) e o `produto`
(KAM-119). O `produto` abriu quando a re-analise passou a comparar o
`conteudo_sha256` (`SQL_POR_REANALISAR`): uma decisao gravada por aqui com outro
texto ja nao faz a re-analise saltar o produto publicado. O `conferir_condicoes`
continua a so aceitar uma porta das condicoes (`orcamento/regras.py`), e por
isso nao grava `produto` com o `quote_id`.

## A categoria declarada, quando nao ha

`None` vai como `null`, e o COM usa a categoria declarada do tenant (a da
decisao de categoria mais recente). E o caso das condicoes, que nao tem
categoria propria.

## *Fail-closed*, e sem texto

Tudo o que nao seja um 200 com um resultado de forma fechada **levanta**: um
erro do COM, um *timeout*, uma decisao fora do dominio, uma regra que nao e
cadeia. Quem chama trata a excepcao como `screening_indisponivel` e recusa. Nem a
mensagem da excepcao nem o registo levam os textos: e texto do dono ou do
cliente, e o ADR-010 nao o deixa sair para um registo.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from kamba_core.catalogo.screening import DECISOES, PERMITIDA, REGRA_REVISAO_PENDENTE, ResultadoDoScreen

from .com import ClienteDoCom

#: A rota do COM. Igual a da constante `ROTAS` de `services/com/src/api/interna.ts`.
ROTA: Final = "/internal/screen"

#: Os sujeitos que o COM aceita na rota (`SUJEITOS_DA_ROTA`): o das condicoes
#: (KAM-222) e o `produto` (KAM-119). Nunca a `categoria`, que e do onboarding.
SUJEITOS: Final = ("condicoes", "produto")

#: O sujeito das condicoes de um orcamento, e o de um produto do Catalogo AI.
SUJEITO_DAS_CONDICOES: Final = "condicoes"
SUJEITO_DO_PRODUTO: Final = "produto"

#: O tecto de uma chamada. O classificador do `screen` tem 15 s
#: (`TEMPO_MAXIMO_MS` do `classificador.ts`), e o COM grava depois: vinte
#: segundos sao essa espera mais a gravacao, e nao um alvo.
TEMPO_MAXIMO_MS: Final = 20_000


class ScreeningIndisponivelError(RuntimeError):
    """O `screen` nao respondeu com um resultado valido. Sem texto na mensagem."""


@dataclass(frozen=True, slots=True)
class _Ctx:
    """O `ctx` que o `ClienteDoCom.chamar` le: tenant, vertical e o fio do pedido."""

    tenant_id: str
    vertical: str
    turn_id: str


def _resultado(valor: Mapping[str, Any], *, do_produto: bool = False) -> ResultadoDoScreen:
    """O resultado do COM, lido contra a forma fechada, ou levanta.

    **No `produto` le-se tambem o `publicavel`** (KAM-119): o `assertPublishable`
    do mesmo conteudo, depois de gravada a decisao. Uma `permitida` que nao e
    publicavel — uma `condicional` anterior do mesmo texto espera por humano —
    chega ao pipeline como `condicional` com a `revisao_pendente` no fim, que e
    o que o `publish-product` vai recusar. Sem o campo, levanta.
    """
    decisao = valor.get("decisao")
    regras = valor.get("regras")
    versao = valor.get("versao_politica")
    confianca = valor.get("confianca")
    if not isinstance(decisao, str) or decisao not in DECISOES:
        raise ScreeningIndisponivelError("decisao fora do dominio")
    if not isinstance(regras, list) or not all(isinstance(r, str) for r in regras):
        raise ScreeningIndisponivelError("regras fora da forma")
    if not isinstance(versao, str) or not versao:
        raise ScreeningIndisponivelError("versao da politica em falta")
    if isinstance(confianca, bool) or not isinstance(confianca, (int, float)):
        raise ScreeningIndisponivelError("confianca fora da forma")
    if do_produto:
        publicavel = valor.get("publicavel")
        if not isinstance(publicavel, bool):
            raise ScreeningIndisponivelError("publicavel em falta")
        if decisao == PERMITIDA and not publicavel:
            return ResultadoDoScreen(
                decisao="condicional",
                regras=(*regras, REGRA_REVISAO_PENDENTE),
                versao_politica=versao,
                confianca=0.0,
            )
    return ResultadoDoScreen(
        decisao=decisao, regras=tuple(regras), versao_politica=versao, confianca=float(confianca)
    )


@dataclass(frozen=True, slots=True)
class ScreeningPeloCom:
    """O `PortaDeScreening` sobre o COM, para um sujeito."""

    cliente: ClienteDoCom
    sujeito_tipo: str
    #: A vertical que o `actor` do COM nomeia (`grafo-<vertical>`).
    vertical: str
    timeout_ms: int = TEMPO_MAXIMO_MS

    def __post_init__(self) -> None:
        if self.sujeito_tipo not in SUJEITOS:
            raise ValueError(f"sujeito fora de {', '.join(SUJEITOS)}")

    nome = "screening-pelo-com"

    def screen(
        self,
        tenant_id: str,
        sujeito_ref: str,
        categoria_declarada: str | None,
        textos: Sequence[str],
    ) -> ResultadoDoScreen:
        ctx = _Ctx(tenant_id=tenant_id, vertical=self.vertical, turn_id=uuid.uuid4().hex)
        corpo = {
            "sujeito_tipo": self.sujeito_tipo,
            "sujeito_ref": sujeito_ref,
            "categoria_declarada": categoria_declarada,
            "textos": list(textos),
        }
        try:
            valor = self.cliente.chamar(ROTA, ctx, corpo, self.timeout_ms)
        except Exception as excepcao:  # noqa: BLE001 — qualquer falha e fechada
            # O `ErroDeBackend` diz o codigo e a rota, e nao o corpo. Mesmo
            # assim nao se encadeia a mensagem: a classe basta a quem opera.
            raise ScreeningIndisponivelError(type(excepcao).__name__) from None
        return _resultado(valor, do_produto=self.sujeito_tipo == SUJEITO_DO_PRODUTO)
