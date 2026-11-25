"""Gate 16: dois revisores para dinheiro, seguranca e isolamento."""

from __future__ import annotations

import unittest

from release import aprovacao
from release.tests.apoio import RAIZ

CABECA = "c" * 40
ANTIGA = "d" * 40


def _revisao(quem: str, estado: str = "APPROVED", oid: str = CABECA) -> dict:
    return {"author": {"login": quem}, "state": estado, "commit": {"oid": oid}}


def _pr(*revisoes: dict, etiquetas: tuple[str, ...] = (), ficheiros: tuple[str, ...] = ("README.md",)) -> dict:
    return {
        "author": {"login": "autora"},
        "headRefOid": CABECA,
        "labels": [{"name": e} for e in etiquetas],
        "reviews": list(revisoes),
        "files": [{"path": f} for f in ficheiros],
        "changedFiles": len(ficheiros),
    }


class TestGate16(unittest.TestCase):
    def test_negativo_dinheiro_com_uma_aprovacao_nao_chega_a_prod(self) -> None:
        decisao = aprovacao.decidir_com_raiz(_pr(_revisao("ana"), etiquetas=("dinheiro",)), RAIZ)
        self.assertTrue(decisao.sensivel)
        self.assertEqual(decisao.exigidas, 2)
        self.assertFalse(decisao.passa)

    def test_dinheiro_com_duas_aprovacoes_passa(self) -> None:
        decisao = aprovacao.decidir_com_raiz(
            _pr(_revisao("ana"), _revisao("rui"), etiquetas=("dinheiro",)), RAIZ
        )
        self.assertTrue(decisao.passa)

    def test_as_tres_etiquetas_pedem_duas(self) -> None:
        for etiqueta in ("dinheiro", "seguranca", "isolamento", "Seguranca"):
            with self.subTest(etiqueta=etiqueta):
                decisao = aprovacao.decidir_com_raiz(_pr(_revisao("ana"), etiquetas=(etiqueta,)), RAIZ)
                self.assertFalse(decisao.passa)

    def test_negativo_caminho_critico_sem_etiqueta_tambem_pede_duas(self) -> None:
        # Sem etiqueta nenhuma: o caminho e que o marca, pelo estrato `critico`
        # do ci/thresholds.yaml — o mesmo do gate 4.
        decisao = aprovacao.decidir_com_raiz(
            _pr(_revisao("ana"), ficheiros=("services/pay/src/pagamentos/referencia.ts",)), RAIZ
        )
        self.assertTrue(decisao.sensivel)
        self.assertFalse(decisao.passa)

    def test_lista_de_ficheiros_truncada_conta_como_sensivel(self) -> None:
        pr = _pr(_revisao("ana"))
        pr["changedFiles"] = 300
        self.assertFalse(aprovacao.decidir_com_raiz(pr, RAIZ).passa)

    def test_sem_changed_files_conta_como_sensivel(self) -> None:
        pr = _pr(_revisao("ana"))
        del pr["changedFiles"]
        self.assertTrue(aprovacao.decidir_com_raiz(pr, RAIZ).sensivel)

    def test_o_resto_passa_com_uma(self) -> None:
        self.assertTrue(aprovacao.decidir_com_raiz(_pr(_revisao("ana")), RAIZ).passa)

    def test_sem_nenhuma_nao_passa(self) -> None:
        self.assertFalse(aprovacao.decidir_com_raiz(_pr(), RAIZ).passa)


class TestQuemAprovou(unittest.TestCase):
    def test_a_autora_nao_conta(self) -> None:
        self.assertEqual(aprovacao.aprovadores(_pr(_revisao("autora"))), ())

    def test_aprovacao_a_commit_anterior_nao_conta(self) -> None:
        self.assertEqual(aprovacao.aprovadores(_pr(_revisao("ana", oid=ANTIGA))), ())

    def test_pedido_de_alteracoes_depois_anula(self) -> None:
        pr = _pr(_revisao("ana"), _revisao("ana", "CHANGES_REQUESTED"))
        self.assertEqual(aprovacao.aprovadores(pr), ())

    def test_comentario_depois_nao_anula(self) -> None:
        pr = _pr(_revisao("ana"), _revisao("ana", "COMMENTED"))
        self.assertEqual(aprovacao.aprovadores(pr), ("ana",))

    def test_a_mesma_pessoa_duas_vezes_conta_uma(self) -> None:
        pr = _pr(_revisao("ana"), _revisao("ana"), etiquetas=("dinheiro",))
        self.assertFalse(aprovacao.decidir(pr, []).passa)


if __name__ == "__main__":
    unittest.main()
