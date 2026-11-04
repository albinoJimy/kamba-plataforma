"""Criterio 8: os eventos saem pelo outbox, na mesma transaccao e sem PII.

O que so aqui se prova, e nenhum duplo de teste pode: que uma falha depois da
emissao reverte **as duas** escritas — a transicao e o evento —, porque o
`evt_emitir` corre na transaccao de quem chama. Num duplo de teste as duas
escritas sao dois objectos em memoria e a reversao e uma afirmacao.

E prova-se tambem a guarda de PII da `0004` sobre **estes** payloads: um
`order.created` com um telefone dentro e recusado pela base com
`check_violation`, antes de qualquer escrita no outbox.

## Cinco tipos e nao seis, e o sexto foi decidido fora

O criterio 8 enumera seis eventos. **Cinco** tem contrato publicado em
`contratos/eventos/` e estao nos trinta e oito tipos que o dicionario §3.5 fixa;
o sexto — `order.reconciliation_issue` — nao tem contrato, nao esta no §3.5 e
nao esta no `docs/tecnica/06` §5. **Estava** so no §12 do `docs/tecnica/03`, que
e o documento que a divida documental 37 descreve como «um segundo catalogo de
eventos, paralelo ao do `docs/tecnica/06` §5, e discorda dele em nomes e em
payloads» — e a **2026-11-04 o fundador decidiu que o evento nao existe**, pelo
que a linha saiu do §12 e a divida 174 ficou riscada.

Este ficheiro mede os cinco e mede a **ausencia** do sexto. Essa medicao nasceu
para que a ausencia fosse um facto verificado e nao uma omissao, e depois da
decisao **mudou de papel: passa a guarda-la**. O que fica no lugar do evento e a
linha de `order_reconciliation_issues`, que o `test_reconciliacao` mede.
"""

from __future__ import annotations

import json

import pg8000.dbapi
from tests.base import VIOLACAO_DE_CHECK, sqlstate
from tests_encomendas.base import TOTAL, ComEncomendas
from tests_encomendas.consultas import EXERCITADAS, SQL_EMITIR, SQL_GRAFO

#: Os cinco tipos com contrato publicado, e as versoes emitidas.
TIPOS = (
    ("order.created", 1),
    ("order.paid", 1),
    ("order.expired", 1),
    ("order.cancelled", 1),
    ("order.delivered", 1),
)

#: O sexto, que o catalogo nao tem. Ver a nota do modulo.
SEM_CONTRATO = "order.reconciliation_issue"


class TestEmissaoPeloOutbox(ComEncomendas):
    """Criterio 8: envelope validado, agregado `order`, sem PII."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)
        self.encomenda = self.criar_encomenda(self.tenant, self.contacto)

    def _emitir(self, cursor, tipo: str, versao: int, payload: dict) -> str:
        cursor.execute(
            SQL_EMITIR.sql,
            SQL_EMITIR.args(
                tipo,
                versao,
                self.tenant,
                "order",
                self.encomenda,
                json.dumps(payload),
                "P0",
                ["transacao"],
            ),
        )
        return str(cursor.fetchone()[0])

    def test_os_cinco_entram_no_outbox_com_o_agregado_order(self) -> None:
        payloads = {
            "order.created": {
                "order_id": self.encomenda,
                "contact_id": self.contacto,
                "numero_publico": "K7H3Q9",
                "origem": "pme",
                "total_minor": TOTAL,
                "currency": "AOA",
                "entrega_modo": "levantamento",
                "linhas": [{"sku": "arroz-5kg", "qty": 1, "preco_minor": TOTAL}],
            },
            "order.paid": {
                "order_id": self.encomenda,
                "valor_minor": TOTAL,
                "currency": "AOA",
                "paga_via": "provider_autenticado",
            },
            "order.expired": {
                "order_id": self.encomenda,
                "expira_at": "2026-11-04T14:03:11.482Z",
            },
            "order.cancelled": {"order_id": self.encomenda, "motivo": "ttl"},
            "order.delivered": {
                "order_id": self.encomenda,
                "entrega_confirmada_por": "cliente",
            },
        }
        _, cursor = self.ligar_app(self.tenant)
        for tipo, versao in TIPOS:
            with self.subTest(tipo=tipo):
                self._emitir(cursor, tipo, versao, payloads[tipo])
        cursor.execute(
            "SELECT tipo, versao, agregado_tipo, agregado_id, agregado_seq "
            "  FROM platform.events_outbox WHERE tenant_id = %s ORDER BY agregado_seq",
            (self.tenant,),
        )
        linhas = [tuple(linha) for linha in cursor.fetchall()]
        self.assertEqual(
            linhas,
            [
                (tipo, versao, "order", self.encomenda, n)
                for n, (tipo, versao) in enumerate(TIPOS, start=1)
            ],
            "os cinco na linhagem da **encomenda**: o `agregado_id` e o "
            "`order_id`, pelo que a sequencia e dela e de mais nenhuma",
        )

    def test_o_envelope_leva_classe_pii_p0_e_finalidade_de_transacao(self) -> None:
        _, cursor = self.ligar_app(self.tenant)
        self._emitir(
            cursor,
            "order.cancelled",
            1,
            {"order_id": self.encomenda, "motivo": "cliente_cancela"},
        )
        cursor.execute(
            "SELECT envelope->>'classe_pii', envelope->'finalidades' "
            "  FROM platform.events_outbox WHERE tenant_id = %s",
            (self.tenant,),
        )
        classe, finalidades = cursor.fetchone()
        self.assertEqual(classe, "P0")
        self.assertEqual(json.loads(finalidades) if isinstance(finalidades, str) else finalidades, ["transacao"])

    def test_um_payload_com_telefone_e_recusado_pela_guarda_da_0004(self) -> None:
        """A guarda de PII corre **antes** de qualquer escrita (ADR-010)."""
        conexao, cursor = self.ligar_app(self.tenant)
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            self._emitir(
                cursor,
                "order.cancelled",
                1,
                {"order_id": self.encomenda, "motivo": "+244923456789"},
            )
        self.assertEqual(sqlstate(capturado.exception), VIOLACAO_DE_CHECK)
        conexao.rollback()
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.events_outbox WHERE tenant_id = %s",
                (self.tenant,),
            ),
            [(0,)],
            "a guarda corre antes da escrita: o outbox fica vazio",
        )

    def test_nenhum_payload_leva_nome_morada_nem_msisdn(self) -> None:
        """Os sete nomes que o *lint* do §7.3 proibe, contra os cinco payloads.

        Nos dois sentidos com o contrato: o `additionalProperties: false` de
        cada um fecha o conjunto por maquina, e isto verifica o que **este**
        modulo escolheu pôr lá dentro.
        """
        proibidos = ("telefone", "nome", "morada", "texto", "email", "msisdn", "bsuid")
        _, cursor = self.ligar_app(self.tenant)
        self._emitir(
            cursor,
            "order.created",
            1,
            {
                "order_id": self.encomenda,
                "contact_id": self.contacto,
                "numero_publico": "K7H3Q9",
                "origem": "pme",
                "total_minor": TOTAL,
                "currency": "AOA",
                "entrega_modo": "levantamento",
                "linhas": [{"sku": "arroz-5kg", "qty": 1, "preco_minor": TOTAL}],
            },
        )
        cursor.execute(
            "SELECT jsonb_object_keys(envelope->'payload') "
            "  FROM platform.events_outbox WHERE tenant_id = %s",
            (self.tenant,),
        )
        chaves = {str(chave) for (chave,) in cursor.fetchall()}
        self.assertTrue(chaves)
        for proibido in proibidos:
            with self.subTest(proibido=proibido):
                self.assertEqual(
                    [chave for chave in chaves if proibido in chave],
                    [],
                )

    def test_o_envelope_de_outro_tenant_e_recusado(self) -> None:
        """ISO-43..46: «o `tenant_id` do envelope é validado contra a sessão».

        O critério 8 cita-os, e são do KAM-005 — o que os impõe é o `WITH CHECK`
        da política do `events_outbox` mais o `SECURITY INVOKER` do
        `evt_emitir`. Mede-se aqui outra vez porque é por **este** caminho que
        os cinco eventos saem: emitir um `order.cancelled` com o `tenant_id` de
        B a partir do contexto de A é a forma concreta que o ataque tomaria.
        """
        outro = self.criar_tenant()
        conexao, cursor = self.ligar_app(self.tenant)
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            cursor.execute(
                SQL_EMITIR.sql,
                SQL_EMITIR.args(
                    "order.cancelled",
                    1,
                    outro,
                    "order",
                    self.encomenda,
                    json.dumps({"order_id": self.encomenda, "motivo": "ataque"}),
                    "P0",
                    ["transacao"],
                ),
            )
        conexao.rollback()
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.events_outbox WHERE tenant_id = %s",
                (outro,),
            ),
            [(0,)],
        )

    def test_o_sexto_tipo_nao_tem_contrato_publicado(self) -> None:
        """A medicao da ausencia, que depois da decisao a guarda. Ver a nota.

        O `evt_emitir` **aceitaria** o tipo — nao valida contra o catalogo —, e
        e exactamente por isso que isto se mede aqui: a recusa vem do
        `validarPayload` do modulo e do publicador, e nao da base. Um tipo sem
        contrato no outbox parava do outro lado da fila.
        """
        from pathlib import Path

        raiz = Path(__file__).resolve().parents[2]
        self.assertFalse(
            (raiz / "contratos" / "eventos" / SEM_CONTRATO).exists(),
            "o fundador decidiu a 2026-11-04 que este evento nao existe, e a "
            "linha dele saiu do §12 do docs/tecnica/03. Se alguem publicar o "
            "contrato, nao basta fazer cair este ensaio: reabre a decisao, "
            "porque leva a emenda do dicionario §3.5 (trinta e oito tipos) e a "
            "contagem que tres ficheiros repetem",
        )
        for tipo, _ in TIPOS:
            with self.subTest(tipo=tipo):
                self.assertTrue(
                    (raiz / "contratos" / "eventos" / tipo / "v1.schema.json").exists()
                )


class TestTransaccionalidade(ComEncomendas):
    """Criterio 2: a transicao e o evento entram ou nao entram juntos."""

    def test_uma_falha_depois_da_emissao_reverte_as_duas_escritas(self) -> None:
        tenant = self.criar_tenant()
        encomenda = self.criar_encomenda(tenant)
        conexao, cursor = self.ligar_app(tenant)
        # **Sem `SET CONSTRAINTS ALL IMMEDIATE`**, e a razao e a ordem: com o
        # *trigger* imediato, o `UPDATE` do estado falha sozinho (`KA005`,
        # medido) porque o registo ainda nao existe — e este ensaio precisa de
        # chegar a emitir para poder provar que a emissao reverte com a
        # transicao. Diferido, as tres escritas entram e a falha injectada
        # leva-as todas.
        cursor.execute(
            "UPDATE platform.orders_mirror SET estado = 'cancelada', "
            "       version = version + 1 "
            " WHERE tenant_id = %s AND id = %s",
            (tenant, encomenda),
        )
        cursor.execute(
            "INSERT INTO platform.order_state_log "
            "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
            "VALUES (%s, %s, 'criada', 'cancelada', 2, 'cliente_cancela', 'agente')",
            (tenant, encomenda),
        )
        cursor.execute(
            SQL_EMITIR.sql,
            SQL_EMITIR.args(
                "order.cancelled",
                1,
                tenant,
                "order",
                encomenda,
                json.dumps({"order_id": encomenda, "motivo": "cliente_cancela"}),
                "P0",
                ["transacao"],
            ),
        )
        # A falha injectada: a mesma transicao outra vez, que a unicidade do
        # registo recusa. E o que acontece a uma repeticao, e e por isso que o
        # ensaio a usa em vez de um erro inventado.
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            cursor.execute(
                "INSERT INTO platform.order_state_log "
                "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
                "VALUES (%s, %s, 'criada', 'cancelada', 2, 'repetida', 'agente')",
                (tenant, encomenda),
            )
        conexao.rollback()

        self.assertEqual(self.estado_de(encomenda), ("criada", 1))
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.events_outbox WHERE tenant_id = %s",
                (tenant,),
            ),
            [(0,)],
            "o evento desapareceu com a transicao: e isso que faz do outbox um "
            "outbox e nao um segundo sistema a precisar de reconciliacao",
        )
        self.assertEqual(
            self.consultar(
                "SELECT count(*) FROM platform.order_state_log WHERE order_id = %s",
                (encomenda,),
            ),
            [(0,)],
        )


class TestCoberturaDasConsultas(ComEncomendas):
    """As consultas do modulo sao exercitadas, e nos dois sentidos."""

    def test_as_consultas_declaradas_existem_no_modulo(self) -> None:
        """Uma declaracao morta nesta suite e um nome que o modulo nao tem."""
        from tests_encomendas import consultas

        for nome in EXERCITADAS:
            with self.subTest(consulta=nome):
                self.assertTrue(hasattr(consultas, nome))

    def test_o_modulo_nao_tem_consulta_que_a_suite_nao_exercite(self) -> None:
        """O outro sentido: uma consulta nova entra sem ser provada."""
        import re

        from tests_encomendas.consultas import MODULO

        texto = MODULO.read_text(encoding="utf-8")
        declaradas = set(re.findall(r"export const (SQL_[A-Z_]+) = `", texto))
        self.assertEqual(
            declaradas,
            set(EXERCITADAS),
            "uma cadeia SQL nova no modulo tem de entrar no `EXERCITADAS` e ser "
            "corrida contra a base: foi assim que o `SQL_GRELHA` do KAM-047 "
            "chegou com um defeito que nenhuma bateria tocava",
        )

    def test_o_grafo_le_se_pela_consulta_do_modulo(self) -> None:
        _, cursor = self.ligar_app(self.criar_tenant())
        cursor.execute(SQL_GRAFO.sql)
        linhas = cursor.fetchall()
        self.assertEqual(len(linhas), 12, "as doze do nucleo")
