"""A forma da exportacao, o congelamento e o `medir` de ponta a ponta (KAM-109).

O que importa medir aqui e a frase do *handoff*: «nao declares nenhuma
hipotese confirmada sem dados exportados e congelados». Logo o `medir` sobre uma
entrada nao congelada, ou mudada depois de congelada, sai com 2 e nao escreve
estado nenhum.
"""

from __future__ import annotations

import copy
import datetime as dt
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from piloto import cli, exportacao, regras, sorteio
from piloto.tests import fabrica as f
from piloto.tests.test_sorteio import preencher

D = dt.timedelta(days=1)
FIM = f.INICIO + 70 * D
SEMENTE = "semente-de-ensaio"


def _correr(argv: list[str]) -> tuple[int, str, str]:
    saida, erro = io.StringIO(), io.StringIO()
    with redirect_stdout(saida), redirect_stderr(erro):
        codigo = cli.principal(argv)
    return codigo, saida.getvalue(), erro.getvalue()


class TestForma(unittest.TestCase):
    def setUp(self) -> None:
        self.bruto = f.bruto([f.pme(1, dias=f.dias_activos(f.INICIO, f.INICIO + D))], FIM)

    def test_a_forma_valida_passa(self) -> None:
        self.assertEqual(len(exportacao.de_objecto(self.bruto).coorte), 1)

    def test_um_campo_a_mais_em_qualquer_nivel_recusa_tudo(self) -> None:
        caminhos = (
            lambda b: b.__setitem__("contact_id", "x"),
            lambda b: b["pmes"][0].__setitem__("telefone", "x"),
            lambda b: next(iter(b["pmes"][0]["dias"].values())).__setitem__("texto", "ola"),
        )
        for mexer in caminhos:
            bruto = copy.deepcopy(self.bruto)
            mexer(bruto)
            with self.subTest(), self.assertRaises(exportacao.ExportacaoInvalida):
                exportacao.de_objecto(bruto)

    def test_o_nome_da_pme_no_lugar_do_ordinal_e_recusado(self) -> None:
        self.bruto["pmes"][0]["pme"] = "Loja da Esquina"
        with self.assertRaises(exportacao.ExportacaoInvalida):
            exportacao.de_objecto(self.bruto)

    def test_custo_em_float_e_motivo_livre_sao_recusados(self) -> None:
        bruto = copy.deepcopy(self.bruto)
        next(iter(bruto["pmes"][0]["dias"].values()))["custo_llm_usd"] = 0.01
        with self.assertRaises(exportacao.ExportacaoInvalida):
            exportacao.de_objecto(bruto)
        bruto = copy.deepcopy(self.bruto)
        bruto["pmes"][0].update(na_coorte=False, saida={"dia": "2027-01-18", "motivo": "o dono disse"})
        with self.assertRaises(exportacao.ExportacaoInvalida):
            exportacao.de_objecto(bruto)

    def test_na_coorte_e_saida_tem_de_concordar(self) -> None:
        self.bruto["pmes"][0]["na_coorte"] = False
        with self.assertRaises(exportacao.ExportacaoInvalida):
            exportacao.de_objecto(self.bruto)

    def test_via_de_pagamento_fora_da_lista(self) -> None:
        self.bruto["pmes"][0]["ciclos_pagos"] = [f.ciclo_pago(f.INICIO, via="dono")]
        with self.assertRaises(exportacao.ExportacaoInvalida):
            exportacao.de_objecto(self.bruto)


class TestCongelar(unittest.TestCase):
    def test_congelar_e_verificar(self) -> None:
        with TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "piloto_export.json"
            caminho.write_text("{}", encoding="utf-8")
            manifesto = exportacao.congelar([caminho], dt.datetime(2027, 3, 1, tzinfo=dt.timezone.utc))
            self.assertEqual(exportacao.verificar(manifesto, Path(pasta)), [])
            caminho.write_text("{ }", encoding="utf-8")
            self.assertEqual(len(exportacao.verificar(manifesto, Path(pasta))), 1)
            caminho.unlink()
            self.assertIn("em falta", exportacao.verificar(manifesto, Path(pasta))[0])

    def test_um_nome_com_caminho_no_manifesto_e_achado(self) -> None:
        manifesto = {"formato": exportacao.FORMATO_MANIFESTO,
                     "ficheiros": [{"nome": "../fora.json", "sha256": "x"}]}
        self.assertIn("invalida", exportacao.verificar(manifesto, Path("."))[0])


class TestMedirDePontaAPonta(unittest.TestCase):
    def setUp(self) -> None:
        self._pasta = TemporaryDirectory()
        self.pasta = Path(self._pasta.name)
        pmes = [
            f.pme(n, dias=f.dias_activos(f.INICIO, FIM) if n <= 7 else {},
                  ciclos=[f.ciclo_pago(f.INICIO)] if n <= 5 else [])
            for n in range(1, 11)
        ]
        self.export = self.pasta / "piloto_export.json"
        self.export.write_text(json.dumps(f.bruto(pmes, FIM)), encoding="utf-8")
        self.h6 = self.pasta / "h6_export.json"
        self.h6.write_text(json.dumps(f.h6_export()), encoding="utf-8")
        lista = "produto_id,nome,preco_minor,disponivel\n" + "".join(
            f"sku-{n},Produto sintetico {n},{n}00,sim\n" for n in range(1, 31))
        for n in range(1, 11):
            pme = f"P{n:02d}"
            (self.pasta / f"produtos_{pme}.csv").write_text(lista, encoding="utf-8")
            amostra = sorteio.sortear(SEMENTE, pme, sorteio.ler_produtos(self.pasta / f"produtos_{pme}.csv"))
            folha = preencher(sorteio.folha(amostra), erros=0 if n <= 6 else 20, mudancas="2",
                              dia=(f.INICIO + 25 * D).isoformat())
            (self.pasta / f"auditoria_{pme}.csv").write_text(folha, encoding="utf-8")
        self.manifesto = self.pasta / "piloto_congelado.json"
        entradas = [self.export, self.h6, *sorted(self.pasta.glob("auditoria_*.csv")),
                    *sorted(self.pasta.glob("produtos_*.csv"))]
        self.assertEqual(_correr(["congelar", *map(str, entradas), "--saida", str(self.manifesto)])[0], 0)

    def tearDown(self) -> None:
        self._pasta.cleanup()

    def _medir(self) -> tuple[int, str, str]:
        return _correr([
            "medir", "--exportacao", str(self.export), "--manifesto", str(self.manifesto),
            "--mensalidade-minor", str(f.MENSALIDADE), "--h6-export", str(self.h6),
            "--auditorias", str(self.pasta), "--semente", SEMENTE,
        ])

    def _recongelar(self) -> None:
        entradas = [self.export, self.h6, *sorted(self.pasta.glob("auditoria_*.csv")),
                    *sorted(self.pasta.glob("produtos_*.csv"))]
        self.assertEqual(_correr(["congelar", *map(str, entradas), "--saida", str(self.manifesto)])[0], 0)

    def test_os_quatro_estados_sobre_entradas_congeladas(self) -> None:
        codigo, saida, erro = self._medir()
        self.assertEqual(codigo, 0, erro)
        resultado = json.loads(saida)
        self.assertEqual(resultado["formato"], cli.FORMATO_RESULTADOS)
        self.assertTrue(resultado["sintetico"])
        estados = {h: v["estado"] for h, v in resultado["hipoteses"].items()}
        # A H6 tem 7 PMEs com 1 conversa por dia em Fevereiro: 196 conversas.
        self.assertEqual(estados, {"H1": regras.CONFIRMADA, "H6": regras.INCONCLUSIVA,
                                   "H8": regras.CONFIRMADA, "H9": regras.CONFIRMADA})
        self.assertEqual(resultado["hipoteses"]["H6"]["amostra_n"], 196)
        p01 = resultado["hipoteses"]["H8"]["detalhe"]["por_pme"]["P01"]
        self.assertEqual((p01["mudancas_reais_declaradas"], p01["fora_da_semana_4"]), (2, False))
        self.assertEqual(set(resultado["fontes"]), {
            "piloto_export.json", "h6_export.json",
            *(f"auditoria_P{n:02d}.csv" for n in range(1, 11)),
            *(f"produtos_P{n:02d}.csv" for n in range(1, 11)),
        })

    def test_uma_folha_com_itens_escolhidos_a_mao_e_recusada(self) -> None:
        # A revisao adversarial (A1): seis folhas de um item certo davam
        # `confirmada`. Uma folha que nao e o sorteio nao se mede.
        produtos = sorteio.ler_produtos(self.pasta / "produtos_P01.csv")
        for escolha in (produtos[:1], list(reversed(sorteio.sortear(SEMENTE, "P01", produtos)))):
            with self.subTest(n=len(escolha)):
                (self.pasta / "auditoria_P01.csv").write_text(
                    preencher(sorteio.folha(escolha), dia=(f.INICIO + 25 * D).isoformat()),
                    encoding="utf-8")
                self._recongelar()
                codigo, saida, erro = self._medir()
                self.assertEqual((codigo, saida), (cli.SAIDA_ERRO, ""))
                self.assertIn("nao sao os do sorteio", erro)

    def test_outra_semente_e_recusada(self) -> None:
        codigo, _, erro = _correr([
            "medir", "--exportacao", str(self.export), "--manifesto", str(self.manifesto),
            "--mensalidade-minor", str(f.MENSALIDADE), "--auditorias", str(self.pasta),
            "--semente", "outra",
        ])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("nao sao os do sorteio", erro)

    def test_auditorias_sem_semente_e_erro(self) -> None:
        codigo, _, erro = _correr([
            "medir", "--exportacao", str(self.export), "--manifesto", str(self.manifesto),
            "--mensalidade-minor", str(f.MENSALIDADE), "--auditorias", str(self.pasta),
        ])
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("--semente", erro)

    def test_uma_auditoria_fora_da_semana_4_conta_e_sai_marcada(self) -> None:
        caminho = self.pasta / "auditoria_P01.csv"
        caminho.write_text(caminho.read_text(encoding="utf-8").replace(
            (f.INICIO + 25 * D).isoformat(), (f.INICIO + 30 * D).isoformat()), encoding="utf-8")
        self._recongelar()
        codigo, saida, erro = self._medir()
        self.assertEqual(codigo, 0, erro)
        self.assertEqual(json.loads(saida)["hipoteses"]["H8"]["detalhe"]["fora_da_semana_4"], ["P01"])

    def test_uma_lista_de_produtos_fora_do_manifesto_nao_se_mede(self) -> None:
        caminho = self.pasta / "produtos_P02.csv"
        caminho.write_text(caminho.read_text(encoding="utf-8") + "sku-99,Produto 99,1,sim\n",
                           encoding="utf-8")
        codigo, _, erro = self._medir()
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("produtos_P02.csv", erro)

    def test_uma_entrada_mudada_depois_de_congelada_nao_se_mede(self) -> None:
        self.export.write_text(self.export.read_text(encoding="utf-8") + " ", encoding="utf-8")
        codigo, saida, erro = self._medir()
        self.assertEqual((codigo, saida), (cli.SAIDA_ERRO, ""))
        self.assertIn("nao congelada", erro)

    def test_uma_folha_fora_do_manifesto_nao_se_mede(self) -> None:
        (self.pasta / "auditoria_P11.csv").write_text("x\n", encoding="utf-8")
        codigo, _, erro = self._medir()
        self.assertEqual(codigo, cli.SAIDA_ERRO)
        self.assertIn("auditoria_P11.csv", erro)

    def test_sem_h6_export_a_h6_e_inconclusiva(self) -> None:
        codigo, saida, _ = _correr([
            "medir", "--exportacao", str(self.export), "--manifesto", str(self.manifesto),
            "--mensalidade-minor", str(f.MENSALIDADE),
        ])
        self.assertEqual(codigo, 0)
        h6 = json.loads(saida)["hipoteses"]["H6"]
        self.assertEqual((h6["estado"], h6["resultado"]), (regras.INCONCLUSIVA, "NAO MEDIDO"))

    def test_verificar_e_relatorio(self) -> None:
        self.assertEqual(_correr(["verificar", "--manifesto", str(self.manifesto)])[0], 0)
        horas = self.pasta / "horas.csv"
        horas.write_text("dia,pme,minutos,categoria\n2027-01-05,P01,30,t2\n", encoding="utf-8")
        codigo, saida, erro = _correr(["relatorio", "--exportacao", str(self.export), "--horas", str(horas),
                                       "--inicio", f.INICIO.isoformat(), "--semana", "1"])
        self.assertEqual(codigo, 0, erro)
        self.assertIn("| P01 |", saida)

    def test_erros_de_uso_saem_com_2(self) -> None:
        self.assertEqual(_correr(["medir"])[0], cli.SAIDA_ERRO)
        self.assertEqual(_correr(["horas", "--registo", str(self.pasta / "nao_existe.csv")])[0],
                         cli.SAIDA_ERRO)
        mau = self.pasta / "mau.csv"
        mau.write_text("dia,pme,minutos,categoria,notas\n", encoding="utf-8")
        self.assertEqual(_correr(["horas", "--registo", str(mau)])[0], cli.SAIDA_ACHADOS)

    def test_sortear_pela_cli(self) -> None:
        produtos = self.pasta / "produtos.csv"
        produtos.write_text("produto_id,nome,preco_minor,disponivel\n"
                            + "".join(f"sku-{n},Produto {n},{n}00,sim\n" for n in range(1, 31)),
                            encoding="utf-8")
        codigo, saida, _ = _correr(["sortear", "--semente", "s", "--pme", "P01", "--produtos", str(produtos)])
        self.assertEqual(codigo, 0)
        self.assertEqual(len(saida.splitlines()), 1 + 20 + 2)  # cabecalho, itens, controlo


if __name__ == "__main__":
    unittest.main()
