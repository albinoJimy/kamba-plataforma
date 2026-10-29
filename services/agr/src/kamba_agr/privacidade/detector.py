"""O detector local: regras, dicionarios e contexto. **Sem chamada externa.**

O bloco do KAM-112 di-lo pelo nome, e a razao e circular de um modo que vale
escrever: «um detector que chamasse um LLM externo seria ele proprio a
transferencia a evitar». Nao ha aqui rede, nao ha modelo, nao ha servico — ha
expressoes regulares, tres dicionarios e padroes de contexto.

## A ordem das estacoes, que e o desenho inteiro

```text
1. dobrar          minusculas, sem acentos, digitos Unicode -> ASCII
                   (comprimento preservado: os indices valem no original)
2. reclamar        os intervalos de numeros de negocio (negocio.py)
3. detectar        por tipo, do mais especifico para o menos
4. recusar         todo o achado que toque um intervalo reclamado
```

O passo 4 e o criterio 4, e e a unica razao por que «0 precos alterados» e uma
propriedade e nao um resultado. O passo 3 e o criterio 2.

**A ordem dentro do passo 3 importa, e e por especificidade:** o e-mail antes do
telefone (um e-mail pode conter nove digitos), o BSUID antes do `sku`, o telefone
antes da morada, e os nomes proprios **em ultimo**, porque sao o tipo com mais
falsos positivos e porque um nome que ja esta dentro de um achado anterior nao se
volta a contar. Cada achado aceite reclama o seu intervalo para os seguintes,
exactamente como o `negocio.py` reclama para todos.

## Os dois limiares nao sao do mesmo tamanho, e a assimetria e real

O criterio 3 pede recall >= 99% em telefone, BSUID, e-mail e NIF, e >= 90% em
moradas e nomes. Os quatro primeiros tem **forma**: um telefone angolano e nove
digitos que comecam por 9, um e-mail tem um `@`, um BSUID tem o prefixo. Os dois
ultimos tem **dicionario e contexto**, e um dicionario escrito a mao nao e uma
forma — um bairro que nao esteja na lista escapa, e um nome proprio sem contexto
de pessoa fica. Os dois limiares sao ***propostas*** do bloco e os dois se medem;
o que esta aqui explica porque e que nao se esperaria que fossem iguais.

## O NIF e um parametro, e isso e uma recusa deliberada de inventar

`docs/tecnica/08` nao define o formato do NIF angolano e o bloco manda **nao o
inventar** («padrao parametrizavel: `../docs/tecnica/08` nao o define e nao se
inventa»). Logo `PADRAO_DE_NIF` nasce `None`, e com `None` **o NIF nao e
detectado por padrao proprio** — o que faz o recall de NIF ser `0%` e nao `99%`,
e isso diz-se em voz alta em vez de se esconder.

E o precedente exacto do `make x11 X11_NIF='<regex>'` do KAM-068, que resolveu a
mesma ausencia da mesma maneira, no mesmo documento. Quem souber o formato
passa-o; a medicao diz, por escrito, que foi medida sem ele.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Final

from . import negocio
from .dicionarios import (
    APELIDOS,
    CONTEXTO_DE_LOCAL,
    CONTEXTO_DE_PESSOA,
    DIGITOS_POR_EXTENSO,
    LOCAIS,
    NOMES_PROPRIOS,
    dobrar,
)

#: Os seis tipos, e sao os seis do criterio 2. O nome do tipo e a raiz do token
#: (`TELEFONE` -> `TELEFONE_1`) e e **etiqueta de `pii_masked_total`**, pelo que
#: cada um tem de casar a gramatica de etiqueta em minusculas
#: (`^[a-z][a-z0-9_]{1,62}$`). Ha um teste que o verifica.
TELEFONE: Final = "TELEFONE"
BSUID: Final = "BSUID"
EMAIL: Final = "EMAIL"
NIF: Final = "NIF"
MORADA: Final = "MORADA"
PESSOA: Final = "PESSOA"

#: Lista **fechada**, pela ordem de deteccao (ver a nota do modulo).
TIPOS: Final = (EMAIL, BSUID, NIF, TELEFONE, MORADA, PESSOA)

#: Os tipos com limiar de 99% (criterio 3): tem **forma**, nao dicionario.
TIPOS_DE_FORMA: Final = (TELEFONE, BSUID, EMAIL, NIF)
#: Os tipos com limiar de 90% (criterio 3): dependem de dicionario e contexto.
TIPOS_DE_DICIONARIO: Final = (MORADA, PESSOA)

#: Um e-mail. Deliberadamente **mais largo** do que a RFC: o que custa aqui e
#: nao apanhar um e-mail, e um falso positivo sobre algo com `@` no meio de
#: texto comercial e improvavel e inofensivo (vira `EMAIL_1`).
EMAIL_PADRAO: Final = re.compile(
    r"[a-z0-9!#$%&'*+/=?^_`{|}~.\-]+@[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?)+"
)

#: Um BSUID na forma que a Meta **documenta**: duas letras, ponto, e
#: alfanumericos.
#:
#: **O codigo deste repositorio nao impoe essa forma, e a diferenca medi-la e
#: obrigatorio.** O `packages/core-ts/src/identity/cripto.ts` aceita
#: `^[\x21-\x7e]{1,256}$` — qualquer ASCII imprimivel — e di-lo por escrito
#: («nao se exige essa forma exacta, para que uma alteracao do formato pela Meta
#: nao se torne em mensagens recusadas»). Um detector com essa forma casava
#: **todo o texto** e era inutil.
#:
#: Logo detecta-se a forma documentada, que e a que um cliente poderia colar
#: numa mensagem. E detectam-se **duas letras quaisquer** e nao so `PT.`: o
#: criterio 2 escreve `PT.…` e as *fixtures* deste repositorio usam `AO.`
#: (`packages/core-ts/tests/identity.cripto.test.ts`), que e Angola. Fixar `PT.`
#: era nao detectar o prefixo que o proprio repositorio usa nos seus exemplos.
#:
#: Estado: INDICIO. A forma documentada vem de
#: `docs/tecnica/evidencia/E1_Meta_WhatsApp.md` §3 (CONFIRMADO para `PT.` + ate
#: 128 alfanumericos); que `AO.` seja a forma angolana e inferencia nossa a
#: partir das *fixtures*, nao fonte primaria.
BSUID_PADRAO: Final = re.compile(r"\b[a-z]{2}\.[a-z0-9]{6,128}\b")

#: O padrao do NIF. **`None` por omissao, e isso e a decisao e nao um esquecimento**
#: — ver a nota do modulo. Quem chamar o `detectar` pode passar o seu.
PADRAO_DE_NIF: Final = None

#: Os prefixos internacionais de Angola que um cliente escreve.
#: `244` sozinho entra tambem: «244 912 345 678» aparece.
_PREFIXO: Final = r"(?:\+\s*244|00\s*244|\b244)"
#: Os separadores que um cliente poe entre os digitos: espaco, ponto, hifen.
_SEP: Final = r"[\s.\-]?"

#: Um movel angolano, em todas as formas do criterio 2.
#:
#: As formas que isto casa, e cada uma esta no corpus:
#:
#:     +244 912 345 678     00244912345678     244-912-345-678
#:     912345678            912 345 678        912.345.678
#:     912-345-678          +244912345678      ٩١٢٣٤٥٦٧٨ (pelo `dobrar`)
#:
#: **Exige-se que o numero local comece por `9`**, que e o movel angolano — e e o
#: que o `packages/core-ts/src/eventos/pii.ts` ja fixa (`\+?244 ?9[0-9]{8}`).
#: Um fixo `+244 222 …` **nao** e detectado: nao esta no criterio 2 e esta
#: declarado como LIMITE no corpus, com a sua linha.
#:
#: **As guardas dos extremos nao sao `\b`**, e tinham de nao ser: um `\b` depois
#: do ultimo digito nao impede que o achado comece a meio de um numero mais
#: longo. O que se exige e que nao haja digito **imediatamente** antes nem
#: depois, para que um numero de catorze digitos nao doe nove e sobre cinco.
TELEFONE_PADRAO: Final = re.compile(
    rf"(?<![0-9])(?:{_PREFIXO}{_SEP})?9(?:{_SEP}[0-9]){{8}}(?![0-9])"
)

#: Um movel ditado por extenso. O criterio 2 nomeia-o («por extenso»).
#:
#: Casa nove ou mais palavras de digito seguidas, separadas por espacos, virgulas
#: ou «e». **Nove e nao menos**, porque menos de nove palavras de digito nao e um
#: telefone e «dois tres» aparece em texto comercial a toda a hora.
_PALAVRA_DE_DIGITO: Final = "|".join(sorted(DIGITOS_POR_EXTENSO, key=len, reverse=True))
TELEFONE_POR_EXTENSO: Final = re.compile(
    rf"\b(?:{_PALAVRA_DE_DIGITO})(?:(?:[\s,]+(?:e[\s,]+)?)(?:{_PALAVRA_DE_DIGITO})){{8,}}\b"
)


@dataclasses.dataclass(frozen=True, slots=True)
class Achado:
    """Um pedaco de PII encontrado: onde esta, que tipo e, e o que diz.

    **O `valor` e o texto original do intervalo, e nunca sai deste processo.**
    Vai para o mapa (que vive no estado do *thread*) e e o que permite a
    re-identificacao do criterio 6. Nao entra em metrica, log, *trace* ou evento —
    o `pii_masked_total` leva **o tipo** e mais nada, e e o criterio
    «metricas sem valores» do bloco.
    """

    inicio: int
    fim: int
    tipo: str
    valor: str


def _aceitar(
    achados: list[Achado],
    reclamados: tuple[negocio.Intervalo, ...],
    inicio: int,
    fim: int,
) -> bool:
    """Este intervalo pode virar achado?

    Duas recusas, e as duas sao barreiras e nao optimizacoes:

    * toca um intervalo de negocio -> **criterio 4**, nunca se mascara;
    * toca um achado ja aceite -> o mesmo texto nao se mascara duas vezes, e um
      achado de um tipo mais especifico ganha ao de um tipo mais largo (e por
      isso que a ordem dos `TIPOS` e por especificidade).
    """
    if negocio.reclamado(reclamados, inicio, fim):
        return False
    return not any(inicio < a.fim and fim > a.inicio for a in achados)


def _por_expressao(
    dobrado: str,
    original: str,
    expressao: re.Pattern[str],
    tipo: str,
    achados: list[Achado],
    reclamados: tuple[negocio.Intervalo, ...],
) -> None:
    for encontrado in expressao.finditer(dobrado):
        inicio, fim = encontrado.start(), encontrado.end()
        # Um achado que acabe em separador («912 345 678 ») apara-se: mascarar o
        # espaco a seguir mudava o texto sem necessidade e tornava a reposicao do
        # criterio «o mapa repoe o original» falsa por um caracter.
        while fim > inicio and dobrado[fim - 1] in " .-,":
            fim -= 1
        while inicio < fim and dobrado[inicio] in " .-,":
            inicio += 1
        if inicio < fim and _aceitar(achados, reclamados, inicio, fim):
            achados.append(Achado(inicio, fim, tipo, original[inicio:fim]))


def _contexto_antes(dobrado: str, inicio: int, gatilhos: tuple[str, ...]) -> bool:
    """Algum gatilho aparece imediatamente antes de `inicio`?

    Olha-se para uma janela curta a esquerda e nao para o texto inteiro: «fala
    com o Joao» tem o gatilho ao lado, e uma mensagem que diga «fala com o
    colega» no inicio e mencione «Benfica» no fim nao faz do Benfica uma pessoa.
    A janela e o comprimento do gatilho mais um pouco de folga para artigos («o»,
    «a», «no», «da») e pontuacao.
    """
    janela = dobrado[max(0, inicio - _JANELA_DE_CONTEXTO) : inicio]
    return any(gatilho in janela for gatilho in gatilhos)


#: Quantos caracteres a esquerda contam como «contexto imediato».
#:
#: 24 cobre o maior gatilho das duas listas mais um artigo e pontuacao. Uma
#: janela larga transformava qualquer «entregar em» no inicio da mensagem em
#: contexto de local para o resto dela — que e o modo de falha deste mecanismo.
_JANELA_DE_CONTEXTO: Final = 24


def _locais(
    dobrado: str,
    original: str,
    achados: list[Achado],
    reclamados: tuple[negocio.Intervalo, ...],
) -> None:
    """Moradas e referencias de local: dicionario **ou** contexto.

    Duas vias, e sao ou-exclusivo nenhum — basta uma:

    1. o toponimo esta no dicionario (`LOCAIS`), e entao e morada onde aparecer:
       «Maianga» nao e outra coisa;
    2. ha um gatilho de local imediatamente antes de uma palavra capitalizada
       («entregar em Nova Esperanca»), e entao mascara-se a palavra mesmo que o
       toponimo nao esteja no dicionario — que e o unico mecanismo que apanha os
       bairros que a lista nao tem, e e por isso que o limiar e 90% e nao 99%.
    """
    for nome in LOCAIS:
        inicio = 0
        while (achado := dobrado.find(nome, inicio)) != -1:
            fim = achado + len(nome)
            inicio = achado + 1
            # Fronteiras de palavra a mao: o toponimo pode ter espacos («nova
            # vida»), e um `\b` numa expressao construida por concatenacao de
            # 40 nomes e mais caro e menos legivel do que duas comparacoes.
            if achado > 0 and (dobrado[achado - 1].isalnum() or dobrado[achado - 1] == "_"):
                continue
            if fim < len(dobrado) and (dobrado[fim].isalnum() or dobrado[fim] == "_"):
                continue
            if _aceitar(achados, reclamados, achado, fim):
                achados.append(Achado(achado, fim, MORADA, original[achado:fim]))

    for encontrado in _SEQUENCIA_CAPITALIZADA.finditer(original):
        inicio, fim = encontrado.start(), encontrado.end()
        if not _contexto_antes(dobrado, inicio, CONTEXTO_DE_LOCAL):
            continue
        if _aceitar(achados, reclamados, inicio, fim):
            achados.append(Achado(inicio, fim, MORADA, original[inicio:fim]))


#: Uma palavra capitalizada no texto **original** (a forma dobrada perdeu a
#: caixa, que e precisamente o sinal de nome proprio). Aceita acentos e o hifen
#: de «Van-Dunem».
_PALAVRA_CAPITALIZADA: Final = re.compile(
    r"\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]{2,}(?:-[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+)?\b"
)

#: Uma **sequencia** de palavras capitalizadas, que e o que um toponimo e.
#:
#: E a correccao de um defeito que os meus proprios casos mostraram antes de
#: existir bateria: «entregar em Nova Esperanca» dava **dois** achados —
#: `MORADA_2 MORADA_3` — porque a regra de contexto corria palavra a palavra e a
#: janela de 24 caracteres cobria as duas. Um toponimo de duas palavras e **um**
#: local, e dois tokens para ele nao e so feio: faz a re-identificacao devolver
#: duas cadeias onde havia uma, e faz o modelo pensar que sao dois sitios.
#:
#: As ligacoes aceitas sao as de um toponimo portugues («de», «da», «dos»), que
#: sao as mesmas do `_LIGACAO_DE_NOME` — e sao duas constantes e nao uma porque
#: aqui a ligacao esta **dentro** do que se mascara e ali esta **entre** dois
#: candidatos.
_SEQUENCIA_CAPITALIZADA: Final = re.compile(
    r"\b[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]{2,}(?:-[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]+)?"
    r"(?:\s(?:d[eao]s?\s)?[A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ]{2,})*\b"
)


def _pessoas(
    dobrado: str,
    original: str,
    achados: list[Achado],
    reclamados: tuple[negocio.Intervalo, ...],
    do_catalogo: frozenset[str],
) -> None:
    """Nomes de terceiros -> `PESSOA_n`, com as tres barreiras do criterio 5.

    Um candidato e uma palavra **capitalizada** no texto original. Vira
    `PESSOA_n` quando:

    * esta em `NOMES_PROPRIOS` **e** tem um gatilho de pessoa por perto; ou
    * forma par nome + apelido («Maria Gourgel»), que dispensa o gatilho porque
      um nome completo nao e ambiguo; ou
    * tem um gatilho de pessoa por perto e esta em `APELIDOS` («fala com o
      Gourgel»).

    E **nunca**, em nenhuma das tres vias, quando o nome esta no catalogo do
    *tenant* (criterio 5) — a barreira corre primeiro, antes das outras, porque e
    a unica que protege um *fact*.

    **Uma palavra capitalizada sozinha e sem gatilho nao e pessoa**, e e a
    decisao que faz este detector utilizavel: sem ela, «Tenho Interesse Naquele
    Produto» dava quatro `PESSOA_n`, e o primeiro cliente que escrevesse em
    maiusculas perdia a mensagem inteira.
    """
    candidatos = list(_PALAVRA_CAPITALIZADA.finditer(original))
    for indice, encontrado in enumerate(candidatos):
        inicio, fim = encontrado.start(), encontrado.end()
        palavra = dobrado[inicio:fim]

        # **Criterio 5, e corre antes de tudo.** Um nome do catalogo nao e
        # candidato, e nao e so «nao se mascara»: nem sequer se considera, para
        # que um «Rosa» do catalogo nao entre em par com o apelido seguinte.
        if palavra in do_catalogo:
            continue

        proximo = candidatos[indice + 1] if indice + 1 < len(candidatos) else None
        par = (
            proximo is not None
            and dobrado[proximo.start() : proximo.end()] in APELIDOS
            # Contiguos: so um espaco (ou «de», «da», «dos») entre os dois. Sem
            # isto, «Maria» no inicio e «Santos» no fim da mensagem formavam par.
            and _LIGACAO_DE_NOME.fullmatch(original[fim : proximo.start()]) is not None
        )
        tem_gatilho = _contexto_antes(dobrado, inicio, CONTEXTO_DE_PESSOA)

        e_nome = palavra in NOMES_PROPRIOS
        e_apelido = palavra in APELIDOS

        if e_nome and par:
            # O par inteiro, num achado so: «Maria Gourgel» e **uma** pessoa, e
            # dois achados davam `PESSOA_1 PESSOA_2` para a mesma.
            assert proximo is not None
            if _aceitar(achados, reclamados, inicio, proximo.end()):
                achados.append(
                    Achado(inicio, proximo.end(), PESSOA, original[inicio : proximo.end()])
                )
            continue
        if (e_nome or e_apelido) and tem_gatilho and _aceitar(achados, reclamados, inicio, fim):
            achados.append(Achado(inicio, fim, PESSOA, original[inicio:fim]))


#: O que pode estar **entre** um nome e um apelido para eles serem o mesmo nome.
_LIGACAO_DE_NOME: Final = re.compile(r"\s(?:d[eao]s?\s)?")


def detectar(
    texto: str,
    *,
    do_catalogo: frozenset[str] = frozenset(),
    padrao_de_nif: re.Pattern[str] | None = PADRAO_DE_NIF,
) -> tuple[Achado, ...]:
    """Os achados de PII em `texto`, por ordem de posicao.

    `do_catalogo` sao os nomes que nao se mascaram (criterio 5), na forma
    dobrada; `padrao_de_nif` e o padrao do NIF, `None` por omissao (ver a nota do
    modulo).

    Levanta `negocio.ReclamouDemais` quando os intervalos de negocio cobrem quase
    tudo — que e o sinal de uma expressao errada, e sobe para falhar fechado.
    """
    dobrado = dobrar(texto)
    reclamados = negocio.reclamar(texto)
    achados: list[Achado] = []

    _por_expressao(dobrado, texto, EMAIL_PADRAO, EMAIL, achados, reclamados)
    _por_expressao(dobrado, texto, BSUID_PADRAO, BSUID, achados, reclamados)
    if padrao_de_nif is not None:
        _por_expressao(dobrado, texto, padrao_de_nif, NIF, achados, reclamados)
    _por_expressao(dobrado, texto, TELEFONE_PADRAO, TELEFONE, achados, reclamados)
    _por_expressao(dobrado, texto, TELEFONE_POR_EXTENSO, TELEFONE, achados, reclamados)
    _locais(dobrado, texto, achados, reclamados)
    _pessoas(dobrado, texto, achados, reclamados, do_catalogo)

    return tuple(sorted(achados, key=lambda a: (a.inicio, a.fim)))
