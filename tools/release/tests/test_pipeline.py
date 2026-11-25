"""Gate 18: um gate saltado no workflow exige ADR, aprovacao ou waiver."""

from __future__ import annotations

import datetime
import unittest

from release import pipeline
from release.tests.apoio import RAIZ

HOJE = datetime.date(2026, 11, 25)


def _workflow(preambulo: str, corpo: str, nome: str = "gate 5 — reservado") -> str:
    return (
        "name: ci\n"
        "on: [pull_request]\n"
        "jobs:\n"
        "  gate-1-build:\n"
        '    name: "gate 1 — build"\n'
        "    runs-on: ubuntu-latest\n"
        f"{preambulo}"
        "  o-job:\n"
        f'    name: "{nome}"\n'
        "    runs-on: ubuntu-latest\n"
        f"{corpo}"
        "    steps:\n"
        "      - run: make ci-5\n"
    )


def _achados(texto: str, waivers: set[tuple[str, str]] = frozenset()) -> list[pipeline.Achado]:
    return pipeline.verificar_texto(texto, "ci.yaml", RAIZ, set(waivers), HOJE)


class TestLintDoPipeline(unittest.TestCase):
    def test_negativo_continue_on_error_sem_registo_falha(self) -> None:
        achados = _achados(_workflow("", "    continue-on-error: true\n"))
        self.assertEqual(len(achados), 1)
        self.assertEqual((achados[0].gate, achados[0].job), ("5", "o-job"))

    def test_negativo_if_false_sem_registo_falha(self) -> None:
        for forma in ("if: false", "if: ${{ false }}"):
            with self.subTest(forma=forma):
                self.assertEqual(len(_achados(_workflow("", f"    {forma}\n"))), 1)

    def test_negativo_num_passo_tambem(self) -> None:
        corpo = "    steps:\n      - run: x\n        continue-on-error: true\n"
        self.assertEqual(len(_achados(_workflow("", corpo))), 1)

    def test_negativo_allow_failure_tambem(self) -> None:
        self.assertEqual(len(_achados(_workflow("", "    allow_failure: true\n"))), 1)

    def test_expressao_conta_como_salto(self) -> None:
        corpo = "    continue-on-error: ${{ matrix.experimental }}\n"
        self.assertEqual(len(_achados(_workflow("", corpo))), 1)

    def test_continue_on_error_false_nao_e_salto(self) -> None:
        self.assertEqual(_achados(_workflow("", "    continue-on-error: false\n")), [])

    def test_adr_local_que_existe_no_preambulo_basta(self) -> None:
        preambulo = "  # Nao bloqueia, por decisao do fundador (ADR-L012).\n"
        self.assertEqual(_achados(_workflow(preambulo, "    continue-on-error: true\n")), [])

    def test_adr_local_que_nao_existe_nao_basta(self) -> None:
        preambulo = "  # Nao bloqueia (ADR-L999).\n"
        self.assertEqual(len(_achados(_workflow(preambulo, "    continue-on-error: true\n"))), 1)

    def test_adr_canonico_que_existe_basta(self) -> None:
        preambulo = "  # Ver ADR-005.\n"
        self.assertEqual(_achados(_workflow(preambulo, "    continue-on-error: true\n")), [])

    def test_aprovacao_datada_basta_e_futura_nao(self) -> None:
        passada = "  # aprovacao:fundador@2026-11-20\n"
        futura = "  # aprovacao:fundador@2026-12-20\n"
        self.assertEqual(_achados(_workflow(passada, "    continue-on-error: true\n")), [])
        self.assertEqual(len(_achados(_workflow(futura, "    continue-on-error: true\n"))), 1)

    def test_comentario_dentro_do_job_tambem_conta(self) -> None:
        corpo = "    continue-on-error: true  # ADR-L012\n"
        self.assertEqual(_achados(_workflow("", corpo)), [])

    def test_mencao_aos_waivers_em_prosa_nao_conta(self) -> None:
        preambulo = "  # A valvula formal e `ci/waivers.yaml`, com prazo de 30 dias.\n"
        self.assertEqual(len(_achados(_workflow(preambulo, "    continue-on-error: true\n"))), 1)

    def test_waiver_do_gate_para_o_job_basta(self) -> None:
        texto = _workflow("", "    continue-on-error: true\n")
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
        achados = _achados(texto)
        self.assertEqual([a.job for a in achados], ["b"])

    def test_job_que_nao_e_gate_nao_entra(self) -> None:
        texto = _workflow("", "    continue-on-error: true\n", nome="vigia — prova nocturna")
        self.assertEqual(_achados(texto), [])

    def test_gate_3b_e_lido(self) -> None:
        texto = _workflow("", "    continue-on-error: true\n", nome="gate 3b — nomes canonicos")
        self.assertEqual(_achados(texto)[0].gate, "3b")


class TestContraOsWorkflowsReais(unittest.TestCase):
    """Medicao, e nao oraculo: o numero esta no bloco do KAM-078."""

    def test_o_gate_13_passa_pelo_adr_l012(self) -> None:
        achados = pipeline.verificar(RAIZ, HOJE)
        self.assertNotIn("gate-13-pesquisa", [a.job for a in achados])


if __name__ == "__main__":
    unittest.main()
