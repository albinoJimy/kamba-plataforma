"""O varrimento de vulnerabilidades do gate 11.

Nenhum destes casos toca na rede. A consulta real a OSV foi exercitada a mao
com `lodash@4.17.11` e `django@3.0.0` — 48 vulnerabilidades, 5 `CRITICAL`,
entre as quais a `GHSA-jf85-cpcp-j695` — e esta registada em `docs/ci.md` §3.
Um teste que dependesse da rede seria vermelho num *runner* sem saida, e seria
o primeiro que alguem desligava.

O que se verifica aqui e a parte nossa: a leitura da severidade, o que
bloqueia, e o que um waiver dispensa.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from sbom import vulns
from sbom.collect import NPM, PYPI, Componente


class TestSeveridade(unittest.TestCase):
    def test_o_texto_do_ghsa_tem_prioridade(self) -> None:
        detalhe = {
            "database_specific": {"severity": "critical"},
            "severity": [{"type": "CVSS_V3", "score": "2.0"}],
        }
        self.assertEqual(vulns._severidade(detalhe), "CRITICAL")

    def test_pontuacao_cvss_numerica(self) -> None:
        for pontuacao, esperado in (
            ("9.8", "CRITICAL"),
            ("9.0", "CRITICAL"),
            ("8.1", "HIGH"),
            ("5.3", "MODERATE"),
            ("2.1", "LOW"),
        ):
            with self.subTest(pontuacao=pontuacao):
                detalhe = {"severity": [{"score": pontuacao}]}
                self.assertEqual(vulns._severidade(detalhe), esperado)

    def test_vector_cvss_nao_se_traduz_a_mao(self) -> None:
        """Um vector sem numero devolve vazio, e vazio **nao** bloqueia.

        Traduzir `CVSS:3.1/AV:N/AC:L/...` a mao aqui seria inventar uma
        pontuacao; e bloquear por ausencia de dado transformaria cada aviso sem
        metadados num PR parado.
        """
        detalhe = {"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L"}]}
        self.assertEqual(vulns._severidade(detalhe), "")

    def test_sem_dados_nenhuns(self) -> None:
        self.assertEqual(vulns._severidade({}), "")


class TestBloqueio(unittest.TestCase):
    """So `CRITICAL` bloqueia: e o que o criterio de aceitacao diz."""

    def test_critical_bloqueia(self) -> None:
        self.assertTrue(
            vulns.Vulnerabilidade("pkg:npm/x@1", "GHSA-a", "CRITICAL", "").bloqueia
        )

    def test_high_nao_bloqueia(self) -> None:
        self.assertFalse(
            vulns.Vulnerabilidade("pkg:npm/x@1", "GHSA-a", "HIGH", "").bloqueia
        )

    def test_sem_severidade_nao_bloqueia(self) -> None:
        self.assertFalse(vulns.Vulnerabilidade("pkg:npm/x@1", "GHSA-a", "", "").bloqueia)

    def test_a_mensagem_nomeia_o_pacote_e_o_id(self) -> None:
        texto = str(vulns.Vulnerabilidade("pkg:npm/x@1", "GHSA-a", "CRITICAL", "resumo"))
        self.assertIn("pkg:npm/x@1", texto)
        self.assertIn("GHSA-a", texto)
        self.assertIn("CRITICAL", texto)


class TestConsulta(unittest.TestCase):
    """A travessia da resposta, com a rede substituida."""

    def setUp(self) -> None:
        self.componentes = [
            Componente(NPM, "lodash", "4.17.11", "MIT", "teste"),
            Componente(NPM, "hono", "4.13.13", "MIT", "teste"),
        ]

    def test_os_pacotes_proprios_nao_se_consultam(self) -> None:
        """Nao estao em base de dados nenhuma; consulta-los gastava pedidos."""
        proprios = [
            Componente(NPM, "@kamba/gwy", "0.1.0", None, "teste", proprio=True)
        ]
        with mock.patch.object(vulns, "_pedir") as pedir:
            self.assertEqual(vulns.consultar(proprios), [])
            pedir.assert_not_called()

    def test_le_os_ids_do_lote_e_a_severidade_do_detalhe(self) -> None:
        respostas = {
            vulns.URL_LOTE: {
                "results": [{"vulns": [{"id": "GHSA-jf85-cpcp-j695"}]}, {}]
            },
            vulns.URL_VULN + "GHSA-jf85-cpcp-j695": {
                "database_specific": {"severity": "CRITICAL"},
                "summary": "Prototype pollution",
            },
        }

        def falso(url, corpo=None):
            return respostas[url]

        with mock.patch.object(vulns, "_pedir", side_effect=falso):
            achadas = vulns.consultar(self.componentes)

        self.assertEqual(len(achadas), 1)
        self.assertEqual(achadas[0].identificador, "GHSA-jf85-cpcp-j695")
        self.assertTrue(achadas[0].bloqueia)
        self.assertEqual(achadas[0].purl, "pkg:npm/lodash@4.17.11")

    def test_resposta_truncada_e_erro_e_nao_silencio(self) -> None:
        """Menos resultados do que consultas significaria componentes nao vistos.

        Alinhar por `zip` e seguir em frente daria um gate verde sobre uma
        resposta incompleta — que e a forma de falha que este modulo existe
        para nao ter.
        """
        with mock.patch.object(vulns, "_pedir", return_value={"results": [{}]}):
            with self.assertRaises(vulns.RedeIndisponivel):
                vulns.consultar(self.componentes)

    def test_sem_vulnerabilidades_nao_pede_detalhes(self) -> None:
        with mock.patch.object(
            vulns, "_pedir", return_value={"results": [{}, {}]}
        ) as pedir:
            self.assertEqual(vulns.consultar(self.componentes), [])
        self.assertEqual(pedir.call_count, 1, "pediu detalhes sem ter ids")


class TestSemRede(unittest.TestCase):
    def test_a_variavel_tem_de_ser_exactamente_1(self) -> None:
        for valor, esperado in (("1", True), ("0", False), ("sim", False), ("", False)):
            with self.subTest(valor=valor), mock.patch.dict(
                os.environ, {"KAMBA_SEM_REDE": valor}
            ):
                self.assertIs(vulns.sem_rede(), esperado)

    def test_por_omissao_varre(self) -> None:
        ambiente = {k: v for k, v in os.environ.items() if k != "KAMBA_SEM_REDE"}
        with mock.patch.dict(os.environ, ambiente, clear=True):
            self.assertFalse(vulns.sem_rede())


class TestWaivers(unittest.TestCase):
    """«Sem excepcao registada» — a excepcao e um waiver com `alvo`."""

    def test_waiver_por_purl_e_por_id(self) -> None:
        from sbom.cli import verificar_vulnerabilidades

        encontradas = [
            vulns.Vulnerabilidade("pkg:npm/a@1", "GHSA-a", "CRITICAL", ""),
            vulns.Vulnerabilidade("pkg:npm/b@2", "GHSA-b", "CRITICAL", ""),
            vulns.Vulnerabilidade("pkg:npm/c@3", "GHSA-c", "CRITICAL", ""),
        ]
        with mock.patch("sbom.cli.recolher", return_value=[]), mock.patch(
            "sbom.cli.vulns.consultar", return_value=encontradas
        ), mock.patch(
            "sbom.cli.waivers_do_gate_11", return_value={"pkg:npm/a@1", "GHSA-b"}
        ):
            achados, resumo = verificar_vulnerabilidades(None)

        self.assertEqual(len(resumo["dispensadas"]), 2)
        self.assertEqual(len(achados), 1)
        self.assertIn("GHSA-c", achados[0])

    def test_waiver_sem_alvo_nao_dispensa_nada(self) -> None:
        """`alvo: tudo` nao existe, e o `ci/waivers.yaml` di-lo."""
        from sbom.cli import verificar_vulnerabilidades

        encontradas = [vulns.Vulnerabilidade("pkg:npm/a@1", "GHSA-a", "CRITICAL", "")]
        with mock.patch("sbom.cli.recolher", return_value=[]), mock.patch(
            "sbom.cli.vulns.consultar", return_value=encontradas
        ), mock.patch("sbom.cli.waivers_do_gate_11", return_value=set()):
            achados, _ = verificar_vulnerabilidades(None)
        self.assertEqual(len(achados), 1)


if __name__ == "__main__":
    unittest.main()
