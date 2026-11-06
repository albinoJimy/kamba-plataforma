"""Le um bloco de ticket nas duas superficies que ele tem sobre o mesmo facto.

Um bloco `## KAM-NNN — ` diz **duas vezes** se um critério está cumprido:

1. na **lista de caixas** de `### Critérios de Aceitação` e de
   `### Definition of Done` — `- [ ]` ou `- [x]`;
2. na **tabela de verificação**, na coluna `Estado`, quando o ticket foi
   entregue.

As duas podem discordar e nenhum dos onze *jobs* de gate as compara. Este modulo
le-as; o `lint.py` compara-as.

## O QUE SE MEDIU ANTES DE ESCREVER ISTO, E PORQUE E QUE MUDOU O DESENHO

A primeira versao deste *lint* ia impor «o numero de `- [x]` iguala o numero de
linhas `**marcada**`».

**Os numeros que seguem sao do `medir.py`**, que vive ao lado deste ficheiro e
declara o predicado de cada um **antes** de o contar. A primeira versao desta
*docstring* citava-os de *scripts* que correram numa pasta temporaria e
desapareceram, e a revisao adversarial montou vinte receitas sem reproduzir
nenhum: a conclusao mantinha-se, os numeros nao.

Medido: essa regra poria **107 dos 126** blocos a vermelho — 84% — e nao por
estarem errados. Nao ha **uma** convencao:

* a coluna de estado usa **77 termos distintos** em 1 432 celulas. Os dois de
  topo sao `satisfeito` (**681**) e `marcada` (**172**); `marcada` — a palavra
  que a regra ia exigir — e minoria por quatro para um;
* o cabecalho da tabela tem muitas formas, e **41 tabelas com coluna de assunto
  nao tem coluna de `Estado`**: nessas o estado vive na prosa da evidencia;
* a seccao de verificacao **nao tem fronteira fiavel**: uns blocos poem-na antes
  dos «Detalhes Técnicos», outros depois do «Handoff», e no KAM-013 as tabelas
  vivem sob um titulo irmao (`### Os critérios, um a um`).

Daí tres escolhas de desenho, e cada uma e uma renuncia:

**Nao se delimita a seccao de verificacao.** Procuram-se **tabelas** em todo o
bloco, e identificam-se pelo **cabecalho**. O bloco e a unidade.

**O vocabulario e declarado e nao inferido**, em `ESTADOS_FEITO` e
`ESTADOS_POR_FAZER`, construidos da medicao acima e nao de memoria. Uma celula
que nao case fica **nao medida** e e **contada** — nao e achado, porque decidir
o que `condicionado ao spike` quer dizer e materia de canon e nao deste *lint*.

**A cobertura e parte da saida.** Um *lint* que nao diga quantos blocos nao
mediu ensina a ler «0 achados» como «esta tudo bem», que e a falha que o
`log_policy` e o `obs_lint` desta casa ja recusam («passar sem ter lido nada nao
e passar»).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lint_backlog.modelo import TITULO_DE_BLOCO, fora_de_cerca

#: Onde vivem os blocos: os dez epics com blocos dentro, e um ficheiro por
#: ticket no EPIC-01 (convencao do KAM-155).
EPICS = "specs/EPIC-*.md"
TICKETS = "specs/tickets"

#: Um titulo de nivel 3 ou 4 dentro de um bloco.
TITULO = re.compile(r"^(#{3,4}) (.+?)\s*$")
#: Uma caixa de lista. Aceita `x` e `X`.
CAIXA = re.compile(r"^- \[([ xX])\] (.*)$")
#: A linha separadora de uma tabela Markdown: `|---|---|`.
SEPARADOR = re.compile(r"^\|[\s\-:|]+\|\s*$")

#: Os titulos das duas listas de caixas. Exactos: um titulo parecido mas
#: diferente e um bloco que escreve fora da convencao, e isso vê-se melhor como
#: «nao medido» do que como uma lista encontrada por aproximacao.
TITULO_DOS_CRITERIOS = "Critérios de Aceitação"
TITULO_DA_DOD = "Definition of Done"

#: O que faz de uma tabela a tabela dos **critérios**: o cabecalho tem uma
#: coluna de assunto **e** uma coluna `Estado`.
#:
#: **Casam por igualdade e nao por sub-cadeia, e a diferenca era um defeito.** A
#: primeira versao usava `p in coluna`, e a tabela `## Riscos do Epic` tem a
#: coluna «Mitigacao **ou critério** de saida» — pelo que ela era lida como
#: tabela de critérios de um bloco. Medido pela revisao adversarial em **quatro**
#: blocos (KAM-064, KAM-117, KAM-127 e KAM-149), e a uma coincidencia de
#: contagem de produzir achados falsos: se a tabela de riscos tivesse tantas
#: linhas quantas as caixas do bloco, o *lint* comparava critérios de aceitacao
#: contra estados de risco.
#:
#: A lista tem as formas que a arvore usa, e nao so a canonica: **26** tabelas
#: escrevem `| CA | Estado | Evidência |`, e descarta-las custava 26 tabelas de
#: cobertura **e** uma mensagem falsa — o bloco caia na categoria «sem tabela de
#: verificacao com coluna `Estado`» tendo-a.
COLUNAS_DE_ASSUNTO = ("critério", "criterio", "ca", "caixa", "linha")
#: E o que faz dela a tabela da **DoD**.
COLUNA_DA_DOD = ("dod",)

#: **Houve aqui uma terceira especie, `ambigua`, e saiu.** Ela separava as seis
#: tabelas de cabecalho `| # | Item | Estado | … |` das restantes sem coluna de
#: assunto, com a justificacao de que emparelha-las por palpite «punha a tabela
#: da DoD contra a lista dos critérios». A revisao adversarial mediu essa
#: justificacao e ela **nao se verifica**: tratar as `ambigua` como `criterios`
#: deixa os numeros da arvore identicos, zero achados novos. Uma distincao que
#: nao muda nenhum resultado e um conceito a mais para quem le o modulo, pelo que
#: o `Item` cai agora em `sem_assunto` como as outras — e a saida continua a
#: dizer, por bloco, que tem coluna `Estado` e um assunto que nao se sabe ler.
#: A coluna que diz o estado. Sem ela, a tabela nao declara estados.
COLUNA_DE_ESTADO = "estado"

#: As palavras de estado que querem dizer «cumprido». Da medicao da arvore,
#: nao de memoria. Casam por **prefixo**, porque a celula leva prosa atras
#: («satisfeito, e e da base», «satisfeito contra o simulador»).
ESTADOS_FEITO = (
    "satisfeito",
    "satisfeita",
    "marcada",
    "marcado",
    "cumprido",
    "cumprida",
    "confirmado",
    "confirmada",
    "verde",
    "ja satisfeito",
    "já satisfeito",
)

#: E as que querem dizer «nao cumprido», incluindo as compostas que **comecam
#: pelo estado da caixa** — `vazia, parcial` e `caixa vazia — parcial` sao a
#: forma que alguns blocos usam para dizer as duas coisas numa celula.
ESTADOS_POR_FAZER = (
    "parcial",
    "vazia",
    "vazio",
    "caixa vazia",
    "(caixa vazia)",
    "nao satisfeito",
    "não satisfeito",
    "nao satisfeita",
    "não satisfeita",
    "nao cumprido",
    "não cumprido",
    "nao verificado",
    "não verificado",
    "por marcar",
    "por cumprir",
    "morto",
    # Formas compostas que a arvore usa e que nenhum prefixo das de cima casava.
    # Medidas pela revisao adversarial: a lista chamava-se «por cumprir» e **nao
    # continha** `por cumprir`, e o `KAM-068` escreve `não — caixa vazia`.
    "nao — caixa vazia",
    "não — caixa vazia",
    "nao - caixa vazia",
    "não - caixa vazia",
)

#: **As que nao se classificam, e e deliberado.** Nenhuma destas quer dizer
#: «cumprido» nem «por cumprir»: dizem que a pergunta nao se aplica, que a
#: resposta nao e nossa, ou que ha uma divergencia registada. Classifica-las
#: punha o *lint* a julgar o que o canon nao decidiu — e foi um achado a
#: aparecer que o mostrou: `não aplicável` com a caixa marcada lia-se como
#: defeito, quando um critério que nao se aplica pode legitimamente ter a caixa
#: marcada. Ficam **nao medidas**, contadas e nomeadas.
#:
#: Unifica-las e uma decisao de canon (ver o §5 do `docs/lint-bloco.md`), e por
#: isso esta devolvida ao fundador em vez de resolvida aqui.
ESTADOS_SEM_CLASSE = (
    "nao aplicavel",
    "não aplicável",
    "nao alterado",
    "não alterado",
    "decisao aberta",
    "decisão aberta",
    "decisao escrita",
    "decisão escrita",
    "a confirmar por parecer",
    "a confirmar na integracao",
    "a confirmar na integração",
    "divergencia registada",
    "divergência registada",
    "observacao de backlog",
    "observação de backlog",
    "conflito documental",
    "defeito do backlog",
    "condicionado ao spike",
    "devolvido",
    "indicio",
    "indício",
)


class BlocoIlegivel(RuntimeError):
    """Uma superficie existe e nao se consegue ler."""


def limpo(celula: str) -> str:
    """Uma celula sem enfase nem acentuacao de codigo, em minusculas."""
    return re.sub(r"[*`_]", "", celula).strip().lower()


#: Os separadores que abrem a **justificacao** de uma celula de estado. Exige-se
#: o espaco depois, e e o que distingue `satisfeito, com a aritmetica corrigida`
#: (justificacao) de `verde-azulado` (uma palavra que nao e o termo).
_SEPARADORES = (", ", " — ", " - ", " (", ": ", "; ", " – ")


def _termo_da_celula(texto: str) -> str:
    """O termo de estado de uma celula, sem a justificacao que vier atras.

    Corta no **primeiro** separador que apareca. Uma cadeia sem separador
    devolve-se inteira, e e isso que a deixa cair em «nao medida» quando nao e
    um termo.
    """
    corte = len(texto)
    for separador in _SEPARADORES:
        posicao = texto.find(separador)
        if posicao != -1:
            corte = min(corte, posicao)
    return texto[:corte].strip()


def classificar_estado(celula: str) -> bool | None:
    """`True` cumprido, `False` por cumprir, `None` **nao medido**.

    ## O CASAMENTO E POR IGUALDADE, E O PREFIXO ERA O MODELO ERRADO

    **A primeira versao casava por prefixo nu, e a revisao adversarial mediu o
    preco:** `verde` esta em `ESTADOS_FEITO`, logo `verde-azulado` dava
    «cumprido»; e `cumprido parcialmente`, `marcadamente insuficiente` e
    `confirmado / não verificado` — esta ultima uma forma **real** da arvore —
    davam o mesmo. Era palpite por prefixo, no proprio sitio em que o ticket
    afirma que nada se classifica por palpite. Uma fronteira de palavra nao
    chega: o `-` de `verde-azulado` e o espaco de `cumprido parcialmente` sao
    fronteiras.

    O modelo e outro: **o estado e o termo, e o que vem depois de um separador e
    justificacao.** Prova-se a celula inteira por igualdade; se nao casar,
    corta-se no primeiro separador **seguido de espaco** (`, `, ` — `, ` (`,
    `: `) e prova-se a cabeca. Uma celula sem separador que nao seja um termo
    conhecido fica **nao medida**.

    O preco esta declarado: celulas como `satisfeito pelo que o repositorio tem`
    deixam de se classificar, porque nao ha separador e a cadeia inteira nao e um
    termo. Perde-se cobertura e nao se ganha palpite — que e a troca que esta
    casa faz em toda a parte («nao medido» conta-se e aparece na saida).

    ## A ORDEM DAS TRES LISTAS E PRECAUCAO, NAO NECESSIDADE

    A versao anterior afirmava que os «por fazer» tinham de ir primeiro «senao
    `vazia, satisfeito` classificava-se ao contrario», e isso e **falso**: o
    termo de `vazia, satisfeito` e `vazia`, e nenhuma ordem o muda. A revisao
    provou-o — a mutacao que troca as listas **sobrevivia** aos ensaios. A ordem
    fica por ser a leitura certa de uma celula composta, e nao porque hoje mude
    um resultado; e ha um ensaio a dizer **isso** em vez de a dizer o contrario.
    """
    texto = limpo(celula)
    if not texto:
        return None
    for lista, veredicto in ((ESTADOS_SEM_CLASSE, None),
                             (ESTADOS_POR_FAZER, False),
                             (ESTADOS_FEITO, True)):
        if texto in lista:
            return veredicto
    termo = _termo_da_celula(texto)
    if termo == texto:
        # Sem justificacao a cortar: ja se provou a cadeia inteira.
        return None
    for lista, veredicto in ((ESTADOS_SEM_CLASSE, None),
                             (ESTADOS_POR_FAZER, False),
                             (ESTADOS_FEITO, True)):
        if termo in lista:
            return veredicto
    return None


#: Um `|` que **nao** esta escapado, e portanto separa celulas.
_SEPARADOR_DE_CELULA = re.compile(r"(?<!\\)\|")


def celulas(linha: str) -> list[str]:
    """As celulas de uma linha de tabela, respeitando o `\\|` escapado.

    **A primeira versao partia em `|` nu**, e uma celula com `\\|` dentro
    deslocava todas as seguintes — o indice da coluna de `Estado`, que vem do
    cabecalho, passava a apontar para outra celula. Medido pela revisao
    adversarial: `KAM-039` tem `\\`grep\\` por \\`vendedor\\|servicos\\|...\\``
    numa celula antes do `Estado`, e o *lint* lia `'servicos\\'` como estado.
    Degradava para «nao medido» e nao para achado falso, mas a mensagem enganava
    quem a lesse.
    """
    partes = _SEPARADOR_DE_CELULA.split(linha)[1:-1]
    return [c.replace("\\|", "|").strip() for c in partes]


@dataclass(frozen=True)
class Caixa:
    """Uma linha `- [ ]` ou `- [x]` de uma das duas listas."""

    marcada: bool
    texto: str
    numero: int


@dataclass(frozen=True)
class Tabela:
    """Uma tabela de verificacao, com a coluna de estado localizada."""

    #: `'criterios'`, `'dod'` ou `'sem_assunto'`.
    especie: str
    cabecalho: tuple[str, ...]
    #: Uma entrada por linha de corpo: a celula de estado, como esta escrita.
    estados: tuple[str, ...]
    numero: int

    @property
    def classes(self) -> tuple[bool | None, ...]:
        return tuple(classificar_estado(e) for e in self.estados)


@dataclass
class Bloco:
    """Um bloco de ticket, nas duas superficies."""

    id: str
    ficheiro: str
    numero: int
    criterios: list[Caixa] = field(default_factory=list)
    dod: list[Caixa] = field(default_factory=list)
    tabelas: list[Tabela] = field(default_factory=list)

    @property
    def onde(self) -> str:
        return f"{self.ficheiro}:{self.numero}"

    def tabela(self, especie: str) -> Tabela | None:
        """A **primeira** tabela daquela especie.

        Primeira e nao unica: um bloco pode ter mais tabelas com a mesma forma
        (o KAM-016 tem uma de achados da revisao adversarial com `| # | …`), e a
        que conta e a que vem antes — a que responde aos critérios.
        """
        for tabela in self.tabelas:
            if tabela.especie == especie:
                return tabela
        return None


def _especie_da_tabela(cabecalho: list[str]) -> str | None:
    """`'criterios'`, `'dod'`, `'sem_assunto'`, ou `None` sem coluna `Estado`."""
    limpas = [limpo(c) for c in cabecalho]
    if COLUNA_DE_ESTADO not in limpas:
        return None
    # **Igualdade, nao sub-cadeia** — ver o comentario de `COLUNAS_DE_ASSUNTO`.
    if any(c in COLUNA_DA_DOD for c in limpas):
        return "dod"
    if any(c in COLUNAS_DE_ASSUNTO for c in limpas):
        return "criterios"
    # Tem coluna `Estado` e nenhuma coluna de assunto que se reconheca. **Nao e
    # «sem coluna de Estado»**, e a diferenca importa para a mensagem: o bloco
    # tem a superficie e o *lint* nao sabe o que ela tabula.
    return "sem_assunto"


def _tabelas(linhas: list[tuple[int, str]]) -> list[Tabela]:
    """As tabelas com coluna de `Estado`, pela ordem do ficheiro."""
    saida: list[Tabela] = []
    indice = 0
    while indice < len(linhas) - 1:
        numero, linha = linhas[indice]
        seguinte = linhas[indice + 1][1]
        if not (linha.startswith("|") and SEPARADOR.match(seguinte)):
            indice += 1
            continue
        cabecalho = celulas(linha)
        especie = _especie_da_tabela(cabecalho)
        coluna = (
            [limpo(c) for c in cabecalho].index(COLUNA_DE_ESTADO)
            if especie else None
        )
        estados: list[str] = []
        corpo = indice + 2
        while corpo < len(linhas) and linhas[corpo][1].startswith("|"):
            if especie is not None:
                cel = celulas(linhas[corpo][1])
                estados.append(cel[coluna] if coluna < len(cel) else "")
            corpo += 1
        if especie is not None:
            saida.append(Tabela(especie=especie,
                                cabecalho=tuple(cabecalho),
                                estados=tuple(estados),
                                numero=numero))
        indice = corpo
    return saida


def _caixas(linhas: list[tuple[int, str]]) -> list[Caixa]:
    saida: list[Caixa] = []
    for numero, linha in linhas:
        achado = CAIXA.match(linha)
        if achado:
            saida.append(Caixa(marcada=achado.group(1).lower() == "x",
                               texto=achado.group(2).strip(),
                               numero=numero))
    return saida


def _blocos_do_texto(texto: str, rel: str) -> list[Bloco]:
    """Os blocos de um ficheiro, com as duas superficies lidas.

    **Salta cercas, e com a gramatica do `lint_backlog` e nao com uma propria**:
    o bloco de *handoff* e cercado e tem linhas que parecem caixas e tabelas, e
    duas gramaticas para «o que e uma cerca» era a forma garantida de dois
    passos discordarem sobre o mesmo bloco — e a razao pela qual aquele modulo
    tornou o `fora_de_cerca` publico.
    """
    visiveis = list(fora_de_cerca(texto))
    blocos: list[Bloco] = []
    actual: Bloco | None = None
    seccao: str | None = None
    corpo: list[tuple[int, str]] = []
    por_seccao: dict[str, list[tuple[int, str]]] = {}

    def fechar() -> None:
        if actual is None:
            return
        actual.criterios = _caixas(por_seccao.get(TITULO_DOS_CRITERIOS, []))
        actual.dod = _caixas(por_seccao.get(TITULO_DA_DOD, []))
        actual.tabelas = _tabelas(corpo)
        blocos.append(actual)

    for numero, linha in visiveis:
        cabeca = TITULO_DE_BLOCO.match(linha)
        if cabeca:
            fechar()
            actual = Bloco(id=cabeca.group(1), ficheiro=rel, numero=numero)
            seccao, corpo, por_seccao = None, [], {}
            continue
        if actual is None:
            continue
        corpo.append((numero, linha))
        titulo = TITULO.match(linha)
        if titulo:
            # Um titulo de nivel 4 **nao** fecha a seccao de nivel 3: o
            # `#### Definition of Done` de dentro da seccao de verificacao e uma
            # tabela, nao a lista de caixas, e tomar o seu titulo por inicio de
            # lista roubava as caixas a lista verdadeira.
            if titulo.group(1) == "###":
                seccao = titulo.group(2)
                por_seccao.setdefault(seccao, [])
            continue
        if seccao is not None:
            por_seccao[seccao].append((numero, linha))
    fechar()
    return blocos


def ler_blocos(raiz: Path) -> list[Bloco]:
    """Todos os blocos dos dois sitios onde vivem.

    **Os dois, e nao um.** Com um glob so, o gate ficava verde sobre os dez
    epics e nao via os blocos do EPIC-01 — o defeito que o KAM-155 abriu no
    `lint_handoff` e no `lint_backlog`, e que nos dois ja esta fechado.
    """
    blocos: list[Bloco] = []
    pasta = raiz / TICKETS
    if not pasta.is_dir():
        raise BlocoIlegivel(f"pasta em falta: {TICKETS}")
    for caminho in sorted(pasta.glob("KAM-*.md")):
        rel = caminho.relative_to(raiz).as_posix()
        blocos += _blocos_do_texto(caminho.read_text(encoding="utf-8"), rel)
    epics = sorted(raiz.glob(EPICS))
    if not epics:
        raise BlocoIlegivel(f"nenhum epic encontrado em {EPICS}")
    for caminho in epics:
        rel = caminho.relative_to(raiz).as_posix()
        blocos += _blocos_do_texto(caminho.read_text(encoding="utf-8"), rel)
    return blocos
