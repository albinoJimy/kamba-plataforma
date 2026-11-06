# `spikes/proxypay-d4` — instrumento de medição do KAM-103

Instrumento do critério 7 do **KAM-103 — Contratos de pagamento: bancos e
facilitadores (D4)**: a verificação empírica do *sandbox* da ProxyPay —
referência por `PUT`, pagamento simulado, `GET /payments`, e os números de
ensaio do OPG. O relatório, com as fichas por contraparte, a matriz
banco × facilitador, a regra ponderada de D4 e o limiar H5, está em
[`docs/tecnica/evidencia/validacao/Pagamentos_Respostas.md`](../../docs/tecnica/evidencia/validacao/Pagamentos_Respostas.md).

**Isto não é código de produção, não é um portão, e é descartável.** Medido: `spikes/` não aparece em `ci/thresholds.yaml`, no `.github/workflows/ci.yaml` nem no `Makefile`. A **única** menção a `spikes/` em configuração de portão é uma **dispensa** em `ci/canon-lint.yaml` para o `.sql` de outro *spike* — ou seja, o *gate* 3b **alcança** `spikes/` por SQL, e este não tem nenhum. O adaptador
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
| 3 | O pagamento simulado (só no *sandbox*) cria o pagamento, **copia** os `custom_fields` da referência **e traz o `amount` pedido** | `E2` §1.2, CONFIRMADO; e o **G4 «Valor exacto»** de `../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §5 |
| 4 | O evento de pagamento traz os seis campos de conciliação, e o **`fee` é um decimal ≥ 0** — não apenas uma chave presente | `E2` §1.2, CONFIRMADO; critério 7 do **KAM-056** |
| 5 | Fila de segurança: `GET /payments` lista o não reconhecido, `DELETE /payments/{id}` remove o nosso, e um `DELETE` de um id **que não existe** não esvazia a fila | `E2` §1.2 |
| 6 | *Webhook* RPS assinado: `X-Signature` = HMAC-SHA256 **do corpo bruto**, com a **própria API key** como segredo, **e o corpo traz o `amount` pedido** | `E2` §1.2, CONFIRMADO; e o G4 |
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

Os três números do OPG são **de ensaio, publicados pelo fornecedor** (`E2`
§1.2). Escrevem-se na forma nacional de nove algarismos, que é a forma em que a
documentação do OPG os publica.

**O quarto número — o «móvel fora da lista» do ensaio 8 — é outra coisa, e é
nosso.** Esse não vem de fonte nenhuma: é escolhido aqui, e por isso sai do
**intervalo ficticio `999`**, que a UIT não atribui a nenhum país e que esta
casa já usa (`../../tools/meta-sim/src/numeros.ts`, `INDICATIVO_FICTICIO`, com
`packages/core-ts/tests_bd/apoio.ts` e `db/tests_entrada/test_entrada.py` a
herdá-lo). A primeira versão usava um `92x` de nove algarismos, com o comentário
«sequencial, e não pertence a ninguém» — e isso era uma **afirmação sem fonte**
sobre um número bem formado da rede móvel angolana, precisamente o que o
`../../tools/meta-sim/src/inventario.ts` diz que nenhuma expressão regular
consegue decidir. Foi achado da revisão adversarial: o *gate* 7 ficava verde
(nove algarismos nus não casam), pelo que nada avermelhava — e era a afirmação
«números de telefone reais: nenhum» que assentava numa conta de três que deixava
o quarto de fora.

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

O `--canario` estraga o *mock* de dezesseis maneiras e **exige que o ensaio
correspondente fique vermelho** em cada uma. **Os dois últimos vieram da revisão
adversarial**, e cada um fechava um ensaio que ficava verde sem medir o seu
predicado:

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
| **`valor-trocado`** | 3 e 6 | **um fornecedor a cobrar 1,00 Kz por uma cobrança de 1.500,00 Kz** — o G4 «Valor exacto» |
| **`fee-nulo`** | 4 | um `fee` presente e vazio, que é a forma provável da falha e a que um ensaio de presença de chave não vê |

A assinatura leva **três** defeitos e não um de propósito. O terceiro é o que
importa mais: assinar o corpo **reserializado** é o erro real desta classe de
integração, porque um cliente que faça `parse` e volte a serializar antes de
verificar fica verde contra um fornecedor correcto e **vermelho** contra um que
mude um espaço — e a ordem certa, verificar sobre os bytes recebidos, está
escrita no próprio `E2` §1.2.

**Os dois defeitos que a revisão adversarial acrescentou valem por si**, porque
cada um fechava um predicado que o relatório dava como medido e não estava:

- **`valor-trocado`.** O `amount` **não atravessava asserção nenhuma**: o ensaio
  2 lia códigos HTTP, o 3 verificava `reference_id` e `custom_fields`, o 4 a
  presença de seis chaves, o 6 a referência no corpo do *callback*. Medido pelo
  revisor com uma mutação de uma linha — a referência a guardar sempre `1.00` —:
  **10 de 10 verdes**, com uma cobrança de 1.500,00 Kz a liquidar por 1,00 Kz.
  Isto é o **G4 «Valor exacto»** de
  `../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md` §5, **regra
  imutável**, e o primeiro caso obrigatório da suite de conformidade do §3.5. O
  valor passa agora por uma constante do ensaio e é exigido em **duas**
  superfícies: o pagamento (ensaio 3) e o corpo assinado do *callback* (ensaio
  6) — porque uma assinatura válida sobre o valor errado é pior do que nenhuma.
- **`fee-nulo`.** O ensaio 4 testava a **presença da chave**, pelo que um
  `fee: null`, `fee: ""` ou `fee: 0` passava e a saída imprimia `fee = None` sem
  avermelhar. O único defeito daquela família apagava a chave, que é a forma
  menos provável de a falha acontecer. O ensaio exige agora um decimal ≥ 0 — e
  importa porque o §3.3 do relatório faz deste campo o instrumento que fecha o
  segundo componente de custo, e o critério 7 do KAM-056 pede-o «em 100% dos
  pagamentos do *sandbox*».

**A revisão adversarial fechou ainda um oráculo importado do alvo, que não tem
defeito de canário porque é do lado do ensaio.** O código do quarto desfecho do
OPG (2010) era **importado do `provedor_mock.py`** — no único sítio onde o
comentário ao lado dizia ter evitado essa armadilha. Medido: trocar a constante
do alvo para `9999` deixava o ensaio 8 **verde**, a imprimir o valor errado como
se fosse o esperado. Agora é literal no `sandbox.py`, e a mesma mutação
avermelha o ensaio 8.

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
- **A regra b do `../../docs/tecnica/04_Pagamentos_Liquidacao_AntiFraude.md`
  §8** — «só reconhecer pagamentos de cobranças nossas». O ensaio 5 mede que um
  `DELETE` de um id **que não existe** não esvazia a fila, e **não é a mesma
  coisa**: a regra b protege contra reconhecer um pagamento **conhecido** que
  venha de outra integração da mesma PME, e a defesa dela é **do nosso cliente**
  (uma chave de API dedicada por PME, e alerta de órfão em vez de `DELETE`), não
  do contrato do fornecedor — a fila do RPS é por chave de API e nenhuma rota
  distingue um pagamento alheio. Um alvo que aceitasse esse `DELETE` passa o
  ensaio 5 limpo. Correcção da revisão adversarial, que mostrou o ensaio a ser
  vendido como medindo a regra b.
- **Preços, prazos, e a estrutura de fundos.** Não são contrato técnico: são as
  perguntas 7 a 10 do `E2` §9, e respondem-se por escrito.
