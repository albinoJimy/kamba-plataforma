# Runbook — Off-boarding: um encerramento parado numa fase

**Esboço** (KAM-210, critério 1). **Não é procedimento ratificado** e nenhum passo foi ensaiado
contra uma pilha com tráfego. O desenho das fases está no [`../offboarding.md`](../offboarding.md) e
no bloco do KAM-098; o processo que as corre, no bloco do KAM-210.

**Não leva número RB-K**, pela razão do [`orcamento-de-erro.md`](orcamento-de-erro.md): a série
`RB-K01`–`RB-K10` é a lista fechada do [`docs/tecnica/09`](../tecnica/09_Topologia_Operacao_Escala.md)
§13.

| Campo | Valor |
|---|---|
| Cenário | Uma fase do encerramento de um tenant está `falhada`; ou `em_curso` com o prazo passado há mais de 24 h; ou `pendente` nas mesmas 24 h **com as fases anteriores concluídas** — podia correr e não correu |
| Severidade | **P2** |
| Quem age | **T2**, com o engenheiro de plataforma (TEN) |
| Alerta que aponta para aqui | `offboarding_fase_parada`, em [`../../infra/compose/prometheus/regras/kamba-offboarding.yml`](../../infra/compose/prometheus/regras/kamba-offboarding.yml) |
| Série | `offboarding_fases_paradas{fase}`, servida pelo `onboarding-lote` |
| Estado | **Esboço.** A folga de 24 h, o `for` de 30 min e o intervalo de 15 min do ciclo são *proposta* |

---

## 1. Qual encerramento

A métrica não leva tenant (`OBS-I`). O encerramento lê-se da `platform.offboarding_run`, **pelo
lote** (`kamba_batch`); a etiqueta `fase` do alerta diz qual procurar.

```sql
SELECT tenant_id, fase, estado, prazo_at, resultado
  FROM platform.offboarding_run
 WHERE estado = 'falhada'
    OR (estado IN ('pendente', 'em_curso') AND prazo_at + interval '24 hours' < now())
 ORDER BY prazo_at;
```

Esta consulta é mais larga do que o alerta: traz também as fases `pendente` que esperam uma anterior
por concluir. A que conta é a **primeira** de cada tenant pela ordem do calendário; as seguintes
esperam por ela.

**Não corrido** contra uma base com dados do Piloto. O `resultado` de cada fase leva contagens,
passos e instantes, e nada do dono.

## 2. O que a fase diz

| Fase | Quem a corre | Causa mais provável hoje | O que fazer |
|---|---|---|---|
| `canal` | `onboarding-lote` | **A porta da Meta não tem adaptador** neste processo (`PortaSemAdaptadorError`): o adaptador existe, mas o *token* de cada WABA vive no cofre, e o cofre não tem leitor no lote | Até ao credor (KAM-218), cancelar a subscrição à mão no Business Manager e marcar a fase com o resultado, como o código a marca. **Nunca** apagar o WABA nem o número: são do cliente (E1) |
| `pendentes` | `onboarding-lote` | Uma encomenda em curso, uma reserva activa ou um reembolso aberto depois do D7 | O `resultado` tem as contagens. Fechar cada uma pelo caminho dela (o dono, ou ops); a volta seguinte conclui |
| `exportacao` | o lado dos dados | O armazenamento falhou, ou o tenant tem mais de 10 000 objectos (o tecto da listagem do KAM-011) | Resolver os pendentes; ou, com o STO de volta, chamar `correr_fase` para `exportacao` |
| `revogacao` | `onboarding-lote` | Uma porta da saga sem adaptador (LiteLLM, Medusa, Chatwoot) **para um recurso que a saga criou**; ou o tenant ficou `restrito` | O `resultado.passos` diz quais já correram, e os feitos não se repetem. Um tenant `restrito` não tem aresta para `encerrado` (decisão do fundador) |
| `purga` | o lado dos dados | `falhada`: uma unidade levantou, e o `purge_log` tem a linha `falhou` | Corrigir a causa e chamar `correr_fase` para `purga`. **Não se repete sozinha**: cada corrida escreve no `purge_log`, que é *append-only* |
| `certificado` | o lado dos dados | **A entrega não tem adaptador** (`PortaSemAdaptador`): não há agregador de SMS nem fornecedor de e-mail escolhidos | Até ao credor (KAM-218), a entrega é manual. O documento é o mesmo em cada tentativa; o canal do titular só sai depois de entregue |

Uma purga `suspensa_disputa` **não** dispara este alerta, e o certificado atrás dela também não:
espera a disputa, e é o que deve fazer. Uma fase que espera outra por concluir também não: conta a
que está à frente.

## 3. Correr uma fase do lado dos dados à mão

`kamba_core.offboarding.correr_fase(abrir_batch, abrir_app, portas, tenant_id, fase, agora)`, com as
mesmas portas do processo. Cada fase pergunta outra vez, sob trinco, se o pedido está vivo e se a
anterior concluiu; correr a mais não duplica nada (KAM-098, critério 9).

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | Novembro 2026 | Esboço, com a regra do KAM-210 | Equipa KAMBÁ |
