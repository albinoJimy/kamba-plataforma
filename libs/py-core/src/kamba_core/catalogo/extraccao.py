"""O que a visao devolve, e como cada campo guarda a sua proveniencia (KAM-049, criterio 4).

## A resposta da visao e dado nao fiavel

O texto escrito numa foto chega aqui pela boca do modelo, e o modelo pode ter
sido convencido por ele (injeccao indirecta, criterio 8). Por isso esta leitura
**nao confia em nada** da resposta:

* so se le um objecto JSON; o resto e `ExtraccaoInvalida`;
* so os campos de `CAMPOS_DA_VISAO` entram; uma chave a mais (`"estado"`,
  `"publicar"`, `"preco"`) ignora-se — o modelo nao escreve no estado da
  ingestao, so em campos de produto;
* cada valor e texto (ou lista de textos, nas variantes), sem caracteres de
  controlo e cortado a `MAXIMO_DO_VALOR`;
* a `confianca` e um numero em [0, 1] — `true`, `"1"`, `1.5` ou `NaN` contam
  como zero, que e o valor que obriga a perguntar;
* a fonte e **sempre** `ia_visao` e o `confirmado` e **sempre** `False`, diga a
  resposta o que disser: nao ha campo do modelo que os preencha.

## O preco lido de uma etiqueta e so sugestao

`preco_etiqueta` nao e um campo do produto: e o `preco_sugerido`, que o resumo
mostra ao dono como «vi 45 mil na etiqueta» e que **nunca** passa a `preco`
sem resposta dele (criterio 5, ADR-007 «numeros so de *tools*»). A primeira
pergunta e sempre o `preco_tipo`, haja etiqueta ou nao.

## O limiar

`LIMIAR_IA_VISAO = 0,8` e *proposta* do bloco, a calibrar com o conjunto de
avaliacao. Um campo `ia_visao` abaixo dele **conta como em falta** para a
completude: e perguntado, e so depois de o dono responder e visivel. Acima
dele tambem nao e visivel ao cliente sem confirmacao — a confirmacao do resumo
(etapa 9) e que o torna `confirmado`.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Final

#: Os campos que a visao pode preencher, pela ordem do criterio 4.
CAMPOS_DA_VISAO: Final = (
    "nome",
    "marca",
    "categoria",
    "cor",
    "tamanho",
    "material",
    "unidade",
    "variantes",
)

#: A chave da sugestao de preco na resposta da visao.
CHAVE_DA_ETIQUETA: Final = "preco_etiqueta"

#: As quatro proveniencias do §8.3, pela ordem do criterio 4.
DONO_TEXTO: Final = "dono_texto"
DONO_VOZ: Final = "dono_voz"
IA_VISAO: Final = "ia_visao"
IMPORTADO: Final = "importado"
FONTES: Final = (DONO_TEXTO, DONO_VOZ, IA_VISAO, IMPORTADO)
FONTES_DO_DONO: Final = frozenset({DONO_TEXTO, DONO_VOZ})

#: *Proposta* do bloco (criterio 4), a calibrar.
LIMIAR_IA_VISAO: Final = Decimal("0.8")

MAXIMO_DO_VALOR: Final = 200
MAXIMO_DE_VARIANTES: Final = 20
#: Uma resposta maior do que isto nao se interpreta: o `max_tokens` do alias e
#: 512 (`llm/aliases.yaml`), e uma resposta de 64 KiB nao veio do modelo.
MAXIMO_DA_RESPOSTA: Final = 65_536


class ExtraccaoInvalida(ValueError):
    """A resposta da visao nao e um objecto JSON com a forma esperada."""


@dataclass(frozen=True)
class Campo:
    """Um campo do produto com a sua proveniencia (§8.3).

    `corrigido` diz que o dono trocou um valor que veio da visao: e o
    numerador da metrica «% de campos `ia_visao` corrigidos» (criterio 9).
    """

    valor: str | tuple[str, ...]
    confianca: Decimal
    fonte: str
    confirmado: bool = False
    corrigido: bool = False

    def __post_init__(self) -> None:
        if self.fonte not in FONTES:
            raise ValueError(f"fonte `{self.fonte}` fora de {FONTES}")
        if not Decimal(0) <= self.confianca <= Decimal(1):
            raise ValueError("confianca fora de [0, 1]")

    @property
    def abaixo_do_limiar(self) -> bool:
        """Um campo da visao que nao se usa sem pergunta."""
        return self.fonte == IA_VISAO and not self.confirmado and self.confianca < LIMIAR_IA_VISAO

    @property
    def visivel_ao_cliente(self) -> bool:
        """So o que o dono confirmou, ou o que ele proprio escreveu ou importou."""
        return self.confirmado or self.fonte != IA_VISAO

    def como_dict(self) -> dict[str, Any]:
        valor: Any = list(self.valor) if isinstance(self.valor, tuple) else self.valor
        return {
            "valor": valor,
            "confianca": str(self.confianca),
            "fonte": self.fonte,
            "confirmado": self.confirmado,
            "corrigido": self.corrigido,
        }

    @classmethod
    def de_dict(cls, dados: Mapping[str, Any]) -> Campo:
        bruto = dados["valor"]
        valor = tuple(str(v) for v in bruto) if isinstance(bruto, list) else str(bruto)
        return cls(
            valor=valor,
            confianca=Decimal(str(dados["confianca"])),
            fonte=str(dados["fonte"]),
            confirmado=bool(dados.get("confirmado", False)),
            corrigido=bool(dados.get("corrigido", False)),
        )


def do_dono(valor: str | tuple[str, ...], fonte: str = DONO_TEXTO, anterior: Campo | None = None) -> Campo:
    """Um campo respondido pelo dono: confirmado, e `corrigido` se trocou a visao."""
    if fonte not in FONTES_DO_DONO:
        raise ValueError(f"o dono responde por `{DONO_TEXTO}` ou `{DONO_VOZ}`, nao por `{fonte}`")
    corrigido = anterior is not None and anterior.fonte == IA_VISAO and anterior.valor != valor
    return Campo(valor=valor, confianca=Decimal(1), fonte=fonte, confirmado=True, corrigido=corrigido or (anterior is not None and anterior.corrigido))


def confirmar(campo: Campo) -> Campo:
    """O campo depois de o dono confirmar o resumo onde ele aparecia."""
    return replace(campo, confirmado=True)


def limpar_texto(bruto: object) -> str | None:
    if not isinstance(bruto, str):
        return None
    # Sem caracteres de controlo nem de formatacao (`Cc`, `Cf`): um texto com
    # `‮` ou um `\n` no meio nao e um nome de produto, e e assim que uma
    # instrucao se esconde de quem le o resumo.
    # O espaco em branco de controlo (`\n`, `\t`) passa a espaco antes: sem isto
    # «azul\nIgnore» colava em «azulIgnore».
    limpo = "".join(
        " " if c.isspace() else c for c in bruto if c.isspace() or unicodedata.category(c) not in ("Cc", "Cf")
    )
    limpo = " ".join(limpo.split())[:MAXIMO_DO_VALOR]
    return limpo or None


def _confianca(bruto: object) -> Decimal:
    # `bool` e subclasse de `int`: um `true` nao e 1,0.
    if isinstance(bruto, bool) or not isinstance(bruto, int | float):
        return Decimal(0)
    if isinstance(bruto, float) and not math.isfinite(bruto):
        return Decimal(0)
    if not 0 <= bruto <= 1:
        return Decimal(0)
    return Decimal(str(bruto)).quantize(Decimal("0.001"))


@dataclass(frozen=True)
class Extraccao:
    """Os campos lidos da foto, e a sugestao de preco que nunca e preco."""

    campos: Mapping[str, Campo]
    preco_etiqueta: str | None = None
    chaves_ignoradas: int = 0


def ler_resposta_da_visao(texto: str) -> Extraccao:
    """Interpreta a resposta do modelo. Levanta `ExtraccaoInvalida`."""
    if len(texto) > MAXIMO_DA_RESPOSTA:
        raise ExtraccaoInvalida("resposta da visao maior do que o tecto")
    try:
        dados = json.loads(texto)
    except (ValueError, RecursionError) as erro:
        raise ExtraccaoInvalida("a resposta da visao nao e JSON") from erro
    if not isinstance(dados, dict):
        raise ExtraccaoInvalida("a resposta da visao nao e um objecto")
    campos: dict[str, Campo] = {}
    for nome in CAMPOS_DA_VISAO:
        entrada = dados.get(nome)
        if not isinstance(entrada, dict):
            continue
        bruto = entrada.get("valor")
        valor: str | tuple[str, ...] | None
        if nome == "variantes":
            if not isinstance(bruto, list):
                continue
            lidas = tuple(t for t in (limpar_texto(v) for v in bruto[:MAXIMO_DE_VARIANTES]) if t)
            valor = lidas or None
        else:
            valor = limpar_texto(bruto)
        if valor is None:
            continue
        campos[nome] = Campo(valor=valor, confianca=_confianca(entrada.get("confianca")), fonte=IA_VISAO)
    etiqueta = dados.get(CHAVE_DA_ETIQUETA)
    preco = limpar_texto(etiqueta.get("valor")) if isinstance(etiqueta, dict) else limpar_texto(etiqueta)
    conhecidas = set(CAMPOS_DA_VISAO) | {CHAVE_DA_ETIQUETA}
    return Extraccao(
        campos=campos,
        preco_etiqueta=preco,
        chaves_ignoradas=sum(1 for chave in dados if chave not in conhecidas),
    )
