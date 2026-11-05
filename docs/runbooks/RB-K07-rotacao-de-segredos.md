# Runbook RB-K07 — Rotacao de segredos, planeada ou em incidente

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
| ID | **RB-K07** |
| Cenario | Um segredo do inventario aproxima-se do fim de vida, ou ha suspeita de fuga |
| Severidade | **P3** (planeada); se for fuga confirmada, escala a **P1** pelo RB-K10 |
| Alertas que apontam para aqui | `segredo_a_expirar` (P3) |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K07** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

Um segredo do `ops/secrets-inventory.yaml` fica a menos de **14 dias** do fim do seu `rotacao_dias` (`docs/tecnica/09` §9.2).

O gatilho por calendario e P3 de proposito: e trabalho planeavel. O caminho de incidente — suspeita de fuga — entra pelo **RB-K10** e nao por aqui, e a diferenca e que nesse a ordem de rotacao muda (`docs/tecnica/09` §13 manda rodar primeiro o LiteLLM e os provedores).

## 2. Sinal

Calendario do inventario; suspeita de fuga (`docs/tecnica/09` §13, linha RB-K07). O procedimento de exportacao e restauro do cofre ja existe em [`../../ops/runbooks/secrets-export.md`](../../ops/runbooks/secrets-export.md) (KAM-010) e **nao** e substituido por esta pagina.

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
