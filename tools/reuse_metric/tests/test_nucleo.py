"""O criterio (d): nomes de vertical no nucleo, e a prova de que morde.

A armadilha que esta bateria fecha e a que esta casa ja pagou seis vezes num
ticket so: **um teste que mede o caso errado passa, e passa com confianca.** Um
verificador que devolve `fluxo = 0` sobre uma arvore sa nao provou nada — pode
estar a devolver zero porque nao sabe procurar. Por isso o que importa aqui nao
sao os testes que confirmam o verde: sao os que injectam a excepcao e exigem
vermelho, e os que injectam a **configuracao** e exigem que o verde se mantenha.
As duas direccoes, sempre.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from kamba_yaml import load_file

from reuse_metric.nucleo import (
    DeclaracaoDoNucleo,
    DeclaracaoDoNucleoInvalidaError,
    ficheiros_do_nucleo,
    verificar,
)
from reuse_metric.tests import arvore


class _ComArvore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.raiz = arvore.montar(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    @property
    def declaracao(self) -> dict:
        return load_file(self.raiz / "ci" / "regra-de-dois.yaml")

    def escrever_no_nucleo(self, texto: str) -> None:
        """Poe `texto` num ficheiro de nucleo, que e onde o criterio olha."""
        alvo = self.raiz / "pkg" / "nucleo.py"
        alvo.write_text(textwrap.dedent(texto), encoding="utf-8")

    def veredicto(self):
        return verificar(self.raiz, self.declaracao)


class TestArvoreSa(_ComArvore):
    def test_sem_nomes_de_vertical_o_nucleo_passa(self) -> None:
        self.escrever_no_nucleo("def correr(estado):\n    return estado\n")
        veredicto = self.veredicto()
        self.assertTrue(veredicto.passa)
        self.assertEqual((veredicto.fluxo, veredicto.conteudo), (0, 0))

    def test_o_que_esta_em_verticais_nao_e_nucleo(self) -> None:
        """Senao o criterio (d) falhava sobre o unico sitio onde pode falhar."""
        relativos = {
            f.relative_to(self.raiz).as_posix() for f in ficheiros_do_nucleo(
                self.raiz, DeclaracaoDoNucleo.de_mapa(self.declaracao, onde="teste")
            )
        }
        self.assertIn("pkg/nucleo.py", relativos)
        self.assertEqual([r for r in relativos if "verticais" in r], [])


class TestProsaNaoEhExcepcao(_ComArvore):
    def test_comentario_que_nomeia_a_vertical_nao_reprova(self) -> None:
        """**A razao pela qual um `grep` nao serve.**

        A convencao da casa e explicar por extenso **porque** e que o nucleo
        nao depende de uma vertical. Um portao que contasse essa explicacao
        obrigava a apaga-la para ficar verde.
        """
        self.escrever_no_nucleo(
            """
            # A tranca e por conversa e nao por vertical: nem a nova nem a
            # velha mudam a chave.
            def correr(estado):
                return estado
            """
        )
        veredicto = self.veredicto()
        self.assertTrue(veredicto.passa)
        self.assertEqual(veredicto.fluxo, 0)
        self.assertEqual(veredicto.prosa, 2)

    def test_docstring_que_nomeia_a_vertical_nao_reprova(self) -> None:
        self.escrever_no_nucleo('"""Serve a nova e a velha."""\nx = 1\n')
        self.assertTrue(self.veredicto().passa)
        self.assertEqual(self.veredicto().prosa, 2)


class TestConfiguracaoNaoEhFluxo(_ComArvore):
    """«Verticais como configuracao» e a tese do ADR-012, nao a sua violacao.

    Uma tabela indexada pelo `id` da vertical conta como `conteudo`: nomeia-se,
    conta-se, vai ao relatorio — e **nao** reprova a condicao (d) por si. Onde
    passa a fronteira entre «tabela» e «excepcao» e decisao de quem assina o
    ADR-012; o que esta bateria fixa e que as duas coisas nao se confundem.
    """

    def test_tabela_indexada_pela_vertical_e_conteudo_e_nao_fluxo(self) -> None:
        self.escrever_no_nucleo(
            """
            TEXTOS = {
                ("nova", "pago"): "feito",
                ("velha", "pago"): "feito",
            }
            """
        )
        veredicto = self.veredicto()
        self.assertTrue(veredicto.passa, "uma tabela nao e uma excepcao no nucleo")
        self.assertEqual(veredicto.fluxo, 0)
        self.assertEqual(veredicto.conteudo, 2)

    def test_identificador_com_nome_de_vertical_e_conteudo(self) -> None:
        self.escrever_no_nucleo("CREDOR_DA_NOVA = 'KAM-047'\n")
        veredicto = self.veredicto()
        self.assertTrue(veredicto.passa)
        self.assertEqual(veredicto.conteudo, 1)
        self.assertEqual(veredicto.de_classe("conteudo")[0].forma, "identificador")


class TestMutacaoOFluxoMorde(_ComArvore):
    """**Os canarios.** Cada forma de escrever a excepcao tem de dar vermelho.

    Nao e uma lista exaustiva das formas possiveis — nenhuma lista o e —, e e o
    limite honesto deste verificador: ele apanha a comparacao, o `match`, o
    teste e o `startswith`. Uma excepcao escrita por uma via que nao esteja
    aqui passa, e isso esta dito em `docs/reuse-metric.md` §4.
    """

    def _exige_vermelho(self, forma_esperada: str) -> None:
        veredicto = self.veredicto()
        self.assertFalse(
            veredicto.passa,
            "o nucleo decide por nome de vertical e o verificador nao viu",
        )
        self.assertGreaterEqual(veredicto.fluxo, 1)
        self.assertIn(forma_esperada, {o.forma for o in veredicto.de_classe("fluxo")})

    def test_igualdade(self) -> None:
        self.escrever_no_nucleo(
            """
            def correr(estado):
                if estado["vertical"] == "nova":
                    return "caminho proprio"
                return "normal"
            """
        )
        self._exige_vermelho("comparacao")

    def test_pertenca_a_um_literal(self) -> None:
        self.escrever_no_nucleo(
            """
            def correr(estado):
                if estado["vertical"] in ("nova", "velha"):
                    return 1
                return 0
            """
        )
        self._exige_vermelho("comparacao")

    def test_match(self) -> None:
        self.escrever_no_nucleo(
            """
            def correr(estado):
                match estado["vertical"]:
                    case "nova":
                        return 1
                    case _:
                        return 0
            """
        )
        self._exige_vermelho("match")

    def test_subcadeia_num_teste(self) -> None:
        """`if "nova" in texto:` nao e um `Compare` com o literal a esquerda."""
        self.escrever_no_nucleo(
            """
            def correr(texto):
                if "nova" in texto:
                    return 1
                return 0
            """
        )
        self._exige_vermelho("comparacao")

    def test_startswith(self) -> None:
        """Uma comparacao escrita como chamada continua a ser uma comparacao."""
        self.escrever_no_nucleo(
            """
            def correr(estado):
                if estado["vertical"].startswith("nova"):
                    return 1
                return 0
            """
        )
        self._exige_vermelho("comparacao")

    def test_expressao_condicional(self) -> None:
        self.escrever_no_nucleo(
            """
            def correr(estado):
                return 1 if estado["vertical"] == "velha" else 0
            """
        )
        self._exige_vermelho("comparacao")

    def test_a_excepcao_num_ficheiro_EXCLUIDO_nao_reprova(self) -> None:
        """O criterio exclui testes e `verticais/`, e a exclusao tem de valer.

        O par positivo do canario: se um `if == "nova"` dentro da propria
        vertical reprovasse, o criterio (d) era impossivel de satisfazer.
        """
        alvo = self.raiz / "pkg" / "verticais" / "nova" / "grafo.py"
        alvo.write_text(
            'from ..velha.n import partilhado_um\nif "nova" == "nova":\n    _ = 1\n',
            encoding="utf-8",
        )
        self.assertTrue(self.veredicto().passa)


class TestDeclaracaoMalformada(_ComArvore):
    def test_sem_mapa_nucleo_levanta(self) -> None:
        with self.assertRaises(DeclaracaoDoNucleoInvalidaError):
            verificar(self.raiz, {"caminho": {}})

    def test_ficheiro_de_nucleo_que_nao_compila_levanta(self) -> None:
        """Saltar era dar `fluxo = 0` por ausencia; subir cru dava *traceback*.

        Medido ao escrever o canario de mutacao: a injeccao caiu com
        indentacao errada e o verificador rebentou com um `IndentationError`
        em vez de dizer qual era o ficheiro.
        """
        self.escrever_no_nucleo("def f(:\n")
        with self.assertRaises(DeclaracaoDoNucleoInvalidaError) as erro:
            self.veredicto()
        self.assertIn("pkg/nucleo.py", str(erro.exception))

    def test_nomes_vazios_levanta(self) -> None:
        """Uma lista de nomes vazia dava zero achados sobre qualquer arvore."""
        with self.assertRaises(DeclaracaoDoNucleoInvalidaError):
            verificar(self.raiz, {"nucleo": {"padroes": ["pkg/*"], "nomes": []}})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
