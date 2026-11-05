"""Ensaio de `sandbox` do KAM-126: os sete predicados do criterio 4.

Corre contra **qualquer** base URL que fale o contrato do
`provedor_mock.py`. Por omissao corre contra o mock, que e o que o ticket
exige: *o script corre contra um mock antes de tocar no fornecedor*.

    python spikes/factura-ai/sandbox.py              # contra o mock
    python spikes/factura-ai/sandbox.py --canario    # prova que os ensaios reprovam
    python spikes/factura-ai/sandbox.py --base URL   # contra um fornecedor real

Os sete predicados, do criterio 4 do bloco KAM-126:

1. criar organizacao (uma por PME)
2. emitir factura
3. emitir proforma, **sem** numeracao fiscal e com o rotulo do E5 B10
4. emitir nota de credito sobre a factura, e **recusar** uma sem origem
5. repetir com a mesma `idempotencyKey` 2x -> **um** documento
6. verificar a assinatura do `webhook`, e **recusar** uma invalida
7. o `sandbox` **nao** submete a AGT

**Dados sinteticos, sem NIF reais.** Os NIFs tem a forma `SINTETICO-<n>`, que
nao e a de um NIF angolano, para que nenhum possa coincidir com um contribuinte
real. Nenhuma chave vive em ficheiro: o segredo do `webhook` e gerado pelo
provedor em cada arranque e entregue no registo.

Nao e codigo de producao e nao e um portao. Biblioteca padrao do Python.
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
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from provedor_mock import DEFEITOS, ROTULO_PROFORMA, Provedor  # noqa: E402

#: Que ensaio tem de ficar vermelho com cada defeito. E o nucleo do canario: um
#: ensaio que nao reprova quando devia nao e evidencia.
CANARIO = {
    "idempotencia-ignorada": 5,
    "assinatura-de-outro-corpo": 6,
    "segredo-errado": 6,
    "proforma-numerada": 3,
    "nota-sem-origem": 4,
    "sandbox-submete": 7,
}


class Reprovado(Exception):
    """Um predicado nao se verificou."""


def exigir(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise Reprovado(mensagem)


# -- cliente HTTP -------------------------------------------------------------


def _chamar(base: str, metodo: str, rota: str, carga: dict | None = None) -> tuple[int, dict]:
    bruto = json.dumps(carga, ensure_ascii=False).encode("utf-8") if carga is not None else None
    pedido = urllib.request.Request(
        base.rstrip("/") + rota,
        data=bruto,
        headers={"Content-Type": "application/json"},
        method=metodo,
    )
    try:
        with urllib.request.urlopen(pedido, timeout=10) as resposta:
            return resposta.status, json.loads(resposta.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as erro:
        texto = erro.read().decode("utf-8") or "{}"
        try:
            return erro.code, json.loads(texto)
        except json.JSONDecodeError:
            return erro.code, {"erro": texto}


# -- receptor de `webhook` ----------------------------------------------------


class Receptor:
    """Um servidor HTTP minimo que recebe o `webhook` e guarda o que chegou.

    Guarda o corpo **em bruto**, porque a assinatura e sobre os bytes que
    viajaram: verificar sobre um JSON reserializado mediria outra coisa.
    """

    def __init__(self) -> None:
        self.recebidos: queue.Queue[tuple[bytes, str]] = queue.Queue()
        receptor = self

        class _H(BaseHTTPRequestHandler):
            def log_message(self, *_a) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                tamanho = int(self.headers.get("Content-Length") or 0)
                bruto = self.rfile.read(tamanho)
                receptor.recebidos.put((bruto, self.headers.get("X-Mock-Signature", "")))
                self.send_response(204)
                self.end_headers()

        self._servidor = ThreadingHTTPServer(("127.0.0.1", 0), _H)
        self._fio = threading.Thread(target=self._servidor.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._servidor.server_address[1]}/webhook"

    def __enter__(self) -> Receptor:
        self._fio.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._servidor.shutdown()
        self._servidor.server_close()
        self._fio.join(timeout=5)

    def esperar(self, segundos: float = 10.0) -> tuple[bytes, str]:
        try:
            return self.recebidos.get(timeout=segundos)
        except queue.Empty as vazio:
            raise Reprovado("nenhum `webhook` chegou dentro do prazo") from vazio


# -- os sete ensaios ----------------------------------------------------------


@dataclass
class Contexto:
    base: str
    receptor: Receptor
    segredo: str
    org: str = ""
    factura: str = ""


def ensaio_1_organizacao(ctx: Contexto) -> str:
    codigo, corpo = _chamar(
        ctx.base, "POST", "/v1/organisations", {"nif": "SINTETICO-0001", "nome": "Loja Sintetica Um"}
    )
    exigir(codigo == 201, f"criar organizacao devolveu {codigo}: {corpo}")
    exigir(bool(corpo.get("id")), "organizacao sem identificador")
    ctx.org = corpo["id"]

    # Uma organizacao por PME: a segunda PME tem de ter identificador distinto.
    codigo2, corpo2 = _chamar(
        ctx.base, "POST", "/v1/organisations", {"nif": "SINTETICO-0002", "nome": "Loja Sintetica Dois"}
    )
    exigir(codigo2 == 201, f"segunda organizacao devolveu {codigo2}: {corpo2}")
    exigir(corpo2["id"] != corpo["id"], "duas PMEs com o mesmo identificador de organizacao")
    return f"organizacoes {corpo['id']} e {corpo2['id']}, NIFs sinteticos"


def ensaio_2_factura(ctx: Contexto) -> str:
    codigo, corpo = _chamar(
        ctx.base,
        "POST",
        f"/v1/organisations/{ctx.org}/documents",
        {"tipo": "factura", "total": 15000, "moeda": "AOA", "idempotencyKey": "chave-factura-1"},
    )
    exigir(codigo == 201, f"emitir factura devolveu {codigo}: {corpo}")
    exigir(corpo.get("tipo") == "factura", f"tipo devolvido: {corpo.get('tipo')!r}")
    exigir(bool(corpo.get("numero_fiscal")), "factura sem numeracao fiscal")
    ctx.factura = corpo["id"]
    return f"factura {corpo['id']}, numero {corpo['numero_fiscal']}"


def ensaio_3_proforma(ctx: Contexto) -> str:
    codigo, corpo = _chamar(
        ctx.base,
        "POST",
        f"/v1/organisations/{ctx.org}/documents",
        {"tipo": "proforma", "total": 15000, "idempotencyKey": "chave-proforma-1"},
    )
    exigir(codigo == 201, f"emitir proforma devolveu {codigo}: {corpo}")
    # O predicado nao e «a proforma existe»: e «a proforma nao se confunde com
    # um documento fiscal», que e o risco B10 do E5.
    exigir(
        corpo.get("numero_fiscal") is None,
        f"proforma com numeracao fiscal {corpo.get('numero_fiscal')!r} — confunde-se com factura (E5 B10)",
    )
    exigir(
        corpo.get("rotulo") == ROTULO_PROFORMA,
        f"proforma sem o rotulo exigido pelo E5 B10: {corpo.get('rotulo')!r}",
    )
    return f"proforma {corpo['id']}, sem numero fiscal, rotulada"


def ensaio_4_nota_credito(ctx: Contexto) -> str:
    codigo, corpo = _chamar(
        ctx.base,
        "POST",
        f"/v1/organisations/{ctx.org}/documents",
        {
            "tipo": "nota_credito",
            "total": -15000,
            "documento_origem": ctx.factura,
            "idempotencyKey": "chave-nota-1",
        },
    )
    exigir(codigo == 201, f"emitir nota de credito devolveu {codigo}: {corpo}")
    exigir(corpo.get("documento_origem") == ctx.factura, "nota de credito sem ligacao a factura de origem")

    # A metade negativa. Sem ela, um provedor que aceitasse notas soltas passava
    # o ensaio, e uma nota de credito sem origem nao e rastreavel pela AGT.
    codigo2, corpo2 = _chamar(
        ctx.base,
        "POST",
        f"/v1/organisations/{ctx.org}/documents",
        {"tipo": "nota_credito", "total": -500, "idempotencyKey": "chave-nota-orfa"},
    )
    exigir(
        codigo2 >= 400,
        f"nota de credito **sem** documento de origem foi aceite com {codigo2}: {corpo2}",
    )
    return f"nota {corpo['id']} sobre {ctx.factura}; nota orfa recusada com {codigo2}"


def ensaio_5_idempotencia(ctx: Contexto) -> str:
    carga = {"tipo": "factura", "total": 22000, "idempotencyKey": "chave-repetida"}
    rota = f"/v1/organisations/{ctx.org}/documents"
    codigo_a, primeiro = _chamar(ctx.base, "POST", rota, carga)
    codigo_b, segundo = _chamar(ctx.base, "POST", rota, carga)
    exigir(codigo_a == 201, f"primeira emissao devolveu {codigo_a}: {primeiro}")
    exigir(codigo_b < 400, f"segunda emissao devolveu {codigo_b}: {segundo}")
    exigir(
        primeiro.get("id") == segundo.get("id"),
        f"duas chamadas com a mesma idempotencyKey deram documentos distintos: "
        f"{primeiro.get('id')!r} e {segundo.get('id')!r}",
    )
    return f"2 chamadas, 1 documento ({primeiro['id']}); codigos {codigo_a} e {codigo_b}"


def ensaio_6_webhook(ctx: Contexto) -> str:
    bruto, cabecalho = ctx.receptor.esperar()
    exigir(cabecalho.startswith("sha256="), f"cabecalho de assinatura inesperado: {cabecalho!r}")
    recebida = cabecalho.split("=", 1)[1]
    esperada = hmac.new(ctx.segredo.encode("utf-8"), bruto, hashlib.sha256).hexdigest()
    exigir(
        hmac.compare_digest(recebida, esperada),
        "assinatura do `webhook` nao corresponde ao HMAC-SHA256 do corpo recebido",
    )
    carga = json.loads(bruto.decode("utf-8"))
    exigir(carga.get("evento") == "invoice.issued", f"evento inesperado: {carga.get('evento')!r}")

    # A metade negativa: um corpo alterado com a mesma assinatura tem de falhar.
    # Sem ela, uma verificacao que devolvesse sempre True passava o ensaio.
    adulterado = bruto + b" "
    exigir(
        not hmac.compare_digest(
            recebida, hmac.new(ctx.segredo.encode("utf-8"), adulterado, hashlib.sha256).hexdigest()
        ),
        "a verificacao aceita um corpo adulterado",
    )
    return "assinatura HMAC-SHA256 confere; corpo adulterado recusado"


def ensaio_7_sem_submissao(ctx: Contexto) -> str:
    codigo, corpo = _chamar(ctx.base, "GET", f"/v1/documents/{ctx.factura}")
    exigir(codigo == 200, f"consulta do documento devolveu {codigo}: {corpo}")
    exigir(corpo.get("ambiente") == "sandbox", f"ambiente devolvido: {corpo.get('ambiente')!r}")
    exigir(
        corpo.get("submetido_agt") is False,
        f"o ambiente de teste declara submissao a AGT: submetido_agt={corpo.get('submetido_agt')!r}",
    )
    return "ambiente sandbox, submetido_agt=False"


ENSAIOS = (
    (1, "criar organizacao (uma por PME)", ensaio_1_organizacao),
    (2, "emitir factura", ensaio_2_factura),
    (3, "emitir proforma sem numeracao fiscal", ensaio_3_proforma),
    (4, "emitir nota de credito sobre a factura", ensaio_4_nota_credito),
    (5, "mesma idempotencyKey 2x -> 1 documento", ensaio_5_idempotencia),
    (6, "assinatura do webhook verificada", ensaio_6_webhook),
    (7, "sandbox nao submete a AGT", ensaio_7_sem_submissao),
)


# -- corrida ------------------------------------------------------------------


def correr(base: str, silencioso: bool = False) -> dict[int, str | None]:
    """Corre os sete ensaios. Devolve {numero: None se verde, mensagem se vermelho}."""
    resultado: dict[int, str | None] = {}
    with Receptor() as receptor:
        codigo, corpo = _chamar(base, "POST", "/v1/webhooks", {"url": receptor.url})
        if codigo != 201 or not corpo.get("segredo"):
            raise SystemExit(f"registo do webhook falhou ({codigo}): {corpo}")
        ctx = Contexto(base=base, receptor=receptor, segredo=corpo["segredo"])

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
    """Estraga o mock de seis maneiras e exige que o ensaio certo fique vermelho."""
    print("canario: seis defeitos, e o ensaio que cada um tem de avermelhar\n")
    falhas = []
    for defeito in DEFEITOS:
        esperado = CANARIO[defeito]
        with Provedor(defeitos={defeito}) as provedor:
            resultado = correr(provedor.base, silencioso=True)
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
    print(f"canario: {len(DEFEITOS)} defeitos, {len(DEFEITOS)} vermelhos — os ensaios medem o que dizem medir")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", help="base URL do provedor; por omissao arranca o mock local")
    parser.add_argument("--canario", action="store_true", help="prova que cada ensaio reprova quando deve")
    args = parser.parse_args(argv)

    if args.canario:
        if args.base:
            parser.error("o canario precisa do mock: nao se estraga o sandbox de um fornecedor")
        return canario()

    if args.base:
        print(f"ensaio contra {args.base}\n")
        resultado = correr(args.base)
    else:
        print("ensaio contra o mock local (`provedor_mock.py`)\n")
        with Provedor() as provedor:
            resultado = correr(provedor.base)

    vermelhos = [n for n, m in resultado.items() if m is not None]
    print()
    if vermelhos:
        print(f"{len(vermelhos)} de {len(ENSAIOS)} predicados vermelhos: {vermelhos}")
        return 1
    print(f"{len(ENSAIOS)} de {len(ENSAIOS)} predicados verdes")
    print("Isto mede o instrumento, nao um fornecedor: um mock passa nos ensaios de quem o escreveu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
