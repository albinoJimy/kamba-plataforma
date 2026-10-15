"""Leitura e validacao de `ops/secrets-inventory.yaml` (KAM-010).

Duas verificacoes, e cada uma falha fechada:

- **esquema** — toda a entrada tem os campos que o criterio de aceitacao pede
  (`owner`, `rotacao_dias`, `ambientes`, `consumidores`) e os que este ticket
  acrescentou, com valores dentro dos dominios permitidos;
- **cobertura** — 100% das linhas da tabela de `docs/tecnica/08` §5 estao
  cobertas por pelo menos uma entrada.

Nenhuma das duas le valores de segredos, porque nao ha valores no inventario.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .canon import componentes_do_doc_00, normalizar, segredos_do_doc_08
from .yamlsubset import YamlSubsetError, load

CAMINHO_INVENTARIO = Path("ops") / "secrets-inventory.yaml"

#: Nome de um segredo: a mesma forma que a `SecretRef` da porta aceita como
#: familia (`packages/core-ts/src/secrets/port.ts`, `libs/py-core/.../port.py`).
ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

#: Papeis responsaveis, de `docs/tecnica/08` §1.3 (Audiencia).
OWNERS = frozenset(
    {"seguranca", "eng_canais", "eng_runtime", "eng_pagamentos", "sre", "privacidade"}
)

AMBIENTES = ("dev", "staging", "prod")

#: Como as instancias de uma familia sao enderecadas.
INSTANCIAS = frozenset({"nenhuma", "tenant", "provedor", "conta", "epoca"})

CHAVES_DE_TOPO = (
    "versao",
    "ticket",
    "estado",
    "fonte",
    "actualizado_em",
    "estado_dos_campos",
    "analise_raizes",
    "analise_excluir",
    "segredos",
)

CAMPOS_OBRIGATORIOS = (
    "id",
    "fonte_08_5",
    "descricao",
    "owner",
    "rotacao_dias",
    "rotacao_gatilho",
    "ambientes",
    "obrigatorio_em",
    "consumidores",
    "instancias",
    "anel",
    "kid",
)

CAMPOS_CONHECIDOS = frozenset(CAMPOS_OBRIGATORIOS) | {"nota", "introduzido_por"}


@dataclass(frozen=True)
class Segredo:
    """Uma entrada do inventario, ja validada."""

    id: str
    fonte_08_5: str
    owner: str
    rotacao_dias: int | None
    rotacao_gatilho: str | None
    ambientes: tuple[str, ...]
    obrigatorio_em: tuple[str, ...]
    consumidores: tuple[str, ...]
    instancias: str
    anel: bool
    kid: bool
    nota: str | None = None


@dataclass
class Inventario:
    """O inventario inteiro."""

    segredos: tuple[Segredo, ...]
    raizes: tuple[str, ...]
    excluir: tuple[str, ...]
    estado: str
    por_id: dict[str, Segredo] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.por_id = {s.id: s for s in self.segredos}


def _como_lista(valor: object) -> list[object]:
    return list(valor) if isinstance(valor, list) else [valor]


def validar(bruto: dict[str, object], componentes: set[str]) -> tuple[Inventario, list[str]]:
    """Valida a estrutura. Devolve o inventario e a lista de erros.

    Devolve **todos** os erros e nao o primeiro: quem escreve um inventario de
    dezenove entradas corrige uma lista, nao descobre um campo por execucao.
    """
    erros: list[str] = []

    for chave in CHAVES_DE_TOPO:
        if chave not in bruto:
            erros.append(f"falta a chave de topo {chave!r}")
    desconhecidas = set(bruto) - set(CHAVES_DE_TOPO)
    for chave in sorted(desconhecidas):
        erros.append(f"chave de topo desconhecida: {chave!r}")

    if bruto.get("versao") != 1:
        erros.append(f"versao suportada e 1, nao {bruto.get('versao')!r}")

    cruas = bruto.get("segredos")
    if not isinstance(cruas, list) or len(cruas) == 0:
        erros.append("`segredos` tem de ser uma lista nao vazia")
        cruas = []

    segredos: list[Segredo] = []
    vistos: set[str] = set()
    for indice, crua in enumerate(cruas):
        if not isinstance(crua, dict):
            erros.append(f"segredo #{indice + 1} nao e um mapa")
            continue
        identificador = crua.get("id")
        rotulo = identificador if isinstance(identificador, str) else f"#{indice + 1}"

        for campo in CAMPOS_OBRIGATORIOS:
            if campo not in crua:
                erros.append(f"{rotulo}: falta o campo {campo!r}")
        for campo in sorted(set(crua) - CAMPOS_CONHECIDOS):
            erros.append(f"{rotulo}: campo desconhecido {campo!r}")

        if not isinstance(identificador, str) or ID.match(identificador) is None:
            erros.append(f"{rotulo}: `id` tem de ser snake_case de 3 a 64 caracteres")
            continue
        if identificador in vistos:
            erros.append(f"{identificador}: `id` repetido")
            continue
        vistos.add(identificador)

        owner = crua.get("owner")
        if owner not in OWNERS:
            erros.append(
                f"{identificador}: `owner` {owner!r} fora dos papeis de "
                f"docs/tecnica/08 §1.3 ({', '.join(sorted(OWNERS))})"
            )

        dias = crua.get("rotacao_dias")
        gatilho = crua.get("rotacao_gatilho")
        if dias is None:
            if not isinstance(gatilho, str) or gatilho.strip() == "":
                erros.append(
                    f"{identificador}: `rotacao_dias: null` exige `rotacao_gatilho` "
                    "(a rotacao e por evento, e o evento tem de estar escrito)"
                )
        elif not isinstance(dias, int) or isinstance(dias, bool) or dias <= 0:
            erros.append(f"{identificador}: `rotacao_dias` tem de ser inteiro > 0 ou null")

        ambientes = [v for v in _como_lista(crua.get("ambientes", [])) if v is not None]
        if len(ambientes) == 0:
            erros.append(f"{identificador}: `ambientes` nao pode ser vazio")
        for ambiente in ambientes:
            if ambiente not in AMBIENTES:
                erros.append(f"{identificador}: ambiente desconhecido {ambiente!r}")

        obrigatorios = [v for v in _como_lista(crua.get("obrigatorio_em", [])) if v is not None]
        for ambiente in obrigatorios:
            if ambiente not in ambientes:
                erros.append(
                    f"{identificador}: `obrigatorio_em` tem {ambiente!r}, que nao esta "
                    "em `ambientes` — um segredo nao pode ser obrigatorio onde nao existe"
                )

        consumidores = [v for v in _como_lista(crua.get("consumidores", [])) if v is not None]
        for codigo in consumidores:
            if codigo not in componentes:
                erros.append(
                    f"{identificador}: consumidor {codigo!r} nao e um codigo do catalogo "
                    "de docs/tecnica/00 §4"
                )
        nota = crua.get("nota")
        if len(consumidores) == 0 and not isinstance(nota, str):
            erros.append(
                f"{identificador}: `consumidores` vazio exige `nota` que diga quem o usa"
            )

        instancias = crua.get("instancias")
        if instancias not in INSTANCIAS:
            erros.append(
                f"{identificador}: `instancias` {instancias!r} fora de "
                f"{', '.join(sorted(INSTANCIAS))}"
            )

        for campo in ("anel", "kid"):
            if not isinstance(crua.get(campo), bool):
                erros.append(f"{identificador}: `{campo}` tem de ser true ou false")

        fonte = crua.get("fonte_08_5")
        if not isinstance(fonte, str) or fonte.strip() == "":
            erros.append(f"{identificador}: `fonte_08_5` tem de ser texto (ou \"-\")")
            fonte = "-"
        elif fonte.strip() == "-" and not isinstance(crua.get("introduzido_por"), str):
            erros.append(
                f"{identificador}: `fonte_08_5: \"-\"` exige `introduzido_por` com o "
                "ticket que o introduziu"
            )

        segredos.append(
            Segredo(
                id=identificador,
                fonte_08_5=str(fonte),
                owner=str(owner),
                rotacao_dias=dias if isinstance(dias, int) and not isinstance(dias, bool) else None,
                rotacao_gatilho=gatilho if isinstance(gatilho, str) else None,
                ambientes=tuple(str(a) for a in ambientes),
                obrigatorio_em=tuple(str(a) for a in obrigatorios),
                consumidores=tuple(str(c) for c in consumidores),
                instancias=str(instancias),
                anel=bool(crua.get("anel")),
                kid=bool(crua.get("kid")),
                nota=nota if isinstance(nota, str) else None,
            )
        )

    raizes = tuple(str(r) for r in _como_lista(bruto.get("analise_raizes", [])) if r is not None)
    excluir: list[str] = []
    for indice, item in enumerate(_como_lista(bruto.get("analise_excluir", []))):
        if not isinstance(item, dict):
            erros.append(f"analise_excluir #{indice + 1} nao e um mapa")
            continue
        caminho = item.get("caminho")
        razao = item.get("razao")
        if not isinstance(caminho, str) or caminho.strip() == "":
            erros.append(f"analise_excluir #{indice + 1}: falta `caminho`")
            continue
        if not isinstance(razao, str) or razao.strip() == "":
            # Uma excepcao sem razao escrita e uma excepcao que ninguem revoga.
            erros.append(f"analise_excluir {caminho!r}: falta `razao`")
        excluir.append(caminho.replace("\\", "/"))

    inventario = Inventario(
        segredos=tuple(segredos),
        raizes=raizes,
        excluir=tuple(excluir),
        estado=str(bruto.get("estado", "")),
    )
    return inventario, erros


def carregar(raiz: Path) -> tuple[Inventario, list[str]]:
    """Le, interpreta e valida o inventario do repositorio em `raiz`."""
    caminho = raiz / CAMINHO_INVENTARIO
    if not caminho.is_file():
        return Inventario((), (), (), ""), [f"inventario ausente: {CAMINHO_INVENTARIO}"]
    try:
        bruto = load(caminho.read_text(encoding="utf-8"))
    except YamlSubsetError as erro:
        return Inventario((), (), (), ""), [f"{CAMINHO_INVENTARIO}: {erro}"]
    componentes = componentes_do_doc_00(raiz)
    return validar(bruto, componentes)


def cobertura(raiz: Path, inventario: Inventario) -> tuple[list[str], list[str]]:
    """Linhas do doc 08 §5 cobertas e nao cobertas pelo inventario."""
    linhas = segredos_do_doc_08(raiz)
    reclamadas = {normalizar(s.fonte_08_5) for s in inventario.segredos}
    cobertas = [linha for linha in linhas if normalizar(linha) in reclamadas]
    em_falta = [linha for linha in linhas if normalizar(linha) not in reclamadas]
    return cobertas, em_falta


def orfas(raiz: Path, inventario: Inventario) -> list[Segredo]:
    """Entradas que reclamam uma linha do doc 08 §5 que nao existe.

    O caso tipico e uma gralha numa copia do rotulo. Sem esta verificacao, uma
    gralha faria a cobertura descer sem ninguem saber onde.
    """
    linhas = {normalizar(linha) for linha in segredos_do_doc_08(raiz)}
    return [
        s
        for s in inventario.segredos
        if s.fonte_08_5.strip() != "-" and normalizar(s.fonte_08_5) not in linhas
    ]
