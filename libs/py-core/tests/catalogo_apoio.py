"""Fakes e imagens sinteticas para os ensaios do Catalogo AI (KAM-049).

Nada aqui fala com a rede nem com um modelo: a visao e falsa, o screening e
falso, o Registo e falso. As imagens sao JPEG e PNG **construidos a mao**, com
os segmentos de metadados que o ensaio quer ver desaparecer — incluindo o que
um telemovel escreve depois do `EOI`.
"""

from __future__ import annotations

import hashlib
import json
import random
import struct
import uuid
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from kamba_core.catalogo.extraccao import Campo
from kamba_core.catalogo.pipeline import (
    ConfirmacaoDoDono,
    ErroDaVisao,
    RespostaDaVisao,
    ServicoDeIngestao,
)
from kamba_core.catalogo.repositorio import RepositorioEmMemoria
from kamba_core.catalogo.screening import ResultadoDoScreen
from kamba_core.destinos.porta import TransferenciaNegada
from kamba_core.idx.normalizacao import Lexico
from kamba_core.storage.fake import criar_storage_fake

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"

#: O que os metadados levam nas imagens de ensaio, para o procurar nos bytes.
GPS = b"GPS-LAT-8.8383-LON-13.2344"
DONO = b"Artist: Fulano Exemplo"

# ---------------------------------------------------------------- imagens


def _segmento(marcador: int, corpo: bytes) -> bytes:
    return bytes((0xFF, marcador)) + struct.pack(">H", len(corpo) + 2) + corpo


def jpeg(marca: bytes = b"", *, com_metadados: bool = True, com_cauda: bool = True) -> bytes:
    """Um JPEG sintetico com EXIF/GPS no APP1, IPTC no APP13, COM e cauda.

    `marca` vai nos dados entropicos: e o que o descodificador falso le para
    escolher a matriz, e o que prova que os dados da imagem sobrevivem.
    """
    partes = [b"\xff\xd8", _segmento(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")]
    if com_metadados:
        partes.append(_segmento(0xE1, b"Exif\x00\x00" + GPS + DONO))
        partes.append(_segmento(0xE1, b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta>" + GPS + b"</x:xmpmeta>"))
        partes.append(_segmento(0xED, b"Photoshop 3.0\x00" + DONO))
        partes.append(_segmento(0xFE, b"comentario " + GPS))
        partes.append(_segmento(0xE2, b"MPF\x00" + GPS))
    partes.append(_segmento(0xE2, b"ICC_PROFILE\x00\x01\x01perfil"))
    partes.append(_segmento(0xDB, b"\x00" + bytes(range(64))))
    partes.append(_segmento(0xC0, b"\x08\x01\xe0\x02\x80\x01\x01\x11\x00"))
    # Um codigo de comprimento 1 e o seu simbolo: 1 + 16 + 1 bytes, exactos.
    partes.append(_segmento(0xC4, b"\x00" + b"\x01" + bytes(15) + b"\x00"))
    partes.append(_segmento(0xDA, b"\x01\x01\x00\x00\x3f\x00"))
    # Dados entropicos com enchimento (`FF 00`) e um RST, como na norma.
    partes.append(b"\x12\x34\xff\x00\x56" + marca + b"\xff\xd0\x78\x9a")
    partes.append(b"\xff\xd9")
    if com_cauda:
        partes.append(b"SEGUNDA-IMAGEM" + GPS)
    return b"".join(partes)


def _chunk(tipo: bytes, dados: bytes) -> bytes:
    return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados))


def png(marca: bytes = b"") -> bytes:
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", struct.pack(">IIBBBBB", 640, 480, 8, 0, 0, 0, 0)),
            _chunk(b"tEXt", b"Author\x00" + DONO),
            _chunk(b"eXIf", b"MM\x00*" + GPS),
            _chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + GPS),
            _chunk(b"pHYs", b"\x00\x00\x0b\x13\x00\x00\x0b\x13\x01"),
            _chunk(b"IDAT", zlib.compress(b"\x00" * 64 + marca)),
            _chunk(b"IEND", b""),
            b"CAUDA" + GPS,
        )
    )


# ---------------------------------------------------------------- matrizes


def textura(semente: bytes, lado: int = 400) -> list[list[float]]:
    """Uma imagem nitida e com contraste, diferente para cada semente."""
    rnd = random.Random(hashlib.sha256(semente).digest())
    base = [[rnd.random() * 255 for _ in range(8)] for _ in range(8)]
    bloco = lado // 8
    return [
        [
            base[y // bloco % 8][x // bloco % 8] * 0.7 + (60 if (x // 4 + y // 4) % 2 else 0)
            for x in range(lado)
        ]
        for y in range(lado)
    ]


def desfocada(lado: int = 400) -> list[list[float]]:
    """Um gradiente suave: contraste sim, arestas nao."""
    return [[(x + y) * 255 / (2 * lado) for x in range(lado)] for y in range(lado)]


def lisa(lado: int = 400) -> list[list[float]]:
    return [[128.0] * lado for _ in range(lado)]


class DescodificadorFake:
    """Escolhe a matriz pela marca nos dados: `BLUR`, `FLAT`, `SMALL`, `BAD`, ou textura."""

    def __init__(self) -> None:
        self.chamadas = 0

    def cinzento(self, corpo: bytes) -> list[list[float]]:
        from kamba_core.catalogo.imagem import ImagemIlegivel

        self.chamadas += 1
        if b"BAD" in corpo:
            raise ImagemIlegivel("ilegivel")
        if b"BLUR" in corpo:
            return desfocada()
        if b"FLAT" in corpo:
            return lisa()
        if b"SMALL" in corpo:
            return textura(corpo, lado=120)
        return textura(corpo)


# ---------------------------------------------------------------- portas falsas


class FonteFake:
    def __init__(self, medias: Mapping[str, bytes]) -> None:
        self.medias = dict(medias)
        self.chamadas: list[tuple[str, str]] = []

    def descarregar(self, tenant_id: str, media_id: str) -> bytes:
        self.chamadas.append((tenant_id, media_id))
        return self.medias[media_id]


def resposta(campos: Mapping[str, object], **extra: object) -> str:
    corpo: dict[str, object] = {
        nome: ({"valor": v, "confianca": 0.95} if not isinstance(v, dict) else v) for nome, v in campos.items()
    }
    corpo.update(extra)
    return json.dumps(corpo, ensure_ascii=False)


CAMISA = resposta(
    {"nome": "Camisa polo", "marca": "Niké", "categoria": "vestuario", "cor": "azul", "variantes": ["M", "L"]},
    preco_etiqueta={"valor": "12 mil kz", "confianca": 0.9},
)


@dataclass
class VisaoFake:
    texto: str = CAMISA
    custo: Decimal = Decimal("0.0042")
    fornecedores: tuple[str, ...] = ("anthropic",)
    falhar: bool = False
    imagens: list[bytes] = field(default_factory=list)

    def extrair(self, tenant_id: str, imagem: bytes) -> RespostaDaVisao:
        self.imagens.append(imagem)
        if self.falhar:
            raise ErroDaVisao("o proxy falhou", custo_usd=self.custo)
        return RespostaDaVisao(texto=self.texto, custo_usd=self.custo)


@dataclass
class DestinosFake:
    autorizados: set[tuple[str, str, str]] = field(default_factory=set)
    pedidos: list[tuple[str, str, str]] = field(default_factory=list)

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        self.pedidos.append((tenant_id, fornecedor, finalidade))
        if (tenant_id, fornecedor, finalidade) not in self.autorizados:
            raise TransferenciaNegada("sem destino autorizado")


@dataclass
class ScreeningFake:
    """`bloqueada` com a regra `alcool` se algum texto falar de cerveja; senao `permitida`."""

    pedidos: list[tuple[str, str, str, tuple[str, ...]]] = field(default_factory=list)
    decisao_forcada: ResultadoDoScreen | None = None
    falhar: bool = False

    def screen(self, tenant_id: str, sujeito_ref: str, categoria_declarada: str, textos: Sequence[str]) -> ResultadoDoScreen:
        self.pedidos.append((tenant_id, sujeito_ref, categoria_declarada, tuple(textos)))
        if self.falhar:
            raise RuntimeError("motor em baixo")
        if self.decisao_forcada is not None:
            return self.decisao_forcada
        if any("cerveja" in t.lower() for t in (*textos, categoria_declarada)):
            return ResultadoDoScreen("bloqueada", ("alcool",), "1.0.0+m.2", 1.0)
        return ResultadoDoScreen("permitida", (), "1.0.0+m.2", 0.99)


@dataclass
class RegistoFake:
    rascunhos: list[tuple[str, str, dict[str, Campo]]] = field(default_factory=list)
    publicados: list[tuple[str, str, ConfirmacaoDoDono]] = field(default_factory=list)

    def rascunho(self, tenant_id: str, sku: str, campos: Mapping[str, Campo]) -> None:
        self.rascunhos.append((tenant_id, sku, dict(campos)))

    def publicar(self, tenant_id: str, sku: str, confirmacao: ConfirmacaoDoDono) -> None:
        self.publicados.append((tenant_id, sku, confirmacao))


LEXICO = (
    {"tenant_id": None, "tipo": "marca", "termo": "nike", "canonico": "nike"},
    {"tenant_id": None, "tipo": "marca", "termo": "samsung", "canonico": "samsung"},
    {"tenant_id": None, "tipo": "unidade", "termo": "unid", "canonico": "un"},
    {"tenant_id": None, "tipo": "unidade", "termo": "pcs", "canonico": "un"},
    {"tenant_id": None, "tipo": "unidade", "termo": "un", "canonico": "un"},
    {"tenant_id": None, "tipo": "unidade", "termo": "caixa", "canonico": "caixa"},
    {"tenant_id": None, "tipo": "unidade", "termo": "fardo", "canonico": "fardo"},
)


def lexico(tenant_id: str | None = None) -> Lexico:
    return Lexico.de_linhas(LEXICO, tenant_id, norm_versao=3)


@dataclass
class Montagem:
    servico: ServicoDeIngestao
    repo: RepositorioEmMemoria
    fonte: FonteFake
    visao: VisaoFake
    destinos: DestinosFake
    screening: ScreeningFake
    registo: RegistoFake
    descodificador: DescodificadorFake
    storage: object


def montar(
    medias: Mapping[str, bytes] | None = None,
    *,
    ambiente: str = "prod",
    autorizar: bool = True,
    visao: VisaoFake | None = None,
) -> Montagem:
    repo = RepositorioEmMemoria()
    fonte = FonteFake(medias or {"m1": jpeg(b"P1")})
    v = visao or VisaoFake()
    destinos = DestinosFake()
    if autorizar:
        for tenant in (A, B):
            for fornecedor in v.fornecedores:
                destinos.autorizados.add((tenant, fornecedor, "visao"))
    screening = ScreeningFake()
    registo = RegistoFake()
    descodificador = DescodificadorFake()
    armazenamento = criar_storage_fake()
    servico = ServicoDeIngestao(
        repositorio=repo,
        fonte=fonte,
        storage=armazenamento.storage,
        descodificador=descodificador,
        destinos=destinos,
        visao=v,
        lexico=lexico,
        screening=screening,
        registo=registo,
        ambiente=ambiente,
    )
    return Montagem(servico, repo, fonte, v, destinos, screening, registo, descodificador, armazenamento)


def responder(servico: ServicoDeIngestao, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
    """O `responder` com um `mensagem_id` novo em cada chamada, salvo se o ensaio der um."""
    kwargs.setdefault("mensagem_id", f"wamid.{uuid.uuid4().hex}")
    return servico.responder(*args, **kwargs)  # type: ignore[arg-type]


def confirmacao(versao: str, actor: str = "owner:1") -> ConfirmacaoDoDono:
    return ConfirmacaoDoDono(actor=actor, em=datetime(2026, 11, 13, 10, 0, tzinfo=UTC), versao_texto=versao)
