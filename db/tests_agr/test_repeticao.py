"""O turno repete-se e o Outbound (falso) nao duplica (KAM-025 criterio 4).

O criterio pede tres coisas, e esta bateria mede as tres com o executor
**verdadeiro** sobre a base **verdadeira**:

1. um turno interrompido a meio repete-se desde o inicio;
2. o envio ao Outbound (fake) usa `idempotency_key = turn_id:seq`;
3. o numero de duplicados e **0**.

## Porque e que isto esta na suite da base e nao no *gate* 4

Porque a repeticao que importa e a que acontece **com a tranca pelo meio**: o
turno levanta, a tranca larga, outro turno do mesmo *thread* entra e corre o
mesmo `turn_id` outra vez. Com uma tranca falsa isso e uma sequencia de chamadas
que o teste escreve; com a tranca de sessao e o que o servidor permite, e e a
unica forma de provar que a segunda volta **consegue** entrar.
"""

from __future__ import annotations

import asyncio
import unittest

from tests_agr.base import ComAgr
from tests_agr.base import thread_id_de

from kamba_agr.admissao import Admissao, Tectos
from kamba_agr.contexto import InvocacaoDoAgente
from kamba_agr.conversa import leitor
from kamba_agr.metricas import METRICA_TURNOS, METRICAS
from kamba_agr.trancas import TrancaDeConversas
from kamba_agr.turno import ExecutorDeTurnos, Palavra


class OutboundFalso:
    """O «(fake)» que o proprio criterio 4 nomeia. Conta por chave.

    Guarda **todas** as chaves que lhe chegam, e nao um conjunto: contar
    duplicados exige ver a repeticao, e um `set` escondia exactamente o que se
    esta a medir.
    """

    def __init__(self) -> None:
        self.chaves: list[str] = []

    def enviar(self, chave: str) -> None:
        self.chaves.append(chave)

    @property
    def duplicados(self) -> int:
        return len(self.chaves) - len(set(self.chaves))

    @property
    def enviadas(self) -> int:
        return len(set(self.chaves))


class GrafoQueEnvia:
    """Um grafo de teste que envia uma mensagem e, se lhe mandarem, levanta."""

    def __init__(self, outbound: OutboundFalso, falhar_nas: int = 0) -> None:
        self._outbound = outbound
        self._falhar_nas = falhar_nas
        self.voltas = 0

    async def ainvoke(self, estado, config):
        self.voltas += 1
        # O `seq` conta **dentro** do turno e comeca em 0 em cada volta, de
        # proposito: um contador que sobrevivesse a repeticao dava chaves novas
        # e o Outbound mandava a mensagem duas vezes.
        invocacao = self._invocacao(estado)
        self._outbound.enviar(invocacao.chave_de_envio(0))
        if self.voltas <= self._falhar_nas:
            raise RuntimeError("o turno rebentou depois do envio")
        self._outbound.enviar(invocacao.chave_de_envio(1))
        return estado

    @staticmethod
    def _invocacao(estado) -> InvocacaoDoAgente:
        return InvocacaoDoAgente(
            tenant_id=estado["tenant_id"],
            contact_id=estado["contact_id"],
            conversation_id=estado["conversation_id"],
            channel_id=estado["channel_id"],
            wamid=estado["turn_id"],
            type="text",
            modo="bot",
            thread_id=estado["thread_id"],
            vertical=estado["vertical"],
        )


class TestRepeticao(ComAgr):
    def setUp(self) -> None:
        super().setUp()
        METRICAS.repor()

    def _executor(self, grafo, reencaminhados=None):
        """O executor verdadeiro, com a tranca e a leitura verdadeiras."""
        import ligacao as modulo

        def abrir_tranca():
            conexao = modulo.ligar("app")
            conexao.autocommit = True
            self._conexoes.append(conexao)
            return conexao

        def abrir_leitura():
            conexao = modulo.ligar("app")
            self._conexoes.append(conexao)
            return conexao

        async def reencaminhar(invocacoes):
            if reencaminhados is not None:
                reencaminhados.extend(invocacoes)

        return ExecutorDeTurnos(
            trancas=TrancaDeConversas(abrir_tranca),
            ler_palavra=leitor(abrir_leitura),
            grafos=lambda _i: grafo,
            reencaminhar=reencaminhar,
            # Coalescencia a zero: o que se mede aqui e a repeticao de **um**
            # turno, e juntar duas mensagens num lote escondia a segunda volta.
            admissao=Admissao(tectos=Tectos(coalescencia_ms=0, tecto_por_tenant=0)),
        )

    def _invocacao(self, conversa, wamid: str) -> InvocacaoDoAgente:
        return InvocacaoDoAgente(
            tenant_id=conversa.tenant_id,
            contact_id=conversa.contact_id,
            conversation_id=conversa.conversation_id,
            channel_id=conversa.canal_id,
            wamid=wamid,
            type="text",
            modo="bot",
            thread_id=thread_id_de(conversa.tenant_id, conversa.contact_id),
            vertical="vendedor",
        )

    def test_um_turno_que_falha_e_repetido_nao_duplica_o_envio(self) -> None:
        conversa = self.criar_conversa()
        outbound = OutboundFalso()
        grafo = GrafoQueEnvia(outbound, falhar_nas=1)
        executor = self._executor(grafo)
        invocacao = self._invocacao(conversa, "wamid.ENSAIO.repeticao")

        async def correr():
            # Primeira volta: levanta depois de enviar a chave `:0`.
            with self.assertRaises(RuntimeError):
                await executor.correr(invocacao)
            # Segunda volta: o *job* voltou a fila e o AGR recebe o **mesmo**
            # `turn_id`. E aqui que a tranca tem de deixar entrar.
            desfecho = await executor.correr(invocacao)
            return desfecho

        desfecho = asyncio.run(correr())
        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(grafo.voltas, 2, "o turno nao se repetiu")
        # A chave `:0` chegou duas vezes ao Outbound, e e isso que faz o teste
        # valer: o que se prova e que as duas vezes trazem a **mesma** chave, e
        # que o Outbound (que deduplica por ela) manda uma mensagem so.
        self.assertEqual(outbound.chaves.count(invocacao.chave_de_envio(0)), 2)
        self.assertEqual(outbound.enviadas, 2, "esperavam-se duas chaves distintas")
        self.assertEqual(
            len(set(outbound.chaves)),
            2,
            f"chaves repetidas tem de ser as mesmas: {outbound.chaves}",
        )
        self.assertEqual(
            sorted(set(outbound.chaves)),
            [invocacao.chave_de_envio(0), invocacao.chave_de_envio(1)],
        )

    def test_a_chave_e_turn_id_dois_pontos_seq(self) -> None:
        conversa = self.criar_conversa()
        outbound = OutboundFalso()
        executor = self._executor(GrafoQueEnvia(outbound))
        invocacao = self._invocacao(conversa, "wamid.ENSAIO.chave")
        asyncio.run(executor.correr(invocacao))
        self.assertEqual(
            outbound.chaves,
            ["wamid.ENSAIO.chave:0", "wamid.ENSAIO.chave:1"],
        )

    def test_vinte_voltas_do_mesmo_turno_dao_duas_chaves(self) -> None:
        # «0 duplicados» a letra: vinte entregas do mesmo *job* nao produzem
        # chave nova nenhuma.
        conversa = self.criar_conversa()
        outbound = OutboundFalso()
        executor = self._executor(GrafoQueEnvia(outbound))
        invocacao = self._invocacao(conversa, "wamid.ENSAIO.vinte")

        async def correr():
            for _ in range(20):
                await executor.correr(invocacao)

        asyncio.run(correr())
        self.assertEqual(outbound.enviadas, 2)
        self.assertEqual(outbound.duplicados, 38)
        self.assertEqual(
            sorted(set(outbound.chaves)),
            ["wamid.ENSAIO.vinte:0", "wamid.ENSAIO.vinte:1"],
        )

    def test_turnos_diferentes_dao_chaves_diferentes(self) -> None:
        # O outro lado da moeda: uma recompra com `wamid` novo **tem** de dar
        # chaves novas, senao a segunda mensagem era deduplicada.
        conversa = self.criar_conversa()
        outbound = OutboundFalso()
        executor = self._executor(GrafoQueEnvia(outbound))

        async def correr():
            for n in range(3):
                await executor.correr(self._invocacao(conversa, f"wamid.ENSAIO.n{n}"))

        asyncio.run(correr())
        self.assertEqual(outbound.enviadas, 6)
        self.assertEqual(outbound.duplicados, 0)


class TestSerieContraABase(ComAgr):
    """Criterio 2: 20 turnos em serie, pela ordem, com um executor.

    **O que este teste mede, e o que nao mede.** Ele constroi **um**
    `ExecutorDeTurnos`, logo **uma** `TrancaDeConversas`, logo **uma** ligacao —
    e o `pg_advisory_lock` conta por **sessao**: a segunda tomada da mesma chave
    na mesma sessao e concedida de imediato. Portanto a serializacao que este
    teste observa vem do **dreno por conversa** de `turno.py`, e nao da base.

    Nao e um defeito do teste: a ordem de chegada e exactamente o que o dreno
    garante, e e o que o criterio 2 pede. Mas a afirmacao «sem a janela a zero
    um defeito na tranca ficava invisivel» estava ao contrario — a este teste um
    defeito na tranca **e** invisivel —, e a revisao adversarial apanhou-a.

    Quem mede a tranca entre sessoes e, por ordem de forca:
    `test_tranca.py::TestExclusaoMutua` (SQL cru, duas ligacoes),
    `TestDoisExecutoresNaMesmaConversa` (abaixo, o **cliente** da tranca com
    duas ligacoes) e `test_tranca.py::TestMorteDoWorker` (o SIGKILL).
    """

    def setUp(self) -> None:
        super().setUp()
        METRICAS.repor()

    def test_vinte_mensagens_da_mesma_thread_correm_em_serie_e_por_ordem(self) -> None:
        conversa = self.criar_conversa()
        ordem: list[str] = []
        dentro = {"agora": 0, "maximo": 0}

        class GrafoQueObserva:
            async def ainvoke(self, estado, config):
                dentro["agora"] += 1
                dentro["maximo"] = max(dentro["maximo"], dentro["agora"])
                ordem.append(estado["turn_id"])
                await asyncio.sleep(0.001)
                dentro["agora"] -= 1
                return estado

        import ligacao as modulo

        def abrir_tranca():
            conexao = modulo.ligar("app")
            conexao.autocommit = True
            self._conexoes.append(conexao)
            return conexao

        def abrir_leitura():
            conexao = modulo.ligar("app")
            self._conexoes.append(conexao)
            return conexao

        async def reencaminhar(_i):
            return None

        executor = ExecutorDeTurnos(
            trancas=TrancaDeConversas(abrir_tranca),
            ler_palavra=leitor(abrir_leitura),
            grafos=lambda _i: GrafoQueObserva(),
            reencaminhar=reencaminhar,
            # Os dois tectos desligados: e a tranca que se mede. Com a
            # coalescencia a 1,5 s as vinte davam um turno, e com o tecto a 3
            # davam dezessete recusas — a tensao entre os criterios 2 e 3 esta
            # escrita em `kamba_agr/admissao.py`.
            admissao=Admissao(tectos=Tectos(coalescencia_ms=0, tecto_por_tenant=0)),
        )
        wamids = [f"wamid.ENSAIO.serie{n:02d}" for n in range(20)]

        async def correr():
            invocacoes = [
                InvocacaoDoAgente(
                    tenant_id=conversa.tenant_id,
                    contact_id=conversa.contact_id,
                    conversation_id=conversa.conversation_id,
                    channel_id=conversa.canal_id,
                    wamid=wamid,
                    type="text",
                    modo="bot",
                    thread_id=conversa.thread_id,
                    vertical="vendedor",
                )
                for wamid in wamids
            ]
            return await asyncio.gather(*(executor.correr(i) for i in invocacoes))

        desfechos = asyncio.run(correr())

        self.assertEqual(len(desfechos), 20)
        self.assertEqual(dentro["maximo"], 1, "houve execucoes sobrepostas")
        self.assertEqual(ordem, wamids, "a ordem de chegada nao se preservou")
        self.assertEqual(METRICAS.ler()[f"{METRICA_TURNOS}:executado"], 20)


class TestODesfechoQuandoNaoSeLeAConversa(ComAgr):
    """As duas propriedades que a prova por mutacao descobriu em falta.

    As duas tinham bateria no *gate* 4 (`services/agr/tests/test_turno.py`) e
    **nenhuma** aqui, e as mutacoes `agr: zero linhas passa a ler-se como bot` e
    `agr: o modo deixa de ser lista de permitidos` sobreviveram a primeira
    execucao da `tests_agr` por causa disso. Nao e uma duplicacao do *gate* 4: a
    primeira destas duas e **mais forte** do lado da base, porque quem esconde a
    linha e a RLS e nao um duplo.
    """

    def setUp(self) -> None:
        super().setUp()
        METRICAS.repor()

    def _executor_com_palavra(self, palavra, grafo):
        """O executor com a tranca **verdadeira** e a palavra dada.

        A tranca e a da base — e o que faz esta bateria pertencer a esta suite —
        e a leitura e injectada, para se poder pedir um modo que o
        `conversations_mode_ck` nao deixa escrever.
        """
        import ligacao as modulo

        def abrir_tranca():
            conexao = modulo.ligar("app")
            conexao.autocommit = True
            self._conexoes.append(conexao)
            return conexao

        async def ler_palavra(_invocacao):
            return palavra

        async def reencaminhar(_invocacoes):
            return None

        return ExecutorDeTurnos(
            trancas=TrancaDeConversas(abrir_tranca),
            ler_palavra=ler_palavra,
            grafos=lambda _i: grafo,
            reencaminhar=reencaminhar,
            admissao=Admissao(tectos=Tectos(coalescencia_ms=0, tecto_por_tenant=0)),
        )

    def test_a_conversa_que_a_rls_esconde_nao_entra_no_grafo(self) -> None:
        """O X-02 ponta a ponta: nao e um duplo que devolve `None`, e a RLS.

        Corre o `leitor` **verdadeiro** contra a base, com a invocacao de um
        *tenant* e o contexto a resolver-se dele: a conversa pertence a outro, e
        o que devolve zero linhas e a politica `tenant_iso`. Um `or 'bot'` no
        `turno.py` fazia o AGR correr um turno sobre a conversa de outro.
        """
        import ligacao as modulo

        de_a = self.criar_conversa()
        de_b = self.criar_conversa()

        def abrir_tranca():
            conexao = modulo.ligar("app")
            conexao.autocommit = True
            self._conexoes.append(conexao)
            return conexao

        def abrir_leitura():
            conexao = modulo.ligar("app")
            self._conexoes.append(conexao)
            return conexao

        outbound = OutboundFalso()
        grafo = GrafoQueEnvia(outbound)

        async def reencaminhar(_invocacoes):
            return None

        executor = ExecutorDeTurnos(
            trancas=TrancaDeConversas(abrir_tranca),
            ler_palavra=leitor(abrir_leitura),
            grafos=lambda _i: grafo,
            reencaminhar=reencaminhar,
            admissao=Admissao(tectos=Tectos(coalescencia_ms=0, tecto_por_tenant=0)),
        )

        # O `tenant_id` e o de B — logo o contexto de RLS e o de B — e o
        # `conversation_id` e o de A. E a forma exacta de um contexto trocado.
        invocacao = InvocacaoDoAgente(
            tenant_id=de_b.tenant_id,
            contact_id=de_b.contact_id,
            conversation_id=de_a.conversation_id,
            channel_id=de_b.canal_id,
            wamid="wamid.ENSAIO.x02",
            type="text",
            modo="bot",
            thread_id=thread_id_de(de_b.tenant_id, de_b.contact_id),
            vertical="vendedor",
        )
        desfecho = asyncio.run(executor.correr(invocacao))

        self.assertEqual(desfecho.desfecho, "sem_conversa")
        self.assertEqual(grafo.voltas, 0, "o grafo correu sobre a conversa de outro")
        self.assertEqual(outbound.chaves, [], "houve envio sobre a conversa de outro")
        self.assertEqual(METRICAS.ler()[f"{METRICA_TURNOS}:sem_conversa"], 1)

    def test_a_conversa_que_nao_existe_tambem_nao_entra(self) -> None:
        # O outro caminho que da zero linhas, e que tem de dar o mesmo desfecho.
        import uuid as _uuid

        import ligacao as modulo

        conversa = self.criar_conversa()

        def abrir_tranca():
            conexao = modulo.ligar("app")
            conexao.autocommit = True
            self._conexoes.append(conexao)
            return conexao

        def abrir_leitura():
            conexao = modulo.ligar("app")
            self._conexoes.append(conexao)
            return conexao

        grafo = GrafoQueEnvia(OutboundFalso())

        async def reencaminhar(_invocacoes):
            return None

        executor = ExecutorDeTurnos(
            trancas=TrancaDeConversas(abrir_tranca),
            ler_palavra=leitor(abrir_leitura),
            grafos=lambda _i: grafo,
            reencaminhar=reencaminhar,
            admissao=Admissao(tectos=Tectos(coalescencia_ms=0, tecto_por_tenant=0)),
        )
        invocacao = InvocacaoDoAgente(
            tenant_id=conversa.tenant_id,
            contact_id=conversa.contact_id,
            conversation_id=str(_uuid.uuid4()),
            channel_id=conversa.canal_id,
            wamid="wamid.ENSAIO.inexistente",
            type="text",
            modo="bot",
            thread_id=conversa.thread_id,
            vertical="vendedor",
        )
        desfecho = asyncio.run(executor.correr(invocacao))
        self.assertEqual(desfecho.desfecho, "sem_conversa")
        self.assertEqual(grafo.voltas, 0)

    def test_um_modo_que_a_base_nao_deixa_escrever_fecha_a_porta(self) -> None:
        """Lista de permitidos e nao de proibidos, e so um quinto modo o mostra.

        O `conversations_mode_ck` nao deixa escrever um quinto valor, pelo que
        este caso nao se semeia: injecta-se a `Palavra`. E a unica coisa desta
        bateria que nao vem da base, e esta aqui porque e onde a mutacao corre —
        `modo != 'bot'` e `modo in ('dono','humano','pausada')` sao equivalentes
        para os quatro valores de hoje, e divergem no dia em que houver um
        quinto. O lado seguro de errar e fechar a porta.
        """
        outbound = OutboundFalso()
        grafo = GrafoQueEnvia(outbound)
        conversa = self.criar_conversa()
        executor = self._executor_com_palavra(
            Palavra(modo="modo_que_ainda_nao_existe", handoff_a_espera=False), grafo
        )
        invocacao = InvocacaoDoAgente(
            tenant_id=conversa.tenant_id,
            contact_id=conversa.contact_id,
            conversation_id=conversa.conversation_id,
            channel_id=conversa.canal_id,
            wamid="wamid.ENSAIO.modo",
            type="text",
            modo="bot",
            thread_id=conversa.thread_id,
            vertical="vendedor",
        )
        desfecho = asyncio.run(executor.correr(invocacao))
        self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
        self.assertEqual(grafo.voltas, 0)
        self.assertEqual(outbound.chaves, [])

    def test_os_tres_modos_de_hoje_tambem_fecham(self) -> None:
        # Sem isto, o teste de cima passava com uma guarda que fechasse a porta
        # a **tudo** — e o `executado` nunca acontecia.
        for modo in ("dono", "humano", "pausada"):
            with self.subTest(modo=modo):
                grafo = GrafoQueEnvia(OutboundFalso())
                conversa = self.criar_conversa()
                executor = self._executor_com_palavra(
                    Palavra(modo=modo, handoff_a_espera=False), grafo
                )
                desfecho = asyncio.run(
                    executor.correr(
                        InvocacaoDoAgente(
                            tenant_id=conversa.tenant_id,
                            contact_id=conversa.contact_id,
                            conversation_id=conversa.conversation_id,
                            channel_id=conversa.canal_id,
                            wamid=f"wamid.ENSAIO.{modo}",
                            type="text",
                            modo="bot",
                            thread_id=conversa.thread_id,
                            vertical="vendedor",
                        )
                    )
                )
                self.assertEqual(desfecho.desfecho, "entregue_ao_hnd")
                self.assertEqual(grafo.voltas, 0)

    def test_e_em_bot_sem_handoff_o_grafo_corre(self) -> None:
        # O controlo positivo das quatro asercoes negativas acima.
        grafo = GrafoQueEnvia(OutboundFalso())
        conversa = self.criar_conversa()
        executor = self._executor_com_palavra(
            Palavra(modo="bot", handoff_a_espera=False), grafo
        )
        desfecho = asyncio.run(
            executor.correr(
                InvocacaoDoAgente(
                    tenant_id=conversa.tenant_id,
                    contact_id=conversa.contact_id,
                    conversation_id=conversa.conversation_id,
                    channel_id=conversa.canal_id,
                    wamid="wamid.ENSAIO.positivo",
                    type="text",
                    modo="bot",
                    thread_id=conversa.thread_id,
                    vertical="vendedor",
                )
            )
        )
        self.assertEqual(desfecho.desfecho, "executado")
        self.assertEqual(grafo.voltas, 1)

class TestDoisExecutoresNaMesmaConversa(ComAgr):
    """Dois executores, duas ligacoes, a mesma conversa: so um turno de cada vez.

    E o teste que faltava, e e o que mede o **cliente** da tranca: o
    `test_tranca.py` prova que o `pg_try_advisory_lock` exclui entre sessoes com
    SQL cru, e o `TestSerieContraABase` prova a ordem com um executor so. Entre
    os dois ficava um vazio — ninguem exercitava dois `TrancaDeConversas` sobre
    a mesma chave —, e era nesse vazio que vivia o defeito que a revisao
    adversarial encontrou: a primeira versao usava `pg_advisory_lock`, que
    **bloqueia** no servidor, dentro do `asyncio.Lock` que serializa a unica
    ligacao do processo. Uma conversa a espera parava o processo inteiro, e as
    que acabaram nao conseguiam destrancar.

    **Dois executores no mesmo processo e nao dois processos**, de proposito:
    dois processos provariam a exclusao (que o `test_tranca.py` ja prova) e nao
    o que aqui importa — que a espera de um nao prende o outro. Com uma
    *event loop* so, se a espera fosse exclusiva este teste nao terminava.
    """

    def setUp(self) -> None:
        super().setUp()
        METRICAS.repor()

    def _executor_proprio(self, grafo, ordem: list):
        """Um executor com `TrancaDeConversas` e ligacao **proprias**."""
        import ligacao as modulo

        def abrir_tranca():
            conexao = modulo.ligar("app")
            conexao.autocommit = True
            self._conexoes.append(conexao)
            return conexao

        async def ler_palavra(_invocacao):
            return Palavra(modo="bot", handoff_a_espera=False)

        async def reencaminhar(_invocacoes):
            return None

        return ExecutorDeTurnos(
            trancas=TrancaDeConversas(abrir_tranca),
            ler_palavra=ler_palavra,
            grafos=lambda _i: grafo,
            reencaminhar=reencaminhar,
            admissao=Admissao(tectos=Tectos(coalescencia_ms=0, tecto_por_tenant=0)),
        )

    def _invocacao(self, conversa, wamid: str) -> InvocacaoDoAgente:
        return InvocacaoDoAgente(
            tenant_id=conversa.tenant_id,
            contact_id=conversa.contact_id,
            conversation_id=conversa.conversation_id,
            channel_id=conversa.canal_id,
            wamid=wamid,
            type="text",
            modo="bot",
            thread_id=conversa.thread_id,
            vertical="vendedor",
        )

    def test_os_dois_turnos_nao_se_sobrepoem(self) -> None:
        conversa = self.criar_conversa()
        dentro = {"agora": 0, "maximo": 0}
        ordem: list[str] = []

        class GrafoQueDemora:
            async def ainvoke(self, estado, config):
                dentro["agora"] += 1
                dentro["maximo"] = max(dentro["maximo"], dentro["agora"])
                ordem.append(estado["turn_id"])
                # Longo o suficiente para que, sem tranca, as duas se cruzem.
                await asyncio.sleep(0.3)
                dentro["agora"] -= 1
                return estado

        grafo = GrafoQueDemora()
        primeiro = self._executor_proprio(grafo, ordem)
        segundo = self._executor_proprio(grafo, ordem)

        async def correr():
            return await asyncio.wait_for(
                asyncio.gather(
                    primeiro.correr(self._invocacao(conversa, "wamid.ENSAIO.dois.a")),
                    segundo.correr(self._invocacao(conversa, "wamid.ENSAIO.dois.b")),
                ),
                timeout=120,
            )

        desfechos = asyncio.run(correr())

        self.assertEqual([d.desfecho for d in desfechos], ["executado", "executado"])
        self.assertEqual(
            dentro["maximo"],
            1,
            "dois turnos correram ao mesmo tempo sobre a mesma conversa: a "
            "tranca de sessao nao excluiu entre as duas ligacoes",
        )
        self.assertEqual(len(ordem), 2)

    def test_a_espera_de_uma_conversa_nao_prende_outra(self) -> None:
        """O defeito C2, medido: a espera nao pode ser exclusiva.

        O primeiro executor detem a tranca da conversa A durante 1 s. O segundo
        pede a **mesma** chave (fica a tentar) e, ao mesmo tempo, um terceiro
        pedido — de outra conversa, no **mesmo** executor que espera — tem de
        passar. Com a espera dentro do `asyncio.Lock` da ligacao, o terceiro
        ficava preso atras do segundo e este teste estourava o `wait_for`.
        """
        a = self.criar_conversa()
        b = self.criar_conversa()
        acabou_b = {"quando": None}

        class GrafoLento:
            async def ainvoke(self, estado, config):
                await asyncio.sleep(1.0)
                return estado

        class GrafoRapido:
            async def ainvoke(self, estado, config):
                acabou_b["quando"] = asyncio.get_running_loop().time()
                return estado

        lento = self._executor_proprio(GrafoLento(), [])
        # **O mesmo** executor para o que espera e para o que passa: e assim
        # que eles partilham a ligacao de tranca, que e onde o defeito vivia.
        outro = self._executor_proprio(GrafoRapido(), [])

        async def correr():
            comecou = asyncio.get_running_loop().time()
            segurar = asyncio.create_task(
                lento.correr(self._invocacao(a, "wamid.ENSAIO.segura"))
            )
            await asyncio.sleep(0.15)  # deixa o primeiro tomar a tranca
            espera = asyncio.create_task(
                outro.correr(self._invocacao(a, "wamid.ENSAIO.espera"))
            )
            await asyncio.sleep(0.05)
            passa = asyncio.create_task(
                outro.correr(self._invocacao(b, "wamid.ENSAIO.passa"))
            )
            # O de outra conversa tem de acabar **antes** de o lento largar.
            await asyncio.wait_for(passa, timeout=30)
            fim_do_que_passa = acabou_b["quando"]
            await asyncio.wait_for(asyncio.gather(segurar, espera), timeout=120)
            return comecou, fim_do_que_passa

        comecou, fim_do_que_passa = asyncio.run(correr())
        self.assertIsNotNone(fim_do_que_passa)
        self.assertLess(
            fim_do_que_passa - comecou,
            1.0,
            "a conversa B esperou pelo turno da conversa A: a espera pela "
            "tranca esta a prender a ligacao do processo (defeito C2)",
        )

if __name__ == "__main__":
    unittest.main()
