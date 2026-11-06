# `spikes/proxypay-d4` — instrumento de medição do KAM-103

Instrumento do critério 7 do **KAM-103 — Contratos de pagamento: bancos e
facilitadores (D4)**: a verificação empírica do *sandbox* da ProxyPay —
referência por `PUT`, pagamento simulado, `GET /payments`, e os números de
ensaio do OPG. O relatório, com as fichas por contraparte, a matriz
banco × facilitador, a regra ponderada de D4 e o limiar H5, está em
[`docs/tecnica/evidencia/validacao/Pagamentos_Respostas.md`](../../docs/tecnica/evidencia/validacao/Pagamentos_Respostas.md).

**Isto não é código de produção, não é um portão, e é descartável.** O adaptador
ProxyPay é o **KAM-056**, e não entra código de pagamentos na `main` por causa
deste *spike*. O que está aqui é o mínimo que torna **mensuráveis** os predicados
do contrato que o
[`../../docs/tecnica/evidencia/E2_Pagamentos_Angola.md`](../../docs/tecnica/evidencia/E2_Pagamentos_Angola.md)
§1.2 dá como CONFIRMADO. Se D4 fechar na ProxyPay, o adaptador nasce no KAM-056
e esta pasta apaga-se.

## Como se corre

Precisa de **Python 3.11+** e de nada mais: biblioteca padrão, sem dependências,
sem Docker, sem rede para fora. Não precisa de `node` nem de `pnpm` — nesta
máquina não existem.

```bash
python spikes/proxypay-d4/sandbox.py
```

```bash
python spikes/proxypay-d4/sandbox.py --canario
```

A primeira forma é a que o ticket exige: **corre contra um *mock* antes de tocar
no fornecedor**. A segunda prova que os ensaios reprovam quando devem.

> **A corrida contra o fornecedor não está feita, e não é «correr e ler».**
> Faltam **duas** coisas e não uma, e cada uma tem credor escrito no §11 do
> relatório:
>
> 1. **As chaves de *sandbox***, que se pedem à TimeBoxed. Pedir chaves é
>    contacto com contraparte, e contacto com contraparte é acto do **fundador**.
>    Sem `PROXYPAY_API_KEY` e `PROXYPAY_OPG_TOKEN` no ambiente, a forma
>    `--base` recusa-se a arrancar em vez de correr metade.
> 2. **Adaptar o cliente** ao contrato real. O que este cliente fala é o
>    contrato do `provedor_mock.py`, e duas peças dele são **inventadas**: a
>    rota de configuração do *callback* do RPS (na ProxyPay isso faz-se no
>    portal, não por API) e o corpo do pagamento simulado. Devolvido ao
>    Engenheiro de Pagamentos, no §8.3 do relatório.

## O que mede

| # | Predicado | Fonte do facto |
|---|---|---|
| 1 | `PUT /references/{id}` devolve **204**, e repetir com o mesmo id **não** deixa uma segunda referência pagável | `E2` §1.2, CONFIRMADO |
| 2 | Limites do `amount` do API: 0,01 e 99.999.999,99 aceitam; 0,00 e 100.000.000,00 recusam | `E2` §1.2, CONFIRMADO |
| 3 | O pagamento simulado (só no *sandbox*) cria o pagamento **e copia** os `custom_fields` da referência | `E2` §1.2, CONFIRMADO |
| 4 | O evento de pagamento traz os seis campos de conciliação, **`fee` incluído** | `E2` §1.2, CONFIRMADO |
| 5 | Fila de segurança: `GET /payments` lista o não reconhecido, `DELETE /payments/{id}` remove o **nosso**, e um `DELETE` de id desconhecido **não** esvazia a fila | `E2` §1.2 + `../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §8 regra b |
| 6 | *Webhook* RPS assinado: `X-Signature` = HMAC-SHA256 **do corpo bruto**, com a **própria API key** como segredo | `E2` §1.2, CONFIRMADO |
| 7 | Dois esquemas de autenticação — `Token` no RPS, `Bearer` no OPG — e a credencial de um **não** serve no outro | `E2` §1.2, CONFIRMADO |
| 8 | OPG: `900000000` aceita, `900002004` rejeita com 2004, `900003000` rejeita com 3000, e um móvel fora da lista rejeita com 2010 | `E2` §1.2, CONFIRMADO |
| 9 | OPG `Idempotency-Key`: a mesma chave duas vezes devolve **uma** transacção | `E2` §1.2, CONFIRMADO |
| 10 | **INSTRUMENTO:** o *callback* do OPG chegou, e os cabeçalhos ficaram registados | — |

### O predicado 10 não é um predicado sobre a ProxyPay

Se o *callback* do OPG é assinado é **NÃO VERIFICADO**: o `E2` §1.2 diz que a
documentação do OPG não menciona assinatura e manda **assumir que não é
assinado**. O *mock* envia-o **sem** assinatura por **escolha nossa**, a
espelhar essa instrução — pelo que uma asserção «não vem assinado» mediria a
nossa escolha, e uma asserção «vem assinado» mediria uma coisa que ninguém
verificou. É a mesma distinção que o KAM-126 fez no seu predicado 7.

O que o ensaio 10 mede é o **instrumento**: que o receptor existe, que recebeu, e
que guardou **todos** os cabeçalhos que vierem — não só os que alguém escolheu
procurar de antemão. É isso que serve para responder à pergunta quando ela for
feita. Quem a fecha é a resposta escrita da TimeBoxed (pergunta 8 do `E2` §9).

A saída di-lo na cara, e o ensaio lista o que viu:

    callback do OPG recebido em /callback/opg; cabecalhos registados:
    ['Connection', 'Content-Type', 'User-Agent']; com aparencia de assinatura:
    nenhum (contra o MOCK: nao diz nada sobre a ProxyPay)

### Os números do OPG, e porque não entram no inventário do *gate* 7

Os três números são **de ensaio, publicados pelo fornecedor** (`E2` §1.2), são
sequenciais, e não pertencem a ninguém. Escrevem-se na forma nacional de nove
algarismos, que é a forma em que a documentação do OPG os publica.

Medido: **nenhum dos três é apanhado pelo varrimento de telefones do *gate* 7**
(`tools/meta-sim`, comando `varrer`), e por isso **nenhum ficheiro deste *spike*
leva entrada no `INVENTARIO`** de `../../tools/meta-sim/src/inventario.ts`. Os
dois padrões de `../../tools/meta-sim/src/numeros.ts` exigem o indicativo `244`
(`telefone_ao`) ou um E.164 entre aspas e com `+` (`e164_entre_aspas`); nove
algarismos nus não casam nenhum dos dois. A medição, com o método e a sua
limitação, está no §8.4 do relatório — e é por isso que o `E2`, que já traz os
três desde a emissão, também não tem entrada no inventário.

**Uma entrada a mais seria um defeito, e não precaução.** O inventário recusa
entradas mortas: uma que declarasse ocorrências num ficheiro onde o varrimento
não encontra nenhuma avermelha o portão. A regra está escrita no topo do próprio
`inventario.ts`.

## O canário, e porque existe

O `provedor_mock.py` guarda de facto o id da referência, remove de facto da fila
o que foi reconhecido, e assina de facto sobre os bytes que viajam. **Um falso
que decidisse pelo nome do ensaio ficava verde com a implementação apagada** — e
o relatório teria uma linha de evidência que não media predicado nenhum.

O `--canario` estraga o *mock* de catorze maneiras e **exige que o ensaio
correspondente fique vermelho** em cada uma:

| Defeito injectado | Ensaio que tem de avermelhar | O que fica sem medida sem ele |
|---|---|---|
| `put-nao-idempotente` | 1 | o cliente final cobrado duas vezes pela mesma cobrança |
| `amount-fora-do-intervalo-aceito` | 2 | uma cobrança criada fora do intervalo que o API aceita |
| `custom-fields-perdidos` | 3 | a reconciliação sem saber de que cobrança é o dinheiro |
| `pagamento-sem-fee` | 4 | o custo real por transacção, que é uma coluna da matriz |
| `delete-nao-remove` | 5 | reconciliação a reprocessar para sempre o mesmo pagamento |
| `delete-de-id-desconhecido-remove` | 5 | **reconhecer um pagamento que não é nosso**, e roubá-lo à PME |
| `assinatura-de-outro-corpo` | 6 | um *callback* forjado aceite como autêntico |
| `assinatura-com-outra-chave` | 6 | idem, por outra via |
| `assinatura-sobre-corpo-reserializado` | 6 | um cliente que verifique o HMAC **depois** do `parse` |
| `auth-partilhada` | 7 | um adaptador com uma só credencial para dois esquemas |
| `opg-aceita-sempre` | 8 | mercadoria entregue contra um pagamento recusado |
| `opg-codigo-de-recusa-errado` | 8 | a mensagem errada ao cliente em WhatsApp (2004 por 3000) |
| `idempotency-key-ignorada` | 9 | duplo toque no WhatsApp a gerar dois pedidos ao Express |
| `opg-sem-callback` | 10 | o receptor a não medir nada, e o ensaio a dizer que mediu |

A assinatura leva **três** defeitos e não um de propósito. O terceiro é o que
importa mais: assinar o corpo **reserializado** é o erro real desta classe de
integração, porque um cliente que faça `parse` e volte a serializar antes de
verificar fica verde contra um fornecedor correcto e **vermelho** contra um que
mude um espaço — e a ordem certa, verificar sobre os bytes recebidos, está
escrita no próprio `E2` §1.2.

**O defeito que mais valeu foi o `put-nao-idempotente`, e valeu por ter falhado
primeiro.** A primeira versão do ensaio 1 comparava o **conjunto** de
`reference_id` na fila, e a primeira versão do defeito renumerava a referência
duplicada. Resultado: 13 de 14 vermelhos, e o ensaio 1 **verde com o defeito
injectado** — uma referência a mais com id novo não é observável por nenhuma
rota documentada. Os dois lados mudaram: o defeito passou a deixar duas
referências pagáveis **sob o mesmo id**, e o ensaio passou a **contar** os
pagamentos que um só pagamento simulado produz. Foi o canário a apanhar o
ensaio, e não o contrário.

**O que o canário não prova:** que a lista de defeitos esgota as maneiras de
quebrar o contrato. A saída di-lo.

## O que este *spike* não mede, e está dito na saída

- **A janela de 5 minutos da `Idempotency-Key`.** Medi-la obrigava a esperar
  cinco minutos ou a mentir sobre o relógio do *mock*; a segunda media o relógio
  e não o contrato. O ensaio 9 prova a idempotência, não a sua expiração.
- **Os 30 minutos de expiração do pedido OPG**, pela mesma razão.
- **O *rate limit* (HTTP 429).** O `E2` §1.2 dá a sua **existência** como
  CONFIRMADA e o **valor** como NÃO VERIFICADO; um *mock* com um valor
  inventado punha o ensaio a validar o número que nós escolhemos.
- **Preços, prazos, e a estrutura de fundos.** Não são contrato técnico: são as
  perguntas 7 a 10 do `E2` §9, e respondem-se por escrito.
