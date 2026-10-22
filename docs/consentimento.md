# Consentimento no 1.º contacto (KAM-022)

| Campo | Valor |
|---|---|
| Ticket | KAM-022 |
| Módulo | `packages/core-ts/src/consentimento/` |
| Revisão | `0015_consentimento` (descende da `0014`) |
| Depende de | KAM-008 (identidade), KAM-014 (CHR e conversas), KAM-015 (saída), KAM-159 (taxonomia de finalidades) |
| Bloqueia | KAM-048, KAM-070, KAM-109 |
| Fonte do desenho | [`tecnica/10_Onboarding_Governanca.md`](tecnica/10_Onboarding_Governanca.md) §7, [`tecnica/06_Dados_Eventos_Analytics.md`](tecnica/06_Dados_Eventos_Analytics.md) §7.3, [`tecnica/evidencia/E1_Meta_WhatsApp.md`](tecnica/evidencia/E1_Meta_WhatsApp.md) §4, `tecnica/evidencia/E3`, ADR-010 |

## 1. O que o módulo faz

É a **barreira anterior ao agente**. Uma mensagem de um contacto que não tenha
`consent_event` válido para a versão vigente do aviso não chega ao AGR: o que sai
é **uma** mensagem — o aviso de privacidade com três botões — e o *job* do
assistente não se monta.

Do que o contacto responde, tira quatro coisas: a **prova** (uma linha
*append-only* com o resumo do que ele viu e aceitou), a **passagem a uma pessoa**
quando ele a pede, a **revogação** de *marketing* quando ele escreve «PARAR», e
os **eventos** `consent.recorded` e `consent.withdrawn`.

## 2. As cinco decisões de desenho

**A decisão é a única porta, e é por isso que ela é um valor.** O `tratar`
devolve um `invocaAgr: boolean`, e quem monta o *job* é o encaminhador do
KAM-013/KAM-014 — este módulo nunca chama o AGR. A propriedade do critério 4
(«em 1.000 mensagens por 50 contactos, nenhum *job* é criado sem `consent_event`
válido anterior») só é demonstrável assim: com a autorização a deduzir-se da
acção em cada chamador, não havia um sítio onde a medir.

**O *append-only* é um privilégio e não uma política.** A `0015` dá a
`kamba_app` `SELECT` e `INSERT` na `consent_event` e **mais nada**, e a bateria
afirma o `42501` num `UPDATE` e num `DELETE`. Um teste do lado do código prova o
que o código faz hoje; este prova o que **nenhum** código pode fazer. Uma prova
de consentimento que se possa corrigir não é prova, e a revogação é uma linha
nova — que é o que o critério 6 pede.

**A idempotência sai da própria prova.** `evidence_hash = sha256(texto_mostrado ‖
contact_id ‖ wamid ‖ hora)`, e o `wamid` e a hora são **da Meta**: uma reentrega
do mesmo *webhook* produz o mesmo resumo e bate na
`UNIQUE (tenant_id, contact_id, purpose, evidence_hash)`. Com a **nossa** hora,
duas entregas do mesmo botão davam dois resumos e duas linhas — e o critério 2
diz o contrário. O separador é `\u0000` porque sem separador
`sha256("ab" ‖ "c")` e `sha256("a" ‖ "bc")` são o mesmo valor, e duas provas
diferentes com o mesmo resumo é exactamente o que uma prova não pode fazer.

**A `consent_actual` é a primeira vista do esquema, e leva
`security_invoker = true`.** Uma vista corre, por omissão, com os privilégios do
**dono**, e o dono está sujeito a RLS só por causa do `FORCE`; a opção põe-na a
correr como quem a consulta, que é o que a política pressupõe. O
`verificar_vistas` de `db/tests_isolamento/catalogo.py` exige-o a **qualquer**
vista, sem lista de excepções, e existe desde o KAM-004 — esta revisão foi a
primeira a dar-lhe algo para ver.

**E a ordem dela é de três critérios, porque dois não bastavam.** O
`DISTINCT ON (tenant_id, contact_id, purpose)` resolve «o último estado» por
`ORDER BY ocorrido_em DESC, registado_em DESC, id DESC`, e o do meio entrou por
um defeito: a primeira versão usava só `ocorrido_em DESC, id DESC` e afirmava —
na revisão **e** no dicionário — que um empate no instante dentro do trio era
impossível «pela unicidade da prova». **É falso.** A unicidade é sobre o
`evidence_hash`, e **a hora que a Meta manda tem resolução de segundos**: dois
cliques no mesmo segundo dão o mesmo instante com `wamid` diferentes, entram as
duas linhas, e a vista desempatava pelo `uuid` aleatório — determinística para os
mesmos dados, e **arbitrária** em relação à cronologia. O `registado_em` é a hora
em que **nós** escrevemos, com `clock_timestamp()` (e não `now()`, que é o início
da transacção e empatava também): é a única coluna do esquema que o usa, e o par
`ocorrido_em`/`registado_em` é o mesmo que o envelope de evento do `06` §6.1 já
tinha.

**A contagem de avisos não acrescentou DDL.** «Repete o aviso até 2 vezes e
depois encaminha a `humano`» precisa de saber quantos avisos já saíram, e não há
coluna para isso em sítio nenhum do esquema. Em vez de criar uma — em
`conversations`, que o KAM-018 teria de aprender a não mexer —, o aviso sai com
`idempotency_key = aviso:{conversation_id}:{n}` e a contagem é um `count(*)` com
prefixo: **a mesma chave que impede o aviso de sair duas vezes é a que diz
quantas vezes saiu.** Resolve-se pelo índice `(tenant_id, idempotency_key)` que a
`0010` já tem.

## 3. A matriz: seis entradas × três estados

| entrada | `ausente` | `desactualizado` | `valido` |
|---|---|---|---|
| botão `continuar` | `registar_e_seguir` | `registar_e_seguir` | `seguir` |
| botão `falar_com_a_loja` | `passar_a_humano` | `passar_a_humano` | `passar_a_humano` |
| botão `saber_mais` | `enviar_politica` | `enviar_politica` | `enviar_politica` |
| «PARAR» | `registar_revogacao` | `registar_revogacao` | `registar_revogacao` |
| texto livre | `enviar_aviso`¹ | `enviar_aviso`¹ | `seguir` |
| outro (áudio, imagem…) | `enviar_aviso`¹ | `enviar_aviso`¹ | `seguir` |

¹ depois de dois avisos nesta conversa, passa a `passar_a_humano`.

**Dezoito células escritas uma a uma**, e não três linhas derivadas por uma
regra: com o tipo `Record<Linha, Record<Estado, Accao>>`, uma célula em falta
deixa de compilar.

**Três linhas não dependem do estado, e isso é decisão.** «Falar com a loja»
vale sempre porque a Messaging Policy exige um caminho de escalonamento para uma
pessoa (`E1` §4, CONFIRMADO) e condicioná-lo ao consentimento era pedir
consentimento para falar com uma pessoa. «Saber mais» vale sempre porque é o
direito de informação. E o «PARAR» vale sempre porque o critério o diz: «em
qualquer ponto».

**Duas acções autorizam o AGR e só duas** — o `seguir` e o `registar_e_seguir` —
e nenhuma o faz a partir de um estado que não seja `valido` ou de um botão que
não seja o `continuar`. É isso que torna a propriedade do critério 4
demonstrável por uma função sozinha.

## 4. O «PARAR», e o que ele não apanha

Conta a palavra **sozinha**, em qualquer caixa, com ou sem acentos, com espaços e
pontuação: `parar`, `stop`, `sair`, `cancelar`. **Não** conta dentro de uma
frase — «não parar» e «pode parar de me mandar isso?» não disparam.

A escolha tem um custo de cada lado e está escrita no módulo: disparar numa frase
dava revogações que o cliente não pediu (ele estava a conversar), e não disparar
deixa passar um pedido escrito por extenso. A escolha é a conservadora para o
**registo** — uma revogação é um facto que fica —, e o que apanha o resto é o
caminho normal: a mensagem segue para o assistente, que tem «falar com humano»
em todas as conversas (§9.2). É o tipo de decisão que um parecer pode mandar
mudar, e o critério vizinho já diz «comportamento a confirmar por parecer».

## 5. As métricas

| Métrica | Tipo | Etiqueta | Porque assim |
|---|---|---|---|
| `consent_notice_sent_total` | contador | — | Do DoD. Conta os que **saíram**: um aviso que não saiu é uma loja que não respondeu |
| `consent_optout_total` | contador | — | Do DoD |
| `consent_accepted_ratio` | *gauge* | — | Do DoD. **Derivado** de dois contadores na leitura, e não uma série guardada que pudesse divergir deles. Vale `-1` antes do primeiro aviso: «não sei» não é «ninguém aceitou» |
| `consent_accepted_total` | contador | — | O numerador do rácio, exposto para que ele se possa verificar |
| `consent_blocked_total` | contador | `accao` (6 valores) | **Não está no DoD.** Entra porque *barrar sem contar é barrar em silêncio*: sem ela, um painel não distingue «os clientes estão todos a consentir» de «não há texto vigente e o gate está a barrar tudo» — e o segundo é uma loja muda |

Nenhuma leva `tenant_id`, e a decisão não é nova: é a da emenda 1.21, repetida na
1.24 e na 1.27. As etiquetas têm de casar `^[a-z][a-z0-9_]{1,62}$` e um UUID com
hífenes **levanta** (`OBS-I` de
[`seguranca/ameacas_stride.md`](seguranca/ameacas_stride.md)).

## 6. A falha fechada, e porque a loja fica muda

A `consent_texts` nasce **vazia**: o texto é jurídico e está «a confirmar por
parecer» (KAM-104). Sem versão vigente, o gate não envia nada e não autoriza o
AGR.

O efeito prático é que **a loja fica muda até o texto existir**, e é o lado
certo. A alternativa era o assistente tratar mensagens de clientes sem lhes ter
mostrado o aviso, que é o que o ADR-010 proíbe e o que o `E3` req. 15 obriga a
fazer. Um defeito que faz a loja ficar calada vê-se no primeiro dia; um que trata
dados sem base legal vê-se quando chega a multa (`E3`: USD 505 mil, 2026-06-24).
A `consent_blocked_total{accao}` existe para que a diferença seja visível num
painel.

## 7. O que fica de fora, e porquê

| O que | Onde está |
|---|---|
| **A base legal de cada finalidade** | **Não fixada, e este ticket não a fixa.** Das dez, só a `marketing` tem fonte directa e CONFIRMADA no `E3` (Art. 19.º da Lei 22/11), e **seis não têm nada**. O que se entrega é a prova de que **o aviso foi apresentado** e o registo do que o titular respondeu; se a base é contrato, consentimento ou interesse legítimo é o KAM-104 |
| **O texto em PT-AO** | A tabela nasce vazia, de propósito. Uma migração que o escrevesse punha no esquema uma afirmação legal que ninguém reviu |
| **`conversations.mode`** | O `UPDATE` que a `0009` concede a `kamba_app` é por coluna e **não inclui o `mode`**, por decisão do KAM-014: ele é de **KAM-018**. O gate diz que a conversa deve passar (`passaAHumano`, `pausaAConversa`) e chama a porta `MudarModo` quando ela está ligada. **Está ligada desde o KAM-018**, que pediu o privilégio que a `0009` lhe reservou: a revisão `0016` concede-o, e o `portaDoConsentGate` do `MaquinaDeModos` traduz o modo que esta porta pede no gatilho da tabela de transições — `humano` por `handoff_pedido`, `pausada` por `opt_out`. Ver [`modos-conversa.md`](modos-conversa.md) §2 |
| **A recusa de *marketing* no Outbound** | «*marketing* sem `accepted = true` específico é recusado pelo Outbound (KAM-015)»: o `decidir` do KAM-015 **já** recusa `marketing` no Piloto (`MARKETING_NOT_ALLOWED`), antes de qualquer consentimento. A verificação por `consent_actual` é para quando houver *marketing*, e aqui ela não tem caminho porque o envio não tem |
| **O «aviso curto» e o «texto completo»** | Os critérios 1 e 3 pressupõem **dois** textos e o critério 7 especifica a tabela com **um**. As duas metades do critério 3 — «envia o texto completo» e «repete o aviso» — cumprem-se numa mensagem: o texto vai com os três botões, que é ao mesmo tempo o texto e o aviso repetido, e é o que mantém verdadeiro o «exactamente 1 mensagem de saída» do critério 1. **Não se acrescentou coluna**: o texto que vai ser revisto juridicamente é um, e dividi-lo em dois é decisão de quem o escreve (KAM-104). Dívida **78** |
| **As outras sete finalidades** | Existem no domínio e não têm caminho aqui: `analytics_agregado`, `sugestoes_patrocinadas` e as três `partilha_*` exigem consentimento específico no momento do uso (`06` §7.3), e quem o pede é quem usa |
| **Os direitos do titular** e o **ToS/DPA da PME** | KAM-070 e KAM-090 |
| **A ligação ao caminho de canal** | **O `ConsentGate` não está construído em `services/worker-canal/src/entrada.ts`**, e não é um passo esquecido: ligá-lo precisa de duas coisas que aquele processo não tem. A primeira é um caminho de **envio** — o `Saida` do KAM-015 não está ali (o *worker* tem três ligações à base e uma fila, e nenhum cliente da Meta), e sem ele o gate barrava o AGR **e não conseguia mandar o aviso**: uma loja muda sem sequer avisar porquê. A segunda é uma **versão do texto publicada** (KAM-104). A ordem de activação é: parecer → publicar a versão → construir o `Saida` no *worker* → ligar o gate |
| **Contactos da sincronização de histórico** (critério 9) | O KAM-017 não existe ainda. O gate trata-os como qualquer outro contacto sem consentimento: o aviso sai na primeira mensagem **depois** do onboarding, que é o que o critério pede — e sai **uma** vez, pela chave de idempotência |

As divergências entre o bloco do ticket e o que o esquema tem estão em
[`dividas-documentais.md`](dividas-documentais.md), linhas 75 a 78.

## 8. Como se prova

```bash
# unidade (gate 4): a matriz, o PARAR, a prova, e a propriedade do criterio 4
pnpm --filter @kamba/core-ts run test

# contra um PostgreSQL real (gate 8): a unicidade da prova sob concorrencia, a
# vista a respeitar a RLS de quem a consulta, a contagem pelo prefixo da chave,
# e o 42501 de um UPDATE que nao existe
make ci-8

# a prova por mutacao das trinta e cinco
python db/mutacoes.py <python> "consentimento"
```

A divisão entre as duas baterias é a que o `outbound.md`, o `metering.md` e o
`qualidade.md` já usam, e a razão é a mesma: **um duplo prova que o nosso código
chama o que pretendíamos chamar, não que o PostgreSQL faz o que pensamos.** O
`ON CONFLICT`, o `security_invoker`, o `LIKE` com prefixo sobre um índice e o
`42501` de um privilégio que não existe não existem numa base falsa.

**O terceiro defeito foi o CI a apanhar uma afirmação que eu tinha escrito
duas vezes.** O ensaio «duas provas do mesmo trio: o estado é o da última»
passava na minha máquina e **falhava no CI**, com os mesmos dados: as duas provas
partilham o `ocorrido_em` (o relógio do ensaio é fixo, e na realidade a hora da
Meta tem resolução de segundos) e a vista escolhia pelo `uuid`. A correcção é o
`registado_em`, acima; e a asserção que o prende verifica primeiro que as duas
linhas **empatam** no instante — senão o teste provaria o relógio e não o
desempate.

**E a revisão adversarial do próprio ticket encontrou dois defeitos que
nenhuma máquina podia dizer.** O primeiro é de custo: o nome da loja lia-se em
**todas** as mensagens, incluindo as que seguem sem aviso — uma consulta por cada
mensagem de cada conversa da plataforma, para um valor que o caminho comum
(`seguir`) não usa. Passou a ler-se só quando alguma coisa o vai usar. O segundo é
de comportamento, e era pior do que qualquer das leituras possíveis do critério:
o «Saber mais» enviava o texto **sem botões** e deixava o cliente sem acção
nenhuma. Passou a levar os três — ver a dívida 78.

**Dois defeitos deste ticket foram apanhados por máquina e nenhum por leitura**,
e os dois são do mesmo tipo — a bateria a afirmar sobre o **ensaio** em vez de
sobre o esquema. O primeiro: a primeira versão da bateria de esquema inventou um
`excepcao.sqlstate` que o `pg8000` não tem (o código vem no campo `C` do
dicionário da mensagem do servidor, e `db/tests/base.py` já tinha o ajudante e os
nomes) — **dezasseis erros à primeira volta**. O segundo: a metade positiva do
*append-only* contava linhas que a sessão da aplicação **não podia ver**, porque
a ligação que o `ComBase` dá nunca confirma; passou a afirmar o privilégio, que é
o que o critério pede, e quem exercita a escrita de verdade é o ensaio em Node
contra dados confirmados.

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Primeira versão, KAM-022. A revisão `0015` (duas tabelas e **a primeira vista do esquema**), o `ConsentGate` com a matriz de dezoito células, o «PARAR», o `evidence_hash` reprodutível e as cinco métricas. A `consent_texts` nasce vazia e o gate falha fechada: o texto está a confirmar por parecer (KAM-104). | Equipa KAMBÁ |
| 1.1 | Outubro 2026 | **KAM-018: a porta `MudarModo` está ligada.** A §7 dizia que ela ficava por ligar porque «este módulo não tem o privilégio»; a revisão `0016` concede-o a `kamba_app` e o `portaDoConsentGate` do `MaquinaDeModos` liga-a, traduzindo o modo que a porta pede no gatilho da tabela de transições. Nada do `ConsentGate` muda: ele já chamava a porta quando ela existisse, e o que faltava era quem a implementasse. | Equipa KAMBÁ |
