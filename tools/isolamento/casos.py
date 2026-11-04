"""O registo de casos, e a cobertura que recusa uma superficie sem caso.

Criterio 2 do KAM-066, segunda metade: «um item enumerado sem caso registado
falha o CI (nao existe "sem teste" silencioso)». A API e a que os Detalhes
Tecnicos do bloco escrevem — `registerCase({id, camada, enumeravel, fn})` — com
o nome desta casa, `registar_caso`, e com `enumeravel` a ser uma **tupla de
identificadores de itens**: os que este caso cobre.

## Porque e que `enumeravel` sao identificadores e nao um filtro

Um `enumeravel` que fosse um predicado — «cubro todas as rotas» — fazia a
cobertura passar para sempre e a verificacao deixava de verificar: uma rota
nova ficava coberta no instante em que nascesse, que e exactamente o «sem teste
silencioso» com outro nome. Sendo identificadores, uma rota nova **nao esta em
lista nenhuma** e o CI fica vermelho ate alguem escrever o caso dela, ou
declarar a dispensa com o credor por escrito.

E porque sao identificadores, uma rota que **desapareca** tambem avermelha: o
caso fica a apontar para um item que nao existe. Isso tem nome nesta casa — uma
dispensa morta — e o remedio e o mesmo: retirar.

## Tres resultados, e nenhum e «mais ou menos»

```text
item com caso        o caso corre na suite e tem de passar
item com dispensa    nao corre; a dispensa nomeia o credor e a razao
item sem nenhum      o CI falha, e diz qual
```

As dispensas vivem em `ci/isolamento-dispensas.yaml`, na forma dos outros
catorze leitores de `ci/*.yaml` desta casa (`version: 1`, uma lista, e cada
entrada com o credor e a razao). Tres trincos, e o terceiro e o que impede a
valvula de virar porta:

1. **o credor e um ticket que existe** — confronta-se com o §4 do
   `specs/INDICE.md`, nao com uma expressao regular. Um numero inventado que
   tenha a forma de um ticket **nao** passa — e so a forma que uma expressao
   regular ve;
2. **a razao tem de ter corpo** — sessenta caracteres, o dobro do que os
   `rls_exceptions` pedem, porque uma dispensa ao isolamento e a unica coisa
   neste ficheiro que ninguem mede depois;
3. **uma dispensa morta falha** — para um item que ja nao existe, ou para um
   item que entretanto ganhou caso.

## Os casos **declaram-se** aqui e **executam-se** na suite

Os modulos de `baterias/` sao importaveis sem PostgreSQL, sem `node` e sem rede: e
o que permite a cobertura ser medida a seco, no passo do *gate* 6 que corre
antes de o contentor subir. O `fn` de cada caso recebe um **contexto** que a
suite constroi (cursores, canarios, o oraculo) e devolve os achados; quem o
chama e `db/tests_isolamento/test_casos_cruzados.py`.
"""

from __future__ import annotations

import dataclasses
import re
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ / "tools") not in sys.path:
    sys.path.insert(0, str(RAIZ / "tools"))

from kamba_yaml import exigir_chaves, load_file  # noqa: E402

from .enumeracao import Item  # noqa: E402

#: As baterias de `docs/tecnica/08` §3.7, com o X-07 **reservado aqui**: a lista
#: original salta do X-06 para o X-08, e o bloco do KAM-066 manda documentar a
#: lacuna. Reservar e nao reutilizar: um X-07 atribuido a outra coisa fazia uma
#: referencia antiga a `08` §3.7 passar a apontar para a bateria errada.
BATERIAS = (
    "X-01",  # rotas: IDOR autenticado
    "X-02",  # tools do REG: estado de A, argumentos de B
    "X-03",  # SQL directo com contexto
    "X-04",  # SQL directo sem contexto (falha fechada)
    "X-05",  # catalogo: RLS FORCE, NOBYPASSRLS, SECURITY DEFINER, vistas
    "X-06",  # vectores (KAM-061)
    "X-07",  # RESERVADO — a lacuna da lista de `docs/tecnica/08` §3.7
    "X-08",  # storage (KAM-011, KAM-020)
    "X-09",  # injeccao cruzada, >= 30 prompts PT-AO (KAM-073)
    "X-10",  # cross-seller e cross-account (KAM-042, KAM-019)
    "X-11",  # logs (KAM-068; corre no `make x11`, dentro do gate 6)
    "C-01",  # isolamento de contacto: X nao le Y, no mesmo tenant
    "P-01",  # pooling em modo transaccao
)

#: O X-07 nao tem, e nao pode ter, caso. Esta aqui para que a lacuna seja
#: visivel no codigo e nao so numa nota de PR.
RESERVADAS = ("X-07",)

_TICKET = re.compile(r"^KAM-[0-9]{3}$")

#: O minimo de corpo de uma razao de dispensa. Ver o ponto 2 da *docstring*.
RAZAO_MINIMA = 60


class RegistoInvalido(RuntimeError):
    """Um caso mal declarado, ou `ci/isolamento-dispensas.yaml` malformado."""


#: O que um caso precisa para correr, e **onde** ele corre. A dependencia e
#: que escolhe a suite, e nao a bateria:
#:
#:   nada      biblioteca padrao e a arvore — o passo a seco do gate 6
#:   agr       o pacote do AGR (starlette, pydantic, yaml) — services/agr/tests
#:   postgres  a base do gate — db/tests_isolamento
#:   node      o condutor de TypeScript — db/tests_isolamento
PRECISA = ("nada", "agr", "postgres", "node")


@dataclasses.dataclass(frozen=True)
class Caso:
    """Um caso de isolamento. `fn` corre na suite; aqui so se declara."""

    id: str
    #: A bateria de `docs/tecnica/08` §3.7 (ou `C-01`/`P-01`).
    bateria: str
    #: A camada que o caso ataca: `rotas`, `tls`, `rls`, `catalogo`, `pool`.
    camada: str
    #: Os identificadores de itens que este caso cobre. Vazia num caso que nao
    #: cobre superficie enumerada (o X-03, que e por tabela e nao por rota).
    enumeravel: tuple[str, ...]
    #: `fn(contexto) -> list[str]` — os achados. Lista vazia e conforme.
    fn: Callable[..., list[str]]
    #: O que o caso precisa para correr. O corredor **falha** se um caso for
    #: saltado: num *gate*, saltar e falhar (`db/correr_suite.py`).
    precisa: str = "nada"
    #: As origens do oraculo que este caso varre (criterio 9). O corredor
    #: confronta-as com as que o caso devolve: um caso que declare `logs` e nao
    #: varra logs e um achado, nao um verde.
    origens: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.precisa not in PRECISA:
            raise RegistoInvalido(
                f"{self.id}: `precisa` {self.precisa!r} fora de {PRECISA}"
            )
        if self.bateria not in BATERIAS:
            raise RegistoInvalido(
                f"{self.id}: bateria {self.bateria!r} fora de {BATERIAS}"
            )
        if self.bateria in RESERVADAS:
            raise RegistoInvalido(
                f"{self.id}: {self.bateria} esta reservada e nao pode ter caso "
                "(`docs/tecnica/08` §3.7 salta-a; o KAM-066 reserva-a)"
            )
        if not callable(self.fn):
            raise RegistoInvalido(f"{self.id}: `fn` nao e chamavel")


#: O registo. Um modulo de `baterias/` acrescenta aqui ao ser importado.
REGISTO: dict[str, Caso] = {}


def registar_caso(
    *,
    id: str,  # noqa: A002 — e o nome que o bloco escreve
    bateria: str,
    camada: str,
    enumeravel: Iterable[str] = (),
    fn: Callable[..., list[str]],
    precisa: str = "nada",
    origens: Iterable[str] = (),
) -> Caso:
    """Declara um caso. Um `id` repetido e erro, nao substituicao."""
    if id in REGISTO:
        raise RegistoInvalido(
            f"caso {id!r} registado duas vezes. Um registo que substituisse em "
            "silencio deixava o segundo caso a correr e o primeiro a parecer "
            "coberto."
        )
    caso = Caso(
        id=id,
        bateria=bateria,
        camada=camada,
        enumeravel=tuple(enumeravel),
        fn=fn,
        precisa=precisa,
        origens=tuple(origens),
    )
    REGISTO[id] = caso
    return caso


def carregar_casos() -> dict[str, Caso]:
    """Importa os modulos de `baterias/` e devolve o registo.

    O `import` e o que povoa o `REGISTO`: e a mesma forma do `unittest` a
    descobrir testes, e evita uma segunda lista de casos a manter a mao — que
    divergiria no primeiro caso que alguem esquecesse de inscrever.

    O pacote chama-se `baterias/` e nao `casos/` porque este modulo **e** o
    `casos`: um modulo e um pacote com o mesmo nome no mesmo sitio nao podem
    coexistir, e as baterias sao o que `docs/tecnica/08` §3.7 chama a cada
    grupo (X-01 a X-11).
    """
    from . import baterias  # noqa: PLC0415 — importacao tardia por desenho

    baterias.carregar()
    return dict(REGISTO)


# ------------------------------------------------------------------ dispensas


@dataclasses.dataclass(frozen=True)
class Dispensa:
    item: str
    credor: str
    razao: str


def _tickets_do_backlog(raiz: Path) -> set[str]:
    """Os `KAM-NNN` do §4 do `specs/INDICE.md`.

    Le-se o indice e nao uma expressao regular: um credor que nao existe no
    backlog e uma dispensa que ninguem vai pagar, e um numero inventado passava
    por um ticket so por ter a forma de um. (O canario que o prova esta em
    `tests/test_cobertura.py`, com a referencia invalida declarada em
    `ci/refs-allow.yaml` — e e o unico sitio onde ela precisa de estar.)
    """
    indice = raiz / "specs" / "INDICE.md"
    if not indice.is_file():
        raise RegistoInvalido(f"{indice} nao existe: nao ha backlog para conferir")
    return set(re.findall(r"\bKAM-[0-9]{3}\b", indice.read_text(encoding="utf-8")))


def ler_dispensas(raiz: Path = RAIZ) -> dict[str, Dispensa]:
    """`ci/isolamento-dispensas.yaml`, validado. Pode ser uma lista vazia."""
    caminho = raiz / "ci" / "isolamento-dispensas.yaml"
    if not caminho.is_file():
        raise RegistoInvalido(f"ficheiro em falta: {caminho}")
    dados = load_file(caminho)
    exigir_chaves(dados, {"version", "dispensas"}, caminho.name, erro=RegistoInvalido)
    if dados.get("version") != 1:
        raise RegistoInvalido(f"{caminho.name}: 'version' tem de ser 1")
    tickets = _tickets_do_backlog(raiz)
    entradas: dict[str, Dispensa] = {}
    for indice, entrada in enumerate(dados.get("dispensas") or [], start=1):
        exigir_chaves(
            entrada,
            {"item", "credor", "razao"},
            f"{caminho.name}: entrada {indice}",
            erro=RegistoInvalido,
        )
        item = str(entrada["item"])
        credor = str(entrada["credor"])
        razao = str(entrada["razao"])
        if not _TICKET.match(credor):
            raise RegistoInvalido(
                f"{caminho.name}: {item}: `credor` tem de ser KAM-NNN, nao "
                f"{credor!r}. Uma dispensa ao isolamento tem dono."
            )
        if credor not in tickets:
            raise RegistoInvalido(
                f"{caminho.name}: {item}: o credor {credor} nao existe no §4 do "
                "specs/INDICE.md. Uma dispensa cujo credor nao existe nunca e "
                "paga."
            )
        if len(razao) < RAZAO_MINIMA:
            raise RegistoInvalido(
                f"{caminho.name}: {item}: a razao tem {len(razao)} caracteres e "
                f"precisa de {RAZAO_MINIMA}. Escreva o que o caso teria de "
                "levantar e porque e que ainda nao pode."
            )
        if item in entradas:
            raise RegistoInvalido(f"{caminho.name}: {item} repetido")
        entradas[item] = Dispensa(item=item, credor=credor, razao=razao)
    return entradas


# ------------------------------------------------------------------ cobertura


def cobertura(
    itens: Sequence[Item],
    casos: dict[str, Caso] | None = None,
    dispensas: dict[str, Dispensa] | None = None,
) -> list[str]:
    """Os problemas de cobertura. Lista vazia quer dizer 100%.

    Quatro perguntas, e as quatro tem de dar a mesma resposta para a cobertura
    ser verdadeira — nao so a primeira:

    1. todo o item enumerado tem caso ou dispensa;
    2. todo o `enumeravel` de um caso e um item que existe;
    3. toda a dispensa e para um item que existe;
    4. nenhuma dispensa cobre um item que ja tem caso.
    """
    casos = carregar_casos() if casos is None else casos
    dispensas = ler_dispensas() if dispensas is None else dispensas
    problemas: list[str] = []

    por_item: dict[str, list[str]] = {}
    for caso in casos.values():
        for alvo in caso.enumeravel:
            por_item.setdefault(alvo, []).append(caso.id)

    existentes = {item.id: item for item in itens}

    for item in itens:
        tem_caso = item.id in por_item
        tem_dispensa = item.id in dispensas
        if tem_caso and tem_dispensa:
            problemas.append(
                f"{item.id}: tem caso ({', '.join(por_item[item.id])}) **e** "
                f"dispensa (credor {dispensas[item.id].credor}). A dispensa "
                "esta morta, retire-a."
            )
            continue
        if tem_caso or tem_dispensa:
            continue
        indicacao = (
            " O nome deste item leva o sitio em vez do caminho porque a "
            "enumeracao nao o conseguiu resolver — ver `enumeracao.py`."
            if item.indeciso
            else ""
        )
        problemas.append(
            f"{item.id} ({item.tipo}, {item.onde}): superficie enumerada sem "
            f"caso registado.{indicacao} Escreva o caso em "
            "`security/isolation/baterias/`, ou declare a dispensa em "
            "`ci/isolamento-dispensas.yaml` com o credor e a razao."
        )

    for caso in casos.values():
        for alvo in caso.enumeravel:
            if alvo not in existentes:
                problemas.append(
                    f"{caso.id}: cobre {alvo!r}, que a enumeracao nao encontra. "
                    "A superficie mudou de nome ou desapareceu: actualize o "
                    "caso, ou retire-o."
                )

    for dispensa in dispensas.values():
        if dispensa.item not in existentes:
            problemas.append(
                f"{dispensa.item}: esta em ci/isolamento-dispensas.yaml e nao e "
                "uma superficie enumerada — a dispensa esta morta, retire-a."
            )

    return problemas


def relatorio(itens: Sequence[Item], raiz: Path = RAIZ) -> str:
    """Contagem por tipo, e por bateria. Para o registo do *gate*."""
    casos = carregar_casos()
    dispensas = ler_dispensas(raiz)
    cobertos = {alvo for caso in casos.values() for alvo in caso.enumeravel}
    linhas = [
        f"itens enumerados: {len(itens)}",
        f"casos registados: {len(casos)}",
        f"itens com caso:   {len(cobertos & {i.id for i in itens})}",
        f"itens dispensados: {len(dispensas)}",
        f"itens indecisos:  {sum(1 for i in itens if i.indeciso)}",
    ]
    por_bateria: dict[str, int] = {}
    for caso in casos.values():
        por_bateria[caso.bateria] = por_bateria.get(caso.bateria, 0) + 1
    for bateria in BATERIAS:
        if bateria in RESERVADAS:
            linhas.append(f"  {bateria}: reservada (lacuna de `08` §3.7)")
            continue
        linhas.append(f"  {bateria}: {por_bateria.get(bateria, 0)} caso(s)")
    return "\n".join(linhas)
