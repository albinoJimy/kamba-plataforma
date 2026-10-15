"""Os git hooks sao shell, mas as suas invariantes sao verificaveis.

Nao se corre o shell aqui (o CI e KAM-002); verifica-se o que, se mudar, quebra
os hooks em silencio numa das plataformas da equipa.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOOKS = ROOT / "tools" / "githooks"


class TestHooksExistem(unittest.TestCase):
    def test_os_dois_hooks_existem(self) -> None:
        for nome in ("commit-msg", "pre-push"):
            with self.subTest(hook=nome):
                self.assertTrue((HOOKS / nome).is_file(), f"{nome} em falta")

    def test_o_bit_de_execucao_esta_no_indice_do_git(self) -> None:
        """O modo tem de ser 100755 **no git**, nao so no sistema de ficheiros.

        Em Windows o NTFS nao tem bit de execucao e `core.filemode` e `false`,
        pelo que um `chmod +x` local nao chega ao indice. Um hook guardado como
        `100644` sai de um `git clone` em Linux sem permissao de execucao, e o
        `core.hooksPath` nao o corre — sem erro, sem aviso, sem validacao.
        """
        try:
            resultado = subprocess.run(
                ["git", "ls-files", "-s", "tools/githooks/commit-msg", "tools/githooks/pre-push"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
            self.skipTest(f"git indisponivel: {exc}")

        linhas = [l for l in resultado.stdout.splitlines() if l.strip()]
        self.assertEqual(len(linhas), 2, resultado.stdout)
        for linha in linhas:
            modo, _, resto = linha.partition(" ")
            with self.subTest(ficheiro=resto.split("	")[-1]):
                self.assertEqual(
                    modo,
                    "100755",
                    "corrija com: git update-index --chmod=+x <ficheiro>",
                )

    def test_sao_sh_portavel_e_nao_bash(self) -> None:
        # `core.hooksPath` corre o que a shebang diz. `/bin/sh` existe em todas
        # as plataformas da equipa; `/bin/bash` nao e garantido.
        for nome in ("commit-msg", "pre-push"):
            with self.subTest(hook=nome):
                primeira = (HOOKS / nome).read_text(encoding="utf-8").splitlines()[0]
                self.assertEqual(primeira, "#!/bin/sh")


class TestDeteccaoDePython(unittest.TestCase):
    """O hook tem de encontrar um Python que **funcione**.

    Em Windows, `command -v python3` encontra o atalho da Microsoft Store: um
    ficheiro que existe e que, ao ser corrido, falha com "Python nao foi
    encontrado". Com deteccao por `command -v`, o hook morria com uma mensagem
    que nao tem nada a ver com o commit — aconteceu na maquina onde o KAM-001 foi
    executado.
    """

    def test_a_deteccao_testa_a_execucao(self) -> None:
        fonte = (HOOKS / "_python.sh").read_text(encoding="utf-8")
        self.assertIn('-c ""', fonte, "a deteccao tem de executar o interpretador")

        # `command -v` pode aparecer no comentario que explica porque nao se usa;
        # o que nao pode e aparecer em codigo.
        codigo = [
            linha
            for linha in fonte.splitlines()
            if linha.strip() and not linha.lstrip().startswith("#")
        ]
        for linha in codigo:
            self.assertNotIn(
                "command -v",
                linha,
                "`command -v` da o atalho da Microsoft Store por valido",
            )

    def test_tenta_os_tres_nomes_e_respeita_a_variavel(self) -> None:
        fonte = (HOOKS / "_python.sh").read_text(encoding="utf-8")
        self.assertIn("for candidato in python3 python py", fonte)
        self.assertIn("${PYTHON:-}", fonte)

    def test_os_hooks_usam_a_deteccao_comum(self) -> None:
        for nome in ("commit-msg", "pre-push"):
            with self.subTest(hook=nome):
                fonte = (HOOKS / nome).read_text(encoding="utf-8")
                self.assertIn("_python.sh", fonte)
                self.assertIn("kamba_find_python", fonte)


class TestPortabilidadeDoCaminho(unittest.TestCase):
    """Os hooks nao podem juntar caminhos ao PYTHONPATH com `:`.

    Em Windows o separador de `sys.path` e `;`. Um hook que faca
    `PYTHONPATH="$ROOT/tools:$PYTHONPATH"` quebra com "No module named
    lint_arch" — uma mensagem que nao tem nada a ver com o commit. Aconteceu na
    maquina onde o KAM-001 foi executado, no primeiro `git commit` real.
    """

    def test_nenhum_hook_constroi_pythonpath(self) -> None:
        for nome in ("commit-msg", "pre-push"):
            with self.subTest(hook=nome):
                codigo = [
                    linha
                    for linha in (HOOKS / nome).read_text(encoding="utf-8").splitlines()
                    if linha.strip() and not linha.lstrip().startswith("#")
                ]
                for linha in codigo:
                    self.assertNotIn("PYTHONPATH", linha)

    def test_correm_de_dentro_de_tools(self) -> None:
        for nome in ("commit-msg", "pre-push"):
            with self.subTest(hook=nome):
                fonte = (HOOKS / nome).read_text(encoding="utf-8")
                self.assertIn('cd "$ROOT/tools"', fonte)
                self.assertIn("--root", fonte)

    def test_o_commit_msg_absolutiza_o_caminho_da_mensagem(self) -> None:
        """Depois do `cd`, um caminho relativo deixaria de resolver."""
        fonte = (HOOKS / "commit-msg").read_text(encoding="utf-8")
        self.assertIn("MENSAGEM=", fonte)
        self.assertIn('/* | ?:*', fonte)


class TestHooksCorremSemNodeModules(unittest.TestCase):
    def test_a_validacao_e_pelo_caminho_python(self) -> None:
        """O primeiro commit de um clone nao tem `node_modules`."""
        fonte = (HOOKS / "commit-msg").read_text(encoding="utf-8")
        self.assertIn("lint_arch", fonte)
        # O commitlint corre **se** existir, nunca como unica via.
        self.assertIn("if [ -x", fonte)

    def test_o_commitlint_so_corre_se_houver_node(self) -> None:
        """O shim em `node_modules/.bin` e um script que invoca `node`.

        Numa maquina onde o `node_modules` foi instalado por contentor — a do
        KAM-001 — o shim existe e o `node` nao. Sem a guarda, o hook recusava
        commits com `exec: node: not found`, que nada tem a ver com o commit.
        """
        fonte = (HOOKS / "commit-msg").read_text(encoding="utf-8")
        self.assertIn("command -v node", fonte)

    def test_o_pre_push_valida_as_refs_do_stdin(self) -> None:
        """E nao o `HEAD`.

        `git push origin outro-ramo` empurra `outro-ramo` enquanto o `HEAD` esta
        noutro sitio. Um hook que validasse o `HEAD` daria por conforme um nome
        que nunca examinou — foi assim que um `test/KAM-002-...` passou a
        validacao estando o `HEAD` num `feature/`.
        """
        fonte = (HOOKS / "pre-push").read_text(encoding="utf-8")
        self.assertIn("while read -r", fonte, "tem de ler as refs do stdin")
        self.assertIn("refs/heads/", fonte)
        # O `HEAD` fica como ultimo recurso, nao como fonte principal.
        posicao_stdin = fonte.index("while read -r")
        posicao_head = fonte.index("rev-parse --abbrev-ref HEAD")
        self.assertLess(
            posicao_stdin,
            posicao_head,
            "o stdin e a fonte principal; o HEAD e o recurso de ultima linha",
        )

    def test_o_pre_commit_corre_o_gate_9(self) -> None:
        fonte = (HOOKS / "pre-commit").read_text(encoding="utf-8")
        self.assertIn("scan_secrets", fonte)
        self.assertIn("staged", fonte)


if __name__ == "__main__":
    unittest.main()
