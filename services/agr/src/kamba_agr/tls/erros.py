"""Os dez erros tipados da ToolLayer (`docs/tecnica/02` §6.5) e o `ToolResult`.

O §6.5 e uma tabela de canon: dez codigos, cada um com o tratamento que o grafo
lhe da. Esta lista e **fechada** — um codigo novo entra no dicionario §3.27
antes de entrar aqui, porque e por ele que o grafo decide se repete, se compoe
uma resposta ou se levanta alerta de seguranca.

## Dois codigos nao nascem aqui, e nao se redeclaram

O `ENTITLEMENT_DENIED` e o `LIMIT_EXCEEDED` sao os que o `hook_de_tool` do
KAM-009 **ja devolve** (`kamba_core.ten.hook`), e o passo 2 do pipeline e esse
*hook* e nao codigo novo. Importam-se de la: duas constantes com o mesmo valor
em dois ficheiros e uma divergencia a espera de acontecer, e o dia em que o TEN
mudasse a grafia de uma delas o grafo deixava de reconhecer a recusa.

## Porque e que o erro nao e uma excepcao

Um `ToolResult` com `ok=False` e `error` preenchido, e nao uma excepcao, porque
**os dez sao respostas previstas** e o grafo decide sobre elas: o §6.5 da, por
cada um, o que `compose` faz. Uma excepcao obrigava cada no do grafo a embrulhar
a chamada num `except`, e e assim que uma recusa prevista deixa de se distinguir
de um defeito — a mesma razao que o KAM-027 escreveu para o `Resolucao` do
`resolve`.

O que **e** excepcao e o que nao e resposta: um contexto malformado, uma
especificacao invalida, uma tool `write` sem chave de idempotencia. Sao defeitos
de quem chama e levantam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from kamba_core.ten.entitlements import CODIGO_ENTITLEMENT_TOOL, CODIGO_LIMITE

#: Estado de negocio: o `compose` explica ao cliente (§6.5, primeira linha).
NOT_FOUND: Final = "NOT_FOUND"
OUT_OF_STOCK: Final = "OUT_OF_STOCK"
PRICE_CHANGED: Final = "PRICE_CHANGED"

#: Limite do plano ou do `ManualProvider`: mensagem honesta e oferta de handoff.
#: O valor vem do TEN, que e quem o devolve (KAM-009).
LIMIT_EXCEEDED: Final = CODIGO_LIMITE

#: Violacao: bloqueio, alerta de seguranca, `safe_reply`; **nunca** repetir.
ENTITLEMENT_DENIED: Final = CODIGO_ENTITLEMENT_TOOL
TOOL_NOT_ALLOWED: Final = "TOOL_NOT_ALLOWED"
TENANT_MISMATCH: Final = "TENANT_MISMATCH"

#: Backend indisponivel: um retry com *backoff*, depois handoff (decisao do
#: grafo; a camada nao repete nada por si).
UPSTREAM_TIMEOUT: Final = "UPSTREAM_TIMEOUT"
UPSTREAM_DOWN: Final = "UPSTREAM_DOWN"

#: Argumentos invalidos do modelo: uma correccao automatica, depois
#: `unknown_reply`.
VALIDATION_ERROR: Final = "VALIDATION_ERROR"

#: Os dez, pela ordem do §6.5. Lista **fechada**.
CODIGOS: Final = (
    NOT_FOUND,
    OUT_OF_STOCK,
    PRICE_CHANGED,
    LIMIT_EXCEEDED,
    ENTITLEMENT_DENIED,
    TOOL_NOT_ALLOWED,
    TENANT_MISMATCH,
    UPSTREAM_TIMEOUT,
    UPSTREAM_DOWN,
    VALIDATION_ERROR,
)

#: Os que o §6.5 classifica como **violacao**, e que por isso levantam alerta de
#: seguranca e nunca se repetem.
VIOLACOES: Final = (ENTITLEMENT_DENIED, TOOL_NOT_ALLOWED, TENANT_MISMATCH)

#: As naturezas de *fact* que o §6.2 nomeia. Lista **fechada** (dicionario
#: §3.27): um `kind` novo entra la com a tool que o produz.
KINDS: Final = ("price", "stock", "total", "datetime")


class CodigoDesconhecidoError(ValueError):
    """Um codigo fora dos dez do §6.5.

    Levanta em vez de passar porque o grafo decide **pelo codigo**: um codigo
    que ele nao conheca cai no caminho de omissao, e o caminho de omissao de uma
    violacao nao e o de um estado de negocio.
    """


@dataclass(frozen=True, slots=True)
class ErroDeTool:
    """Um dos dez codigos do §6.5, com o detalhe para o registo.

    O `detalhe` **nao vai para o cliente** e **nao vai para a `tool_audit`**: a
    tabela guarda o `error_code` e mais nada (§6.4). Vai para o log do servico,
    onde a *allowlist* do `docs/tecnica/08` §7.3 o aceita como campo nomeado.
    """

    codigo: str
    detalhe: str = ""

    def __post_init__(self) -> None:
        if self.codigo not in CODIGOS:
            raise CodigoDesconhecidoError(
                f"{self.codigo!r} nao e um dos dez erros de `docs/tecnica/02` §6.5: "
                f"{list(CODIGOS)}"
            )

    @property
    def e_violacao(self) -> bool:
        """Se o §6.5 manda bloquear, alertar e nunca repetir."""
        return self.codigo in VIOLACOES


@dataclass(frozen=True, slots=True)
class Fact:
    """Um numero que veio de uma tool, com a prova de onde veio (ADR-007).

    «O numero e prova, o texto nao»: preco, stock e totais so existem no
    Registo, e o modelo cita-os por `fact_id`. O validador de citacao do
    KAM-032 e quem confronta a resposta gerada com esta lista.

    O `retrieved_at` nao e decoracao: um `stock` de ha dez minutos e um numero
    diferente de um `stock` de agora, e e o que permite a um no decidir se
    volta a perguntar.
    """

    fact_id: str
    kind: str
    value: Any
    retrieved_at: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(
                f"{self.kind!r} nao e um `kind` do `docs/tecnica/02` §6.2: {list(KINDS)}"
            )
        if not self.fact_id:
            raise ValueError("um `Fact` sem `fact_id` nao se consegue citar (ADR-007)")


@dataclass(frozen=True, slots=True)
class ToolResult:
    """O que `invoke` devolve (§6.1).

    `ok` e `error` sao dois lados da mesma moeda e ha um invariante: ou um, ou o
    outro. Um `ok=True` com `error` e um `ok=False` sem `error` sao a mesma
    classe de resultado ilegivel, e e o mesmo invariante que o `CHECK`
    `tool_audit_erro_tem_codigo` impoe na base.
    """

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    facts: tuple[Fact, ...] = ()
    error: ErroDeTool | None = None
    #: **Sempre `False` neste ticket.** Quem o poe a `True` e o KAM-029, quando
    #: a chave de idempotencia encontrar um resultado guardado (§6.3).
    idempotent_replay: bool = False

    def __post_init__(self) -> None:
        if self.ok and self.error is not None:
            raise ValueError("um resultado `ok` nao leva erro")
        if not self.ok and self.error is None:
            raise ValueError("um resultado que falhou tem de dizer com que codigo")


def falha(codigo: str, detalhe: str = "") -> ToolResult:
    """O resultado de uma recusa. Existe porque se escreve dez vezes."""
    return ToolResult(ok=False, error=ErroDeTool(codigo=codigo, detalhe=detalhe))
