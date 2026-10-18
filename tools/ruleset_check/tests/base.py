"""A raiz do repositorio e a resposta de API em fixture.

A fixture **nao** e uma copia escrita a mao: e o espelho real embrulhado nos
campos que a API acrescenta e que nao sao politica. Assim um campo novo no
espelho entra nos testes sem ninguem se lembrar de o copiar, e a resposta usada
nos testes continua a ser a forma que a API devolve — que e o que o criterio 4
manda testar.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

ESPELHO = ROOT / ".github" / "rulesets" / "main.json"

#: Os volateis, com valores plausiveis. Sao os mesmos nomes de
#: `comparador.VOLATEIS`, e ha um teste que confronta as duas listas: uma
#: fixture que deixasse de exercitar um volatil deixava de provar que ele e
#: ignorado.
VOLATEIS_NA_FIXTURE = {
    "id": 24879081,
    "node_id": "RRS_lACqUmVwb3NpdG9yZQ",
    "source": "albinoJimy/kamba",
    "source_type": "Repository",
    "created_at": "2026-10-11T13:13:14.002+01:00",
    "updated_at": "2026-10-11T19:27:44.348+01:00",
    "current_user_can_bypass": "never",
    "_links": {"self": {"href": "https://api.github.com/x"}, "html": {"href": "https://x"}},
}


def espelho() -> dict:
    return json.loads(ESPELHO.read_text(encoding="utf-8"))


def resposta_da_api(**alteracoes) -> dict:
    """O espelho real, mais os campos volateis, mais o que o teste alterar."""
    bruto = espelho()
    bruto.update(copy.deepcopy(VOLATEIS_NA_FIXTURE))
    bruto.update(copy.deepcopy(alteracoes))
    return bruto


def regra(bruto: dict, tipo: str) -> dict:
    for entrada in bruto["rules"]:
        if entrada.get("type") == tipo:
            return entrada
    raise AssertionError(f"a fixture nao tem a regra {tipo!r}")


def contextos(bruto: dict) -> list[dict]:
    return regra(bruto, "required_status_checks")["parameters"]["required_status_checks"]
