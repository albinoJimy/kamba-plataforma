"""Gate 14: os dois testes negativos do criterio, e os outros cinco modos de falhar."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from release import imagem
from release.lock import Entrada, Lock
from release.tests.apoio import COMMIT, lock_com

CHAVE = imagem.Assinatura(chave="cosign.pub")


def _cosign_aceita(comando: list[str]) -> tuple[int, str]:
    return 0, "ok"


def _cosign_recusa(comando: list[str]) -> tuple[int, str]:
    return 1, "no matching signatures"


def _cosign_ausente(comando: list[str]) -> tuple[int, str]:
    return 127, "cosign: binario ausente"


class _Artefactos:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)

    def sbom(self, servico: str, componentes: int = 1, formato: str = "CycloneDX") -> None:
        corpo = {"bomFormat": formato, "components": [{"name": f"c{i}"} for i in range(componentes)]}
        (self.pasta / f"{servico}.sbom.json").write_text(json.dumps(corpo), encoding="utf-8")

    def vulns(self, servico: str, *vulns: tuple[str, str], sem_chave: bool = False) -> None:
        corpo: dict = {"bomFormat": "CycloneDX"}
        if not sem_chave:
            corpo["vulnerabilities"] = [
                {"id": vid, "ratings": [{"severity": sev}]} for vid, sev in vulns
            ]
        (self.pasta / f"{servico}.vulns.json").write_text(json.dumps(corpo), encoding="utf-8")

    def limpar(self) -> None:
        self._tmp.cleanup()


class TestGate14(unittest.TestCase):
    def setUp(self) -> None:
        self.art = _Artefactos()
        self.addCleanup(self.art.limpar)
        self.lock = lock_com(gwy=("a", "build"), postgres=("b", "terceiros"))
        self.art.sbom("gwy")
        self.art.vulns("gwy", ("CVE-0000-0001", "high"))

    def regras(self, achados: list[imagem.Achado]) -> list[str]:
        return [a.regra for a in achados]

    def test_tudo_em_ordem_passa(self) -> None:
        self.assertEqual(imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), _cosign_aceita), [])

    # --- os dois testes negativos do criterio --------------------------------

    def test_negativo_imagem_sem_assinatura_verificada_falha(self) -> None:
        achados = imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), _cosign_recusa)
        self.assertEqual(self.regras(achados), ["cosign-recusou"])

    def test_negativo_critica_sem_excepcao_registada_falha(self) -> None:
        self.art.vulns("gwy", ("CVE-0000-0002", "Critical"))
        achados = imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), _cosign_aceita)
        self.assertEqual(self.regras(achados), ["critica-sem-excepcao"])
        self.assertIn("CVE-0000-0002", str(achados[0]))

    # --- o resto -------------------------------------------------------------

    def test_critica_com_waiver_do_gate_14_passa(self) -> None:
        self.art.vulns("gwy", ("CVE-0000-0002", "critical"))
        achados = imagem.verificar(
            self.lock, self.art.pasta, CHAVE, {"CVE-0000-0002"}, _cosign_aceita
        )
        self.assertEqual(achados, [])

    def test_sem_digest_falha_e_nao_chama_o_cosign(self) -> None:
        chamadas: list[list[str]] = []

        def regista(comando: list[str]) -> tuple[int, str]:
            chamadas.append(comando)
            return 0, ""

        sem = Lock(COMMIT, {"gwy": Entrada("registo.exemplo/gwy:1.0", "build")})
        achados = imagem.verificar(sem, self.art.pasta, CHAVE, set(), regista)
        self.assertEqual(self.regras(achados), ["sem-digest"])
        self.assertEqual(chamadas, [])

    def test_sem_sbom_falha(self) -> None:
        (self.art.pasta / "gwy.sbom.json").unlink()
        self.assertEqual(
            self.regras(imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), _cosign_aceita)),
            ["sem-sbom"],
        )

    def test_sbom_vazio_falha(self) -> None:
        self.art.sbom("gwy", componentes=0)
        self.assertEqual(
            self.regras(imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), _cosign_aceita)),
            ["sbom-vazio"],
        )

    def test_sbom_noutro_formato_falha(self) -> None:
        self.art.sbom("gwy", formato="SPDX")
        self.assertIn(
            "sem-sbom",
            self.regras(imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), _cosign_aceita)),
        )

    def test_varrimento_sem_a_chave_falha(self) -> None:
        self.art.vulns("gwy", sem_chave=True)
        self.assertEqual(
            self.regras(imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), _cosign_aceita)),
            ["sem-varrimento"],
        )

    def test_cosign_ausente_falha_e_nao_salta(self) -> None:
        self.assertEqual(
            self.regras(imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), _cosign_ausente)),
            ["cosign-sem-binario"],
        )

    def test_o_executor_real_sem_binario_devolve_127(self) -> None:
        codigo, _ = imagem.executar(["kamba-binario-que-nao-existe", "verify"])
        self.assertEqual(codigo, 127)

    def test_lock_que_esconde_um_build_como_terceiros_falha(self) -> None:
        escondido = lock_com(gwy=("a", "terceiros"))
        achados = imagem.verificar(
            escondido, self.art.pasta, CHAVE, set(), _cosign_aceita,
            construidos_no_compose={"gwy"},
        )
        self.assertEqual(self.regras(achados), ["origem-trocada"])

    def test_imagens_de_terceiros_nao_passam_por_aqui(self) -> None:
        chamadas: list[str] = []

        def regista(comando: list[str]) -> tuple[int, str]:
            chamadas.append(comando[-1])
            return 0, ""

        imagem.verificar(self.lock, self.art.pasta, CHAVE, set(), regista)
        self.assertEqual(len(chamadas), 1)
        self.assertIn("/gwy@", chamadas[0])


class TestAssinatura(unittest.TestCase):
    def test_verifica_o_digest_com_chave(self) -> None:
        self.assertEqual(
            CHAVE.comando("r/gwy@sha256:x"), ["cosign", "verify", "--key", "cosign.pub", "r/gwy@sha256:x"]
        )

    def test_keyless_leva_identidade_e_emissor(self) -> None:
        a = imagem.Assinatura(identidade="https://exemplo/wf", emissor=imagem.EMISSOR_DAS_ACTIONS)
        comando = a.comando("r@sha256:x")
        self.assertIn("--certificate-identity", comando)
        self.assertIn(imagem.EMISSOR_DAS_ACTIONS, comando)

    def test_exactamente_uma_forma(self) -> None:
        for errada in (
            {},
            {"chave": "k", "identidade": "i", "emissor": "e"},
            {"identidade": "i"},
        ):
            with self.subTest(errada=errada), self.assertRaises(ValueError):
                imagem.Assinatura(**errada)


class TestCriticas(unittest.TestCase):
    def test_qualquer_rating_critico_conta(self) -> None:
        varrimento = {"vulnerabilities": [
            {"id": "A", "ratings": [{"severity": "low"}, {"severity": "critical"}]},
            {"id": "B", "ratings": [{"severity": "high"}]},
            {"id": "C"},
        ]}
        self.assertEqual(imagem.criticas(varrimento), ["A"])


if __name__ == "__main__":
    unittest.main()
