"""O custo por tenant e por conversa sem base de dados (KAM-081).

Sete coisas, e todas sao leitura de ficheiros ou aritmetica:

1. **As tarifas da vista sao as do `config/meta_rates.yaml`.** Tres copias — o
   YAML, a constante e o `CASE` do SQL — e o ensaio le as tres. O SQL vem de
   `db/custo.py`, o mesmo modulo que a revisao chama: nao ha uma quarta copia
   aqui.
2. **Nenhum campo de saida aponta para uma pessoa**: as colunas da vista e os
   campos da exportacao contra a lista de identificadores proibidos.
3. **A *fixture* de conversas com totais conhecidos, por igualdade exacta**
   (criterio 2): segmentacao com a pausa de 24 h, Meta medida, LLM rateado,
   percentis e racio a mensalidade.
4. **A reconciliacao** (criterio 3): LLM a 2% por tenant e Meta a 1%.
5. **O cambio** (criterio 1): omissao 913 e os dois modos de sensibilidade.
6. **A unit economics** (criterios 5 e 6), com o `meta_payer` e o item de
   revisao quando o desvio passa de 30%.
7. **As estimativas sao as do `docs/tecnica/09` §14.3**, lidas do documento.

Os paineis tem bateria propria no fim: nenhum `rawSql` le alem da vista e do
contador do *free tier*, e nenhum nomeia um identificador.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unittest
from decimal import Decimal
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[2]
for _pasta in (_RAIZ / "db", _RAIZ / "tools"):
    if str(_pasta) not in sys.path:
        sys.path.insert(0, str(_pasta))

import custo  # noqa: E402
import h6_export as h6  # noqa: E402
from kamba_yaml import load_file  # noqa: E402

UTC = dt.timezone.utc


def _instante(texto: str) -> dt.datetime:
    return dt.datetime.fromisoformat(texto).replace(tzinfo=UTC)


def _m(tenant: str, contacto: int, instante: str, entregue: bool = True, **pricing):
    quando = _instante(instante)
    return h6.Mensagem(
        tenant_id=tenant,
        contacto=contacto,
        instante=quando,
        dia=quando.date(),
        entregue=entregue,
        pricing=pricing or None,
    )


#: A *fixture* do criterio 2. Quatro conversas, com totais calculados a mao:
#:
#:   A/1  10-01 10:00 service cobravel, 12:00 utility cobravel      -> conversa 1
#:   A/1  10-02 14:00 service gratis (26 h depois: parte)           -> conversa 2
#:   A/2  10-01 11:00 marketing cobravel, 10-02 11:00 por entregar  -> conversa 3
#:        (exactamente 24 h: **nao** parte)
#:   B/1  10-01 09:00 cobravel de categoria desconhecida            -> conversa 4
#:
#: LLM do dia: A 10-01 0,003; A 10-02 0,001; B 10-01 0,0005. Mensagens do dia:
#: A 10-01 tres, A 10-02 duas, B 10-01 uma.
FIXTURE = [
    _m("A", 1, "2026-10-01T10:00:00", billable=True, category="service"),
    _m("A", 1, "2026-10-01T12:00:00", billable=True, category="utility"),
    _m("A", 1, "2026-10-02T14:00:00", billable=False, category="service"),
    _m("A", 2, "2026-10-01T11:00:00", billable=True, category="marketing"),
    _m("A", 2, "2026-10-02T11:00:00", entregue=False),
    _m("B", 1, "2026-10-01T09:00:00", billable=True, category="xpto"),
]
LLM_DA_FIXTURE = {
    ("A", dt.date(2026, 10, 1)): Decimal("0.003000"),
    ("A", dt.date(2026, 10, 2)): Decimal("0.001000"),
    ("B", dt.date(2026, 10, 1)): Decimal("0.000500"),
}


class TestTarifas(unittest.TestCase):
    """O YAML, a constante e o `CASE` da vista dizem o mesmo."""

    def test_a_constante_e_o_yaml(self) -> None:
        yaml = load_file(_RAIZ / "config" / "meta_rates.yaml")
        do_yaml = {t["categoria"]: t["usd_micro"] for t in yaml["tarifas"]}
        self.assertEqual(do_yaml, custo.TARIFAS_MICRO_USD)
        self.assertEqual(yaml["efectivas_em"], custo.TARIFAS_EFECTIVAS_EM)
        self.assertEqual(yaml["unidade"], "micro_usd")

    def test_o_case_do_sql_e_a_constante(self) -> None:
        precos = dict(
            (categoria, int(valor))
            for categoria, valor in re.findall(
                r"WHEN '([a-z]+)' THEN (\d+)", custo.SQL_CRIAR_VISTA
            )
        )
        self.assertEqual(precos, custo.TARIFAS_MICRO_USD)

    def test_cada_rubrica_meta_tem_categoria(self) -> None:
        rubricas = set(re.findall(r"THEN '(meta_[a-z]+)'", custo.SQL_CRIAR_VISTA))
        rubricas |= set(re.findall(r"ELSE '(meta_[a-z]+)'", custo.SQL_CRIAR_VISTA))
        self.assertEqual(rubricas | {"llm"}, set(custo.RUBRICAS))

    def test_a_regra_da_tarifa(self) -> None:
        self.assertEqual(custo.tarifa_micro_usd({"billable": True, "category": "utility"}), 4000)
        self.assertEqual(custo.tarifa_micro_usd({"billable": True, "category": "marketing"}), 22500)
        self.assertEqual(custo.tarifa_micro_usd({"billable": False, "category": "marketing"}), 0)
        self.assertEqual(custo.tarifa_micro_usd(None), 0)
        self.assertIsNone(custo.tarifa_micro_usd({"billable": True, "category": "xpto"}))


class TestSemPessoas(unittest.TestCase):
    """Criterio 7 e DoD: sem conteudo nem `contact_id` no que se expoe."""

    def test_as_colunas_da_vista_nao_apontam_para_pessoas(self) -> None:
        self.assertEqual(set(custo.COLUNAS) & h6.IDENTIFICADORES_PROIBIDOS, set())

    def test_os_campos_da_exportacao_nao_apontam_para_pessoas(self) -> None:
        self.assertEqual(set(h6.CAMPOS_DA_CONVERSA) & h6.IDENTIFICADORES_PROIBIDOS, set())

    def test_a_exportacao_so_tem_os_campos_declarados(self) -> None:
        saida = h6.montar_exportacao(
            h6.segmentar(FIXTURE), LLM_DA_FIXTURE, 10, Decimal(913), Decimal(30000)
        )
        for linha in saida["conversas"]:
            self.assertEqual(tuple(linha), h6.CAMPOS_DA_CONVERSA)
        texto = json.dumps(saida)
        for proibido in h6.IDENTIFICADORES_PROIBIDOS:
            self.assertNotIn(f'"{proibido}"', texto)

    def test_a_consulta_troca_o_contacto_por_um_ordinal_na_base(self) -> None:
        """O `contact_id` so aparece dentro do `dense_rank`: nunca e coluna devolvida."""
        lista = h6.SQL_MENSAGENS.split("FROM")[0]
        self.assertIn("dense_rank() OVER (ORDER BY o.tenant_id, o.contact_id) AS contacto", lista)
        self.assertEqual(lista.count("contact_id"), 1)


class TestConversas(unittest.TestCase):
    """Criterio 2: a definicao de conversa e a *fixture* com totais conhecidos."""

    def setUp(self) -> None:
        self.saida = h6.montar_exportacao(
            h6.segmentar(FIXTURE), LLM_DA_FIXTURE, 500, Decimal(913), Decimal(30000)
        )

    def test_vinte_e_quatro_horas_nao_partem_e_mais_partem(self) -> None:
        conversas = h6.segmentar(FIXTURE)
        self.assertEqual([len(c.mensagens) for c in conversas], [2, 1, 2, 1])

    def test_um_microssegundo_acima_parte(self) -> None:
        a = _m("A", 1, "2026-10-01T10:00:00")
        b = h6.Mensagem("A", 1, a.instante + h6.PAUSA + dt.timedelta(microseconds=1),
                        a.dia, True, None)
        self.assertEqual(len(h6.segmentar([b, a])), 2)

    def test_os_totais_por_conversa(self) -> None:
        """Igualdade exacta, por `Decimal`, contra o calculo a mao do topo."""
        esperado = [
            # n, tenant, llm, meta, total, Kz minor a 913
            (1, "B", "0.000500", "0", "0.000500", 46),
            (2, "A", "0.002000", "0.008", "0.010000", 913),
            (3, "A", "0.001500", "0.0225", "0.024000", 2191),
            (4, "A", "0.000500", "0", "0.000500", 46),
        ]
        obtido = [
            (
                c["n"],
                c["tenant_id"],
                Decimal(c["custo_llm_usd"]),
                Decimal(c["custo_meta_usd"]),
                Decimal(c["custo_total_usd"]),
                c["custo_total_aoa_minor"],
            )
            for c in self.saida["conversas"]
        ]
        self.assertEqual(
            obtido,
            [(n, t, Decimal(l), Decimal(m), Decimal(s), k) for n, t, l, m, s, k in esperado],
        )
        self.assertTrue(all(c["custo_stt_usd"] is None for c in self.saida["conversas"]))

    def test_o_rateio_devolve_o_custo_do_dia_inteiro(self) -> None:
        """O LLM rateado soma ao LLM da vista, tenant a tenant."""
        soma = {}
        for c in self.saida["conversas"]:
            soma[c["tenant_id"]] = soma.get(c["tenant_id"], Decimal(0)) + Decimal(c["custo_llm_usd"])
        self.assertEqual(soma, {"A": Decimal("0.004"), "B": Decimal("0.0005")})

    def test_os_percentis(self) -> None:
        self.assertEqual(
            {k: Decimal(v) for k, v in self.saida["percentis_custo_total_usd"].items()},
            {"p50": Decimal("0.0005"), "p90": Decimal("0.024"), "p99": Decimal("0.024")},
        )

    def _com_mes(self, n: int) -> dict:
        return h6.montar_exportacao(
            h6.segmentar(FIXTURE), LLM_DA_FIXTURE, n, Decimal(913), Decimal(30000),
            custo_mensal={("A", "2026-10"): Decimal("0.0345"), ("B", "2026-10"): Decimal("0.0005")},
            mes_corrente="2026-11",
        )

    def test_o_racio_a_mensalidade_e_do_mes_inteiro(self) -> None:
        racios = {r["tenant_id"]: r for r in self._com_mes(500)["racio_por_tenant_e_mes"]}
        self.assertEqual(racios["A"]["conversas_na_amostra"], 3)
        self.assertEqual(racios["A"]["custo_aoa_minor"], 3150)  # 0,0345 x 913 x 100
        self.assertEqual(Decimal(racios["A"]["racio_custo_mensalidade"]), Decimal("0.001050"))
        self.assertTrue(racios["A"]["mes_completo"])
        self.assertEqual(self.saida["mensalidade_aoa_minor"], 3_000_000)

    def test_o_racio_nao_depende_do_tamanho_da_amostra(self) -> None:
        """Achado A3 da revisao: somado da amostra, N=1 e N=500 davam racios diferentes."""
        grande = {r["tenant_id"]: r for r in self._com_mes(500)["racio_por_tenant_e_mes"]}
        pequena = {r["tenant_id"]: r for r in self._com_mes(1)["racio_por_tenant_e_mes"]}
        self.assertTrue(pequena)
        for tenant_id, linha in pequena.items():
            self.assertEqual(
                linha["racio_custo_mensalidade"], grande[tenant_id]["racio_custo_mensalidade"]
            )

    def test_o_mes_corrente_sai_incompleto(self) -> None:
        saida = h6.montar_exportacao(
            h6.segmentar(FIXTURE), LLM_DA_FIXTURE, 500, Decimal(913), Decimal(30000),
            custo_mensal={("A", "2026-10"): Decimal("0.0345")}, mes_corrente="2026-10",
        )
        linha = next(r for r in saida["racio_por_tenant_e_mes"] if r["tenant_id"] == "A")
        self.assertFalse(linha["mes_completo"])

    def test_o_llm_de_um_dia_sem_mensagens_nao_se_perde(self) -> None:
        """Achado A2: o LLM de um dia sem saida saia do rateio sem rasto."""
        llm = dict(LLM_DA_FIXTURE)
        llm[("A", dt.date(2026, 10, 3))] = Decimal("0.009000")
        saida = h6.montar_exportacao(h6.segmentar(FIXTURE), llm, 500, Decimal(913), Decimal(30000))
        self.assertEqual(
            saida["llm_nao_atribuido"], [{"tenant_id": "A", "dias": 1, "custo_usd": "0.009000"}]
        )
        self.assertEqual(self.saida["llm_nao_atribuido"], [])

    def test_conversas_por_fechar_e_cortadas_ficam_de_fora(self) -> None:
        """Achado A13: a amostra so leva conversas inteiras."""
        escolhidas, excluidas = h6.ultimas(
            h6.segmentar(FIXTURE), 500,
            fechadas_ate=_instante("2026-10-02T12:00:00"),   # a A/1 das 14:00 esta aberta
            inicio_minimo=_instante("2026-10-01T10:30:00"),  # comecam antes: A/1 e B/1
        )
        self.assertEqual(excluidas, {"por_fechar": 1, "cortadas_pela_janela": 2})
        self.assertEqual([(c.tenant_id, c.contacto) for c in escolhidas], [("A", 2)])

    def test_a_categoria_sem_tarifa_conta_e_nao_custa(self) -> None:
        self.assertEqual(self.saida["mensagens_meta_sem_tarifa"], 1)

    def test_as_ultimas_n(self) -> None:
        saida = h6.montar_exportacao(
            h6.segmentar(FIXTURE), LLM_DA_FIXTURE, 2, Decimal(913), Decimal(30000)
        )
        self.assertEqual([c["fim_dia"] for c in saida["conversas"]], ["2026-10-02", "2026-10-02"])
        self.assertEqual(saida["amostra"], 2)
        with self.assertRaises(h6.ErroDeUso):
            h6.ultimas(h6.segmentar(FIXTURE), 0)

    def test_percentil_por_posicao_mais_proxima(self) -> None:
        valores = [Decimal(v) for v in range(1, 101)]
        self.assertEqual(h6.percentil(valores, 50), Decimal(50))
        self.assertEqual(h6.percentil(valores, 99), Decimal(99))
        self.assertIsNone(h6.percentil([], 50))


class TestReconciliacao(unittest.TestCase):
    """Criterio 3, na *fixture*."""

    def test_llm_a_dois_por_cento_por_tenant(self) -> None:
        achados = h6.reconciliar_llm(
            {"A": Decimal("1.00"), "B": Decimal("2.00"), "C": Decimal("1")},
            {"A": Decimal("1.019"), "B": Decimal("2.05")},
        )
        self.assertEqual(len(achados), 2)
        self.assertTrue(achados[0].startswith("B:"))
        self.assertIn("sem linhas em LiteLLM", achados[1])

    def test_a_pme_tipica_do_doc_09(self) -> None:
        """2.880 mensagens de servico, 1.000 gratis: 1.880 x 0,004 = 7,52 USD."""
        self.assertEqual(h6.meta_pela_tarifa({"service": 2880}), 7_520_000)

    def test_por_numero_a_meta_medida_e_a_da_tarifa(self) -> None:
        """O medido vem das cobradas pelo `pricing`; o estimado, da contagem pela tarifa.

        Achado A4 da revisao: o ensaio anterior usava a mesma constante dos dois
        lados. Aqui os dois lados vem de colunas diferentes da mesma linha.
        """
        resultados, achados = h6.reconciliar_meta_por_numero([
            ("A", 1, "service", 1003, 3),     # a Meta cobrou 3: as 1.000 primeiras gratis
            ("A", 1, "utility", 2, 2),
            ("A", 2, "service", 1003, 1003),  # cobrou tudo: o free tier nao se aplicou
        ])
        por_numero = {r["numero"]: r for r in resultados}
        self.assertEqual(por_numero[1]["medido_usd_micro"], 20_000)
        self.assertEqual(por_numero[1]["pela_tarifa_usd_micro"], 20_000)
        self.assertTrue(por_numero[1]["dentro_da_tolerancia"])
        self.assertFalse(por_numero[2]["dentro_da_tolerancia"])
        self.assertEqual(len(achados), 1)
        self.assertIn("numero 2", achados[0])

    def test_categoria_desconhecida_e_achado(self) -> None:
        _, achados = h6.reconciliar_meta_por_numero([("A", 1, "xpto", 5, 5)])
        self.assertIn("categoria sem tarifa", achados[0])

    def test_meta_a_um_por_cento(self) -> None:
        estimado = h6.meta_pela_tarifa({"service": 1500, "utility": 100, "marketing": 10})
        self.assertEqual(estimado, 500 * 4000 + 100 * 4000 + 10 * 22500)
        self.assertIsNone(h6.reconciliar_meta(int(estimado * 1.005), estimado))
        self.assertIsNotNone(h6.reconciliar_meta(int(estimado * 1.02), estimado))

    def test_o_desvio_contra_zero_nao_e_zero(self) -> None:
        self.assertEqual(h6.desvio(Decimal(0), Decimal(0)), Decimal(0))
        self.assertIsNone(h6.desvio(Decimal(1), Decimal(0)))


class TestCambio(unittest.TestCase):
    """Criterio 1: omissao 913 e os modos +7,4% e +35%."""

    def test_os_modos(self) -> None:
        self.assertEqual(custo.cambio(), Decimal(913))
        self.assertEqual(custo.cambio("venda_bni"), Decimal(981))
        self.assertEqual(custo.cambio("choque"), Decimal(1232))
        self.assertEqual(custo.cambio(valor="950"), Decimal(950))

    def test_recusas(self) -> None:
        for invalido in ("0", "-1", "nan", "abc"):
            with self.subTest(invalido=invalido), self.assertRaises((ValueError, ArithmeticError)):
                custo.cambio(valor=invalido)
        with self.assertRaises(ValueError):
            custo.cambio("base", "913")

    def test_a_omissao_do_sql_e_a_do_python(self) -> None:
        self.assertRegex(
            custo.SQL_CRIAR_VISTA,
            r"current_setting\('app\.fx_aoa_per_usd', true\), ''\)::numeric,\s+913\s+\)",
        )
        self.assertEqual(custo.CAMBIO_POR_OMISSAO, Decimal(913))

    def test_o_arredondamento_e_o_do_round_do_postgres(self) -> None:
        # 0,0005 x 913 x 100 = 45,65 -> 46; metade exacta sobe.
        self.assertEqual(custo.para_aoa_minor(Decimal("0.0005"), Decimal(913)), 46)
        self.assertEqual(custo.para_aoa_minor(Decimal("0.005"), Decimal(1000)), 500)
        self.assertEqual(custo.para_aoa_minor(Decimal("0.000005"), Decimal(1000)), 1)


class TestEconomia(unittest.TestCase):
    """Criterios 5 e 6."""

    MES = {
        "A": {"llm": Decimal("5.5"), "meta_service": Decimal("7.5")},
        "B": {"llm": Decimal("5.5"), "meta_utility": Decimal("7.5")},
    }

    def test_quem_paga_a_meta_muda_o_custo_para_a_kamba_e_nao_o_do_cliente(self) -> None:
        pme = h6.economia(self.MES, Decimal(600), Decimal(45000), Decimal(913), "pme")
        kamba = h6.economia(self.MES, Decimal(600), Decimal(45000), Decimal(913), "kamba")
        self.assertEqual(Decimal(pme["custo_para_kamba_por_pme_usd"]), Decimal("305.5"))
        self.assertEqual(Decimal(kamba["custo_para_kamba_por_pme_usd"]), Decimal("313"))
        # O cliente paga a mensalidade, e a Meta por cima so quando e ele quem a paga.
        mensalidade = Decimal(45000) / Decimal(913)
        self.assertEqual(Decimal(pme["custo_total_cliente_por_pme_usd"]),
                         (mensalidade + Decimal("7.5")).quantize(h6.ESCALA_USD))
        self.assertEqual(Decimal(kamba["custo_total_cliente_por_pme_usd"]),
                         mensalidade.quantize(h6.ESCALA_USD))
        self.assertEqual(Decimal(pme["custo_fixo_por_pme_usd"]), Decimal(300))

    def test_o_ponto_de_equilibrio(self) -> None:
        # 45.000 / 913 = 49,288 USD; contribuicao 43,788 (pme) e 36,288 (kamba).
        pme = h6.economia(self.MES, Decimal(600), Decimal(45000), Decimal(913), "pme")
        kamba = h6.economia(self.MES, Decimal(600), Decimal(45000), Decimal(913), "kamba")
        self.assertEqual(pme["ponto_de_equilibrio_pmes"], 14)
        self.assertEqual(kamba["ponto_de_equilibrio_pmes"], 17)

    def test_no_estimado_nao_ha_item_de_revisao(self) -> None:
        saida = h6.economia(self.MES, Decimal(600), Decimal(45000), Decimal(913), "pme")
        self.assertEqual(saida["itens_de_revisao"], [])

    def test_trinta_por_cento_acima_gera_item(self) -> None:
        mes = {"A": {"llm": Decimal("8"), "meta_service": Decimal("7.5")}}
        saida = h6.economia(mes, Decimal(600), Decimal(45000), Decimal(913), "pme")
        self.assertEqual([i["rubrica"] for i in saida["itens_de_revisao"]], ["llm"])
        self.assertIn("docs/tecnica/09", saida["itens_de_revisao"][0]["item"])

    def test_recusas(self) -> None:
        with self.assertRaises(h6.ErroDeUso):
            h6.economia(self.MES, Decimal(600), Decimal(45000), Decimal(913), "outro")
        with self.assertRaises(h6.ErroDeUso):
            h6.economia({}, Decimal(600), Decimal(45000), Decimal(913), "pme")
        with self.assertRaises(h6.ErroDeUso):
            h6.economia(self.MES, Decimal(600), Decimal(0), Decimal(913), "pme")

    def test_a_linha_de_comandos_recusa_sem_traceback(self) -> None:
        """Achado A12: `abc` e `0` saem pelo `argparse`, com 2, antes de tocar na base."""
        for argumentos in (["exportar", "--mensalidade-kz", "abc"],
                           ["exportar", "--mensalidade-kz", "0"],
                           ["exportar", "--cambio", "-913"],
                           ["economia", "--mes", "2026-13", "--fixo-usd", "470"]):
            with self.subTest(argumentos=argumentos):
                with self.assertRaises(SystemExit) as saida:
                    h6._analisador().parse_args(argumentos)
                self.assertEqual(saida.exception.code, 2)


class TestEstimativasDoDoc09(unittest.TestCase):
    """As estimativas sao as do §14.3, lidas do documento e nao copiadas de memoria."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = (_RAIZ / "docs" / "tecnica" / "09_Topologia_Operacao_Escala.md").read_text(
            encoding="utf-8"
        )

    def _linha(self, rotulo: str) -> list[Decimal]:
        linha = next(l for l in self.doc.splitlines() if l.startswith(f"| {rotulo}"))
        return [Decimal(v.replace(",", ".")) for v in re.findall(r"\$(\d+(?:,\d+)?)", linha)]

    def test_llm_por_pme(self) -> None:
        cenarios = ("baixo", "misto", "sonnet")
        self.assertEqual(
            self._linha("**LLM por PME/mês**"),
            [h6.ESTIMATIVAS_POR_PME_MES[c]["llm"] for c in cenarios],
        )

    def test_stt(self) -> None:
        cenarios = ("baixo", "misto", "sonnet")
        self.assertEqual(
            self._linha("STT (300 min/mês de voz)"),
            [h6.ESTIMATIVAS_POR_PME_MES[c]["stt"] for c in cenarios],
        )

    def test_meta(self) -> None:
        self.assertIn("= **$7,5/PME/mês", self.doc)
        self.assertTrue(all(e["meta"] == Decimal("7.5") for e in h6.ESTIMATIVAS_POR_PME_MES.values()))


class TestPaineis(unittest.TestCase):
    """Os dois paineis do KAM-081 nao expoem pessoas nem leem alem do que devem."""

    PAINEIS = ("custo-por-tenant", "unit-economics")

    #: As unicas relacoes que um `rawSql` destes paineis pode ler.
    RELACOES = {"platform.v_tenant_cost_daily", "platform.tenant_channels", "platform.tenants"}

    def _consultas(self, nome: str) -> list[str]:
        dados = json.loads((_RAIZ / "ops" / "paineis" / f"{nome}.json").read_text(encoding="utf-8"))
        encontradas: list[str] = []

        def descer(no) -> None:
            if isinstance(no, dict):
                for chave, valor in no.items():
                    if chave == "rawSql" and isinstance(valor, str):
                        encontradas.append(valor)
                    else:
                        descer(valor)
            elif isinstance(no, list):
                for item in no:
                    descer(item)

        descer(dados)
        return encontradas

    def test_cada_painel_tem_consultas(self) -> None:
        for nome in self.PAINEIS:
            with self.subTest(painel=nome):
                self.assertGreater(len(self._consultas(nome)), 0)

    #: Os esquemas da base, o `public` e os de sistema. Uma relacao destes escrita
    #: em **qualquer** sitio da consulta conta como lida — e nao so a que vem a
    #: seguir a um `FROM`/`JOIN` em maiusculas: a revisao adversarial (A5) leu a
    #: `outbound_messages` por uma juncao por virgula e por um `join` em
    #: minusculas, e as duas passavam.
    ESQUEMAS = r"(?:platform|dat|lg|servicos|public|pg_catalog|information_schema)"

    #: Os nomes sem esquema que um `FROM` destes paineis pode ter: as CTE.
    CTES = {"mes", "medido", "variaveis"}

    def _lidas(self, sql: str) -> set[str]:
        return {
            r.lower() for r in re.findall(rf"\b({self.ESQUEMAS}\.[a-z_]+)", sql, re.IGNORECASE)
        }

    def test_nenhuma_consulta_nomeia_um_identificador(self) -> None:
        for nome in self.PAINEIS:
            for sql in self._consultas(nome):
                with self.subTest(painel=nome, sql=sql[:60]):
                    for proibido in h6.IDENTIFICADORES_PROIBIDOS:
                        self.assertIsNone(
                            re.search(rf"\b{proibido}\b", sql, re.IGNORECASE), proibido
                        )

    def test_so_leem_as_relacoes_permitidas(self) -> None:
        for nome in self.PAINEIS:
            for sql in self._consultas(nome):
                with self.subTest(painel=nome, sql=sql[:60]):
                    lidas = self._lidas(sql)
                    self.assertTrue(lidas, "consulta sem relacao qualificada")
                    self.assertLessEqual(lidas, self.RELACOES)

    def test_nao_ha_relacao_sem_esquema(self) -> None:
        """Um `FROM outbound_messages` sem esquema escapava ao ensaio de cima."""
        for nome in self.PAINEIS:
            for sql in self._consultas(nome):
                with self.subTest(painel=nome, sql=sql[:60]):
                    for alvo in re.findall(
                        r"\b(?:from|join)\s+([a-z_]+)\b(?!\.)", sql, re.IGNORECASE
                    ):
                        self.assertIn(alvo.lower(), self.CTES, f"relacao sem esquema: {alvo}")

    def test_o_ensaio_morde_as_formas_da_revisao(self) -> None:
        """As formas que a revisao usou para ler a `outbound_messages`, e uma terceira."""
        formas = (
            "SELECT o.* FROM platform.v_tenant_cost_daily v, platform.outbound_messages o",
            "SELECT 1 FROM platform.v_tenant_cost_daily v join platform.outbound_messages o on true",
            "select 1 from PLATFORM.OUTBOUND_MESSAGES",
        )
        for sql in formas:
            with self.subTest(sql=sql):
                self.assertFalse(self._lidas(sql) <= self.RELACOES)


if __name__ == "__main__":
    unittest.main()
