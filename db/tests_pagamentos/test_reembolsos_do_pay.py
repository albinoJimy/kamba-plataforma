"""KAM-197: o PAY abre a `refund_cases` ao consumir `order.refund_requested`.

Contra PostgreSQL, com o texto que o TypeScript envia
(`services/com/src/payments/reembolsos.ts`, pelo `ConsultaDoTypeScript`), e
com o papel que corre o consumidor do PAY. O que aqui se mede e o que so a base
pode dizer:

```text
sem ledger     o caso abre sem linha nova em `payment_events` e sem a cobranca
               mudar de estado
x10            o mesmo pedido dez vezes da um caso, e uma repeticao que diverge
               e recusada
barreiras      o motivo contra a lista fechada, a encomenda no tenant, a moeda
               e o valor
um dono        o papel do COM nao escreve na `refund_cases`, nem por `INSERT`
               nem pela porta
o duplicado    o `pagamento_duplicado` do ledger chega ao COM como o
               `payment.confirmed` que a regra 4 le, valido contra o contrato
```

**Corre depois do `test_downgrade*` e do `test_fks_e_mapa`, pela ordem
alfabetica, e isso conta:** os casos que estes ensaios deixam (com
`pedido_evento_id`) fazem o `downgrade` da `0050` recusar-se, que e o que ele
deve fazer. A limpeza do `ComConfirmacaoManual` apaga-os por tenant.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    ConsultaDoTypeScript,
)
from tests_pagamentos.base import VALOR, ComLedger
from tests_pagamentos.manual_base import ComConfirmacaoManual

RAIZ = Path(__file__).resolve().parents[2]

MODULO = RAIZ / "services" / "com" / "src" / "payments" / "reembolsos.ts"

CONTRATO = (
    RAIZ / "contratos" / "eventos" / "order.refund_requested" / "v1.schema.json"
)

#: A identidade do `db/ligacao.py` que corre o consumidor do PAY.
PAPEL_DO_PAY = "pay"

ABRIR = ConsultaDoTypeScript("SQL_ABRIR_CASO_DE_REEMBOLSO", MODULO)


class ComPedidoDeReembolso(ComConfirmacaoManual):
    """Uma encomenda paga e o papel do PAY no tenant dela."""

    def setUp(self) -> None:
        super().setUp()
        self.pay = self.cursor_papel(PAPEL_DO_PAY, self.tenant)

    def abrir(self, cursor=None, **campos) -> str:
        valores = {
            "tenant": self.tenant,
            "encomenda": self.encomenda,
            "motivo": "pagamento_duplicado",
            "valor": VALOR,
            "moeda": "AOA",
            "pedido": str(uuid.uuid4()),
        }
        valores.update(campos)
        alvo = self.pay if cursor is None else cursor
        alvo.execute(
            ABRIR.sql,
            ABRIR.args(
                valores["tenant"],
                valores["encomenda"],
                valores["motivo"],
                valores["valor"],
                valores["moeda"],
                valores["pedido"],
            ),
        )
        return str(alvo.fetchone()[0])

    def casos(self) -> list[tuple]:
        self.semente.execute(
            "SELECT order_id, charge_id, motivo, valor_minor, estado, "
            "       pedido_evento_id "
            "  FROM platform.refund_cases WHERE tenant_id = %s ORDER BY criado_at",
            (self.tenant,),
        )
        return [tuple(str(c) if c is not None else None for c in linha)
                for linha in self.semente.fetchall()]

    def eventos_do_tenant(self) -> int:
        self.semente.execute(
            "SELECT count(*) FROM platform.payment_events WHERE tenant_id = %s",
            (self.tenant,),
        )
        return int(self.semente.fetchone()[0])


class TestAberturaSemLedger(ComPedidoDeReembolso):
    """O criterio 1 e a «Base de dados» dos Testes Requeridos."""

    def test_o_caso_abre_sem_linha_nova_no_ledger(self) -> None:
        eventos_antes = self.eventos_do_tenant()
        estado_antes = self.estado_da_cobranca(self.cobranca)
        pedido = str(uuid.uuid4())

        caso = self.abrir(pedido=pedido)
        self.confirmar(self.pay, self.tenant)

        self.assertEqual(
            self.casos(),
            [(self.encomenda, None, "pagamento_duplicado", str(VALOR), "aberto",
              pedido)],
        )
        self.assertTrue(caso)
        self.assertEqual(self.eventos_do_tenant(), eventos_antes,
                         "nenhuma linha nova no ledger")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), estado_antes,
                         "nenhuma cobranca muda de estado")

    def test_duplicados_x10_dao_um_caso(self) -> None:
        pedido = str(uuid.uuid4())
        devolvidos = {self.abrir(pedido=pedido) for _ in range(10)}
        self.confirmar(self.pay, self.tenant)
        self.assertEqual(len(devolvidos), 1, "o mesmo caso as dez vezes")
        self.assertEqual(len(self.casos()), 1)

    def test_dois_pedidos_sao_dois_casos(self) -> None:
        # O controlo do de cima: sem ele, uma porta que abrisse um caso por
        # encomenda passava o x10.
        self.abrir()
        self.abrir()
        self.confirmar(self.pay, self.tenant)
        self.assertEqual(len(self.casos()), 2)

    def test_uma_repeticao_que_diverge_e_recusada(self) -> None:
        pedido = str(uuid.uuid4())
        self.abrir(pedido=pedido)
        for campo, valor in (
            ("valor", VALOR + 1),
            ("motivo", "disputa"),
        ):
            with self.subTest(campo=campo):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    self.pay,
                    ABRIR.sql,
                    ABRIR.args(
                        self.tenant,
                        self.encomenda,
                        valor if campo == "motivo" else "pagamento_duplicado",
                        valor if campo == "valor" else VALOR,
                        "AOA",
                        pedido,
                    ),
                )
        self.confirmar(self.pay, self.tenant)
        self.assertEqual(len(self.casos()), 1)


class TestBarreirasDaPorta(ComPedidoDeReembolso):
    """Cada barreira com o seu caso, a correr com o papel do PAY."""

    def recusa(self, **campos) -> None:
        valores = {
            "tenant": self.tenant,
            "encomenda": self.encomenda,
            "motivo": "pagamento_duplicado",
            "valor": VALOR,
            "moeda": "AOA",
            "pedido": str(uuid.uuid4()),
        }
        valores.update(campos)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            self.pay,
            ABRIR.sql,
            ABRIR.args(*(valores[c] for c in (
                "tenant", "encomenda", "motivo", "valor", "moeda", "pedido"))),
        )

    def test_um_motivo_fora_do_contrato_e_recusado(self) -> None:
        for motivo in ("reembolso", "pagamento_tardio_sem_stock", "", None):
            with self.subTest(motivo=motivo):
                self.recusa(motivo=motivo)

    def test_sem_pedido_nao_ha_caso(self) -> None:
        self.recusa(pedido=None)

    def test_uma_encomenda_que_nao_existe_e_recusada(self) -> None:
        self.recusa(encomenda=str(uuid.uuid4()))

    def test_outra_moeda_e_recusada(self) -> None:
        for moeda in ("USD", None):
            with self.subTest(moeda=moeda):
                self.recusa(moeda=moeda)

    def test_valor_zero_e_recusado_pela_tabela(self) -> None:
        # O contrato admite `minimum: 0`; quem recusa e o `refund_cases_valor_ck`.
        self.recusa(valor=0)

    def test_a_encomenda_de_outro_tenant_nao_abre_caso(self) -> None:
        """O `DEFINER` da privilegio e nao da isolamento (nota da `0039`).

        No contexto de A, nem a encomenda de B nem o tenant de B: os dois sao
        recusados — o primeiro pela leitura sob RLS, o segundo pela politica.
        """
        outro = self.criar_tenant()
        encomenda_de_b = self.criar_encomenda(outro)
        self.recusa(encomenda=encomenda_de_b)
        self.recusa(tenant=outro, encomenda=encomenda_de_b)
        self.confirmar(self.pay, self.tenant)
        self.semente.execute(
            "SELECT count(*) FROM platform.refund_cases WHERE tenant_id = %s",
            (outro,),
        )
        self.assertEqual(int(self.semente.fetchone()[0]), 0)

    def test_sem_contexto_de_tenant_a_porta_nao_abre(self) -> None:
        sem_contexto = self.cursor_papel(PAPEL_DO_PAY, None)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            sem_contexto,
            ABRIR.sql,
            ABRIR.args(self.tenant, self.encomenda, "pagamento_duplicado", VALOR,
                       "AOA", str(uuid.uuid4())),
        )

    def test_os_motivos_da_porta_sao_os_do_contrato(self) -> None:
        """Tres superficies: o contrato, a porta instalada e o dicionario.

        O confronto e entre o **ficheiro do contrato** e o `pg_get_functiondef`
        da funcao instalada — e nao com uma lista escrita neste ensaio, que
        concordava com a revisao por construcao.
        """
        contrato = json.loads(CONTRATO.read_text(encoding="utf-8"))
        esperados = set(
            contrato["properties"]["payload"]["properties"]["motivo"]["enum"]
        )
        self.semente.execute(
            "SELECT pg_get_functiondef('platform.abrir_caso_de_reembolso("
            "uuid, uuid, text, bigint, text, uuid)'::regprocedure)"
        )
        corpo = self.semente.fetchone()[0]
        lista = re.search(r"p_motivo NOT IN \(([^)]*)\)", corpo)
        self.assertIsNotNone(lista, "a porta perdeu a lista fechada do motivo")
        instalados = set(re.findall(r"'([a-z_]+)'", lista.group(1)))
        self.assertEqual(instalados, esperados)


class TestUmDonoSo(ComPedidoDeReembolso):
    """O COM nao escreve na `refund_cases` (Detalhes Tecnicos, «um dono so»)."""

    def test_o_papel_do_com_nao_insere(self) -> None:
        com = self.cursor_papel("app", self.tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            com,
            "INSERT INTO platform.refund_cases "
            "(tenant_id, order_id, motivo, valor_minor) VALUES (%s, %s, %s, %s)",
            (self.tenant, self.encomenda, "pagamento_duplicado", VALOR),
        )

    def test_o_papel_do_com_nao_abre_caso_pela_porta(self) -> None:
        """A decisao (A) do fundador, medida: o `kamba_app` leva `42501`.

        E a metade que faz da regra «um so dono» uma recusa da base. O controlo
        positivo e o resto desta suite, que abre casos com o `kamba_pay`.
        """
        com = self.cursor_papel("app", self.tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            com,
            ABRIR.sql,
            ABRIR.args(self.tenant, self.encomenda, "pagamento_duplicado", VALOR,
                       "AOA", str(uuid.uuid4())),
        )

    def test_a_porta_so_tem_execute_para_o_papel_do_pay(self) -> None:
        self.semente.execute(
            "SELECT r.rolname FROM pg_roles r "
            " WHERE has_function_privilege(r.oid, "
            "  'platform.abrir_caso_de_reembolso(uuid, uuid, text, bigint, text, "
            "uuid)', 'EXECUTE') AND NOT r.rolsuper "
            "   AND r.rolname LIKE 'kamba\\_%%' ORDER BY 1"
        )
        com_execute = [linha[0] for linha in self.semente.fetchall()]
        # O dono da funcao (o `kamba_migrator`) tem-no sempre.
        self.assertEqual(
            [p for p in com_execute if p != "kamba_migrator"],
            ["kamba_pay"],
        )


class TestDuplicadoChegaAoCom(ComLedger):
    """O criterio 2: o `pagamento_duplicado` no `payment_outbox_map`."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.encomenda = self.criar_encomenda(self.tenant)
        self.cobranca = self.criar_cobranca(
            self.tenant, self.conta, order_id=self.encomenda
        )

    def test_o_duplicado_sai_como_payment_confirmed_valido(self) -> None:
        import jsonschema

        from tests_pagamentos.test_fks_e_mapa import esquema, verificador

        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(cursor, self.cobranca, self.conta, "pagamento_confirmado")
        segundo = 1_234_500
        duplicado = self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_duplicado",
            p_decisao="informativo", p_valor_minor=segundo,
        )
        self.confirmar(cursor, self.tenant)
        self.assertEqual(duplicado[3], "paga", "o duplicado nao move a cobranca")
        self.assertIsNotNone(duplicado[4], "o duplicado produz evento de dominio")

        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox WHERE event_id = %s",
            (duplicado[4],),
        )
        envelope = self.semente.fetchone()[0]
        if isinstance(envelope, str):
            envelope = json.loads(envelope)
        self.assertEqual(envelope["tipo"], "payment.confirmed")
        self.assertEqual(envelope["agregado"]["tipo"], "order")
        self.assertEqual(envelope["agregado"]["id"], self.encomenda)
        self.assertEqual(envelope["payload"]["valor_minor"], segundo,
                         "o valor e o do segundo pagamento, que e o que se devolve")
        self.assertIs(envelope["payload"]["autenticacao"]["authn_ok"], True)
        jsonschema.validate(
            envelope, esquema("payment.confirmed"), format_checker=verificador()
        )

    def test_um_duplicado_sem_autenticacao_nao_publica(self) -> None:
        """A `payment_evt_payload` da `0035` recusa o confirmado sem `authn_ok`.

        Com o mapa, um `pagamento_duplicado` com `authn_ok` falso deixa de se
        gravar em silencio e passa a ser recusado: e o lado certo, porque o
        evento que ele produzia era um pagamento nao autenticado a chegar ao COM.
        O unico escritor do tipo (o veredicto `duplo` do `gates.ts`) so o
        prescreve depois do G1.
        """
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(cursor, self.cobranca, self.conta, "pagamento_confirmado")
        self.confirmar(cursor, self.tenant)
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="pagamento_duplicado",
            p_account_id=self.conta,
            p_decisao="informativo",
            p_authn_ok=False,
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
