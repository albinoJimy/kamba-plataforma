"""Validacao de `ci/waivers.yaml` — o unico mecanismo de excepcao do pipeline.

A regra transversal do §4 do Engineering Standards diz: «nenhum gate pode ser
marcado *skip* sem ADR ou aprovacao registada». Dois tickets a jusante repetem a
exigencia com palavras diferentes — o KAM-067 diz «excepcao registada em ADR» e o
KAM-078 diz «exige referencia a ADR/aprovacao (*lint* do pipeline)» — e ambos
consomem este esquema, em vez de inventarem o seu.

O que este modulo recusa, e porque:

| Recusa | Razao |
|---|---|
| sem `adr_ou_aprovacao` | uma excepcao sem fundamento e uma decisao sem autor |
| sem `expira_em` | uma excepcao sem prazo fica para sempre |
| `expira_em` > 30 dias | o limite e *proposta* do ticket, e e ele que a torna temporaria |
| **expirado** | **falha o pipeline** — nao avisa, nao ignora |
| sem `alvo` | uma excepcao que nao diz a quem se aplica aplica-se a tudo |
| sem `razao` | a razao e o que sobrevive a saida do autor |

A recusa de um waiver expirado e a parte que importa. A alternativa — avisar e
seguir — produz excepcoes que ninguem revisita, porque nada obriga a isso.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import re
import sys
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

#: Limite de validade de um waiver, em dias. *Proposta* do ticket KAM-002.
PRAZO_MAXIMO_DIAS = 30

#: Gates que aceitam waiver. Os gates 1 e 2 nao estao aqui: um build que nao
#: compila ou um tipo que nao verifica nao se dispensa, corrige-se.
GATES_COM_WAIVER = {"3", "4", "5", "6", "7", "8", "9", "11"}

_ADR = re.compile(r"^ADR-[0-9]{3}$")
_ADR_LOCAL = re.compile(r"^ADR-L[0-9]{3}$")
_APROVACAO = re.compile(r"^aprovacao:[^@\s]+@\d{4}-\d{2}-\d{2}$")

_CAMPOS = ("gate", "alvo", "adr_ou_aprovacao", "autor", "razao", "expira_em")


class WaiverInvalido(RuntimeError):
    """O ficheiro de waivers esta malformado, ou um waiver expirou."""


class ConfiguracaoIlegivel(WaiverInvalido):
    """`ci/waivers.yaml` nao se le: o leitor recusou-o.

    Separa-se de `WaiverInvalido` por causa do codigo de saida (KAM-136): uma
    recusa do leitor e um **erro de configuracao** (2), nao um achado (1).
    Subclasse, e nao irma, para que quem ja apanhava `WaiverInvalido` continue
    a apanhar isto.
    """


def _data(valor, onde: str) -> _datetime.date:
    try:
        return _datetime.date.fromisoformat(str(valor))
    except (TypeError, ValueError) as excepcao:
        raise WaiverInvalido(
            f"{onde}: `expira_em` tem de ser uma data ISO (AAAA-MM-DD), lido {valor!r}"
        ) from excepcao


def ler(raiz: Path, hoje: _datetime.date | None = None) -> list[dict]:
    """Le e valida `ci/waivers.yaml`. Levanta se algo estiver errado."""
    caminho = raiz / "ci" / "waivers.yaml"
    if not caminho.is_file():
        raise WaiverInvalido(f"ficheiro em falta: {caminho}")
    try:
        dados = load_file(caminho)
    except YamlSubsetError as excepcao:
        raise ConfiguracaoIlegivel(str(excepcao)) from excepcao
    if dados.get("version") != 1:
        raise WaiverInvalido(f"{caminho}: 'version' tem de ser 1")

    hoje = hoje or _datetime.date.today()
    waivers = dados.get("waivers")
    if waivers is None:
        raise WaiverInvalido(
            f"{caminho}: falta a chave `waivers`. Use `waivers: []` para dizer "
            "«nenhuma excepcao» — a ausencia da chave e ambigua."
        )
    if not isinstance(waivers, list):
        raise WaiverInvalido(f"{caminho}: `waivers` tem de ser uma lista")

    validados: list[dict] = []
    for indice, waiver in enumerate(waivers, start=1):
        onde = f"{caminho}: waiver {indice}"
        if not isinstance(waiver, dict):
            raise WaiverInvalido(f"{onde}: esperava um mapa")

        faltam = [c for c in _CAMPOS if not waiver.get(c)]
        if faltam:
            raise WaiverInvalido(f"{onde}: campos obrigatorios em falta: {', '.join(faltam)}")

        gate = str(waiver["gate"])
        if gate not in GATES_COM_WAIVER:
            raise WaiverInvalido(
                f"{onde}: o gate {gate} nao aceita waiver (aceitam: "
                f"{', '.join(sorted(GATES_COM_WAIVER))}). Um build que nao compila "
                "ou um tipo que nao verifica corrige-se, nao se dispensa."
            )

        referencia = str(waiver["adr_ou_aprovacao"])
        if not (
            _ADR.match(referencia)
            or _ADR_LOCAL.match(referencia)
            or _APROVACAO.match(referencia)
        ):
            raise WaiverInvalido(
                f"{onde}: `adr_ou_aprovacao` tem de ser `ADR-NNN`, `ADR-LNNN` ou "
                f"`aprovacao:<quem>@<AAAA-MM-DD>`; lido {referencia!r}"
            )

        if len(str(waiver["razao"])) < 40:
            raise WaiverInvalido(
                f"{onde}: a razao tem {len(str(waiver['razao']))} caracteres. "
                "Uma excepcao justificada em meia linha nao sobrevive a saida do "
                "autor — escreva o que a torna aceitavel e quando rever."
            )

        expira = _data(waiver["expira_em"], onde)
        if expira < hoje:
            raise WaiverInvalido(
                f"{onde}: **expirou** a {expira.isoformat()} (hoje e "
                f"{hoje.isoformat()}). Um waiver expirado falha o pipeline: ou se "
                "corrige o que ele dispensava, ou se renova com razao nova."
            )
        if (expira - hoje).days > PRAZO_MAXIMO_DIAS:
            raise WaiverInvalido(
                f"{onde}: `expira_em` esta a {(expira - hoje).days} dias; o maximo "
                f"e {PRAZO_MAXIMO_DIAS}."
            )

        validados.append({**waiver, "gate": gate, "expira_em": expira.isoformat()})

    return validados


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="ci_waivers", description="Valida ci/waivers.yaml"
    )
    analisador.add_argument("--root", type=Path, default=None)
    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parent.parent).resolve()

    try:
        waivers = ler(raiz)
    except ConfiguracaoIlegivel as excepcao:
        # Codigo 2 e nao 1: o ficheiro nao se le, logo nao se sabe se ha achados.
        # E a mesma convencao dos outros nove consumidores do `kamba_yaml`.
        print(f"ci_waivers: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2
    except WaiverInvalido as excepcao:
        print(f"ci_waivers: {excepcao}", file=sys.stderr)
        return 1

    if not waivers:
        print("ci_waivers: nenhuma excepcao activa")
        return 0

    hoje = _datetime.date.today()
    print(f"ci_waivers: {len(waivers)} excepcao(oes) activa(s)")
    for waiver in waivers:
        dias = (_datetime.date.fromisoformat(waiver["expira_em"]) - hoje).days
        print(
            f"  gate {waiver['gate']}  {waiver['alvo']}  "
            f"{waiver['adr_ou_aprovacao']}  expira em {dias} dia(s)  "
            f"({waiver['autor']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
