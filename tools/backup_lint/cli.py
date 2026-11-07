"""Interface de linha de comandos do `backup_lint` (KAM-079).

    python -m backup_lint lint     [--root .]              as cinco superficies
    python -m backup_lint canario  [--root .]              prova que o lint morde
    python -m backup_lint restauro [--agora ...] [--ultimo ...]  o predicado mensal
    python -m backup_lint debito --bytes N --segundos S     o orcamento do §8.2

Codigo de saida 0 = limpo, 1 = achados, 2 = erro de utilizacao ou configuracao.

A distincao entre 1 e 2 e a do `canon_lint`, do `env_lint` e do `obs_lint`: **uma
configuracao que nao se le nao pode parecer uma configuracao conforme.**

================================================================================
O FUNIL E UM SO
================================================================================

Os comandos `restauro` e `debito` tem **duas** formas de saida — texto para quem
le no terminal e `--json` para quem a consome num *job*. A guarda do criterio 7
(nada de dados reais sem `apd_ref`) atravessa as duas pelo **mesmo** ponto:
`_decidir`, que e a unica funcao que chama o `politica.pode_enviar`, e
`_imprimir`, que e a unica que escreve.

Isto nao e arrumacao. Uma protecao de privacidade que vive dentro do caminho de
JSON deixa o caminho de texto — que e o de **omissao** — sem guarda nenhuma, e
foi medido neste repositorio noutro ticket. O ensaio
`test_o_funil_e_um_so` prende-o estruturalmente: conta as chamadas a
`pode_enviar` no modulo e exige que haja **uma**.

================================================================================
NAO ESTA LIGADO A NENHUM PORTAO, E ISSO E DELIBERADO
================================================================================

Ligar uma verificacao que trava fusoes e **alteracao de regra de bloqueio**, e
isso e decisao do fundador — nao de quem escreve o ticket. Vale pelos dois
caminhos, e o segundo e o que parece inofensivo:

1. um *job* novo no `.github/workflows/ci.yaml` acrescenta um **contexto
   exigido** ao *ruleset* da `main`;
2. entrar num alvo `ci-*` que ja existe nao cria contexto novo, mas muda o
   **criterio** de um portao que ja bloqueia: a partir desse momento o portao
   reprova arvores que antes aprovava. E a mesma fronteira, por outra porta.

A suite `tools/backup_lint/tests/` corre no *gate* 4 como as outras de `tools/`,
porque esse portao e sobre **testes** e nao sobre esta configuracao. Quem quiser
ligar o *lint* escreve uma linha no `Makefile`, no alvo `ci-2`, ao lado do
`log-lint`:

    @$(MAKE) backup-lint
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import canario as canario_mod
from . import lint, politica

#: Quantos achados se imprimem antes de resumir.
MAXIMO_IMPRESSO = 40


def _raiz(argumentos) -> Path:
    return (argumentos.root or Path(__file__).resolve().parents[2]).resolve()


def _imprimir(carga: dict, como_json: bool) -> None:
    """**A unica funcao que escreve.** Os dois formatos saem daqui.

    Com duas funcoes de impressao, uma mensagem acrescentada a um formato
    faltaria no outro — e e assim que uma guarda fica a faltar num dos caminhos.
    """
    if como_json:
        print(json.dumps(carga, ensure_ascii=False, sort_keys=True))
        return
    for chave, valor in carga.items():
        if isinstance(valor, dict):
            print(f"{chave}:")
            for sub, subvalor in valor.items():
                print(f"  {sub}: {subvalor}")
        else:
            print(f"{chave}: {valor}")


def _decidir(argumentos) -> politica.Veredicto:
    """**A unica chamada ao funil.** Todo o comando que escreve passa por aqui.

    O `--classe` tem omissao `synthetic`, que e a do compose de producao
    (`KAMBA_DATA_CLASS: ${KAMBA_DATA_CLASS:-synthetic}`): a omissao de um
    comando de backup nao pode ser «trata isto como dados reais».

    O `--apd-ref` nao tem omissao nenhuma. Nao ha destino decidido
    (D1/KAM-105), pelo que `--classe real` recusa hoje **sempre** — e e isso que
    o gate do criterio 7 tem de fazer.
    """
    return politica.pode_enviar(
        classe_de_dados=argumentos.classe,
        apd_ref=argumentos.apd_ref,
        destino=argumentos.destino,
    )


def _comando_lint(argumentos) -> int:
    try:
        achados, numeros = lint.varrer(_raiz(argumentos))
    except lint.ConfiguracaoInvalida as erro:
        print(f"backup_lint: {erro}", file=sys.stderr)
        return 2
    # Imprime **quanto** leu, sempre, e os `configurado` em voz alta: um verde
    # sobre itens que nunca correram nao e o mesmo verde.
    print(
        f"backup_lint: {numeros['itens']} itens de cobertura "
        f"({numeros['cobertos']} coberto(s), "
        f"{numeros['configurados']} CONFIGURADO(S) e nunca executado(s), "
        f"{numeros['por_cobrir']} por cobrir), "
        f"{numeros['destinos']} destino(s) e {numeros['destinos_por_decidir']} "
        f"por decidir, "
        f"{numeros['chaves_do_pgbackrest']}+{numeros['chaves_do_arquivo']} chaves "
        f"de configuracao, {numeros['regras']} regras"
    )
    if not achados:
        print("backup_lint: 0 achados")
        return 0
    for achado in achados[:MAXIMO_IMPRESSO]:
        print(f"backup_lint: {achado}", file=sys.stderr)
    if len(achados) > MAXIMO_IMPRESSO:
        print(
            f"backup_lint: e mais {len(achados) - MAXIMO_IMPRESSO} achados",
            file=sys.stderr,
        )
    print(f"backup_lint: {len(achados)} achados", file=sys.stderr)
    return 1


def _comando_canario(argumentos) -> int:
    try:
        falhas, numeros = canario_mod.correr(_raiz(argumentos))
    except lint.ConfiguracaoInvalida as erro:
        print(f"backup_lint: {erro}", file=sys.stderr)
        return 2
    print(
        f"backup_lint canario: {numeros['morderam']} de {numeros['casos']} casos "
        f"a morder, a exercitar {numeros['regras_exercitadas']} de "
        f"{numeros['regras']} regras"
    )
    if not falhas:
        return 0
    for falha in falhas:
        print(f"backup_lint canario: {falha}", file=sys.stderr)
    print(f"backup_lint canario: {len(falhas)} falha(s)", file=sys.stderr)
    return 1


def _comando_restauro(argumentos) -> int:
    """O predicado mensal, com o relogio por parametro — tambem na linha."""
    raiz = _raiz(argumentos)
    try:
        dados = lint.ler(raiz)
    except lint.ConfiguracaoInvalida as erro:
        print(f"backup_lint: {erro}", file=sys.stderr)
        return 2
    periodo = dados.cobertura["restauro"]["periodo_dias"]
    try:
        agora = (
            politica.ler_instante(argumentos.agora)
            if argumentos.agora
            else datetime.now(timezone.utc)
        )
        ultimo = politica.ler_instante(argumentos.ultimo) if argumentos.ultimo else None
        devido = politica.restauro_devido(
            agora=agora, ultimo_em=ultimo, periodo_dias=periodo
        )
        vence = politica.proximo_restauro(
            ultimo_em=ultimo, periodo_dias=periodo, agora=agora
        )
    except ValueError as erro:
        print(f"backup_lint: {erro}", file=sys.stderr)
        return 2
    veredicto = _decidir(argumentos)
    _imprimir(
        {
            "comando": "restauro",
            "agora": agora.isoformat(),
            "ultimo_em": ultimo.isoformat() if ultimo else None,
            "periodo_dias": periodo,
            "devido": devido,
            "vence_em": vence.isoformat(),
            "agendador": dados.cobertura["restauro"]["agendador"],
            "credor_do_agendador": dados.cobertura["restauro"].get(
                "credor_do_agendador"
            ),
            "envio": {"permitido": veredicto.permitido, "razao": veredicto.razao},
        },
        argumentos.json,
    )
    # **O codigo de saida nao e o do predicado.** Um restauro em divida nao e um
    # erro da ferramenta: e a resposta que se pediu. Quem o quer como falha le o
    # `devido`. O que **e** saida 1 e o envio recusado, porque isso e a guarda a
    # morder.
    return 0 if veredicto.permitido else 1


def _comando_debito(argumentos) -> int:
    """O debito medido contra o orcamento do `docs/tecnica/09` §8.2."""
    raiz = _raiz(argumentos)
    try:
        dados = lint.ler(raiz)
    except lint.ConfiguracaoInvalida as erro:
        print(f"backup_lint: {erro}", file=sys.stderr)
        return 2
    alvos = dados.cobertura["alvos"]
    try:
        mbps = politica.debito_mbps(
            bytes_lidos=argumentos.bytes, segundos=argumentos.segundos
        )
        divergencia_tempo = politica.divergencia_do_orcamento_pct(
            medido=argumentos.segundos,
            orcamentado=alvos["orcamento_restauro_segundos"],
        )
        corrigir = politica.orcamento_a_corrigir(
            medido=argumentos.segundos,
            orcamentado=alvos["orcamento_restauro_segundos"],
            divergencia_maxima_pct=alvos["divergencia_maxima_pct"],
        )
    except ValueError as erro:
        print(f"backup_lint: {erro}", file=sys.stderr)
        return 2
    veredicto = _decidir(argumentos)
    _imprimir(
        {
            "comando": "debito",
            "bytes": argumentos.bytes,
            "segundos": argumentos.segundos,
            "debito_mbps": round(mbps, 3),
            "orcamento_debito_mbps": alvos["orcamento_debito_mbps"],
            "orcamento_restauro_segundos": alvos["orcamento_restauro_segundos"],
            "divergencia_pct": round(divergencia_tempo, 2),
            "divergencia_maxima_pct": alvos["divergencia_maxima_pct"],
            "orcamento_a_corrigir": corrigir,
            "envio": {"permitido": veredicto.permitido, "razao": veredicto.razao},
        },
        argumentos.json,
    )
    return 0 if veredicto.permitido else 1


def _acrescentar_guarda(analisador: argparse.ArgumentParser) -> None:
    """As tres opcoes do funil, iguais em todos os comandos que escrevem.

    Estao numa funcao e nao copiadas: duas copias divergem, e a divergencia que
    importa e a omissao do `--classe`. Um comando onde ela fosse `real` por
    distraccao era o gate do criterio 7 aberto num dos caminhos.
    """
    analisador.add_argument(
        "--classe",
        choices=politica.CLASSES_DE_DADOS,
        default="synthetic",
        help="classe de dados (omissao: synthetic, a do compose de producao)",
    )
    analisador.add_argument("--apd-ref", default=None, dest="apd_ref")
    analisador.add_argument("--destino", default=None)
    analisador.add_argument("--json", action="store_true")


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog="backup_lint", description=__doc__)
    analisador.add_argument("--root", type=Path, default=None)
    sub = analisador.add_subparsers(dest="comando", required=True)

    sub.add_parser("lint", help="as cinco superficies concordam")
    sub.add_parser("canario", help="prova que o lint morde")

    restauro = sub.add_parser("restauro", help="o predicado do restauro mensal")
    restauro.add_argument("--agora", default=None, help="ISO-8601 com fuso")
    restauro.add_argument("--ultimo", default=None, help="ISO-8601 com fuso")
    _acrescentar_guarda(restauro)

    debito = sub.add_parser("debito", help="debito medido contra o orcamento")
    debito.add_argument("--bytes", type=int, required=True)
    debito.add_argument("--segundos", type=float, required=True)
    _acrescentar_guarda(debito)

    argumentos = analisador.parse_args(argv)
    if argumentos.comando == "lint":
        return _comando_lint(argumentos)
    if argumentos.comando == "canario":
        return _comando_canario(argumentos)
    if argumentos.comando == "restauro":
        return _comando_restauro(argumentos)
    return _comando_debito(argumentos)
