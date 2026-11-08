"""A CLI do `backup_lint`, e o ensaio que prende o funil (KAM-079).

    TestOFunilEUmSo    a guarda atravessa os dois formatos de saida?
    TestComandos       os codigos de saida e o conteudo de cada comando
    TestCanario        o canario corre e morde sobre a arvore real
"""

from __future__ import annotations

import ast
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from backup_lint import canario, cli, lint

RAIZ = Path(__file__).resolve().parents[3]


def _correr(argv: list[str]) -> tuple[int, str, str]:
    saida, erro = io.StringIO(), io.StringIO()
    with redirect_stdout(saida), redirect_stderr(erro):
        codigo = cli.main(["--root", str(RAIZ), *argv])
    return codigo, saida.getvalue(), erro.getvalue()


class TestOFunilEUmSo(unittest.TestCase):
    """**O ensaio mais importante desta suite.**

    Uma guarda que vive num dos dois caminhos de saida nao e uma guarda. Foi
    medido neste repositorio noutro ticket: uma proteccao de privacidade estava
    dentro do caminho de JSON, e o caminho de texto — que era o de **omissao**
    do CLI — nao corria guarda nenhuma.

    Aqui ha dois comandos que escrevem (`restauro` e `debito`) e dois formatos
    (texto e `--json`). Sao quatro caminhos, e a guarda tem de ser a mesma nos
    quatro.

    **Quem prende a propriedade e o comportamento, e nao a arvore sintactica.**
    A primeira versao desta docstring dizia «prende-se estruturalmente», e a
    revisao adversarial mediu que isso sobrevendia o que os ensaios de `ast`
    dao: acrescentou um segundo funil chamado por referencia indirecta
    (`getattr(politica, "pode_" + "enviar")`), contornou o gate por inteiro —
    `--classe real --destino repo1` passou a sair com **0** em vez de 1 — e os
    **tres** ensaios de arvore sintactica passaram todos, porque contam
    `ast.Call` com `func.attr == "pode_enviar"` e um `getattr` nao e um
    `ast.Attribute` com aquele nome.

    O unico ensaio que apanhou a fuga foi o de comportamento
    (`test_os_dois_formatos_dizem_a_mesma_coisa_sobre_o_envio`), e e por isso
    que e ele a garantia. Os ensaios de `ast` ficam como verificacao **barata e
    secundaria** da forma: dizem que a guarda tem um nome e um sitio, o que faz
    a proxima pessoa escrever no sitio certo. Nao dizem que nao ha outra.
    """

    def _arvore(self) -> ast.Module:
        caminho = Path(cli.__file__)
        return ast.parse(caminho.read_text(encoding="utf-8"))

    def test_ha_exactamente_uma_chamada_ao_pode_enviar(self) -> None:
        chamadas = [
            no
            for no in ast.walk(self._arvore())
            if isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "pode_enviar"
        ]
        self.assertEqual(
            len(chamadas),
            1,
            "a guarda duplicou-se. Duas chamadas divergem, e a que divergir "
            "deixa um dos caminhos de saida sem guarda — que foi exactamente o "
            "defeito medido noutro ticket",
        )

    def test_a_unica_chamada_esta_no_decidir(self) -> None:
        for no in ast.walk(self._arvore()):
            if isinstance(no, ast.FunctionDef) and no.name == "_decidir":
                chamadas = [
                    sub
                    for sub in ast.walk(no)
                    if isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "pode_enviar"
                ]
                self.assertEqual(len(chamadas), 1)
                return
        self.fail("`_decidir` desapareceu: o funil deixou de ter nome")

    def _comandos_que_escrevem(self) -> set[str]:
        """Os `_comando_*` que chamam o `_imprimir`, **descobertos** na arvore.

        Descoberto e nao escrito a mao: a lista a mao era `("_comando_restauro",
        "_comando_debito")`, e um comando novo que escrevesse resultado ficava
        fora de todos os ensaios desta classe.
        """
        nomes = set()
        for no in ast.walk(self._arvore()):
            if not isinstance(no, ast.FunctionDef):
                continue
            if not no.name.startswith("_comando_"):
                continue
            for sub in ast.walk(no):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "_imprimir"
                ):
                    nomes.add(no.name)
                    break
        return nomes

    def test_os_comandos_com_guarda_sao_exactamente_os_que_escrevem(self) -> None:
        """**A emenda do furo que a revisao nomeou**, e e por igualdade.

        De um lado, os comandos que o analisador equipa com `--classe` (a
        guarda); do outro, os `_comando_*` que chamam o `_imprimir` (os que
        escrevem resultado). Os dois conjuntos tem de ser o **mesmo**: um
        comando que escreva sem guarda reprova aqui, e uma guarda num comando
        que nao escreve tambem — porque significa que alguem a pos no sitio
        errado.
        """
        analisador = cli.construir_analisador()
        com_guarda = set()
        for accao in analisador._subparsers._group_actions:  # noqa: SLF001
            for nome, sub in accao.choices.items():
                if any("--classe" in a.option_strings for a in sub._actions):  # noqa: SLF001
                    com_guarda.add(f"_comando_{nome}")
        self.assertEqual(
            com_guarda,
            self._comandos_que_escrevem(),
            "um comando que escreve resultado sem guarda, ou ao contrario",
        )
        self.assertTrue(com_guarda, "zero comandos nao e um zero util")

    def test_todo_o_comando_que_escreve_passa_pelo_decidir(self) -> None:
        """Nenhum escreve sem ter decidido, e decide pelo nome do funil."""
        for nome in sorted(self._comandos_que_escrevem()):
            with self.subTest(funcao=nome):
                for no in ast.walk(self._arvore()):
                    if isinstance(no, ast.FunctionDef) and no.name == nome:
                        decisoes = {
                            sub.func.id
                            for sub in ast.walk(no)
                            if isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Name)
                            and sub.func.id.startswith("_decidir")
                        }
                        self.assertEqual(
                            decisoes,
                            {"_decidir"},
                            f"{nome} decide por outra funcao que nao o funil",
                        )
                        break

    def test_ha_exactamente_uma_funcao_que_escreve(self) -> None:
        """O `print` vive no `_imprimir` e nos resumos dos dois *lints*.

        Os comandos que **decidem** nao imprimem por si: com duas funcoes de
        impressao, uma mensagem acrescentada a um formato faltaria no outro — e
        e assim que uma guarda fica a faltar num dos caminhos.

        A lista de nomes vem do `_comandos_que_escrevem`, descoberta na arvore.
        """
        for nome in sorted(self._comandos_que_escrevem()):
            with self.subTest(funcao=nome):
                for no in ast.walk(self._arvore()):
                    if isinstance(no, ast.FunctionDef) and no.name == nome:
                        prints = [
                            sub
                            for sub in ast.walk(no)
                            if isinstance(sub, ast.Call)
                            and isinstance(sub.func, ast.Name)
                            and sub.func.id == "print"
                        ]
                        # Os unicos `print` tolerados sao os de erro de leitura,
                        # que sao `file=sys.stderr` e nao saida de resultado.
                        for chamada in prints:
                            self.assertTrue(
                                any(p.arg == "file" for p in chamada.keywords),
                                f"{nome} imprime resultado fora do `_imprimir`",
                            )
                        break
                else:  # pragma: no cover
                    self.fail(f"{nome} desapareceu")

    def test_a_omissao_da_classe_e_sintetica_nos_dois_comandos(self) -> None:
        """A omissao de um comando de backup nao pode ser «trata isto como dados
        reais». E a omissao do compose de producao
        (`KAMBA_DATA_CLASS: ${KAMBA_DATA_CLASS:-synthetic}`)."""
        for argv in (["restauro"], ["debito", "--bytes", "1", "--segundos", "1"]):
            with self.subTest(argv=argv[0]):
                codigo, saida, _ = _correr([*argv, "--json"])
                self.assertEqual(codigo, 0)
                carga = json.loads(saida)
                self.assertTrue(carga["envio"]["permitido"])
                self.assertIn("sintetic", carga["envio"]["razao"])

    def test_os_dois_formatos_dizem_a_mesma_coisa_sobre_o_envio(self) -> None:
        """Nao e redundancia: e o ensaio que apanharia a guarda a existir num
        formato e nao no outro."""
        for argv in (["restauro"], ["debito", "--bytes", "1", "--segundos", "1"]):
            with self.subTest(argv=argv[0]):
                pedido = [*argv, "--classe", "real", "--destino", "repo1"]
                codigo_texto, texto, _ = _correr(pedido)
                codigo_json, bruto, _ = _correr([*pedido, "--json"])
                self.assertEqual(codigo_texto, 1, "dados reais sem apd_ref")
                self.assertEqual(codigo_json, 1)
                carga = json.loads(bruto)
                self.assertFalse(carga["envio"]["permitido"])
                self.assertIn("apd_ref", texto)
                self.assertIn("apd_ref", carga["envio"]["razao"])


class TestComandos(unittest.TestCase):
    def test_lint_sobre_a_arvore_real_sai_zero(self) -> None:
        codigo, saida, _ = _correr(["lint"])
        self.assertEqual(codigo, 0)
        self.assertIn("0 achados", saida)
        self.assertIn("CONFIGURADO", saida, "os que nunca correram dizem-se")

    def test_restauro_sem_ultimo_esta_devido(self) -> None:
        codigo, saida, _ = _correr(
            ["restauro", "--agora", "2026-11-07T00:00:00Z", "--json"]
        )
        self.assertEqual(codigo, 0)
        carga = json.loads(saida)
        self.assertTrue(carga["devido"])
        self.assertEqual(carga["agendador"], "ausente")
        self.assertTrue(carga["credor_do_agendador"])

    def test_o_codigo_de_saida_nao_e_o_do_predicado(self) -> None:
        """Um restauro em divida nao e um erro da ferramenta: e a resposta que se
        pediu. O que **e** saida 1 e o envio recusado, porque isso e a guarda a
        morder."""
        devido, saida, _ = _correr(
            [
                "restauro",
                "--agora",
                "2026-11-07T00:00:00Z",
                "--ultimo",
                "2026-01-01T00:00:00Z",
                "--json",
            ]
        )
        self.assertEqual(devido, 0)
        self.assertTrue(json.loads(saida)["devido"])

    def test_um_instante_sem_fuso_sai_dois(self) -> None:
        """Saida 2 e «nao se consegue medir», distinta de 1 («ha achado»)."""
        codigo, _, erro = _correr(["restauro", "--agora", "2026-11-07T00:00:00"])
        self.assertEqual(codigo, 2)
        self.assertIn("ingenuo", erro)

    def test_o_debito_compara_com_o_orcamento_do_doc_09(self) -> None:
        # 20 GB em 1600 s = 100 Mbps, que e o orcamento. 1600 s contra os 1800
        # orcamentados divergem -11,1%, dentro dos 20%.
        codigo, saida, _ = _correr(
            ["debito", "--bytes", "20000000000", "--segundos", "1600", "--json"]
        )
        self.assertEqual(codigo, 0)
        carga = json.loads(saida)
        self.assertAlmostEqual(carga["debito_mbps"], 100.0, places=1)
        self.assertFalse(carga["orcamento_a_corrigir"])

    def test_um_debito_muito_fora_pede_correccao_do_orcamento(self) -> None:
        codigo, saida, _ = _correr(
            ["debito", "--bytes", "20000000000", "--segundos", "5400", "--json"]
        )
        self.assertEqual(codigo, 0)
        carga = json.loads(saida)
        self.assertTrue(carga["orcamento_a_corrigir"])
        self.assertGreater(carga["divergencia_pct"], 20)

    def test_zero_segundos_sai_dois(self) -> None:
        codigo, _, erro = _correr(["debito", "--bytes", "1", "--segundos", "0"])
        self.assertEqual(codigo, 2)
        self.assertIn("medicao que nao se fez", erro)


class TestSaidas(unittest.TestCase):
    """Os tres codigos de saida, cada um pelo seu caminho.

    A distincao entre **1** e **2** e a do `canon_lint` e do `obs_lint`, e e a
    que importa: uma configuracao que nao se le nao pode parecer uma
    configuracao conforme. Sem estes casos, o caminho do 2 existia e nunca
    tinha corrido.
    """

    def _copia(self) -> Path:
        import shutil
        import tempfile

        pasta = Path(tempfile.mkdtemp(prefix="backup-lint-cli-"))
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        canario._copiar(RAIZ, pasta)
        return pasta

    def _correr_em(self, raiz: Path, argv: list[str]) -> tuple[int, str, str]:
        saida, erro = io.StringIO(), io.StringIO()
        with redirect_stdout(saida), redirect_stderr(erro):
            codigo = cli.main(["--root", str(raiz), *argv])
        return codigo, saida.getvalue(), erro.getvalue()

    def test_uma_arvore_com_defeito_sai_um_e_imprime_o_achado(self) -> None:
        pasta = self._copia()
        caminho = pasta / lint.PGBACKREST
        caminho.write_text(
            caminho.read_text(encoding="utf-8").replace(
                "repo1-cipher-type=aes-256-cbc", "repo1-cipher-type=aes-128-cbc"
            ),
            encoding="utf-8",
            newline="\n",
        )
        codigo, _, erro = self._correr_em(pasta, ["lint"])
        self.assertEqual(codigo, 1)
        self.assertIn("cifra-fraca", erro)

    def test_sem_cobertura_os_tres_comandos_saem_dois(self) -> None:
        """E **dois** e nao um: a ferramenta nao mediu, e dizer «0 achados»
        sobre uma arvore que nao se leu era o pior resultado possivel."""
        for argv in (
            ["lint"],
            ["restauro"],
            ["debito", "--bytes", "1", "--segundos", "1"],
        ):
            with self.subTest(argv=argv[0]):
                pasta = self._copia()
                (pasta / lint.COBERTURA).unlink()
                codigo, _, erro = self._correr_em(pasta, argv)
                self.assertEqual(codigo, 2)
                self.assertIn("cobertura.yaml", erro)

    def test_o_canario_sobre_uma_arvore_suja_sai_um(self) -> None:
        pasta = self._copia()
        caminho = pasta / lint.COBERTURA
        caminho.write_text(
            caminho.read_text(encoding="utf-8").replace(
                "  limite_segundos: 300", "  limite_segundos: 600"
            ),
            encoding="utf-8",
            newline="\n",
        )
        codigo, saida, erro = self._correr_em(pasta, ["canario"])
        self.assertEqual(codigo, 1)
        self.assertIn("nao esta limpa", erro)
        self.assertIn("0 de", saida, "e diz quantos morderam: zero")


class TestCanario(unittest.TestCase):
    def test_todos_os_casos_mordem_sobre_a_arvore_real(self) -> None:
        falhas, numeros = canario.correr(RAIZ)
        self.assertEqual(falhas, [])
        self.assertEqual(numeros["morderam"], numeros["casos"])
        self.assertEqual(numeros["regras_exercitadas"], len(lint.REGRAS))

    def test_toda_a_regra_tem_caso(self) -> None:
        """O terceiro fecho: uma regra nova sem canario falha o canario, em vez
        de ficar em silencio a espera de que alguem repare."""
        nomes = {regra.__name__ for regra in lint.REGRAS}
        self.assertEqual(nomes, set(canario.MINIMO_POR_REGRA))

    def test_a_mutacao_que_nao_se_aplica_e_falha_e_nao_verde(self) -> None:
        """A armadilha desta forma: a arvore muda, o texto que a mutacao
        trocava desaparece, e o caso passa a verde por nao ter medido nada."""
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            copia = canario.Copia(Path(pasta))
            with self.assertRaises(canario.NaoSeAplica):
                copia.trocar(lint.COBERTURA, "qualquer", "coisa")

    def test_o_canario_recusa_uma_arvore_ja_suja(self) -> None:
        """Sem isto, um caso que «da vermelho» podia estar a dar vermelho pelo
        que ja la estava."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            destino = Path(pasta)
            canario._copiar(RAIZ, destino)
            caminho = destino / lint.PGBACKREST
            caminho.write_text(
                caminho.read_text(encoding="utf-8").replace(
                    "repo1-cipher-type=aes-256-cbc", "repo1-cipher-type=aes-128-cbc"
                ),
                encoding="utf-8",
                newline="\n",
            )
            falhas, numeros = canario.correr(destino)
            self.assertTrue(falhas)
            self.assertIn("nao esta limpa", falhas[0])
            self.assertEqual(numeros["morderam"], 0)
            del shutil


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
