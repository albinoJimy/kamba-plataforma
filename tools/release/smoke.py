"""Gate 15, a parte que nao depende do numero de teste real nem do sandbox.

Duas decisoes, e as duas tem de estar certas **antes** de existir o numero:

1. **A guarda.** «Chaves do numero de teste e do sandbox sao distintas das de
   producao; o *smoke* aborta se detectar o numero de producao (teste
   negativo).» `guardar` corre antes de qualquer envio e levanta
   `SmokeAbortado`; o *smoke* nao tem caminho que envie sem passar por ela.
2. **A classificacao.** «Resposta correcta em ≤ 15 s (p95 de 20 execucoes)», «o
   caminho de pedido fecha em `paga` em ≤ 60 s», e «falhas da Meta no *smoke*
   classificam-se `inconclusivo`, nao `verde`».

## A guarda e por lista positiva, nao so negativa

Detectar «o numero de producao» exige saber qual e — e em producao os numeros
sao os dos clientes, chegados pelo Embedded Signup, que este repositorio
publico nao pode listar. Por isso a guarda **nao confia so na lista**:

| Ambiente alvo | Exige |
|---|---|
| `prod`, ou um cujo `meta.modo` seja `producao` | aborta sempre |
| sem `infra/envs/<ambiente>/env.yaml` | aborta: ambiente que ninguem declarou |
| `meta.modo: mock` (o `dev`) | numero no intervalo ficticio do `tools/meta-sim` (`999…`) e base da Graph que **nao** seja a da Meta |
| `meta.modo: numero-de-teste` (o `staging`) | a lista de producao **presente** — sem ela aborta, porque nao se prova que o alvo nao e producao —, o numero e o `phone_number_id` fora dela, e o projecto de segredos diferente do de `prod` |

Em qualquer modo, o projecto de segredos igual ao de `prod` aborta: e a outra
metade do criterio («chaves distintas»), e o `env_lint` ja a prende do lado da
configuracao.

**De onde vem a lista de producao, quando houver producao:** do projecto `prod`
do cofre, lida pelo *job* de *release* com um *token* so de leitura, e passada
por ficheiro. Nao se escreve no repositorio — e publico.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Callable, Iterable

#: O anfitriao da Graph real. Num *smoke* contra o simulador, uma base que o
#: contenha e um *smoke* que ia falar com a Meta.
ANFITRIAO_DA_META = "graph.facebook.com"

#: Do criterio do gate 15.
LIMITE_DA_RESPOSTA_S = 15.0
EXECUCOES_MINIMAS = 20
LIMITE_DO_PAGAMENTO_S = 60.0

VERDE, VERMELHO, INCONCLUSIVO = "verde", "vermelho", "inconclusivo"


class SmokeAbortado(RuntimeError):
    """O alvo e, ou pode ser, producao. Nenhuma mensagem saiu."""


@dataclasses.dataclass(frozen=True)
class Alvo:
    ambiente: str
    numero: str
    phone_number_id: str
    projecto_de_segredos: str
    graph_base: str


@dataclasses.dataclass(frozen=True)
class Producao:
    """O que identifica producao. `numeros is None` = lista desconhecida."""

    projecto: str
    numeros: frozenset[str] | None
    phone_number_ids: frozenset[str] = frozenset()


def _env_yaml(raiz: Path, ambiente: str) -> dict | None:
    from kamba_yaml import load_file

    caminho = raiz / "infra" / "envs" / ambiente / "env.yaml"
    if not caminho.is_file():
        return None
    return load_file(caminho)


def producao_declarada(raiz: Path, numeros: Iterable[str] | None, ids: Iterable[str] = ()) -> Producao:
    """O projecto de `prod` lido do `env.yaml`; a lista vem de fora."""
    prod = _env_yaml(raiz, "prod") or {}
    projecto = str((prod.get("segredos") or {}).get("projecto") or "")
    if not projecto:
        raise SmokeAbortado("infra/envs/prod/env.yaml sem `segredos.projecto`: nao se sabe o que evitar")
    return Producao(
        projecto=projecto,
        numeros=None if numeros is None else frozenset(_digitos(n) for n in numeros),
        phone_number_ids=frozenset(str(i) for i in ids),
    )


def _digitos(numero: str) -> str:
    return "".join(c for c in numero if c.isdigit())


def intervalo_ficticio(raiz: Path) -> tuple[int, int]:
    """O `primeiro` e o `ultimo` do `tools/meta-sim/fake_numbers.yaml`."""
    from kamba_yaml import load_file

    dados = load_file(raiz / "tools" / "meta-sim" / "fake_numbers.yaml")
    return int(dados["primeiro"]), int(dados["ultimo"])


def guardar(alvo: Alvo, producao: Producao, raiz: Path) -> None:
    """Levanta `SmokeAbortado` se o alvo for, ou puder ser, producao."""
    if alvo.ambiente == "prod":
        raise SmokeAbortado("o ambiente alvo e `prod`: o smoke nunca corre em producao")
    declarado = _env_yaml(raiz, alvo.ambiente)
    if declarado is None:
        raise SmokeAbortado(f"infra/envs/{alvo.ambiente}/env.yaml nao existe: ambiente nao declarado")
    modo = str((declarado.get("meta") or {}).get("modo") or "")
    if modo not in ("mock", "numero-de-teste"):
        raise SmokeAbortado(f"`meta.modo` de {alvo.ambiente} e {modo!r}: so `mock` e `numero-de-teste`")
    if alvo.projecto_de_segredos == producao.projecto:
        raise SmokeAbortado(
            f"o projecto de segredos e {producao.projecto!r}, o de producao: as chaves "
            "do smoke tem de ser distintas"
        )

    numero = _digitos(alvo.numero)
    if not numero:
        raise SmokeAbortado("numero alvo vazio")
    if modo == "mock":
        primeiro, ultimo = intervalo_ficticio(raiz)
        if not (len(numero) == len(str(primeiro)) and primeiro <= int(numero) <= ultimo):
            raise SmokeAbortado("em `mock` o numero tem de estar no intervalo ficticio do meta-sim")
        if ANFITRIAO_DA_META in alvo.graph_base:
            raise SmokeAbortado("em `mock` a base da Graph nao pode ser a da Meta")
        return

    # numero-de-teste
    if producao.numeros is None:
        raise SmokeAbortado(
            "sem a lista de numeros de producao nao se prova que o alvo nao e producao"
        )
    if numero in producao.numeros:
        raise SmokeAbortado("o numero alvo e um numero de producao")
    if alvo.phone_number_id in producao.phone_number_ids:
        raise SmokeAbortado("o phone_number_id alvo e de producao")


# --------------------------------------------------------------------------
# Classificacao
# --------------------------------------------------------------------------

#: Os desfechos de uma execucao. `meta_indisponivel` e o unico que nao e do
#: nosso lado, e por isso o unico que da `inconclusivo`.
DESFECHOS = ("ok", "resposta_errada", "sem_resposta", "meta_indisponivel")


@dataclasses.dataclass(frozen=True)
class Execucao:
    desfecho: str
    segundos: float | None = None

    def __post_init__(self) -> None:
        if self.desfecho not in DESFECHOS:
            raise ValueError(f"desfecho {self.desfecho!r}")
        if self.desfecho == "ok" and self.segundos is None:
            raise ValueError("uma execucao `ok` tem tempo medido")


def p95(valores: list[float]) -> float:
    """Percentil 95 por posicao mais proxima (sem interpolacao)."""
    if not valores:
        raise ValueError("p95 de nada")
    ordenados = sorted(valores)
    return ordenados[math.ceil(0.95 * len(ordenados)) - 1]


@dataclasses.dataclass(frozen=True)
class Veredicto:
    estado: str
    razao: str


def classificar(execucoes: list[Execucao]) -> Veredicto:
    erradas = [e for e in execucoes if e.desfecho in ("resposta_errada", "sem_resposta")]
    if erradas:
        return Veredicto(VERMELHO, f"{len(erradas)} execucoes sem a resposta certa")
    oks = [e.segundos for e in execucoes if e.desfecho == "ok" and e.segundos is not None]
    meta = sum(1 for e in execucoes if e.desfecho == "meta_indisponivel")
    if len(oks) < EXECUCOES_MINIMAS:
        return Veredicto(
            INCONCLUSIVO,
            f"{len(oks)} execucoes medidas de {EXECUCOES_MINIMAS} ({meta} com a Meta indisponivel)",
        )
    valor = p95(oks)
    if valor > LIMITE_DA_RESPOSTA_S:
        return Veredicto(VERMELHO, f"p95 {valor:.2f} s > {LIMITE_DA_RESPOSTA_S:g} s")
    if meta:
        # A letra pede 20 medidas, e ha-as; mas uma indisponibilidade no meio
        # diz que o fio ponta a ponta nao esteve inteiro. Nao e verde.
        return Veredicto(INCONCLUSIVO, f"p95 {valor:.2f} s, e {meta} execucoes com a Meta indisponivel")
    return Veredicto(VERDE, f"p95 {valor:.2f} s em {len(oks)} execucoes")


def classificar_pagamento(estado_final: str | None, segundos: float | None, facilitador_disponivel: bool) -> Veredicto:
    """O caminho de pedido: `paga` em ≤ 60 s, ou inconclusivo se o sandbox caiu."""
    if not facilitador_disponivel:
        return Veredicto(INCONCLUSIVO, "o facilitador (ou o sandbox) nao respondeu")
    if estado_final != "paga":
        return Veredicto(VERMELHO, f"o pedido acabou em {estado_final!r} e nao em `paga`")
    if segundos is None or segundos > LIMITE_DO_PAGAMENTO_S:
        return Veredicto(VERMELHO, f"`paga` em {segundos} s; o limite e {LIMITE_DO_PAGAMENTO_S:g} s")
    return Veredicto(VERDE, f"`paga` em {segundos:.1f} s")


def correr(
    alvo: Alvo,
    producao: Producao,
    raiz: Path,
    uma_execucao: Callable[[Alvo], Execucao],
    vezes: int = EXECUCOES_MINIMAS,
) -> Veredicto:
    """A guarda primeiro, e so depois as execucoes. Um aborto nao envia nada."""
    guardar(alvo, producao, raiz)
    return classificar([uma_execucao(alvo) for _ in range(vezes)])
