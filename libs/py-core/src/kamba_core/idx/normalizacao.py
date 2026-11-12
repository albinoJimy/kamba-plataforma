"""A normalizacao PT-AO: os nove passos do `docs/tecnica/05` §5.1 (KAM-062).

**Determinista e sem LLM.** Tudo aqui e funcao pura sobre tres entradas — o
texto, o lexico do tenant e o vocabulario do tenant — e o modulo nao importa
nada que fale com a rede (o ensaio le os `import` deste ficheiro). O que le a
base esta em `kamba_core.idx.lexico`, que constroi as entradas e chama isto.

## Os dois lados

| Passo | Indice (`normalizar_documento`) | Consulta (`normalizar`) |
|---|---|---|
| 1. NFKC, minusculas, sem acentos, sem pontuacao | sim | sim |
| 2. numeros por extenso | nao | so `origem = 'voz'` |
| 3. restricoes de preco | nao | sim, e **saem** do texto |
| 4. unidades (`tipo = 'unidade'`) | sim | sim |
| 5. marcas (`tipo = 'marca'`) | sim | sim |
| 6. erros comuns (`tipo = 'erro_comum'`) e *typo* por vocabulario | nao | sim |
| 7. *stopwords* (`tipo = 'stopword'`) | nao | sim |
| 8. sinonimos (`tipo = 'sinonimo'`), so no `q_or` | nao | sim |

E por isso que alterar um sinonimo **nao** obriga a reindexar e alterar uma
marca ou unidade obriga (§4.4, criterio 4): so os passos 4 e 5 escrevem no
`nome_norm`. O `nome_norm` e o `q_norm` passam pelos mesmos passos 1, 4 e 5 —
um indice e uma consulta normalizados por funcoes diferentes divergem na
primeira marca que uma delas canonize e a outra nao.

## O lexico e de quem

Todo o lexico — marcas, unidades, erros comuns, *stopwords* e sinonimos — vem
do `idx.termo_canonico`, e **nenhum esta escrito aqui**. O do §5.1 e
ilustrativo e NAO VERIFICADO (nao foi revisto por falantes de PT-AO): so entra
em producao curado por *ops*, revisto por falantes e validado contra o dataset
do KAM-064. Os ensaios usam-no como *fixture*, e so como *fixture*.

O que esta aqui e gramatica e nao lexico: os numeros por extenso, a forma das
restricoes de preco do §5.2 e as palavras funcionais do portugues que nao se
tratam como *typo* (`_FUNCIONAIS`).

## Precedencia

O termo do tenant prevalece sobre o global (§4.4). Um termo de **outro** tenant
nunca se aplica: a RLS do `idx.termo_canonico` ja nao o deixa ler, e o
`Lexico.de_linhas` descarta-o outra vez — defesa em profundidade, com ensaio.

## *Typo* por vocabulario (§5.3)

Um *token* que nao esta no vocabulario do tenant procura o vocabulo de maior
semelhanca de trigramas (a do `pg_trgm`, reimplementada em `semelhanca` e
cruzada com a do PostgreSQL no *gate* 8), com a frequencia como desempate e a
ordem alfabetica como desempate final. **So corrige com semelhanca >= 0,6**
(`LIMIAR_DE_CORRECCAO`). O vocabulario vem so de documentos visiveis do tenant e
sem palavras vazias da configuracao `idx.kamba_pt`, pelo que um vocabulo
corrigido e um termo que o ramo `fts` encontra num documento visivel; e como o
`q_or` liga os termos por `or` (D7), a **pergunta inteira** corrigida tambem
devolve esse documento, diga o resto o que disser. E o «>= 1 candidato apos
correccao» do criterio 5, e o *gate* 8 mede-o com a palavra sozinha e com a
frase. Duas fronteiras, ditas: o filtro de preco da oferta viva corre **depois**
(um tecto pode esvaziar a resposta, e isso e o tecto, nao a correccao); e os
erros comuns da **tabela** (`erro_comum`) corrigem sem limiar, porque sao
curados — o proprio criterio pede «niker» -> «nike», e a semelhanca dos dois e
4/7, abaixo de 0,6. Abaixo do limiar, o *token* vai para
`tokens_nao_resolvidos` e o AGR pergunta (se nada passar o limiar do grafo).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from .numeros import NUMERO, Restricoes, extrair_restricoes, por_extenso

#: As origens do texto (§5.1). Lista fechada.
ORIGENS: Final = ("texto", "voz")

#: O separador da expansao, como o `websearch_to_tsquery` o le (§6.2, D7).
SEPARADOR_OR: Final = " or "

#: A semelhanca minima para corrigir um *typo* (§5.3, criterio 5).
LIMIAR_DE_CORRECCAO: Final = 0.6

#: O separador das alternativas de um sinonimo ambiguo: `telefone` ->
#: `telemovel|telefone fixo` (§5.1, «ambiguo -> perguntar», criterio 9). O
#: indice unico do §4.4 (`tenant`, `tipo`, `termo`) deixa um so canonico por
#: termo, e e no canonico que as alternativas se escrevem.
SEPARADOR_DE_ALTERNATIVAS: Final = "|"

#: O maior numero de palavras de um termo do lexico («i phone», «por favor»).
MAX_PALAVRAS_DO_TERMO: Final = 4

#: O tamanho minimo de um *token* para ser candidato a *typo*. Abaixo disto
#: («tv», «lg») a semelhanca de trigramas nao distingue nada.
TAMANHO_MINIMO_DO_TYPO: Final = 3

#: Palavras funcionais do portugues: gramatica, nao lexico. Nunca sao *typo*
#: nem «nao resolvido» — senao «geleira **de** 250 l» perguntava pelo «de».
_FUNCIONAIS: Final = frozenset(
    "a o as os um uma uns umas de da do das dos em na no nas nos para pra pro "
    "por pelo pela com sem que e ou se ao aos me te lhe eu tu ele ela nos vos "
    "eles elas este esta esse essa isto isso aquele aquela mais menos muito "
    "tem ha".split()
)

#: Tudo o que nao e letra nem algarismo passa a espaco (passo 1). O `\x01` e o
#: ponto decimal guardado (ver `_DECIMAL`), que volta a ser `.` no fim.
_NAO_PALAVRA: Final = re.compile('[^0-9a-z"\x01]+')

#: Separador de milhares: `250.000` -> `250000` (§5.2, «menos de 250.000 kz»).
_MILHARES: Final = re.compile(r"(?<=\d)\.(?=\d{3}(?!\d))")

#: O que sobra entre algarismos depois dos milhares e decimal: a virgula
#: angolana («1,5 milhoes», «250.000,00») e o ponto («1.5 mil»). Sem isto, a
#: pontuacao partia «1,5» em `1 5`, e o `5 milhoes` virava um preco errado
#: com o `1` no texto do indice (achados 2 e 5 da revisao adversarial).
_DECIMAL: Final = re.compile(r"(?<=\d)[.,](?=\d)")

#: Algarismos colados a um sufixo de preco: `250k`, `250kz`, `250mil` ->
#: `250 k`, `250 kz`, `250 mil`.
_SUFIXO_DE_PRECO: Final = re.compile(r"^(\d+(?:\.\d+)?)(k|kz|akz|aoa|mil)$")

#: Algarismos colados a letras, para o passo 4 separar so quando o sufixo e
#: uma unidade do lexico (`250l` sim, `a52` e `ps5` nao).
_ALGARISMOS_E_LETRAS: Final = re.compile(r"^(\d+)([a-z]+)$")

#: As aspas so sobrevivem ao passo 1 coladas a algarismos (`55"` = polegadas),
#: e passam a *token* proprio para a tabela de unidades as ler.
_ASPAS_DEPOIS_DE_ALGARISMO: Final = re.compile(r'(\d)\s*"')

#: `$` e `€` passam a palavra antes de a pontuacao desaparecer (§5.2: «qualquer
#: outra moeda -> pergunta»).
_SIMBOLOS_DE_MOEDA: Final = (("us$", " usd "), ("$", " usd "), ("€", " eur "))


def _sem_acentos(texto: str) -> str:
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(c for c in decomposto if unicodedata.category(c) != "Mn")


def passo_1(texto: str) -> list[str]:
    """NFKC, minusculas, sem acentos, sem emojis nem pontuacao, em *tokens*.

    Igual ao `kamba_core.idx.texto.normalizar` do KAM-061, mais tres cuidados
    que o §5.2 pede: o separador de milhares, os simbolos de moeda e as aspas
    de polegadas coladas a algarismos.

    >>> passo_1('Geleira LG 55", até 250.000 Kz!! 😀')
    ['geleira', 'lg', '55', '"', 'ate', '250000', 'kz']
    >>> passo_1("até 250.000,00 kz ou 1,5 milhões")
    ['ate', '250000.00', 'kz', 'ou', '1.5', 'milhoes']
    """
    base = _sem_acentos(unicodedata.normalize("NFKC", texto).lower())
    for simbolo, palavra in _SIMBOLOS_DE_MOEDA:
        base = base.replace(simbolo, palavra)
    base = _MILHARES.sub("", base)
    base = _DECIMAL.sub("\x01", base)
    base = _ASPAS_DEPOIS_DE_ALGARISMO.sub(lambda m: m.group(1) + " \x00", base)
    base = base.replace('"', " ").replace("\x00", '"')
    tokens: list[str] = []
    for token in _NAO_PALAVRA.sub(" ", base).split():
        token = token.replace("\x01", ".")
        sufixo = _SUFIXO_DE_PRECO.match(token)
        tokens.extend(sufixo.groups() if sufixo else (token,))
    return tokens


# ---------------------------------------------------------------- lexico


def _palavras_do_termo(termo: str) -> tuple[str, ...]:
    """O termo do lexico pelo passo 1. As aspas sozinhas sao a unidade `"`."""
    if termo.strip() == '"':
        return ('"',)
    return tuple(passo_1(termo))


@dataclass(frozen=True)
class Termo:
    """Uma linha activa do `idx.termo_canonico`, ja resolvida para um tenant."""

    tipo: str
    termo: tuple[str, ...]
    canonico: str
    peso: float = 1.0
    do_tenant: bool = False


@dataclass(frozen=True)
class Lexico:
    """O lexico de **um** tenant: o seu e o global, com o seu a prevalecer.

    Constroi-se com `de_linhas`; o construtor directo e para ensaios.
    """

    tenant_id: str | None
    termos: Mapping[tuple[str, tuple[str, ...]], Termo] = field(default_factory=dict)
    norm_versao: int = 1

    @classmethod
    def de_linhas(
        cls,
        linhas: Iterable[Mapping[str, object]],
        tenant_id: object,
        *,
        norm_versao: int = 1,
    ) -> Lexico:
        """As linhas do `idx.termo_canonico` para o tenant `tenant_id`.

        Ficam as globais (`tenant_id` nulo) e as do tenant; as de outro tenant
        **descartam-se**, e as inactivas tambem. Em conflito no mesmo
        `(tipo, termo)`, ganha a do tenant (§4.4).
        """
        alvo = str(tenant_id) if tenant_id is not None else None
        termos: dict[tuple[str, tuple[str, ...]], Termo] = {}
        for linha in linhas:
            if linha.get("activo", True) is False:
                continue
            dono = linha.get("tenant_id")
            dono = str(dono) if dono is not None else None
            if dono is not None and dono != alvo:
                continue
            tipo = str(linha["tipo"])
            palavras = _palavras_do_termo(str(linha["termo"]))
            if not palavras:
                continue
            chave = (tipo, palavras)
            # O canonico passa pelo mesmo passo 1, alternativa a alternativa.
            alternativas = (
                " ".join(passo_1(alt))
                for alt in str(linha["canonico"]).split(SEPARADOR_DE_ALTERNATIVAS)
            )
            novo = Termo(
                tipo=tipo,
                termo=palavras,
                canonico=SEPARADOR_DE_ALTERNATIVAS.join(a for a in alternativas if a),
                peso=float(linha.get("peso", 1.0) or 1.0),  # type: ignore[arg-type]
                do_tenant=dono is not None,
            )
            existente = termos.get(chave)
            if existente is None or (novo.do_tenant and not existente.do_tenant):
                termos[chave] = novo
        return cls(tenant_id=alvo, termos=termos, norm_versao=norm_versao)

    def __post_init__(self) -> None:
        # Os termos por tipo e as palavras protegidas do *typo*, calculados uma
        # vez por lexico e nao em cada consulta: o lexico vive no *cache* e a
        # consulta corre no orcamento de 20 ms do criterio 10.
        por_tipo: dict[str, dict[tuple[str, ...], Termo]] = {}
        for (tipo, palavras), termo in self.termos.items():
            por_tipo.setdefault(tipo, {})[palavras] = termo
        protegidas = frozenset(
            palavra
            for tipo in ("stopword", "sinonimo", "marca", "unidade")
            for termo in por_tipo.get(tipo, {}).values()
            for palavra in (
                *termo.termo,
                *termo.canonico.replace(SEPARADOR_DE_ALTERNATIVAS, " ").split(),
            )
        )
        object.__setattr__(self, "_por_tipo", por_tipo)
        object.__setattr__(self, "_protegidas", protegidas)

    def do_tipo(self, tipo: str) -> Mapping[tuple[str, ...], Termo]:
        """Os termos de um tipo, pelas suas palavras."""
        return self._por_tipo.get(tipo, {})  # type: ignore[attr-defined]

    @property
    def protegidas(self) -> frozenset[str]:
        """As palavras do lexico que nunca sao *typo* (termos e canonicos)."""
        return self._protegidas  # type: ignore[attr-defined]


def _substituir(
    tokens: Sequence[str],
    termos: Mapping[tuple[str, ...], Termo],
) -> tuple[list[str], list[Termo]]:
    """Troca cada ocorrencia de um termo pelo seu canonico, a mais longa primeiro."""
    saida: list[str] = []
    aplicados: list[Termo] = []
    i = 0
    while i < len(tokens):
        for n in range(min(MAX_PALAVRAS_DO_TERMO, len(tokens) - i), 0, -1):
            termo = termos.get(tuple(tokens[i : i + n]))
            if termo is not None:
                saida.extend(termo.canonico.split())
                aplicados.append(termo)
                i += n
                break
        else:
            saida.append(tokens[i])
            i += 1
    return saida, aplicados


def _separar_unidades(tokens: Sequence[str], unidades: Mapping[tuple[str, ...], Termo]) -> list[str]:
    """`250l` -> `250 l` quando `l` e uma unidade do lexico; `a52` fica."""
    sufixos = {p[0] for p in unidades if len(p) == 1} | {
        t.canonico for t in unidades.values() if " " not in t.canonico
    }
    saida: list[str] = []
    for token in tokens:
        colado = _ALGARISMOS_E_LETRAS.match(token)
        if colado and colado.group(2) in sufixos:
            saida.extend(colado.groups())
        else:
            saida.append(token)
    return saida


def _passos_4_e_5(tokens: Sequence[str], lexico: Lexico) -> tuple[list[str], str | None]:
    """Unidades e marcas canonicas: o que os dois lados partilham."""
    unidades = lexico.do_tipo("unidade")
    separadas = _separar_unidades(tokens, unidades)
    com_unidades, _ = _substituir(separadas, unidades)
    com_marcas, marcas = _substituir(com_unidades, lexico.do_tipo("marca"))
    marca_canon = marcas[0].canonico if marcas else None
    return com_marcas, marca_canon


# ---------------------------------------------------------------- vocabulario


def trigramas(texto: str) -> frozenset[str]:
    """Os trigramas do `pg_trgm`: por palavra, `'  '` antes e `' '` depois.

    >>> sorted(trigramas("nike"))
    ['  n', ' ni', 'ike', 'ke ', 'nik']
    """
    conjunto: set[str] = set()
    for palavra in re.findall(r"[0-9a-z]+", texto.lower()):
        com_margem = "  " + palavra + " "
        conjunto.update(com_margem[i : i + 3] for i in range(len(com_margem) - 2))
    return frozenset(conjunto)


def semelhanca(a: str, b: str) -> float:
    """O `similarity()` do `pg_trgm`: trigramas comuns sobre trigramas distintos."""
    ta, tb = trigramas(a), trigramas(b)
    if not ta or not tb:
        return 0.0
    comuns = len(ta & tb)
    return comuns / (len(ta) + len(tb) - comuns)


@dataclass(frozen=True)
class Vocabulario:
    """As palavras dos documentos visiveis do tenant, com a frequencia.

    Guarda um indice invertido trigrama -> palavras, para que a procura do
    *typo* nao compare o *token* com o vocabulario inteiro.
    """

    frequencias: Mapping[str, int]
    _por_trigrama: Mapping[str, frozenset[str]] = field(default_factory=dict, repr=False)

    @classmethod
    def de_frequencias(cls, frequencias: Mapping[str, int]) -> Vocabulario:
        por_trigrama: dict[str, set[str]] = {}
        for palavra in frequencias:
            for trigrama in trigramas(palavra):
                por_trigrama.setdefault(trigrama, set()).add(palavra)
        return cls(
            frequencias=dict(frequencias),
            _por_trigrama={t: frozenset(p) for t, p in por_trigrama.items()},
        )

    def __contains__(self, palavra: object) -> bool:
        return palavra in self.frequencias

    def melhor(self, token: str) -> tuple[str, float] | None:
        """O vocabulo mais semelhante: semelhanca, frequencia, ordem alfabetica."""
        candidatos: set[str] = set()
        for trigrama in trigramas(token):
            candidatos.update(self._por_trigrama.get(trigrama, ()))
        if not candidatos:
            return None
        escolhido = min(
            candidatos,
            key=lambda p: (-semelhanca(token, p), -self.frequencias[p], p),
        )
        return escolhido, semelhanca(token, escolhido)


# ---------------------------------------------------------------- resultado


@dataclass(frozen=True)
class Desambiguacao:
    """Um termo com mais de um sentido: o AGR pergunta (criterio 9)."""

    termo: str
    alternativas: tuple[str, ...]


@dataclass(frozen=True)
class Normalizacao:
    """O que o passo 9 devolve, e o que cada consumidor le.

    `q_norm` e `q_or` vao ao `idx.candidatos`; `restricoes` vai a oferta viva
    (§6.3) e **nunca** ao indice; `tokens_nao_resolvidos` e `desambiguacoes`
    sao as perguntas do AGR; `correccoes` diz o que se corrigiu, para o ensaio
    e para quem depura, e nunca vai a um registo.
    """

    q_norm: str
    q_or: str
    restricoes: Restricoes
    tokens_nao_resolvidos: tuple[str, ...]
    norm_versao: int
    desambiguacoes: tuple[Desambiguacao, ...] = ()
    correccoes: tuple[tuple[str, str], ...] = ()

    def como_dict(self) -> dict[str, object]:
        """Os cinco campos do criterio 1, e as perguntas."""
        return {
            "q_norm": self.q_norm,
            "q_or": self.q_or,
            "restricoes": self.restricoes.como_dict(),
            "tokens_nao_resolvidos": list(self.tokens_nao_resolvidos),
            "norm_versao": self.norm_versao,
            "desambiguacoes": [
                {"termo": d.termo, "alternativas": list(d.alternativas)}
                for d in self.desambiguacoes
            ],
        }

    @property
    def precisa_de_pergunta(self) -> bool:
        """Ha alguma coisa que o AGR tem de perguntar antes de pesquisar."""
        return bool(
            self.tokens_nao_resolvidos or self.desambiguacoes or self.restricoes.moeda
        )


@dataclass(frozen=True)
class Documento:
    """O lado do indice: o `nome_norm` e a `marca_canon` do documento."""

    nome_norm: str
    marca_canon: str | None
    norm_versao: int


# ---------------------------------------------------------------- os dois lados


def normalizar_documento(nome: str, lexico: Lexico) -> Documento:
    """O texto do catalogo como entra no indice: passos 1, 4 e 5.

    >>> normalizar_documento("Frigorífico LG 250 L", Lexico(None)).nome_norm
    'frigorifico lg 250 l'
    """
    tokens, marca = _passos_4_e_5(passo_1(nome), lexico)
    return Documento(nome_norm=" ".join(tokens), marca_canon=marca, norm_versao=lexico.norm_versao)


def _corrigir(
    tokens: Sequence[str],
    lexico: Lexico,
    vocabulario: Vocabulario | None,
    protegidos: frozenset[str],
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Passo 6: erros comuns pela tabela, depois *typo* pelo vocabulario."""
    tokens, aplicados = _substituir(tokens, lexico.do_tipo("erro_comum"))
    correccoes = [(" ".join(t.termo), t.canonico) for t in aplicados]
    if vocabulario is None:
        return list(tokens), correccoes, []
    saida: list[str] = []
    nao_resolvidos: list[str] = []
    for token in tokens:
        if (
            token in vocabulario
            or token in protegidos
            or token in _FUNCIONAIS
            or not token.isalpha()
            or len(token) < TAMANHO_MINIMO_DO_TYPO
        ):
            saida.append(token)
            continue
        melhor = vocabulario.melhor(token)
        if melhor is not None and melhor[1] >= LIMIAR_DE_CORRECCAO:
            saida.append(melhor[0])
            correccoes.append((token, melhor[0]))
        else:
            saida.append(token)
            if token not in nao_resolvidos:
                nao_resolvidos.append(token)
    return saida, correccoes, nao_resolvidos


def _contem(tokens: Sequence[str], frase: Sequence[str]) -> bool:
    n = len(frase)
    return any(tuple(tokens[i : i + n]) == tuple(frase) for i in range(len(tokens) - n + 1))


def _sinonimos(
    tokens: Sequence[str], lexico: Lexico
) -> tuple[list[str], list[Desambiguacao]]:
    """Passo 8: os canonicos a juntar ao `q_or`, e as ambiguidades."""
    sinonimos = lexico.do_tipo("sinonimo")
    extra: list[str] = []
    ambiguas: list[Desambiguacao] = []
    i = 0
    while i < len(tokens):
        for n in range(min(MAX_PALAVRAS_DO_TERMO, len(tokens) - i), 0, -1):
            termo = sinonimos.get(tuple(tokens[i : i + n]))
            if termo is None:
                continue
            alternativas = tuple(termo.canonico.split(SEPARADOR_DE_ALTERNATIVAS))
            if len(alternativas) == 1:
                extra.extend(alternativas[0].split())
            elif not any(
                _contem(tokens, alt.split()) and len(alt.split()) > n for alt in alternativas
            ):
                # «telefone» sozinho e ambiguo; «telefone fixo» ja respondeu.
                ambiguas.append(Desambiguacao(" ".join(termo.termo), alternativas))
            i += n
            break
        else:
            i += 1
    return extra, ambiguas


def normalizar(
    texto: str,
    tenant_id: object,
    origem: str,
    *,
    lexico: Lexico,
    vocabulario: Vocabulario | None = None,
) -> Normalizacao:
    """`normalizar(texto, tenant_id, origem)` do §5.1, com as entradas explicitas.

    Pura: a mesma entrada da a mesma saida, sem rede, sem relogio e sem
    aleatoriedade. O `tenant_id` tem de ser o do `lexico` — um lexico de outro
    tenant e defeito de ligacao, e levanta em vez de aplicar termos alheios.
    `vocabulario = None` desliga o *typo* por vocabulario (e o modo dos ensaios
    de pureza e de quem nao tem base).
    """
    if origem not in ORIGENS:
        raise ValueError(f"origem desconhecida: {origem!r} (aceita {ORIGENS})")
    alvo = str(tenant_id) if tenant_id is not None else None
    if lexico.tenant_id != alvo:
        raise ValueError("o lexico e de outro tenant: nao se aplicam termos alheios")

    tokens = passo_1(texto)
    if origem == "voz":
        tokens = por_extenso(tokens)
    restricoes, tokens = extrair_restricoes(tokens)
    tokens, _ = _passos_4_e_5(tokens, lexico)

    stopwords = lexico.do_tipo("stopword")
    tokens, correccoes, nao_resolvidos = _corrigir(
        tokens, lexico, vocabulario, lexico.protegidas
    )
    tokens, _ = _substituir(tokens, {k: Termo("stopword", k, "") for k in stopwords})
    extra, ambiguas = _sinonimos(tokens, lexico)

    # Os numeros (inteiros e decimais) e as aspas nao vao ao `q_or` (passo 3).
    termos_or = [
        t for t in dict.fromkeys([*tokens, *extra]) if not NUMERO.fullmatch(t) and t != "\""
    ]
    # Um termo ambiguo nao entra no `q_or` sozinho: pergunta-se primeiro.
    ambiguos = {palavra for d in ambiguas for palavra in d.termo.split()}
    termos_or = [t for t in termos_or if t not in ambiguos]
    return Normalizacao(
        q_norm=" ".join(tokens),
        q_or=SEPARADOR_OR.join(termos_or),
        restricoes=restricoes,
        tokens_nao_resolvidos=tuple(nao_resolvidos),
        norm_versao=lexico.norm_versao,
        desambiguacoes=tuple(ambiguas),
        correccoes=tuple(correccoes),
    )
