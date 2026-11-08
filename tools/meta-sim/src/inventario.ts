/**
 * O inventário de números de **forma** real, e porque é que o critério 7 não se
 * cumpre sem ele (KAM-024).
 *
 * O critério pede «o repositório fica com 0 telefones reais (scan)». Corri o
 * *scan* sobre o repositório antes de escrever isto: **89 ocorrências em 24
 * ficheiros**. Nenhuma é um descuido. Todas são *fixtures* de redacção de PII —
 * `tools/log_policy`, `tools/contract_diff`, `packages/core-ts/src/eventos/pii`,
 * os dois *loggers*, as suites de `evt_emitir` — e existem para que o detector
 * **dispare**.
 *
 * Isso obriga a ler o critério com cuidado, porque as duas leituras dão
 * respostas opostas:
 *
 * - «0 cadeias com a forma de um número angolano» é **insatisfazível**, e
 *   satisfazê-la destruía o que vale mais: um redactor testado só com números
 *   do `999` nunca prova que apanha um `+244 9…`, que é precisamente o que
 *   existe para apanhar. A caixa ficava marcada e a protecção ficava pior;
 * - «0 números que pertençam a uma pessoa real» é o que o DoD quer dizer
 *   («0 telefones reais **ou dados pessoais**; capturas saneadas»), e é
 *   verificável — mas não por expressão regular, porque nenhuma expressão
 *   distingue um número atribuído de um sequencial.
 *
 * ## O que torna a segunda leitura verificável: um raquete, não uma isenção
 *
 * A tentação é isentar `tests/`. É exactamente o que a skill desta casa nomeia
 * como cumprir em espírito e não à letra — «um canário numa *fixture* falha o PR»
 * não está cumprido se a pasta do canário for uma área permitida. Uma pasta
 * isenta cresce em silêncio, e no dia em que alguém colar uma captura real num
 * teste o *scan* fica verde.
 *
 * O inventário é o contrário disso, e a diferença está em três propriedades:
 *
 * 1. **Conta.** Cada entrada diz quantas ocorrências aquele ficheiro tem. Uma a
 *    mais falha, **mesmo num ficheiro já inventariado** — que é o caso que a
 *    pasta isenta deixava passar.
 * 2. **Explica.** Cada entrada diz porquê, e a razão tem de nomear o que o
 *    número está a testar. Uma entrada sem razão é um defeito do inventário.
 * 3. **Não fica para trás.** Uma entrada que já não corresponde — o ficheiro
 *    perdeu o número, ou desapareceu — também falha. Um inventário com entradas
 *    mortas é um inventário que ninguém releu.
 *
 * Um ficheiro fora do inventário com uma só ocorrência falha o *scan*. É isso
 * que o torna uma salvaguarda, e é a razão por que a caixa do critério 7 se
 * pode marcar com esta leitura escrita por extenso ao lado.
 *
 * ## Porque é TypeScript e não YAML
 *
 * Porque o `numeros.ts` já explica porque é que este pacote não traz um quarto
 * leitor de YAML ao repositório, e porque uma lista com razões em prosa lê-se
 * melhor com os comentários onde eles pertencem.
 */

/** Uma entrada do inventário. */
export interface Entrada {
  /** O caminho, relativo à raiz do repositório, com `/`. */
  readonly ficheiro: string;
  /** Quantas ocorrências aquele ficheiro tem. Exacto, não um tecto. */
  readonly ocorrencias: number;
  /** O que o número está a testar. Sem isto a entrada é um defeito. */
  readonly razao: string;
}

/**
 * Os ficheiros que levam números de forma real, medidos em 2026-10-20 com
 * `meta-sim varrer`.
 *
 * As contagens **não foram escritas à mão**: saíram do próprio *scan*. Quem
 * mexer num destes ficheiros corre `meta-sim varrer` e actualiza o número, que
 * é a única maneira de a contagem continuar a querer dizer algo.
 */
export const INVENTARIO: readonly Entrada[] = [
  // --- Os detectores de PII, que têm de disparar ---------------------------
  {
    ficheiro: "packages/core-ts/src/eventos/pii.ts",
    ocorrencias: 1,
    razao:
      "o exemplo na docstring do padrao que o guarda de platform.evt_emitir usa; " +
      "um exemplo que nao casasse o proprio padrao enganava quem o lesse",
  },
  {
    ficheiro: "packages/core-ts/src/identity/cripto.ts",
    ocorrencias: 2,
    razao: "o exemplo de E.164 na docstring da normalizacao de telefone (KAM-006)",
  },
  {
    ficheiro: "tools/contract_diff/cli.py",
    ocorrencias: 1,
    razao: "o exemplo de achado que o gate 7 imprime, na ajuda do comando",
  },
  {
    ficheiro: "tools/contract_diff/tests/test_pii.py",
    ocorrencias: 7,
    razao:
      "controlo positivo do gate 7: sem um numero de forma angolana a suite nao " +
      "prova que o detector o ve, e um zero sobre uma entrada limpa nao diz nada",
  },
  {
    ficheiro: "services/agr/src/kamba_agr/privacidade/detector.py",
    ocorrencias: 2,
    razao:
      "os exemplos na docstring do TELEFONE_PADRAO do KAM-112, que lista as dez " +
      "formas de escrever um movel angolano que o criterio 2 enumera. Duas das " +
      "dez — o `+244` junto e o `00244` — tem a forma que este scan procura, e " +
      "tinham de ter: um exemplo que nao casasse o padrao que ilustra enganava " +
      "quem o lesse, que e a mesma razao da entrada do `eventos/pii.ts`. " +
      "Sequenciais, como os das outras entradas desta lista",
  },
  {
    ficheiro: "services/agr/tests/test_minimizacao.py",
    ocorrencias: 1,
    razao:
      "o exemplo no comentario do `test_zero_dados_reais` do KAM-112, que " +
      "explica porque e que a primeira versao daquele ensaio acusava quarenta e " +
      "dois numeros «nao declarados» que eram os declarados vistos a meio: um " +
      "`\d{9}` deslizante apanha janelas de nove digitos **dentro** de um " +
      "numero com prefixo. Sem o exemplo, o comentario nao se podia verificar",
  },
  {
    ficheiro: "db/tests_encomendas/test_outbox.py",
    ocorrencias: 2,
    razao:
      "controlo positivo da guarda de PII de platform.evt_emitir (KAM-044, " +
      "criterio 8): o ensaio emite um order.cancelled com um numero de forma " +
      "angolana no `motivo` e exige `check_violation` **antes** de qualquer " +
      "escrita no outbox. Sem um numero de forma real a asercao nao prova que o " +
      "padrao da revisao 0004 o ve, que e a razao da entrada do " +
      "`contract_diff/tests/test_pii.py`. **Sao duas ocorrencias e o numero e " +
      "um**: ele casa os **dois** padroes desta ferramenta — o `telefone_ao` " +
      "pelo `+244 9...` e o `e164_entre_aspas` por estar entre aspas num " +
      "literal de Python —, e o varrimento conta por padrao. Medido com os dois " +
      "padroes de `numeros.ts` sobre o ficheiro. Sequencial a partir do prefixo " +
      "movel, como os das outras entradas desta lista, e nao pertence a ninguem",
  },
  {
    ficheiro: "packages/core-ts/tests/avisos.test.ts",
    ocorrencias: 2,
    razao:
      "os nomes de loja do varrimento de 200 avisos do KAM-115, criterio 5: o " +
      "aviso ao dono mascara corridas de sete ou mais digitos no nome da loja " +
      "porque «Loja do Ze 923 456 789» e um nome plausivel em Luanda, e sem " +
      "numeros de forma real o teste provava que a mascara apanha numeros que " +
      "nao se parecem com telefones — que e o contrario do que ela existe para " +
      "fazer. Nenhum pertence a ninguem: sao sequenciais a partir do prefixo " +
      "movel, como os das outras entradas desta lista",
  },
  {
    ficheiro: "db/tests_agr/test_checkpointer.py",
    ocorrencias: 3,
    razao:
      "o controlo positivo do criterio 2 do KAM-026: o estado do checkpointer " +
      "vai em `msgpack` para uma coluna `bytea`, pelo que uma busca por texto " +
      "devolve **zero** com um telefone la dentro. O varrimento desserializa, e " +
      "so prova alguma coisa depois de se mostrar que encontra o que la esta — " +
      "pelo que o ensaio semeia um numero e exige que o encontre. Sao **tres** " +
      "formas e nao uma: a internacional que o criterio escreve, a mesma sem o " +
      "`+`, e a **local** com espacos, que e a que um cliente angolano escreve " +
      "no WhatsApp e que a primeira versao da expressao nao apanhava. Nenhum " +
      "pertence a ninguem: sao sequenciais a partir do prefixo movel, como os " +
      "das outras entradas desta lista",
  },
  {
    ficheiro: "tools/log_policy/tests/test_x11.py",
    ocorrencias: 6,
    razao:
      "a suite X-11 de docs/tecnica/08 §3.7: 1 000 chamadas com telefones reais " +
      "pelos dois loggers, e a saida de Python tem de ser igual a de TypeScript",
  },
  // --- Os dois loggers e a sua paridade ------------------------------------
  {
    ficheiro: "packages/core-ts/tests/logger.test.ts",
    ocorrencias: 4,
    razao: "controlo positivo da redaccao do logger de TypeScript (KAM-068)",
  },
  {
    ficheiro: "libs/py-core/tests/test_logger.py",
    ocorrencias: 3,
    razao: "controlo positivo da redaccao do logger de Python (KAM-068)",
  },
  {
    ficheiro: "libs/py-core/tests/test_logger_ponte.py",
    ocorrencias: 1,
    razao: "a ponte entre os dois loggers, pela mesma razao",
  },
  {
    ficheiro: "packages/core-ts/tests/fixtures/logger_paridade.json",
    ocorrencias: 5,
    razao:
      "as entradas da paridade byte a byte entre os dois loggers; e JSON e nao " +
      "leva comentario, e por isso a razao vive aqui",
  },
  // --- Os contratos de evento e o guarda de PII ----------------------------
  {
    ficheiro: "packages/core-ts/tests/eventos.pii.test.ts",
    ocorrencias: 6,
    razao: "controlo positivo do guarda de PII dos envelopes (KAM-007)",
  },
  {
    ficheiro: "packages/core-ts/tests/eventos.envelope.test.ts",
    ocorrencias: 2,
    razao: "um envelope que o guarda tem de recusar",
  },
  {
    ficheiro: "packages/core-ts/tests/eventos.publicador.test.ts",
    ocorrencias: 2,
    razao: "o publicador recusa publicar um payload com telefone",
  },
  {
    ficheiro: "packages/core-ts/tests/fixtures/eventos_pii.json",
    ocorrencias: 9,
    razao:
      "as nove formas que o detector de PII tem de apanhar, incluindo as que " +
      "casam por pouco; e JSON e nao leva comentario",
  },
  {
    ficheiro: "db/tests/test_eventos_schema.py",
    ocorrencias: 9,
    razao: "o guarda de platform.evt_emitir recusa no lado da base (KAM-007)",
  },
  {
    ficheiro: "db/tests_eventos/test_publicador.py",
    ocorrencias: 2,
    razao: "o mesmo, pelo lado do publicador a correr contra a base",
  },
  {
    ficheiro: "db/tests_pagamentos/test_porta.py",
    ocorrencias: 5,
    razao:
      "a guarda de PII da platform.append_payment_event, que e a caixa de " +
      "privacidade do KAM-053 e tem de morder no payload **e** no motivo — o " +
      "motivo viaja para o outbox. Cinco: tres formas no payload (o +244 com " +
      "prefixo, o 244 sem ele e um internacional que casa pelo segundo padrao), " +
      "uma no motivo, e a sonda positiva de um payload redigido ao lado, sem a " +
      "qual uma guarda que recusasse tudo deixava as outras quatro verdes. Num " +
      "ledger append-only isto conta mais do que noutra tabela: um telefone que " +
      "entre nao sai, nem com UPDATE, porque o deny_mutation recusa",
  },
  // --- A entrada de canal --------------------------------------------------
  {
    ficheiro: "packages/core-ts/tests/entrada.explosao.test.ts",
    ocorrencias: 2,
    razao:
      "a explosao de um corpo da Meta com a forma que o trafego tem; os wamid " +
      "do KAM-013 contem o numero, e e isso que o idOpaco fecha",
  },
  {
    ficheiro: "packages/core-ts/tests/entrada.registo.test.ts",
    ocorrencias: 1,
    razao: "o registo da entrada nao escreve o telefone que recebeu",
  },
  {
    ficheiro: "packages/core-ts/tests/identity.cripto.test.ts",
    ocorrencias: 2,
    razao:
      "os dois E.164 que a normalizacao tem de recusar: um dos EUA e um com " +
      "zero a cabeca, que sao os casos de fronteira do KAM-006",
  },
  {
    ficheiro: "services/gwy/tests/webhook.test.ts",
    ocorrencias: 1,
    razao:
      "o canario do criterio 9 do KAM-013: 1 000 pedidos com telefones reais " +
      "nos logs tem de dar 0 achados, e um canario ficticio nao provava nada",
  },
  // --- Desenho -------------------------------------------------------------
  {
    ficheiro: "docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md",
    ocorrencias: 3,
    razao:
      "os tres numeros de exemplo do desenho do indice de pesquisa; o prefixo " +
      "900 nao e atribuido a nenhuma operadora angolana",
  },
  // --- Este ticket ---------------------------------------------------------
  {
    ficheiro: "tools/meta-sim/tests/captura.test.ts",
    ocorrencias: 12,
    razao:
      "a captura «real» que o saneador tem de limpar, e o scan que tem de a " +
      "detectar; sem numeros de forma real estes testes nao testavam nada",
  },
  {
    ficheiro: "tools/meta-sim/tests/simulador.test.ts",
    ocorrencias: 5,
    razao: "o controlo positivo de telefonesReais e de exigirFicticios",
  },
  // --- O agregador de SMS (KAM-116) ----------------------------------------
  //
  // Cinco ficheiros e catorze ocorrencias, todas do padrao `e164_entre_aspas`:
  // sao destinos em cadeia, da forma `+244` seguido de nove algarismos, e
  // **nenhuma** casa o `telefone_ao`, que exige o `9` depois do indicativo.
  //
  // (Os exemplos deste comentario vao **sem aspas** de proposito. Um `+244…`
  // entre aspas casa o `e164_entre_aspas`, e este ficheiro passava a precisar
  // de uma entrada para si mesmo — medido: a primeira versao desta nota deu
  // exactamente isso. Uma entrada do inventario para a prosa do inventario e
  // ruido, e o que vale a pena declarar sao as *fixtures*.)
  //
  // **Porque e que nao se usa o intervalo ficticio, que e a resposta normal.**
  // O modulo `packages/core-ts/src/sms/` so aceita o prefixo `+244` — e a
  // recusa de tudo o resto e o critetio 6 do ticket, nao uma conveniencia. Um
  // `999…` do intervalo reservado e recusado pelo `normalizarDestino` antes de
  // chegar a qualquer ensaio, pelo que uma suite escrita com numeros ficticios
  // nao podia exercitar nem o caminho feliz nem a recusa. E a mesma forma de
  // argumento que a nota do topo deste ficheiro faz para os redactores de PII:
  // «um redactor testado so com numeros do 999 nunca prova que apanha um
  // +244 9…».
  //
  // **E porque e que nao se escondem do varredor.** Compor `"+244" + NACIONAL`
  // em vez de escrever a cadeia inteira tirava-os destas contagens sem tirar a
  // forma do ficheiro — seria passar o portao em vez de o satisfazer, que e o
  // que a nota do topo recusa quando fala de isentar `tests/`.
  //
  // **O que torna estes catorze seguros nao e a declaracao, e a forma deles:**
  // o numero nacional comeca por `0`, e um E.164 nacional nunca comeca por
  // zero. Nao podem colidir com o telefone de ninguem, e a revisao adversarial
  // deste ticket confirmou-o levantando todas as formas `+244…`/`00244…`/`244…`
  // dos ficheiros do ticket: **todas** tem essa forma, sem excepcao.
  {
    ficheiro: "packages/core-ts/tests/sms.contrato.test.ts",
    ocorrencias: 10,
    razao:
      "as tres grafias do indicativo que o normalizarDestino aceita (+244, 244 " +
      "e 00244, com e sem separadores) e as que ele recusa — outro pais, sem " +
      "indicativo, e com mais e menos algarismos do que nove; mais o valor de " +
      "ouro do HMAC do destino, que prende o separador de dominio. Sem numeros " +
      "de forma real estes testes nao testavam nada: o modulo so aceita +244, " +
      "e um numero ficticio e recusado antes de chegar ao caso",
  },
  {
    ficheiro: "packages/core-ts/tests/sms.idempotencia.test.ts",
    ocorrencias: 1,
    razao:
      "o destino unico da bateria de idempotencia: duas chamadas com a mesma " +
      "chave tem de dar UM SMS, e o destino tem de ser cunhavel pelo modulo, " +
      "que so aceita +244",
  },
  {
    ficheiro: "packages/core-ts/tests/sms.privacidade.test.ts",
    ocorrencias: 1,
    razao:
      "o controlo positivo da bateria X-11 do modulo: o varrimento tem de VER " +
      "o telefone e o codigo do OTP quando eles la estao, senao o zero dos " +
      "casos seguintes nao diz nada — e a licao escrita no alvo x11 do Makefile",
  },
  {
    ficheiro: "packages/core-ts/tests/sms.governanca.test.ts",
    ocorrencias: 1,
    razao:
      "o destino que o pepper lido do cofre cunha, que e o que liga o critetio 7 " +
      "(segredos com anel) ao critetio 6 (HMAC nos registos) num ensaio so",
  },
  {
    ficheiro: "packages/core-ts/tests/sms.revisao.test.ts",
    ocorrencias: 1,
    razao:
      "o destino dos sete achados da revisao adversarial, entre eles o recibo " +
      "forjado que a lista de IPs aceitava por uma barra final; um destino " +
      "ficticio nao chegava a cunhar-se e o achado 1 nao se podia medir",
  },
  // --- A inscricao self-service (KAM-086) ----------------------------------
  //
  // Cinco ficheiros e vinte e sete ocorrencias, **medidas com `meta-sim
  // varrer` e nao escritas a mao** — e e a unica maneira de a contagem
  // continuar a querer dizer algo.
  //
  // **Porque e que nao se usa o intervalo ficticio**, que e a resposta normal: o
  // registo e o OTP deste ticket correm sobre o `packages/core-ts/src/sms/`, que
  // so aceita o prefixo `+244` — e a recusa de tudo o resto e o criterio 6 do
  // KAM-116 e o criterio 6 deste bloco, nao uma conveniencia. Um `999...` do
  // intervalo reservado e recusado pelo `normalizarTelefone` antes de chegar a
  // qualquer ensaio, pelo que uma bateria escrita com numeros ficticios nao
  // podia exercitar nem o caminho feliz nem a recusa. E a mesma forma de
  // argumento da entrada do KAM-116, duas acima.
  //
  // **E porque e que nao se esconde do varredor.** Compor `"+244" + NACIONAL` em
  // vez de escrever a cadeia inteira tirava-os destas contagens sem tirar a
  // forma do ficheiro — seria passar o portao em vez de o satisfazer.
  //
  // **O que torna estes vinte e sete seguros nao e a declaracao, e a forma
  // deles:** o numero nacional comeca por `0`, e um E.164 nacional nunca comeca
  // por zero — o zero e prefixo de chamada nacional e nao entra no numero
  // internacional. Nao podem colidir com o telefone de ninguem. A excepcao sao
  // as grafias **estrangeiras** do ensaio de *SMS pumping*, que existem para
  // serem RECUSADAS e que por isso nunca chegam a ser um destino: sao as tres do
  // `adversarial.test.ts`, e estao la porque um ensaio que so recusasse numeros
  // impossiveis nao provava que o modulo recusa um numero de outro pais.
  {
    ficheiro: "packages/core-ts/tests/inscricao.identificadores.test.ts",
    ocorrencias: 7,
    razao:
      "as doze grafias do mesmo telefone que o criterio 4 do KAM-086 enumera: " +
      "seis levam separador pelo meio, que e precisamente a forma que o " +
      "telefone_ao deste ficheiro NAO apanha — a corrida de digitos quebra no " +
      "espaco. Sem numeros de forma real a bateria provava que a normalizacao " +
      "junta grafias de um numero que o modulo recusa antes de as ver",
  },
  {
    ficheiro: "packages/core-ts/tests/inscricao.otp.test.ts",
    ocorrencias: 10,
    razao:
      "os destinos das baterias de frequencia, intervalo e orcamento do " +
      "criterio 5: o limite e POR TELEFONE, pelo que medi-lo exige telefones " +
      "distintos e cunhaveis pelo modulo — que so aceita +244. Um numero " +
      "ficticio era recusado antes de chegar ao caso que se quer medir",
  },
  {
    ficheiro: "packages/core-ts/tests/inscricao.registo.test.ts",
    ocorrencias: 5,
    razao:
      "o telefone do caso base e o segundo telefone dos ensaios de duplicado do " +
      "criterio 8: o telefone repetido com NIF diferente e a recuperacao de " +
      "sessao, onde se compara o destino do SMS da recuperacao com o do registo " +
      "original para provar que ele vai ao numero REGISTADO e nao ao submetido",
  },
  {
    ficheiro: "services/onboarding-web/tests/registo.test.ts",
    ocorrencias: 2,
    razao:
      "o telefone que o formulario submete pela rota HTTP, e um segundo para o " +
      "ensaio de isolamento entre dois casos. A bateria do servico existe para " +
      "medir que as barreiras estao LIGADAS ao pedido, e um pedido com um " +
      "telefone que o modulo recusa nunca chega a exercitar a ligacao",
  },
  {
    ficheiro: "services/onboarding-web/tests/adversarial.test.ts",
    ocorrencias: 3,
    razao:
      "as grafias ESTRANGEIRAS do ensaio adversarial (d) de SMS pumping, que " +
      "existem para ser recusadas: um ensaio escrito so com numeros impossiveis " +
      "nao provava que o modulo recusa um numero de outro pais, que e o ataque " +
      "real — usar o nosso agregador como rele para destinos que pagam mais " +
      "caro. As restantes grafias deste ficheiro sao compostas por indice e nao " +
      "contam aqui",
  },
  // --- O canario do ensaio de privacidade do spike H3 (KAM-100) ------------
  //
  // **Cinco ocorrencias num ficheiro so, e o ficheiro e um ensaio de canario.**
  // Medidas com os dois padroes de `numeros.ts` sobre o ficheiro, nao escritas
  // a mao.
  //
  // O spike H3 grava JSON-lines de coexistencia e tem de provar que **nao** leva
  // telefone nenhum. O criterio do ticket pede «um teste de que o resultado nao
  // contem texto de mensagens», e esse teste escrito ao pe da letra — comparar
  // nomes de campo com uma lista — fica verde com uma mensagem inteira num campo
  // chamado `nota`. Por isso o ensaio mede a **forma dos valores**, e para isso
  // precisa de um corpo de entrada com telefones de forma angolana: sem eles,
  // provava que o detector apanha numeros que nao se parecem com telefones, que
  // e o contrario do que ele existe para fazer. E a mesma razao da entrada do
  // `sms.privacidade.test.ts` e do `contract_diff/tests/test_pii.py`.
  //
  // As grafias que os ensaios precisam de levar, e o que cada uma custa:
  //
  //   `+244` com espaco antes do movel     1 — so `telefone_ao`: o espaco
  //                                        quebra a corrida de digitos de que o
  //                                        `e164_entre_aspas` precisa
  //   `+244` junto ao movel                2 — `telefone_ao` e
  //                                        `e164_entre_aspas`, este por estar
  //                                        entre aspas num literal de Python
  //   `244` e `00244` sem o mais           1 cada — `telefone_ao`, nas duas
  //                                        grafias que o `id_opaco` tem de
  //                                        recusar
  //   `244` com separadores pelo meio      1 cada — as grafias com hifen, ponto
  //                                        e parentese que a guarda do
  //                                        `id_opaco` tambem tem de descartar,
  //                                        e que a primeira versao dela
  //                                        **resumia** por so retirar espacos
  //   `fase_` com um E.164 sem o mais      1 — o valor de ataque que prova que
  //                                        a forma da chave `fase` ja nao
  //                                        admite um telefone
  //
  // **As formas descrevem-se aqui e nao se escrevem.** Um literal num
  // comentario acrescenta ocorrencias ao ficheiro que o leva, e um comentario
  // nao esta a testar nada: o inventario passava a declarar numeros inuteis. O
  // erro foi cometido **duas vezes** neste ticket — a primeira versao desta
  // entrada tinha-os aqui, e a `ANALISE-52` tinha-os na prosa —, e as duas vezes
  // apareceu ao **re-medir a arvore**, nao a ler.
  //
  // Os ensaios levam tambem a forma **local** (`9` mais oito digitos), que
  // **nenhum** destes dois padroes apanha — um exige `244`, o outro um `+` — e
  // que por isso nao conta aqui. Esta la de proposito: um telefone que entrasse
  // assim num ficheiro de evidencia passava este gate e continuava a ser um dado
  // pessoal, e o ensaio acrescenta um terceiro detector so para ele.
  //
  // Nenhum pertence a ninguem: sao sequenciais a partir do prefixo movel, como
  // os das outras entradas desta lista.
  //
  // **As duas entradas morrem com o spike.** O `spikes/h3/` e descartavel e o
  // `confrontar` recusa entrada morta, pelo que quem apagar a pasta apaga estas
  // entradas no mesmo PR — que e exactamente o comportamento que se quer.
  {
    ficheiro: "spikes/h3/tests/test_privacidade.py",
    ocorrencias: 8,
    razao:
      "o canario do ensaio de privacidade do KAM-100: o detector tem de VER as " +
      "formas de movel angolano na entrada, senao o zero medido na saida do " +
      "registo nao diz nada — a licao do sms.privacidade.test.ts e do alvo x11. " +
      "Oito ocorrencias: as quatro grafias do canario (uma delas a contar duas " +
      "vezes, por casar os dois padroes) mais as tres com separadores pelo meio " +
      "que a guarda do id_opaco tem de descartar e que a primeira versao dela " +
      "resumia. Sequenciais a partir do prefixo movel",
  },
  {
    ficheiro: "spikes/h3/tests/test_extrair.py",
    ocorrencias: 1,
    razao:
      "o valor de ataque do ensaio da chave `fase` do KAM-100: um E.164 sem o " +
      "mais dentro de um `fase_`, que a forma antiga da chave aceitava e o " +
      "extractor fabricava a partir de qualquer inteiro do metadata.phase. Sem " +
      "o literal o ensaio provava que a forma recusa um valor que nao tem forma " +
      "de telefone, que e o contrario do que ele existe para fazer. Sequencial",
  },
];

/** O que o *scan* mediu num ficheiro. */
export interface Medicao {
  readonly ficheiro: string;
  readonly ocorrencias: number;
}

/** Uma divergência entre o inventário e o que o *scan* mediu. */
export interface Divergencia {
  readonly ficheiro: string;
  readonly tipo: "nao_declarado" | "a_mais" | "a_menos" | "entrada_morta" | "sem_razao";
  readonly declaradas: number;
  readonly medidas: number;
  readonly razao: string;
}

/** A frase de uma divergência, para o relatório do CI. */
export function frase(d: Divergencia): string {
  switch (d.tipo) {
    case "nao_declarado":
      return `${d.ficheiro}: ${d.medidas} numero(s) de forma real e nenhuma entrada no inventario`;
    case "a_mais":
      return `${d.ficheiro}: ${d.medidas} numero(s) e o inventario declara ${d.declaradas}`;
    case "a_menos":
      return (
        `${d.ficheiro}: ${d.medidas} numero(s) e o inventario declara ${d.declaradas} — ` +
        "baixe a contagem, senao o inventario deixa de contar"
      );
    case "entrada_morta":
      return `${d.ficheiro}: declarado no inventario e sem numero nenhum (ou o ficheiro desapareceu)`;
    case "sem_razao":
      return `${d.ficheiro}: a entrada do inventario nao diz porque e que o numero esta la`;
  }
}

/** O comprimento mínimo de uma razão. Uma palavra não é uma razão. */
const RAZAO_MINIMA = 30;

/**
 * Confronta o inventário com o que o *scan* mediu.
 *
 * `medicoes` traz **só** os ficheiros com ocorrências; um ficheiro declarado que
 * não apareça lá é uma entrada morta, e é por isso que a comparação é nos dois
 * sentidos e não só num.
 */
export function confrontar(
  medicoes: readonly Medicao[],
  inventario: readonly Entrada[] = INVENTARIO,
): readonly Divergencia[] {
  const divergencias: Divergencia[] = [];
  const declarado = new Map(inventario.map((e) => [e.ficheiro, e]));
  const medido = new Map(medicoes.map((m) => [m.ficheiro, m.ocorrencias]));

  for (const entrada of inventario) {
    if (entrada.razao.trim().length < RAZAO_MINIMA) {
      divergencias.push({
        ficheiro: entrada.ficheiro,
        tipo: "sem_razao",
        declaradas: entrada.ocorrencias,
        medidas: medido.get(entrada.ficheiro) ?? 0,
        razao: entrada.razao,
      });
    }
  }

  for (const [ficheiro, ocorrencias] of medido) {
    const entrada = declarado.get(ficheiro);
    if (entrada === undefined) {
      divergencias.push({ ficheiro, tipo: "nao_declarado", declaradas: 0, medidas: ocorrencias, razao: "" });
      continue;
    }
    if (ocorrencias > entrada.ocorrencias) {
      divergencias.push({
        ficheiro,
        tipo: "a_mais",
        declaradas: entrada.ocorrencias,
        medidas: ocorrencias,
        razao: entrada.razao,
      });
    } else if (ocorrencias < entrada.ocorrencias) {
      divergencias.push({
        ficheiro,
        tipo: "a_menos",
        declaradas: entrada.ocorrencias,
        medidas: ocorrencias,
        razao: entrada.razao,
      });
    }
  }

  for (const entrada of inventario) {
    if (!medido.has(entrada.ficheiro)) {
      divergencias.push({
        ficheiro: entrada.ficheiro,
        tipo: "entrada_morta",
        declaradas: entrada.ocorrencias,
        medidas: 0,
        razao: entrada.razao,
      });
    }
  }

  // Comparação de cadeias e **não** `localeCompare`: o `localeCompare` depende
  // do locale e do ICU do *runner*, e a ordem desta lista vai para a evidência.
  // Um diff que mude de máquina para máquina é um diff que ninguém lê.
  const antes = (x: string, y: string): number => (x < y ? -1 : x > y ? 1 : 0);
  return divergencias.sort(
    (a, b) => antes(a.ficheiro, b.ficheiro) || antes(a.tipo, b.tipo),
  );
}

/** O total declarado. Para o relatório, e para ver se sobe. */
export function totalDeclarado(inventario: readonly Entrada[] = INVENTARIO): number {
  return inventario.reduce((soma, e) => soma + e.ocorrencias, 0);
}
