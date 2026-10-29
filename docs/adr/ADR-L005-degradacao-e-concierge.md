# ADR-L005 — O que acontece com o modo determinístico e o modo concierge em vigor ao mesmo tempo

| Campo | Valor |
|---|---|
| Estado | Aceite |
| Data | 2026-10-29 |
| Ticket | KAM-037 — Modo determinístico sem LLM e degradação |
| Âmbito | Local (ver [`README.md`](README.md)): o que sai ao cliente quando o LLM está indisponível **e** a política `concierge` está activa no mesmo *tenant*. Não decide a política de concierge (**KAM-114**), nem os gatilhos da degradação (este ticket), nem o que o modo determinístico serve |
| Decisores | **O fundador, a 2026-10-29**, sobre a leitura que o executor do KAM-037 implementou e devolveu |
| ADRs canónicos aplicáveis | ADR-002 (LangGraph), ADR-007 (números só de *tools*), ADR-018 (observabilidade e proibição de treino) |
| Documentos aplicáveis | [`../tecnica/02_Agent_Runtime_Verticais.md`](../tecnica/02_Agent_Runtime_Verticais.md) §7.3 linha 35, §11, §14; [`../tecnica/00_Arquitectura_Solucao.md`](../tecnica/00_Arquitectura_Solucao.md) princípio 12; [`../agr.md`](../agr.md) §7-I; [`../concierge.md`](../concierge.md); [`../../specs/02_Dicionario_de_Dados_Canonico.md`](../../specs/02_Dicionario_de_Dados_Canonico.md) §3.34 e §3.35 |
| Substitui | — |

## Contexto

O **KAM-037** foi escrito antes do **KAM-114**, e o KAM-114 fundiu a 2026-10-28
(`0baea39`). Nenhum dos dois blocos diz o que acontece quando os dois mecanismos
estão em vigor no mesmo *tenant*:

* o KAM-037 manda «degradar, nunca calar» — com o LLM em baixo, o turno responde
  por menus e *templates*, e o critério 1 conta «0 turnos sem resposta em 100
  execuções»;
* o KAM-114 manda «sem decisão humana registada não sai mensagem» — o nó `send`
  é substituído por um pedido de aprovação, e o critério 1 **dele** conta «0
  mensagens ao cliente sem decisão».

**Os dois critérios 1 não podem ser os dois verdadeiros ao mesmo tempo** para um
*tenant* que esteja nas duas condições. Quem decide qual cede é o fundador, e é
isso que este ADR registra.

### As três leituras, e o que cada uma custa

| Leitura | O que preserva | O que custa |
|---|---|---|
| **A** — a resposta determinística **também** vai a aprovação; os dois somam-se | A barreira do KAM-114, intacta: nada sai sem decisão humana | O critério 1 do KAM-037 fica **falso** para esses *tenants*: o cliente não recebe nada até um operador aprovar, e é precisamente quando o sistema está degradado |
| **B** — o modo degradado passa à frente do concierge | O critério 1 do KAM-037: o cliente recebe sempre resposta | Uma mensagem sai **sem aprovação** quando o sistema está degradado. É o furo que o KAM-114 existe para fechar, aberto no momento de menor controlo |
| **C** — o concierge fica suspenso enquanto houver degradação | O mesmo que a **B**, com o estado explícito | O mesmo furo da **B**, mais uma máquina de estados nova — e uma política de segurança que se desliga por uma condição que o próprio sistema detecta |

A **B** e a **C** retiram uma barreira, e a regra de implementação desta casa é
que *mínimo* nunca é isso: «uma política RLS, um *fail-closed*, um passo de
canário, uma verificação de assinatura não são código a mais: são o produto».

## Decisão

**(A) Com a política `concierge` activa, a resposta determinística do modo
degradado também vai a aprovação humana. Os dois mecanismos somam-se e não se
substituem.** Decidida pelo fundador a 2026-10-29.

Concretamente:

1. **Não há código de interacção**, e isso é a propriedade que a torna segura. O
   KAM-114 intercepta no nó `send`, que é por onde passam as **cinco** arestas de
   saída do grafo (a 32, as três da 34, e a 37), e o caminho degradado sai por
   uma delas. A nota da aresta 35 em
   [`../../services/agr/src/kamba_agr/verticais/vendedor/arestas.py`](../../services/agr/src/kamba_agr/verticais/vendedor/arestas.py)
   já escrevia a razão de interceptar **ali** e não à entrada de cada caminho:
   «uma resposta estática é uma mensagem ao cliente tanto como uma composta».
   Uma resposta determinística é textualmente dessa classe.
2. **O `draft_prepare` e o `draft_wait` não precisam do LLM**, pelo que a
   aprovação funciona com o modelo em baixo: o primeiro grava a linha e publica
   no HND, o segundo só faz `interrupt()`.
3. **O critério 1 do KAM-037 mede-se com a política desligada**, que é o caso de
   todos os *tenants* fora do Piloto concierge, e a secção de verificação do
   bloco diz isso por extenso em vez de o esconder num ensaio.
4. **O que o cliente de um *tenant* concierge vê, com o LLM em baixo, é nada até
   um operador aprovar.** Está escrito no runbook
   ([`../runbooks/degradacao-do-agr.md`](../runbooks/degradacao-do-agr.md) §4) com
   o sinal que o distingue de uma avaria: o `agr_degraded_turns_total` a subir
   **e** o `agr_draft_pendentes` a subir com ele. Se o segundo subir sozinho, não
   é degradação — é falta de operador.

## Consequências

**Boas.** A barreira do KAM-114 não tem excepções, e uma barreira sem excepções é
verificável por posição em vez de por regra: não há caminho a auditar, porque não
há caminho alternativo. Para um *tenant* concierge, a degradação do LLM deixa de
ser um evento de segurança — passa a ser latência.

**Más, e assumidas.** Um *tenant* concierge sem operador disponível e com o LLM
em baixo deixa o cliente sem resposta até o prazo das 24 h fechar o rascunho como
`expirado`. O princípio 12 («o utilizador nunca fica sem resposta») cede aqui
perante o critério 1 do KAM-114, e cede **por decisão** e não por omissão.

**O que isto obriga, e o credor de cada:**

* **medir a latência de aprovação no Piloto concierge**, porque é ela que decide
  se esta leitura é tolerável em produção. O alvo de ≤ 5 s do critério 4 do
  KAM-114 é latência do HND até ao operador, não até à decisão dele. Credor:
  **KAM-109**;
* **o alerta de rascunhos pendentes** (`agr_draft_pendentes`, KAM-114) passa a
  ter uma segunda leitura — com degradação a correr, é o sinal de que a fila de
  aprovação não está a ser servida. Fica no runbook; o artefacto de alerta é o
  **KAM-080**;
* **a guarda de arranque para o par «política activa, `ServicoDeRascunho` por
  ligar»**: com o LLM em baixo **todos** os turnos chegam ao `draft_prepare`, e
  sem serviço ele levanta `ConciergeSemServicoError` e o *job* repete para
  sempre. É comportamento do KAM-114 e não deste ticket, mas o modo degradado é
  o caminho que mais vezes o atinge — é o achado `P4`/`P3` da
  [`../analises/ANALISE-39-kam-037-modo-deterministico.md`](../analises/ANALISE-39-kam-037-modo-deterministico.md),
  e o credor é quem ligar a porta `grafos` do `turno.py`.

## Esta decisão é candidata a subir a canónica, e isso não se decide aqui

O [`README.md`](README.md) deste directório fixa o critério: uma decisão local
sobe a canónica «quando passa a governar mais do que o seu ticket — porque outro
subsistema depende dela». **Esta governa dois tickets** (o KAM-037 e o KAM-114) e
uma invariante de segurança do produto, pelo que o critério aponta para cima.

Fica **local** porque promovê-la é uma alteração ao canon que ninguém pediu: um
ADR canónico novo em `../tecnica/00` §8 toma o número seguinte ao último — hoje o
**vigésimo**, que o fundador acrescentou a 2026-10-09 e a Carta marca FIXA — e
obriga a actualizar a contagem de ADRs e o mapeamento ADR → documento em
`../tecnica/INDICE.md` §5; a classificação dos ADRs é, ela própria, proposta até o
fundador a ratificar. O que falta para a promover está nomeado aqui; quem a
promove é quem o fundador mandar.

(**Não se escreve aqui o número que ela teria.** O `lint_refs` recusa uma
referência a um `ADR-NNN` que o §8 não tem — e recusou esta frase na primeira
versão, com razão: um número de ADR escrito antes de o ADR existir lê-se como
canon a quem passar por aqui. A dispensa em `ci/refs-allow.yaml` existe e **não**
se usou: o próprio ficheiro diz que não é mecanismo de dispensa genérico.)

## Como se mede que isto é verdade

```text
TestDegradadoComConcierge::test_o_menu_degradado_vai_a_aprovacao_e_nao_sai_ao_cliente
  política activa + disjuntor aberto -> 0 mensagens ao cliente, 1 rascunho aberto,
  com o texto do menu e o `graph_version` 1.2.0

TestDegradadoComConcierge::test_sem_a_politica_o_menu_degradado_sai_no_mesmo_turno
  política desligada -> 1 mensagem no mesmo turno, 0 rascunhos
```

Em [`../../services/agr/tests/test_degradacao.py`](../../services/agr/tests/test_degradacao.py).
A revisão adversarial do KAM-037 procurou o furo — uma mensagem a sair sem
aprovação com o sistema degradado — e **não o encontrou**; o que ela confirma é o
outro lado, que é o custo registado acima.
