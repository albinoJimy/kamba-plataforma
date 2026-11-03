"""Criterio 1: o grafo e dados, e o *trigger* `BEFORE UPDATE` e que o impoe.

O ensaio e *table-driven* sobre **todos** os pares dos doze estados — cento e
quarenta e quatro — e nao so sobre os validos. A diferenca nao e de forma: um
ensaio que corra os doze pares do nucleo prova que eles passam, e deixa as
restantes cento e vinte combinacoes sem ninguem a dizer que sao recusadas.

## Os doze estados, e nao os nove do `CHECK` do §5.4

O dominio da coluna e o do dicionario §3.3, que marca a maquina de
`docs/tecnica/03` §6.1 como «Maquina incompleta» e tem fonte no
`docs/tecnica/00` §6.1. Os quatro que o §5.4 nao tem — `entrega_falhada`,
`em_disputa`, `reembolsada` e, no grafo, tudo o que passe por eles — existem
como **valor** e nao como destino: e o KAM-050 que lhes acrescenta transicoes.

## Como e que os cento e quarenta e quatro pares se medem

Nem todos se medem da mesma forma, e isso esta escrito aqui em vez de ficar
escondido numa contagem:

```text
88 pares com `de`    medidos **por execucao**: a encomenda e levada ao estado de
alcancavel           partida pelo caminho do grafo e tenta-se cada destino. Sao
                     as **oito** origens alcancaveis vezes os 11 destinos: as
                     seis do nucleo sem bandeira, o `entregue` (que e terminal,
                     e tem ensaio proprio) e o `em_entrega`, que so se alcanca
                     com a bandeira ligada e por isso tem o seu.
 8 pares `X -> X`    nao sao transicoes, e medem-se nas **oito** origens
                     alcancaveis: o `UPDATE` passa, o estado fica o mesmo e o
                     *trigger* diferido nao exige registo nenhum. O grafo tem
                     `CHECK (de <> para)`, que os torna inrepresentaveis.
48 pares com `de`    medidos **por construcao**: `entrega_falhada`,
inalcancavel         `em_disputa`, `reembolso_pendente` e `reembolsada` nao sao
                     destino de transicao nenhuma do nucleo, pelo que nenhuma
                     encomenda pode estar neles — nem para transitar (44 pares)
                     nem para nao transitar (os 4 `X -> X` deles). Prova-se que
                     nao sao alcancaveis, e que o grafo nao tem linha nenhuma a
                     sair deles ou a chegar-lhes — que e a **unica** entrada que
                     o *trigger* le.
```

88 + 8 + 48 = 144, e a conta esta aqui porque a primeira versao desta nota
**estava errada**: dizia 88 por execucao quando o laco exercitava 77 (faltava o
`em_entrega` como origem, que ninguem exercitava), e dizia 12 pares `X -> X`
medidos quando era um. Medido antes da revisao adversarial, com a conta feita
sobre o proprio ficheiro.

A alternativa para os 44 era semear o estado com o *trigger* desligado, e isso
e medir uma barreira com a barreira fora: o que o ensaio diria e «com o
*trigger* desligado, o estado inalcancavel aceita-se», que e verdade e nao
interessa.

## O canario, que e o que torna o resto honesto

O `test_canario_sem_o_trigger_a_transicao_invalida_passa` desliga o *trigger*
dentro de um `SAVEPOINT`, tenta `criada -> entregue` e exige que **passe**. Sem
ele, este ficheiro nao distingue «o *trigger* recusa» de «um `CHECK` qualquer
recusa»: os doze estados estao todos no dominio da coluna, pelo que nenhum
`CHECK` de dominio tem opiniao sobre o par.
"""

from __future__ import annotations

from tests_encomendas.base import (
    CAUSA_PROVIDER,
    ESTADOS,
    GUC_DA_ENTREGA,
    NUCLEO,
    TRANSICAO_INVALIDA,
    ComEncomendas,
)

#: Os estados a que uma encomenda chega pelo nucleo, e como. O `em_entrega` e o
#: `entregue` entram pelos ensaios que ligam a bandeira.
ALCANCAVEIS_SEM_BANDEIRA = (
    "criada",
    "aguarda_pagamento",
    "pendente_confirmacao",
    "paga",
    "expirada",
    "cancelada",
)

#: Os quatro que nenhuma transicao do nucleo alcanca. Sao do KAM-050.
INALCANCAVEIS = (
    "entrega_falhada",
    "em_disputa",
    "reembolso_pendente",
    "reembolsada",
)


class TestATabelaDoGrafo(ComEncomendas):
    """A tabela tem o nucleo e **so** o nucleo, nos dois sentidos."""

    def test_a_tabela_tem_exactamente_as_doze_do_nucleo(self) -> None:
        linhas = self.consultar(
            "SELECT de, para, flag FROM platform.order_state_graph ORDER BY de, para"
        )
        self.assertEqual(
            {(de, para): flag for de, para, flag in linhas},
            NUCLEO,
            "o grafo da base e o nucleo declarado tem de bater nos dois "
            "sentidos: uma linha a mais e escopo do KAM-050 a entrar sem "
            "ticket, e uma a menos e uma transicao do §6.2 que deixou de valer",
        )

    def test_as_duas_atras_da_bandeira_sao_as_do_em_entrega(self) -> None:
        """Criterio 1: «`em_entrega` atras de `COM_DELIVERY_ENABLED`»."""
        linhas = self.consultar(
            "SELECT de, para FROM platform.order_state_graph "
            "WHERE flag IS NOT NULL ORDER BY de, para"
        )
        self.assertEqual(
            linhas, [("em_entrega", "entregue"), ("paga", "em_entrega")]
        )

    def test_o_grafo_nao_tem_laco_nem_estado_fora_do_dominio(self) -> None:
        linhas = self.consultar(
            "SELECT de, para FROM platform.order_state_graph "
            "WHERE de = para OR de <> ALL(%s) OR para <> ALL(%s)",
            (list(ESTADOS), list(ESTADOS)),
        )
        self.assertEqual(linhas, [])

    def test_nenhuma_transicao_sai_dos_quatro_do_kam_050(self) -> None:
        """A medicao «por construcao» dos 48 pares. Ver a nota do modulo.

        Os 44 em que um dos quatro e origem ou destino, mais os 4 `X -> X`
        deles: nenhuma encomenda pode estar num estado que transicao nenhuma
        alcanca, e o que o *trigger* le e so esta tabela.
        """
        linhas = self.consultar(
            "SELECT de, para FROM platform.order_state_graph "
            "WHERE de = ANY(%s) OR para = ANY(%s)",
            (list(INALCANCAVEIS), list(INALCANCAVEIS)),
        )
        self.assertEqual(
            linhas,
            [],
            "nenhum dos quatro estados do KAM-050 e origem nem destino no "
            "nucleo: e isso que os torna inalcancaveis, e o *trigger* le so "
            "esta tabela",
        )


class TestTodosOsParesDeEstados(ComEncomendas):
    """Criterio 1: *table-driven* sobre os cento e quarenta e quatro pares."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)

    def _tentar(self, de: str, para: str, bandeira: bool) -> str | None:
        """Tenta o par numa encomenda nova. Devolve o SQLSTATE, ou `None`.

        Uma encomenda **por par**: cada tentativa parte de uma linha limpa, pelo
        que uma que passe nao precisa de ser desfeita — e desfaze-la com
        `SAVEPOINT` nao era possivel, porque a ligacao da semente e `autocommit`
        (ver a nota do `base.py`).

        A bandeira entra por `set_config(..., true)` — **local a transaccao** —,
        o que a faz desaparecer com o `COMMIT` ou o `ROLLBACK` da tentativa. Com
        `false` ficava na sessao e o par seguinte herdava-a, que era um ensaio a
        medir uma bandeira que ele proprio nao pediu.
        """
        encomenda = self.criar_encomenda(self.tenant, self.contacto)
        versao = self.levar_a(self.tenant, encomenda, de)
        if bandeira:
            self.ensaio.execute("SELECT set_config(%s, 'on', true)", (GUC_DA_ENTREGA,))
            self.ensaio.fetchone()
        # **Para `paga`, a causa tem de ser autenticada**, e nao e uma
        # concessao: este ficheiro mede o **grafo**, e com uma causa de ensaio o
        # que recusava `aguarda_pagamento -> paga` era o *trigger* diferido
        # (`KA006`) e nao o grafo — o ensaio dizia «o grafo recusa» sobre um par
        # que ele aceita. Medido na segunda corrida da suite.
        extra: dict[str, object] = {}
        if para == "paga":
            # O `evento_id` tem de ter **recibo de consumo** (KAM-006): desde o
            # achado 1 da revisao adversarial, um texto inventado e recusado com
            # `KA006` — e este ficheiro mede o **grafo**, nao aquela barreira.
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

    def test_so_os_pares_do_grafo_passam_e_os_restantes_sao_recusados(self) -> None:
        """Os 88 pares com estado de partida alcancavel, por execucao."""
        for de in ALCANCAVEIS_SEM_BANDEIRA:
            for para in ESTADOS:
                if de == para:
                    continue
                esperado = NUCLEO.get((de, para), "NAO_ESTA")
                with self.subTest(de=de, para=para):
                    erro = self._tentar(de, para, bandeira=False)
                    if esperado is None:
                        self.assertIsNone(
                            erro, f"{de} -> {para} esta no nucleo e tem de passar"
                        )
                    else:
                        self.assertEqual(
                            erro,
                            TRANSICAO_INVALIDA,
                            f"{de} -> {para} nao esta activo e tem de ser "
                            "recusado pelo trigger",
                        )

    def test_as_duas_da_bandeira_passam_com_ela_ligada_e_so_com_ela(self) -> None:
        """Nos dois sentidos, que e o que faz da bandeira uma bandeira."""
        self.assertEqual(
            self._tentar("paga", "em_entrega", bandeira=False),
            TRANSICAO_INVALIDA,
            "desligada no Piloto: a transicao existe no grafo e nao passa",
        )
        self.assertIsNone(
            self._tentar("paga", "em_entrega", bandeira=True),
            "ligada: a mesma transicao passa, e sem migracao nenhuma",
        )

    def test_a_partir_de_em_entrega_so_sai_o_entregue(self) -> None:
        """Os 11 pares com `em_entrega` como origem, com a bandeira ligada.

        **So se alcanca com a bandeira**, e e por isso que tem ensaio proprio:
        o laco de cima corre com ela desligada, onde `em_entrega` nao e
        alcancavel. Com ela ligada, a unica saida e `entregue` — e o
        `paga -> em_entrega` da entrada mede-se no ensaio da bandeira.
        """
        # **Uma encomenda por destino**, e a razao foi medida: o caso
        # `em_entrega -> entregue` **passa** e confirma, pelo que a encomenda
        # muda de estado e de versao — e os destinos seguintes do laco deixavam
        # de casar o CAS, falhando por «a semente nao conseguiu transitar» em
        # vez de pelo *trigger*. Quatro subTests vermelhos a prova-lo.
        for para in ESTADOS:
            if para == "em_entrega":
                continue
            with self.subTest(para=para):
                encomenda = self.criar_encomenda(self.tenant, self.contacto)
                versao = self.levar_a(self.tenant, encomenda, "paga")
                self.ensaio.execute(
                    "SELECT set_config(%s, 'on', true)", (GUC_DA_ENTREGA,)
                )
                self.ensaio.fetchone()
                versao = self.transitar(
                    self.tenant, encomenda, "paga", "em_entrega", versao, "dispatch"
                )
                self.ensaio.execute(
                    "SELECT set_config(%s, 'on', true)", (GUC_DA_ENTREGA,)
                )
                self.ensaio.fetchone()
                erro = self.tentar_transicao(
                    self.tenant, encomenda, "em_entrega", para, versao, "ensaio"
                )
                if para == "entregue":
                    self.assertIsNone(erro, "em_entrega -> entregue esta no nucleo")
                else:
                    self.assertEqual(
                        erro,
                        TRANSICAO_INVALIDA,
                        f"em_entrega -> {para} nao esta no grafo",
                    )

    def test_com_a_bandeira_desligada_nem_a_saida_do_em_entrega_passa(self) -> None:
        """A bandeira guarda as **duas** linhas, e nao so a de entrada.

        Uma encomenda que entrou em `em_entrega` com a bandeira ligada e depois a
        encontra desligada **nao sai** por ela — e e o comportamento certo: o
        `order_state_graph` poe a bandeira nas duas linhas, e desligar a entrega
        a meio e uma decisao de operacao, nao um estado novo.
        """
        encomenda = self.criar_encomenda(self.tenant, self.contacto)
        versao = self.levar_a(self.tenant, encomenda, "paga")
        self.ensaio.execute("SELECT set_config(%s, 'on', true)", (GUC_DA_ENTREGA,))
        self.ensaio.fetchone()
        versao = self.transitar(
            self.tenant, encomenda, "paga", "em_entrega", versao, "dispatch"
        )
        self.assertEqual(
            self.tentar_transicao(
                self.tenant, encomenda, "em_entrega", "entregue", versao, "codigo"
            ),
            TRANSICAO_INVALIDA,
        )

    def test_a_partir_de_entregue_nao_sai_nada(self) -> None:
        """`entregue` e terminal no nucleo: a disputa e o reembolso sao do KAM-050."""
        encomenda = self.criar_encomenda(self.tenant, self.contacto)
        versao = self.levar_a(self.tenant, encomenda, "paga")
        versao = self.transitar(
            self.tenant, encomenda, "paga", "entregue", versao, "levantamento"
        )
        for para in ESTADOS:
            if para == "entregue":
                continue
            with self.subTest(para=para):
                self.assertEqual(
                    self.tentar_transicao(
                        self.tenant, encomenda, "entregue", para, versao, "ensaio"
                    ),
                    TRANSICAO_INVALIDA,
                    f"entregue -> {para} nao devia passar",
                )

    def test_os_pares_x_para_x_nao_sao_transicoes(self) -> None:
        """Os **oito** pares `X -> X` alcancaveis. Ver a nota do modulo.

        O `UPDATE` passa — e tem de passar, porque e por ele que o `expira_at` e
        o `deleted_at` se escrevem —, o estado fica o mesmo e o *trigger*
        diferido nao exige registo nenhum: nao houve transicao para registar.

        **Oito e nao doze**: os quatro do KAM-050 sao inalcancaveis, pelo que o
        par `X -> X` deles nao se consegue medir por execucao. Entram na conta
        por construcao, com os outros 44.

        O `em_entrega` entra com a bandeira ligada, que e a unica forma de uma
        encomenda estar nele.
        """
        for estado in (*ALCANCAVEIS_SEM_BANDEIRA, "entregue", "em_entrega"):
            with self.subTest(estado=estado):
                encomenda = self.criar_encomenda(self.tenant, self.contacto)
                if estado == "em_entrega":
                    versao = self.levar_a(self.tenant, encomenda, "paga")
                    self.ensaio.execute(
                        "SELECT set_config(%s, 'on', true)", (GUC_DA_ENTREGA,)
                    )
                    self.ensaio.fetchone()
                    versao = self.transitar(
                        self.tenant, encomenda, "paga", "em_entrega", versao,
                        "dispatch",
                    )
                elif estado == "entregue":
                    versao = self.levar_a(self.tenant, encomenda, "paga")
                    versao = self.transitar(
                        self.tenant, encomenda, "paga", "entregue", versao,
                        "levantamento",
                    )
                else:
                    versao = self.levar_a(self.tenant, encomenda, estado)

                antes = self.consultar(
                    "SELECT count(*) FROM platform.order_state_log "
                    " WHERE order_id = %s",
                    (encomenda,),
                )
                # O `UPDATE` poe o estado no valor que ele ja tem, e mexe numa
                # coluna que a encomenda deixa mexer em qualquer estado.
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
