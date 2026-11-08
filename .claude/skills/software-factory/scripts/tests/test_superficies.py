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


def documento(cabecalho: str, linhas: list[str]) -> str:
    tabela = "\n".join(f"| {v} | Novembro 2026 | emenda | Equipa |" for v in linhas)
    return (f"# Doc\n\n| Campo | Valor |\n|---|---|\n| Versão | {cabecalho} |\n\n"
            f"| 1.6 | uma linha de checklist que nao e emenda |\n\n"
            f"## Controlo de versões\n\n| Versão | Data | Descrição | Autor |\n"
            f"|---|---|---|---|\n{tabela}\n")


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

    def test_um_documento_coerente_nao_tem_problemas(self) -> None:
        self.assertEqual(sup.problemas_de_versoes(sup.DICIONARIO, documento("1.10", ["1.9", "1.10"])), [])

    def test_o_maximo_e_numerico_e_nao_a_ultima_linha(self) -> None:
        self.assertEqual(sup.maximo(["1.12", "1.15", "1.14", "1.13"]), "1.15")
        self.assertEqual(sup.maximo(["1.9", "1.10"]), "1.10")

    def test_tres_1_68_sao_duplicados(self) -> None:
        problemas = sup.problemas_de_versoes("x.md", documento("1.68", ["1.67", "1.68", "1.68", "1.68"]))
        self.assertTrue(any("1.68 aparece 3 vezes" in p for p in problemas), problemas)

    def test_cabecalho_atras_da_emenda_e_vermelho_no_dicionario(self) -> None:
        problemas = sup.problemas_de_versoes(sup.DICIONARIO, documento("1.67", ["1.67", "1.68"]))
        self.assertEqual(len(problemas), 1)
        self.assertIn("VERMELHO no dict_export", problemas[0])

    def test_e_indicio_fora_do_dicionario(self) -> None:
        problemas = sup.problemas_de_versoes("specs/EPIC-03.md", documento("1.13", ["1.13", "1.14"]))
        self.assertIn("INDICIO", problemas[0])

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


if __name__ == "__main__":
    unittest.main()
