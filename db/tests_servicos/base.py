"""Base da suite da agenda: tenants, servicos e recursos semeados e confirmados.

O que esta suite prova e o **esquema `servicos`** da revisao `0025` (KAM-047) —
em particular a restricao de exclusao `bookings_sem_sobreposicao`, que e a
barreira do criterio 1. Nao prova o catalogo nem a RLS, que tem prova propria em
`db/tests/` e no X-05 do *gate* 6.

## Porque e que as sementes sao confirmadas

O criterio 1 pede mil tentativas **concorrentes**. Concorrentes quer dizer
ligacoes diferentes, e uma ligacao nao ve o que outra ainda nao confirmou: um
servico semeado numa transaccao aberta era invisivel as mil, e as mil falhavam
todas na chave estrangeira — com a suite verde e sem nada provado. E a mesma
licao que o `db/tests_ten/base.py` escreveu para o KAM-009.

Por isso as sementes vao por ligacoes em `autocommit`, e cada teste apaga o que
semeou.

## Suite propria, e nao dentro de `tests`

Pela razao do `tests_ten` e do `tests_auditoria_carga`: as mil paralelas custam
relogio, e uma suite custa isso por cada mutacao que a escolha. O criterio 1
mede-se aqui; o inventario, os privilegios e a cadeia medem-se na suite `tests`.

## O SQL e o do modulo, e nao uma copia dele

As consultas que esta suite exercita **sao as do modulo**, e nao uma copia
delas: o `tests_servicos/consultas.py` le o ficheiro
`services/com/src/servicos/consultas.ts` e extrai as constantes, convertendo so o
estilo do parametro (`$n` -> `%s`). Se alguem alterar uma consulta la, o que esta
suite corre muda com ela; numa copia, ficava verde sobre texto que ja ninguem
enviava — que e exactamente o defeito que a revisao adversarial do KAM-009
encontrou no `SQL_PERIODO`.

E ha um teste que fecha a outra metade: o
`test_contrato.TestOContratoComOModulo` confronta o conjunto de consultas do
modulo com o `EXERCITADAS` **nos dois sentidos** e corre cada uma contra a base.
Sem ele, uma consulta nova entrava sem ninguem a exercitar — e foi assim que o
`SQL_GRELHA` chegou com um defeito que nenhuma bateria tocava.
"""

from __future__ import annotations

import datetime
import uuid

import ligacao
from tests import factories
from tests.base import ComBase

#: O servico de ensaio: meia hora, sem preco (o unico par que o
#: `services_preco_ck` aceita sem numero).
DURACAO_MIN = 30

#: O TTL do hold, em minutos. **Proposta** (critério 3), e esta aqui porque e o
#: modulo que o escolhe e nao o DDL — ver `TTL_DO_HOLD_MS` em
#: `services/com/src/servicos/contrato.ts`.
TTL_DO_HOLD_MIN = 10


class ComAgenda(ComBase):
    """Um tenant com um servico e um recurso, semeados e confirmados.

    A limpeza apaga pela ordem das chaves estrangeiras — `bookings` e
    `availability_rules` antes de `resources` e `services` —, que e a mesma
    ordem inversa do `ORDEM` de `db/tests_isolamento/sementes.py` e pela mesma
    razao: nenhuma FK apaga em cascata, de proposito.
    """

    def setUp(self) -> None:
        super().setUp()
        self._admin = ligacao.ligar("admin")
        self._admin.autocommit = True
        self.semente = self._admin.cursor()
        self._tenants: list[str] = []
        self._app: dict[str, object] = {}
        self.addCleanup(self._limpar)

    def _limpar(self) -> None:
        try:
            for tenant in self._tenants:
                for tabela in (
                    "servicos.bookings",
                    "servicos.availability_rules",
                    "servicos.resources",
                    "servicos.services",
                ):
                    self.semente.execute(
                        f"DELETE FROM {tabela} WHERE tenant_id = %s", (tenant,)
                    )
                for tabela in ("usage_ledger", "tenant_usage", "entitlements"):
                    self.semente.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s",
                        (tenant,),
                    )
                self.semente.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
        finally:
            # **Só a de administrador.** As de `self._app` vêm do
            # `ComBase.ligar`, que as registra e as fecha no `tearDown` — e os
            # `addCleanup` correm **depois** dele, pelo que fechá-las aqui
            # levantava `InterfaceError: connection is closed`. Medido: vinte e
            # três erros, todos nesta linha, e nenhum deles no que os testes
            # mediam. A de administrador é aberta por `ligacao.ligar` directo
            # (precisa de `autocommit`), não está nesse registo, e é esta que
            # tem de ser fechada aqui.
            self._admin.close()

    # ------------------------------------------------------------- sementes

    def criar_tenant(self) -> str:
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        return tenant

    def criar_servico(self, tenant: str, *, duracao_min: int = DURACAO_MIN) -> str:
        self.semente.execute(
            "INSERT INTO servicos.services "
            "(tenant_id, nome, duracao_min, preco_tipo) "
            "VALUES (%s, %s, %s, 'sob_consulta') RETURNING service_id",
            (tenant, f"ensaio-{uuid.uuid4().hex[:8]}", duracao_min),
        )
        return str(self.semente.fetchone()[0])

    def criar_recurso(self, tenant: str) -> str:
        self.semente.execute(
            "INSERT INTO servicos.resources (tenant_id, nome) "
            "VALUES (%s, %s) RETURNING resource_id",
            (tenant, f"recurso-{uuid.uuid4().hex[:8]}"),
        )
        return str(self.semente.fetchone()[0])

    def criar_agenda(self, *, duracao_min: int = DURACAO_MIN) -> tuple[str, str, str]:
        """`(tenant, service_id, resource_id)`, o caso comum."""
        tenant = self.criar_tenant()
        return tenant, self.criar_servico(tenant, duracao_min=duracao_min), (
            self.criar_recurso(tenant)
        )

    def dar_entitlement(
        self, tenant: str, limite: int, *, chave: str = "marcacoes_mes"
    ) -> None:
        factories.entitlement(
            self.semente, tenant, modulo="servicos", limites={chave: limite}
        )

    # -------------------------------------------------------------- ligacao

    def cursor_app(self, tenant: str | None, *, papel: str = "app"):
        """Cursor do papel pedido com o contexto dado (ou sem nenhum).

        `kamba_app` e `NOBYPASSRLS`: e com ele que o modulo corre em producao, e
        so com ele e que um teste de isolamento quer dizer alguma coisa. A
        transaccao fica **aberta**, porque o `assertErroSql` precisa de um
        `SAVEPOINT`.
        """
        chave = f"{papel}:{tenant or ''}"
        conexao = self._app.get(chave)
        if conexao is None:
            conexao = self.ligar(papel)
            self._app[chave] = conexao
        cursor = conexao.cursor()  # type: ignore[attr-defined]
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant or "",))
        cursor.fetchone()
        return cursor

    # ------------------------------------------------------------- leituras

    def marcacoes(self, tenant: str) -> list[tuple[str, str]]:
        """`(estado, slot_id)` de cada linha do tenant, lidas pelo administrador."""
        self.semente.execute(
            "SELECT estado, slot_id FROM servicos.bookings "
            " WHERE tenant_id = %s ORDER BY criado_at, booking_id",
            (tenant,),
        )
        return [(str(e), str(s)) for e, s in self.semente.fetchall()]

    def contar(self, tenant: str, *estados: str) -> int:
        self.semente.execute(
            "SELECT count(*) FROM servicos.bookings "
            " WHERE tenant_id = %s AND estado = ANY(%s)",
            (tenant, list(estados)),
        )
        return int(self.semente.fetchone()[0])

    def eventos(self, tenant: str, tipo: str) -> list[dict]:
        """Os envelopes de um tipo no outbox deste tenant, pela ordem de sequencia."""
        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox "
            " WHERE tenant_id = %s AND tipo = %s ORDER BY agregado_seq, event_id",
            (tenant, tipo),
        )
        import json

        return [
            linha[0] if isinstance(linha[0], dict) else json.loads(linha[0])
            for linha in self.semente.fetchall()
        ]


def prazo_do_hold(minutos: int = TTL_DO_HOLD_MIN):
    """O `hold_expires_at` de um hold novo, como `datetime` com fuso.

    O TTL e do **modulo** e nao do DDL (`TTL_DO_HOLD_MS` em
    `services/com/src/servicos/contrato.ts`), e por isso entra como argumento do
    `SQL_CRIAR_HOLD` em vez de um `now() + interval` escrito na consulta: um
    numero no SQL obrigava a uma revisao de base de dados para o calibrar, e ele
    e *proposta*.
    """
    return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=minutos
    )


def intervalo(minutos_a_partir_de_agora: int, duracao_min: int = DURACAO_MIN):
    """Um intervalo futuro, como par de `datetime` com fuso.

    Futuro porque uma marcacao no passado nao se marca, e com fuso porque o
    `timestamptz` sem fuso herda o `TimeZone` da sessao — e duas sessoes com
    `TimeZone` diferente escreviam instantes diferentes para o mesmo texto.
    """
    inicio = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=minutos_a_partir_de_agora
    )
    return inicio, inicio + datetime.timedelta(minutes=duracao_min)
