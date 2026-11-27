"""Interface de linha de comandos da `borda` (KAM-077).

    python -m borda rtt-medir --origem luanda-1 --alvo host=<endereco>:443 \\
                              [--alvo graph=graph.facebook.com:443] --saida amostras.jsonl
                              [--duracao 86400] [--intervalo 60]
    python -m borda rtt-relatorio amostras.jsonl [...] [--saida RTT.md]
                              [--janela-minima 86400] [--lacuna-maxima 600]
    python -m borda rtt-verificar RTT.md amostras.jsonl [...]
    python -m borda firewall [--root .] [--porta-wireguard 51820]

Codigo de saida 0 = conforme, 1 = recusa ou achados, 2 = erro de utilizacao ou
de leitura. A distincao entre 1 e 2 e a do `env_lint`: amostras que nao se leem
nao podem parecer amostras que nao chegam.

**Nao entra em nenhum gate.** A sonda corre num *host* que ainda nao existe, e
a verificacao das regras corre pela suite (`tools/borda/tests`), que o gate 4
descobre sozinho. Ligar um *job* novo era alterar o *ruleset* de `main`, que e
decisao do fundador.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import firewall, rtt


def _raiz(argumentos) -> Path:
    return (argumentos.root or Path(__file__).resolve().parents[2]).resolve()


def _rtt_medir(argumentos) -> int:
    try:
        alvos = [rtt.Alvo.ler(texto) for texto in argumentos.alvo]
        escritas = rtt.medir(
            argumentos.origem,
            alvos,
            Path(argumentos.saida),
            duracao_s=argumentos.duracao,
            intervalo_s=argumentos.intervalo,
        )
    except ValueError as erro:
        print(f"borda: {erro}", file=sys.stderr)
        return 2
    print(f"borda: {escritas} amostras em {argumentos.saida}")
    return 0


def _rtt_relatorio(argumentos) -> int:
    try:
        texto = rtt.relatorio(
            [Path(caminho) for caminho in argumentos.amostras],
            janela_minima_s=argumentos.janela_minima,
            lacuna_maxima_s=argumentos.lacuna_maxima,
        )
    except (rtt.AmostraInvalida, OSError, UnicodeDecodeError) as erro:
        print(f"borda: {erro}", file=sys.stderr)
        return 2
    except rtt.Recusa as recusa:
        print(f"borda: relatorio recusado — {recusa}", file=sys.stderr)
        return 1
    if argumentos.saida:
        Path(argumentos.saida).write_text(texto, encoding="utf-8", newline="\n")
        print(f"borda: relatorio em {argumentos.saida}")
    else:
        sys.stdout.write(texto)
    return 0


def _rtt_verificar(argumentos) -> int:
    try:
        texto = Path(argumentos.relatorio).read_text(encoding="utf-8")
        problemas = rtt.verificar(texto, [Path(caminho) for caminho in argumentos.amostras])
    except (rtt.AmostraInvalida, OSError, UnicodeDecodeError) as erro:
        print(f"borda: {erro}", file=sys.stderr)
        return 2
    for problema in problemas:
        print(f"borda: {problema}", file=sys.stderr)
    if problemas:
        return 1
    print(f"borda: a tabela bate com {len(argumentos.amostras)} ficheiro(s) de amostras")
    return 0


def _firewall(argumentos) -> int:
    try:
        regras = firewall.do_modelo(_raiz(argumentos), argumentos.porta_wireguard)
    except (firewall.RegrasAusentes, OSError) as erro:
        print(f"borda: {erro}", file=sys.stderr)
        return 2
    achados = firewall.verificar(regras, argumentos.porta_wireguard)
    print(f"borda: {len(regras.splitlines())} linhas de regras lidas de {firewall.MODELO}")
    for achado in achados:
        print(f"borda: {achado}", file=sys.stderr)
    print(f"borda: {len(achados)} achados", file=sys.stderr if achados else sys.stdout)
    return 1 if achados else 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="borda", description=__doc__.splitlines()[0])
    sub = analisador.add_subparsers(dest="comando", required=True)

    medir = sub.add_parser("rtt-medir", help="mede o RTT por handshake TCP, uma ronda por intervalo")
    medir.add_argument("--origem", required=True, help="etiqueta da sonda, ex. luanda-1")
    medir.add_argument("--alvo", action="append", required=True, help="nome=endereco:porta (repetivel)")
    medir.add_argument("--saida", required=True, help="ficheiro JSON Lines (acrescenta)")
    medir.add_argument("--duracao", type=int, default=rtt.JANELA_MINIMA_S, help="segundos (24 h)")
    medir.add_argument("--intervalo", type=int, default=rtt.INTERVALO_S, help="segundos entre rondas")
    medir.set_defaults(funcao=_rtt_medir)

    relatorio = sub.add_parser("rtt-relatorio", help="a tabela p50/p95, ou a recusa")
    relatorio.add_argument("amostras", nargs="+")
    relatorio.add_argument("--saida")
    relatorio.add_argument("--janela-minima", type=int, default=rtt.JANELA_MINIMA_S)
    relatorio.add_argument("--lacuna-maxima", type=int, default=rtt.LACUNA_MAXIMA_S)
    relatorio.set_defaults(funcao=_rtt_relatorio)

    verificar = sub.add_parser("rtt-verificar", help="recalcula a tabela a partir das amostras")
    verificar.add_argument("relatorio")
    verificar.add_argument("amostras", nargs="+")
    verificar.set_defaults(funcao=_rtt_verificar)

    regras = sub.add_parser("firewall", help="verifica as regras nftables do host-base")
    regras.add_argument("--root", type=Path)
    regras.add_argument("--porta-wireguard", type=int, default=51820)
    regras.set_defaults(funcao=_firewall)

    argumentos = analisador.parse_args(argv)
    if getattr(argumentos, "intervalo", 1) <= 0 or getattr(argumentos, "duracao", 1) <= 0:
        print("borda: --intervalo e --duracao tem de ser positivos", file=sys.stderr)
        return 2
    return argumentos.funcao(argumentos)
