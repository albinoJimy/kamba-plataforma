"""A interface `ImageProvider` e a configuracao dos fornecedores (KAM-120).

## A interface, e onde ela diverge da letra do bloco

O criterio 1 escreve `ImageProvider.enhance(imageRef, opts) → {versaoRef,
custoUsd, provider, latenciaMs}`. **O contrato de referencias e o do
`enhance_image`** (o `ServicoDeFoto`): recebe a chave do original no STO e
devolve a chave da versao, o custo, o fornecedor e a latencia. O adaptador de
fornecedor, por baixo, recebe **bytes** e devolve bytes, e a razao e a regra
do bloco: o que sai do pais e a imagem **depois** da minimizacao (sem EXIF,
reduzida, sem rostos nem matriculas). Uma referencia entregue a um terceiro
deixava-o ir buscar o original, e a minimizacao passava a ser opcional.

Os adaptadores sao intermutaveis porque o servico so conhece este `Protocol`:
trocar o primario pela contingencia, ou um fornecedor por outro depois do
*bake-off*, e configuracao, e o `enhance_image` nao muda.

**Nenhum adaptador real existe neste ticket**, e e deliberado: sem fornecedor
pago nem chave, um adaptador HTTP seria um nome de parametro inventado. O
*bake-off* (`bakeoff.py`) e quem escolhe primario e contingencia, e os
adaptadores nascem com essa decisao.

## A configuracao, e o que ela recusa no arranque

* **Lista de recusa** (criterio 6): a Black Forest Labs (licenca perpetua de
  treino com *inputs* e *outputs*) e o remove.bg (passa para a Leonardo.Ai a
  2026-12-01), pelo E5. O nome compara-se **normalizado** — minusculas e so
  letras e digitos —, porque `Remove.bg`, `remove_bg` e `removebg` sao o mesmo
  fornecedor e uma lista que so casasse a grafia exacta deixava passar as
  outras duas.
* **So o *tier* pago** (criterio 5): `tier` e obrigatorio e tem de ser `pago`.
  **Reconhecer uma chave de *tier* gratuito pela forma dela e NAO VERIFICADO**
  — nenhum dos candidatos publica a diferenca —, pelo que o que se impoe e a
  declaracao. A leitura esta escrita no bloco.
* **`real_data_ok`** (criterio 8): `False` por omissao. Um fornecedor sem a
  carta de nao-treino, retencao e regiao arquivada so recebe imagens
  sinteticas.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol, runtime_checkable

OPERACAO_CUTOUT: Final = "cutout"
OPERACAO_FUNDO_SIMPLES: Final = "fundo_simples"
OPERACAO_LUZ_BASICA: Final = "luz_basica"
OPERACAO_VARIACAO_LIFESTYLE: Final = "variacao_lifestyle"

#: As quatro operacoes do criterio 1, pela ordem do `CHECK`.
OPERACOES: Final = (OPERACAO_CUTOUT, OPERACAO_FUNDO_SIMPLES, OPERACAO_LUZ_BASICA, OPERACAO_VARIACAO_LIFESTYLE)

#: As que geram conteudo, e levam a etiqueta. E a coluna gerada
#: `image_jobs.gerado_por_ia` (`operacao = 'variacao_lifestyle'`).
GENERATIVAS: Final = frozenset({OPERACAO_VARIACAO_LIFESTYLE})

#: A etiqueta que acompanha uma versao generativa, para quem a mostra ao dono.
ETIQUETA_GERADA: Final = "gerada por IA"

TIER_PAGO: Final = "pago"

#: O *timeout* do criterio 9: 45 s, depois a contingencia uma vez.
TIMEOUT_S: Final = 45.0

#: A forma de um fornecedor: o `provider` da `0036` e da `image_jobs`.
FORMA_DO_FORNECEDOR: Final = re.compile(r"[a-z][a-z0-9_-]{1,62}")

#: A lista de recusa do criterio 6, **normalizada** e procurada como
#: **subcadeia** do nome normalizado (ver a nota do modulo). A primeira versao
#: comparava por igualdade e pelas partes entre `-`/`_`, e a revisao
#: adversarial mostrou `remove-bg-api`, `black-forest` e `black-forest-labs-api`
#: a passar. Uma subcadeia recusa de mais (um `influx` cai no `flux`), e e o
#: lado seguro: o nome do adaptador escolhe-se, e escolhe-se outro.
RECUSADOS: Final[dict[str, str]] = {
    "blackforest": "Black Forest Labs: licenca perpetua de treino com inputs e outputs (E5)",
    "bfl": "Black Forest Labs: licenca perpetua de treino com inputs e outputs (E5)",
    "flux": "o modelo da Black Forest Labs, pela mesma licenca (E5)",
    "removebg": "remove.bg: passa para a Leonardo.Ai a 2026-12-01 (E5)",
}


def normalizar_nome(nome: str) -> str:
    """Minusculas e so `[a-z0-9]`: `Remove.bg`, `remove_bg` e `removebg` sao um."""
    return re.sub(r"[^a-z0-9]", "", nome.lower())


class FornecedorRecusado(ValueError):
    """O arranque recusa: fornecedor na lista de recusa, *tier* ou forma invalidos."""


@dataclass(frozen=True)
class Opcoes:
    operacao: str
    timeout_s: float = TIMEOUT_S


@dataclass(frozen=True)
class Melhoria:
    """O que um adaptador devolve. A `imagem` e a versao, ja descarregada.

    Sem latencia: quem a mede e o servico, com o seu relogio, e nao o
    fornecedor a dizer quanto demorou.
    """

    imagem: bytes
    custo_usd: Decimal
    provider: str
    #: O identificador do resultado no fornecedor, para o apagar la. `None`
    #: quando a API nao guarda nada.
    ref_no_fornecedor: str | None = None


class ErroDoFornecedor(RuntimeError):
    """O fornecedor falhou. Leva o custo que ja se pagou, se se pagou."""

    def __init__(self, mensagem: str, custo_usd: Decimal = Decimal(0)) -> None:
        super().__init__(mensagem)
        self.custo_usd = custo_usd


@runtime_checkable
class ImageProvider(Protocol):
    """Um adaptador de fornecedor de imagem. Intermutavel: o servico so ve isto."""

    nome: str
    tier: str
    real_data_ok: bool

    def enhance(self, imagem: bytes, opcoes: Opcoes) -> Melhoria:
        """A versao melhorada. Levanta `TimeoutError` ao fim de `opcoes.timeout_s`."""
        ...

    def apagar(self, ref_no_fornecedor: str) -> bool:
        """Apaga o resultado no fornecedor; `False` se a API nao o permitir."""
        ...


def validar_fornecedor(fornecedor: ImageProvider) -> None:
    """Uma entrada da configuracao. Levanta `FornecedorRecusado`."""
    nome = getattr(fornecedor, "nome", None)
    if not isinstance(nome, str) or not FORMA_DO_FORNECEDOR.fullmatch(nome):
        raise FornecedorRecusado("o nome de um fornecedor tem a forma do `provider` da `0036`")
    normalizado = normalizar_nome(nome)
    razao = next((r for marca, r in sorted(RECUSADOS.items()) if marca in normalizado), None)
    if razao is not None:
        raise FornecedorRecusado(f"fornecedor `{nome}` na lista de recusa: {razao}")
    if getattr(fornecedor, "tier", None) != TIER_PAGO:
        raise FornecedorRecusado(f"fornecedor `{nome}`: so o tier `{TIER_PAGO}` e aceite")
    if not isinstance(getattr(fornecedor, "real_data_ok", None), bool):
        raise FornecedorRecusado(f"fornecedor `{nome}`: `real_data_ok` e booleano e explicito")


def validar_configuracao(fornecedores: Iterable[ImageProvider]) -> tuple[ImageProvider, ...]:
    """A configuracao inteira, no arranque: um a dois fornecedores, sem repetidos.

    O primeiro e o primario e o segundo, se houver, a contingencia do
    criterio 9 (uma vez).
    """
    lista = tuple(fornecedores)
    if not 1 <= len(lista) <= 2:
        raise FornecedorRecusado("um primario e, no maximo, uma contingencia")
    for fornecedor in lista:
        validar_fornecedor(fornecedor)
    if len({f.nome for f in lista}) != len(lista):
        raise FornecedorRecusado("o primario e a contingencia sao fornecedores diferentes")
    return lista
