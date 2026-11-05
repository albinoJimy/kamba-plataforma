"""Gate 8: um caso negativo por `CHECK` e por `UNIQUE`, e os positivos todos.

Criterios de aceitacao 2, 3, 4 e 8 do KAM-003. Os inserts correm como
`kamba_app`, que e quem os fara em producao: um teste que so passasse como
superutilizador nao provava o privilegio.

Para os dominios fechados verificam-se as duas metades de «aceita exactamente»:
cada valor esperado entra, **e** o conjunto que o catalogo regista e igual ao
esperado. Sem a segunda metade, um sexto estado acrescentado por engano passava.
"""

from __future__ import annotations

import datetime
import re
import uuid

from tests import factories
from tests.base import (
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_NOT_NULL,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
)

ESTADOS_DO_TENANT = {"onboarding", "ativo", "restrito", "suspenso", "encerrado"}
ESTADOS_DO_CANAL = {"pendente", "ativo", "restrito", "desligado", "suspenso", "encerrado"}
TIPOS_DE_TENANT = {"pme", "courier", "reseller", "agent", "platform"}
ORIGENS = {"pme", "plataforma"}
MODOS = {"coexistencia", "cloud_only"}


class _ComApp(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("app")
        self.cursor = self.conexao.cursor()

    def tenant_rejeitado(self, esperado: str, **campos) -> None:
        """Um `INSERT` em `tenants` que tem de falhar, e pela razao esperada.

        Pre-aloca o `id` e define o contexto antes, como o onboarding faz: sem
        isso a RLS do KAM-004 recusava a linha no `WITH CHECK` (42501) antes de
        o `CHECK` ou o `UNIQUE` em teste chegarem a ser avaliados, e o teste
        passava a medir a politica em vez da restricao. Um campo a `None`
        fica fora do `INSERT` (para testar `NOT NULL`).
        """
        valores = {"id": str(uuid.uuid4()), "tipo": "pme", "nome": "x"}
        valores.update(campos)
        valores = {k: v for k, v in valores.items() if v is not None}
        factories.contexto(self.cursor, valores["id"])
        self.assertErroSql(
            esperado,
            self.cursor,
            f"INSERT INTO platform.tenants ({', '.join(valores)}) "
            f"VALUES ({', '.join(['%s'] * len(valores))})",
            tuple(valores.values()),
        )

    def dominio_no_catalogo(self, restricao: str) -> set[str]:
        """Os literais de um `CHECK (coluna IN (...))`, lidos do catalogo."""
        linhas = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            (restricao,),
        )
        self.assertEqual(len(linhas), 1, f"restricao {restricao} nao existe")
        return set(re.findall(r"'([^']+)'", linhas[0][0]))


class TestEstadoDoTenant(_ComApp):
    """CA 2: `tenants.estado` aceita exactamente cinco valores."""

    def test_aceita_cada_um_dos_cinco(self) -> None:
        for estado in sorted(ESTADOS_DO_TENANT):
            with self.subTest(estado=estado):
                factories.tenant(self.cursor, estado=estado)

    def test_o_catalogo_tem_exactamente_os_cinco(self) -> None:
        self.assertEqual(self.dominio_no_catalogo("tenants_estado_ck"), ESTADOS_DO_TENANT)

    def test_rejeita_qualquer_outro(self) -> None:
        # `pausado` e `revogado` sao os estados do DDL antigo do doc 03.
        for estado in ("pausado", "revogado", "ATIVO", "activo", "", "pendente"):
            with self.subTest(estado=estado):
                self.tenant_rejeitado(VIOLACAO_DE_CHECK, estado=estado)

    def test_a_omissao_e_onboarding(self) -> None:
        identificador = factories.tenant(self.cursor)
        self.cursor.execute(
            "SELECT estado FROM platform.tenants WHERE id = %s", (identificador,)
        )
        self.assertEqual(self.cursor.fetchone()[0], "onboarding")


class TestTipoDoTenant(_ComApp):
    def test_dominio(self) -> None:
        self.assertEqual(self.dominio_no_catalogo("tenants_tipo_ck"), TIPOS_DE_TENANT)
        for tipo in sorted(TIPOS_DE_TENANT):
            with self.subTest(tipo=tipo):
                factories.tenant(self.cursor, tipo=tipo)

    def test_rejeita_outro(self) -> None:
        self.tenant_rejeitado(VIOLACAO_DE_CHECK, tipo="plataforma")

    def test_tipo_e_nome_sao_obrigatorios(self) -> None:
        self.tenant_rejeitado(VIOLACAO_DE_NOT_NULL, tipo=None)
        self.tenant_rejeitado(VIOLACAO_DE_NOT_NULL, nome=None)


class TestNif(_ComApp):
    """CA 4: `tenants_nif_uq` e unico parcial."""

    def test_segundo_tenant_com_o_mesmo_nif_e_rejeitado(self) -> None:
        nif = f"NIF-TESTE-{uuid.uuid4().hex[:10]}"
        factories.tenant(self.cursor, nif=nif)
        self.tenant_rejeitado(VIOLACAO_DE_UNICIDADE, nome="outro", nif=nif)

    def test_dois_tenants_sem_nif_coexistem(self) -> None:
        factories.tenant(self.cursor, nif=None)
        factories.tenant(self.cursor, nif=None)

    def test_o_nif_de_um_tenant_apagado_fica_livre(self) -> None:
        """A metade «e nao apagado» do indice parcial."""
        nif = f"NIF-TESTE-{uuid.uuid4().hex[:10]}"
        primeiro = factories.tenant(self.cursor, nif=nif)
        self.cursor.execute(
            "UPDATE platform.tenants SET deleted_at = now() WHERE id = %s", (primeiro,)
        )
        factories.tenant(self.cursor, nif=nif)

    def test_o_indice_e_o_que_o_criterio_nomeia(self) -> None:
        linhas = self.consultar(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'platform' "
            "AND indexname = 'tenants_nif_uq'"
        )
        self.assertEqual(len(linhas), 1)
        definicao = linhas[0][0]
        self.assertIn("UNIQUE", definicao)
        self.assertIn("nif IS NOT NULL", definicao)
        self.assertIn("deleted_at IS NULL", definicao)


class TestCanal(_ComApp):
    """CA 3: estados do canal e unicidade do `phone_number_id`."""

    def setUp(self) -> None:
        super().setUp()
        self.tenant = factories.tenant(self.cursor)

    def test_aceita_cada_um_dos_seis_estados(self) -> None:
        for estado in sorted(ESTADOS_DO_CANAL):
            with self.subTest(estado=estado):
                factories.canal(self.cursor, self.tenant, estado=estado)

    def test_o_catalogo_tem_exactamente_os_seis(self) -> None:
        self.assertEqual(
            self.dominio_no_catalogo("tenant_channels_estado_ck"), ESTADOS_DO_CANAL
        )

    def test_o_indice_por_tenant_comeca_pelo_tenant(self) -> None:
        """A ordem das colunas **e** a razao de este indice existir.

        `(tenant_id, estado)` e nao `(estado, tenant_id)`: o `tenant_id` e o
        predicado que a RLS do KAM-004 acrescenta a **todas** as consultas desta
        tabela, e e por ele que o indice serve. Trocada a ordem, o indice
        continua a existir, com o mesmo nome e o mesmo numero de colunas, e
        continua a servir uma consulta por `estado` — nada na bateria lia a
        **definicao**, e a mutacao `ordem do indice trocada` sobreviveu a noite
        de 2026-10-26.

        O modelo e o `test_os_dois_indices_existem_e_o_primeiro_comeca_pelo_tenant`
        do `test_coexistencia_schema.py`, que ja faz isto para o indice gemeo da
        `0018`. Faltava o irmao para a `0001`.
        """
        linhas = self.consultar(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'platform' "
            "AND indexname = 'tenant_channels_tenant_estado_idx'"
        )
        # O canario: sem esta linha, um indice que deixasse de existir dava uma
        # lista vazia e o `assertIn` nunca corria.
        self.assertEqual(len(linhas), 1, "o indice por tenant desapareceu")
        self.assertIn("(tenant_id, estado)", linhas[0][0])

    def test_rejeita_os_estados_do_ddl_antigo(self) -> None:
        for estado in ("pausado", "revogado", "onboarding"):
            with self.subTest(estado=estado):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    self.cursor,
                    "INSERT INTO platform.tenant_channels "
                    "(tenant_id, waba_id, phone_number_id, channel_mode, vertical, "
                    " token_ref, estado) VALUES (%s, 'w', %s, 'coexistencia', "
                    " 'vendedor', 'ref', %s)",
                    (self.tenant, f"pnid-{uuid.uuid4().hex}", estado),
                )

    def test_a_omissao_e_pendente(self) -> None:
        identificador = factories.canal(self.cursor, self.tenant)
        self.cursor.execute(
            "SELECT estado, origem, free_tier_used FROM platform.tenant_channels "
            "WHERE id = %s",
            (identificador,),
        )
        self.assertEqual(tuple(self.cursor.fetchone()), ("pendente", "pme", 0))

    def test_o_mesmo_phone_number_id_noutro_tenant_falha(self) -> None:
        """O CHR resolve o tenant por este valor: dois donos seria fuga entre tenants."""
        partilhado = f"pnid-teste-{uuid.uuid4().hex[:12]}"
        factories.canal(self.cursor, self.tenant, phone_number_id=partilhado)
        outro = factories.tenant(self.cursor)
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE,
            self.cursor,
            "INSERT INTO platform.tenant_channels "
            "(tenant_id, waba_id, phone_number_id, channel_mode, vertical, token_ref) "
            "VALUES (%s, 'w', %s, 'cloud_only', 'servicos', 'ref')",
            (outro, partilhado),
        )

    def test_origem_e_modo(self) -> None:
        self.assertEqual(self.dominio_no_catalogo("tenant_channels_origem_ck"), ORIGENS)
        self.assertEqual(
            self.dominio_no_catalogo("tenant_channels_channel_mode_ck"), MODOS
        )
        for coluna, valor in (("origem", "agregador"), ("channel_mode", "hibrido")):
            with self.subTest(coluna=coluna):
                campos = {"origem": "pme", "channel_mode": "coexistencia"}
                campos[coluna] = valor
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    self.cursor,
                    "INSERT INTO platform.tenant_channels "
                    "(tenant_id, waba_id, phone_number_id, channel_mode, vertical, "
                    " token_ref, origem) VALUES (%s, 'w', %s, %s, 'vendedor', 'ref', %s)",
                    (self.tenant, f"pnid-{uuid.uuid4().hex}",
                     campos["channel_mode"], campos["origem"]),
                )

    def test_canal_sem_tenant_existente_falha(self) -> None:
        inexistente = str(uuid.uuid4())
        factories.contexto(self.cursor, inexistente)
        self.assertErroSql(
            VIOLACAO_DE_FK,
            self.cursor,
            "INSERT INTO platform.tenant_channels "
            "(tenant_id, waba_id, phone_number_id, channel_mode, vertical, token_ref) "
            "VALUES (%s, 'w', %s, 'coexistencia', 'vendedor', 'ref')",
            (inexistente, f"pnid-{uuid.uuid4().hex}"),
        )

    def test_token_ref_e_obrigatorio(self) -> None:
        self.assertErroSql(
            VIOLACAO_DE_NOT_NULL,
            self.cursor,
            "INSERT INTO platform.tenant_channels "
            "(tenant_id, waba_id, phone_number_id, channel_mode, vertical) "
            "VALUES (%s, 'w', %s, 'coexistencia', 'vendedor')",
            (self.tenant, f"pnid-{uuid.uuid4().hex}"),
        )


class TestEntitlements(ComBase):
    """As restricoes de `entitlements`, semeadas pelo papel que a escreve.

    **Corria como `kamba_app` e deixou de poder.** A revisao `0007` retirou-lhe
    o `INSERT` nesta tabela (KAM-009, emenda 1.18 do dicionario): com
    `WITH CHECK (tenant_id = app.tenant_id)` a politica autorizava a linha —
    e dele — pelo que um tenant criava o proprio entitlement com o tecto que
    quisesse. Quem provisiona e o `kamba_batch`.

    O que estes testes medem e um `CHECK`, um `UNIQUE` e uma chave
    estrangeira, e nao um privilegio: com o papel errado nem chegavam a
    avalia-los — o `test_entitlement_sem_tenant_falha` esperava `23503` e
    recebia `42501`, isto e, media a porta em vez da restricao. Passam a
    correr com `kamba_batch`, que e quem insere. **O privilegio que a
    aplicacao ja nao tem prova-se noutro sitio**, e em dois:
    `tests/test_privilegios.py::TestOQueAAppNaoConsegue` e
    `tests_ten/test_escalada.py::TestNaoCriaOProprioEntitlement`.

    O tenant nasce na **mesma ligacao**: nada aqui confirma, e um tenant
    escrito noutra transaccao era invisivel a esta.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("batch")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)

    def test_um_por_tenant_e_modulo(self) -> None:
        factories.entitlement(self.cursor, self.tenant, "catalogo")
        factories.entitlement(self.cursor, self.tenant, "social")
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE,
            self.cursor,
            "INSERT INTO platform.entitlements (tenant_id, modulo) VALUES (%s, 'catalogo')",
            (self.tenant,),
        )

    def test_omissoes(self) -> None:
        factories.entitlement(self.cursor, self.tenant, "catalogo")
        self.cursor.execute(
            "SELECT limites::text, ativo FROM platform.entitlements WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(tuple(self.cursor.fetchone()), ("{}", True))

    def test_limites_guarda_inteiros_em_unidade_menor(self) -> None:
        """As chaves sao do dicionario §3.2; o valor e inteiro, nunca decimal."""
        self.cursor.execute(
            "INSERT INTO platform.entitlements (tenant_id, modulo, limites) "
            "VALUES (%s, 'pagamentos', %s::jsonb)",
            (self.tenant, '{"msgs_ai_mes": 100, "manual_max_minor": 5000000}'),
        )
        self.cursor.execute(
            "SELECT jsonb_typeof(limites->'manual_max_minor'), "
            "(limites->>'manual_max_minor')::bigint "
            "FROM platform.entitlements WHERE tenant_id = %s AND modulo = 'pagamentos'",
            (self.tenant,),
        )
        self.assertEqual(tuple(self.cursor.fetchone()), ("number", 5000000))

    def test_entitlement_sem_tenant_falha(self) -> None:
        inexistente = str(uuid.uuid4())
        factories.contexto(self.cursor, inexistente)
        self.assertErroSql(
            VIOLACAO_DE_FK,
            self.cursor,
            "INSERT INTO platform.entitlements (tenant_id, modulo) VALUES (%s, 'x')",
            (inexistente,),
        )


class TestFormas(_ComApp):
    """Os CHECK de forma que a revisao adversarial mostrou em falta.

    Tudo isto era aceite na primeira versao: dois tenants «sem NIF» que gravassem
    a cadeia vazia colidiam no indice unico, o mesmo NIF com um espaco criava um
    segundo tenant, e `limites` aceitava um vector — que rebentaria o KAM-009 a
    ler.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = factories.tenant(self.cursor)

    def canal_com(self, coluna: str, valor) -> tuple[str, tuple]:
        campos = {
            "tenant_id": self.tenant,
            "waba_id": "waba-teste",
            "phone_number_id": f"pnid-{uuid.uuid4().hex}",
            "channel_mode": "coexistencia",
            "vertical": "vendedor",
            "token_ref": "ref-de-teste",
        }
        campos[coluna] = valor
        return (
            f"INSERT INTO platform.tenant_channels ({', '.join(campos)}) "
            f"VALUES ({', '.join(['%s'] * len(campos))})",
            tuple(campos.values()),
        )

    def test_nif_vazio_ou_com_espacos_e_rejeitado(self) -> None:
        for nif in ("", " 5000123456", "5000123456 ", "   "):
            with self.subTest(nif=nif):
                self.tenant_rejeitado(VIOLACAO_DE_CHECK, nif=nif)

    def test_nome_em_branco_e_rejeitado(self) -> None:
        for nome in ("", "   "):
            with self.subTest(nome=nome):
                self.tenant_rejeitado(VIOLACAO_DE_CHECK, nome=nome)

    def test_a_vertical_tem_forma_de_chave(self) -> None:
        """Minusculas e snake_case (dicionario §2). O dominio e do registo, nao do DDL.

        A guarda do ADR-011 compara a vertical com uma lista; sem este CHECK,
        `Assistente` ou ` assistente` entravam na coluna com uma forma que nenhuma
        comparacao previa.
        """
        for vertical in ("Assistente", " assistente", "assistente ", "ASSISTENTE", "",
                         "com espaco", "9inicio", "com-hifen"):
            with self.subTest(vertical=vertical):
                sql, parametros = self.canal_com("vertical", vertical)
                self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, sql, parametros)
        for vertical in ("vendedor", "servicos", "assistente", "catalogo_v2"):
            with self.subTest(vertical=vertical):
                sql, parametros = self.canal_com("vertical", vertical)
                self.cursor.execute(sql, parametros)

    def test_identificadores_do_canal_nao_sao_vazios_nem_tem_espacos_a_volta(self) -> None:
        for coluna, valor in (("waba_id", ""), ("waba_id", " w"), ("phone_number_id", ""),
                              ("phone_number_id", " p1"), ("phone_number_id", "p1 "),
                              ("token_ref", ""), ("token_ref", "   ")):
            with self.subTest(coluna=coluna, valor=valor):
                sql, parametros = self.canal_com(coluna, valor)
                self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, sql, parametros)

    def test_free_tier_used_nao_e_negativo(self) -> None:
        sql, parametros = self.canal_com("free_tier_used", -1)
        self.assertErroSql(VIOLACAO_DE_CHECK, self.cursor, sql, parametros)

    def entitlements_pelo_batch(self):
        """Cursor de `kamba_batch` com um tenant seu, e porque faz falta.

        A aplicacao deixou de ter `INSERT` em `entitlements` com a revisao
        `0007` (ver a docstring de `TestEntitlements`), e um `CHECK` medido
        com o papel errado nao chega a ser avaliado: o `42501` vem primeiro.
        O tenant nasce na mesma ligacao porque nada aqui confirma.
        """
        cursor = self.ligar("batch").cursor()
        return cursor, factories.tenant(cursor)

    def test_limites_tem_de_ser_um_objecto(self) -> None:
        cursor, tenant = self.entitlements_pelo_batch()
        for limites in ("[]", '"x"', "null", "3"):
            with self.subTest(limites=limites):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    cursor,
                    "INSERT INTO platform.entitlements (tenant_id, modulo, limites) "
                    "VALUES (%s, 'catalogo', %s::jsonb)",
                    (tenant, limites),
                )

    def test_o_modulo_tem_forma_de_chave(self) -> None:
        cursor, tenant = self.entitlements_pelo_batch()
        for modulo in ("", "MODULO QUALQUER", "Catalogo", "com-hifen"):
            with self.subTest(modulo=modulo):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK,
                    cursor,
                    "INSERT INTO platform.entitlements (tenant_id, modulo) VALUES (%s, %s)",
                    (tenant, modulo),
                )

    def test_apagar_um_tenant_com_canais_falha(self) -> None:
        """Como `kamba_batch`, que e quem pode apagar: a FK nao tem CASCADE."""
        cursor = self.ligar("batch").cursor()
        tenant = factories.tenant(cursor)
        factories.canal(cursor, tenant)
        self.assertErroSql(
            VIOLACAO_DE_FK,
            cursor,
            "DELETE FROM platform.tenants WHERE id = %s",
            (tenant,),
        )


class TestIdentificadoresETempos(_ComApp):
    """CA 8: `uuid` gerado, `timestamptz` em UTC, fuso por omissao `Africa/Luanda`."""

    def test_o_id_e_um_uuid_gerado(self) -> None:
        primeiro = factories.tenant(self.cursor)
        segundo = factories.tenant(self.cursor)
        self.assertNotEqual(primeiro, segundo)
        self.assertEqual(uuid.UUID(primeiro).version, 4)

    def test_o_fuso_por_omissao_e_luanda(self) -> None:
        identificador = factories.tenant(self.cursor)
        self.cursor.execute(
            "SELECT fuso_horario FROM platform.tenants WHERE id = %s", (identificador,)
        )
        self.assertEqual(self.cursor.fetchone()[0], "Africa/Luanda")

    def test_criado_at_e_um_instante_com_fuso(self) -> None:
        identificador = factories.tenant(self.cursor)
        self.cursor.execute(
            "SELECT criado_at FROM platform.tenants WHERE id = %s", (identificador,)
        )
        instante = self.cursor.fetchone()[0]
        self.assertIsNotNone(instante.tzinfo, "criado_at chegou sem fuso")
        agora = datetime.datetime.now(datetime.timezone.utc)
        self.assertLess(abs((agora - instante).total_seconds()), 300)

    def test_um_instante_guarda_se_em_utc_venha_de_onde_vier(self) -> None:
        """Luanda e UTC+1: 13:00 em Luanda sao 12:00 UTC, e e isso que se le."""
        identificador = factories.tenant(self.cursor)
        self.cursor.execute(
            "UPDATE platform.tenants SET verificado_at = "
            "'2026-10-11 13:00:00 Africa/Luanda'::timestamptz WHERE id = %s",
            (identificador,),
        )
        self.cursor.execute(
            "SELECT (verificado_at AT TIME ZONE 'UTC')::text FROM platform.tenants "
            "WHERE id = %s",
            (identificador,),
        )
        self.assertEqual(self.cursor.fetchone()[0], "2026-10-11 12:00:00")


#: Os oito passos da saga, pela ordem do `PASSOS` de
#: `packages/core-ts/src/provisioning/contrato.ts`. O dicionario secao 3.47
#: fixa-os.
PASSOS_DA_SAGA = {
    "tenant_e_caso", "chave_llm", "canal_comercio", "conta_atendimento",
    "entitlements", "espera_es", "inbox_e_rota", "teste_ponta_a_ponta",
}
ESTADOS_DE_PASSO = {"em_curso", "concluido", "falhado", "escalado", "compensado"}
ESPERAS = {"aguarda_es", "aguarda_catalogo", "aguarda_teste"}

#: Sentinela que distingue as duas coisas que `None` confundiria: **fora** do
#: `INSERT` (para medir o `NOT NULL`) e **dentro** com valor nulo (para medir
#: que um `CHECK` sobre coluna anulavel deixa passar o nulo).
NULO = object()


class TestProvisioningStep(_ComApp):
    """Os oito `CHECK` e a chave primaria da revisao `0034` (KAM-091).

    **Isto existe porque a revisao adversarial mediu que nao existia.** O
    `test_downgrade_0034.py` e o `test_inventario.py` afirmam as restricoes pelo
    **nome** (`conname`), e um nome nao e um predicado: tirem-se as ancoras ao
    `provisioning_step_error_code_ck` — de `'^[A-Za-z][A-Za-z0-9_]{2,63}$'` para
    `'[A-Za-z][A-Za-z0-9_]{2,63}'` — e as duas superficies continuam verdes,
    enquanto a coluna passa a aceitar uma chave do LiteLLM que tenha um pedaco
    `snake_case` la dentro. Que e **a fuga** que esta revisao existe para fechar.

    Os `INSERT` correm como `kamba_app`, que e quem os fara em producao: a saga
    corre sob o `app.tenant_id` do caso (criterio 6 dos *Testes Requeridos* do
    bloco). Um ensaio que so passasse como superutilizador nao provava o
    privilegio — e, pior, com `FORCE` nem chegava a avaliar o `CHECK`: a
    politica recusava a linha no `WITH CHECK` (42501) primeiro.

    **Nao ha `tenants` semeada**, e isso nao e atalho: esta tabela **nao tem
    FK** para `platform.tenants` porque e o passo 1 da saga que escreve essa
    linha. Um `tenant_id` que nao existe em `tenants` e um estado legitimo aqui.
    """

    def setUp(self) -> None:
        super().setUp()
        self.tenant = str(uuid.uuid4())
        factories.contexto(self.cursor, self.tenant)

    # -------------------------------------------------------------- auxiliares

    def _campos(self, **mudancas) -> dict:
        """A linha valida minima, com as mudancas pedidas por cima.

        Um campo a `None` **fica fora** do `INSERT`, para se poder testar o
        `NOT NULL`; um campo a `NULO` entra com o valor nulo.
        """
        valores = {
            "onboarding_id": str(uuid.uuid4()),
            "tenant_id": self.tenant,
            "step": "tenant_e_caso",
            "status": "em_curso",
            "attempt": 1,
        }
        valores.update(mudancas)
        return {k: v for k, v in valores.items() if v is not None}

    def _inserir(self, **mudancas) -> None:
        valores = self._campos(**mudancas)
        valores = {k: (None if v is NULO else v) for k, v in valores.items()}
        self.cursor.execute(
            f"INSERT INTO platform.provisioning_step ({', '.join(valores)}) "
            f"VALUES ({', '.join(['%s'] * len(valores))})",
            tuple(valores.values()),
        )

    def _rejeitado(self, esperado: str, **mudancas) -> None:
        valores = self._campos(**mudancas)
        valores = {k: (None if v is NULO else v) for k, v in valores.items()}
        self.assertErroSql(
            esperado,
            self.cursor,
            f"INSERT INTO platform.provisioning_step ({', '.join(valores)}) "
            f"VALUES ({', '.join(['%s'] * len(valores))})",
            tuple(valores.values()),
        )

    # ------------------------------------------------- os tres dominios fechados

    def test_os_oito_passos_entram_e_sao_exactamente_estes(self) -> None:
        """As duas metades de «aceita exactamente», como o resto do ficheiro."""
        for passo in sorted(PASSOS_DA_SAGA):
            with self.subTest(passo=passo):
                self._inserir(step=passo)
        self.assertEqual(
            self.dominio_no_catalogo("provisioning_step_step_ck"),
            PASSOS_DA_SAGA,
            "um nono passo acrescentado por engano passava sem esta metade",
        )

    def test_um_passo_que_o_contrato_nao_tem_e_recusado(self) -> None:
        # `chatwoot` e o nome do **fornecedor**, e o contrato recusa-o de
        # proposito: o passo chama-se `conta_atendimento` porque o fornecedor e
        # uma decisao aberta.
        self._rejeitado(VIOLACAO_DE_CHECK, step="chatwoot")

    def test_os_cinco_estados_entram_e_sao_exactamente_estes(self) -> None:
        for estado in sorted(ESTADOS_DE_PASSO):
            with self.subTest(estado=estado):
                # Os dois estados de falha exigem codigo (ver abaixo).
                codigo = "erro_opaco" if estado in ("falhado", "escalado") else None
                self._inserir(status=estado, error_code=codigo)
        self.assertEqual(
            self.dominio_no_catalogo("provisioning_step_status_ck"),
            ESTADOS_DE_PASSO,
        )

    def test_running_e_recusado_e_e_o_nome_do_esboco(self) -> None:
        """O `../docs/tecnica/10` secao 5.2 escreve `status: 'running'`.

        Esta e a divida documental 193: o esboco daquele documento usa tres
        formas que esta tabela recusa. O ensaio prende a recusa.
        """
        self._rejeitado(VIOLACAO_DE_CHECK, status="running")

    def test_as_tres_esperas_entram_e_sao_exactamente_estas(self) -> None:
        for espera in sorted(ESPERAS):
            with self.subTest(espera=espera):
                self._inserir(status_de_espera=espera)
        self.assertEqual(
            self.dominio_no_catalogo("provisioning_step_espera_ck"),
            ESPERAS,
            "o dominio e do `marcarEspera` e nao o `onboarding_case.fase`, que "
            "tem seis valores e nao tem o `aguarda_teste`",
        )

    def test_uma_fase_do_caso_nao_serve_de_espera_do_passo(self) -> None:
        """`kyc_pendente` e do `onboarding_case.fase` (secao 3.2), nao desta coluna."""
        self._rejeitado(VIOLACAO_DE_CHECK, status_de_espera="kyc_pendente")

    # ------------------------------------------------- a forma do `error_code`

    def test_um_codigo_bem_formado_entra(self) -> None:
        for codigo in ("erro_opaco", "upstream_timeout", "Erro", "A_1"):
            with self.subTest(codigo=codigo):
                self._inserir(status="falhado", error_code=codigo)

    def test_uma_chave_do_litellm_nao_entra_no_error_code(self) -> None:
        """**A fuga que esta revisao fecha, medida com valores concretos.**

        A revisao adversarial do KAM-091 mostrou que o `erro.name` e escrevivel
        por quem lanca, e punha a chave inteira nesta coluna. O codigo passou a
        devolver `erro_opaco` para o que nao casa a forma; isto prende a mesma
        recusa **na coluna**, que e a terceira superficie que a caixa dos
        segredos nomeia.

        **O terceiro e o quarto casos sao o que mata a mutacao das ancoras.**
        Sem o `^` e o `$`, o `~` casa uma subcadeia: `sk-abc_def_ghi` tem
        `abc_def_ghi` la dentro e passaria, levando a chave inteira para a
        coluna. Com as ancoras, nao passa.
        """
        for codigo in (
            "sk-1234567890abcdef",
            'Error: {"error":"invalid key sk-1234567890abcdef"}',
            "sk-abc_def_ghi",
            "1234567890abcdef_chave",
            "erro com espacos",
            "x",
            "",
        ):
            with self.subTest(codigo=codigo):
                self._rejeitado(
                    VIOLACAO_DE_CHECK, status="falhado", error_code=codigo
                )

    def test_um_codigo_acima_do_tecto_nao_entra(self) -> None:
        """64 caracteres passam, 65 nao: o tecto e `{2,63}` depois do primeiro."""
        self._inserir(status="falhado", error_code="e" + "x" * 63)
        self._rejeitado(
            VIOLACAO_DE_CHECK, status="falhado", error_code="e" + "x" * 64
        )

    # ------------------------------------------------- as duas implicacoes

    def test_uma_falha_terminal_sem_codigo_e_recusada(self) -> None:
        for estado in ("falhado", "escalado"):
            with self.subTest(estado=estado):
                self._rejeitado(VIOLACAO_DE_CHECK, status=estado)

    def test_um_estado_que_nao_e_de_falha_passa_sem_codigo(self) -> None:
        """O controlo positivo da implicacao: ela nao proibe o nulo em geral."""
        for estado in ("em_curso", "concluido", "compensado"):
            with self.subTest(estado=estado):
                self._inserir(status=estado)

    def test_um_passo_concluido_com_erro_e_recusado(self) -> None:
        self._rejeitado(
            VIOLACAO_DE_CHECK, status="concluido", error_code="erro_opaco"
        )

    def test_um_passo_concluido_a_espera_de_alguem_e_recusado(self) -> None:
        """A metade do `status_de_espera`, medida **sozinha**.

        Apagada, a implicacao continuava a recusar o caso do `error_code` e este
        ensaio era o unico a ficar vermelho — que e a razao de ser dois ensaios
        e nao um.
        """
        self._rejeitado(
            VIOLACAO_DE_CHECK, status="concluido", status_de_espera="aguarda_es"
        )

    def test_um_passo_compensado_guarda_o_erro_e_a_espera(self) -> None:
        """O `marcarCompensado` **nao** limpa nada, e nenhum `CHECK` o obriga.

        A referencia externa e o codigo do recurso desfeito sao o que a
        reconciliacao precisa para o reconhecer — sem isto, ela classificava um
        recurso compensado como `externo_em_falta` e voltava a cria-lo.
        """
        self._inserir(
            status="compensado",
            error_code="upstream_down",
            status_de_espera="aguarda_es",
            external_id="conta-de-ensaio-1",
        )

    # ------------------------------------------------- o resto

    def test_um_external_id_vazio_e_recusado_e_o_nulo_nao(self) -> None:
        """Vazio gravava «ha um recurso la fora» sem dizer qual."""
        self._rejeitado(VIOLACAO_DE_CHECK, external_id="")
        self._rejeitado(VIOLACAO_DE_CHECK, external_id="   ")
        # O nulo passa: dois dos oito `ensure` devolvem `null`.
        self._inserir(external_id=NULO)

    def test_um_attempt_negativo_e_recusado_e_o_zero_nao(self) -> None:
        """Zero e legitimo: o `marcarEspera` repoe a zero."""
        self._rejeitado(VIOLACAO_DE_CHECK, attempt=-1)
        self._inserir(attempt=0)

    def test_o_attempt_nao_tem_omissao(self) -> None:
        """**Sem `DEFAULT`, de proposito**, e e a correccao de um desvio de um.

        Um `DEFAULT 0` convidava o `ON CONFLICT ... DO UPDATE SET attempt =
        attempt + 1` a deixar o `attempt` fora do `INSERT` e a devolver zero a
        primeira volta, deslocando as tres metades do criterio 5 em silencio.
        Sem omissao, esse `INSERT` leva `23502`.
        """
        self._rejeitado(VIOLACAO_DE_NOT_NULL, attempt=None)

    def test_o_mesmo_passo_do_mesmo_caso_duas_vezes_e_recusado(self) -> None:
        """A chave primaria **e** a `UNIQUE(onboarding_id, step)` do contrato."""
        caso = str(uuid.uuid4())
        self._inserir(onboarding_id=caso, step="chave_llm")
        self._inserir(onboarding_id=caso, step="canal_comercio")
        self._rejeitado(
            VIOLACAO_DE_UNICIDADE, onboarding_id=caso, step="chave_llm"
        )
