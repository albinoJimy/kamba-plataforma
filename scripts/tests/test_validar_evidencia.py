"""Ensaios do `scripts/validar_evidencia.py` (KAM-100).

**Existem porque uma revisao adversarial os pediu, e quatro deles sao de
regressao.** O validador foi entregue na primeira versao sem ensaio nenhum, e a
revisao encontrou-lhe quatro defeitos — todos da mesma familia: **dar verde
sobre um ficheiro que nao cumpre**. Num instrumento que o KAM-101, o KAM-103, o
KAM-104 e o KAM-105 citam nos «Testes Requeridos», um falso verde nao e um bug: e
uma prova de conformidade que nao prova nada.

Os quatro, cada um com a sua classe aqui:

    TestLinhaTruncada       uma linha com 3 das 12 colunas passava o --completo
    TestNaoMedido           108 celulas em `NÃO MEDIDO` passavam o --completo
    TestGlossario           um glossario antes do cabecalho dava falso positivo
    TestEstadoPorIgualdade  `NÃO CONFIRMADO` passava, porque contem `CONFIRMADO`

**Nenhum portao corre estes ensaios**, e isso esta medido: `scripts/` nao esta
nos padroes de `ci/thresholds.yaml`, nao esta no `SUITES_DE_TOOLS` do `Makefile`
— que descobre suites por `tools/*/tests/test_*.py` — e nao e nomeado no
`ci.yaml`. Liga-los a um portao muda o que o gate 4 passa a exigir, e isso e
decisao do fundador; fica devolvido no §6, item 7, do
`docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md`.

    python -m unittest discover -s scripts/tests -t scripts
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# O validador vive em `scripts/`, que nao e um pacote: carrega-se pelo caminho.
# E a consequencia de o bloco do ticket fixar `scripts/validar_evidencia.py`, e
# fica a vista em vez de se resolver com um `sys.path` a mexer.
_spec = importlib.util.spec_from_file_location(
    "validar_evidencia", RAIZ / "scripts" / "validar_evidencia.py"
)
assert _spec is not None and _spec.loader is not None
ve = importlib.util.module_from_spec(_spec)
sys.modules["validar_evidencia"] = ve
_spec.loader.exec_module(ve)


CABECALHO_COMPLETO = """# Um ficheiro de evidencia

| Campo | Valor |
|---|---|
| Estado | CONFIRMADO |
| Fonte | uma fonte primaria |
| Data | 2026-11-06 |
| Dono | Fundador |
"""


def escrever(pasta: str, nome: str, texto: str) -> Path:
    caminho = Path(pasta) / nome
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def folha(linhas: list[str], cabecalho: list[str] | None = None) -> str:
    """Uma folha de hipoteses com o cabecalho do esquema e as linhas dadas."""
    colunas = cabecalho if cabecalho is not None else list(ve.COLUNAS_DO_REGISTO)
    return (
        "# Registo\n\n"
        + "| "
        + " | ".join(colunas)
        + " |\n|"
        + "---|" * len(colunas)
        + "\n"
        + "".join(linhas)
    )


def linha_completa(h: str) -> str:
    """Uma linha com as doze celulas preenchidas e um estado valido."""
    celulas = [
        h, "enunciado", "limiar", "metodo", "20", "19 de 20",
        "confirmada", "uma fonte", "uma decisao", "um pivo", "Fundador",
        "2026-11-06",
    ]
    return "| " + " | ".join(celulas) + " |\n"


class TestFicheiroDeEvidencia(unittest.TestCase):
    def test_um_ficheiro_com_as_quatro_declaracoes_passa(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "bom.md", CABECALHO_COMPLETO)
            self.assertEqual(ve.verificar_ficheiro(f), [])

    def test_cada_declaracao_em_falta_e_um_achado(self) -> None:
        for campo in ve.DECLARACOES:
            with self.subTest(campo=campo):
                texto = "\n".join(
                    l for l in CABECALHO_COMPLETO.splitlines() if not l.startswith(f"| {campo} ")
                )
                with tempfile.TemporaryDirectory() as pasta:
                    f = escrever(pasta, "mau.md", texto)
                    achados = ve.verificar_ficheiro(f)
                self.assertEqual([a.onde for a in achados], [campo])

    def test_a_forma_de_prosa_tambem_conta(self) -> None:
        texto = (
            "# Um ficheiro\n\n**Estado:** INDÍCIO\n**Fonte:** um BSP\n"
            "**Data:** 2026-11-06\n**Dono:** Responsável de Produto\n"
        )
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "prosa.md", texto)
            self.assertEqual(ve.verificar_ficheiro(f), [])


class TestGlossario(unittest.TestCase):
    """Regressao: uma tabela antes do cabecalho dava falso positivo.

    O `declaracoes` aceitava qualquer linha de duas celulas em **qualquer**
    tabela, e o `setdefault` fixava a primeira. Um ficheiro conforme era
    recusado por ter antes um glossario, e a mensagem acusava «um quarto
    estado». Quatro dos 23 achados que o ticket devolveu eram isto.
    """

    GLOSSARIO = "| Estado | Significado |\n|---|---|\n| CONFIRMADO | fonte primaria |\n"

    def test_um_glossario_depois_do_cabecalho_nao_engana(self) -> None:
        """O caso real: tres ficheiros desta pasta tem o glossario mais abaixo."""
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "glossario.md",
                         CABECALHO_COMPLETO + "\n## Escala\n\n" + self.GLOSSARIO)
            achados = ve.verificar_ficheiro(f)
        self.assertEqual(achados, [], [str(a) for a in achados])

    def test_um_glossario_antes_do_cabecalho_tambem_nao_engana(self) -> None:
        """O marcador e `| Campo | Valor |`, e nao a posicao.

        A primeira versao desta correccao usava «a primeira tabela», e trocava um
        falso positivo por outro: aqui a primeira tabela nao e o cabecalho, e as
        quatro declaracoes deixavam de ser lidas.
        """
        corpo = CABECALHO_COMPLETO.split("\n", 2)[2]
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "glossario.md",
                         "# Um ficheiro\n\n" + self.GLOSSARIO + "\n" + corpo)
            achados = ve.verificar_ficheiro(f)
        self.assertEqual(achados, [], [str(a) for a in achados])

    def test_sem_marcador_cai_na_primeira_tabela(self) -> None:
        """Um ficheiro sem `| Campo | Valor |` ainda e lido pelo melhor palpite."""
        texto = (
            "# Um ficheiro\n\n| Chave | Valor |\n|---|---|\n| Estado | INDÍCIO |\n"
            "| Fonte | um BSP |\n| Data | 2026-11-06 |\n| Dono | Produto |\n"
        )
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "sem_marcador.md", texto)
            achados = ve.verificar_ficheiro(f)
        self.assertEqual(achados, [], [str(a) for a in achados])

    def test_uma_tabela_de_dados_depois_do_cabecalho_nao_engana(self) -> None:
        """O caso do `Meta_Perguntas.md`: `| Estado | por enviar |` numa tabela."""
        texto = CABECALHO_COMPLETO + (
            "\n## Perguntas\n\n| Campo | Valor |\n|---|---|\n| Estado | por enviar |\n"
        )
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "perguntas.md", texto)
            achados = ve.verificar_ficheiro(f)
        self.assertEqual(achados, [], [str(a) for a in achados])

    def test_o_cabecalho_continua_a_ser_lido(self) -> None:
        """O controlo: se a restricao cortasse a mais, nada passaria a ser lido."""
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "bom.md", CABECALHO_COMPLETO)
            self.assertEqual(ve.declaracoes(f.read_text(encoding="utf-8"))["Estado"],
                             "CONFIRMADO")


class TestEstadoPorIgualdade(unittest.TestCase):
    """Regressao: a comparacao era por subcadeia, e `NÃO CONFIRMADO` passava."""

    def test_os_tres_estados_passam(self) -> None:
        for estado in ve.ESTADOS:
            with self.subTest(estado=estado):
                self.assertEqual(ve._estado_declarado(estado), estado)

    def test_um_qualificador_antes_e_recusado(self) -> None:
        for mau in ("NÃO CONFIRMADO", "QUASE CONFIRMADO", "PARCIALMENTE CONFIRMADO",
                    "NAO VERIFICADO POR NINGUEM TODAVIA SIM", "SEM INDÍCIO"):
            with self.subTest(estado=mau):
                self.assertIsNone(
                    ve._estado_declarado(mau),
                    f"{mau!r} passou: a escala deixa de dizer o que diz",
                )

    def test_enfase_e_cauda_depois_de_separador_toleram_se(self) -> None:
        """O conjunto escreve-os assim, e recusa-los era recusar os ficheiros reais."""
        for bom in ("**CONFIRMADO**", "CONFIRMADO (fonte primária)",
                    "CONFIRMADO — fonte primária", "`INDÍCIO`", "CONFIRMADO.",
                    "NÃO VERIFICADO: ninguém mediu"):
            with self.subTest(estado=bom):
                self.assertIsNotNone(ve._estado_declarado(bom), f"{bom!r} foi recusado")

    def test_o_ficheiro_com_um_quarto_estado_e_recusado(self) -> None:
        texto = CABECALHO_COMPLETO.replace("| Estado | CONFIRMADO |",
                                           "| Estado | NÃO CONFIRMADO |")
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "quarto.md", texto)
            achados = ve.verificar_ficheiro(f)
        self.assertEqual([a.onde for a in achados], ["Estado"])


class TestRegistoConforme(unittest.TestCase):
    def test_as_nove_linhas_completas_passam_o_completo(self) -> None:
        texto = folha([linha_completa(h) for h in ve.HIPOTESES])
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, vazias, total = ve.verificar_registo(f, completo=True)
        self.assertEqual(achados, [], [str(a) for a in achados])
        self.assertEqual((vazias, total), (0, 9 * 12))

    def test_uma_hipotese_em_falta_e_um_achado(self) -> None:
        texto = folha([linha_completa(h) for h in ve.HIPOTESES[:-1]])
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, _, _ = ve.verificar_registo(f, completo=False)
        self.assertTrue(any("falta a linha H9" in a.porque for a in achados))

    def test_uma_hipotese_a_mais_e_um_achado(self) -> None:
        texto = folha([linha_completa(h) for h in list(ve.HIPOTESES) + ["H10"]])
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, _, _ = ve.verificar_registo(f, completo=False)
        self.assertTrue(any("linhas a mais" in a.porque for a in achados))

    def test_as_colunas_fora_de_ordem_sao_um_achado(self) -> None:
        trocadas = list(ve.COLUNAS_DO_REGISTO)
        trocadas[1], trocadas[2] = trocadas[2], trocadas[1]
        texto = folha([linha_completa(h) for h in ve.HIPOTESES], cabecalho=trocadas)
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, _, _ = ve.verificar_registo(f, completo=False)
        self.assertTrue(any("ordem" in a.porque for a in achados))

    def test_sem_tabela_de_hipoteses_e_um_achado(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", "# Nada\n\ntexto\n")
            achados, _, _ = ve.verificar_registo(f, completo=False)
        self.assertTrue(any("primeira coluna seja" in a.porque for a in achados))


class TestLinhaTruncada(unittest.TestCase):
    """Regressao, e e o achado mais grave: o denominador era a linha.

    Uma linha com 3 das 12 colunas dava «3 de 3 preenchidas» e o `--completo`
    saia **verde** — no modo que o criterio de saida do EPIC-10 §2 usa como
    prova de «9 de 9 linhas completas».
    """

    def test_linhas_truncadas_nao_passam_o_completo(self) -> None:
        texto = folha([f"| {h} | enunciado | limiar |\n" for h in ve.HIPOTESES])
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, vazias, total = ve.verificar_registo(f, completo=True)
        self.assertEqual(total, 9 * 12, "o denominador tem de ser o esquema")
        self.assertEqual(vazias, 9 * 9, "nove celulas em falta por linha")
        self.assertTrue(achados)
        self.assertTrue(
            any("celula em falta" in a.porque for a in achados),
            "a mensagem tem de distinguir «em falta» de «vazia»",
        )

    def test_o_check_conta_as_mesmas_vazias_sem_falhar(self) -> None:
        texto = folha([f"| {h} | enunciado | limiar |\n" for h in ve.HIPOTESES])
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, vazias, total = ve.verificar_registo(f, completo=False)
        self.assertEqual((vazias, total), (81, 108))
        self.assertEqual(achados, [], [str(a) for a in achados])

    def test_celulas_a_mais_sao_um_achado(self) -> None:
        texto = folha([linha_completa(h).rstrip("\n")[:-1] + " | a mais |\n"
                       for h in ve.HIPOTESES])
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, _, _ = ve.verificar_registo(f, completo=False)
        self.assertTrue(any("a mais" in a.porque for a in achados))


class TestNaoMedido(unittest.TestCase):
    """Regressao: uma folha inteira em `NÃO MEDIDO` passava o `--completo`."""

    def test_uma_folha_toda_em_nao_medido_nao_passa_o_completo(self) -> None:
        celulas = [ve.POR_MEDIR] * 12
        linhas = []
        for h in ve.HIPOTESES:
            suas = list(celulas)
            suas[0] = h
            linhas.append("| " + " | ".join(suas) + " |\n")
        texto = folha(linhas)
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, vazias, _ = ve.verificar_registo(f, completo=True)
        self.assertEqual(vazias, 0, "`NÃO MEDIDO` nao e uma celula vazia")
        self.assertEqual(
            len([a for a in achados if a.onde.endswith("/estado")]),
            len(ve.HIPOTESES),
            "cada linha tem de dar um achado de estado",
        )

    def test_nao_medido_no_estado_passa_o_check_e_falha_o_completo(self) -> None:
        linhas = []
        for h in ve.HIPOTESES:
            celulas = linha_completa(h).strip().strip("|").split("|")
            celulas = [c.strip() for c in celulas]
            celulas[6] = ve.POR_MEDIR
            linhas.append("| " + " | ".join(celulas) + " |\n")
        texto = folha(linhas)
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            do_check, _, _ = ve.verificar_registo(f, completo=False)
            do_completo, _, _ = ve.verificar_registo(f, completo=True)
        self.assertEqual(do_check, [], [str(a) for a in do_check])
        self.assertEqual(len(do_completo), len(ve.HIPOTESES))

    def test_nao_medido_no_resultado_com_inconclusiva_passa(self) -> None:
        """A regra do §2 do registo: sem numero, `NÃO MEDIDO` e `inconclusiva`."""
        linhas = []
        for h in ve.HIPOTESES:
            celulas = [c.strip() for c in linha_completa(h).strip().strip("|").split("|")]
            celulas[5] = ve.POR_MEDIR
            celulas[6] = "inconclusiva"
            linhas.append("| " + " | ".join(celulas) + " |\n")
        texto = folha(linhas)
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            achados, _, _ = ve.verificar_registo(f, completo=True)
        self.assertEqual(achados, [], [str(a) for a in achados])

    def test_um_estado_inventado_e_um_achado_nos_dois_modos(self) -> None:
        linhas = []
        for h in ve.HIPOTESES:
            celulas = [c.strip() for c in linha_completa(h).strip().strip("|").split("|")]
            celulas[6] = "quase confirmada"
            linhas.append("| " + " | ".join(celulas) + " |\n")
        texto = folha(linhas)
        with tempfile.TemporaryDirectory() as pasta:
            f = escrever(pasta, "Registo_Hipoteses.md", texto)
            for completo in (False, True):
                with self.subTest(completo=completo):
                    achados, _, _ = ve.verificar_registo(f, completo=completo)
                    self.assertEqual(len(achados), len(ve.HIPOTESES))


class TestOsFicheirosDesteTicket(unittest.TestCase):
    """Os dois artefactos do KAM-100, contra o validador que o KAM-100 entrega."""

    def test_o_h3_declara_as_quatro(self) -> None:
        f = RAIZ / "docs/tecnica/evidencia/validacao/H3_Coexistencia_244.md"
        achados = ve.verificar_ficheiro(f)
        self.assertEqual(achados, [], [str(a) for a in achados])

    def test_o_registo_passa_o_check_e_falha_o_completo(self) -> None:
        """Nasce por preencher: e isso que o `check` verde e o `--completo` dizem."""
        f = RAIZ / "docs/tecnica/evidencia/validacao/Registo_Hipoteses.md"
        do_check, vazias, total = ve.verificar_registo(f, completo=False)
        self.assertEqual(do_check, [], [str(a) for a in do_check])
        self.assertEqual(total, 9 * 12)
        self.assertGreater(vazias, 0)
        do_completo, _, _ = ve.verificar_registo(f, completo=True)
        self.assertEqual(len(do_completo), vazias)

    def test_o_esquema_e_o_do_epic(self) -> None:
        """As doze colunas, pela ordem, como os «Detalhes Tecnicos» as fixam."""
        bloco = (RAIZ / "specs/EPIC-10_Spikes_Validacao_Gates.md").read_text(
            encoding="utf-8"
        )
        esquema = (
            "`H | enunciado | limiar | método | amostra n | resultado | estado | "
            "fonte | decisão | pivô aplicável (14 §6) | dono | data`"
        )
        self.assertIn(esquema, bloco)
        for coluna in ve.COLUNAS_DO_REGISTO:
            self.assertIn(coluna, esquema)


if __name__ == "__main__":
    unittest.main()
