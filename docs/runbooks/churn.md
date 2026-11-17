# Runbook — sinais de churn e tenants dormentes

**Esboço** (KAM-117, DoD «runbook `docs/runbooks/churn.md`»). **Não é procedimento ratificado** e
nenhum passo foi ensaiado. O desenho está em [`../kpis.md`](../kpis.md).

**Não leva número RB-K**, pela razão do [`orcamento-de-erro.md`](orcamento-de-erro.md): a série
`RB-K01`–`RB-K10` é a lista fechada do [`docs/tecnica/09`](../tecnica/09_Topologia_Operacao_Escala.md)
§13, e um `RB-K11` acrescentava uma linha a um canon que este ticket não governa.

| Campo | Valor |
|---|---|
| Cenário | Um tenant `ativo` mostra um sinal de churn, ou ficou dormente |
| Severidade | **P3**, por tenant |
| Quem age | **T2** |
| Alertas que apontam para aqui | **Nenhuma regra Prometheus.** O alerta por tenant é a linha aberta da `platform.v_churn_signals` (o `OBS-I` recusa o `tenant_id` como etiqueta, e o *job* de lote não tem `/metrics`). A regra agregada sobre `churn_signal{sinal}` nasce quando houver processo que a sirva |
| Linha canónica | [`docs/tecnica/10`](../tecnica/10_Onboarding_Governanca.md) §13 |
| Estado | **Esboço.** Gatilho e leitura fixados; contacto com o dono por escrever (KAM-115) |

---

## 1. Gatilho

A T2 lê, uma vez por dia útil, os episódios abertos. **A lista entre tenants só sai pelo lote**
(`kamba_batch`): a ligação de auditoria vê os episódios de um tenant só com o contexto dele, e
serve para confirmar um caso que já se conhece:

```sql
SELECT tenant_id, sinal, aberto_at, ensaio
  FROM platform.v_churn_signals
 ORDER BY aberto_at;

SELECT tenant_id, aberto_at, avisado_at, orcamento_a_zero, ensaio
  FROM platform.v_tenant_dormente;
```

**Não corrido** contra uma base com dados do Piloto. Nenhuma das duas vistas tem contacto, telefone,
nome ou conteúdo, e nenhuma se copia para um canal de conversa com o identificador do tenant: o que
se partilha é o sinal e o número do caso de suporte.

## 2. O que fazer por sinal (`docs/tecnica/10` §13)

| Sinal | Acção (*proposta*) |
|---|---|
| `dono_inactivo` | contacto do agente ou da T2 com o dono |
| `sem_pedidos` | revisão do catálogo e da oferta com o dono |
| `canal_desligado` | reconexão assistida (`docs/tecnica/10` §6.4); ver também o RB-K06 |
| `pagamento_em_atraso` | aviso; a suspensão é da régua de cobrança (KAM-058), não daqui |
| `catalogo_desactualizado` | lembrete ao dono |
| dormente, `avisado_at` nulo | o aviso ainda não saiu, e enquanto não sair o orçamento não vai a zero. Sem a porta do KAM-115 é sempre assim: a T2 contacta o dono à mão |
| dormente, `orcamento_a_zero = false` | avisado; vai a zero sete dias depois do aviso se nada mudar |
| dormente, `orcamento_a_zero = true` | nada a fazer: o AGR está em modo determinístico e o cliente continua a ter resposta. A primeira actividade do dono repõe o orçamento em ≤ 1 min (o `reactivar`, quando houver agendador) |

## 3. Falso positivo

Nos primeiros 14 dias do Piloto os episódios vêm com `ensaio = true` e nada é zerado. Um falso
positivo regista-se no §5 do [`../kpis.md`](../kpis.md), e o limiar muda num PR ao
`config/kpis.yaml`. **Não** se fecha um episódio à mão: o *job* fecha-o quando a condição deixa de
valer, e o `kamba_batch` é o único papel que escreve na tabela.

## 4. Repor um orçamento à mão

Só se o `reactivar` não correu (sem agendador) e o dono voltou. A porta real é do KAM-030 e ainda
não existe; até lá, o orçamento repõe-se no LiteLLM pelo procedimento de
[`rotacao-de-chaves-de-llm.md`](rotacao-de-chaves-de-llm.md), e a próxima corrida do *job* fecha o
episódio e escreve `llm.orcamento_reposto`.

## 5. O que este esboço não é

Não é o contacto com o dono (KAM-115) nem o encerramento do tenant (KAM-098). Um tenant dormente
**não** muda de estado: «dormente» é uma marca, e os cinco estados do tenant continuam os do
`docs/tecnica/00` §6.2.
