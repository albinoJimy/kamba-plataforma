"""Um turno por conversa: a tranca (KAM-025 criterio 2, `docs/tecnica/02` §12).

A decisao — `pg_advisory_lock` de **sessao** numa ligacao dedicada, contra o
`pg_advisory_xact_lock` e contra uma fila por chave — esta em
`docs/adr/ADR-L004-fila-e-tranca-do-agr.md` (Decisao 2), com as tres opcoes e o
que cada uma custa. Aqui esta so o que ela obriga.

## Tres coisas que este modulo e, e uma que nao e

**E a ligacao dedicada.** A tranca vive fora do *pool* de transaccoes porque e
tomada antes do turno e largada depois dele, e um turno dura segundos (§15.1 da
1,5–3,5 s so ao `compose`). Uma tranca de sessao numa ligacao que volta ao
*pool* entre instrucoes e invisivel a quem a tomou e presa para quem vier a
seguir — e o modo de falha que nao da erro nenhum, e por isso esta escrito
aqui, em `../../../docs/agr.md` e no ADR.

**ATENCAO:** isto **nao** pode correr atras de um *pooler* em modo transaccao
(PgBouncer `pool_mode = transaction`, e a omissao do Supavisor). Em modo
`session` funciona. O `KAMBA_AGR_TRANCA_DB_URL` aponta para a base, nao para um
*pooler*, e a *suite* do *gate* 8 mede a propriedade que isso compra: duas
ligacoes, e a segunda a nao conseguir a tranca da primeira.

**E `autocommit`.** Em transaccao, `pg_advisory_lock` continua a ser de sessao
(nao larga no `COMMIT`) — mas uma transaccao aberta e exactamente o que esta
escolha existe para evitar. Com `autocommit`, cada `SELECT` e a sua propria
transaccao, a tranca sobrevive-lhe, e nao ha nada aberto durante o turno. E por
isso que esta ligacao **nao** passa pelo `kamba_core.tenant_guard.tx`, que
recusa `autocommit` — de propósito, para o seu proprio uso.

**E sincrona por dentro e assincrona por fora.** O driver da casa e o `pg8000`
(sincrono, BSD-3-Clause, Python puro — a escolha e a justificacao estao em
`db/requirements/migrations.in`), e os *workers* do AGR sao `asyncio`. Por isso
cada chamada ao driver vai a um *executor*; a ligacao e usada por uma `thread`
de cada vez, protegida pelo `asyncio.Lock` desta classe.

**E a espera nao acontece dentro desse `asyncio.Lock`.** A primeira versao usava
`pg_advisory_lock`, que bloqueia **no servidor** ate a tranca ser sua — com a
`thread` presa e, com ela, o `asyncio.Lock` da unica ligacao do processo. A
revisao adversarial mediu o que isso custa: uma conversa a espera de uma chave
parava o processo inteiro, e as conversas que **acabaram** nao conseguiam
destrancar, porque o `pg_advisory_unlock` precisa da mesma ligacao. Bloqueio de
cabeca de fila a atravessar *tenants*, que e o que o criterio 5 proibe.

Hoje usa-se `pg_try_advisory_lock` num ciclo: cada tentativa toma o
`asyncio.Lock`, faz **uma** instrucao e larga-o; entre tentativas espera-se fora
dele. A ordem de chegada continua preservada porque dentro do processo so uma
corrotina por `thread_id` chega aqui — e quem o garante esta na secção seguinte.

## A tranca da base **nao** exclui dentro do processo (KAM-034)

E a correccao de uma afirmacao que esteve aqui desde o KAM-025 e que era falsa.
Esta linha dizia que «dentro do processo so uma corrotina por `thread_id` chega
aqui — quem serializa e o dreno de `turno.py`», e o `turno.py` dizia que «a
tranca da base serializa entre processos **e entre as conversas do mesmo
contacto**». As duas nao podiam ser verdade, e a segunda e a que importa:

**os *advisory locks* de sessao do PostgreSQL sao contados.** Esta classe tem
**uma** ligacao por processo (`self._ligacao`), pelo que a segunda tomada da
mesma chave na mesma sessao devolve `true` — e devolve `true` tambem o
`pg_advisory_unlock` de cada uma, pelo que o `TrancaNaoLargadaError`, que existe
para que «a exclusao mutua que deixou de existir apareca», nunca levanta. Medido
contra PostgreSQL 18 pela revisao adversarial do KAM-034: duas corrotinas
**dentro** da secção critica da mesma conversa, e o controlo positivo com duas
ligacoes a dar uma.

Para o turno isso estava coberto por outra peca — o dreno de `turno.py`, que
serializa por `(thread_id, conversation_id)` — e por isso ninguem tropecou nela.
O KAM-034 acrescentou os dois unicos chamadores que **nao** passam pelo dreno
(a rota `/internal/resume` e a varredura dos prazos), e para esses a tranca era a
unica barreira.

A correccao e um `asyncio.Lock` por `thread_id` **a frente** da ida a base: a
tranca da base continua a excluir entre processos, e o trinco exclui dentro de
um. Nao substitui o dreno, que faz outra coisa (coalescer e preservar a ordem de
chegada de um lote); dar as duas e o que torna verdadeira a frase em que o
KAM-034 assenta — «entre o CAS e a compensacao ninguem mais toca na linha».

**O que nao e: o grafo.** Este modulo nao sabe o que corre dentro da secção
critica. Recebe uma corrotina e corre-a com a tranca tomada.

## O que o SIGKILL compra, e porque nao ha temporizador

Morto o processo, o sistema operativo fecha a ligacao, o PostgreSQL larga a
tranca, e o *worker* seguinte toma-a. Nao ha TTL a expirar com o dono vivo, nem
tranca orfa a limpar a mao, nem relogio a calibrar. E a razao de peso da
Decisao 2 do ADR, e a *suite* mede-a com um `SIGKILL` a serio.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from .consultas import SQL_DESTRANCAR_THREAD, SQL_TRANCAR_THREAD

#: Quanto se espera entre duas tentativas de tomar a tranca, em segundos.
#: *Proposta*. Sobe por recuo exponencial ate `ESPERA_MAXIMA_S`, para que uma
#: conversa a espera de um turno de 7 s nao faca 700 idas a base.
ESPERA_INICIAL_S: float = 0.01
ESPERA_MAXIMA_S: float = 0.5

#: Tecto de espera por uma tranca, em segundos. *Proposta*: tres vezes a espera
#: maxima do *shim* (`ESPERA_MAXIMA_MS`, 30 s), para que quem desiste seja o
#: `fetch` e nao isto — desistir aqui devolve o *job* a fila, que e o certo, mas
#: o tecto existe para que uma tranca que ficou presa por um defeito nao
#: prenda uma corrotina para sempre. Calibra-se em KAM-084.
ESPERA_TOTAL_MAXIMA_S: float = 90.0


class TrancaNaoObtidaError(RuntimeError):
    """Nao se conseguiu a tranca dentro de `ESPERA_TOTAL_MAXIMA_S`.

    O turno nao corre e a excepcao sobe: o *shim* ve 500 e devolve o *job* a
    fila, que e o comportamento certo — a mensagem nao se perde e a conversa que
    detem a tranca acaba o seu turno. Um tecto e nao uma espera sem fim porque
    uma tranca presa por um defeito (um *pooler* em modo transaccao, uma sessao
    orfa) prenderia a corrotina para sempre, e um pedido pendurado nao da erro.
    """


class TrancaNaoLargadaError(RuntimeError):
    """O `pg_advisory_unlock` devolveu `false`: esta sessao nao tinha a tranca.

    Nao se engole. Um `false` aqui quer dizer que o `trancar` e o `destrancar`
    correram em ligacoes **diferentes** — o sintoma exacto de um *pooler* em
    modo transaccao — ou que alguem largou a tranca por fora. Nos dois casos a
    exclusao mutua deixou de existir e o AGR esta a correr dois turnos sobre o
    mesmo *thread* sem o saber. Levanta-se para que apareca.
    """


class TrancaDeConversas:
    """A tranca por `thread_id`, sobre uma ligacao dedicada.

    `abrir_ligacao` e uma funcao sem argumentos que devolve uma ligacao DB-API
    em `autocommit`. E injectada, e nao construida aqui, pela razao do
    `consumo.py` do KAM-006: com o cliente injectado, a secção critica
    testa-se inteira sem PostgreSQL, e o que a *suite* do *gate* 8 prova e o que
    so a base pode provar.
    """

    def __init__(
        self,
        abrir_ligacao: Callable[[], Any],
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._abrir = abrir_ligacao
        self._agora = relogio
        self._ligacao: Any | None = None
        # Uma ligacao, uma `thread` de cada vez. O `pg8000` nao e seguro para
        # uso concorrente na mesma ligacao, e duas corrotinas a mandar
        # instrucoes pela mesma tomada entrelacam as respostas.
        self._exclusiva = asyncio.Lock()
        # **A exclusao dentro do processo, que a tranca da base nao da.** Ver a
        # secção «A tranca da base nao exclui dentro do processo» na *docstring*
        # do modulo. Um `asyncio.Lock` por `thread_id`, com contagem de quem
        # espera para que o dicionario nao cresca com as conversas que passaram.
        self._por_thread: dict[str, tuple[asyncio.Lock, list[int]]] = {}

    async def _executar(self, sql: str, thread_id: str) -> Any:
        async with self._exclusiva:
            return await asyncio.to_thread(self._sincrono, sql, thread_id)

    def _sincrono(self, sql: str, thread_id: str) -> Any:
        if self._ligacao is None:
            self._ligacao = self._abrir()
        try:
            cursor = self._ligacao.cursor()
            try:
                cursor.execute(sql, (thread_id,))
                linha = cursor.fetchone()
                return None if linha is None else linha[0]
            finally:
                cursor.close()
        except Exception:
            # **A ligacao morta larga-se.** Sem isto, um corte de rede ou um
            # reinicio do PostgreSQL deixava esta ligacao quebrada em
            # `self._ligacao` para sempre, e **todos** os turnos deste processo
            # falhavam a tomar a tranca ate alguem reiniciar o servico — um
            # defeito que nao da erro de arranque e que um teste de unidade nao
            # ve. Largando-a, a tentativa seguinte abre outra; e o *job* volta a
            # fila pelo caminho normal, porque a excepcao sobe.
            #
            # Largar a ligacao larga tambem as trancas que ela tivesse, o que e
            # o comportamento certo: se ela esta quebrada, a tranca dela nao
            # protege nada.
            ligacao, self._ligacao = self._ligacao, None
            if ligacao is not None:
                try:
                    ligacao.close()
                except Exception:  # noqa: BLE001 — ja esta quebrada
                    pass
            raise

    async def _esperar_pela_tranca(self, thread_id: str) -> None:
        """Tenta ate conseguir, largando o `asyncio.Lock` entre tentativas.

        **Espera**, nao desiste a primeira: o criterio 2 pede vinte turnos em
        serie com a ordem de chegada preservada, e desistir perdia turnos. O que
        mudou face a primeira versao e **onde** se espera: fora do
        `asyncio.Lock`, para que uma conversa a espera nao prenda as outras.
        """
        espera = ESPERA_INICIAL_S
        limite = self._agora() + ESPERA_TOTAL_MAXIMA_S
        while True:
            if await self._executar(SQL_TRANCAR_THREAD, thread_id) is True:
                return
            if self._agora() >= limite:
                raise TrancaNaoObtidaError("tranca_nao_obtida")
            await asyncio.sleep(espera)
            espera = min(espera * 2, ESPERA_MAXIMA_S)

    @contextlib.asynccontextmanager
    async def tomar(self, thread_id: str) -> AsyncIterator[None]:
        """Corre o bloco com a tranca de `thread_id` tomada.

        O `destrancar` corre no `finally` — mesmo com o turno a levantar. Se
        **ele** falhar, a tranca fica ate a ligacao morrer, o que e o
        comportamento certo: o processo que a tomou ja nao esta em condicoes de
        a largar, e a ligacao e o unico sinal honesto que resta.

        **Sao duas trancas e nao uma**, e a de dentro do processo vem primeiro:
        ver a secção «A tranca da base nao exclui dentro do processo» na
        *docstring* do modulo. A ordem importa — o `asyncio.Lock` antes da ida a
        base — porque assim so **uma** corrotina por `thread_id` chega ao
        `pg_try_advisory_lock`, que e precisamente a premissa que o
        `_esperar_pela_tranca` assume para nao haver duas tentativas da mesma
        chave a competir neste processo.
        """
        trinco = self._trinco_do_thread(thread_id)
        async with trinco:
            await self._esperar_pela_tranca(thread_id)
            try:
                yield
            finally:
                try:
                    largou = await self._executar(SQL_DESTRANCAR_THREAD, thread_id)
                finally:
                    self._largar_o_trinco(thread_id)
                if largou is False:
                    raise TrancaNaoLargadaError("tranca_nao_largada")

    def _trinco_do_thread(self, thread_id: str) -> asyncio.Lock:
        """O `asyncio.Lock` deste `thread_id`, criando-o a primeira vez.

        Conta quem espera, para que o dicionario nao cresca com as conversas que
        ja passaram: um `dict` de trincos sem limpeza e uma fuga de memoria
        proporcional ao numero de conversas distintas que o processo viu.

        Nao ha corrida na criacao: isto corre na *event loop*, sem `await` entre
        a leitura e a escrita.
        """
        entrada = self._por_thread.get(thread_id)
        if entrada is None:
            entrada = (asyncio.Lock(), [0])
            self._por_thread[thread_id] = entrada
        entrada[1][0] += 1
        return entrada[0]

    def _largar_o_trinco(self, thread_id: str) -> None:
        """Esquece o trinco quando ninguem mais o espera."""
        entrada = self._por_thread.get(thread_id)
        if entrada is None:
            return
        entrada[1][0] -= 1
        if entrada[1][0] <= 0:
            self._por_thread.pop(thread_id, None)

    async def fechar(self) -> None:
        """Fecha a ligacao dedicada, largando tudo o que ela tivesse.

        No encerramento ordenado do processo. Um `close` que levante nao impede
        o arranque de nada e nao se propaga: o que importa e que a tomada
        fecha, e uma tomada fechada larga as trancas de qualquer maneira.
        """
        async with self._exclusiva:
            ligacao, self._ligacao = self._ligacao, None
            if ligacao is None:
                return
            try:
                await asyncio.to_thread(ligacao.close)
            except Exception:  # noqa: BLE001 — ver docstring
                pass
