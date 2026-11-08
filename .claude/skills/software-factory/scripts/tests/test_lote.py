"""A escolha do lote: o limite de migracoes e os componentes, sem `git` nem GitHub."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lote  # noqa: E402


def dados(prioridade: str = "P1", fase: str = "0", estimativa: str = "M") -> dict:
    return {"titulo": "x", "tipo": "feat", "estimativa": estimativa,
            "prioridade": prioridade, "fase": fase, "dependencias": set()}


def bloco(texto: str, verificacao: str = "") -> str:
    return f"## KAM-NNN — x\n\n### Contexto\n\n{texto}\n\n### Verificação dos Critérios de Aceitação\n\n{verificacao}\n"


class TestPrever(unittest.TestCase):
    def test_rls_ou_trigger_preve_migracao(self) -> None:
        self.assertTrue(lote.prever("KAM-1", dados(), bloco("a politica de RLS da tabela")).migracao)
        self.assertTrue(lote.prever("KAM-1", dados(), bloco("um trigger recusa o UPDATE")).migracao)

    def test_sem_vocabulario_de_esquema_nao_preve(self) -> None:
        self.assertFalse(lote.prever("KAM-1", dados(), bloco("um runbook operacional")).migracao)

    def test_a_seccao_de_verificacao_nao_conta(self) -> None:
        """Ela nomeia os ficheiros que mudaram, e contaminava a previsao com o passado."""
        candidato = lote.prever("KAM-1", dados(), bloco("so prosa", verificacao="RLS medido em db/"))
        self.assertFalse(candidato.migracao)
        self.assertEqual(candidato.componentes, set())

    def test_componentes(self) -> None:
        texto = "toca em `services/com/src` e `packages/core-ts` e em db/migrations"
        self.assertEqual(lote.componentes_de(texto), {"services/com", "packages/core-ts", "db"})


class TestEscolher(unittest.TestCase):
    def candidato(self, ticket: str, migracao: bool = False, componentes: set[str] | None = None,
                  prioridade: str = "P1") -> lote.Candidato:
        return lote.Candidato(ticket, dados(prioridade), migracao, componentes or set())

    def test_uma_migracao_por_lote(self) -> None:
        cs = [self.candidato("KAM-001", True), self.candidato("KAM-002", True),
              self.candidato("KAM-003")]
        escolhidos, preteridos = lote.escolher(cs, 5, migracoes_abertas=0)
        self.assertEqual([c.ticket for c in escolhidos], ["KAM-001", "KAM-003"])
        self.assertEqual([c.ticket for c in preteridos], ["KAM-002"])
        self.assertIn("no lote", preteridos[0].motivo)

    def test_zero_migracoes_com_um_pr_aberto_que_ja_tem_uma(self) -> None:
        escolhidos, preteridos = lote.escolher([self.candidato("KAM-001", True)], 5, 1)
        self.assertEqual(escolhidos, [])
        self.assertIn("PR aberto", preteridos[0].motivo)

    def test_dois_no_mesmo_componente_nao_vao_juntos(self) -> None:
        cs = [self.candidato("KAM-001", componentes={"services/com"}),
              self.candidato("KAM-002", componentes={"services/com"})]
        escolhidos, preteridos = lote.escolher(cs, 5, 0)
        self.assertEqual(len(escolhidos), 1)
        self.assertIn("services/com", preteridos[0].motivo)

    def test_a_prioridade_ordena_e_o_n_corta(self) -> None:
        cs = [self.candidato("KAM-001", prioridade="P2"), self.candidato("KAM-002", prioridade="P0"),
              self.candidato("KAM-003", prioridade="P1")]
        escolhidos, _ = lote.escolher(cs, 2, 0)
        self.assertEqual([c.ticket for c in escolhidos], ["KAM-002", "KAM-003"])


if __name__ == "__main__":
    unittest.main()
