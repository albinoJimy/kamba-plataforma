"""A folha de passos com carimbos — o relogio comum do simulacro (KAM-085).

Os sete passos sao os do criterio 1 do bloco, pela ordem do orcamento do
`docs/tecnica/09` §8.2: deteccao, decisao, IaC, restauro, *replay*,
verificacao e DNS. O orcamento soma **105 min**, e o §8.2 orca a verificacao e
o DNS **juntos** (15 min): por isso os dois passos partilham uma rubrica, e a
comparacao com o orcamento faz-se por rubrica e nao por passo.

## Um carimbo e uma linha de JSON

    {"cenario": "A", "passo": "restauro", "evento": "inicio",
     "em": "2026-11-08T10:00:00.123456Z", "nota": "..."}

`evento` e `inicio`, `fim` ou `nao_medido`. O terceiro existe porque o modo de
falha que esta folha fecha e **preencher um passo que ninguem cronometrou com o
numero do orcamento**: um RTO de 105 min «medido» em que 60 min sao o
orcamento copiado nao e uma medicao. Um passo `nao_medido` leva a razao e entra
no RTO **composto** (dito como tal), nunca no **medido**.

## O relogio

Todos os carimbos de um cenario vem do mesmo relogio — o do processo que
conduz o ensaio — e em UTC com microssegundos. Os marcadores (`marcadores.py`)
levam o instante da **base**, e o RPO calcula-se so com esses: misturar os dois
relogios num subtraccao era medir o desvio entre eles e chamar-lhe RPO.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: Os passos, pela ordem do criterio 1, e a rubrica do orcamento de cada um.
PASSOS: tuple[tuple[str, str], ...] = (
    ("deteccao", "deteccao"),
    ("decisao", "decisao"),
    ("iac", "iac"),
    ("restauro", "restauro"),
    ("replay", "replay"),
    ("verificacao", "verificacao_e_dns"),
    ("dns", "verificacao_e_dns"),
)

#: Passos que so um cenario tem. O `cofre` e o do cenario C: decifrar a
#: exportacao offline quando o cofre nao responde. O §8.2 nao o orca — e por
#: isso a rubrica tem orcamento **zero**, e todo o tempo dele e o «RTO
#: adicional» que o criterio 4 manda registar.
PASSOS_OPCIONAIS: tuple[tuple[str, str], ...] = (("cofre", "cofre"),)

#: O orcamento do `docs/tecnica/09` §8.2, em minutos, por rubrica. ESTIMATIVA
#: no proprio documento; e o termo de comparacao, nao um valor medido.
#: O `restauro` e o da linha «BD <= 20 GB ~ 30 min em 100 Mbps».
ORCAMENTO_MIN: dict[str, float] = {
    "deteccao": 10,
    "decisao": 10,
    "iac": 30,
    "restauro": 30,
    "replay": 10,
    "verificacao_e_dns": 15,
    "cofre": 0,
}

#: O restauro orcado para 50 GB, na mesma linha do §8.2.
ORCAMENTO_RESTAURO_50GB_MIN = 70

EVENTOS = ("inicio", "fim", "nao_medido")


class FolhaInvalida(ValueError):
    """A folha nao se le, ou diz uma coisa impossivel."""


@dataclass(frozen=True)
class Carimbo:
    cenario: str
    passo: str
    evento: str
    em: datetime | None
    nota: str = ""

    def como_dict(self) -> dict:
        carga = {"cenario": self.cenario, "passo": self.passo, "evento": self.evento}
        if self.em is not None:
            carga["em"] = formatar(self.em)
        if self.nota:
            carga["nota"] = self.nota
        return carga


def formatar(instante: datetime) -> str:
    """ISO 8601 em UTC com microssegundos e `Z`. Recusa instantes sem fuso."""
    if instante.tzinfo is None:
        raise FolhaInvalida("instante sem fuso: a folha so aceita UTC explicito")
    return instante.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def ler_instante(texto: str) -> datetime:
    """O inverso de `formatar`, e aceita tambem `+00:00`. Recusa sem fuso."""
    try:
        instante = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError as erro:
        raise FolhaInvalida(f"instante ilegivel: {texto!r}") from erro
    if instante.tzinfo is None:
        raise FolhaInvalida(f"instante sem fuso: {texto!r}")
    return instante.astimezone(timezone.utc)


def _de_dict(carga: dict, onde: str) -> Carimbo:
    for chave in ("cenario", "passo", "evento"):
        if not isinstance(carga.get(chave), str) or not carga[chave]:
            raise FolhaInvalida(f"{onde}: falta `{chave}`")
    if carga["passo"] not in dict(PASSOS + PASSOS_OPCIONAIS):
        raise FolhaInvalida(f"{onde}: passo desconhecido `{carga['passo']}`")
    if carga["evento"] not in EVENTOS:
        raise FolhaInvalida(f"{onde}: evento desconhecido `{carga['evento']}`")
    em = carga.get("em")
    if carga["evento"] == "nao_medido":
        if not str(carga.get("nota", "")).strip():
            raise FolhaInvalida(f"{onde}: um passo `nao_medido` tem de dizer porque")
        instante = None
    else:
        if not isinstance(em, str):
            raise FolhaInvalida(f"{onde}: `{carga['evento']}` sem `em`")
        instante = ler_instante(em)
    return Carimbo(carga["cenario"], carga["passo"], carga["evento"], instante,
                   str(carga.get("nota", "")))


def ler(caminho: Path) -> list[Carimbo]:
    """Os carimbos de um ficheiro JSONL, pela ordem em que foram escritos."""
    carimbos = []
    for numero, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
        if not linha.strip():
            continue
        try:
            carga = json.loads(linha)
        except json.JSONDecodeError as erro:
            raise FolhaInvalida(f"{caminho.name}:{numero}: JSON ilegivel") from erro
        if not isinstance(carga, dict):
            raise FolhaInvalida(f"{caminho.name}:{numero}: a linha nao e um objecto")
        carimbos.append(_de_dict(carga, f"{caminho.name}:{numero}"))
    return carimbos


class Folha:
    """Escreve carimbos num JSONL, com `flush` e `fsync` a cada linha.

    O `fsync` nao e zelo: a folha e o registo de um ensaio em que se mata um
    *host* de proposito, e uma folha que perde a ultima linha no momento da
    falha perde exactamente o carimbo que interessa.
    """

    def __init__(self, caminho: Path, cenario: str, relogio=None):
        self.caminho = caminho
        self.cenario = cenario
        self._relogio = relogio or (lambda: datetime.now(timezone.utc))

    def _escrever(self, carimbo: Carimbo) -> Carimbo:
        import os

        with self.caminho.open("a", encoding="utf-8", newline="\n") as ficheiro:
            ficheiro.write(json.dumps(carimbo.como_dict(), ensure_ascii=False) + "\n")
            ficheiro.flush()
            os.fsync(ficheiro.fileno())
        return carimbo

    def inicio(self, passo: str, nota: str = "") -> Carimbo:
        return self._escrever(_de_dict(
            {"cenario": self.cenario, "passo": passo, "evento": "inicio",
             "em": formatar(self._relogio()), "nota": nota}, "inicio"))

    def fim(self, passo: str, nota: str = "") -> Carimbo:
        return self._escrever(_de_dict(
            {"cenario": self.cenario, "passo": passo, "evento": "fim",
             "em": formatar(self._relogio()), "nota": nota}, "fim"))

    def nao_medido(self, passo: str, razao: str) -> Carimbo:
        return self._escrever(_de_dict(
            {"cenario": self.cenario, "passo": passo, "evento": "nao_medido",
             "nota": razao}, "nao_medido"))
