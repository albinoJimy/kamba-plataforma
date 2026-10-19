"""Contagens derivadas: §3.1 por epic, intervalos, soma contra TOTAL, e o §1.

Uma contagem escrita a mao num segundo sitio deixa de acompanhar. O
`lint_contagens` (KAM-158) fechou a classe na **prosa**; as tabelas sao o outro
sitio, e sao estas.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from lint_backlog import modelo
from lint_backlog.cli import contagens
from lint_backlog.tests.conjunto import Conjunto, kam

MINIMO = 1


class Base(unittest.TestCase):
    def achados(self, conjunto: Conjunto) -> list[str]:
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, True)
        conjunto.escrever(pasta)
        return contagens(modelo.ler(pasta, minimo=MINIMO))


class TestContagens(Base):
    def test_o_conjunto_coerente_da_zero(self) -> None:
        self.assertEqual(self.achados(Conjunto()), [])

    def test_contagem_do_31_errada(self) -> None:
        conjunto = Conjunto()
        conjunto.quantos_no_inventario[1] = 9
        achados = self.achados(conjunto)
        self.assertTrue(any('declara 9 ticket(s) e o §4 tem 3' in a
                            for a in achados))

    def test_soma_da_coluna_diferente_do_total(self) -> None:
        conjunto = Conjunto()
        conjunto.total_declarado = 7
        achados = self.achados(conjunto)
        self.assertTrue(any('a soma da coluna' in a for a in achados))

    def test_intervalo_do_31_que_nao_cobre_um_ticket_existente(self) -> None:
        conjunto = Conjunto()
        conjunto.intervalo_no_inventario[1] = f'{kam(1)} – {kam(2)}'
        achados = self.achados(conjunto)
        self.assertTrue(any('nao cobre' in a and kam(3) in a for a in achados))

    def test_intervalo_do_31_que_cobre_a_mais(self) -> None:
        conjunto = Conjunto()
        conjunto.intervalo_no_inventario[1] = f'{kam(1)} – {kam(9)}'
        achados = self.achados(conjunto)
        self.assertTrue(any('cobre' in a and kam(9) in a for a in achados))

    def test_intervalo_com_pecas_soltas_expande_se(self) -> None:
        """`KAM-001 – KAM-002, KAM-003` e a forma que o §3.1 real usa."""
        conjunto = Conjunto()
        conjunto.intervalo_no_inventario[1] = f'{kam(1)} – {kam(2)}, {kam(3)}'
        self.assertEqual(self.achados(conjunto), [])

    def test_intervalo_do_total_errado(self) -> None:
        conjunto = Conjunto()
        conjunto.intervalo_total = f'{kam(1)} – {kam(4)}'
        achados = self.achados(conjunto)
        self.assertTrue(any('intervalo do TOTAL' in a for a in achados))

    def test_numero_do_1_errado(self) -> None:
        conjunto = Conjunto()
        conjunto.quantos_no_proposito = 4
        achados = self.achados(conjunto)
        self.assertTrue(any('§1: declara 4 ticket(s)' in a for a in achados))

    def test_numero_de_epics_do_1_errado(self) -> None:
        conjunto = Conjunto()
        conjunto.epics_no_proposito = 5
        achados = self.achados(conjunto)
        self.assertTrue(any('declara 5 epics' in a for a in achados))

    def test_a_contagem_acompanha_um_ticket_novo_sem_ninguem_lhe_tocar(self) -> None:
        """A prova de que as contagens sao derivadas e nao copiadas.

        Acrescentar um ticket a *fixture* nao obriga a mexer em numero nenhum:
        se obrigasse, o gate estaria a comparar duas copias.
        """
        from lint_backlog.tests.conjunto import Ticket
        conjunto = Conjunto()
        conjunto.tickets.append(Ticket(6, 2, 'Outro ticket do canal',
                                       prioridade='P1', fase='1'))
        self.assertEqual(self.achados(conjunto), [])


class TestMutacaoDeliberada(Base):
    """A mutacao que o ticket pede: mexer so num lado torna o gate vermelho."""

    def test_estimativa_alterada_so_no_4_e_depois_revertida(self) -> None:
        from lint_backlog.cli import verificar
        pasta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, pasta, True)
        Conjunto().escrever(pasta)
        self.assertEqual(verificar(pasta, minimo=MINIMO).achados, [])

        indice = pasta / 'specs' / 'INDICE.md'
        bom = indice.read_text(encoding='utf-8')
        mau = bom.replace(f'| {kam(3)} | Schema `platform` e migrações '
                          'reversíveis | feature | L |',
                          f'| {kam(3)} | Schema `platform` e migrações '
                          'reversíveis | feature | S |')
        self.assertNotEqual(bom, mau, 'a mutacao nao casou nada')
        indice.write_text(mau, encoding='utf-8')
        achados = verificar(pasta, minimo=MINIMO).achados
        self.assertTrue(any('`estimativa` diverge' in a for a in achados))

        indice.write_text(bom, encoding='utf-8')
        self.assertEqual(verificar(pasta, minimo=MINIMO).achados, [])


if __name__ == '__main__':
    unittest.main()
