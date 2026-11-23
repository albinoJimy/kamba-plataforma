"""O fundo gerado das artes (KAM-122, criterio 3): destino autorizado, OCR e regeracao.

    escolher_fundo(tenant, pedido, gerador, ocr, destinos) -> Escolha

O modelo de imagem gera **so o fundo** (`E5` §2). O fundo gerado entra numa arte
so com as tres coisas:

1. **um destino autorizado** para a finalidade `geracao_de_imagem` (ADR-008,
   decisao do fundador de 2026-11-21, D3 opcao A): `autorizar(tenant,
   fornecedor, finalidade)` do KAM-069, que levanta sem `apd_ref`. Sem ele, a
   arte usa o fundo do *template* — e **nenhum** pedido sai;
2. **o gerador ligado**. Nao ha adaptador real nem fornecedor pago contratado
   (o bloco nomeia o Gemini, ≈ 0,0336 USD por imagem 1K, `E5`): o
   `GeradorPorLigar` levanta, e a arte usa o fundo do *template*. A chamada ao
   fornecedor fica por ligar, a **falhar fechada**;
3. **o OCR sem texto** (`ocr.py`). Com texto, regera-se ate duas vezes
   (`TENTATIVAS_DO_FUNDO` = 3 pedidos); depois, o fundo do *template*.

## O que vai ao fornecedor

**So o tipo de negocio e o formato**, num pedido escrito por codigo
(`descricao_do_fundo`): nem o nome da loja, nem os factos, nem a legenda, nem a
categoria declarada. E a minimizacao do ADR-008 — o que sai do pais e uma frase
generica que nao identifica o tenant.

## O custo

`custo_usd` soma **todas** as chamadas, as recusadas pelo OCR incluidas: e o
que o fornecedor cobra (a regra do `kamba_core/foto/servico.py`). Uma chamada
que falhou depois de se pagar traz o custo no erro.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from kamba_core.destinos.porta import FINALIDADE_GERACAO_DE_IMAGEM

from .ocr import OcrIndisponivelError, VerificadorDeTexto

#: A finalidade de transferencia do fundo gerado (ADR-008, `0085`): a do dominio.
FINALIDADE: Final = FINALIDADE_GERACAO_DE_IMAGEM

#: O primeiro pedido e duas regeracoes (criterio 3).
TENTATIVAS_DO_FUNDO: Final = 3

GERADO: Final = "gerado"
GRADIENTE: Final = "gradiente"

#: O que se pede por tipo de negocio. **Sem dados do tenant.** Sem digitos.
CENAS: Final = {
    "alimentacao": "uma mesa de madeira clara com loica simples e luz natural",
    "servicos": "um espaco de trabalho arrumado com luz suave",
    "produtos": "uma superficie lisa de estudio com luz difusa",
}

RESTRICOES: Final = "sem texto, sem letras, sem numeros, sem logotipos, sem marcas e sem pessoas"


def descricao_do_fundo(tipo_de_negocio: str, formato: str) -> str:
    """O pedido ao gerador, escrito por codigo. So o tipo e o formato entram."""
    cena = CENAS.get(tipo_de_negocio, CENAS["produtos"])
    enquadramento = "quadrado" if formato == "quadrado" else "vertical"
    return f"Fotografia de fundo, enquadramento {enquadramento}: {cena}; {RESTRICOES}."


@dataclass(frozen=True)
class PedidoDeFundo:
    tipo_de_negocio: str
    formato: str

    @property
    def descricao(self) -> str:
        return descricao_do_fundo(self.tipo_de_negocio, self.formato)


@dataclass(frozen=True)
class Fundo:
    imagem: bytes
    custo_usd: Decimal


class ErroDoGerador(RuntimeError):
    """O gerador falhou. Leva o custo que ja se pagou, se se pagou."""

    def __init__(self, mensagem: str, custo_usd: Decimal = Decimal(0)) -> None:
        super().__init__(mensagem)
        self.custo_usd = custo_usd


class GeradorPorLigarError(ErroDoGerador):
    """Nao ha gerador ligado: nenhum pedido saiu, e nada se pagou."""


class GeradorDeFundos(Protocol):
    nome: str

    def gerar(self, pedido: PedidoDeFundo) -> Fundo: ...


class GeradorPorLigar:
    """O gerador sem adaptador: **falha fechada**, e nenhum pedido sai."""

    nome: Final = "pendente"

    def gerar(self, pedido: PedidoDeFundo) -> Fundo:
        raise GeradorPorLigarError("sem gerador de fundos ligado")


class PortaDeDestinos(Protocol):
    """O `autorizar` do KAM-069: levanta se o destino nao estiver autorizado."""

    def autorizar(self, tenant_id: str, fornecedor: str, finalidade: str) -> None: ...


@dataclass(frozen=True)
class Escolha:
    """O fundo da arte: a cena gerada (`gerado`) ou `None` (o do *template*)."""

    imagem: bytes | None
    fundo: str
    custo_usd: Decimal
    pedidos: int
    #: Porque nao ha cena: `sem_destino`, `por_ligar`, `gerador_falhou`, `com_texto`, ou `None`.
    motivo: str | None = None


def escolher_fundo(
    tenant_id: str,
    pedido: PedidoDeFundo,
    gerador: GeradorDeFundos,
    ocr: VerificadorDeTexto,
    destinos: PortaDeDestinos,
    *,
    antes_de_pedir: Callable[[], None] | None = None,
) -> Escolha:
    """A cena gerada sem texto, ou o fundo do *template*. Nunca levanta.

    `antes_de_pedir` corre uma vez, antes do primeiro pedido que sai (o
    consumo do `imagens_mes`); se levantar, nada sai e a excepcao sobe.
    """
    if isinstance(gerador, GeradorPorLigar):
        return Escolha(None, GRADIENTE, Decimal(0), 0, "por_ligar")
    try:
        destinos.autorizar(tenant_id, gerador.nome, FINALIDADE)
    except Exception:  # noqa: BLE001 — sem destino autorizado, nada sai
        return Escolha(None, GRADIENTE, Decimal(0), 0, "sem_destino")
    if antes_de_pedir is not None:
        antes_de_pedir()
    custo = Decimal(0)
    for pedidos in range(1, TENTATIVAS_DO_FUNDO + 1):
        try:
            fundo = gerador.gerar(pedido)
        except GeradorPorLigarError:
            return Escolha(None, GRADIENTE, custo, pedidos - 1, "por_ligar")
        except ErroDoGerador as erro:
            return Escolha(None, GRADIENTE, custo + erro.custo_usd, pedidos, "gerador_falhou")
        except Exception:  # noqa: BLE001 — um gerador que rebenta nao rebenta a arte
            return Escolha(None, GRADIENTE, custo, pedidos, "gerador_falhou")
        custo += fundo.custo_usd
        try:
            com_texto = ocr.tem_texto(fundo.imagem)
        except OcrIndisponivelError:
            com_texto = True  # falha fechada: sem leitura, o fundo nao entra
        if not com_texto:
            return Escolha(fundo.imagem, GERADO, custo, pedidos)
    return Escolha(None, GRADIENTE, custo, TENTATIVAS_DO_FUNDO, "com_texto")
