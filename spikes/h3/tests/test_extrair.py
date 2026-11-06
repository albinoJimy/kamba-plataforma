"""Do corpo da Meta para as linhas do registo (KAM-100).

O ticket pede, nos «Testes Requeridos», «subscricao dos campos». E isso tem duas
metades que se confundem com facilidade:

    os cinco campos subscritos produzem linha
    os outros seis do §4.4 **nao** produzem linha

A segunda e a que mede alguma coisa. Um extractor que aceitasse tudo passava a
primeira metade e enchia o ficheiro de evidencia com eventos de template.

As formas dos corpos sao as de `tools/meta-sim/src/campos.ts`, e herdam-se os
estados que ele declara: o nome do array dos ecos e **proposta**, e a forma
interna de `history` e de `smb_app_state_sync` e **INDICIO**. Por isso ha um
ensaio para o caso em que a forma vem diferente do esperado — tem de produzir
menos campos, nao uma excepcao.
"""

from __future__ import annotations

import unittest

from extrair import ARRAY_DOS_ECHOES, CAMPOS_SUBSCRITOS, extrair
from registo import validar

INSTANTE = "2026-11-06T10:00:00.000Z"
CANAL = "900900900900900"
ROTULOS = {CANAL: "N1"}

#: Um `wamid` de ensaio. O base64 e texto, nao um numero codificado.
WAMID = "wamid.SElUT1JJQ09ERU5TQUlPREVIMzEyMw=="
OUTRO_WAMID = "wamid.T1VUUk9JREVOU0FJT0RFSDMxMjM0NQ=="

#: Os seis campos do §4.4 que este spike **nao** subscreve.
NAO_SUBSCRITOS = (
    "phone_number_quality_update",
    "business_capability_update",
    "account_alerts",
    "message_template_status_update",
    "template_category_update",
    "message_template_quality_update",
)


def corpo(campo: str, valor: dict) -> dict:
    """Um corpo de webhook com um `change` do campo dado."""
    base = {"messaging_product": "whatsapp", "metadata": {"phone_number_id": CANAL}}
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1" * 15, "changes": [{"field": campo, "value": {**base, **valor}}]}],
    }


def extrair_de(campo: str, valor: dict, nossos: tuple[str, ...] = ()) -> list[dict]:
    return extrair(corpo(campo, valor), ROTULOS, nossos, INSTANTE)


class TestSubscricao(unittest.TestCase):
    def test_os_cinco_campos_subscritos_sao_os_do_ticket(self) -> None:
        self.assertEqual(
            set(CAMPOS_SUBSCRITOS),
            {
                "messages",
                "history",
                "smb_app_state_sync",
                "smb_message_echoes",
                "account_update",
            },
        )

    def test_os_seis_campos_nao_subscritos_nao_produzem_linha(self) -> None:
        """A metade que mede: o endpoint e um so e recebe os onze campos."""
        for campo in NAO_SUBSCRITOS:
            with self.subTest(campo=campo):
                self.assertEqual(extrair_de(campo, {"event": "APPROVED"}), [])

    def test_um_campo_inventado_nao_produz_linha(self) -> None:
        self.assertEqual(extrair_de("campo_que_a_meta_ainda_nao_tem", {"x": 1}), [])

    def test_toda_a_linha_produzida_passa_a_allowlist(self) -> None:
        """O invariante que liga os dois modulos.

        Se `extrair` produzisse uma chave fora de `registo.PERMITIDOS`, o
        receptor levantava **em execucao**, com o evento perdido. Mede-se aqui,
        sobre todos os ramos, em vez de se descobrir em campo.
        """
        casos = [
            ("messages", {"messages": [{"id": WAMID, "timestamp": "1790812800",
                                        "context": {"id": OUTRO_WAMID}}]}),
            ("smb_message_echoes", {ARRAY_DOS_ECHOES: [{"id": WAMID,
                                                        "timestamp": "1790812800"}]}),
            ("history", {"history": [{"metadata": {"phase": 0, "chunk_order": 1,
                                                   "progress": 100},
                                      "threads": [{"messages": [{}, {}]}],
                                      "errors": [{"code": 2593109}]}]}),
            ("smb_app_state_sync", {"state_sync": [{"metadata": {"phase": 1},
                                                    "contact": {}}]}),
            ("account_update", {"event": "PARTNER_REMOVED",
                                "partner_removed_info": {"reason": "PRIMARY_INACTIVITY"}}),
        ]
        for campo, valor in casos:
            with self.subTest(campo=campo):
                linhas = extrair_de(campo, valor)
                self.assertTrue(linhas, f"{campo} nao produziu linha")
                for linha in linhas:
                    self.assertEqual(validar(linha), linha)


class TestEcoDaApi(unittest.TestCase):
    """A medicao do item NAO VERIFICADO de `docs/tecnica/01` §10.3."""

    def test_eco_de_um_wamid_nosso_marca_true(self) -> None:
        linhas = extrair_de(
            "smb_message_echoes",
            {ARRAY_DOS_ECHOES: [{"id": WAMID, "timestamp": "1790812800"}]},
            nossos=(WAMID,),
        )
        self.assertEqual([l["enviada_por_nos"] for l in linhas], [True])

    def test_eco_de_um_wamid_alheio_marca_false(self) -> None:
        linhas = extrair_de(
            "smb_message_echoes",
            {ARRAY_DOS_ECHOES: [{"id": WAMID, "timestamp": "1790812800"}]},
            nossos=(OUTRO_WAMID,),
        )
        self.assertEqual([l["enviada_por_nos"] for l in linhas], [False])

    def test_o_wamid_nosso_nao_entra_na_linha(self) -> None:
        """O confronto faz-se com o valor em claro e **nao** o guarda."""
        linhas = extrair_de(
            "smb_message_echoes",
            {ARRAY_DOS_ECHOES: [{"id": WAMID, "timestamp": "1790812800"}]},
            nossos=(WAMID,),
        )
        self.assertNotIn(WAMID, str(linhas))
        self.assertRegex(linhas[0]["id"], r"^m_[0-9a-f]{32}$")

    def test_eco_sem_id_nao_leva_a_marca(self) -> None:
        """Sem `wamid` nao ha confronto, e um `False` seria uma afirmacao falsa."""
        linhas = extrair_de(
            "smb_message_echoes", {ARRAY_DOS_ECHOES: [{"timestamp": "1790812800"}]}
        )
        self.assertNotIn("enviada_por_nos", linhas[0])


class TestHistory(unittest.TestCase):
    def test_o_2593109_entra_como_error_code(self) -> None:
        linhas = extrair_de(
            "history",
            {"history": [{"threads": [], "errors": [{"code": 2593109,
                                                     "title": "History not shared"}]}]},
        )
        self.assertEqual(linhas[0]["error_code"], 2_593_109)

    def test_conta_conversas_e_mensagens_sem_as_copiar(self) -> None:
        linhas = extrair_de(
            "history",
            {
                "history": [
                    {
                        "threads": [
                            {"id": "x", "messages": [{"text": {"body": "segredo um"}},
                                                     {"text": {"body": "segredo dois"}}]},
                            {"id": "y", "messages": [{"text": {"body": "segredo tres"}}]},
                        ]
                    }
                ]
            },
        )
        self.assertEqual(linhas[0]["threads"], 2)
        self.assertEqual(linhas[0]["mensagens"], 3)
        self.assertNotIn("segredo", str(linhas))

    def test_a_fase_numerica_vira_texto(self) -> None:
        """A Meta manda `phase: 0`; o registo exige texto, e nao se relaxa."""
        linhas = extrair_de("history", {"history": [{"metadata": {"phase": 0}}]})
        self.assertEqual(linhas[0]["fase"], "fase_0")

    def test_um_history_sem_threads_produz_contagens_a_zero(self) -> None:
        """Zero mensagens **medidas** e diferente de campo em falta."""
        linhas = extrair_de("history", {"history": [{}]})
        self.assertEqual(linhas[0]["threads"], 0)
        self.assertEqual(linhas[0]["mensagens"], 0)


class TestStateSync(unittest.TestCase):
    def test_conta_contactos_e_nao_le_nome_nem_telefone(self) -> None:
        linhas = extrair_de(
            "smb_app_state_sync",
            {
                "state_sync": [
                    {"type": "contact", "contact": {"full_name": "Ana Maria",
                                                    "phone_number": "923456788"}},
                    {"type": "contact", "contact": {"full_name": "Joao Pedro",
                                                    "phone_number": "923456787"}},
                ]
            },
        )
        self.assertEqual(linhas[0]["contactos"], 2)
        for proibido in ("Ana", "Joao", "923456788", "923456787"):
            self.assertNotIn(proibido, str(linhas))

    def test_elemento_sem_contact_nao_conta(self) -> None:
        linhas = extrair_de(
            "smb_app_state_sync", {"state_sync": [{"type": "contact"}, {"contact": {}}]}
        )
        self.assertEqual(linhas[0]["contactos"], 1)


class TestFormaInesperada(unittest.TestCase):
    """A forma interna e INDICIO: uma diferenca produz menos campos, nao erro.

    Levantar aqui fazia o spike **perder** o evento que viesse numa forma
    ligeiramente diferente — que e precisamente o que ha para medir.
    """

    def test_valores_nao_esperados_nao_levantam(self) -> None:
        casos = [
            ("history", {"history": "nao e uma lista"}),
            ("history", {"history": [None, 7, "x"]}),
            ("smb_app_state_sync", {"state_sync": None}),
            ("smb_message_echoes", {ARRAY_DOS_ECHOES: {"nao": "e lista"}}),
            ("messages", {"messages": [{"timestamp": "nao e numero"}]}),
            ("account_update", {"event": None, "partner_removed_info": "x"}),
        ]
        for campo, valor in casos:
            with self.subTest(campo=campo, valor=str(valor)[:28]):
                for linha in extrair_de(campo, valor):
                    self.assertEqual(validar(linha), linha)

    def test_corpo_sem_entry_nem_changes_devolve_vazio(self) -> None:
        for mau in ({}, {"entry": None}, {"entry": [{}]},
                    {"entry": [{"changes": "x"}]},
                    {"entry": [{"changes": [{"field": "messages", "value": None}]}]}):
            with self.subTest(corpo=str(mau)[:34]):
                self.assertEqual(extrair(mau, ROTULOS, (), INSTANTE), [])

    def test_um_timestamp_booleano_nao_entra_como_carimbo(self) -> None:
        """`True` e um `int` em Python e passaria por um carimbo de 1970."""
        linhas = extrair_de("messages", {"messages": [{"id": WAMID, "timestamp": True}]})
        self.assertNotIn("carimbo", linhas[0])


class TestRotulos(unittest.TestCase):
    def test_canal_sem_rotulo_sai_sem_numero_e_nao_com_o_id(self) -> None:
        """A tabela recusa a linha, e e melhor do que atribui-la ao numero errado."""
        linhas = extrair(
            corpo("account_update", {"event": "PARTNER_REMOVED"}), {}, (), INSTANTE
        )
        self.assertTrue(linhas)
        self.assertNotIn("numero", linhas[0])
        self.assertNotIn(CANAL, str(linhas))

    def test_o_rotulo_vem_do_mapa_e_nao_do_corpo(self) -> None:
        linhas = extrair(
            corpo("account_update", {"event": "PARTNER_REMOVED"}),
            {CANAL: "N3"},
            (),
            INSTANTE,
        )
        self.assertEqual(linhas[0]["numero"], "N3")


class TestMensagens(unittest.TestCase):
    def test_os_statuses_nao_produzem_linha(self) -> None:
        """Os estados de entrega sao do KAM-017 e nao medem nada de H3."""
        linhas = extrair_de(
            "messages",
            {"statuses": [{"id": WAMID, "status": "delivered", "timestamp": "1790812800"}]},
        )
        self.assertEqual(linhas, [])

    def test_uma_linha_por_mensagem(self) -> None:
        linhas = extrair_de(
            "messages",
            {"messages": [{"id": WAMID, "timestamp": "1790812800"},
                          {"id": OUTRO_WAMID, "timestamp": "1790812801"}]},
        )
        self.assertEqual(len(linhas), 2)
        self.assertEqual({l["direccao"] for l in linhas}, {"entrada"})
        self.assertNotEqual(linhas[0]["id"], linhas[1]["id"])


if __name__ == "__main__":
    unittest.main()
