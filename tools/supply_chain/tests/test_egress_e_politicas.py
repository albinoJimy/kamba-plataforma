"""Egress por servico, quarentena do Renovate e chaves no CI (criterios 8 e 9)."""

from __future__ import annotations

import json
import unittest

from supply_chain import ci_chaves, egress, renovate
from supply_chain.base import ConfiguracaoInvalida

from .base import ROOT, ComArvore

GWY = "services/gwy/egress.yaml"

DESTINO = """destinos:
  - fqdn: graph.facebook.com
    porta: 443
    protocolo: https
    razao: Envio de mensagens pela Cloud API da Meta
    ticket: KAM-013
"""


class TestEgress(ComArvore):
    def regras_de(self) -> list[str]:
        return self.regras(egress.verificar(self.raiz)[0])

    def test_o_minimo_passa(self) -> None:
        achados, resumo = egress.verificar(self.raiz)
        self.assertEqual([str(a) for a in achados], [])
        self.assertEqual(resumo, {"servicos": 3, "destinos": 0})

    def test_um_destino_bem_formado_passa_e_conta(self) -> None:
        self.trocar(GWY, "destinos: []\n", DESTINO)
        achados, resumo = egress.verificar(self.raiz)
        self.assertEqual([str(a) for a in achados], [])
        self.assertEqual(resumo["destinos"], 1)

    def test_servico_do_monorepo_sem_declaracao(self) -> None:
        (self.raiz / GWY).unlink()
        achados, _ = egress.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("egress-em-falta", GWY)])

    def test_servico_que_so_existe_no_compose_sem_declaracao(self) -> None:
        (self.raiz / "infra/egress/queue.yaml").unlink()
        achados, _ = egress.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro) for a in achados], [("egress-em-falta", "infra/egress/queue.yaml")])

    def test_servico_novo_no_compose_ou_em_services(self) -> None:
        self.escrever("services/novo/src/x.ts", "export {};\n")
        self.assertEqual(self.regras_de(), ["egress-em-falta"])
        self.escrever("services/novo/egress.yaml", "version: 1\nservico: novo\npor_omissao: negar\ndestinos: []\n")
        self.assertEqual(self.regras_de(), [])

    def test_declaracao_orfa(self) -> None:
        self.escrever("infra/egress/fantasma.yaml", "version: 1\nservico: fantasma\npor_omissao: negar\ndestinos: []\n")
        self.assertEqual(self.regras_de(), ["egress-orfao"])

    def test_a_declaracao_de_um_servico_do_monorepo_nao_vale_em_infra(self) -> None:
        """Mover o ficheiro para o sitio errado nao conta como declarar."""
        (self.raiz / GWY).rename(self.raiz / "infra/egress/gwy.yaml")
        self.assertEqual(self.regras_de(), ["egress-em-falta", "egress-orfao"])

    def test_formas_invalidas(self) -> None:
        for antigo, novo, fragmento in (
            ("por_omissao: negar", "por_omissao: permitir", "`por_omissao` tem de ser `negar`"),
            ("por_omissao: negar\n", "", "`por_omissao` tem de ser `negar`"),
            ("servico: gwy", "servico: outro", "`servico` tem de ser `gwy`"),
            ("version: 1", "version: 2", "'version' tem de ser 1"),
            ("destinos: []\n", "", "falta `destinos`"),
            ("destinos: []", "destinos: []\npermitir_tudo: true", "nenhum codigo le"),
            ("destinos: []", "destinos:\n  - graph.facebook.com", "esperava um mapa"),
        ):
            with self.subTest(novo=novo):
                original = self.ler(GWY)
                self.trocar(GWY, antigo, novo)
                try:
                    achados, _ = egress.verificar(self.raiz)
                finally:
                    self.escrever(GWY, original)
                self.assertEqual(set(self.regras(achados)), {"egress-invalido"})
                self.assertTrue(any(fragmento in a.mensagem for a in achados), [a.mensagem for a in achados])

    def test_um_egress_que_nao_se_le_e_erro_de_configuracao_e_nao_achado(self) -> None:
        """KAM-136: codigo 2, nao 1.

        Era um achado `egress-invalido` — e um achado dispensa-se com um
        *waiver* do *gate* 11. Uma lista de saidas que nao se le nao produziu
        achado nenhum: e a mesma regra que as `imagens` e as `licencas` ao lado
        ja seguiam, e que o `base.ConfiguracaoInvalida` escreve.
        """
        from supply_chain.base import ConfiguracaoInvalida

        original = self.ler(GWY)
        self.trocar(GWY, "destinos: []", "destinos: [a, b]")
        try:
            with self.assertRaises(ConfiguracaoInvalida) as capturado:
                egress.verificar(self.raiz)
        finally:
            self.escrever(GWY, original)
        self.assertIn("ilegivel", str(capturado.exception))
        self.assertIn(GWY, str(capturado.exception))

    def test_destinos_invalidos(self) -> None:
        for antigo, novo, fragmento in (
            ("fqdn: graph.facebook.com", 'fqdn: "*"', "nao e um FQDN"),
            ("fqdn: graph.facebook.com", 'fqdn: "*.facebook.com"', "nao e um FQDN"),
            ("fqdn: graph.facebook.com", "fqdn: 157.240.1.35", "nao e um FQDN"),
            ("fqdn: graph.facebook.com", 'fqdn: "0.0.0.0/0"', "nao e um FQDN"),
            ("fqdn: graph.facebook.com", "fqdn: localhost", "nao e um FQDN"),
            ("fqdn: graph.facebook.com", "fqdn: Graph.Facebook.com", "nao e um FQDN"),
            ("fqdn: graph.facebook.com", 'fqdn: "graph.facebook.com/x"', "nao e um FQDN"),
            ("porta: 443", "porta: 0", "`porta`"),
            ("porta: 443", "porta: 70000", "`porta`"),
            ("porta: 443", 'porta: "443"', "`porta`"),
            ("porta: 443", "porta: true", "`porta`"),
            ("protocolo: https", "protocolo: qualquer", "`protocolo`"),
            ("razao: Envio de mensagens pela Cloud API da Meta", "razao: porque sim", "`razao`"),
            ("ticket: KAM-013", "ticket: depois", "`ticket`"),
            ("    ticket: KAM-013\n", "", "campos em falta: ticket"),
            ("    ticket: KAM-013", "    ticket: KAM-013\n    qualquer: sim", "desconhecida"),
        ):
            with self.subTest(novo=novo):
                self.escrever(GWY, self.ler(GWY).replace("destinos: []\n", DESTINO))
                self.trocar(GWY, antigo, novo)
                try:
                    achados, _ = egress.verificar(self.raiz)
                finally:
                    self.escrever(GWY, "version: 1\nservico: gwy\npor_omissao: negar\ndestinos: []\n")
                self.assertEqual(set(self.regras(achados)), {"egress-invalido"})
                self.assertTrue(any(fragmento in a.mensagem for a in achados), [a.mensagem for a in achados])

    def test_destino_repetido(self) -> None:
        self.trocar(GWY, "destinos: []\n", DESTINO + DESTINO.split("\n", 1)[1])
        achados, _ = egress.verificar(self.raiz)
        self.assertTrue(any("repetido" in a.mensagem for a in achados))


class TestRenovate(ComArvore):
    def regras_de(self) -> list[str]:
        return self.regras(renovate.verificar(self.raiz)[0])

    def test_o_minimo_passa(self) -> None:
        achados, resumo = renovate.verificar(self.raiz)
        self.assertEqual([str(a) for a in achados], [])
        self.assertEqual(resumo, {"quarentena_dias": 7})

    def test_o_ficheiro_real_converte_se_e_tem_o_que_o_ticket_pede(self) -> None:
        dados = json.loads(renovate.json5_para_json((ROOT / "renovate.json5").read_text(encoding="utf-8")))
        self.assertEqual(dados["minimumReleaseAge"], "7 days")
        self.assertIs(dados["automerge"], False)
        self.assertIs(dados["vulnerabilityAlerts"]["automerge"], False)
        self.assertIn("team:seguranca", dados["vulnerabilityAlerts"]["reviewers"])
        # As expressoes regulares dentro de cadeias sobrevivem a conversao.
        self.assertIn("/^@typebot\\.io//", dados["packageRules"][-1]["matchPackageNames"])

    def test_json5(self) -> None:
        convertido = renovate.json5_para_json(
            '{\n  // c1\n  a: "x // nao e comentario", /* c2 */\n  "b": [1, 2,],\n  $c: {d: null,},\n}\n'
        )
        self.assertEqual(json.loads(convertido), {"a": "x // nao e comentario", "b": [1, 2], "$c": {"d": None}})

    def test_json5_que_nao_se_le(self) -> None:
        for texto in ("{a: 'aspas simples'}", "{a: 1 /* por fechar", "{a: }", "[1, 2]"):
            with self.subTest(texto=texto):
                self.escrever("renovate.json5", texto)
                with self.assertRaises(ConfiguracaoInvalida):
                    renovate.verificar(self.raiz)

    def test_ficheiro_em_falta(self) -> None:
        (self.raiz / "renovate.json5").unlink()
        with self.assertRaises(ConfiguracaoInvalida):
            renovate.verificar(self.raiz)

    def test_prazos(self) -> None:
        self.assertEqual(renovate.dias("7 days"), 7)
        self.assertEqual(renovate.dias("1 week"), 7)
        self.assertEqual(renovate.dias("14 days"), 14)
        for mau in (None, 7, "sete dias", "7 hours", "7", ""):
            with self.subTest(mau=mau):
                self.assertIsNone(renovate.dias(mau))

    def test_quarentena_retirada_ou_encurtada(self) -> None:
        for novo in (
            "",
            '  minimumReleaseAge: "3 days",\n',
            '  minimumReleaseAge: "0 days",\n',
            "  minimumReleaseAge: null,\n",
            '  minimumReleaseAge: "12 hours",\n',
            '  minimumReleaseAge: "7 days",\n  internalChecksFilter: "none",\n',
            '  minimumReleaseAge: "7 days",\n  enabled: false,\n',
        ):
            with self.subTest(novo=novo):
                original = self.ler("renovate.json5")
                self.trocar("renovate.json5", '  minimumReleaseAge: "7 days",\n', novo)
                try:
                    self.assertEqual(self.regras_de(), ["quarentena-desligada"])
                finally:
                    self.escrever("renovate.json5", original)

    def test_regra_de_pacote_que_fura_a_quarentena(self) -> None:
        for regra in (
            '{ matchPackageNames: ["x"], minimumReleaseAge: null },',
            '{ matchPackageNames: ["x"], minimumReleaseAge: "1 day" },',
            '{ matchPackageNames: ["x"], minimumReleaseAge: "0 days" },',
        ):
            with self.subTest(regra=regra):
                original = self.ler("renovate.json5")
                self.trocar("renovate.json5", "  packageRules: [\n", "  packageRules: [\n    " + regra + "\n")
                try:
                    self.assertEqual(self.regras_de(), ["quarentena-desligada"])
                finally:
                    self.escrever("renovate.json5", original)

    def test_regra_de_pacote_que_alonga_a_quarentena_passa(self) -> None:
        self.trocar("renovate.json5", "  packageRules: [\n", '  packageRules: [\n    { matchPackageNames: ["x"], minimumReleaseAge: "30 days" },\n')
        self.assertEqual(self.regras_de(), [])

    def test_automerge(self) -> None:
        self.trocar("renovate.json5", "  automerge: false,\n  packageRules", "  automerge: true,\n  packageRules")
        self.assertEqual(self.regras_de(), ["automerge-ligado"])

    def test_automerge_omitido_nao_chega(self) -> None:
        self.trocar("renovate.json5", "  automerge: false,\n  packageRules", "  packageRules")
        self.assertEqual(self.regras_de(), ["automerge-ligado"])

    def test_automerge_numa_regra(self) -> None:
        self.trocar("renovate.json5", "allowedVersions: \"<5.0.0\" }", "allowedVersions: \"<5.0.0\", automerge: true }")
        self.assertEqual(self.regras_de(), ["automerge-ligado"])

    def test_a_excepcao_de_seguranca_tem_de_ser_marcada_e_revista(self) -> None:
        for antigo, novo in (
            ('    reviewers: ["team:plataforma"],\n', ""),
            ('    reviewers: ["team:plataforma"],\n', "    reviewers: [],\n"),
            ('    labels: ["dependencias", "seguranca"],\n', ""),
            ("    automerge: false,\n  },", "  },"),
        ):
            with self.subTest(novo=novo):
                original = self.ler("renovate.json5")
                self.trocar("renovate.json5", antigo, novo)
                try:
                    self.assertEqual(self.regras_de(), ["excepcao-de-seguranca-sem-revisao"])
                finally:
                    self.escrever("renovate.json5", original)

    def test_automerge_na_excepcao_de_seguranca(self) -> None:
        self.trocar("renovate.json5", "    automerge: false,\n  },", "    automerge: true,\n  },")
        self.assertEqual(self.regras_de(), ["automerge-ligado"])

    def test_excepcao_que_mantem_a_quarentena_nao_precisa_de_revisores(self) -> None:
        self.trocar("renovate.json5", "    minimumReleaseAge: null,\n", "")
        self.trocar("renovate.json5", '    reviewers: ["team:plataforma"],\n', "")
        self.assertEqual(self.regras_de(), [])


class TestChavesNoCI(ComArvore):
    WORKFLOW = ".github/workflows/ci.yaml"

    def test_o_minimo_passa(self) -> None:
        achados, resumo = ci_chaves.verificar(self.raiz)
        self.assertEqual(achados, [])
        self.assertEqual(resumo, {"ficheiros": 1})

    def test_referencias_ao_cofre(self) -> None:
        for linha in (
            "          TOKEN: ${{ secrets.REGISTO }}",
            "          TOKEN: ${{secrets.REGISTO}}",
            "          TOKEN: ${{ secrets['REGISTO'] }}",
            "          TOKEN: ${{ secrets . REGISTO }}",
            "      # TOKEN: ${{ secrets.REGISTO }}",
            "    secrets: inherit",
        ):
            with self.subTest(linha=linha):
                original = self.ler(self.WORKFLOW)
                self.escrever(self.WORKFLOW, original + linha + "\n")
                try:
                    achados, _ = ci_chaves.verificar(self.raiz)
                finally:
                    self.escrever(self.WORKFLOW, original)
                self.assertEqual(self.regras(achados), ["chave-estatica-no-ci"])

    def test_a_palavra_sozinha_nao_e_referencia(self) -> None:
        self.escrever(self.WORKFLOW, self.ler(self.WORKFLOW) + "# sem secrets do cofre; o gate 9 varre segredos\n")
        self.assertEqual(ci_chaves.verificar(self.raiz)[0], [])

    def test_accoes_compostas_tambem_contam_e_o_resto_nao(self) -> None:
        self.escrever(".github/actions/x/action.yml", "runs:\n  steps:\n    - run: echo ${{ secrets.X }}\n")
        self.escrever("docs/exemplo.yaml", "x: ${{ secrets.X }}\n")
        achados, _ = ci_chaves.verificar(self.raiz)
        self.assertEqual([(a.regra, a.ficheiro, a.linha) for a in achados], [("chave-estatica-no-ci", ".github/actions/x/action.yml", 3)])


if __name__ == "__main__":
    unittest.main()
