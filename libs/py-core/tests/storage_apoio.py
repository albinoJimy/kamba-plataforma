"""Apoio as suites de armazenamento (KAM-011): relogio, servidor S3 em memoria e
os alvos da bateria de contrato. Espelho de `packages/core-ts/tests/apoio/`.

O servidor em memoria existe para que o `MotorS3` **inteiro** — assinatura, XML,
envio em partes, paginacao, traducao de erros — corra no *gate* 4, sem
contentor. Nao substitui a prova contra um servidor real: confere as assinaturas
com a mesma funcao que as produz, pelo que apanha um cabecalho por assinar ou
uma URL adulterada, e **nao** apanha um erro de canonicalizacao que os dois
lados partilhem. Essa prova e a de `tests/integracao/`, contra o SeaweedFS.

Implementa o subconjunto que `kamba_core/storage/s3.py` usa, e recusa o resto
com 501.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, unquote, urlsplit

from kamba_core.storage.config import (
    DestinoDeArmazenamento,
    StorageConfig,
    criar_storage_s3,
)
from kamba_core.storage.fake import criar_storage_fake
from kamba_core.storage.port import StorageProvider
from kamba_core.storage.s3 import PedidoHttp, RespostaHttp
from kamba_core.storage.sigv4 import (
    CORPO_NAO_ASSINADO,
    Credenciais,
    anfitriao,
    assinatura,
    sha256_hex,
)

_PARTE_MINIMA = 5 * 1024 * 1024


class Relogio:
    """Um relogio que so anda quando lhe mandam."""

    def __init__(self, inicio: str = "2026-10-12T09:00:00+00:00") -> None:
        self._agora = datetime.fromisoformat(inicio)

    def agora(self) -> datetime:
        return self._agora

    def avancar(self, segundos: float) -> None:
        self._agora += timedelta(seconds=segundos)


#: Valores de teste, com forma que nao se confunde com uma chave real.
CREDENCIAIS_DE_TESTE = Credenciais("chave-de-teste", "valor-de-teste")

CONFIG_DE_TESTE = StorageConfig(
    endpoint="http://s3.teste.invalid:8333",
    bucket="kamba-teste",
    regiao="ao-teste-1",
    destino=DestinoDeArmazenamento(country="AO", provider="seaweedfs_teste", apd_ref=None),
)


class CofreDeTeste:
    """Um cofre de teste: devolve os dois valores e regista os pedidos."""

    def __init__(self, valores: dict[str, str] | None = None) -> None:
        self.valores = valores or {
            "storage_access_key_id": CREDENCIAIS_DE_TESTE.access_key_id,
            "storage_secret_access_key": CREDENCIAIS_DE_TESTE.secret_access_key,
        }
        self.pedidos: list[str] = []

    def get(self, ref: str) -> str:
        self.pedidos.append(ref)
        return self.valores[ref]


def _xml(estado: int, corpo: str, cabecalhos: dict[str, str] | None = None) -> RespostaHttp:
    return RespostaHttp(
        estado=estado,
        cabecalhos={"content-type": "application/xml", **(cabecalhos or {})},
        corpo=(f'<?xml version="1.0" encoding="UTF-8"?>{corpo}'.encode(),),
    )


def _erro(estado: int, codigo: str) -> RespostaHttp:
    return _xml(estado, f"<Error><Code>{codigo}</Code><Message>{codigo}</Message></Error>")


def _etag(dados: bytes) -> str:
    return f'"{hashlib.md5(dados, usedforsecurity=False).hexdigest()}"'


def _quando(amz: str) -> datetime | None:
    try:
        return datetime.strptime(amz, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


_AUTORIZACAO = re.compile(
    r"AWS4-HMAC-SHA256 Credential=([^/]+)/\S+, SignedHeaders=(\S+), Signature=([0-9a-f]+)"
)
_PARTE = re.compile(r"<Part><PartNumber>(\d+)</PartNumber><ETag>([^<]*)</ETag></Part>")


@dataclass
class _Envio:
    chave: str
    cabecalhos: dict[str, str]
    partes: dict[int, tuple[bytes, str]] = field(default_factory=dict)


class S3EmMemoria:
    """Um servidor S3 em memoria. `transporte` e o que se da ao `MotorS3`."""

    def __init__(
        self,
        *,
        bucket: str,
        regiao: str,
        credenciais: Credenciais,
        agora: Callable[[], datetime],
        pagina: int = 1000,
    ) -> None:
        self.bucket = bucket
        self.regiao = regiao
        self.credenciais = credenciais
        self.agora = agora
        self.pagina = pagina
        self.objectos: dict[str, tuple[bytes, dict[str, str]]] = {}
        self.envios: dict[str, _Envio] = {}
        #: Todos os pedidos recebidos, pela ordem.
        self.pedidos: list[PedidoHttp] = []
        #: Gancho de falha: se devolver uma resposta, e essa que o pedido
        #: recebe; se levantar, o pedido falha como falha a rede.
        self.interceptar: Callable[[PedidoHttp], RespostaHttp | None] | None = None

    def transporte(self, pedido: PedidoHttp) -> RespostaHttp:
        self.pedidos.append(pedido)
        if self.interceptar is not None:
            forcada = self.interceptar(pedido)
            if forcada is not None:
                return forcada
        return self._servir(pedido)

    def buscar(self, url: str) -> tuple[int, bytes]:
        """`GET` sem credenciais nenhumas, como um cliente a quem deram uma URL."""
        resposta = self.transporte(PedidoHttp("GET", url, {}))
        return resposta.estado, b"".join(resposta.corpo)

    def _autenticado(self, pedido: PedidoHttp, query: list[tuple[str, str]]) -> RespostaHttp | None:
        agora = self.agora()
        corpo = pedido.corpo or b""
        parametros = dict(query)
        host = anfitriao(pedido.url)

        if "X-Amz-Signature" in parametros:
            data = parametros.get("X-Amz-Date", "")
            esperada, _ = assinatura(
                metodo=pedido.metodo,
                url=pedido.url,
                cabecalhos={"host": host},
                hash_do_corpo=CORPO_NAO_ASSINADO,
                regiao=self.regiao,
                quando=data,
                segredo=self.credenciais.secret_access_key,
                query=[(n, v) for n, v in query if n != "X-Amz-Signature"],
            )
            if parametros["X-Amz-Signature"] != esperada:
                return _erro(403, "SignatureDoesNotMatch")
            inicio = _quando(data)
            expira = parametros.get("X-Amz-Expires", "")
            if inicio is None or not expira.isdigit():
                return _erro(403, "AccessDenied")
            if agora >= inicio + timedelta(seconds=int(expira)):
                return _erro(403, "AccessDenied")
            return None

        m = _AUTORIZACAO.fullmatch(pedido.cabecalhos.get("authorization", ""))
        if m is None:
            return _erro(403, "AccessDenied")
        if m.group(1) != self.credenciais.access_key_id:
            return _erro(403, "InvalidAccessKeyId")
        data = pedido.cabecalhos.get("x-amz-date", "")
        inicio = _quando(data)
        if inicio is None or abs((agora - inicio).total_seconds()) > 15 * 60:
            return _erro(403, "RequestTimeTooSkewed")
        hash_do_corpo = pedido.cabecalhos.get("x-amz-content-sha256", "")
        if hash_do_corpo != sha256_hex(corpo):
            return _erro(400, "XAmzContentSHA256Mismatch")
        assinados: dict[str, str] = {}
        for nome in m.group(2).split(";"):
            valor = host if nome == "host" else pedido.cabecalhos.get(nome)
            if valor is None:
                return _erro(403, "SignatureDoesNotMatch")
            assinados[nome] = valor
        # Todo o cabecalho de metadados tem de estar assinado.
        for nome in pedido.cabecalhos:
            if nome.startswith("x-amz-meta-") and nome not in assinados:
                return _erro(403, "SignatureDoesNotMatch")
        esperada, _ = assinatura(
            metodo=pedido.metodo,
            url=pedido.url,
            cabecalhos=assinados,
            hash_do_corpo=hash_do_corpo,
            regiao=self.regiao,
            quando=data,
            segredo=self.credenciais.secret_access_key,
        )
        return None if m.group(3) == esperada else _erro(403, "SignatureDoesNotMatch")

    def _servir(self, pedido: PedidoHttp) -> RespostaHttp:  # noqa: PLR0911, PLR0912
        partes = urlsplit(pedido.url)
        query = parse_qsl(partes.query, keep_blank_values=True)
        recusa = self._autenticado(pedido, query)
        if recusa is not None:
            return recusa

        segmentos = partes.path.split("/")
        bucket = segmentos[1] if len(segmentos) > 1 else ""
        if bucket != self.bucket:
            return _erro(404, "NoSuchBucket")
        chave = "/".join(unquote(s) for s in segmentos[2:])
        q = dict(query)
        corpo = pedido.corpo or b""
        vazia = RespostaHttp

        if chave == "":
            if pedido.metodo == "GET" and q.get("list-type") == "2":
                return self._listar(q)
            return _erro(501, "NotImplemented")

        if pedido.metodo == "POST" and "uploads" in q:
            identificador = str(uuid.uuid4())
            self.envios[identificador] = _Envio(chave, dict(pedido.cabecalhos))
            return _xml(
                200,
                f"<InitiateMultipartUploadResult><Bucket>{bucket}</Bucket><Key>{chave}</Key>"
                f"<UploadId>{identificador}</UploadId></InitiateMultipartUploadResult>",
            )
        if "uploadId" in q:
            envio = self.envios.get(q["uploadId"])
            if envio is None or envio.chave != chave:
                return _erro(404, "NoSuchUpload")
            if pedido.metodo == "PUT" and "partNumber" in q:
                etag = _etag(corpo)
                envio.partes[int(q["partNumber"])] = (corpo, etag)
                return vazia(200, {"etag": etag})
            if pedido.metodo == "DELETE":
                del self.envios[q["uploadId"]]
                return vazia(204)
            if pedido.metodo == "POST":
                pedidas = _PARTE.findall(corpo.decode())
                blocos: list[bytes] = []
                for i, (numero, etag) in enumerate(pedidas):
                    parte = envio.partes.get(int(numero))
                    if parte is None or parte[1] != etag.replace("&quot;", '"'):
                        return _erro(400, "InvalidPart")
                    if i < len(pedidas) - 1 and len(parte[0]) < _PARTE_MINIMA:
                        return _erro(400, "EntityTooSmall")
                    blocos.append(parte[0])
                if not blocos:
                    return _erro(400, "MalformedXML")
                del self.envios[q["uploadId"]]
                self.objectos[chave] = (b"".join(blocos), envio.cabecalhos)
                return _xml(
                    200,
                    f"<CompleteMultipartUploadResult><Key>{chave}</Key>"
                    "</CompleteMultipartUploadResult>",
                )
            return _erro(501, "NotImplemented")

        if pedido.metodo == "PUT":
            self.objectos[chave] = (corpo, dict(pedido.cabecalhos))
            return vazia(200, {"etag": _etag(corpo)})
        if pedido.metodo in ("GET", "HEAD"):
            objecto = self.objectos.get(chave)
            if objecto is None:
                return vazia(404) if pedido.metodo == "HEAD" else _erro(404, "NoSuchKey")
            dados, guardados = objecto
            cabecalhos = {
                "content-length": str(len(dados)),
                "content-type": guardados.get("content-type", "application/octet-stream"),
            }
            cabecalhos.update(
                (n, v) for n, v in guardados.items() if n.startswith("x-amz-meta-")
            )
            return RespostaHttp(200, cabecalhos, () if pedido.metodo == "HEAD" else (dados,))
        if pedido.metodo == "DELETE":
            self.objectos.pop(chave, None)
            return vazia(204)
        return _erro(501, "NotImplemented")

    def _listar(self, q: dict[str, str]) -> RespostaHttp:
        prefixo = q.get("prefix", "")
        pedidas = min(int(q.get("max-keys", "1000")), self.pagina)
        depois = q.get("continuation-token")
        chaves = sorted(
            c
            for c in self.objectos
            if c.startswith(prefixo) and (depois is None or c > depois)
        )
        pagina = chaves[:pedidas]
        truncada = len(chaves) > len(pagina)
        return _xml(
            200,
            f"<ListBucketResult><Name>{self.bucket}</Name><Prefix>{prefixo}</Prefix>"
            f"<KeyCount>{len(pagina)}</KeyCount>"
            f"<IsTruncated>{'true' if truncada else 'false'}</IsTruncated>"
            + "".join(
                f"<Contents><Key>{c}</Key><Size>{len(self.objectos[c][0])}</Size></Contents>"
                for c in pagina
            )
            + (
                f"<NextContinuationToken>{pagina[-1]}</NextContinuationToken>"
                if truncada
                else ""
            )
            + "</ListBucketResult>",
        )


@dataclass
class Alvo:
    """Uma implementacao sob teste."""

    storage: StorageProvider
    #: `GET` de uma URL assinada, sem mais credencial nenhuma: `(estado, corpo)`.
    buscar: Callable[[str], tuple[int, bytes]]
    #: Faz passar `segundos`. Num alvo com relogio injectado e instantaneo; num
    #: servidor real **espera-se**.
    avancar: Callable[[float], None]


def alvo_fake() -> Alvo:
    relogio = Relogio()
    fake = criar_storage_fake(relogio.agora)

    def buscar(url: str) -> tuple[int, bytes]:
        resposta = fake.buscar(url)
        return resposta.estado, resposta.corpo

    return Alvo(storage=fake.storage, buscar=buscar, avancar=relogio.avancar)


def montar_s3_em_memoria(
    *, pagina: int = 1000, tamanho_da_parte: int | None = None
) -> tuple[Alvo, S3EmMemoria, Relogio]:
    """O motor S3 sobre um servidor em memoria, e o servidor para quem o quer espiar."""
    relogio = Relogio()
    servidor = S3EmMemoria(
        bucket=CONFIG_DE_TESTE.bucket,
        regiao=CONFIG_DE_TESTE.regiao,
        credenciais=CREDENCIAIS_DE_TESTE,
        agora=relogio.agora,
        pagina=pagina,
    )
    extra = {} if tamanho_da_parte is None else {"tamanho_da_parte": tamanho_da_parte}
    storage = criar_storage_s3(
        config=CONFIG_DE_TESTE,
        secrets=CofreDeTeste(),
        transporte=servidor.transporte,
        agora=relogio.agora,
        **extra,
    )
    return Alvo(storage=storage, buscar=servidor.buscar, avancar=relogio.avancar), servidor, relogio


def alvo_s3_em_memoria() -> Alvo:
    return montar_s3_em_memoria()[0]
