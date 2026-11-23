"""As regras puras do modulo `social` (KAM-121): perfil, semana, agenda e temas.

Nada aqui fala com a base, com um modelo ou com o relogio: o instante entra
por argumento, e a mesma entrada da sempre a mesma saida. E o que deixa o
criterio 2 medir-se a letra — «datas/horas sugeridas calculadas por codigo a
partir das preferencias em `Africa/Luanda`, nunca pelo modelo».

## O perfil de marca: oito perguntas, uma de cada vez

| # | Campo | O que se aceita |
|---|---|---|
| 1 | `nome` | o nome da marca, 2 a 60 caracteres |
| 2 | `categoria` | o que a loja vende, 2 a 60 caracteres |
| 3 | `tom` | uma das tres opcoes de `TONS`, por botao ou por extenso |
| 4 | `cores` | ate tres cores em hexadecimal (`#1A2B3C` ou `#ABC`), ou «nenhuma» |
| 5 | `publico` | a quem a loja fala, 2 a 200 caracteres |
| 6 | `slots` | dias e horas preferidos («segunda 18h, quarta 12:30») |
| 7 | `factos` | os factos que a loja autoriza a dizer, um por linha, ou «nenhum» |
| 8 | `logo` | o logotipo **do proprio dono** — a media nao chega ao AGR (credor no bloco) |

O 8.o nao conta para o perfil completo: e a arte do KAM-122 que o usa, e uma
legenda nao precisa dele. **Um perfil incompleto nao gera calendario** (criterio
1): `perfil_completo` diz quais faltam.

## Os factos de promocao levam validade

Um facto com valor, percentagem ou palavra de promocao («10% de desconto», «leve
dois pague um») **so e aceite com a validade** («ate 30/11»): o criterio 4 pede
«facto de promocao fornecido pelo dono com validade». Sem ela, a resposta e
recusada e a pergunta volta, a dizer porque.

## A semana do calendario e a seguinte

«IDEIAS» planeia a **proxima** semana ISO, em `Africa/Luanda`: um calendario da
semana corrente nascia com metade das horas no passado. A chave do criterio 2 e
`tenant|semana_iso` dessa semana, e repetir «IDEIAS» na mesma semana da a mesma
chave.

## As referencias e os botoes nao levam algarismos

`SOC-` e oito letras derivadas do `id` do item, como o `PRD-…` do catalogo: o
#237 mediu que a guarda de entrada redige como cartao um identificador opaco com
algarismos. Os botoes deste modulo citam so letras.
"""

from __future__ import annotations

import datetime
import re
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from ..validador.render import LUANDA

# ------------------------------------------------------------------ o dominio

#: Os tipos de um `content_item` (criterio 2). Lista **fechada**, a mesma do
#: `CHECK` da tabela.
TIPOS: Final = ("produto", "dica", "bastidores", "promocao")

#: As tres opcoes de tom (criterio 1). *Proposta*: os nomes sao do executor.
TONS: Final = ("proximo", "profissional", "divertido")

#: O texto de cada tom no botao e na pergunta.
TITULO_DO_TOM: Final = {
    "proximo": "Proximo e caloroso",
    "profissional": "Profissional",
    "divertido": "Divertido",
}

#: Quantos itens um calendario tem (criterio 2). *Proposta*.
MINIMO_DE_ITENS: Final = 3
MAXIMO_DE_ITENS: Final = 7

#: Ate quantas cores o perfil leva (criterio 1).
MAXIMO_DE_CORES: Final = 3

#: Ate quantos factos o perfil leva. *Proposta*: cabem numa mensagem.
MAXIMO_DE_FACTOS: Final = 10
TAMANHO_DE_UM_FACTO: Final = 200

#: As perguntas do perfil, pela ordem em que se fazem (criterio 1: <= 8).
CAMPOS_DO_PERFIL: Final = ("nome", "categoria", "tom", "cores", "publico", "slots", "factos", "logo")

#: Os que o perfil completo exige. O `logo` nao: ver o cabecalho.
CAMPOS_OBRIGATORIOS: Final = CAMPOS_DO_PERFIL[:-1]

#: O texto de cada pergunta. **Sem digitos**: vao direitos ao `send`.
PERGUNTAS: Final = {
    "nome": "Como se chama a sua marca?",
    "categoria": "O que vende a sua loja? Por exemplo: roupa, comida, beleza.",
    "tom": "Que tom quer nas suas publicacoes? Escolha um dos botoes.",
    "cores": (
        "Quais sao as cores da marca? Escreva ate tres em codigo hexadecimal, "
        "como #FFAACC, ou escreva nenhuma."
    ),
    "publico": "Para quem sao as suas publicacoes? Por exemplo: maes jovens de Luanda.",
    "slots": (
        "Em que dias e a que horas prefere publicar? Por exemplo: segunda as dezoito "
        "horas, quarta ao meio-dia. Pode escrever as horas em numeros."
    ),
    "factos": (
        "Que factos da loja posso usar nas legendas? Um por linha: entregas, "
        "horario, promocoes com a data em que acabam. Ou escreva nenhum."
    ),
    "logo": "O logotipo da marca ainda nao se recebe por aqui. Fica para depois.",
}

#: As palavras que querem dizer «nenhum».
_NENHUM: Final = frozenset({"nenhum", "nenhuma", "nada", "nao", "nao tenho", "sem"})


class RespostaRecusadaError(ValueError):
    """Uma resposta ao perfil que nao tem a forma da pergunta. `motivo` e o codigo."""

    def __init__(self, motivo: str) -> None:
        super().__init__(motivo)
        self.motivo = motivo


def sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


# ------------------------------------------------------------------ os dias e as horas

#: O dia da semana (segunda = 0), por extenso e abreviado, sem acentos.
DIAS: Final = {
    "segunda": 0, "seg": 0, "segunda-feira": 0,
    "terca": 1, "ter": 1, "terca-feira": 1,
    "quarta": 2, "qua": 2, "quarta-feira": 2,
    "quinta": 3, "qui": 3, "quinta-feira": 3,
    "sexta": 4, "sex": 4, "sexta-feira": 4,
    "sabado": 5, "sab": 5,
    "domingo": 6, "dom": 6,
}

#: O nome de cada dia, para o texto ao dono.
NOME_DO_DIA: Final = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")

_HORA: Final = re.compile(r"(?<!\d)([01]?\d|2[0-3])\s*(?:h|:|horas?\b)\s*([0-5]\d)?")
_HORAS_POR_EXTENSO: Final = {"meio-dia": (12, 0), "meio dia": (12, 0), "meia-noite": (0, 0), "meia noite": (0, 0)}


@dataclass(frozen=True, order=True)
class Slot:
    """Um dia da semana e uma hora local (`Africa/Luanda`)."""

    dia: int
    hora: int
    minuto: int = 0

    def para_json(self) -> dict[str, Any]:
        return {"dia": NOME_DO_DIA[self.dia], "hora": f"{self.hora:02d}:{self.minuto:02d}"}

    @classmethod
    def de_json(cls, valor: Mapping[str, Any]) -> Slot:
        dia = DIAS[str(valor["dia"])]
        hora, minuto = (int(x) for x in str(valor["hora"]).split(":"))
        return cls(dia, hora, minuto)


def ler_slots(texto: str) -> tuple[Slot, ...]:
    """Os dias e horas de um texto do dono, por ordem e sem repetir.

    Cada pedaco separado por virgula, «;», «e» ou mudanca de linha tem de ter um
    dia; a hora e a do proprio pedaco ou, sem ela, a do pedaco anterior («segunda
    e quarta as 18h» da duas). Um pedaco sem dia, ou sem hora nenhuma no texto,
    recusa a resposta inteira: um slot adivinhado era uma hora que o dono nao deu.
    """
    limpo = sem_acentos(texto)
    pedacos = [p.strip() for p in re.split(r"[,;\n]|\be\b", limpo) if p.strip()]
    if not pedacos:
        raise RespostaRecusadaError("slots_vazios")
    lidos: list[tuple[int, tuple[int, int] | None]] = []
    for pedaco in pedacos:
        dias = [DIAS[p] for p in re.findall(r"[a-z-]+", pedaco) if p in DIAS]
        if len(dias) != 1:
            raise RespostaRecusadaError("slot_sem_dia")
        hora: tuple[int, int] | None = None
        for extenso, valor in _HORAS_POR_EXTENSO.items():
            if extenso in pedaco:
                hora = valor
        casado = _HORA.search(pedaco)
        if casado is not None:
            hora = (int(casado.group(1)), int(casado.group(2) or 0))
        lidos.append((dias[0], hora))
    # A hora de um pedaco sem ela e a do seguinte que a tenha («segunda e quarta
    # as 18h»), e senao a do anterior.
    resolvidos: list[Slot] = []
    for i, (dia, hora) in enumerate(lidos):
        if hora is None:
            seguintes = [h for _d, h in lidos[i + 1 :] if h is not None]
            anteriores = [h for _d, h in lidos[:i] if h is not None]
            hora = seguintes[0] if seguintes else (anteriores[-1] if anteriores else None)
        if hora is None:
            raise RespostaRecusadaError("slot_sem_hora")
        resolvidos.append(Slot(dia, hora[0], hora[1]))
    unicos = tuple(sorted(set(resolvidos)))
    if len(unicos) > MAXIMO_DE_ITENS:
        raise RespostaRecusadaError("slots_a_mais")
    return unicos


# ------------------------------------------------------------------ as cores

_HEX: Final = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def ler_cores(texto: str) -> tuple[str, ...]:
    """Ate tres cores em hexadecimal, em maiusculas e de seis digitos, ou nenhuma."""
    if sem_acentos(texto).strip(" .!") in _NENHUM:
        return ()
    achadas = _HEX.findall(texto)
    resto = _HEX.sub(" ", texto)
    if not achadas or re.search(r"[0-9A-Za-z]", re.sub(r"\b(?:e|a|cor|cores)\b", " ", resto, flags=re.I)):
        raise RespostaRecusadaError("cores_fora_da_forma")
    normalizadas: list[str] = []
    for cor in achadas:
        digitos = cor[1:].upper()
        if len(digitos) == 3:
            digitos = "".join(c * 2 for c in digitos)
        if f"#{digitos}" not in normalizadas:
            normalizadas.append(f"#{digitos}")
    if len(normalizadas) > MAXIMO_DE_CORES:
        raise RespostaRecusadaError("cores_a_mais")
    return tuple(normalizadas)


# ------------------------------------------------------------------ os factos

#: Os padroes que fazem de um texto uma **promocao** (criterio 4), sobre o texto
#: sem acentos e com os espacos colapsados, **por palavra** — «leve» so com
#: «pague», e «promo» nao casa «promover» (achado M2 da revisao). E a mesma
#: lista que decide se um facto do dono e uma promocao e que a guarda de
#: numeros le numa legenda (`numeros.py`). *Proposta*: vem do bloco e de
#: conhecimento geral, nao de anuncios contados.
PADROES_DE_PROMOCAO: Final = {
    "promocao": re.compile(r"\bpromoc(?:ao|oes)\b|\bpromo\b"),
    "desconto": re.compile(r"\bdescontos?\b"),
    "saldos": re.compile(r"\bsaldos?\b"),
    "gratis": re.compile(r"\bgratis\b|\bgratuit[oa]s?\b|\bde borla\b"),
    "oferta": re.compile(r"\bofertas?\b"),
    "brinde": re.compile(r"\bbrindes?\b"),
    "leve_pague": re.compile(r"\bleve\b.{0,20}\bpague\b"),
    "metade": re.compile(r"\bmetade do preco\b|\bpela metade\b"),
    "liquidacao": re.compile(r"\bliquidac(?:ao|oes)\b|\bqueima\b"),
    "black_friday": re.compile(r"\bblack friday\b"),
    "preco_especial": re.compile(r"\bprecos? (?:especia(?:l|is)|baix(?:o|os|issimos?)|imbativ\w*|de amigo)\b"),
    "imperdivel": re.compile(r"\bimperdive(?:l|is)\b"),
    "por_tempo_limitado": re.compile(
        r"\bso (?:hoje|esta semana|este mes|amanha)\b|\bpor tempo limitado\b|\bultimos dias\b|\bultimas unidades\b"
    ),
}

#: As genericas: dizem «ha uma promocao», e passam com qualquer promocao valida
#: do dono. As outras tem de estar **na** promocao do dono (`numeros.py`).
PROMOCAO_GENERICA: Final = frozenset({"promocao", "por_tempo_limitado"})


def palavras_de_promocao(texto: str) -> list[str]:
    """Os nomes dos padroes de promocao que casam no texto, pela ordem da lista."""
    limpo = " ".join(sem_acentos(texto).split())
    return [nome for nome, padrao in PADROES_DE_PROMOCAO.items() if padrao.search(limpo)]


_VALIDADE: Final = re.compile(
    r"\bate\s+(?:dia\s+)?(?P<dia>[0-3]?\d)\s*[/.-]\s*(?P<mes>[01]?\d)(?:\s*[/.-]\s*(?P<ano>\d{2,4}))?"
)
#: Uma percentagem (em algarismos ou por extenso) faz de um facto uma promocao.
#: **Um preco nao** (achado M6): «Camisas a 8.000 Kz» e um facto do dono, e
#: entra sem validade.
_PERCENTAGEM: Final = re.compile(r"\d\s*%|\bpor\s?cento\b|\bporcento\b")


@dataclass(frozen=True)
class Facto:
    """Um facto que o dono autoriza a dizer. A promocao leva `valido_ate` (data local)."""

    texto: str
    promocao: bool = False
    valido_ate: datetime.date | None = None

    def para_json(self) -> dict[str, Any]:
        dados: dict[str, Any] = {"texto": self.texto, "promocao": self.promocao}
        if self.valido_ate is not None:
            dados["valido_ate"] = self.valido_ate.isoformat()
        return dados

    @classmethod
    def de_json(cls, valor: Mapping[str, Any]) -> Facto:
        validade = valor.get("valido_ate")
        return cls(
            texto=str(valor["texto"]),
            promocao=bool(valor.get("promocao", False)),
            valido_ate=datetime.date.fromisoformat(validade) if validade else None,
        )

    def vale_em(self, dia: datetime.date) -> bool:
        """Um facto normal vale sempre; uma promocao so ate ao dia da validade."""
        return not self.promocao or (self.valido_ate is not None and dia <= self.valido_ate)


def e_promocao(texto: str) -> bool:
    return bool(palavras_de_promocao(texto)) or bool(_PERCENTAGEM.search(sem_acentos(texto)))


def ler_validade(texto: str, hoje: datetime.date) -> datetime.date | None:
    """A data de «ate DD/MM[/AAAA]», no ano de `hoje` ou no seguinte se ja passou."""
    casado = _VALIDADE.search(sem_acentos(texto))
    if casado is None:
        return None
    dia, mes = int(casado.group("dia")), int(casado.group("mes"))
    ano_escrito = casado.group("ano")
    try:
        if ano_escrito:
            ano = int(ano_escrito) + (2000 if len(ano_escrito) == 2 else 0)
            return datetime.date(ano, mes, dia)
        data = datetime.date(hoje.year, mes, dia)
        return data if data >= hoje else datetime.date(hoje.year + 1, mes, dia)
    except ValueError:
        return None


def ler_factos(texto: str, hoje: datetime.date) -> tuple[Facto, ...]:
    """Os factos de um texto do dono, um por linha (ou por «;»), ou nenhum.

    Uma promocao sem validade, ou com a validade no passado, **recusa a resposta
    inteira** (`promocao_sem_validade`): o criterio 4 so deixa uma promocao
    entrar numa legenda se o dono a deu com a data em que acaba.
    """
    if sem_acentos(texto).strip(" .!") in _NENHUM:
        return ()
    linhas = [" ".join(linha.split()) for linha in re.split(r"[\n;]", texto)]
    linhas = [linha for linha in linhas if linha]
    if not linhas:
        raise RespostaRecusadaError("factos_vazios")
    if len(linhas) > MAXIMO_DE_FACTOS:
        raise RespostaRecusadaError("factos_a_mais")
    factos: list[Facto] = []
    for linha in linhas:
        if len(linha) > TAMANHO_DE_UM_FACTO or len(linha) < 3:
            raise RespostaRecusadaError("facto_fora_da_forma")
        if e_promocao(linha):
            validade = ler_validade(linha, hoje)
            if validade is None:
                raise RespostaRecusadaError("promocao_sem_validade")
            if validade < hoje:
                # Uma data com o ano escrito e ja passada (achado M3): um facto
                # morto que o dono julgava valido. Recusa-se, e diz-se porque.
                raise RespostaRecusadaError("promocao_vencida")
            factos.append(Facto(linha, promocao=True, valido_ate=validade))
        else:
            factos.append(Facto(linha))
    return tuple(factos)


# ------------------------------------------------------------------ as respostas


def _texto_curto(texto: str, minimo: int, maximo: int, motivo: str) -> str:
    limpo = " ".join(texto.split())
    if not minimo <= len(limpo) <= maximo:
        raise RespostaRecusadaError(motivo)
    return limpo


def ler_tom(texto: str) -> str:
    limpo = sem_acentos(texto).strip(" .!")
    for tom in TONS:
        if limpo == tom or limpo == sem_acentos(TITULO_DO_TOM[tom]):
            return tom
    raise RespostaRecusadaError("tom_fora_da_lista")


def ler_resposta(campo: str, texto: str, hoje: datetime.date) -> Any:
    """O valor que uma resposta do dono grava no campo, ou `RespostaRecusadaError`.

    O valor ja vem na forma da coluna: texto, lista de cores, lista de slots em
    JSON, lista de factos em JSON.
    """
    if campo == "nome":
        return _texto_curto(texto, 2, 60, "nome_fora_da_forma")
    if campo == "categoria":
        return _texto_curto(texto, 2, 60, "categoria_fora_da_forma")
    if campo == "tom":
        return ler_tom(texto)
    if campo == "cores":
        return list(ler_cores(texto))
    if campo == "publico":
        return _texto_curto(texto, 2, 200, "publico_fora_da_forma")
    if campo == "slots":
        return [s.para_json() for s in ler_slots(texto)]
    if campo == "factos":
        return [f.para_json() for f in ler_factos(texto, hoje)]
    raise RespostaRecusadaError("campo_desconhecido")


# ------------------------------------------------------------------ o perfil


@dataclass(frozen=True)
class Perfil:
    """O `brand_profile` de um tenant. `None` num campo e «ainda por responder»."""

    tenant_id: str
    nome: str | None = None
    categoria: str | None = None
    tom: str | None = None
    cores: tuple[str, ...] | None = None
    publico: str | None = None
    slots: tuple[Slot, ...] | None = None
    factos: tuple[Facto, ...] | None = None
    logo_asset_id: str | None = None
    idioma: str = "pt-AO"
    versao: int = 1

    def respondido(self, campo: str) -> bool:
        if campo == "logo":
            return self.logo_asset_id is not None
        return getattr(self, campo) is not None

    def em_falta(self) -> tuple[str, ...]:
        return tuple(c for c in CAMPOS_OBRIGATORIOS if not self.respondido(c))

    @property
    def completo(self) -> bool:
        return not self.em_falta()

    def proxima_pergunta(self) -> str | None:
        falta = self.em_falta()
        return falta[0] if falta else None

    def factos_validos(self, dia: datetime.date) -> tuple[Facto, ...]:
        return tuple(f for f in (self.factos or ()) if f.vale_em(dia))

    def vista(self) -> dict[str, Any]:
        return {
            "nome": self.nome,
            "categoria": self.categoria,
            "tom": self.tom,
            "cores": list(self.cores) if self.cores is not None else None,
            "publico": self.publico,
            "slots": [s.para_json() for s in self.slots] if self.slots is not None else None,
            "factos": [f.para_json() for f in self.factos] if self.factos is not None else None,
            "tem_logo": self.logo_asset_id is not None,
            "idioma": self.idioma,
            "versao": self.versao,
        }


def com_resposta(perfil: Perfil, campo: str, valor: Any) -> Perfil:
    """O perfil com o campo gravado (o `valor` ja vem do `ler_resposta`)."""
    convertido: Any = valor
    if campo == "cores":
        convertido = tuple(valor)
    elif campo == "slots":
        convertido = tuple(Slot.de_json(v) for v in valor)
    elif campo == "factos":
        convertido = tuple(Facto.de_json(v) for v in valor)
    elif campo not in ("nome", "categoria", "tom", "publico"):
        raise RespostaRecusadaError("campo_desconhecido")
    campos = {campo: convertido, "versao": perfil.versao + 1}
    return Perfil(**{**perfil.__dict__, **campos})


# ------------------------------------------------------------------ a semana e a agenda


def semana_iso(instante: datetime.datetime) -> str:
    """`AAAA-Www` da semana ISO de um instante, em `Africa/Luanda`."""
    if instante.tzinfo is None:
        raise ValueError("instante sem fuso")
    ano, semana, _dia = instante.astimezone(LUANDA).isocalendar()
    return f"{ano}-W{semana:02d}"


FORMA_DA_SEMANA: Final = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")


def semana_do_calendario(instante: datetime.datetime) -> str:
    """A semana que «IDEIAS» planeia: a **seguinte** a de `instante` (ver o cabecalho)."""
    return semana_iso(instante + datetime.timedelta(days=7))


def inicio_da_semana(semana: str) -> datetime.datetime:
    """A segunda-feira as 00:00 de `Africa/Luanda` da semana, como instante."""
    if not FORMA_DA_SEMANA.match(semana):
        raise ValueError("semana fora da forma")
    ano, numero = int(semana[:4]), int(semana[6:])
    dia = datetime.date.fromisocalendar(ano, numero, 1)
    return datetime.datetime(dia.year, dia.month, dia.day, tzinfo=LUANDA)


def quantos_itens(slots: Sequence[Slot]) -> int:
    """3 a 7 (criterio 2): um por slot, com o minimo e o maximo do criterio."""
    return max(MINIMO_DE_ITENS, min(MAXIMO_DE_ITENS, len(slots)))


def agenda(semana: str, slots: Sequence[Slot]) -> tuple[datetime.datetime, ...]:
    """As horas sugeridas dos itens, em UTC, por ordem. **So codigo**, nunca o modelo.

    Um item por slot preferido, pela ordem da semana. Com menos de tres slots, os
    que faltam vao para os dias seguintes ainda livres, a hora do primeiro slot
    (a semana da a volta ao domingo e recomeca na segunda). Sem slots, recusa:
    um perfil completo tem-nos sempre.
    """
    if not slots:
        raise ValueError("sem slots")
    ordenados = sorted(set(slots))
    n = quantos_itens(ordenados)
    escolhidos = list(ordenados[:n])
    usados = {s.dia for s in escolhidos}
    base = ordenados[0]
    dia = base.dia
    while len(escolhidos) < n:
        dia = (dia + 1) % 7
        if dia in usados:
            continue
        escolhidos.append(Slot(dia, base.hora, base.minuto))
        usados.add(dia)
    inicio = inicio_da_semana(semana)
    instantes = [
        (inicio + datetime.timedelta(days=s.dia, hours=s.hora, minutes=s.minuto)).astimezone(datetime.UTC)
        for s in escolhidos
    ]
    return tuple(sorted(instantes))


def dia_local(instante: datetime.datetime) -> datetime.date:
    return instante.astimezone(LUANDA).date()


def quando(instante: datetime.datetime) -> str:
    """«segunda 18:00» — o texto da hora sugerida, em `Africa/Luanda`."""
    local = instante.astimezone(LUANDA)
    return f"{NOME_DO_DIA[local.weekday()]} {local.hour:02d}:{local.minute:02d}"


# ------------------------------------------------------------------ os temas

#: Os modelos de tema por tipo. Tres por tipo: um «NOVA» roda-os pela geracao.
#: **Sem digitos**, e o que entra de fora e so o nome e a categoria do perfil.
MODELOS_DE_TEMA: Final = {
    "produto": (
        "Um produto em destaque de {nome}",
        "O produto mais pedido da semana em {categoria}",
        "Como se usa um dos produtos de {nome}",
    ),
    "dica": (
        "Uma dica para quem compra {categoria}",
        "Um erro comum ao escolher {categoria}, e como o evitar",
        "Como cuidar bem do que se compra em {categoria}",
    ),
    "bastidores": (
        "Os bastidores de {nome}",
        "Quem faz {nome} acontecer",
        "Um dia normal em {nome}",
    ),
    "promocao": (
        "A promocao em curso: {promocao}",
        "Lembrete da promocao: {promocao}",
        "Ultimos dias da promocao: {promocao}",
    ),
}

#: A ordem dos tipos num calendario sem promocao valida.
CICLO_DE_TIPOS: Final = ("produto", "dica", "bastidores", "produto", "dica", "bastidores", "produto")


@dataclass(frozen=True)
class Tema:
    tipo: str
    tema: str
    agendado_at: datetime.datetime


def temas(perfil: Perfil, semana: str, geracao: int) -> tuple[Tema, ...]:
    """Os temas do calendario de uma semana, deterministicos.

    Um item de `promocao` so existe se houver uma promocao do dono **valida no
    dia em que o item fica agendado**; substitui o primeiro `produto` em cujo
    dia ela vale, e e um so por semana. Sem ela, o calendario nunca fala de
    promocao (criterio 4).
    """
    if not perfil.completo:
        raise ValueError("perfil incompleto")
    assert perfil.slots is not None and perfil.nome is not None and perfil.categoria is not None
    horas = agenda(semana, perfil.slots)
    tipos = list(CICLO_DE_TIPOS[: len(horas)])
    escolhidos: list[Tema] = []
    promocao_usada = False
    for i, (tipo, hora) in enumerate(zip(tipos, horas, strict=True)):
        texto_da_promocao = None
        if tipo == "produto" and not promocao_usada:
            validas = [f for f in perfil.factos_validos(dia_local(hora)) if f.promocao]
            if validas:
                tipo, texto_da_promocao, promocao_usada = "promocao", validas[0].texto, True
        modelos = MODELOS_DE_TEMA[tipo]
        modelo = modelos[(geracao - 1 + i) % len(modelos)]
        texto = modelo.format(nome=perfil.nome, categoria=perfil.categoria, promocao=texto_da_promocao or "")
        escolhidos.append(Tema(tipo=tipo, tema=texto, agendado_at=hora))
    return tuple(escolhidos)


# ------------------------------------------------------------------ as referencias e os botoes

PREFIXO_DA_REFERENCIA: Final = "SOC-"
_LETRAS: Final = "ABCDEFGHJKLMNPQR"
REFERENCIA_NO_TEXTO: Final = re.compile(r"\bSOC-([A-HJ-NP-R]{8})\b", re.IGNORECASE)
FORMA_DA_REFERENCIA: Final = r"^SOC-[A-HJ-NP-R]{8}$"


def referencia_do_item(content_item_id: object) -> str:
    """`SOC-` e oito letras derivadas do `id` do item. Sem digitos (o #237)."""
    return PREFIXO_DA_REFERENCIA + "".join(_LETRAS[int(c, 16)] for c in uuid.UUID(str(content_item_id)).hex[:8])


def prefixo_da_referencia(referencia: object) -> str | None:
    """Os oito hexadecimais de onde uma referencia `SOC-…` veio, ou `None`."""
    if not isinstance(referencia, str):
        return None
    casado = re.fullmatch(r"SOC-([A-HJ-NP-R]{8})", referencia.strip().upper())
    if casado is None:
        return None
    return "".join(f"{_LETRAS.index(c):x}" for c in casado.group(1))


def referencia_no_texto(texto: str) -> tuple[str | None, str]:
    """`(referencia, resto)`."""
    achada = REFERENCIA_NO_TEXTO.search(texto)
    referencia = f"SOC-{achada.group(1).upper()}" if achada else None
    resto = " ".join(REFERENCIA_NO_TEXTO.sub(" ", texto).split()).strip(" :;,-")
    return referencia, resto


#: Os botoes da conversa social. Todos so com letras.
PREFIXO_DO_TOM: Final = "tom:"
PREFIXO_DA_LEGENDA: Final = "legenda:"
BOTAO_NOVA: Final = "social:nova"
BOTAO_IDEIAS: Final = "social:ideias"


def botao_do_tom(tom: str) -> str:
    if tom not in TONS:
        raise ValueError("tom fora da lista")
    return f"{PREFIXO_DO_TOM}{tom}"


def botao_da_legenda(referencia: str) -> str:
    return botao_do_item(PREFIXO_DA_LEGENDA, referencia)


#: Os botoes de um item depois da legenda (KAM-122). O Aprovar **nao** esta aqui:
#: e o `confirm:{action_id}` da `owner_actions` (decisao D4 do fundador).
PREFIXO_DA_ARTE: Final = "arte:"
PREFIXO_DE_EDITAR: Final = "editar:"
PREFIXO_DE_REJEITAR: Final = "rejeitar:"
PREFIXO_DE_ENVIAR: Final = "enviar:"
_ACCOES_DO_ITEM: Final = {
    PREFIXO_DA_LEGENDA: "legenda",
    PREFIXO_DA_ARTE: "arte",
    PREFIXO_DE_EDITAR: "editar",
    PREFIXO_DE_REJEITAR: "rejeitar",
    PREFIXO_DE_ENVIAR: "enviar",
}


def botao_do_item(prefixo: str, referencia: str) -> str:
    if prefixo not in _ACCOES_DO_ITEM or prefixo_da_referencia(referencia) is None:
        raise ValueError("botao fora da forma")
    return f"{prefixo}{referencia}"


@dataclass(frozen=True)
class BotaoSocial:
    accao: str  # "tom", "legenda", "arte", "editar", "rejeitar", "enviar", "nova", "ideias"
    valor: str = ""


def ler_botao(botao: object) -> BotaoSocial | None:
    """O botao social de um `id`, ou `None` se nao for deste modulo."""
    if not isinstance(botao, str):
        return None
    if botao == BOTAO_NOVA:
        return BotaoSocial("nova")
    if botao == BOTAO_IDEIAS:
        return BotaoSocial("ideias")
    if botao.startswith(PREFIXO_DO_TOM) and botao[len(PREFIXO_DO_TOM) :] in TONS:
        return BotaoSocial("tom", botao[len(PREFIXO_DO_TOM) :])
    for prefixo, accao in _ACCOES_DO_ITEM.items():
        if botao.startswith(prefixo):
            referencia = botao[len(prefixo) :]
            if prefixo_da_referencia(referencia) is not None:
                return BotaoSocial(accao, referencia.upper())
    return None
