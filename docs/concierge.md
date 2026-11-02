# Modo concierge: a IA rascunha e o humano aprova

| Campo | Valor |
|---|---|
| Ticket | KAM-114 |
| Módulo | `services/agr/src/kamba_agr/concierge/` |
| Revisão | `0024_draft_decisions` (descende da `0023`) |
| Depende de | KAM-018 (os modos e o `PreSendGuard`), KAM-031 (o grafo do Vendedor), KAM-034 (o padrão dos dois nós), KAM-032 (o validador de citação), KAM-009 (`check_entitlement`) |
| Bloqueia | KAM-109 (o Piloto concierge, que mede H1, H6, H7 e H9) |
| Fonte do desenho | [`tecnica/02`](tecnica/02_Agent_Runtime_Verticais.md) §11 e §16, [`tecnica/01`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §10.2, §10.3 e §11.4, [`tecnica/10`](tecnica/10_Onboarding_Governanca.md) §11.2 e §11.3, [`exploracao/14`](exploracao/14-tese-minima-e-plano-de-validacao.md) §3A, ADR-002, ADR-007, ADR-010, ADR-015, ADR-018 |
| Canon | `../specs/02_Dicionario_de_Dados_Canonico.md` §3.34 (emenda 1.44, *proposta*) |
| Entregue | A política, os dois nós, o CAS, a varredura, a substituição e a exportação. O que falta tem credor nomeado no §7 |

## 1. O que o módulo faz

Com a política `concierge` activa num *tenant*, o assistente **não fala sozinho**:
escreve um rascunho, mostra-o a um operador humano no Chatwoot, e só envia a
mensagem depois de alguém a aprovar ou editar. Sem decisão humana registada,
**nada sai**.

É o que o Piloto precisa para medir H1, H6, H7 e H9 com PMEs reais antes de o bot
responder por conta própria (KAM-109).

## 2. O que ele **não** é

**Não é um quinto modo de conversa.** Os quatro modos — `bot`, `dono`, `humano`,
`pausada` — ficam como estão, e o KAM-018 continua a recusar transições fora da
tabela de [`tecnica/01`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §10.2. O
concierge é uma **política por *tenant*** aplicada à conversa que está em modo
`bot`: o nó de envio é substituído por um pedido de aprovação. Nada neste módulo
toca na `platform.conversations` nem no `SQL_MUDAR_MODO`.

Também não é, por decisão do próprio ticket: aprovação automática por limiar de
risco (Fase 2), interface própria do operador (usa-se o Chatwoot), e **nenhum**
treino ou *fine-tuning* com as decisões — o ADR-018 proíbe-o.

## 3. O caminho, nó a nó

```text
guard_out --(32)--> send
unknown_reply / ask_repeat / safe_reply --(34)--> send
handoff_prepare --(37, degradado)--> send

                      send
                       |
        .--------------+--------------.
        | (35) enviado                | (40) aprovar
        v                             v
       END                      draft_prepare
                                      | (41)
                                      v
                                 draft_wait   <-- interrupt()
                                      |
                        .-------------+-------------.
                        | (42) enviar               | (43) end
                        v                           v
                       send                        END
```

**A intercepção é no `send` e não à entrada de cada caminho**, e isso é a decisão
de desenho que mais importa aqui: são **cinco** as arestas que chegam ao `send`, e
o critério 1 conta «0 mensagens ao cliente sem decisão» — uma resposta estática é
uma mensagem ao cliente tanto como uma composta. Interceptar num sítio cobre as
cinco; interceptar à entrada obrigava a cinco condicionais, e a primeira
esquecida era uma mensagem a sair sem aprovação.

**O ciclo `send → draft_prepare → draft_wait → send` é limitado pelo
`interrupt()`**, não por um contador. O `draft_wait` **para** o grafo, e só uma
decisão humana ou a varredura o retomam: ele não pode girar sozinho, o que é um
limite mais forte do que um tecto porque não depende de alguém manter o tecto
certo. A segunda passagem pelo `send` traz a decisão no estado e sai pela aresta
`enviado`.

| Nó | O que faz | Proibido |
|---|---|---|
| `draft_prepare` | grava a linha em `platform.draft_decisions` e publica o rascunho no HND. **Idempotente por `draft_id`** | enviar qualquer coisa ao cliente |
| `draft_wait` | **só** o `interrupt()`, na primeira instrução | ter efeitos antes dele, `try/except` em volta, ou estar num ciclo `while` |

A mesma política AST do `handoff_wait` (KAM-034) corre sobre o `draft_wait`, **sem
regra nova**: o `verificar` do `politica_ast.py` recebe o nome do nó.

## 4. A barreira, e as cinco maneiras de a furar que estão fechadas

A regra é uma: **sem decisão `aprovado` ou `editado` registada, não sai
mensagem.** O rascunho expira às 24 h. As cinco maneiras de a furar, e onde cada
uma está fechada:

| Como se furava | Onde está fechado |
|---|---|
| O HND em baixo → mandar uma mensagem de degradação | Não se manda. Uma mensagem de degradação **é** uma mensagem; fica a linha `pendente`, a contagem `agr_draft_indisponivel_total` e o prazo das 24 h. O cliente não recebe nada, e isso diz-se — ver o §6 |
| A varredura escrever `aprovado` | Os domínios das duas vias são **disjuntos**: três valores para o operador, dois para o sistema, e o `decidir_pelo_sistema` levanta `DecisaoDoSistemaInvalidaError` |
| A política ilegível virar «desligada» | Não vira. A excepção **sobe**, o turno falha e nada sai. Apanhá-la para devolver `False` era *fail-open* com cara de robustez |
| A decisão de um turno valer no turno seguinte | O `estado_inicial` repõe o `concierge` a `None` em cada turno. Sem isso, o `send` do 2.º turno lia a aprovação do 1.º — a barreira furada no caminho mais comum que há |
| Um corpo de retoma que não se entende | O `r_draft` devolve `end` por omissão: a omissão segura é **não enviar** |

E há uma sexta, que não é furar a barreira mas matar a conversa: a política activa
com o `ServicoDeRascunho` por ligar. Aí **levanta** (`ConciergeSemServicoError`) em
vez de interromper — sem linha gravada, a varredura nunca encontra o rascunho e o
CAS nunca o casa, pelo que o `interrupt` ficava pendente **para sempre** e a
invariante do §11 fechava a conversa a mensagens novas. Levantar faz o turno
falhar e a mensagem fica na fila.

## 5. A política, e porque é que ela é uma linha de `entitlements`

```sql
INSERT INTO platform.entitlements (tenant_id, modulo, ativo)
VALUES ('<tenant>', 'concierge', true);
```

Não há migração para a política: a coluna `modulo` tem `CHECK` de **forma** e não
de domínio desde a `0001`, e o dicionário §3.7 escreve que «um módulo novo entra
por configuração e não por migração» (ADR-012).

**As outras três superfícies foram medidas e nenhuma serve.** O `registry/*.yaml`
lê-se uma vez no arranque e não se recarrega — não há *watcher*, não há TTL —,
pelo que uma política em YAML falhava o critério 8 («desactivar repõe o envio
automático **sem reiniciar o AGR**») por construção. O `entitlements.limites` tem
`additionalProperties: false` no `registry/entitlement_keys.schema.json` e as suas
dez chaves são todas `bigint_nao_negativo`, pelo que um `concierge: true` ali é
**recusado na escrita**. E uma tabela de políticas não existe, e era uma
superfície a mais para o que uma linha já diz.

**Lê-se em cada turno, sem *cache*.** O `check_entitlement` aceita uma
`CacheDeEntitlements` com TTL de 60 s e **não se passa**: o que se compra é que
desactivar tem efeito **no turno seguinte** em vez de «até 60 s depois», o que
torna o critério 8 uma propriedade e não um prazo. O que se paga é uma leitura por
chave primária por turno. Se o Piloto medir isto como caminho quente, a *cache*
existe e o limite está escrito.

**Desligar:**

```sql
UPDATE platform.entitlements SET ativo = false
 WHERE tenant_id = '<tenant>' AND modulo = 'concierge';
```

O envio automático volta no turno seguinte. Os rascunhos já `pendente` passam a
`substituido` quando a varredura correr; até lá o prazo das 24 h fecha-os como
`expirado`. **Nenhum deles chega a ser enviado**, que é a barreira que importa.

## 6. Privacidade

`platform.draft_decisions` guarda **hashes, identificadores, números e um
booleano**. Não tem coluna de texto livre, e isso é o produto e não arrumação: o
texto do rascunho vive só no checkpointer (`lg`, com a retenção de conversa de
[`tecnica/08`](tecnica/08_Seguranca_Conformidade.md) §7.1) e no HND.

A medida da edição calcula-se no `concierge/servico.py`, que lê o texto original
do *checkpoint* com `aget_state`: o texto **entra** ali e **não sai** — para a
tabela atravessa um `numeric(4, 3)`.

Das cinco colunas `text`, nenhuma é livre: `draft_id` tem forma hexadecimal,
`graph_version` tem forma SemVer, `thread_id` e `turn_id` exigem não-vazio, e
`decisao` e `motivo` são domínios fechados. O `graph_version` **ganhou** a sua
forma na revisão adversarial deste ticket, e a razão é o critério 7: ele é a única
destas colunas que **sai** na exportação, e sem forma era um campo livre a
atravessar para fora.

**E «não há coluna de texto» não é prova de «não há texto»** — é a lição do
KAM-026, cujo varrimento dava zero por procurar texto num campo `msgpack`. A prova
é por varrimento **dos dados** com canários, em
`../db/tests_agr/test_draft_decisions.py`.

### O *golden*, e o que a Meta proíbe

Os Termos da Meta §4.7 proíbem usar dados da plataforma para criar, desenvolver,
treinar ou melhorar sistemas de ML/IA
([`tecnica/evidencia/E1`](tecnica/evidencia/E1_Meta_WhatsApp.md) §4, **NÃO
VERIFICADO** na íntegra; ADR-018), e o [`tecnica/10`](tecnica/10_Onboarding_Governanca.md)
§11.3 tira a conclusão: uma conversa real só entra no *golden* como
`real_consentido`, com **registo de consentimento** (as três origens do KAM-040,
decisão do fundador a 2026-10-30; [`adr/ADR-L006`](adr/ADR-L006-origem-do-golden-set.md)).
**Desta exportação não sai conversa nenhuma:** o que sai são reescritas
sintéticas, nunca cópias.

```bash
python db/golden_candidates.py esquema      # o teste de esquema do critério 7
python db/golden_candidates.py exportar     # os candidatos, em JSON
```

Daqui saem **cinco** campos de cada rascunho `editado` ou `rejeitado` — a decisão,
o motivo, o sinal do número livre, a versão do grafo e a razão de edição
arredondada a uma casa — e `origem=sintetico` em cada registo. Nenhum
identificador, nenhum instante, nenhum texto. O que sai é o **rótulo**; quem
escreve o caso reescreve-o à mão, com dados inventados, e o caso entra em
**KAM-040**.

O arredondamento a uma casa é minimização e não estética: três casas (a escala da
coluna) sobre um universo pequeno de rascunhos é quase um identificador — duas
edições com `0,418` são provavelmente a mesma conversa vista duas vezes.

## 7. O que não está entregue, com credor

| O que falta | Credor |
|---|---|
| **O *eval-gate* («Gate 13 verde com a política desligada e ligada»).** O gate 13 **não existe**: não há alvo `ci-13` no `Makefile` nem *job* no `.github/workflows/ci.yaml`, e mediu-se antes de se escrever código | **KAM-040**, aberto e bloqueado pelo KAM-035 e pelo KAM-033 |
| **O custo por rascunho aprovado — decidido, e não entregue.** A `dat.llm_call_log` não tem `turn_id` (tem `trace_id`, que é outro conceito) e o `kamba_app` não tem `SELECT` nela, por decisão deliberada do KAM-030. Das três saídas do dicionário §3.34 — uma delas retirava aquela barreira de privilégio —, **aceitou-se a vista sem coluna de custo**. O critério 6 fica `parcial`: o custo não é entregue | **KAM-109** (o H6), se o custo fizer falta; o preço do modelo é do **KAM-040** |
| **Bloquear** uma edição com número livre, em vez de a sinalizar | **Responsável de Produto** (o critério 4 devolve-o por escrito) |
| **O texto pré-aprovado** para quando o HND está em baixo, se alguém decidir que o cliente não pode ficar sem resposta | **Responsável de Produto** |
| **O `postDraft` do lado do HND** (o cliente HTTP do Chatwoot). Até lá a porta por omissão levanta `RascunhoIndisponivel`, que é a linha que o [`tecnica/01`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §11.5 escreve para «Chatwoot indisponível» | **KAM-019** |
| **O agendador da varredura.** Entrega-se o corpo (`Varredura.varrer`) e prova-se com relógio simulado; quem a chama a horas é o *scheduler* do EVT | **KAM-071** |
| **A ligação das portas ao grafo.** O AGR não constrói `Dependencias` nesta fase — o `grafos` é o `sem_grafos` e o `/internal/turn` responde 503. Quem ligar o AgentRegistry passa `concierge=` e `rascunho=` ao `build_graph`; sem elas a `Dependencias.concierge` fica `SemPolitica()` e o concierge nunca liga | **KAM-027** |
| **A mensagem nova do cliente com um rascunho pendente**, que abre um segundo rascunho em vez de substituir o primeiro. Não sai mensagem nenhuma e o prazo fecha o órfão; fechá-lo na hora pedia que a invariante do §11 soubesse de rascunhos pendentes, e ela lê `conversations.mode` e `handoffs.status` | **KAM-025** e **KAM-018** |
| **A calibração dos valores *proposta***: os seis motivos, a medida da distância, o alerta dos 10 minutos e o «≤ 5 s» do HND | **KAM-109** |

## 8. Como se corre, nesta máquina

Não há `make`, `node` nem `pnpm` no `PATH`; há Docker, Python e um `.venv`.

```bash
.venv/Scripts/python.exe -m unittest discover -s services/agr/tests -t services/agr/tests
.venv/Scripts/python.exe db/gate_bd.py --suite tests_agr
.venv/Scripts/python.exe db/gate_bd.py --suite tests_isolamento
.venv/Scripts/python.exe db/golden_candidates.py esquema
```

**A bateria do concierge corre em `unittest.TestCase` com `asyncio.run`, e não em
`IsolatedAsyncioTestCase`** — a razão é medida: aquela classe custa **47×** mais
neste perfil (100 turnos do grafo levam 27,8 s nela contra 0,59 s com
`asyncio.run`), porque cada invocação do LangGraph cria dezenas de tarefas e o
isolamento paga por cada uma. Com ela, os 1.000 turnos do critério 1 levavam **26
minutos** e o `make test-py` triplicava; assim levam segundos.

## 9. Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial. O modo concierge do KAM-114: a política por *tenant*, os nós `draft_prepare` e `draft_wait`, a `platform.draft_decisions` (revisão `0024`), o CAS de `/internal/draft-decision`, a varredura dos prazos, a substituição por *echo* do dono ou handoff, e a exportação `golden-candidates`. | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | KAM-169: a secção «O *golden*, e o que a Meta proíbe» atribuía ao `tecnica/10` §11.3 a conclusão «o *golden* leva reescritas sintéticas, nunca cópias», que é a **oposta** à que esse §11.3 passou a tirar — uma conversa real entra como `real_consentido` com registo de consentimento, pelas três origens do KAM-040 (decisão do fundador a 2026-10-30, `adr/ADR-L006-origem-do-golden-set.md`). A frase sobre **esta exportação** mantém-se e ganha o sujeito explícito: dela não sai conversa nenhuma, saem reescritas sintéticas. Achado da revisão adversarial do KAM-169, que mostrou que esta linha fala do **conjunto** e não da exportação, e que o ADR-L006 a tinha classificado entre as que «não são contradição». | Equipa KAMBÁ |
