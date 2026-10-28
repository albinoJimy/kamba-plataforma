"""As ligacoes do AGR a base da plataforma (KAM-025, KAM-026, KAM-028 a KAM-034).

O AGR corre com **dois** papeis e abre **seis** ligacoes. Cinco sao do
`kamba_app` (`NOBYPASSRLS`, sem DDL) e nao sao cinco papeis: sao cinco usos que
nao podem partilhar uma tomada, porque o `kamba_core.tenant_guard` recusa uma
segunda transaccao na mesma ligacao. A sexta e de outro papel, e isso **e**
deliberado — ver `PAPEL_DO_CHECKPOINTER` mais abaixo.

| Ligacao | Papel | `autocommit` | Para que serve |
|---|---|---|---|
| leitura | `kamba_app` | nao | `conversations.mode` e `handoffs.status`, dentro de `tenant_guard.tx` |
| tranca | `kamba_app` | **sim** | so `pg_advisory_lock` / `pg_advisory_unlock` (`trancas.py`) |
| tools | `kamba_app` | nao | a ToolLayer: entitlement, backend `plataforma` e `tool_audit` (`tls/`) |
| llm | `kamba_app` | nao | so `dat.llm_call_log` (`llm/registo.py`) |
| handoff | `kamba_app` | nao | o CAS da retoma em `platform.handoffs` (`handoff/retoma.py`) |
| checkpoint | `kamba_agr` | nao | o esquema `lg`, e **nada** do `platform` (`checkpointer.py`) |

A varredura dos prazos do *handoff* **nao** esta na tabela, e nao e
esquecimento: ela atravessa *tenants*, corre como `kamba_batch`, e recebe a
ligacao de quem a chama — como o `retencao.varrer` do KAM-026. Nenhuma funcao
deste modulo abre uma ligacao de lote, para que o processo do AGR nao ganhe um
terceiro papel por causa de um trabalho que corre fora de qualquer pedido.

A das tools e uma tomada propria e nao a da leitura, e a razao e o
`kamba_core.tenant_guard`: ele **recusa** uma segunda transaccao na mesma
ligacao (`LigacaoEmUso`), e uma invocacao de tool abre tres em serie — o
entitlement, o backend e a auditoria. Partilhada com a leitura da palavra da
conversa, a primeira tool de um turno rebentava por uma razao que nao tem nada
a ver com ela.

A da tranca e `autocommit` porque a tranca e de **sessao** e nao de transaccao
(`docs/adr/ADR-L004-fila-e-tranca-do-agr.md`, Decisao 2): com `autocommit` cada
`SELECT` e a sua propria transaccao, a tranca sobrevive-lhe, e nao fica nada
aberto durante os segundos do turno. A de leitura **nao** pode ser `autocommit`,
e o `kamba_core.tenant_guard.tx` recusa-a se for — o `set_config(..., true)`
expirava antes da consulta seguinte, e a RLS devolvia zero linhas.

## Isto le as variaveis do `db/ligacao.py`; nao as define outra vez

Os nomes — `KAMBA_DB_HOST`, `KAMBA_DB_PORT`, `KAMBA_DB_NAME`, e as
palavras-passe em `KAMBA_SECRET_DB_APP_PASSWORD` e
`KAMBA_SECRET_DB_AGR_PASSWORD` — sao os de `db/ligacao.py` (KAM-003, KAM-026), e
os papeis sao os do dicionario §3.2. **Nao se inventa nome nenhum aqui**, e e
deliberado: um segundo conjunto de nomes para a mesma base era o defeito que o
§3.13 ja pagou a inventar `KAMBA_CHR_*_DB_URL`.

A regra nao e «nenhuma variavel nova» — e «nenhum nome que o `db/ligacao.py`
nao tenha». E por isso que o `test_nao_ha_variavel_nova_para_o_agr` compara o
conjunto com o `VARIAVEL_DA_SENHA` **dele** em vez de contar variaveis: um papel
novo passa, um nome inventado nao.

Porque e que ha codigo aqui, entao: o `db/ligacao.py` vive em `db/`, que nao e
um pacote instalado e nao esta no caminho de importacao de um servico. O que
impede as duas copias de divergirem e uma maquina, e nao uma intencao: o
`TestParidadeComODbLigacao` de `tests/test_ligacao.py` carrega o `db/ligacao.py`
pelo caminho e compara os nomes das variaveis e o nome do papel. E a mesma
resposta que o `ten/consultas.py` deu ao mesmo problema entre Python e
TypeScript.

## O `application_name`, que parece enfeite e nao e

As duas ligacoes identificam-se em `pg_stat_activity` (`kamba-agr:leitura` e
`kamba-agr:tranca`). E o que torna diagnosticavel o unico modo de falha serio
desta escolha: uma tranca presa aparece como uma sessao `kamba-agr:tranca` com
um `pg_locks` de tipo `advisory`, e sem o nome nao se distinguia das outras.

Nenhuma destas funcoes **imprime** a palavra-passe nem a devolve: a mensagem de
uma variavel em falta nomeia a variavel e nunca o valor, como em `db/ligacao.py`.
"""

from __future__ import annotations

import os
from typing import Any, Final

#: O papel com que o AGR corre. Dicionario §3.2.
PAPEL: Final = "kamba_app"

#: As variaveis que dizem onde esta a base. As de `db/ligacao.py`.
VAR_HOST: Final = "KAMBA_DB_HOST"
VAR_PORTA: Final = "KAMBA_DB_PORT"
VAR_BASE: Final = "KAMBA_DB_NAME"

#: A palavra-passe do `kamba_app`, no nome que o `EnvProvider` do KAM-010 le
#: (`KAMBA_SECRET_` + o `id` do inventario em maiusculas).
VAR_SENHA: Final = "KAMBA_SECRET_DB_APP_PASSWORD"

#: O papel do checkpointer, e **o segundo papel do AGR** (KAM-026). Dicionario
#: §3.2; criado pelo `db/bootstrap.py` como os outros seis.
#:
#: Sao dois papeis e nao um porque fazem coisas incompativeis. O `kamba_app` le
#: o `platform` e nao toca no `lg`; o `kamba_agr` escreve o `lg` e **nao tem
#: `USAGE` no `platform`** — e isso que o criterio 4 do KAM-026 pede, e e o que
#: faz do estado das conversas um compartimento: o codigo do checkpointer nao
#: tem por onde chegar aos `contacts`, haja o defeito que houver.
#:
#: Isto revoga em parte a nota do modulo acima, que foi escrita no KAM-025 e
#: dizia «nao se acrescenta variavel nenhuma para o AGR». O que ela recusava —
#: e bem — era um **segundo conjunto de nomes para a mesma coisa**
#: (`KAMBA_AGR_DB_URL` a duplicar o `KAMBA_DB_*`). Isto nao e isso: e a
#: palavra-passe de um papel novo, no mesmo esquema de nomes do
#: `db/ligacao.py`, que e quem continua a mandar nos nomes.
PAPEL_DO_CHECKPOINTER: Final = "kamba_agr"
VAR_SENHA_AGR: Final = "KAMBA_SECRET_DB_AGR_PASSWORD"

#: `application_name` de cada uso, para o `pg_stat_activity`.
NOME_DA_LEITURA: Final = "kamba-agr:leitura"
NOME_DA_TRANCA: Final = "kamba-agr:tranca"
NOME_DO_CHECKPOINTER: Final = "kamba-agr:checkpoint"
#: A quarta ligacao, da ToolLayer (KAM-028).
NOME_DAS_TOOLS: Final = "kamba-agr:tools"
#: A quinta, do gateway de LLM (KAM-030): so `dat.llm_call_log`.
NOME_DO_LLM: Final = "kamba-agr:llm"
#: A sexta, da retoma do *handoff* (KAM-034): so `platform.handoffs`.
NOME_DO_HANDOFF: Final = "kamba-agr:handoff"
#: A setima, da subscricao de eventos (KAM-038): `platform.events_consumed`,
#: `platform.events_dlq` e a leitura de `platform.conversations`.
NOME_DOS_EVENTOS: Final = "kamba-agr:eventos"
#: A oitava, do modo concierge (KAM-114): so `platform.draft_decisions`.
NOME_DO_CONCIERGE: Final = "kamba-agr:concierge"


class ConfiguracaoEmFalta(RuntimeError):
    """Falta uma variavel de ambiente. A mensagem diz qual; nunca um valor."""


def _exigir(nome: str, ambiente: Any) -> str:
    valor = ambiente.get(nome, "")
    if not valor:
        raise ConfiguracaoEmFalta(
            f"a variavel de ambiente {nome} nao esta definida (ou esta vazia)"
        )
    return valor


def _ligar(
    ambiente: Any,
    autocommit: bool,
    nome: str,
    papel: str = PAPEL,
    var_senha: str = VAR_SENHA,
) -> Any:
    import pg8000.dbapi

    ambiente = os.environ if ambiente is None else ambiente
    porta = ambiente.get(VAR_PORTA, "5432")
    if not porta.isdigit():
        raise ConfiguracaoEmFalta(f"{VAR_PORTA} tem de ser um numero de porta")
    ligacao = pg8000.dbapi.connect(
        user=papel,
        password=_exigir(var_senha, ambiente),
        host=ambiente.get(VAR_HOST, "127.0.0.1"),
        port=int(porta),
        database=_exigir(VAR_BASE, ambiente),
        application_name=nome,
    )
    ligacao.autocommit = autocommit
    return ligacao


def ligar_para_leitura(ambiente: Any = None) -> Any:
    """Ligacao transaccional, para usar **sempre** dentro de `tenant_guard.tx`."""
    return _ligar(ambiente, autocommit=False, nome=NOME_DA_LEITURA)


def ligar_para_tranca(ambiente: Any = None) -> Any:
    """A ligacao dedicada da tranca. `autocommit`, e so para `pg_advisory_*`.

    **Nao pode apontar para um *pooler* em modo transaccao.** Em modo
    transaccao a ligacao e devolvida ao *pool* entre instrucoes, e a tranca de
    sessao fica invisivel a quem a tomou e presa para quem vier a seguir — o
    unico modo de falha desta escolha que nao da erro nenhum (ADR-L004,
    Decisao 2). O `KAMBA_DB_HOST` do AGR aponta para a base.
    """
    return _ligar(ambiente, autocommit=True, nome=NOME_DA_TRANCA)


def ligar_para_tools(ambiente: Any = None) -> Any:
    """A ligacao da ToolLayer (KAM-028). Transaccional, papel `kamba_app`.

    `autocommit` **nao**, pela razao da leitura: tudo o que a camada faz na base
    corre dentro de `tenant_guard.tx`, que precisa de o `SET LOCAL
    app.tenant_id` sobreviver ate a consulta seguinte.

    Papel `kamba_app` e nao `kamba_agr`: o que ela toca e do `platform` — a
    `platform.entitlements` (passo 2), a `platform.tenants` (`get_store_info`) e
    a `platform.tool_audit` (passo 7) —, e o `kamba_agr` **nao tem `USAGE` no
    `platform`**, de proposito (KAM-026).
    """
    return _ligar(ambiente, autocommit=False, nome=NOME_DAS_TOOLS)


def ligar_para_llm(ambiente: Any = None) -> Any:
    """A ligacao do gateway de LLM (KAM-030). Transaccional, papel `kamba_app`.

    **A quinta tomada, e nao a das tools**, pela razao que a tabela deste modulo
    da para a das tools nao ser a da leitura: o `kamba_core.tenant_guard` recusa
    uma segunda transaccao na mesma ligacao (`LigacaoEmUso`), e uma chamada ao
    modelo acontece **dentro** de um no do grafo que pode ter uma invocacao de
    tool a meio. Partilhada, a linha de `dat.llm_call_log` rebentava por uma
    razao que nao tem nada a ver com ela — e e precisamente a linha que o
    criterio 5 exige que exista.

    Papel `kamba_app` e nao `kamba_agr`: o que ela toca e a `dat.llm_call_log`, e
    o `GRANT INSERT` por coluna da revisao `0023` e para o `kamba_app`. O
    `kamba_agr` nao ganha nada no `dat`, pela mesma razao por que nao tem `USAGE`
    no `platform` (KAM-026): o papel que guarda o estado das conversas nao tem
    por onde chegar ao custo de ninguem.
    """
    return _ligar(ambiente, autocommit=False, nome=NOME_DO_LLM)


def ligar_para_handoff(ambiente: Any = None) -> Any:
    """A ligacao da retoma do *handoff* (KAM-034). Transaccional, `kamba_app`.

    **A sexta tomada, e pela razao das duas anteriores**: o
    `kamba_core.tenant_guard` recusa uma segunda transaccao na mesma ligacao
    (`LigacaoEmUso`), e uma retoma corre **ao mesmo tempo** que turnos de outras
    conversas — a tranca serializa por `thread_id`, nao o processo. Partilhada
    com a leitura da palavra, um `/internal/resume` e um `/internal/turn`
    concorrentes rebentavam um ao outro.

    Papel `kamba_app` e nao `kamba_agr`: o que ela toca e a `platform.handoffs`
    (`UPDATE (status, resumed_at)`, revisao `0011`) e a `platform.conversations`
    (`SELECT`, para o vinculo ao *thread*), e o `kamba_agr` **nao tem `USAGE` no
    `platform`**, de proposito (KAM-026).

    A varredura dos prazos **nao** usa esta: atravessa *tenants*, corre como
    `kamba_batch`, e recebe a ligacao de quem a chama — como o
    `retencao.varrer` do KAM-026, e pela mesma razao. Dar ao processo do AGR um
    terceiro papel para uma varredura que corre fora de qualquer pedido era
    alargar o que o servico pode fazer pelo resto do tempo.
    """
    return _ligar(ambiente, autocommit=False, nome=NOME_DO_HANDOFF)


def ligar_para_eventos(ambiente: Any = None) -> Any:
    """A ligacao do consumidor de eventos (KAM-038). Transaccional, `kamba_app`.

    **A setima tomada, e pela razao das tres anteriores**: o
    `kamba_core.tenant_guard` recusa uma segunda transaccao na mesma ligacao
    (`LigacaoEmUso`), e um evento e consumido **ao mesmo tempo** que turnos de
    outras conversas — a tranca serializa por `thread_id`, nao o processo.

    Papel `kamba_app` e nao `kamba_agr`: o que ela toca e a
    `platform.events_consumed` (`SELECT, INSERT`), a `platform.events_dlq`
    (`INSERT`) e a `platform.conversations` (`SELECT`), e o `kamba_agr` **nao
    tem `USAGE` no `platform`**, de proposito (KAM-026). Os tres privilegios
    existem desde a revisao `0005` e a `0009`; nao ha migracao neste ticket.

    **Transaccional e nao `autocommit`**, apesar de o `consumir` do KAM-006
    mandar `BEGIN`, `COMMIT` e `ROLLBACK` como instrucoes: o
    `LigacaoDoConsumo` traduz as tres na API do condutor, e a razao esta na
    *docstring* dele — em `autocommit` o `tenant_guard.tx` recusava a ligacao, e
    a leitura da conversa e a entrada na DLQ precisam dele.
    """
    return _ligar(ambiente, autocommit=False, nome=NOME_DOS_EVENTOS)


def ligar_para_checkpoint(ambiente: Any = None) -> Any:
    """A ligacao do checkpointer, com o papel proprio (KAM-026).

    `autocommit` **nao**: o `_correr_sincrono` do `checkpointer.py` confirma
    cada instrucao, e um `aput` seguido de um `aput_writes` que falhasse a meio
    tem de deixar o checkpoint escrito — e a propria interface que o diz, ao
    separar os dois metodos.
    """
    return _ligar(
        ambiente,
        autocommit=False,
        nome=NOME_DO_CHECKPOINTER,
        papel=PAPEL_DO_CHECKPOINTER,
        var_senha=VAR_SENHA_AGR,
    )


def ligar_para_concierge(ambiente: Any = None) -> Any:
    """A ligacao do modo concierge (KAM-114). Transaccional, `kamba_app`.

    **A oitava tomada, e pela razao das quatro anteriores**: o
    `kamba_core.tenant_guard` recusa uma segunda transaccao na mesma ligacao
    (`LigacaoEmUso`), e uma decisao de rascunho corre **ao mesmo tempo** que
    turnos de outras conversas — a tranca serializa por `thread_id`, nao o
    processo.

    **E nao se partilha com a do `handoff`**, que e do mesmo papel e serviria em
    privilegio: um `/internal/draft-decision` e um `/internal/resume`
    concorrentes rebentavam um ao outro, e as duas rotas existem ao mesmo tempo.

    Papel `kamba_app`: o que ela toca e a `platform.draft_decisions`
    (`SELECT`, `INSERT` e `UPDATE` por coluna, revisao `0024`), e o `kamba_agr`
    **nao tem `USAGE` no `platform`**, de proposito (KAM-026).

    A varredura dos prazos **nao** usa esta: atravessa *tenants*, corre como
    `kamba_batch` e recebe a ligacao de quem a chama — a mesma linha que o
    `ligar_para_handoff` escreveu, e pela mesma razao.
    """
    return _ligar(ambiente, autocommit=False, nome=NOME_DO_CONCIERGE)
