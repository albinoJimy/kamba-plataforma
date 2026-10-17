"""Um exemplo valido por contrato, validado contra o proprio contrato.

E a verificacao mais barata que existe e a que apanha o erro mais comum: um
schema que ninguem conseguiu satisfazer. Um `required` esquecido, um `const`
com o tipo errado, um `enum` sem o valor que o produtor vai usar — nada disso
aparece a ler o schema, e tudo aparece a tentar escrever um exemplo.

Usa o `jsonschema` (4.26.0, ja fixado em `tools/requirements/tools.txt` com
hashes). E a unica das quatro verificacoes que precisa de uma biblioteca: as
outras tres leem JSON e comparam.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from contract_diff import catalogo


@dataclasses.dataclass(frozen=True)
class Achado:
    ficheiro: str
    porque: str

    def __str__(self) -> str:
        return f"{self.ficheiro}: {self.porque}"


def validar(raiz: Path) -> list[Achado]:
    """Cada contrato tem exemplo, e o exemplo valida contra ele."""
    import jsonschema

    achados: list[Achado] = []
    for contrato in catalogo.todos(raiz):
        caminho = catalogo.exemplo_de(contrato)
        if not caminho.is_file():
            achados.append(
                Achado(
                    contrato.relativo,
                    "nao tem exemplo. Um schema que ninguem conseguiu satisfazer "
                    "passa despercebido ate o primeiro produtor tentar emitir",
                )
            )
            continue
        relativo = caminho.relative_to(raiz).as_posix()
        try:
            exemplo = json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError as erro:
            achados.append(Achado(relativo, f"JSON invalido — {erro}"))
            continue
        try:
            jsonschema.validate(exemplo, contrato.documento)
        except jsonschema.ValidationError as erro:
            caminho_do_erro = "/".join(str(p) for p in erro.absolute_path) or "(raiz)"
            achados.append(Achado(relativo, f"{caminho_do_erro}: {erro.message}"))
        except jsonschema.SchemaError as erro:
            achados.append(
                Achado(contrato.relativo, f"o schema nao e um JSON Schema valido — {erro.message}")
            )
    return achados


def coerencia(raiz: Path) -> list[Achado]:
    """O exemplo diz o mesmo que o caminho e o catalogo dizem.

    Validar contra o schema **nao** chega: o `tipo` e a `versao` sao `const` no
    schema, pelo que um exemplo de `order.paid` guardado na pasta do
    `order.created` falharia — mas um exemplo cujo `agregado.tipo` nao bata com
    o do catalogo passa, e um cuja `classe_pii` seja mais permissiva do que a
    do §5 tambem. Estas sao as duas que o schema sozinho nao apanha.
    """
    achados: list[Achado] = []
    for contrato in catalogo.todos(raiz):
        caminho = catalogo.exemplo_de(contrato)
        if not caminho.is_file():
            continue
        relativo = caminho.relative_to(raiz).as_posix()
        try:
            exemplo = json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError:
            continue  # ja e achado em `validar`
        if not isinstance(exemplo, dict):
            continue
        if exemplo.get("tipo") != contrato.tipo:
            achados.append(
                Achado(relativo, f"o tipo e {exemplo.get('tipo')!r} e a pasta diz "
                                 f"{contrato.tipo!r}")
            )
        if exemplo.get("versao") != contrato.versao:
            achados.append(
                Achado(relativo, f"a versao e {exemplo.get('versao')!r} e o nome do "
                                 f"ficheiro diz {contrato.versao}")
            )
        if exemplo.get("classe_pii") == "P2":
            achados.append(
                Achado(relativo, "classe_pii P2: dado pessoal directo e proibido em "
                                 "evento (§7.1), e nenhum exemplo o pode normalizar")
            )
    return achados
