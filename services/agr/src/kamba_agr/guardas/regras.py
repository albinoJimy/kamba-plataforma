"""As regras deterministicas de entrada (§8.4): os seis veredictos, a custo zero.

    veredicto_por_regras(texto) -> veredicto | None

`None` quer dizer **indeciso**, e so nesse caso o `guard_in` chama o
classificador (`classificador.py`). E a ordem que o §8.4 escreve por baixo da
tabela: «os guardrails deterministicos correm primeiro (custo zero); o
classificador barato so quando as regras nao decidem».

## A ordem das regras e uma decisao, e mede-se com casos mistos

1. **`card_data`** primeiro: uma mensagem com um PAN e um pedido de credito ao
   mesmo tempo e tratada como cartao — o §8.4 manda nao guardar, e e a unica
   classe cujo conteudo se **redige** antes de qualquer outra coisa.
2. **`sensitive`** antes da injeccao: uma pergunta sobre medicamentos escrita
   com «finge que» continua a ser sobre medicamentos, e quem decide e uma pessoa.
3. **`injection`**, que inclui a travessia de fronteira do X-09.
4. **`abuse`**.
5. **`out_of_domain`**: o «assistente universal».
6. **`ok`** quando o texto fala do dominio comercial; senao **indeciso**.

## O PAN e o IBAN levam verificacao de digitos, e nao so forma

O Luhn para o PAN e o *mod 97* (ISO 13616) para o IBAN. Sem eles, um
`order_id` de dezasseis digitos ou um codigo comprido colado a um prefixo de
pais era redigido e recusado — recusar o turno de quem pediu o estado de uma
encomenda. Nenhum dos dois prova que e um cartao ou uma conta; provam que
**pode** ser, e e o que o §8.4 pede.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from ..privacidade.dicionarios import dobrar
from . import politica

#: Os seis veredictos de entrada, pela lista fechada do dicionario §3.31.
VEREDICTOS: Final = ("ok", "injection", "abuse", "out_of_domain", "card_data", "sensitive")

#: O que substitui um PAN e um IBAN no texto. **Sem digitos**, para que o
#: marcador nao seja ele proprio um candidato, e reconhecivel pelo `guard_in`
#: depois de o texto ter sido redigido a entrada (`entrada.py`).
MARCA_CARTAO: Final = "[cartao removido]"
MARCA_CONTA: Final = "[conta removida]"
#: O que substitui uma mensagem inteira de assunto sensivel (criterio 7: «o
#: conteudo sensivel **nao** e persistido»).
MARCA_SENSIVEL: Final = "[assunto sensivel removido]"

#: Caracteres de largura zero e de controlo de direccao: escondem palavras
#: («ig​nora») sem mudarem o que o cliente ve (`docs/tecnica/08` §4.3, L1).
_INVISIVEIS: Final = re.compile(
    "[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f­​-‏‪-‮⁠-⁤﻿]"
)
_ESPACOS: Final = re.compile(r"\s+")

#: Uma sequencia de digitos com espacos ou tracos simples pelo meio. O PAN
#: procura-se **dentro** dela, por grupos (ver o `_pans`).
_SEQUENCIA: Final = re.compile(r"(?<![0-9])[0-9]+(?:[ -][0-9]+)*(?![0-9])")
_GRUPO: Final = re.compile(r"[0-9]+")
#: Um IBAN candidato: duas letras, dois digitos de controlo, e o BBAN, com ou
#: sem espacos de quatro em quatro. Corre sobre o texto em maiusculas.
_IBAN: Final = re.compile(r"\b[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")


def _compilar(padroes: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in padroes)


_INJECCAO: Final = _compilar(politica.INJECCAO)
_FRONTEIRA: Final = _compilar(politica.FRONTEIRA)
_PRIMEIRA_PESSOA: Final = re.compile(politica.PRIMEIRA_PESSOA)
_SENSIVEL: Final = _compilar(politica.SENSIVEL)
_ABUSO: Final = _compilar(politica.ABUSO)
_FORA_DE_DOMINIO: Final = _compilar(politica.FORA_DE_DOMINIO)
_DOMINIO: Final = _compilar(politica.DOMINIO)


def normalizar(texto: str) -> str:
    """A forma sobre a qual as regras correm (`docs/tecnica/08` §4.3, L1).

    Sem invisiveis, `NFKC`, dobrada (minusculas, sem acentos, digitos ASCII) e
    com os espacos colapsados. **Nao preserva o comprimento**, ao contrario do
    `dobrar`: as regras so decidem, nao mascaram posicoes.
    """
    limpo = _INVISIVEIS.sub("", texto)
    return _ESPACOS.sub(" ", dobrar(unicodedata.normalize("NFKC", limpo))).strip()


def luhn(digitos: str) -> bool:
    """O algoritmo de Luhn (§8.4, «PAN com Luhn»)."""
    soma = 0
    for posicao, caracter in enumerate(reversed(digitos)):
        valor = int(caracter)
        if posicao % 2 == 1:
            valor *= 2
            if valor > 9:
                valor -= 9
        soma += valor
    return soma % 10 == 0


def iban_valido(candidato: str) -> bool:
    """O *mod 97* da ISO 13616: o resto tem de ser 1."""
    compacto = candidato.replace(" ", "").upper()
    if not 15 <= len(compacto) <= 34:
        return False
    rodado = compacto[4:] + compacto[:4]
    try:
        numero = "".join(str(int(c, 36)) for c in rodado)
    except ValueError:
        return False
    return int(numero) % 97 == 1


def _pans(texto: str) -> list[tuple[int, int]]:
    """Os intervalos de PAN validos por Luhn.

    **Por grupos, e nao por uma expressao gulosa**, e a diferenca mediu-se: com
    `(?:[0-9][ -]?){12,18}[0-9]`, «pedido 12345 4111 1111 1111 1111» dava um
    achado de dezanove digitos que comecava no `12345`, o Luhn falhava, e o
    cartao **passava** — o `finditer` continuava depois do achado. Aqui cada
    sequencia parte-se pelos separadores e experimenta-se cada corrida de grupos
    consecutivos com treze a dezanove digitos. Uma corrida de digitos **sem**
    separadores com mais de dezanove nao e um PAN.
    """
    intervalos: list[tuple[int, int]] = []
    for sequencia in _SEQUENCIA.finditer(texto):
        grupos = [
            (g.start() + sequencia.start(), g.end() + sequencia.start(), g.group(0))
            for g in _GRUPO.finditer(sequencia.group(0))
        ]
        for i in range(len(grupos)):
            digitos = ""
            for j in range(i, len(grupos)):
                digitos += grupos[j][2]
                if len(digitos) > 19:
                    break
                if len(digitos) >= 13 and luhn(digitos):
                    intervalos.append((grupos[i][0], grupos[j][1]))
    # Intervalos sobrepostos fundem-se: a redaccao troca cada um por uma marca.
    fundidos: list[tuple[int, int]] = []
    for inicio, fim in sorted(intervalos):
        if fundidos and inicio <= fundidos[-1][1]:
            fundidos[-1] = (fundidos[-1][0], max(fim, fundidos[-1][1]))
        else:
            fundidos.append((inicio, fim))
    return fundidos


def _ibans(texto: str) -> list[tuple[int, int]]:
    # Corre sobre o texto em maiusculas para que «ao06 0044 …» case. **O
    # `upper()` preserva o comprimento** para os caracteres de um IBAN, que sao
    # ASCII; os intervalos valem no original.
    maiusculas = texto.upper()
    return [a.span() for a in _IBAN.finditer(maiusculas) if iban_valido(a.group(0))]


def tem_dados_de_cartao(texto: str) -> bool:
    """Se o texto leva um PAN valido por Luhn, um IBAN valido, ou ja a marca."""
    digitos = unicodedata.normalize("NFKC", _INVISIVEIS.sub("", texto))
    return bool(
        _pans(digitos) or _ibans(digitos) or MARCA_CARTAO in texto or MARCA_CONTA in texto
    )


def redigir_cartao(texto: str) -> str:
    """O texto sem PAN nem IBAN (criterio 2). Idempotente.

    Corre sobre o texto **sem invisiveis e em `NFKC`**, que e a forma em que os
    digitos de largura total e os separadores escondidos deixam de esconder um
    numero. O que sai e essa forma, com os numeros trocados pelas marcas.
    """
    limpo = unicodedata.normalize("NFKC", _INVISIVEIS.sub("", texto))
    # **Um passo de cada vez, e os intervalos recalculam-se**: trocar os PAN
    # muda as posicoes, e intervalos de IBAN medidos antes da troca cortavam o
    # sitio errado.
    for procurar, marca in ((_pans, MARCA_CARTAO), (_ibans, MARCA_CONTA)):
        for inicio, fim in sorted(procurar(limpo), reverse=True):
            limpo = limpo[:inicio] + marca + limpo[fim:]
    return limpo


def e_sensivel(texto: str) -> bool:
    """Se o texto fala de um assunto sensivel, pelas regras."""
    normal = normalizar(texto)
    return MARCA_SENSIVEL in texto or any(p.search(normal) for p in _SENSIVEL)


def atravessa_fronteira(normal: str) -> bool:
    """O X-09 pelas regras: pedir dados de outro contacto, loja ou *tenant*."""
    return any(p.search(normal) for p in _FRONTEIRA) and not _PRIMEIRA_PESSOA.search(normal)


def veredicto_por_regras(texto: str) -> str | None:
    """O veredicto que as regras decidem, ou `None` se nenhuma decidir."""
    if tem_dados_de_cartao(texto):
        return "card_data"
    if e_sensivel(texto):
        return "sensitive"
    normal = normalizar(texto)
    if any(p.search(normal) for p in _INJECCAO) or atravessa_fronteira(normal):
        # **Atravessar a fronteira do tenant e `injection`**, nao
        # `out_of_domain`: os dois vao ao `safe_reply` pela linha 9, mas e o
        # `injection` que nomeia o que isto e, e e ele que conta para o
        # *cool-down* do criterio 5.
        return "injection"
    if any(p.search(normal) for p in _ABUSO):
        return "abuse"
    if any(p.search(normal) for p in _FORA_DE_DOMINIO):
        return "out_of_domain"
    if any(p.search(normal) for p in _DOMINIO):
        return "ok"
    return None
