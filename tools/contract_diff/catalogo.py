"""Onde vivem os contratos, e como se leem.

Um sitio so para o caminho e para a forma do nome: quatro verificacoes e o
gerador de tipos leem daqui, e um `glob` repetido cinco vezes diverge na que se
esquecer do `v<N>`.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

#: A pasta dos contratos, relativa a raiz do repositorio.
#:
#: `contratos/eventos/` e **nao** `packages/contracts/eventos/`: e o caminho
#: que o `docs/tecnica/06` §4, o `ci/canon-lint.yaml`, os blocos do KAM-055 e
#: do KAM-092, o `docs/eventos.md` e as migracoes usam. O bloco do KAM-007
#: dizia o outro; alinhou-se o bloco, que era um sitio contra oito.
PASTA = Path("contratos") / "eventos"

#: `v<N>.schema.json`, com N sem zeros a esquerda. A mesma forma que o
#: `canon_lint` exige — e o mesmo motivo: o numero no nome **e** a versao, e um
#: `v01` seria uma segunda forma de escrever a mesma coisa.
NOME_DO_FICHEIRO = re.compile(r"^v([1-9][0-9]*)\.schema\.json$")

#: O nome do exemplo que acompanha cada contrato.
NOME_DO_EXEMPLO = "exemplo.json"

#: A gramatica de um tipo de evento. A mesma do `lerEnvelope` e do `canon_lint`.
TIPO_DE_EVENTO = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class ContratoInvalidoError(ValueError):
    """Um ficheiro na pasta dos contratos que nao e um contrato."""


@dataclasses.dataclass(frozen=True)
class Contrato:
    """Um `v<N>.schema.json` lido, com o que o nome do caminho promete."""

    tipo: str
    versao: int
    caminho: Path
    #: O caminho relativo a raiz, em forma POSIX. E o que aparece nas mensagens
    #: e o que o `git show` recebe — nunca o caminho do anfitriao.
    relativo: str
    documento: dict

    @property
    def payload(self) -> dict:
        corpo = (self.documento.get("properties") or {}).get("payload")
        return corpo if isinstance(corpo, dict) else {}


def ler(caminho: Path, raiz: Path) -> Contrato:
    """Le um contrato e confere que o nome do caminho diz a verdade."""
    achado = NOME_DO_FICHEIRO.match(caminho.name)
    if achado is None:
        raise ContratoInvalidoError(
            f"{caminho.name}: o nome tem de ser v<N>.schema.json, com N sem zeros a esquerda"
        )
    tipo = caminho.parent.name
    if not TIPO_DE_EVENTO.match(tipo):
        raise ContratoInvalidoError(
            f"{tipo}: a pasta de um contrato e o tipo do evento, na forma familia.verbo"
        )
    try:
        documento = json.loads(caminho.read_text(encoding="utf-8"))
    except ValueError as erro:
        raise ContratoInvalidoError(f"{caminho}: JSON invalido — {erro}") from erro
    if not isinstance(documento, dict):
        raise ContratoInvalidoError(f"{caminho}: a raiz de um schema e um objecto")
    return Contrato(
        tipo=tipo,
        versao=int(achado.group(1)),
        caminho=caminho,
        relativo=caminho.relative_to(raiz).as_posix(),
        documento=documento,
    )


def todos(raiz: Path) -> list[Contrato]:
    """Todos os contratos, por tipo e depois por versao."""
    pasta = raiz / PASTA
    if not pasta.is_dir():
        return []
    contratos = [
        ler(caminho, raiz)
        for caminho in sorted(pasta.glob("*/*.json"))
        if caminho.name != NOME_DO_EXEMPLO
    ]
    return sorted(contratos, key=lambda c: (c.tipo, c.versao))


def exemplo_de(contrato: Contrato) -> Path:
    """O exemplo que acompanha um contrato. Pode nao existir — quem chama ve."""
    return contrato.caminho.parent / NOME_DO_EXEMPLO
