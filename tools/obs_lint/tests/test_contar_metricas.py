"""Testes do `contar_metricas` — o instrumento por tras dos numeros do KAM-080.

Este ficheiro existe pela razao que a revisao adversarial tornou visivel: a
secao de verificacao do bloco citava «109 metricas, 23 servidas, 7 alcancaveis»
em quatro sitios **sem comando nenhum**, e um numero reconstruido a mao e
INDICIO. O instrumento fechou essa lacuna; estes testes fecham a seguinte, que e
«e o instrumento esta certo?».

O que se prende aqui e o **predicado**, nao o numero. Um numero muda com o
repositorio; o predicado e o que decide se o numero quer dizer algo.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from obs_lint import contar_metricas as cm

RAIZ = Path(__file__).resolve().parents[3]


class _ComArvore(unittest.TestCase):
    """Monta uma arvore minima, para medir o predicado e nao o repositorio."""

    def arvore(self, ficheiros: dict[str, str]) -> Path:
        raiz = Path(tempfile.mkdtemp(prefix="contar-"))
        self.addCleanup(shutil.rmtree, raiz, ignore_errors=True)
        for caminho, conteudo in ficheiros.items():
            alvo = raiz / caminho
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text(conteudo, encoding="utf-8")
        return raiz


class TestPredicado(_ComArvore):
    """O predicado 1: um modulo de metricas e o que emite formato de exposicao."""

    def test_um_ficheiro_sem_type_nao_e_modulo_de_metricas(self) -> None:
        """E o predicado, e nao o nome: um `metricas.ts` sem `# TYPE` nao conta."""
        raiz = self.arvore(
            {"packages/x/src/metricas.ts": 'export const METRICA_A = "a_total";\n'}
        )
        self.assertEqual(cm._modulos(raiz), [])

    def test_um_ficheiro_com_type_e_modulo_mesmo_com_outro_nome(self) -> None:
        raiz = self.arvore(
            {
                "packages/x/src/qualquer.ts": (
                    'const AJUDA = "# TYPE";\nexport const METRICA_A = "a_total";\n'
                )
            }
        )
        self.assertEqual([p.name for p in cm._modulos(raiz)], ["qualquer.ts"])

    def test_as_pastas_ignoradas_nao_entram(self) -> None:
        corpo = 'const A = "# TYPE";\nexport const METRICA_A = "a_total";\n'
        raiz = self.arvore(
            {
                "packages/x/node_modules/m/metricas.ts": corpo,
                "packages/x/dist/metricas.ts": corpo,
                "packages/x/tests/metricas.ts": corpo,
                "packages/x/src/metricas.ts": corpo,
            }
        )
        self.assertEqual([p.parent.name for p in cm._modulos(raiz)], ["src"])

    def test_so_as_tres_raizes_se_leem(self) -> None:
        corpo = 'const A = "# TYPE";\nexport const METRICA_A = "a_total";\n'
        raiz = self.arvore({"tools/x/metricas.ts": corpo, "docs/metricas.ts": corpo})
        self.assertEqual(cm._modulos(raiz), [])


class TestNomes(_ComArvore):
    """O predicado 2: o que e, e o que nao e, um nome de metrica."""

    def _nomes(self, corpo: str, extensao: str = ".ts") -> set[str]:
        raiz = self.arvore({f"packages/x/src/metricas{extensao}": corpo})
        return cm._nomes(raiz / f"packages/x/src/metricas{extensao}")

    def test_uma_constante_METRICA_da_o_nome(self) -> None:
        corpo = '# TYPE\nexport const METRICA_ENVIADAS = "outbound_sent_total";\n'
        self.assertEqual(self._nomes(corpo), {"outbound_sent_total"})

    def test_a_forma_com_Final_do_python_tambem(self) -> None:
        corpo = '# TYPE\nMETRICA_TURNOS: Final = "agr_turns_total"\n'
        self.assertEqual(self._nomes(corpo, ".py"), {"agr_turns_total"})

    def test_uma_chave_de_tabela_de_ajuda_da_o_nome(self) -> None:
        corpo = '# TYPE\nconst AJUDA = {\n  "gwy_requests_total": ["counter", "x"],\n};\n'
        self.assertEqual(self._nomes(corpo), {"gwy_requests_total"})

    def test_uma_etiqueta_nao_e_uma_metrica(self) -> None:
        """A razao de o predicado ser estreito: `ETIQUETAS` nao sao metricas."""
        corpo = (
            "# TYPE\n"
            'export const ETIQUETA = "filtro";\n'
            'export const ORIGENS = ["bucket", "meta"];\n'
            'export const METRICA_A = "a_total";\n'
        )
        self.assertEqual(self._nomes(corpo), {"a_total"})

    def test_um_nome_sem_underscore_nao_conta(self) -> None:
        corpo = '# TYPE\nexport const METRICA_A = "up";\n'
        self.assertEqual(self._nomes(corpo), set())

    def test_um_nome_com_maiusculas_nao_conta(self) -> None:
        corpo = '# TYPE\nexport const METRICA_A = "Nao_E_Nome";\n'
        self.assertEqual(self._nomes(corpo), set())

    def test_uma_docstring_python_que_lista_metricas_nao_conta(self) -> None:
        """Os modulos desta casa listam as metricas em prosa no cabecalho.

        Sem retirar os comentarios, a tabela do cabecalho era contada duas
        vezes — e e por isso que o `_nomes` os retira em Python.
        """
        corpo = (
            "# TYPE\n"
            '# METRICA_FALSA = "nao_existe_total"\n'
            'METRICA_A: Final = "existe_total"\n'
        )
        self.assertEqual(self._nomes(corpo, ".py"), {"existe_total"})


class TestRepositorio(unittest.TestCase):
    """Sobre a arvore real, e com a reconciliacao escrita."""

    def test_os_dezoito_modulos_e_o_piso_de_cento_e_sete(self) -> None:
        """Os dois numeros que a documentacao cita, prendidos aqui.

        Se um modulo de metricas nascer ou morrer, este teste falha — e e isso
        que se quer: a documentacao cita **109**, que e 107 mais os dois do COM,
        e um numero que se mexe sem ninguem notar e pior do que nenhum.
        """
        modulos = cm._modulos(RAIZ)
        todos: set[str] = set()
        for modulo in modulos:
            todos |= cm._nomes(modulo)
        self.assertEqual(len(modulos), 18, [p.name for p in modulos])
        self.assertEqual(len(todos), 107)

    def test_o_com_conta_zero_e_e_a_reconciliacao_de_107_para_109(self) -> None:
        """O módulo do COM declara 0 porque importa os nomes de `repo-base`.

        É a diferença entre 107 e os 109 que a documentação cita, e está escrita
        em `docs/observabilidade.md` §2.1.
        """
        modulo = RAIZ / "services" / "com" / "src" / "metricas.ts"
        self.assertEqual(cm._nomes(modulo), set())
        repo_base = (RAIZ / "services/com/src/repo-base/index.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn('"com_repo_filtro_em_falta_total"', repo_base)
        self.assertIn('"com_repo_consultas_total"', repo_base)

    def test_o_agr_declara_quarenta_e_quatro(self) -> None:
        """O número que o ticket cita como a lacuna que fechou."""
        modulo = RAIZ / "services" / "agr" / "src" / "kamba_agr" / "metricas.py"
        self.assertEqual(len(cm._nomes(modulo)), 44)


class TestCli(unittest.TestCase):
    def test_sai_com_zero_na_arvore_real(self) -> None:
        self.assertEqual(cm.main(["--root", str(RAIZ)]), 0)

    def test_com_detalhe_tambem(self) -> None:
        self.assertEqual(cm.main(["--root", str(RAIZ), "--detalhe"]), 0)

    def test_uma_arvore_sem_modulos_sai_com_dois(self) -> None:
        """Zero módulos não é um zero útil: é «não se conseguiu verificar»."""
        vazia = Path(tempfile.mkdtemp(prefix="contar-vazia-"))
        self.addCleanup(shutil.rmtree, vazia, ignore_errors=True)
        self.assertEqual(cm.main(["--root", str(vazia)]), 2)


if __name__ == "__main__":
    unittest.main()
