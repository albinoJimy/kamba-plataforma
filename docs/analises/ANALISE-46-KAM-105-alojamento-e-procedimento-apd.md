# ANÁLISE 46 — KAM-105: alojamento D1 e procedimento APD

| Campo | Valor |
|---|---|
| Ticket | KAM-105 (EPIC-10 — Spikes, Validação e Gates) |
| Artefactos revistos | `../tecnica/evidencia/validacao/Mapa_Tratamentos_v1.md`, `GoLive_Gate.md`, `Alojamento_Cotacoes.md`, `Seguimento_APD.md` |
| Estação | Revisão adversarial (§1.6 da `software-factory`), **uma** passagem |
| Revisor | Subagente `general-purpose`, read-only, que recebeu os artefactos e os requisitos e **não** o raciocínio do autor |
| Árvore no lançamento | `6ae0241` (base `7426abf`) |
| Árvore na verificação | `a1af2d8` (o `#94` e o `#95` fundiram durante a revisão) |
| Achados | **17**, todos `CONFIRMADO` menos uma metade `PLAUSÍVEL` no achado 1 |
| Data | Novembro de 2026 |

---

## 1. O achado que importava: a inferência estava invertida

**Onde:** `../tecnica/evidencia/validacao/Mapa_Tratamentos_v1.md` §0.

**O que eu tinha escrito:** «à data deste mapa **não existe caminho pelo qual
dados pessoais de produção saiam da plataforma** — não porque ninguém os enviou
ainda, mas porque as saídas que os levariam não estão declaradas e as três que
estão falham fechadas. Isto é verificável em código, não é uma declaração de
intenção.»

**Porque está errado.** Duas coisas, e a primeira é de lógica:

**(a) Uma lista de saída não declarada não bloqueia nada.** Os ficheiros
`egress.yaml` são **contratos**; a aplicação na rede é o **KAM-076**, e não está
feita. Com a aplicação em falta, «não declarado» significa **«não governado»**,
não «fechado» — e eu tinha escrito isso mesmo, com outras palavras, na linha
**D2t** do meu próprio `GoLive_Gate.md`, duas secções adiante: «os contratos
existem … a aplicação na rede é o KAM-076 e não está feita». **A contradição
estava dentro do meu próprio trabalho** e não a vi, porque li cada ficheiro a
afirmar a sua tese e nenhum contra o outro.

**(b) Há contra-exemplo, e é um cliente HTTP com endereço fixo.** O
`packages/core-ts/src/outbound/cliente.ts` define
`ANFITRIAO_DA_GRAPH = "https://graph.facebook.com"` e monta um corpo que leva o
telefone do destinatário quando não há identificador da Meta. Verifiquei:
`find packages libs -name 'egress*'` devolve **zero**. O regime de `egress`
cobre `services/*` e os serviços do *compose* — **`packages/` e `libs/` estão
fora dele**. O próprio ficheiro diz que «este é o primeiro código que sai para
lá» e remete a regra para o `../tecnica/08` §4.4, um proxy de saída com lista de
permissão, **não para uma lista de `egress`**.

**A metade `PLAUSÍVEL` resolveu-se a favor do revisor.** Ele marcou assim a
questão de saber se «não existe caminho» é literalmente falso hoje, por não
encontrar nenhum serviço a instanciar o cliente. Confirmei:
`grep -rn "ClienteDaGraph" services/` devolve **nada**. Logo nenhum processo
abre hoje essa ligação — e é por isso, e só por isso, que não há caminho.

**O que ficou escrito.** Uma afirmação menor e verdadeira: **nenhum serviço em
execução instancia hoje um cliente de saída para terceiros**, pelo que a
contenção actual é de **ausência de ligação, não de controlo**; o caminho do
`packages/core-ts` existe e não está coberto por lista nenhuma; e os controlos
que governarão o envio estão **nomeados e por construir** (KAM-069 para a
autorização por destino, KAM-076 para a aplicação na rede). Mais uma tabela de
duas linhas a dizer o que **não** se pode concluir.

> **Porque isto era grave e não cosmético.** O documento vai para a APD. Uma
> afirmação de impossibilidade técnica que não se sustenta é pior do que não
> afirmar nada: convida a autoridade a verificá-la, e quem a verificar encontra
> o cliente com o endereço fixo. A versão corrigida diz menos e aguenta.

---

## 2. Os dois outros de substância

### Achado 2 — a base declarada eram 6 de 13 listas

Eu citei `infra/egress/litellm.yaml` e os cinco `services/*/egress.yaml`. O
`infra/egress/` tem **oito** ficheiros — `chatwoot.yaml`,
`chatwoot-worker.yaml`, `chatwoot-db.yaml`, `chatwoot-redis.yaml`,
`litellm.yaml`, `postgres.yaml`, `queue.yaml`, `seaweedfs.yaml` —, logo são
**treze** listas. A conclusão sobrevive (as outras doze têm `destinos: []`), mas
**quem verificasse pela base que eu dei não a podia reproduzir**, e num documento
cuja força é ser verificável isso é o defeito todo.

O revisor acrescentou uma observação que vale mais do que a correcção: o
`chatwoot-worker.yaml` diz, no seu próprio comentário, que «as filas deste
processo são as do correio e das notificações, que é o caminho por onde conteúdo
de conversa de um cliente final sairia sem ninguém decidir». E a pilha do Piloto
não tem cinco serviços: o `../tecnica/09` §3.1 lista também o Medusa e a pilha de
observação, que **não têm lista nenhuma**, apesar de o `../tecnica/08` §8.3.1
sujeitar «ferramentas de observabilidade» ao *gate*. Ficou no mapa como
divergência.

### Achado 3 — a finalidade sobre-declarada em dois dos três destinos de modelos

O mapa diz-se gerado da configuração, e a configuração dizia outra coisa. Lendo
o `llm/aliases.yaml` com o `services/agr/src/kamba_agr/llm/destinos.py`
(`router` e `chat` → `conversa`, `vision` → `visao`, `embed` → `embeddings`):

| Fornecedor | Finalidade real | O que o mapa dizia |
|---|---|---|
| anthropic (`router`, `chat` ordem 1) | `conversa` | `conversa` — correcto |
| openai (`chat` ordem 2) | `conversa` | `conversa`, **`embeddings`** — a mais |
| google (`vision`, `embed`) | `visao`, `embeddings` | **`conversa`**, `embeddings`, `visao` — a mais |

**`purpose` é exactamente a coluna do `tenant_destinations` e do formulário da
APD.** Declarar uma finalidade que o fornecedor não serve é **pedir autorização
para uma transferência que não existe** — o inverso do que o mapa serve.
Corrigido, e o mapa passa a dizer como a finalidade foi derivada, para que a
próxima pessoa a reconfira em vez de confiar.

---

## 3. Os restantes catorze

| # | Achado | O que se fez |
|---|---|---|
| 4 | «Cada um tem a razão a dizer `pendente`» — só o `api.anthropic.com` a tem; os outros dois falam do *fallback* e dos aliases | Passou a «a razão de um dos três di-lo; a condição comum está no cabeçalho do ficheiro» |
| 5 | O critério 6 nomeia **seis** campos por destino e faltava a **retenção proposta**; a retenção existia só por classe, e um destino toca várias classes | Coluna nova na tabela §3, com a retenção de cada destino |
| 6 | O 2.º Teste Requerido pede que «nenhum destino fique sem **linha**» no gate, e o gate agregava os catorze em duas condições | **Bloco E**, uma linha por destino, com `apd_ref`, contrato, estado e data |
| 7 | Remissão quebrada: o gate apontava para o `§5` das cotações, que é «Latência»; a recomendação de D6 é o `§6` | Corrigido. **Escapou ao meu script** porque a citação estava dentro de uma ligação Markdown — ver §5 |
| 8 | O gate declarava quatro estados no §0 e usava **seis** (`parcial`, `satisfeito por desenho`, prosa); a contagem «4 de 22» mapeava-os em silêncio | Vocabulário reduzido aos quatro, nuance movida para a coluna «Evidência», e a §6 passou a dizer **como se reproduz** a contagem |
| 9 | O critério 8 pede «cada linha com estado e **data**» e a coluna Data estava vazia nas 24, incluindo as satisfeitas | Datadas as satisfeitas; as não cumpridas ficam sem data **de propósito**, e isso está dito |
| 10 | **Promoção de estado:** «CONFIRMADO quanto aos artigos» promovia o Art. 23.º, que é **INDÍCIO** na fonte — e é o artigo que sustenta o papel de subcontratada | Separado: Art. 5.º CONFIRMADO, Art. 23.º INDÍCIO |
| 11 | A caixa 2 de DoD pede D6 e D9 **no registo da Carta**, e ficaram só nos ficheiros novos; a folha não tinha **Dono** nem **Prazo-limite**, que a caixa 5 pede | Carta §4.2 com o apontador nas três linhas, **sem mudar nenhum estado**; colunas novas na folha |
| 12 | «Não há lista pública de países adequados» sem o «**nas fontes consultadas**» que a fonte exige — são dois graus, e o segundo não é nosso para afirmar | Corrigido, com os dois graus explicitados |
| 13 | «O **único** parâmetro de retenção sem valor» é falso: o prazo de prova dos consentimentos também está «a confirmar» | Passou a «o de maior impacto, e não o único» |
| 14 | «São esqueletos» e «com o ticket nomeado no comentário» não se verificam nos cinco: o `agr` declara-se funcional, e **nenhum** nomeia o ticket introdutor | Corrigido para o que os ficheiros dizem |
| 15 | O `../tecnica/09` §19 lista **três** testes de SeaweedFS; eu atribuí-lhe quatro | O T4 passou a declarado como **acrescento nosso**, do §8.1 |
| 16 | A R4 era declarada «não aplicada» e o §3.1 aplicava-lhe o efeito em prosa («é a coluna que decide se a cotação serve») | §3.1 passou a «é a coluna que a **R4 proposta** faria decidir», e diz que hoje a decisão não a usa |
| 17 | O mesmo endereço era, numa tabela, a saída declarada de um fornecedor de transcrição e, na seguinte, prova de que nenhuma transcrição tem saída | Corrigido: nenhum endereço entra **pela finalidade** de transcrição |

---

## 4. O que saiu limpo, e com que verificação

Registo-o porque é a parte que dá crédito aos achados.

| Alvo | Resultado |
|---|---|
| **1.º Teste Requerido** — nenhum preço, SLA ou latência estimado | **Limpo.** Varredura por script: 17 linhas com número de preço/SLA/latência, nenhuma sem estado. Os herdados estão marcados ou recusados — o «~52 ms» com «**INDÍCIO** … **não o uso**», o «$300–400/mês» e o «×1–2 de JNB» fora das tabelas e declarados hipótese |
| **Dados pessoais e segredos** | **Limpo.** Zero em telefone angolano, e-mail, IBAN, NIF com valor e padrões de chave ou token |
| **Português europeu/angolano** | **Limpo.** Zero em 25 formas PT-BR, por palavra inteira |
| **Critério 2 contra a fonte** | **Limpo.** R1, R2 e R3 reproduzem as três condições do `../tecnica/09` §5.3 ponto 4 com o mesmo sentido e o mesmo conectivo |
| **Referências a KAM, D e ADR** | **Limpas.** Os onze tickets citados existem com o título atribuído; D1, D6, D9 e D12 conferem com a Carta §4.2; o maior KAM citado é o 112 |
| **Contagens entre ficheiros** | **Limpas.** Mapa §3 = 14 linhas; folha §1 = 14 e batem 1:1 pela ordem; as cinco divergências anunciadas eram cinco |
| **O *gate* de destino dos modelos é real** | **Levantado e morto.** O `destinos.py` levanta `DestinoNegado` para tudo em `prod`, é construído no arranque do serviço e chamado antes do pedido. A linha D1t do gate é verdadeira |

---

## 5. O que isto diz sobre o ciclo, e um portão que falta

**O achado grave era uma contradição interna que nenhuma máquina apanha.** O
mapa afirmava que as listas não declaradas fecham a saída; o gate, duas secções
adiante, dizia que a aplicação não está feita. **Os dois ficheiros eram meus, do
mesmo dia.** Nenhum linter compara duas afirmações em dois documentos, e a minha
*self-validation* leu cada um a afirmar a sua tese. É o modo de falha que a
skill descreve na abertura — «deixar dois documentos a dizer coisas diferentes
sem ninguém notar» — e aconteceu **dentro de um único ticket**.

**Nenhum dos seis linters verifica referências de secção nem caminhos fora dos
blocos de *handoff*.** O `lint_handoff` olha só para dentro dos blocos e o
`lint_refs` valida identificadores, não caminhos. Escrevi um script que extrai as
citações `<ficheiro> §N` e confirma que a secção existe no alvo: **apanhou dois
caminhos que não resolviam** (`specs/00_KAMBA_Carta.md` citado de quatro níveis
abaixo). Mas a **primeira versão do script tinha uma lacuna própria**: só
reconhecia o ficheiro entre acentos graves, e deixou passar as citações dentro de
ligações Markdown — onde vivia exactamente a remissão quebrada do achado 7, que
a revisão encontrou à mão. Corrigido o padrão, **92 citações e 92 válidas**.

> **Uma lição que se repete e que convém escrever uma vez mais:** nesta sessão,
> três defeitos distintos vieram de **instrumentos que não mostraram o que
> havia** — um `grep` vazio por ênfase no meio da frase (no KAM-104), uma leitura
> truncada por `cut` (idem), e agora um padrão de script que não cobria uma das
> duas formas de citar. A defesa não é ter mais cuidado: é **medir a cobertura do
> instrumento antes de confiar no silêncio dele**.

**E a colisão de numeração voltou a ser apanhada por máquina.** A minha linha de
emenda da Carta tomou a `1.3`, que o KAM-169 já tinha tomado no mesmo dia. O
`lint_backlog` recusou com a mensagem certa — «dois ramos tomaram o mesmo número
e nenhum renumerou» — e passou a `1.4`. É o portão a funcionar.

---

## 6. O que não se corrigiu, e porquê

| Item | Razão |
|---|---|
| **`packages/` e `libs/` fora do regime de `egress`** | É o achado mais reutilizável desta revisão e **não é deste ticket**: o regime é o KAM-067 e a aplicação o KAM-076. Fica medido no mapa §0, com o ficheiro e a constante nomeados |
| **Medusa e a pilha de observação sem lista de saída** | Idem. Fica como divergência no mapa §3.1 |
| **O `../tecnica/08` §8.3.2 sem linha para o fornecedor de imagem** | Lacuna já atribuída ao **KAM-069** pelo `../tecnica/08` §18; abrir ticket duplicava-lhe o âmbito. Declarada no mapa |
| **A sonda sintética externa sem linha no inventário** | Mesma razão: é alteração de documento técnico, fora do diff. Entra no mapa como destino 13, com a qualificação «a confirmar» |
| **Os itens NÃO VERIFICADOS do `../tecnica/09` §19** | Continuam NÃO VERIFICADO, e é consequência honesta de não haver cotações. A caixa 4 de DoD fica vazia por isso |

---

## 7. Retractação: a dívida 158 estava errada, e foi retirada

Esta secção foi escrita **depois** do merge do `#96`, e retira uma coisa que esse
merge pôs em `main`.

**O que a dívida 158 afirmava.** Que oito citações do `EPIC-10`, fora dos blocos
de *handoff*, usavam «caminhos relativos à raiz dentro de um ficheiro que já está
em `specs/`, pelo que não resolvem de posição nenhuma».

**Porque é falso.** A segunda metade da frase é que está errada: **um caminho
relativo à raiz resolve — da raiz.** O `specs/00_KAMBA_Carta.md`, o
`specs/01_Engineering_Standards_e_Handoff.md` e o `specs/INDICE.md` existem todos
a partir da raiz do repositório, e a raiz é **a posição de leitura que este
conjunto adopta**: o `../../specs/01_Engineering_Standards_e_Handoff.md` §5
declara que «o executor corre na raiz do repositório» e fixa os caminhos dos
blocos de *handoff* como relativos a ela. Citar `specs/X.md` de dentro de
`specs/` não é um caminho quebrado — é a outra das duas convenções que o
ficheiro usa.

**Como cheguei ao erro.** O script que escrevi para verificar as citações de
secção resolvia o ficheiro citado **só relativo à pasta do ficheiro citante**.
Lido de `specs/`, o `specs/00_KAMBA_Carta.md` dá `specs/specs/00_KAMBA_Carta.md`
e não existe — e o script reportou «ficheiro não resolve». Não lhe acrescentei a
segunda tentativa, relativa à raiz, que é a que o conjunto usa. **O instrumento
tinha uma cobertura mais estreita do que a convenção que media**, e eu li o seu
silêncio como ausência.

Soube-o ao ler o **portão de citações de secção que está a ser construído** para
esta mesma família — em ramo, ainda não fundido, pelo que não o cito pelo número
do ticket: o  recusa uma referência a um ticket que o backlog ainda
não tem, e tem razão. A sua regra de endereçabilidade diz o que o meu script não fazia:
*«resolve-se primeiro relativo à pasta do ficheiro citante, **depois relativo à
raiz**»*. Duas tentativas, não uma.

**E a oitava não era uma citação.** A linha do critério E do KAM-110 escreve
«**E. Decisão assinada** (`Gate_Piloto_Decisao.md`): `CONTINUAR`, `PIVÔ` (qual
linha de `14` §6 …)». O `§6` pertence ao `14`, não ao ficheiro — e o
`Gate_Piloto_Decisao.md` aparece **sem secção nenhuma** e como o **entregável que
aquele critério manda produzir**, não como fonte citada. O meu padrão apanhou um
`§` que estava a 40 caracteres de distância e atribuiu-lho. **Um critério que
nomeia o seu próprio entregável não é uma referência quebrada**; se fosse, todo
o entregável por fazer era um defeito.

**O que sobra.** Das oito, zero são defeito. A única citação genuinamente
irresolúvel que o script encontrou era **minha** — um `Seguimento_APD.md` nu, sem
directório, que não resolve nem da pasta nem da raiz — e foi corrigida antes do
merge. A dívida ficou, portanto, a descrever uma população vazia, e **uma dívida
que descreve um problema inexistente é pior do que nenhuma**: manda a próxima
pessoa procurar o que não está lá, e uma dispensa declarada sobre ela seria uma
dispensa falsa. Retirada.

**A colisão de número, de passagem.** O ticket desse portão tomou o **158** para
outra dívida — o intervalo de identificadores desactualizado no `../ci.md` §3 —,
porque o seu ramo foi cortado antes do `#96` fundir. Retirar a minha resolve a
colisão a favor da dele, sem ninguém ter de renumerar.

**A quarta do dia, e é a mesma.** Quatro defeitos desta sessão vieram de
instrumentos cuja cobertura era mais estreita do que a pergunta: um `grep` vazio
porque a frase tinha ênfase no meio; um `cut` a truncar antes da metade que
importava; um padrão que não via as citações dentro de ligações Markdown; e agora
um resolvedor com uma tentativa em vez de duas. **A defesa não é mais cuidado:**
é perguntar, antes de confiar num silêncio, o que o instrumento **não** cobre — e
dizê-lo junto com o resultado.

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.1 | Novembro 2026 | **Retractação da dívida 158** (§7), escrita depois do merge do `#96` e a retirar o que ele pôs em `main`: as sete citações `specs/…` do `EPIC-10` são **relativas à raiz e resolvem de lá**, e a oitava não era citação — era o entregável que o critério nomeia. O erro foi do meu resolvedor, que tentava **uma** posição onde a convenção usa duas. A dívida descrevia população vazia e foi retirada. | Equipa KAMBÁ |
| 1.0 | Novembro 2026 | Revisão adversarial do KAM-105: **17 achados**, todos corrigidos. O grave foi a afirmação central do mapa — correcta na conclusão, **invertida na inferência** —, que contradizia uma linha do meu próprio gate escrita no mesmo dia; mais a base declarada de 6 em 13 listas de saída e a finalidade sobre-declarada em dois dos três destinos de modelos, que é coluna do formulário da APD. Registado o que saiu limpo e com que verificação, o que não se corrigiu e porquê, e duas lacunas de instrumento: nenhum linter verifica referências de secção, e o meu primeiro script para as verificar tinha ele próprio uma lacuna de cobertura. | Equipa KAMBÁ |
