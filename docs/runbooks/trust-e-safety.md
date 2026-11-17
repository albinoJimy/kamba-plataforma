# Runbook — Trust & Safety: uma suspensão decidida, e a escada automática acima do ritmo

**Esboço** (KAM-200, critério 3). **Não é procedimento ratificado** e nenhum passo foi ensaiado
contra uma pilha com tráfego. O desenho está no [`docs/tecnica/10`](../tecnica/10_Onboarding_Governanca.md)
§8.3 e no bloco do KAM-097.

**Não leva número RB-K**, pela razão do [`orcamento-de-erro.md`](orcamento-de-erro.md): a série
`RB-K01`–`RB-K10` é a lista fechada do [`docs/tecnica/09`](../tecnica/09_Topologia_Operacao_Escala.md)
§13, e um `RB-K11` acrescentava uma linha a um canon que este ticket não governa.

| Campo | Valor |
|---|---|
| Cenário | Uma loja foi suspensa por decisão de T&S; ou a escada automática (`aviso`, `limitacao`) deu mais passos numa hora do que o ritmo esperado |
| Severidade | **P3** a suspensão; **P2** a escada acima do ritmo |
| Quem age | **T2**, com o responsável de produto de T&S |
| Alertas que apontam para aqui | `ts_suspensao_decidida` e `ts_escada_automatica_acima_do_ritmo`, em [`../../infra/compose/prometheus/regras/kamba-trust.yml`](../../infra/compose/prometheus/regras/kamba-trust.yml) |
| Série | `ts_sancoes_total{passo,origem}`, servida pelo `onboarding-lote` |
| Estado | **Esboço.** Gatilho e leitura fixados; o ritmo de 5 passos por hora é *proposta* |

---

## 1. Qual loja

A métrica não leva tenant (`OBS-I`). A loja lê-se da `platform.ts_sanction`, **pelo lote**
(`kamba_batch`): a ligação de auditoria só vê um tenant com o contexto dele.

```sql
SELECT tenant_id, passo, origem, motivo_publico, case_id, em
  FROM platform.ts_sanction
 WHERE em > now() - interval '1 hour' AND recurso_de IS NULL
 ORDER BY em DESC;
```

**Não corrido** contra uma base com dados do Piloto. O `motivo_interno`, a `regra` e os `sinais` da
mesma linha são só de T&S: não se copiam para um canal de conversa, e nunca para o dono.

## 2. Uma suspensão decidida (`ts_suspensao_decidida`)

A decisão já foi humana, com papel e MFA, na fila de revisão (KAM-089). O alerta existe para que a
equipa saiba que aconteceu, e não para a reverter. Confirmar três coisas:

1. **O estado mudou pela porta.** A suspensão passa pelo `platform.transition_tenant` (KAM-092): há
   uma linha no `platform.tenant_state_log` com o motivo `decisao_ts` e o actor do revisor, e um
   `tenant.suspended` no *outbox*. Sem a linha, a transição não aconteceu (o tenant não estava
   `ativo` nem `restrito`), e o caso mostra porquê.
2. **O aviso ao dono saiu.** Hoje **não sai**: o processo de lote não tem agregador de SMS nem o
   telefone em claro (KAM-116), e o caso fica com o efeito por reaplicar
   (`review_case.efeito_pendente_at`). É o estado esperado até o agregador existir, e não uma falha
   deste alerta.
3. **O recurso.** O dono pode recorrer uma vez; o recurso é outro caso da fila, decidido por outro
   revisor. Um recurso provido devolve a loja a `ativo` pela mesma porta (`tenant.reactivated`) — a
   menos que a suspensão em vigor seja a da régua de cobrança (KAM-058), que T&S não levanta.

## 3. A escada automática acima do ritmo (`ts_escada_automatica_acima_do_ritmo`)

Mais de cinco passos automáticos numa hora em toda a plataforma. Duas leituras, e a segunda é a
mais provável enquanto a política não estiver calibrada:

- **Um ataque em curso** — vários tenants novos a gerar `burla_provavel` ou `auto_compra`. Ver os
  sinais da última hora por tipo (`ts_sinais_total{tipo}` no painel, ou a `platform.ts_signal`
  pelo lote) e procurar um padrão comum.
- **A política de risco está a limitar lojas honestas.** Os pesos, a meia-vida e os dois limiares
  são *proposta* (`POLITICA_DE_RISCO`, `../../packages/core-ts/src/trust/regras.ts`). Uma
  `limitacao` automática bloqueia produtos novos, e cada uma é recorrível: um surto delas enche a
  fila de recursos.

**Não se desliga a escada à mão.** Mudar a política é mudar a versão dela, e isso é uma alteração
de código revista — não uma operação.

## Controlo de versões

| Versão | Data | Alteração | Autor |
|---|---|---|---|
| 0.1 | Novembro 2026 | Esboço, com as duas regras do KAM-200 | Equipa KAMBÁ |
