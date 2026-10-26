"""O *gate* de destino: nada sai de Angola sem autorizacao (ADR-008, KAM-030).

**Esta e a decisao que este ticket teve de tomar, e esta tomada em voz alta.**

O DoR do KAM-030 nomeia o **KAM-069** — «Inventario de subprocessadores e gate de
transferencia com `apd_ref`» — como dependencia, e o KAM-069 **nao esta
entregue**: nao existe a tabela `tenant_destinations`, nao existe
`assertDestinationAllowed`, e nao existe linha nenhuma com `apd_ref`. Medido
antes de se escrever codigo: zero caixas marcadas no bloco dele, e nenhum
ficheiro de inventario ou de *gate* no repositorio.

As duas leituras defensaveis eram entregar o *gateway* com o destino a falhar
**fechado** e o KAM-069 nomeado como credor, ou parar e devolver a decisao. **Fica
a primeira**, e a razao tem tres partes:

1. **E o que o proprio criterio 8 manda.** Ele escreve, por extenso, «ate
   KAM-069 existir, so dados sinteticos em `staging`» — quem redigiu o critero
   previu esta situacao e disse o que fazer nela. Parar seria recusar uma
   instrucao escrita.
2. **E o padrao desta linha de tickets.** O KAM-028 deixou o passo 5 do pipeline
   vazio para o KAM-029; o KAM-029 deixou o `stage` do `confirm_gate` para o
   KAM-031. Uma costura nomeada, com o credor escrito, e como este epic avanca.
3. **Falhar fechado em `prod` nao e um compromisso: e mais restritivo do que o
   KAM-069 sera.** Com o KAM-069 feito, um destino `autorizado` com `apd_ref`
   passa; aqui, em `prod`, **nao passa nenhum**. Nao ha janela para fechar
   depois — ha uma porta que so o KAM-069 pode abrir.

**O que isto custa, dito sem rodeios:** o `/internal/turn` com `KAMBA_ENV=prod`
nao consegue chamar um modelo. O AGR em producao continua sem responder — mas ja
nao estava a responder (o `ExecutorDeTurnos` recebe `sem_grafos` e os grafos sao
o KAM-031 e o KAM-035). O que este ticket entrega e o caminho inteiro provado em
`staging` com dados sinteticos, e a porta de `prod` fechada por desenho em vez de
aberta por omissao.

**E por isso a caixa do criterio 8 fica `parcial` e nenhuma caixa que dependa do
que o KAM-069 entrega vai marcada** — nem o critero 8 por inteiro, nem a linha de
privacidade do DoD que pede «nenhum dado pessoal sai de Angola fora de destino
registado com `apd_ref`»: o `apd_ref` nao existe para se registar.

## A interface e a que o KAM-069 vai implementar, nao uma nossa

A `PortaDeDestinos` tem a assinatura que o bloco do KAM-069 anuncia —
`assertDestinationAllowed(tenant, provider, purpose)` — com os nomes em
portugues do resto do codigo. Quando o KAM-069 chegar, implementa a porta sobre
`tenant_destinations` e **nada neste modulo muda**: troca-se o que o arranque
constroi. A *cache* com TTL de 60 s que o criterio 3 do KAM-069 pede e **dele** e
nao daqui — esta implementacao nao tem o que *cachear*.
"""

from __future__ import annotations

from typing import Final, Protocol, runtime_checkable

from .erros import DestinoNegado

#: Os ambientes, como em `kamba_core.secrets.port`.
AMBIENTE_PROD: Final = "prod"
AMBIENTE_STAGING: Final = "staging"
AMBIENTE_DEV: Final = "dev"

#: A finalidade de uma chamada, no vocabulario do `docs/tecnica/08` §8.3.1 (a
#: coluna `purpose` de `tenant_destinations`). Lista **fechada**: uma finalidade
#: nova e uma linha nova no inventario de subprocessadores, nao uma constante.
FINALIDADE_CONVERSA: Final = "conversa"
FINALIDADE_EMBEDDINGS: Final = "embeddings"
FINALIDADE_VISAO: Final = "visao"
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


def arrancar(ambiente: str) -> PortaDeDestinos:
    """A porta deste processo. Um ambiente desconhecido **nega**, nao cai em dev.

    E a mesma escolha do `_ambiente` do `__main__.py`, e pela mesma razao que o
    `chaves.ts` do KAM-008 escreveu por extenso: um `KAMBA_ENV=producao` escrito
    por engano nao pode servir a politica de `dev`. Aqui o engano custa mais —
    custava uma transferencia — e por isso um valor desconhecido e tratado como
    `prod`.
    """
    conhecido = ambiente in (AMBIENTE_PROD, AMBIENTE_STAGING, AMBIENTE_DEV)
    return NegaTudoAteKam069(ambiente if conhecido else AMBIENTE_PROD)


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
