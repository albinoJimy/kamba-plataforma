"""Os numeros de negocio, e a razao de este modulo correr **antes** do detector.

O criterio 4 do KAM-112 e o mais duro do bloco e e onde esta o valor do ticket:
«em >= 200 casos adversariais, 0 precos, totais, quantidades, horas ou `sku`
alterados». Precos, totais, quantidades, horas e `sku` sao *facts* de negocio
(ADR-007) e **so saem de tools**; um detector que mascare um preco destroi o
produto, porque o modelo deixa de poder citar o numero que a tool lhe deu e o
validador de citacao (KAM-032) recusa a resposta.

## A ordem e a barreira, e nao a qualidade das expressoes

A primeira forma de escrever isto — detectar PII e depois «ter cuidado» com os
numeros — nao consegue dar zero: basta um telefone e um preco com a mesma forma
para que a decisao seja uma aposta. «912.500.000 Kz» e um total de nove digitos e
e tambem, caracter a caracter, um movel angolano valido.

Por isso o desenho e o inverso: este modulo **reclama intervalos** do texto, e o
`detector.py` so procura PII no que ficou **por reclamar**. Um preco nao e
mascarado porque o detector nunca o ve. O «0 alterados» passa a ser uma
propriedade da construcao e nao um resultado de medicao — e a medicao dos 200
casos existe para provar que a construcao e a que eu digo que e, nao para
descobrir se calhou bem.

## O que se reclama, e o que deliberadamente nao se reclama

Reclama-se so o que o criterio nomeia, mais o que e indissociavel dele:

| Reclamado | Porque |
|---|---|
| numero junto a marcador de moeda | precos e totais — «12.500 Kz», «Kz 12.500», «912.500.000 Kz» |
| quantidade com multiplicador | «2 x 3.500», «3x», «x 2» — o criterio nomeia «2 x 3.500» |
| numero com unidade | «2 kg», «500 g», «1,5 l», «3 unidades» |
| hora | «as 15h30», «15:30», «9h», «15 h 30» |
| data | «12/03», «12-03-2026» — nao esta no criterio e entra, ver abaixo |
| percentagem | «20%» — nao esta no criterio e entra, ver abaixo |
| `sku` | codigo alfanumerico com letras **e** digitos |

**A data e a percentagem nao estao no criterio 4 e entram, e isso e alargar.**
E a excepcao que o §1.4 da skill permite — «tecnicamente necessaria, justificada
e registada» — e a justificacao e esta: `12/03/2026` e, caracter a caracter, uma
forma de NIF e de muitos codigos; `20%` nao, mas `2026` isolado parece um ano e
um preco. Deixar as duas fora nao tornava o criterio 4 falso, tornava **o
criterio 2 destrutivo** sobre texto comercial banal («a promocao e de 12/03 a
20/03»). O que nao se faz e o inverso — reclamar um intervalo largo «por
precaucao» —, porque cada intervalo reclamado e PII que **nao** se mascara, e um
reclamador generoso e um buraco na minimizacao. Ver o `reclamar_demais` abaixo.

## O risco deste modulo e simetrico, e e por isso que ele tem dois testes

Um intervalo reclamado a mais **esconde PII do detector**. Um telefone escrito
«912500000 Kz» nunca seria mascarado — e um cliente pode escrever isso por erro.
A bateria mede os dois lados: o `test_minimizacao` corre os 200 casos de numeros
(nenhum alterado) **e** corre o corpus de PII (recall), e nenhum dos dois numeros
se pode subir a custa do outro. O caso «telefone colado a um marcador de moeda»
esta no corpus como **LIMITE** declarado, com a sua linha, pela mesma forma que o
KAM-032 declarou os limites do validador: e risco residual medido, nao defeito
escondido.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Final

from .dicionarios import dobrar

#: Marcadores de moeda, na forma dobrada. O `kz` e o do produto (`docs/tecnica/`
#: usa `Kz` por extenso e `*_minor` em codigo); os outros entram porque um cliente
#: escreve o que quiser e um preco em dolares continua a ser um preco.
#:
#: **Nao se usa `\b` a volta de `$` e `€`**: nao sao caracteres de palavra e o
#: `\b` nunca casaria do lado deles.
MOEDAS_PALAVRA: Final = ("kz", "akz", "aoa", "kwanzas", "kwanza", "usd", "eur")
MOEDAS_SIMBOLO: Final = ("$", "€")

#: Unidades de quantidade. So as que aparecem em comercio, e **todas curtas**:
#: uma lista longa reclama mais texto, e reclamar e esconder.
UNIDADES: Final = (
    "kg", "g", "gr", "mg", "l", "ml", "cl", "dl", "m", "cm", "mm", "km",
    "un", "und", "uni", "unid", "unidade", "unidades", "pack", "packs",
    "caixa", "caixas", "duzia", "duzias", "par", "pares", "saco", "sacos",
    "garrafa", "garrafas", "lata", "latas", "fardo", "fardos",
)

#: Um numero como o cliente o escreve: digitos com pontos, virgulas ou espacos
#: como separador de milhares, e virgula ou ponto decimal. Sem ancoras.
#:
#: **O espaco como separador de milhares esta aqui de proposito** («12 500 Kz»),
#: e e tambem a forma de um telefone («912 345 678»). Nao ha conflito porque este
#: padrao so reclama quando ha um **marcador** ao lado; sozinho nao reclama nada.
#:
#: **O `+` da primeira alternativa era um `*`, e o `*` truncava numeros.** Com
#: `*`, a primeira alternativa casava `\d{1,3}` e zero grupos de milhares — isto
#: e, os **tres primeiros digitos** de qualquer numero —, e a alternancia da
#: expressao regular prefere a primeira que case. Em `Kz 912500000`, o `PRECO`
#: reclamava `kz 912` e nao `kz 912500000`: nove digitos de um total ficavam por
#: reclamar, o detector via-os, e o total **saia mascarado como telefone** nos dez
#: casos da familia `preco_que_parece_telefone` — exactamente o caso que o bloco
#: nomeia por extenso.
#:
#: Com `+`, a primeira alternativa so casa um numero **com** separador de
#: milhares (`12.500`, `12 500`, `912.500.000`) e o resto cai na segunda, que
#: leva o grupo de digitos inteiro (`912500000`, `7,50`, `250,00`).
#:
#: **Quem revelou isto foi o `_na_fronteira`**, e vale dizer porque: a
#: reclamacao truncada acabava a meio de um grupo de digitos, a regra de fronteira
#: recusou-a, e a recusa apareceu como dez casos vermelhos no corpus. Sem a regra,
#: a reclamacao curta era aceite, o `912` ficava protegido, o `500000` nao, e o
#: resultado era um total meio mascarado — uma falha mais calada e pior.
_NUMERO: Final = r"\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"

#: Um numero com marcador de moeda, dos dois lados. A moeda pode vir antes
#: («Kz 12.500») ou depois («12.500 Kz»), que e como as duas se escrevem em
#: Angola.
_MOEDAS_ALTERNATIVA: Final = "|".join(
    [*(re.escape(m) for m in MOEDAS_SIMBOLO), *(rf"{m}\b" for m in MOEDAS_PALAVRA)]
)
PRECO: Final = re.compile(
    rf"(?:(?:{_MOEDAS_ALTERNATIVA})\s*(?:{_NUMERO}))"
    rf"|(?:(?:{_NUMERO})\s*(?:{_MOEDAS_ALTERNATIVA}))",
    re.IGNORECASE,
)

#: «2 x 3.500», «2x3500», «3x», «x 2». O `x` e o `*` sao os dois que alguem
#: escreve. **O segundo numero entra no mesmo intervalo**: num «2 x 3.500» o
#: 3.500 e o preco unitario, e reclamar so o «2 x» deixava-o ao detector.
#:
#: Tambem aqui as fronteiras sao do `_na_fronteira` e nao deste padrao.
QUANTIDADE: Final = re.compile(
    rf"(?:{_NUMERO})\s*[x*]\s*(?:{_NUMERO})"
    rf"|(?:{_NUMERO})\s*[x*](?![a-z])"
    rf"|[x*]\s*(?:{_NUMERO})",
    re.IGNORECASE,
)

#: Um numero com unidade: «2 kg», «500 g», «1,5 l», «3 unidades».
UNIDADE = re.compile(
    rf"(?:{_NUMERO})\s*(?:{'|'.join(UNIDADES)})\b",
    re.IGNORECASE,
)

#: Horas: «15h30», «15:30», «9h», «15 h 30», «15h30m». O criterio nomeia
#: «as 15h30».
HORA: Final = re.compile(
    r"\d{1,2}\s*(?:h|:)\s*\d{2}\s*(?:m|min)?|\d{1,2}\s*h\b",
    re.IGNORECASE,
)

#: Datas numericas: «12/03», «12-03-2026», «12.03.2026». **Nao** se reclama
#: «2026» sozinho: um ano isolado e indistinguivel de um numero qualquer, e
#: reclamar quatro digitos soltos era reclamar meio texto.
DATA: Final = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?\b")

#: Percentagens.
PERCENTAGEM: Final = re.compile(rf"(?:{_NUMERO})\s*%")

#: Um `sku`: um codigo com letras **e** digitos, eventualmente com hifen ou
#: barra. A exigencia de ter letras **e** digitos e o que o separa de um telefone
#: — `912345678` nao casa, `SKU-912345678` casa.
#:
#: **Nao casa um BSUID**, e quem o garante e o `_na_fronteira` e nao este padrao.
#: Ver a nota dele: as guardas por padrao foram tentadas e falharam tres vezes.
SKU: Final = re.compile(
    r"\b(?=[a-z0-9\-/]*\d)(?=[a-z0-9\-/]*[a-z])[a-z0-9]+(?:[-/][a-z0-9]+)*\b",
    re.IGNORECASE,
)

#: As expressoes por ordem de aplicacao. A ordem importa onde dois padroes se
#: sobrepoem: o `PRECO` corre antes da `QUANTIDADE` para que «2 x 3.500 Kz`
#: reclame o preco inteiro, e o `SKU` corre **ultimo** porque e o mais largo dos
#: sete e nao deve decidir a forma de um intervalo que outro ja explica melhor.
REGRAS: Final = (
    ("preco", PRECO),
    ("hora", HORA),
    ("data", DATA),
    ("percentagem", PERCENTAGEM),
    ("quantidade", QUANTIDADE),
    ("unidade", UNIDADE),
    ("sku", SKU),
)

#: O tecto de texto que este modulo aceita reclamar, em fraccao do total. Acima
#: disto, `reclamar` levanta.
#:
#: **E uma barreira contra o modo de falha deste modulo e nao uma optimizacao.**
#: Um intervalo reclamado e PII que nao se mascara; um padrao que, por um erro
#: numa expressao, reclamasse o texto inteiro fazia o `minimise` devolver o
#: original **sem mascarar nada** e sem falhar — a pior falha possivel neste
#: ticket, porque e silenciosa e passa por sucesso. Com este tecto, esse erro
#: falha fechado (criterio 7) em vez de transferir dados.
#:
#: O valor e ***proposta***: 0,9 e folgado de proposito, porque uma mensagem
#: legitima **pode** ser quase toda numeros («2x500, 3x250, 1x1000, total 2750
#: Kz»). O que ele apanha e a expressao que reclama **tudo**, que e o defeito
#: real. Calibra-se no Piloto (KAM-109) contra mensagens verdadeiras.
#:
#: shortcut: tecto folgado (0,9) que so apanha a expressao que reclama o texto
#: inteiro; revê-se no KAM-109 com mensagens reais do Piloto.
FRACCAO_MAXIMA: Final = 0.9

#: Abaixo deste comprimento o tecto nao se aplica: «12.500 Kz» e 100% preco e
#: esta certo. O tecto existe para mensagens, nao para fragmentos.
COMPRIMENTO_MINIMO_DO_TECTO: Final = 40


class ReclamouDemais(RuntimeError):
    """Os intervalos de negocio cobrem quase todo o texto.

    Nao e um erro do cliente: e o sinal de que uma das sete expressoes deste
    modulo esta errada. Sobe, o `minimise` converte-o em falha fechada, e o turno
    vai ao modo deterministico — porque a alternativa era devolver texto nao
    minimizado a dizer que estava minimizado.
    """


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class Intervalo:
    """Um intervalo reclamado, em indices do texto **original**.

    O `order=True` e para o `sorted` da fusao; a `regra` vem depois dos indices
    de proposito, para que a ordem seja posicional.
    """

    inicio: int
    fim: int
    regra: str = ""

    def cobre(self, inicio: int, fim: int) -> bool:
        """Este intervalo sobrepoe-se a `[inicio, fim)`?

        **Sobreposicao e nao contencao**, e e a pergunta certa: um telefone que
        comece dentro de um preco e acabe fora dele continua a ser um telefone
        que nao se pode mascarar sem partir o preco.
        """
        return inicio < self.fim and fim > self.inicio


def _fundir(intervalos: list[Intervalo]) -> tuple[Intervalo, ...]:
    """Junta intervalos que se toquem, para que a contagem de cobertura seja real.

    Sem a fusao, sete regras a casar o mesmo «12.500 Kz» davam sete intervalos e
    uma cobertura de 700% — e o tecto do `FRACCAO_MAXIMA` levantava sobre texto
    conforme. A fusao e o que torna a fraccao mensuravel.
    """
    if not intervalos:
        return ()
    ordenados = sorted(intervalos)
    fundidos = [ordenados[0]]
    for actual in ordenados[1:]:
        ultimo = fundidos[-1]
        if actual.inicio <= ultimo.fim:
            if actual.fim > ultimo.fim:
                regra = ultimo.regra if ultimo.regra == actual.regra else "varias"
                fundidos[-1] = Intervalo(ultimo.inicio, actual.fim, regra)
        else:
            fundidos.append(actual)
    return tuple(fundidos)


def _na_fronteira(dobrado: str, inicio: int, fim: int) -> bool:
    """Este intervalo comeca e acaba num sitio onde um numero de negocio pode?

    **E a barreira que substituiu tres remendos, e a historia e o argumento.** As
    sete expressoes acima podem casar a **meio** de um simbolo que nao e numero
    de negocio nenhum, e cada vez que isso acontece o intervalo reclamado
    **esconde PII do detector** — o modo de falha que o cabecalho deste modulo
    descreve. Aconteceu tres vezes, as tres sobre BSUID, as tres medidas contra o
    corpus:

    | Texto | Quem reclamava | O que saia em claro |
    |---|---|---|
    | `AO.abc123def456` | `SKU`, no `abc123def456` | o BSUID inteiro |
    | `PT.x9k2m4p8q1` | `QUANTIDADE`, no `x9` | o BSUID inteiro |
    | `PT.d4s3a2z1x0` | `QUANTIDADE`, no `1x0` | o BSUID inteiro |

    As duas primeiras foram emendadas com uma guarda **no padrao**
    (`(?<!\\.)` no `SKU`, `(?<![a-z0-9.])` numa alternativa da `QUANTIDADE`), e a
    terceira apareceu logo a seguir noutra alternativa do mesmo padrao. Tres
    defeitos da mesma familia e dois remendos que nao a cobriam e o sinal de que
    o problema nao estava nos padroes: estava em **nao haver regra de fronteira**.
    As guardas foram retiradas e isto ficou no lugar delas.

    A regra, e porque e assimetrica:

    * **a esquerda** recusa-se letra, digito **ou ponto**. Letra e digito porque
      um numero de negocio nao comeca a meio de uma palavra nem de um numero
      maior; o ponto porque e o separador do BSUID (`PT.`) — e e exactamente o
      caracter que os tres defeitos atravessaram;
    * **a direita** recusa-se letra ou digito, **mas nao pontuacao**. Um preco
      acaba a toda a hora antes de um ponto final (`12.500 Kz.`) e recusar isso
      deixava de reclamar o preco — que e o defeito simetrico e pior.

    Nao se usa `\\b`: um `\\b` depois de um ponto e uma fronteira valida, que e
    precisamente como os tres defeitos passaram.
    """
    if inicio > 0:
        anterior = dobrado[inicio - 1]
        if anterior.isalnum() or anterior in "._":
            return False
    if fim < len(dobrado):
        seguinte = dobrado[fim]
        if seguinte.isalnum():
            return False
    return True


def reclamar(texto: str) -> tuple[Intervalo, ...]:
    """Os intervalos de `texto` que sao numeros de negocio e nao se mascaram.

    Corre sobre a forma **dobrada** — que tem o mesmo comprimento que o original
    (`dicionarios.dobrar`) — para que um preco escrito com digitos Unicode
    («١٢٥٠٠ Kz») seja reclamado pelos mesmos indices. Os indices devolvidos valem
    no texto original.

    Levanta `ReclamouDemais` quando a cobertura passa o `FRACCAO_MAXIMA`.
    """
    dobrado = dobrar(texto)
    encontrados = [
        Intervalo(achado.start(), achado.end(), nome)
        for nome, expressao in REGRAS
        for achado in expressao.finditer(dobrado)
        if _na_fronteira(dobrado, achado.start(), achado.end())
    ]
    intervalos = _fundir(encontrados)
    if len(texto) >= COMPRIMENTO_MINIMO_DO_TECTO:
        coberto = sum(i.fim - i.inicio for i in intervalos)
        if coberto > FRACCAO_MAXIMA * len(texto):
            raise ReclamouDemais(
                f"os intervalos de negocio cobrem {coberto}/{len(texto)} "
                f"caracteres, acima de {FRACCAO_MAXIMA:.0%}"
            )
    return intervalos


def reclamado(intervalos: tuple[Intervalo, ...], inicio: int, fim: int) -> bool:
    """`[inicio, fim)` toca algum intervalo de negocio?

    E a pergunta que o `detector.py` faz antes de aceitar um achado, e a unica
    via pela qual o criterio 4 se cumpre.
    """
    return any(intervalo.cobre(inicio, fim) for intervalo in intervalos)
