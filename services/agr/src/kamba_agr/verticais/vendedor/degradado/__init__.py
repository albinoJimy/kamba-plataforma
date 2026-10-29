"""O sub-grafo deterministico do Vendedor (KAM-037, `docs/tecnica/02` §14).

«Degradar, nunca calar»: com o LLM em baixo, lento, sem orcamento ou com o
disjuntor aberto — e com a fila acima do limiar —, o turno **continua a
responder**, por menus e *templates*, sem passar pelo modelo.

```text
classify --(degradado e a intencao nao e servida)--> degraded_menu --> validate
         --(confirmar)-------------------------> confirm_gate --> create_order
         --(encomenda, pagamento_estado)-------> order_status
         --(info_loja)-------------------------> tools_info
         --(humano)----------------------------> handoff_prepare
```

## O caminho do bloco nao e este, e a arvore ganha

O bloco escreve `kamba/verticals/vendedor/degraded/{graph,intents,templates}.py`.
Nao ha `verticals` nem `degraded` em sitio nenhum desta arvore: a convencao e
**portuguesa** (`verticais/vendedor/{arestas,encaminhadores,fakes,grafo,nos}.py`,
e o `concierge/` que o KAM-114 acrescentou com `maquina.py`, `politica.py`,
`rascunho.py`). Segue-se a arvore; a discrepancia e **residuo textual** e esta
registada em `docs/dividas-documentais.md`.

## Nao e um grafo compilado a parte, e a razao e o *checkpointer*

«Sub-grafo» le-se como **sub-grafo do grafo do Vendedor**: nos e arestas que so
sao alcancaveis em modo degradado, na mesma tabela de `arestas.py` e com `fonte`
propria. Um segundo `build_graph` compilado era uma tentacao, e foi medido o que
custava: os dois grafos partilham o `thread_id` do LangGraph (§12), pelo que
invocar o segundo depois de o primeiro ter escrito um *checkpoint* parcial punha
dois esquemas de canais sobre o mesmo *thread* — e a degradacao a meio de um
turno (o `ErroDeLlm` que o `classify` apanha) obrigava exactamente a isso.

Com os nos dentro do grafo, a degradacao a meio de um turno e **uma aresta** e
nao uma segunda invocacao: o turno responde em **um** turno, que e o criterio 1.

## O que o modo serve, e e lista fechada (criterio 2)

| O que | Por onde |
|---|---|
| menu principal (≤ 3 botoes) | `degraded_menu`, bloco `buttons` |
| lista de opcoes (≤ 10 linhas) | `degraded_menu`, bloco `buttons` (o limite da Meta e do `MAX_BOTOES`) |
| estado do pedido | `order_status`, reutilizado do grafo normal |
| horario e morada | `tools_info`, reutilizado |
| referencia de pagamento **ja emitida** | `order_status` — **parcial**, divida 124 |
| «falar com humano» | `handoff_prepare`, reutilizado |

**A pesquisa de catalogo nao esta na lista, e isso e a letra do criterio.** O
IDX nao e o LLM e nao esta em baixo quando o modelo esta; servir pesquisa aqui
era mais util e **nao** era o que o criterio 2 enumera. As intencoes `produto`,
`preco_stock` e `comprar` caem no menu, e a leitura esta devolvida ao fundador na
secção de verificacao do bloco — **essa continua por decidir**.

**O que ja esta decidido e a interacção com o modo concierge** (`docs/adr/ADR-L005`,
decisao do fundador de 2026-10-29): com a politica activa, a resposta
deterministica **tambem vai a aprovacao humana**. Nao ha codigo de interacção, e e
isso que a torna segura — o caminho degradado sai pelo `send`, que e onde o
KAM-114 intercepta as cinco arestas de saida.

## A referencia de pagamento e a divida 124, e nao se paga aqui

O criterio 2 pede «referencia de pagamento **ja emitida**». Uma referencia e uma
**cadeia opaca com digitos**, e nenhum dos cinco blocos do §9.1 a leva: um
`text` com digitos faz o `renderizar` **levantar** (de proposito — e a regra que
impede prosa numerica, ADR-007), e o `item`, o `total` e o `datetime` estao
presos a um *fact* numerico. A divida 124 ja nomeia este caso por extenso — «a
referencia de pagamento que o §14 manda repetir no modo deterministico» — e o
credor e o **KAM-032**, que tem a superficie do *renderer*.

O que este ticket faz e o que o KAM-034 fez com a `MSG_ALTERNATIVAS`: serve a
intencao **em especie e nao em detalhe** — encaminha para o `order_status`, que
diz a **palavra** do estado do pedido sem os digitos. Alargar a proibicao de
digitos para caber uma referencia era retirar uma barreira, e *minimo* nunca e
isso.

## Os modulos

| Modulo | O que tem |
|---|---|
| `textos` | os textos estaticos em `pt` de Angola, com SemVer, e os identificadores de opcao |
| `intencoes` | a intencao sem LLM: identificadores de botao/lista e palavras-chave |
| `nos` | o `degraded_menu` |

**Nada se reexporta daqui**, pela razao do `concierge/__init__.py`: quem precisa
de um nome importa-o do modulo que o define.
"""

from __future__ import annotations

__all__: list[str] = []
