"""Criterio 7 do KAM-043: RLS `FORCE` nas duas, e a colisao de SKU entre tenants.

«RLS `FORCE` em `offer_terms` e `price_quotes`; ISO-39..42 passam; consulta com
`tenant_id` de outro tenant devolve 0 linhas.»

## O ISO-39..42 e definido sobre a `orders_mirror`, e aqui e por analogia

Vale a pena dize-lo, porque a caixa do criterio 7 nomeia a gama e a gama nao e
desta tabela. A matriz do `docs/tecnica/03` §4.4 escreve: «ISO-39..42 |
`orders_mirror` / RLS | Sessao SQL com `app.tenant_id` de A:
`SELECT/UPDATE/DELETE` em linhas de B; sessao sem `app.tenant_id` | 0 linhas;
falha fechada». A `orders_mirror` e do **KAM-044** e nao existe ainda.

O que se faz aqui e **a mesma forma contra as duas tabelas novas**, que e o que o
criterio 7 e os Testes Requeridos do bloco pedem («ISO-33..42 para estas
tabelas») e o que o KAM-051 chama, por escrito, «ISO-39..42 por analogia». Nao se
inventam IDs novos: os quatro casos ficam nomeados pela gama de origem, com a
tabela a que se aplicam no nome do teste.

## A sonda positiva, e porque e que quatro zeros nao provam nada

O `spikes/medusa-d3/iso.py` tem, fora da contagem, um `RLS-CONTROLO`: «as linhas
de A sao visiveis (senao os ISO-39..42 passam por vazio)». E a licao que esta
suite herda e que o `test_a_sonda_positiva...` implementa primeiro: uma bateria
que afirma «zero linhas» quatro vezes contra uma tabela vazia, ou contra um papel
sem `SELECT`, fica **verde sem RLS nenhuma**. Por isso cada caso negativo tem o
seu positivo ao lado, na mesma ligacao e com o mesmo papel.

## E corre como `kamba_app`, nunca como administrador

`kamba_app` e `NOBYPASSRLS`: e com ele que o modulo corre em producao. Com o
administrador a politica nao se aplica, e o teste nao prova nada.
"""

from __future__ import annotations

from tests_produtos.base import SKU_PARTILHADO, ComOfertas, daqui_a
from tests_produtos.consultas import SQL_TERMOS

#: As duas tabelas que esta revisao cria. A gama ISO aplica-se as duas.
TABELAS = ("offer_terms", "price_quotes")


class TestAsBandeirasDaRls(ComOfertas):
    def test_as_duas_tem_enable_e_force_e_a_politica_tenant_iso(self) -> None:
        """`FORCE` vincula tambem o dono: sem ele, o `kamba_migrator` via tudo.

        O X-05 do *gate* 6 descobre as tabelas pelo catalogo e nao por lista,
        pelo que estas duas entram na verificacao de RLS sem ninguem as
        declarar. O que este caso acrescenta e a **leitura directa das
        bandeiras**, para que uma revisao futura que ligue a RLS sem `FORCE`
        falhe aqui com a razao escrita, e nao num oraculo generico.
        """
        linhas = self.consultar(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relkind = 'r' "
            "   AND c.relname = ANY(%s) ORDER BY c.relname",
            (list(TABELAS),),
        )
        self.assertEqual(
            linhas,
            [("offer_terms", True, True), ("price_quotes", True, True)],
        )

    def test_a_politica_tem_using_e_with_check_e_sao_iguais(self) -> None:
        politicas = self.consultar(
            "SELECT tablename, policyname, qual, with_check FROM pg_policies "
            " WHERE schemaname = 'platform' AND tablename = ANY(%s) "
            " ORDER BY tablename",
            (list(TABELAS),),
        )
        self.assertEqual(
            [(t, p) for t, p, _, _ in politicas],
            [("offer_terms", "tenant_iso"), ("price_quotes", "tenant_iso")],
        )
        # **O `WITH CHECK` nao e redundante com o `USING`**: o primeiro decide o
        # que se pode escrever, o segundo o que se pode ler. Uma politica so com
        # `USING` deixava o `kamba_app` **inserir** uma oferta no nome de outro
        # tenant — e e precisamente isso que o X-04 ataca.
        for tabela, _, qual, with_check in politicas:
            with self.subTest(tabela=tabela):
                self.assertIsNotNone(with_check, "a politica tem de ter WITH CHECK")
                self.assertEqual(qual, with_check)
                self.assertIn("current_setting('app.tenant_id'", str(qual))


class TestIso3942NasTabelasNovas(ComOfertas):
    """A gama ISO-39..42, pela forma do §4.4, contra as duas tabelas novas."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant_a = self.criar_tenant()
        self.tenant_b = self.criar_tenant()
        self.criar_oferta(self.tenant_a, nome="arroz de A")
        self.criar_oferta(self.tenant_b, nome="arroz de B")
        self.contacto_b = self.criar_contacto(self.tenant_b)
        self.cotacao_de_b = self.criar_cotacao(self.tenant_b, self.contacto_b)

    def test_a_sonda_positiva_ve_as_linhas_do_proprio_tenant(self) -> None:
        """**Primeiro isto.** Sem ele, os quatro casos abaixo passam por vazio.

        E o `RLS-CONTROLO` do `spikes/medusa-d3/iso.py`, e esta primeiro de
        proposito: uma bateria que afirma «zero linhas» contra uma tabela vazia,
        ou com um papel sem `SELECT`, fica verde **sem RLS nenhuma**.
        """
        cursor = self.cursor_app(self.tenant_a)
        cursor.execute(
            "SELECT sku, nome FROM platform.offer_terms WHERE tenant_id = %s",
            (self.tenant_a,),
        )
        self.assertEqual(
            [tuple(linha) for linha in cursor.fetchall()],
            [(SKU_PARTILHADO, "arroz de A")],
            "o kamba_app nao ve a propria oferta: os casos negativos abaixo "
            "passariam por vazio e nao provariam RLS nenhuma",
        )
        cursor.execute(
            "SELECT count(*) FROM platform.price_quotes WHERE tenant_id = %s",
            (self.tenant_b,),
        )
        # Com o contexto de A, a cotacao de B nao se conta — mas a sonda da
        # cotacao propria vive no caso do tenant B, abaixo.
        self.assertEqual(int(cursor.fetchone()[0]), 0)

    def test_iso_39_select_na_linha_de_outro_tenant_da_zero_linhas(self) -> None:
        cursor = self.cursor_app(self.tenant_a)
        for tabela, filtro in (
            ("offer_terms", "sku = %s"),
            ("price_quotes", "id = %s"),
        ):
            alvo = SKU_PARTILHADO if tabela == "offer_terms" else self.cotacao_de_b
            with self.subTest(tabela=tabela):
                cursor.execute(
                    f"SELECT count(*) FROM platform.{tabela} WHERE {filtro}",
                    (alvo,),
                )
                # Em `offer_terms` o `sku` de B e o mesmo texto que o de A, e a
                # contagem com o contexto de A tem de dar **um** — o de A — e
                # nunca dois. E a colisao de SKU (ISO-33..38) e o ISO-39 no
                # mesmo caso.
                esperado = 1 if tabela == "offer_terms" else 0
                self.assertEqual(int(cursor.fetchone()[0]), esperado)

    def test_iso_39_a_linha_que_se_ve_e_a_propria_e_nao_a_do_outro(self) -> None:
        """O ISO-39 na forma que importa: **qual** linha, e nao quantas."""
        cursor = self.cursor_app(self.tenant_a)
        cursor.execute(
            "SELECT nome FROM platform.offer_terms WHERE sku = %s",
            (SKU_PARTILHADO,),
        )
        nomes = [str(linha[0]) for linha in cursor.fetchall()]
        self.assertEqual(nomes, ["arroz de A"])
        self.assertNotIn("arroz de B", nomes)

    def test_iso_40_update_na_linha_de_outro_tenant_nao_afecta_nada(self) -> None:
        cursor = self.cursor_app(self.tenant_a)
        # Sem `tenant_id` no `WHERE`: e o caso do §4.4, que mede a **politica** e
        # nao o predicado de quem escreve.
        cursor.execute(
            "UPDATE platform.offer_terms SET nome = 'invadido' WHERE sku = %s",
            (SKU_PARTILHADO,),
        )
        # Uma linha afectada — a de A. A de B fica intacta, e e o administrador
        # que o confirma, porque o `kamba_app` de A nao a consegue ler.
        self.assertEqual(cursor.rowcount, 1)
        cursor.connection.rollback()
        self.semente.execute(
            "SELECT nome FROM platform.offer_terms WHERE tenant_id = %s",
            (self.tenant_b,),
        )
        self.assertEqual(str(self.semente.fetchone()[0]), "arroz de B")

    def test_iso_41_delete_na_linha_de_outro_tenant_nao_apaga_nada(self) -> None:
        """O `kamba_app` **nao tem** `DELETE` nestas tabelas, e isso conta.

        O harness do spike distingue as duas barreiras de proposito: «o
        `kamba_app` nao tem `DELETE` em `orders_mirror`, pelo que o ISO-41 pode
        ser legitimamente bloqueado pelo `GRANT` e nao pela `tenant_iso`». Aqui e
        o mesmo, e por decisao da revisao `0028`: em `offer_terms` apagar e
        escrever `deleted_at`, e uma cotacao emitida e prova. Este caso afirma
        **a barreira que existe**, com o `SQLSTATE` do privilegio, em vez de
        afirmar zero linhas e deixar quem le a pensar que foi a politica.
        """
        cursor = self.cursor_app(self.tenant_a)
        for tabela in TABELAS:
            with self.subTest(tabela=tabela):
                # `42501`: insufficient_privilege.
                self.assertErroSql(
                    "42501",
                    cursor,
                    f"DELETE FROM platform.{tabela} WHERE tenant_id = %s",
                    (self.tenant_a,),
                )

    def test_iso_42_sem_contexto_nenhum_da_zero_linhas_e_falha_fechada(self) -> None:
        """Sessao **sem** `app.tenant_id`. A metade «falha fechada» do §4.4.

        `current_setting(..., true)` devolve NULL se a variavel nunca foi
        definida, e `''` depois de um `SET LOCAL` de outra transaccao ter
        expirado; o `NULLIF` reduz os dois a NULL, e `coluna = NULL` nao e
        verdadeiro para linha nenhuma.
        """
        cursor = self.cursor_app(None)
        for tabela in TABELAS:
            with self.subTest(tabela=tabela):
                cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
                self.assertEqual(int(cursor.fetchone()[0]), 0)

        # E uma escrita tambem nao passa: o `WITH CHECK` recusa-a. `42501` seria
        # privilegio; aqui o que falha e a politica, com `42501` da RLS sobre
        # `INSERT` — que o PostgreSQL devolve como `new row violates row-level
        # security policy` (`42501`).
        self.assertErroSql(
            "42501",
            cursor,
            "INSERT INTO platform.offer_terms "
            "(tenant_id, sku, nome, preco_tipo, preco_minor) "
            "VALUES (%s, 'x', 'x', 'fixo', 1)",
            (self.tenant_a,),
        )

    def test_um_contexto_que_nao_e_uuid_rebenta_em_vez_de_devolver_linhas(self) -> None:
        """Falha fechada **pelo lado ruidoso**, que e a outra metade do ISO-42.

        Um valor que nao seja UUID rebenta no `::uuid` do predicado. E a
        propriedade que o `db/rls.py` descreve, e vale a pena medi-la: um
        predicado que silenciasse o erro devolvia **todas** as linhas ou
        nenhuma, e as duas sao piores do que uma excepcao.
        """
        cursor = self.cursor_app("nao-e-uuid")
        # `22P02`: invalid_text_representation.
        self.assertErroSql(
            "22P02", cursor, "SELECT count(*) FROM platform.offer_terms"
        )


class TestColisaoDeSkuEntreTenants(ComOfertas):
    """ISO-33..38 na forma que estas tabelas permitem.

    A matriz do §4.4 define ISO-33..38 sobre **reservas** («A reserva stock de
    SKU de B por `sku` igual»), e as reservas sao do KAM-045. O que este ticket
    pode provar, e o que os Testes Requeridos lhe pedem («tenant A nao le SKU de
    B (colisao de SKU)»), e a metade de baixo: que o mesmo texto de `sku` em dois
    tenants sao **duas linhas independentes**, e que nenhum dos dois ve a do
    outro.
    """

    def test_o_mesmo_sku_existe_nos_dois_tenants_sem_conflito(self) -> None:
        a = self.criar_tenant()
        b = self.criar_tenant()
        # **Sem `ON CONFLICT`**: se a chave fosse so `(sku)`, este segundo
        # `INSERT` dava `23505` e o teste falhava aqui — que e exactamente o que
        # a chave composta existe para impedir.
        self.criar_oferta(a, nome="arroz de A", preco_minor=1_000_000)
        self.criar_oferta(b, nome="arroz de B", preco_minor=2_000_000)
        self.assertEqual(self.ofertas(a), [(SKU_PARTILHADO, "fixo", 1_000_000, "publicado")])
        self.assertEqual(self.ofertas(b), [(SKU_PARTILHADO, "fixo", 2_000_000, "publicado")])

    def test_a_consulta_do_modulo_com_o_ctx_de_a_nunca_devolve_o_preco_de_b(self) -> None:
        """E a consulta **do modulo**, lida do TypeScript, e nao uma copia dela."""
        a = self.criar_tenant()
        b = self.criar_tenant()
        self.criar_oferta(a, nome="arroz de A", preco_minor=1_000_000)
        self.criar_oferta(b, nome="arroz de B", preco_minor=2_000_000)

        cursor = self.cursor_app(a)
        cursor.execute(SQL_TERMOS.sql, SQL_TERMOS.args(a, SKU_PARTILHADO))
        linhas = [tuple(linha) for linha in cursor.fetchall()]
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][1], "arroz de A")
        self.assertEqual(linhas[0][3], 1_000_000)

        # E a mesma consulta com o `tenant_id` de B **no argumento** mas o
        # contexto de A devolve zero: as duas barreiras, e nao uma. O repo-base
        # nunca a chamaria assim (o `$1` vem do `ctx`), e e por isso que este
        # caso existe — mede a politica com o predicado a apontar para o outro
        # lado.
        cursor.execute(SQL_TERMOS.sql, SQL_TERMOS.args(b, SKU_PARTILHADO))
        # `list()`: o pg8000 devolve um tuplo vazio, e `() != []`.
        self.assertEqual(list(cursor.fetchall()), [])


class TestAsCotacoesNaoAtravessamTenants(ComOfertas):
    def test_a_fk_composta_recusa_uma_cotacao_sobre_o_contacto_de_outro(self) -> None:
        """A correccao de 2026-10-27 do §5.4, medida.

        Com a FK **simples** que o bloco SQL daquele §5.4 escreve
        (`REFERENCES platform.contacts(contact_id)`), esta insercao **passava**:
        a FK e satisfeita pela chave primaria de `contacts`, que nao inclui o
        tenant, e a politica olha para o `tenant_id` da linha da cotacao, que
        esta correcto. E o ISO-58 do spike KAM-041, na coluna desta tabela.

        Com a FK composta, falha com `23503`.
        """
        a = self.criar_tenant()
        b = self.criar_tenant()
        contacto_de_b = self.criar_contacto(b)
        self.criar_oferta(a)

        # `23503`: foreign_key_violation.
        self.assertErroSql(
            "23503",
            self.cursor_app(a),
            "INSERT INTO platform.price_quotes "
            "(tenant_id, contact_id, sku, qty, preco_total_minor, valida_ate, "
            " emitida_por) "
            "VALUES (%s, %s, %s, 1, 1000, %s, %s)",
            (a, contacto_de_b, SKU_PARTILHADO, daqui_a(horas=1), a),
        )

    def test_a_fk_composta_aceita_o_contacto_do_proprio_tenant(self) -> None:
        """O caminho legitimo. **E o caso que apanha uma FK demasiado estreita.**

        Duas vezes neste repositorio foi um caso do uso correcto que encontrou o
        defeito, e nao um canario da recusa — o `regiaoDoSet` do repo-base e a
        `0025`. Uma barreira que recusa o uso correcto nao protege: ensina o
        contorno.
        """
        a = self.criar_tenant()
        contacto = self.criar_contacto(a)
        self.criar_oferta(a)
        cursor = self.cursor_app(a)
        cursor.execute(
            "INSERT INTO platform.price_quotes "
            "(tenant_id, contact_id, sku, qty, preco_total_minor, valida_ate, "
            " emitida_por) "
            "VALUES (%s, %s, %s, 1, 1000, %s, %s) RETURNING id",
            (a, contacto, SKU_PARTILHADO, daqui_a(horas=1), a),
        )
        self.assertIsNotNone(cursor.fetchone()[0])
        cursor.connection.rollback()
