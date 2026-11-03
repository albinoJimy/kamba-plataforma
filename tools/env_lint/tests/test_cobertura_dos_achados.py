"""Nenhum achado sem prova de que morde.

Este ficheiro existe por causa de um buraco encontrado na auto-validação deste
ticket: o canário tem **19** casos e o `lint.py` produz **30** códigos de
achado. Ler «19 de 19 casos a morder» como cobertura total era o erro à espera
de acontecer — e a forma de o fechar não é escrever onze mutações a mais, é
exigir por máquina que **cada código tenha prova em algum sítio**.

A divisão de trabalho, que fica declarada em vez de assumida:

* **canário** — as regras que os critérios de aceitação nomeiam. Provam-se
  contra a árvore **real**, que é a que o gate verifica;
* **testes unitários** — as regras de esquema e de estrutura (uma chave a mais,
  uma secção em falta, uma lista mal formada). Provam-se contra um `Dados`
  construído à mão, porque mutá-las na árvore real exigia uma árvore inválida.

O que este teste impõe é a **união**: um código novo sem prova em nenhum dos
dois lados fica vermelho aqui. Era o único sítio por onde um achado podia
nascer morto sem ninguém notar.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from env_lint import canario

PASTA = Path(__file__).resolve().parent
FONTE = PASTA.parent / "lint.py"

#: O primeiro argumento de cada `Achado(...)` do `lint.py`.
_CODIGO_DE_ACHADO = re.compile(r'Achado\(\s*\n?\s*"([a-z0-9-]+)"')


def _codigos_produzidos() -> set[str]:
    return set(_CODIGO_DE_ACHADO.findall(FONTE.read_text(encoding="utf-8")))


def _codigos_nos_testes() -> set[str]:
    """Os códigos que algum teste afirma, lidos dos próprios ficheiros.

    Lê-se a fonte dos testes e não se instrumenta a execução: o que se quer
    saber é se **existe** um teste que nomeie o código, e um teste que o nomeie
    numa `assertIn` ou numa `assertNotIn` serve as duas direcções.
    """
    encontrados: set[str] = set()
    for ficheiro in PASTA.glob("test_*.py"):
        if ficheiro.name == Path(__file__).name:
            continue
        texto = ficheiro.read_text(encoding="utf-8")
        encontrados |= set(re.findall(r'"([a-z0-9]+(?:-[a-z0-9]+)+)"', texto))
    return encontrados


class TestCoberturaDosAchados(unittest.TestCase):
    def test_o_lint_produz_mais_codigos_do_que_o_canario_cobre(self) -> None:
        # Não é um defeito: é o facto que justifica este ficheiro, e fica
        # medido para que ninguém leia «19 de 19» como cobertura total.
        produzidos = _codigos_produzidos()
        do_canario = {caso.codigo for caso in canario.CASOS}
        self.assertGreater(len(produzidos), len(do_canario))

    def test_todo_o_codigo_tem_prova_no_canario_ou_num_teste(self) -> None:
        produzidos = _codigos_produzidos()
        self.assertGreater(len(produzidos), 0, "a leitura da fonte devolveu zero códigos")
        cobertos = {caso.codigo for caso in canario.CASOS} | _codigos_nos_testes()
        sem_prova = sorted(produzidos - cobertos)
        self.assertEqual(
            sem_prova,
            [],
            "achados que o lint produz e que nenhum canário nem teste exercita: "
            f"{sem_prova}. Um achado sem prova de que morde é um achado que pode "
            "nascer morto.",
        )

    def test_nenhum_caso_de_canario_aponta_para_um_codigo_que_nao_existe(self) -> None:
        # A direcção inversa, e vale tanto como a outra: um caso que espere um
        # código renomeado falharia, mas um caso que espere um código **apagado**
        # também — e este teste diz qual é o problema em vez de deixar a falha
        # aparecer como «a mutação não produziu o achado».
        produzidos = _codigos_produzidos()
        orfaos = sorted({caso.codigo for caso in canario.CASOS} - produzidos)
        self.assertEqual(orfaos, [], f"casos de canário sem código correspondente: {orfaos}")

    def test_o_readme_documenta_todos_os_codigos(self) -> None:
        # O README é a página que alguém lê quando o gate 2 fica vermelho com
        # um código que não conhece. Um código que não esteja lá é um gate que
        # falha sem explicação.
        readme = (PASTA.parent / "README.md").read_text(encoding="utf-8")
        ausentes = sorted(c for c in _codigos_produzidos() if f"`{c}`" not in readme)
        self.assertEqual(ausentes, [], f"códigos não documentados em README.md: {ausentes}")


if __name__ == "__main__":
    unittest.main()
