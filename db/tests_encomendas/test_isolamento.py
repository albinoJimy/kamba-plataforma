"""Criterio 6: RLS `FORCE`, registo *append-only* e ISO-39..42.

O que so aqui se prova, e nenhum duplo de teste pode: que um `INSERT` directo no
`order_state_log` falha por **privilegio** (`42501`) para o `kamba_app` no que
ele nao tem, e que o `deny_mutation` recusa `UPDATE`, `DELETE` e `TRUNCATE`
**ao superutilizador** — que e o unico que nenhum `REVOKE` prende. Uma base
falsa nao tem papeis, logo nao pode falhar por privilegio nenhum.

## A sonda positiva ao lado, sempre

Quatro zeros contra uma tabela vazia nao provam nada: e a licao que o
`db/tests_produtos/test_isolamento.py` escreveu. Cada ensaio de «B nao ve»
tem ao lado o «A ve», sobre a mesma linha.
"""

from __future__ import annotations

import pg8000.dbapi
from tests.base import PRIVILEGIO_INSUFICIENTE, sqlstate
from tests_encomendas.base import TRANSICAO_INVALIDA, ComEncomendas

#: As quatro tabelas com `tenant_id` da revisao. O grafo nao entra: nao a tem.
COM_TENANT = (
    "orders_mirror",
    "order_intents",
    "order_state_log",
    "order_reconciliation_issues",
)

#: O que o `kamba_app` pode alterar na `orders_mirror`, coluna a coluna.
UPDATE_DA_APP_EM_ENCOMENDAS = (
    "estado",
    "confirmacao_dono",
    "total_minor",
    "lines_snapshot",
    "entrega_modo",
    "medusa_order_id",
    "expira_at",
    "paga_at",
    "paga_via",
    "excepcao",
    "entregue_at",
    "entrega_confirmada_por",
    "version",
    "atualizado_at",
    "deleted_at",
)

#: O que ele **nao** pode alterar, e a razao de cada uma esta na revisao `0030`.
SEM_UPDATE_DA_APP = (
    "id",
    "tenant_id",
    "contact_id",
    "origem",
    "numero_publico",
    "intent_key",
    "currency",
    "criado_at",
)


class TestRlsDasEncomendas(ComEncomendas):
    """ISO-39..42: a encomenda de A nao se ve do contexto de B."""

    def setUp(self) -> None:
        super().setUp()
        self.a = self.criar_tenant()
        self.b = self.criar_tenant()
        self.encomenda = self.criar_encomenda(self.a)

    def test_as_quatro_tem_enable_force_e_politica(self) -> None:
        linhas = self.consultar(
            "SELECT c.relname::text, c.relrowsecurity, c.relforcerowsecurity, "
            "       count(p.polname) "
            "  FROM pg_class c LEFT JOIN pg_policy p ON p.polrelid = c.oid "
            " WHERE c.relnamespace = 'platform'::regnamespace "
            "   AND c.relname = ANY(%s) "
            " GROUP BY 1, 2, 3 ORDER BY 1",
            (list(COM_TENANT),),
        )
        self.assertEqual(
            linhas,
            [(tabela, True, True, 1) for tabela in sorted(COM_TENANT)],
        )

    def test_o_grafo_nao_tem_rls_e_nao_e_falta(self) -> None:
        """Tabela de referencia, sem `tenant_id`: o X-05 pergunta pela coluna."""
        linhas = self.consultar(
            # `count(a.attname)` e **nao** `count(*)`: num `LEFT JOIN` sem
            # correspondencia o `count(*)` conta a linha com nulos e devolve 1,
            # que e o que a primeira versao deste ensaio media (e falhava com
            # `(False, 1) != (False, 0)` sobre uma tabela que nao tem a coluna).
            "SELECT relrowsecurity, count(a.attname) FROM pg_class c "
            " LEFT JOIN pg_attribute a ON a.attrelid = c.oid "
            "       AND a.attname = 'tenant_id' AND a.attnum > 0 "
            " WHERE c.oid = 'platform.order_state_graph'::regclass "
            " GROUP BY 1"
        )
        self.assertEqual(linhas, [(False, 0)])

    def test_a_encomenda_de_a_ve_se_de_a_e_nao_de_b(self) -> None:
        _, cursor_a = self.ligar_app(self.a)
        cursor_a.execute(
            "SELECT count(*) FROM platform.orders_mirror WHERE id = %s",
            (self.encomenda,),
        )
        self.assertEqual(cursor_a.fetchone()[0], 1, "a sonda positiva")

        _, cursor_b = self.ligar_app(self.b)
        cursor_b.execute(
            "SELECT count(*) FROM platform.orders_mirror WHERE id = %s",
            (self.encomenda,),
        )
        self.assertEqual(cursor_b.fetchone()[0], 0, "ISO-39: B nao ve a de A")

    def test_sem_contexto_zero_linhas(self) -> None:
        """Falha fechada: `current_setting(..., true)` da NULL e nada iguala NULL."""
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        cursor.execute("SELECT count(*) FROM platform.orders_mirror")
        self.assertEqual(cursor.fetchone()[0], 0)

    def test_com_contexto_invalido_e_erro_e_nao_linhas(self) -> None:
        conexao = self.ligar("app")
        cursor = conexao.cursor()
        cursor.execute("SELECT set_config('app.tenant_id', 'nao-e-uuid', true)")
        cursor.fetchone()
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            cursor.execute("SELECT count(*) FROM platform.orders_mirror")

    def test_b_nao_escreve_uma_encomenda_com_o_tenant_de_a(self) -> None:
        """O `WITH CHECK` da politica: o `tenant_id` tem de ser o do contexto."""
        contacto = self.criar_contacto(self.a)
        conexao, cursor = self.ligar_app(self.b)
        with self.assertRaises(pg8000.dbapi.DatabaseError):
            cursor.execute(
                "INSERT INTO platform.orders_mirror "
                "       (tenant_id, contact_id, intent_key, total_minor, "
                "        lines_snapshot) "
                "VALUES (%s, %s, 'ik-cruzado', 1, '[]'::jsonb)",
                (self.a, contacto),
            )
        conexao.rollback()

    def test_uma_encomenda_de_a_nao_aponta_para_um_contacto_de_b(self) -> None:
        """ISO-58: a FK **composta**, e a simples deixava passar.

        Medido no spike KAM-041, e a correccao de 2026-10-27 do §5.4 nomeia
        esta tabela. A FK simples e satisfeita pela chave primaria de
        `contacts`, que nao inclui o tenant.
        """
        contacto_de_b = self.criar_contacto(self.b)
        try:
            self.criar_encomenda(self.a, contacto_de_b)
            self.fail("uma encomenda de A nao devia apontar para um contacto de B")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), "23503")

    def test_o_registo_de_a_nao_se_le_do_contexto_de_b(self) -> None:
        self.levar_a(self.a, self.encomenda, "aguarda_pagamento")
        _, cursor_a = self.ligar_app(self.a)
        cursor_a.execute(
            "SELECT count(*) FROM platform.order_state_log WHERE order_id = %s",
            (self.encomenda,),
        )
        self.assertEqual(cursor_a.fetchone()[0], 1, "a sonda positiva")
        _, cursor_b = self.ligar_app(self.b)
        cursor_b.execute(
            "SELECT count(*) FROM platform.order_state_log WHERE order_id = %s",
            (self.encomenda,),
        )
        self.assertEqual(cursor_b.fetchone()[0], 0)


class TestOsTriggersSaoSempreActivos(ComEncomendas):
    """Os cinco *triggers* sao `ENABLE ALWAYS`, e **nenhum ensaio o media**.

    **O achado 4 da revisao adversarial**: a revisao poe os cinco em `ALWAYS` e
    escreve a razao — a omissao (`O`) e saltada por
    `session_replication_role = replica`, e com ela um `UPDATE` escrevia `paga`
    sem evento nenhum e sem registo nenhum. A barreira estava certa (a propria
    revisao mediu-a a mao) e **nao tinha teste**: `grep tgenabled`
    em `db/tests_encomendas/` devolvia zero, enquanto a suite do ledger
    (`db/tests_pagamentos/`) o tem em quatro ficheiros.

    `A` e `ENABLE ALWAYS`; `O` e a omissao.
    """

    #: Os cinco, com o nome e a tabela.
    TRIGGERS = (
        ("orders_mirror", "order_nasce_criada"),
        ("orders_mirror", "order_transicao_valida"),
        ("orders_mirror", "order_estado_exige_log"),
        ("order_state_log", "order_state_log_sem_mutacao"),
        ("order_state_log", "order_state_log_sem_truncate"),
    )

    def test_os_cinco_sao_enable_always(self) -> None:
        linhas = self.consultar(
            "SELECT c.relname::text, t.tgname::text, t.tgenabled::text "
            "  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            " WHERE c.relnamespace = 'platform'::regnamespace "
            "   AND NOT t.tgisinternal "
            "   AND c.relname IN ('orders_mirror', 'order_state_log') "
            " ORDER BY 1, 2"
        )
        self.assertEqual(
            linhas,
            [(tabela, nome, "A") for tabela, nome in sorted(self.TRIGGERS)],
            "os cinco em `A`, e **so** os cinco: um *trigger* novo nestas duas "
            "tabelas entra por aqui, e um que perca o `ALWAYS` aparece como `O`",
        )

    def test_em_modo_replica_a_transicao_invalida_continua_recusada(self) -> None:
        """A prova de que o `ALWAYS` serve para alguma coisa, por execucao.

        `session_replication_role = replica` e o modo em que corre quem **aplica**
        replicacao logica, e salta os *triggers* de omissao. Com os cinco em
        `ALWAYS`, o grafo continua a recusar.
        """
        tenant = self.criar_tenant()
        encomenda = self.criar_encomenda(tenant)
        self.ensaio.execute("SET session_replication_role = replica")
        try:
            erro = self.tentar(
                "UPDATE platform.orders_mirror SET estado = 'entregue', "
                "       version = version + 1, entregue_at = now(), "
                "       entrega_confirmada_por = 'cliente' "
                " WHERE tenant_id = %s AND id = %s",
                (tenant, encomenda),
            )
            self.assertEqual(
                erro,
                TRANSICAO_INVALIDA,
                "em modo replica o *trigger* do grafo continua a recusar: e o "
                "que o `ENABLE ALWAYS` compra",
            )
        finally:
            self.ensaio.execute("SET session_replication_role = origin")
            self._ensaio.commit()

    def test_em_modo_replica_o_registo_continua_append_only(self) -> None:
        tenant = self.criar_tenant()
        encomenda = self.criar_encomenda(tenant)
        self.levar_a(tenant, encomenda, "aguarda_pagamento")
        try:
            # **As quatro instrucoes, e as duas sem linhas entraram com o
            # KAM-176.** O `replica` salta os *triggers* de omissao, pelo que
            # este ensaio mede o `ENABLE ALWAYS` — e media-o so para o `DELETE`.
            # O *trigger* por instrucao da `0031` passou a cobrir o `UPDATE`, e
            # o `ENABLE ALWAYS` dele tem de valer para a metade nova tambem:
            # sem estes casos, a revisao podia criar o *trigger* sem `ALWAYS` e
            # a suite ficava verde sobre uma barreira que o `replica` saltava.
            #
            # **O `SET` corre dentro do ciclo, e nao uma vez antes dele.** Um
            # `SET` cru e **desfeito por um `ROLLBACK`**, e o `tentar` faz
            # `rollback` em cada recusa: posto antes do ciclo, a partir da
            # segunda iteracao a sessao estava de volta em `origin` e as tres
            # restantes mediam o modo errado — verde pela razao errada, e sobre
            # a barreira que o `replica` existe para contornar. Nao mordia
            # enquanto este ensaio tinha uma instrucao so.
            for instrucao, parametros in (
                (
                    "DELETE FROM platform.order_state_log WHERE tenant_id = %s",
                    (tenant,),
                ),
                (
                    "UPDATE platform.order_state_log SET causa = 'reescrita' "
                    " WHERE tenant_id = %s",
                    (tenant,),
                ),
                (
                    "DELETE FROM platform.order_state_log "
                    " WHERE causa = 'nao-existe'",
                    (),
                ),
                (
                    "UPDATE platform.order_state_log SET causa = 'reescrita' "
                    " WHERE causa = 'nao-existe'",
                    (),
                ),
            ):
                with self.subTest(
                    instrucao=instrucao.split()[0], com_linhas=bool(parametros)
                ):
                    self.ensaio.execute("SET session_replication_role = replica")
                    # **Le-se o modo na mesma ligacao, antes de cada tentativa.**
                    # E a asercao que impede o defeito descrito acima de voltar:
                    # se um `ROLLBACK` tiver reposto o `origin`, este
                    # `assertEqual` falha em vez de a suite ficar verde a medir
                    # o modo errado.
                    self.ensaio.execute("SHOW session_replication_role")
                    self.assertEqual(
                        str(self.ensaio.fetchone()[0]),
                        "replica",
                        "o modo tem de estar activo no momento da instrucao, "
                        "senao este ensaio nao mede o ENABLE ALWAYS",
                    )
                    self.assertEqual(
                        self.tentar(instrucao, parametros),
                        PRIVILEGIO_INSUFICIENTE,
                    )
        finally:
            self.ensaio.execute("SET session_replication_role = origin")
            self._ensaio.commit()


class TestRegistoAppendOnly(ComEncomendas):
    """Criterio 6: «so `INSERT` para `kamba_app`»."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.encomenda = self.criar_encomenda(self.tenant)
        self.levar_a(self.tenant, self.encomenda, "aguarda_pagamento")

    def test_o_kamba_app_nao_tem_update_nem_delete_no_registo(self) -> None:
        linhas = self.consultar(
            "SELECT has_table_privilege('kamba_app', 'platform.order_state_log', p) "
            "  FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) AS p"
        )
        self.assertEqual(linhas, [(True,), (True,), (False,), (False,), (False,)])

    def test_o_update_do_kamba_app_no_registo_falha_por_privilegio(self) -> None:
        conexao, cursor = self.ligar_app(self.tenant)
        with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
            cursor.execute(
                "UPDATE platform.order_state_log SET causa = 'reescrita' "
                " WHERE tenant_id = %s",
                (self.tenant,),
            )
        self.assertEqual(sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE)
        conexao.rollback()

    def test_o_deny_mutation_recusa_tambem_ao_superutilizador(self) -> None:
        """O que nenhum `REVOKE` alcanca. Tres instrucoes, as tres recusadas."""
        for sql in (
            "UPDATE platform.order_state_log SET causa = 'x' WHERE tenant_id = %s",
            "DELETE FROM platform.order_state_log WHERE tenant_id = %s",
        ):
            with self.subTest(sql=sql.split()[0]):
                try:
                    self.semente.execute(sql, (self.tenant,))
                    self.fail(f"{sql.split()[0]} nao devia passar")
                except pg8000.dbapi.DatabaseError as erro:
                    self.assertEqual(sqlstate(erro), PRIVILEGIO_INSUFICIENTE)

        try:
            self.semente.execute("TRUNCATE platform.order_state_log")
            self.fail("TRUNCATE nao devia passar")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), PRIVILEGIO_INSUFICIENTE)

    def test_o_delete_sem_linhas_tambem_e_recusado(self) -> None:
        """O *trigger* por instrucao, que e a razao de serem dois.

        Um `BEFORE DELETE FOR EACH ROW` nao dispara quando nao ha linhas, e um
        `DELETE` que nao apaga nada **parecia** passar — o que deixava quem
        auditasse a pensar que a tabela aceita `DELETE`.
        """
        try:
            self.semente.execute(
                "DELETE FROM platform.order_state_log WHERE causa = 'nao-existe'"
            )
            self.fail("um DELETE sem linhas tambem devia ser recusado")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), PRIVILEGIO_INSUFICIENTE)

    def test_o_update_sem_linhas_tambem_e_recusado(self) -> None:
        """A metade que o KAM-044 deixou aberta, fechada pelo KAM-176.

        O `order_state_log_sem_mutacao` e `FOR EACH ROW` e nao dispara quando
        nao ha linhas; o `order_state_log_sem_truncate` era
        `BEFORE TRUNCATE OR DELETE` e parava ali. Logo um
        `UPDATE ... WHERE <predicado que nao casa>` devolvia `UPDATE 0` e
        passava, e quem auditasse lia a ausencia de erro como «a tabela aceita
        `UPDATE` e nao havia nada para actualizar».

        **Ensaio separado do do `DELETE`, de proposito** (criterio 2 do
        KAM-176): uma asercao que cobrisse os dois casos nao distinguia qual
        deles regrediu, e o do `DELETE` acima fica como estava.

        **Dois predicados, e sao dois pela licao da revisao adversarial do
        KAM-175** (achado 11): o `causa = 'nao-existe'` e o caso real, e o
        `false` e o degenerado, onde o planeador sabe de antemao que nao ha
        linhas (`One-Time Filter: false`). Medido: o *trigger* por instrucao
        dispara nos dois.
        """
        for predicado in (" WHERE causa = 'nao-existe'", " WHERE false"):
            with self.subTest(predicado=predicado.strip()):
                try:
                    self.semente.execute(
                        "UPDATE platform.order_state_log SET causa = 'reescrita'"
                        + predicado
                    )
                    self.fail("um UPDATE sem linhas tambem devia ser recusado")
                except pg8000.dbapi.DatabaseError as erro:
                    self.assertEqual(sqlstate(erro), PRIVILEGIO_INSUFICIENTE)

    def test_a_lista_de_eventos_dos_triggers_do_registo_esta_no_catalogo(self) -> None:
        """O `tgtype`, e nao so o nome e o `tgenabled`.

        O `TestOsTriggersSaoSempreActivos` deste ficheiro compara pares
        `(tabela, trigger)` com o `tgenabled`, e o `db/tests/test_inventario.py`
        prende os nomes. **Nenhum dos dois diz que eventos cada *trigger*
        cobre**, pelo que a forma so se confirmava por comportamento — e e por
        isso que o `DELETE` fechado e o `UPDATE` aberto conviveram aqui sem
        ninguem notar. Aqui prende-se, pelo `pg_get_triggerdef`, que e o que o
        servidor reconstroi da sua propria tabela de catalogo.

        E a licao do achado 10 da revisao adversarial do KAM-175, aplicada a
        tabela irma: um escape que um portao podia ter apanhado vira portao.
        """
        definicoes = {
            nome: texto
            for nome, texto in self.consultar(
                "SELECT t.tgname::text, pg_get_triggerdef(t.oid) FROM pg_trigger t "
                "  JOIN pg_class c ON c.oid = t.tgrelid "
                "  JOIN pg_namespace n ON n.oid = c.relnamespace "
                " WHERE n.nspname = 'platform' "
                "   AND c.relname = 'order_state_log' AND NOT t.tgisinternal"
            )
        }
        # **Nao se compara a frase inteira**: o `pg_get_triggerdef` reordena os
        # eventos pela ordem canonica do catalogo, que nao e a ordem em que a
        # revisao os escreveu. O que se prende e o **conjunto** de verbos e o
        # nivel, que e a propriedade; a ordem do texto nao e.
        por_linha = definicoes["order_state_log_sem_mutacao"]
        por_instrucao = definicoes["order_state_log_sem_truncate"]

        self.assertIn("FOR EACH ROW", por_linha)
        self.assertIn("FOR EACH STATEMENT", por_instrucao)
        self.assertNotIn(
            "TRUNCATE",
            por_linha,
            "o FOR EACH ROW nao admite TRUNCATE, e e a razao de serem dois",
        )
        # **A funcao tambem, e nao so os verbos e o nivel.** O criterio 1 pede
        # «continua a chamar a `platform.deny_mutation()`», e sem esta asercao
        # uma revisao que apontasse o *trigger* para outra funcao ficava verde
        # aqui e verde no `test_os_cinco_sao_enable_always`. Apanhado pela
        # revisao adversarial do KAM-176.
        for nome, definicao in (("sem_mutacao", por_linha), ("sem_truncate", por_instrucao)):
            with self.subTest(trigger=nome, parte="funcao"):
                self.assertIn(
                    "EXECUTE FUNCTION platform.deny_mutation()", definicao
                )
        for verbo in ("UPDATE", "DELETE"):
            with self.subTest(trigger="sem_mutacao", verbo=verbo):
                self.assertIn(verbo, por_linha.split(" ON ")[0])
        for verbo in ("TRUNCATE", "DELETE", "UPDATE"):
            with self.subTest(trigger="sem_truncate", verbo=verbo):
                self.assertIn(
                    verbo,
                    por_instrucao.split(" ON ")[0],
                    "o por instrucao tem de cobrir os tres eventos: e ele que "
                    "da a propriedade para a instrucao que nao toca linha "
                    "nenhuma (KAM-176)",
                )

    def test_o_insert_no_registo_com_on_conflict_do_update_e_recusado(self) -> None:
        """Uma consequencia do `FOR EACH STATEMENT` que vale declarar.

        Um *trigger* `BEFORE UPDATE ... FOR EACH STATEMENT` dispara num
        `INSERT ... ON CONFLICT DO UPDATE` **mesmo quando nao ha conflito** e o
        ramo de `UPDATE` nunca e tomado. Medido no KAM-175 para a
        `payment_events`; vale aqui pela mesma razao, e desde esta revisao
        tambem para o `UPDATE` e nao so para o `DELETE`.

        **Nao quebra caminho nenhum hoje**: o registo e escrito pelo
        `inserirNoTenant` e por mais nada, e a idempotencia dele vive na
        restricao `order_state_log_version_uq` — o ensaio a seguir — e nao num
        `ON CONFLICT`. Fica medido para quem escrever o proximo escritor, em vez
        de aparecer como uma recusa que fala de imutabilidade num `INSERT`
        legitimo.

        **O alvo do `ON CONFLICT` sao as tres colunas e nao duas.** A
        `order_state_log_version_uq` e `UNIQUE (tenant_id, order_id, version)`;
        com `(order_id, version)` o PostgreSQL recusa com `42P10` — «no unique or
        exclusion constraint matching the ON CONFLICT specification» — **no
        planeador**, antes de qualquer *trigger*, e o ensaio passava a medir um
        defeito do proprio ensaio em vez da barreira. Medido na primeira
        execucao desta suite.

        **E a `version` tem de ser uma que NAO exista.** Com `version = 2` havia
        **sempre** conflito — o `setUp` leva a encomenda a `aguarda_pagamento` e
        o `transitar` escreve o registo com `version = 2` —, pelo que o ramo de
        `UPDATE` era tomado e o `order_state_log_sem_mutacao` (`FOR EACH ROW`) ja
        bastava para recusar: o ensaio ficava verde **com a barreira nova
        retirada** e nao media nada do que o seu nome diz. Medido pela revisao
        adversarial, que correu a suite com a mutacao aplicada e viu este ensaio
        **sobreviver**. Com uma `version` livre nao ha conflito, o ramo de
        `UPDATE` nunca e tomado, e so o *trigger* por instrucao pode recusar — e
        e isso que torna esta asercao uma medicao da barreira da `0031`.
        """
        try:
            self.ensaio.execute(
                "INSERT INTO platform.order_state_log "
                "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
                "VALUES (%s, %s, 'criada', 'aguarda_pagamento', 99, 'sem-conflito',"
                "        'ops') "
                " ON CONFLICT (tenant_id, order_id, version) "
                "   DO UPDATE SET causa = 'adulterada'",
                (self.tenant, self.encomenda),
            )
            self.fail("um ON CONFLICT DO UPDATE no registo devia ser recusado")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), PRIVILEGIO_INSUFICIENTE)
        finally:
            self._ensaio.rollback()

    def test_a_mesma_transicao_gravada_duas_vezes_e_unicidade(self) -> None:
        """A idempotencia do DoD, na restricao e nao no codigo."""
        try:
            self.semente.execute(
                "INSERT INTO platform.order_state_log "
                "       (tenant_id, order_id, de, para, version, causa, actor_kind) "
                "VALUES (%s, %s, 'criada', 'aguarda_pagamento', 2, 'repetida', 'ops')",
                (self.tenant, self.encomenda),
            )
            self.fail("a mesma `(order_id, version)` nao devia passar duas vezes")
        except pg8000.dbapi.DatabaseError as erro:
            self.assertEqual(sqlstate(erro), "23505")


class TestCanarioDoTriggerPorInstrucaoDoRegisto(ComEncomendas):
    """Criterio 4 do KAM-176: **qual** dos dois *triggers* recusa o caso sem linhas.

    Com os dois ligados, o caso e recusado e nenhum ensaio distingue quem
    mordeu. Desligado **so** o `order_state_log_sem_truncate` — com o
    `order_state_log_sem_mutacao` ligado —, o `UPDATE` sem linhas tem de
    **passar**: e isso, e so isso, que prova que quem da a propriedade e o
    *trigger* por instrucao.

    **E corre nos dois sentidos**, que e a licao do achado 3 da revisao
    adversarial do KAM-175: um canario que desligue sempre o mesmo *trigger*
    prova uma proposicao e deixa a irma por medir — e la a celula que afirmava a
    redundancia citava justamente o ensaio da proposicao inversa. Os dois
    ensaios desta classe desligam um *trigger* de cada vez.

    **O `ALTER TABLE` corre na ligacao transaccional (`self.ensaio`) e e
    revertido**, pela razao escrita no `TestCanarioDoTrigger` do
    `test_grafo.py`: um `ALTER TABLE` confirmado deixava a base do *gate* 8 sem
    barreira para os ensaios seguintes, e a suite passava a medir uma tabela sem
    *trigger*.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.encomenda = self.criar_encomenda(self.tenant)
        self.levar_a(self.tenant, self.encomenda, "aguarda_pagamento")

    def test_sem_o_trigger_por_instrucao_o_update_sem_linhas_passa(self) -> None:
        try:
            self.ensaio.execute(
                "ALTER TABLE platform.order_state_log DISABLE TRIGGER "
                "order_state_log_sem_truncate"
            )
            # O por linha fica **ligado**: e o que torna isto um canario do por
            # instrucao e nao de «a tabela nao tem triggers».
            self.assertEqual(self._tgenabled("order_state_log_sem_mutacao"), "A")
            self.ensaio.execute(
                "UPDATE platform.order_state_log SET causa = 'reescrita' "
                " WHERE causa = 'nao-existe'"
            )
            self.assertEqual(
                self.ensaio.rowcount,
                0,
                "com o por instrucao desligado o UPDATE passa, e nao toca linha "
                "nenhuma: e esse par que prova quem recusa",
            )
        finally:
            self._ensaio.rollback()

    def test_sem_o_por_linha_o_update_com_linhas_continua_recusado(self) -> None:
        """O sentido simetrico, e o que mede a redundancia do por linha.

        Desligado so ele, com o por instrucao ligado, um `UPDATE` **com** linhas
        continua recusado. O `setUp` deixou uma linha de registo, e sem ela o por
        instrucao recusaria de qualquer forma — a asercao deixava de medir «com
        linhas», que e o defeito que o achado 3 do KAM-175 apanhou.

        ## «Redundante» tem um limite, e nao e «estritamente»

        O por linha e redundante para **toda a instrucao SQL** — e o que este
        ensaio mede. **Nao** e redundante para um `UPDATE` aplicado por
        **replicacao logica**: o aplicador dispara *triggers* por linha marcados
        `ALWAYS`/`REPLICA` e **nao** dispara os por instrucao, porque nao ha
        instrucao a disparar. Nesse caminho o por linha e a **unica** barreira.

        Esta distincao nao se mede aqui, e di-lo: um `SET
        session_replication_role = replica` com um `UPDATE` SQL — que e o que o
        `test_em_modo_replica_o_registo_continua_append_only` faz — **tem**
        instrucao, logo dispara o por instrucao. Medir o outro caminho exigia
        uma publicacao e uma subscricao reais, que este repositorio nao tem.
        Estado: **NAO VERIFICADO** por execucao; a semantica do PostgreSQL e
        documentada. Apanhado pela revisao adversarial do KAM-176.

        **Logo o por linha fica por ter um caminho proprio**, e nao por
        contabilidade de ensaios. Que dois ensaios o prendam pelo nome — o
        `test_os_cinco_sao_enable_always` desta mesma suite e o
        `test_a_lista_de_eventos_dos_triggers_do_registo_esta_no_catalogo` — e
        consequencia, nao razao. (O `db/tests/test_inventario.py` **nao** prende
        o nome destes dois *triggers*: prende as restricoes do
        `order_state_log`. A primeira versao deste docstring dizia o contrario.)
        """
        self.assertGreater(
            self.consultar(
                "SELECT count(*) FROM platform.order_state_log WHERE order_id = %s",
                (self.encomenda,),
            )[0][0],
            0,
            "o ensaio precisa de linhas para medir o caso «com linhas»",
        )
        try:
            self.ensaio.execute(
                "ALTER TABLE platform.order_state_log DISABLE TRIGGER "
                "order_state_log_sem_mutacao"
            )
            self.assertEqual(self._tgenabled("order_state_log_sem_truncate"), "A")
            with self.assertRaises(pg8000.dbapi.DatabaseError) as capturado:
                self.ensaio.execute(
                    "UPDATE platform.order_state_log SET causa = 'reescrita' "
                    " WHERE order_id = %s",
                    (self.encomenda,),
                )
            self.assertEqual(
                sqlstate(capturado.exception), PRIVILEGIO_INSUFICIENTE
            )
        finally:
            self._ensaio.rollback()

    def _tgenabled(self, trigger: str) -> str:
        """O estado do *trigger* **na mesma ligacao** que largou o outro.

        Le-se do `self.ensaio` e nao do `self.consultar`: o `ALTER TABLE` ainda
        nao esta confirmado, pelo que outra ligacao veria o estado antigo e a
        asercao passava sem medir nada.
        """
        self.ensaio.execute(
            "SELECT t.tgenabled::text FROM pg_trigger t "
            "  JOIN pg_class c ON c.oid = t.tgrelid "
            "  JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'platform' AND c.relname = 'order_state_log' "
            "   AND t.tgname = %s",
            (trigger,),
        )
        return str(self.ensaio.fetchone()[0])


class TestPrivilegiosPorColuna(ComEncomendas):
    """O `UPDATE` da encomenda e **por coluna**, e nos dois sentidos.

    A matriz de `db/tests/test_privilegios.py` nao o ve: o
    `has_table_privilege(..., 'UPDATE')` devolve `false` com ou sem um
    `GRANT UPDATE (estado)`. E a mesma razao pela qual a `offer_terms` do
    KAM-043 tem o seu ensaio em `db/tests_produtos/test_contrato.py`.
    """

    def test_o_update_e_por_coluna(self) -> None:
        for coluna in UPDATE_DA_APP_EM_ENCOMENDAS:
            with self.subTest(coluna=coluna, sentido="tem"):
                self.assertEqual(
                    self.consultar(
                        "SELECT has_column_privilege('kamba_app', "
                        "       'platform.orders_mirror', %s, 'UPDATE')",
                        (coluna,),
                    ),
                    [(True,)],
                )
        for coluna in SEM_UPDATE_DA_APP:
            with self.subTest(coluna=coluna, sentido="nao tem"):
                self.assertEqual(
                    self.consultar(
                        "SELECT has_column_privilege('kamba_app', "
                        "       'platform.orders_mirror', %s, 'UPDATE')",
                        (coluna,),
                    ),
                    [(False,)],
                    "mudar esta coluna era mudar a identidade da encomenda ou "
                    "a referencia que o cliente tem no telemovel",
                )

    def test_as_duas_listas_cobrem_a_tabela_inteira(self) -> None:
        """Nos dois sentidos: uma coluna nova cai numa das duas ou falha aqui."""
        colunas = {
            coluna
            for (coluna,) in self.consultar(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_schema = 'platform' AND table_name = 'orders_mirror'"
            )
        }
        self.assertEqual(
            colunas,
            set(UPDATE_DA_APP_EM_ENCOMENDAS) | set(SEM_UPDATE_DA_APP),
        )

    def test_a_divergencia_fecha_se_por_duas_colunas(self) -> None:
        for coluna, esperado in (
            ("estado", True),
            ("resolvida_at", True),
            ("tipo", False),
            ("detalhe", False),
            ("order_id", False),
        ):
            with self.subTest(coluna=coluna):
                self.assertEqual(
                    self.consultar(
                        "SELECT has_column_privilege('kamba_app', "
                        "       'platform.order_reconciliation_issues', %s, 'UPDATE')",
                        (coluna,),
                    ),
                    [(esperado,)],
                )
