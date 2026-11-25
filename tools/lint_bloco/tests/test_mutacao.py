"""O inventario do `mutacao.py` contra a arvore que ele muta — KAM-258.

    TestMutacoesAplicam         cada `velho` esta uma vez no ficheiro alvo, e
                                em codigo, nao num comentario nem num texto
    TestVarreduraSemOInventario as copias da varredura nao levam este ensaio
    TestPisoNasSuperficies      cada piso diz o mesmo no `lint.py`, no
                                `mutacao.py` e no §4 de `docs/lint-bloco.md`

**Porque e que isto e um ensaio e nao uma corrida do `mutacao.py`.** A
varredura copia a arvore vinte vezes e corre a suite em cada copia: minutos,
e fora do caminho dos PRs. Mas o defeito que se repetiu nao precisa dela. Um
literal de mutacao que ficou atras do `lint.py` da «NAO APLICOU» antes de
correr seja o que for — e uma comparacao de texto, e mede-se em milissegundos.
Aconteceu pelo menos sete vezes (KAM-108, KAM-210, KAM-207, KAM-216, KAM-227
com o KAM-230, KAM-237 e KAM-127, este na `main` em `fd5e5d1a` e acertado pelo
KAM-246), e de cada vez so quem correu a varredura a mao o viu.

**O que fica de fora**, e e do `mutacao.py`: se uma mutacao que aplica e
apanhada pelos ensaios. Isso so a varredura responde.
"""

from __future__ import annotations

import io
import re
import shutil
import tempfile
import tokenize
import unittest
from pathlib import Path

from lint_bloco import lint, mutacao

RAIZ = Path(__file__).resolve().parents[3]
PACOTE = RAIZ / "tools" / "lint_bloco"
NOTA = RAIZ / "docs" / "lint-bloco.md"

#: O piso numa linha de codigo: `MINIMO_DE_BLOCOS_MEDIDOS = 97`.
_PISO_EM_CODIGO = re.compile(r"^(MINIMO_[A-Z_]+) = (\d+)$")
#: O piso na prosa do §4: `` `MINIMO_DE_BLOCOS_MEDIDOS` (**97**) ``.
_PISO_NA_NOTA = re.compile(r"`(MINIMO_[A-Z_]+)` \(\**(\d+)\**\)")


def _pisos_do_lint() -> dict[str, int]:
    """As constantes `MINIMO_*` do `lint.py`, lidas do modulo e nao de uma lista."""
    return {nome: valor for nome, valor in vars(lint).items()
            if nome.startswith("MINIMO_") and type(valor) is int}


def _texto_ou_comentario(texto: str) -> list[tuple[int, int]]:
    """Os intervalos `[inicio, fim)` de cada `STRING` e `COMMENT` do ficheiro."""
    inicios = [0]
    for linha in texto.splitlines(keepends=True):
        inicios.append(inicios[-1] + len(linha))
    intervalos = []
    for tok in tokenize.generate_tokens(io.StringIO(texto).readline):
        if tok.type in (tokenize.STRING, tokenize.COMMENT):
            (l0, c0), (l1, c1) = tok.start, tok.end
            intervalos.append((inicios[l0 - 1] + c0, inicios[l1 - 1] + c1))
    return intervalos


def _seccao_4(texto: str) -> str:
    inicio = texto.find("\n## 4.")
    fim = texto.find("\n## 5.", inicio)
    if inicio == -1 or fim == -1:
        raise AssertionError(
            "docs/lint-bloco.md: nao encontrei o §4 entre `## 4.` e `## 5.`")
    return texto[inicio:fim]


class TestMutacoesAplicam(unittest.TestCase):
    def test_cada_velho_esta_uma_vez_no_seu_ficheiro(self) -> None:
        """O «NAO APLICOU» da varredura, antes de a correr.

        **Uma vez, e nao «pelo menos uma».** O `replace(velho, novo, 1)` muta a
        primeira ocorrencia: com duas, uma copia num docstring ou outro ciclo
        com o mesmo texto mais acima bastava para a mutacao mudar de alvo, ou
        ficar muda, com este ensaio verde.
        """
        for nome, ficheiro, velho, novo in mutacao.MUTACOES:
            with self.subTest(mutacao=nome):
                alvo = PACOTE / ficheiro
                self.assertTrue(alvo.is_file(), f"{ficheiro} nao existe")
                self.assertEqual(
                    alvo.read_text(encoding="utf-8").count(velho), 1,
                    f"o `velho` de «{nome}» tem de estar uma vez em {ficheiro}")
                self.assertNotEqual(velho, novo)

    def test_o_velho_esta_em_codigo(self) -> None:
        """Num comentario ou num docstring a mutacao nao muda comportamento."""
        for nome, ficheiro, velho, _ in mutacao.MUTACOES:
            texto = (PACOTE / ficheiro).read_text(encoding="utf-8")
            posicao = texto.find(velho)
            if posicao == -1:
                continue  # o ensaio de cima ja o diz
            with self.subTest(mutacao=nome):
                dentro = [(a, b) for a, b in _texto_ou_comentario(texto)
                          if a <= posicao < b]
                self.assertEqual(dentro, [],
                                 f"«{nome}» casa num comentario ou num texto "
                                 f"de {ficheiro}")


class TestVarreduraSemOInventario(unittest.TestCase):
    def test_a_copia_da_varredura_nao_leva_este_ensaio(self) -> None:
        """Numa copia mutada o `velho` foi substituido; este ensaio matava tudo.

        Medido: com ele nas copias, as duas `SOBREVIVENTES_ESPERADAS` passaram
        a «morta», e as outras dezoito morriam por ele e nao pelos ensaios de
        comportamento. Faz-se a copia de verdade, e nao se le a constante.
        """
        destino = Path(tempfile.mkdtemp(prefix="lint-bloco-copia-"))
        self.addCleanup(shutil.rmtree, destino, ignore_errors=True)
        mutacao._copiar(destino)
        testes = destino / "tools" / "lint_bloco" / "tests"
        self.assertTrue((testes / "test_lint.py").is_file())
        self.assertFalse((testes / Path(__file__).name).exists())


class TestPisoNasSuperficies(unittest.TestCase):
    def test_o_lint_py_tem_pisos(self) -> None:
        """Sem isto, um `_pisos_do_lint` vazio deixava os dois de baixo verdes."""
        self.assertIn("MINIMO_DE_BLOCOS_MEDIDOS", _pisos_do_lint())
        self.assertIn("MINIMO_DE_BLOCOS", _pisos_do_lint())

    def test_o_mutacao_py_diz_cada_piso_do_lint_py(self) -> None:
        vistos: dict[str, list[int]] = {}
        for _, ficheiro, velho, _ in mutacao.MUTACOES:
            casado = _PISO_EM_CODIGO.match(velho)
            if ficheiro == "lint.py" and casado:
                vistos.setdefault(casado.group(1), []).append(int(casado.group(2)))
        pisos = _pisos_do_lint()
        self.assertEqual(sorted(vistos), sorted(pisos),
                         "cada piso do lint.py tem de ter a sua mutacao")
        for nome, valores in vistos.items():
            with self.subTest(piso=nome):
                self.assertEqual(set(valores), {pisos[nome]},
                                 f"mutacao.py diz {nome} = {valores}")

    def test_o_paragrafo_4_da_nota_diz_cada_piso_do_lint_py(self) -> None:
        seccao = _seccao_4(NOTA.read_text(encoding="utf-8"))
        vistos: dict[str, list[int]] = {}
        for nome, valor in _PISO_NA_NOTA.findall(seccao):
            vistos.setdefault(nome, []).append(int(valor))
        pisos = _pisos_do_lint()
        self.assertEqual(sorted(vistos), sorted(pisos),
                         "o §4 tem de dizer cada piso do lint.py na forma "
                         "`NOME` (**N**)")
        for nome, valores in vistos.items():
            with self.subTest(piso=nome):
                self.assertEqual(set(valores), {pisos[nome]},
                                 f"o §4 diz {nome} = {valores}")


if __name__ == "__main__":
    unittest.main()
