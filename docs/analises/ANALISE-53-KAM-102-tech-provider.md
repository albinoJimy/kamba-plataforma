# ANÁLISE-53 — Revisão adversarial do KAM-102 (Tech Provider, App Review, D5)

| Campo | Valor |
|---|---|
| Ticket | KAM-102 (EPIC-10) — Business Verification, App Review e Tech Provider (D5) |
| Ramo | `feature/KAM-102-tech-provider-app-review` |
| Revisão lançada sobre | `f740bc3`, **depois** de empurrar o ramo |
| Método | Subagente independente, **sem** o raciocínio do executor; recebeu o diff, o bloco do ticket e as fontes que ele nomeia |
| Alvo | [`../tecnica/evidencia/validacao/Tech_Provider_Dossie.md`](../tecnica/evidencia/validacao/Tech_Provider_Dossie.md) (novo) e o bloco KAM-102 de `../../specs/EPIC-10_Spikes_Validacao_Gates.md` |
| Achados | **27** — **15 `CONFIRMADO`** e **12 `PLAUSÍVEL`**; **27 aplicados**, **0 `MORTO`**. Mais **três** correcções que a **integração** trouxe depois (§4, numeradas 28 a 30), e que não são achados da revisão |
| Data | 2026-11-06 |
| Depois da revisão | A integração da `main` em `111de2d` (fusão do **KAM-100**) obrigou a **três** correcções que a revisão não podia ter visto, e estão no §5 |

---

## 1. Porque é que isto fica escrito

Um achado morto que não se regista volta na próxima auditoria e paga-se outra
vez; e um achado **vivo** que se corrige em silêncio deixa a próxima sessão a
repetir o erro. Nesta revisão nenhum achado morreu — o que é um resultado em si,
e o que mais diz sobre a entrega original.

**Os três que mudaram a entrega**, e não só o texto:

1. **Desmarcou a única caixa marcada.** A caixa 3 de DoD pede que os segredos
   estejam no cofre **e** que os documentos da empresa estejam em arquivo
   controlado. A evidência dada provava a **ausência no repositório** — que é
   outra coisa. Nada foi submetido, o `config_id` está «não criado», e a coluna
   «Onde vive» do dossiê é declaradamente uma **proposta**. Pela mesma régua com
   que o executor desmarcou o critério 1 («a tabela existe, o valor medido não»),
   esta caixa tinha de ficar vazia. Passou de **1 de 5** para **0 de 5**.
2. **Desfez um endurecimento do canon.** O dossiê afirmava, como a frase que
   «ordena tudo o resto», que escolher MPS ou BSP «não é preencher D5: é
   substituir um ADR em vigor». Quatro fontes dizem o contrário: o
   [`../tecnica/00_Arquitectura_Solucao.md`](../tecnica/00_Arquitectura_Solucao.md)
   §13.3 mantém D5 nas decisões **abertas**; a Carta §4.2 dá-a **ABERTA** com
   dono Produto; o
   [`../tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](../tecnica/01_Canais_WhatsApp_Fluxo_Dual.md)
   §4.1 dá o BSP como «alternativa só se Tech Provider falhar» e a cotação a 2
   BSPs **como plano B**; e o `14` §6 inscreve «BSP parceiro» como **pivô**. O
   que o ADR-001 bane é o *gateway* não-oficial. **Exercer um plano B inscrito no
   canon não é substituir um ADR** — e se a redacção do ADR-001 tiver de mudar,
   isso é pergunta para o Arquitecto de Plataforma e para o fundador, que ficou
   devolvida.
3. **Mostrou que um *storyboard* estava ao alcance onde o dossiê chamava
   «achado» à sua ausência.** Para as permissões de redes não há publicação
   automática para gravar — o ADR-020 regra 3 proíbe-a no Piloto e a D13
   difere-a —, mas **há** o fluxo que as próprias descrições do dossiê
   descrevem: gerar a peça, o dono aprovar, entregar para publicação manual (o
   `ManualDelivery` de `../tecnica/evidencia/E5_Modulos_Entrada.md` §3). Redigir
   descrições para essas permissões e recusar-lhes gravação era uma assimetria
   sem razão. O *storyboard* passou de **quatro** gravações a **seis**.

---

## 2. Os 27 achados

A classificação é a do executor, depois de verificar cada achado contra a
árvore. «Aplicado» significa que o texto mudou; a coluna diz o que mudou.

### 2.1 Afirmações que não se sustentavam na fonte citada (categoria 1)

| # | Achado | Classe | O que se fez |
|---|---|---|---|
| 5 | O «*turnaround* muito mais rápido» da verificação conduzida por Solution Partner estava dado como **CONFIRMADO**, quando a linha de E1 §3 que o carrega tem estado **NÃO VERIFICADO (prazo)** e a sua segunda fonte está declarada **«listada, não lida»**. E caía o qualificador **Select/Premier**, alargando a afirmação a qualquer Solution Partner | **CONFIRMADO** — é o achado de categoria 1 desta revisão, num ficheiro cujo pedido avisava que promover INDÍCIO é o defeito mais comum da casa | Desceu a **NÃO VERIFICADO**, com a razão escrita e o qualificador reposto |
| 8 | «As acompanhantes que **E1 §3** (…) nomeiam» — `pages_read_engagement`, `instagram_business_basic`, `publish_video`, `pages_manage_posts`: **nenhuma ocorre em E1**, em §3 ou em qualquer secção | **CONFIRMADO** (`grep` sobre E1 devolve zero) | A atribuição passou a E5 §3 e ao critério 9; as duas linhas das permissões de redes dizem «**não consta de E1**» |
| 9 | A «pergunta 1 da lista "Para a Meta"» não está em **E5 §3** — vive na secção final não numerada «Perguntas para o advogado e para a Meta». O `lint_refs` não a apanha porque o §3 existe; é o conteúdo que não está lá | **CONFIRMADO** | Citação corrigida para a secção certa, nos três sítios |
| 10 | «Perde o Fluxo A, que é a base do desenho (`01` §4)» — o §4 do `01` é «Estatuto perante a Meta»; o Fluxo A *vs* Fluxo B é o **§12** | **CONFIRMADO** | Citação corrigida |
| 11 | O INDÍCIO da barreira do cartão atribuído ao `00` §13.3, que é uma tabela de decisões abertas e **não classifica** nada. Quem o afirma é **E1 §1** (CONFIRMADO quanto à facturação em moeda estrangeira, com a barreira como **implicação**), e quem lhe põe o rótulo INDÍCIO é a tabela de riscos do **EPIC-10** | **CONFIRMADO** | Atribuição reescrita com os três graus separados |
| 12 | As 1.000 *service messages* atribuídas a E1 §3; estão em **E1 §1**, e são **por número de telefone** — qualificador que o dossiê deixava cair, e que é o que torna o escudo partilhável ou não | **CONFIRMADO** (a afirmação sobrevive por `10` §6.1; falhava a citação) | Citação corrigida e o «por número» reposto, com a consequência escrita |
| 22 | «App Meta tipo *Business*» dado como CONFIRMADO por E1 §3, que diz «app Meta com caso de uso WhatsApp e portfólio de negócio» e **não** nomeia o tipo. Quem o fixa é o `01` §4.2 | **CONFIRMADO** (facto certo, fonte errada) | Fonte corrigida |
| 23 | O §7 item 2 de `Meta_Perguntas.md` transposto do canal de **envio das perguntas** para o canal de **escalada do App Review**, sem declarar a transposição | **CONFIRMADO** | A transposição passou a vir declarada: transpõe-se a razão, não a conclusão |
| 24 | «cinco documentos» afirmam a cláusula 4.7 sem a condicionante, contra uma tabela que enumera **seis**. A prosa da fonte também diz cinco | **CONFIRMADO** | Fica a discrepância escrita e **não corrigida**: o alcance do ticket da L1 é o da tabela, e reconciliar a prosa é dele |

### 2.2 Caixas e contagens (categorias 2 e 6)

| # | Achado | Classe | O que se fez |
|---|---|---|---|
| 1 | «o credor de **doze** deles é o fundador» — a tabela do §12 dava **nove** | **CONFIRMADO** | Contagem recontada por *script* e reescrita; com os dois itens novos são **dezoito** itens e o fundador é credor em **dez** |
| 17 | A única caixa marcada (caixa 3 de DoD) fecha-se **em espírito**: a evidência prova a ausência no repositório, não a existência do arquivo controlado | **CONFIRMADO** pela régua que o próprio ficheiro aplica ao critério 1 | Desmarcada. **0 de 5** |
| 18 | «*Gate* 9 verde» a partir de **uma** das suas duas passagens (desde o KAM-131 corre árvore **e** história do PR, `../ci.md` §2); o argumento do `+244` pertence ao ***gate* 7**; o padrão vive em `numeros.ts` e não em `inventario.ts`; e os `+244` do dossiê são **dois**, não um | **CONFIRMADO** (quatro sub-pontos, todos verificados) | A célula passou a dizer que correu a passagem da árvore e **só essa**, com o *gate* 7 nomeado e a contagem certa |
| 6 | «o **único** cujo prazo é NÃO VERIFICADO» — o prazo da *Access Verification* também o é, duas linhas abaixo e no §8.2. E «o passo 2 é o primeiro da cadeia» contra a própria tabela, onde o passo 1 o precede | **CONFIRMADO** | Reescrito: o passo 2 é o **primeiro com prazo de terceiro**, e o passo 5 também tem prazo NÃO VERIFICADO, com o agravante de não se saber o processo |
| 27 | A célula «Condição: **Nenhuma**» do limite de 10 sem remissão para o §8.3, que regista uma condição **anterior** a esse limite | **CONFIRMADO** | Remissão acrescentada, mantendo o §8.3 como **INDÍCIO** |

### 2.3 Instrumentos que não podiam responder ao que se lhes pedia

| # | Achado | Classe | O que se fez |
|---|---|---|---|
| 14 | O *blockquote* argumentava que `por submeter` «**não é um resultado**» e a tabela logo abaixo escrevia-o na coluna **Resultado**. O precedente invocado (`Seguimento_APD.md` §1) tem **«Estado» e «Resultado» como colunas separadas** | **CONFIRMADO** — e «o precedente é exacto» era falso no único ponto que importava | Coluna **«Estado»** acrescentada, `por submeter` mudou para lá, «Resultado» nasce em branco |
| 15 | A lista de verificação da semana 6 manda ler a aprovação por permissão na «linha 4 do §2», que é uma linha única com uma célula de resultado | **CONFIRMADO** | Passo 4 desdobrado em **4a–4d**, uma linha por permissão, e a lista aponta para 4a e 4b |
| 13 | «§1, acto 5» dado como credor do envio da **Q9**; o acto 5 é obter as cotações, e enviar perguntas **não é nenhum** dos seis actos deste ticket | **CONFIRMADO** | Corrigido para o item 1 do §7 de `Meta_Perguntas.md`, com a razão |

### 2.4 Trabalho que estava ao alcance e não foi feito

| # | Achado | Classe | O que se fez |
|---|---|---|---|
| 4 | Os «Detalhes Técnicos» do ticket mandam preparar «**o modelo de cotação a BSPs**»; o dossiê recusava-o («o pedido não se reescreve») e **não o devolvia** — o item 6 do §12 era «obter as cotações», que é outra coisa. O precedente que ele próprio invoca (`Alojamento_Cotacoes.md`) traz o **texto integral** do pedido e **nomeia os fornecedores** | **CONFIRMADO** — é «podia ter entregado e escondeu-se atrás de é acto humano» | Entregue em duas partes: a **Q15** como corpo, que continua a não se reescrever, mais as **três** perguntas que ela não faz; e uma tabela de destinatários |
| 3 | «Pede exactamente as colunas do §6.2» — a Q15 pede quatro coisas e **não pede** três colunas da tabela: presença em África, moeda de facturação e se factura em Kwanzas. As duas últimas são o NÃO VERIFICADO da própria matriz e a metade do critério 5 que pede o modelo de facturação | **CONFIRMADO** — a frase era o fundamento do «não se reescreve», e era falsa | As três ficaram redigidas em EN como **acrescento** ao corpo da Q15 |
| 16 | O «achado mais caro» do dossiê (as permissões de redes sem *storyboard*) era meio raciocínio: há o fluxo de **entrega para publicação manual**, que é o que as suas próprias descrições descrevem e que o E5 §3 permite. E o `01` §4.2 — Documento-fonte do dossiê — nunca era citado no ponto da divergência de leitura | **CONFIRMADO** na parte do *storyboard* e na citação omitida. **A conclusão do revisor de que a divergência «está resolvida» pelo `01` §4.2 não se sustenta**: o `01` §4.2 escreve «2 vídeos (mensagem, template) por permissão», que **repete** a redacção do critério 3 e acrescenta o parêntesis da leitura de E1 — nenhuma das três diz quantos ficheiros se submetem | *Storyboard* **C1** e **D1** acrescentados, com a escolha declarada e o que acontece se a Meta exigir a demonstração do acto de publicar; o `01` §4.2 passou a ser citado como **terceira formulação**, e a divergência continua devolvida |
| 25 | As quatro descrições do App Review só existiam em português, quando o formulário vai à Meta e o precedente da casa (critério 1 do KAM-101) escreve EN | **CONFIRMADO** | Redigidas em **EN e PT**, com o EN declarado como o texto que se submete |

### 2.5 Precisão de canon e de fonte

| # | Achado | Classe | O que se fez |
|---|---|---|---|
| 19 | «Escolher MPS ou BSP é substituir um ADR em vigor» endurece uma decisão que o canon registou **aberta** | **CONFIRMADO** — ver o §1, ponto 2 | Reescrito com as quatro fontes, e a versão anterior fica registada no próprio parágrafo para não voltar. Item **17** novo no §12: se a redacção do ADR-001 tem de mudar, decidem-no o Arquitecto de Plataforma e o fundador |
| 20 | «Fecho de decisão aberta é do fundador (Carta §4.2)» — a linha de D5 na Carta §4.2 dá **dono Produto** e não nomeia assinatura do fundador; onde a Carta quer o fundador, di-lo (D1, D9) | **CONFIRMADO** | Reescrito em três sítios: a assinatura do fundador cobre o **pivô** e os actos em nome da entidade legal; o **registo e o fecho** de D5 são do dono que a Carta nomeia |
| 21 | A linha do fuso dava **UTC** «para a data de registo, como todo o conjunto» — o dicionário canónico §2 fixa UTC para **armazenamento** e «apresentação em `Africa/Luanda`», e uma data numa célula é apresentação. É material: Luanda é UTC+1, pelo que uma submissão depois das 23:00 locais cai no dia UTC seguinte, e numa sexta-feira isso atravessa o fim de semana na contagem | **CONFIRMADO** | Mudado para `Africa/Luanda`, com a consequência escrita |
| 2 | O bloco citava a `ANALISE-53` **antes de ela existir** — uma afirmação sobre o mundo escrita antes de acontecer, num ficheiro que declara evitar exactamente isso | **CONFIRMADO** | Este ficheiro. O precedente do KAM-101 escreveu a sua linha de versão **depois** da `ANALISE-51` existir |
| 7 | O inventário de prazos do §2.3 declarava-se completo e deixava fora **o único INDÍCIO que o conjunto tem** para o prazo da Business Verification: «dias a semanas», com um caso de fórum a «10 dias em revisão», em E5 §3 — uma fonte que o próprio dossiê cita noutros pontos | **CONFIRMADO** — não é promover nada, é **subcontar** a evidência existente, no ponto exacto do critério 1 | Acrescentado como quarta linha, com o estado **INDÍCIO**, o âmbito (Business Verification em geral, não a do WhatsApp) e a declaração de que não tem fonte oficial |
| 26 | As durações-alvo do *storyboard* (60–90 s, 45–60 s) não têm fonte, num ficheiro cujo §7 insiste que nenhum número está inventado | **CONFIRMADO** | A coluna passou a dizer «**escolha nossa, sem fonte**» |

---

## 3. O que a revisão deu por limpo

Vale tanto como o que falhou, e fica escrito para a próxima auditoria não o
repetir.

| Categoria | Resultado |
|---|---|
| **Afirmar o que não aconteceu** — o defeito que o pedido mandava vigiar | **Limpo.** Varrido o ficheiro inteiro: nenhuma data de submissão, nenhum prazo medido, nenhum estatuto declarado, nenhuma cotação recebida, nenhuma gravação feita, nenhuma submissão usada, nenhuma PME entrevistada. A barreira do cartão vem marcada «0 de 0 — e isto não é zero por cento: é não medido». Os achados 2 e 5 são da mesma família, mas vivem no bloco do epic e numa linha do §2.3, **não nas folhas** |
| **Números afirmados como factos** | Todos batem com a fonte: 10, 200, 24 h, 1.000, 2.000, 250, 20, 6 meses, 14 dias, 3 submissões — E1 §1, §3, §8 ou `../tecnica/10_Onboarding_Governanca.md` §6.1 |
| **Credores que sobrevivem à fusão** | **Limpo.** Todos os itens do §12 têm credor nomeado — fundador, Responsável de Produto, Arquitecto de Plataforma, KAM-106 ou KAM-100. **Nenhum** «entra quando X aterrar», «fica para depois» ou «a sessão escreve-a». A única objecção era a **contagem** (achado 1) |
| **Critério desmarcado que a entrega feche à letra** | **Nenhum.** Os critérios 2, 3, 4, 5, 6, 7 e 9 exigem submissão, gravação, confirmação de painel, cotação de terceiro, número de entrevistas ou assinatura; o 1 e o 8 têm metade por medir e metade por receber |
| **Segredos, telefones, nomes, documentos** | **Limpo.** Sem App Secret, `config_id`, token, captura, nome de pessoa ou documento de empresa; os dois `+244` são indicativo de país sem dígitos de assinante |
| **Cercas de código dentro de *blockquote*** | **Nenhuma** — o `lint_contagens` lê o conteúdo de uma cerca citada como prosa, e não há nenhuma |
| **Português europeu** | **Limpo** — varrimento com fronteiras de palavra sobre as formas de PT-BR mais prováveis, zero ocorrências |
| **Jurídico com ressalva** | O §11 leva `(a confirmar por parecer)` |
| **Referências internas** | Todas resolvem, excepto a do achado 13 |
| **Citações de fonte conferidas e certas** | A ordem «Business Verification antes do App Review»; 10 → 200 com os três passos; Meta Business Partner acima de 200; contas de *developer app* não integráveis pelo ES; On-Behalf-Of descontinuado; BSUID obrigatórios e o telefone a poder faltar no webhook; ecrã gravado e nunca captura; descrição obrigatória por permissão; cURL do API Setup no lugar da app; Tech Provider sem *credit line*; *Direct Support* como atributo do estatuto; «cerca de 24 horas» com «planear 1 a 2 semanas»; «não é necessário ser BSP para coexistência»; MPS como aliança que partilha a *credit line*; os preços de BSP como INDÍCIO e a ausência de tarifa para Angola; os três pivôs do `14` §6 palavra a palavra; ADR-001 e ADR-020 regra 3; a ressalva de H4 do `Meta_Perguntas.md` §4.1; a dependência `ext:KAM-102` do KAM-095; e o contador do KAM-016 a atravessar *tenants* |

---

## 4. O que a integração da `main` trouxe, depois da revisão

A revisão correu sobre `f740bc3`, antes de o KAM-100 fundir. A integração da
`main` em `111de2d` trouxe **três** correcções que nenhum revisor podia ter
antecipado, e ficam aqui porque duas delas são colisões que se repetem:

| # | O que a fusão mostrou | O que se fez |
|---|---|---|
| 28 | **Dois ficheiros `ANALISE-52`.** O KAM-100 criou a `ANALISE-52-KAM-100-spike-h3-coexistencia.md` e esta entrega criara a `ANALISE-52-KAM-102-…`. O `git` **não** dá conflito, porque os nomes diferem; nenhum *linter* conta ficheiros de análise | Esta análise passou a **`ANALISE-53`**, com as nove referências actualizadas. O número de uma análise reclama-se como um `KAM-NNN`: quem funde em segundo renumera |
| 29 | **O `validar_evidencia.py` aterrou — e o dossiê falhava.** Os «Testes Requeridos» do KAM-102 nomeiam-no, e ele era artefacto do KAM-100 que não existia na árvore; estava **devolvido** ao KAM-100. Correu-o sobre o dossiê: **três achados** — faltavam `Estado`, `Fonte` e `Dono` na tabela de cabeçalho | Os três declarados, pela convenção que o próprio `H3_Coexistencia_244.md` do KAM-100 usa. O validador passa a **`conforme`**, código 0. **Um item devolvido cujo credor entrega fecha-se e verifica-se**: dar-lhe por fechado sem correr o instrumento era o defeito simétrico |
| 30 | **Os outros onze ficheiros de `validacao/` não passam.** Corrido sobre a pasta: **30 achados em 12 ficheiros**. Onze são alheios a este ticket — escritos antes de o validador existir. E o `Meta_Perguntas.md` tem um achado de outra natureza: o validador lê **`MORTO`** da prosa do §3.5 como se fosse o `Estado` do documento, que é um falso positivo dele | **Não corrigido**: onze ficheiros alheios a coberto de um ticket de dossiê era alargar escopo em silêncio, e o validador **não está no CI** (nem no `Makefile` nem nos *workflows*), pelo que nada está vermelho. Fica medido para a linha **L1**, com o **fundador** como credor (item 15b do §12 do dossiê) |

**A lição das três, que é uma só:** um ramo não reserva nada para si — nem a
linha de versões, nem o número da análise, nem o estado «este artefacto não
existe». As três afirmações eram verdadeiras quando foram escritas e falsas
quando o vizinho fundiu, e **nenhum portão as apanha**. Quem funde em segundo
mede-as outra vez.

---

## 5. A lição da revisão, e onde ela entra

**Quatro dos 27 achados são citações de secção erradas que nenhum *linter*
apanha** — os achados 9, 10, 12 e 22. O `lint_refs` resolve `§N` contra os
títulos do documento citado e dá **conforme**, porque a secção **existe**: o que
está errado é o conteúdo não estar nela. É a segunda sub-classe que o próprio
`tools/lint_refs/seccoes.py` declara fora de alcance por escrito — «a secção
existe e é a errada» —, e esta revisão mediu-lhe o custo: quatro em 27, num só
ficheiro, todos em afirmações de facto sobre fontes primárias.

**Não proponho portão novo.** Fechar esta classe exigiria verificar que o
conteúdo citado ocorre dentro da secção citada, e o módulo regista que essa
heurística foi **medida sobre a árvore e rejeitada** por falsos positivos. O que
fica é a prática: **uma citação de secção confere-se abrindo a secção**, e um
revisor adversarial é hoje o único instrumento que o faz.

E a lição do achado 4, que é a mais transferível: **recusar entregar com o
argumento «é acto humano» é uma decisão que precisa de ser verificada contra os
«Detalhes Técnicos» do ticket.** Submeter é acto humano; redigir o pedido que se
submete não é.
