# ANALISE-51 — KAM-101: revisão adversarial do dossiê de perguntas à Meta

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Análise — revisão adversarial do KAM-101, com a verificação de cada achado |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-101 (EPIC-10) |
| Artefacto revisto | [`../tecnica/evidencia/validacao/Meta_Perguntas.md`](../tecnica/evidencia/validacao/Meta_Perguntas.md) e o bloco KAM-101 de `../../specs/EPIC-10_Spikes_Validacao_Gates.md` |
| Ramo e commit revistos | `feature/KAM-101-perguntas-meta`, `01dcd3a` |

**Uma revisão, corrida sobre o ramo depois de empurrar, sem o raciocínio do
autor.** O revisor recebeu o artefacto, os critérios de aceitação e as fontes
contra as quais verificar — nunca as justificações de quem o escreveu. Devolveu
**14 achados**. Cada um foi verificado contra a árvore antes de gerar trabalho,
e o resultado está na coluna «Verificação»: **12 CONFIRMADO**, **1 MORTO** e
**1 PARCIALMENTE MORTO**.

> **O achado mais valioso desta revisão matou uma afirmação do próprio autor.**
> O A6 levou à descoberta de que o «desvio 2» que o ficheiro alegava contra o E1
> **não existe**: o E1 §1 já registava a data que o desvio dizia faltar. Um
> revisor que concordasse tinha deixado uma afirmação falsa sobre uma fonte de
> verdade dentro de um ficheiro de evidência.

---

## 1. Os achados, com a verificação

| # | Achado | Gravidade | Verificação | O que se fez |
|---|---|---|---|---|
| A1 | O critério do KAM-102 sobre D5 e as cotações de BSP é citado como **4** em quatro sítios do ficheiro e um do epic; é o **5** | media | **CONFIRMADO.** Numeração das caixas do bloco KAM-102: o 4 é «Estatuto Tech Provider confirmado no painel da app», o 5 é «**D5 registada até à semana 4** … ≥ 2 cotações formais de BSP» | Corrigidas as **cinco** citações. As duas que estavam certas (estatuto na via B do §4.1, *Direct Support* no §8) ficaram intactas |
| A2 | Três dos quinze campos «secção de E1 que a origina» nomeiam uma secção que não origina a pergunta | media | **CONFIRMADO, com a medição dos limites das secções.** Q14 dizia §5 e a linha dos limites por utilizador de marketing está no **§7**; Q4 dizia §2 e o registo/verificação de números está no **§5** e no **§3**; Q10 dizia §1 e §5 e a janela FEP só aparece no **§1** | Corrigidos os três, e cada um passa a nomear a **linha** e não só a secção, com o «**não** §N» escrito, para a correcção não se perder |
| A3 | A caixa do critério 1 não fecha «à letra»: (a) o estado nasce num quarto valor, `por enviar`; (b) duas perguntas não nomeiam decisão afectada | media | **(a) MORTO. (b) CONFIRMADO.** O critério 7 do KAM-105 nomeia **quatro** estados (`submetido`, `em apreciação`, `autorizado`, `negado`) e **`por submeter` não está entre eles** — o `Seguimento_APD.md` também nasce num estado anterior acrescentado pelo executor, pelo que o precedente é **exacto** e o argumento que o distinguia não se sustenta. Em (b), a contagem confirma: 13 das 15 nomeiam decisão ou ADR | A caixa **fica marcada**, e as duas leituras ficam **medidas e devolvidas** ao Responsável de Produto (§7, item 11), com a nota escrita de que, na leitura estrita, a caixa desmarca-se — e que desmarcá-la é de quem escreveu o critério |
| A4 | Três contagens incompatíveis para o mesmo conjunto de desvios: «três divergências», «quatro desvios», cinco rótulos | media | **CONFIRMADO** | Depois de A6 matar um, ficam **quatro vivos** (0 a 3) e **um morto** (§3.5). Todas as contagens, nos dois ficheiros, passam a dizer isso |
| A5 | O desvio 0 diz «três páginas» e foram quatro, e omite a data que o E1 atribui à quarta | media | **CONFIRMADO.** As páginas relidas em `developers.facebook.com` são `pricing/ai-providers`, `onboarding-business-app-users`, `embedded-signup/overview` e `changelog` | Passa a **quatro**, com a data que o E1 atribui a cada uma, a de preços incluída (**Sep 1, 2026**) |
| A6 | O desvio 2 afirma que «E1 trata as duas datas como uma», e o E1 trata-as como duas | media | **CONFIRMADO, e mais fundo do que o achado dizia: o desvio está MORTO.** O **E1 §1** regista «Pricing policy para "AI Providers" … **desde 16 Fev 2026**», CONFIRMADO e com a mesma fonte; e a releitura mostra que a página de preços **confirma** 15 Jan 2026 como data dos Termos, pelo que o parêntesis do E1 §4 também está correcto. Não há desvio nenhum | O desvio **sai** do §3 e fica registado no **§3.5** como MORTO, com a evidência que o matou e a causa: lera-se o E1 §4 e não o E1 §1 |
| A7 | A correcção devolvida nomeia dois documentos, e a leitura geral da cláusula está em mais sítios | media | **CONFIRMADO, e o levantamento foi alargado.** Além do E1 §4 e do `10` §11.3, há **cinco** sítios que a afirmam **sem** condicionante (`00` §11, a célula do ADR-018 em `00` §8, `10` §7.3, o `EPIC-03`, o `KAM-169.md`) e um **ADR-L em vigor** entre eles; e **seis** que já se declaram NÃO VERIFICADO ou com ressalva | O **§3.1.1** passa a nomear os dois grupos, com o que cada sítio diz hoje e como entra no ticket. O ADR-L fica marcado como **não corrigível por iniciativa de sessão**: regista uma decisão do fundador |
| A8 | O credor do item 6 do §7 não sobrevive à fusão: «KAM-NNN a abrir» | media | **CONFIRMADO.** É o único dos dez itens sem credor verificável, e um ticket que ainda não existe morre no acto da fusão | O credor passa a ser o **fundador**, que é a autoridade do canon de que estes documentos são nível 2 e 10 |
| A9 | O texto EN acrescenta especificações em nove perguntas e só uma adição está declarada; e a Q4 EN deixa de nomear as operadoras que o PT nomeia | media | **CONFIRMADO** | Nova secção **§1.2**: declara as nove, uma a uma, com a razão de cada acréscimo. A Q4 EN volta a nomear as operadoras. O cabeçalho deixa de dizer que «só o §3» muda |
| A10 | Estados do §3 acima do que o método suporta: CONFIRMADO para o *enquadramento* de uma cláusula sobre uma só leitura automática | media no commit revisto | **CONFIRMADO, e já estava corrigido** em `d762e71`, empurrado antes de a revisão responder | Nada a fazer. O §3 passou a fixar a regra de estado, e o §3.1 e o §3.4 baixaram a INDÍCIO |
| A11 | O registo de H4 grava `inconclusiva` sem nenhuma das condições da sua própria lista de verificação | menor | **CONFIRMADO** | O estado passa a **«Não avaliada»**, com o resultado por omissão dito à parte. Um estado não pode negar a lista que o define |
| A12 | «Decisão afectada» com referências que não cobrem a pergunta: **D12** na Q7 e **ADR-001** na Q13 | menor | **CONFIRMADO.** O D12 é «CDN/WAF que termina TLS como subprocessador; licença do Redis»; o ADR-001 é «Cloud API oficial + coexistência; Tech Provider; ES v4; GWY» | A Q7 passa a **ADR-008** (residência e transferências — enviar conteúdo de conversa a um LLM de terceiros é uma transferência). A Q13 passa a **—**: nenhuma decisão aberta depende dela, e inventar uma era o defeito |
| A13 | «Os três lotes» numa tabela com dois números de lote | menor | **CONFIRMADO** | Passa a «**três grupos de prioridade, em dois lotes de envio**», com a razão escrita |
| A14 | Citação do E1 truncada dentro das aspas, sem elipse, a perder a ressalva da própria fonte | menor | **CONFIRMADO** | A citação passa a incluir «, tradução da leitura automática» |

### 1.1 O que a revisão deu por limpo

Vale tanto como a lista de achados, e por isso fica escrito. Verificado e limpo:

- **As 15 perguntas.** Presentes, com a numeração e a ordem do E1. *Diff*
  programático PT contra E1: **15 de 15 literalmente idênticas**, mudando só o
  estilo de aspas. Nenhuma encurtada, fundida ou alterada de sentido. O EN mantém
  as 15 — o que acrescenta é o A9.
- **Lotes e contagens das perguntas.** Lote 1 = 8, lote 2 = 6 + Q15 = 7, total
  15. Nenhuma em dois lotes, nenhuma fora. Bate com os «Detalhes Técnicos» e com
  o critério 2. As caixas: 7 critérios com 4 marcados, 5 de DoD com 2 marcados.
- **Os nove campos.** Presentes nos 15 blocos, nenhum em falta. Doze das quinze
  origens conferiam já contra a árvore; as outras três são o A2.
- **Respostas inventadas: zero.** `Data de envio` = `—` nas 15; `Estado` =
  `por enviar` nas 15; as colunas de canal, envio, resposta e classificação da
  folha **vazias** nas 15. Nenhuma ficha de resposta preenchida. Nenhum facto
  atribuído à Meta sem URL e data de leitura. **É o que este ticket mais
  arriscava, e verifica-se por contagem e não por leitura.**
- **Nenhum NÃO VERIFICADO fechado.** O risco 1, a *Access Verification* e a
  elegibilidade de Angola mantêm-se, cada um com a razão escrita.
- **Nenhuma reprodução do texto dos Termos.** Só resumo, com as citações em
  inglês limitadas a fragmentos de duas a quatro palavras, e a proibição de
  transcrever afirmada no próprio ficheiro.
- **Caixas não marcadas.** Todas com razão escrita **e** credor que sobrevive à
  fusão. Nenhuma diz «quando X aterrar», «fica para depois» ou «a sessão
  escreve-a» — as três formas foram procuradas. A única excepção era o A8.
- **D2, D10 e H4.** D2 fica CONDICIONAL com gatilho e assinatura vazia; D10 fica
  provisória com o fecho reservado ao fundador; a regra de H4 tem as três saídas
  e a ressalva. **Nada decide por humanos**: as divergências de leitura são
  devolvidas em vez de resolvidas.
- **Escopo.** Dois ficheiros no *commit* revisto. Nada do KAM-102 entra, e o §5.3
  recusa registar o D5.
- **Forma.** Os sete caminhos relativos resolvem; os `KAM-NNN`, `ADR-NNN`, `D#` e
  `H#` citados existem; ortografia em português europeu, com zero ocorrências de
  treze formas PT-BR procuradas; tabela de cabeçalho, tabela de aprovação e
  «Controlo de versões» presentes; versão do epic 1.8 → 1.9 no cabeçalho **e** na
  tabela, sem buraco na numeração.
- **Dados pessoais e segredos: zero**, nos dois ficheiros — sem nomes de pessoas,
  sem endereços de correio, sem `+244` seguido de dígitos, sem números em forma
  angolana, sem `token`/`key`/`secret`/`bearer`. O `+244` aparece só como
  indicativo de país.

### 1.2 O que a revisão não podia verificar

O **conteúdo** da releitura do §3 — o que as páginas da Meta dizem hoje. São
páginas vivas de terceiros e a revisão corre sobre a árvore; não há segunda
leitura independente para as contrapor. **É exactamente por isso que o estado
importa**, e é o que o `d762e71` corrigiu: o leitor não tem outra salvaguarda
além do estado que o ficheiro atribui à leitura, e por isso ele é **INDÍCIO, uma
leitura**. O que *é* verificável — e foi verificado — é tudo o que o §3 afirma
**sobre o E1**: aí os desvios 1, 2 e 3 conferem, e o quarto morreu (A6).

---

## 2. As três lições, e o que fazem a seguir

| Lição | De onde | Destino |
|---|---|---|
| **Um desvio alegado contra um documento mede-se contra o documento inteiro, não contra a secção que se tinha aberto.** O desvio morto do §3.5 nasceu de ler o E1 §4 e não o E1 §1, que tinha a resposta a duas secções de distância | A6 | Registada no **§3.5** do artefacto, com a causa. Não vira portão: não há linter que saiba que uma afirmação sobre um documento devia ter sido medida contra outra secção dele |
| **Citar o critério de outro ticket pelo número exige contar as caixas desse bloco.** Cinco citações erradas saíram de contar de memória | A1 | Candidata a **portão**, e o credor é o **fundador**: uma citação da forma «KAM-NNN, critério N» é verificável por contagem das caixas do bloco citado, como o `lint_backlog` já verifica dependências, e cabe num portão que já existe. Mas **alterar o critério de um portão é decisão do fundador**, não de sessão — por isso aqui fica a **medição** (cinco citações erradas num só ticket, nenhum linter as viu) e não a implementação. Não se abre ticket a frio: com cinco sessões a correr, tomar número era criar a colisão que o KAM-101 evitou |
| **Redigir numa segunda língua é uma decisão de redacção, e declara-se.** Nove perguntas ganharam especificações que o português não pedia, e só uma estava declarada | A9 | Registada no **§1.2** do artefacto. A revisão cruzada do «Testes Requeridos» passa a ter o que recusar |

---

## 3. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Produto | | | |
| Arquitecto de Plataforma | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-101. Uma revisão adversarial sobre `01dcd3a`, corrida depois de empurrar e sem o raciocínio do autor, com **14 achados** verificados um a um contra a árvore: **12 CONFIRMADO**, **1 MORTO** (o A3a: o critério 7 do KAM-105 nomeia quatro estados e `por submeter` não está entre eles, pelo que o precedente do estado anterior é exacto e o argumento que o distinguia cai) e **1 parcialmente morto**. O mais valioso foi o **A6**, que levou a matar uma afirmação do próprio artefacto: o «desvio 2» alegado contra o E1 não existe, porque o E1 §1 já registava a data da política de preços, CONFIRMADA e com a mesma fonte, e a página de preços confirma a data dos Termos — um revisor que concordasse tinha deixado uma afirmação falsa sobre uma fonte de verdade dentro de um ficheiro de evidência. O **A10** estava já corrigido em `d762e71`, empurrado antes de a revisão responder. Nenhum achado tocou no que o ticket mais arriscava: zero respostas inventadas, zero datas de envio preenchidas, zero NÃO VERIFICADOS fechados, zero dados pessoais, nenhuma reprodução do texto dos Termos — e isso verificou-se por contagem, não por leitura. | Equipa KAMBÁ |
