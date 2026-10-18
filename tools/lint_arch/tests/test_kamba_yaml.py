"""O leitor de YAML aceita o subconjunto e recusa o resto.

Os testes de recusa valem mais do que os de aceitacao: o valor deste modulo e
**ser inutil para qualquer outra coisa**. Se ele comecar a aceitar YAML a serio,
alguem reutiliza-o como se fosse, e deixa de se poder confiar em que o que esta
no ficheiro e o que a ferramenta leu.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import kamba_yaml
from kamba_yaml import YamlSubsetError, load

from . import leitor_antes_do_kam136

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / "ci"


class TestAceita(unittest.TestCase):
    def test_escalares(self) -> None:
        d = load(
            "texto: ola\n"
            "inteiro: 42\n"
            "verdade: true\n"
            "falsidade: false\n"
            "nulo: null\n"
            "til: ~\n"
            'aspas_duplas: "com: dois pontos"\n'
            "aspas_simples: 'com # cardinal'\n"
            "lista_vazia: []\n"
        )
        self.assertEqual(
            d,
            {
                "texto": "ola",
                "inteiro": 42,
                "verdade": True,
                "falsidade": False,
                "nulo": None,
                "til": None,
                "aspas_duplas": "com: dois pontos",
                "aspas_simples": "com # cardinal",
                "lista_vazia": [],
            },
        )

    def test_lista_de_escalares(self) -> None:
        self.assertEqual(
            load("itens:\n  - um\n  - dois\n  - 3\n"), {"itens": ["um", "dois", 3]}
        )

    def test_lista_de_mapas(self) -> None:
        d = load(
            "entradas:\n"
            "  - nome: a\n"
            "    valor: 1\n"
            "  - nome: b\n"
            "    valor: 2\n"
        )
        self.assertEqual(
            d, {"entradas": [{"nome": "a", "valor": 1}, {"nome": "b", "valor": 2}]}
        )

    def test_mapa_aninhado(self) -> None:
        d = load("fora:\n  dentro:\n    fundo: valor\n  irmao: 2\n")
        self.assertEqual(d, {"fora": {"dentro": {"fundo": "valor"}, "irmao": 2}})

    def test_lista_dentro_de_item_de_lista(self) -> None:
        d = load(
            "areas:\n"
            "  - caminho: x\n"
            "    classes:\n"
            "      - a\n"
            "      - b\n"
            "  - caminho: y\n"
            "    classes:\n"
            "      - c\n"
        )
        self.assertEqual(
            d["areas"],
            [{"caminho": "x", "classes": ["a", "b"]}, {"caminho": "y", "classes": ["c"]}],
        )

    def test_escalar_dobrado(self) -> None:
        d = load("razao: >-\n  primeira linha\n  segunda linha\n")
        self.assertEqual(d["razao"], "primeira linha segunda linha")

    def test_escalar_dobrado_dentro_de_item(self) -> None:
        d = load(
            "entradas:\n"
            "  - nome: a\n"
            "    razao: >-\n"
            "      uma razao\n"
            "      que continua\n"
            "    outro: 1\n"
        )
        self.assertEqual(
            d["entradas"], [{"nome": "a", "razao": "uma razao que continua", "outro": 1}]
        )

    def test_comentarios_e_linhas_vazias(self) -> None:
        d = load("# cabecalho\n\nchave: valor  # fim de linha\n\n# rodape\n")
        self.assertEqual(d, {"chave": "valor"})

    def test_cardinal_dentro_de_aspas_nao_e_comentario(self) -> None:
        self.assertEqual(load('chave: "a#b"\n'), {"chave": "a#b"})

    def test_documento_vazio(self) -> None:
        self.assertEqual(load(""), {})
        self.assertEqual(load("# so comentarios\n"), {})


class TestRecusa(unittest.TestCase):
    """Cada um destes e YAML valido que este leitor **nao** aceita."""

    CASOS = {
        "ancora": "chave: &ancora valor\n",
        "alias": "a: &x 1\nb: *x\n",
        "escalar literal": "chave: |\n  linha\n",
        "mapa em fluxo": "chave: {a: 1}\n",
        "lista em fluxo com conteudo": "chave: [a, b]\n",
        "tag": "chave: !!str 1\n",
        "documentos multiplos": "---\na: 1\n---\nb: 2\n",
        "tabulacao na indentacao": "chave:\n\t- item\n",
        "chave repetida": "a: 1\na: 2\n",
        "chave repetida em item": "l:\n  - a: 1\n    a: 2\n",
        "indentacao a comecar": "  chave: valor\n",
        "chave sem valor nem bloco": "chave:\n",
        "valor vazio depois de dois pontos": "chave: \nirmao: 1\n",
        "sem dois pontos": "isto nao e um mapa\n",
        "dobrado sem conteudo": "chave: >-\n",
    }

    def test_cada_caso_e_recusado(self) -> None:
        for nome, texto in self.CASOS.items():
            with self.subTest(caso=nome):
                with self.assertRaises(YamlSubsetError, msg=f"devia recusar: {nome}"):
                    load(texto)

    def test_a_mensagem_diz_a_linha(self) -> None:
        with self.assertRaises(YamlSubsetError) as capturado:
            load("a: 1\nb: 2\nc: {x: 1}\n")
        self.assertIn("linha 3", str(capturado.exception))

    def test_o_ficheiro_aparece_na_mensagem(self) -> None:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("chave: {a: 1}\n")
            caminho = Path(handle.name)
        try:
            with self.assertRaises(YamlSubsetError) as capturado:
                kamba_yaml.load_file(caminho)
            self.assertIn(caminho.name, str(capturado.exception))
        finally:
            caminho.unlink()


class TestFicheirosDoRepositorio(unittest.TestCase):
    """Os ficheiros reais leem-se, e leem-se com a forma que as ferramentas esperam."""

    def test_os_cinco_ci_yaml_leem(self) -> None:
        for nome in (
            "thresholds",
            "licenses",
            "secrets-allow",
            "waivers",
            "refs-allow",
        ):
            with self.subTest(ficheiro=nome):
                d = kamba_yaml.load_file(CI / f"{nome}.yaml")
                self.assertEqual(d.get("version"), 1, "todos tem `version: 1`")

    def test_a_blocklist_do_kam_001_continua_a_ler(self) -> None:
        """A migracao do `yamlmini` para este leitor nao pode mudar o resultado."""
        d = kamba_yaml.load_file(ROOT / "tools" / "blocklist.yaml")
        self.assertEqual(d["version"], 1)
        # 10 entradas: 7 itens do ticket mais 3 variantes de imagem
        # (`langgraph-api`, `langgenius`, `n8nio`) acrescentadas pela revisao.
        self.assertEqual(len(d["entries"]), 10)
        for entrada in d["entries"]:
            self.assertIn("name", entrada)
            self.assertIn("adr", entrada)

    def test_todos_os_ficheiros_reais_se_leem(self) -> None:
        """Nenhuma recusa nova sobre os ficheiros do repositorio.

        O risco das recusas que o KAM-136 acrescentou e recusarem **de mais**.
        Este teste e a guarda: descobre os ficheiros por *glob*, para que um
        ficheiro de configuracao novo entre aqui sem ninguem se lembrar.
        """
        for caminho in _ficheiros_reais():
            with self.subTest(ficheiro=caminho.relative_to(ROOT).as_posix()):
                self.assertIsInstance(kamba_yaml.load_file(caminho), dict)

    def test_nenhum_item_tem_uma_chave_so_com_um_texto_que_parece_chaves(self) -> None:
        """Canario do caso 1 do KAM-136, sobre os ficheiros reais.

        A assinatura do defeito era um item de lista com **uma** chave cujo
        valor e um texto longo que contem `': '` — as chaves engolidas.

        **Nao e um discriminador hoje, e nao se deve ler como tal.** A revisao
        adversarial mediu-o: com o leitor defeituoso, sobre estes ficheiros,
        este canario tambem passa — porque nenhum deles usa a forma do caso 1
        (`- razao: >-` tem zero ocorrencias nos 22). Quem distingue os dois
        estados do mundo e o `TestEquivalenciaAntesEDepois` e os testes de
        `TestCaso1DoKam136`. Isto fica como guarda para o dia em que um
        ficheiro real **ganhar** a forma: ai passa a discriminar.
        """
        suspeitos = []
        for caminho in _ficheiros_reais():
            dados = kamba_yaml.load_file(caminho)
            for onde, valor in _mapas(dados, caminho.relative_to(ROOT).as_posix()):
                if len(valor) != 1:
                    continue
                (unica,) = valor.values()
                if isinstance(unica, str) and ": " in unica and len(unica) > 60:
                    suspeitos.append(f"{onde}: {unica[:80]!r}")
        self.assertEqual(suspeitos, [], "item com uma chave e um texto que parece conter chaves")

    def test_thresholds_tem_a_forma_que_o_gate_4_espera(self) -> None:
        d = kamba_yaml.load_file(CI / "thresholds.yaml")
        nomes = [e["nome"] for e in d["estratos"]]
        self.assertEqual(nomes, ["critico", "restante"])
        self.assertEqual(d["estratos"][0]["minimo_linhas"], 90)
        self.assertEqual(d["estratos"][1]["minimo_linhas"], 75)
        for estrato in d["estratos"]:
            self.assertTrue(estrato["padroes"], "cada estrato tem padroes")
            self.assertGreater(len(estrato["razao"]), 20, "cada estrato diz porque existe")


class TestCaso1DoKam136(unittest.TestCase):
    """`>-` como **primeira** chave de um item de lista.

    Antes, a dobra recebia `indentacao_chave - 1` como indentacao do pai, e por
    isso consumia as linhas que estavam ao nivel das chaves seguintes do mesmo
    item: o item saia com uma chave e um `razao` que continha o texto **e** as
    outras chaves. Sem erro. A escolha do ticket foi **ler correctamente** e nao
    recusar, porque o defeito era a indentacao passada e nao uma regra em falta
    — a maquina de dobra ja existia e ja estava certa na posicao de mapa.
    """

    def test_as_chaves_seguintes_estao_todas_presentes(self) -> None:
        d = load(
            "areas:\n"
            "  - razao: >-\n"
            "      texto longo que continua\n"
            "      na linha seguinte\n"
            "    caminho: ci/x.yaml\n"
            "    obrigatorio: true\n"
        )
        self.assertEqual(
            d["areas"],
            [
                {
                    "razao": "texto longo que continua na linha seguinte",
                    "caminho": "ci/x.yaml",
                    "obrigatorio": True,
                }
            ],
        )

    def test_a_forma_que_os_ficheiros_reais_usam(self) -> None:
        """`razao: >-` seguido de mais chaves, com `razao` em segundo lugar.

        E a forma de `ci/licenses.yaml`, `ci/refs-allow.yaml`,
        `ci/secrets-allow.yaml` e `ci/waivers.yaml` na maioria das entradas.
        """
        d = load(
            "excepcoes:\n"
            "  - ficheiro: docs/ci.md\n"
            "    token: KAM-136\n"
            "    razao: >-\n"
            "      Duas passagens citam o ID como exemplo\n"
            "      e nao como referencia.\n"
            "  - ficheiro: outro.md\n"
            "    token: ADR-001\n"
            "    razao: Uma linha so.\n"
        )
        self.assertEqual(
            d["excepcoes"],
            [
                {
                    "ficheiro": "docs/ci.md",
                    "token": "KAM-136",
                    "razao": "Duas passagens citam o ID como exemplo e nao como referencia.",
                },
                {"ficheiro": "outro.md", "token": "ADR-001", "razao": "Uma linha so."},
            ],
        )

    def test_dobrado_como_primeira_chave_com_bloco_depois(self) -> None:
        d = load(
            "areas:\n"
            "  - razao: >-\n"
            "      uma razao\n"
            "    classes:\n"
            "      - a\n"
            "      - b\n"
        )
        self.assertEqual(d["areas"], [{"razao": "uma razao", "classes": ["a", "b"]}])

    def test_bloco_como_primeira_chave_do_item(self) -> None:
        """A forma de `ci/canon-lint.yaml` §197: `- colunas:` e uma lista, e
        depois mais duas chaves do mesmo item. E a vizinha do caso 1 — a
        primeira chave do item cujo valor nao esta na linha do `-`."""
        d = load(
            "cruzadas:\n"
            "  - colunas:\n"
            "      - provider\n"
            "      - referencia\n"
            "    seccao: \"3.4\"\n"
            "    conceito: \"Unicidade do ledger\"\n"
        )
        self.assertEqual(
            d["cruzadas"],
            [
                {
                    "colunas": ["provider", "referencia"],
                    "seccao": "3.4",
                    "conceito": "Unicidade do ledger",
                }
            ],
        )

    def test_so_o_barra_menos_se_aceita(self) -> None:
        """`>` e `>+` guardam a linha final; este leitor nao a preserva."""
        moldes = {
            "em posicao de mapa": "razao: {}\n  texto\n",
            "como primeira chave de um item": "l:\n  - razao: {}\n      texto\n",
        }
        for indicador in (">", ">+", "|", "|-", "|+"):
            for posicao, molde in moldes.items():
                with self.subTest(indicador=indicador, posicao=posicao):
                    with self.assertRaises(YamlSubsetError):
                        load(molde.format(indicador))

    def test_a_recusa_do_indicador_nomeia_o_ficheiro_e_a_linha(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "exemplo.yaml"
            caminho.write_text("version: 1\nrazao: >\n  texto\n", encoding="utf-8")
            with self.assertRaises(YamlSubsetError) as capturado:
                kamba_yaml.load_file(caminho)
        mensagem = str(capturado.exception)
        self.assertIn("exemplo.yaml", mensagem)
        self.assertIn("linha 2", mensagem)

    def test_o_dobrado_dentro_de_um_escalar_nao_apanha_a_chave_irma(self) -> None:
        """Regressao directa: a chave irma nao pode acabar dentro do texto."""
        d = load("l:\n  - razao: >-\n      a\n    outra: 2\n")
        self.assertNotIn("outra", d["l"][0]["razao"])
        self.assertEqual(d["l"][0]["outra"], 2)


class TestCaso2DoKam136(unittest.TestCase):
    """Item de lista nao citado que contem `:`.

    Antes, `- https://x` dava `{"https": "//x"}`. O YAML exige `:` seguido de
    espaco ou fim de linha para separar chave de valor; o `_CHAVE` nao o exigia.
    A escolha foi **ler como cadeia** — que e o que o YAML diz e o que o autor
    quis — e nao recusar: nenhuma outra forma substitui a cadeia sem aspas.
    """

    def test_url_num_item_de_lista_e_cadeia(self) -> None:
        self.assertEqual(
            load("destinos:\n  - https://graph.facebook.com\n  - http://localhost:5432\n"),
            {"destinos": ["https://graph.facebook.com", "http://localhost:5432"]},
        )

    def test_caminho_com_letra_de_unidade_e_cadeia(self) -> None:
        self.assertEqual(load("areas:\n  - C:/Jimy/Ideias\n"), {"areas": ["C:/Jimy/Ideias"]})

    def test_item_que_e_mesmo_um_mapa_continua_a_ser_mapa(self) -> None:
        self.assertEqual(load("l:\n  - chave: valor\n"), {"l": [{"chave": "valor"}]})

    def test_chave_sem_espaco_depois_dos_dois_pontos_e_recusada(self) -> None:
        """Em YAML, `chave:valor` e a cadeia `'chave:valor'`, nao um mapa."""
        with self.assertRaises(YamlSubsetError):
            load("chave:valor\n")

    def test_item_de_lista_sem_espaco_e_cadeia(self) -> None:
        self.assertEqual(load("l:\n  - chave:valor\n"), {"l": ["chave:valor"]})


class TestVarreduraDaMesmaClasse(unittest.TestCase):
    """Os casos varridos a procura de mais leituras silenciosas.

    O ticket pedia a varredura (ancoras, documentos multiplos, chaves
    duplicadas, tabulacoes, `null`/`~`, cadeias que comecam por `#`) e mais do
    que isso saiu dela. Cada caso tem aqui o seu resultado: **le bem** ou
    **recusa**. Nenhum le mal em silencio.
    """

    LEEM = {
        "nulo explicito": ("chave: null\n", {"chave": None}),
        "nulo com til": ("chave: ~\n", {"chave": None}),
        "cardinal dentro de aspas": ('chave: "a # b"\n', {"chave": "a # b"}),
        "lista vazia em fluxo": ("chave: []\n", {"chave": []}),
        "data nao e numero": ("criado_em: 2026-10-12\n", {"criado_em": "2026-10-12"}),
        "versao de tres partes": ("etiqueta: 1.83.0\n", {"etiqueta": "1.83.0"}),
        "etiqueta com sufixo": ("etiqueta: 0.8.7-pg18\n", {"etiqueta": "0.8.7-pg18"}),
        "inteiro com sinal": ("limiar: +5\n", {"limiar": 5}),
        "zero": ("limiar: 0\n", {"limiar": 0}),
        "algarismos nao ASCII sao texto": ("limiar: \u0661\u0662\u0663\n", {"limiar": "\u0661\u0662\u0663"}),
        "item citado com dois pontos": ('l:\n  - "a: b"\n', {"l": ["a: b"]}),
        "tabulacao depois dos dois pontos": ("chave:\tvalor\n", {"chave": "valor"}),
        "apostrofo em texto plano": ("razao: o 'valor que ficou\n", {"razao": "o 'valor que ficou"}),
        "apostrofo e comentario": (
            "razao: nao e so isto  # nota\n",
            {"razao": "nao e so isto"},
        ),
        "apostrofo no meio nao abre aspa": (
            # Antes, o `_sem_comentario` tratava este apostrofo como aspa aberta
            # e o `# nota` deixava de ser comentario: ficava colado ao valor.
            "razao: o 'valor que ficou  # nota\n",
            {"razao": "o 'valor que ficou"},
        ),
        "dobrado na posicao de mapa": (
            "razao: >-\n  um\n  dois\nirma: 1\n",
            {"razao": "um dois", "irma": 1},
        ),
        "comentario desindentado a seguir ao dobrado": (
            "razao: >-\n  um\n# nota\nirma: 1\n",
            {"razao": "um", "irma": 1},
        ),
        # --- achados da revisao adversarial (ANALISE-12), que passaram a ler bem
        "A4 aspa a meio de texto plano nao abre cadeia citada": (
            # Antes, qualquer `-` ou `:` anterior valia como inicio de escalar:
            # a aspa abria, o `#` ficava «dentro de aspas» e entrava no valor.
            'razao: a - "b # c"\n',
            {"razao": 'a - "b'},
        ),
        "A4 o mesmo com aspa simples": ("razao: a - 'b # c\n", {"razao": "a - 'b"}),
        "A5 CR sozinho e quebra de linha": ("a: 1\rb: 2\r", {"a": 1, "b": 2}),
        "A5 CR sozinho numa lista": ("l:\r  - um\r  - dois\r", {"l": ["um", "dois"]}),
        "A7 chave citada com apostrofo dentro": ("\"a'\": 1\n", {"a'": 1}),
        "A7 chave que e duas aspas simples": ("\"''\": 1\n", {"''": 1}),
        "B1 BOM no inicio do ficheiro": ("\ufeffversion: 1\na: 2\n", {"version": 1, "a": 2}),
        "B2 marcador de um documento": ("---\nversion: 1\n", {"version": 1}),
        "B2 marcador com comentario": ("--- # doc\nversion: 1\n", {"version": 1}),
        "B4 `---` indentado e conteudo": ("razao: >-\n  ---\n", {"razao": "---"}),
        "B4 `...` indentado e conteudo": ("razao: >-\n  ...\n", {"razao": "..."}),
        "B7 lista vazia com espaco dentro": ("a: [ ]\n", {"a": []}),
        # Cadeias que comecam por `#` — o ticket nomeia-as na varredura. Com
        # aspas, leem-se; sem aspas, o `#` e comentario (como em YAML) e o que
        # sobra e recusado (ver `RECUSAM`).
        "cadeia que comeca por `#`, com aspas duplas": ('chave: "#abc"\n', {"chave": "#abc"}),
        "cadeia que comeca por `#`, com aspas simples": ("chave: '#abc'\n", {"chave": "#abc"}),
        "item de lista que comeca por `#`, citado": ('l:\n  - "#abc"\n', {"l": ["#abc"]}),
        "`#` sem espaco antes nao e comentario": ("chave: a#b\n", {"chave": "a#b"}),
    }

    RECUSAM = {
        "ancora": "chave: &a valor\n",
        "alias": "a: &x 1\nb: *x\n",
        "ancora em item de lista": "l:\n  - &a valor\n",
        "merge key": "a:\n  <<: valor\n",
        "mapa em fluxo": "chave: {a: 1}\n",
        "mapa vazio em fluxo": "chave: {}\n",
        "lista em fluxo com conteudo": "chave: [a, b]\n",
        "tag": "chave: !!str 1\n",
        "directiva": "%YAML 1.2\nchave: valor\n",
        # Dois documentos a serio. O `---\na: 1\n` sozinho e **um** documento com
        # marcador e passa a ler-se (ver `LEEM`); estava mal rotulado aqui.
        "documentos multiplos": "---\na: 1\n---\nb: 2\n",
        "segundo marcador de documento": "a: 1\n---\nb: 2\n",
        "fim de documento": "a: 1\n...\n",
        "tabulacao na indentacao": "chave:\n\t- item\n",
        "chave repetida": "a: 1\na: 2\n",
        "chave repetida em item": "l:\n  - a: 1\n    a: 2\n",
        "lista aninhada": "l:\n  - - a\n",
        "lista ao nivel da chave": "a:\n- x\n",
        "documento de topo que e lista": "- a\n- b\n",
        "aspa dupla aberta e nao fechada": 'razao: "abre e nao fecha\n',
        "aspa simples aberta e nao fechada": "razao: 'abre e nao fecha\n",
        "conteudo depois da aspa de fecho": 'razao: "a" extra\n',
        "duas partes citadas": 'razao: "a" "b"\n',
        "cardinal depois de aspa aberta": "razao: 'abre e nao fecha # nota\n",
        "decimal": "limiar: 1.5\n",
        "exponente": "limiar: 1e3\n",
        "hexadecimal": "limiar: 0x1f\n",
        "sublinhado de milhares": "limiar: 1_000\n",
        "infinito": "limiar: .inf\n",
        "nao numero": "limiar: .nan\n",
        "verdadeiro maiusculo": "activo: True\n",
        "falso maiusculo": "activo: FALSE\n",
        "sim": "activo: yes\n",
        "nao": "activo: no\n",
        "ligado": "activo: on\n",
        "desligado": "activo: off\n",
        "nulo maiusculo": "chave: NULL\n",
        "nulo do Python": "chave: None\n",
        "cardinal dentro de dobrado": "razao: >-\n  texto com # cardinal\n",
        "comentario ao nivel do dobrado": "razao: >-\n  um\n  # nota\nirma: 1\n",
        "linha vazia dentro de dobrado": "razao: >-\n  um\n\n  dois\n",
        "indentacao irregular dentro de dobrado": "razao: >-\n  um\n   dois\n",
        "dobrado sem conteudo": "chave: >-\n",
        # --- achados da revisao adversarial (ANALISE-12), que passaram a recusa
        "A1 comentario como primeira linha do dobrado": (
            "waivers:\n  - gate: 11\n    razao: >-\n      # ver ADR-014\n"
            "      A licenca e AGPL mas corre em separado.\n    autor: nome\n"
        ),
        "A1 linha vazia como primeira linha do dobrado": "razao: >-\n\n  um\n",
        "A1 dois comentarios antes do conteudo": "razao: >-\n  # a\n  # b\n  um\n",
        "A1 linha vazia antes do conteudo, em item": "l:\n  - razao: >-\n\n      um\n    outra: 2\n",
        "A1 primeira linha do bloco mais indentada": "razao: >-\n      # muito\n  um\n",
        "A2 octal do YAML 1.1 (017)": "modo: 017\n",
        "A2 octal do YAML 1.1 (0644)": "modo: 0644\n",
        "A2 zero a esquerda com sinal": "modo: -010\n",
        "A2 zero a esquerda que nao e octal": "modo: 008\n",
        "A2 inteiro com zeros a esquerda": "limiar: 007\n",
        "A3 sexagesimal do YAML 1.1": "limite: 1:30\n",
        "A3 sexagesimal de tres partes": "limite: 10:20:30\n",
        # Sem `: ` no texto: se a recusa das quebras ambiguas desaparecer, estes
        # casos **leem-se** (como uma cadeia com o caractere dentro) em vez de
        # ca\u00edrem noutra recusa qualquer. A prova por mutacao apanhou a primeira
        # versao destes tres a passar pela razao errada, pela regra do `: `.
        "A5 NEL como quebra de linha": "lista:\n  - um\x85  - dois\n",
        "A5 U+2028 como quebra de linha": "lista:\n  - um\u2028  - dois\n",
        "A5 U+2029 como quebra de linha": "lista:\n  - um\u2029  - dois\n",
        "A8 NUL no valor": "chave: a\x00b\n",
        "A8 ESC no valor": "chave: a\x1bb\n",
        "A8 form feed na indentacao": "\x0cchave: valor\n",
        "A9 valor plano com dois pontos": "razao: a: b\n",
        "A9 valor plano que acaba em dois pontos": "razao: nota:\n",
        "B3 aspa simples duplicada": "l:\n  - razao: 'o ''valor'' certo'\n",
        "B3 aspa dupla escapada": 'razao: "o \\"valor\\" certo"\n',
        "cadeia que comeca por `#` sem aspas": "chave: #abc\n",
        "item de lista que comeca por `#` sem aspas": "l:\n  - #abc\n",
    }

    def test_os_casos_que_leem_bem(self) -> None:
        for nome, (texto, esperado) in self.LEEM.items():
            with self.subTest(caso=nome):
                self.assertEqual(load(texto), esperado)

    def test_os_casos_que_recusam(self) -> None:
        for nome, texto in self.RECUSAM.items():
            with self.subTest(caso=nome):
                with self.assertRaises(YamlSubsetError, msg=f"devia recusar: {nome}"):
                    load(texto)

    def test_a_recusa_das_quebras_ambiguas_diz_qual_e(self) -> None:
        """A mensagem nomeia o caractere, e e por ela que se sabe que foi esta
        regra a recusar e nao outra."""
        for texto, nome in (
            ("lista:\n  - um\x85  - dois\n", "NEL"),
            ("lista:\n  - um   - dois\n", "U+2028"),
            ("lista:\n  - um   - dois\n", "U+2029"),
        ):
            with self.subTest(caractere=nome):
                with self.assertRaises(YamlSubsetError) as capturado:
                    load(texto)
                self.assertIn(nome, str(capturado.exception))

    def test_ficheiro_que_nao_e_utf8_e_erro_de_configuracao(self) -> None:
        """Sem isto, um `UnicodeDecodeError` saia do modulo e o gate morria
        com *traceback* e codigo 1 em vez de erro de configuracao (codigo 2)."""
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "latin1.yaml"
            caminho.write_bytes(b"chave: valor\nrazao: caf\xe9\n")
            with self.assertRaises(YamlSubsetError) as capturado:
                kamba_yaml.load_file(caminho)
        self.assertIn("latin1.yaml", str(capturado.exception))


class TestRecusaEhErroDeConfiguracao(unittest.TestCase):
    """Uma recusa do leitor sai com **2**, nao com 1.

    A diferenca nao e cosmetica: 1 e «encontrei achados», 2 e «nao consigo
    verificar». Um ficheiro que o leitor recusa nao produziu achado nenhum, e
    dizer que produziu manda quem le o registo procurar o achado errado.

    Dos dez consumidores do modulo, o `ci_waivers` era o unico que devolvia 1;
    passou a ter `ConfiguracaoIlegivel`. Aqui provam-se por execucao os dois
    cuja configuracao e **um** ficheiro; os outros oito estao no quadro de
    `docs/evidencia/KAM-136.md`, com a linha do `return 2`.
    """

    MAU = "waivers: {isto nao e do subconjunto}\n"

    def test_ci_waivers_devolve_2(self) -> None:
        import ci_waivers

        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "waivers.yaml").write_text(
                "version: 1\n" + self.MAU, encoding="utf-8"
            )
            self.assertEqual(ci_waivers.main(["--root", str(raiz)]), 2)

    def test_ci_waivers_continua_a_devolver_1_para_um_achado(self) -> None:
        """Um *waiver* expirado **e** um achado: continua a ser 1."""
        import ci_waivers

        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "waivers.yaml").write_text(
                "version: 1\n"
                "waivers:\n"
                "  - gate: 5\n"
                "    alvo: pipeline\n"
                "    adr_ou_aprovacao: aprovacao:fundador@2020-01-01\n"
                "    autor: fundador\n"
                "    razao: Um waiver que expirou ha muito tempo, com razao longa.\n"
                "    criado_em: 2020-01-01\n"
                "    expira_em: 2020-01-02\n",
                encoding="utf-8",
            )
            self.assertEqual(ci_waivers.main(["--root", str(raiz)]), 1)

    def test_coverage_gate_devolve_2(self) -> None:
        import coverage_gate

        with tempfile.TemporaryDirectory() as pasta:
            raiz = Path(pasta)
            (raiz / "ci").mkdir()
            (raiz / "ci" / "thresholds.yaml").write_text(
                "version: 1\nestratos: {a: 1}\n", encoding="utf-8"
            )
            self.assertEqual(coverage_gate.main(["--root", str(raiz)]), 2)


class TestEquivalenciaAntesEDepois(unittest.TestCase):
    """A estrutura lida de cada ficheiro real, antes e depois, campo a campo.

    O oraculo e `leitor_antes_do_kam136`, a copia congelada do modulo tal como
    estava em `origin/main`. Um retrato em JSON envelhecia a cada edicao de um
    `ci/*.yaml`; um algoritmo nao envelhece.
    """

    #: Ficheiro -> razao, para quando uma leitura mudar **de proposito**. O DoD
    #: do KAM-136 pede 2 revisores nesse caso. Hoje esta vazio: nenhuma leitura
    #: mudou.
    _DIVERGENCIAS_ACEITES: dict[str, str] = {}

    def test_cada_ficheiro_real_le_igual(self) -> None:
        comparados = campos = 0
        vistos: set[str] = set()
        for caminho in _ficheiros_reais():
            relativo = caminho.relative_to(ROOT).as_posix()
            with self.subTest(ficheiro=relativo):
                antes = _ler_ou_recusa(leitor_antes_do_kam136, caminho)
                depois = _ler_ou_recusa(kamba_yaml, caminho)
                if relativo in self._DIVERGENCIAS_ACEITES:
                    continue
                folhas_antes = dict(_folhas(antes))
                folhas_depois = dict(_folhas(depois))
                self.assertEqual(
                    folhas_antes,
                    folhas_depois,
                    f"{relativo}: a leitura mudou de resultado — o DoD do KAM-136 "
                    "pede 2 revisores, e a razao vai para _DIVERGENCIAS_ACEITES",
                )
                comparados += 1
                campos += len(folhas_antes)
                vistos.add(relativo)
        self.assertGreaterEqual(comparados, 20, "a descoberta de ficheiros parou de funcionar")
        self.assertGreater(campos, 2000, "comparou poucos campos para a dimensao destes ficheiros")
        # A guarda de cima e satisfeita pelo `canon/dicionario.yaml` sozinho
        # (1 423 campos). Esta exige que os ficheiros que o ticket nomeia
        # estejam **mesmo** na comparacao.
        for nome in ("ci/thresholds.yaml", "ci/waivers.yaml", "ci/licenses.yaml",
                     "ci/refs-allow.yaml", "ci/secrets-allow.yaml", "ci/canon-lint.yaml"):
            self.assertIn(nome, vistos, f"{nome} ficou fora da comparacao de equivalencia")

    def test_o_leitor_antigo_ainda_tem_os_dois_defeitos(self) -> None:
        """Se a copia congelada deixar de ter os defeitos, deixou de ser oraculo."""
        engolido = leitor_antes_do_kam136.load(
            "l:\n  - razao: >-\n      um\n    outra: 2\n"
        )
        self.assertEqual(list(engolido["l"][0]), ["razao"], "o caso 1 devia estar presente")
        virou_mapa = leitor_antes_do_kam136.load("l:\n  - https://x\n")
        self.assertEqual(virou_mapa["l"], [{"https": "//x"}], "o caso 2 devia estar presente")


#: Ficheiros de configuracao que o `kamba_yaml` le. Descobertos por *glob*: um
#: ficheiro novo entra nos testes sem ninguem se lembrar dele.
_PADROES_REAIS = (
    "ci/*.yaml",
    "ci/supply-chain/*.yaml",
    "canon/*.yaml",
    "infra/egress/*.yaml",
    "services/*/egress.yaml",
    "tools/blocklist.yaml",
)


def _ficheiros_reais() -> list[Path]:
    encontrados: list[Path] = []
    for padrao in _PADROES_REAIS:
        encontrados.extend(ROOT.glob(padrao))
    return sorted(set(encontrados))


def _ler_ou_recusa(modulo, caminho: Path):
    try:
        return modulo.load_file(caminho)
    except modulo.YamlSubsetError as excepcao:
        return f"RECUSA: {excepcao}"


def _folhas(valor, caminho: tuple = ()):
    """Achata a estrutura em pares caminho -> valor, para comparar campo a campo.

    O caminho e um **tuplo**, e nao um texto: com `f"{prefixo}.{chave}"`, os
    documentos `{"a": {"b": 1}}` e `{"a.b": 1}` achatavam para a mesma chave e
    a comparacao nao os distinguia. E um mapa e uma lista vazios produzem um par
    proprio — sem isso, um mapa que passasse a `{}` era invisivel.
    """
    if isinstance(valor, dict):
        if not valor:
            yield caminho, "<mapa vazio>"
        for chave, filho in valor.items():
            yield from _folhas(filho, caminho + (("chave", chave),))
    elif isinstance(valor, list):
        if not valor:
            yield caminho, "<lista vazia>"
        for indice, filho in enumerate(valor):
            yield from _folhas(filho, caminho + (("indice", indice),))
    else:
        yield caminho, valor


def _mapas(valor, prefixo: str = ""):
    """Todos os mapas da estrutura, com o caminho onde estao."""
    if isinstance(valor, dict):
        yield prefixo, valor
        for chave, filho in valor.items():
            yield from _mapas(filho, f"{prefixo}.{chave}")
    elif isinstance(valor, list):
        for indice, filho in enumerate(valor):
            yield from _mapas(filho, f"{prefixo}[{indice}]")


if __name__ == "__main__":
    unittest.main()


class TestExigirChaves(unittest.TestCase):
    """A recusa de chaves desconhecidas (KAM-134).

    Vive aqui, com o leitor, porque e dele que os quinze leitores de
    `ci/*.yaml` a passaram a importar. Os testes por leitor — que o conjunto
    declarado e o certo, e que uma gralha numa chave existente falha — ficam
    com cada leitor.
    """

    def test_um_mapa_conforme_passa(self) -> None:
        kamba_yaml.exigir_chaves({"version": 1, "areas": []}, {"version", "areas"}, "x.yaml")

    def test_um_mapa_com_menos_chaves_passa(self) -> None:
        """O conjunto e um tecto, nao uma obrigacao: os campos obrigatorios
        verificam-se a parte, e com mensagem propria."""
        kamba_yaml.exigir_chaves({"version": 1}, {"version", "areas"}, "x.yaml")

    def test_chave_desconhecida_levanta(self) -> None:
        with self.assertRaises(YamlSubsetError) as capturado:
            kamba_yaml.exigir_chaves({"versao": 1}, {"version"}, "x.yaml")
        self.assertIn("x.yaml", str(capturado.exception))
        self.assertIn("versao", str(capturado.exception))

    def test_a_mensagem_diz_o_conjunto_aceite(self) -> None:
        """O criterio do KAM-134 pede o ficheiro, a chave **e** as aceites.

        A implementacao de que esta saiu — a do `canon_lint`, desde o KAM-111 —
        dizia so as chaves a mais. Quem acrescentou a chave precisa de saber o
        que podia ter escrito, e a lista e curta.
        """
        with self.assertRaises(YamlSubsetError) as capturado:
            kamba_yaml.exigir_chaves({"xpto": 1}, {"areas", "version"}, "x.yaml")
        mensagem = str(capturado.exception)
        self.assertIn("As aceites aqui sao: areas, version", mensagem)

    def test_varias_chaves_saem_ordenadas(self) -> None:
        with self.assertRaises(YamlSubsetError) as capturado:
            kamba_yaml.exigir_chaves({"zeta": 1, "alfa": 2}, set(), "x.yaml")
        self.assertIn("['alfa', 'zeta']", str(capturado.exception))

    def test_o_erro_e_parametro(self) -> None:
        """Cada leitor tem a sua taxonomia e o seu mapeamento para codigo de
        saida. Forcar uma excepcao unica partia os `except` que ja existem."""

        class Proprio(ValueError):
            pass

        with self.assertRaises(Proprio):
            kamba_yaml.exigir_chaves({"xpto": 1}, set(), "x.yaml", erro=Proprio)

    def test_o_que_nao_e_mapa_levanta(self) -> None:
        for valor in ([], "texto", None, 3):
            with self.subTest(valor=valor):
                with self.assertRaises(YamlSubsetError) as capturado:
                    kamba_yaml.exigir_chaves(valor, {"a"}, "x.yaml")
                self.assertIn("tem de ser um mapa", str(capturado.exception))


class TestOsQuinzeLeitoresDeclaramOQueLeem(unittest.TestCase):
    """Nenhuma chave activa em `ci/*.yaml` fica sem leitor (KAM-134).

    E o inverso do teste de cima: la prova-se que a recusa funciona, aqui que
    ela esta **ligada** em todo o lado e que os ficheiros reais a passam. Um
    mecanismo partilhado que ninguem chama nao vale nada.
    """

    def test_todos_os_ficheiros_de_ci_sao_lidos_por_alguem(self) -> None:
        import ci_waivers
        from contract_diff.pii import ler_allowlist
        from coverage_gate import ler_limiares
        from lint_backlog.cli import ler_declaracoes as _backlog
        from lint_contagens.cli import ler_declaracoes as _contagens
        from lint_handoff.cli import ler_excepcoes as _handoff
        from lint_refs.cli import Excepcoes
        from sbom.cli import ler_politica
        from scan_secrets.scanner import Permissoes
        from supply_chain.imagens import ler_inventario
        from supply_chain.licencas import ler_registo

        # Cada um le o ficheiro real e nao levanta. Se uma chave do ficheiro
        # nao estiver no conjunto declarado, isto fica vermelho — que e
        # exactamente o que se quer que aconteca a quem acrescentar uma.
        ler_limiares(ROOT)
        ler_politica(ROOT)
        Excepcoes.ler(ROOT)
        ci_waivers.ler(ROOT)
        Permissoes.ler(ROOT)
        _handoff(ROOT)
        _contagens(ROOT)
        _backlog(ROOT)
        ler_allowlist(ROOT)
        ler_inventario(ROOT)
        ler_registo(ROOT)

    #: Para cada `ci/*.yaml`, o conjunto que o seu leitor declara. A chave e o
    #: caminho relativo a raiz, e e por **descoberta** que se verifica que esta
    #: completo — ver o teste a seguir. Uma lista a mao nunca apanharia um
    #: ficheiro novo, que e metade do que o criterio 2 do KAM-134 pede.
    @staticmethod
    def conjuntos_por_ficheiro() -> dict[str, set[str]]:
        import ci_waivers
        from canon_lint import documentos as canon_documentos
        from canon_lint.dicionario import CHAVES_DA_POLITICA
        from contract_diff import pii
        from coverage_gate import CHAVES as chaves_thresholds
        from lint_backlog.cli import CHAVES as chaves_backlog
        from lint_contagens import cli as contagens
        from lint_handoff import cli as handoff
        from lint_refs.cli import CHAVES as chaves_refs
        from sbom.cli import CHAVES_DE_LICENCAS
        from scan_secrets import scanner
        from supply_chain import imagens, licencas

        return {
            "ci/thresholds.yaml": chaves_thresholds,
            "ci/licenses.yaml": CHAVES_DE_LICENCAS,
            "ci/refs-allow.yaml": chaves_refs,
            "ci/waivers.yaml": ci_waivers._CHAVES,
            "ci/secrets-allow.yaml": scanner._CHAVES,
            "ci/handoff-allow.yaml": handoff._CHAVES,
            "ci/contagens-allow.yaml": contagens._CHAVES,
            "ci/backlog-allow.yaml": chaves_backlog,
            "ci/contratos-allow.yaml": pii._CHAVES,
            "ci/canon-allow.yaml": canon_documentos.CHAVES_DE_TOPO,
            "ci/canon-lint.yaml": CHAVES_DA_POLITICA,
            "ci/rls_exceptions.yaml": {"version", "excepcoes"},
            "ci/secdef_allowlist.yaml": {"version", "funcoes"},
            "ci/supply-chain/imagens.yaml": imagens._CHAVES_TOPO,
            "ci/supply-chain/licencas.yaml": licencas._CHAVES_TOPO,
        }

    def test_nenhuma_chave_de_topo_fica_por_declarar(self) -> None:
        """A conta que a *discovery* fez a mao, agora por maquina.

        Para cada `ci/*.yaml`, as chaves de topo do ficheiro tem de estar no
        conjunto que o seu leitor declara. E assim que uma chave como a
        `arredondamento` — que esteve dois tickets no ficheiro sem ninguem a
        ler — deixa de poder voltar.
        """
        conjuntos = self.conjuntos_por_ficheiro()
        for nome, aceites in conjuntos.items():
            with self.subTest(ficheiro=nome):
                dados = kamba_yaml.load_file(ROOT / nome)
                a_mais = sorted(set(dados) - aceites)
                self.assertEqual(a_mais, [], f"{nome}: chave(s) sem leitor")

    def test_um_ci_yaml_novo_nao_passa_despercebido(self) -> None:
        """A outra metade do criterio 2, e a que a primeira versao nao tinha.

        «Toda a chave activa nos `ci/*.yaml` depois deste ticket tem um
        leitor.» Com a lista a mao, um ficheiro **novo** nao tinha nada que o
        forcasse a ter leitor — a classe que o ticket fecha reabria no proximo
        ficheiro. O padrao certo ja estava neste ficheiro, no
        `test_todos_os_ficheiros_reais_se_leem`: descobrir por *glob*.
        """
        descobertos = {
            caminho.relative_to(ROOT).as_posix()
            for padrao in ("ci/*.yaml", "ci/supply-chain/*.yaml")
            for caminho in ROOT.glob(padrao)
        }
        declarados = set(self.conjuntos_por_ficheiro())
        sem_leitor = sorted(descobertos - declarados)
        self.assertEqual(
            sem_leitor, [],
            "ficheiro(s) de configuracao sem leitor declarado. Ou ganham um "
            "leitor, ou nao pertencem a `ci/`.",
        )
        # E o inverso: um leitor declarado cujo ficheiro desapareceu e uma
        # entrada morta que da falsa seguranca a este teste.
        self.assertEqual(sorted(declarados - descobertos), [])


class TestUmaGralhaEhApanhada(unittest.TestCase):
    """«`padrões` por `padroes`, `permitidos` por `permitidas`» (KAM-134).

    E a forma mais provavel de a classe reaparecer, e por isso tem teste
    proprio: o ficheiro fica com uma chave que ninguem le, o gate comporta-se
    como se ela nao existisse, e quem a escreveu conclui que o gate esta
    avariado.
    """

    def escrever(self, nome: str, texto: str) -> Path:
        pasta = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (pasta / "ci").mkdir()
        (pasta / "ci" / nome).write_text(texto, encoding="utf-8")
        return pasta

    def test_thresholds_com_padroes_mal_escrito(self) -> None:
        from coverage_gate import ConfiguracaoInvalida, ler_limiares

        raiz = self.escrever(
            "thresholds.yaml",
            "version: 1\n"
            "estratos:\n"
            "  - nome: restante\n"
            "    minimo_linhas: 75\n"
            "    razao: uma razao com comprimento suficiente para passar\n"
            "    padrao:\n"
            "      - 'tools/**'\n",
        )
        with self.assertRaises(ConfiguracaoInvalida) as capturado:
            ler_limiares(raiz)
        self.assertIn("padrao", str(capturado.exception))
        self.assertIn("padroes", str(capturado.exception))

    def test_licenses_com_permitidos_em_vez_de_permitidas(self) -> None:
        from sbom.cli import ConfiguracaoInvalida, ler_politica

        raiz = self.escrever("licenses.yaml", "version: 1\npermitidos:\n  - MIT\n")
        with self.assertRaises(ConfiguracaoInvalida) as capturado:
            ler_politica(raiz)
        self.assertIn("permitidos", str(capturado.exception))

    def test_waivers_com_a_regra_que_ninguem_lia(self) -> None:
        """A chave mais perigosa das que o KAM-134 fechou.

        Quem escrevia `regra: licenca` acreditava ter dispensado so a licenca,
        e tinha dispensado tambem a vulnerabilidade. Agora da erro.
        """
        import ci_waivers

        raiz = self.escrever(
            "waivers.yaml",
            "version: 1\n"
            "waivers:\n"
            "  - gate: 11\n"
            "    regra: licenca\n"
            "    alvo: 'pkg:npm/x@1.0.0'\n"
            "    adr_ou_aprovacao: ADR-014\n"
            "    autor: alguem\n"
            "    razao: uma razao suficientemente longa para sobreviver ao autor\n"
            "    expira_em: 2099-01-01\n",
        )
        with self.assertRaises(ci_waivers.ConfiguracaoIlegivel) as capturado:
            ci_waivers.ler(raiz)
        self.assertIn("regra", str(capturado.exception))

    def test_refs_allow_com_a_serie_d_que_saiu(self) -> None:
        from lint_refs.cli import Excepcoes, FonteCanonicaAusente

        # O valor nao interessa ao teste, e escrever um prazo real aqui fazia
        # o proprio `lint_refs` avisar sobre esta *fixture* — a verificacao
        # cruzada a funcionar, e boa razao para nao o escrever.
        raiz = self.escrever(
            "refs-allow.yaml",
            "version: 1\nserie_d:\n  prazos_conhecidos:\n    - qualquer\n",
        )
        with self.assertRaises(FonteCanonicaAusente) as capturado:
            Excepcoes.ler(raiz)
        self.assertIn("serie_d", str(capturado.exception))

    def test_secrets_allow_com_chave_de_topo_inventada(self) -> None:
        """Este leitor ja recusava uma **classe** inventada e ignorava uma
        **chave** inventada. Eram o mesmo defeito visto de dois lados."""
        from scan_secrets.scanner import ConfiguracaoInvalida, Permissoes

        raiz = self.escrever(
            "secrets-allow.yaml", "version: 1\nplaceholders:\n  - xpto\n"
        )
        with self.assertRaises(ConfiguracaoInvalida) as capturado:
            Permissoes.ler(raiz)
        self.assertIn("placeholders", str(capturado.exception))

    def test_a_gralha_aninhada_tambem(self) -> None:
        """«A validacao tem de descer»: um validador so do primeiro nivel nao
        apanhava uma gralha dentro de um estrato nem dentro de um waiver."""
        from sbom.cli import ConfiguracaoInvalida, ler_politica

        raiz = self.escrever(
            "licenses.yaml",
            "version: 1\n"
            "permitidas:\n  - MIT\n"
            "negadas:\n  - prefixos: AGPL\n    razao: copyleft forte\n",
        )
        with self.assertRaises(ConfiguracaoInvalida) as capturado:
            ler_politica(raiz)
        self.assertIn("prefixos", str(capturado.exception))
        self.assertIn("negada 1", str(capturado.exception))


class TestCodigoDeSaidaDois(unittest.TestCase):
    """«A recusa distingue erro de configuracao de achado» (KAM-134).

    Codigo 2, nao 1. A frase do `lint_arch` que o ticket cita: «um ficheiro de
    bloqueio malformado nao pode parecer um repositorio limpo». Aqui corre-se
    o CLI, e nao a funcao de leitura: e o codigo de saida que o `make` ve.
    """

    def raiz_com(self, nome: str, texto: str) -> Path:
        pasta = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (pasta / "ci").mkdir()
        (pasta / "ci" / nome).write_text(texto, encoding="utf-8")
        return pasta

    def test_coverage_gate(self) -> None:
        import coverage_gate

        raiz = self.raiz_com("thresholds.yaml", "version: 1\nxpto: 1\n")
        self.assertEqual(coverage_gate.main(["--root", str(raiz)]), 2)

    def test_ci_waivers(self) -> None:
        import ci_waivers

        raiz = self.raiz_com("waivers.yaml", "version: 1\nwaivers: []\nxpto: 1\n")
        self.assertEqual(ci_waivers.main(["--root", str(raiz)]), 2)

    def test_ci_gate_reservado(self) -> None:
        """Este devolvia **1 para tudo** (KAM-134).

        O `ConfiguracaoIlegivel` e subclasse de `WaiverInvalido`, pelo que o
        `except` largo o apanhava primeiro — e com isso o trabalho do KAM-136,
        que separou configuracao de achado, perdia-se neste leitor.
        """
        import ci_gate_reservado

        raiz = self.raiz_com("waivers.yaml", "version: 1\nwaivers: []\nxpto: 1\n")
        codigo = ci_gate_reservado.main(
            ["--root", str(raiz), "--gate", "5", "--nome", "x", "--ticket", "KAM-003"]
        )
        self.assertEqual(codigo, 2)

    def test_um_waiver_expirado_continua_a_ser_achado_e_nao_configuracao(self) -> None:
        """O inverso, que importa tanto como o resto: a recusa nova nao pode
        engolir o que ja era achado."""
        import ci_waivers

        raiz = self.raiz_com(
            "waivers.yaml",
            "version: 1\n"
            "waivers:\n"
            "  - gate: 11\n"
            "    alvo: 'pkg:npm/x@1.0.0'\n"
            "    adr_ou_aprovacao: ADR-014\n"
            "    autor: alguem\n"
            "    razao: uma razao suficientemente longa para sobreviver ao autor\n"
            "    criado_em: 2019-12-20\n"
            "    expira_em: 2020-01-01\n",
        )
        self.assertEqual(ci_waivers.main(["--root", str(raiz)]), 1)
