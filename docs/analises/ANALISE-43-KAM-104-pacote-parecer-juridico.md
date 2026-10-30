# ANÁLISE 43 — KAM-104: pacote de perguntas para o parecer jurídico

| Campo | Valor |
|---|---|
| Ticket | KAM-104 (EPIC-10 — Spikes, Validação e Gates) |
| PR | [albinoJimy/kamba-plataforma#93](https://github.com/albinoJimy/kamba-plataforma/pull/93) |
| Artefactos revistos | `../tecnica/evidencia/validacao/Pacote_Parecer_Juridico.md`, `../tecnica/evidencia/validacao/Anexo_Factos_do_Caso.md` |
| Estação | Revisão adversarial (§1.6 da `software-factory`), **uma** passagem |
| Revisor | Subagente `general-purpose`, read-only, que recebeu os documentos e os requisitos e **não** o raciocínio do autor |
| Árvore no lançamento | `0cd4b2d` |
| Árvore na verificação | `b04522a` (o `fd0a32d` / KAM-168 fundiu durante a revisão) |
| Achados | **11: 9 `CONFIRMADO`, 1 `PLAUSÍVEL`, 1 `MORTO`** |
| Data | Outubro de 2026 |

---

## 1. O que a revisão mediu, e o que saiu limpo

Registo primeiro a parte limpa, porque é a que custa mais a produzir e porque é
ela que torna os achados credíveis — um revisor que só traz defeitos não
mediu nada.

| Alvo | Resultado | Instrumento |
|---|---|---|
| **Cobertura do critério 1** | **Limpo.** As 40 presentes, verificadas **da origem para o pacote**, uma a uma. Nenhuma fundida, truncada ou omitida | Script: 40 blocos `####`; por bloco 12+8+6+1+5+3+5 = 40; por origem 20+12+1+4+3 = 40; por prioridade 11+19+10 = 40. **As três somas fecham entre si** |
| **Os oito campos (critério 2)** | **Limpo, 40/40**, pela mesma ordem | Script sobre os sete rótulos, com o n.º como título |
| **As prioridades (critério 2)** | **Limpo.** As 26 atribuições que o critério fixa pela letra estão todas certas | Comparação uma a uma contra a letra do critério |
| **Estados de verificação promovidos** | **Quase limpo:** 141 marcadores extraídos e comparados com a linha da fonte em `E1`, `E2`, `E3` e `08`. **Uma** promoção — achado 2 | Marcador a marcador, não por amostragem |
| **Itens assumidos com dono (critério 7)** | **Limpo**, todos com dono, e os dois exemplos do critério são os dois primeiros | Leitura da tabela |
| **Dados pessoais no anexo** | **Limpo: zero** em seis padrões (telefone `+244`, `9\d{8}`, e-mail, NIF, IBAN `AO`, URL) | Varredura por expressões regulares nos dois ficheiros |
| **Coerência com o canon** | **Limpo, e melhor do que o exigido.** O §4 reproduz `08` §8.3.2, o §5 reproduz `08` §11, o §3 reproduz `08` §7.1, o §6 reproduz `08` §8.2 e a tabela de base legal de `10` §7.2 — escolhendo **seis** finalidades sem fonte, que é o número do corpo daquela secção e não o «cinco» errado do seu título | Comparação linha a linha |
| **Referências** | **Limpas.** Os 19 `KAM-NNN` citados existem e os títulos correspondem; D1, D2, D6, D7, D8, D9, D11, D12 conferem com a Carta §4.2 e `00` §13.3, incluindo os estados | `specs/INDICE.md`, Carta, `00` |
| **Português** | **Quase limpo.** Zero formas PT-BR em 15 padrões. Duas gralhas — achado 9 | Varredura |
| **As duas lacunas que o anexo declara** | **Ambas verdadeiras** | O CDN que termina TLS está dito em `08` §8.3.2; o fornecedor de imagem aparece em `E5` §2, `09` e `08` §18 mas **não** na tabela de `08` §8.3.2 |

---

## 2. Os achados

### Achado 1 — `CONFIRMADO` — o pacote dizia que o conjunto de avaliação é inteiramente sintético, e não é

**Onde:** `Pacote_Parecer_Juridico.md`, F-03 (contexto e opções) e D-01 (opção b);
`Anexo_Factos_do_Caso.md`, §2.

**O que estava lá:** «A KAMBÁ já decidiu, por **ADR-018**, que o conjunto de
referência é **sintético** — é a decisão que o KAM-040 implementa»; opção (a)
«conjunto inteiramente sintético, sem material real — o que ADR-018 já
estabelece e o estado assumido»; opção (c) «material real pseudonimizado, **se o
parecer e a Meta o permitirem**».

**Porque é defeito.** É falso, e falso precisamente na pergunta que pergunta
isso. O **KAM-040** (`specs/EPIC-03_Agent_Runtime_Verticais.md`, critério de
aceitação) exige que cada caso tenha
`origem ∈ {sintetico, t2_anonimizado, real_consentido}` e que **nenhum caso
`real_consentido` entre sem registo de consentimento**; e
`docs/tecnica/00_Arquitectura_Solucao.md` escreve «o dataset de avaliação é
construído por reescrita sintética **e por casos autorizados pela PME**
(ADR-018)». Consequências: o advogado era informado de que o estado actual é
«nenhum material real» quando a especificação admite **duas** origens de
material real; a opção (c) era apresentada como hipótese futura quando já está
especificada; e **a barreira que existe — o registo de consentimento por caso —
não aparecia em sítio nenhum**, nem no §4 dos itens assumidos, onde devia estar.
Um parecer dado sobre «nada de real» não responde ao sistema especificado, que é
exactamente o modo de falha que este pacote existe para evitar.

**Verificação:** `grep -n "origem ∈" specs/EPIC-03_Agent_Runtime_Verticais.md` →
o critério está lá; `sed -n '413p' docs/tecnica/00_Arquitectura_Solucao.md` → a
frase está lá. **Mantém-se na árvore pós-merge.**

**Nota que vale mais do que o achado: há tensão no canon, e é mais larga do que
«uma célula-resumo».** Sete afirmações sobre a origem do *golden set*, todas a
invocar o **ADR-018**, e não dizem o mesmo. **Quatro dizem só reescrita
sintética:**

| Ficheiro e linha | O que diz |
|---|---|
| `../tecnica/00_Arquitectura_Solucao.md`:354 | A célula do **ADR-018** no registo de ADRs: «Golden set por **reescrita sintética**: os Termos da Meta proíbem treinar ou melhorar ML com dados do WhatsApp» |
| `../../specs/EPIC-10_Spikes_Validacao_Gates.md`:730 | «Casos T2 resolvidos alimentam o golden **só por reescrita sintética sem dados pessoais** (ADR-018)» — e está **no próprio epic deste ticket** |
| `../logs.md`:579 | «O *golden set* é feito por reescrita sintética \| ADR-018; Termos da Meta» |
| `../tecnica/10_Onboarding_Governanca.md`:740 | Linha de risco: «Golden set contamina-se com dados reais \| violação dos Termos Meta / Lei 22/11 \| reescrita sintética; parecer» |

**Três admitem material real com consentimento:**

| Ficheiro e linha | O que diz |
|---|---|
| `../tecnica/00_Arquitectura_Solucao.md`:413 | «o dataset de avaliação é construído por reescrita sintética **e por casos autorizados pela PME** (ADR-018)» |
| `../../specs/EPIC-03_Agent_Runtime_Verticais.md`:3799 | Critério de aceitação do **KAM-040**: `origem ∈ {sintetico, t2_anonimizado, real_consentido}`, e nenhum `real_consentido` sem registo de consentimento |
| `../../specs/EPIC-06_Indice_Pesquisa.md`:296 | «conversas do concierge/H7, **só depois da reescrita sintética e com consentimento** (a confirmar por parecer, `E3`)» |

**A tensão está dentro do `00`, entre duas linhas que citam o mesmo ADR:** a 354
dá uma origem, a 413 dá duas. Não é «observabilidade contra dataset» — a célula
da 354 é de observabilidade **e** fixa a origem do *golden set* na mesma frase.

**E uma correcção minha, que importa mais do que o achado.** O primeiro `grep`
que corri — `grep -n "Golden set por reescrita" docs/tecnica/00` — **voltou
vazio**, porque a frase real tem os marcadores de negrito dentro
(`por **reescrita sintética**`). Registei a contradição a partir do relatório do
revisor **depois de a minha própria medição ter falhado em confirmá-la**, e isso
é exactamente o que o §1.4 proíbe: uma afirmação de um subagente verifica-se com
comando próprio, e um comando que volta vazio é um comando por corrigir, não uma
confirmação pela negativa. A tensão existe — as sete linhas acima medem-na — mas
eu cheguei a ela pelo caminho errado, e por pouco teria registado no canon um
defeito que não tinha medido.

A tensão é anterior a este ticket e **fica registada aqui**; não se corrigiu, por
ser fora de escopo e por tocar um ADR e quatro documentos. O que se corrigiu foi
o pacote, que citava um dos lados como se fosse o único.

**Corrigido:** o contexto de F-03 passa a dizer as três origens e a nomear a
contradição do canon; as opções passam a (a) só sintético, (b) as três origens
que o KAM-040 especifica, (c) para além delas; a opção (b) de D-01 e a frase do
anexo idem. E a barreira entrou no §4 como **17.º item assumido**, com dono.

### Achado 2 — `CONFIRMADO` — «já são transferências» é um INDÍCIO apresentado como facto

**Onde:** `Anexo_Factos_do_Caso.md` §4; `Pacote_Parecer_Juridico.md`, E-03
(opções).

**O que estava lá:** «**alojar em Luanda não dispensa o procedimento**, porque os
modelos, a transcrição e a própria Meta **já são transferências**».

**Porque é defeito.** Em `E3` §2 a afirmação «enviar texto/áudio a APIs de LLM
implica transferência internacional» está marcada **INDÍCIO (raciocínio
jurídico)**, e a África do Sul também. Nas duas frases o INDÍCIO aparecia como
facto consumado. Agrava: na mesma frase do anexo a primeira oração **levava**
«(INDÍCIO)» e a oração causal não levava nada — o leitor concluiria que a
segunda é mais firme, quando é a mesma inferência. **E é o fundamento de D1
inteiro:** é a premissa de que «Luanda não dispensa nada». O pacote protege-se em
A-02 e não aqui; o anexo, que o advogado lê como «os factos do caso», não o fazia
em sítio nenhum. Atribuir a `08` §8.3.1 não salva — essa secção também o afirma
sem estado, e cita `E3`, onde está marcado.

**Verificação:** `sed -n '62p;64p' docs/tecnica/evidencia/E3_Regulatorio_Dados.md`.
**Mantém-se na árvore pós-merge.**

**Corrigido:** as duas orações causais levam agora **INDÍCIO**, a remissão para
A-02 e a marca; e o anexo diz expressamente que a premissa de D1 vale o que valer
a inferência.

### Achado 3 — `CONFIRMADO` — a qualificação jurídica do CDN estava afirmada, e é o que a pergunta pede

**Onde:** `Pacote_Parecer_Juridico.md`, E-04 (contexto);
`Anexo_Factos_do_Caso.md` §4, nota de lacuna 1.

**O que estava lá:** «o proxy termina TLS e vê o corpo dos webhooks, **logo é
subprocessador com acesso a conteúdo**».

**Porque é defeito.** É o caso que a regra da casa separa: conclusão jurídica da
KAMBÁ afirmada sem marca e sem estado. E é a conclusão **exacta** que E-04 (= N1)
pede ao advogado — o título da pergunta é «é subprocessador com acesso a
conteúdo?». Um advogado que leia o contexto encontra a resposta já dada antes de
a formular. O facto técnico (termina TLS, vê o corpo em claro) é verificável e
não é o problema; a qualificação que lhe seguia é.

**Verificação:** `08` §8.3.2 contém a mesma frase sem marca, logo o pacote
**herdou** um defeito da fonte interna em vez de o corrigir, e não há linha de
`E1`/`E2`/`E3` com estado que a sustente. **Mantém-se na árvore pós-merge.**

**Corrigido:** o facto técnico fica, a qualificação passa a «se isso o torna
subprocessador com acesso a conteúdo é o que esta pergunta pede *(a confirmar por
parecer)*», nos dois ficheiros, com a nota de que a documentação interna o afirma
sem ressalva e o pacote não herda isso.

### Achado 4 — `CONFIRMADO` — o aviso de abertura prometia uma ressalva universal que o documento não tinha

**Onde:** aviso de abertura dos dois ficheiros.

**O que estava lá:** «**Toda** a afirmação sobre direito angolano ou sobre os
Termos da Meta que aqui apareça leva a marca *(a confirmar por parecer)* —
incluindo as que a KAMBÁ apresenta como «opções propostas»».

**Porque é defeito.** A promessa não se cumpria, e é contável: com o espaço
normalizado — a expressão parte-se por linhas, pelo que um `grep` ingénuo
subconta, e foi o que me fez subestimá-la na minha própria *self-validation* — a
marca aparecia **4 vezes** no pacote, uma delas a própria promessa, logo **3 no
corpo**; e o mesmo no anexo. **37 das 40 perguntas não tinham nenhuma**, e
nenhuma «opção proposta» a levava, ao contrário do que a promessa dizia
expressamente. O substituto — a escala de três estados por pergunta — é legítimo
e está bem aplicado, mas o aviso descrevia outro documento: um advogado que
confie numa ressalva universal **baixa a guarda onde ela falta**, que é
precisamente onde os achados 2 e 3 moravam.

**Verificação:** `re.sub(r'\s+',' ',txt).count('a confirmar por parecer')` → 4 e
4; por bloco de pergunta, 37 com zero.

**Corrigido:** os dois avisos passam a descrever o que os documentos fazem —
estado de verificação, ou a marca onde é conclusão nossa — e o do pacote
**registra a promessa falhada e a contagem**, em vez de a apagar.

### Achado 5 — `PLAUSÍVEL` → aceite, e desmarcou uma caixa — a extensão do anexo

**Onde:** cabeçalho do anexo, campo «Extensão»; e a caixa do critério 3, que
estava marcada.

**O que estava lá:** «290 linhas renderizadas … **6 páginas** à densidade de 48
linhas por página».

**Porque é defeito.** A aritmética estava certa e a convenção estava declarada,
mas a conta só dá 6 páginas **se o espaçamento entre parágrafos não ocupar linha
nenhuma** — e ocupa, em qualquer renderizador. O revisor reimplementou a
convenção em quatro variantes: 277 e 286 linhas sem os espaçamentos, **346 e 355
com**, ou seja **7,2 a 7,4 páginas**. E o próprio pacote diz que **nenhum
conversor correu** nesta máquina: logo não houve página nenhuma medida.

**Porque fica `PLAUSÍVEL` e não `CONFIRMADO`:** falta o que ninguém tem nesta
máquina — uma renderização real para contar páginas em vez de linhas. Mas o
argumento é bom e **aceitei-o**.

**O que se fez.** Cortei do anexo o que **não** é dos seis itens que o critério 3
enumera: a §8 inteira (alojamento, cópias de segurança e chaves) e o parágrafo
dos registos técnicos. O anexo passou de 3 427 a **3 058** palavras, e de ~346
para **311** linhas com os espaçamentos contados — **251** sem. Isto é **5,2 a
6,8 páginas** entre as densidades de 48 e 46.

**E a caixa do critério 3 desmarcou-se.** Cortar mais passaria a tirar conteúdo
dos seis itens que o próprio critério exige, e isso é pior para quem vai ler o
anexo do que uma página a mais. A leitura ficou escrita na linha de evidência e a
decisão voltou a quem escreveu o critério: renderizar uma vez e fechar a conta,
ou aceitar sete páginas. **É a regra da casa a funcionar: não se marca uma caixa
por duas terças partes.**

### Achado 6 — `CONFIRMADO` — contradição interna na tabela que o KAM-105 vai usar

**Onde:** `Pacote_Parecer_Juridico.md` §2 (mapa, linha A-01), contra o §0.5 e o
§2.1 do mesmo ficheiro.

**O que estava lá:** no mapa, a coluna «Decisão» de A-01 dizia **D9**; o §0.5
dizia «As P0 que decidem **D1** são sete: **A-01**, A-02, A-03, A-11, E-01,
E-02, E-03»; e o §2.1 punha A-01 na tabela «o que o KAM-105 não consegue decidir
sem isto».

**Porque é defeito.** O mapa pergunta → decisão → ticket é o artefacto que uma
caixa de DoD declara publicado. Se não liga A-01 a D1, quem o filtrar por «D1»
obtém **seis** perguntas e perde exactamente a que determina **quem submete o
procedimento**. Pelo conteúdo do §2.1, o erro estava na coluna do mapa.

**Verificação:** as três linhas estão no mesmo ficheiro e dizem coisas
diferentes.

**Corrigido:** a coluna passa a «**D1**, D9».

### Achado 7 — `CONFIRMADO` — o anexo declarava uma varredura que não podia ter corrido

**Onde:** `Anexo_Factos_do_Caso.md`, secção «Ausência de dados pessoais», e a
linha do controlo de versões.

**O que estava lá:** «Varredura automática **dos documentos de origem** e deste
anexo: **zero números de telefone**, zero NIF com valor…».

**Porque é defeito.** A parte relativa às origens é falsa, e é uma declaração de
verificação num documento que **sai da casa**. O `E2_Pagamentos_Angola.md` contém
um número de telefone público real em claro — a linha de apoio da EMIS — e três
códigos de sandbox. Ou a varredura declarada não correu, ou correu e o resultado
não é o que estava escrito. O anexo **em si** está limpo, e é isso que o critério
exige; mas uma afirmação de verificação que não se sustenta é pior do que
nenhuma, porque desincentiva quem a lê de repetir a varredura.

**Verificação:** regex de telefone angolano sobre `E2` → duas linhas.
**Mantém-se na árvore pós-merge.** Nota: o levantamento que eu encomendei na
*discovery* tinha reportado «13 ocorrências, todas sintéticas» e **não** apanhou
a linha de apoio, porque o número vem com espaços. Uma negativa trazida por um
subagente é uma afirmação como as outras.

**Corrigido:** a declaração limita-se ao anexo e ao pacote — os dois ficheiros
que saem — e **diz** que a versão anterior afirmava mais do que podia, e que a
evidência interna contém pelo menos um telefone público real.

### Achado 8 — `CONFIRMADO` — três ligações vivas, dentro do pacote, para um ficheiro que não vai com ele

**Onde:** `Pacote_Parecer_Juridico.md`, cabeçalho e §6 (duas remissões).

**Porque é defeito.** O §0.7 diz «O que sai da casa são **dois ficheiros**: este
pacote e o anexo», e o pacote levava **três ligações** para o artefacto interno
— incluindo duas a secções concretas que justificam porque os critérios 5 e 6
ficam não satisfeitos. Exportado como estava, o advogado recebia três
referências que não resolvem e duas justificações que não podia ler. Não é erro
de conteúdo: é **erro de fronteira de exportação**, e a fronteira é o que o
critério 4 e o DoD «confidencialidade respeitada» controlam.

**Corrigido:** as três passam a menção sem ligação, pelo número da secção.

### Achado 9 — `CONFIRMADO` — duas gralhas

«não **corrididos**» (deve ser «corridos»), na coluna «Barreira hoje» do item que
o critério 7 dá como exemplo — ou seja no sítio mais lido da tabela; e «contas
**inauténticas**» sem circunflexo, a cinco linhas da grafia correcta do mesmo
termo legal na mesma pergunta. A segunda é **herdada do `E3`**, e transcrever a
gralha de uma fonte num pedido de parecer sobre o texto de uma lei é precisamente
onde não se deve. Corrigidas.

### Achado 10 — `CONFIRMADO` — G-04 perdeu o acrónimo do regulador

**Onde:** `Pacote_Parecer_Juridico.md`, G-04 (texto e contexto).

A origem, `E3` 14, pergunta «Que prova de licença **ISJ** deve a PME exibir?»; o
pacote escrevia «Que prova de licença deve a PME exibir para operar jogos?», e o
contexto falava de «regulador próprio» sem nunca nomear o ISJ, apesar de o `E3`
o nomear. Sem o nome da autoridade o advogado pode responder em abstracto, e o
pacote fica sem o dado de que o screening do KAM-088 precisa. **Foi o único caso
de desgaste de sentido nas 33 perguntas transpostas.** Corrigido: o texto nomeia
o Instituto de Supervisão de Jogos e o contexto também.

### Achado 11 — `MORTO` — a colocação de E3 3, 4 e 18 no bloco E

**O que se levantou.** As três perguntas mais consequentes sobre a APD — países
adequados (E-01), o caso sancionatório (E-02) e residência de dados (E-03) —
ficam no bloco **E «Alojamento, CDN e backups»** e não no bloco **A «APD e Lei
22/11»**. O pacote justifica longamente o bloco G novo e não justifica esta
colocação; o resultado é que o bloco rotulado «APD e Lei 22/11» não contém a
pergunta que o próprio pacote chama «a mais consequente do pacote». Um advogado
que receba o pacote por lotes e leia o bloco A como «o lote da protecção de
dados» não encontra ali o Art. 33.º/34.º nem a prática sancionatória.

**A evidência que o matou.** A letra dos «Detalhes Técnicos» do ticket nomeia o
bloco E como «**alojamento**, CDN e backups», e as três perguntas são, todas,
perguntas de destino de alojamento: decidem **D1 e só D1**, que é o que o §2.1
demonstra com uma linha por cada. Além disso o §0.4 **publica** a repartição
explícita «A (11), E (3), G (5), C (1)», pelo que a colocação está declarada e
não escondida. Não há defeito.

**Fica registado com a evidência que o matou**, para não voltar na próxima
auditoria e ser pago outra vez.

---

## 3. O que isto diz sobre o ciclo

**Dois dos nove `CONFIRMADO` eram promoções de estado** (achados 2 e 3) — o
defeito que a `software-factory` diz ser o mais comum nesta casa. Confirma-se, e
num pacote para advogado é o que faz um parecer responder à pergunta errada. **A
minha própria self-validation não os apanhou:** procurei a marca
`(a confirmar por parecer)` e contei estados, mas não comparei cada estado com a
linha da fonte. A revisão comparou os 141, um a um. É a diferença entre verificar
e ler.

**O achado mais caro (1) foi uma citação do lado curto de uma contradição no
canon.** O `00` descreve o ADR-018 de duas formas que não dizem o mesmo, e eu
citei a célula-resumo tendo à mão o ticket que a implementa. A lição tem forma de
portão: **quando um ADR é citado por uma célula-resumo e por um ticket, lê-se o
ticket** — é ele que tem os critérios de aceitação.

**O achado 4 é o mais instrutivo sobre honestidade.** Eu tinha contado a marca na
self-validation e obtido «4 ocorrências», tinha-o achado pouco para 40 perguntas,
e concluí que o substituto (os estados de verificação) bastava. Bastava para o
conteúdo e **não** para o aviso, que prometia outra coisa. Um aviso que promete
mais do que o documento faz é pior do que não ter aviso.

**E o achado 7 é uma negativa de subagente que passou.** O levantamento da
discovery disse «13 ocorrências, todas sintéticas» e eu escrevi a declaração de
varredura a partir disso, alargando-a às origens. O número era de um padrão sem
espaços. A regra do §1.4 — «uma negativa trazida por um subagente é uma afirmação
como as outras: confirma-a com comando próprio» — foi escrita para isto, e eu
não a corri.

**Calibração desta revisão:** 9 `CONFIRMADO` e 1 `PLAUSÍVEL` aceite em 11
achados levantados, com 1 `MORTO`. É alta, e a razão provável está no alvo: o
contrato do revisor nomeou quatro alvos concretos e exigiu que a contagem fosse
por script, em vez de pedir «vê se está bem». Como a §3 da skill avisa, este
número lê-se à mão e é **INDÍCIO**, não `CONFIRMADO`.

---

## 4. O que não se corrigiu, e porquê

| Item | Razão |
|---|---|
| **A tensão do canon sobre a origem do *golden set*** — quatro linhas dizem só reescrita sintética, três admitem material real com consentimento, todas a citar o ADR-018, e duas delas são o `00`:354 e o `00`:413 | Fora de escopo: toca um ADR e quatro documentos, um deles o `EPIC-10`:730 deste próprio epic. Fica medida no achado 1, com ficheiro e linha dos sete, e **nomeada no contexto de F-03** para que o advogado a veja. Quem a fechar decide qual dos lados vale |
| **O fornecedor de imagem sem linha em `08` §8.3.2** | Lacuna real, e **já tem credor**: o `08` §18 atribui-a ao **KAM-069** («inventário e `apd_ref` antes de produção»). Abrir ticket duplicava-lhe o âmbito. Fica declarada no anexo |
| **A opção do caminho de webhooks atrás do proxy** | Não é defeito: é a pergunta **N1**, que o pacote leva ao advogado como E-04. Decidi-la era o erro. Ficou **fora** da lista de assunções do §4, de propósito — essa lista diz o que a KAMBÁ assume *enquanto espera*, e uma pergunta não decidida não é uma assunção |
| **A afirmação sem marca em `08` §8.3.2 e §8.3.1** | É a fonte interna de onde os achados 2 e 3 vinham. Corrigiu-se o pacote e o anexo, que é o escopo deste ticket; emendar o `08` é alteração de documento técnico, fora do diff |

---

## 5. Método

Uma passagem, read-only, sem ver o raciocínio do autor. `Grep`, `Read` e quatro
scripts Python (`-I`) para: contar os 40 blocos e as três somas; verificar os
oito campos nos 40; extrair e comparar os 141 marcadores de estado contra as
linhas das fontes; varrer dados pessoais por seis padrões; contar as marcas
`(a confirmar por parecer)` **com o espaço normalizado**, porque a expressão
parte-se por linhas e um `grep` simples subconta; reimplementar em quatro
variantes a convenção de contagem de linhas do anexo; e resolver os sete links
Markdown. Nada foi escrito no repositório pelo revisor. **O codegraph não foi
usado**, e com razão: o índice cobre código, e todo o eixo deste ticket é `.md`.

Cada `CONFIRMADO` foi **reverificado contra a árvore pós-merge** (`b04522a`), que
não é a árvore sobre a qual a revisão foi lançada (`0cd4b2d`) — o `fd0a32d`
fundiu pelo meio. Nenhum morreu nessa passagem.

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Revisão adversarial do KAM-104: 11 achados, 9 `CONFIRMADO` corrigidos, 1 `PLAUSÍVEL` aceite (desmarcou a caixa do critério 3), 1 `MORTO` registado com a evidência que o matou. Mais o que ficou por corrigir, com razão por item, e as quatro lições do ciclo. | Equipa KAMBÁ |
