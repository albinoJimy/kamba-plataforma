"""Os textos estaticos do modo deterministico, e os identificadores de opcao.

«Textos estaticos em `pt` de Angola versionados» — o bloco pede o SemVer por
extenso, e ele esta na `VERSAO_DOS_TEXTOS`.

## Estes textos passam pelo `renderizar`, e os do `nos.py` nao

E a diferenca que decide como se escrevem. Os `MSG_*` do `nos.py` saem pelas
arestas da linha 34 (`unknown_reply`, `ask_repeat`, `safe_reply` -> `send`), que
**passam ao lado do `validate`**; os daqui vao num bloco `text` do
`degraded_menu` e atravessam o `renderizar` e as duas camadas do §9.1 — que e o
criterio 5 («o validador aplica-se **tambem** ao modo deterministico: 0 numeros
fora de *facts*»).

Por isso a regra e mais apertada do que «sem digitos», e nao e por estilo:

* **sem digitos**, que o `renderizar` recusa num bloco `text`;
* **sem duas palavras de numero seguidas** — o `extraccao.py` conta uma corrida
  de duas ou mais como numero («doze mil», «vinte e cinco»), e o `renderizar`
  pergunta-lhe. Uma palavra isolada passa, porque sem moeda nem palavra de
  contagem ao lado nao e uma citacao: e conversa (ver o `_extenso_conta`);
* **sem palavra de contagem ao lado de uma palavra de numero** (`unidades`,
  `pecas`, `caixas`…), pela mesma razao.

Ha ensaio que renderiza **todos** os textos deste modulo com zero *facts* e mede
que nenhum levanta — porque uma regra que so vive numa *docstring* e uma regra
que a proxima pessoa nao ve.

## Porque e que os identificadores levam prefixo, e porque nao e `confirm:`

Um identificador de opcao e a forma de o criterio 4 se cumprir sem modelo: «a
intencao e decidida sem LLM (**identificadores de botao/lista** e palavras-chave)».
O prefixo `menu:` separa-os dos dois identificadores que ja existem — o
`confirm:{cart_id}` (§7.3, fluxo de dois turnos) e o `falar_com_humano` — e o
`intencoes.py` traduz cada um numa das nove intencoes do §7.3.

**Nao sao intencoes novas**, e isso e deliberado: as nove do dicionario §3.31
ficam como estao, e o modo deterministico nao acrescenta vocabulario ao
classificador — so uma porta de entrada para o que ja existe. Um identificador
novo que **nao** casasse uma das nove era uma decima intencao por outro nome.

## Tres botoes e dez linhas, e os dois numeros tem fonte diferente

O criterio 2 pede «menu principal (≤ 3 botoes)» e «lista de opcoes (≤ 10
linhas)». **Sao dois limites da Meta e nao um:** tres e o maximo de *reply
buttons* de uma mensagem interactiva, dez e o maximo de linhas de uma lista
(`docs/tecnica/02` §8.2, e e o `MAX_BOTOES` do `validador/render.py`,
CONFIRMADO). O `renderizar` impoe o dez; o tres impoe-se aqui, com ensaio, porque
o bloco `buttons` do §9.1 nao distingue os dois tipos de mensagem interactiva —
e essa indistincao esta registada como o que ela e, uma lacuna do §9.1 que este
ticket **nao** fecha (o `degraded_menu` escolhe pela contagem).
"""

from __future__ import annotations

from typing import Final

#: SemVer dos textos deste modulo. Sobe no *minor* quando um texto entra ou sai,
#: e no *patch* quando um se reescreve sem mudar o que a opcao faz.
#:
#: **E um artefacto comportamental**, como o `llm/aliases.yaml`: mudar o que o
#: menu diz muda o que o produto responde. O que falta e o *lock* e o *golden* —
#: e o gate 13, que **nao existe** e nasce com o KAM-040.
VERSAO_DOS_TEXTOS: Final = "1.0.0"

#: O prefixo de um identificador de opcao do modo deterministico.
PREFIXO_DA_OPCAO: Final = "menu:"

OPCAO_ENCOMENDA: Final = "menu:encomenda"
OPCAO_PAGAMENTO: Final = "menu:pagamento"
OPCAO_LOJA: Final = "menu:loja"
OPCAO_HUMANO: Final = "menu:humano"

#: O menu principal: **tres** opcoes, que e o tecto de *reply buttons* da Meta.
#:
#: Quais tres, e porque estas: o estado de um pedido, a informacao da loja e o
#: colega. A referencia de pagamento fica **fora** do menu principal e dentro da
#: lista, e nao e arbitrario — e a opcao que o modo serve pior (divida 124: a
#: referencia tem digitos e nenhum bloco do §9.1 a leva), pelo que por-la a
#: frente prometia o que o modo nao cumpre.
MENU_PRINCIPAL: Final = (OPCAO_ENCOMENDA, OPCAO_LOJA, OPCAO_HUMANO)

#: A lista de opcoes: **uma linha por capacidade** que o modo serve, e sao
#: quatro. O tecto e dez (`MAX_BOTOES`), e nao se enche: uma lista com opcoes que
#: o modo nao serve era um menu a prometer o que nao faz.
LISTA_DE_OPCOES: Final = (
    OPCAO_ENCOMENDA,
    OPCAO_PAGAMENTO,
    OPCAO_LOJA,
    OPCAO_HUMANO,
)

#: O maximo de *reply buttons* de uma mensagem interactiva da Meta
#: (`docs/tecnica/02` §8.2). O do bloco `buttons` do §9.1 e o de **lista** —
#: dez —, e o `renderizar` so conhece esse; este impoe-se aqui.
MAX_BOTOES_DO_MENU: Final = 3

# ------------------------------------------------------------------- os textos
#
# **Nenhum leva digitos nem duas palavras de numero seguidas** — ver o cabecalho.

#: O que se diz ao servir o menu principal. **Nao nomeia a avaria**, e isso e
#: escolha: «o nosso modelo de linguagem esta em baixo» e informacao interna a
#: chegar ao cliente, e nao o ajuda a decidir nada. Diz-se o que se pode fazer,
#: que e o que «degradar, nunca calar» quer (principio 12).
MSG_MENU: Final = (
    "Neste momento posso ajudar com estas opcoes. Escolha a que precisa."
)

#: O que se diz ao servir a lista, depois de nao se ter reconhecido o pedido.
#:
#: **Nao repete «nao entendi»**, que e o texto do `unknown_reply`: aquele e uma
#: pesquisa sem resultados no catalogo e este e o modo reduzido a dizer o que
#: sabe fazer. Dois textos para duas situacoes.
MSG_LISTA: Final = (
    "Nao consegui tratar esse pedido agora. Posso ajudar com o seguinte."
)

#: O que se diz quando o cliente pede catalogo ou precos em modo deterministico.
#:
#: A pesquisa **nao** esta na lista do criterio 2, e o cliente tem de saber que
#: o pedido nao se perdeu — e a diferenca entre degradar e calar.
MSG_SEM_CATALOGO: Final = (
    "Nao consigo consultar o catalogo da loja neste momento. Pode escrever-me "
    "outra vez mais tarde, ou falar com um colega da loja."
)

#: Os textos deste modulo, para o ensaio que os renderiza todos. **Derivado nao
#: da-se**: sao constantes de modulo e uma lista literal e a unica forma de as
#: nomear — mas ha ensaio que confronta esta tupla com todas as `MSG_*` deste
#: modulo por introspeccao, pelo que um texto novo que nao entre aqui falha.
TEXTOS: Final = (MSG_MENU, MSG_LISTA, MSG_SEM_CATALOGO)


__all__ = [
    "LISTA_DE_OPCOES",
    "MAX_BOTOES_DO_MENU",
    "MENU_PRINCIPAL",
    "MSG_LISTA",
    "MSG_MENU",
    "MSG_SEM_CATALOGO",
    "OPCAO_ENCOMENDA",
    "OPCAO_HUMANO",
    "OPCAO_LOJA",
    "OPCAO_PAGAMENTO",
    "PREFIXO_DA_OPCAO",
    "TEXTOS",
    "VERSAO_DOS_TEXTOS",
]
