"""O corpus da varredura do KAM-148 sobre o `tools/secrets_inventory/yamlsubset.py`.

Uma construcao por entrada, com o **resultado declarado**: ou a estrutura que o
leitor tem de devolver, ou `RECUSA` — a sentinela que diz que a unica saida
aceitavel e um `YamlSubsetError`. Nao ha terceira saida: ler uma estrutura
diferente da declarada **e** o defeito que este ticket fecha.

O corpus esta aqui, e nao dentro do ficheiro de testes, porque serve duas
coisas: `test_yamlsubset.py` usa-o como teste permanente, e a varredura do
ticket usa-o para classificar cada caso contra a copia congelada do leitor
anterior (`leitor_antes_do_kam148.py`) **e** contra o actual, pela diferenca
entre as duas saidas. A tabela caso a caso esta em `docs/evidencia/KAM-148.md`.

As 101 construcoes do KAM-136 (`docs/analises/ANALISE-12-KAM-136-leitor-de-yaml.md`
§2) estao aqui adaptados ao subconjunto deste leitor — que aceita listas de
fluxo **com conteudo**, e nao aceita mapas de fluxo nem aninhamento alem de
«mapa de topo → lista de mapas».
"""

from __future__ import annotations


class _Recusa:
    def __repr__(self) -> str:  # pragma: no cover - so para mensagens de teste
        return "RECUSA"


#: A unica saida aceitavel e um `YamlSubsetError` com a linha.
RECUSA = _Recusa()

#: A forma que o inventario real usa, como referencia das que leem bem.
_ENTRADA = (
    "segredos:\n"
    "  - id: meta_app_secret\n"
    '    fonte_08_5: "WhatsApp Cloud API"\n'
    "    rotacao_dias: 180\n"
    "    rotacao_gatilho: null\n"
    "    ambientes: [dev, prod]\n"
    "    obrigatorio_em: []\n"
)

CASOS: dict[str, tuple[str, object]] = {
    # ------------------------------------------------------------------ #
    # A forma do inventario real
    # ------------------------------------------------------------------ #
    "a entrada do inventario real": (
        _ENTRADA,
        {
            "segredos": [
                {
                    "id": "meta_app_secret",
                    "fonte_08_5": "WhatsApp Cloud API",
                    "rotacao_dias": 180,
                    "rotacao_gatilho": None,
                    "ambientes": ["dev", "prod"],
                    "obrigatorio_em": [],
                }
            ]
        },
    ),
    "escalares de topo": (
        'versao: 1\nestado: proposta\nfonte: "doc 08 §5"\n',
        {"versao": 1, "estado": "proposta", "fonte": "doc 08 §5"},
    ),
    "lista de fluxo": ("ambientes: [dev, staging, prod]\n", {"ambientes": ["dev", "staging", "prod"]}),
    "lista de fluxo vazia": ("ambientes: []\n", {"ambientes": []}),
    "nulo explicito": ("rotacao_gatilho: null\n", {"rotacao_gatilho": None}),
    "nulo com til": ("rotacao_gatilho: ~\n", {"rotacao_gatilho": None}),
    "booleano": ("obrigatorio: true\nopcional: false\n", {"obrigatorio": True, "opcional": False}),
    "inteiro": ("rotacao_dias: 180\n", {"rotacao_dias": 180}),
    "zero": ("rotacao_dias: 0\n", {"rotacao_dias": 0}),
    "data nao e numero": ("actualizado_em: 2026-10-11\n", {"actualizado_em": "2026-10-11"}),
    "semver de tres partes": ("versao_do_cofre: 1.0.0\n", {"versao_do_cofre": "1.0.0"}),
    "dois pontos dentro de aspas": (
        'fonte: "doc 08 §5: tabela de segredos"\n',
        {"fonte": "doc 08 §5: tabela de segredos"},
    ),
    "cardinal dentro de aspas": ('nota: "usa # para comentar"\n', {"nota": "usa # para comentar"}),
    "comentario de fim de linha": ("id: meta_app_secret  # do doc 08\n", {"id": "meta_app_secret"}),
    "comentario de linha inteira": ("# --- Meta ---\nid: x\n", {"id": "x"}),
    "cardinal sem aspas e comentario": ("nota: usa # isto\n", {"nota": "usa"}),
    "apostrofo em texto plano": ("nota: o 'valor que ficou\n", {"nota": "o 'valor que ficou"}),
    # As formas de chave que uma primeira versao deste ticket recusava, e que o
    # leitor anterior lia **correctamente**. Num repositorio em portugues, a
    # chave acentuada e a mais plausivel de todas.
    "chave acentuada": ("rotação_dias: 180\n", {"rotação_dias": 180}),
    "chave com espaco": ("a b: 1\n", {"a b": 1}),
    "chave com barra": ("a/b: 1\n", {"a/b": 1}),
    "chave que comeca por digito": ("2fa: x\n", {"2fa": "x"}),
    "espaco antes dos dois pontos": ("a : b\n", {"a": "b"}),
    "chave citada com um cardinal dentro": ('"a #b": c\n', {"a #b": "c"}),
    "chave de topo sem valor e nulo": (
        # Assumir sempre uma lista dava `{"a": []}`; o YAML diz nulo.
        "a:\nb: 1\n",
        {"a": None, "b": 1},
    ),
    "chave que abre uma lista com um item": (
        "a:\n  - b: 1\n",
        {"a": [{"b": 1}]},
    ),
    "fecho de lista dentro de aspas na lista de fluxo": (
        # A deteccao de aninhamento corria **antes** de se respeitar as aspas, e
        # recusava isto com «lista de listas».
        'a: ["x]y"]\n',
        {"a": ["x]y"]},
    ),
    "parentesis recto dentro de um item nao citado": ("a: [x]y]\n", RECUSA),
    "documento vazio": ("", {}),
    # ------------------------------------------------------------------ #
    # Estrutura que este leitor nao tem, e que ja recusava
    # ------------------------------------------------------------------ #
    "ancora": ("id: &a valor\n", RECUSA),
    "alias": ("a: &x 1\nb: *x\n", RECUSA),
    "tag": ("id: !!str 1\n", RECUSA),
    "directiva": ("%YAML 1.2\nid: x\n", RECUSA),
    "merge key": ("<<: valor\n", RECUSA),
    "mapa em estilo de fluxo": ("models: {a: 1}\n", RECUSA),
    "indicador reservado @": ("nota: @x\n", RECUSA),
    "indicador reservado crase": ("nota: `x\n", RECUSA),
    "indicador reservado @ em posicao de chave": ("@a: 1\n", RECUSA),
    "directiva em posicao de chave": ("%YAML: 1\n", RECUSA),
    "chave explicita": ("? a\n", RECUSA),
    "indicador de fluxo ] como valor": ("a: ]\n", RECUSA),
    "indicador de fluxo } como valor": ("a: }\n", RECUSA),
    "indicador de fluxo , como valor": ("a: ,\n", RECUSA),
    "chave explicita como valor": ("a: ?\n", RECUSA),
    # O `#` nao entra num nome de chave: o corte de comentarios tira-se linha a
    # linha, antes de se saber se o `#` e comentario. E a unica forma que o
    # leitor anterior lia e este recusa, e esta escrita no *docstring*.
    "cardinal dentro do nome da chave": ("a#b: 1\n", RECUSA),
    "escalar literal": ("nota: |\n  linha\n", RECUSA),
    "escalar dobrado": ("nota: >-\n  linha\n", RECUSA),
    "documentos multiplos": ("---\na: 1\n---\nb: 2\n", RECUSA),
    "marcador de um documento": ("---\nid: x\n", RECUSA),
    "fim de documento": ("a: 1\n...\n", RECUSA),
    "tabulacao": ("id:\tx\n", RECUSA),
    "chave repetida no mesmo item": ("l:\n  - a: 1\n    a: 2\n", RECUSA),
    "item de lista sem chave de lista acima": ("- a: 1\n", RECUSA),
    "item de lista que nao e 'chave: valor'": ("l:\n  - escalar\n", RECUSA),
    "item de lista com chave sem valor": ("l:\n  - a:\n", RECUSA),
    "lista de listas": ("l:\n  - a: [[1]]\n", RECUSA),
    "lista aninhada alem de um nivel": ("a:\n  b:\n    - c: 1\n", RECUSA),
    "chave indentada fora de um item": ("a: 1\n  b: 2\n", RECUSA),
    "indentacao de item inconsistente": ("l:\n  - a: 1\n   - b: 2\n", RECUSA),
    "lista de fluxo sem fecho": ("ambientes: [dev, prod\n", RECUSA),
    "sem dois pontos": ("isto nao e um mapa\n", RECUSA),
    "valor vazio depois dos dois pontos num item": ("l:\n  - a: \n", RECUSA),
    # ------------------------------------------------------------------ #
    # Liam mal em silencio, e passaram a RECUSA
    # ------------------------------------------------------------------ #
    "chave de topo repetida": ("id: 1\nid: 2\n", RECUSA),
    "chave de topo repetida com lista pelo meio": (
        "ambientes: [dev]\nid: 1\nambientes: [prod]\n",
        RECUSA,
    ),
    "chave de topo repetida que abre uma lista": (
        # O ramo do `load` que abre uma lista de mapas e outro: sem um caso
        # proprio, a verificacao podia desaparecer dele sem nenhum teste ficar
        # vermelho — foi uma mutacao sobrevivente que o mostrou.
        "segredos:\n  - id: a\nsegredos:\n  - id: b\n",
        RECUSA,
    ),
    "chave sem espaco depois dos dois pontos": ("id:valor\n", RECUSA),
    "verdadeiro maiusculo": ("obrigatorio: True\n", RECUSA),
    "falso maiusculo": ("obrigatorio: FALSE\n", RECUSA),
    "sim": ("obrigatorio: yes\n", RECUSA),
    "nao": ("obrigatorio: no\n", RECUSA),
    "ligado": ("activo: on\n", RECUSA),
    "desligado": ("activo: off\n", RECUSA),
    "nulo maiusculo": ("rotacao_gatilho: NULL\n", RECUSA),
    "nulo do Python": ("rotacao_gatilho: None\n", RECUSA),
    "decimal": ("rotacao_dias: 1.5\n", RECUSA),
    "exponente": ("rotacao_dias: 1e3\n", RECUSA),
    "hexadecimal": ("rotacao_dias: 0x1f\n", RECUSA),
    "sublinhado de milhares": ("rotacao_dias: 1_000\n", RECUSA),
    "infinito": ("rotacao_dias: .inf\n", RECUSA),
    "nao numero": ("rotacao_dias: .nan\n", RECUSA),
    "octal do YAML 1.1 (017)": ("rotacao_dias: 017\n", RECUSA),
    "octal do YAML 1.1 (0180)": ("rotacao_dias: 0180\n", RECUSA),
    "zero a esquerda que nao e octal": ("rotacao_dias: 008\n", RECUSA),
    "sexagesimal do YAML 1.1": ("limite: 1:30\n", RECUSA),
    "aspa dupla aberta e nao fechada": ('nota: "abre e nao fecha\n', RECUSA),
    "aspa simples aberta e nao fechada": ("nota: 'abre e nao fecha\n", RECUSA),
    "conteudo depois da aspa de fecho": ('nota: "a" extra\n', RECUSA),
    "duas partes citadas": ('nota: "a" "b"\n', RECUSA),
    "aspa simples duplicada": ("nota: 'o ''valor'' certo'\n", RECUSA),
    "aspa dupla escapada": ('nota: "o \\"valor\\" certo"\n', RECUSA),
    "cardinal depois de aspa aberta": ("nota: 'abre e nao fecha # nota\n", RECUSA),
    "valor plano com dois pontos": ("nota: a: b\n", RECUSA),
    "valor plano que acaba em dois pontos": ("nota: a:\n", RECUSA),
    "aspa por fechar dentro da lista de fluxo": ('ambientes: ["dev, prod]\n', RECUSA),
    "item vazio na lista de fluxo": ("ambientes: [dev,, prod]\n", RECUSA),
    "NUL no valor": ("a: x\x00y\n", RECUSA),
    "ESC no valor": ("a: x\x1by\n", RECUSA),
    "DEL no valor": ("a: x\x7fy\n", RECUSA),
    "form feed na indentacao": ("\x0ca: 1\n", RECUSA),
    # Sem `: ` depois da quebra: se a recusa das quebras ambiguas desaparecer,
    # estes tres **leem-se** (como uma cadeia com o caractere dentro) em vez de
    # cairem noutra recusa qualquer. Com `a: 1<NEL>b: 2` a prova nao valia: caia
    # na recusa do escalar nao citado com `: `. Foi uma mutacao sobrevivente que
    # o mostrou \u2014 a mesma armadilha que o KAM-136 apanhou nos seus.
    "NEL como quebra de linha": ("nota: um\x85dois\n", RECUSA),
    "U+2028 como quebra de linha": ("nota: um\u2028dois\n", RECUSA),
    "U+2029 como quebra de linha": ("nota: um\u2029dois\n", RECUSA),
    # ------------------------------------------------------------------ #
    # Liam mal em silencio, e passaram a LER BEM (interpretar)
    # ------------------------------------------------------------------ #
    "item nao citado com dois pontos nao e um mapa": (
        # Era o caso 2 do KAM-136, vivo aqui: `- https://x` dava
        # `{"https": "//x"}`. Aqui a escolha e **recusar**, e nao ler como
        # cadeia: este leitor nao tem itens de lista que sejam escalares.
        "consumidores:\n  - https://exemplo.ao/p\n",
        RECUSA,
    ),
    "virgula dentro de aspas na lista de fluxo": (
        # Antes, o `split(",")` dava tres itens, dois com uma aspa pendurada.
        'consumidores: ["gwy, chr", agr]\n',
        {"consumidores": ["gwy, chr", "agr"]},
    ),
    "apostrofo no meio nao engole o comentario": (
        "nota: nao e' assim  # nota\n",
        {"nota": "nao e' assim"},
    ),
    "inteiro com sinal": ("rotacao_dias: +5\n", {"rotacao_dias": 5}),
    "algarismos nao-ASCII sao texto": (
        "rotacao_dias: \u0661\u0662\u0663\n",
        {"rotacao_dias": "\u0661\u0662\u0663"},
    ),
    "chave citada com zeros a esquerda": ('"007": x\n', {"007": "x"}),
    "BOM no inicio do ficheiro": ("\ufeffversao: 1\n", {"versao": 1}),
    "CR sozinho e quebra de linha": ("a: 1\rb: 2\r", {"a": 1, "b": 2}),
}

#: Os defeitos que a copia congelada **tem de** continuar a ter: se os perder,
#: deixou de ser oraculo e o teste de equivalencia passa a verde por construcao.
DEFEITOS_DO_LEITOR_ANTERIOR: dict[str, tuple[str, object]] = {
    "a chave de topo repetida calava a primeira": ("id: 1\nid: 2\n", {"id": 2}),
    "`chave:valor` sem espaco virava um mapa": ("id:valor\n", {"id": "valor"}),
    "o caso 2 do KAM-136, vivo aqui": (
        "consumidores:\n  - https://exemplo.ao/p\n",
        {"consumidores": [{"https": "//exemplo.ao/p"}]},
    ),
    "o split(',') partia a aspa ao meio": (
        'consumidores: ["gwy, chr", agr]\n',
        {"consumidores": ['"gwy', 'chr"', "agr"]},
    ),
    "falso maiusculo era a cadeia 'FALSE', verdadeira em Python": (
        "obrigatorio: FALSE\n",
        {"obrigatorio": "FALSE"},
    ),
    "um periodo de rotacao com zero a esquerda virava outro numero": (
        "rotacao_dias: 0180\n",
        {"rotacao_dias": 180},
    ),
    "algarismos nao-ASCII viravam um inteiro": (
        "rotacao_dias: \u0661\u0662\u0663\n",
        {"rotacao_dias": 123},
    ),
}
