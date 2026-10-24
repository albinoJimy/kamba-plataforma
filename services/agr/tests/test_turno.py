"""Um turno por conversa, por ordem, e quem tem a palavra (criterios 2, 3 e 6).

O que **esta** bateria prova e que o executor pede a tranca, corre um lote de
cada vez e preserva a ordem dentro do processo. O que ela **nao** pode provar e
que o `pg_advisory_lock` e exclusao mutua entre **processos**: isso e a *suite*
`db/tests_agr/` do *gate* 8, com duas ligacoes e um `SIGKILL` a serio. A
distincao esta escrita porque uma tranca falsa que serializa e exactamente o
duplo que faz um defeito de SQL passar por verde.
"""

from __future__ import annotations

import asyncio
import unittest
import uuid

from apoio import TrancaFalsa, invocacao_crua
from kamba_agr.admissao import Admissao, Tectos
from kamba_agr.contexto import ler_invocacao
from kamba_agr.metricas import (
    METRICA_COALESCIDAS,
    METRICA_CONTRAPRESSAO,
    METRICA_DURACAO,
    METRICA_FILA,
    METRICA_TURNOS,
    METRICAS,
)
from kamba_agr.turno import (
    ExecutorDeTurnos,
    GrafoNaoRegistadoError,
    Palavra,
    sem_grafos,
)


class GrafoEspia:
    """Um grafo de teste que registra as entradas e nunca se sobrepoe a si."""

    def __init__(self, atraso: float = 0.0) -> None:
        self.turnos: list[str] = []
        self.dentro = 0
        self.sobrepostas = 0
        self._atraso = atraso

    async def ainvoke(self, estado, config):
        self.dentro += 1
        if self.dentro > 1:
            self.sobrepostas += 1
        self.turnos.append(estado["turn_id"])
        self.config = config
        if self._atraso:
            await asyncio.sleep(self._atraso)
        else:
            # Um `sleep(0)` cede a *event loop*: sem ele, uma corrotina que
            # nunca espera corre do inicio ao fim e a sobreposicao era
            # impossivel por construcao — o teste passava sem medir nada.
            await asyncio.sleep(0)
        self.dentro -= 1
        return estado


def executor(
    palavra=Palavra(modo="bot", handoff_a_espera=False),
    grafo=None,
    tectos=None,
    reencaminhados=None,
):
    tranca = TrancaFalsa()
    grafo = grafo if grafo is not None else GrafoEspia()

    async def ler_palavra(_invocacao):
        return palavra

    async def reencaminhar(invocacoes):
        if reencaminhados is not None:
            reencaminhados.extend(invocacoes)

    return (
        ExecutorDeTurnos(
            trancas=tranca,
            ler_palavra=ler_palavra,
            grafos=lambda _i: grafo,
            reencaminhar=reencaminhar,
            admissao=Admissao(tectos=tectos or Tectos(coalescencia_ms=0)),
        ),
        tranca,
        grafo,
    )


class TestSerializacao(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    async def test_vinte_mensagens_da_mesma_thread_dao_vinte_turnos_em_serie(
        self,
    ) -> None:
        # Criterio 2, com a coalescencia a zero: e a propriedade da tranca, e e
        # por isso que a janela se desliga para a deixar ver.
        exec_, tranca, grafo = executor(grafo=GrafoEspia(atraso=0.001))
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        invocacoes = [
            ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
            for _ in range(20)
        ]
        desfechos = await asyncio.gather(*(exec_.correr(i) for i in invocacoes))

        self.assertEqual(len(desfechos), 20)
        self.assertEqual(grafo.sobrepostas, 0)
        self.assertEqual(tranca.sobrepostas, 0)
        self.assertEqual(len(grafo.turnos), 20)
        # Ordem de chegada preservada: a ordem em que o grafo viu os turnos e a
        # ordem em que as invocacoes entraram.
        self.assertEqual(grafo.turnos, [i.turn_id for i in invocacoes])
        self.assertEqual(METRICAS.ler()[f"{METRICA_TURNOS}:executado"], 20)

    async def test_a_tranca_e_tomada_uma_vez_por_lote(self) -> None:
        exec_, tranca, _ = executor()
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        thread = f"{tenant}:{contacto}"
        invocacoes = [
            ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
            for _ in range(5)
        ]
        await asyncio.gather(*(exec_.correr(i) for i in invocacoes))
        self.assertEqual(tranca.tomadas, [thread] * 5)

    async def test_duas_conversas_diferentes_nao_se_travam(self) -> None:
        exec_, _, grafo = executor(grafo=GrafoEspia(atraso=0.01))
        a = ler_invocacao(invocacao_crua())
        b = ler_invocacao(invocacao_crua())
        await asyncio.gather(exec_.correr(a), exec_.correr(b))
        self.assertEqual(sorted(grafo.turnos), sorted([a.turn_id, b.turn_id]))

    async def test_o_thread_id_vai_ao_configurable_do_grafo(self) -> None:
        # `{"configurable": {"thread_id": ...}}` e o que o `interrupt()` do
        # LangGraph exige (`docs/tecnica/02` §11).
        exec_, _, grafo = executor()
        invocacao = ler_invocacao(invocacao_crua())
        await exec_.correr(invocacao)
        self.assertEqual(grafo.config, {"configurable": {"thread_id": invocacao.thread_id}})


class TestCoalescenciaNoExecutor(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    async def test_mensagens_que_chegam_durante_um_turno_juntam_se(self) -> None:
        # Criterio 3. As que chegam enquanto o primeiro turno corre ficam em
        # fila; as que distam menos de 1,5 s entram no mesmo lote.
        exec_, _, grafo = executor(
            grafo=GrafoEspia(atraso=0.02), tectos=Tectos(coalescencia_ms=1_500)
        )
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        invocacoes = [
            ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
            for _ in range(6)
        ]
        desfechos = await asyncio.gather(*(exec_.correr(i) for i in invocacoes))

        # Seis mensagens, dois lotes no maximo. **Quantos** depende de o dreno
        # arrancar antes ou depois de as seis estarem na fila, e isso e a
        # ordem em que o `asyncio` escalona — nao se fixa o numero, fixa-se o
        # invariante: cada mensagem que nao abriu um lote foi coalescida.
        self.assertEqual(len(desfechos), 6)
        self.assertGreaterEqual(len(grafo.turnos), 1)
        self.assertLessEqual(len(grafo.turnos), 2)
        self.assertEqual(
            METRICAS.ler()[METRICA_COALESCIDAS], 6 - len(grafo.turnos)
        )
        # Todas as do lote recebem o **mesmo** desfecho, com o `turn_id` do
        # turno que correu: e o que diz ao *shim* que a mensagem foi tratada e
        # que o *job* se pode completar.
        self.assertTrue(all(d.turn_id in grafo.turnos for d in desfechos))
        self.assertGreaterEqual(max(d.coalescidos for d in desfechos), 1)

    async def test_uma_chegada_na_fronteira_do_dreno_nao_fica_pendurada(self) -> None:
        # A corrida que o `finally` do `_drenar` fecha: entre o `while` ver a
        # fila vazia e o dreno sair do registo, uma invocacao nova via um dreno
        # ainda vivo e ficava sem ninguem a drena-la.
        exec_, _, grafo = executor(grafo=GrafoEspia(atraso=0.005))
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        primeira = ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
        tarefa = asyncio.create_task(exec_.correr(primeira))
        for _ in range(30):
            await asyncio.sleep(0)
        segunda = ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
        desfechos = await asyncio.wait_for(
            asyncio.gather(tarefa, exec_.correr(segunda)), timeout=5
        )
        self.assertEqual(len(desfechos), 2)
        self.assertIn(segunda.turn_id, grafo.turnos)


class TestQuemTemAPalavra(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    async def test_uma_conversa_em_bot_entra_no_grafo(self) -> None:
        exec_, _, grafo = executor(Palavra(modo="bot", handoff_a_espera=False))
        desfecho = await exec_.correr(ler_invocacao(invocacao_crua()))
        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(len(grafo.turnos), 1)

    async def test_os_tres_modos_que_nao_sao_bot_vao_ao_hnd(self) -> None:
        # Criterio 6 e invariante do `docs/tecnica/02` §11 regra 4.
        for modo in ("dono", "humano", "pausada"):
            with self.subTest(modo=modo):
                reencaminhados: list = []
                exec_, _, grafo = executor(
                    Palavra(modo=modo, handoff_a_espera=False),
                    reencaminhados=reencaminhados,
                )
                invocacao = ler_invocacao(invocacao_crua())
                desfecho = await exec_.correr(invocacao)
                self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
                self.assertEqual(grafo.turnos, [])
                self.assertEqual([i.turn_id for i in reencaminhados], [invocacao.turn_id])

    async def test_um_handoff_a_espera_fecha_a_porta_mesmo_em_bot(self) -> None:
        reencaminhados: list = []
        exec_, _, grafo = executor(
            Palavra(modo="bot", handoff_a_espera=True), reencaminhados=reencaminhados
        )
        desfecho = await exec_.correr(ler_invocacao(invocacao_crua()))
        self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
        self.assertEqual(grafo.turnos, [])
        self.assertEqual(len(reencaminhados), 1)

    async def test_um_modo_desconhecido_fecha_a_porta(self) -> None:
        # Lista de permitidos e nao de proibidos: um modo novo no dominio nao
        # pode abrir a porta por omissao.
        exec_, _, grafo = executor(Palavra(modo="modo_novo", handoff_a_espera=False))
        desfecho = await exec_.correr(ler_invocacao(invocacao_crua()))
        self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
        self.assertEqual(grafo.turnos, [])

    async def test_zero_linhas_nao_e_bot(self) -> None:
        # O furo de isolamento mais barato que este ticket podia ter: um
        # `or 'bot'` aqui bastava para o AGR correr um turno sobre a conversa de
        # outro quando o contexto de RLS estivesse trocado.
        exec_, _, grafo = executor(palavra=None)
        desfecho = await exec_.correr(ler_invocacao(invocacao_crua()))
        self.assertEqual(desfecho.desfecho, "sem_conversa")
        self.assertEqual(grafo.turnos, [])
        self.assertEqual(METRICAS.ler()[f"{METRICA_TURNOS}:sem_conversa"], 1)


class TestFalhas(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    async def test_sem_grafo_registado_levanta_e_conta_como_falhou(self) -> None:
        tranca = TrancaFalsa()

        async def ler_palavra(_i):
            return Palavra(modo="bot", handoff_a_espera=False)

        async def reencaminhar(_i):
            return None

        exec_ = ExecutorDeTurnos(
            trancas=tranca,
            ler_palavra=ler_palavra,
            grafos=sem_grafos,
            reencaminhar=reencaminhar,
            admissao=Admissao(tectos=Tectos(coalescencia_ms=0)),
        )
        with self.assertRaises(GrafoNaoRegistadoError):
            await exec_.correr(ler_invocacao(invocacao_crua()))
        self.assertEqual(METRICAS.ler()[f"{METRICA_TURNOS}:falhou"], 1)
        # A tranca foi tomada **e** largada: a `TrancaFalsa` conta `dentro`.
        self.assertEqual(tranca.dentro, 0)

    async def test_uma_falha_num_lote_chega_a_todos_os_que_esperavam(self) -> None:
        # Senao, as mensagens coalescidas ficavam penduradas para sempre e o
        # `lockDuration` do *shim* era quem as resolvia.
        class GrafoQueLevanta:
            async def ainvoke(self, estado, config):
                await asyncio.sleep(0)
                raise RuntimeError("rebentou")

        exec_, _, _ = executor(
            grafo=GrafoQueLevanta(), tectos=Tectos(coalescencia_ms=1_500)
        )
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        invocacoes = [
            ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
            for _ in range(4)
        ]
        resultados = await asyncio.gather(
            *(exec_.correr(i) for i in invocacoes), return_exceptions=True
        )
        self.assertEqual(len(resultados), 4)
        self.assertTrue(all(isinstance(r, RuntimeError) for r in resultados), resultados)

    async def test_a_duracao_mede_se_tambem_quando_o_turno_falha(self) -> None:
        class GrafoQueLevanta:
            async def ainvoke(self, estado, config):
                raise RuntimeError("rebentou")

        exec_, _, _ = executor(grafo=GrafoQueLevanta())
        with self.assertRaises(RuntimeError):
            await exec_.correr(ler_invocacao(invocacao_crua()))
        self.assertIn(METRICA_DURACAO, METRICAS.ler())


class TestAProfundidadeDaFila(unittest.IsolatedAsyncioTestCase):
    """O `agr_queue_depth` conta turnos **a espera**, nao lotes a correr.

    A primeira versao contava no `_correr_lote`, isto e, media os lotes **em
    execucao**: com um dreno por `thread_id` e o tecto do *tenant* a 3, o
    numero nunca passava de um valor pequeno, e o `AGR_LIMIAR_DE_CONTRAPRESSAO`
    de 100 era inalcancavel por construcao. A metrica dizia uma coisa e media
    outra, e um painel de contrapressao ficava a zero sob qualquer carga.
    Encontrado na revisao adversarial do proprio ticket.
    """

    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    async def test_a_fila_cresce_com_as_mensagens_a_espera(self) -> None:
        porta = asyncio.Event()

        class GrafoQueEspera:
            async def ainvoke(self, estado, config):
                await porta.wait()
                return estado

        exec_, _, _ = executor(grafo=GrafoQueEspera())
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        invocacoes = [
            ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
            for _ in range(8)
        ]
        tarefas = [asyncio.create_task(exec_.correr(i)) for i in invocacoes]
        for _ in range(50):
            await asyncio.sleep(0)

        # As oito estao a espera (uma dentro do grafo, sete na fila), e e esse o
        # numero que a metrica tem de dar.
        self.assertEqual(METRICAS.ler()[METRICA_FILA], 8)
        porta.set()
        await asyncio.wait_for(asyncio.gather(*tarefas), timeout=10)
        self.assertEqual(METRICAS.ler()[METRICA_FILA], 0)

    async def test_a_contrapressao_conta_a_passagem_do_limiar(self) -> None:
        porta = asyncio.Event()

        class GrafoQueEspera:
            async def ainvoke(self, estado, config):
                await porta.wait()
                return estado

        exec_, _, _ = executor(
            grafo=GrafoQueEspera(),
            tectos=Tectos(coalescencia_ms=0, limiar_de_contrapressao=5),
        )
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        tarefas = [
            asyncio.create_task(
                exec_.correr(
                    ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
                )
            )
            for _ in range(9)
        ]
        for _ in range(50):
            await asyncio.sleep(0)
        self.assertEqual(METRICAS.ler()[METRICA_CONTRAPRESSAO], 1)
        porta.set()
        await asyncio.wait_for(asyncio.gather(*tarefas), timeout=10)


class TestODrenoNaoPenduraNinguem(unittest.IsolatedAsyncioTestCase):
    """Uma falha **fora** do `_correr_lote` nao deixa pedidos pendurados.

    Os dois modos de falha que isto fecha, os dois piores do que um erro: o
    dreno a renascer em ciclo sobre a mesma excepcao, e os `Future` dos
    pendentes sem ninguem a resolve-los — isto e, **todos os pedidos HTTP
    daquela conversa pendurados ate o `lockDuration` do shim expirar**.
    Encontrado na revisao adversarial do proprio ticket.
    """

    async def asyncSetUp(self) -> None:
        METRICAS.repor()

    async def test_uma_falha_na_coalescencia_falha_os_pedidos(self) -> None:
        class AdmissaoQueRebenta(Admissao):
            def coalescer(self, pendentes):
                raise RuntimeError("a coalescencia rebentou")

        tranca = TrancaFalsa()

        async def ler_palavra(_i):
            return Palavra(modo="bot", handoff_a_espera=False)

        async def reencaminhar(_i):
            return None

        exec_ = ExecutorDeTurnos(
            trancas=tranca,
            ler_palavra=ler_palavra,
            grafos=lambda _i: GrafoEspia(),
            reencaminhar=reencaminhar,
            admissao=AdmissaoQueRebenta(tectos=Tectos(coalescencia_ms=0)),
        )
        tenant, contacto = str(uuid.uuid4()), str(uuid.uuid4())
        invocacoes = [
            ler_invocacao(invocacao_crua(tenant_id=tenant, contact_id=contacto))
            for _ in range(3)
        ]
        resultados = await asyncio.wait_for(
            asyncio.gather(
                *(exec_.correr(i) for i in invocacoes), return_exceptions=True
            ),
            timeout=10,
        )
        self.assertEqual(len(resultados), 3)
        self.assertTrue(
            all(isinstance(r, RuntimeError) for r in resultados), resultados
        )
        # E a fila fica vazia: nem pendentes orfaos, nem dreno a renascer.
        self.assertEqual(METRICAS.ler().get(METRICA_FILA, 0), 0)

    async def test_e_a_conversa_seguinte_continua_a_funcionar(self) -> None:
        # Senao, a falha de uma conversa envenenava o processo.
        falhas = {"restantes": 1}
        real = Admissao.coalescer

        class AdmissaoQueRebentaUmaVez(Admissao):
            def coalescer(self, pendentes):
                if falhas["restantes"] > 0:
                    falhas["restantes"] -= 1
                    raise RuntimeError("uma vez")
                return real(self, pendentes)

        tranca = TrancaFalsa()
        grafo = GrafoEspia()

        async def ler_palavra(_i):
            return Palavra(modo="bot", handoff_a_espera=False)

        async def reencaminhar(_i):
            return None

        exec_ = ExecutorDeTurnos(
            trancas=tranca,
            ler_palavra=ler_palavra,
            grafos=lambda _i: grafo,
            reencaminhar=reencaminhar,
            admissao=AdmissaoQueRebentaUmaVez(tectos=Tectos(coalescencia_ms=0)),
        )
        with self.assertRaises(RuntimeError):
            await asyncio.wait_for(
                exec_.correr(ler_invocacao(invocacao_crua())), timeout=10
            )
        desfecho = await asyncio.wait_for(
            exec_.correr(ler_invocacao(invocacao_crua())), timeout=10
        )
        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(len(grafo.turnos), 1)

if __name__ == "__main__":
    unittest.main()
