# Runbook RB-K03 — LLM em baixo, lento, ou sem *budget*

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
| ID | **RB-K03** |
| Cenario | Latencia de resposta acima do alvo, fila a crescer, ou orcamento diario do tenant perto do tecto |
| Severidade | **P2** (latencia e fila), **P3** (orcamento) |
| Alertas que apontam para aqui | `fila_de_entrada_a_crescer` (P2), `fila_do_agente_a_crescer` (P2), `latencia_de_resposta_alta` (P2) e `llm_sem_budget` (P3). **Nao** a `degradacao_acima_do_limiar` nem o `disjuntor_do_llm_aberto`, que apontam para [`degradacao-do-agr.md`](degradacao-do-agr.md) — a pagina que fala deles |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K03** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

Tres condicoes distintas com o mesmo destino (`docs/tecnica/09` §9.2):

- **fila** — idade do mais antigo acima de **2 minutos** (P2);
- **latencia** — p95 de resposta acima de **8 s** durante **10 minutos** (P2);
- **orcamento** — acima de **80%** do *budget* diario do tenant (P3).

O que as junta e o diagnostico: `docs/tecnica/09` §13 manda **separar «indisponivel» de «sem *budget*»** antes de agir, e as duas dao latencia alta.

## 2. Sinal

p95 > 8 s, 429/5xx dos provedores, *budget* esgotado (`docs/tecnica/09` §13, linha RB-K03).

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
