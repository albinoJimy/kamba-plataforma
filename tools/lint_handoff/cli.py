"""Interface de linha de comando do `lint_handoff`.

    python -m lint_handoff check [--root .]   falha se houver caminho defeituoso
    python -m lint_handoff censo [--root .]   imprime a populacao por classe
    python -m lint_handoff file <ficheiro>    varre um ficheiro (para depurar)

Codigo de saida 0 = conforme, 1 = achados, 2 = erro de configuracao. A
distincao importa: uma arvore que nao se encontrou nao pode parecer limpa.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

from kamba_yaml import YamlSubsetError, load_file

from .scan import (DEFEITOS, PADROES, contar_blocos, ficheiros, varrer_arvore,
                   varrer_ficheiro)

#: Onde vivem as excepcoes declaradas, relativo a raiz.
ALLOW = 'ci/handoff-allow.yaml'


class ConfiguracaoInvalida(Exception):
    """A lista de excepcoes nao se pode ler, ou nao diz o que promete."""


def ler_excepcoes(raiz: Path) -> tuple[str, ...]:
    """Os excertos declarados em `ci/handoff-allow.yaml`.

    A ausencia do ficheiro e legitima e significa «nenhuma excepcao». Um
    ficheiro ilegivel, ou uma entrada sem `excerto` ou sem `razao`, **nao** e:
    uma excepcao sem razao escrita e uma excepcao que ninguem pode revogar.
    """
    f = raiz / ALLOW
    if not f.is_file():
        return ()
    try:
        dados = load_file(f)
    except (YamlSubsetError, OSError) as e:
        raise ConfiguracaoInvalida(f'{ALLOW}: {e}') from e
    if not isinstance(dados, dict):
        raise ConfiguracaoInvalida(f'{ALLOW}: a raiz tem de ser um mapeamento')
    entradas = dados.get('excepcoes') or []
    if not isinstance(entradas, list):
        raise ConfiguracaoInvalida(f'{ALLOW}: `excepcoes` tem de ser uma lista')
    out: list[str] = []
    for i, e in enumerate(entradas, 1):
        if not isinstance(e, dict):
            raise ConfiguracaoInvalida(f'{ALLOW}: a entrada {i} nao e um mapeamento')
        excerto, razao = e.get('excerto'), e.get('razao')
        if not isinstance(excerto, str) or not excerto.strip():
            raise ConfiguracaoInvalida(f'{ALLOW}: a entrada {i} nao tem `excerto`')
        if not isinstance(razao, str) or not razao.strip():
            raise ConfiguracaoInvalida(f'{ALLOW}: a entrada {i} ({excerto!r}) nao tem `razao`')
        out.append(excerto)
    return tuple(out)


def _excepcoes_mortas(raiz: Path, padroes, excepcoes: tuple[str, ...]) -> list[str]:
    """As excepcoes que nao casam nenhuma linha de nenhum bloco de *handoff*.

    Uma excepcao esquecida continua a abrir uma porta que ninguem vigia.
    """
    vivas: set[str] = set()
    for f in ficheiros(raiz, padroes):
        texto = f.read_text(encoding='utf-8')
        for e in excepcoes:
            if e in texto:
                vivas.add(e)
    return [e for e in excepcoes if e not in vivas]


def _imprimir_censo(achados: list, destino) -> None:
    """A populacao por ficheiro e por classe, com a soma a fechar."""
    por = collections.Counter((a.ficheiro, a.classe) for a in achados)
    classes = sorted({a.classe for a in achados})
    ficheiros = sorted({a.ficheiro for a in achados})
    largura = max((len(f) for f in ficheiros), default=10)
    print('  '.join(['ficheiro'.ljust(largura)] + [c.rjust(16) for c in classes]), file=destino)
    for f in ficheiros:
        linha = [f.ljust(largura)] + [str(por[(f, c)]).rjust(16) for c in classes]
        print('  '.join(linha), file=destino)
    total = [str(sum(por[(f, c)] for f in ficheiros)).rjust(16) for c in classes]
    print('  '.join(['TOTAL'.ljust(largura)] + total), file=destino)
    print(f'\n{len(achados)} ocorrencia(s) em {len(ficheiros)} ficheiro(s).', file=destino)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog='lint_handoff',
        description='Caminhos dentro de blocos de handoff: relativos a raiz do repositorio.',
    )
    p.add_argument('--root', default='.', help='raiz do repositorio (por omissao, o cwd)')
    p.add_argument('--padrao', action='append', dest='padroes', metavar='GLOB',
                   help='glob dos ficheiros a varrer; repetivel. Por omissao: '
                        + ' e '.join(PADROES))
    sub = p.add_subparsers(dest='acao', required=True)
    sub.add_parser('check', help='falha se houver caminho defeituoso')
    sub.add_parser('censo', help='imprime a populacao por classe')
    pf = sub.add_parser('file', help='varre um ficheiro')
    pf.add_argument('ficheiro')
    a = p.parse_args(argv)
    padroes = tuple(a.padroes) if a.padroes else PADROES

    raiz = Path(a.root).resolve()
    if not raiz.is_dir():
        print(f'lint_handoff: raiz inexistente: {raiz}', file=sys.stderr)
        return 2
    try:
        excepcoes = ler_excepcoes(raiz)
    except ConfiguracaoInvalida as e:
        print(f'lint_handoff: {e}', file=sys.stderr)
        return 2

    if a.acao == 'file':
        f = Path(a.ficheiro)
        f = f if f.is_absolute() else (raiz / f)
        if not f.is_file():
            print(f'lint_handoff: ficheiro inexistente: {f}', file=sys.stderr)
            return 2
        achados = varrer_ficheiro(f.resolve(), raiz, excepcoes)
    else:
        achados = varrer_arvore(raiz, padroes, excepcoes)
        if not achados:
            print(f'lint_handoff: nenhum bloco de handoff em {list(padroes)!r} sob {raiz}',
                  file=sys.stderr)
            return 2

    if a.acao == 'censo':
        _imprimir_censo(achados, sys.stdout)
        return 0

    # O delimitador tem de ver um bloco por ticket. Sem isto, «conforme» diz o
    # mesmo sobre a populacao inteira e sobre zero blocos reconhecidos. So se
    # exige onde ha titulos de ticket: uma arvore de prova nao os tem.
    blocos, titulos = contar_blocos(raiz, padroes)
    if titulos and blocos != titulos:
        print(f'lint_handoff: {blocos} bloco(s) de handoff para {titulos} ticket(s) — '
              'cada bloco `## KAM-NNN` tem de ter exactamente um. Um titulo mal escrito, '
              'uma cerca que nao fecha, ou um bloco a mais deixam parte da arvore sem '
              'ser lida.', file=sys.stderr)
        return 2

    mortas = _excepcoes_mortas(raiz, padroes, excepcoes)
    if mortas:
        print(f'lint_handoff: {len(mortas)} excepcao(oes) de {ALLOW} nao casam nenhuma linha:',
              file=sys.stderr)
        for e in mortas:
            print(f'  - {e!r}', file=sys.stderr)
        print('Uma excepcao esquecida continua a abrir uma porta que ninguem vigia: '
              'apaga-a ou corrige o excerto.', file=sys.stderr)
        return 2

    maus = [x for x in achados if x.defeito]
    if maus:
        print(f'lint_handoff: {len(maus)} caminho(s) defeituoso(s) em '
              f'{len({x.ficheiro for x in maus})} ficheiro(s):')
        for x in maus:
            porque = ('aponta para fora da arvore a partir da raiz' if x.classe == 'acima-da-raiz'
                      else 'nao resolve de posicao nenhuma: falta o directorio')
            print(f'  - {x.ficheiro}:{x.linha}: {x.texto}  ({porque})')
        print('\nOs caminhos dentro de um bloco de handoff sao relativos a raiz do repositorio')
        print('(specs/01_Engineering_Standards_e_Handoff.md §5, KAM-145). Fora desses blocos a')
        print(f'regra e a do KAM-128 e este gate nao a le. Uma linha cujo ASSUNTO e uma forma de')
        print(f'caminho declara-se em {ALLOW}, com a razao.')
        return 1

    print(f'lint_handoff: conforme — {len(achados)} caminho(s) em {blocos} bloco(s) de handoff, '
          f'{len({x.ficheiro for x in achados})} ficheiro(s); 0 defeituoso(s) '
          f'({", ".join(DEFEITOS)}); {len(excepcoes)} excepcao(oes) declarada(s).')
    return 0
