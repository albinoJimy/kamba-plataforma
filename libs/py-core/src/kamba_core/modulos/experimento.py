"""O experimento dos modulos de entrada: limiares, Wilson e a regra de decisao (KAM-127).

    from kamba_core.modulos import experimento
    l = experimento.ler(Path("config/experimento_modulos.yaml"))
    experimento.wilson(6, 10)                 # (0.3127, 0.8318), 95%
    experimento.decidir(medicao, l)           # Decisao(modulo, decisao, criterios, ...)

Tudo aqui e **puro**: nao le a base nem o relogio. As medicoes vem das vistas
`platform.v_h10`, `platform.v_h11` e `platform.v_h12` (e o
`db/experimento_modulos.py` monta-as); a decisao que sai daqui so fica escrita
quando um humano a regista em `platform.module_decisions` com o nome dele.

## A regra, pre-registada (bloco do KAM-127)

Por modulo, pela ordem:

1. **abater** se (a) o uso aos 14 dias esta abaixo de `abate_uso_minimo_pct`,
   ou (c) houve incidentes de conteudo na janela — >= `abate_incidentes_alta`
   de gravidade alta, ou >= `abate_incidentes_media` de media;
2. **ajustar** se (b) o custo passou `abate_custo_maximo_pct` do preco de teste
   em `abate_semanas_de_custo` semanas seguidas, ou a margem foi negativa, ou
   algum criterio esta a `ajuste_margem_pct` do seu limiar;
3. **manter** se tudo esta dentro.

**(d) o `catalogo` nunca se abate** (ADR-020): onde a regra diria «abater», diz
«ajustar», e o criterio que o accionou fica registado na mesma.

## O que a regra nao decide

* **Sem coorte, nao ha decisao.** Com N = 0 o uso nao se mede e o criterio (a)
  nao se avalia: `decidir` devolve `decisao=None` com `motivo`
  `dados_insuficientes`, que e a «justificacao de dados insuficientes» da DoD.
  Nao se inventou um N minimo: com N pequeno o intervalo de Wilson e largo, e
  e o intervalo — que sai sempre — que o diz a quem le.
* **A proximidade do limiar** («a <= 10% do limiar») le-se como a margem
  relativa ao proprio limiar: o uso esta perto quando fica abaixo de
  `limiar * (1 + margem)`, e o custo da ultima semana completa quando passa
  `limiar * (1 - margem)`. E uma leitura e esta escrita; a letra do bloco nao
  diz se os 10% sao relativos ou absolutos. **Nao se aplica aos incidentes**:
  sao contagens inteiras com limiares de 1 e 3, e «a 10% de 3» seria 2,7 — nao
  ha contagem entre o 2 (dentro) e o 3 (abate).
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field, fields
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

from .uso import MODULOS_DE_ENTRADA

#: A unica versao do formato que este leitor conhece.
VERSAO: Final = 1

#: O quantil da normal para 95% bilateral (o «intervalo de Wilson 95%» do bloco).
Z_95: Final = 1.959963984540054

#: O modulo que nunca se abate (ADR-020; criterio de abate (d)).
MODULO_QUE_NAO_SE_ABATE: Final = "catalogo"

#: As tres decisoes do bloco, e so elas — o `CHECK` de `module_decisions.decisao`.
DECISOES: Final = ("manter", "ajustar", "abater")

#: Os criterios que a regra pode accionar, com o nome que fica em
#: `module_decisions.criterio`.
CRITERIO_USO: Final = "a_uso"
CRITERIO_CUSTO: Final = "b_custo"
CRITERIO_MARGEM: Final = "b_margem_negativa"
CRITERIO_INCIDENTES: Final = "c_incidentes"
CRITERIO_PERTO: Final = "perto_do_limiar"
CRITERIO_CATALOGO: Final = "d_catalogo_nao_se_abate"

MOTIVO_SEM_DADOS: Final = "dados_insuficientes"

_LINHA = re.compile(r"^([a-z][a-z0-9_]*):\s*(\S+)\s*$")


class LimiaresInvalidos(ValueError):
    """O ficheiro nao tem a forma, ou falta-lhe ou sobra-lhe uma chave."""


@dataclass(frozen=True)
class Limiares:
    """Os limiares do experimento, todos *proposta*. Percentagens em pontos."""

    h10_limiar_pct: int
    h11_limiar_pct: int
    h12_custo_pct: int
    h12_pagantes: int
    janela_de_uso_dias: int
    janela_de_activacao_dias: int
    abate_uso_minimo_pct: int
    abate_custo_maximo_pct: int
    abate_semanas_de_custo: int
    abate_incidentes_alta: int
    abate_incidentes_media: int
    abate_janela_de_incidentes_dias: int
    ajuste_margem_pct: int

    def __post_init__(self) -> None:
        for nome in (n for n in CHAVES if n.endswith("_pct")):
            if getattr(self, nome) > 100:
                raise LimiaresInvalidos(f"{nome} acima de 100: uma percentagem nao passa os 100")


CHAVES: Final = tuple(f.name for f in fields(Limiares))


def interpretar(texto: str) -> Limiares:
    """Le o texto do ficheiro. Falha fechado, como o `kpis.limiares` do KAM-117."""
    valores: dict[str, int] = {}
    versao: int | None = None
    for numero, linha in enumerate(texto.splitlines(), start=1):
        limpa = linha.split("#", 1)[0].strip()
        if not limpa:
            continue
        casou = _LINHA.match(limpa)
        if casou is None:
            raise LimiaresInvalidos(f"linha {numero}: nao e `chave: inteiro`: {linha!r}")
        chave, cru = casou.groups()
        if not cru.isdigit():
            raise LimiaresInvalidos(f"linha {numero}: {chave} nao e inteiro: {cru!r}")
        valor = int(cru)
        if chave == "version":
            versao = valor
            continue
        if chave not in CHAVES:
            raise LimiaresInvalidos(f"linha {numero}: chave desconhecida {chave!r}")
        if chave in valores:
            raise LimiaresInvalidos(f"linha {numero}: {chave} repetida")
        if valor <= 0:
            raise LimiaresInvalidos(f"linha {numero}: {chave} tem de ser positivo")
        valores[chave] = valor
    if versao != VERSAO:
        raise LimiaresInvalidos(f"version {versao!r}; este leitor so conhece {VERSAO}")
    faltam = [c for c in CHAVES if c not in valores]
    if faltam:
        raise LimiaresInvalidos(f"faltam chaves: {', '.join(faltam)}")
    return Limiares(**valores)


def ler(caminho: Path) -> Limiares:
    return interpretar(caminho.read_text(encoding="utf-8"))


# --------------------------------------------------------------------- Wilson
def wilson(n: int, total: int, z: float = Z_95) -> tuple[float, float] | None:
    """O intervalo de Wilson de `n` sucessos em `total`, com quatro casas.

    `None` com `total = 0`: sem coorte nao ha proporcao, e devolver `(0, 1)` era
    dar um intervalo a uma medicao que nao se fez.
    """
    if isinstance(n, bool) or isinstance(total, bool) or not isinstance(n, int) or not isinstance(total, int):
        raise TypeError("n e total sao inteiros")
    if total < 0 or n < 0 or n > total:
        raise ValueError(f"n={n} e total={total}: precisa-se de 0 <= n <= total")
    if total == 0:
        return None
    p = n / total
    z2 = z * z
    denominador = 1 + z2 / total
    centro = (p + z2 / (2 * total)) / denominador
    meia = z * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total)) / denominador
    return (round(max(0.0, centro - meia), 4), round(min(1.0, centro + meia), 4))


@dataclass(frozen=True)
class Proporcao:
    """`n` de `total`, com o intervalo — a forma em que toda a leitura sai."""

    n: int
    total: int
    proporcao: float | None
    wilson_95: tuple[float, float] | None

    @classmethod
    def de(cls, n: int, total: int) -> "Proporcao":
        return cls(
            n=n,
            total=total,
            proporcao=None if total == 0 else round(n / total, 4),
            wilson_95=wilson(n, total),
        )


@dataclass(frozen=True)
class LeituraDeHipotese:
    """Uma hipotese medida contra o limiar pre-registado."""

    hipotese: str
    medida: Proporcao
    limiar_pct: int
    #: `None` sem coorte; senao, se a proporcao pontual chega ao limiar. O
    #: intervalo vai ao lado: com N pequeno, «cumpre» com um Wilson que desce
    #: abaixo do limiar e uma leitura fraca, e e o relatorio que o diz.
    cumpre: bool | None


def ler_hipotese(hipotese: str, n: int, total: int, limiar_pct: int) -> LeituraDeHipotese:
    medida = Proporcao.de(n, total)
    cumpre = None if total == 0 else Fraction(n, total) >= Fraction(limiar_pct, 100)
    return LeituraDeHipotese(hipotese=hipotese, medida=medida, limiar_pct=limiar_pct, cumpre=cumpre)


# ------------------------------------------------------------------ a decisao
@dataclass(frozen=True)
class MedicaoDoModulo:
    """O que a regra de decisao le de um modulo, numa leitura.

    `custo_racios_semanais` sao os racios custo / preco de teste das ultimas
    semanas, a mais recente no fim (`v_h12`, agregado por semana); `None` numa
    semana sem preco de teste. Os incidentes sao os da janela de
    `abate_janela_de_incidentes_dias`, contados a mao a partir do golden e da
    auditoria do KAM-125 — nao ha tabela de incidentes de conteudo.
    """

    modulo: str
    usaram: int
    coorte: int
    custo_racios_semanais: tuple[float | None, ...] = ()
    margem_negativa: bool = False
    incidentes_alta: int = 0
    incidentes_media: int = 0

    def __post_init__(self) -> None:
        if self.modulo not in MODULOS_DE_ENTRADA:
            raise ValueError(f"modulo desconhecido: {self.modulo!r}")
        if self.coorte < 0 or self.usaram < 0 or self.usaram > self.coorte:
            raise ValueError(f"usaram={self.usaram} e coorte={self.coorte}")
        if self.incidentes_alta < 0 or self.incidentes_media < 0:
            raise ValueError("incidentes negativos")


@dataclass(frozen=True)
class Decisao:
    """A decisao proposta pela regra para um modulo. Nao e registo: e proposta."""

    modulo: str
    decisao: str | None
    criterios: tuple[str, ...]
    uso: Proporcao
    motivo: str | None = None
    detalhe: dict[str, Any] = field(default_factory=dict)

    @property
    def criterio(self) -> str | None:
        """A coluna `module_decisions.criterio`: os accionados, por virgula."""
        return ",".join(self.criterios) or None

    def metricas(self) -> dict[str, Any]:
        """O `jsonb` de `module_decisions.metricas`: n/N, Wilson e o resto."""
        uso = asdict(self.uso)
        uso["wilson_95"] = list(self.uso.wilson_95) if self.uso.wilson_95 else None
        return {"uso": uso, **self.detalhe}


def _semanas_seguidas_acima(racios: tuple[float | None, ...], limiar: Fraction) -> int:
    """Quantas das ultimas semanas, seguidas, passaram o limiar."""
    seguidas = 0
    for racio in reversed(racios):
        if racio is None or Fraction(str(racio)) <= limiar:
            break
        seguidas += 1
    return seguidas


def decidir(medicao: MedicaoDoModulo, limiares: Limiares) -> Decisao:
    """A regra pre-registada do bloco, aplicada a um modulo."""
    uso = Proporcao.de(medicao.usaram, medicao.coorte)
    margem = Fraction(limiares.ajuste_margem_pct, 100)
    custo_limiar = Fraction(limiares.abate_custo_maximo_pct, 100)
    seguidas = _semanas_seguidas_acima(medicao.custo_racios_semanais, custo_limiar)
    ultimo = next((r for r in reversed(medicao.custo_racios_semanais) if r is not None), None)
    detalhe: dict[str, Any] = {
        "custo_racios_semanais": list(medicao.custo_racios_semanais),
        "custo_semanas_seguidas_acima": seguidas,
        "margem_negativa": medicao.margem_negativa,
        "incidentes_alta": medicao.incidentes_alta,
        "incidentes_media": medicao.incidentes_media,
        "limiares": {
            "abate_uso_minimo_pct": limiares.abate_uso_minimo_pct,
            "abate_custo_maximo_pct": limiares.abate_custo_maximo_pct,
            "abate_semanas_de_custo": limiares.abate_semanas_de_custo,
            "abate_incidentes_alta": limiares.abate_incidentes_alta,
            "abate_incidentes_media": limiares.abate_incidentes_media,
            "ajuste_margem_pct": limiares.ajuste_margem_pct,
        },
    }
    if medicao.coorte == 0:
        return Decisao(medicao.modulo, None, (), uso, motivo=MOTIVO_SEM_DADOS, detalhe=detalhe)

    uso_frac = Fraction(medicao.usaram, medicao.coorte)
    uso_limiar = Fraction(limiares.abate_uso_minimo_pct, 100)

    para_abater: list[str] = []
    if uso_frac < uso_limiar:
        para_abater.append(CRITERIO_USO)
    if (
        medicao.incidentes_alta >= limiares.abate_incidentes_alta
        or medicao.incidentes_media >= limiares.abate_incidentes_media
    ):
        para_abater.append(CRITERIO_INCIDENTES)

    para_ajustar: list[str] = []
    if seguidas >= limiares.abate_semanas_de_custo:
        para_ajustar.append(CRITERIO_CUSTO)
    if medicao.margem_negativa:
        para_ajustar.append(CRITERIO_MARGEM)
    perto = uso_frac < uso_limiar * (1 + margem) or (
        ultimo is not None and Fraction(str(ultimo)) > custo_limiar * (1 - margem)
    )
    if perto and not para_abater:
        para_ajustar.append(CRITERIO_PERTO)

    if para_abater:
        if medicao.modulo == MODULO_QUE_NAO_SE_ABATE:
            criterios = (*para_abater, *para_ajustar, CRITERIO_CATALOGO)
            return Decisao(medicao.modulo, "ajustar", criterios, uso, detalhe=detalhe)
        return Decisao(medicao.modulo, "abater", (*para_abater, *para_ajustar), uso, detalhe=detalhe)
    if para_ajustar:
        return Decisao(medicao.modulo, "ajustar", tuple(para_ajustar), uso, detalhe=detalhe)
    return Decisao(medicao.modulo, "manter", (), uso, detalhe=detalhe)
