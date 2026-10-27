"""As portas do *handoff* e a excepcao que o grafo apanha (KAM-034).

Sem dependencias para dentro do AGR: e o que permite ao
`verticais/vendedor/nos.py` importar daqui sem o caminho inverso existir. Um
modulo de portas que importe o que implementa as portas e um ciclo a espera de
quem acrescentar a segunda vertical.

## Porque e que a `HandoffIndisponivel` passou a viver aqui

O KAM-031 definiu-a em `verticais/vendedor/nos.py`, que e onde ela era usada —
e estava certo enquanto o unico codigo que a levantava fosse o que a apanhava.
Deixou de ser: quem a levanta e o `ServicoDeHandoff`, que e **partilhado** pelas
duas verticais (§5.4, a «regra de dois»), e a identidade da classe importa — um
`except HandoffIndisponivel` no no so apanha a excepcao se for a **mesma**
classe, e nao uma com o mesmo nome.

As duas alternativas eram piores. Importar o `nos.py` do Vendedor para dentro do
servico arrastava o grafo inteiro — o LangGraph, o validador, a ToolLayer — para
o caminho de `/internal/resume`, que nao tem grafo nenhum pela frente; e deixar
cada vertical com a sua classe dava duas excepcoes com o mesmo nome e um
`except` que cala uma delas, que e a classe de defeito que nao da erro.

O nome continua importavel de `verticais.vendedor.nos` — e o **mesmo objecto**,
reexportado la —, pelo que nada do que o KAM-031 escreveu muda de forma. O
`Protocol` `PortaDeHandoff` ficou onde estava, porque uma implementacao nao
precisa de o importar para o satisfazer: a tipagem e estrutural.
"""

from __future__ import annotations

from typing import Any, Protocol


class HandoffIndisponivel(RuntimeError):
    """O `HandoffUnavailable` do §11: o HND nao aceitou abrir o *handoff*.

    O que o grafo faz com ela esta na linha 37 da tabela de arestas do KAM-031:
    estado `degraded`, mensagem de degradacao, e o turno acaba no `send`.
    """


class PortaDoProvedor(Protocol):
    """O `openHandoff` do `HandoffProvider` (`docs/tecnica/01` §11.1).

    **Uma operacao e nao seis.** A porta do §11.1 tem `ensureAccount`,
    `mirrorMessage`, `openHandoff`, `setBotMuted`, `onHumanEvent` e `close`, e o
    AGR chama **uma**: o `openHandoff`, que o §11.1 descreve como «a unica
    operacao com efeito externo antes do `interrupt()`». As outras cinco correm
    no HND, do lado dele — o espelho e dos *webhooks* da Meta, o `close` e do
    *callback* do Chatwoot, e o `setBotMuted` nem e executavel (§3.15). Declarar
    aqui as seis era uma porta de que cinco metodos nunca teriam chamador.

    Levanta `HandoffIndisponivel` quando o provedor nao aceitou. **Idempotente
    por `handoff_id`**: e a propriedade que o `SQL_ABRIR_HANDOFF` do HND compra
    com um `ON CONFLICT (handoff_id) DO NOTHING`, e e ela que torna o criterio 1
    deste ticket possivel — o no repete e a passagem e a mesma.
    """

    def abrir(
        self,
        *,
        handoff_id: str,
        tenant_id: str,
        contact_id: str,
        conversation_id: str,
        motivo: str,
        resumo: str,
    ) -> str: ...


class PortaDeModos(Protocol):
    """Pausar uma conversa. O `conversation.mode = pausada` do criterio 6.

    **E uma porta e nao uma consulta deste servico, e a decisao e escrita.** A
    maquina de modos e do KAM-018: a transicao corre pelo `SQL_MUDAR_MODO`
    (com `FOR UPDATE` e a monotonia no predicado) e emite
    `conversation.mode_changed` pelo `SQL_EMITIR_MODE_CHANGED` **na mesma
    transaccao** — «o evento e a mudanca de modo confirmam juntos ou nao
    confirmam nenhum». Reescrever esse par em Python dava um segundo dono para
    uma transicao e, pior, a possibilidade de um modo mudar **sem evento**:
    nenhum consumidor a jusante (o painel, KAM-091) saberia que a conversa ficou
    `pausada`.

    O privilegio existe — a revisao `0016` concedeu `UPDATE (mode)` a
    `kamba_app` — pelo que isto nao e uma limitacao da base. E uma escolha de
    quem e o dono, e o credor da ligacao em producao e o **KAM-018**, do lado do
    CHR. Ate la a porta e a decisao, com o ensaio a medir que ela e chamada com
    a conversa certa, pelo mesmo desenho com que o KAM-025 deixou o
    `reencaminhar` e o KAM-027 o `grafos`.

    **E sincrona porque o `PortaDeHandoff.abrir` do KAM-031 e sincrono**, e e de
    dentro dele que isto e chamado. A consequencia esta escrita no
    `servico.py`: uma implementacao que faca E/S de rede nesta chamada prende a
    *event loop* do *worker*, que e uma restricao que o `abrir` ja tem e que
    este ticket nao resolve nem agrava.
    """

    def pausar(self, *, tenant_id: str, conversation_id: str, motivo: str) -> None: ...


class PortaDeGrafos(Protocol):
    """Resolve o grafo de um *thread* para lhe entregar o `Command(resume=...)`.

    Recebe o `thread_id` e nao a invocacao, porque a retoma **nao tem
    invocacao**: o que chega a `/internal/resume` sao tres campos e nenhum e o
    `agent_invocation` do §3.13. A vertical de um *thread* que esta a espera de
    um humano e a do grafo que o interrompeu, e quem a sabe e o *checkpoint* —
    nao quem retoma.
    """

    def __call__(self, thread_id: str) -> Any: ...
