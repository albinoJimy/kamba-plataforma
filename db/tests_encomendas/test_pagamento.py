"""Criterio 3: `paga` so por evento autenticado do PAY, com actor `sistema`.

O que so aqui se prova, e nenhum duplo de teste pode: que a barreira esta na
**base** e nao no modulo. Uma verificacao em TypeScript cobre a via que passa
pelo TypeScript; o DoD diz «nenhuma via leva a `paga` sem evento ou confirmacao
manual auditada», e «nenhuma» inclui um `UPDATE` a mao de quem tem o privilegio
e um `INSERT` que nasca ja pago.

## As quatro vias, e o que recusa cada uma

```text
transicao com actor `dono`/`agente`   trigger diferido, KA006
transicao sem `evento_id`             trigger diferido, KA006
transicao com causa que nao e do PAY  trigger diferido, KA006
`INSERT` directo em `paga`            trigger `order_nasce_criada`, KA003
`UPDATE` de estado sem registo        trigger diferido, KA005
`paga` sem `paga_via` das duas        CHECK `orders_mirror_paga_exige_via_ck`
```

A quinta via e a que o KAM-053 ensinou a procurar («ha outro caminho que escreva
`paga`?»), e a resposta desta revisao e o `order_nasce_criada`: o §6.2 tem uma
seta de entrada so.

## O *trigger* e diferido, e os ensaios tem de o acordar

Um `CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED` corre no `COMMIT`. Os
ensaios usam `SET CONSTRAINTS order_estado_exige_log IMMEDIATE`, que o passa a
correr no fim da instrucao — e o mesmo corpo, no mesmo lugar, sem precisar de
confirmar a transaccao e de a limpar depois. O
`test_diferido_a_falha_aparece_no_commit_e_nao_antes` mede o modo **real**, com
`COMMIT`, para que o modo imediato dos outros nao seja a unica coisa medida.
"""

from __future__ import annotations

import uuid

import pg8000.dbapi
from tests import factories
from tests.base import VIOLACAO_DE_CHECK, sqlstate
from tests_encomendas.base import (
    CAUSA_MANUAL,
    CAUSA_PROVIDER,
    PAGA_SEM_EVENTO,
    REGISTO_EM_FALTA,
    TECTO_MANUAL,
    TECTO_MANUAL_EXCEDIDO,
    TRANSICAO_INVALIDA,
    ComEncomendas,
)



class TestPagaExigeEventoAutenticado(ComEncomendas):
    """Criterio 3, nos dois sentidos."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()

    def _encomenda_a_aguardar(self) -> tuple[str, int]:
        encomenda = self.criar_encomenda(self.tenant)
        versao = self.levar_a(self.tenant, encomenda, "aguarda_pagamento")
        return encomenda, versao

    def test_com_evento_do_provider_e_actor_sistema_passa(self) -> None:
        encomenda, versao = self._encomenda_a_aguardar()
        self.transitar(
            self.tenant,
            encomenda,
            "aguarda_pagamento",
            "paga",
            versao,
            CAUSA_PROVIDER,
            actor_kind="sistema",
            evento_id=f"evt-{uuid.uuid4().hex[:12]}",
        )
        self.assertEqual(self.estado_de(encomenda), ("paga", 3))
        self.assertEqual(
            self.consultar(
                "SELECT paga_via, paga_at IS NOT NULL FROM platform.orders_mirror "
                "WHERE id = %s",
                (encomenda,),
            ),
            [("provider_autenticado", True)],
        )

    def test_com_confirmacao_manual_auditada_passa(self) -> None:
        """A segunda via do criterio 3, pelo `pendente_confirmacao`."""
        encomenda = self.criar_encomenda(self.tenant)
        versao = self.levar_a(self.tenant, encomenda, "pendente_confirmacao")
        self.transitar(
            self.tenant,
            encomenda,
            "pendente_confirmacao",
            "paga",
            versao,
            CAUSA_MANUAL,
            actor_kind="sistema",
            evento_id=f"evt-{uuid.uuid4().hex[:12]}",
        )
        self.assertEqual(
            self.consultar(
                "SELECT paga_via FROM platform.orders_mirror WHERE id = %s",
                (encomenda,),
            ),
            [("manual_auditado",)],
        )

    def test_actor_dono_sem_evento_e_recusado(self) -> None:
        """O criterio 3 a letra: «actor `agente` ou `dono` sem evento e recusado»."""
        encomenda, versao = self._encomenda_a_aguardar()
        self.assertEqual(
            self.tentar_transicao(
                    self.tenant,
                    encomenda,
                    "aguarda_pagamento",
                    "paga",
                    versao,
                    "dono_declara",
                    actor_kind="dono",
                    evento_id=None,
            ),
            PAGA_SEM_EVENTO,
        )

    def test_actor_agente_mesmo_com_evento_e_recusado(self) -> None:
        """**Com** evento tambem: quem fala pelo PAY e o `sistema`.

        A primeira versao deste ensaio so media «sem evento», que e o que o
        criterio escreve. Com evento e actor `agente` passava — e isso era um
        agente a declarar um pagamento autenticado, que e precisamente o que o
        ADR-013 recusa.
        """
        encomenda, versao = self._encomenda_a_aguardar()
        self.assertEqual(
            self.tentar_transicao(
                    self.tenant,
                    encomenda,
                    "aguarda_pagamento",
                    "paga",
                    versao,
                    CAUSA_PROVIDER,
                    actor_kind="agente",
                    evento_id=f"evt-{uuid.uuid4().hex[:12]}",
            ),
            PAGA_SEM_EVENTO,
        )

    def test_sistema_com_causa_que_nao_e_do_pay_e_recusado(self) -> None:
        """Nem a reconciliacao escreve `paga`: o espelho nao se auto-autoriza."""
        encomenda, versao = self._encomenda_a_aguardar()
        self.assertEqual(
            self.tentar_transicao(
                    self.tenant,
                    encomenda,
                    "aguarda_pagamento",
                    "paga",
                    versao,
                    "reconciliacao",
                    actor_kind="sistema",
                    evento_id=f"evt-{uuid.uuid4().hex[:12]}",
            ),
            PAGA_SEM_EVENTO,
        )

    def test_sistema_com_evento_vazio_e_recusado(self) -> None:
        """Texto em branco nao e um `evento_id`: o *trigger* faz `btrim`."""
        encomenda, versao = self._encomenda_a_aguardar()
        self.assertEqual(
            self.tentar_transicao(
                    self.tenant,
                    encomenda,
                    "aguarda_pagamento",
                    "paga",
                    versao,
                    CAUSA_PROVIDER,
                    actor_kind="sistema",
                    evento_id="   ",
            ),
            PAGA_SEM_EVENTO,
        )

    def test_paga_sem_via_das_duas_e_recusado_pelo_check(self) -> None:
        """A barreira da **coluna**, que corre antes do *trigger*.

        O `cod_manual` esta no dominio da coluna (§5.4) e **nao** no `CHECK` do
        estado: nenhuma transicao do nucleo o escreve.
        """
        encomenda, versao = self._encomenda_a_aguardar()
        self.assertEqual(
            self.tentar(
                "UPDATE platform.orders_mirror SET estado = 'paga', "
                "       version = version + 1, paga_at = now(), "
                "       paga_via = 'cod_manual' "
                " WHERE tenant_id = %s AND id = %s AND version = %s",
                (self.tenant, encomenda, versao),
            ),
            VIOLACAO_DE_CHECK,
            "`paga` com `cod_manual` nao passa o CHECK do estado",
        )


class TestGuardaDoTectoManual(ComEncomendas):
    """A guarda do `pendente_confirmacao` (§6.2), nos dois sentidos.

    «`total_minor <= limite_manual` do tenant», e o limite lê-se de
    `platform.ten_tecto(tenant, 'manual_max_minor')` — a função da revisão
    `0007` que o `checkCeiling` do `packages/core-ts/src/ten` já usa, e **não**
    um caminho novo. O que ela devolve é o mínimo entre os módulos activos que
    declaram a chave, e `NULL` quando nenhum a declara.
    """

    def test_abaixo_do_tecto_passa(self) -> None:
        tenant = self.criar_tenant(tecto_manual=TECTO_MANUAL)
        encomenda = self.criar_encomenda(tenant, total=TECTO_MANUAL - 1)
        versao = self.levar_a(tenant, encomenda, "aguarda_pagamento")
        self.assertIsNone(
            self.tentar_transicao(
                tenant,
                encomenda,
                "aguarda_pagamento",
                "pendente_confirmacao",
                versao,
                "dono_declara",
                actor_kind="dono",
            )
        )

    def test_exactamente_no_tecto_passa(self) -> None:
        """`<=` e nao `<`: o §6.2 escreve `total_minor <= limite_manual`."""
        tenant = self.criar_tenant(tecto_manual=TECTO_MANUAL)
        encomenda = self.criar_encomenda(tenant, total=TECTO_MANUAL)
        versao = self.levar_a(tenant, encomenda, "aguarda_pagamento")
        self.assertIsNone(
            self.tentar_transicao(
                tenant,
                encomenda,
                "aguarda_pagamento",
                "pendente_confirmacao",
                versao,
                "dono_declara",
                actor_kind="dono",
            )
        )

    def test_acima_do_tecto_e_recusado(self) -> None:
        tenant = self.criar_tenant(tecto_manual=TECTO_MANUAL)
        encomenda = self.criar_encomenda(tenant, total=TECTO_MANUAL + 1)
        versao = self.levar_a(tenant, encomenda, "aguarda_pagamento")
        self.assertEqual(
            self.tentar_transicao(
                tenant,
                encomenda,
                "aguarda_pagamento",
                "pendente_confirmacao",
                versao,
                "dono_declara",
                actor_kind="dono",
            ),
            TECTO_MANUAL_EXCEDIDO,
        )

    def test_sem_entitlement_que_declare_a_chave_e_recusado(self) -> None:
        """A falha fechada: «sem tecto» não quer dizer «sem limite».

        É o critério 2 do KAM-009 aplicado aqui, e é o caso que o `COALESCE(-1)`
        do *trigger* existe para fechar: sem ele, a comparação com `NULL` não é
        verdadeira para valor nenhum, o `IF` não dispara e a transição passa
        **sem tecto nenhum** — num tenant que não tem o módulo de pagamentos
        activo.
        """
        tenant = self.criar_tenant(tecto_manual=None)
        encomenda = self.criar_encomenda(tenant, total=1)
        versao = self.levar_a(tenant, encomenda, "aguarda_pagamento")
        self.assertEqual(
            self.tentar_transicao(
                tenant,
                encomenda,
                "aguarda_pagamento",
                "pendente_confirmacao",
                versao,
                "dono_declara",
                actor_kind="dono",
            ),
            TECTO_MANUAL_EXCEDIDO,
        )

    def test_com_o_entitlement_inactivo_e_recusado(self) -> None:
        """A `ten_tecto` só olha para `ativo`, e é isso que se mede."""
        tenant = self.criar_tenant(tecto_manual=TECTO_MANUAL)
        self.semente.execute(
            "UPDATE platform.entitlements SET ativo = false WHERE tenant_id = %s",
            (tenant,),
        )
        encomenda = self.criar_encomenda(tenant, total=1)
        versao = self.levar_a(tenant, encomenda, "aguarda_pagamento")
        self.assertEqual(
            self.tentar_transicao(
                tenant,
                encomenda,
                "aguarda_pagamento",
                "pendente_confirmacao",
                versao,
                "dono_declara",
                actor_kind="dono",
            ),
            TECTO_MANUAL_EXCEDIDO,
        )

    def test_o_tecto_e_o_minimo_entre_os_modulos_activos(self) -> None:
        """É o que a `ten_tecto` faz, e vale a pena medir aqui: um módulo com
        tecto mais baixo baixa o tecto da encomenda."""
        tenant = self.criar_tenant(tecto_manual=TECTO_MANUAL)
        factories.entitlement(
            self.semente,
            tenant,
            modulo="cobrancas",
            limites={"manual_max_minor": 1000},
        )
        encomenda = self.criar_encomenda(tenant, total=2000)
        versao = self.levar_a(tenant, encomenda, "aguarda_pagamento")
        self.assertEqual(
            self.tentar_transicao(
                tenant,
                encomenda,
                "aguarda_pagamento",
                "pendente_confirmacao",
                versao,
                "dono_declara",
                actor_kind="dono",
            ),
            TECTO_MANUAL_EXCEDIDO,
            "o tecto efectivo e o **minimo** entre os modulos activos",
        )


class TestAQuintaVia(ComEncomendas):
    """«Ha outro caminho que escreva `paga`?» — a pergunta do KAM-053."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()

    def test_um_insert_directo_em_paga_e_recusado(self) -> None:
        """A via que o `order_nasce_criada` fecha: nascer pago."""
        contacto = self.criar_contacto(self.tenant)
        try:
            self.criar_encomenda(
                self.tenant,
                contacto,
                estado="paga",
                paga_at="2026-11-03 10:00:00+01",
                paga_via="provider_autenticado",
            )
            self.fail("uma encomenda nao devia poder nascer paga")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), TRANSICAO_INVALIDA)

    def test_um_insert_directo_em_outro_estado_qualquer_e_recusado(self) -> None:
        contacto = self.criar_contacto(self.tenant)
        for estado in ("aguarda_pagamento", "entregue", "cancelada", "em_disputa"):
            with self.subTest(estado=estado):
                try:
                    self.criar_encomenda(self.tenant, contacto, estado=estado)
                    self.fail(f"uma encomenda nao devia nascer em {estado}")
                except pg8000.dbapi.DatabaseError as erro:
                    self.assertEqual(sqlstate(erro), TRANSICAO_INVALIDA)

    def test_uma_encomenda_nasce_na_versao_1(self) -> None:
        """Nascer na versao 7 dava uma encomenda com seis transicoes que nao houve."""
        contacto = self.criar_contacto(self.tenant)
        try:
            self.criar_encomenda(self.tenant, contacto, version=7)
            self.fail("uma encomenda nao devia nascer na versao 7")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), TRANSICAO_INVALIDA)

    def test_mudar_de_estado_sem_gravar_o_registo_nao_passa(self) -> None:
        """Criterio 2: o registo e o evento entram na **mesma transaccao**.

        E o que faz de «na mesma transaccao» uma imposicao e nao uma combinacao:
        quem muda o estado e nao grava o registo nao confirma.
        """
        encomenda = self.criar_encomenda(self.tenant)
        self.assertEqual(
            self.tentar(
                "UPDATE platform.orders_mirror SET estado = 'cancelada', "
                "       version = version + 1 "
                " WHERE tenant_id = %s AND id = %s",
                (self.tenant, encomenda),
            ),
            REGISTO_EM_FALTA,
            "mudar de estado sem registo nao confirma",
        )

    def test_um_registo_que_descreve_outra_transicao_nao_passa(self) -> None:
        """A linha tem de dizer o que aconteceu, e nao so existir."""
        encomenda = self.criar_encomenda(self.tenant)
        try:
            self.ensaio.execute(
                "UPDATE platform.orders_mirror SET estado = 'cancelada', "
                "       version = version + 1 "
                " WHERE tenant_id = %s AND id = %s",
                (self.tenant, encomenda),
            )
            self.ensaio.execute(
                "INSERT INTO platform.order_state_log "
                "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
                "VALUES (%s, %s, 'criada', 'aguarda_pagamento', 2, 'mentira', 'ops')",
                (self.tenant, encomenda),
            )
            self._ensaio.commit()
            self.fail("um registo que descreve outra transicao nao devia passar")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), REGISTO_EM_FALTA)
        finally:
            self._ensaio.rollback()


class TestODiferidoCorreNoCommit(ComEncomendas):
    """O modo real do *trigger*: a falha aparece no `COMMIT` e nao antes."""

    def test_diferido_a_falha_aparece_no_commit_e_nao_antes(self) -> None:
        tenant = self.criar_tenant()
        encomenda = self.criar_encomenda(tenant)
        conexao, cursor = self.ligar_app(tenant)
        cursor.execute(
            "UPDATE platform.orders_mirror SET estado = 'cancelada', "
            "       version = version + 1 "
            " WHERE tenant_id = %s AND id = %s",
            (tenant, encomenda),
        )
        # A instrucao **passou**: e isso que «diferido» quer dizer, e e a razao
        # pela qual os outros ensaios pedem o modo imediato.
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            conexao.commit()
        self.assertEqual(sqlstate(capturado.exception), REGISTO_EM_FALTA)
        conexao.rollback()
        self.assertEqual(self.estado_de(encomenda), ("criada", 1))
