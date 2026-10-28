"""O *compare-and-set* da decisao e a retoma do grafo (KAM-114, criterios 2 e 4).

A forma e a do `Retomador` do KAM-034, e nao por simetria: as tres licoes que
aquele ticket pagou aplicam-se inteiras aqui.

1. **O grafo resolve-se antes do CAS.** Sem grafo para esta *thread*, o CAS
   escrevia a decisao e a compensacao devolvia-a a `pendente` — duas escritas
   para nada e uma janela em que o rascunho aparecia decidido. Resolvido
   primeiro, a excepcao sobe **antes** de a base ser tocada.
2. **O CAS e uma instrucao.** Ler o estado e escrever depois perdia a corrida
   entre dois cliques, que e exactamente o que o criterio 2 mede.
3. **A tranca e de quem chama.** Ela tem de cobrir o CAS, o `Command` **e** a
   compensacao; tomada aqui dentro cobria so o que esta classe faz.

## Porque e que a distancia se calcula **antes** do CAS

A revisao `0024` tem um `CHECK` que exige `razao_edicao IS NOT NULL` quando
`decisao = 'editado'`. Isso nao e inconveniente: e a base a dizer que a decisao e
a sua medida sao **um** facto e entram numa escrita so. Uma segunda escrita a
seguir deixava uma janela — e, se falhasse, uma linha `editado` sem medida, isto
e, uma edicao que o `draft_edit_ratio_p50` nao conta e que ninguem ve que falta.

Para a calcular preciso do texto **original**, e ele nao esta nesta tabela de
proposito (nao ha texto aqui). Esta no *checkpoint* do LangGraph, que e nosso, e
le-se com `aget_state` — a mesma configuracao de `thread_id` que a retoma usa
para o `Command`. **Medido** contra a versao fixada no `.venv`: o `Pregel` expoe
`aget_state` e `aget_state_history`.

E o que atravessa para a tabela e **um numero e um booleano**. O texto entra
nesta classe, e usado para medir, e nao sai.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from kamba_core import tenant_guard

from ..metricas import METRICA_DRAFT_DECISAO, METRICA_DRAFT_ESTADO, MetricasDoAgr
from ..handoff.retoma import partes
from .consultas import (
    SQL_DECIDIR_RASCUNHO,
    SQL_ESTADO_DO_RASCUNHO,
    SQL_REVERTER_DECISAO,
)
from .maquina import (
    DESFECHOS,
    distancia_normalizada,
    exigir_decisao,
    exigir_motivo,
    numero_livre,
)

class TextoEditadoInvalidoError(ValueError):
    """`editado` sem texto, ou texto numa decisao que o nao leva."""


class DecisaoDoSistemaInvalidaError(ValueError):
    """Pediu-se ao sistema uma decisao que so um humano pode tomar.

    E o espelho do `do_operador` do `exigir_decisao`: as duas vias tem dominios
    **disjuntos** — tres valores de um lado, dois do outro — e nenhuma pode
    escrever os valores da outra. Sem isto, a varredura podia escrever
    `aprovado` e deixar sair uma mensagem que nenhum humano aprovou, que e a
    barreira do criterio 1 aberta de dentro.
    """


class GrafoDaDecisaoError(RuntimeError):
    """A retoma do grafo falhou **depois** de o CAS vencer; a decisao foi revertida."""


class ReversaoFalhadaError(RuntimeError):
    """A compensacao tambem falhou: a linha fica decidida e o grafo nao retomado.

    E o residuo da falha dupla, e a mesma classe que o KAM-034 declarou. Fica
    dito em vez de escondido: nenhuma varredura deste repositorio limpa um
    rascunho decidido cujo *checkpoint* nao retomou, porque isso exige ler o
    estado do LangGraph.
    """

    def __init__(self, mensagem: str, original: BaseException | None = None) -> None:
        super().__init__(mensagem)
        self.original = original


class ResultadoDaDecisao:
    """O que a rota precisa de devolver ao HND (KAM-114, criterios 2 e 4).

    **Nao e so o desfecho, e a razao e o criterio 4.** Ele manda que uma edicao
    com numero fora dos *facts* seja «**sinalizada ao operador** e registada
    como `edicao_numero_livre`». O registo faz-se na coluna; a sinalizacao tem
    de **voltar** pela resposta, senao o unico lugar onde o sinal existe e um
    painel que o operador nao esta a ver — ele editou, meteu um preco que
    nenhuma tool devolveu, e a plataforma contou-o sem lhe dizer nada.

    A primeira versao devolvia so a cadeia do desfecho, e o `numero_livre`
    morria no estado do grafo. Apanhado pela revisao adversarial.

    O `desfecho` continua a decidir o estado HTTP; o `numero_livre` e informacao
    para quem decidiu.
    """

    __slots__ = ("desfecho", "numero_livre")

    def __init__(self, desfecho: str, numero_livre: bool = False) -> None:
        self.desfecho = desfecho
        self.numero_livre = numero_livre


class RascunhoNoCheckpoint:
    """O que o *checkpoint* diz sobre o rascunho deste turno."""

    __slots__ = ("texto", "facts")

    def __init__(self, texto: str, facts: tuple[Any, ...]) -> None:
        self.texto = texto
        self.facts = facts


class Decisor:
    """O CAS da decisao, a medida da edicao e o `Command(resume=...)`.

    `abrir_ligacao` devolve uma ligacao DB-API transaccional (o `pg8000` da
    casa); `grafos` resolve o grafo de um *thread*. A ligacao abre-se a primeira
    decisao e fica, com um `asyncio.Lock` a serializa-la — o `pg8000` nao e
    seguro para uso concorrente na mesma ligacao.
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

    async def decidir(
        self,
        thread_id: str,
        draft_id: str,
        decisao: str,
        motivo: object = None,
        texto_editado: object = None,
    ) -> ResultadoDaDecisao:
        """Decide o rascunho. Devolve o desfecho **e** o sinal do numero livre.

        `decisao` e uma das tres que um clique pode pedir: o `expirado` e da
        varredura e o `substituido` e do *echo* ou do handoff, e aceita-los aqui
        dava a um operador a possibilidade de escrever um desfecho que o sistema
        reserva para si.
        """
        decisao = exigir_decisao(decisao, do_operador=True)
        motivo_valido = exigir_motivo(motivo, decisao)
        tenant_id, _contact_id = partes(thread_id)

        # Licao 1 da nota do modulo: antes de tocar na base.
        grafo = self._grafos(thread_id)

        razao: float | None = None
        livre = False
        if decisao == "editado":
            if not isinstance(texto_editado, str) or not texto_editado.strip():
                raise TextoEditadoInvalidoError(
                    "uma decisao `editado` sem texto nao e uma edicao"
                )
            no_checkpoint = await self._rascunho_no_checkpoint(grafo, thread_id)
            razao = distancia_normalizada(no_checkpoint.texto, texto_editado)
            livre = numero_livre(texto_editado, no_checkpoint.facts)
        elif texto_editado is not None:
            # **Nao se ignora em silencio.** Um `aprovado` com texto e um
            # operador a achar que editou: aceitar e descartar o texto enviava
            # o rascunho original como se fosse a edicao dele.
            raise TextoEditadoInvalidoError(
                f"so uma decisao `editado` leva texto (recebido com {decisao!r})"
            )

        venceu = await self._executar(
            SQL_DECIDIR_RASCUNHO,
            (decisao, motivo_valido, razao, livre, tenant_id, draft_id, thread_id),
            tenant_id,
        )
        if not venceu:
            return ResultadoDaDecisao(
                self._contar_e_devolver(
                    await self._classificar(tenant_id, draft_id, thread_id)
                ),
                # **O sinal nao se devolve num desfecho que nao decidiu.** Num
                # duplo clique, quem decidiu foi o primeiro pedido, e repetir-lhe
                # o sinal dizia a quem chegou segundo que a **sua** edicao trazia
                # um numero livre — e ela nao foi gravada.
                numero_livre=False,
            )

        try:
            await self._resumir_o_grafo(grafo, thread_id, decisao, texto_editado, livre)
        except BaseException as erro:
            await self._reverter(tenant_id, draft_id, thread_id, decisao, erro)
            raise GrafoDaDecisaoError("retoma_do_grafo_falhou") from erro

        self._contar_estado(decisao)
        return ResultadoDaDecisao(self._contar_e_devolver("decidido"), livre)

    async def decidir_pelo_sistema(
        self, thread_id: str, draft_id: str, decisao: str
    ) -> str:
        """`expirado` ou `substituido`: a decisao que **nao** vem de um clique.

        Devolve um dos `DESFECHOS`. E a via da varredura dos prazos (criterio 1)
        e da substituicao por *echo* do dono, por handoff ou por politica
        desligada (criterios 5 e 8).

        **Passa pelo mesmo CAS e pela mesma retoma que o clique**, e isso e
        deliberado: o criterio 7 do KAM-034 pagou esta licao do outro lado («uma
        segunda via de retoma que nao passasse pelo CAS nem pela tranca era uma
        segunda implementacao do criterio 3»). Aqui a corrida e real e nao
        hipotetica — um operador pode carregar em «aprovar» no mesmo instante em
        que a varredura decide expirar o rascunho —, e o CAS e o que garante que
        **um** dos dois vence e que so **um** envio acontece.

        **E retoma o grafo**, que e a metade que nao se pode esquecer: o
        `draft_wait` esta interrompido, e um rascunho marcado `substituido` sem
        retoma deixava o *thread* com um `interrupt` pendente para sempre — e a
        invariante do §11 proibe invocar o grafo com *input* novo nesse estado,
        pelo que a conversa ficava **muda** em vez de automatica.
        """
        if decisao not in ("expirado", "substituido"):
            raise DecisaoDoSistemaInvalidaError(
                "pelo sistema decidem-se so `expirado` e `substituido` "
                f"(recebido: {decisao!r})"
            )
        tenant_id, _contact_id = partes(thread_id)
        grafo = self._grafos(thread_id)

        venceu = await self._executar(
            SQL_DECIDIR_RASCUNHO,
            (decisao, None, None, False, tenant_id, draft_id, thread_id),
            tenant_id,
        )
        if not venceu:
            return self._contar_e_devolver(
                await self._classificar(tenant_id, draft_id, thread_id)
            )

        try:
            await self._resumir_o_grafo(grafo, thread_id, decisao, None, False)
        except BaseException as erro:
            await self._reverter(tenant_id, draft_id, thread_id, decisao, erro)
            raise GrafoDaDecisaoError("retoma_do_grafo_falhou") from erro

        self._contar_estado(decisao)
        return self._contar_e_devolver("decidido")

    async def _rascunho_no_checkpoint(
        self, grafo: Any, thread_id: str
    ) -> RascunhoNoCheckpoint:
        """O texto do rascunho e os *facts* do turno, lidos do *checkpoint*.

        **E a unica fonte possivel do texto original**, e e por isso que a
        medida da edicao se faz aqui e nao no HND: o provedor tem uma **copia**
        do que lhe publicamos, e medir contra uma copia que alguem no Chatwoot
        pode ter tocado media a edicao errada.
        """
        estado = await grafo.aget_state({"configurable": {"thread_id": thread_id}})
        valores = getattr(estado, "values", None) or {}
        rascunho = valores.get("draft") or {}
        texto = str(rascunho.get("texto") or "")
        if not texto:
            raise TextoEditadoInvalidoError(
                "o checkpoint deste thread nao tem rascunho para comparar"
            )
        return RascunhoNoCheckpoint(texto, tuple(valores.get("facts") or ()))

    async def _resumir_o_grafo(
        self,
        grafo: Any,
        thread_id: str,
        decisao: str,
        texto_editado: object,
        livre: bool,
    ) -> None:
        """`Command(resume={...})` no grafo deste *thread*.

        O `Command` importa-se **aqui** e nao no topo do modulo, pela razao do
        `handoff/retoma.py`: o `langgraph.types` arrasta o LangGraph, e os
        modulos deste pacote que nao retomam grafo nenhum (a `maquina`, a
        `politica`) importam-se sem ele.

        **O `texto` so vai no `editado`.** No `aprovado` o texto a enviar e o que
        esta no estado, e manda-lo outra vez dava duas fontes para a mesma
        mensagem — e a do corpo HTTP e a menos fiavel das duas.
        """
        from langgraph.types import Command

        retoma: dict[str, Any] = {"decisao": decisao, "numero_livre": livre}
        if decisao == "editado":
            retoma["texto"] = texto_editado
        await grafo.ainvoke(
            Command(resume=retoma),
            {"configurable": {"thread_id": thread_id}},
        )

    async def _classificar(
        self, tenant_id: str, draft_id: str, thread_id: str
    ) -> str:
        """`repetido` se o rascunho e deste *thread*; `recusado` se nao e.

        **Zero linhas sao duas respostas diferentes**, e e isso que a
        classificacao separa (a licao do KAM-034): o rascunho que ja foi decidido
        e o duplo clique (200, `repetido`) e o que nao e deste *thread* e uma
        recusa (404, `recusado`) — um 200 ali dizia ao HND «tratado» sobre um
        pedido que nao tratamos.
        """
        linha = await self._executar(
            SQL_ESTADO_DO_RASCUNHO, (tenant_id, draft_id, thread_id), tenant_id
        )
        if linha is None:
            return "recusado"
        # Um rascunho **deste** *thread* que ja tem decisao. O `None` aqui e por
        # construcao impossivel — o CAS acabou de nao casar —, e confronta-se de
        # qualquer maneira: se um dia disser `None` sobre um rascunho que o CAS
        # recusou, as duas leituras divergiram, e isso e um defeito e nao um
        # duplicado.
        if linha[0] is None:
            return "recusado"
        return "repetido"

    async def _reverter(
        self,
        tenant_id: str,
        draft_id: str,
        thread_id: str,
        decisao: str,
        original: BaseException,
    ) -> None:
        """Devolve o rascunho a `pendente` depois de a retoma falhar.

        Sem isto, uma falha do `Command` deixava a linha decidida e o
        *checkpoint* a espera: o operador via o rascunho como tratado, o cliente
        nunca recebia nada, e a varredura dos prazos **nao o encontrava** —
        porque ela filtra `decisao IS NULL`.
        """
        try:
            await self._executar(
                SQL_REVERTER_DECISAO,
                (tenant_id, draft_id, thread_id, decisao),
                tenant_id,
            )
        except BaseException as falha:
            raise ReversaoFalhadaError(
                "a decisao ficou gravada e o grafo nao retomou", original
            ) from falha

    async def _executar(self, sql: str, parametros: tuple, tenant_id: str) -> Any:
        """Uma instrucao com contexto de *tenant*, num *executor*.

        Devolve a primeira linha, ou `None` se nao houve nenhuma — que e o que
        um `RETURNING` que nao casa da, e e a resposta e nao um erro.
        """
        async with self._exclusiva:
            try:
                return await asyncio.to_thread(
                    self._sincrono, sql, parametros, tenant_id
                )
            except Exception:
                # A razao do `trancas.py` e do `handoff/retoma.py`: uma ligacao
                # quebrada que fique guardada faz **todas** as decisoes deste
                # processo falharem ate alguem reiniciar o servico.
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

    def _contar_estado(self, decisao: str) -> None:
        """Conta o estado em que o rascunho ficou (`agr_draft_estado_total`).

        **E separado do desfecho da chamada**, e a razao e a mesma do
        `agr_handoff_total` contra o `agr_resume_total`: um painel que somasse os
        dois nao distinguia «um rascunho aprovado» de «uma chamada que aprovou um
        rascunho», e no duplo clique sao um e dois.
        """
        if self._metricas is not None:
            self._metricas.contar(METRICA_DRAFT_ESTADO, decisao)

    def _contar_e_devolver(self, desfecho: str) -> str:
        if desfecho not in DESFECHOS:  # pragma: no cover — defensivo
            raise ValueError(f"desfecho fora de {DESFECHOS}: {desfecho!r}")
        if self._metricas is not None:
            self._metricas.contar(METRICA_DRAFT_DECISAO, desfecho)
        return desfecho

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


__all__ = [
    "DecisaoDoSistemaInvalidaError",
    "ResultadoDaDecisao",
    "Decisor",
    "GrafoDaDecisaoError",
    "RascunhoNoCheckpoint",
    "ReversaoFalhadaError",
    "TextoEditadoInvalidoError",
]
