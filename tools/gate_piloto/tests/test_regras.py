"""As regras: os dois ensaios que os «Testes Requeridos» do KAM-110 nomeiam, e o resto.

1. «Registo de Hipóteses sintético (9 estados misturados): nenhuma linha sem
   dados sai `confirmada`» — `TestEstadoEfectivo`.
2. «a matriz de `14` §6 devolve a linha correcta para cada falha simulada» —
   `TestMatriz`. O oráculo é a **tabela do `14` §6 lida do disco**, coluna
   «Se acontecer…» ligada à coluna «Então…», e não a constante do gerador:
   trocar duas linhas da constante entre si tem de avermelhar.
"""

from __future__ import annotations

import itertools
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gate_piloto import entradas, registo, regras
from gate_piloto.tests import sintetico

RAIZ = Path(__file__).resolve().parents[3]
DOC_14 = RAIZ / "docs/exploracao/14-tese-minima-e-plano-de-validacao.md"

CONGELADA = entradas.validar(sintetico.resumo(exportacao="x.csv", exportacao_sha256="ab" * 32))

#: As fontes sintéticas que «existem». Uma fonte fora deste conjunto não existe.
EXISTEM = {"a.md", "b.md", "c.md", "d.md", "e.md", "f.md", "g.md", "x.md"}


def _existe(celula: str) -> bool:
    return celula in EXISTEM


def _estados(linhas: dict, resumo: entradas.Resumo = CONGELADA) -> dict[str, regras.Estado]:
    return regras.estados(registo.ler_texto(sintetico.registo(linhas)), resumo, _existe)


class TestEstadoEfectivo(unittest.TestCase):
    def test_nove_estados_misturados_nenhum_sem_dados_sai_confirmada(self) -> None:
        # Os nove, de uma vez, como os «Testes Requeridos» pedem.
        misturado = {
            "H1": ("10", "6", "confirmada", "a.md"),  # com dados: fica
            "H2": ("", "", "confirmada", ""),  # sem nada
            "H3": ("3", "NÃO MEDIDO", "confirmada", "b.md"),  # resultado por medir
            "H4": ("1", "1", "confirmada", "nao-existe.md"),  # a fonte não existe
            "H5": ("0", "0", "refutada", "c.md"),  # amostra zero
            "H6": ("499", "9", "confirmada", "d.md"),  # abaixo do mínimo do critério
            "H7": ("100", "70", "refutada", "e.md"),  # com dados: fica
            "H8": ("10", "5", "", "f.md"),  # estado por decidir
            "H9": ("7", "6", "confirmada", "g.md"),  # < 8 PMEs com 60 dias
        }
        e = _estados(misturado)
        self.assertEqual(e["H1"].efectivo, "confirmada")
        self.assertEqual(e["H7"].efectivo, "refutada")
        for h in ("H2", "H3", "H4", "H5", "H6", "H8", "H9"):
            self.assertEqual(e[h].efectivo, "inconclusiva", h)
            self.assertTrue(e[h].razoes, h)

    def test_toda_a_combinacao_de_dados_em_falta(self) -> None:
        # Exaustivo sobre as três peças de dados, nos dois estados que decidem.
        # Os resultados sem número são os que o Registo §2 dá como inválidos.
        sem_numero = ("", "—", "correu bem", "NÃO MEDIDO", "não medido", "NÃO MEDIDO (sem resposta 12)")
        pecas = {
            "amostra": ("", "0", "12"),
            "resultado": (*sem_numero, "12"),
            "fonte": ("", "Reunião de 12 de Novembro", "x.md"),
        }
        for amostra, resultado, fonte in itertools.product(*pecas.values()):
            completa = amostra == "12" and resultado == "12" and fonte == "x.md"
            for declarado in ("confirmada", "refutada"):
                linha = registo.Linha("H2", "", "", "", amostra, resultado, declarado, fonte, "", "", "", "")
                efectivo = regras.estado_efectivo(linha, False, _existe).efectivo
                with self.subTest(amostra=amostra, resultado=resultado, fonte=fonte, declarado=declarado):
                    self.assertEqual(efectivo, declarado if completa else "inconclusiva")

    def test_fronteiras_das_amostras_minimas(self) -> None:
        for h, minimo in (("H6", 500), ("H9", 8)):
            abaixo = _estados({h: (str(minimo - 1), "1", "confirmada", "x.md")})[h]
            no_limite = _estados({h: (str(minimo), "1", "confirmada", "x.md")})[h]
            self.assertEqual(abaixo.efectivo, "inconclusiva", h)
            self.assertEqual(no_limite.efectivo, "confirmada", h)

    def test_as_do_kam_109_exigem_a_exportacao_congelada(self) -> None:
        com = ("600", "9", "confirmada", "x.md")
        linhas = {h: com for h in ("H1", "H2", "H6", "H8", "H9")}
        sem = _estados(linhas, entradas.VAZIO)
        for h in regras.DO_KAM_109:
            self.assertEqual(sem[h].efectivo, "inconclusiva", h)
            self.assertIn("sem exportação congelada do KAM-109 no resumo", sem[h].razoes)
        self.assertEqual(sem["H2"].efectivo, "confirmada")
        self.assertEqual(_estados(linhas)["H1"].efectivo, "confirmada")

    def test_amostra_minima_vale_tambem_para_refutada(self) -> None:
        self.assertEqual(_estados({"H9": ("5", "2", "refutada", "x.md")})["H9"].efectivo, "inconclusiva")

    def test_amostra_com_unidade_le_o_numero_a_cabeca(self) -> None:
        self.assertEqual(_estados({"H6": ("512 conversas", "9", "confirmada", "x.md")})["H6"].efectivo, "confirmada")
        self.assertEqual(_estados({"H6": ("cerca de 600", "9", "confirmada", "x.md")})["H6"].efectivo, "inconclusiva")

    def test_o_registo_real_de_hoje_da_nove_inconclusivas(self) -> None:
        caminho = RAIZ / "docs/tecnica/evidencia/validacao/Registo_Hipoteses.md"
        reais = regras.estados(
            registo.ler(caminho), entradas.VAZIO, regras.resolvedor(caminho.parent, RAIZ)
        )
        if any(e.declarado for e in reais.values()):
            self.skipTest("o Registo já tem estados declarados; este ensaio era para o Registo vazio")
        self.assertEqual({e.efectivo for e in reais.values()}, {"inconclusiva"})


class TestResolvedor(unittest.TestCase):
    def test_ligacoes_crases_e_caminho_nu(self) -> None:
        with TemporaryDirectory() as d:
            raiz = Path(d) / "repo"
            pasta = raiz / "docs/validacao"
            pasta.mkdir(parents=True)
            (pasta / "H3.md").write_text("sintético", encoding="utf-8")
            (raiz / "docs/outro.md").write_text("sintético", encoding="utf-8")
            (Path(d) / "fora-da-arvore.md").write_text("sintético", encoding="utf-8")
            existe = regras.resolvedor(pasta, raiz)
            self.assertTrue(existe("[`H3.md`](H3.md) §3"))
            self.assertTrue(existe("`docs/outro.md`"))
            self.assertTrue(existe("H3.md#tabela"))
            self.assertTrue(existe("[x](../outro.md)"))
            self.assertFalse(existe("Reunião de 12 de Novembro"))
            self.assertFalse(existe("[x](nao.md)"))
            self.assertFalse(existe("—"))
            self.assertFalse(existe("[x](../../../fora-da-arvore.md)"))


def _tabela_14_6() -> dict[str, str]:
    """A tabela do §6, lida do documento: gatilho → «Então…».

    O gatilho é a hipótese nomeada na coluna «Se acontecer…» (H3 e H4 partilham
    linha), ou `canal` para a linha da distribuição.
    """
    texto = DOC_14.read_text(encoding="utf-8")
    seccao = texto.split("## 6. Critérios de pivô e de paragem", 1)[1].split("\n## ", 1)[0]
    linhas = [l for l in seccao.splitlines() if l.startswith("|") and not re.match(r"\|\s*-", l)]
    tabela: dict[str, str] = {}
    for linha in linhas[1:]:
        se, entao = (c.strip() for c in linha.split("|")[1:3])
        nomeadas = re.findall(r"\bH\d\b", se)
        for h in nomeadas or ["canal"]:
            tabela[h] = entao
    return tabela


class TestMatriz(unittest.TestCase):
    def test_a_fonte_tem_as_linhas_que_o_ensaio_espera(self) -> None:
        self.assertEqual(sorted(_tabela_14_6()), ["H1", "H2", "H3", "H4", "H5", "H6", "canal"])

    def test_paragem_transcrita(self) -> None:
        texto = DOC_14.read_text(encoding="utf-8")
        self.assertIn(f"Paragem total: se {regras.PARAGEM}.", " ".join(texto.split()))

    def _accionadas(self, refutadas: tuple[str, ...], **resumo) -> list[regras.Accionada]:
        linhas = {h: ("600", "1", "refutada", "x.md") for h in refutadas}
        r = entradas.validar(sintetico.resumo(exportacao="x.csv", exportacao_sha256="ab" * 32, **resumo))
        return regras.matriz(_estados(linhas, r), r)

    def test_cada_falha_simulada_da_a_linha_que_a_fonte_lhe_da(self) -> None:
        fonte = _tabela_14_6()
        for h in registo.HIPOTESES:
            esperado = fonte.get(h, regras.SEM_LINHA)
            with self.subTest(h=h):
                self.assertEqual(self._accionadas((h,)), [regras.Accionada(h, esperado)])

    def test_h3_e_h4_juntas_dao_uma_linha(self) -> None:
        self.assertEqual(
            self._accionadas(("H3", "H4")),
            [regras.Accionada("H3, H4", _tabela_14_6()["H3"])],
        )

    def test_nenhum_canal_repetivel_acciona_e_por_medir_nao(self) -> None:
        self.assertEqual(
            [a.linha for a in self._accionadas((), canal_comercial_repetivel=False)],
            [_tabela_14_6()["canal"]],
        )
        self.assertEqual(self._accionadas(()), [])
        self.assertEqual(self._accionadas((), canal_comercial_repetivel=True), [])

    def test_ordem_da_fonte_e_sem_linha_no_fim(self) -> None:
        gatilhos = [a.gatilho for a in self._accionadas(("H9", "H6", "H1", "H2"))]
        self.assertEqual(gatilhos, ["H1", "H2", "H6", "H9"])

    def test_inconclusiva_nao_acciona(self) -> None:
        linhas = {"H1": ("", "", "refutada", "")}
        self.assertEqual(regras.matriz(_estados(linhas), entradas.VAZIO), [])


class TestParagem(unittest.TestCase):
    def _p(self, **campos) -> str:
        return regras.paragem_total(entradas.validar(sintetico.resumo(**campos)))[0]

    def test_casos(self) -> None:
        completo = {"semana_do_gate": 12, "canal_comercial_repetivel": False}
        self.assertEqual(self._p(), "nao_avaliavel")
        self.assertEqual(self._p(pagantes_recorrentes=2, semana_do_gate=11, canal_comercial_repetivel=False), "nao_avaliavel")
        self.assertEqual(self._p(pagantes_recorrentes=2, **completo), "verificada")
        self.assertEqual(self._p(pagantes_recorrentes=0, **completo), "verificada")
        self.assertEqual(self._p(pagantes_recorrentes=3, **completo), "nao_verificada")
        self.assertEqual(self._p(pagantes_recorrentes=2, semana_do_gate=12, canal_comercial_repetivel=True), "nao_verificada")

    def test_cada_dado_em_falta_sozinho_da_nao_avaliavel(self) -> None:
        completo = {"semana_do_gate": 12, "pagantes_recorrentes": 2, "canal_comercial_repetivel": False}
        for falta in completo:
            campos = {k: v for k, v in completo.items() if k != falta}
            with self.subTest(falta=falta):
                self.assertEqual(self._p(**campos), "nao_avaliavel")


class TestCarta(unittest.TestCase):
    def test_os_ids_sao_os_declaraveis_mais_os_derivados(self) -> None:
        ids = {i.id for i in regras.CARTA_5}
        derivados = {i.id for i in regras.CARTA_5 if i.hipoteses}
        self.assertEqual(derivados, {"P2", "P3", "F3"})
        self.assertEqual(ids - derivados, set(entradas.ITENS_DECLARAVEIS))

    def _avaliar(self, linhas: dict, raiz: Path, **resumo) -> dict[str, regras.Avaliacao]:
        r = entradas.validar(sintetico.resumo(exportacao="x.csv", exportacao_sha256="ab" * 32, **resumo))
        return {a.item.id: a for a in regras.carta(_estados(linhas, r), r, raiz)}

    def test_derivados(self) -> None:
        ok = ("600", "1", "confirmada", "x.md")
        with TemporaryDirectory() as d:
            a = self._avaliar({"H1": ok, "H9": ("8", "6", "confirmada", "x.md")}, Path(d))
            self.assertEqual(a["P2"].estado, "satisfeito")
            a = self._avaliar({"H1": ok}, Path(d))
            self.assertEqual(a["P2"].estado, "por_verificar")
            a = self._avaliar({"H1": ok, "H9": ("8", "4", "refutada", "x.md")}, Path(d))
            self.assertEqual(a["P2"].estado, "nao_satisfeito")

    def test_declarados_exigem_ficheiro_que_exista(self) -> None:
        with TemporaryDirectory() as d:
            raiz = Path(d)
            (raiz / "ev").mkdir()
            (raiz / "ev/f1.md").write_text("sintético", encoding="utf-8")
            a = self._avaliar(
                {},
                raiz,
                carta5={
                    "F1": {"estado": "satisfeito", "evidencia": "ev/f1.md"},
                    "F2": {"estado": "satisfeito", "evidencia": "ev/nao-existe.md"},
                    "F4": {"estado": "satisfeito"},
                    "F5": {"estado": "nao_satisfeito"},
                },
            )
        self.assertEqual(a["F1"].estado, "satisfeito")
        self.assertEqual(a["F2"].estado, "por_verificar")
        self.assertEqual(a["F4"].estado, "por_verificar")
        self.assertEqual(a["F5"].estado, "nao_satisfeito")
        self.assertEqual(a["C1"].estado, "por_verificar")


if __name__ == "__main__":
    unittest.main()
