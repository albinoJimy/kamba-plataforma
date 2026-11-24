"""A leitura da foto de um turno do painel pelo AGR, contra o PostgreSQL (KAM-243).

O turno da foto do painel nao traz `message_id`, e a prova de que o contacto e o
dono — que o turno de texto faz no `SQL_LER_MENSAGEM` — faz-se aqui, sobre a
linha da `platform.media_assets` (achado 1 da revisao adversarial). O que so a
base diz:

| Propriedade | Porque precisa da base |
|---|---|
| a foto le-se com o tenant, o contacto e a conversa da invocacao | o `WHERE` |
| so `armazenado`, da classe `media_imagem` e com o `media_id` do painel | as tres condicoes |
| so se o contacto for o dono vivo do tenant | o `EXISTS` sobre a `contacts` |
| um tenant nao le a foto de outro, nem com o `asset_id` certo | a RLS `FORCE` |

A instrucao e a de `kamba_agr.mensagens`, chamada pela funcao do modulo.
"""

from __future__ import annotations

import dataclasses
import uuid

from tests_agr.base import ComAgr

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr import mensagens  # noqa: E402
from kamba_agr.contexto import InvocacaoDoAgente  # noqa: E402


class ComFotos(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        self.conversa = self.criar_conversa()
        self.tenant = self.conversa.tenant_id
        self.tornar_dono(self.conversa)
        self.addCleanup(self._limpar_fotos)
        self.app = self.ligar("app")

    def tornar_dono(self, conversa) -> None:
        self.semente.execute(
            "UPDATE platform.contacts SET papel = 'dono' WHERE tenant_id = %s AND contact_id = %s",
            (conversa.tenant_id, conversa.contact_id),
        )

    def _limpar_fotos(self) -> None:
        for tenant in self._tenants:
            self.semente.execute("DELETE FROM platform.media_assets WHERE tenant_id = %s", (tenant,))

    def guardar(
        self,
        conversa=None,
        *,
        media_id: str | None = None,
        estado: str = "armazenado",
        classe: str = "media_imagem",
    ) -> str:
        c = conversa or self.conversa
        media_id = media_id or f"painel.{uuid.uuid4()}"
        armazenado = estado == "armazenado"
        self.semente.execute(
            "INSERT INTO platform.media_assets "
            "(tenant_id, contact_id, conversation_id, wamid, media_id, classe, estado, "
            " content_type, size, sha256, storage_ref) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING asset_id::text",
            (
                c.tenant_id,
                c.contact_id,
                c.conversation_id,
                media_id,
                media_id,
                classe,
                estado,
                "image/jpeg" if armazenado else None,
                10 if armazenado else None,
                "0" * 64 if armazenado else None,
                f"t/{c.tenant_id}/{classe}/2026/11/x" if armazenado else None,
            ),
        )
        return self.semente.fetchone()[0]

    def invocacao(self, asset_id: str, conversa=None, **sobrepor) -> InvocacaoDoAgente:
        c = conversa or self.conversa
        base = InvocacaoDoAgente(
            tenant_id=c.tenant_id,
            contact_id=c.contact_id,
            conversation_id=c.conversation_id,
            channel_id=c.canal_id,
            wamid=f"painel.{asset_id}.{uuid.uuid4().hex}",
            type="image",
            modo="bot",
            thread_id=c.thread_id,
            vertical="vendedor",
            persona="dono",
            asset_id=asset_id,
        )
        return dataclasses.replace(base, **sobrepor)

    def le(self, invocacao: InvocacaoDoAgente) -> bool:
        return mensagens.ler_foto_do_painel_sincrono(self.app, invocacao)


class TestALeitura(ComFotos):
    def test_a_foto_do_dono_guardada_pelo_painel_le_se(self) -> None:
        self.assertTrue(self.le(self.invocacao(self.guardar())))

    def test_com_outro_contacto_ou_outra_conversa_nao_se_le(self) -> None:
        asset = self.guardar()
        outra = self.criar_conversa()
        for campo, valor in (
            ("contact_id", outra.contact_id),
            ("conversation_id", outra.conversation_id),
        ):
            with self.subTest(campo=campo):
                self.assertFalse(self.le(self.invocacao(asset, **{campo: valor})))

    def test_um_cliente_nao_passa_por_dono_com_a_foto_dele(self) -> None:
        # O achado 1 da revisao: um cliente do tenant, a conversa dele e uma foto
        # `armazenado` dele. Com a credencial do painel era um turno do dono.
        cliente = self.criar_conversa()
        asset = self.guardar(cliente)
        self.assertFalse(self.le(self.invocacao(asset, conversa=cliente)))
        # O controlo: o mesmo, com o contacto feito dono, le-se.
        self.tornar_dono(cliente)
        self.assertTrue(self.le(self.invocacao(asset, conversa=cliente)))

    def test_um_dono_apagado_deixa_de_se_ler(self) -> None:
        asset = self.guardar()
        self.semente.execute(
            "UPDATE platform.contacts SET erased_at = now() WHERE tenant_id = %s AND contact_id = %s",
            (self.tenant, self.conversa.contact_id),
        )
        self.assertFalse(self.le(self.invocacao(asset)))

    def test_so_uma_foto_armazenado_do_painel(self) -> None:
        casos = {
            "pendente": self.guardar(estado="pendente"),
            "falhou": self.guardar(estado="falhou"),
            "audio": self.guardar(classe="media_audio"),
            "do whatsapp": self.guardar(media_id=f"meta-{uuid.uuid4().hex}"),
        }
        for nome, asset in casos.items():
            with self.subTest(nome):
                self.assertFalse(self.le(self.invocacao(asset)))

    def test_outro_tenant_nao_le_a_foto_nem_com_o_asset_id(self) -> None:
        asset = self.guardar()
        b = self.criar_conversa()
        self.tornar_dono(b)
        self.assertFalse(self.le(self.invocacao(asset, conversa=b)))
