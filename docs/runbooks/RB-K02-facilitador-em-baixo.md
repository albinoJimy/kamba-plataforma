# Runbook RB-K02 — Facilitador de pagamentos em baixo

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
| ID | **RB-K02** |
| Cenario | Criacao de referencia falha, callbacks parados, ou reconciliacao encontra pagamento por reconhecer |
| Severidade | **P1** |
| Alertas que apontam para aqui | **Nenhum, hoje.** Os dois que lhe pertencem — falhas HMAC > 3/h e pagamento por reconhecer — estao **por escrever**: o `hnd_callback_rejeitado_total` existe e o modulo `hnd` nao e importado por nenhum servico. Ver `regras_por_escrever` em [`../../ops/metricas/catalogo.yaml`](../../ops/metricas/catalogo.yaml) |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K02** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

Falhas de verificacao HMAC acima de **3 por hora**, **ou** o reconciliador encontra um pagamento por reconhecer (`docs/tecnica/09` §9.2).

As duas metades sao alertas diferentes com o mesmo destino, e a distincao e operacional: falhas de HMAC podem ser uma rotacao de chave mal feita (RB-K07); um pagamento por reconhecer e dinheiro que o cliente pagou e que nos nao vimos.

## 2. Sinal

Criacao de referencia falha; callbacks parados; reconciliador encontra pagamentos por reconhecer (`docs/tecnica/09` §13, linha RB-K02).

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
