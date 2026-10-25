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
ESCRITA_NO_PLATFORM = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+platform\.", re.IGNORECASE
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
