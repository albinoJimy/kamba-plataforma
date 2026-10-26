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

#: Os desfechos que **nao** sao sucesso. Derivado e nao escrito a mao: um
#: desfecho novo entra em `RESULTADOS` e aparece aqui sem ninguem se lembrar.
FALHAS: Final = tuple(r for r in RESULTADOS if not r.startswith("ok"))

#: O `error.type` que o proxy usa para orcamento esgotado. Medido na versao
#: fixada; ver a nota do modulo.
TIPO_ORCAMENTO: Final = "budget_exceeded"


class ErroDeLlm(RuntimeError):
    """Base dos erros do gateway. `resultado` e o que vai para o registo."""

    #: Um dos `RESULTADOS`. Subclasses fixam-no.
    resultado: str = RESULTADO_ERRO

    def __init__(self, mensagem: str, papel: str = "") -> None:
        super().__init__(mensagem)
        self.papel = papel

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
    (KAM-037, `docs/tecnica/02` §14) — que **nao existe**. Hoje o turno falha e o
    *job* volta a fila, e e isso que esta escrito na secao de verificacao do
    bloco: a degradacao e do KAM-037 e esta caixa fica por marcar nessa metade.
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


def classificar(estado: int, corpo: object, papel: str = "") -> ErroDeLlm:
    """Traduz uma resposta de erro do proxy num erro tipado.

    `corpo` e o que o proxy devolveu, ja interpretado (um `dict`) ou texto. O
    reconhecimento e pelo `error.type` e **nao** pelo estado: ver a nota do
    modulo, e a medicao em `docs/evidencia/KAM-030-litellm.md` §4.
    """
    tipo = ""
    mensagem = ""
    if isinstance(corpo, dict):
        erro = corpo.get("error")
        if isinstance(erro, dict):
            tipo = str(erro.get("type") or "")
            mensagem = str(erro.get("message") or "")
    if not mensagem:
        mensagem = str(corpo)[:200]

    if tipo == TIPO_ORCAMENTO:
        return OrcamentoEsgotado(
            f"o orcamento da chave virtual esgotou-se ({estado}): {mensagem}", papel
        )
    # 408 e 504 sao tempo; o `httpx` trata o tempo do lado do cliente e nunca
    # chega aqui com estado, mas um proxy intermedio pode responder assim.
    if estado in (408, 504):
        return TempoEsgotado(f"o proxy respondeu {estado}: {mensagem}", papel)
    return FornecedorFalhou(f"o proxy respondeu {estado}: {mensagem}", papel)
