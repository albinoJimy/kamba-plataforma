"""Criterio 1 do KAM-044 e do KAM-050: o grafo e dados, e o *trigger* impoe-no.

O ensaio e *table-driven* sobre **todos** os pares dos doze estados — cento e
quarenta e quatro — e nao so sobre os validos. Um ensaio que corra as vinte e
uma arestas prova que elas passam, e deixa as restantes cento e onze
combinacoes sem ninguem a dizer que sao recusadas.

## Desde o KAM-050 os cento e quarenta e quatro medem-se por execucao

O KAM-044 media quarenta e oito pares **por construcao**: quatro estados —
`entrega_falhada`, `em_disputa`, `reembolso_pendente`, `reembolsada` — nao eram
destino de aresta nenhuma, pelo que nenhuma encomenda podia estar neles. A
revisao `0046` da-lhes entrada, e cada um passa a alcancar-se pelo caminho do
grafo (o `levar_a` do `base.py`). A conta e agora uma so:

```text
132 pares com de != para   medidos por execucao, com a bandeira ligada, a
                           partir de cada um dos doze estados
 12 pares X -> X           nao sao transicoes: o `UPDATE` passa, o estado fica
                           e o *trigger* diferido nao exige registo nenhum
```

132 + 12 = 144. A bandeira mede-se a parte, nos dois sentidos: as **cinco**
arestas atras dela sao recusadas com ela desligada.

## O canario, que e o que torna o resto honesto

O `test_canario_sem_o_trigger_a_transicao_invalida_passa` desliga o *trigger*
dentro de uma transaccao revertida, tenta `criada -> entregue` e exige que
**passe**. Sem ele, este ficheiro nao distingue «o *trigger* recusa» de «um
`CHECK` qualquer recusa»: os doze estados estao todos no dominio da coluna.
"""

from __future__ import annotations

import pg8000.dbapi

from tests.base import sqlstate
from tests_encomendas.base import (
    CAUSA_PROVIDER,
    ESTADOS,
    GRAFO,
    NUCLEO,
    KAM_050,
    REEMBOLSO_SEM_ACTOR,
    TRANSICAO_INVALIDA,
    ComEncomendas,
)

#: As cinco arestas atras de `COM_DELIVERY_ENABLED`, escritas a mao.
ATRAS_DA_BANDEIRA = [
    ("em_entrega", "entrega_falhada"),
    ("em_entrega", "entregue"),
    ("entrega_falhada", "em_entrega"),
    ("entrega_falhada", "reembolso_pendente"),
    ("paga", "em_entrega"),
]


class TestATabelaDoGrafo(ComEncomendas):
    """A tabela tem as vinte e uma e **so** essas, nos dois sentidos."""

    def test_a_tabela_tem_exactamente_as_vinte_e_uma(self) -> None:
        linhas = self.consultar(
            "SELECT de, para, flag FROM platform.order_state_graph ORDER BY de, para"
        )
        self.assertEqual(
            {(de, para): flag for de, para, flag in linhas},
            GRAFO,
            "o grafo da base e o declarado tem de bater nos dois sentidos: uma "
            "linha a mais e escopo a entrar sem ticket, e uma a menos e uma "
            "transicao do §6.1 que deixou de valer",
        )
        self.assertEqual(len(NUCLEO), 12)
        self.assertEqual(len(KAM_050), 9)

    def test_as_cinco_atras_da_bandeira(self) -> None:
        """Criterio 6 do KAM-050: `em_entrega`/`entrega_falhada` atras da bandeira."""
        linhas = self.consultar(
            "SELECT de, para FROM platform.order_state_graph "
            "WHERE flag IS NOT NULL ORDER BY de, para"
        )
        self.assertEqual(linhas, ATRAS_DA_BANDEIRA)

    def test_o_grafo_nao_tem_laco_nem_estado_fora_do_dominio(self) -> None:
        linhas = self.consultar(
            "SELECT de, para FROM platform.order_state_graph "
            "WHERE de = para OR de <> ALL(%s) OR para <> ALL(%s)",
            (list(ESTADOS), list(ESTADOS)),
        )
        self.assertEqual(linhas, [])

    def test_os_doze_estados_alcancam_se_a_partir_de_criada(self) -> None:
        """Nenhum estado fica sem entrada: a classe de defeito que a nona aresta fecha.

        O criterio 1 do KAM-050, a letra, acrescentava duas arestas que **saem**
        de `entrega_falhada` e nenhuma que la chegue. Este ensaio e o que o
        teria apanhado: percorre o grafo da base a partir de `criada` e exige os
        doze.
        """
        arestas = self.consultar("SELECT de, para FROM platform.order_state_graph")
        vistos, fila = {"criada"}, ["criada"]
        while fila:
            de = fila.pop()
            for origem, destino in arestas:
                if origem == de and destino not in vistos:
                    vistos.add(destino)
                    fila.append(destino)
        self.assertEqual(vistos, set(ESTADOS))

    def test_so_cancelada_e_reembolsada_sao_terminais(self) -> None:
        origens = {de for (de,) in self.consultar(
            "SELECT DISTINCT de FROM platform.order_state_graph"
        )}
        self.assertEqual(set(ESTADOS) - origens, {"cancelada", "reembolsada"})


class TestTodosOsParesDeEstados(ComEncomendas):
    """Os cento e quarenta e quatro pares, por execucao."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)

    def _tentar(self, de: str, para: str, bandeira: bool) -> str | None:
        """Tenta o par numa encomenda nova. Devolve o SQLSTATE, ou `None`.

        Uma encomenda **por par**: cada tentativa parte de uma linha limpa. A
        bandeira entra por `set_config(..., true)` — local a transaccao —, pelo
        que desaparece com o `COMMIT` ou o `ROLLBACK` da tentativa.

        **Para `paga`, a causa tem de ser autenticada** e o evento tem de ter
        recibo de consumo: este ficheiro mede o **grafo**, e com uma causa de
        ensaio o que recusava era o *trigger* diferido (`KA006`) e nao o grafo.
        O `reembolsada` vai com actor `ops` identificado, que e a omissao do
        `transitar`, pela mesma razao.
        """
        encomenda = self.criar_encomenda(self.tenant, self.contacto)
        versao = self.levar_a(self.tenant, encomenda, de)
        if bandeira:
            self.ligar_bandeira()
        extra: dict[str, object] = {}
        if para == "paga":
            extra = {
                "actor_kind": "sistema",
                "evento_id": self.registar_consumo(self.tenant),
            }
        return self.tentar_transicao(
            self.tenant,
            encomenda,
            de,
            para,
            versao,
            CAUSA_PROVIDER if para == "paga" else "ensaio",
            **extra,
        )

    def test_os_132_pares_so_passam_os_do_grafo(self) -> None:
        """Com a bandeira ligada, para que as cinco dela contem como arestas."""
        for de in ESTADOS:
            for para in ESTADOS:
                if de == para:
                    continue
                with self.subTest(de=de, para=para):
                    erro = self._tentar(de, para, bandeira=True)
                    if (de, para) in GRAFO:
                        self.assertIsNone(
                            erro, f"{de} -> {para} esta no grafo e tem de passar"
                        )
                    else:
                        self.assertEqual(
                            erro,
                            TRANSICAO_INVALIDA,
                            f"{de} -> {para} nao esta no grafo e tem de ser "
                            "recusado pelo trigger",
                        )

    def test_as_cinco_da_bandeira_nao_passam_com_ela_desligada(self) -> None:
        """O outro sentido: e o que faz da bandeira uma bandeira."""
        for de, para in ATRAS_DA_BANDEIRA:
            with self.subTest(de=de, para=para):
                self.assertEqual(
                    self._tentar(de, para, bandeira=False),
                    TRANSICAO_INVALIDA,
                    "desligada no Piloto: a aresta existe e nao passa",
                )

    def test_ligar_a_bandeira_nao_exige_migracao(self) -> None:
        """A mesma aresta, a mesma base: so a variavel de sessao muda."""
        self.assertEqual(
            self._tentar("paga", "em_entrega", bandeira=False), TRANSICAO_INVALIDA
        )
        self.assertIsNone(self._tentar("paga", "em_entrega", bandeira=True))

    def test_os_pares_x_para_x_nao_sao_transicoes(self) -> None:
        """Os **doze** pares `X -> X`: o `UPDATE` passa e nao grava registo."""
        for estado in ESTADOS:
            with self.subTest(estado=estado):
                encomenda = self.criar_encomenda(self.tenant, self.contacto)
                versao = self.levar_a(self.tenant, encomenda, estado)
                antes = self.consultar(
                    "SELECT count(*) FROM platform.order_state_log "
                    " WHERE order_id = %s",
                    (encomenda,),
                )
                self.semente.execute(
                    "UPDATE platform.orders_mirror SET estado = %s, "
                    "       expira_at = now() + interval '1 hour' "
                    " WHERE tenant_id = %s AND id = %s",
                    (estado, self.tenant, encomenda),
                )
                self.assertEqual(self.estado_de(encomenda), (estado, versao))
                self.assertEqual(
                    self.consultar(
                        "SELECT count(*) FROM platform.order_state_log "
                        " WHERE order_id = %s",
                        (encomenda,),
                    ),
                    antes,
                    "um par X -> X nao e transicao: nao grava registo nenhum",
                )


class TestReembolsadaSoPorDonoOuOps(ComEncomendas):
    """Criterio 5 do KAM-050: `reembolsada` so por registo manual identificado."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()

    def _tentar(self, actor_kind: str, actor_id: str | None) -> tuple[str | None, str]:
        encomenda = self.criar_encomenda(self.tenant)
        versao = self.levar_a(self.tenant, encomenda, "reembolso_pendente")
        try:
            self.transitar(
                self.tenant,
                encomenda,
                "reembolso_pendente",
                "reembolsada",
                versao,
                "reembolso_manual_registado",
                actor_kind=actor_kind,
                actor_id=actor_id,
            )
            return None, ""
        except pg8000.dbapi.DatabaseError as erro:
            self._ensaio.rollback()
            return sqlstate(erro), str(erro)

    def test_agente_e_sistema_sao_recusados(self) -> None:
        for kind in ("agente", "sistema"):
            with self.subTest(actor=kind):
                codigo, mensagem = self._tentar(kind, "quem-1")
                self.assertEqual(codigo, REEMBOLSO_SEM_ACTOR)
                # A mensagem e a do ramo novo e nao a do `paga`: os dois usam
                # `KA006`, e e o texto que diz qual dos dois recusou.
                self.assertIn("reembolsada exige", mensagem)

    def test_dono_ou_ops_sem_id_sao_recusados(self) -> None:
        for kind, quem in (("ops", None), ("dono", "   ")):
            with self.subTest(actor=kind, id=quem):
                codigo, mensagem = self._tentar(kind, quem)
                self.assertEqual(codigo, REEMBOLSO_SEM_ACTOR)
                self.assertIn("reembolsada exige", mensagem)

    def test_dono_e_ops_identificados_passam(self) -> None:
        for kind in ("dono", "ops"):
            with self.subTest(actor=kind):
                self.assertEqual(self._tentar(kind, f"{kind}-1"), (None, ""))

    def test_canario_sem_o_trigger_diferido_o_agente_passa(self) -> None:
        """Quem recusa e o `order_estado_exige_log`, e nao outra coisa.

        O *trigger* e diferido; o `SET CONSTRAINTS ALL IMMEDIATE` fa-lo correr no
        fim de cada instrucao, pelo que o registo entra **antes** do `UPDATE` e a
        recusa (ou a falta dela) ve-se dentro de uma transaccao que se reverte.
        """
        encomenda = self.criar_encomenda(self.tenant)
        versao = self.levar_a(self.tenant, encomenda, "reembolso_pendente")
        registo = (
            "INSERT INTO platform.order_state_log (tenant_id, order_id, de, para, "
            "  version, causa, actor_kind, actor_id) "
            "VALUES (%s, %s, 'reembolso_pendente', 'reembolsada', %s, 'ensaio', "
            "  'agente', 'a-1')"
        )
        mudar = (
            "UPDATE platform.orders_mirror SET estado = 'reembolsada', "
            "       version = version + 1 WHERE tenant_id = %s AND id = %s"
        )
        try:
            self.ensaio.execute("SET CONSTRAINTS ALL IMMEDIATE")
            self.ensaio.execute(registo, (self.tenant, encomenda, versao + 1))
            with self.assertRaises(pg8000.dbapi.DatabaseError) as recusa:
                self.ensaio.execute(mudar, (self.tenant, encomenda))
            self.assertEqual(sqlstate(recusa.exception), REEMBOLSO_SEM_ACTOR)
        finally:
            self._ensaio.rollback()
        try:
            self.ensaio.execute(
                "ALTER TABLE platform.orders_mirror DISABLE TRIGGER "
                "order_estado_exige_log"
            )
            self.ensaio.execute("SET CONSTRAINTS ALL IMMEDIATE")
            self.ensaio.execute(registo, (self.tenant, encomenda, versao + 1))
            self.ensaio.execute(mudar, (self.tenant, encomenda))
        finally:
            self._ensaio.rollback()


class TestCanarioDoTrigger(ComEncomendas):
    """Sem o *trigger*, a transicao invalida passa. Ver a nota do modulo."""

    def test_canario_sem_o_trigger_a_transicao_invalida_passa(self) -> None:
        tenant = self.criar_tenant()
        encomenda = self.criar_encomenda(tenant)
        # Na ligacao **transaccional**, e revertido: um `ALTER TABLE`
        # confirmado deixava a base do *gate* sem a barreira para os ensaios
        # seguintes — e a suite inteira passava a medir uma tabela sem
        # *trigger*.
        try:
            self.ensaio.execute(
                "ALTER TABLE platform.orders_mirror DISABLE TRIGGER "
                "order_transicao_valida"
            )
            self.ensaio.execute(
                "UPDATE platform.orders_mirror SET estado = 'entregue', "
                "       version = version + 1, entregue_at = now(), "
                "       entrega_confirmada_por = 'cliente' "
                " WHERE id = %s RETURNING version",
                (encomenda,),
            )
            self.assertEqual(
                int(self.ensaio.fetchone()[0]),
                2,
                "com o trigger desligado, `criada -> entregue` passa: e isso "
                "que prova que quem recusa e ele, e nao um CHECK de dominio",
            )
        finally:
            self._ensaio.rollback()
