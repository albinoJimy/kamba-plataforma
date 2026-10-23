# Aviso ao dono por canal alternativo (KAM-115)

| Campo | Valor |
|---|---|
| Ticket | KAM-115 |
| Módulo | `packages/core-ts/src/avisos/` |
| Revisão | `0019_aviso_ao_dono` (descende da `0018`) |
| Depende de | KAM-017 (coexistência: `channel.updated` e `channel.inactivity_warning`), KAM-021 (qualidade: `restrito`), KAM-023 (*free tier*: `motivo_restricao='payment_method'`), KAM-016 (cifra por *tenant*), KAM-116 (SMS, **fora de âmbito**) |
| Bloqueia | — (é o último ticket do EPIC-02) |
| Fonte do desenho | [`tecnica/01_Canais_WhatsApp_Fluxo_Dual.md`](tecnica/01_Canais_WhatsApp_Fluxo_Dual.md) §10.5, §11.4, §14, [`tecnica/10_Onboarding_Governanca.md`](tecnica/10_Onboarding_Governanca.md) §6.4, §13, [`tecnica/evidencia/E1_Meta_WhatsApp.md`](tecnica/evidencia/E1_Meta_WhatsApp.md) §1, §2, [`tecnica/evidencia/E3_Regulatorio_Dados.md`](tecnica/evidencia/E3_Regulatorio_Dados.md) §1, ADR-001, ADR-008, ADR-010 |

## 1. O que o módulo faz

**Avisa o dono pelo canal que não falhou.** Quando o WhatsApp de uma loja cai,
fica restrito ou deixa de entregar, avisar por WhatsApp é inútil — e é essa frase
que é o ticket inteiro. O módulo consome os eventos de falha ou risco que o
KAM-017, o KAM-021 e o KAM-023 já emitiam, e entrega um aviso por **e-mail** e
por **notificação do painel**, com texto próprio por situação, limites de
frequência, lembretes e nenhum dado de clientes.

Fecha a lacuna **R16** do epic: «sem ticket para avisar o dono por canal
alternativo em `PARTNER_REMOVED`, inactividade ou falha de pagamento Meta». Os
emissores existiam; o que não existia era quem entrega.

## 2. As seis decisões de desenho

**São duas tabelas e não uma, e quem o decide é o critério 7.** Ele manda que uma
falha de entrega «marque o **contacto** como inválido»: isso é um facto do
contacto e não do aviso. Com uma tabela só, a invalidação vivia na última linha
de aviso e a pergunta «este dono tem contacto válido?» passava a ser uma consulta
sobre o histórico de envios em vez de um facto. A `owner_contacts` guarda o
endereço, a prova de verificação e a invalidez; a `owner_notices` guarda o
registo de cada aviso — **sem corpo**.

**O gatilho é a *situação* e não o tipo do evento.** São cinco: `canal_desligado`,
`inactividade`, `qualidade_restrita`, `sem_pagamento` e `painel_indisponivel`.
Duas delas chegam pelo mesmo `channel.updated`, e se o gatilho fosse o tipo os
dois casos tinham o mesmo texto — o «cada um com texto próprio e o passo
seguinte» do critério 1 ficava sem sujeito. **Os seis motivos de
`PARTNER_REMOVED` são um gatilho só**, e é decisão: o critério pede que os seis
*gerem* aviso, não que gerem seis textos; o passo é o mesmo nos seis — reconectar
pelo painel — e seis modelos iguais eram seis sítios para a mesma frase divergir.
O motivo vive no `episodio`, que é o que faz um `change_number` depois de um
`primary_inactivity` ser um episódio novo.

**A idempotência e os lembretes vivem na mesma unicidade.** O critério 2 quer «o
mesmo evento 3× produz 1 aviso»; o critério 4 quer «lembretes às 24 h e 72 h se o
estado persiste». A chave é
`owner_notices_idempotencia_uq (tenant_id, chave, lembrete, canal)`, e dela saem
as duas propriedades de uma vez: três entregas do mesmo evento tentam escrever a
mesma linha e o `ON CONFLICT DO NOTHING` deixa uma; um episódio novo tem outra
chave; e o lembrete das 24 h não colide com o aviso de que é lembrete. Com a
unicidade sem o `lembrete`, o critério 2 passava e o critério 4 era **impossível**
— e falhava com `23505` em produção, não em teste.

**O endereço do dono vive cifrado, e não há coluna em claro.** É o DoD
«Privacidade» por extenso. A cifra é a do `onboarding/cifra.ts` do KAM-016
(AES-256-GCM, DEK por *tenant* derivada por HKDF, `kid` dentro do criptograma) e
**não se reescreveu nada**: o que muda é a KEK, a entrada nova
`kek_contacto_dono` do [`../ops/secrets-inventory.yaml`](../ops/secrets-inventory.yaml).
Duas KEK diferentes dão duas DEK diferentes para o mesmo *tenant*, pelo que a
separação de domínio sai da **chave** em vez de sair de uma constante que alguém
pode esquecer de mudar. Não há HMAC de pesquisa, ao contrário do
`contact_endpoints` do KAM-008: lá há pesquisa por valor, aqui entra-se sempre
pelo `tenant_id` — e um HMAC sem quem o consulte era uma chave a mais para rodar.

**O conteúdo é uma lista branca aplicada na construção, não um varrimento
depois.** Os parâmetros são quatro — `loja`, `estado`, `hora`, `painel` — e um
quinto **levanta**. Um varrimento *a posteriori* diz que um aviso leva um
telefone; uma lista fechada faz o telefone não ter por onde entrar. Fazem-se as
duas coisas: a lista, e o varrimento sobre 200 avisos que o critério 5 manda.

**O nome da loja mascara-se, não se recusa.** O `loja` é o que o dono escreveu, e
um dono pode ter escrito lá um telefone — «Loja do Zé 923 456 789» é um nome
plausível em Luanda. Recusar o aviso fazia o dono não saber que o canal caiu por
causa de como ele escreveu o nome da loja, que é castigá-lo por um defeito nosso.
A fronteira é o `DIGITOS_MAXIMOS` do `logger/politica.ts` — **seis** —,
reexportado e não redeclarado, e a régua apanha corridas de sete ou mais dígitos
separadas por espaços, pontos, hífenes e barras, que é como uma pessoa escreve um
telefone à mão.

## 3. A ordem das recusas, e porque é que ela importa

O `decidir` avalia quatro recusas, e a ordem foi medida:

1. **gatilho desconhecido** — o critério 1 («um gatilho fora da lista não envia
   nada»);
2. **lembrete acima do máximo** — o «depois pára» do critério 4;
3. **o mesmo episódio no mesmo lembrete** — o critério 2. Vem **antes** dos
   limites porque não é um limite: um evento re-entregue pela DLQ não deve gastar
   o tecto diário de ninguém. Sem esta ordem, três entregas do mesmo evento
   consumiam o dia todo do dono e os outros gatilhos calavam-se;
4. **a janela de 24 h por gatilho**, e só para o aviso próprio. Um lembrete é,
   por definição, um segundo aviso do mesmo gatilho dentro da janela — e a
   primeira versão filtrava os dois, pelo que **os lembretes nunca saíam**;
5. **o tecto diário de 3**, que conta **avisos distintos** e não linhas: um aviso
   sai pelos dois canais e é um aviso, e contar duas linhas fazia o tecto de três
   valer um e meio.

A janela do gatilho vem **antes** do tecto diário, e a diferença é concreta: com
o tecto primeiro, um *tenant* com três episódios do mesmo gatilho gastava o dia
todo num gatilho só e os outros quatro ficavam sem voz para as 24 h seguintes. É
a diferença entre um dono que sabe que tem três problemas e um dono que sabe três
vezes o mesmo.

## 4. O que a base garante, e não o código

| Propriedade | Onde vive |
|---|---|
| «O mesmo evento 3× produz 1 aviso» | `owner_notices_idempotencia_uq` + `ON CONFLICT DO NOTHING` |
| «Um novo episódio produz outro aviso» | a `chave` deriva do `episodio`, e o `episodio` não pode ser vazio |
| «Depois pára» (lembretes) | `owner_notices_lembrete_ck CHECK (lembrete BETWEEN 0 AND 2)` |
| «Um gatilho fora da lista não envia nada» | `owner_notices_gatilho_ck`, com os cinco valores |
| «Nunca pelo WhatsApp» | `owner_notices_canal_ck`, com dois valores, e um teste de configuração que lê os `import` do módulo |
| «≥ 1 contacto alternativo» | `owner_contacts_canal_uq (tenant_id, canal)` |
| «Sem corpo» | não existe coluna de texto para conteúdo |
| Isolamento de *tenant* | RLS `FORCE` + política `tenant_iso` nas duas tabelas (X-03 no *gate* 6) |

A regra de parar está na base e não só no código porque **é a parte do limite que
protege o dono de nós**: deixá-la no código era deixá-la ao alcance do primeiro
`if` mal escrito.

## 5. O relógio é por fora, e isto custou um defeito

Nenhuma função do módulo chama `Date.now()`: o relógio é a porta `Relogio`, e é
isso que torna os critérios 3 e 4 mensuráveis («medida com relógio acelerado»,
«lembretes às 24 h e 72 h»).

**E o `criado_at` também vem desse relógio, não do `now()` do servidor.** Era
`DEFAULT now()` na primeira versão, e o primeiro ensaio contra a base mostrou o
que isso custava: os dois limites e os lembretes medem-se desse carimbo, e com
ele escrito pelo servidor o relógio acelerado media uma coisa e a base registava
outra — a varredura dos lembretes não via episódio nenhum, porque as linhas
tinham a hora real e a janela tinha a hora do ensaio. É a mesma razão pela qual o
`prazo_em` da `0018` é coluna e não cálculo: «um prazo derivado de `now()` na
consulta não se acelera sem mexer no servidor». O `DEFAULT now()` fica na tabela
para quem insira à mão e para a semente do *gate* 6.

**E a hora que o dono lê sai em `Africa/Luanda`**, que é a omissão de
`tenants.fuso_horario` (revisão `0007`) e o fuso que o `metering/consultas.ts` do
KAM-023 usa para fechar o mês. Em UTC, o aviso dizia a um dono de Luanda que o
canal caiu uma hora antes do que caiu. E sai na forma **longa** — «9 de novembro
de 2026 às 10:00» — e não na curta, por uma razão medida: `09/11/2026` são oito
dígitos separados por barras, e a régua do §2 que apanha telefones escritos à mão
apanharia a data também.

## 6. Não há agendador, e isso é o precedente da casa

Os lembretes das 24 h e das 72 h não têm agendador — não existe nenhum neste
repositório, e nasce com o KAM-071/KAM-078. O que existe é o padrão que o
`abandonarVencidas` do KAM-016, o `pausarPorInactividade` do KAM-018 e as
varreduras do KAM-017 escreveram: **uma função idempotente por predicado SQL, com
o relógio por parâmetro, testável agora e chamável depois**. São três:

* `varrerLembretes` — os episódios cujo lembrete está devido;
* `varrerContactos` — os *tenants* `ativo` sem contacto verificado (critério 6);
* e a leitura dos avisos que ficaram `pendente`, pelo índice parcial.

As três correm **sem `tenant_id` no predicado**, porque um lembrete que venceu
não é problema de uma loja — e por isso só correm com `BYPASSRLS`, que só o
`kamba_batch` tem. Sem a concessão da `0019`, os critérios 4 e 6 não tinham
caminho executável: só decisão escrita. É o achado que a revisão adversarial da
`0018` pagou, aplicado aqui antes de custar.

## 7. As cinco métricas

    owner_notice_sent_total{gatilho,canal}       counter
    owner_notice_latency_s                       histogram
    owner_alt_contact_missing                    gauge
    owner_notice_suppressed_total{gatilho,motivo} counter
    owner_notice_failed_total{canal,motivo}      counter

As três primeiras são as do DoD. As outras duas entram porque **há duas maneiras
opostas de um aviso não chegar ao dono**: nós recusámos (um limite, um gatilho
desconhecido) ou o fornecedor não entregou (um *bounce*, uma rejeição). Sem as
duas séries, um painel vê «o dono não foi avisado» e não distingue a regra a
funcionar do canal alternativo estar quebrado — que é a diferença entre não fazer
nada e acordar alguém. O critério 7 escreve-o: «nenhum aviso se perde em
silêncio».

**É a primeira métrica desta casa com duas etiquetas**, e nenhuma é
identificador: cinco gatilhos × dois canais são dez séries fixas e conhecidas em
tempo de compilação, e o `OBS-I` de
[`seguranca/ameacas_stride.md`](seguranca/ameacas_stride.md) recusa
identificadores, não dimensões pequenas. O `owner_alt_contact_missing` é um
**número** e não uma série por *tenant* — um `tenant_id` é um UUID com hífenes e
**levanta** na validação de etiquetas —, e publica-se com o seu total, porque a
percentagem do critério 6 precisa de denominador.

O corte de **300 s** está nos baldes do histograma por causa do critério 3: o
alvo é «≤ 5 min p95», e um balde exactamente nos 300 segundos faz a pergunta
ler-se sem interpolar entre dois cortes.

## 8. O fornecedor de e-mail é um subprocessador, e bloqueia `prod`

O critério 8 pede que o fornecedor «conste do inventário de subprocessadores
(KAM-069) com `apd_ref`, ou fique `pendente` e **bloqueie `prod`**». O inventário
não existe — nasce com o KAM-069 —, e inventá-lo aqui era construir por outro
ticket. O que está entregue é a alternativa que o próprio critério escreve: o
`fornecedor.ts` lê a declaração do ambiente e, em `prod`, com o fornecedor fora
de Angola ou por escolher e sem `apd_ref`, **o serviço não arranca**.

É a forma do `storage/config.ts` do KAM-011, e de propósito: os três campos têm os
nomes de `tenant_destinations(provider, country, apd_ref)` do
[`tecnica/08`](tecnica/08_Seguranca_Conformidade.md) §8.3.1, porque é essa a
tabela que o KAM-069 vai confrontar com isto. Um segundo vocabulário para a mesma
ideia dava duas tabelas a reconciliar no dia em que o inventário existisse.

**Qual é o fornecedor não se decide aqui**, e não é omissão: escolher um
subprocessador num ficheiro de código é exactamente o que o ADR-008 existe para
impedir. O valor por omissão é `pendente`, e `pendente` em `prod` é um arranque
recusado.

O que é um dado pessoal neste ticket: o aviso leva o **endereço de e-mail do
dono** — uma pessoa singular — para fora da nossa infra-estrutura, e o fornecedor
guarda-o em registos de entrega. É transferência no sentido do ADR-008, e é por
isso que o critério a trata como trata o armazenamento de mídia.

## 9. O que fica por marcar, e porquê

**O alvo de «≥ 95% dos *tenants* `ativo` com contacto verificado»** (critério 6)
é uma medição sobre *tenants* reais, e não há nenhum. A métrica que o mede está
entregue, com numerador e denominador; a varredura que a alimenta também; o
número sai no Piloto. Afirmar a percentagem contra dois *tenants* de ensaio era
afirmar 100% de nada.

O resto do que o ticket não faz é escopo de outros, e os próprios *Fora de
âmbito* dizem-no: o adaptador **SMS** (KAM-116 — e o `sms` **não** está
pré-declarado em domínio nenhum, porque um nome sem superfície é o que o *gate*
3b recusa), o **número operacional da KAMBÁ** (D10, KAM-101 — e o ticket manda
explicitamente não o assumir), a **captação do e-mail** e a entrega da ligação de
confirmação (KAM-086), a **base legal** e a finalidade do contacto do dono
(KAM-104), os ***runbooks*** (KAM-083) e os **avisos de cobrança** (KAM-058).

E a fila humana do T2 é uma **porta**: não existe mecanismo de *ticket* neste
repositório — dívida **73**, escrita pelo KAM-021 —, e inventar um a partir de um
critério deste ticket era alargar o escopo em silêncio. O que o módulo garante é
que **chama**, e há teste da chamada.

## 10. Os defeitos que uma máquina apanhou

**O primeiro foi o relógio, e foi o ensaio contra a base.** A varredura dos
lembretes não encontrava episódio nenhum: as linhas tinham `criado_at` do
servidor e a janela tinha a hora acelerada do ensaio. A correcção é a §5, e é de
desenho e não de teste — em produção os dois relógios coincidem, pelo que isto
nunca apareceria antes do Piloto.

**O segundo foi o `after` do ensaio, e pendurou o processo.** O `apagarTenant` do
`tests_bd/apoio.ts` não conhecia as duas tabelas novas, pelo que o `DELETE` do
*tenant* rebentava com `23503` **depois** de os testes passarem — e o `after` que
fecha as ligações nunca chegava ao fim, pelo que o `node --test` não acabava.
Trezentos segundos de silêncio, sem uma linha de saída. O lançador desta *suite*
passou a devolver a saída parcial quando o tempo estoura, porque um ensaio
pendurado sem saída não se investiga.

**O terceiro foram quatro testes meus a passar pela razão errada, e foi a prova
por mutação.** Cada caso negativo precisa do seu `SAVEPOINT`: um erro aborta a
transacção inteira no PostgreSQL, pelo que a segunda assercão negativa do mesmo
teste respondia `25P02` («in_failed_sql_transaction») e não o `23514` que se
esperava. O `ComBase.assertErroSql` já existia e faz exactamente isto — e a mesma
corrida mostrou que um cursor do `pg8000` **não é gestor de contexto**, o que
fazia o teste do `downgrade` levantar `TypeError` antes de afirmar o que fosse. A
bateria de esquema **nunca tinha corrido**: o *gate* 8 correu antes de ela
existir, e a prova por mutação foi a primeira coisa a executá-la.

## 11. A revisão adversarial: quatro achados, e dois tornavam critérios inexecutáveis

1. **Os lembretes nunca saíam.** A janela de 24 h por gatilho filtrava **todos**
   os avisos desse gatilho, e um lembrete é por definição um segundo aviso do
   mesmo gatilho dentro da janela. O critério 4 manda enviá-lo, e a regra
   recusava-o. O teste que afirmava o contrário media o lembrete das 24 h num
   histórico **vazio**, onde a janela não tem nada para recusar: passava, e não
   provava nada. A correcção é o `lembrete === 0` no predicado da janela, e o
   teste afirma agora as duas coisas no mesmo instante.
2. **O «depois pára e abre tarefa a T2» não tinha caminho.** A varredura tinha
   um `if (devido > LEMBRETE_MAXIMO)` que **nunca podia ser verdade** — o
   `lembreteDevido` não devolve mais do que o número de atrasos —, pelo que a
   regra era código morto. E o `lembretesEsgotados`, que responde exactamente a
   essa pergunta, existia, estava testado e **não era chamado por ninguém**. A
   correcção tem duas metades: a varredura passa a perguntar-lhe, e o `HAVING`
   da consulta passa de `<` para `<=`, porque com `<` o episódio esgotado
   **desaparecia** da varredura e não havia nada para reconhecer. É a mesma
   classe de achado que a revisão adversarial da `0018` encontrou nas concessões
   ao `kamba_batch`, e a mesma lição que o KAM-018 escreveu: «uma guarda
   inalcançável dá a ilusão de proteger».
3. **O tecto diário contava linhas.** Um aviso sai pelos dois canais e escreve
   duas linhas; com a contagem por linha, o tecto de três valia um e meio e um
   dono com três problemas sabia de um. Passou a contar `(gatilho, episodio,
   lembrete)` distintos.
4. **A hora saía em UTC a um dono de Luanda.** E a correcção trouxe uma
   propriedade a mais: a forma **longa** de `pt-PT` («9 de novembro de 2026 às
   10:00») não tem nenhuma corrida de sete dígitos, ao contrário da curta
   (`09/11/2026`, oito dígitos separados por barras — que a régua do §2
   apanharia). O varrimento do critério 5 passou a correr sobre o aviso
   **inteiro**, sem excepção nenhuma, e um varrimento sem excepções é mais forte
   do que um com.

E a linha de `sem_contacto` passou a entrar no resultado devolvido: ela **foi
escrita**, e o campo está documentado como «as linhas escritas» — descartá-la
fazia o resultado dizer que nada se escreveu num caminho que escreve.

## 12. O que a prova por mutação mostrou: oito lacunas nos meus testes

As 79 mutações deste ticket correram com o código já congelado, e **oito
sobreviveram**. Nenhuma era um falso positivo. O inventário está na secção de
verificação do bloco do ticket, e o resumo é este: dois testes mediam a fronteira
**com a própria constante**, pelo que eram verdadeiros para qualquer valor dela;
dois construíam uma colisão ou um cenário que **não podia falhar**; dois viviam
só na base falsa, que implementa o seu próprio predicado e não o do SQL; um
guardava um ramo **inalcançável** — e a resposta foi apagar a guarda, como o
KAM-018 fez; e um apontava para um caminho que **só a concorrência alcança**, o
`registado === null`, que em série o `decidir` tapa antes.

O mais útil dos oito foi o que apagou o predicado `lembrete === 0` — a própria
correcção da revisão adversarial. O teste que o afirmava media o lembrete das
24 h com o aviso em `T0`, onde a janela já tinha expirado: passava nos dois
sentidos. Uma correcção sem um teste que a prenda é uma correcção que a próxima
pessoa desfaz.

## Controlo de versões

| Versão | Data | Descrição | Autor |
|---|---|---|---|
| 1.0 | Outubro 2026 | Primeira versão, KAM-115. A revisão `0019` (duas tabelas), o `AvisoAoDono` com os cinco gatilhos, a idempotência e os lembretes na mesma unicidade, a lista branca de modelos, o *gate* de `prod` do subprocessador e as cinco métricas. Fecha a lacuna R16 e o EPIC-02. Uma caixa fica por marcar — o alvo de ≥ 95%, que é medição sobre *tenants* reais. | Equipa KAMBÁ |
