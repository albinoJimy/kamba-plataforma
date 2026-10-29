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

## Tres opcoes, e porque e que nao sao quatro nem dez

O criterio 2 pede «menu principal (≤ 3 botoes)» e «lista de opcoes (≤ 10
linhas)». Sao dois **tectos** da Meta e nao um: tres e o maximo de *reply
buttons* de uma mensagem interactiva, dez e o maximo de linhas de uma lista
(`docs/tecnica/02` §8.2, e e o `MAX_BOTOES` do `validador/render.py`,
CONFIRMADO).

**Serve-se um conjunto de tres, e os dois tectos ficam satisfeitos pelo mesmo
conjunto.** A primeira versao tinha quatro opcoes na «lista» e tres no «menu», e
a revisao adversarial mediu o que isso custava (achado C6): o bloco `buttons` do
§9.1 **nao distingue** *reply buttons* de lista — nem o `PortaDeSaida.enfileirar`,
que recebe `botoes: Sequence[str]` e mais nada —, pelo que quem mapeasse o bloco
para o `Corpo` do Outbound nao tinha por onde escolher. E o Outbound ja tem a
regra escrita: `packages/core-ts/src/outbound/contrato.ts` fixa
`MAXIMO_DE_BOTOES = 3` e o `decisao.ts` devolve `TOO_MANY_BUTTONS` acima disso —
isto e, **o turno degradado mais comum ficava sem resposta**, que e o oposto do
criterio 1.

Tres e o unico numero que e valido nos **dois** mapeamentos possiveis, e e por
isso que e este: *fail-closed*. O que fica em divida, com credor, e a **forma de
lista** — e nao o tecto dela: quem mapear o bloco `buttons` para um `Corpo` do
Outbound precisa de saber se e `botoes` ou `lista`, e de um **rotulo** por opcao
(o `Corpo` exige `{id, titulo}`). Os rotulos ja existem aqui, em `pt` de Angola e
versionados (`ROTULO_DA_OPCAO`), porque o criterio pede «textos estaticos em `pt`
de Angola versionados» e um identificador cru no ecra do cliente nao e um texto;
o que falta e a porta por onde eles passem, e isso e a superficie do **KAM-015**.
"""

from __future__ import annotations

from typing import Final

#: SemVer dos textos deste modulo. Sobe no *minor* quando um texto entra ou sai,
#: e no *patch* quando um se reescreve sem mudar o que a opcao faz.
#:
#: **1.1.0:** a revisao adversarial juntou duas opcoes numa (`menu:pedido`),
#: acrescentou o `MSG_PEDE_REFERENCIA` e os rotulos. Um texto entrou e dois
#: identificadores sairam, pelo que sobe no *minor* — e e a primeira vez que esta
#: constante se move, o que e o que ela existe para tornar visivel.
#:
#: **E um artefacto comportamental**, como o `llm/aliases.yaml`: mudar o que o
#: menu diz muda o que o produto responde. O que falta e o *lock* e o *golden* —
#: e o gate 13, que **nao existe** e nasce com o KAM-040.
VERSAO_DOS_TEXTOS: Final = "1.1.0"

#: O prefixo de um identificador de opcao do modo deterministico.
PREFIXO_DA_OPCAO: Final = "menu:"

#: O estado de um pedido **e** a referencia de pagamento dele. **Uma opcao e nao
#: duas**, e a juncao e a correccao do achado C2: as duas davam a chave `status`,
#: iam as duas ao `order_status`, e as duas precisam da mesma coisa — a
#: referencia. Duas portas para a mesma pergunta gastavam duas das tres que a
#: Meta permite.
OPCAO_PEDIDO: Final = "menu:pedido"
OPCAO_LOJA: Final = "menu:loja"
OPCAO_HUMANO: Final = "menu:humano"

#: As opcoes que o modo serve. **Tres**, e e o conjunto unico das duas
#: superficies do criterio 2 — ver o cabecalho.
OPCOES: Final = (OPCAO_PEDIDO, OPCAO_LOJA, OPCAO_HUMANO)

#: O maximo de *reply buttons* de uma mensagem interactiva da Meta
#: (`docs/tecnica/02` §8.2), que o `packages/core-ts/src/outbound/contrato.ts`
#: ja fixa como `MAXIMO_DE_BOTOES`. **E o tecto efectivo deste modo**, porque e
#: o menor dos dois mapeamentos possiveis do bloco `buttons`.
MAX_BOTOES_DO_MENU: Final = 3

#: O rotulo de cada opcao, em `pt` de Angola. **Nenhum leva digitos**, pela mesma
#: regra dos textos: um rotulo e texto que chega ao cliente.
#:
#: **Existem e ainda nao tem por onde sair**, e isso e divida com credor: o
#: `PortaDeSaida.enfileirar` recebe `botoes: Sequence[str]` — identificadores — e
#: o `Corpo` do Outbound exige `{id, titulo}`. Declaram-se aqui porque o criterio
#: pede textos estaticos em `pt` de Angola **versionados**, e um identificador
#: cru (`menu:pedido`) no ecra do cliente nao e um texto. Credor: **KAM-015**,
#: que tem a superficie do Outbound. Apanhado pela revisao adversarial (C6).
ROTULO_DA_OPCAO: Final = {
    OPCAO_PEDIDO: "O meu pedido",
    OPCAO_LOJA: "Horario e morada",
    OPCAO_HUMANO: "Falar com um colega",
}

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

#: O que se diz a quem toca em «O meu pedido» sem ter dito qual.
#:
#: **Existe porque a opcao era inalcancavel sem ele** (achado C2): o
#: `order_status` procura a referencia **no texto do cliente**, e no turno de um
#: toque o texto do turno *e* o identificador do botao. Sem esta pergunta, o
#: cliente recebia «Nao encontrei esse artigo no catalogo da loja» — a frase de
#: catalogo a quem pediu um pedido.
#:
#: **Nao e este texto que o `order_status` usa**: quem o diz e o `compose`, pelo
#: aviso `REFERENCIA_EM_FALTA`, para que a mesma pergunta valha no modo normal.
#: Fica aqui como o rotulo da intencao, e e o que o menu diz quando ja perguntou.
MSG_PEDE_REFERENCIA: Final = (
    "Diga-me a referencia do pedido e eu consulto-o. Ou escolha outra opcao."
)

#: Os textos deste modulo, para o ensaio que os renderiza todos. **Derivado nao
#: da-se**: sao constantes de modulo e uma lista literal e a unica forma de as
#: nomear — mas ha ensaio que confronta esta tupla com todas as `MSG_*` deste
#: modulo por introspeccao, pelo que um texto novo que nao entre aqui falha.
TEXTOS: Final = (MSG_MENU, MSG_LISTA, MSG_SEM_CATALOGO, MSG_PEDE_REFERENCIA)


__all__ = [
    "MAX_BOTOES_DO_MENU",
    "MSG_LISTA",
    "MSG_MENU",
    "MSG_PEDE_REFERENCIA",
    "MSG_SEM_CATALOGO",
    "OPCAO_HUMANO",
    "OPCAO_LOJA",
    "OPCAO_PEDIDO",
    "OPCOES",
    "PREFIXO_DA_OPCAO",
    "ROTULO_DA_OPCAO",
    "TEXTOS",
    "VERSAO_DOS_TEXTOS",
]
