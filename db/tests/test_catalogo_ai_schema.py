"""A revisao do Catalogo AI contra a base: platform.catalog_ingestions (KAM-049).

O que so uma base prova, e por isso este ficheiro existe:

1. **As listas sao as do codigo.** O `CHECK` do estado contra
   `kamba_core.catalogo.estados.ESTADOS`, e a maquina do *trigger* contra a
   `TRANSICOES` de la, nas 81 combinacoes — incluindo a recusa de qualquer
   alteracao a uma linha `publicada` ou `descartada`.
2. **As restricoes de linha** do criterio 1 e da etapa 9: idempotencia por
   `(tenant_id, media_id_meta)`, `media_ref` presa ao STO do proprio tenant
   (nunca URL da Meta), `publicada` so com confirmacao do dono, `bloqueada_categoria`
   so com `categoria_restrita`, no maximo doze perguntas e nunca a descer.
3. **Privilegios e RLS `FORCE`** (DoD, ADR-015): o `kamba_app` nao apaga, nao
   muda a identidade da foto, nao le nem escreve outro tenant, e sem contexto
   nao ve nada.
4. **O pipeline sobre a base**: o `ServicoDeIngestao` com o
   `RepositorioDbapi` pela ligacao da aplicacao, da foto a `publicada`, com a
   idempotencia por `media_id` medida contra o `UNIQUE` e o isolamento contra
   a RLS.
5. **O `downgrade`**, para a revisao de baixo lida do proprio ficheiro.
"""

from __future__ import annotations

import ast
import itertools
import sys
import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import ligacao
from tests import factories
from tests.base import (
    PRIVILEGIO_INSUFICIENTE,
    VIOLACAO_DE_CHECK,
    VIOLACAO_DE_UNICIDADE,
    ComBase,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

RAIZ = Path(__file__).resolve().parents[2]
# O `kamba_core` e os fakes do Catalogo AI nao estao no caminho de quem corre
# esta suite: a mesma solucao do `test_destinos_schema.py`.
for _pasta in (RAIZ / "libs" / "py-core" / "src", RAIZ / "libs" / "py-core" / "tests"):
    if str(_pasta) not in sys.path:
        sys.path.insert(0, str(_pasta))

from catalogo_apoio import (  # noqa: E402
    DescodificadorFake,
    DestinosFake,
    FonteFake,
    RegistoFake,
    ScreeningFake,
    VisaoFake,
    confirmacao,
    jpeg,
    lexico,
    responder,
)
from kamba_core.catalogo import estados  # noqa: E402
from kamba_core.catalogo.pipeline import ServicoDeIngestao  # noqa: E402
from kamba_core.catalogo.repositorio import ConflitoDeEstado, RepositorioDbapi  # noqa: E402
from kamba_core.storage.fake import criar_storage_fake  # noqa: E402

TABELA = "platform.catalog_ingestions"
REVISAO = next((RAIZ / "db" / "migrations" / "versions").glob("*_catalogo_ai.py"))
AGORA = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)


def _literal(nome: str) -> str:
    """O `revision` ou o `down_revision` da revisao, lidos do ficheiro."""
    arvore = ast.parse(REVISAO.read_text(encoding="utf-8"))
    for no in arvore.body:
        if isinstance(no, ast.Assign) and any(getattr(t, "id", None) == nome for t in no.targets):
            return ast.literal_eval(no.value)
    raise AssertionError(f"{nome} nao encontrado em {REVISAO.name}")


def _colunas_para(estado: str) -> dict[str, object]:
    """O que uma linha precisa para satisfazer os `CHECK` de um estado."""
    if estado == "bloqueada_categoria":
        return {"categoria_restrita": "alcool"}
    if estado == "publicada":
        return {"sku": "cat-x", "confirmado_at": AGORA, "confirmado_por": "owner:1", "categoria_restrita": None}
    return {"categoria_restrita": None}


def inserir(cursor, tenant_id: str, estado: str = "recebida", **campos) -> str:
    """Uma ingestao pela ligacao de quem chama. Devolve o `id`."""
    valores: dict[str, object] = {
        "tenant_id": tenant_id,
        "media_ref": f"t/{tenant_id}/catalogo/2026/11/{uuid.uuid4()}",
        "media_id_meta": f"wamid.{uuid.uuid4().hex}",
        "estado": estado,
    }
    valores.update(_colunas_para(estado))
    valores.update(campos)
    colunas = ", ".join(valores)
    marcadores = ", ".join(["%s"] * len(valores))
    cursor.execute(f"INSERT INTO {TABELA} ({colunas}) VALUES ({marcadores}) RETURNING id::text", tuple(valores.values()))
    return cursor.fetchone()[0]


class TestDominios(ComBase):
    def test_o_dominio_do_estado_e_o_do_modulo(self) -> None:
        [(definicao,)] = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'catalog_ingestions_estado_ck'"
        )
        for estado in estados.ESTADOS:
            self.assertIn(f"'{estado}'", definicao)
        self.assertEqual(definicao.count("'"), 2 * len(estados.ESTADOS))

    def test_a_maquina_do_trigger_e_a_do_modulo_nas_81_combinacoes(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = factories.tenant(admin)
        for de, para in itertools.product(estados.ESTADOS, repeat=2):
            with self.subTest(de=de, para=para):
                linha = inserir(admin, tenant, de)
                definir = ", ".join(f"{c} = %s" for c in _colunas_para(para))
                sql = f"UPDATE {TABELA} SET estado = %s, {definir} WHERE id = %s"
                parametros = (para, *_colunas_para(para).values(), linha)
                if de not in estados.FINAIS and estados.pode(de, para):
                    admin.execute(sql, parametros)
                else:
                    self.assertErroSql(VIOLACAO_DE_CHECK, admin, sql, parametros)

    def test_uma_linha_final_nao_muda_nem_fora_do_estado(self) -> None:
        admin = self.ligar("admin").cursor()
        tenant = factories.tenant(admin)
        for final in sorted(estados.FINAIS):
            with self.subTest(final=final):
                linha = inserir(admin, tenant, final)
                self.assertErroSql(VIOLACAO_DE_CHECK, admin,
                                   f"UPDATE {TABELA} SET extraido = '{{\"preco\": 1}}' WHERE id = %s", (linha,))


class TestRestricoes(ComBase):
    def test_reprocessar_o_mesmo_media_id_no_mesmo_tenant_e_recusado(self) -> None:
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        b = factories.tenant(admin)
        inserir(admin, a, media_id_meta="wamid.repetido")
        inserir(admin, b, media_id_meta="wamid.repetido")
        self.assertErroSql(
            VIOLACAO_DE_UNICIDADE, admin,
            f"INSERT INTO {TABELA} (tenant_id, media_ref, media_id_meta) VALUES (%s, %s, 'wamid.repetido')",
            (a, f"t/{a}/catalogo/2026/11/{uuid.uuid4()}"),
        )

    def test_media_ref_e_uma_chave_do_sto_do_proprio_tenant(self) -> None:
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        b = factories.tenant(admin)
        for media_ref in (
            "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1",
            f"t/{b}/catalogo/2026/11/{uuid.uuid4()}",
            f"t/{a}/audio/2026/11/{uuid.uuid4()}",
        ):
            with self.subTest(media_ref=media_ref):
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, admin,
                    f"INSERT INTO {TABELA} (tenant_id, media_ref) VALUES (%s, %s)", (a, media_ref),
                )

    def test_restricoes_de_linha(self) -> None:
        admin = self.ligar("admin").cursor()
        a = factories.tenant(admin)
        casos = (
            ("phash de quatro bytes", {"phash": b"1234"}),
            ("treze perguntas", {"perguntas_feitas": 13}),
            ("perguntas negativas", {"perguntas_feitas": -1}),
            ("categoria fora da forma", {"categoria_restrita": "Alcool!"}),
            ("custo negativo", {"custo_llm_usd": Decimal("-0.01")}),
            ("extraido que nao e objecto", {"extraido": "[]"}),
            ("estado inventado", {"estado": "aprovada"}),
            ("bloqueada sem categoria", {"estado": "bloqueada_categoria", "categoria_restrita": None}),
            ("publicada sem confirmacao", {"estado": "publicada", "confirmado_at": None}),
            ("publicada sem quem confirmou", {"estado": "publicada", "confirmado_por": None}),
            ("publicada sem sku", {"estado": "publicada", "sku": None}),
            ("publicada com categoria restrita", {"estado": "publicada", "categoria_restrita": "alcool"}),
        )
        for nome, campos in casos:
            with self.subTest(caso=nome):
                estado = str(campos.get("estado", "recebida"))
                valores = {**_colunas_para(estado), **campos}
                valores.pop("estado", None)
                colunas = ", ".join(("tenant_id", "media_ref", "estado", *valores))
                marcadores = ", ".join(["%s"] * (3 + len(valores)))
                if "extraido" in valores:
                    marcadores = marcadores[: -2] + "%s::jsonb"
                self.assertErroSql(
                    VIOLACAO_DE_CHECK, admin,
                    f"INSERT INTO {TABELA} ({colunas}) VALUES ({marcadores})",
                    (a, f"t/{a}/catalogo/2026/11/{uuid.uuid4()}", estado, *valores.values()),
                )

    def test_as_perguntas_nao_descem(self) -> None:
        admin = self.ligar("admin").cursor()
        linha = inserir(admin, factories.tenant(admin), "a_perguntar", perguntas_feitas=6)
        self.assertErroSql(VIOLACAO_DE_CHECK, admin,
                           f"UPDATE {TABELA} SET perguntas_feitas = 5 WHERE id = %s", (linha,))
        admin.execute(f"UPDATE {TABELA} SET perguntas_feitas = 9 WHERE id = %s", (linha,))


class TestPrivilegios(ComBase):
    def test_a_rls_esta_ligada_e_forcada(self) -> None:
        [(ligada, forcada)] = self.consultar(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", (TABELA,)
        )
        self.assertEqual((ligada, forcada), (True, True))

    def test_a_aplicacao_nao_apaga_nem_muda_a_identidade_da_foto(self) -> None:
        admin = self.ligar("admin")
        tenant = factories.tenant(admin.cursor())
        linha = inserir(admin.cursor(), tenant)
        admin.commit()
        app = self.ligar("app").cursor()
        factories.contexto(app, tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app, f"DELETE FROM {TABELA} WHERE id = %s", (linha,))
        for coluna, valor in (
            ("media_ref", f"'t/{tenant}/catalogo/2026/11/{uuid.uuid4()}'"),
            ("media_id_meta", "'outro'"),
            ("tenant_id", "gen_random_uuid()"),
            ("criado_at", "now()"),
        ):
            with self.subTest(coluna=coluna):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                                   f"UPDATE {TABELA} SET {coluna} = {valor} WHERE id = %s", (linha,))
        # O estado so nasce `recebida`: a aplicacao nao insere outro.
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app,
            f"INSERT INTO {TABELA} (tenant_id, media_ref, estado) VALUES (%s, %s, 'publicada')",
            (tenant, f"t/{tenant}/catalogo/2026/11/{uuid.uuid4()}"),
        )

    def test_a_aplicacao_so_ve_e_escreve_o_seu_tenant(self) -> None:
        admin = self.ligar("admin")
        a = factories.tenant(admin.cursor())
        b = factories.tenant(admin.cursor())
        linha_a = inserir(admin.cursor(), a)
        admin.commit()
        app = self.ligar("app").cursor()
        factories.contexto(app, b)
        app.execute(f"SELECT count(*) FROM {TABELA} WHERE id = %s", (linha_a,))
        self.assertEqual(app.fetchone()[0], 0)
        app.execute(f"UPDATE {TABELA} SET estado = 'descartada' WHERE id = %s", (linha_a,))
        self.assertEqual(app.rowcount, 0)
        # Escrever uma linha de A com o contexto de B: a `WITH CHECK` recusa.
        self.assertErroSql(
            PRIVILEGIO_INSUFICIENTE, app,
            f"INSERT INTO {TABELA} (tenant_id, media_ref) VALUES (%s, %s)",
            (a, f"t/{a}/catalogo/2026/11/{uuid.uuid4()}"),
        )
        factories.contexto(app, None)
        app.execute(f"SELECT count(*) FROM {TABELA}")
        self.assertEqual(app.fetchone()[0], 0)
        factories.contexto(app, a)
        app.execute(f"SELECT count(*) FROM {TABELA} WHERE id = %s", (linha_a,))
        self.assertEqual(app.fetchone()[0], 1)


class TestPipelineNaBase(ComBase):
    """O `ServicoDeIngestao` com o `RepositorioDbapi`, pela ligacao da aplicacao."""

    def _tenants(self) -> tuple[str, str]:
        admin = self.ligar("admin")
        a = factories.tenant(admin.cursor())
        b = factories.tenant(admin.cursor())
        admin.commit()
        return a, b

    def _servico(self, tenants: tuple[str, ...], medias: dict[str, bytes]) -> tuple[ServicoDeIngestao, VisaoFake, RegistoFake]:
        visao = VisaoFake()
        destinos = DestinosFake({(t, "anthropic", "visao") for t in tenants})
        registo = RegistoFake()
        servico = ServicoDeIngestao(
            repositorio=RepositorioDbapi(lambda: ligacao.ligar("app")),
            fonte=FonteFake(medias),
            storage=criar_storage_fake().storage,
            descodificador=DescodificadorFake(),
            destinos=destinos,
            visao=visao,
            lexico=lexico,
            screening=ScreeningFake(),
            registo=registo,
            ambiente="prod",
        )
        return servico, visao, registo

    def test_da_foto_a_publicada(self) -> None:
        a, _ = self._tenants()
        servico, visao, registo = self._servico((a,), {"m1": jpeg(b"BASE")})
        r = servico.receber(a, "m1")
        self.assertEqual(r.estado, estados.A_PERGUNTAR)
        for resposta in ({"preco_tipo": "fixo"}, {"preco": "12 mil"}, {"stock_modo": "garantido"},
                         {"stock": "5"}, {"entrega": "entrega"}):
            r = responder(servico, a, r.ingestao.id, resposta)
        self.assertEqual(r.estado, estados.RASCUNHO)
        final = servico.confirmar(a, r.ingestao.id, confirmacao(r.versao_texto or ""))
        self.assertEqual(final.estado, estados.PUBLICADA)
        self.assertEqual(len(registo.publicados), 1)
        lida = self.consultar(
            f"SELECT estado, confirmado_por, custo_llm_usd, perguntas_feitas, "
            f"extraido -> 'preco' ->> 'fonte', extraido -> 'marca' ->> 'valor' FROM {TABELA} WHERE id = %s",
            (final.ingestao.id,),
        )
        self.assertEqual(lida, [("publicada", "owner:1", Decimal("0.004200"), 5, "dono_texto", "nike")])
        self.assertEqual(len(visao.imagens), 1)

    def test_o_mesmo_media_id_e_uma_linha(self) -> None:
        a, _ = self._tenants()
        servico, visao, _ = self._servico((a,), {"m1": jpeg(b"IDEM")})
        primeira = servico.receber(a, "m1")
        segunda = servico.receber(a, "m1")
        self.assertEqual(primeira.ingestao.id, segunda.ingestao.id)
        self.assertEqual(len(visao.imagens), 1)
        [(linhas,)] = self.consultar(
            f"SELECT count(*) FROM {TABELA} WHERE tenant_id = %s AND media_id_meta = 'm1'", (a,)
        )
        self.assertEqual(linhas, 1)

    def test_outro_tenant_nao_le_a_ingestao(self) -> None:
        a, b = self._tenants()
        servico, _, _ = self._servico((a, b), {"m1": jpeg(b"ISO")})
        de_a = servico.receber(a, "m1")
        repo = RepositorioDbapi(lambda: ligacao.ligar("app"))
        self.assertIsNone(repo.ler(b, de_a.ingestao.id))
        self.assertIsNotNone(repo.ler(a, de_a.ingestao.id))

    def test_escrita_concorrente_recebe_conflito(self) -> None:
        a, _ = self._tenants()
        servico, _, _ = self._servico((a,), {"m1": jpeg(b"CONC")})
        lida = servico.receber(a, "m1").ingestao
        repo = RepositorioDbapi(lambda: ligacao.ligar("app"))
        repo.gravar(lida, _com_estado(lida, "descartada"))
        with self.assertRaises(ConflitoDeEstado):
            repo.gravar(lida, _com_estado(lida, "rascunho"))

    def test_duas_escritas_no_mesmo_estado_nao_se_sobrepoem(self) -> None:
        """A versao, e nao o estado, e o que o `gravar` compara (achado 4 da revisao)."""
        from dataclasses import replace

        a, _ = self._tenants()
        servico, _, _ = self._servico((a,), {"m1": jpeg(b"VERS")})
        lida = servico.receber(a, "m1").ingestao
        self.assertEqual(lida.estado, estados.A_PERGUNTAR)
        repo = RepositorioDbapi(lambda: ligacao.ligar("app"))
        escrita = repo.gravar(lida, replace(lida, perguntas_feitas=lida.perguntas_feitas + 1))
        self.assertEqual(escrita.versao, lida.versao + 1)
        with self.assertRaises(ConflitoDeEstado):
            repo.gravar(lida, replace(lida, perguntas_feitas=lida.perguntas_feitas + 2))

    def test_a_versao_e_o_atualizado_at_sao_do_gatilho(self) -> None:
        admin = self.ligar("admin")
        tenant = factories.tenant(admin.cursor())
        linha = inserir(admin.cursor(), tenant)
        admin.commit()
        app = self.ligar("app").cursor()
        factories.contexto(app, tenant)
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"UPDATE {TABELA} SET versao = 0 WHERE id = %s", (linha,))
        self.assertErroSql(PRIVILEGIO_INSUFICIENTE, app,
                           f"UPDATE {TABELA} SET atualizado_at = now() WHERE id = %s", (linha,))
        app.execute(f"UPDATE {TABELA} SET sku = 'cat-a' WHERE id = %s RETURNING versao", (linha,))
        self.assertEqual(app.fetchone()[0], 1)
        app.execute(f"UPDATE {TABELA} SET sku = 'cat-b' WHERE id = %s RETURNING versao", (linha,))
        self.assertEqual(app.fetchone()[0], 2)


def _com_estado(ingestao, estado: str):
    from dataclasses import replace

    return replace(ingestao, estado=estado)


class TestDowngrade(unittest.TestCase):
    """Desce para a revisao de baixo (lida do ficheiro), com linhas, e volta a subir.

    **Nao exige `em_head()` depois de descer**: com outra revisao por cima, o
    Alembic desce-a primeiro e a base fica na de baixo desta, que e o que se
    mede.
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

    def _existe(self) -> tuple[int, int]:
        conexao = ligacao.ligar("admin")
        try:
            c = conexao.cursor()
            c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'platform' "
                      "AND tablename = 'catalog_ingestions'")
            tabelas = c.fetchone()[0]
            c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'catalog_ingestions_transicao'")
            return tabelas, c.fetchone()[0]
        finally:
            conexao.close()

    def test_desce_com_linhas_e_volta_a_subir(self) -> None:
        conexao = ligacao.ligar("admin")
        try:
            cursor = conexao.cursor()
            inserir(cursor, factories.tenant(cursor), "a_perguntar")
            conexao.commit()
        finally:
            conexao.close()
        alembic_ok("downgrade", _literal("down_revision"))
        self.assertEqual(self._existe(), (0, 0))
        alembic_ok("upgrade", "head")
        self.assertEqual(self._existe(), (1, 1))


if __name__ == "__main__":
    unittest.main()
