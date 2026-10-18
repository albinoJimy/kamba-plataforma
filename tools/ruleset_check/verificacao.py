"""Um alvo de cada vez: resolver o ruleset, le-lo, compara-lo.

Este modulo e o que faltava quando a verificacao tinha um alvo so. A ordem e:

1. ler o espelho — dele sai o **nome** do ruleset que se espera;
2. listar os rulesets do repositorio e procurar esse nome;
3. comparar o que se encontrou com o espelho.

**Os passos 2 e 3 produzem vermelhos diferentes, e isso importa.** Nao
encontrar nada nao e «nao consegui verificar»: a leitura correu bem e a
resposta foi «este repositorio nao tem a politica que o ficheiro declara». Isso
e uma **divergencia** (saida 1), nomeada, e nao um 2. O 2 fica para quando a
API nao responde ou a credencial nao autoriza — a distincao e o criterio 5 do
ticket.

O caso que deu origem a este modulo: o `albinoJimy/kamba-plataforma` — o
repositorio publico, onde os PR vivem — nao tinha ruleset nenhum, e a
verificacao de alvo unico lia o ruleset do **privado**, dizia «conforme» e saia
0 de dentro dele.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from . import api, comparador
from .comparador import AUSENTE, Divergencia
from .config import Alvo


@dataclasses.dataclass(frozen=True)
class Resultado:
    alvo: Alvo
    #: O `id` com que o ruleset foi encontrado, ou `None` se nao foi.
    ruleset_id: int | None
    divergencias: list[Divergencia]
    #: Quantos `required_status_checks` o espelho declara. So para o resumo.
    contextos_no_espelho: int
    #: Quantos rulesets o repositorio tem, ao todo. So para a mensagem.
    rulesets_no_repositorio: int
    #: O ruleset efectivo, em bruto, ou `None` se nao se chegou a le-lo. Esta
    #: aqui para o `mostrar` nao ter de o pedir uma segunda vez a API.
    efectivo: dict | None = None

    @property
    def conforme(self) -> bool:
        return not self.divergencias


def verificar(raiz: Path, alvo: Alvo, transporte: str) -> Resultado:
    """Levanta `ApiIndisponivel` ou `EspelhoInvalido`; o resto e divergencia."""
    espelho = comparador.ler_espelho(raiz / alvo.espelho)
    nome = espelho.get("name")
    if not isinstance(nome, str) or not nome:
        raise comparador.EspelhoInvalido(
            f"{alvo.espelho}: sem `name`. E por ele que o ruleset se resolve na API"
        )
    contextos = _contextos_no_espelho(espelho)

    existentes = api.listar(alvo.caminho_da_lista, transporte)
    candidatos = [
        r for r in existentes
        if isinstance(r, dict) and r.get("name") == nome and isinstance(r.get("id"), int)
    ]

    if not existentes:
        return Resultado(
            alvo, None,
            [Divergencia(
                "repositorio-sem-ruleset", alvo.repositorio, nome, AUSENTE,
                "o repositorio nao tem ruleset nenhum. Nao ha PR obrigatorio, nao ha "
                "required checks, e `main` pode ser apagado ou reescrito. A politica "
                "que o espelho declara nao esta aplicada aqui",
            )],
            contextos, 0,
        )
    if not candidatos:
        tem = sorted(str(r.get("name")) for r in existentes if isinstance(r, dict))
        return Resultado(
            alvo, None,
            [Divergencia(
                "ruleset-ausente", alvo.repositorio, nome, tem,
                f"o repositorio tem {len(existentes)} ruleset(s), e nenhum se chama "
                "como o espelho. Ou falta criar este, ou alguem o renomeou",
            )],
            contextos, len(existentes),
        )
    if len(candidatos) > 1:
        # O `ruleset_id` declarado desempata — e e por isso que a mensagem do
        # caso sem desempate manda declara-lo: seria uma promessa por cumprir
        # se o codigo nao o usasse aqui.
        pelo_id = [r for r in candidatos if int(r["id"]) == alvo.ruleset_id]
        if len(pelo_id) != 1:
            return Resultado(
                alvo, None,
                [Divergencia(
                    "ruleset-ambiguo", alvo.repositorio, nome,
                    sorted(int(r["id"]) for r in candidatos),
                    f"ha {len(candidatos)} rulesets com este nome. Nao se escolhe um "
                    "por adivinhacao: declare em ci/ruleset.yaml o `ruleset_id` do que "
                    "vale",
                )],
                contextos, len(existentes),
            )
        candidatos = pelo_id

    ruleset_id = int(candidatos[0]["id"])
    divergencias: list[Divergencia] = []
    if alvo.ruleset_id is not None and alvo.ruleset_id != ruleset_id:
        divergencias.append(Divergencia(
            "id-do-ruleset-divergente", alvo.repositorio, alvo.ruleset_id, ruleset_id,
            "o ruleset com este nome tem outro `id`. Um `id` que muda significa que o "
            "ruleset foi apagado e feito de novo — e entre uma coisa e a outra `main` "
            "esteve sem protecao",
        ))

    efectivo = api.obter(alvo.caminho_do_ruleset(ruleset_id), transporte)
    divergencias += comparador.comparar(espelho, efectivo)
    return Resultado(
        alvo, ruleset_id, divergencias, contextos, len(existentes), efectivo
    )


def _contextos_no_espelho(espelho: dict) -> int:
    for regra in espelho.get("rules") or []:
        if isinstance(regra, dict) and regra.get("type") == "required_status_checks":
            return len((regra.get("parameters") or {}).get("required_status_checks") or [])
    return 0
