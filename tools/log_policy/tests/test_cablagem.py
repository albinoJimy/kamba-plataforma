"""A cablagem: os alvos existem, estao nos gates, e os servicos usam o *logger*.

Um lint que ninguem chama nao protege nada. A revisao adversarial do KAM-068
tirou `log-lint` do `ci-2`, `x11` do `ci-6` e o canario do `log-lint`, e as
baterias continuaram verdes (`docs/analises/ANALISE-11`, A10). Aqui le-se o
`Makefile` e o arranque de cada servico, sem correr o `make`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
SERVICOS_NODE = ("gwy", "com", "onboarding-web", "worker-canal")


def receita(alvo: str) -> str:
    """As linhas da receita de um alvo do Makefile, sem comentarios."""
    achado = re.search(rf"^{re.escape(alvo)}:[^\n]*\n((?:\t[^\n]*\n)+)", MAKEFILE, re.M)
    if achado is None:
        raise AssertionError(f"alvo `{alvo}` sem receita no Makefile")
    linhas = [l for l in achado.group(1).splitlines() if not l.lstrip("\t@").startswith("#")]
    return "\n".join(linhas)


class TestMakefile(unittest.TestCase):
    def test_o_gate_2_corre_o_lint_dos_logs(self) -> None:
        self.assertIn("$(MAKE) log-lint", receita("ci-2"))

    def test_o_lint_dos_logs_corre_o_lint_e_o_canario(self) -> None:
        passos = receita("log-lint")
        self.assertRegex(passos, r"-m log_policy --root \$\(ROOT\) lint\b")
        self.assertRegex(passos, r"-m log_policy --root \$\(ROOT\) canario\b")

    def test_o_gate_6_corre_o_x11_antes_da_base_de_dados(self) -> None:
        passos = receita("ci-6")
        self.assertIn("$(MAKE) x11", passos)
        self.assertLess(passos.index("$(MAKE) x11"), passos.index("gate_bd.py"))

    def test_o_x11_compara_as_duas_linguagens_e_varre_as_tres_saidas(self) -> None:
        passos = receita("x11")
        self.assertIn("log_policy fixtures", passos)
        self.assertIn("log_policy conduzir", passos)
        self.assertIn("node packages/core-ts/tests/x11_conduzir.ts", passos)
        self.assertIn("log_policy iguais $(X11_DIR)/py.log $(X11_DIR)/ts.log", passos)
        self.assertIn(
            "log_policy iguais $(X11_DIR)/py.contadores.json $(X11_DIR)/ts.contadores.json", passos
        )
        varrimentos = [l for l in passos.splitlines() if "log_policy x11 " in l]
        self.assertEqual(len(varrimentos), 2)
        for linha in varrimentos:
            self.assertIn("--fixtures $(X11_DIR)/fixtures.json", linha)
        self.assertIn("--linhas-esperadas 1030", varrimentos[0])
        self.assertIn("$(X11_DIR)/py.log $(X11_DIR)/ts.log", varrimentos[0])
        self.assertIn("$(X11_DIR)/py.ponte.log", varrimentos[1])

    def test_nenhum_passo_dos_dois_alvos_engole_o_codigo_de_saida(self) -> None:
        for alvo in ("log-lint", "x11"):
            for linha in receita(alvo).splitlines():
                self.assertNotIn("|| true", linha)
                self.assertFalse(linha.startswith("\t-"), linha)


class TestLimiares(unittest.TestCase):
    """O *logger* esta no estrato `critico` (90%), e e isso que sustenta a caixa
    «cobertura do modulo de logger >= 90%» do ticket. Tirar o padrao de
    `ci/thresholds.yaml` deixava-o no `restante`, a 75%, sem nada ficar vermelho
    (primeira revisao adversarial)."""

    def test_o_logger_cai_no_estrato_critico_nas_duas_linguagens(self) -> None:
        import coverage_gate

        limiares = coverage_gate.ler_limiares(ROOT)
        critico = next(e for e in limiares.estratos if e.nome == "critico")
        self.assertEqual(critico.minimo, 90)
        self.assertIn("*/logger/*", critico.padroes)
        ficheiros = [
            "libs/py-core/src/kamba_core/logger/__init__.py",
            "libs/py-core/src/kamba_core/logger/politica.py",
            "libs/py-core/src/kamba_core/logger/ponte.py",
            "packages/core-ts/src/logger/index.ts",
            "packages/core-ts/src/logger/politica.ts",
        ]
        for ficheiro in ficheiros:
            with self.subTest(ficheiro=ficheiro):
                self.assertTrue((ROOT / ficheiro).is_file())
                self.assertFalse(limiares.esta_excluido(ficheiro))
                self.assertEqual(limiares.classificar(ficheiro).nome, "critico")

    def test_a_pasta_isenta_do_lint_so_tem_o_logger(self) -> None:
        """Um ficheiro novo nas pastas isentas herdava a isencao sem ninguem
        decidir: a lista esta presa aqui, e acrescentar um e mudar este teste."""
        self.assertEqual(
            sorted(p.name for p in (ROOT / "packages/core-ts/src/logger").iterdir() if p.is_file()),
            ["index.ts", "politica.ts"],
        )
        self.assertEqual(
            sorted(p.name for p in (ROOT / "libs/py-core/src/kamba_core/logger").glob("*.py")),
            ["__init__.py", "politica.py", "ponte.py"],
        )
        for pasta in ("packages/core-ts/src/logger", "libs/py-core/src/kamba_core/logger"):
            subpastas = [p.name for p in (ROOT / pasta).iterdir() if p.is_dir() and p.name != "__pycache__"]
            self.assertEqual(subpastas, [], pasta)


class TestServicos(unittest.TestCase):
    def test_os_servicos_node_instalam_o_logger_e_ligam_o_tratador_de_erro(self) -> None:
        for servico in SERVICOS_NODE:
            with self.subTest(servico=servico):
                arranque = (ROOT / "services" / servico / "src/server.ts").read_text(encoding="utf-8")
                self.assertIn("const log = instalar(SERVICE);", arranque)
                self.assertIn("createApp(log).fetch", arranque)
                self.assertLess(arranque.index("instalar(SERVICE)"), arranque.index("port(DEFAULT_PORT)"))
                aplicacao = (ROOT / "services" / servico / "src/app.ts").read_text(encoding="utf-8")
                self.assertIn("app.onError(", aplicacao)
                self.assertIn('log?.excepcao(erro, "tratador_falhou")', aplicacao)


if __name__ == "__main__":
    unittest.main()
