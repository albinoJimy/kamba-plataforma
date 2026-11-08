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


#: Os dois repositorios de `ci/ruleset.yaml`. Lidos do ficheiro real, para uma
#: alteracao da configuracao nao deixar os testes a falar de alvos que ja nao
#: existem.
PRIVADO = "albinoJimy/kamba"
PUBLICO = "albinoJimy/kamba-plataforma"

#: Os `id` que a configuracao declara, **lidos do ficheiro real** e nao
#: copiados para aqui. A razao foi medida: o alvo do publico passou a declarar
#: o seu `id` (25359475, criado a 2026-10-18 e escrito a 2026-11-07), e os
#: numeros inventados que estavam nestas fixtures passaram a valer como
#: `id-do-ruleset-divergente`. Um `id` copiado para os testes e uma segunda
#: copia do mesmo numero — exactamente o que o `README.md` do ruleset tem um
#: teste para impedir.
def _ids_declarados() -> dict[str, int]:
    from ruleset_check import config

    return {alvo.repositorio: alvo.ruleset_id
            for alvo in config.ler(ROOT) if alvo.ruleset_id is not None}


IDS_DECLARADOS = _ids_declarados()

#: O `id` do ruleset do privado, como a configuracao o declara.
ID_DO_PRIVADO = IDS_DECLARADOS[PRIVADO]

#: E o do publico, que existe desde 2026-10-18.
ID_DO_PUBLICO = IDS_DECLARADOS[PUBLICO]


def entrada_da_listagem(ruleset_id: int = ID_DO_PRIVADO, nome: str | None = None) -> dict:
    """Uma linha de `GET /repos/{o}/{r}/rulesets`, como a API a devolve.

    A listagem **nao** traz as regras: traz `id`, `name`, `target`,
    `enforcement` e metadados. E por isso que a verificacao faz dois pedidos.
    """
    return {
        "id": ruleset_id,
        "name": nome if nome is not None else espelho()["name"],
        "target": "branch",
        "source_type": "Repository",
        "source": PRIVADO,
        "enforcement": "active",
        "node_id": "RRS_lACqUmVwb3NpdG9yZQ",
        "created_at": "2026-10-11T13:13:14.002+01:00",
        "updated_at": "2026-10-11T19:27:44.348+01:00",
    }


def api_falsa(por_repositorio: dict[str, tuple[list, dict]]):
    """Devolve `(listar, obter)` para substituir os do modulo `api`.

    `por_repositorio` mapeia `dono/repo` -> (listagem, {id: resposta completa}).
    Um repositorio que nao esteja no mapa **levanta**, para um teste nao passar
    por engano contra um alvo que nunca configurou.
    """
    def listar(caminho: str, transporte: str = "gh") -> list:
        repositorio = caminho[len("repos/"):-len("/rulesets")]
        return por_repositorio[repositorio][0]

    def obter(caminho: str, transporte: str = "gh") -> dict:
        partes = caminho.split("/")
        repositorio = f"{partes[1]}/{partes[2]}"
        return por_repositorio[repositorio][1][int(partes[4])]

    return listar, obter


def tudo_conforme() -> dict[str, tuple[list, dict]]:
    """Os dois alvos com o ruleset aplicado e igual ao espelho.

    O `id` de cada alvo e o que a configuracao declara: um numero diferente
    aqui seria uma divergencia a mais, e este e o estado «tudo conforme».
    """
    return {
        PRIVADO: ([entrada_da_listagem()], {ID_DO_PRIVADO: resposta_da_api()}),
        PUBLICO: ([entrada_da_listagem(ruleset_id=ID_DO_PUBLICO)],
                  {ID_DO_PUBLICO: resposta_da_api()}),
    }


def regra(bruto: dict, tipo: str) -> dict:
    for entrada in bruto["rules"]:
        if entrada.get("type") == tipo:
            return entrada
    raise AssertionError(f"a fixture nao tem a regra {tipo!r}")


def contextos(bruto: dict) -> list[dict]:
    return regra(bruto, "required_status_checks")["parameters"]["required_status_checks"]
