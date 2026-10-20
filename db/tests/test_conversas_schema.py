"""A revisao `0009` — conversas (KAM-014).

O esquema em si e o seu isolamento provam-se nas baterias que ja existiam: o
inventario fechado de colunas (`test_inventario.py`), a matriz de privilegios
(`test_privilegios.py`), o catalogo (`test_catalogo.py`) e o X-03/X-04/X-05 do
*gate* 6. O que **so** aqui se prova e o que o DoD do ticket pede pelo nome:

    «Migracoes reversiveis — `downgrade` de `conversations` testado.»

E reverter esta revisao nao e como reverter a `0008`. O que se perde nao e um
registo de passagem: e a **janela de 24 h** e o **modo** de cada conversa. Perder
o modo e o pior dos dois — uma conversa que estava em `humano` volta a `bot` no
`upgrade` seguinte, e o assistente interrompe um atendimento que uma pessoa
estava a fazer, o que o `docs/tecnica/01` §10.2 proibe por escrito. Por isso o
`downgrade` **recusa** com linhas e sem copia logica, na forma da `0003`.

Nao herda de `ComBase`: controla ele proprio a revisao em que a base esta.
"""

from __future__ import annotations

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
    ComBase,
    TABELAS,
    TABELAS_ATE_0008,
    TABELAS_ATE_0009,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0009_COPIA"

#: As oito colunas que a copia logica escreve, pela ordem da revisao.
COLUNAS_DA_COPIA = (
    "id",
    "tenant_id",
    "contact_id",
    "channel_id",
    "mode",
    "last_inbound_at",
    "window_expires_at",
    "last_human_activity_at",
)


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestFkCompostas(ComBase):
    """As FK da conversa, **coluna a coluna**.

    O inventario fechado (`test_inventario.py`) lista as FK por **nome**, e um
    nome nao diz quantas colunas a restricao tem: trocar
    `FOREIGN KEY (tenant_id, channel_id)` por `FOREIGN KEY (channel_id)` deixava
    `conversations_channel_fk` com o mesmo nome e a lista verde. E o furo que
    isso abre nao e teorico — uma conversa do tenant A a apontar para um canal
    do tenant B, que a RLS de `conversations` nao apanha (a linha e de A) e a de
    `tenant_channels` tambem nao (a FK e verificada por dentro).

    Medido: as duas mutacoes que tiram o `tenant_id` das FK eram «apanhadas» por
    um teste da propria lista de mutacoes, e nao por nada que afirmasse a
    propriedade. Esta classe afirma-a.
    """

    #: restricao -> (colunas de origem, tabela de destino, colunas de destino).
    ESPERADO = {
        "conversations_tenant_fk": (
            ["tenant_id"], "platform.tenants", ["id"],
        ),
        "conversations_contact_fk": (
            ["tenant_id", "contact_id"], "platform.contacts", ["tenant_id", "contact_id"],
        ),
        "conversations_channel_fk": (
            ["tenant_id", "channel_id"], "platform.tenant_channels", ["tenant_id", "id"],
        ),
    }

    def test_as_fk_da_conversa_sao_as_declaradas_coluna_a_coluna(self) -> None:
        for nome, (origem, destino, alvo) in self.ESPERADO.items():
            with self.subTest(fk=nome):
                linhas = self.consultar(
                    "SELECT confrelid::regclass::text, "
                    "  (SELECT array_agg(a.attname::text ORDER BY k.ordem) "
                    "     FROM unnest(c.conkey) WITH ORDINALITY AS k(att, ordem) "
                    "     JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.att), "
                    "  (SELECT array_agg(a.attname::text ORDER BY k.ordem) "
                    "     FROM unnest(c.confkey) WITH ORDINALITY AS k(att, ordem) "
                    "     JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.att) "
                    "FROM pg_constraint c WHERE c.conname = %s AND c.contype = 'f'",
                    (nome,),
                )
                self.assertEqual(len(linhas), 1, f"{nome} nao existe")
                self.assertEqual(
                    (linhas[0][0], list(linhas[0][1]), list(linhas[0][2])),
                    (destino, origem, alvo),
                )

    def test_a_unique_de_tenant_channels_existe_para_a_fk_composta_assentar(self) -> None:
        """Sem ela, a FK do canal nao podia ser composta: nao havia chave.

        E a razao por que a `0009` toca numa tabela da `0001`, o que nenhuma
        outra revisao aditiva faz.
        """
        linhas = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'tenant_channels_tenant_id_uq'"
        )
        self.assertEqual(linhas, [("UNIQUE (tenant_id, id)",)])

    def test_nenhuma_fk_da_conversa_e_diferida(self) -> None:
        """So a do dono o e (`test_inventario.py`), e por uma razao que nao vale aqui."""
        linhas = self.consultar(
            "SELECT conname::text FROM pg_constraint "
            "WHERE conrelid = 'platform.conversations'::regclass "
            "AND contype = 'f' AND (condeferrable OR condeferred)"
        )
        self.assertEqual(linhas, [])


class TestDowngradeDa0009(unittest.TestCase):
    """«`downgrade` de `conversations` testado», e sem perda em silencio."""

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
        self.copia = Path(self.pasta.name) / "copia-0009.json"
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
                    "DELETE FROM platform.conversations WHERE tenant_id = %s", (tenant,)
                )
                self.cursor.execute(
                    "DELETE FROM platform.tenant_channels WHERE tenant_id = %s", (tenant,)
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

    def semear(self) -> list[dict]:
        """Duas conversas de dois tenants, com modos e janelas diferentes.

        Uma em `humano` e com a janela aberta, outra em `bot` e sem janela: sao
        as duas formas que o `conversations_janela_ck` aceita, e e a primeira
        que torna o `downgrade` destrutivo de verdade.
        """
        linhas: list[dict] = []
        for indice in range(2):
            tenant = factories.tenant(self.cursor)
            self.tenants.append(tenant)
            canal = factories.canal(self.cursor, tenant)
            contacto = factories.contacto(self.cursor, tenant)
            identificador = str(uuid.uuid4())
            if indice == 0:
                self.cursor.execute(
                    "INSERT INTO platform.conversations "
                    "(id, tenant_id, contact_id, channel_id, mode, last_inbound_at, "
                    " window_expires_at, last_human_activity_at) "
                    "VALUES (%s, %s, %s, %s, 'humano', now(), "
                    "        now() + interval '24 hours', now())",
                    (identificador, tenant, contacto, canal),
                )
            else:
                self.cursor.execute(
                    "INSERT INTO platform.conversations "
                    "(id, tenant_id, contact_id, channel_id) VALUES (%s, %s, %s, %s)",
                    (identificador, tenant, contacto, canal),
                )
            linhas.append({"id": identificador, "tenant_id": tenant})
        return linhas

    def test_com_a_tabela_vazia_desce_e_sobe_sem_pedir_copia(self) -> None:
        """Sem conversas nao ha nada a perder: o `downgrade` nao pergunta."""
        self.cursor.execute("SELECT count(*) FROM platform.conversations")
        self.assertEqual(self.cursor.fetchone()[0], 0)

        alembic_ok("downgrade", "0008")
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0008)
        # A `UNIQUE` que a `0009` acrescentou a `tenant_channels` tambem sai, e
        # o `FORCE` fica reposto: sem isto, um `upgrade` seguinte falhava a
        # criar a restricao que ja existia.
        self.cursor.execute(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = 'tenant_channels_tenant_id_uq'"
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)
        self.cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'platform.tenant_channels'::regclass"
        )
        self.assertEqual(tuple(self.cursor.fetchone()), (True, True))
        # E o `plano` volta a estar fora do alcance do resolvedor.
        self.cursor.execute(
            "SELECT has_column_privilege('kamba_resolver', 'platform.tenants', "
            "'plano', 'SELECT')"
        )
        self.assertFalse(self.cursor.fetchone()[0])

        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.cursor.execute(
            "SELECT has_column_privilege('kamba_resolver', 'platform.tenants', "
            "'plano', 'SELECT')"
        )
        self.assertTrue(self.cursor.fetchone()[0])

    def test_com_conversas_e_sem_a_variavel_o_downgrade_recusa(self) -> None:
        """Nao ha perda em silencio: recusa, e a mensagem diz quantas e porque."""
        self.semear()

        resultado = alembic("downgrade", "0008")

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        saida = resultado.stdout + resultado.stderr
        self.assertIn("2 conversa(s)", saida)
        self.assertIn(VARIAVEL_DA_COPIA, saida)
        # A base ficou **em `0009`**, e nao em head, desde que o KAM-015
        # acrescentou a `0010`. Nao e regressao: o Alembic corre **uma
        # transaccao por revisao** (`transaction_per_migration=True`), pelo que
        # o `downgrade` da `0010` — que nao tem envios nem templates para
        # perder — desce e **compromete** antes de a `0009` levantar. O que
        # esta linha tem de afirmar e a propriedade que importa: a revisao que
        # recusa nao toca em nada do que e dela, e as conversas ficam.
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0009)
        self.cursor.execute("SELECT count(*) FROM platform.conversations")
        self.assertEqual(self.cursor.fetchone()[0], 2)

    def test_com_a_variavel_escreve_a_copia_e_desce(self) -> None:
        """A copia leva as oito colunas de cada conversa, e repoe-se a partir dela."""
        semeadas = self.semear()
        os.environ[VARIAVEL_DA_COPIA] = str(self.copia)

        alembic_ok("downgrade", "0008")

        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0008)
        self.assertTrue(self.copia.is_file(), "a copia logica nao foi escrita")
        copia = json.loads(self.copia.read_text(encoding="utf-8"))
        self.assertEqual(len(copia), 2)
        for linha in copia:
            self.assertEqual(tuple(linha), COLUNAS_DA_COPIA)
        por_id = {linha["id"]: linha for linha in copia}
        self.assertEqual(set(por_id), {linha["id"] for linha in semeadas})
        # A que estava em `humano` levou o modo **e** a janela; a outra levou os
        # tres tempos a nulo. E isto que torna a copia uma reposicao possivel.
        emHumano = [linha for linha in copia if linha["mode"] == "humano"]
        self.assertEqual(len(emHumano), 1)
        self.assertIsNotNone(emHumano[0]["last_inbound_at"])
        self.assertIsNotNone(emHumano[0]["window_expires_at"])
        self.assertIsNotNone(emHumano[0]["last_human_activity_at"])
        emBot = [linha for linha in copia if linha["mode"] == "bot"]
        self.assertEqual(len(emBot), 1)
        self.assertIsNone(emBot[0]["last_inbound_at"])
        self.assertIsNone(emBot[0]["window_expires_at"])

        # E o `upgrade` seguinte repoe a tabela — vazia, como a revisao a cria.
        # **Nao ha ferramenta de reposicao**, e isso e a limitacao que a `0003`
        # ja declarou: a copia e um `INSERT` por linha, a mao.
        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.cursor.execute("SELECT count(*) FROM platform.conversations")
        self.assertEqual(self.cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
