"""A revisao `arte_e_aprovacao_do_social` (KAM-122): a maquina do item, a arte, a finalidade e a descida.

Quatro coisas, e a primeira e a que a revisao existe para ter:

1. **o gatilho `content_items_transicao`** faz da maquina de estados do item uma
   restricao da base (criterio 6: «0 itens `entregue` sem estado `aprovado`»):
   `entregue` so de `aprovado`, os finais nao mudam, a legenda, a arte e o hash
   nao mudam num item `aprovado` (criterio 5: a aprovacao fica ligada ao que o
   dono viu) e `aprovado -> pendente_aprovacao` e o caminho de uma edicao;
2. **as restricoes das colunas novas**: a chave do STO presa ao tenant da linha,
   ate tres tentativas, a arte completa ou nenhuma, e as tres que ligam o estado
   as colunas da aprovacao e da entrega;
3. **os privilegios**: o `kamba_app` muda as colunas novas e continua sem
   `DELETE`;
4. **a finalidade e a descida**: o dominio de `tenant_destinations.purpose` tem a
   `geracao_de_imagem` (decisao do fundador de 2026-11-21, opcao A da D3), e o
   `downgrade` **recusa-se** com um destino dela e deixa a base como estava; sem
   ele desce, tira o gatilho, as restricoes e as colunas, repoe as dezassete da
   `social_do_dono`, e volta a subir.

**Os casos das restricoes escolhem-se para so a restricao os recusar**, e os do
gatilho para so o gatilho: os dois falham com o mesmo `23514`, e um caso que os
dois recusassem nao mediria nenhum deles. Por isso um item `rascunho` com a arte,
a legenda, o hash e a hora da aprovacao todos escritos (o `CHECK` aceita-o) e o
que mede a aresta `-> entregue`.

A revisao descobre-se por *glob* e o `down_revision` le-se do ficheiro: o numero
e o da fila de integracao. **Nenhum ensaio exige a cabeca depois de descer**,
pela licao da `foto_de_produtos`.
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
    PRIVILEGIO_INSUFICIENTE,
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
ITENS = "platform.content_items"
FINALIDADE = "geracao_de_imagem"

#: As colunas que a revisao acrescenta ao item, e a do perfil.
COLUNAS_DO_ITEM = (
    "aprovacao_hash",
    "aprovado_at",
    "arte_custo_usd",
    "arte_formato",
    "arte_fundo",
    "arte_ref",
    "arte_sha256",
    "arte_tentativas",
    "arte_texto",
    "entregue_at",
)
COLUNA_DO_PERFIL = "termos_entrega_at"

#: As dezassete da `social_do_dono`, a que o `downgrade` volta. Por extenso: o
#: oraculo nao se le da revisao que mede.
FINALIDADES_DA_0079 = (
    "alojamento", "canal", "classificacao_de_catalogo", "classificacao_de_condicoes",
    "classificacao_de_conteudo", "conversa", "copias_de_seguranca", "embeddings",
    "entrega_de_conteudo", "facturacao", "imagem", "observabilidade",
    "otp_e_avisos_de_servico", "pagamentos", "segredos", "transcricao", "visao",
)

SQL_DESTINO = (
    f"INSERT INTO {DESTINOS} (tenant_id, provider, country, purpose, status, "
    "retencao_zero, sem_treino) VALUES (%s, 'google', 'US', %s, 'pendente', false, false)"
)

#: Dois `sha256` com a forma do `CHECK`. Em base32 seriam letras maiusculas, que
#: a forma recusa; o hexadecimal minusculo e o que o `hashlib` escreve.
SHA_A = "a" * 64
SHA_B = "b" * 64

#: A arte inteira: a chave, o `sha256`, o fundo, o texto e o formato que estao na
#: imagem. A `content_items_arte_completa_ck` exige as cinco ou nenhuma.
ARTE = (
    "arte_ref = %s, arte_sha256 = %s, arte_fundo = 'gerado', "
    "arte_texto = 'Loja da Ana - 12.500 Kz', arte_formato = 'quadrado'"
)


def _abaixo() -> str:
    [ficheiro] = list(VERSOES.glob("*_arte_e_aprovacao_do_social.py"))
    achado = re.search(r'^down_revision = "(\d{4})"$', ficheiro.read_text(encoding="utf-8"), re.M)
    assert achado, "a revisao nao declara down_revision"
    return achado.group(1)


def _chave(tenant: str) -> str:
    """Uma chave do STO do tenant, com a forma do `kamba_core/storage/chave.py`."""
    return f"t/{tenant}/social/2026/11/{uuid.uuid4()}"


class TestAFinalidade(ComBase):
    def test_a_geracao_de_imagem_e_a_decima_oitava_e_e_aceite(self) -> None:
        admin = self.ligar("admin").cursor()
        dominio = screening._dominio(admin, "tenant_destinations_purpose_ck")
        self.assertIn(FINALIDADE, dominio)
        self.assertEqual(len(dominio), 18)
        self.assertEqual(set(dominio) - {FINALIDADE}, set(FINALIDADES_DA_0079))
        tenant = factories.tenant(admin)
        admin.execute(SQL_DESTINO, (tenant, FINALIDADE))
        self.assertEqual(admin.rowcount, 1)
        self.assertErroSql(VIOLACAO_DE_CHECK, admin, SQL_DESTINO, (tenant, "geracao_da_imagem"))
        self.assertErroSql(VIOLACAO_DE_CHECK, admin, SQL_DESTINO, (tenant, "geracao"))


class ComItem(ComBase):
    """Uma transaccao do administrador que nunca confirma, com um tenant e um calendario."""

    def setUp(self) -> None:
        super().setUp()
        self.c = self.ligar("admin").cursor()
        self.tenant = factories.tenant(self.c)
        self.c.execute(
            "INSERT INTO platform.content_calendar "
            "(tenant_id, semana_iso, geracao, decisao, versao_politica) "
            "VALUES (%s, '2026-W48', 1, 'permitida', 'v1') RETURNING calendar_id::text",
            (self.tenant,),
        )
        self.calendario = self.c.fetchone()[0]

    def _novo(self, tenant: str | None = None) -> str:
        """Um item `rascunho`, como o `generate_calendar` o grava."""
        self.c.execute(
            f"INSERT INTO {ITENS} (tenant_id, calendar_id, semana_iso, tipo, tema, agendado_at) "
            "VALUES (%s, %s, '2026-W48', 'dica', 'um tema', now()) RETURNING content_item_id::text",
            (tenant or self.tenant, self.calendario),
        )
        return self.c.fetchone()[0]

    def _mudar(self, item: str, atribuicoes: str, parametros: tuple = ()) -> None:
        self.c.execute(f"UPDATE {ITENS} SET {atribuicoes} WHERE content_item_id = %s", (*parametros, item))
        self.assertEqual(self.c.rowcount, 1)

    def _recusa(self, item: str, atribuicoes: str, parametros: tuple = ()) -> None:
        self.assertErroSql(
            VIOLACAO_DE_CHECK,
            self.c,
            f"UPDATE {ITENS} SET {atribuicoes} WHERE content_item_id = %s",
            (*parametros, item),
        )

    def _com_tudo(self, item: str) -> None:
        """A legenda, a arte, o hash e a hora da aprovacao, sem mudar o estado."""
        self._mudar(
            item,
            f"legenda = 'Uma legenda.', {ARTE}, aprovacao_hash = %s, aprovado_at = now()",
            (_chave(self.tenant), SHA_A, SHA_B),
        )

    def _pendente(self) -> str:
        """O `request_approval`: a legenda, a arte e o hash do que o dono ve."""
        item = self._novo()
        self._mudar(
            item,
            f"legenda = 'Uma legenda.', {ARTE}, aprovacao_hash = %s, estado = 'pendente_aprovacao'",
            (_chave(self.tenant), SHA_A, SHA_B),
        )
        return item

    def _aprovado(self) -> str:
        item = self._pendente()
        self._mudar(item, "estado = 'aprovado', aprovado_at = now()")
        return item

    def _entregue(self) -> str:
        item = self._aprovado()
        self._mudar(item, "estado = 'entregue', entregue_at = now()")
        return item

    def _estado(self, item: str) -> str:
        self.c.execute(f"SELECT estado FROM {ITENS} WHERE content_item_id = %s", (item,))
        return self.c.fetchone()[0]


class TestAsTransicoes(ComItem):
    def test_o_caminho_da_aprovacao_ate_a_entrega_e_aceite(self) -> None:
        item = self._entregue()
        self.assertEqual(self._estado(item), "entregue")

    def test_entregue_so_de_aprovado(self) -> None:
        """Criterio 6. O item tem tudo o que o `CHECK` pede: so o gatilho recusa."""
        rascunho = self._novo()
        self._com_tudo(rascunho)
        self._recusa(rascunho, "estado = 'entregue', entregue_at = now()")
        pendente = self._pendente()
        self._mudar(pendente, "aprovado_at = now()")
        self._recusa(pendente, "estado = 'entregue', entregue_at = now()")
        self.assertEqual((self._estado(rascunho), self._estado(pendente)), ("rascunho", "pendente_aprovacao"))

    def test_as_arestas_fora_do_grafo_sao_recusadas(self) -> None:
        rascunho = self._novo()
        self._com_tudo(rascunho)
        self._recusa(rascunho, "estado = 'aprovado'")
        self._recusa(self._pendente(), "estado = 'rascunho'")
        self._recusa(self._aprovado(), "estado = 'rascunho'")
        self._recusa(self._aprovado(), "estado = 'expirado'")

    def test_as_arestas_do_grafo_sao_aceites(self) -> None:
        for chegada in ("pendente_aprovacao", "rejeitado", "expirado"):
            with self.subTest(de="rascunho", para=chegada):
                item = self._novo()
                if chegada == "pendente_aprovacao":
                    self._com_tudo(item)
                self._mudar(item, "estado = %s", (chegada,))
        for chegada in ("rejeitado", "expirado"):
            with self.subTest(de="pendente_aprovacao", para=chegada):
                self._mudar(self._pendente(), "estado = %s", (chegada,))
        with self.subTest(de="aprovado", para="rejeitado"):
            self._mudar(self._aprovado(), "estado = 'rejeitado'")

    def test_os_finais_nao_mudam(self) -> None:
        rejeitado = self._novo()
        self._mudar(rejeitado, "estado = 'rejeitado'")
        expirado = self._novo()
        self._mudar(expirado, "estado = 'expirado'")
        finais = {"entregue": self._entregue(), "rejeitado": rejeitado, "expirado": expirado}
        for estado, item in finais.items():
            with self.subTest(estado=estado):
                # Nem uma coluna que nenhuma outra regra guarda, nem o estado.
                self._recusa(item, "versao = versao + 1")
                self._recusa(item, "legenda = 'Outra legenda.'")
                self._recusa(item, "estado = 'pendente_aprovacao'")
                self.assertEqual(self._estado(item), estado)

    def test_um_aprovado_nao_muda_a_legenda_a_arte_nem_o_hash(self) -> None:
        """Criterio 5: a aprovacao fica ligada a `hash(legenda, arte, versao)`."""
        item = self._aprovado()
        for atribuicoes, parametros in (
            ("legenda = 'Outra legenda.'", ()),
            ("arte_ref = %s", (_chave(self.tenant),)),
            ("arte_sha256 = %s", ("c" * 64,)),
            ("arte_texto = 'Outro texto'", ()),
            ("aprovacao_hash = %s", ("c" * 64,)),
        ):
            with self.subTest(atribuicoes=atribuicoes):
                self._recusa(item, atribuicoes, parametros)
        # O que nao e a aprovacao muda.
        self._mudar(item, "atualizado_at = now()")
        self.assertEqual(self._estado(item), "aprovado")

    def test_a_passagem_a_aprovado_nao_muda_a_legenda_nem_o_hash_na_mesma_instrucao(self) -> None:
        item = self._pendente()
        self._recusa(item, "estado = 'aprovado', aprovado_at = now(), legenda = 'Outra.'")
        self._recusa(item, "estado = 'aprovado', aprovado_at = now(), aprovacao_hash = %s", ("c" * 64,))
        self._mudar(item, "estado = 'aprovado', aprovado_at = now()")

    def test_a_edicao_de_um_aprovado_volta_a_pendente_e_aprova_se_de_novo(self) -> None:
        item = self._aprovado()
        self._mudar(
            item,
            "estado = 'pendente_aprovacao', legenda = 'A legenda editada.', aprovacao_hash = %s",
            ("c" * 64,),
        )
        self.assertEqual(self._estado(item), "pendente_aprovacao")
        self._mudar(item, "estado = 'aprovado', aprovado_at = now()")
        self.assertEqual(self._estado(item), "aprovado")


class TestAsRestricoes(ComItem):
    def test_a_arte_e_uma_chave_do_sto_do_tenant_da_linha(self) -> None:
        outro = factories.tenant(self.c)
        factories.contexto(self.c, self.tenant)
        item = self._novo()
        atribuicoes = ARTE
        self._recusa(item, atribuicoes, (_chave(outro), SHA_A))
        self._recusa(item, atribuicoes, (f"t/{self.tenant}/social/2026/13/{uuid.uuid4()}", SHA_A))
        self._recusa(item, atribuicoes, (f"x/{self.tenant}/social/2026/11/{uuid.uuid4()}", SHA_A))
        self._mudar(item, atribuicoes, (_chave(self.tenant), SHA_A))

    def test_a_arte_e_completa_ou_nenhuma_e_o_fundo_e_de_dois(self) -> None:
        item = self._novo()
        chave = _chave(self.tenant)
        self._recusa(item, "arte_ref = %s", (chave,))
        self._recusa(item, "arte_sha256 = %s", (SHA_A,))
        self._recusa(item, "arte_fundo = 'gerado'")
        self._recusa(item, "arte_texto = 'Loja da Ana'")
        self._recusa(item, "arte_formato = 'quadrado'")
        # Quatro das cinco: falta o texto, ou falta o formato.
        self._recusa(
            item, "arte_ref = %s, arte_sha256 = %s, arte_fundo = 'gerado', arte_formato = 'quadrado'", (chave, SHA_A)
        )
        self._recusa(
            item, "arte_ref = %s, arte_sha256 = %s, arte_fundo = 'gerado', arte_texto = 'Loja da Ana'", (chave, SHA_A)
        )
        self._recusa(item, ARTE.replace("'gerado'", "'liso'"), (chave, SHA_A))
        self._mudar(item, ARTE, (chave, SHA_A))

    def test_o_texto_e_o_formato_da_arte_tem_dominio(self) -> None:
        item = self._novo()
        chave = _chave(self.tenant)
        self._recusa(item, ARTE.replace("'quadrado'", "'paisagem'"), (chave, SHA_A))
        self._recusa(item, ARTE.replace("'Loja da Ana - 12.500 Kz'", "''"), (chave, SHA_A))
        self._recusa(item, ARTE.replace("'Loja da Ana - 12.500 Kz'", "repeat('x', 601)"), (chave, SHA_A))
        self._mudar(
            item,
            ARTE.replace("'quadrado'", "'retrato'").replace("'Loja da Ana - 12.500 Kz'", "repeat('x', 600)"),
            (chave, SHA_A),
        )

    def test_os_sha256_tem_a_forma_do_hashlib(self) -> None:
        item = self._novo()
        self._recusa(item, ARTE, (_chave(self.tenant), "A" * 64))
        self._recusa(item, "aprovacao_hash = %s", ("a" * 63,))
        self._mudar(item, "aprovacao_hash = %s", (SHA_B,))

    def test_ate_tres_tentativas_e_custo_nao_negativo(self) -> None:
        item = self._novo()
        self._mudar(item, "arte_tentativas = 3")
        self._recusa(item, "arte_tentativas = 4")
        self._recusa(item, "arte_tentativas = -1")
        self._mudar(item, "arte_custo_usd = 0.1008")
        self._recusa(item, "arte_custo_usd = -0.000001")

    def test_o_estado_exige_as_colunas_da_aprovacao_e_da_entrega(self) -> None:
        """As tres restricoes de estado, com transicoes que o gatilho aceita."""
        sem_arte = self._novo()
        self._mudar(sem_arte, "legenda = 'Uma legenda.'")
        self._recusa(sem_arte, "estado = 'pendente_aprovacao'")
        sem_hora = self._pendente()
        self._recusa(sem_hora, "estado = 'aprovado'")
        sem_entrega = self._aprovado()
        self._recusa(sem_entrega, "estado = 'entregue'")
        self._recusa(self._novo(), "entregue_at = now()")


class TestOsPrivilegios(ComItem):
    def test_o_app_muda_as_colunas_novas_e_nao_apaga(self) -> None:
        self.c.execute("INSERT INTO platform.brand_profile (tenant_id) VALUES (%s)", (self.tenant,))
        item = self._novo()
        self.c.execute("SET LOCAL ROLE kamba_app")
        factories.contexto(self.c, self.tenant)
        self._mudar(
            item,
            f"legenda = 'Uma legenda.', {ARTE}, "
            "arte_tentativas = 1, arte_custo_usd = 0.0336, aprovacao_hash = %s, "
            "estado = 'pendente_aprovacao'",
            (_chave(self.tenant), SHA_A, SHA_B),
        )
        self._mudar(item, "estado = 'aprovado', aprovado_at = now()")
        self._mudar(item, "estado = 'entregue', entregue_at = now()")
        self.c.execute(
            "UPDATE platform.brand_profile SET termos_entrega_at = now() WHERE tenant_id = %s",
            (self.tenant,),
        )
        self.assertEqual(self.c.rowcount, 1)
        for sql in (
            f"DELETE FROM {ITENS} WHERE content_item_id = %s",
            f"UPDATE {ITENS} SET is_ai_generated = false WHERE content_item_id = %s",
        ):
            with self.subTest(sql=sql):
                self.assertErroSql(PRIVILEGIO_INSUFICIENTE, self.c, sql, (item,))
        self.c.execute("RESET ROLE")

    def test_so_o_app_e_o_dono_mudam_as_colunas_novas(self) -> None:
        papeis = sorted({*ligacao.PAPEIS.values(), "public"})
        for tabela, colunas in ((ITENS, COLUNAS_DO_ITEM), ("platform.brand_profile", (COLUNA_DO_PERFIL,))):
            for coluna in colunas:
                with self.subTest(tabela=tabela, coluna=coluna):
                    self.c.execute(
                        "SELECT r.papel FROM unnest(%s::text[]) AS r(papel) "
                        "WHERE has_column_privilege(r.papel, %s, %s, 'UPDATE') ORDER BY 1",
                        (papeis, tabela, coluna),
                    )
                    self.assertEqual(
                        [p for (p,) in self.c.fetchall()], ["kamba_app", "kamba_migrator"]
                    )


class TestDowngradeDaArteEAprovacao(unittest.TestCase):
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

    def _estado(self) -> tuple:
        """As colunas novas, o gatilho, a funcao e o dominio das finalidades."""
        colunas = self._admin(
            "SELECT table_name::text, column_name::text FROM information_schema.columns "
            "WHERE table_schema = 'platform' AND table_name IN ('content_items', 'brand_profile') "
            "AND column_name = ANY(%s) ORDER BY 1, 2",
            ([*COLUNAS_DO_ITEM, COLUNA_DO_PERFIL],),
        )
        gatilho = self._admin("SELECT count(*) FROM pg_trigger WHERE tgname = 'content_items_transicao'")
        funcao = self._admin("SELECT count(*) FROM pg_proc WHERE proname = 'content_items_transicao'")
        conexao = ligacao.ligar("admin")
        try:
            dominio = screening._dominio(conexao.cursor(), "tenant_destinations_purpose_ck")
        finally:
            conexao.close()
        return tuple(colunas), gatilho[0][0], funcao[0][0], dominio

    def test_com_um_destino_recusa_e_sem_ele_desce_e_volta(self) -> None:
        abaixo = _abaixo()
        conexao = ligacao.ligar("admin")
        try:
            tenant = factories.tenant(conexao.cursor())
            conexao.commit()
        finally:
            conexao.close()
        self.addCleanup(self._admin, "DELETE FROM platform.tenants WHERE id = %s", (tenant,))
        cabeca = self._estado()
        self.assertEqual(len(cabeca[0]), len(COLUNAS_DO_ITEM) + 1)
        self.assertEqual(cabeca[1:3], (1, 1))
        self.assertIn(FINALIDADE, cabeca[3])

        # 1. Com um destino da finalidade, a descida recusa e nada muda.
        [(destino,)] = self._admin(SQL_DESTINO + " RETURNING id::text", (tenant, FINALIDADE))
        try:
            recusa = alembic("downgrade", abaixo)
            self.assertNotEqual(recusa.returncode, 0, "a descida com o destino devia recusar")
            self.assertIn(f"purpose {FINALIDADE}", recusa.stdout + recusa.stderr)
            self.assertEqual(self._estado(), cabeca)
            self.assertEqual(
                self._admin(f"SELECT relforcerowsecurity FROM pg_class WHERE oid = '{DESTINOS}'::regclass"),
                [(True,)],
            )
        finally:
            self._admin(f"DELETE FROM {DESTINOS} WHERE id = %s", (destino,))
            if not em_head():
                alembic_ok("upgrade", "head")

        # 2. Sem ele, desce: as colunas, o gatilho e a funcao saem, e o dominio
        # volta as dezassete.
        alembic_ok("downgrade", abaixo)
        try:
            self.assertEqual(self._estado(), ((), 0, 0, FINALIDADES_DA_0079))
            self.assertEqual(
                self._admin(f"SELECT relforcerowsecurity FROM pg_class WHERE oid = '{DESTINOS}'::regclass"),
                [(True,)],
            )
        finally:
            alembic_ok("upgrade", "head")

        # 3. E volta.
        self.assertEqual(self._estado(), cabeca)


if __name__ == "__main__":
    unittest.main()
