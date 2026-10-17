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
        nome = _nome_do_tipo(contrato.tipo)
        partes.append(f"/** Payload de `{contrato.tipo}` v{contrato.versao}. */")
        partes.append(f"export interface Payload{nome} {_ts_objecto(contrato.payload, 2)}")
        partes.append("")

    partes.append("/** O que o `validarPayload` precisa de saber de cada contrato. */")
    partes.append("export interface EntradaDoCatalogo {")
    partes.append("  readonly versao: number;")
    partes.append("  readonly obrigatorios: readonly string[];")
    partes.append("  readonly permitidos: readonly string[];")
    partes.append("}")
    partes.append("")
    partes.append("/** Todos os contratos, por tipo. A lista e fechada: um tipo fora dela e desconhecido. */")
    partes.append("export const CATALOGO = {")
    for contrato in contratos:
        obrigatorios = sorted(contrato.payload.get("required") or [])
        permitidos = sorted((contrato.payload.get("properties") or {}))
        partes.append(f'  "{contrato.tipo}": {{')
        partes.append(f"    versao: {contrato.versao},")
        partes.append(f"    obrigatorios: [{', '.join(repr(o).replace(chr(39), chr(34)) for o in obrigatorios)}],")
        partes.append(f"    permitidos: [{', '.join(repr(p).replace(chr(39), chr(34)) for p in permitidos)}],")
        partes.append("  },")
    partes.append("} as const satisfies Record<string, EntradaDoCatalogo>;")
    partes.append("")
    partes.append("/** Os tipos de evento que tem contrato. */")
    partes.append("export type TipoDeEvento = keyof typeof CATALOGO;")
    partes.append("")
    return "\n".join(partes)


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
        "from __future__ import annotations",
        "",
        "from typing import TypedDict",
        "",
        "",
    ]
    for contrato in contratos:
        nome = _nome_do_tipo(contrato.tipo)
        obrigatorios = set(contrato.payload.get("required") or [])
        propriedades = contrato.payload.get("properties") or {}
        partes.append(f'class Payload{nome}(TypedDict, total=False):')
        partes.append(f'    """Payload de `{contrato.tipo}` v{contrato.versao}."""')
        if not propriedades:
            partes.append("    # Sem campos: o envelope ja diz tudo o que este evento diz.")
        for campo, corpo in propriedades.items():
            marca = "" if campo in obrigatorios else "  # opcional"
            partes.append(f"    {campo}: {_py(corpo)}{marca}")
        partes.append("")
        partes.append("")

    partes.append("#: Todos os contratos, por tipo. Lista fechada.")
    partes.append("CATALOGO: dict[str, dict[str, object]] = {")
    for contrato in contratos:
        obrigatorios = sorted(contrato.payload.get("required") or [])
        permitidos = sorted((contrato.payload.get("properties") or {}))
        partes.append(f'    "{contrato.tipo}": {{')
        partes.append(f'        "versao": {contrato.versao},')
        partes.append(f'        "obrigatorios": {obrigatorios!r},')
        partes.append(f'        "permitidos": {permitidos!r},')
        partes.append("    },")
    partes.append("}")
    partes.append("")
    return "\n".join(partes)


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
