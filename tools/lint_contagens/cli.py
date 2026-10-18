"""Interface de linha de comando do `lint_contagens`.

    python -m lint_contagens check [--root .]   falha se uma contagem nao bater
    python -m lint_contagens censo [--root .]   imprime as fontes e a populacao
    python -m lint_contagens file <ficheiro>    varre um ficheiro (para depurar)

Codigo de saida 0 = conforme, 1 = contagem errada, 2 = erro de configuracao. A
distincao importa: uma arvore que nao se encontrou nao pode parecer limpa.

Duas listas em `ci/contagens-allow.yaml`, e a diferenca entre elas e de fundo:

- **`excepcoes`** sao linhas em que o numero **esta certo** por nao ser uma
  contagem do conjunto: a citacao de um defeito passado («o `INDICE.md` ainda
  descreve 12 ADRs»), ou a descricao do conteudo de outro documento. Nao tem
  prazo, porque nao ha nada para corrigir.
- **`dividas`** sao contagens **erradas** que pertencem a outro ticket. Tem dono
  e `expira_em`, e a partir dessa data o gate falha. Sem prazo era uma amnistia.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import sys
from pathlib import Path
from typing import NamedTuple

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

#: As chaves de `ci/contagens-allow.yaml` que este leitor conhece (KAM-134). A
#: `version` esta no ficheiro e ninguem a le; declara-se para que a recusa nao
#: a apanhe.
_CHAVES = {'version', 'excepcoes', 'dividas'}

#: As chaves de cada divida. Todas lidas (KAM-134): declarar uma e nao a ler
#: seria instanciar de novo o defeito que este ticket fecha.
_CHAVES_DE_DIVIDA = {
    'ficheiro', 'grandeza', 'escrito', 'ocorrencias', 'origem',
    'criado_em', 'expira_em', 'razao',
}

#: Quanto tempo uma divida de contagem pode viver, contado **da criacao**.
#: *Proposta*, a calibrar: e o mesmo valor que o `ci/waivers.yaml` usa para as
#: excepcoes do pipeline, e pela mesma razao.
PRAZO_MAXIMO = datetime.timedelta(days=31)

from . import fontes as mod_fontes
from .scan import PADROES, Achado, ficheiros, varrer_arvore, varrer_ficheiro

#: Onde vivem as declaracoes, relativo a raiz.
ALLOW = 'ci/contagens-allow.yaml'

#: Quantas contagens vivas se espera encontrar, no minimo. **Escrito a mao, de
#: proposito**, como o `esperados=N` do resumo do KAM-002: se uma alteracao ao
#: delimitador ou aos padroes fizer a varredura deixar de ver a populacao, o
#: gate tem de falhar em vez de dizer «conforme» sobre o vazio. Sobe-se quando a
#: populacao sobe, e isso e uma decisao, nao um efeito.
#:
#: Medido a 2026-10-16 sobre `main`: **15** contagens vivas (7 de tickets, 5 de
#: ADRs, 3 de epics) depois de as 18 excepcoes declaradas saltarem as suas
#: linhas — eram 40 antes delas. O minimo fica em **10**: da folga para um
#: ticket retirar prosa sem o gate morder, e nao da folga para a varredura
#: deixar de ver um terco da populacao.
MINIMO_ESPERADO = 10


class Divida(NamedTuple):
    """Uma contagem errada que e de **outro** ticket, com dono e prazo."""

    ficheiro: str
    grandeza: str
    escrito: int
    ocorrencias: int
    origem: str
    criado_em: datetime.date
    expira_em: datetime.date
    razao: str

    def cobre(self, achado: Achado) -> bool:
        return (achado.ficheiro == self.ficheiro
                and achado.grandeza == self.grandeza
                and achado.escrito == self.escrito)


class ConfiguracaoInvalida(Exception):
    """A lista nao se pode ler, ou nao diz o que promete."""


def _data(valor, onde: str) -> datetime.date:
    if isinstance(valor, datetime.date):
        return valor
    if isinstance(valor, str):
        try:
            return datetime.date.fromisoformat(valor.strip())
        except ValueError as e:
            raise ConfiguracaoInvalida(f'{onde}: data invalida {valor!r}') from e
    raise ConfiguracaoInvalida(f'{onde}: falta a data')


def ler_declaracoes(raiz: Path) -> tuple[tuple[str, ...], tuple[Divida, ...]]:
    """`(excertos das excepcoes, dividas)` de `ci/contagens-allow.yaml`.

    A ausencia do ficheiro e legitima e significa «nada declarado». Um ficheiro
    ilegivel, ou uma entrada sem razao, **nao** e: uma declaracao sem razao
    escrita e uma declaracao que ninguem pode revogar.
    """
    f = raiz / ALLOW
    if not f.is_file():
        return (), ()
    try:
        dados = load_file(f)
    except (YamlSubsetError, OSError) as e:
        raise ConfiguracaoInvalida(f'{ALLOW}: {e}') from e
    exigir_chaves(dados, _CHAVES, ALLOW, erro=ConfiguracaoInvalida)

    excepcoes: list[str] = []
    for i, e in enumerate(dados.get('excepcoes') or [], 1):
        exigir_chaves(
            e, {'excerto', 'razao'}, f'{ALLOW}: a excepcao {i}',
            erro=ConfiguracaoInvalida,
        )
        excerto, razao = e.get('excerto'), e.get('razao')
        if not isinstance(excerto, str) or not excerto.strip():
            raise ConfiguracaoInvalida(f'{ALLOW}: a excepcao {i} nao tem `excerto`')
        if not isinstance(razao, str) or not razao.strip():
            raise ConfiguracaoInvalida(
                f'{ALLOW}: a excepcao {i} ({excerto!r}) nao tem `razao`')
        excepcoes.append(excerto)

    dividas: list[Divida] = []
    for i, d in enumerate(dados.get('dividas') or [], 1):
        onde = f'{ALLOW}: a divida {i}'
        exigir_chaves(d, _CHAVES_DE_DIVIDA, onde, erro=ConfiguracaoInvalida)
        for chave in ('ficheiro', 'grandeza', 'escrito', 'ocorrencias', 'origem',
                      'criado_em', 'expira_em', 'razao'):
            if not d.get(chave) and d.get(chave) != 0:
                raise ConfiguracaoInvalida(f'{onde} nao tem `{chave}`')
        if d['grandeza'] not in PADROES:
            raise ConfiguracaoInvalida(
                f'{onde}: grandeza desconhecida {d["grandeza"]!r}; '
                f'as declaradas sao {", ".join(PADROES)}')
        try:
            escrito = int(d['escrito'])
        except (TypeError, ValueError) as e:
            raise ConfiguracaoInvalida(f'{onde}: `escrito` nao e um numero') from e
        try:
            quantas = int(d['ocorrencias'])
        except (TypeError, ValueError) as e:
            raise ConfiguracaoInvalida(f'{onde}: `ocorrencias` nao e um numero') from e
        criado_em = _data(d['criado_em'], f'{onde}: `criado_em`')
        expira_em = _data(d['expira_em'], f'{onde}: `expira_em`')
        # O `criado_em` **e lido**, e e isto que o torna util (KAM-134): sem
        # esta conta, prolongar uma divida era empurrar o `expira_em` e mais
        # nada — um *diff* de um caractere, sem decisao nova e sem dono novo.
        # E o mesmo defeito que o KAM-135 vai fechar nos *waivers*.
        if expira_em < criado_em:
            raise ConfiguracaoInvalida(
                f'{onde}: `expira_em` ({expira_em}) e anterior a `criado_em` '
                f'({criado_em})')
        if expira_em - criado_em > PRAZO_MAXIMO:
            raise ConfiguracaoInvalida(
                f'{onde}: o prazo e de {(expira_em - criado_em).days} dias, e o '
                f'maximo sao {PRAZO_MAXIMO.days} contados da criacao. Prolongar '
                'uma divida exige mexer no `criado_em` — ou seja, uma decisao '
                'nova, que se le no diff.')
        dividas.append(Divida(
            ficheiro=str(d['ficheiro']), grandeza=str(d['grandeza']), escrito=escrito,
            ocorrencias=quantas, origem=str(d['origem']),
            criado_em=criado_em, expira_em=expira_em, razao=str(d['razao']),
        ))
    return tuple(excepcoes), tuple(dividas)


def excepcoes_mortas(raiz: Path, excepcoes: tuple[str, ...]) -> list[str]:
    """As excepcoes que nao casam nenhuma linha de nenhum ficheiro varrido.

    Uma excepcao esquecida continua a abrir uma porta que ninguem vigia.
    """
    vivas: set[str] = set()
    for f in ficheiros(raiz):
        texto = f.read_text(encoding='utf-8')
        for e in excepcoes:
            if e in texto:
                vivas.add(e)
    return [e for e in excepcoes if e not in vivas]


def _censo(fontes: mod_fontes.Fontes, achados: list[Achado], destino) -> None:
    print('fontes contaveis:', file=destino)
    comandos = fontes.comandos()
    for nome, valor in (('tickets', fontes.tickets), ('blocos', fontes.blocos),
                        ('ADRs', fontes.adrs), ('ADRs locais', fontes.adrs_locais),
                        ('anexos', fontes.anexos), ('epics', fontes.epics)):
        print(f'  {nome:12} {valor:4}   {comandos[nome]}', file=destino)
    print('\nblocos por epic:', file=destino)
    for epic, n in sorted(fontes.por_epic.items()):
        print(f'  {epic} {n:4}', file=destino)
    por = collections.Counter(a.grandeza for a in achados)
    print('\ncontagens vivas encontradas:', file=destino)
    for grandeza in PADROES:
        print(f'  {grandeza:12} {por[grandeza]:4}', file=destino)
    print(f'  {"TOTAL":12} {len(achados):4}', file=destino)


def main(argv: list[str] | None = None) -> int:
    # Este anfitriao escreve em cp1252, e um excerto de linha com acentos
    # matava o guiao com `UnicodeEncodeError` **depois** de ele ja ter dito que
    # havia erros — a saida mais inutil possivel.
    for canal in (sys.stdout, sys.stderr):
        if hasattr(canal, 'reconfigure'):
            canal.reconfigure(encoding='utf-8', errors='replace')

    p = argparse.ArgumentParser(
        prog='lint_contagens',
        description='Contagens escritas em prosa, confrontadas com a fonte contavel.',
    )
    p.add_argument('--root', default='.', help='raiz do repositorio (por omissao, o cwd)')
    p.add_argument('--hoje', default=None, metavar='AAAA-MM-DD',
                   help='data a usar para os prazos das dividas (para testes)')
    sub = p.add_subparsers(dest='acao', required=True)
    sub.add_parser('check', help='falha se uma contagem nao bater com a fonte')
    sub.add_parser('censo', help='imprime as fontes e a populacao encontrada')
    pf = sub.add_parser('file', help='varre um ficheiro')
    pf.add_argument('ficheiro')
    a = p.parse_args(argv)

    raiz = Path(a.root).resolve()
    if not raiz.is_dir():
        print(f'lint_contagens: raiz inexistente: {raiz}', file=sys.stderr)
        return 2
    try:
        hoje = (datetime.date.fromisoformat(a.hoje) if a.hoje
                else datetime.date.today())
    except ValueError:
        print(f'lint_contagens: --hoje invalido: {a.hoje!r}', file=sys.stderr)
        return 2
    try:
        excepcoes, dividas = ler_declaracoes(raiz)
    except ConfiguracaoInvalida as e:
        print(f'lint_contagens: {e}', file=sys.stderr)
        return 2
    try:
        fontes = mod_fontes.ler(raiz)
    except OSError as e:
        print(f'lint_contagens: nao consegui ler uma fonte: {e}', file=sys.stderr)
        return 2

    if a.acao == 'file':
        f = Path(a.ficheiro)
        f = f if f.is_absolute() else (raiz / f)
        if not f.is_file():
            print(f'lint_contagens: ficheiro inexistente: {f}', file=sys.stderr)
            return 2
        achados = varrer_ficheiro(f.resolve(), raiz, fontes, excepcoes)
        for x in achados:
            print(f'{"ok  " if x.bate else "ERRO"} {x}')
        return 0 if all(x.bate for x in achados) else 1

    achados = varrer_arvore(raiz, fontes, excepcoes)

    if a.acao == 'censo':
        _censo(fontes, achados, sys.stdout)
        return 0

    # A guarda do «nao pode passar sobre zero»: uma varredura que deixou de ver
    # a populacao nao e uma arvore limpa.
    # Cada grandeza declarada tem de aparecer. Uma grandeza que deixe de casar
    # nada e um padrao que apodreceu em silencio — e isso nao se ve no total.
    por_grandeza = collections.Counter(x.grandeza for x in achados)
    vazias = [g for g in PADROES if not por_grandeza[g]]
    if vazias:
        print(f'lint_contagens: {len(vazias)} grandeza(s) declarada(s) sem uma unica '
              f'ocorrencia: {", ".join(vazias)}. Um padrao que deixa de casar nada nao '
              'protege nada, e nao se ve no total. Corrige o padrao, ou tira a grandeza '
              'de PADROES e escreve porque.', file=sys.stderr)
        return 2

    if len(achados) < MINIMO_ESPERADO:
        print(f'lint_contagens: encontrei {len(achados)} contagem(ns) viva(s), e esperam-se '
              f'pelo menos {MINIMO_ESPERADO}. Ou o delimitador das zonas de historia ou os '
              'padroes deixaram de ver a populacao — e «conforme» sobre o vazio e a falha '
              'que este gate existe para recusar. Se a populacao mudou de verdade, baixa o '
              '`MINIMO_ESPERADO` e diz porque no commit.', file=sys.stderr)
        return 2

    mortas = excepcoes_mortas(raiz, excepcoes)
    if mortas:
        print(f'lint_contagens: {len(mortas)} excepcao(oes) de {ALLOW} nao casam nenhuma '
              'linha:', file=sys.stderr)
        for e in mortas:
            print(f'  - {e!r}', file=sys.stderr)
        print('Uma excepcao esquecida continua a abrir uma porta que ninguem vigia: '
              'apaga-a ou corrige o excerto.', file=sys.stderr)
        return 2

    maus = [x for x in achados if not x.bate]
    cobertos: list[tuple[Achado, Divida]] = []
    sobram: list[Achado] = []
    usadas: set[Divida] = set()
    for x in maus:
        divida = next((d for d in dividas if d.cobre(x)), None)
        if divida is None:
            sobram.append(x)
        else:
            cobertos.append((x, divida))
            usadas.add(divida)

    # Uma divida que nao cobre nada ja foi paga, e a declaracao ficou: e a mesma
    # mentira de uma excepcao esquecida.
    # Uma divida que cobre mais ocorrencias do que declara esta a tapar algo que
    # ninguem viu — e e por isso que o numero se escreve.
    quantas_cobre: dict[Divida, int] = collections.Counter(d for _, d in cobertos)
    descontadas = [(d, quantas_cobre[d]) for d in dividas
                   if d in usadas and quantas_cobre[d] != d.ocorrencias]
    if descontadas:
        print(f'lint_contagens: {len(descontadas)} divida(s) com `ocorrencias` errado:',
              file=sys.stderr)
        for d, quantas in descontadas:
            print(f'  - {d.ficheiro}: {d.grandeza} = {d.escrito} declara {d.ocorrencias} '
                  f'e cobre {quantas}', file=sys.stderr)
        return 2

    pagas = [d for d in dividas if d not in usadas]
    if pagas:
        print(f'lint_contagens: {len(pagas)} divida(s) de {ALLOW} nao cobrem nenhuma '
              'contagem errada — foram pagas e a declaracao ficou:', file=sys.stderr)
        for d in pagas:
            print(f'  - {d.ficheiro}: {d.grandeza} = {d.escrito} ({d.origem})',
                  file=sys.stderr)
        return 2

    vencidas = [(x, d) for x, d in cobertos if d.expira_em < hoje]
    if vencidas:
        print(f'lint_contagens: {len(vencidas)} divida(s) vencida(s):', file=sys.stderr)
        for x, d in vencidas:
            print(f'  - {x} — declarada por {d.origem}, venceu a '
                  f'{d.expira_em.isoformat()}', file=sys.stderr)
        return 1

    if sobram:
        comandos = fontes.comandos()
        print(f'lint_contagens: {len(sobram)} contagem(ns) que nao batem com a fonte, em '
              f'{len({x.ficheiro for x in sobram})} ficheiro(s):')
        for x in sobram:
            print(f'  - {x}')
            print(f'      {x.excerto}')
            print(f'      reproduz: {comandos.get(x.grandeza, "—")}')
        print(f'\nUma contagem escreve-se a partir da fonte, nao de outro documento '
              f'(KAM-130). Se o numero for a citacao de um defeito passado, declara-o em '
              f'{ALLOW} como `excepcao`, com a razao; se for uma contagem errada que '
              'pertence a outro ticket, declara-o como `divida`, com dono e prazo.')
        return 1

    por = collections.Counter(x.grandeza for x in achados)
    resumo = ', '.join(f'{por[g]} de {g}' for g in PADROES if por[g])
    print(f'lint_contagens: conforme — {len(achados)} contagem(ns) viva(s) '
          f'({resumo}) em {len({x.ficheiro for x in achados})} ficheiro(s); '
          f'{len(excepcoes)} excepcao(oes) e {len(dividas)} divida(s) declarada(s). '
          f'Fontes: {fontes.tickets} tickets, {fontes.blocos} blocos, {fontes.adrs} ADRs, '
          f'{fontes.anexos} anexos, {fontes.epics} epics.')
    if dividas:
        primeira = min(d.expira_em for d in dividas)
        print(f'  ATENCAO: {len(dividas)} divida(s) declarada(s); a primeira vence a '
              f'{primeira.isoformat()} e a partir dai o gate falha.')
    return 0
