"""Correr um turno: a secção critica do AGR (KAM-025 criterios 2, 4 e 6).

E o `handle(job)` do esqueleto de codigo do bloco do ticket, com o que ele
deixa implicito escrito por extenso:

    admissao (ritmo, vaga do tenant)        <- admissao.py, antes da tranca
    fila por `thread_id`, coalescencia      <- aqui
    async with trancas.tomar(thread_id):    <- trancas.py
        palavra = ler_palavra(...)          <- consultas.py, contra a base
        se o humano tem a palavra: HND      <- criterio 6
        senao: grafo.ainvoke(estado_inicial) <- KAM-027/KAM-031

## Este modulo nao conhece grafo nenhum

O `grafos` e uma porta: uma funcao que recebe a invocacao e devolve algo com
`ainvoke(estado, config)`. O AgentRegistry e o KAM-027 e o grafo do Vendedor e
o KAM-031; o que aqui esta e o sitio onde eles encaixam, e o «grafo de teste»
que o criterio 2 nomeia e exactamente isso — uma porta com um duplo.

Mesma regra para o `hnd` (reencaminhar) e para o `outbound` (enviar com chave
de idempotencia): portas. O Outbound real e o KAM-015 e o HND e o KAM-019; o
«(fake)» do criterio 4 esta no enunciado do proprio criterio.

## A fila e por conversa; a tranca e por `thread_id`. Sao chaves diferentes.

E a correccao mais importante que a revisao adversarial trouxe, e vale a pena
ver porque e que as duas chaves tem de ser diferentes.

O `thread_id` e `{tenant_id}:{contact_id}` — e **por contacto**, porque e o
`thread_id` do LangGraph (`docs/tecnica/02` §12). Mas a `conversations` e
`UNIQUE (tenant_id, contact_id, channel_id)` (revisao `0009`): o **mesmo
contacto em dois canais do mesmo tenant tem duas conversas e um so
`thread_id`**.

A primeira versao indexava a fila por `thread_id` e corria o lote com a
**primeira** invocacao: `ler_palavra(primeira)` e `estado_inicial(primeira)`.
Com duas mensagens de conversas diferentes do mesmo contacto a distarem menos de
1,5 s, elas coalesciam e a decisao da conversa A valia para a B — se a B
estivesse com um *handoff* em `waiting`, o turno entrava no grafo sobre ela
(invariante do §11 regra 4 violada, criterio 6), e a mensagem da B **perdia-se**,
porque o *shim* via 200 e completava o *job*.

Hoje a fila e indexada por `(thread_id, conversation_id)`: um lote nunca
atravessa conversas. **A tranca continua a ser por `thread_id`**, e isso e
deliberado: ela tem de travar os dois canais do mesmo contacto, senao dois turnos
corriam sobre o **mesmo** *thread* do LangGraph. Logo as duas conversas de um
contacto serializam entre si — pela tranca — e nunca se misturam num lote — pela
fila.

## A ordem de chegada, e ate onde ela e garantida

Dentro deste processo e garantida por **esta** fila, e nao pela tranca: o
`pg_try_advisory_lock` nao promete nada sobre a ordem em que os que esperam o
conseguem, e vinte corrotinas a tenta-lo davam vinte turnos em serie **em ordem
arbitraria** — que cumpre «0 execucoes sobrepostas» e falha «ordem de chegada
preservada». Por isso ha um dreno por conversa, com uma lista FIFO, e a tranca e
tomada **uma vez por lote**, pelo dreno.

**Entre processos nao e garantida, e fica dito.** Duas replicas do AGR com
mensagens da mesma `thread_id` serializam (a tranca e da base) mas podem
inverter a ordem. Fechar isso pedia uma fila por chave com dono unico, que o
`ADR-L004` pesou e recusou pela razao la escrita. No Piloto o caminho normal e
um *job* por mensagem numa fila que entrega por ordem; a inversao exige duas
mensagens da mesma conversa em voo em dois processos, e o que a torna inofensiva
e o `turn_id` ser o `wamid` — cada turno sabe de que mensagem e.

## A repeticao e a chave, e e aqui que o criterio 4 vive

Um turno que levante — ou um processo que morra a meio — deixa o *job* na fila,
e o turno **repete-se desde o inicio**. Nada neste modulo tenta adivinhar onde
ia: o que o torna seguro e o `idempotency_key = turn_id:seq` de
`InvocacaoDoAgente.chave_de_envio`, que da a **mesma** chave na segunda volta.
O `seq` conta dentro do turno e comeca em 0 em cada volta, de proposito: um
contador que sobrevivesse a repeticao dava chaves novas e o Outbound mandava a
mensagem duas vezes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .admissao import Admissao, Pendente
from .contexto import MODO_DO_BOT, InvocacaoDoAgente
from .estado import estado_inicial
from .metricas import METRICA_DURACAO, METRICA_TURNOS, METRICAS


@dataclass(frozen=True, slots=True)
class Palavra:
    """Quem tem a palavra numa conversa. O que `SQL_PALAVRA_DA_CONVERSA` le."""

    modo: str
    handoff_a_espera: bool

    @property
    def do_humano(self) -> bool:
        """`True` se o turno **nao** entra no grafo. Criterio 6.

        Duas condicoes, e basta uma: o modo nao e `bot` (`dono`, `humano` ou
        `pausada`), ou ha um *handoff* em `waiting`. E a invariante do
        `docs/tecnica/02` §11 regra 4 — «nunca se invoca o grafo com *input*
        novo num thread com `interrupt` pendente».

        O modo testa-se por **igualdade a `bot`** e nao por desigualdade aos
        outros tres, pela razao do criterio 5 do KAM-014: lista de permitidos,
        nao de proibidos. Um modo novo no dominio fecha a porta por omissao, que
        e o lado seguro de errar.
        """
        return self.modo != MODO_DO_BOT or self.handoff_a_espera


class Grafo(Protocol):
    """O minimo de um grafo LangGraph de que o AGR depende."""

    async def ainvoke(self, estado: dict[str, Any], config: dict[str, Any]) -> Any: ...


class GrafoNaoRegistadoError(RuntimeError):
    """Nao ha grafo para esta vertical. O AgentRegistry e o KAM-027.

    E o estado em que este ticket deixa o servico de proposito: o Objectivo diz
    «sem ainda conter grafos de negocio». O que isto **nao** pode ser e um 200 a
    fingir que o turno correu, nem um 500 que ponha o BullMQ a repetir para
    sempre uma mensagem que nenhuma versao deste codigo consegue tratar: a API
    responde 503 com `Retry-After`, que e «o turno nao corre agora e a mensagem
    fica na fila» — a mesma linha que o `docs/tecnica/02` §14 escreve para o
    checkpointer indisponivel.

    **O AGR nao vai a producao antes do KAM-027 e do KAM-031.** Fica escrito
    aqui, em `docs/agr.md` e na secção de verificacao do bloco do ticket.
    """


def sem_grafos(_invocacao: InvocacaoDoAgente) -> Grafo:
    """A porta `grafos` por omissao: levanta. Substituida pelo KAM-027."""
    raise GrafoNaoRegistadoError("grafo_nao_registado")


@dataclass(frozen=True, slots=True)
class DesfechoDoTurno:
    """O que aconteceu. O `desfecho` e um dos `DESFECHOS` de `metricas.py`."""

    desfecho: str
    turn_id: str
    coalescidos: int = 0


class ExecutorDeTurnos:
    """A fila por `thread_id`, a tranca e o que corre dentro dela."""

    def __init__(
        self,
        trancas: Any,
        ler_palavra: Callable[[InvocacaoDoAgente], Awaitable[Palavra | None]],
        grafos: Callable[[InvocacaoDoAgente], Grafo],
        reencaminhar: Callable[[list[InvocacaoDoAgente]], Awaitable[None]],
        admissao: Admissao | None = None,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._trancas = trancas
        self._ler_palavra = ler_palavra
        self._grafos = grafos
        self._reencaminhar = reencaminhar
        self._admissao = admissao or Admissao()
        self._agora = relogio
        # A chave e `(thread_id, conversation_id)` e nao o `thread_id`: ver a
        # *docstring* do modulo. A da tranca continua a ser o `thread_id`.
        self._pendentes: dict[tuple[str, str], list[Pendente]] = {}
        self._drenos: dict[tuple[str, str], asyncio.Task] = {}

    async def correr(self, invocacao: InvocacaoDoAgente) -> DesfechoDoTurno:
        """Poe a invocacao na fila da sua `thread_id` e espera pelo desfecho.

        A vaga do *tenant* ja foi tomada por quem chama (`api_interna.py`), e
        nao aqui: uma recusa por tecto tem de chegar ao chamador **antes** de a
        mensagem entrar numa fila, senao o 503 que devolve o *job* a fila nunca
        acontece e as mil mensagens de um *tenant* ficam a ocupar memoria deste
        processo.
        """
        pendente = Pendente(invocacao=invocacao, chegou_em=self._agora())
        # O contador da fila abre **aqui** e nao no `_correr_lote`, e a diferenca
        # e o que o nome da metrica promete: `agr_queue_depth` e «turnos a
        # espera». Contado no `_correr_lote`, media os **lotes a correr** — com
        # um dreno por `thread_id` e o tecto do *tenant* a 3, nunca passava de
        # um numero pequeno, e o `AGR_LIMIAR_DE_CONTRAPRESSAO` de 100 era
        # inalcancavel por construcao. A metrica dizia uma coisa e media outra.
        chave = (invocacao.thread_id, invocacao.conversation_id)
        with self._admissao.na_fila():
            self._pendentes.setdefault(chave, []).append(pendente)
            self._arrancar_dreno(chave)
            return await pendente.espera

    def _arrancar_dreno(self, chave: tuple[str, str]) -> None:
        dreno = self._drenos.get(chave)
        if dreno is None or dreno.done():
            self._drenos[chave] = asyncio.create_task(self._drenar(chave))

    async def _drenar(self, chave: tuple[str, str]) -> None:
        """Corre lotes desta conversa ate a fila esvaziar.

        Um dreno por `(thread_id, conversation_id)`, e e ele que serializa dentro
        do processo **e** garante que um lote nunca atravessa conversas. A tranca
        da base serializa **entre** processos e **entre as conversas do mesmo
        contacto**; as duas sao precisas, e nenhuma substitui a outra.
        """
        thread_id = chave[0]
        try:
            while True:
                pendentes = self._pendentes.get(chave) or []
                if not pendentes:
                    break
                try:
                    lote, resto = self._admissao.coalescer(pendentes)
                    if resto:
                        self._pendentes[chave] = resto
                    else:
                        self._pendentes.pop(chave, None)
                except BaseException as erro:  # noqa: BLE001 — ver comentario
                    # Sem isto, uma excepcao **fora** do `_correr_lote` — na
                    # coalescencia, ou num contador de metrica a recusar — tinha
                    # dois modos de falha, os dois piores do que um erro: ou os
                    # pendentes ficavam em `_pendentes` e o `finally` abaixo
                    # ressuscitava o dreno, que rebentava outra vez, para sempre;
                    # ou saiam de `_pendentes` sem ninguem resolver os seus
                    # `Future`, e **todos os pedidos HTTP daquela conversa
                    # ficavam pendurados ate o `lockDuration` do shim expirar**.
                    # Falha-se o que estava na fila e larga-se.
                    self._pendentes.pop(chave, None)
                    self._falhar(pendentes, erro)
                    if isinstance(erro, asyncio.CancelledError):
                        raise
                    return
                await self._correr_lote(thread_id, lote)
        finally:
            self._drenos.pop(chave, None)
            # Entre o `while` ver a fila vazia e o dreno sair, uma invocacao
            # nova pode ter chegado e visto um dreno ainda vivo — e ficava sem
            # ninguem a drena-la, pendurada no `await` para sempre. Fechar a
            # janela aqui, depois de o dreno se ter retirado do registo, e o
            # que a impede. Apanhado a pensar na corrida, nao a correr: o teste
            # `test_chegada_na_fronteira_do_dreno` reproduz a intercalacao.
            if self._pendentes.get(chave):
                self._arrancar_dreno(chave)

    async def _correr_lote(self, thread_id: str, lote: list[Pendente]) -> None:
        comecou = self._agora()
        invocacoes = [pendente.invocacao for pendente in lote]
        primeira = invocacoes[0]
        # **Um lote e de uma conversa so.** A decisao e o estado saem da
        # `primeira`, pelo que um lote que atravessasse conversas aplicava a
        # decisao de uma a outra — e a segunda mensagem perdia-se, porque o
        # *shim* ve 200. A fila ja garante isto pela chave; afirma-se aqui
        # porque uma invariante que so vive no indice de um dicionario e uma
        # invariante que a proxima pessoa nao ve.
        assert all(
            invocacao.conversation_id == primeira.conversation_id
            and invocacao.thread_id == thread_id
            for invocacao in invocacoes
        ), "um lote atravessou conversas"
        try:
            async with self._trancas.tomar(thread_id):
                palavra = await self._ler_palavra(primeira)
                if palavra is None:
                    # Zero linhas **nao** e «esta em `bot`». A conversa nao
                    # existe, foi apagada, ou o contexto de RLS e de outro
                    # tenant; nas tres, o turno nao entra no grafo.
                    desfecho = "sem_conversa"
                elif palavra.do_humano:
                    await self._reencaminhar(invocacoes)
                    desfecho = "entregue_ao_hnd"
                else:
                    estado = estado_inicial(primeira)
                    grafo = self._grafos(primeira)
                    await grafo.ainvoke(
                        estado, {"configurable": {"thread_id": thread_id}}
                    )
                    desfecho = "executado"
        except BaseException as erro:  # noqa: BLE001 — repassado a quem chama
            METRICAS.contar(METRICA_TURNOS, "falhou")
            METRICAS.medir(METRICA_DURACAO, (self._agora() - comecou) * 1_000)
            self._falhar(lote, erro)
            if isinstance(erro, asyncio.CancelledError):
                raise
            return

        METRICAS.contar(METRICA_TURNOS, desfecho)
        METRICAS.medir(METRICA_DURACAO, (self._agora() - comecou) * 1_000)
        resultado = DesfechoDoTurno(
            desfecho=desfecho, turn_id=primeira.turn_id, coalescidos=len(lote) - 1
        )
        for pendente in lote:
            if not pendente.espera.done():
                pendente.espera.set_result(resultado)

    @staticmethod
    def _falhar(pendentes: list[Pendente], erro: BaseException) -> None:
        """Entrega o erro a quem esperava. Um `Future` por resolver e um pedido
        pendurado, e um pedido pendurado nao da erro nenhum."""
        for pendente in pendentes:
            if not pendente.espera.done():
                pendente.espera.set_exception(erro)
