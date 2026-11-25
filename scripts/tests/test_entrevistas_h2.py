"""Ensaios do `scripts/entrevistas_h2.py` (KAM-106).

Os «Testes Requeridos» do bloco pedem *fixtures* com o limiar de 14/20 itens e
15/30 PMEs, e os casos de fronteira 14 e 13. Estao em `TestFronteiraPorPME` e
`TestFronteiraDaAmostra`; o resto ensaia o que a ficha pode trazer de errado.

**Todas as fichas daqui sao sinteticas.** Os ids comecam por `SINT-` e nao ha
nenhum contacto nem telefone: a ficha nao tem colunas para isso, de proposito
(os contactos vivem no arquivo controlado).

Como o `test_validar_evidencia.py`, **nenhum portao corre estes ensaios**:
`scripts/` nao esta no `ci/thresholds.yaml` nem nas suites do `Makefile`.

    python -m unittest discover -s scripts/tests -t scripts
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
VALIDACAO = RAIZ / "docs" / "tecnica" / "evidencia" / "validacao"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "entrevistas_sinteticas.csv"

_spec = importlib.util.spec_from_file_location("entrevistas_h2", RAIZ / "scripts" / "entrevistas_h2.py")
assert _spec is not None and _spec.loader is not None
h2 = importlib.util.module_from_spec(_spec)
sys.modules["entrevistas_h2"] = h2
_spec.loader.exec_module(h2)


def linha(i: int, aceites: int = 20, **campos: str) -> dict[str, str]:
    """Uma entrevista sintetica completa, com `aceites` produtos aceites."""
    base = {
        "id_anonimo": f"SINT-{i:02d}",
        "data_entrevista": "2000-01-03",
        "categoria": "categoria-sintetica",
        "formal": "S",
        "n_empregados": "3",
        "canal_origem": h2.CANAIS[i % 5],
        "dor": "3",
        "comprovativos_semana": "4",
        "faixa_preco": "15-30",
        "cartao_internacional": "N",
        "categoria_vedada": "N",
        "disponivel_piloto": "N",
        "consentimento": "escrito",
    }
    for j, col in enumerate(h2.COLUNAS_PRODUTO):
        base[col] = "fixo" if j < aceites else "sob consulta"
    base.update(campos)
    return base


def csv_de(linhas: list[dict[str, str]], colunas=None, delim: str = ";") -> str:
    colunas = colunas or h2.COLUNAS
    corpo = [delim.join(colunas)]
    corpo += [delim.join(l.get(c, "") for c in colunas) for l in linhas]
    return "\n".join(corpo) + "\n"


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def ficheiro(self, texto: str, nome: str = "ficha.csv", bom: bool = False) -> Path:
        p = Path(self._dir.name) / nome
        p.write_text(("﻿" if bom else "") + texto, encoding="utf-8")
        return p

    def ler(self, linhas: list[dict[str, str]]):
        return h2.ler_ficha(self.ficheiro(csv_de(linhas)))

    def correr(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            codigo = h2.main(list(args))
        return codigo, out.getvalue(), err.getvalue()


class TestFronteiraPorPME(Base):
    def test_catorze_de_vinte_passa(self) -> None:
        self.assertTrue(self.ler([linha(1, aceites=14)]).completas[0].passa_h2)

    def test_treze_de_vinte_nao_passa(self) -> None:
        self.assertFalse(self.ler([linha(1, aceites=13)]).completas[0].passa_h2)

    def test_a_partir_de_conta_como_aceite_e_sob_consulta_nao(self) -> None:
        l = linha(1, aceites=0)
        for col in h2.COLUNAS_PRODUTO[:7]:
            l[col] = "a partir de"
        for col in h2.COLUNAS_PRODUTO[7:14]:
            l[col] = "fixo"
        self.assertEqual(self.ler([l]).completas[0].aceites, 14)


class TestFronteiraDaAmostra(Base):
    def amostra(self, n: int, passam: int) -> str:
        linhas = [linha(i, aceites=14 if i < passam else 13) for i in range(n)]
        c = self.ler(linhas).completas
        return h2.estado_h2(len(c), sum(e.passa_h2 for e in c))

    def test_quinze_de_trinta_confirma(self) -> None:
        self.assertEqual(self.amostra(30, 15), "confirmada")

    def test_catorze_de_trinta_refuta(self) -> None:
        self.assertEqual(self.amostra(30, 14), "refutada")

    def test_vinte_e_nove_completas_e_inconclusiva_mesmo_todas_a_passar(self) -> None:
        self.assertEqual(self.amostra(29, 29), "inconclusiva")
        texto = "\n".join(h2.relatorio(self.ler([linha(i) for i in range(29)])))
        self.assertIn("**inconclusiva**", texto)
        self.assertIn("Amostra abaixo de 30", texto)

    def test_acima_de_trinta_usa_cinquenta_por_cento_de_n(self) -> None:
        self.assertEqual(self.amostra(32, 16), "confirmada")
        self.assertEqual(self.amostra(32, 15), "refutada")

    def test_refutada_lista_o_pivo_e_os_tickets(self) -> None:
        linhas = [linha(i, aceites=13) for i in range(30)]
        texto = "\n".join(h2.relatorio(self.ler(linhas)))
        self.assertIn("refutada", texto)
        for alvo in ("KAM-043", "KAM-061", "mensagem comercial", "atendimento e disponibilidade"):
            self.assertIn(alvo, texto)


class TestCompletude(Base):
    def test_celula_vazia_torna_incompleta_e_nao_conta(self) -> None:
        l = linha(1)
        l["produto_20"] = ""
        r = self.ler([l, linha(2)])
        self.assertEqual([e.id_anonimo for e in r.completas], ["SINT-02"])
        self.assertEqual(r.incompletas, ["SINT-01"])

    def test_sem_consentimento_fica_fora_e_e_contado_a_parte(self) -> None:
        vazia = {c: "" for c in h2.COLUNAS[1:]}
        vazia.update(id_anonimo="SINT-01", consentimento="nao")
        r = self.ler([vazia, linha(2, consentimento="gravado")])
        self.assertEqual(r.sem_consentimento, ["SINT-01"])
        self.assertEqual(len(r.completas), 1)

    def test_consentimento_nao_com_respostas_e_recusado(self) -> None:
        with self.assertRaises(h2.FichaInvalida):
            self.ler([linha(1, consentimento="nao")])

    def test_consentimento_vazio_e_incompleta(self) -> None:
        self.assertEqual(self.ler([linha(1, consentimento="")]).incompletas, ["SINT-01"])

    def test_linha_toda_vazia_ignora_se(self) -> None:
        texto = csv_de([linha(1)]) + ";" * (len(h2.COLUNAS) - 1) + "\n"
        self.assertEqual(len(h2.ler_ficha(self.ficheiro(texto)).completas), 1)


class TestFichaInvalida(Base):
    def assertInvalida(self, texto: str) -> None:
        codigo, out, err = self.correr(str(self.ficheiro(texto)))
        self.assertEqual(codigo, 2)
        self.assertEqual(out, "")
        self.assertIn("ficha invalida", err)

    def test_valor_fora_do_dominio_falha_mesmo_em_linha_incompleta(self) -> None:
        self.assertInvalida(csv_de([linha(1, produto_01="fixa", produto_02="")]))

    def test_empregados_negativo(self) -> None:
        self.assertInvalida(csv_de([linha(1, n_empregados="-1")]))

    def test_dor_fora_de_um_a_cinco(self) -> None:
        self.assertInvalida(csv_de([linha(1, dor="6")]))

    def test_canal_desconhecido(self) -> None:
        self.assertInvalida(csv_de([linha(1, canal_origem="C6")]))

    def test_faixa_desconhecida(self) -> None:
        self.assertInvalida(csv_de([linha(1, faixa_preco="30")]))

    def test_data_mal_escrita(self) -> None:
        self.assertInvalida(csv_de([linha(1, data_entrevista="03/01/2000")]))

    def test_id_repetido(self) -> None:
        self.assertInvalida(csv_de([linha(1), linha(1)]))

    def test_colunas_trocadas(self) -> None:
        cols = list(h2.COLUNAS)
        cols[1], cols[2] = cols[2], cols[1]
        self.assertInvalida(csv_de([linha(1)], colunas=cols))

    def test_coluna_a_mais(self) -> None:
        self.assertInvalida(csv_de([linha(1)], colunas=list(h2.COLUNAS) + ["telefone"]))

    def test_mais_celulas_do_que_colunas(self) -> None:
        self.assertInvalida(csv_de([linha(1)]).rstrip("\n") + ";extra\n")


class TestFormatoDoCSV(Base):
    def test_virgula_e_bom_tambem_se_leem(self) -> None:
        p = self.ficheiro(csv_de([linha(1)], delim=","), bom=True)
        self.assertEqual(len(h2.ler_ficha(p).completas), 1)


class TestSinalDeH1(Base):
    def test_faixas_contam_por_valor(self) -> None:
        linhas = [linha(i, faixa_preco=f) for i, f in enumerate(["<15", "30-60", "30-60", ">60"])]
        texto = "\n".join(h2.relatorio(self.ler(linhas)))
        self.assertIn("| <15 | 1 |", texto)
        self.assertIn("| 15-30 | 0 |", texto)
        self.assertIn("| 30-60 | 2 |", texto)
        self.assertIn("| >60 | 1 |", texto)

    def test_vedada_disponivel_nao_e_elegivel(self) -> None:
        linhas = [linha(i, disponivel_piloto="S") for i in range(30)]
        for l in linhas[:21]:
            l["categoria_vedada"] = "S"
        texto = "\n".join(h2.relatorio(self.ler(linhas)))
        self.assertIn("Disponíveis para piloto gratuito de 30 dias: **30 de 30", texto)
        self.assertIn("Elegíveis (disponíveis, com NIF e fora de categoria vedada): **9 de 30", texto)
        self.assertIn("Problema de distribuição", texto)

    def test_sem_nif_nao_e_elegivel(self) -> None:
        linhas = [linha(i, disponivel_piloto="S", formal="N" if i < 21 else "S") for i in range(30)]
        texto = "\n".join(h2.relatorio(self.ler(linhas)))
        self.assertIn("com NIF e fora de categoria vedada): **9 de 30", texto)
        self.assertIn("Problema de distribuição", texto)

    def test_dez_elegiveis_nao_e_problema(self) -> None:
        linhas = [linha(i, disponivel_piloto="S" if i < 10 else "N") for i in range(30)]
        self.assertNotIn("Problema de distribuição", "\n".join(h2.relatorio(self.ler(linhas))))

    def test_regra_dos_dez_espera_pelas_trinta(self) -> None:
        texto = "\n".join(h2.relatorio(self.ler([linha(1)])))
        self.assertNotIn("Problema de distribuição", texto)
        self.assertIn("só se aplica depois", texto)


class TestEntradasParaOutrosTickets(Base):
    def test_zero_de_zero_e_nao_medido(self) -> None:
        texto = "\n".join(h2.relatorio(h2.Leitura()))
        self.assertIn("cartão internacional (KAM-102, D5): **0 de 0 (não medido)**", texto)
        self.assertNotIn("0.0%", texto)

    def test_vedada_e_cartao_contam_em_absoluto(self) -> None:
        linhas = [linha(1, categoria_vedada="S", cartao_internacional="S"), linha(2)]
        texto = "\n".join(h2.relatorio(self.ler(linhas)))
        self.assertIn("(KAM-088): **1 de 2 (50.0%)**", texto)
        self.assertIn("(KAM-102, D5): **1 de 2 (50.0%)**", texto)

    def test_lista_de_alvos(self) -> None:
        corpo = "\n".join(
            [
                ";".join(h2.COLUNAS_LISTA),
                "SINT-01;categoria-sintetica;S;C1;alvo",
                "SINT-02;categoria-sintetica;N;C2;alvo",
                "SINT-03;categoria-sintetica;N;C3;suplente",
                "SINT-04;categoria-sintetica;N;C4;suplente",
            ]
        )
        self.assertEqual(h2.ler_lista(self.ficheiro(corpo, "lista.csv")), (2, 2, 1))


class TestCanais(Base):
    def test_tecto_de_quarenta_por_cento(self) -> None:
        # O resto espalha-se por C2..C4, para que so o C1 possa passar o tecto.
        dentro = [linha(i, canal_origem="C1" if i < 12 else f"C{2 + i % 3}") for i in range(30)]
        fora = [linha(i, canal_origem="C1" if i < 13 else f"C{2 + i % 3}") for i in range(30)]
        self.assertIn("dentro do tecto", "\n".join(h2.relatorio(self.ler(dentro))))
        self.assertIn("acima do tecto", "\n".join(h2.relatorio(self.ler(fora))))

    def rondas(self, *linhas: str) -> dict[str, tuple[int, int]]:
        corpo = "\n".join([";".join(h2.COLUNAS_RONDAS), *linhas])
        return h2.ler_rondas(self.ficheiro(corpo, "rondas.csv"))

    def test_seis_em_duas_rondas_e_repetivel(self) -> None:
        r = self.rondas("C1;1;2000-01-03;3", "C1;2;2000-01-10;3")
        self.assertEqual(r["C1"], (6, 2))
        self.assertTrue(h2.repetivel(*r["C1"]))

    def test_seis_numa_so_ronda_nao_e(self) -> None:
        self.assertFalse(h2.repetivel(*self.rondas("C2;1;2000-01-03;6")["C2"]))

    def test_cinco_em_duas_rondas_nao_e(self) -> None:
        self.assertFalse(h2.repetivel(*self.rondas("C3;1;2000-01-03;3", "C3;2;2000-01-10;2")["C3"]))

    def test_ronda_sem_entrega_nao_conta_como_ronda(self) -> None:
        r = self.rondas("C4;1;2000-01-03;6", "C4;2;2000-01-10;0")
        self.assertEqual(r["C4"], (6, 1))

    def test_nenhum_repetivel_pede_a_decisao_de_distribuicao(self) -> None:
        r = self.rondas("C5;1;2000-01-03;1")
        texto = "\n".join(h2.relatorio(self.ler([linha(1)]), rondas=r))
        self.assertIn("Nenhum canal repetível", texto)

    def test_um_repetivel_basta_para_nao_pedir_a_decisao(self) -> None:
        r = self.rondas("C1;1;2000-01-03;3", "C1;2;2000-01-10;3", "C5;1;2000-01-03;1")
        texto = "\n".join(h2.relatorio(self.ler([linha(1)]), rondas=r))
        self.assertIn("| C1 | 0 | 6 | 2 | sim |", texto)
        self.assertNotIn("Nenhum canal repetível", texto)

    def test_ronda_com_celula_vazia_falha(self) -> None:
        with self.assertRaises(h2.FichaInvalida):
            self.rondas("C1;1;;3")


class TestPrazoDaSemanaQuatro(Base):
    def test_conta_so_as_anteriores_ao_dia_vinte_e_nove(self) -> None:
        linhas = [linha(1, data_entrevista="2000-01-28"), linha(2, data_entrevista="2000-01-29")]
        codigo, out, _ = self.correr(str(self.ficheiro(csv_de(linhas))), "--inicio", "2000-01-01")
        self.assertEqual(codigo, 0)
        self.assertIn("Completas até ao fim da semana 4 (antes de 2000-01-29): **1**; fora do prazo: **1**", out)
        self.assertIn("Critério 2 por cumprir", out)


class TestSintetico(Base):
    def test_ficha_sintetica_sai_marcada(self) -> None:
        codigo, out, _ = self.correr(str(FIXTURE), "--resumo")
        self.assertEqual(codigo, 0)
        self.assertIn("FICHA SINTÉTICA", out)
        self.assertIn("direccional", out)
        self.assertTrue(out.startswith("# H1 e H2"))

    def test_basta_uma_linha_sintetica_para_o_aviso(self) -> None:
        linhas = [linha(1, id_anonimo="P-01"), linha(2)]
        self.assertIn("FICHA SINTÉTICA", "\n".join(h2.relatorio(self.ler(linhas))))

    def test_ids_reais_nao_levam_o_aviso(self) -> None:
        texto = "\n".join(h2.relatorio(self.ler([linha(1, id_anonimo="P-01")])))
        self.assertNotIn("FICHA SINTÉTICA", texto)

    def test_a_fixture_so_tem_ids_sinteticos(self) -> None:
        r = h2.ler_ficha(FIXTURE)
        ids = [e.id_anonimo for e in r.completas] + r.incompletas + r.sem_consentimento
        self.assertEqual(len(ids), 32)
        self.assertTrue(all(i.startswith(h2.PREFIXO_SINTETICO) for i in ids))


class TestModelosNoRepositorio(Base):
    """Os modelos vazios em `validacao/` tem o cabecalho que o script le, e zero linhas."""

    def test_ficha(self) -> None:
        r = h2.ler_ficha(VALIDACAO / "Entrevistas_Ficha.csv")
        self.assertEqual((r.completas, r.incompletas, r.sem_consentimento), ([], [], []))

    def test_rondas(self) -> None:
        r = h2.ler_rondas(VALIDACAO / "Canais_Rondas.csv")
        self.assertEqual(set(r.values()), {(0, 0)})

    def test_lista(self) -> None:
        self.assertEqual(h2.ler_lista(VALIDACAO / "PMEs_Lista_Alvo.csv"), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
