# Qualidade do canal, estado `restrito` e limites (KAM-021)

| Campo | Valor |
|---|---|
| Ticket | KAM-021 |
| Módulo | `packages/core-ts/src/qualidade/` |
| Revisão | `0014_qualidade_de_canal` (descende da `0013`) |
| Depende de | KAM-013 (encaminhamento dos *webhooks*), KAM-009 (matriz de estados), KAM-015 (saída de canal), KAM-023 (`motivo_restricao`) |
| Consumido por | KAM-115 (aviso ao dono), KAM-081 (painel), KAM-097 (T&S) |
| Fonte do desenho | [`tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §9 e [`tecnica/evidencia/E1_Meta_WhatsApp.md`](tecnica/evidencia/E1_Meta_WhatsApp.md) §5 |

## 1. O que o módulo faz

Preenche o braço `gestao_de_canal` do `Encaminhador` que o KAM-013 declarou e
deixou **a registar e mais nada** — o `EncaminhadorQueSoRegista` do
`services/worker-canal/src/entrada.ts` empurra quatro `kind` para uma lista, e o
*docstring* dele diz «a gestão de canal está repartida entre KAM-016 e
KAM-021». Os quatro são `phone_number_quality_update`,
`business_capability_update`, `account_alerts` e
`message_template_quality_update`.

Do que chega, tira quatro coisas: o **registo** da transição (uma linha por
anúncio da Meta, com a hora que ela diz), o **estado** do canal (`restrito` com
`RED`, `ativo` outra vez com `GREEN`), os **limites** (escalão de mensagens e
tecto de números do portfólio), e a **medição** da utilização do escalão —
utilizadores únicos contactados por template em 24 h móveis ÷ tecto.

## 2. As cinco decisões de desenho

**A tradução faz-se na fronteira, e as duas colunas guardam coisas
diferentes.** O `channel_quality_log.valor_novo` guarda o **bruto** da Meta
(`GREEN`, e também `PURPLE` se ela um dia o mandar); o
`tenant_channels.quality_rating` guarda o canónico em minúsculas, pela regra do
§2 do dicionário. A razão é o critério 1 por extenso — «outro valor registado
como desconhecido sem falhar»: um domínio fechado na coluna do registo
transformava uma mudança de vocabulário da Meta numa **falha de inserção**, e
ela já mudou este vocabulário uma vez (o estado «Flagged» foi eliminado a
2025-10-07, CONFIRMADO `E1` §5). A tradução é um mapa explícito com teste, e não
um `toLowerCase()`: sem uma lista, não há contra o que um valor ser
desconhecido.

**O `UPDATE` não existe na tabela nova — nem de tabela nem de coluna.** Uma
linha do registo é o facto de a Meta ter dito uma coisa a uma hora, e um facto
não se corrige. A aplicação tem `SELECT` e `INSERT`, e a bateria contra a base
afirma o **`42501`** em vez de afirmar que o módulo não corrige nada: um teste do
lado do código prova o que o código faz hoje, este prova o que nenhum código
pode fazer. É a mesma forma do `usage_ledger` do §3.9 do dicionário.

**Cada ticket levanta apenas o motivo que põe.** O `SQL_REPOR` leva
`motivo_restricao = 'quality'` no predicado. Um canal restrito por falta de
método de pagamento (KAM-023) continua a ter qualidade — a Meta deixa de
entregar, mas o `quality_rating` pode muito bem voltar a `green` —, e repô-lo
nesse caso era desfazer a decisão de outro ticket a partir de um sinal que não
lhe diz respeito. O resultado prático era uma loja a voltar a `ativo` com a Meta
ainda a recusar as mensagens dela. É a mesma regra que a `levantarRestricao` do
KAM-023 escreveu pelo outro lado, e as duas juntas dizem a propriedade inteira.

Do outro lado da mesma moeda, o `SQL_RESTRINGIR` usa
`COALESCE(motivo_restricao, 'quality')`: **a primeira marca é a que fica.** Um
canal `ativo` com `motivo_restricao = 'payment_method'` é um estado que existe —
a `marcarRestricao` do KAM-023 escreve a coluna sem mexer no `estado` —, e
quando a qualidade cai nesse canal o motivo que o KAM-115 vai contar ao dono é a
**causa original**, não a consequência.

**O critério 9 usa a matriz do KAM-009 e não um `if`.** O `decidir` do KAM-015
ganha um parâmetro opcional com o par (estado do *tenant*, estado do canal) e
chama o `tenantGate`; um `STATE_REFUSED` novo entra nos `MOTIVOS_DE_RECUSA`, que
passam de dez a **onze**. Um motivo e não um por estado: o que recusa é a
matriz, que decide por um **regime** saído do par, e um motivo por estado dava
seis etiquetas de métrica para uma causa só. A porta é opcional, pelo que nenhum
`adapter` ligado antes disto passa a recusar; o que **não** é permissivo é o
canal que não se encontra — a porta devolve `null` e o `adapter` trata-o como
recusa, porque um canal que não se resolve não envia.

Uma consequência que se aceita de olhos abertos: a linha `restrito` da matriz
tem `enviar_template_utilidade: false`, pelo que a `utility` também é recusada —
e o critério 2 só nomeia a `marketing`. **A matriz é mais restritiva do que a
frase, que é o lado seguro**, e é o que o critério 9 pede por extenso («o CHR
usa a matriz de KAM-009»). Mudá-la era mexer numa decisão do KAM-009 que tem
espelho em Python e paridade imposta pelo X-11.

**O evento sai antes da *cache*.** `channel.updated` primeiro, invalidação do
canal no CHR depois, e só quando o estado de facto mudou. O evento é durável
quando a transacção confirmar; a invalidação é de memória e não sobrevive a
nada. Invalidar primeiro deixava uma janela em que a *cache* já esqueceu e o
evento ainda pode não sair.

## 3. A ordem dos passos

Para um `phone_number_quality_update`:

1. **lê o canal** — o `estado` e o `quality_rating` anteriores decidem se há
   transição, e o `motivo_restricao` decide se se pode repor;
2. **registra a transição** — e se o `RETURNING` vier vazio, **pára aqui**;
3. **escreve a qualidade canónica**, se a Meta mandou um valor que se reconhece;
4. **restringe ou repõe**, se houver transição de estado;
5. **emite `channel.updated` e esquece o canal na *cache***, e só se o passo 4
   mexeu em algo.

O passo 2 está antes do 3 de propósito. Se a qualidade se escrevesse primeiro,
um evento repetido que chegasse depois de o estado já ter sido reposto
reescrevia o `quality_rating` com um valor **velho** — e a ordem dos `statuses`
da Meta não é garantida (CONFIRMADO, `E1` §5). Com o registo à frente, o segundo
evento morre na unicidade antes de tocar em nada.

**Os cinco passos correm numa transacção, e ela é de quem chama.** O passo 2
consome a `event_key`; um processo que caia entre ele e o passo 4 perde a
transição **para sempre**, porque a Meta reenvia e o `ON CONFLICT` deduplica
contra a linha que ficou. O `ClienteSql` é a ligação **dentro** da transacção de
quem chama, pelo mesmo argumento que obriga a `Emitir` a correr lá — e é o que o
`comConsumo` do KAM-006 dá por desenho (ADR-013: marca de consumo e efeito na
mesma transacção).

A idempotência é **da base**: `ON CONFLICT (tenant_id, event_key) DO NOTHING
RETURNING id`, e o `RETURNING` vazio é o sinal. Não há `SELECT` antes do
`INSERT` — entre os dois cabe outro processo, e o critério pede **uma**
transição, não «quase sempre uma». A chave é composta com o `tenant_id` pela
razão da emenda 1.21: com unicidade global, um evento do *tenant* B que calhasse
na mesma chave era deduplicado em silêncio contra uma linha de A.

É o **segundo** nível de deduplicação. O primeiro é o `inbound_events (kind,
event_key)` da `0008`, e existe porque esse dedupe o **corpo** e não o
encaminhamento: o `registo.ts` do KAM-013 diz por extenso que registar e
encaminhar não são atómicos e que «todo o tratador de destino tem de ser
idempotente».

## 4. As métricas

| Métrica | Tipo | Etiqueta | Porque assim |
|---|---|---|---|
| `channel_quality` | *gauge* | `rating` (3 valores) | *Gauge* e **sem `_total`**: um canal que melhora sai de uma série e entra na outra, e um `_total` que desce é um contador que mente. A etiqueta passa onde a de *tenant* não passava porque tem três valores fechados e não é um identificador (`seguranca/ameacas_stride.md`, OBS-I) |
| `messaging_limit_usage_ratio` | *gauge* | — (máximo entre canais) | Vale `-1` antes da primeira observação **e também** quando o escalão não se reconhece: «não sei» não é «está folgado» |
| `channel_restricted_total` | contador | `motivo` (3 valores) | Com o domínio **inteiro** do `motivo_restricao` e não só o `quality`: a métrica é do canal e não deste ticket, e quando o KAM-023 ou o KAM-017 restringirem contam na mesma série |
| `channel_quality_event_total` | contador | `evento` (4 valores) | Não está no DoD. Entra pela razão da `outbound_rate_limited_total` da emenda 1.21: **tratar sem contar é tratar em silêncio**, e sem a etiqueta um painel não distingue «a Meta não mandou nada» de «mandámos tudo para o braço errado» |

Nenhuma leva `tenant_id`, e isso é decisão escrita e não omissão: as etiquetas
têm de casar `^[a-z][a-z0-9_]{1,62}$` e um UUID com hífenes **levanta**. Quem
precisa do corte por *tenant* lê a base, como o custo do KAM-015 faz.

## 5. A medição do escalão

`count(DISTINCT contact_id)` sobre `outbound_messages`, com três filtros, e cada
um é uma linha do critério 7:

* **`kind <> 'service'`** — «resposta dentro da janela não consome». O limite da
  Meta é sobre **iniciar** conversas fora da janela (CONFIRMADO, `E1` §5), e uma
  `service` é, por definição, a mensagem livre dentro da janela: responde, não
  inicia;
* **24 h móveis** — e não «hoje». **É por isto que esta consulta não chama a
  `platform.ten_periodo`**, ao contrário do contador do KAM-023: o mês do *free
  tier* reinicia à meia-noite de um fuso; este não reinicia, vai andando;
* **`state <> 'queued'`** — uma mensagem que a nossa própria fila ainda tem em
  mão não contactou ninguém.

A junção por `tenant_channels` existe porque `outbound_messages` guarda
`channel_id` e não o número — o mesmo desencontro que o KAM-023 registou na
dívida 68 — e leva `tenant_id` nos **dois** lados, como todas as FK desde a
`0003`.

Os **nomes** dos escalões são os que o gerador do KAM-024 produz (`TIER_250`,
`TIER_1K`, `TIER_2K`, `TIER_10K`, `TIER_100K`, `TIER_UNLIMITED`), que é a única
fonte deste repositório que corre. O bloco do ticket escreve `TIER_2000` no
exemplo: a divergência está nas dívidas e **não se resolve inventando um
sinónimo** — um escalão fora do mapa é desconhecido e o rácio fica `null`. O
`TIER_UNLIMITED` vale `Infinity`, o que faz o rácio dar `0` por aritmética em
vez de por um caso especial.

## 6. O que fica de fora, e porquê

| O que o critério pede | Onde está |
|---|---|
| **O `tenants.estado` a projectar `restrito`** (critério 3) | **Não se faz, e a caixa fica vazia.** A revisão `0007` retirou o `UPDATE (estado)` a `kamba_app` de propósito — «o sujeito da condição não pode ser quem a retira» — e o `db/tests/test_privilegios.py` prende-o. Nenhum dos papéis que o *worker* de canal tem pode escrever ali; só o `kamba_batch`. Devolver o privilégio reabria a escalada que a revisão adversarial do KAM-009 fechou. Decisão do fundador: caixa vazia com a razão escrita |
| **O *ticket* de T&S** (critérios 4 e 8) | Não existe mecanismo de *ticket* neste repositório. O que existe — **contador** e **registo** — é o que se usa, como o KAM-023 fez para o aviso do *free tier*: o alerta conta em `channel_quality_event_total`, o texto da Meta vai para o `valor_novo` e o `outcome` vai para o registo de linha. Quem notifica é o **KAM-115** |
| O texto da Meta no registo de linha | **Vai para a base e não para o `log`**, e a diferença é a política: a lista branca de nove campos do `logger/politica.ts` não tem campo de texto livre, e o `outcome` é um identificador. Um alerta da Meta pode trazer qualquer coisa escrita; a base aceita-o, uma linha de *log* não |
| O fuso por canal | Não existe coluna, e o KAM-023 registou-o na dívida 66. **Este medidor não precisa dela:** as 24 h são móveis e não fecham em meia-noite nenhuma |
| A suspensão automática | Não há caminho nenhum aqui que produza `suspenso`, e é isso que o teste dos 50 eventos aleatórios afirma. **A divergência que o DoD manda registar não existe:** o bloco diz que o `docs/tecnica/10` §6.4 põe RED → `suspenso`, e aquele §6.4 diz «vermelho → `restrito` (§15); T&S analisa» — o controlo de versões do documento registra a emenda **KAM-111** que o corrigiu (D-08). Quem ainda diz `suspenso` é o `docs/tecnica/00` §6.2, e isso o `docs/tecnica/01` §9 já registra. Dívida **74** |

As divergências entre o bloco do ticket e o que o esquema e a matriz têm estão
em [`dividas-documentais.md`](dividas-documentais.md), linhas 70 a 74.

## 7. Como se prova

```bash
# unidade (gate 4): a matriz de accao, a traducao, o racio, as metricas
pnpm --filter @kamba/core-ts run test

# contra um PostgreSQL real (gate 8): a corrida pela chave unica, o privilegio
# que nao existe, a RLS, a juncao da medicao e o criterio 9 de ponta a ponta
make ci-8

# a prova por mutacao das trinta e quatro
python db/mutacoes.py <python> "qualidade"
python db/mutacoes.py <python> "criterio 9:"
```

A divisão entre as duas baterias é a que o `outbound.md` e o `metering.md` já
usam, e a razão é a mesma: **um duplo prova que o nosso código chama o que
pretendíamos chamar, não que o PostgreSQL faz o que pensamos.** O
`ON CONFLICT`, o `count(DISTINCT)`, o intervalo móvel, o `42501` de um
privilégio que não existe e a RLS não existem numa base falsa.

**Cinco defeitos deste ticket foram apanhados por máquina e nenhum por
leitura**, e dois deles são testes em falta que a prova por mutação encontrou.

1. **O grupo do critério 9 passava pela razão errada.** O `tenants.estado` nasce
   `onboarding`, a matriz decide por um **regime** saído do par, e `onboarding` é
   mais restritivo do que `restrito`: as três asserções de `STATE_REFUSED`
   teriam passado com o canal `ativo`. O grupo ganhou um `before` que põe o
   *tenant* `ativo` — escrito pelo **administrador**, porque o `kamba_app` não
   tem esse privilégio, que é a mesma retirada que deixa a caixa do critério 3
   vazia — e um teste de **controlo** que prova que o template sai quando nada o
   impede: sem ele, uma recusa não se distingue de um envio que nunca podia sair.
2. **O `WHERE estado <> 'restrito'` do `SQL_RESTRINGIR` não tinha prova.** A
   mutação que o apagou **sobreviveu**, porque no caminho sequencial o predicado
   é redundante: o `accaoDaQualidade` já devolve `"nada"` quando o canal está
   `restrito`. Quem o torna necessário é a **concorrência** com chaves
   **diferentes** — as duas passam pelo registo, as duas leem `ativo`, e as duas
   decidem restringir —, e o teste da corrida que existia usa a **mesma** chave,
   pelo que prova o índice único e não o `UPDATE`. As duas provas são precisas e
   uma não substitui a outra.
3. **A recusa de um canal que a porta não encontra não tinha prova nenhuma.**
   Nenhum teste ligava a porta 5 a responder `null`, pelo que a mutação que
   apagou a recusa também sobreviveu. É a mais importante das três recusas: um
   canal que não se consegue resolver não é «sem opinião», é um canal que não
   existe neste contexto. Entrou um grupo em
   `tests/outbound.adapter.test.ts`, com a metade positiva — **sem** a porta
   ligada, envia como antes do KAM-021 — que é o que torna a negativa legível.
4. **O nome `max_phone_numbers_per_business` contém «phone».** Dispara a lista
   fechada de colunas de telefone do `test_catalogo.py` — declarou-se, e a razão
   é que num `integer` não cabe um E.164, garantia **mais forte** do que a do
   `phone_number_id`, que é `text`. E descer de `head` para a `0011` passa agora
   pela `0014`, que compromete **antes** de a `0012` recusar, pelo que a
   asserção do `downgrade` da mídia mudou de `TABELAS` para `TABELAS_ATE_0013`.
5. **O `outbound_messages_template_ck` recusou a receita de sementes do
   medidor.** A `0010` exige `template_name` em tudo o que não é `service`, e o
   ajudante do teste inseria `utility` sem ele: `23514` à primeira execução do
   *gate* 8.

E a revisão adversarial do próprio ticket encontrou **três** coisas que nenhuma
máquina podia dizer. A primeira é a mais barata de deixar passar: o
`contrato.ts` afirmava que «há um teste que compara as três listas» do domínio
dos eventos e o que existia comparava **duas** — as duas de TypeScript. A
terceira, que é o `CHECK` da revisão, não era confrontada com nenhuma; entrou o
`TestParidadeDosDominios`, que lê as revisões `0010`, `0013` e `0014` como texto
e confronta os três domínios com as constantes do módulo. Um motivo novo no
`CHECK` da `0013` sem entrada no `MOTIVOS` fazia o `contar` **levantar**, e o que
se perdia não era a métrica: era a restrição.

A segunda é que os cinco passos **não são atómicos por si**: o passo que
registra consome a `event_key`, e um processo que caia antes da mudança de estado
perde a transição para sempre. Está agora escrito que o `ClienteSql` é a ligação
**dentro** da transacção de quem chama, como a `Emitir` já exigia.

A terceira é que o `estadoDepois` era uma função que **só existia para ser
testada** — o mapa acção → estado estava lá, e o SQL escrevia os literais sem
ninguém confrontar os dois. Entrou a asserção que os liga, e com ela uma mutação
que a prende.

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Primeira versão, KAM-021. O módulo, a revisão `0014`, as quatro métricas e o `STATE_REFUSED` que faz os `MOTIVOS_DE_RECUSA` passarem de dez a onze. A caixa do critério 3 fica vazia, por segurança e por decisão do fundador. | Equipa KAMBÁ |
