"""Convencoes de commit e de ramo do §5 do Engineering Standards.

As regras vivem em `tools/conventions.json` e sao lidas tambem pelo
`commitlint.config.cjs`. Estes testes cobrem o lado que corre sem Node — que e o
lado que os *git hooks* usam.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from lint_arch import conventions

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
