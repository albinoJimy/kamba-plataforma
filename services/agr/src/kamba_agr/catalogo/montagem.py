"""A montagem do pipeline do KAM-049 no AGR (KAM-119), e as portas que ainda nao tem adaptador.

## O que se liga aqui, e o que fica por ligar

O `ServicoDeIngestao` pede nove portas, todas obrigatorias. Este ticket liga
as que tem com quem falar:

| Porta | Aqui |
|---|---|
| `Repositorio` | `RepositorioDbapi` sobre a ligacao da ToolLayer (`kamba_app`, RLS `FORCE`) |
| `PortaDeScreening` | `ScreeningPeloCom` com o sujeito `produto` (`tls/screening.py`) |
| `PortaDoRegisto` | `RegistoPeloCom` (`tls/registo_com.py`) |
| `FonteDeMedia` | **por ligar** — o MED do KAM-020 nao esta montado em servico nenhum, e o `agent_invocation` nao leva a media |
| `Descodificador` | o `DescodificadorPillow` (KAM-231, `catalogo/descodificador.py`), que o processo passa; a omissao daqui continua a por ligar |
| `ExtractorDeVisao` | **por ligar** — o adaptador do alias `kamba-vision` pelo *gateway* |

As por ligar **levantam**, e o pipeline trata isso como falha fechada: uma
foto que chegue nao vira rascunho, e o dono e avisado. O credor e o ticket da
entrada real da foto, nomeado no bloco do KAM-119.

## A porta da foto (`ImageEnhancePort`, *proposta*)

O criterio 8 do bloco: depois do rascunho, com o entitlement `foto` activo,
oferece-se «melhorar foto» (KAM-120). A porta e uma pergunta so —
`disponivel(tenant)` — e o adaptador nulo diz que nao, sem erro. O trabalho em
si e o `enhance_image` do `kamba_core.foto`, que o dono pede pelo canal quando
o KAM-120 o ligar.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol, runtime_checkable

from kamba_core.catalogo.imagem import Descodificador, ImagemIlegivel, Matriz
from kamba_core.catalogo.pipeline import (
    AMBIENTE_PROD,
    ErroDaVisao,
    ExtractorDeVisao,
    FonteDeMedia,
    PortaDeDestinos,
    PortaDoRegisto,
    RespostaDaVisao,
    ServicoDeIngestao,
)
from kamba_core.catalogo.repositorio import Repositorio, RepositorioDbapi
from kamba_core.catalogo.screening import PortaDeScreening
from kamba_core.idx.normalizacao import Lexico
from kamba_core.storage.port import StorageProvider

#: O credor da entrada real da foto (fonte, descodificador e visao). Ver o bloco.
CREDOR_DA_FOTO: Final = "KAM-231"


class FotoPorLigarError(RuntimeError):
    """Uma porta da entrada da foto que ainda nao tem adaptador."""


class FontePorLigar:
    """A `FonteDeMedia` enquanto o MED nao esta montado. **Levanta sempre.**"""

    def descarregar(self, tenant_id: str, media_id: str) -> bytes:
        raise FotoPorLigarError(f"a fonte de media do canal nao esta ligada (credor {CREDOR_DA_FOTO})")


class DescodificadorPorLigar:
    """O `Descodificador` enquanto nao ha biblioteca de imagem. Toda a imagem e ilegivel."""

    def cinzento(self, corpo: bytes) -> Matriz:
        raise ImagemIlegivel(f"sem descodificador de imagem (credor {CREDOR_DA_FOTO})")


@dataclass(frozen=True)
class VisaoPorLigar:
    """O `ExtractorDeVisao` sem adaptador: sem fornecedores, e o *gate* bloqueia antes."""

    fornecedores: tuple[str, ...] = ()

    def extrair(self, tenant_id: str, imagem: bytes) -> RespostaDaVisao:
        raise ErroDaVisao(f"sem adaptador de visao (credor {CREDOR_DA_FOTO})")


class StoragePorLigar:
    """O STO da ingestao sem adaptador. So a foto o usa, e a fonte ja levantou antes."""

    def __getattr__(self, nome: str) -> Any:
        raise FotoPorLigarError(f"o armazenamento da foto nao esta ligado (credor {CREDOR_DA_FOTO})")


class DestinosPorLigar:
    """A porta de destinos sem adaptador: **nada** esta autorizado."""

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None:
        raise PermissionError("destino nao autorizado")


def _lexico_vazio(tenant_id: str) -> Lexico:
    """Sem termos: a marca e a unidade ficam como vieram. So a extraccao o le, e
    a extraccao precisa da visao, que esta por ligar."""
    return Lexico(tenant_id=tenant_id)


@runtime_checkable
class ImageEnhancePort(Protocol):
    """A oferta de «melhorar foto» do KAM-120, depois do rascunho (*proposta*)."""

    def disponivel(self, tenant_id: str) -> bool: ...


class EnhanceNulo:
    """Sem o modulo `foto`: nunca ha oferta, e o fluxo segue sem erro."""

    def disponivel(self, tenant_id: str) -> bool:
        return False


class _NaoFecha:
    """A ligacao da ToolLayer emprestada ao `RepositorioDbapi`, que fecha a sua.

    O repositorio do KAM-049 abre e fecha uma ligacao por chamada; a da ToolLayer
    e da vaga dela e volta a fila depois do turno. O `close` aqui e nada.

    O `__weakref__` e do `tenant_guard`, que regista a ligacao em uso numa
    `WeakSet` (apanhado no gate 8). Regista o **involucro**, e nao a tomada: a
    exclusividade vale entre transaccoes deste repositorio, e o executor nunca
    abre uma transaccao na tomada crua enquanto uma destas esta aberta — cada
    operacao do repositorio e uma transaccao inteira.
    """

    __slots__ = ("_ligacao", "__weakref__")

    def __init__(self, ligacao: Any) -> None:
        self._ligacao = ligacao

    def close(self) -> None:
        return None

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._ligacao, nome)


def repositorio_sobre(ligacao: Any) -> Repositorio:
    """O `RepositorioDbapi` sobre a ligacao de uma invocacao, sem a fechar."""
    emprestada = _NaoFecha(ligacao)
    return RepositorioDbapi(lambda: emprestada)


@dataclass(frozen=True)
class PortasDoCatalogo:
    """As portas do pipeline que nao dependem da invocacao, e as duas do modulo.

    `sintetica` e a declaracao do KAM-049 de que as fotos sao sinteticas: **so
    quem compoe o processo a da**, e so fora de `prod` vale (o pipeline ignora-a
    em `prod`). Nenhum argumento de tool a expoe ao modelo.
    """

    screening: PortaDeScreening
    registo: PortaDoRegisto
    ambiente: str = AMBIENTE_PROD
    fonte: FonteDeMedia = field(default_factory=FontePorLigar)
    #: KAM-231. A fonte **por invocacao**, sobre a ligacao dela: a `FonteDoMed`
    #: le a `media_assets` no tenant da invocacao (`catalogo/fonte.py`). Com
    #: ela, o `fonte` acima nao se usa.
    fonte_sobre: Callable[[Any], FonteDeMedia] | None = None
    storage: StorageProvider = field(default_factory=StoragePorLigar)  # type: ignore[assignment]
    descodificador: Descodificador = field(default_factory=DescodificadorPorLigar)
    destinos: PortaDeDestinos = field(default_factory=DestinosPorLigar)
    visao: ExtractorDeVisao = field(default_factory=VisaoPorLigar)
    lexico: Callable[[str], Lexico] = _lexico_vazio
    enhance: ImageEnhancePort = field(default_factory=EnhanceNulo)
    sintetica: bool = False
    repositorio: Callable[[Any], Repositorio] = repositorio_sobre
    agora: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def servico(self, ligacao: Any) -> ServicoDeIngestao:
        """O pipeline para uma invocacao: o repositorio sobre a ligacao dela."""
        return ServicoDeIngestao(
            repositorio=self.repositorio(ligacao),
            fonte=self.fonte if self.fonte_sobre is None else self.fonte_sobre(ligacao),
            storage=self.storage,
            descodificador=self.descodificador,
            destinos=self.destinos,
            visao=self.visao,
            lexico=self.lexico,
            screening=self.screening,
            registo=self.registo,
            ambiente=self.ambiente,
            agora=self.agora,
        )


__all__ = [
    "CREDOR_DA_FOTO",
    "DescodificadorPorLigar",
    "DestinosPorLigar",
    "EnhanceNulo",
    "FontePorLigar",
    "FotoPorLigarError",
    "ImageEnhancePort",
    "PortasDoCatalogo",
    "StoragePorLigar",
    "VisaoPorLigar",
    "repositorio_sobre",
]
