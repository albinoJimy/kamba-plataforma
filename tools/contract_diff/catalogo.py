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

#: O nome do exemplo que acompanha a **v1** de cada contrato.
NOME_DO_EXEMPLO = "exemplo.json"

#: E o das versoes seguintes: `exemplo.v2.json`, `exemplo.v3.json` (KAM-159).
#:
#: Havia **um** exemplo por pasta, validado contra **todos** os contratos dela.
#: Enquanto so houve `v1` isso bastou; no dia em que nasceu a `v2`, o mesmo
#: ficheiro tinha de dizer `versao: 1` e `versao: 2` ao mesmo tempo. Nao e um
#: detalhe de arrumacao: um exemplo e a unica prova executavel de que um
#: contrato descreve um evento que alguem consegue escrever, e um contrato sem
#: exemplo proprio nunca foi verificado.
NOME_DO_EXEMPLO_POR_VERSAO = re.compile(r"^exemplo\.v([1-9][0-9]*)\.json$")


def nome_do_exemplo(versao: int) -> str:
    """O nome do exemplo da versao `n`. A `v1` mantem o nome historico."""
    return NOME_DO_EXEMPLO if versao == 1 else f"exemplo.v{versao}.json"

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
        and not NOME_DO_EXEMPLO_POR_VERSAO.match(caminho.name)
    ]
    return sorted(contratos, key=lambda c: (c.tipo, c.versao))


def exemplo_de(contrato: Contrato) -> Path:
    """O exemplo que acompanha um contrato. Pode nao existir — quem chama ve.

    **Por versao** desde o KAM-159: a `v1` fica com o nome historico
    (`exemplo.json`) e as seguintes levam a versao no nome. Sem isto, o mesmo
    ficheiro tinha de declarar duas versoes ao mesmo tempo.
    """
    return contrato.caminho.parent / nome_do_exemplo(contrato.versao)
