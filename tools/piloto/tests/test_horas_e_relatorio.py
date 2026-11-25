"""O registo de horas e o relatorio semanal sem conteudo nem telefones (KAM-109).

«Testes Requeridos»: ensaio do relatorio sobre dados sinteticos, e verificacao
de que nao contem conteudo de conversas nem telefones. A guarda corre **primeiro
sobre a entrada**, como canario: um detector que devolvesse sempre «limpo»
passava este ficheiro inteiro.
"""

from __future__ import annotations

import datetime as dt
import unittest

from piloto import horas, relatorio
from piloto.tests import fabrica as f

D = dt.timedelta(days=1)
REGISTO = (
    "dia,pme,minutos,categoria\n"
    "2027-01-05,P01,45,onboarding\n"
    "2027-01-06,P01,30,incidente\n"
    "2027-01-06,-,20,outro\n"
    "2027-01-12,P02,60,t2\n"
)


class TestHoras(unittest.TestCase):
    def test_le_e_agrega_por_semana(self) -> None:
        blocos = horas.ler(REGISTO)
        semana1 = horas.por_pme(blocos, f.INICIO, f.INICIO + 6 * D)
        self.assertEqual(semana1["P01"], {"minutos": 75, "incidentes": 1})
        self.assertEqual(semana1["-"], {"minutos": 20, "incidentes": 0})
        self.assertNotIn("P02", semana1)

    def test_recusa_notas_categorias_e_minutos_fora(self) -> None:
        for texto in (
            "dia,pme,minutos,categoria,notas\n2027-01-05,P01,45,t2,ligou o dono\n",
            "dia,pme,minutos,categoria\n2027-01-05,P01,45,conversa\n",
            "dia,pme,minutos,categoria\n2027-01-05,P01,0,t2\n",
            "dia,pme,minutos,categoria\n2027-01-05,P01,721,t2\n",
            "dia,pme,minutos,categoria\n2027-01-05,Loja,10,t2\n",
            "dia,pme,minutos,categoria\n05/01/2027,P01,10,t2\n",
        ):
            with self.subTest(texto=texto), self.assertRaises(horas.RegistoInvalido):
                horas.ler(texto)


class TestRelatorio(unittest.TestCase):
    def setUp(self) -> None:
        pmes = [
            f.pme(1, dias=f.dias_activos(f.INICIO, f.INICIO + 20 * D),
                  ciclos=[f.ciclo_pago(f.INICIO, dia=3)]),
            f.pme(2, activada=f.INICIO + 3 * D),
            f.pme(3, activada=None),
            f.pme(4, na_coorte=False),
        ]
        self.exportacao = f.coorte(pmes, f.INICIO + 20 * D)
        self.blocos = horas.ler(REGISTO)

    def _gerar(self, semana: int = 1) -> str:
        return relatorio.gerar(self.exportacao, self.blocos, f.INICIO, semana, "ab" * 32)

    def test_o_canario_morde_na_entrada(self) -> None:
        telefone = "9" + "23" + "456" + "789"
        for texto in (f.tenant(1), telefone, f"+244{telefone}", f"{telefone[:3]}-{telefone[3:6]}-{telefone[6:]}"):
            with self.subTest(texto=texto), self.assertRaises(relatorio.RelatorioRecusado):
                relatorio.verificar_sem_pii(f"| P01 | {texto} |")

    def test_um_sha256_em_hex_nao_e_telefone(self) -> None:
        relatorio.verificar_sem_pii("sha256 `" + "9" * 9 + "a" * 55 + "`")
        relatorio.verificar_sem_pii("sha256 `" + "a" * 55 + "9" * 9 + "`")

    def test_o_relatorio_sintetico_passa_a_guarda_e_nao_tem_os_tenants(self) -> None:
        texto = self._gerar()
        relatorio.verificar_sem_pii(texto)
        for n in range(1, 5):
            self.assertNotIn(f.tenant(n), texto)
        self.assertIn("DADOS SINTÉTICOS", texto)

    def test_as_sete_colunas_e_os_valores_da_semana(self) -> None:
        linhas = {l.split(" | ")[0].strip("| "): l for l in self._gerar().splitlines() if l.startswith("| ")}
        self.assertEqual(linhas["PME"].count("|"), len(relatorio.COLUNAS) + 1)
        # P01: 7 conversas, 1 ciclo pago no dia 3, custo 7 x 0,014, 1h15 de operador e 1 incidente.
        self.assertEqual(linhas["P01"], "| P01 | 6 | não | 7 | 0 | 1 | 0.10 | 1 | 1h15 |")
        self.assertIn("| P03 | — | — | 0 |", linhas["P03"])
        self.assertNotIn("P04", linhas)
        self.assertIn("| Sem PME |", self._gerar())

    def test_a_activa_usa_a_definicao_do_protocolo(self) -> None:
        # Na semana 2 a P01 tem 14 dias de actividade: activa.
        linha = next(l for l in self._gerar(2).splitlines() if l.startswith("| P01 "))
        self.assertIn("| sim |", linha)

    def test_semana_incompleta_nao_se_emite(self) -> None:
        self._gerar(3)  # dias 14 a 20: o ultimo dia exportado fecha-a
        with self.assertRaises(ValueError):
            self._gerar(4)

    def test_um_relatorio_contaminado_nao_sai(self) -> None:
        # Se alguem trocasse o ordinal pelo tenant_id, a guarda apanhava-o.
        original = relatorio.verificar_sem_pii
        visto: list[str] = []
        relatorio.verificar_sem_pii = lambda texto: visto.append(texto) or original(texto)
        try:
            self._gerar()
        finally:
            relatorio.verificar_sem_pii = original
        self.assertEqual(len(visto), 1, "o gerar tem de passar o texto inteiro pela guarda")
        with self.assertRaises(relatorio.RelatorioRecusado):
            original(visto[0].replace("| P01 |", f"| {f.tenant(1)} |"))


if __name__ == "__main__":
    unittest.main()
