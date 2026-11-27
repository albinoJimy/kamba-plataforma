"""`python -m gate_piloto` — o gerador do pacote de evidência do gate do Piloto.

    python -m gate_piloto pacote --registo R [--resumo J] [--data D] [--saida F | --check F]

Sem `--saida` nem `--check`, escreve o pacote no `stdout`.

## Os códigos de saída

    0   escrito, ou `--check` conforme
    1   `--check`: o ficheiro versionado já não é o que o gerador escreve
    2   o Registo ou o resumo não servem

O 2 separa-se do 1 pela lição do KAM-134: uma entrada que não se lê não pode
sair indistinguível de um pacote desactualizado.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from . import entradas, pacote, registo, regras

SAIDA_CONFORME = 0
SAIDA_DIVERGE = 1
SAIDA_ERRO = 2


def _raiz_por_omissao() -> Path:
    """A raiz do repositório, a subir até ao `pnpm-workspace.yaml` (receita do `gate_fase0`)."""
    actual = Path(__file__).resolve().parent
    for candidato in [actual, *actual.parents]:
        if (candidato / "pnpm-workspace.yaml").is_file():
            return candidato
    return Path.cwd()


def _relativo(caminho: Path, raiz: Path) -> str:
    try:
        return caminho.resolve().relative_to(raiz.resolve()).as_posix()
    except ValueError:
        return caminho.name


def _analisador() -> argparse.ArgumentParser:
    a = argparse.ArgumentParser(
        prog="python -m gate_piloto",
        description="pacote de evidência do gate do Piloto (KAM-110); a decisão é humana",
    )
    a.add_argument("--root", type=Path, default=None, help="a raiz do repositório")
    sub = a.add_subparsers(dest="comando", required=True)
    p = sub.add_parser("pacote", help="escreve o Gate_Piloto.md")
    p.add_argument("--registo", type=Path, required=True, help="o Registo_Hipoteses.md")
    p.add_argument("--resumo", type=Path, default=None, help="o resumo do piloto (JSON)")
    p.add_argument("--data", default="por preencher", help="a data do cabeçalho")
    destino = p.add_mutually_exclusive_group()
    destino.add_argument("--saida", type=Path, default=None, help="escreve aqui")
    destino.add_argument("--check", type=Path, default=None, help="compara com este ficheiro")
    return a


def principal(argv: list[str] | None = None) -> int:
    args = _analisador().parse_args(argv)
    raiz = args.root or _raiz_por_omissao()
    try:
        linhas = registo.ler(args.registo)
        resumo = entradas.ler(args.resumo) if args.resumo else None
    except (registo.RegistoIlegivel, entradas.EntradaInvalida) as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return SAIDA_ERRO

    efectivo = resumo or entradas.VAZIO
    conferido = False
    # A exportação pode estar arquivada fora da árvore; quando está dentro, o
    # *hash* confere-se, porque um *hash* que não é o do ficheiro não congela nada.
    if efectivo.exportacao is not None:
        ficheiro = raiz / efectivo.exportacao
        if ficheiro.is_file():
            real = hashlib.sha256(ficheiro.read_bytes()).hexdigest()
            if real != efectivo.exportacao_sha256:
                print(
                    f"ERRO: {efectivo.exportacao}: o SHA-256 é {real}, e o resumo diz "
                    f"{efectivo.exportacao_sha256}",
                    file=sys.stderr,
                )
                return SAIDA_ERRO
            conferido = True
    existe = regras.resolvedor(args.registo.resolve().parent, raiz)
    estados = regras.estados(linhas, efectivo, existe)
    texto = pacote.escrever(
        linhas,
        estados,
        regras.carta(estados, efectivo, raiz),
        regras.matriz(estados, efectivo),
        regras.paragem_total(efectivo),
        resumo,
        _relativo(args.registo, raiz),
        _relativo(args.resumo, raiz) if args.resumo else None,
        args.data,
        conferido,
    )

    if args.check is not None:
        try:
            actual = args.check.read_text(encoding="utf-8")
        except OSError as erro:
            print(f"ERRO: {erro}", file=sys.stderr)
            return SAIDA_ERRO
        if actual != texto:
            print(f"{args.check}: difere do que o gerador escreve; regenera-o", file=sys.stderr)
            return SAIDA_DIVERGE
        return SAIDA_CONFORME
    if args.saida is not None:
        args.saida.write_bytes(texto.encode("utf-8"))
        return SAIDA_CONFORME
    # Em bytes quando se pode: a consola do Windows não é UTF-8 por omissão, e
    # o pacote tem «≥» e «—».
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(texto.encode("utf-8"))
        buffer.flush()
    else:
        sys.stdout.write(texto)
    return SAIDA_CONFORME
