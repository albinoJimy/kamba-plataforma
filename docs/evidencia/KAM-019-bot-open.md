# KAM-019 — o spike do L7: o token do *agent bot* passa `pending → open`?

| Campo | Valor |
|---|---|
| Ticket | KAM-019 — HND: `HandoffProvider` e Chatwoot |
| Critério | 8 — «Spike de 1 dia concluído …» |
| Lacuna | **L7**, NÃO VERIFICADO (`../tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §18) |
| Imagem | `chatwoot/chatwoot:v4.18.0`, fixada por digest em `ci/supply-chain/imagens.yaml` |
| Dados | **sintéticos**. Nenhum dado de pessoa real entrou nesta instância |
| Como se reproduz | `make chatwoot-spike` |
| Veredicto | **NAO CONCLUIDO** |

## O que aconteceu, passo a passo

| Passo | Desfecho | Nota |
|---|---|---|
| arranque | OK | /api respondeu 200 |
| sem credenciais da Meta | OK | as tres ausentes no `env` do contentor a correr |
| token da Platform API | OK | 24 caracteres |

## O que este resultado decide

O critério 8 pede que «a implementação usa a opção que funciona (bot ou
utilizador-serviço)». A opção está no `abrirConversa` de
`packages/core-ts/src/hnd/chatwoot.ts`, e é o **único** método que muda
entre as duas: o resto do cliente usa o *token* do bot para operações que
a documentação do Chatwoot já dá como permitidas.

Se o veredicto for `O TOKEN DO BOT NAO CHEGA`, o plano B é o que o
`../tecnica/01_Canais_WhatsApp_Fluxo_Dual.md` §11.3 já escreve — um
utilizador-serviço «KAMBÁ Bot» com *token* da Application API —, e o que
ele custa é um segredo a mais por conta.

Se for `NAO CONCLUIDO`, **a pergunta continua aberta** e a caixa do
critério 8 fica vazia. A tabela acima diz em que passo parou, e isso é o
que um spike deve deixar: um spike que escrevesse «funciona» sem ter
chegado ao passo que decide fechava uma pergunta aberta com uma resposta
inventada.

## Controlo de versões

| Versão | Data | Alteração |
|---|---|---|
| 1.0 | Outubro 2026 | Criado pelo KAM-019. |
