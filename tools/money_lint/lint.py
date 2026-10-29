"""O varrimento: nenhum montante por `number` nem por virgula flutuante.

O criterio 1 do KAM-052 pede «um *lint* falha o *build* se um montante for
`number` ou virgula flutuante em qualquer ficheiro de `pay-core`». Este modulo e
esse lint.

## Porque e um lint e nao so o tipo `Minor = bigint`

Porque o tipo protege as **fronteiras** e nao o meio. `Minor` e `bigint`, e por
isso nenhuma assinatura publica aceita um `number`; mas dentro de uma funcao
nada impede `Number(valor) / 100`, `montante.toFixed(2)` ou um literal `0.14`, e
foi exactamente assim que o `outbound/tarifas.ts` (KAM-015) descreve o defeito
que o custo da Meta teve de evitar. O tipo diz o que entra; o lint diz o que se
faz lá dentro.

## As seis regras, e o que cada uma impede

    FLUTUANTE     um literal com ponto decimal (`0.14`, `1.0`). Nao ha valor de
                  dinheiro que precise de um, e os que **nao** sao dinheiro
                  (percentagens, factores) nao existem neste modulo
    NUMBER        `number` numa declaracao cujo nome e de dinheiro
                  (`amount`, `valor`, `minor`, `preco`, `fee`, `taxa`, `base`,
                  `comissao`, `montante`, `saldo`)
    CONVERSAO     `parseFloat`, `parseInt`, `Number(`, `.toFixed(`, `Math.round`,
                  `Math.floor`, `Math.ceil`, `+valor` sobre dinheiro
    DIVISAO       `/` ou `*` entre um nome de dinheiro e um literal decimal
    SEM_FUNDOS    `balance`, `wallet`, `escrow`, `saldo` — a G-3 do §10.4
                  («nao existe `balance`/`wallet`»), que e ADR-004 no vocabulario
    MINOR         o alias `Minor` declarado como algo que nao seja `bigint`
    ILEGIVEL      nao se conseguiu ler o ficheiro; o que nao se le nao passa

## O ambito, e porque exclui os testes

Varre `packages/core-ts/src/pagamentos/`, que e o `pay-core` do bloco (ver o
cabecalho de `index.ts` para a razao de o modulo morar ali e nao em
`services/pay/`). **Nao varre os testes**, e isso e deliberado e nao uma lacuna:
o canario do *harness* de conformidade tem de poder escrever a conversao errada
para provar que o caso 2 a apanha — e a mesma separacao que as *fixtures*
negativas do `canon_lint` tem face as superficies que ele varre. Um `parseFloat`
num ficheiro de `src/pagamentos/` e um defeito; num ensaio que exige que ele
falhe, e o objecto da medicao.

A lista de raizes e enumerada de proposito, como o `PACOTES_NODE`: quando o
KAM-056 criar o adaptador do ProxyPay, acrescentar o caminho aqui e uma
alteracao visivel em vez de uma deteccao silenciosa.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

FLUTUANTE = "flutuante"
NUMBER = "number"
CONVERSAO = "conversao"
DIVISAO = "divisao"
SEM_FUNDOS = "sem_fundos"
MINOR = "minor"
ILEGIVEL = "ilegivel"

#: As raizes varridas. Enumeradas de proposito — ver o cabecalho.
RAIZES = ("packages/core-ts/src/pagamentos",)

EXTENSOES = (".ts", ".mts", ".cts")

#: Os nomes que denunciam um valor de dinheiro. Em ingles e em portugues, porque
#: o dicionario §2 poe o dominio em portugues e o tecnico em ingles, e este
#: modulo tem os dois (`amount_minor` e `valor_minor` sao a mesma coluna vista
#: de dois documentos).
NOMES_DE_DINHEIRO = (
    "amount",
    "valor",
    "montante",
    "minor",
    "preco",
    "price",
    "fee",
    "taxa",
    "comissao",
    "commission",
    "base_minor",
    "saldo",
    "balance",
    "total",
    "subtotal",
    "iva",
    "centimos",
    "kz",
)

#: Os nomes que a G-3 proibe. **Nao e a mesma lista** que a de cima, e a
#: diferenca importa: `valor` e um nome legitimo que tem de ser inteiro; `wallet`
#: e um nome que nao pode existir, porque a plataforma nao detem fundos
#: (ADR-004). O `saldo`/`balance` esta nas duas.
NOMES_SEM_FUNDOS = ("balance", "wallet", "escrow", "saldo", "carteira", "custodia")

_DINHEIRO = "|".join(NOMES_DE_DINHEIRO)

#: Um literal com ponto decimal. Exclui o que nao e numero: versoes em cadeia
#: (`"1.2"`), caminhos de import e propriedades (`a.b`).
_FLUTUANTE = re.compile(r"(?<![\w.\"'])\d+\.\d+(?![\w.\"'])")

#: `number` numa declaracao cujo nome e de dinheiro. Apanha `let valor: number`,
#: `readonly amount: number`, `fee?: number` e `(preco: number)`.
_NUMBER = re.compile(
    rf"\b\w*(?:{_DINHEIRO})\w*\s*\??\s*:\s*number\b",
    re.IGNORECASE,
)

#: Conversoes que passam por `float`. O `Number(` e o unico que precisa do
#: parentesis: `Number.MAX_SAFE_INTEGER` e uma leitura legitima.
_CONVERSAO = re.compile(
    r"\b(?:parseFloat|parseInt)\s*\(|\bNumber\s*\(|\.toFixed\s*\(|"
    r"\bMath\.(?:round|floor|ceil|trunc|abs)\s*\(",
)

#: `/` ou `*` com um literal decimal de um dos lados.
_DIVISAO = re.compile(r"[*/]\s*\d+\.\d+|\d+\.\d+\s*[*/]")

_SEM_FUNDOS = re.compile(
    r"\b\w*(?:" + "|".join(NOMES_SEM_FUNDOS) + r")\w*\b",
    re.IGNORECASE,
)

#: `type Minor = <algo>`. O grupo 1 e o que ele e.
_MINOR = re.compile(r"\btype\s+Minor\s*=\s*([A-Za-z_][\w.<>\[\] |]*)")

#: Comentarios de linha e de bloco, e cadeias. As regras aplicam-se ao
#: **codigo**: um `0.14` numa frase que explica porque nao se usam flutuantes nao
#: e um defeito, e um lint que o acusasse ensinava a nao escrever a explicacao.
_COMENTARIO_BLOCO = re.compile(r"/\*.*?\*/", re.S)
_COMENTARIO_LINHA = re.compile(r"//[^\n]*")
_CADEIA = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`", re.S)

MENSAGENS = {
    FLUTUANTE: (
        "literal de virgula flutuante: dinheiro e inteiro em unidade menor "
        "(`Minor = bigint`, dicionario §2). Um `0.1 + 0.2` nao da `0.3`"
    ),
    NUMBER: (
        "montante tipado `number`: um IEEE-754 perde centimos "
        "(medido: `Math.trunc(parseFloat('1024.09') * 100)` da 102408). "
        "Usa-se `Minor`, que e `bigint`"
    ),
    CONVERSAO: (
        "conversao por `float`: `parseFloat`, `Number(`, `toFixed` e os "
        "arredondamentos de `Math` passam o valor por IEEE-754. A travessia "
        "`Minor` <-> `decimal2`/`inteiro_kz` e lexical e esta em `dinheiro.ts`"
    ),
    DIVISAO: (
        "aritmetica com literal decimal: divide-se e multiplica-se em `bigint`, "
        "e converte-se **uma** vez no fim para apresentar"
    ),
    SEM_FUNDOS: (
        "nome de saldo ou de custodia: a plataforma nao detem fundos (ADR-004; "
        "`docs/tecnica/04` §10.4 G-3 e G-4: «nao existe `balance`/`wallet`»). "
        "O ledger registra factos; «a receber pela PME» e informativo e rotulado"
    ),
    MINOR: "o alias `Minor` tem de ser `bigint` (docs/tecnica/04 §3.1)",
    ILEGIVEL: "nao se conseguiu analisar o ficheiro; o que nao se le nao passa",
}

#: As regras que o canario tem de ver morder. **Fixas aqui e nao lidas das
#: fixtures**: um manifesto que se esvazia dava «0 negativas, tudo verde», que e
#: o defeito B1 do `docs/analises/ANALISE-05` e a razao de o `canon_lint` ter a
#: mesma constante no codigo.
REGRAS_OBRIGATORIAS = (FLUTUANTE, NUMBER, CONVERSAO, DIVISAO, SEM_FUNDOS, MINOR)


class ConfiguracaoInvalida(RuntimeError):
    """A arvore nao tem a forma que o lint precisa para dizer alguma coisa."""


@dataclasses.dataclass(frozen=True)
class Achado:
    ficheiro: str
    linha: int
    regra: str

    def __str__(self) -> str:
        return f"{self.ficheiro}:{self.linha}: [{self.regra}] {MENSAGENS[self.regra]}"


def _sem_comentarios_nem_cadeias(fonte: str) -> str:
    """Substitui comentarios e cadeias por espacos, **preservando as linhas**.

    Preservar o numero de linhas nao e detalhe: sem isso cada achado depois de um
    comentario de bloco aponta para a linha errada, e um lint que aponta para o
    sitio errado e um lint que se ignora.
    """

    def _em_branco(encontro: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", encontro.group(0))

    sem = _COMENTARIO_BLOCO.sub(_em_branco, fonte)
    sem = _COMENTARIO_LINHA.sub(_em_branco, sem)
    return _CADEIA.sub(_em_branco, sem)


def varrer_texto(fonte: str, ficheiro: str) -> list[Achado]:
    """Os achados de um ficheiro. A ordem e a das linhas."""
    achados: list[Achado] = []
    codigo = _sem_comentarios_nem_cadeias(fonte)

    for numero, linha in enumerate(codigo.split("\n"), start=1):
        if not linha.strip():
            continue
        for regra, padrao in (
            (NUMBER, _NUMBER),
            (CONVERSAO, _CONVERSAO),
            (DIVISAO, _DIVISAO),
            (SEM_FUNDOS, _SEM_FUNDOS),
            (FLUTUANTE, _FLUTUANTE),
        ):
            if padrao.search(linha):
                achados.append(Achado(ficheiro, numero, regra))

    for encontro in _MINOR.finditer(codigo):
        if encontro.group(1).strip() != "bigint":
            linha = codigo[: encontro.start()].count("\n") + 1
            achados.append(Achado(ficheiro, linha, MINOR))

    return achados


def ficheiros(raiz: Path) -> list[Path]:
    """Os ficheiros varridos. Vazio e **erro de configuracao**, nao um verde."""
    encontrados: list[Path] = []
    for relativo in RAIZES:
        pasta = raiz / relativo
        if not pasta.is_dir():
            continue
        for caminho in sorted(pasta.rglob("*")):
            if caminho.is_file() and caminho.suffix in EXTENSOES:
                encontrados.append(caminho)
    return encontrados


def varrer(raiz: Path) -> tuple[list[Achado], int]:
    """Varre a arvore. Devolve (achados, quantos ficheiros leu).

    **Zero ficheiros levanta.** E a licao que o `canon_lint` escreve por extenso:
    «uma superficie com zero ficheiros passa sempre, e a unica defesa contra ler
    isso como "esta tudo bem" e a saida dize-lo por extenso.» Aqui vai um passo
    mais longe e recusa-se a devolver 0, porque um lint de dinheiro que nao
    encontrou dinheiro nenhum nao verificou nada.
    """
    lidos = ficheiros(raiz)
    if not lidos:
        raise ConfiguracaoInvalida(
            "nenhum ficheiro varrido em "
            + ", ".join(RAIZES)
            + ". Um lint de dinheiro que nao encontra dinheiro nao verificou "
            "nada — e se o modulo mudou de sitio, o `RAIZES` do "
            "`tools/money_lint/lint.py` muda com ele."
        )
    achados: list[Achado] = []
    for caminho in lidos:
        relativo = caminho.relative_to(raiz).as_posix()
        try:
            fonte = caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            achados.append(Achado(relativo, 0, ILEGIVEL))
            continue
        achados.extend(varrer_texto(fonte, relativo))
    return achados, len(lidos)


# ----------------------------------------------------------------- o canario


def canario(pasta: Path) -> tuple[list[str], dict[str, int]]:
    """As negativas tem de dar a regra do seu nome; as positivas, nada.

    Uma negativa chama-se `<regra>__<descricao>.ts`. E a forma do
    `log_policy.canario`, e pela mesma razao: a prova de que o lint morde tem de
    correr **no gate**, nao so num `unittest` — um teste de `lint_refs` esteve
    vermelho em sete PRs com o gate verde.
    """
    falhas: list[str] = []
    vistas: set[str] = set()
    numeros = {"negativas": 0, "positivas": 0}

    def _listar(nome: str) -> list[Path]:
        sub = pasta / nome
        return sorted(p for p in sub.glob("*") if p.suffix in EXTENSOES) if sub.is_dir() else []

    for caminho in _listar("negativas"):
        numeros["negativas"] += 1
        esperada = caminho.name.split("__", 1)[0]
        if esperada not in MENSAGENS:
            falhas.append(f"{caminho.name}: `{esperada}` nao e uma regra deste lint")
            continue
        achados = varrer_texto(caminho.read_text(encoding="utf-8"), caminho.name)
        regras = {a.regra for a in achados}
        if esperada not in regras:
            falhas.append(
                f"{caminho.name}: devia dar `{esperada}` e deu "
                f"{sorted(regras) or 'nada'} — o lint nao morde nesta regra"
            )
            continue
        vistas.add(esperada)

    for caminho in _listar("positivas"):
        numeros["positivas"] += 1
        achados = varrer_texto(caminho.read_text(encoding="utf-8"), caminho.name)
        if achados:
            falhas.append(
                f"{caminho.name}: devia estar limpo e deu {[str(a) for a in achados]}"
            )

    em_falta = [r for r in REGRAS_OBRIGATORIAS if r not in vistas]
    if em_falta:
        falhas.append(
            "sem negativa para: "
            + ", ".join(em_falta)
            + " — uma regra sem canario e uma regra que pode ter deixado de morder"
        )
    if numeros["positivas"] == 0:
        falhas.append(
            "sem positivas: sem elas o canario prova que o lint acusa e nao "
            "prova que ele deixa passar o codigo correcto"
        )
    return falhas, numeros
