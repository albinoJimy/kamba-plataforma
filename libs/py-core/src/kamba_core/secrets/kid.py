"""O `kid` de uma versao de segredo, lido do proprio valor (KAM-205).

Espelho de `packages/core-ts/src/secrets/kid.ts`: as duas portas tem de
significar o mesmo (`port.py`). Um valor `<kid>:<base64 de 32 octetos>` da o seu
`kid`, que vai com ele quando passa de actual a anterior; so um valor sem essa
forma recebe o rotulo posicional. A forma e estrita, para que uma senha
`utilizador:segredo` nao de um pedaco dela como `kid`.

Decisao do fundador, 2026-11-18: o `kid` estavel vale so para as versoes que o
trazem no valor (os segredos `kid: true` do inventario); os `kid: false` ficam
com o rotulo posicional, sem um `kid` tirado de um resumo do valor.

**Nenhum erro deste modulo leva o valor.**
"""

from __future__ import annotations

import base64
import binascii
import re

#: Os rotulos posicionais que um provedor de ambiente da a um valor sem `kid`.
ROTULOS_POSICIONAIS = ("actual", "anterior")

#: Octetos da chave que segue o `kid`.
OCTETOS_DA_CHAVE_VERSIONADA = 32

_KID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


class KidRepetidoNoCofreError(Exception):
    """Duas versoes vivas com o mesmo `kid`: tudo o que o guarda fica ambiguo."""

    def __init__(self, ref: str, kid: str) -> None:
        super().__init__(f"a versao actual e a anterior de {ref} tem o mesmo kid {kid}")
        self.ref = ref
        self.kid = kid


def separar_kid(valor: str) -> tuple[str, str] | None:
    """Separa `<kid>:<base64>`; `None` quando o valor nao tem essa forma."""
    kid, sep, chave = valor.partition(":")
    if sep == "" or not _KID.match(kid) or kid in ROTULOS_POSICIONAIS:
        return None
    if not _BASE64.match(chave) or len(chave) % 4 != 0:
        return None
    try:
        octetos = base64.b64decode(chave, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(octetos) != OCTETOS_DA_CHAVE_VERSIONADA:
        return None
    return kid, chave


def kid_do_valor(valor: str) -> str | None:
    """O `kid` que o valor traz, ou `None`."""
    separado = separar_kid(valor)
    return None if separado is None else separado[0]


def kids_das_versoes(ref: str, actual: str, anterior: str | None) -> tuple[str, ...]:
    """Os identificadores de `[actual, anterior]`, pela ordem do contrato."""
    primeiro = kid_do_valor(actual) or ROTULOS_POSICIONAIS[0]
    if anterior is None:
        return (primeiro,)
    segundo = kid_do_valor(anterior) or ROTULOS_POSICIONAIS[1]
    if segundo == primeiro:
        raise KidRepetidoNoCofreError(ref, segundo)
    return (primeiro, segundo)


__all__ = [
    "OCTETOS_DA_CHAVE_VERSIONADA",
    "ROTULOS_POSICIONAIS",
    "KidRepetidoNoCofreError",
    "kid_do_valor",
    "kids_das_versoes",
    "separar_kid",
]
