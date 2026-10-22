# Monitorização do *free tier* de *service messages* (KAM-023)

| Campo | Valor |
|---|---|
| Ticket | KAM-023 |
| Módulo | `packages/core-ts/src/metering/` |
| Depende de | KAM-015 (saída de canal), KAM-009 (`platform.ten_periodo`) |
| Consumido por | KAM-081 (painel de custos), KAM-115 (aviso ao dono), KAM-094 (gate de activação) |
| Estado | **Entregue em duas metades**, a de código e a revisão `0013`. Ver §6. |

## 1. O que o módulo faz

Mantém, por canal e por mês, quantas *service messages* foram **entregues** —
o contador que decide se a próxima é grátis. Daí tira três coisas: um aviso ao
atravessar 80% do tecto e outro ao atravessar o tecto, uma estimativa do custo
acima dele, e uma suspeita de que a PME não tem método de pagamento válido.

Os factos que o justificam são **CONFIRMADOS** em
[`tecnica/evidencia/E1_Meta_WhatsApp.md`](tecnica/evidencia/E1_Meta_WhatsApp.md)
§1: desde 2026-10-01 só as primeiras **1.000** *service messages* entregues por
número e por mês são grátis (sem acumular, com reinício às 00:00 do fuso da
conta); acima disso custam **0,004 USD** cada; e **sem método de pagamento na
conta a Meta entrega as do *free tier* e deixa de entregar depois** — uma falha
silenciosa que só se vê nos estados `failed`.

## 2. As quatro decisões de desenho

**Quem conta é a transição, não o `statuses`.** A Meta reenvia os `statuses` sem
ordem garantida e com entrega concorrente (`E1` §5). Quem sabe se **esta**
chegada foi a que entregou a mensagem é o `SQL_AVANCAR_ESTADO` do KAM-015, que
decide sob `FOR UPDATE` e devolve o estado que substituiu. O adapter diz esse
facto a quem conta, pelo campo `entregou`; este módulo nunca relê o estado para
o re-decidir. É daí que vem a **idempotência por `wamid`** sem uma linha de
código sobre `wamid` aqui: três repetições produzem uma transição, logo `+1`.

Um serviço liga as duas metades assim:

```ts
const metering = new Metering({ bd });
const saida = new Saida({ ..., freeTier: (t, p) => metering.estado(t, p) });

const r = await saida.ingerir(tenantId, wamid, estado, pricing, phoneNumberId);
if (r.entregou && pricing?.category === "service") {
  await metering.contar(tenantId, phoneNumberId);
}
```

**O mês vem da base, e o fuso vive num sítio.** `platform.ten_periodo` (revisão
`0007`) é `date_trunc('month', p_agora AT TIME ZONE 'Africa/Luanda')`, é
`IMMUTABLE` e está concedida a `kamba_app`. Não se reimplementa a fronteira em
TypeScript: o comentário que criou a função di-lo por extenso, e há um teste em
`libs/py-core/tests/test_ten.py` que recusa o nome do fuso escrito no código.
A `free_tier_month` é `date` precisamente porque é o que aquela função devolve.

**O aviso é um flanco, e o flanco sai do próprio `UPDATE`.** «Um aviso aos 800,
sem repetição no mesmo mês» não precisa de guardar «já avisei» — logo não precisa
de coluna nova. O `UPDATE` que incrementa devolve o valor **antes** e **depois**,
e o número 800 é atravessado por exactamente um incremento. Sob concorrência
vale pela mesma razão que o custo do KAM-015: o `FOR UPDATE` serializa e o
segundo processo lê o que o primeiro escreveu.

**As métricas não levam etiqueta de *tenant*.** Decisão herdada da emenda 1.21
do dicionário, tomada para a `meta_cost_usd_total` do KAM-015: as bibliotecas de
métricas desta casa recusam **por gramática** uma etiqueta que não case
`^[a-z][a-z0-9_]{1,62}$`, e um `tenant_id` é um UUID com hífenes — a chamada
**levanta**. A razão de fundo é o `OBS-I` de
[`seguranca/ameacas_stride.md`](seguranca/ameacas_stride.md). Consequência para
os *gauges*: sem etiqueta, o valor publicado tinha de ser «o último canal
observado», que não é o de nenhum — passam a **agregados explícitos**, o máximo
para o rácio («qual é o canal mais perto do tecto») e a soma para a estimativa
(«quanto é que isto vai custar»). O por-canal sai de consulta.

## 3. As métricas

| Nome | Tipo | O que diz |
|---|---|---|
| `meta_free_tier_used_ratio` | *gauge* | Fracção consumida, no canal **mais perto** do tecto. `-1` antes da primeira observação |
| `meta_cost_usd_estimate` | *gauge* | Estimativa acima do tecto, em **micro-dólares inteiros**, **somada** sobre os canais |
| `meta_free_tier_alert_total` | contador | Avisos emitidos, com etiqueta «nivel» ∈ {`aviso`, `esgotado`} |
| `meta_payment_suspect_total` | contador | Vezes que a heurística concluiu suspeita |

Os nomes estão no §3.16 do
[`../specs/02_Dicionario_de_Dados_Canonico.md`](../specs/02_Dicionario_de_Dados_Canonico.md)
(emenda 1.24). A unidade é o micro-dólar e o nome diz `usd`: o nome é o do
critério e não se muda; a unidade é a do §2 do dicionário, inteira, porque somar
`0.004` mil vezes em `float64` não dá `4.00`.

**`meta_cost_usd_estimate` não é a `meta_cost_usd_total` do KAM-015 com outro
nome**, e a diferença é o ticket inteiro: aquela é o que a Meta **disse** ter
cobrado, somada do `pricing` de cada `statuses`; esta é o que **nós** estimamos
a partir do nosso contador. A diferença entre as duas é o que a reconciliação
mede — com uma só, não havia contra o que reconciliar.

## 4. A suspeita de método de pagamento

Três condições, todas necessárias: o *free tier* está esgotado (`>= 1000`), a
janela das últimas 20 mensagens **com destino já conhecido** está cheia, e pelo
menos 4 dessas falharam (20%).

A janela ignora `queued` e `sent` de propósito: uma mensagem que ainda não
falhou nem foi entregue diluía a taxa exactamente no momento em que ela importa
— uma rajada de 20 envios que a Meta vai recusar entrava como «sem falha» e
fazia a taxa parecer boa enquanto o canal morria.

Os limiares (20% em 20) são **proposta**, e a palavra é do próprio critério. O
que é CONFIRMADO é o comportamento; o que **não existe em evidência nenhuma** é
o **código de erro** com que a Meta recusa por falta de pagamento — o `E1`
nomeia `2593109`, `130429` e `131049`, e nenhum é de pagamento. É por isso que a
detecção é sobre a taxa e não sobre um código, e é por isso que o critério manda
guardar os códigos vistos: é a calibração que permitirá um dia trocar a
heurística pelo código certo. A pergunta está no pacote do **KAM-101**.

A verificação de que o método existe no Billing Hub é o **KAM-093**; aqui só a
detecção em *runtime*. E quem avisa o dono é o **KAM-115**: este módulo conta e
registra, não notifica.

## 5. A reconciliação

O contador é nosso e a factura é da Meta. A `reconciliar` mede, para o **mês
corrente**, o nosso contador contra o que o `pricing` das linhas testemunha, e
devolve **duas** divergências:

- `divergenciaDaContagem` — «contámos bem?» Compara o contador com as entregas
  de *service* que o `pricing` conta. Mesma grandeza.
- `divergenciaDoFacturavel` — «a fronteira do *free tier* é onde pensamos?»
  Compara a nossa estimativa de facturáveis com as que a Meta marcou `billable`.

**São duas porque o critério 7 é ambíguo e não se escolhe em silêncio.** Ele diz
«o contador interno vs `pricing.billable` agregado», e o contador conta **todas**
as *service* entregues (1.200 num mês cheio) enquanto o `billable` só marca as
que estão acima do tecto (200). Comparados directamente dariam 83% de divergência
num canal onde tudo está certo, e o limiar de 2% nunca fecharia.

**É o mês corrente e só esse**, porque não há outro que se possa reconciliar: o
contador é uma coluna e não uma série, e quando o mês vira o valor anterior
desaparece. O período exprime-se pela própria função do fuso
(`ten_periodo(delivered_at) = ten_periodo(agora)`) e não por fronteiras em
instantes — que vinham em UTC e perdiam a última hora do mês de Luanda.

**O que a reconciliação vai encontrar, e é esperado:** mensagens cujo `statuses`
não traga `pricing` não são contadas (o critério manda contar por
`pricing.category`), e as isenções que o `E1` §1 descreve — janela *free entry
point*, mensagens de grupo a consumir várias unidades do mesmo contador,
ONG/governo isentos até 2027 — **não estão modeladas**. O tamanho disso é o que
um mês de Piloto vai dizer; discrepâncias sobem ao KAM-101.

## 6. A marca de restrição e os códigos vistos

A revisão `0013` acrescenta duas colunas a `tenant_channels`:

| Coluna | Tipo | O que guarda |
|---|---|---|
| `motivo_restricao` | `text`, anulável, domínio de três valores | Porque é que o canal está restrito. `NULL` é o estado normal |
| `meta_error_codes_seen` | `integer[]`, `NOT NULL DEFAULT '{}'`, tecto de 32 | Os códigos de erro que a Meta já devolveu neste canal |

**O evento sai uma vez por restrição, e não uma por mensagem falhada.** A Meta
reenvia os `statuses` e a heurística volta a disparar enquanto a taxa de falhas
se mantiver. Quem decide é o `marcado` que a base devolve do `antes`, sob
`FOR UPDATE`: um `COALESCE` faz a **primeira** marca ser a que fica, e sob
concorrência só um dos processos vê `NULL`. Um evento por mensagem falhada é o
contrário de um alerta.

O `channel.updated` vai por `platform.evt_emitir`, na transacção de quem chama,
e o envelope **constrói-se em SQL** — a regra é do KAM-005 e do ADR-009, e a
razão está no `eventos/envelope.ts`: duas fontes para a mesma forma divergem no
primeiro campo novo. O `payload` valida-se contra o contrato **antes** de
qualquer escrita (KAM-007), e tem exactamente `phone_number_id` e `motivo` —
nenhum dos dois é PII, porque o `phone_number_id` é um identificador opaco da
Meta e não um telefone, como o inventário da `0001` diz por extenso.

**O que o ticket decidiu não fazer, e está escrito:** o canal **não** passa a
`restrito`. O critério não o pede, e passar uma loja a `restrito` por uma
heurística de limiares *propostos* era cortar-lhe o atendimento por uma
suspeita. Quem restringe de facto é o KAM-021 (qualidade RED) e o KAM-094 (gate
de activação). O `tenant_channels.estado` já tem `restrito` desde a `0001`.

Levantar a marca exige o motivo certo: um canal restrito por qualidade continua
a entregar mensagens, pelo que uma entrega **não** é prova de que a qualidade
melhorou, e limpar a marca de outro ticket ao passar era apagar uma decisão que
não é nossa.

**Três valores no domínio, e só um é deste ticket.** O `quality` (KAM-021) e o
`policy` (KAM-017) nascem na mesma revisão pela mecânica que a emenda 1.20 já
pagou e a `0010` repetiu para o `suppressed_by_human`: o *gate* 3b lê o `CHECK`
de cada revisão **isoladamente**, pelo que alargar o domínio numa revisão
posterior deixava a `0013` vermelha por lhe «faltar» um valor.

### O que continua de fora

| O quê | Porquê |
|---|---|
| O fuso **por canal** (critério 3) | A única coluna de fuso do esquema é a de `tenants`, por *tenant*. Criá-la por canal era decidir, de fora deste ticket, que um *tenant* pode ter dois fusos — e nenhum critério o pede. Dívida 66 |
| A etiqueta `{tenant}` nas métricas (critério 4) | As bibliotecas da casa recusam-na por gramática; ver §2. Mesmo precedente da emenda 1.21 |
| A reconciliação de um mês real (critério 7) | É critério de **saída**: pede um mês de Piloto. O instrumento está entregue |
| O aviso ao dono | É o **KAM-115**, que nomeia este ticket como emissor de `motivo_restricao='payment_method'` |
| A verificação do método de pagamento no Billing Hub | É o **KAM-093**. Aqui só a detecção em *runtime* |

As quatro divergências entre o bloco do ticket e o que o esquema tem estão em
[`dividas-documentais.md`](dividas-documentais.md), linhas 65 a 68.

## 7. Como se prova

```bash
# unidade (gate 4): as contas, o flanco, a heuristica, as metricas
pnpm --filter @kamba/core-ts run test

# contra um PostgreSQL real (gate 8): o fuso, a concorrencia, o isolamento,
# a revisao 0013 e o seu downgrade
make ci-8

# a prova por mutacao das vinte e seis
python db/mutacoes.py <python> "free tier:"
python db/mutacoes.py <python> "restricao"
```

A divisão entre as duas baterias é a que o `outbound.md` já usa, e a razão é a
mesma: **um duplo prova que o nosso código chama o que pretendíamos chamar, não
que o PostgreSQL faz o que pensamos.** O `FOR UPDATE`, o `IS DISTINCT FROM` com
`NULL`, o `platform.ten_periodo` e a RLS não existem numa base falsa.

Dois defeitos deste módulo foram apanhados por máquina e não por leitura, e
ambos eram invisíveis no CI: o driver `pg` converte uma coluna `date` num `Date`
à meia-noite **local do processo**, pelo que o mês voltava com um dia de erro em
qualquer fuso a oeste de Greenwich e certo num contentor em UTC; e a
reconciliação, na primeira versão, comparava o contador de um mês com as
entregas de outro. O primeiro saiu da bateria contra a base, o segundo da
revisão adversarial.

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Primeira versão, KAM-023. O módulo entra sem DDL; os critérios 5 e 6 esperam a revisão que descende da `0012` do KAM-020. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | **A segunda metade, com a revisão `0013`.** O KAM-020 fundiu e a revisão deixou de estar bloqueada: §6 passa a descrever a marca de restrição, o conjunto de códigos vistos e o `channel.updated`, e a lista do «que falta» encurta para o que **não é** trabalho em falta — o fuso por canal que o esquema não tem, a etiqueta de métrica que as bibliotecas recusam, e o critério de saída que pede um mês real. | Equipa KAMBÁ |
