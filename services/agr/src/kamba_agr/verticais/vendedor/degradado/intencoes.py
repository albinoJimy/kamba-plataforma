"""A intencao sem LLM, e o que o modo deterministico serve (criterios 2 e 4).

O criterio 4: «a intencao e decidida sem LLM (identificadores de botao/lista e
palavras-chave); texto livre nao reconhecido devolve o menu, **nao inventa
resposta**».

## Nao ha segundo classificador, e isso e a decisao que importa

A tentacao era escrever aqui um classificador por regras proprio do modo
degradado. Nao se escreve, por uma razao medida: o `intencao_por_regras` do
`nos.py` **ja** e um classificador por regras sem LLM, com oito padroes afinados
pela revisao adversarial do KAM-031 (o `humano` que exige a pessoa como objecto
do pedido, o `comprar` antes do `encomenda`, o `entrega` que saiu do
`encomenda`). Uma segunda copia divergia dele no dia em que alguem corrigisse
uma — e cada divergencia e uma intencao decidida de duas maneiras no mesmo
produto.

O que **e** deste modulo, e so existe aqui:

1. **os identificadores de opcao** (`menu:*`) traduzidos em intencao — e a porta
   que o menu abre, e nao existia;
2. **a lista fechada do que o modo serve**, que e o que decide se o turno segue
   para um no de trabalho ou volta ao menu.

## O que o modo serve, e porque a pesquisa fica fora

O criterio 2 enumera: menu, lista, estado do pedido, horario/morada, referencia
de pagamento ja emitida, e «falar com humano». **A pesquisa de catalogo nao esta
na lista**, e a lista le-se como fechada.

E uma leitura, e tem custo: o IDX nao e o LLM e **nao** esta em baixo quando o
modelo esta, pelo que servir pesquisa aqui era tecnicamente possivel e mais util
ao cliente. O que o impede e a letra do criterio — e a regra da casa e que,
quando a leitura divergir da letra, se escreve a leitura e se **devolve** a
decisao a quem escreveu o criterio. Esta devolvida na secção de verificacao do
bloco; ate ela voltar, as intencoes `produto`, `preco_stock` e `comprar` caem no
menu.

**O `comprar` tambem fica fora, e e a parte menos obvia.** Construir um carrinho
pede o `propose_cart` — uma tool de escrita com preco e stock a serem lidos no
mesmo turno — e o criterio 2 nao a nomeia; o que o criterio **3** nomeia e o
toque em `confirm:{cart_id}` de um carrinho **ja construido**, que e outra coisa.
Servir a compra sem servir a pesquisa dava um carrinho sobre um produto que o
cliente nao pode ter visto neste turno.
"""

from __future__ import annotations

import re
from typing import Final

# **Este modulo importa o `..nos`, e o `..nos` nao importa este.** E a regra que
# mantem o pacote sem ciclo: quem precisa de uma peca do modo degradado dentro do
# `nos.py` (o `classify`) faz o *import* **no corpo da funcao**, que e o idioma
# da casa (ver o `_valores_derivados` do `metricas.py` e o `pediu_cancelamento`
# deste mesmo `nos.py`). Os nos do sub-grafo entram no grafo pelo `grafo.py`, que
# junta as duas tabelas — e nao pelo `NOS_DO_GRAFO`, que e do `nos.py`.
from ..nos import BOTAO_HUMANO, PREFIXO_DE_CONFIRMACAO, intencao_por_regras
from .textos import OPCAO_HUMANO, OPCAO_LOJA, OPCAO_PEDIDO

#: Cada identificador de opcao, na intencao do §7.3 que ele abre. **Nenhuma
#: intencao nova**: ver o cabecalho do `textos.py`.
#:
#: **E consultado pelo `classify` em TODOS os turnos, degradado ou nao**, e a
#: primeira versao so o consultava em modo degradado — o que era o achado C1 da
#: revisao adversarial, e critico: o `degradado` e um campo **do turno** e o
#: botao **fica no ecra do WhatsApp**, pelo que o turno em que o menu sai
#: reconhecia os identificadores e o turno seguinte, com o modelo recuperado,
#: nao os reconhecia. Um `menu:humano` deixava de abrir *handoff* e o
#: identificador cru ia ao modelo como se fosse texto do cliente.
#:
#: E a mesma licao que o `_CANCELAMENTO` do `nos.py` pagou, escrita no proprio
#: ficheiro: «o botao `confirm:{cart_id}` da mensagem anterior continua no ecra
#: do WhatsApp». Um identificador nosso nao depende da saude do modelo.
INTENCAO_DA_OPCAO: Final = {
    OPCAO_PEDIDO: "encomenda",
    OPCAO_LOJA: "info_loja",
    OPCAO_HUMANO: "humano",
}

#: As intencoes que o modo deterministico **serve**, pela lista do criterio 2.
#: Lista **fechada**: o que ficar fora vai ao menu, que e *fail-closed* — o lado
#: seguro de errar e nao inventar resposta.
SERVIDAS: Final = (
    "confirmar",
    "pagamento_estado",
    "encomenda",
    "info_loja",
    "humano",
)

#: A referencia de um pedido, sozinha num turno. **E a segunda metade do achado
#: C2**: sem ela, um cliente que respondesse `ABC-123` a pergunta do
#: `REFERENCIA_EM_FALTA` caia em `outro` e voltava ao menu — a capacidade «estado
#: do pedido» ficava inalcancavel pelo menu, em ciclo.
#:
#: **Vive aqui e nao no `_REGRAS_DE_INTENCAO` do `nos.py`**, e e deliberado: no
#: modo normal o modelo trata um turno destes, e acrescentar o padrao as regras
#: do §15.1 era «um caso que o modelo deixa de ver, e tambem um caso que ninguem
#: reve» — a razao que a lista de regras tem escrita.
#:
#: O padrao e **ancorado** e exige um digito: sem a ancora, qualquer frase com
#: uma palavra curta seguida de numero virava consulta de pedido.
_SO_REFERENCIA: Final = re.compile(r"^\s*([A-Za-z]{1,4}-?\d{1,12})\s*[?.!]?\s*$")

#: As intencoes que o modo **nao** serve e que pedem explicacao propria: o
#: cliente perguntou pelo catalogo, e tem de saber que o pedido nao se perdeu.
#: As outras (`outro`) recebem a lista de opcoes.
DE_CATALOGO: Final = ("produto", "preco_stock", "comprar")


def serve(intencao: str | None) -> bool:
    """Se o modo deterministico tem no de trabalho para esta intencao."""
    return intencao in SERVIDAS


def so_uma_referencia(texto: str) -> bool:
    """Se o turno e **so** a referencia de um pedido. Ver o `_SO_REFERENCIA`."""
    return bool(_SO_REFERENCIA.match(texto))


def intencao_sem_llm(botao: str, texto: str) -> str:
    """A intencao de um turno degradado. **Nunca chama o modelo.**

    A ordem e a decisao, e e a mesma do `classify` do grafo normal:

    1. um `confirm:{cart_id}` e `confirmar` — e dinheiro, e a intencao esta no
       identificador do botao e nao no texto;
    2. um `menu:*` e a intencao que ele abre;
    3. o `falar_com_humano`, que ja existia;
    4. as palavras-chave do `intencao_por_regras`;
    5. e, se nada decidir, `outro` — que o `r_intent` manda ao menu.

    **O botao vem antes do texto**, e nao e indiferente: uma mensagem
    interactiva do WhatsApp traz o identificador **e** o rotulo do botao como
    texto, pelo que ler o texto primeiro fazia o rotulo «Falar com um colega»
    casar o padrao `humano` por acidente — e dava a resposta certa pela razao
    errada, que e a classe de defeito que deixa de dar a resposta certa no dia
    em que alguem mudar o rotulo.
    """
    if botao.startswith(PREFIXO_DE_CONFIRMACAO):
        return "confirmar"
    if botao in INTENCAO_DA_OPCAO:
        return INTENCAO_DA_OPCAO[botao]
    if botao == BOTAO_HUMANO:
        return "humano"
    decidida = intencao_por_regras(texto)
    if decidida is None and so_uma_referencia(texto):
        return "encomenda"
    return decidida or "outro"


__all__ = [
    "DE_CATALOGO",
    "INTENCAO_DA_OPCAO",
    "SERVIDAS",
    "intencao_sem_llm",
    "serve",
    "so_uma_referencia",
]
