"""Ensaio de `sandbox` do KAM-103: o criterio 7, contra um mock.

Corre contra o `provedor_mock.py`, que e o que o ticket exige: *prepara o script
e um mock do contrato, corre-o contra o mock, e deixa a corrida contra o
fornecedor como caixa devolvida* — pedir chaves e contacto com contraparte, e
contacto com contraparte e acto do fundador.

    python spikes/proxypay-d4/sandbox.py              # contra o mock
    python spikes/proxypay-d4/sandbox.py --canario    # prova que os ensaios reprovam
    python spikes/proxypay-d4/sandbox.py --base URL   # contra outro alvo

**Aviso sobre o `--base`, e e a parte que nao se pode calar.** O contrato que
este cliente fala e o do `provedor_mock.py`, que espelha a forma documentada do
RPS v2 e do OPG v1 mas **nao e** o contrato do fornecedor: a configuracao do
`webhook` e uma rota inventada (`POST /_mock/webhook`, porque na ProxyPay isso
faz-se no portal), o pagamento simulado toma `reference_id` num corpo que nao
foi lido numa fonte primaria, e **nao ha chaves**. Apontado ao
`api.sandbox.proxypay.co.ao`, este cliente devolve **401 na primeira chamada e
corre zero ensaios** sem `PROXYPAY_API_KEY` e `PROXYPAY_OPG_TOKEN` no ambiente —
e as chaves de `sandbox` pedem-se a TimeBoxed, que e contacto com contraparte.

Faltam, portanto, **duas** coisas e nao uma: as **chaves de teste**, que sao
acto do fundador, e **adaptar o cliente** ao contrato real (rotas exactas do
pagamento simulado, configuracao do callback, nomes de campo). A segunda esta
devolvida no §8.3 do relatorio. **Nao e «correr e ler».**

Os dez predicados:

 1. referencia por `PUT /references/{id}` -> 204, e o mesmo id **nao** cria
    uma segunda referencia
 2. limites do `amount` do API: 0,01 e 99.999.999,99 aceitam; 0,00 e
    100.000.000,00 recusam
 3. pagamento simulado cria o pagamento **e copia** os `custom_fields`
 4. o evento de pagamento traz os seis campos de conciliacao, `fee` incluido
 5. fila de seguranca: `GET /payments` lista; `DELETE /payments/{id}` remove o
    **nosso**; e um `DELETE` de id desconhecido **nao** esvazia a fila
 6. `webhook` RPS assinado: `X-Signature` = HMAC-SHA256 **do corpo bruto**, com
    a **propria API key** como segredo
 7. dois esquemas de autenticacao: `Token` no RPS, `Bearer` no OPG, e a
    credencial de um **nao** serve no outro
 8. OPG, os tres numeros de teste: 900000000 aceita, 900002004 rejeita com
    2004, 900003000 rejeita com 3000, outro movel rejeita com 2010
 9. OPG `Idempotency-Key`: a mesma chave 2x devolve **uma** transacao
10. o callback do OPG chegou e os cabecalhos **ficaram registados**

**O predicado 10 nao e um predicado sobre a ProxyPay, e o ensaio di-lo na
saida.** Se o callback do OPG e assinado e **NAO VERIFICADO** (`E2` §1.2: a
documentacao do OPG nao menciona assinatura). O mock envia-o **sem** assinatura
por **escolha nossa**, a espelhar o que o `E2` manda assumir — pelo que uma
asercao «nao vem assinado» mediria a nossa escolha e nao o fornecedor. O que o
ensaio 10 mede e o **instrumento**: que o receptor existe, recebeu, e guardou os
cabecalhos que vierem. Quem fecha a pergunta e a resposta escrita da TimeBoxed
(pergunta 8 do `E2` §9).

**Sem dados reais.** Os numeros do OPG sao os **de ensaio publicados pelo
fornecedor** (`E2` §1.2) e nao pertencem a ninguem; escrevem-se na forma
nacional de nove algarismos, que e a forma em que a documentacao os publica.
Nenhuma chave vive em ficheiro: as do mock sao geradas em cada arranque, e as
de um fornecedor viriam do ambiente.

Nao e codigo de producao e nao e um portao: o adaptador ProxyPay e o KAM-056.
Biblioteca padrao do Python.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import queue
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from provedor_mock import DEFEITOS, Provedor  # noqa: E402

#: Que ensaio cada defeito tem de avermelhar. O canario le isto.
CANARIO: dict[str, int] = {
    "put-nao-idempotente": 1,
    "amount-fora-do-intervalo-aceito": 2,
    "custom-fields-perdidos": 3,
    "pagamento-sem-fee": 4,
    "delete-nao-remove": 5,
    "delete-de-id-desconhecido-remove": 5,
    "assinatura-de-outro-corpo": 6,
    "assinatura-com-outra-chave": 6,
    "assinatura-sobre-corpo-reserializado": 6,
    "auth-partilhada": 7,
    "opg-aceita-sempre": 8,
    "opg-codigo-de-recusa-errado": 8,
    "idempotency-key-ignorada": 9,
    "opg-sem-callback": 10,
    "valor-trocado": 3,
    "fee-nulo": 4,
}

#: Os seis campos de conciliacao do evento de pagamento (`E2` §1.2).
CAMPOS_DE_CONCILIACAO = (
    "entity_id",
    "fee",
    "terminal_type",
    "terminal_transaction_id",
    "terminal_location",
    "terminal_id",
)

#: Os numeros de ensaio do OPG e o desfecho que **o ensaio** espera. Escritos
#: aqui e **nao** importados do mock: alvo e oraculo no mesmo literal nao mediam
#: nada — trocar o valor no mock deixava o ensaio verde com o OPG a mentir.
OPG_ESPERADO: tuple[tuple[str, str, int | None], ...] = (
    ("900000000", "accepted", None),
    ("900002004", "rejected", 2004),
    ("900003000", "rejected", 3000),
)

#: O codigo do quarto desfecho: qualquer outro movel rejeita imediato com 2010
#: (`E2` §1.2, CONF). **Literal aqui, e nao importado do mock**, pela mesma razao
#: do `OPG_ESPERADO` acima — e a primeira versao **importava-o**, pelo que trocar
#: a constante do alvo deixava o ensaio 8 verde a imprimir o valor errado como
#: esperado. Achado da revisao adversarial, na unica constante onde o comentario
#: ao lado dizia ter evitado a armadilha e nao a evitou.
OPG_CODIGO_FORA_DA_LISTA = 2010

#: Um movel que nao esta na lista de ensaio do fornecedor.
#:
#: **E do intervalo ficticio `999`**, que a UIT nao atribui a nenhum pais e que
#: esta casa ja usa (`tools/meta-sim/src/numeros.ts`, `INDICATIVO_FICTICIO`).
#: A primeira versao usava um `92x` de nove algarismos «sequencial, e nao
#: pertence a ninguem» — e isso era uma afirmacao sem fonte sobre um numero bem
#: formado da rede movel angolana, exactamente o que o `inventario.ts` diz que
#: nenhuma expressao regular consegue decidir. O ensaio 8 so precisa de «um
#: movel que nao esta na lista», e o intervalo reservado serve igual.
OPG_FORA_DA_LISTA = "999100000001"


#: O valor da cobranca do ensaio, em `decimal2` como o RPS o quer. Fica numa
#: constante porque **atravessa quatro superficies** — o `PUT`, o pagamento, o
#: evento da fila e o corpo do `callback` — e o que os ensaios 3 e 6 medem e que
#: e **o mesmo** nas quatro. E o gate G4 «Valor exacto» do
#: `../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §5.
VALOR = "1500.00"


class Reprovado(Exception):
    """Um predicado deixou de valer."""


def exigir(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise Reprovado(mensagem)


# -- receptor de callback -----------------------------------------------------


class _Receptor(BaseHTTPRequestHandler):
    filas: dict[str, queue.Queue]

    def log_message(self, *_args) -> None:  # noqa: D102
        return

    def do_POST(self) -> None:  # noqa: N802
        tamanho = int(self.headers.get("Content-Length") or 0)
        bruto = self.rfile.read(tamanho) if tamanho else b""
        # **Guarda-se o corpo em bytes**, nao o objecto: o HMAC do RPS e sobre o
        # corpo bruto, e verificar sobre o reserializado era o defeito que o
        # `assinatura-sobre-corpo-reserializado` do canario apanha.
        #
        # E guardam-se **todos** os cabecalhos, nao so o da assinatura: a
        # pergunta a que este receptor serve — «o callback do OPG e assinado?» —
        # nao se responde a procurar um nome que se escolheu de antemao.
        #
        # Uma fila **por rota**, e nao uma so: o RPS e o OPG entregam os dois
        # neste receptor, e uma fila unica punha o ensaio 10 a ler o callback do
        # RPS que o ensaio 6 nao consumiu. Dois canais distintos leem-se em
        # canais distintos.
        qual = "opg" if self.path.rstrip("/").endswith("/opg") else "rps"
        self.filas[qual].put((self.path, bruto, dict(self.headers.items())))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


class Receptor:
    """Recebe callbacks numa porta efemera do `localhost`, um canal por rota."""

    def __init__(self) -> None:
        self.filas: dict[str, queue.Queue] = {"rps": queue.Queue(), "opg": queue.Queue()}
        handler = type("_R", (_Receptor,), {"filas": self.filas})
        self._servidor = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._fio = threading.Thread(target=self._servidor.serve_forever, daemon=True)

    def _url(self, qual: str) -> str:
        return f"http://127.0.0.1:{self._servidor.server_address[1]}/callback/{qual}"

    @property
    def url_rps(self) -> str:
        return self._url("rps")

    @property
    def url_opg(self) -> str:
        return self._url("opg")

    def esperar(self, qual: str, segundos: float = 10.0) -> tuple[str, bytes, dict[str, str]]:
        try:
            return self.filas[qual].get(timeout=segundos)
        except queue.Empty as vazio:
            raise Reprovado(f"nenhum callback de {qual} chegou em {segundos:.0f}s") from vazio

    def __enter__(self) -> Receptor:
        self._fio.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._servidor.shutdown()
        self._servidor.server_close()
        self._fio.join(timeout=5)


# -- cliente ------------------------------------------------------------------


def _chamar(
    base: str,
    metodo: str,
    caminho: str,
    corpo: dict | None = None,
    credencial: str | None = None,
    extra: dict[str, str] | None = None,
) -> tuple[int, dict]:
    """Devolve `(codigo, corpo)`. Um 204 da `{}`, e um 4xx da o corpo do erro."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    cabecalhos = {"Content-Type": "application/json", **(extra or {})}
    if credencial:
        cabecalhos["Authorization"] = credencial
    pedido = urllib.request.Request(
        base.rstrip("/") + caminho, data=dados, headers=cabecalhos, method=metodo
    )
    try:
        with urllib.request.urlopen(pedido, timeout=15) as resposta:
            bruto = resposta.read()
            return resposta.status, (json.loads(bruto.decode("utf-8")) if bruto else {})
    except urllib.error.HTTPError as erro:
        bruto = erro.read()
        try:
            return erro.code, json.loads(bruto.decode("utf-8")) if bruto else {}
        except json.JSONDecodeError:
            return erro.code, {"erro": bruto.decode("utf-8", errors="replace")[:200]}
    except (urllib.error.URLError, OSError) as erro:
        raise SystemExit(f"nao foi possivel falar com {base}: {erro}")


@dataclass
class Contexto:
    base: str
    receptor: Receptor
    api_key: str
    opg_token: str
    referencia: str = ""
    pagamento: str = ""
    cabecalhos_do_opg: dict[str, str] = field(default_factory=dict)

    @property
    def rps(self) -> str:
        return f"Token {self.api_key}"

    @property
    def opg(self) -> str:
        return f"Bearer {self.opg_token}"


# -- os dez ensaios -----------------------------------------------------------


def ensaio_1_referencia(ctx: Contexto) -> str:
    codigo, corpo = _chamar(ctx.base, "POST", "/reference_ids", {}, ctx.rps)
    exigir(codigo == 200 and corpo.get("id"), f"`POST /reference_ids` devolveu {codigo}: {corpo}")
    ctx.referencia = str(corpo["id"])

    carga = {
        "amount": VALOR,
        "end_datetime": "2027-01-31T23:59:59Z",
        # Sem PII: o que vai nos `custom_fields` e o id da cobranca, nunca o
        # telefone nem o nome do cliente (`../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §3.3).
        "custom_fields": {"charge": "SINTETICO-c1"},
    }
    codigo, corpo = _chamar(ctx.base, "PUT", f"/references/{ctx.referencia}", carga, ctx.rps)
    exigir(codigo == 204, f"`PUT /references/{{id}}` devolveu {codigo}, esperava 204: {corpo}")

    # Repetir o mesmo `PUT`: nao pode nascer uma segunda referencia. Mede-se
    # pelo **estado da fila**, nao pela resposta: um fornecedor que renumere
    # devolve 204 as duas vezes e a diferenca so aparece a seguir.
    codigo, corpo = _chamar(ctx.base, "PUT", f"/references/{ctx.referencia}", carga, ctx.rps)
    exigir(codigo == 204, f"o segundo `PUT` devolveu {codigo}: {corpo}")

    codigo, corpo = _chamar(ctx.base, "POST", "/payments", {"reference_id": ctx.referencia}, ctx.rps)
    exigir(codigo in (200, 201), f"pagamento simulado da referencia devolveu {codigo}: {corpo}")
    codigo, lista = _chamar(ctx.base, "GET", "/payments?n=100", None, ctx.rps)
    exigir(codigo == 200, f"`GET /payments` devolveu {codigo}: {lista}")
    pagamentos = lista.get("payments") or []
    # **Conta-se, nao se olha para o conjunto de ids.** Uma referencia a mais
    # sob o mesmo id nao muda o conjunto de `reference_id` da fila; muda
    # **quantos pagamentos** um unico pagamento simulado produz, que e a forma
    # em que um `PUT` nao idempotente cobra o cliente final duas vezes. A
    # primeira versao deste ensaio comparava o conjunto e ficava verde com o
    # defeito injectado.
    nossos = [p for p in pagamentos if p.get("reference_id") == ctx.referencia]
    exigir(
        len(nossos) == 1 and len(pagamentos) == 1,
        f"um pagamento simulado produziu {len(nossos)} pagamento(s) para a referencia "
        f"{ctx.referencia} (fila com {len(pagamentos)}): o `PUT` repetido deixou mais do "
        "que uma referencia pagavel sob o mesmo id",
    )
    # Limpa a fila para que o ensaio 3 meca a sua propria.
    for pagamento in pagamentos:
        _chamar(ctx.base, "DELETE", f"/payments/{pagamento['id']}", None, ctx.rps)
    return f"referencia {ctx.referencia} criada com 204; o `PUT` repetido nao criou uma segunda"


def ensaio_2_limites_do_amount(ctx: Contexto) -> str:
    casos = (("0.01", True), ("99999999.99", True), ("0.00", False), ("100000000.00", False))
    for valor, aceitavel in casos:
        codigo, corpo = _chamar(
            ctx.base,
            "PUT",
            f"/references/{ctx.referencia}-a-{valor.replace('.', '')}",
            {"amount": valor, "end_datetime": "2027-01-31T23:59:59Z"},
            ctx.rps,
        )
        if aceitavel:
            exigir(codigo == 204, f"`amount={valor}` devia ser aceite e deu {codigo}: {corpo}")
        else:
            exigir(
                codigo == 422,
                f"`amount={valor}` esta fora de [0,01; 99.999.999,99] e foi aceite ({codigo})",
            )
    # As duas referencias aceites ficam sem pagamento, logo sem fila.
    return "0,01 e 99.999.999,99 aceites; 0,00 e 100.000.000,00 recusados com 422"


def ensaio_3_pagamento_simulado(ctx: Contexto) -> str:
    codigo, corpo = _chamar(ctx.base, "POST", "/payments", {"reference_id": ctx.referencia}, ctx.rps)
    exigir(codigo in (200, 201), f"pagamento simulado devolveu {codigo}: {corpo}")
    exigir(bool(corpo.get("id")), f"o pagamento veio sem `id`: {corpo}")
    ctx.pagamento = str(corpo["id"])
    exigir(
        corpo.get("reference_id") == ctx.referencia,
        f"o pagamento diz ser da referencia {corpo.get('reference_id')!r} e nao de {ctx.referencia!r}",
    )
    # Os `custom_fields` do `PUT` **copiados para o pagamento**: e o que liga o
    # pagamento a cobranca sem guardar PII na referencia. Sem eles, a
    # reconciliacao do KAM-056 nao sabe de quem e o dinheiro.
    exigir(
        (corpo.get("custom_fields") or {}).get("charge") == "SINTETICO-c1",
        f"os `custom_fields` do `PUT` nao foram copiados para o pagamento: {corpo.get('custom_fields')!r}",
    )
    # **O valor tem de ser o valor pedido**, e isto foi o achado mais grave da
    # revisao adversarial: sem esta asercao os dez ensaios ficavam verdes com um
    # fornecedor que cobrasse 1,00 Kz por uma cobranca de 1.500,00 Kz. E o gate
    # **G4 «Valor exacto»** do `../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`
    # §5, que e **regra imutavel** desta casa, e o primeiro caso obrigatorio da
    # suite de conformidade do §3.5. Compara-se contra a constante **do ensaio**,
    # nunca contra o que o alvo devolveu no `PUT`.
    exigir(
        str(corpo.get("amount")) == VALOR,
        f"o pagamento diz {corpo.get('amount')!r} e a cobranca pedida foi {VALOR!r}",
    )
    return (
        f"pagamento {ctx.pagamento} criado, com os `custom_fields` da referencia "
        f"copiados e `amount` = {VALOR}"
    )


def ensaio_4_campos_de_conciliacao(ctx: Contexto) -> str:
    codigo, lista = _chamar(ctx.base, "GET", "/payments?n=100", None, ctx.rps)
    exigir(codigo == 200, f"`GET /payments` devolveu {codigo}: {lista}")
    nosso = [p for p in (lista.get("payments") or []) if p.get("id") == ctx.pagamento]
    exigir(len(nosso) == 1, f"o pagamento {ctx.pagamento} nao esta na fila: {lista}")
    faltam = [c for c in CAMPOS_DE_CONCILIACAO if c not in nosso[0]]
    exigir(not faltam, f"o evento de pagamento nao traz {faltam}")
    # **Presenca de chave nao mede o `fee`**, e foi um achado da revisao
    # adversarial: um fornecedor que devolva `fee: null`, `fee: ""` ou `fee: 0`
    # passava, e a saida imprimia `fee = None` sem avermelhar. O criterio 7 do
    # KAM-056 pede o `fee` guardado «em 100% dos pagamentos do sandbox», e o
    # §3.3 do relatorio faz deste campo o instrumento que fecha o segundo
    # componente de custo — nenhuma das duas coisas se sustenta numa chave vazia.
    bruto = nosso[0]["fee"]
    exigir(
        bruto is not None and str(bruto).strip() != "",
        f"o `fee` vem presente e vazio: {bruto!r} — presenca de chave nao e valor",
    )
    try:
        valor = Decimal(str(bruto))
    except InvalidOperation as erro:
        raise Reprovado(f"o `fee` nao e um decimal: {bruto!r}") from erro
    exigir(valor >= 0, f"o `fee` e negativo: {bruto!r}")
    return f"os {len(CAMPOS_DE_CONCILIACAO)} campos presentes; `fee` = {valor} (decimal, >= 0)"


def ensaio_5_fila_de_seguranca(ctx: Contexto) -> str:
    def fila() -> set[str]:
        codigo, lista = _chamar(ctx.base, "GET", "/payments?n=100", None, ctx.rps)
        exigir(codigo == 200, f"`GET /payments` devolveu {codigo}: {lista}")
        return {str(p.get("id")) for p in (lista.get("payments") or [])}

    exigir(ctx.pagamento in fila(), f"o pagamento {ctx.pagamento} devia estar na fila e nao esta")

    # Um `DELETE` de um id **que nao existe** nao pode esvaziar a fila.
    #
    # **E isto, e so isto, que o ensaio mede** — e a precisao e uma correccao da
    # revisao adversarial. A regra b do
    # `../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §8 e outra
    # coisa: «so reconhecer pagamentos de cobrancas nossas», porque se a PME
    # usar a mesma conta ProxyPay noutra integracao o nosso *job* roubar-lhe-ia
    # pagamentos. Essa regra e uma propriedade **do nosso cliente** (uma chave
    # dedicada por PME, e alerta de orfao em vez de `DELETE`), nao do contrato
    # do fornecedor: a fila do RPS e por chave de API, e nenhuma rota distingue
    # um pagamento «alheio». Um alvo que aceitasse um `DELETE` sobre um
    # pagamento conhecido e de outra integracao passa este ensaio limpo, e isso
    # esta na lista do que o *spike* nao mede, no `README.md`.
    _chamar(ctx.base, "DELETE", "/payments/pay_INEXISTENTE", None, ctx.rps)
    exigir(
        ctx.pagamento in fila(),
        f"um `DELETE` de um id desconhecido removeu o pagamento {ctx.pagamento} da fila",
    )

    codigo, corpo = _chamar(ctx.base, "DELETE", f"/payments/{ctx.pagamento}", None, ctx.rps)
    exigir(codigo in (200, 204), f"`DELETE /payments/{{id}}` devolveu {codigo}: {corpo}")
    exigir(
        ctx.pagamento not in fila(),
        f"o pagamento {ctx.pagamento} continua na fila depois do `DELETE`",
    )
    return (
        "o pagamento aparece na fila, sobrevive a um `DELETE` de id inexistente, "
        "e sai com o seu (a regra b do `04` §8 e do cliente, e nao se mede aqui)"
    )


def ensaio_6_webhook_assinado(ctx: Contexto) -> str:
    caminho, bruto, cabecalhos = ctx.receptor.esperar("rps")
    assinatura = next(
        (v for k, v in cabecalhos.items() if k.lower() == "x-signature"),
        None,
    )
    exigir(
        assinatura is not None,
        f"o callback do RPS chegou sem `X-Signature`; cabecalhos: {sorted(cabecalhos)}",
    )
    # **O segredo e a propria API key** (`E2` §1.2), e e sobre o **corpo bruto**.
    esperada = hmac.new(ctx.api_key.encode("utf-8"), bruto, hashlib.sha256).hexdigest()
    exigir(
        hmac.compare_digest(assinatura, esperada),
        "`X-Signature` nao corresponde ao HMAC-SHA256 do corpo bruto com a API key",
    )
    # Um byte alterado tem de deixar de conferir. Nao e tautologia: prova que a
    # comparacao e sobre **este** corpo e nao sobre um prefixo ou um resumo.
    adulterado = bytearray(bruto)
    adulterado[-2] ^= 0x01
    exigir(
        not hmac.compare_digest(
            assinatura,
            hmac.new(ctx.api_key.encode("utf-8"), bytes(adulterado), hashlib.sha256).hexdigest(),
        ),
        "um byte alterado no corpo continua a conferir com a mesma assinatura",
    )
    carga = json.loads(bruto.decode("utf-8"))
    pagamento = carga.get("payment") or {}
    exigir(
        pagamento.get("reference_id") == ctx.referencia,
        f"o callback notificou a referencia {pagamento.get('reference_id')!r} e nao {ctx.referencia!r}",
    )
    # Uma assinatura valida sobre o valor errado e pior do que nenhuma: a
    # plataforma marcaria como paga uma cobranca por outro montante, e o G4
    # «Valor exacto» existe precisamente para isso. A quarta superficie por onde
    # o valor passa, e a ultima.
    exigir(
        str(pagamento.get("amount")) == VALOR,
        f"o callback assinado traz `amount` {pagamento.get('amount')!r} e a cobranca foi {VALOR!r}",
    )
    return (
        f"`X-Signature` = HMAC-SHA256(API key, corpo bruto) confere em {caminho}, "
        f"e o corpo traz `amount` = {VALOR}"
    )


def ensaio_7_dois_esquemas_de_auth(ctx: Contexto) -> str:
    codigo, _ = _chamar(ctx.base, "POST", "/reference_ids", {}, ctx.opg)
    exigir(codigo == 401, f"o RPS aceitou o `Bearer` do OPG ({codigo}); esperava 401")
    codigo, _ = _chamar(
        ctx.base,
        "POST",
        "/opg/v1/transactions",
        {"type": "payment", "pos_id": "SINTETICO-POS", "mobile": "900000000", "amount": "1500.00"},
        ctx.rps,
    )
    exigir(codigo == 401, f"o OPG aceitou o `Token` do RPS ({codigo}); esperava 401")
    return "`Token` so no RPS e `Bearer` so no OPG: a credencial de um nao serve no outro"


def ensaio_8_opg_tres_numeros(ctx: Contexto) -> str:
    vistos = []
    for movel, estado, codigo_esperado in OPG_ESPERADO:
        carga = {
            "type": "payment",
            "pos_id": "SINTETICO-POS",
            "mobile": movel,
            "amount": VALOR,
            "callback_url": ctx.receptor.url_opg,
        }
        codigo, corpo = _chamar(ctx.base, "POST", "/opg/v1/transactions", carga, ctx.opg)
        exigir(codigo in (200, 201), f"`POST /opg/v1/transactions` ({movel}) devolveu {codigo}: {corpo}")
        exigir(
            corpo.get("status") == estado,
            f"o movel de ensaio {movel} devia dar `{estado}` e deu `{corpo.get('status')}`",
        )
        exigir(
            corpo.get("code") == codigo_esperado,
            f"o movel de ensaio {movel} devia dar codigo {codigo_esperado} e deu {corpo.get('code')}",
        )
        vistos.append(f"{movel}->{estado}/{codigo_esperado}")

    codigo, corpo = _chamar(
        ctx.base,
        "POST",
        "/opg/v1/transactions",
        {"type": "payment", "pos_id": "SINTETICO-POS", "mobile": OPG_FORA_DA_LISTA, "amount": "1500.00"},
        ctx.opg,
    )
    exigir(codigo in (200, 201), f"o movel fora da lista devolveu {codigo}: {corpo}")
    exigir(
        corpo.get("status") == "rejected" and corpo.get("code") == OPG_CODIGO_FORA_DA_LISTA,
        f"um movel fora da lista de ensaio devia dar rejected/{OPG_CODIGO_FORA_DA_LISTA} "
        f"e deu {corpo.get('status')}/{corpo.get('code')}",
    )
    return "; ".join(vistos) + f"; fora da lista -> rejected/{OPG_CODIGO_FORA_DA_LISTA}"


def ensaio_9_idempotency_key(ctx: Contexto) -> str:
    carga = {
        "type": "payment",
        "pos_id": "SINTETICO-POS",
        "mobile": "900000000",
        "amount": VALOR,
    }
    chave = {"Idempotency-Key": "SINTETICO-idem-1"}
    codigo, primeira = _chamar(ctx.base, "POST", "/opg/v1/transactions", carga, ctx.opg, chave)
    exigir(codigo in (200, 201), f"a primeira chamada devolveu {codigo}: {primeira}")
    codigo, segunda = _chamar(ctx.base, "POST", "/opg/v1/transactions", carga, ctx.opg, chave)
    exigir(codigo in (200, 201), f"a segunda chamada devolveu {codigo}: {segunda}")
    exigir(
        primeira.get("id") == segunda.get("id"),
        f"a mesma `Idempotency-Key` deu duas transacoes: {primeira.get('id')} e {segunda.get('id')}",
    )
    # A cache do fornecedor e de 5 minutos (`E2` §1.2), e isso **nao** se mede
    # aqui: medi-lo obrigava a esperar cinco minutos ou a mentir sobre o relogio
    # do mock. Fica dito na saida e no §8.2 do relatorio.
    return (
        f"a mesma chave devolveu a transacao {primeira.get('id')} duas vezes "
        "(a janela de 5 min do fornecedor nao e medida aqui)"
    )


def ensaio_10_callback_do_opg(ctx: Contexto) -> str:
    caminho, bruto, cabecalhos = ctx.receptor.esperar("opg")
    ctx.cabecalhos_do_opg = cabecalhos
    exigir(bool(bruto), f"o callback do OPG chegou a {caminho} com corpo vazio")
    carga = json.loads(bruto.decode("utf-8"))
    exigir(
        carga.get("status") in ("accepted", "rejected"),
        f"o callback do OPG nao traz `status`: {carga}",
    )
    # **Nao se afirma nada sobre assinatura.** Lista-se o que veio, e quem le
    # decide. Um ensaio que exigisse a ausencia de assinatura media a escolha do
    # nosso mock; um que exigisse a presenca media uma coisa que ninguem
    # verificou. A resposta e a pergunta 8 do `E2` §9.
    nomes = sorted(k for k in cabecalhos if k.lower() not in ("host", "content-length", "accept-encoding"))
    candidatos = [k for k in nomes if "sign" in k.lower() or "hmac" in k.lower() or "hash" in k.lower()]
    return (
        f"callback do OPG recebido em {caminho}; cabecalhos registados: {nomes}; "
        f"com aparencia de assinatura: {candidatos or 'nenhum'} "
        "(contra o MOCK: nao diz nada sobre a ProxyPay — pergunta 8 do E2 §9)"
    )


ENSAIOS = (
    (1, "referencia por PUT, e o mesmo id nao cria uma segunda", ensaio_1_referencia),
    (2, "limites do `amount` do API (0,01 a 99.999.999,99)", ensaio_2_limites_do_amount),
    (3, "pagamento simulado copia os `custom_fields`", ensaio_3_pagamento_simulado),
    (4, "o evento traz os seis campos de conciliacao, `fee` incluido", ensaio_4_campos_de_conciliacao),
    (5, "fila de seguranca: GET lista, DELETE remove so o nosso", ensaio_5_fila_de_seguranca),
    (6, "webhook RPS assinado sobre o corpo bruto, com a API key", ensaio_6_webhook_assinado),
    (7, "dois esquemas de auth, e nao intercambiaveis", ensaio_7_dois_esquemas_de_auth),
    (8, "OPG: os tres numeros de ensaio e o quarto desfecho", ensaio_8_opg_tres_numeros),
    (9, "OPG: a mesma Idempotency-Key da uma transacao", ensaio_9_idempotency_key),
    (10, "INSTRUMENTO: o callback do OPG chegou e os cabecalhos ficaram", ensaio_10_callback_do_opg),
)


# -- corrida ------------------------------------------------------------------


def correr(
    base: str,
    api_key: str,
    opg_token: str,
    registar_webhook: bool,
    silencioso: bool = False,
) -> dict[int, str | None]:
    """Corre os dez ensaios. Devolve `{numero: None se verde, mensagem se vermelho}`."""
    resultado: dict[int, str | None] = {}
    with Receptor() as receptor:
        if registar_webhook:
            codigo, corpo = _chamar(base, "POST", "/_mock/webhook", {"url": receptor.url_rps})
            if codigo != 201:
                raise SystemExit(
                    f"registo do webhook falhou ({codigo}): {corpo}\n"
                    "Se o alvo e a ProxyPay, esta rota nao existe: a URL de callback do RPS "
                    "configura-se no portal, e este cliente nao fala o contrato do fornecedor "
                    "— ver o §8.3 do relatorio."
                )
        ctx = Contexto(base=base, receptor=receptor, api_key=api_key, opg_token=opg_token)

        for numero, titulo, funcao in ENSAIOS:
            try:
                detalhe = funcao(ctx)
            except Reprovado as reprovado:
                resultado[numero] = str(reprovado)
                if not silencioso:
                    print(f"  VERMELHO  {numero}. {titulo}")
                    print(f"            {reprovado}")
            else:
                resultado[numero] = None
                if not silencioso:
                    print(f"  verde     {numero}. {titulo}")
                    print(f"            {detalhe}")
    return resultado


def canario() -> int:
    """Estraga o mock de catorze maneiras e exige que o ensaio certo avermelhe."""
    print(f"canario: {len(DEFEITOS)} defeitos, e o ensaio que cada um tem de avermelhar\n")
    falhas = []
    for defeito in DEFEITOS:
        esperado = CANARIO[defeito]
        with Provedor(defeitos={defeito}) as provedor:
            resultado = correr(
                provedor.base, provedor.api_key, provedor.opg_token, True, silencioso=True
            )
        vermelhos = sorted(n for n, m in resultado.items() if m is not None)
        if esperado in vermelhos:
            print(f"  ok     {defeito}: ensaio {esperado} vermelho")
            print(f"         {resultado[esperado]}")
        else:
            falhas.append(defeito)
            print(f"  FALHA  {defeito}: ensaio {esperado} ficou **verde**; vermelhos: {vermelhos or 'nenhum'}")

    print()
    if falhas:
        print(f"canario: {len(falhas)} defeito(s) sem ensaio que os apanhe: {', '.join(falhas)}")
        return 1
    print(
        f"canario: {len(DEFEITOS)} defeitos, {len(DEFEITOS)} vermelhos — cada ensaio reprova "
        "quando o seu predicado desaparece"
    )
    print("O que isto nao prova: que a lista de defeitos esgota as maneiras de quebrar o contrato.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base", help="base URL do alvo; por omissao arranca o mock local")
    parser.add_argument("--canario", action="store_true", help="prova que cada ensaio reprova quando deve")
    args = parser.parse_args(argv)

    if args.canario:
        if args.base:
            parser.error("o canario precisa do mock: nao se estraga o sandbox de um fornecedor")
        return canario()

    if args.base:
        api_key = os.environ.get("PROXYPAY_API_KEY", "")
        opg_token = os.environ.get("PROXYPAY_OPG_TOKEN", "")
        if not api_key or not opg_token:
            raise SystemExit(
                "faltam PROXYPAY_API_KEY e/ou PROXYPAY_OPG_TOKEN no ambiente.\n"
                "As chaves de sandbox pedem-se a TimeBoxed, e pedir chaves e contacto com "
                "contraparte: e acto do fundador. Ver o §11 do relatorio."
            )
        print(f"ensaio contra {args.base}")
        print("aviso: este cliente fala o contrato do mock, nao o da ProxyPay (ver §8.3)\n")
        resultado = correr(args.base, api_key, opg_token, registar_webhook=False)
    else:
        print("ensaio contra o mock local (`provedor_mock.py`)\n")
        with Provedor() as provedor:
            resultado = correr(provedor.base, provedor.api_key, provedor.opg_token, True)

    vermelhos = [n for n, m in resultado.items() if m is not None]
    print()
    if vermelhos:
        print(f"{len(vermelhos)} de {len(ENSAIOS)} predicados vermelhos: {vermelhos}")
        return 1
    print(f"{len(ENSAIOS)} de {len(ENSAIOS)} predicados verdes")
    print("Isto mede o instrumento, nao a ProxyPay: um mock passa nos ensaios de quem o escreveu.")
    print("E o ensaio 10 e instrumento, nao predicado — se o callback do OPG e assinado")
    print("continua NAO VERIFICADO, e fecha-se com a resposta escrita (pergunta 8 do E2 §9).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
