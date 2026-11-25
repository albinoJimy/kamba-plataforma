"""Gate 18: um gate saltado no workflow exige ADR existente ou waiver."""

from __future__ import annotations

import datetime
import unittest

from release import pipeline
from release.tests.apoio import RAIZ

HOJE = datetime.date(2026, 11, 25)


def _workflow(preambulo: str, corpo: str, nome: str = "gate 5 — reservado", indent: str = "  ") -> str:
    i, j = indent, indent * 2
    return (
        "name: ci\n"
        "on: [pull_request]\n"
        "jobs:\n"
        f"{i}gate-1-build:\n"
        f'{j}name: "gate 1 — build"\n'
        f"{j}runs-on: ubuntu-latest\n"
        f"{preambulo}"
        f"{i}o-job:\n"
        f'{j}name: "{nome}"\n'
        f"{j}runs-on: ubuntu-latest\n"
        f"{corpo}"
        f"{j}steps:\n"
        f"{j}  - run: make ci-5\n"
    )


def _achados(texto: str, waivers: set[tuple[str, str]] = frozenset()) -> list[pipeline.Achado]:
    return pipeline.verificar_texto(texto, "ci.yaml", RAIZ, set(waivers))


SALTO = "    continue-on-error: true\n"


class TestFormasDeSaltar(unittest.TestCase):
    def test_negativo_continue_on_error_sem_registo_falha(self) -> None:
        achados = _achados(_workflow("", SALTO))
        self.assertEqual([(a.gate, a.job) for a in achados], [("5", "o-job")])

    def test_negativo_if_que_nao_corre_sempre(self) -> None:
        for forma in ("if: false", "if: ${{ false }}", "if: 'false'", "if: ${{ false && true }}",
                      "if: github.event_name == 'nunca'", "if: >-"):
            with self.subTest(forma=forma):
                self.assertEqual(len(_achados(_workflow("", f"    {forma}\n"))), 1)

    def test_os_ifs_que_correm_sempre_nao_sao_salto(self) -> None:
        for forma in ("if: always()", "if: ${{ !cancelled() }}", "if: success()"):
            with self.subTest(forma=forma):
                self.assertEqual(_achados(_workflow("", f"    {forma}\n")), [])

    def test_negativo_num_passo_tambem(self) -> None:
        corpo = "    steps:\n      - run: x\n        continue-on-error: true\n"
        self.assertEqual(len(_achados(_workflow("", corpo))), 1)

    def test_negativo_allow_failure_e_chave_entre_aspas(self) -> None:
        for corpo in ("    allow_failure: true\n", '    "continue-on-error": true\n'):
            with self.subTest(corpo=corpo):
                self.assertEqual(len(_achados(_workflow("", corpo))), 1)

    def test_expressao_conta_como_salto(self) -> None:
        corpo = "    continue-on-error: ${{ matrix.experimental }}\n"
        self.assertEqual(len(_achados(_workflow("", corpo))), 1)

    def test_continue_on_error_false_nao_e_salto(self) -> None:
        self.assertEqual(_achados(_workflow("", "    continue-on-error: false\n")), [])

    def test_jobs_a_quatro_espacos(self) -> None:
        texto = _workflow("", "        continue-on-error: true\n", indent="    ")
        self.assertEqual(len(_achados(texto)), 1)

    def test_jobs_com_comentario_na_linha(self) -> None:
        texto = _workflow("", SALTO).replace("jobs:\n", "jobs:  # os gates\n")
        self.assertEqual(len(_achados(texto)), 1)

    def test_job_em_fluxo_e_ilegivel(self) -> None:
        texto = "jobs:\n  g: {name: gate 14, continue-on-error: true}\n"
        self.assertEqual(len(_achados(texto)), 1)

    def test_passo_em_fluxo_e_ilegivel(self) -> None:
        corpo = "    steps:\n      - {run: x, continue-on-error: true}\n"
        self.assertEqual(len(_achados(_workflow("", corpo))), 1)

    def test_nome_em_bloco_e_ilegivel(self) -> None:
        texto = "jobs:\n  g:\n    name: >-\n      gate 14\n    continue-on-error: true\n"
        self.assertEqual(len(_achados(texto)), 1)

    def test_gate_no_meio_do_nome_ou_na_chave(self) -> None:
        self.assertEqual(len(_achados(_workflow("", SALTO, nome="[gate 14] imagem"))), 1)
        texto = "jobs:\n  gate-16-aprovacao:\n    name: aprovacao\n    continue-on-error: true\n"
        self.assertEqual(_achados(texto)[0].gate, "16")

    def test_job_que_nao_e_gate_nao_entra(self) -> None:
        self.assertEqual(_achados(_workflow("", SALTO, nome="vigia — prova nocturna")), [])

    def test_gate_3b_e_lido(self) -> None:
        self.assertEqual(_achados(_workflow("", SALTO, nome="gate 3b — nomes canonicos"))[0].gate, "3b")


class TestRegisto(unittest.TestCase):
    def test_adr_local_que_existe_no_preambulo_basta(self) -> None:
        preambulo = "  # Nao bloqueia, por decisao do fundador (ADR-L012).\n"
        self.assertEqual(_achados(_workflow(preambulo, SALTO)), [])

    def test_adr_local_que_nao_existe_nao_basta(self) -> None:
        self.assertEqual(len(_achados(_workflow("  # Nao bloqueia (ADR-L999).\n", SALTO))), 1)

    def test_adr_canonico_que_existe_basta(self) -> None:
        self.assertEqual(_achados(_workflow("  # Ver ADR-005.\n", SALTO)), [])

    def test_adr_colado_a_outra_palavra_nao_conta(self) -> None:
        # O segundo monta-se por partes: escrito inteiro, o lint_refs le-o como
        # uma referencia a um ADR que nao existe.
        for preambulo in ("  # sem-ADR-005\n", "  # ADR-" + "0050\n", "  # XADR-L012\n"):
            with self.subTest(preambulo=preambulo):
                self.assertEqual(len(_achados(_workflow(preambulo, SALTO))), 1)

    def test_aprovacao_solta_nao_conta(self) -> None:
        # So no ci/waivers.yaml, com prazo e autor (achado da revisao).
        for preambulo in ("  # aprovacao:fundador@2026-11-20\n", "  # aprovacao:ninguem@1900-01-01\n"):
            with self.subTest(preambulo=preambulo):
                self.assertEqual(len(_achados(_workflow(preambulo, SALTO))), 1)

    def test_comentario_de_linha_inteira_dentro_do_job_conta(self) -> None:
        corpo = "    # ADR-L012\n" + SALTO
        self.assertEqual(_achados(_workflow("", corpo)), [])

    def test_cardinal_dentro_de_um_run_nao_e_comentario(self) -> None:
        corpo = SALTO + "    steps:\n      - run: echo '#ADR-001'\n"
        self.assertEqual(len(_achados(_workflow("", corpo))), 1)

    def test_comentario_no_fim_da_linha_nao_conta(self) -> None:
        self.assertEqual(len(_achados(_workflow("", "    continue-on-error: true  # ADR-L012\n"))), 1)

    def test_mencao_aos_waivers_em_prosa_nao_conta(self) -> None:
        preambulo = "  # A valvula formal e `ci/waivers.yaml`, com prazo de 30 dias.\n"
        self.assertEqual(len(_achados(_workflow(preambulo, SALTO))), 1)

    def test_waiver_do_gate_para_o_job_basta(self) -> None:
        texto = _workflow("", SALTO)
        self.assertEqual(_achados(texto, {("5", "o-job")}), [])
        self.assertEqual(len(_achados(texto, {("5", "outro-job")})), 1)
        self.assertEqual(len(_achados(texto, {("6", "o-job")})), 1)

    def test_o_preambulo_de_um_job_nao_vale_para_o_seguinte(self) -> None:
        texto = (
            "jobs:\n"
            "  # ADR-L012\n"
            "  a:\n"
            '    name: "gate 13 — a"\n'
            "    continue-on-error: true\n"
            "  b:\n"
            '    name: "gate 13 — b"\n'
            "    continue-on-error: true\n"
        )
        self.assertEqual([a.job for a in _achados(texto)], ["b"])

    def test_comentario_na_coluna_dos_jobs_a_meio_e_do_job_de_cima(self) -> None:
        # Entre o `steps:` e o primeiro passo do *job* a, a dois espacos: e do a,
        # e nao regista o gate 16 saltado que vem a seguir (achado da revisao).
        texto = (
            "jobs:\n"
            "  a:\n"
            '    name: "gate 1 — a"\n'
            "    steps:\n"
            "  # ADR-005\n"
            "      - run: x\n"
            "  b:\n"
            '    name: "gate 16 — b"\n'
            "    continue-on-error: true\n"
        )
        self.assertEqual([a.job for a in _achados(texto)], ["b"])


class TestContraOsWorkflowsReais(unittest.TestCase):
    """Medicao, e nao oraculo: o achado de hoje (o gate 5) esta no bloco do
    KAM-078 e muda quando o fundador decidir; aqui so se prende que o gate 13,
    que tem o ADR-L012, nao aparece, e que nenhum *workflow* e ilegivel."""

    def test_o_gate_13_passa_pelo_adr_l012_e_tudo_se_le(self) -> None:
        achados = pipeline.verificar(RAIZ, HOJE)
        self.assertNotIn("gate-13-pesquisa", [a.job for a in achados])
        self.assertNotIn("?", [a.gate for a in achados])


if __name__ == "__main__":
    unittest.main()
