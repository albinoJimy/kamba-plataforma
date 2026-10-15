"""Gate 8: o que cada papel **consegue**, e nao so os atributos que tem.

A primeira versao destes testes media `rolbypassrls` e pouco mais, e a revisao
adversarial mostrou o que isso deixava passar: com `GRANT kamba_batch TO
kamba_app` no bootstrap — a aplicacao a um `SET ROLE` de contornar a RLS — os
75 testes continuavam verdes. O criterio «`kamba_app` `NOBYPASSRLS`, sem DDL»
passava com a propriedade falsa.

Aqui mede-se o efeito: pertencas, a matriz exacta de privilegios por tabela e
por coluna, os privilegios por omissao, e o que acontece quando `kamba_app`
tenta o que nao deve.
"""

from __future__ import annotations

import bootstrap
import ligacao
from tests import factories
from tests.base import PRIVILEGIO_INSUFICIENTE, TABELAS, TABELAS_0001, ComBase

PRIVILEGIOS_DE_TABELA = (
    "SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER",
)

#: O que cada papel tem **ao nivel da tabela** nas tres tabelas da revisao 0001.
#: `kamba_app` nao tem UPDATE de tabela: tem-no coluna a coluna (ver abaixo).
#: `kamba_resolver` nao tem **nada** ao nivel da tabela: so `SELECT` por coluna
#: (conferido em `tests_isolamento/test_resolver.py`). Esteve fora desta matriz,
#: e a revisao do KAM-004 mostrou que um `GRANT INSERT` ao resolvedor passava
#: nos dois gates. `kamba_migrator` e o dono, e tem tudo. `kamba_identity`
#: (KAM-008) nao tem nada nestas tres: nao le tenants, canais nem entitlements.
_ESPERADO_0001 = {
    "kamba_app": {"SELECT", "INSERT"},
    "kamba_batch": {"SELECT", "INSERT", "UPDATE", "DELETE"},
    "kamba_resolver": set(),
    "kamba_identity": set(),
    "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
    "public": set(),
}


def _identidade(*privilegios: str) -> dict[str, set[str]]:
    """Matriz de uma tabela da revisao 0003: so `kamba_identity` e o dono.

    `kamba_app` nao tem **nada** ao nivel da tabela — em `contacts` tem `SELECT`
    por coluna (ver `COLUNAS_POR_PAPEL`), nas outras nem isso. `kamba_batch`
    tambem nao: quem purga (KAM-071) e quem roda chaves (KAM-072) pede o que
    precisar por revisao, em vez de herdar `BYPASSRLS` sobre o cofre.
    """
    return {
        "kamba_app": set(),
        "kamba_batch": set(),
        "kamba_resolver": set(),
        "kamba_identity": set(privilegios),
        "kamba_migrator": set(PRIVILEGIOS_DE_TABELA),
        "public": set(),
    }


#: tabela -> papel -> privilegios de tabela. Cobre **todas** as tabelas de
#: `platform`: uma tabela nova sem linha aqui falha `test_a_matriz_cobre_...`.
ESPERADO_POR_TABELA = {tabela: _ESPERADO_0001 for tabela in TABELAS_0001}
ESPERADO_POR_TABELA.update(
    {
        "contacts": _identidade("SELECT", "INSERT"),
        "contact_deks": _identidade("SELECT", "INSERT"),
        # O unico `DELETE` fora do `kamba_batch`: o apagamento a pedido do
        # titular e um `DELETE` verdadeiro (doc 06 §7.6), e so aqui.
        "contact_endpoints": _identidade("SELECT", "INSERT", "DELETE"),
        "hmac_key_versions": _identidade("SELECT", "INSERT"),
    }
)

#: (papel, tabela, privilegio) -> colunas concedidas **por coluna** nas tabelas
#: da revisao 0003. O que nao esta aqui nao tem privilegio de coluna nenhum.
COLUNAS_POR_PAPEL = {
    ("kamba_app", "contacts", "SELECT"): {
        "contact_id", "tenant_id", "criado_at", "erased_at", "merged_into", "merged_at",
    },
    ("kamba_identity", "contacts", "UPDATE"): {
        "phone_hmac", "hmac_kid", "erased_at", "merged_into", "merged_at",
    },
    ("kamba_identity", "contact_endpoints", "UPDATE"): {
        "contact_id", "bsuid_hmac", "hmac_kid", "phone_enc", "dek_id",
        "recolhido_at", "expira_at",
    },
    ("kamba_identity", "contact_deks", "UPDATE"): {
        "contact_id", "wrapped_dek", "kek_id", "destroyed_at",
    },
    ("kamba_identity", "hmac_key_versions", "UPDATE"): {"estado"},
}
PRIVILEGIOS_DE_COLUNA = ("SELECT", "INSERT", "UPDATE", "REFERENCES")

#: Colunas que `kamba_app` **nao** pode alterar depois do insert, e porque.
IMUTAVEIS_PARA_A_APP = {
    "tenants": {
        "id",         # identidade
        "tipo",       # costura do Fluxo B: `platform` -> `pme` tirava-o da vista da guarda
        "criado_at",  # registo
    },
    "tenant_channels": {
        "id",         # identidade
        "tenant_id",  # mover um canal de tenant entregava mensagens de um negocio a outro
        "origem",     # costura do Fluxo B
    },
    "entitlements": {
        "tenant_id",  # chave
        "modulo",     # chave
    },
}


class TestPertencas(ComBase):
    def test_nenhum_dos_tres_papeis_pertence_a_outro_nem_tem_membros(self) -> None:
        linhas = self.consultar(
            "SELECT g.rolname, m.rolname FROM pg_auth_members a "
            "JOIN pg_roles g ON g.oid = a.roleid JOIN pg_roles m ON m.oid = a.member "
            "WHERE g.rolname = ANY(%s) OR m.rolname = ANY(%s)",
            (list(ligacao.PAPEIS.values()), list(ligacao.PAPEIS.values())),
        )
        self.assertEqual(linhas, [])

    def test_o_bootstrap_revoga_uma_pertenca_posta_a_mao(self) -> None:
        """`GRANT kamba_batch TO kamba_app` e o atalho para contornar a RLS."""
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        try:
            cursor = admin.cursor()
            cursor.execute("GRANT kamba_batch TO kamba_app")
            cursor.execute("GRANT kamba_migrator TO kamba_app")
            feito = bootstrap.aplicar()
            self.assertEqual(sum("pertenca revogada" in linha for linha in feito), 2)
            cursor.execute(
                "SELECT count(*) FROM pg_auth_members a "
                "JOIN pg_roles m ON m.oid = a.member WHERE m.rolname = 'kamba_app'"
            )
            self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            admin.close()

    def test_kamba_app_nao_assume_outro_papel(self) -> None:
        cursor = self.ligar("app").cursor()
        for papel in ("kamba_migrator", "kamba_batch"):
            with self.subTest(papel=papel):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, f"SET ROLE {papel}")

    def test_o_bootstrap_apaga_configuracao_posta_a_mao(self) -> None:
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        try:
            cursor = admin.cursor()
            cursor.execute("ALTER ROLE kamba_app SET search_path = intrusa, public")
            bootstrap.aplicar()
            cursor.execute(
                "SELECT rolconfig FROM pg_roles WHERE rolname = 'kamba_app'"
            )
            self.assertIsNone(cursor.fetchone()[0])
        finally:
            admin.close()


class TestMatrizDePrivilegios(ComBase):
    """A matriz exacta: nem um privilegio a menos, nem um a mais."""

    def test_privilegios_de_tabela(self) -> None:
        # Uma so ligacao para a matriz inteira: uma por celula esgotava as do servidor.
        cursor = self.ligar("admin").cursor()
        for tabela in TABELAS:
            for papel, esperados in ESPERADO_POR_TABELA[tabela].items():
                for privilegio in PRIVILEGIOS_DE_TABELA:
                    with self.subTest(papel=papel, tabela=tabela, privilegio=privilegio):
                        cursor.execute(
                            "SELECT has_table_privilege(%s, %s, %s)",
                            (papel, f"platform.{tabela}", privilegio),
                        )
                        self.assertEqual(cursor.fetchone()[0], privilegio in esperados)

    def test_a_matriz_cobre_todos_os_papeis_do_bootstrap(self) -> None:
        """Um papel novo que ninguem ponha na matriz e um papel por medir."""
        self.assertEqual(set(ESPERADO_POR_TABELA), set(TABELAS))
        for tabela, por_papel in ESPERADO_POR_TABELA.items():
            with self.subTest(tabela=tabela):
                self.assertEqual(
                    set(por_papel) - {"public"}, set(ligacao.PAPEIS.values())
                )

    def test_privilegios_por_coluna_nas_tabelas_de_identidade(self) -> None:
        """Coluna a coluna, nos dois sentidos, para todos os papeis menos o dono.

        `has_column_privilege` tambem responde `true` quando o privilegio e de
        tabela; por isso o esperado e a uniao dos dois. Um `GRANT UPDATE
        (tenant_id)` a `kamba_identity`, ou um `GRANT SELECT (phone_hmac)` a
        `kamba_app`, aparece aqui como uma coluna a mais.
        """
        cursor = self.ligar("admin").cursor()
        for tabela in ("contacts", "contact_deks", "contact_endpoints", "hmac_key_versions"):
            cursor.execute(
                "SELECT column_name::text FROM information_schema.columns "
                "WHERE table_schema = 'platform' AND table_name = %s",
                (tabela,),
            )
            colunas = sorted(linha[0] for linha in cursor.fetchall())
            self.assertTrue(colunas)
            for papel in ("kamba_app", "kamba_batch", "kamba_resolver", "kamba_identity", "public"):
                for privilegio in PRIVILEGIOS_DE_COLUNA:
                    de_tabela = privilegio in ESPERADO_POR_TABELA[tabela][papel]
                    por_coluna = COLUNAS_POR_PAPEL.get((papel, tabela, privilegio), set())
                    self.assertTrue(por_coluna <= set(colunas), "coluna inexistente na matriz")
                    for coluna in colunas:
                        with self.subTest(
                            papel=papel, coluna=f"{tabela}.{coluna}", privilegio=privilegio
                        ):
                            cursor.execute(
                                "SELECT has_column_privilege(%s, %s, %s, %s)",
                                (papel, f"platform.{tabela}", coluna, privilegio),
                            )
                            self.assertEqual(
                                cursor.fetchone()[0], de_tabela or coluna in por_coluna
                            )

    def test_ninguem_pode_passar_privilegios_adiante(self) -> None:
        for papel in ("kamba_app", "kamba_batch", "kamba_resolver", "kamba_identity"):
            for tabela in TABELAS:
                with self.subTest(papel=papel, tabela=tabela):
                    tem = self.consultar(
                        "SELECT has_table_privilege(%s, %s, 'SELECT WITH GRANT OPTION')",
                        (papel, f"platform.{tabela}"),
                    )[0][0]
                    self.assertFalse(tem)

    def test_update_por_coluna_da_app(self) -> None:
        """Todas as colunas menos as imutaveis — e a lista confere-se nos dois sentidos."""
        for tabela, imutaveis in IMUTAVEIS_PARA_A_APP.items():
            colunas = self.consultar(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'platform' AND table_name = %s",
                (tabela,),
            )
            nomes = {c for (c,) in colunas}
            self.assertTrue(imutaveis <= nomes, f"coluna imutavel inexistente em {tabela}")
            for coluna in sorted(nomes):
                with self.subTest(coluna=f"{tabela}.{coluna}"):
                    pode = self.consultar(
                        "SELECT has_column_privilege('kamba_app', %s, %s, 'UPDATE')",
                        (f"platform.{tabela}", coluna),
                    )[0][0]
                    self.assertEqual(pode, coluna not in imutaveis)

    def test_nao_ha_privilegios_por_omissao(self) -> None:
        """Sem `ALTER DEFAULT PRIVILEGES`: uma tabela nova nao nasce acessivel."""
        self.assertEqual(self.consultar("SELECT count(*) FROM pg_default_acl"), [(0,)])

    def test_public_nao_tem_nada_na_base(self) -> None:
        base = ligacao.alvo().base
        linhas = self.consultar(
            "SELECT has_database_privilege('public', %s, 'TEMPORARY'), "
            "has_database_privilege('public', %s, 'CONNECT'), "
            "has_database_privilege('kamba_app', %s, 'CONNECT'), "
            "has_database_privilege('kamba_app', %s, 'TEMPORARY'), "
            "has_database_privilege('kamba_app', %s, 'CREATE')",
            (base, base, base, base, base),
        )
        self.assertEqual(linhas, [(False, False, True, False, False)])


class TestOQueAAppNaoConsegue(ComBase):
    """O efeito, tentado: cada uma destas instrucoes era aceite na primeira versao."""

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("app")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.canal = factories.canal(self.cursor, self.tenant)
        factories.entitlement(self.cursor, self.tenant)

    def test_nao_apaga_linhas_de_tabela_nenhuma(self) -> None:
        """Dicionario §2: «soft delete: estado, nunca DELETE». Nas sete tabelas."""
        for tabela in TABELAS:
            with self.subTest(tabela=tabela):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, self.cursor, f"DELETE FROM platform.{tabela}"
                )

    def test_nao_muda_o_tipo_de_um_tenant(self) -> None:
        """Um tenant `platform` que passasse a `pme` saia da vista da guarda."""
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor,
            "UPDATE platform.tenants SET tipo = 'courier' WHERE id = %s",
            (self.tenant,),
        )

    def test_nao_move_um_canal_para_outro_tenant(self) -> None:
        outro = factories.tenant(self.cursor)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor,
            "UPDATE platform.tenant_channels SET tenant_id = %s WHERE id = %s",
            (outro, self.canal),
        )

    def test_nao_muda_a_origem_de_um_canal(self) -> None:
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE,
            self.cursor,
            "UPDATE platform.tenant_channels SET origem = 'plataforma' WHERE id = %s",
            (self.canal,),
        )

    def test_nao_cria_tabelas_temporarias(self) -> None:
        """O criterio diz «`CREATE TABLE` sob `kamba_app` falha», sem excepcao."""
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.cursor, "CREATE TEMP TABLE t_app (x integer)"
        )

    def test_continua_a_poder_o_que_deve(self) -> None:
        """A correccao nao pode ter tirado a aplicacao o que ela precisa."""
        self.cursor.execute(
            "UPDATE platform.tenants SET estado = 'ativo', nome = 'Outro nome' "
            "WHERE id = %s",
            (self.tenant,),
        )
        self.cursor.execute(
            "UPDATE platform.tenant_channels SET estado = 'ativo', "
            "quality_rating = 'GREEN' WHERE id = %s",
            (self.canal,),
        )
        self.cursor.execute(
            "UPDATE platform.entitlements SET ativo = false WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.cursor.execute(
            "SELECT count(*) FROM platform.tenant_channels WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)


class TestOBatch(ComBase):
    def test_apaga_e_altera_tudo(self) -> None:
        """Retencao e correccoes sao do `kamba_batch`, auditado (doc 08 §3.3)."""
        cursor = self.ligar("batch").cursor()
        tenant = factories.tenant(cursor, tipo="platform")
        factories.entitlement(cursor, tenant)
        cursor.execute("UPDATE platform.tenants SET tipo = 'pme' WHERE id = %s", (tenant,))
        cursor.execute("DELETE FROM platform.entitlements WHERE tenant_id = %s", (tenant,))
        cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))
