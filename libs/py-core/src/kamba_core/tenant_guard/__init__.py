"""Transaccoes com contexto de tenant (KAM-004, ADR-015).

A base tem RLS `FORCE` em todas as tabelas com `tenant_id`: sem contexto,
devolve zero linhas. Este modulo e a forma de **dar** esse contexto, e e a unica:

    with tx(conexao, tenant) as cursor:
        cursor.execute("SELECT ... FROM platform.tenant_channels")

`tx` executa `SELECT set_config('app.tenant_id', <tenant>, true)` — o equivalente
parametrizavel de `SET LOCAL` — no inicio da transaccao, confirma no fim e desfaz
em caso de erro. O terceiro argumento `true` e o que importa: o valor morre com a
transaccao, pelo que uma ligacao devolvida a um *pool* nao leva o contexto de um
tenant para o pedido seguinte. **Nunca** `SET` de sessao (`docs/tecnica/08` §3.3).

Tres recusas sobre o que se pede, todas antes de tocar na base:

- **Sem tenant** (`None` ou vazio): `ContextoEmFalta`, e conta em
  `rls_context_missing_total`. A base ja devolveria zero linhas; recusar aqui
  transforma um resultado vazio silencioso num erro com nome.
- **Tenant que nao e um UUID**: `TenantInvalido`. A base rebentaria no `::uuid`
  da politica; aqui a mensagem **nao** repete o valor recebido, porque um valor
  que nao e um UUID pode ser qualquer coisa — incluindo conteudo de um cliente.
- **Ligacao em `autocommit`**: `LigacaoEmAutocommit`. Em `autocommit` cada
  instrucao e a sua propria transaccao, e o `set_config(..., true)` expirava
  antes da consulta seguinte.

E uma quarta, que nao e sobre o que se pede mas sobre **onde**:

- **Ligacao ja dentro de uma transaccao deste modulo**: `LigacaoEmUso`. Um `tx`
  dentro de outro, na mesma ligacao, **nao** abre uma transaccao nova: o segundo
  `set_config` sobrepoe o primeiro, e o codigo de fora passa a ler as linhas do
  tenant de dentro — e o `commit` de dentro confirma o trabalho de fora. O mesmo
  vale para duas *threads* a partilhar uma ligacao. A revisao adversarial do
  KAM-004 reproduziu-o contra um PostgreSQL real. Reconhece-se o **mesmo
  objecto**; um *wrapper* diferente a volta da mesma ligacao nao e reconhecido —
  a regra e de quem chama (uma ligacao por pedido), e isto e a rede.

`tx_batch` e a outra porta, para o papel `kamba_batch` (`BYPASSRLS`): nao define
contexto, exige o **nome do job** e conta cada uso. «Jobs nomeados e auditados»
(doc 08 §3.3) comeca por nao haver forma de o usar sem dizer para que.

**O modulo nao regista nada.** Nem o tenant, nem a consulta, nem o erro: o DoD
proibe associar `tenant_id` a conteudo em *logs*, e a forma segura de o garantir
e nao escrever em *log* nenhum. Os contadores sao so numeros.

So depende da biblioteca padrao: recebe uma ligacao DB-API ja aberta.
"""

from __future__ import annotations

import contextlib
import re
import threading
import uuid

VARIAVEL = "app.tenant_id"

#: `set_config(nome, valor, is_local)`. Com `is_local = true` e um `SET LOCAL`.
SQL_DEFINIR_CONTEXTO = "SELECT set_config('app.tenant_id', %s, true)"

_NOME_DE_JOB = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


class ContextoEmFalta(RuntimeError):
    """Pediu-se uma transaccao de tenant sem dizer qual."""


class TenantInvalido(ValueError):
    """O tenant dado nao e um UUID. A mensagem nao repete o valor."""


class LigacaoEmAutocommit(RuntimeError):
    """Em `autocommit` o contexto expirava antes da primeira consulta."""


class LigacaoEmUso(RuntimeError):
    """A ligacao ja esta numa transaccao deste modulo (reentrancia ou partilha)."""


class JobSemNome(ValueError):
    """`tx_batch` exige o nome do job: e o que torna o uso auditavel."""


class Contadores:
    """Contadores em memoria, seguros entre *threads*. So numeros.

    Nao ha ainda pilha de metricas no repositorio; quando houver, e isto que ela
    le. Os nomes sao os do DoD do KAM-004.
    """

    def __init__(self) -> None:
        self._trinco = threading.Lock()
        self._valores: dict[str, int] = {}

    def incrementar(self, nome: str) -> None:
        with self._trinco:
            self._valores[nome] = self._valores.get(nome, 0) + 1

    def ler(self) -> dict[str, int]:
        with self._trinco:
            return dict(self._valores)

    def repor(self) -> None:
        with self._trinco:
            self._valores.clear()


CONTADORES = Contadores()

#: Transaccoes de tenant pedidas sem contexto (recusadas).
METRICA_SEM_CONTEXTO = "rls_context_missing_total"
#: Prefixo do contador de usos de `kamba_batch`; o sufixo e o nome do job.
METRICA_BATCH = "kamba_batch_tx_total"


def normalizar_tenant(tenant) -> str:
    """O tenant como texto canonico de UUID, ou levanta.

    Aceita `uuid.UUID` e a forma textual canonica. Nada mais: nem inteiros, nem
    *bytes*, nem a forma sem hifenes — duas escritas do mesmo tenant sao duas
    chaves de *cache* e dois valores de *log* diferentes mais adiante.
    """
    if tenant is None or tenant == "":
        CONTADORES.incrementar(METRICA_SEM_CONTEXTO)
        raise ContextoEmFalta(
            "transaccao de tenant sem tenant: a base devolveria zero linhas. "
            "Para trabalho sem contexto de tenant, `tx_batch` com o nome do job."
        )
    if isinstance(tenant, uuid.UUID):
        return str(tenant)
    if isinstance(tenant, str):
        try:
            canonico = str(uuid.UUID(tenant))
        except ValueError:
            canonico = None
        if canonico is not None and canonico == tenant.lower():
            return canonico
    raise TenantInvalido(
        f"o tenant tem de ser um UUID na forma canonica (recebido: "
        f"{type(tenant).__name__} com {len(str(tenant))} caracteres)"
    )


def _exigir_transaccional(conexao) -> None:
    if getattr(conexao, "autocommit", False):
        raise LigacaoEmAutocommit(
            "a ligacao esta em autocommit: `set_config(..., true)` expirava "
            "antes da consulta seguinte e a RLS devolvia zero linhas"
        )


#: Ligacoes com uma transaccao deste modulo aberta, por identidade do objecto.
_EM_USO: set[int] = set()
_TRINCO_EM_USO = threading.Lock()


@contextlib.contextmanager
def _exclusiva(conexao):
    """Reserva a ligacao ate a transaccao acabar; a segunda entrada levanta."""
    chave = id(conexao)
    with _TRINCO_EM_USO:
        if chave in _EM_USO:
            raise LigacaoEmUso(
                "esta ligacao ja esta dentro de uma transaccao de `tenant_guard`: "
                "uma segunda sobrepunha o contexto de tenant da primeira e "
                "confirmava o trabalho dela. Uma ligacao por pedido, e uma "
                "transaccao de cada vez por ligacao."
            )
        _EM_USO.add(chave)
    try:
        yield
    finally:
        with _TRINCO_EM_USO:
            _EM_USO.discard(chave)


@contextlib.contextmanager
def tx(conexao, tenant):
    """Transaccao com `app.tenant_id` definido. Devolve um cursor."""
    canonico = normalizar_tenant(tenant)
    _exigir_transaccional(conexao)
    with _exclusiva(conexao):
        cursor = conexao.cursor()
        try:
            cursor.execute(SQL_DEFINIR_CONTEXTO, (canonico,))
            cursor.fetchone()
            yield cursor
            conexao.commit()
        except BaseException:
            conexao.rollback()
            raise
        finally:
            cursor.close()


@contextlib.contextmanager
def tx_batch(conexao, job: str):
    """Transaccao **sem** contexto de tenant, para `kamba_batch`. Exige o job.

    Nao verifica o papel da ligacao: com outro papel a RLS devolve zero linhas,
    que e a falha certa. O que isto garante e que nao ha uso sem nome nem sem
    contagem.
    """
    if not isinstance(job, str) or not _NOME_DE_JOB.match(job):
        raise JobSemNome(
            "o job tem de ter um nome em minusculas e snake_case (3 a 63 "
            "caracteres): e ele que fica no registo de usos de `kamba_batch`"
        )
    _exigir_transaccional(conexao)
    with _exclusiva(conexao):
        CONTADORES.incrementar(f"{METRICA_BATCH}:{job}")
        cursor = conexao.cursor()
        try:
            yield cursor
            conexao.commit()
        except BaseException:
            conexao.rollback()
            raise
        finally:
            cursor.close()
