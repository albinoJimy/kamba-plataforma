# Runbook — degradação do AGR e modo determinístico

> **Esboço** (KAM-037, DoD «documentação do runbook de degradação actualizada»).
> Não é procedimento ratificado, e três coisas que ele manda olhar ainda não
> existem: **não há sistema de alertas** neste repositório (medido: não há
> `ops/alertas*`, nem `PrometheusRule`, nem `alerting_rules`), a agregação
> contínua das métricas é o **KAM-080**, e o AGR **não expõe `/metrics`** — a
> leitura faz-se por `METRICAS.exposicao()`, que é o que a bateria lê. O que está
> aqui é o que se consegue escrever hoje, com os passos que dependem de
> infra-estrutura marcados.

| O que degrada | Detecção | O que o AGR faz |
|---|---|---|
| LLM lento (*timeout* de 20 s do `kamba-chat`) | `ErroDeLlm` do tipo `TempoEsgotado` no `classify` | modo determinístico, motivo `timeout` |
| LLM a recusar por ritmo (HTTP 429) | `estado_http == 429` no erro tipado | modo determinístico, motivo `http_429` |
| Orçamento da chave virtual esgotado | `error.type == "budget_exceeded"` (HTTP 422, não 400 — ver `../evidencia/KAM-030-litellm.md` §4) | modo determinístico, motivo `budget` |
| Disjuntor do LLM aberto | três falhas consecutivas, pausa de 30 s | modo determinístico, motivo `breaker`, **sem ir ao proxy** |
| Contrapressão | *tenant* no tecto de concorrência **e** fila acima do limiar | modo determinístico, motivo `backpressure` |
| **Postgres ou *checkpointer* indisponível** | erro de ligação | **não degrada**: o turno não corre, a mensagem fica na fila, 503 com `Retry-After`. Alerta crítico |

A última linha é a que se perde primeiro, e é a mais importante desta página.
Degradar com o estado indisponível era responder **sem carrinho, sem `stage` e
sem janela de mensagens** — o oposto do que o modo existe para fazer. O
`docs/tecnica/02` §14 dá-lhe linha própria e o detector impõe-no por tipo: só um
`ErroDeLlm` degrada, e qualquer outra excepção sobe.

---

## 1. Como se vê que há degradação

Três números, e nenhum substitui os outros:

```text
agr_degraded_turns_total{motivo}        quantos turnos correram em modo determinístico
agr_degraded_breaker_aberto_total       quantas vezes o modelo ficou inalcançável
agr_turns_total{outcome="falhou"}       turnos que NÃO correram
```

**A leitura que importa é a combinação, não cada um.** O `degraded_turns` a subir
com o `falhou` estável é o modo a funcionar: o cliente está a receber menus em vez
de nada. O `falhou` a subir com o `degraded_turns` **estável** é o caso da última
linha da tabela — o estado não está disponível, nada degradou, e as mensagens
estão a acumular-se na fila. É esse que é Sev1, e não o primeiro.

**O `tenant_id` não está em etiqueta nenhuma**, por desenho (`OBS-I`, e a
gramática de etiqueta recusa-o pela forma). Para saber **que** *tenant* degradou,
a via é o campo `tenant_id` do *logger*, que a *allowlist* de
`../tecnica/08` §7.3 permite em log.

## 2. O alerta, e porque é que ele é uma proposta

> Alerta quando mais de **5%** dos turnos de um *tenant* degradam em **15
> minutos**, com um mínimo de **vinte** turnos na janela.

Os três números são ***proposta***. Os dois primeiros vêm do critério 6 do
KAM-037, que escreve «limiar *proposta*»; o mínimo é nosso e não está no critério
— sem ele, um único turno degradado dá 100% e alerta por um caso. Calibram-se no
**KAM-084**, com os cinco tectos do `admissao.py`.

**A janela é por processo e não por réplica.** Duas réplicas do AGR têm duas
janelas, e cada uma alerta sobre o que viu: um *tenant* repartido por duas chega
ao limiar mais tarde em cada uma. O que se perde é sensibilidade, não correcção, e
fechar isso pedia estado partilhado — Redis ou uma tabela — para um limiar que
ainda é proposta.

**Onde é que o alerta dispara hoje: em nenhum sítio automático.** Não há sistema
de alertas (ver a nota de topo). O `registar_turno` devolve `True` quando o limiar
passa, e quem o chamar liga isso ao que existir. É a mesma situação do
`agr_registry_denied_total` (KAM-027) e do `agr_draft_pendentes` (KAM-114): uma
métrica com nome mais esta página.

## 3. O que o modo determinístico serve, e o que não serve

| Serve | Por onde |
|---|---|
| menu principal, até três botões | `degraded_menu` |
| lista de opções, quatro linhas | `degraded_menu` |
| estado do pedido | `order_status`, o do grafo normal |
| horário e morada da loja | `tools_info`, o do grafo normal |
| confirmação de um carrinho **já construído** | `confirm_gate` → `create_order` |
| «falar com um colega» | `handoff_prepare` |

| **Não** serve | Porquê |
|---|---|
| pesquisa de catálogo e preços | a lista do critério 2 não a enumera. O IDX não é o LLM e não está em baixo quando o modelo está, pelo que isto é a **letra do critério** e não uma limitação técnica — e está devolvido ao fundador |
| construir um carrinho novo | pede o `propose_cart`, que o critério 2 não nomeia. Servir a compra sem servir a pesquisa dava um carrinho sobre um produto que o cliente não pôde ver neste turno |
| repetir a **referência de pagamento** com os dígitos | uma referência é uma cadeia opaca com dígitos e nenhum dos cinco blocos do §9.1 a leva. É a **dívida 124**, credor **KAM-032**. Serve-se em espécie — a palavra do estado do pedido — e não em detalhe |
| o perfil de **Serviços** | fora de âmbito do KAM-037; abre-se como ticket próprio quando o **KAM-035** estiver `Done` |

**Nada sai sem passar pelo validador.** O menu escreve blocos e a aresta leva-o
ao `validate`, como o `compose` — ao contrário das respostas estáticas das arestas
da linha 34, que passam ao lado dele. É o critério 5, e o custo é real: os textos
do modo passam pelo `renderizar`, que recusa dígitos e prosa numérica. Quem
escrever um texto novo lê o cabeçalho de
`services/agr/src/kamba_agr/verticais/vendedor/degradado/textos.py` primeiro.

## 4. Quando a degradação é do concierge e não do LLM

Um *tenant* com a política `concierge` activa **não recebe a resposta
determinística directamente**: ela vai a aprovação humana, como qualquer outra
resposta daquele *tenant*. Os dois mecanismos somam-se e não se substituem.

**Isto é uma leitura e não uma decisão fechada.** O KAM-037 foi escrito antes do
KAM-114 e nenhum dos dois diz o que acontece com os dois em vigor; a leitura
implementada é a que não retira a barreira do KAM-114 («sem decisão humana não sai
mensagem»), e a decisão está devolvida ao fundador na secção de verificação do
bloco do KAM-037.

A consequência operacional: num *tenant* concierge, o LLM em baixo **não** faz
chegar nada ao cliente até um operador aprovar. O que se vê nos números é o
`agr_degraded_turns_total` a subir **e** o `agr_draft_pendentes` a subir com ele.
Se o segundo subir sozinho, não é degradação: é falta de operador.

## 5. Como recuperar

**Não há passo de recuperação a correr, e isso é desenho.** O `degradado` é um
campo do turno, reiniciado no `ingest`: o turno seguinte nasce sem ele e o
detector volta a ser consultado. O disjuntor fecha-se ao **primeiro** sucesso
(contagem de falhas consecutivas) e, passada a pausa de 30 s, deixa passar **uma**
tentativa. Logo:

* **LLM recuperado** → o turno seguinte vai ao modelo e sai do modo sozinho;
* **orçamento recarregado** → idem, porque a chave volta a responder;
* **contrapressão** → sai quando a fila desce ou o *tenant* liberta vagas.

Não se reenviam respostas antigas. O `draft` é do turno e o `ingest` reinicia-o,
pelo que não há resposta antiga para reenviar; quem impõe a janela de 24 h é o
Outbound (**KAM-015**), e o modo determinístico não a contorna — fora da janela
só por *template*.

## 6. O que fazer, por ordem

1. **Olhar primeiro o `agr_turns_total{outcome="falhou"}`.** Se estiver a subir e
   o `degraded_turns` não, o problema é o estado e não o modelo: ver Postgres e o
   `lg`. As mensagens estão na fila e não se perderam.
2. **Se for `budget`:** a chave virtual do *tenant* esgotou-se. O orçamento é 15%
   da mensalidade (`../tecnica/02` §13.3) e há alerta aos 80% — que também não tem
   onde disparar hoje. Recarregar a chave; o turno seguinte sai do modo.
3. **Se for `timeout` ou `http_429`:** o fornecedor. O *fallback* entre
   fornecedores é do router do proxy e não nosso; ver
   `rotacao-de-chaves-de-llm.md` se houver suspeita de credencial.
4. **Se for `breaker`:** o disjuntor já está a poupar as idas. Confirmar que o
   proxy responde antes de mexer em alguma coisa — a pausa é de 30 s e ele
   resolve-se sozinho se o fornecedor voltar.
5. **Se for `backpressure`:** é a regra 4 do §15.2 a funcionar. Subir a escala
   horizontal dos *workers*; o tecto por *tenant* e o limiar da fila são
   `AGR_TECTO_POR_TENANT` e `AGR_LIMIAR_DE_CONTRAPRESSAO`, os dois *proposta*.

## 7. O que esta página não cobre

* **o canário do alerta** — não há sistema de alertas, pelo que não há forma de
  provar que o alerta morde. Credor: **KAM-080** (agregação contínua) e quem
  escolher o sistema;
* **a medição em `staging`** da proporção real de turnos degradados, que é o que
  calibra o limiar. Credor: **KAM-084**;
* **os casos degradados no *golden*** e o *lock* dos textos do modo, que é o
  **gate 13** — e o gate 13 **não existe**: não há alvo `ci-13` no `Makefile` nem
  *job* no `.github/workflows/ci.yaml`. Credor: **KAM-040**;
* **o perfil de Serviços**, que usa o mesmo mecanismo. Credor: **KAM-035**, e
  abre-se como ticket próprio.
