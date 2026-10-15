"""AWS Signature Version 4, o suficiente para S3 (KAM-011).

Espelho de `packages/core-ts/src/storage/sigv4.ts`, escrito em separado. A prova
de que os dois calculam o mesmo e um vector fixado nas duas suites de teste
(`test_storage_s3.py` e `storage.s3.test.ts`); a prova de que esse "mesmo" e o
que um servidor S3 aceita e `docs/evidencia/KAM-011-seaweedfs.md`.

**Porque e que isto esta escrito a mao.** O `kamba-core` nao tem dependencias,
de proposito (`pyproject.toml`), e o `boto3` traria seis pacotes para fazer
cinco pedidos HTTP. O algoritmo e publico, pequeno e estavel.

O que esta aqui: assinatura por cabecalho `Authorization` e por *query* (URL
pre-assinada). O que nao esta: `aws-chunked`, SigV4A, *session tokens*.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, unquote, urlsplit

ALGORITMO = "AWS4-HMAC-SHA256"
_SERVICO = "s3"
_TERMINADOR = "aws4_request"

#: Valor de `x-amz-content-sha256` de uma URL pre-assinada.
CORPO_NAO_ASSINADO = "UNSIGNED-PAYLOAD"


@dataclass(frozen=True)
class Credenciais:
    """Credenciais S3. **Nunca** entram numa mensagem de erro nem num log.

    O `repr` omite o segredo: um `print` de depuracao esquecido nao o escreve.
    """

    access_key_id: str
    secret_access_key: str

    def __repr__(self) -> str:
        return "Credenciais(access_key_id=<omitido>, secret_access_key=<omitido>)"


def sha256_hex(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _hmac(chave: bytes, dados: str) -> bytes:
    return hmac.new(chave, dados.encode(), hashlib.sha256).digest()


def codificar(texto: str) -> str:
    """Codificacao RFC 3986: so `A-Za-z0-9-_.~` ficam em claro."""
    return quote(texto, safe="-_.~")


def caminho_canonico(caminho: str) -> str:
    """Caminho canonico: cada segmento codificado uma vez, as barras preservadas."""
    return "/".join(codificar(unquote(segmento)) for segmento in caminho.split("/"))


def query_canonica(parametros: Iterable[tuple[str, str]]) -> str:
    """*Query* canonica: pares codificados, ordenados por nome e depois por valor."""
    pares = sorted((codificar(nome), codificar(valor)) for nome, valor in parametros)
    return "&".join(f"{nome}={valor}" for nome, valor in pares)


def data_amz(instante: datetime) -> str:
    """`20261012T101500Z`"""
    return instante.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def anfitriao(url: str) -> str:
    """O valor do cabecalho `Host` de uma URL: sem a porta quando e a do esquema."""
    partes = urlsplit(url)
    nome = partes.hostname or ""
    if ":" in nome:
        nome = f"[{nome}]"
    porta = partes.port
    if porta is None or (partes.scheme, porta) in (("http", 80), ("https", 443)):
        return nome
    return f"{nome}:{porta}"


def _ambito(dia: str, regiao: str) -> str:
    return f"{dia}/{regiao}/{_SERVICO}/{_TERMINADOR}"


def _chave_de_assinatura(segredo: str, dia: str, regiao: str) -> bytes:
    passo = _hmac(f"AWS4{segredo}".encode(), dia)
    for parte in (regiao, _SERVICO, _TERMINADOR):
        passo = _hmac(passo, parte)
    return passo


def assinatura(
    *,
    metodo: str,
    url: str,
    cabecalhos: Mapping[str, str],
    hash_do_corpo: str,
    regiao: str,
    quando: str,
    segredo: str,
    query: Iterable[tuple[str, str]] | None = None,
) -> tuple[str, str]:
    """`(assinatura, cabecalhos_assinados)` de um pedido.

    E publica porque ha dois lados que a calculam: quem assina, e um servidor de
    teste que confere.
    """
    partes = urlsplit(url)
    pares = sorted(
        (nome.lower(), " ".join(valor.split())) for nome, valor in cabecalhos.items()
    )
    assinados = ";".join(nome for nome, _ in pares)
    if query is None:
        query = parse_qsl(partes.query, keep_blank_values=True)
    pedido_canonico = "\n".join(
        (
            metodo,
            caminho_canonico(partes.path or "/"),
            query_canonica(query),
            "".join(f"{nome}:{valor}\n" for nome, valor in pares),
            assinados,
            hash_do_corpo,
        )
    )
    dia = quando[:8]
    a_assinar = "\n".join(
        (ALGORITMO, quando, _ambito(dia, regiao), sha256_hex(pedido_canonico.encode()))
    )
    valor = hmac.new(
        _chave_de_assinatura(segredo, dia, regiao), a_assinar.encode(), hashlib.sha256
    ).hexdigest()
    return valor, assinados


def assinar_pedido(
    *,
    metodo: str,
    url: str,
    cabecalhos: Mapping[str, str] | None = None,
    corpo: bytes = b"",
    credenciais: Credenciais,
    regiao: str,
    agora: datetime,
) -> dict[str, str]:
    """Cabecalhos de um pedido assinado: os dados, mais `host`, `x-amz-date`,
    `x-amz-content-sha256` e `authorization`.

    **Todos** os cabecalhos dados sao assinados. Um cabecalho de metadados fora
    da assinatura e um cabecalho que um intermediario pode trocar — e os
    metadados sao onde vive o `retain_until`.
    """
    hash_do_corpo = sha256_hex(corpo)
    quando = data_amz(agora)
    finais = {nome.lower(): valor for nome, valor in (cabecalhos or {}).items()}
    finais["host"] = anfitriao(url)
    finais["x-amz-content-sha256"] = hash_do_corpo
    finais["x-amz-date"] = quando
    valor, assinados = assinatura(
        metodo=metodo,
        url=url,
        cabecalhos=finais,
        hash_do_corpo=hash_do_corpo,
        regiao=regiao,
        quando=quando,
        segredo=credenciais.secret_access_key,
    )
    credencial = f"{credenciais.access_key_id}/{_ambito(quando[:8], regiao)}"
    finais["authorization"] = (
        f"{ALGORITMO} Credential={credencial}, SignedHeaders={assinados}, Signature={valor}"
    )
    return finais


def presignar_get(
    *,
    url: str,
    credenciais: Credenciais,
    regiao: str,
    agora: datetime,
    expira_s: int,
) -> str:
    """URL pre-assinada de leitura (`GET`), valida durante `expira_s` segundos.

    So `host` e assinado, pelo que quem recebe a URL nao precisa de mandar
    cabecalho nenhum. O preco e o que se sabe: **quem tem a URL tem o objecto**
    ate ela expirar. Por isso o tecto de 300 s nao e deste ficheiro, e da guarda.
    """
    partes = urlsplit(url)
    quando = data_amz(agora)
    parametros = [
        *parse_qsl(partes.query, keep_blank_values=True),
        ("X-Amz-Algorithm", ALGORITMO),
        ("X-Amz-Credential", f"{credenciais.access_key_id}/{_ambito(quando[:8], regiao)}"),
        ("X-Amz-Date", quando),
        ("X-Amz-Expires", str(expira_s)),
        ("X-Amz-SignedHeaders", "host"),
    ]
    valor, _ = assinatura(
        metodo="GET",
        url=url,
        cabecalhos={"host": anfitriao(url)},
        hash_do_corpo=CORPO_NAO_ASSINADO,
        regiao=regiao,
        quando=quando,
        segredo=credenciais.secret_access_key,
        query=parametros,
    )
    return (
        f"{partes.scheme}://{anfitriao(url)}{caminho_canonico(partes.path)}"
        f"?{query_canonica(parametros)}&X-Amz-Signature={valor}"
    )
