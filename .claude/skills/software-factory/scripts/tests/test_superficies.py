"""As tres superficies, cada defeito plantado ao lado do caso que tem de passar."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import superficies as sup  # noqa: E402


def revisao(numero: str, pai: str | None) -> str:
    pai_txt = "None" if pai is None else f'"{pai}"'
    return f'"""x"""\nrevision = "{numero}"\ndown_revision = {pai_txt}\n'


CADEIA = {
    "db/migrations/versions/0001_a.py": revisao("0001", None),
    "db/migrations/versions/0002_b.py": revisao("0002", "0001"),
}


def tabela(linhas: list[str]) -> str:
    corpo = "\n".join(f"| {v} | Novembro 2026 | emenda | Equipa |" for v in linhas)
    return f"## Controlo de versões\n\n| Versão | Data | Descrição | Autor |\n|---|---|---|---|\n{corpo}\n"


def documento(cabecalho: str, linhas: list[str]) -> str:
    """Um documento com o cabecalho em tabela, como os epics e o dicionario."""
    return (f"# Doc\n\n| Campo | Valor |\n|---|---|\n| Versão | {cabecalho} |\n\n"
            f"| 1.6 | uma linha de checklist que nao e emenda |\n\n{tabela(linhas)}")


def indice(cabecalho: str, linhas: list[str]) -> str:
    """Um documento com o cabecalho em texto, como o `specs/INDICE.md`."""
    return f"# Indice\n\n**Versão do conjunto:** {cabecalho}\n\nprosa\n\n{tabela(linhas)}"


class TestCadeia(unittest.TestCase):
    def test_uma_cadeia_linear_nao_tem_problemas(self) -> None:
        self.assertEqual(sup.problemas_da_cadeia(CADEIA), [])
        self.assertEqual(sup.cabeca(CADEIA), "0002")

    def test_duas_0003_sao_uma_colisao(self) -> None:
        cadeia = dict(CADEIA)
        cadeia["db/migrations/versions/0003_oferta.py"] = revisao("0003", "0002")
        cadeia["db/migrations/versions/0003_direitos.py"] = revisao("0003", "0002")
        problemas = sup.problemas_da_cadeia(cadeia)
        self.assertTrue(any("revisao 0003 em 2 ficheiros" in p for p in problemas), problemas)

    def test_um_pai_que_falta_e_o_buraco_do_158(self) -> None:
        cadeia = dict(CADEIA)
        cadeia["db/migrations/versions/0004_direitos.py"] = revisao("0004", "0003")
        problemas = sup.problemas_da_cadeia(cadeia)
        self.assertTrue(any("aponta para 0003, que nao existe" in p for p in problemas), problemas)

    def test_duas_cabecas(self) -> None:
        cadeia = dict(CADEIA)
        cadeia["db/migrations/versions/0003_a.py"] = revisao("0003", "0002")
        cadeia["db/migrations/versions/0004_b.py"] = revisao("0004", "0002")
        self.assertTrue(any("2 cabecas" in p for p in sup.problemas_da_cadeia(cadeia)))

    def test_o_nome_e_o_revision_tem_de_concordar(self) -> None:
        cadeia = dict(CADEIA)
        cadeia["db/migrations/versions/0004_renumerada.py"] = revisao("0003", "0002")
        self.assertTrue(any("o ficheiro diz 0004 e o `revision` diz 0003" in p
                            for p in sup.problemas_da_cadeia(cadeia)))

    def test_le_a_forma_anotada_do_revision(self) -> None:
        texto = 'revision: str = "0007"\ndown_revision: Union[str, None] = "0006"\n'
        self.assertEqual(sup.revisao_e_pai(texto), ("0007", "0006"))


class TestVersoes(unittest.TestCase):
    def test_conta_so_as_linhas_da_tabela_de_controlo(self) -> None:
        self.assertEqual(sup.versoes(documento("1.2", ["1.1", "1.2"])), ["1.1", "1.2"])

    def test_a_tabela_acaba_na_primeira_linha_que_nao_e_tabela(self) -> None:
        texto = documento("1.2", ["1.1", "1.2"]) + "\nprosa\n\n| 1.9 | uma linha solta |\n"
        self.assertEqual(sup.versoes(texto), ["1.1", "1.2"])

    def test_um_documento_coerente_nao_tem_problemas(self) -> None:
        self.assertEqual(sup.problemas_de_versoes(sup.DICIONARIO, documento("1.10", ["1.9", "1.10"])), [])
        self.assertEqual(sup.problemas_de_versoes("specs/INDICE.md", indice("1.3", ["1.2", "1.1", "1.3"])), [])

    def test_o_maximo_e_numerico_e_nao_a_ultima_linha(self) -> None:
        self.assertEqual(sup.maximo(["1.12", "1.15", "1.14", "1.13"]), "1.15")
        self.assertEqual(sup.maximo(["1.9", "1.10"]), "1.10")

    def test_tres_1_68_sao_repetidas(self) -> None:
        problemas = sup.problemas_de_versoes("specs/x.md", documento("1.68", ["1.67", "1.68", "1.68", "1.68"]))
        self.assertTrue(any("1.68 aparece mais de uma vez" in p for p in problemas), problemas)

    def test_um_buraco_na_sequencia(self) -> None:
        problemas = sup.problemas_de_versoes(sup.DICIONARIO, documento("1.4", ["1.1", "1.2", "1.4"]))
        self.assertEqual(problemas, [f"{sup.DICIONARIO}: falta a versao 1.3 na sequencia "
                                     "(VERMELHO no gate 3c)"])

    def test_cabecalho_atras_da_emenda_no_dicionario(self) -> None:
        problemas = sup.problemas_de_versoes(sup.DICIONARIO, documento("1.67", ["1.67", "1.68"]))
        self.assertEqual(len(problemas), 1)
        self.assertIn("VERMELHO no gate 3c, e no dict_export", problemas[0])

    def test_cabecalho_em_texto_do_indice_atras_da_emenda(self) -> None:
        """O achado 1 da revisao: a forma `**Versao do conjunto:**` nao se lia."""
        texto = indice("1.2", ["1.1", "1.2", "1.3"])
        self.assertEqual(sup.cabecalho(texto), "1.2")
        problemas = sup.problemas_de_versoes("specs/INDICE.md", texto)
        self.assertTrue(any("cabecalho 1.2" in p and "VERMELHO no gate 3c" in p
                            for p in problemas), problemas)

    def test_o_atraso_e_vermelho_em_qualquer_epic_e_nao_so_no_dicionario(self) -> None:
        problemas = sup.problemas_de_versoes("specs/EPIC-03.md", documento("1.13", ["1.13", "1.14"]))
        self.assertIn("VERMELHO no gate 3c", problemas[0])

    def test_fora_do_gate_diz_que_esta_fora(self) -> None:
        texto = documento("1.13", ["1.13", "1.14"])
        self.assertIn("fora do gate 3c", sup.problemas_de_versoes("docs/evidencia/x.md", texto)[0])
        self.assertIn("fora do gate 3c", sup.problemas_de_versoes("notas/x.md", texto)[0])

    def test_acrescentadas_sao_as_que_o_ramo_escreveu(self) -> None:
        antes = documento("1.2", ["1.1", "1.2"])
        depois = documento("1.3", ["1.1", "1.2", "1.3"])
        self.assertEqual(sup.acrescentadas(antes, depois), ["1.3"])
        self.assertEqual(sup.acrescentadas(antes, antes), [])
        self.assertEqual(sup.acrescentadas(None, depois), ["1.1", "1.2", "1.3"])

    def test_seguinte(self) -> None:
        self.assertEqual(sup.seguinte("1.9"), "1.10")


class TestPiso(unittest.TestCase):
    def test_a_fronteira_dos_dois_ensaios(self) -> None:
        self.assertIsNone(sup.problema_do_piso(87, 43))       # 87 // 2 = 43
        self.assertIsNone(sup.problema_do_piso(88, 44))
        self.assertIn("sobe `MINIMO_DE_BLOCOS_MEDIDOS` para 44", sup.problema_do_piso(88, 43))
        self.assertIn("acima", sup.problema_do_piso(10, 11))

    def test_le_a_constante_do_lint(self) -> None:
        texto = "#: comentario\nMINIMO_DE_BLOCOS_MEDIDOS = 44\n\nMINIMO_DE_BLOCOS = 150\n"
        self.assertEqual(sup.PISO.search(texto).group(1), "44")


if __name__ == "__main__":
    unittest.main()
