"""O `h12-export` sem base: pseudonimo, precos, CSV, alertas e reconciliacao (KAM-124).

O que corre contra a base esta em `test_modulos_custo_schema.py`. Aqui provam-se
as funcoes puras do comando, com numeros escritos a mao.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import unittest
from decimal import Decimal
from pathlib import Path

import h12_export as h12
import modulos_custo

RAIZ = Path(__file__).resolve().parents[2]
T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"


class TestPseudonimo(unittest.TestCase):
    def test_estavel_irreversivel_e_sem_hexadecimal(self) -> None:
        um = h12.pseudonimo(b"chave", T1)
        self.assertEqual(um, h12.pseudonimo(b"chave", T1))
        self.assertNotEqual(um, h12.pseudonimo(b"outra", T1))
        self.assertNotEqual(um, h12.pseudonimo(b"chave", T2))
        self.assertEqual(len(um), 20)
        self.assertNotIn(T1, um)
        self.assertTrue(set(um) <= set("abcdefghijklmnopqrstuvwxyz234567"))

    def test_sem_chave_recusa(self) -> None:
        with self.assertRaises(h12.ErroDeUso):
            h12.pseudonimo(b"", T1)
        for ambiente in ({}, {h12.VARIAVEL_DA_CHAVE: "  "}):
            with self.subTest(ambiente=ambiente), self.assertRaises(h12.ErroDeUso):
                h12.chave_do_ambiente(ambiente)
        self.assertEqual(h12.chave_do_ambiente({h12.VARIAVEL_DA_CHAVE: "s"}), b"s")


class TestPrecos(unittest.TestCase):
    def _plano(self, estado: str = "hipotese_nao_validada", modulo: str = "foto", preco: object = 1500000):
        return {"plans": {"entrada_x": {"estado": estado, "entitlements": [
            {"modulo": modulo, "ativo": True, "preco_teste_minor": preco, "limites": {"imagens_mes": 1}}]}}}

    def test_o_ficheiro_real(self) -> None:
        import sys

        sys.path.insert(0, str(RAIZ / "tools"))
        import kamba_yaml

        precos = h12.precos_do_registo(kamba_yaml.load((RAIZ / "registry" / "plans.yaml").read_text(encoding="utf-8")))
        self.assertEqual(len(precos), 8)
        self.assertEqual({p.estado for p in precos}, {"hipotese_nao_validada"})
        self.assertIn(h12.PrecoDeTeste("entrada_social", "social", 6000000, "hipotese_nao_validada"), precos)
        # O `free` nao tem preco de teste e nao aparece.
        self.assertNotIn("free", {p.plano for p in precos})

    def test_recusas(self) -> None:
        for documento in (
            {},
            {"plans": {"x": 3}},
            self._plano(estado="decidido"),
            self._plano(modulo="vendedor"),
            self._plano(preco=-1),
            self._plano(preco=True),
            self._plano(preco="1500000"),
        ):
            with self.subTest(documento=documento), self.assertRaises(h12.ErroDeUso):
                h12.precos_do_registo(documento)


class TestMapaDeTemplates(unittest.TestCase):
    def test_o_ficheiro_real_so_tem_os_dois_do_orcamento(self) -> None:
        """KAM-221: os dois *templates* do orcamento expresso, e nenhum outro."""
        import sys

        sys.path.insert(0, str(RAIZ / "tools"))
        import kamba_yaml

        documento = kamba_yaml.load((RAIZ / "config" / "templates_por_modulo.yaml").read_text(encoding="utf-8"))
        self.assertEqual(
            h12.mapa_de_templates(documento),
            (["orcamento_pronto", "orcamento_em_espera"], ["orcamento", "orcamento"]),
        )

    def test_a_forma_e_as_recusas(self) -> None:
        self.assertEqual(
            h12.mapa_de_templates({"templates": [{"template": "a", "modulo": "foto"}, {"template": "b", "modulo": "social"}]}),
            (["a", "b"], ["foto", "social"]),
        )
        for documento in (
            {},
            {"templates": ["a"]},
            {"templates": [{"template": "", "modulo": "foto"}]},
            {"templates": [{"template": "a", "modulo": "vendedor"}]},
            {"templates": [{"template": "a", "modulo": "foto"}, {"template": "a", "modulo": "social"}]},
        ):
            with self.subTest(documento=documento), self.assertRaises(h12.ErroDeUso):
                h12.mapa_de_templates(documento)


class TestCsv(unittest.TestCase):
    def test_as_linhas_sem_tenant_id_e_o_uso_por_modulo(self) -> None:
        h12_linhas = [
            {"tenant_id": T1, "mes": dt.date(2026, 11, 1), "modulo": "foto", "custo_usd": Decimal("0.18"),
             "custo_aoa_minor": 16434, "fx_aoa_per_usd": Decimal("913"), "preco_teste_minor": 1500000,
             "racio": Decimal("0.010956"), "margem_minor": 1483566},
            {"tenant_id": T1, "mes": dt.date(2026, 11, 1), "modulo": "catalogo", "custo_usd": Decimal("0.01"),
             "custo_aoa_minor": 913, "fx_aoa_per_usd": Decimal("913"), "preco_teste_minor": None,
             "racio": None, "margem_minor": None},
            {"tenant_id": T2, "mes": dt.date(2026, 11, 1), "modulo": "social", "custo_usd": Decimal("1"),
             "custo_aoa_minor": 91300, "fx_aoa_per_usd": Decimal("913"), "preco_teste_minor": 6000000,
             "racio": Decimal("0.015217"), "margem_minor": 5908700},
        ]
        texto = h12.csv_de(h12.linhas_do_csv(h12_linhas, {(T1, "imagens_mes"): 7}, b"k"))
        self.assertNotIn(T1, texto)
        self.assertNotIn(T2, texto)
        self.assertNotIn("\r", texto)
        linhas = list(csv.DictReader(io.StringIO(texto)))
        self.assertEqual(tuple(linhas[0]), h12.CAMPOS_DO_CSV)
        por_modulo = {l["modulo"]: l for l in linhas}
        self.assertEqual((por_modulo["foto"]["uso"], por_modulo["foto"]["estado_do_preco"]), ("7", "hipotese_nao_validada"))
        self.assertEqual((por_modulo["catalogo"]["uso"], por_modulo["catalogo"]["preco_teste_minor"],
                          por_modulo["catalogo"]["estado_do_preco"], por_modulo["catalogo"]["racio"]), ("", "", "", ""))
        self.assertEqual(por_modulo["social"]["uso"], "0")  # tem contador e nao ha linha de uso
        self.assertEqual(por_modulo["foto"]["mes"], "2026-11")

    def test_os_campos_nao_tem_identificador_de_pessoa(self) -> None:
        for campo in h12.CAMPOS_DO_CSV:
            for proibido in ("tenant_id", "contact", "telefone", "phone", "nome", "texto"):
                self.assertNotIn(proibido, campo)


class TestAlertas(unittest.TestCase):
    def test_limiares_do_preco(self) -> None:
        linhas = [
            {"tenant_id": T1, "modulo": "foto", "racio": Decimal("0.15")},     # no limiar: nada
            {"tenant_id": T1, "modulo": "social", "racio": Decimal("0.150001")},
            {"tenant_id": T2, "modulo": "foto", "racio": Decimal("0.30")},     # aviso, nao critico
            {"tenant_id": T2, "modulo": "social", "racio": Decimal("0.300001")},
            {"tenant_id": T2, "modulo": "catalogo", "racio": None},            # sem preco
        ]
        self.assertEqual(
            [(a.tenant_id, a.modulo, a.severidade) for a in h12.alertas_de_preco(linhas)],
            [(T1, "social", "aviso"), (T2, "foto", "aviso"), (T2, "social", "critico")],
        )

    def test_dia_acima_de_tres_vezes_a_mediana(self) -> None:
        hoje = dt.date(2026, 11, 16)
        base = [(T1, hoje - dt.timedelta(days=n), Decimal("1")) for n in range(1, 8)]
        self.assertEqual(h12.alertas_diarios(base + [(T1, hoje, Decimal("3"))], hoje), [])
        alerta = h12.alertas_diarios(base + [(T1, hoje, Decimal("3.01"))], hoje)
        self.assertEqual([(a.tipo, a.tenant_id) for a in alerta], [("custo_diario_anomalo", T1)])
        # Seis dias de historia nao chegam para uma mediana.
        self.assertEqual(h12.alertas_diarios(base[:6] + [(T1, hoje, Decimal("100"))], hoje), [])
        # Dias fora da janela de 28 nao contam.
        velhos = [(T1, hoje - dt.timedelta(days=30 + n), Decimal("1")) for n in range(10)]
        self.assertEqual(h12.alertas_diarios(velhos + [(T1, hoje, Decimal("100"))], hoje), [])
        # Sem custo hoje, nada.
        self.assertEqual(h12.alertas_diarios(base, hoje), [])

    def test_fornecedor_sem_custo_e_mensagem_sem_tarifa(self) -> None:
        alertas = h12.alertas_de_fornecedor([("bria", 0, 10), ("photoroom", 2, 5)], sem_tarifa=3)
        self.assertEqual([(a.tipo, a.valor) for a in alertas],
                         [("imagem_sem_custo", "photoroom:2/5"), ("mensagem_sem_tarifa", "3")])
        self.assertEqual(h12.alertas_de_fornecedor([("bria", 0, 10)]), [])


class TestReconciliacao(unittest.TestCase):
    def test_desvio(self) -> None:
        self.assertEqual(h12.desvio(Decimal("102"), Decimal("100")), Decimal("0.02"))
        self.assertIsNone(h12.desvio(Decimal(0), Decimal(0)))
        self.assertEqual(h12.desvio(Decimal(1), Decimal(0)), Decimal("Infinity"))

    def test_as_tolerancias_do_criterio(self) -> None:
        self.assertEqual(dict(h12.TOLERANCIA), {"llm": Decimal("0.02"), "imagem": Decimal("0.05"),
                                                "mensagem": Decimal("0.05")})
        ledger = {"foto": Decimal("102"), "social": Decimal("102.01")}
        referencia = {"foto": Decimal("100"), "social": Decimal("100"), "catalogo": Decimal("1")}
        achados = h12.reconciliar(ledger, referencia, Decimal("0.02"), "litellm")
        self.assertEqual([a["chave"] for a in achados], ["catalogo", "social"])

    def test_por_modulo(self) -> None:
        somas = {(T1, "foto", "llm"): Decimal(1), (T2, "foto", "llm"): Decimal(2), (T1, "foto", "imagem"): Decimal(5)}
        self.assertEqual(h12._por_modulo(somas, "llm"), {"foto": Decimal(3)})


class TestSqlDaConsolidacao(unittest.TestCase):
    def test_as_tres_rubricas_e_os_quatro_modulos(self) -> None:
        self.assertEqual(modulos_custo.RUBRICAS, ("llm", "imagem", "mensagem"))
        self.assertEqual(modulos_custo.MODULOS, ("catalogo", "foto", "social", "orcamento"))
        for sql, prefixo in ((modulos_custo.SQL_CONSOLIDAR_IMAGEM, "'imagem:'"),
                             (modulos_custo.SQL_CONSOLIDAR_LLM, "'llm:'"),
                             (modulos_custo.SQL_CONSOLIDAR_MENSAGEM, "'mensagem:'")):
            with self.subTest(prefixo=prefixo):
                self.assertIn("platform.module_cost_gravar", sql)
                self.assertIn(prefixo, sql)

    def test_a_tarifa_da_mensagem_e_a_da_v_tenant_cost_daily(self) -> None:
        import custo

        for categoria, micro in custo.TARIFAS_MICRO_USD.items():
            with self.subTest(categoria=categoria):
                self.assertIn(f"WHEN '{categoria}' THEN {micro}", modulos_custo.SQL_CONSOLIDAR_MENSAGEM)


if __name__ == "__main__":
    unittest.main()
