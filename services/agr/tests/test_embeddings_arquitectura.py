"""Nenhum pedido ao fornecedor de embeddings sem passar pela porta (KAM-063).

O teste de contrato do bloco: «falha se o cliente de embeddings for importado
fora do modulo». Le a **fonte** e nao importa nada, pela razao do
`politica_llm_ast.py` (KAM-112): uma barreira que so morde em execucao nao
apanha o caminho que ninguem exercitou.

## As quatro regras

1. `gateway_fora_do_adaptador` — um `.embeber(...)` fora do
   `kamba_agr/tls/embeddings.py`. O `ClienteDeLlm.embeber` tem a porta do
   gateway, mas nao a do nucleo, nem o tecto de 1,5 s, nem o detector do
   criterio 4: chama-lo directamente era a pesquisa a ir ao fornecedor sem
   nenhuma das tres.
2. `adaptador_fora_do_cliente` — um `FornecedorDoGateway(...)` que nao seja
   argumento directo de um `ClienteDeEmbeddings(...)`. E a construcao que poe a
   porta a frente de cada chamada; um adaptador guardado numa variavel e um
   adaptador que alguem chama sem ela.
3. `fornecedor_antes_da_porta` — no `ClienteDeEmbeddings`, o fornecedor e
   chamado antes do `self.autorizar(...)`, ou referido num metodo que nao seja
   o construtor, a porta ou a chamada.
4. `rota_de_embeddings_fora_do_cliente` — o literal `/embeddings` fora do
   `kamba_agr/llm/cliente.py`: um segundo cliente HTTP do gateway.

Cada regra tem um canario abaixo, uma fonte que **tem** de ser recusada.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

RAIZ = pathlib.Path(__file__).resolve().parents[3]
ARVORES = (RAIZ / "services" / "agr" / "src", RAIZ / "libs" / "py-core" / "src")

ADAPTADOR = "kamba_agr/tls/embeddings.py"
CLIENTE_HTTP = "kamba_agr/llm/cliente.py"
NUCLEO = "kamba_core/idx/embeddings.py"

#: Os metodos do `ClienteDeEmbeddings` que podem tocar no fornecedor. O
#: `aceita` le o filtro local dele (`FornecedorDoGateway.aceita`, que so corre o
#: detector de PII) e nunca o chama: o que sai para fora passa pelo `vectores`.
METODOS_COM_FORNECEDOR = frozenset({"__init__", "aceita", "autorizar", "vectores"})


def _nome(no: ast.AST) -> str | None:
    if isinstance(no, ast.Name):
        return no.id
    if isinstance(no, ast.Attribute):
        return no.attr
    return None


def _e_self_fornecedor(no: ast.AST) -> bool:
    return (
        isinstance(no, ast.Attribute)
        and no.attr == "_fornecedor"
        and isinstance(no.value, ast.Name)
        and no.value.id == "self"
    )


def achados(relativo: str, fonte: str) -> list[tuple[str, int]]:
    """As violacoes de `fonte`, com o caminho relativo a raiz do pacote."""
    arvore = ast.parse(fonte)
    saida: list[tuple[str, int]] = []
    argumentos_do_cliente: set[int] = set()
    # As *docstrings* falam da rota e nao a chamam: ficam fora da regra 4.
    documentacao = {
        id(no.body[0].value)
        for no in ast.walk(arvore)
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and no.body
        and isinstance(no.body[0], ast.Expr)
        and isinstance(no.body[0].value, ast.Constant)
    }
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and _nome(no.func) == "ClienteDeEmbeddings":
            for argumento in (*no.args, *(k.value for k in no.keywords)):
                argumentos_do_cliente.add(id(argumento))
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call):
            if (
                isinstance(no.func, ast.Attribute)
                and no.func.attr == "embeber"
                and relativo != ADAPTADOR
            ):
                saida.append(("gateway_fora_do_adaptador", no.lineno))
            if _nome(no.func) == "FornecedorDoGateway" and id(no) not in argumentos_do_cliente:
                saida.append(("adaptador_fora_do_cliente", no.lineno))
        if (
            isinstance(no, ast.Constant)
            and isinstance(no.value, str)
            and "/embeddings" in no.value
            and id(no) not in documentacao
            and relativo != CLIENTE_HTTP
        ):
            saida.append(("rota_de_embeddings_fora_do_cliente", no.lineno))
        if isinstance(no, ast.ClassDef) and no.name == "ClienteDeEmbeddings":
            saida.extend(_ordem_no_cliente(no))
    return saida


def _ordem_no_cliente(classe: ast.ClassDef) -> list[tuple[str, int]]:
    saida: list[tuple[str, int]] = []
    for metodo in classe.body:
        if not isinstance(metodo, ast.FunctionDef):
            continue
        referencias = [n.lineno for n in ast.walk(metodo) if _e_self_fornecedor(n)]
        if not referencias:
            continue
        if metodo.name not in METODOS_COM_FORNECEDOR:
            saida.append(("fornecedor_antes_da_porta", referencias[0]))
            continue
        if metodo.name != "vectores":
            continue
        portas = [
            n.lineno
            for n in ast.walk(metodo)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "autorizar"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "self"
        ]
        if not portas or min(referencias) < min(portas):
            saida.append(("fornecedor_antes_da_porta", min(referencias)))
        # A porta dentro de um `try` pode ser engolida (achado 11 da revisao):
        # a ordem das linhas fica certa e a recusa nao chega a quem chama.
        for no in ast.walk(metodo):
            if isinstance(no, ast.Try) and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "autorizar"
                for n in ast.walk(no)
            ):
                saida.append(("fornecedor_antes_da_porta", no.lineno))
    return saida


def _fontes() -> list[tuple[str, str]]:
    fontes = []
    for arvore in ARVORES:
        for caminho in sorted(arvore.rglob("*.py")):
            relativo = caminho.relative_to(arvore).as_posix()
            fontes.append((relativo, caminho.read_text(encoding="utf-8")))
    return fontes


class TestArquitectura(unittest.TestCase):
    def test_o_repositorio_esta_conforme(self) -> None:
        violacoes = [
            (relativo, regra, linha)
            for relativo, fonte in _fontes()
            for regra, linha in achados(relativo, fonte)
        ]
        self.assertEqual(violacoes, [])

    def test_as_tres_pecas_existem_e_foram_lidas(self) -> None:
        """Um varrimento que nao ve os ficheiros fica conforme por nao ler nada."""
        lidos = dict(_fontes())
        for relativo in (ADAPTADOR, CLIENTE_HTTP, NUCLEO):
            with self.subTest(ficheiro=relativo):
                self.assertIn(relativo, lidos)
        self.assertIn("class ClienteDeEmbeddings", lidos[NUCLEO])
        self.assertIn(".embeber(", lidos[ADAPTADOR])
        self.assertIn("FornecedorDoGateway(", lidos[ADAPTADOR])


class TestCanarios(unittest.TestCase):
    """Cada regra recusa a fonte que a quebra."""

    def regras(self, relativo: str, fonte: str) -> set[str]:
        return {regra for regra, _ in achados(relativo, fonte)}

    def test_gateway_chamado_fora_do_adaptador(self) -> None:
        fonte = "def f(cliente, t, c):\n    return cliente.embeber('embed', t, c)\n"
        self.assertIn("gateway_fora_do_adaptador", self.regras("kamba_agr/tls/idx.py", fonte))
        self.assertNotIn("gateway_fora_do_adaptador", self.regras(ADAPTADOR, fonte))

    def test_adaptador_guardado_numa_variavel(self) -> None:
        fonte = "f = FornecedorDoGateway(cliente)\nc = ClienteDeEmbeddings(porta, f)\n"
        self.assertIn("adaptador_fora_do_cliente", self.regras("kamba_agr/__main__.py", fonte))
        boa = "c = ClienteDeEmbeddings(porta, FornecedorDoGateway(cliente))\n"
        self.assertEqual(self.regras(ADAPTADOR, boa), set())

    def test_fornecedor_chamado_antes_da_porta(self) -> None:
        fonte = (
            "class ClienteDeEmbeddings:\n"
            "    def vectores(self, t, x):\n"
            "        r = self._fornecedor(t, x, 1)\n"
            "        self.autorizar(t)\n"
            "        return r\n"
        )
        self.assertIn("fornecedor_antes_da_porta", self.regras(NUCLEO, fonte))

    def test_fornecedor_sem_porta_nenhuma(self) -> None:
        fonte = (
            "class ClienteDeEmbeddings:\n"
            "    def vectores(self, t, x):\n"
            "        return self._fornecedor(t, x, 1)\n"
        )
        self.assertIn("fornecedor_antes_da_porta", self.regras(NUCLEO, fonte))

    def test_porta_engolida_por_um_try(self) -> None:
        fonte = (
            "class ClienteDeEmbeddings:\n"
            "    def vectores(self, t, x):\n"
            "        try:\n"
            "            self.autorizar(t)\n"
            "        except EmbeddingNegado:\n"
            "            pass\n"
            "        return self._fornecedor(t, x, 1)\n"
        )
        self.assertIn("fornecedor_antes_da_porta", self.regras(NUCLEO, fonte))

    def test_fornecedor_num_metodo_novo(self) -> None:
        fonte = (
            "class ClienteDeEmbeddings:\n"
            "    def atalho(self, t, x):\n"
            "        return self._fornecedor(t, x, 1)\n"
        )
        self.assertIn("fornecedor_antes_da_porta", self.regras(NUCLEO, fonte))

    def test_segundo_cliente_http_do_gateway(self) -> None:
        fonte = "import httpx\nhttpx.post(url + '/embeddings', json={})\n"
        self.assertIn(
            "rota_de_embeddings_fora_do_cliente", self.regras("kamba_agr/outro.py", fonte)
        )
        self.assertEqual(self.regras(CLIENTE_HTTP, fonte), set())


if __name__ == "__main__":
    unittest.main()
