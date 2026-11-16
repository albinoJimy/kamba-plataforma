"""Os modulos de entrada: uso, orcamento e a guarda da imagem (KAM-124, criterio 7).

Sem base: o SQL corre contra a base no `db/tests/test_modulos_custo_schema.py`.
Aqui prova-se o que fica do lado Python — a leitura do orcamento (falha
fechada), o `get_usage`, a mensagem estatica sem precos, e que **nenhum
trabalho de imagem nasce acima do orcamento** com o servico inteiro por cima.
"""

from __future__ import annotations

import datetime as dt
import json
import unittest
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from test_foto import A, B, jpeg, montar

from kamba_core.foto.orcamento import OrcamentoSobreBase, QuotaComOrcamento
from kamba_core.foto.servico import Consumo
from kamba_core.modulos import (
    CHAVE_DE_USO,
    MODULOS_DE_ENTRADA,
    SQL_GASTO_DO_MES,
    SQL_USO,
    Gasto,
    UsoDoModulo,
    gasto_do_mes,
    get_usage,
    mensagem_orcamento_esgotado,
)
from kamba_core.modulos.uso import ModuloDesconhecido
from kamba_core.ten.entitlements import Resultado

RAIZ = Path(__file__).resolve().parents[3]
MAIO = dt.date(2026, 5, 1)
DEZEMBRO = dt.date(2026, 12, 1)


@dataclass
class BdFalsa:
    """Responde por SQL: o gasto de cada modulo e as linhas do uso."""

    gastos: dict[str, dict] = field(default_factory=dict)
    uso: list[dict] = field(default_factory=list)
    chamadas: list[tuple[str, tuple]] = field(default_factory=list)

    def executar(self, sql: str, parametros=()):  # type: ignore[no-untyped-def]
        self.chamadas.append((sql, tuple(parametros)))
        if sql == SQL_GASTO_DO_MES:
            linha = self.gastos.get(parametros[1])
            return Resultado(linhas=[] if linha is None else [linha])
        if sql == SQL_USO:
            return Resultado(linhas=self.uso)
        raise AssertionError(f"SQL inesperado: {sql[:40]}")


class TestRegisto(unittest.TestCase):
    def test_os_quatro_modulos_sao_os_do_registo_e_do_plans(self) -> None:
        esquema = json.loads((RAIZ / "registry" / "entitlement_keys.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(tuple(esquema["$defs"]["modulo_de_entrada"]["enum"]), MODULOS_DE_ENTRADA)
        self.assertEqual(MODULOS_DE_ENTRADA, ("catalogo", "foto", "social", "orcamento"))
        # Os contadores sao chaves do registo, e consumiveis.
        for modulo, chave in CHAVE_DE_USO.items():
            with self.subTest(modulo=modulo):
                self.assertIn(modulo, MODULOS_DE_ENTRADA)
                self.assertTrue(esquema["properties"][chave]["x-kamba-consumivel"])
        orcamento = esquema["properties"]["custo_max_mes_micro_usd"]
        self.assertEqual((orcamento["x-kamba-categoria"], orcamento["x-kamba-consumivel"]),
                         ("tecto_por_janela", False))


class TestGasto(unittest.TestCase):
    def _gasto(self, linha: dict | None, modulo: str = "foto") -> Gasto:
        return gasto_do_mes(BdFalsa(gastos={} if linha is None else {modulo: linha}), A, modulo)

    def test_le_o_orcamento_e_o_gasto_com_os_parametros_pela_ordem(self) -> None:
        bd = BdFalsa(gastos={"foto": {"orcamento": 4_000_000, "gasto_usd": Decimal("1.5")}})
        gasto = gasto_do_mes(bd, A, "foto")
        self.assertEqual(bd.chamadas, [(SQL_GASTO_DO_MES, (A, "foto", A, "foto", A, "foto"))])
        self.assertEqual((gasto.orcamento_micro_usd, gasto.gasto_usd), (4_000_000, Decimal("1.5")))
        self.assertEqual((gasto.esgotado, gasto.motivo, gasto.percentagem), (False, None, 37))

    def test_no_tecto_esta_esgotado(self) -> None:
        gasto = self._gasto({"orcamento": 1_500_000, "gasto_usd": "1.5"})
        self.assertEqual((gasto.esgotado, gasto.motivo, gasto.percentagem), (True, "orcamento_esgotado", 100))
        um_abaixo = self._gasto({"orcamento": 1_500_001, "gasto_usd": "1.5"})
        self.assertFalse(um_abaixo.esgotado)

    def test_sem_orcamento_ou_ilegivel_esta_esgotado(self) -> None:
        """Falha fechada: «sem orcamento» nao e «sem limite»."""
        for valor in (None, True, 7.0, -1, "4000000", {"x": 1}):
            with self.subTest(valor=valor):
                gasto = self._gasto({"orcamento": valor, "gasto_usd": 0})
                self.assertEqual((gasto.esgotado, gasto.motivo, gasto.percentagem), (True, "sem_orcamento", None))
        sem_linha = self._gasto(None)
        self.assertEqual((sem_linha.esgotado, sem_linha.motivo), (True, "sem_orcamento"))

    def test_orcamento_zero_esta_esgotado(self) -> None:
        gasto = self._gasto({"orcamento": 0, "gasto_usd": 0})
        self.assertEqual((gasto.esgotado, gasto.motivo, gasto.percentagem), (True, "orcamento_esgotado", None))

    def test_gasto_ilegivel_levanta(self) -> None:
        for valor in ("abc", "-1", "NaN", None):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                self._gasto({"orcamento": 1, "gasto_usd": valor})

    def test_modulo_que_nao_e_de_entrada_e_recusado(self) -> None:
        for modulo in ("vendedor", "Foto", None):
            with self.subTest(modulo=modulo), self.assertRaises(ModuloDesconhecido):
                gasto_do_mes(BdFalsa(), A, modulo)

    def test_o_tenant_e_canonico(self) -> None:
        with self.assertRaises(ValueError):
            gasto_do_mes(BdFalsa(), "nao-e-um-uuid", "foto")


class TestGetUsage(unittest.TestCase):
    def test_os_modulos_activos_com_contador_limite_e_gasto(self) -> None:
        bd = BdFalsa(
            gastos={
                "catalogo": {"orcamento": 4_000_000, "gasto_usd": Decimal("0.2")},
                "foto": {"orcamento": 4_000_000, "gasto_usd": Decimal("4")},
            },
            uso=[
                {"modulo": "catalogo", "limites": {"custo_max_mes_micro_usd": 4_000_000}, "periodo": MAIO, "usado": None},
                {"modulo": "foto", "limites": {"imagens_mes": 40}, "periodo": MAIO, "usado": 40},
            ],
        )
        catalogo, foto = get_usage(bd, A)
        self.assertEqual(bd.chamadas[0], (SQL_USO, (A,)))
        self.assertEqual((catalogo.chave, catalogo.usado, catalogo.limite), (None, None, None))
        self.assertEqual((foto.chave, foto.usado, foto.limite, foto.periodo), ("imagens_mes", 40, 40, MAIO))
        self.assertTrue(foto.gasto.esgotado)
        self.assertFalse(catalogo.gasto.esgotado)

    def test_sem_linha_de_uso_e_zero_e_limites_ilegiveis_sao_none(self) -> None:
        bd = BdFalsa(
            gastos={"social": {"orcamento": 1, "gasto_usd": 0}},
            uso=[{"modulo": "social", "limites": "nao e um mapa", "periodo": MAIO, "usado": None}],
        )
        (social,) = get_usage(bd, A)
        self.assertEqual((social.chave, social.usado, social.limite), ("posts_mes", 0, None))

    def test_periodo_ilegivel_levanta(self) -> None:
        bd = BdFalsa(uso=[{"modulo": "foto", "limites": {}, "periodo": "2026-05-01", "usado": 1}])
        with self.assertRaises(ValueError):
            get_usage(bd, A)

    def test_um_modulo_que_nao_e_de_entrada_na_resposta_levanta(self) -> None:
        bd = BdFalsa(uso=[{"modulo": "vendedor", "limites": {}, "periodo": MAIO, "usado": 1}])
        with self.assertRaises(ModuloDesconhecido):
            get_usage(bd, A)


class TestMensagem(unittest.TestCase):
    def _uso(self, modulo: str, *, usado=12, limite=40, orcamento=1_000_000, gasto="1", periodo=MAIO) -> UsoDoModulo:
        return UsoDoModulo(
            modulo=modulo, periodo=periodo, chave=CHAVE_DE_USO.get(modulo),
            usado=usado if modulo in CHAVE_DE_USO else None,
            limite=limite if modulo in CHAVE_DE_USO else None,
            gasto=Gasto(modulo, orcamento, Decimal(gasto)),
        )

    def test_os_numeros_do_get_usage_e_o_mes_seguinte(self) -> None:
        self.assertEqual(
            mensagem_orcamento_esgotado(self._uso("foto")),
            "O módulo Foto de produtos chegou ao limite de custo deste mês (100% usado). "
            "Uso do mês: 12 de 40 imagens. Novos pedidos voltam a ser aceites a 1 de Junho.",
        )

    def test_dezembro_reabre_em_janeiro_e_o_catalogo_nao_tem_contador(self) -> None:
        texto = mensagem_orcamento_esgotado(self._uso("catalogo", periodo=DEZEMBRO))
        self.assertTrue(texto.endswith("a 1 de Janeiro."))
        self.assertNotIn("Uso do mês", texto)

    def test_sem_orcamento_diz_que_nao_ha(self) -> None:
        texto = mensagem_orcamento_esgotado(self._uso("social", orcamento=None))
        self.assertTrue(texto.startswith("O módulo Redes sociais não tem orçamento disponível este mês."))

    def test_nenhum_preco_de_teste_no_texto(self) -> None:
        """Criterio 3: os precos de teste nao chegam ao cliente. Nem a palavra Kz."""
        for modulo in MODULOS_DE_ENTRADA:
            for orcamento in (None, 1_000_000):
                with self.subTest(modulo=modulo, orcamento=orcamento):
                    texto = mensagem_orcamento_esgotado(self._uso(modulo, orcamento=orcamento))
                    for proibido in ("Kz", "AOA", "kwanza", "preço", "USD", "$"):
                        self.assertNotIn(proibido, texto)


@dataclass
class OrcamentoFalso:
    gasto_: Gasto | None = None
    erro: bool = False
    chamadas: int = 0

    def gasto(self, tenant_id: str) -> Gasto:
        self.chamadas += 1
        if self.erro:
            raise RuntimeError("base em baixo")
        assert self.gasto_ is not None
        return self.gasto_


class TestGuarda(unittest.TestCase):
    def test_abaixo_do_orcamento_consome_a_quota(self) -> None:
        m = montar()
        guarda = QuotaComOrcamento(OrcamentoFalso(Gasto("foto", 1_000_000, Decimal("0.5"))), m.quota)
        self.assertEqual(guarda.consumir(A, "foto:k1"), Consumo(aceite=True))
        self.assertEqual(len(m.quota.chaves), 1)

    def test_acima_ou_sem_orcamento_ou_com_erro_nao_consome(self) -> None:
        for porta, motivo in (
            (OrcamentoFalso(Gasto("foto", 1_000_000, Decimal("1"))), "orcamento_esgotado"),
            (OrcamentoFalso(Gasto("foto", None, Decimal(0))), "sem_orcamento"),
            (OrcamentoFalso(erro=True), "sem_orcamento"),
        ):
            with self.subTest(motivo=motivo):
                m = montar()
                self.assertEqual(QuotaComOrcamento(porta, m.quota).consumir(A, "foto:k1"),
                                 Consumo(aceite=False, motivo=motivo))
                self.assertEqual(m.quota.chaves, set())

    def test_nenhum_trabalho_de_imagem_nasce_acima_do_orcamento(self) -> None:
        """Criterio 7: «nenhum trabalho de imagem e iniciado acima do orcamento (0 em teste)»."""
        m = montar()
        gastos = {A: Decimal("0.99"), B: Decimal("1")}

        class PorTenant:
            def gasto(self, tenant_id: str) -> Gasto:
                return Gasto("foto", 1_000_000, gastos[tenant_id])

        m.servico.quota = QuotaComOrcamento(PorTenant(), m.quota)
        aceite = m.servico.enhance_image(A, m.guardar(jpeg(b"P1")), "cutout", "k1")
        self.assertIsNotNone(aceite.trabalho)
        recusas = [
            m.servico.enhance_image(B, m.guardar(jpeg(b"P%d" % i), tenant=B), "cutout", f"k{i}")
            for i in range(20)
        ]
        self.assertEqual({(r.trabalho, r.motivo) for r in recusas}, {(None, "orcamento_esgotado")})
        self.assertEqual([t.tenant_id for t in m.repo.todas()], [A])
        self.assertEqual(len(m.quota.chaves), 1)
        self.assertEqual(len(m.primario.recebidos), 0)

    def test_o_adaptador_da_base_pergunta_pelo_modulo_foto(self) -> None:
        bd = BdFalsa(gastos={"foto": {"orcamento": 10, "gasto_usd": 0}})
        self.assertEqual(OrcamentoSobreBase(bd).gasto(A).orcamento_micro_usd, 10)
        self.assertEqual(bd.chamadas[0][1][1], "foto")


if __name__ == "__main__":
    unittest.main()
