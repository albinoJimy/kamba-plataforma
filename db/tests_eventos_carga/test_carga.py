"""Criterio 8 do KAM-005: 50 eventos/s durante 5 min, com medicao do atraso.

Suite propria, e a razao e custo. Sao **cinco minutos** de carga — o numero e do
criterio, nao folga — e uma suite custa isso **por cada mutacao** que a escolha
(`db/mutacoes.py`). Com a medicao de carga dentro de `tests_eventos`, cada
mutacao do publicador passava a custar oito minutos, e a prova por mutacao
nocturna (KAM-143) nao se paga assim. Separada, as mutacoes do publicador correm
contra `tests_eventos` em tres minutos e esta corre uma vez, no gate 8.

Nao e uma suite «opcional»: `make ci-8` corre-a, e um p95 acima do limiar falha
o build como qualquer outra.
"""

from __future__ import annotations

import time
import unittest

from tests_eventos.base import ComFila, esperar_por

#: Os nomes das metricas, como `packages/core-ts/src/eventos/metricas.ts` os
#: escreve. Repetidos aqui de proposito: se mudarem num lado e nao no outro, e
#: este teste que o diz — e o criterio 8 nomeia-os.
METRICA_ATRASO = "evt_outbox_lag_seconds"
METRICA_PUBLICADOS = "evt_publish_total"
METRICA_ERROS = "evt_publish_errors_total"

#: «50 eventos/s durante 5 min» e «p95 <= 1 s (proposta, a calibrar)».
TAXA = 50
DURACAO = 300

#: O limiar **do criterio**, que e *proposta*. Nao e o que este teste faz
#: falhar: ver `TECTO_DE_REGRESSAO`.
P95_DO_CRITERIO = 1.0

#: O que faz o gate falhar, e porque nao e o limiar do criterio.
#:
#: Medido nesta maquina (Windows, Docker Desktop, PostgreSQL e Valkey em
#: contentores e o publicador num terceiro), **duas vezes**:
#:
#:   maquina livre                  p95 = 6,0 s    max = 20,8 s
#:   com outra suite de BD a correr p95 = 15,0 s   max = 29,5 s
#:
#: nas duas com os 15 000 eventos publicados, os 15 000 arquivados, zero
#: perdidos e zero recuos. O atraso nao vem de lentidao: vem do **periodo do
#: lote**. A 50/s um lote de 200 (o valor do §6.2) enche-se a cada 4 s, e quando
#: o publicador corre a capacidade o atraso de um evento e esse periodo. Baixar
#: o lote baixa o atraso — e e calibracao, que nao se faz aqui.
#:
#: Logo: a caixa do criterio 8 fica **vazia** no bloco do ticket, com os numeros
#: escritos. E o tecto deste teste e de **sessenta** segundos, nao de trinta: a
#: segunda medicao chegou aos 29,5 s de maximo so por haver outra suite na
#: maquina, e um tecto que falha por carga do *runner* e um gate que mente —
#: conta como mutacao apanhada quando nao apanhou nada (a regra das `PROVA
#: INVALIDA` de `db/mutacoes.py`).
#:
#: O que o tecto apanha e o publicador que **deixou de acompanhar**: a bloquear,
#: a recuar em ciclo, a perder a lideranca. Note-se que isso ja e apanhado antes,
#: pela espera de `pendentes() == 0`; o tecto e a segunda rede, e e por isso que
#: pode ser generoso sem deixar de servir.
TECTO_DE_REGRESSAO = 60.0


class TestCarga(ComFila):
    """Criterio 8: 50 eventos/s durante 5 min, com medicao do atraso."""

    def setUp(self) -> None:
        super().setUp()
        self.subscrever()

    def test_cinquenta_por_segundo_durante_cinco_minutos(self) -> None:
        """O criterio, a letra: a taxa e a duracao sao as do bloco.

        O atraso mede-se na base — `publicado_at - criado_at` — e nao com um
        cronometro do lado do teste: e o atraso **outbox -> fila** que o
        criterio nomeia, e a base e quem tem os dois instantes. O limiar de
        1 s e *proposta* e esta por calibrar; o que aqui se fixa e a medicao.
        """
        publicador = self.lancar_publicador()
        total = TAXA * DURACAO
        intervalo = 1.0 / TAXA
        inicio = time.monotonic()
        emitidos = 0
        while emitidos < total:
            alvo = inicio + emitidos * intervalo
            atraso = alvo - time.monotonic()
            if atraso > 0:
                time.sleep(atraso)
            self.emitir(1)
            emitidos += 1
        decorrido = time.monotonic() - inicio

        # A taxa efectiva tem de estar perto da pedida: se a maquina nao
        # conseguir emitir 50/s, o que se mediu nao foi 50/s e di-lo.
        taxa = emitidos / decorrido
        self.assertGreater(
            taxa,
            TAXA * 0.9,
            f"a medicao correu a {taxa:.1f} eventos/s, nao a {TAXA}",
        )

        self.assertTrue(
            esperar_por(lambda: self.pendentes() == 0, 120, intervalo=0.5),
            f"ficaram {self.pendentes()} por publicar",
        )
        publicador.parar()

        self.cursor.execute(
            "SELECT count(*), "
            "       percentile_disc(0.95) WITHIN GROUP ("
            "           ORDER BY extract(epoch FROM (publicado_at - criado_at))), "
            "       max(extract(epoch FROM (publicado_at - criado_at))) "
            "  FROM platform.events_outbox WHERE publicado_at IS NOT NULL"
        )
        quantos, p95, maximo = self.cursor.fetchone()
        self.assertEqual(int(quantos), total, "perdeu-se algum evento")

        # **As metricas confrontadas com a base**, e nao so medidas. O criterio
        # 8 pede o p95 **e** as metricas expostas, e a revisao adversarial
        # (ANALISE-20, achado 7) notou que nenhum teste as confrontava com a
        # realidade: o unico que havia verificava que o *gauge* continha o
        # numero que uma base **falsa** devolveu. O publicador imprime-as ao
        # terminar; comparam-se com o que a base diz.
        metricas = {}
        for registo in publicador.linhas():
            if registo.get("evento") == "terminou":
                metricas = registo.get("metricas") or {}
        self.assertTrue(metricas, f"o publicador nao imprimiu metricas{self.diagnostico()}")
        self.assertEqual(
            metricas.get(f"{METRICA_PUBLICADOS}:entregue"),
            total,
            "evt_publish_total nao bate com os eventos publicados na base",
        )
        self.assertEqual(
            metricas.get(f"{METRICA_ERROS}:fila_indisponivel", 0),
            0,
            "houve erros de fila durante a medicao: o p95 nao e de um caminho limpo",
        )
        # O atraso foi medido, e o ultimo valor e 0 porque nao sobrou pendente
        # nenhum — que e a resposta certa, nao «sem dados».
        self.assertIn(METRICA_ATRASO, metricas)
        self.assertEqual(metricas[METRICA_ATRASO], 0)
        print(
            f"\ncarga: {emitidos} eventos a {taxa:.1f}/s; "
            f"atraso outbox->fila p95={float(p95):.3f}s max={float(maximo):.3f}s; "
            f"limiar do criterio {P95_DO_CRITERIO}s (proposta), "
            f"tecto de regressao {TECTO_DE_REGRESSAO}s"
        )
        self.assertLessEqual(
            float(p95),
            TECTO_DE_REGRESSAO,
            f"p95 do atraso outbox->fila: {float(p95):.3f}s — acima do tecto de "
            "regressao, o que quer dizer que o publicador deixou de acompanhar "
            "(ver a nota de TECTO_DE_REGRESSAO)",
        )


if __name__ == "__main__":
    unittest.main()
