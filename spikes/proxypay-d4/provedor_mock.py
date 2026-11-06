"""Mock do contrato da ProxyPay (RPS v2 e OPG v1), para o KAM-103.

Nao e um cliente da ProxyPay: e o **alvo** contra o qual o `sandbox.py` se mede
**antes** de tocar no fornecedor. Implementa a forma do contrato que o
`docs/tecnica/evidencia/E2_Pagamentos_Angola.md` §1.2 descreve como CONFIRMADO
a partir da documentacao publica do proprio fornecedor: referencia por
`PUT /references/{id}`, pagamento simulado so no sandbox, fila de seguranca
`GET /payments` e `DELETE /payments/{id}`, `webhook` RPS assinado com
HMAC-SHA256 **sobre o corpo bruto** e com a **propria API key** como segredo, e
o OPG com os quatro desfechos dos numeros de teste.

**Duas coisas deste mock sao inventadas, e dize-las aqui e metade do valor do
ficheiro:**

1. A **rota de configuracao do `webhook`** (`POST /_mock/webhook`). Na ProxyPay
   a URL de callback do RPS configura-se no portal, nao por API. Aqui tem de
   haver uma rota porque o ensaio arranca o seu proprio receptor numa porta
   efemera.
2. O **callback do OPG vai sem assinatura**, e isso e **escolha nossa**, nao
   medicao: o `E2` §1.2 diz que a documentacao do OPG nao menciona assinatura e
   manda **assumir que nao e assinado**. Um mock que o assinasse punha o
   `sandbox.py` a «provar» uma coisa que ninguem verificou. O que fecha essa
   pergunta e a resposta escrita da TimeBoxed (pergunta 8 do `E2` §9), nao este
   ficheiro.

Apontar o `sandbox.py` ao `sandbox` do fornecedor **nao e mudar o alvo**: e
adaptar o cliente e ter chaves. Esta escrito no §8.3 do relatorio, com credor.

**O mock esta escrito para poder reprovar.** A idempotencia do `PUT` guarda de
facto o id; a fila de seguranca remove de facto o que foi reconhecido; a
assinatura calcula-se de facto sobre os bytes que viajam. Um falso que decidisse
pelo nome do ensaio ficava verde com a implementacao apagada, e nao media
predicado nenhum. Por isso aceita tambem **defeitos** injectados (`DEFEITOS`),
que o canario do `sandbox.py` usa para exigir que cada ensaio fique vermelho
quando o predicado deixa de valer.

Nao e codigo de producao, nao e um portao, e nao entra na `main` como
biblioteca: o adaptador ProxyPay e o KAM-056. Biblioteca padrao do Python, sem
dependencias, sem rede para fora.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: Os defeitos que o canario injecta. Cada um apaga **um** predicado, e o ensaio
#: correspondente do `sandbox.py` tem de ficar vermelho por causa dele.
#:
#: Tres familias levam mais do que um defeito, de proposito:
#:
#: - a **fila de seguranca** leva dois, porque «nao remove o que reconheci» e
#:   «remove o que eu nao reconheci» sao falhas opostas e a segunda e a que
#:   rouba um pagamento a PME (`../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`
#:   §8, regra b);
#: - a **assinatura** leva tres: assinar outro corpo, assinar com outra chave, e
#:   assinar o corpo **reserializado**. A terceira e a que apanha um cliente que
#:   verifique o HMAC depois do `parse` em vez de sobre os bytes recebidos, que
#:   e o erro real desta classe de integracao;
#: - o **OPG** leva dois, porque «aceita sempre» e «rejeita com o codigo errado»
#:   falham o mesmo ensaio por razoes diferentes, e um mapeamento de codigos que
#:   troca `2004` por `3000` manda para o cliente a mensagem errada.
DEFEITOS = (
    "put-nao-idempotente",
    "amount-fora-do-intervalo-aceito",
    "custom-fields-perdidos",
    "pagamento-sem-fee",
    "delete-nao-remove",
    "delete-de-id-desconhecido-remove",
    "assinatura-de-outro-corpo",
    "assinatura-com-outra-chave",
    "assinatura-sobre-corpo-reserializado",
    "auth-partilhada",
    "opg-aceita-sempre",
    "opg-codigo-de-recusa-errado",
    "idempotency-key-ignorada",
    "opg-sem-callback",
)

#: Os limites do `amount` do RPS v2, CONFIRMADOS no `E2` §1.2. Sao limites **do
#: API**, nao da rede Multicaixa, e o `E2` di-lo na mesma celula.
AMOUNT_MINIMO = Decimal("0.01")
AMOUNT_MAXIMO = Decimal("99999999.99")

#: Os desfechos dos numeros de teste do OPG, CONFIRMADOS no `E2` §1.2.
#:
#: Sao numeros **de ensaio publicados pelo fornecedor** e nao pertencem a
#: ninguem. Escrevem-se na forma nacional de nove algarismos, que e a forma em
#: que a documentacao do OPG os publica — e tambem a unica que nao e apanhada
#: pelo varrimento de telefones do *gate* 7 (`tools/meta-sim`), cujos padroes
#: exigem o indicativo `244` ou um E.164 entre aspas. Medido: ver o §8.4 do
#: relatorio.
OPG_DESFECHOS: dict[str, tuple[str, int | None]] = {
    "900000000": ("accepted", None),
    "900002004": ("rejected", 2004),
    "900003000": ("rejected", 3000),
}

#: O que qualquer outro movel da: rejeicao imediata com 2010 (`E2` §1.2).
OPG_CODIGO_DESCONHECIDO = 2010


@dataclass
class Pagamento:
    """Um pagamento na fila de seguranca do RPS."""

    id: str
    reference_id: str
    amount: str
    custom_fields: dict


@dataclass
class Estado:
    """O que o provedor guarda. Em memoria, porque e descartavel."""

    defeitos: frozenset[str] = frozenset()
    #: A API key do RPS. **E tambem o segredo do HMAC do `webhook`** — nao sao
    #: duas credenciais, e e isso que torna a rotacao de chaves a pergunta 10 do
    #: `E2` §9: rodar a chave roda a assinatura.
    api_key: str = field(default_factory=lambda: secrets.token_hex(24))
    #: O token do OPG, que e **outro** esquema (`Bearer`) e outra credencial.
    opg_token: str = field(default_factory=lambda: secrets.token_hex(24))
    referencias: dict[str, dict] = field(default_factory=dict)
    #: Quantas referencias **a mais** existem sob o mesmo id. So o defeito
    #: `put-nao-idempotente` o enche, e e o que torna a falha observavel: um
    #: fornecedor que nao seja idempotente por id deixa duas referencias
    #: pagaveis, e o cliente cobra o cliente final duas vezes.
    duplicadas: dict[str, int] = field(default_factory=dict)
    pagamentos: dict[str, Pagamento] = field(default_factory=dict)
    #: Ids ja reconhecidos por `DELETE`, para o segundo `GET` nao os trazer.
    reconhecidos: set[str] = field(default_factory=set)
    #: `Idempotency-Key` do OPG -> id da transacao. Cache de 5 min no fornecedor
    #: (`E2` §1.2); aqui nao expira, porque o ensaio corre em segundos e um
    #: relogio falso media o relogio e nao o contrato.
    idempotencia_opg: dict[str, str] = field(default_factory=dict)
    transaccoes: dict[str, dict] = field(default_factory=dict)
    callback_rps: str | None = None
    proximo_id: int = 1

    def tem(self, defeito: str) -> bool:
        return defeito in self.defeitos

    def novo_id(self, prefixo: str) -> str:
        valor = f"{prefixo}_{self.proximo_id}"
        self.proximo_id += 1
        return valor


class _Handler(BaseHTTPRequestHandler):
    estado: Estado

    # O servidor e um instrumento de medicao: o registo por omissao do
    # `BaseHTTPRequestHandler` escreve para `stderr` e sujava a saida do ensaio.
    def log_message(self, *_args) -> None:  # noqa: D102
        return

    # -- utilitarios ----------------------------------------------------------

    def _corpo(self) -> dict:
        tamanho = int(self.headers.get("Content-Length") or 0)
        if not tamanho:
            return {}
        return json.loads(self.rfile.read(tamanho).decode("utf-8"))

    def _responder(self, codigo: int, carga: dict | None = None) -> None:
        if carga is None:
            self.send_response(codigo)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        bruto = json.dumps(carga, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(bruto)))
        self.end_headers()
        self.wfile.write(bruto)

    def _autorizado(self, esquema: str) -> bool:
        """`Token <api_key>` no RPS, `Bearer <opg_token>` no OPG.

        Sao **dois** esquemas no mesmo fornecedor (`E2` §1.2), e o ensaio 7
        exige que a credencial de um **nao** sirva no outro. O defeito
        `auth-partilhada` aceita qualquer das duas em qualquer rota, e e
        exactamente o atalho que um adaptador com uma so credencial escondia.
        """
        estado = self.estado
        cabecalho = (self.headers.get("Authorization") or "").strip()
        esperados = {"Token": f"Token {estado.api_key}", "Bearer": f"Bearer {estado.opg_token}"}
        if estado.tem("auth-partilhada"):
            return cabecalho in {
                f"Token {estado.api_key}",
                f"Bearer {estado.opg_token}",
                f"Token {estado.opg_token}",
                f"Bearer {estado.api_key}",
            }
        return cabecalho == esperados[esquema]

    # -- rotas ----------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        caminho = self.path.rstrip("/")
        try:
            corpo = self._corpo()
        except (ValueError, json.JSONDecodeError):
            self._responder(400, {"erro": "corpo nao e JSON"})
            return

        # Rota **inventada**: na ProxyPay a URL de callback do RPS configura-se
        # no portal. Vive com prefixo `_mock` para que ninguem a confunda com
        # contrato do fornecedor.
        if caminho == "/_mock/webhook":
            self.estado.callback_rps = corpo.get("url")
            self._responder(201, {"api_key": self.estado.api_key})
            return

        if caminho == "/reference_ids":
            if not self._autorizado("Token"):
                self._responder(401, {"erro": "RPS exige `Authorization: Token <API_KEY>`"})
                return
            self._responder(200, {"id": self.estado.novo_id("ref")})
            return

        if caminho == "/payments":
            if not self._autorizado("Token"):
                self._responder(401, {"erro": "RPS exige `Authorization: Token <API_KEY>`"})
                return
            self._pagamento_simulado(corpo)
            return

        if caminho == "/opg/v1/transactions":
            if not self._autorizado("Bearer"):
                self._responder(401, {"erro": "OPG exige `Authorization: Bearer <TOKEN>`"})
                return
            self._opg_transaccao(corpo)
            return

        self._responder(404, {"erro": f"rota desconhecida: {caminho}"})

    def do_PUT(self) -> None:  # noqa: N802
        caminho = self.path.rstrip("/")
        partes = caminho.split("/")
        if len(partes) == 3 and partes[1] == "references":
            if not self._autorizado("Token"):
                self._responder(401, {"erro": "RPS exige `Authorization: Token <API_KEY>`"})
                return
            try:
                corpo = self._corpo()
            except (ValueError, json.JSONDecodeError):
                self._responder(400, {"erro": "corpo nao e JSON"})
                return
            self._criar_referencia(partes[2], corpo)
            return
        self._responder(404, {"erro": f"rota desconhecida: {caminho}"})

    def do_GET(self) -> None:  # noqa: N802
        caminho = self.path.split("?")[0].rstrip("/")
        partes = caminho.split("/")

        if caminho == "/payments":
            if not self._autorizado("Token"):
                self._responder(401, {"erro": "RPS exige `Authorization: Token <API_KEY>`"})
                return
            fila = [
                self._evento(p)
                for pid, p in self.estado.pagamentos.items()
                if pid not in self.estado.reconhecidos
            ]
            self._responder(200, {"payments": fila})
            return

        if len(partes) == 5 and partes[1] == "opg" and partes[3] == "transactions":
            if not self._autorizado("Bearer"):
                self._responder(401, {"erro": "OPG exige `Authorization: Bearer <TOKEN>`"})
                return
            transaccao = self.estado.transaccoes.get(partes[4])
            if transaccao is None:
                self._responder(404, {"erro": "transacao desconhecida"})
                return
            self._responder(200, transaccao)
            return

        self._responder(404, {"erro": f"rota desconhecida: {caminho}"})

    def do_DELETE(self) -> None:  # noqa: N802
        caminho = self.path.rstrip("/")
        partes = caminho.split("/")
        if len(partes) == 3 and partes[1] == "payments":
            if not self._autorizado("Token"):
                self._responder(401, {"erro": "RPS exige `Authorization: Token <API_KEY>`"})
                return
            self._reconhecer(partes[2])
            return
        self._responder(404, {"erro": f"rota desconhecida: {caminho}"})

    # -- RPS: referencias -----------------------------------------------------

    def _criar_referencia(self, ref_id: str, corpo: dict) -> None:
        estado = self.estado

        bruto = corpo.get("amount")
        try:
            amount = Decimal(str(bruto))
        except (InvalidOperation, TypeError):
            self._responder(422, {"erro": f"`amount` invalido: {bruto!r}"})
            return
        # Os limites do API. O defeito `amount-fora-do-intervalo-aceito`
        # apaga a verificacao, e o ensaio 2 tem de o apanhar.
        if not estado.tem("amount-fora-do-intervalo-aceito"):
            if amount < AMOUNT_MINIMO or amount > AMOUNT_MAXIMO:
                self._responder(
                    422,
                    {"erro": f"`amount` fora de [{AMOUNT_MINIMO}, {AMOUNT_MAXIMO}]"},
                )
                return

        if not corpo.get("end_datetime"):
            self._responder(422, {"erro": "`end_datetime` em falta"})
            return

        campos = corpo.get("custom_fields") or {}
        if len(campos) > 10:
            self._responder(422, {"erro": "`custom_fields` aceita no maximo 10 pares"})
            return

        # O `PUT` e idempotente **pelo id da referencia**: repetir com o mesmo
        # id nao cria uma segunda. O defeito `put-nao-idempotente` deixa uma
        # segunda referencia pagavel sob o mesmo id — que e a forma em que a
        # falha se ve de fora: o mesmo pagamento aparece duas vezes na fila, e
        # o cliente final e cobrado duas vezes. **A primeira versao deste
        # defeito renumerava**, e o ensaio 1 ficava verde com ele: uma
        # referencia extra com id novo nao e observavel por nenhuma rota
        # documentada. Foi o canario a apanhar o ensaio, nao o contrario.
        if ref_id in estado.referencias and estado.tem("put-nao-idempotente"):
            estado.duplicadas[ref_id] = estado.duplicadas.get(ref_id, 0) + 1

        estado.referencias[ref_id] = {
            "id": ref_id,
            "amount": str(amount),
            "end_datetime": corpo["end_datetime"],
            "custom_fields": campos,
        }
        # 204, como o `E2` §1.2 registra: a resposta do `PUT` nao tem corpo.
        self._responder(204)

    # -- RPS: pagamento simulado e fila de seguranca --------------------------

    def _pagamento_simulado(self, corpo: dict) -> None:
        """O *Mock Payment*, que no fornecedor **so existe no sandbox**."""
        estado = self.estado
        ref_id = str(corpo.get("reference_id", ""))
        referencia = estado.referencias.get(ref_id)
        if referencia is None:
            self._responder(404, {"erro": "referencia desconhecida"})
            return

        # Os `custom_fields` do `PUT` sao **copiados para o pagamento** (`E2`
        # §1.2). E isso que permite ligar o pagamento a cobranca sem guardar PII
        # na referencia. O defeito `custom-fields-perdidos` devolve-os vazios, e
        # o ensaio 3 tem de o apanhar.
        campos = {} if estado.tem("custom-fields-perdidos") else dict(referencia["custom_fields"])

        # Uma referencia pagavel da **um** pagamento. Com o defeito
        # `put-nao-idempotente` ha mais do que uma sob o mesmo id, e entao o
        # mesmo pagamento simulado produz um pagamento por cada — que e a forma
        # em que um `PUT` nao idempotente cobra o cliente final duas vezes.
        quantas = 1 + estado.duplicadas.get(ref_id, 0)
        primeiro: Pagamento | None = None
        for _ in range(quantas):
            pagamento = Pagamento(
                id=estado.novo_id("pay"),
                reference_id=ref_id,
                amount=referencia["amount"],
                custom_fields=dict(campos),
            )
            estado.pagamentos[pagamento.id] = pagamento
            primeiro = primeiro or pagamento

        assert primeiro is not None
        self._responder(201, self._evento(primeiro))
        self._disparar_webhook_rps(primeiro)

    def _evento(self, pagamento: Pagamento) -> dict:
        """O evento de pagamento, com os seis campos que o `E2` §1.2 nomeia.

        O `fee` e a comissao **bancaria**, e e o unico sitio em todo este ensaio
        onde o custo real por transacao aparece — e a razao por que o ensaio 4
        existe e por que a matriz do relatorio tem uma coluna para ele. O
        defeito `pagamento-sem-fee` apaga-o.
        """
        evento = {
            "id": pagamento.id,
            "reference_id": pagamento.reference_id,
            "amount": pagamento.amount,
            "custom_fields": pagamento.custom_fields,
            "entity_id": "00000",
            "fee": "15.00",
            "terminal_type": "ATM",
            "terminal_transaction_id": "SINTETICO-1",
            "terminal_location": "SINTETICO",
            "terminal_id": "SINTETICO-T1",
        }
        if self.estado.tem("pagamento-sem-fee"):
            evento.pop("fee")
        return evento

    def _reconhecer(self, pagamento_id: str) -> None:
        estado = self.estado
        if pagamento_id not in estado.pagamentos:
            # `DELETE` de um id que nao existe **nao remove nada**. O defeito
            # `delete-de-id-desconhecido-remove` esvazia a fila, que e a forma
            # de reconhecer um pagamento que nao e nosso — a falha que roubava
            # um pagamento a PME. Ensaio 5.
            if estado.tem("delete-de-id-desconhecido-remove"):
                estado.reconhecidos.update(estado.pagamentos)
                self._responder(204)
                return
            self._responder(404, {"erro": "pagamento desconhecido"})
            return
        if not estado.tem("delete-nao-remove"):
            estado.reconhecidos.add(pagamento_id)
        self._responder(204)

    def _disparar_webhook_rps(self, pagamento: Pagamento) -> None:
        estado = self.estado
        if not estado.callback_rps:
            return

        carga = {"evento": "payment", "payment": self._evento(pagamento)}
        # Duas serializacoes do mesmo objecto, de proposito: a que **viaja** e a
        # compacta. Sem isto o defeito `assinatura-sobre-corpo-reserializado`
        # nao tinha como produzir bytes diferentes, e um defeito que nao muda
        # nada e um defeito que nao prova nada.
        bruto = json.dumps(carga, ensure_ascii=False, separators=(", ", ": ")).encode("utf-8")
        compacto = json.dumps(carga, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        assinado = bruto
        if estado.tem("assinatura-de-outro-corpo"):
            assinado = json.dumps({"evento": "payment"}, ensure_ascii=False).encode("utf-8")
        elif estado.tem("assinatura-sobre-corpo-reserializado"):
            assinado = compacto

        # **O segredo e a propria API key** (`E2` §1.2). Nao e uma simplificacao
        # do mock: e o facto que torna a rotacao de chaves uma pergunta ao
        # fornecedor em vez de uma decisao nossa.
        segredo = estado.api_key
        if estado.tem("assinatura-com-outra-chave"):
            segredo = secrets.token_hex(24)

        assinatura = hmac.new(segredo.encode("utf-8"), assinado, hashlib.sha256).hexdigest()
        self._entregar(estado.callback_rps, bruto, {"X-Signature": assinatura})

    # -- OPG ------------------------------------------------------------------

    def _opg_transaccao(self, corpo: dict) -> None:
        estado = self.estado
        if corpo.get("type") != "payment":
            self._responder(422, {"erro": f"`type` invalido: {corpo.get('type')!r}"})
            return
        movel = str(corpo.get("mobile", ""))
        if not corpo.get("pos_id"):
            self._responder(422, {"erro": "`pos_id` em falta"})
            return

        # `Idempotency-Key` com cache no fornecedor (`E2` §1.2): a mesma chave
        # devolve a **mesma** transacao. O defeito `idempotency-key-ignorada`
        # cria uma segunda, e o ensaio 9 tem de o apanhar.
        chave = self.headers.get("Idempotency-Key")
        if chave and chave in estado.idempotencia_opg and not estado.tem("idempotency-key-ignorada"):
            anterior = estado.transaccoes[estado.idempotencia_opg[chave]]
            self._responder(200, {**anterior, "repetido": True})
            return

        estado_t, codigo = OPG_DESFECHOS.get(movel, ("rejected", OPG_CODIGO_DESCONHECIDO))
        if estado.tem("opg-aceita-sempre"):
            estado_t, codigo = "accepted", None
        elif codigo is not None and estado.tem("opg-codigo-de-recusa-errado"):
            # Troca os dois codigos de recusa um pelo outro: 2004 (timeout) e
            # 3000 (recusa do cliente) passam a mentir um sobre o outro, o que
            # manda para o cliente a mensagem errada em WhatsApp.
            codigo = 3000 if codigo == 2004 else 2004

        transaccao = {
            "id": estado.novo_id("opg"),
            "status": estado_t,
            "code": codigo,
            "mobile": movel,
            "amount": corpo.get("amount"),
        }
        estado.transaccoes[transaccao["id"]] = transaccao
        if chave:
            estado.idempotencia_opg[chave] = transaccao["id"]
        self._responder(201, transaccao)

        # O callback do OPG vai **sem assinatura**, e e escolha deste mock a
        # espelhar o que o `E2` §1.2 manda assumir. Ver a nota no topo: nao e
        # uma medicao sobre a ProxyPay. O defeito `opg-sem-callback` nao o envia,
        # e o ensaio 10 tem de o apanhar — o ensaio mede o **instrumento**.
        destino = corpo.get("callback_url")
        if destino and not estado.tem("opg-sem-callback"):
            self._entregar(destino, json.dumps(transaccao).encode("utf-8"), {})

    # -- entrega --------------------------------------------------------------

    def _entregar(self, url: str, bruto: bytes, cabecalhos: dict[str, str]) -> None:
        pedido = urllib.request.Request(
            url,
            data=bruto,
            headers={"Content-Type": "application/json", **cabecalhos},
            method="POST",
        )
        try:
            urllib.request.urlopen(pedido, timeout=5).read()
        except (urllib.error.URLError, OSError):
            # O cliente pode ter fechado; os ensaios do callback apanham-no pela
            # ausencia de evento recebido, nao por uma excepcao daqui.
            pass


class Provedor:
    """O mock a correr. Usa-se como gestor de contexto."""

    def __init__(self, defeitos: frozenset[str] | None = None) -> None:
        self.estado = Estado(defeitos=frozenset(defeitos or ()))
        desconhecidos = self.estado.defeitos - set(DEFEITOS)
        if desconhecidos:
            raise ValueError(f"defeito(s) desconhecido(s): {sorted(desconhecidos)}")
        handler = type("_H", (_Handler,), {"estado": self.estado})
        self._servidor = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._fio = threading.Thread(target=self._servidor.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        porta = self._servidor.server_address[1]
        return f"http://127.0.0.1:{porta}"

    @property
    def api_key(self) -> str:
        return self.estado.api_key

    @property
    def opg_token(self) -> str:
        return self.estado.opg_token

    def __enter__(self) -> Provedor:
        self._fio.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._servidor.shutdown()
        self._servidor.server_close()
        self._fio.join(timeout=5)
