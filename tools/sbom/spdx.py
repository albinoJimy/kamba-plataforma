"""Avaliacao de expressoes SPDX contra a politica de `ci/licenses.yaml`.

Nao se comparam cadeias: avaliam-se **expressoes**. `MIT AND BUSL-1.1`
(Meilisearch, `docs/tecnica/evidencia/E4_Stack_Licencas.md` §2.13) contem `MIT`,
e um comparador de cadeias que procurasse `MIT` dentro dela aprovava uma licenca
que obriga a acordo comercial para producao.

A assimetria entre `AND` e `OR` e deliberada:

* `AND` significa «cumpre as duas» — logo cumpre a pior, e e a pior que conta;
* `OR` significa «escolhe uma» — e nos escolhemos uma permitida, se houver.

O veredicto tem quatro valores, nao dois, porque «nao sei» e «espera por uma
decisao» sao estados diferentes de «proibido», e a correccao de cada um e outra:

| Veredicto | O que fazer |
|---|---|
| `permitida` | nada |
| `negada` | tirar a dependencia, ou waiver com ADR |
| `pendente` | fechar a decisao aberta que a trava (`D#`) |
| `desconhecida` | descobrir a licenca e registar; nunca deixar passar |
"""

from __future__ import annotations

import dataclasses
import re

PERMITIDA = "permitida"
NEGADA = "negada"
PENDENTE = "pendente"
DESCONHECIDA = "desconhecida"

#: Valores que significam «o scanner nao conseguiu determinar». O `NOASSERTION`
#: e o caso do Medusa v2 — o Registo de Comercio do Piloto (ADR-003) — porque o
#: repositorio e MIT **excepto** a Enterprise Edition.
SEM_INFORMACAO = frozenset(
    {"", "noassertion", "unknown", "none", "null", "see license", "other", "proprietary"}
)

_TOKEN = re.compile(r"\(|\)|\bAND\b|\bOR\b|\bWITH\b|[^\s()]+", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class Politica:
    permitidas: frozenset[str]
    negadas: tuple[tuple[str, str], ...]
    pendentes: tuple[tuple[str, str, str], ...]
    #: Nomes que a correspondencia parcial de `pendentes` apanharia e **nao**
    #: sao o componente travado: bibliotecas de cliente, utilitarios, analisadores
    #: de protocolo. Cada um com a razao, em `ci/licenses.yaml`. Vazio por
    #: omissao, para que uma politica construida a mao continue a valer.
    excepcoes_de_nome: frozenset[str] = dataclasses.field(default_factory=frozenset)

    def classificar_termo(self, licenca: str) -> tuple[str, str]:
        """Classifica **um** identificador SPDX. Devolve (veredicto, razao)."""
        bruto = licenca.strip().rstrip("+")
        if bruto.lower() in SEM_INFORMACAO:
            return DESCONHECIDA, f"licenca nao determinada ({licenca!r})"

        # A comparacao de permitidas e exacta, sem familias: `BSD` sozinho nao
        # bate em nada, para que ninguem o reintroduza por engano.
        for permitida in self.permitidas:
            if bruto.lower() == permitida.lower():
                return PERMITIDA, permitida

        for prefixo, razao in self.negadas:
            if bruto.lower().startswith(prefixo.lower()):
                return NEGADA, razao

        return DESCONHECIDA, (
            f"{bruto} nao esta nem nas permitidas nem nas negadas de "
            "ci/licenses.yaml; classifique-a antes de a deixar entrar"
        )


def _avaliar(tokens: list[str], politica: Politica) -> tuple[str, str]:
    """Avalia a lista de tokens de uma expressao SPDX, sem recursao de parenteses.

    Suporta parenteses por reducao: resolve o grupo mais interno primeiro.
    """
    while "(" in tokens:
        fim = tokens.index(")")
        inicio = max(i for i, t in enumerate(tokens[:fim]) if t == "(")
        veredicto, razao = _avaliar(tokens[inicio + 1 : fim], politica)
        tokens = tokens[:inicio] + [f"\x00{veredicto}\x00{razao}"] + tokens[fim + 1 :]

    # `WITH` liga uma licenca a uma excepcao; avalia-se a licenca.
    limpos: list[str] = []
    saltar = False
    for indice, token in enumerate(tokens):
        if saltar:
            saltar = False
            continue
        if token.upper() == "WITH":
            saltar = True
            continue
        limpos.append(token)
    tokens = limpos

    def resolver(token: str) -> tuple[str, str]:
        if token.startswith("\x00"):
            _, veredicto, razao = token.split("\x00", 2)
            return veredicto, razao
        return politica.classificar_termo(token)

    # Partir por OR no nivel de topo: basta um ramo passar.
    if any(t.upper() == "OR" for t in tokens):
        ramos: list[list[str]] = [[]]
        for token in tokens:
            if token.upper() == "OR":
                ramos.append([])
            else:
                ramos[-1].append(token)
        resultados = [_avaliar(ramo, politica) for ramo in ramos if ramo]
        for veredicto, razao in resultados:
            if veredicto == PERMITIDA:
                return PERMITIDA, f"ramo permitido: {razao}"
        # Nenhum ramo passa: devolve-se o pior, por esta ordem de gravidade.
        for alvo in (NEGADA, PENDENTE, DESCONHECIDA):
            for veredicto, razao in resultados:
                if veredicto == alvo:
                    return veredicto, razao
        return DESCONHECIDA, "expressao OR sem ramos avaliaveis"

    # Restam termos ligados por AND: todos tem de passar, e a pior conta.
    termos = [t for t in tokens if t.upper() != "AND"]
    if not termos:
        return DESCONHECIDA, "expressao vazia"
    resultados = [resolver(t) for t in termos]
    for alvo in (NEGADA, PENDENTE, DESCONHECIDA):
        for veredicto, razao in resultados:
            if veredicto == alvo:
                return veredicto, f"num `AND`, o pior termo manda: {razao}"
    return PERMITIDA, " AND ".join(r for _, r in resultados)


def classificar(expressao: str | None, politica: Politica) -> tuple[str, str]:
    """Classifica uma expressao SPDX completa."""
    if expressao is None or not str(expressao).strip():
        return DESCONHECIDA, "sem campo de licenca"
    tokens = _TOKEN.findall(str(expressao))
    if not tokens:
        return DESCONHECIDA, f"expressao ilegivel ({expressao!r})"
    return _avaliar(tokens, politica)


def classificar_pacote(
    nome: str, expressao: str | None, politica: Politica
) -> tuple[str, str]:
    """Como `classificar`, mas verifica primeiro as decisoes pendentes por nome.

    O Redis e o Valkey estao travados pela D12, e a travagem e **pelo nome do
    componente**, nao pela licenca: o Valkey e `BSD-3-Clause`, que esta na
    allowlist, e aprova-lo por via da licenca fecharia a D12 pela porta de tras.
    """
    minusculas = nome.strip().lower()
    # As excepcoes vem **primeiro**: sao nomes exactos, e a correspondencia de
    # `pendentes` e parcial. Sem isto, o `redis-parser` — MIT, analisador do
    # protocolo RESP e dependencia do cliente `ioredis` — era travado pela D12,
    # que e sobre a licenca do **servidor** (medido ao entrar o publicador do
    # KAM-005). A lista esta em `ci/licenses.yaml`, nome a nome e com a razao.
    if minusculas in politica.excepcoes_de_nome:
        return classificar(expressao, politica)
    for pendente, decisao, razao in politica.pendentes:
        if pendente in minusculas:
            return PENDENTE, f"{decisao} esta aberta: {razao}"
    return classificar(expressao, politica)
