"""O checkpointer do AGR sobre `pg8000` (KAM-026).

## Porque e que este codigo existe, em vez do `AsyncPostgresSaver`

O `docs/tecnica/02` §12 nomeia o `langgraph-checkpoint-postgres` 3.1.2, e o `E4`
§2.6 da-o como «MIT | SIM, sem restricoes». O pacote e MIT; **o fecho dele nao
e**. Medido contra o PyPI, nao de memoria:

    langgraph-checkpoint-postgres 3.1.2   MIT
      -> psycopg >= 3.2.0                 LGPL-3.0-only
      -> psycopg-pool >= 3.2.0            LGPL-3.0-only

O `ci/licenses.yaml` nega o prefixo `LGPL`, e este repositorio ja recusou o
`psycopg` pelo nome duas vezes por escrito — `db/requirements/migrations.in`
(KAM-003) tem a tabela com a medicao, e o `runtime.in` deste servico repete-a.
Emendar a politica pede dois revisores (DoD do KAM-002), que esta fase nao tem.

O que se usa e o `langgraph-checkpoint` (MIT, fecho de 36 pacotes sem nenhuma
licenca negada): dele vem a **interface** — `BaseCheckpointSaver` — e o
**serializador**, que e a parte dificil e a que nao se reescreve. O que fica
nosso e o SQL, em `consultas.py`, sobre o `pg8000` que e o driver de toda a casa.

## Sincrono por dentro, assincrono por fora

O `pg8000` e sincrono e o AGR e assincrono. A travessia e a mesma que o
`conversa.py` do KAM-025 escreveu: `asyncio.to_thread`. Nao se inventa aqui um
segundo padrao para o mesmo problema.

## Uma ligacao e uma tranca, e nao um *pool*

O bloco pede «pool dedicado». O `pg8000` nao tem um, e duas corrotinas a usar a
mesma ligacao ao mesmo tempo corrompem o protocolo — pelo que ou ha uma ligacao
por chamada, ou ha exclusao. Escolhe-se a exclusao: uma ligacao, um
`asyncio.Lock`, tres linhas.

shortcut: o `asyncio.Lock` serializa o I/O de checkpoints de **todas** as
conversas; a 0,05-0,15 s por escrita (`docs/tecnica/02` §15.1) chega para o
Piloto. Trocar por um *pool* quando a tranca aparecer como espera no
`checkpoint_latency`, nao antes.

## O que este checkpointer **nao** implementa, e porque

O `BaseCheckpointSaver` levanta `NotImplementedError` no que nao se sobrepoe, e
isso e o comportamento certo: melhor levantar do que devolver um estado errado
em silencio.

- **`aprune` (a poda «ultimos N» do criterio 8).** A propria interface avisa que
  um `keep_latest` ingenuo corta a cadeia de um canal `DeltaChannel` e que o
  valor «would silently reconstruct as empty (no error raised)». Ela nomeia como
  opcao segura «skip pruning threads whose graph uses `DeltaChannel`» — e hoje
  **nao existe grafo nenhum**, pelo que nao ha como saber quais usam. Quem
  decide isso e o KAM-031. A metade do criterio 8 que a lei pede — apagar o que
  esta inactivo — faz-se com `adelete_thread`, e essa nao tem este perigo.
- **`acopy_thread` (a fusao de contactos).** O `docs/tecnica/02` §12 diz que a
  fusao migra o *thread*, e o §12 do `docs/tecnica/01` repete-o. Nenhum criterio
  deste bloco o pede, e quem funde contactos e o modulo de identidade noutro
  processo. Fica para quem tiver o gancho.
- **`aget_delta_channel_history`.** Depende do `checkpoint_blobs` que esta
  esquema nao tem, pela razao escrita na revisao `0020`.
- **Os metodos sincronos** (`get_tuple`, `put`, ...). O AGR so chama os
  assincronos. Um grafo sincrono levanta, e levanta a dizer o que falta.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any, Final

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

from . import consultas

#: Quantas mensagens a janela recortada do estado pode levar, alem do `summary`
#: (`docs/tecnica/02` §12: «ultimas K, K a calibrar»).
#:
#: **20 e *proposta*, nao medicao.** O desenho nao lhe da valor e nao ha
#: conversa real para medir. Vinte sao cerca de dez trocas, que e o que uma
#: compra por WhatsApp leva antes de o `summary` passar a valer mais do que o
#: detalhe. Calibra-se em dois sitios: no *golden* do KAM-040, que mede se a
#: resposta piora com menos, e no `llm_call_log` do KAM-030, que mede o que cada
#: mensagem a mais custa.
JANELA_MAXIMA: Final = 20

#: O *namespace* do grafo de topo. O LangGraph passa cadeia vazia quando nao ha
#: subgrafo, e a coluna tem `DEFAULT ''` por isso.
NS_DE_TOPO: Final = ""


class JanelaExcedidaError(RuntimeError):
    """O estado a persistir tem mais mensagens do que a janela admite.

    Levanta em vez de recortar. Recortar aqui era o `checkpointer` a decidir o
    que o grafo guarda: o estado em memoria do grafo passava a divergir do que
    esta na base, e a leitura seguinte devolvia menos mensagens do que a
    execucao escreveu — sem erro nenhum. O recorte e do `ingest` (KAM-031), e
    `estado.recortar_janela` e a funcao que ele chama.
    """


class CheckpointerDoAgr(BaseCheckpointSaver[int]):
    """O `BaseCheckpointSaver` do AGR, com o SQL de `consultas.py`.

    Parametrizado em `int` e nao em `str`: o `get_next_version` da interface tem
    implementacao por omissao com versoes inteiras e **levanta** se a versao for
    uma cadeia. Em inteiros nao se sobrepoe nada.
    """

    def __init__(self, ligacao: Any, *, serde: Any = None) -> None:
        super().__init__(serde=serde)
        self._ligacao = ligacao
        self._tranca = asyncio.Lock()

    # -- leitura ------------------------------------------------------------

    async def aget_tuple(self, config: Any) -> CheckpointTuple | None:
        thread_id, ns, checkpoint_id = _coordenadas(config)
        if checkpoint_id is None:
            linhas = await self._correr(
                consultas.SQL_CHECKPOINT_RECENTE, (thread_id, ns)
            )
        else:
            linhas = await self._correr(
                consultas.SQL_CHECKPOINT_POR_ID, (thread_id, ns, checkpoint_id)
            )
        if not linhas:
            return None
        return await self._montar(thread_id, ns, linhas[0])

    async def alist(
        self,
        config: Any | None,
        *,
        filter: dict[str, Any] | None = None,
        before: Any | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        # **Um filtro de metadados levanta, nao se ignora.** Os metadados estao
        # serializados numa coluna `bytea` e nao em `jsonb`, pelo que nao ha
        # como filtrar por eles em SQL. Ignorar o argumento devolvia o historico
        # inteiro a quem pediu um pedaco — a resposta errada sem erro, que e
        # pior do que a excepcao.
        if filter:
            raise NotImplementedError(
                "alist com filtro de metadados: os metadados estao em bytea, "
                "nao em jsonb"
            )
        thread_id, ns, _ = _coordenadas(config)
        antes = _coordenadas(before)[2] if before is not None else None
        linhas = await self._correr(
            consultas.SQL_LISTAR_CHECKPOINTS,
            (thread_id, ns, antes, antes, limit if limit is not None else 100),
        )
        for linha in linhas:
            yield await self._montar(thread_id, ns, linha)

    # -- escrita ------------------------------------------------------------

    async def aput(
        self,
        config: Any,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> Any:
        thread_id, ns, pai = _coordenadas(config)
        _exigir_janela(checkpoint)
        tipo, octetos = self.serde.dumps_typed(checkpoint)
        tipo_meta, octetos_meta = self.serde.dumps_typed(metadata)
        await self._correr(
            consultas.SQL_GRAVAR_CHECKPOINT,
            (
                thread_id,
                ns,
                checkpoint["id"],
                pai,
                tipo,
                octetos,
                tipo_meta,
                octetos_meta,
            ),
        )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: Any,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id, ns, checkpoint_id = _coordenadas(config)
        if checkpoint_id is None:
            raise ValueError("aput_writes sem checkpoint_id no config")
        for idx, (channel, valor) in enumerate(writes):
            tipo, octetos = self.serde.dumps_typed(valor)
            await self._correr(
                consultas.SQL_GRAVAR_ESCRITA,
                (
                    thread_id,
                    ns,
                    checkpoint_id,
                    task_id,
                    task_path,
                    idx,
                    channel,
                    tipo,
                    octetos,
                ),
            )

    def fechar(self) -> None:
        """Larga a ligacao. Corre no `lifespan`, como o `trancas.fechar`.

        Tem chamador de proposito: o `TrancaDeConversas.fechar` do KAM-025
        existiu sem um e foi achado critico da revisao adversarial. Uma tomada
        que nao fecha fica no servidor ate ele notar, e as que o AGR abre sao
        poucas e longas.
        """
        self._ligacao.close()

    async def adelete_thread(self, thread_id: str) -> None:
        # As escritas primeiro: na ordem inversa, uma falha entre as duas
        # deixava escritas sem o checkpoint que as explica.
        await self._correr(consultas.SQL_APAGAR_ESCRITAS_DA_THREAD, (thread_id,))
        await self._correr(consultas.SQL_APAGAR_CHECKPOINTS_DA_THREAD, (thread_id,))

    # -- base ---------------------------------------------------------------

    async def _correr(self, sql: str, parametros: tuple[Any, ...]) -> list[list[Any]]:
        async with self._tranca:
            return await asyncio.to_thread(self._correr_sincrono, sql, parametros)

    def _correr_sincrono(
        self, sql: str, parametros: tuple[Any, ...]
    ) -> list[list[Any]]:
        cursor = self._ligacao.cursor()
        try:
            cursor.execute(sql, parametros)
            # O `pg8000` levanta em `fetchall()` numa instrucao sem resultado,
            # e um `DELETE` nao tem. O `description` e `None` nessas.
            linhas = list(cursor.fetchall()) if cursor.description else []
        finally:
            cursor.close()
        self._ligacao.commit()
        return linhas

    async def _montar(
        self, thread_id: str, ns: str, linha: Sequence[Any]
    ) -> CheckpointTuple:
        checkpoint_id, pai, tipo, octetos, tipo_meta, octetos_meta = linha
        escritas = await self._correr(
            consultas.SQL_ESCRITAS_PENDENTES, (thread_id, ns, checkpoint_id)
        )
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=self.serde.loads_typed((tipo, bytes(octetos))),
            metadata=self.serde.loads_typed((tipo_meta, bytes(octetos_meta))),
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": ns,
                        "checkpoint_id": pai,
                    }
                }
                if pai is not None
                else None
            ),
            pending_writes=[
                (task_id, channel, self.serde.loads_typed((t, bytes(b))))
                for task_id, channel, t, b in escritas
            ],
        )


def _coordenadas(config: Any) -> tuple[str, str, str | None]:
    """O `(thread_id, checkpoint_ns, checkpoint_id)` de um `RunnableConfig`.

    Um `config` sem `thread_id` levanta: e o que o proprio
    `BaseCheckpointSaver` diz na docstring — «Without it, the checkpointer
    cannot save state» —, e um checkpointer que aceitasse a ausencia gravava o
    estado de uma conversa debaixo do de outra.
    """
    configuravel = (config or {}).get("configurable") or {}
    thread_id = configuravel.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("config sem `thread_id`")
    ns = configuravel.get("checkpoint_ns") or NS_DE_TOPO
    checkpoint_id = configuravel.get("checkpoint_id")
    return thread_id, ns, checkpoint_id


def _exigir_janela(checkpoint: Checkpoint) -> None:
    mensagens = (checkpoint.get("channel_values") or {}).get("messages")
    if isinstance(mensagens, list) and len(mensagens) > JANELA_MAXIMA:
        raise JanelaExcedidaError(
            f"{len(mensagens)} mensagens, janela de {JANELA_MAXIMA}"
        )
