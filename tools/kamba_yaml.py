"""Leitor de um subconjunto limitado de YAML, da biblioteca padrao do Python.

**Nao e um parser de YAML.** Aceita a forma que os ficheiros de configuracao
deste repositorio usam e **recusa tudo o resto, em voz alta**.

Existe porque as ferramentas que lhe chamam tem de correr **antes de qualquer
instalacao**:

* `lint_arch` corre como primeiro passo do `make bootstrap` — um linter que
  precisasse de dependencias instaladas para dizer que uma dependencia e
  proibida chegaria sempre tarde (`docs/tecnica/08` §4.8);
* `scan_secrets` corre como *hook* de pre-commit, e o primeiro commit de um
  clone nao tem `.venv` nem `node_modules`.

PyYAML com *hash* resolveria a leitura e perderia as duas propriedades. Esta e a
troca, registada em `docs/adr/ADR-L001-toolchain.md` §6 e §12: ~380 linhas
nossas em vez de uma dependencia na camada que existe para controlar
dependencias.

## O que aceita

```yaml
---                            # um marcador de documento, no inicio, e opcional
chave: escalar                 # texto, inteiro decimal, booleano, nulo
chave: "com aspas"             # aspas simples ou duplas
chave: >-                      # escalar dobrado (as linhas juntam-se com espaco)
  texto que continua
  na linha seguinte
lista:
  - escalar
  - chave: valor               # item que e um mapa
    outra: valor
  - razao: >-                  # tambem como primeira chave do item
      texto que continua
    outra: valor
  - colunas:                   # ou com o bloco a comecar na linha seguinte
      - a
    outra: valor
mapa:
  chave: valor                 # mapa aninhado
  lista:
    - item
vazia: []                      # so a lista vazia, em estilo de fluxo
```

## O que recusa, com erro

A recusa e deliberada: um leitor que aceitasse mais seria reutilizado como se
fosse YAML a serio, e deixaria de se poder confiar em que o que esta no ficheiro
e o que a ferramenta leu. **Esta lista e a garantia, e tem de ser verdadeira** —
cada linha tem um teste em `tools/lint_arch/tests/test_kamba_yaml.py`, e duas
linhas dela estavam falsas na primeira versao do KAM-136, apanhadas pela revisao
adversarial (`docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md` §4, C4).

Estrutura:

* ancoras e *aliases* (`&`, `*`) e *merge keys* (`<<`);
* estilo de fluxo com conteudo (`[a, b]`, `{a: b}`, `{}`) — so `[]` e `[ ]` passam;
* *tags* (`!!str`), directivas (`%YAML`), um segundo `---` e o fim de documento
  (`...`). Os dois marcadores so contam na coluna 0: indentados sao conteudo;
* tabulacoes na indentacao e qualquer indentacao inconsistente;
* chaves repetidas no mesmo mapa;
* documento de topo que nao seja um mapa, e listas aninhadas (`- - a`);
* lista ao nivel da chave que a introduz (`a:` seguido de `- x` sem indentar);
* caracteres de controlo C0 (excepto TAB), `DEL`, e as quebras de linha que o
  YAML 1.1 reconhece e o 1.2 nao (`NEL`, `U+2028`, `U+2029`). O `CR` sozinho **e**
  quebra de linha, como no YAML 1.2.

Escalares em bloco:

* **so `>-`**. O `>` e o `>+` diferem apenas na linha final que preservam, e
  este leitor nao a preserva: aceita-los seria ler `>` como `>-` em silencio.
  O `|`, `|-` e `|+` (literais) tambem se recusam;
* dentro de um `>-`, recusa-se indentacao irregular, linha vazia (que em YAML e
  uma quebra de paragrafo e aqui viraria um espaco) e `#` (que em YAML e
  conteudo e aqui seria cortado como comentario) — **em qualquer posicao do
  bloco, incluindo antes da primeira linha de conteudo**. Era aqui que a lista
  mentia: a primeira versao do KAM-136 so olhava a partir da primeira linha
  sobrevivente, e um `# ver ADR-014` como primeira linha de um `razao: >-`
  desaparecia sem erro.

Escalares:

* aspa aberta e nao fechada, e conteudo depois da aspa de fecho
  (`"a" extra`, `"a" "b"`, `'o ''valor'' certo'`);
* `#` depois de uma aspa aberta e nao fechada: nao se sabe se e comentario ou
  conteudo, e por isso recusa-se em vez de adivinhar;
* escalar nao citado que contenha `: ` ou acabe em `:` — o YAML tambem o
  recusa, e aqui era lido como texto;
* escalares que **parecem numero e nao sao inteiro decimal**: `1.5`, `1e3`,
  `0x1f`, `1_000`, `.inf`, `.nan`, **`017` e `0644`** (octal no YAML 1.1,
  decimal no 1.2) e **`1:30`** (sexagesimal no YAML 1.1). O que estes ficheiros
  descrevem sao limiares e portas; `porta: 0443` lido como 443 ou como 291 nao
  e a mesma regra de rede;
* escalares **ambiguos** como booleano ou nulo: `True`, `FALSE`, `yes`, `no`,
  `on`, `off`, `NULL` — e `None`, que nenhuma versao do YAML resolve mas que
  quem o escreve espera que seja nulo. So `true`, `false`, `null` e `~` passam.
  Para o texto, use aspas.

**Nao interpreta escapes.** O conteudo entre aspas e literal: `"a\\nb"` da a
cadeia de cinco caracteres `a\\nb`, nao uma quebra de linha. E um **desvio do
YAML**, nao uma leitura silenciosa: e a semantica de que
`tools/dict_export/exportar.py` depende (`_texto` escolhe a aspa que o texto nao
contem e recusa o que contenha as duas), e a verificacao de ida-e-volta do
`render` prova que quem escreve e quem le concordam. Uma aspa escapada (`\\"`)
dentro de aspas duplas cai na recusa de «conteudo depois da aspa de fecho».

**Uma recusa que recusa de mais, conhecida e aceite.** Uma linha de conteudo de
um escalar dobrado que comece por uma aspa, nao a feche, e tenha um ` #` depois
e recusada, porque os comentarios tiram-se linha a linha antes de se saber se a
linha e conteudo de bloco. O YAML leria aquilo como texto. A recusa e alta e
diagnostica; saber que a linha e conteudo exigia reordenar o leitor.

## Os dois erros silenciosos que o KAM-136 fechou

Antes do KAM-136 havia dois casos em que este leitor **lia mal sem o dizer** —
num leitor cuja premissa e «recusa o que nao entendes», o modo de falha mais
caro que existe, porque nao ha sintoma:

1. **`>-` como primeira chave de um item de lista engolia as chaves seguintes.**
   `- razao: >-` seguido de `caminho:` e `obrigatorio:` dava um item com uma so
   chave e um `razao` que continha o texto *e* as outras chaves. O defeito era a
   indentacao do pai passada a dobra (`indentacao_chave - 1` em vez de
   `indentacao_chave`), nao uma regra em falta: por isso corrigiu-se a leitura
   em vez de a recusar.
2. **Item de lista nao citado com `:` tornava-se um mapa.** `- https://x` dava
   `{"https": "//x"}`. O YAML exige `:` seguido de espaco ou fim de linha para
   separar chave de valor; este leitor nao o exigia. Passou a exigir, e o item
   le-se como a cadeia que e.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = ["YamlSubsetError", "load", "load_file"]


class YamlSubsetError(ValueError):
    """O ficheiro usa YAML fora do subconjunto aceite."""


_PROIBIDOS = {
    "&": "ancora",
    "*": "alias",
    "|": "escalar literal",
    "{": "mapa em estilo de fluxo",
    "!": "tag",
    "%": "directiva",
}

#: Indicadores de escalar em bloco. So `>-` se aceita; ver o *docstring*.
_DOBRADO = ">-"
_BLOCO = (">", ">-", ">+", "|", "|-", "|+")

#: O `(?=[ \t]|$)` e o caso 2 do KAM-136: sem ele, `- https://x` virava um mapa.
_CHAVE = re.compile(
    r"^(?P<chave>[A-Za-z_][A-Za-z0-9_.-]*|\"[^\"]+\"|'[^']+'):(?=[ \t]|$)(?P<resto>.*)$"
)

#: Caracteres que o YAML 1.2 §5.1 nao admite num documento (C0 sem TAB, e DEL).
#: O `\n` e o `\r` ja foram consumidos pela divisao em linhas.
_CONTROLO = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Quebras de linha do YAML 1.1 que o 1.2 retirou. Lidas como texto, partiam um
#: documento em dois sitios diferentes conforme a versao; recusam-se.
_QUEBRAS_AMBIGUAS = {"\x85": "NEL", "\u2028": "U+2028", "\u2029": "U+2029"}

#: A unica forma numerica que este leitor converte. Deliberadamente nao se usa
#: `int()`: ele aceita `1_000` e algarismos nao-ASCII, que o YAML nao resolve
#: como inteiros — e aceitava-os em silencio.
_INTEIRO = re.compile(r"^[-+]?(0|[1-9][0-9]*)$")

#: Parece numero e nao e inteiro decimal. Recusa-se em vez de virar texto — ou,
#: pior, em vez de virar o numero errado: `017` sao 15 em YAML 1.1 e 17 em 1.2.
_PARECE_NUMERO = re.compile(
    r"""^[-+]?(
          [0-9][0-9_]*\.[0-9_]*([eE][-+]?[0-9]+)?    # 1.5  1.  1.5e3
        | \.[0-9][0-9_]*([eE][-+]?[0-9]+)?           # .5
        | [0-9][0-9_]*[eE][-+]?[0-9]+                # 1e3
        | 0[xXoObB][0-9a-fA-F_]+                     # 0x1f  0o17  0b1
        | [0-9]+_[0-9_]*                             # 1_000
        | 0[0-9][0-9_]*                              # 017  0644  008
        | [0-9]+(:[0-9]{1,2})+                       # 1:30  10:20:30
        | \.(inf|Inf|INF|nan|NaN|NAN)                # .inf  .nan
        )$""",
    re.VERBOSE,
)

#: Resolvem-se como booleano ou nulo em YAML 1.1, em YAML 1.2, ou nos dois — e
#: este leitor dava-os como texto. Recusar e mais barato do que escolher a
#: versao do YAML que ninguem declarou. A excepcao e o `None`, que **nenhuma**
#: versao resolve: entra porque quem escreve `None` espera nulo, e dar-lhe a
#: cadeia `"None"` (verdadeira em Python) e o mesmo genero de surpresa.
_AMBIGUOS = frozenset(
    {
        "True",
        "TRUE",
        "False",
        "FALSE",
        "yes",
        "Yes",
        "YES",
        "no",
        "No",
        "NO",
        "on",
        "On",
        "ON",
        "off",
        "Off",
        "OFF",
        "Null",
        "NULL",
        "None",
    }
)


def _nome_da_chave(bruta: str) -> str:
    """O nome de uma chave, sem **um** par de aspas.

    `.strip("\\"'")` tirava todas as aspas das pontas: a chave `"a'"` ficava
    `a` e a chave `"''"` ficava vazia.
    """
    if len(bruta) >= 2 and bruta[0] == bruta[-1] and bruta[0] in "\"'":
        return bruta[1:-1]
    return bruta


def _escalar(bruto: str, onde: str):
    """Converte um escalar: nulo, booleano, inteiro decimal, ou texto."""
    texto = bruto.strip()
    if texto == "":
        raise YamlSubsetError(f"{onde}: valor vazio (use \"\" para texto vazio)")

    if texto[0] in "\"'":
        aspa = texto[0]
        fim = texto.find(aspa, 1)
        if fim == -1:
            raise YamlSubsetError(f"{onde}: aspa {aspa} aberta e nao fechada ({texto!r})")
        if fim != len(texto) - 1:
            resto = texto[fim + 1 :].strip()
            escapada = texto[fim - 1] == "\\" or resto[:1] == aspa
            pista = (
                "; este leitor nao interpreta escapes nem aspas duplicadas "
                f"({aspa}{aspa} ou \\{aspa}): use a outra aspa"
                if escapada
                else "; este leitor nao junta partes citadas"
            )
            raise YamlSubsetError(
                f"{onde}: conteudo depois da aspa de fecho ({resto!r}){pista}"
            )
        return texto[1:fim]

    if texto[0] in _PROIBIDOS:
        raise YamlSubsetError(f"{onde}: {_PROIBIDOS[texto[0]]} nao suportado ({texto[0]!r})")
    if texto.startswith("<<"):
        raise YamlSubsetError(f"{onde}: merge key nao suportada ('<<')")
    if texto.strip("[] ") == "" and texto.startswith("["):
        return []
    if texto.startswith("["):
        raise YamlSubsetError(f"{onde}: lista em estilo de fluxo com conteudo nao suportada")

    if ": " in texto or texto.endswith(":"):
        # `razao: a: b` dava a cadeia `"a: b"`; o YAML recusa-o («mapping values
        # are not allowed here»). Ler o que o YAML recusa e a mesma classe de
        # defeito que ler mal: o ficheiro nao diz o que a ferramenta leu.
        raise YamlSubsetError(
            f"{onde}: escalar nao citado com ':' ({texto!r}); "
            "o YAML tambem o recusa — use aspas"
        )

    if texto in ("null", "~"):
        return None
    if texto in ("true", "false"):
        return texto == "true"
    if texto in _AMBIGUOS:
        raise YamlSubsetError(
            f"{onde}: {texto!r} e ambiguo entre booleano/nulo e texto; "
            "use `true`, `false`, `null`, ou aspas"
        )
    if _INTEIRO.match(texto):
        return int(texto)
    if _PARECE_NUMERO.match(texto):
        raise YamlSubsetError(
            f"{onde}: {texto!r} parece um numero e este leitor so converte inteiros "
            "decimais sem zero a esquerda; use um inteiro, ou aspas se for texto"
        )
    return texto


def _inicio_do_escalar(linha: str) -> int:
    """Onde comeca o escalar desta linha.

    Neste subconjunto um escalar comeca depois da indentacao, depois dos `- `
    dos itens de lista, e depois do `:` de uma chave. Em mais nenhum sitio uma
    aspa abre uma cadeia citada: em `razao: a - "b # c"` a aspa e texto, e
    tratar qualquer `-` ou `:` anterior como inicio de escalar — o que a
    primeira versao do KAM-136 fazia — guardava o `# c` dentro do valor.
    """
    posicao = len(linha) - len(linha.lstrip(" \t"))
    while linha.startswith("- ", posicao):
        posicao += 2
        while posicao < len(linha) and linha[posicao] == " ":
            posicao += 1
    correspondencia = _CHAVE.match(linha[posicao:])
    if correspondencia:
        posicao += correspondencia.end("chave") + 1
        while posicao < len(linha) and linha[posicao] in " \t":
            posicao += 1
    return posicao


def _sem_comentario(linha: str, onde: str) -> tuple[str, bool]:
    """Remove um comentario de fim de linha, respeitando aspas.

    Devolve `(linha, cortou)`. `razao: "usa # para comentar"` nao perde o `#`.
    """
    inicio = _inicio_do_escalar(linha)
    fora_de_aspas = True
    aspa = ""
    cardinal_ambiguo = -1
    for indice, caractere in enumerate(linha):
        inicio_de_comentario = caractere == "#" and (indice == 0 or linha[indice - 1] in " \t")
        if fora_de_aspas and indice == inicio and caractere in "\"'":
            fora_de_aspas, aspa = False, caractere
        elif not fora_de_aspas and caractere == aspa:
            fora_de_aspas = True
        elif fora_de_aspas and inicio_de_comentario:
            return linha[:indice], True
        elif not fora_de_aspas and inicio_de_comentario and cardinal_ambiguo < 0:
            cardinal_ambiguo = indice
    if not fora_de_aspas and cardinal_ambiguo >= 0:
        raise YamlSubsetError(
            f"{onde}: aspa {aspa} aberta e nao fechada antes de um `#`; "
            "nao se sabe se o `#` e comentario ou conteudo"
        )
    return linha, False


class _Linhas:
    """Linhas com indentacao, sem comentarios nem linhas vazias.

    Guarda tambem o que descartou (`descartadas`: numero da linha -> indentacao,
    ou `None` se a linha era vazia) e, por linha, se lhe cortou um comentario.
    Sem isso, um `#` ou uma linha vazia **dentro** de um escalar dobrado
    desapareciam em silencio — e em YAML sao conteudo.
    """

    def __init__(self, texto: str) -> None:
        self.itens: list[tuple[int, int, str, bool]] = []
        self.descartadas: dict[int, int | None] = {}
        # O BOM e permitido no inicio do *stream* (YAML 1.2 §5.2). Sem isto, um
        # ficheiro gravado por um editor do Windows como «UTF-8 with BOM» era
        # recusado com «esperava 'chave: valor'», que manda procurar um erro de
        # sintaxe que nao existe.
        texto = texto.lstrip("\ufeff")
        for ambigua, nome in _QUEBRAS_AMBIGUAS.items():
            if ambigua in texto:
                numero = texto[: texto.index(ambigua)].count("\n") + 1
                raise YamlSubsetError(
                    f"linha {numero}: {nome} e quebra de linha em YAML 1.1 e nao em 1.2; "
                    "nao se adivinha a versao — tire-o ou use uma quebra de linha"
                )
        # `\r` sozinho **e** quebra de linha (YAML 1.2 §5.4). Sem a segunda
        # substituicao, `a: 1\rb: 2` dava a cadeia `'1\rb: 2'`.
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
        viu_conteudo = False
        for numero, bruta in enumerate(texto.split("\n"), start=1):
            onde = f"linha {numero}"
            achado = _CONTROLO.search(bruta)
            if achado:
                raise YamlSubsetError(
                    f"{onde}: caractere de controlo {achado.group()!r} "
                    "nao e admitido num documento YAML"
                )
            if "\t" in bruta[: len(bruta) - len(bruta.lstrip())]:
                raise YamlSubsetError(f"{onde}: tabulacao na indentacao")
            limpa, cortou = _sem_comentario(bruta, onde)
            limpa = limpa.rstrip()
            # Os marcadores de documento so contam na coluna 0: `---` indentado
            # dentro de um escalar dobrado e conteudo, e era recusado.
            if limpa == "---":
                if viu_conteudo:
                    raise YamlSubsetError(f"{onde}: documentos multiplos nao suportados")
                continue
            if limpa == "...":
                raise YamlSubsetError(f"{onde}: fim de documento ('...') nao suportado")
            if not limpa.strip():
                self.descartadas[numero] = (
                    None if not bruta.strip() else len(bruta) - len(bruta.lstrip(" "))
                )
                continue
            indentacao = len(limpa) - len(limpa.lstrip(" "))
            self.itens.append((numero, indentacao, limpa.strip(), cortou))
            viu_conteudo = True
        self.posicao = 0

    def olhar(self) -> tuple[int, int, str, bool] | None:
        return self.itens[self.posicao] if self.posicao < len(self.itens) else None

    def seguinte(self) -> tuple[int, int, str, bool]:
        item = self.itens[self.posicao]
        self.posicao += 1
        return item


def _ler_dobrado(linhas: _Linhas, indentacao_pai: int, onde: str, indicador: int) -> str:
    """Le um escalar `>-`: as linhas juntam-se com um espaco.

    So e correcto quando as linhas estao todas ao mesmo nivel e nao ha nada
    descartado pelo meio. Tudo o resto recusa-se: em YAML, uma linha mais
    indentada passa a literal, uma linha vazia e uma quebra de paragrafo, e um
    `#` e conteudo — e nenhuma dessas tres coisas este leitor sabe fazer.

    `indicador` e o numero da linha onde esta o `>-`. A fronteira inferior da
    varredura das linhas descartadas **tem de ser ela**, e nao a primeira linha
    de conteudo: com a primeira linha de conteudo, um `# ver ADR-014` ou uma
    linha vazia antes dela cai fora do intervalo e desaparece sem erro. Era o
    mesmo defeito de fronteira do caso 1, no outro extremo do bloco.
    """
    partes: list[str] = []
    indentacao_conteudo: int | None = None
    ultima = indicador
    while True:
        item = linhas.olhar()
        if item is None:
            break
        numero, indentacao, conteudo, cortou = item
        if indentacao <= indentacao_pai:
            break
        if indentacao_conteudo is None:
            indentacao_conteudo = indentacao
        elif indentacao != indentacao_conteudo:
            raise YamlSubsetError(
                f"linha {numero}: indentacao irregular dentro do escalar dobrado "
                f"(esperava {indentacao_conteudo}, lido {indentacao}); "
                "este leitor so dobra linhas todas ao mesmo nivel"
            )
        if cortou:
            raise YamlSubsetError(
                f"linha {numero}: `#` dentro de um escalar dobrado e conteudo em YAML, "
                "e este leitor corta-o como comentario; use aspas ou tire o `#`"
            )
        linhas.seguinte()
        partes.append(conteudo)
        ultima = numero
    if not partes:
        raise YamlSubsetError(f"{onde}: escalar dobrado sem conteudo")

    seguinte = linhas.olhar()
    fim_do_bloco = seguinte[0] if seguinte is not None else max(linhas.descartadas, default=0) + 1
    for numero in sorted(linhas.descartadas):
        if not indicador < numero < fim_do_bloco:
            continue
        indentacao = linhas.descartadas[numero]
        if numero < ultima:
            raise YamlSubsetError(
                f"linha {numero}: linha vazia ou comentada dentro de um escalar dobrado; "
                "em YAML e conteudo (quebra de paragrafo ou texto) e aqui desapareceria"
            )
        if indentacao is not None and indentacao >= (indentacao_conteudo or 0):
            raise YamlSubsetError(
                f"linha {numero}: `#` ao nivel do conteudo de um escalar dobrado e "
                "conteudo em YAML, e este leitor descarta-o; use aspas ou desindente"
            )
    return " ".join(partes)


def _valor_de_bloco(
    linhas: _Linhas, resto: str, indentacao_pai: int, onde: str, numero: int
):
    """O valor de uma chave cujo resto da linha e um indicador de bloco."""
    if resto != _DOBRADO:
        raise YamlSubsetError(
            f"{onde}: escalar em bloco {resto!r} nao suportado; so `>-`. "
            "O `>` e o `>+` guardam a linha final, que este leitor nao preserva, "
            "e o `|` preserva as quebras de linha"
        )
    return _ler_dobrado(linhas, indentacao_pai, onde, numero)


def _ler_mapa(linhas: _Linhas, indentacao: int) -> dict:
    mapa: dict = {}
    while True:
        item = linhas.olhar()
        if item is None:
            break
        numero, indentacao_actual, conteudo, _ = item
        if indentacao_actual < indentacao:
            break
        if indentacao_actual > indentacao:
            raise YamlSubsetError(f"linha {numero}: indentacao inesperada")
        if conteudo.startswith("- ") or conteudo == "-":
            break

        linhas.seguinte()
        onde = f"linha {numero}"
        correspondencia = _CHAVE.match(conteudo)
        if not correspondencia:
            raise YamlSubsetError(f"{onde}: esperava 'chave: valor' (lido {conteudo!r})")

        chave = _nome_da_chave(correspondencia.group("chave"))
        if chave in mapa:
            raise YamlSubsetError(f"{onde}: chave repetida {chave!r}")
        resto = correspondencia.group("resto").strip()

        if resto in _BLOCO:
            mapa[chave] = _valor_de_bloco(linhas, resto, indentacao, onde, numero)
        elif resto == "":
            mapa[chave] = _ler_bloco(linhas, indentacao, onde)
        else:
            mapa[chave] = _escalar(resto, onde)
    return mapa


def _ler_lista(linhas: _Linhas, indentacao: int) -> list:
    lista: list = []
    while True:
        item = linhas.olhar()
        if item is None:
            break
        numero, indentacao_actual, conteudo, _ = item
        if indentacao_actual < indentacao or not conteudo.startswith("- "):
            break
        if indentacao_actual > indentacao:
            raise YamlSubsetError(f"linha {numero}: indentacao de item inconsistente")

        linhas.seguinte()
        onde = f"linha {numero}"
        corpo = conteudo[2:].strip()
        if corpo.startswith("- ") or corpo == "-":
            raise YamlSubsetError(f"{onde}: lista aninhada numa lista nao suportada")
        correspondencia = _CHAVE.match(corpo)
        if correspondencia:
            # Item que e um mapa: a primeira chave esta na propria linha do `-`,
            # e as seguintes vem indentadas ao nivel dessa chave.
            indentacao_chave = indentacao + 2
            chave = _nome_da_chave(correspondencia.group("chave"))
            resto = correspondencia.group("resto").strip()
            if resto in _BLOCO:
                # `indentacao_chave`, e nao `indentacao_chave - 1`: o caso 1 do
                # KAM-136. Com o `- 1`, a dobra consumia as linhas ao nivel das
                # chaves seguintes do mesmo item, e engolia-as.
                primeiro = {
                    chave: _valor_de_bloco(linhas, resto, indentacao_chave, onde, numero)
                }
            elif resto == "":
                primeiro = {chave: _ler_bloco(linhas, indentacao_chave, onde)}
            else:
                primeiro = {chave: _escalar(resto, onde)}
            seguintes = _ler_mapa(linhas, indentacao_chave)
            repetidas = set(primeiro) & set(seguintes)
            if repetidas:
                raise YamlSubsetError(f"{onde}: chave repetida no item: {sorted(repetidas)}")
            primeiro.update(seguintes)
            lista.append(primeiro)
        else:
            lista.append(_escalar(corpo, onde))
    return lista


def _ler_bloco(linhas: _Linhas, indentacao_pai: int, onde: str):
    """Le o bloco indentado que vem depois de uma `chave:` sem valor."""
    item = linhas.olhar()
    if item is None:
        raise YamlSubsetError(f"{onde}: chave sem valor nem bloco")
    _, indentacao, conteudo, _ = item
    if indentacao <= indentacao_pai:
        raise YamlSubsetError(f"{onde}: chave sem valor nem bloco")
    if conteudo.startswith("- "):
        return _ler_lista(linhas, indentacao)
    return _ler_mapa(linhas, indentacao)


def load(texto: str) -> dict:
    """Le o subconjunto e devolve um dicionario de topo."""
    linhas = _Linhas(texto)
    if linhas.olhar() is None:
        return {}
    numero, indentacao, _, _ = linhas.olhar()
    if indentacao != 0:
        raise YamlSubsetError(f"linha {numero}: o documento tem de comecar sem indentacao")
    documento = _ler_mapa(linhas, 0)
    sobra = linhas.olhar()
    if sobra is not None:
        raise YamlSubsetError(f"linha {sobra[0]}: conteudo nao consumido ({sobra[2]!r})")
    return documento


def load_file(caminho: Path) -> dict:
    """Le um ficheiro, com o nome do ficheiro na mensagem de erro."""
    try:
        texto = caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as excepcao:
        # `UnicodeDecodeError` nao e `OSError`: sem este ramo, um ficheiro que
        # nao fosse UTF-8 saia do modulo como excepcao nao tratada, e o gate
        # morria com *traceback* e codigo 1 em vez de erro de configuracao (2).
        raise YamlSubsetError(f"{caminho}: {excepcao}") from excepcao
    try:
        return load(texto)
    except YamlSubsetError as excepcao:
        raise YamlSubsetError(f"{caminho}: {excepcao}") from excepcao
