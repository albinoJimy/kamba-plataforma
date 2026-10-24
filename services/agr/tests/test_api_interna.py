"""A API interna recusa sem credencial, e o que cada estado diz ao *shim*.

Criterio 1 do KAM-025, e a tabela de estados do `api_interna.py`.
"""

from __future__ import annotations

import json
import unittest

from apoio import CREDENCIAL, TrancaFalsa, como_json, invocacao_crua, pedir
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
    trancas=None,
):
    admissao = Admissao(tectos=tectos or Tectos())
    trancas = trancas if trancas is not None else TrancaFalsa()

    async def executar(_invocacao):
        if erro is not None:
            raise erro
        return desfecho

    return create_app(
        rotas_internas=rotas(
            credencial=lambda: CREDENCIAL,
            executar=executar,
            admissao=admissao,
            trancas=trancas,
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
        #
        # **Duas mensagens diferentes do mesmo contacto**, e nao a mesma duas
        # vezes: o ritmo conta mensagens e nao entregas, e a mesma invocacao
        # repetida mede a idempotencia (o teste seguinte).
        avisos: list = []
        app, _ = aplicacao(tectos=Tectos(ritmo_por_contacto=1), avisos=avisos)
        primeira = invocacao_crua()
        segunda = invocacao_crua(
            tenant_id=primeira["tenant_id"], contact_id=primeira["contact_id"]
        )
        self.assertNotEqual(primeira["wamid"], segunda["wamid"])
        primeiro, _, _ = await pedir(
            app, "/internal/turn", "POST", como_json(primeira), COM_CREDENCIAL
        )
        self.assertEqual(primeiro, 200)
        segundo, _, resposta = await pedir(
            app, "/internal/turn", "POST", como_json(segunda), COM_CREDENCIAL
        )
        self.assertEqual(segundo, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "descartado")
        self.assertEqual(avisos, ["ritmo_excedido"])

    async def test_a_re_entrega_do_mesmo_job_nao_gasta_quota(self) -> None:
        """Vinte entregas do mesmo `wamid` gastam **uma** quota.

        Com a ordem anterior — ritmo antes da vaga, e sem memoria do `turn_id` —
        vinte 503 do mesmo *job* consumiam os vinte lugares do minuto e a
        mensagem seguinte, legitima, era descartada em silencio. E o efeito
        duplicado que o DoD da idempotencia diz nao existir. Achado da revisao
        adversarial.
        """
        app, _ = aplicacao(tectos=Tectos(ritmo_por_contacto=2))
        corpo = invocacao_crua()
        for _ in range(20):
            estado, _, resposta = await pedir(
                app, "/internal/turn", "POST", como_json(corpo), COM_CREDENCIAL
            )
            self.assertEqual(estado, 200)
            self.assertEqual(json.loads(resposta)["outcome"], "executado")
        # Sobra **uma** quota das duas, para uma mensagem nova.
        outra = invocacao_crua(
            tenant_id=corpo["tenant_id"], contact_id=corpo["contact_id"]
        )
        _, _, resposta = await pedir(
            app, "/internal/turn", "POST", como_json(outra), COM_CREDENCIAL
        )
        self.assertEqual(json.loads(resposta)["outcome"], "executado")
        terceira = invocacao_crua(
            tenant_id=corpo["tenant_id"], contact_id=corpo["contact_id"]
        )
        _, _, resposta = await pedir(
            app, "/internal/turn", "POST", como_json(terceira), COM_CREDENCIAL
        )
        self.assertEqual(json.loads(resposta)["outcome"], "descartado")

    async def test_uma_recusa_por_tecto_nao_gasta_quota_de_ritmo(self) -> None:
        # A segunda via da correccao: o ritmo verifica-se **dentro** da vaga.
        from kamba_agr.contexto import ler_invocacao

        app, admissao = aplicacao(
            tectos=Tectos(tecto_por_tenant=1, ritmo_por_contacto=1)
        )
        corpo = invocacao_crua()
        vaga = admissao.vaga(ler_invocacao(corpo))
        await vaga.__aenter__()
        try:
            for _ in range(5):
                estado, _, _ = await pedir(
                    app, "/internal/turn", "POST", como_json(corpo), COM_CREDENCIAL
                )
                self.assertEqual(estado, 503)
        finally:
            await vaga.__aexit__(None, None, None)
        # As cinco recusas nao gastaram nada: a quota de 1 esta intacta.
        estado, _, resposta = await pedir(
            app, "/internal/turn", "POST", como_json(corpo), COM_CREDENCIAL
        )
        self.assertEqual(estado, 200)
        self.assertEqual(json.loads(resposta)["outcome"], "executado")

    async def test_o_aviso_do_descarte_e_um_so(self) -> None:
        avisos: list = []
        app, _ = aplicacao(tectos=Tectos(ritmo_por_contacto=0), avisos=avisos)
        # Com o ritmo a 0 (sem limite) nao ha descarte nenhum, logo nem aviso.
        await pedir(app, "/internal/turn", "POST", como_json(invocacao_crua()), COM_CREDENCIAL)
        self.assertEqual(avisos, [])

        avisos.clear()
        app, _ = aplicacao(tectos=Tectos(ritmo_por_contacto=1), avisos=avisos)
        primeira = invocacao_crua()
        await pedir(app, "/internal/turn", "POST", como_json(primeira), COM_CREDENCIAL)
        # Cinco mensagens **novas** do mesmo contacto, todas descartadas, e um
        # so aviso.
        for _ in range(5):
            corpo = invocacao_crua(
                tenant_id=primeira["tenant_id"], contact_id=primeira["contact_id"]
            )
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

    async def test_a_retoma_corre_sob_a_tranca_da_conversa(self) -> None:
        """`docs/tecnica/02` §11 regra 3, por escrito: «a invocacao
        `Command(resume=...)` corre sob o *lock* da conversa».

        Tres sitios afirmavam que o KAM-025 entregava isto — a *docstring* do
        `RetomaNaoImplementadaError`, o dicionario §3.24 e a secção de
        verificação — e o codigo chamava a porta directamente. Sem a tranca, um
        `resume` entra no grafo ao mesmo tempo que um turno novo, sobre o mesmo
        *thread*. Achado da revisao adversarial.
        """
        dentro: list = []
        tranca = TrancaFalsa()

        async def retomar(thread_id, _handoff_id, _outcome):
            # Dentro do `retomar`, a tranca daquele `thread_id` tem de estar
            # tomada.
            dentro.append((thread_id, tranca.dentro))

        app, _ = aplicacao(retomar=retomar, trancas=tranca)
        estado, _, _ = await pedir(
            app,
            "/internal/resume",
            "POST",
            como_json({"thread_id": "a:b", "handoff_id": "h", "outcome": "resumed"}),
            COM_CREDENCIAL,
        )
        self.assertEqual(estado, 200)
        self.assertEqual(tranca.tomadas, ["a:b"])
        self.assertEqual(dentro, [("a:b", 1)])
        # E larga-se no fim.
        self.assertEqual(tranca.dentro, 0)

    async def test_a_retoma_nao_toma_a_tranca_sem_credencial(self) -> None:
        # Senao, um pedido nao autenticado podia prender a conversa de alguem.
        tranca = TrancaFalsa()
        app, _ = aplicacao(retomar=lambda *_a: None, trancas=tranca)
        estado, _, _ = await pedir(
            app,
            "/internal/resume",
            "POST",
            como_json({"thread_id": "a:b", "handoff_id": "h", "outcome": "resumed"}),
        )
        self.assertEqual(estado, 401)
        self.assertEqual(tranca.tomadas, [])


class TestEncerramento(unittest.IsolatedAsyncioTestCase):
    """O `ao_encerrar` corre no fim do `lifespan`.

    O `TrancaDeConversas.fechar()` existia e **nao tinha chamador nenhum em
    producao** (achado da revisao adversarial): as trancas de um processo que
    para ficavam ate o PostgreSQL notar a tomada fechada, e o *worker* que
    recebe os *jobs* a seguir esperava por elas sem razao. Agora liga-se pelo
    `lifespan`, que o uvicorn fecha em `SIGTERM`.
    """

    async def _ciclo(self, app) -> None:
        """Conduz o `lifespan` da aplicacao ASGI: arranca e encerra."""
        recebidas: list[dict] = []
        a_enviar = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]

        async def receive() -> dict:
            return a_enviar.pop(0) if a_enviar else {"type": "lifespan.shutdown"}

        async def send(mensagem: dict) -> None:
            recebidas.append(mensagem)

        await app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)
        self.assertIn(
            "lifespan.startup.complete", [m["type"] for m in recebidas], recebidas
        )

    async def test_o_encerramento_fecha_as_ligacoes(self) -> None:
        fechou = {"vezes": 0}

        async def ao_encerrar() -> None:
            fechou["vezes"] += 1

        await self._ciclo(create_app(ao_encerrar=ao_encerrar))
        self.assertEqual(fechou["vezes"], 1)

    async def test_sem_ao_encerrar_a_aplicacao_arranca_igual(self) -> None:
        # A aplicacao do KAM-001 continua a construir-se sem argumentos.
        await self._ciclo(create_app())

    async def test_o_encerramento_corre_mesmo_quando_o_ciclo_rebenta(self) -> None:
        """E um `finally`, e isso tem um limite que vale a pena escrever.

        **Cobre** um erro depois do arranque: o Starlette ja entrou no gestor de
        contexto, e o `finally` corre. **Nao cobre** um erro no proprio arranque
        — ali o `receive()` levanta antes de se entrar no gestor, e nao ha nada
        a fechar porque nada abriu. A primeira versao deste teste afirmava o
        contrario e falhou, que e onde se quer que isso aconteca.
        """
        fechou = {"vezes": 0}

        async def ao_encerrar() -> None:
            fechou["vezes"] += 1

        app = create_app(ao_encerrar=ao_encerrar)
        passos = [{"type": "lifespan.startup"}]

        async def receive() -> dict:
            if passos:
                return passos.pop(0)
            raise RuntimeError("o servidor ASGI rebentou a meio")

        async def send(_m: dict) -> None:
            return None

        with self.assertRaises(RuntimeError):
            await app({"type": "lifespan", "asgi": {"version": "3.0"}}, receive, send)
        self.assertEqual(fechou["vezes"], 1)

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
