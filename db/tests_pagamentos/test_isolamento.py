"""RLS `FORCE` e o papel estreito: a caixa de isolamento do DoD (ADR-015).

Duas afirmacoes, e a segunda e a que este ticket acrescenta ao que o X-03/X-04
do *gate* 6 ja fazem:

    1  a cobranca e o evento de A nao se veem no contexto de B — o de sempre
    2  a `append_payment_event` corre `SECURITY DEFINER` e **nao** contorna o
       `FORCE`: uma chamada com o contexto de B sobre uma cobranca de A recusa

A segunda e a unica forma de medir a afirmacao central do `db/rls.py`, que nomeia
este ticket como credor. Se o `DEFINER` contornasse o `FORCE`, a porta do ledger
era um caminho para escrever eventos no tenant de outra PME — com um `charge_id`
adivinhado, que e um `uuid` mas nao e um segredo.

O inbox nao tem RLS e nao tem `tenant_id`: o que o isola e o papel, e e isso que
o `TestOPapelEstreito` mede.
"""

from __future__ import annotations

import uuid

from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK
from tests_pagamentos.base import ComLedger

#: As duas tabelas desta revisao com `tenant_id`.
COM_TENANT = ("payment_charges", "payment_events")


class TestRlsDasDuasTabelas(ComLedger):
    """As bandeiras do catalogo e as quatro leituras cruzadas."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant_a = self.criar_tenant()
        self.conta_a = self.criar_conta(self.tenant_a)
        self.cobranca_a = self.criar_cobranca(self.tenant_a, self.conta_a)
        self.tenant_b = self.criar_tenant()
        cursor = self.cursor_papel("app", self.tenant_a)
        self.appendar(
            cursor, self.cobranca_a, self.conta_a, "pagamento_recebido",
            p_decisao="informativo",
        )
        self.confirmar(cursor, self.tenant_a)

    def test_as_duas_tabelas_tem_enable_e_force(self) -> None:
        self.semente.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relkind = 'r' "
            "   AND c.relname = ANY(%s) ORDER BY c.relname",
            (list(COM_TENANT),),
        )
        self.assertEqual(
            [tuple(linha) for linha in self.semente.fetchall()],
            [("payment_charges", True, True), ("payment_events", True, True)],
        )

    def test_o_inbox_e_o_mapa_nao_tem_tenant_id(self) -> None:
        """A afirmacao inversa, e e deliberada.

        O X-05 do *gate* 6 descobre as tabelas **com** `tenant_id` pelo catalogo;
        estas duas ficam fora da verificacao, e por isso tem de haver um ensaio
        que diga que ficam fora **por nao terem a coluna** e nao por alguem a ter
        esquecido. Sem isto, acrescentar um `tenant_id` anulavel ao inbox um dia
        passava sem RLS e sem ninguem notar.
        """
        self.semente.execute(
            "SELECT table_name FROM information_schema.columns "
            " WHERE table_schema = 'platform' AND column_name = 'tenant_id' "
            "   AND table_name IN ('payment_callbacks_inbox', 'payment_outbox_map')"
        )
        self.assertEqual([tuple(l) for l in self.semente.fetchall()], [])

    def test_a_sonda_positiva_ve_as_proprias_linhas(self) -> None:
        """Primeiro. **Sem ela, as leituras cruzadas ficam verdes sobre nada.**

        Uma bateria que afirma «zero linhas» quatro vezes contra tabelas vazias
        passa sem RLS nenhuma. A licao e do `tests_produtos`.
        """
        cursor = self.cursor_papel("app", self.tenant_a)
        for tabela in COM_TENANT:
            with self.subTest(tabela=tabela):
                cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
                self.assertGreaterEqual(int(cursor.fetchone()[0]), 1)

    def test_o_contexto_de_b_nao_ve_nada_de_a(self) -> None:
        cursor = self.cursor_papel("app", self.tenant_b)
        for tabela in COM_TENANT:
            with self.subTest(tabela=tabela):
                cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
                self.assertEqual(int(cursor.fetchone()[0]), 0)

    def test_sem_contexto_nenhum_da_zero_linhas_e_falha_fechada(self) -> None:
        """Sem contexto: zero linhas na leitura, e a escrita recusada **duas vezes**.

        A escrita falha com `23514` e nao com o `42501` da RLS, e isso tem uma
        razao que vale a pena ficar escrita: o *trigger* `assert_beneficiary`
        (G-1, da `0027`) corre **BEFORE INSERT** e e `SECURITY INVOKER` — sem
        contexto de tenant, a politica da `payment_accounts` esconde-lhe a conta
        e ele recusa com «a conta nao existe ou nao e visivel» antes de o
        `WITH CHECK` da `tenant_iso` chegar a ser avaliado.

        Isto e, uma cobranca sem contexto e recusada por **duas** barreiras
        independentes e a primeira ganha. O ensaio afirma a que ganha, e o
        `test_a_rls_recusa_a_cobranca_com_o_tenant_de_outro` a seguir afirma a
        segunda — que de outra forma ficava sem ensaio nenhum, escondida atras
        desta.
        """
        cursor = self.cursor_papel("app", None)
        for tabela in COM_TENANT:
            with self.subTest(tabela=tabela):
                cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
                self.assertEqual(int(cursor.fetchone()[0]), 0)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            "INSERT INTO platform.payment_charges "
            "(tenant_id, order_id, account_id, provider, metodo, amount_minor, "
            " valid_until) VALUES (%s, %s, %s, 'fakeprovider', 'referencia', 1, "
            " now() + interval '1 day')",
            (self.tenant_a, str(uuid.uuid4()), self.conta_a),
        )

    def test_o_with_check_da_cobranca_e_inalcancavel_e_isso_fica_medido(self) -> None:
        """**Um achado, e nao um ensaio de conveniencia.**

        O `WITH CHECK` da `tenant_iso` sobre a `payment_charges` nao se consegue
        alcancar com o `kamba_app`, e tentei as duas formas que ha:

            contexto A, `tenant_id` B    o `assert_beneficiary` (G-1, da `0027`)
                                         ve a conta de A, compara com o
                                         `tenant_id` da linha e recusa — «uma
                                         conta nunca e partilhada entre
                                         tenants»
            contexto C, `tenant_id` A    o G-1 e `SECURITY INVOKER` e a
                                         politica da `payment_accounts` esconde
                                         -lhe a conta: recusa com «nao existe ou
                                         nao e visivel»

        Nos dois casos o *trigger* corre `BEFORE INSERT` e ganha, pelo que o
        `WITH CHECK` nunca e avaliado num `INSERT` de cobranca de encomenda. Nao
        e um defeito — sao duas barreiras independentes e a primeira da a
        mensagem mais util —, mas **e preciso que alguem o saiba**: quem ler «a
        tabela tem `tenant_iso` com `WITH CHECK`» supoe que ha um ensaio a
        prova-lo, e nao ha nesta tabela.
        
        Onde o `WITH CHECK` **e** medido e no `payment_events`, pela porta: ver
        o `TestADefinerSobRls`, onde a `append_payment_event` corre
        `SECURITY DEFINER` e e a politica que a prende.
        """
        cursor = self.cursor_papel("app", self.tenant_a)
        sql = (
            "INSERT INTO platform.payment_charges "
            "(tenant_id, order_id, account_id, provider, metodo, "
            " amount_minor, valid_until) "
            "VALUES (%s, %s, %s, 'fakeprovider', 'referencia', 1, "
            " now() + interval '1 day')"
        )
        # Contexto A, tenant da linha B: o G-1 compara e recusa.
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            cursor,
            sql,
            (self.tenant_b, str(uuid.uuid4()), self.conta_a),
        )
        # Contexto C, tenant da linha A: o G-1 nao ve a conta e recusa.
        terceiro = self.criar_tenant()
        outro = self.cursor_papel("app", terceiro)
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            outro,
            sql,
            (self.tenant_a, str(uuid.uuid4()), self.conta_a),
        )

    def test_um_contexto_que_nao_e_uuid_rebenta_em_vez_de_devolver_linhas(self) -> None:
        cursor = self.cursor_papel("app", "nao-e-uuid")
        # `22P02`: invalid_text_representation. Falha pelo lado ruidoso.
        self.assertErroSql(
            "22P02", cursor, "SELECT count(*) FROM platform.payment_charges"
        )


class TestADefinerSobRls(ComLedger):
    """A afirmacao central do `db/rls.py`, medida sobre a porta deste ticket."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant_a = self.criar_tenant()
        self.conta_a = self.criar_conta(self.tenant_a)
        self.cobranca_a = self.criar_cobranca(self.tenant_a, self.conta_a)
        self.tenant_b = self.criar_tenant()

    def test_a_porta_recusa_a_cobranca_de_outro_tenant(self) -> None:
        """O `charge_id` de A, chamado com o contexto de B.

        Recusa com `check_violation` e com a mensagem das **duas**
        possibilidades — «nao existe ou nao e visivel» —, porque sob RLS a funcao
        nao as distingue. E a mesma honestidade de mensagem que o
        `assert_beneficiary` da `0027` escreveu.
        """
        cursor = self.cursor_papel("app", self.tenant_b)
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca_a,
            p_tipo_evento="pagamento_recebido",
            p_account_id=self.conta_a,
            p_decisao="informativo",
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
        self.confirmar(cursor, self.tenant_b)
        self.assertEqual(
            self.eventos_da_cobranca(self.cobranca_a),
            [],
            "o DEFINER nao escreveu no tenant de A com o contexto de B",
        )

    def test_a_porta_recusa_sem_contexto_de_tenant(self) -> None:
        """Falha fechada: sem contexto, a politica esconde toda a cobranca.

        E a razao de o *worker* do §5.1 correr **depois** do 2xx, com o tenant
        ja resolvido do *token*: a porta nao e chamavel antes disso, e nao e por
        convencao.
        """
        cursor = self.cursor_papel("app", None)
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca_a,
            p_tipo_evento="pagamento_recebido",
            p_account_id=self.conta_a,
            p_decisao="informativo",
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)

    def test_a_mesma_chamada_com_o_contexto_certo_passa(self) -> None:
        """A sonda positiva das duas acima."""
        cursor = self.cursor_papel("app", self.tenant_a)
        linha = self.appendar(
            cursor, self.cobranca_a, self.conta_a, "pagamento_recebido",
            p_decisao="informativo",
        )
        self.confirmar(cursor, self.tenant_a)
        self.assertEqual(linha[1], 1)


class TestOPapelEstreito(ComLedger):
    """`kamba_pay_hooks`: o que ele alcanca, e o muito que nao alcanca."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.token = uuid.uuid4().hex
        self.conta = self.criar_conta(self.tenant, wt=self.token)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_resolve_o_token_sem_contexto_de_tenant(self) -> None:
        """A razao de ser do papel: o §5.1 resolve o *token* antes de saber de quem e.

        Sem contexto, de proposito — e isso tem de **funcionar**, nao de falhar
        fechado: e a unica leitura do sistema em que nao ha tenant para pôr no
        contexto porque e ela que o descobre.
        """
        cursor = self.cursor_papel("pay_hooks", None)
        cursor.execute(
            "SELECT account_id, tenant_id, provider, estado "
            "  FROM platform.resolve_webhook_token(%s)",
            (self.token,),
        )
        self.assertEqual(
            [(str(a), str(t), p, e) for a, t, p, e in cursor.fetchall()],
            [(self.conta, self.tenant, "fakeprovider", "ativo")],
        )

    def test_um_token_desconhecido_resolve_a_zero_linhas(self) -> None:
        """O 404 uniforme do criterio 7 comeca aqui: zero linhas, nao um erro.

        Um erro distinguia «token mal formado» de «token que nao existe», e isso
        e informacao para quem varre tokens.
        """
        cursor = self.cursor_papel("pay_hooks", None)
        cursor.execute(
            "SELECT count(*) FROM platform.resolve_webhook_token(%s)",
            (uuid.uuid4().hex,),
        )
        self.assertEqual(int(cursor.fetchone()[0]), 0)

    def test_grava_no_inbox_sem_contexto_de_tenant(self) -> None:
        cursor = self.cursor_papel("pay_hooks", None)
        cursor.execute(
            "INSERT INTO platform.payment_callbacks_inbox "
            "(account_id, body, body_hash) VALUES (%s, %s, sha256(%s)) "
            "RETURNING id, estado",
            (self.conta, b'{"ref":"x"}', b'{"ref":"x"}'),
        )
        identificador, estado = tuple(cursor.fetchone())
        self.assertIsNotNone(identificador)
        self.assertEqual(estado, "recebido", "o corpo e duravel antes de haver veredicto")
        self.confirmar(cursor, self.tenant)

    def test_grava_no_inbox_com_conta_nula(self) -> None:
        """O `token_desconhecido`: a entrega guarda-se mesmo sem conta.

        E o que torna um varrimento de *tokens* auditavel. Sem esta linha, o 404
        uniforme nao deixava rasto nenhum — e o §5.1 escreve `inbox.insert`
        **antes** de resolver qualquer coisa.
        """
        cursor = self.cursor_papel("pay_hooks", None)
        cursor.execute(
            "INSERT INTO platform.payment_callbacks_inbox "
            "(account_id, body, body_hash, estado) "
            "VALUES (NULL, %s, sha256(%s), 'token_desconhecido') RETURNING id",
            (b"{}", b"{}"),
        )
        self.assertIsNotNone(cursor.fetchone()[0])
        self.confirmar(cursor, self.tenant)

    def test_marca_o_estado_mas_nao_reescreve_o_corpo(self) -> None:
        """O `GRANT UPDATE` e **por coluna**: o que entrou pela rede nao se muta.

        E o que faz do inbox uma prova em vez de um registo de trabalho. Sem a
        matriz por coluna, quem marca `hmac_invalido` podia reescrever o corpo
        que o HMAC nao cobriu — e ninguem o saberia.
        """
        cursor = self.cursor_papel("pay_hooks", None)
        cursor.execute(
            "INSERT INTO platform.payment_callbacks_inbox "
            "(account_id, body, body_hash) VALUES (%s, %s, sha256(%s)) RETURNING id",
            (self.conta, b"{}", b"{}"),
        )
        identificador = cursor.fetchone()[0]
        cursor.execute(
            "UPDATE platform.payment_callbacks_inbox "
            "   SET estado = 'hmac_invalido', authn_ok = false, processado_at = now() "
            " WHERE id = %s",
            (identificador,),
        )
        for coluna, valor in (("body", b"adulterado"), ("body_hash", bytes(32))):
            with self.subTest(coluna=coluna):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    f"UPDATE platform.payment_callbacks_inbox SET {coluna} = %s "
                    " WHERE id = %s",
                    (valor, identificador),
                )
        self.confirmar(cursor, self.tenant)

    def test_nao_alcanca_a_cobranca_o_ledger_nem_a_porta(self) -> None:
        """O que o papel **nao** pode, que e onde a estreiteza vive.

        O ledger escreve-se no *worker*, como `kamba_app`, com o contexto
        resolvido — e nao no processo que atende a rede.
        """
        cursor = self.cursor_papel("pay_hooks", None)
        for instrucao, parametros in (
            ("SELECT count(*) FROM platform.payment_charges", ()),
            ("SELECT count(*) FROM platform.payment_events", ()),
            (
                "SELECT * FROM platform.append_payment_event("
                "p_charge_id => %s, p_tipo_evento => 'pagamento_recebido', "
                "p_account_id => %s, p_valor_minor => 1, "
                "p_authn_method => 'hmac', p_authn_ok => true, "
                "p_decisao => 'informativo')",
                (self.cobranca, self.conta),
            ),
        ):
            with self.subTest(instrucao=instrucao[:40]):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, cursor, instrucao, parametros
                )

    def test_nao_le_as_credenciais_nem_as_instrucoes_manuais(self) -> None:
        """O `GRANT SELECT` em `payment_accounts` e por coluna.

        A politica `pay_hooks_token` da-lhe as linhas de **todos** os tenants —
        tem de dar, porque ele resolve um *token* sem saber de quem e —, e o que
        limita o que ele ve e o `GRANT`. As duas barreiras juntas sao mais
        estreitas do que uma `SECURITY DEFINER`, que por dentro alcancava a
        tabela inteira.
        """
        cursor = self.cursor_papel("pay_hooks", None)
        for coluna in ("credenciais_ref", "manual_instrucoes", "checklist", "iec"):
            with self.subTest(coluna=coluna):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    f"SELECT {coluna} FROM platform.payment_accounts LIMIT 1",
                )

    def test_a_politica_por_papel_nao_abre_nada_aos_outros(self) -> None:
        """A `pay_hooks_token` e `TO kamba_pay_hooks`, e nao se soma a `tenant_iso`.

        E o risco de que a `0027` avisa — «politicas permissivas somam-se por
        OU» —, e aqui mede-se que nao se soma: o `kamba_app` com o contexto de um
        tenant continua a nao ver a conta de outro.
        """
        outro = self.criar_tenant()
        self.criar_conta(outro)
        cursor = self.cursor_papel("app", self.tenant)
        cursor.execute(
            "SELECT count(*) FROM platform.payment_accounts WHERE tenant_id = %s",
            (outro,),
        )
        self.assertEqual(int(cursor.fetchone()[0]), 0)
