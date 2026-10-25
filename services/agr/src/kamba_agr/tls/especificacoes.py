"""A especificacao de uma tool e o catalogo que as guarda.

O `kamba/tls/specs/` dos *Detalhes Tecnicos* do bloco pede «uma spec por tool:
nome, `klass`, versao, modelo Pydantic». Aqui esta a forma dela e o catalogo; as
especificacoes do Piloto estao em `catalogo.py`.

## Uma entrada tem dois estados, e e isso que fecha a validacao (1)

O bloco diz duas coisas que parecem nao caber juntas: «aqui entra o *framework*
e `get_store_info` como primeira tool real», e «nao expandas escopo: as
especificacoes das tools de cada vertical (KAM-031/035) sao tickets proprios».
Mas a validacao (1) do `docs/tecnica/02` §5.2 exige que **todas** as `tools[]`
de uma vertical existam no catalogo, e as duas verticais declaram onze nomes.

A distincao que resolve e entre **nome** e **especificacao**:

* o nome, a classe, a vertical e o botao de confirmacao sao canon desde a emenda
  **1.35** do dicionario, que os poe lá e escreve «o que entra aqui e o
  **nome**». Transcrever canon nao e desenhar;
* o modelo de argumentos e o executor que fala com o COM, o PAY ou o IDX sao do
  KAM-031 e do KAM-035.

Daí os dois estados de uma entrada:

| | `ligada` | `declarada` |
|---|---|---|
| nome, `klass`, `backend`, `versao` | sim | sim |
| `modelo` e `executor` | sim | **nao** |
| `credor` | nao — ja esta ligada | **obrigatorio** |
| visivel ao modelo (`for_context`) | sim | **nao** |
| `invoke` | corre | recusa com `TOOL_NOT_ALLOWED` |

E as consequencias, que e o que faz desta validacao uma verificacao e nao uma
passagem vazia:

1. uma entrada `declarada` **nao esta exposta ao modelo**, pelo que os
   `parametros_visiveis` dela sao vazios porque nada dela esta exposto — e nao
   porque nao se procurou. Ha teste a provar que o `for_context` nao a liga e
   que o `invoke` a recusa;
2. uma entrada sem executor **e sem `credor`** e recusada. E a disciplina que o
   KAM-027 impôs ao `registry/gates.yaml` — «um atalho sem o ticket que o fecha
   nao e atalho» — aplicada a mesma superficie;
3. no dia em que o KAM-031 registar o `search_catalog` com um `tenant_id` no
   modelo, a validacao **morde**, porque passou a `bloqueio` neste ticket.

## O `extra="forbid"` verifica-se aqui, e nao se confia no autor

O passo 3 do §6.1 pede argumentos validados «por Pydantic com
`extra="forbid"`», e o critero 2 do bloco pede que um argumento a mais devolva
`VALIDATION_ERROR`. Um modelo que o autor se esqueca de configurar aceita
argumentos a mais em silencio, e um argumento a mais produzido pelo modelo e
precisamente o vector do §4.3. Por isso o `__post_init__` **recusa** um modelo
sem `extra="forbid"`: e mais barato falhar no arranque do que descobrir pelo
lado de um carrinho com um campo que ninguem le.

Pela mesma razao recusa um modelo que exponha um dos quatro
`PARAMETROS_PROIBIDOS`. Isto nao substitui o *lint* de CI do critero 3 — que
falha o *build* e corre sobre a **fonte**, sem importar nada — mas fecha o
caminho em execucao: as duas verificacoes olham para a mesma regra por dois
lados, e a de CI apanha-a antes de alguem a correr.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from pydantic import BaseModel

from ..registo.validar import PARAMETROS_PROIBIDOS
from .contexto import ToolContext
from .erros import Fact

#: As tres classes de tool (§6.1, dicionario §3.27). Lista **fechada**.
CLASSES: Final = ("read", "write", "money")

#: As classes que exigem confirmacao por botao (§6.1 passo 4, `08` §4.3).
CLASSES_DE_ESCRITA: Final = ("write", "money")

#: Os backends, que sao a unidade do *circuit breaker* (§6.5). Lista
#: **fechada**: os tres componentes do `docs/tecnica/00` §4 mais a nossa propria
#: base, que e o backend do `get_store_info`.
BACKENDS: Final = ("com", "pay", "idx", "plataforma")

#: A gramatica de um nome de tool. A mesma do `CHECK` da revisao `0021` e a
#: mesma de uma etiqueta de metrica — porque o nome **e** etiqueta de metrica.
NOME_DE_TOOL: Final = re.compile(r"^[a-z][a-z0-9_]{1,62}$")

#: A forma de um credor: um ticket do backlog mestre. O *gate* 3 (referencias
#: cruzadas) le os `KAM-NNN` deste ficheiro como le os de qualquer outro, pelo
#: que um credor inventado falha o CI sem precisar de verificacao propria.
CREDOR: Final = re.compile(r"^KAM-\d{3}$")


class EspecificacaoInvalidaError(ValueError):
    """Uma especificacao que o catalogo nao aceita.

    Levanta no arranque e nao em execucao: e um defeito de quem a escreveu, e
    uma tool mal declarada que so rebente a primeira vez que o modelo a chamar
    rebenta a meio de uma conversa de um cliente.
    """


@dataclass(frozen=True, slots=True)
class Pedido:
    """O que um executor recebe: o contexto, os argumentos ja validados e o tecto.

    O executor **nao** recebe o dicionario `args` cru: recebe o modelo Pydantic
    ja construido, pela razao que o `hook.py` do KAM-009 escreveu para o seu
    proprio contrato — «um argumento produzido pelo modelo nao tem por onde
    chegar aqui» sem passar pela validacao.

    A `ligacao` e a tomada DB-API para os backends que falam com a nossa base
    (o `plataforma`); e `None` para os outros, e um executor que a precise e nao
    a tenha levanta — o que e um defeito de registo, nao uma resposta.
    """

    ctx: ToolContext
    args: BaseModel
    timeout_ms: int
    ligacao: Any = None


@dataclass(frozen=True, slots=True)
class Resposta:
    """O que um executor devolve: os dados e os *facts* (ADR-007)."""

    data: dict[str, Any]
    facts: tuple[Fact, ...] = ()


class ErroDeBackend(Exception):
    """Um estado de negocio que o backend reportou, com o codigo do §6.5.

    E a unica excepcao que um executor levanta de proposito, e o `invoke`
    traduz-la no `ToolResult`. Qualquer outra excepcao e `UPSTREAM_DOWN`: um
    executor que rebente de maneira que nao previu nao e um estado de negocio.
    """

    def __init__(self, codigo: str, detalhe: str = "") -> None:
        super().__init__(f"{codigo}: {detalhe}" if detalhe else codigo)
        self.codigo = codigo
        self.detalhe = detalhe


class Executor(Protocol):
    """O que liga uma especificacao a um backend."""

    def __call__(self, pedido: Pedido) -> Resposta: ...


@dataclass(frozen=True, slots=True)
class EspecificacaoDeTool:
    """Uma tool do catalogo (§6.2), ligada ou declarada."""

    nome: str
    klass: str
    backend: str
    versao: str = "1"
    #: O modelo dos argumentos, com `extra="forbid"`. `None` numa entrada
    #: `declarada`.
    modelo: type[BaseModel] | None = None
    #: Quem fala com o backend. `None` numa entrada `declarada`.
    executor: Executor | None = None
    #: O campo dos `args` cuja referencia o botao `confirm:{…}` tem de citar.
    #: Obrigatorio numa entrada `ligada` de classe `write` ou `money`.
    campo_de_confirmacao: str | None = None
    #: O ticket que liga esta entrada. Obrigatorio numa entrada `declarada`.
    credor: str | None = None

    def __post_init__(self) -> None:
        if not NOME_DE_TOOL.match(self.nome):
            raise EspecificacaoInvalidaError(
                f"{self.nome!r} nao casa a gramatica de um nome de tool "
                f"({NOME_DE_TOOL.pattern}); e tambem etiqueta de metrica"
            )
        if self.klass not in CLASSES:
            raise EspecificacaoInvalidaError(
                f"a tool `{self.nome}` tem `klass` {self.klass!r}, que nao e uma das "
                f"tres de `docs/tecnica/02` §6.1: {list(CLASSES)}"
            )
        if self.backend not in BACKENDS:
            raise EspecificacaoInvalidaError(
                f"a tool `{self.nome}` tem `backend` {self.backend!r}, fora de "
                f"{list(BACKENDS)}; o backend e a unidade do disjuntor (§6.5)"
            )
        if (self.modelo is None) != (self.executor is None):
            raise EspecificacaoInvalidaError(
                f"a tool `{self.nome}` tem modelo sem executor ou executor sem modelo. "
                "Uma entrada esta `ligada` (os dois) ou `declarada` (nenhum): um "
                "esquema exposto ao modelo sem nada que o execute e uma tool que o "
                "modelo chama e que nao responde"
            )
        if self.ligada:
            self._validar_ligada()
        else:
            self._validar_declarada()

    @property
    def ligada(self) -> bool:
        """Se tem modelo e executor — e portanto se e visivel ao modelo."""
        return self.modelo is not None

    @property
    def exige_confirmacao(self) -> bool:
        """Se o §6.1 passo 4 se lhe aplica."""
        return self.klass in CLASSES_DE_ESCRITA

    def parametros_visiveis(self) -> frozenset[str]:
        """Os campos que o modelo ve. Vazio numa entrada `declarada`.

        **Vazio porque nada esta exposto**, e nao porque nao se procurou: uma
        entrada `declarada` nao entra no `for_context` nem passa o passo 1 do
        `invoke`, e ha teste a provar as duas coisas.
        """
        if self.modelo is None:
            return frozenset()
        return frozenset(self.modelo.model_fields)

    def esquema(self) -> dict[str, Any]:
        """O esquema JSON que vai ao modelo. Vazio numa entrada `declarada`."""
        if self.modelo is None:
            return {}
        return self.modelo.model_json_schema()

    def _validar_ligada(self) -> None:
        assert self.modelo is not None  # garantido pelo invariante acima
        if self.credor is not None:
            raise EspecificacaoInvalidaError(
                f"a tool `{self.nome}` esta ligada e tem `credor` {self.credor!r}. "
                "Um credor e o ticket que falta: numa entrada ligada ele e uma "
                "divida ja paga que ninguem vai riscar"
            )
        if self.modelo.model_config.get("extra") != "forbid":
            raise EspecificacaoInvalidaError(
                f"o modelo de `{self.nome}` nao tem `extra=\"forbid\"`. O passo 3 do "
                "§6.1 pede-o pelo nome, e sem ele um argumento a mais produzido pelo "
                "modelo entra em silencio — que e o vector do `docs/tecnica/08` §4.3"
            )
        expostos = sorted(self.parametros_visiveis() & set(PARAMETROS_PROIBIDOS))
        if expostos:
            raise EspecificacaoInvalidaError(
                f"o modelo de `{self.nome}` expoe {expostos} ao modelo. O modelo nunca "
                "ve nem fornece estes parametros (§6.1, ADR-015): vem do `ToolContext`"
            )
        if self.exige_confirmacao:
            if self.campo_de_confirmacao is None:
                raise EspecificacaoInvalidaError(
                    f"a tool `{self.nome}` e de classe `{self.klass}` e nao diz que "
                    "argumento o botao `confirm:{…}` tem de citar. Sem isso, o passo 4 "
                    "so podia verificar que **existe** um botao — e um botao de outro "
                    "carrinho e um botao que existe"
                )
            if self.campo_de_confirmacao not in self.parametros_visiveis():
                raise EspecificacaoInvalidaError(
                    f"a tool `{self.nome}` manda o botao citar "
                    f"`{self.campo_de_confirmacao}`, que nao e argumento dela "
                    f"({sorted(self.parametros_visiveis())})"
                )
        elif self.campo_de_confirmacao is not None:
            raise EspecificacaoInvalidaError(
                f"a tool `{self.nome}` e `read` e declara campo de confirmacao. Uma "
                "leitura que exigisse botao punha o runtime a pedir confirmacao para "
                "responder ao horario da loja"
            )

    def _validar_declarada(self) -> None:
        if self.credor is None or not CREDOR.match(self.credor):
            raise EspecificacaoInvalidaError(
                f"a tool `{self.nome}` nao tem executor e o `credor` e "
                f"{self.credor!r}. Uma entrada sem executor tem de nomear o ticket "
                "que a liga, na forma `KAM-NNN` — um atalho sem o ticket que o fecha "
                "nao e atalho (a regra do `registry/gates.yaml`, KAM-027)"
            )
        if self.campo_de_confirmacao is not None:
            raise EspecificacaoInvalidaError(
                f"a tool `{self.nome}` esta declarada e diz que campo o botao cita. "
                f"O campo e do modelo, e o modelo e do {self.credor}"
            )


class Catalogo:
    """O catalogo da ToolLayer, e a fonte da validacao (1) do §5.2.

    Satisfaz o `CatalogoDeTools` que o `registo/validar.py` do KAM-027 declarou
    — `nomes()` e `parametros_visiveis(tool)` — e e por isso que a linha
    `tools: { modo: aviso }` do `registry/gates.yaml` sai neste ticket.
    """

    def __init__(self, especificacoes: tuple[EspecificacaoDeTool, ...]) -> None:
        por_nome: dict[str, EspecificacaoDeTool] = {}
        for especificacao in especificacoes:
            if especificacao.nome in por_nome:
                raise EspecificacaoInvalidaError(
                    f"a tool `{especificacao.nome}` esta no catalogo duas vezes. A "
                    "segunda calava a primeira, e qual delas ficava dependia da ordem"
                )
            por_nome[especificacao.nome] = especificacao
        self._por_nome = por_nome

    def nomes(self) -> frozenset[str]:
        """Os nomes do catalogo — ligados **e** declarados.

        Os declarados entram porque a validacao (1) pergunta «esta tool
        existe?», e a resposta para uma tool do §6.2 que o KAM-031 ainda nao
        ligou e **sim, e falta liga-la**. Deixa-los de fora punha o arranque a
        recusar as duas verticais do Piloto por causa de dois tickets que ainda
        nao correram.
        """
        return frozenset(self._por_nome)

    def parametros_visiveis(self, tool: str) -> frozenset[str]:
        """Os parametros que o modelo ve, para uma tool do catalogo."""
        especificacao = self._por_nome.get(tool)
        if especificacao is None:
            return frozenset()
        return especificacao.parametros_visiveis()

    def __getitem__(self, nome: str) -> EspecificacaoDeTool:
        return self._por_nome[nome]

    def get(self, nome: str) -> EspecificacaoDeTool | None:
        return self._por_nome.get(nome)

    def ligadas(self) -> tuple[str, ...]:
        """Os nomes com executor, por ordem. Para o arranque e para os testes."""
        return tuple(
            sorted(nome for nome, e in self._por_nome.items() if e.ligada)
        )

    def declaradas(self) -> dict[str, str]:
        """`nome -> credor` das entradas sem executor.

        O arranque escreve-as no log: uma vertical cujas tools estao quase todas
        por ligar nao responde a nada, e isso tem de se ler num painel em vez de
        se descobrir pelo silencio.
        """
        return {
            nome: e.credor
            for nome, e in sorted(self._por_nome.items())
            if not e.ligada and e.credor is not None
        }
