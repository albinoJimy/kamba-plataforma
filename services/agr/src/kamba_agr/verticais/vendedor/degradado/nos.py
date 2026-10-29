"""O no do sub-grafo deterministico: o `degraded_menu` (KAM-037).

E **um** no, e a contagem e o resultado de uma decisao: tudo o que o modo
deterministico faz de util — o estado do pedido, o horario e a morada, a
confirmacao de um carrinho, a passagem a humano — ja esta escrito no grafo
normal e **reutiliza-se**, como o bloco manda («reutiliza
`confirm_gate`/`create_order`/`order_status`/`tools_info` do grafo normal»).

O que **nao** existia era o menu. Por isso e so este no que entra.

## E o `compose` que mudava, e nao mudou — porque nao tinha de mudar

O bloco diz «so `classify` e `compose` mudam para versoes sem LLM». Medido: o
`compose` do `nos.py` **nao chama modelo nenhum** — monta blocos a partir dos
*facts*, das ofertas e dos avisos do estado, e o *renderer* preenche-os. O unico
sitio do grafo do Vendedor por onde o LLM entra e o `deps.classificador` do
`classify` (§15.1, «as regras primeiro e o modelo so se elas nao decidirem»), e
esse esta **por ligar** — a `Dependencias.classificador` nasce `None`.

Logo metade da frase do bloco ja estava satisfeita antes deste ticket, e a outra
metade e o `classify`, que passou a nao chamar o modelo quando degradado. Esta
escrito na secção de verificacao do bloco, porque uma frase do ticket que se
cumpre por o codigo ja estar certo e um facto que a proxima pessoa tem de poder
ler sem o remedir.

## O no escreve blocos e **nao** uma resposta estatica

O `_resposta_estatica` do `nos.py` salta o `validate` — e o que as arestas da
linha 34 fazem. Aqui nao serve: o criterio 5 manda o validador aplicar-se
**tambem** ao modo deterministico, e um menu que passasse ao lado do `validate`
era a excepcao que o criterio fecha. Por isso o `degraded_menu` devolve
`draft.blocos` e a aresta leva-o ao `validate`, como o `compose` faz.

**O custo e real e aceita-se:** os textos deste modo passam pelo `renderizar`, que
recusa digitos e prosa numerica — e e por isso que o `textos.py` tem um cabecalho
sobre como se escrevem. Em troca, nao ha caminho de saida do modo degradado que o
validador nao veja.
"""

from __future__ import annotations

from typing import Any

from ..nos import Dependencias, _primeiro_turno
from .intencoes import DE_CATALOGO
from .textos import MSG_LISTA, MSG_MENU, MSG_SEM_CATALOGO, OPCOES


def degraded_menu(deps: Dependencias):
    """O menu do modo deterministico. Tres superficies, e a intencao escolhe.

    | Quando | O que sai |
    |---|---|
    | a intencao e de catalogo (`produto`, `preco_stock`, `comprar`) | `MSG_SEM_CATALOGO` |
    | e o primeiro turno da conversa | `MSG_MENU` |
    | ja se falou e nao se reconheceu o pedido | `MSG_LISTA` |

    **As tres levam as mesmas `OPCOES`**, e sao **tres**: o que muda e o texto e
    nao o conjunto. A primeira versao tinha quatro numa superficie e tres na
    outra, e a revisao adversarial mediu o que isso custava (achado C6) — o
    Outbound fixa `MAXIMO_DE_BOTOES = 3` e recusa o corpo acima disso, pelo que o
    turno degradado mais comum ficava **sem resposta**. Ver o cabecalho do
    `textos.py`.

    **A primeira condicao vem antes da segunda**, e a ordem e a decisao: um
    cliente que abre a conversa a perguntar por um produto tem de ouvir que o
    catalogo nao esta disponivel, e nao um menu que nao responde a pergunta que
    ele fez. Dizer «escolha uma destas opcoes» a quem perguntou por um preco e
    calar com cara de degradar.

    **Nao ha ramo de omissao que siga em frente**, como em todo o grafo: a
    terceira linha da tabela e a omissao, e e a lista — nunca o silencio nem
    texto livre. E o criterio 4 («texto livre nao reconhecido devolve o menu,
    nao inventa resposta») e o que o torna *fail-closed*.
    """

    async def no(estado: dict[str, Any]) -> dict[str, Any]:
        if estado.get("intent") in DE_CATALOGO:
            texto = MSG_SEM_CATALOGO
        elif _primeiro_turno(estado):
            texto = MSG_MENU
        else:
            texto = MSG_LISTA
        # **O rascunho substitui-se e nao se preserva**, ao contrario do que o
        # `compose` faz com o `draft`: um turno que chega ao menu nao tem
        # `dados` de tool nenhuma para dizer — se tivesse, tinha ido ao
        # `order_status` ou ao `tools_info` e nao aqui. Preservar punha no menu
        # os blocos do que uma tool devolveu num ramo que o turno nao tomou.
        return {
            "draft": {
                "blocos": (
                    {"type": "text", "text": texto},
                    {"type": "buttons", "ids": list(OPCOES)},
                )
            }
        }

    return no


#: Os nos que o sub-grafo deterministico acrescenta. O `grafo.py` junta esta
#: tabela a `NOS_DO_GRAFO` do `nos.py`, e e a juncao que o `_conferir_coerencia`
#: confronta com a tabela de arestas.
#:
#: **Vive aqui e nao no `NOS_DO_GRAFO`** para que o `nos.py` nao importe este
#: pacote: ver a nota do `intencoes.py` sobre o ciclo.
NOS_DEGRADADOS = {"degraded_menu": degraded_menu}


__all__ = ["NOS_DEGRADADOS", "degraded_menu"]
