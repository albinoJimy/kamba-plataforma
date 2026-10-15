"""A estrutura obrigatoria e os ficheiros proibidos."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lint_arch import structure

ROOT = Path(__file__).resolve().parents[3]


class TestRepositorio(unittest.TestCase):
    def test_a_arvore_do_repositorio_esta_conforme(self) -> None:
        self.assertEqual(structure.check(ROOT), [])

    def test_os_cinco_servicos_sao_os_da_topologia(self) -> None:
        # docs/tecnica/09 §3.1: a vitrine Next.js fica para Clusters (ADR-019) e por
        # isso nao esta aqui; o onboarding-web entra em seu lugar.
        self.assertEqual(
            structure.SERVICES,
            ("gwy", "worker-canal", "agr", "com", "onboarding-web"),
        )


class TestArvoreIncompleta(unittest.TestCase):
    def test_arvore_vazia_acusa_tudo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            problemas = structure.check(Path(tmp))
            self.assertNotEqual(problemas, [])
            texto = "\n".join(problemas)
            for esperado in ("services", "Makefile", "tools/blocklist.yaml"):
                self.assertIn(esperado, texto)

    def test_servico_sem_dockerfile_e_acusado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            for servico in structure.SERVICES:
                (raiz / "services" / servico / "src").mkdir(parents=True)
                (raiz / "services" / servico / "tests").mkdir(parents=True)
            problemas = structure.check(raiz)
            for servico in structure.SERVICES:
                self.assertIn(f"services/{servico}/Dockerfile em falta", problemas)

    def test_servico_a_mais_e_acusado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "services" / "storefront").mkdir(parents=True)
            problemas = "\n".join(structure.check(raiz))
            self.assertIn("services/storefront/", problemas)
            self.assertIn("docs/tecnica/09", problemas)


class TestFicheirosProibidos(unittest.TestCase):
    def test_pnpmfile_e_recusado(self) -> None:
        """O `.pnpmfile` corre mesmo com `ignore-scripts=true`."""
        for nome in structure.FORBIDDEN_FILES:
            with self.subTest(nome=nome):
                with tempfile.TemporaryDirectory() as tmp:
                    raiz = Path(tmp)
                    (raiz / nome).write_text("module.exports = {}\n", encoding="utf-8")
                    problemas = "\n".join(structure.check(raiz))
                    self.assertIn(nome, problemas)
                    self.assertIn("ignore-scripts", problemas)

    def test_pnpmfile_em_subdirectorio_tambem_e_recusado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "packages" / "contracts").mkdir(parents=True)
            (raiz / "packages" / "contracts" / ".pnpmfile.cjs").write_text(
                "module.exports = {}\n", encoding="utf-8"
            )
            problemas = "\n".join(structure.check(raiz))
            self.assertIn("packages/contracts/.pnpmfile.cjs", problemas)

    def test_o_repositorio_nao_tem_nenhum(self) -> None:
        for nome in structure.FORBIDDEN_FILES:
            with self.subTest(nome=nome):
                encontrados = [
                    p for p in ROOT.rglob(nome) if "node_modules" not in p.parts
                ]
                self.assertEqual(encontrados, [])


if __name__ == "__main__":
    unittest.main()
