"""As guardas tecnicas do ADR-002 em *runtime* (KAM-025 criterios 7 e 8).

O `docs/tecnica/02` §4.2 tem quatro regras; duas delas sao de CI e duas sao
daqui:

| Regra | Onde se cumpre |
|---|---|
| 1 — lista de bloqueio no lockfile | CI: `tools/lint_arch` (*gate* 2) e `make supply-chain` |
| 2 — `LANGSMITH_TRACING=false`, egresso por *allowlist* | **aqui**, e `services/agr/egress.yaml` |
| 3 — traces no Langfuse, nao no LangSmith | KAM-069 (OBS) |
| 4 — servico proprio com API interna minima | `api_interna.py` |

E o criterio 8 do ticket junta-lhe uma terceira: **o arranque falha se
`langgraph_api` for importavel**.

## A segunda metade: o SBOM do ambiente (KAM-027, criterio 7)

O KAM-025 entregou metade do criterio — «se um pacote proibido for
importavel» — e o KAM-027 entrega a outra: «**ou constar do SBOM do
ambiente**». Nao e a mesma pergunta, e a diferenca mede-se num pacote real.

O `find_spec` procura **modulos**. O `langgraph-checkpoint-postgres` instala o
modulo `langgraph.checkpoint.postgres`, dentro de um pacote de *namespace* que
nos **temos** e queremos ter: nenhum nome de `MODULOS_PROIBIDOS` o encontraria,
e ele esta na lista de bloqueio desde o KAM-026 porque o fecho dele exige
`psycopg` e `psycopg-pool`, LGPL-3.0-only. Um `pip install` a mao num contentor
de depuracao punha-o la, com licenca proibida, e a guarda de cima dizia que
estava tudo bem.

O que o `exigir_sbom_mit` le e o `importlib.metadata`: as **distribuicoes
instaladas** neste interprete, que e o SBOM do ambiente no unico sentido que um
processo pode medir sobre si proprio. Compara-as com a lista de bloqueio pelas
mesmas regras do *gate* 2 — nomes normalizados por PEP 503, fronteira de
palavra para os nomes curtos, e `forbidden_below` onde ele existe —, e ha um
teste de paridade que confronta a tabela deste modulo com `tools/blocklist.yaml`
e falha se as duas divergirem. Sem esse teste, a tabela era uma copia a
envelhecer.

## Porque e que a importabilidade se verifica em *runtime* e nao so no CI

Porque o lockfile e a imagem nao sao a mesma coisa que o processo. Um
`pip install` a mao num contentor de depuracao, uma imagem base que mude, uma
camada que alguem acrescente — nenhuma dessas passa pelo lockfile, e todas
acabam com o `langgraph_api` importavel num processo que corre em producao. O
que o §4.2 regra 1 protege e o que **declaramos**; isto protege o que **corre**.

O `langgraph-api` e Elastic-2.0, exige `LANGSMITH_API_KEY` e
`LANGGRAPH_CLOUD_LICENSE_KEY` e abre egresso para `beacon.langchain.com`
(CONFIRMADO, `E4` §2.6). Nao e uma dependencia a mais: e licenca e telemetria.

**Verifica-se com `importlib.util.find_spec` e nao com um `import`**, e a
diferenca e de seguranca: um `import` executa o `__init__.py` do pacote
proibido — isto e, corre o codigo que estamos a recusar, e nalguns pacotes isso
e bastante para contactar a rede. O `find_spec` so procura o modulo.

## O `LANGSMITH_TRACING`

O nome exacto da variavel na versao fixada do LangGraph e **NAO VERIFICADO**
(L5): o criterio 7 do ticket di-lo por escrito, e o §4.2 regra 2 repete-o
(«nome exacto das variaveis a validar»). O que este modulo faz e **impor** o
valor `false` nas variaveis que a evidencia nomeia, e nao adivinhar outras.
Impor e nao verificar: um AGR que arrancasse a dizer «falta pôr
`LANGSMITH_TRACING=false`» deixava a decisao a quem faz o *deploy*, e a
telemetria liga-se por omissao.

E impor nao chega, e por isso nao e tudo o que se faz: o egresso continua negado
por omissao em `egress.yaml`, e e esse que vale se a variavel estiver errada. A
*suite* do *gate* 8 nao mede «0 chamadas a `beacon.langchain.com`» com um
contador de chamadas — mede que o destino **nao esta** na *allowlist* do
servico, que e a propriedade que se tem hoje; a aplicacao na rede e o KAM-076.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import re
from dataclasses import dataclass
from typing import Final

#: Os modulos que nao podem estar importaveis no processo do AGR.
#:
#: Sao nomes de **modulo** (com `_`), nao de distribuicao (com `-`): o que o
#: `find_spec` procura e `langgraph_api`, e o pacote no PyPI chama-se
#: `langgraph-api`. Escrever o nome do pacote aqui dava um `find_spec` que
#: nunca encontra nada e uma guarda que passa sempre.
MODULOS_PROIBIDOS: Final = ("langgraph_api", "langgraph_runtime_inmem")

@dataclass(frozen=True, slots=True)
class DistribuicaoProibida:
    """Uma entrada da lista de bloqueio que pode estar instalada em Python.

    O espelho das entradas `kind: pypi` e `kind: any` de `tools/blocklist.yaml`
    — as unicas que um `pip install` pode trazer. As `kind: image` e `kind: npm`
    ficam de fora porque nao sao distribuicoes Python, e nao se finge
    verifica-las aqui.

    `limiar` e o `forbidden_below`: a versao a partir da qual o pacote deixa de
    estar bloqueado. Existe num unico caso, o `litellm`, e existe porque o que
    esta proibido ali sao **duas versoes com malware** e nao o pacote.
    """

    nome: str
    #: `True` para `match: exact`, `False` para `match: boundary`.
    exacto: bool
    limiar: tuple[int, ...] | None = None


#: As entradas de `tools/blocklist.yaml` que podem estar instaladas em Python.
#: **Nao e uma copia que apodrece**: o `test_egresso.py` le o ficheiro pelo
#: `lint_arch.blocklist` e falha se a tabela divergir, nos dois sentidos — e
#: compara as duas implementacoes por **comportamento**, com o
#: `versions.satisfies_floor` real do outro lado.
#:
#: O `psycopg2-binary` entrou nas duas com o KAM-027: o `runtime.in` e o
#: `db/requirements/migrations.in` recusavam-no pelo nome em prosa, e nem esta
#: tabela nem a lista de bloqueio o tinham — as entradas `psycopg` sao `exact` e
#: nao lhe batem. Foi o teste de paridade que o encontrou, com os dois controlos
#: calados sobre um pacote LGPL.
#:
#: Esta em codigo e nao se le o YAML em execucao pela razao do ADR-L001 §6: uma
#: guarda que precisasse de um ficheiro do repositorio para dizer que uma
#: dependencia e proibida chegava sempre tarde — e, ao contrario do `registry/`,
#: esta lista nao e configuracao de ninguem: alterar a lista de bloqueio exige
#: citar o ADR e a evidencia (`specs/01` §5), o que e um PR revisto.
DISTRIBUICOES_PROIBIDAS: Final = (
    DistribuicaoProibida("langgraph-api", exacto=True),
    DistribuicaoProibida("langgraph-checkpoint-postgres", exacto=True),
    DistribuicaoProibida("langgraph-runtime-inmem", exacto=True),
    DistribuicaoProibida("psycopg", exacto=True),
    DistribuicaoProibida("psycopg-pool", exacto=True),
    DistribuicaoProibida("psycopg2-binary", exacto=True),
    DistribuicaoProibida("dify", exacto=False),
    DistribuicaoProibida("litellm", exacto=False, limiar=(1, 83, 0)),
    DistribuicaoProibida("minio", exacto=False),
    DistribuicaoProibida("n8n", exacto=False),
    DistribuicaoProibida("typebot", exacto=False),
)

#: PEP 503: `-`, `_` e `.` em sequencia valem por um `-`, e a caixa nao conta.
#: `langgraph_api` e `langgraph-api` sao o mesmo pacote.
_SEPARADORES: Final = re.compile(r"[-_.]+")

#: As variaveis de telemetria que se impoem a `false`.
#:
#: As duas: o `LANGCHAIN_TRACING_V2` e o nome antigo e continua a ser lido por
#: versoes do ecossistema LangChain que o LangGraph arrasta. Impor so a nova
#: deixava a antiga a decidir. **NAO VERIFICADO** qual delas a versao fixada le
#: (L5); impoem-se as duas, que e o que custa zero e fecha as duas leituras.
VARIAVEIS_DE_TELEMETRIA: Final = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")

#: O valor que se impoe.
TELEMETRIA_DESLIGADA: Final = "false"

#: O destino que o `langgraph-api` contacta e que nao sai daqui (`E4` §2.6).
#: Esta nomeado para que a *suite* o possa procurar na *allowlist* do servico.
BEACON: Final = "beacon.langchain.com"


class ModuloProibidoError(RuntimeError):
    """Um modulo da lista de bloqueio esta importavel. O arranque falha.

    Criterio 8 do KAM-025 e §4.2 regra 1 do `docs/tecnica/02`. A mensagem
    nomeia o modulo — o nome vem desta lista e nao de fora, pelo que nao ha aqui
    conteudo de ninguem.
    """


def exigir_biblioteca_mit() -> None:
    """Levanta se algum `MODULOS_PROIBIDOS` estiver importavel.

    Chamada no arranque, antes de qualquer porta abrir. O `find_spec` pode ele
    proprio levantar (`ModuleNotFoundError` quando o **pai** de um modulo nao
    existe, `ValueError` quando o modulo esta em `sys.modules` sem `__spec__`),
    e as duas contam como «nao esta importavel» — e por isso que o `except` nao
    deixa o arranque cair por causa da propria verificacao.
    """
    for modulo in MODULOS_PROIBIDOS:
        try:
            encontrado = importlib.util.find_spec(modulo) is not None
        except (ImportError, ValueError):
            encontrado = False
        if encontrado:
            raise ModuloProibidoError(
                f"{modulo} esta importavel neste processo. E Elastic-2.0 e abre "
                f"egresso para {BEACON} (E4 §2.6); o ADR-002 so admite o "
                "LangGraph como biblioteca MIT."
            )


def normalizar(nome: str) -> str:
    """O nome de uma distribuicao, normalizado por PEP 503."""
    return _SEPARADORES.sub("-", nome).lower()


def _versao(bruta: str) -> tuple[int, ...] | None:
    """Os componentes de uma versao, ou `None` se ela nao for **toda** numerica.

    **E o `parse` de `tools/lint_arch/versions.py`, componente a componente**, e
    nao uma aproximacao dele. A primeira versao desta funcao parava no primeiro
    componente nao numerico, e a revisao adversarial mediu duas divergencias
    face ao *gate* 2 — uma em cada sentido:

    | Versao | O `lint_arch` dizia | Esta funcao dizia |
    |---|---|---|
    | `1.83` | permitida (o `compare` iguala as larguras: `(1,83)` vs `(1,83,0)`) | **bloqueada** |
    | `1.84.0.post1` | bloqueada (nao e pin exacto, logo nao esta provada) | **permitida** |

    A segunda era a grave: um `litellm` com sufixo de *post-release* passava a
    guarda de *runtime* e falhava o CI, que e a ordem errada — o controlo que
    protege o que **corre** era o mais frouxo dos dois.

    Agora: todos os componentes tem de ser digitos, senao a versao nao esta
    provada. «Nao provado» trata-se como «nao permitido» para um pacote que ja
    foi vector de ataque (ADR-L001 §10).
    """
    partes = bruta.strip().split(".")
    if not partes or not all(parte.isdigit() for parte in partes):
        return None
    return tuple(int(parte) for parte in partes)


def _bate(entrada: DistribuicaoProibida, nome: str, versao: str | None) -> bool:
    """`True` se esta distribuicao instalada bate nesta entrada da lista."""
    if entrada.exacto:
        if nome != entrada.nome:
            return False
    elif not re.search(
        r"(?<![a-z0-9])" + re.escape(entrada.nome) + r"(?![a-z0-9])", nome
    ):
        return False
    if entrada.limiar is None:
        return True
    # Sem versao provada nao se prova que esta acima do limiar, e para um
    # pacote que ja foi vector de ataque «nao provado» trata-se como «nao
    # permitido» — a mesma regra que o ADR-L001 §10 escreveu para as imagens
    # fixadas por digest sem versao na tag.
    partes = _versao(versao or "")
    if partes is None:
        return True
    # **As larguras igualam-se**, como o `compare` do `lint_arch` faz: `1.83`
    # e `1.83.0` sao a mesma versao, e sem isto a guarda bloqueava a primeira e
    # o *gate* 2 permitia-a.
    largura = max(len(partes), len(entrada.limiar))
    esquerda = partes + (0,) * (largura - len(partes))
    direita = entrada.limiar + (0,) * (largura - len(entrada.limiar))
    return esquerda < direita


def exigir_sbom_mit() -> None:
    """Levanta se uma distribuicao da lista de bloqueio estiver instalada.

    A segunda metade do criterio 7 do KAM-027. Chamada no arranque, logo a
    seguir ao `exigir_biblioteca_mit`: as duas correm antes de se ler uma
    variavel de ambiente e antes de abrir uma porta.

    Um `importlib.metadata` que nao consiga ler uma distribuicao nao faz o
    arranque cair pela propria verificacao — a mesma decisao do `find_spec` em
    `exigir_biblioteca_mit`, e pela mesma razao: a guarda recusa pacotes, nao
    interpretes.
    """
    for distribuicao in importlib.metadata.distributions():
        try:
            nome = distribuicao.metadata["Name"]
            versao = distribuicao.version
        except Exception:  # noqa: BLE001 — metadados ilegiveis nao sao um bloqueio
            continue
        if not nome:
            continue
        normalizado = normalizar(nome)
        for entrada in DISTRIBUICOES_PROIBIDAS:
            if _bate(entrada, normalizado, versao):
                raise ModuloProibidoError(
                    f"{normalizado} {versao} esta instalado neste ambiente e esta na lista "
                    f"de bloqueio (tools/blocklist.yaml, {entrada.nome}). O que o lockfile "
                    "declara e o que o gate 2 verifica; isto verifica o que corre."
                )


def desligar_telemetria(ambiente: dict[str, str] | None = None) -> tuple[str, ...]:
    """Poe as `VARIAVEIS_DE_TELEMETRIA` a `false`. Devolve os **nomes** que mudou.

    **Sobrepoe** um valor existente, mesmo que diga `true`. Nao e descuido com
    a configuracao de quem faz o *deploy*: e o criterio 7, e um AGR que
    respeitasse um `LANGSMITH_TRACING=true` do ambiente mandava conteudo de
    conversas de clientes para fora de Angola sem destino registado (ADR-008).
    Quem quiser *traces* tem o Langfuse (KAM-069).

    **Devolve nomes e nao um `dict`, e isto e uma correccao.** A primeira versao
    devolvia `{nome: valor_anterior}` com uma *docstring* a prometer «o nome e
    nunca o valor»: o valor anterior ia no dicionario, e um `LANGSMITH_TRACING`
    pode trazer uma chave colada por engano. O arranque salvava-se por acidente,
    porque registava `sorted(...)` — que itera as **chaves** —, e o teste que
    negava o valor fazia `" ".join(mudou)`, que itera as chaves tambem: a
    asercao era sempre verdadeira. Um tipo que nao pode levar o valor fecha as
    duas coisas de uma vez. Achado da revisao adversarial.
    """
    alvo = ambiente if ambiente is not None else os.environ
    mudou: list[str] = []
    for variavel in VARIAVEIS_DE_TELEMETRIA:
        if alvo.get(variavel) != TELEMETRIA_DESLIGADA:
            mudou.append(variavel)
        alvo[variavel] = TELEMETRIA_DESLIGADA
    return tuple(mudou)
