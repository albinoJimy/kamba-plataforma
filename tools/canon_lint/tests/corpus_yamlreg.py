"""O corpus da varredura do KAM-148 sobre o `tools/canon_lint/yamlreg.py`.

Uma construcao por entrada, com o **resultado declarado**: ou a estrutura que o
leitor tem de devolver, ou `RECUSA` — a sentinela que diz que a unica saida
aceitavel e um `YamlIlegivel`. Nao ha terceira saida: ler uma estrutura
diferente da declarada **e** o defeito que este ticket fecha.

O corpus esta aqui, e nao dentro do ficheiro de testes, porque serve duas
coisas: `test_yamlreg.py` usa-o como teste permanente, e a varredura do ticket
usa-o para classificar cada caso contra a copia congelada do leitor anterior
(`leitor_antes_do_kam148.py`) **e** contra o actual, pela diferenca entre as
duas saidas. A tabela caso a caso esta em `docs/evidencia/KAM-148.md`.

As 101 construcoes do KAM-136 (`docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md`
§2) estao aqui adaptados, mais os que so existem neste leitor: o estilo de
fluxo, que o `kamba_yaml` recusa de proposito e que por isso **nunca ninguem
mediu**.
"""

from __future__ import annotations


class _Recusa:
    def __repr__(self) -> str:  # pragma: no cover - so para mensagens de teste
        return "RECUSA"


#: A unica saida aceitavel e um `YamlIlegivel` com ficheiro e linha.
RECUSA = _Recusa()

#: 60 niveis de mapa de bloco, acima do `_PROFUNDIDADE_MAXIMA` do leitor.
_FUNDO_DE_BLOCO = "".join("  " * nivel + f"k{nivel}:\n" for nivel in range(60)) + "  " * 60 + "v: 1\n"

#: 60 niveis de lista de fluxo, na mesma.
_FUNDO_DE_FLUXO = "a: " + "[" * 60 + "1" + "]" * 60 + "\n"

#: O que o leitor tem de devolver, por construcao.
CASOS: dict[str, tuple[str, object]] = {
    # ------------------------------------------------------------------ #
    # Estrutura que este leitor nao tem, e que ja recusava
    # ------------------------------------------------------------------ #
    "ancora": ("id: &a valor\n", RECUSA),
    "alias": ("a: &x 1\nb: *x\n", RECUSA),
    "ancora em item de lista": ("l:\n  - &a valor\n", RECUSA),
    "merge key": ("a:\n  <<: valor\n", RECUSA),
    "tag": ("id: !!str 1\n", RECUSA),
    "directiva": ("%YAML 1.2\nid: x\n", RECUSA),
    "indicador reservado @": ("id: @x\n", RECUSA),
    "indicador reservado crase": ("id: `x\n", RECUSA),
    # Os indicadores em posicao de **chave**: liam-se como chaves chamadas
    # `@a`, `` `a `` e `%YAML`, em silencio, e nenhuma e YAML valido (§7.3.3).
    "indicador reservado @ em posicao de chave": ("@a: 1\n", RECUSA),
    "indicador reservado crase em posicao de chave": ("`a: 1\n", RECUSA),
    "directiva em posicao de chave": ("%YAML: 1\n", RECUSA),
    "chave explicita": ("? a\n", RECUSA),
    # Indicadores de fluxo no inicio de um escalar plano: liam-se como cadeia.
    "indicador de fluxo ] como valor": ("a: ]\n", RECUSA),
    "indicador de fluxo } como valor": ("a: }\n", RECUSA),
    "indicador de fluxo , como valor": ("a: ,\n", RECUSA),
    "chave explicita como valor": ("a: ?\n", RECUSA),
    # O leitor e recursivo: sem limite, 400 niveis davam um `RecursionError`,
    # que nao e recusa — e o *gate* morto com *traceback* e codigo 1.
    "aninhamento de bloco acima do limite": (_FUNDO_DE_BLOCO, RECUSA),
    "aninhamento de fluxo acima do limite": (_FUNDO_DE_FLUXO, RECUSA),
    # Os seis indicadores de bloco, um caso cada: a lista do *docstring* diz
    # «(`|`, `|-`, `|+`, `>`, `>-`, `>+`)» e tem de ser verdadeira nos seis.
    "escalar literal": ("id: |\n  linha\n", RECUSA),
    "escalar literal sem linha final": ("id: |-\n  linha\n", RECUSA),
    "escalar literal com linhas finais": ("id: |+\n  linha\n", RECUSA),
    "escalar dobrado com linha final": ("id: >\n  linha\n", RECUSA),
    "escalar dobrado": ("id: >-\n  linha\n", RECUSA),
    "escalar dobrado com linhas finais": ("id: >+\n  linha\n", RECUSA),
    "escalar dobrado sem conteudo": ("id: >-\n", RECUSA),
    "documentos multiplos": ("---\na: 1\n---\nb: 2\n", RECUSA),
    "marcador de um documento": ("---\nid: x\n", RECUSA),
    "fim de documento": ("a: 1\n...\n", RECUSA),
    "tabulacao na indentacao": ("id:\n\t- x\n", RECUSA),
    "chave repetida no mapa": ("a: 1\na: 2\n", RECUSA),
    "chave repetida no item de lista": ("l:\n  - a: 1\n    a: 2\n", RECUSA),
    "documento que comeca indentado": ("  id: x\n", RECUSA),
    "indentacao inesperada no mapa": ("a: 1\n  b: 2\n", RECUSA),
    "indentacao inesperada numa lista": ("l:\n  - a\n    - b\n", RECUSA),
    # ------------------------------------------------------------------ #
    # Estilo de fluxo — a superficie que o KAM-136 nao tinha
    # ------------------------------------------------------------------ #
    "fluxo: mapa de uma linha": (
        "models: { router: kamba-router, chat: kamba-chat }\n",
        {"models": {"router": "kamba-router", "chat": "kamba-chat"}},
    ),
    "fluxo: mapa vazio": ("models: {}\n", {"models": {}}),
    "fluxo: lista de uma linha": (
        "tools: [list_services, book_slot]\n",
        {"tools": ["list_services", "book_slot"]},
    ),
    "fluxo: lista vazia": ("limites: []\n", {"limites": []}),
    "fluxo: lista vazia com espaco": ("limites: [ ]\n", {"limites": []}),
    "fluxo: a subscricao do manifesto real": (
        "subscriptions:\n  - { tipo: payment.confirmed, versao: 1 }\n",
        {"subscriptions": [{"tipo": "payment.confirmed", "versao": 1}]},
    ),
    "fluxo: lista dentro de mapa": (
        "entitlements: { modulo: vendedor, limites: [msgs_ai_mes] }\n",
        {"entitlements": {"modulo": "vendedor", "limites": ["msgs_ai_mes"]}},
    ),
    "fluxo: virgula dentro de aspas": (
        'guardrails: { tom: "cordial, directo" }\n',
        {"guardrails": {"tom": "cordial, directo"}},
    ),
    "fluxo: cardinal dentro de aspas": (
        'guardrails: { tom: "usa # para marcar" }\n',
        {"guardrails": {"tom": "usa # para marcar"}},
    ),
    "fluxo: chave citada": ('a: { "b c": 1 }\n', {"a": {"b c": 1}}),
    "fluxo: chave repetida": ("a: { b: 1, b: 2 }\n", RECUSA),
    # A `merge key` em fluxo tem o seu caso porque e outro ramo do leitor: sem
    # ele, a verificacao podia desaparecer de la sem nenhum teste ficar
    # vermelho. Foi uma mutacao sobrevivente que o mostrou.
    "fluxo: merge key": ("a: { <<: b }\n", RECUSA),
    "fluxo: partido por varias linhas": ("a: [1,\n  2]\n", RECUSA),
    "fluxo: lista por fechar": ("a: [1, 2\n", RECUSA),
    "fluxo: mapa por fechar": ("a: { b: 1\n", RECUSA),
    "fluxo: item vazio": ("a: [1,, 2]\n", RECUSA),
    "fluxo: chave vazia": ("a: { : 1 }\n", RECUSA),
    "fluxo: par solto numa sequencia": ("a: [b: 1]\n", RECUSA),
    "fluxo: chave sem dois pontos": ("a: { b }\n", RECUSA),
    "fluxo: texto a mais depois do fecho": ("a: [1] extra\n", RECUSA),
    "fluxo: aspas por fechar": ('a: ["x]\n', RECUSA),
    "fluxo: conteudo depois da aspa de fecho": ('a: ["x" y]\n', RECUSA),
    # ------------------------------------------------------------------ #
    # Estrutura em bloco que este leitor le — e o `kamba_yaml` recusa
    # ------------------------------------------------------------------ #
    "mapa aninhado": (
        "persona:\n  nome: Vendedor\n  idioma: pt\n",
        {"persona": {"nome": "Vendedor", "idioma": "pt"}},
    ),
    "lista de escalares em bloco": ("tools:\n  - a\n  - b\n", {"tools": ["a", "b"]}),
    "lista de mapas em bloco": (
        "subscriptions:\n  - tipo: a\n    versao: 1\n  - tipo: b\n    versao: 2\n",
        {"subscriptions": [{"tipo": "a", "versao": 1}, {"tipo": "b", "versao": 2}]},
    ),
    "lista ao nivel da chave": ("tools:\n- a\n- b\n", {"tools": ["a", "b"]}),
    "documento de topo que e lista": ("- a\n- b\n", ["a", "b"]),
    "chave sem valor e nulo": ("a:\nb: 1\n", {"a": None, "b": 1}),
    "lista aninhada": ("l:\n  - - a\n", RECUSA),
    "documento vazio": ("", None),
    "documento so com comentario": ("# so um comentario\n", None),
    # ------------------------------------------------------------------ #
    # Escalares que liam bem, e continuam a ler bem
    # ------------------------------------------------------------------ #
    "nulo explicito": ("a: null\n", {"a": None}),
    "nulo com til": ("a: ~\n", {"a": None}),
    "booleano": ("activo: true\nparado: false\n", {"activo": True, "parado": False}),
    "inteiro": ("versao: 1\n", {"versao": 1}),
    "zero": ("limiar: 0\n", {"limiar": 0}),
    "data nao e numero": ("criado_em: 2026-10-12\n", {"criado_em": "2026-10-12"}),
    "semver de tres partes": ("version: 1.0.0\n", {"version": "1.0.0"}),
    "etiqueta com sufixo": ("etiqueta: 0.8.7-pg18\n", {"etiqueta": "0.8.7-pg18"}),
    "cardinal dentro de aspas": ('tom: "usa # para marcar"\n', {"tom": "usa # para marcar"}),
    "comentario de fim de linha": ("id: vendedor  # a vertical\n", {"id": "vendedor"}),
    "tabulacao depois dos dois pontos": ("id:\tvendedor\n", {"id": "vendedor"}),
    "item citado com dois pontos": ('l:\n  - "a: b"\n', {"l": ["a: b"]}),
    "item de lista com chave citada e um mapa": (
        # O `_CHAVE` exige o `:` **depois** da aspa de fecho, pelo que o item
        # anterior continua a ser cadeia e este e um mapa.
        'l:\n  - "a": 1\n',
        {"l": [{"a": 1}]},
    ),
    "chave citada com um cardinal dentro": ('"a #b": c\n', {"a #b": "c"}),
    "lista de 60 itens nao e aninhamento": (
        # O limite conta **niveis**, nao chamadas: contar chamadas recusava uma
        # lista de 51 itens, que e aninhamento 1.
        "l:\n" + "".join(f"  - {i}\n" for i in range(60)),
        {"l": list(range(60))},
    ),
    "fluxo de 60 itens nao e aninhamento": (
        "a: [" + ", ".join(str(i) for i in range(60)) + "]\n",
        {"a": list(range(60))},
    ),
    "item nao citado com dois pontos e cadeia": (
        "l:\n  - https://exemplo.ao/p\n",
        {"l": ["https://exemplo.ao/p"]},
    ),
    "apostrofo em texto plano": ("tom: o 'valor que ficou\n", {"tom": "o 'valor que ficou"}),
    "aspa a meio de texto plano nao abre cadeia": (
        'tom: a - "b # c"\n',
        {"tom": 'a - "b'},
    ),
    # ------------------------------------------------------------------ #
    # Liam mal em silencio, e passaram a LER BEM (interpretar)
    # ------------------------------------------------------------------ #
    "apostrofo no meio nao engole o comentario": (
        # Antes: o apostrofo «abria» uma aspa, o `#` ficava «dentro de aspas» e
        # o comentario entrava no valor.
        "id: nao e' assim  # nota\n",
        {"id": "nao e' assim"},
    ),
    "inteiro com sinal": ("limiar: +5\n", {"limiar": 5}),
    "algarismos nao-ASCII sao texto": (
        # O `int()` aceita `١٢٣`; o YAML resolve inteiros so com `[0-9]`.
        "limiar: \u0661\u0662\u0663\n",
        {"limiar": "\u0661\u0662\u0663"},
    ),
    "chave com zeros a esquerda nao e numero": ("007: x\n", {"007": "x"}),
    "chave citada com zeros a esquerda": ('"007": x\n', {"007": "x"}),
    "chave que parece booleano fica texto": ("true: x\n", {"true": "x"}),
    "BOM no inicio do ficheiro": ("\ufeffversion: 1\na: 2\n", {"version": 1, "a": 2}),
    "CR sozinho e quebra de linha": ("a: 1\rb: 2\r", {"a": 1, "b": 2}),
    "chave citada com apostrofo dentro": ("\"a'\": 1\n", {"a'": 1}),
    "chave que e duas aspas simples": ("\"''\": 1\n", {"''": 1}),
    # ------------------------------------------------------------------ #
    # Liam mal em silencio, e passaram a RECUSA
    # ------------------------------------------------------------------ #
    "verdadeiro maiusculo": ("activo: True\n", RECUSA),
    "falso maiusculo": ("activo: FALSE\n", RECUSA),
    "sim": ("activo: yes\n", RECUSA),
    "nao": ("activo: no\n", RECUSA),
    "ligado": ("activo: on\n", RECUSA),
    "desligado": ("activo: off\n", RECUSA),
    "nulo maiusculo": ("a: NULL\n", RECUSA),
    "nulo do Python": ("a: None\n", RECUSA),
    "decimal": ("temperatura: 1.5\n", RECUSA),
    "exponente": ("limiar: 1e3\n", RECUSA),
    "hexadecimal": ("limiar: 0x1f\n", RECUSA),
    "sublinhado de milhares": ("limiar: 1_000\n", RECUSA),
    "infinito": ("limiar: .inf\n", RECUSA),
    "nao numero": ("limiar: .nan\n", RECUSA),
    "octal do YAML 1.1 (017)": ("modo: 017\n", RECUSA),
    "octal do YAML 1.1 (0644)": ("modo: 0644\n", RECUSA),
    "zero a esquerda que nao e octal": ("modo: 008\n", RECUSA),
    "zero a esquerda com sinal": ("modo: -010\n", RECUSA),
    "inteiro com zeros a esquerda": ("limiar: 007\n", RECUSA),
    "sexagesimal do YAML 1.1": ("limite: 1:30\n", RECUSA),
    "sexagesimal de tres partes": ("limite: 10:20:30\n", RECUSA),
    "aspa dupla aberta e nao fechada": ('tom: "abre e nao fecha\n', RECUSA),
    "aspa simples aberta e nao fechada": ("tom: 'abre e nao fecha\n", RECUSA),
    "conteudo depois da aspa de fecho": ('tom: "a" extra\n', RECUSA),
    "duas partes citadas": ('tom: "a" "b"\n', RECUSA),
    "aspa simples duplicada": ("tom: 'o ''valor'' certo'\n", RECUSA),
    "aspa dupla escapada": ('tom: "o \\"valor\\" certo"\n', RECUSA),
    "cardinal depois de aspa aberta": ("tom: 'abre e nao fecha # nota\n", RECUSA),
    "valor plano com dois pontos": ("tom: a: b\n", RECUSA),
    "valor plano que acaba em dois pontos": ("tom: nota:\n", RECUSA),
    "NUL no valor": ("a: x\x00y\n", RECUSA),
    "ESC no valor": ("a: x\x1by\n", RECUSA),
    "DEL no valor": ("a: x\x7fy\n", RECUSA),
    "form feed na indentacao": ("\x0ca: 1\n", RECUSA),
    "NEL como quebra de linha": ("l:\n  - um\x85  - dois\n", RECUSA),
    "U+2028 como quebra de linha": ("l:\n  - um\u2028  - dois\n", RECUSA),
    "U+2029 como quebra de linha": ("l:\n  - um\u2029  - dois\n", RECUSA),
}

#: Os defeitos que a copia congelada **tem de** continuar a ter: se os perder,
#: deixou de ser oraculo e o teste de equivalencia passa a verde por construcao.
DEFEITOS_DO_LEITOR_ANTERIOR: dict[str, tuple[str, object]] = {
    "falso maiusculo era a cadeia 'FALSE', verdadeira em Python": (
        "activo: FALSE\n",
        {"activo": "FALSE"},
    ),
    "um decimal era uma cadeia": ("temperatura: 1.5\n", {"temperatura": "1.5"}),
    "algarismos nao-ASCII viravam um inteiro": (
        "limiar: \u0661\u0662\u0663\n",
        {"limiar": 123},
    ),
    "uma aspa aberta e nao fechada entrava no texto": (
        'tom: "abre e nao fecha\n',
        {"tom": '"abre e nao fecha'},
    ),
    "a lista aninhada virava a cadeia do item interior": ("l:\n  - - a\n", {"l": ["- a"]}),
    "um apostrofo a meio engolia o comentario": (
        "id: nao e' assim  # nota\n",
        {"id": "nao e' assim  # nota"},
    ),
    "a chave passava pelo conversor do valor": ("007: x\n", {"7": "x"}),
}
