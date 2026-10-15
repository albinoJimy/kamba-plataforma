"""Leitor de YAML para `registry/*.yaml`, com estilo de fluxo.

O `tools/kamba_yaml.py` recusa `{a: b}` e `[a, b]` de proposito, e os ficheiros
do AgentRegistry usam-nos (`docs/tecnica/02` §5.1: `subscriptions:` com
`- { tipo: payment.confirmed, versao: 1 }`). Alargar o `kamba_yaml` torna-lo-ia
mais permissivo para todas as ferramentas que o usam, incluindo as que correm no
*pre-commit*; este leitor fica aqui, ao lado da unica superficie que precisa
dele.

Aceita: mapas e listas em bloco, mapas e listas de fluxo **numa linha**,
escalares simples e entre aspas, comentarios. Um ficheiro que este leitor nao
percebe **falha** o gate: nao passa por nao ter sido lido.

## O que recusa, com erro

**Esta lista e a garantia, e tem de ser verdadeira**: cada linha tem um teste em
`tools/canon_lint/tests/test_yamlreg.py`, sobre o corpus de
`tools/canon_lint/tests/corpus_yamlreg.py`. Antes do **KAM-148** a lista era
curta e falsa — dez construcoes liam mal **sem o dizer**, e num leitor cuja
premissa e esta o silencio e o modo de falha mais caro que existe, porque nao ha
sintoma. As regras abaixo sao as do `kamba_yaml` depois do KAM-136, pela mesma
razao e com a mesma escolha: **recusar o que nao se entende**.

Estrutura:

* ancoras e *aliases* (`&`, `*`) e *merge keys* (`<<`), em posicao de valor
  **e** de chave;
* *tags* (`!!str`), directivas (`%YAML`) e os indicadores reservados
  (`@`, `` ` ``), em posicao de valor **e** de chave: `@a: 1`, `` `a: 1 `` e
  `%YAML: 1` liam-se como chaves chamadas `@a`, `` `a `` e `%YAML`, e nenhuma
  e YAML valido (§7.3.3, `ns-plain-first` exclui `c-indicator`);
* a chave explicita (`? a`), e o `?` sozinho como valor;
* um escalar plano que **comece** por um indicador de fluxo (`]`, `}`, `,`):
  `a: ]` dava a cadeia `']'`. Dentro de um escalar eles sao texto
  (`a: b,c` le-se);
* um `#` dentro do **nome** de uma chave (`a#b: 1`): o corte de comentarios
  faz-se linha a linha, antes de se saber se o `#` e comentario;
* escalares em bloco (`|`, `|-`, `|+`, `>`, `>-`, `>+`) — este leitor nao os
  interpreta, e o `>-` do `kamba_yaml` nao e necessario aqui;
* documentos multiplos (`---`) e fim de documento (`...`);
* tabulacoes na indentacao e indentacao inconsistente;
* chaves repetidas no mesmo mapa, no mesmo item de lista e no mesmo mapa de
  fluxo;
* listas aninhadas **em bloco** (`- - a`): em fluxo, `[[1, 2]]` e
  `{a: {b: 1}}` leem-se, e por isso a frase antiga («estrutura que este
  leitor nao tem») era falsa;
* **mais de 50 niveis de aninhamento**, em bloco ou em fluxo. O leitor e
  recursivo: sem este limite, 400 linhas de YAML de bloco perfeitamente
  comum davam um `RecursionError` — que nao e uma recusa, e sim o *gate*
  morto com *traceback* e codigo 1. O limite conta **niveis**, nao
  chamadas: uma lista de 60 itens e aninhamento 1;
* fluxo partido por varias linhas, fluxo por fechar (`[a`, `{a: 1`), item vazio
  (`[a,, b]`), chave vazia (`{: 1}`), par solto numa sequencia (`[a: 1]`) e
  texto a mais depois do fluxo;
* caracteres de controlo C0 (excepto TAB), `DEL`, e as quebras de linha que o
  YAML 1.1 reconhece e o 1.2 nao (`NEL`, `U+2028`, `U+2029`). O `CR` sozinho
  **e** quebra de linha, como no YAML 1.2, e o BOM no inicio e permitido.

Escalares:

* aspa aberta e nao fechada, e conteudo depois da aspa de fecho (`"a" extra`,
  `"a" "b"`, `'o ''valor'' certo'`) — este leitor nao interpreta escapes nem
  aspas duplicadas;
* `#` depois de uma aspa aberta e nao fechada: nao se sabe se e comentario ou
  conteudo, e por isso recusa-se em vez de adivinhar;
* escalar nao citado que contenha `: ` ou acabe em `:` — o YAML tambem o recusa,
  e aqui era lido como texto;
* escalares que **parecem numero e nao sao inteiro decimal**: `1.5`, `1e3`,
  `0x1f`, `1_000`, `.inf`, `.nan`, `017` e `0644` (octal no YAML 1.1, decimal no
  1.2) e `1:30` (sexagesimal no YAML 1.1). Um manifesto que precise de um
  decimal — um `temperature: 0.2` em `models` — falha aqui, **em voz alta**, e a
  resposta e aspas ou uma regra nova com teste; nao e ler `0644` como 644 ou
  como 420 sem ninguem saber qual;
* escalares **ambiguos** como booleano ou nulo: `True`, `FALSE`, `yes`, `no`,
  `on`, `off`, `NULL` — e `None`, que nenhuma versao do YAML resolve mas que
  quem o escreve espera que seja nulo. So `true`, `false`, `null` e `~` passam.

## O que le, e que antes lia mal

Tres casos em que a correccao foi **interpretar**, e nao recusar, porque o
leitor ja tinha a maquina para os ler e o corpus precisa deles:

1. **Nomes de chave nao se resolvem como valores.** A chave passava pelo mesmo
   conversor do valor: `"007": x` dava a chave `7` e `true: x` dava `True`.
   Agora tira-se **um** par de aspas e mais nada.
2. **Uma aspa a meio de um texto plano nao abre uma cadeia citada.** Em
   `id: nao e' assim # nota` o apostrofo e texto, e o `# nota` e comentario;
   antes a aspa «abria» e o comentario entrava no valor.
3. **Algarismos nao-ASCII nao sao inteiros.** O `int()` aceita `١٢٣`; o YAML
   resolve inteiros so com `[0-9]`, e agora tambem este leitor.

Duas construcoes que este leitor le **e** o `kamba_yaml` recusa, e que ficam
como estao porque as le correctamente: a lista ao nivel da chave que a introduz
(`a:` seguido de `- x` sem indentar) e o documento de topo que e uma lista.

E duas que passaram a ler-se com a revisao adversarial deste ticket, por
serem YAML valido que o leitor anterior lia e uma primeira versao recusava:
uma **chave citada com um ` #` dentro** (`"a #b": c`) e um **item de lista
cuja chave esta citada** (`- "a": 1`, que e um mapa; `- "a: b"` continua a
ser cadeia, porque o `:` tem de vir depois da aspa de fecho).
"""

from __future__ import annotations

import re


class YamlIlegivel(ValueError):
    """O ficheiro usa YAML que este leitor nao aceita."""


#: O primeiro caractere do **nome de uma chave** nao citada exclui os
#: indicadores do YAML (§7.3.3, `ns-plain-first` exclui `c-indicator`). Sem o
#: `%@`` ?`, as linhas `@a: 1`, `` `a: 1 ``, `%YAML: 1` e `? a: 1` liam-se como
#: chaves chamadas `@a`, `` `a ``, `%YAML` e `? a` — em silencio, e nenhuma
#: delas e um documento YAML valido.
_CHAVE = re.compile(
    r"""^(?P<chave>"[^"]*"|'[^']*'|[^\s"'{}\[\],:#&*!|>%@`?][^:#]*?)\s*:(?:\s+(?P<resto>.*))?$"""
)

#: O primeiro caractere de um escalar que este leitor nao interpreta.
_PROIBIDOS = {
    "&": "ancora",
    "*": "alias",
    "!": "tag",
    "%": "directiva",
    "@": "indicador reservado",
    "`": "indicador reservado",
    "|": "escalar de bloco",
    ">": "escalar de bloco",
    # Em YAML 1.2 um escalar plano **nao pode comecar** por um indicador de
    # fluxo. `a: ]` dava a cadeia `']'`, em silencio.
    "]": "indicador de fluxo",
    "}": "indicador de fluxo",
    ",": "indicador de fluxo",
}

#: Quantos niveis de aninhamento este leitor desce antes de desistir. Os
#: manifestos de `docs/tecnica/02` §5.1 usam tres. O leitor e recursivo, e sem
#: este limite 400 linhas de YAML de bloco perfeitamente comum davam um
#: `RecursionError` — que nao e uma recusa: e o *gate* morto com *traceback* e
#: codigo 1, o modo de falha que o KAM-136 fechou no `kamba_yaml`.
_PROFUNDIDADE_MAXIMA = 50

#: Caracteres que o YAML 1.2 §5.1 nao admite num documento (C0 sem TAB, e DEL).
_CONTROLO = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Quebras de linha do YAML 1.1 que o 1.2 retirou. Lidas como texto, partiam um
#: documento em sitios diferentes conforme a versao; recusam-se.
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
        "True", "TRUE", "False", "FALSE",
        "yes", "Yes", "YES", "no", "No", "NO",
        "on", "On", "ON", "off", "Off", "OFF",
        "Null", "NULL", "None",
    }
)


def _nome_da_chave(bruta: str) -> str:
    """O nome de uma chave, sem **um** par de aspas, e sem resolucao de tipo.

    Uma chave nao e um valor: passa-la pelo `_escalar` dava a chave `7` para
    `"007"` e a chave `True` para `true`.
    """
    bruta = bruta.strip()
    if len(bruta) >= 2 and bruta[0] == bruta[-1] and bruta[0] in "\"'":
        return bruta[1:-1]
    return bruta


def _inicio_do_escalar(linha: str) -> int:
    """Onde comeca o escalar desta linha.

    Neste subconjunto um escalar comeca depois da indentacao, depois dos `- `
    dos itens de lista, e depois do `:` de uma chave. Em mais nenhum sitio uma
    aspa abre uma cadeia citada: em `id: nao e' assim # nota` o apostrofo e
    texto, e trata-lo como aspa aberta guardava o `# nota` dentro do valor.
    """
    posicao = len(linha) - len(linha.lstrip(" \t"))
    while linha.startswith("- ", posicao):
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
    """Remove um comentario de fim de linha, respeitando aspas."""
    inicio, inicio_da_chave = _inicio_do_escalar(linha)
    # Dentro de uma expressao de fluxo uma aspa pode abrir um atomo em muitas
    # posicoes (`{ chat: "a # b", tom: 'c' }`), e nao so no inicio do escalar.
    em_fluxo = linha[inicio : inicio + 1] in ("{", "[")
    # Uma **chave** citada tambem abre uma cadeia: sem isto, `"a #b": c` perdia
    # o ` #b": c` como comentario e a linha ficava em `"a`.
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
        raise YamlIlegivel(
            f"{onde}: aspa {aspa} aberta e nao fechada antes de um `#`; "
            "nao se sabe se o `#` e comentario ou conteudo"
        )
    return linha


def _escalar(texto: str, onde: str):
    """Converte um escalar: nulo, booleano, inteiro decimal, ou texto."""
    texto = texto.strip()
    if texto == "":
        raise YamlIlegivel(f"{onde}: valor vazio (use \"\" para texto vazio, ou null)")

    if texto[0] in "\"'":
        aspa = texto[0]
        fim = texto.find(aspa, 1)
        if fim == -1:
            raise YamlIlegivel(f"{onde}: aspa {aspa} aberta e nao fechada ({texto!r})")
        if fim != len(texto) - 1:
            resto = texto[fim + 1 :].strip()
            escapada = texto[fim - 1] == "\\" or resto[:1] == aspa
            pista = (
                "; este leitor nao interpreta escapes nem aspas duplicadas "
                f"({aspa}{aspa} ou \\{aspa}): use a outra aspa"
                if escapada
                else "; este leitor nao junta partes citadas"
            )
            raise YamlIlegivel(f"{onde}: conteudo depois da aspa de fecho ({resto!r}){pista}")
        return texto[1:fim]

    if texto.startswith("<<"):
        raise YamlIlegivel(f"{onde}: merge key nao suportada ('<<')")
    if texto[0] in _PROIBIDOS:
        raise YamlIlegivel(f"{onde}: {_PROIBIDOS[texto[0]]} nao suportado ({texto[0]!r})")
    if texto == "?" or texto.startswith("? "):
        # `?` seguido de espaco ou fim de linha e o indicador de chave
        # explicita, nao um escalar. `a: ?` dava a cadeia `'?'`.
        raise YamlIlegivel(f"{onde}: chave explicita ('?') nao suportada")

    if ": " in texto or texto.endswith(":"):
        # `razao: a: b` dava a cadeia `"a: b"`; o YAML recusa-o («mapping values
        # are not allowed here»). Ler o que o YAML recusa e a mesma classe de
        # defeito que ler mal: o ficheiro nao diz o que a ferramenta leu.
        raise YamlIlegivel(
            f"{onde}: escalar nao citado com ':' ({texto!r}); o YAML tambem o recusa — use aspas"
        )

    if texto in ("~", "null"):
        return None
    if texto in ("true", "false"):
        return texto == "true"
    if texto in _AMBIGUOS:
        raise YamlIlegivel(
            f"{onde}: {texto!r} e ambiguo entre booleano/nulo e texto; "
            "use `true`, `false`, `null`, ou aspas"
        )
    if _INTEIRO.match(texto):
        return int(texto)
    if _PARECE_NUMERO.match(texto):
        raise YamlIlegivel(
            f"{onde}: {texto!r} parece um numero e este leitor so converte inteiros "
            "decimais sem zero a esquerda; use um inteiro, ou aspas se for texto"
        )
    return texto


class _Fluxo:
    """Analisador descendente de uma expressao de fluxo numa linha."""

    def __init__(self, texto: str, onde: str, profundidade: int = 0) -> None:
        self.t, self.i, self.onde = texto, 0, onde
        self.profundidade = profundidade

    def _espacos(self) -> None:
        while self.i < len(self.t) and self.t[self.i] in " \t":
            self.i += 1

    def _atomo(self, paragens: str) -> str:
        self._espacos()
        if self.i < len(self.t) and self.t[self.i] in "\"'":
            aspa = self.t[self.i]
            fim = self.t.find(aspa, self.i + 1)
            if fim == -1:
                raise YamlIlegivel(f"{self.onde}: aspas por fechar")
            bruto = self.t[self.i : fim + 1]
            self.i = fim + 1
            self._espacos()
            if self.i < len(self.t) and self.t[self.i] not in paragens:
                raise YamlIlegivel(
                    f"{self.onde}: conteudo depois da aspa de fecho ({self.t[self.i:]!r})"
                )
            return bruto
        inicio = self.i
        while self.i < len(self.t) and self.t[self.i] not in paragens:
            self.i += 1
        return self.t[inicio : self.i].strip()

    def valor(self):
        """Um valor de fluxo, com o aninhamento contado.

        O contador sobe a entrar e desce a sair: contar chamadas em vez de
        niveis recusava uma lista de 51 itens, que e aninhamento 1.
        """
        self.profundidade += 1
        if self.profundidade > _PROFUNDIDADE_MAXIMA:
            raise YamlIlegivel(
                f"{self.onde}: fluxo com mais de {_PROFUNDIDADE_MAXIMA} niveis de aninhamento"
            )
        try:
            return self._valor()
        finally:
            self.profundidade -= 1

    def _valor(self):
        self._espacos()
        if self.i >= len(self.t):
            raise YamlIlegivel(f"{self.onde}: fluxo que acaba a meio (fluxo em varias linhas nao e suportado)")
        c = self.t[self.i]
        if c == "[":
            self.i += 1
            itens = []
            while True:
                self._espacos()
                if self.i >= len(self.t):
                    raise YamlIlegivel(f"{self.onde}: `[` por fechar")
                if self.t[self.i] == "]":
                    self.i += 1
                    return itens
                itens.append(self.valor())
                self._espacos()
                if self.i < len(self.t) and self.t[self.i] == ",":
                    self.i += 1
                elif self.i < len(self.t) and self.t[self.i] != "]":
                    raise YamlIlegivel(f"{self.onde}: esperava `,` ou `]`")
        if c == "{":
            self.i += 1
            mapa: dict = {}
            while True:
                self._espacos()
                if self.i >= len(self.t):
                    raise YamlIlegivel(f"{self.onde}: `{{` por fechar")
                if self.t[self.i] == "}":
                    self.i += 1
                    return mapa
                bruta = self._chave_de_fluxo()
                if bruta.strip() == "":
                    raise YamlIlegivel(f"{self.onde}: chave vazia num mapa de fluxo")
                chave = _nome_da_chave(bruta)
                if chave == "<<":
                    raise YamlIlegivel(f"{self.onde}: merge key nao suportada ('<<')")
                self._espacos()
                if self.i >= len(self.t) or self.t[self.i] != ":":
                    raise YamlIlegivel(f"{self.onde}: esperava `:` depois de {chave!r}")
                self.i += 1
                if chave in mapa:
                    raise YamlIlegivel(f"{self.onde}: chave repetida {chave!r}")
                mapa[chave] = self.valor()
                self._espacos()
                if self.i < len(self.t) and self.t[self.i] == ",":
                    self.i += 1
                elif self.i < len(self.t) and self.t[self.i] != "}":
                    raise YamlIlegivel(f"{self.onde}: esperava `,` ou `}}`")
        return _escalar(self._atomo(",]}"), self.onde)

    def _chave_de_fluxo(self) -> str:
        self._espacos()
        if self.i < len(self.t) and self.t[self.i] in "\"'":
            return self._atomo(":")
        inicio = self.i
        while self.i < len(self.t) and self.t[self.i] not in ":,{}[]":
            self.i += 1
        return self.t[inicio : self.i].strip()

    def tudo(self):
        resultado = self.valor()
        self._espacos()
        if self.i != len(self.t):
            raise YamlIlegivel(f"{self.onde}: texto a mais depois do fluxo: {self.t[self.i:]!r}")
        return resultado


def _valor(texto: str, onde: str, profundidade: int = 0):
    texto = texto.strip()
    if texto[:1] in ("{", "["):
        # O aninhamento do fluxo conta a partir do nivel de bloco onde esta.
        return _Fluxo(texto, onde, profundidade).tudo()
    return _escalar(texto, onde)


class _Leitor:
    def __init__(self, texto: str) -> None:
        self.linhas: list[tuple[int, int, str]] = []
        # O BOM e permitido no inicio do *stream* (YAML 1.2 §5.2). Sem isto, um
        # ficheiro gravado como «UTF-8 with BOM» dava uma primeira chave com o
        # BOM dentro do nome, em silencio.
        texto = texto.lstrip("\ufeff")
        for ambigua, nome in _QUEBRAS_AMBIGUAS.items():
            if ambigua in texto:
                numero = texto[: texto.index(ambigua)].count("\n") + 1
                raise YamlIlegivel(
                    f"linha {numero}: {nome} e quebra de linha em YAML 1.1 e nao em 1.2; "
                    "nao se adivinha a versao — tire-o ou use uma quebra de linha"
                )
        # `\r` sozinho **e** quebra de linha (YAML 1.2 §5.4).
        texto = texto.replace("\r\n", "\n").replace("\r", "\n")
        for numero, bruta in enumerate(texto.split("\n"), start=1):
            onde = f"linha {numero}"
            achado = _CONTROLO.search(bruta)
            if achado:
                raise YamlIlegivel(
                    f"{onde}: caractere de controlo {achado.group()!r} "
                    "nao e admitido num documento YAML"
                )
            margem = bruta[: len(bruta) - len(bruta.lstrip())]
            if "\t" in margem:
                raise YamlIlegivel(f"{onde}: tabulacao na indentacao")
            limpa = _sem_comentario(bruta, onde).rstrip()
            if not limpa.strip():
                continue
            if limpa.strip() in ("---", "..."):
                raise YamlIlegivel(f"{onde}: documentos multiplos nao suportados")
            self.linhas.append((numero, len(limpa) - len(limpa.lstrip(" ")), limpa.strip()))
        self.p = 0

    def olhar(self):
        return self.linhas[self.p] if self.p < len(self.linhas) else None

    def _fundo(self, profundidade: int, numero: int) -> None:
        """O leitor e recursivo: sem isto, 400 linhas de YAML de bloco
        perfeitamente comum davam um `RecursionError` — que nao e uma recusa,
        e sim o *gate* morto com *traceback* e codigo 1."""
        if profundidade > _PROFUNDIDADE_MAXIMA:
            raise YamlIlegivel(
                f"linha {numero}: mais de {_PROFUNDIDADE_MAXIMA} niveis de aninhamento"
            )

    def bloco(self, indentacao: int, profundidade: int = 1):
        item = self.olhar()
        if item is None:
            return None
        numero, actual, conteudo = item
        self._fundo(profundidade, numero)
        if conteudo == "-" or conteudo.startswith("- "):
            return self.lista(actual, profundidade)
        return self.mapa(actual, profundidade)

    def _filho(self, indentacao: int, numero: int, profundidade: int = 1):
        """O valor de uma chave (ou item) sem nada na propria linha."""
        seguinte = self.olhar()
        if seguinte is None:
            return None
        _, proxima, conteudo = seguinte
        if proxima > indentacao:
            return self.bloco(proxima, profundidade + 1)
        if proxima == indentacao and (conteudo == "-" or conteudo.startswith("- ")):
            # lista ao nivel da chave: YAML valido
            return self.lista(proxima, profundidade + 1)
        return None

    def mapa(self, indentacao: int, profundidade: int = 1) -> dict:
        resultado: dict = {}
        while True:
            item = self.olhar()
            if item is None:
                break
            numero, actual, conteudo = item
            if actual < indentacao:
                break
            if actual > indentacao:
                raise YamlIlegivel(f"linha {numero}: indentacao inesperada")
            if conteudo == "-" or conteudo.startswith("- "):
                break
            achado = _CHAVE.match(conteudo)
            if not achado:
                if conteudo[:1] in _PROIBIDOS:
                    # Sem isto, `%YAML 1.2` e `@a: 1` caiam na mensagem generica
                    # — recusados, mas pela regra errada, que manda procurar um
                    # erro de sintaxe em vez do indicador que la esta.
                    raise YamlIlegivel(
                        f"linha {numero}: {_PROIBIDOS[conteudo[0]]} nao suportado "
                        f"({conteudo[0]!r})"
                    )
                raise YamlIlegivel(f"linha {numero}: esperava `chave: valor` (lido {conteudo!r})")
            self.p += 1
            chave = _nome_da_chave(achado.group("chave"))
            if chave == "<<":
                # `<<: valor` e uma *merge key*. Era lida como uma chave
                # chamada `<<`, o que da um mapa com uma chave a mais e sem a
                # fusao que o ficheiro pedia.
                raise YamlIlegivel(f"linha {numero}: merge key nao suportada ('<<')")
            if chave in resultado:
                raise YamlIlegivel(f"linha {numero}: chave repetida {chave!r}")
            resto = (achado.group("resto") or "").strip()
            if resto == "":
                resultado[chave] = self._filho(indentacao, numero, profundidade)
            else:
                resultado[chave] = _valor(resto, f"linha {numero}", profundidade)
        return resultado

    def lista(self, indentacao: int, profundidade: int = 1) -> list:
        resultado: list = []
        while True:
            item = self.olhar()
            if item is None:
                break
            numero, actual, conteudo = item
            if actual != indentacao or not (conteudo == "-" or conteudo.startswith("- ")):
                if actual > indentacao:
                    raise YamlIlegivel(f"linha {numero}: indentacao inesperada numa lista")
                break
            corpo = conteudo[1:].strip()
            if corpo == "":
                self.p += 1
                resultado.append(self._filho(indentacao, numero, profundidade))
            elif corpo == "-" or corpo.startswith("- "):
                # `- - a`: uma sequencia dentro de uma sequencia. Antes, o corpo
                # caia no `_valor` e a lista interior virava a cadeia `"- a"`.
                raise YamlIlegivel(f"linha {numero}: lista aninhada nao suportada ({conteudo!r})")
            # A aspa **nao** exclui o ramo de mapa: `- "a": 1` e um item que e um
            # mapa de chave citada, e `- "a: b"` continua a ser cadeia, porque o
            # `_CHAVE` exige o `:` **depois** da aspa de fecho.
            elif corpo[:1] not in ("{", "[") and _CHAVE.match(corpo):
                # `- chave: valor`: o item e um mapa cuja primeira chave esta
                # nesta linha, a `indentacao + 2`.
                desvio = len(conteudo) - len(corpo)
                self.linhas[self.p] = (numero, indentacao + desvio, corpo)
                resultado.append(self.mapa(indentacao + desvio, profundidade + 1))
            else:
                self.p += 1
                resultado.append(_valor(corpo, f"linha {numero}", profundidade))
        return resultado


def ler(texto: str):
    """Le um documento. Devolve o que la estiver (mapa, lista) ou `None` se vazio."""
    leitor = _Leitor(texto)
    if leitor.olhar() is None:
        return None
    numero, indentacao, _ = leitor.olhar()
    if indentacao != 0:
        raise YamlIlegivel(f"linha {numero}: o documento tem de comecar sem indentacao")
    documento = leitor.bloco(0)
    sobra = leitor.olhar()
    if sobra is not None:
        raise YamlIlegivel(f"linha {sobra[0]}: conteudo que nao foi lido ({sobra[2]!r})")
    return documento
