"""O estado do canal do painel do dono contra a base (KAM-190).

As tres consultas de `services/com/src/canal/vista.ts` e a dos avisos de T&S
(`SQL_SANCOES_DO_TENANT_APP`, do KAM-097), executadas **tal como estao escritas**
e **como `kamba_app`**, que e o papel com que o COM as corre. O que so a base
prova:

1. **Os privilegios chegam**: o `kamba_app` le as colunas que as quatro pedem —
   a `trust_level` so em quatro das nove, e a `ts_sanction` sem o motivo interno.
   Uma coluna a mais numa consulta era um `42501` em producao, e a bateria do COM
   (`services/com/tests/canal.vista.test.ts`) nao o ve.
2. **O tenant e o do contexto**: com o contexto de A, nada de B sai — nem o canal,
   nem a sincronizacao, nem o nivel, nem as sancoes.
3. **A escolha do canal e a do texto**: o da plataforma (Fluxo B) nao entra, e
   entre dois o ligado vem primeiro.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from tests import factories
from tests.base import ComBase, ConsultaDoTypeScript
from tests.test_kyc_schema import caso as novo_caso
from tests.test_kyc_schema import verificacao

RAIZ = Path(__file__).resolve().parents[2]
VISTA_TS = RAIZ / "services" / "com" / "src" / "canal" / "vista.ts"
TRUST_TS = RAIZ / "packages" / "core-ts" / "src" / "trust" / "sql.ts"

SQL_CANAL = ConsultaDoTypeScript("SQL_CANAL_DO_PAINEL", VISTA_TS)
SQL_SINCRONIZACAO = ConsultaDoTypeScript("SQL_SINCRONIZACAO_DO_CANAL", VISTA_TS)
SQL_NIVEL = ConsultaDoTypeScript("SQL_NIVEL_DO_TENANT", VISTA_TS)
SQL_SANCOES = ConsultaDoTypeScript("SQL_SANCOES_DO_TENANT_APP", TRUST_TS)
SQL_GRAVAR_SANCAO = ConsultaDoTypeScript("SQL_GRAVAR_SANCAO", TRUST_TS)


class TestCanalDoPainel(ComBase):
    """Uma transaccao do administrador que nunca confirma; o `kamba_app` por `SET LOCAL ROLE`."""

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.ligar("admin").cursor()
        self.a = self._tenant(nivel=1, tecto=5_000_000)
        self.b = self._tenant(nivel=0, tecto=2_000_000)
        self.canal_a = factories.canal(self.cursor, self.a, estado="restrito", quality_rating="amarelo", messaging_limit="TIER_250")
        factories.canal(self.cursor, self.b, estado="ativo", quality_rating="verde", messaging_limit="TIER_1K")
        self.cursor.execute(
            "INSERT INTO platform.channel_coexistence (tenant_id, channel_id, estado, prazo_em) "
            "VALUES (%s, %s, 'a_sincronizar', now() + interval '1 day')",
            (self.a, self.canal_a),
        )
        self._sancao(self.a, "aviso", "conduta_em_analise")
        # O primeiro passo, como o de A: o *trigger* da `ts_sanction` recusa saltar
        # passos da escada sem justificacao (23514).
        self._sancao(self.b, "aviso", "conduta_em_analise")
        factories.contexto(self.cursor, None)

    def _tenant(self, nivel: int, tecto: int) -> str:
        tenant = factories.tenant(self.cursor)
        caso, _ = novo_caso(self.cursor, tenant_id=tenant, fase="activo")
        verificacao(self.cursor, caso, tenant, resultado="k1_ok")
        self.cursor.execute(
            "INSERT INTO platform.trust_level (tenant_id, nivel, tecto_pedido_minor, motivo, actor, versao_config) "
            "VALUES (%s, %s, %s, 'k1_completo', 'sistema:x', %s)",
            (tenant, nivel, tecto, factories.VERSAO_DA_CONFIGURACAO_DE_ENSAIO),
        )
        return tenant

    def _sancao(self, tenant: str, passo: str, motivo: str) -> None:
        self.cursor.execute(
            SQL_GRAVAR_SANCAO.sql,
            SQL_GRAVAR_SANCAO.args(
                tenant, f"auto:{passo}:{uuid.uuid4()}", passo, "automatica", "risco=35;limiar=30", motivo,
                "sistema:1.0.0", "risco_ts>=30", "[]", None, None, None, None,
            ),
        )

    def como_app(self, tenant: str) -> None:
        self.cursor.execute("RESET ROLE")
        factories.contexto(self.cursor, tenant)
        self.cursor.execute("SET LOCAL ROLE kamba_app")

    def linhas(self, consulta: ConsultaDoTypeScript, *argumentos) -> list[dict]:
        self.cursor.execute(consulta.sql, consulta.args(*argumentos))
        colunas = [d[0] for d in self.cursor.description or []]
        return [dict(zip(colunas, linha)) for linha in self.cursor.fetchall()]

    def test_o_kamba_app_le_as_quatro_so_do_seu_tenant(self) -> None:
        self.como_app(self.a)
        canal = self.linhas(SQL_CANAL, self.a)
        self.assertEqual(len(canal), 1)
        self.assertEqual(
            (canal[0]["channel_id"], canal[0]["estado"], canal[0]["quality_rating"], canal[0]["messaging_limit"]),
            (self.canal_a, "restrito", "amarelo", "TIER_250"),
        )
        self.assertEqual(
            [l["estado"] for l in self.linhas(SQL_SINCRONIZACAO, self.a, self.canal_a)], ["a_sincronizar"]
        )
        nivel = self.linhas(SQL_NIVEL, self.a)
        self.assertEqual([(l["nivel"], int(l["tecto_pedido_minor"]), l["currency"]) for l in nivel], [(1, 5_000_000, "AOA")])
        self.assertEqual([l["motivo_publico"] for l in self.linhas(SQL_SANCOES, self.a)], ["conduta_em_analise"])

    def test_com_o_contexto_de_a_o_tenant_de_b_nao_devolve_nada(self) -> None:
        """O `tenant_id = $1` do texto e a RLS: o B pedido com o contexto de A da zero linhas."""
        self.como_app(self.a)
        self.assertEqual(self.linhas(SQL_CANAL, self.b), [])
        self.assertEqual(self.linhas(SQL_NIVEL, self.b), [])
        self.assertEqual(self.linhas(SQL_SANCOES, self.b), [])

    def test_a_sincronizacao_e_a_do_canal_pedido(self) -> None:
        """O `channel_id = $2`: a sincronizacao de **outro** canal do mesmo tenant nao sai.

        Ha uma por canal (`channel_coexistence_canal_uq`), pelo que e este o
        predicado que decide. Com ele apagado, a consulta devolvia as duas.
        Achado 8 da revisao adversarial.
        """
        outro = factories.canal(self.cursor, self.a, estado="desligado")
        self.cursor.execute(
            "INSERT INTO platform.channel_coexistence (tenant_id, channel_id, estado, prazo_em) "
            "VALUES (%s, %s, 'falhado', now() + interval '1 day')",
            (self.a, outro),
        )
        self.como_app(self.a)
        self.assertEqual(
            [l["estado"] for l in self.linhas(SQL_SINCRONIZACAO, self.a, self.canal_a)], ["a_sincronizar"]
        )
        self.assertEqual([l["estado"] for l in self.linhas(SQL_SINCRONIZACAO, self.a, outro)], ["falhado"])

    def test_o_canal_da_plataforma_nao_e_o_do_dono_e_o_ligado_vem_primeiro(self) -> None:
        self.cursor.execute("RESET ROLE")
        factories.canal(self.cursor, self.a, estado="desligado", quality_rating="vermelho")
        plataforma = factories.canal(self.cursor, self.a, estado="ativo", origem="plataforma")
        self.como_app(self.a)
        canal = self.linhas(SQL_CANAL, self.a)
        self.assertEqual(len(canal), 1)
        self.assertNotEqual(canal[0]["channel_id"], plataforma)
        # O restrito ganha ao desligado: o `CASE` da ordem.
        self.assertEqual(canal[0]["estado"], "restrito")
