"""A categoria da oferta e a fonte do preco anomalo, contra a base (KAM-209).

O que so uma base prova, e por isso este ficheiro existe:

1. **O dominio fechado** da `offer_terms.categoria`: as oito da politica
   passam, uma fora dela recusa (`23514`).
2. **A guarda na publicacao**, com o SQL do COM tal como esta escrito e pela
   ligacao da aplicacao: sem categoria, o `SQL_PUBLICAR` afecta zero linhas e o
   `INSERT` ja publicado recusa; com categoria, publica. Uma oferta publicada
   antes da revisao (nula, semeada pelo dono da tabela) continua publicada e
   continua a aceitar os termos; a categoria de um publicado nao volta a nulo.
3. **O `kamba_app` escreve a categoria** pelo `SQL_ACTUALIZAR_TERMOS` e o
   `INSERT` do rascunho.
4. **A `fonte` no detalhe de um sinal**, e so ela a mais.
5. **O `downgrade`**, pelo numero lido da revisao. A recusa com um sinal que
   leva a `fonte` **nao** se ensaia aqui: provoca-la e gravar numa tabela
   *append-only* uma linha que depois trava a descida de todas as revisoes
   abaixo desta, na mesma base (a licao do `tenant_state_log`, KAM-092).
"""

from __future__ import annotations

import json
import re
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    VIOLACAO_DE_CHECK,
    ComBase,
    ConsultaDoTypeScript,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)
from tests.test_publicacao_segura_schema import decidir, sha

_RAIZ = Path(__file__).resolve().parents[2]
COM = _RAIZ / "services" / "com" / "src" / "produtos" / "consultas.ts"
REVISAO = next((_RAIZ / "db" / "migrations" / "versions").glob("*_categoria_da_oferta.py"))

OFERTA = "platform.offer_terms"
AGORA = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
CATEGORIAS = ("moda", "mercearia", "restauracao", "beleza", "electronica", "servicos",
              "material_construcao", "outra")


def _anterior() -> str:
    """O `down_revision` da revisao, lido dela: muda na integracao, e o ensaio segue-o."""
    achado = re.search(r'^down_revision = "(\d{4})"$', REVISAO.read_text(encoding="utf-8"), re.M)
    assert achado is not None
    return achado.group(1)


def com(cursor, nome: str, *valores) -> int:
    q = ConsultaDoTypeScript(nome, COM)
    cursor.execute(q.sql, q.args(*valores))
    return cursor.rowcount


def oferta(cursor, tenant: str, sku: str, *, categoria: str | None, estado: str = "rascunho") -> None:
    cursor.execute(
        f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor, estado, categoria) "
        "VALUES (%s, %s, 'Camisola de malha', 'fixo', 100000, %s, %s)",
        (tenant, sku, estado, categoria),
    )


def linha(cursor, tenant: str, sku: str) -> tuple[str, str | None]:
    cursor.execute(f"SELECT estado, categoria FROM {OFERTA} WHERE tenant_id = %s AND sku = %s", (tenant, sku))
    estado, categoria = cursor.fetchone()
    return estado, categoria


class _Oferta(ComBase):
    """Um tenant com a categoria `moda` e o produto decididos, numa transaccao que o ensaio desfaz."""

    def setUp(self) -> None:
        super().setUp()
        self.admin = self.ligar("admin").cursor()
        self.tenant = factories.tenant(self.admin)
        decidir(self.admin, self.tenant, "categoria", "moda", "permitida")

    def produto(self, sku: str, *, categoria: str | None, estado: str = "rascunho") -> str:
        oferta(self.admin, self.tenant, sku, categoria=categoria, estado=estado)
        decidir(self.admin, self.tenant, "produto", sku, "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        return sku

    def como(self, papel: str):
        self.admin.execute(f"SET LOCAL ROLE {papel}")
        factories.contexto(self.admin, self.tenant)
        return self.admin

    def recusa(self, sql: str, valores: tuple) -> str:
        self.admin.execute("SAVEPOINT r")
        try:
            with self.assertRaises(Exception) as erro:
                self.admin.execute(sql, valores)
            return str(erro.exception)
        finally:
            self.admin.execute("ROLLBACK TO SAVEPOINT r")


class TestDominio(_Oferta):
    def test_as_oito_da_politica_passam(self) -> None:
        for i, categoria in enumerate(CATEGORIAS):
            with self.subTest(categoria=categoria):
                oferta(self.admin, self.tenant, f"sku-{i}", categoria=categoria)

    def test_uma_fora_da_lista_recusa(self) -> None:
        for fora in ("vestuario", "Moda", "", "outras"):
            with self.subTest(categoria=fora):
                texto = self.recusa(
                    f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor, categoria) "
                    "VALUES (%s, 'x', 'Saia', 'fixo', 1000, %s)", (self.tenant, fora))
                self.assertIn(VIOLACAO_DE_CHECK, texto)
                self.assertIn("offer_terms_categoria_ck", texto)


class TestGuardaNaPublicacao(_Oferta):
    def test_sem_categoria_o_sql_publicar_afecta_zero_linhas(self) -> None:
        sku = self.produto("sku-1", categoria=None)
        app = self.como("kamba_app")
        self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 0)
        self.assertEqual(linha(app, self.tenant, sku), ("rascunho", None))

    def test_com_categoria_publica(self) -> None:
        sku = self.produto("sku-1", categoria="moda")
        app = self.como("kamba_app")
        self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 1)
        self.assertEqual(linha(app, self.tenant, sku), ("publicado", "moda"))

    def test_o_insert_ja_publicado_sem_categoria_recusa_pelos_dois_papeis_de_servico(self) -> None:
        decidir(self.admin, self.tenant, "produto", "sku-p", "permitida",
                conteudo=sha(self.admin, "moda", "Camisola de malha"))
        for papel in ("kamba_app", "kamba_batch"):
            with self.subTest(papel=papel):
                self.admin.execute("SAVEPOINT p")
                self.como(papel)
                texto = self.recusa(
                    f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor, estado) "
                    "VALUES (%s, 'sku-p', 'Camisola de malha', 'fixo', 1000, 'publicado')", (self.tenant,))
                self.assertIn(VIOLACAO_DE_CHECK, texto)
                self.assertIn("sem categoria", texto)
                self.admin.execute("ROLLBACK TO SAVEPOINT p")

    def test_a_categoria_de_um_publicado_nao_volta_a_nulo(self) -> None:
        sku = self.produto("sku-1", categoria="moda")
        app = self.como("kamba_app")
        com(app, "SQL_PUBLICAR", self.tenant, sku)
        texto = self.recusa(
            f"UPDATE {OFERTA} SET categoria = NULL WHERE tenant_id = %s AND sku = %s", (self.tenant, sku))
        self.assertIn(VIOLACAO_DE_CHECK, texto)

    def test_uma_publicada_de_antes_fica_nula_e_os_termos_continuam_a_escrever(self) -> None:
        """Decisao do fundador de 2026-11-21: a guarda vale so na publicacao."""
        sku = self.produto("sku-antiga", categoria=None, estado="publicado")
        app = self.como("kamba_app")
        self.assertEqual(com(app, "SQL_ACTUALIZAR_TERMOS", self.tenant, sku, "Camisola de malha", "fixo",
                             150000, None, "indicativo", AGORA, None), 1)
        self.assertEqual(com(app, "SQL_PUBLICAR", self.tenant, sku), 1, "republicar o publicado passa")
        self.assertEqual(linha(app, self.tenant, sku), ("publicado", None))

    def test_a_aplicacao_poe_a_categoria_pelos_termos_e_a_de_antes_passa_a_ter(self) -> None:
        sku = self.produto("sku-antiga", categoria=None, estado="publicado")
        app = self.como("kamba_app")
        self.assertEqual(com(app, "SQL_ACTUALIZAR_TERMOS", self.tenant, sku, "Camisola de malha", "fixo",
                             100000, None, "indicativo", AGORA, "moda"), 1)
        self.assertEqual(linha(app, self.tenant, sku), ("publicado", "moda"))

    def test_o_rascunho_da_aplicacao_nasce_com_a_categoria(self) -> None:
        app = self.como("kamba_app")
        app.execute(
            f"INSERT INTO {OFERTA} (tenant_id, sku, nome, preco_tipo, preco_minor, categoria) "
            "VALUES (%s, 'sku-novo', 'Saia', 'fixo', 1000, 'moda')", (self.tenant,))
        self.assertEqual(linha(app, self.tenant, "sku-novo"), ("rascunho", "moda"))


class TestPrivilegios(ComBase):
    def test_o_kamba_app_actualiza_a_categoria_e_a_funcao_nao_e_publica(self) -> None:
        c = self.ligar("admin").cursor()
        c.execute("SELECT has_column_privilege('kamba_app', 'platform.offer_terms', 'categoria', 'UPDATE')")
        self.assertTrue(c.fetchone()[0])
        c.execute("SELECT has_function_privilege('public', "
                  "'platform.offer_terms_categoria_na_publicacao()', 'EXECUTE')")
        self.assertFalse(c.fetchone()[0])
        c.execute("SELECT tgenabled FROM pg_trigger WHERE tgname = 'offer_terms_categoria_na_publicacao'")
        self.assertEqual(c.fetchone()[0], "A", "ENABLE ALWAYS")


class TestFonteNoDetalhe(ComBase):
    def _sinal(self, c, tenant: str, detalhe: dict) -> None:
        c.execute(
            "INSERT INTO platform.ts_signal (tenant_id, tipo, severidade, ref_evento, detalhe, ocorrido_em) "
            "VALUES (%s, 'preco_anomalo', 'baixa', %s, %s::jsonb, now())",
            (tenant, str(uuid.uuid4()), json.dumps(detalhe)))

    def test_a_fonte_passa_e_uma_chave_inventada_continua_a_recusar(self) -> None:
        c = self.ligar("admin").cursor()
        tenant = factories.tenant(c)
        self._sinal(c, tenant, {"sku": "x", "contagem": 20, "fonte": "plataforma/1", "versao_politica": "1.0.0"})
        c.execute("SAVEPOINT s")
        with self.assertRaises(Exception) as erro:
            self._sinal(c, tenant, {"mediana": 100000})
        self.assertIn(VIOLACAO_DE_CHECK, str(erro.exception))
        c.execute("ROLLBACK TO SAVEPOINT s")


class TestDowngradeDaCategoriaDaOferta(unittest.TestCase):
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

    def _objectos(self) -> int:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'platform' "
                      "AND table_name = 'offer_terms' AND column_name = 'categoria'")
            n = int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'offer_terms_categoria_na_publicacao'")
            n += int(c.fetchone()[0])
            c.execute("SELECT count(*) FROM pg_constraint WHERE conname = 'ts_signal_detalhe_ck' "
                      "AND pg_get_constraintdef(oid) LIKE '%fonte%'")
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


if __name__ == "__main__":
    unittest.main()
