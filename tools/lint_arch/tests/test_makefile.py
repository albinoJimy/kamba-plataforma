"""Invariantes do Makefile que, quando se quebram, quebram em silencio.

Nao se corre o `make` aqui (a maquina de execucao pode nao o ter). Verifica-se o
que uma leitura distraida deixa passar e que so aparece quando o alvo e
finalmente executado numa maquina com a toolchain toda — que foi exactamente o
que aconteceu com as duas verificacoes de versao do `make doctor`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from coverage_gate import base_do_nome, ler_limiares, universo

ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = ROOT / "Makefile"

# Tabulacao e salto de linha nomeados. Este ficheiro fala de receitas de make,
# que sao definidas por tabulacoes, e ja foi reescrito por script uma vez: uma
# barra invertida colapsada deixa o caractere real dentro das aspas, e o
# ficheiro deixa de compilar sem que se veja porque.
TABULACAO = chr(9)
SALTO = chr(10)


def _e_comentario(linha: str) -> bool:
    """Comentarios de receita (`@#` ou `#`) nao chegam a shell."""
    return linha.lstrip("\t").lstrip("@").startswith("#")


class TestReceitas(unittest.TestCase):
    def setUp(self) -> None:
        self.linhas = MAKEFILE.read_text(encoding="utf-8").split("\n")

    def test_receitas_usam_tab(self) -> None:
        """Uma receita indentada com espacos da "missing separator"."""
        for numero, linha in enumerate(self.linhas, start=1):
            if re.match(r"^ +@?(python|pnpm|node|git|docker|echo|rm|find|corepack)", linha):
                self.fail(
                    f"linha {numero}: receita indentada com espacos: {linha[:60]!r}"
                )

    def test_sem_continuacao_dentro_de_aspas_simples(self) -> None:
        r"""Uma barra de continuacao dentro de `'...'` chega literal ao interpretador.

        A shell nao consome a barra dentro de aspas simples, pelo que o `node -e`
        ou o `python -c` recebem um `\` e morrem com erro de sintaxe. As duas
        verificacoes de versao do `make doctor` estiveram assim e **nunca
        correram**: o alvo falhava antes, no `command -v`, e ninguem deu por isso.
        """
        for numero, linha in enumerate(self.linhas, start=1):
            if not linha.startswith("\t") or _e_comentario(linha):
                continue
            if not linha.rstrip().endswith("\\"):
                continue
            if linha.count("'") % 2 == 1:
                self.fail(
                    f"linha {numero}: continuacao dentro de aspas simples — escreva "
                    f"a receita numa linha. {linha[:70]!r}"
                )

    def test_expansao_de_shell_esta_escapada(self) -> None:
        """`${v}` numa receita e expansao do **make**, nao da shell.

        O make substitui-a antes de a shell ver a linha, pelo que chega vazia. O
        `make doctor` imprimia `node  ok`, sem versao, por causa disto. Precisa
        de `$${v}`.
        """
        padrao = re.compile(r"(?<!\$)\$\{[A-Za-z_][A-Za-z0-9_]*\}")
        for numero, linha in enumerate(self.linhas, start=1):
            if not linha.startswith("\t") or _e_comentario(linha):
                continue
            achado = padrao.search(linha)
            if achado:
                self.fail(
                    f"linha {numero}: {achado.group()} e expansao do make e chega "
                    f"vazia a shell; use $${achado.group()}. {linha[:60]!r}"
                )

    def test_sem_barra_literal_fora_das_receitas(self) -> None:
        r"""Nenhuma linha de declaracao tem a cadeia `\n` em vez de mudar de linha.

        Aconteceu ao editar o `.PHONY` por script: ficou `queue-cli \n        clean`
        numa so linha, e o `\n` passou a ser um alvo com esse nome.

        Verifica-se **fora** das receitas, de proposito: uma receita pode ter um
        `\n` legitimo dentro de um formato de `printf` ou de `awk`, como o alvo
        `help` tem.
        """
        for numero, linha in enumerate(self.linhas, start=1):
            if linha.startswith("\t"):
                continue
            self.assertNotIn(
                "\\n",
                linha,
                f"linha {numero} tem a cadeia '\\n' literal fora de uma receita: "
                f"{linha[:70]!r}",
            )


def _receita(linhas: list[str], alvo: str) -> list[str]:
    """As linhas de receita de um alvo, sem comentarios."""
    saida: list[str] = []
    dentro = False
    for linha in linhas:
        if linha.startswith(f"{alvo}:"):
            dentro = True
            continue
        if dentro:
            if linha and not linha.startswith(TABULACAO):
                break
            if linha.startswith(TABULACAO) and not _e_comentario(linha):
                saida.append(linha)
    assert saida, f"alvo `{alvo}` sem receita"
    return saida


class TestGate4NaoEngoleTestesVermelhos(unittest.TestCase):
    """O gate 4 chama-se «unit e cobertura», e a primeira palavra tem de contar.

    A primeira versao dos alvos de cobertura punha `|| true` em cada suite e
    `>/dev/null 2>&1` por cima: media a cobertura do codigo que os testes
    cobriam e nunca olhava para o **resultado** deles. Um teste de `lint_refs`
    esteve vermelho desde que o alvo nasceu, e o gate passou verde em sete PRs
    — incluindo nos seis PRs de teste que deviam provar que os gates bloqueiam.

    Nao se corre o `make` aqui; verifica-se que o codigo de saida nao e
    descartado na linha que corre os testes.
    """

    def setUp(self) -> None:
        self.linhas = MAKEFILE.read_text(encoding="utf-8").splitlines()

    def test_o_node_test_nao_termina_em_ou_true(self) -> None:
        for linha in _receita(self.linhas, "coverage-node"):
            if "node --test" in linha:
                self.assertNotIn(
                    "|| true",
                    linha,
                    "o codigo de saida do `node --test` nao pode ser descartado",
                )

    def test_o_unittest_discover_nao_termina_em_ou_true(self) -> None:
        for linha in _receita(self.linhas, "coverage-python"):
            if "unittest discover" in linha:
                self.assertNotIn(
                    "|| true",
                    linha,
                    "o codigo de saida do `unittest` nao pode ser descartado",
                )

    def test_as_receitas_falham_quando_uma_suite_falha(self) -> None:
        """Ha um `exit 1` em cada alvo, e nao so um aviso impresso."""
        for alvo in ("coverage-node", "coverage-python"):
            with self.subTest(alvo=alvo):
                receita = SALTO.join(_receita(self.linhas, alvo))
                self.assertIn("exit 1", receita, f"`{alvo}` nunca falha")
                self.assertNotIn(
                    "aviso: $$pacote sem relatorio",
                    receita,
                    "um pacote sem relatorio e falha, nao aviso",
                )

    def test_o_lcov_sai_antes_de_falhar(self) -> None:
        """Falhar sem relatorio esconde a cobertura de quem for depurar.

        As suites correm todas, o LCOV e escrito, e so depois o alvo falha.
        """
        receita = SALTO.join(_receita(self.linhas, "coverage-python"))
        posicao_lcov = receita.find("coverage lcov")
        posicao_exit = receita.find("exit 1", posicao_lcov)
        self.assertGreater(posicao_lcov, 0, "sem `coverage lcov`")
        self.assertGreater(
            posicao_exit, posicao_lcov, "o alvo falha antes de escrever o LCOV"
        )


class TestCoberturaNodeMedeOAmbito(unittest.TestCase):
    """A cablagem do KAM-132, que se desfaz sem deixar um teste vermelho.

    O alvo mede o ambito do `ci/thresholds.yaml` por duas pecas que se perdem
    com facilidade: a *flag* `--test-coverage-include`, que torna o relatorio
    igual ao ambito, e os padroes que a alimentam, que vem do proprio
    `coverage_gate`. Tirar qualquer uma delas devolve o alvo ao estado em que
    um servico Node inteiro sem testes mantinha o gate verde — e nao ha teste
    de unidade que o note, porque a cobertura continuaria a ser medida: so
    deixava de ser medida sobre o universo certo.
    """

    def setUp(self) -> None:
        self.receita = SALTO.join(_receita(MAKEFILE.read_text(encoding="utf-8").splitlines(), "coverage-node"))

    def test_passa_o_test_coverage_exclude(self) -> None:
        self.assertIn("--test-coverage-exclude=", self.receita)

    def test_nao_passa_o_ambito_em_test_coverage_include(self) -> None:
        """Passar o **ambito** na *flag* de inclusao era o achado maior da revisao.

        A *flag* de inclusao retira do relatorio tudo o que nao esteja na lista,
        incluindo um ficheiro que nenhum estrato classifica — e esse tem de
        chegar ao gate para o **falhar**. Reproduzido por execucao: um
        `packages/core-ts/fora.ts` carregado por um teste falhava o gate sem a
        *flag* e passava com ela.
        """
        self.assertNotIn("--test-coverage-include=", self.receita)

    def test_a_lista_vem_do_coverage_gate(self) -> None:
        """E nao de uma lista escrita no Makefile, que divergiria dos limiares."""
        self.assertIn("coverage_gate.py", self.receita)
        self.assertIn("--exclusoes-node", self.receita)
        posicao_lista = self.receita.find("--exclusoes-node")
        posicao_flag = self.receita.find("--test-coverage-exclude=")
        self.assertGreater(
            posicao_flag,
            posicao_lista,
            "a lista passa-se depois de ser pedida ao coverage_gate",
        )

    def test_a_flag_vai_para_o_node_test(self) -> None:
        """Gerar a lista e nao a passar ao `node --test` e o defeito silencioso."""
        linhas = [
            linha
            for linha in self.receita.split(SALTO)
            if "node --test" in linha
        ]
        self.assertTrue(linhas, "o alvo nao corre `node --test`")
        for linha in linhas:
            self.assertIn("$$excluir", linha, linha)


def _comandos(linhas: list[str]) -> list[str]:
    """As linhas de receita juntas pelas barras de continuacao.

    Um `cd tools && ... --source=.` tem o `cd` e o `--source` em linhas
    diferentes do **mesmo** comando, e ler linha a linha perdia a ligacao entre
    os dois — que e precisamente o que diz qual a pasta medida.
    """
    comandos: list[str] = []
    actual = ""
    for linha in linhas:
        corpo = linha.lstrip(TABULACAO).lstrip("@")
        if corpo.rstrip().endswith("\\"):
            actual += corpo.rstrip()[:-1] + " "
            continue
        comandos.append(actual + corpo)
        actual = ""
    if actual:
        comandos.append(actual)
    return comandos


class TestCoberturaPythonMedeOAmbito(unittest.TestCase):
    """A cablagem do KAM-151, que fechou a lacuna 25 — e que se desfaz calada.

    O `ci/thresholds.yaml` declara **quem e medido**, mas do lado Python nao ha
    quem o imponha: o `universo()` do `coverage_gate` injecta a 0% o `.ts` que
    nenhum relatorio mediu e **nao** o pode fazer com `.py`, porque a regua do
    `coverage.py` sao instrucoes e nao linhas do ficheiro. O universo do Python
    garante-se por cablagem: um `--source=` neste alvo por cada pasta de `.py`
    do ambito.

    E isso nao tinha gate. Os tres ficheiros de `services/agr/src/kamba_agr/`
    estiveram no ambito desde o KAM-002 e fora do denominador desde sempre,
    **com `services/agr/tests/` a exercita-los a fundo**: faltava a medicao, e
    nao os testes. Ninguem notou porque nada ficava vermelho — a mesma classe de
    defeito que o KAM-132 fechou do lado Node. Estes testes sao o que faz a
    proxima pasta de `.py` do ambito ficar vermelha em vez de invisivel.
    """

    def setUp(self) -> None:
        self.linhas = MAKEFILE.read_text(encoding="utf-8").splitlines()
        self.receita = _receita(self.linhas, "coverage-python")

    def _pastas_medidas(self) -> set[str]:
        """As pastas que a receita mede, em caminho relativo a raiz.

        Le-se do `--source=` de cada `coverage run`, com o `cd <pasta> &&` do
        mesmo comando a dar o prefixo: `cd tools && ... --source=.` mede
        `tools`.
        """
        pastas: set[str] = set()
        for comando in _comandos(self.receita):
            if "coverage run" not in comando:
                continue
            # **Um `cd` por comando.** O prefixo do primeiro `cd` vale para
            # todos os `--source=` do mesmo comando; dois `cd` diferentes num
            # so comando atribuiriam a pasta errada e nada ficaria vermelho.
            # Hoje so o laco das suites de `tools/` tem `cd`, e tem um.
            cd = re.search(r"\bcd\s+([^\s&]+)\s*&&", comando)
            prefixo = cd.group(1).strip("\"'") if cd else ""
            for fonte in re.findall(r"--source=(\S+)", comando):
                fonte = fonte.strip("\"'")
                if fonte == ".":
                    caminho = prefixo
                elif prefixo:
                    caminho = f"{prefixo}/{fonte}"
                else:
                    caminho = fonte
                if caminho:
                    pastas.add(caminho.rstrip("/"))
        return pastas

    def test_todo_o_py_do_ambito_cai_sob_um_source(self) -> None:
        """O teste que a lacuna 25 nao tinha.

        O universo sai do **mesmo** `ci/thresholds.yaml` que classifica o que
        foi medido — os `padroes` dos estratos menos os `excluidos` —, e nao de
        uma lista escrita aqui, que divergiria dele em silencio como a do
        `make coverage-node` teria divergido.
        """
        limiares = ler_limiares(ROOT)
        do_ambito = universo(ROOT, limiares, extensoes=(".py",))
        self.assertTrue(
            do_ambito, "universo de `.py` vazio: o teste nao provaria nada"
        )
        pastas = self._pastas_medidas()
        self.assertTrue(pastas, "a receita nao tem nenhum `--source=`")
        sem_medicao = sorted(
            caminho
            for caminho in do_ambito
            if not any(
                caminho == pasta or caminho.startswith(f"{pasta}/")
                for pasta in pastas
            )
        )
        self.assertEqual(
            sem_medicao,
            [],
            "`.py` no ambito de ci/thresholds.yaml que nenhum `--source=` de "
            f"`coverage-python` mede: {sem_medicao}. As pastas medidas sao "
            f"{sorted(pastas)}. Acrescente um `--source=` ao alvo, ou o ficheiro "
            "a `excluidos` com a razao — o que nao se pode e deixa-lo declarado "
            "no ambito e fora do denominador (lacuna 25 de docs/ci.md §7).",
        )

    def test_o_agr_e_medido_por_nome(self) -> None:
        """A pasta que a lacuna 25 nomeia, pregada a parte.

        O teste acima e geral e passaria se alguem **retirasse** o AGR do ambito
        em vez de o medir. Este diz que a pasta que o KAM-151 veio medir continua
        medida.
        """
        self.assertIn("services/agr/src", self._pastas_medidas())

    def test_cada_coverage_run_escreve_o_seu_lcov_antes_do_proximo(self) -> None:
        """`coverage run` sem `--append` **apaga** o ficheiro de dados.

        Um bloco novo entre o `run` e o `coverage lcov` de outro deixava esse
        outro com um relatorio vazio, sem erro nenhum: o gate media menos e
        continuava verde. A regra e conservadora de proposito — o `cd tools`
        escreve noutro ficheiro de dados —, porque e mais barato mante-la do que
        qualificar quais os blocos que partilham o ficheiro.
        """
        texto = SALTO.join(self.receita)
        marcas = [m.group(1) for m in re.finditer(r"coverage (run|lcov)", texto)]
        self.assertIn("run", marcas, "a receita nao corre `coverage run`")
        self.assertIn("lcov", marcas, "a receita nao escreve nenhum LCOV")
        for anterior, seguinte in zip(marcas, marcas[1:]):
            if anterior == "run" and seguinte == "run":
                self.fail(
                    "ha dois `coverage run` seguidos sem `coverage lcov` pelo "
                    f"meio, e o segundo apaga os dados do primeiro: {marcas}"
                )
        self.assertEqual(
            marcas[-1], "lcov", "o ultimo `coverage run` nao escreve LCOV nenhum"
        )

    def _destinos_dos_lcov(self) -> list[str]:
        """O destino de cada `coverage lcov`, relativo a raiz."""
        destinos: list[str] = []
        for comando in _comandos(self.receita):
            if "coverage lcov" not in comando:
                continue
            alvos = re.findall(r"-o\s+(\S+)", comando)
            self.assertEqual(
                len(alvos), 1, f"`coverage lcov` sem um `-o` claro: {comando[:80]!r}"
            )
            destinos.append(alvos[0].replace("$(ROOT)/", "").lstrip("/"))
        return destinos

    def test_cada_coverage_run_escreve_um_lcov_que_o_gate_le(self) -> None:
        """Liga as **tres** pecas: `coverage run` -> nome do LCOV -> glob do gate.

        Cada peca sozinha passa com o arreio desfeito, e e a juncao que importa.

        O `coverage_gate.main` le `ci/coverage/*.lcov` por `glob`: um destino
        com outra extensao — `ci/coverage/agr.dat` — deixa o relatorio **fora do
        gate sem nada ficar vermelho**, que e a mesma classe de defeito que esta
        classe fecha, um nivel acima. E o `base_do_nome` le o pacote do **nome**
        do ficheiro: `python-agr.lcov` dava a base `agr`, que nao e familia
        nenhuma nem pasta do disco, enquanto `python-services-agr.lcov` da
        `services/agr`. Hoje os dois nomes funcionariam, porque o
        `coverage lcov` corre da raiz e emite caminhos relativos a ela; no dia em
        que os emitir relativos ao pacote, um nome que nao resolve manda os
        ficheiros todos para «nao classificados».
        """
        runs = [c for c in _comandos(self.receita) if "coverage run" in c]
        destinos = self._destinos_dos_lcov()
        self.assertTrue(runs, "a receita nao corre `coverage run`")
        self.assertEqual(
            len(destinos),
            len(runs),
            "cada `coverage run` precisa do seu `coverage lcov`: "
            f"{len(runs)} run(s) contra {len(destinos)} lcov(s)",
        )
        for destino in destinos:
            with self.subTest(destino=destino):
                self.assertRegex(
                    destino,
                    r"^ci/coverage/[^/]+\.lcov$",
                    "o destino cai fora do glob `ci/coverage/*.lcov` do "
                    "coverage_gate, e o relatorio nunca chega ao gate",
                )
                base = base_do_nome(Path(destino))
                self.assertTrue(base, f"`{destino}` nao diz a que pacote pertence")
                self.assertTrue(
                    (ROOT / base).is_dir(),
                    f"`{destino}` resolve para `{base}`, que nao e pasta do "
                    "repositorio",
                )

    def test_cada_pasta_medida_tem_um_lcov_com_o_seu_nome(self) -> None:
        """A pasta que um `--source=` mede tem de ser a base do LCOV que a leva.

        Sem isto, o alvo pode medir `services/agr/src` e escrever o resultado
        num `python-libs.lcov`: o gate le-o, e classifica-o pela base errada.
        """
        bases = {base_do_nome(Path(d)) for d in self._destinos_dos_lcov()}
        for pasta in sorted(self._pastas_medidas()):
            with self.subTest(pasta=pasta):
                self.assertTrue(
                    any(pasta == b or pasta.startswith(f"{b}/") for b in bases),
                    f"a pasta medida `{pasta}` nao tem LCOV com o seu nome; "
                    f"as bases dos LCOV sao {sorted(bases)}",
                )


class TestSuitesDeTools(unittest.TestCase):
    """As suites de `tools/` descobrem-se pelo disco (KAM-142) — e isso tem um custo.

    Uma lista escrita a mao rebentava quando uma suite desaparecia; uma
    descoberta deixa de a correr, calada. Estes testes sao a lista que ficou:
    o conjunto minimo esperado, e a forma que a descoberta exige de cada suite.
    """

    #: Quem acrescentar uma suite nao precisa de tocar aqui. Quem **retirar**
    #: uma precisa — e e esse o ponto.
    MINIMAS = {
        "canon_lint", "dict_export", "lint_arch", "lint_refs", "sbom",
        "scan_secrets", "secrets_inventory",
    }

    def setUp(self) -> None:
        self.texto = MAKEFILE.read_text(encoding="utf-8")
        self.descobertas = {
            caminho.parent.parent.name
            for caminho in (ROOT / "tools").glob("*/tests/test_*.py")
        }

    def test_as_suites_minimas_existem_no_disco(self) -> None:
        self.assertEqual(self.MINIMAS - self.descobertas, set())

    def test_cada_suite_e_importavel_pelo_unittest(self) -> None:
        """`discover -t tools` exige `__init__.py` na suite e na pasta de testes."""
        for suite in sorted(self.descobertas):
            with self.subTest(suite=suite):
                self.assertTrue((ROOT / "tools" / suite / "__init__.py").is_file())
                self.assertTrue((ROOT / "tools" / suite / "tests" / "__init__.py").is_file())

    def test_nao_ha_pasta_de_testes_que_a_descoberta_nao_veja(self) -> None:
        """Um `tests/` sem `test_*.py`, ou com outro nome, ficava por correr."""
        for pasta in sorted((ROOT / "tools").iterdir()):
            if not pasta.is_dir() or pasta.name.startswith((".", "__")):
                continue
            for sub in sorted(pasta.iterdir()):
                if sub.is_dir() and sub.name.startswith("test"):
                    with self.subTest(pasta=f"{pasta.name}/{sub.name}"):
                        self.assertEqual(sub.name, "tests")
                        self.assertIn(pasta.name, self.descobertas)

    def test_os_dois_alvos_iteram_a_descoberta_e_exigem_na(self) -> None:
        self.assertEqual(self.texto.count("for suite in $(SUITES_DE_TOOLS); do"), 2)
        self.assertNotRegex(self.texto, r"for suite in [a-z_]+ [a-z_]+")
        for alvo in ("test-py", "coverage-python"):
            with self.subTest(alvo=alvo):
                self.assertRegex(self.texto, rf"(?m)^{alvo}:.*\bexige-suites\b")

    def test_a_descoberta_parte_da_raiz_e_nao_do_directorio_de_trabalho(self) -> None:
        self.assertIn("$(wildcard $(ROOT)/tools/*/tests/test_*.py)", self.texto)


class TestAlvos(unittest.TestCase):
    def setUp(self) -> None:
        self.texto = MAKEFILE.read_text(encoding="utf-8")
        self.documentados = set(
            re.findall(r"^## ([a-z-]+):", self.texto, flags=re.MULTILINE)
        )

    def test_alvos_documentados_existem(self) -> None:
        """Cada `## alvo:` do `make help` tem de ter uma regra."""
        definidos = set(re.findall(r"^([a-z-]+):", self.texto, flags=re.MULTILINE))
        faltam = self.documentados - definidos
        self.assertEqual(faltam, set(), f"alvos no help sem regra: {sorted(faltam)}")

    def test_alvos_estao_em_phony(self) -> None:
        """Um ficheiro com o nome de um alvo fa-lo deixar de correr."""
        bloco = self.texto[self.texto.index(".PHONY:") :]
        bloco = bloco[: bloco.index("\n\n")]
        phony = set(bloco.replace(".PHONY:", "").replace("\\", " ").split())
        faltam = self.documentados - phony
        self.assertEqual(
            faltam, set(), f"alvos documentados fora de .PHONY: {sorted(faltam)}"
        )

    def test_o_docker_so_e_exigido_no_up(self) -> None:
        """`make bootstrap` nao pode exigir docker.

        O critério de aceitacao pede `make bootstrap && make check` verdes a
        partir de clone limpo; um runner que so constroi e testa nao tem de ter
        docker, e so `make up` levanta contentores.
        """
        doctor = self.texto[
            self.texto.index("\ndoctor:") : self.texto.index("\n## bootstrap")
        ]
        self.assertIn("AVISO: sem docker", doctor, "o doctor tem de avisar, nao falhar")
        self.assertNotIn("FALTA docker", doctor)

        resto = self.texto[self.texto.index("\nup:") :]
        up = resto[: resto.index("\n## down")]
        self.assertIn("FALTA docker", up, "o up tem de exigir docker explicitamente")

    def test_o_lint_corre_antes_de_instalar(self) -> None:
        """A lista de bloqueio tem de ser pre-requisito do bootstrap.

        Um linter de dependencias que so corresse depois do `pnpm install`
        chegaria tarde para o unico caso que interessa (docs/tecnica/08 §4.8).
        """
        linha = next(
            l for l in self.texto.split("\n") if l.startswith("bootstrap:")
        )
        self.assertIn("lint-arch", linha)
        self.assertLess(
            linha.index("lint-arch"),
            linha.index("$(VENV)") if "$(VENV)" in linha else len(linha),
            "lint-arch tem de vir antes da instalacao",
        )


if __name__ == "__main__":
    unittest.main()
