"""A maquina de estados do §6.1, e a paridade com o TypeScript (KAM-006).

O que aqui se verifica:

    TestGrafo             o grafo e fechado: doze estados, nenhuma aresta para
                          fora da lista, dois estados terminais, e o
                          `expirada -> paga` que o negocio aceita.
    TestPodeTransitar     um estado desconhecido **levanta**; nao devolve
                          `False`. A diferenca decide entre adiar e DLQ.
    TestEstadoPretendido  so os dois tipos que **causam** a transicao; os que o
                          COM emite **depois** dela ficam fora, e esse e o
                          criterio.
    TestMaquinaNaBase     o `agregado_id` vai como parametro, o nome da tabela e
                          validado, e um estado que a tabela tenha e a maquina
                          nao conheca nao passa por «pode».
    TestParidadeDoTypeScript
                          as transicoes, os estados e os estados pretendidos sao
                          os mesmos numeros nos dois lados. E o padrao do
                          KAM-005 (`TestParidadeDoGuardaDePii`): duas
                          implementacoes do mesmo contrato so se mantem honestas
                          se houver uma maquina a confronta-las.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from kamba_core.eventos.estados import (
    ESTADO_PRETENDIDO,
    ESTADOS_DA_ENCOMENDA,
    TRANSICOES,
    EstadoDesconhecidoError,
    MaquinaNaBase,
    e_estado,
    pode_transitar,
)

RAIZ = Path(__file__).resolve().parents[3]
ESTADOS_TS = RAIZ / "packages" / "core-ts" / "src" / "eventos" / "estados.ts"


class _Leitura:
    def __init__(self, linhas: tuple[dict[str, object], ...]) -> None:
        self.linhas = linhas


class _Bd:
    """Um cliente que so le, e que guarda o que lhe pediram."""

    def __init__(self, linhas: tuple[dict[str, object], ...] = ()) -> None:
        self._linhas = linhas
        self.registo: list[tuple[str, tuple[object, ...]]] = []

    def executar(self, sql: str, parametros: tuple[object, ...] = ()) -> _Leitura:
        self.registo.append((sql, tuple(parametros)))
        return _Leitura(self._linhas)


class TestGrafo(unittest.TestCase):
    def test_sao_os_doze_estados_do_paragrafo_6_1(self) -> None:
        self.assertEqual(len(ESTADOS_DA_ENCOMENDA), 12)
        self.assertEqual(len(set(ESTADOS_DA_ENCOMENDA)), 12)

    def test_cada_estado_tem_entrada_e_nenhuma_aresta_sai_da_lista(self) -> None:
        self.assertEqual(set(TRANSICOES), set(ESTADOS_DA_ENCOMENDA))
        for origem, destinos in TRANSICOES.items():
            with self.subTest(origem=origem):
                for destino in destinos:
                    self.assertIn(destino, ESTADOS_DA_ENCOMENDA)
                self.assertNotIn(origem, destinos, "nao ha lacos sobre si mesmo")
                self.assertEqual(len(set(destinos)), len(destinos))

    def test_cancelada_e_reembolsada_sao_terminais(self) -> None:
        self.assertEqual(TRANSICOES["cancelada"], ())
        self.assertEqual(TRANSICOES["reembolsada"], ())

    def test_o_pagamento_tardio_do_multicaixa_e_valido(self) -> None:
        """`expirada -> paga` esta no §6.1 de proposito: o negocio aceita-o."""
        self.assertTrue(pode_transitar("expirada", "paga"))

    def test_a_transicao_que_o_consumidor_protege(self) -> None:
        self.assertTrue(pode_transitar("aguarda_pagamento", "paga"))
        self.assertFalse(pode_transitar("criada", "paga"))


class TestPodeTransitar(unittest.TestCase):
    def test_e_estado_so_aceita_os_doze_e_so_texto(self) -> None:
        self.assertTrue(e_estado("paga"))
        for valor in ("PAGA", "pago", "", None, 7, ["paga"]):
            with self.subTest(valor=repr(valor)):
                self.assertFalse(e_estado(valor))

    def test_origem_desconhecida_levanta(self) -> None:
        """Um `False` silencioso aqui era indistinguivel de «nao existe»."""
        with self.assertRaises(EstadoDesconhecidoError) as capturado:
            pode_transitar("em_processamento", "paga")
        self.assertEqual(capturado.exception.estado, "em_processamento")

    def test_destino_desconhecido_levanta(self) -> None:
        with self.assertRaises(EstadoDesconhecidoError) as capturado:
            pode_transitar("paga", "liquidada")
        self.assertEqual(capturado.exception.estado, "liquidada")


class TestEstadoPretendido(unittest.TestCase):
    def test_sao_os_dois_tipos_que_causam_a_transicao(self) -> None:
        self.assertEqual(
            set(ESTADO_PRETENDIDO),
            {"payment.confirmed", "payment.manual_confirmed"},
        )

    def test_os_eventos_que_o_com_emite_depois_nao_estao_aqui(self) -> None:
        """Quem os consome esta a ser informado, nao a decidir.

        A primeira versao tinha-os, e misturar os dois criterios era o defeito:
        pedir pre-condicao de estado a uma **noticia** da transicao era exigir
        que a replica ja tivesse o estado novo para a aceitar, e isso adiava
        toda a primeira entrega.
        """
        for tipo in ("order.expired", "order.delivered", "order.paid"):
            with self.subTest(tipo=tipo):
                self.assertNotIn(tipo, ESTADO_PRETENDIDO)

    def test_cada_pretendido_e_um_estado_da_maquina(self) -> None:
        for tipo, estado in ESTADO_PRETENDIDO.items():
            with self.subTest(tipo=tipo):
                self.assertTrue(e_estado(estado))


class TestMaquinaNaBase(unittest.TestCase):
    def test_le_o_estado_com_o_agregado_como_parametro(self) -> None:
        bd = _Bd(({"estado": "aguarda_pagamento"},))
        maquina = MaquinaNaBase(bd)
        self.assertEqual(maquina.estado_de("order", "ORD-1"), "aguarda_pagamento")
        sql, parametros = bd.registo[0]
        self.assertEqual(parametros, ("ORD-1",))
        self.assertNotIn("ORD-1", sql)
        self.assertIn("FROM platform.orders", sql)

    def test_sem_linha_devolve_none_e_nao_e_pode(self) -> None:
        self.assertIsNone(MaquinaNaBase(_Bd()).estado_de("order", "ORD-1"))

    def test_outro_agregado_nao_toca_na_base(self) -> None:
        bd = _Bd(({"estado": "paga"},))
        self.assertIsNone(MaquinaNaBase(bd).estado_de("payment", "PAY-1"))
        self.assertEqual(bd.registo, [])

    def test_um_estado_que_a_maquina_nao_conhece_levanta(self) -> None:
        bd = _Bd(({"estado": "em_processamento"},))
        with self.assertRaises(EstadoDesconhecidoError):
            MaquinaNaBase(bd).estado_de("order", "ORD-1")

    def test_um_nome_de_tabela_ou_coluna_vindo_de_fora_e_recusado(self) -> None:
        for nome in (
            "orders; DROP TABLE orders",
            "Orders",
            "o",
            "",
            "9orders",
            "orders--",
            "a" * 64,
            None,
        ):
            with self.subTest(nome=repr(nome)):
                with self.assertRaises(ValueError):
                    MaquinaNaBase(_Bd(), nome)
                with self.assertRaises(ValueError):
                    MaquinaNaBase(_Bd(), "orders", nome)
                with self.assertRaises(ValueError):
                    MaquinaNaBase(_Bd(), "orders", "id", nome)

    def test_a_tabela_e_as_colunas_podem_ser_outras(self) -> None:
        bd = _Bd(({"estado": "paga"},))
        maquina = MaquinaNaBase(bd, "orders_mirror", "order_id", "estado_actual")
        self.assertEqual(maquina.estado_de("order", "ORD-9"), "paga")
        sql, _ = bd.registo[0]
        self.assertIn("estado_actual AS estado", sql)
        self.assertIn("platform.orders_mirror", sql)
        self.assertIn("order_id = %s", sql)


class TestParidadeDoTypeScript(unittest.TestCase):
    """O mesmo grafo dos dois lados, lido do TypeScript como texto.

    O padrao e o do KAM-005 (`TestParidadeDoGuardaDePii` em
    `db/tests/test_eventos_schema.py`): nao se confia na memoria de quem copiou.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.texto = ESTADOS_TS.read_text(encoding="utf-8")

    def _bloco(self, nome: str) -> str:
        achado = re.search(
            rf"export const {nome}\b[^=]*= [\[{{](.*?)\n(?:\]|}})", self.texto, re.S
        )
        self.assertIsNotNone(achado, f"nao se encontrou {nome} em {ESTADOS_TS.name}")
        return achado.group(1)

    def test_o_ficheiro_do_typescript_existe(self) -> None:
        self.assertTrue(ESTADOS_TS.is_file(), ESTADOS_TS)

    def test_os_estados_sao_os_mesmos_e_pela_mesma_ordem(self) -> None:
        do_ts = tuple(re.findall(r"'([a-z_]+)'", self._bloco("ESTADOS_DA_ENCOMENDA")))
        self.assertEqual(do_ts, ESTADOS_DA_ENCOMENDA)

    def test_as_transicoes_sao_as_mesmas_aresta_a_aresta(self) -> None:
        bloco = self._bloco("TRANSICOES")
        do_ts = {
            origem: tuple(re.findall(r"'([a-z_]+)'", destinos))
            for origem, destinos in re.findall(r"(\w+): \[([^\]]*)\]", bloco)
        }
        self.assertEqual(len(do_ts), 12, do_ts)
        self.assertEqual(do_ts, dict(TRANSICOES))

    def test_os_estados_pretendidos_sao_os_mesmos(self) -> None:
        bloco = self._bloco("ESTADO_PRETENDIDO")
        do_ts = dict(re.findall(r"'([\w.]+)': '([a-z_]+)'", bloco))
        self.assertEqual(len(do_ts), 2, do_ts)
        self.assertEqual(do_ts, dict(ESTADO_PRETENDIDO))


if __name__ == "__main__":
    unittest.main()
