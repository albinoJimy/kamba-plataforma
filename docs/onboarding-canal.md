# Onboarding de canal: Embedded Signup v4 e Tech Provider (KAM-016)

| Campo | Valor |
|---|---|
| Ticket | KAM-016 |
| Módulo | `packages/core-ts/src/onboarding/` |
| Rota | `POST /internal/channels`, na app **interna** do GWY (`services/gwy/src/canais.ts`) |
| Revisão | `0017_onboarding_de_canal` (descende da `0016` do KAM-018) |
| Depende de | KAM-013 (GWY), KAM-003 (`tenant_channels`), KAM-010 (cofre), KAM-024 (Graph falsa), `ext:KAM-102` (Business Verification, App Review, Tech Provider) |
| Bloqueia | KAM-017, KAM-091, KAM-093 |
| Fonte do desenho | [`tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §4.2–§4.4 e §13, [`tecnica/evidencia/E1_Meta_WhatsApp.md`](tecnica/evidencia/E1_Meta_WhatsApp.md) §3, [`tecnica/08_Seguranca_Conformidade.md`](tecnica/08_Seguranca_Conformidade.md) §5, ADR-001, ADR-019 |

## 1. O que o módulo faz, e o que não é

Recebe o resultado de um *popup* do Embedded Signup v4 e deixa um canal
`pendente` com os webhooks subscritos. Sete passos, cada um com o seu recurso
registado e a sua compensação:

1. o **tecto** da Meta — `es_onboardings_7d < 10` —, e recusa antes de tocar em nada;
2. a **forma do ES** — v4 ou recusa;
3. **abrir a tentativa** — e se ela já existia, devolve-a e **não faz mais nada**;
4. **trocar o *code*** por um *token* de cliente, cifrá-lo e cunhar a referência;
5. o **PIN 2FA**, só em `cloud_only`;
6. **criar o canal** — e é aqui que o 409 nasce;
7. **subscrever os onze campos** e **confirmar por leitura**.

**Isto não é o orquestrador.** Os *Detalhes Técnicos* do bloco são explícitos:
«O orquestrador (saga) é KAM-091; este ticket entrega **passos idempotentes**.»
O que está aqui é o conjunto de passos e um `ligar()` que os corre pela ordem —
não uma máquina de saga com persistência de *jobs*, retomas e políticas de
retentativa.

**E não activa canal nenhum.** O canal nasce `pendente` e fica: «nenhum cliente
é contactado até ao passo 10 passar» (`01` §13.2), e o *gate* de activação é
KAM-093.

## 2. As sete decisões de desenho

### 2.1 O 409 é a unicidade a morder, e não uma verificação em código

«Anexar um `phone_number_id` já usado por outro tenant devolve 409» é a
`tenant_channels_phone_number_id_uq` da revisão `0001` a levantar `23505`. A
unicidade é **global**, sem `tenant_id` na chave, e é a mesma propriedade que
torna a resolução do CHR determinística.

Um `SELECT` antes do `INSERT` seria uma segunda verdade a reconciliar com a
primeira, e perderia a corrida: entre o `SELECT` e o `INSERT` cabe outro
processo.

**As três metades do critério resolvem-se com a forma da transacção**, e não com
três mecanismos: o **409** é o `23505`; o **«não altera nada»** é essa transacção
a reverter; e o **registo de auditoria** escreve-se depois, numa transacção
própria — é por isso que o `registarRecusa` é chamado pela rota e não dentro do
`ligar()`.

### 2.2 O passo do *token* vem antes do canal, e isso é uma coluna que decide

`tenant_channels.token_ref` é `NOT NULL` desde a `0001`, pelo que não há linha de
canal a criar antes de haver *token*. A primeira leitura disto é um defeito —
gasta-se o *code* num onboarding que vai dar 409 —, e a segunda é que torna o
critério 4 e o critério 7 **a mesma maquinaria**: o conflito compensa o passo do
*token* pelo mesmo caminho que uma falha na subscrição.

### 2.3 A idempotência são duas unicidades, e «1 canal» sai de «1 linha»

```
channel_onboarding_code_uq         (tenant_id, code_hash)
channel_onboarding_tenant_waba_uq  (tenant_id, waba_id)
```

O canal cria-se **dentro da mesma transacção** que escreve o `channel_id` na
linha da tentativa: duas chamadas concorrentes com o mesmo par não podem ter as
duas uma linha aqui, logo não podem ter as duas um canal.

**O que a segunda chave custa, e está escrito:** um *tenant* não pode ter dois
números no **mesmo** WABA por este caminho. O recurso do passo 4 — a subscrição —
é **do WABA** e não do número, pelo que «0 subscrições duplicadas» é,
literalmente, uma subscrição por `(tenant, waba)`. Um segundo número no mesmo
WABA é um caminho novo, não um relaxamento desta chave.

### 2.4 As nove fases, e a décima que não é fase

O diagrama do `01` §13.1 desenha **dez** estados; o critério enumera **nove**. O
décimo é o `desligado`, e ele é valor de `tenant_channels.estado` — quem o
escreve é o tratador do `account_update`, que é KAM-017. O `ativo` é **terminal**
nesta tabela.

A matriz tem **dezesseis** arestas e o diagrama desenha onze. A diferença é uma
regra: **de qualquer fase não terminal vai-se a `falhado`**. O diagrama só desenha
`a_sincronizar --> falhado`, mas o critério 7 pede uma falha injectada no **passo
4** — a subscrição, que corre em `es_concluido`; sem a aresta, o caminho que o
critério manda exercitar não é representável.

A matriz vive no **código** (`contrato.ts`) e aplica-se por *compare-and-set*
(`WHERE fase = <esperada>`), como a monotonia de `outbound_messages.state` da
`0010`. A base impõe o domínio das nove, e o *gate* 8 percorre os **81** pares
ordenados contra um PostgreSQL real.

### 2.5 O *token* é cifrado **e** referenciado, e a DEK é derivada

O critério pede as duas metades ao mesmo tempo, e o inventário de segredos
confirma-o do outro lado: declara `kek_token_cliente` como entrada **separada**
do `meta_client_token`. O que fica no cofre, sob a referência, é o
**criptograma** — uma cópia do cofre não dá o *token* sem também a KEK, que tem
dono diferente.

A DEK por *tenant* é **derivada** (`HKDF-SHA256(KEK, domínio ‖ tenant_id)`) e não
guardada numa tabela como a `contact_deks` do KAM-008: este segredo é
re-cunhável, e uma tabela nova com `tenant_id` que a *suite* não saiba semear
falha o *gate* 6.

O `kid` vai **dentro** do criptograma. Sem ele, o dia em que a KEK rodasse
tornava indecifráveis todos os *tokens* já guardados — e um *token* de cliente
não se regenera sem o dono repetir o *popup*.

O contexto autenticado leva `domínio ‖ tenant_id ‖ kid`: um criptograma copiado
para a linha de outro *tenant* **não abre**. Isso não é zelo — mover um
`token_ref` de A para a linha de B é uma escrita que a base aceita, porque o
`GRANT UPDATE` da `0001` concede essa coluna a `kamba_app`.

### 2.6 A rota vive na app interna do GWY

Esta rota **cria canais** e o `tenant_id` vem no corpo. Na porta pública —
alcançável da Internet por desenho (ADR-001) — quem lhe chegasse podia ligar um
número ao *tenant* que quisesse. É a mesma razão que tirou o `/metrics` de lá na
revisão adversarial do KAM-013, com mais em jogo: ali lia-se a profundidade da
fila, aqui escrevia-se no esquema. Fechar a rede é KAM-077.

**E o `tenant_id` no corpo não contradiz o ADR-010**: este corpo não é texto de
utilizador, é o resultado de um *popup* que a nossa página abriu (KAM-093) com o
`tenant_id` que ela já tinha em contexto.

### 2.7 Quem escreve é o `kamba_batch`

O onboarding de um canal é **provisionamento**, e o dicionário §3.2 já lho
atribuiu. Três consequências:

* o contador `es_onboardings_7d` **atravessa *tenants*** — o limite de dez
  clientes por sete dias é da nossa app perante a Meta, não de uma loja — e com
  a política `tenant_iso` o `kamba_app` nunca o poderia contar;
* a compensação **apaga** a linha de `tenant_channels` que o passo anterior
  criou, e `kamba_app` não tem `DELETE` em tabela nenhuma desde a `0001`;
* `kamba_app` fica com **`SELECT` e mais nada**: o painel da loja lê em que fase
  está o seu canal.

## 3. A compensação, e os três sítios onde se leem os «0 recursos órfãos»

`recursos_criados` é a lista, pela ordem em que os passos a escreveram. A
compensação lê-a **da base** e não de uma variável deste processo — é o que a
torna retomável: um processo que caia depois do passo 6 deixa o canal e o *token*
registados na coluna.

Percorre-a ao **contrário**, e isso não é arbitrário: anular a subscrição exige o
*token* em claro, pelo que revogar o *token* primeiro deixava a subscrição sem
forma de ser desfeita.

Cada passo da compensação é **tolerante à ausência** — revogar um segredo que já
não existe resolve, apagar um canal que já não está lá devolve zero linhas. Uma
compensação que falhasse na segunda passagem deixava a saga sem forma de acabar.

E **uma compensação que falha não para as outras**: deixar o canal para trás
porque a Meta não respondeu ao `DELETE` da subscrição era trocar um recurso órfão
por dois. A lista só se esvazia se todos passarem.

Depois de compensar, a lista fica `[]` e a fase fica `falhado`. Os «0 recursos
órfãos» medem-se em **três** sítios, e não só na coluna: `0` linhas em
`tenant_channels`, `0` segredos no cofre, `0` subscrições no WABA. Uma lista
vazia só prova que a lista está vazia.

## 4. Os onze campos de webhook

| Campo | Quem o trata |
|---|---|
| `messages` | KAM-013 (entrada), KAM-014 (encaminhamento) |
| `smb_message_echoes` | KAM-017 (coexistência) |
| `history`, `smb_app_state_sync` | KAM-017 (sincronização) |
| `account_update` | KAM-017 (`PARTNER_REMOVED`), KAM-021 |
| `phone_number_quality_update`, `business_capability_update`, `account_alerts` | KAM-021 |
| `message_template_status_update`, `template_category_update`, `message_template_quality_update` | KAM-015 |

Subscrevem-se os onze e **este ticket não trata nenhum**: subscrever menos do que
onze era deixar um webhook que outro ticket espera a nunca chegar, e isso não se
descobre num teste do ticket que o trata.

A confirmação é por **igualdade de conjuntos** e não de listas: a Meta devolve
`subscribed_fields` sem ordem garantida.

## 5. As quatro métricas

```
es_onboardings_7d              gauge    clientes novos na janela de 7 dias
es_onboarding_fase             gauge    tentativas por fase
es_onboarding_compensado_total counter  compensações corridas, por recurso
es_onboarding_recusado_total   counter  recusas, por motivo
```

A primeira é a que o critério nomeia. As outras três estão lá porque
**compensar sem contar é compensar em silêncio**: uma saga que reverte tudo
correctamente e uma saga que nunca chega ao passo 4 produzem o mesmo número de
canais activos — zero.

Nenhuma leva etiqueta de *tenant*: o `OBS-I` de
[`seguranca/ameacas_stride.md`](seguranca/ameacas_stride.md) recusa
identificadores em etiquetas, e as bibliotecas da casa recusam por **gramática**
uma etiqueta que não case `^[a-z][a-z0-9_]{1,62}$`. Aqui isso nem custa: o
`es_onboardings_7d` é, por definição, um número **da plataforma**.

## 6. Limitações declaradas

**A troca do *code* vai na consulta, e não devia.** O `code` e o `client_secret`
seguem em `GET` com os parâmetros na URL, porque é a forma que a Meta documenta e
que o `GraphFalso` do KAM-024 modela. A primeira versão do cliente mandava-os no
corpo `form-urlencoded`, pela RFC 6749 §4.1.3 — e **ficou vermelha** contra o
simulador. A alternativa era alargar o simulador e passar a provar o cliente
contra uma superfície alargada para lhe servir; se a Graph real só aceitar a
consulta, o primeiro onboarding real falha com os testes verdes, que é o desfecho
que o «não inventes caminhos de API» do bloco existe para evitar.

O pedido sai em TLS e o `code` é de uso único; este cliente nunca escreve a URL
num log, e o `caminho` de um erro não leva a consulta. O que **não** está
mitigado é um proxy de saída nosso que registre a linha de pedido — e isso é
KAM-077.

**Os caminhos da Graph são *proposta*.** O `E1` não tem as páginas de referência
de API e não as lista como omissão; os três caminhos vivem em constantes
exportadas para que o dia em que alguém leia a documentação vigente seja uma
alteração de três linhas com um teste a afirmá-las.

**A leitura de confirmação junta os campos de todas as apps subscritas.** No novo
modelo de contas um número pode estar ligado a várias *Messaging accounts* de
parceiros diferentes (CONFIRMADO, `E1` §3), e distinguir a nossa exige o
`app_id`, que a forma exacta da resposta não está CONFIRMADA a trazer.

**O contador conta tudo o que entrou na janela**, incluindo o `abandonado` e o
`falhado`. Se um *popup* fechado consome um lugar na contagem **da Meta** é NÃO
VERIFICADO; contar de mais custa esperar, contar de menos custa um cliente.

**O registo de auditoria da recusa não é o `audit_log`.** O domínio de
`audit_log.action` tem sete valores e o `CHECK` está na revisão `0006`, fundida;
o *gate* 3b compara-o com o dicionário nos dois sentidos, pelo que um oitavo
valor deixava a `0006` vermelha. O registo é uma linha de `channel_onboarding` em
`falhado`, com o motivo escrito.

**E o nono critério está por marcar.** «1 onboarding ES v4 real numa conta de
teste da Meta, depois de KAM-102» depende de Business Verification, App Review e
Tech Provider, que é trabalho do fundador. Não há evidência em
`docs/evidencia/KAM-016.md`, e não se inventou nenhuma: o que está provado está
provado contra o `GraphFalso`, e o que só o primeiro contacto real pode dizer
está na secção de verificação do bloco do ticket.

## 7. O que este ticket não faz

| Fora de âmbito | Ticket |
|---|---|
| Business Verification, App Review, Tech Provider | `ext:KAM-102` |
| Sincronização de contactos e histórico (`subscrito → a_sincronizar`) | KAM-017 |
| Orquestrador da saga | KAM-091 |
| Página do *popup* e *gate* de activação | KAM-093 |
| Registo do número em `cloud_only` (passo 5′) | KAM-093 |
| Lista de espera do tecto de dez | KAM-095 |
| Conta, bot e *inbox* no Chatwoot | KAM-019 / KAM-091 |
| Submissão de templates | KAM-015 |
| Fechar a rede interna | KAM-077 |

## 8. Como correr

```bash
make ci-3b                                  # nomes canónicos (dicionário §3.20)
make ci-4                                   # unidade e cobertura
python db/gate_bd.py --suite tests          # esquema, inventário, privilégios
python db/gate_bd.py --suite tests_isolamento   # gate 6: X-03/X-04 e catálogo
python db/gate_bd.py --suite tests_outbound     # as três baterias do módulo
python db/mutacoes.py --aplicaveis          # as mutações ainda encontram o alvo
```
