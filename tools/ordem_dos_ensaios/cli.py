"""Interface de linha de comando do `ordem_dos_ensaios`.

    python -m ordem_dos_ensaios check --suite <dir> [--topo <dir>] [--nome <n>]
    python -m ordem_dos_ensaios canario
    python -m ordem_dos_ensaios corredor --suite <dir> --topo <dir> \
        --padrao <p> --ordem <normal|inversa> --saida <json>

Codigo de saida 0 = conforme, 1 = suite dependente da ordem (ou canario que
nao morde), 2 = erro de configuracao. A distincao importa: uma suite que nao
se encontrou nao pode parecer limpa — foi o defeito que o `db/correr_suite.py`
fechou do seu lado («num gate, saltar e falhar»).

O `corredor` e o subcomando **interno**: e o processo filho que corre uma
ordem. Nao se chama a mao; esta documentado porque aparece no `ps` e nos
registos quando algo corre mal.

## O que este portao nao cobre, dito junto com o resultado

1. **Uma ordem a mais nao prova independencia de ordem.** Prova que a ordem
   inversa tambem passa. Provar independencia era correr cada teste sozinho —
   537 processos para o `libs/py-core` — e isso e isolamento, nao ordem: outro
   problema, muito maior, e nao e este ticket.
2. **Nao cobre as suites de `tools/`** nem as de `db/`. A razao e o custo,
   medido, e esta escrita em `specs/tickets/KAM-173.md`.
3. **Nao ve acoplamento entre processos** — ficheiros deixados no disco, portas,
   contentores. Isso e o *gate* 8 e o `db/mutacoes.py`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import canario as mod_canario
from . import corredor as mod_corredor
from .corredor import Resultado

#: O padrao do `unittest discover`, que e tambem o que o alvo `coverage-python`
#: usa nas suites reais. As *fixtures* do canario usam outro, de proposito
#: (ver `canario.PADRAO`).
PADRAO_PADRAO = 'test*.py'


def _ambiente_do_filho() -> dict[str, str]:
    """O `PYTHONPATH` do filho, com o `sys.path` deste processo a cabeca.

    Sem isto, o filho importava `ordem_dos_ensaios` so quando o `PYTHONPATH`
    do ambiente ja o levava — que e o caso no `make` (`export PYTHONPATH`) e
    **nao** e o caso de quem corre a suite deste modulo a mao. Um verificador
    que so funciona quando invocado de uma maneira nao e um portao.
    """
    ambiente = dict(os.environ)
    caminhos = [p for p in sys.path if p]
    anterior = ambiente.get('PYTHONPATH', '')
    if anterior:
        caminhos.append(anterior)
    ambiente['PYTHONPATH'] = os.pathsep.join(caminhos)
    return ambiente


def _correr_fora(
    start_dir: Path, topo: Path, padrao: str, ordem: str
) -> Resultado:
    """Corre uma ordem **noutro processo**, e le o resultado de um JSON.

    O processo proprio e o ponto todo: duas ordens no mesmo processo mediam a
    passagem anterior e nao a ordem (ver o `corredor`).
    """
    with tempfile.TemporaryDirectory() as temporario:
        saida = Path(temporario) / 'estado.json'
        comando = [
            sys.executable,
            '-m',
            'ordem_dos_ensaios',
            'corredor',
            '--suite',
            str(start_dir),
            '--topo',
            str(topo),
            '--padrao',
            padrao,
            '--ordem',
            ordem,
            '--saida',
            str(saida),
        ]
        processo = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            check=False,
            env=_ambiente_do_filho(),
        )
        if not saida.exists():
            raise RuntimeError(
                f'o corredor nao escreveu {saida} (ordem {ordem}, codigo '
                f'{processo.returncode}):\n{processo.stdout}\n{processo.stderr}'
            )
        dados = json.loads(saida.read_text(encoding='utf-8'))
    return Resultado(dados['estado'], dados['corridos'])


def _check(args: argparse.Namespace) -> int:
    raiz = Path(args.root).resolve()
    start_dir = (raiz / args.suite).resolve()
    topo = (raiz / args.topo).resolve() if args.topo else start_dir
    nome = args.nome or args.suite

    if not start_dir.is_dir():
        print(f'ordem_dos_ensaios: {start_dir} nao existe.', file=sys.stderr)
        return 2

    try:
        resultado = _correr_fora(start_dir, topo, args.padrao, 'inversa')
    except (RuntimeError, json.JSONDecodeError) as erro:
        print(f'ordem_dos_ensaios: {erro}', file=sys.stderr)
        return 2

    if resultado.corridos == 0:
        print(
            f'ordem_dos_ensaios: {nome} — nenhum teste foi descoberto na '
            'ordem inversa. Um portao que nao corre nada nao verifica nada.',
            file=sys.stderr,
        )
        return 2

    vermelhos = resultado.vermelhos()
    if vermelhos:
        print(
            f'ordem_dos_ensaios: {nome} — {len(vermelhos)} de '
            f'{resultado.corridos} teste(s) vermelho(s) na ordem inversa. A '
            'ordem de omissao do unittest ja foi exigida verde pelo '
            'coverage-python, que corre antes deste alvo no gate 4; logo '
            'estes passam por acidente da ordem de carregamento:',
            file=sys.stderr,
        )
        for identificador in vermelhos[:20]:
            estado = resultado.estado[identificador]
            print(f'  - {identificador}: {estado}', file=sys.stderr)
        print(
            '\nA correccao e no teste, nao no portao: o estado de processo que '
            'ele toca (um registo a nivel de modulo, uma variavel de ambiente, '
            'o nivel de um logger com nome, uma entrada do sys.modules) tem de '
            'ser reposto por quem o suja.',
            file=sys.stderr,
        )
        return 1

    print(
        f'ordem_dos_ensaios: {nome} — {resultado.corridos} testes na ordem '
        'inversa, 0 vermelhos'
    )
    return 0


def _canario(args: argparse.Namespace) -> int:
    del args

    def correr_fixture(pasta: Path, ordem: str) -> Resultado:
        return _correr_fora(pasta, pasta, mod_canario.PADRAO, ordem)

    queixas: list[str] = []
    for caso in mod_canario.CASOS:
        try:
            queixas.extend(mod_canario.verificar(caso, correr_fixture))
        except (RuntimeError, json.JSONDecodeError) as erro:
            queixas.append(f'{caso.codigo}: {erro}')

    if queixas:
        print(
            'ordem_dos_ensaios canario: o portao nao se provou.',
            file=sys.stderr,
        )
        for queixa in queixas:
            print(f'  - {queixa}', file=sys.stderr)
        return 1

    mordem = sum(1 for caso in mod_canario.CASOS if not caso.inversa_verde)
    print(
        f'ordem_dos_ensaios canario: {len(mod_canario.CASOS)} de '
        f'{len(mod_canario.CASOS)} casos conforme ({mordem} a morder, '
        f'{len(mod_canario.CASOS) - mordem} a distinguir)'
    )
    return 0


def _corredor(args: argparse.Namespace) -> int:
    """O filho: corre uma ordem e escreve o estado de cada teste."""
    resultado, relato = mod_corredor.correr(
        args.suite, args.topo, args.padrao, args.ordem
    )
    Path(args.saida).write_text(
        json.dumps(
            {'estado': resultado.estado, 'corridos': resultado.corridos},
            indent=0,
            sort_keys=True,
        ),
        encoding='utf-8',
    )
    if resultado.vermelhos():
        sys.stderr.write(relato[-8000:])
    return 0


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(prog='ordem_dos_ensaios')
    analisador.add_argument('--root', default='.')
    comandos = analisador.add_subparsers(dest='comando', required=True)

    verificar = comandos.add_parser(
        'check', help='corre a suite na ordem inversa e exige verde'
    )
    verificar.add_argument('--suite', required=True)
    verificar.add_argument('--topo', default=None)
    verificar.add_argument('--nome', default=None)
    #: So os testes deste modulo o passam, para exercitarem o `check` contra as
    #: *fixtures* do canario, que usam `caso_*.py`. No `Makefile` fica a
    #: omissao, que e o padrao das suites reais.
    verificar.add_argument('--padrao', default=PADRAO_PADRAO)
    verificar.set_defaults(funcao=_check)

    prova = comandos.add_parser(
        'canario', help='prova que o portao morde, e que distingue'
    )
    prova.set_defaults(funcao=_canario)

    filho = comandos.add_parser('corredor', help='interno: corre uma ordem')
    filho.add_argument('--suite', required=True)
    filho.add_argument('--topo', required=True)
    filho.add_argument('--padrao', required=True)
    filho.add_argument('--ordem', required=True, choices=mod_corredor.ORDENS)
    filho.add_argument('--saida', required=True)
    filho.set_defaults(funcao=_corredor)

    args = analisador.parse_args(argv)
    return int(args.funcao(args))
