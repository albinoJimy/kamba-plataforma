"""O gate 4: classificacao por estrato, leitura de LCOV e aplicacao do limiar.

As ferramentas que impoem os gates tem de ser testadas, e e por isso que
`tools/**` esta no estrato `restante` de `ci/thresholds.yaml`: um `coverage_gate`
sem testes nao protege cobertura nenhuma.
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from coverage_gate import (
    ConfiguracaoInvalida,
    Medicao,
    avaliar,
    base_do_nome,
    ler_limiares,
    ler_lcov,
    linhas_do_ficheiro,
    main,
    universo,
)

ROOT = Path(__file__).resolve().parents[3]

LCOV = """TN:
SF:services/gwy/src/app.ts
DA:1,1
LF:10
LH:8
end_of_record
TN:
SF:tools/lint_refs/scan.py
DA:1,1
LF:100
LH:90
end_of_record
"""


class TestBaseDoNome(unittest.TestCase):
    """O pacote vem do nome do ficheiro, porque os caminhos `SF:` sao relativos."""

    def test_node(self) -> None:
        for nome, esperado in (
            ("node-services-gwy.lcov", "services/gwy"),
            ("node-packages-core-ts.lcov", "packages/core-ts"),
            ("node-libs-py-core.lcov", "libs/py-core"),
        ):
            with self.subTest(nome=nome):
                self.assertEqual(base_do_nome(Path(nome)), esperado)

    def test_python(self) -> None:
        self.assertEqual(base_do_nome(Path("python-tools.lcov")), "tools")

    def test_nome_sem_prefixo(self) -> None:
        self.assertEqual(base_do_nome(Path("qualquer.lcov")), "")


class TestLerLcov(unittest.TestCase):
    def test_le_sf_lf_lh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "python-tools.lcov"
            caminho.write_text(LCOV, encoding="utf-8")
            medicoes = ler_lcov(caminho, ROOT)
        self.assertIn("services/gwy/src/app.ts", medicoes)
        self.assertEqual(medicoes["services/gwy/src/app.ts"].linhas_encontradas, 10)
        self.assertEqual(medicoes["services/gwy/src/app.ts"].linhas_cobertas, 8)

    def test_percentagem(self) -> None:
        self.assertEqual(Medicao("x", 10, 8).percentagem, 80.0)

    def test_ficheiro_sem_linhas_conta_como_coberto(self) -> None:
        """Um ficheiro sem linhas instrumentadas nao e 0%: nao ha nada a medir."""
        self.assertEqual(Medicao("x", 0, 0).percentagem, 100.0)

    def test_caminho_relativo_recebe_o_prefixo_do_pacote(self) -> None:
        """O Node emite `src/app.ts`; sem prefixo nenhum estrato o classifica."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "node-services-gwy.lcov"
            caminho.write_text(
                "SF:src/app.ts\nLF:4\nLH:4\nend_of_record\n", encoding="utf-8"
            )
            medicoes = ler_lcov(caminho, ROOT)
        self.assertIn("services/gwy/src/app.ts", medicoes)

    def test_nome_nu_nao_se_resolve_contra_o_cwd(self) -> None:
        """`Path("cli.py").resolve()` resolvia contra o directorio actual.

        Era por isso que 36 ficheiros de `tools/` ficavam sem estrato: o caminho
        saia como `cli.py`, parecia relativo a raiz, e nunca chegava ao prefixo.
        """
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "python-tools.lcov"
            caminho.write_text(
                "SF:lint_refs/cli.py\nLF:4\nLH:4\nend_of_record\n", encoding="utf-8"
            )
            medicoes = ler_lcov(caminho, ROOT)
        self.assertIn("tools/lint_refs/cli.py", medicoes)


class TestLimiares(unittest.TestCase):
    def setUp(self) -> None:
        self.limiares = ler_limiares(ROOT)

    def test_os_dois_estratos_do_standards(self) -> None:
        nomes = [e.nome for e in self.limiares.estratos]
        self.assertEqual(nomes, ["critico", "restante"])
        self.assertEqual(self.limiares.estratos[0].minimo, 90)
        self.assertEqual(self.limiares.estratos[1].minimo, 75)

    def test_as_ferramentas_estao_classificadas(self) -> None:
        """`tools/**` tem de bater num estrato.

        Sem esta linha, o gate 4 passava com os **dois** estratos vazios.
        """
        estrato = self.limiares.classificar("tools/lint_refs/scan.py")
        self.assertIsNotNone(estrato)
        self.assertEqual(estrato.nome, "restante")

    def test_codigo_de_dinheiro_cai_no_estrato_critico(self) -> None:
        for caminho in (
            "services/com/src/pagamentos/referencia.ts",
            "services/agr/src/toollayer/money.py",
            "libs/py-core/src/tenant_guard/rls.py",
        ):
            with self.subTest(caminho=caminho):
                estrato = self.limiares.classificar(caminho)
                self.assertIsNotNone(estrato, caminho)
                self.assertEqual(estrato.nome, "critico", caminho)

    def test_a_ordem_decide(self) -> None:
        """O primeiro padrao que bate manda.

        `services/*/src/**` tambem apanharia um ficheiro de pagamentos; e o
        estrato `critico` vir primeiro que o impede de cair nos 75%.
        """
        estrato = self.limiares.classificar("services/com/src/pagamentos/x.ts")
        self.assertEqual(estrato.nome, "critico")

    def test_excluidos_sao_estado_proprio(self) -> None:
        """«Excluido» e «sem estrato» sao coisas diferentes.

        O primeiro e uma decisao escrita; o segundo e um ficheiro que escapou ao
        limiar sem ninguem decidir isso.
        """
        for caminho in (
            "packages/core-ts/dist/index.js",
            "services/gwy/tests/healthz.test.ts",
            "tools/lint_refs/tests/test_scan.py",
            "services/gwy/src/server.ts",
        ):
            with self.subTest(caminho=caminho):
                self.assertTrue(self.limiares.esta_excluido(caminho), caminho)

    def test_configuracao_invalida(self) -> None:
        casos = {
            "sem ficheiro": None,
            "sem estratos": "version: 1\nestratos:\n",
            "versao errada": "version: 2\nestratos:\n  - nome: x\n",
            "estrato incompleto": "version: 1\nestratos:\n  - nome: x\n    minimo_linhas: 80\n",
        }
        for nome, conteudo in casos.items():
            with self.subTest(caso=nome), tempfile.TemporaryDirectory() as tmp:
                raiz = Path(tmp)
                if conteudo is not None:
                    (raiz / "ci").mkdir()
                    (raiz / "ci" / "thresholds.yaml").write_text(conteudo, encoding="utf-8")
                with self.assertRaises(ConfiguracaoInvalida):
                    ler_limiares(raiz)


class TestAvaliar(unittest.TestCase):
    def setUp(self) -> None:
        self.limiares = ler_limiares(ROOT)

    def test_acima_do_limiar_passa(self) -> None:
        medicoes = {"tools/x.py": Medicao("tools/x.py", 100, 80)}
        achados, _ = avaliar(medicoes, self.limiares)
        self.assertEqual(achados, [])

    def test_abaixo_do_limiar_falha(self) -> None:
        medicoes = {"tools/x.py": Medicao("tools/x.py", 100, 70)}
        achados, _ = avaliar(medicoes, self.limiares)
        self.assertTrue(achados)
        self.assertIn("70%", achados[0])
        self.assertIn("minimo 75%", achados[0])

    def test_trunca_e_nao_arredonda(self) -> None:
        """O ticket diz «descer 1 ponto abaixo falha»: 74,9% nao e 75%."""
        medicoes = {"tools/x.py": Medicao("tools/x.py", 1000, 749)}
        achados, _ = avaliar(medicoes, self.limiares)
        self.assertTrue(achados, "74,9% tem de falhar")

        medicoes = {"tools/x.py": Medicao("tools/x.py", 1000, 750)}
        achados, _ = avaliar(medicoes, self.limiares)
        self.assertEqual(achados, [], "75,0% passa")

    def test_ficheiro_sem_estrato_falha(self) -> None:
        """Escapar ao limiar em silencio e o defeito que isto fecha."""
        medicoes = {"inventado/sitio.py": Medicao("inventado/sitio.py", 10, 0)}
        achados, resumo = avaliar(medicoes, self.limiares)
        self.assertTrue(achados)
        self.assertIn("nao classificados", achados[0])
        self.assertEqual(resumo["nao_classificados"], ["inventado/sitio.py"])

    def test_excluido_nao_falha_nem_conta(self) -> None:
        medicoes = {
            "packages/core-ts/dist/index.js": Medicao("packages/core-ts/dist/index.js", 10, 0)
        }
        achados, resumo = avaliar(medicoes, self.limiares)
        self.assertEqual(achados, [])
        self.assertEqual(resumo["excluidos"], 1)

    def test_estrato_vazio_nao_falha(self) -> None:
        """Hoje o `critico` esta vazio: nao ha codigo de dinheiro no repositorio."""
        medicoes = {"tools/x.py": Medicao("tools/x.py", 100, 100)}
        achados, resumo = avaliar(medicoes, self.limiares)
        self.assertEqual(achados, [])
        self.assertEqual(resumo["por_estrato"]["critico"]["ficheiros"], 0)

    def test_um_ficheiro_a_zero_baixa_o_agregado(self) -> None:
        """A propriedade do KAM-132: o denominador cresce com codigo sem testes.

        Antes do KAM-132 um ficheiro TypeScript sem nenhum teste nao chegava a
        este dicionario — o V8 so reporta o que os testes carregam —, pelo que a
        percentagem do estrato nao se movia por mais TypeScript sem testes que
        houvesse. Aqui mede-se a consequencia: o mesmo numerador, com o ficheiro
        a 0% no denominador, da uma percentagem menor.
        """
        base = {"tools/a.py": Medicao("tools/a.py", 100, 80)}
        _, resumo = avaliar(dict(base), self.limiares)
        antes = resumo["por_estrato"]["restante"]

        com_zero = dict(base)
        com_zero["packages/p/src/novo.ts"] = Medicao("packages/p/src/novo.ts", 50, 0)
        achados, resumo = avaliar(com_zero, self.limiares)
        depois = resumo["por_estrato"]["restante"]

        self.assertEqual(antes["cobertas"], depois["cobertas"], "o numerador e o mesmo")
        self.assertEqual(depois["encontradas"], antes["encontradas"] + 50)
        self.assertEqual(antes["cobertas"] * 100 // antes["encontradas"], 80)
        self.assertEqual(depois["cobertas"] * 100 // depois["encontradas"], 53)
        self.assertTrue(achados, "53% esta abaixo dos 75% e tem de falhar")


#: Um `ci/thresholds.yaml` minimo com as tres formas que importam: um estrato
#: com um padrao que atravessa barras, um estrato generico, e exclusoes.
LIMIARES_DE_PROVA = (
    "version: 1\n"
    "estratos:\n"
    "  - nome: critico\n"
    "    minimo_linhas: 90\n"
    "    razao: isolamento\n"
    "    padroes:\n"
    '      - "*/identity/*"\n'
    "  - nome: restante\n"
    "    minimo_linhas: 75\n"
    "    razao: o resto\n"
    "    padroes:\n"
    '      - "packages/*/src/**"\n'
    "excluidos:\n"
    '  - "**/*.test.ts"\n'
    '  - "**/dist/**"\n'
    '  - "packages/p/src/excluido.ts"\n'
)


def arvore_de_prova(raiz: Path) -> None:
    """Uma arvore com um ficheiro de cada caso que o universo tem de decidir."""
    (raiz / "ci").mkdir()
    (raiz / "ci" / "thresholds.yaml").write_text(LIMIARES_DE_PROVA, encoding="utf-8")
    for relativo in (
        "packages/p/src/medido.ts",
        "packages/p/src/sem_teste.ts",
        "packages/p/src/excluido.ts",
        "packages/p/src/identity/chaves.ts",
        "packages/p/src/coisa.test.ts",
        "packages/p/dist/medido.js",
        "packages/p/node_modules/dep/src/index.ts",
        "fora/do/ambito.ts",
        "packages/p/src/notas.md",
        # Fora de `src/`: nenhum estrato o classifica. Nao entra no universo,
        # mas **tem** de falhar o gate se algum teste o carregar.
        "packages/p/fora_do_estrato.ts",
        # As quatro extensoes que a primeira versao deixava fugir.
        "packages/p/src/moderno.mts",
        "packages/p/src/antigo.cts",
        "packages/p/src/vista.tsx",
        "packages/p/src/legado.js",
        # Uma copia por versionar num sitio que o `.gitignore` ignora: o `*` do
        # `fnmatch` atravessa barras, pelo que `*/identity/*` apanharia isto.
        "rascunho/packages/p/src/identity/chaves.ts",
        "tmp/base/packages/p/src/identity/chaves.ts",
        # Uma pasta de ferramenta **dentro** de uma raiz: nao e fonte.
        "packages/p/src/.cache/identity/chaves.ts",
    ):
        caminho = raiz / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text("linha 1\nlinha 2\nlinha 3\n", encoding="utf-8")


class TestUniverso(unittest.TestCase):
    """O universo lido do disco: quem entra na medicao mesmo sem ser carregado."""

    def test_le_o_ambito_e_so_o_ambito(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            arvore_de_prova(raiz)
            lista = universo(raiz, ler_limiares(raiz))
        self.assertEqual(
            lista,
            [
                "packages/p/src/antigo.cts",
                "packages/p/src/identity/chaves.ts",
                "packages/p/src/legado.js",
                "packages/p/src/medido.ts",
                "packages/p/src/moderno.mts",
                "packages/p/src/sem_teste.ts",
                "packages/p/src/vista.tsx",
            ],
        )

    def test_as_outras_extensoes_do_node_nao_fogem(self) -> None:
        """`.mts`, `.cts` e `.tsx` sao TypeScript; `.js` e executado pelo Node.

        A primeira versao deste ficheiro so contava `.ts`, e a revisao
        adversarial mostrou a fuga por execucao: um `fuga.mts` com 50
        declaracoes e sem teste nenhum deixava os tres numeros do estrato
        iguais.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            arvore_de_prova(raiz)
            lista = universo(raiz, ler_limiares(raiz))
        for nome in ("moderno.mts", "antigo.cts", "vista.tsx", "legado.js"):
            self.assertIn(f"packages/p/src/{nome}", lista, nome)

    def test_nao_entra_pelo_que_esta_fora_das_raizes_dos_padroes(self) -> None:
        """O universo procura nas raizes dos `padroes`, nao na arvore toda.

        `*/identity/*` apanha qualquer caminho com esse segmento, porque o `*`
        do `fnmatch` atravessa barras — e a revisao adversarial mediu o custo:
        uma copia de `packages/core-ts/src/` dentro de `tmp/`, que o
        `.gitignore` ignora, levava o estrato `critico` de 94% para 46%.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            arvore_de_prova(raiz)
            copia = raiz / ".claude" / "worktrees" / "agente" / "packages" / "p" / "src"
            (copia / "identity").mkdir(parents=True)
            (copia / "identity" / "chaves.ts").write_text("x\n", encoding="utf-8")
            lista = universo(raiz, ler_limiares(raiz))
        for fora in (
            ".claude/worktrees/agente/packages/p/src/identity/chaves.ts",
            "rascunho/packages/p/src/identity/chaves.ts",
            "tmp/base/packages/p/src/identity/chaves.ts",
            # Esta esta **dentro** de uma raiz, e e a regra das pastas com ponto
            # a cabeca que a tira: uma pasta de ferramenta nao e fonte.
            "packages/p/src/.cache/identity/chaves.ts",
        ):
            self.assertNotIn(fora, lista, fora)
        self.assertEqual(len(lista), 7)

    def test_sem_raiz_literal_e_erro_de_configuracao(self) -> None:
        """Um ficheiro de limiares que nao diz por onde comecar nao mede zero.

        Medir zero ficheiros em silencio e o defeito que este gate existe para
        nao ter.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "thresholds.yaml").write_text(
                "version: 1\n"
                "estratos:\n"
                "  - nome: restante\n"
                "    minimo_linhas: 75\n"
                "    razao: o resto\n"
                "    padroes:\n"
                '      - "*/src/**"\n',
                encoding="utf-8",
            )
            with self.assertRaises(ConfiguracaoInvalida):
                universo(raiz, ler_limiares(raiz))

    def test_linhas_do_ficheiro_e_o_lf_do_node(self) -> None:
        """O `LF` do Node e o numero de linhas, comentarios e vazias incluidos."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "x.ts"
            caminho.write_text("// um\n\nexport const a = 1;\n", encoding="utf-8")
            self.assertEqual(linhas_do_ficheiro(caminho), 3)

    def test_sem_newline_no_fim_conta_a_ultima_linha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "x.ts"
            caminho.write_text("a\nb", encoding="utf-8")
            self.assertEqual(linhas_do_ficheiro(caminho), 2)

    def test_conta_os_terminadores_do_javascript_e_nao_os_do_splitlines(self) -> None:
        """`str.splitlines` divide em `\\x0c`, `\\x0b` e `\\x85`; o Node nao.

        Medido pela revisao adversarial: um ficheiro de cinco linhas com um
        *form feed*, um *vertical tab* e um NEL dentro de literais sai `LF:5` do
        Node e dava **8** pelo `splitlines`.
        """
        texto = (
            'const a = "x\x0cy";\n'
            'const b = "p\x0bq";\n'
            'const c = "m\x85n";\n'
            "const d = 4;\n"
            "const e = 5;\n"
        )
        self.assertEqual(len(texto.splitlines()), 8, "o defeito era este")
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "x.ts"
            caminho.write_text(texto, encoding="utf-8")
            self.assertEqual(linhas_do_ficheiro(caminho), 5)

    def test_crlf_e_um_terminador_e_nao_dois(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "x.ts"
            caminho.write_bytes(b"a\r\nb\r\n")
            self.assertEqual(linhas_do_ficheiro(caminho), 2)

    def test_ficheiro_vazio_nao_tem_linhas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caminho = Path(tmp) / "x.ts"
            caminho.write_text("", encoding="utf-8")
            self.assertEqual(linhas_do_ficheiro(caminho), 0)


class TestInjeccaoPeloMain(unittest.TestCase):
    """O que `main()` faz com um ficheiro do ambito que nenhum relatorio mediu."""

    def _raiz(self, tmp: str) -> Path:
        raiz = Path(tmp)
        (raiz / "ci").mkdir()
        (raiz / "ci" / "thresholds.yaml").write_text(
            LIMIARES_DE_PROVA, encoding="utf-8"
        )
        (raiz / "packages" / "p" / "src").mkdir(parents=True)
        (raiz / "packages" / "p" / "src" / "medido.ts").write_text(
            "a\nb\nc\nd\n", encoding="utf-8"
        )
        # 60 linhas sem teste nenhum, que e o que o gate nunca via.
        (raiz / "packages" / "p" / "src" / "sem_teste.ts").write_text(
            "linha\n" * 60, encoding="utf-8"
        )
        (raiz / "packages" / "p" / "src" / "excluido.ts").write_text(
            "linha\n" * 999, encoding="utf-8"
        )
        lcov = raiz / "medicao.lcov"
        lcov.write_text(
            "SF:packages/p/src/medido.ts\nLF:4\nLH:4\nend_of_record\n", encoding="utf-8"
        )
        return raiz

    def test_o_ficheiro_sem_medicao_entra_a_zero_e_falha_o_estrato(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = self._raiz(tmp)
            codigo = main(["--root", str(raiz), str(raiz / "medicao.lcov")])
        # 4 cobertas em 64 linhas = 6%, abaixo dos 75% do estrato `restante`.
        self.assertEqual(codigo, 1)

    def test_sem_universo_repoe_o_comportamento_antigo(self) -> None:
        """A prova de que a diferenca e a injeccao, e nao outra coisa."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = self._raiz(tmp)
            codigo = main(
                ["--root", str(raiz), "--sem-universo", str(raiz / "medicao.lcov")]
            )
        self.assertEqual(codigo, 0, "antes do KAM-132, 4/4 = 100% e o gate passava")

    def test_quem_entrou_a_zero_sai_pelo_nome(self) -> None:
        """Uma percentagem que desce sem se saber por que ficheiro nao e medicao.

        E a parte que se perde primeiro: injectar e barato, dizer o que se
        injectou e o que torna o numero auditavel por quem o le no CI.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = self._raiz(tmp)
            saida = StringIO()
            with redirect_stdout(saida):
                main(["--root", str(raiz), str(raiz / "medicao.lcov")])
        self.assertIn("packages/p/src/sem_teste.ts", saida.getvalue())
        self.assertIn("sem medicao", saida.getvalue())

    def test_o_excluido_nao_e_injectado(self) -> None:
        """Se o fosse, as 999 linhas de `excluido.ts` afundavam o estrato."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = self._raiz(tmp)
            (raiz / "packages" / "p" / "src" / "sem_teste.ts").unlink()
            codigo = main(["--root", str(raiz), str(raiz / "medicao.lcov")])
        self.assertEqual(codigo, 0)

    def test_um_ts_medido_sem_estrato_falha_o_gate(self) -> None:
        """O critério 7 do ticket, ao nível a que ele se perdeu.

        A bateria tinha isto só sobre `avaliar()` com um caminho `.py`
        sintético, que nunca passa pelo filtro que o `make coverage-node`
        aplica. A revisão adversarial mostrou que, com o **ambito** passado em
        `--test-coverage-include`, um `.ts` sem estrato era retirado do
        relatório e deixava de falhar. Aqui mede-se o que o gate faz quando o
        ficheiro **chega** ao relatório, que é o que agora acontece.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = self._raiz(tmp)
            (raiz / "packages" / "p" / "src" / "sem_teste.ts").unlink()
            lcov = raiz / "com-orfao.lcov"
            lcov.write_text(
                "SF:packages/p/src/medido.ts\nLF:4\nLH:4\nend_of_record\n"
                "SF:packages/p/fora_do_estrato.ts\nLF:9\nLH:9\nend_of_record\n",
                encoding="utf-8",
            )
            (raiz / "packages" / "p" / "fora_do_estrato.ts").write_text(
                "a\n" * 9, encoding="utf-8"
            )
            saida = StringIO()
            with redirect_stdout(saida):
                codigo = main(["--root", str(raiz), str(lcov)])
        self.assertEqual(codigo, 1, "medido e nao classificado tem de falhar o gate")
        self.assertIn("nao classificados", saida.getvalue())
        self.assertIn("packages/p/fora_do_estrato.ts", saida.getvalue())


class TestExclusoesNode(unittest.TestCase):
    """A lista do `--test-coverage-exclude`, derivada do ficheiro de limiares."""

    def test_caminhos_relativos_ao_pacote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            arvore_de_prova(raiz)
            saida = StringIO()
            with redirect_stdout(saida):
                codigo = main(["--root", str(raiz), "--exclusoes-node", "packages/p"])
        self.assertEqual(codigo, 0)
        # `dist/` nao aparece porque nem se percorre: a saida de compilacao nao
        # e codigo de execucao deste repositorio. Os `dist/*.js` dos pacotes do
        # workspace que os testes dos servicos carregam continuam a entrar no
        # relatorio e a ser excluidos na avaliacao, como antes do KAM-132 — sao
        # caminhos `../../packages/...`, que uma exclusao relativa ao pacote nao
        # alcanca, e nao mexem em numero nenhum.
        self.assertEqual(
            saida.getvalue().split(), ["src/coisa.test.ts", "src/excluido.ts"]
        )

    def test_o_que_nenhum_estrato_classifica_nao_e_excluido(self) -> None:
        """E o achado maior da revisao adversarial, em forma de teste.

        Passar o **ambito** em `--test-coverage-include` retirava do relatorio
        o ficheiro que nenhum estrato classifica, e esse tem de chegar ao
        `avaliar()` para falhar o gate. A lista que se passa ao Node e de
        **exclusoes**, e um ficheiro sem estrato nao esta nela.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            arvore_de_prova(raiz)
            saida = StringIO()
            with redirect_stdout(saida):
                main(["--root", str(raiz), "--exclusoes-node", "packages/p"])
        self.assertNotIn("fora_do_estrato.ts", saida.getvalue())

    def test_pacote_sem_ficheiros_no_ambito_e_erro(self) -> None:
        """Um pacote de `PACOTES_NODE` sem nada no ambito e erro de configuracao."""
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            arvore_de_prova(raiz)
            (raiz / "services" / "vazio").mkdir(parents=True)
            codigo = main(["--root", str(raiz), "--exclusoes-node", "services/vazio"])
        self.assertEqual(codigo, 2)

    def test_caminho_com_espaco_e_erro(self) -> None:
        """O `make coverage-node` expande a lista sem aspas.

        Um caminho com espaco partia-se em dois argumentos e o padrao deixava de
        bater, em silencio. Recusa-se onde se ve.
        """
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            arvore_de_prova(raiz)
            (raiz / "packages" / "p" / "src" / "com espaco.test.ts").write_text(
                "a\n", encoding="utf-8"
            )
            codigo = main(["--root", str(raiz), "--exclusoes-node", "packages/p"])
        self.assertEqual(codigo, 2)

    def test_pacote_inexistente_e_erro(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            arvore_de_prova(raiz)
            codigo = main(["--root", str(raiz), "--exclusoes-node", "nao/existe"])
        self.assertEqual(codigo, 2)


class TestAmbitoRealDoRepositorio(unittest.TestCase):
    """O universo sobre o repositorio a serio, nao sobre uma arvore inventada."""

    def setUp(self) -> None:
        self.lista = universo(ROOT, ler_limiares(ROOT))

    def test_tem_os_ficheiros_que_o_node_nao_carregava(self) -> None:
        """Os tres que o gate 4 nunca viu antes do KAM-132.

        Nenhum teste os importa — sao o indice do modulo e a costura do motor de
        armazenamento —, pelo que o V8 nunca os reportava e o denominador do
        gate nao os continha. Entram no universo mesmo que um ticket futuro lhes
        de testes: a lista e o ambito, nao o que esta coberto.
        """
        for caminho in (
            "packages/core-ts/src/identity/index.ts",
            "packages/core-ts/src/storage/index.ts",
            "packages/core-ts/src/storage/motor.ts",
        ):
            self.assertIn(caminho, self.lista)

    def test_nao_tem_os_excluidos(self) -> None:
        """Os `excluidos` valem na injeccao, nao so na avaliacao."""
        for caminho in (
            "services/gwy/src/server.ts",
            "services/com/src/server.ts",
            "packages/core-ts/src/identity/contactos.ts",
        ):
            self.assertNotIn(caminho, self.lista)

    def test_nao_tem_testes_nem_dependencias_nem_compilado(self) -> None:
        for caminho in self.lista:
            self.assertTrue(caminho.endswith(".ts"), caminho)
            for proibido in ("/node_modules/", "/dist/", "/tests/", ".test.ts"):
                self.assertNotIn(proibido, caminho, caminho)

    def test_cada_um_esta_classificado(self) -> None:
        """Um ficheiro do universo sem estrato injectava-se e falhava o gate."""
        limiares = ler_limiares(ROOT)
        for caminho in self.lista:
            self.assertIsNotNone(limiares.classificar(caminho), caminho)


if __name__ == "__main__":
    unittest.main()
