"""Extraccao de referencias: as armadilhas que a discovery mediu.

Cada caso aqui vem de uma forma **real** encontrada no conjunto documental, com
o ficheiro de origem no comentario. Nenhum e inventado para o teste parecer
completo.
"""

from __future__ import annotations

import unittest

from lint_refs.scan import extrair

MAX_D = 13


def ids(texto: str, **kwargs) -> list[str]:
    kwargs.setdefault("maximo_d", MAX_D)
    return [o.identificador for o in extrair(texto, **kwargs)]


class TestFormasSimples(unittest.TestCase):
    def test_nu_em_prosa(self) -> None:
        # specs/EPIC-01:27
        self.assertEqual(ids("(KAM-001, KAM-002)"), ["KAM-001", "KAM-002"])

    def test_em_backticks(self) -> None:
        # specs/01:86
        self.assertEqual(ids("o `KAM-024` trata disso"), ["KAM-024"])

    def test_em_negrito(self) -> None:
        # docs/tecnica/00:348
        self.assertEqual(ids("| **ADR-013** | decisao |"), ["ADR-013"])

    def test_com_sufixo_de_pontuacao(self) -> None:
        # ~52 ocorrencias de `ADR-010)`
        self.assertEqual(ids("estado (ADR-010), e KAM-030, tambem"), ["ADR-010", "KAM-030"])

    def test_em_celula_de_tabela(self) -> None:
        self.assertEqual(ids("| KAM-002 | Pipeline de CI |"), ["KAM-002"])

    def test_decisao(self) -> None:
        self.assertEqual(ids("a decisao D12 esta aberta"), ["D12"])


class TestFormasCompostas(unittest.TestCase):
    """As que escondem referencias de uma regex ingenua."""

    def test_unidos_por_barra_com_prefixo(self) -> None:
        # specs/EPIC-01:19
        self.assertEqual(ids("ADR-002/ADR-005"), ["ADR-002", "ADR-005"])

    def test_unidos_por_barra_sem_prefixo(self) -> None:
        # specs/EPIC-02:172 — uma regex simples apanha so o primeiro
        self.assertEqual(
            ids("KAM-007/008/009/022"),
            ["KAM-007", "KAM-008", "KAM-009", "KAM-022"],
        )
        # specs/00_KAMBA_Carta.md:77
        self.assertEqual(ids("KAM-039/108"), ["KAM-039", "KAM-108"])

    def test_intervalo_com_travessao(self) -> None:
        # specs/00_System_Spec.md:163
        self.assertEqual(
            ids("ADR-001–003"), ["ADR-001", "ADR-002", "ADR-003"]
        )

    def test_intervalo_com_prefixo_repetido(self) -> None:
        # specs/INDICE.md:51
        self.assertEqual(
            ids("KAM-001 – KAM-003"), ["KAM-001", "KAM-002", "KAM-003"]
        )

    def test_intervalo_com_a(self) -> None:
        # specs/00_System_Spec.md:177
        self.assertEqual(
            ids("ADR-018 a ADR-020"), ["ADR-018", "ADR-019", "ADR-020"]
        )

    def test_intervalo_de_decisoes_dentro_do_canon(self) -> None:
        self.assertEqual(ids("D1–D3"), ["D1", "D2", "D3"])

    def test_intervalo_invertido_nao_expande(self) -> None:
        """Um intervalo ao contrario nao inventa nada.

        So o identificador com prefixo e reconhecido; o `005` nu fica de fora,
        porque sem prefixo nao se sabe de que serie e. Um intervalo malformado
        nao e materia do gate 3 — ele valida se o que esta citado existe, nao se
        esta bem escrito.
        """
        self.assertEqual(ids("KAM-010–005"), ["KAM-010"])


class TestFalsosPositivos(unittest.TestCase):
    """Formas que **nao** sao referencias. Cada uma deixaria o gate vermelho por nada."""

    def test_adr_local_nao_conta(self) -> None:
        # docs/adr/ADR-L001-toolchain.md — sequencia separada
        self.assertEqual(ids("ver ADR-L001"), [])

    def test_divergencias_do_kam_111_nao_contam(self) -> None:
        # specs/EPIC-01, tabela de divergencias: D-01 … D-12
        self.assertEqual(ids("| D-01 | tres versoes de contacts |"), [])

    def test_prazos_com_sinal_nao_contam(self) -> None:
        self.assertEqual(ids("entrega em D+30 e D+7"), [])

    def test_intervalo_de_prazos_nao_se_expande(self) -> None:
        """`Prazos D0–D30` (specs/EPIC-09:1054) inventava D14…D29."""
        obtidos = ids("Prazos D0–D30 sao propostas")
        self.assertNotIn("D14", obtidos)
        self.assertNotIn("D29", obtidos)
        # As pontas continuam a aparecer, para receberem o aviso.
        self.assertIn("D0", obtidos)
        self.assertIn("D30", obtidos)

    def test_intervalo_de_prazos_curto_nao_se_expande(self) -> None:
        """`D0–D7` (specs/EPIC-09, tabela de off-boarding)."""
        obtidos = ids("| Fecho de pendentes | D0–D7 |")
        self.assertEqual(obtidos, ["D0", "D7"])

    def test_numeros_de_quatro_digitos_contam_e_sao_invalidos(self) -> None:
        """Quatro digitos passaram a ser **vistos**, para poderem ser recusados.

        Antes `[0-9]{3}(?![0-9])` nao batia em `KAM-0999` nem em `KAM-1300`, e
        o resultado era que a forma mais simples de citar um ticket inexistente
        sem o gate dar por isso era acrescentar um digito. Nao ver nao e o
        mesmo que aprovar, mas tem o mesmo efeito no PR.

        Agora batem, e o numero valida-se depois contra o canon — onde nao
        existem, pelo que ficam recusados com o nome e a linha.
        """
        self.assertEqual(ids("KAM-0012 e ADR-1234"), ["KAM-0012", "ADR-1234"])

    def test_hifen_tipografico_nao_disfarca_a_referencia(self) -> None:
        """`KAM(U+2011)999` e indistinguivel a vista de `KAM-999`.

        E um editor produz o hifen nao-quebravel e a meia-risca sozinho. O
        token normaliza-se para o hifen comum, pelo que a validacao e a mesma.
        """
        for hifen in ("‑", "–"):
            with self.subTest(hifen=hex(ord(hifen))):
                self.assertEqual(ids(f"o KAM{hifen}999 citado"), ["KAM-999"])

    def test_cerca_desequilibrada_nao_cega_o_resto_do_ficheiro(self) -> None:
        """Um numero impar de cercas desligava o varrimento dali para a frente.

        `dentro_de_cerca` e um interruptor. Com uma cerca aberta e nunca
        fechada, tudo o que vinha depois ficava invisivel — e isso acontece por
        acidente num `.md` ou numa docstring, nao so por malicia. Quando as
        cercas nao fecham, a dispensa nao se aplica.
        """
        texto = "antes KAM-001\n```text\nKAM-999 aqui dentro\ne nunca fecha\n"
        self.assertIn("KAM-999", ids(texto))

    def test_blocos_de_codigo_sao_ignorados(self) -> None:
        """Cada ticket tem um bloco de handoff que cita tickets como instrucao."""
        texto = (
            "antes KAM-001\n"
            "```text\n"
            "Es o executor do KAM-999 e le o KAM-998\n"
            "```\n"
            "depois KAM-002\n"
        )
        self.assertEqual(ids(texto), ["KAM-001", "KAM-002"])

    def test_blocos_de_codigo_contam_se_pedido(self) -> None:
        texto = "```\nKAM-003\n```\n"
        self.assertEqual(ids(texto, ignorar_blocos_de_codigo=False), ["KAM-003"])


class TestDeduplicacao(unittest.TestCase):
    def test_a_mesma_referencia_na_mesma_linha_conta_uma_vez(self) -> None:
        self.assertEqual(ids("KAM-001 e outra vez KAM-001"), ["KAM-001"])

    def test_a_mesma_referencia_em_linhas_diferentes_conta_duas(self) -> None:
        self.assertEqual(ids("KAM-001\nKAM-001"), ["KAM-001", "KAM-001"])


class TestLinhaEContexto(unittest.TestCase):
    def test_a_linha_e_a_certa(self) -> None:
        ocorrencias = extrair("um\ndois\nKAM-005 aqui\n", maximo_d=MAX_D)
        self.assertEqual(ocorrencias[0].linha, 3)
        self.assertIn("KAM-005", ocorrencias[0].contexto)


if __name__ == "__main__":
    unittest.main()
