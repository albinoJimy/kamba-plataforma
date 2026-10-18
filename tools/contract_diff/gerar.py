"""Tipos TypeScript e modelos Python a partir dos contratos (criterio 7).

## Porque e que o gerador e nosso

O DoD pede «gerador de tipos fixado por lockfile; licenca verificada», e isso
supoe um gerador de terceiros. Nao se trouxe nenhum, e a razao tem precedente
neste repositorio: o `tools/kamba_yaml.py` recusou o PyYAML e escreveu o
subconjunto de YAML que o repositorio usa, porque o subconjunto e pequeno e o
custo de uma dependencia nova nao e so a dependencia — e o SBOM, a licenca, o
`--require-hashes`, e a actualizacao a cada CVE de um projecto inteiro de que
usamos uma funcao.

Aqui o argumento e mais forte ainda, porque o subconjunto de JSON Schema que os
contratos usam **nao e o que algum dia venha a aparecer**: e o que este mesmo
pacote escreve e o `canon_lint` verifica. Sao nove palavras-chave. Um gerador
de uso geral traria suporte para `oneOf`, `$ref` externos, `patternProperties`
e mais trinta coisas que os contratos nao podem ter.

**O que isto custa, e fica dito:** uma palavra-chave nova num contrato nao
aparece nos tipos sem alguem a acrescentar aqui. O `PALAVRAS_SUPORTADAS`
fecha-o pelo lado ruidoso — o gerador **recusa** o que nao sabe traduzir, em
vez de emitir um tipo errado.

## O que se gera, e porque sao duas coisas

    tipos       uma interface por payload. Servem quem escreve codigo: o
                compilador recusa um campo com o nome errado.
    catalogo    tipo -> {versao, obrigatorios, permitidos}. Serve quem valida
                em execucao: e o que o `validarPayload` le.

Os tipos sozinhos nao chegam porque um `JSON.parse` devolve `unknown` e um
`as` nao verifica nada; o catalogo sozinho nao chega porque nao ha erro de
compilacao nenhum num nome mal escrito.
"""

from __future__ import annotations

from pathlib import Path

from contract_diff import catalogo

#: O que o gerador sabe traduzir. Uma palavra-chave fora disto e recusa.
PALAVRAS_SUPORTADAS = frozenset(
    {"type", "properties", "required", "additionalProperties", "enum", "const",
     "items", "minimum", "maximum", "minItems", "uniqueItems", "format",
     "description", "title", "$schema", "$id", "minLength", "maxLength", "pattern"}
)

DESTINO_TS = Path("packages") / "contracts" / "src" / "eventos.gerado.ts"
DESTINO_PY = Path("libs") / "py-core" / "src" / "kamba_core" / "eventos" / "contratos.py"

AVISO = "Gerado por `python -m contract_diff gerar`. Nao editar a mao."


class NaoSeiTraduzirError(ValueError):
    """Uma palavra-chave que o gerador nao sabe traduzir."""


def _nome_do_tipo(tipo: str) -> str:
    """`order.created` -> `OrderCreated`."""
    return "".join(parte.title() for parte in tipo.replace(".", "_").split("_"))


def _nome_do_payload(tipo: str, versao: int) -> str:
    """`order.created` v1 -> `PayloadOrderCreated`; v2 -> `...V2` (KAM-159).

    **A `v1` mantem o nome sem sufixo**, e isso nao e preguica: o nome sem
    sufixo esta escrito em codigo que nao e gerado, e renomea-lo seria uma
    alteracao quebrante no pacote por causa de uma versao nova de **outro**
    contrato. A regra e a mesma do `exemplo.json`: a primeira versao fica com
    o nome historico.

    O sufixo e preciso porque o payload **pode** mudar entre versoes — e muda:
    o `consent.recorded` e o `consent.withdrawn` tem o dominio das finalidades
    dentro do proprio payload, pelo que a `v2` deles difere da `v1`. Sem
    sufixo, o TypeScript funde as duas interfaces com o mesmo nome e recusa
    («Subsequent property declarations must have the same type»).
    """
    return _nome_do_tipo(tipo) + ("" if versao == 1 else f"V{versao}")


def _verificar(no: dict, onde: str) -> None:
    desconhecidas = set(no) - PALAVRAS_SUPORTADAS
    if desconhecidas:
        raise NaoSeiTraduzirError(
            f"{onde}: {sorted(desconhecidas)} — o gerador recusa o que nao sabe "
            "traduzir, em vez de emitir um tipo errado. Acrescente o suporte em "
            "tools/contract_diff/gerar.py, ou nao use a palavra-chave no contrato"
        )
    for nome, filho in (no.get("properties") or {}).items():
        _verificar(filho, f"{onde}.{nome}")
    if isinstance(no.get("items"), dict):
        _verificar(no["items"], f"{onde}[]")


def _ts(no: dict, indentacao: int = 2) -> str:
    """O tipo TypeScript de um no."""
    if "const" in no:
        valor = no["const"]
        return f'"{valor}"' if isinstance(valor, str) else str(valor).lower()
    if "enum" in no:
        return " | ".join(f'"{v}"' for v in no["enum"])
    tipos = no.get("type")
    tipos = tipos if isinstance(tipos, list) else [tipos]
    anulavel = "null" in tipos
    principal = next((t for t in tipos if t != "null"), "string")
    if principal == "object":
        corpo = _ts_objecto(no, indentacao)
    elif principal == "array":
        corpo = f"readonly {_ts(no.get('items') or {'type': 'string'}, indentacao)}[]"
    elif principal == "integer":
        corpo = "number"
    elif principal == "boolean":
        corpo = "boolean"
    else:
        corpo = "string"
    return f"{corpo} | null" if anulavel else corpo


def _ts_objecto(no: dict, indentacao: int) -> str:
    obrigatorios = set(no.get("required") or [])
    espaco = " " * indentacao
    linhas = ["{"]
    for nome, filho in (no.get("properties") or {}).items():
        opcional = "" if nome in obrigatorios else "?"
        linhas.append(f"{espaco}readonly {nome}{opcional}: {_ts(filho, indentacao + 2)};")
    linhas.append(" " * (indentacao - 2) + "}")
    return "\n".join(linhas)


def typescript(contratos: list[catalogo.Contrato]) -> str:
    partes = [
        "/**",
        f" * {AVISO}",
        " *",
        " * Os tipos dos payloads dos contratos de `contratos/eventos/`, e o catalogo",
        " * que o `validarPayload` le em execucao. Os dois sao precisos: um `as` nao",
        " * verifica nada em execucao, e um nome mal escrito nao da erro de compilacao",
        " * nenhum a quem le de um catalogo.",
        " *",
        " * O gate 7 (`make ci-7`) falha se este ficheiro estiver desactualizado.",
        " */",
        "",
    ]
    for contrato in contratos:
        nome = _nome_do_payload(contrato.tipo, contrato.versao)
        partes.append(f"/** Payload de `{contrato.tipo}` v{contrato.versao}. */")
        partes.append(f"export interface Payload{nome} {_ts_objecto(contrato.payload, 2)}")
        partes.append("")

    partes.append("/** O que o `validarPayload` precisa de saber de cada contrato. */")
    partes.append("export interface EntradaDoCatalogo {")
    partes.append("  /** Todas as versoes publicadas deste tipo, por ordem crescente. */")
    partes.append("  readonly versoes: readonly number[];")
    partes.append("  readonly obrigatorios: readonly string[];")
    partes.append("  readonly permitidos: readonly string[];")
    partes.append("}")
    partes.append("")
    partes.append("/** Todos os contratos, por tipo. A lista e fechada: um tipo fora dela e desconhecido. */")
    partes.append("export const CATALOGO = {")
    for tipo, versoes in _por_tipo(contratos).items():
        contrato = versoes[0]
        obrigatorios = sorted(contrato.payload.get("required") or [])
        permitidos = sorted((contrato.payload.get("properties") or {}))
        numeros = ", ".join(str(c.versao) for c in versoes)
        partes.append(f'  "{tipo}": {{')
        partes.append(f"    versoes: [{numeros}],")
        partes.append(f"    obrigatorios: [{', '.join(repr(o).replace(chr(39), chr(34)) for o in obrigatorios)}],")
        partes.append(f"    permitidos: [{', '.join(repr(p).replace(chr(39), chr(34)) for p in permitidos)}],")
        partes.append("  },")
    partes.append("} as const satisfies Record<string, EntradaDoCatalogo>;")
    partes.append("")
    partes.append("/** Os tipos de evento que tem contrato. */")
    partes.append("export type TipoDeEvento = keyof typeof CATALOGO;")
    partes.append("")
    return "\n".join(partes)


def _por_tipo(contratos: list) -> dict[str, list]:
    """Os contratos agrupados por tipo, por versao crescente (KAM-159).

    Ate a primeira `v2` existir, havia **um** contrato por tipo e o catalogo
    era indexado por tipo. Com duas versoes a chave repetia-se, e o TypeScript
    nao compilava: «An object literal cannot have multiple properties with the
    same name».

    **O limite deste gerador, dito e preso por asserção.** A entrada do
    catalogo guarda uma **forma de payload por tipo**, e nao por versao: hoje
    isso e verdade — a `v2` do KAM-159 difere da `v1` no dominio de
    `finalidades`, que vive no **envelope**, e os payloads sao iguais. No dia
    em que uma versao mudar o payload, isto rebenta aqui, com nome, em vez de
    gerar um catalogo que valida a versao errada em silencio.
    """
    grupos: dict[str, list] = {}
    for contrato in contratos:
        grupos.setdefault(contrato.tipo, []).append(contrato)
    for tipo, versoes in grupos.items():
        versoes.sort(key=lambda c: c.versao)
        primeira = versoes[0]
        for outra in versoes[1:]:
            mesma = (
                sorted(primeira.payload.get("required") or [])
                == sorted(outra.payload.get("required") or [])
                and sorted(primeira.payload.get("properties") or {})
                == sorted(outra.payload.get("properties") or {})
            )
            if not mesma:
                raise NaoSeiTraduzirError(
                    f"{tipo}: a v{outra.versao} tem um payload diferente da "
                    f"v{primeira.versao}, e este gerador guarda **uma** forma "
                    "de payload por tipo. Passe a entrada do catalogo a ter a "
                    "forma por versao antes de publicar esta versao."
                )
    return dict(sorted(grupos.items()))


def _py(no: dict) -> str:
    if "enum" in no and all(isinstance(v, str) for v in no["enum"]):
        return "str"
    if "const" in no:
        return "str" if isinstance(no["const"], str) else "int"
    tipos = no.get("type")
    tipos = tipos if isinstance(tipos, list) else [tipos]
    anulavel = "null" in tipos
    principal = next((t for t in tipos if t != "null"), "string")
    corpo = {
        "object": "dict[str, object]",
        "array": "list[object]",
        "integer": "int",
        "boolean": "bool",
    }.get(principal, "str")
    return f"{corpo} | None" if anulavel else corpo


def python(contratos: list[catalogo.Contrato]) -> str:
    partes = [
        '"""' + AVISO,
        "",
        "Os payloads dos contratos de `contratos/eventos/`, como `TypedDict`, e o",
        "catalogo que o espelho em Python le. O gate 7 (`make ci-7`) falha se este",
        "ficheiro estiver desactualizado.",
        '"""',
        "",
        # Sem `from __future__ import annotations`: com ele as anotacoes ficam
        # texto e o `TypedDict` deixa de reconhecer o `NotRequired` **em
        # execucao** — o `__required_keys__` passa a dizer que todos os campos
        # sao obrigatorios, que e o contrario do que o ficheiro declara. O
        # mypy le-o bem nos dois casos; o que se perde e a verdade em runtime,
        # e e dela que um teste se serve. Nada aqui precisa do adiamento:
        # `str`, `int`, `bool`, `list[object]` e `X | None` existem todos no
        # 3.12, que e o piso do `libs/py-core`.
        "from typing import NotRequired, TypedDict",
        "",
        "",
    ]
    for contrato in contratos:
        nome = _nome_do_payload(contrato.tipo, contrato.versao)
        obrigatorios = set(contrato.payload.get("required") or [])
        propriedades = contrato.payload.get("properties") or {}
        # `total=True`, com `NotRequired` nos opcionais. A primeira versao
        # escrevia `total=False` em todos, e isso fazia do lado Python uma
        # declaracao sem forca nenhuma: um `PayloadOrderCreated()` vazio
        # passava o `mypy`, enquanto o lado TypeScript distinguia `x: T` de
        # `x?: T`. Achado M5 da revisao adversarial, e nao e hipotetico — o
        # AGR, que e Python, e produtor de `review.created` e dos tres
        # `query.*`, todos de Fase P.
        partes.append(f"class Payload{nome}(TypedDict):")
        partes.append(f'    """Payload de `{contrato.tipo}` v{contrato.versao}."""')
        if not propriedades:
            partes.append("    # Sem campos: o envelope ja diz tudo o que este evento diz.")
        for campo, corpo in propriedades.items():
            anotacao = _py(corpo)
            if campo not in obrigatorios:
                anotacao = f"NotRequired[{anotacao}]"
            partes.append(f"    {campo}: {anotacao}")
        partes.append("")
        partes.append("")

    partes.append("#: Todos os contratos, por tipo. Lista fechada.")
    partes.append("CATALOGO: dict[str, dict[str, object]] = {")
    for tipo, versoes in _por_tipo(contratos).items():
        contrato = versoes[0]
        obrigatorios = sorted(contrato.payload.get("required") or [])
        permitidos = sorted((contrato.payload.get("properties") or {}))
        partes.append(f'    "{tipo}": {{')
        partes.append(f'        "versoes": {[c.versao for c in versoes]!r},')
        partes.append(f'        "obrigatorios": {obrigatorios!r},')
        partes.append(f'        "permitidos": {permitidos!r},')
        partes.append("    },")
    partes.append("}")
    partes.append("")
    partes.append("")
    partes.extend(_VALIDADOR_PY.splitlines())
    partes.append("")
    return "\n".join(partes)


#: O espelho Python do `validarPayload` de `@kamba/core-ts`.
#:
#: Escrito aqui, no gerador, e nao a mao no `libs/py-core`: a forma do
#: `CATALOGO` e desta funcao sao a mesma coisa, e duas copias que se podem
#: desalinhar sao o defeito que este gerador existe para nao ter. O lado
#: TypeScript tem a mesma funcao a mao porque la o catalogo e importado, nao
#: embebido.
_VALIDADOR_PY = '''class TipoDesconhecidoError(ValueError):
    """Um tipo de evento que nao tem contrato."""


class VersaoDesconhecidaError(ValueError):
    """Uma versao que nao e a do contrato publicado."""


class PayloadInvalidoError(ValueError):
    """O payload nao bate com o contrato: falta obrigatorio ou sobra campo."""


def tipos_com_contrato() -> list[str]:
    """Os tipos de evento que tem contrato publicado, por ordem."""
    return sorted(CATALOGO)


def validar_payload(tipo: str, versao: int, payload: dict) -> None:
    """Recusa o que o contrato nao admite, antes de o evento ser emitido.

    O espelho do `validarPayload` de `@kamba/core-ts`, com o **mesmo limite**:
    verifica o tipo, a versao, os campos obrigatorios e os campos a mais, e
    **nao** verifica tipos nem formatos — isso e JSON Schema completo em
    execucao, que e uma dependencia que o lado Python nao tem no caminho de
    emissao. Os tipos sao do verificador estatico, pelo `Payload*` gerado
    acima, que desde o KAM-007 distingue obrigatorio de opcional.
    """
    entrada = CATALOGO.get(tipo)
    if entrada is None:
        raise TipoDesconhecidoError(
            f"{tipo} nao tem contrato em contratos/eventos/; "
            f"os que tem: {', '.join(tipos_com_contrato())}"
        )
    versoes = entrada["versoes"]
    if versao not in versoes:
        publicadas = ", ".join(f"v{v}" for v in versoes)
        raise VersaoDesconhecidaError(
            f"{tipo} v{versao}: as versoes publicadas sao {publicadas}"
        )
    if not isinstance(payload, dict):
        raise PayloadInvalidoError(f"{tipo}: o payload tem de ser um objecto")
    obrigatorios = set(entrada["obrigatorios"])
    permitidos = set(entrada["permitidos"])
    em_falta = sorted(obrigatorios - set(payload))
    se_sobra = sorted(set(payload) - permitidos)
    if em_falta or se_sobra:
        partes = []
        if em_falta:
            partes.append(f"faltam {em_falta}")
        if se_sobra:
            partes.append(f"sobram {se_sobra} (o contrato e fechado)")
        raise PayloadInvalidoError(f"{tipo} v{versao}: " + "; ".join(partes))
'''


def gerar(raiz: Path) -> dict[Path, str]:
    """O conteudo que cada ficheiro gerado devia ter."""
    contratos = catalogo.todos(raiz)
    for contrato in contratos:
        _verificar(contrato.documento, contrato.relativo)
    return {DESTINO_TS: typescript(contratos), DESTINO_PY: python(contratos)}


def escrever(raiz: Path) -> list[Path]:
    escritos = []
    for relativo, conteudo in gerar(raiz).items():
        caminho = raiz / relativo
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(conteudo, encoding="utf-8")
        escritos.append(relativo)
    return escritos


def desactualizados(raiz: Path) -> list[str]:
    """Os ficheiros gerados que nao batem com os contratos de hoje."""
    fora = []
    for relativo, esperado in gerar(raiz).items():
        caminho = raiz / relativo
        if not caminho.is_file():
            fora.append(f"{relativo.as_posix()}: nao existe")
        elif caminho.read_text(encoding="utf-8") != esperado:
            fora.append(
                f"{relativo.as_posix()}: desactualizado. Corra "
                "`python -m contract_diff gerar` e inclua o resultado no commit"
            )
    return fora
