# ADR-L012 — A pesquisa no Piloto: *eval-gate* em aviso, relatório de *tokens* só do *dataset*, e só lexical

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-11-16 |
| Ticket | KAM-199 — Activação do *eval-gate* de pesquisa e troca do modelo de embeddings |
| Âmbito | Local (ver [`README.md`](README.md)): as três perguntas que o KAM-064 deixou ao fundador em [`../evidencia/KAM-064.md`](../evidencia/KAM-064.md) §4. Não acrescenta contexto exigido ao *ruleset* de `main`, não muda o `ci/thresholds.yaml` nem o `needs` do agregador, e não decide o modelo de embeddings: adia-o, com o credor escrito |
| Decisores | **O fundador, a 2026-11-16**, no chat com o orquestrador do lote |
| ADRs canónicos aplicáveis | ADR-006 (pesquisa híbrida, sem ANN no Piloto), ADR-008 (destinos de transferência autorizados), ADR-018 (o *golden set* e as suas origens) |
| Documentos aplicáveis | [`../tecnica/05_Indice_Pesquisa_Motor_Atencao.md`](../tecnica/05_Indice_Pesquisa_Motor_Atencao.md) §14; [`../../specs/EPIC-06_Indice_Pesquisa.md`](../../specs/EPIC-06_Indice_Pesquisa.md) (blocos KAM-062, KAM-063, KAM-064 e KAM-199); [`../ci.md`](../ci.md) §2 e §3; [`../../llm/aliases.yaml`](../../llm/aliases.yaml) (`kamba-embed`); [`../../specs/INDICE.md`](../../specs/INDICE.md) §6 |
| Substitui | — |

## Contexto

O KAM-064 entregou o *dataset* `golden_search` (100% sintético), o executor, as
métricas, o *gate* do §14.3 como comando e a linha de base `1.0.0`. Três caixas
que recebeu do KAM-062, do KAM-063 e do KAM-194 não fechavam sem uma decisão do
fundador, e o anexo dele preparou-as com as opções e a medição que as informa.
As três foram respondidas a 2026-11-16, e as três respostas foram as
recomendadas no anexo. Este ADR regista-as no repositório, que é onde a
autoridade do canon se escreve.

## Decisão 1 — O *job* de CI do *eval-gate*: opção C, aviso

O *eval-gate* da pesquisa corre no CI como **aviso, não exigido**, enquanto o
*dataset* for 100% sintético: o *job* `gate-13-pesquisa`, com
`continue-on-error`, fora do `needs` do agregador `gates do KAM-002` e fora dos
contextos exigidos do *ruleset*. Uma regressão fica vermelha no PR e não impede a
fusão.

**Promove-se a exigido quando houver dados reais**, e essa promoção **volta ao
fundador**: é uma regra de bloqueio.

*Proposta do KAM-199, e não parte da decisão:* levar à promoção as duas caixas
que só ganham sentido com um *gate* que bloqueia — a anotação B por uma segunda
pessoa com o κ (critério 2 do KAM-064, trabalho de *ops* com duas pessoas) e as
métricas da execução no painel de OBS (DoD do KAM-064). Fica como pergunta ao
fundador, e não como decidido.

**Porque não as outras.** A (exigido em todo o PR) e B (exigido, filtrado por
caminhos) bloqueavam fusões com um *dataset* escrito por uma só pessoa; D (um
passo dentro do *gate* 8) mudava o critério do *gate* 8, que também é regra de
bloqueio, e alongava o *gate* mais lento.

## Decisão 2 — O relatório de *tokens* não resolvidos: opção A, nada em produção

**Não se guarda nada em produção.** O relatório de *tokens* não resolvidos corre
só sobre o *dataset*: é o `tokens_nao_resolvidos` do relatório do
`golden_search`, que sai em cada execução do *gate*. O critério 8 do KAM-062 reescreve-se nesta forma, e perde o
«≥ 5 sujeitos distintos», que só fazia sentido com consultas reais.

**Porque não as outras.** A B guardava, por semana, um conjunto de
`HMAC(sal, sujeito)` por *token*; a C guardava consultas pseudonimizadas. As duas
são dados ligados a sujeitos, e a C pedia base legal e consentimento específico
(a confirmar por parecer). Perde-se o sinal real da cauda; recupera-se quando o
*dataset* 2.0.0 trouxer consultas reais reescritas, pelo plano do anexo do
KAM-064 §3.

## Decisão 3 — O `kamba-embed`: opção A, só lexical no Piloto

**O Piloto fica em modo lexical, e o vector não se liga.** O `kamba-embed`
continua `por_decidir` em `llm/aliases.yaml`, e o AGR não passa a
`ConsultaVectorial`. Ficam **para depois do Piloto**, e não se implementam no
KAM-199:

- o modo híbrido e a escolha do modelo (PROP-IDX-4; critério 8 do KAM-063), com
  ≥ 2 candidatos medidos na divisão `dev`;
- a calibração do limiar do `retrieve` do AGR para o híbrido (o `LIMIAR_DO_RRF`
  de 0,3 deixa passar sempre o vizinho mais próximo: falso-positivo de 100% no
  anexo do KAM-064);
- a coluna com a dimensão do modelo e a comutação atómica (critério 6 do KAM-063);
- o p95 do embedding em *staging* e os 2 000 produtos com o fornecedor real, e a
  fila de mortos persistida (critérios 3 e 7 do KAM-063);
- o *eval-gate* verde na troca de modelo, com linha de base nova (DoD do KAM-063).

**O credor** é a linha «Pesquisa híbrida» do [`../../specs/INDICE.md`](../../specs/INDICE.md)
§6 (o que fica fora e quando entra), com o gatilho escrito: o *gate* do Piloto
(KAM-110) verde, um destino de transferência autorizado com `apd_ref` (ADR-008)
ou um modelo servido em Luanda, e a decisão do modelo. O `credor` do
`kamba-embed` em `llm/aliases.yaml` é o **KAM-063**, que fica aberto com as
caixas do modelo, a começar pelo critério 8 (o documento de decisão do
modelo, que é o que tira o *alias* de `por_decidir`). O campo só aceita um
`KAM-NNN`, e o KAM-199 fecha com a sua fusão. Escolha do orquestrador do lote
a 2026-11-16, depois de recusados o KAM-110 (dar-lhe a caixa mudava os
critérios de um *gate*, que são do fundador) e um ticket novo (o §1 do
backlog mestre só escreve a Fase 2 com o KAM-110 verde).

**Porque não as outras.** B e C pediam chamadas pagas ou infraestrutura antes de
haver um número sobre um modelo real, e o que o *dataset* mostra do modo híbrido
é de um fornecedor falso de trigramas, não de um modelo.

## Consequências

- **O que o KAM-199 entrega:** o *job* de aviso, a reescrita do critério 8 do
  KAM-062, e a revisão que troca a `termo_canonico_dataset_inactivo_ck` por uma
  activação com o relatório verde do *gate* anexado (`idx.eval_relatorio`). Uma
  entrada de léxico de *dataset* pode ficar activa a partir de agora, mas só com
  um relatório que a base aceite como verde **e que a tenha medido**
  (`golden_search --lexico`).
- **O que fica aberto, e de quem:** a anotação B e o κ (*ops*, com duas pessoas);
  a promoção do *job* a exigido (o fundador, quando houver dados reais); as
  métricas no painel de OBS (uma pergunta ao fundador, acima); o modo híbrido
  inteiro (a linha do §6 do `specs/INDICE.md`).
- **Reverte-se** por decisão do fundador, e cada uma das três de forma
  independente: a 1 promovendo o *job*, a 2 com um ticket que guarde o agregado
  da opção B, a 3 ligando o vector depois do Piloto.
