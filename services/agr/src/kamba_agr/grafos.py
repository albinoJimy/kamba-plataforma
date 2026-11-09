"""A porta `grafos` do AGR, ligada ao registo de verticais (KAM-186).

Ate este modulo, as tres portas `grafos` do processo acabavam no `sem_grafos`
do `turno.py`, e todo o turno que chegava ao grafo respondia 503. Aqui ficam as
tres, e sao **duas resolucoes e nao uma**, que e a parte que importa:

    porta                    recebe               resolve a vertical por
    ExecutorDeTurnos         InvocacaoDoAgente    `AgentRegistry.resolve`, que
                                                  le o entitlement (KAM-027)
    Retomador (KAM-034)      thread_id            o *checkpoint* da thread
    Decisor (KAM-114)        thread_id            o *checkpoint* da thread

A retoma e a decisao de rascunho nao tem invocacao — o corpo de
`/internal/resume` sao tres campos —, e a vertical de uma *thread* que espera
por um humano e a do grafo que a interrompeu, e quem a sabe e o *checkpoint*.
Passar a mesma funcao as tres escondia isso.

**As duas resolucoes sao `async` e correm antes de tudo o resto.** A do turno
le o entitlement e o contacto **antes** do `ainvoke`; a da *thread* le o
*checkpoint* **antes** do CAS, e e isso que mantem a promessa do
`handoff/retoma.py`: sem grafo, a excepcao sobe antes de a base ser tocada.

## Uma vertical recusada nao volta a fila

O `resolve` devolve a recusa do criterio 6 do KAM-027 (`servico_indisponivel`)
para um *tenant* sem o entitlement ou com uma vertical que o registo nao tem.
Isto e configuracao, nao avaria: nenhuma das seis tentativas da escada do
*shim* a muda. Por isso a recusa sobe como `VerticalRecusadaError`, o turno
acaba com o desfecho `servico_indisponivel` e a rota responde **200** — uma
tentativa, e o *job* completa.

## A admissao do turno decide-se fora do grafo, e o grafo le-a

A porta `admitir` das `Dependencias` e sincrona e recebe o estado. As duas
condicoes que ela tem de ver (criterio 7 do KAM-031) estao fora do estado:

* o **contacto bloqueado** esta em `platform.contacts`, que e E/S de base, e um
  no sincrono a fazer E/S prendia a *event loop*;
* o **`turn_id` repetido** so se ve no *checkpoint* de **antes** do turno — o
  `estado_inicial` escreve o `turn_id` novo por cima, e o LangGraph grava essa
  entrada num *checkpoint* antes do primeiro no (medido pelo KAM-033).

Por isso as duas leem-se na resolucao do turno, que e `async`, e o veredicto
viaja ate a porta num `ContextVar`: o LangGraph cria as tarefas dos nos a partir
da tarefa que chama o `ainvoke`, e elas herdam o contexto dela. **O `ritmo` nao
se le aqui**: o `aceita_o_ritmo` do `admissao.py` registra a chegada, e chama-lo
outra vez gastava duas vagas por mensagem e cortava o tecto a metade.
"""

from __future__ import annotations

import asyncio
import contextvars
import importlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final

from .contexto import InvocacaoDoAgente
from .turno import (
    Grafo,
    GrafoNaoRegistadoError,
    SaidaPorLigarError,
    VerticalRecusadaError,
)

#: As duas recusas que a admissao do turno decide aqui. A terceira do dominio
#: (`ritmo`, dicionario §3.30) e da `api_interna.py`, antes da tranca.
TURNO_REPETIDO: Final = "turno_repetido"
CONTACTO_BLOQUEADO: Final = "contacto_bloqueado"

#: O veredicto da admissao do turno em curso. `None` fora de um turno, que e
#: «admite» — e o que a porta devolve a quem compile um grafo sem a resolucao.
_ADMISSAO: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "kamba_agr_admissao_do_turno", default=None
)

#: A politica de concierge deste turno, lida antes do `ainvoke`: `(tenant, activa)`.
#: `None` fora de um turno — na retoma e na decisao de rascunho, que nao passam
#: pela resolucao do turno — e a `PoliticaDoTurno` le-a entao directamente.
_CONCIERGE: contextvars.ContextVar[tuple[str, bool] | None] = contextvars.ContextVar(
    "kamba_agr_concierge_do_turno", default=None
)


class PortasIncoerentesError(RuntimeError):
    """O `Dependencias` tem a politica de concierge e nao tem o servico.

    E o par do `P3` da `ANALISE-39` e do `ADR-L005`: com a politica activa e o
    `ServicoDeRascunho` por ligar, o turno levanta `ConciergeSemServicoError` e
    o *job* gasta as seis tentativas. O arranque recusa-o, com o codigo `2` da
    configuracao invalida — e e configuracao, nao avaria.
    """


def importar_build_graph(alvo: str) -> Callable[[Any], Grafo]:
    """O `build_graph` de `modulo:funcao`, o `graph` de `registry/<id>.yaml`."""
    modulo, separador, funcao = alvo.partition(":")
    if not separador or not funcao:
        raise GrafoNaoRegistadoError(f"alvo_sem_funcao:{alvo}")
    return getattr(importlib.import_module(modulo), funcao)


def admitir(_estado: Mapping[str, Any]) -> str | None:
    """A porta `admitir` das `Dependencias`: o veredicto da resolucao do turno."""
    return _ADMISSAO.get()


class PoliticaDoTurno:
    """A `PoliticaDeConcierge`, lida **fora** da *event loop* e uma vez por turno.

    O no `send` e `async` e pergunta `activa(tenant)` sem `await`; a
    `PoliticaDeConcierge` responde com uma leitura sincrona a base. Ligada
    directamente, essa leitura corria na *event loop* em cada turno que envia, e
    dois turnos de *threads* diferentes serializavam — medido pela revisao
    adversarial do KAM-186: 1,43 s contra 0,33 s com um leitor de 0,5 s.

    A leitura passa para a resolucao do turno, num *executor*, e o resultado
    chega ao `send` por um `ContextVar`, como a admissao. **Continua a ser uma
    leitura por turno e sem *cache*** — o criterio 8 do KAM-114. Fora de um turno
    (a retoma e a decisao, que tambem chegam ao `send`) le directamente.
    """

    __slots__ = ("politica",)

    def __init__(self, politica: Any) -> None:
        self.politica = politica

    def activa(self, tenant_id: str) -> bool:
        lida = _CONCIERGE.get()
        if lida is not None and lida[0] == tenant_id:
            return lida[1]
        return bool(self.politica.activa(tenant_id))


def exigir_portas_coerentes(portas: Mapping[str, Any]) -> None:
    """Criterio 8: a politica de concierge sem `ServicoDeRascunho` recusa."""
    from .concierge.politica import SemPolitica

    concierge = portas.get("concierge")
    if isinstance(concierge, PoliticaDoTurno):
        concierge = concierge.politica
    if concierge is not None and not isinstance(concierge, SemPolitica):
        if portas.get("rascunho") is None:
            raise PortasIncoerentesError("concierge_sem_servico_de_rascunho")


def compilar(
    verticais: Mapping[str, Any],
    portas: Mapping[str, Any],
    dependencias: Callable[..., Any] | None = None,
) -> dict[str, Grafo]:
    """Um grafo compilado por vertical, com as mesmas portas em todas.

    A `persona` e as `tools_permitidas` sao **da vertical** e vem do registo;
    o resto e do processo e e o mesmo objecto para as duas — um disjuntor por
    grafo dava a cada vertical um contador proprio, e dois contadores a metade
    do caminho nunca abrem (a nota da ToolLayer no `__main__`).
    """
    exigir_portas_coerentes(portas)
    if dependencias is None:
        from .verticais.vendedor.nos import Dependencias as dependencias
    grafos: dict[str, Grafo] = {}
    for identificador, vertical in sorted(verticais.items()):
        deps = dependencias(
            persona=vertical.persona.model_dump(exclude_none=True),
            tools_permitidas=tuple(vertical.tools),
            **portas,
        )
        grafos[identificador] = importar_build_graph(vertical.graph)(deps)
    return grafos


def para_validar(vertical: Any) -> Grafo:
    """O `construir_grafo` da validacao (3) do §5.2, com portas inertes.

    A validacao corre com o registo, **antes** de o cofre e o checkpointer
    abrirem, e o que confere e a forma: o alvo importa, compila, e tem os seis
    nos obrigatorios. Os nos dependem das portas so quando correm, pelo que
    compilar sem elas da o mesmo grafo — e o grafo que serve compila-se do
    **mesmo** alvo, mais abaixo no arranque, com as portas reais.
    """
    return compilar(
        {vertical.id: vertical}, {"tools": None, "saida": SaidaPorLigar()}
    )[vertical.id]


class _GrafoDoTurno:
    """O grafo da vertical, com o que se leu antes do turno: admissao e politica."""

    __slots__ = ("_grafo", "_admissao", "_concierge")

    def __init__(
        self,
        grafo: Grafo,
        admissao: str | None,
        concierge: tuple[str, bool] | None = None,
    ) -> None:
        self._grafo = grafo
        self._admissao = admissao
        self._concierge = concierge

    async def ainvoke(self, estado: dict[str, Any], config: dict[str, Any]) -> Any:
        marca = _ADMISSAO.set(self._admissao)
        marca_da_politica = _CONCIERGE.set(self._concierge)
        try:
            return await self._grafo.ainvoke(estado, config)
        finally:
            _CONCIERGE.reset(marca_da_politica)
            _ADMISSAO.reset(marca)


class PortaDeGrafos:
    """As tres portas `grafos`: a do turno e as duas por `thread_id`."""

    __slots__ = ("_registo", "_grafos", "_checkpointer", "_bloqueado", "_politica")

    def __init__(
        self,
        *,
        registo: Any,
        grafos: Mapping[str, Grafo],
        checkpointer: Any,
        contacto_bloqueado: Callable[[InvocacaoDoAgente], Awaitable[bool]],
        politica: PoliticaDoTurno | None = None,
    ) -> None:
        self._registo = registo
        self._grafos = dict(grafos)
        self._checkpointer = checkpointer
        self._bloqueado = contacto_bloqueado
        self._politica = politica

    def _grafo(self, vertical: object) -> Grafo:
        grafo = self._grafos.get(vertical) if isinstance(vertical, str) else None
        if grafo is None:
            raise GrafoNaoRegistadoError("grafo_nao_registado")
        return grafo

    async def do_turno(self, invocacao: InvocacaoDoAgente) -> Grafo:
        """A porta do `ExecutorDeTurnos`. Levanta `VerticalRecusadaError`.

        O `resolve` le o entitlement com o driver sincrono da casa, e por isso
        vai a um *executor*: na *event loop* serializava o AGR inteiro na
        latencia da base (a nota 3 do `conversa.py`).
        """
        resolucao = await asyncio.to_thread(self._registo.resolve, invocacao)
        if resolucao.vertical is None:
            raise VerticalRecusadaError(str(resolucao.motivo))
        grafo = self._grafo(resolucao.vertical.id)
        admissao = await self._admissao(invocacao, grafo)
        concierge = None
        if self._politica is not None:
            activa = await asyncio.to_thread(
                self._politica.politica.activa, invocacao.tenant_id
            )
            concierge = (invocacao.tenant_id, bool(activa))
        return _GrafoDoTurno(grafo, admissao, concierge)

    async def _admissao(self, invocacao: InvocacaoDoAgente, grafo: Any) -> str | None:
        if await self._bloqueado(invocacao):
            return CONTACTO_BLOQUEADO
        # **Repetido e o mesmo `turn_id` num turno que acabou.** Um turno que
        # morreu a meio deixa o *checkpoint* com `next` por correr e tem de se
        # repetir desde o inicio (criterio 4 do KAM-025): a chave `turn_id:seq`
        # e que o torna seguro, e chamar-lhe repetido perdia a resposta.
        foto = await grafo.aget_state(
            {"configurable": {"thread_id": invocacao.thread_id}}
        )
        if foto.values.get("turn_id") == invocacao.turn_id and not foto.next:
            return TURNO_REPETIDO
        return None

    async def da_thread(self, thread_id: str) -> Grafo:
        """A porta do `Retomador` e do `Decisor`: a vertical do *checkpoint*.

        Sem *checkpoint*, ou com uma vertical que o registo nao tem, levanta
        `GrafoNaoRegistadoError` — que a rota traduz em 503 **sem escrever
        nada**, porque quem chama resolve o grafo antes do CAS.
        """
        tupla = await self._checkpointer.aget_tuple(
            {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
        )
        valores = {} if tupla is None else tupla.checkpoint.get("channel_values", {})
        return self._grafo(valores.get("vertical"))


class SaidaPorLigar:
    """A `PortaDeSaida` do grafo, por ligar: **nao ha Outbound a que o AGR fale**.

    O Outbound e o `Saida` de `packages/core-ts/src/outbound/` (KAM-015), uma
    biblioteca TypeScript que **nenhum servico instancia** — medido:
    `grep -rn "new Saida" services packages` so encontra comentarios. O AGR e
    Python, e nao ha fila nem rota entre os dois. A linha que aqui fica nao e
    deste ticket nem de nenhum aberto: e um achado com credor por abrir.

    **Avisa e levanta `SaidaPorLigarError`**, que a rota traduz em 503
    `saida_por_ligar` com `Retry-After`. A primeira versao nao levantava, e a
    revisao adversarial mediu o que isso custava: o turno acabava `executado`, o
    *job* completava, a resposta ia para lado nenhum — e a desduplicacao por
    `turn_id` marcava qualquer reentrega como `turno_repetido`, pelo que a
    mensagem ficava **irrecuperavel**. Levantando, o turno nao acaba (o
    *checkpoint* fica com o `send` por correr), o *job* esgota a escada e fica em
    `failed`, e reprocessa-se quando a ponte existir. Nenhuma resposta se perde,
    e o `executado` nao conta turnos que nao falaram.
    """

    __slots__ = ("_aviso",)

    def __init__(self, aviso: Callable[[str], None] | None = None) -> None:
        self._aviso = aviso

    def enfileirar(
        self, estado: Mapping[str, Any], texto: str, *, chave: str, botoes: Any = ()
    ) -> None:
        if self._aviso is not None:
            self._aviso("saida_por_ligar")
        raise SaidaPorLigarError("saida_por_ligar")


__all__ = [
    "CONTACTO_BLOQUEADO",
    "PortaDeGrafos",
    "PoliticaDoTurno",
    "PortasIncoerentesError",
    "SaidaPorLigar",
    "TURNO_REPETIDO",
    "VerticalRecusadaError",
    "admitir",
    "compilar",
    "exigir_portas_coerentes",
    "importar_build_graph",
    "para_validar",
]
