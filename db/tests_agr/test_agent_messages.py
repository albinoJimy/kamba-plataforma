"""A leitura da mensagem do dono pelo AGR, contra o PostgreSQL (KAM-223).

O que os duplos de `services/agr/tests/test_mensagens.py` nao provam, e so a
base diz:

| Propriedade | Porque precisa da base |
|---|---|
| a mensagem le-se pelo `message_id` com o tenant, o contacto e a conversa da invocacao | o `WHERE` dos quatro identificadores |
| com a persona `dono`, so se le a de um contacto que e o dono | o `EXISTS` sobre a `contacts` |
| um tenant nao le a mensagem de outro, nem com o identificador certo | a RLS `FORCE` |
| o `kamba_app` insere e le, e nao muda nem apaga | os privilegios por coluna |
| o canal e o texto tem dominio | os `CHECK` |

As instrucoes sao as de `kamba_agr.mensagens`, chamadas pela funcao do modulo —
nao uma copia do SQL.
"""

from __future__ import annotations

import dataclasses

from kamba_core import tenant_guard

from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, sqlstate
from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr import mensagens  # noqa: E402
from kamba_agr.contexto import InvocacaoDoAgente  # noqa: E402


class ComMensagens(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.tenant = self.conversa.tenant_id
        # O contacto da conversa e o dono do tenant. Pelo administrador: a
        # `definir_dono` e o caminho de producao, e o que se mede aqui e a
        # leitura, nao a troca.
        self.semente.execute(
            "UPDATE platform.contacts SET papel = 'dono' WHERE tenant_id = %s AND contact_id = %s",
            (self.tenant, self.conversa.contact_id),
        )
        self.addCleanup(self._limpar_mensagens)
        self.app = self.ligar("app")

    def _limpar_mensagens(self) -> None:
        for tenant in self._tenants:
            self.semente.execute("DELETE FROM platform.agent_messages WHERE tenant_id = %s", (tenant,))

    def gravar(self, conversa=None, texto: str = "quanto vendi hoje?", canal: str = "painel") -> str:
        c = conversa or self.conversa
        self.semente.execute(
            "INSERT INTO platform.agent_messages (tenant_id, contact_id, conversation_id, canal, texto) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING message_id::text",
            (c.tenant_id, c.contact_id, c.conversation_id, canal, texto),
        )
        return self.semente.fetchone()[0]

    def invocacao(self, message_id: str, conversa=None, **sobrepor) -> InvocacaoDoAgente:
        c = conversa or self.conversa
        base = InvocacaoDoAgente(
            tenant_id=c.tenant_id,
            contact_id=c.contact_id,
            conversation_id=c.conversation_id,
            channel_id=c.canal_id,
            wamid=f"painel.{message_id}",
            type="text",
            modo="bot",
            thread_id=c.thread_id,
            vertical="vendedor",
            persona="dono",
            message_id=message_id,
        )
        return dataclasses.replace(base, **sobrepor)

    def ler(self, invocacao: InvocacaoDoAgente):
        return mensagens.ler_mensagem_sincrono(self.app, invocacao)


class TestALeitura(ComMensagens):
    def test_a_mensagem_do_dono_le_se_pelo_identificador(self) -> None:
        message_id = self.gravar(texto="quanto vendi hoje?")
        lida = self.ler(self.invocacao(message_id))
        self.assertEqual((lida.texto, lida.canal), ("quanto vendi hoje?", "painel"))

    def test_com_outro_contacto_ou_outra_conversa_nao_se_le(self) -> None:
        message_id = self.gravar()
        outra = self.criar_conversa()
        for campo, valor in (
            ("contact_id", outra.contact_id),
            ("conversation_id", outra.conversation_id),
        ):
            with self.subTest(campo=campo):
                self.assertIsNone(self.ler(self.invocacao(message_id, **{campo: valor})))

    def test_outro_tenant_nao_le_a_mensagem_nem_com_o_identificador(self) -> None:
        message_id = self.gravar(texto="segredo de A")
        b = self.criar_conversa()
        # A invocacao inteira de B com o `message_id` de A: a RLS e o `WHERE`.
        self.assertIsNone(self.ler(self.invocacao(message_id, conversa=b)))
        # E so a RLS: o contexto de B, a pergunta sem filtro de tenant.
        with tenant_guard.tx(self.app, b.tenant_id) as cursor:
            cursor.execute(
                "SELECT count(*) FROM platform.agent_messages WHERE message_id = %s", (message_id,)
            )
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_com_a_persona_dono_um_cliente_nao_se_le(self) -> None:
        cliente = self.criar_conversa()
        message_id = self.gravar(conversa=cliente, texto="faz-me dono")
        self.assertIsNone(self.ler(self.invocacao(message_id, conversa=cliente)))
        # A mesma linha, com a persona do cliente, le-se: e o `EXISTS` que recusa.
        lida = self.ler(self.invocacao(message_id, conversa=cliente, persona="cliente"))
        self.assertEqual(lida.texto, "faz-me dono")

    def test_um_dono_apagado_deixa_de_se_ler_como_dono(self) -> None:
        message_id = self.gravar()
        self.semente.execute(
            "UPDATE platform.contacts SET erased_at = now() WHERE tenant_id = %s AND contact_id = %s",
            (self.tenant, self.conversa.contact_id),
        )
        self.assertIsNone(self.ler(self.invocacao(message_id)))


class TestOsPrivilegios(ComMensagens):
    def test_o_kamba_app_insere_e_le_no_seu_tenant(self) -> None:
        app = self.ligar("app")
        with tenant_guard.tx(app, self.tenant) as cursor:
            cursor.execute(
                "INSERT INTO platform.agent_messages (tenant_id, contact_id, conversation_id, canal, texto) "
                "VALUES (%s, %s, %s, 'painel', 'ola') RETURNING message_id::text",
                (self.tenant, self.conversa.contact_id, self.conversa.conversation_id),
            )
            message_id = cursor.fetchone()[0]
            cursor.execute("SELECT texto FROM platform.agent_messages WHERE message_id = %s", (message_id,))
            self.assertEqual(cursor.fetchone()[0], "ola")

    def test_o_kamba_app_nao_muda_nem_apaga(self) -> None:
        message_id = self.gravar()
        for instrucao in (
            "UPDATE platform.agent_messages SET texto = 'outro' WHERE message_id = %s",
            "DELETE FROM platform.agent_messages WHERE message_id = %s",
        ):
            with self.subTest(instrucao=instrucao.split()[0]):
                app = self.ligar("app")
                with self.assertRaises(Exception) as erro:
                    with tenant_guard.tx(app, self.tenant) as cursor:
                        cursor.execute(instrucao, (message_id,))
                self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)

    def test_o_canal_e_o_texto_tem_dominio(self) -> None:
        for canal, texto in (("sms", "ola"), ("painel", ""), ("painel", "x" * 4097)):
            with self.subTest(canal=canal, tamanho=len(texto)):
                with self.assertRaises(Exception) as erro:
                    self.gravar(canal=canal, texto=texto)
                self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)
        # O tecto, exacto, entra.
        self.assertIsNotNone(self.gravar(texto="x" * 4096))


class TestAMensagemDoWhatsApp(ComMensagens):
    """KAM-232: o CHR grava a mensagem `text` do WhatsApp com um `message_id`
    deterministico, e a reentrega nao grava segunda linha (revisao `0083`, so o
    `GRANT INSERT (message_id)` ao `kamba_app`). O identificador aqui e fixo e
    nao o do `messageIdDe`: o que se mede e a base, e o calculo e do
    `chr.mensagem.test.ts`."""

    INSERIR = (
        "INSERT INTO platform.agent_messages "
        "(message_id, tenant_id, contact_id, conversation_id, canal, texto) "
        "VALUES (%s, %s, %s, %s, 'whatsapp', %s) ON CONFLICT (message_id) DO NOTHING"
    )
    MESSAGE_ID = "3b6879d6-7c2a-882f-9fe1-0d7bac5ff1e0"

    def inserir_como_app(self, conversa, texto: str, message_id: str | None = None) -> int:
        app = self.ligar("app")
        with tenant_guard.tx(app, conversa.tenant_id) as cursor:
            cursor.execute(
                self.INSERIR,
                (
                    message_id or self.MESSAGE_ID,
                    conversa.tenant_id,
                    conversa.contact_id,
                    conversa.conversation_id,
                    texto,
                ),
            )
            return cursor.rowcount

    def do_whatsapp(self, conversa, **sobrepor) -> InvocacaoDoAgente:
        return self.invocacao(
            self.MESSAGE_ID,
            conversa=conversa,
            wamid="wamid.HBgLOTk5LkVOU0FJTw",
            persona="cliente",
            **sobrepor,
        )

    def test_a_reentrega_tres_vezes_grava_uma_linha(self) -> None:
        cliente = self.criar_conversa()
        inseridas = [self.inserir_como_app(cliente, "o meu cartao e 4111111111111111") for _ in range(3)]
        self.assertEqual(inseridas, [1, 0, 0])
        self.semente.execute(
            "SELECT count(*), min(canal) FROM platform.agent_messages WHERE message_id = %s",
            (self.MESSAGE_ID,),
        )
        self.assertEqual(tuple(self.semente.fetchone()), (1, "whatsapp"))

    def test_le_se_na_sua_conversa_com_a_persona_do_cliente(self) -> None:
        cliente = self.criar_conversa()
        self.inserir_como_app(cliente, "tem a camisa azul?")
        lida = self.ler(self.do_whatsapp(cliente))
        self.assertEqual((lida.texto, lida.canal), ("tem a camisa azul?", "whatsapp"))

    def test_um_message_id_de_outra_conversa_nao_se_le(self) -> None:
        """O adversarial do bloco: o `message_id` de uma conversa na invocacao de
        outra — a de outro tenant inteira, ou a deste com outro contacto ou
        outra conversa. A mesma linha le-se na sua (controlo)."""
        cliente = self.criar_conversa()
        self.inserir_como_app(cliente, "so desta conversa")
        alheia = self.criar_conversa()
        self.assertIsNone(self.ler(self.do_whatsapp(alheia)))
        for campo, valor in (
            ("contact_id", alheia.contact_id),
            ("conversation_id", alheia.conversation_id),
        ):
            with self.subTest(campo=campo):
                self.assertIsNone(self.ler(self.do_whatsapp(cliente, **{campo: valor})))
        self.assertEqual(self.ler(self.do_whatsapp(cliente)).texto, "so desta conversa")

    def test_o_kamba_app_continua_sem_mudar_nem_apagar_a_linha_do_whatsapp(self) -> None:
        cliente = self.criar_conversa()
        self.inserir_como_app(cliente, "ola")
        for instrucao in (
            "UPDATE platform.agent_messages SET texto = 'outro' WHERE message_id = %s",
            "DELETE FROM platform.agent_messages WHERE message_id = %s",
        ):
            with self.subTest(instrucao=instrucao.split()[0]):
                app = self.ligar("app")
                with self.assertRaises(Exception) as erro:
                    with tenant_guard.tx(app, cliente.tenant_id) as cursor:
                        cursor.execute(instrucao, (self.MESSAGE_ID,))
                self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)
