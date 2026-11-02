"""A porta: privilegios, imutabilidade e as recusas que o `CHECK` nao pode fazer.

Criterios 1, 2 e 8 do bloco KAM-053, mais a caixa do DoD que diz «nao existe
caminho de codigo que escreva `paga` fora de `append_payment_event`».

**A caixa do DoD nao se prova com um `grep`.** Um `grep` por `UPDATE
payment_charges` mostra o que o codigo de hoje faz; o que se quer e que o codigo
de amanha tambem nao o consiga. Por isso a prova e por privilegio: o
`TestNaoHaSegundaPorta` tenta escrever `paga` por **todas** as vias que um papel
de aplicacao tem — `UPDATE` directo, `INSERT` no ledger, `UPDATE` do ledger,
`TRUNCATE` — e exige o `SQLSTATE` de cada recusa.
"""

from __future__ import annotations

import json
import uuid

from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
)
from tests_pagamentos.base import VALOR, ComLedger

#: Os papeis de aplicacao que **nao** podem mutar o ledger. O `kamba_ops` do
#: criterio 1 **nao existe** nesta base: os papeis sao oito e nenhum se chama
#: assim (`db/bootstrap.py`), e o dicionario §3.2 registra-o como **variante
#: proibida**. Os tres que aqui estao sao a leitura mais forte possivel da letra
#: do criterio:
#:
#:     app     e o papel com que o PAY corre em producao
#:     batch   tem `BYPASSRLS`: e o mais privilegiado dos tres, e se ele nao
#:             consegue, nenhum papel sujeito a RLS consegue
#:     audit   e o papel de ops que existe — quem audita «para onde foi o
#:             dinheiro desta venda»
#:
#: Criar um `kamba_ops` para satisfazer a letra era criar um papel sem chamador.
#: Os dois padroes da guarda de PII, como o PostgreSQL os guarda no corpo
#: das duas funcoes. Escritos aqui uma vez para o ensaio de paridade os
#: comparar sem os repetir — e para quem os mudar num sitio ver que ha dois.
PADRAO_244 = r"\+?244 ?9[0-9]{8}"
PADRAO_INTERNACIONAL = r'"\+[0-9]{9,15}"'

PAPEIS_DE_APLICACAO = ("app", "batch", "audit")


class TestPrivilegiosDoLedger(ComLedger):
    """Criterio 1: a escrita directa no ledger nao existe para papel nenhum."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_insert_directo_no_ledger_falha_por_privilegio(self) -> None:
        """`42501`, e **antes** de qualquer `CHECK`.

        A ordem importa: se falhasse por `CHECK`, a barreira era o conteudo da
        linha e bastava escrever uma linha valida para a contornar. Falhando por
        privilegio, nao ha linha nenhuma que passe — e e por isso que a linha
        deste ensaio e **deliberadamente valida** em tudo o mais.
        """
        for identidade in PAPEIS_DE_APLICACAO:
            with self.subTest(papel=identidade):
                cursor = self.cursor_papel(identidade, self.tenant)
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    "INSERT INTO platform.payment_events ("
                    "  tenant_id, charge_id, order_id, provider, account_id,"
                    "  referencia, tipo_evento, sequencia, valor_minor,"
                    "  authn_method, authn_ok, decisao, actor_kind,"
                    "  payload_hash, row_hash)"
                    " VALUES (%s, %s, %s, 'fakeprovider', %s, 'REF1',"
                    "  'pagamento_recebido', 1, %s, 'hmac', true, 'informativo',"
                    "  'provider', sha256('{}'::bytea), sha256('{}'::bytea))",
                    (self.tenant, self.cobranca, str(uuid.uuid4()), self.conta, VALOR),
                )

    def test_a_porta_funciona_como_app(self) -> None:
        """O caminho legitimo ao lado. **Sem ele, o ensaio acima nao diz nada.**

        Uma porta que recusasse tudo deixava o ensaio dos privilegios verde
        sobre um ledger onde nao se consegue escrever nada — que e a forma mais
        caro de um teste passar. E o `SELECT * FROM` e a forma do criterio 1.
        """
        cursor = self.cursor_papel("app", self.tenant)
        linha = self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        event_id, sequencia, row_hash, estado_novo, outbox = linha
        self.assertIsNotNone(event_id)
        self.assertEqual(sequencia, 1)
        self.assertEqual(len(row_hash), 32, "o row_hash e um sha256")
        self.assertEqual(
            estado_novo, "emitida", "um pagamento_recebido nao move o estado"
        )
        self.assertIsNone(
            outbox, "sem mapeamento de outbox nao ha evento de dominio"
        )

    def test_update_delete_e_truncate_no_ledger_falham(self) -> None:
        """Criterio 1: as tres mutacoes, para cada papel de aplicacao.

        O `TRUNCATE` sai `42501` por privilegio (nenhum papel o tem) e o
        *trigger* `payment_events_sem_truncate` e o que prende quem **tem** — ver
        o `TestNemOSuperutilizador`.
        """
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        self.confirmar(cursor, self.tenant)

        for identidade in PAPEIS_DE_APLICACAO:
            for instrucao in (
                "UPDATE platform.payment_events SET motivo = 'x'",
                "DELETE FROM platform.payment_events",
                "TRUNCATE platform.payment_events",
            ):
                with self.subTest(papel=identidade, instrucao=instrucao.split()[0]):
                    alvo = self.cursor_papel(identidade, self.tenant)
                    self.assertErroSql(PRIVILEGIO_INSUFICIENTE, alvo, instrucao)


class TestNemOSuperutilizador(ComLedger):
    """O `deny_mutation` prende quem os `REVOKE` nao prendem.

    E a razao de a imutabilidade nao ser uma matriz de privilegios: o
    administrador tem tudo, e tem de ser recusado na mesma. Sem este ensaio, a
    afirmacao «ledger append-only» valia so para os papeis que alguem se lembrou
    de listar.

    O `deny_mutation` levanta `insufficient_privilege` (`42501`) de proposito, e
    nao `check_violation`: o que falha nao e o conteudo da linha — e a operacao.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        self.confirmar(cursor, self.tenant)

    def test_o_administrador_tambem_nao_muta_o_ledger(self) -> None:
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        for instrucao in (
            "UPDATE platform.payment_events SET motivo = 'adulterado'",
            "DELETE FROM platform.payment_events",
            "TRUNCATE platform.payment_events",
        ):
            with self.subTest(instrucao=instrucao.split()[0]):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, instrucao)

    def test_o_administrador_le_o_ledger(self) -> None:
        """A sonda positiva: a recusa acima e da mutacao, nao da tabela.

        Sem isto, os tres casos acima ficavam verdes contra uma tabela que o
        administrador nem consegue abrir.
        """
        self.assertEqual(
            len(self.eventos_da_cobranca(self.cobranca)),
            1,
            "o evento semeado tem de estar la para o UPDATE ter o que mutar",
        )


class TestNaoHaSegundaPorta(ComLedger):
    """A caixa do DoD: `paga` nao se escreve fora da porta.

    Quatro vias, e as quatro recusadas pela base:

        1  `UPDATE payment_charges SET estado = 'paga'` — nenhum papel tem
           `UPDATE` nesta tabela
        2  `INSERT` no ledger com `pagamento_confirmado` — nenhum papel tem
           `INSERT`
        3  a porta com `authn_ok = false` — a funcao recusa
        4  a porta com `decisao = 'rejeitada'` — o `CHECK` recusa

    E uma via que **passa**, que e a razao de as quatro valerem.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_ninguem_tem_update_em_payment_charges(self) -> None:
        """Via 1. Inclui o `kamba_batch`, que tem `BYPASSRLS`.

        O `42501` e o que distingue esta recusa de uma recusa por RLS: com
        `BYPASSRLS` a politica nao se aplica, e o que resta e o privilegio que
        ninguem tem. Sem este ensaio, a barreira podia ser a politica — e um
        processo de plataforma contorna a politica.
        """
        for identidade in PAPEIS_DE_APLICACAO:
            with self.subTest(papel=identidade):
                cursor = self.cursor_papel(identidade, self.tenant)
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    cursor,
                    "UPDATE platform.payment_charges SET estado = 'paga' "
                    " WHERE id = %s",
                    (self.cobranca,),
                )
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")

    def test_a_porta_recusa_confirmar_sem_autenticacao(self) -> None:
        """Via 3: `authn_ok = false`. A funcao, antes do `CHECK`.

        O `CHECK` `confirmar_exige_autenticacao` tambem o recusaria — e por isso
        este ensaio e sobre a funcao: ela recusa **primeiro**, com a mensagem que
        nomeia o G1, e e isso que o contrato do §6.2 chama
        «cinto-e-suspensorios».
        """
        cursor = self.cursor_papel("app", self.tenant)
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="pagamento_confirmado",
            p_account_id=self.conta,
            p_authn_ok=False,
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")
        self.assertEqual(self.eventos_da_cobranca(self.cobranca), [])

    def test_a_porta_recusa_confirmar_com_decisao_rejeitada(self) -> None:
        """Via 4: `decisao = 'rejeitada'` num `pagamento_confirmado`.

        Aqui quem recusa e a maquina de estados — `next_state` so da `paga` com
        `decisao = 'aceite'` —, e depois dela o `CHECK`. As duas barreiras
        existem, e a ordem e a que faz o ledger nao ficar com a linha escrita.
        """
        cursor = self.cursor_papel("app", self.tenant)
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="pagamento_confirmado",
            p_account_id=self.conta,
            p_decisao="rejeitada",
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
        self.assertEqual(self.eventos_da_cobranca(self.cobranca), [])

    def test_a_porta_recusa_valor_diferente_do_da_cobranca(self) -> None:
        """Criterio 2: o G4, **na funcao**, porque o `CHECK` nao ve a cobranca.

        E a recusa mais importante das tres: um `CHECK` nunca a pode fazer —
        nenhuma restricao de `payment_events` consegue ler o `amount_minor` da
        `payment_charges`. Logo se esta recusa nao estiver na funcao, nao esta em
        sitio nenhum.
        """
        cursor = self.cursor_papel("app", self.tenant)
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="pagamento_confirmado",
            p_account_id=self.conta,
            p_valor_minor=VALOR - 1,
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "emitida")

    def test_a_porta_recusa_conta_diferente_da_da_cobranca(self) -> None:
        """Criterio 2: o G2, e para **todos** os tipos, nao so para o confirmado.

        A segunda conta e do **mesmo** tenant de proposito: se fosse de outro, a
        RLS podia ser a razao da recusa e o ensaio nao distinguia as duas.
        """
        outra = self.criar_conta(self.tenant)
        cursor = self.cursor_papel("app", self.tenant)
        for tipo, decisao in (
            ("pagamento_confirmado", "aceite"),
            ("pagamento_recebido", "informativo"),
        ):
            with self.subTest(tipo=tipo):
                sql, args = self.sql_da_porta(
                    p_charge_id=self.cobranca,
                    p_tipo_evento=tipo,
                    p_account_id=outra,
                    p_decisao=decisao,
                )
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)

    def test_a_via_que_passa_escreve_paga(self) -> None:
        """A sonda positiva das quatro vias acima.

        Sem ela, uma funcao que recusasse **tudo** deixava este ficheiro inteiro
        verde e a `paga` inalcancavel — o que nao e «o ledger esta seguro», e «o
        pagamento nao funciona».
        """
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        linha = self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_confirmado"
        )
        self.confirmar(cursor, self.tenant)
        self.assertEqual(linha[3], "paga")
        self.assertEqual(self.estado_da_cobranca(self.cobranca), "paga")


class TestIdempotenciaDaEntrega(ComLedger):
    """Criterio 4: o G7, provado por **teste** e nao pelo indice.

    O bloco da sessao diz-o por extenso: «dois callbacks com a mesma entrega dao
    um evento, e e o que o indice existe para garantir — prova-o com um teste,
    nao com o indice». A diferenca e real: um indice parcial com o predicado
    errado existe e nao morde, e lê-lo no DDL nao distingue um caso do outro.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_o_mesmo_provider_event_id_duas_vezes_da_uma_linha(self) -> None:
        entrega = f"ev-{uuid.uuid4().hex[:10]}"
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo", p_provider_event_id=entrega,
        )
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="pagamento_recebido",
            p_account_id=self.conta,
            p_decisao="informativo",
            p_provider_event_id=entrega,
        )
        self.assertErroSql(VIOLACAO_DE_UNICIDADE, cursor, sql, args)
        self.confirmar(cursor, self.tenant)
        self.assertEqual(
            [(t, s) for t, s, _, _ in self.eventos_da_cobranca(self.cobranca)],
            [("pagamento_recebido", 1)],
            "o segundo callback nao escreve nada: uma linha no ledger (G7)",
        )

    def test_dez_duplicados_dao_um_efeito(self) -> None:
        """A caixa do DoD: «duplicados x10 produzem 1 efeito»."""
        entrega = f"ev-{uuid.uuid4().hex[:10]}"
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo", p_provider_event_id=entrega,
        )
        self.confirmar(cursor, self.tenant)
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="pagamento_recebido",
            p_account_id=self.conta,
            p_decisao="informativo",
            p_provider_event_id=entrega,
        )
        for tentativa in range(10):
            with self.subTest(tentativa=tentativa):
                self.assertErroSql(VIOLACAO_DE_UNICIDADE, cursor, sql, args)
        self.assertEqual(len(self.eventos_da_cobranca(self.cobranca)), 1)

    def test_a_mesma_referencia_em_duas_contas_e_aceite(self) -> None:
        """Criterio 4, segunda metade: a entidade faz parte da identidade.

        Uma referencia Multicaixa e **Entidade + Referencia** (`evidencia/E2`
        §2): duas PMEs podem ter o mesmo numero, e um indice sem a conta
        recusava a segunda — que e o defeito que o §6.1 corrige no documento 11.
        """
        self.semente.execute(
            "SELECT referencia FROM platform.payment_charges WHERE id = %s",
            (self.cobranca,),
        )
        referencia = self.semente.fetchone()[0]
        outra_conta = self.criar_conta(self.tenant)
        outra_cobranca = self.criar_cobranca(
            self.tenant, outra_conta, referencia=referencia
        )
        cursor = self.cursor_papel("app", self.tenant)
        for cobranca, conta in (
            (self.cobranca, self.conta),
            (outra_cobranca, outra_conta),
        ):
            linha = self.appendar(
                cursor, cobranca, conta, "pagamento_recebido",
                p_decisao="informativo",
                p_provider_event_id=f"ev-{uuid.uuid4().hex[:10]}",
            )
            self.assertEqual(linha[1], 1, "cada conta tem a sua sequencia")
        self.confirmar(cursor, self.tenant)

    def test_o_mesmo_provider_event_id_noutra_conta_e_aceite(self) -> None:
        """O indice e por `(provider, account_id, provider_event_id)`.

        Dois facilitadores — ou duas contas do mesmo — podem numerar as entregas
        a partir de 1. Sem a conta no indice, a segunda PME a receber a entrega
        numero 1 ficava sem o seu pagamento registado.
        """
        entrega = f"ev-{uuid.uuid4().hex[:10]}"
        outra_conta = self.criar_conta(self.tenant)
        outra_cobranca = self.criar_cobranca(self.tenant, outra_conta)
        cursor = self.cursor_papel("app", self.tenant)
        for cobranca, conta in (
            (self.cobranca, self.conta),
            (outra_cobranca, outra_conta),
        ):
            self.appendar(
                cursor, cobranca, conta, "pagamento_recebido",
                p_decisao="informativo", p_provider_event_id=entrega,
            )
        self.confirmar(cursor, self.tenant)


class TestOutboxNaMesmaTransaccao(ComLedger):
    """Criterio 8: uma falha forcada no *outbox* reverte a linha do ledger.

    ## A falha e forcada **na base**, com um *trigger* de ensaio

    A primeira versao deste ficheiro forcava-a com um `payload` que tinha um
    padrao de telefone, contando com a guarda de PII do `evt_emitir`. **Nao
    funcionou, e a razao e um achado:** o `payload` que vai para o *outbox* nao
    e o `p_payload` do evento — e um `jsonb_build_object` que a
    `append_payment_event` constroi com os campos da decisao. O ensaio passava a
    chamada, nada falhava, e o `assertErroSql` dizia «DatabaseError not raised».

    (O achado nao se perdeu: dele saiu a **guarda de PII da propria porta**, que
    e a caixa de privacidade do DoD — ver o `TestPrivacidadeDoPayload`.)

    O que se usa agora e um *trigger* `BEFORE INSERT` sobre o `events_outbox`
    que levanta, criado e apagado por este ensaio. E a leitura literal do
    criterio — «uma falha **forcada** no *outbox*» — e e mais honesto do que
    qualquer alternativa: nao depende de nenhuma guarda existente continuar a
    apanhar o que se lhe atira, e falha no sitio exacto onde o criterio quer que
    falhe. O *trigger* cai num `finally`, com asercao de que caiu.
    """

    TRIGGER = "outbox_de_ensaio_falha"

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)
        self.mapear_outbox()

    def test_com_mapeamento_o_outbox_recebe_na_mesma_transaccao(self) -> None:
        """A sonda positiva: o caminho que funciona, antes de o partir."""
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        linha = self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_confirmado"
        )
        self.assertIsNotNone(linha[4], "com mapeamento, ha evento de dominio")
        cursor.execute(
            "SELECT tipo, agregado_tipo, agregado_id FROM platform.events_outbox "
            " WHERE event_id = %s",
            (linha[4],),
        )
        self.assertEqual(
            tuple(str(campo) for campo in cursor.fetchone()),
            ("payment.confirmed", "payment_charge", self.cobranca),
        )
        self.confirmar(cursor, self.tenant)

    def test_sem_mapeamento_nao_ha_evento_de_dominio_e_o_ledger_grava(self) -> None:
        """O que deixa esta revisao fundir antes do KAM-055.

        Um `tipo_evento` sem linha no mapa nao produz evento de dominio **e nao
        falha**. Sem isto, a revisao exigia o mapeamento definitivo — que e do
        KAM-055 — para o ledger funcionar.
        """
        self.semente.execute("DELETE FROM platform.payment_outbox_map")
        cursor = self.cursor_papel("app", self.tenant)
        linha = self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        self.assertIsNone(linha[4])
        self.assertEqual(linha[1], 1, "e o ledger grava na mesma")
        self.confirmar(cursor, self.tenant)

    def test_uma_falha_no_outbox_reverte_a_linha_do_ledger(self) -> None:
        cursor = self.cursor_papel("app", self.tenant)
        self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        self.confirmar(cursor, self.tenant)
        antes = len(self.eventos_da_cobranca(self.cobranca))

        self.semente.execute(
            "CREATE FUNCTION platform." + self.TRIGGER + "() RETURNS trigger "
            "LANGUAGE plpgsql AS $ensaio$ BEGIN "
            "  RAISE EXCEPTION 'falha forcada no outbox (criterio 8)' "
            "    USING ERRCODE = 'check_violation'; "
            "END $ensaio$"
        )
        self.semente.execute(
            "CREATE TRIGGER " + self.TRIGGER + " BEFORE INSERT "
            "ON platform.events_outbox FOR EACH ROW "
            "EXECUTE FUNCTION platform." + self.TRIGGER + "()"
        )
        try:
            sql, args = self.sql_da_porta(
                p_charge_id=self.cobranca,
                p_tipo_evento="pagamento_confirmado",
                p_account_id=self.conta,
            )
            self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
            self.confirmar(cursor, self.tenant)
        finally:
            self.semente.execute(
                "DROP TRIGGER " + self.TRIGGER + " ON platform.events_outbox"
            )
            self.semente.execute("DROP FUNCTION platform." + self.TRIGGER + "()")
        self.semente.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            " WHERE c.relname = 'events_outbox' AND t.tgname = %s",
            (self.TRIGGER,),
        )
        self.assertEqual(
            int(self.semente.fetchone()[0]), 0, "o trigger de ensaio tem de cair"
        )

        self.assertEqual(
            len(self.eventos_da_cobranca(self.cobranca)),
            antes,
            "a linha do ledger tem de ter sido revertida com o outbox",
        )
        self.assertEqual(
            self.estado_da_cobranca(self.cobranca),
            "emitida",
            "e a projeccao do estado tambem",
        )


class TestPrivacidadeDoPayload(ComLedger):
    """A caixa de privacidade do DoD: «`payload` redigido sem PII».

    Nasceu de um achado — ver o cabecalho do `TestOutboxNaMesmaTransaccao`. O
    `payload` do evento **nao** passa pela guarda de PII do `evt_emitir`, porque
    o que vai para o *outbox* e uma projeccao construida pela funcao. Logo, sem
    uma guarda propria, a caixa marcava-se por convencao de quem escreve o
    codigo — e num ledger *append-only* isso e pior do que em qualquer outra
    tabela: um telefone que entre nao sai, nem com `UPDATE`, porque o
    `deny_mutation` recusa.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)
        self.cobranca = self.criar_cobranca(self.tenant, self.conta)

    def test_um_telefone_no_payload_e_recusado(self) -> None:
        cursor = self.cursor_papel("app", self.tenant)
        for payload in (
            {"telefone": "+244912345678"},
            {"msisdn": "244912345678"},
            {"contacto": "+351912345678"},
        ):
            with self.subTest(payload=payload):
                sql, args = self.sql_da_porta(
                    p_charge_id=self.cobranca,
                    p_tipo_evento="pagamento_recebido",
                    p_account_id=self.conta,
                    p_decisao="informativo",
                    p_payload=json.dumps(payload),
                )
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)
        self.assertEqual(self.eventos_da_cobranca(self.cobranca), [])

    def test_um_telefone_no_motivo_e_recusado(self) -> None:
        """O `motivo` viaja para o *outbox*, e por isso entra na guarda."""
        cursor = self.cursor_papel("app", self.tenant)
        sql, args = self.sql_da_porta(
            p_charge_id=self.cobranca,
            p_tipo_evento="pagamento_divergente",
            p_account_id=self.conta,
            p_decisao="rejeitada",
            p_motivo="o cliente +244912345678 pagou a menos",
        )
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, args)

    def test_um_payload_redigido_passa(self) -> None:
        """A sonda positiva. **Sem ela, a guarda podia recusar tudo.**

        Um padrao escrito ao contrario — que apanhasse qualquer digito — deixava
        os casos acima verdes sobre um ledger onde nao entra payload nenhum.
        """
        cursor = self.cursor_papel("app", self.tenant)
        linha = self.appendar(
            cursor, self.cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
            p_payload=json.dumps(
                {"contact_id": "9c3d1a7e-0000-4000-8000-000000000001", "fee": 1500}
            ),
        )
        self.assertEqual(linha[1], 1)
        self.confirmar(cursor, self.tenant)

    def test_a_guarda_e_a_mesma_do_evt_emitir(self) -> None:
        """Os padroes sao **os mesmos** da `0004`, e isso le-se das duas funcoes.

        Nao e cosmetica: um ledger mais permissivo do que o *outbox* deixava
        passar o que o evento de dominio recusa, e a diferenca so aparecia no dia
        em que o KAM-055 enchesse o mapa — com a linha ja escrita e imutavel.
        """
        self.semente.execute(
            "SELECT p.proname::text, pg_get_functiondef(p.oid) FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' "
            "   AND p.proname IN ('evt_emitir', 'append_payment_event')"
        )
        corpos = {str(nome): str(corpo) for nome, corpo in self.semente.fetchall()}
        self.assertEqual(len(corpos), 2)
        for padrao in (PADRAO_244, PADRAO_INTERNACIONAL):
            for nome, corpo in corpos.items():
                with self.subTest(funcao=nome, padrao=padrao):
                    self.assertIn(padrao, corpo)
