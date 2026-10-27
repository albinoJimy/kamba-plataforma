"""A politica AST do `handoff_wait` **morde** (KAM-034, criterio 2).

O criterio escreve as tres coisas que o teste tem de reprovar, e esta bateria
prova-as uma a uma com um canario por regra. O que ela **nao** prova com o
primeiro teste e nada: «o repositorio esta conforme» e uma linha que um
`verificar` a devolver `[]` passaria. Os outros medem o contrario.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import politica_ast

NOS = (
    Path(__file__).resolve().parents[3]
    / "services"
    / "agr"
    / "src"
    / "kamba_agr"
    / "verticais"
    / "vendedor"
    / "nos.py"
)

CONFORME = """
def handoff_wait(deps):
    async def no(estado):
        desfecho = interrupt({"handoff_id": estado["handoff"]["id"]})
        return {"handoff": {"status": "resumed", "outcome": desfecho}}

    return no
"""


class TestOCodigoReal(unittest.TestCase):
    def test_o_handoff_wait_do_vendedor_esta_conforme(self) -> None:
        self.assertEqual(politica_ast.verificar(NOS.read_text(encoding="utf-8")), [])

    def test_o_interrupt_e_a_primeira_instrucao_do_no(self) -> None:
        """A assercao directa, para alem do `verificar`.

        O `from langgraph.types import interrupt` esteve dentro desta funcao
        (KAM-031) e subiu para o topo do modulo com este ticket: nao era um
        efeito, era uma instrucao antes do `interrupt`, e deixa-la la obrigava a
        politica a ter uma excepcao.
        """
        import ast

        arvore = ast.parse(NOS.read_text(encoding="utf-8"))
        fabrica = politica_ast._fabrica(arvore, "handoff_wait")
        self.assertIsNotNone(fabrica)
        interno = politica_ast._no_interno(fabrica)
        self.assertIsNotNone(interno)
        primeira = interno.body[0]
        self.assertIsInstance(primeira, ast.Assign)
        self.assertTrue(politica_ast._chama_interrupt(primeira))


class TestCanarios(unittest.TestCase):
    def test_o_conforme_passa(self) -> None:
        """O controlo positivo: sem ele, um `verificar` que achasse sempre algo
        passava os quatro canarios abaixo."""
        self.assertEqual(politica_ast.verificar(CONFORME), [])

    def test_um_efeito_antes_do_interrupt_falha(self) -> None:
        for antes in (
            'deps.saida.enfileirar(estado, "ola", chave="k")',
            "estado[\"handoff\"] = {}",
            "contador = deps.metricas.contar('x')",
            'from langgraph.types import interrupt',
            "pass",
        ):
            with self.subTest(antes=antes[:28]):
                achados = politica_ast.verificar(
                    "def handoff_wait(deps):\n"
                    "    async def no(estado):\n"
                    f"        {antes}\n"
                    "        desfecho = interrupt({})\n"
                    "        return {}\n\n"
                    "    return no\n"
                )
                self.assertEqual(len(achados), 1, achados)
                self.assertIn(politica_ast.EFEITO_ANTES, achados[0])

    def test_o_interrupt_dentro_de_try_falha(self) -> None:
        achados = politica_ast.verificar(
            "def handoff_wait(deps):\n"
            "    async def no(estado):\n"
            "        try:\n"
            "            desfecho = interrupt({})\n"
            "        except Exception:\n"
            "            desfecho = None\n"
            "        return {}\n\n"
            "    return no\n"
        )
        # Dois achados: esta dentro de `try` **e** nao e a primeira instrucao
        # (a primeira e o `try`). As duas sao verdade e as duas se dizem.
        self.assertIn(politica_ast.DENTRO_DE_TRY, " ".join(achados))

    def test_o_interrupt_dentro_de_while_falha(self) -> None:
        achados = politica_ast.verificar(
            "def handoff_wait(deps):\n"
            "    async def no(estado):\n"
            "        while True:\n"
            "            desfecho = interrupt({})\n"
            "            if desfecho:\n"
            "                break\n"
            "        return {}\n\n"
            "    return no\n"
        )
        self.assertIn(politica_ast.DENTRO_DE_CICLO, " ".join(achados))

    def test_o_interrupt_dentro_de_for_tambem_falha(self) -> None:
        """O §11 nomeia o `while`; um `for` tem o mesmo problema de indice."""
        achados = politica_ast.verificar(
            "def handoff_wait(deps):\n"
            "    async def no(estado):\n"
            "        for _ in range(3):\n"
            "            desfecho = interrupt({})\n"
            "        return {}\n\n"
            "    return no\n"
        )
        self.assertIn(politica_ast.DENTRO_DE_CICLO, " ".join(achados))

    def test_um_no_sem_interrupt_falha(self) -> None:
        """A quarta regra, que o criterio nao pede e sem a qual as tres passam
        vazias."""
        achados = politica_ast.verificar(
            "def handoff_wait(deps):\n"
            "    async def no(estado):\n"
            '        return {"handoff": {"status": "resumed"}}\n\n'
            "    return no\n"
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn(politica_ast.SEM_INTERRUPT, achados[0])

    def test_uma_docstring_nao_e_um_efeito(self) -> None:
        """O interpretador nao a executa como efeito, e recusa-la era recusar
        codigo correcto — que e como se ensina alguem a desligar uma politica."""
        achados = politica_ast.verificar(
            "def handoff_wait(deps):\n"
            "    async def no(estado):\n"
            '        """Espera pelo humano."""\n'
            "        desfecho = interrupt({})\n"
            "        return {}\n\n"
            "    return no\n"
        )
        self.assertEqual(achados, [])

    def test_uma_chamada_de_atributo_tambem_conta_como_interrupt(self) -> None:
        """`types.interrupt(...)` e o mesmo `interrupt`, por outro caminho.

        Sem isto, escrever `langgraph.types.interrupt(...)` dava
        `sem_interrupt` sobre um no correcto — e a resposta de quem levasse esse
        vermelho era desligar a politica.
        """
        achados = politica_ast.verificar(
            "def handoff_wait(deps):\n"
            "    async def no(estado):\n"
            "        desfecho = types.interrupt({})\n"
            "        return {}\n\n"
            "    return no\n"
        )
        self.assertEqual(achados, [])

    def test_sem_a_fabrica_ou_sem_o_no_interno_e_achado_e_nao_silencio(self) -> None:
        """Falha fechada: o que a politica nao consegue ler nao passa."""
        for fonte in (
            "def outra_coisa():\n    pass\n",
            "def handoff_wait(deps):\n    return None\n",
        ):
            with self.subTest(fonte=fonte.split("\n")[0]):
                achados = politica_ast.verificar(fonte)
                self.assertEqual(len(achados), 1, achados)
                self.assertIn(politica_ast.SEM_NO, achados[0])

    def test_o_no_interno_resolve_se_pelo_return_e_nao_pelo_nome(self) -> None:
        """Uma politica que dependesse do nome `no` calava-se com um `rename`."""
        achados = politica_ast.verificar(
            "def handoff_wait(deps):\n"
            "    async def espera(estado):\n"
            '        deps.saida.enfileirar(estado, "x", chave="k")\n'
            "        desfecho = interrupt({})\n"
            "        return {}\n\n"
            "    return espera\n"
        )
        self.assertEqual(len(achados), 1, achados)
        self.assertIn(politica_ast.EFEITO_ANTES, achados[0])


class TestManifesto(unittest.TestCase):
    def test_cada_regra_obrigatoria_tem_mensagem_e_um_canario(self) -> None:
        """A forma do `REGRAS_OBRIGATORIAS` do `log_policy`: um manifesto que se
        esvazia dava «0 negativas, tudo verde»."""
        for regra in politica_ast.REGRAS_OBRIGATORIAS:
            with self.subTest(regra=regra):
                self.assertIn(regra, politica_ast.MENSAGENS)
                self.assertTrue(politica_ast.MENSAGENS[regra].strip())
        nomes = {
            nome
            for nome in dir(TestCanarios)
            if nome.startswith("test_") and "falha" in nome
        }
        self.assertGreaterEqual(len(nomes), len(politica_ast.REGRAS_OBRIGATORIAS))


if __name__ == "__main__":
    unittest.main()
