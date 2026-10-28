"""Criterio 6 do KAM-047: RLS `FORCE` nas quatro, e dois niveis de isolamento.

«Todas as tabelas tem `tenant_id` e RLS `FORCE`; X-05 (catalogo RLS) cobre o
esquema `servicos`; tenant A nao le marcacoes de B e contacto X nao le marcacoes
de Y (X-02/ISO).»

**Sao dois isolamentos diferentes, e so um deles e da RLS.**

- **Tenant A nao ve B** e da politica `tenant_iso`, e e por isso que estes
  testes correm como `kamba_app` (`NOBYPASSRLS`) e nunca como administrador: com
  o administrador a politica nao se aplica e o teste nao prova nada.
- **Contacto X nao ve Y** **nao** e da RLS: a politica isola tenants, e os dois
  contactos sao do mesmo tenant. Quem o impoe e o `contact_id` no `WHERE` das
  consultas do modulo — e e por isso que ele tem de estar la, e por isso que
  estes testes correm as consultas **do modulo** e nao um `SELECT` escrito aqui.

**O X-05 cobre o esquema sem ninguem o declarar.** O
`db/tests_isolamento/catalogo.py` descobre as tabelas pelo catalogo — exclui
`pg_catalog`, `information_schema` e `pg_toast`, e trata **todo o resto** como
aplicacional —, pelo que as quatro entram na verificacao de RLS do *gate* 6 por
construcao. O que este ficheiro acrescenta e a leitura directa das bandeiras,
para que uma revisao futura que ligue a RLS sem `FORCE` falhe aqui com a razao
escrita, e nao num oraculo generico.
"""

from __future__ import annotations

from tests_servicos.base import ComAgenda, intervalo, prazo_do_hold
from tests_servicos.consultas import (
    SQL_CANCELAR,
    SQL_CRIAR_HOLD,
    SQL_MARCACAO,
    SQL_OCUPADO,
)

CONTACTO_X = "11111111-1111-4111-8111-111111111111"
CONTACTO_Y = "22222222-2222-4222-8222-222222222222"


class TestAsBandeirasDaRls(ComAgenda):
    def test_as_quatro_tem_enable_e_force_e_a_politica_tenant_iso(self) -> None:
        """`FORCE` vincula tambem o dono: sem ele, o `kamba_migrator` via tudo."""
        linhas = self.consultar(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'servicos' AND c.relkind = 'r' "
            " ORDER BY c.relname"
        )
        self.assertEqual(
            linhas,
            [
                ("availability_rules", True, True),
                ("bookings", True, True),
                ("resources", True, True),
                ("services", True, True),
            ],
        )

        politicas = self.consultar(
            "SELECT tablename, policyname, qual, with_check FROM pg_policies "
            " WHERE schemaname = 'servicos' ORDER BY tablename"
        )
        self.assertEqual(
            [(t, p) for t, p, _, _ in politicas],
            [
                ("availability_rules", "tenant_iso"),
                ("bookings", "tenant_iso"),
                ("resources", "tenant_iso"),
                ("services", "tenant_iso"),
            ],
        )
        # **O `WITH CHECK` nao e redundante com o `USING`**: o primeiro decide o
        # que se pode escrever, o segundo o que se pode ler. Uma politica so com
        # `USING` deixava o `kamba_app` **inserir** uma marcacao no nome de outro
        # tenant — e e precisamente isso que o X-04 ataca.
        for tabela, _, qual, with_check in politicas:
            with self.subTest(tabela=tabela):
                self.assertIsNotNone(with_check, "a politica tem de ter WITH CHECK")
                self.assertEqual(qual, with_check)
                self.assertIn("current_setting('app.tenant_id'", str(qual))


class TestSemContextoNaoHaAgenda(ComAgenda):
    """Criterio 8: «operacoes sem `ctx.tenantId` falham fechadas»."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()
        inicio, fim = intervalo(60)
        self.semente.execute(
            SQL_CRIAR_HOLD,
            (
                self.tenant,
                CONTACTO_X,
                self.servico,
                self.recurso,
                "slot-x",
                inicio,
                fim,
                prazo_do_hold(),
            ),
        )
        self.booking = str(self.semente.fetchone()[0])

    def test_sem_contexto_a_leitura_devolve_zero_linhas(self) -> None:
        """`NULLIF(current_setting(..., true), '')::uuid` reduz a ausencia a NULL."""
        cursor = self.cursor_app(None)
        cursor.execute(SQL_MARCACAO, (self.booking,))
        self.assertIsNone(
            cursor.fetchone(),
            "sem contexto a politica nao e verdadeira para linha nenhuma",
        )
        cursor.connection.rollback()

    def test_sem_contexto_a_escrita_e_recusada(self) -> None:
        cursor = self.cursor_app(None)
        inicio, fim = intervalo(300)
        self.assertErroSql(
            "42501",
            cursor,
            SQL_CRIAR_HOLD,
            (
                self.tenant,
                CONTACTO_X,
                self.servico,
                self.recurso,
                "slot-sem-contexto",
                inicio,
                fim,
                prazo_do_hold(),
            ),
        )


class TestTenantNaoVeTenant(ComAgenda):
    """X-03 e X-04 sobre o esquema `servicos`, com as consultas do modulo."""

    def setUp(self) -> None:
        super().setUp()
        self.a, self.servico_a, self.recurso_a = self.criar_agenda()
        self.b, self.servico_b, self.recurso_b = self.criar_agenda()
        self.inicio, self.fim = intervalo(60)
        self.semente.execute(
            SQL_CRIAR_HOLD,
            (
                self.a,
                CONTACTO_X,
                self.servico_a,
                self.recurso_a,
                "slot-de-a",
                self.inicio,
                self.fim,
                prazo_do_hold(),
            ),
        )
        self.booking_a = str(self.semente.fetchone()[0])

    def test_o_tenant_b_nao_le_a_marcacao_de_a(self) -> None:
        cursor = self.cursor_app(self.b)
        cursor.execute(SQL_MARCACAO, (self.booking_a,))
        self.assertIsNone(cursor.fetchone())
        cursor.connection.rollback()

    def test_o_tenant_b_nao_ve_o_intervalo_ocupado_de_a(self) -> None:
        """A disponibilidade de B nao e afectada pela agenda de A.

        E a propriedade que faz da RLS uma barreira **exercida** nesta tabela: o
        `SQL_OCUPADO` nao tem `tenant_id` no `WHERE`, e se a politica falhasse, o
        recurso de A escondia horas a B.
        """
        cursor = self.cursor_app(self.b)
        cursor.execute(SQL_OCUPADO, (self.inicio, self.fim))
        self.assertEqual(list(cursor.fetchall()), [])
        cursor.connection.rollback()

        cursor_a = self.cursor_app(self.a)
        cursor_a.execute(SQL_OCUPADO, (self.inicio, self.fim))
        self.assertEqual(len(cursor_a.fetchall()), 1, "e A ve a sua")
        cursor_a.connection.rollback()

    def test_o_tenant_b_nao_cancela_a_marcacao_de_a(self) -> None:
        cursor = self.cursor_app(self.b)
        cursor.execute(SQL_CANCELAR, (self.booking_a, CONTACTO_X))
        self.assertIsNone(cursor.fetchone())
        cursor.connection.commit()
        self.assertEqual(self.contar(self.a, "hold"), 1)

    def test_o_tenant_b_nao_escreve_uma_marcacao_no_nome_de_a(self) -> None:
        """X-04: o `WITH CHECK` da politica, com o `tenant_id` de outro."""
        cursor = self.cursor_app(self.b)
        inicio, fim = intervalo(600)
        self.assertErroSql(
            "42501",
            cursor,
            SQL_CRIAR_HOLD,
            (
                self.a,
                CONTACTO_X,
                self.servico_a,
                self.recurso_a,
                "ataque",
                inicio,
                fim,
                prazo_do_hold(),
            ),
        )

    def test_o_tenant_id_da_restricao_de_exclusao_e_defesa_em_profundidade(self) -> None:
        """O `tenant_id WITH =` **nao e exercitavel** hoje, e isso diz-se.

        A pergunta que este teste responde e se o `tenant_id WITH =` da
        restricao de exclusao e uma barreira exercida ou redundancia. **E
        redundancia, enquanto o `resources_pkey` for o que e** — e a medicao
        esta aqui em vez de uma afirmacao.

        A cadeia: `resources_pkey` e `PRIMARY KEY (resource_id)`, sem o
        `tenant_id`, pelo que um `resource_id` e **globalmente** unico; a
        `bookings_recurso_fk` e composta `(tenant_id, resource_id)` e exige que
        o par exista em `resources`; logo um `resource_id` so existe num tenant,
        e duas marcacoes com o mesmo `resource_id` sao sempre do mesmo tenant. A
        tentativa de criar o mesmo `resource_id` em dois tenants falha com
        `23505 duplicate key value violates unique constraint "resources_pkey"`
        — medido, e e por isso que o cenario que o criterio descreve nao se
        consegue montar.

        **Nao se tira a coluna da restricao**, e a razao e esta: no dia em que
        alguem tornar o `resources_pkey` composto — que e a forma natural de o
        fazer, e a que as outras tabelas deste esquema usam no indice unico
        auxiliar —, o `tenant_id WITH =` passa a ser a **unica** coisa entre o
        recurso de um tenant e o intervalo de outro, e com ele vem tambem o que
        a mensagem de conflito do PostgreSQL diria: ela cita a chave em
        conflito, e sem aquela coluna isso era um canal de leitura entre
        vizinhos. Este teste falha nesse dia, e o comentario diz o que fazer:
        escrever o caso cruzado, que ate la nao existe.
        """
        self.assertErroSql(
            "23505",
            self.cursor_app(self.a, papel="batch"),
            "INSERT INTO servicos.resources (resource_id, tenant_id, nome) "
            "VALUES (%s, %s, 'partilhado')",
            (self.recurso_a, self.b),
        )
        linhas = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            " WHERE conname = 'resources_pkey' "
            "   AND connamespace = 'servicos'::regnamespace"
        )
        self.assertEqual(
            linhas,
            [("PRIMARY KEY (resource_id)",)],
            "se esta chave passar a ser composta com o tenant_id, o "
            "`tenant_id WITH =` da restricao de exclusao deixa de ser "
            "redundancia e passa a ser a barreira — e o caso cruzado tem de "
            "ser escrito",
        )


class TestContactoNaoVeContacto(ComAgenda):
    """X-02 **dentro** do tenant: e do `contact_id` no `WHERE`, nao da RLS."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant, self.servico, self.recurso = self.criar_agenda()
        inicio, fim = intervalo(60)
        self.semente.execute(
            SQL_CRIAR_HOLD,
            (
                self.tenant,
                CONTACTO_X,
                self.servico,
                self.recurso,
                "slot-de-x",
                inicio,
                fim,
                prazo_do_hold(),
            ),
        )
        self.booking_x = str(self.semente.fetchone()[0])

    def test_a_marcacao_de_x_e_legivel_no_tenant_e_filtrada_por_contacto(self) -> None:
        """A leitura **ve** a linha; quem a esconde de Y e o modulo, nao a base.

        Esta asercao e desconfortavel de proposito: o `SQL_MARCACAO` devolve a
        marcacao de X a qualquer contacto do mesmo tenant, porque a RLS isola
        tenants e nao contactos. O que impede Y de a ler e a comparacao
        `marcacao.contactId !== contactId` no `getBooking` — codigo, e nao
        barreira de base de dados.

        **Fica escrito porque e uma assimetria real** e nao uma distraccao: um
        leitor que assuma «a base protege tudo» tirava aquela comparacao a
        pensar que era redundante. O `cancelBooking` e o `rescheduleBooking` nao
        dependem dela — tem o `contact_id` no `WHERE`, e isso esta medido no
        `test_um_contacto_nao_cancela_a_marcacao_de_outro`.
        """
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_MARCACAO, (self.booking_x,))
        linha = cursor.fetchone()
        self.assertIsNotNone(linha)
        colunas = [d[0] for d in cursor.description]
        self.assertEqual(
            str(dict(zip(colunas, linha))["contact_id"]),
            CONTACTO_X,
            "a linha vem com o contacto dela; o filtro por contacto e do modulo",
        )
        cursor.connection.rollback()

    def test_o_cancelamento_filtra_por_contacto_na_propria_instrucao(self) -> None:
        cursor = self.cursor_app(self.tenant)
        cursor.execute(SQL_CANCELAR, (self.booking_x, CONTACTO_Y))
        self.assertIsNone(cursor.fetchone(), "Y nao cancela a marcacao de X")
        cursor.execute(SQL_CANCELAR, (self.booking_x, CONTACTO_X))
        self.assertIsNotNone(cursor.fetchone(), "X cancela a sua")
        cursor.connection.commit()
        self.assertEqual(self.contar(self.tenant, "cancelada"), 1)
