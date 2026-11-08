"""O gerador de carga do KAM-084: corpos de webhook sinteticos, a ritmo imposto.

## O ritmo e imposto pelo instante-alvo, como no KAM-013

O pedido `n` tem um instante-alvo, e sai **nesse** instante e nao «quando o
anterior responder». Sem isto o ensaio media a capacidade do gerador e nao a
latencia do sistema a uma taxa — que e o que os criterios pedem. E o atraso de
cada pedido face ao seu alvo **regista-se**: um gerador que nao consegue manter
a taxa nao pode passar por um sistema que a aguenta. O relatorio de cada cenario
leva a taxa conseguida e o p99 do atraso, e um degrau da rampa cujo gerador se
atrasou e um degrau **do gerador**, nao do sistema.

## Ligacoes persistentes, e o que isso esconde

Cada *thread* mantem uma ligacao HTTP/1.1 por replica do GWY. Em producao
quem fala com o GWY e o `proxy-tls` (Caddy), que reutiliza ligacoes; a Meta
fala com o Caddy, e se reutiliza ou nao nao ha evidencia no `E1`. A latencia e
a vista pelo cliente (do primeiro byte enviado ao ultimo recebido); sem TLS,
porque o TLS termina no `proxy-tls` e esse nao esta no ensaio.

**O numero de *threads* acompanha a taxa, e a razao foi medida.** Com 64
*threads* a 5 pedidos/s cada ligacao fica ~13 s parada, acima dos 5 s de
*keep-alive* do servidor HTTP do Node: o servidor fecha-a, e o pedido seguinte
encontra-a fechada e paga uma ligacao nova, de Windows para uma porta publicada
do Docker Desktop. Medido no S1 encurtado a 120 s: com 64 *threads*, **535 dos
600** pedidos reabriram a ligacao e o p50 foi 15 ms; com 8, **zero** e 5 ms. (A
primeira corrida do S1, com 64 e sem esta contagem, deu p50 de 60 ms a 5/s
contra 4 ms a 100/s.) O que se media era o encaminhamento de portas do Docker
Desktop, e nao o GWY — que em producao fala com o `proxy-tls`, e nao com a Meta.
Por isso `paralelismo` por omissao e `taxa / 8`, entre 8 e 64 (cada ligacao
fica parada no maximo ~1,6 s), e cada pedido que teve de reabrir a ligacao
**conta** (`reconectou`), para que o efeito fique a vista em vez de escondido.

## Os corpos sao sinteticos, e a forma e a do `E1` §5

Uma mensagem de texto por corpo, ou um estado com `pricing` por corpo — e nunca
lotes, para que um corpo seja um *job* e a reconciliacao se faca por chave. Os
telefones usam o indicativo `999`, que a UIT nao atribui (a convencao de
`db/tests_entrada`). Os `wamid` levam o prefixo `wamid.KAM084.` e um contador.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import math
import random
import threading
import time
from dataclasses import dataclass

#: Prefixo de todos os `wamid` do ensaio.
PREFIXO_WAMID = "wamid.KAM084"


@dataclass(frozen=True)
class Canal:
    """Um canal sintetico: o tenant, a WABA e o `phone_number_id`."""

    tenant_id: str
    waba_id: str
    phone_number_id: str
    indice: int

    def telefone(self, contacto: int) -> str:
        # 999 + 3 digitos do canal + 6 do contacto = 12 digitos, sem pais.
        return f"999{self.indice:03d}{contacto:06d}"


@dataclass(frozen=True)
class Pedido:
    """Um corpo a enviar: quando, o que, e a chave que a base vai ter."""

    alvo: float
    corpo: bytes
    assinatura: str
    #: `(kind, event_key)` que o *worker* de entrada escreve em `inbound_events`.
    chave: tuple[str, str]


def assinar(corpo: bytes, segredo: str) -> str:
    """O `x-hub-signature-256`, calculado aqui e nao pelo modulo testado."""
    return "sha256=" + hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()


def _envelope(canal: Canal, valor: dict) -> bytes:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": canal.waba_id,
                "changes": [{"field": "messages", "value": valor}],
            }
        ],
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def corpo_de_mensagem(canal: Canal, contacto: int, wamid: str, instante: int) -> bytes:
    telefone = canal.telefone(contacto)
    return _envelope(
        canal,
        {
            "messaging_product": "whatsapp",
            "metadata": {
                "display_phone_number": f"999{canal.indice:09d}",
                "phone_number_id": canal.phone_number_id,
            },
            "contacts": [{"profile": {"name": "Cliente sintetico"}, "wa_id": telefone}],
            "messages": [
                {
                    "from": telefone,
                    "id": wamid,
                    "timestamp": str(instante),
                    "type": "text",
                    "text": {"body": "quanto custa o produto 12?"},
                }
            ],
        },
    )


def corpo_de_estado(canal: Canal, contacto: int, wamid: str, estado: str) -> bytes:
    # Com `pricing`: o descarte sob saturacao do KAM-013 nunca o pode levar, e
    # por isso cada estado tambem entra na reconciliacao.
    return _envelope(
        canal,
        {
            "messaging_product": "whatsapp",
            "metadata": {"phone_number_id": canal.phone_number_id},
            "statuses": [
                {
                    "id": wamid,
                    "status": estado,
                    "recipient_id": canal.telefone(contacto),
                    "pricing": {"category": "service"},
                }
            ],
        },
    )


ESTADOS = ("sent", "delivered", "read")


class Fabrica:
    """Gera a mistura do perfil: **1 mensagem de cliente para 3 estados**.

    E a proporcao do `E1` §5 («3x o trafego de saida (status) + 1x o de
    entrada») e a do KAM-013. Cada mensagem de cliente tem uma resposta do bot,
    e cada resposta do bot gera os tres estados — o que da 1:3 e nao 1:3,6 como
    as 28 800 respostas para 24 000 mensagens do doc 09 §14.1 dariam. A
    diferenca e 20% na contagem de estados e fica escrita no relatorio.

    O contador e da fabrica, e nao de cada chamada: dois cenarios na mesma
    corrida nunca repetem um `wamid` por acidente — so quando o cenario o pede
    (a rajada reentrega de proposito).
    """

    def __init__(self, segredo: str, canais: list[Canal], contactos_por_canal: int, semente: int) -> None:
        self.segredo = segredo
        self.canais = canais
        self.contactos = contactos_por_canal
        self._aleatorio = random.Random(semente)
        self._contador = 0

    def _proximo(self, tipo: str) -> str:
        self._contador += 1
        return f"{PREFIXO_WAMID}.{tipo}.{self._contador:09d}"

    def bloco(self, alvo_base: float, intervalo: float, canais: list[Canal] | None = None) -> list[Pedido]:
        """Quatro pedidos (1 mensagem + 3 estados), com alvos espacados de `intervalo`."""
        canal = self._aleatorio.choice(canais or self.canais)
        contacto = self._aleatorio.randrange(self.contactos)
        entrada = self._proximo("M")
        resposta = self._proximo("B")
        pedidos = []
        corpo = corpo_de_mensagem(canal, contacto, entrada, 1_793_000_000 + self._contador)
        pedidos.append(Pedido(alvo_base, corpo, assinar(corpo, self.segredo), ("message", entrada)))
        for i, estado in enumerate(ESTADOS, start=1):
            corpo = corpo_de_estado(canal, contacto, resposta, estado)
            pedidos.append(
                Pedido(
                    alvo_base + i * intervalo,
                    corpo,
                    assinar(corpo, self.segredo),
                    ("statuses", f"{resposta}:{estado}"),
                )
            )
        return pedidos

    def plano(self, taxa: float, segundos: float, inicio: float = 0.0, canais: list[Canal] | None = None) -> list[Pedido]:
        """`taxa` pedidos por segundo durante `segundos`, a partir de `inicio`."""
        if taxa <= 0 or segundos <= 0:
            raise ValueError("taxa e duracao tem de ser positivas")
        total = int(round(taxa * segundos))
        intervalo = 1.0 / taxa
        pedidos: list[Pedido] = []
        while len(pedidos) < total:
            pedidos.extend(self.bloco(inicio + len(pedidos) * intervalo, intervalo, canais))
        return pedidos[:total]


@dataclass
class Resultado:
    """O que aconteceu a um pedido."""

    alvo: float
    atraso_ms: float
    latencia_ms: float
    codigo: int
    #: Relogio de parede do anfitriao no envio — para a idade na fila.
    enviado_epoch: float
    #: A ligacao persistente estava fechada e abriu-se outra.
    reconectou: bool = False


def _enviar(
    ligacoes: dict[int, http.client.HTTPConnection], porta: int, pedido: Pedido
) -> tuple[int, float, bool]:
    """`(codigo, latencia_ms, reconectou)`. A latencia e a da tentativa que contou."""
    reconectou = False
    for tentativa in (1, 2):
        ligacao = ligacoes.get(porta)
        if ligacao is None:
            ligacao = http.client.HTTPConnection("127.0.0.1", porta, timeout=30)
            ligacoes[porta] = ligacao
        inicio = time.perf_counter()
        try:
            ligacao.request(
                "POST",
                "/wa/webhook",
                body=pedido.corpo,
                headers={
                    "content-type": "application/json",
                    "x-hub-signature-256": pedido.assinatura,
                },
            )
            resposta = ligacao.getresponse()
            resposta.read()
            return resposta.status, (time.perf_counter() - inicio) * 1000.0, reconectou
        except (http.client.HTTPException, OSError):
            # Uma ligacao persistente que o servidor fechou: reabre-se uma vez.
            # A segunda falha e um 0 — ligacao recusada —, e conta.
            ligacao.close()
            ligacoes.pop(porta, None)
            reconectou = True
            if tentativa == 2:
                return 0, (time.perf_counter() - inicio) * 1000.0, reconectou
    return 0, 0.0, reconectou


def paralelismo_para(taxa: float) -> int:
    """`taxa / 8`, entre 8 e 64. Ver «O numero de *threads* acompanha a taxa»."""
    return max(8, min(64, math.ceil(taxa / 8)))


def disparar(
    pedidos: list[Pedido], portas: list[int], paralelismo: int | None = None
) -> list[Resultado]:
    """Envia o plano a ritmo, repartido em *round-robin* pelas replicas.

    Devolve um resultado por pedido, pela ordem do plano.
    """
    if not portas:
        raise ValueError("sem portas")
    if paralelismo is None:
        duracao = max(pedidos[-1].alvo - pedidos[0].alvo, 1e-9) if len(pedidos) > 1 else 1.0
        paralelismo = paralelismo_para(len(pedidos) / duracao)
    resultados: list[Resultado | None] = [None] * len(pedidos)
    proximo = [0]
    tranca = threading.Lock()
    inicio = time.perf_counter()
    inicio_epoch = time.time()

    def trabalhar() -> None:
        ligacoes: dict[int, http.client.HTTPConnection] = {}
        try:
            while True:
                with tranca:
                    indice = proximo[0]
                    proximo[0] += 1
                if indice >= len(pedidos):
                    return
                pedido = pedidos[indice]
                espera = pedido.alvo - (time.perf_counter() - inicio)
                if espera > 0:
                    time.sleep(espera)
                saida = time.perf_counter()
                codigo, ms, reconectou = _enviar(ligacoes, portas[indice % len(portas)], pedido)
                resultados[indice] = Resultado(
                    alvo=pedido.alvo,
                    atraso_ms=(saida - inicio - pedido.alvo) * 1000.0,
                    latencia_ms=ms,
                    codigo=codigo,
                    enviado_epoch=inicio_epoch + (saida - inicio),
                    reconectou=reconectou,
                )
        finally:
            for ligacao in ligacoes.values():
                ligacao.close()

    fios = [threading.Thread(target=trabalhar, daemon=True) for _ in range(paralelismo)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    return [r for r in resultados if r is not None]
