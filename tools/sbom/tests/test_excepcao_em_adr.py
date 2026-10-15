"""Uma licenca proibida so entra com excepcao registada em ADR (KAM-067, criterio 6).

O esquema de `ci/waivers.yaml` aceita `ADR-NNN` e `aprovacao:<quem>@<data>`. Para
os outros gates as duas servem. Para uma licenca **proibida** (AGPL, BUSL,
Elastic, SSPL, FSL, SUL) o criterio pede ADR, e ate ao KAM-067 uma aprovacao
datada chegava.
"""

from __future__ import annotations

import datetime
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from sbom.cli import verificar_licencas

ROOT = Path(__file__).resolve().parents[3]


class TestExcepcaoEmADR(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="kamba-adr-")
        self.addCleanup(self._tmp.cleanup)
        self.raiz = Path(self._tmp.name)
        (self.raiz / "ci").mkdir()
        shutil.copyfile(ROOT / "ci" / "licenses.yaml", self.raiz / "ci" / "licenses.yaml")
        # As duas fontes dos ADR: a excepcao tem de citar um que exista.
        for ficheiro in ("docs/tecnica/00_Arquitectura_Solucao.md", "docs/adr/ADR-L001-toolchain.md"):
            (self.raiz / ficheiro).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / ficheiro, self.raiz / ficheiro)
        self.expira = (datetime.date.today() + datetime.timedelta(days=10)).isoformat()

    def instalar(self, nome: str, licenca: str | None) -> None:
        pasta = self.raiz / "node_modules" / ".pnpm" / f"{nome}@1.0.0" / "node_modules" / nome
        pasta.mkdir(parents=True)
        manifesto = {"name": nome, "version": "1.0.0"}
        if licenca is not None:
            manifesto["license"] = licenca
        (pasta / "package.json").write_text(json.dumps(manifesto), encoding="utf-8")

    def waiver(self, alvo: str, referencia: str | None) -> None:
        if referencia is None:
            texto = "version: 1\nwaivers: []\n"
        else:
            texto = (
                "version: 1\nwaivers:\n"
                "  - gate: 11\n"
                f"    alvo: \"{alvo}\"\n"
                f"    adr_ou_aprovacao: \"{referencia}\"\n"
                "    autor: teste\n"
                "    razao: Uma razao com mais de quarenta caracteres, para o validador a aceitar.\n"
                f"    expira_em: \"{self.expira}\"\n"
            )
        (self.raiz / "ci" / "waivers.yaml").write_text(texto, encoding="utf-8")

    def test_sem_waiver_a_licenca_proibida_falha(self) -> None:
        self.instalar("proibido", "BUSL-1.1")
        self.waiver("", None)
        achados, _ = verificar_licencas(self.raiz)
        self.assertEqual(len(achados), 1)
        self.assertIn("licenca proibida", achados[0])

    def test_cada_familia_proibida_com_aprovacao_datada_continua_a_falhar(self) -> None:
        for licenca in (
            "AGPL-3.0", "BUSL-1.1", "Elastic-2.0", "SSPL-1.0", "FSL-1.1-Apache-2.0",
            "SUL-1.0", "MIT AND BUSL-1.1",
        ):
            with self.subTest(licenca=licenca):
                shutil.rmtree(self.raiz / "node_modules", ignore_errors=True)
                self.instalar("proibido", licenca)
                self.waiver("pkg:npm/proibido@1.0.0", "aprovacao:fundador@2026-10-12")
                achados, estatisticas = verificar_licencas(self.raiz)
                self.assertEqual(len(achados), 1, achados)
                self.assertIn("nao cita um ADR", achados[0])
                self.assertEqual(estatisticas["contagem"]["permitida"], 0)

    def test_com_adr_a_excepcao_vale(self) -> None:
        for referencia in ("ADR-014", "ADR-L001"):
            with self.subTest(referencia=referencia):
                shutil.rmtree(self.raiz / "node_modules", ignore_errors=True)
                self.instalar("proibido", "AGPL-3.0")
                self.waiver("pkg:npm/proibido@1.0.0", referencia)
                achados, estatisticas = verificar_licencas(self.raiz)
                self.assertEqual(achados, [])
                self.assertEqual(estatisticas["contagem"]["permitida"], 1)

    def test_adr_que_nao_existe_nao_vale(self) -> None:
        """Achado M2 da revisao: `startswith("ADR-")` aceitava um ADR inventado."""
        # Escritos aos pedacos: por extenso, o gate 3 lia-os como referencias invalidas.
        for referencia in ("ADR-" + "999", "ADR-L" + "999", "ADR-" + "021"):
            with self.subTest(referencia=referencia):
                shutil.rmtree(self.raiz / "node_modules", ignore_errors=True)
                self.instalar("proibido", "BUSL-1.1")
                self.waiver("pkg:npm/proibido@1.0.0", referencia)
                achados, estatisticas = verificar_licencas(self.raiz)
                self.assertEqual(len(achados), 1, achados)
                self.assertIn("cita um ADR que nao existe", achados[0])
                self.assertEqual(estatisticas["contagem"]["permitida"], 0)

    def test_sem_as_fontes_dos_adr_nenhuma_excepcao_vale(self) -> None:
        """Fail-closed: se nao se consegue ler a tabela dos ADR, nenhum existe."""
        shutil.rmtree(self.raiz / "docs")
        self.instalar("proibido", "AGPL-3.0")
        self.waiver("pkg:npm/proibido@1.0.0", "ADR-014")
        achados, _ = verificar_licencas(self.raiz)
        self.assertEqual(len(achados), 1)

    def test_o_indice_le_as_duas_fontes(self) -> None:
        from sbom import adr

        existentes = adr.existentes(ROOT)
        self.assertEqual(len([a for a in existentes if not a.startswith("ADR-L")]), 20)
        self.assertIn("ADR-L001", existentes)
        self.assertNotIn("ADR-" + "999", existentes)
        self.assertEqual(adr.existentes(self.raiz / "nao-existe"), frozenset())

    def test_licenca_por_determinar_continua_a_aceitar_aprovacao(self) -> None:
        """So as **proibidas** exigem ADR: «nao sei que licenca e» resolve-se lendo-a,
        e quem a leu assina — e o que `ci/licenses.yaml` descreve."""
        self.instalar("misterio", None)
        self.waiver("pkg:npm/misterio@1.0.0", "aprovacao:fundador@2026-10-12")
        achados, _ = verificar_licencas(self.raiz)
        self.assertEqual(achados, [])


if __name__ == "__main__":
    unittest.main()
