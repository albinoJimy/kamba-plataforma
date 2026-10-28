"""A politica `concierge` por *tenant* (KAM-114).

## Porque e que a politica e uma linha de `entitlements` e nao superficie nova

O concierge **nao** e um quinto modo de conversa: o KAM-018 recusa transicoes
fora da tabela de `docs/tecnica/01` §10.2 e os quatro modos ficam como estao. E
uma politica por *tenant* aplicada a conversa em modo `bot`, e a casa dela e uma
linha de `platform.entitlements` com `modulo = 'concierge'`:

* a coluna `modulo` tem `CHECK` de **forma** (`^[a-z][a-z0-9_]*$`) e nao de
  dominio desde a `0001`, e o dicionario §3.7 escreve por extenso que «um modulo
  novo entra por **configuracao** e nao por migracao» (ADR-012). Nao ha migracao
  para a politica — so para a `draft_decisions`;
* o leitor e o `check_entitlement` do KAM-009, que **falha fechado**, tem a RLS
  por baixo e entra sozinho no X-03;
* escreve-se na base, pelo que **desactivar nao precisa de reiniciar o AGR** —
  que e o criterio 8.

**As outras tres superficies foram medidas e nenhuma serve.** O
`registry/*.yaml` le-se uma vez no arranque e nao se recarrega (nao ha *watcher*,
nao ha TTL), pelo que uma politica em YAML falhava o criterio 8 por construcao; o
`entitlements.limites` tem `additionalProperties: false` no
`registry/entitlement_keys.schema.json` e as suas dez chaves sao todas
`bigint_nao_negativo`, pelo que um `concierge: true` ali e **recusado na
escrita**; e uma tabela ou coluna de politicas nova nao existe e era uma
superficie a mais para o que uma linha ja diz.

## As duas direccoes de falha, e as duas sao seguras

Isto e um controlo de seguranca, pelo que a direccao da falha nao e detalhe:

* **sem linha, linha inactiva, ou *tenant* em `onboarding`/`suspenso`/
  `encerrado`** -> `permitido = False` -> politica **desligada** -> envio
  automatico. E a resposta certa, e e a da vasta maioria dos *tenants*: quem nao
  esta no Piloto concierge nao tem a linha;
* **erro de leitura** (a base em baixo, a tomada caida) -> a excepcao **sobe** e
  o turno falha -> **nao sai mensagem nenhuma**. Tambem seguro, pelo outro lado:
  a barreira do criterio 1 e «sem decisao humana nao sai mensagem», e um turno
  que falha nao envia nada.

**Nao se apanha a excepcao para devolver `False`**, e e a decisao que importa
nesta classe: devolver «politica desligada» quando nao se conseguiu ler a
politica punha o bot a falar sozinho na conversa de um *tenant* que pediu
aprovacao humana — exactamente o que o concierge existe para impedir. Um
`except` aqui era *fail-open* com cara de robustez.

## Sem *cache*, e isso e escolha

O `check_entitlement` aceita uma `CacheDeEntitlements` com TTL de 60 s, e **nao
se passa**: a politica le-se da base em cada turno, como o
`LeitorDeEntitlements` do KAM-038 ja faz para as subscricoes. O que se compra e
que desactivar tem efeito **no turno seguinte** em vez de «ate 60 s depois», o
que torna o criterio 8 uma propriedade e nao um prazo. O que se paga e uma
leitura por chave primaria por turno.

Se o Piloto medir isto como caminho quente, a *cache* existe e o limite fica
escrito: 60 s (`TTL_POR_OMISSAO_MS`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, Protocol

#: O `modulo` da linha de `platform.entitlements`. Dicionario §3.34.
MODULO: Final = "concierge"


class _Entitlement(Protocol):
    """A fatia do `kamba_core.ten.Entitlement` de que a politica depende.

    So o `permitido`, como o `_Entitlement` do `eventos/consumo.py`: um
    `Protocol` estreito e o que permite ao ensaio passar um duplo sem construir
    o `dataclass` inteiro do KAM-009.
    """

    @property
    def permitido(self) -> bool: ...


class PoliticaDeConcierge:
    """`tenant_id -> a politica esta activa?`

    Recebe o leitor por injeccao e nao abre ligacoes: quem as abre e o
    `LeitorDeEntitlements` do KAM-038, que ja corre em `tenant_guard.tx` com o
    *tenant* de quem chama — pelo que um turno forjado le a politica do *tenant*
    que declarou e nao a de outro.
    """

    __slots__ = ("_ler",)

    def __init__(self, ler_entitlement: Callable[[str, str], _Entitlement]) -> None:
        self._ler = ler_entitlement

    def activa(self, tenant_id: str) -> bool:
        """`True` quando este *tenant* esta no modo concierge.

        Nao apanha excepcoes — ver a nota do modulo.
        """
        return bool(self._ler(tenant_id, MODULO).permitido)


#: A politica que **nunca** esta activa. E a omissao do grafo quando ninguem
#: liga um leitor, e nao e *fail-open* disfarcado: sem leitor nao ha *tenant*
#: nenhum no Piloto concierge, e o comportamento e o que o KAM-031 ja entregou.
#:
#: E uma classe e nao um `lambda` para o ensaio poder afirmar a identidade.
class SemPolitica:
    """A politica desligada, para quando o AGR corre sem leitor."""

    __slots__ = ()

    def activa(self, tenant_id: str) -> bool:  # noqa: ARG002 — assinatura da porta
        return False


__all__ = ["MODULO", "PoliticaDeConcierge", "SemPolitica"]
