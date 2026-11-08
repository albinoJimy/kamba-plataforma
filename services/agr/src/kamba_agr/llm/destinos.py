"""O *gate* de destino: nada sai de Angola sem autorizacao (ADR-008, KAM-030).

**Este modulo nasceu com a porta por implementar, e o KAM-069 implementou-a.**
O que aqui fica e o contrato — a `PortaDeDestinos` que o `cliente.py` consulta
antes de cada chamada — e **duas** portas que o satisfazem:

    NegaTudoAteKam069   a porta de um processo **sem ligacao a base**. Nega tudo
                        em `prod`. Nao desapareceu com o KAM-069, e isso e
                        decisao: um processo que nao consegue abrir ligacao nao
                        passa a autorizar, passa a negar.
    PortaDoNucleo       a porta real: a `PortaSobreDestinos` do
                        `kamba_core.destinos` sobre `platform.tenant_destinations`
                        (revisao `0036`), com a *cache* de 60 s do criterio 3 do
                        KAM-069.

O que o `arrancar` devolve depende de haver ou nao quem abra ligacao, e nada no
`cliente.py` muda com a troca — que e o que a versao anterior deste ficheiro
prometeu por escrito («troca-se o que o arranque constroi»).

## Porque e que a traducao de erro existe, e nao se dispensa

A `PortaSobreDestinos` levanta `TransferenciaNegada`, que **nao** e um
`ErroDeLlm`. O `cliente.py` apanha `ErroDeLlm` e so: uma `TransferenciaNegada` a
subir por ali escapava ao `except`, nao contava a metrica
`agr_llm_destino_negado_total`, nao gravava a linha `destino_negado` em
`dat.llm_call_log` e nao degradava — o turno rebentava. Nada sairia de Angola,
pelo que a propriedade de seguranca mantinha-se; o que se perdia era tudo o que
o criterio 5 do KAM-030 fecha.

O `PortaDoNucleo` traduz, e e a unica coisa que faz. O dicionario §3.49 escreve
porque sao dois erros e nao um: o `DestinoNegado` e o contrato entre o grafo e o
**modelo**, e a `TransferenciaNegada` e a recusa de uma porta que nao sabe que
existe um modelo do outro lado.

## As tres finalidades deste servico, e as treze da coluna

A coluna `tenant_destinations.purpose` tem **treze** valores (dicionario §3.49),
porque o *gate* corre em sete pontos e so um e o *gateway* de modelos. Deste
lado interessam **tres**, e os literais vem do nucleo: duas copias das mesmas
cadeias divergiam no dia em que uma delas mudasse, e foi para evitar isso que o
dominio saiu daqui para a revisao que cria a coluna.
"""

from __future__ import annotations

from typing import Any, Final, Protocol, runtime_checkable

from kamba_core.destinos import (
    FINALIDADE_CONVERSA,
    FINALIDADE_EMBEDDINGS,
    FINALIDADE_VISAO,
    CacheDeDestinos,
    PortaSobreDestinos,
    TransferenciaNegada,
)
from kamba_core.destinos import dbapi as destinos_dbapi

from .erros import DestinoNegado

#: Os ambientes, como em `kamba_core.secrets.port`.
AMBIENTE_PROD: Final = "prod"
AMBIENTE_STAGING: Final = "staging"
AMBIENTE_DEV: Final = "dev"

#: As finalidades que **este servico** usa: tres das treze de
#: `tenant_destinations.purpose` (revisao `0036`, dicionario §3.49).
#:
#: Os literais vem de `kamba_core.destinos` e nao se reescrevem aqui — ver a
#: nota do modulo. Lista **fechada** deste lado: uma finalidade nova no AGR e um
#: papel novo em `llm/aliases.yaml`, e uma finalidade nova na coluna e uma
#: revisao de base de dados.
FINALIDADES: Final = (FINALIDADE_CONVERSA, FINALIDADE_EMBEDDINGS, FINALIDADE_VISAO)

#: Papel -> finalidade. O `router` e o `chat` tratam conteudo de conversa; o
#: `embed` indexa catalogo e o `vision` le fotos de produto. Sao finalidades
#: diferentes porque o inventario as separa, e porque um dia uma pode estar
#: autorizada e a outra nao.
FINALIDADE_DO_PAPEL: Final = {
    "router": FINALIDADE_CONVERSA,
    "chat": FINALIDADE_CONVERSA,
    "vision": FINALIDADE_VISAO,
    "embed": FINALIDADE_EMBEDDINGS,
}


@runtime_checkable
class PortaDeDestinos(Protocol):
    """O `assertDestinationAllowed` do KAM-069, com nomes deste repositorio."""

    #: Para a mensagem de arranque e para o registo. Nunca um segredo.
    nome: str

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        """Nao devolve nada; **levanta** `DestinoNegado` se nao autorizar."""
        ...


class NegaTudoAteKam069:
    """A porta por omissao: nega **tudo** em `prod` (ADR-008).

    Fora de `prod` autoriza, e isso nao e uma excepcao a regra — e a regra: o
    ADR-008 fala de «dados pessoais **de producao**», e o criterio 8 diz «so
    dados sinteticos em `staging`». O que esta classe **nao** consegue fazer e
    verificar que os dados sao sinteticos: isso e operacional, nao se le de um
    pedido, e por isso o arranque **avisa** em `staging` em vez de ficar calado.
    Um aviso por arranque e barato; a alternativa era um silencio que se lia como
    garantia.
    """

    nome = "nega-tudo-ate-kam069"

    def __init__(self, ambiente: str) -> None:
        self.ambiente = ambiente

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        if finalidade not in FINALIDADES:
            # Falha fechada tambem aqui: uma finalidade que o inventario nao
            # conhece nao se pode autorizar, porque nao ha linha onde ela caiba.
            raise DestinoNegado(
                f"finalidade `{finalidade}` fora de {FINALIDADES}: nao ha linha de "
                "`tenant_destinations` onde ela caiba (KAM-069)"
            )
        if self.ambiente != AMBIENTE_PROD:
            return
        raise DestinoNegado(
            f"transferencia para `{fornecedor}` recusada em `{AMBIENTE_PROD}`: a "
            "tabela `tenant_destinations` nao existe e nenhum destino tem "
            "`apd_ref` (KAM-069, ADR-008). Nenhum dado pessoal de producao sai de "
            "Angola sem notificacao ou autorizacao da APD"
        )


class PortaDoNucleo:
    """A `PortaSobreDestinos` do nucleo, com o erro traduzido.

    **Faz uma coisa so.** Nao decide nada, nao cacheia nada, nao toca na base:
    delega e traduz. Toda a regra — a precedencia das linhas do tenant, a
    conjuncao sobre todas as aplicaveis, a falha fechada, o TTL de 60 s — vive em
    `kamba_core.destinos.porta`, que e onde ela se prova sem base nenhuma.

    A traducao e `TransferenciaNegada` -> `DestinoNegado`, e a nota do modulo diz
    porque nao se dispensa.
    """

    nome = "tenant-destinations"

    def __init__(self, porta: PortaSobreDestinos) -> None:
        self._porta = porta

    @property
    def cache(self) -> CacheDeDestinos:
        """Para quem revoga e nao quer esperar pelo TTL (criterio 3)."""
        return self._porta.cache

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        try:
            self._porta.autorizar(tenant_id, fornecedor, finalidade)
        except TransferenciaNegada as erro:
            # **A mensagem passa inteira.** Ela nomeia o fornecedor, o pais e o
            # estado, e e isso que torna um `destino_negado` diagnosticavel: as
            # cinco maneiras de negar dao textos diferentes. Nenhuma leva o
            # `apd_ref` — a consulta nao o traz da base, so o booleano.
            raise DestinoNegado(str(erro)) from erro


def arrancar(
    ambiente: str, abrir_ligacao: Any | None = None
) -> PortaDeDestinos:
    """A porta deste processo. Um ambiente desconhecido **nega**, nao cai em dev.

    E a mesma escolha do `_ambiente` do `__main__.py`, e pela mesma razao que o
    `chaves.ts` do KAM-008 escreveu por extenso: um `KAMBA_ENV=producao` escrito
    por engano nao pode servir a politica de `dev`. Aqui o engano custa mais —
    custava uma transferencia — e por isso um valor desconhecido e tratado como
    `prod`.

    **Com `abrir_ligacao`, a porta e a real; sem ele, nega tudo em `prod`.** O
    argumento e opcional e nao obrigatorio por uma razao que se diz: os testes
    deste servico, e o `arrancar` de quem ainda nao tem base, continuam a
    receber uma porta valida em vez de um `None` que o `cliente.py` teria de
    verificar. E a ausencia de ligacao nao afrouxa nada — a porta que se recebe
    sem ela e a **mais** restritiva das duas.
    """
    conhecido = ambiente in (AMBIENTE_PROD, AMBIENTE_STAGING, AMBIENTE_DEV)
    efectivo = ambiente if conhecido else AMBIENTE_PROD
    if abrir_ligacao is None:
        return NegaTudoAteKam069(efectivo)
    return PortaDoNucleo(
        PortaSobreDestinos(destinos_dbapi.leitor(abrir_ligacao), CacheDeDestinos())
    )


def finalidade_de(papel: str) -> str:
    """A finalidade de um papel. Um papel desconhecido nao tem finalidade."""
    try:
        return FINALIDADE_DO_PAPEL[papel]
    except KeyError:
        raise DestinoNegado(
            f"o papel `{papel}` nao tem finalidade declarada em "
            "`FINALIDADE_DO_PAPEL`: sem finalidade nao ha linha de "
            "`tenant_destinations` a consultar (KAM-069)"
        ) from None
