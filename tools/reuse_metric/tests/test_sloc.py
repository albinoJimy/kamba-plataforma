"""O contador de linhas de codigo: o que conta, e o que nao conta (KAM-039).

A bateria existe porque a unidade da metrica e esta funcao. Um contador que
conte prosa transforma «quanto codigo e que a vertical nova escreveu» em
«quanto e que ela comentou», e o numero passa a mover-se ao contrario do que
afirma medir.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from reuse_metric.sloc import (
    FonteInvalidaError,
    SimboloAusenteError,
    linhas_de_codigo,
    sloc_de_ficheiro,
    sloc_de_simbolo,
)


def conta(fonte: str) -> int:
    return len(linhas_de_codigo(textwrap.dedent(fonte)))


class TestOQueNaoEhCodigo(unittest.TestCase):
    def test_comentario_nao_conta(self) -> None:
        self.assertEqual(conta("# so um comentario\n"), 0)

    def test_linha_vazia_nao_conta(self) -> None:
        self.assertEqual(conta("\n\n\n"), 0)

    def test_docstring_de_modulo_nao_conta(self) -> None:
        self.assertEqual(conta('"""Tres\nlinhas\nde prosa."""\n'), 0)

    def test_docstring_de_funcao_nao_conta(self) -> None:
        """Duas linhas de codigo (o `def` e o `return`), e nao cinco."""
        self.assertEqual(
            conta(
                """
                def f():
                    \"\"\"Prosa
                    em duas linhas.
                    \"\"\"
                    return 1
                """
            ),
            2,
        )

    def test_cadeia_solta_como_comentario_de_bloco_nao_conta(self) -> None:
        """Este repositorio usa-as; sao instrucoes de expressao, logo prosa."""
        self.assertEqual(
            conta(
                """
                x = 1
                \"\"\"Um comentario de bloco escrito como cadeia.\"\"\"
                y = 2
                """
            ),
            2,
        )


class TestOQueEhCodigo(unittest.TestCase):
    def test_import_conta(self) -> None:
        self.assertEqual(conta("import os\nfrom pathlib import Path\n"), 2)

    def test_cadeia_que_e_VALOR_conta(self) -> None:
        """**A correccao que a primeira versao desta funcao precisou.**

        Excluir qualquer cadeia de tres aspas contava a menos: um SQL ou um
        texto de persona guardado numa constante e codigo que alguem escreveu e
        mantem. Ha-os no `privacidade/catalogo.py` e nos `nos.py` das duas
        verticais.
        """
        self.assertEqual(
            conta(
                '''
                SQL = """
                SELECT 1
                """
                '''
            ),
            3,
        )

    def test_linha_de_continuacao_conta_uma_vez_por_linha(self) -> None:
        self.assertEqual(conta("x = (\n    1\n    + 2\n)\n"), 4)

    def test_decorador_conta(self) -> None:
        self.assertEqual(conta("@algo\ndef f():\n    return 1\n"), 3)


class TestFicheiroEhSimbolo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def escrever(self, nome: str, texto: str) -> Path:
        alvo = self.raiz / nome
        alvo.write_text(textwrap.dedent(texto), encoding="utf-8")
        return alvo

    def test_sloc_de_ficheiro(self) -> None:
        alvo = self.escrever("a.py", '"""Prosa."""\nimport os\nx = 1\n')
        self.assertEqual(sloc_de_ficheiro(alvo), 2)

    def test_sloc_de_simbolo_conta_so_a_definicao(self) -> None:
        alvo = self.escrever(
            "b.py",
            """
            \"\"\"Prosa do modulo.\"\"\"
            import os

            TECTO = 3

            def um():
                return 1

            def dois():
                a = 1
                b = 2
                return a + b
            """,
        )
        self.assertEqual(sloc_de_simbolo(alvo, "um"), 2)
        self.assertEqual(sloc_de_simbolo(alvo, "dois"), 4)
        # E o ficheiro inteiro e mais do que a soma das duas, porque leva o
        # `import` e a constante de topo. A metrica conta simbolos **so** nos
        # ficheiros mistos, e e por isso que a diferenca importa: contar o
        # ficheiro onde se devia contar o simbolo punha no partilhado codigo
        # que a vertical nova nunca importou.
        self.assertEqual(sloc_de_ficheiro(alvo), 8)

    def test_sloc_de_simbolo_de_uma_constante(self) -> None:
        alvo = self.escrever("c.py", "TABELA = {\n    'a': 1,\n    'b': 2,\n}\n")
        self.assertEqual(sloc_de_simbolo(alvo, "TABELA"), 4)

    def test_simbolo_ausente_levanta(self) -> None:
        """Nao devolve zero: um simbolo que desapareceu mudou o caminho."""
        alvo = self.escrever("d.py", "x = 1\n")
        with self.assertRaises(SimboloAusenteError):
            sloc_de_simbolo(alvo, "nao_existe")

    def test_simbolo_aninhado_nao_se_alcanca(self) -> None:
        """O que se importa de um modulo e o que ele expoe no topo."""
        alvo = self.escrever("e.py", "def fora():\n    def dentro():\n        return 1\n")
        with self.assertRaises(SimboloAusenteError):
            sloc_de_simbolo(alvo, "dentro")

    def test_sintaxe_invalida_levanta_em_vez_de_contar_zero(self) -> None:
        """Contar zero era a forma de um erro de sintaxe **subir** o reuso."""
        alvo = self.escrever("f.py", "def (:\n")
        with self.assertRaises(FonteInvalidaError):
            sloc_de_ficheiro(alvo)


class TestMutacaoDaUnidade(unittest.TestCase):
    """**O canario da unidade.** Trinta linhas de comentario nao sao reuso.

    Se esta propriedade cair, a metrica passa a medir densidade de prosa — que
    e precisamente o defeito que o `wc -l` tem e que esta funcao existe para
    nao ter. Mede-se nas duas direccoes: a prosa nao move o numero, e uma linha
    de codigo move-o.
    """

    def test_acrescentar_prosa_nao_muda_a_contagem(self) -> None:
        base = "def f():\n    return 1\n"
        com_prosa = (
            "# " + "\n# ".join(["razao"] * 30) + "\n" + 'x = """\nnao\n"""\n' + base
        )
        # A cadeia e um VALOR (tres linhas de codigo), logo a diferenca e 3 e
        # nao 33: os trinta comentarios nao contam.
        self.assertEqual(conta(com_prosa) - conta(base), 3)

    def test_acrescentar_codigo_muda_a_contagem(self) -> None:
        base = "def f():\n    return 1\n"
        self.assertEqual(conta(base + "y = 2\n") - conta(base), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
