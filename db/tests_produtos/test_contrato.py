"""Criterio 1 do KAM-043: o `CHECK` do preco opaco, e o contrato com o modulo.

«`offer_terms` aplica `CHECK` `(preco_tipo='sob_consulta' AND preco_minor IS
NULL) OR (preco_tipo<>'sob_consulta' AND preco_minor IS NOT NULL)`; valores em
`bigint` minor (1 Kz = 100 centimos) com `currency='AOA'`; **inserir violacao
falha na BD**.»

A ultima metade e a que obriga a esta suite: «falha na BD» nao se prova contra
uma base falsa, e um `CHECK` escrito num documento e uma *proposta* de esquema
ate alguem o correr.
"""

from __future__ import annotations

from tests_produtos import consultas
from tests_produtos.base import PRECO, SKU_PARTILHADO, ComOfertas, daqui_a
from tests_produtos.consultas import EXERCITADAS


class TestOCheckDoPrecoOpaco(ComOfertas):
    """As **duas** metades da equivalencia, e nao so uma."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.cursor = self.cursor_app(self.tenant)

    def inserir(self, **campos):
        valores = {
            "tenant_id": self.tenant,
            "sku": SKU_PARTILHADO,
            "nome": "arroz",
            "preco_tipo": "fixo",
            "preco_minor": PRECO,
        }
        valores.update(campos)
        colunas = ", ".join(valores)
        marcas = ", ".join(["%s"] * len(valores))
        return (
            f"INSERT INTO platform.offer_terms ({colunas}) VALUES ({marcas})",
            tuple(valores.values()),
        )

    def test_sob_consulta_com_preco_falha_na_bd(self) -> None:
        """A primeira metade: um numero que ninguem cotou."""
        sql, args = self.inserir(preco_tipo="sob_consulta", preco_minor=PRECO)
        # `23514`: check_violation.
        self.assertErroSql("23514", self.cursor, sql, args)

    def test_fixo_sem_preco_falha_na_bd(self) -> None:
        """A segunda metade, **e e a que uma leitura distraida deixa passar**.

        Um `sob_consulta` com preco e o caso que se ve; um `fixo` sem preco e o
        que faz falta mais vezes, porque deixa o agente sem *fact* para citar — e
        um `CHECK` que so verificasse o primeiro sentido aceitava-o.
        """
        sql, args = self.inserir(preco_tipo="fixo", preco_minor=None)
        self.assertErroSql("23514", self.cursor, sql, args)

    def test_a_partir_de_sem_minimo_falha_na_bd(self) -> None:
        sql, args = self.inserir(preco_tipo="a_partir_de", preco_minor=None)
        self.assertErroSql("23514", self.cursor, sql, args)

    def test_os_tres_pares_legitimos_entram(self) -> None:
        """O caminho correcto. **Sem ele, os tres casos acima nao dizem nada.**

        Um `CHECK` escrito ao contrario — `AND` onde devia estar `OR` — recusava
        tudo, e os tres casos negativos acima ficavam verdes sobre uma tabela
        onde nao se consegue inserir nada.
        """
        for i, (tipo, minor) in enumerate(
            [("fixo", PRECO), ("a_partir_de", PRECO), ("sob_consulta", None)]
        ):
            with self.subTest(preco_tipo=tipo):
                sql, args = self.inserir(
                    sku=f"sku-{i}", preco_tipo=tipo, preco_minor=minor
                )
                self.cursor.execute(sql, args)
                self.assertEqual(self.cursor.rowcount, 1)
        self.cursor.connection.rollback()

    def test_um_preco_negativo_falha_na_bd(self) -> None:
        sql, args = self.inserir(preco_minor=-1)
        self.assertErroSql("23514", self.cursor, sql, args)

    def test_uma_moeda_fora_do_dominio_falha_na_bd(self) -> None:
        """`currency` ∈ {`AOA`} — o dominio de um valor do dicionario §3.4.

        **E e por isto que a coluna e `text` com `CHECK` e nao `char(3)`**, como
        o §5.4 escreve: um `char(3)` sem `CHECK` aceitava `'USD'` em silencio, e
        gate nenhum o leria.
        """
        sql, args = self.inserir(currency="USD")
        self.assertErroSql("23514", self.cursor, sql, args)

    def test_os_dominios_fechados_recusam_um_valor_inventado(self) -> None:
        for coluna, mau in (
            ("preco_tipo", "exato"),
            ("stock_modo", "ilimitado"),
            ("estado", "live"),
        ):
            with self.subTest(coluna=coluna):
                sql, args = self.inserir(**{coluna: mau})
                self.assertErroSql("23514", self.cursor, sql, args)

    def test_um_sku_ou_nome_em_branco_falha_na_bd(self) -> None:
        """Texto em branco nao e um identificador nem um nome."""
        for coluna in ("sku", "nome"):
            with self.subTest(coluna=coluna):
                sql, args = self.inserir(**{coluna: "   "})
                self.assertErroSql("23514", self.cursor, sql, args)

    def test_uma_categoria_restrita_vazia_falha_na_bd(self) -> None:
        """Vazio nao e «sem categoria restrita»: o `publishProduct` lia-o como
        presente e bloqueava a publicacao sem dizer qual."""
        sql, args = self.inserir(categoria_restrita="")
        self.assertErroSql("23514", self.cursor, sql, args)

    def test_a_chave_e_composta_e_repetir_o_sku_no_mesmo_tenant_falha(self) -> None:
        sql, args = self.inserir()
        self.cursor.execute(sql, args)
        # `23505`: unique_violation.
        self.assertErroSql("23505", self.cursor, sql, args)
        self.cursor.connection.rollback()

    def test_o_dinheiro_e_bigint_e_nao_integer(self) -> None:
        """Acima de 2^31 centimos um `integer` estourava. O §5.4 diz `bigint`."""
        acima_de_um_integer = 3_000_000_000
        sql, args = self.inserir(preco_minor=acima_de_um_integer)
        self.cursor.execute(sql, args)
        self.semente.execute(
            "SELECT preco_minor FROM platform.offer_terms WHERE tenant_id = %s",
            (self.tenant,),
        )
        # Nada ainda: a transaccao do `kamba_app` nao confirmou. O que este caso
        # prova e que o `INSERT` **passou** — com `integer` dava `22003`.
        self.assertEqual(self.cursor.rowcount, 1)
        self.cursor.connection.rollback()


class TestOCheckDaCotacao(ComOfertas):
    def setUp(self) -> None:
        super().setUp()
        self.tenant = self.criar_tenant()
        self.contacto = self.criar_contacto(self.tenant)
        self.criar_oferta(self.tenant)
        self.cursor = self.cursor_app(self.tenant)

    def inserir(self, **campos):
        valores = {
            "tenant_id": self.tenant,
            "contact_id": self.contacto,
            "sku": SKU_PARTILHADO,
            "qty": 10,
            "preco_total_minor": PRECO * 10,
            "valida_ate": daqui_a(horas=24),
            "emitida_por": self.tenant,
        }
        valores.update(campos)
        colunas = ", ".join(valores)
        marcas = ", ".join(["%s"] * len(valores))
        return (
            f"INSERT INTO platform.price_quotes ({colunas}) VALUES ({marcas})",
            tuple(valores.values()),
        )

    def test_uma_quantidade_nula_ou_negativa_falha_na_bd(self) -> None:
        for qty in (0, -1):
            with self.subTest(qty=qty):
                sql, args = self.inserir(qty=qty)
                self.assertErroSql("23514", self.cursor, sql, args)

    def test_um_total_negativo_falha_na_bd(self) -> None:
        sql, args = self.inserir(preco_total_minor=-1)
        self.assertErroSql("23514", self.cursor, sql, args)

    def test_um_estado_fora_do_dominio_falha_na_bd(self) -> None:
        sql, args = self.inserir(estado="pendente")
        self.assertErroSql("23514", self.cursor, sql, args)

    def test_a_cotacao_legitima_entra(self) -> None:
        sql, args = self.inserir()
        self.cursor.execute(sql, args)
        self.assertEqual(self.cursor.rowcount, 1)
        self.cursor.connection.rollback()


class TestOInventarioDasDuasTabelas(ComOfertas):
    """O que a revisao criou, e que o inventario fechado nomeia.

    O catalogo completo e a pergunta «guarda dados pessoais?» vivem em
    `db/tests/test_inventario.py`, que e onde o trinco esta. O que este caso
    acrescenta e a forma das chaves e dos indices, que esse ficheiro nao le.
    """

    def test_a_chave_primaria_da_oferta_e_composta_por_tenant_e_sku(self) -> None:
        linhas = self.consultar(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
            " WHERE conrelid = 'platform.offer_terms'::regclass AND contype = 'p'"
        )
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0][0], "offer_terms_pkey")
        self.assertEqual(linhas[0][1], "PRIMARY KEY (tenant_id, sku)")

    def test_a_fk_do_contacto_da_cotacao_e_composta(self) -> None:
        """A correccao de 2026-10-27 do §5.4, lida no catalogo."""
        linhas = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            " WHERE conrelid = 'platform.price_quotes'::regclass "
            "   AND contype = 'f' AND conname = "
            "       'price_quotes_contacto_do_mesmo_tenant_fk'"
        )
        self.assertEqual(len(linhas), 1)
        self.assertIn("(tenant_id, contact_id)", linhas[0][0])
        self.assertIn("platform.contacts(tenant_id, contact_id)", linhas[0][0])

    def test_as_fk_nao_apagam_em_cascata(self) -> None:
        """Nenhuma FK destas duas tabelas apaga em cascata, de proposito.

        Apagar um tenant nao apaga as ofertas em silencio: a retencao e
        explicita (KAM-071), e um `CASCADE` tornava-a invisivel.
        """
        linhas = self.consultar(
            "SELECT conname, confdeltype FROM pg_constraint "
            " WHERE conrelid IN ('platform.offer_terms'::regclass, "
            "                    'platform.price_quotes'::regclass) "
            "   AND contype = 'f' ORDER BY conname"
        )
        self.assertNotEqual(linhas, [])
        for nome, tipo in linhas:
            with self.subTest(fk=nome):
                # `a` = NO ACTION. `c` seria `CASCADE`.
                self.assertEqual(tipo, "a", f"{nome} apaga em cascata")

    def test_o_indice_de_trigramas_existe_e_usa_o_pg_trgm(self) -> None:
        linhas = self.consultar(
            "SELECT indexdef FROM pg_indexes "
            " WHERE schemaname = 'platform' "
            "   AND indexname = 'offer_terms_nome_trgm_idx'"
        )
        self.assertEqual(len(linhas), 1)
        self.assertIn("gin", linhas[0][0].lower())
        self.assertIn("gin_trgm_ops", linhas[0][0])

    def test_a_extensao_pg_trgm_esta_instalada(self) -> None:
        """Sem ela o indice e o operador `%` do `SQL_PESQUISAR` nao existem.

        A revisao cria-a com `IF NOT EXISTS` porque o
        `infra/compose/postgres/initdb/01-bases-e-extensoes.sql` tambem a cria —
        e sem a guarda a revisao falhava com `42710` em toda a base que o compose
        tenha preparado.
        """
        linhas = self.consultar(
            "SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"
        )
        self.assertEqual(linhas, [("pg_trgm",)])

    def test_o_indice_parcial_da_cotacao_viva_e_o_esperado(self) -> None:
        linhas = self.consultar(
            "SELECT indexdef FROM pg_indexes "
            " WHERE schemaname = 'platform' AND indexname = 'price_quotes_vivas_idx'"
        )
        self.assertEqual(len(linhas), 1)
        self.assertIn("WHERE (estado = 'emitida'::text)", linhas[0][0])


class TestOsPrivilegios(ComOfertas):
    def test_a_aplicacao_escreve_as_duas_e_nao_apaga_nenhuma(self) -> None:
        for tabela in ("offer_terms", "price_quotes"):
            for privilegio, esperado in (
                ("SELECT", True),
                ("INSERT", True),
                ("DELETE", False),
            ):
                with self.subTest(tabela=tabela, privilegio=privilegio):
                    linhas = self.consultar(
                        "SELECT has_table_privilege('kamba_app', %s, %s)",
                        (f"platform.{tabela}", privilegio),
                    )
                    self.assertEqual(linhas[0][0], esperado)

    def test_o_update_e_por_coluna_nas_duas(self) -> None:
        """Nenhuma das duas da `UPDATE` de tabela inteira ao `kamba_app`.

        Na cotacao e so o `estado`: mudar o `preco_total_minor`, o `qty`, o
        `sku` ou o `valida_ate` de uma emitida era reescrever o que o dono cotou
        depois de o cliente o ter visto.

        Na oferta sao dez, e ficam de fora a chave (`tenant_id`, `sku`), a
        `currency` (dominio de um valor), o `criado_at` (historia), o
        `categoria_restrita` (e do *screening* do KAM-049, e a aplicacao a
        escrever desbloqueava a publicacao que ele existe para travar) e o
        `medusa_variant_id` (e do Registo).

        **A primeira versao da `0028` dava `UPDATE` de tabela inteira na
        oferta**, e a assimetria com a cotacao ao lado foi um achado da revisao
        adversarial: o argumento que restringia uma aplicava-se a outra, e so uma
        o tinha escrito. Este caso percorre as duas **nos dois sentidos**.
        """
        permitidas = {
            "price_quotes": {"estado"},
            "offer_terms": {
                "nome",
                "preco_tipo",
                "preco_minor",
                "preco_atualizado_at",
                "preco_valido_ate",
                "stock_modo",
                "stock_verificado_at",
                "estado",
                "atualizado_at",
                "deleted_at",
                # KAM-045: a revisao `0033` acrescenta `GRANT UPDATE` nesta e
                # **so** nesta das duas colunas que cria. A `stock_quantidade`
                # fica de fora de proposito: nada a escreve ainda, e conceder um
                # privilegio que ninguem usa escreve no catalogo uma permissao
                # que nao existe — a mesma razao pela qual a `0030` nao deu
                # `UPDATE` ao `kamba_batch` no `order_state_log`.
                "stock_reservada",
            },
        }
        todas = {
            "price_quotes": (
                "id",
                "tenant_id",
                "contact_id",
                "sku",
                "qty",
                "preco_total_minor",
                "currency",
                "valida_ate",
                "estado",
                "emitida_por",
                "criado_at",
            ),
            "offer_terms": (
                "tenant_id",
                "sku",
                "nome",
                "medusa_variant_id",
                "preco_tipo",
                "preco_minor",
                "currency",
                "preco_atualizado_at",
                "preco_valido_ate",
                "stock_modo",
                "stock_verificado_at",
                "estado",
                "categoria_restrita",
                # KAM-045: as duas colunas de quantidade da revisao `0033`, que
                # sao a autoridade de stock que o `OUT_OF_STOCK` esperava.
                "stock_quantidade",
                "stock_reservada",
                "criado_at",
                "atualizado_at",
                "deleted_at",
            ),
        }
        for tabela, colunas in todas.items():
            # **O inventario desta lista confronta-se com o catalogo**, senao uma
            # coluna nova entrava sem ninguem decidir se a aplicacao a escreve.
            no_catalogo = {
                str(linha[0])
                for linha in self.consultar(
                    "SELECT column_name FROM information_schema.columns "
                    " WHERE table_schema = 'platform' AND table_name = %s",
                    (tabela,),
                )
            }
            self.assertEqual(set(colunas), no_catalogo, tabela)
            for coluna in colunas:
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    linhas = self.consultar(
                        "SELECT has_column_privilege('kamba_app', %s, %s, 'UPDATE')",
                        (f"platform.{tabela}", coluna),
                    )
                    self.assertEqual(
                        linhas[0][0], coluna in permitidas[tabela]
                    )

    def test_nenhuma_das_duas_da_update_de_tabela_inteira(self) -> None:
        """O `has_table_privilege` so ve concessoes de tabela — e nao ha.

        Sem este caso, um `GRANT UPDATE ON platform.offer_terms` acrescentado
        por distraccao passava: ele daria `has_column_privilege` verdadeiro em
        **todas** as colunas, e o caso de cima ficava vermelho — mas com a
        mensagem a apontar para a coluna errada em vez de para o `GRANT`.
        """
        for tabela in ("offer_terms", "price_quotes"):
            with self.subTest(tabela=tabela):
                linhas = self.consultar(
                    "SELECT has_table_privilege('kamba_app', %s, 'UPDATE')",
                    (f"platform.{tabela}",),
                )
                self.assertEqual(linhas[0][0], False)

    def test_o_audit_append_e_executavel_pela_aplicacao_e_a_tabela_nao_e_legivel(
        self,
    ) -> None:
        """A assimetria desenhada pelo KAM-012, de que este ticket passa a
        depender: `EXECUTE` na porta, **sem** `SELECT` na tabela."""
        linhas = self.consultar(
            "SELECT has_function_privilege('kamba_app', "
            "'platform.audit_append(uuid, text, text, text, text, text, text, "
            "bytea)', 'EXECUTE')"
        )
        self.assertEqual(linhas[0][0], True)
        linhas = self.consultar(
            "SELECT has_table_privilege('kamba_app', 'platform.audit_log', 'SELECT')"
        )
        self.assertEqual(linhas[0][0], False)


class TestOContratoComOModulo(ComOfertas):
    """As consultas do modulo **correm**, e a lista cobre-as nos dois sentidos.

    Sem isto, uma consulta nova entrava sem ninguem a exercitar — e foi assim
    que o `SQL_GRELHA` do KAM-047 chegou com um defeito que nenhuma bateria
    tocava. O caso corre cada uma contra a base com argumentos plausiveis: o que
    prova nao e o resultado, e que o PostgreSQL **aceita o texto** — um erro de
    sintaxe ou um nome de coluna errado falhava aqui, e nao no primeiro pedido
    real.
    """

    def test_a_lista_de_exercitadas_e_o_modulo_dizem_o_mesmo(self) -> None:
        do_modulo = {
            nome
            for nome in dir(consultas)
            if nome.startswith("SQL_") and not nome.startswith("SQL_STATE")
        }
        self.assertEqual(
            do_modulo,
            set(EXERCITADAS),
            "ha uma consulta do modulo que ninguem exercita, ou um nome na "
            "lista que o modulo nao tem",
        )

    def test_cada_consulta_do_modulo_corre_contra_a_base(self) -> None:
        tenant = self.criar_tenant()
        contacto = self.criar_contacto(tenant)
        self.criar_oferta(tenant)
        cotacao = self.criar_cotacao(tenant, contacto)
        cursor = self.cursor_app(tenant)
        agora = daqui_a()

        plausiveis = {
            "SQL_TERMOS": (tenant, SKU_PARTILHADO),
            "SQL_TERMOS_PARA_ESCRITA": (tenant, SKU_PARTILHADO),
            # Oito e nao sete: o `preco_atualizado_at` passou a vir como
            # argumento (`$8`) em vez de ser `now()` na instrucao. A razao esta
            # na consulta: era reescrito numa repeticao byte-a-byte, e a coluna
            # que significa «quando o preco foi posto» passava a significar
            # «quando alguem reescreveu o rascunho».
            "SQL_ACTUALIZAR_TERMOS": (
                tenant,
                SKU_PARTILHADO,
                "arroz novo",
                "a_partir_de",
                PRECO,
                None,
                "indicativo",
                agora,
            ),
            "SQL_PUBLICAR": (tenant, SKU_PARTILHADO),
            "SQL_AJUSTAR_STOCK": (tenant, SKU_PARTILHADO, "garantido"),
            "SQL_PESQUISAR": (tenant, "arroz", "arroz", 5),
            # KAM-099. A versao e um texto que nao casa: o caso prova que o
            # texto corre, e o `test_painel` mede o CAS.
            "SQL_LISTAR_OFERTAS": (tenant, 5),
            "SQL_OFERTA_DO_PAINEL": (tenant, SKU_PARTILHADO),
            "SQL_ALTERAR_OFERTA": (tenant, SKU_PARTILHADO, "fixo", PRECO, "2026-01-01T00:00:00.000001Z", True),
            # Cinco e nao quatro: o `contact_id = $2` entrou com o KAM-179.
            # A cotacao e **por contacto**, por decisao do fundador de
            # 2026-11-04: sem o predicado, dentro do mesmo tenant o contacto X
            # recebia o total negociado para Y. Ver o
            # `test_x_nao_le_a_cotacao_de_y_dentro_do_mesmo_tenant`, que e quem
            # mede a propriedade — este caso so prova que o texto corre.
            "SQL_COTACAO_VALIDA": (tenant, contacto, SKU_PARTILHADO, 10, agora),
            # Quatro e nao dois. O `valida_ate > $4` entrou com um achado da
            # revisao adversarial — «cotacao expirada nao e aceite» e o
            # criterio 6, e filtrar so por `estado = 'emitida'` nao bastava,
            # porque a expiracao e por `valida_ate` e um estado so muda
            # quando alguem o muda. O `contact_id = $2` entrou com o KAM-179,
            # e aqui fecha a escalada de leitura para escrita: com o `id` que a
            # leitura devolvia, X punha a cotacao de Y a `aceite`.
            "SQL_ACEITAR_COTACAO": (tenant, contacto, cotacao, agora),
            "SQL_AUDITAR": (
                tenant,
                "owner",
                "o-dono",
                "price.update",
                "offer_terms",
                SKU_PARTILHADO,
                None,
                "antes=1,depois=2",
            ),
            "SQL_EMITIR": (
                "catalog.product_changed",
                1,
                tenant,
                "product",
                SKU_PARTILHADO,
                '{"sku": "arroz-5kg", "estado": "publicado"}',
                "P0",
                ["transacao"],
            ),
        }
        self.assertEqual(set(plausiveis), set(EXERCITADAS))

        for nome in EXERCITADAS:
            consulta = getattr(consultas, nome)
            with self.subTest(consulta=nome):
                cursor.execute(consulta.sql, consulta.args(*plausiveis[nome]))
        cursor.connection.rollback()

    def test_a_pesquisa_por_trigramas_encontra_com_erro_de_acento(self) -> None:
        """O que um `LIKE` nao fazia, e a razao de o indice ser de trigramas."""
        tenant = self.criar_tenant()
        self.criar_oferta(tenant, sku="sabao-azul", nome="Sabão Azul em Barra")
        cursor = self.cursor_app(tenant)
        consulta = consultas.SQL_PESQUISAR
        cursor.execute(consulta.sql, consulta.args(tenant, "sabao azul", "sabao azul", 5))
        encontrados = [str(linha[0]) for linha in cursor.fetchall()]
        self.assertEqual(encontrados, ["sabao-azul"])

    def test_a_pesquisa_nao_devolve_rascunhos(self) -> None:
        """Um rascunho citado era um preco a frente de um cliente sem o dono o
        ter publicado."""
        tenant = self.criar_tenant()
        self.criar_oferta(tenant, sku="r1", nome="Arroz Agulha", estado="rascunho")
        self.criar_oferta(tenant, sku="r2", nome="Arroz Carolino", estado="publicado")
        cursor = self.cursor_app(tenant)
        consulta = consultas.SQL_PESQUISAR
        cursor.execute(consulta.sql, consulta.args(tenant, "arroz", "arroz", 5))
        self.assertEqual([str(l[0]) for l in cursor.fetchall()], ["r2"])

    def test_a_pesquisa_respeita_o_tecto_de_cinco(self) -> None:
        tenant = self.criar_tenant()
        for i in range(8):
            self.criar_oferta(tenant, sku=f"arroz-{i}", nome=f"Arroz tipo {i}")
        cursor = self.cursor_app(tenant)
        consulta = consultas.SQL_PESQUISAR
        cursor.execute(consulta.sql, consulta.args(tenant, "arroz", "arroz", 5))
        self.assertEqual(len(cursor.fetchall()), 5)
