"""Mock de um provedor de facturacao electronica certificado pela AGT.

Nao e um cliente de fornecedor nenhum: e o **alvo** contra o qual o
`sandbox.py` se mede antes de tocar em fornecedor. Implementa a forma do
contrato que o `docs/tecnica/evidencia/validacao/KAM-126_Factura_AI.md` §4
descreve a partir da documentacao publica da Vero (INDICIO) — organizacoes,
documentos com chave de idempotencia, e `webhook` assinado com HMAC-SHA256.

**Este contrato e inventado.** As rotas, os nomes de campo e o cabecalho de
assinatura sao deste mock, nao da Vero: o `E2` §6.2 documenta
`POST /v1/organisations/{ORG_ID}/invoices` e `X-Vero-Signature`, e exige um
`Bearer`. Apontar o `sandbox.py` a um fornecedor real **nao e mudar o alvo**:
e adaptar o cliente. Esta escrito no §5.3 do relatorio, com credor.

**O mock esta escrito para poder reprovar.** A idempotencia guarda de facto a
chave **por organizacao**; a assinatura calcula-se de facto sobre o corpo que
viaja. Um falso que decidisse pelo nome do ensaio ficava verde com a
implementacao apagada, e nao mediria predicado nenhum. Por isso tambem aceita
**defeitos** injectados (`DEFEITOS`), que o canario do `sandbox.py` usa para
exigir que cada ensaio fique vermelho quando o predicado deixa de valer.

Nao e codigo de producao, nao e um portao, e nao entra na `main` como
biblioteca. Biblioteca padrao do Python, sem dependencias.
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

#: Os defeitos que o canario injecta. Cada um apaga **um** predicado, e o
#: ensaio correspondente do `sandbox.py` tem de ficar vermelho por causa dele.
#:
#: Os quatro ultimos nasceram da revisao adversarial do KAM-126: sem eles, o
#: canario provava que o instrumento apanha os defeitos que o autor escolheu,
#: e **nao** que os ensaios medem os predicados. Em particular, tres mutacoes
#: de multi-tenancy deixavam 7/7 verdes — a chave de idempotencia global entre
#: contribuintes, o `webhook` a notificar documento de outra organizacao, e
#: dois NIFs iguais a criar duas organizacoes.
DEFEITOS = (
    "idempotencia-ignorada",
    "idempotencia-global",
    "assinatura-de-outro-corpo",
    "segredo-errado",
    "webhook-de-outra-org",
    "proforma-numerada",
    "rotulo-errado",
    "nota-sem-origem",
    "nif-duplicado",
    "sandbox-submete",
)

#: Rotulo que o `E5` («Bloqueios e riscos», B10) exige num documento que nao e
#: factura. O `sandbox.py` **nao importa esta constante**: compara o rotulo
#: contra um predicado proprio, porque alvo e oraculo no mesmo literal nao
#: mediriam nada (achado 2 da revisao adversarial).
ROTULO_PROFORMA = "Orcamento — nao e factura"

#: O que o defeito `rotulo-errado` poe no lugar dele: um rotulo que declara a
#: proforma como documento fiscal valido, que e exactamente o risco B10.
ROTULO_ENGANOSO = "Factura fiscal — documento valido para a AGT"


@dataclass
class Estado:
    """O que o provedor guarda. Em memoria, porque e descartavel."""

    defeitos: frozenset[str] = frozenset()
    #: Segredo do `webhook`, gerado em cada arranque. Nunca em ficheiro.
    segredo: str = field(default_factory=lambda: secrets.token_hex(32))
    organizacoes: dict[str, dict] = field(default_factory=dict)
    #: NIF -> id da organizacao. Uma organizacao por PME.
    nifs: dict[str, str] = field(default_factory=dict)
    documentos: dict[str, dict] = field(default_factory=dict)
    #: (organizacao, chave de idempotencia) -> id do documento ja emitido.
    idempotencia: dict[tuple[str, str] | str, str] = field(default_factory=dict)
    callback: str | None = None
    proximo_numero: int = 1

    def tem(self, defeito: str) -> bool:
        return defeito in self.defeitos


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

    def _responder(self, codigo: int, carga: dict) -> None:
        bruto = json.dumps(carga, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(bruto)))
        self.end_headers()
        self.wfile.write(bruto)

    # -- rotas ----------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        estado = self.estado
        caminho = self.path.rstrip("/")
        try:
            corpo = self._corpo()
        except (ValueError, json.JSONDecodeError):
            self._responder(400, {"erro": "corpo nao e JSON"})
            return

        if caminho == "/v1/webhooks":
            estado.callback = corpo.get("url")
            self._responder(201, {"segredo": estado.segredo, "eventos": ["invoice.issued"]})
            return

        if caminho == "/v1/organisations":
            self._criar_organizacao(corpo)
            return

        partes = caminho.split("/")
        if len(partes) == 5 and partes[1] == "v1" and partes[2] == "organisations" and partes[4] == "documents":
            self._emitir(partes[3], corpo)
            return

        self._responder(404, {"erro": f"rota desconhecida: {caminho}"})

    def do_GET(self) -> None:  # noqa: N802
        caminho = self.path.rstrip("/")
        partes = caminho.split("/")
        if len(partes) == 4 and partes[1] == "v1" and partes[2] == "documents":
            doc = self.estado.documentos.get(partes[3])
            if doc is None:
                self._responder(404, {"erro": "documento desconhecido"})
                return
            self._responder(200, doc)
            return
        self._responder(404, {"erro": f"rota desconhecida: {caminho}"})

    # -- organizacoes ---------------------------------------------------------

    def _criar_organizacao(self, corpo: dict) -> None:
        estado = self.estado
        nif = corpo.get("nif", "")
        if not nif.startswith("SINTETICO-"):
            # O proprio mock recusa um NIF que nao seja declaradamente
            # sintetico. E a fronteira do ticket posta no instrumento.
            self._responder(422, {"erro": "NIF tem de ter a forma SINTETICO-<n>"})
            return

        # Uma organizacao por PME: o mesmo NIF duas vezes devolve a **mesma**
        # organizacao, com 200. O defeito `nif-duplicado` cria uma segunda, e o
        # ensaio 1 tem de o apanhar.
        if nif in estado.nifs and not estado.tem("nif-duplicado"):
            self._responder(200, {**estado.organizacoes[estado.nifs[nif]], "repetido": True})
            return

        org_id = f"org_{len(estado.organizacoes) + 1}"
        registo = {"id": org_id, "nif": nif, "nome": corpo.get("nome", "")}
        estado.organizacoes[org_id] = registo
        estado.nifs.setdefault(nif, org_id)
        self._responder(201, registo)

    # -- emissao --------------------------------------------------------------

    def _emitir(self, org_id: str, corpo: dict) -> None:
        estado = self.estado
        if org_id not in estado.organizacoes:
            self._responder(404, {"erro": "organizacao desconhecida"})
            return

        tipo = corpo.get("tipo")
        if tipo not in ("factura", "factura_recibo", "proforma", "nota_credito"):
            self._responder(422, {"erro": f"tipo invalido: {tipo!r}"})
            return

        chave = corpo.get("idempotencyKey") or self.headers.get("Idempotency-Key")
        if not chave:
            self._responder(422, {"erro": "idempotencyKey em falta"})
            return

        # Nota de credito exige documento de origem. O defeito `nota-sem-origem`
        # apaga esta exigencia, e o ensaio 4 tem de o apanhar.
        if tipo == "nota_credito" and not corpo.get("documento_origem"):
            if not estado.tem("nota-sem-origem"):
                self._responder(422, {"erro": "nota de credito exige documento_origem"})
                return

        # Idempotencia: a segunda chamada com a mesma chave devolve o **mesmo**
        # documento, com 200 em vez de 201. A chave e por organizacao -- duas
        # PMEs com a mesma chave sao dois documentos. Dois defeitos distintos a
        # quebram: `idempotencia-ignorada` emite sempre documento novo, e
        # `idempotencia-global` partilha a chave entre contribuintes.
        marca: tuple[str, str] | str = chave if estado.tem("idempotencia-global") else (org_id, chave)
        if marca in estado.idempotencia and not estado.tem("idempotencia-ignorada"):
            doc_id = estado.idempotencia[marca]
            self._responder(200, {**estado.documentos[doc_id], "repetido": True})
            return

        doc_id = f"doc_{len(estado.documentos) + 1}"
        numero = None
        if tipo in ("factura", "factura_recibo", "nota_credito") or estado.tem("proforma-numerada"):
            numero = f"FT SINTETICO/{estado.proximo_numero}"
            estado.proximo_numero += 1

        doc = {
            "id": doc_id,
            "organisation": org_id,
            "tipo": tipo,
            "numero_fiscal": numero,
            "total": corpo.get("total"),
            "moeda": corpo.get("moeda", "AOA"),
            "documento_origem": corpo.get("documento_origem"),
            "estado": "pendente",
            "ambiente": "sandbox",
            # O `sandbox` nao submete a AGT. O defeito `sandbox-submete` diz o
            # contrario, e o ensaio 7 tem de o apanhar. **E uma declaracao do
            # provedor, nao uma medicao** -- ver o ensaio 7 do `sandbox.py`.
            "submetido_agt": bool(estado.tem("sandbox-submete")),
            "idempotencyKey": chave,
        }
        if tipo == "proforma":
            # O rotulo do B10. O defeito `rotulo-errado` troca-o por um que
            # declara a proforma como documento fiscal, **sem** lhe dar numero:
            # isola o predicado do rotulo do predicado da numeracao.
            doc["rotulo"] = ROTULO_ENGANOSO if estado.tem("rotulo-errado") else ROTULO_PROFORMA
            if estado.tem("proforma-numerada"):
                doc.pop("rotulo")

        estado.documentos[doc_id] = doc
        estado.idempotencia[marca] = doc_id
        self._responder(201, doc)

        if tipo in ("factura", "factura_recibo"):
            self._disparar_webhook(doc)

    def _disparar_webhook(self, doc: dict) -> None:
        estado = self.estado
        if not estado.callback:
            return

        # O defeito `webhook-de-outra-org` notifica um documento que nao foi o
        # emitido, e de outra organizacao, **bem assinado**. Uma verificacao que
        # so olhe para a assinatura e para o nome do evento fica verde com ele.
        notificado = doc
        if estado.tem("webhook-de-outra-org"):
            notificado = {**doc, "id": "doc_INEXISTENTE", "organisation": "org_DE_OUTRA_PME"}

        carga = {"evento": "invoice.issued", "documento": notificado}
        bruto = json.dumps(carga, ensure_ascii=False).encode("utf-8")

        # A assinatura calcula-se sobre o corpo que viaja, com o segredo que foi
        # entregue no registo. Os dois defeitos abaixo quebram-na de maneiras
        # diferentes de proposito: assinar outro corpo e assinar com outro
        # segredo sao falhas distintas, e um unico ensaio podia cobrir so uma.
        assinado = bruto
        if estado.tem("assinatura-de-outro-corpo"):
            assinado = json.dumps({"evento": "invoice.issued"}, ensure_ascii=False).encode("utf-8")
        segredo = estado.segredo
        if estado.tem("segredo-errado"):
            segredo = secrets.token_hex(32)

        assinatura = hmac.new(segredo.encode("utf-8"), assinado, hashlib.sha256).hexdigest()
        pedido = urllib.request.Request(
            estado.callback,
            data=bruto,
            headers={"Content-Type": "application/json", "X-Mock-Signature": f"sha256={assinatura}"},
            method="POST",
        )
        try:
            urllib.request.urlopen(pedido, timeout=5).read()
        except (urllib.error.URLError, OSError):
            # O cliente pode ter fechado; o ensaio do `webhook` apanha-o pela
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

    def __enter__(self) -> Provedor:
        self._fio.start()
        return self

    def __exit__(self, *_exc) -> None:
        self._servidor.shutdown()
        self._servidor.server_close()
        self._fio.join(timeout=5)
