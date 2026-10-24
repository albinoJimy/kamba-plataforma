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

import importlib.util
import os
from typing import Final

#: Os modulos que nao podem estar importaveis no processo do AGR.
#:
#: Sao nomes de **modulo** (com `_`), nao de distribuicao (com `-`): o que o
#: `find_spec` procura e `langgraph_api`, e o pacote no PyPI chama-se
#: `langgraph-api`. Escrever o nome do pacote aqui dava um `find_spec` que
#: nunca encontra nada e uma guarda que passa sempre.
MODULOS_PROIBIDOS: Final = ("langgraph_api", "langgraph_runtime_inmem")

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


def desligar_telemetria(ambiente: dict[str, str] | None = None) -> dict[str, str]:
    """Poe as `VARIAVEIS_DE_TELEMETRIA` a `false`. Devolve o que mudou.

    **Sobrepoe** um valor existente, mesmo que diga `true`. Nao e descuido com
    a configuracao de quem faz o *deploy*: e o criterio 7, e um AGR que
    respeitasse um `LANGSMITH_TRACING=true` do ambiente mandava conteudo de
    conversas de clientes para fora de Angola sem destino registado (ADR-008).
    Quem quiser *traces* tem o Langfuse (KAM-069).

    Devolve-se o que mudou para que o arranque o possa registar — o **nome** da
    variavel, que e constante deste modulo, e nunca o valor que lá estava.
    """
    alvo = ambiente if ambiente is not None else os.environ
    mudou: dict[str, str] = {}
    for variavel in VARIAVEIS_DE_TELEMETRIA:
        if alvo.get(variavel) != TELEMETRIA_DESLIGADA:
            mudou[variavel] = alvo.get(variavel, "")
        alvo[variavel] = TELEMETRIA_DESLIGADA
    return mudou
