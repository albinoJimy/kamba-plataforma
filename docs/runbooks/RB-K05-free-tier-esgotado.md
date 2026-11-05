# Runbook RB-K05 — *Free tier* de *service messages* esgotado

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
| ID | **RB-K05** |
| Cenario | O numero aproxima-se das 1.000 mensagens de servico gratuitas do mes, ou esgota-as |
| Severidade | **P2** (100%), **P3** (80%) |
| Alertas que apontam para aqui | `free_tier` (P3 aos 80%, P2 aos 100%) |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K05** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

**800** mensagens (80%) e **1.000** mensagens (100%) por numero e por mes (`docs/tecnica/09` §9.2).

Sao dois limiares e duas severidades na mesma serie, e nao dois alertas: o de 80% existe para haver tempo de agir antes do de 100%.

## 2. Sinal

800 (80%) e 1.000 por numero/mes (`docs/tecnica/09` §13, linha RB-K05).

**Facto CONFIRMADO (`E1`), e e o que torna isto P2 e nao P3:** sem metodo de pagamento no Billing Hub, a Meta **deixa de entregar** depois do *free tier*. O alerta de 100% nao e um aviso de custo — e a antecipacao de uma paragem de entrega.

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
