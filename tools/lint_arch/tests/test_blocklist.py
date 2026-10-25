"""A lista de bloqueio bloqueia o que tem de bloquear, e nada mais.

O KAM-001 exige sete *fixtures* de bloqueio (uma por entrada) e duas de
passagem. Estao aqui catorze e quatro, porque sete cobriam as sete formas que as
*fixtures* escolheram e nao a classe do problema: uma revisao adversarial
encontrou **oito formas reproduziveis** de meter uma dependencia proibida no
repositorio sem que a lista desse por isso. Cada uma e agora uma fixture.

As de passagem valem tanto como as outras: um linter que bloqueia tudo satisfaz
as de bloqueio e nao serve para nada. A `p3` e a que importa — contem pacotes npm
**reais** cujos nomes contem as cadeias bloqueadas por acidente.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from lint_arch import blocklist
from lint_arch.cli import check_dependencies

ROOT = Path(__file__).resolve().parents[3]
BLOCKLIST = ROOT / "tools" / "blocklist.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: fixture -> (cadeia que a mensagem tem de citar, ADR)
BLOCKING = {
    # As sete do ticket, uma por item da lista.
    "f1-langgraph-api": ("langgraph-api", "ADR-002"),
    "f2-langgraph-runtime-inmem": ("langgraph-runtime-inmem", "ADR-002"),
    "f3-dify": ("dify", "ADR-002"),
    "f4-n8n": ("n8n", "ADR-002"),
    "f5-typebot": ("typebot", "ADR-002"),
    "f6-minio": ("minio", "ADR-014"),
    "f7-litellm-antigo": ("litellm", "ADR-005"),
    # As sete que a revisao adversarial descobriu em falta.
    "f8-litellm-imagem": ("litellm", "ADR-005"),
    "f9-pnpm-overrides": ("n8n", "ADR-002"),
    "f10-from-platform": ("minio", "ADR-014"),
    "f11-build-system-requires": ("langgraph-api", "ADR-002"),
    "f12-alias-npm": ("minio", "ADR-014"),
    "f13-editable-egg": ("langgraph", "ADR-002"),
    "f14-compose-sem-nome-convencional": ("minio", "ADR-014"),
}

PASSING = (
    "p1-minimo",
    "p2-litellm-corrigido",
    "p3-nomes-parecidos",
    "p4-litellm-imagem-corrigida",
)


class TestFicheiroDeBloqueio(unittest.TestCase):
    def test_carrega_e_cobre_os_sete_itens_do_ticket(self) -> None:
        entries = blocklist.load_entries(BLOCKLIST)
        nomes = {entry.name for entry in entries}
        for exigido in (
            "langgraph-api",
            "langgraph-runtime-inmem",
            "dify",
            "n8n",
            "typebot",
            "minio",
            "litellm",
        ):
            self.assertIn(exigido, nomes, f"{exigido} tem de estar na lista (KAM-001)")

    def test_cada_entrada_cita_adr_evidencia_e_razao(self) -> None:
        for entry in blocklist.load_entries(BLOCKLIST):
            with self.subTest(entry=entry.name):
                self.assertRegex(entry.adr, r"^ADR-[0-9]{3}$")
                self.assertIn("E4_Stack_Licencas.md", entry.evidence)
                self.assertGreater(len(entry.reason), 30)

    def test_o_saver_postgres_e_os_dois_lgpl_sao_bloqueados(self) -> None:
        """A descoberta do KAM-026, presa por teste.

        O `langgraph-checkpoint-postgres` e MIT e o fecho dele nao e. Bloquear
        o pacote sem bloquear os dois que ele arrasta deixava a porta aberta a
        quem os pedisse directamente.
        """
        entries = blocklist.load_entries(BLOCKLIST)
        for nome in ("langgraph-checkpoint-postgres", "psycopg", "psycopg-pool"):
            with self.subTest(nome=nome):
                self.assertTrue(
                    any(
                        e.applies_to_kind("pypi") and e.matches_name(nome, "pypi")
                        for e in entries
                    ),
                    f"{nome} e LGPL por transitividade e tem de estar bloqueado",
                )

    def test_litellm_tem_limiar(self) -> None:
        entries = [e for e in blocklist.load_entries(BLOCKLIST) if e.name == "litellm"]
        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(entry.forbidden_below, "1.83.0")

    def test_ficheiro_malformado_falha_em_vez_de_ficar_vazio(self) -> None:
        import tempfile

        casos = {
            "sem versao": "entries:\n  - name: x\n",
            "versao errada": "version: 2\nentries:\n  - name: x\n",
            "entries vazio": "version: 1\nentries:\n",
            "campo em falta": "version: 1\nentries:\n  - name: x\n    kind: npm\n",
            "kind invalido": (
                "version: 1\nentries:\n  - name: x\n    kind: cargo\n"
                "    match: exact\n    adr: ADR-002\n    evidence: e\n    reason: r\n"
            ),
            "match invalido": (
                "version: 1\nentries:\n  - name: x\n    kind: npm\n"
                "    match: regex\n    adr: ADR-002\n    evidence: e\n    reason: r\n"
            ),
            "nome em maiusculas": (
                "version: 1\nentries:\n  - name: MinIO\n    kind: any\n"
                "    match: boundary\n    adr: ADR-014\n    evidence: e\n    reason: r\n"
            ),
            "limiar nao numerico": (
                "version: 1\nentries:\n  - name: litellm\n    kind: any\n"
                "    match: exact\n    forbidden_below: ultima\n    adr: ADR-005\n"
                "    evidence: e\n    reason: r\n"
            ),
        }
        for nome, conteudo in casos.items():
            with self.subTest(caso=nome):
                with tempfile.NamedTemporaryFile(
                    "w", suffix=".yaml", delete=False, encoding="utf-8"
                ) as handle:
                    handle.write(conteudo)
                    caminho = Path(handle.name)
                try:
                    with self.assertRaises(ValueError):
                        blocklist.load_entries(caminho)
                finally:
                    caminho.unlink()


class TestFixturesDeBloqueio(unittest.TestCase):
    def test_cada_fixture_e_bloqueada_com_o_adr_certo(self) -> None:
        for nome, (pacote, adr) in BLOCKING.items():
            with self.subTest(fixture=nome):
                achados = check_dependencies(FIXTURES / "bloqueio" / nome, BLOCKLIST)
                self.assertTrue(
                    achados, f"a fixture {nome} tinha de ser bloqueada e passou"
                )
                texto = "\n".join(achados)
                self.assertIn(adr, texto, "a mensagem tem de citar o ADR")
                self.assertIn(pacote, texto.lower())
                self.assertIn("E4_Stack_Licencas.md", texto, "tem de citar a evidencia")

    def test_as_fixtures_declaradas_existem_todas(self) -> None:
        encontradas = {p.name for p in (FIXTURES / "bloqueio").iterdir() if p.is_dir()}
        self.assertEqual(encontradas, set(BLOCKING))


class TestFixturesDePassagem(unittest.TestCase):
    def test_nao_ha_falsos_positivos(self) -> None:
        for nome in PASSING:
            with self.subTest(fixture=nome):
                achados = check_dependencies(FIXTURES / "passagem" / nome, BLOCKLIST)
                self.assertEqual(
                    achados,
                    [],
                    f"a fixture {nome} e legitima e foi bloqueada:\n"
                    + "\n".join(achados),
                )

    def test_as_fixtures_de_passagem_existem_todas(self) -> None:
        encontradas = {p.name for p in (FIXTURES / "passagem").iterdir() if p.is_dir()}
        self.assertEqual(encontradas, set(PASSING))


class TestNomesParecidosNaoSaoBloqueados(unittest.TestCase):
    """Pacotes npm reais que contem as cadeias bloqueadas por acidente.

    Confirmados existentes no registo npm. `modify-values` e da familia
    `conventional-changelog` — o mesmo ecossistema do `@commitlint/*` que este
    repositorio tem nas devDependencies. Com um `match: substring`, o dia em que
    um deles entrasse como dependencia transitiva deixava `make check` vermelho
    no repositorio inteiro, por um pacote que ninguem escolheu.
    """

    LEGITIMOS = (
        "modify-values",
        "modify-babel-preset",
        "codify",
        "solidify",
        "nodify",
        "minion",
        "dominion",
        "pagination",
        "dignify",
        "minimatch",
    )
    PROIBIDOS = (
        "n8n",
        "n8n-nodes-base",
        "@typebot.io/js",
        "minio",
        "dify-client",
    )

    def setUp(self) -> None:
        self.entries = blocklist.load_entries(BLOCKLIST)

    def _bloqueado(self, nome: str, kind: str = "npm") -> bool:
        return any(
            entry.applies_to_kind(kind) and entry.matches_name(nome, kind)
            for entry in self.entries
        )

    def test_nomes_legitimos_passam(self) -> None:
        for nome in self.LEGITIMOS:
            with self.subTest(nome=nome):
                self.assertFalse(
                    self._bloqueado(nome), f"{nome} e um pacote real e legitimo"
                )

    def test_nomes_proibidos_sao_bloqueados(self) -> None:
        for nome in self.PROIBIDOS:
            with self.subTest(nome=nome):
                self.assertTrue(self._bloqueado(nome), f"{nome} tinha de ser bloqueado")


class TestNormalizacaoPyPI(unittest.TestCase):
    """PEP 503: `langgraph_api` e `langgraph-api` instalam o mesmo pacote."""

    def setUp(self) -> None:
        # Ha duas entradas chamadas `langgraph-api`: uma `pypi`/`exact` e uma
        # `image`/`boundary`. Indexar so pelo nome apanharia a errada.
        self.entries = {
            (e.name, e.kind): e for e in blocklist.load_entries(BLOCKLIST)
        }

    def test_variantes_de_separador_batem(self) -> None:
        entry = self.entries[("langgraph-api", "pypi")]
        for variante in (
            "langgraph-api",
            "langgraph_api",
            "LangGraph.API",
            "LANGGRAPH__API",
        ):
            with self.subTest(variante=variante):
                self.assertTrue(entry.matches_name(variante, "pypi"))

    def test_nome_vizinho_nao_bate(self) -> None:
        """`langgraph` (MIT, ADR-002 manda usar) e vizinhos nao sao bloqueados.

        **O `langgraph-checkpoint-postgres` estava nesta lista e saiu.** Estava
        aqui porque o `E4` §2.6 o dava como «MIT, sem restricoes» — e o pacote
        e MIT, mas o fecho nao: exige `psycopg` e `psycopg-pool`, LGPL-3.0-only
        (KAM-026, medido contra o `requires_dist` do PyPI). Passou para o
        `test_o_saver_postgres_e_bloqueado`, abaixo. O que ficou no lugar dele
        e o `langgraph-checkpoint`, que e o que a casa usa mesmo.
        """
        entries = blocklist.load_entries(BLOCKLIST)
        for vizinho in ("langgraph", "langgraph-api-client", "langgraph-checkpoint"):
            with self.subTest(vizinho=vizinho):
                bloqueado = any(
                    e.applies_to_kind("pypi") and e.matches_name(vizinho, "pypi")
                    for e in entries
                )
                self.assertFalse(
                    bloqueado,
                    f"{vizinho} e legitimo: o ADR-002 manda usar a biblioteca MIT",
                )


class TestRepositorio(unittest.TestCase):
    def test_repositorio_esta_limpo(self) -> None:
        """O proprio monorepo passa a lista de bloqueio.

        Este teste tambem guarda a excepcao das fixtures: se ela desaparecer, as
        dependencias proibidas das fixtures aparecem aqui.
        """
        achados = check_dependencies(ROOT)
        self.assertEqual(achados, [], "\n".join(achados))

    def test_a_excepcao_das_fixtures_e_estreita(self) -> None:
        from lint_arch import manifests

        self.assertEqual(
            manifests.SKIP_PATHS,
            ("tools/lint_arch/tests/fixtures", ".claude/worktrees"),
        )
        varridos = {declaration.source for declaration in manifests.collect(ROOT)}
        # Manifestos reais que tem de continuar a ser varridos.
        for esperado in (
            "package.json",
            "services/gwy/package.json",
            "services/agr/pyproject.toml",
            "services/agr/requirements/runtime.txt",
            "services/agr/requirements/runtime.in",
            "infra/compose/docker-compose.dev.yml",
            "services/gwy/Dockerfile",
            "services/agr/Dockerfile",
            "tools/requirements/tools.txt",
        ):
            self.assertIn(esperado, varridos)


if __name__ == "__main__":
    unittest.main()
