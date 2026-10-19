"""Normalizacao e comparacao do ruleset efectivo contra o espelho versionado.

## O que se compara, e a lista esta escrita

O criterio 4 do KAM-137 nomeia-o, e e isto, nem mais nem menos:

* `enforcement` — `active`. Um ruleset em `evaluate` reporta e nao bloqueia, que
  e indistinguivel de nao existir para quem faz merge;
* `name` e `target` — identificam o que se esta a comparar. Um ruleset
  renomeado ou apontado a `tag` em vez de `branch` nao e o mesmo ruleset;
* `conditions` — a que refs se aplica. Um `~DEFAULT_BRANCH` trocado por um
  padrao que nao casa `main` desliga tudo sem mexer numa regra;
* `rules` — as quatro: `pull_request`, `required_status_checks` (os sete
  contextos), `deletion` e `non_fast_forward`. Os parametros comparados de cada
  uma estao em `PARAMETROS_DE_POLITICA`;
* `bypass_actors` — **vazio**. Um bypass actor acrescentado e tao grave como um
  gate retirado, e e a alteracao que mais facilmente passa despercebida: e uma
  entrada numa lista que normalmente esta vazia e que ninguem rele.

Duas notas de fundo sobre o que **nao** e defeito:

* **`required_approving_review_count` e `0`, e compara-se como esta.** Nao e um
  valor a corrigir aqui: a cedencia esta registada em
  `.github/rulesets/README.md` e na lacuna 16 do `docs/ci.md` §7, e volta a 1
  com o segundo contribuidor. Este modulo compara o GitHub com o ficheiro, nao
  o ficheiro com uma opiniao.
* **`strict_required_status_checks_policy` e `false` de proposito**, justificado
  no mesmo README. Compara-se como esta.

## Campos volateis, nomeados um a um

Sao os que a API devolve e que **nao sao politica**: mudam sem ninguem decidir
nada, e compara-los produzia vermelho a cada leitura. Cada um com a sua razao,
em `VOLATEIS`. Um campo de topo que a API passe a devolver e que nao esteja nem
em `CAMPOS_DE_TOPO` nem em `VOLATEIS` **falha** — e o unico comportamento que
nao esconde uma politica nova atras de um campo novo.

## Um campo de politica ausente e divergencia

Nao basta comparar os valores dos campos que existem: um campo que desapareca
dos **dois** lados fica igual a si proprio e passa. Por isso exige-se presenca:
os seis campos de topo em ambos os lados, e os parametros de
`PARAMETROS_DE_POLITICA` em ambos os lados de cada regra que exista nos dois.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any


class EspelhoInvalido(RuntimeError):
    """O `.github/rulesets/main.json` falta ou nao e um objecto JSON.

    Nao e um achado: e saida 2. Um espelho ilegivel nao pode parecer um ruleset
    conforme.
    """


class _Ausente:
    """Sentinela para «este campo nao veio». Distingue-se de `null` e de `[]`."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover — so aparece em mensagens
        return "<ausente>"


AUSENTE = _Ausente()


#: Os campos de topo que sao politica. E tambem o conjunto exacto de chaves que
#: o espelho tem de ter: o comando de exportacao do `README.md` produz estas
#: seis e mais nenhuma.
CAMPOS_DE_TOPO = ("bypass_actors", "conditions", "enforcement", "name", "rules", "target")

#: Os campos que a API devolve e que **nao** sao politica, nomeados um a um com
#: a razao. A razao importa: e o que impede que a lista cresca para calar um
#: vermelho inconveniente.
VOLATEIS: dict[str, str] = {
    "id": "identificador atribuido pelo GitHub; o espelho nao o guarda, o `ci/ruleset.yaml` sim",
    "node_id": "identificador opaco da API GraphQL; muda de forma sem mudar politica",
    "source": "o repositorio de onde o ruleset vem; e contexto, nao regra",
    "source_type": "`Repository` ou `Organization`; e contexto, nao regra",
    "created_at": "carimbo de criacao",
    "updated_at": "carimbo da ultima alteracao; muda a cada edicao, incluindo as que nao mudam politica",
    "current_user_can_bypass": "depende de **quem** pergunta, nao do ruleset; dois leitores veem valores diferentes do mesmo ruleset",
    "_links": "hiperligacoes de navegacao da API",
}

#: Por tipo de regra, os parametros que sao politica e cuja **presenca** se
#: exige dos dois lados. Os valores comparam-se sempre pela uniao das chaves
#: presentes, pelo que um parametro novo que a API devolva tambem e apanhado —
#: esta lista e sobre o que nao pode faltar, nao sobre o que se olha.
PARAMETROS_DE_POLITICA: dict[str, frozenset[str]] = {
    "pull_request": frozenset(
        {
            "required_approving_review_count",
            "dismiss_stale_reviews_on_push",
            "require_code_owner_review",
            "require_last_push_approval",
            "required_review_thread_resolution",
            "require_extra_approval_for_unattributed_changes",
            "required_reviewers",
            "allowed_merge_methods",
        }
    ),
    "required_status_checks": frozenset(
        {
            "strict_required_status_checks_policy",
            "do_not_enforce_on_create",
            "required_status_checks",
        }
    ),
    "deletion": frozenset(),
    "non_fast_forward": frozenset(),
}


@dataclasses.dataclass(frozen=True)
class Divergencia:
    #: Identificador estavel da regra que apanhou. Os testes confrontam-no: uma
    #: divergencia tem de ser apanhada **por esta regra** e nao por outra.
    regra: str
    #: Onde, em notacao de caminho (`rules.pull_request.require_code_owner_review`).
    onde: str
    #: O que o espelho diz, e o que o GitHub aplica.
    espelho: Any
    efectivo: Any
    mensagem: str = ""

    def __str__(self) -> str:
        corpo = f"[{self.regra}] {self.onde}"
        if self.mensagem:
            corpo += f": {self.mensagem}"
        return (
            f"{corpo}\n"
            f"        espelho:  {_mostrar(self.espelho)}\n"
            f"        GitHub:   {_mostrar(self.efectivo)}"
        )


def _mostrar(valor: Any) -> str:
    if isinstance(valor, _Ausente):
        return "<ausente>"
    return json.dumps(valor, ensure_ascii=False, sort_keys=True)


# --- normalizacao ------------------------------------------------------------


def _canonico(valor: Any) -> Any:
    """Forma comparavel: mapas com chaves ordenadas, listas como estao."""
    if isinstance(valor, dict):
        return {chave: _canonico(valor[chave]) for chave in sorted(valor)}
    if isinstance(valor, list):
        return [_canonico(item) for item in valor]
    return valor


def _chave_de_ordenacao(valor: Any) -> str:
    return json.dumps(_canonico(valor), ensure_ascii=False, sort_keys=True)


def _contexto(entrada: Any) -> tuple[str, Any]:
    """Um `required_status_check` reduzido ao que e politica.

    O `integration_id` entra: diz **que aplicacao** tem de reportar o contexto,
    e um contexto reportado por outra aplicacao nao e o mesmo contexto. Hoje
    nenhum dos sete o declara, pelo que fica `None` dos dois lados.
    """
    if isinstance(entrada, dict):
        return (str(entrada.get("context", "")), entrada.get("integration_id"))
    return (str(entrada), None)


def normalizar(bruto: dict) -> dict:
    """Do que a API (ou o ficheiro) devolve, para a forma que se compara.

    Deixa cair os volateis nomeados, ordena o que nao tem ordem semantica
    (regras por tipo, contextos, bypass actors, listas de `conditions`) e marca
    com `AUSENTE` o campo de politica que nao veio.
    """
    if not isinstance(bruto, dict):
        raise EspelhoInvalido(f"esperava um objecto, veio {type(bruto).__name__}")

    normalizado: dict[str, Any] = {}
    for campo in CAMPOS_DE_TOPO:
        normalizado[campo] = bruto[campo] if campo in bruto else AUSENTE

    # Campos que nao sao nem politica nem volateis conhecidos: guardam-se para
    # a comparacao os apanhar. Nao se descartam em silencio.
    desconhecidos = sorted(set(bruto) - set(CAMPOS_DE_TOPO) - set(VOLATEIS))
    normalizado["_desconhecidos"] = {chave: _canonico(bruto[chave]) for chave in desconhecidos}

    if not isinstance(normalizado["conditions"], _Ausente):
        normalizado["conditions"] = _normalizar_conditions(normalizado["conditions"])
    if not isinstance(normalizado["bypass_actors"], _Ausente):
        normalizado["bypass_actors"] = sorted(
            (_canonico(a) for a in _lista(normalizado["bypass_actors"], "bypass_actors")),
            key=_chave_de_ordenacao,
        )
    normalizado["rules"] = _normalizar_rules(normalizado["rules"])
    return normalizado


def _lista(valor: Any, onde: str) -> list:
    if not isinstance(valor, list):
        raise EspelhoInvalido(f"{onde}: esperava uma lista, veio {type(valor).__name__}")
    return valor


def _normalizar_conditions(conditions: Any) -> Any:
    if not isinstance(conditions, dict):
        return _canonico(conditions)
    saida = _canonico(conditions)
    ref_name = saida.get("ref_name")
    if isinstance(ref_name, dict):
        for chave in ("include", "exclude"):
            if isinstance(ref_name.get(chave), list):
                ref_name[chave] = sorted(ref_name[chave], key=_chave_de_ordenacao)
    return saida


def _normalizar_rules(rules: Any) -> Any:
    """Lista de regras -> mapa `tipo -> parametros`. A ordem da lista nao e politica."""
    if isinstance(rules, _Ausente):
        return AUSENTE
    por_tipo: dict[str, Any] = {}
    for regra in _lista(rules, "rules"):
        if not isinstance(regra, dict) or "type" not in regra:
            raise EspelhoInvalido(f"rules: entrada sem `type`: {regra!r}")
        tipo = str(regra["type"])
        if tipo in por_tipo:
            raise EspelhoInvalido(f"rules: tipo repetido {tipo!r}")
        parametros = regra.get("parameters", {})
        if not isinstance(parametros, dict):
            raise EspelhoInvalido(f"rules.{tipo}.parameters: esperava um mapa")
        parametros = _canonico(parametros)
        contextos = parametros.get("required_status_checks")
        if isinstance(contextos, list):
            parametros["required_status_checks"] = sorted(
                (_contexto(c) for c in contextos), key=repr
            )
        for chave in ("required_reviewers", "allowed_merge_methods"):
            if isinstance(parametros.get(chave), list):
                parametros[chave] = sorted(parametros[chave], key=_chave_de_ordenacao)
        por_tipo[tipo] = parametros
    return por_tipo


# --- comparacao --------------------------------------------------------------


def comparar(espelho_bruto: dict, efectivo_bruto: dict) -> list[Divergencia]:
    """As divergencias entre o espelho versionado e o ruleset que o GitHub aplica."""
    espelho = normalizar(espelho_bruto)
    efectivo = normalizar(efectivo_bruto)
    divergencias: list[Divergencia] = []

    divergencias += _campos_de_topo(espelho, efectivo)
    divergencias += _campos_fora_da_lista(espelho, efectivo)
    divergencias += _bypass_actors(espelho, efectivo)
    divergencias += _regras(espelho, efectivo)
    return divergencias


def _campos_de_topo(espelho: dict, efectivo: dict) -> list[Divergencia]:
    saida: list[Divergencia] = []
    for campo in CAMPOS_DE_TOPO:
        no_espelho, no_github = espelho[campo], efectivo[campo]
        faltam = [
            lado
            for lado, valor in (("espelho", no_espelho), ("GitHub", no_github))
            if isinstance(valor, _Ausente)
        ]
        if faltam:
            saida.append(
                Divergencia(
                    "campo-de-politica-ausente", campo, no_espelho, no_github,
                    f"campo de politica ausente em: {', '.join(faltam)}. Um campo que "
                    "desaparece dos dois lados fica igual a si proprio — por isso exige-se "
                    "a presenca e nao so a igualdade",
                )
            )
            continue
        if campo in ("bypass_actors", "rules"):
            continue  # tem comparacao propria, com mensagens melhores
        if no_espelho != no_github:
            saida.append(Divergencia("campo-divergente", campo, no_espelho, no_github))
    return saida


def _campos_fora_da_lista(espelho: dict, efectivo: dict) -> list[Divergencia]:
    """Um campo de topo que nao e politica conhecida nem volatil declarado.

    E a porta que impede a lista de campos comparados de envelhecer em silencio:
    uma politica nova num campo novo passava despercebida se o normalizador a
    deitasse fora sem dizer nada.
    """
    saida = []
    for chave, valor in efectivo["_desconhecidos"].items():
        saida.append(
            Divergencia(
                "campo-novo-na-api", chave, AUSENTE, valor,
                "campo de topo que a API devolve e que nao e politica conhecida nem "
                "volatil declarado. Ou entra em `CAMPOS_DE_TOPO` e no espelho, ou entra "
                "em `VOLATEIS` com a razao escrita",
            )
        )
    for chave, valor in espelho["_desconhecidos"].items():
        saida.append(
            Divergencia(
                "campo-a-mais-no-espelho", chave, valor, AUSENTE,
                "campo de topo no espelho que nao esta na lista comparada. O comando de "
                "exportacao do `.github/rulesets/README.md` produz seis campos; este nao "
                "e um deles",
            )
        )
    return saida


def _bypass_actors(espelho: dict, efectivo: dict) -> list[Divergencia]:
    """`bypass_actors` vazio, e vazio dos dois lados.

    Ha aqui uma regra a mais do que a igualdade, e e deliberada: um actor com
    bypass **no GitHub** e divergencia mesmo que alguem o tenha acrescentado
    tambem ao ficheiro. O ficheiro nao e autoridade para conceder bypass; a
    unica forma de isto ficar verde e retirar o actor, nao actualizar o espelho.
    """
    saida: list[Divergencia] = []
    no_espelho, no_github = espelho["bypass_actors"], efectivo["bypass_actors"]
    if isinstance(no_espelho, _Ausente) or isinstance(no_github, _Ausente):
        return saida  # ja reportado como `campo-de-politica-ausente`
    if no_github:
        saida.append(
            Divergencia(
                "bypass-actor-no-github", "bypass_actors", no_espelho, no_github,
                f"{len(no_github)} actor(es) com bypass no ruleset efectivo. Um bypass "
                "actor acrescentado e tao grave como um gate retirado: quem o tem funde "
                "sem os gates. A lista tem de estar vazia",
            )
        )
    if no_espelho != no_github:
        saida.append(Divergencia("campo-divergente", "bypass_actors", no_espelho, no_github))
    return saida


def _regras(espelho: dict, efectivo: dict) -> list[Divergencia]:
    saida: list[Divergencia] = []
    regras_espelho, regras_github = espelho["rules"], efectivo["rules"]
    if isinstance(regras_espelho, _Ausente) or isinstance(regras_github, _Ausente):
        return saida  # ja reportado como `campo-de-politica-ausente`

    for tipo in sorted(set(regras_espelho) - set(regras_github)):
        saida.append(
            Divergencia(
                "regra-ausente-no-github", f"rules.{tipo}", regras_espelho[tipo], AUSENTE,
                "regra que o espelho declara e o GitHub nao aplica",
            )
        )
    for tipo in sorted(set(regras_github) - set(regras_espelho)):
        saida.append(
            Divergencia(
                "regra-nao-declarada", f"rules.{tipo}", AUSENTE, regras_github[tipo],
                "regra que o GitHub aplica e o espelho nao declara",
            )
        )

    for tipo in sorted(set(regras_espelho) & set(regras_github)):
        saida += _parametros(tipo, regras_espelho[tipo], regras_github[tipo])
    return saida


def _parametros(tipo: str, no_espelho: dict, no_github: dict) -> list[Divergencia]:
    saida: list[Divergencia] = []
    #: Reportar o mesmo parametro duas vezes — ausente **e** divergente — nao
    #: acrescenta informacao e enterra as outras divergencias na saida.
    ja_reportado: set[str] = set()

    for parametro in sorted(PARAMETROS_DE_POLITICA.get(tipo, frozenset())):
        faltam = [
            lado
            for lado, lado_dados in (("espelho", no_espelho), ("GitHub", no_github))
            if parametro not in lado_dados
        ]
        if faltam:
            saida.append(
                Divergencia(
                    "campo-de-politica-ausente", f"rules.{tipo}.{parametro}",
                    no_espelho.get(parametro, AUSENTE), no_github.get(parametro, AUSENTE),
                    f"parametro de politica ausente em: {', '.join(faltam)}",
                )
            )
            ja_reportado.add(parametro)

    if tipo == "required_status_checks":
        saida += _contextos(no_espelho, no_github)
        ja_reportado.add("required_status_checks")

    for parametro in sorted(set(no_espelho) | set(no_github)):
        if parametro in ja_reportado:
            continue
        valor_espelho = no_espelho.get(parametro, AUSENTE)
        valor_github = no_github.get(parametro, AUSENTE)
        if isinstance(valor_espelho, _Ausente) and isinstance(valor_github, _Ausente):
            continue
        if valor_espelho != valor_github:
            saida.append(
                Divergencia(
                    "parametro-divergente", f"rules.{tipo}.{parametro}",
                    valor_espelho, valor_github,
                )
            )
    return saida


def _contextos(no_espelho: dict, no_github: dict) -> list[Divergencia]:
    """Os required checks, um a um, e em que sentido faltam.

    A divergencia diz o **sentido** porque a accao e diferente: um contexto so
    no ficheiro corrige-se no ficheiro ou no GitHub conforme a intencao; um
    contexto so no GitHub e uma regra que ninguem declarou.
    """
    saida: list[Divergencia] = []
    esperados = no_espelho.get("required_status_checks")
    aplicados = no_github.get("required_status_checks")
    if not isinstance(esperados, list) or not isinstance(aplicados, list):
        return saida  # ja reportado como ausente, ou como parametro divergente
    conjunto_espelho = {tuple(c) for c in esperados}
    conjunto_github = {tuple(c) for c in aplicados}
    for contexto, integracao in sorted(conjunto_espelho - conjunto_github, key=repr):
        saida.append(
            Divergencia(
                "contexto-so-no-ficheiro",
                f"rules.required_status_checks[{contexto}]", contexto, AUSENTE,
                "required check que o espelho declara e o GitHub nao exige. Um PR que o "
                "deixe vermelho funde na mesma",
            )
        )
    for contexto, integracao in sorted(conjunto_github - conjunto_espelho, key=repr):
        saida.append(
            Divergencia(
                "contexto-so-no-github",
                f"rules.required_status_checks[{contexto}]", AUSENTE, contexto,
                "required check que o GitHub exige e o espelho nao declara",
            )
        )
    return saida


# --- leitura do espelho ------------------------------------------------------


def ler_espelho(caminho: Path) -> dict:
    if not caminho.is_file():
        raise EspelhoInvalido(f"{caminho}: nao existe")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as erro:
        raise EspelhoInvalido(f"{caminho}: {erro}") from erro
    if not isinstance(dados, dict):
        raise EspelhoInvalido(f"{caminho}: esperava um objecto JSON")
    return dados
