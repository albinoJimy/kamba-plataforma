"""O `ConversaState` base e o estado inicial de um turno (`docs/tecnica/02` §5.3).

O bloco do KAM-025 propoe-o em `kamba/core/state.py`; fica em
`services/agr/src/kamba_agr/estado.py` porque o AGR e o unico processo que o
constroi e o unico que o le, e porque `libs/py-core` e o que **todos** os
servicos Python precisam de fazer da mesma maneira (`index.ts` do `core-ts`
diz a mesma regra do lado Node). Quando o KAM-026 puser o `AsyncPostgresSaver` a
persistir isto, continua a ser o AGR a ler e a escrever.

## As chaves sao as do §5.3, e nenhuma e nova

O §5.3 e um bloco de canon citado: as dezenove chaves abaixo sao as dele, com
os mesmos nomes. **Nao se acrescenta nenhuma** — e o §3 do dicionario a valer: um
nome novo entra no dicionario antes de entrar em codigo.

O que se faz e deixar as sub-estruturas por tipar, como `dict` ou `list`:

| Chave | Quem lhe da forma |
|---|---|
| `stt` | KAM-036 (pipeline de voz) |
| `guard` | KAM-033 (guardrails) |
| `facts` | KAM-028 (ToolLayer) |
| `cart` | KAM-031 (grafo do Vendedor) |
| `slots` | KAM-035 (grafo de Servicos) |
| `draft`, `citation_retries` | KAM-032 (validador de citacao) |
| `handoff`, `handoff_seq` | KAM-034 (handoff em dois nos) |
| `messages`, `summary` | KAM-026 (recorte da janela) |

Tipar aqui qualquer uma delas era decidir por esses tickets, e o bloco deste
diz «nao expandas escopo» pelo nome. O que este ticket entrega e a **chave** com
o nome certo e o valor vazio certo, para que o grafo que vier a seguir nao tenha
de inventar a chave nem o AGR de migrar o estado por causa dela.

## O `schema_version` e o unico campo que este ticket decide

Nasce a `1`. O §5.3 pede-o e o §12 diz o que ele serve: «`ingest` migra estados
antigos». O `ingest` e do KAM-031; o que aqui esta e o numero e a funcao que o
le de um estado que veio da base, para que o dia em que ele subir nao comece com
uma arqueologia. Uma versao **a frente** da que este codigo conhece nao se
migra: levanta, porque degradar um estado futuro e perder o que ele traz.
"""

from __future__ import annotations

from typing import Any, Final

from .contexto import InvocacaoDoAgente

#: A versao do estado que este codigo escreve (`docs/tecnica/02` §5.3).
SCHEMA_VERSION: Final = 1

#: Os valores de `stage` (§5.3). Lista **fechada**: e etiqueta de metrica.
ESTAGIOS: Final = ("browsing", "awaiting_confirm", "awaiting_payment", "done")

#: O `stage` com que um turno comeca.
ESTAGIO_INICIAL: Final = "browsing"

#: Os valores de `input_kind` (§5.3). Nao e o `wa_type` do dicionario §3.12 —
#: sao cinco e os `wa_type` sao doze: e a **classe** de entrada que o grafo
#: distingue, e o mapeamento de um para o outro e do `ingest` (KAM-031).
TIPOS_DE_ENTRADA: Final = ("text", "audio", "interactive", "location", "image")

#: Com que `input_kind` nasce um turno cujo `type` nao casa nenhum dos cinco.
#: O `ingest` do KAM-031 refina; aqui so nao se perde o turno por causa disso.
TIPO_DE_ENTRADA_POR_OMISSAO: Final = "text"


class VersaoDeEstadoAFrenteError(RuntimeError):
    """O estado lido tem `schema_version` maior do que o que este codigo escreve.

    Nao se degrada e nao se ignora. Um estado da versao N+1 traz chaves que
    este codigo nao sabe preservar, e correr um turno sobre ele reescreve-o
    **sem** elas — o que e perder dados de uma conversa a meio. A resposta e
    levantar: o turno nao corre, a mensagem fica na fila, e o alerta diz que ha
    uma replica velha a receber trafego de uma nova (`docs/tecnica/02` §14,
    linha do checkpointer indisponivel).
    """


def estado_inicial(invocacao: InvocacaoDoAgente) -> dict[str, Any]:
    """O estado com que um turno entra no grafo.

    E o `initial_state(ctx)` do esqueleto de codigo do bloco do ticket. Os
    cinco identificadores vem **todos** da invocacao e nenhum do texto: e aqui
    que o «`tenant_id` injectado pelo CHR; imutavel; nunca vem do texto» do
    §5.3 se cumpre, e nao ha outro caminho para dentro do estado.

    `facts` nasce vazio **e e reiniciado em cada turno**, nao acumulado: o §5.3
    di-lo («so deste turno; reiniciado em `ingest`») e a razao e o validador de
    citacao — um *fact* de um turno anterior e um numero sem prova neste.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "tenant_id": invocacao.tenant_id,
        "channel_id": invocacao.channel_id,
        "contact_id": invocacao.contact_id,
        "conversation_id": invocacao.conversation_id,
        "vertical": invocacao.vertical,
        "turn_id": invocacao.turn_id,
        "thread_id": invocacao.thread_id,
        "input_kind": tipo_de_entrada(invocacao.type),
        "messages": [],
        "summary": None,
        "stt": None,
        "guard": None,
        "intent": None,
        "facts": [],
        "cart": None,
        "stage": ESTAGIO_INICIAL,
        "slots": None,
        "draft": None,
        "citation_retries": 0,
        "handoff_seq": 0,
        "handoff": None,
    }


def tipo_de_entrada(wa_type: str) -> str:
    """A classe de entrada de um `wa_type` (§3.12 -> §5.3).

    Mapeamento **minimo**: os `wa_type` cujo nome e o proprio `input_kind`
    passam, e o resto cai em `text`. Nao se escreve aqui a tabela dos doze
    valores — isso e `ingest` (KAM-031), que tem o corpo da mensagem para
    decidir; o que aqui esta e o que impede o estado de nascer com um
    `input_kind` que nao esta nos cinco.
    """
    return wa_type if wa_type in TIPOS_DE_ENTRADA else TIPO_DE_ENTRADA_POR_OMISSAO


def versao_lida(estado: dict[str, Any]) -> int:
    """A `schema_version` de um estado que veio da base.

    Um estado sem a chave conta como `1`: e o que os *threads* escritos antes de
    o campo existir sao, e tratar a ausencia como «desconhecido» obrigava a
    migrar o que nao mudou. Um valor que nao seja inteiro **e** desconhecido, e
    levanta — porque um `schema_version` de texto e um estado que alguem
    escreveu a mao.
    """
    valor = estado.get("schema_version", 1)
    if not isinstance(valor, int) or isinstance(valor, bool) or valor < 1:
        raise VersaoDeEstadoAFrenteError("schema_version_invalida")
    if valor > SCHEMA_VERSION:
        raise VersaoDeEstadoAFrenteError("schema_version_a_frente")
    return valor


def recortar_janela(estado: dict[str, Any], maximo: int) -> dict[str, Any]:
    """Deixa no estado as ultimas `maximo` mensagens, e mais nada muda.

    E o «estado minimo» do `docs/tecnica/02` §12: «janela de mensagens recortada
    (ultimas K, K a calibrar) + `summary`». O `maximo` vem de quem chama — o
    `JANELA_MAXIMA` do `checkpointer.py` — e nao esta aqui para que a constante
    tenha **um** dono.

    **Quem chama isto e o `ingest` (KAM-031), e e por isso que o checkpointer
    nao o faz.** Recortar na gravacao punha o estado em memoria do grafo a
    divergir do que esta na base sem erro nenhum: a leitura seguinte devolvia
    menos mensagens do que a execucao escreveu. O `aput` **levanta** em vez de
    recortar, e esta funcao e a que faz o estado caber antes de la chegar.

    Devolve um `dict` novo: o estado do LangGraph passa por redutores que
    comparam identidade, e mutar a lista no sitio escondia a alteracao de quem
    guardasse a referencia anterior.
    """
    if maximo < 0:
        raise ValueError("a janela nao pode ser negativa")
    mensagens = estado.get("messages")
    if not isinstance(mensagens, list) or len(mensagens) <= maximo:
        return estado
    # As **ultimas**, nao as primeiras: o que uma conversa perde primeiro e o
    # principio, que o `summary` ja resume. `maximo` zero e lista vazia, e nao
    # a lista inteira — que e o que um `[-0:]` daria.
    return dict(estado, messages=mensagens[len(mensagens) - maximo :])
