"""Citacoes de seccao (`§N`) resolvidas contra os titulos do documento citado.

Entra no gate 3 pelo `lint_refs check`, e nao num *job* novo: um *job* novo
acrescenta um contexto exigido ao *ruleset* de `main`, que e alteracao de regra
de bloqueio.

## Porque isto existe

O `lint_refs` resolve `KAM-NNN`, `ADR-NNN` e `D#`; o `lint_handoff` resolve os
caminhos dos blocos de *handoff*. **Nenhum dos seis linters resolvia um `§N`** —
e um bloco que escreve «§18» esta a fazer uma afirmacao verificavel,
exactamente como um que escreve um caminho.

Medido no KAM-169 (PR #94): dez citacoes de seccao erradas atravessaram **duas**
passagens dos seis linters, todos a sair 0. Uma delas estava no bloco de
*handoff*, a instruir o executor seguinte a «nao apagar a linha de risco do
§12» — a proteger uma linha que nao vive nessa seccao.

## O que este portao apanha, e o que nao apanha

A familia parte-se em duas sub-classes, e so uma e mecanizavel:

| Sub-classe | Exemplo | Mecanizavel? |
|---|---|---|
| **a seccao nao existe** | `docs/logs.md` §7.14, quando o `logs.md` tem §7 e nao tem §7.14 | **sim** — e o que este modulo faz |
| **a seccao existe e e a errada** | «a linha de risco do §12», quando o risco esta no §18 | nao |

As dez do KAM-169 eram da **segunda** sub-classe: o §12 e o §16 do
`docs/tecnica/10` existem (sao «Segmento A vs B» e «Metricas de governacao»),
pelo que resolvem e este portao deixa-as passar. Diz-se por escrito em vez de
se deixar supor o contrario.

A unica verificacao candidata para a segunda sub-classe — exigir que um
identificador citado ao lado de um `§N` ocorra **dentro** dessa seccao, que
apanharia as seis do «PA-GOV-4 do §16» — foi medida sobre a arvore e
**recusada**: 19 pares verificaveis, **7 falsos positivos** (um `KAM-111` e um
`§6.4` na mesma celula de `docs/dividas-documentais.md` sem relacao entre si).
Uma verificacao que precisa de dispensas para passar nao e um portao; e uma
nota, e vale mais dize-lo.

O que o portao fecha, medido na `main` de 2026-11-02: **nove** citacoes que nao
resolvem, em 3 629 enderecaveis. Todas corrigidas no PR deste ticket, sem uma
unica dispensa em `ci/refs-allow.yaml`.

## A regra de enderecabilidade

Uma citacao e **enderecavel** — e so entao verificavel — quando as quatro
condicoes se verificam. O que nao for enderecavel nao pode dar falso positivo,
que e a fronteira que torna isto um portao e nao um incomodo.

1. **Ha um designador de documento ao lado**, e ele tem separador de
   directorio: um caminho para um `.md` seguido pelo git, ou um caminho
   truncado ao prefixo do nome (`docs/tecnica/10`, `../specs/EPIC-07`) que
   resolva para **exactamente um** ficheiro seguido. Resolve-se primeiro
   relativo a pasta do ficheiro citante, depois relativo a raiz.

   Fora, de proposito: o `§8` nu dentro do proprio documento (nao nomeia
   documento nenhum), e o cuneo abreviado sem pasta — `` `00` §12 `` —, que
   e ambiguo entre `docs/tecnica/00`, `specs/00_KAMBA_Carta.md` e
   `specs/00_System_Spec.md` e so se resolveria com um mapa de apelidos escrito
   a mao. Sao **5 489 das 8 157** ocorrencias de `§N` do conjunto documental da
   `main` (153 ficheiros de `specs/`, `docs/` e `README.md`, menos os dois
   registos datados); ficam sem portao, e isso esta dito.

2. **O documento citado tem titulos numerados** (`^#{2,4} N[.N[.N]]`). Um que
   nao tenha e um *stub* de um documento que vive noutro repositorio —
   `docs/isolamento.md` e `docs/seguranca/*` apontam para o `albinoJimy/kamba`
   privado, com o caminho de proposito igual «para que as citacoes espalhadas
   pelo conjunto continuem a resolver». As onze citacoes para eles nao sao
   defeito: a seccao existe, nao e aqui que ela esta.

3. **A citacao esta fora de um bloco de codigo cercado**, com a mesma reserva do
   `scan.py`: um numero impar de cercas desliga a dispensa e varre-se tudo.

4. **O numero resolve** se for um numero de titulo **ou o prefixo de um**. O
   `docs/exploracao/06` numera `### 3.1` sob um `## Camada 3 — Dinheiro` que
   nao leva numero: o `§3` e a seccao-contentor, e existe. Sem esta regra as
   duas citacoes para ele eram falsos positivos.

## Corpus

Tudo o que o git segue, **menos** `docs/analises/` e `docs/evidencia/`. Os dois
sao registos datados — uma analise diz o que estava errado no dia em que foi
escrita, e corrigi-la reescreve o registo em vez de o preservar.
"""

from __future__ import annotations

import dataclasses
import posixpath
import re

#: A deteccao do bloco de *handoff* vem do `lint_handoff`, que ja corre no mesmo
#: *gate* 3 e ja entra nesses blocos para resolver caminhos. O precedente de
#: importar entre ferramentas e o `lint_backlog`, que le o §4 pelo
#: `lint_refs.sets` desde o KAM-138, e pela mesma razao: duas gramaticas para a
#: mesma coisa era a forma garantida de as duas discordarem.
from lint_handoff.scan import blocos as lint_handoff_blocos

#: `§4`, `§20.1`, `§7.6.2`. Tres niveis, que e o que o conjunto usa
#: (`#### 7.6.2` existe tres vezes).
_SEC = r"§[0-9]+(?:\.[0-9]+){0,2}"

#: Designador de documento. **Exige separador de directorio** — e essa exigencia
#: que mantem o cuneo ambiguo (`` `00` ``) fora do portao.
_DESIGNADOR = (
    r"(?:\.{1,2}/)*"            # ../ ../../
    r"(?:[A-Za-z0-9_.-]+/)+"    # pelo menos uma pasta
    r"[A-Za-z0-9_.-]+"          # nome completo, ou prefixo do nome
)

#: Ruido admitido entre o designador e o `§`: o fecho de um `` ` ``, de um
#: `](...)` de *markdown*, um parentesis a abrir, espacos e uma virgula. E
#: deliberadamente curto: alargar isto e comecar a emparelhar um documento com
#: um `§` que pertence a outro.
_RUIDO = r"[`\]\)\(\s,]*"

#: Ordem A — o documento primeiro: `` `specs/INDICE.md` §4 ``.
_ORDEM_A = re.compile(rf"(?P<doc>{_DESIGNADOR})(?P<ruido>{_RUIDO})(?P<sec>{_SEC})")

#: Ordem B — o `§` primeiro: «o §12 do `docs/tecnica/10`». E a forma em que as
#: dez do KAM-169 foram escritas.
_ORDEM_B = re.compile(
    rf"(?P<sec>{_SEC})\s+(?:do|da|de|em|no|na)\s+[`\[]*(?P<doc>{_DESIGNADOR})"
)

#: Corrida de `§` depois do primeiro, separados so por virgula, «e», «ou» ou um
#: travessao: `` `08` (§4, §8.5, §9, §12) ``, «§11.2, §11.3, §18 e §20.1» e
#: «§8.3–§8.4» sao as formas normais de citar varias seccoes do mesmo
#: documento. Sem isto perdia-se tudo menos a primeira de cada lista — e o
#: travessao sozinho valia **70** linhas do conjunto, medidas pela revisao
#: adversarial do KAM-170 (achado A-10). Expandem-se as **pontas escritas**, nao
#: o interior: «§8.3–§8.4» da o 8.3 e o 8.4, e um intervalo nao diz quais sao os
#: numeros entre eles.
_CORRIDA = re.compile(rf"\s*(?:,|\be\b|\bou\b|–|—|-)?\s*(?P<sec>{_SEC})")

#: `## 18. Riscos e mitigacoes`, `### 20.1 Propostas de ADR`, `#### 7.6.2 …`.
#: O ponto final depois do numero e opcional: o conjunto escreve `## 4.` e
#: `### 4.1` (sem ponto) e os dois contam.
#:
#: E o proprio `§` no titulo e opcional, porque dois ADRs locais numeram assim:
#: `## §6 — Quando reverter, e o que falta nesta porta`
#: (`docs/adr/ADR-L002` e `ADR-L003`). Sem o `§?`, esses dois documentos nao
#: tinham titulo numerado nenhum e **o documento inteiro ficava inenderecavel**
#: pela condicao 2 — o que escondia um `§5` quebrado citado de
#: `libs/py-core/src/kamba_core/secrets/port.py`. Achado A-07 da revisao
#: adversarial do KAM-170.
_CABECALHO = re.compile(r"^#{2,4}\s+§?(?P<numero>[0-9]+(?:\.[0-9]+){0,2})\.?\s")

_CERCA = re.compile(r"^\s*```")

#: Registos datados: uma analise descreve o que estava errado no dia em que foi
#: escrita. Corrigir uma citacao la dentro reescreve o registo.
EXCLUIDOS = ("docs/analises/", "docs/evidencia/")


@dataclasses.dataclass(frozen=True)
class Citacao:
    """Uma citacao de seccao enderecavel."""

    linha: int
    #: O designador tal como esta escrito, para a mensagem de erro o devolver.
    designador: str
    #: O caminho relativo a raiz do documento a que se refere.
    destino: str
    #: O numero da seccao, sem o `§`.
    seccao: str
    contexto: str


def numeros_de_seccao(texto: str) -> frozenset[str]:
    """Os numeros dos titulos numerados de um documento.

    Vazio quando o documento nao numera titulos — e o sinal de que ele nao e
    enderecavel por `§` (condicao 2 da regra).
    """
    return frozenset(
        m.group("numero")
        for linha in texto.split("\n")
        if (m := _CABECALHO.match(linha))
    )


def resolve(numero: str, numeros: frozenset[str]) -> bool:
    """`§3` resolve se existir `## 3.` **ou** um `### 3.1` sob um titulo sem numero."""
    if numero in numeros:
        return True
    return any(outro.startswith(numero + ".") for outro in numeros)


class Resolvedor:
    """Designador de documento -> caminho relativo a raiz.

    Guarda o resultado por `(designador, pasta do citante)`. Sem a memoria, o
    varrimento da arvore inteira passava dos dois minutos: o mesmo
    `../docs/tecnica/00` e resolvido centenas de vezes, e o conjunto dos
    candidatos truncados varre-se por prefixo.
    """

    def __init__(self, seguidos: set[str]) -> None:
        #: So os `.md`: um `§` so e enderecavel num documento com titulos.
        self._seguidos = frozenset(s for s in seguidos if s.endswith(".md"))
        self._memoria: dict[tuple[str, str], str | None] = {}

    def __call__(self, designador: str, ficheiro_citante: str) -> str | None:
        pasta = posixpath.dirname(ficheiro_citante)
        chave = (designador, pasta)
        if chave not in self._memoria:
            self._memoria[chave] = self._resolver(designador, pasta)
        return self._memoria[chave]

    def _resolver(self, designador: str, pasta: str) -> str | None:
        # A condicao 1 vive **aqui** e no `_DESIGNADOR`, de proposito. Sem ela
        # aqui, um `` `00` `` citado de dentro de `docs/tecnica/` juntava-se a
        # pasta do citante e resolvia para `docs/tecnica/00_…` — o cuneo
        # ambiguo a entrar pela porta do lado. Apanhado por
        # `test_um_designador_sem_pasta_nao_e_enderecavel`, que falhou quando
        # a regra estava so no padrao.
        if "/" not in designador:
            return None

        candidatos: list[str] = []
        for base in (pasta, ""):
            # Normalizacao **lexical**: o `Path.resolve()` toca no disco a cada
            # chamada, e e o que tornava o varrimento inviavel.
            norm = posixpath.normpath(posixpath.join(base, designador))
            if norm.startswith(".."):
                continue
            if norm.endswith(".md"):
                if norm in self._seguidos:
                    return norm
                continue
            iguais = self._por_prefixo(norm)
            if len(iguais) == 1:
                candidatos.append(iguais[0])
        # Duas bases a dar dois destinos diferentes e ambiguidade, nao defeito.
        unicos = set(candidatos)
        return candidatos[0] if len(unicos) == 1 else None

    def _por_prefixo(self, truncado: str) -> list[str]:
        """`docs/tecnica/10` -> `docs/tecnica/10_Onboarding_Governanca.md`.

        Exige-se que o prefixo case o **nome do ficheiro** e nao so o caminho, e
        que acabe numa **fronteira** do nome — `_`, `-` ou `.`. Sem a fronteira,
        `docs/tecnica/1` resolvia em silencio para o `10_Onboarding…`, por ser o
        unico `1*` daquela pasta, quando quem escreve «doc 1» quer o
        `01_Canais…`: resolver para o documento errado e pior do que nao
        resolver. A fronteira cobre as tres formas que a casa usa —
        `10_Onboarding…`, `05-estrategia…` e `concierge.md`. Achado A-10 da
        revisao adversarial do KAM-170; o teste que protegia isto era sintetico,
        com um `11_*.md` que este repositorio nao tem.

        E exige-se **um** so resultado: `docs/tecnica/0` casa dez ficheiros e
        nao designa nenhum.
        """
        pasta, _, caule = truncado.rpartition("/")
        if not pasta or not caule:
            return []
        iguais = []
        for s in self._seguidos:
            if not s.startswith(pasta + "/"):
                continue
            nome = posixpath.basename(s)
            if not nome.startswith(caule):
                continue
            if nome[len(caule) : len(caule) + 1] not in ("_", "-", "."):
                continue
            iguais.append(s)
        return iguais


def linhas_de_handoff(texto: str) -> frozenset[int]:
    """Os numeros de linha que caem dentro de um bloco `### Handoff para Claude Code`.

    Estes blocos sao cercados por construcao — sao 170 em 65 ficheiros — e a
    condicao 3 saltava-os todos. Era o **pior** ponto cego possivel: e o unico
    sitio onde um `§N` da uma **ordem** ao executor seguinte, e a ocorrencia que
    motivou este portao vivia exactamente ali («NAO apagues a linha de risco do
    §12», `specs/tickets/KAM-169.md`, dentro da cerca). Um portao que nomeia o
    bloco de *handoff* como o caso que o motiva e nao o le e um portao que
    promete o que nao faz. Achado A-02 da revisao adversarial do KAM-170.

    A deteccao vem do `lint_handoff`, que ja entra nestes blocos para resolver
    os caminhos, e nao de uma gramatica propria: duas leituras de «o que e um
    bloco de *handoff*» era a forma garantida de os dois passos do *gate* 3
    discordarem sobre o mesmo bloco.
    """
    linhas = texto.split("\n")
    dentro: set[int] = set()
    for inicio, fim in lint_handoff_blocos(linhas):
        # `blocos` devolve indices de linha base-0, [inicio, fim); as linhas
        # contam-se de 1.
        dentro.update(range(inicio + 1, fim + 1))
    return frozenset(dentro)


def citacoes(
    texto: str,
    ficheiro: str,
    resolvedor: Resolvedor,
    dentro_do_handoff: frozenset[int] = frozenset(),
) -> list[Citacao]:
    """As citacoes de seccao enderecaveis de um texto."""
    encontradas: list[Citacao] = []
    # Sem um `§` nao ha nada a emparelhar, e os padroes do designador tem
    # quantificadores encaixados que retrocedem muito em ficheiros de codigo
    # cheios de caminhos. O numero esta na secao «O custo» da docstring.
    if "§" not in texto:
        return encontradas
    linhas = texto.split("\n")

    # Mesma reserva do `scan.py`: uma cerca aberta e nunca fechada cegava o
    # resto do ficheiro, e um `.md` com cercas desequilibradas produz isto por
    # acidente. Com um numero impar, varre-se tudo.
    ignorar_cercas = sum(1 for linha in linhas if _CERCA.match(linha)) % 2 == 0

    # Que linhas se varrem, decidido primeiro: a varredura por fronteira (mais
    # abaixo) precisa de saber se a linha **seguinte** tambem se varre, e um
    # interruptor consumido a meio do ciclo nao da essa resposta.
    varrer: list[bool] = []
    dentro_de_cerca = False
    for numero_linha, linha in enumerate(linhas, start=1):
        if _CERCA.match(linha):
            dentro_de_cerca = not dentro_de_cerca
            varrer.append(False)
            continue
        oculta = dentro_de_cerca and ignorar_cercas
        varrer.append(not oculta or numero_linha in dentro_do_handoff)

    vistos: set[tuple[int, str, str]] = set()

    def juntar(
        numero_linha: int, designador: str, destino: str, seccao: str, contexto: str
    ) -> None:
        if (numero_linha, destino, seccao) in vistos:
            return
        vistos.add((numero_linha, destino, seccao))
        encontradas.append(Citacao(numero_linha, designador, destino, seccao, contexto))

    def varrer_unidade(
        unidade: str, numero_linha: int, corte: int | None = None
    ) -> None:
        """Empareha designadores e `§` numa unidade de texto.

        `corte` restringe aos pares que **atravessam** essa posicao, e e como se
        varre a fronteira entre duas linhas sem repetir o que cada uma ja deu.
        """
        if "§" not in unidade:
            return
        contexto = " ".join(unidade.split())[:120]

        def aceita(inicio: int, fim: int) -> bool:
            return corte is None or (inicio < corte < fim)

        # A ordem B corre **primeiro**, e o que ela emparelhar fica-lhe.
        #
        # «`specs/02` §7.6.2 do `tecnica/06`» casa as duas ordens com o mesmo
        # `§`, e dao documentos **diferentes**: a A junta-o ao `specs/02` que
        # esta antes, a B ao `tecnica/06` que a preposicao nomeia. A B e que tem
        # razao — «do» nomeia o documento, a A so tem a vizinhanca — e sem esta
        # precedencia o gate acusava a seccao no documento errado. Medido sobre
        # o bloco deste ticket, que escreve essa frase.
        reclamados: set[int] = set()
        for correspondencia in _ORDEM_B.finditer(unidade):
            reclamados.add(correspondencia.start("sec"))
            if not aceita(correspondencia.start(), correspondencia.end()):
                continue
            designador = correspondencia.group("doc")
            destino = resolvedor(designador, ficheiro)
            if destino is None:
                continue
            juntar(
                numero_linha, designador, destino,
                correspondencia.group("sec")[1:], contexto,
            )

        for correspondencia in _ORDEM_A.finditer(unidade):
            if correspondencia.start("sec") in reclamados:
                continue
            designador = correspondencia.group("doc")
            destino = resolvedor(designador, ficheiro)
            if destino is None:
                continue
            if aceita(correspondencia.start(), correspondencia.end()):
                juntar(
                    numero_linha, designador, destino,
                    correspondencia.group("sec")[1:], contexto,
                )
            # A corrida: os `§` seguintes pertencem ao mesmo documento.
            posicao = correspondencia.end()
            while seguinte := _CORRIDA.match(unidade, posicao):
                if seguinte.start("sec") in reclamados:
                    break
                if aceita(correspondencia.start(), seguinte.end()):
                    juntar(
                        numero_linha, designador, destino,
                        seguinte.group("sec")[1:], contexto,
                    )
                posicao = seguinte.end()

    for indice, linha in enumerate(linhas):
        if not varrer[indice]:
            continue
        varrer_unidade(linha, indice + 1)

        # A fronteira entre esta linha e a seguinte. A prosa deste conjunto
        # muda de linha a ~80 colunas, pelo que um designador no fim de uma
        # linha e o `§` no inicio da outra e forma corrente e nao exotica:
        # `specs/EPIC-03_Agent_Runtime_Verticais.md:391` fecha com
        # `` `../docs/tecnica/06` `` e a 392 abre com `§7.6.2`, que nao existe
        # nesse documento — a gemea exacta de uma das citacoes que este ticket
        # corrige, a uma mudanca de linha de distancia, e o portao saia 0 com
        # ela. Achado A-03 da revisao adversarial do KAM-170.
        #
        # Duas linhas bastam: um designador mais um `§` nao atravessa tres.
        # Uma linha vazia nao se junta — separa paragrafos, e juntar atraves
        # dela emparelhava um documento de um paragrafo com um `§` do seguinte.
        if indice + 1 >= len(linhas) or not varrer[indice + 1]:
            continue
        if not linha.strip() or not linhas[indice + 1].strip():
            continue
        juncao = linha + " " + linhas[indice + 1]
        varrer_unidade(juncao, indice + 1, corte=len(linha))

    return encontradas


def token(citacao: Citacao) -> str:
    """A forma com que uma citacao se declara em `ci/refs-allow.yaml`.

    `§7.14@docs/logs.md` — a seccao **e** o destino, porque o mesmo `§7.14` esta
    certo num documento e errado noutro, e uma dispensa por numero so dispensava
    o conjunto todo de uma vez.
    """
    return f"§{citacao.seccao}@{citacao.destino}"
