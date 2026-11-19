"""O canal do dono guardado contra a base: tenants.owner_channel_wa (KAM-216).

Decisao do fundador de 2026-11-19 (opcao C): o numero da loja nao se guarda;
guarda-se so o booleano, calculado pelo `onboarding-web` a cada troca de
telefone. O que so uma base prova, e por isso este ficheiro existe:

1. **A coluna escreve-a so a porta**, na transaccao que move o papel: a troca
   com o terceiro argumento escreve-o; o provisionamento, que chama com dois,
   deixa-o nulo; a reentrega idempotente nao o apaga.
2. **Nenhum papel de aplicacao a escreve**: o `kamba_app` e o `kamba_identity`
   recebem `42501`; so o `kamba_batch` (o lote) mantem o `UPDATE` de tabela da
   `0001`. O `kamba_identity` continua sem ler a `tenants` (KAM-008): quem le a
   coluna e o COM, como `kamba_app` (`test_canal_do_painel.py`).
3. **O `downgrade`** repoe a porta de dois argumentos da `0070` e larga a
   coluna, e o regresso a `head`.

O comportamento ponta a ponta — a troca pelo `onboarding-web` e a leitura do
painel — mede-se em `packages/core-ts/tests_bd/dono.bd.test.ts`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests.test_canal_do_dono_schema import ComDono, _papel

RAIZ = Path(__file__).resolve().parents[2]
#: Por *glob* e nao pelo numero: o numero e *provisorio* e da-se na integracao.
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_canal_do_dono_guardado.py"))

TROCA = "SELECT platform.definir_dono(%s, 'troca_de_telefone', %s)"


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


class ComCanal(ComDono):
    def trocar(self, tenant: str, contacto: str, canal: bool | None):
        _papel(self.cur, "kamba_identity", tenant)
        self.cur.execute(TROCA, (contacto, canal))
        devolvido = self.cur.fetchone()[0]
        _papel(self.cur, None)
        return None if devolvido is None else str(devolvido)

    def canal(self, tenant: str) -> bool | None:
        self.cur.execute("SELECT owner_channel_wa FROM platform.tenants WHERE id = %s", (tenant,))
        return self.cur.fetchone()[0]

    def com_dono(self) -> tuple[str, str]:
        tenant = factories.tenant(self.cur)
        dono = factories.contacto(self.cur, tenant)
        self.definir(tenant, dono)
        return tenant, dono


class TestEscritaPelaPorta(ComCanal):
    def test_o_provisionamento_deixa_a_coluna_nula(self) -> None:
        tenant, _ = self.com_dono()
        self.assertIsNone(self.canal(tenant))

    def test_a_troca_escreve_o_canal_do_dono_novo_com_o_dono(self) -> None:
        for canal in (True, False):
            with self.subTest(canal=canal):
                tenant, antigo = self.com_dono()
                novo = factories.contacto(self.cur, tenant)
                self.assertEqual(self.trocar(tenant, novo, canal), antigo)
                self.assertIs(self.canal(tenant), canal)
                self.assertEqual(self.dono_do_tenant(tenant), novo)

    def test_trocar_outra_vez_reescreve_o_canal(self) -> None:
        tenant, antigo = self.com_dono()
        novo = factories.contacto(self.cur, tenant)
        self.trocar(tenant, novo, True)
        self.trocar(tenant, antigo, False)
        self.assertIs(self.canal(tenant), False)

    def test_a_reentrega_do_provisionamento_nao_apaga_o_canal(self) -> None:
        """A reentrega chama com dois argumentos (nulo) e o contacto ja e o dono:
        devolve sem tocar em nada, e o valor da troca fica."""
        tenant, _ = self.com_dono()
        novo = factories.contacto(self.cur, tenant)
        self.trocar(tenant, novo, True)
        self.assertIsNone(self.definir(tenant, novo))
        self.assertIs(self.canal(tenant), True)

    def test_uma_troca_para_o_dono_que_ja_e_dono_nao_muda_o_canal(self) -> None:
        tenant, _ = self.com_dono()
        novo = factories.contacto(self.cur, tenant)
        self.trocar(tenant, novo, True)
        self.assertIsNone(self.trocar(tenant, novo, False))
        self.assertIs(self.canal(tenant), True)

    def test_a_porta_e_uma_so_com_o_terceiro_argumento(self) -> None:
        self.cur.execute(
            "SELECT pg_get_function_identity_arguments(p.oid) FROM pg_proc p "
            "WHERE p.proname = 'definir_dono'"
        )
        self.assertEqual(
            [r[0] for r in self.cur.fetchall()],
            ["p_contact_id uuid, p_origem text, p_owner_channel_wa boolean"],
        )


class TestNinguemEscrevePorFora(ComCanal):
    def test_so_o_lote_tem_update_na_coluna(self) -> None:
        """Nenhum papel de aplicacao a escreve; o `kamba_batch` mantem o `UPDATE`
        de tabela da `0001`, o mesmo com que o lote escreve o `owner_contact_id`."""
        self.cur.execute(
            "SELECT array_agg(r.rolname::text ORDER BY r.rolname) FROM pg_roles r "
            "WHERE r.rolname LIKE %s AND r.rolname <> 'kamba_migrator' "
            "AND has_column_privilege(r.oid, 'platform.tenants', 'owner_channel_wa', 'UPDATE')",
            ("kamba\\_%",),
        )
        self.assertEqual(self.cur.fetchone()[0], ["kamba_batch"])

    def test_a_identidade_e_a_aplicacao_recebem_42501_no_update(self) -> None:
        tenant, _ = self.com_dono()
        for papel in ("kamba_identity", "kamba_app"):
            with self.subTest(papel=papel):
                _papel(self.cur, papel, tenant)
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE,
                    self.cur,
                    "UPDATE platform.tenants SET owner_channel_wa = true WHERE id = %s",
                    (tenant,),
                )
                _papel(self.cur, None)
        self.assertIsNone(self.canal(tenant))

    def test_a_identidade_continua_sem_ler_a_tenants(self) -> None:
        """A invariante do KAM-008: quem le o canal do dono e o COM, como `kamba_app`."""
        self.cur.execute(
            "SELECT has_column_privilege('kamba_identity', 'platform.tenants', 'owner_channel_wa', 'SELECT')"
        )
        self.assertIs(self.cur.fetchone()[0], False)


class TestDowngradeDoCanalGuardado(unittest.TestCase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
    """

    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _objectos(self) -> tuple[int, list[str]]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'platform' "
                "AND table_name = 'tenants' AND column_name = 'owner_channel_wa'"
            )
            colunas = int(c.fetchone()[0])
            c.execute(
                "SELECT pg_get_function_identity_arguments(p.oid) FROM pg_proc p "
                "WHERE p.proname = 'definir_dono'"
            )
            assinaturas = [r[0] for r in c.fetchall()]
            return colunas, assinaturas
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        tres = (1, ["p_contact_id uuid, p_origem text, p_owner_channel_wa boolean"])
        dois = (0, ["p_contact_id uuid, p_origem text"])
        self.assertEqual(self._objectos(), tres)
        alembic_ok("downgrade", _anterior())
        self.assertEqual(self._objectos(), dois)
        alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), tres)


if __name__ == "__main__":
    unittest.main()
