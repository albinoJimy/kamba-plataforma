"""A revisao 0013 contra a base: o motivo de restricao e os codigos vistos.

Duas coisas, e a segunda e a que o DoD pede pelo nome:

1. **O que o DDL promete.** O dominio fechado de `motivo_restricao`, o tecto do
   `meta_error_codes_seen`, a omissao e o `NOT NULL` do conjunto, e o
   privilegio: o `kamba_app` tem de poder escrever as duas colunas, porque e
   ele que corre o adaptador que consome os `statuses` da Meta.

2. **O `downgrade`** — «Migracoes reversiveis: `downgrade` testado». Ao
   contrario do da `0010`, este **nao recusa com linhas** e e deliberado: o que
   se perde e o motivo de uma restricao e um conjunto de codigos de
   diagnostico, e os dois reconstroem-se do proximo `statuses` que chegar.
   Nenhum e prova de nada perante terceiros. Uma guarda que obrigasse a uma
   variavel de ambiente para desfazer duas colunas de diagnostico era cerimonia
   sem conteudo — e a diferenca face a `0010`, que apaga o registo do que se
   enviou e cobrou, esta escrita no `docstring` da propria revisao.

   O que este teste **exige** e que o `downgrade` reponha o privilegio da
   `0001` tal e qual. Sem isso, descer e subir deixava o `kamba_app` com uma
   concessao a menos e o adaptador a falhar com `42501` numa coluna que nada
   neste ficheiro nomeia.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
da base, e `ComBase` assume `head`.
"""

from __future__ import annotations

import unittest

import bootstrap
import ligacao
from tests import factories
from tests.base import (
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

#: Os SQLSTATE que os dois casos negativos esperam.
CHECK_VIOLATION = "23514"
NOT_NULL_VIOLATION = "23502"

#: O dominio de `motivo_restricao`, como a revisao o declara.
MOTIVOS = ("payment_method", "quality", "policy")

#: O tecto de codigos distintos por canal, como a revisao o declara.
TECTO_DE_CODIGOS = 32

#: As colunas de `tenant_channels` que o `kamba_app` pode alterar depois da
#: `0013`. E a lista da `0001` mais as duas novas.
COLUNAS_DA_APP = (
    "channel_mode",
    "coexistence_synced_at",
    "estado",
    "free_tier_month",
    "free_tier_used",
    "last_account_update_at",
    "messaging_limit",
    "meta_error_codes_seen",
    "motivo_restricao",
    "phone_number_id",
    "quality_rating",
    "token_ref",
    "vertical",
    "waac_id",
    "waba_id",
)

#: As da `0001`, para o `downgrade` as repor.
COLUNAS_DA_0001 = tuple(
    c for c in COLUNAS_DA_APP if c not in ("motivo_restricao", "meta_error_codes_seen")
)


def _colunas_de_update(cursor) -> tuple[str, ...]:
    """As colunas de `tenant_channels` em que `kamba_app` tem `UPDATE`."""
    cursor.execute(
        """
        SELECT column_name::text
          FROM information_schema.column_privileges
         WHERE table_schema = 'platform'
           AND table_name = 'tenant_channels'
           AND grantee = 'kamba_app'
           AND privilege_type = 'UPDATE'
         ORDER BY 1
        """
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestRestricaoDeCanal(ComBase):
    """O que o DDL da `0013` promete.

    `ComBase` da uma ligacao que **nunca confirma**: cada teste desfaz o que
    escreveu, e e por isso que o canal se semeia em cada um em vez de na classe.
    """

    def setUp(self) -> None:
        super().setUp()
        self.conexao = self.ligar("admin")
        self.cursor = self.conexao.cursor()
        self.tenant = factories.tenant(self.cursor)
        self.canal = factories.canal(self.cursor, self.tenant)

    def test_a_omissao_do_conjunto_e_vazia_e_nao_nula(self) -> None:
        """Um `NULL` aqui obrigava cada leitura a um `coalesce`."""
        self.cursor.execute(
            "SELECT motivo_restricao, meta_error_codes_seen "
            "FROM platform.tenant_channels WHERE id = %s",
            (self.canal,),
        )
        motivo, codigos = self.cursor.fetchone()
        # O `NULL` do motivo e o estado normal: este canal nao esta restrito.
        self.assertIsNone(motivo)
        self.assertEqual(list(codigos), [])

    def test_os_tres_motivos_do_dominio_passam(self) -> None:
        for motivo in MOTIVOS:
            with self.subTest(motivo=motivo):
                self.cursor.execute(
                    "UPDATE platform.tenant_channels SET motivo_restricao = %s "
                    "WHERE id = %s",
                    (motivo, self.canal),
                )

    def test_um_motivo_fora_do_dominio_e_recusado(self) -> None:
        """O `CHECK` e a ultima barreira; a lista do `contrato.ts` e a primeira."""
        self.assertErroSql(
            CHECK_VIOLATION,
            self.cursor,
            "UPDATE platform.tenant_channels SET motivo_restricao = 'cartao_sem_saldo' "
            "WHERE id = %s",
            (self.canal,),
        )

    def test_o_conjunto_aceita_o_tecto_e_recusa_um_a_mais(self) -> None:
        """O tecto transforma um crescimento sem fim num erro visivel."""
        no_tecto = list(range(1, TECTO_DE_CODIGOS + 1))
        self.cursor.execute(
            "UPDATE platform.tenant_channels SET meta_error_codes_seen = %s WHERE id = %s",
            (no_tecto, self.canal),
        )
        self.assertErroSql(
            CHECK_VIOLATION,
            self.cursor,
            "UPDATE platform.tenant_channels SET meta_error_codes_seen = %s WHERE id = %s",
            (no_tecto + [TECTO_DE_CODIGOS + 1], self.canal),
        )

    def test_o_conjunto_nao_aceita_nulo(self) -> None:
        self.assertErroSql(
            NOT_NULL_VIOLATION,
            self.cursor,
            "UPDATE platform.tenant_channels SET meta_error_codes_seen = NULL "
            "WHERE id = %s",
            (self.canal,),
        )

    def test_a_app_pode_escrever_as_duas_colunas_novas(self) -> None:
        """Sem isto, o adaptador falhava com `42501` numa coluna que o DDL tem.

        A verificacao e pelo catalogo e nao por uma escrita, porque o que se
        afirma e o **privilegio** e nao o efeito: uma escrita como
        administrador passava mesmo sem concessao nenhuma.
        """
        self.assertEqual(_colunas_de_update(self.cursor), COLUNAS_DA_APP)


class TestDowngradeDa0013(unittest.TestCase):
    """«Migracoes reversiveis — `downgrade` testado»."""

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
        self.tenants: list[str] = []

    def tearDown(self) -> None:
        try:
            # Cada processo do Alembic custa segundos: so quando a base nao
            # esta em `head` (o teste desceu, ou falhou a meio de descer).
            if not em_head():
                alembic_ok("upgrade", "head")
            for tenant in self.tenants:
                self.cursor.execute(
                    "DELETE FROM platform.tenant_channels WHERE tenant_id = %s",
                    (tenant,),
                )
                self.cursor.execute(
                    "DELETE FROM platform.tenants WHERE id = %s", (tenant,)
                )
        finally:
            self.conexao.close()

    def _colunas(self) -> tuple[str, ...]:
        self.cursor.execute(
            """
            SELECT column_name::text
              FROM information_schema.columns
             WHERE table_schema = 'platform' AND table_name = 'tenant_channels'
               AND column_name IN ('motivo_restricao', 'meta_error_codes_seen')
             ORDER BY 1
            """
        )
        return tuple(linha[0] for linha in self.cursor.fetchall())

    def test_desce_com_linhas_marcadas_e_sobe_outra_vez(self) -> None:
        """Desce **sem recusar**, e a razao esta no `docstring` da revisao.

        O que se perde e o motivo de uma restricao e um conjunto de codigos de
        diagnostico, e os dois reconstroem-se do proximo `statuses`. E a
        diferenca face ao `downgrade` da `0010`, que recusa porque apaga o
        registo do que se enviou e cobrou.
        """
        tenant = factories.tenant(self.cursor)
        self.tenants.append(tenant)
        canal = factories.canal(self.cursor, tenant)
        self.cursor.execute(
            "UPDATE platform.tenant_channels "
            "SET motivo_restricao = 'payment_method', "
            "    meta_error_codes_seen = ARRAY[131049, 130429] "
            "WHERE id = %s",
            (canal,),
        )
        self.assertEqual(
            self._colunas(), ("meta_error_codes_seen", "motivo_restricao")
        )

        alembic_ok("downgrade", "0012")
        # As duas colunas desapareceram, e a linha do canal **ficou**.
        self.assertEqual(self._colunas(), ())
        self.cursor.execute(
            "SELECT count(*) FROM platform.tenant_channels WHERE id = %s", (canal,)
        )
        self.assertEqual(self.cursor.fetchone()[0], 1)
        # E o privilegio voltou a ser o da `0001`, exactamente. Sem isto, subir
        # outra vez deixava o `kamba_app` com uma concessao a menos.
        self.assertEqual(_colunas_de_update(self.cursor), COLUNAS_DA_0001)

        alembic_ok("upgrade", "head")
        self.assertEqual(
            self._colunas(), ("meta_error_codes_seen", "motivo_restricao")
        )
        self.assertEqual(_colunas_de_update(self.cursor), COLUNAS_DA_APP)
        # E a marca nao voltou: a coluna e nova e a omissao e a dela.
        self.cursor.execute(
            "SELECT motivo_restricao, meta_error_codes_seen "
            "FROM platform.tenant_channels WHERE id = %s",
            (canal,),
        )
        motivo, codigos = self.cursor.fetchone()
        self.assertIsNone(motivo)
        self.assertEqual(codigos, [])


if __name__ == "__main__":
    unittest.main()
