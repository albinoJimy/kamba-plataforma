"""A garantia «so leitura», e o que ela garante exactamente (KAM-137).

A decisao do `docs/adr/ADR-L003-verificacao-do-ruleset.md` e «so deteccao»: a
credencial e de leitura e o modulo nao escreve. Essa frase aparece em varios
documentos, e uma frase dessas so vale o que a maquina a sustentar.

**A primeira versao desta guarda nao a sustentava.** Procurava `POST`, `PUT`,
`PATCH` e `DELETE` em literais de cadeia, em maiusculas, e dois dos tres testes
liam **so** o `api.py`. A revisao adversarial injectou cinco caminhos de escrita
e os cinco passaram:

1. `urllib.request.Request(url, data=corpo)` — `POST` implicito, sem a palavra;
2. `os.system("curl -d ...")`;
3. `verbo = "PU" + "T"` — a concatenacao esconde a palavra do varrimento;
4. `subprocess.run(["gh", "api", p, "-X", "post"])` — em minusculas;
5. `gh ruleset rm` no `cli.py`, que nem sequer era lido.

Os cinco estao aqui como canarios: cada um tem de ser apanhado, e **pela sua
regra**. Sem isso, a guarda voltava a poder enfraquecer em silencio.

## O que esta guarda garante, e o que nao garante

Garante que, em **todos** os modulos da raiz do pacote, nao ha: literal de
cadeia com `post`/`put`/`patch`/`delete` (sem distincao de maiusculas, com as
concatenacoes de constantes dobradas antes de comparar), `--method` nem `-X`,
chamada a `os.system`/`os.popen`/`os.exec*`/`os.spawn*`, chamada a `subprocess`
que nao seja um `run` com lista literal comecada por `gh`, `api`, nem
`urlopen`/`Request` com corpo.

**Nao garante a ausencia de caminhos de escrita.** E uma lista de padroes, e um
autor determinado contorna-a — com um nome de funcao construido em tempo de
execucao, por exemplo. E por isso que a afirmacao nos documentos e «nenhum
caminho de escrita que estes padroes apanhem» e nao «nao ha caminho de
escrita». Dizer a segunda seria prometer uma garantia de maquina que nao
existe, que e pior do que nao a prometer.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from ruleset_check import api

PACOTE = Path(api.__file__).resolve().parent

#: Os verbos de escrita, em qualquer caixa.
_VERBOS = re.compile(r"(?i)\b(post|put|patch|delete)\b")

#: `--method` em qualquer caixa, e o `-X` do curl/gh como token isolado.
_FLAGS = re.compile(r"(?i)--method\b|(?<![\w-])-x(?![\w-])")

#: Funcoes do `os` que executam um comando do sistema.
_OS_PROIBIDO = ("system", "popen", "execv", "execve", "execl", "execlp", "execvp",
                "spawnl", "spawnv", "spawnve", "posix_spawn")

#: Modulos de rede que o pacote nao usa e nao pode comecar a usar sem se dizer.
_MODULOS_PROIBIDOS = ("requests", "httpx", "http.client", "aiohttp", "urllib3")


def _nome_do_alvo(no: ast.AST) -> str:
    """`a.b.c(...)` -> `a.b.c`; `f(...)` -> `f`."""
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute):
        return f"{_nome_do_alvo(no.value)}.{no.attr}"
    return ""


def _dobrar(no: ast.AST) -> str | None:
    """O valor de uma expressao que seja uma cadeia constante, somas incluidas."""
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value
    if isinstance(no, ast.BinOp) and isinstance(no.op, ast.Add):
        esquerda, direita = _dobrar(no.left), _dobrar(no.right)
        if esquerda is not None and direita is not None:
            return esquerda + direita
    if isinstance(no, ast.JoinedStr):
        partes = []
        for peca in no.values:
            if isinstance(peca, ast.Constant) and isinstance(peca.value, str):
                partes.append(peca.value)
        return "".join(partes)
    return None


def _ids_dos_docstrings(arvore: ast.AST) -> set[int]:
    """Os docstrings nomeiam os verbos **para dizer que nao estao la**."""
    ids = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            corpo = getattr(no, "body", [])
            if (corpo and isinstance(corpo[0], ast.Expr)
                    and isinstance(corpo[0].value, ast.Constant)
                    and isinstance(corpo[0].value.value, str)):
                ids.add(id(corpo[0].value))
    return ids


def achados_de_escrita(texto: str, nome: str = "<memoria>") -> list[str]:
    """Os caminhos de escrita que esta guarda reconhece, cada um com a sua regra."""
    arvore = ast.parse(texto)
    docstrings = _ids_dos_docstrings(arvore)
    achados: list[str] = []

    # --- literais ----------------------------------------------------------
    for no in ast.walk(arvore):
        if isinstance(no, ast.Constant) and isinstance(no.value, str) and id(no) in docstrings:
            continue
        valor = None
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            valor = no.value
        elif isinstance(no, (ast.BinOp, ast.JoinedStr)):
            valor = _dobrar(no)
        if valor is None:
            continue
        if _VERBOS.search(valor):
            achados.append(f"verbo-de-escrita: {nome}:{getattr(no, 'lineno', 0)}: {valor!r}")
        if _FLAGS.search(valor):
            achados.append(f"flag-de-metodo: {nome}:{getattr(no, 'lineno', 0)}: {valor!r}")

    # --- importacoes -------------------------------------------------------
    for no in ast.walk(arvore):
        nomes: list[str] = []
        if isinstance(no, ast.Import):
            nomes = [a.name for a in no.names]
        elif isinstance(no, ast.ImportFrom):
            nomes = [no.module or ""]
        for modulo in nomes:
            if any(modulo == p or modulo.startswith(p + ".") for p in _MODULOS_PROIBIDOS):
                achados.append(f"modulo-de-rede: {nome}:{no.lineno}: {modulo}")

    # --- chamadas ----------------------------------------------------------
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        alvo = _nome_do_alvo(no.func)
        linha = no.lineno
        curto = alvo.rsplit(".", 1)[-1]

        if alvo.startswith("os.") and curto in _OS_PROIBIDO:
            achados.append(f"comando-do-sistema: {nome}:{linha}: {alvo}")

        if alvo.startswith("subprocess."):
            if curto != "run":
                achados.append(f"subprocesso-nao-run: {nome}:{linha}: {alvo}")
            elif not _e_gh_api(no):
                achados.append(f"subprocesso-fora-de-gh-api: {nome}:{linha}: {alvo}")

        if curto in ("Request", "urlopen"):
            com_corpo = any(k.arg == "data" and not _e_none(k.value) for k in no.keywords)
            if com_corpo or len(no.args) >= 2:
                achados.append(f"pedido-com-corpo: {nome}:{linha}: {alvo}")

    return sorted(achados)


def _e_none(no: ast.AST) -> bool:
    return isinstance(no, ast.Constant) and no.value is None


def _e_gh_api(chamada: ast.Call) -> bool:
    """`subprocess.run([...])` com uma lista literal que comeca em `gh`, `api`."""
    if not chamada.args or not isinstance(chamada.args[0], ast.List):
        return False
    itens = chamada.args[0].elts
    if len(itens) < 2:
        return False
    primeiros = [_dobrar(itens[0]), _dobrar(itens[1])]
    return primeiros == ["gh", "api"]


class TestOPacoteNaoEscreve(unittest.TestCase):
    """Sobre **todos** os modulos da raiz do pacote, e nao so o `api.py`."""

    def ficheiros(self) -> list[Path]:
        return sorted(PACOTE.glob("*.py"))

    def test_ha_mais_do_que_um_modulo_a_varrer(self) -> None:
        """A guarda antiga lia um ficheiro; se voltar a ler um, isto fica vermelho."""
        self.assertGreaterEqual(len(self.ficheiros()), 5)

    def test_nenhum_modulo_tem_caminho_de_escrita(self) -> None:
        for ficheiro in self.ficheiros():
            with self.subTest(modulo=ficheiro.name):
                self.assertEqual(
                    achados_de_escrita(ficheiro.read_text(encoding="utf-8"), ficheiro.name),
                    [],
                )

    def test_o_unico_metodo_pedido_e_get(self) -> None:
        texto = (PACOTE / "api.py").read_text(encoding="utf-8")
        self.assertIn('method="GET"', texto)

    def test_o_gh_e_chamado_so_com_o_subcomando_api(self) -> None:
        for ficheiro in self.ficheiros():
            texto = ficheiro.read_text(encoding="utf-8")
            with self.subTest(modulo=ficheiro.name):
                self.assertEqual(set(re.findall(r'\["gh",\s*"([a-z-]+)"', texto)) - {"api"}, set())


class TestAGuardaMorde(unittest.TestCase):
    """Os cinco caminhos que a revisao adversarial injectou, e mais alguns.

    Cada um tem de ser apanhado **pela sua regra**: uma guarda que apanhasse
    tudo por `verbo-de-escrita` nao provava nada sobre as outras.
    """

    def regras(self, fonte: str) -> list[str]:
        return sorted({a.split(":")[0] for a in achados_de_escrita(fonte)})

    def test_pedido_com_corpo_por_palavra_chave(self) -> None:
        fonte = "import urllib.request\np = urllib.request.Request(url, data=corpo)\n"
        self.assertEqual(self.regras(fonte), ["pedido-com-corpo"])

    def test_pedido_com_corpo_por_posicao(self) -> None:
        self.assertEqual(
            self.regras("r = urlopen(endereco, corpo)\n"), ["pedido-com-corpo"]
        )

    def test_urlopen_com_timeout_nao_e_corpo(self) -> None:
        """O caminho legitimo do proprio modulo nao pode dar falso vermelho."""
        self.assertEqual(achados_de_escrita("r = urlopen(pedido, timeout=30)\n"), [])

    def test_comando_do_sistema(self) -> None:
        """O `curl -d` nao traz o verbo nem o `-X`: e a regra do `os.system` que morde.

        Vale dizer porque nao se acrescentou `-d` a lista de flags: o
        `os.system` ja fecha qualquer comando do sistema, e um `-d` solto numa
        cadeia qualquer era um falso vermelho a espera de acontecer.
        """
        fonte = 'import os\nos.system("curl -d @corpo.json https://api.github.com/x")\n'
        self.assertEqual(self.regras(fonte), ["comando-do-sistema"])

    def test_comando_do_sistema_sem_flag(self) -> None:
        self.assertEqual(
            self.regras('import os\nos.popen("algo")\n'), ["comando-do-sistema"]
        )

    def test_verbo_escondido_numa_concatenacao(self) -> None:
        self.assertEqual(self.regras('verbo = "PU" + "T"\n'), ["verbo-de-escrita"])

    def test_verbo_escondido_num_f_string(self) -> None:
        self.assertEqual(self.regras('v = f"PAT{x}CH"\nw = f"DELETE {x}"\n'),
                         ["verbo-de-escrita"])

    def test_flag_x_em_minusculas(self) -> None:
        fonte = 'import subprocess\nsubprocess.run(["gh", "api", p, "-X", "post"])\n'
        self.assertEqual(self.regras(fonte), ["flag-de-metodo", "verbo-de-escrita"])

    def test_gh_com_outro_subcomando(self) -> None:
        fonte = 'import subprocess\nsubprocess.run(["gh", "ruleset", "rm", i])\n'
        self.assertEqual(self.regras(fonte), ["subprocesso-fora-de-gh-api"])

    def test_subprocesso_que_nao_e_run(self) -> None:
        fonte = 'import subprocess\nsubprocess.Popen(["gh", "api", p])\n'
        self.assertEqual(self.regras(fonte), ["subprocesso-nao-run"])

    def test_subprocesso_com_cadeia_em_vez_de_lista(self) -> None:
        fonte = 'import subprocess\nsubprocess.run("gh api " + p, shell=True)\n'
        self.assertEqual(self.regras(fonte), ["subprocesso-fora-de-gh-api"])

    def test_modulo_de_rede_novo(self) -> None:
        self.assertEqual(self.regras("import requests\n"), ["modulo-de-rede"])
        self.assertEqual(self.regras("from http.client import HTTPSConnection\n"),
                         ["modulo-de-rede"])

    def test_metodo_por_palavra_chave(self) -> None:
        self.assertEqual(
            self.regras('r = Request(u, method="PUT")\n'), ["verbo-de-escrita"]
        )

    def test_flag_longa_do_gh(self) -> None:
        fonte = 'import subprocess\nsubprocess.run(["gh", "api", p, "--method", "x"])\n'
        self.assertEqual(self.regras(fonte), ["flag-de-metodo"])

    def test_o_caminho_legitimo_do_pacote_passa(self) -> None:
        """Controlo positivo: sem ele, uma guarda que recusasse tudo «passava»."""
        fonte = (
            "import subprocess\n"
            'r = subprocess.run(["gh", "api", caminho], capture_output=True)\n'
            'p = urllib.request.Request(u, method="GET", headers=h)\n'
            "with urlopen(p, timeout=30) as resposta:\n    pass\n"
        )
        self.assertEqual(achados_de_escrita(fonte), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
