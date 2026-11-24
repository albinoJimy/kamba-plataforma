"""A revisao do guia na base contra a base: o estado do guia e a busca pelo numero (KAM-239).

O que so uma base prova, e por isso este ficheiro existe:

1. **O estado do guia** isola pelo tenant do caso (a receita de sementes do
   X-05 nao o cobre: ver `sementes.SEM_RECEITA_COM_RAZAO`), nao se apaga, e o
   `kamba_batch` so muda o estado (a volta dos 30 minutos).
2. **A busca pelo numero ligado** (a forma da D1-A do KAM-236): ve o guia de
   qualquer tenant, devolve **so** o caso e o tenant, devolve um so, e so o
   `kamba_app` a executa. E a politica `guia_busca` nao abre nada ao `kamba_app`.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    ComBase,
    alembic_ok,
    em_head,
)

RAIZ = Path(__file__).resolve().parents[2]
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_guia_na_base.py"))

CASO = "platform.onboarding_case"
GUIA = "platform.onboarding_guia"
VIOLACAO_DE_CHECK = "23514"
VIOLACAO_DE_FK = "23503"


def _hmac() -> bytes:
    return hashlib.sha256(uuid.uuid4().bytes).digest()


def _numero() -> str:
    """Um `phone_number_id` de ensaio: algarismos, como os da Meta, sem forma de telefone."""
    return "10" + str(uuid.uuid4().int)[:14]


class TestGuiaNaBase(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()

    def _caso(self) -> tuple[str, str]:
        self.admin.execute(
            f"INSERT INTO {CASO} (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, "
            "phone_enc, phone_hmac, device_hash) "
            "VALUES ('aguarda_es', 'convite', 'Loja de ensaio', 'moda', '\\x01', %s, '\\x02', %s, %s) "
            "RETURNING id::text, tenant_id::text",
            (_hmac(), _hmac(), _hmac()),
        )
        onb, tenant = self.admin.fetchone()
        return onb, tenant

    def _guia(self, onb: str, tenant: str, numero: str | None = None) -> None:
        self.admin.execute(f"INSERT INTO {GUIA} (onboarding_id, tenant_id) VALUES (%s, %s)", (onb, tenant))
        if numero is not None:
            self.admin.execute(
                f"UPDATE {GUIA} SET estado = 'es_concluido', phone_number_id = %s, waba_id = 'waba-ensaio', "
                "numero_ligado_at = clock_timestamp(), actualizado_at = clock_timestamp() WHERE onboarding_id = %s",
                (numero, onb),
            )

    def _como(self, papel: str, tenant: str | None) -> None:
        self.admin.execute("SAVEPOINT papel")
        self.admin.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.admin, tenant)

    def _de_volta(self) -> None:
        self.admin.execute("ROLLBACK TO SAVEPOINT papel")

    # ------------------------------------------------------------ o estado do guia

    def test_o_guia_isola_pelo_tenant_do_caso(self) -> None:
        onb, tenant = self._caso()
        self._como("kamba_app", tenant)
        self.admin.execute(f"INSERT INTO {GUIA} (onboarding_id, tenant_id) VALUES (%s, %s)", (onb, tenant))
        self.admin.execute(f"SELECT estado, numero_confirmado, sincronizado FROM {GUIA} WHERE onboarding_id = %s", (onb,))
        self.assertEqual([tuple(l) for l in self.admin.fetchall()], [("pre_voo", False, False)])
        factories.contexto(self.admin, str(uuid.uuid4()))
        self.admin.execute(f"SELECT count(*) FROM {GUIA} WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 0, "com o contexto de outro tenant, zero")
        self.admin.execute(f"UPDATE {GUIA} SET estado = 'iniciado' WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.rowcount, 0, "e nao muda o guia de outro")
        factories.contexto(self.admin, None)
        self.admin.execute(f"SELECT count(*) FROM {GUIA} WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 0, "sem contexto, zero")
        self._de_volta()
        onb_b, tenant_b = self._caso()
        self._como("kamba_app", tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.admin,
            f"INSERT INTO {GUIA} (onboarding_id, tenant_id) VALUES (%s, %s)", (onb_b, tenant_b),
        )
        self._de_volta()

    def test_o_guia_esta_preso_ao_caso_e_ao_tenant_dele(self) -> None:
        onb, _ = self._caso()
        self.admin.execute("SAVEPOINT fk")
        self.assertErroSql(
            VIOLACAO_DE_FK, self.admin,
            f"INSERT INTO {GUIA} (onboarding_id, tenant_id) VALUES (%s, %s)", (onb, str(uuid.uuid4())),
        )
        self.admin.execute("ROLLBACK TO SAVEPOINT fk")

    def test_o_guia_nao_se_apaga_e_o_estado_e_o_motivo_sao_fechados(self) -> None:
        onb, tenant = self._caso()
        self._guia(onb, tenant)
        self._como("kamba_app", tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.admin, f"DELETE FROM {GUIA} WHERE onboarding_id = %s", (onb,))
        self._de_volta()
        for coluna, valor in (("estado", "activo"), ("motivo", "outro")):
            with self.subTest(coluna=coluna):
                self.admin.execute("SAVEPOINT forma")
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, self.admin,
                    f"UPDATE {GUIA} SET {coluna} = %s WHERE onboarding_id = %s", (valor, onb),
                )
                self.admin.execute("ROLLBACK TO SAVEPOINT forma")

    def test_o_lote_ve_todos_os_tenants_e_so_muda_o_estado(self) -> None:
        onb, tenant = self._caso()
        self._guia(onb, tenant)
        self._como("kamba_batch", None)
        self.admin.execute(
            f"UPDATE {GUIA} SET estado = 'abandonado', actualizado_at = now() WHERE onboarding_id = %s", (onb,)
        )
        self.assertEqual(self.admin.rowcount, 1, "o abandono dos 30 minutos atravessa os tenants")
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.admin,
            f"UPDATE {GUIA} SET phone_number_id = 'outro' WHERE onboarding_id = %s", (onb,),
        )
        self._de_volta()
        self._como("kamba_batch", None)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.admin, f"DELETE FROM {GUIA} WHERE onboarding_id = %s", (onb,))
        self._de_volta()

    # ------------------------------------------------------------ a busca pelo numero

    def test_a_busca_ve_o_guia_de_outro_tenant_e_so_devolve_o_caso_e_o_tenant(self) -> None:
        onb, tenant = self._caso()
        numero = _numero()
        self._guia(onb, tenant, numero)
        self._como("kamba_app", str(uuid.uuid4()))
        self.admin.execute(f"SELECT count(*) FROM {GUIA} WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 0, "pela tabela, o guia de outro tenant nao se ve")
        self.admin.execute("SELECT * FROM platform.guia_caso_por_phone_number_id(%s)", (numero,))
        self.assertEqual([d[0] for d in self.admin.description], ["id", "tenant_id"])
        self.assertEqual([tuple(map(str, l)) for l in self.admin.fetchall()], [(onb, tenant)])
        self.admin.execute("SELECT count(*) FROM platform.guia_caso_por_phone_number_id(%s)", (_numero(),))
        self.assertEqual(self.admin.fetchone()[0], 0, "um numero que ninguem ligou, nada")
        self._de_volta()

    def test_dois_guias_com_o_mesmo_numero_devolvem_o_ultimo_a_liga_lo_e_nunca_um_preso(self) -> None:
        """O ultimo a **ligar** o numero, e nao o ultimo a mexer no guia (achado 2 da
        revisao adversarial): uma escrita qualquer no primeiro nao lhe devolve os
        sinais; e preso o segundo por numero divergente, voltam ao primeiro."""
        numero = _numero()
        primeiro, tenant_1 = self._caso()
        self._guia(primeiro, tenant_1, numero)
        segundo, tenant_2 = self._caso()
        self._guia(segundo, tenant_2, numero)
        busca = "SELECT id::text, tenant_id::text FROM platform.guia_caso_por_phone_number_id(%s)"
        self._como("kamba_app", None)
        self.admin.execute(busca, (numero,))
        self.assertEqual([tuple(l) for l in self.admin.fetchall()], [(segundo, tenant_2)])
        self._de_volta()
        # O primeiro mexe no guia depois (o pre-voo repetido): os sinais nao mudam de guia.
        self.admin.execute(
            f"UPDATE {GUIA} SET preflight_at = now(), actualizado_at = clock_timestamp() + interval '1 hour' "
            "WHERE onboarding_id = %s",
            (primeiro,),
        )
        self._como("kamba_app", None)
        self.admin.execute(busca, (numero,))
        self.assertEqual([tuple(l) for l in self.admin.fetchall()], [(segundo, tenant_2)])
        self._de_volta()
        # Preso o segundo, os sinais do numero voltam ao primeiro.
        self.admin.execute(
            f"UPDATE {GUIA} SET estado = 'falhado', motivo = 'numero_divergente' WHERE onboarding_id = %s", (segundo,)
        )
        self._como("kamba_app", None)
        self.admin.execute(busca, (numero,))
        self.assertEqual([tuple(l) for l in self.admin.fetchall()], [(primeiro, tenant_1)])
        self._de_volta()

    def test_so_o_kamba_app_executa_a_busca(self) -> None:
        for papel in ("kamba_batch", "kamba_identity", "kamba_audit"):
            with self.subTest(papel=papel):
                self._como(papel, None)
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, self.admin,
                    "SELECT * FROM platform.guia_caso_por_phone_number_id(%s)", ("1",),
                )
                self._de_volta()
        self.assertEqual(
            self.consultar(
                "SELECT p.proname::text, p.prosecdef, array_to_string(p.proconfig, ',') "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'platform' AND p.proname LIKE 'guia\\_%%' ORDER BY 1"
            ),
            [("guia_caso_por_phone_number_id", True, "search_path=pg_catalog, platform")],
        )

    def test_a_politica_da_busca_e_so_do_dono_so_de_leitura_e_so_com_a_variavel(self) -> None:
        self.assertEqual(
            self.consultar(
                "SELECT cmd::text, roles::text, qual FROM pg_policies "
                "WHERE tablename = 'onboarding_guia' AND policyname = 'guia_busca'"
            ),
            [("SELECT", "{kamba_migrator}", "(current_setting('app.guia_busca'::text, true) = 'on'::text)")],
        )
        onb, tenant = self._caso()
        numero = _numero()
        self._guia(onb, tenant, numero)
        self._como("kamba_app", None)
        self.admin.execute("SELECT set_config('app.guia_busca', 'on', true)")
        self.admin.execute(f"SELECT count(*) FROM {GUIA} WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 0, "a variavel ligada pela aplicacao nao lhe abre nada")
        self.admin.execute("SELECT count(*) FROM platform.guia_caso_por_phone_number_id(%s)", (numero,))
        self.admin.execute("SELECT current_setting('app.guia_busca', true)")
        self.assertEqual(self.admin.fetchone()[0], "off", "e a busca desliga-a ao sair")
        self._de_volta()

    def test_so_a_busca_le_o_guia_como_dono(self) -> None:
        """Pela razao do `test_so_as_cinco_buscas_leem_o_caso_como_dono` da
        revisao da inscricao na base: a variavel pode ser ligada pela aplicacao,
        e o que ela abriria era outra funcao `SECURITY DEFINER` do dono a ler o
        guia na mesma transaccao. Falha no dia em que houver uma."""
        self.assertEqual(
            self.consultar(
                "SELECT p.proname::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND p.prosrc ILIKE '%%onboarding_guia%%' ORDER BY 1"
            ),
            [("guia_caso_por_phone_number_id",)],
        )
        self.assertEqual(
            self.consultar(
                "SELECT c.relname::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind IN ('v', 'm') AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND pg_get_viewdef(c.oid) ILIKE '%%onboarding_guia%%' "
                "AND NOT coalesce('security_invoker=true' = ANY (c.reloptions), false) ORDER BY 1"
            ),
            [],
        )


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


class TestDowngradeDoGuiaNaBase(ComBase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro.
    """

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _objectos(self) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' AND tablename = 'onboarding_guia'")
            n = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'guia_caso_por_phone_number_id'")
            n += int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_policies WHERE policyname = 'guia_busca'")
            return n + int(c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _anterior())
        try:
            self.assertEqual(self._objectos(), 0)
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), 3)
