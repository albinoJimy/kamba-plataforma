"""A prova de carga do webhook — KAM-013, criterio 7.

    «Carga de 200 pedidos/s durante 60 s com 3 estados por mensagem (proposta de
    perfil): p99 < 500 ms, mediana <= 250 ms, < 1% acima de 1 s; sob saturacao
    (fila > 10.000 jobs, proposta) sao descartados estados nao facturaveis,
    nunca `messages`.»

Suite propria, e nao dentro de `tests_entrada`, pela mesma razao que a carga de
eventos (KAM-005) e a de auditoria (KAM-012) tem a sua: custa um minuto de
relogio por execucao, e uma suite paga esse custo por cada mutacao que a
escolha.

## O perfil, a letra

«200 pedidos/s com 3 estados por mensagem» le-se como a mistura do trafego, e
nao como 200 mensagens mais 600 estados: o `E1` §5 diz que o servidor tem de
aguentar «3x o trafego de saida (status) + 1x o de entrada», o que da uma parte
de mensagens por tres de estados. Logo, por segundo: **50 corpos de mensagem e
150 corpos de estado**, 200 ao todo, 12 000 em 60 s. O numero esta em
`MENSAGENS_POR_SEGUNDO` e `ESTADOS_POR_SEGUNDO`, e a leitura esta aqui porque e
uma **leitura** e nao um facto — se quem escreveu o criterio quis outra coisa, o
que muda sao estas duas constantes.

## O que se mede, e com que honestidade

Mede-se a latencia **vista pelo cliente**: do primeiro byte enviado ao ultimo
recebido, incluindo a pilha HTTP do Python e o laco de eventos do anfitriao. E
mais pessimista do que a latencia do servidor, e e de proposito: e a que a Meta
veria.

**O que isto nao e:** nao e uma medicao de capacidade da infraestrutura de
producao. Corre num PostgreSQL e numa fila em contentores descartaveis, na
maquina de quem corre o gate, com o cliente no mesmo anfitriao. O
dimensionamento a serio e o KAM-084, que depende deste ticket. O que esta suite
prova e que o **desenho** aguenta o perfil — que o 200 nao espera por I/O que
nao devia estar no caminho — e nao que uma maquina X aguenta Y.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import statistics
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from tests_entrada import node
from tests_entrada.test_entrada import (
    APP_SECRET_ACTUAL,
    APP_SECRET_ANTERIOR,
    ComEntrada,
    PNID,
    TELEFONE,
    VERIFY_TOKEN,
    WABA,
    esperar_por,
)

#: O perfil. Ver a docstring do modulo para a leitura do criterio.
SEGUNDOS = 60
MENSAGENS_POR_SEGUNDO = 50
ESTADOS_POR_SEGUNDO = 150
PEDIDOS_POR_SEGUNDO = MENSAGENS_POR_SEGUNDO + ESTADOS_POR_SEGUNDO

#: Os limiares do criterio 7, em milissegundos.
P99_MAXIMO_MS = 500
MEDIANA_MAXIMA_MS = 250
#: Fraccao maxima de pedidos acima de 1 s.
ACIMA_DE_UM_SEGUNDO_MAXIMO = 0.01

#: Quantas ligacoes em paralelo. Nao e o perfil — e o que permite atingi-lo: a
#: 200 pedidos/s com 10 ms de latencia por pedido, um unico fio da 100/s.
PARALELISMO = 32


def _assinar(corpo: bytes, segredo: str) -> str:
    return "sha256=" + hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()


def _corpo_de_mensagem(indice: int) -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": WABA,
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": TELEFONE,
                                    "phone_number_id": PNID,
                                },
                                "messages": [
                                    {
                                        "from": TELEFONE,
                                        "id": f"wamid.CARGA.M.{indice}",
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": f"pedido de carga {indice}"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _corpo_de_estado(indice: int) -> bytes:
    # Com `pricing`: e o caso que o descarte **nao** pode levar, e e o que
    # torna a asercao «nenhuma mensagem perdida» mais forte do que se os
    # estados fossem todos descartaveis.
    estado = ("sent", "delivered", "read")[indice % 3]
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": WABA,
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": PNID},
                                "statuses": [
                                    {
                                        "id": f"wamid.CARGA.M.{indice // 3}",
                                        "status": estado,
                                        "recipient_id": TELEFONE,
                                        "pricing": {"category": "service"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


class TestCarga(ComEntrada):
    """O perfil do criterio 7 contra o GWY real, com o *worker* a consumir."""

    PROCESSOS = ("gwy", "worker")

    def _um_pedido(self, corpo: bytes) -> tuple[int, float]:
        pedido = urllib.request.Request(
            f"http://127.0.0.1:{self.gwy.porta}/wa/webhook",
            data=corpo,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": _assinar(corpo, APP_SECRET_ACTUAL),
            },
            method="POST",
        )
        inicio = time.perf_counter()
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                resposta.read()
                codigo = resposta.status
        except urllib.error.HTTPError as erro:
            erro.read()
            codigo = erro.code
        except (urllib.error.URLError, OSError, TimeoutError):
            codigo = 0
        return codigo, (time.perf_counter() - inicio) * 1000.0

    def test_o_perfil_do_criterio_7(self) -> None:
        corpos: list[bytes] = []
        for segundo in range(SEGUNDOS):
            base = segundo * PEDIDOS_POR_SEGUNDO
            for i in range(MENSAGENS_POR_SEGUNDO):
                corpos.append(_corpo_de_mensagem(base + i))
            for i in range(ESTADOS_POR_SEGUNDO):
                corpos.append(_corpo_de_estado(base + MENSAGENS_POR_SEGUNDO + i))
        self.assertEqual(len(corpos), SEGUNDOS * PEDIDOS_POR_SEGUNDO)

        latencias: list[float] = []
        codigos: dict[int, int] = {}
        inicio = time.perf_counter()

        with ThreadPoolExecutor(max_workers=PARALELISMO) as executor:
            pendentes = []
            for indice, corpo in enumerate(corpos):
                # O ritmo: o pedido `n` sai no instante `n / 200` segundos. Sem
                # isto o teste media a capacidade maxima do anfitriao, que nao
                # e o que o criterio pede — ele fixa a **taxa** e pergunta a
                # latencia a essa taxa.
                alvo = indice / PEDIDOS_POR_SEGUNDO
                atraso = alvo - (time.perf_counter() - inicio)
                if atraso > 0:
                    time.sleep(atraso)
                pendentes.append(executor.submit(self._um_pedido, corpo))
            for futuro in pendentes:
                codigo, ms = futuro.result()
                codigos[codigo] = codigos.get(codigo, 0) + 1
                latencias.append(ms)

        duracao = time.perf_counter() - inicio
        latencias.sort()
        mediana = statistics.median(latencias)
        p99 = latencias[min(len(latencias) - 1, int(len(latencias) * 0.99))]
        acima_de_um_segundo = sum(1 for ms in latencias if ms > 1000.0) / len(latencias)
        taxa = len(latencias) / duracao

        relatorio = (
            f"\n--- carga do criterio 7 ---\n"
            f"pedidos:   {len(latencias)} em {duracao:.1f}s ({taxa:.0f}/s)\n"
            f"codigos:   {dict(sorted(codigos.items()))}\n"
            f"mediana:   {mediana:.0f} ms (limiar <= {MEDIANA_MAXIMA_MS})\n"
            f"p99:       {p99:.0f} ms (limiar < {P99_MAXIMO_MS})\n"
            f"> 1 s:     {acima_de_um_segundo * 100:.2f}% "
            f"(limiar < {ACIMA_DE_UM_SEGUNDO_MAXIMO * 100:.0f}%)\n"
            f"maximo:    {latencias[-1]:.0f} ms\n"
            f"---"
        )
        # O relatorio fica no registo do teste, para entrar na evidencia do
        # ticket: um limiar cumprido sem o numero medido nao e evidencia.
        print(relatorio)

        # **Nenhum pedido falhou**, antes dos limiares: um 503 sob carga e um
        # webhook que a Meta vai repetir, e um 0 e uma ligacao recusada.
        self.assertEqual(
            set(codigos), {200}, f"houve respostas que nao foram 200{relatorio}"
        )
        self.assertLessEqual(mediana, MEDIANA_MAXIMA_MS, relatorio)
        self.assertLess(p99, P99_MAXIMO_MS, relatorio)
        self.assertLess(acima_de_um_segundo, ACIMA_DE_UM_SEGUNDO_MAXIMO, relatorio)

        # **Nenhuma mensagem perdida.** O descarte do critério 7 só pode levar
        # estados sem preço, e todos os estados deste perfil trazem `pricing`:
        # as 3 000 mensagens têm de estar todas registadas.
        esperadas = SEGUNDOS * MENSAGENS_POR_SEGUNDO
        self.assertTrue(
            esperar_por(lambda: self._mensagens_registadas() >= esperadas, 180.0, 1.0),
            f"ficaram {self._mensagens_registadas()} de {esperadas} mensagens"
            f"{relatorio}{self.worker.diagnostico()}",
        )
        self.assertEqual(self._descartados(), 0, "descartou-se algo com `pricing`")

    def _mensagens_registadas(self) -> int:
        self.cursor.execute(
            "SELECT count(*) FROM platform.inbound_events WHERE kind = 'message'"
        )
        return int(self.cursor.fetchone()[0])

    def _descartados(self) -> int:
        import re

        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.gwy.porta_das_metricas}/metrics", timeout=10
        ) as resposta:
            texto = resposta.read().decode("utf-8")
        achado = re.search(r"^gwy_shed_total (\d+)$", texto, re.M)
        return int(achado.group(1)) if achado else -1


if __name__ == "__main__":
    unittest.main()
