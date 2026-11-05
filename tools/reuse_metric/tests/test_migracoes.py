"""A cadeia do Alembic: quais migracoes estao debaixo da vertical (KAM-039).

As migracoes sao o unico termo do §5.4 sem grafo de importacao, e a primeira
versao deste ticket contou-as mal: as da vertical entravam no numerador e as de
`platform` sobre as quais elas correm nao entravam no denominador. Esta bateria
fixa a correccao — a cadeia le-se do `down_revision`, e as duas pontas entram
juntas.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reuse_metric.migracoes import CadeiaInvalidaError, antepassados, ler_revisoes


class _ComPasta(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pasta = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def migracao(self, nome: str, revisao: str, anterior: str | None) -> None:
        anterior_py = "None" if anterior is None else f'"{anterior}"'
        (self.pasta / nome).write_text(
            f'"""Prosa."""\nrevision = "{revisao}"\ndown_revision = {anterior_py}\n',
            encoding="utf-8",
        )

    def cadeia_linear(self, quantas: int) -> None:
        anterior = None
        for n in range(1, quantas + 1):
            revisao = f"{n:04d}"
            self.migracao(f"{revisao}_r.py", revisao, anterior)
            anterior = revisao


class TestLerRevisoes(_ComPasta):
    def test_le_a_revisao_e_a_anterior(self) -> None:
        self.cadeia_linear(3)
        revisoes = ler_revisoes(self.pasta)
        self.assertEqual([r.revisao for r in revisoes], ["0001", "0002", "0003"])
        self.assertEqual([r.anterior for r in revisoes], [None, "0001", "0002"])

    def test_pasta_que_nao_existe_levanta(self) -> None:
        with self.assertRaises(CadeiaInvalidaError):
            ler_revisoes(self.pasta / "nao_existe")

    def test_migracao_sem_revision_levanta(self) -> None:
        (self.pasta / "0001_x.py").write_text("x = 1\n", encoding="utf-8")
        with self.assertRaises(CadeiaInvalidaError):
            ler_revisoes(self.pasta)

    def test_nao_importa_a_migracao_para_a_ler(self) -> None:
        """Uma migracao do Alembic importa o `op` e o `sa` ao nivel do modulo.

        Le-se por AST: importa-la era correr codigo de terceiros para responder
        a uma pergunta de contagem.
        """
        (self.pasta / "0001_x.py").write_text(
            "import modulo_que_nao_existe_em_lado_nenhum\n"
            'revision = "0001"\ndown_revision = None\n',
            encoding="utf-8",
        )
        self.assertEqual(ler_revisoes(self.pasta)[0].revisao, "0001")


class TestAntepassados(_ComPasta):
    def test_a_cadeia_sobe_ate_a_raiz_e_nao_inclui_a_semente(self) -> None:
        self.cadeia_linear(5)
        cadeia = antepassados(ler_revisoes(self.pasta), ("0003_r.py",))
        self.assertEqual([r.revisao for r in cadeia], ["0001", "0002"])

    def test_o_que_vem_DEPOIS_fica_de_fora(self) -> None:
        """No repositorio verdadeiro sao a `0027` a `0031`: pagamentos e
        encomendas. Uma marcacao nao corre sobre elas."""
        self.cadeia_linear(5)
        cadeia = antepassados(ler_revisoes(self.pasta), ("0003_r.py",))
        self.assertNotIn("0004", [r.revisao for r in cadeia])
        self.assertNotIn("0005", [r.revisao for r in cadeia])

    def test_uma_semente_antepassada_de_outra_nao_entra_no_partilhado(self) -> None:
        """E o caso da `0025` e da `0026`: as duas sao da vertical.

        Sem esta regra, a `0025` aparecia nas duas classes e as suas 368 linhas
        contavam ao mesmo tempo no numerador e no denominador.
        """
        self.cadeia_linear(5)
        cadeia = antepassados(ler_revisoes(self.pasta), ("0002_r.py", "0003_r.py"))
        self.assertEqual([r.revisao for r in cadeia], ["0001"])

    def test_semente_que_nao_existe_levanta(self) -> None:
        """Uma declaracao a apontar para o vazio encolhia o denominador calada."""
        self.cadeia_linear(3)
        with self.assertRaises(CadeiaInvalidaError):
            antepassados(ler_revisoes(self.pasta), ("9999_fantasma.py",))

    def test_cadeia_partida_levanta(self) -> None:
        self.migracao("0001_r.py", "0001", "nao_existe")
        with self.assertRaises(CadeiaInvalidaError) as erro:
            antepassados(ler_revisoes(self.pasta), ("0001_r.py",))
        self.assertIn("cadeia esta partida", str(erro.exception))

    def test_a_linearidade_nao_esta_assumida(self) -> None:
        """Hoje a cadeia e linear; o codigo nao pode depender disso.

        Duas sementes em ramos diferentes tem de dar a uniao dos antepassados,
        senao o dia em que a cadeia se bifurcar da o numero errado em silencio.
        """
        self.migracao("0001_base.py", "0001", None)
        self.migracao("0002_a.py", "0002", "0001")
        self.migracao("0003_b.py", "0003", "0001")
        self.migracao("0004_folha_a.py", "0004", "0002")
        self.migracao("0005_folha_b.py", "0005", "0003")
        cadeia = antepassados(
            ler_revisoes(self.pasta), ("0004_folha_a.py", "0005_folha_b.py")
        )
        self.assertEqual([r.revisao for r in cadeia], ["0001", "0002", "0003"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
