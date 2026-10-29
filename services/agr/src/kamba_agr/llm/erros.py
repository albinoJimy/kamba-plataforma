"""Os erros tipados do gateway de LLM (KAM-030).

**Nao sao os erros da ToolLayer**, e isso e deliberado. O `tls/erros.py` tem onze
codigos do `docs/tecnica/02` §6.5, e sao o contrato entre o grafo e uma *tool*;
estes sao o contrato entre o grafo e o **modelo**. Juntar os dois punha um
`BUDGET_EXHAUSTED` na lista que a `tool_audit.error_code` tem num `CHECK`
fechado — quatro sitios e uma revisao de base de dados, pela licao que a `0022`
pagou — para descrever uma coisa que nenhuma *tool* faz.

## O mapeamento do orcamento **nao** e pelo 400, e isso corrige o bloco

O criterio 4 diz «com orcamento esgotado o cliente recebe `BUDGET_EXHAUSTED`
(mapeado do **400**)». Medido contra a imagem fixada (`docs/evidencia/KAM-030-litellm.md`
§4, CONFIRMADO), uma chamada com a chave virtual sem orcamento devolve:

    HTTP 422
    {"error": {"message": "Budget has been exceeded! Key=… Current cost: 0.0,
               Max budget: 0.0", "type": "budget_exceeded", "code": "422"}}

**422 e nao 400.** Um mapeamento pelo 400 nunca disparava, e o criterio ficava
satisfeito por nada — a classe de defeito mais cara deste repositorio. Pior: o
proxy **usa** o 400 para outra coisa, e isso tambem se mediu — um
`/key/generate` com um `key_alias` repetido devolve 400 «already exists». Mapear
o 400 para orcamento dizia «sem orcamento» a um erro de provisionamento.

Por isso o reconhecimento e pelo **`error.type`**, que e semantico e estavel, com
o estado como corroboracao e nao como criterio. O `type` desconhecido cai em
`ERRO_FORNECEDOR`, que e o desfecho honesto para «o fornecedor recusou e nao
sabemos classificar».
"""

from __future__ import annotations

import re
from typing import Final

#: Os seis desfechos de uma chamada. **E o dominio de
#: `dat.llm_call_log.resultado`**, e a lista vive aqui e no `CHECK` da revisao
#: `0023`; um teste confronta as duas. Lista fechada: um valor novo e uma
#: revisao de base de dados, nao uma constante.
RESULTADO_OK: Final = "ok"
RESULTADO_OK_FALLBACK: Final = "ok_fallback"
RESULTADO_BUDGET: Final = "budget_exhausted"
RESULTADO_TIMEOUT: Final = "timeout"
RESULTADO_ERRO: Final = "erro_fornecedor"
RESULTADO_DESTINO: Final = "destino_negado"

RESULTADOS: Final = (
    RESULTADO_OK,
    RESULTADO_OK_FALLBACK,
    RESULTADO_BUDGET,
    RESULTADO_TIMEOUT,
    RESULTADO_ERRO,
    RESULTADO_DESTINO,
)

#: O `error.type` que o proxy usa para orcamento esgotado. Medido na versao
#: fixada; ver a nota do modulo.
TIPO_ORCAMENTO: Final = "budget_exceeded"


class ErroDeLlm(RuntimeError):
    """Base dos erros do gateway. `resultado` e o que vai para o registo."""

    #: Um dos `RESULTADOS`. Subclasses fixam-no.
    resultado: str = RESULTADO_ERRO

    def __init__(
        self, mensagem: str, papel: str = "", estado_http: int | None = None
    ) -> None:
        super().__init__(mensagem)
        self.papel = papel
        #: O estado HTTP com que o proxy recusou, quando houve um.
        #:
        #: **Nao e um `resultado` novo, e a distincao e uma revisao de base de
        #: dados.** O `RESULTADOS` e o dominio fechado de
        #: `dat.llm_call_log.resultado`, com `CHECK` na revisao `0023`: dar tipo
        #: proprio ao 429 obrigava a quatro sitios e a uma migracao, pela licao
        #: que a `0022` pagou. Mas o criterio 1 do KAM-037 nomeia o **429** como
        #: gatilho de degradacao ao lado do *timeout* e do orcamento, e sem este
        #: campo a unica forma de o ver era ler a mensagem da excepcao — texto
        #: formatado, que muda quando alguem lhe mexer.
        #:
        #: Fica aqui como atributo de diagnostico: nao vai para a tabela, nao
        #: entra em etiqueta de metrica, e quem o le e o `degradacao.py`.
        self.estado_http = estado_http

    def codigo(self) -> str:
        """O identificador para o `error_code` do *logger*.

        A *allowlist* de `docs/tecnica/08` §7.3 so aceita identificadores — nao
        prosa. E a licao que o KAM-027 pagou com a `Adiada.codigo()`: com prosa,
        o `Logger` em modo estrito **levanta** e aborta o arranque.
        """
        return self.resultado


class OrcamentoEsgotado(ErroDeLlm):
    """O `BUDGET_EXHAUSTED` do criterio 4.

    Quem o apanha e o grafo, e a resposta e degradar para o modo deterministico
    (KAM-037, `docs/tecnica/02` §14) — que **ja existe**: o `classify` do
    Vendedor apanha-o, o `degradacao.py` da-lhe o motivo `budget`, e o turno
    responde pelo menu em vez de falhar. A linha anterior desta *docstring*
    dizia que o modo «nao existe», e deixou de ser verdade com o KAM-037.
    """

    resultado = RESULTADO_BUDGET


class TempoEsgotado(ErroDeLlm):
    """Passou o tecto do alias: 8 s no `router`, 20 s no `chat` (§13.1)."""

    resultado = RESULTADO_TIMEOUT


class FornecedorFalhou(ErroDeLlm):
    """O fornecedor recusou por outra razao, ou nao se soube classificar."""

    resultado = RESULTADO_ERRO


class DestinoNegado(ErroDeLlm):
    """O *gate* de destino recusou a chamada **antes** de ela sair.

    Nao e um erro do fornecedor: e a recusa de uma transferencia de dados
    pessoais para fora de Angola sem destino autorizado (ADR-008). Levanta um
    tipo proprio porque o desfecho e outro, a metrica e outra (e um alerta, nao
    uma estatistica) e porque a linha de registo nao pode levar custo nem
    *tokens* — o `CHECK llm_call_log_negado_sem_consumo` da revisao `0023`
    recusa-a se levar.
    """

    resultado = RESULTADO_DESTINO


class FalhaDeMinimizacao(ErroDeLlm):
    """A minimizacao de PII falhou, e por isso a chamada **nao sai** (KAM-112).

    E a falha fechada do criterio 7 do KAM-112: «erro ou *timeout* do detector
    impede a chamada ao LLM e conduz ao modo deterministico (KAM-037) ou a
    handoff».

    **Vive aqui e nao em `privacidade/`, e e a mesma razao do `DestinoNegado`:**
    nao e um erro do fornecedor, e uma barreira que impede a transferencia antes
    de ela acontecer, e o que a torna util e **ser um `ErroDeLlm`** — o
    `classify` do Vendedor ja apanha esse tipo (`verticais/vendedor/nos.py`), o
    `degradacao.motivo_do_erro` ja o classifica, e o turno responde pelo menu em
    vez de falhar. Posta em `privacidade/`, esta classe obrigava o `classify` a
    um `except` novo e o `degradacao.py` a importar o pacote de privacidade —
    duas alteracoes para nenhum ganho.

    **Nao tem `resultado` proprio, e isso e deliberado.** O `RESULTADOS` e o
    dominio fechado de `dat.llm_call_log.resultado`, com `CHECK` na revisao
    `0023`: um valor novo e uma revisao de base de dados, e a licao esta escrita
    no `estado_http` do `ErroDeLlm` («dar tipo proprio ao 429 obrigava a quatro
    sitios e a uma migracao»). E aqui nao e preciso: esta falha acontece
    **antes** do `chamar`, pelo que **nenhuma linha de `llm_call_log` se escreve
    por causa dela** — o `resultado` nunca chega a ser lido. Quem a distingue e o
    `degradacao.motivo_do_erro`, por `isinstance` e nao por `resultado`.
    """

    resultado = RESULTADO_ERRO


#: A gramatica de um `error.type` que se pode repetir numa mensagem. E a mesma
#: forma que a *allowlist* de `docs/tecnica/08` §7.3 aceita para um
#: `error_code`: letras minusculas, digitos e sublinhado.
_TIPO = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def classificar(estado: int, corpo: object, papel: str = "") -> ErroDeLlm:
    """Traduz uma resposta de erro do proxy num erro tipado.

    `corpo` e o que o proxy devolveu, ja interpretado (um `dict`) ou texto. O
    reconhecimento e pelo `error.type` e **nao** pelo estado: ver a nota do
    modulo, e a medicao em `docs/evidencia/KAM-030-litellm.md` §4.

    ## A mensagem do fornecedor **nao** entra na excepcao

    A primeira versao copiava ate 200 caracteres do corpo para `str(erro)`, e
    isso e uma fuga de conteudo: o proxy devolve o pedido recusado dentro da
    mensagem de erro, pelo que um `{"message": "Invalid value for
    'messages[0].content': 'Bom dia, o meu numero e 923000000'"}` punha um
    telefone de cliente na excepcao. O `/internal/turn` nao apanha `ErroDeLlm`,
    pelo que o *traceback* do uvicorn escrevia-a no *stdout* do contentor — e o
    varrimento de privacidade deste ticket varre as **colunas da tabela**, nao a
    mensagem de uma excepcao. ADR-010 e a linha de privacidade do DoD.
    Encontrado pela revisao adversarial.

    O que fica na mensagem e o **estado** e o `error.type`, e o tipo so se ele
    casar a gramatica de identificador — um fornecedor que puser prosa no `type`
    nao a passa por ali.
    """
    tipo = ""
    if isinstance(corpo, dict):
        erro = corpo.get("error")
        if isinstance(erro, dict):
            tipo = str(erro.get("type") or "")
    seguro = tipo if _TIPO.match(tipo) else "sem_tipo"

    if tipo == TIPO_ORCAMENTO:
        return OrcamentoEsgotado(
            f"o orcamento da chave virtual esgotou-se ({estado}, {seguro})",
            papel,
            estado,
        )
    # 408 e 504 sao tempo; o `httpx` trata o tempo do lado do cliente e nunca
    # chega aqui com estado, mas um proxy intermedio pode responder assim.
    if estado in (408, 504):
        return TempoEsgotado(f"o proxy respondeu {estado} ({seguro})", papel, estado)
    # O **429** sai daqui como `FornecedorFalhou` e **nao** como tipo proprio:
    # ver o `estado_http` do `ErroDeLlm`. Quem o distingue do resto das avarias
    # do fornecedor e o `degradacao.py`, pelo estado.
    return FornecedorFalhou(f"o proxy respondeu {estado} ({seguro})", papel, estado)
