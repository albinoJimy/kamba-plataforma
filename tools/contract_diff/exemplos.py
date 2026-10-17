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

    **O que esta funcao verifica e o que o schema, por constucao, nao pode.**
    A primeira versao deste docstring prometia duas verificacoes que o codigo
    nao fazia — `agregado.tipo` contra o catalogo e `classe_pii` contra o §5 —
    e a revisao adversarial apanhou-o (achado M2). As duas foram feitas, mas
    no sitio certo: **no schema**, com `agregado.tipo` fixo em `const` e
    `classe_pii` limitada por `enum` a classe que o §5 da ao tipo. Um exemplo
    que as viole falha agora na validacao, que e mais forte do que falhar
    aqui, porque passa a valer tambem para o produtor.

    Vale a pena dizer o que isso apanhou no dia em que entrou: **vinte e sete
    dos trinta e oito exemplos** tinham `agregado.tipo: "order"` — o valor da
    primeira pasta, copiado — e estavam todos «validos» porque nada os lia.

    Fica aqui o que depende do **caminho do ficheiro**, que nenhum schema ve:
    o `tipo` da pasta e a `versao` do nome. E fica o P2, que o `enum` ja
    recusa, como segunda barreira com mensagem propria: a regra do §7.1 e a
    unica deste modulo cuja violacao e um incidente de privacidade, e uma
    mensagem de `jsonschema` sobre um `enum` nao a explica a ninguem.
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
