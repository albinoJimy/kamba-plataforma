"""`MotorS3` — motor sobre a API S3, por HTTP (KAM-011).

Espelho de `packages/core-ts/src/storage/s3.ts`. Fala com qualquer servidor que
implemente o subconjunto abaixo: **qual** e configuracao (`config.py`), e a
decisao D6 — SeaweedFS auto-alojado ou S3 gerido — fica onde esta, aberta. O que
foi exercitado contra um servidor real esta em
`docs/evidencia/KAM-011-seaweedfs.md`; contra um S3 gerido **nada foi
verificado**.

Subconjunto usado, e mais nenhum:

- escrita simples: `PUT /{bucket}/{chave}`;
- escrita em partes: `POST ?uploads`, `PUT ?partNumber&uploadId`,
  `POST ?uploadId`, `DELETE ?uploadId`;
- leitura: `GET` e `HEAD /{bucket}/{chave}`;
- eliminacao: `DELETE /{bucket}/{chave}`;
- listagem: `GET /{bucket}?list-type=2&prefix=…`;
- URL de leitura: SigV4 por *query*, so `GET`.

Enderecamento **por caminho** (`{endpoint}/{bucket}/{chave}`). O estilo
*virtual-hosted* nao esta implementado, e isso e um dado para a D6.

Um corpo ate `tamanho_da_parte` vai num pedido so; acima disso vai em partes. O
objecto nao e junto em memoria: fica o que ainda nao foi enviado — menos de
uma parte, mais o bloco que quem chama acabou de entregar — e a copia da parte
que esta a ser enviada. Medido pela revisao: cerca de tres partes de pico com
blocos pequenos. Quem entrega o objecto inteiro num so bloco tem-no inteiro em
memoria, e isso este modulo nao muda.
"""

from __future__ import annotations

import hashlib
import http.client
import re
import ssl
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import quote, urlencode, urlsplit

from .motor import Escrito, InfoBruta, ItemListado, Listagem, MetaBruta
from .port import ArmazenamentoIndisponivelError, ObjectoInexistenteError
from .sigv4 import Credenciais, assinar_pedido, presignar_get

#: Minimo que o S3 aceita numa parte que nao seja a ultima: 5 MiB.
PARTE_MINIMA = 5 * 1024 * 1024

#: Tamanho de parte por omissao: 16 MiB. Com este valor um objecto de 10 MB vai
#: num pedido e um de 25 MB vai em duas partes. E *proposta*: o limite de media
#: do WhatsApp e a memoria do *worker* calibram-no no KAM-020.
PARTE_POR_OMISSAO = 16 * 1024 * 1024

#: Paginas de listagem: o maximo que o S3 devolve por pedido.
_PAGINA = 1000

#: Quanto do corpo de um erro se le a procura do `<Code>`.
_LIMITE_DO_ERRO = 64 * 1024

#: Prefixo dos cabecalhos de metadados do utilizador.
_PREFIXO_META = "x-amz-meta-"

_BLOCO = 64 * 1024


@dataclass(frozen=True)
class PedidoHttp:
    """Um pedido HTTP, na forma minima de que o motor precisa."""

    metodo: str
    url: str
    cabecalhos: Mapping[str, str]
    corpo: bytes | None = None


@dataclass(frozen=True)
class RespostaHttp:
    """Uma resposta HTTP. Os nomes dos cabecalhos vem em minusculas."""

    estado: int
    cabecalhos: Mapping[str, str] = field(default_factory=dict)
    corpo: Iterable[bytes] = ()


#: Como o motor chega a rede. Injectavel para que a suite de contrato corra o
#: motor S3 **inteiro** contra um servidor em memoria, sem contentor.
Transporte = Callable[[PedidoHttp], RespostaHttp]


def transporte_por_http(tempo_limite_s: float = 120.0) -> Transporte:
    """O transporte de producao: `http.client`, que nao segue redireccionamentos.

    Um redireccionamento levava o pedido assinado para outro anfitriao; o
    `http.client` nunca o segue, e e por isso que se usa em vez do `urllib`.
    """

    def transporte(pedido: PedidoHttp) -> RespostaHttp:
        partes = urlsplit(pedido.url)
        if partes.scheme == "https":
            ligacao: http.client.HTTPConnection = http.client.HTTPSConnection(
                partes.hostname or "",
                partes.port,
                timeout=tempo_limite_s,
                context=ssl.create_default_context(),
            )
        else:
            ligacao = http.client.HTTPConnection(
                partes.hostname or "", partes.port, timeout=tempo_limite_s
            )
        caminho = partes.path or "/"
        if partes.query:
            caminho = f"{caminho}?{partes.query}"
        try:
            ligacao.request(
                pedido.metodo, caminho, body=pedido.corpo, headers=dict(pedido.cabecalhos)
            )
            resposta = ligacao.getresponse()
        except BaseException:
            ligacao.close()
            raise

        def corpo() -> Iterator[bytes]:
            try:
                while bloco := resposta.read(_BLOCO):
                    yield bloco
            finally:
                ligacao.close()

        return RespostaHttp(
            estado=resposta.status,
            cabecalhos={nome.lower(): valor for nome, valor in resposta.getheaders()},
            corpo=corpo(),
        )

    return transporte


def _ler_tudo(corpo: Iterable[bytes], limite: int) -> bytes:
    """Esvazia a resposta, guardando ate `limite` bytes."""
    guardados: list[bytes] = []
    total = 0
    for bloco in corpo:
        if total < limite:
            guardados.append(bloco)
        total += len(bloco)
    return b"".join(guardados)


_ENTIDADES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'"}
_ENTIDADE = re.compile(r"&(#x[0-9a-fA-F]+|#[0-9]+|[a-z]+);")


def desescapar_xml(texto: str) -> str:
    """Desfaz as entidades XML de um valor de texto."""

    def trocar(m: re.Match[str]) -> str:
        corpo = m.group(1)
        try:
            if corpo.startswith("#x"):
                return chr(int(corpo[2:], 16))
            if corpo.startswith("#"):
                return chr(int(corpo[1:]))
        except (ValueError, OverflowError):
            # Um ponto de codigo que nao existe fica como veio: quem decide o
            # que fazer com um valor estranho e quem o confere a seguir.
            return m.group(0)
        return _ENTIDADES.get(corpo, m.group(0))

    return _ENTIDADE.sub(trocar, texto)


def elemento_xml(xml: str, nome: str) -> str | None:
    """Primeiro valor de um elemento XML simples, ou `None`."""
    m = re.search(rf"<{nome}>([^<]*)</{nome}>", xml)
    return None if m is None else desescapar_xml(m.group(1))


def _escapar_xml(texto: str) -> str:
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


_DIGITOS = re.compile(r"[0-9]+")


class MotorS3:
    """Motor S3. Ver `criar_storage_s3` (`config.py`) para a forma de o usar."""

    nome = "s3"

    def __init__(
        self,
        *,
        endpoint: str,
        bucket: str,
        regiao: str,
        credenciais: Callable[[], Credenciais],
        transporte: Transporte | None = None,
        agora: Callable[[], datetime] | None = None,
        tamanho_da_parte: int = PARTE_POR_OMISSAO,
        tempo_limite_s: float = 120.0,
    ) -> None:
        if (
            not isinstance(tamanho_da_parte, int)
            or isinstance(tamanho_da_parte, bool)
            or tamanho_da_parte < PARTE_MINIMA
        ):
            raise ValueError(f"tamanho_da_parte tem de ser um inteiro >= {PARTE_MINIMA} (5 MiB)")
        self._base = f"{endpoint.rstrip('/')}/{bucket}"
        self._regiao = regiao
        #: Chamada **em cada pedido**: e o que deixa uma rotacao no cofre chegar
        #: aqui sem reiniciar o processo.
        self._credenciais = credenciais
        self._transporte = transporte or transporte_por_http(tempo_limite_s)
        self._agora = agora or (lambda: datetime.now(UTC))
        self._parte = tamanho_da_parte

    # ------------------------------------------------------------------ escrita

    def put(self, chave: str, corpo: Iterable[bytes], meta: MetaBruta) -> Escrito:
        cabecalhos = {"content-type": meta.content_type}
        for nome, valor in meta.metadados.items():
            cabecalhos[_PREFIXO_META + nome] = valor

        soma = hashlib.sha256()
        tamanho = 0
        envio: str | None = None
        etags: list[str] = []
        pendente = bytearray()

        def enviar_parte(dados: bytes) -> None:
            nonlocal envio
            if envio is None:
                aberta = self._pedido("put", "POST", chave, {"uploads": ""}, cabecalhos)
                xml = _ler_tudo(aberta.corpo, _LIMITE_DO_ERRO).decode("utf-8", "replace")
                identificador = elemento_xml(xml, "UploadId")
                if not identificador:
                    raise ArmazenamentoIndisponivelError("put", aberta.estado, "SemUploadId")
                envio = identificador
            resposta = self._pedido(
                "put",
                "PUT",
                chave,
                {"partNumber": str(len(etags) + 1), "uploadId": envio},
                {},
                dados,
            )
            _ler_tudo(resposta.corpo, 0)
            etag = resposta.cabecalhos.get("etag")
            if not etag:
                raise ArmazenamentoIndisponivelError("put", resposta.estado, "SemETag")
            etags.append(etag)

        try:
            for bloco in corpo:
                soma.update(bloco)
                tamanho += len(bloco)
                pendente += bloco
                # `>` e nao `>=`: um corpo com exactamente o tamanho de uma
                # parte vai num pedido so. So se abre um envio em partes quando
                # se sabe que ha mais do que uma.
                while len(pendente) > self._parte:
                    enviar_parte(bytes(pendente[: self._parte]))
                    del pendente[: self._parte]
            if envio is None:
                resposta = self._pedido("put", "PUT", chave, {}, cabecalhos, bytes(pendente))
                _ler_tudo(resposta.corpo, 0)
            else:
                enviar_parte(bytes(pendente))
                fecho = (
                    "<CompleteMultipartUpload>"
                    + "".join(
                        f"<Part><PartNumber>{i}</PartNumber>"
                        f"<ETag>{_escapar_xml(etag)}</ETag></Part>"
                        for i, etag in enumerate(etags, start=1)
                    )
                    + "</CompleteMultipartUpload>"
                )
                resposta = self._pedido(
                    "put",
                    "POST",
                    chave,
                    {"uploadId": envio},
                    {"content-type": "application/xml"},
                    fecho.encode(),
                )
                # O S3 pode responder 200 a um fecho que falhou, com o erro no corpo.
                xml = _ler_tudo(resposta.corpo, _LIMITE_DO_ERRO).decode("utf-8", "replace")
                if "<Error>" in xml:
                    raise ArmazenamentoIndisponivelError(
                        "put", resposta.estado, elemento_xml(xml, "Code")
                    )
        except BaseException:
            if envio is not None:
                # Um envio em partes abandonado ocupa espaco ate alguem o
                # abortar. O melhor esforco fica aqui; o erro que sobe e o
                # original.
                try:
                    aborto = self._transporte(
                        self._assinado("DELETE", chave, {"uploadId": envio}, {}, None)
                    )
                    _ler_tudo(aborto.corpo, 0)
                except Exception:  # noqa: BLE001 - a limpeza nao pode esconder o erro
                    pass
            raise
        return Escrito(tamanho=tamanho, sha256=soma.hexdigest())

    # ------------------------------------------------------------------ leitura

    def get(self, chave: str) -> Iterator[bytes]:
        return iter(self._pedido("get", "GET", chave, {}, {}).corpo)

    def head(self, chave: str) -> InfoBruta:
        resposta = self._pedido("head", "HEAD", chave, {}, {})
        _ler_tudo(resposta.corpo, 0)
        metadados = {
            nome[len(_PREFIXO_META) :]: valor
            for nome, valor in resposta.cabecalhos.items()
            if nome.startswith(_PREFIXO_META)
        }
        tamanho_bruto = resposta.cabecalhos.get("content-length")
        if tamanho_bruto is None or _DIGITOS.fullmatch(tamanho_bruto) is None:
            raise ArmazenamentoIndisponivelError("head", resposta.estado, "SemContentLength")
        return InfoBruta(
            tamanho=int(tamanho_bruto),
            content_type=resposta.cabecalhos.get("content-type", "application/octet-stream"),
            metadados=metadados,
        )

    def delete(self, chave: str) -> None:
        resposta = self._pedido("delete", "DELETE", chave, {}, {}, inexistente_serve=True)
        _ler_tudo(resposta.corpo, 0)

    def list(self, prefixo: str, maximo: int) -> Listagem:
        itens: list[ItemListado] = []
        continuacao: str | None = None
        while True:
            query = {
                "list-type": "2",
                "prefix": prefixo,
                "max-keys": str(min(_PAGINA, maximo - len(itens))),
            }
            if continuacao is not None:
                query["continuation-token"] = continuacao
            resposta = self._pedido("list", "GET", None, query, {})
            xml = b"".join(resposta.corpo).decode("utf-8", "replace")
            for m in re.finditer(r"<Contents>(.*?)</Contents>", xml, re.DOTALL):
                chave = elemento_xml(m.group(1), "Key")
                tamanho_bruto = elemento_xml(m.group(1), "Size")
                if (
                    chave is None
                    or tamanho_bruto is None
                    or _DIGITOS.fullmatch(tamanho_bruto) is None
                ):
                    raise ArmazenamentoIndisponivelError(
                        "list", resposta.estado, "ListagemIlegivel"
                    )
                itens.append(ItemListado(chave, int(tamanho_bruto)))
            truncada = elemento_xml(xml, "IsTruncated") == "true"
            continuacao = elemento_xml(xml, "NextContinuationToken")
            if not truncada:
                return Listagem(tuple(itens), truncada=False)
            if len(itens) >= maximo:
                return Listagem(tuple(itens[:maximo]), truncada=True)
            if not continuacao:
                # Truncada e sem forma de continuar: nao se devolve meia listagem.
                raise ArmazenamentoIndisponivelError("list", resposta.estado, "SemContinuacao")

    def sign_url(self, chave: str, ttl_segundos: int) -> str:
        return presignar_get(
            url=f"{self._base}/{chave}",
            credenciais=self._credenciais(),
            regiao=self._regiao,
            agora=self._agora(),
            expira_s=ttl_segundos,
        )

    # ----------------------------------------------------------------- internos

    def _assinado(
        self,
        metodo: str,
        chave: str | None,
        query: Mapping[str, str],
        cabecalhos: Mapping[str, str],
        corpo: bytes | None,
    ) -> PedidoHttp:
        url = self._base if chave is None else f"{self._base}/{chave}"
        if query:
            url = f"{url}?{urlencode(query, quote_via=quote, safe='-_.~')}"
        assinados = assinar_pedido(
            metodo=metodo,
            url=url,
            cabecalhos=cabecalhos,
            corpo=corpo or b"",
            credenciais=self._credenciais(),
            regiao=self._regiao,
            agora=self._agora(),
        )
        # O cliente HTTP escreve o seu proprio `Host` a partir da URL, e e esse
        # que foi assinado; manda-lo outra vez duplicava o cabecalho.
        del assinados["host"]
        return PedidoHttp(metodo=metodo, url=url, cabecalhos=assinados, corpo=corpo)

    def _pedido(
        self,
        operacao: str,
        metodo: str,
        chave: str | None,
        query: Mapping[str, str],
        cabecalhos: Mapping[str, str],
        corpo: bytes | None = None,
        *,
        inexistente_serve: bool = False,
    ) -> RespostaHttp:
        """Um pedido assinado, com os erros traduzidos.

        404 num objecto e `ObjectoInexistenteError` (ou sucesso, num `DELETE`);
        um 404 com `NoSuchBucket` **nao** e — e configuracao errada, e trata-lo
        como "objecto inexistente" escondia um *bucket* em falta atras de uma
        resposta que o codigo de negocio trata como normal.
        """
        # Fora do `try`: um segredo ausente no cofre sobe tal como e — nomeia a
        # referencia, nunca o valor — em vez de se disfarcar de falha de rede.
        assinado = self._assinado(metodo, chave, query, cabecalhos, corpo)
        resposta = None
        try:
            resposta = self._transporte(assinado)
        except Exception:  # noqa: BLE001, S110
            pass
        if resposta is None:
            # Levantado **fora** do `except`, e nao com `from None` la dentro: o
            # `from None` so esconde a causa do *traceback*, e o erro de rede —
            # com a URL e o cabecalho `Authorization` na mensagem — ficava em
            # `__context__`, a mao de qualquer agregador de erros.
            raise ArmazenamentoIndisponivelError(operacao, None, None)
        if 200 <= resposta.estado < 300:
            return resposta
        xml = _ler_tudo(resposta.corpo, _LIMITE_DO_ERRO).decode("utf-8", "replace")
        codigo = elemento_xml(xml, "Code")
        if resposta.estado == 404 and chave is not None and codigo != "NoSuchBucket":
            if inexistente_serve:
                return RespostaHttp(estado=resposta.estado, cabecalhos=resposta.cabecalhos)
            raise ObjectoInexistenteError
        raise ArmazenamentoIndisponivelError(operacao, resposta.estado, codigo)
