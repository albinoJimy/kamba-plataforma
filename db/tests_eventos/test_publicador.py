"""Criterios 3, 4, 5 e 7 do KAM-005, contra PostgreSQL e fila reais.

Cada classe e um criterio, e esta dito qual. O que falha aqui falha o gate 8.

    TestPublicacao         o caminho normal, e a metade positiva de tudo o resto:
                           sem ela, «nao duplicou» provava-se com uma fila vazia.
    TestRoteamento         criterio 7: finalidade e *fan-out* por 16 filas.
    TestKill9              criterio 3: `kill -9` entre o `add` e o `COMMIT`.
    TestFilaParada         criterio 4: fila parada 60 s com 1 000 eventos.
    TestLideranca          criterio 5: dois publicadores, um publica.
"""

from __future__ import annotations

import time
import unittest
import uuid

from tests_eventos import node
from tests_eventos.base import (
    CONSUMER,
    CONSUMER_ANALITICO,
    TIPO,
    ComFila,
    esperar_por,
)

#: Criterio 4: «Redis parado 60 s com 1 000 eventos emitidos».
EVENTOS_DO_CRITERIO_4 = 1000
PARAGEM_DO_CRITERIO_4 = 60
#: «apos o regresso, 100% publicados em <= 60 s».
RECUPERACAO_DO_CRITERIO_4 = 60

#: Criterio 5: «a outra assume em <= 10 s quando a lider morre (proposta)».
ASSUNCAO_DO_CRITERIO_5 = 10


class TestPublicacao(ComFila):
    """O caminho normal. A metade positiva de que todo o resto depende."""

    def setUp(self) -> None:
        super().setUp()
        self.subscrever()

    def test_um_evento_vai_a_fila_da_sua_particao_com_o_event_id_por_jobId(self) -> None:
        (identificador,) = self.emitir()
        nome = self.nome_da_fila(identificador)
        self.lancar_publicador()

        self.assertTrue(
            esperar_por(lambda: self.fila.jobs(nome) == {identificador}, 30),
            f"a fila {nome} tem {self.fila.jobs(nome)}{self.diagnostico()}",
        )
        self.assertTrue(esperar_por(lambda: self.pendentes() == 0, 30))
        self.assertEqual(self.publicados(), 1)
        self.assertEqual(self.arquivados(), 1, "o evento tem de ficar no arquivo")
        # **Uma** entrada na lista de espera, e nao «a chave existe»: e este o
        # numero que distingue um job de dois (ANALISE-20, achado 3).
        self.assertEqual(self.fila.pendentes(nome), 1)
        self.assertEqual(self.fila.espera(nome), [identificador])

    def test_o_arquivo_fica_coerente_com_o_outbox(self) -> None:
        identificadores = self.emitir(5)
        self.lancar_publicador()
        self.assertTrue(esperar_por(lambda: self.arquivados() == 5, 60))
        self.cursor.execute(
            "SELECT count(*) FROM platform.events_log l "
            "  JOIN platform.events_outbox o USING (event_id) "
            " WHERE l.tenant_id = o.tenant_id AND l.agregado_seq = o.agregado_seq "
            "   AND l.ocorrido_em = (o.envelope->>'ocorrido_em')::timestamptz"
        )
        self.assertEqual(int(self.cursor.fetchone()[0]), 5)
        self.assertEqual(len(set(identificadores)), 5)

    def test_um_evento_sem_subscricao_arquiva_se_e_nao_vai_a_fila(self) -> None:
        self.cursor.execute("DELETE FROM platform.evt_subscricoes")
        self.emitir()
        self.lancar_publicador()
        self.assertTrue(esperar_por(lambda: self.publicados() == 1, 30))
        self.assertEqual(self.arquivados(), 1)
        self.assertEqual(self.fila.filas(), set(), "nao devia haver fila nenhuma")

    def test_uma_linha_envenenada_nao_prende_o_resto_do_lote(self) -> None:
        """Achado 1 da ANALISE-20: era perda de eventos com o outbox saudavel.

        Uma linha com envelope ilegivel entra no lote **antes** das boas (tem o
        `id` mais baixo). Na versao de fase unica, abortava a transaccao, as
        boas recuavam com ela, e no ciclo seguinte repetia-se o mesmo — para
        sempre, sem nunca entrarem no `events_log` (e por isso invisiveis para o
        reconciliador do §6.5). Com as duas fases, a linha ma fica de lado com o
        seu agregado e as outras publicam-se.
        """
        self.cursor.execute(
            "INSERT INTO platform.events_outbox "
            "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
            " agregado_seq, particao, envelope) "
            "VALUES (gen_random_uuid(), %s, 1, %s, 'order', 'agg-envenenado', 1, 0, "
            "%s::jsonb)",
            (TIPO, self.tenant, '{"tipo": "order.created"}'),
        )
        boas = self.emitir(3)
        self.lancar_publicador()

        self.assertTrue(
            esperar_por(lambda: self.publicados() == 3, 60),
            f"as linhas boas nao passaram: {self.pendentes()} pendentes"
            f"{self.diagnostico()}",
        )
        self.assertEqual(self.pendentes(), 1, "a linha envenenada devia ficar")
        self.cursor.execute(
            "SELECT tentativas > 0, proxima_tentativa_at > now() "
            "  FROM platform.events_outbox WHERE agregado_id = 'agg-envenenado'"
        )
        self.assertEqual(tuple(self.cursor.fetchone()), (True, True))
        for identificador in boas:
            with self.subTest(evento=identificador):
                self.assertEqual(
                    self.fila.pendentes(self.nome_da_fila(identificador)), 1
                )

    def test_a_linha_envenenada_arrasta_o_seu_agregado_e_mais_nenhum(self) -> None:
        """A outra metade do achado 1: o corte e por agregado.

        Se o corte fosse so da linha ma, a `seq` seguinte do mesmo agregado ia a
        fila com a anterior para tras — perda de ordem causal. Se fosse do lote,
        voltava o defeito. E por agregado: o agregado da linha ma espera, os
        outros seguem.
        """
        agregado = self.agregado_novo()
        primeira = self.emitir(1, agregado=agregado)[0]
        envenenada = self.emitir(1, agregado=agregado)[0]
        self.cursor.execute(
            "UPDATE platform.events_outbox SET envelope = %s::jsonb WHERE event_id = %s",
            ("{}", envenenada),
        )
        terceira = self.emitir(1, agregado=agregado)[0]
        de_outro_agregado = self.emitir(1)[0]

        self.lancar_publicador()
        self.assertTrue(
            esperar_por(lambda: self.publicados() == 2, 60),
            f"esperava 2 publicadas, ha {self.publicados()}{self.diagnostico()}",
        )
        self.cursor.execute(
            "SELECT event_id::text FROM platform.events_outbox "
            " WHERE publicado_at IS NOT NULL"
        )
        publicados = {linha[0] for linha in self.cursor.fetchall()}
        self.assertEqual(publicados, {primeira, de_outro_agregado})
        self.assertNotIn(terceira, publicados, "a `seq` seguinte do agregado passou")
        self.assertNotIn(envenenada, publicados)

    def _inserir_directo(self, envelope: str, particao: int = 0) -> str:
        """Uma linha no outbox **sem** passar pelo `evt_emitir`.

        E o caminho que o `evt_emitir` nao cobre (`kamba_batch`, uma migracao,
        um *replay*) e por isso e o unico em que as guardas do publicador tem
        efeito observavel. Sem estas linhas, tres mutacoes do publicador
        sobreviviam a esta suite (ANALISE-20, achado 5).
        """
        self.cursor.execute(
            "INSERT INTO platform.events_outbox "
            "(event_id, tipo, versao, tenant_id, agregado_tipo, agregado_id, "
            " agregado_seq, particao, envelope) "
            "VALUES (gen_random_uuid(), %s, 1, %s, 'order', %s, 1, %s, %s::jsonb) "
            "RETURNING event_id::text",
            (TIPO, self.tenant, self.agregado_novo(), particao, envelope),
        )
        return str(self.cursor.fetchone()[0])

    def _envelope(self, payload: str) -> str:
        import json

        return json.dumps(
            {
                "id": str(uuid.uuid4()),
                "tipo": TIPO,
                "versao": 1,
                "tenant_id": self.tenant,
                "ocorrido_em": "2026-11-02T14:03:11.482Z",
                "registado_em": "2026-11-02T14:03:11.610Z",
                "produtor": "ensaio@0",
                "agregado": {"tipo": "order", "id": "agg-directo", "seq": 1},
                "correlacao_id": None,
                "causa_id": None,
                "trace_id": None,
                "classe_pii": "P1",
                "finalidades": ["transacao"],
                "payload": json.loads(payload),
            }
        )

    def test_um_envelope_com_telefone_inserido_directamente_nao_vai_a_fila(self) -> None:
        """A guarda de PII do publicador, exercida pelo caminho que a justifica."""
        mau = self._inserir_directo(self._envelope('{"recipient": "+244912345678"}'))
        (boa,) = self.emitir(1)
        self.lancar_publicador()

        self.assertTrue(
            esperar_por(lambda: self.publicados() == 1, 60),
            f"a linha boa nao passou{self.diagnostico()}",
        )
        self.cursor.execute(
            "SELECT publicado_at IS NULL FROM platform.events_outbox WHERE event_id = %s",
            (mau,),
        )
        self.assertTrue(self.cursor.fetchone()[0], "publicou um envelope com telefone")
        self.assertEqual(self.fila.pendentes(self.nome_da_fila(boa)), 1)

    def test_uma_particao_fora_de_0_15_nao_vai_a_fila_nenhuma(self) -> None:
        """Falha fechada, em vez de dobrar por modulo e trocar a ordem.

        A linha boa vai para um agregado que **nao** cai na `p0`, e isso nao e
        detalhe: 16 dobrado por modulo da `p0`, e a asercao final e que a `p0`
        nao existe. Com um agregado ao acaso, uma vez em dezasseis a linha boa
        caia la por direito proprio e o teste ficava vermelho sem nada estar
        errado — a terceira vez que esta suite paga a mesma classe de defeito
        (as duas primeiras estao na ANALISE-20 e no `agregado_fora_da_particao`).
        """
        mau = self._inserir_directo(self._envelope('{"order_id": "x"}'), particao=16)
        (boa,) = self.emitir(1, agregado=self.agregado_fora_da_particao(0))
        self.lancar_publicador()

        self.assertTrue(
            esperar_por(lambda: self.publicados() == 1, 60),
            f"a linha boa nao passou{self.diagnostico()}",
        )
        self.cursor.execute(
            "SELECT publicado_at IS NULL FROM platform.events_outbox WHERE event_id = %s",
            (mau,),
        )
        self.assertTrue(self.cursor.fetchone()[0], "publicou uma particao invalida")
        self.assertNotEqual(
            self.particao_de(boa), 0, "o auxiliar devolveu um agregado da p0"
        )
        self.assertNotIn(
            f"evt.{CONSUMER}.p0", self.fila.filas(), "dobrou a particao por modulo"
        )

    def test_uma_subscricao_inactiva_nao_recebe(self) -> None:
        self.cursor.execute("DELETE FROM platform.evt_subscricoes")
        self.subscrever(activo=False)
        (identificador,) = self.emitir()
        self.lancar_publicador()
        self.assertTrue(esperar_por(lambda: self.publicados() == 1, 30))
        self.assertEqual(self.fila.jobs(self.nome_da_fila(identificador)), set())


class TestRoteamento(ComFila):
    """Criterio 7: roteamento por finalidade e *fan-out* por 16 filas."""

    def test_quem_subscreve_outro_tipo_nao_recebe(self) -> None:
        """Sem isto, ignorar o `tipo` no roteamento nao tinha efeito nesta suite:
        todas as subscricoes eram do mesmo tipo (ANALISE-20, achado 5)."""
        self.subscrever(CONSUMER, tipo="order.expired")
        (identificador,) = self.emitir()
        self.lancar_publicador()
        self.assertTrue(esperar_por(lambda: self.publicados() == 1, 60))
        self.assertEqual(
            self.fila.filas(),
            set(),
            "um consumidor de `order.expired` recebeu um `order.created`",
        )

    def test_so_quem_tem_a_finalidade_do_envelope_recebe(self) -> None:
        self.subscrever(CONSUMER, finalidade="transacao")
        self.subscrever(CONSUMER_ANALITICO, finalidade="analytics_agregado")
        self.subscrever(CONSUMER, tipo="order.expired", finalidade="transacao")
        (so_transacao,) = self.emitir(finalidades=("transacao",))
        # Os dois eventos em particoes **diferentes**, de proposito: a asercao
        # abaixo e de fila vazia, e com os dois na mesma particao (uma vez em
        # dezasseis, com agregados ao acaso) a fila do consumidor analitico leva
        # o evento das duas finalidades **por direito**. Falhava sem nada estar
        # errado, e foi assim que falhou na primeira execucao em Linux.
        (ambas,) = self.emitir(
            finalidades=("transacao", "analytics_agregado"),
            agregado=self.agregado_fora_da_particao(self.particao_de(so_transacao)),
        )
        self.lancar_publicador()

        self.assertTrue(esperar_por(lambda: self.publicados() == 2, 60))
        self.assertIn(so_transacao, self.fila.jobs(self.nome_da_fila(so_transacao)))
        self.assertEqual(
            self.fila.jobs(self.nome_da_fila(so_transacao, CONSUMER_ANALITICO)),
            set(),
            "um consumidor de `analytics_agregado` recebeu um evento so de `transacao`",
        )
        self.assertIn(ambas, self.fila.jobs(self.nome_da_fila(ambas)))
        self.assertIn(
            ambas, self.fila.jobs(self.nome_da_fila(ambas, CONSUMER_ANALITICO))
        )

    def test_a_fan_out_usa_as_dezasseis_filas_do_consumidor(self) -> None:
        """Nao e «usa mais do que uma»: com 160 agregados, usa-as todas.

        Se o `& 15` estivesse errado — um `% 8`, um `& 7` — faltavam filas, e a
        falta nao se ve com dois ou tres eventos.
        """
        self.subscrever()
        identificadores = self.emitir(160)
        self.lancar_publicador()
        self.assertTrue(esperar_por(lambda: self.publicados() == 160, 120))

        esperadas = {self.nome_da_fila(i) for i in identificadores}
        self.assertEqual(
            len(esperadas), 16, f"os 160 agregados cairam em {len(esperadas)} filas"
        )
        self.assertTrue(
            esperar_por(lambda: esperadas <= self.fila.filas(), 60),
            f"filas na fila: {sorted(self.fila.filas())}",
        )
        for nome in sorted(esperadas):
            with self.subTest(fila=nome):
                self.assertTrue(self.fila.jobs(nome))

    def test_o_mesmo_agregado_vai_sempre_a_mesma_fila(self) -> None:
        """A ordem vale dentro da particao: dois eventos do mesmo agregado
        em filas diferentes eram perda de ordem, silenciosa."""
        self.subscrever()
        agregado = self.agregado_novo()
        identificadores = self.emitir(5, agregado=agregado)
        nomes = {self.nome_da_fila(i) for i in identificadores}
        self.assertEqual(len(nomes), 1, nomes)
        self.lancar_publicador()
        nome = nomes.pop()
        self.assertTrue(
            esperar_por(lambda: self.fila.pendentes(nome) == 5, 60),
            f"a fila {nome} tem {self.fila.espera(nome)}{self.diagnostico()}",
        )
        # **A ordem de entrega, e nao o conjunto.** O `seq` e a ordem causal, a
        # particao garante que os cinco vao para a mesma fila, e a concorrencia 1
        # por fila faz o consumidor ve-los por esta ordem. Comparar conjuntos
        # deixava passar uma inversao — e deixava sobreviver a mutacao que troca
        # o `ORDER BY id` por `ORDER BY id DESC` (ANALISE-20, achado 4).
        self.assertEqual(
            self.fila.espera(nome),
            identificadores,
            "a ordem de entrega nao e a ordem de `seq` do agregado",
        )


class TestKill9(ComFila):
    """Criterio 3: `kill -9` entre o `add` e o `COMMIT`."""

    def setUp(self) -> None:
        super().setUp()
        self.subscrever()

    def test_depois_do_kill_o_evento_republica_se_e_fica_um_job(self) -> None:
        (identificador,) = self.emitir()
        nome = self.nome_da_fila(identificador)

        parado = self.lancar_publicador("parado", KAMBA_PUB_PARAR_APOS_ADD="1")
        # Espera que o `add` ja tenha acontecido: o *job* esta na fila e a linha
        # continua sem `publicado_at`. E a janela exacta do criterio.
        self.assertTrue(
            esperar_por(lambda: self.fila.jobs(nome) == {identificador}, 60),
            f"o publicador nao chegou a por o job na fila{self.diagnostico()}",
        )
        self.assertEqual(self.pendentes(), 1, "ja tinha confirmado: a janela passou")

        parado.matar()
        self.assertFalse(parado.vivo())
        # O `lock` consultivo e de sessao: morre com a ligacao, e e isso que faz
        # o segundo publicador conseguir ser lider. Nao se afirma aqui que a
        # linha «sobreviveu»: isso ja foi afirmado acima e nada entretanto
        # publicou — era uma asercao que nao podia falhar (ANALISE-20, achado
        # 12). O que prova o lock largado e o ciclo do segundo publicador,
        # abaixo.

        self.lancar_publicador("b")
        self.assertTrue(
            esperar_por(lambda: self.pendentes() == 0, 60),
            f"o evento nao foi republicado depois do reinicio{self.diagnostico()}",
        )
        self.assertEqual(
            self.fila.pendentes(nome),
            1,
            "republicar deixou mais do que um job por (consumer, event_id): "
            f"{self.fila.espera(nome)}{self.diagnostico()}",
        )
        self.assertEqual(self.fila.espera(nome), [identificador])
        self.assertEqual(self.arquivados(), 1)

    def test_a_republicacao_nao_duplica_com_dois_consumidores(self) -> None:
        self.subscrever(CONSUMER_ANALITICO)
        (identificador,) = self.emitir()
        nomes = [
            self.nome_da_fila(identificador),
            self.nome_da_fila(identificador, CONSUMER_ANALITICO),
        ]
        parado = self.lancar_publicador("parado", KAMBA_PUB_PARAR_APOS_ADD="1")
        self.assertTrue(esperar_por(lambda: bool(self.fila.jobs(nomes[0])), 60))
        parado.matar()

        self.lancar_publicador("b")
        self.assertTrue(esperar_por(lambda: self.pendentes() == 0, 60))
        for nome in nomes:
            with self.subTest(fila=nome):
                self.assertEqual(self.fila.pendentes(nome), 1, self.fila.espera(nome))
                self.assertEqual(self.fila.espera(nome), [identificador])

    def test_o_arquivo_nao_duplica_na_republicacao(self) -> None:
        """`ON CONFLICT DO NOTHING`: o arquivo e imutavel e nao cresce duas vezes."""
        (identificador,) = self.emitir()
        parado = self.lancar_publicador("parado", KAMBA_PUB_PARAR_APOS_ADD="1")
        self.assertTrue(
            esperar_por(
                lambda: bool(self.fila.jobs(self.nome_da_fila(identificador))), 60
            )
        )
        parado.matar()
        self.lancar_publicador("b")
        self.assertTrue(esperar_por(lambda: self.pendentes() == 0, 60))
        self.assertEqual(self.arquivados(), 1)


class TestFilaParada(ComFila):
    """Criterio 4: fila parada 60 s com 1 000 eventos emitidos."""

    def setUp(self) -> None:
        super().setUp()
        self.subscrever()
        self.contentor = node.os.environ.get("KAMBA_GATE_FILA", "")
        if not self.contentor:
            raise AssertionError("KAMBA_GATE_FILA nao esta definida")

    def _docker(self, *argumentos: str) -> None:
        import subprocess

        resultado = subprocess.run(
            ["docker", *argumentos, self.contentor], capture_output=True, text=True
        )
        if resultado.returncode != 0:
            raise AssertionError(
                f"docker {argumentos[0]} {self.contentor}: {resultado.stderr[-300:]}"
            )

    def test_mil_eventos_com_a_fila_parada_recuperam_sem_perder_nenhum(self) -> None:
        identificadores = self.emitir(EVENTOS_DO_CRITERIO_4)
        self.assertEqual(self.pendentes(), EVENTOS_DO_CRITERIO_4)

        self._docker("stop", "--timeout", "0")
        self.addCleanup(lambda: self._docker("start"))
        publicador = self.lancar_publicador()

        # Com a fila em baixo, nenhuma linha fica publicada e o recuo avanca.
        time.sleep(PARAGEM_DO_CRITERIO_4)
        self.assertEqual(
            self.publicados(), 0, "publicou alguma coisa com a fila parada"
        )
        tentativas, no_futuro = self.recuo_de(identificadores[0])
        self.assertGreater(
            tentativas, 0, f"`tentativas` nao recuou{self.diagnostico()}"
        )
        self.assertTrue(no_futuro, "`proxima_tentativa_at` nao foi adiada")

        self._docker("start")
        self.assertTrue(self.fila.esperar_viva(60), "a fila nao voltou")

        inicio = time.monotonic()
        recuperou = esperar_por(
            lambda: self.pendentes() == 0, RECUPERACAO_DO_CRITERIO_4, intervalo=0.5
        )
        demorou = time.monotonic() - inicio
        self.assertTrue(
            recuperou,
            f"ficaram {self.pendentes()} por publicar depois de "
            f"{RECUPERACAO_DO_CRITERIO_4}s (demorou {demorou:.1f}s)"
            f"{self.diagnostico()}",
        )
        self.assertEqual(
            self.publicados(), EVENTOS_DO_CRITERIO_4, "perdeu-se algum evento"
        )
        self.assertEqual(self.arquivados(), EVENTOS_DO_CRITERIO_4)
        publicador.parar()

        # 0 perdidos tambem **na fila**: cada evento tem o seu *job*.
        na_fila = set()
        for nome in self.fila.filas():
            na_fila |= self.fila.jobs(nome)
        self.assertEqual(
            na_fila,
            set(identificadores),
            f"na fila ha {len(na_fila)} jobs para {EVENTOS_DO_CRITERIO_4} eventos",
        )


class TestLideranca(ComFila):
    """Criterio 5: duas instancias em simultaneo, so uma publica."""

    def setUp(self) -> None:
        super().setUp()
        self.subscrever()

    def test_so_um_publica_e_o_outro_assume_quando_a_lider_morre(self) -> None:
        primeiro = self.lancar_publicador("a")
        self.assertTrue(
            self.esperar_lider(primeiro, 60),
            f"o primeiro nao ficou lider{self.diagnostico()}",
        )

        segundo = self.lancar_publicador("b")
        # Enquanto o primeiro vive, o segundo nunca se diz lider.
        self.assertFalse(
            self.esperar_lider(segundo, 5),
            f"houve dois lideres ao mesmo tempo{self.diagnostico()}",
        )

        # Com so um lider, um evento publica-se uma vez e nao duas.
        (identificador,) = self.emitir()
        nome = self.nome_da_fila(identificador)
        self.assertTrue(esperar_por(lambda: self.pendentes() == 0, 60))
        self.assertEqual(
            self.fila.pendentes(nome), 1, f"dois lideres publicaram: {self.fila.espera(nome)}"
        )

        primeiro.matar()
        inicio = time.monotonic()
        assumiu = self.esperar_lider(segundo, ASSUNCAO_DO_CRITERIO_5)
        demorou = time.monotonic() - inicio
        self.assertTrue(
            assumiu,
            f"o segundo nao assumiu em {ASSUNCAO_DO_CRITERIO_5}s "
            f"(esperou {demorou:.1f}s)",
        )

        # E publica: assumir sem publicar nao e assumir.
        #
        # Noutra particao, de proposito: as duas asercoes abaixo sao sobre a
        # fila de `outro`, e com os dois eventos na mesma particao (uma vez em
        # dezasseis, com agregados ao acaso) a fila leva **os dois** — o
        # primeiro por direito. `pendentes` dava 2 e `espera` dava uma lista de
        # dois, sem nada estar errado. E a mesma causa que o
        # `test_so_quem_tem_a_finalidade_do_envelope_recebe` ja tinha corrigido,
        # neste teste irmao que nao foi varrido na altura.
        (outro,) = self.emitir(
            agregado=self.agregado_fora_da_particao(self.particao_de(identificador)))
        self.assertTrue(esperar_por(lambda: self.pendentes() == 0, 60))
        self.assertEqual(self.fila.pendentes(self.nome_da_fila(outro)), 1)
        self.assertEqual(self.fila.espera(self.nome_da_fila(outro)), [outro])

    def test_a_paragem_limpa_larga_a_lideranca(self) -> None:
        primeiro = self.lancar_publicador("a")
        self.assertTrue(self.esperar_lider(primeiro, 60))
        segundo = self.lancar_publicador("b")
        self.assertFalse(self.esperar_lider(segundo, 5))
        primeiro.parar()
        self.assertTrue(
            self.esperar_lider(segundo, ASSUNCAO_DO_CRITERIO_5),
            "um `SIGTERM` nao largou o lock consultivo",
        )


if __name__ == "__main__":
    unittest.main()
