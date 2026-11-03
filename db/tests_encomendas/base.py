"""Base da suite das encomendas: tenants, contactos e encomendas semeadas.

O que esta suite prova e a **revisao `0030`** (KAM-044) — o grafo e o *trigger*
que o impoe, o CAS por `version`, o *trigger* diferido que exige o registo e a
autenticidade de `paga`, a imutabilidade do `lines_snapshot`, o `numero_publico`,
a RLS `FORCE` com o registo *append-only*, e as cinco regras da reconciliacao do
lado da base — e as consultas de `services/com/src/orders/consultas.ts`, lidas de
la.

**Nao prova** as funcoes puras do modulo: o predicado do grafo em TypeScript, os
payloads dos eventos e as cinco regras da reconciliacao sobre duas fotografias
medem-se em `services/com/tests/orders.*.test.ts`, sem base de dados. Medir aqui
o que nao precisa de PostgreSQL era pagar o preco de uma suite por asercoes que
correm em microssegundos.

## Porque e que as sementes sao confirmadas

Pela razao do `db/tests_produtos/base.py` e do `db/tests_pagamentos/base.py`: uma
ligacao nao ve o que outra ainda nao confirmou. As vinte transicoes concorrentes
do criterio 2 correm em vinte ligacoes proprias, e uma encomenda semeada dentro
de uma transaccao aberta era **invisivel** para as vinte — com a suite verde e
nada provado.

Por isso as sementes vao por uma ligacao de administrador em `autocommit`, e cada
teste apaga o que semeou.

## Sao **duas** ligacoes de administrador, e a razao custou 109 erros

A `semente` corre em `autocommit`: cada instrucao e a sua propria transaccao, o
que e o que faz a semente visivel as outras ligacoes — e o que torna
`SAVEPOINT` **impossivel** nela (`25P01: SAVEPOINT can only be used in
transaction blocks`).

A `ensaio` nao: e nela que corre tudo o que tem de ser **uma** transaccao, e a
transicao e o caso central. Em `autocommit`, o `UPDATE` do estado e o `INSERT`
no registo sao duas transaccoes, e o `CONSTRAINT TRIGGER` diferido corre no fim
da primeira — onde o registo ainda nao existe. A primeira versao desta base
semeava assim e a suite deu **67 `KA005`**: o *trigger* estava certo e a semente
errada, e e por isso que a nota esta aqui e nao no `docs`.

`SET CONSTRAINTS ALL IMMEDIATE` e **ALL** e nao pelo nome: `SET CONSTRAINTS
order_estado_exige_log IMMEDIATE` procura a restricao no `search_path`, e a
tabela esta em `platform` — medido, `42704 constraint does not exist` vinte e
tres vezes.

## O `order_state_log` nao se apaga, e e por desenho

O `deny_mutation` da `0029`, ligado a esta tabela pela `0030`, recusa `UPDATE`,
`DELETE` e `TRUNCATE` **a todos** — incluindo ao superutilizador que semeia. Um
registo *append-only* que o teste conseguisse apagar nao era *append-only*, e e
a mesma licao que o `db/tests_produtos/base.py` escreveu para a `audit_log`.

A limpeza nao o tenta: apaga a **encomenda**, e a FK composta do registo recusa
isso enquanto houver linhas. Por isso a ordem e `order_state_log` nunca,
`orders_mirror` so quando nao transitou, e o tenant por ultimo — na pratica, cada
teste cria o seu tenant, todas as leituras filtram por ele, e a base do *gate* 8
e descartavel.
"""

from __future__ import annotations

import json
import uuid

import ligacao
import pg8000.dbapi
from tests import factories
from tests.base import ComBase, sqlstate

#: O total de uma encomenda de teste: 12 500 Kz em unidade menor.
TOTAL = 1_250_000

#: O tecto manual do tenant de ensaio: 50 000 Kz em unidade menor, que e o
#: valor do exemplo de `docs/tecnica/03` secao 5.2. Acima do `TOTAL`, para que
#: a guarda do `pendente_confirmacao` deixe passar o caso comum.
TECTO_MANUAL = 5_000_000

#: O SQLSTATE da guarda do tecto manual.
TECTO_MANUAL_EXCEDIDO = "KA007"

#: As linhas de uma encomenda de teste, na forma do §5.4.
LINHAS = [
    {
        "sku": "arroz-5kg",
        "nome": "Arroz 5 kg",
        "qty": 1,
        "preco_minor": TOTAL,
        "preco_tipo": "fixo",
        "origem_preco": "offer_terms",
    }
]

#: Os **doze** estados do dicionario §3.3, que e o dominio do `CHECK`.
ESTADOS = (
    "criada",
    "aguarda_pagamento",
    "pendente_confirmacao",
    "paga",
    "expirada",
    "em_entrega",
    "entrega_falhada",
    "entregue",
    "em_disputa",
    "reembolso_pendente",
    "reembolsada",
    "cancelada",
)

#: As **doze** transicoes do nucleo, com a bandeira de cada uma. A copia e
#: deliberada e o `test_grafo` compara-a com a tabela nos dois sentidos: e a
#: unica forma de um ensaio dizer «o grafo e este» em vez de «o grafo e o que a
#: base tem».
NUCLEO = {
    ("criada", "aguarda_pagamento"): None,
    ("criada", "cancelada"): None,
    ("aguarda_pagamento", "paga"): None,
    ("aguarda_pagamento", "pendente_confirmacao"): None,
    ("aguarda_pagamento", "expirada"): None,
    ("pendente_confirmacao", "paga"): None,
    ("pendente_confirmacao", "aguarda_pagamento"): None,
    ("expirada", "aguarda_pagamento"): None,
    ("expirada", "cancelada"): None,
    ("paga", "entregue"): None,
    ("paga", "em_entrega"): "COM_DELIVERY_ENABLED",
    ("em_entrega", "entregue"): "COM_DELIVERY_ENABLED",
}

#: A variavel de sessao que liga a entrega.
GUC_DA_ENTREGA = "app.com_delivery_enabled"

#: Os SQLSTATE da revisao `0030`.
TRANSICAO_INVALIDA = "KA003"
SNAPSHOT_IMUTAVEL = "KA004"
REGISTO_EM_FALTA = "KA005"
PAGA_SEM_EVENTO = "KA006"

#: As duas causas autenticadas do §12 que levam a `paga`.
CAUSA_PROVIDER = "payment.confirmed"
CAUSA_MANUAL = "payment.manual_confirmed"


class ComEncomendas(ComBase):
    """Um tenant com contacto e encomendas, semeadas e confirmadas."""

    def setUp(self) -> None:
        super().setUp()
        self._admin = ligacao.ligar("admin")
        self._admin.autocommit = True
        self.semente = self._admin.cursor()
        # A segunda: transaccional, para o que tem de ser **uma** transaccao.
        # Ver a nota do modulo.
        self._ensaio = ligacao.ligar("admin")
        self.ensaio = self._ensaio.cursor()
        self._tenants: list[str] = []
        self.addCleanup(self._limpar)

    def _limpar(self) -> None:
        try:
            for tenant in self._tenants:
                # Pela ordem inversa das FK. O `order_state_log` **nao** se
                # apaga (ver a nota do modulo), pelo que as encomendas que
                # transitaram ficam — e com elas o tenant, cuja FK as recusa
                # apagar. Nao acumula lixo que conte: a base e descartavel e
                # cada teste tem o seu tenant.
                for tabela in (
                    "order_reconciliation_issues",
                    "order_intents",
                    "events_outbox",
                    # O entitlement do tecto manual, que o `criar_tenant`
                    # semeia: a FK dele recusa apagar o tenant enquanto ele
                    # existir, e foi isso que a terceira corrida da suite
                    # mediu — 36 erros, **todos** na limpeza.
                    "entitlements",
                ):
                    self.semente.execute(
                        f"DELETE FROM platform.{tabela} WHERE tenant_id = %s",
                        (tenant,),
                    )
                self.semente.execute(
                    "DELETE FROM platform.orders_mirror WHERE tenant_id = %s "
                    "  AND id NOT IN (SELECT order_id FROM platform.order_state_log "
                    "                  WHERE tenant_id = %s)",
                    (tenant, tenant),
                )
                self.semente.execute(
                    "DELETE FROM platform.contacts WHERE tenant_id = %s AND "
                    "contact_id NOT IN (SELECT contact_id FROM platform.orders_mirror "
                    "                    WHERE tenant_id = %s)",
                    (tenant, tenant),
                )
                self.semente.execute(
                    "DELETE FROM platform.tenants WHERE id = %s AND id NOT IN "
                    "(SELECT tenant_id FROM platform.orders_mirror)",
                    (tenant,),
                )
        finally:
            # **So as de administrador.** As de `ComBase.ligar` sao fechadas pelo
            # `tearDown`, e os `addCleanup` correm **depois** dele: fecha-las
            # aqui levantava `InterfaceError: connection is closed`.
            try:
                self._ensaio.rollback()
            except Exception:  # noqa: BLE001 — uma ligacao ja fechada nao e um erro aqui
                pass
            self._ensaio.close()
            self._admin.close()

    # --------------------------------------------------------------- sementes

    def criar_tenant(self, *, tecto_manual: int | None = TECTO_MANUAL) -> str:
        """Um tenant, com o entitlement do tecto manual se `tecto_manual` vier.

        **O entitlement nao e enfeite:** a guarda do `pendente_confirmacao`
        (§6.2) le `manual_max_minor` por `platform.ten_tecto`, e sem linha
        activa que declare a chave a funcao devolve `NULL` e o *trigger* recusa
        — que e a falha fechada do criterio 2 do KAM-009. Um tenant sem
        entitlement obtem-se com `tecto_manual=None`, e e com ele que o
        `test_pagamento` mede a recusa.
        """
        tenant = factories.tenant(self.semente)
        self._tenants.append(tenant)
        if tecto_manual is not None:
            # O `limites` vai como **`dict`**: a fabrica serializa-o e diz o
            # tipo (`::jsonb`), porque uma cadeia enviada como parametro chega
            # ao PostgreSQL como `text` e `text` nao se converte sozinho.
            factories.entitlement(
                self.semente,
                tenant,
                modulo="pagamentos",
                limites={"manual_max_minor": tecto_manual},
            )
        return tenant

    def criar_contacto(self, tenant: str) -> str:
        return factories.contacto(self.semente, tenant)

    def criar_encomenda(
        self,
        tenant: str,
        contacto: str | None = None,
        *,
        total: int = TOTAL,
        linhas: list | None = None,
        **campos,
    ) -> str:
        """Insere uma encomenda em `criada` e devolve o `id`.

        O `numero_publico` **nao** se passa: e a omissao da coluna, que e o
        `platform.order_numero_publico()`. Passa-lo aqui era o ensaio a provar
        um numero que ele proprio escolheu.
        """
        valores = {
            "tenant_id": tenant,
            "contact_id": contacto if contacto is not None else self.criar_contacto(tenant),
            "intent_key": f"ik-{uuid.uuid4().hex[:16]}",
            "total_minor": total,
            "lines_snapshot": json.dumps(LINHAS if linhas is None else linhas),
        }
        valores.update(campos)
        colunas = ", ".join(valores)
        marcadores = ", ".join("%s" for _ in valores)
        self.semente.execute(
            f"INSERT INTO platform.orders_mirror ({colunas}) "
            f"VALUES ({marcadores}) RETURNING id",
            tuple(valores.values()),
        )
        return str(self.semente.fetchone()[0])

    def levar_a(self, tenant: str, encomenda: str, estado: str) -> int:
        """Leva a encomenda ate um estado pelo caminho do grafo, e devolve a versao.

        Semeia **pelo caminho legitimo** — CAS mais registo, como o modulo faz —
        e nao com um `UPDATE` directo: o *trigger* diferido recusava o directo,
        e um ensaio que semeasse por um caminho que a base recusa estava a
        provar outra coisa.
        """
        caminhos = {
            "aguarda_pagamento": [("criada", "aguarda_pagamento", "charge.issued")],
            "pendente_confirmacao": [
                ("criada", "aguarda_pagamento", "charge.issued"),
                ("aguarda_pagamento", "pendente_confirmacao", "dono_declara"),
            ],
            "paga": [
                ("criada", "aguarda_pagamento", "charge.issued"),
                ("aguarda_pagamento", "paga", CAUSA_PROVIDER),
            ],
            "expirada": [
                ("criada", "aguarda_pagamento", "charge.issued"),
                ("aguarda_pagamento", "expirada", "ttl"),
            ],
            "cancelada": [("criada", "cancelada", "cliente_cancela")],
        }
        if estado == "criada":
            return 1
        versao = 1
        for de, para, causa in caminhos[estado]:
            versao = self.transitar(tenant, encomenda, de, para, versao, causa)
        return versao

    def transitar(
        self,
        tenant: str,
        encomenda: str,
        de: str,
        para: str,
        versao: int,
        causa: str,
        *,
        actor_kind: str | None = None,
        evento_id: str | None = None,
        cursor=None,
        confirmar: bool = True,
    ) -> int:
        """Uma transicao pelo caminho do modulo: CAS, registo, na mesma transaccao.

        Corre na ligacao **transaccional** (ver a nota do modulo) e confirma no
        fim: e o `COMMIT` que faz o *trigger* diferido correr, e por isso o
        `confirmar` nao e uma conveniencia — e o que torna a semente igual ao
        caminho real.

        Devolve a versao nova. Levanta se o CAS nao escrever linha nenhuma — num
        ensaio de semente isso e um defeito do ensaio e nao um conflito.
        """
        alvo = self.ensaio if cursor is None else cursor
        if actor_kind is None:
            actor_kind = "sistema" if para == "paga" else "ops"
        if evento_id is None and para == "paga":
            evento_id = f"evt-{uuid.uuid4().hex[:12]}"
        alvo.execute(
            "UPDATE platform.orders_mirror "
            "   SET estado = %s, version = version + 1, atualizado_at = now(), "
            "       paga_at = CASE WHEN %s = 'paga' THEN now() ELSE paga_at END, "
            "       paga_via = CASE WHEN %s = 'paga' THEN %s ELSE paga_via END, "
            "       entregue_at = CASE WHEN %s = 'entregue' THEN now() "
            "                          ELSE entregue_at END, "
            "       entrega_confirmada_por = CASE WHEN %s = 'entregue' THEN 'cliente' "
            "                                     ELSE entrega_confirmada_por END, "
            "       expira_at = COALESCE(expira_at, now() + interval '48 hours') "
            " WHERE tenant_id = %s AND id = %s AND version = %s AND estado = %s "
            "RETURNING version",
            (
                para,
                para,
                para,
                "provider_autenticado" if causa == CAUSA_PROVIDER else "manual_auditado",
                para,
                para,
                tenant,
                encomenda,
                versao,
                de,
            ),
        )
        linha = alvo.fetchone()
        if linha is None:
            raise AssertionError(
                f"a semente nao conseguiu transitar {de} -> {para} na versao {versao}"
            )
        nova = int(linha[0])
        alvo.execute(
            "INSERT INTO platform.order_state_log "
            "       (tenant_id, order_id, de, para, version, causa, evento_id, "
            "        actor_kind, actor_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (tenant, encomenda, de, para, nova, causa, evento_id, actor_kind, "ops-1"),
        )
        if confirmar and cursor is None:
            self._ensaio.commit()
        return nova

    def tentar_transicao(
        self,
        tenant: str,
        encomenda: str,
        de: str,
        para: str,
        versao: int,
        causa: str,
        **campos,
    ) -> str | None:
        """Tenta a transicao e devolve o SQLSTATE da recusa, ou `None`.

        **O `COMMIT` esta aqui dentro de proposito**: e nele que o *trigger*
        diferido corre, e um ensaio que nao confirmasse media so as barreiras
        imediatas — o grafo e os `CHECK` — e dava verde a uma transicao que a
        base recusaria no fim.
        """
        try:
            self.transitar(tenant, encomenda, de, para, versao, causa, **campos)
            return None
        except pg8000.dbapi.DatabaseError as erro:
            self._ensaio.rollback()
            return sqlstate(erro)

    def tentar(self, sql: str, parametros: tuple = ()) -> str | None:
        """Corre uma instrucao na ligacao transaccional e confirma, ou devolve o
        SQLSTATE da recusa.

        Sem `SAVEPOINT`: a ligacao da semente e `autocommit` e nao os aceita, e
        esta e transaccional — um `rollback` desfaz o que a instrucao tentou.
        """
        try:
            self.ensaio.execute(sql, parametros)
            self._ensaio.commit()
            return None
        except pg8000.dbapi.DatabaseError as erro:
            self._ensaio.rollback()
            return sqlstate(erro)

    # ---------------------------------------------------------------- leituras

    def estado_de(self, encomenda: str) -> tuple[str, int]:
        self.semente.execute(
            "SELECT estado, version FROM platform.orders_mirror WHERE id = %s",
            (encomenda,),
        )
        estado, versao = self.semente.fetchone()
        return str(estado), int(versao)

    def ligar_app(self, tenant: str):
        """Uma ligacao como `kamba_app`, com o contexto do tenant posto."""
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        cursor.fetchone()
        return conexao, cursor
