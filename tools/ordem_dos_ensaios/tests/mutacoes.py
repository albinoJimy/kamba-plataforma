"""As mutacoes deste portao, para a afirmacao «morrem» ser reproduzivel.

Uma afirmacao de mutacao sem guiao e uma afirmacao: o bloco do KAM-182 dizia
«seis mutacoes, seis mortas» e o guiao nao estava na arvore, pelo que ninguem a
podia correr. Achado da revisao adversarial, e e por isso que este ficheiro
existe. O irmao e o `tools/log_policy/tests/mutacoes.py`, e vive debaixo de
`tests/` pela mesma razao: o `--omit="*/tests/*"` do alvo `coverage-python`
deixa-o fora do denominador da cobertura.

**Nao e um portao, e isso e deliberado.** Nenhum alvo do `Makefile` o chama.
Uma suite de mutacao ligada ao *gate* 4 multiplicava o tempo dele por treze, e
o custo das suites de `tools/` esta medido em `specs/tickets/KAM-173.md`.
Corre-se a mao, e a saida dele e a evidencia:

    PYTHONPATH=tools python -m ordem_dos_ensaios.tests.mutacoes

Cada mutacao e uma substituicao textual exacta num dos dois ficheiros de
codigo. O guiao aplica-a, corre a bateria **inteira** do modulo, restaura o
ficheiro no `finally` e diz quantos casos morreram. Uma mutacao que **nao casa**
e tratada como falha e nao como sucesso: significa que o codigo mudou de forma e
que a mutacao deixou de medir o que dizia medir, que e o modo de falha do
`env_lint/canario.py` registado nesta casa.

**As treze cobrem tres famílias**, e a terceira so existe por causa da revisao:

    a rede        desfazer a recusa, ou condiciona-la a ter conseguido nomear
    a atribuicao  cegar cada um dos quatro predicados que nomeiam a hipotese
    as direccoes  olhar so para uma ordem, ou so para um dos dois lados
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
MODULO = RAIZ / 'tools' / 'ordem_dos_ensaios'
CLI = MODULO / 'cli.py'
CORREDOR = MODULO / 'corredor.py'

#: `(rotulo, ficheiro, texto a substituir, substituto)`. O texto tem de casar
#: **exactamente** uma vez.
MUTACOES: tuple[tuple[str, Path, str, str], ...] = (
    (
        'a recusa devolve verde',
        CLI,
        '        if sem_nome:',
        '        return 0\n        if sem_nome:',
    ),
    (
        'recusar so quando consegue nomear alguem',
        CLI,
        '        if not resultado.sucesso\n    ]',
        '        if not resultado.sucesso\n'
        '        and (resultado.acusados or resultado.vermelhos())\n    ]',
    ),
    (
        'a frase de que a falha e do portao desaparece',
        CLI,
        '        if sem_nome:\n',
        '        if False and sem_nome:\n',
    ),
    (
        'os acusados que o Registo nao viu comecar deixam de contar',
        CLI,
        '    nunca_vistos = [i for i in acusados if i not in resultado.estado]',
        '    nunca_vistos = []',
    ),
    (
        'os acusados dados por verdes deixam de contar',
        CLI,
        '    dados_por_verdes = [\n'
        '        i for i in acusados if resultado.estado.get(i) in VERDE\n'
        '    ]',
        '    dados_por_verdes = []',
    ),
    (
        'o colapso medido contra o len(estado) e nao contra os casos',
        CLI,
        '    colapsados = resultado.corridos - resultado.corridos_distintos',
        '    colapsados = resultado.corridos - len(resultado.estado)',
    ),
    (
        'o Registo nomeou vermelhos e a saida cala-o',
        CLI,
        '    if vermelhos and not nunca_vistos and not dados_por_verdes:',
        '    if False:',
    ),
    (
        'a hipotese nao sai, so os conjuntos',
        CLI,
        "                print(f'      hipotese: {hipotese}', file=sys.stderr)",
        '                pass',
    ),
    (
        'os conjuntos nao saem, so a hipotese',
        CLI,
        "                print(f'      {linha}', file=sys.stderr)",
        '                pass',
    ),
    (
        'a discordancia so se mede na ordem inversa',
        CLI,
        '        for ordem, resultado in resultados.items()\n'
        '        if not resultado.sucesso',
        '        for ordem, resultado in resultados.items()\n'
        "        if not resultado.sucesso and ordem == 'inversa'",
    ),
    (
        'sem a dobra do _SubTest no caso-pai',
        CORREDOR,
        "    pai = getattr(entrada, 'test_case', None)\n"
        '    if isinstance(pai, unittest.TestCase):\n'
        '        entrada = pai\n',
        '',
    ),
    (
        'sem a discriminacao caso / nao-caso nas acusacoes',
        CORREDOR,
        '    if isinstance(entrada, unittest.TestCase):\n'
        '        return etiqueta, etiqueta\n'
        '    return None, etiqueta\n',
        '    return etiqueta, etiqueta\n',
    ),
    (
        'os unexpectedSuccesses deixam de ser acusados',
        CORREDOR,
        "    entradas += list(getattr(registo, 'unexpectedSuccesses', ()))",
        '    pass',
    ),
)


def _correr_bateria() -> tuple[int, int]:
    """`(codigo, casos vermelhos)` da bateria inteira do modulo."""
    ambiente = dict(os.environ)
    ambiente['PYTHONPATH'] = str(RAIZ / 'tools')
    processo = subprocess.run(
        [
            sys.executable,
            '-m',
            'unittest',
            'discover',
            '-s',
            'tools/ordem_dos_ensaios/tests',
            '-t',
            'tools',
        ],
        cwd=RAIZ,
        env=ambiente,
        capture_output=True,
        text=True,
        check=False,
    )
    mortos = sum(
        1
        for linha in processo.stderr.splitlines()
        if linha.startswith(('FAIL:', 'ERROR:'))
    )
    return processo.returncode, mortos


def main() -> int:
    sobreviventes: list[str] = []
    for rotulo, ficheiro, velho, novo in MUTACOES:
        original = ficheiro.read_text(encoding='utf-8')
        if original.count(velho) != 1:
            print(
                f'{rotulo}: NAO CASOU ({original.count(velho)} ocorrencias) — '
                'a mutacao deixou de medir o que dizia medir',
                flush=True,
            )
            sobreviventes.append(rotulo)
            continue
        ficheiro.write_text(
            original.replace(velho, novo, 1), encoding='utf-8', newline='\n'
        )
        try:
            codigo, mortos = _correr_bateria()
        finally:
            ficheiro.write_text(original, encoding='utf-8', newline='\n')
        if codigo == 0:
            sobreviventes.append(rotulo)
            print(f'{rotulo}: SOBREVIVEU', flush=True)
        else:
            print(f'{rotulo}: MORTA ({mortos} caso(s))', flush=True)

    print(
        f'\n{len(MUTACOES) - len(sobreviventes)} de {len(MUTACOES)} mortas; '
        f'sobreviventes: {sobreviventes or "nenhuma"}',
        flush=True,
    )
    return 1 if sobreviventes else 0


if __name__ == '__main__':
    raise SystemExit(main())
