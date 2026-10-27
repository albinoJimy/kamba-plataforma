"""A maquina de estados de uma passagem a humano (KAM-034, criterio 8).

Funcoes puras e vocabulario, sem base de dados e sem grafo. Vive separado do
`servico.py` pela razao do `encaminhadores.py` do KAM-031: o que se consegue
decidir sobre o estado sem falar com ninguem decide-se num sitio onde um teste
nao precisa de montar nada.

## Dois vocabularios e nao um, e e por isso que este modulo existe

O `docs/tecnica/01` §11.1 da ao `close` do provedor tres **desfechos**
(`resolved`, `timeout`, `cancelled`) e a `platform.handoffs` cinco **estados**
(`waiting`, `resumed`, `timeout`, `cancelled`, `degraded`). Os dois conjuntos
tocam-se mas nao coincidem, e o dicionario §3.15 ja escreveu porque:
«`resolved` -> `status = resumed`, `timeout` -> `timeout`, `cancelled` ->
`cancelled`. O `waiting` e o `degraded` nao sao desfechos (sao estados de
abertura) e o `resumed` nao e desfecho de `close`».

O corpo de `/internal/resume` leva o **desfecho** (`{thread_id, handoff_id,
outcome}`, §11 regra 3) e a tabela guarda o **estado**. `ESTADO_DO_DESFECHO` e
essa correspondencia, e esta aqui para que exista **uma** copia dela: a
primeira versao traduzia no corpo da rota e o `handoff_close` do grafo
comparava `outcome == "timeout"` contra o valor cru — duas leituras do mesmo
par, uma em cada lado, e o dia em que uma crescesse a outra calava-se.

**O desfecho atravessa o `interrupt()` sem traducao.** O que o
`Command(resume=...)` entrega ao `handoff_wait` e o `outcome` do pedido, e nao
o estado: o `handoff_close` do KAM-031 le `handoff["outcome"] == "timeout"`
para mandar a mensagem de alternativas, e traduzir antes de entrar fazia-o
comparar `timeout` com `timeout` por acidente — e `resolved` com `resumed`, que
nao bate. O estado e para a tabela; o desfecho e para o grafo.
"""

from __future__ import annotations

from typing import Final

#: Os cinco estados de `platform.handoffs.status` (dicionario §3.15, e o `CHECK`
#: da revisao `0011`). Lista **fechada**, e e ela que o `CHECK` da base impõe de
#: qualquer maneira: um valor fora disto e `23514` e nao um estado novo.
ESTADOS: Final = ("waiting", "resumed", "timeout", "cancelled", "degraded")

#: O estado em que uma passagem nasce. E a omissao da coluna na `0011`.
ESTADO_INICIAL: Final = "waiting"

#: Os tres desfechos de um `close` (`docs/tecnica/01` §11.1). Lista **fechada**:
#: e o que `/internal/resume` aceita no campo `outcome`, e um quarto valor e um
#: corpo que nao conhecemos — recusa-se com 400, nao se ignora.
DESFECHOS: Final = ("resolved", "timeout", "cancelled")

#: O desfecho com que a varredura dos prazos retoma (criterio 7).
DESFECHO_DO_PRAZO: Final = "timeout"

#: Desfecho -> estado. A correspondencia do dicionario §3.15, numa copia so.
#:
#: **O `resolved` nao se chama `resumed` e isso nao e arrumacao.** O provedor
#: diz «esta conversa foi resolvida» e a nossa tabela diz «esta passagem foi
#: retomada»: sao duas afirmacoes sobre coisas diferentes — a conversa dele e o
#: *thread* nosso — e o dia em que uma resolucao no Chatwoot deixar de retomar o
#: grafo (o modo concierge do KAM-114 e um candidato) os dois nomes separam-se
#: sem que ninguem tenha de renomear uma coluna.
ESTADO_DO_DESFECHO: Final = {
    "resolved": "resumed",
    "timeout": "timeout",
    "cancelled": "cancelled",
}

#: De que estados se pode sair por uma retoma. **Um, e e o ponto do criterio 3.**
#:
#: Nao e uma lista por generosidade futura: o *compare-and-set* do §11 regra 3 e
#: `waiting -> resumed`, e um segundo estado de partida fazia um `resolved`
#: duplicado encontrar a passagem em `resumed` e **vencer outra vez** — que e
#: exactamente o que o `no-op` existe para impedir. O `degraded` tambem nao
#: entra: uma passagem que nunca chegou ao provedor nao tem resposta humana para
#: retomar, e quem a recupera e o `SQL_MARCAR_ABERTA` do HND, que a devolve a
#: `waiting` quando a fila dele drenar.
ESTADOS_RETOMAVEIS: Final = ("waiting",)


class DesfechoInvalidoError(ValueError):
    """O `outcome` do pedido nao e um dos tres do §11.1.

    Levanta em vez de cair num estado por omissao. Um `outcome` desconhecido
    tratado como `resolved` era um desfecho inventado a fechar uma passagem, e
    tratado como `timeout` era a mensagem de alternativas enviada por um
    *webhook* que ninguem percebeu.
    """


def estado_do_desfecho(desfecho: str) -> str:
    """O `handoffs.status` que um desfecho de `close` escreve.

    Valida por **pertenca ao dicionario** e nao por `in DESFECHOS` seguido de um
    `[]`: sao a mesma pergunta feita duas vezes, e as duas listas podiam
    divergir. Ha um ensaio que confronta as chaves de `ESTADO_DO_DESFECHO` com
    `DESFECHOS` e os valores com `ESTADOS`, nos dois sentidos.
    """
    try:
        return ESTADO_DO_DESFECHO[desfecho]
    except KeyError:
        raise DesfechoInvalidoError(f"desfecho_invalido: {desfecho!r}") from None


def pode_retomar(status: str) -> bool:
    """`True` se uma passagem neste estado ainda pode ser retomada.

    Nao substitui o predicado do CAS — quem decide e a base, porque so ela
    serializa dois *webhooks* que chegam a dois processos. Serve para
    **classificar** o zero linhas: uma passagem em `resumed` e um duplicado
    (200 sem efeito) e nao uma recusa.
    """
    return status in ESTADOS_RETOMAVEIS
