# KPIs de onboarding, churn e tenants dormentes

| Campo | Valor |
|---|---|
| Ticket | **KAM-117** — `specs/EPIC-09_Onboarding_Governanca.md` |
| Versão | 1.0 |
| Fontes | [`tecnica/10_Onboarding_Governanca.md`](tecnica/10_Onboarding_Governanca.md) §13 e §16, [`tecnica/09_Topologia_Operacao_Escala.md`](tecnica/09_Topologia_Operacao_Escala.md) §9.2, [`exploracao/14-tese-minima-e-plano-de-validacao.md`](exploracao/14-tese-minima-e-plano-de-validacao.md) §2 (H1, H8, H9) |
| Estado | **Proposta.** Todos os limiares são *proposta* a calibrar no Piloto; a mortalidade de PMEs em Angola é **NÃO VERIFICADA** |
| *Runbook* | [`runbooks/churn.md`](runbooks/churn.md) |

---

## 1. O que existe

| Peça | Onde | O que faz |
|---|---|---|
| Limiares | [`../config/kpis.yaml`](../config/kpis.yaml) | Oito valores em dias, todos *proposta*. O leitor (`kamba_core.kpis.limiares`) falha fechado |
| Episódios | `platform.churn_signal_episode` (revisão dos KPIs de churn) | Um sinal aberto por tenant e sinal; fecha na primeira corrida em que deixa de valer |
| Sinais | `platform.churn_sinais(agora, limiares)` | Os sinais que valem **agora** para cada tenant `ativo`, com relógio e limiares por parâmetro |
| Actividade do dono | `platform.churn_dono_at(tenant, agora)` | *Echo* da app do dono, linha `owner` do `audit_log`, e o piso da **primeira** entrada em `ativo` (um levantamento de `restrito` é da equipa e não reinicia relógios) |
| Vistas | `v_churn_signals`, `v_tenant_dormente`, `v_onboarding_kpis_semanal` | Sem `contact_id`, telefone, nome nem conteúdo. O `kamba_app` não lê nenhuma. **A leitura entre tenants só a faz o `kamba_batch`**: o `kamba_audit` lê os episódios com o contexto de um tenant, e não lê a vista semanal |
| *Job* | [`../libs/py-core/src/kamba_core/kpis/churn.py`](../libs/py-core/src/kamba_core/kpis/churn.py) | `executar` (diário) e `reactivar` (a cada minuto) |
| Métricas | [`../libs/py-core/src/kamba_core/kpis/metricas.py`](../libs/py-core/src/kamba_core/kpis/metricas.py) | `onboarding_activation_minutes`, `churn_signal{sinal}`, `tenants_dormentes`; sem etiqueta de tenant |
| Painéis | [`../ops/paineis/onboarding.json`](../ops/paineis/onboarding.json), [`../ops/paineis/churn-e-dormentes.json`](../ops/paineis/churn-e-dormentes.json) | Configuração versionada; o Grafana está pendente (KAM-080) |

## 2. Os cinco sinais e o dormente

| Sinal | Condição (limiar *proposta*) | Fonte |
|---|---|---|
| `dono_inactivo` | última actividade do dono há **≥ 7 dias** | `channel_coexistence.ultimo_echo_em`, `audit_log` com `actor_type = 'owner'` |
| `sem_pedidos` | último pedido há **≥ 14 dias** | `orders_mirror.criado_at` |
| `canal_desligado` | um canal `desligado` e nenhum `pendente`, `ativo` ou `restrito` | `tenant_channels.estado` (imediato na corrida seguinte) |
| `pagamento_em_atraso` | ciclo `cobranca_emitida` ou `em_atraso` com **≥ 5 dias** de calendário de Luanda desde o início do período | `billing_cycles` |
| `catalogo_desactualizado` | último `price.update` ou `stock.adjust` sobre `offer_terms` há **≥ 28 dias** (aproximação de H8) | `audit_log` |
| `dormente` | actividade do dono há **≥ 53 dias** (o aviso) e **> 60** (pleno), sem pedidos nem mensagens de clientes nos últimos **30** | as acima, mais `conversations.last_inbound_at` |

**O piso.** Os três sinais de «há N dias sem X» contam, no mínimo, desde a **primeira** entrada do
tenant em `ativo` (`tenant_state_log`, ou o `criado_at` do tenant): um tenant activado há três dias não tem
«14 dias sem pedidos». O dormente **não** usa o piso para os pedidos e as mensagens: a janela é
absoluta.

**As fronteiras** são as do critério 3 e estão medidas com relógio fixo: 6 d 23 h não dispara e 7 d
dispara (`<=`); «> 60 dias» é estrito (`<`).

**O vencimento do ciclo.** A `billing_cycles` não tem coluna de vencimento nem de pagamento
(revisão `0055`); o início do período é o vencimento *proposta*. A régua de cobrança do **KAM-058**
decide o vencimento real — quando o fizer, a condição muda aqui e mais nada.

## 3. O *job* e a idempotência

1. **Episódios** — uma transacção, com tranca consultiva: abre o que não tem episódio aberto e fecha
   o que deixou de valer, numa instrução cada (com uma por sinal, 100 tenants levavam 161 s, só de
   idas e voltas à base). O índice único parcial é a rede; duas corridas no mesmo dia escrevem uma
   vez.
2. **Avisar** — fora do ensaio, cada dormente aberto recebe o aviso ao dono pela porta `AvisoAoDono`,
   e fica com `avisado_at`. **Sem a porta (KAM-115), nada se avisa e nada vai a zero**: a base
   recusa um orçamento zerado sem `avisado_at`, porque o bloco põe o aviso antes do zero.
3. **Zerar** — por tenant, só um dormente **pleno** cujo aviso **saiu** há pelo menos 7 dias, fora
   do modo de ensaio. A transacção tranca o episódio, **volta a perguntar** pelas mensagens de clientes na
   janela, chama a porta do orçamento, marca `orcamento_zerado_at` e escreve
   `llm.orcamento_zerado` no `audit_log`. Se a marca ou o `COMMIT` falharem depois de a porta ter
   zerado, o *job* repõe logo; a morte do processo entre os dois é o atalho registado no código.
4. **Repor** — por tenant: actividade do dono depois da abertura, ou o episódio fechado com o
   tenant ainda `ativo` (voltaram clientes ou pedidos). Chama a porta, marca `orcamento_reposto_at`,
   fecha o episódio e escreve `llm.orcamento_reposto`. Corre também em modo de ensaio, e é o que o
   `reactivar` faz a cada minuto. **Um tenant que sai de `ativo` (suspenso, encerrado) fica a
   zero.**

Com o orçamento a zero, o AGR já degrada para o modo determinístico (KAM-037): o LiteLLM responde
`budget_exceeded` e o motivo é `budget` — ver [`runbooks/degradacao-do-agr.md`](runbooks/degradacao-do-agr.md).
Nenhuma mensagem de cliente fica sem resposta por causa disto.

## 4. Os KPIs de onboarding

A `v_onboarding_kpis_semanal` **lê** a `v_onboarding_kpis` do KAM-092 e a `v_review_sla` do
KAM-089, e não as duplica. Uma linha por semana de activação (segunda-feira, `Africa/Luanda`) e uma
acumulada (`acumulado = true`):

| Coluna | Alvo (*proposta*, `tecnica/10` §16) |
|---|---|
| `owner_active_minutos_mediana` | ≤ 60 |
| `dias_calendario_mediana` | ≤ 3 |
| `sem_intervencao_ratio` | ≥ 0,80 |
| `saga_primeira_tentativa_ratio` | ≥ 0,95 |
| `fila_no_sla_ratio` | ≥ 0,90 (é o «p90 ≤ 1 dia útil» enquanto o prazo da fila for de um dia útil, o `diasUteisDoSla` do KAM-089; os casos em recurso ficam de fora, porque o recurso reescreve o prazo) |

**Os recursos órfãos não estão na vista.** A reconciliação nocturna do KAM-091 conta-os num *gauge*
em memória (`saga_orfaos{classe}`) e nenhuma tabela os guarda.

## 5. Registo de calibração

Nos primeiros 14 dias do Piloto o *job* corre em **ensaio**: abre e fecha episódios, marcados
`ensaio = true`, e não avisa nem zera nada. Um dormente aberto em ensaio é avisado na primeira
corrida fora dele e só vai a zero sete dias depois. A lista para revisão é o `Relatorio.sinais` de cada corrida e as
linhas da `v_churn_signals`.

| Data | Sinal | Limiar | Falsos positivos | Decisão | Quem |
|---|---|---|---|---|---|
| — | — | — | — | (vazio até ao Piloto) | — |

Um limiar muda num PR ao `config/kpis.yaml`, com a linha deste registo a dizer porquê.

## 6. O que não está aqui, e a quem

| Falta | Credor |
|---|---|
| O agendador que chama o `executar` de noite e o `reactivar` a cada minuto | KAM-078 (o mesmo do `kamba_core.retencao`) |
| A porta real do orçamento LiteLLM (o `OrcamentoLlm` só tem o duplo dos ensaios) | KAM-030 |
| A porta real do aviso ao dono (a `AvisoAoDono` só tem o duplo), e o aviso de cada sinal | KAM-115 |
| A suspensão das automações de um dormente: os lembretes de agendamento do KAM-048 (`services/com/src/servicos/reminders/`) continuam a sair | sem ticket; a decisão de os suspender é de produto |
| Um papel só de leitura para o Grafana: hoje só o `kamba_batch` lê as vistas entre tenants, e tem escrita a mais para ser credencial de painel | KAM-080 (o Grafana e as fontes são dele) |
| Servir as três métricas e a regra de alerta agregada | quem ligar o *job* a um processo com `/metrics` |
| Os recursos órfãos no painel | KAM-091 |
| As coortes de H1 e H9 (retenção ao dia 60, PMEs pagantes) | KAM-127 |

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 1.0 | Novembro 2026 | Emissão inicial (KAM-117). | Equipa KAMBÁ |
