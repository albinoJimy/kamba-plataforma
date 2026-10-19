"""Base da suite do uso: tenants semeados e confirmados, e a regra chamada como a aplicacao.

O que esta suite prova e a **funcao** `platform.ten_consumir` (revisao 0007,
KAM-009) — nao o esquema, que tem prova propria em `db/tests/`, nem a politica
de RLS, que o gate 6 descobre pelo catalogo. Sao coisas diferentes e a
diferenca importa: a funcao e `SECURITY INVOKER`, pelo que corre com os
privilegios e com a RLS **de quem a chama**, e nenhum teste de catalogo diz o
que ela faz quando quem chama e outro tenant.

## Porque e que as sementes sao confirmadas

O criterio 3 do bloco pede mil chamadas **paralelas**. Paralelas quer dizer
ligacoes diferentes, e uma ligacao nao ve o que outra ainda nao confirmou: um
tenant semeado numa transaccao aberta era invisivel as mil, e as mil negavam
todas por falta de entitlement — com a suite verde e sem nada provado. Por
isso as sementes vao por uma ligacao de administrador em `autocommit`, e cada
teste apaga o que semeou.

O administrador e nao o `kamba_batch` por uma razao so: as receitas nao
definem contexto, e o `kamba_batch` e `BYPASSRLS` mas nao escapa ao `WITH
CHECK` de uma politica quando a sessao tem contexto de outro tenant. O
administrador da instancia contorna a RLS sempre, e o que se semeia aqui nao
e o que se esta a provar.

## O SQL e o das bibliotecas, e nao uma copia dele

Esta suite escrevia o seu proprio `SELECT … FROM platform.ten_consumir(…)`.
A revisao adversarial apanhou o que isso escondia: **o SQL das bibliotecas
nunca corria contra uma base**, e o `SQL_PERIODO` tinha um defeito real — sem
`coalesce`, `periodo()` sem instante devolvia `NULL`, o Python devolvia `None`
em silencio e o TypeScript levantava. Dois modulos escritos para nao
divergirem tinham uma divergencia que ninguem media.

Por isso importam-se as constantes de `kamba_core.ten.consultas`, que e o
espelho verificado do `packages/core-ts/src/ten/consultas.ts`: o que o gate 8
exercita contra PostgreSQL passa a ser **o texto que a biblioteca envia**. O
`sys.path` segue o precedente do `db/tests/test_arranque_fluxo_b.py`, que ja
importa de `libs/py-core/src`.

## Porque e que o `p_agora` passa por `coalesce`

A assinatura tem `p_agora timestamptz DEFAULT now()`, e um `NULL` explicito
**nao** e o mesmo que a omissao: `date_trunc('month', NULL)` e `NULL`, o
periodo sai nulo e a insercao morre num `NOT NULL` que nao tem nada a ver com
o que o teste queria dizer. O `coalesce(%s, now())` do `SQL_CONSUMIR` deixa o
mesmo chamador pedir as duas coisas. Quem prova que a **omissao** tambem
funciona e `test_tecto.TestAssinatura`, que chama a funcao com quatro
argumentos.

## E porque e que a fronteira de mes corre como `kamba_batch`

Desde a revisao adversarial, `p_agora` so aponta para outro periodo quando
quem chama e `kamba_batch`: `kamba_app` tem `EXECUTE` na assinatura de seis
argumentos, e um instante do ano passado dava-lhe um balde vazio por cada mes
do calendario. Os testes de relogio fixo passam a pedir `papel="batch"`, e ha
um teste que prova que a aplicacao e **recusada** no mesmo instante
(`test_fronteira_de_mes.TestORelogioSoSeFixaDeRetaguarda`).
"""

from __future__ import annotations

import collections
import sys
import uuid
from pathlib import Path

import pg8000.dbapi

import ligacao
from tests import factories
from tests.base import ComBase, sqlstate

#: O mesmo caminho que o `db/tests/test_arranque_fluxo_b.py` usa.
_PY_CORE = Path(__file__).resolve().parents[2] / "libs" / "py-core" / "src"
if str(_PY_CORE) not in sys.path:
    sys.path.insert(0, str(_PY_CORE))

from kamba_core.ten.consultas import SQL_CONSUMIR, SQL_PERIODO  # noqa: E402

__all__ = ["AUTO", "CHAVE", "SQL_CONSUMIR", "SQL_PERIODO", "Consumo", "ComUso"]

#: A chave de limite destes testes. E uma das do registo do ticket, e cumpre o
#: `CHECK (chave_limite ~ '^[a-z][a-z0-9_]*$')` das duas tabelas.
CHAVE = "msgs_ai_mes"

#: Uma segunda chave, de outra especie: um tecto por pedido, e nao um balde
#: por mes. Existe aqui para o caso que a revisao adversarial mediu — a mesma
#: chave de idempotencia a atravessar duas chaves de limite.
CHAVE_DE_DINHEIRO = "valor_max_pedido_minor"

#: O que a funcao devolve, com nome em vez de posicao.
Consumo = collections.namedtuple("Consumo", "aceite valor repetido limite")


#: «Gera uma chave nova». Nao e `None`: `None` e a chave **nula**, que e um
#: caso que os testes querem poder pedir desde a revisao adversarial.
AUTO = object()


def consumir(
    cursor,
    tenant: str,
    *,
    chave: str = CHAVE,
    quantidade: int = 1,
    idempotency_key=AUTO,
    limite: int | None = None,
    agora: str | None = None,
) -> Consumo:
    """Uma chamada a `platform.ten_consumir`, no cursor dado.

    Sem `idempotency_key`, gera-se uma unica: quase todos os testes querem uma
    chamada nova, e uma chave repetida por descuido lia-se como idempotencia a
    funcionar quando era o teste a enganar-se. `idempotency_key=None` passa
    **`NULL`**, que e outra coisa.
    """
    if idempotency_key is AUTO:
        idempotency_key = f"ensaio-{uuid.uuid4().hex}"
    cursor.execute(
        SQL_CONSUMIR, (tenant, chave, quantidade, idempotency_key, limite, agora)
    )
    return Consumo(*cursor.fetchone())


class ComUso(ComBase):
    """Tenants com entitlements, semeados e confirmados; apagados no fim.

    **Cada consumo confirma.** O que se le a seguir — o contador, o livro — le-se
    pela ligacao de administrador, que e outra ligacao: sem `commit`, lia o
    estado anterior e o teste afirmava sobre o nada. Confirmar tambem e o que
    as mil paralelas fazem, pelo que os dois caminhos exercitam o mesmo.

    A limpeza apaga o que ficou confirmado, por tenant e pela ordem das chaves
    estrangeiras.
    """

    def setUp(self) -> None:
        super().setUp()
        self._admin = ligacao.ligar("admin")
        self._admin.autocommit = True
        self.semente = self._admin.cursor()
        self._tenants: list[str] = []
        #: `(uso, contexto)` -> ligacao. Duas por contexto, no maximo: a que
        #: confirma (`consumir`) e a que fica aberta (`cursor_app`).
        self._app: dict[tuple[str, str], object] = {}
        self.addCleanup(self._limpar)

    def _limpar(self) -> None:
        """Pela ordem das chaves estrangeiras, e com a ligacao fechada no fim."""
        try:
            for tenant in self._tenants:
                for tabela in ("usage_ledger", "tenant_usage", "entitlements"):
                    self.semente.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s", (tenant,)
                    )
                self.semente.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
        finally:
            self._admin.close()

    # ------------------------------------------------------------- sementes

    def criar_tenant(self) -> str:
        """Um tenant confirmado, sem entitlement nenhum."""
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        return tenant

    def dar_entitlement(
        self,
        tenant: str,
        limites: dict,
        *,
        modulo: str = "catalogo",
        ativo: bool = True,
    ) -> None:
        factories.entitlement(
            self.semente, tenant, modulo=modulo, limites=limites, ativo=ativo
        )

    def tenant_com_limite(self, limite: int, *, chave: str = CHAVE) -> str:
        """O caso comum: um tenant, um modulo activo, um tecto."""
        tenant = self.criar_tenant()
        self.dar_entitlement(tenant, {chave: limite})
        return tenant

    # -------------------------------------------------------------- ligacao

    def cursor_app(self, tenant: str | None):
        """Cursor de `kamba_app` com o contexto pedido (ou sem nenhum).

        `kamba_app` e `NOBYPASSRLS`: e com ele que a funcao corre em producao,
        e so com ele e que o teste de isolamento quer dizer alguma coisa.

        A transaccao fica **aberta**: e este o cursor de quem escreve SQL a
        mao e espera que ele falhe (o `assertErroSql` precisa de um
        `SAVEPOINT`, que so existe dentro de uma transaccao). Quem consome usa
        o `consumir()` da classe, que confirma.
        """
        conexao = self._app.get(("cru", tenant or ""))
        if conexao is None:
            conexao = self.ligar("app")
            self._app[("cru", tenant or "")] = conexao
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant or "",))
        cursor.fetchone()
        return cursor

    #: Sentinela para «o contexto e o do proprio `p_tenant`». `None` nao serve:
    #: ausencia de contexto e um caso que os testes querem pedir.
    PROPRIO = object()

    def consumir(
        self,
        tenant: str,
        *,
        contexto=PROPRIO,
        fuso: str | None = None,
        papel: str = "app",
        **argumentos,
    ) -> Consumo:
        """Chama a `ten_consumir` e **confirma**. Por omissao, como `kamba_app`.

        `contexto` e o tenant que fica em `app.tenant_id`; por omissao e o
        proprio `p_tenant`, que e o caso normal. Os testes de isolamento
        passam outro — ou `None`, para nenhum.

        `papel` existe por causa da guarda do `p_agora`: desde a revisao
        adversarial so o `kamba_batch` fixa o relogio para outro periodo.
        Quem passa `agora=` de outro mes tem de passar tambem
        `papel="batch"`, e quem nao passa continua a correr como a aplicacao
        — que e o papel em que tudo o resto desta suite tem de valer.

        `fuso` poe o `TimeZone` da **sessao** antes da chamada, e so para esta
        transaccao: e o que permite perguntar se o periodo depende de quem
        liga. O nome e validado contra o catalogo de fusos do servidor, porque
        entra em SQL por interpolacao (o `SET` nao aceita parametro).
        """
        alvo = tenant if contexto is self.PROPRIO else contexto
        conexao = self._app.get((papel, alvo or ""))
        if conexao is None:
            conexao = self.ligar(papel)
            self._app[(papel, alvo or "")] = conexao
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (alvo or "",))
        cursor.fetchone()
        if fuso is not None:
            cursor.execute("SELECT count(*) FROM pg_timezone_names WHERE name = %s",
                           (fuso,))
            if int(cursor.fetchone()[0]) != 1:
                raise AssertionError(f"fuso desconhecido no servidor: {fuso!r}")
            cursor.execute(f"SET LOCAL TimeZone = '{fuso}'")
        try:
            resultado = consumir(cursor, tenant, **argumentos)
        except Exception:
            # Sem `SAVEPOINT`: o que falhou aqui nao deixa nada meio escrito —
            # a funcao e atomica — e a transaccao desta chamada acaba aqui.
            conexao.rollback()
            raise
        conexao.commit()
        return resultado

    def assertConsumoLevanta(self, esperado: str, tenant: str, **argumentos):
        """A chamada tem de falhar, e com o SQLSTATE esperado.

        Os codigos que a `ten_consumir` levanta de proposito: `23514` para
        uma quantidade nao positiva ou uma chave de idempotencia vazia,
        `22023` para um instante fora do periodo corrente ou um limite nao
        inteiro em `entitlements`, e `KA002` para a mesma chave repetida com
        outra quantidade.
        """
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self.consumir(tenant, **argumentos)
        self.assertEqual(
            sqlstate(capturado.exception),
            esperado,
            f"falhou, mas nao pela razao esperada: {capturado.exception}",
        )
        return capturado.exception

    # ------------------------------------------------------------- leituras

    def uso(self, tenant: str, *, chave: str = CHAVE, periodo: str | None = None) -> int:
        """O contador, lido pelo administrador. `0` quando a linha nao existe."""
        if periodo is None:
            self.semente.execute(
                "SELECT coalesce(sum(valor), 0) FROM platform.tenant_usage "
                " WHERE tenant_id = %s AND chave_limite = %s",
                (tenant, chave),
            )
        else:
            self.semente.execute(
                "SELECT coalesce(sum(valor), 0) FROM platform.tenant_usage "
                " WHERE tenant_id = %s AND chave_limite = %s AND periodo = %s::date",
                (tenant, chave, periodo),
            )
        return int(self.semente.fetchone()[0])

    def periodos(self, tenant: str) -> list[tuple[str, int]]:
        """`(periodo, valor)` de cada linha do contador, por ordem de periodo."""
        self.semente.execute(
            "SELECT periodo::text, valor FROM platform.tenant_usage "
            " WHERE tenant_id = %s ORDER BY periodo",
            (tenant,),
        )
        return [(str(p), int(v)) for p, v in self.semente.fetchall()]

    def livro(self, tenant: str) -> list[tuple[str, str, str, int]]:
        """`(idempotency_key, chave_limite, periodo, quantidade)` do livro.

        A `chave_limite` esta aqui desde que entrou na chave primaria: sem ela
        o que o teste le nao distingue duas entradas que a base distingue.
        """
        self.semente.execute(
            "SELECT idempotency_key, chave_limite, periodo::text, quantidade "
            "  FROM platform.usage_ledger WHERE tenant_id = %s "
            " ORDER BY idempotency_key, chave_limite",
            (tenant,),
        )
        return [
            (str(k), str(c), str(p), int(q)) for k, c, p, q in self.semente.fetchall()
        ]

    def no_livro(self, tenant: str, idempotency_key: str, chave: str = CHAVE) -> bool:
        self.semente.execute(
            "SELECT count(*) FROM platform.usage_ledger "
            " WHERE tenant_id = %s AND idempotency_key = %s AND chave_limite = %s",
            (tenant, idempotency_key, chave),
        )
        return int(self.semente.fetchone()[0]) > 0
