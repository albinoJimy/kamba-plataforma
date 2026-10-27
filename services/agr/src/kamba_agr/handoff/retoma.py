"""A retoma por *compare-and-set* e o `Command(resume=...)` (criterios 3 e 8).

«`POST /internal/resume {thread_id, handoff_id, outcome}` faz CAS `waiting ->
resumed`; dois pedidos concorrentes com o mesmo `handoff_id` produzem 1 retoma e
o 2.º devolve *no-op* (200).»

## A ordem das duas escritas, e porque e esta

Sao duas escritas em dois sitios: o `status` da passagem, na base, e o
`Command(resume=...)`, no *checkpointer* do LangGraph. Nao ha transaccao que as
cubra, pelo que ha uma ordem e ha uma falha possivel entre elas.

**CAS primeiro.** E o que o §11 regra 3 manda («so o primeiro vence, o segundo
e *no-op*») e e a unica ordem em que a propriedade do criterio 3 e verdadeira:
com o `Command` primeiro, dois *webhooks* duplicados do Chatwoot retomavam o
grafo **duas vezes** e so depois disputavam uma linha — e o segundo
`Command(resume=...)` entrava num *thread* que ja nao tinha `interrupt`
pendente.

**E a falha entre as duas compensa-se.** Se o `Command` levantar depois de o CAS
ter vencido, a linha fica em `resumed` com o grafo ainda interrompido: o
*webhook* repetido ve zero linhas, responde 200, e a passagem fica presa **para
sempre** — invisivel, porque a varredura dos prazos so olha para `waiting`. Por
isso o `SQL_REVERTER_RETOMA` devolve a linha a `waiting` e a excepcao sobe: o
HND repete, o CAS vence outra vez, e o `Command` tem outra oportunidade.

A compensacao e segura porque **tudo isto corre sob a tranca da conversa**, que
quem chama toma antes (o `api_interna.py` e a varredura dos prazos, cada um no
seu caminho). Entre o CAS e a compensacao ninguem mais toca na linha, e o
predicado da reversao confirma-o de qualquer maneira.

## Zero linhas sao duas respostas diferentes

O CAS nao casa em dois casos que nao se podem confundir:

* a passagem **ja saiu** de `waiting` — e o *webhook* duplicado, e a resposta e
  200 sem efeito (`repetido`);
* a passagem **nao e deste *thread*** — nao existe, e de outro *tenant*, ou e de
  outro contacto do mesmo *tenant*. A resposta e uma recusa (`recusado`), e nao
  um 200: um 200 aqui dizia ao HND «tratado» sobre um pedido que nao tratamos, e
  um `thread_id` trocado passava a ser um erro silencioso em vez de um alerta.

Quem os separa e o `SQL_HANDOFF_PARA_RETOMA`, e corre **so** neste caminho — o
que vence paga uma instrucao e nao duas.

## O `outcome` atravessa sem traducao

O que entra no `Command(resume=...)` e o desfecho do pedido, nao o estado que
foi escrito: o `handoff_wait` do KAM-031 devolve `{"handoff": {..., "outcome":
resultado}}` e o `handoff_close` compara `outcome == "timeout"` para mandar a
mensagem de alternativas. Traduzir antes de entrar fazia o `resolved` chegar la
como `resumed`, que nao bate com nada, e o criterio 7 deixava de ter caminho.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Final

from kamba_core import tenant_guard

from ..consultas import (
    SQL_HANDOFF_PARA_RETOMA,
    SQL_RETOMAR_HANDOFF,
    SQL_REVERTER_RETOMA,
)
from ..metricas import METRICA_HANDOFF, METRICA_RETOMA, MetricasDoAgr
from .maquina import estado_do_desfecho, pode_retomar

#: Os tres desfechos de uma chamada a `retomar`. Lista **fechada**: e etiqueta
#: de `agr_resume_total`.
#:
#: `retomado`  venceu o CAS e o grafo foi retomado
#: `repetido`  a passagem ja tinha saido de `waiting`: *no-op* (criterio 3)
#: `recusado`  a passagem nao e deste *thread* (isolamento, ADR-015)
DESFECHOS_DA_RETOMA: Final = ("retomado", "repetido", "recusado")


class ThreadInvalidoError(ValueError):
    """O `thread_id` do pedido nao tem a forma `{tenant_id}:{contact_id}`.

    Levanta em vez de recusar com `recusado`, e a diferenca e o estado HTTP: um
    `thread_id` malformado e um **corpo invalido** (400) e nao uma passagem que
    nao existe (404). O `contexto.py` faz a mesma distincao para o
    `/internal/turn`, e pela mesma razao — um 404 dizia ao HND que o pedido
    estava bem formado e que a passagem e que nao estava la.
    """


class GrafoDaRetomaError(RuntimeError):
    """O `Command(resume=...)` nao correu, e a passagem foi devolvida a `waiting`.

    Sobe para que a rota responda 5xx e o HND repita. O que a distingue de uma
    falha qualquer e a *docstring* do modulo: quando ela aparece, a compensacao
    **ja** correu, e por isso repetir e seguro.
    """


class ReversaoFalhadaError(RuntimeError):
    """A compensacao nao correu: a passagem ficou em `resumed` sem grafo retomado.

    E o residuo deste desenho, e nomeia-se em vez de se esconder. Acontece se o
    `Command` **e** a reversao falharem no mesmo pedido — tipicamente a base a
    cair entre os dois. A passagem fica presa: o *webhook* repetido ve zero
    linhas e a varredura dos prazos nao a ve, porque so olha para `waiting`.

    Levanta-se com a falha original encadeada (`raise ... from`), que e o que
    poe as duas no mesmo registo. **Quem a limpa nao esta atribuido a ticket
    nenhum**, e isso fica escrito no bloco do ticket: uma varredura de passagens
    em `resumed` sem *checkpoint* retomado precisa de ler o estado do LangGraph,
    que e o que esta varredura nao faz.
    """


class Retomador:
    """O CAS, o `Command(resume=...)` e a compensacao, sobre uma ligacao propria.

    `abrir_ligacao` devolve uma ligacao DB-API transaccional (o `pg8000` da
    casa); `grafos` resolve o grafo de um *thread*. A ligacao abre-se a primeira
    retoma e fica, com um `asyncio.Lock` a serializa-la — a mesma forma do
    `conversa.leitor`, e pela mesma razao: o `pg8000` nao e seguro para uso
    concorrente na mesma ligacao, e duas corrotinas na mesma tomada entrelacam
    as respostas.

    **Nao toma a tranca da conversa.** Quem a toma e quem chama — a rota e a
    varredura dos prazos —, e a razao e o alcance: a tranca tem de cobrir o CAS,
    o `Command` **e** a compensacao, que e o que torna a reversao segura. Tomada
    aqui dentro, cobria so o que esta classe faz, e a rota ficava a decidir o
    estado HTTP fora dela.

    **E nao e por um `unlock` a largar a tranca cedo**, que foi o que a primeira
    versao desta nota afirmou e que e falso: os *advisory locks* de sessao do
    PostgreSQL sao **contados**, pelo que um segundo `pg_try_advisory_lock` da
    mesma chave na mesma sessao sobe o contador e o `pg_advisory_unlock` de
    dentro desce-o para um — o bloco de fora continua a deter a tranca. O custo
    de aninhar era uma ida a base por retoma e um leitor a deixar de ver que a
    compensacao precisa da tranca; nao era um defeito de exclusao.
    """

    __slots__ = ("_abrir", "_grafos", "_metricas", "_ligacao", "_exclusiva")

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        grafos: Callable[[str], Any],
        metricas: MetricasDoAgr | None = None,
    ) -> None:
        self._abrir = abrir_ligacao
        self._grafos = grafos
        self._metricas = metricas
        self._ligacao: Any | None = None
        self._exclusiva = asyncio.Lock()

    async def retomar(self, thread_id: str, handoff_id: str, desfecho: str) -> str:
        """Retoma a passagem. Devolve um dos `DESFECHOS_DA_RETOMA`.

        `desfecho` e o `outcome` do corpo — um dos tres do §11.1. Um valor fora
        deles levanta `DesfechoInvalidoError`, que a rota traduz em 400.
        """
        estado_novo = estado_do_desfecho(desfecho)
        tenant_id, contact_id = partes(thread_id)

        # **O grafo resolve-se antes do CAS**, e nao e indiferente: sem grafo
        # para esta *thread* — que e o estado do servico enquanto a porta
        # `grafos` do `turno.py` levantar `GrafoNaoRegistadoError` — o CAS
        # escrevia `resumed` e a compensacao devolvia-o a `waiting`, isto e, duas
        # escritas para nada e uma janela em que a passagem aparecia retomada.
        # Resolvido primeiro, a excepcao sobe **antes** de a base ser tocada e a
        # rota responde 503 com `Retry-After`: o *webhook* volta e nada mudou.
        grafo = self._grafos(thread_id)

        venceu = await self._executar(
            SQL_RETOMAR_HANDOFF,
            (estado_novo, tenant_id, handoff_id, contact_id),
            tenant_id,
        )
        if not venceu:
            return self._contar_e_devolver(
                await self._classificar(tenant_id, handoff_id, contact_id)
            )

        try:
            await self._resumir_o_grafo(grafo, thread_id, desfecho)
        except BaseException as erro:
            await self._reverter(tenant_id, handoff_id, estado_novo, erro)
            raise GrafoDaRetomaError("retoma_do_grafo_falhou") from erro

        self._contar(METRICA_HANDOFF, estado_novo)
        return self._contar_e_devolver("retomado")

    async def _resumir_o_grafo(self, grafo: Any, thread_id: str, desfecho: str) -> None:
        """`Command(resume={"outcome": ...})` no grafo deste *thread*.

        O grafo vem de fora, ja resolvido: quem o resolve e o `retomar`, antes
        do CAS, pela razao escrita la.

        O `Command` importa-se **aqui** e nao no topo do modulo, pela razao do
        `handoff_wait` do KAM-031: o `langgraph.types` arrasta o LangGraph, e os
        modulos deste pacote que nao retomam grafo nenhum (a `maquina`, a
        `autenticacao`) importam-se sem ele.
        """
        from langgraph.types import Command

        await grafo.ainvoke(
            Command(resume={"outcome": desfecho}),
            {"configurable": {"thread_id": thread_id}},
        )

    async def _classificar(
        self, tenant_id: str, handoff_id: str, contact_id: str
    ) -> str:
        """`repetido` se a passagem e deste *thread*; `recusado` se nao e."""
        linha = await self._executar(
            SQL_HANDOFF_PARA_RETOMA, (tenant_id, handoff_id, contact_id), tenant_id
        )
        if linha is None:
            return "recusado"
        # Uma passagem **desta** conversa que ja saiu de `waiting`. O
        # `pode_retomar` e `False` aqui por construcao — o CAS acabou de nao
        # casar —, e confronta-se de qualquer maneira: se um dia ele disser
        # `True` sobre uma passagem que o CAS recusou, as duas leituras do
        # dominio divergiram, e isso e um defeito e nao um duplicado.
        if pode_retomar(str(linha[0])):
            return "recusado"
        return "repetido"

    async def _reverter(
        self, tenant_id: str, handoff_id: str, estado_novo: str, original: BaseException
    ) -> None:
        """Devolve a passagem a `waiting`. Ver a *docstring* do modulo."""
        try:
            revertida = await self._executar(
                SQL_REVERTER_RETOMA, (tenant_id, handoff_id, estado_novo), tenant_id
            )
        except BaseException as erro:
            # **A falha original encadeia-se e a da reversao vai no contexto.**
            # Um `raise ... from erro` deixava o registo a dizer que a base caiu
            # e calava **qual** retoma ficou presa, que e a unica informacao com
            # que alguem consegue ir desencravar a passagem a mao.
            falha = ReversaoFalhadaError("reversao_da_retoma_falhou")
            falha.__cause__ = original
            falha.__context__ = erro
            raise falha from original
        if not revertida:
            raise ReversaoFalhadaError("reversao_da_retoma_sem_linha") from original

    async def _executar(self, sql: str, parametros: tuple, tenant_id: str) -> Any:
        """Uma instrucao com contexto de *tenant*, num *executor*.

        Devolve a primeira linha, ou `None` se nao houve nenhuma — que e o que
        um `RETURNING 1` que nao casa da, e e a resposta e nao um erro.
        """
        async with self._exclusiva:
            try:
                return await asyncio.to_thread(
                    self._sincrono, sql, parametros, tenant_id
                )
            except Exception:
                # A mesma razao do `trancas.py` e do `conversa.py`: uma ligacao
                # quebrada que fique guardada faz **todas** as retomas deste
                # processo falharem ate alguem reiniciar o servico. Larga-se, a
                # excepcao sobe, e a tentativa seguinte abre outra.
                ligacao, self._ligacao = self._ligacao, None
                if ligacao is not None:
                    try:
                        ligacao.close()
                    except Exception:  # noqa: BLE001 — ja esta quebrada
                        pass
                raise

    def _sincrono(self, sql: str, parametros: tuple, tenant_id: str) -> Any:
        if self._ligacao is None:
            self._ligacao = self._abrir()
        with tenant_guard.tx(self._ligacao, tenant_id) as cursor:
            cursor.execute(sql, parametros)
            return cursor.fetchone()

    def _contar_e_devolver(self, desfecho: str) -> str:
        self._contar(METRICA_RETOMA, desfecho)
        return desfecho

    def _contar(self, metrica: str, etiqueta: str | None) -> None:
        if self._metricas is not None:
            self._metricas.contar(metrica, etiqueta)

    async def fechar(self) -> None:
        """Fecha a ligacao, no encerramento ordenado do processo."""
        async with self._exclusiva:
            ligacao, self._ligacao = self._ligacao, None
            if ligacao is None:
                return
            try:
                await asyncio.to_thread(ligacao.close)
            except Exception:  # noqa: BLE001 — a tomada fecha de qualquer forma
                pass


def partes(thread_id: str) -> tuple[str, str]:
    """`(tenant_id, contact_id)` de um `thread_id`, ou levanta.

    **Exige exactamente um `:`**, e nao e rigor decorativo: o
    `autenticacao.tenant_do_thread` le o prefixo e deixa passar o resto, porque
    o que ele precisa e de saber de quem e o segredo. Aqui as duas metades vao
    para o predicado do CAS, e um `contact_id` com um `:` dentro e um
    `contact_id` que nao e um UUID — o que significa que o `thread_id` nao e o
    que o `contexto.py` constroi. Recusa-se com 400 em vez de ir a base
    perguntar por uma conversa que nao pode existir.
    """
    tenant_id, separador, contact_id = thread_id.partition(":")
    if not separador or not tenant_id or not contact_id or ":" in contact_id:
        raise ThreadInvalidoError("thread_id_invalido")
    return tenant_id, contact_id
