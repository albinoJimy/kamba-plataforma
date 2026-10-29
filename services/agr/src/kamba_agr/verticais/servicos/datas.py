"""A leitura de datas e horas do texto do cliente, e o que ela recusa ler.

O criterio 3 do bloco pede que «hora ambigua ("as 5") gere pergunta de
desambiguacao, **nunca palpite**», e o criterio 6 pede um adversarial de >= 30
casos com «horas trocadas, fuso, "amanha" ambiguo» e **zero** falhas. Este
modulo e a superficie onde os dois se cumprem, e e de funcoes puras de
proposito: a tabela de decisao mede-se com um `dict`, sem grafo, sem base e sem
tools.

## O que este modulo NAO faz, e e metade do valor

**Nao calcula horas livres.** O §8.2 escreve «Disponibilidade: so tool; o modelo
nao calcula horas livres», e isso vale tambem para nos: o que aqui se le e o que
o cliente **disse**, e quem diz se existe vaga e a agenda. Uma funcao chamada
`proxima_vaga` neste ficheiro seria o §8.2 contrariado em codigo.

**Nao adivinha.** Uma leitura com mais do que um resultado possivel devolve
`ambigua` e as candidatas, e nunca escolhe. E o unico caminho honesto: um
palpite numa hora produz uma marcacao real na hora errada, que e pior do que uma
pergunta a mais.

## O fuso: tudo o que e relativo conta-se em Luanda, nunca em UTC

A convencao do conjunto e «datas em UTC, apresentacao em `Africa/Luanda`». Para
**armazenar** isso basta converter no fim; para **ler** nao basta, e e aqui que
esta a armadilha que o criterio 6 chama «fuso».

Angola esta em WAT (UTC+1) sem horario de verao. Logo, entre as **23h00 e a
meia-noite UTC** ja e o dia seguinte em Luanda. Uma mensagem que chegue as
23h30 UTC de 13 de Novembro chega as 00h30 de **14** de Novembro para quem a
escreveu: «amanha» e dia **15**, e nao dia 14. Contado em UTC, o «amanha» dava
14 — a marcacao saia um dia **antes** do que o cliente pediu, e nada no
resultado o denunciava, porque 14 e uma data perfeitamente valida.

Por isso **toda** a aritmetica de dias deste modulo passa primeiro o instante
para Luanda (`em_luanda` do *renderer*, que e quem tem o desvio) e so no fim
volta a UTC. O `LUANDA` nao se redeclara aqui: importa-se do `validador.render`,
que o fixou com a razao escrita (nao ha `tzdata` nesta maquina, e o desvio fixo
e **exacto** para um fuso sem transicoes).

## Porque e que uma hora nua de 1 a 12 e ambigua, e a de 13 a 23 nao e

«As 5» sao as 05h00 ou as 17h00, e o criterio nomeia este caso. «As 14» so pode
ser 14h00 — nao existe a leitura de 12 horas para 14. A regra e essa, e e
uniforme: **1 a 12 nua e ambigua; 0 e 13 a 23 nao**.

**O 12 esta dentro, e e a escolha fail-closed.** «As 12» quase sempre significa
meio-dia em PT-AO, e e tentador decidi-lo. Mas «quase sempre» num campo que
produz uma marcacao real nao e uma leitura, e um palpite — e o criterio diz
«nunca palpite» sem abrir excepcao para o caso provavel. Quem escrever
«meio-dia» tem leitura exacta e nao passa por aqui.

Uma **marca de periodo** desfaz a ambiguidade, e e por isso que ela se procura
primeiro: «5 da tarde» e 17h00 e «5 da manha» e 05h00, as duas sem pergunta.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from ...validador.render import LUANDA, em_luanda

#: Os minutos de um dia. O `minutos` de uma `Hora` conta desde a meia-noite de
#: Luanda, e nao e um `datetime`: somar um numero de minutos a uma data e a
#: unica operacao que este modulo faz com horas, e um `time` obrigava a
#: construir um `datetime` por candidata.
MINUTOS_DO_DIA: Final = 24 * 60

#: A hora nua a partir da qual nao ha leitura de 12 horas. Ver o cabecalho.
PRIMEIRA_HORA_SEM_AMBIGUIDADE: Final = 13

#: As marcas de periodo, e o intervalo que cada uma abre. A ordem **conta**: a
#: «madrugada» tem de se procurar antes da «manha» porque as duas palavras
#: aparecem na mesma frase («as 5 da madrugada»), e um `in` sobre a segunda
#: casava as duas.
_PERIODOS: Final = (
    ("madrugada", 0),
    ("manha", 0),
    ("manhã", 0),
    ("tarde", 12),
    ("noite", 12),
)

#: As formas exactas, que nao passam pela regra da ambiguidade porque nao tem
#: duas leituras. O `meio-dia` e o `meia-noite` sao as duas que o portugues
#: escreve por palavras.
_HORAS_EXACTAS: Final = {
    "meio-dia": 12 * 60,
    "meio dia": 12 * 60,
    "meia-noite": 0,
    "meia noite": 0,
}

#: Uma hora escrita: `14h30`, `14h`, `14:30`, ou o numero nu de «as 5».
#: **O numero nu exige a preposicao** (`as`, `às`, `para as`): sem ela, o `5` de
#: «quero cortar 5 cm» era uma hora. E a mesma regra que o
#: `quantidade_pedida` do Vendedor pagou — um numero so conta quando algo o
#: reclama.
#:
#: **O ponto NAO e separador de horas, e isso foi medido.** A primeira versao
#: aceitava `(?:h|:|\.)`, e a revisao adversarial mostrou o que isso lia
#: (`ANALISE-40`, achado 15):
#:
#: ```text
#: «na 2.a feira as 10h»       -> ambiguo entre 02h00 e 14h00 (o «2.a» vence)
#: «a 1.a hora livre»          -> 01h00 ou 13h00
#: «dia 5.11»                  -> 05h11
#: «custa 2.500 kz?»           -> 02h00 ou 14h00
#: «pode ser dia 20. as 10h»   -> **20h00**, e o cliente escreveu 10h
#: ```
#:
#: O ultimo e o pior porque **nao e ambiguo**: e um valor errado com confianca,
#: que e o palpite que este modulo existe para nao dar. O `search` devolve a
#: **primeira** ocorrencia e nao a mais plausivel, pelo que basta um ordinal ou
#: um separador de milhares antes da hora para a hora certa nunca ser lida.
#:
#: Em PT-AO o ponto escreve ordinais (`2.ª`), milhares (`2.500`) e datas
#: (`5.11`) — e **nao** escreve horas: a forma da casa e `14h30` e a
#: internacional e `14:30`. Tirar o ponto nao perde uma forma que alguem use;
#: mante-lo perdia a hora em cinco frases normais.
_HORA_COM_MARCA: Final = re.compile(
    r"\b(?P<h>[01]?\d|2[0-3])\s*(?:h|:)\s*(?P<m>[0-5]\d)?\b",
    re.IGNORECASE,
)

#: As fraccoes de hora que o portugues escreve por palavras, em minutos.
#:
#: **Existem porque a ausencia delas perdia a meia hora em silencio**: «as 5 e
#: meia da tarde» dava 17h00 e seguia como hora **lida**, sem pergunta e sem
#: aviso — uma marcacao real meia hora antes do que o cliente pediu. Medido pela
#: revisao adversarial (`ANALISE-40`, achado 16).
#:
#: A ordem conta: «e tres quartos» contem «quartos», e procurar o quarto
#: primeiro casava os dois.
_FRACCOES: Final = (
    ("e tres quartos", 45),
    ("e um quarto", 15),
    ("e quarenta e cinco", 45),
    ("e quinze", 15),
    ("e meia", 30),
    ("e trinta", 30),
)
_HORA_NUA: Final = re.compile(
    r"\b(?:[aà]s|para\s+as|para\s+[aà]s)\s+(?P<h>[01]?\d|2[0-3])\b(?!\s*(?:h|:|\.|/|-))",
    re.IGNORECASE,
)

#: Uma data numerica: `14/11`, `14/11/2026`, `14-11-2026`, `2026-11-14`.
_DATA_ISO: Final = re.compile(r"\b(?P<a>20\d{2})-(?P<m>0?[1-9]|1[0-2])-(?P<d>0?[1-9]|[12]\d|3[01])\b")
_DATA_PT: Final = re.compile(
    r"\b(?P<d>0?[1-9]|[12]\d|3[01])[/-](?P<m>0?[1-9]|1[0-2])(?:[/-](?P<a>20\d{2}|\d{2}))?\b"
)

#: Os meses por nome, para `14 de Novembro`. Sem acentos na chave: compara-se
#: contra o texto ja normalizado pelo `_sem_acentos`.
_MESES: Final = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_DATA_POR_EXTENSO: Final = re.compile(
    r"\b(?P<d>0?[1-9]|[12]\d|3[01])\s+de\s+(?P<mes>" + "|".join(_MESES) + r")\b",
    re.IGNORECASE,
)

#: Os dias relativos, em dias a somar ao **dia de Luanda**. Ver o cabecalho.
_RELATIVOS: Final = {
    "hoje": 0,
    "amanha": 1,
    "amanhã": 1,
    "depois de amanha": 2,
    "depois de amanhã": 2,
}

#: Os dias da semana, pelo indice do `weekday()` (segunda = 0).
_DIAS_DA_SEMANA: Final = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}
_DIA_DA_SEMANA: Final = re.compile(
    r"\b(?:na\s+|a\s+|no\s+|ao\s+)?(?P<dia>" + "|".join(_DIAS_DA_SEMANA) + r")(?:-feira)?\b",
    re.IGNORECASE,
)

_ACENTOS: Final = str.maketrans("áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ", "aaaaeeioooucAAAAEEIOOOUC")


def sem_acentos(texto: str) -> str:
    """O texto em minusculas e sem acentos, para comparar com as tabelas.

    **Publica**, porque o `nos.py` compara o texto do cliente com as mesmas
    palavras: uma segunda copia desta funcao divergia no dia em que alguem
    acrescentasse uma letra a tabela de uma delas.
    """
    return texto.translate(_ACENTOS).lower()


@dataclass(frozen=True, slots=True)
class Hora:
    """Uma hora lida do texto, ou a razao por que nao se leu uma so.

    `minutos` e `None` quando nao se leu nenhuma hora **ou** quando a leitura e
    ambigua: nos dois casos nao ha valor para usar, e e deliberado que a
    distincao se faca por `candidatas` e nao por um valor com uma *flag* ao
    lado — um `minutos` preenchido numa leitura ambigua era um palpite a espera
    de que alguem se esquecesse de ler a *flag*.
    """

    minutos: int | None = None
    #: As leituras possiveis, quando ha mais do que uma. Vazio quando a leitura
    #: e unica ou quando nao se leu nada.
    candidatas: tuple[int, ...] = ()

    @property
    def ambigua(self) -> bool:
        return len(self.candidatas) > 1

    @property
    def lida(self) -> bool:
        """Leu-se **uma** hora. Uma leitura ambigua nao conta como lida."""
        return self.minutos is not None


def ler_hora(texto: str) -> Hora:
    """A hora que o cliente escreveu, ou a ambiguidade dela.

    A ordem e decisao: primeiro as formas exactas por palavras, depois a hora
    com marca (`14h30`), depois a nua com preposicao (`as 5`). Uma hora com
    marca nunca e ambigua — quem escreve `17h` nao escreveu `5`.
    """
    limpo = sem_acentos(texto)

    for forma, minutos in _HORAS_EXACTAS.items():
        if sem_acentos(forma) in limpo:
            return Hora(minutos=minutos)

    periodo = _periodo_de(limpo)
    fraccao = _fraccao_de(limpo)

    achado = _HORA_COM_MARCA.search(texto)
    if achado is not None:
        hora = int(achado.group("h"))
        # **A fraccao por palavras nao sobrepoe os minutos escritos.** «14h30 e
        # meia» e prosa que ninguem escreve, e somar as duas dava 15h00; quem
        # escreveu os minutos ja disse os minutos.
        escritos = achado.group("m")
        minuto = int(escritos) if escritos else fraccao
        return _resolver(hora, minuto, periodo, com_marca=True)

    nua = _HORA_NUA.search(texto)
    if nua is not None:
        return _resolver(int(nua.group("h")), fraccao, periodo, com_marca=False)

    return Hora()


def _fraccao_de(limpo: str) -> int:
    """Os minutos que uma fraccao por palavras acrescenta. Zero se nao houver."""
    for palavra, minutos in _FRACCOES:
        if sem_acentos(palavra) in limpo:
            return minutos
    return 0


def resolver_candidatas(texto: str, candidatas: Sequence[int]) -> int | None:
    """A candidata que a marca de periodo do texto escolhe, ou `None`.

    ## Existe porque a pergunta era inrespondivel

    O `slots_collect` pergunta «essa hora e de manha ou de tarde?» e guarda as
    duas candidatas. A primeira versao **nunca as lia**: o cliente que
    respondesse exactamente o que lhe foi perguntado — «de tarde» — chegava ao
    `ler_hora`, que nao encontrava hora no texto (porque nao ha digitos em «de
    tarde»), e recebia de volta «a que horas lhe da jeito?». Um ciclo, de que
    escapava so quem escrevesse «17h». Medido pela revisao adversarial
    (`ANALISE-40`, achado 7), em dois turnos.

    **Nao e um palpite, e e a distincao que importa:** o cliente respondeu a
    pergunta que lhe foi feita, e o que esta funcao faz e aplicar a resposta as
    duas leituras que **ja** estavam guardadas. Sem marca de periodo no texto,
    devolve `None` e pergunta-se outra vez.

    Uma marca que nao case nenhuma candidata tambem devolve `None`: duas
    candidatas de manha (que o `_resolver` nao produz, mas que um estado escrito
    a mao produziria) nao se desempatam por «de manha».
    """
    periodo = _periodo_de(sem_acentos(texto))
    if periodo is None:
        return None
    if periodo == 0:
        batem = [c for c in candidatas if c < 12 * 60]
    else:
        batem = [c for c in candidatas if c >= 12 * 60]
    return batem[0] if len(batem) == 1 else None


def _periodo_de(limpo: str) -> int | None:
    """O deslocamento de horas que uma marca de periodo impoe, ou `None`."""
    for palavra, deslocamento in _PERIODOS:
        if sem_acentos(palavra) in limpo:
            return deslocamento
    return None


def _resolver(
    hora: int, minuto: int, periodo: int | None, *, com_marca: bool
) -> Hora:
    """Uma hora e um minuto, mais a marca de periodo se houver.

    **A marca de periodo nao se aplica a uma hora que ja e inequivoca.** «As 14
    da tarde» e 14h00 e nao 26h00: somar o deslocamento a uma hora >= 13 dava um
    valor fora do dia, e um `% 24` escondia-o nas 2h00 da manha. Quem escreve a
    hora em 24 horas ja disse o periodo.

    ## O `com_marca` decide a ambiguidade, e nao o numero sozinho

    O cabecalho deste modulo diz que «uma hora com marca nunca e ambigua — quem
    escreve `17h` nao escreveu `5`», e a primeira versao **nao cumpria a propria
    frase**: mandava `10h` pela regra do 1 a 12 e devolvia as duas candidatas
    (10h00 e 22h00). O efeito era o pior possivel para o criterio 3 — uma hora
    perfeitamente clara a gerar pergunta de desambiguacao, isto e, a
    desambiguacao a disparar no caso em que nao ha nada para desambiguar.

    **Nao foi a revisao que o apanhou: foi o ensaio do achado 15**, que precisava
    de ler «as 10h» no meio de uma frase com um ordinal. Os casos da tabela de
    horas usavam todos `14h` ou mais, pelo que a regra errada nunca se via — e e
    a licao de sempre, que uma tabela de casos so mede o que lhe poem.

    A forma `10h`/`10:30` **e** a notacao de 24 horas: quem a usa ja disse qual
    das duas. So o numero nu («as 5») tem duas leituras.
    """
    if com_marca:
        if periodo is not None and hora < PRIMEIRA_HORA_SEM_AMBIGUIDADE:
            # «as 5h da tarde» e 17h00: a marca explicita vence, e nao e um
            # palpite — o cliente disse as duas coisas.
            resolvida = (12 if hora == 12 else hora + 12) if periodo else (
                0 if hora == 12 else hora
            )
            return Hora(minutos=resolvida * 60 + minuto)
        return Hora(minutos=hora * 60 + minuto)

    if hora >= PRIMEIRA_HORA_SEM_AMBIGUIDADE or hora == 0:
        return Hora(minutos=hora * 60 + minuto)

    if periodo is not None:
        # `hora == 12` com marca de manha fica 12h00 e nao 24h00: o 12 do
        # relogio de 12 horas e o zero da manha e o doze da tarde.
        if periodo == 0:
            resolvida = 0 if hora == 12 else hora
        else:
            resolvida = 12 if hora == 12 else hora + 12
        return Hora(minutos=resolvida * 60 + minuto)

    # Nua, de 1 a 12: duas leituras, e nenhuma se escolhe.
    manha = (0 if hora == 12 else hora) * 60 + minuto
    tarde = (12 if hora == 12 else hora + 12) * 60 + minuto
    return Hora(candidatas=(manha, tarde))


def ler_data(texto: str, agora_utc: datetime.datetime) -> str | None:
    """A data que o cliente escreveu, em ISO (`2026-11-14`), no dia de Luanda.

    O `agora_utc` e o instante da mensagem e serve de origem a tudo o que e
    relativo. **Converte-se para Luanda antes de somar dias** — ver o cabecalho.

    Devolve `None` quando nao ha data no texto. Uma data no **passado** tambem
    devolve `None`, e nao e uma leitura falhada: e a recusa de marcar para
    tras, e quem a trata e o `slots_collect`, que volta a perguntar.
    """
    hoje = em_luanda(agora_utc.isoformat()).date()
    limpo = sem_acentos(texto)

    # Os relativos primeiro, e os compostos antes dos simples: «depois de
    # amanha» contem «amanha», e procurar o simples primeiro dava 1 onde sao 2.
    for palavra in sorted(_RELATIVOS, key=len, reverse=True):
        if sem_acentos(palavra) in limpo:
            return (hoje + datetime.timedelta(days=_RELATIVOS[palavra])).isoformat()

    achado = _DATA_ISO.search(texto)
    if achado is not None:
        return _valida(int(achado.group("a")), int(achado.group("m")), int(achado.group("d")), hoje)

    achado = _DATA_PT.search(texto)
    if achado is not None:
        ano = _ano_de(achado.group("a"), hoje)
        dia, mes = int(achado.group("d")), int(achado.group("m"))
        if achado.group("a") is None:
            # Sem ano, escolhe-se a **proxima** ocorrencia: «14/11» em Dezembro
            # e o 14 de Novembro do ano que vem, e nao um dia que ja passou.
            # Nao e um palpite sobre o que o cliente quis — e a unica leitura
            # que produz uma marcacao possivel.
            return _proxima_ocorrencia(dia, mes, hoje)
        return _valida(ano, mes, dia, hoje)

    achado = _DATA_POR_EXTENSO.search(texto)
    if achado is not None:
        mes = _MESES[sem_acentos(achado.group("mes"))]
        return _proxima_ocorrencia(int(achado.group("d")), mes, hoje)

    achado = _DIA_DA_SEMANA.search(limpo)
    if achado is not None:
        return _proximo_dia_da_semana(_DIAS_DA_SEMANA[achado.group("dia")], hoje)

    return None


def _ano_de(cru: str | None, hoje: datetime.date) -> int:
    """O ano de uma data escrita com dois digitos, quatro, ou nenhum."""
    if cru is None:
        return hoje.year
    valor = int(cru)
    return valor if valor >= 100 else 2000 + valor


def _valida(ano: int, mes: int, dia: int, hoje: datetime.date) -> str | None:
    """A data, se existir no calendario e nao estiver no passado.

    Um 31 de Fevereiro **nao** se corrige para o 28: devolve `None`, e o
    `slots_collect` pergunta outra vez. Corrigi-lo era marcar noutro dia.
    """
    try:
        quando = datetime.date(ano, mes, dia)
    except ValueError:
        return None
    return quando.isoformat() if quando >= hoje else None


def _proxima_ocorrencia(dia: int, mes: int, hoje: datetime.date) -> str | None:
    """O proximo `dia/mes` a partir de hoje, este ano ou no seguinte."""
    for ano in (hoje.year, hoje.year + 1):
        try:
            quando = datetime.date(ano, mes, dia)
        except ValueError:
            continue
        if quando >= hoje:
            return quando.isoformat()
    return None


def _proximo_dia_da_semana(indice: int, hoje: datetime.date) -> str:
    """A proxima ocorrencia daquele dia da semana, **nunca hoje**.

    «Na terca» dito numa terca e a terca **seguinte**: um cliente que escreve o
    nome do dia em que esta a falar nao esta a pedir hoje — e se estivesse,
    dizia «hoje». Escolher hoje dava uma marcacao para dentro de minutos.
    """
    avanco = (indice - hoje.weekday()) % 7 or 7
    return (hoje + datetime.timedelta(days=avanco)).isoformat()


def instante_utc(data: str, minutos: int) -> str:
    """Uma data de Luanda e os minutos desde a meia-noite, em UTC ISO-8601.

    E o inverso do `em_luanda` do *renderer*, e e o unico sitio onde este modulo
    produz um instante: o armazenamento e UTC (convencao do conjunto) e a
    leitura foi toda feita no dia de Luanda.
    """
    if not 0 <= minutos < MINUTOS_DO_DIA:
        raise ValueError(f"{minutos} nao e um minuto do dia")
    dia = datetime.date.fromisoformat(data)
    local = datetime.datetime.combine(
        dia, datetime.time(minutos // 60, minutos % 60), tzinfo=LUANDA
    )
    return local.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
