"""A revisao `social_do_dono` (KAM-121): a finalidade e a descida.

Duas coisas, e a segunda e a que a revisao tem de ter medida:

1. o dominio de `tenant_destinations.purpose` tem a `classificacao_de_conteudo`
   (pelo precedente da opcao B do KAM-230: um tratamento, uma finalidade), e o
   do `screening_decision.sujeito_tipo` tem o `conteudo`;
2. o `downgrade` **recusa-se** com um destino `classificacao_de_conteudo` (e o
   registo de uma decisao de transferencia) e deixa a base como estava; sem ele
   desce: larga as tres tabelas, **apaga so as decisoes `conteudo`**, repoe os
   dominios da `0078` e o *trigger* da `screening_decision`, e volta a subir.

A revisao descobre-se por *glob* e o `down_revision` le-se do ficheiro: o
numero e o da fila de integracao, e nenhum literal daqui muda com ele. **Nenhum
ensaio exige a cabeca depois de descer**, pela licao da `foto_de_produtos`: com
outra revisao por cima, o Alembic desce-a primeiro.
"""

from __future__ import annotations

import re
import unittest
import uuid
from pathlib import Path

import ligacao
from tests import factories
from tests import test_screening_schema as screening
from tests.base import (
    VIOLACAO_DE_CHECK,
    ComBase,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

RAIZ = Path(__file__).resolve().parents[2]
VERSOES = RAIZ / "db" / "migrations" / "versions"
DESTINOS = "platform.tenant_destinations"
FINALIDADE = "classificacao_de_conteudo"
TABELAS = ("brand_profile", "content_calendar", "content_items")

#: As dezasseis da `finalidade_das_condicoes`, a que o `downgrade` volta. Por
#: extenso: o oraculo nao se le da revisao que mede.
FINALIDADES_DA_0078 = (
    "alojamento", "canal", "classificacao_de_catalogo", "classificacao_de_condicoes",
    "conversa", "copias_de_seguranca", "embeddings", "entrega_de_conteudo", "facturacao",
    "imagem", "observabilidade", "otp_e_avisos_de_servico", "pagamentos", "segredos",
    "transcricao", "visao",
)

SQL_DESTINO = (
    f"INSERT INTO {DESTINOS} (tenant_id, provider, country, purpose, status, "
    "retencao_zero, sem_treino) VALUES (%s, 'anthropic', 'US', %s, 'pendente', false, false)"
)


def _abaixo() -> str:
    [ficheiro] = list(VERSOES.glob("*_social_do_dono.py"))
    achado = re.search(r'^down_revision = "(\d{4})"$', ficheiro.read_text(encoding="utf-8"), re.M)
    assert achado, "a revisao nao declara down_revision"
    return achado.group(1)


class TestOsDominios(ComBase):
    def test_a_finalidade_e_o_sujeito_do_conteudo_sao_aceites(self) -> None:
        admin = self.ligar("admin").cursor()
        self.assertIn(FINALIDADE, screening._dominio(admin, "tenant_destinations_purpose_ck"))
        self.assertIn("conteudo", screening._dominio(admin, "screening_decision_sujeito_tipo_ck"))
        tenant = factories.tenant(admin)
        admin.execute(SQL_DESTINO, (tenant, FINALIDADE))
        self.assertEqual(admin.rowcount, 1)
        self.assertErroSql(VIOLACAO_DE_CHECK, admin, SQL_DESTINO, (tenant, "classificacao_do_conteudo"))
        self.assertErroSql(VIOLACAO_DE_CHECK, admin, SQL_DESTINO, (tenant, "conteudo"))


class TestDowngradeDoSocialDoDono(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        exigir_base_descartavel()
        if not em_head():
            alembic_ok("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if not em_head():
            alembic_ok("upgrade", "head")

    def _admin(self, sql: str, parametros: tuple = ()) -> list[tuple]:
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            cursor.execute(sql, parametros)
            linhas = [tuple(l) for l in cursor.fetchall()] if cursor.description else []
            conexao.commit()
            return linhas
        finally:
            conexao.close()

    def _tabelas(self) -> tuple[str, ...]:
        linhas = self._admin(
            "SELECT relname FROM pg_class WHERE relnamespace = 'platform'::regnamespace "
            "AND relkind = 'r' AND relname = ANY(%s) ORDER BY 1",
            (list(TABELAS),),
        )
        return tuple(n for (n,) in linhas)

    def _dominio(self, restricao: str) -> tuple[str, ...]:
        conexao = ligacao.ligar("admin")
        try:
            return screening._dominio(conexao.cursor(), restricao)
        finally:
            conexao.close()

    def _decisoes(self, tenant: str) -> dict[str, int]:
        conexao = ligacao.ligar("app")
        try:
            c = conexao.cursor()
            factories.contexto(c, tenant)
            c.execute(
                "SELECT sujeito_tipo, count(*) FROM platform.screening_decision GROUP BY sujeito_tipo"
            )
            return {tipo: int(n) for tipo, n in c.fetchall()}
        finally:
            conexao.close()

    def test_com_um_destino_recusa_e_sem_ele_desce_apagando_so_o_conteudo_e_volta(self) -> None:
        abaixo = _abaixo()
        conexao = ligacao.ligar("admin")
        try:
            tenant = factories.tenant(conexao.cursor())
            conexao.commit()
        finally:
            conexao.close()
        self.addCleanup(self._admin, "DELETE FROM platform.tenants WHERE id = %s", (tenant,))
        self.assertEqual(self._tabelas(), TABELAS)

        # 1. Com um destino da finalidade, a descida recusa e nada muda.
        [(destino,)] = self._admin(SQL_DESTINO + " RETURNING id::text", (tenant, FINALIDADE))
        try:
            recusa = alembic("downgrade", abaixo)
            self.assertNotEqual(recusa.returncode, 0, "a descida com o destino devia recusar")
            self.assertIn(f"purpose {FINALIDADE}", recusa.stdout + recusa.stderr)
            self.assertEqual(self._tabelas(), TABELAS)
            self.assertIn(FINALIDADE, self._dominio("tenant_destinations_purpose_ck"))
        finally:
            self._admin(f"DELETE FROM {DESTINOS} WHERE id = %s", (destino,))
            if not em_head():
                alembic_ok("upgrade", "head")

        # 2. Sem ele, desce: so as decisoes `conteudo` saem.
        conexao = ligacao.ligar("app")
        try:
            c = conexao.cursor()
            factories.contexto(c, tenant)
            screening.gravar(c, tenant, sujeito_tipo="conteudo", sujeito_ref=str(uuid.uuid4()))
            screening.gravar(c, tenant, sujeito_tipo="produto", sujeito_ref="sku-fica")
            conexao.commit()
        finally:
            conexao.close()
        self.assertEqual(self._decisoes(tenant), {"conteudo": 1, "produto": 1})

        alembic_ok("downgrade", abaixo)
        try:
            self.assertEqual(self._tabelas(), ())
            self.assertEqual(self._dominio("tenant_destinations_purpose_ck"), FINALIDADES_DA_0078)
            self.assertEqual(
                self._dominio("screening_decision_sujeito_tipo_ck"),
                ("categoria", "condicoes", "produto"),
            )
            self.assertEqual(self._decisoes(tenant), {"produto": 1})
            self.assertEqual(
                self._admin(
                    "SELECT tgenabled FROM pg_trigger WHERE tgname = 'screening_decision_imutavel'"
                ),
                [("O",)],
            )
            self.assertEqual(
                self._admin(
                    "SELECT relforcerowsecurity, (SELECT relforcerowsecurity FROM pg_class "
                    f"WHERE oid = '{DESTINOS}'::regclass) FROM pg_class "
                    "WHERE oid = 'platform.screening_decision'::regclass"
                ),
                [(True, True)],
            )
        finally:
            alembic_ok("upgrade", "head")

        # 3. E volta.
        self.assertEqual(self._tabelas(), TABELAS)
        self.assertIn(FINALIDADE, self._dominio("tenant_destinations_purpose_ck"))
        self.assertIn("conteudo", self._dominio("screening_decision_sujeito_tipo_ck"))


if __name__ == "__main__":
    unittest.main()
