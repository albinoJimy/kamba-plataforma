# Runbook RB-K01 — Meta em baixo

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
| ID | **RB-K01** |
| Cenario | A Cloud API da Meta nao aceita envios, ou a ingestao parou |
| Severidade | **P1** |
| Alertas que apontam para aqui | `ingress_parado` (P1), em conjunto com o **RB-K08** |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K01** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

A sonda sintetica externa falha **duas** vezes seguidas, **ou** o numero de mensagens recebidas e zero durante mais de **10 minutos** em horario comercial (07:00-23:00 WAT, `docs/tecnica/09` §9.2).

O horario importa: fora dele, zero mensagens e o estado normal, e um alerta que dispara todas as noites ensina a equipa a ignora-lo.

## 2. Sinal

Erros 5xx no envio, sonda a falhar, `graph.facebook.com` indisponivel (`docs/tecnica/09` §13, linha RB-K01).

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
