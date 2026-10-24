"""O contrato `agent_invocation` le-se por forma, e o `tenant_id` nao se move.

Criterio 1 (a API recusa o que nao e contrato), os «Testes Requeridos» (unit:
construcao de `thread_id`) e o DoD de isolamento e de privacidade.
"""

from __future__ import annotations

import dataclasses
import unittest
import uuid

from apoio import invocacao_crua
from kamba_agr.contexto import (
    CAMPOS,
    MODOS,
    VERTICAIS,
    WAMID_MAXIMO,
    InvocacaoInvalidaError,
    ler_invocacao,
    thread_id_de,
)


class TestLeitura(unittest.TestCase):
    def test_um_contrato_valido_le_se_nos_nove_campos(self) -> None:
        corpo = invocacao_crua()
        invocacao = ler_invocacao(corpo)
        for campo in CAMPOS:
            self.assertEqual(getattr(invocacao, campo), corpo[campo])

    def test_o_turn_id_e_o_wamid_e_nao_um_campo_novo(self) -> None:
        # Dicionario §3.13: duplicar o mesmo valor com dois nomes num contrato
        # era pedir que divergissem. Logo o `turn_id` e derivado.
        invocacao = ler_invocacao(invocacao_crua())
        self.assertEqual(invocacao.turn_id, invocacao.wamid)
        self.assertNotIn("turn_id", CAMPOS)

    def test_a_chave_de_envio_e_turn_id_dois_pontos_seq(self) -> None:
        invocacao = ler_invocacao(invocacao_crua())
        self.assertEqual(invocacao.chave_de_envio(0), f"{invocacao.wamid}:0")
        self.assertEqual(invocacao.chave_de_envio(7), f"{invocacao.wamid}:7")

    def test_a_mesma_chave_em_duas_voltas_do_mesmo_turno(self) -> None:
        # E o criterio 4: «0 duplicados» tem de ser consequencia da repeticao e
        # nao coincidencia. Duas leituras do mesmo corpo dao a mesma chave.
        corpo = invocacao_crua()
        self.assertEqual(
            ler_invocacao(corpo).chave_de_envio(3),
            ler_invocacao(corpo).chave_de_envio(3),
        )

    def test_um_seq_negativo_recusa(self) -> None:
        with self.assertRaises(ValueError):
            ler_invocacao(invocacao_crua()).chave_de_envio(-1)

    def test_a_invocacao_e_imutavel(self) -> None:
        # «`tenant_id` injectado pelo CHR; imutavel» (`docs/tecnica/02` §5.3)
        # deixa de ser uma frase e passa a ser uma propriedade do tipo.
        invocacao = ler_invocacao(invocacao_crua())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            invocacao.tenant_id = str(uuid.uuid4())  # type: ignore[misc]


class TestRecusas(unittest.TestCase):
    def test_o_que_nao_e_objecto_recusa(self) -> None:
        for corpo in ([], "x", 1, None, True):
            with self.subTest(corpo=corpo), self.assertRaises(InvocacaoInvalidaError):
                ler_invocacao(corpo)

    def test_um_campo_a_mais_recusa_em_vez_de_se_ignorar(self) -> None:
        corpo = invocacao_crua()
        corpo["turn_id"] = corpo["wamid"]
        with self.assertRaises(InvocacaoInvalidaError) as apanhado:
            ler_invocacao(corpo)
        self.assertEqual(apanhado.exception.codigo, "campo_desconhecido")

    def test_o_codigo_de_um_campo_a_mais_nao_repete_o_nome_que_veio_de_fora(self) -> None:
        corpo = invocacao_crua()
        corpo["telefone_do_cliente"] = "+244923456789"
        with self.assertRaises(InvocacaoInvalidaError) as apanhado:
            ler_invocacao(corpo)
        self.assertNotIn("telefone", apanhado.exception.codigo)
        self.assertNotIn("923456789", str(apanhado.exception))

    def test_cada_campo_em_falta_recusa(self) -> None:
        for campo in CAMPOS:
            corpo = invocacao_crua()
            del corpo[campo]
            with self.subTest(campo=campo), self.assertRaises(
                InvocacaoInvalidaError
            ) as apanhado:
                ler_invocacao(corpo)
            self.assertEqual(apanhado.exception.codigo, "campo_em_falta")

    def test_um_campo_que_nao_e_texto_recusa(self) -> None:
        for campo in CAMPOS:
            with self.subTest(campo=campo), self.assertRaises(InvocacaoInvalidaError):
                ler_invocacao(invocacao_crua(**{campo: 7}))

    def test_os_quatro_identificadores_tem_de_ser_uuid(self) -> None:
        for campo in ("tenant_id", "contact_id", "conversation_id", "channel_id"):
            for valor in ("", "nao-e-uuid", "923456789", str(uuid.uuid4()).upper()):
                corpo = invocacao_crua(**{campo: valor})
                if campo in ("tenant_id", "contact_id"):
                    corpo["thread_id"] = thread_id_de(
                        corpo["tenant_id"], corpo["contact_id"]
                    )
                with self.subTest(campo=campo, valor=valor), self.assertRaises(
                    InvocacaoInvalidaError
                ):
                    ler_invocacao(corpo)

    def test_um_wamid_sem_forma_ou_sem_tecto_recusa(self) -> None:
        for valor in ("", "curto", "a" * (WAMID_MAXIMO + 1), "com espaco aqui"):
            with self.subTest(valor=valor[:12]), self.assertRaises(
                InvocacaoInvalidaError
            ):
                ler_invocacao(invocacao_crua(wamid=valor))

    def test_so_os_quatro_modos_do_check_passam(self) -> None:
        for modo in MODOS:
            with self.subTest(modo=modo):
                self.assertEqual(ler_invocacao(invocacao_crua(modo=modo)).modo, modo)
        for modo in ("", "BOT", "desconhecido", "bot "):
            with self.subTest(modo=modo), self.assertRaises(InvocacaoInvalidaError):
                ler_invocacao(invocacao_crua(modo=modo))

    def test_a_vertical_e_lista_de_permitidas_e_nao_de_proibidas(self) -> None:
        # A licao do criterio 5 do KAM-014: uma comparacao por igualdade com
        # `assistente` nao via `assistente_v2`.
        for vertical in VERTICAIS:
            with self.subTest(vertical=vertical):
                self.assertEqual(
                    ler_invocacao(invocacao_crua(vertical=vertical)).vertical, vertical
                )
        for vertical in ("assistente", "assistente_v2", "vendedor_v2", ""):
            with self.subTest(vertical=vertical), self.assertRaises(
                InvocacaoInvalidaError
            ):
                ler_invocacao(invocacao_crua(vertical=vertical))

    def test_um_thread_id_incoerente_recusa_em_vez_de_se_recalcular(self) -> None:
        # E a tranca que depende do `thread_id`: recalcula-lo em silencio sobre
        # um contrato incoerente era serializar pela chave errada.
        outro = str(uuid.uuid4())
        corpo = invocacao_crua()
        corpo["thread_id"] = thread_id_de(outro, corpo["contact_id"])
        with self.assertRaises(InvocacaoInvalidaError) as apanhado:
            ler_invocacao(corpo)
        self.assertEqual(apanhado.exception.codigo, "thread_id_incoerente")

    def test_um_thread_id_coerente_consigo_e_nao_com_o_par_recusa(self) -> None:
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        corpo = invocacao_crua()
        corpo["thread_id"] = thread_id_de(a, b)
        with self.assertRaises(InvocacaoInvalidaError):
            ler_invocacao(corpo)


class TestThreadId(unittest.TestCase):
    def test_e_tenant_dois_pontos_contacto_e_nunca_telefone(self) -> None:
        # ADR-010: o telefone nunca e chave. O exploratorio escrevia
        # `msisdn_hash+tenant` e o `docs/tecnica/02` §12 corrige-o.
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        thread = thread_id_de(tenant, contacto)
        self.assertEqual(thread, f"{tenant}:{contacto}")
        self.assertNotIn("244", thread.replace(tenant, "").replace(contacto, ""))

    def test_e_o_espelho_do_threadIdDe_do_typescript(self) -> None:
        # Nao se compara codigo: compara-se o **texto** do TypeScript, que e o
        # que pode divergir. E o padrao do `TestParidadeDoTypeScript` do TEN.
        from pathlib import Path

        fonte = (
            Path(__file__).resolve().parents[3]
            / "packages"
            / "core-ts"
            / "src"
            / "chr"
            / "contrato.ts"
        ).read_text(encoding="utf-8")
        self.assertIn("return `${tenantId}:${contactId}`;", fonte)


if __name__ == "__main__":
    unittest.main()
