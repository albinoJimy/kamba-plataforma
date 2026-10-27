"""O *lint* dos esquemas de tool expostos ao modelo (KAM-028, critero 3).

O critero 3 do bloco e o `docs/tecnica/08` §3.2 pedem a mesma coisa, e pedem-na
como *gate*: «Nenhum esquema de tool exposto ao modelo contem parametro
`tenant_id`, `merchant_id`, `seller` ou `account` (lint de CI, **falha o
build**)». O §3.2 acrescenta a segunda metade: «ou import do repositorio de
escrita fora da TLS».

Corre dentro do `lint_arch` e nao num *gate* proprio: o `lint_arch` ja corre no
*gate* 2 e no 11, e um *gate* novo era uma regra de bloqueio nova — que pede
dois revisores e que esta linha de trabalho nao abre.

## Le a **fonte** e nao importa nada

O `lint_arch` «depende apenas da biblioteca padrao, por desenho» (a sua propria
*docstring*), e isso aqui nao e uma limitacao: e o que faz este *lint* valer.
Importar os modelos para lhes perguntar os campos exigia o Pydantic instalado e
dava a resposta **do codigo a correr**; ler a fonte com o `ast` da a resposta do
codigo escrito, que e o que um PR traz. Um modelo que so construisse o campo
proibido em tempo de execucao escapava as duas, e por isso a camada tambem o
recusa ao construir a especificacao (`tls/especificacoes.py`) — as duas
verificacoes olham para a mesma regra por dois lados.

## O que conta como «esquema de tool exposto ao modelo»

Uma classe que herde de `BaseModel` num ficheiro dentro de um directorio `tls/`
de um servico. A convencao e estreita de proposito: dentro da ToolLayer, um
`BaseModel` **e** um esquema de argumentos — e o que o §6.1 passo 3 descreve —, e
alargar a varredura a todo o repositorio apanhava os modelos do registo
(`registo/esquema.py`), que leem `registry/*.yaml` e onde um `tenant_id` nao
chega a modelo nenhum.

Dois achados por classe, e nenhum e de estilo:

* **parametro proibido** — o campo esta no esquema que vai ao modelo, e um campo
  do esquema e um campo que o modelo pode preencher com o que o texto do cliente
  lhe disser (ADR-015, `08` §4.3);
* **sem `extra="forbid"`** — o passo 3 pede-o pelo nome, e sem ele um argumento
  a mais entra em silencio. O critero 2 do bloco mede-o: «argumento extra
  devolve `VALIDATION_ERROR`».

## A segunda metade: escrita no `platform` fora da TLS

«A TLS e a **unica** via de leitura e escrita dos agentes» (§6.1, ADR-015). O
que se verifica e o lado da escrita, que e o que tem consequencia: uma
instrucao `INSERT`, `UPDATE` ou `DELETE` contra o `platform` num modulo do AGR
fora de `tls/`.

**Nao se verifica a leitura**, e e deliberado: o `conversa.py` do KAM-025 le a
`conversations` e a `handoffs` para decidir se o turno entra no grafo, e isso e
a admissao do turno e nao um agente a ler dados de negocio. Uma regra que o
proibisse obrigava a uma excepcao no primeiro dia, e uma regra que nasce com
excepcao nao e a regra.

### E a escrita do plano de controlo, que o KAM-034 trouxe

A mesma distincao valeu pelo lado da escrita no dia em que houve uma: o
*compare-and-set* `waiting -> resumed` de `/internal/resume`, que o
`docs/tecnica/02` §11 regra 3 poe no AGR **por escrito** e que o dicionario
§3.15 ja tinha atribuido ao KAM-034. Nao e um agente a escrever: nao ha modelo
no caminho, o desfecho vem num corpo autenticado pelo `secret` do *agent bot* e
e um de tres valores de lista fechada.

O que a regra dizia — «nenhuma escrita no `platform` fora da TLS» — e mais
larga do que a regra que ela implementa — «a TLS e a unica via dos **agentes**»
—, e as duas davam o mesmo resultado so enquanto nao houvesse uma unica escrita
de plano de controlo. `ESCRITAS_DO_PLANO_DE_CONTROLO` e onde a palavra
«agentes» passa a contar, com **quatro** criterios por entrada e a chave em
`(ficheiro, tabela)` — nunca o ficheiro inteiro, para que um `UPDATE
platform.orders` na linha seguinte continue a morder. Ha um canario que o mede.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

#: Os quatro do dicionario §3.26. A mesma lista que o `registo/validar.py`
#: declara e que a `tls/especificacoes.py` aplica em execucao.
#:
#: Repetida aqui e nao importada **de proposito**: o `lint_arch` corre antes de
#: qualquer instalacao e sem os servicos no caminho de importacao, e um *lint*
#: que precisasse de importar o codigo que verifica chegava sempre tarde (a
#: razao esta na *docstring* do pacote). O que impede as duas copias de
#: divergirem e um teste que as confronta.
PARAMETROS_PROIBIDOS = ("tenant_id", "merchant_id", "seller", "account")

#: O nome do directorio que delimita a ToolLayer de um servico.
DIRECTORIO_DA_TLS = "tls"

#: Uma escrita SQL contra o `platform`. Procura-se o texto da instrucao e nao
#: uma chamada: o SQL vive em constantes de modulo (`SQL_ESCREVER`,
#: `SQL_PALAVRA_DA_CONVERSA`), que e a forma desta casa.
#:
#: **Aplica-se ao ficheiro inteiro e nao linha a linha.** O padrao atravessa
#: espaco em branco — `INSERT\s+INTO` — e o SQL desta casa esta em literais de
#: varias linhas: um `INSERT INTO` com a tabela na linha seguinte era invisivel
#: a uma varredura por linha. Apanhado pela revisao adversarial.
#: **O identificador pode vir entre aspas, e a primeira versao da captura
#: esqueceu-o.** O padrao era `platform\.` sem grupo e apanhava `UPDATE
#: platform."orders"`; passar a `platform\.(\w+)` para saber a **tabela** fez o
#: `\w+` nao casar a aspa, e com isso uma escrita com identificador citado
#: deixou de morder — uma regressao num *gate* de bloqueio, e para **todas** as
#: tabelas e nao so para a dispensada. Apanhado pela revisao adversarial do
#: KAM-034 (achado 4).
#:
#: O grupo 1 e a forma sem aspas e o grupo 2 a forma com aspas; o `_tabela_de`
#: junta-os. O verbo tambem se captura, porque a dispensa e por verbo.
ESCRITA_NO_PLATFORM = re.compile(
    r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+platform\.(?:(\w+)|\"([^\"]+)\")",
    re.IGNORECASE,
)


def _tabela_de(achado: re.Match[str]) -> str:
    """O nome da tabela, com ou sem aspas, em minusculas."""
    return (achado.group(2) or achado.group(3) or "").lower()


def _verbo_de(achado: re.Match[str]) -> str:
    """`insert`, `update` ou `delete`, normalizado."""
    return achado.group(1).split()[0].lower()

#: As escritas no `platform` que **nao** sao um agente a escrever, por
#: `(ficheiro, tabela)`.
#:
#: **A regra que o §6.1 escreve e «a TLS e a unica via de leitura e escrita dos
#: *agentes*», e esta lista e onde a palavra «agentes» passa a contar.** Ate ao
#: KAM-034 nao havia no AGR uma unica escrita no `platform` fora da TLS, pelo
#: que proibi-las todas e dizer «dos agentes» davam o mesmo resultado; deixaram
#: de dar. Esta e a mesma distincao que a *docstring* deste modulo ja fazia pelo
#: lado da leitura — «o `conversa.py` le a `conversations` e a `handoffs` para
#: decidir se o turno entra no grafo, e isso e a admissao do turno e nao um
#: agente a ler dados de negocio».
#:
#: **O criterio e estreito, e nao e «o AGR pode escrever».** Uma entrada so
#: entra aqui se as quatro valerem:
#:
#: 1. nenhum passo da escrita depende de saida de modelo nem de texto do
#:    cliente — se dependesse, era a TLS que tinha de a validar;
#: 2. o que se escreve e **plano de controlo** do runtime (o estado de uma
#:    espera, uma tranca, um prazo) e nao dado de negocio (uma encomenda, um
#:    preco, um contacto);
#: 3. o `tenant_id` esta no predicado e a instrucao corre dentro de
#:    `tenant_guard.tx` — o isolamento do ADR-015 continua a ser da base;
#: 4. o canon **nomeia** o AGR como dono da escrita.
#:
#: E a chave e `(ficheiro, tabela, verbo)` e nao o ficheiro: um `consultas.py`
#: dispensado em bloco deixava passar um `UPDATE platform.orders` na linha
#: seguinte, que e precisamente o que esta regra existe para apanhar. Ha
#: canarios que medem os tres eixos.
#:
#: **O verbo entra, e a primeira versao desta lista deixou-o de fora.** Ela
#: dispensava `(ficheiro, tabela)` e argumentava que distinguir verbos era
#: redundante porque «o `GRANT` por coluna da revisao `0011` da-a melhor: o
#: `kamba_app` **nao tem** `DELETE` em `platform.handoffs`». Metade disso era
#: falso: a `0011` concede `GRANT SELECT, INSERT ON platform.handoffs TO
#: kamba_app`, pelo que um `INSERT` escrito aqui **passava o *lint* e corria na
#: base** — e o canon atribui a criacao da passagem ao HND e a purga ao
#: `kamba_batch`, nao ao AGR. Apanhado pela revisao adversarial do KAM-034
#: (achado 5).
ESCRITAS_DO_PLANO_DE_CONTROLO = frozenset(
    {
        # KAM-034, criterio 3: o *compare-and-set* `waiting -> resumed` de
        # `/internal/resume`. O `docs/tecnica/02` §11 regra 3 poe o *endpoint* no
        # AGR por escrito, e o dicionario §3.15 ja o atribuiu («o
        # *compare-and-set* `waiting -> resumed` fica fora deste ticket [o
        # KAM-019]»). Escreve duas colunas — `status` e `resumed_at` —, as duas
        # com `GRANT UPDATE` por coluna na revisao `0011`, e nenhuma delas vem de
        # modelo nenhum: o `outcome` chega num corpo autenticado pelo `secret`
        # do *agent bot* e e um de tres valores de lista fechada.
        #
        # **So o `update`.** A criacao da passagem e do HND (`SQL_ABRIR_HANDOFF`)
        # e a purga e do `kamba_batch` (KAM-071); um `INSERT` ou um `DELETE`
        # escritos no AGR sao uma fronteira a mudar, e uma fronteira a mudar
        # passa por aqui com uma entrada nova e a razao escrita.
        ("services/agr/src/kamba_agr/consultas.py", "handoffs", "update"),
    }
)


def _ficheiros_de_servico(root: Path) -> list[Path]:
    return sorted(
        caminho
        for caminho in root.glob("services/*/src/**/*.py")
        if "__pycache__" not in caminho.parts
    )


def _dentro_da_tls(caminho: Path) -> bool:
    return DIRECTORIO_DA_TLS in caminho.parts


def _nome_da_base(base: ast.expr) -> str | None:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None


def _modelos_do_ficheiro(arvore: ast.AST) -> tuple[set[str], set[str]]:
    """`(modelos, indecisos)` — as classes que herdam de `BaseModel`, e as duvidas.

    **Transitivo e nao directo**, e foi um canario a mostrar porque: a primeira
    versao reconhecia so `class Args(BaseModel)`, pelo que

        class Base(BaseModel): ...
        class Args(Base):
            tenant_id: str

    passava as duas verificacoes e o *lint* devolvia `conforme` — com o
    `tenant_id` no esquema que vai ao modelo. Apanhado pela revisao adversarial,
    medido numa arvore de ensaio.

    Resolve-se por ponto fixo sobre os nomes das bases **dentro do ficheiro**,
    que e tudo o que o `ast` pode saber sem importar nada. Uma classe cuja base
    e um nome que o ficheiro nao define — importado de outro modulo — fica
    **indecisa**, e um indeciso e um achado: o *lint* diz que nao consegue
    decidir em vez de deixar passar. E a mesma regra que o `check_dependencies`
    aplica a uma dependencia que nao consegue ler (`declaration.name == "?"`).
    """
    classes = {
        no.name: no for no in ast.walk(arvore) if isinstance(no, ast.ClassDef)
    }
    modelos: set[str] = set()
    indecisos: set[str] = set()
    # Ponto fixo: no maximo tantas passagens quantas classes houver.
    for _ in range(len(classes) + 1):
        mudou = False
        for nome, classe in classes.items():
            if nome in modelos:
                continue
            for base in classe.bases:
                etiqueta = _nome_da_base(base)
                if etiqueta is None:
                    continue
                if etiqueta == "BaseModel" or etiqueta in modelos:
                    modelos.add(nome)
                    mudou = True
                    break
        if not mudou:
            break
    for nome, classe in classes.items():
        if nome in modelos:
            continue
        for base in classe.bases:
            etiqueta = _nome_da_base(base)
            if etiqueta is not None and etiqueta not in classes:
                # Uma base que este ficheiro nao define. Pode ser um `BaseModel`
                # de outro modulo, pode ser um `Protocol`, pode ser `Exception`.
                # Os nomes que esta casa usa e que **nao** sao modelos declaram-se
                # aqui; o resto e indeciso.
                if etiqueta not in BASES_QUE_NAO_SAO_MODELO:
                    indecisos.add(nome)
                break
    return modelos, indecisos


#: As bases que, vindas de fora do ficheiro, **nao** sao modelos de argumentos.
#: Lista curta e de nomes da biblioteca padrao e dos `Protocol` desta casa: o
#: que nao estiver aqui e indeciso, e um indeciso e um achado.
BASES_QUE_NAO_SAO_MODELO = frozenset(
    {
        "Exception", "ValueError", "RuntimeError", "TypeError", "KeyError",
        "OSError", "Protocol", "Enum", "StrEnum", "IntEnum", "TypedDict",
        "NamedTuple", "ABC", "object", "str", "int", "dict", "list", "tuple",
    }
)


def _campos(classe: ast.ClassDef) -> list[str]:
    """Os campos anotados da classe. O `model_config` nao e campo."""
    campos: list[str] = []
    for corpo in classe.body:
        if not isinstance(corpo, ast.AnnAssign) or not isinstance(corpo.target, ast.Name):
            continue
        if corpo.target.id == "model_config":
            continue
        campos.append(corpo.target.id)
    return campos


def _proibe_extra(classe: ast.ClassDef, por_nome: dict[str, ast.ClassDef]) -> bool:
    """Se a classe configura `extra="forbid"`.

    Aceita as duas formas que o Pydantic 2 tem — `ConfigDict(extra="forbid")` e
    um `dict` literal — porque as duas produzem a mesma configuracao, e um
    *lint* que so reconhecesse uma recusava codigo correcto.
    """
    vistas: set[str] = set()
    fila = [classe]
    while fila:
        actual = fila.pop()
        if actual.name in vistas:
            continue
        vistas.add(actual.name)
        for corpo in actual.body:
            if not isinstance(corpo, ast.AnnAssign | ast.Assign):
                continue
            alvos = (
                [corpo.target]
                if isinstance(corpo, ast.AnnAssign)
                else list(corpo.targets)
            )
            if not any(
                isinstance(a, ast.Name) and a.id == "model_config" for a in alvos
            ):
                continue
            valor = corpo.value
            if isinstance(valor, ast.Call):
                for palavra in valor.keywords:
                    if palavra.arg == "extra" and _texto(palavra.value) == "forbid":
                        return True
            if isinstance(valor, ast.Dict):
                for chave, item in zip(valor.keys, valor.values, strict=True):
                    if _texto(chave) == "extra" and _texto(item) == "forbid":
                        return True
        # **Herda-se, e o Pydantic herda mesmo.** Um `class Args(Base)` cujo
        # `Base` declara `extra="forbid"` esta configurado, e exigir-lhe a linha
        # outra vez era recusar codigo correcto.
        for base in actual.bases:
            etiqueta = _nome_da_base(base)
            if etiqueta is not None and etiqueta in por_nome:
                fila.append(por_nome[etiqueta])
    return False


def _texto(no: ast.expr | None) -> str | None:
    return no.value if isinstance(no, ast.Constant) and isinstance(no.value, str) else None


#: As classes de cada ficheiro, por nome, enquanto o `check` corre. Existe para
#: o `_proibe_extra` poder subir a cadeia de bases sem reparsear.
_POR_NOME: dict[str, dict[str, ast.ClassDef]] = {}


def check(root: Path) -> list[str]:
    """Os achados. Lista vazia e conforme."""
    achados: list[str] = []
    _POR_NOME.clear()
    for caminho in _ficheiros_de_servico(root):
        onde = caminho.relative_to(root).as_posix()
        try:
            fonte = caminho.read_text(encoding="utf-8")
        except OSError as erro:
            achados.append(f"{onde}: nao se conseguiu ler: {erro}")
            continue

        if not _dentro_da_tls(caminho):
            for achado in ESCRITA_NO_PLATFORM.finditer(fonte):
                chave = (onde, _tabela_de(achado), _verbo_de(achado))
                if chave in ESCRITAS_DO_PLANO_DE_CONTROLO:
                    # Plano de controlo do runtime, declarado por
                    # `(ficheiro, tabela, verbo)`. Ver
                    # `ESCRITAS_DO_PLANO_DE_CONTROLO` para os quatro criterios e
                    # a razao de cada entrada.
                    continue
                numero = fonte.count("\n", 0, achado.start()) + 1
                achados.append(
                    f"{onde}:{numero}: escrita no schema `platform` fora da "
                    f"ToolLayer.\n"
                    "    A TLS e a unica via de escrita dos agentes "
                    "(`docs/tecnica/02` §6.1, ADR-015, `docs/tecnica/08` §3.2).\n"
                    f"    {' '.join(achado.group(0).split())}"
                )
            continue

        try:
            arvore = ast.parse(fonte, filename=onde)
        except SyntaxError as erro:
            achados.append(f"{onde}: nao compila: {erro}")
            continue

        modelos, indecisos = _modelos_do_ficheiro(arvore)
        _POR_NOME[onde] = {
            no.name: no for no in ast.walk(arvore) if isinstance(no, ast.ClassDef)
        }
        for nome in sorted(indecisos):
            achados.append(
                f"{onde}: a classe `{nome}` herda de um nome que este ficheiro "
                "nao define, e o *lint* nao importa nada para o descobrir.\n"
                "    Se e um esquema de tool, declare a base neste ficheiro; se "
                "nao e um modelo, acrescente a base a `BASES_QUE_NAO_SAO_MODELO`.\n"
                "    Falha fechada de proposito: um esquema que o lint nao "
                "consegue ler e um esquema que ele nao verifica."
            )
        for no in ast.walk(arvore):
            if not isinstance(no, ast.ClassDef) or no.name not in modelos:
                continue
            expostos = sorted(set(_campos(no)) & set(PARAMETROS_PROIBIDOS))
            if expostos:
                achados.append(
                    f"{onde}:{no.lineno}: o esquema `{no.name}` expoe {expostos} ao "
                    "modelo.\n"
                    "    O modelo nunca ve nem fornece estes parametros: vem do "
                    "`ToolContext`, derivado do estado (`docs/tecnica/02` §6.1, "
                    "ADR-015).\n"
                    "    Tire o campo do esquema e leia-o de `pedido.ctx`."
                )
            if not _proibe_extra(no, _POR_NOME.get(onde, {})):
                achados.append(
                    f"{onde}:{no.lineno}: o esquema `{no.name}` nao declara "
                    '`model_config = ConfigDict(extra="forbid")`.\n'
                    "    O passo 3 de `docs/tecnica/02` §6.1 pede-o pelo nome; sem "
                    "ele um argumento a mais produzido pelo modelo entra em silencio "
                    "(`docs/tecnica/08` §4.3)."
                )
    return achados
