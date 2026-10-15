"""Interface de linha de comandos do `log_policy` (KAM-068).

    python -m log_policy lint     [--root .]              gate 2
    python -m log_policy canario  [--root .]              gate 2
    python -m log_policy fixtures --saida F               gera as 1 000 fixtures
    python -m log_policy conduzir F --saida L --contadores C [--ponte P]
    python -m log_policy iguais A B                       paridade byte a byte
    python -m log_policy x11 [--fixtures F] [--linhas-esperadas N]
                             [--nif-padrao R]... LOG...   gate 6 (`make x11`)
    python -m log_policy amostra PASTA --registo F        amostragem de `prod`

Codigo de saida 0 = limpo, 1 = achados, 2 = erro de utilizacao ou configuracao.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import amostra as amostragem
from . import fixtures as gerador
from . import lint
from . import x11

PASTA_DO_CANARIO = "tools/log_policy/tests/fixtures/lint"

#: Classes de canario que os **padroes** tem de ver sozinhos, sem a ajuda da
#: lista de canarios. E o controlo positivo do varrimento: se os padroes
#: deixarem de ver um telefone, o zero que o `x11` devolve deixa de significar
#: alguma coisa.
CLASSES_VISIVEIS_POR_PADRAO = ("telefone", "nif", "email", "iban", "wamid")

#: Quantos achados se imprimem antes de resumir.
MAXIMO_IMPRESSO = 40


def _raiz(argumentos) -> Path:
    return (argumentos.root or Path(__file__).resolve().parents[2]).resolve()


def _ler_fixtures(caminho: Path) -> list[dict]:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise x11.ConfiguracaoInvalida(
            f"nao se leem as fixtures em {caminho.name} ({type(erro).__name__})"
        ) from None
    if not isinstance(dados, list) or not dados:
        raise x11.ConfiguracaoInvalida("o ficheiro de fixtures esta vazio ou nao e uma lista")
    return dados


def controlo_positivo(fixtures: list[dict], nif_padroes=()) -> dict[str, tuple[int, int]]:
    """Por classe: quantas *fixtures* os padroes veem, e quantas ha.

    Varre-se o **valor** de cada *fixture*, so com os padroes (sem canarios) —
    e nao a chamada inteira, que leva um `tenant_id` com digitos seus.
    """
    configuracao = x11.Configuracao.criar(nif_padroes=nif_padroes)
    contagem: dict[str, list[int]] = {}
    for fixture in fixtures:
        visto = bool(x11.padroes_no_texto(fixture["valor"], configuracao))
        par = contagem.setdefault(fixture["classe"], [0, 0])
        par[0] += 1 if visto else 0
        par[1] += 1
    return {classe: (vistas, total) for classe, (vistas, total) in contagem.items()}


def _comando_lint(argumentos) -> int:
    raiz = _raiz(argumentos)
    achados, lidos = lint.verificar(raiz)
    for achado in achados:
        print(achado, file=sys.stderr)
    print(
        f"log_policy lint: {lidos['ts']} ficheiros TS/JS e {lidos['py']} Python "
        f"de servico lidos ({lidos['isentos']} do logger, isentos); "
        f"{len(achados)} achado(s)"
    )
    return 1 if achados else 0


def _comando_canario(argumentos) -> int:
    raiz = _raiz(argumentos)
    falhas, numeros = lint.canario(raiz / PASTA_DO_CANARIO)
    for falha in falhas:
        print(f"canario: {falha}", file=sys.stderr)
    print(
        f"log_policy canario: {numeros['negativas']} negativas e "
        f"{numeros['positivas']} positivas; {len(falhas)} falha(s)"
    )
    return 1 if falhas else 0


def _comando_fixtures(argumentos) -> int:
    fixtures = gerador.gerar(argumentos.quantas, argumentos.semente)
    if argumentos.quantas == gerador.QUANTAS:
        # O conjunto completo leva as fixtures de forma; um conjunto pequeno,
        # pedido por um teste, nao.
        fixtures += gerador.gerar_extras(argumentos.semente)
    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    argumentos.saida.write_text(
        json.dumps(fixtures, ensure_ascii=True, indent=None) + "\n", encoding="utf-8"
    )
    print(f"log_policy fixtures: {len(fixtures)} fixtures (semente {argumentos.semente})")
    return 0


def _comando_conduzir(argumentos) -> int:
    from . import conduzir

    fixtures = _ler_fixtures(argumentos.fixtures)
    texto, contadores = conduzir.conduzir(fixtures)
    argumentos.saida.parent.mkdir(parents=True, exist_ok=True)
    argumentos.saida.write_text(texto, encoding="utf-8", newline="\n")
    argumentos.contadores.write_text(
        json.dumps(contadores, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    if argumentos.ponte is not None:
        argumentos.ponte.write_text(
            conduzir.conduzir_ponte(fixtures), encoding="utf-8", newline="\n"
        )
    print(f"log_policy conduzir: {len(fixtures)} chamadas, {sum(contadores.values())} rejeicoes")
    return 0


def _comando_iguais(argumentos) -> int:
    a = argumentos.a.read_bytes()
    b = argumentos.b.read_bytes()
    if a == b:
        print(f"log_policy iguais: {argumentos.a.name} e {argumentos.b.name} coincidem ({len(a)} bytes)")
        return 0
    linhas_a, linhas_b = a.split(b"\n"), b.split(b"\n")
    primeira = next(
        (i for i, (x, y) in enumerate(zip(linhas_a, linhas_b), start=1) if x != y),
        min(len(linhas_a), len(linhas_b)) + 1,
    )
    # So o numero da linha: o conteudo de uma linha que diverge pode ser
    # precisamente o que uma das implementacoes deixou passar.
    print(
        f"log_policy iguais: {argumentos.a.name} e {argumentos.b.name} divergem "
        f"a partir da linha {primeira} ({len(linhas_a)} e {len(linhas_b)} linhas)",
        file=sys.stderr,
    )
    return 1


def _comando_x11(argumentos) -> int:
    canarios: list[str] = []
    falhou = False
    if argumentos.fixtures is not None:
        fixtures = _ler_fixtures(argumentos.fixtures)
        for fixture in fixtures:
            canarios.extend(fixture["canarios"])
        controlo = controlo_positivo(fixtures, argumentos.nif_padrao)
        for classe in CLASSES_VISIVEIS_POR_PADRAO:
            vistas, total = controlo.get(classe, (0, 0))
            if total == 0 or vistas != total:
                print(
                    f"x11: controlo positivo falhou em `{classe}`: os padroes "
                    f"veem {vistas} de {total} fixtures",
                    file=sys.stderr,
                )
                falhou = True
        print(
            "x11: controlo positivo — "
            + ", ".join(f"{c} {v}/{t}" for c, (v, t) in sorted(controlo.items()))
        )
    configuracao = x11.Configuracao.criar(nif_padroes=argumentos.nif_padrao, canarios=canarios)
    if not configuracao.nif_padroes:
        print(
            "x11: PADRAO DE NIF NAO DEFINIDO — o NIF nao e medido por padrao "
            "proprio (docs/seguranca/lacunas.md, Q-A); fica o de sequencia de digitos"
        )

    total_linhas = 0
    achados: list[x11.Achado] = []
    for caminho in argumentos.logs:
        do_ficheiro, linhas = x11.varrer_ficheiro(caminho, configuracao)
        achados.extend(do_ficheiro)
        total_linhas += linhas
        if argumentos.linhas_esperadas is not None and linhas != argumentos.linhas_esperadas:
            print(
                f"x11: {caminho.name} tem {linhas} linhas, esperava "
                f"{argumentos.linhas_esperadas}: um registo incompleto nao prova nada",
                file=sys.stderr,
            )
            falhou = True
    if total_linhas == 0:
        print("x11: nenhuma linha lida; zero achados em zero linhas nao e um resultado", file=sys.stderr)
        falhou = True

    for achado in achados[:MAXIMO_IMPRESSO]:
        print(f"x11: {achado}", file=sys.stderr)
    if len(achados) > MAXIMO_IMPRESSO:
        print(f"x11: … e mais {len(achados) - MAXIMO_IMPRESSO}", file=sys.stderr)
    print(
        f"log_policy x11: {total_linhas} linhas em {len(argumentos.logs)} ficheiro(s), "
        f"{len(canarios)} canarios; {len(achados)} achado(s)"
    )
    return 1 if achados or falhou else 0


def _comando_amostra(argumentos) -> int:
    configuracao = x11.Configuracao.criar(nif_padroes=argumentos.nif_padrao)
    registo = amostragem.amostrar(
        argumentos.pasta,
        configuracao,
        quantas=argumentos.linhas,
        semente=argumentos.semente,
    )
    amostragem.registar(registo, argumentos.registo)
    print(json.dumps(registo, ensure_ascii=False, sort_keys=True))
    return 1 if registo["identificadores_directos"] or registo["desvios_de_formato"] else 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="log_policy", description="Politica de logs sem conteudo (KAM-068)"
    )
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)

    sub.add_parser("lint", help="nenhum servico escreve fora do logger")
    sub.add_parser("canario", help="as fixtures negativas do lint tem de falhar")

    p = sub.add_parser("fixtures", help="gera as fixtures do X-11")
    p.add_argument("--saida", type=Path, required=True)
    p.add_argument("--quantas", type=int, default=gerador.QUANTAS)
    p.add_argument("--semente", type=int, default=gerador.SEMENTE)

    p = sub.add_parser("conduzir", help="passa as fixtures pelo logger em Python")
    p.add_argument("fixtures", type=Path)
    p.add_argument("--saida", type=Path, required=True)
    p.add_argument("--contadores", type=Path, required=True)
    p.add_argument("--ponte", type=Path, default=None)

    p = sub.add_parser("iguais", help="dois ficheiros sao iguais byte a byte")
    p.add_argument("a", type=Path)
    p.add_argument("b", type=Path)

    p = sub.add_parser("x11", help="varre ficheiros de log")
    p.add_argument("logs", nargs="+", type=Path)
    p.add_argument("--fixtures", type=Path, default=None)
    p.add_argument("--linhas-esperadas", type=int, default=None)
    p.add_argument("--nif-padrao", action="append", default=[])

    p = sub.add_parser("amostra", help="amostra e varre os logs de cada servico")
    p.add_argument("pasta", type=Path)
    p.add_argument("--registo", type=Path, required=True)
    p.add_argument("--linhas", type=int, default=amostragem.LINHAS_POR_SERVICO)
    p.add_argument("--semente", type=int, default=None)
    p.add_argument("--nif-padrao", action="append", default=[])

    argumentos = analisador.parse_args(argv)
    comandos = {
        "lint": _comando_lint,
        "canario": _comando_canario,
        "fixtures": _comando_fixtures,
        "conduzir": _comando_conduzir,
        "iguais": _comando_iguais,
        "x11": _comando_x11,
        "amostra": _comando_amostra,
    }
    try:
        return comandos[argumentos.comando](argumentos)
    except (x11.ConfiguracaoInvalida, lint.ConfiguracaoInvalida, OSError) as erro:
        print(f"log_policy: erro: {erro}", file=sys.stderr)
        return 2
