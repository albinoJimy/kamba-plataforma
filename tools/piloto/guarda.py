"""A guarda de dados pessoais do relatorio e da folha de auditoria (KAM-109).

Duas formas, e as duas recusam em vez de limpar: um texto que as tem nao se
escreve.

* **Telefone angolano**, movel (`9XXXXXXXX`) ou fixo (`2XXXXXXXX`), com ou sem
  indicativo (`+244`, `00244`, `244`), com qualquer agrupamento de espacos,
  pontos, hifens ou parenteses, e colado a letras (`tel923…`). Os separadores
  tiram-se **antes** de procurar, e e isso que apanha o `923 45 67 89`.
* **`uuid`** — um `tenant_id` ou um `contact_id`.

Os limites sao de digito, e nao de letra: um `sha256` em hex pode ter nove
digitos seguidos entre letras, e casa. Por isso quem escreve um *hash* conhecido
no texto passa-o em `permitidos`, e ele sai da procura **pelo valor exacto** —
um telefone noutro sitio do texto continua a ser apanhado.
"""

from __future__ import annotations

import re
from typing import Final, Iterable

_SEPARADORES: Final = re.compile(r"[ .()\- ]")
_TELEFONE: Final = re.compile(r"(?<!\d)(?:00244|\+244|244)?[29]\d{8}(?!\d)")
_UUID: Final = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def tem_telefone(texto: str) -> bool:
    return bool(_TELEFONE.search(_SEPARADORES.sub("", texto))) or "+244" in texto


def tem_uuid(texto: str) -> bool:
    return bool(_UUID.search(texto))


def achados(texto: str, permitidos: Iterable[str] = ()) -> list[str]:
    for valor in permitidos:
        texto = texto.replace(valor, "")
    saida = []
    if tem_uuid(texto):
        saida.append("uuid")
    if tem_telefone(texto):
        saida.append("forma de telefone")
    return saida
