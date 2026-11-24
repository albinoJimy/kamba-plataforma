"""A imagem da resposta do AGR contra o PostgreSQL (KAM-246, revisao `0092`).

O que os duplos de `services/agr/tests/test_saida.py` nao provam, e so a base
diz:

| Propriedade | Porque precisa da base |
|---|---|
| a resposta com imagem grava a chave da arte, e emite um evento sem ela | o `SQL_INSERIR_COM_MEDIA` e a `evt_emitir`, na mesma transaccao |
| uma chave de outro tenant, de outra classe ou um URL recusam | o `agent_replies_media_ref_ck`, que confere o tenant contra o da linha |
| uma imagem com *template* recusa | o `agent_replies_media_sem_template_ck` |
| o `kamba_app` nao muda a imagem de uma resposta emitida | o `UPDATE` por coluna, so o `entregue_at` |
| a resposta de texto livre continua sem imagem | o `SQL_INSERIR` do KAM-224, intacto |

As instrucoes sao as de `kamba_agr.saida`; as recusas da base provam-se com a
instrucao do modulo, sem a guarda Python (que recusa antes de chegar aqui).
"""

from __future__ import annotations

import tests_agr.test_agent_replies as resposta_do_agr
from tests.base import PRIVILEGIO_INSUFICIENTE, VIOLACAO_DE_CHECK, sqlstate

# O `tests_agr.base` poe o `services/agr/src` no caminho, e por isso vem antes.
from kamba_agr import saida  # noqa: E402
from kamba_core import tenant_guard  # noqa: E402

UUID_DO_OBJECTO = "0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b"


class TestImagemDaResposta(resposta_do_agr.ComSaida):
    def _arte(self, tenant: str | None = None, classe: str = "arte") -> str:
        return f"t/{tenant or self.tenant}/{classe}/2026/11/{UUID_DO_OBJECTO}"

    def _media(self) -> list[tuple]:
        self.semente.execute(
            "SELECT chave, media_ref FROM platform.agent_replies WHERE tenant_id = %s ORDER BY criado_at",
            (self.tenant,),
        )
        return [tuple(linha) for linha in self.semente.fetchall()]

    def test_a_resposta_com_imagem_grava_a_chave_e_emite_uma_vez_sem_ela(self) -> None:
        arte = self._arte()
        primeira = self.emitir(chave="arte:1", media=arte, botoes=("falar_com_humano",))
        repetida = self.emitir(chave="arte:1", media=arte, botoes=("falar_com_humano",))
        self.assertIsNotNone(primeira)
        self.assertIsNone(repetida)
        self.assertEqual(self._media(), [("arte:1", arte)])
        eventos = self._eventos()
        self.assertEqual(len(eventos), 1)
        # O `agent.replied` nao muda: o consumidor le a imagem pela linha.
        self.assertNotIn(arte, str(eventos[0]))
        self.assertEqual(
            set(eventos[0]["payload"]), {"reply_id", "thread_id", "conversation_id", "contact_id", "canal"}
        )

    def test_a_resposta_de_texto_livre_continua_sem_imagem(self) -> None:
        self.emitir()
        self.assertEqual(self._media(), [("wamid.ensaio:0", None)])

    def _inserir(self, media: str, template: str | None = None) -> None:
        c = self.conversa
        with tenant_guard.tx(self.app, self.tenant) as cursor:
            if template is None:
                cursor.execute(
                    saida.SQL_INSERIR_COM_MEDIA,
                    (self.tenant, "k:recusa", c.contact_id, c.conversation_id, "whatsapp",
                     "ola", "[]", None, media),
                )
            else:
                cursor.execute(
                    "INSERT INTO platform.agent_replies (tenant_id, chave, contact_id, conversation_id, "
                    "canal, texto, botoes, template_nome, media_ref) "
                    "VALUES (%s, %s, %s, %s, 'whatsapp', 'ola', '[]'::jsonb, %s, %s)",
                    (self.tenant, "k:recusa", c.contact_id, c.conversation_id, template, media),
                )

    def test_a_base_recusa_a_chave_alheia_de_outra_classe_um_url_e_a_imagem_com_template(self) -> None:
        outro = "9e8d7c6b-5a4f-4e3d-8c2b-1a0f9e8d7c6b"
        for media in (
            self._arte(tenant=outro),            # de outro tenant
            self._arte(classe="foto"),            # de outra classe
            "https://exemplo.invalid/arte.jpg",  # um URL
            self._arte() + "/x",                  # fora da forma
            self._arte().upper(),                 # em maiusculas
        ):
            with self.subTest(media=media):
                with self.assertRaises(Exception) as erro:
                    self._inserir(media)
                self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)
        with self.assertRaises(Exception) as erro:
            self._inserir(self._arte(), template="orcamento_pronto")
        self.assertEqual(sqlstate(erro.exception), VIOLACAO_DE_CHECK)
        self.assertEqual(self._media(), [])

    def test_o_kamba_app_nao_muda_a_imagem_de_uma_resposta_emitida(self) -> None:
        arte = self._arte()
        self.emitir(chave="arte:1", media=arte)
        with self.assertRaises(Exception) as erro:
            with tenant_guard.tx(self.app, self.tenant) as cursor:
                cursor.execute(
                    "UPDATE platform.agent_replies SET media_ref = NULL WHERE tenant_id = %s", (self.tenant,)
                )
        self.assertEqual(sqlstate(erro.exception), PRIVILEGIO_INSUFICIENTE)
        self.assertEqual(self._media(), [("arte:1", arte)])
