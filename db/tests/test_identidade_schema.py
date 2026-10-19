"""Gate 8: a revisao 0003 — identidade de contacto (KAM-008, ADR-010).

O que o **schema** garante sozinho, sem o modulo de identidade: restricoes,
privilegios e o `downgrade`. O comportamento do modulo (resolver, fundir, rodar,
apagar) prova-se na suite `tests_identidade`, com o codigo real.

As restricoes testam-se como administrador da instancia: contorna a RLS e os
privilegios, e por isso o que falha aqui falha **pela restricao**. Os
privilegios testam-se com o papel verdadeiro, ligado pela sua palavra-passe.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import bootstrap
import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    TABELAS,
    TABELAS_0001,
    TABELAS_ATE_0003,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_FK,
    VIOLACAO_DE_NOT_NULL,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

HMAC_A = bytes(range(32))
HMAC_B = bytes(range(1, 33))
VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0003_COPIA"


class _ComAdmin(ComBase):
    """Um tenant e um contacto com DEK, numa transaccao que nunca se confirma."""

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()
        self.tenant = factories.tenant(self.cursor)
        self.contacto = factories.contacto(self.cursor, self.tenant)
        self.dek = factories.dek(self.cursor, self.tenant, self.contacto)
        factories.versao_de_chave(self.cursor)

    def falha(self, esperado: str, sql: str, parametros: tuple = ()) -> None:
        self.assertErroSql(esperado, self.cursor, sql, parametros)

    def endpoint(self, **campos) -> tuple[str, tuple]:
        """SQL e parametros de um `INSERT` em `contact_endpoints`."""
        valores = {
            "tenant_id": self.tenant,
            "contact_id": self.contacto,
            "dek_id": self.dek,
            "tipo": "bsuid",
            "bsuid_hmac": HMAC_A,
            "hmac_kid": factories.KID_DE_TESTE,
            "bsuid_enc": b"cifra-de-ensaio",
        }
        valores.update(campos)
        colunas = ", ".join(valores)
        marcadores = ", ".join(["%s"] * len(valores))
        return (
            f"INSERT INTO platform.contact_endpoints ({colunas}) VALUES ({marcadores})",
            tuple(valores.values()),
        )


class TestContacts(_ComAdmin):
    def test_o_contact_id_e_aleatorio_e_nao_vem_de_fora(self) -> None:
        """ADR-010: `contact_id` aleatorio. Dois contactos sem mais nada tem ids diferentes."""
        outro = factories.contacto(self.cursor, self.tenant)
        self.assertNotEqual(outro, self.contacto)
        self.assertEqual(uuid.UUID(outro).version, 4)

    def test_contacto_sem_tenant_existente_falha(self) -> None:
        self.falha(
            VIOLACAO_DE_FK,
            "INSERT INTO platform.contacts (tenant_id) VALUES (%s)",
            (str(uuid.uuid4()),),
        )

    def test_o_hmac_do_telefone_tem_32_octetos(self) -> None:
        for mau in (b"", b"curto", bytes(31), bytes(33)):
            with self.subTest(octetos=len(mau)):
                self.falha(
                    VIOLACAO_DE_CHECK,
                    "UPDATE platform.contacts SET phone_hmac = %s, hmac_kid = %s "
                    "WHERE contact_id = %s",
                    (mau, factories.KID_DE_TESTE, self.contacto),
                )

    def test_hmac_e_versao_da_chave_andam_juntos(self) -> None:
        """Um HMAC sem `kid` nao se consegue rodar; um `kid` sem HMAC nao diz nada."""
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contacts SET phone_hmac = %s WHERE contact_id = %s",
            (HMAC_A, self.contacto),
        )
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contacts SET hmac_kid = %s WHERE contact_id = %s",
            (factories.KID_DE_TESTE, self.contacto),
        )

    def test_a_versao_da_chave_tem_de_estar_registada(self) -> None:
        self.falha(
            VIOLACAO_DE_FK,
            "UPDATE platform.contacts SET phone_hmac = %s, hmac_kid = 'kid-fantasma' "
            "WHERE contact_id = %s",
            (HMAC_A, self.contacto),
        )

    def test_o_mesmo_telefone_duas_vezes_no_tenant_falha(self) -> None:
        factories.contacto(
            self.cursor, self.tenant, phone_hmac=HMAC_A, hmac_kid=factories.KID_DE_TESTE
        )
        self.falha(
            VIOLACAO_DE_UNICIDADE,
            "INSERT INTO platform.contacts (tenant_id, phone_hmac, hmac_kid) "
            "VALUES (%s, %s, %s)",
            (self.tenant, HMAC_A, factories.KID_DE_TESTE),
        )

    def test_o_mesmo_telefone_noutro_tenant_e_outro_contacto(self) -> None:
        """O mesmo cliente em dois tenants e dois contactos (doc 03 §5.3, nota c)."""
        outro_tenant = factories.tenant(self.cursor)
        primeiro = factories.contacto(
            self.cursor, self.tenant, phone_hmac=HMAC_A, hmac_kid=factories.KID_DE_TESTE
        )
        segundo = factories.contacto(
            self.cursor, outro_tenant, phone_hmac=HMAC_A, hmac_kid=factories.KID_DE_TESTE
        )
        self.assertNotEqual(primeiro, segundo)

    def test_contactos_sem_telefone_coexistem(self) -> None:
        factories.contacto(self.cursor, self.tenant)
        factories.contacto(self.cursor, self.tenant)

    def test_um_contacto_apagado_nao_guarda_o_hmac_do_telefone(self) -> None:
        """Senao o telefone continuava a resolver para o contacto apagado."""
        com_telefone = factories.contacto(
            self.cursor, self.tenant, phone_hmac=HMAC_A, hmac_kid=factories.KID_DE_TESTE
        )
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contacts SET erased_at = now() WHERE contact_id = %s",
            (com_telefone,),
        )
        self.cursor.execute(
            "UPDATE platform.contacts SET erased_at = now(), phone_hmac = NULL, "
            "hmac_kid = NULL WHERE contact_id = %s",
            (com_telefone,),
        )

    def test_uma_lapide_de_fusao_nao_guarda_o_hmac_do_telefone(self) -> None:
        perdedor = factories.contacto(
            self.cursor, self.tenant, phone_hmac=HMAC_A, hmac_kid=factories.KID_DE_TESTE
        )
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contacts SET merged_into = %s, merged_at = now() "
            "WHERE contact_id = %s",
            (self.contacto, perdedor),
        )

    def test_a_fusao_tem_destino_e_data_ou_nenhum_dos_dois(self) -> None:
        outro = factories.contacto(self.cursor, self.tenant)
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contacts SET merged_into = %s WHERE contact_id = %s",
            (self.contacto, outro),
        )
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contacts SET merged_at = now() WHERE contact_id = %s",
            (outro,),
        )

    def test_um_contacto_nao_se_funde_consigo_proprio(self) -> None:
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contacts SET merged_into = contact_id, merged_at = now() "
            "WHERE contact_id = %s",
            (self.contacto,),
        )

    def test_um_contacto_nao_se_funde_com_o_de_outro_tenant(self) -> None:
        outro_tenant = factories.tenant(self.cursor)
        alheio = factories.contacto(self.cursor, outro_tenant)
        self.falha(
            VIOLACAO_DE_FK,
            "UPDATE platform.contacts SET merged_into = %s, merged_at = now() "
            "WHERE contact_id = %s",
            (alheio, self.contacto),
        )

    def test_nao_ha_coluna_de_texto_livre_em_contacts(self) -> None:
        """Nem nome, nem username, nem numero: so ids, HMAC, versao e datas."""
        linhas = self.consultar(
            "SELECT column_name::text FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'contacts' "
            "AND data_type IN ('text', 'character varying', 'jsonb', 'json')"
        )
        self.assertEqual(linhas, [("hmac_kid",)])


class TestEndpoints(_ComAdmin):
    def test_endpoint_de_bsuid_valido(self) -> None:
        self.cursor.execute(*self.endpoint())

    def test_endpoint_de_telefone_valido(self) -> None:
        factories.endpoint_telefone(self.cursor, self.tenant, self.contacto, self.dek)

    def test_o_tipo_e_fechado(self) -> None:
        sql, parametros = self.endpoint(tipo="email")
        self.falha(VIOLACAO_DE_CHECK, sql, parametros)
        self.assertEqual(
            self.consultar(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'contact_endpoints_tipo_ck'"
            ),
            [("CHECK ((tipo = ANY (ARRAY['bsuid'::text, 'telefone'::text])))",)],
        )

    def test_um_bsuid_sem_hmac_sem_versao_ou_sem_cifra_falha(self) -> None:
        for coluna in ("bsuid_hmac", "hmac_kid", "bsuid_enc"):
            with self.subTest(em_falta=coluna):
                sql, parametros = self.endpoint(**{coluna: None})
                self.falha(VIOLACAO_DE_CHECK, sql, parametros)

    def test_um_bsuid_nao_leva_telefone_nem_finalidade(self) -> None:
        sql, parametros = self.endpoint(phone_enc=b"cifra")
        self.falha(VIOLACAO_DE_CHECK, sql, parametros)
        sql, parametros = self.endpoint(finalidade="entrega")
        self.falha(VIOLACAO_DE_CHECK, sql, parametros)

    def test_um_telefone_exige_cifra_finalidade_e_prazo(self) -> None:
        """DoD: retencao e finalidade em `contact_endpoints.expira_at`."""
        base = {
            "tipo": "telefone", "bsuid_hmac": None, "hmac_kid": None, "bsuid_enc": None,
            "phone_enc": b"cifra", "finalidade": "entrega",
            "expira_at": "2099-01-01T00:00:00+00:00",
        }
        self.cursor.execute("SAVEPOINT positivo")
        self.cursor.execute(*self.endpoint(**base))
        self.cursor.execute("ROLLBACK TO SAVEPOINT positivo")
        for coluna in ("phone_enc", "finalidade", "expira_at"):
            with self.subTest(em_falta=coluna):
                sql, parametros = self.endpoint(**dict(base, **{coluna: None}))
                self.falha(VIOLACAO_DE_CHECK, sql, parametros)

    def test_um_telefone_nao_leva_hmac_nem_bsuid(self) -> None:
        base = {
            "tipo": "telefone", "bsuid_hmac": None, "hmac_kid": None, "bsuid_enc": None,
            "phone_enc": b"cifra", "finalidade": "entrega",
            "expira_at": "2099-01-01T00:00:00+00:00",
        }
        for coluna, valor in (
            ("bsuid_hmac", HMAC_A), ("hmac_kid", factories.KID_DE_TESTE),
            ("bsuid_enc", b"cifra"),
        ):
            with self.subTest(a_mais=coluna):
                sql, parametros = self.endpoint(**dict(base, **{coluna: valor}))
                self.falha(VIOLACAO_DE_CHECK, sql, parametros)

    def test_a_finalidade_e_fechada(self) -> None:
        with self.assertRaises(AssertionError):
            # Sanidade do proprio teste: uma finalidade valida nao falha.
            self.assertErroSql(
                VIOLACAO_DE_CHECK,
                self.cursor,
                *self._telefone("entrega"),
            )
        for finalidade in ("marketing", "", "Entrega"):
            with self.subTest(finalidade=finalidade):
                self.falha(VIOLACAO_DE_CHECK, *self._telefone(finalidade))

    def _telefone(self, finalidade: str) -> tuple[str, tuple]:
        return self.endpoint(
            tipo="telefone", bsuid_hmac=None, hmac_kid=None, bsuid_enc=None,
            phone_enc=b"cifra", finalidade=finalidade,
            expira_at="2099-01-01T00:00:00+00:00",
        )

    def test_o_hmac_do_bsuid_tem_32_octetos(self) -> None:
        for mau in (b"curto", bytes(31), bytes(33)):
            with self.subTest(octetos=len(mau)):
                sql, parametros = self.endpoint(bsuid_hmac=mau)
                self.falha(VIOLACAO_DE_CHECK, sql, parametros)

    def test_o_mesmo_bsuid_duas_vezes_no_tenant_falha(self) -> None:
        """A unicidade que o ticket pede, na tabela onde o dicionario poe o HMAC."""
        self.cursor.execute(*self.endpoint())
        outro = factories.contacto(self.cursor, self.tenant)
        outra_dek = factories.dek(self.cursor, self.tenant, outro)
        sql, parametros = self.endpoint(contact_id=outro, dek_id=outra_dek)
        self.falha(VIOLACAO_DE_UNICIDADE, sql, parametros)
        self.assertEqual(
            self.consultar(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'contact_endpoints_bsuid_uq'"
            ),
            [("UNIQUE (tenant_id, hmac_kid, bsuid_hmac)",)],
        )

    def test_o_mesmo_bsuid_noutro_tenant_e_outro_endpoint(self) -> None:
        self.cursor.execute(*self.endpoint())
        outro_tenant = factories.tenant(self.cursor)
        outro = factories.contacto(self.cursor, outro_tenant)
        outra_dek = factories.dek(self.cursor, outro_tenant, outro)
        self.cursor.execute(
            *self.endpoint(tenant_id=outro_tenant, contact_id=outro, dek_id=outra_dek)
        )

    def test_o_mesmo_hmac_com_outra_versao_da_chave_coexiste(self) -> None:
        """A janela de rotacao: a mesma linha logica existe sob o `kid` novo."""
        factories.versao_de_chave(self.cursor, "kid-seguinte")
        self.cursor.execute(*self.endpoint())
        self.cursor.execute(*self.endpoint(hmac_kid="kid-seguinte"))

    def test_um_telefone_por_contacto_e_finalidade(self) -> None:
        factories.endpoint_telefone(self.cursor, self.tenant, self.contacto, self.dek)
        factories.endpoint_telefone(
            self.cursor, self.tenant, self.contacto, self.dek, finalidade="contacto_pedido"
        )
        self.falha(VIOLACAO_DE_UNICIDADE, *self._telefone("entrega"))

    def test_endpoint_com_contacto_de_outro_tenant_falha(self) -> None:
        """FK composta: o `tenant_id` do endpoint e o do contacto sao o mesmo."""
        outro_tenant = factories.tenant(self.cursor)
        alheio = factories.contacto(self.cursor, outro_tenant)
        sql, parametros = self.endpoint(contact_id=alheio)
        self.falha(VIOLACAO_DE_FK, sql, parametros)

    def test_endpoint_com_dek_de_outro_tenant_falha(self) -> None:
        outro_tenant = factories.tenant(self.cursor)
        alheio = factories.contacto(self.cursor, outro_tenant)
        dek_alheia = factories.dek(self.cursor, outro_tenant, alheio)
        sql, parametros = self.endpoint(dek_id=dek_alheia)
        self.falha(VIOLACAO_DE_FK, sql, parametros)

    def test_endpoint_sem_dek_falha(self) -> None:
        sql, parametros = self.endpoint(dek_id=None)
        self.falha(VIOLACAO_DE_NOT_NULL, sql, parametros)

    def test_apagar_um_contacto_com_endpoints_falha(self) -> None:
        """Sem cascata: o apagamento e uma sequencia escrita, nao um efeito lateral."""
        self.cursor.execute(*self.endpoint())
        self.falha(
            VIOLACAO_DE_FK,
            "DELETE FROM platform.contacts WHERE contact_id = %s",
            (self.contacto,),
        )

    def test_o_bsuid_e_o_telefone_nao_tem_coluna_em_claro(self) -> None:
        """Em `contact_endpoints` so `tipo`, `finalidade` e `hmac_kid` sao texto."""
        linhas = self.consultar(
            "SELECT column_name::text FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'contact_endpoints' "
            "AND data_type NOT IN ('uuid', 'bytea', 'timestamp with time zone') ORDER BY 1"
        )
        self.assertEqual(linhas, [("finalidade",), ("hmac_kid",), ("tipo",)])


class TestDeks(_ComAdmin):
    def test_dek_com_contacto_de_outro_tenant_falha(self) -> None:
        outro_tenant = factories.tenant(self.cursor)
        self.falha(
            VIOLACAO_DE_FK,
            "INSERT INTO platform.contact_deks (tenant_id, contact_id, wrapped_dek, kek_id) "
            "VALUES (%s, %s, %s, 'kek-de-teste')",
            (outro_tenant, self.contacto, b"embrulho"),
        )

    def test_destruir_e_apagar_o_embrulho_e_datar(self) -> None:
        """Uma DEK «destruida» que ainda guarda o embrulho nao foi destruida."""
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contact_deks SET destroyed_at = now() WHERE dek_id = %s",
            (self.dek,),
        )
        self.falha(
            VIOLACAO_DE_CHECK,
            "UPDATE platform.contact_deks SET wrapped_dek = NULL WHERE dek_id = %s",
            (self.dek,),
        )
        self.cursor.execute(
            "UPDATE platform.contact_deks SET wrapped_dek = NULL, destroyed_at = now() "
            "WHERE dek_id = %s",
            (self.dek,),
        )

    def test_a_versao_da_kek_e_obrigatoria_e_sem_espacos(self) -> None:
        for mau in ("", " kek", "kek "):
            with self.subTest(kek_id=mau):
                self.falha(
                    VIOLACAO_DE_CHECK,
                    "UPDATE platform.contact_deks SET kek_id = %s WHERE dek_id = %s",
                    (mau, self.dek),
                )
        self.falha(
            VIOLACAO_DE_NOT_NULL,
            "UPDATE platform.contact_deks SET kek_id = NULL WHERE dek_id = %s",
            (self.dek,),
        )

    def test_apagar_uma_dek_em_uso_falha(self) -> None:
        factories.endpoint_bsuid(self.cursor, self.tenant, self.contacto, self.dek)
        self.falha(
            VIOLACAO_DE_FK,
            "DELETE FROM platform.contact_deks WHERE dek_id = %s",
            (self.dek,),
        )


class TestVersoesDeChave(_ComAdmin):
    def test_os_estados_sao_tres(self) -> None:
        self.falha(
            VIOLACAO_DE_CHECK,
            "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES ('k9', 'activa')",
        )
        self.assertEqual(
            self.consultar(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'hmac_key_versions_estado_ck'"
            ),
            [(
                "CHECK ((estado = ANY (ARRAY['actual'::text, 'anterior'::text, "
                "'retirada'::text])))",
            )],
        )

    def test_so_uma_actual_e_so_uma_anterior(self) -> None:
        for estado in ("actual", "anterior"):
            with self.subTest(estado=estado):
                self.cursor.execute(
                    "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES (%s, %s)",
                    (f"k-{estado}-1", estado),
                )
                self.falha(
                    VIOLACAO_DE_UNICIDADE,
                    "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES (%s, %s)",
                    (f"k-{estado}-2", estado),
                )

    def test_retiradas_pode_haver_varias(self) -> None:
        for kid in ("k-velha-1", "k-velha-2"):
            self.cursor.execute(
                "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES (%s, 'retirada')",
                (kid,),
            )

    def test_o_kid_tem_forma_de_identificador(self) -> None:
        for mau in ("", "Com-Maiusculas", " k1", "k 1", "-k1", "k" * 64, "segredo/valor"):
            with self.subTest(kid=mau):
                self.falha(
                    VIOLACAO_DE_CHECK,
                    "INSERT INTO platform.hmac_key_versions (kid, estado) "
                    "VALUES (%s, 'retirada')",
                    (mau,),
                )

    def test_a_tabela_nao_tem_onde_guardar_um_segredo(self) -> None:
        """«Metadados, nunca segredos»: tres colunas, e nenhuma e `bytea`."""
        linhas = self.consultar(
            "SELECT column_name::text, data_type::text FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name = 'hmac_key_versions' ORDER BY 1"
        )
        self.assertEqual(
            linhas,
            [("criado_at", "timestamp with time zone"), ("estado", "text"), ("kid", "text")],
        )

    def test_apagar_uma_versao_em_uso_falha(self) -> None:
        factories.endpoint_bsuid(self.cursor, self.tenant, self.contacto, self.dek)
        self.falha(
            VIOLACAO_DE_FK,
            "DELETE FROM platform.hmac_key_versions WHERE kid = %s",
            (factories.KID_DE_TESTE,),
        )


class TestDonoDoTenant(ComBase):
    """`tenants.owner_contact_id`: FK composta e diferida (a que o KAM-003 deixou)."""

    def test_o_tenant_e_o_seu_dono_nascem_na_mesma_transaccao(self) -> None:
        """Diferida: a ordem das instrucoes nao importa, so o estado no `COMMIT`."""
        cursor = self.ligar("admin").cursor()
        tenant, dono = str(uuid.uuid4()), str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO platform.tenants (id, tipo, nome, owner_contact_id) "
            "VALUES (%s, 'pme', 'Loja com dono', %s)",
            (tenant, dono),
        )
        cursor.execute(
            "INSERT INTO platform.contacts (contact_id, tenant_id) VALUES (%s, %s)",
            (dono, tenant),
        )
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_um_dono_que_nao_existe_falha_no_fim(self) -> None:
        cursor = self.ligar("admin").cursor()
        cursor.execute(
            "INSERT INTO platform.tenants (id, tipo, nome, owner_contact_id) "
            "VALUES (gen_random_uuid(), 'pme', 'Loja sem dono', gen_random_uuid())"
        )
        self.assertErroSql(VIOLACAO_DE_FK, cursor, "SET CONSTRAINTS ALL IMMEDIATE")

    def test_o_dono_tem_de_ser_um_contacto_do_proprio_tenant(self) -> None:
        """Com a FK simples do doc 03 §5.3, um tenant apontava para o contacto de outro."""
        cursor = self.ligar("admin").cursor()
        primeiro = factories.tenant(cursor)
        segundo = factories.tenant(cursor)
        alheio = factories.contacto(cursor, segundo)
        cursor.execute(
            "UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s",
            (alheio, primeiro),
        )
        self.assertErroSql(VIOLACAO_DE_FK, cursor, "SET CONSTRAINTS ALL IMMEDIATE")

    def test_um_tenant_sem_dono_continua_valido(self) -> None:
        cursor = self.ligar("admin").cursor()
        factories.tenant(cursor)
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

    def test_apagar_o_contacto_que_e_dono_falha(self) -> None:
        cursor = self.ligar("admin").cursor()
        tenant = factories.tenant(cursor)
        dono = factories.contacto(cursor, tenant)
        cursor.execute(
            "UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s", (dono, tenant)
        )
        # A partir daqui a FK e imediata nesta transaccao: falha na instrucao.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        self.assertErroSql(
            VIOLACAO_DE_FK,
            cursor,
            "DELETE FROM platform.contacts WHERE contact_id = %s",
            (dono,),
        )


class TestPrivilegiosDeIdentidade(ComBase):
    """O efeito, tentado com o papel verdadeiro. Criterio 8 do KAM-008."""

    def test_kamba_app_nao_le_contact_endpoints(self) -> None:
        cursor = self.ligar("app").cursor()
        for consulta in (
            "SELECT * FROM platform.contact_endpoints",
            "SELECT count(*) FROM platform.contact_endpoints",
            "SELECT id FROM platform.contact_endpoints",
            "SELECT bsuid_enc FROM platform.contact_endpoints",
            "SELECT 1 FROM platform.contact_endpoints LIMIT 1",
        ):
            with self.subTest(consulta=consulta):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, consulta)

    def test_um_join_de_encomendas_com_endpoints_falha_por_privilegio(self) -> None:
        """A letra do criterio. Ainda nao ha encomendas (EPIC-04): faz-se uma de ensaio.

        A tabela de ensaio e de `kamba_app` em tudo o que conta — tem `SELECT`
        nela — para que a recusa so possa vir de `contact_endpoints`.
        """
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        try:
            cursor_admin = admin.cursor()
            cursor_admin.execute(
                "CREATE TABLE platform.encomendas_de_ensaio "
                "(id uuid PRIMARY KEY DEFAULT gen_random_uuid(), contact_id uuid NOT NULL)"
            )
            cursor_admin.execute(
                "GRANT SELECT ON platform.encomendas_de_ensaio TO kamba_app"
            )
            cursor = self.ligar("app").cursor()
            cursor.execute("SELECT count(*) FROM platform.encomendas_de_ensaio")
            self.assertEqual(cursor.fetchone()[0], 0)
            for consulta in (
                "SELECT o.id, e.bsuid_enc FROM platform.encomendas_de_ensaio o "
                "JOIN platform.contact_endpoints e ON e.contact_id = o.contact_id",
                "SELECT o.id FROM platform.encomendas_de_ensaio o "
                "WHERE EXISTS (SELECT 1 FROM platform.contact_endpoints e "
                "              WHERE e.contact_id = o.contact_id)",
                "SELECT o.id FROM platform.encomendas_de_ensaio o "
                "LEFT JOIN platform.contact_endpoints e USING (contact_id)",
            ):
                with self.subTest(consulta=consulta[:60]):
                    self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, consulta)
        finally:
            for conexao in self._conexoes:
                conexao.rollback()
            admin.cursor().execute("DROP TABLE IF EXISTS platform.encomendas_de_ensaio")
            admin.close()

    def test_kamba_app_nao_le_as_deks_nem_as_versoes_de_chave(self) -> None:
        cursor = self.ligar("app").cursor()
        for tabela in ("contact_deks", "hmac_key_versions"):
            with self.subTest(tabela=tabela):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, cursor, f"SELECT count(*) FROM platform.{tabela}"
                )

    def test_kamba_app_le_de_contacts_so_as_colunas_de_negocio(self) -> None:
        cursor = self.ligar("app").cursor()
        cursor.execute(
            "SELECT contact_id, tenant_id, criado_at, erased_at, merged_into, merged_at "
            "FROM platform.contacts"
        )
        self.assertEqual(list(cursor.fetchall()), [])
        for consulta in (
            "SELECT phone_hmac FROM platform.contacts",
            "SELECT hmac_kid FROM platform.contacts",
            "SELECT * FROM platform.contacts",
            "SELECT contact_id FROM platform.contacts WHERE phone_hmac IS NOT NULL",
        ):
            with self.subTest(consulta=consulta):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, consulta)

    def test_kamba_app_nao_escreve_em_nenhuma_tabela_de_identidade(self) -> None:
        """Um contacto nasce, funde-se e apaga-se so pelo modulo de identidade."""
        cursor = self.ligar("app").cursor()
        for instrucao in (
            "INSERT INTO platform.contacts (tenant_id) VALUES (gen_random_uuid())",
            "UPDATE platform.contacts SET erased_at = now()",
            "UPDATE platform.contacts SET merged_at = NULL",
            "DELETE FROM platform.contacts",
            "INSERT INTO platform.contact_deks (tenant_id, contact_id, kek_id) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), 'k')",
            "UPDATE platform.contact_deks SET destroyed_at = now()",
            "DELETE FROM platform.contact_deks",
            "INSERT INTO platform.contact_endpoints (tenant_id, contact_id, dek_id, tipo) "
            "VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), 'bsuid')",
            "UPDATE platform.contact_endpoints SET expira_at = now()",
            "DELETE FROM platform.contact_endpoints",
            "INSERT INTO platform.hmac_key_versions (kid, estado) VALUES ('k', 'actual')",
            "UPDATE platform.hmac_key_versions SET estado = 'retirada'",
            "DELETE FROM platform.hmac_key_versions",
        ):
            with self.subTest(instrucao=instrucao[:60]):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, instrucao)

    def test_kamba_batch_e_kamba_resolver_nao_tocam_no_cofre(self) -> None:
        """`BYPASSRLS` sobre o cofre era ler todos os tenants de uma vez."""
        for identidade in ("batch", "resolver"):
            cursor = self.ligar(identidade).cursor()
            for tabela in ("contacts", "contact_deks", "contact_endpoints", "hmac_key_versions"):
                for instrucao in (
                    f"SELECT count(*) FROM platform.{tabela}",
                    f"DELETE FROM platform.{tabela}",
                ):
                    with self.subTest(identidade=identidade, instrucao=instrucao):
                        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, instrucao)

    def test_kamba_identity_liga_se_e_le_o_cofre_sem_contexto_ve_zero(self) -> None:
        cursor = self.ligar("identity").cursor()
        cursor.execute("SELECT current_user::text, session_user::text")
        self.assertEqual(tuple(cursor.fetchone()), ("kamba_identity", "kamba_identity"))
        for tabela in ("contacts", "contact_deks", "contact_endpoints"):
            with self.subTest(tabela=tabela):
                cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
                self.assertEqual(cursor.fetchone()[0], 0)

    def test_kamba_identity_nao_le_tenants_canais_nem_entitlements(self) -> None:
        cursor = self.ligar("identity").cursor()
        for tabela in TABELAS_0001:
            with self.subTest(tabela=tabela):
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, cursor, f"SELECT count(*) FROM platform.{tabela}"
                )

    def test_kamba_identity_nao_faz_o_que_o_modulo_nao_precisa(self) -> None:
        cursor = self.ligar("identity").cursor()
        for instrucao in (
            # Mover uma linha de tenant e a fuga que a RLS existe para impedir.
            "UPDATE platform.contacts SET tenant_id = gen_random_uuid()",
            "UPDATE platform.contact_endpoints SET tenant_id = gen_random_uuid()",
            "UPDATE platform.contact_deks SET tenant_id = gen_random_uuid()",
            # Identidade e registo.
            "UPDATE platform.contacts SET contact_id = gen_random_uuid()",
            "UPDATE platform.contacts SET criado_at = now()",
            "UPDATE platform.contact_endpoints SET tipo = 'telefone'",
            "UPDATE platform.contact_endpoints SET bsuid_enc = NULL",
            "UPDATE platform.contact_endpoints SET finalidade = 'entrega'",
            "UPDATE platform.hmac_key_versions SET kid = 'outro'",
            # Contactos e DEK nao se apagam: ficam a lapide e a prova da destruicao.
            "DELETE FROM platform.contacts",
            "DELETE FROM platform.contact_deks",
            "DELETE FROM platform.hmac_key_versions",
            "TRUNCATE platform.contact_endpoints",
            "CREATE TABLE platform.nao_devia_existir (x integer)",
            "CREATE TEMP TABLE t_identidade (x integer)",
        ):
            with self.subTest(instrucao=instrucao[:60]):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, instrucao)

    def test_kamba_identity_nao_assume_outro_papel(self) -> None:
        cursor = self.ligar("identity").cursor()
        for papel in ("kamba_app", "kamba_batch", "kamba_migrator", "kamba_resolver"):
            with self.subTest(papel=papel):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, cursor, f"SET ROLE {papel}")

    def test_o_bootstrap_repoe_um_bypassrls_dado_a_mao_a_kamba_identity(self) -> None:
        admin = ligacao.ligar("admin")
        admin.autocommit = True
        try:
            cursor = admin.cursor()
            cursor.execute("ALTER ROLE kamba_identity BYPASSRLS")
            bootstrap.aplicar()
            cursor.execute(
                "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'kamba_identity'"
            )
            self.assertFalse(cursor.fetchone()[0])
        finally:
            admin.close()


def _estado_da_0003(cursor) -> dict:
    cursor.execute(
        "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    tabelas = tuple(linha[0] for linha in cursor.fetchall())
    cursor.execute(
        "SELECT count(*) FROM pg_constraint WHERE conname = 'tenants_owner_fk'"
    )
    fk = cursor.fetchone()[0]
    cursor.execute(
        "SELECT has_schema_privilege('kamba_identity', 'platform', 'USAGE'), "
        "(SELECT count(*) FROM information_schema.table_privileges "
        "  WHERE grantee = 'kamba_identity' AND table_schema = 'platform'), "
        # Privilegios dados **por coluna** (`attacl`), sem os que vem da tabela.
        "(SELECT count(*) FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "  WHERE c.relnamespace = 'platform'::regnamespace "
        "    AND a.attacl::text LIKE '%%kamba_identity=%%'), "
        "(SELECT count(*) FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "  WHERE c.relnamespace = 'platform'::regnamespace AND c.relname = 'contacts' "
        "    AND a.attacl::text LIKE '%%kamba_app=%%')"
    )
    identidade = tuple(cursor.fetchone())
    cursor.execute(
        "SELECT tablename::text, policyname::text FROM pg_policies "
        "WHERE schemaname = 'platform' AND tablename LIKE 'contact%%' ORDER BY 1, 2"
    )
    politicas = [tuple(linha) for linha in cursor.fetchall()]
    cursor.execute(
        "SELECT col_description('platform.tenants'::regclass, "
        "(SELECT attnum FROM pg_attribute WHERE attrelid = 'platform.tenants'::regclass "
        "  AND attname = 'owner_contact_id'))"
    )
    comentario = cursor.fetchone()[0]
    cursor.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE oid = 'platform.tenants'::regclass"
    )
    rls_de_tenants = tuple(cursor.fetchone())
    return {
        "rls_de_tenants": rls_de_tenants,
        "tabelas": tabelas,
        "fk_do_dono": fk,
        "identidade": identidade,
        "politicas": politicas,
        "comentario": comentario,
    }


class TestDowngradeDa0003(unittest.TestCase):
    """«Migracoes reversiveis — sem perda silenciosa de endpoints: backup logico no passo.»

    Nao herda de `ComBase`: controla ele proprio a revisao em que a base esta.
    """

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
        self.pasta = tempfile.TemporaryDirectory()
        self.copia = Path(self.pasta.name) / "copia-0003.jsonl"
        self.tenants: list[str] = []
        os.environ.pop(VARIAVEL_DA_COPIA, None)

    def tearDown(self) -> None:
        os.environ.pop(VARIAVEL_DA_COPIA, None)
        try:
            # Cada processo do Alembic custa segundos: so quando a base nao esta
            # em `head` (o teste desceu, ou falhou a meio de descer).
            if not em_head():
                alembic_ok("upgrade", "head")
            for tenant in self.tenants:
                self.cursor.execute(
                    "UPDATE platform.tenants SET owner_contact_id = NULL WHERE id = %s",
                    (tenant,),
                )
                self.cursor.execute(
                    "DELETE FROM platform.contact_endpoints WHERE tenant_id = %s", (tenant,)
                )
                self.cursor.execute(
                    "DELETE FROM platform.contact_deks WHERE tenant_id = %s", (tenant,)
                )
                self.cursor.execute(
                    "DELETE FROM platform.contacts WHERE tenant_id = %s", (tenant,)
                )
                self.cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (tenant,))
            self.cursor.execute(
                "DELETE FROM platform.hmac_key_versions WHERE kid = %s",
                (factories.KID_DE_TESTE,),
            )
        finally:
            self.conexao.close()
            self.pasta.cleanup()

    def semear(self) -> dict[str, int]:
        """Dois tenants, tres contactos, com endpoints dos dois tipos. Confirmado."""
        for _ in range(2):
            tenant = factories.tenant(self.cursor)
            self.tenants.append(tenant)
            for indice in range(2 if tenant == self.tenants[0] else 1):
                contacto = factories.contacto(self.cursor, tenant)
                dek = factories.dek(self.cursor, tenant, contacto)
                factories.endpoint_bsuid(self.cursor, tenant, contacto, dek)
                if indice == 0:
                    factories.endpoint_telefone(self.cursor, tenant, contacto, dek)
                    # O primeiro contacto de cada tenant e o seu dono.
                    self.cursor.execute(
                        "UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s",
                        (contacto, tenant),
                    )
        return {
            "hmac_key_versions": 1, "contacts": 3, "contact_deks": 3,
            "contact_endpoints": 5, "tenants": 2,
        }

    def donos(self) -> list[tuple]:
        self.cursor.execute(
            "SELECT id::text, owner_contact_id::text FROM platform.tenants "
            "WHERE id = ANY(%s) ORDER BY 1",
            (self.tenants,),
        )
        return [tuple(linha) for linha in self.cursor.fetchall()]

    def linhas(self, tabela: str) -> list[dict]:
        self.cursor.execute(f"SELECT * FROM platform.{tabela} ORDER BY 1")
        colunas = [d[0] for d in self.cursor.description]
        return [dict(zip(colunas, linha)) for linha in self.cursor.fetchall()]

    def test_o_downgrade_desfaz_tudo_o_que_a_0003_fez(self) -> None:
        em_head = _estado_da_0003(self.cursor)
        self.assertEqual(em_head["tabelas"], TABELAS)
        self.assertEqual(em_head["fk_do_dono"], 1)
        # USAGE; quatro tabelas x (SELECT, INSERT) + DELETE; 24 colunas com ACL
        # por coluna; seis colunas de SELECT de `kamba_app` em `contacts`.
        #
        # **24 e nao 17 desde o KAM-014.** A revisao `0009` da ao
        # `kamba_identity` privilegios por coluna na `conversations` — `SELECT`
        # em sete e `UPDATE` em quatro delas —, e a contagem e de **colunas com
        # ACL** e nao de concessoes: as sete da conversa somam-se as dezassete
        # da identidade. E para o gancho de fusao reapontar conversas **dentro**
        # da transacao da fusao, que e a unica forma de a atomicidade do KAM-008
        # continuar verdadeira (`docs/chr.md` §5).
        self.assertEqual(em_head["identidade"], (True, 9, 24, 6))
        self.assertEqual(
            em_head["politicas"],
            [
                ("contact_deks", "tenant_iso"),
                ("contact_endpoints", "tenant_iso"),
                ("contacts", "tenant_iso"),
            ],
        )
        self.assertIn("FK composta e diferida", em_head["comentario"])
        # A 0003 tira o `FORCE` a `tenants` para validar a FK, e tem de o repor.
        self.assertEqual(em_head["rls_de_tenants"], (True, True))

        alembic_ok("downgrade", "0002")
        em_0002 = _estado_da_0003(self.cursor)
        self.assertEqual(em_0002["tabelas"], TABELAS_0001)
        self.assertEqual(em_0002["fk_do_dono"], 0)
        self.assertEqual(em_0002["identidade"], (False, 0, 0, 0))
        self.assertEqual(em_0002["politicas"], [])
        self.assertIn("Sem FK nesta revisao", em_0002["comentario"])
        self.assertEqual(em_0002["rls_de_tenants"], (True, True))

        # Com as tabelas vazias nao ha o que copiar: o passo nao pede copia.
        self.assertFalse(self.copia.exists())

        alembic_ok("upgrade", "head")
        self.assertEqual(_estado_da_0003(self.cursor), em_head)

    def test_com_linhas_e_sem_copia_o_downgrade_e_recusado_e_nada_muda(self) -> None:
        """Sem perda silenciosa: falha, diz porque, e a base fica como estava."""
        contagens = self.semear()
        antes = {tabela: self.linhas(tabela) for tabela in contagens}
        donos = self.donos()

        resultado = alembic("downgrade", "0002")

        self.assertNotEqual(resultado.returncode, 0, "o downgrade apagou os endpoints calado")
        self.assertIn(VARIAVEL_DA_COPIA, resultado.stdout + resultado.stderr)
        self.assertIn("contact_endpoints: 5", resultado.stdout + resultado.stderr)
        self.assertIn("donos de tenant: 2", resultado.stdout + resultado.stderr)
        self.assertEqual(self.donos(), donos, "o passo falhou e anulou os donos")
        self.assertEqual(_estado_da_0003(self.cursor)["rls_de_tenants"], (True, True))
        # O DDL e transaccional: a RLS que o passo ja tinha desligado voltou.
        #
        # `TABELAS_ATE_0003` e nao `TABELAS`: o Alembic corre **uma transaccao
        # por revisao** (`transaction_per_migration=True`), pelo que um
        # `downgrade 0002` a partir da cabeca desce a 0004 — que confirma — antes
        # de tentar a 0003. O que esta recusa protege e a identidade, e essa fica
        # inteira; e o que as linhas abaixo verificam.
        self.assertEqual(_estado_da_0003(self.cursor)["tabelas"], TABELAS_ATE_0003)
        self.assertEqual(len(_estado_da_0003(self.cursor)["politicas"]), 3)
        self.assertEqual({tabela: self.linhas(tabela) for tabela in contagens}, antes)

    def test_basta_uma_linha_em_qualquer_das_tres_tabelas(self) -> None:
        """Um contacto sem endpoints tambem e identidade que o passo apagaria."""
        tenant = factories.tenant(self.cursor)
        self.tenants.append(tenant)
        factories.contacto(self.cursor, tenant)
        resultado = alembic("downgrade", "0002")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("contacts: 1", resultado.stdout + resultado.stderr)

    def test_basta_uma_versao_de_chave(self) -> None:
        """Qual era a versao actual e a anterior tambem se perde com o passo."""
        factories.versao_de_chave(self.cursor)
        resultado = alembic("downgrade", "0002")
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("hmac_key_versions: 1", resultado.stdout + resultado.stderr)

    def test_com_copia_o_downgrade_avanca_e_a_copia_tem_todas_as_linhas(self) -> None:
        contagens = self.semear()
        de_identidade = [tabela for tabela in contagens if tabela != "tenants"]
        antes = {tabela: self.linhas(tabela) for tabela in de_identidade}
        donos = self.donos()
        self.assertEqual(len([d for d in donos if d[1] is not None]), 2)
        os.environ[VARIAVEL_DA_COPIA] = str(self.copia)

        alembic_ok("downgrade", "0002")

        self.assertEqual(_estado_da_0003(self.cursor)["tabelas"], TABELAS_0001)
        # Sem `contacts`, um dono preenchido apontava para nada: o passo anula-os
        # (estao na copia), e `tenants` volta a ter `FORCE`.
        self.assertEqual([dono for _, dono in self.donos()], [None, None])
        self.assertEqual(_estado_da_0003(self.cursor)["rls_de_tenants"], (True, True))
        registos = [
            json.loads(linha)
            for linha in self.copia.read_text(encoding="utf-8").splitlines()
        ]
        por_tabela: dict[str, list[dict]] = {}
        for registo in registos:
            por_tabela.setdefault(registo["tabela"], []).append(registo["linha"])
        self.assertEqual({t: len(l) for t, l in por_tabela.items()}, contagens)

        # A copia chega para repor tudo, octeto a octeto: sobe-se outra vez — o
        # que so e possivel porque os donos foram anulados —, repoe-se pela
        # ordem da copia, e compara-se.
        alembic_ok("upgrade", "head")
        self.assertEqual(
            list(por_tabela),
            ["hmac_key_versions", "contacts", "contact_deks", "contact_endpoints", "tenants"],
        )
        for tabela in de_identidade:
            for linha in por_tabela[tabela]:
                valores = {
                    coluna: base64.b64decode(valor["b64"]) if isinstance(valor, dict) else valor
                    for coluna, valor in linha.items()
                }
                colunas = ", ".join(valores)
                marcadores = ", ".join(["%s"] * len(valores))
                self.cursor.execute(
                    f"INSERT INTO platform.{tabela} ({colunas}) VALUES ({marcadores})",
                    tuple(valores.values()),
                )
        self.assertEqual({tabela: self.linhas(tabela) for tabela in de_identidade}, antes)
        for linha in por_tabela["tenants"]:
            self.cursor.execute(
                "UPDATE platform.tenants SET owner_contact_id = %s WHERE id = %s",
                (linha["owner_contact_id"], linha["id"]),
            )
        self.assertEqual(self.donos(), donos)

    def test_a_copia_nao_escreve_por_cima_de_um_ficheiro_que_ja_existe(self) -> None:
        self.semear()
        self.copia.write_text("copia anterior\n", encoding="utf-8")
        os.environ[VARIAVEL_DA_COPIA] = str(self.copia)

        resultado = alembic("downgrade", "0002")

        self.assertNotEqual(resultado.returncode, 0)
        self.assertEqual(self.copia.read_text(encoding="utf-8"), "copia anterior\n")
        # Ver a nota em `test_com_linhas_e_sem_copia_...`: a 0004 ja desceu.
        self.assertEqual(_estado_da_0003(self.cursor)["tabelas"], TABELAS_ATE_0003)

    def test_o_upgrade_preserva_os_tenants_e_trava_num_dono_orfao(self) -> None:
        """Aditiva para quem nao tem dono; fechada para um dono que nao aponta para nada.

        Um tenant com `owner_contact_id` nulo atravessa a 0003 intacto. Um
        `owner_contact_id` posto antes da FK — quando nao havia `contacts` — e
        orfao por definicao, e o `upgrade` falha em vez de o deixar debaixo de
        uma FK que diz que nao ha orfaos.
        """
        alembic_ok("downgrade", "0002")
        self.cursor.execute(
            "INSERT INTO platform.tenants (id, tipo, nome) "
            "VALUES (gen_random_uuid(), 'pme', 'antes da identidade') RETURNING id::text"
        )
        tenant = self.cursor.fetchone()[0]
        self.tenants.append(tenant)
        self.cursor.execute(
            "INSERT INTO platform.tenants (id, tipo, nome, owner_contact_id) "
            "VALUES (gen_random_uuid(), 'pme', 'dono orfao', gen_random_uuid()) "
            "RETURNING id::text"
        )
        orfao = self.cursor.fetchone()[0]
        try:
            resultado = alembic("upgrade", "head")
            self.assertNotEqual(
                resultado.returncode, 0, "um dono orfao passou a validacao da FK"
            )
            self.assertIn("tenants_owner_fk", resultado.stdout + resultado.stderr)
            self.assertEqual(_estado_da_0003(self.cursor)["tabelas"], TABELAS_0001)
            # A revisao falhou inteira: `tenants` nao ficou sem o `FORCE`.
            self.assertEqual(_estado_da_0003(self.cursor)["rls_de_tenants"], (True, True))
        finally:
            self.cursor.execute("DELETE FROM platform.tenants WHERE id = %s", (orfao,))

        alembic_ok("upgrade", "head")
        self.cursor.execute(
            "SELECT nome, owner_contact_id FROM platform.tenants WHERE id = %s", (tenant,)
        )
        self.assertEqual(tuple(self.cursor.fetchone()), ("antes da identidade", None))


if __name__ == "__main__":
    unittest.main()
