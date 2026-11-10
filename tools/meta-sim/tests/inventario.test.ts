/**
 * O inventário de números de forma real (KAM-024, critério 7).
 *
 * Estes testes provam que o inventário é um **raquete** e não uma isenção: que
 * falha nos quatro sentidos em que uma pasta permitida não falharia. É a parte
 * que decide se a caixa do critério 7 se pode marcar, e por isso cada sentido
 * tem o seu teste.
 *
 * O confronto contra o repositório real **não** está aqui: é o `meta-sim
 * varrer` que o faz, no gate 7, porque é lá que ele tem o repositório inteiro à
 * frente. Aqui prova-se a regra; lá aplica-se.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { INVENTARIO, confrontar, frase, totalDeclarado, type Entrada } from "../src/inventario.ts";

const UM: readonly Entrada[] = [
  {
    ficheiro: "a/b.ts",
    ocorrencias: 2,
    razao: "um controlo positivo do detector de PII, que sem isto nao dispara",
  },
];

describe("o inventario falha nos quatro sentidos", () => {
  it("um ficheiro com numero e sem entrada: nao_declarado", () => {
    // É o sentido que importa mais: é o que uma pasta permitida deixava passar.
    const d = confrontar([{ ficheiro: "c/d.ts", ocorrencias: 1 }], UM);
    assert.equal(d.filter((x) => x.tipo === "nao_declarado").length, 1);
    assert.match(frase(d.find((x) => x.tipo === "nao_declarado")!), /nenhuma entrada no inventario/);
  });

  it("um numero a mais num ficheiro JA declarado: a_mais", () => {
    // O segundo sentido que a pasta permitida deixava passar: dentro de um
    // ficheiro já tolerado, um número novo não se via.
    const d = confrontar([{ ficheiro: "a/b.ts", ocorrencias: 3 }], UM);
    assert.equal(d.length, 1);
    assert.equal(d[0]?.tipo, "a_mais");
    assert.match(frase(d[0]!), /3 numero\(s\) e o inventario declara 2/);
  });

  it("um numero a menos: a_menos, para o inventario nao envelhecer", () => {
    const d = confrontar([{ ficheiro: "a/b.ts", ocorrencias: 1 }], UM);
    assert.equal(d.length, 1);
    assert.equal(d[0]?.tipo, "a_menos");
    assert.match(frase(d[0]!), /baixe a contagem/);
  });

  it("uma entrada sem medicao: entrada_morta", () => {
    const d = confrontar([], UM);
    assert.equal(d.length, 1);
    assert.equal(d[0]?.tipo, "entrada_morta");
  });

  it("uma razao curta e um defeito do inventario", () => {
    // Uma entrada sem razão é uma isenção disfarçada de inventário.
    const d = confrontar(
      [{ ficheiro: "a/b.ts", ocorrencias: 2 }],
      [{ ficheiro: "a/b.ts", ocorrencias: 2, razao: "e um teste" }],
    );
    assert.equal(d.length, 1);
    assert.equal(d[0]?.tipo, "sem_razao");
  });

  it("a contagem certa com a razao certa nao diverge", () => {
    assert.deepEqual(confrontar([{ ficheiro: "a/b.ts", ocorrencias: 2 }], UM), []);
  });
});

describe("o inventario deste repositorio", () => {
  it("cada entrada diz porque e que o numero esta la", () => {
    for (const entrada of INVENTARIO) {
      assert.ok(
        entrada.razao.trim().length >= 30,
        `${entrada.ficheiro}: a razao tem ${entrada.razao.trim().length} caracteres`,
      );
    }
  });

  it("nao ha ficheiros repetidos", () => {
    const vistos = new Set(INVENTARIO.map((e) => e.ficheiro));
    assert.equal(vistos.size, INVENTARIO.length);
  });

  it("os caminhos sao relativos e com barra, nao com contrabarra", () => {
    // Um inventário com `\\` numa máquina e `/` na outra dava «não declarado»
    // para tudo, no sítio onde ninguém olha.
    for (const entrada of INVENTARIO) {
      assert.ok(!entrada.ficheiro.includes("\\"), entrada.ficheiro);
      assert.ok(!entrada.ficheiro.startsWith("/"), entrada.ficheiro);
      assert.ok(!entrada.ficheiro.includes(".."), entrada.ficheiro);
    }
  });

  it("o total declarado e o que a medicao diz", () => {
    // 89 ocorrências em 24 ficheiros na medição de 2026-10-20, menos as 3 que o
    // KAM-024 passou para o intervalo fictício em
    // `services/gwy/tests/webhook.test.ts`: **86**.
    //
    // **88 desde o KAM-115**, e as duas que entram dizem para que servem: são
    // nomes de loja do varrimento de 200 avisos do critério 5 daquele ticket. O
    // aviso ao dono mascara corridas de sete ou mais dígitos no nome da loja
    // porque «Loja do Zé 923 456 789» é um nome plausível em Luanda — e sem
    // números de **forma** real o teste provava que a máscara apanha números
    // que não se parecem com telefones, que é o contrário do que ela existe
    // para fazer.
    //
    // **Este número sobe com o inventário e é isso que o torna um raquete**: a
    // contagem num sítio só obriga quem acrescenta um ficheiro a dizê-lo aqui
    // também, e é o que distingue isto de uma pasta isenta — que cresceria em
    // silêncio.
    // **94 em 26 ficheiros desde o KAM-112**, e as tres que entram sao das
    // docstrings do detector de PII daquele ticket: duas das dez formas de
    // telefone que o criterio 2 enumera — o `+244` junto e o `00244` — tem a
    // forma que este scan procura, e tinham de ter, porque um exemplo que nao
    // casasse o padrao que ilustra enganava quem o lesse. A terceira esta no
    // comentario do ensaio que explica porque e que um `\d{9}` deslizante
    // conta janelas de nove digitos **dentro** de um numero com prefixo.
    //
    // **E este gate apanhou-as antes de mim**, que e o que ele existe para
    // fazer: o KAM-112 abriu PR com os tres numeros por declarar e o gate 7
    // ficou vermelho. Uma pasta `tests/` isenta — a tentacao que o
    // `inventario.ts` recusa por extenso — tinha deixado passar os tres.
    //
    // **99 em 27 ficheiros desde o KAM-053**, e as cinco que entram sao da
    // guarda de PII da `platform.append_payment_event`: tres formas no payload
    // (o `+244` com prefixo, o `244` sem ele e um internacional que casa pelo
    // segundo padrao), uma no `motivo` — que viaja para o *outbox* e por isso
    // entra na guarda — e a sonda positiva de um payload redigido ao lado, sem
    // a qual uma guarda que recusasse tudo deixava as outras quatro verdes.
    //
    // **E este gate apanhou-as outra vez, e a mim**: o PR do KAM-053 abriu com
    // as cinco por declarar e o gate 7 ficou vermelho na primeira corrida, com
    // a mensagem a nomear o ficheiro. E a terceira vez que a mesma salvaguarda
    // morde um ticket que nao a estava a pensar — o KAM-115, o KAM-112 e este —
    // e e por isso que a contagem fica aqui e nao numa pasta isenta.
    //
    // **101 em 28 ficheiros desde o KAM-044**, e as duas que entram sao **um
    // numero**: o controlo positivo da guarda de PII de `platform.evt_emitir`
    // no `db/tests_encomendas/test_outbox.py` — um `order.cancelled` com um
    // numero de forma angolana no `motivo`, que tem de ser recusado **antes**
    // de qualquer escrita no outbox. Conta duas vezes porque casa os **dois**
    // padroes de `numeros.ts`: o `telefone_ao` pelo `+244 9...` e o
    // `e164_entre_aspas` por estar entre aspas num literal de Python.
    //
    // **E este gate apanhou-o outra vez, e a mim**: o PR do KAM-044 abriu com
    // o numero por declarar e o gate 7 ficou vermelho na primeira corrida, com
    // a mensagem a nomear o ficheiro e a contagem. E a quarta vez que a mesma
    // salvaguarda morde um ticket que nao a estava a pensar — o KAM-115, o
    // KAM-112, o KAM-053 e este.
    //
    // **115 em 33 ficheiros desde o KAM-116**, e as catorze que entram sao as
    // cinco suites do agregador de SMS: dez na do contrato (as tres grafias do
    // indicativo que o modulo aceita, as que ele recusa, e o valor de ouro do
    // HMAC do destino) e uma em cada das outras quatro. Todas casam **so** o
    // `e164_entre_aspas`, porque o numero nacional comeca por `0` e o
    // `telefone_ao` exige o `9` depois do indicativo.
    //
    // **E este e o caso em que o intervalo ficticio nao servia**, o que vale a
    // pena registar porque e a primeira vez nesta lista: o modulo `sms/` so
    // aceita o prefixo `+244` — a recusa de tudo o resto e um critetio de
    // aceitacao dele —, pelo que um `999...` do intervalo reservado e recusado
    // pelo `normalizarDestino` antes de chegar a qualquer ensaio. E a mesma
    // forma de argumento que o `inventario.ts` faz para os redactores de PII,
    // aplicada a um modulo que valida em vez de redigir.
    //
    // **E apanhou-o outra vez, e a mim**: o PR do KAM-116 abriu com os catorze
    // por declarar e o gate 7 ficou vermelho na primeira corrida. E a **quinta**
    // vez que a mesma salvaguarda morde um ticket que nao a estava a pensar — o
    // KAM-115, o KAM-112, o KAM-053, o KAM-044 e este —, e a quinta em que o
    // autor verificou os nove portoes que corre nesta maquina e nao podia ver
    // este: o `ci-7-meta` corre por `pnpm`, que aqui nao existe.
    //
    // **124 em 35 ficheiros desde o KAM-100**, e as nove que entram sao os
    // canarios de dois ensaios do spike H3: **oito** no da privacidade e **uma**
    // no do extractor. Sao as quatro grafias do canario — uma delas a contar
    // duas vezes, porque a forma com o `244` junto ao movel casa os **dois**
    // padroes —, mais as tres com separadores pelo meio que a guarda do
    // `id_opaco` tem de descartar, mais o valor de ataque da chave `fase`.
    //
    // O ticket pede «um teste de que o resultado nao contem texto de
    // mensagens», e esse teste escrito ao pe da letra — comparar nomes de campo
    // com uma lista — fica verde com uma mensagem inteira guardada num campo
    // chamado `nota`. O ensaio mede por isso a **forma dos valores**, e para
    // isso precisa de uma entrada com telefones de forma angolana: sem eles
    // provava que o detector apanha numeros que nao se parecem com telefones,
    // que e o contrario do que ele existe para fazer. E a mesma forma de
    // argumento das entradas do `sms.privacidade.test.ts` e do
    // `contract_diff/tests/test_pii.py`.
    //
    // **Esta e a primeira vez nesta lista em que o gate nao apanhou o autor**, e
    // vale a pena registar porque e a licao que o paragrafo anterior deixou
    // escrita: o `ci-7-meta` corre por `pnpm`, que nesta maquina nao existe,
    // pelo que o autor do KAM-100 reimplementou os dois padroes de `numeros.ts`
    // em Python, varreu a arvore e confrontou-a com o inventario antes de abrir
    // o PR — **34 ficheiros, 120 ocorrencias, 0 divergencias** — e **leu este
    // ensaio** em vez de o correr. Foi a leitura, e nao a medicao, que apanhou
    // este par de numeros: uma arvore conforme com um total desactualizado aqui
    // deixava o gate 7 vermelho na mesma.
    //
    // **E o mesmo defeito apareceu duas vezes no proprio ticket**: literais com
    // forma de telefone escritos **dentro de prosa** — a primeira versao da
    // entrada do KAM-100 tinha-os no comentario de `inventario.ts`, que **nao
    // tem entrada propria**, e a `ANALISE-52` tinha-os no corpo do documento. As
    // duas vezes apareceu ao **re-medir a arvore**, e nao a ler. Os dois sitios
    // descrevem agora as formas sem as escrever, e a razao e a mesma: um
    // comentario nao esta a testar nada, e declarar numeros que nao testam nada
    // e o contrario do que esta lista e.
    //
    // **As duas entradas do spike morrem com ele.** O `spikes/h3/` e
    // descartavel e o `confrontar` recusa entrada morta, pelo que quem apagar a
    // pasta apaga as entradas e baixa estes dois numeros no mesmo PR.
    // **154 em 41 ficheiros desde o KAM-086**, e as trinta que entram sao as seis
    // superficies da inscricao: cinco baterias (sete nos identificadores, onze no
    // OTP, cinco no registo, dois na rota e tres no adversarial) mais dois no
    // condutor do grupo `inscricao` do gate 6. Todas casam **so** o
    // `e164_entre_aspas`, porque o numero nacional comeca por `0` e o
    // `telefone_ao` exige o `9` depois do indicativo — com a excepcao declarada
    // das tres **estrangeiras** do ensaio de *SMS pumping*, que existem para ser
    // RECUSADAS: um ensaio escrito so com numeros impossiveis nao provava que o
    // modulo recusa um numero de outro pais, que e o ataque real.
    //
    // **E o intervalo ficticio nao servia aqui pela mesma razao do KAM-116**: o
    // modulo da inscricao corre sobre a porta de SMS, que so aceita `+244`, pelo
    // que um `999...` do intervalo reservado e recusado antes de chegar ao caso.
    //
    // **E este gate apanhou o autor duas vezes no mesmo ticket**, e as duas
    // vezes ao **re-medir** e nao a ler: a primeira ao abrir o PR, com as 27
    // ocorrencias das baterias por declarar; e a segunda **depois da revisao
    // adversarial**, porque fechar os achados reescreveu as baterias e a conta
    // mudou — o OTP ganhou um destino (dez para onze) e o condutor do gate 6
    // nasceu com dois. A licao e a da entrada do KAM-100, do outro lado: a
    // contagem nao se cita de uma medicao anterior, re-mede-se depois da ultima
    // edicao. E a sexta vez que esta salvaguarda morde um ticket que nao a
    // estava a pensar.
    //
    // **165 em 43 ficheiros desde o KAM-093**: as duas baterias do passo guiado
    // (seis e quatro) e um terceiro destino no condutor do gate 6, o do caso de
    // A do grupo `guia`. Medidas com `varrer`, e a razao de os moveis casarem os
    // dois padroes esta na entrada.
    assert.equal(totalDeclarado(), 165);
    assert.equal(INVENTARIO.length, 43);
  });

  it("nenhuma entrada e de uma pasta inteira", () => {
    // O inventário é por **ficheiro**. Uma entrada que fosse uma pasta era a
    // isenção que isto existe para não ser.
    for (const entrada of INVENTARIO) {
      assert.ok(/\.[a-z]+$/.test(entrada.ficheiro), `${entrada.ficheiro} nao parece um ficheiro`);
    }
  });
});
