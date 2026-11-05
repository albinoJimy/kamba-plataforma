# Runbook RB-K06 — Expiracao ou invalidacao de token, ou desligacao da conta

**Esboco** (KAM-080, criterio 4: «os *stubs* RB-K01 a RB-K10 (titulo, gatilho,
severidade)»). **Nao e procedimento ratificado e nao se executa a partir daqui.**
O runbook completo — passos executaveis por quem nao esteve na conversa,
ensaiados por outra pessoa que nao o autor — e o **KAM-083**, que depende deste
ticket.

O que este *stub* existe para fazer sao duas coisas, e so duas:

1. **dar ao alerta um destino que existe.** A regra do `docs/tecnica/09` §9.2 e
   «alerta sem runbook e removido»; o `runbook_url` de cada regra de alerta
   aponta para este ficheiro, e o *lint* de `tools/obs_lint` recusa um alerta
   cujo destino nao exista no disco;
2. **fixar o gatilho e a severidade**, que sao o que o alerta codifica. O
   diagnostico e a mitigacao estao na linha deste runbook em
   `docs/tecnica/09` §13 e **nao se repetem aqui**, para que nao haja duas
   versoes a divergir antes de o KAM-083 escrever a definitiva.

| Campo | Valor |
|---|---|
| ID | **RB-K06** |
| Cenario | `account_update` com `PARTNER_REMOVED`, `PRIMARY_INACTIVITY` ou `ACCOUNT_DISCONNECTED` |
| Severidade | **P2** |
| Alertas que apontam para aqui | **Nenhum, hoje.** O `account_update` esta **por escrever**: o `channel_disconnected_total` existe e o modulo `coexistencia` nao e importado por nenhum servico |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K06** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

Chega um webhook `account_update` com `PARTNER_REMOVED`, `PRIMARY_INACTIVITY` (≈ 14 dias) ou `ACCOUNT_DISCONNECTED`, ou uma chamada falha por token invalido (`docs/tecnica/09` §9.2 e §13).

## 2. Sinal

Cliente desligou, inactividade, ou mudanca de numero (`docs/tecnica/09` §13, linha RB-K06).

**O passo que nao se pode esquecer, e esta aqui por isso:** o aviso ao dono vai **por canal alternativo**. O canal que falhou foi precisamente o WhatsApp, e mandar por WhatsApp o aviso de que o WhatsApp caiu e uma mensagem que nunca chega.

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
