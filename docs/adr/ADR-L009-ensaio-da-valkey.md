# ADR-L009 — O ensaio da Valkey: o que se mediu, e porque a **D12 continua aberta**

| Campo | Valor |
|---|---|
| Estado | **Aceite** — como registo do ensaio. **Não ratifica a ADR-P09 e não fecha a D12** |
| Ticket | KAM-076 — Compose de produção do conjunto reduzido e redes isoladas (critério 6) |
| Data | 2026-11-03 |
| Decisores | quem executa o KAM-076. **A D12 é acto do fundador** |
| Relacionado | ADR-P09 e D12 (`../tecnica/09_Topologia_Operacao_Escala.md` §20), ADR-009, [ADR-L004](ADR-L004-fila-e-tranca-do-agr.md) |

---

## 1. Contexto

O critério 6 do KAM-076 diz, por escrito:

> Teste de compatibilidade Valkey em *staging* (BullMQ do *outbox*, Sidekiq do
> Chatwoot, eventos/cache do Medusa) passa; se falhar, regressa-se a Redis e
> abre-se D12 sobre a licença. Resultado registado em ADR-P09.

A **ADR-P09** («Valkey no lugar de Redis, condicionado a teste em *staging*») é
uma **proposta** do `../tecnica/09` §20, não um ADR canónico: vive numa tabela
de propostas e ratificá-la é acto do fundador. A **D12** é a decisão aberta
sobre a licença do Redis — o Redis ≥ 7.4 passou a RSAL/SSPL, e o
`../../ci/licenses.yaml` já trava **os dois** lados em
`pendentes_de_decisao`, o Redis *e* a Valkey, precisamente para que aprovar um
deles pela via da licença não feche a decisão pela porta de trás.

Este ADR local existe para registar **o que o ensaio mediu**, com a mesma
disciplina do resto: nenhuma afirmação sem a medição que a sustenta.

---

## 2. Decisão

**O ensaio está incompleto, e por isso nada muda.** A Valkey 9.1.2 continua a
omissão do compose; a D12 continua **aberta**, como já estava; a ADR-P09
continua **proposta**.

> **ACRESCENTO DE 2026-11-03, DEPOIS DE O ENSAIO SER ENTREGUE: o fundador
> deferiu.** A sessão que orquestra o trabalho relatou a decisão — **fica a
> *flag*, a omissão em Valkey mantém-se, e a D12 não fecha agora**.
>
> **A proveniência fica dita porque importa:** a decisão chegou-me **relatada
> por essa sessão** e não lida por mim no registo de decisões da Carta §4.2. Não
> se escreveu nada nesse registo a partir daqui — registar uma decisão do
> fundador no canon não é acto de quem executa o ticket —, e o que este ADR
> local registra é o **ensaio**, que é o que o critério 6 lhe pede.
>
> **O que a deferição muda:** nada no código e nada nos dois ficheiros de
> licença, onde o Redis e a Valkey seguem os dois `pendentes_de_decisao`
> (verificado, e de propósito não alterado). O que muda é o estado da caixa do
> critério 6: deixa de ser uma pergunta em aberto e passa a ser uma caixa
> **devolvida com o decisor nomeado**.
>
> **E a razão da deferição vale ser escrita, porque explica porque é que uma
> decisão de licença não bloqueou um PR.** O `${KAMBA_QUEUE_IMAGE}`, o
> `${KAMBA_QUEUE_CLI}` e o nome neutro do serviço `queue` tornam a troca para
> Redis **um valor de ambiente e não uma reescrita**; e não há produção para
> afectar enquanto a **D1** não decidir o alojamento. O custo de reverter a
> omissão está medido em **uma variável**. **Isto não é uma dispensa** — é a
> decisão adiada com o custo de a mudar conhecido, que é o contrário de a adiar
> sem saber o que custa.

Não se marca o critério 6 como satisfeito. E também **não** se executa a segunda
metade dele («se falhar, regressa-se a Redis e abre-se D12»): o ensaio não
*falhou* — ficou **incompleto**, e a diferença entre as duas coisas é exactamente
o que este ficheiro existe para não apagar. Regressar a Redis com base num
ensaio incompleto trocaria uma licença BSD-3 por uma RSAL/SSPL sem medição que o
justificasse.

A **forma** da decisão continua protegida, e isso é o que o ticket entrega de
facto: o serviço chama-se `queue` e não `redis` nem `valkey`, a imagem é
`${KAMBA_QUEUE_IMAGE:-...}` e o cliente é `${KAMBA_QUEUE_CLI:-valkey-cli}`.
Fechar a D12 em qualquer dos sentidos é mudar duas variáveis de ambiente, não
editar código — e nenhum módulo do repositório sabe qual das duas corre.

---

## 3. O que se mediu, consumidor a consumidor

| Consumidor | Estado | O que o sustenta |
|---|---|---|
| **BullMQ do *outbox*** | **CONFIRMADO, com uma falha a caracterizar** | A suite `tests_eventos` do gate 8 corre o publicador **contra uma Valkey 9.1.2 real**, fixada por *digest* (`db/fila_do_gate.py`), e não contra uma fila em memória — foi escrita assim no KAM-005 porque as garantias do BullMQ estão NÃO VERIFICADO (`E4` §2.10). Medido a 2026-11-03: `python db/gate_bd.py --suite tests_eventos` → **20 testes, 19 verdes, 1 vermelho**. Os 19 cobrem publicação, recuo, republicação depois de `kill -9`, eleição de líder, DLQ e o esquema fechado do envelope. O vermelho é `test_mil_eventos_com_a_fila_parada_recuperam_sem_perder_nenhum`, com `AssertionError: proxima_tentativa_at nao foi adiada` — ver §4 |
| **Sidekiq do Chatwoot** | **INDÍCIO** | O `infra/compose/docker-compose.chatwoot.yml` (KAM-019) já aponta o Chatwoot **e** o `chatwoot-worker` (Sidekiq) para uma **Valkey**, pelo mesmo *digest*, e o spike do KAM-019 correu essa pilha com êxito (`../evidencia/KAM-019-bot-open.md`: `/api` respondeu 200, conta, *agent bot*, *inbox* e conversa criados). Isso mostra que o **Rails** fala com a Valkey. **Não mostra que o Sidekiq processou um trabalho**: ninguém o afirmou nem o mediu, e a evidência do KAM-019 não fala de Sidekiq. Elevar a CONFIRMADO exige uma medição que §5 nomeia |
| **Eventos/cache do Medusa** | **NÃO APLICÁVEL** | E não é uma evasiva: o Medusa do Piloto **não usa Redis nem Valkey**. O `spikes/medusa-d3/contentor.py` di-lo e explica porquê — «o Medusa aceita os módulos de event bus e de cache locais (em memória) e o spike não mede o bus: o bus canónico é o **EVT** (ADR-009), não o do Medusa». Não há nada a ensaiar aqui enquanto essa escolha se mantiver. Se algum dia o Medusa passar a usar `@medusajs/event-bus-redis` ou `@medusajs/cache-redis` — ambos estão no *lockfile* do spike, logo disponíveis —, este ensaio ganha um terceiro consumidor e este ADR fica desactualizado |

---

## 4. A falha, e o que ela é e não é

`test_mil_eventos_com_a_fila_parada_recuperam_sem_perder_nenhum` falha em
`db/tests_eventos/test_publicador.py:536`, na asserção de que
`proxima_tentativa_at` foi adiada depois de a fila parar.

O que se sabe, e o que não se sabe:

* **Está fora do diff deste ticket.** O KAM-076 não toca em `db/` — por
  fronteira declarada, porque outra sessão implementa o KAM-044 ali.
* A primeira execução correu **enquanto esta máquina levantava contentores para
  os ensaios de rede**, e o teste para e volta a arrancar o contentor da fila e
  mede uma janela de recuo: é sensível a contenção.
* **Não se estabeleceu se é pré-existente, e a primeira versão deste ficheiro
  dizia que sim — erradamente.** A tentativa de controlo foi correr a mesma
  suite numa árvore pristina de `publico/main` (`git archive`). Nessa árvore
  falham **sete ou mais** testes e não um, o que a torna um **controlo
  inválido**: não reproduz o cenário, falha por outra razão (a árvore extraída
  não tem o `node_modules` nem o ambiente que a suite monta), e uma comparação
  entre «1 vermelho» e «7 vermelhos por outro motivo» não distingue nada.
  Apagar o controlo e ficar com a conclusão era o defeito que estes documentos
  existem para evitar, pelo que fica escrito que a conclusão **caiu**.
* **O que se sabe com certeza:** o diff deste ramo tem 29 ficheiros e **nenhum**
  em `db/` nem em `services/com/` — verificado, não suposto. A suite não lê
  nenhum ficheiro que este ramo toque, pelo que o diff não a pode ter quebrado.
  Isto é um argumento de construção, mais fraco do que uma medição, e está
  marcado como tal.
* Estado honesto: **NÃO VERIFICADO** se a falha é pré-existente em
  `publico/main`. O que falta para a apurar está em `../evidencia/KAM-076.md`
  §4.2.

Não se conta esta falha como evidência a favor nem contra a Valkey: um teste de
recuo que falha na asserção do adiamento não diz nada sobre o protocolo da fila.
Mas **é um achado**, e vai no PR como achado, com o estado que tem — não se
corrige aqui, porque o KAM-076 não toca em `db/` por fronteira declarada com a
sessão que implementa o KAM-044.

---

## 5. O que falta para o critério 6 ficar satisfeito

| # | Medição | Porque não está aqui |
|---|---|---|
| 1 | **Sidekiq processa um trabalho contra a Valkey**, e não só arranca ao lado dela. A medição precisa: levantar o `docker-compose.chatwoot.yml`, pôr o Sidekiq a registar-se — ele inscreve-se na fila sob a chave `processes` —, e confirmar que a inscrição aparece e que um trabalho sai da fila | É uma medição de minutos (o primeiro arranque corre as migrações do Rails) e não estava no caminho dos outros sete critérios |
| 2 | **Em *staging***, e não numa máquina de desenvolvimento. O critério diz «em *staging*», e não há *staging*: depende da **D1**, que está em branco (KAM-105) | Acto do fundador |
| 3 | A **licença da Valkey lida da fonte**. O `../../ci/supply-chain/licencas.yaml` tem `estado_verificacao: INDÍCIO` com a razão escrita: «o E4 não tem linha para o Valkey e ninguém leu o ficheiro de licença» | Uma linha a mais no E4, não neste ticket |

---

## 6. Consequências

* A D12 continua aberta, e com ela a Valkey e o Redis continuam os dois
  `pendentes_de_decisao` no `../../ci/licenses.yaml`. O *gate* 11 **falha** para
  qualquer um dos dois se alguém os declarar como componente aprovado — que é o
  comportamento certo enquanto a decisão não existir.
* O compose de produção corre com a Valkey por omissão. Isto **não** é a
  decisão: é a omissão que o KAM-001 já tinha escolhido, mantida por não haver
  medição que a contrarie.
* Quem fechar a D12 fecha-a nos dois ficheiros (`ci/licenses.yaml` e
  `ci/supply-chain/licencas.yaml`) e no registo de decisões da Carta §4.2, e
  este ADR passa a apontar para ela.

---

## 7. Alternativas consideradas

| Alternativa | Porque não |
|---|---|
| Marcar o critério 6 satisfeito com o que há | Dois dos três consumidores não estão medidos. Promover um INDÍCIO a facto é defeito, e o `../../specs/01` §4 chama-lhe isso |
| Declarar o ensaio falhado e regressar a Redis | O ensaio não falhou — ficou incompleto. E regressar trocaria BSD-3 por RSAL/SSPL sem medição que o justifique |
| Fechar a D12 aqui | Decisão do fundador. Este ticket entrega a medição e a recomendação, não a decisão |
| Deixar o resultado só na evidência, sem ADR | O critério 6 pede o resultado «registado em ADR-P09», e a ADR-P09 é uma proposta num documento de referência. O espaço de ADRs locais (`README.md` deste directório) é onde um resultado destes se registra sem fingir que é canon |
