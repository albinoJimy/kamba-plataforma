# Runbook RB-K08 — Base de dados indisponivel ou corrompida; restauro PITR

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
| ID | **RB-K08** |
| Cenario | WAL parado, *host* perdido, erro de integridade, ou restauro mensal falhado |
| Severidade | **P1** (WAL parado), **P2** (restauro mensal falhado) |
| Alertas que apontam para aqui | `wal_atrasado` (P1), `restauro_mensal_falhou` (P2) e `ingress_parado` (P1), este em conjunto com o **RB-K01** |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K08** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

Duas condicoes com severidades diferentes (`docs/tecnica/09` §9.2):

- **WAL** — o ultimo arquivo tem mais de **5 minutos** (P1);
- **restauro mensal** — o *job* de restauro do mes falhou (P2).

O WAL e P1 e o restauro falhado e P2, e a ordem nao e arbitraria: o WAL parado e perda de dados **a acontecer agora** (o RPO a crescer em tempo real); o restauro falhado e a descoberta de que a rede de seguranca pode nao estar la — grave, mas sem relogio a correr.

## 2. Sinal

`pgbackrest check`, estado do disco (`docs/tecnica/09` §13, linha RB-K08). O desenho de backups e DR e o §8 do mesmo documento; o pgBackRest e o **KAM-079**.

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
