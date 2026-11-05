# Runbook RB-K09 — *Flood* e *denial of wallet*

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
| ID | **RB-K09** |
| Cenario | Pico de mensagens de um contacto ou IP, ou custo de LLM anomalo |
| Severidade | **P3** (pelo alerta de orcamento); escala com o volume |
| Alertas que apontam para aqui | `orcamento_llm` (P3), em conjunto com o **RB-K03** |
| Linha canonica | [`docs/tecnica/09_Topologia_Operacao_Escala.md`](../tecnica/09_Topologia_Operacao_Escala.md) §13, linha **RB-K09** |
| Estado | **Esboco.** Gatilho e severidade fixados; procedimento por escrever (KAM-083) |

---

## 1. Gatilho

O custo de LLM de um tenant passa **80%** do *budget* diario sem que o volume de conversas o explique (`docs/tecnica/09` §9.2 e §13).

**O alerta e o mesmo do RB-K03, e o destino e que e duplo por desenho.** Orcamento a subir porque o LLM esta a ser usado e RB-K03; orcamento a subir porque **alguem** o esta a fazer subir e RB-K09. Quem atende decide qual e, e e por isso que a regra aponta para os dois.

## 2. Sinal

Por `contact_hmac`, IP e tenant (`docs/tecnica/09` §13, linha RB-K09).

**O `contact_hmac` e o identificador de diagnostico, e nao entra em etiqueta de metrica** — e pseudonimizacao, nao anonimizacao (`docs/tecnica/08` §7.2), e o espaco de numeros moveis angolanos e pequeno o bastante para ser enumeravel. O *lint* de cardinalidade recusa-o.

## 3. O que este *stub* nao e

Nao e o procedimento. Quem cair aqui durante um incidente tem de ir a
`docs/tecnica/09` §13 (diagnostico e mitigacao) e, se for um incidente de
seguranca, a [`../seguranca/resposta_incidentes.md`](../seguranca/resposta_incidentes.md).
Marcar esta pagina como suficiente para operar e exactamente o defeito que o
KAM-083 existe para fechar.
