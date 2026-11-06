"""As regras que comparam as duas superficies de um bloco, e a sua cobertura.

Duas regras, e a segunda e a que apanha o escape que deu origem a este *lint*:

    tabela_sem_par      a tabela de verificacao tem de ter **uma linha por
                        caixa** da lista que ela tabula. Uma linha a menos e um
                        item que saiu da verificacao sem que nada o diga.

    estado_contra_caixa a caixa `- [x]` e a celula de `Estado` tem de dizer o
                        mesmo, **par a par** e nao em contagem. Uma troca entre
                        duas linhas da a mesma contagem e e um defeito.

## O ESCAPE QUE ISTO FECHA, MEDIDO E NAO SUPOSTO

O KAM-082 abriu com as tabelas a dar **quatro** linhas como `marcada` e a lista
de caixas com **zero** `- [x]` em doze — as quatro provas escritas na coluna de
evidencia e as quatro caixas por marcar. Nenhum dos onze *jobs* de gate o leu;
apanhou-o quem verificou o PR, a olho, e **por ter cruzado os dois numeros**.

E custou uma fusao antes dessa: um bloco com «1 erro de conteudo» na caixa e «3»
na prosa do mesmo bloco, apanhado um dia depois por uma revisao adversarial
sobre outro ramo.

A regra desta casa e que «um escape que um portao podia ter apanhado vira
portao». Este e o portao — **entregue sem estar ligado**, porque ligar uma
verificacao que trava fusoes e alteracao de regra de bloqueio.

## O EMPARELHAMENTO E GUIADO PELOS DADOS, E A PRIMEIRA VERSAO NAO ERA

A primeira versao emparelhava a tabela de `Critério` com a lista de critérios, e
ponto. Deu **13 achados falsos**, e a causa mediu-se: ha blocos que tabulam os
critérios **e** a DoD numa **so** tabela com cabecalho `| # | Critério | Estado |
Evidência |` — o KAM-155 tem 8 caixas de critérios, 4 de DoD e **12** linhas.
Contra a lista dos critérios sozinha, aquilo lia-se como «quatro linhas a mais».

Por isso o emparelhamento prova as duas convencoes e **nao escolhe por palpite**:

    uma tabela de DoD propria   ->  critérios↔critérios e DoD↔DoD
    so a tabela de critérios    ->  tenta `len(linhas) == len(CA)`;
                                    senao tenta `len(CA) + len(DoD)`;
                                    se nenhuma casar, **ai** e achado

O que isto renuncia, dito: uma tabela combinada cujo numero de linhas por
coincidencia iguale o das caixas de critérios e emparelhada com a lista errada.
Nao ha daqui como as distinguir, e preferiu-se a convencao mais comum.

## O QUE ESTE *LINT* NAO MEDE, E PORQUE

A terceira comparacao que o pedido original nomeava — **os numeros escritos
dentro de uma caixa contra os mesmos numeros na prosa da celula de evidencia** —
**nao se implementou**. A razao esta em `docs/lint-bloco.md` §6, com a medicao:
nao se encontrou predicado que a meca sem gritar sobre blocos limpos. Fica
devolvida com a medicao, em vez de entregue a gritar.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lint_bloco import modelo

#: As regras, pelo nome com que aparecem num achado. Fixa no codigo e **nao**
#: lida das *fixtures*: um manifesto vazio nao pode dar «tudo verde».
REGRAS_OBRIGATORIAS = ("estado_contra_caixa",)

#: Quantos blocos, no minimo, tem de ser medidos para a saida valer algo.
#:
#: Sao **parametros** do `verificar` e nao constantes fechadas, pela razao do
#: `minimo` do `lint_backlog.ler_blocos`: as *fixtures* do canario sao arvores de
#: dois ou tres blocos, e um piso fechado tornava-as impossiveis de escrever —
#: o que empurrava o canario para fora da arvore real, que e onde ele vale menos.
#:
#: **Nao e enfeite.** Um `glob` que deixe de casar, um titulo de seccao que mude,
#: ou uma mudanca na forma do cabecalho das tabelas poem este *lint* a medir
#: **zero** blocos e a dizer «0 achados» — que se le como «esta tudo bem» e e a
#: falha que o `log_policy` e o `obs_lint` desta casa ja recusam. Medido a
#: 2026-11-06: **53** blocos emparelhados na `publico/main` e **54** com este
#: ticket dentro. O piso fica
#: abaixo com folga, para nao exigir emenda a cada bloco novo, e acima de zero
#: com muita.
MINIMO_DE_BLOCOS_MEDIDOS = 40

#: Quantos blocos existem, no minimo. O mesmo argumento, para a camada de baixo:
#: se o `ler_blocos` deixar de ver a populacao, o piso de cima podia continuar a
#: ser atingido por acidente. Medido: 182.
MINIMO_DE_BLOCOS = 150


class ConfiguracaoInvalida(RuntimeError):
    """Nao se conseguiu medir o suficiente para a saida valer algo."""


@dataclass(frozen=True)
class Achado:
    regra: str
    onde: str
    detalhe: str

    def __str__(self) -> str:
        return f"{self.onde}: {self.regra} — {self.detalhe}"


@dataclass(frozen=True)
class NaoMedido:
    """Um bloco, ou metade de um bloco, que o *lint* nao conseguiu medir.

    **Nao e um achado**, e a diferenca importa: um achado diz «isto esta
    errado», isto diz «isto nao foi olhado». Contam-se e nomeiam-se, porque um
    *lint* que nao diga o que nao mediu ensina a ler «0 achados» como «esta tudo
    bem».
    """

    bloco: str
    onde: str
    #: A categoria, para a saida agrupar. Um campo e nao um prefixo do texto:
    #: agrupar pelo inicio da frase dava «critérios 7» como categoria.
    categoria: str
    porque: str


@dataclass(frozen=True)
class Par:
    """Uma tabela emparelhada com a lista de caixas que ela tabula."""

    rotulo: str
    caixas: tuple[modelo.Caixa, ...]
    estados: tuple[str, ...]
    onde_tabela: str


def emparelhar(bloco: modelo.Bloco) -> tuple[list[Par], list[Achado],
                                             list[NaoMedido]]:
    """Que lista de caixas cada tabela do bloco tabula.

    Ver a secao «O emparelhamento e guiado pelos dados» no topo do modulo.
    """
    pares: list[Par] = []
    achados: list[Achado] = []
    nao_medidos: list[NaoMedido] = []

    tab_ca = bloco.tabela("criterios")
    tab_dod = bloco.tabela("dod")

    if tab_ca is None and tab_dod is None:
        nao_medidos.append(NaoMedido(
            bloco.id, bloco.onde, "sem tabela de verificacao com coluna `Estado`",
            "o bloco nao tem tabela de verificacao com coluna `Estado`"))
        return pares, achados, nao_medidos

    def exigir(tabela: modelo.Tabela, caixas: list[modelo.Caixa],
               rotulo: str) -> None:
        onde = f"{bloco.ficheiro}:{tabela.numero}"
        if not caixas:
            nao_medidos.append(NaoMedido(
                bloco.id, onde, "tabela sem lista de caixas",
                f"tem tabela de {rotulo} e nao tem lista de caixas de {rotulo}"))
            return
        if len(tabela.estados) != len(caixas):
            nao_medidos.append(NaoMedido(
                bloco.id, onde, "tabela sem correspondencia um-a-um com a lista",
                f"a tabela de {rotulo} tem {len(tabela.estados)} linha(s) e a "
                f"lista tem {len(caixas)} caixa(s): sem correspondencia um-a-um "
                "nao se emparelha"))
            return
        pares.append(Par(rotulo, tuple(caixas), tabela.estados, onde))

    if tab_dod is not None:
        # Ha tabela de DoD propria: cada lista contra a sua.
        if tab_ca is not None:
            exigir(tab_ca, bloco.criterios, "critérios")
        exigir(tab_dod, bloco.dod, "DoD")
        return pares, achados, nao_medidos

    # So a tabela de critérios: ela tabula os critérios, ou os critérios **e** a
    # DoD. Prova-se a primeira convencao e depois a segunda.
    onde = f"{bloco.ficheiro}:{tab_ca.numero}"
    linhas = len(tab_ca.estados)
    if linhas == len(bloco.criterios) and bloco.criterios:
        pares.append(Par("critérios", tuple(bloco.criterios), tab_ca.estados, onde))
    elif linhas == len(bloco.criterios) + len(bloco.dod) and bloco.criterios:
        pares.append(Par("critérios e DoD",
                         tuple(bloco.criterios) + tuple(bloco.dod),
                         tab_ca.estados, onde))
    elif not bloco.criterios:
        nao_medidos.append(NaoMedido(
            bloco.id, onde, "tabela sem lista de caixas",
            "tem tabela de verificacao e nao tem lista de caixas"))
    else:
        nao_medidos.append(NaoMedido(
            bloco.id, onde, "tabela sem correspondencia um-a-um com a lista",
            f"a tabela tem {linhas} linha(s) e nao casa nem com as "
            f"{len(bloco.criterios)} caixa(s) de critérios nem com as "
            f"{len(bloco.criterios) + len(bloco.dod)} de critérios mais DoD"))
    return pares, achados, nao_medidos


def _comparar(bloco: modelo.Bloco, par: Par, dispensas: frozenset[str]
              ) -> tuple[list[Achado], list[NaoMedido]]:
    """A regra `estado_contra_caixa`, par a par."""
    achados: list[Achado] = []
    nao_medidos: list[NaoMedido] = []
    for indice, (caixa, estado) in enumerate(zip(par.caixas, par.estados), start=1):
        classe = modelo.classificar_estado(estado)
        if classe is None:
            nao_medidos.append(NaoMedido(
                bloco.id, f"{bloco.ficheiro}:{caixa.numero}",
                "o vocabulario nao classifica a celula de Estado",
                f"{par.rotulo} {indice}: a celula de Estado e "
                f"{modelo.limpo(estado)[:40]!r}, que o vocabulario nao classifica"))
            continue
        if classe != caixa.marcada and bloco.id not in dispensas:
            achados.append(Achado(
                "estado_contra_caixa", f"{bloco.ficheiro}:{caixa.numero}",
                f"{par.rotulo} {indice}: a caixa esta "
                f"{'marcada' if caixa.marcada else 'por marcar'} e a tabela diz "
                f"{modelo.limpo(estado)[:40]!r} "
                f"({'cumprido' if classe else 'por cumprir'})"))
    return achados, nao_medidos


def verificar(raiz: Path, dispensas: frozenset[str] = frozenset(),
              minimo_blocos: int = MINIMO_DE_BLOCOS,
              minimo_medidos: int = MINIMO_DE_BLOCOS_MEDIDOS
              ) -> tuple[list[Achado], list[NaoMedido], dict[str, int]]:
    """Corre as duas regras sobre todos os blocos.

    `dispensas` sao os `KAM-NNN` declarados em `ci/bloco-allow.yaml`: blocos que
    **ja divergiam antes deste *lint* existir**. Nao se corrigem aqui, e a razao
    esta escrita no ficheiro — a caixa segue a tabela, e a tabela e a evidencia
    daquele ticket e nao deste.
    """
    blocos = modelo.ler_blocos(raiz)
    if len(blocos) < minimo_blocos:
        raise ConfiguracaoInvalida(
            f"li {len(blocos)} bloco(s) e esperam-se pelo menos "
            f"{minimo_blocos}. Ou um glob ou a forma do titulo deixaram de "
            "ver a populacao — e «0 achados» sobre o vazio e a falha que este "
            "lint existe para recusar")

    achados: list[Achado] = []
    nao_medidos: list[NaoMedido] = []
    medidos = 0
    ambiguas = 0
    for bloco in blocos:
        ambiguas += sum(1 for t in bloco.tabelas if t.especie == "ambigua")
        pares, a, n = emparelhar(bloco)
        achados += [x for x in a if bloco.id not in dispensas]
        nao_medidos += n
        for par in pares:
            a2, n2 = _comparar(bloco, par, dispensas)
            achados += a2
            nao_medidos += n2
        if pares:
            medidos += 1

    if medidos < minimo_medidos:
        raise ConfiguracaoInvalida(
            f"emparelharam-se {medidos} bloco(s) e esperam-se pelo menos "
            f"{minimo_medidos}. Uma mudanca na forma do cabecalho das "
            "tabelas poe este lint a medir quase nada e a dizer «0 achados»")

    numeros = {
        "blocos": len(blocos),
        "medidos": medidos,
        "achados": len(achados),
        "nao_medidos": len(nao_medidos),
        "tabelas_ambiguas": ambiguas,
        "dispensas": len(dispensas),
    }
    return achados, nao_medidos, numeros
