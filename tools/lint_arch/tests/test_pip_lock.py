"""`pip_lock`: comparacao de versoes, marcadores e verificacao de fecho.

Nenhum destes casos toca na rede. Os que exigem PyPI vivem em `make lock-verify`,
e e por isso que `--check-offline` existe separado — o criterio de aceitacao do
KAM-001 pede que `make check` termine verde «usando apenas lockfiles».
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pip_lock
from pip_lock import (
    MarkerUndecided,
    _compare,
    canonical,
    check_offline,
    marker_is_true,
    read_pins,
)

ROOT = Path(__file__).resolve().parents[3]


class TestCanonical(unittest.TestCase):
    """PEP 503: `-`, `_` e `.` sao equivalentes."""

    def test_variantes(self) -> None:
        for bruto in ("typing-extensions", "typing_extensions", "Typing.Extensions"):
            with self.subTest(bruto=bruto):
                self.assertEqual(canonical(bruto), "typing-extensions")


class TestCompare(unittest.TestCase):
    def test_versoes(self) -> None:
        self.assertTrue(_compare("3.12", ">=", "3.9"))
        self.assertFalse(_compare("3.12", "<", "3.11"))
        self.assertTrue(_compare("3.12", "==", "3.12"))

    def test_comparacao_numerica_e_nao_lexicografica(self) -> None:
        self.assertTrue(_compare("3.10", ">", "3.9"))

    def test_wildcard_pep440(self) -> None:
        """`X.*` e legal e comum em `requires_dist`.

        Comparado como texto, `"3.12" == "3.12.*"` e falso — e era o unico ponto
        *fail-open* do modulo: o marcador dava-se por falso, a dependencia por
        desnecessaria, e ficava fora da verificacao de fecho.
        """
        self.assertTrue(_compare("3.12", "==", "3.12.*"))
        self.assertTrue(_compare("3.12.1", "==", "3.12.*"))
        self.assertFalse(_compare("3.11", "==", "3.12.*"))
        self.assertFalse(_compare("3.12", "!=", "3.12.*"))

    def test_wildcard_so_com_igualdade(self) -> None:
        with self.assertRaises(MarkerUndecided):
            _compare("3.12", "<", "3.12.*")

    def test_tipos_mistos_sao_indecidiveis(self) -> None:
        """Comparar `3.12` com `cpython` como texto devolvia uma resposta que
        ninguem pediu."""
        with self.assertRaises(MarkerUndecided):
            _compare("3.12", "==", "cpython")


class TestMarcadores(unittest.TestCase):
    def test_versao_de_python(self) -> None:
        self.assertTrue(marker_is_true('python_version < "3.13"'))
        self.assertFalse(marker_is_true('python_version < "3.11"'))

    def test_extra_torna_falso(self) -> None:
        self.assertFalse(marker_is_true('extra == "standard"'))

    def test_extra_decide_mesmo_com_clausula_indecidivel(self) -> None:
        """O caso do `coverage`.

        Declara `tomli; python_full_version <= "3.11.0a6" and extra == "toml"`.
        A primeira clausula compara com `3.11.0a6`, que nao e numerica, e
        levantava `MarkerUndecided`; o fecho passava a exigir `tomli`, que nunca
        e instalado. Numa cadeia `and`, uma clausula definitivamente falsa decide
        o resultado.
        """
        self.assertFalse(
            marker_is_true('python_full_version <= "3.11.0a6" and extra == "toml"')
        )

    def test_plataforma_conta_como_necessaria(self) -> None:
        """O lock e multi-plataforma: e o pip que decide, nao nos."""
        self.assertTrue(marker_is_true('sys_platform == "win32"'))

    def test_sem_marcador(self) -> None:
        self.assertTrue(marker_is_true(None))
        self.assertTrue(marker_is_true(""))

    def test_or_e_indecidivel(self) -> None:
        with self.assertRaises(MarkerUndecided):
            marker_is_true('python_version < "3.11" or extra == "x"')


class TestReadPins(unittest.TestCase):
    def test_le_os_pins_do_repositorio(self) -> None:
        pins = read_pins(ROOT / "tools" / "requirements" / "tools.in")
        nomes = {canonical(p["name"]) for p in pins}
        self.assertIn("jsonschema", nomes)
        self.assertIn("coverage", nomes)

    def test_recusa_linha_sem_pin_exacto(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "x.in"
            caminho.write_text("jsonschema>=4\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                read_pins(caminho)

    def test_recusa_ficheiro_vazio(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "x.in"
            caminho.write_text("# so comentarios\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                read_pins(caminho)


class TestCheckOffline(unittest.TestCase):
    """A verificacao que `make check` corre: sem rede."""

    def test_os_locks_do_repositorio_estao_coerentes(self) -> None:
        for base in ("tools/requirements/tools", "services/agr/requirements/runtime"):
            with self.subTest(lock=base):
                problemas = check_offline(
                    ROOT / f"{base}.in", ROOT / f"{base}.txt"
                )
                self.assertEqual(problemas, [], "\n".join(problemas))

    def test_txt_em_falta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origem = Path(tmp) / "x.in"
            origem.write_text("jsonschema==4.26.0\n", encoding="utf-8")
            problemas = check_offline(origem, Path(tmp) / "x.txt")
            self.assertTrue(problemas)
            self.assertIn("nao existe", problemas[0])

    def test_versao_divergente(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origem = Path(tmp) / "x.in"
            destino = Path(tmp) / "x.txt"
            origem.write_text("jsonschema==4.26.0\n", encoding="utf-8")
            destino.write_text(
                "jsonschema==4.25.0 \\\n    --hash=sha256:" + "a" * 64 + "\n",
                encoding="utf-8",
            )
            problemas = check_offline(origem, destino)
            self.assertTrue(any("4.25.0" in p for p in problemas))

    def test_pin_sem_hash(self) -> None:
        """Sem hash, `--require-hashes` recusa — e o gate tem de o dizer antes."""
        with tempfile.TemporaryDirectory() as tmp:
            origem = Path(tmp) / "x.in"
            destino = Path(tmp) / "x.txt"
            origem.write_text("jsonschema==4.26.0\n", encoding="utf-8")
            destino.write_text("jsonschema==4.26.0\n", encoding="utf-8")
            problemas = check_offline(origem, destino)
            self.assertTrue(any("--hash" in p for p in problemas))

    def test_pacote_a_mais_no_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origem = Path(tmp) / "x.in"
            destino = Path(tmp) / "x.txt"
            origem.write_text("jsonschema==4.26.0\n", encoding="utf-8")
            destino.write_text(
                "jsonschema==4.26.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"
                "intruso==1.0.0 \\\n    --hash=sha256:" + "b" * 64 + "\n",
                encoding="utf-8",
            )
            problemas = check_offline(origem, destino)
            self.assertTrue(any("intruso" in p for p in problemas))


class TestRender(unittest.TestCase):
    def test_o_cabecalho_diz_como_instalar(self) -> None:
        """Quem abre o `.txt` tem de ver `--require-hashes` sem procurar."""
        texto = (ROOT / "tools" / "requirements" / "tools.txt").read_text(encoding="utf-8")
        self.assertIn("--require-hashes", texto)
        self.assertIn("NAO EDITAR A MAO", texto)

    def test_o_ambiente_alvo_esta_declarado(self) -> None:
        self.assertEqual(pip_lock.TARGET_ENV["python_version"], "3.12")


if __name__ == "__main__":
    unittest.main()
