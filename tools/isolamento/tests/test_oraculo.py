"""O oraculo encontra o canario nas formas em que ele sai — e sabe dizer que nao.

Criterio 9 do KAM-066. A afirmacao que importa aqui nao e «o oraculo nao
encontrou nada»: e que ele **encontraria** se houvesse. Sem esta bateria, cada
«zero canarios» da suite vale tanto quanto um `varrer` que devolvesse `[]`.
"""

from __future__ import annotations

import unittest

from isolamento.oraculo import ORIGENS, Oraculo, OraculoCego, achatar

CANARIO = "canario_b_0123456789abcdef0123456789abcdef"
TENANT = "22222222-2222-2222-2222-222222222222"


class TestEncontra(unittest.TestCase):
    def setUp(self) -> None:
        self.oraculo = Oraculo({"platform.tenants": CANARIO, "tenant_id": TENANT})

    def test_numa_cadeia(self) -> None:
        self.assertTrue(self.oraculo.varrer("corpo", f"ruido {CANARIO} ruido"))

    def test_em_octetos(self) -> None:
        """Uma coluna `bytea` devolve octetos, e o canario atravessa em ASCII."""
        self.assertTrue(self.oraculo.varrer("corpo", CANARIO.encode("ascii")))

    def test_dentro_de_um_mapa_aninhado(self) -> None:
        self.assertTrue(
            self.oraculo.varrer("corpo", {"linha": {"coluna": CANARIO}})
        )

    def test_dentro_de_uma_lista_de_tuplos(self) -> None:
        self.assertTrue(self.oraculo.varrer("corpo", [("a",), (CANARIO,)]))

    def test_numa_excepcao(self) -> None:
        """A classe **e** a mensagem: e nela que a uniformidade se perde."""
        self.assertTrue(self.oraculo.varrer("erro", ValueError(CANARIO)))

    def test_o_tenant_id_sozinho_tambem(self) -> None:
        """«o tenant <uuid> nao tem este recurso» nao leva canario e entrega B."""
        fugas = self.oraculo.varrer("erro", f"o tenant {TENANT} nao tem isso")
        self.assertEqual([fuga.rotulo for fuga in fugas], ["tenant_id"])

    def test_nada_de_b_nao_e_fuga(self) -> None:
        self.assertEqual(self.oraculo.varrer("corpo", {"ok": True}), [])

    def test_varrer_tudo_junta_as_origens(self) -> None:
        fugas = self.oraculo.varrer_tudo(
            {"corpo": CANARIO, "cabecalhos": {"x-tenant": TENANT}}
        )
        self.assertEqual({fuga.origem for fuga in fugas}, {"corpo", "cabecalhos"})


class TestNaoDenuncia(unittest.TestCase):
    def test_o_contexto_nao_leva_o_canario_inteiro(self) -> None:
        """O relatorio do *gate* e publico, e um canario completo tem forma de segredo.

        Um valor com forma real num log de CI atravessaria o varrimento do gate
        9 sem ser apanhado — a area do canario e a unica onde isso e permitido,
        e um relatorio nao e essa area.
        """
        fuga = Oraculo({"t": CANARIO}).varrer("corpo", CANARIO)[0]
        self.assertNotIn(CANARIO, fuga.contexto)
        self.assertLess(len(fuga.contexto), len(CANARIO))


class TestSabeDizerQueNao(unittest.TestCase):
    def test_um_oraculo_sem_nada_proibido_e_erro(self) -> None:
        with self.assertRaises(OraculoCego):
            Oraculo({})

    def test_um_canario_curto_e_erro(self) -> None:
        """Um canario de poucos caracteres aparece por acidente em qualquer corpo."""
        with self.assertRaises(OraculoCego) as apanhado:
            Oraculo({"t": "ab"})
        self.assertIn("demasiado curtos", str(apanhado.exception))

    def test_uma_origem_inventada_e_erro(self) -> None:
        with self.assertRaises(OraculoCego):
            Oraculo({"t": CANARIO}).varrer("telepatia", "x")

    def test_as_cinco_origens_sao_as_do_criterio(self) -> None:
        self.assertEqual(ORIGENS, ("corpo", "cabecalhos", "erro", "logs", "spans"))

    def test_a_sonda_positiva_passa_num_oraculo_que_morde(self) -> None:
        Oraculo({"t": CANARIO}).confirmar_que_morde()

    def test_a_sonda_positiva_falha_num_oraculo_cego(self) -> None:
        """O canario do proprio oraculo: cega-se o `varrer` e exige-se a queixa."""

        class Cego(Oraculo):
            def varrer(self, origem, valor):  # noqa: ANN001, ANN201, ARG002
                return []

        with self.assertRaises(OraculoCego) as apanhado:
            Cego({"t": CANARIO}).confirmar_que_morde()
        self.assertIn("sonda positiva falhou", str(apanhado.exception))


class TestAchatar(unittest.TestCase):
    def test_os_octetos_preservam_se(self) -> None:
        self.assertEqual(achatar(b"\x00abc"), "\x00abc")

    def test_um_none_nao_rebenta(self) -> None:
        self.assertEqual(achatar(None), "None")


if __name__ == "__main__":
    unittest.main()
