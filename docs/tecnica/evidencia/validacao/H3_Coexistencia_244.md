# H3 — coexistência com três números +244

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Validação — resultado do spike H3: coexistência em três números +244 |
| Versão | 1.0 |
| Data | Novembro de 2026 |
| Classificação | Documento de Referência — Interno |
| Ticket | KAM-100 (EPIC-10) |
| Estado | NÃO VERIFICADO — o spike **não correu**: nenhum número foi ligado |
| Fonte | `../E1_Meta_WhatsApp.md` §2 e §5; `../../01_Canais_WhatsApp_Fluxo_Dual.md` §4.3, §4.4, §10, §13; `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 |
| Dono | Fundador (único a falar com donos de números e a obter consentimentos) |
| Documento-fonte | `../../../../specs/EPIC-10_Spikes_Validacao_Gates.md`, bloco KAM-100 |
| Relacionados | [`Registo_Hipoteses.md`](Registo_Hipoteses.md), [`Meta_Perguntas.md`](Meta_Perguntas.md) |

> **Este ficheiro nasce vazio de medições, e é isso que o KAM-100 entrega.** O
> harness, o script da tabela, a folha do operador e o validador estão feitos e
> exercitados; o que falta é o que **só uma pessoa pode fazer** — falar com três
> donos de número, obter consentimento escrito e correr o Embedded Signup com
> cada um. O executor não o fez e não o pode fazer.
>
> O que está preenchido são as **colunas certas**, o **limiar operacionalizado**,
> a **regra de decisão** e o **Passo 0** com o estado que ele tem hoje. O que
> está em `NÃO MEDIDO` significa que o evento não chegou, nunca que correu mal.

---

## 1. Passo 0 — o ES v4 de coexistência pode correr antes da aprovação de Tech Provider?

**Resposta: `NÃO VERIFICADO`.**

| Campo | Valor |
|---|---|
| Data da leitura | 2026-11-06 |
| Fonte | `../E1_Meta_WhatsApp.md` §2 (o requisito) e §3 (as páginas de Tech Provider, Embedded Signup e App Review lidas) |
| Quem leu | Executor do KAM-100, por leitura das afirmações já registadas em E1 — **sem releitura de fonte primária** |
| Estado | NÃO VERIFICADO |

O que se sabe, e o que não:

| Afirmação | Estado | Onde |
|---|---|---|
| A coexistência **exige** ser Solution Partner ou Tech Provider | CONFIRMADO (fonte primária) | `../E1_Meta_WhatsApp.md` §2 |
| Se o requisito se satisfaz com a app em **modo de desenvolvimento** e utilizadores com função atribuída | **NÃO VERIFICADO** | nenhuma das páginas registadas em `../E1_Meta_WhatsApp.md` §2 ou §3 o diz, nem para afirmar nem para negar |
| Contas criadas originalmente por *developer app* **não** podem ser *onboarded* pelo ES | CONFIRMADO (fonte primária) | `../E1_Meta_WhatsApp.md` §3 |
| A elegibilidade de **Angola** para a coexistência | **NÃO VERIFICADO** (ausência de exclusão) | `../E1_Meta_WhatsApp.md` §2 |
| Fontes secundárias que dizem «global» | **INDÍCIO** | `../E1_Meta_WhatsApp.md` §2 |

**Os dois últimos estados herdam-se e não se promovem.** «Provavelmente
elegível» é a implicação que E1 tira, e não é um facto: é por isso que H3 existe.

### 1.1 Consequência, escrita como estado e não como facto

O critério manda que, se a resposta for `Não`, o spike espere pelo KAM-102 e o
novo prazo fique registado. A resposta **não é `Não`** — é `NÃO VERIFICADO` —,
pelo que o que fica registado é isto:

| | |
|---|---|
| O spike arranca | **Bloqueado por uma pergunta sem resposta**, e não por um `Não` |
| Quem pode responder | A Meta, pela **Q3** e pela **Q9** de [`Meta_Perguntas.md`](Meta_Perguntas.md) §1, ambas em `por enviar` |
| Caminho alternativo | A aprovação de Tech Provider do **KAM-102**, que torna a pergunta irrelevante |
| Prazo novo | **NÃO VERIFICADO.** Não se escreve aqui: depende do KAM-102, cujo próprio prazo depende da Business Verification, cujo prazo a Meta **não documenta** (`../E1_Meta_WhatsApp.md` §3, NÃO VERIFICADO) |
| Credor | **Fundador** (envio das perguntas e decisão de esperar ou tentar), e **KAM-102** para a aprovação |

Escrever aqui um prazo em semanas seria inventar o número de que depende o
caminho crítico da Fase 0. O que se pode afirmar é a **ordem**: nenhuma das duas
vias está fechada, e a primeira a fechar liberta o spike.

---

## 2. Tabela N1–N3

Gera-se com o script, a partir dos JSON-lines do receptor:

```bash
python spikes/h3/tabela.py eventos.jsonl
```

São **catorze** propriedades: **oito saem dos eventos** e **seis preenchem-se à
mão** a partir da folha do operador (`spikes/h3/protocolo_operador.md`), porque
nenhum webhook as traz. O script escreve `NAO MEDIDO (folha)` nessas, e não um
valor plausível.

> A conta e a lista são presas por um ensaio
> (`spikes/h3/tests/test_tabela.py::TestColunas`), e não escritas aqui à mão.
> Fazia falta: a primeira versão desta secção dizia «sete das treze… cinco à
> mão» — 7 + 5 = 12 sobre uma tabela de 13 — e tinha a linha da **entrega do
> SMS** que o gerador **não produzia**. O operador perdia-a no instante em que
> regenerasse esta tabela com o comando acima, e é a linha que o critério 4
> exige. Apanhado pela revisão adversarial.

A ordem e os títulos são os do `COLUNAS` do gerador, para que regenerar não mexa
na forma da tabela:

| Propriedade | N1 | N2 | N3 |
|---|---|---|---|
| Operadora | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Tipo | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Versao da app (>= 2.24.17) | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Verificacao | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Entrega do SMS registada | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| FINISH recebido | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| `history` ou 2593109 | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Contactos em `smb_app_state_sync` | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Tempo de sincronizacao | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Latencia do eco (mediana) | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Mensagem da API gera eco | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Janela de 24 h | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| `account_update` | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |
| Eventos no registo | NÃO MEDIDO | NÃO MEDIDO | NÃO MEDIDO |

**Os números nunca entram neste ficheiro.** As colunas são `N1`, `N2` e `N3`, e
a correspondência entre rótulo e número vive **fora do repositório**, na folha
do operador — o repositório é público e o ADR-010 proíbe telefone em claro em
ficheiro de evidência. O receptor nunca grava o telefone: grava o rótulo.

### 2.1 A regra do zero

**Zero eventos de um tipo escreve-se `NÃO MEDIDO`, e nunca `N`.** «Não recebi o
`FINISH`» e «não liguei o receptor a tempo» produzem os mesmos zero eventos e
têm conclusões opostas: a primeira refuta H3 para aquele número, a segunda não
diz nada.

**E não há excepção.** A primeira versão abria uma, para a coluna do *echo* da
API: dizia que «houve *echoes* e nenhum é nosso» era prova de ausência. Não é —
só o seria se tivéssemos enviado ≥ 1 mensagem pela API, e **nada nos JSON-lines
diz que enviámos**. Com o `nossos.txt` esquecido, ou acrescentado depois de o
receptor arrancar, todos os *echoes* saem marcados como não-nossos e a célula
afirmava «uma mensagem da API **não** gera *echo*» sobre zero envios — a regra do
zero violada no único sítio onde se lhe tinha aberto excepção, e no item que o
DoD 5 declara ter passado a ter instrumento. Apanhado pela revisão adversarial.

A coluna escreve agora `S` quando se viu e `NÃO MEDIDO` no resto, com a contagem
dos *echoes* examinados. O `N` fecha-se **cruzando** com o passo 4.2 da folha do
operador, que é o que registra se houve envio pela API. É o item NÃO VERIFICADO
de `../../01_Canais_WhatsApp_Fluxo_Dual.md` §10.3, e passa a ter instrumento com
as duas metades — não com uma.

---

## 3. Limiar H3, operacionalizado

O limiar de `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §2 é
**3/3 ligados «sem perda de histórico»**. A operacionalização é *proposta* do
bloco do KAM-100 e fixa-se antes de medir:

| | |
|---|---|
| Amostra de controlo | **20 conversas** indicadas pelo dono, por número |
| Critério | **≥ 95%** das mensagens dos últimos 6 meses presentes, **por contagem** |
| O erro 2593109 | Só conta como êxito **se o dono recusou partilhar** — e essa recusa é uma afirmação da folha do operador, não dos eventos |
| Janela de histórico | 6 meses (CONFIRMADO, `../E1_Meta_WhatsApp.md` §2) |
| Prazo de sincronização | 24 h após o *onboarding*, cada passo executável **uma vez** (CONFIRMADO, idem) |

> **A contagem das 20 conversas de controlo não sai do harness.** Os JSON-lines
> contam as mensagens que o `history` entregou; quantas **deviam** estar lá é
> uma contagem que o dono faz na app dele, conversa a conversa, e que entra pela
> folha do operador. Sem as duas metades não há percentagem — e apresentar a
> primeira sozinha era dar por medido o que não foi.

### 3.1 Amostra exigida

| Requisito | Estado |
|---|---|
| ≥ 1 número Unitel | NÃO MEDIDO |
| ≥ 1 número Africell | NÃO MEDIDO |
| ≥ 1 número fixo, com verificação por voz | NÃO MEDIDO |
| Razão escrita, se algum faltar | — |

Um fixo é o caso que `../E1_Meta_WhatsApp.md` §5 diz ser «não recomendado» para
OTP por SMS, pelo que a verificação tem de ser **por voz**. A entrega de SMS
internacional em Unitel e Africell é **NÃO VERIFICADA** (idem), e é um dos
resultados do spike.

---

## 4. Regra de decisão (fim da semana 3; revista na semana 6)

Transcrita do critério do KAM-100. **A decisão é do fundador**, com dono e data.

| Resultado | Estado de H3 | O que muda no produto |
|---|---|---|
| **3/3** | `confirmada` | Modo `coexistencia` por omissão para o canal |
| **2/3** | `inconclusiva` | Isolar a causa no número que falhou, e `cloud_only` com número novo dedicado **como alternativa por número** |
| **≤ 1/3**, ou exclusão explícita de Angola | `refutada` | Pivô de `../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §6: BSP parceiro, número novo, ou produto sem automação no WhatsApp da PME |

Revisão na semana 6 pela Regra 5 de
`../../../exploracao/14-tese-minima-e-plano-de-validacao.md` §3A. Os dois modos
— `coexistencia` e `cloud_only` — são os de
`../../01_Canais_WhatsApp_Fluxo_Dual.md` §10.1, e a lógica de saída é a mesma nos
dois: só muda o §10.2.

| | |
|---|---|
| Decisão | **NÃO MEDIDO** |
| Dono | |
| Data | |

---

## 5. Privacidade e prazo de apagamento

| Requisito do critério | Como se cumpre | Estado |
|---|---|---|
| Consentimento escrito de cada dono | Arquivado **fora do repositório**, pelo fundador | NÃO MEDIDO |
| Nenhum conteúdo de mensagem armazenado | *Allowlist* de **18** chaves com **forma exacta** por valor, em `spikes/h3/registo.py`; medida por forma de valor em `spikes/h3/tests/test_privacidade.py`, e a contagem presa por ensaio em vez de escrita à mão | **CONFIRMADO** (105 ensaios verdes, ver o PR) |
| Nenhum telefone em claro | Os telefones são **descartados**, não resumidos: um móvel de nove dígitos inverte-se por enumeração (ADR-010, `../../../logs.md` §2.1). No lugar fica o rótulo `N1`–`N3` | **CONFIRMADO** (idem) |
| Registos apagados em ≤ 30 dias | Os JSON-lines, o `rotulos.json` e o `nossos.txt` vivem no portátil do operador e **nunca** entram no repositório | NÃO MEDIDO — o apagamento é acto do operador |
| Sem segredos no repositório | App Secret e `hub.verify_token` entram por ambiente; o receptor **recusa arrancar** sem eles | **CONFIRMADO** |
| Excepção de dados reais de teste declarada em KAM-104 | Devolvido: é do KAM-104 | NÃO MEDIDO |

---

## 6. O que fica devolvido, e a quem

| # | O que | Porque não se fecha aqui | Credor |
|---|---|---|---|
| 1 | **Correr o ES com três donos de número**, obter consentimento escrito, verificar a versão da app e executar os 10 envios | São actos humanos com terceiros. O bloco é explícito: «O operador humano executa o ES com cada dono; a decisão é humana» | **Fundador** |
| 2 | **A resposta ao Passo 0** (§1) | Só a Meta a dá, pela Q3 e Q9 de [`Meta_Perguntas.md`](Meta_Perguntas.md), ou torna-se irrelevante com a aprovação de Tech Provider | **Fundador** (envio) e **KAM-102** (aprovação) |
| 3 | **O prazo novo do spike**, se o Passo 0 vier `Não` | Depende do KAM-102, cujo prazo depende de uma Business Verification sem prazo documentado | **Fundador** |
| 4 | **A contagem das 20 conversas de controlo** por número | Conta-se na app do dono, conversa a conversa. O harness conta o que recebeu, não o que devia receber | **Fundador** |
| 5 | **A decisão H3** e a linha correspondente no [`Registo_Hipoteses.md`](Registo_Hipoteses.md) | Nenhuma decisão é automática (EPIC-10 §1), e esta é do registo de decisões da Carta | **Fundador** |
| 6 | **A nota de entrega a KAM-017 e KAM-018** com os factos medidos | Não há factos medidos para entregar. A nota nasce com o primeiro resultado | **KAM-017**, **KAM-018** |
| 7 | **Ligar a um portão os ensaios do *harness* e os do validador.** Medido: **nem `spikes/` nem `scripts/`** entram em nenhum — não estão nos padrões de `../../../../ci/thresholds.yaml`, não estão no `SUITES_DE_TOOLS` do `Makefile`, que descobre suites por `tools/*/tests/test_*.py`, e não são nomeados no `ci.yaml` | Mudar o que o gate 4 passa a exigir é alteração de regra de bloqueio. Entrega-se a medição, não a implementação. **A diferença entre os dois, que pesa na decisão:** o `spikes/h3/` é descartável, e um artefacto cuja remoção avermelha o gate 4 de todos os PRs deixa de ser descartável; o `scripts/validar_evidencia.py` é **permanente** e é citado nos «Testes Requeridos» de quatro tickets, pelo que o argumento do descartável não se lhe aplica | **Fundador** |
| 8 | **Nove dos onze ficheiros desta pasta não declaram `Estado`, `Fonte` nem `Dono`.** Medido com o validador que este ticket entrega, a 2026-11-06: **27 achados em 9 ficheiros**, exactamente **3 em cada** — `Estado`, `Fonte` e `Dono` em falta nos nove; o `Data` está presente em todos. Só este ficheiro e o [`Registo_Hipoteses.md`](Registo_Hipoteses.md) os declaram | Porque são artefactos de outros tickets, e emendar o cabeçalho de um ficheiro alheio é alargar o escopo deste PR em silêncio — além de que `Estado` e `Dono` são afirmações sobre o conteúdo deles, que o executor do KAM-100 não tem base para fazer. **A primeira medição disto deu 23, e estava errada por defeito do próprio validador:** ele aceitava uma linha de duas células de *qualquer* tabela, pelo que um glossário `\| Estado \| Significado \|` mais abaixo no ficheiro era lido como a declaração e tapava a ausência dela, trocando-a por um falso «quarto estado». Corrigido e re-medido; fica escrito porque um número devolvido a quatro tickets não se emenda em silêncio. Por ficheiro: **KAM-105** nos quatro (`Alojamento_Cotacoes`, `GoLive_Gate`, `Mapa_Tratamentos_v1`, `Seguimento_APD`), **KAM-104** nos três (`Anexo_Factos_do_Caso`, `Pacote_Parecer_Juridico`, `Seleccao_e_Registo_Juridico`), **KAM-126** num e **KAM-101** num | **KAM-104**, **KAM-105**, **KAM-101** e **KAM-126** |

---

## 7. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Fundador (decisão H3) | | | |
| Engenheiro de Plataforma (medição) | | | |
| Responsável de Segurança (privacidade) | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Novembro de 2026 | Emissão inicial, KAM-100. O ficheiro de resultado do spike H3, a nascer **sem medições**: nenhum dos três números foi ligado, porque correr o Embedded Signup com um dono de número é acto humano e o executor não o pode praticar. **O Passo 0 fica `NÃO VERIFICADO`**, com data e fonte, e não `Sim` nem `Não`: o requisito de ser Solution Partner ou Tech Provider é CONFIRMADO (`../E1_Meta_WhatsApp.md` §2), mas **nenhuma** das páginas registadas em E1 §2 ou §3 diz se o modo de desenvolvimento o satisfaz — nem para afirmar nem para negar. Em consequência, o §1.1 registra o estado em vez de um prazo: o spike está bloqueado por **uma pergunta sem resposta** e não por um `Não`, as duas vias de desbloqueio são a Q3/Q9 de [`Meta_Perguntas.md`](Meta_Perguntas.md) (em `por enviar`) e a aprovação do **KAM-102**, e o prazo novo é **NÃO VERIFICADO** porque depende de uma Business Verification cujo prazo a Meta não documenta — escrevê-lo em semanas era inventar o número de que depende o caminho crítico da Fase 0. A elegibilidade de Angola fica **NÃO VERIFICADA** e as fontes secundárias que dizem «global» ficam **INDÍCIO**, herdados de E1 e não promovidos. A tabela N1–N3 do §2 nasce toda em `NÃO MEDIDO` e o §2.1 fixa a **regra do zero**: zero eventos escreve-se `NÃO MEDIDO` e nunca `N`, com uma só excepção — o *echo* da API, que tem prova de ausência. **Os números nunca entram no ficheiro**: as colunas são rótulos `N1`–`N3` e a correspondência vive fora do repositório, que é público. O limiar do §3 está operacionalizado antes de medir, e diz o que o harness **não** mede: a contagem das 20 conversas de controlo faz-se na app do dono. **Oito itens devolvidos no §6**, cada um com credor nomeado — o fundador em cinco, o KAM-102, o KAM-017 e o KAM-018 nos outros, e o item 8 repartido por quatro tickets. O item 8 é uma medição feita **com o validador que este ticket entrega**, e não uma leitura: **27 achados em 9 dos 11 ficheiros** desta pasta, exactamente três em cada, por não declararem `Estado`, `Fonte` nem `Dono`; não se emendaram, porque são artefactos de outros tickets e porque `Estado` e `Dono` são afirmações sobre o conteúdo deles. **A revisão adversarial devolveu 16 achados, os 16 confirmados contra a árvore, e está na** [`ANALISE-52`](../../../analises/ANALISE-52-KAM-100-spike-h3-coexistencia.md). Dois mudaram o que este ficheiro afirma: a **excepção à regra do zero** do §2.1 foi **fechada** — «houve *echoes* e nenhum é nosso» não é prova de ausência sem se saber que houve envio pela API —, e a primeira medição do item 8 dava **23** por defeito do próprio validador, que lia um glossário como declaração e tapava a ausência dela. A tabela do §2 ganha a linha da **entrega do SMS**, que o critério 4 exige e que o gerador não produzia: o operador perdia-a ao regenerar. | Equipa KAMBÁ |
