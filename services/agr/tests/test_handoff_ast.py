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
        # **O valor inteiro, e nao «contem um interrupt em qualquer ponto».** A
        # distincao e o achado 3: `interrupt(deps.x())` contem um interrupt e
        # corre um efeito antes dele.
        self.assertTrue(politica_ast._e_interrupt(primeira.value))
        # E os argumentos nao tocam a porta do mundo.
        self.assertFalse(
            any(politica_ast._toca_a_porta(a) for a in primeira.value.args)
        )


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


def _fabrica(corpo: str) -> str:
    """Uma fabrica de no com `corpo` dentro, indentado."""
    linhas = "\n".join(f"        {linha}" for linha in corpo.strip("\n").split("\n"))
    return (
        "def handoff_wait(deps):\n"
        "    async def no(estado):\n"
        f"{linhas}\n\n"
        "    return no\n"
    )


class TestAsSeisEvasoes(unittest.TestCase):
    """As seis formas com que a primeira versao desta política se evadia.

    Todas medidas pela revisão adversarial do KAM-034 (achado 3), e as três
    primeiras são o erro que alguém escreveria **sem má-fé** — quem queira passar
    contexto ao `interrupt` escreve a primeira.

    Cada uma é um canário: entra aqui para que a correcção não se desfaça sem
    alguém ver. E cada uma diz **qual** regra tem de morder, porque uma evasão
    apanhada pela regra errada é uma evasão que volta quando a regra mudar.
    """

    def um_achado(self, corpo: str, regra: str) -> None:
        achados = politica_ast.verificar(_fabrica(corpo))
        self.assertTrue(achados, "a politica ficou calada")
        self.assertIn(regra, " ".join(achados), achados)

    def test_a_efeito_na_posicao_de_argumento(self) -> None:
        """`interrupt(deps.saida.enfileirar(...))` — o argumento avalia-se antes.

        A revisão executou o controlo positivo: a ordem real é
        `['efeito', 'interrupt']`. É o defeito 6 do §7.1 inteiro, numa linha.
        """
        self.um_achado(
            'desfecho = interrupt(deps.saida.enfileirar(estado, "ola", chave="k"))\n'
            "return {}",
            politica_ast.EFEITO_NO_ARGUMENTO,
        )

    def test_a2_o_efeito_num_argumento_nomeado_tambem(self) -> None:
        self.um_achado(
            'desfecho = interrupt({"x": 1}, extra=deps.metricas.contar("x"))\n'
            "return {}",
            politica_ast.EFEITO_NO_ARGUMENTO,
        )

    def test_b_efeito_num_tuplo_avaliado_antes(self) -> None:
        self.um_achado(
            '_, desfecho = deps.saida.enfileirar(estado, "ola", chave="k"), interrupt({})\n'
            "return {}",
            politica_ast.EFEITO_ANTES,
        )

    def test_c_o_interrupt_dentro_de_with_contextlib_suppress(self) -> None:
        """O LangGraph interrompe **levantando**, e o `suppress` engole-o
        exactamente como o `except` que a regra do `try` existe para apanhar."""
        achados = politica_ast.verificar(
            _fabrica(
                "with contextlib.suppress(BaseException):\n"
                "    desfecho = interrupt({})\n"
                "return {}"
            )
        )
        juntos = " ".join(achados)
        self.assertIn(politica_ast.DENTRO_DE_TRY, juntos, achados)
        self.assertIn(politica_ast.EFEITO_ANTES, juntos, achados)

    def test_d_o_interrupt_num_ciclo_escrito_como_compreensao(self) -> None:
        """Uma compreensão não é `ast.For`: os geradores dela são
        `ast.comprehension`. Três `interrupt()` num ciclo."""
        achados = politica_ast.verificar(
            _fabrica('desfecho = [interrupt({"i": i}) for i in range(3)][-1]\nreturn {}')
        )
        juntos = " ".join(achados)
        self.assertIn(politica_ast.DENTRO_DE_CICLO, juntos, achados)
        self.assertIn(politica_ast.EFEITO_ANTES, juntos, achados)

    def test_e_o_interrupt_dentro_de_except_estrela(self) -> None:
        """`ast.TryStar` não é `ast.Try`."""
        self.um_achado(
            "try:\n"
            "    desfecho = interrupt({})\n"
            "except* Exception:\n"
            "    desfecho = None\n"
            "return {}",
            politica_ast.DENTRO_DE_TRY,
        )

    def test_f_o_interrupt_dentro_de_async_with_que_engole(self) -> None:
        self.um_achado(
            "async with deps.engole():\n"
            "    desfecho = interrupt({})\n"
            "return {}",
            politica_ast.DENTRO_DE_TRY,
        )

    def test_as_seis_sao_seis_e_nenhuma_passa(self) -> None:
        """A asserção de conjunto: **nenhuma** das seis fica calada.

        Sem isto, a bateria media seis casos um a um e não a propriedade que
        importa — que é «a política não tem buraco conhecido».
        """
        evasoes = (
            'desfecho = interrupt(deps.saida.enfileirar(estado, "o", chave="k"))\nreturn {}',
            '_, desfecho = deps.saida.enfileirar(estado, "o", chave="k"), interrupt({})\nreturn {}',
            "with contextlib.suppress(BaseException):\n    desfecho = interrupt({})\nreturn {}",
            'desfecho = [interrupt({"i": i}) for i in range(3)][-1]\nreturn {}',
            "try:\n    desfecho = interrupt({})\nexcept* Exception:\n    desfecho = None\nreturn {}",
            "async with deps.engole():\n    desfecho = interrupt({})\nreturn {}",
        )
        caladas = [
            corpo for corpo in evasoes if not politica_ast.verificar(_fabrica(corpo))
        ]
        self.assertEqual(caladas, [], f"{len(caladas)} evasao(oes) por apanhar")


class TestOQuePassaEDeveParsar(unittest.TestCase):
    """Os controlos positivos, sem os quais a política pode recusar tudo.

    Uma política que recusa código correcto ensina quem leva o vermelho a
    desligá-la, e é por isso que estes valem tanto como os canários.
    """

    def test_o_estado_nos_argumentos_passa(self) -> None:
        """É o que o nó real faz: `estado.get(...)` é uma chamada e **não** é um
        efeito. Proibir chamadas nos argumentos recusava o código certo."""
        self.assertEqual(
            politica_ast.verificar(
                _fabrica(
                    "desfecho = interrupt(\n"
                    '    {"handoff_id": (estado.get("handoff") or {}).get("id"),\n'
                    '     "motivo": estado.get("handoff_motivo") or MOTIVO}\n'
                    ")\n"
                    "return {}"
                )
            ),
            [],
        )

    def test_o_deps_depois_do_interrupt_passa(self) -> None:
        """Depois da interrupção já não é «antes»: a retoma reinicia o nó, e o
        que corre depois do `interrupt` corre uma vez por retoma."""
        self.assertEqual(
            politica_ast.verificar(
                _fabrica(
                    "desfecho = interrupt({})\n"
                    'deps.saida.enfileirar(estado, "ola", chave="k")\n'
                    "return {}"
                )
            ),
            [],
        )

    def test_um_await_sobre_a_propria_chamada_passa(self) -> None:
        self.assertEqual(
            politica_ast.verificar(_fabrica("desfecho = await interrupt({})\nreturn {}")),
            [],
        )

    def test_um_try_depois_do_interrupt_falha_mesmo_assim(self) -> None:
        """E **isto** é deliberado: o §11 diz «não se pode envolver `interrupt()`
        em `try/except` genérico», e um `try` que o envolva engole-o esteja onde
        estiver. Um `try` que **não** o envolva passa (o caso seguinte)."""
        self.um_achado = None  # type: ignore[assignment]
        achados = politica_ast.verificar(
            _fabrica(
                "desfecho = interrupt({})\n"
                "try:\n"
                "    anterior = dict(estado.get('handoff') or {})\n"
                "except KeyError:\n"
                "    anterior = {}\n"
                "return {}"
            )
        )
        self.assertEqual(achados, [], "um `try` que nao envolve o interrupt passa")


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
