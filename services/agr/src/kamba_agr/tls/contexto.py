"""O `ToolContext` e a `Confirmation` (`docs/tecnica/02` §6.1).

Estes dois objectos sao a fronteira entre o que o modelo pode influenciar e o
que nao pode, e e por isso que estao num ficheiro so com eles.

## O `ToolContext` constroi-se do **estado**, nunca de texto

«O modelo nunca ve nem fornece `tenant_id`: as tools sao construidas por turno a
partir do contexto do estado» (§6.1). O `de_estado` e o unico caminho para
dentro, e o estado de onde ele le e o que o `estado_inicial` do KAM-025 montou a
partir da `InvocacaoDoAgente` — onde os cinco identificadores vem do CHR e
nenhum do corpo da mensagem.

`frozen=True` nao e estilo: um `ctx.tenant_id = ...` a meio de um turno era a
injeccao que o ADR-015 existe para fechar, e um objecto imutavel nao tem esse
caminho.

## Dois campos nao vem do estado, e nao podem vir

O §5.3 fixa **dezenove** chaves e o `estado.py` escreve que nao se acrescenta
nenhuma. O `run_id` e o `graph_version` nao estao nessas dezenove:

* o `graph_version` e o `version` que a vertical declara em `registry/*.yaml` —
  e configuracao, nao estado de conversa;
* o `run_id` identifica **uma execucao** do grafo. Posto no estado, era gravado
  em cada *checkpoint* um numero que so vale enquanto o processo corre.

Vem por parametro, de quem constroi o contexto (o KAM-031, no `ingest`).

## A `Confirmation` e a prova de L3, e as tres perguntas sao as tres

O `docs/tecnica/08` §4.3 poe a fronteira contra injeccao na camada das tools, e
nao no texto: «escrita so apos **botao interactivo** emitido pelo runtime e
resposta do mesmo BSUID». O critero 4 do bloco traduz isso em tres perguntas, e
as tres tem de dar a mesma resposta:

1. o `botao` e o `confirm:{<referencia>}` que o runtime emitiu, e a referencia e
   a do **argumento** da chamada (o `cart_id` de `criar_pedido`);
2. quem respondeu e o **mesmo** `contact_id` do turno;
3. a resposta e **deste** turno.

Falhar qualquer uma delas nao e um erro de forma: e uma escrita que o cliente
nao autorizou. Nenhuma se pode presumir das outras duas — um botao certo de
outro contacto e o ataque do §4.4 (exfiltracao entre contactos), e um botao
certo do contacto certo num turno antigo e a re-entrega de webhook do §6.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from kamba_core.tenant_guard import normalizar_tenant

#: O prefixo que o runtime poe no `id` de um botao de confirmacao (§6.3).
PREFIXO_DE_CONFIRMACAO: Final = "confirm:"

#: As chaves do estado (§5.3) que o `ToolContext` le. Nenhuma e opcional: um
#: contexto sem `contact_id` nao sabe de quem e o turno, e uma tool com ambito
#: «tenant **e** contacto» (o `get_order_status` do §6.2) deixava de ter como o
#: impor.
CHAVES_DO_ESTADO: Final = (
    "tenant_id",
    "channel_id",
    "contact_id",
    "conversation_id",
    "turn_id",
    "vertical",
)


class ContextoInvalidoError(ValueError):
    """O estado nao tem com que construir um `ToolContext`.

    Levanta e nao devolve erro tipado: nenhum dos dez codigos do §6.5 descreve
    isto, porque nao e uma resposta a uma invocacao — e o turno a nao ter
    identidade, que e um defeito de quem montou o estado. O desfecho certo e o
    turno falhar e o *job* voltar a fila, como no `VersaoDeEstadoAFrenteError`
    do KAM-025.
    """


@dataclass(frozen=True, slots=True)
class ToolContext:
    """De quem e este turno (§6.1). Imutavel, e construido do estado."""

    tenant_id: str
    channel_id: str
    contact_id: str
    conversation_id: str
    turn_id: str
    vertical: str
    run_id: str
    graph_version: str

    @classmethod
    def de_estado(
        cls, estado: dict[str, Any], *, run_id: str, graph_version: str
    ) -> "ToolContext":
        """O unico caminho para dentro. Levanta se faltar identidade.

        O `tenant_id` passa pelo `normalizar_tenant` do KAM-004 e nao por uma
        verificacao de forma propria: e a mesma funcao que o `tenant_guard.tx`
        usa para escrever o `app.tenant_id`, pelo que um valor que aqui passe e
        um valor que a RLS aceita. Duas normalizacoes diferentes para o mesmo
        identificador era um `ToolContext` valido a abrir uma transaccao que
        rebenta no `::uuid`.
        """
        faltam = [
            chave
            for chave in CHAVES_DO_ESTADO
            if not isinstance(estado.get(chave), str) or not estado[chave]
        ]
        if faltam:
            raise ContextoInvalidoError(
                f"o estado nao tem {faltam} com que construir o `ToolContext` "
                "(`docs/tecnica/02` §5.3, §6.1)"
            )
        if not run_id or not graph_version:
            raise ContextoInvalidoError(
                "o `run_id` e o `graph_version` vem de quem constroi o contexto e "
                "nao do estado (§5.3 fecha em dezenove chaves); nenhum pode ser vazio"
            )
        try:
            tenant = normalizar_tenant(estado["tenant_id"])
        except Exception as erro:  # noqa: BLE001 — a razao vai na mensagem
            raise ContextoInvalidoError(
                f"o `tenant_id` do estado nao e um tenant: {erro}"
            ) from erro
        return cls(
            tenant_id=tenant,
            channel_id=estado["channel_id"],
            contact_id=estado["contact_id"],
            conversation_id=estado["conversation_id"],
            turn_id=estado["turn_id"],
            vertical=estado["vertical"],
            run_id=run_id,
            graph_version=graph_version,
        )


@dataclass(frozen=True, slots=True)
class Confirmation:
    """A resposta a um botao de confirmacao emitido pelo runtime (§6.1, §6.3)."""

    botao: str
    contact_id: str
    turn_id: str

    @property
    def referencia(self) -> str:
        """O que vem depois do `confirm:` — o `cart_id` ou o `hold_id`.

        Vazio quando o `botao` nao tem a forma de um botao de confirmacao, e
        isso **nao** se corrige aqui: quem decide e o passo 4 do `invoke`, que
        tem de recusar com `VALIDATION_ERROR` em vez de comparar o vazio com um
        argumento vazio e achar que bate.
        """
        if not self.botao.startswith(PREFIXO_DE_CONFIRMACAO):
            return ""
        return self.botao[len(PREFIXO_DE_CONFIRMACAO) :]

    def autoriza(self, ctx: ToolContext, referencia_esperada: str) -> bool:
        """As tres perguntas do critero 4, e as tres por `and`.

        Nao se devolve qual delas falhou: a mensagem ao cliente e a mesma e o
        codigo e o mesmo, e dizer qual falhou a quem a provocou era um oraculo
        («este `cart_id` existe, o contacto e que nao bate»).
        """
        return bool(
            referencia_esperada
            and self.referencia == referencia_esperada
            and self.contact_id == ctx.contact_id
            and self.turn_id == ctx.turn_id
        )
