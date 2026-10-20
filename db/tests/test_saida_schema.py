"""A revisao `0010` — saida de canal (KAM-015).

O esquema em si prova-se nas baterias que ja existiam: o inventario fechado de
colunas (`test_inventario.py`), a matriz de privilegios (`test_privilegios.py`),
o catalogo (`test_catalogo.py`) e o X-03/X-04/X-05 do *gate* 6. O que **so**
aqui se prova sao duas coisas que nenhuma delas consegue afirmar:

1. **As FK compostas, coluna a coluna.** O inventario lista as FK por **nome**,
   e um nome nao diz quantas colunas a restricao tem: trocar
   `FOREIGN KEY (tenant_id, channel_id)` por `FOREIGN KEY (channel_id)` deixava
   `outbound_messages_channel_fk` com o mesmo nome e a lista verde. E o furo
   que isso abre e o que a emenda 1.21 declarou como a primeira divergencia —
   uma mensagem do *tenant* A a apontar para um canal de B, que a RLS de
   `outbound_messages` nao apanha (a linha e de A) e a de `tenant_channels`
   tambem nao (uma FK e verificada por dentro). E a licao da `0009`, aplicada a
   uma revisao com **tres** FK compostas em vez de duas.

2. **O `downgrade`**, que o DoD pede pelo nome: «Migracoes reversiveis —
   `downgrade` testado». E reverter esta revisao perde duas coisas que nao se
   reconstroem: o `pricing` de cada mensagem entregue — o unico registo do que a
   Meta cobrou, e o que o §16 do `docs/tecnica/01` aponta como mecanismo de
   «custo monitorizado por tenant e por mensagem» — e as chaves de idempotencia
   que ja passaram, sem as quais um `upgrade` seguido de uma repeticao reenvia
   tudo o que estava em voo. Por isso o `downgrade` **recusa** com linhas e sem
   copia logica, na forma da `0003` e da `0009`.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
em que a base esta.
"""

from __future__ import annotations

import datetime
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
    TABELAS_ATE_0009,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0010_COPIA"

#: As catorze colunas que a copia de envios escreve, pela ordem da revisao.
COLUNAS_DA_COPIA_DE_ENVIOS = (
    "id",
    "tenant_id",
    "channel_id",
    "contact_id",
    "conversation_id",
    "idempotency_key",
    "wamid",
    "kind",
    "template_name",
    "state",
    "pricing",
    "error_code",
    "created_at",
    "delivered_at",
)

#: As dez dos templates, idem.
COLUNAS_DA_COPIA_DE_TEMPLATES = (
    "tenant_id",
    "name",
    "lang",
    "category",
    "status",
    "quality",
    "meta_template_id",
    "body_hash",
    "bloqueado_em",
    "updated_at",
)


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestFkCompostasDaSaida(ComBase):
    """As FK da saida, **coluna a coluna**. Ver o ponto 1 da docstring do modulo."""

    #: restricao -> (colunas de origem, tabela de destino, colunas de destino).
    ESPERADO = {
        "outbound_messages_tenant_fk": (
            ["tenant_id"],
            "platform.tenants",
            ["id"],
        ),
        "outbound_messages_channel_fk": (
            ["tenant_id", "channel_id"],
            "platform.tenant_channels",
            ["tenant_id", "id"],
        ),
        "outbound_messages_contact_fk": (
            ["tenant_id", "contact_id"],
            "platform.contacts",
            ["tenant_id", "contact_id"],
        ),
        "outbound_messages_conversation_fk": (
            ["tenant_id", "conversation_id"],
            "platform.conversations",
            ["tenant_id", "id"],
        ),
        "message_templates_tenant_fk": (
            ["tenant_id"],
            "platform.tenants",
            ["id"],
        ),
    }

    def test_as_fk_da_saida_sao_as_declaradas_coluna_a_coluna(self) -> None:
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

    def test_tres_das_quatro_fk_da_mensagem_levam_o_tenant_id(self) -> None:
        """A contagem, e nao so cada uma: e o que uma FK nova nao pode baixar.

        A do *tenant* e simples porque a `tenants.id` **e** a chave; as outras
        tres sao compostas porque cada destino tem `tenant_id`. Uma FK nova em
        `outbound_messages` para uma tabela com `tenant_id` tem de ser composta,
        e esta assercao e a que a obriga a passar por aqui.
        """
        linhas = self.consultar(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conrelid = 'platform.outbound_messages'::regclass "
            "AND contype = 'f' AND cardinality(conkey) = 2"
        )
        self.assertEqual(linhas, [(3,)])

    def test_a_unique_de_conversations_existe_para_a_fk_composta_assentar(self) -> None:
        """Sem ela, a FK da conversa nao podia ser composta: nao havia chave.

        E a razao por que a `0010` toca numa tabela da `0009`, como a `0009`
        tocou numa da `0001`.
        """
        linhas = self.consultar(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'conversations_tenant_id_uq'"
        )
        self.assertEqual(linhas, [("UNIQUE (tenant_id, id)",)])

    def test_a_unicidade_da_chave_e_por_tenant_e_a_do_wamid_e_global(self) -> None:
        """A assimetria do §3.14, afirmada — e nao so os nomes das restricoes.

        A da chave e **por tenant**: com unicidade global, um *tenant* suprimia
        em silencio o envio de outro que calhasse usar a mesma chave. A do
        `wamid` e **global**: um `wamid` e um identificador da Meta, e o mesmo
        `wamid` em dois *tenants* nao e coincidencia, e defeito nosso.
        """
        linhas = dict(
            self.consultar(
                "SELECT conname::text, pg_get_constraintdef(oid) "
                "FROM pg_constraint "
                "WHERE conrelid = 'platform.outbound_messages'::regclass "
                "AND contype = 'u'"
            )
        )
        self.assertEqual(
            linhas,
            {
                "outbound_messages_idempotency_uq": "UNIQUE (tenant_id, idempotency_key)",
                "outbound_messages_wamid_uq": "UNIQUE (wamid)",
            },
        )


class TestCoerenciasDaSaida(ComBase):
    """As tres `CHECK` de coerencia, pela **semantica** e nao pelo nome.

    O inventario fechado lista-as por nome, e as mutacoes da `0010` trocam-lhes
    o nome — o que a lista apanha. Nenhuma das duas diz o que a restricao
    **faz**: uma `CHECK (true)` com o nome certo passava as duas.

    E foi exactamente ali que o defeito esteve. A `outbound_messages_entrega_ck`
    admitia `delivered_at` so em `delivered` e `read`, e o `estados.ts` deixa
    sair de qualquer nao-terminal para um terminal — uma mensagem entregue que
    passasse a `failed` matava o `UPDATE` com `23514`. O caso positivo abaixo e
    o que prende a correccao; os negativos sao o que ela nao podia alargar.
    """

    #: Um instante qualquer, resolvido em Python: um `now()` nao cabe num
    #: parametro, e construir o SQL por concatenacao para o meter la era trocar
    #: legibilidade por nada.
    AGORA = datetime.datetime(2026, 10, 20, 12, 0, tzinfo=datetime.timezone.utc)

    def semear(self, cursor) -> dict[str, str]:
        """Um tenant com canal, contacto e conversa."""
        tenant = factories.tenant(cursor)
        canal = factories.canal(cursor, tenant)
        contacto = factories.contacto(cursor, tenant)
        conversa = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO platform.conversations "
            "(id, tenant_id, contact_id, channel_id) VALUES (%s, %s, %s, %s)",
            (conversa, tenant, contacto, canal),
        )
        return {
            "tenant_id": tenant,
            "channel_id": canal,
            "contact_id": contacto,
            "conversation_id": conversa,
        }

    def envio(self, chaves: dict[str, str], **troca) -> tuple[str, tuple]:
        """O `INSERT` de um envio, com as colunas por omissao e as trocas."""
        colunas = {
            "id": str(uuid.uuid4()),
            **chaves,
            "idempotency_key": f"chave-{uuid.uuid4()}",
            "kind": "service",
            "state": "queued",
            **troca,
        }
        nomes = ", ".join(colunas)
        marcas = ", ".join(["%s"] * len(colunas))
        return (
            f"INSERT INTO platform.outbound_messages ({nomes}) VALUES ({marcas})",
            tuple(colunas.values()),
        )

    def test_um_instante_de_entrega_antes_da_entrega_e_recusado(self) -> None:
        """A razao de a restricao existir: a cobranca e na entrega.

        `queued` e `sent` sao os dois estados por onde uma mensagem passa
        **sem** ter sido entregue, e sao os dois que a restricao tem de
        recusar — enviada nao e entregue, e e essa a diferenca que o custo usa.
        """
        cursor = self.ligar("admin").cursor()
        chaves = self.semear(cursor)
        for estado in ("queued", "sent"):
            with self.subTest(estado=estado):
                sql, valores = self.envio(chaves, state=estado, delivered_at=self.AGORA)
                self.assertErroSql("23514", cursor, sql, valores)

    def test_um_instante_de_entrega_nos_dois_terminais_e_ACEITE(self) -> None:
        """**A correccao.** A entrega aconteceu; o instante nao se apaga.

        Uma mensagem entregue pode passar a `failed` depois — a Meta nao garante
        ordem nos `statuses` — e o custo ja foi contado. Apagar o instante era
        destruir a linha de auditoria que reconcilia a factura, e recusar o
        `UPDATE` era o que a primeira versao fazia: matava a ingestao com
        `23514`. O `suppressed_by_human` esta aqui pela mesma razao, e e o
        estado que o KAM-018 usa.
        """
        cursor = self.ligar("admin").cursor()
        chaves = self.semear(cursor)
        for estado in ("delivered", "read", "failed", "suppressed_by_human"):
            with self.subTest(estado=estado):
                sql, valores = self.envio(chaves, state=estado, delivered_at=self.AGORA)
                cursor.execute(sql, valores)
                self.assertEqual(cursor.rowcount, 1)

    def test_um_codigo_de_erro_fora_de_failed_e_recusado(self) -> None:
        cursor = self.ligar("admin").cursor()
        chaves = self.semear(cursor)
        sql, valores = self.envio(chaves, state="sent", error_code=131026)
        self.assertErroSql("23514", cursor, sql, valores)

    def test_um_codigo_de_erro_num_failed_passa(self) -> None:
        cursor = self.ligar("admin").cursor()
        chaves = self.semear(cursor)
        sql, valores = self.envio(chaves, state="failed", error_code=131026)
        cursor.execute(sql, valores)
        self.assertEqual(cursor.rowcount, 1)

    def test_uma_utility_sem_template_e_recusada(self) -> None:
        """E o que impede uma mensagem paga de ser gravada como se fosse livre."""
        cursor = self.ligar("admin").cursor()
        chaves = self.semear(cursor)
        sql, valores = self.envio(chaves, kind="utility")
        self.assertErroSql("23514", cursor, sql, valores)

    def test_um_service_com_template_e_recusado(self) -> None:
        """O outro lado da mesma restricao: um `service` nao leva template."""
        cursor = self.ligar("admin").cursor()
        chaves = self.semear(cursor)
        sql, valores = self.envio(
            chaves, kind="service", template_name="confirmacao_de_pedido"
        )
        self.assertErroSql("23514", cursor, sql, valores)

    def test_uma_utility_com_template_passa(self) -> None:
        cursor = self.ligar("admin").cursor()
        chaves = self.semear(cursor)
        sql, valores = self.envio(
            chaves, kind="utility", template_name="confirmacao_de_pedido"
        )
        cursor.execute(sql, valores)
        self.assertEqual(cursor.rowcount, 1)


class TestDowngradeDa0010(unittest.TestCase):
    """«Migracoes reversiveis — `downgrade` testado», e sem perda em silencio."""

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
        self.copia = Path(self.pasta.name) / "copia-0010.json"
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
                    "DELETE FROM platform.outbound_messages WHERE tenant_id = %s",
                    (tenant,),
                )
                self.cursor.execute(
                    "DELETE FROM platform.message_templates WHERE tenant_id = %s",
                    (tenant,),
                )
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

    def semear(self) -> dict[str, list[str]]:
        """Dois envios de dois tenants, um entregue com `pricing`, e um template.

        O entregue e o que torna o `downgrade` destrutivo de verdade: leva o
        `pricing` e o `delivered_at`, que sao o registo do que a Meta cobrou.
        """
        envios: list[str] = []
        templates: list[str] = []
        for indice in range(2):
            tenant = factories.tenant(self.cursor)
            self.tenants.append(tenant)
            canal = factories.canal(self.cursor, tenant)
            contacto = factories.contacto(self.cursor, tenant)
            conversa = str(uuid.uuid4())
            self.cursor.execute(
                "INSERT INTO platform.conversations "
                "(id, tenant_id, contact_id, channel_id, last_inbound_at, "
                " window_expires_at) "
                "VALUES (%s, %s, %s, %s, now(), now() + interval '24 hours')",
                (conversa, tenant, contacto, canal),
            )
            identificador = str(uuid.uuid4())
            if indice == 0:
                self.cursor.execute(
                    "INSERT INTO platform.outbound_messages "
                    "(id, tenant_id, channel_id, contact_id, conversation_id, "
                    " idempotency_key, wamid, kind, state, pricing, delivered_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, 'service', 'delivered', "
                    "        %s::jsonb, now())",
                    (
                        identificador,
                        tenant,
                        canal,
                        contacto,
                        conversa,
                        f"chave-{indice}",
                        f"wamid.ENSAIO{indice}",
                        json.dumps(
                            {
                                "billable": True,
                                "pricing_model": "CBP",
                                "type": "service",
                                "category": "service",
                            }
                        ),
                    ),
                )
            else:
                self.cursor.execute(
                    "INSERT INTO platform.outbound_messages "
                    "(id, tenant_id, channel_id, contact_id, conversation_id, "
                    " idempotency_key, kind, state) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'service', 'queued')",
                    (
                        identificador,
                        tenant,
                        canal,
                        contacto,
                        conversa,
                        f"chave-{indice}",
                    ),
                )
            envios.append(identificador)
            self.cursor.execute(
                "INSERT INTO platform.message_templates "
                "(tenant_id, name, lang, category, status, body_hash) "
                "VALUES (%s, 'confirmacao_de_pedido', 'pt_PT', 'utility', "
                "        'approved', %s)",
                # O `body_hash` e `NOT NULL`: e o que torna uma alteracao de
                # corpo detectavel sem guardar o corpo. Foi o que faltou a
                # primeira versao desta semente, e a base recusou-a com 23502.
                (tenant, "0" * 64),
            )
            templates.append(tenant)
        return {"envios": envios, "templates": templates}

    def test_com_as_tabelas_vazias_desce_e_sobe_sem_pedir_copia(self) -> None:
        """Sem envios nem templates nao ha nada a perder: o `downgrade` nao pergunta."""
        for tabela in ("outbound_messages", "message_templates"):
            self.cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
            self.assertEqual(self.cursor.fetchone()[0], 0, tabela)

        alembic_ok("downgrade", "0009")
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0009)
        # A `UNIQUE` que a `0010` acrescentou a `conversations` tambem sai, e o
        # `FORCE` fica reposto: sem isto, um `upgrade` seguinte falhava a criar
        # a restricao que ja existia.
        self.cursor.execute(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conname = 'conversations_tenant_id_uq'"
        )
        self.assertEqual(self.cursor.fetchone()[0], 0)
        self.cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'platform.conversations'::regclass"
        )
        self.assertEqual(tuple(self.cursor.fetchone()), (True, True))

        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)

    def test_com_linhas_e_sem_a_variavel_o_downgrade_recusa(self) -> None:
        """Nao ha perda em silencio: recusa, e a mensagem diz quantas e porque.

        **A contagem tem de ver as linhas**, e e por isso que este teste e o que
        prende a ordem das instrucoes do `downgrade`: com `FORCE ROW LEVEL
        SECURITY`, o dono esta sujeito a politica, e uma migracao corre sem
        contexto de *tenant*. Se os `disable_tenant_rls` nao fossem as primeiras
        instrucoes, o `count(*)` via **zero** sobre duas tabelas cheias — nao
        pedia copia nenhuma e apagava em silencio, que e o contrario do que
        estas linhas existem para impedir.
        """
        self.semear()

        resultado = alembic("downgrade", "0009")

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        saida = resultado.stdout + resultado.stderr
        self.assertIn("2 mensagem(ns) de saida", saida)
        self.assertIn("2 template(s)", saida)
        self.assertIn(VARIAVEL_DA_COPIA, saida)
        # A base ficou em `head`: o `downgrade` levanta na propria revisao, e o
        # Alembic corre uma transaccao por revisao — logo as politicas que a
        # funcao desligou voltam atras com ela.
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.cursor.execute("SELECT count(*) FROM platform.outbound_messages")
        self.assertEqual(self.cursor.fetchone()[0], 2)
        # E o `FORCE` das duas tabelas ficou **intacto**: a recusa nao pode
        # deixar a base com a RLS desligada, que seria trocar uma perda de dados
        # por um furo de isolamento.
        for tabela in ("outbound_messages", "message_templates"):
            with self.subTest(tabela=tabela):
                self.cursor.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    f"WHERE oid = 'platform.{tabela}'::regclass"
                )
                self.assertEqual(tuple(self.cursor.fetchone()), (True, True))

    def test_com_a_variavel_escreve_a_copia_e_desce(self) -> None:
        """A copia leva as catorze colunas de cada envio e as dez de cada template."""
        semeadas = self.semear()
        os.environ[VARIAVEL_DA_COPIA] = str(self.copia)

        alembic_ok("downgrade", "0009")

        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0009)
        self.assertTrue(self.copia.is_file(), "a copia logica nao foi escrita")
        copia = json.loads(self.copia.read_text(encoding="utf-8"))
        self.assertEqual(sorted(copia), ["message_templates", "outbound_messages"])

        envios = copia["outbound_messages"]
        self.assertEqual(len(envios), 2)
        for linha in envios:
            self.assertEqual(tuple(linha), COLUNAS_DA_COPIA_DE_ENVIOS)
        self.assertEqual({linha["id"] for linha in envios}, set(semeadas["envios"]))

        # **O `pricing` esta na copia**, e e esta assercao que justifica a
        # recusa: sem ele nao ha como reconciliar uma factura da Meta, e e a
        # razao escrita no `downgrade`. Uma copia que levasse as linhas e
        # perdesse o `pricing` era pior do que nenhuma, porque parecia completa.
        entregue = [linha for linha in envios if linha["state"] == "delivered"]
        self.assertEqual(len(entregue), 1)
        self.assertEqual(entregue[0]["pricing"]["category"], "service")
        self.assertIs(entregue[0]["pricing"]["billable"], True)
        self.assertIsNotNone(entregue[0]["delivered_at"])
        self.assertIsNotNone(entregue[0]["wamid"])
        # O que ficou em `queued` leva os tres a nulo, e tambem isso se repoe.
        emFila = [linha for linha in envios if linha["state"] == "queued"]
        self.assertEqual(len(emFila), 1)
        self.assertIsNone(emFila[0]["pricing"])
        self.assertIsNone(emFila[0]["delivered_at"])
        self.assertIsNone(emFila[0]["wamid"])
        # E a chave de idempotencia **de cada um**: e a outra coisa que se perde.
        self.assertEqual(
            sorted(linha["idempotency_key"] for linha in envios),
            ["chave-0", "chave-1"],
        )

        templates = copia["message_templates"]
        self.assertEqual(len(templates), 2)
        for linha in templates:
            self.assertEqual(tuple(linha), COLUNAS_DA_COPIA_DE_TEMPLATES)
        self.assertEqual(
            {linha["tenant_id"] for linha in templates}, set(semeadas["templates"])
        )
        self.assertEqual({linha["status"] for linha in templates}, {"approved"})

        # E o `upgrade` seguinte repoe as tabelas — vazias, como a revisao as
        # cria. **Nao ha ferramenta de reposicao**, e isso e a limitacao que a
        # `0003` ja declarou: a copia e um `INSERT` por linha, a mao.
        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.cursor.execute("SELECT count(*) FROM platform.outbound_messages")
        self.assertEqual(self.cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
