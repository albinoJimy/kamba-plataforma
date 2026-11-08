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

## O `check` corre as DUAS ordens, e isso custa o dobro de proposito

A primeira versao corria so a inversa, e dava a ordem de omissao por verde
porque o `coverage-python` a exige verde antes deste alvo. **A revisao
adversarial mostrou que isso nao mede a ordem**, e a prova ja estava escrita no
ticket de onde este herda: o `specs/tickets/KAM-163.md` registra que **duas
versoes do mesmo ensaio ficaram vermelhas sem nada ter mudado no codigo — uma
pela ordem das classes, outra pelo rastreador do `coverage`**. O
`coverage-python` corre sob `coverage run --branch`; este alvo nao. Com as duas
passagens a diferir no rastreador **e** na ordem, um vermelho na inversa nao
distinguia «dependente da ordem» de «vermelho sob o rastreador» — que e
exactamente a confusao que este portao existe para desfazer.

Agora as duas ordens correm aqui, no mesmo interpretador, com as mesmas
variaveis e sem `coverage` em nenhuma. **A unica coisa que difere entre elas e
a ordem**, pelo que uma diferenca de resultado e dela. O preco e uma execucao a
mais por suite (~12 s no `libs/py-core`, ~86 s no `services/agr`), e paga-se:
sem ela o portao afirmava mais do que media.

## O que este portao nao cobre, dito junto com o resultado

1. **Uma ordem a mais nao prova independencia de ordem.** Prova que a ordem
   inversa tambem passa. Provar independencia era correr cada teste sozinho —
   551 processos para o `libs/py-core` — e isso e isolamento, nao ordem: outro
   problema, muito maior, e nao e este ticket.
2. **Nao cobre as suites de `tools/`** — esta inclusive — nem as de `db/`. A
   razao e o custo, medido: as 18 de `tools/` que existiam antes deste modulo
   levam 1 911 s numa passagem, 1 422 deles da `supply_chain` so. Esta escrita
   em `specs/tickets/KAM-173.md`, com dono e prazo.
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
from .corredor import VERDE, Resultado

#: O padrao do `unittest discover`, que e tambem o que o alvo `coverage-python`
#: usa nas suites reais. As *fixtures* do canario usam outro, de proposito
#: (ver `canario.PADRAO`).
PADRAO_PADRAO = 'test*.py'

#: Tecto por passagem. A suite mais lenta que este alvo corre leva ~86 s, pelo
#: que 1 800 s e folga de vinte vezes e nunca aborta um verde. Existe porque a
#: ordem inversa muda **que** estado de processo existe quando cada teste
#: corre, e e essa a condicao que transforma um trinco latente em bloqueio: sem
#: tecto, o filho pendura, o *job* morre no relogio do GitHub e nao fica nada
#: para ler. Com tecto, sai 2 com o nome da suite e da ordem.
TECTO_SEGUNDOS = 1800


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
        try:
            processo = subprocess.run(
                comando,
                capture_output=True,
                text=True,
                check=False,
                env=_ambiente_do_filho(),
                timeout=TECTO_SEGUNDOS,
            )
        except subprocess.TimeoutExpired as expirou:
            raise RuntimeError(
                f'o corredor passou do tecto de {TECTO_SEGUNDOS} s na ordem '
                f'{ordem} sobre {start_dir}. Um teste que pendura so nesta '
                'ordem e acoplamento de ordem a bloquear — nao e um verde.'
            ) from expirou
        if not saida.exists():
            raise RuntimeError(
                f'o corredor nao escreveu {saida} (ordem {ordem}, codigo '
                f'{processo.returncode}):\n{processo.stdout}\n{processo.stderr}'
            )
        dados = json.loads(saida.read_text(encoding='utf-8'))
    return Resultado(
        estado=dados['estado'],
        corridos=dados['corridos'],
        sucesso=dados['sucesso'],
        relato=dados['relato'],
        # Por chave e nao por `.get`: um filho de outra versao tem de dar erro
        # e nao degradar em silencio para «nao acusa ninguem», que e
        # exactamente a saida que o KAM-182 veio tirar.
        corridos_distintos=dados['corridos_distintos'],
        acusados=tuple(dados['acusados']),
        sem_caso=tuple(dados['sem_caso']),
    )


def _atribuir(resultado: Resultado) -> tuple[list[str], list[str]]:
    """`(conjuntos, hipoteses)` de uma ordem que o `wasSuccessful()` reprovou.

    O KAM-182 fechou-se nisto: ate ele, o portao dizia «o instrumento perdeu
    informacao» quando a informacao estava no processo — o `relato` impresso a
    seguir **tinha** o nome e o *traceback*. Aqui poem-se os dois lados lado a
    lado — o que o `TestResult` acusa e o que o `Registo` classificou — e e a
    **diferenca** entre eles que nomeia a hipotese, em vez de quem le ter de a
    adivinhar a partir do *traceback* em bruto.

    As tres hipoteses distinguem-se por medicao e nao por preferencia:

        `corridos` > `corridos_distintos`  duas classificacoes colapsaram: dois
                                           casos com o mesmo `id()`, e a
                                           ultima escrita apagou o vermelho
        acusado que o `Registo` nao        um sinal do `unittest` que ele nao
        viu comecar                        derruba: entrou no `TestResult` por
                                           um caminho que o observador nao
                                           cobre
        acusado que o `estado` da verde    a classificacao daquele caso foi
                                           **sobrescrita** por um sinal
                                           posterior

    **A terceira diz o que se mediu e nao o mecanismo**, e isso e uma correccao
    ao Contexto do proprio KAM-182. O bloco supoe «um erro que chega depois de o
    caso ter terminado — num `tearDown`, num `done_callback`, numa *thread*» —
    e por essa via **nao ha discordancia nenhuma**: o erro entra pelo
    `addError`, que derruba o caso e o deixa vermelho no `estado`. Para o
    acusado ficar verde, alguem tem de escrever por cima depois: um `skip` de
    limpeza (o `addSkip` nao protege um vermelho, ao contrario do
    `addSubTest`), ou um `startTest` do mesmo `id()`. Medido pela revisao
    adversarial, com um `addCleanup` a levantar `SkipTest` sobre um caso que ja
    tinha falhado — e com o texto antigo a mandar procurar uma *thread* que nao
    existia.

    Mais do que uma pode valer ao mesmo tempo, e devolvem-se todas: no
    exemplar do `id()` repetido valem a primeira e a terceira, porque o colapso
    **e** o mecanismo pelo qual o acusado aparece verde. Nenhuma delas relaxa
    nada — quem decide o codigo de saida e o `_check`, e continua a ser 2.
    """
    vermelhos = resultado.vermelhos()
    acusados = list(resultado.acusados)
    nunca_vistos = [i for i in acusados if i not in resultado.estado]
    dados_por_verdes = [
        i for i in acusados if resultado.estado.get(i) in VERDE
    ]
    # **Nao e `len(estado)`.** O `estado` leva tambem as frases do
    # `_ErrorHolder`, e duas delas enchiam a conta que dois casos colapsados
    # tinham esvaziado: a hipotese 2 ficava calada e a 3 era anunciada no lugar
    # dela. Achado da revisao adversarial, com um `setUpModule` a levantar
    # `SkipTest`. O `corridos_distintos` conta so o que passou pelo
    # `startTest`, que so recebe casos.
    colapsados = resultado.corridos - resultado.corridos_distintos

    conjuntos = [
        f'TestResult acusa ({len(acusados)}): {acusados[:20]}',
        f'Registo classificou vermelho ({len(vermelhos)}): {vermelhos[:20]}',
        f'acusados que o Registo nao viu comecar: {nunca_vistos[:20]}',
        f'acusados que o Registo deu por verdes: {dados_por_verdes[:20]}',
        f'entradas sem id() de teste: {list(resultado.sem_caso)[:20]}',
        f'corridos={resultado.corridos}, casos distintos iniciados='
        f'{resultado.corridos_distintos}, entradas no estado='
        f'{len(resultado.estado)}',
    ]

    hipoteses: list[str] = []
    if colapsados > 0:
        hipoteses.append(
            f'id() repetido: o testsRun conta {resultado.corridos} e o '
            f'startTest viu {resultado.corridos_distintos} id() distinto(s), '
            f'logo {colapsados} classificacao(oes) colapsaram — a ultima '
            'escrita apagou o vermelho de quem partilha o id().'
        )
    if nunca_vistos:
        hipoteses.append(
            'sinal do unittest que o Registo nao derruba: '
            f'{nunca_vistos[:20]} entrou(entraram) no TestResult sem nunca '
            'passar pelo startTest. E a classe do addSubTest, que foi o falso '
            'verde que o KAM-173 mediu; o hook novo e que esta por derrubar.'
        )
    if dados_por_verdes:
        hipoteses.append(
            'classificacao sobrescrita depois de o caso ser acusado: '
            f'{dados_por_verdes[:20]} esta(estao) no TestResult e o Registo '
            'da-o(s) por verde(s). Alguem escreveu por cima a seguir — um '
            'skip de limpeza (o addSkip nao protege um vermelho) ou um '
            'startTest do mesmo id(). Veja-se a linha do id() repetido acima: '
            'se ela estiver la, foi essa a escrita.'
        )
    if vermelhos and not nunca_vistos and not dados_por_verdes:
        hipoteses.append(
            f'nenhuma das tres: o Registo nomeou {vermelhos[:20]} nesta '
            'ordem, e as comparacoes entre as duas ordens nao os cobrem — sao '
            'verdes na outra. Um teste vermelho **so** na ordem de omissao e '
            'dependencia de ordem tanto como o inverso, e o remedio e o mesmo: '
            'quem suja o estado de processo repoe-no.'
        )
    if not hipoteses and resultado.sem_caso:
        hipoteses.append(
            'nenhum id() de teste a nomear: as entradas acusadas nao sao casos '
            f'({list(resultado.sem_caso)[:20]}). Um erro de setUpClass, '
            'tearDownClass, setUpModule ou tearDownModule vem num _ErrorHolder '
            'cujo id() e uma frase, e trata-la como um id() de teste era '
            'inventar um caso que nao existe. A falha e real e esta no relato '
            'abaixo; o que o portao nao consegue e atribui-la a um caso.'
        )
    if not hipoteses:
        hipoteses.append(
            'nenhuma das tres, e o TestResult tambem nao acusa ninguem. E o '
            'unico caso em que o instrumento perdeu mesmo a informacao, e '
            'nao ha nada aqui que a reconstrua: ha um sinal do unittest que '
            'nem o Registo nem o failures/errors/unexpectedSuccesses levam.'
        )
    return conjuntos, hipoteses


def _check(args: argparse.Namespace) -> int:
    raiz = Path(args.root).resolve()
    start_dir = (raiz / args.suite).resolve()
    topo = (raiz / args.topo).resolve() if args.topo else start_dir
    nome = args.nome or args.suite

    if not start_dir.is_dir():
        print(f'ordem_dos_ensaios: {start_dir} nao existe.', file=sys.stderr)
        return 2

    resultados = {}
    for ordem in mod_corredor.ORDENS:
        try:
            resultados[ordem] = _correr_fora(
                start_dir, topo, args.padrao, ordem
            )
        except (RuntimeError, json.JSONDecodeError) as erro:
            print(f'ordem_dos_ensaios: {erro}', file=sys.stderr)
            return 2

    for ordem, resultado in resultados.items():
        if resultado.corridos == 0:
            print(
                f'ordem_dos_ensaios: {nome} — nenhum teste foi descoberto na '
                f'ordem {ordem}. Um portao que nao corre nada nao verifica '
                'nada.',
                file=sys.stderr,
            )
            return 2

    normal, inversa = resultados['normal'], resultados['inversa']

    # Os quatro achados sao distintos, e so o primeiro e deste portao.
    # Dizem-se separados porque o remedio de cada um e outro, e um relatorio
    # que os misture manda corrigir a coisa errada — foi o que a revisao
    # adversarial apanhou na primeira versao.
    pela_ordem = sorted(
        i
        for i, estado in inversa.estado.items()
        if estado not in VERDE and normal.estado.get(i) in VERDE
    )
    nas_duas = sorted(
        i
        for i, estado in inversa.estado.items()
        if estado not in VERDE and normal.estado.get(i) not in VERDE
    )
    so_numa = sorted(set(normal.estado) ^ set(inversa.estado))

    if pela_ordem:
        print(
            f'ordem_dos_ensaios: {nome} — {len(pela_ordem)} de '
            f'{inversa.corridos} teste(s) verde(s) na ordem de omissao do '
            'unittest e vermelho(s) na inversa. As duas passagens correram no '
            'mesmo interpretador, sem coverage em nenhuma, e a unica coisa '
            'que difere entre elas e a ordem; logo estes passam por acidente '
            'da ordem de carregamento:',
            file=sys.stderr,
        )
        for identificador in pela_ordem[:20]:
            estado = inversa.estado[identificador]
            print(f'  - {identificador}: ok -> {estado}', file=sys.stderr)
        print(
            '\nA correccao e no teste, nao no portao: o estado de processo que '
            'ele toca (um registo a nivel de modulo, uma variavel de ambiente, '
            'o nivel de um logger com nome, uma entrada do sys.modules) tem de '
            'ser reposto por quem o suja.\n',
            file=sys.stderr,
        )
        if inversa.relato:
            print(inversa.relato[:8000], file=sys.stderr)
        return 1

    if so_numa:
        print(
            f'ordem_dos_ensaios: {nome} — {len(so_numa)} teste(s) existem numa '
            f'passagem e nao na outra ({normal.corridos} contra '
            f'{inversa.corridos} corridos). A descoberta nao e deterministica '
            '— um SkipTest de modulo ou de classe faz desaparecer os testes '
            'que ele cobre —, e sem inventario igual nao ha comparacao que '
            'valha:',
            file=sys.stderr,
        )
        for identificador in so_numa[:20]:
            onde = 'so na ordem de omissao' if identificador in normal.estado \
                else 'so na ordem inversa'
            print(f'  - {identificador}: {onde}', file=sys.stderr)
        return 1

    if nas_duas:
        # Nao e achado deste portao — o `coverage-python` ja o devia ter
        # apanhado —, mas calar-se aqui dava a entender que a suite esta verde.
        print(
            f'ordem_dos_ensaios: {nome} — {len(nas_duas)} teste(s) '
            'vermelho(s) nas **duas** ordens. Nao e dependencia de ordem: e '
            'um teste quebrado, e o lugar de o apanhar e o coverage-python:',
            file=sys.stderr,
        )
        for identificador in nas_duas[:20]:
            print(
                f'  - {identificador}: {inversa.estado[identificador]}',
                file=sys.stderr,
            )
        if inversa.relato:
            print('\n' + inversa.relato[:8000], file=sys.stderr)
        return 1

    # A rede, e e a parte que nao se pode tirar. O `estado` e um dicionario com
    # perdas (ver o `corredor`); o `wasSuccessful()` vem do proprio
    # `TestResult`. Se os dois discordarem, isso e falha do instrumento a
    # atribuir — nunca verde da suite. Sem esta verificacao, um sinal do
    # `unittest` que ninguem derrube volta a dar falso verde, que foi o que
    # aconteceu com o `addSubTest` e os seus 332 usos.
    #
    # Ate ao KAM-182 este comentario e a mensagem diziam que o instrumento
    # «perdeu informacao», e isso era falso na maioria dos casos: a informacao
    # estava no `failures`/`errors` do `TestResult`. Hoje o `_atribuir` le-a.
    discordam = [
        ordem
        for ordem, resultado in resultados.items()
        if not resultado.sucesso
    ]
    if discordam:
        # **Nomear, e nao deixar passar** (KAM-182). Ate aqui esta mensagem
        # dizia que o instrumento perdeu a informacao — e a informacao estava
        # no processo: o `relato` impresso logo a seguir tinha o nome e o
        # *traceback*. Agora os dois lados saem lado a lado e a diferenca entre
        # eles nomeia a hipotese. O que **nao** muda e o veredicto: o codigo de
        # saida e 2 nos dois casos, com nome e sem nome, porque um corredor que
        # nomeie melhor mas de verde quando nao sabe e pior do que o de antes.
        print(
            f'ordem_dos_ensaios: {nome} — o unittest diz que a(s) ordem(ns) '
            f'{", ".join(discordam)} NAO passaram, e as comparacoes entre as '
            'duas ordens nao apanharam nenhum vermelho. Isto e falha do '
            'portao a atribuir a falha, nao verde da suite: o veredicto vem '
            'do wasSuccessful() do TestResult e nao do dicionario do Registo. '
            'Os dois lados, lado a lado:',
            file=sys.stderr,
        )
        sem_nome = []
        for ordem in discordam:
            resultado = resultados[ordem]
            conjuntos, hipoteses = _atribuir(resultado)
            if not resultado.acusados and not resultado.vermelhos():
                sem_nome.append(ordem)
            print(
                f'  - {ordem}: corridos={resultado.corridos}, '
                f'classificados={len(resultado.estado)}, '
                f'sucesso={resultado.sucesso}',
                file=sys.stderr,
            )
            for linha in conjuntos:
                print(f'      {linha}', file=sys.stderr)
            for hipotese in hipoteses:
                print(f'      hipotese: {hipotese}', file=sys.stderr)
            if resultado.relato:
                print(resultado.relato[:4000], file=sys.stderr)
        if sem_nome:
            # A segunda metade do critério 2 do KAM-182, e esteve em falta por
            # uma versao: quando nem o `TestResult` nomeia um caso, a mensagem
            # tem de **continuar a dizer que a falha e do portao** e nao so a
            # sair com 2. Achado da revisao adversarial.
            print(
                f'\nNa(s) ordem(ns) {", ".join(sem_nome)} nem o TestResult '
                'nomeia um caso: a falha e do portao, nao da suite, e '
                'corrige-se no corredor. O codigo de saida e 2 na mesma — '
                'recusar o verde quando nao se sabe nao e negociavel.',
                file=sys.stderr,
            )
        return 2

    print(
        f'ordem_dos_ensaios: {nome} — {normal.corridos} testes nas duas '
        'ordens, 0 mudancas de resultado'
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
    """O filho: corre uma ordem e escreve o resultado."""
    resultado = mod_corredor.correr(
        args.suite, args.topo, args.padrao, args.ordem
    )
    Path(args.saida).write_text(
        json.dumps(
            {
                'estado': resultado.estado,
                'corridos': resultado.corridos,
                'sucesso': resultado.sucesso,
                'relato': resultado.relato[:20000],
                'corridos_distintos': resultado.corridos_distintos,
                'acusados': list(resultado.acusados),
                'sem_caso': list(resultado.sem_caso),
            },
            indent=0,
            sort_keys=True,
        ),
        encoding='utf-8',
    )
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
