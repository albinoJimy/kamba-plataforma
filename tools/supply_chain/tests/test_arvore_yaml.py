"""O leitor estrutural: ancoras, *merge keys*, listas, blocos — e o que recusa."""

from __future__ import annotations

import unittest

from supply_chain import arvore_yaml
from supply_chain.arvore_yaml import YamlIlegivel

from .base import COMPOSE, ROOT, WORKFLOW


class TestEstrutura(unittest.TestCase):
    def test_merge_key_traz_as_chaves_da_ancora(self) -> None:
        documento = arvore_yaml.ler(COMPOSE)
        servicos = documento.mapa(documento.mapa(documento.raiz)["services"])
        gwy = documento.mapa(servicos["gwy"])
        self.assertEqual(gwy["read_only"].texto(), "true")
        self.assertEqual(gwy["restart"].texto(), "unless-stopped")
        self.assertIn("build", gwy)

    def test_a_chave_propria_ganha_a_fundida(self) -> None:
        documento = arvore_yaml.ler(
            "x: &base\n  read_only: true\n  user: node\n"
            "services:\n  a:\n    <<: *base\n    read_only: false\n"
        )
        a = documento.mapa(documento.mapa(documento.mapa(documento.raiz)["services"])["a"])
        self.assertEqual(a["read_only"].texto(), "false")
        self.assertEqual(a["user"].texto(), "node")

    def test_merge_de_varias_ancoras_a_primeira_ganha(self) -> None:
        documento = arvore_yaml.ler(
            "a: &a\n  k: um\nb: &b\n  k: dois\n  so_b: sim\nc:\n  <<: [*a, *b]\n"
        )
        c = documento.mapa(documento.mapa(documento.raiz)["c"])
        self.assertEqual(c["k"].texto(), "um")
        self.assertEqual(c["so_b"].texto(), "sim")

    def test_merge_em_lista_de_blocos(self) -> None:
        documento = arvore_yaml.ler("a: &a\n  k: um\nc:\n  <<:\n    - *a\n")
        self.assertEqual(documento.mapa(documento.mapa(documento.raiz)["c"])["k"].texto(), "um")

    def test_alias_como_valor(self) -> None:
        documento = arvore_yaml.ler("log: &log\n  driver: json-file\nsvc:\n  logging: *log\n")
        svc = documento.mapa(documento.mapa(documento.raiz)["svc"])
        self.assertEqual(documento.mapa(svc["logging"])["driver"].texto(), "json-file")

    def test_lista_a_mesma_indentacao_da_chave(self) -> None:
        documento = arvore_yaml.ler(WORKFLOW)
        gate = documento.mapa(documento.mapa(documento.mapa(documento.raiz)["jobs"])["gate"])
        self.assertEqual(documento.itens(gate["needs"]), ["outro"])
        self.assertEqual(gate["runs-on"].texto(), "ubuntu-latest")
        self.assertIn("steps", gate)

    def test_item_que_e_um_mapa(self) -> None:
        documento = arvore_yaml.ler("l:\n  - a: 1\n    b: 2\n  - a: 3\n")
        itens = documento.mapa(documento.raiz)["l"].filhos
        self.assertEqual(len(itens), 2)
        self.assertEqual({f.chave: f.texto() for f in itens[0].filhos}, {"a": "1", "b": "2"})

    def test_escalar_de_bloco_fica_inteiro(self) -> None:
        documento = arvore_yaml.ler("run: |\n  make a\n  # nao e comentario yaml\n  pip install x\nk: v\n")
        topo = documento.mapa(documento.raiz)
        self.assertTrue(topo["run"].bloco)
        self.assertIn("pip install x", topo["run"].valor)
        self.assertEqual(topo["k"].texto(), "v")

    def test_fluxo_em_varias_linhas(self) -> None:
        documento = arvore_yaml.ler('t: ["CMD",\n    "pg_isready"]\nk: v\n')
        topo = documento.mapa(documento.raiz)
        self.assertEqual(documento.itens(topo["t"]), ["CMD", "pg_isready"])
        self.assertEqual(topo["k"].texto(), "v")

    def test_comentarios_e_aspas(self) -> None:
        documento = arvore_yaml.ler('a: "x # y"  # fim\nb: \'z\'\n"c d": 1\n')
        topo = documento.mapa(documento.raiz)
        self.assertEqual(topo["a"].texto(), "x # y")
        self.assertEqual(topo["b"].texto(), "z")
        self.assertEqual(topo["c d"].texto(), "1")

    def test_escalares_com_dois_pontos_nao_sao_chaves(self) -> None:
        documento = arvore_yaml.ler(
            "v:\n  - /tmp:size=64m\n  - ./a:/b:ro\n  - no-new-privileges:true\n  - \"127.0.0.1:3000:3000\"\n"
        )
        self.assertEqual(
            documento.itens(documento.mapa(documento.raiz)["v"]),
            ["/tmp:size=64m", "./a:/b:ro", "no-new-privileges:true", "127.0.0.1:3000:3000"],
        )

    def test_todos_percorre_em_profundidade(self) -> None:
        documento = arvore_yaml.ler("a:\n  b:\n    c: 1\nd: 2\n")
        self.assertEqual([no.chave for no in documento.todos()], ["a", "b", "c", "d"])


class TestRecusa(unittest.TestCase):
    """O que nao se consegue seguir levanta — nunca devolve uma estrutura a meio."""

    def recusa(self, texto: str, fragmento: str) -> None:
        with self.assertRaises(YamlIlegivel) as contexto:
            documento = arvore_yaml.ler(texto)
            for no in documento.todos():
                if no.filhos or no.chave == "<<":
                    documento.mapa(no)
        self.assertIn(fragmento, str(contexto.exception))

    def test_tabulacao(self) -> None:
        self.recusa("a:\n\tb: 1\n", "tabulacao")

    def test_documentos_multiplos(self) -> None:
        self.recusa("a: 1\n---\nb: 2\n", "documentos multiplos")

    def test_alias_sem_ancora(self) -> None:
        self.recusa("a:\n  <<: *nada\n", "merge key")

    def test_ancora_repetida(self) -> None:
        self.recusa("a: &x\n  k: 1\nb: &x\n  k: 2\n", "repetida")

    def test_linha_que_nao_e_chave_nem_item(self) -> None:
        self.recusa("a: 1\nisto nao e yaml em blocos\n", "nem `chave: valor`")

    def test_bloco_sob_um_escalar(self) -> None:
        self.recusa("a: valor\n  b: 1\n", "sob um escalar")

    def test_fluxo_por_fechar(self) -> None:
        self.recusa("a: [1, 2\n", "por fechar")

    def test_mapa_em_fluxo_onde_se_esperava_um_mapa(self) -> None:
        documento = arvore_yaml.ler("svc: {image: x}\n")
        with self.assertRaises(YamlIlegivel):
            documento.mapa(documento.mapa(documento.raiz)["svc"])

    def test_alias_em_ciclo(self) -> None:
        documento = arvore_yaml.ler("a: &a\n  <<: *a\n")
        with self.assertRaises(YamlIlegivel):
            documento.mapa(documento.mapa(documento.raiz)["a"])


class TestFicheirosReais(unittest.TestCase):
    """Os ficheiros que o gate le de facto tem de se deixar ler."""

    def test_o_compose_o_workflow_e_a_accao(self) -> None:
        for ficheiro in (
            "infra/compose/docker-compose.dev.yml",
            ".github/workflows/ci.yaml",
            ".github/actions/preparar/action.yaml",
        ):
            with self.subTest(ficheiro=ficheiro):
                documento = arvore_yaml.ler((ROOT / ficheiro).read_text(encoding="utf-8"))
                self.assertTrue(documento.raiz.filhos)

    def test_o_compose_real_tem_sete_servicos_e_todos_resolvem(self) -> None:
        documento = arvore_yaml.ler(
            (ROOT / "infra/compose/docker-compose.dev.yml").read_text(encoding="utf-8")
        )
        servicos = documento.mapa(documento.mapa(documento.raiz)["services"])
        self.assertEqual(
            sorted(servicos),
            ["agr", "com", "gwy", "onboarding-web", "postgres", "queue", "worker-canal"],
        )
        # O `user` do AGR e proprio (`nobody`) e ganha o da ancora (`node`).
        self.assertEqual(documento.mapa(servicos["agr"])["user"].texto(), "nobody")
        self.assertEqual(documento.mapa(servicos["gwy"])["user"].texto(), "node")


if __name__ == "__main__":
    unittest.main()
