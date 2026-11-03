"""Convencoes de commit e de ramo do §5 do Engineering Standards.

As regras vivem em `tools/conventions.json` e sao lidas tambem pelo
`commitlint.config.cjs`. Estes testes cobrem o lado que corre sem Node — que e o
lado que os *git hooks* usam.
"""

from __future__ import annotations

import dataclasses
import json
import re
import unittest
from pathlib import Path

from lint_arch import canario_titulo, conventions

ROOT = Path(__file__).resolve().parents[3]
CONVENTIONS = ROOT / "tools" / "conventions.json"


class TestCarregamento(unittest.TestCase):
    def test_carrega_o_ficheiro_do_repositorio(self) -> None:
        rules = conventions.load(CONVENTIONS)
        self.assertEqual(
            rules.types, ("feat", "fix", "chore", "refactor", "test", "docs", "spike")
        )
        self.assertEqual(rules.scope_pattern, "^KAM-[0-9]{3}$")

    def test_ficheiro_incompleto_falha(self) -> None:
        import tempfile

        for caso in ('{"commit": {}}', '{"commit": {"types": []}}', "{}", "nao-json"):
            with self.subTest(caso=caso):
                with tempfile.NamedTemporaryFile(
                    "w", suffix=".json", delete=False, encoding="utf-8"
                ) as handle:
                    handle.write(caso)
                    caminho = Path(handle.name)
                try:
                    with self.assertRaises(conventions.ConventionError):
                        conventions.load(caminho)
                finally:
                    caminho.unlink()


class TestMensagemDeCommit(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = conventions.load(CONVENTIONS)

    def aceita(self, mensagem: str) -> None:
        problemas = conventions.check_commit_message(mensagem, self.rules)
        self.assertEqual(problemas, [], f"devia aceitar: {mensagem!r}")

    def recusa(self, mensagem: str) -> None:
        problemas = conventions.check_commit_message(mensagem, self.rules)
        self.assertNotEqual(problemas, [], f"devia recusar: {mensagem!r}")

    def test_aceita_cada_tipo_permitido(self) -> None:
        for tipo in self.rules.types:
            self.aceita(f"{tipo}(KAM-001): cria a arvore do monorepo")

    def test_aceita_corpo_e_rodape(self) -> None:
        self.aceita(
            "chore(KAM-001): cria a arvore do monorepo\n\n"
            "Fixa Node 24 LTS e Hono 4.13.x.\n\n"
            "Refs: ADR-002\n"
        )

    def test_recusa_sem_ticket(self) -> None:
        self.recusa("chore: cria a arvore do monorepo")

    def test_recusa_ambito_que_nao_e_ticket(self) -> None:
        for ambito in ("monorepo", "kam-001", "KAM-1", "KAM-0001", "ABC-001"):
            with self.subTest(ambito=ambito):
                self.recusa(f"chore({ambito}): cria a arvore do monorepo")

    def test_recusa_tipo_fora_da_lista(self) -> None:
        for tipo in ("build", "ci", "style", "perf", "wip"):
            with self.subTest(tipo=tipo):
                self.recusa(f"{tipo}(KAM-001): cria a arvore do monorepo")

    def test_recusa_formato_livre(self) -> None:
        for mensagem in (
            "arranjei o monorepo",
            "KAM-001 cria a arvore",
            "chore(KAM-001) cria a arvore do monorepo",
            "chore(KAM-001):sem espaco depois dos dois pontos",
            "",
        ):
            with self.subTest(mensagem=mensagem):
                self.recusa(mensagem)

    def test_recusa_descricao_capitalizada_ou_terminada_em_ponto(self) -> None:
        self.recusa("chore(KAM-001): Cria a arvore do monorepo")
        self.recusa("chore(KAM-001): cria a arvore do monorepo.")

    def test_recusa_descricao_curta_ou_longa(self) -> None:
        self.recusa("chore(KAM-001): curto")
        self.recusa("chore(KAM-001): " + "a" * 200)

    def test_aceita_merge_e_revert(self) -> None:
        # Sem esta excepcao, `git merge` e `git revert` ficavam impossiveis.
        self.aceita("Merge branch 'main' into feature/KAM-001-monorepo")
        self.aceita('Revert "chore(KAM-001): cria a arvore do monorepo"')
        self.aceita("fixup! chore(KAM-001): cria a arvore do monorepo")

    def test_ignora_comentarios_do_git(self) -> None:
        self.aceita(
            "# Por favor escreva a mensagem\nchore(KAM-001): cria a arvore do monorepo"
        )


class TestNomeDeRamo(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = conventions.load(CONVENTIONS)

    def test_aceita_feature_e_fix(self) -> None:
        for nome in (
            "feature/KAM-001-monorepo-e-toolchain",
            "fix/KAM-013-assinatura-do-webhook",
            "feature/KAM-127-h10",
        ):
            with self.subTest(nome=nome):
                self.assertEqual(conventions.check_branch_name(nome, self.rules), [])

    def test_aceita_main(self) -> None:
        self.assertEqual(conventions.check_branch_name("main", self.rules), [])

    def test_recusa_o_resto(self) -> None:
        for nome in (
            "feature/monorepo",
            "feature/KAM-001",
            "chore/KAM-001-monorepo",
            "feature/kam-001-monorepo",
            "feature/KAM-001-Monorepo",
            "feature/KAM-001_monorepo",
            "KAM-001",
            "develop",
            "",
        ):
            with self.subTest(nome=nome):
                problemas = conventions.check_branch_name(nome, self.rules)
                self.assertNotEqual(problemas, [], f"devia recusar: {nome!r}")


class TestSiglasEMaiusculas(unittest.TestCase):
    """O vocabulario do projecto tem siglas, e elas tem de passar.

    Uma regra `subject-case: lower-case` recusaria metade das mensagens que este
    projecto escreve. O que se recusa e a descricao **inteira** em maiusculas e a
    primeira letra capitalizada — nao as siglas no meio.
    """

    def setUp(self) -> None:
        self.rules = conventions.load(CONVENTIONS)

    def test_siglas_no_meio_passam(self) -> None:
        for mensagem in (
            "feat(KAM-004): acrescenta RLS FORCE a todas as tabelas com tenant_id",
            "feat(KAM-008): roda a chave do HMAC do BSUID",
            "fix(KAM-052): corrige o callback do PSP sem assinatura HMAC",
            "chore(KAM-010): move os segredos para o Doppler",
            "docs(KAM-001): registra o intervalo de Node do Medusa",
            "feat(KAM-064): declara a transferencia a APD e a AGT",
        ):
            with self.subTest(mensagem=mensagem):
                self.assertEqual(
                    conventions.check_commit_message(mensagem, self.rules), []
                )

    def test_descricao_inteira_em_maiusculas_falha(self) -> None:
        problemas = conventions.check_commit_message(
            "chore(KAM-001): CRIA A ARVORE DO MONOREPO", self.rules
        )
        self.assertNotEqual(problemas, [])


class TestCorpoERodape(unittest.TestCase):
    """As regras que o commitlint impoe e que o hook tem de impor tambem."""

    def setUp(self) -> None:
        self.rules = conventions.load(CONVENTIONS)

    def test_corpo_sem_linha_em_branco_falha(self) -> None:
        problemas = conventions.check_commit_message(
            "chore(KAM-001): cria a arvore do monorepo\nsem linha em branco",
            self.rules,
        )
        self.assertTrue(
            any("body-leading-blank" in p for p in problemas), problemas
        )

    def test_corpo_com_linha_em_branco_passa(self) -> None:
        self.assertEqual(
            conventions.check_commit_message(
                "chore(KAM-001): cria a arvore do monorepo\n\nFixa Node 24 LTS.",
                self.rules,
            ),
            [],
        )

    def test_rodape_sem_linha_em_branco_falha(self) -> None:
        problemas = conventions.check_commit_message(
            "chore(KAM-001): cria a arvore do monorepo\n\n"
            "Fixa Node 24 LTS.\nRefs: ADR-002",
            self.rules,
        )
        self.assertTrue(
            any("footer-leading-blank" in p for p in problemas), problemas
        )

    def test_rodape_com_linha_em_branco_passa(self) -> None:
        self.assertEqual(
            conventions.check_commit_message(
                "chore(KAM-001): cria a arvore do monorepo\n\n"
                "Fixa Node 24 LTS.\n\nRefs: ADR-002",
                self.rules,
            ),
            [],
        )


# ---------------------------------------------------------------------------
# O titulo do PR — KAM-164
# ---------------------------------------------------------------------------

#: Os seis assuntos de *squash* que estao no `main`, **copiados de la** e nao
#: inventados: e o que os torna prova. Leem-se com
#: `git log -1 --format=%s <sha>`, e o ` (#NN)` do fim e o que o GitHub acrescenta
#: na fusao. Os cinco primeiros estao conformes por os seus PR terem sido
#: titulados a mao na forma certa — nao por alguma coisa o exigir, que e
#: precisamente o que o KAM-164 vem corrigir. O sexto e o defeito.
ASSUNTOS_CONFORMES = (
    ("eee3994", "chore(KAM-162): retira a agentic-engineering e põe a software-factory no seu lugar (#74)"),
    ("c0b1816", "fix(KAM-019): a fronteira da saida de waiting da platform.handoffs (fecha o criterio 3 do KAM-034) (#73)"),
    ("6e1bd7b", "docs(KAM-161): o registo de entrega nas duas tabelas de versoes (#72)"),
    ("7e431b5", "docs(KAM-034): o bloco deixa de afirmar o que a revisao mudou (#71)"),
    ("c65d134", "feat(KAM-034): handoff idempotente em dois nos e retoma por compare-and-set (#70)"),
)

#: O assunto que ficou no `main` sem passar por nenhum dos tres mecanismos: o PR
#: #75 trazia dois commits, os dois conformes e os dois verificados pelo *gate*
#: 2, e o GitHub usou o titulo do PR. Nao tem tipo.
ASSUNTO_RECUSADO = ("29778f3", "KAM-038 — Subscricao de eventos: as verticais acordam por evento (#75)")


class TestTituloDePR(unittest.TestCase):
    """Criterio 3 e «Testes Requeridos: unit» do KAM-164.

    O titulo de um PR e o assunto que fica no `main` quando a fusao e por
    *squash* e o PR traz mais do que um commit
    (`squash_merge_commit_title: COMMIT_OR_PR_TITLE`).
    """

    def setUp(self) -> None:
        self.rules = conventions.load(CONVENTIONS)

    def test_aceita_os_cinco_assuntos_reais_conformes(self) -> None:
        for sha, assunto in ASSUNTOS_CONFORMES:
            with self.subTest(sha=sha):
                self.assertEqual(
                    conventions.check_pr_title(assunto, self.rules),
                    [],
                    f"o assunto do {sha} esta conforme e tem de passar",
                )

    def test_recusa_o_assunto_do_29778f3(self) -> None:
        sha, assunto = ASSUNTO_RECUSADO
        problemas = conventions.check_pr_title(assunto, self.rules)
        self.assertNotEqual(problemas, [], f"o assunto do {sha} tem de ser recusado")
        self.assertTrue(
            any("titulo fora de" in p for p in problemas),
            f"a razao tem de ser a forma, nao outra: {problemas}",
        )

    def test_a_palavra_do_achado_fala_de_titulo_e_nao_de_cabecalho(self) -> None:
        # Criterio 6: quem le o achado esta a olhar para um titulo de PR.
        problemas = conventions.check_pr_title("arranjei o monorepo", self.rules)
        self.assertTrue(any(p.startswith("titulo ") for p in problemas), problemas)

    def test_recusa_titulo_vazio_ou_so_com_espacos(self) -> None:
        for titulo in ("", "   ", "\n", "\t "):
            with self.subTest(titulo=titulo):
                self.assertEqual(
                    conventions.check_pr_title(titulo, self.rules),
                    ["titulo de PR vazio"],
                )

    def test_normaliza_espaco_em_branco(self) -> None:
        # Um titulo colado traz espacos duplos; o achado, se houver, tem de ser
        # pela forma e nao por um caractere que ninguem ve.
        self.assertEqual(
            conventions.check_pr_title(
                "  feat(KAM-164):   verifica o titulo do PR contra a convencao  ",
                self.rules,
            ),
            [],
        )

    def test_nao_dispensa_merge_revert_nem_fixup(self) -> None:
        """A diferenca deliberada face a `check_commit_message`.

        `exemptHeaderPatterns` dispensa o que o *git* gera sozinho. Nada no
        GitHub gera um titulo de PR dessas formas, e um `Merge ...` dispensado
        acabaria no `main` como assunto — o defeito que isto existe para fechar.
        """
        for titulo in (
            "Merge branch 'main' into feature/KAM-164-titulo-do-pr-verificado",
            'Revert "chore(KAM-001): cria a arvore do monorepo"',
            "fixup! chore(KAM-001): cria a arvore do monorepo",
            "squash! chore(KAM-001): cria a arvore do monorepo",
        ):
            with self.subTest(titulo=titulo):
                self.assertNotEqual(
                    conventions.check_pr_title(titulo, self.rules),
                    [],
                    "um titulo de PR nao tem dispensas",
                )
                # E a prova de que a diferenca e desta superficie e nao da forma:
                # a mesma linha, como mensagem de commit, continua dispensada.
                self.assertEqual(
                    conventions.check_commit_message(titulo, self.rules), []
                )

    def test_herda_as_regras_do_ficheiro_de_convencoes(self) -> None:
        # Nao ha regras proprias: tudo o que o cabecalho de um commit recusa, o
        # titulo recusa tambem.
        for titulo in (
            "chore: cria a arvore do monorepo",  # sem ambito
            "build(KAM-001): cria a arvore do monorepo",  # tipo fora da lista
            "chore(monorepo): cria a arvore do monorepo",  # ambito que nao e ticket
            "chore(KAM-001): Cria a arvore do monorepo",  # capitalizada
            "chore(KAM-001): cria a arvore do monorepo.",  # ponto final
            "chore(KAM-001): curto",  # descricao curta
            "chore(KAM-001): " + "a" * 200,  # descricao longa
            "chore(KAM-001): CRIA A ARVORE DO MONOREPO",  # tudo em maiusculas
        ):
            with self.subTest(titulo=titulo):
                self.assertNotEqual(conventions.check_pr_title(titulo, self.rules), [])

    def test_aceita_cada_tipo_permitido(self) -> None:
        for tipo in self.rules.types:
            with self.subTest(tipo=tipo):
                self.assertEqual(
                    conventions.check_pr_title(
                        f"{tipo}(KAM-164): verifica o titulo do PR", self.rules
                    ),
                    [],
                )


class TestCanarioDoTitulo(unittest.TestCase):
    """Criterio 5 do KAM-164: o canario fica verde quando a verificacao morde…

    …e **vermelho quando ela deixa de morder**, que e a metade que distingue um
    canario de um teste. Prova-se por mutacao das proprias convencoes, em
    memoria: nao ha arvore para copiar, porque o que se verifica e uma cadeia de
    caracteres.
    """

    def setUp(self) -> None:
        self.rules = conventions.load(CONVENTIONS)

    def test_verde_com_as_convencoes_do_repositorio(self) -> None:
        falhas, numeros = canario_titulo.canario(self.rules)
        self.assertEqual(falhas, [])
        self.assertGreaterEqual(numeros["negativos"], len(canario_titulo.REGRAS_DO_TITULO))
        self.assertGreaterEqual(numeros["positivos"], 2)

    def test_vermelho_quando_duas_regras_deixam_de_morder(self) -> None:
        mudadas = dataclasses.replace(
            self.rules, subject_starts_lowercase=False, subject_ends_without_period=False
        )
        falhas, _ = canario_titulo.canario(mudadas)
        for regra in ("descricao comeca em minuscula", "descricao nao termina em ponto"):
            with self.subTest(regra=regra):
                self.assertTrue(
                    any(f"sem caso negativo que prove {regra!r}" in f for f in falhas),
                    f"o canario nao deu pela regra {regra!r}: {falhas}",
                )

    def test_vermelho_quando_a_forma_deixa_de_morder(self) -> None:
        # Todos os tipos aceites e um ambito que aceita tudo: a verificacao passa
        # a aprovar o que recusava, e o canario tem de o dizer.
        mudadas = dataclasses.replace(
            self.rules,
            types=self.rules.types + ("build", "KAM-038"),
            scope_pattern="^.*$",
        )
        falhas, _ = canario_titulo.canario(mudadas)
        self.assertNotEqual(falhas, [], "a forma afrouxou e o canario ficou verde")

    def test_vermelho_quando_um_positivo_real_e_recusado(self) -> None:
        # O outro lado: uma regra nova que recusasse os assuntos que estao no
        # `main` e um falso vermelho a quem titula bem, e isso tambem e falha.
        mudadas = dataclasses.replace(self.rules, subject_max_length=20)
        falhas, _ = canario_titulo.canario(mudadas)
        self.assertTrue(
            any("esta conforme e foi recusado" in f for f in falhas), falhas
        )

    def test_cada_regra_da_verificacao_tem_quem_a_prove(self) -> None:
        """`REGRAS_DO_TITULO` nao pode ficar atras do que a verificacao produz.

        Se `check_pr_title` ganhar uma regra e ninguem a acrescentar aqui, o
        canario passa a cobrir menos do que existe — sem avisar. Esta e a
        asercao que obriga a lista a crescer com a verificacao.
        """
        produzidas: set[str] = set()
        for titulo, _ in canario_titulo.NEGATIVOS:
            produzidas.update(conventions.check_pr_title(titulo, self.rules))
        for regra in canario_titulo.REGRAS_DO_TITULO:
            with self.subTest(regra=regra):
                self.assertTrue(
                    any(regra in p for p in produzidas),
                    f"a regra {regra!r} nao e produzida por nenhum negativo",
                )

    def test_o_primeiro_negativo_e_o_caso_real_do_29778f3(self) -> None:
        # A lista nao se enche de casos inventados: o primeiro e o assunto que
        # esta no `main`, sem o ` (#75)` que o GitHub acrescenta na fusao.
        titulo, regra = canario_titulo.NEGATIVOS[0]
        self.assertEqual(titulo, ASSUNTO_RECUSADO[1].removesuffix(" (#75)"))
        self.assertEqual(regra, "titulo fora de")

    def test_os_positivos_sao_os_cinco_assuntos_reais(self) -> None:
        esperados = tuple(
            assunto.rsplit(" (#", 1)[0] for _, assunto in ASSUNTOS_CONFORMES
        )
        self.assertEqual(canario_titulo.POSITIVOS, esperados)


class TestFonteUnicaDaForma(unittest.TestCase):
    """Criterio 2 e «Uma so fonte da forma» da DoD do KAM-164.

    A forma vive em `tools/conventions.json`. Duas copias divergem, e a
    divergencia aparece no dia em que alguem repara que uma superficie aceita o
    que a outra recusa — o `commitlint.config.cjs` e o `conventions.py` existem
    nessa forma por essa razao.

    O discriminante e a **alternacao dos tipos**: um `KAM-[0-9]{3}` sozinho e um
    identificador de ticket, que meia duzia de ferramentas desta casa tem razao
    para reconhecer (`lint_refs`, `supply_chain`, o `vagas.py`). O que nenhuma
    tem razao para escrever e `feat|fix|chore|…`, porque isso e a forma do
    cabecalho, e dela ha uma so fonte.
    """

    #: Onde a forma pode aparecer: a fonte, e este ficheiro — que a afirma para
    #: verificar que a fonte nao mudou debaixo dos pes. Uma asercao sobre a fonte
    #: nao e uma segunda implementacao dela.
    PERMITIDOS = frozenset(
        {
            "tools/conventions.json",
            "tools/lint_arch/tests/test_conventions.py",
        }
    )

    #: Superficies que uma maquina le. A prosa fica de fora de proposito: o
    #: criterio 1 do KAM-164 **manda** escrever a forma no `specs/01` §5 e §7, e
    #: um teste que a proibisse ali contradizia o criterio ao lado.
    SUFIXOS = (".py", ".cjs", ".js", ".mjs", ".ts", ".yaml", ".yml", ".json", ".json5", ".sh")

    #: Caminho -> texto, lido uma vez. Varrer a arvore duas vezes custava meio
    #: minuto num `make ci-4` que corre a cada PR.
    corpus: dict[str, str] = {}

    @classmethod
    def setUpClass(cls) -> None:
        import subprocess

        saida = subprocess.run(
            ["git", "ls-files"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for linha in saida.splitlines():
            caminho = linha.strip()
            if not caminho or caminho in cls.PERMITIDOS:
                continue
            if not (
                caminho.endswith(cls.SUFIXOS) or caminho.startswith("tools/githooks/")
            ):
                continue
            try:
                cls.corpus[caminho] = (ROOT / caminho).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

    def test_o_corpus_nao_esta_vazio(self) -> None:
        # Um teste de ausencia que varra zero ficheiros passa sempre, e nao prova
        # nada. Esta e a guarda contra um `git ls-files` que falhe em silencio.
        self.assertGreater(len(self.corpus), 100, "o corpus de ficheiros ficou vazio")
        self.assertIn("commitlint.config.cjs", self.corpus)

    def test_a_alternacao_dos_tipos_nao_aparece_em_mais_nenhum_sitio(self) -> None:
        rules = conventions.load(CONVENTIONS)
        tipos = "|".join(re.escape(t) for t in rules.types)
        # Dois tipos separados por `|`, que e a assinatura de uma alternacao de
        # regex e nao de prosa.
        alternacao = re.compile(rf"(?:{tipos})[ ]*\|[ ]*(?:{tipos})")

        copias = [c for c, texto in self.corpus.items() if alternacao.search(texto)]
        self.assertEqual(
            copias,
            [],
            "a forma do cabecalho vive so em tools/conventions.json; "
            f"segunda copia em: {copias}",
        )

    def test_a_lista_de_tipos_nao_esta_escrita_em_mais_nenhum_sitio(self) -> None:
        rules = conventions.load(CONVENTIONS)
        # A lista inteira, escrita como literais, num ficheiro que nao e a fonte.
        copias = [
            caminho
            for caminho, texto in self.corpus.items()
            if all(f'"{tipo}"' in texto or f"'{tipo}'" in texto for tipo in rules.types)
        ]
        self.assertEqual(
            copias,
            [],
            "a lista de tipos vive so em tools/conventions.json; "
            f"segunda copia em: {copias}",
        )

    def test_a_verificacao_do_titulo_le_a_mesma_fonte(self) -> None:
        # A prova pelo comportamento, nao pela leitura: muda-se a fonte e a
        # verificacao do titulo muda com ela.
        import tempfile

        dados = json.loads(CONVENTIONS.read_text(encoding="utf-8"))
        dados["commit"]["types"] = ["inventado"]
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(json.dumps(dados))
            caminho = Path(handle.name)
        try:
            outras = conventions.load(caminho)
            self.assertEqual(
                conventions.check_pr_title(
                    "inventado(KAM-164): verifica o titulo do PR", outras
                ),
                [],
            )
            self.assertNotEqual(
                conventions.check_pr_title(
                    "feat(KAM-164): verifica o titulo do PR", outras
                ),
                [],
            )
        finally:
            caminho.unlink()


class TestFonteUnica(unittest.TestCase):
    def test_toda_a_regra_do_commitlint_esta_no_json_e_no_python(self) -> None:
        """Nenhuma regra activa no commitlint pode faltar do lado Python.

        E esta a promessa de `tools/conventions.json`: "o hook nao pode aceitar o
        que o CI recusa". Uma regra que exista so no `.cjs` e uma divergencia.
        Este teste e a razao pela qual ela nao volta.
        """
        config = (ROOT / "commitlint.config.cjs").read_text(encoding="utf-8")
        padrao = r'^\s*"([a-z-]+)":\s*(?:\[\s*ERRO|subject)'
        activas = set(re.findall(padrao, config, re.M))

        # Regra do commitlint -> como se verifica no lado Python.
        coberta_por = {
            "type-enum": "types",
            "type-case": "header_pattern",
            "type-empty": "header_pattern",
            "scope-empty": "header_pattern",
            "kamba-scope-is-ticket": "scope_pattern",
            "subject-empty": "header_pattern",
            "subject-min-length": "subject_min_length",
            "subject-max-length": "subject_max_length",
            "header-max-length": "header_max_length",
            "subject-case": "descricao inteira em maiusculas",
            "subject-full-stop": "subject_ends_without_period",
            "body-leading-blank": "body_leading_blank",
            "footer-leading-blank": "footer_leading_blank",
        }
        nao_cobertas = activas - set(coberta_por)
        self.assertEqual(
            nao_cobertas,
            set(),
            f"regras activas no commitlint sem implementacao em conventions.py: "
            f"{sorted(nao_cobertas)}",
        )

    def test_o_commitlint_le_o_mesmo_ficheiro(self) -> None:
        """O config do commitlint tem de ler `tools/conventions.json`, nao copia-lo.

        Duas definicoes da mesma regra divergem; a divergencia aparece no dia em
        que o hook aceita o que o CI recusa.
        """
        config = (ROOT / "commitlint.config.cjs").read_text(encoding="utf-8")
        self.assertIn("tools/conventions.json", config)

    def test_o_json_e_valido_e_tem_as_chaves_que_as_duas_vias_usam(self) -> None:
        data = json.loads(CONVENTIONS.read_text(encoding="utf-8"))
        for chave in (
            "types",
            "scopePattern",
            "subjectMinLength",
            "subjectMaxLength",
            "headerMaxLength",
            "subjectStartsLowercase",
            "subjectEndsWithoutPeriod",
            "bodyLeadingBlank",
            "footerLeadingBlank",
        ):
            self.assertIn(chave, data["commit"])
        self.assertIn("patterns", data["branch"])


if __name__ == "__main__":
    unittest.main()
