"""A revisao da inscricao na base contra a base: as buscas, o OTP, os contadores e as revogacoes (KAM-236).

O que so uma base prova, e por isso este ficheiro existe:

1. **As cinco buscas do registo** (decisao do fundador de 2026-11-21, D1-A):
   veem o caso de qualquer tenant, devolvem **so** o caso e o tenant, deixam de
   ver um caso morto, e so o `kamba_app` as executa. E a politica
   `registo_busca` nao abre nada ao `kamba_app`.
2. **O desafio do OTP** isola pelo tenant do caso (a receita de sementes do X-05
   nao o cobre: ver `sementes.SEM_RECEITA_COM_RAZAO`).
3. **Os contadores** sao so do `kamba_app`; **as revogacoes** nao se apagam e
   sao uma sessao ou um corte; **a chave de idempotencia** e unica e nao muda.
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
    sqlstate,
)

RAIZ = Path(__file__).resolve().parents[2]
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_inscricao_na_base.py"))

CASO = "platform.onboarding_case"
OTP = "platform.onboarding_otp"
CONTADOR = "platform.onboarding_contador"
REVOGACAO = "platform.painel_revogacao"
VIOLACAO_DE_UNICIDADE = "23505"
VIOLACAO_DE_CHECK = "23514"
HMAC_HEX = "a" * 64


def _hmac() -> bytes:
    return hashlib.sha256(uuid.uuid4().bytes).digest()


class TestInscricaoNaBase(ComBase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()

    def _caso(self, *, fase: str = "registo", chave: str | None = None) -> tuple[str, str, bytes, bytes, bytes]:
        nif, telefone, dispositivo = _hmac(), _hmac(), _hmac()
        self.admin.execute(
            f"INSERT INTO {CASO} (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, "
            "phone_enc, phone_hmac, device_hash, chave_idem) "
            "VALUES (%s, 'convite', 'Loja de ensaio', 'moda', '\\x01', %s, '\\x02', %s, %s, %s) "
            "RETURNING id::text, tenant_id::text",
            (fase, nif, telefone, dispositivo, chave),
        )
        onb, tenant = self.admin.fetchone()
        return onb, tenant, nif, telefone, dispositivo

    def _como(self, papel: str, tenant: str | None) -> None:
        self.admin.execute("SAVEPOINT papel")
        self.admin.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.admin, tenant)

    def _de_volta(self) -> None:
        self.admin.execute("ROLLBACK TO SAVEPOINT papel")

    # ------------------------------------------------------------ as buscas

    def test_as_buscas_veem_o_caso_de_outro_tenant_e_so_devolvem_o_caso_e_o_tenant(self) -> None:
        chave = f"kam-236-{uuid.uuid4()}"
        onb, tenant, nif, telefone, dispositivo = self._caso(chave=chave)
        self._como("kamba_app", str(uuid.uuid4()))
        self.admin.execute(f"SELECT count(*) FROM {CASO} WHERE id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 0, "pela tabela, o caso de outro tenant nao se ve")
        self.admin.execute("SELECT * FROM platform.registo_caso_vivo_por_nif(%s)", (nif.hex(),))
        self.assertEqual([d[0] for d in self.admin.description], ["id", "tenant_id"])
        self.assertEqual([tuple(map(str, l)) for l in self.admin.fetchall()], [(onb, tenant)])
        self.admin.execute("SELECT * FROM platform.registo_casos_vivos_por_telefone(%s)", (telefone.hex(),))
        self.assertEqual([d[0] for d in self.admin.description], ["id", "tenant_id"])
        self.assertEqual([tuple(map(str, l)) for l in self.admin.fetchall()], [(onb, tenant)])
        self.admin.execute("SELECT * FROM platform.registo_caso_por_chave(%s)", (chave,))
        self.assertEqual([tuple(map(str, l)) for l in self.admin.fetchall()], [(onb, tenant)])
        self.admin.execute("SELECT platform.registo_tenant_do_caso(%s)::text", (onb,))
        self.assertEqual(self.admin.fetchone()[0], tenant)
        self.admin.execute(
            "SELECT platform.registo_contar_por_dispositivo(%s, now() - interval '1 hour')", (dispositivo.hex(),)
        )
        self.assertEqual(self.admin.fetchone()[0], 1)
        self._de_volta()

    def test_um_caso_morto_nao_se_encontra_pelo_nif_nem_pelo_telefone(self) -> None:
        _, _, nif, telefone, _ = self._caso(fase="abandonado")
        self._como("kamba_app", None)
        self.admin.execute("SELECT count(*) FROM platform.registo_caso_vivo_por_nif(%s)", (nif.hex(),))
        self.assertEqual(self.admin.fetchone()[0], 0)
        self.admin.execute("SELECT count(*) FROM platform.registo_casos_vivos_por_telefone(%s)", (telefone.hex(),))
        self.assertEqual(self.admin.fetchone()[0], 0)
        self._de_volta()

    def test_so_o_kamba_app_executa_as_buscas(self) -> None:
        for papel in ("kamba_batch", "kamba_identity", "kamba_audit"):
            with self.subTest(papel=papel):
                self._como(papel, None)
                self.assertErroSql(
                    PRIVILEGIO_INSUFICIENTE, self.admin,
                    "SELECT * FROM platform.registo_caso_vivo_por_nif(%s)", (HMAC_HEX,),
                )
                self._de_volta()
        linhas = self.consultar(
            "SELECT p.proname::text, p.prosecdef, array_to_string(p.proconfig, ',') "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'platform' AND p.proname LIKE 'registo\\_%%' ORDER BY 1"
        )
        self.assertEqual(
            linhas,
            [
                ("registo_caso_por_chave", True, "search_path=pg_catalog, platform"),
                ("registo_caso_vivo_por_nif", True, "search_path=pg_catalog, platform"),
                ("registo_casos_vivos_por_telefone", True, "search_path=pg_catalog, platform"),
                ("registo_contar_por_dispositivo", True, "search_path=pg_catalog, platform"),
                ("registo_tenant_do_caso", True, "search_path=pg_catalog, platform"),
            ],
        )

    def test_a_politica_das_buscas_e_so_do_dono_so_de_leitura_e_so_com_a_variavel(self) -> None:
        self.assertEqual(
            self.consultar(
                "SELECT cmd::text, roles::text, qual FROM pg_policies "
                "WHERE tablename = 'onboarding_case' AND policyname = 'registo_busca'"
            ),
            [("SELECT", "{kamba_migrator}",
              "(current_setting('app.registo_busca'::text, true) = 'on'::text)")],
        )
        # A variavel ligada a mao pelo `kamba_app` nao abre nada: a politica nao e dele.
        # E uma busca desliga-a ao sair, mesmo que a aplicacao a tenha ligado.
        onb, *_ = self._caso()
        self._como("kamba_app", None)
        self.admin.execute("SELECT set_config('app.registo_busca', 'on', true)")
        self.admin.execute(f"SELECT count(*) FROM {CASO} WHERE id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 0)
        self.admin.execute("SELECT platform.registo_tenant_do_caso(%s)", (onb,))
        self.admin.execute("SELECT current_setting('app.registo_busca', true)")
        self.assertEqual(self.admin.fetchone()[0], "off")
        self._de_volta()

    def test_so_as_cinco_buscas_leem_o_caso_como_dono(self) -> None:
        """A variavel que a politica le pode ser ligada pela aplicacao (nao lhe
        abre nada). O que ela abriria e **outra** funcao `SECURITY DEFINER` do
        dono a ler a `onboarding_case` na mesma transaccao. Este ensaio falha no
        dia em que houver uma, para que alguem decida antes."""
        self.assertEqual(
            self.consultar(
                "SELECT p.proname::text FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog', 'information_schema') "
                "AND p.prosrc ILIKE '%%onboarding_case%%' ORDER BY 1"
            ),
            [
                ("registo_caso_por_chave",),
                ("registo_caso_vivo_por_nif",),
                ("registo_casos_vivos_por_telefone",),
                ("registo_contar_por_dispositivo",),
                ("registo_tenant_do_caso",),
            ],
        )

    # ------------------------------------------------------------ o desafio do OTP

    def test_o_desafio_isola_pelo_tenant_do_caso(self) -> None:
        onb, tenant, *_ = self._caso()
        outro = str(uuid.uuid4())
        self._como("kamba_app", tenant)
        self.admin.execute(
            f"INSERT INTO {OTP} (onboarding_id, tenant_id, codigo_hmac, expira_at, tentativas) "
            "VALUES (%s, %s, %s, now() + interval '5 minutes', 0)",
            (onb, tenant, HMAC_HEX),
        )
        self.admin.execute(f"SELECT count(*) FROM {OTP} WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 1)
        factories.contexto(self.admin, outro)
        self.admin.execute(f"SELECT count(*) FROM {OTP} WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 0, "com o contexto de outro tenant, zero")
        self.admin.execute(f"UPDATE {OTP} SET tentativas = 9 WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.rowcount, 0, "e nao muda o desafio de outro")
        factories.contexto(self.admin, None)
        self.admin.execute(f"SELECT count(*) FROM {OTP} WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.fetchone()[0], 0, "sem contexto, zero")
        self._de_volta()
        onb_b, tenant_b, *_ = self._caso()
        self._como("kamba_app", tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.admin,
            f"INSERT INTO {OTP} (onboarding_id, tenant_id, codigo_hmac, expira_at) "
            "VALUES (%s, %s, %s, now())",
            (onb_b, tenant_b, HMAC_HEX),
        )
        self._de_volta()

    def test_o_desafio_nao_se_apaga_marca_se_usado(self) -> None:
        onb, tenant, *_ = self._caso()
        self._como("kamba_app", tenant)
        self.admin.execute(
            f"INSERT INTO {OTP} (onboarding_id, tenant_id, codigo_hmac, expira_at) "
            "VALUES (%s, %s, %s, now() + interval '5 minutes')",
            (onb, tenant, HMAC_HEX),
        )
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.admin, f"DELETE FROM {OTP} WHERE onboarding_id = %s", (onb,))
        self.admin.execute(f"UPDATE {OTP} SET usado_at = now() WHERE onboarding_id = %s", (onb,))
        self.assertEqual(self.admin.rowcount, 1)
        self._de_volta()

    def test_o_desafio_guarda_so_o_hmac(self) -> None:
        onb, tenant, *_ = self._caso()
        self.admin.execute("SAVEPOINT forma")
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.admin,
            f"INSERT INTO {OTP} (onboarding_id, tenant_id, codigo_hmac, expira_at) VALUES (%s, %s, '123456', now())",
            (onb, tenant),
        )
        self.admin.execute("ROLLBACK TO SAVEPOINT forma")

    # ------------------------------------------------------------ contadores, revogacoes e a chave

    def test_os_contadores_escreve_os_a_aplicacao_e_apaga_os_o_lote(self) -> None:
        chave = f"ensaio:{uuid.uuid4()}"
        self._como("kamba_app", None)
        self.admin.execute(
            f"INSERT INTO {CONTADOR} (chave, instantes, actualizado_at) "
            "VALUES (%s, ARRAY[now() - interval '2 days'], now() - interval '2 days')",
            (chave,),
        )
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.admin, f"DELETE FROM {CONTADOR} WHERE chave = %s", (chave,))
        self.admin.execute("RELEASE SAVEPOINT papel")
        self.admin.execute("RESET ROLE")
        # A purga e a da retencao, como lote (`CAMINHO_CONTADORES_DO_REGISTO`).
        self._como("kamba_batch", None)
        self.admin.execute(
            f"DELETE FROM {CONTADOR} WHERE actualizado_at < now() - interval '25 hours' AND chave = %s", (chave,)
        )
        self.assertEqual(self.admin.rowcount, 1)
        self._de_volta()

    def test_as_revogacoes_nao_se_apagam_e_sao_uma_sessao_ou_um_corte(self) -> None:
        tenant = str(uuid.uuid4())
        self._como("kamba_app", tenant)
        self.admin.execute(
            f"INSERT INTO {REVOGACAO} (tenant_id, sid, expira_at) VALUES (%s, %s, now())", (tenant, str(uuid.uuid4()))
        )
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.admin, f"DELETE FROM {REVOGACAO} WHERE tenant_id = %s", (tenant,))
        self._de_volta()
        self.admin.execute("SAVEPOINT alvo")
        self.assertErroSql(
            VIOLACAO_DE_CHECK, self.admin,
            f"INSERT INTO {REVOGACAO} (tenant_id, sid, ate, expira_at) VALUES (%s, %s, 1, now())",
            (tenant, str(uuid.uuid4())),
        )
        self.admin.execute("ROLLBACK TO SAVEPOINT alvo")

    def test_a_chave_de_idempotencia_e_unica_e_nao_muda(self) -> None:
        chave = f"kam-236-{uuid.uuid4()}"
        onb, tenant, *_ = self._caso(chave=chave)
        self.admin.execute("SAVEPOINT unica")
        import pg8000.dbapi

        with self.assertRaises(pg8000.dbapi.DatabaseError) as erro:
            self._caso(chave=chave)
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_UNICIDADE)
        self.admin.execute("ROLLBACK TO SAVEPOINT unica")
        self._como("kamba_app", tenant)
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, self.admin,
            f"UPDATE {CASO} SET chave_idem = %s WHERE id = %s", (f"kam-236-{uuid.uuid4()}", onb),
        )
        self._de_volta()


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


class TestDowngradeDaInscricaoNaBase(ComBase):
    """Desce pelo numero da revisao anterior, lido da revisao, e volta.

    **Nao exige `em_head()` no meio**, pela licao do KAM-089: com outra revisao
    por cima, o Alembic desce-a primeiro. Herda o arranque do `ComBase` (os
    papeis do `bootstrap` e a base em `head`): corrida sozinha, sem outra classe
    antes, o `kamba_migrator` ainda nao tinha senha.
    """

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _objectos(self) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                "AND tablename IN ('onboarding_otp', 'onboarding_contador', 'painel_revogacao')"
            )
            n = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname LIKE 'registo!_%%' ESCAPE '!'")
            n += int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_policies WHERE policyname = 'registo_busca'")
            n += int(c.fetchone()[0])
            c.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'platform' "
                "AND table_name = 'onboarding_case' AND column_name = 'chave_idem'"
            )
            return n + int(c.fetchone()[0])
        finally:
            conexao.close()

    def test_desce_e_volta(self) -> None:
        alembic_ok("downgrade", _anterior())
        try:
            self.assertEqual(self._objectos(), 0)
        finally:
            alembic_ok("upgrade", "head")
        self.assertEqual(self._objectos(), 10)
