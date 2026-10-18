"""O *hook* do TEN para a ToolLayer (KAM-009; `docs/tecnica/02` §6.1, passo 2).

O pipeline de `invoke` da TLS tem oito passos e falha-fecha em cada um. O passo
2 e «entitlement activo e limites do TEN», e e este modulo. O espelho do lado
TypeScript e o `middleware.ts`, que faz o mesmo para HTTP; o que muda e a forma
da saida — ali um estado e um corpo, aqui um erro tipado do §6.5 —, e **nao** a
ordem nem a decisao, que sao as mesmas e tem teste a confronta-las.

## Porque e que recebe o contexto e nao os `args`

«O modelo nunca ve nem fornece `tenant_id`: as tools sao construidas por turno
a partir do contexto do estado» (`02` §6.1). E o §5.2 poe isso na validacao de
arranque: «nenhuma tool tem parametro `tenant_id`/`merchant_id` no esquema
visivel ao modelo».

Este *hook* recebe o `ToolContext` e **nunca** o dicionario `args` da tool. Nao
e uma convencao: e a assinatura. Um argumento produzido pelo modelo nao tem por
onde chegar aqui, e o teste `test_o_hook_nao_le_args_nenhuns` le a fonte deste
ficheiro para o confirmar.

## O codigo de erro e o do §6.5, e nao o do criterio 2

A ToolLayer tem vocabulario proprio, escrito em documento tecnico:
`ENTITLEMENT_DENIED` e `LIMIT_EXCEEDED` (`02` §6.5). O criterio 2 do bloco do
KAM-009 escreve `ENTITLEMENT_DISABLED`, que nao esta em documento nenhum e que
o proprio criterio marca «em proposta». Aqui usa-se o do documento; no HTTP
usa-se o do criterio. **A decisao de unificar os dois devolve-se ao dono do
`02` §6.5** — ver a nota em `entitlements.py`.

O tratamento no grafo tambem vem do §6.5, e as duas linhas sao diferentes:
`LIMIT_EXCEEDED` da «mensagem honesta + oferta de handoff», e
`ENTITLEMENT_DENIED` da «bloqueio, alerta de seguranca, `safe_reply`; **nunca**
tentar de novo». Quem decide isso e o grafo; este modulo so diz qual e.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .entitlements import (
    CODIGO_ENTITLEMENT_TOOL,
    CODIGO_LIMITE,
    CacheDeEntitlements,
    ChaveDeIdempotenciaInvalida,
    ClienteSql,
    Metricas,
    check_entitlement,
    consume_limit,
)


class ContextoDeTool(Protocol):
    """O minimo do `ToolContext` de `02` §6.1: de quem e este turno.

    **So o `tenant_id`.** O resto do `ToolContext` — `contact_id`, `turn_id`,
    `run_id` — nao entra aqui porque nada disto depende dele, e um protocolo
    que pedisse campos que nao usa obrigava quem chama a inventa-los nos
    testes.
    """

    tenant_id: object


@dataclass(frozen=True)
class ErroDeTool:
    """Um erro tipado do §6.5, pronto a entrar no `ToolResult.error`."""

    #: `ENTITLEMENT_DENIED` ou `LIMIT_EXCEEDED`.
    codigo: str
    #: O modulo (vertical) que foi recusado.
    modulo: str
    #: A chave de limite, quando a recusa foi de limite.
    chave: str | None = None
    #: O tecto efectivo, quando havia um.
    limite: int | None = None


def hook_de_tool(
    bd: ClienteSql,
    contexto: ContextoDeTool,
    *,
    modulo: str,
    chave: str | None = None,
    quantidade: int = 1,
    idempotency_key: str | None = None,
    limite: int | None = None,
    agora: object | None = None,
    cache: CacheDeEntitlements | None = None,
    metricas: Metricas | None = None,
) -> ErroDeTool | None:
    """Verifica o entitlement e, se houver chave, consome o limite.

    Pela ordem, e a ordem importa: uma tool de um modulo que o tenant nao tem
    e recusada **sem** consumir nada. Consumir primeiro gastava o tecto de quem
    nem sequer podia entrar.

    Devolve `None` quando a tool pode correr.

    Nao inventa um terceiro codigo: uma chamada que precise de consumir e nao
    traga chave de idempotencia e um defeito de quem chama — o `02` §6.3 diz
    como a derivar, `sha256(tenant_id | contact_id | tool | cart_id)` — e
    levanta `ChaveDeIdempotenciaInvalida` em vez de virar um erro de negocio.
    """
    tenant = contexto.tenant_id

    entitlement = check_entitlement(
        bd, tenant, modulo, cache=cache, metricas=metricas
    )
    if not entitlement.permitido:
        return ErroDeTool(codigo=CODIGO_ENTITLEMENT_TOOL, modulo=modulo)

    if chave is None:
        return None
    if not isinstance(idempotency_key, str) or idempotency_key.strip() == "":
        raise ChaveDeIdempotenciaInvalida(
            "uma tool que consome limite precisa de chave de idempotencia "
            "(`docs/tecnica/02` §6.3). A mensagem nao repete o valor."
        )

    consumo = consume_limit(
        bd,
        tenant,
        chave,
        quantidade,
        idempotency_key,
        limite=limite,
        agora=agora,
        modulo=modulo,
        metricas=metricas,
    )
    if consumo.aceite:
        return None
    # Sem tecto nenhum declarado para a chave nao e «excedeu»: e «nao tem». A
    # `0007` devolve `limite = NULL` nesse caso e o criterio 2 manda negar como
    # entitlement — e o §6.5 diz que a `ENTITLEMENT_DENIED` o grafo **nunca**
    # tenta de novo, que e o tratamento certo para um entitlement em falta.
    if consumo.motivo == "sem_entitlement":
        return ErroDeTool(codigo=CODIGO_ENTITLEMENT_TOOL, modulo=modulo, chave=chave)
    return ErroDeTool(
        codigo=CODIGO_LIMITE, modulo=modulo, chave=chave, limite=consumo.limite
    )
