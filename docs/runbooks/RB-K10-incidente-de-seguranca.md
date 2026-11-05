# Runbook RB-K10 — Incidente de seguranca P1

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
| ID | **RB-K10** |
| Cenario | Fuga, acesso indevido, ou comprometimento confirmado |
| Severidade | **P1** |
| Alertas que apontam para aqui | Nenhuma regra de alerta aponta para aqui, e e deliberado — ver §4 |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K10** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

Entrada manual, ou escalamento a partir do **RB-K07** quando a suspeita de fuga se confirma (`docs/tecnica/09` §13, linha RB-K10).

## 2. Sinal

Ver [`../tecnica/08_Seguranca_Conformidade.md`](../tecnica/08_Seguranca_Conformidade.md) §10 e [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md). A notificacao a APD em 72 h e **boa pratica; a obrigacao esta a confirmar por parecer** — nao se cita como prazo legal certo.

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.

## 4. Este runbook nao tem alerta, e isso e deliberado

Os outros nove sao destino de pelo menos uma das doze regras. Este nao: um incidente de seguranca nao tem uma serie temporal que o anuncie, e inventar uma regra para dar simetria a tabela criava um alerta que nunca dispara — que e pior do que nenhum, porque parece cobertura.

O KAM-083 pede «bijeccao alerta ↔ runbook: todo o alerta aponta para um runbook existente **e todo o runbook tem pelo menos um alerta ou gatilho manual declarado**». A segunda metade e esta linha: o gatilho deste e **manual**, e esta declarado.
