"""As tres superficies do backlog, lidas da arvore — e nada mais.

Este modulo **le**; nao julga. Quem compara e quem decide o codigo de saida e o
`cli`. A separacao importa porque a leitura e a parte fragil: as duas gramaticas
sao tabelas de Markdown escritas a mao, e um parser que seja tolerante aqui
transforma-se num gate que diz «conforme» sobre o que nao percebeu.

Tres regras de leitura, todas por o contrario ja ter custado:

1. **Estrito, e diz o que nao entendeu.** Uma linha de `§4` com um numero de
   celulas diferente do cabecalho, um bloco sem tabela de campos, um epic sem
   §3 — tudo isso e `BacklogIlegivel`, que o `cli` traduz em codigo 2.
2. **Nao le dentro de cercas de codigo.** Os blocos `### Handoff para Claude
   Code` sao cercas ```text com `KAM-NNN` la dentro, e `specs/01` §7 tem um
   `## KAM-NNN — <titulo do ticket>` que e o *template* do PR e nao um ticket.
3. **Reutiliza o leitor do §4 do `lint_refs`** (`seccao`, `LINHA_BACKLOG`). Duas
   gramaticas para a mesma tabela era a forma garantida de o gate 3 e o gate 3c
   discordarem sobre o que e uma linha de ticket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lint_refs.sets import FonteCanonicaAusente, LINHA_BACKLOG, seccao

#: O backlog mestre, e o §4 de onde se le o contrato entre epics.
INDICE = 'specs/INDICE.md'
#: Os onze epics. Dez tem os blocos dentro; o EPIC-01 e so indice (KAM-155).
EPICS = 'specs/EPIC-*.md'
#: Um ficheiro por ticket, convencao do KAM-155 e por agora so do EPIC-01.
TICKETS = 'specs/tickets'

#: Titulo de um bloco de ticket. O travessao e o `—` (U+2014), sempre.
TITULO_DE_BLOCO = re.compile(r'^## (KAM-\d{3}) — (.+?)\s*$')
#: Sub-tabela do §4: `### EPIC-07 — Seguranca e Conformidade`.
SUBTABELA = re.compile(r'^### (EPIC-\d{2}) — (.+?)\s*$')
#: Linha de uma tabela de campos: `| Fase | 0 |`.
CAMPO = re.compile(r'^\|\s*(?P<campo>[^|]+?)\s*\|\s*(?P<valor>.*?)\s*\|\s*$')
#: Celula de ID da tabela §3, que no EPIC-01 e uma ligacao (KAM-155) e nos
#: outros dez e o identificador nu.
#:
#: **`fullmatch`, e com a ligacao lida.** A primeira versao casava por prefixo
#: (`^\[?(KAM-\d{3})\]?`) e dava verde a uma celula com **quatro**
#: digitos, na linha do ticket de tres que lhe serve de prefixo: um
#: digito a mais passava despercebido. E nao olhava para o destino da
#: ligacao, pelo que `[KAM-154](tickets/KAM-003.md)` passava nos dois gates: o
#: 3 ve um `KAM-154` que existe e um caminho que resolve, e o 3c via o ID
#: certo. Os dois achados sao da revisao adversarial do KAM-138 (m1 e m2).
ID_DA_TABELA = re.compile(
    r'(?:\[(?P<ligado>KAM-\d{3})\]\((?P<destino>[^)]*)\)|(?P<nu>KAM-\d{3}))')
CERCA = re.compile(r'^\s*```')

#: As colunas do §4, por ordem. Escritas, e nao inferidas do cabecalho: se
#: alguem acrescentar uma coluna, o gate tem de parar e nao adivinhar.
COLUNAS_DO_INDICE = ('id', 'titulo', 'tipo', 'estimativa', 'prioridade',
                     'fase', 'dependencias')
#: As colunas da «Tabela Resumo de Tickets» do §3. **Nao tem `fase`** — e por
#: isso que a comparacao com o §3 e de cinco campos e nao de seis.
COLUNAS_DA_RESUMO = ('id', 'titulo', 'tipo', 'estimativa', 'prioridade',
                     'dependencias')
#: Os campos que **todo** o bloco tem de declarar. Um campo em falta e codigo 2
#: e nao «sem divergencia»: um bloco mudo passaria a comparacao por omissao.
CAMPOS_OBRIGATORIOS = ('Epic', 'Fase', 'Tipo', 'Prioridade', 'Estimativa',
                       'Dependências', 'Bloqueia')
#: O nome como esta escrito nos documentos (com acentos) -> nome interno.
NOME_DO_CAMPO = {
    'Epic': 'epic', 'Fase': 'fase', 'Tipo': 'tipo', 'Prioridade': 'prioridade',
    'Estimativa': 'estimativa', 'Dependências': 'dependencias',
    'Bloqueia': 'bloqueia',
}

#: Quantos blocos se espera encontrar, no minimo. **Escrito a mao, de
#: proposito**, como o `MINIMO_ESPERADO` do `lint_contagens` e o `esperados=N`
#: do KAM-002: se um glob ou o titulo dos blocos mudarem de forma, o gate tem de
#: falhar em vez de dizer «conforme» sobre o vazio.
#:
#: Medido a 2026-10-18 sobre `publico/main`: **159** linhas no §4 e **159**
#: blocos. O minimo fica em **100**: da folga para o backlog encolher por
#: decisao, e nao da folga para a leitura deixar de ver um terco da populacao.
MINIMO_DE_BLOCOS = 100

#: «Nenhum», no campo `Dependencias` e no `Bloqueia`.
VAZIO = ('—', '-', '', '–')


class BacklogIlegivel(RuntimeError):
    """Uma superficie nao se consegue ler, ou nao diz o que promete.

    Levanta-se em vez de devolver vazio: um conjunto vazio faria o gate dizer
    «0 divergencias» sobre o que nunca leu, que e exactamente o modo de falha
    que este gate existe para nao ter.
    """


def normalizar_titulo(titulo: str) -> str:
    """O titulo comparavel entre superficies que vivem em pastas diferentes.

    **A regra, escrita, porque sem ela a comparacao de titulos esta errada.**
    Um titulo pode conter um caminho relativo — o KAM-139 chama-se «Variantes
    vivas em `../docs/tecnica/` …» — e pela convencao do KAM-128 o caminho e
    relativo ao **documento que o escreve**. O `specs/INDICE.md` escreve
    `../docs/tecnica/`; o bloco, que desde o KAM-155 vive em `specs/tickets/`,
    escreve `../../docs/tecnica/`. Os dois estao certos e apontam para o mesmo
    ficheiro: exigir igualdade exacta reportaria tres divergencias que nao
    existem, e a correccao «obvia» de qualquer delas partia um caminho.

    Colapsa-se, por isso, a subida de directorio, e **mais nada**: o `código`,
    o *italico* e os travessoes comparam-se tal como estao escritos. Tres
    titulos do conjunto dependem desta regra hoje (KAM-111, KAM-139, KAM-140).
    """
    return re.sub(r'(?:\.\./)+', '../', titulo)


def lista_de_ids(valor: str) -> tuple[str, ...]:
    """`'KAM-003, ext:D6'` -> `('KAM-003', 'ext:D6')`; `'—'` -> `()`."""
    if valor.strip() in VAZIO:
        return ()
    return tuple(x.strip() for x in valor.split(',') if x.strip())


@dataclass(frozen=True)
class Linha:
    """Uma linha de ticket do §4 — o contrato entre epics."""

    id: str
    titulo: str
    tipo: str
    estimativa: str
    prioridade: str
    fase: str
    dependencias: str
    epic: str
    numero: int

    @property
    def deps(self) -> tuple[str, ...]:
        return lista_de_ids(self.dependencias)


@dataclass(frozen=True)
class Bloco:
    """Um bloco `## KAM-NNN — `, com a sua tabela de campos."""

    id: str
    titulo: str
    campos: dict[str, str]
    ficheiro: str
    numero: int

    def campo(self, nome: str) -> str:
        return self.campos[nome]

    @property
    def deps(self) -> tuple[str, ...]:
        return lista_de_ids(self.campos['dependencias'])

    @property
    def bloqueia(self) -> tuple[str, ...]:
        return lista_de_ids(self.campos['bloqueia'])

    @property
    def onde(self) -> str:
        return f'{self.ficheiro}:{self.numero}'


@dataclass(frozen=True)
class Resumo:
    """Uma linha da «Tabela Resumo de Tickets» do §3 de um epic."""

    id: str
    titulo: str
    tipo: str
    estimativa: str
    prioridade: str
    dependencias: str
    ficheiro: str
    numero: int
    #: O caminho da ligacao, quando a celula de ID e uma (EPIC-01, KAM-155).
    #: `None` nos outros dez epics, que escrevem o identificador nu.
    destino: str | None = None


@dataclass(frozen=True)
class Inventario:
    """Uma linha do §3.1, «Por epic» — a contagem declarada."""

    epic: str
    intervalo: str
    quantos: int
    fases: str
    numero: int


@dataclass(frozen=True)
class Backlog:
    """As tres superficies, lidas uma vez."""

    linhas: dict[str, Linha]
    blocos: dict[str, Bloco]
    resumos: dict[str, list[Resumo]]
    inventario: list[Inventario]
    total: Inventario | None
    #: `(quantos, primeiro, ultimo)` do §1, ou `None` se a frase nao existir.
    proposito: tuple[int, str, str] | None
    #: Quantos epics o §1 declara.
    epics_no_proposito: int | None
    epics: tuple[str, ...]
    por_epic: dict[str, list[str]] = field(default_factory=dict)


def _recortar(texto: str, inicio: str, fim: str, onde: str) -> str:
    """O `seccao` do `lint_refs`, com a excepcao traduzida para esta taxonomia.

    O `lint_refs` levanta `FonteCanonicaAusente` e mapeia-a para codigo 2; aqui
    o nome da excepcao e outro e o codigo e o mesmo. Traduz-se no ponto de
    leitura para que a mensagem diga **que ficheiro** nao tinha a seccao: a do
    `lint_refs` so diz o nome da seccao, e com onze epics isso nao chega.
    """
    try:
        corpo = seccao(texto, inicio, fim)
    except FonteCanonicaAusente as excepcao:
        raise BacklogIlegivel(f'{onde}: {excepcao}') from excepcao
    if not corpo.strip():
        raise BacklogIlegivel(f'{onde}: a seccao {inicio!r} esta vazia')
    return corpo


def _celulas(linha: str) -> list[str]:
    return [c.strip() for c in linha.strip().strip('|').split('|')]


def _fora_de_cerca(texto: str):
    """`(numero, linha)` das linhas que nao estao dentro de uma cerca.

    Sem isto, o `## KAM-NNN — <titulo do ticket>` do *template* de PR e os
    `KAM-NNN` dos blocos de *handoff* entravam no universo de blocos.
    """
    dentro = False
    for numero, linha in enumerate(texto.split('\n'), 1):
        if CERCA.match(linha):
            dentro = not dentro
            continue
        if not dentro:
            yield numero, linha


def ler_indice(raiz: Path) -> tuple[dict[str, Linha], dict[str, list[str]],
                                    tuple[str, ...]]:
    """As linhas do §4, por ID, e a ordem dos epics."""
    caminho = raiz / INDICE
    if not caminho.is_file():
        raise BacklogIlegivel(f'fonte em falta: {INDICE}')
    texto = caminho.read_text(encoding='utf-8')
    corpo = _recortar(texto, '## 4. Backlog mestre', '\n## 5.', INDICE)

    deslocamento = texto[:texto.find('## 4. Backlog mestre')].count('\n')
    linhas: dict[str, Linha] = {}
    por_epic: dict[str, list[str]] = {}
    ordem: list[str] = []
    epic: str | None = None
    for numero, bruta in _fora_de_cerca(corpo):
        sub = SUBTABELA.match(bruta)
        if sub:
            epic = sub.group(1)
            if epic in por_epic:
                raise BacklogIlegivel(
                    f'{INDICE}:{deslocamento + numero}: sub-tabela {epic} repetida '
                    'no §4')
            por_epic[epic] = []
            ordem.append(epic)
            continue
        if not LINHA_BACKLOG.match(bruta):
            continue
        if epic is None:
            raise BacklogIlegivel(
                f'{INDICE}:{deslocamento + numero}: linha de ticket antes de '
                'qualquer `### EPIC-NN — `; nao se sabe a que epic pertence')
        celulas = _celulas(bruta)
        if len(celulas) != len(COLUNAS_DO_INDICE):
            raise BacklogIlegivel(
                f'{INDICE}:{deslocamento + numero}: a linha tem {len(celulas)} '
                f'celula(s) e o §4 tem {len(COLUNAS_DO_INDICE)} colunas '
                f'({", ".join(COLUNAS_DO_INDICE)}); lido: {bruta.strip()[:120]}')
        valores = dict(zip(COLUNAS_DO_INDICE, celulas))
        identificador = valores['id']
        if identificador in linhas:
            raise BacklogIlegivel(
                f'{INDICE}:{deslocamento + numero}: {identificador} tem duas '
                f'linhas no §4 (a primeira em :{linhas[identificador].numero})')
        linhas[identificador] = Linha(
            **valores, epic=epic, numero=deslocamento + numero)
        por_epic[epic].append(identificador)

    if not linhas:
        raise BacklogIlegivel(f'{INDICE}: §4 sem uma unica linha de ticket')
    return linhas, por_epic, tuple(ordem)


def _campos_do_bloco(linhas: list[tuple[int, str]], onde: str) -> dict[str, str]:
    """A tabela `| Campo | Valor |` que vem logo a seguir ao titulo."""
    campos: dict[str, str] = {}
    for _, bruta in linhas:
        if bruta.startswith('#'):
            break
        achado = CAMPO.match(bruta)
        if not achado:
            continue
        nome, valor = achado.group('campo'), achado.group('valor')
        if nome in ('Campo', '---') or set(nome) <= {'-', ':'}:
            continue
        campos[nome] = valor
    if not campos:
        raise BacklogIlegivel(
            f'{onde}: bloco sem tabela de campos. Um bloco mudo passaria a '
            'comparacao por omissao, e e por isso que isto e erro de '
            'configuracao e nao «sem divergencia».')
    traduzidos = {NOME_DO_CAMPO[k]: v for k, v in campos.items()
                  if k in NOME_DO_CAMPO}
    faltam = [k for k in CAMPOS_OBRIGATORIOS
              if NOME_DO_CAMPO[k] not in traduzidos]
    if faltam:
        raise BacklogIlegivel(
            f'{onde}: faltam no bloco o(s) campo(s) {", ".join(faltam)}')
    return traduzidos


def _blocos_do_texto(texto: str, rel: str) -> list[Bloco]:
    visiveis = list(_fora_de_cerca(texto))
    blocos: list[Bloco] = []
    for indice, (numero, bruta) in enumerate(visiveis):
        achado = TITULO_DE_BLOCO.match(bruta)
        if not achado:
            continue
        identificador, titulo = achado.group(1), achado.group(2)
        onde = f'{rel}:{numero}'
        blocos.append(Bloco(
            id=identificador, titulo=titulo,
            campos=_campos_do_bloco(visiveis[indice + 1:], onde),
            ficheiro=rel, numero=numero))
    return blocos


def ler_blocos(raiz: Path, minimo: int = MINIMO_DE_BLOCOS) -> dict[str, Bloco]:
    """Os blocos dos dois sitios onde vivem: `specs/tickets/` e os epics.

    **Os dois, e nao um.** Com um glob so, o gate ficava verde sobre os dez
    epics e nao via os 44 blocos do EPIC-01 — o mesmo defeito que o KAM-155
    abriu no `lint_handoff` e que la ja esta fechado.
    """
    blocos: dict[str, Bloco] = {}

    def juntar(novos: list[Bloco]) -> None:
        for bloco in novos:
            anterior = blocos.get(bloco.id)
            if anterior is not None:
                raise BacklogIlegivel(
                    f'{bloco.onde}: {bloco.id} tem dois blocos (o outro em '
                    f'{anterior.onde}); um ticket tem uma especificacao')
            blocos[bloco.id] = bloco

    pasta = raiz / TICKETS
    if not pasta.is_dir():
        raise BacklogIlegivel(f'pasta em falta: {TICKETS}')
    for caminho in sorted(pasta.glob('KAM-*.md')):
        rel = caminho.relative_to(raiz).as_posix()
        novos = _blocos_do_texto(caminho.read_text(encoding='utf-8'), rel)
        if not novos:
            raise BacklogIlegivel(
                f'{rel}: ficheiro de ticket sem bloco `## KAM-NNN — `')
        if len(novos) > 1:
            raise BacklogIlegivel(
                f'{rel}: {len(novos)} blocos num ficheiro de ticket; a convencao '
                'do KAM-155 e um ficheiro por ticket')
        if novos[0].id != caminho.stem:
            raise BacklogIlegivel(
                f'{rel}: o ficheiro chama-se {caminho.stem} e o bloco diz '
                f'{novos[0].id}')
        juntar(novos)

    epics = sorted(raiz.glob(EPICS))
    if not epics:
        raise BacklogIlegivel(f'nenhum epic encontrado em {EPICS}')
    for caminho in epics:
        rel = caminho.relative_to(raiz).as_posix()
        juntar(_blocos_do_texto(caminho.read_text(encoding='utf-8'), rel))

    if len(blocos) < minimo:
        raise BacklogIlegivel(
            f'li {len(blocos)} bloco(s) e esperam-se pelo menos '
            f'{minimo}. Ou um glob ou a forma do titulo deixaram de ver '
            'a populacao — e «0 divergencias» sobre o vazio e a falha que este '
            'gate existe para recusar. Se o backlog encolheu de verdade, baixa o '
            '`MINIMO_DE_BLOCOS` e diz porque no commit.')
    return blocos


def epic_do_ficheiro(rel: str) -> str | None:
    achado = re.match(r'specs/EPIC-(\d{2})_', rel)
    return f'EPIC-{achado.group(1)}' if achado else None


def ler_resumos(raiz: Path) -> dict[str, list[Resumo]]:
    """A «Tabela Resumo de Tickets» do §3 de cada epic — a terceira superficie."""
    resumos: dict[str, list[Resumo]] = {}
    for caminho in sorted(raiz.glob(EPICS)):
        rel = caminho.relative_to(raiz).as_posix()
        epic = epic_do_ficheiro(rel)
        if epic is None:
            raise BacklogIlegivel(f'{rel}: nome de epic que nao se sabe ler')
        texto = caminho.read_text(encoding='utf-8')
        marca = '## 3. Tabela Resumo de Tickets'
        corpo = _recortar(texto, marca, '\n## ', rel)
        deslocamento = texto[:texto.find(marca)].count('\n')
        linhas: list[Resumo] = []
        for numero, bruta in _fora_de_cerca(corpo):
            if not bruta.startswith('|'):
                continue
            celulas = _celulas(bruta)
            achado = ID_DA_TABELA.fullmatch(celulas[0])
            if not achado:
                # Uma celula que **nao menciona** um ticket nao e uma linha de
                # ticket: e o cabecalho, o separador, ou prosa. Uma que o
                # mencione e nao tenha uma das duas formas aceites e uma linha
                # que o parser nao sabe ler, e isso diz-se em voz alta — era
                # assim que uma celula com um digito a mais passava
                # pelo ticket que lhe serve de prefixo.
                if 'KAM-' in celulas[0]:
                    raise BacklogIlegivel(
                        f'{rel}:{deslocamento + numero}: a celula de ID do §3 e '
                        f'{celulas[0]!r}, que nao e `KAM-NNN` nem '
                        '`[KAM-NNN](caminho)`')
                continue
            if len(celulas) != len(COLUNAS_DA_RESUMO):
                raise BacklogIlegivel(
                    f'{rel}:{deslocamento + numero}: a linha do §3 tem '
                    f'{len(celulas)} celula(s) e esperam-se '
                    f'{len(COLUNAS_DA_RESUMO)} ({", ".join(COLUNAS_DA_RESUMO)})')
            valores = dict(zip(COLUNAS_DA_RESUMO, celulas))
            valores['id'] = achado.group('ligado') or achado.group('nu')
            linhas.append(Resumo(**valores, destino=achado.group('destino'),
                                 ficheiro=rel, numero=deslocamento + numero))
        if not linhas:
            raise BacklogIlegivel(f'{rel}: §3 sem uma unica linha de ticket')
        resumos[epic] = linhas
    return resumos


_LINHA_31 = re.compile(
    r'^\|\s*\**(?P<epic>EPIC-\d{2}|TOTAL)[^|*]*\**\s*\|'
    r'\s*\**(?P<intervalo>[^|*]+?)\**\s*\|'
    r'\s*\**(?P<quantos>\d+)\**\s*\|'
    r'\s*\**(?P<fases>[^|*]*?)\**\s*\|\s*$')


def ler_inventario(raiz: Path) -> tuple[list[Inventario], Inventario | None]:
    """As linhas do §3.1 «Por epic», e a do TOTAL."""
    texto = (raiz / INDICE).read_text(encoding='utf-8')
    marca = '### 3.1 Por epic'
    corpo = _recortar(texto, marca, '\n### 3.2', INDICE)
    deslocamento = texto[:texto.find(marca)].count('\n')
    por_epic: list[Inventario] = []
    total: Inventario | None = None
    for numero, bruta in _fora_de_cerca(corpo):
        achado = _LINHA_31.match(bruta)
        if not achado:
            continue
        entrada = Inventario(
            epic=achado.group('epic'), intervalo=achado.group('intervalo').strip(),
            quantos=int(achado.group('quantos')),
            fases=achado.group('fases').strip(), numero=deslocamento + numero)
        if entrada.epic == 'TOTAL':
            total = entrada
        else:
            por_epic.append(entrada)
    if not por_epic:
        raise BacklogIlegivel(f'{INDICE}: §3.1 sem uma unica linha de epic')
    return por_epic, total


_PROPOSITO = re.compile(
    r'\*\*(\d+) tickets atómicos \(KAM-(\d{3}) a KAM-(\d{3})\)\*\*')
_EPICS_NO_PROPOSITO = re.compile(r'\*\*(\d+) epics\*\*')


def ler_proposito(raiz: Path):
    """Os numeros do §1: quantos tickets, que intervalo, quantos epics."""
    texto = (raiz / INDICE).read_text(encoding='utf-8')
    corpo = _recortar(texto, '## 1. Propósito', '\n## 2.', INDICE)
    achado = _PROPOSITO.search(corpo)
    quantos = ((int(achado.group(1)), f'KAM-{achado.group(2)}',
                f'KAM-{achado.group(3)}') if achado else None)
    epics = _EPICS_NO_PROPOSITO.search(corpo)
    return quantos, (int(epics.group(1)) if epics else None)


def ler(raiz: Path, minimo: int = MINIMO_DE_BLOCOS) -> Backlog:
    """As tres superficies e as contagens, numa leitura.

    O `minimo` e parametro **so** para as *fixtures* dos testes, que tem meia
    duzia de blocos de proposito: uma guarda contra o vazio calibrada para o
    conjunto real nao se pode verificar com o conjunto real.
    """
    linhas, por_epic, epics = ler_indice(raiz)
    blocos = ler_blocos(raiz, minimo)
    resumos = ler_resumos(raiz)
    inventario, total = ler_inventario(raiz)
    proposito, epics_no_proposito = ler_proposito(raiz)
    return Backlog(linhas=linhas, blocos=blocos, resumos=resumos,
                   inventario=inventario, total=total, proposito=proposito,
                   epics_no_proposito=epics_no_proposito, epics=epics,
                   por_epic=por_epic)
