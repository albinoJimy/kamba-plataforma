/**
 * Os parâmetros do lembrete vêm **só de factos da marcação** (KAM-048,
 * critério 7).
 *
 * ## O que este ficheiro mede, e porque é que a forma óbvia não serve
 *
 * O critério pede «teste prova que nenhum valor é composto pelo LLM». A forma
 * óbvia — verificar que os parâmetros têm os nomes certos, ou que a saída tem
 * três posições — **não prova nada**: fica verde com um valor inventado lá
 * dentro, porque o nome de um campo não diz de onde veio o valor. É o defeito
 * que uma revisão adversarial apanhou noutro ticket, num ensaio que olhava para
 * nomes de etiqueta e não para a origem dos valores.
 *
 * O que aqui se mede é **proveniência**, por quatro vias, e cada uma apanha uma
 * coisa que as outras não apanham:
 *
 * ```text
 * 1. que campos foram LIDOS        Proxy sobre os factos; o conjunto tem de ser
 *                                  exactamente o da PROVENIENCIA
 * 2. o que MUDA quando o facto muda  varia-se um campo; o parâmetro que dele vem
 *                                  tem de mudar, e os outros de ficar iguais
 * 3. o que NAO ENTRA               um campo a mais, com texto da forma que um
 *                                  modelo escreveria, não aparece em parâmetro
 *                                  nenhum
 * 4. o que o MODULO ALCANCA        a lista de importações de `template.ts` não
 *                                  tem por onde chegar a um gerador de texto
 * ```
 *
 * Um valor constante falha (1) e (2); um valor de outra origem falha (1) ou
 * (3); uma aresta nova para um modelo falha (4). **Nenhuma das quatro olha para
 * o nome de coisa nenhuma.**
 *
 * ## O que NÃO prova
 *
 * Não prova que o corpo que a Meta aprovou tem três posições — isso é da
 * submissão, que é do EPIC-02 (KAM-091), e o que está aqui é a asserção de que
 * esta função devolve tantos parâmetros quantos a `PROVENIENCIA` declara. E não
 * prova que o *template* existe na `message_templates`: isso é o portão do
 * KAM-015, medido em `servicos.reminders.deliver.test.ts`.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  CAMPOS_DE_FACTO,
  CAMPOS_LIDOS,
  CORPO_DO_TEMPLATE,
  InicioInvalidoError,
  PARAMETROS_DO_LEMBRETE,
  PROVENIENCIA,
  dataDeLuanda,
  horaDeLuanda,
  parametrosDoLembrete,
  provenienciaCoerente,
  textoDoLembrete,
  type CampoDeFacto,
  type FactosDaMarcacao,
} from "../src/servicos/reminders/index.ts";

/** Os factos de ensaio. Um nome sem dígitos e um instante em plena tarde. */
const FACTOS: FactosDaMarcacao = {
  nomeDoServico: "Corte de cabelo",
  inicioAt: "2026-11-05T09:00:00.000Z",
};

/**
 * Os factos embrulhados num `Proxy` que registra cada campo lido.
 *
 * É a via (1) da nota do módulo, e é a única das quatro que um parâmetro
 * **constante** não consegue satisfazer: um valor que não vem de nenhum facto
 * não lê nenhum campo, e o conjunto registado fica mais pequeno do que o
 * declarado.
 */
function comRegisto(factos: FactosDaMarcacao): {
  readonly factos: FactosDaMarcacao;
  readonly lidos: Set<string>;
} {
  const lidos = new Set<string>();
  const alvo: Record<string, unknown> = { ...factos };
  const espelho = new Proxy(alvo, {
    get(objecto, campo, receptor) {
      if (typeof campo === "string") lidos.add(campo);
      return Reflect.get(objecto, campo, receptor);
    },
  }) as unknown as FactosDaMarcacao;
  return { factos: espelho, lidos };
}

/** Um facto variado num campo só. É a via (2). */
function variar(campo: CampoDeFacto): FactosDaMarcacao {
  if (campo === "nomeDoServico") {
    return { ...FACTOS, nomeDoServico: "Penteado de noiva" };
  }
  // Outro dia **e** outra hora: o `inicioAt` alimenta dois parâmetros, e variar
  // só a hora deixava o da data igual — o que faria a asserção «mudou» falhar
  // por uma razão que não é um defeito do código.
  return { ...FACTOS, inicioAt: "2026-12-24T16:45:00.000Z" };
}

test("o vocabulario da proveniencia e coerente consigo mesmo", () => {
  // Sem isto, as vias (1) e (2) comparavam dois conjuntos ambos errados e
  // ficavam verdes: uma `PROVENIENCIA` que nomeasse um campo inexistente
  // produzia um `undefined` lido do `Proxy` e um parâmetro vazio.
  assert.ok(provenienciaCoerente());
  assert.equal(PROVENIENCIA.length, PARAMETROS_DO_LEMBRETE);
  assert.deepEqual([...CAMPOS_LIDOS].sort(), [...new Set(PROVENIENCIA)].sort());
  for (const campo of CAMPOS_LIDOS) {
    assert.ok((CAMPOS_DE_FACTO as readonly string[]).includes(campo));
  }
});

test("(1) os campos lidos sao exactamente os que a PROVENIENCIA declara", () => {
  const { factos, lidos } = comRegisto(FACTOS);
  const parametros = parametrosDoLembrete(factos);

  assert.equal(parametros.length, PARAMETROS_DO_LEMBRETE);
  // **A asserção é de igualdade e não de inclusão.** «Subconjunto» deixava
  // passar um parâmetro constante (lê menos); «superconjunto» deixava passar um
  // valor de outra origem (lê mais). As duas direcções importam.
  assert.deepEqual([...lidos].sort(), [...new Set(PROVENIENCIA)].sort());
  for (const valor of parametros) {
    assert.notEqual(valor.trim(), "");
  }
});

test("(2) cada parametro muda com o seu facto, e so com o seu facto", () => {
  const base = parametrosDoLembrete(FACTOS);

  for (let i = 0; i < PROVENIENCIA.length; i += 1) {
    const campo = PROVENIENCIA[i] as CampoDeFacto;
    const variado = parametrosDoLembrete(variar(campo));

    assert.notEqual(
      variado[i],
      base[i],
      `o parametro ${i + 1} diz vir de ${campo} e nao mudou quando ${campo} mudou: ` +
        "e um valor fixo com uma etiqueta de proveniencia que mente",
    );

    for (let j = 0; j < PROVENIENCIA.length; j += 1) {
      if (PROVENIENCIA[j] === campo) continue;
      assert.equal(
        variado[j],
        base[j],
        `o parametro ${j + 1} diz vir de ${PROVENIENCIA[j]} e mudou quando ` +
          `${campo} mudou: le um facto que nao declara`,
      );
    }
  }
});

test("(3) texto a mais nos factos nao chega a parametro nenhum", () => {
  // A forma literal de «nenhum valor e composto pelo LLM»: um campo que nao
  // esta em `CAMPOS_DE_FACTO`, com prosa da forma que um modelo escreveria.
  const intruso = "amanha as 15:00, como combinamos";
  const comIntruso = { ...FACTOS, textoDoModelo: intruso } as FactosDaMarcacao;
  const { factos, lidos } = comRegisto(comIntruso);

  for (const valor of parametrosDoLembrete(factos)) {
    assert.ok(!valor.includes(intruso));
    assert.ok(!valor.includes("amanha"));
  }
  assert.ok(!lidos.has("textoDoModelo"));

  // E a mensagem livre tambem nao: ela usa os mesmos parametros, e e esse o
  // ponto do `textoDoLembrete` — a propriedade vale nos dois caminhos.
  assert.ok(!textoDoLembrete(comIntruso).includes(intruso));
});

test("(4) o modulo do template nao alcanca nada que gere texto", () => {
  // A via estrutural. Nao mede valores: mede o que o modulo **pode** alcancar.
  // Uma aresta nova para um modelo aparece aqui antes de aparecer numa saida.
  const fonte = readFileSync(
    new URL("../src/servicos/reminders/template.ts", import.meta.url),
    "utf8",
  );
  const especificadores = [...fonte.matchAll(/^\s*import[^"']*["']([^"']+)["']/gm)].map(
    (m) => m[1] as string,
  );
  assert.ok(especificadores.length > 0, "a regra nao esta a ver importacao nenhuma");
  for (const especificador of especificadores) {
    assert.equal(
      especificador,
      "./contrato.ts",
      `o template.ts importa ${especificador}: a unica importacao admitida e o ` +
        "proprio vocabulario, para que nao haja caminho para um gerador de texto",
    );
  }
});

test("(5) cada parametro e EXACTAMENTE a formatacao do seu facto", () => {
  // **A via que faltava, e a lacuna que ela fecha e a mais provavel de todas.**
  // As vias (1) a (3) apanham um valor **inventado** — que nao le campo nenhum,
  // ou que traz texto de outra origem. Nao apanham um valor **composto**: um
  // parametro que concatene prosa a um facto le o campo declarado, muda com ele,
  // nao contem o intruso da via (3) e nao acrescenta importacao nenhuma.
  //
  // A revisao adversarial mediu-o: pondo
  // `factos.nomeDoServico + ", como combinamos ontem"`, os 52 ensaios ficavam
  // **verdes** — e o `includes("Corte de cabelo")` do ensaio da entrega tambem
  // passava, porque o facto continua la dentro. E a forma mais provavel de texto
  // de modelo entrar num parametro: nao a substituir um facto, a envolve-lo.
  //
  // A asserção é de **igualdade** e não de inclusão, e é isso que a torna uma
  // prova: cada parâmetro tem de ser o valor do facto, ou a formatação dele, e
  // mais nada. Qualquer carácter a mais falha.
  const instante = new Date(FACTOS.inicioAt);
  const esperados: readonly string[] = [
    FACTOS.nomeDoServico,
    dataDeLuanda(instante),
    horaDeLuanda(instante),
  ];
  assert.deepEqual([...parametrosDoLembrete(FACTOS)], [...esperados]);

  // E as formatações são elas próprias funções do facto e de mais nada: o mesmo
  // instante dá sempre a mesma cadeia, e dois instantes diferentes dão cadeias
  // diferentes. Sem isto, uma «formatação» que devolvesse uma constante
  // satisfazia a igualdade acima.
  assert.equal(dataDeLuanda(instante), dataDeLuanda(new Date(FACTOS.inicioAt)));
  assert.notEqual(dataDeLuanda(instante), dataDeLuanda(new Date("2026-12-24T16:45:00.000Z")));
  assert.notEqual(horaDeLuanda(instante), horaDeLuanda(new Date("2026-12-24T16:45:00.000Z")));
});

test("o fuso e o de Luanda, e uma marcacao as 00:30 cai no dia certo", () => {
  // O ensaio de fuso do bloco. `Africa/Luanda` e UTC+1 sem horario de verao,
  // pelo que `23:30Z` de 5 de Novembro e `00:30` do dia **6**.
  const meiaNoiteEMeia: FactosDaMarcacao = {
    nomeDoServico: "Corte de cabelo",
    inicioAt: "2026-11-05T23:30:00.000Z",
  };
  const [, data, hora] = parametrosDoLembrete(meiaNoiteEMeia);

  assert.equal(hora, "00:30");
  assert.match(data as string, /6 de novembro de 2026/);
  // **A forma que apanha a formatacao em UTC**: ela daria o dia 5. Sem esta
  // assercao, um `Intl` sem `timeZone` passava o teste acima por acidente nos
  // instantes em que os dois fusos coincidem no dia.
  assert.doesNotMatch(data as string, /5 de novembro de 2026/);
});

test("a data nao tem corrida de digitos que a regua de telefone apanhe", () => {
  // A razao pela qual o `dateStyle` e `long` e nao `medium`: `09/11/2026` sao
  // oito digitos separados por barras, e a regua do `meta-sim` apanha-os. E o
  // mesmo raciocinio do `horaDeLuanda` do KAM-115, aqui preso por asserção.
  const instante = new Date("2026-11-09T10:00:00.000Z");
  const data = dataDeLuanda(instante);
  for (const corrida of data.match(/\d+/g) ?? []) {
    assert.ok(corrida.length <= 4, `a data tem a corrida de digitos ${corrida}`);
  }
  assert.match(horaDeLuanda(instante), /^\d{2}:\d{2}$/);
});

test("um inicio_at invalido levanta em vez de produzir um parametro vazio", () => {
  // A assimetria com o `instanteDoLembrete`, que devolve `null`: la a pergunta e
  // «agendo?» e um `null` responde-lhe; aqui ja se decidiu enviar, e um
  // parametro vazio era um template **pago** com um espaco no lugar da data.
  assert.throws(
    () => parametrosDoLembrete({ ...FACTOS, inicioAt: "nao e uma data" }),
    InicioInvalidoError,
  );
});

test("a mensagem livre e o corpo aprovado com as posicoes preenchidas", () => {
  const parametros = parametrosDoLembrete(FACTOS);
  const texto = textoDoLembrete(FACTOS);

  // Nenhuma posicao fica por preencher: um `{{2}}` literal numa mensagem ao
  // cliente e o defeito que esta asserção existe para apanhar.
  assert.doesNotMatch(texto, /\{\{\d+\}\}/);
  for (const valor of parametros) {
    assert.ok(texto.includes(valor));
  }
  // E e o **mesmo** corpo: o texto livre nao e um segundo texto escrito ao lado.
  // Comparam-se as duas pontas fixas do corpo aprovado.
  assert.ok(texto.startsWith("Lembrete: tem marcação de "));
  assert.ok(CORPO_DO_TEMPLATE.startsWith("Lembrete: tem marcação de "));
  assert.ok(texto.endsWith("responda a esta mensagem."));
  assert.ok(CORPO_DO_TEMPLATE.endsWith("responda a esta mensagem."));
});
