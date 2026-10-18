"""Interface de linha de comando do `lint_backlog` (gate 3c). KAM-138.

    python -m lint_backlog check [--root .]   falha se as superficies discordarem
    python -m lint_backlog censo [--root .]   imprime o que leu, e quanto

Codigo de saida 0 = conforme, 1 = achados, 2 = erro de configuracao. A distincao
importa, e aqui mais do que nos irmaos: um lint de coerencia que de verde por
nao ter conseguido ler o backlog e o modo de falha que ele existe para nao ter.

**Duas verificacoes nascem como aviso, e a escolha esta escrita.** As inversoes
de prioridade e de fase, e o controlo de versoes, tem estado inicial sujo. Em
vez de nascerem desligadas — que era nao verificar nada — nascem a **avisar**,
com o estado conhecido declarado em `ci/backlog-allow.yaml` com razao por
entrada. Uma inversao ou um documento que **nao** esteja declarado falha desde
o primeiro dia, e quando a lista esvaziar deixa de haver aviso nenhum: o gate
passa a falha sem ninguem mexer no codigo. Uma declaracao que deixe de casar
alguma coisa **falha** (codigo 2), como nos irmaos — uma excepcao esquecida
continua a abrir uma porta que ninguem vigia.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from kamba_yaml import YamlSubsetError, exigir_chaves, load_file

from . import modelo, versoes
from .modelo import Backlog, BacklogIlegivel, normalizar_titulo

#: Onde vivem as declaracoes, relativo a raiz.
ALLOW = 'ci/backlog-allow.yaml'

#: As chaves de `ci/backlog-allow.yaml` que este leitor conhece (KAM-134).
#: Todas lidas: declarar uma e nao a ler era instanciar de novo o defeito que o
#: KAM-134 fechou nos outros catorze leitores.
CHAVES = {'version', 'inversoes', 'sequencias', 'cabecalhos'}
#: Cada declaracao tem dono (`origem`), razao, e **prazo**. O prazo nao estava
#: na primeira versao, e a revisao adversarial mostrou o que isso custava: dos
#: 25 documentos com campo de versao, 24 estavam dispensados e o unico que
#: passava tem uma so linha de historico — a verificacao nao validava **um
#: unico** documento com emendas, e sem prazo nunca viria a validar. «Passa a
#: falha quando a lista esvaziar» so e um compromisso se houver uma data em que
#: a lista tem de estar vazia.
_PRAZO = {'criado_em', 'expira_em'}
CHAVES_DE_INVERSAO = {'de', 'para', 'genero', 'origem', 'razao'} | _PRAZO
CHAVES_DE_SEQUENCIA = {'ficheiro', 'falta', 'origem', 'razao'} | _PRAZO
CHAVES_DE_CABECALHO = {'ficheiro', 'origem', 'razao'} | _PRAZO

#: Quanto tempo uma declaracao pode viver, contado **da criacao**. E o mesmo
#: valor e a mesma conta do `ci/contagens-allow.yaml` (KAM-158), e pela mesma
#: razao: sem a conta, prolongar uma dispensa era empurrar o `expira_em` e mais
#: nada — um *diff* de um caractere, sem decisao nova e sem dono novo.
PRAZO_MAXIMO = datetime.timedelta(days=31)

#: Uma razao mais curta do que isto nao se compreende daqui a seis meses. E o
#: mesmo limiar do `lint_refs`, e pela mesma razao.
RAZAO_MINIMA = 30

#: Ordem das prioridades. Um P0 que dependa de um P1 e uma inversao.
ORDEM_DE_PRIORIDADE = {'P0': 0, 'P1': 1, 'P2': 2}

#: Os campos comparados entre a linha do §4 e o bloco. **Seis**, e o titulo e um
#: deles: o §4 e o bloco escrevem-no os dois.
CAMPOS_COMPARADOS = ('titulo', 'tipo', 'estimativa', 'prioridade', 'fase',
                     'dependencias')
#: Os campos comparados com a «Tabela Resumo» do §3. **Cinco**: essa tabela nao
#: tem coluna `Fase`.
CAMPOS_DA_RESUMO = ('titulo', 'tipo', 'estimativa', 'prioridade', 'dependencias')

#: Travessoes que o conjunto usa num intervalo `KAM-001 – KAM-012`.
_TRACOS = r'[–—-]'
_INTERVALO = re.compile(rf'KAM-(\d{{3}})\s*{_TRACOS}\s*KAM-(\d{{3}})')
_SOLTO = re.compile(r'KAM-(\d{3})')


class ConfiguracaoInvalida(Exception):
    """A lista de declaracoes nao se le, ou nao diz o que promete."""


@dataclass(frozen=True)
class ComPrazo:
    """O que as tres declaracoes partilham: dono, razao e data de validade."""

    origem: str
    razao: str
    criado_em: datetime.date
    expira_em: datetime.date

    def vencida(self, hoje: datetime.date) -> bool:
        return self.expira_em < hoje


@dataclass(frozen=True)
class Inversao(ComPrazo):
    de: str = ''
    para: str = ''
    genero: str = ''

    def cobre(self, de: str, para: str, genero: str) -> bool:
        return (self.de, self.para, self.genero) == (de, para, genero)

    def __str__(self) -> str:
        return f'a inversao {self.de} → {self.para} ({self.genero})'


@dataclass(frozen=True)
class Sequencia(ComPrazo):
    ficheiro: str = ''
    falta: str = ''

    def __str__(self) -> str:
        return f'o buraco {self.falta} de {self.ficheiro}'


@dataclass(frozen=True)
class Cabecalho(ComPrazo):
    ficheiro: str = ''

    def __str__(self) -> str:
        return f'o cabecalho de {self.ficheiro}'


@dataclass(frozen=True)
class Declaracoes:
    inversoes: tuple[Inversao, ...] = ()
    sequencias: tuple[Sequencia, ...] = ()
    cabecalhos: tuple[Cabecalho, ...] = ()

    def __len__(self) -> int:
        return len(self.inversoes) + len(self.sequencias) + len(self.cabecalhos)

    def todas(self) -> tuple[ComPrazo, ...]:
        return self.inversoes + self.sequencias + self.cabecalhos


def _texto(entrada: dict, chave: str, onde: str) -> str:
    valor = entrada.get(chave)
    if not isinstance(valor, str) or not valor.strip():
        raise ConfiguracaoInvalida(f'{onde} nao tem `{chave}`')
    return valor.strip()


def _razao(entrada: dict, onde: str) -> str:
    razao = _texto(entrada, 'razao', onde)
    if len(razao) < RAZAO_MINIMA:
        raise ConfiguracaoInvalida(
            f'{onde} tem uma razao demasiado curta para alguem a compreender '
            'daqui a seis meses')
    return razao


def _data(valor, onde: str) -> datetime.date:
    if isinstance(valor, datetime.date):
        return valor
    if isinstance(valor, str):
        try:
            return datetime.date.fromisoformat(valor.strip())
        except ValueError as excepcao:
            raise ConfiguracaoInvalida(
                f'{onde}: data invalida {valor!r}') from excepcao
    raise ConfiguracaoInvalida(f'{onde}: falta a data')


def _com_prazo(entrada: dict, onde: str) -> dict:
    """Os quatro campos partilhados, ja validados.

    O `criado_em` **e lido**, e e isso que o torna util: sem a conta contra o
    `PRAZO_MAXIMO`, prolongar uma dispensa era empurrar o `expira_em` e mais
    nada. E a licao do KAM-134 e do KAM-135, aplicada aqui antes de custar.
    """
    criado_em = _data(entrada.get('criado_em'), f'{onde}: `criado_em`')
    expira_em = _data(entrada.get('expira_em'), f'{onde}: `expira_em`')
    if expira_em < criado_em:
        raise ConfiguracaoInvalida(
            f'{onde}: `expira_em` ({expira_em}) e anterior a `criado_em` '
            f'({criado_em})')
    if expira_em - criado_em > PRAZO_MAXIMO:
        raise ConfiguracaoInvalida(
            f'{onde}: o prazo e de {(expira_em - criado_em).days} dias, e o '
            f'maximo sao {PRAZO_MAXIMO.days} contados da criacao. Prolongar uma '
            'dispensa exige mexer no `criado_em` — ou seja, uma decisao nova, '
            'que se le no diff.')
    return {'origem': _texto(entrada, 'origem', onde),
            'razao': _razao(entrada, onde),
            'criado_em': criado_em, 'expira_em': expira_em}


def ler_declaracoes(raiz: Path) -> Declaracoes:
    """As declaracoes de `ci/backlog-allow.yaml`.

    A ausencia do ficheiro e legitima e significa «nada declarado» — e nesse
    estado as duas verificacoes de estado sujo falham, que e o fim a que se
    quer chegar. Um ficheiro ilegivel, ou uma entrada sem razao, **nao** e
    legitimo: uma declaracao sem razao escrita e uma declaracao que ninguem
    pode revogar.
    """
    caminho = raiz / ALLOW
    if not caminho.is_file():
        return Declaracoes()
    try:
        dados = load_file(caminho)
    except (YamlSubsetError, OSError) as excepcao:
        raise ConfiguracaoInvalida(f'{ALLOW}: {excepcao}') from excepcao
    exigir_chaves(dados, CHAVES, ALLOW, erro=ConfiguracaoInvalida)
    if dados.get('version') != 1:
        raise ConfiguracaoInvalida(f'{ALLOW}: `version` tem de ser 1')

    inversoes: list[Inversao] = []
    for indice, entrada in enumerate(dados.get('inversoes') or [], 1):
        onde = f'{ALLOW}: a inversao {indice}'
        exigir_chaves(entrada, CHAVES_DE_INVERSAO, onde, erro=ConfiguracaoInvalida)
        genero = _texto(entrada, 'genero', onde)
        if genero not in ('prioridade', 'fase'):
            raise ConfiguracaoInvalida(
                f'{onde}: `genero` e {genero!r} e so ha dois, `prioridade` e `fase`')
        inversoes.append(Inversao(
            de=_texto(entrada, 'de', onde), para=_texto(entrada, 'para', onde),
            genero=genero, **_com_prazo(entrada, onde)))

    sequencias: list[Sequencia] = []
    for indice, entrada in enumerate(dados.get('sequencias') or [], 1):
        onde = f'{ALLOW}: a sequencia {indice}'
        exigir_chaves(entrada, CHAVES_DE_SEQUENCIA, onde, erro=ConfiguracaoInvalida)
        sequencias.append(Sequencia(
            ficheiro=_texto(entrada, 'ficheiro', onde),
            falta=_texto(entrada, 'falta', onde), **_com_prazo(entrada, onde)))

    cabecalhos: list[Cabecalho] = []
    for indice, entrada in enumerate(dados.get('cabecalhos') or [], 1):
        onde = f'{ALLOW}: o cabecalho {indice}'
        exigir_chaves(entrada, CHAVES_DE_CABECALHO, onde, erro=ConfiguracaoInvalida)
        cabecalhos.append(Cabecalho(
            ficheiro=_texto(entrada, 'ficheiro', onde),
            **_com_prazo(entrada, onde)))

    return Declaracoes(tuple(inversoes), tuple(sequencias), tuple(cabecalhos))


# --------------------------------------------------------------------------
# As verificacoes. Cada uma devolve uma lista de achados em texto; nenhuma
# decide o codigo de saida, e nenhuma corrige nada.
# --------------------------------------------------------------------------

def sincronia(backlog: Backlog) -> list[str]:
    """Campo a campo, entre a linha do §4 e o bloco.

    O gate **nao** decide qual dos dois esta certo: imprime os dois valores e
    falha. O §4 e o contrato entre epics e o bloco e a especificacao; qual
    deles se corrige e de quem escreveu o ticket.
    """
    achados: list[str] = []
    for identificador in sorted(set(backlog.linhas) & set(backlog.blocos)):
        linha, bloco = backlog.linhas[identificador], backlog.blocos[identificador]
        for campo in CAMPOS_COMPARADOS:
            do_indice = getattr(linha, campo)
            do_bloco = bloco.titulo if campo == 'titulo' else bloco.campo(campo)
            if campo == 'titulo':
                iguais = normalizar_titulo(do_indice) == normalizar_titulo(do_bloco)
            else:
                iguais = do_indice == do_bloco
            if not iguais:
                achados.append(
                    f'{identificador}: `{campo}` diverge — '
                    f'{modelo.INDICE}:{linha.numero} diz {do_indice!r}, '
                    f'{bloco.onde} diz {do_bloco!r}')
    return achados


def orfaos(backlog: Backlog) -> list[str]:
    """Nos dois sentidos: linha sem bloco, e bloco sem linha."""
    achados: list[str] = []
    for identificador in sorted(set(backlog.linhas) - set(backlog.blocos)):
        linha = backlog.linhas[identificador]
        achados.append(
            f'{identificador}: tem linha em {modelo.INDICE}:{linha.numero} e nao '
            f'tem bloco `## {identificador} — ` em {modelo.TICKETS}/ nem em '
            f'nenhum epic')
    for identificador in sorted(set(backlog.blocos) - set(backlog.linhas)):
        bloco = backlog.blocos[identificador]
        achados.append(
            f'{identificador}: tem bloco em {bloco.onde} e nao tem linha no §4 '
            f'de {modelo.INDICE} — o §4 e o universo, e o gate 3 le-o de la')
    return achados


def terceira_superficie(backlog: Backlog) -> list[str]:
    """A «Tabela Resumo de Tickets» do §3 de cada epic contra o §4.

    E a superficie que ninguem compara e que por isso apodrece primeiro: antes
    do KAM-155 esta tabela do EPIC-01 tinha 36 linhas para 39 blocos, e o
    defeito viveu ali meses sem ninguem o ver.
    """
    achados: list[str] = []
    for epic in backlog.epics:
        esperados = backlog.por_epic.get(epic, [])
        resumos = {r.id: r for r in backlog.resumos.get(epic, [])}
        for identificador in esperados:
            resumo = resumos.get(identificador)
            if resumo is None:
                ficheiro = next((r.ficheiro for r in backlog.resumos.get(epic, [])),
                                epic)
                achados.append(
                    f'{identificador}: esta no §4 sob {epic} e nao tem linha na '
                    f'«Tabela Resumo de Tickets» do §3 de {ficheiro}')
                continue
            linha = backlog.linhas[identificador]
            # A ligacao tem de apontar ao ticket que a linha nomeia. Sem isto,
            # `[KAM-154](tickets/KAM-003.md)` passava nos dois gates: o 3 ve um
            # identificador que existe e um caminho que resolve, e o 3c via o
            # identificador certo. E o achado m2 da revisao adversarial.
            if resumo.destino is not None:
                esperado = f'{identificador}.md'
                if not resumo.destino.endswith(esperado):
                    achados.append(
                        f'{identificador}: a linha do §3 em {resumo.ficheiro}:'
                        f'{resumo.numero} liga a {resumo.destino!r}, que nao e o '
                        f'ficheiro deste ticket ({esperado})')
            for campo in CAMPOS_DA_RESUMO:
                do_indice, do_resumo = getattr(linha, campo), getattr(resumo, campo)
                iguais = (normalizar_titulo(do_indice) == normalizar_titulo(do_resumo)
                          if campo == 'titulo' else do_indice == do_resumo)
                if not iguais:
                    achados.append(
                        f'{identificador}: `{campo}` diverge entre o §4 e o §3 — '
                        f'{modelo.INDICE}:{linha.numero} diz {do_indice!r}, '
                        f'{resumo.ficheiro}:{resumo.numero} diz {do_resumo!r}')
        for identificador, resumo in sorted(resumos.items()):
            if identificador not in esperados:
                achados.append(
                    f'{identificador}: tem linha no §3 de {resumo.ficheiro}:'
                    f'{resumo.numero} e nao pertence a {epic} no §4')
    return achados


#: Um ticket. **Exactamente** tres digitos: `KAM-19` e `KAM019` nao sao tickets
#: deste conjunto, sao gralhas.
_TICKET = re.compile(r'KAM-\d{3}')
#: Uma decisao aberta do §13.3 da arquitectura, a unica forma externa que nao e
#: um ticket. Medido sobre `main`: as entradas `ext:` do conjunto sao `ext:D6` e
#: `ext:KAM-{069,100,101,102,103,104,105}`, e mais nenhuma.
_DECISAO = re.compile(r'D\d{1,2}')

#: As formas que uma entrada de `Dependencias` ou de `Bloqueia` pode ter. A
#: lista e fechada, e e isso que a torna util: ver a lista acima.
FORMAS_ACEITES = '`KAM-NNN`, `ext:KAM-NNN` ou `ext:D#`'


class Aresta(NamedTuple):
    """Uma entrada de `Dependencias` ou de `Bloqueia`, ja classificada.

    Tres estados, e o terceiro e o que faltava: **malformada**. Ate ao KAM-138
    ter sido revisto, o ramo das dependencias fazia `continue` sobre tudo o que
    nao reconhecia, enquanto o ramo do `Bloqueia`, vinte linhas abaixo,
    reportava — a assimetria provava que era lapso e nao decisao.

    **O que o silencio custava, medido.** Escrita coerentemente nas tres
    superficies, que e como uma gralha viaja (copia-se a celula), qualquer de
    `KAM-19`, `kam-019`, `KAM019`, `Kam-019`, `ext:kam-019` ou `XPTO-1` dava
    conforme no 3c **e** conforme no gate 3: uma aresta que existe em prosa,
    esta coerente em todo o lado, e e invisivel a reciprocidade, aos ciclos e
    as inversoes. `KAM-19` e a gralha mais provavel que ha neste conjunto, e e
    a classe G5 / KAM-144 que este gate existe para fechar.
    """

    bruto: str
    #: O ticket apontado, ou `None` quando a entrada nao aponta um ticket
    #: (`ext:D6`) ou nao se reconhece.
    alvo: str | None
    #: `True` para as entradas `ext:`, que nao exigem reciprocidade.
    externo: bool
    #: `True` quando a entrada nao tem nenhuma das `FORMAS_ACEITES`.
    malformada: bool


def classificar(valor: str) -> Aresta:
    """`'ext:KAM-102'` -> ticket externo; `'ext:D6'` -> decisao; `'KAM-19'` -> gralha."""
    if valor.startswith('ext:'):
        resto = valor[4:]
        if _TICKET.fullmatch(resto):
            return Aresta(valor, resto, True, False)
        if _DECISAO.fullmatch(resto):
            return Aresta(valor, None, True, False)
        return Aresta(valor, None, True, True)
    if _TICKET.fullmatch(valor):
        return Aresta(valor, valor, False, False)
    return Aresta(valor, None, False, True)


def _gralha(identificador: str, onde: str, campo: str, bruto: str) -> str:
    return (f'{identificador} ({onde}): `{campo}` tem {bruto!r}, que nao e '
            f'{FORMAS_ACEITES}. Uma gralha de identificador **desaparece do '
            'grafo**: a aresta existe em prosa, pode estar coerente nas tres '
            'superficies, e nao existe para a reciprocidade, para os ciclos '
            'nem para as inversoes.')


def malformadas(backlog: Backlog) -> list[str]:
    """Entradas de `Dependencias` e de `Bloqueia` que nao se sabem ler.

    Reporta-se **aqui**, uma vez por entrada, e nao em cada verificacao que a
    encontra: os `ciclos` e as `inversoes` saltam-na em silencio de propósito,
    porque repetir o mesmo achado tres vezes com tres redaccoes diferentes faz
    parecer que sao tres defeitos.
    """
    achados: list[str] = []
    for identificador in sorted(backlog.blocos):
        bloco = backlog.blocos[identificador]
        for campo, entradas in (('Dependências', bloco.deps),
                                ('Bloqueia', bloco.bloqueia)):
            for bruto in entradas:
                if classificar(bruto).malformada:
                    achados.append(
                        _gralha(identificador, bloco.onde, campo, bruto))
    return achados


def reciprocidade(backlog: Backlog) -> list[str]:
    """`Dependencias` e `Bloqueia` sao a mesma aresta vista dos dois lados.

    **E este criterio que distingue o gate de uma comparacao de tabelas.** O §4
    nao tem coluna `Bloqueia`, pelo que a sincronia linha<->bloco nao olha para
    metade do grafo: um ticket que declare `Dependencias | B` sem entrar no
    `Bloqueia` de B satisfaz a sincronia **pela razao errada**. Aconteceu na
    primeira versao do KAM-129 e outra vez em oito tickets, que o KAM-144 teve
    de repor a mao.

    **O `ext:` nao exige reciprocidade, mas satisfaz a do outro lado.**
    `ext:D6` e uma decisao aberta e nao tem bloco nenhum. O `ext:KAM-NNN` e o
    que engana: tem forma de ticket e significa «espera por este, que e externo
    ao codigo» — o KAM-016 depende de `ext:KAM-102`, e exigir que o KAM-102
    tambem o declarasse seria inventar uma aresta de codigo que nao existe. Mas
    quando o KAM-102 **escolhe** declarar `Bloqueia | KAM-016`, o `ext:KAM-102`
    do outro lado fecha a aresta: o contrario obrigava a apagar `Bloqueia` que
    estao certos.
    """
    achados: list[str] = []
    for identificador in sorted(backlog.blocos):
        bloco = backlog.blocos[identificador]
        for bruto in bloco.deps:
            aresta = classificar(bruto)
            # A malformada ja foi reportada por `malformadas`; aqui so se salta.
            if aresta.malformada or aresta.alvo is None:
                continue
            outro = backlog.blocos.get(aresta.alvo)
            if outro is None:
                achados.append(
                    f'{identificador} ({bloco.onde}): declara depender de {bruto} '
                    f'e {aresta.alvo} nao tem bloco nenhum')
                continue
            if aresta.externo:
                continue
            if identificador not in outro.bloqueia:
                achados.append(
                    f'{identificador} depende de {aresta.alvo} e o `Bloqueia` de '
                    f'{aresta.alvo} ({outro.onde}) nao o inclui — a aresta esta '
                    'declarada de um so lado, e o §4 nao tem coluna `Bloqueia` '
                    'para o denunciar')
        for bruto in bloco.bloqueia:
            aresta = classificar(bruto)
            if aresta.malformada or aresta.externo or aresta.alvo is None:
                continue
            outro = backlog.blocos.get(aresta.alvo)
            if outro is None:
                achados.append(
                    f'{identificador} ({bloco.onde}): declara bloquear '
                    f'{aresta.alvo}, que nao tem bloco nenhum')
                continue
            alvos = {classificar(d).alvo for d in outro.deps}
            if identificador not in alvos:
                achados.append(
                    f'{identificador} bloqueia {aresta.alvo} e as `Dependencias` '
                    f'de {aresta.alvo} ({outro.onde}) nao o incluem')
    return achados


def ciclos(backlog: Backlog) -> list[str]:
    """Ciclos no grafo de dependencias, com o caminho completo na mensagem.

    O caminho inteiro e o ponto: dizer «o KAM-042 esta num ciclo» manda procurar
    o resto a mao, e e a mao que estes defeitos escapam.
    """
    cor: dict[str, int] = {}
    caminho: list[str] = []
    encontrados: list[str] = []

    def visitar(no: str) -> None:
        cor[no] = 1
        caminho.append(no)
        bloco = backlog.blocos[no]
        for bruto in bloco.deps:
            # A malformada salta-se **em silencio, e so aqui**: foi reportada
            # por `malformadas`, e um segundo achado sobre o mesmo token faria
            # parecer que sao dois defeitos.
            alvo = classificar(bruto)
            if alvo.malformada or alvo.externo or alvo.alvo is None:
                continue
            alvo = alvo.alvo
            if alvo not in backlog.blocos:
                continue
            if cor.get(alvo) == 1:
                ciclo = caminho[caminho.index(alvo):] + [alvo]
                encontrados.append('ciclo de dependencias: '
                                   + ' → '.join(ciclo))
            elif cor.get(alvo, 0) == 0:
                visitar(alvo)
        caminho.pop()
        cor[no] = 2

    anterior = sys.getrecursionlimit()
    sys.setrecursionlimit(max(anterior, len(backlog.blocos) * 10 + 1000))
    try:
        for no in sorted(backlog.blocos):
            if cor.get(no, 0) == 0:
                visitar(no)
    finally:
        sys.setrecursionlimit(anterior)
    return encontrados


def inversoes(backlog: Backlog) -> list[tuple[str, str, str, str]]:
    """`(de, para, genero, texto)` de cada inversao de prioridade ou de fase."""
    saida: list[tuple[str, str, str, str]] = []
    for identificador in sorted(backlog.blocos):
        bloco = backlog.blocos[identificador]
        for bruto in bloco.deps:
            # Como nos `ciclos`: a malformada ja tem achado proprio.
            aresta = classificar(bruto)
            alvo = aresta.alvo
            if aresta.malformada or aresta.externo or alvo is None:
                continue
            if alvo not in backlog.blocos:
                continue
            outro = backlog.blocos[alvo]
            minha = bloco.campo('prioridade')
            dele = outro.campo('prioridade')
            if (minha in ORDEM_DE_PRIORIDADE and dele in ORDEM_DE_PRIORIDADE
                    and ORDEM_DE_PRIORIDADE[dele] > ORDEM_DE_PRIORIDADE[minha]):
                saida.append((identificador, alvo, 'prioridade',
                              f'{identificador} e {minha} e depende de {alvo}, '
                              f'que e {dele}'))
            try:
                minha_fase, dele_fase = int(bloco.campo('fase')), int(outro.campo('fase'))
            except ValueError:
                continue
            if dele_fase > minha_fase:
                saida.append((identificador, alvo, 'fase',
                              f'{identificador} e da Fase {minha_fase} e depende '
                              f'de {alvo}, que e da Fase {dele_fase}'))
    return saida


def _expandir(intervalo: str) -> set[int]:
    """`'KAM-001 – KAM-003, KAM-111'` -> `{1, 2, 3, 111}`."""
    numeros: set[int] = set()
    resto = intervalo
    for achado in _INTERVALO.finditer(intervalo):
        numeros |= set(range(int(achado.group(1)), int(achado.group(2)) + 1))
        resto = resto.replace(achado.group(0), ' ')
    numeros |= {int(x) for x in _SOLTO.findall(resto)}
    return numeros


def _como_ids(numeros) -> str:
    return ', '.join(f'KAM-{x:03d}' for x in sorted(numeros))


def contagens(backlog: Backlog) -> list[str]:
    """Tudo o que o §3.1 e o §1 declaram, recalculado a partir do §4.

    Uma contagem que nao derive do §4 e uma copia, e uma copia deixa de
    acompanhar: aconteceu quatro vezes antes do `lint_contagens` (KAM-158), que
    fechou a classe na **prosa**. As tabelas sao o outro sitio, e sao estas.
    """
    achados: list[str] = []
    declarados = {entrada.epic: entrada for entrada in backlog.inventario}

    for epic in backlog.epics:
        reais = backlog.por_epic.get(epic, [])
        entrada = declarados.get(epic)
        if entrada is None:
            achados.append(
                f'{epic}: tem {len(reais)} linha(s) no §4 e nao tem linha no §3.1')
            continue
        if entrada.quantos != len(reais):
            achados.append(
                f'{epic}: o §3.1 ({modelo.INDICE}:{entrada.numero}) declara '
                f'{entrada.quantos} ticket(s) e o §4 tem {len(reais)}')
        no_intervalo = _expandir(entrada.intervalo)
        tem = {int(x[4:]) for x in reais}
        fora = tem - no_intervalo
        a_mais = no_intervalo - tem
        if fora:
            achados.append(
                f'{epic}: o intervalo do §3.1 ({entrada.intervalo!r}) nao cobre '
                f'{_como_ids(fora)}')
        if a_mais:
            achados.append(
                f'{epic}: o intervalo do §3.1 ({entrada.intervalo!r}) cobre '
                f'{_como_ids(a_mais)}, que nao esta no §4 sob {epic}')
    for epic, entrada in sorted(declarados.items()):
        if epic not in backlog.epics:
            achados.append(
                f'{epic}: tem linha no §3.1 ({modelo.INDICE}:{entrada.numero}) e '
                'nao tem sub-tabela no §4')

    total_real = len(backlog.linhas)
    soma = sum(entrada.quantos for entrada in backlog.inventario)
    if backlog.total is None:
        achados.append(f'{modelo.INDICE}: o §3.1 nao tem linha de TOTAL')
    else:
        if soma != backlog.total.quantos:
            achados.append(
                f'§3.1: a soma da coluna «N.º tickets» da {soma} e o TOTAL '
                f'({modelo.INDICE}:{backlog.total.numero}) diz '
                f'{backlog.total.quantos}')
        if backlog.total.quantos != total_real:
            achados.append(
                f'§3.1: o TOTAL ({modelo.INDICE}:{backlog.total.numero}) diz '
                f'{backlog.total.quantos} e o §4 tem {total_real} linha(s)')
        no_total = _expandir(backlog.total.intervalo)
        todos = {int(x[4:]) for x in backlog.linhas}
        if no_total != todos:
            fora, a_mais = todos - no_total, no_total - todos
            detalhe = []
            if fora:
                detalhe.append(f'nao cobre {_como_ids(fora)}')
            if a_mais:
                detalhe.append(f'cobre a mais {_como_ids(a_mais)}')
            achados.append(
                f'§3.1: o intervalo do TOTAL ({backlog.total.intervalo!r}) '
                + ' e '.join(detalhe))

    if backlog.proposito is None:
        achados.append(
            f'{modelo.INDICE}: o §1 nao declara «N tickets atómicos (KAM-… a '
            'KAM-…)»; a frase existe para ser derivada, e sem ela nao ha o que '
            'verificar')
    else:
        quantos, primeiro, ultimo = backlog.proposito
        if quantos != total_real:
            achados.append(
                f'§1: declara {quantos} ticket(s) e o §4 tem {total_real}')
        ordenados = sorted(backlog.linhas)
        if (primeiro, ultimo) != (ordenados[0], ordenados[-1]):
            achados.append(
                f'§1: declara o intervalo {primeiro}–{ultimo} e o §4 vai de '
                f'{ordenados[0]} a {ordenados[-1]}')
    if backlog.epics_no_proposito is None:
        achados.append(f'{modelo.INDICE}: o §1 nao declara «N epics»')
    elif backlog.epics_no_proposito != len(backlog.epics):
        achados.append(
            f'§1: declara {backlog.epics_no_proposito} epics e o §4 tem '
            f'{len(backlog.epics)} sub-tabelas')
    return achados


# --------------------------------------------------------------------------


@dataclass
class Veredicto:
    achados: list[str]
    avisos: list[str]
    configuracao: list[str]
    estatisticas: dict


def verificar(raiz: Path, minimo: int = modelo.MINIMO_DE_BLOCOS,
              hoje: datetime.date | None = None) -> Veredicto:
    """Tudo, numa passagem. Nao imprime e nao decide o codigo de saida."""
    hoje = hoje or datetime.date.today()
    declaracoes = ler_declaracoes(raiz)
    backlog = modelo.ler(raiz, minimo)
    controlos = versoes.varrer(raiz)

    achados: list[str] = []
    achados += sincronia(backlog)
    achados += orfaos(backlog)
    achados += terceira_superficie(backlog)
    achados += malformadas(backlog)
    achados += reciprocidade(backlog)
    achados += ciclos(backlog)
    achados += contagens(backlog)

    avisos: list[str] = []
    configuracao: list[str] = []

    # --- inversoes: aviso se declaradas, falha se nao.
    usadas: set[Inversao] = set()
    todas = inversoes(backlog)
    for de, para, genero, texto in todas:
        declarada = next((i for i in declaracoes.inversoes
                          if i.cobre(de, para, genero)), None)
        if declarada is None:
            achados.append(
                f'inversao de {genero}: {texto}. Se e deliberada, declara-a em '
                f'{ALLOW} com a razao e o risco do epic que a regista.')
        else:
            usadas.add(declarada)
            avisos.append(f'inversao de {genero} declarada ({declarada.origem}): '
                          f'{texto}')
    mortas = [i for i in declaracoes.inversoes if i not in usadas]
    for morta in mortas:
        configuracao.append(
            f'{ALLOW}: a inversao {morta.de} → {morta.para} ({morta.genero}) nao '
            'casa nenhuma inversao real; foi paga e a declaracao ficou')

    # --- controlo de versoes.
    por_ficheiro = {c.ficheiro: c for c in controlos}
    sequencias_usadas: set[Sequencia] = set()
    cabecalhos_usados: set[Cabecalho] = set()
    for controlo in controlos:
        # O numero repetido **nao** se declara: nao ha estado sujo nenhum para
        # cobrir (medido: 0 em 41 documentos), e a correccao e trocar um
        # numero numa linha. Falha desde o primeiro dia.
        for repetida in controlo.repetidas:
            achados.append(
                f'{controlo.ficheiro}: o «Controlo de versões» tem duas linhas '
                f'com a versão {repetida}. Dois ramos tomaram o mesmo numero e '
                'nenhum renumerou — a historia passa a ter duas emendas com o '
                'mesmo nome.')
        for buraco in controlo.buracos:
            declarada = next(
                (s for s in declaracoes.sequencias
                 if s.ficheiro == controlo.ficheiro and s.falta == buraco), None)
            if declarada is None:
                achados.append(
                    f'{controlo.ficheiro}: o «Controlo de versões» salta a '
                    f'{buraco} — a sequencia tem um buraco. Dois ramos tomaram o '
                    'mesmo numero e a emenda ficou sem linha.')
            else:
                sequencias_usadas.add(declarada)
                avisos.append(
                    f'{controlo.ficheiro}: buraco {buraco} declarado '
                    f'({declarada.origem})')
        if controlo.atrasado:
            declarado = next((c for c in declaracoes.cabecalhos
                              if c.ficheiro == controlo.ficheiro), None)
            if declarado is None:
                achados.append(
                    f'{controlo.ficheiro}: o cabecalho diz a versao '
                    f'{controlo.cabecalho} e a ultima linha do «Controlo de '
                    f'versões» e a {controlo.ultima}')
            else:
                cabecalhos_usados.add(declarado)
                avisos.append(
                    f'{controlo.ficheiro}: cabecalho atrasado declarado '
                    f'({declarado.origem}; {controlo.cabecalho} contra '
                    f'{controlo.ultima})')
    for sequencia in declaracoes.sequencias:
        if sequencia in sequencias_usadas:
            continue
        if sequencia.ficheiro not in por_ficheiro:
            configuracao.append(
                f'{ALLOW}: a sequencia declara {sequencia.ficheiro}, que nao tem '
                'tabela de controlo de versoes')
        else:
            configuracao.append(
                f'{ALLOW}: a sequencia declara que falta a {sequencia.falta} em '
                f'{sequencia.ficheiro}, e a sequencia esta continua; a divida foi '
                'paga e a declaracao ficou')
    for cabecalho in declaracoes.cabecalhos:
        if cabecalho in cabecalhos_usados:
            continue
        if cabecalho.ficheiro not in por_ficheiro:
            configuracao.append(
                f'{ALLOW}: o cabecalho declara {cabecalho.ficheiro}, que nao tem '
                'tabela de controlo de versoes')
        else:
            configuracao.append(
                f'{ALLOW}: o cabecalho de {cabecalho.ficheiro} ja esta a dia; a '
                'divida foi paga e a declaracao ficou')

    # --- prazos. Uma dispensa vencida volta a ser achado, e isso e o que
    # torna «passa a falha quando a lista esvaziar» um compromisso com data em
    # vez de uma intencao. Sem isto, a verificacao do cabecalho ficava
    # dispensada em 24 dos 25 documentos que tem campo de versao — e o unico
    # que passava tem **uma** linha de historico, pelo que passava
    # trivialmente: a verificacao nao validava um unico documento com emendas.
    vencidas = [d for d in declaracoes.todas() if d.vencida(hoje)]
    for declarada in vencidas:
        achados.append(
            f'{ALLOW}: {declarada} esta declarada por {declarada.origem} e a '
            f'dispensa venceu a {declarada.expira_em.isoformat()}. Corrige o '
            'que ela cobre, ou renova-a mexendo no `criado_em` — o que e uma '
            'decisao nova, e le-se no diff.')

    sem_campo = [c.ficheiro for c in controlos if c.cabecalho is None]
    proxima = min((d.expira_em for d in declaracoes.todas()), default=None)
    return Veredicto(
        achados=achados, avisos=avisos, configuracao=configuracao,
        estatisticas={
            'linhas': len(backlog.linhas), 'blocos': len(backlog.blocos),
            'epics': len(backlog.epics),
            'resumos': sum(len(v) for v in backlog.resumos.values()),
            'documentos': len(controlos), 'sem_campo': len(sem_campo),
            'declaracoes': len(declaracoes), 'backlog': backlog,
            'controlos': controlos, 'proxima_a_vencer': proxima,
        })


def _censo(veredicto: Veredicto, destino) -> None:
    estatisticas = veredicto.estatisticas
    backlog: Backlog = estatisticas['backlog']
    print('superficies:', file=destino)
    print(f'  linhas do §4        {estatisticas["linhas"]:4}', file=destino)
    print(f'  blocos              {estatisticas["blocos"]:4}', file=destino)
    print(f'  linhas do §3        {estatisticas["resumos"]:4}', file=destino)
    print(f'  epics               {estatisticas["epics"]:4}', file=destino)
    print('\nlinhas do §4 por epic:', file=destino)
    for epic in backlog.epics:
        print(f'  {epic} {len(backlog.por_epic.get(epic, [])):4}', file=destino)
    print('\ncontrolo de versões:', file=destino)
    print(f'  documentos com tabela      {estatisticas["documentos"]:4}', file=destino)
    print(f'  sem campo no cabeçalho     {estatisticas["sem_campo"]:4}', file=destino)
    com_buraco = sum(1 for c in estatisticas['controlos'] if c.buracos)
    atrasados = sum(1 for c in estatisticas['controlos'] if c.atrasado)
    print(f'  com buraco na sequência    {com_buraco:4}', file=destino)
    print(f'  cabeçalho atrasado         {atrasados:4}', file=destino)


def main(argv: list[str] | None = None) -> int:
    # Este anfitriao escreve em cp1252, e um excerto com acentos matava o guiao
    # com `UnicodeEncodeError` **depois** de ele ja ter dito que havia erros — a
    # saida mais inutil possivel. E a mesma precaucao do `lint_contagens`.
    for canal in (sys.stdout, sys.stderr):
        if hasattr(canal, 'reconfigure'):
            canal.reconfigure(encoding='utf-8', errors='replace')

    analisador = argparse.ArgumentParser(
        prog='lint_backlog',
        description='Gate 3c: coerencia do backlog mestre com os blocos dos epics.')
    analisador.add_argument('--root', default='.',
                            help='raiz do repositorio (por omissao, o cwd)')
    analisador.add_argument('--hoje', default=None, metavar='AAAA-MM-DD',
                            help='data a usar para os prazos (para testes)')
    sub = analisador.add_subparsers(dest='comando', required=True)
    sub.add_parser('check', help='falha se as superficies discordarem')
    sub.add_parser('censo', help='imprime o que leu, e quanto')
    argumentos = analisador.parse_args(argv)

    raiz = Path(argumentos.root).resolve()
    if not raiz.is_dir():
        print(f'lint_backlog: raiz inexistente: {raiz}', file=sys.stderr)
        return 2
    try:
        hoje = (datetime.date.fromisoformat(argumentos.hoje)
                if argumentos.hoje else None)
        veredicto = verificar(raiz, hoje=hoje)
    except (ConfiguracaoInvalida, BacklogIlegivel, versoes.ControloIlegivel,
            YamlSubsetError, OSError) as excepcao:
        print(f'lint_backlog: erro de configuracao: {excepcao}', file=sys.stderr)
        return 2

    if argumentos.comando == 'censo':
        _censo(veredicto, sys.stdout)
        return 0

    if veredicto.configuracao:
        print(f'lint_backlog: {len(veredicto.configuracao)} declaracao(oes) de '
              f'{ALLOW} que nao casam nada:', file=sys.stderr)
        for linha in veredicto.configuracao:
            print(f'  - {linha}', file=sys.stderr)
        print('Uma declaracao esquecida continua a abrir uma porta que ninguem '
              'vigia: apaga-a.', file=sys.stderr)
        return 2

    estatisticas = veredicto.estatisticas
    if veredicto.achados:
        print(f'lint_backlog: {len(veredicto.achados)} divergencia(s) entre as '
              f'tres superficies do backlog:', file=sys.stderr)
        for linha in veredicto.achados:
            print(f'  - {linha}', file=sys.stderr)
        print('\nO gate nao escolhe o lado certo: diz os dois valores e falha. O §4 '
              'e o contrato entre epics e o bloco e a especificacao; qual deles se '
              'corrige e de quem escreveu o ticket.', file=sys.stderr)
        return 1

    if veredicto.avisos:
        print(f'lint_backlog: {len(veredicto.avisos)} aviso(s) declarado(s) em '
              f'{ALLOW}:')
        for linha in veredicto.avisos:
            print(f'  . {linha}')
        print('  Quando a lista esvaziar, estas verificacoes passam a falha sem '
              'ninguem mexer no codigo.')
        if estatisticas['proxima_a_vencer'] is not None:
            print(f'  ATENCAO: a primeira dispensa vence a '
                  f'{estatisticas["proxima_a_vencer"].isoformat()}, e a partir '
                  'dai o gate falha. A data e o que distingue um prazo de uma '
                  'amnistia.')

    print(f'lint_backlog: conforme — {estatisticas["linhas"]} linha(s) no §4, '
          f'{estatisticas["blocos"]} bloco(s) e {estatisticas["resumos"]} linha(s) '
          f'de §3 em {estatisticas["epics"]} epics, a dizer o mesmo; '
          f'{estatisticas["documentos"]} documento(s) com «Controlo de versões» '
          f'({estatisticas["sem_campo"]} sem campo no cabeçalho); '
          f'{estatisticas["declaracoes"]} declaracao(oes) em {ALLOW}.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
