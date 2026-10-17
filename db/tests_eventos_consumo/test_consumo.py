"""Os criterios do KAM-006 contra PostgreSQL e fila reais.

O que se prova aqui, e **so** aqui, porque nenhuma base falsa o diz:

    criterio 1   a re-entrega do mesmo evento da um efeito e uma linha
    criterio 2   seis tentativas (1 + 5) e depois uma entrada na DLQ
    criterio 3   uma pre-condicao que nunca se verifica nunca aplica a transicao
    criterio 4   um evento atrasado numa transicao invalida vai directo a DLQ
    criterio 7   a base recusa uma subscricao de `payment.*` sem ordem
    criterio 8   o que o Redis perdeu volta a fila, e so o que se perdeu

O que **nao** se prova aqui, e onde: a logica de decisao esta em
`packages/core-ts/tests/eventos.consumo.test.ts` e em
`libs/py-core/tests/test_eventos_consumo.py` (sem fila, com base falsa); os
dois aprovadores do descarte estao em `db/tests/test_dlq.py`; a recusa de
arranque esta em `services/worker-canal/tests/consumidor.test.ts`; o isolamento
das tres tabelas esta na suite do gate 6 (`db/tests_isolamento/`). Um laco que
passa com uma base falsa nao prova transaccoes, e e por isso que estes testes
existem; um teste que repita o que a base falsa ja prova so gasta o gate.

**O relogio e acelerado.** Ver a docstring do `base.py`: a escada e cinco
degraus de 300 ms em vez de 1 s, 5 s, 30 s, 2 min, 10 min, e a carencia da
reposicao e zero em vez de dez minutos. Os valores reais tem prova propria; o
que esta suite mede e a contagem de tentativas e o caminho, que e o que so uma
fila real diz.
"""

from __future__ import annotations

import json
import unittest
import uuid

from tests_eventos_consumo.base import (
    CONSUMER,
    ESPERA,
    ESPERA_DA_DLQ,
    ComConsumidor,
    esperar_por,
)


class TestDuplicado(ComConsumidor):
    """Criterio 1: reentregar o mesmo evento duas vezes da um efeito."""

    def test_a_re_entrega_do_mesmo_evento_da_um_efeito_e_uma_linha(self) -> None:
        self.subscrever()
        (identificador,) = self.publicar()

        consumidor = self.lancar_consumidor("a", KAMBA_CON_EFEITO="conta")
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: self.consumidos() == 1, ESPERA),
            f"o evento nao foi consumido{self.diagnostico()}",
        )
        self.assertEqual(self.efeitos(), 1)
        self.assertEqual(self.desfechos(consumidor), ["aplicado"])

        # A segunda entrega, pelo caminho real: a fila esquece o *job* e o
        # outbox volta a ter a linha por publicar. Sem o esquecimento, o `add`
        # do BullMQ e idempotente por `jobId` e a republicacao nao entregava
        # nada — um teste de re-entrega que nao re-entrega passava sem provar
        # nada.
        self.esquecer_na_fila(identificador)
        self.republicar(identificador)
        segundo = self.lancar_publicador("p2")
        self.assertTrue(
            esperar_por(lambda: self.pendentes() == 0, ESPERA),
            f"o publicador nao republicou{self.diagnostico()}",
        )
        segundo.parar()

        self.assertTrue(
            esperar_por(lambda: len(self.desfechos(consumidor)) == 2, ESPERA),
            f"a segunda entrega nao chegou ao consumidor{self.diagnostico()}",
        )
        self.assertEqual(self.desfechos(consumidor), ["aplicado", "duplicado"])
        self.assertEqual(self.consumidos(), 1, "duas linhas de deduplicacao")
        self.assertEqual(self.efeitos(), 1, "o efeito repetiu-se")


class TestFalhaPermanente(ComConsumidor):
    """Criterio 2: seis tentativas, depois DLQ."""

    def test_um_handler_que_falha_sempre_abre_uma_entrada_com_seis_tentativas(self) -> None:
        self.subscrever()
        (identificador,) = self.publicar()

        consumidor = self.lancar_consumidor("a", KAMBA_CON_EFEITO="falha")
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: len(self.na_dlq()) == 1, ESPERA_DA_DLQ),
            f"nao abriu entrada na DLQ{self.diagnostico()}",
        )
        (entrada,) = self.na_dlq()
        self.assertEqual(entrada["event_id"], identificador)
        self.assertEqual(entrada["estado"], "aberta")
        self.assertEqual(entrada["tentativas"], 6, "nao foram 1 + 5")
        self.assertIn("falha sempre", entrada["erro"])
        # «envelope P0/P1», do criterio: o que fica guardado e o envelope
        # inteiro, e a sua classe de PII e a que o produtor declarou. Um P2 aqui
        # era conteudo sensivel a ficar numa tabela de operacao.
        self.assertEqual(entrada["versao"], 1)
        self.assertIn(entrada["envelope"]["classe_pii"], ("P0", "P1"))
        self.assertEqual(entrada["envelope"]["id"], identificador)
        # Uma falha tecnica nao e um desfecho: o `processar()` relanca-a para a
        # fila contar. So a ultima tentativa escreve, e escreve `dlq`.
        self.assertEqual(self.desfechos(consumidor), ["dlq"])
        self.assertEqual(self.efeitos(), 0)

    def test_um_evento_que_falha_nao_deixa_marca_de_consumo(self) -> None:
        """A transaccao e uma: se o efeito falha, a marca desaparece com ele.

        E a outra metade do criterio 1. Sem isto, um evento que falhasse ficava
        marcado como consumido e nenhuma re-entrega o voltava a tentar — o
        efeito perdia-se para sempre, que e o modo de falha pior dos dois.
        """
        self.subscrever()
        self.publicar()
        consumidor = self.lancar_consumidor("a", KAMBA_CON_EFEITO="falha")
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: len(self.na_dlq()) == 1, ESPERA_DA_DLQ),
            f"nao abriu entrada na DLQ{self.diagnostico()}",
        )
        self.assertEqual(
            self.consumidos(), 0, "ficou marcado como consumido sem o efeito ter corrido"
        )


class TestOrdem(ComConsumidor):
    """Criterios 3 e 4: a pre-condicao e a transicao invalida."""

    def test_uma_pre_condicao_que_nunca_se_verifica_adia_cinco_vezes_e_vai_a_dlq(self) -> None:
        self.subscrever(tipo="payment.confirmed")
        (identificador,) = self.publicar(tipo="payment.confirmed")

        # A encomenda esta em `criada`: `criada -> paga` nao e transicao valida,
        # e o `seq` nao vem atrasado — logo adia-se, e so na sexta vai a DLQ.
        consumidor = self.lancar_consumidor(
            "a", KAMBA_CON_EFEITO="conta", KAMBA_CON_ESTADO="criada"
        )
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: len(self.na_dlq()) == 1, ESPERA_DA_DLQ),
            f"nao abriu entrada na DLQ{self.diagnostico()}",
        )
        (entrada,) = self.na_dlq()
        self.assertEqual(entrada["tipo"], "payment.confirmed")
        self.assertEqual(entrada["event_id"], identificador)
        self.assertEqual(entrada["tentativas"], 6)
        self.assertIn("adiado_sem_resolver", entrada["erro"])
        self.assertIn("criada -> paga", entrada["erro"])
        # Cinco adiamentos e uma entrada: e o «1 + 5» do criterio 2 visto do
        # outro lado, e a prova de que nenhuma das seis aplicou a transicao.
        self.assertEqual(
            self.desfechos(consumidor), ["adiado"] * 5 + ["dlq"], self.diagnostico()
        )
        self.assertEqual(
            self.efeitos(), 0, "aplicou a transicao invalida — e o que nao pode acontecer"
        )
        self.assertEqual(self.consumidos(), 0, "marcou consumido sem aplicar nada")

    def test_o_agregado_que_ainda_nao_existe_adia_e_nao_aplica(self) -> None:
        """`null` nunca e «pode»: um agregado que nao existe e cedo, nao invalido."""
        self.subscrever(tipo="payment.confirmed")
        self.publicar(tipo="payment.confirmed")

        consumidor = self.lancar_consumidor(
            "a", KAMBA_CON_EFEITO="conta", KAMBA_CON_ESTADO="nenhum"
        )
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: len(self.na_dlq()) == 1, ESPERA_DA_DLQ),
            f"nao abriu entrada na DLQ{self.diagnostico()}",
        )
        (entrada,) = self.na_dlq()
        self.assertIn("ainda nao existe", entrada["erro"].replace("ã", "a"))
        self.assertEqual(self.desfechos(consumidor), ["adiado"] * 5 + ["dlq"])
        self.assertEqual(self.efeitos(), 0)

    def test_um_evento_atrasado_numa_transicao_invalida_vai_directo_a_dlq(self) -> None:
        """Criterio 4: `fora_de_ordem`, numa tentativa so.

        Nao ha tentativa que resolva um evento que vem atrasado numa transicao
        invalida: o atraso nao se desfaz. Por isso nao recua pela escada — abre
        a entrada a primeira, com o codigo que o criterio nomeia.

        Como se produz o atraso: dois eventos do **mesmo** agregado (`seq` 1 e
        2) e a linha de consumo do segundo escrita a mao. Quando o primeiro
        chega, o ultimo `seq` consumido ja e 2 e o dele e 1.
        """
        agregado = self.agregado_novo()
        self.subscrever(tipo="payment.confirmed")
        primeiro, segundo = self.emitir(2, agregado=agregado, tipo="payment.confirmed")
        self.cursor.execute(
            "INSERT INTO platform.events_consumed "
            "(consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq) "
            "VALUES (%s, %s, %s, 'order', %s, 2)",
            (CONSUMER, segundo, self.tenant, agregado),
        )
        publicador = self.lancar_publicador("p")
        self.assertTrue(
            esperar_por(lambda: self.pendentes() == 0, ESPERA),
            f"o publicador nao publicou{self.diagnostico()}",
        )
        publicador.parar()

        consumidor = self.lancar_consumidor(
            "a", KAMBA_CON_EFEITO="conta", KAMBA_CON_ESTADO="criada"
        )
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: len(self.na_dlq()) == 1, ESPERA_DA_DLQ),
            f"nao abriu entrada na DLQ{self.diagnostico()}",
        )
        (entrada,) = self.na_dlq()
        self.assertEqual(entrada["event_id"], primeiro)
        self.assertEqual(entrada["erro"], "fora_de_ordem")
        self.assertEqual(
            entrada["tentativas"], 1, "recuou pela escada em vez de ir directo"
        )
        self.assertEqual(self.desfechos(consumidor, primeiro), ["dlq"])
        self.assertEqual(self.efeitos(), 0)


class TestEnvelopeIlegivel(ComConsumidor):
    """O que acontece quando o arquivo nao responde pelo evento.

    A leitura do envelope corre **antes** da politica, e por isso fora dela. Um
    erro ali, deixado a subir, esgotava as seis tentativas e deixava o *job* em
    `failed` no Redis — sem linha na DLQ, sem metrica e sem alerta —, e como
    nao ha `events_consumed` nem `events_dlq` o reconciliador voltava a
    enfileira-lo de cinco em cinco minutos durante 24 h. Um ciclo silencioso.
    """

    def test_um_evento_que_o_arquivo_nao_tem_acaba_na_dlq(self) -> None:
        self.subscrever()
        (identificador,) = self.publicar()
        # O arquivo perde a linha. Na pratica isto acontece ao contrario — o
        # *job* chega antes do `COMMIT` que arquiva —, e o efeito e o mesmo:
        # a leitura devolve zero linhas.
        self.cursor.execute(
            "DELETE FROM platform.events_log WHERE event_id = %s", (identificador,)
        )

        consumidor = self.lancar_consumidor("a", KAMBA_CON_EFEITO="conta")
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: len(self.na_dlq()) == 1, ESPERA_DA_DLQ),
            f"o evento ilegivel nao deixou entrada na DLQ{self.diagnostico()}",
        )
        (entrada,) = self.na_dlq()
        self.assertEqual(entrada["event_id"], identificador)
        self.assertEqual(entrada["tipo"], "evt.ilegivel")
        self.assertEqual(entrada["versao"], 0)
        self.assertEqual(entrada["tentativas"], 6)
        self.assertIn("events_log", entrada["erro"])
        # O que fica no lugar do envelope **diz** que nao e um envelope: sem
        # isso, alguem le a entrada e tenta reprocessa-la como se fosse um
        # evento. Guarda o `event_id` e o motivo, e mais nada.
        substituto = entrada["envelope"]
        self.assertEqual(substituto["id"], identificador)
        self.assertIn("aviso", substituto)
        self.assertNotIn("payload", substituto)
        self.assertEqual(self.consumidos(), 0)
        self.assertEqual(self.efeitos(), 0)

    def test_o_que_esta_na_dlq_por_ilegivel_nao_e_reposto(self) -> None:
        """E a razao de ser do teste acima: fechar o ciclo da reposicao."""
        self.subscrever()
        (identificador,) = self.publicar()
        self.cursor.execute(
            "DELETE FROM platform.events_log WHERE event_id = %s", (identificador,)
        )
        consumidor = self.lancar_consumidor("a")
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: len(self.na_dlq()) == 1, ESPERA_DA_DLQ),
            f"o evento ilegivel nao deixou entrada na DLQ{self.diagnostico()}",
        )
        # Sem a linha no arquivo a consulta do §6.5 nem o encontra; com ela, e
        # a entrada na DLQ que o tira dos candidatos. As duas redes.
        reposicao = self.repor_uma_vez()
        self.assertTrue(self.esperar_fim(reposicao), self.diagnostico())
        passagens = [
            linha for linha in reposicao.linhas() if linha.get("evento") == "passagem"
        ]
        self.assertEqual([p.get("encontradas") for p in passagens], [0])


class TestReposicao(ComConsumidor):
    """Criterio 8: o que o Redis perdeu volta a fila."""

    def test_depois_de_limpar_a_fila_o_evento_volta_a_ser_enfileirado(self) -> None:
        self.subscrever()
        (identificador,) = self.publicar()
        fila = self.nome_da_fila(identificador)
        self.assertEqual(self.fila.pendentes(fila), 1)

        # O Redis perde tudo. A linha do outbox ja esta publicada, pelo que o
        # publicador nao lhe volta a tocar: sem reconciliador, o evento
        # desaparece — e e esse o buraco que o criterio 8 fecha.
        self.fila.limpar()
        self.assertEqual(self.fila.pendentes(fila), 0)

        reposicao = self.repor_uma_vez()
        self.assertTrue(
            esperar_por(lambda: self.fila.pendentes(fila) == 1, ESPERA),
            f"o evento nao voltou a fila{self.diagnostico()}",
        )
        self.assertEqual(
            self.fila.espera(fila), [identificador], "voltou outro, ou mais do que um"
        )
        self.assertTrue(self.esperar_fim(reposicao), self.diagnostico())

    def test_o_evento_reposto_traz_o_tenant_e_e_consumido(self) -> None:
        """Repor sem `tenant_id` era repor para a DLQ.

        O consumidor e `kamba_app`, sujeito a RLS: sem contexto, a leitura do
        arquivo devolve zero linhas e o evento reposto ia para a DLQ como
        «evento desconhecido». Este teste e o que apanha essa regressao —
        verificar so que o *job* voltou a fila nao a apanhava.
        """
        self.subscrever()
        self.publicar()
        self.fila.limpar()
        reposicao = self.repor_uma_vez()
        self.assertTrue(self.esperar_fim(reposicao), self.diagnostico())

        consumidor = self.lancar_consumidor("a", KAMBA_CON_EFEITO="conta")
        self.assertTrue(self.esperar_arranque(consumidor), self.diagnostico())
        self.assertTrue(
            esperar_por(lambda: self.consumidos() == 1, ESPERA),
            f"o evento reposto nao foi consumido{self.diagnostico()}",
        )
        self.assertEqual(self.desfechos(consumidor), ["aplicado"])
        self.assertEqual(self.na_dlq(), [], "o evento reposto foi para a DLQ")
        self.assertEqual(self.efeitos(), 1)

    def test_o_que_ja_foi_consumido_nao_volta(self) -> None:
        """A reposicao le o consumo: repor o que ja produziu efeito era duplicar."""
        self.subscrever()
        (identificador,) = self.publicar()
        self.cursor.execute(
            "INSERT INTO platform.events_consumed "
            "(consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq) "
            "VALUES (%s, %s, %s, 'order', 'agg-consumido', 1)",
            (CONSUMER, identificador, self.tenant),
        )
        self.fila.limpar()

        reposicao = self.repor_uma_vez()
        self.assertTrue(self.esperar_fim(reposicao), self.diagnostico())
        self.assertEqual(
            self.fila.pendentes(self.nome_da_fila(identificador)),
            0,
            "repos um evento que ja tinha sido consumido",
        )

    def test_o_que_esta_na_dlq_nao_volta(self) -> None:
        """Uma entrada na DLQ e um efeito por aplicar **com dono**.

        Repo-lo era entregar outra vez o que ja esta a espera de uma decisao
        humana — e o reprocessamento tem caminho proprio, auditado, na CLI.
        """
        self.subscrever()
        (identificador,) = self.publicar()
        self.cursor.execute(
            "INSERT INTO platform.events_dlq "
            "(consumer, event_id, tipo, versao, tenant_id, envelope, erro, tentativas) "
            "VALUES (%s, %s, 'order.created', 1, %s, %s::jsonb, 'erro', 6)",
            (CONSUMER, identificador, self.tenant, json.dumps({"id": identificador})),
        )
        self.fila.limpar()

        reposicao = self.repor_uma_vez()
        self.assertTrue(self.esperar_fim(reposicao), self.diagnostico())
        self.assertEqual(self.fila.pendentes(self.nome_da_fila(identificador)), 0)

    def test_com_a_carencia_do_documento_o_que_passou_dos_dez_minutos_volta(self) -> None:
        """A carencia tambem tem de deixar passar, e nao so travar.

        Os outros testes desta classe correm com carencia zero, e o seguinte
        prova que a de producao **trava** o que e recente. Sozinhos, os dois
        passavam com o sinal da comparacao trocado ou com o parametro ignorado:
        nada provaria que, com os dez minutos do §6.5, um evento mais velho e
        de facto reposto. E este teste que fecha essa assimetria — e fecha-a
        sem esperar dez minutos, recuando o `registado_em` do arquivo, que e a
        coluna que a consulta le.
        """
        self.subscrever()
        (identificador,) = self.publicar()
        self.cursor.execute(
            "UPDATE platform.events_log SET registado_em = now() - interval '11 minutes' "
            " WHERE event_id = %s",
            (identificador,),
        )
        self.fila.limpar()

        reposicao = self.repor_uma_vez(KAMBA_RECON_CARENCIA="600")
        self.assertTrue(
            esperar_por(
                lambda: self.fila.pendentes(self.nome_da_fila(identificador)) == 1, ESPERA
            ),
            f"nao repos um evento publicado ha onze minutos{self.diagnostico()}",
        )
        self.assertTrue(self.esperar_fim(reposicao), self.diagnostico())

    def test_a_carencia_do_documento_protege_o_que_acabou_de_ser_publicado(self) -> None:
        """Com os dez minutos do §6.5, um evento fresco **nao** se repoe.

        E a prova de que a carencia nao e decoracao — e a justificacao de a
        acelerar nos outros testes: com o valor do documento, um evento
        publicado agora nao e candidato, e a suite nao teria como o observar sem
        esperar dez minutos reais.
        """
        self.subscrever()
        (identificador,) = self.publicar()
        self.fila.limpar()

        reposicao = self.repor_uma_vez(KAMBA_RECON_CARENCIA="600")
        self.assertTrue(self.esperar_fim(reposicao), self.diagnostico())
        self.assertEqual(
            self.fila.pendentes(self.nome_da_fila(identificador)),
            0,
            "repos um evento publicado ha segundos: a carencia nao foi respeitada",
        )
        passagens = [
            linha for linha in reposicao.linhas() if linha.get("evento") == "passagem"
        ]
        self.assertEqual([p.get("encontradas") for p in passagens], [0])


class TestArranque(ComConsumidor):
    """Criterio 7, primeira metade: a base recusa a configuracao errada."""

    def test_a_base_recusa_a_subscricao_de_pagamento_sem_ordem(self) -> None:
        """A verificacao de arranque e a segunda metade, e corre em TypeScript.

        Esta e a restricao da revisao 0005, que faz a configuracao errada ser
        **recusada** em vez de detectada — e continua a valer se alguem nao
        chamar a verificacao.
        """
        import pg8000.dbapi

        with self.assertRaises(pg8000.dbapi.DatabaseError) as apanhado:
            self.subscrever(
                consumer="ensaio-mau", tipo="payment.confirmed", exige_ordem=False
            )
        self.assertIn("evt_subscricoes_payment_exige_ordem", str(apanhado.exception))

    def test_com_ordem_a_mesma_subscricao_entra(self) -> None:
        self.subscrever(consumer="ensaio-bom", tipo="payment.confirmed")
        self.cursor.execute(
            "SELECT exige_ordem FROM platform.evt_subscricoes WHERE consumer = 'ensaio-bom'"
        )
        self.assertEqual(self.cursor.fetchone()[0], True)

    def test_um_tipo_que_nao_e_pagamento_entra_sem_ordem(self) -> None:
        """A restricao e sobre `payment.%` e mais nada: o resto fica como estava."""
        self.subscrever(consumer="ensaio-sem", tipo="order.created", exige_ordem=False)
        self.cursor.execute(
            "SELECT exige_ordem FROM platform.evt_subscricoes WHERE consumer = 'ensaio-sem'"
        )
        self.assertEqual(self.cursor.fetchone()[0], False)


class TestRetencao(ComConsumidor):
    """As duas funcoes de retencao, que o agendador vai chamar (KAM-071/080)."""

    def test_a_janela_de_deduplicacao_apaga_o_que_passou_de_90_dias(self) -> None:
        self.cursor.execute(
            "INSERT INTO platform.events_consumed "
            "(consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq, "
            " processado_at) VALUES (%s, %s, %s, 'order', 'agg-velho', 1, "
            " now() - interval '91 days')",
            (CONSUMER, str(uuid.uuid4()), self.tenant),
        )
        self.cursor.execute(
            "INSERT INTO platform.events_consumed "
            "(consumer, event_id, tenant_id, agregado_tipo, agregado_id, agregado_seq) "
            "VALUES (%s, %s, %s, 'order', 'agg-novo', 2)",
            (CONSUMER, str(uuid.uuid4()), self.tenant),
        )
        self.cursor.execute("SELECT platform.evt_limpar_consumidos()")
        self.assertEqual(self.cursor.fetchone()[0], 1)
        self.assertEqual(self.consumidos(), 1, "apagou a linha nova, ou nao apagou a velha")

    def test_a_retencao_recusa_uma_janela_menor_do_que_a_re_entrega_da_meta(self) -> None:
        """Sete dias e o minimo: abaixo disso um evento re-entregue repete o efeito."""
        import pg8000.dbapi

        with self.assertRaises(pg8000.dbapi.DatabaseError) as apanhado:
            self.cursor.execute("SELECT platform.evt_limpar_consumidos(3)")
        self.assertIn("Meta", str(apanhado.exception))

    def test_a_dlq_so_apaga_o_que_foi_resolvido(self) -> None:
        for estado, resolvido, quem in (
            ("aberta", "NULL", None),
            ("descartada", "now() - interval '31 days'", "alguem"),
        ):
            self.cursor.execute(
                "INSERT INTO platform.events_dlq "
                "(consumer, event_id, tipo, versao, tenant_id, envelope, erro, tentativas, "
                " estado, resolvido_at, resolvido_por) "
                f"VALUES (%s, %s, 'order.created', 1, %s, %s::jsonb, 'erro', 6, %s, "
                f"{resolvido}, %s)",
                (
                    CONSUMER,
                    str(uuid.uuid4()),
                    self.tenant,
                    json.dumps({"id": str(uuid.uuid4())}),
                    estado,
                    quem,
                ),
            )
        self.cursor.execute("SELECT platform.evt_limpar_dlq()")
        self.assertEqual(self.cursor.fetchone()[0], 1)
        restantes = self.na_dlq()
        self.assertEqual(len(restantes), 1)
        self.assertEqual(
            restantes[0]["estado"], "aberta", "apagou a aberta, que e um efeito por aplicar"
        )


if __name__ == "__main__":
    unittest.main()
