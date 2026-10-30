# Anexo «factos do caso» — KAMBÁ

| Campo | Valor |
|---|---|
| Produto | KAMBÁ (nome de trabalho) — plataforma WhatsApp-native de comércio conversacional para Angola |
| Documento | Anexo de factos do caso, para acompanhar o pedido de parecer jurídico |
| Versão | 1.0 |
| Data | Outubro de 2026 |
| Classificação | Destinado a transmissão a advogado sob compromisso de confidencialidade |
| Ticket | KAM-104 (EPIC-10) |
| Pacote que acompanha | [`Pacote_Parecer_Juridico.md`](Pacote_Parecer_Juridico.md) — as 40 perguntas |
| Gerado a partir de | `../../00_Arquitectura_Solucao.md` e `../../01` a `../../10` |
| Extensão | **Não demonstrada em páginas, e a razão está dita.** Linhas de tabela a uma linha e prosa a 95 caracteres por linha: **251** linhas se o espaçamento entre parágrafos não ocupar linha, **311** se ocupar — ou seja **5,2 a 6,8 páginas** entre as densidades de 48 e 46 linhas por página (A4, 11 pt). Nenhum conversor correu nesta máquina, pelo que **nenhuma página foi medida**; quem tiver um renderizador fecha a conta numa passagem. Ver o critério 3 do KAM-104, cuja caixa fica vazia por isto |

> **Descritivo, sem dados pessoais, e sem leitura jurídica da KAMBÁ.** Cada
> afirmação que toca a Lei 22/11, a APD, o BNA, a AGT, a defesa do consumidor ou
> os Termos da Meta aparece **com o estado de verificação** com que foi lida na
> evidência da KAMBÁ, ou **com a marca *(a confirmar por parecer)*** quando é
> conclusão nossa sem fonte que a sustente — e não de outra forma. **CONFIRMADO**,
> **INDÍCIO** e **NÃO VERIFICADO** têm o sentido da evidência de pesquisa da
> KAMBÁ, de 8 de Outubro de 2026, e **não são promovidos** aqui. Os textos de
> lei que a KAMBÁ leu vieram de repositórios não oficiais: **verificar no Diário
> da República**. Os fornecedores aparecem pela função que desempenham.

---

## 1. Identificação e estado

| Facto | Valor |
|---|---|
| Natureza | Software que permite a PMEs angolanas vender por conversa no WhatsApp, com assistente automático assente em modelos de linguagem |
| Fase | Fase 0 / Fase 1 (Piloto). **Não está em produção** |
| Dimensão do Piloto | 5 a 10 PMEs; equipa pequena |
| Dados reais hoje | **Nenhum.** Desenvolvimento e pré-produção com dados sintéticos; produção com dados reais depende da decisão de alojamento (D1) e do procedimento junto da APD |
| Canal | WhatsApp Business Platform (API oficial da Meta); gateways não oficiais proibidos por decisão de arquitectura |
| Modelo do Piloto | A PME usa o **seu próprio número**. Um número agregador a falar por várias lojas está **diferido** |
| Receita | **Assinatura** fixa, facturada à PME. Comissão sobre transacção **desligada** até haver parecer |
| Posse de fundos | **Nenhuma.** A plataforma nunca está no caminho do dinheiro das vendas |

---

## 2. Fluxos de dados

**Entrada.** Meta → *gateway* → fila → trabalhador de canal → base de dados →
resolutor de canal e contacto. O pedido é autenticado por dispersão com chave
sobre o corpo bruto, **antes** da desserialização; falha devolve 401
(CONFIRMADO). A Meta re-entrega até 7 dias, sem ordem garantida (CONFIRMADO).
Entram texto, notas de voz, fotografias, localização partilhada pelo cliente e o
identificador do cliente.

**Identificador do cliente.** Atribuído pela Meta, **único por par
portfólio-utilizador**; o telefone é opcional e pode não vir no evento. Duas
consequências: o telefone **não é chave** em nenhuma tabela de negócio, e o
mesmo cliente tem identificadores diferentes em PMEs diferentes — **não existe
identidade de cliente global derivável do canal**.

**Identidade em duas camadas.** As tabelas de negócio só contêm um identificador
**aleatório**, sem significado. Um cofre separado é a **única** ponte para o
identificador real: guarda uma dispersão do telefone (nunca o telefone em claro)
e, em tabela própria, o identificador da Meta e o telefone **cifrados** com uma
chave de dados por contacto. Anular essa chave torna os dados ilegíveis
**incluindo nas cópias de segurança**. Para analítica usa-se um pseudónimo
derivado com chave **mensal**, destruída ao fim da retenção: dentro do mês
contam-se clientes distintos, entre meses não há ligação.

> **Limite declarado.** O espaço de números móveis angolanos é pequeno (da ordem
> de 10^8), pelo que uma dispersão do telefone **sem segredo, ou com o segredo
> comprometido, é reversível por enumeração**. O resultado é
> **pseudonimização, não anonimização** — continua dado pessoal *(a confirmar
> por parecer)*. Pergunta A-12.

**Assistente e modelos.** Todas as chamadas passam por um proxy interno único,
com rede de saída restrita a fornecedores aprovados e chave virtual por PME com
orçamento. Antes de cada chamada:

```text
detector (telefone, NIF, e-mail, morada, nomes)
  → tokenização (PESSOA_1, MORADA_1, guardados no estado local)
  → gate «este destino está autorizado para esta PME?» → não: falha fechada
  → modelo → re-identificação só dentro da região aprovada
```

> **Limite declarado.** Nomes próprios em texto livre e referências a locais
> escapam às expressões regulares; a minimização **reduz** a exposição mas **não
> prova** que deixou de haver transferência *(a confirmar por parecer)*.
> Pergunta A-02.

**Treino.** Conversas **não** são usadas para treinar nem afinar modelos; os
contratos com fornecedores exigem retenção zero e não-treino. A razão invocada é
a cláusula dos Termos da Meta sobre aprendizagem automática, cujo texto a KAMBÁ
leu por extracção automática e pede que seja confirmado (pergunta D-01). Por
isso o conjunto de casos para avaliar o sistema admite três origens — sintética,
anonimizada e real **com registo de consentimento por caso**, sem o qual nenhum
caso real entra (KAM-040). Se os Termos permitem as duas últimas é a pergunta
F-03.

**Voz.** Nota de voz → transcrição por fornecedor no estrangeiro → o áudio é
apagado (proposta: ≤ 24 h, limite de erro 72 h). Áudio bruto não sai sem o
*gate* de destino. A voz identifica a pessoa, pelo que a transcrição fora de
Angola é tratada como transferência; sem procedimento APD concluído, **a voz não
entra em produção com dados reais**.

**Catálogo e encomenda.** A fotografia do dono da loja perde os metadados de
imagem, incluindo localização, à entrada, e rostos e matrículas detectados não
são enviados a fornecedores sem base legal. As mensagens relevantes à formação
do contrato ficam com resumo criptográfico e carimbo temporal.

**Analítica.** Sem dados pessoais directos em eventos: o pseudónimo é admitido;
telefone, identificador da Meta, nome, morada e texto não. Finalidade declarada
em cada evento e em cada subscrição; os esquemas são fechados e um teste
automático recusa nomes de campo como `telefone`, `nome` ou `morada` fora de uma
lista aprovada. Localização em analítica: célula de cerca de 1 km e bairro,
**nunca** coordenadas exactas. Na entrega (fase posterior, fora do Piloto) o
pino e a morada do consumidor e a posição do estafeta são dados pessoais *(a
confirmar por parecer)*, e **o estafeta não recebe o telefone do consumidor**.

---

## 3. Classes de dados

| Classe | Exemplos | Retenção proposta |
|---|---|---|
| Identificadores de contacto | Identificador da Meta, telefone quando existe, dispersão do contacto | Relação mais prazo de prova |
| Telemetria e dados da PME | Registos e métricas; NIF e alvará da PME | Registos 30 dias; PME: relação mais prazo fiscal |
| Conteúdo de conversa | Texto, transcrições, localização | 90 dias após o fecho; até 12 meses com justificação da PME |
| Áudio e fotografias | Notas de voz, fotografias de produto | Áudio ≤ 24 h após transcrição; fotografias: vida do catálogo |
| Encomendas e pagamentos | Itens, valor, referência | Prazo fiscal — **parâmetro sem valor, por o prazo ser NÃO VERIFICADO** |
| Consentimentos | Finalidade, versão, hora | Prova pelo prazo da relação mais prescrição |

Todas as classes são cifradas em repouso; as colunas com identificadores
directos são cifradas individualmente.

**Categorias especiais.** Ao detectar indicação de saúde, religião, convicções
políticas ou vida sexual, o sistema **não persiste nem envia ao modelo**,
responde de forma neutra e passa a humano — até haver autorização da APD
(pergunta A-04). Medicamentos e dispositivos médicos estão **excluídos** do
Piloto por dupla razão: a política da Meta proíbe a categoria, e os dados de
compra seriam dados de saúde.

---

## 4. Inventário de subprocessadores

Estado: **Piloto; países a confirmar contratualmente.**

| Subprocessador | Função | Dados pessoais | Destino (hipótese) | Procedimento |
|---|---|---|---|---|
| Meta (WhatsApp) | Canal | Conteúdo, telefone ou identificador | EUA/UE (NÃO VERIFICADO) | Notificação separada? — pergunta A-11 |
| Fornecedor de modelo e transcrição | Modelo, transcrição | Texto minimizado, áudio | EUA | A tratar; retenção zero a confirmar |
| Dois outros fornecedores de modelo | Modelo de linguagem | Texto minimizado | EUA/UE e EUA | Idem |
| Fornecedor de transcrição | Transcrição | Áudio | EUA | Idem; preferir transcrever em destino já autorizado |
| Alojamento (Luanda ou JNB/CPT) | Computação, base de dados, cópias | Todos | Angola ou África do Sul | Decisão **D1** |
| CDN e firewall aplicacional | **Termina TLS, vê tráfego em claro** | Conteúdo em trânsito | Global | **Lacuna** — pergunta E-04 |
| Facilitador de pagamentos | Pagamentos | Valor, referência, telefone do pagamento | Angola | Contrato por decidir |
| Software de facturação certificado | Facturas | Dados do cliente na factura | Angola (a confirmar) | Por decidir |
| Cofre de segredos | Segredos | **Nenhum, por regra** | EUA | Sem dados pessoais |
| Correio ou SMS transaccional | Notificações | Contacto | A decidir | A decidir |
| Fornecedor de melhoramento de imagem | Imagem de catálogo | Fotografias do dono | Estrangeiro, por decidir | **Sem linha no inventário — lacuna** |

> **Duas lacunas que a KAMBÁ assinala por sua iniciativa**, por terem de ser
> corrigidas antes de o inventário ir para a APD:
>
> 1. **O CDN e firewall termina TLS**, logo vê o corpo dos pedidos em claro,
>    incluindo o dos eventos da Meta. Esse é o facto técnico; **se o torna
>    subprocessador com acesso a conteúdo é o que a pergunta E-04 pede**
>    *(a confirmar por parecer)*. Há duas opções e **nenhuma está decidida**: (a) assumi-lo como
>    subprocessador e incluí-lo na notificação; (b) **não** pôr o caminho dos
>    eventos atrás do proxy — a assinatura da Meta já autentica o pedido.
>    Pergunta E-04.
> 2. **O fornecedor de imagem não tem linha no inventário**, apesar de a
>    documentação de desenho o tratar como subprocessador no estrangeiro. É
>    incoerência interna, não pergunta jurídica, e está aqui para que o
>    inventário que o parecer apreciar seja o inventário real.

**Gate de transferência.** Configuração por PME e por destino — PME, fornecedor,
país, finalidade, referência da autorização da APD e estado — e por defeito
**negado**: sem linha autorizada, a chamada falha fechada. Aplica-se a
fornecedores de modelo e transcrição, alojamento e cópias de segurança fora de
Angola, CDN, observação, e correio ou SMS, com evidência arquivada por destino.

**Limites da leitura da KAMBÁ.** Não há lista pública de países adequados
(**NÃO VERIFICADO**); a União Europeia e a África do Sul são **hipóteses**
(INDÍCIO) e os EUA **provavelmente** exigem autorização (INDÍCIO); as
cláusulas-tipo oficiais da APD **não foram encontradas** (NÃO VERIFICADO), e a
KAMBÁ **não** assume as da União Europeia. Alojar em Joanesburgo ou na Cidade do
Cabo é **também** transferência (INDÍCIO), e **alojar em Luanda não dispensa o
procedimento**, porque os modelos, a transcrição e a própria Meta seriam
transferências — **INDÍCIO** também, pela mesma inferência, e é o que a pergunta
A-02 pede *(a confirmar por parecer)*. A premissa de que «Luanda não dispensa
nada», que é o fundamento de **D1**, vale o que valer essa inferência.

---

## 5. Retenção proposta

Prazos **propostos** pela engenharia; os legais estão por confirmar — o critério
da lei é o «período necessário às finalidades», e o prazo fiscal é
**NÃO VERIFICADO**.

| Classe | Prazo proposto | Mecanismo |
|---|---|---|
| Conteúdo de conversa | 90 dias após o fecho; até 12 meses com justificação | Trabalho agendado, com registo da eliminação |
| Áudio | ≤ 24 h após transcrição (máximo 72 h) | Expiração no armazenamento mais trabalho agendado |
| Transcrições e consultas ao assistente | Pseudonimizadas, 12 meses; o texto em tabela separada, 90 dias | Remoção de partição mensal |
| Consentimentos e prova de contrato | Relação mais prazo de prova (**a confirmar**) | Trabalho agendado |
| Encomendas e eventos de pagamento | **Prazo fiscal, sem valor até confirmação** | Tabelas separadas do histórico de conversa |
| Registo de auditoria | Não inferior ao prazo fiscal para dinheiro; 12 meses para acessos | Apenas acrescenta; arquivo |
| Registos técnicos e diagnóstico de modelos | 30 dias | Rotação |
| Cópias de segurança | Escrita antecipada 7 dias, mais diárias de 35 dias | **Não se reescrevem**; o registo de eliminações é reaplicado após restauro |

**PME que encerra:** exportação ao responsável e eliminação, excepto o que a lei
fiscal exigir, em 30 dias. **Pedido do titular:** prazo interno de 30 dias (a lei
admite até 60 dias úteis para rectificar ou eliminar — INDÍCIO). O **prazo de
conservação fiscal é NÃO VERIFICADO** onde quer que apareça e é o **único
parâmetro de retenção sem valor** em todo o desenho: os dados fiscais ficam em
tabelas separadas, fora do histórico de conversa — apagar uma conversa **não**
apaga o registo fiscal —, e até haver confirmação **nenhum registo fiscal é
eliminado** (pergunta C-05).

> **Conflito que a KAMBÁ quer ver apreciado.** O registo de pagamentos **apenas
> acrescenta**, por auditoria, prevenção de fraude e retenção fiscal; a lei
> reconhece eliminação e minimização. Resolução desenhada, *a confirmar por
> parecer*: o registo **não contém dado pessoal directo**, só um identificador
> aleatório, e apagar a linha do cofre de identidade torna esse identificador um
> **órfão irreversível**, permanecendo o registo ao abrigo de obrigação legal.
> Para o conteúdo pessoal cifrado, apagar a chave do contacto torna-o ilegível,
> incluindo nas cópias de segurança.

---

## 6. Papéis

> Por defeito cada PME é **responsável pelo tratamento** e a KAMBÁ é
> **subcontratada**, com contrato de subcontratação como pré-condição do
> onboarding. A KAMBÁ **tornar-se-ia co-responsável** nos tratamentos em que
> decide finalidades e meios — o sinal de procura agregado e um índice de
> reputação comercial. **Como a APD qualifica plataformas de software como
> serviço é NÃO VERIFICADO**, e quem notifica ou pede autorização está por
> decidir. Até haver parecer, **as finalidades próprias da KAMBÁ ficam
> desligadas por defeito no Piloto.** É a pergunta A-01, a primeira do pacote.

**Base legal por finalidade: é uma lacuna, e a KAMBÁ declara-a.** O registo de
consentimento admite dez finalidades. Dessas, **só uma — marketing — tem fonte
legal directa e CONFIRMADA** (o artigo da Lei 22/11 sobre marketing
electrónico, cuja aplicação ao WhatsApp é a pergunta A-07); duas apoiam-se numa
implicação a partir da base «execução de contrato», uma no artigo vizinho sobre
comunicação de dados pelo subcontratado (INDÍCIO), e **seis não têm nenhuma
linha na evidência** — atendimento, analítica agregada, sugestões patrocinadas,
partilha com a loja, partilha com o estafeta e notificação ao dono. As de maior
risco são as sugestões patrocinadas e as duas partilhas com terceiros. **Fixar a
base legal de cada uma é objecto deste pedido.**

**Aviso de privacidade.** A primeira resposta com dados deve identificar a loja
como responsável, declarar que é um assistente automático, resumir as
finalidades, nomear os destinatários e os seus países, enunciar os direitos e
ligar ao aviso completo versionado. **O texto ainda não existe**: a tabela de
textos nasce vazia e o controlo falha fechada, pelo que sem aviso publicado o
assistente não corre. O texto espera por este parecer.

---

## 7. Arquitectura de pagamentos

**Princípio.** Facilitador técnico; **liquidação sempre directa à PME**; a
plataforma **nunca detém fundos**. Receber-e-repassar, retenção até entrega e
pagamentos a terceiros só através de prestador licenciado e **fora** do Piloto.

```text
Cliente --(Kz: ATM, homebanking ou aplicação móvel)--> rede interbancária
rede interbancária --(liquidação directa)--> Banco da PME --> Conta da PME
Facilitador ...(só notifica e concilia, sem posse de fundos)...> KAMBÁ
Conta da PME --(assinatura mensal, por referência)--> Conta própria da KAMBÁ
```

As credenciais junto da entidade de serviços interbancários são **do
comerciante**, não da plataforma: não existe conta da plataforma no fluxo das
vendas. A única cobrança que a KAMBÁ recebe é a sua própria assinatura, como
comerciante.

**Meios previstos.** Referência paga em ATM, homebanking ou aplicação (**sem
devolução automática**); pedido de pagamento aprovado pelo cliente na **sua
própria** aplicação, nunca com credenciais na plataforma; carteira de operador
móvel via facilitador (INDÍCIO); débito directo só para a assinatura e só em
fase posterior; e, no arranque, confirmação humana auditada com limite de valor.
**Pagamento contra entrega em numerário não existe.** O pagamento só se dá por
confirmado por **evento autenticado** do facilitador — uma imagem de
comprovativo **nunca** é prova, porque a fraude de comprovativos está
documentada na evidência de pesquisa.

**Seis barreiras técnicas** que tornam o desenho verificável e não apenas
declarado, cada uma com o que impede e a razão invocada *(a confirmar por
parecer)*:

| # | Barreira e mecanismo | Razão invocada |
|---|---|---|
| 1 | Beneficiário é sempre a PME: validação na base de dados de que a conta de recebimento pertence à mesma PME, e uma conta nunca é partilhada | Receber e repassar aproximar-se-ia de sub-adquirente |
| 2 | Sem pagamentos a terceiros nem reembolsos automáticos: capacidade declarada indisponível, a chamada devolve «não suportado», bandeira fail-closed, e exigiria adaptador marcado como licenciado | Seria execução de operações de pagamento |
| 3 | Sem saldos nem carteira: não existe noção de saldo, e os relatórios «a receber pela PME» são informativos e rotulados | A moeda electrónica exige prestador licenciado |
| 4 | Sem contas da KAMBÁ como beneficiárias de vendas e sem retenção até entrega: verificação na integração contínua e no arranque; não existe estado «retido» | Retenção equivaleria a deter fundos de utilizadores |
| 5 | Sem iniciação a partir da conta do cliente: fora do catálogo de adaptadores; o pedido é aprovado pelo cliente na sua aplicação | Poderia ser iniciação de pagamento, actividade regulada. **É a pergunta B-02** |
| 6 | Reembolso como processo manual, executado pela PME a partir da conta dela | As referências não têm devolução automática |

**Comissão sobre transacção: desligada.** No Piloto a receita é a assinatura. A
comissão existe apenas como acumulação em **modo sombra**, calculada a partir do
evento de pagamento confirmado para medir atribuição e economia unitária, **sem
facturar**. Activá-la exige parecer. Se alguma vez for activada, será sempre
**facturada à PME** no ciclo seguinte e **nunca retida na liquidação** — porque
a plataforma não detém fundos e portanto não pode deduzir nada.

**Uma PME sem NIF** não consegue conta bancária colectiva nem contrato com a
entidade de serviços interbancários, pelo que fica fora do pagamento integrado.
É relevante porque parte do comércio-alvo é informal.

---

## 8. O que ainda não existe

Para que o parecer saiba o que **não** pode apreciar. Não existe: **mapa de
tratamentos** (desenhado como pré-requisito — as §3, §4 e §5 deste anexo são a
matéria-prima, não o produto); **contrato de subcontratação** redigido;
**avaliação de impacto** completa (esqueleto de duas linhas); **texto do aviso
de privacidade**; **base legal de seis das dez finalidades**; **parecer sobre o
enquadramento no sistema de pagamentos**; **resposta escrita da Meta** sobre a
classificação do caso de uso e o número agregador, que não é matéria deste
parecer mas condiciona o produto; **lista de países adequados e cláusulas-tipo
da APD**; e **validação da certificação** do parceiro de facturação.

---

## 9. Ausência de dados pessoais

Varredura automática **deste anexo e do pacote que ele acompanha** — que são os
dois ficheiros que saem da casa: zero números de telefone, zero NIF com valor,
zero endereços de correio electrónico, zero nomes de pessoas e zero moradas
concretas. **A varredura não se estende aos documentos de origem, e a primeira
versão desta secção dizia que sim, o que era falso:** a evidência de pesquisa
interna da KAMBÁ contém pelo menos um número de telefone público real, e é
precisamente por isso que este anexo foi redigido e não copiado. Se o parecer
precisar de um exemplo concreto, pede-se que o **solicite**, em vez de a KAMBÁ o
antecipar.

---

## 10. Tabela de aprovação

| Papel | Nome | Data | Assinatura |
|---|---|---|---|
| Responsável de Segurança (privacidade) | | | |
| Arquitecto de Plataforma | | | |
| Fundador | | | |

---

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Emissão inicial, KAM-104. Factos do caso gerados a partir de `../../00` a `../../10`: fluxos de dados, identidade em duas camadas, classes de dados, inventário de subprocessadores com as duas lacunas assinaladas, retenção proposta, papéis e a lacuna da base legal de seis finalidades, arquitectura de pagamentos com as seis barreiras técnicas, alojamento e cópias de segurança, facturação, e o que ainda não existe. Sem dados pessoais neste anexo e no pacote, verificado por varredura dos dois. Nomes de fornecedores substituídos pela função. | Equipa KAMBÁ |
