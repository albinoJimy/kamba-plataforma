"""A API interna recusa sem credencial, e o que cada estado diz ao *shim*.

Criterio 1 do KAM-025, e a tabela de estados do `api_interna.py`.
"""

from __future__ import annotations

import json
import unittest

from apoio import CREDENCIAL, como_json, invocacao_crua, pedir
from kamba_agr.admissao import Admissao, Tectos
from kamba_agr.api_interna import (
    CABECALHO,
    CORPO_MAXIMO,
    ESPERAR_SEGUNDOS,
    SEGREDO_DA_API,
    RetomaNaoImplementadaError,
    rotas,
)
from kamba_agr.app import create_app
from kamba_agr.metricas import METRICA_RECUSADOS, METRICAS
from kamba_agr.turno import DesfechoDoTurno, GrafoNaoRegistadoError


def aplicacao(
    desfecho=DesfechoDoTurno(desfecho="executado", turn_id="wamid.X"),
    erro=None,
    tectos=None,
    retomar=None,
    avisos=None,
):
    admissao = Admissao(tectos=tectos or Tectos())

    async def executar(_invocacao):
        if erro is not None:
            raise erro
        return desfecho

    return create_app(
        rotas_internas=rotas(
            credencial=lambda: CREDENCIAL,
            executar=executar,
            admissao=admissao,
            retomar=retomar,
            aviso=(avisos.append if avisos is not None else None),
        )
    ), admissao


COM_CREDENCIAL = {CABECALHO: CREDENCIAL}


class TestAutenticacao(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()
        self.app, _ = aplicacao()

    async def test_sem_cabecalho_e_401_nas_duas_rotas(self) -> None:
        for caminho in ("/internal/turn", "/internal/resume"):
            with self.subTest(caminho=caminho):
                estado, _, _ = await pedir(self.app, caminho, "POST", b"{}")
                self.assertEqual(estado, 401)

    async def test_com_a_credencial_errada_e_401_tambem(self) -> None:
        for valor in ("", " ", CREDENCIAL + "x", CREDENCIAL[:-1], CREDENCIAL.upper()):
            with self.subTest(valor=valor[:8]):
                estado, _, _ = await pedir(
                    self.app, "/internal/turn", "POST", b"{}", {CABECALHO: valor}
                )
                self.assertEqual(estado, 401)

    async def test_o_401_nao_diz_se_faltava_o_cabecalho_ou_se_o_valor_estava_errado(
        self,
    ) -> None:
        # As duas respostas juntas sao um oraculo sobre o formato da credencial.
        _, _, sem = await pedir(self.app, "/internal/turn", "POST", b"{}")
        _, _, errada = await pedir(
            self.app, "/internal/turn", "POST", b"{}", {CABECALHO: "outra"}
        )
        self.assertEqual(sem, errada)

    async def test_a_autenticacao_corre_antes_de_se_ler_o_corpo(self) -> None:
        # Um corpo de quem nao tem credencial nao chega a ser descodificado:
        # senao a rota autenticada e tambem uma superficie de DoS nao
        # autenticada. Prova-se com um corpo que **nao e JSON** e grande:
        # devolve 401, nao 400.
        estado, _, _ = await pedir(
            self.app, "/internal/turn", "POST", b"x" * (CORPO_MAXIMO * 2)
        )
        self.assertEqual(estado, 401)

    async def test_a_healthz_continua_sem_credencial(self) -> None:
        # Uma sonda que precisa de segredo e uma sonda que falha no dia em que
        # o segredo roda (`docs/tecnica/09` §7).
        estado, _, _ = await pedir(self.app, "/healthz")
        self.assertEqual(estado, 200)

    async def test_as_rotas_internas_so_aceitam_post(self) -> None:
        for caminho in ("/internal/turn", "/internal/resume"):
            for metodo in ("GET", "PUT", "DELETE"):
                with self.subTest(caminho=caminho, metodo=metodo):
                    estado, _, _ = await pedir(self.app, caminho, metodo)
                    self.assertEqual(estado, 405)

    async def test_sem_rotas_internas_a_aplicacao_nao_as_tem(self) -> None:
        # Um esqueleto que expoe uma rota que nao funciona e pior do que um que
        # a nao expoe.
        estado, _, _ = await pedir(create_app(), "/internal/turn", "POST", b"{}")
        self.assertEqual(estado, 404)


class TestTurno(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    async def test_uma_invocacao_valida_corre_e_devolve_o_desfecho(self) -> None:
        app, _ = aplicacao(
            DesfechoDoTurno(desfecho="executado", turn_id="wamid.ABC", coalescidos=2)
        )
        estado, _, corpo = await pedir(
            app, "/internal/turn", "POST", como_json(invocacao_crua()), COM_CREDENCIAL
        )
        self.assertEqual(estado, 200)
        self.assertEqual(
            json.loads(corpo),
            {"outcome": "executado", "turn_id": "wamid.ABC", "coalescidos": 2},
        )

    async def test_um_corpo_que_nao_e_contrato_da_400_e_conta(self) -> None:
        app, _ = aplicacao()
        for corpo in (b"{}", b"nao e json", b"[]", como_json({"tenant_id": "x"})):
            with self.subTest(corpo=corpo[:12]):
                estado, _, resposta = await pedir(
                    app, "/internal/turn", "POST", corpo, COM_CREDENCIAL
                )
                self.assertEqual(estado, 400)
                self.assertEqual(json.loads(resposta)["outcome"], "invocacao_invalida")
        self.assertEqual(METRICAS.ler()[f"{METRICA_RECUSADOS}:invocacao_invalida"], 4)

    async def test_um_corpo_grande_da_400_e_nao_se_descodifica(self) -> None:
        app, _ = aplicacao()
        estado, _, resposta = await pedir(
            app,
            "/internal/turn",
            "POST",
            b"{" + b"a" * (CORPO_MAXIMO + 1),
            COM_CREDENCIAL,
        )
        self.assertEqual(estado, 400)
        self.assertEqual(json.loads(resposta)["error_code"], "corpo_grande")

    async def test_o_descarte_por_ritmo_da_200(self) -> None:
        # Um 429 fazia o BullMQ repetir a mensagem que acabamos de decidir
        # descartar, e um descarte que se repete nao e um descarte.
        avisos: list = []
        app, _ = aplicacao(tectos=Tectos(ritmo_por_contacto=1), avisos=avisos)
        corpo = invocacao_crua()
        primeiro, _, _ = await pedir(
            app, "/internal/turn", "POST", como_json(corpo), COM_CREDENCIAL
        )
        self.assertEqual(primeiro, 200)
        segundo, _, resposta = await pedir(
            app, "/internal/turn", "POST", como_json(corpo), COM_CREDENCIAL
        )
        self.assertEqual(segundo, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "descartado")
        self.assertEqual(avisos, ["ritmo_excedido"])

    async def test_o_aviso_do_descarte_e_um_so(self) -> None:
        avisos: list = []
        app, _ = aplicacao(tectos=Tectos(ritmo_por_contacto=0), avisos=avisos)
        # Com o ritmo a 0 (sem limite) nao ha descarte nenhum, logo nem aviso.
        await pedir(app, "/internal/turn", "POST", como_json(invocacao_crua()), COM_CREDENCIAL)
        self.assertEqual(avisos, [])

        avisos.clear()
        app, _ = aplicacao(tectos=Tectos(ritmo_por_contacto=1), avisos=avisos)
        corpo = invocacao_crua()
        for _ in range(5):
            await pedir(app, "/internal/turn", "POST", como_json(corpo), COM_CREDENCIAL)
        self.assertEqual(avisos, ["ritmo_excedido"])

    async def test_o_tecto_cheio_da_503_com_retry_after(self) -> None:
        app, admissao = aplicacao(tectos=Tectos(tecto_por_tenant=1))
        corpo = invocacao_crua()
        invocacao = __import__("kamba_agr.contexto", fromlist=["ler_invocacao"]).ler_invocacao(corpo)
        vaga = admissao.vaga(invocacao)
        await vaga.__aenter__()
        try:
            estado, cabecalhos, resposta = await pedir(
                app, "/internal/turn", "POST", como_json(corpo), COM_CREDENCIAL
            )
        finally:
            await vaga.__aexit__(None, None, None)
        self.assertEqual(estado, 503)
        self.assertEqual(cabecalhos["retry-after"], str(ESPERAR_SEGUNDOS))
        self.assertEqual(json.loads(resposta)["outcome"], "tecto_do_tenant")

    async def test_sem_grafo_registado_da_503_e_nao_500(self) -> None:
        # «O turno nao corre e a mensagem fica na fila» (`docs/tecnica/02` §14).
        # Um 500 punha o BullMQ a repetir para sempre uma mensagem que nenhuma
        # versao deste codigo consegue tratar.
        app, _ = aplicacao(erro=GrafoNaoRegistadoError("grafo_nao_registado"))
        estado, cabecalhos, resposta = await pedir(
            app, "/internal/turn", "POST", como_json(invocacao_crua()), COM_CREDENCIAL
        )
        self.assertEqual(estado, 503)
        self.assertEqual(cabecalhos["retry-after"], str(ESPERAR_SEGUNDOS))
        self.assertEqual(json.loads(resposta)["outcome"], "grafo_nao_registado")

    async def test_uma_falha_do_turno_propaga_se(self) -> None:
        # O *shim* ve 500 e devolve o *job* a fila. Nao se engole.
        app, _ = aplicacao(erro=RuntimeError("rebentou"))
        with self.assertRaises(RuntimeError):
            await pedir(
                app, "/internal/turn", "POST", como_json(invocacao_crua()), COM_CREDENCIAL
            )


class TestRetoma(unittest.IsolatedAsyncioTestCase):
    async def test_o_corpo_tem_de_ter_os_tres_campos_e_so_eles(self) -> None:
        app, _ = aplicacao()
        maus = [
            {},
            {"thread_id": "a"},
            {"thread_id": "a", "handoff_id": "b"},
            {"thread_id": "a", "handoff_id": "b", "outcome": "c", "extra": "d"},
            {"thread_id": "", "handoff_id": "b", "outcome": "c"},
            {"thread_id": "a", "handoff_id": 7, "outcome": "c"},
        ]
        for corpo in maus:
            with self.subTest(corpo=sorted(corpo)):
                estado, _, resposta = await pedir(
                    app, "/internal/resume", "POST", como_json(corpo), COM_CREDENCIAL
                )
                self.assertEqual(estado, 400)
                self.assertEqual(json.loads(resposta)["outcome"], "corpo_invalido")

    async def test_sem_a_porta_do_kam_034_levanta_em_vez_de_fingir_200(self) -> None:
        app, _ = aplicacao()
        with self.assertRaises(RetomaNaoImplementadaError):
            await pedir(
                app,
                "/internal/resume",
                "POST",
                como_json({"thread_id": "a:b", "handoff_id": "h", "outcome": "resumed"}),
                COM_CREDENCIAL,
            )

    async def test_com_a_porta_ligada_chama_a_e_devolve_200(self) -> None:
        chamadas: list = []

        async def retomar(thread_id, handoff_id, outcome):
            chamadas.append((thread_id, handoff_id, outcome))

        app, _ = aplicacao(retomar=retomar)
        estado, _, resposta = await pedir(
            app,
            "/internal/resume",
            "POST",
            como_json({"thread_id": "a:b", "handoff_id": "h", "outcome": "resumed"}),
            COM_CREDENCIAL,
        )
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "retomado")
        self.assertEqual(chamadas, [("a:b", "h", "resumed")])


class TestNomes(unittest.TestCase):
    def test_o_id_do_segredo_esta_no_inventario(self) -> None:
        from pathlib import Path

        inventario = (
            Path(__file__).resolve().parents[3] / "ops" / "secrets-inventory.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn(f"- id: {SEGREDO_DA_API}", inventario)

    def test_o_cabecalho_e_minusculas(self) -> None:
        # Os cabecalhos ASGI chegam em minusculas; um `X-Kamba-Interno` escrito
        # aqui nunca casava.
        self.assertEqual(CABECALHO, CABECALHO.lower())


if __name__ == "__main__":
    unittest.main()
