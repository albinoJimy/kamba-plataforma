"""A revisão `0035`: as três FK, o mapa do *outbox* e o `payload` do contrato.

O que esta suite prova é o critério 8 do KAM-055 (migração reversível) e as duas
metades do critério 2 que são da base de dados (o mapeamento, e a barreira do
`authn_ok`). O critério 1 entra aqui pela porta de trás, e é a parte que vale
mais: **o oráculo do `payload` é o ficheiro de contrato publicado**, lido do
disco, e não uma constante escrita ao lado do código que ela julga. Trocar um
campo na `payment_evt_payload` e no ensaio ao mesmo tempo não dá verde — o
esquema recusa.

## Por objecto, e não pela cadeia

O ciclo `upgrade → downgrade → upgrade` já corre no *gate* 8 sobre uma base
vazia, e o que ele prova é que a **cadeia** encaixa: um `downgrade` que largasse
duas das três FK e se esquecesse da terceira, ou que deixasse a função no
catálogo, passava-o inteiro. Por isso cada objecto é afirmado **pelo nome** —
as três restrições, a função e as sete linhas do mapa.

**E primeiro em `head`, a exigir presença.** Uma consulta de catálogo errada
devolve zero linhas dos dois lados, pelo que um ensaio que só verificasse a
ausência depois do `downgrade` ficava verde sem ter medido nada. O
`test_em_head_esta_tudo` é a pré-condição de todos os outros, e cada asserção de
ausência leva o seu controlo positivo na mesma consulta — uma FK que **tem** de
ficar (`payment_charges_tenant_fk`), para separar «esta FK saiu» de «a consulta
não vê FK nenhuma».

## E pergunta-se ao `pg_constraint`, não ao `pg_indexes`

Uma `FOREIGN KEY` aparece **só** no `pg_constraint`. O `pg_indexes` mostra o
índice que uma `PRIMARY KEY` ou uma `UNIQUE` cria, e não mostra FK nenhuma: uma
afirmação de ausência feita contra ele dava verde com as três FK presentes. É a
mesma nota do `db/tests/test_downgrade_0034.py` e do
`db/tests_encomendas/test_downgrade_0033.py`.

## O `downgrade` da porta não se mede por a função existir

A `append_payment_event` existe antes e depois: o `downgrade` **substitui-a**,
não a apaga. Um ensaio que perguntasse ao catálogo se ela existe ficava verde
com o `downgrade` a não fazer nada. O que se mede é o **corpo**, pelo
`pg_get_functiondef`: depois do `downgrade` ele volta a dizer `'payment_charge'`
e deixa de citar a `payment_evt_payload`.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import bootstrap
import ligacao
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests_pagamentos.base import VALOR, ComLedger

#: A raiz do repositório. O corredor das suites corre com `cwd` em `db/`, pelo
#: que um caminho relativo apontava para dentro dela.
RAIZ = Path(__file__).resolve().parents[2]

CONTRATOS = RAIZ / "contratos" / "eventos"

#: A revisão anterior. O `downgrade` desta volta aqui, e anda a par da
#: `down_revision` do ficheiro da revisão.
ANTERIOR = "0034"

#: As três FK, com a tabela de cada uma.
FKS = (
    ("payment_charges", "payment_charges_encomenda_do_mesmo_tenant_fk"),
    ("payment_events", "payment_events_encomenda_do_mesmo_tenant_fk"),
    ("refund_cases", "refund_cases_encomenda_do_mesmo_tenant_fk"),
)

#: Uma FK que a `0035` **não** cria e que tem de ficar depois do `downgrade`.
#: É o controlo positivo das asserções de ausência.
FK_QUE_FICA = "payment_charges_tenant_fk"

FUNCAO = "payment_evt_payload"

#: A tabela e as colunas que as três FK apontam. **O alvo entra na forma
#: medida**, e a razão é um falso verde que esta suite tinha: uma FK de duas
#: colunas, `NO ACTION`, não diferida e `MATCH SIMPLE` para a tabela errada ou
#: para as colunas erradas dá exactamente a mesma forma que a certa.
ALVO = "platform.orders_mirror"
COLUNAS = ["tenant_id", "order_id"]
COLUNAS_DO_ALVO = ["tenant_id", "id"]

#: A frase que o `COMMENT` da porta leva **a mais** em `head`, e que uma base em
#: `0034` não pode ter: lá, o corpo agrega pela cobrança.
CODA_DO_0035 = (
    "O passo (7) agrega por encomenda e usa o payload do contrato desde o "
    "KAM-055."
)

#: Em que o comentário da `0029` acaba. É o controlo positivo da ausência
#: acima: sem ele, um `obj_description` que devolvesse `NULL` (ou uma consulta
#: a olhar para a função errada) lia-se como «o `downgrade` repôs o texto».
FIM_DO_COMENTARIO_DA_0029 = "que prende tambem o dono (FORCE)."

#: O mapa que a revisão declara, repetido aqui **de propósito**.
#:
#: É a segunda superfície, e o `test_o_mapa_e_exactamente_o_declarado` cruza-a
#: com a base. Duas listas do mesmo conteúdo divergem no dia em que uma delas
#: mudar — e é isso que se quer medir: quem mexer no mapeamento da revisão sem
#: mexer aqui descobre-o por um vermelho, e não por um evento que um consumidor
#: deixou de receber em produção.
MAPEAMENTO = (
    ("cobranca_expirada", "sistema", "payment.expired", 1),
    ("pagamento_confirmado", "consulta", "payment.confirmed", 1),
    ("pagamento_confirmado", "hmac", "payment.confirmed", 1),
    ("pagamento_confirmado", "manual", "payment.manual_confirmed", 1),
    ("pagamento_divergente", "consulta", "payment.failed", 1),
    ("pagamento_divergente", "hmac", "payment.failed", 1),
    ("referencia_emitida", "sistema", "payment.reference_issued", 1),
)


def esquema(tipo: str, versao: int = 1) -> dict:
    """O contrato publicado, lido do disco.

    O oráculo deste ficheiro. Não se copia para uma constante: uma cópia
    envelhece em silêncio, e o que interessa medir é o que os consumidores
    recebem contra o que lhes foi prometido.
    """
    caminho = CONTRATOS / tipo / f"v{versao}.schema.json"
    return json.loads(caminho.read_text(encoding="utf-8"))


def verificador():
    """O `FormatChecker`, e o que ele **não** mede nesta máquina.

    Sem ele, o `jsonschema.validate` ignora `format` por inteiro — e os cinco
    contratos declaram `format: uuid` no `order_id` e `format: date-time` no
    `expira_at`. Ligá-lo fecha o `uuid`.

    **O `date-time` fica por medir, e diz-se:** o verificador dele só existe
    com o `rfc3339-validator` instalado, e neste `.venv` não está — medido
    (`sorted(jsonschema.FormatChecker().checkers)` traz `uuid` e não traz
    `date-time`). Na prática o PostgreSQL serializa `timestamptz` em `jsonb`
    como ISO-8601, pelo que o campo sai bem; o que não se pode dizer é que
    **este** ensaio o prende.
    """
    import jsonschema

    return jsonschema.FormatChecker()


class TestFksEMapaDa0035(unittest.TestCase):
    """O catálogo e o `downgrade`. Como administrador, e a controlar a revisão."""

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        bootstrap.aplicar()
        if not em_head():
            alembic_ok("upgrade", "head")

    def setUp(self) -> None:
        self.conexao = ligacao.ligar("admin")
        self.conexao.autocommit = True
        self.cursor = self.conexao.cursor()

    def tearDown(self) -> None:
        try:
            if not em_head():
                alembic_ok("upgrade", "head")
        finally:
            self.conexao.close()

    # -------------------------------------------------------------- auxiliares

    def chaves_estrangeiras(self, tabela: str) -> list[str]:
        """As FK **daquela** tabela, pelo `pg_constraint`.

        A tabela vai por parâmetro e não fixa, para que a mesma consulta possa
        correr contra um alvo que se sabe ter FK — é o controlo positivo, e sem
        ele uma consulta mal escrita lia-se como «o `downgrade` funcionou».
        """
        self.cursor.execute(
            "SELECT c.conname::text FROM pg_constraint c "
            "  JOIN pg_class t ON t.oid = c.conrelid "
            "  JOIN pg_namespace n ON n.oid = t.relnamespace "
            " WHERE n.nspname = 'platform' AND t.relname = %s "
            "   AND c.contype = 'f' ORDER BY 1",
            (tabela,),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def funcoes(self) -> list[str]:
        self.cursor.execute(
            "SELECT p.proname::text FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = ANY(%s) ORDER BY 1",
            ([FUNCAO, "append_payment_event"],),
        )
        return [str(linha[0]) for linha in self.cursor.fetchall()]

    def mapa(self) -> list[tuple]:
        self.cursor.execute(
            "SELECT tipo_evento, authn_method, evt_tipo, evt_versao "
            "  FROM platform.payment_outbox_map ORDER BY 1, 2"
        )
        return [
            (str(a), str(b), str(c), int(d)) for a, b, c, d in self.cursor.fetchall()
        ]

    def corpo_da_porta(self) -> str:
        self.cursor.execute(
            "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = 'append_payment_event'"
        )
        return str(self.cursor.fetchone()[0])

    def comentario_da_porta(self) -> str:
        """A descrição que o catálogo guarda da porta.

        **Não vem no `pg_get_functiondef`**, e é por isso que precisa de
        consulta própria: o `test_o_downgrade_repoe_o_passo_sete_da_0029` mede o
        corpo e dava verde com o comentário a descrever a versão errada.
        """
        self.cursor.execute(
            "SELECT obj_description(p.oid, 'pg_proc') FROM pg_proc p "
            "  JOIN pg_namespace n ON n.oid = p.pronamespace "
            " WHERE n.nspname = 'platform' AND p.proname = 'append_payment_event'"
        )
        linha = self.cursor.fetchone()
        self.assertIsNotNone(linha, "a porta nao existe")
        self.assertIsNotNone(linha[0], "a porta nao tem COMMENT nenhum")
        return str(linha[0])

    def forma_da_fk(self, nome: str) -> tuple:
        """`(colunas, apaga, actualiza, diferida, match, alvo, de, para)`.

        **O alvo e as colunas dos dois lados entram, e não por completude.** A
        primeira versão devolvia só os cinco primeiros campos, e com eles
        trocar `REFERENCES platform.orders_mirror (tenant_id, id)` por
        `REFERENCES platform.payment_accounts (tenant_id, id)` — ou tirar o
        `tenant_id` ao par — deixava esta asserção verde: a forma é a mesma.
        Quem diz para onde a FK aponta é o `confrelid`, e quais as colunas são
        o `conkey` e o `confkey`.
        """
        self.cursor.execute(
            "SELECT array_length(c.conkey, 1), c.confdeltype, c.confupdtype, "
            "       c.condeferrable, c.confmatchtype, "
            "       (SELECT n2.nspname || '.' || cl.relname FROM pg_class cl "
            "          JOIN pg_namespace n2 ON n2.oid = cl.relnamespace "
            "         WHERE cl.oid = c.confrelid), "
            "       (SELECT array_agg(a.attname::text ORDER BY k.ord) "
            "          FROM unnest(c.conkey) WITH ORDINALITY AS k(att, ord) "
            "          JOIN pg_attribute a ON a.attrelid = c.conrelid "
            "           AND a.attnum = k.att), "
            "       (SELECT array_agg(a.attname::text ORDER BY k.ord) "
            "          FROM unnest(c.confkey) WITH ORDINALITY AS k(att, ord) "
            "          JOIN pg_attribute a ON a.attrelid = c.confrelid "
            "           AND a.attnum = k.att) "
            "  FROM pg_constraint c "
            "  JOIN pg_namespace n ON n.oid = c.connamespace "
            " WHERE n.nspname = 'platform' AND c.conname = %s",
            (nome,),
        )
        linha = self.cursor.fetchone()
        self.assertIsNotNone(linha, f"a FK {nome} nao existe")
        return (
            int(linha[0]),
            str(linha[1]),
            str(linha[2]),
            bool(linha[3]),
            str(linha[4]),
            str(linha[5]),
            [str(c) for c in linha[6]],
            [str(c) for c in linha[7]],
        )

    # ------------------------------------------------------------- a presença

    def test_em_head_esta_tudo(self) -> None:
        """O ponto de partida. **Sem isto, os casos seguintes nao dizem nada.**"""
        for tabela, restricao in FKS:
            with self.subTest(fk=restricao):
                self.assertIn(restricao, self.chaves_estrangeiras(tabela))
        self.assertEqual(self.funcoes(), ["append_payment_event", FUNCAO])
        self.assertEqual(self.mapa(), list(MAPEAMENTO))
        self.assertIn(
            "platform.payment_evt_payload(",
            self.corpo_da_porta(),
            "em head a porta chama a funcao do payload",
        )
        self.assertIn(
            CODA_DO_0035,
            self.comentario_da_porta(),
            "em head o catalogo descreve a porta que esta la",
        )

    def test_o_mapa_e_exactamente_o_declarado(self) -> None:
        """As duas superfícies que dizem o mesmo, cruzadas.

        `assertEqual` do conjunto inteiro e não `assertIn` linha a linha: uma
        linha **a mais** no mapa é tão grave como uma a menos — publica um
        evento de domínio que ninguém decidiu publicar, a um consumidor que o
        vai consumir.
        """
        self.assertEqual(self.mapa(), list(MAPEAMENTO))

    def test_as_fk_sao_compostas_sem_cascata_e_nao_diferidas(self) -> None:
        """A forma das três, e cada campo fecha uma lista fechada da casa.

        * **duas colunas** — `(tenant_id, order_id)`. Com uma só, a cobrança de
          A podia apontar para a encomenda de B, que é o ISO-58 do spike
          KAM-041;
        * **`a` nos dois sentidos** (`NO ACTION`) — o
          `test_as_fk_nao_apagam_em_cascata` de `db/tests/test_inventario.py`
          exige-o de **todas**, e aqui vale a dobrar: uma cascata da encomenda
          para o ledger apagava prova *append-only* por uma porta que o
          `deny_mutation` não guarda;
        * **não diferida** — o `test_a_fk_do_dono_e_a_unica_diferida` afirma que
          a `tenants_owner_fk` é a única do esquema;
        * **`s` de `MATCH SIMPLE`** — é o que deixa a cobrança de ciclo de
          billing (`order_id` nulo) passar. Com `f` (`MATCH FULL`) o §11.2
          ficava sem caminho de escrita, e isso não aparecia como erro de
          migração: aparecia, meses depois, como uma facturação que não grava;
        * **o alvo e as colunas dos dois lados** — ver o `forma_da_fk`. Sem
          eles, os quatro campos acima são os mesmos para uma FK que aponte
          para a tabela errada, e a asserção media a forma em vez da ligação.
        """
        for _tabela, restricao in FKS:
            with self.subTest(fk=restricao):
                self.assertEqual(
                    self.forma_da_fk(restricao),
                    (2, "a", "a", False, "s", ALVO, COLUNAS, COLUNAS_DO_ALVO),
                )

    # -------------------------------------------------------------- a ausência

    def test_o_downgrade_leva_as_tres_fk_a_funcao_e_as_sete_linhas(self) -> None:
        alembic_ok("downgrade", ANTERIOR)
        for tabela, restricao in FKS:
            with self.subTest(fk=restricao):
                presentes = self.chaves_estrangeiras(tabela)
                self.assertNotIn(restricao, presentes)
                # O controlo positivo, **na mesma consulta**: a
                # `payment_charges` tem de continuar a ter FK, senão o
                # `assertNotIn` acima estava a medir uma consulta cega.
                if tabela == "payment_charges":
                    self.assertIn(FK_QUE_FICA, presentes)
                else:
                    self.assertNotEqual(presentes, [], "controlo: a tabela tem FK")
        self.assertEqual(self.funcoes(), ["append_payment_event"])
        self.assertEqual(self.mapa(), [], "o mapa volta a ficar vazio, como a 0029")

    def test_o_downgrade_repoe_o_passo_sete_da_0029(self) -> None:
        """O que mede que o `downgrade` da porta é real.

        A função existe antes e depois — o `downgrade` substitui-a. Perguntar ao
        catálogo se ela existe dava verde com o `downgrade` a não fazer nada;
        quem responde é o corpo.
        """
        alembic_ok("downgrade", ANTERIOR)
        corpo = self.corpo_da_porta()
        self.assertIn("'payment_charge'", corpo, "volta a agregar pela cobranca")
        self.assertNotIn("platform.payment_evt_payload(", corpo)
        self.assertNotIn("v_charge.tenant_id, 'order'", corpo)

    def test_o_downgrade_repoe_o_comentario_da_0029(self) -> None:
        """O objecto que faltava à medição do `downgrade` por objecto.

        O `_porta` emitia o `COMMENT` **sempre igual**, com a frase do KAM-055
        no fim — também quando era o `downgrade` a chamá-lo. Depois de
        `alembic downgrade 0034`, o corpo voltava a agregar pela cobrança e o
        catálogo continuava a afirmar o contrário a quem o lesse.

        **Nada ficava vermelho**, e é essa a parte que interessa: o
        `pg_get_functiondef` não traz o `COMMENT`, e o ciclo `upgrade ->
        downgrade -> upgrade` passa inteiro porque o `upgrade` seguinte
        reescreve a frase certa.

        **A presença primeiro, e depois a ausência**, como todas as asserções de
        `downgrade` desta suite: sem a primeira linha, um `obj_description` nulo
        passava o `assertNotIn`.
        """
        self.assertIn(CODA_DO_0035, self.comentario_da_porta())
        alembic_ok("downgrade", ANTERIOR)
        comentario = self.comentario_da_porta()
        self.assertNotIn(CODA_DO_0035, comentario)
        self.assertTrue(
            comentario.endswith(FIM_DO_COMENTARIO_DA_0029),
            f"o comentario da 0029 nao voltou inteiro: ...{comentario[-90:]}",
        )

    def test_o_upgrade_seguinte_repoe_tudo(self) -> None:
        alembic_ok("downgrade", ANTERIOR)
        self.assertEqual(self.mapa(), [], "pre-condicao: o mapa saiu")
        alembic_ok("upgrade", "head")
        for tabela, restricao in FKS:
            with self.subTest(fk=restricao):
                self.assertIn(restricao, self.chaves_estrangeiras(tabela))
        self.assertEqual(self.funcoes(), ["append_payment_event", FUNCAO])
        self.assertEqual(self.mapa(), list(MAPEAMENTO))
        self.assertIn("platform.payment_evt_payload(", self.corpo_da_porta())


class TestBarreirasDa0035(ComLedger):
    """As recusas, a correr como `kamba_app`. Cada restrição com o seu caso.

    Uma restrição afirmada só pelo nome está medida como nome e não como
    barreira: a lição da revisão `0034`, onde oito `CHECK` estavam nomeados em
    duas superfícies e **nenhuma** tinha caso negativo — tirar as âncoras a um
    deles deixava as duas verdes enquanto a coluna passava a aceitar um segredo.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.conta = self.criar_conta(self.tenant)

    def test_uma_cobranca_para_encomenda_inexistente_e_recusada(self) -> None:
        """O caso que a FK recusa, e o que a semente desta suite fazia antes."""
        cursor = self.cursor_papel("app", self.tenant)
        self.assertErroSql(
            VIOLACAO_DE_FK,
            cursor,
            "INSERT INTO platform.payment_charges "
            "(tenant_id, order_id, account_id, provider, metodo, referencia, "
            " amount_minor, valid_until) "
            "VALUES (%s, gen_random_uuid(), %s, 'fakeprovider', 'referencia', "
            "        'REF-inexistente', %s, now() + interval '1 day')",
            (self.tenant, self.conta, VALOR),
        )
        self.confirmar(cursor, self.tenant)

    def test_uma_cobranca_para_encomenda_de_outro_tenant_e_recusada(self) -> None:
        """A razão de a FK ser **composta**, e o único caso que a mede.

        Uma FK só sobre `order_id` aceitava esta linha: a encomenda existe. O
        que não existe é o par `(tenant desta cobrança, aquela encomenda)` — e
        é esse o par que a restrição pede.

        **Dois tenants e não um**, pela razão do `assert_beneficiary`: provar
        que uma encomenda inexistente é recusada não prova que a encomenda de
        outro tenant também o seja.
        """
        outro = self.criar_tenant()
        encomenda_do_outro = self.criar_encomenda(outro)
        cursor = self.cursor_papel("app", self.tenant)
        self.assertErroSql(
            VIOLACAO_DE_FK,
            cursor,
            "INSERT INTO platform.payment_charges "
            "(tenant_id, order_id, account_id, provider, metodo, referencia, "
            " amount_minor, valid_until) "
            "VALUES (%s, %s, %s, 'fakeprovider', 'referencia', 'REF-alheia', "
            "        %s, now() + interval '1 day')",
            (self.tenant, encomenda_do_outro, self.conta, VALOR),
        )
        self.confirmar(cursor, self.tenant)

    def test_um_sujeito_de_billing_sem_encomenda_continua_a_passar(self) -> None:
        """O lado positivo do `MATCH SIMPLE`, e sem ele o §11.2 não grava.

        O caminho que uma `MATCH FULL` teria fechado: `order_id` **nulo** e
        `billing_cycle_id` preenchido, que é o que a facturação da própria
        KAMBÁ do §11.2 escreve e que o `um_sujeito` pede. Com `MATCH FULL` a
        restrição avaliava o par `(tenant_id, NULL)` e recusava-o; com `MATCH
        SIMPLE` um nulo no par satisfaz, e é essa a propriedade medida.

        **Mede-se no `payment_events` e não na `payment_charges`, e a razão é
        outra barreira:** o `assert_beneficiary` da `0027` corre `BEFORE INSERT`
        na cobrança e recusa uma cobrança de billing numa conta `pme` **antes**
        de a FK ser avaliada — isto é, aqui ele mediria a guarda G-1 e não o
        `MATCH SIMPLE`. A `payment_events` tem a mesma coluna anulável, o mesmo
        `CHECK` de exclusividade e a **mesma** FK desta revisão, e não tem o
        *trigger* do beneficiário: é o sítio onde esta pergunta tem uma resposta
        só.

        Pelo superutilizador, que é o único com `INSERT` nesta tabela — a mesma
        via do `TestOsCheckMordemSozinhos`, e pela mesma razão.
        """
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        cobranca = self.criar_cobranca(self.tenant, self.conta)
        cursor.execute(
            "INSERT INTO platform.payment_events "
            "(tenant_id, charge_id, order_id, billing_cycle_id, provider, "
            " account_id, referencia, tipo_evento, sequencia, valor_minor, "
            " authn_method, authn_ok, decisao, actor_kind, payload_hash, "
            " prev_hash, row_hash) "
            "VALUES (%s, %s, NULL, %s, 'fakeprovider', %s, 'REF-billing', "
            "        'cobranca_criada', 77, %s, 'sistema', true, 'informativo', "
            f"        'sistema', sha256('{{}}'::bytea), '\\x{'00' * 32}'::bytea, "
            "        sha256('billing'::bytea))",
            (
                self.tenant,
                cobranca,
                "11111111-2222-4333-8444-555555555555",
                self.conta,
                VALOR,
            ),
        )
        cursor.execute(
            "SELECT order_id, billing_cycle_id FROM platform.payment_events "
            " WHERE sequencia = 77 AND charge_id = %s",
            (cobranca,),
        )
        order_id, ciclo = cursor.fetchone()
        self.assertIsNone(order_id, "o nulo passou a FK composta")
        self.assertIsNotNone(ciclo)
        # **Sem `COMMIT`**: o `payment_events` é *append-only* e a limpeza não o
        # apaga, pelo que confirmar esta linha deixava-a na base para sempre —
        # e com ela a cobrança e o tenant. O `rollback` é o que a tira.
        conexao.rollback()

    def test_um_evento_para_encomenda_de_outro_tenant_e_recusado(self) -> None:
        """A FK que o critério 8 nomeia, medida pelo que ela **recusa**.

        A primeira versão desta suite media esta FK só pelo nome e pela forma,
        mais o caso **positivo** do `MATCH SIMPLE` logo abaixo. Com isso, tirar
        o `tenant_id` ao par (ou apontá-lo à tabela errada) deixava tudo verde
        — e é esta a FK que o próprio módulo diz que «custa», porque torna a
        encomenda com ledger impossível de apagar.

        **Pelo superutilizador**, que é o único com `INSERT` nesta tabela, e
        pela mesma via do caso positivo. A linha é recusada pela FK e não pelo
        `um_sujeito`: o `order_id` vai preenchido e o `billing_cycle_id` nulo,
        que é exactamente o par que aquele `CHECK` aceita.
        """
        outro = self.criar_tenant()
        encomenda_do_outro = self.criar_encomenda(outro)
        cobranca = self.criar_cobranca(self.tenant, self.conta)
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        self.assertErroSql(
            VIOLACAO_DE_FK,
            cursor,
            "INSERT INTO platform.payment_events "
            "(tenant_id, charge_id, order_id, billing_cycle_id, provider, "
            " account_id, referencia, tipo_evento, sequencia, valor_minor, "
            " authn_method, authn_ok, decisao, actor_kind, payload_hash, "
            " prev_hash, row_hash) "
            "VALUES (%s, %s, %s, NULL, 'fakeprovider', %s, 'REF-alheia', "
            "        'cobranca_criada', 78, %s, 'sistema', true, 'informativo', "
            f"        'sistema', sha256('{{}}'::bytea), '\\x{'00' * 32}'::bytea, "
            "        sha256('alheia'::bytea))",
            (
                self.tenant,
                cobranca,
                encomenda_do_outro,
                self.conta,
                VALOR,
            ),
        )
        conexao.rollback()

    def test_um_caso_de_reembolso_para_encomenda_de_outro_tenant_e_recusado(
        self,
    ) -> None:
        """A terceira FK, que não está no critério 8 e não tinha caso nenhum.

        É a que paga a dívida que o repositório nomeia em quatro sítios, e a
        razão escrita é a coerência do par: pôr a FK de `order_id` só num dos
        lados deixava o reembolso de A a apontar para a encomenda de B. Isso é
        uma afirmação sobre o que a restrição **recusa**, e por isso mede-se
        aqui e não no catálogo.

        **Pelo superutilizador**, porque nenhum papel de aplicação tem `INSERT`
        nesta tabela — quem a escreve é a `manual_reverter`, que é
        `SECURITY DEFINER`. O `charge_id` fica nulo, que é o par que o
        `refund_cases_um_sujeito` aceita com o `order_id` preenchido.
        """
        outro = self.criar_tenant()
        encomenda_do_outro = self.criar_encomenda(outro)
        conexao = self.ligar("admin")
        cursor = conexao.cursor()
        self.assertErroSql(
            VIOLACAO_DE_FK,
            cursor,
            "INSERT INTO platform.refund_cases "
            "(tenant_id, order_id, motivo, valor_minor, estado) "
            "VALUES (%s, %s, 'encomenda alheia', %s, 'aberto')",
            (self.tenant, encomenda_do_outro, VALOR),
        )
        conexao.rollback()

    # ----------------------------------------------- as recusas do `payload`
    #
    # **Como administrador, e não como `kamba_app`.** A regra da casa é medir uma
    # barreira com o papel que a encontra em produção, e o papel que encontra
    # esta é o **dono** da `append_payment_event`: ela é `SECURITY DEFINER`, pelo
    # que a chamada à `payment_evt_payload` corre com os privilégios dele.
    #
    # O `kamba_app` **não** a alcança, e isso é a barreira de privilégio desta
    # revisão — medida no `test_o_kamba_app_nao_chama_a_funcao_do_payload`. A
    # primeira versão destes ensaios corria-os como `kamba_app` e mediu `42501`
    # quatro vezes a pensar que media `23514`: o erro certo pela razão errada.

    def test_o_kamba_app_nao_chama_a_funcao_do_payload(self) -> None:
        """A barreira de privilégio: só o `REVOKE` e nenhum `GRANT`.

        A `payment_evt_payload` não é uma porta: é um auxiliar da porta. Dar-lhe
        `EXECUTE` ao `kamba_app` alargava a superfície dele por nada — ele já
        não precisa dela, porque a `append_payment_event` corre como o dono. Que
        o `REVOKE` morde mede-se, e é isto.
        """
        cursor = self.cursor_papel("app", self.tenant)
        sql, parametros = self._sql_do_payload("payment.confirmed")
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, sql, parametros)
        self.confirmar(cursor, self.tenant)

    def _sql_do_payload(self, evt_tipo: str, **campos) -> tuple[str, tuple]:
        """A chamada com **os onze** argumentos, sempre.

        A `payment_evt_payload` não tem valores por omissão, de propósito: um
        campo esquecido tem de ser um erro de assinatura e não um `null` dentro
        de um `payload` que o esquema depois recusa. O preço é que a notação por
        nome exige os onze — e sem eles o PostgreSQL responde `42883` («a função
        não existe»), que é o que a primeira versão deste ficheiro mediu a
        pensar que media uma recusa de domínio.
        """
        argumentos = {
            "p_evt_tipo": evt_tipo,
            "p_order_id": "11111111-2222-4333-8444-666666666666",
            "p_provider": "fakeprovider",
            "p_referencia": "REF123456789",
            "p_valor_minor": VALOR,
            "p_currency": "AOA",
            "p_authn_method": "hmac",
            "p_authn_ok": True,
            "p_provider_event_id": None,
            "p_motivo": None,
            "p_expira_at": "2099-01-01T00:00:00+00:00",
        }
        argumentos.update(campos)
        nomes = ", ".join(f"{nome} => %s" for nome in argumentos)
        return (
            f"SELECT platform.payment_evt_payload({nomes})",
            tuple(argumentos.values()),
        )

    def _payload(self, cursor, evt_tipo: str, **campos):
        cursor.execute(*self._sql_do_payload(evt_tipo, **campos))
        bruto = cursor.fetchone()[0]
        return json.loads(bruto) if isinstance(bruto, str) else bruto

    def test_o_payload_recusa_um_confirmado_sem_autenticacao(self) -> None:
        """A barreira do critério 2, e o caso que a mede.

        «Nunca existe um emitido sem o `authn_ok=true` correspondente no
        ledger» — escrito como recusa e não como convenção de quem enche o
        mapa.
        """
        cursor = self.cursor_papel("admin", self.tenant)
        for evt_tipo in ("payment.confirmed", "payment.manual_confirmed"):
            with self.subTest(evento=evt_tipo):
                sql, parametros = self._sql_do_payload(evt_tipo, p_authn_ok=False)
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, parametros)
        self.confirmar(cursor, self.tenant)

    def test_o_payload_recusa_uma_encomenda_nula(self) -> None:
        """A função é **total**: cada caminho devolve payload válido ou levanta.

        O passo (7) da porta já não a chama para uma cobrança de billing
        (`order_id` nulo), pelo que este caminho é inalcançável **de lá** — e é
        por isso que se mede aqui, pela chamada directa, em vez de se supor.
        Sem a recusa, um chamador de outro sítio obtinha
        `"order_id": null`, que o `format: uuid` dos cinco contratos recusa.
        """
        cursor = self.cursor_papel("admin", self.tenant)
        for evt_tipo in (
            "payment.confirmed",
            "payment.manual_confirmed",
            "payment.reference_issued",
            "payment.failed",
            "payment.expired",
        ):
            with self.subTest(evento=evt_tipo):
                sql, parametros = self._sql_do_payload(
                    evt_tipo, p_order_id=None, p_motivo="valor_divergente"
                )
                self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, parametros)
        self.confirmar(cursor, self.tenant)

    def test_o_payload_recusa_um_failed_sem_motivo(self) -> None:
        """O contrato exige o `motivo`, e um texto de enchimento era pior."""
        cursor = self.cursor_papel("admin", self.tenant)
        sql, parametros = self._sql_do_payload("payment.failed", p_motivo=None)
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, parametros)
        self.confirmar(cursor, self.tenant)

    def test_o_payload_recusa_um_evento_que_nao_conhece(self) -> None:
        """Um mapa que aponte para um evento sem `payload` conhecido recusa.

        É o caminho por onde uma linha nova no mapa — sem ninguém acrescentar o
        ramo aqui — publicaria um envelope que o esquema do evento rejeita. A
        recusa é o que o torna um erro de migração em vez de um evento inválido
        em produção.
        """
        cursor = self.cursor_papel("admin", self.tenant)
        sql, parametros = self._sql_do_payload("order.manual_confirmation_requested")
        self.assertErroSql(VIOLACAO_DE_CHECK, cursor, sql, parametros)
        self.confirmar(cursor, self.tenant)

    # ------------------------------------------- o contrato como oráculo

    def test_o_payload_de_cada_contrato_valida_contra_o_esquema_publicado(self) -> None:
        """Os cinco `payload`, validados contra os ficheiros de `contratos/`.

        O oráculo é externo: o esquema vem do disco, e foi escrito pelo KAM-007
        muito antes desta revisão. Um campo a mais, um a menos, ou um tipo
        errado na `payment_evt_payload` dá vermelho aqui mesmo que o ensaio e a
        função mudem juntos — que é o que uma constante escrita ao lado não
        consegue garantir.

        Valida-se contra o **subesquema do `payload`** e não contra o envelope
        inteiro porque é a `payment_evt_payload` que está em medição; o envelope
        completo é medido pelo `test_o_envelope_da_porta_valida_contra_o_esquema`
        abaixo, que o lê do `events_outbox`.
        """
        import jsonschema

        cursor = self.cursor_papel("admin", self.tenant)
        casos = {
            "payment.confirmed": {},
            "payment.manual_confirmed": {"p_authn_method": "manual"},
            "payment.reference_issued": {},
            # `valor_divergente` e não `valor`: é um dos nove
            # `MOTIVOS_DE_FALHA` da `0029`, que é o domínio que o
            # `payment_charges_motivo_falha_ck` fecha. O §5 escreve a forma
            # curta e a base recusa-a — medido com `23514`.
            "payment.failed": {"p_motivo": "valor_divergente"},
            "payment.expired": {},
        }
        for tipo, extra in casos.items():
            with self.subTest(evento=tipo):
                payload = self._payload(cursor, tipo, **extra)
                jsonschema.validate(
                    payload,
                    esquema(tipo)["properties"]["payload"],
                    format_checker=verificador(),
                )
        self.confirmar(cursor, self.tenant)

    def test_o_envelope_da_porta_valida_contra_o_esquema(self) -> None:
        """O envelope inteiro, como o consumidor o recebe.

        É a prova de que o critério 1 e o critério 2 são verdadeiros **ao mesmo
        tempo**: o que a porta escreve no `events_outbox` é o que o contrato
        publicado promete, campo de topo incluído — o `agregado.tipo` com
        `const: "order"` é a metade que a `0029` não cumpria.

        Dois eventos e não um: o `payment.confirmed` pelo caminho `hmac` e o
        `payment.reference_issued` pelo `sistema`, que são os dois que a porta
        alcança com uma cobrança semeada. São também os dois extremos do mapa —
        um `authn_method` que autentica e um que não.
        """
        import jsonschema

        encomenda = self.criar_encomenda(self.tenant)
        cursor = self.cursor_papel("app", self.tenant)
        cobranca = self.criar_cobranca(
            self.tenant, self.conta, order_id=encomenda, estado="iniciada"
        )
        # `referencia_emitida` leva a cobranca de `iniciada` a `emitida`, e e o
        # `payment.reference_issued` do mapa.
        # Os mesmos argumentos que o `_levar_a` usa para esta aresta
        # (`CAMINHOS["emitida"]`): `informativo` e `sistema`. O `p_authn_ok`
        # fica na omissao da semente, para que este ensaio meca o mapa e nao
        # uma combinacao que a suite nunca produz.
        emitida = self.appendar(
            cursor, cobranca, self.conta, "referencia_emitida",
            p_decisao="informativo", p_authn_method="sistema",
        )
        self.appendar(
            cursor, cobranca, self.conta, "pagamento_recebido",
            p_decisao="informativo",
        )
        confirmada = self.appendar(
            cursor, cobranca, self.conta, "pagamento_confirmado"
        )
        for evento, tipo in (
            (emitida, "payment.reference_issued"),
            (confirmada, "payment.confirmed"),
        ):
            with self.subTest(evento=tipo):
                self.assertIsNotNone(evento[4], f"o mapa produz {tipo}")
                cursor.execute(
                    "SELECT envelope FROM platform.events_outbox "
                    " WHERE event_id = %s",
                    (evento[4],),
                )
                envelope = cursor.fetchone()[0]
                if isinstance(envelope, str):
                    envelope = json.loads(envelope)
                self.assertEqual(envelope["tipo"], tipo)
                self.assertEqual(envelope["agregado"]["tipo"], "order")
                self.assertEqual(envelope["agregado"]["id"], encomenda)
                jsonschema.validate(
                    envelope, esquema(tipo), format_checker=verificador()
                )
        self.confirmar(cursor, self.tenant)

    def test_o_payment_failed_sai_pela_receita_de_semente_e_valida(self) -> None:
        """O quinto par do mapa, pelo caminho que a semente da suite já tem.

        Mede duas coisas de uma vez, e a segunda é a que importa: que o
        `CAMINHOS["falhada"]` do `base.py` **continua a funcionar**. A barreira
        do `motivo` tornou-o inutilizável — o `_levar_a` não passava nenhum — e
        nenhum ensaio o usava, pelo que a suite ficava verde com uma receita de
        semente partida à espera de quem a chamasse. É a lição «uma restrição em
        tabela alheia pede o caminho de escrita», um nível abaixo: corrigir a
        receita sem a exercitar era repetir o defeito.
        """
        import jsonschema

        encomenda = self.criar_encomenda(self.tenant)
        cobranca = self.criar_cobranca(
            self.tenant, self.conta, order_id=encomenda, estado="falhada"
        )
        self.semente.execute(
            "SELECT estado, motivo_falha FROM platform.payment_charges "
            " WHERE id = %s",
            (cobranca,),
        )
        estado, motivo_falha = self.semente.fetchone()
        self.assertEqual(estado, "falhada", "a receita levou a cobranca la")
        self.assertEqual(motivo_falha, "valor_divergente")

        self.semente.execute(
            "SELECT envelope FROM platform.events_outbox "
            " WHERE tipo = 'payment.failed' AND agregado_id = %s",
            (encomenda,),
        )
        linha = self.semente.fetchone()
        self.assertIsNotNone(linha, "o quinto par do mapa produziu o evento")
        envelope = linha[0]
        if isinstance(envelope, str):
            envelope = json.loads(envelope)
        self.assertEqual(envelope["agregado"]["tipo"], "order")
        self.assertEqual(envelope["payload"]["motivo"], "valor_divergente")
        jsonschema.validate(
            envelope, esquema("payment.failed"), format_checker=verificador()
        )


if __name__ == "__main__":
    unittest.main()
