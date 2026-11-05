# Runbook RB-K04 — *Quality rating* amarelo ou vermelho

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
| ID | **RB-K04** |
| Cenario | A Meta baixou a classificacao de qualidade do numero ou de um template |
| Severidade | **P1** (vermelho), **P3** (amarelo) |
| Alertas que apontam para aqui | **Nenhum, hoje.** O `quality_rating` esta **por escrever**: o `channel_quality{rating}` existe e o modulo `qualidade` nao e importado por nenhum servico |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K04** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

Chega um `phone_number_quality_update` ou um `message_template_quality_update` com a qualidade em **amarelo** (P3) ou **vermelho** (P1) (`docs/tecnica/09` §9.2).

A assimetria de severidade e deliberada: amarelo e uma tendencia a corrigir com calma; vermelho e o estado em que a Meta pode pausar templates.

## 2. Sinal

`phone_number_quality_update`, `message_template_quality_update` (`docs/tecnica/09` §13, linha RB-K04).

**Facto CONFIRMADO (`E1`), que muda o que se faz:** qualidade baixa **ja nao reduz o limite** de envio, mas **pode pausar templates**. Quem operar a partir da regra antiga vai procurar um limite que nao mudou.

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
