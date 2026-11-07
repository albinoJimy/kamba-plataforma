"""Interface de linha de comando do inventario de subprocessadores (KAM-069).

    python -m subprocessadores [--root .]            escreve os dois documentos
    python -m subprocessadores --check [--root .]    verifica que estao em dia
    python -m subprocessadores --versao [--root .]   imprime a versao do mapa

Codigo de saida 0 = conforme, 1 = divergencia, 2 = inventario invalido. A
distincao importa, e e a mesma do `dict_export`: um inventario que nao se le nao
pode parecer um repositorio limpo.

O `--versao` existe para o *gate* de go-live: o criterio 8 exige «a referencia
do mapa de tratamentos», e quem activa um tenant tem de a poder obter sem abrir
o documento e copiar a mao.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import documentos
from .inventario import CAMINHO as CAMINHO_DO_INVENTARIO
from .inventario import InventarioInvalido, ler


def _utf8() -> None:
    """As mensagens levam `§` e `—`, que a consola cp1252 nao tem.

    Sem isto, a primeira divergencia em Windows era um `UnicodeEncodeError` — o
    verificador rebentava em vez de dizer o que encontrou. E a mesma correccao
    que o `canon_lint.cli` ja faz, e pela mesma razao.
    """
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")


def _escrever(caminho: Path, conteudo: str) -> None:
    """Escreve com `\\n`, sempre.

    `newline=""` e nao a omissao: nesta maquina o Python traduz `\\n` para
    `\\r\\n` ao escrever, e o `.gitattributes` normaliza no *commit* — pelo que o
    ficheiro no disco e o ficheiro no indice ficavam diferentes e o `--check`
    dizia «divergente» sobre conteudo identico.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as ficheiro:
        ficheiro.write(conteudo)


def main(argv: list[str] | None = None) -> int:
    _utf8()
    parser = argparse.ArgumentParser(
        prog="subprocessadores",
        description=(
            "Gera a lista publica e o mapa de tratamentos do inventario de "
            "subprocessadores (KAM-069)."
        ),
    )
    parser.add_argument("--root", default=".", help="raiz do repositorio")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--check",
        action="store_true",
        help="nao escreve; falha se o que esta no disco divergir",
    )
    grupo.add_argument(
        "--versao",
        action="store_true",
        help="imprime a versao do mapa e sai",
    )
    args = parser.parse_args(argv)
    raiz = Path(args.root).resolve()

    try:
        inventario = ler(raiz)
    except InventarioInvalido as erro:
        print(f"subprocessadores: inventario invalido — {erro}", file=sys.stderr)
        return 2

    # **Os destinos ficam vazios, e isso nao e um atalho.** A tabela
    # `platform.tenant_destinations` nao se le daqui: esta ferramenta corre no
    # *gate* 2, sem base de dados — e e a mesma razao pela qual o `kamba_yaml`
    # existe. O documento gerado **diz** quantas linhas leu, pelo que um mapa
    # gerado sem a tabela nao se confunde com um gerado com ela.
    #
    # Quem tiver a base a mao gera com ela chamando `documentos.mapa_de_tratamentos`
    # com as linhas; o que corre no CI e esta forma, e a versao muda quando as
    # linhas aparecerem.
    destinos: tuple[dict, ...] = ()
    versao = inventario.versao_do_mapa(destinos)

    if args.versao:
        print(versao)
        return 0

    saidas = {
        documentos.CAMINHO_PUBLICO: documentos.lista_publica(inventario, versao),
        documentos.CAMINHO_MAPA: documentos.mapa_de_tratamentos(
            inventario, versao, destinos
        ),
    }

    if not args.check:
        for relativo, conteudo in saidas.items():
            _escrever(raiz / relativo, conteudo)
            print(f"subprocessadores: {relativo} escrito (versao {versao})")
        return 0

    divergentes = []
    for relativo, conteudo in saidas.items():
        caminho = raiz / relativo
        try:
            actual = caminho.read_text(encoding="utf-8")
        except OSError:
            divergentes.append(f"{relativo}: nao existe")
            continue
        if actual.replace("\r\n", "\n") != conteudo:
            divergentes.append(f"{relativo}: difere do inventario")
    if divergentes:
        print(
            f"subprocessadores: os documentos gerados nao estao em dia com "
            f"{CAMINHO_DO_INVENTARIO}:",
            file=sys.stderr,
        )
        for problema in divergentes:
            print(f"  - {problema}", file=sys.stderr)
        print(
            "  Corra `python -m subprocessadores --root .` e versione o "
            "resultado.",
            file=sys.stderr,
        )
        return 1
    print(
        f"subprocessadores: conforme — {len(inventario.subprocessadores)} "
        f"subprocessadores, {len(inventario.nao_autorizados)} nao "
        f"autorizado(s), "
        f"versao {versao}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
