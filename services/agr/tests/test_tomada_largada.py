"""A tomada largada durante o `screen` (KAM-230, achado 9 do KAM-228 e achados 1 e 5 da revisao do KAM-230).

O `Pedido.sem_tomada` devolve a ligacao a fila da ToolLayer enquanto um trabalho
espera pela rede, e retoma uma vaga depois. Tres propriedades, e nenhuma se via
pelos ensaios do `submit_quote`, que usam uma tomada so:

1. **A ToolLayer nao para.** A vaga e tomada no laco antes de haver *worker*; com
   todos os *workers* do executor presos a espera da retoma, as tomadas ficavam
   presas em tarefas que nunca corriam. `LARGAS_MAXIMAS` fica abaixo dos
   *workers*, e a invocacao a mais corre com a tomada. Canario: o mesmo ensaio
   com o limite igual aos *workers* pendura.
2. **A ligacao que volta e a retomada**, e nao a largada, que ja pode estar
   noutra invocacao: duas invocacoes nunca seguram o mesmo objecto, e no fim a
   fila tem as vagas todas e nenhuma repetida.
3. **Um trabalho que levanta** tambem retoma, e a contagem de vagas nao muda.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
import unittest
from typing import Any
from unittest import mock

from kamba_agr.tls import camada as camada_mod
from kamba_agr.tls.camada import ToolLayer
from kamba_agr.tls.erros import ToolResult
from kamba_agr.tls.especificacoes import Catalogo


class _Ligacao:
    """Uma ligacao com identidade, que conta quem a usa ao mesmo tempo."""

    def __init__(self) -> None:
        self.em_uso = 0
        self.maximo_em_uso = 0
        self._trinco = threading.Lock()

    def usar(self) -> None:
        with self._trinco:
            self.em_uso += 1
            self.maximo_em_uso = max(self.maximo_em_uso, self.em_uso)
        time.sleep(0.02)
        with self._trinco:
            self.em_uso -= 1

    def close(self) -> None:
        return None


def _camada(passo: Any, ligacoes: int, abertas: list[_Ligacao]) -> ToolLayer:
    def abrir() -> _Ligacao:
        nova = _Ligacao()
        abertas.append(nova)
        return nova

    return ToolLayer(Catalogo(()), abrir_ligacao=abrir, ligacoes=ligacoes, passos=[passo])


def _invocar(camada: ToolLayer) -> Any:
    return camada.invoke(None, "x", {}, allowed=())  # type: ignore[arg-type]


class TestNaoPara(unittest.TestCase):
    """Quatro tomadas, cinco *workers*, dez invocacoes que largam a tomada."""

    def _rajada(self) -> tuple[list[Any], int]:
        def passo(inv):  # noqa: ANN001, ANN202
            inv.camada._largar_tomada(inv, lambda: time.sleep(0.3))
            return ToolResult(ok=True, data={})

        async def correr() -> tuple[list[Any], int]:
            laco = asyncio.get_running_loop()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
            laco.set_default_executor(executor)
            camada = _camada(passo, 4, [])
            resultados = await asyncio.wait_for(
                asyncio.gather(*[_invocar(camada) for _ in range(10)]), 20
            )
            seguinte = await asyncio.wait_for(_invocar(camada), 10)
            return [*resultados, seguinte], camada._tomadas.qsize()

        return asyncio.run(correr())

    def test_dez_invocacoes_que_largam_acabam_e_a_fila_volta_inteira(self) -> None:
        resultados, vagas = self._rajada()
        self.assertTrue(all(r.ok for r in resultados), [r.error for r in resultados])
        self.assertEqual(vagas, 4)

    def test_canario_com_o_limite_igual_aos_workers_a_camada_para(self) -> None:
        """Sem o limite (cinco largas para cinco *workers*), a rajada pendura."""
        with mock.patch.object(camada_mod, "LARGAS_MAXIMAS", 5):
            with self.assertRaises(TimeoutError):
                # O laco fica com *threads* presas: o `asyncio.run` nao acaba
                # enquanto elas vivem, pelo que se corre numa *thread* propria.
                fio_resultado: list[BaseException] = []

                def em_fio() -> None:
                    try:
                        self._rajada()
                    except BaseException as erro:  # noqa: BLE001
                        fio_resultado.append(erro)

                fio = threading.Thread(target=em_fio, daemon=True)
                fio.start()
                fio.join(timeout=25)
                if fio.is_alive() or (fio_resultado and isinstance(fio_resultado[0], TimeoutError)):
                    raise TimeoutError("a camada parou")
                if fio_resultado:
                    raise fio_resultado[0]


class TestALigacaoQueVolta(unittest.TestCase):
    def test_duas_invocacoes_nunca_seguram_a_mesma_ligacao(self) -> None:
        """Duas tomadas, seis invocacoes: cada uma usa a ligacao antes e depois do `screen`."""
        abertas: list[_Ligacao] = []
        trocas: list[bool] = []

        def passo(inv):  # noqa: ANN001, ANN202
            antes = inv.ligacao
            antes.usar()
            _resultado, depois = inv.camada._largar_tomada(inv, lambda: time.sleep(0.1))
            self.assertIs(depois, inv.ligacao)
            trocas.append(depois is not antes)
            depois.usar()
            return ToolResult(ok=True, data={})

        async def correr() -> int:
            camada = _camada(passo, 2, abertas)
            resultados = await asyncio.gather(*[_invocar(camada) for _ in range(6)])
            self.assertTrue(all(r.ok for r in resultados))
            vagas = []
            while not camada._tomadas.empty():
                vagas.append(camada._tomadas.get_nowait())
            self.assertEqual(len(vagas), 2)
            self.assertEqual(len({id(v) for v in vagas if v is not None}), len([v for v in vagas if v is not None]))
            return len(vagas)

        asyncio.run(correr())
        # Nenhuma ligacao foi usada por duas invocacoes ao mesmo tempo. (Se
        # houve troca depende da ordem das *threads*; a troca garantida mede-se
        # no ensaio seguinte.)
        self.assertTrue(abertas)
        self.assertEqual(max(lig.maximo_em_uso for lig in abertas), 1)
        del trocas

    def test_a_retoma_traz_a_outra_vaga_e_e_essa_que_volta_a_fila(self) -> None:
        """Deterministico: duas vagas, uma invocacao.

        A fila e FIFO: a ligacao largada vai para o fim, e a retoma apanha a
        outra vaga (vazia, logo uma ligacao nova). Os dois mutantes do achado 5
        — devolver a largada no `_largar_tomada`, ou a original no `_correr` —
        poem aqui a mesma ligacao duas vezes.
        """
        abertas: list[_Ligacao] = []
        vistas: list[tuple[Any, Any, Any]] = []

        def passo(inv):  # noqa: ANN001, ANN202
            antes = inv.ligacao
            _resultado, depois = inv.camada._largar_tomada(inv, lambda: None)
            vistas.append((antes, depois, inv.ligacao))
            return ToolResult(ok=True, data={})

        async def correr() -> list[Any]:
            camada = _camada(passo, 2, abertas)
            resultado = await _invocar(camada)
            self.assertTrue(resultado.ok)
            vagas = []
            while not camada._tomadas.empty():
                vagas.append(camada._tomadas.get_nowait())
            return vagas

        vagas = asyncio.run(correr())
        ((antes, depois, agora),) = vistas
        self.assertIsNot(depois, antes)
        self.assertIs(depois, agora)
        self.assertEqual(len(abertas), 2)
        self.assertEqual({id(v) for v in vagas}, {id(antes), id(depois)})

    def test_um_trabalho_que_levanta_retoma_e_nao_perde_vagas(self) -> None:
        def passo(inv):  # noqa: ANN001, ANN202
            try:
                inv.camada._largar_tomada(inv, lambda: (_ for _ in ()).throw(RuntimeError("rede")))
            except RuntimeError:
                pass
            self.assertIsNotNone(inv.ligacao)
            return ToolResult(ok=True, data={})

        async def correr() -> int:
            camada = _camada(passo, 3, [])
            await asyncio.gather(*[_invocar(camada) for _ in range(5)])
            return camada._tomadas.qsize()

        self.assertEqual(asyncio.run(correr()), 3)


if __name__ == "__main__":
    unittest.main()
