"""Interface de linha de comando do `supply_chain` (KAM-067).

    python -m supply_chain check     [--root .]   todas as verificacoes
    python -m supply_chain imagens   [--root .]   digests, inventario e cosign
    python -m supply_chain runtime   [--root .]   instalacao e so-de-leitura
    python -m supply_chain egress    [--root .]   listas de saida por servico
    python -m supply_chain licencas  [--root .]   registo de licencas por versao
    python -m supply_chain renovate  [--root .]   quarentena de versoes novas
    python -m supply_chain ci        [--root .]   chaves estaticas nos workflows
    python -m supply_chain canario   [--root .]   prova de que cada uma morde

Codigo de saida 0 = conforme, 1 = achados, 2 = erro de configuracao. A distincao
importa: um ficheiro de politica ilegivel nao pode parecer um repositorio limpo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import canario, ci_chaves, cosign, egress, imagens, licencas, renovate, runtime
from .base import Achado, ConfiguracaoInvalida

VERIFICACOES = ("imagens", "runtime", "egress", "licencas", "renovate", "ci")


def executar(nome: str, raiz: Path) -> tuple[list[Achado], str]:
    """Corre uma verificacao. Devolve (achados, linha de resumo)."""
    if nome == "imagens":
        achados, resumo = imagens.verificar(raiz)
        achados_cosign, resumo_cosign = cosign.verificar(resumo["inventario"])
        estados = resumo["cosign"]
        return achados + achados_cosign, (
            f"{resumo['referencias']} referencia(s) a {resumo['imagens']} imagem(ns), "
            f"todas por digest; cosign: {resumo_cosign['verificadas']} verificada(s), "
            f"{estados[imagens.COSIGN_NA]} n/a, "
            f"{estados[imagens.COSIGN_POR_APURAR]} com assinatura POR APURAR"
        )
    if nome == "runtime":
        achados, resumo = runtime.verificar(raiz)
        return achados, (
            f"{resumo['dockerfiles']} Dockerfile(s), {resumo['servicos']} servico(s) de "
            f"compose so de leitura, {resumo['instalacoes_de_build']} instalacao(oes) "
            "de build, todas do lockfile; nenhuma em runtime"
        )
    if nome == "egress":
        achados, resumo = egress.verificar(raiz)
        return achados, (
            f"{resumo['servicos']} servico(s) com lista de saidas, negado por omissao; "
            f"{resumo['destinos']} destino(s) aprovado(s)"
        )
    if nome == "licencas":
        achados, resumo = licencas.verificar(raiz)
        estados = ", ".join(f"{n} {e}" for e, n in resumo["estados"].items() if n)
        return achados, f"{resumo['componentes']} componente(s) registado(s) ({estados})"
    if nome == "renovate":
        achados, resumo = renovate.verificar(raiz)
        return achados, (
            f"quarentena de {resumo['quarentena_dias']} dia(s), sem automerge "
            "(a configuracao; que o Renovate a aplique nao se ve daqui)"
        )
    if nome == "ci":
        achados, resumo = ci_chaves.verificar(raiz)
        return achados, f"{resumo['ficheiros']} ficheiro(s) de workflow sem chaves estaticas"
    raise ValueError(nome)


def executar_todas(raiz: Path) -> list[Achado]:
    """Todas as verificacoes, sem imprimir. E o que o canario usa."""
    achados: list[Achado] = []
    for nome in VERIFICACOES:
        achados += executar(nome, raiz)[0]
    return achados


def _relatar(nome: str, raiz: Path) -> int:
    achados, resumo = executar(nome, raiz)
    if not achados:
        print(f"supply_chain: {nome}: conforme — {resumo}")
        return 0
    print(f"supply_chain: {nome}: {len(achados)} achado(s)", file=sys.stderr)
    for achado in achados:
        print(f"  - {achado}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="supply_chain", description="Cadeia de abastecimento (KAM-067)"
    )
    analisador.add_argument("--root", type=Path, default=None, help="raiz do repositorio")
    sub = analisador.add_subparsers(dest="comando", required=True)
    sub.add_parser("check", help="todas as verificacoes")
    for nome in VERIFICACOES:
        sub.add_parser(nome)
    sub.add_parser("canario", help="prova por mutacao de que cada verificacao falha")

    argumentos = analisador.parse_args(argv)
    raiz = (argumentos.root or Path(__file__).resolve().parents[2]).resolve()

    try:
        if argumentos.comando == "canario":
            return canario.main(raiz)
        nomes = VERIFICACOES if argumentos.comando == "check" else (argumentos.comando,)
        estado = 0
        for nome in nomes:
            estado = max(estado, _relatar(nome, raiz))
        return estado
    except ConfiguracaoInvalida as excepcao:
        print(f"supply_chain: erro de configuracao: {excepcao}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
