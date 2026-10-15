"""Leitor de um subconjunto estrito de YAML, suficiente para `ops/secrets-inventory.yaml`.

Nao e um parser de YAML. Aceita exactamente a forma que o inventario usa e
**recusa tudo o resto**, em voz alta:

    chave: escalar
    chave: "texto com : dois pontos"
    chave: null
    chave: [a, b, c]
    chave: []
    lista:
      - chave: escalar
        outra: [a, b]

Sem aninhamento alem deste, sem ancoras, sem documentos multiplos, sem escalares
de bloco (`|`, `>`), sem listas de listas.

## Porque e que isto existe, outra vez

`tools/kamba_yaml.py` ja le um subconjunto de YAML, e o seu docstring diz
explicitamente que tem de ser inutil para outra coisa qualquer, para que ninguem
o reutilize. Cumpre-se: ele recusa `[a, b]` (estilo de fluxo) e o inventario
precisa dele para `ambientes` e `consumidores`. Acrescentar o estilo de fluxo
ao `kamba_yaml` tornaria-o util de mais — e ele corre no `pre-commit`, onde um
parser mais permissivo e um risco que nao compensa.

A razao de nenhum dos dois usar PyYAML e a do KAM-001: `libs/py-core` e as
ferramentas que correm nos *hooks* nao tem dependencias, para que funcionem num
clone antes de qualquer instalacao.

## O que recusa, com erro

**Esta lista e a garantia, e tem de ser verdadeira**: cada linha tem um teste em
`tools/secrets_inventory/tests/test_yamlsubset.py`, sobre o corpus de
`tools/secrets_inventory/tests/corpus_yamlsubset.py`. Antes do **KAM-148** a
lista era curta e falsa — onze construcoes liam mal **sem o dizer**, e o que
este leitor le e o inventario de segredos: uma chave engolida e um segredo sem
rotacao declarada. As regras abaixo sao as do `kamba_yaml` depois do KAM-136,
pela mesma razao e com a mesma escolha: **recusar o que nao se entende**.

Estrutura:

* ancoras e *aliases* (`&`, `*`), *merge keys* (`<<`), *tags* (`!`), directivas
  (`%`) e os indicadores reservados (`@`, `` ` ``) — em posicao de valor **e**
  de chave;
* a chave explicita (`? a`), e o `?` sozinho como valor;
* um escalar plano que **comece** por um indicador de fluxo (`]`, `}`, `,`);
* um `#` dentro do **nome** de uma chave (`a#b: 1`) — e a unica forma de chave
  que o leitor anterior lia e este recusa, e esta aqui por isso: o corte de
  comentarios faz-se linha a linha, antes de se saber se o `#` e comentario.
  Tudo o mais que seja nome de chave continua a ler-se, incluindo acentos
  (`rotação_dias:`), espacos, barras e o digito inicial;
* mapas em estilo de fluxo (`{a: 1}`) e escalares de bloco (`|`, `>`);
* **chaves repetidas no mapa de topo** — a segunda calava a primeira em
  silencio, e no inventario isso e uma entrada que desaparece;
* chaves repetidas no mesmo item de lista, listas de listas, aninhamento alem
  de «mapa de topo → lista de mapas», e itens de lista que nao sejam
  `chave: valor`;
* documentos multiplos (`---`) e fim de documento (`...`);
* tabulacoes (em qualquer posicao da linha) e indentacao inconsistente;
* lista de fluxo sem fecho, com item vazio (`[a,, b]`) ou aninhada
  (`[a, [b]]`), e um `[` ou `]` dentro de um item **nao citado**. Entre aspas
  sao texto: `["x]y"]` le-se;
* caracteres de controlo C0 (excepto TAB), `DEL`, e as quebras de linha que o
  YAML 1.1 reconhece e o 1.2 nao (`NEL`, `U+2028`, `U+2029`). O `CR` sozinho
  **e** quebra de linha, como no YAML 1.2, e o BOM no inicio e permitido.

Escalares:

* `chave:valor` sem espaco depois dos dois pontos: o YAML exige `:` seguido de
  espaco ou fim de linha, e isto era lido como um mapa. Em posicao de item de
  lista, `- https://exemplo.ao/p` dava `{"https": "//exemplo.ao/p"}`;
* aspa aberta e nao fechada, e conteudo depois da aspa de fecho (`"a" extra`,
  `"a" "b"`, `'o ''valor'' certo'`) — nao se interpretam escapes nem aspas
  duplicadas;
* `#` depois de uma aspa aberta e nao fechada: nao se sabe se e comentario ou
  conteudo, e por isso recusa-se em vez de adivinhar;
* escalar nao citado que contenha `: ` ou acabe em `:`;
* escalares que **parecem numero e nao sao inteiro decimal**: `1.5`, `1e3`,
  `0x1f`, `1_000`, `.inf`, `.nan`, `017` e `0644` (octal no YAML 1.1, decimal no
  1.2) e `1:30` (sexagesimal no YAML 1.1). O que este ficheiro descreve sao
  periodos de rotacao em dias; `rotacao_dias: 0180` lido como 180 ou como 120
  nao e a mesma politica;
* escalares **ambiguos** como booleano ou nulo: `True`, `FALSE`, `yes`, `no`,
  `on`, `off`, `NULL` — e `None`, que nenhuma versao do YAML resolve mas que
  quem o escreve espera que seja nulo. So `true`, `false`, `null` e `~` passam.
  **Isto importa aqui mais do que em qualquer outro ficheiro:** `obrigatorio:
  FALSE` dava a cadeia `"FALSE"`, que e **verdadeira** em Python.

**Nao interpreta escapes.** O conteudo entre aspas e literal, como no
`kamba_yaml`: `"a\\nb"` da a cadeia de **quatro** caracteres (`a`, `\\`, `n`,
`b`), nao uma quebra de linha.

## Uma chave de topo sem valor e **nulo**

`a:` sozinho da `None`, e nao `[]`. O leitor assumia sempre que uma chave sem
valor abria uma lista de mapas, mesmo quando nenhum item vinha: `{"a": []}`
onde o YAML diz nulo, e sem o dizer. A chave so passa a lista quando o
primeiro item chega.

## Comentarios de fim de linha

O que o *docstring* chamava «limite conhecido» — um valor sem aspas que contenha
` #` perde o resto da linha — **e o que o YAML faz**: num escalar plano, ` #`
abre um comentario. Deixou de estar escrito como limite e passou a estar
provado por teste, nos dois sentidos (`"tem # dentro"` guarda o cardinal;
`tem # dentro` perde-o). O caso que faltava — uma aspa aberta e nao fechada
antes de um `#`, onde nao se sabe se o cardinal e comentario ou conteudo —
**recusa-se**.
"""

from __future__ import annotations

import re


class YamlSubsetError(ValueError):
    """O ficheiro usa YAML fora do subconjunto aceite."""


Escalar = str | int | bool | None

#: O `(?=[ \t]|$)` e o caso 2 do KAM-136, vivo neste leitor ate ao KAM-148: sem
#: ele, `chave:valor` virava um mapa e `- https://x` virava `{"https": "//x"}`.
#:
#: A classe do primeiro caractere e **negativa**, como a do `yamlreg`, e nao a
#: lista `[A-Za-z_]` que uma primeira versao deste ticket poe aqui: essa
#: recusava `razao:` com acento, `a b:`, `a/b:` e `2fa:`, que o leitor anterior
#: lia **correctamente** — num repositorio inteiramente em portugues, uma chave
#: acentuada e a forma mais plausivel de todas. O que fica de fora sao os
#: indicadores do YAML (§7.3.3) e o `#`, que o corte de comentarios nao sabe
#: distinguir de um comentario.
_CHAVE = re.compile(
    r"^(?P<chave>\"[^\"]+\"|'[^']+'|[^\s\"'{}\[\],:#&*!|>%@`?][^:#]*?)\s*:(?=[ \t]|$)(?P<resto>.*)$"
)

_PROIBIDOS = {
    "&": "ancora",
    "*": "alias",
    "!": "tag",
    "%": "directiva",
    "@": "indicador reservado",
    "`": "indicador reservado",
    "|": "escalar de bloco",
    ">": "escalar de bloco",
    "{": "mapa em estilo de fluxo",
    # Em YAML 1.2 um escalar plano **nao pode comecar** por um indicador de
    # fluxo. `a: ]` dava a cadeia `']'`, em silencio.
    "]": "indicador de fluxo",
    "}": "indicador de fluxo",
    ",": "indicador de fluxo",
}

#: Caracteres que o YAML 1.2 §5.1 nao admite num documento (C0 sem TAB, e DEL).
_CONTROLO = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Quebras de linha do YAML 1.1 que o 1.2 retirou.
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
#: versao do YAML que ninguem declarou.
_AMBIGUOS = frozenset(
    {
        "True", "TRUE", "False", "FALSE",
        "yes", "Yes", "YES", "no", "No", "NO",
        "on", "On", "ON", "off", "Off", "OFF",
        "Null", "NULL", "None",
    }
)


def _nome_da_chave(bruta: str, onde: str) -> str:
    """O nome de uma chave, sem **um** par de aspas, e sem resolucao de tipo."""
    bruta = bruta.strip()
    if bruta == "<<":
        # `<<: valor` e uma *merge key*. Com a classe de chave larga, era lida
        # como uma chave chamada `<<`: um mapa com uma chave a mais e sem a
        # fusao que o ficheiro pedia.
        raise YamlSubsetError(f"{onde}: merge key nao suportada ('<<')")
    if len(bruta) >= 2 and bruta[0] == bruta[-1] and bruta[0] in "\"'":
        return bruta[1:-1]
    return bruta


def _escalar(bruto: str, onde: str) -> Escalar:
    """Converte um escalar: texto, inteiro decimal, booleano ou `null`."""
    texto = bruto.strip()
    if texto == "":
        raise YamlSubsetError(f"{onde}: valor vazio (use \"\" ou null)")

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

    if texto.startswith("<<"):
        raise YamlSubsetError(f"{onde}: merge key nao suportada ('<<')")
    if texto[0] in _PROIBIDOS:
        raise YamlSubsetError(f"{onde}: {_PROIBIDOS[texto[0]]} nao suportado ({texto[0]!r})")
    if texto == "?" or texto.startswith("? "):
        # `?` seguido de espaco ou fim de linha e o indicador de chave
        # explicita, nao um escalar. `a: ?` dava a cadeia `'?'`.
        raise YamlSubsetError(f"{onde}: chave explicita ('?') nao suportada")

    if ": " in texto or texto.endswith(":"):
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


def _partes_do_fluxo(interior: str, onde: str) -> list[str]:
    """Parte `a, "b, c", d` nas virgulas **que estao fora de aspas**.

    Antes partia-se por `split(",")`: `["x, y", z]` dava tres itens em vez de
    dois, e os dois primeiros com uma aspa pendurada.
    """
    partes: list[str] = []
    actual = ""
    aspa = ""
    for caractere in interior:
        if aspa:
            actual += caractere
            if caractere == aspa:
                aspa = ""
        elif caractere in "\"'":
            aspa = caractere
            actual += caractere
        elif caractere == ",":
            partes.append(actual)
            actual = ""
        else:
            actual += caractere
    if aspa:
        raise YamlSubsetError(f"{onde}: aspa {aspa} aberta e nao fechada na lista de fluxo")
    partes.append(actual)
    return partes


def _lista_de_fluxo(bruto: str, onde: str) -> list[Escalar]:
    """Converte `[a, b, c]` e `[]`.

    O aninhamento verifica-se **depois** de partir pelas virgulas que estao fora
    de aspas: `["x]y"]` nao e uma lista de listas, e a verificacao antiga —
    `"]" in interior` — recusava-a com essa mensagem. O irmao deste caso (o
    `split(",")` que nao respeitava aspas) ja estava corrigido; este nao.
    """
    interior = bruto.strip()[1:-1].strip()
    if interior == "":
        return []
    partes = _partes_do_fluxo(interior, onde)
    for parte in partes:
        if parte.strip()[:1] == "[":
            raise YamlSubsetError(f"{onde}: lista de listas nao suportada")
        if parte.strip()[:1] not in ("\"", "'") and ("[" in parte or "]" in parte):
            raise YamlSubsetError(
                f"{onde}: `[` ou `]` dentro de um item nao citado ({parte.strip()!r}); use aspas"
            )
    return [_escalar(parte, onde) for parte in partes]


def _valor(bruto: str, onde: str) -> Escalar | list[Escalar]:
    texto = bruto.strip()
    if texto.startswith("["):
        if not texto.endswith("]"):
            raise YamlSubsetError(f"{onde}: lista de fluxo sem fecho")
        return _lista_de_fluxo(texto, onde)
    return _escalar(texto, onde)


def _inicio_do_escalar(linha: str) -> int:
    """Onde comeca o escalar desta linha.

    Neste subconjunto um escalar comeca depois da indentacao, depois do `- ` de
    um item de lista, e depois do `:` de uma chave. Em mais nenhum sitio uma
    aspa abre uma cadeia citada.
    """
    posicao = len(linha) - len(linha.lstrip(" \t"))
    if linha.startswith("- ", posicao):
        posicao += 2
        while posicao < len(linha) and linha[posicao] == " ":
            posicao += 1
    inicio_da_chave = posicao
    correspondencia = _CHAVE.match(linha[posicao:])
    if correspondencia:
        posicao += correspondencia.end("chave")
        while posicao < len(linha) and linha[posicao] in " \t":
            posicao += 1
        posicao += 1  # o `:`
        while posicao < len(linha) and linha[posicao] in " \t":
            posicao += 1
    return posicao, inicio_da_chave


def _sem_comentario(linha: str, onde: str) -> str:
    """Remove um comentario de fim de linha, respeitando aspas.

    `razao: "usa # para comentar"` nao perde o `#`; `razao: usa # isto` perde,
    porque e o que o YAML faz num escalar plano.
    """
    inicio, inicio_da_chave = _inicio_do_escalar(linha)
    # Dentro de uma lista de fluxo uma aspa pode abrir um atomo em qualquer
    # posicao (`[a, "b # c"]`), e nao so no inicio do escalar.
    em_fluxo = linha[inicio : inicio + 1] == "["
    # Uma **chave** citada tambem abre uma cadeia: sem isto, `"a #b": c` perdia
    # o resto da linha como comentario.
    aberturas = {inicio, inicio_da_chave}
    fora_de_aspas = True
    aspa = ""
    cardinal_ambiguo = -1
    for indice, caractere in enumerate(linha):
        inicio_de_comentario = caractere == "#" and (indice == 0 or linha[indice - 1] in " \t")
        if fora_de_aspas and caractere in "\"'" and (indice in aberturas or (em_fluxo and indice > inicio)):
            fora_de_aspas, aspa = False, caractere
        elif not fora_de_aspas and caractere == aspa:
            fora_de_aspas = True
        elif fora_de_aspas and inicio_de_comentario:
            return linha[:indice]
        elif not fora_de_aspas and inicio_de_comentario and cardinal_ambiguo < 0:
            cardinal_ambiguo = indice
    if not fora_de_aspas and cardinal_ambiguo >= 0:
        raise YamlSubsetError(
            f"{onde}: aspa {aspa} aberta e nao fechada antes de um `#`; "
            "nao se sabe se o `#` e comentario ou conteudo"
        )
    return linha


def load(texto: str) -> dict[str, object]:
    """Le o subconjunto e devolve um dicionario de topo."""
    raiz: dict[str, object] = {}
    lista_actual: list[dict[str, object]] | None = None
    item_actual: dict[str, object] | None = None
    indent_item: int | None = None
    #: A chave que abriu uma lista e ainda nao recebeu nenhum item: fica a
    #: valer `None` na raiz, e so passa a lista quando o primeiro item chega.
    chave_da_lista: str | None = None

    # O BOM e permitido no inicio do *stream* (YAML 1.2 §5.2). Sem isto, a
    # primeira chave ficava com o BOM dentro do nome, em silencio.
    texto = texto.lstrip("\ufeff")
    for ambigua, nome in _QUEBRAS_AMBIGUAS.items():
        if ambigua in texto:
            numero = texto[: texto.index(ambigua)].count("\n") + 1
            raise YamlSubsetError(
                f"linha {numero}: {nome} e quebra de linha em YAML 1.1 e nao em 1.2; "
                "nao se adivinha a versao — tire-o ou use uma quebra de linha"
            )
    # `\r` sozinho **e** quebra de linha (YAML 1.2 §5.4).
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")

    for numero, linha_bruta in enumerate(texto.split("\n"), start=1):
        onde = f"linha {numero}"
        achado_controlo = _CONTROLO.search(linha_bruta)
        if achado_controlo:
            raise YamlSubsetError(
                f"{onde}: caractere de controlo {achado_controlo.group()!r} "
                "nao e admitido num documento YAML"
            )
        if "\t" in linha_bruta:
            raise YamlSubsetError(f"{onde}: tabulacao")
        linha = _sem_comentario(linha_bruta, onde)
        if linha.strip() == "":
            continue

        indent = len(linha) - len(linha.lstrip(" "))
        corpo = linha.strip()
        if corpo in ("---", "..."):
            raise YamlSubsetError(f"{onde}: documentos multiplos nao suportados")

        if corpo.startswith("- "):
            if lista_actual is None:
                raise YamlSubsetError(f"{onde}: item de lista sem chave de lista acima")
            if indent_item is None:
                indent_item = indent
            elif indent != indent_item:
                raise YamlSubsetError(f"{onde}: indentacao de item inconsistente")
            corpo = corpo[2:].strip()
            achado = _CHAVE.match(corpo)
            if achado is None or achado.group("resto").strip() == "":
                raise YamlSubsetError(f"{onde}: item de lista tem de ser 'chave: valor'")
            item_actual = {}
            # A chave so passa a lista quando chega o **primeiro** item: ver o
            # ramo da chave sem valor, em baixo.
            if chave_da_lista is not None:
                raiz[chave_da_lista] = lista_actual
                chave_da_lista = None
            lista_actual.append(item_actual)
            item_actual[_nome_da_chave(achado.group("chave"), onde)] = _valor(achado.group("resto"), onde)
            continue

        achado = _CHAVE.match(corpo)
        if achado is None:
            if corpo[:1] in _PROIBIDOS:
                # Sem isto, `%YAML 1.2` e `@a: 1` caiam na mensagem generica —
                # recusados, mas pela regra errada.
                raise YamlSubsetError(
                    f"{onde}: {_PROIBIDOS[corpo[0]]} nao suportado ({corpo[0]!r})"
                )
            raise YamlSubsetError(f"{onde}: esperava 'chave: valor' (lido {corpo!r})")
        chave = _nome_da_chave(achado.group("chave"), onde)
        valor = achado.group("resto")

        if valor.strip() == "":
            # Chave sem valor na propria linha: **nulo**, ate chegar o primeiro
            # item de lista. Assumir sempre a lista dava `{"a": []}` para `a:`,
            # quando o YAML diz nulo — e era uma leitura ma em silencio.
            if indent != 0:
                raise YamlSubsetError(f"{onde}: lista aninhada nao suportada")
            if chave in raiz:
                raise YamlSubsetError(f"{onde}: chave repetida no mapa de topo ({chave})")
            lista_actual = []
            item_actual = None
            indent_item = None
            chave_da_lista = chave
            raiz[chave] = None
            continue

        if indent == 0:
            if chave in raiz:
                raise YamlSubsetError(f"{onde}: chave repetida no mapa de topo ({chave})")
            raiz[chave] = _valor(valor, onde)
            lista_actual = None
            item_actual = None
            indent_item = None
            chave_da_lista = None
        else:
            if item_actual is None:
                raise YamlSubsetError(f"{onde}: chave indentada fora de um item de lista")
            if indent_item is not None and indent != indent_item + 2:
                raise YamlSubsetError(f"{onde}: indentacao de chave inconsistente")
            if chave in item_actual:
                raise YamlSubsetError(f"{onde}: chave repetida no mesmo item ({chave})")
            item_actual[chave] = _valor(valor, onde)

    return raiz
