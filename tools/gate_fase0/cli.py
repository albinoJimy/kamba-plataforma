"""`python -m gate_fase0` — os instrumentos do gate da Fase 0 (KAM-108).

Seis subcomandos, e nenhum deles decide o veredicto:

    cenario    imprime o guião do operador, gerado do `cenario.py`
    consulta   imprime as consultas de leitura que dão os três elos de baixo
    traco      a cadeia mensagem -> pedido -> evento -> consumo, por identificadores
    ci         o estado dos gates do §4 numa execução de CI
    reuso      a métrica de reaproveitamento, com a proveniência verificada
    decisoes   as sete linhas do G0-7, com as três invariantes verificadas

## Os códigos de saída, e porque são três

    0   conforme
    1   há achados, ou a cadeia tem elos em falta
    2   a entrada ou a configuração não servem

O 2 separa-se do 1 de propósito, e é a lição do KAM-134 que este repositório já
pagou noutros *lints*: um `traceback` por uma entrada que falta sai
indistinguível de «o traço não fechou», e as duas conclusões são opostas — a
primeira é um erro de quem corre, a segunda é o resultado da demonstração.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import cenario as modulo_cenario
from . import consulta as modulo_consulta
from . import recolha as modulo_recolha
from . import traco as modulo_traco

SAIDA_CONFORME = 0
SAIDA_ACHADOS = 1
SAIDA_ERRO = 2


def _raiz_por_omissao() -> Path:
    """A raiz do repositório, a subir até ao `pnpm-workspace.yaml`.

    É a receita do `tools/meta-sim/src/cli.ts`, e pela razão que lá está escrita:
    um instrumento cujo significado muda com o `cwd` não é um instrumento. Aqui
    custa menos — `tools/gate_fase0/cli.py` está sempre a dois níveis da raiz —,
    mas procura-se o ficheiro em vez de contar pastas, porque contar pastas
    quebra no dia em que o pacote se mover.
    """
    actual = Path(__file__).resolve().parent
    for candidato in [actual, *actual.parents]:
        if (candidato / "pnpm-workspace.yaml").is_file():
            return candidato
    return Path.cwd()


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(
        prog="python -m gate_fase0",
        description="instrumentos do gate da Fase 0 (KAM-108); o veredicto é humano",
    )
    analisador.add_argument(
        "--root", type=Path, default=None, help="a raiz do repositório"
    )
    sub = analisador.add_subparsers(dest="comando", required=True)

    sub.add_parser("cenario", help="o guião do operador, gerado do cenário")
    sub.add_parser("consulta", help="as consultas de leitura dos três elos de baixo")

    p_traco = sub.add_parser("traco", help="a cadeia por identificadores")
    p_traco.add_argument(
        "entradas",
        type=Path,
        nargs="+",
        help="ficheiros JSON-lines: os *logs* e a saída das consultas",
    )
    p_traco.add_argument(
        "--json", action="store_true", help="devolve o traço em JSON em vez de texto"
    )

    p_ci = sub.add_parser("ci", help="o estado dos gates do §4 numa execução")
    p_ci.add_argument(
        "corrida",
        type=Path,
        help="saída de `gh run view <id> --json jobs,headSha,url,conclusion`",
    )

    p_reuso = sub.add_parser("reuso", help="a métrica de reaproveitamento")
    p_reuso.add_argument(
        "artefacto", type=Path, help="saída de `reuse_metric --json <caminho> medir`"
    )
    p_reuso.add_argument(
        "--ponta", default=None, help="a ponta que o artefacto tem de declarar"
    )

    p_dec = sub.add_parser("decisoes", help="as sete linhas do G0-7")
    p_dec.add_argument("--manifesto", type=Path, default=None)
    p_dec.add_argument(
        "--prefixo",
        default="",
        help="o que precede cada caminho, para a ligação resolver de onde a "
        "tabela for colada (`../../../` em `docs/tecnica/evidencia/validacao/`)",
    )

    return analisador


def principal(argv: list[str] | None = None) -> int:
    argumentos = _analisador().parse_args(argv)
    raiz = argumentos.root or _raiz_por_omissao()

    if argumentos.comando == "cenario":
        try:
            modulo_cenario.verificar()
        except modulo_cenario.CenarioIncoerente as excepcao:
            print(f"cenario: {excepcao}", file=sys.stderr)
            return SAIDA_ERRO
        print(modulo_cenario.como_markdown())
        return SAIDA_CONFORME

    if argumentos.comando == "consulta":
        try:
            modulo_consulta.verificar()
        except modulo_consulta.ProjeccaoProibida as excepcao:
            print(f"consulta: {excepcao}", file=sys.stderr)
            return SAIDA_ERRO
        print(modulo_consulta.como_texto())
        return SAIDA_CONFORME

    if argumentos.comando == "traco":
        for entrada in argumentos.entradas:
            if not entrada.is_file():
                print(f"traco: `{entrada}` não existe", file=sys.stderr)
                return SAIDA_ERRO
        try:
            cadeias, descartes = modulo_traco.tracar(argumentos.entradas)
            saida = (
                modulo_traco.como_json(cadeias, descartes)
                if argumentos.json
                else modulo_traco.como_texto(cadeias)
            )
        except modulo_traco.ConteudoRecusado as excepcao:
            print(f"traco: {excepcao}", file=sys.stderr)
            return SAIDA_ERRO
        except modulo_traco.EloEmFalta as excepcao:
            print(f"traco: {excepcao}", file=sys.stderr)
            return SAIDA_ERRO
        print(saida)
        incompletas = [cadeia for cadeia in cadeias if not cadeia.completa()]
        if incompletas or not cadeias:
            # **Código 1 e não 0, e não é pedantismo.** Uma cadeia incompleta é o
            # resultado da demonstração e tem de se ver no código de saída, senão
            # um `&& echo verde` num guião do operador diz verde sobre uma cadeia
            # que parou no evento.
            print(
                f"\n{len(incompletas)} de {len(cadeias)} cadeia(s) com elos em falta",
                file=sys.stderr,
            )
            return SAIDA_ACHADOS
        return SAIDA_CONFORME

    if argumentos.comando == "ci":
        if not argumentos.corrida.is_file():
            print(f"ci: `{argumentos.corrida}` não existe", file=sys.stderr)
            return SAIDA_ERRO
        try:
            estados, meta = modulo_recolha.ler_corrida(argumentos.corrida)
        except (modulo_recolha.RecolhaInvalida, ValueError) as excepcao:
            print(f"ci: {excepcao}", file=sys.stderr)
            return SAIDA_ERRO
        print(modulo_recolha.tabela_de_ci(estados, meta))
        vermelhos = [
            estado
            for estado in estados
            if estado.job is not None and estado.conclusao != "success" and estado.bloqueia
        ]
        return SAIDA_ACHADOS if vermelhos else SAIDA_CONFORME

    if argumentos.comando == "reuso":
        if not argumentos.artefacto.is_file():
            print(f"reuso: `{argumentos.artefacto}` não existe", file=sys.stderr)
            return SAIDA_ERRO
        try:
            documento = modulo_recolha.ler_reuso(argumentos.artefacto, argumentos.ponta)
            limiar = modulo_recolha.limiar_do_reuso(raiz)
        except (modulo_recolha.RecolhaInvalida, ValueError) as excepcao:
            print(f"reuso: {excepcao}", file=sys.stderr)
            return SAIDA_ERRO
        print(modulo_recolha.tabela_de_reuso(documento, limiar))
        return (
            SAIDA_CONFORME
            if float(documento["reuso_pct"]) >= limiar
            else SAIDA_ACHADOS
        )

    if argumentos.comando == "decisoes":
        try:
            linhas, achados = modulo_recolha.ler_decisoes(raiz, argumentos.manifesto)
        except (modulo_recolha.RecolhaInvalida, ValueError) as excepcao:
            print(f"decisoes: {excepcao}", file=sys.stderr)
            return SAIDA_ERRO
        print(modulo_recolha.tabela_de_decisoes(linhas, argumentos.prefixo))
        if achados:
            print("", file=sys.stderr)
            for achado in achados:
                print(f"decisoes: {achado}", file=sys.stderr)
            return SAIDA_ACHADOS
        confirmadas = sum(1 for linha in linhas if linha.estado == "confirmada")
        print(
            f"\n{len(linhas)} linha(s), {confirmadas} `confirmada`(s); "
            "as invariantes do manifesto passam"
        )
        return SAIDA_CONFORME

    return SAIDA_ERRO
