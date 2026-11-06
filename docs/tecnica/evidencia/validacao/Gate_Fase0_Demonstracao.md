# Guião da demonstração do esqueleto andante

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — guião do operador e cenário *scriptado* do gate da Fase 0 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Estado | NÃO VERIFICADO |
| Fonte | `../../00_Arquitectura_Solucao.md` §13.2; `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md` (bloco KAM-108, critério G0-1) |
| Dono | Arquitecto de Plataforma (prepara); o operador que conduz **não** pode ser quem escreveu o código |
| Ticket | KAM-108 (EPIC-10) |
| Classificação | Documento de Referência — Interno |
| Relacionados | [`Gate_Fase0.md`](Gate_Fase0.md), [`Gate_Fase0_Decisao.md`](Gate_Fase0_Decisao.md) |
| Instrumentos | [`tools/gate_fase0/`](../../../../tools/gate_fase0/README.md) |

> **Quem conduz não pode ser quem escreveu o código.** É a letra do critério
> G0-1: «3 execuções consecutivas verdes por uma pessoa que **não escreveu o
> código**». Não é desconfiança: é o único mecanismo que separa «o sistema
> funciona» de «o autor sabe por onde ir».
>
> **E a Meta é a real: telemóvel → número de teste ou de coexistência, nunca
> simulador.** Com o `tools/meta-sim` a cadeia fecha e não prova nada sobre o
> canal, que é metade do que esta demonstração existe para provar. É o passo P0,
> e é a única parte que não se pode automatizar sem deixar de a provar.

---

## 1. Antes de começar

| # | Preparação | Como se confirma |
|---|---|---|
| 1 | O número de destino é **de teste ou de coexistência** da Meta | Pelo painel da Meta, e não por memória |
| 2 | O **simulador não está no caminho** | O ambiente não corre em modo de simulação, e a mensagem sai de um telemóvel a sério e não de um `curl` |
| 3 | O *tenant* da demonstração tem **as duas verticais activas** | É o *tenant* que o critério G0-1 pressupõe: sem as duas, a regra de dois não se exerce e o consumo cruzado não acontece |
| 4 | O `ManualProvider` está activo e com **limite de valor** | E o limite está assinado — é a linha 3.5 da [`Gate_Fase0.md`](Gate_Fase0.md), e assinar um limite é decisão do fundador |
| 5 | Há **gravação do ecrã** a correr | Os «Detalhes Técnicos» do bloco pedem-na como evidência |
| 6 | A janela `:desde` está anotada | É o parâmetro das consultas do §3. Sem janela, a cadeia de hoje mistura-se com as de ontem, e uma cadeia feita de elos de execuções diferentes parece completa sem o ser |

**O que não se prepara, e é deliberado: o texto das mensagens.** O que se escreve
ao assistente é escolha do operador no momento. Um guião versionado com frases de
conversa é conteúdo de conversa no repositório, e este guião leva o **acto** e o
**observável**, nunca a frase.

---

## 2. O cenário *scriptado*

A tabela abaixo é a saída de `python -m gate_fase0 cenario`, **gerada** de
`tools/gate_fase0/cenario.py`. Gera-se em vez de se escrever à mão por uma razão
que não é de estilo: se os passos vivessem aqui e os elos que o traço procura
vivessem em código, a demonstração podia correr os passos certos e o traço medir
outra coisa — e ninguém reparava, porque os dois estavam certos cada um por si.
Há ensaio a exigir que **cada elo que o traço procura tenha um passo que o
produz**, e um canário que avermelha ao tirar um passo.

| # | Quem | Acto | O que tem de se observar | Elo | Fonte |
|---|---|---|---|---|---|
| P0 | operador | confirmar que o número de destino é um número de teste ou de coexistência da Meta e que o simulador não está no caminho | o `KAMBA_META_MODO` do ambiente não é `simulador`; a mensagem sai de um telemóvel a sério e não de um `curl` | — | EPIC-10, KAM-108, critério G0-1 |
| P1 | operador | enviar a primeira mensagem ao número, do telemóvel | uma linha de *log* com `tenant_id` e `turn_id`/`msg_id` na forma do `docs/logs.md` §2; nenhuma linha com texto | **mensagem** | `docs/tecnica/00` §13.2: «uma conversa real» |
| P2 | operador | percorrer o atendimento do Vendedor até criar um pedido, pelo caminho que o assistente oferecer | um `order_id` novo, ligado ao `turn_id` do P1 pelo `audit_log(turn_id, entity, entity_id)` | **pedido** | EPIC-10, KAM-108, critério G0-1: «cria um pedido (Vendedor)» |
| P3 | sistema | emitir a referência de pagamento do pedido | um `payment.reference_issued` com `agregado_id` igual ao `order_id` | — | EPIC-10, KAM-108, critério G0-1: «emite referência» |
| P4 | dono (ou *sandbox* do facilitador) | confirmar o pagamento — pelo `ManualProvider`, dentro do limite de valor, ou pelo *sandbox* se houver contrato | um `payment.manual_confirmed` (ou `payment.confirmed`) com `agregado_id` igual ao `order_id`, e `autenticacao.authn_ok` verdadeiro | **evento de pagamento** | `docs/tecnica/00` §13.2; ADR-013 |
| P5 | sistema | transitar a encomenda para `paga` | o estado da encomenda é `paga`, e a transição veio do evento — nenhum caminho aplicacional a marca (ADR-013) | — | EPIC-10, KAM-108, critério G0-1: «passa a `paga`» |
| P6 | sistema | a vertical Serviços consome o evento de pagamento | uma linha de `events_consumed` com `consumer = 'agr_servicos'` e o `event_id` do P4 | **consumo por `agr_servicos`** | `docs/tecnica/00` §13.2: «esse evento é consumido pela vertical Serviços» |
| P7 | sistema | a vertical Serviços cria o lembrete ou a marcação | um `booking_id` novo, ou um `booking.reminder_due` agendado | — | EPIC-10, KAM-108, critério G0-1: «cria o lembrete/agenda» |

### 2.1 O que se sabe hoje sobre o P7, e porque se corre o cenário de qualquer modo

**Medido em `fe40048`: a acção do P7 não está escrita.** Os dois pares
`(servicos, payment.confirmed)` e `(servicos, payment.manual_confirmed)` estão no
`ACCOES_POR_LIGAR` do `services/agr/src/kamba_agr/eventos/handlers.py`, o que
quer dizer «esta vertical subscreve e a acção dela não está escrita», e o
desfecho do consumo é `sem_accao`. A medição completa, com os credores e as
perguntas devolvidas, está no §9.2 da [`Gate_Fase0.md`](Gate_Fase0.md).

**Corre-se o cenário todo de qualquer modo, e por duas razões.** O P6 — o consumo
— **existe** e tem de ser observado: é ele que prova a regra de dois sobre o
*bus*, e o `sem_accao` é um desfecho contado e registado, não um silêncio. E as
três execuções medem muito mais do que o P7: o canal real, a criação do pedido, a
autenticação do pagamento, a transição, e o traço sem conteúdo nem telefone.

**O que não se faz é dar o P7 por observado.** Se a marcação não aparecer, a
linha do traço diz `— nao criada`, e é isso que vai para a checklist.

---

## 3. As consultas da base

Três elos da cadeia **não cabem nos *logs***, e isso não é uma falta: é a política
desta casa. O ADR-010 e o `../../../logs.md` §2 fixam uma *allowlist* de doze
campos, e `order_id`, `event_id`, `booking_id` e `conversation_id` não são nenhum
deles — o §2.2 recusa o `contact_id` pelo nome. Dos quatro elos, os *logs* dão o
primeiro e mais nada.

Correm-se com o papel que **lê**, e com o contexto de *tenant* posto — sem ele a
RLS devolve zero linhas, que é o comportamento certo e o primeiro sinal de que o
contexto falta. Imprimem-se com `python -m gate_fase0 consulta`; **projectam só
identificadores**, e há ensaio a provar que nenhuma selecciona uma coluna que
leve conteúdo, telefone ou um resumo invertível — nos dois lados, a tupla
declarada e o `SELECT` que corre.

```sql
-- pedido: pedido
-- fonte: dicionário §3, `audit_log(…, entity, entity_id, turn_id, …)`
SELECT tenant_id, turn_id, entity, entity_id, criado_at
  FROM audit_log
 WHERE tenant_id = :tenant_id
   AND criado_at >= :desde
   AND entity IN ('order', 'encomenda')
 ORDER BY criado_at;

-- evento: evento de pagamento
-- fonte: dicionário §3, `events_log(event_id, tipo, …, agregado_id, …)`
SELECT tenant_id, event_id, tipo, versao, agregado_tipo, agregado_id,
       ocorrido_em
  FROM events_log
 WHERE tenant_id = :tenant_id
   AND ocorrido_em >= :desde
   AND tipo IN ('payment.manual_confirmed', 'payment.confirmed',
                'payment.reference_issued')
 ORDER BY ocorrido_em;

-- consumo: consumo por `agr_servicos`
-- fonte: dicionário §3, `events_consumed(consumer, event_id, …, processado_at)`
SELECT tenant_id, consumer, event_id, agregado_tipo, agregado_id,
       processado_at
  FROM events_consumed
 WHERE tenant_id = :tenant_id
   AND processado_at >= :desde
 ORDER BY processado_at;

-- marcacao: (efeito, não é elo da cadeia)
-- fonte: dicionário §3, `bookings(booking_id, …, estado, …, criado_at)`
SELECT tenant_id, booking_id, estado, criado_at
  FROM bookings
 WHERE tenant_id = :tenant_id
   AND criado_at >= :desde
 ORDER BY criado_at;
```

**A marcação fica numa consulta à parte, e não num `UNION`.** As três primeiras
são a cadeia; esta é o **efeito**. A diferença aparece na checklist: uma cadeia
completa com zero marcações é um resultado diferente de uma cadeia que parou no
consumo, e juntá-las apagava a distinção.

### 3.1 Correr o traço

Guardar as linhas das consultas em JSON-lines (um objecto por linha), juntar-lhes
as linhas de *log* da execução, e correr:

```bash
cd tools && PYTHONPATH=. python -m gate_fase0 traco ../logs.jsonl ../base.jsonl
```

**Lê-se o código de saída, não a saída.** `0` é a cadeia completa; **`1` é a
cadeia com elos em falta** — e é por isso que ele existe: um `&& echo verde` num
guião diria verde sobre uma cadeia que parou no evento de pagamento. `2` é a
entrada que não serve, que é um problema de quem corre e não um resultado da
demonstração.

O traço **não emite conteúdo nem telefone**, e isso está provado por controlo
negativo e não por promessa: alimentado com um *log* que leva conteúdo e um
telefone de forma real, a saída não leva nenhum dos dois, e os detectores correm
**primeiro sobre a entrada** como canário. Ver o
[`README`](../../../../tools/gate_fase0/README.md) do pacote.

---

## 4. Folha das três execuções — **por preencher**

O critério pede **3 execuções consecutivas verdes**. «Consecutivas» é literal: uma
execução vermelha pelo meio reinicia a contagem, e não se escolhem as três
melhores de cinco.

| # | Data e hora (UTC) | Operador (papel) | P1–P7 todos observados? | Código de saída do traço | Traço arquivado em | Gravação do ecrã em | Observações |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |

| Campo | Valor |
|---|---|
| **Três consecutivas verdes?** | |
| Se não: qual falhou, e em que passo | |
| Quem conduziu escreveu o código? | *(tem de ser «não»)* |

---

## 5. O ensaio geral, antes do gate

Os «Testes Requeridos» do bloco pedem «**ensaio geral** da demonstração (3
execuções) **antes** do gate». É uma quarta execução e não uma das três: serve
para descobrir o que falta no ambiente sem gastar uma das execuções que contam.

| # | Data | Quem | O que se descobriu | O que se corrigiu antes do gate |
|---|---|---|---|---|
| | | | | |

---

## 6. O que fazer quando um passo falha

**Não se emenda o sistema a meio da demonstração.** Uma correcção entre a
execução 1 e a 2 faz das três execuções três medições de três sistemas
diferentes, e a palavra «consecutivas» deixa de querer dizer nada.

| Se falhar… | Então |
|---|---|
| **P0** (o número ou o modo) | Para-se. Não há demonstração com simulador, e uma demonstração com simulador registada como válida é pior do que nenhuma |
| **P1 a P5** | Regista-se o passo, o código de saída do traço e o que se observou; a contagem das três reinicia |
| **P6** (o consumo) | Regista-se. É o elo que prova a regra de dois sobre o *bus*, e é o que a linha 1.6 da [`Gate_Fase0.md`](Gate_Fase0.md) mede |
| **P7** (o lembrete ou a marcação) | Regista-se como `— nao criada`. **Já se sabe que a acção não está escrita** (§2.1), pelo que isto é o esperado e não uma surpresa — e não se corrige aqui: é ticket novo, devolvido no §9.2 da [`Gate_Fase0.md`](Gate_Fase0.md) |
| Qualquer passo, com **conteúdo ou telefone na saída do traço** | **Para-se e não se arquiva a saída.** O traço recusa-se a devolvê-la (sai com `2`), e um traço que emitisse conteúdo era uma fuga de dados pessoais num ficheiro de evidência |

---

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-108): o guião do operador, o cenário *scriptado* em oito passos **gerado** de `tools/gate_fase0/cenario.py` com ensaio a amarrá-lo aos elos que o traço procura, as quatro consultas de leitura que projectam só identificadores, a folha das três execuções consecutivas e a do ensaio geral — as duas a nascer vazias —, e o que fazer quando um passo falha. Registado o que se mediu sobre o P7: a acção do consumo na vertical Serviços **não está escrita**, pelo que o passo se corre e se regista, não se dá por observado nem se corrige aqui. | Equipa KAMBÁ |
