"""`python -m gate_piloto` — o gerador do pacote de evidência do gate do Piloto.

    python -m gate_piloto pacote --registo R [--resumo J] [--data D] [--saida F | --check F]

Sem `--saida` nem `--check`, escreve o pacote no `stdout`.

## Os códigos de saída

    0   escrito, ou `--check` conforme
    1   `--check`: o ficheiro versionado já não é o que o gerador escreve
    2   o Registo, o resumo ou o manifesto não servem

O 2 separa-se do 1 pela lição do KAM-134: uma entrada que não se lê não pode
sair indistinguível de um pacote desactualizado.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import entradas, pacote, registo, regras

SAIDA_CONFORME = 0
SAIDA_DIVERGE = 1
SAIDA_ERRO = 2

#: A forma do manifesto do KAM-109 (`tools/piloto/exportacao.py`), e o ficheiro
#: que ele tem de congelar para que H1, H6, H8 e H9 se possam ler.
FORMATO_DO_MANIFESTO = "kamba-piloto-congelado/1"
EXPORTACAO_DO_PILOTO = "piloto_export.json"


def _manifesto_nao_serve(dados: object) -> str | None:
    """O que falta a um manifesto que está na árvore; `None` se serve."""
    if not isinstance(dados, dict) or dados.get("formato") != FORMATO_DO_MANIFESTO:
        return f"não tem o formato {FORMATO_DO_MANIFESTO}"
    ficheiros = dados.get("ficheiros")
    nomes = {f.get("nome") for f in ficheiros if isinstance(f, dict)} if isinstance(ficheiros, list) else set()
    if EXPORTACAO_DO_PILOTO not in nomes:
        return f"não congela o {EXPORTACAO_DO_PILOTO}"
    return None


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
    # O protocolo do Piloto (§10) arquiva o conjunto fora do repositório, e então
    # o *hash* confere-se à mão. Quando o manifesto está na árvore, confere-se
    # aqui: o *hash*, a forma, e que congela a exportação do Piloto.
    if efectivo.manifesto is not None:
        ficheiro = raiz / efectivo.manifesto
        if ficheiro.is_file():
            bruto = ficheiro.read_bytes()
            real = hashlib.sha256(bruto).hexdigest()
            if real != efectivo.manifesto_sha256:
                print(
                    f"ERRO: {efectivo.manifesto}: o SHA-256 é {real}, e o resumo diz "
                    f"{efectivo.manifesto_sha256}",
                    file=sys.stderr,
                )
                return SAIDA_ERRO
            try:
                defeito = _manifesto_nao_serve(json.loads(bruto.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError) as erro:
                defeito = f"não é JSON ({erro})"
            if defeito:
                print(f"ERRO: {efectivo.manifesto}: {defeito}", file=sys.stderr)
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
