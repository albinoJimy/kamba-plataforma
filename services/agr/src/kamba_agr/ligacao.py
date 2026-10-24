"""As duas ligacoes do AGR a base da plataforma (KAM-025).

O AGR corre com **um** papel, o `kamba_app` (`NOBYPASSRLS`, sem DDL), e abre
**duas** ligacoes com ele. Nao sao dois papeis: sao dois usos que nao podem
partilhar uma tomada.

| Ligacao | `autocommit` | Para que serve |
|---|---|---|
| leitura | nao | `conversations.mode` e `handoffs.status`, dentro de `tenant_guard.tx` |
| tranca | **sim** | so `pg_advisory_lock` / `pg_advisory_unlock` (`trancas.py`) |

A da tranca e `autocommit` porque a tranca e de **sessao** e nao de transaccao
(`docs/adr/ADR-L004-fila-e-tranca-do-agr.md`, Decisao 2): com `autocommit` cada
`SELECT` e a sua propria transaccao, a tranca sobrevive-lhe, e nao fica nada
aberto durante os segundos do turno. A de leitura **nao** pode ser `autocommit`,
e o `kamba_core.tenant_guard.tx` recusa-a se for — o `set_config(..., true)`
expirava antes da consulta seguinte, e a RLS devolvia zero linhas.

## Isto le as variaveis do `db/ligacao.py`; nao as define outra vez

Os nomes — `KAMBA_DB_HOST`, `KAMBA_DB_PORT`, `KAMBA_DB_NAME`, e a palavra-passe
em `KAMBA_SECRET_DB_APP_PASSWORD` — sao os de `db/ligacao.py` (KAM-003), e o
papel e o `kamba_app` do dicionario §3.2. **Nao se acrescenta variavel nenhuma
para o AGR**, e e deliberado: um segundo conjunto de nomes para a mesma base
era o defeito que o §3.13 ja pagou a inventar `KAMBA_CHR_*_DB_URL`.

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

#: `application_name` de cada uso, para o `pg_stat_activity`.
NOME_DA_LEITURA: Final = "kamba-agr:leitura"
NOME_DA_TRANCA: Final = "kamba-agr:tranca"


class ConfiguracaoEmFalta(RuntimeError):
    """Falta uma variavel de ambiente. A mensagem diz qual; nunca um valor."""


def _exigir(nome: str, ambiente: Any) -> str:
    valor = ambiente.get(nome, "")
    if not valor:
        raise ConfiguracaoEmFalta(
            f"a variavel de ambiente {nome} nao esta definida (ou esta vazia)"
        )
    return valor


def _ligar(ambiente: Any, autocommit: bool, nome: str) -> Any:
    import pg8000.dbapi

    ambiente = os.environ if ambiente is None else ambiente
    porta = ambiente.get(VAR_PORTA, "5432")
    if not porta.isdigit():
        raise ConfiguracaoEmFalta(f"{VAR_PORTA} tem de ser um numero de porta")
    ligacao = pg8000.dbapi.connect(
        user=PAPEL,
        password=_exigir(VAR_SENHA, ambiente),
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
