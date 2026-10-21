"""A revisao `0011` — passagem a humano (KAM-019).

O esquema em si prova-se nas baterias que ja existiam: o inventario fechado de
colunas (`test_inventario.py`), a matriz de privilegios (`test_privilegios.py`),
o catalogo (`test_catalogo.py`) e o X-03/X-05 do *gate* 6. O que **so** aqui se
prova sao tres coisas que nenhuma delas consegue afirmar:

1. **As FK da passagem, coluna a coluna.** O inventario lista-as por **nome**, e
   um nome nao diz quantas colunas a restricao tem: trocar
   `FOREIGN KEY (tenant_id, conversation_id)` por `FOREIGN KEY (conversation_id)`
   deixava `handoffs_conversation_fk` com o mesmo nome e a lista verde. E o furo
   que a `0009` nomeou — uma passagem do tenant A a apontar para uma conversa de
   B, que a RLS de `handoffs` nao apanha (a linha e de A) e a de `conversations`
   tambem nao (uma FK e verificada por dentro).

2. **A unicidade da conta no provedor, pela semantica.** A
   `handoff_accounts_conta_uq` e o que impede a **mesma conta do provedor em
   dois tenants**, e e o furo que o X-10 procura. A chave primaria
   `(tenant_id, provedor)` fecha o outro lado e nao este.

3. **O `downgrade`**, que o DoD pede pelo nome. Reverter perde duas coisas que
   nao se reconstroem: a **conta no provedor**, cujo `account_id` fica a existir
   la fora e que nenhuma migracao nossa pode desfazer porque o recurso nao e
   nosso — e sem a linha que o aponta, o `ensureAccount` seguinte cria uma
   segunda conta para a mesma PME, que e exactamente o que o criterio 1 proibe —
   e o **historico de passagens**, que sustenta o SLA de retoma.

A classe do `downgrade` nao herda de `ComBase`: controla ela propria a revisao
em que a base esta.
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
    TABELAS_ATE_0010,
    TABELAS_ATE_0011,
    alembic,
    alembic_ok,
    em_head,
    exigir_base_descartavel,
)

VARIAVEL_DA_COPIA = "KAMBA_DOWNGRADE_0011_COPIA"

#: As nove colunas que a copia de passagens escreve, pela ordem da revisao.
COLUNAS_DA_COPIA_DE_HANDOFFS = (
    "handoff_id",
    "tenant_id",
    "conversation_id",
    "status",
    "motivo",
    "external_id",
    "opened_at",
    "resumed_at",
    "resolver",
)

#: As **dez** das contas de atendimento, idem. Eram oito; o `provider_user_id`
#: e o `user_token_ref` entraram pela emenda 1.23, que veio do spike: os
#: endpoints da conta recusam o token da plataforma e o do bot nao cria
#: contactos, pelo que ha um utilizador da conta e os identificadores dele
#: existem **la fora** — nao os copiar era perde-los para sempre.
COLUNAS_DA_COPIA_DE_CONTAS = (
    "tenant_id",
    "provedor",
    "account_id",
    "inbox_id",
    "bot_id",
    "provider_user_id",
    "token_ref",
    "user_token_ref",
    "criado_at",
    "updated_at",
)


def _tabelas(cursor) -> tuple[str, ...]:
    cursor.execute(
        "SELECT tablename::text FROM pg_tables WHERE schemaname = 'platform' ORDER BY 1"
    )
    return tuple(linha[0] for linha in cursor.fetchall())


class TestFkEUnicidadeDoHandoff(ComBase):
    """As FK e a unicidade, pela semantica. Ver os pontos 1 e 2 da docstring."""

    #: restricao -> (colunas de origem, tabela de destino, colunas de destino).
    ESPERADO = {
        "handoffs_tenant_fk": (["tenant_id"], "platform.tenants", ["id"]),
        "handoffs_conversation_fk": (
            ["tenant_id", "conversation_id"],
            "platform.conversations",
            ["tenant_id", "id"],
        ),
        "handoff_accounts_tenant_fk": (["tenant_id"], "platform.tenants", ["id"]),
    }

    def test_as_fk_do_handoff_sao_as_declaradas_coluna_a_coluna(self) -> None:
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

    def test_a_fk_da_conversa_e_a_unica_composta_e_leva_o_tenant(self) -> None:
        """A contagem, e nao so cada uma: e o que uma FK nova nao pode baixar."""
        linhas = self.consultar(
            "SELECT count(*) FROM pg_constraint "
            "WHERE conrelid = 'platform.handoffs'::regclass "
            "AND contype = 'f' AND cardinality(conkey) = 2"
        )
        self.assertEqual(linhas, [(1,)])

    def test_as_tres_unicidades_da_conta_dizem_coisas_diferentes(self) -> None:
        """A chave primaria fecha um lado; as duas `UNIQUE` fecham o outro.

        A primaria impede dois registos para o mesmo tenant. A
        `handoff_accounts_conta_uq` impede a **mesma conta do provedor em dois
        tenants**, que e o furo que o X-10 procura e que a primaria nao ve. E a
        `handoff_accounts_utilizador_uq` fecha o mesmo furo do lado do
        utilizador: o mesmo utilizador do provedor em dois tenants dava a um
        agente de uma PME um `access_token` que ve as conversas da outra. A
        conta fechada sem o utilizador fechado era meia fechadura.
        """
        linhas = dict(
            self.consultar(
                "SELECT conname::text, pg_get_constraintdef(oid) "
                "FROM pg_constraint "
                "WHERE conrelid = 'platform.handoff_accounts'::regclass "
                "AND contype IN ('p', 'u')"
            )
        )
        self.assertEqual(
            linhas,
            {
                "handoff_accounts_pkey": "PRIMARY KEY (tenant_id, provedor)",
                "handoff_accounts_conta_uq": "UNIQUE (provedor, account_id)",
                "handoff_accounts_utilizador_uq": (
                    "UNIQUE (provedor, provider_user_id)"
                ),
            },
        )

    def test_a_passagem_tem_indice_que_comeca_por_tenant_id(self) -> None:
        """A convencao da casa, e a `handoffs` e a primeira que nao a cumpre de graca.

        A chave primaria e o `handoff_id` derivado e nao leva `tenant_id`, pelo
        que a revisao acrescentou `(tenant_id, opened_at DESC)`. A segunda coluna
        e a consulta do SLA que a escolhe.
        """
        linhas = self.consultar(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'platform' AND tablename = 'handoffs' "
            "AND indexname = 'handoffs_tenant_idx'"
        )
        self.assertEqual(len(linhas), 1, "o indice por tenant nao existe")
        self.assertIn("tenant_id", linhas[0][0])
        self.assertIn("opened_at DESC", linhas[0][0])

    def test_nao_ha_check_sobre_o_resumed_at_nem_o_resolver(self) -> None:
        """**A ausencia e a assercao**, e tem razao escrita na revisao.

        Era o que apetecia («um instante de retoma so existe num `resumed`») e e
        o defeito que a `outbound_messages_entrega_ck` da `0010` pagou — uma
        restricao que recusa um estado que a propria maquina produz. Aqui e
        pior, porque **ninguem escreve estas duas colunas neste ticket**: o
        compare-and-set e do KAM-034, e a restricao seria descoberta por quem o
        fizer, contra linhas que ja existem.

        Este teste existe para que acrescentar essa restricao **passe por aqui**,
        e nao em silencio.
        """
        linhas = self.consultar(
            "SELECT conname::text, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'platform.handoffs'::regclass AND contype = 'c'"
        )
        definicoes = " ".join(d for _, d in linhas)
        self.assertNotIn("resumed_at", definicoes)
        self.assertNotIn("resolver", definicoes)
        # E as duas que **ha**: o dominio do estado e o motivo nao vazio.
        self.assertEqual(
            sorted(nome for nome, _ in linhas),
            ["handoffs_motivo_ck", "handoffs_status_ck"],
        )


class TestDowngradeDa0011(unittest.TestCase):
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
        self.copia = Path(self.pasta.name) / "copia-0011.json"
        self.tenants: list[str] = []
        os.environ.pop(VARIAVEL_DA_COPIA, None)

    def tearDown(self) -> None:
        os.environ.pop(VARIAVEL_DA_COPIA, None)
        try:
            if not em_head():
                alembic_ok("upgrade", "head")
            for tenant in self.tenants:
                self.cursor.execute(
                    "DELETE FROM platform.handoffs WHERE tenant_id = %s", (tenant,)
                )
                self.cursor.execute(
                    "DELETE FROM platform.handoff_accounts WHERE tenant_id = %s", (tenant,)
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
        """Duas passagens de dois tenants e duas contas de atendimento.

        Uma das passagens fica **em `resumed` com `resolver`**, e e a que torna o
        `downgrade` destrutivo de verdade: leva o historico que sustenta o SLA.
        """
        passagens: list[str] = []
        for indice in range(2):
            tenant = factories.tenant(self.cursor)
            self.tenants.append(tenant)
            canal = factories.canal(self.cursor, tenant)
            contacto = factories.contacto(self.cursor, tenant)
            conversa = str(uuid.uuid4())
            self.cursor.execute(
                "INSERT INTO platform.conversations "
                "(id, tenant_id, contact_id, channel_id) VALUES (%s, %s, %s, %s)",
                (conversa, tenant, contacto, canal),
            )
            identificador = f"h_{indice}_{uuid.uuid4().hex[:8]}"
            if indice == 0:
                self.cursor.execute(
                    "INSERT INTO platform.handoffs "
                    "(handoff_id, tenant_id, conversation_id, status, motivo, "
                    " external_id, resumed_at, resolver) "
                    "VALUES (%s, %s, %s, 'resumed', 'o cliente pediu', 'cw-1', "
                    "        now(), 'agente-7')",
                    (identificador, tenant, conversa),
                )
            else:
                self.cursor.execute(
                    "INSERT INTO platform.handoffs "
                    "(handoff_id, tenant_id, conversation_id, motivo) "
                    "VALUES (%s, %s, %s, 'o bot nao soube')",
                    (identificador, tenant, conversa),
                )
            passagens.append(identificador)
            self.cursor.execute(
                "INSERT INTO platform.handoff_accounts "
                "(tenant_id, provedor, account_id, inbox_id, bot_id, "
                " provider_user_id, token_ref, user_token_ref) "
                "VALUES (%s, 'chatwoot', %s, %s, %s, %s, %s, %s)",
                (
                    tenant,
                    900 + indice,
                    910 + indice,
                    920 + indice,
                    930 + indice,
                    f"ref/bot/{indice}",
                    f"ref/user/{indice}",
                ),
            )
        return {"passagens": passagens, "tenants": list(self.tenants)}

    def test_com_as_tabelas_vazias_desce_e_sobe_sem_pedir_copia(self) -> None:
        """Sem passagens nem contas nao ha nada a perder: nao pergunta."""
        for tabela in ("handoffs", "handoff_accounts"):
            self.cursor.execute(f"SELECT count(*) FROM platform.{tabela}")
            self.assertEqual(self.cursor.fetchone()[0], 0, tabela)

        alembic_ok("downgrade", "0010")
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0010)
        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)

    def test_com_linhas_e_sem_a_variavel_o_downgrade_recusa(self) -> None:
        """Nao ha perda em silencio: recusa, e a mensagem diz quantas e porque.

        **A contagem tem de ver as linhas**, e e por isso que este teste prende a
        ordem das instrucoes do `downgrade`: com `FORCE ROW LEVEL SECURITY` o
        dono esta sujeito a politica, e uma migracao corre sem contexto de
        tenant. Se os `disable_tenant_rls` nao fossem as primeiras instrucoes, o
        `count(*)` via **zero** sobre duas tabelas cheias — nao pedia copia e
        apagava em silencio.
        """
        self.semear()

        resultado = alembic("downgrade", "0010")

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout + resultado.stderr)
        saida = resultado.stdout + resultado.stderr
        self.assertIn("2 passagem(ns)", saida)
        self.assertIn("2 conta(s)", saida)
        self.assertIn(VARIAVEL_DA_COPIA, saida)
        # **A base ficou em `0011` e nao em `head`, e desde a `0012` a diferenca
        # existe.** O `downgrade` levanta na propria revisao e o Alembic corre
        # uma transaccao por revisao (`transaction_per_migration=True`), pelo
        # que descer de `head` para `0010` passa primeiro pela `0012`, que desce
        # e **compromete**, e so depois a `0011` recusa. A `media_assets` ja
        # caiu quando esta linha corre — e e a mesma nota que a propria `0011`
        # escreveu para o `TABELAS_ATE_0009`.
        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0011)
        self.cursor.execute("SELECT count(*) FROM platform.handoffs")
        self.assertEqual(self.cursor.fetchone()[0], 2)
        # E o `FORCE` das duas ficou **intacto**: a recusa nao pode trocar uma
        # perda de dados por um furo de isolamento.
        for tabela in ("handoffs", "handoff_accounts"):
            with self.subTest(tabela=tabela):
                self.cursor.execute(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    f"WHERE oid = 'platform.{tabela}'::regclass"
                )
                self.assertEqual(tuple(self.cursor.fetchone()), (True, True))

    def test_com_a_variavel_escreve_a_copia_e_desce(self) -> None:
        """A copia leva as nove colunas de cada passagem e as oito de cada conta."""
        semeadas = self.semear()
        os.environ[VARIAVEL_DA_COPIA] = str(self.copia)

        alembic_ok("downgrade", "0010")

        self.assertEqual(_tabelas(self.cursor), TABELAS_ATE_0010)
        self.assertTrue(self.copia.is_file(), "a copia logica nao foi escrita")
        copia = json.loads(self.copia.read_text(encoding="utf-8"))
        self.assertEqual(sorted(copia), ["handoff_accounts", "handoffs"])

        passagens = copia["handoffs"]
        self.assertEqual(len(passagens), 2)
        for linha in passagens:
            self.assertEqual(tuple(linha), COLUNAS_DA_COPIA_DE_HANDOFFS)
        self.assertEqual(
            {linha["handoff_id"] for linha in passagens}, set(semeadas["passagens"])
        )

        # **O historico da retomada esta na copia**, e e isso que justifica a
        # recusa: sem o `resumed_at` e o `resolver` nao ha SLA que se reconstrua.
        retomada = [l for l in passagens if l["status"] == "resumed"]
        self.assertEqual(len(retomada), 1)
        self.assertIsNotNone(retomada[0]["resumed_at"])
        self.assertEqual(retomada[0]["resolver"], "agente-7")
        self.assertEqual(retomada[0]["external_id"], "cw-1")
        # A que ficou a espera leva os tres a nulo.
        espera = [l for l in passagens if l["status"] == "waiting"]
        self.assertEqual(len(espera), 1)
        self.assertIsNone(espera[0]["resumed_at"])
        self.assertIsNone(espera[0]["resolver"])
        self.assertIsNone(espera[0]["external_id"])

        contas = copia["handoff_accounts"]
        self.assertEqual(len(contas), 2)
        for linha in contas:
            self.assertEqual(tuple(linha), COLUNAS_DA_COPIA_DE_CONTAS)
        # **Os identificadores da conta no provedor estao na copia**, e sao a
        # razao mais forte da recusa: eles ficam a existir **la fora**, e sem a
        # linha que os aponta o `ensureAccount` seguinte cria uma segunda conta
        # para a mesma PME — que e o que o criterio 1 proibe, e que nenhuma
        # migracao nossa pode desfazer porque o recurso nao e nosso.
        self.assertEqual(
            sorted(linha["account_id"] for linha in contas), ["900", "901"]
        )
        self.assertEqual({linha["provedor"] for linha in contas}, {"chatwoot"})

        alembic_ok("upgrade", "head")
        self.assertEqual(_tabelas(self.cursor), TABELAS)
        self.cursor.execute("SELECT count(*) FROM platform.handoffs")
        self.assertEqual(self.cursor.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
