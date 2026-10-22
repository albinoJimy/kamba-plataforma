/**
 * A qualidade do canal: a tradução, a matriz, o medidor e a ligação (KAM-021).
 *
 * ## O que esta bateria prova, e o que não pode provar
 *
 * As funções de `decisao.ts` e a tradução de `contrato.ts` são puras e
 * provam-se aqui por inteiro: o que cada valor da Meta significa, o que
 * restringe, o que repõe, o que avisa, e o rácio do escalão. Nenhuma precisa de
 * base, e medi-las contra uma base era pagar um contentor para confirmar uma
 * tabela de decisão.
 *
 * A `GestaoDeCanal` precisa de base, e aqui a base é **falsa**. Isso tem um
 * limite que vale a pena dizer antes de alguém ler as asserções e concluir mais
 * do que elas dizem:
 *
 * > **Um duplo prova que o nosso código chama o que pretendíamos chamar; não
 * > prova que o PostgreSQL faz o que pensamos.** A unicidade
 * > `(tenant_id, event_key)` que dá a idempotência do critério 6, o
 * > `WHERE estado <> 'restrito'` que serializa a transição, o
 * > `motivo_restricao = 'quality'` que impede levantar a restrição de outro
 * > ticket, e a RLS **não existem** numa base falsa. Existem numa real, e é lá
 * > que são provados: `tests_bd/qualidade.bd.test.ts`, no *gate* 8.
 *
 * O que esta montagem mede, e que a base verdadeira mede pior: **a ordem dos
 * passos** — que o registo vem antes da escrita da qualidade, e que o evento e
 * a invalidação da *cache* vêm depois da transição e só quando houve uma. O
 * despacho é por **identidade da constante** e não por texto, como no KAM-015 e
 * no KAM-023: comparar `texto === SQL_RESTRINGIR` falha a compilar se a
 * constante desaparecer.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Logger } from "../src/logger/index.ts";
import { ESTADOS_DO_CANAL, ESTADOS_DO_TENANT } from "../src/ten/index.ts";
import {
  ESTADO_ACTIVO,
  ESTADO_RESTRITO,
  EVENTOS_DE_CANAL,
  FRACCAO_DE_AVISO,
  GestaoDeCanal,
  METRICA_EVENTOS,
  METRICA_QUALIDADE,
  METRICA_RESTRICOES,
  METRICA_UTILIZACAO,
  MOTIVO_DE_QUALIDADE,
  MetricaDesconhecidaError,
  MetricasDaQualidade,
  QUALIDADES,
  SQL_CANAL,
  SQL_ESCREVER_LIMITES,
  SQL_ESCREVER_QUALIDADE,
  SQL_MARCAR_TEMPLATES,
  SQL_PAUSAR_TEMPLATE,
  SQL_REGISTAR_TRANSICAO,
  SQL_REPOR,
  SQL_RESTRINGIR,
  SQL_UNICOS_FORA_DA_JANELA,
  SufixoInvalidoError,
  TECTO_POR_ESCALAO,
  accaoDaQualidade,
  avisaDeAmarelo,
  estadoDepois,
  traduzirQualidade,
  utilizacaoDoEscalao,
} from "../src/qualidade/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const CANAL = "22222222-2222-4222-8222-222222222222";
const PNID = "109876543210987";
const T0 = new Date("2026-10-22T12:00:00.000Z");

// ------------------------------------------------------------- a tradução

describe("a traducao do vocabulario da Meta (criterio 1)", () => {
  it("**os tres que a Meta manda viram os tres canonicos**", () => {
    assert.equal(traduzirQualidade("GREEN"), "green");
    assert.equal(traduzirQualidade("YELLOW"), "yellow");
    assert.equal(traduzirQualidade("RED"), "red");
  });

  it("**um valor que nao se reconhece da `null`, e isso nao e um erro**", () => {
    // O criterio 1 chama-lhe «registado como desconhecido sem falhar». O `null`
    // e o que diz a quem chama «guarda o bruto e nao mexas no estado».
    assert.equal(traduzirQualidade("PURPLE"), null);
    assert.equal(traduzirQualidade("FLAGGED"), null);
  });

  it("**nao e um `toLowerCase()`**, e a diferenca e o criterio", () => {
    // Um `toLowerCase()` aceitava qualquer cadeia, e entao nao havia lista
    // contra a qual um valor fosse «desconhecido». O mapa e onde se ve o que se
    // sabe — e a Meta ja mudou este vocabulario uma vez: o «Flagged» foi
    // eliminado a 2025-10-07 (CONFIRMADO, `E1` §5).
    assert.equal(traduzirQualidade("green"), null);
    assert.equal(traduzirQualidade("Green"), null);
  });

  it("o que nao e cadeia nao e qualidade", () => {
    assert.equal(traduzirQualidade(null), null);
    assert.equal(traduzirQualidade(undefined), null);
    assert.equal(traduzirQualidade(3), null);
    assert.equal(traduzirQualidade({ GREEN: 1 }), null);
  });

  it("as tres qualidades canonicas sao as mesmas do template do KAM-015", () => {
    // O `message_templates.quality` da `0010` usa exactamente estas, e e
    // deliberado: a qualidade de um numero e a de um template medem a mesma
    // coisa e nao tem razao para ter dois alfabetos.
    assert.deepEqual([...QUALIDADES], ["green", "yellow", "red"]);
  });
});

// ------------------------------------------------------- a matriz do estado

describe("o que a qualidade manda fazer ao canal (criterio 2)", () => {
  it("**`red` restringe um canal activo**", () => {
    assert.equal(accaoDaQualidade("red", ESTADO_ACTIVO), "restringir");
    assert.equal(estadoDepois("restringir"), ESTADO_RESTRITO);
  });

  it("**`red` num canal ja restrito nao e transicao nova**", () => {
    // O criterio pede «1 transicao», e um `red` repetido nao e uma.
    assert.equal(accaoDaQualidade("red", ESTADO_RESTRITO), "nada");
  });

  it("**`green` e `yellow` repoem, e so se houver o que repor**", () => {
    assert.equal(accaoDaQualidade("green", ESTADO_RESTRITO), "repor");
    assert.equal(accaoDaQualidade("yellow", ESTADO_RESTRITO), "repor");
    assert.equal(estadoDepois("repor"), ESTADO_ACTIVO);
    // Num canal que ja esta activo, nao ha nada a repor.
    assert.equal(accaoDaQualidade("green", ESTADO_ACTIVO), "nada");
    assert.equal(accaoDaQualidade("yellow", ESTADO_ACTIVO), "nada");
  });

  it("**um valor desconhecido nao mexe no estado**", () => {
    // Mudar o estado por um valor que nao se compreende era pior do que nao o
    // mudar.
    for (const estado of ESTADOS_DO_CANAL) {
      assert.equal(accaoDaQualidade(null, estado), "nada", estado);
    }
  });

  it("**nunca produz `suspenso`, com 50 eventos aleatorios** — a letra do criterio", () => {
    // O criterio 2: «nunca ha transicao automatica para `suspenso` (teste com
    // 50 eventos aleatorios)». O `suspenso` e de T&S (KAM-089/097), e a
    // divergencia com o `docs/tecnica/10` §6.4 — que diz RED → `suspenso` —
    // esta registada.
    //
    // O aleatorio e **determinista**: uma semente fixa, para o caso que falhar
    // se poder repetir. Um `Math.random()` aqui dava um teste que falha uma vez
    // por mes e nunca se reproduz.
    let semente = 20261022;
    const proximo = (n: number): number => {
      semente = (semente * 1103515245 + 12345) & 0x7fffffff;
      return semente % n;
    };
    const valores = ["GREEN", "YELLOW", "RED", "PURPLE", "", "red"];
    for (let i = 0; i < 50; i += 1) {
      const bruto = valores[proximo(valores.length)] ?? "GREEN";
      const estado = ESTADOS_DO_CANAL[proximo(ESTADOS_DO_CANAL.length)] ?? ESTADO_ACTIVO;
      const accao = accaoDaQualidade(traduzirQualidade(bruto), estado);
      const depois = estadoDepois(accao);
      assert.notEqual(depois, "suspenso", `${bruto} em ${estado} deu suspenso`);
      assert.ok(
        depois === null || depois === ESTADO_RESTRITO || depois === ESTADO_ACTIVO,
        `${bruto} em ${estado} deu ${String(depois)}`,
      );
    }
  });

  it("os estados que este modulo escreve estao no dominio da `0001`", () => {
    assert.ok(ESTADOS_DO_CANAL.includes(ESTADO_RESTRITO));
    assert.ok(ESTADOS_DO_CANAL.includes(ESTADO_ACTIVO));
    // E o `suspenso` existe no dominio, e e por isso que o teste acima e uma
    // asserção e nao uma tautologia: ele **podia** ser produzido.
    assert.ok(ESTADOS_DO_TENANT.includes("suspenso"));
  });
});

describe("o aviso de amarelo (criterio 4)", () => {
  it("**avisa quando passa a ser `yellow`**", () => {
    assert.equal(avisaDeAmarelo("yellow", "green"), true);
    assert.equal(avisaDeAmarelo("yellow", "red"), true);
    assert.equal(avisaDeAmarelo("yellow", null), true);
  });

  it("**um `yellow` que ja era `yellow` nao avisa**", () => {
    // Avisar nele dava um alerta por cada webhook que a Meta reenviasse, que e
    // o contrario de um alerta — a mesma razao que o KAM-023 escreveu para o
    // `channel.updated`.
    assert.equal(avisaDeAmarelo("yellow", "yellow"), false);
  });

  it("as outras duas qualidades nao avisam", () => {
    assert.equal(avisaDeAmarelo("green", "red"), false);
    assert.equal(avisaDeAmarelo("red", "green"), false);
    assert.equal(avisaDeAmarelo(null, "green"), false);
  });
});

// --------------------------------------------------------------- o medidor

describe("o medidor do escalao (criterio 7)", () => {
  it("**200 distintos com `TIER_250` da 0,8 e avisa** — a letra do criterio", () => {
    const leitura = utilizacaoDoEscalao(200, "TIER_250");
    assert.equal(leitura.racio, 0.8);
    assert.equal(leitura.avisa, true);
    assert.equal(leitura.unicos, 200);
    assert.equal(leitura.escalao, "TIER_250");
  });

  it("abaixo de 80% nao avisa", () => {
    assert.equal(utilizacaoDoEscalao(199, "TIER_250").avisa, false);
    assert.equal(utilizacaoDoEscalao(0, "TIER_250").racio, 0);
  });

  it("acima do tecto o racio passa de 1, e isso e o que se quer ver", () => {
    // Limitar a 1 fazia um painel mostrar «100%» tanto para quem acabou de
    // esgotar como para quem vai no dobro.
    assert.equal(utilizacaoDoEscalao(500, "TIER_250").racio, 2);
  });

  it("**o `TIER_UNLIMITED` da zero por aritmetica e nao por caso especial**", () => {
    // O tecto dele e `Infinity`, e e por isso que nao ha um `if` a escrever.
    assert.equal(TECTO_POR_ESCALAO.TIER_UNLIMITED, Number.POSITIVE_INFINITY);
    const leitura = utilizacaoDoEscalao(1_000_000, "TIER_UNLIMITED");
    assert.equal(leitura.racio, 0);
    assert.equal(leitura.avisa, false);
  });

  it("**um escalao que nao se reconhece da `null` e nao zero**", () => {
    // «Nao sei» nao e «esta folgado». E a mesma escolha que a `divergencia` do
    // KAM-023 faz para o denominador zero. O bloco do ticket escreve
    // `TIER_2000` e o gerador do KAM-024 escreve `TIER_2K`: a divergencia esta
    // nas dividas documentais e **nao se resolve inventando um sinonimo**.
    for (const escalao of ["TIER_2000", "TIER_500", "", "unlimited"]) {
      const leitura = utilizacaoDoEscalao(240, escalao);
      assert.equal(leitura.racio, null, escalao);
      assert.equal(leitura.avisa, false, escalao);
    }
  });

  it("sem escalao nenhum tambem da `null`", () => {
    assert.equal(utilizacaoDoEscalao(240, null).racio, null);
  });

  it("um numero negativo de unicos nao da um racio negativo", () => {
    assert.equal(utilizacaoDoEscalao(-5, "TIER_250").racio, 0);
  });

  it("o limiar e 80% e e o mesmo do free tier do KAM-023", () => {
    assert.equal(FRACCAO_DE_AVISO, 0.8);
  });
});

// --------------------------------------------------------------- métricas

describe("as metricas da qualidade", () => {
  it("**a etiqueta `rating` passa onde a de tenant nao passava**", () => {
    // Tres valores fechados, e nenhum cresce com o trafego: o `OBS-I` recusa
    // identificadores, nao dimensoes pequenas.
    const m = new MetricasDaQualidade();
    m.observarQualidade("canal-a", "red");
    m.observarQualidade("canal-b", "green");
    m.observarQualidade("canal-c", "green");
    const lido = m.ler();
    assert.equal(lido[`${METRICA_QUALIDADE}:green`], 2);
    assert.equal(lido[`${METRICA_QUALIDADE}:red`], 1);
    assert.equal(lido[`${METRICA_QUALIDADE}:yellow`], 0);
  });

  it("**um canal que melhora sai de uma serie e entra na outra**", () => {
    // E por isso que e um *gauge* e nao um contador, e que o nome nao leva
    // `_total`: um `_total` que desce e um contador que mente.
    const m = new MetricasDaQualidade();
    m.observarQualidade("canal-a", "red");
    assert.equal(m.ler()[`${METRICA_QUALIDADE}:red`], 1);
    m.observarQualidade("canal-a", "green");
    assert.equal(m.ler()[`${METRICA_QUALIDADE}:red`], 0);
    assert.equal(m.ler()[`${METRICA_QUALIDADE}:green`], 1);
  });

  it("uma qualidade fora da lista fechada nao entra em serie nenhuma", () => {
    const m = new MetricasDaQualidade();
    m.observarQualidade("canal-a", "purple");
    for (const q of QUALIDADES) {
      assert.equal(m.ler()[`${METRICA_QUALIDADE}:${q}`], 0, q);
    }
  });

  it("**um `tenant_id` como sufixo levanta**", () => {
    const m = new MetricasDaQualidade();
    assert.throws(() => m.contar(METRICA_RESTRICOES, TENANT), SufixoInvalidoError);
    assert.throws(() => m.contar(METRICA_RESTRICOES, TENANT), /tenant_id/);
  });

  it("uma metrica que nao existe levanta, e um gauge nao se conta", () => {
    const m = new MetricasDaQualidade();
    assert.throws(() => m.contar("channel_inventada_total"), MetricaDesconhecidaError);
    assert.throws(() => m.contar(METRICA_QUALIDADE), MetricaDesconhecidaError);
  });

  it("**o racio e o maximo**, sobre os canais", () => {
    const m = new MetricasDaQualidade();
    m.observarUtilizacao("canal-a", 0.1);
    m.observarUtilizacao("canal-b", 0.9);
    m.observarUtilizacao("canal-c", 0.5);
    // «Qual e o canal mais perto do tecto» — a media dava 0,5 e nao dizia que
    // um canal esta a 90%.
    assert.equal(m.ler()[METRICA_UTILIZACAO], 0.9);
  });

  it("antes da primeira observacao o racio diz `-1` e nao zero", () => {
    assert.equal(new MetricasDaQualidade().ler()[METRICA_UTILIZACAO], -1);
  });

  it("um racio que nao e finito nao entra", () => {
    const m = new MetricasDaQualidade();
    m.observarUtilizacao("canal-a", Number.NaN);
    // Um `NaN` no formato de exposicao faz o Prometheus descartar a recolha
    // **toda**.
    assert.equal(m.ler()[METRICA_UTILIZACAO], -1);
  });

  it("a exposicao tem as quatro, com tipo e ajuda, e sem identificadores", () => {
    const m = new MetricasDaQualidade();
    m.observarQualidade(CANAL, "red");
    m.observarUtilizacao(CANAL, 0.8);
    m.contar(METRICA_RESTRICOES, MOTIVO_DE_QUALIDADE);
    m.contar(METRICA_EVENTOS, "phone_number_quality_update");
    const texto = m.exposicao();
    for (const nome of [
      METRICA_QUALIDADE,
      METRICA_UTILIZACAO,
      METRICA_RESTRICOES,
      METRICA_EVENTOS,
    ]) {
      assert.match(texto, new RegExp(`^# HELP ${nome} `, "m"), nome);
      assert.match(texto, new RegExp(`^# TYPE ${nome} `, "m"), nome);
    }
    assert.match(texto, /^channel_quality\{rating="red"\} 1$/m);
    assert.match(texto, /^channel_quality\{rating="green"\} 0$/m);
    assert.match(texto, /^channel_restricted_total\{motivo="quality"\} 1$/m);
    assert.match(texto, /^messaging_limit_usage_ratio 0\.8$/m);
    // A asserção que guarda o OBS-I: nenhum identificador no ficheiro.
    assert.ok(!texto.includes(TENANT), "o tenant apareceu na exposicao");
    assert.ok(!texto.includes(CANAL), "o canal apareceu na exposicao");
  });

  it("as quatro aparecem mesmo sem nada ter acontecido", () => {
    const texto = new MetricasDaQualidade().exposicao();
    assert.match(texto, /^channel_restricted_total 0$/m);
    assert.match(texto, /^channel_quality_event_total 0$/m);
    assert.match(texto, /^messaging_limit_usage_ratio -1$/m);
    assert.match(texto, /^channel_quality\{rating="green"\} 0$/m);
  });
});

// --------------------------------------------------------------- a ligação

/**
 * A base por porta, com um registo do que lhe foi pedido e por que ordem.
 *
 * Despacha por **identidade da constante**, como a `BaseFalsa` do KAM-015 e a
 * do KAM-023 e pela mesma razão. **O que ela imita, imita-o mal de propósito:**
 * a unicidade `(tenant_id, event_key)`, o `WHERE estado <> 'restrito'` e a RLS
 * não têm equivalente aqui. O que se prova com ela é **quem chamou o quê, por
 * que ordem, e o que se fez com a resposta**.
 */
class BaseFalsa {
  readonly pedidos: string[] = [];
  readonly parametros: readonly unknown[][] = [];
  /** O canal, ou `null` para «não existe neste contexto». */
  canal: {
    estado: string;
    quality_rating: string | null;
    messaging_limit: string | null;
    motivo_restricao: string | null;
  } | null = {
    estado: "ativo",
    quality_rating: "green",
    messaging_limit: "TIER_250",
    motivo_restricao: null,
  };
  /** `false` finge «esta chave já passou». */
  registaNova = true;
  /** `false` finge «o `UPDATE` não casou nenhuma linha». */
  transicaoCasa = true;
  /** O que o `SQL_UNICOS_FORA_DA_JANELA` devolve. */
  unicos = 0;
  /** `false` finge «não havia esse template». */
  templateCasa = true;

  async query<T>(
    texto: string,
    valores: readonly unknown[] = [],
  ): Promise<{ readonly rows: readonly T[] }> {
    this.pedidos.push(texto);
    (this.parametros as unknown[][]).push([...valores]);

    if (texto === SQL_CANAL) {
      if (this.canal === null) return { rows: [] };
      return {
        rows: [
          {
            channel_id: CANAL,
            phone_number_id: PNID,
            ...this.canal,
          } as unknown as T,
        ],
      };
    }
    if (texto === SQL_REGISTAR_TRANSICAO) {
      return { rows: this.registaNova ? [{ id: "linha" } as unknown as T] : [] };
    }
    if (texto === SQL_RESTRINGIR || texto === SQL_REPOR) {
      return { rows: this.transicaoCasa ? [{ id: CANAL } as unknown as T] : [] };
    }
    if (texto === SQL_ESCREVER_QUALIDADE || texto === SQL_ESCREVER_LIMITES) {
      return { rows: [{} as unknown as T] };
    }
    if (texto === SQL_MARCAR_TEMPLATES) {
      return { rows: [{ name: "confirmacao" } as unknown as T] };
    }
    if (texto === SQL_PAUSAR_TEMPLATE) {
      return { rows: this.templateCasa ? [{ name: "confirmacao" } as unknown as T] : [] };
    }
    if (texto === SQL_UNICOS_FORA_DA_JANELA) {
      return { rows: [{ unicos: this.unicos } as unknown as T] };
    }
    throw new Error(`consulta inesperada: ${texto.slice(0, 60)}`);
  }
}

interface Montagem {
  readonly bd: BaseFalsa;
  readonly gestao: GestaoDeCanal;
  readonly metricas: MetricasDaQualidade;
  readonly registo: Record<string, unknown>[];
  readonly emitidos: string[];
  readonly invalidados: string[];
}

function montar(): Montagem {
  const bd = new BaseFalsa();
  const metricas = new MetricasDaQualidade();
  const registo: Record<string, unknown>[] = [];
  const emitidos: string[] = [];
  const invalidados: string[] = [];
  // O `Logger` **real** e em modo estrito: e o que recusa um campo fora da
  // *allowlist* de nove. E ele que prova que os avisos deste ticket sao
  // escreviveis, e nao a nossa opiniao sobre eles.
  const log = new Logger("gwy", {
    estrito: true,
    relogio: () => T0,
    destino: {
      write: (texto: string) => {
        registo.push(JSON.parse(texto) as Record<string, unknown>);
      },
    },
  });
  const gestao = new GestaoDeCanal({
    bd,
    log,
    metricas,
    agora: () => T0,
    emitir: async (_t, _c, _p, motivo) => {
      emitidos.push(motivo);
    },
    invalidar: (canal) => {
      invalidados.push(canal);
    },
  });
  return { bd, gestao, metricas, registo, emitidos, invalidados };
}

describe("a qualidade do numero, pela porta (criterios 1, 2 e 4)", () => {
  it("**o registo vem antes da escrita da qualidade**, e a ordem e deliberada", async () => {
    // Se a qualidade se escrevesse primeiro, um evento repetido que chegasse
    // depois de o estado ja ter sido reposto reescrevia o `quality_rating` com
    // um valor velho — e a ordem dos `statuses` da Meta nao e garantida.
    const { bd, gestao } = montar();
    await gestao.qualidadeDoNumero(TENANT, PNID, "RED", "k1");
    const indiceDoRegisto = bd.pedidos.indexOf(SQL_REGISTAR_TRANSICAO);
    const indiceDaEscrita = bd.pedidos.indexOf(SQL_ESCREVER_QUALIDADE);
    assert.ok(indiceDoRegisto >= 0 && indiceDaEscrita >= 0);
    assert.ok(indiceDoRegisto < indiceDaEscrita, bd.pedidos.join(" | "));
  });

  it("**um evento repetido nao escreve nada** — a idempotencia do criterio 6", async () => {
    const { bd, gestao, emitidos } = montar();
    bd.registaNova = false;
    const r = await gestao.qualidadeDoNumero(TENANT, PNID, "RED", "k1");
    assert.equal(r?.registou, false);
    assert.equal(r?.restringiu, false);
    // Nem a qualidade, nem o estado, nem o evento.
    assert.deepEqual(bd.pedidos, [SQL_CANAL, SQL_REGISTAR_TRANSICAO]);
    assert.deepEqual(emitidos, []);
  });

  it("**`RED` restringe, emite e esquece o canal na cache**", async () => {
    const { bd, gestao, metricas, emitidos, invalidados, registo } = montar();
    const r = await gestao.qualidadeDoNumero(TENANT, PNID, "RED", "k1");
    assert.equal(r?.restringiu, true);
    assert.equal(r?.qualidade, "red");
    assert.ok(bd.pedidos.includes(SQL_RESTRINGIR));
    assert.deepEqual(emitidos, [MOTIVO_DE_QUALIDADE]);
    assert.deepEqual(invalidados, [CANAL]);
    assert.equal(metricas.ler()[`${METRICA_RESTRICOES}:quality`], 1);
    assert.ok(registo.some((l) => l.outcome === "canal_restrito_quality"));
  });

  it("**o evento sai antes da cache**, porque so ele e duravel", async () => {
    // A invalidacao e de memoria e nao sobrevive a nada; o evento e duravel
    // quando a transaccao confirmar. Invalidar primeiro deixava uma janela em
    // que a cache ja esqueceu e o evento ainda pode nao sair.
    const ordem: string[] = [];
    const bd = new BaseFalsa();
    const gestao = new GestaoDeCanal({
      bd,
      agora: () => T0,
      emitir: async () => {
        ordem.push("evento");
      },
      invalidar: () => {
        ordem.push("cache");
      },
    });
    await gestao.qualidadeDoNumero(TENANT, PNID, "RED", "k1");
    assert.deepEqual(ordem, ["evento", "cache"]);
  });

  it("**`RED` num canal ja restrito nao emite outro evento**", async () => {
    const { bd, gestao, emitidos } = montar();
    bd.canal = {
      estado: ESTADO_RESTRITO,
      quality_rating: "red",
      messaging_limit: "TIER_250",
      motivo_restricao: MOTIVO_DE_QUALIDADE,
    };
    const r = await gestao.qualidadeDoNumero(TENANT, PNID, "RED", "k2");
    assert.equal(r?.restringiu, false);
    assert.ok(!bd.pedidos.includes(SQL_RESTRINGIR));
    assert.deepEqual(emitidos, []);
  });

  it("**`GREEN` num canal restrito repoe, e emite**", async () => {
    const { bd, gestao, emitidos, registo } = montar();
    bd.canal = {
      estado: ESTADO_RESTRITO,
      quality_rating: "red",
      messaging_limit: "TIER_250",
      motivo_restricao: MOTIVO_DE_QUALIDADE,
    };
    const r = await gestao.qualidadeDoNumero(TENANT, PNID, "GREEN", "k3");
    assert.equal(r?.reposto, true);
    assert.ok(bd.pedidos.includes(SQL_REPOR));
    assert.deepEqual(emitidos, [MOTIVO_DE_QUALIDADE]);
    assert.ok(registo.some((l) => l.outcome === "canal_reposto_quality"));
  });

  it("**um valor desconhecido registra-se e nao mexe no estado** (criterio 1)", async () => {
    const { bd, gestao, emitidos, registo } = montar();
    const r = await gestao.qualidadeDoNumero(TENANT, PNID, "PURPLE", "k4");
    assert.equal(r?.registou, true);
    assert.equal(r?.qualidade, null);
    assert.equal(r?.restringiu, false);
    // Registou-se, e **mais nada**: nem a qualidade canonica nem o estado.
    assert.deepEqual(bd.pedidos, [SQL_CANAL, SQL_REGISTAR_TRANSICAO]);
    assert.deepEqual(emitidos, []);
    assert.ok(registo.some((l) => l.outcome === "qualidade_desconhecida"));
  });

  it("**o bruto da Meta e o que vai para o registo**, e nao o canonico", async () => {
    const { bd, gestao } = montar();
    await gestao.qualidadeDoNumero(TENANT, PNID, "PURPLE", "k5");
    const indice = bd.pedidos.indexOf(SQL_REGISTAR_TRANSICAO);
    // `$5` e o `valor_novo`: guardar o canonico perdia a unica informacao que o
    // criterio 1 pede para um valor desconhecido — qual era.
    assert.equal(bd.parametros[indice]?.[4], "PURPLE");
  });

  it("**`YELLOW` avisa uma vez e marca os templates** (criterio 4)", async () => {
    const { bd, gestao, registo } = montar();
    const r = await gestao.qualidadeDoNumero(TENANT, PNID, "YELLOW", "k6");
    assert.equal(r?.avisou, true);
    assert.ok(bd.pedidos.includes(SQL_MARCAR_TEMPLATES));
    assert.ok(registo.some((l) => l.outcome === "canal_qualidade_amarela"));
  });

  it("**um `YELLOW` que ja era `yellow` nao avisa nem marca**", async () => {
    const { bd, gestao, registo } = montar();
    bd.canal = {
      estado: "ativo",
      quality_rating: "yellow",
      messaging_limit: "TIER_250",
      motivo_restricao: null,
    };
    const r = await gestao.qualidadeDoNumero(TENANT, PNID, "YELLOW", "k7");
    assert.equal(r?.avisou, false);
    assert.ok(!bd.pedidos.includes(SQL_MARCAR_TEMPLATES));
    assert.ok(!registo.some((l) => l.outcome === "canal_qualidade_amarela"));
  });

  it("**os avisos passam a lista branca de nove campos**", async () => {
    const { gestao, registo } = montar();
    await gestao.qualidadeDoNumero(TENANT, PNID, "RED", "k8");
    const aviso = registo.find((l) => l.outcome === "canal_restrito_quality");
    assert.ok(aviso !== undefined, JSON.stringify(registo));
    assert.equal(aviso.tenant_id, TENANT);
    // O DoD pede «alertas e tickets sem conteudo nem telefone», e a allowlist
    // nao tem campo para o `phone_number_id`.
    assert.ok(!JSON.stringify(aviso).includes(PNID), "o pnid entrou no registo");
  });

  it("um canal que nao existe nao se trata", async () => {
    const { bd, gestao, registo } = montar();
    bd.canal = null;
    assert.equal(await gestao.qualidadeDoNumero(TENANT, PNID, "RED", "k9"), null);
    assert.ok(registo.some((l) => l.outcome === "canal_desconhecido"));
  });

  it("o evento conta na metrica, pela etiqueta", async () => {
    const { gestao, metricas } = montar();
    await gestao.qualidadeDoNumero(TENANT, PNID, "GREEN", "k10");
    assert.equal(
      metricas.ler()[`${METRICA_EVENTOS}:phone_number_quality_update`],
      1,
    );
  });
});

describe("a capacidade e o template (criterio 5)", () => {
  it("**persiste o escalao e o tecto de numeros**", async () => {
    const { bd, gestao } = montar();
    assert.equal(await gestao.capacidade(TENANT, PNID, "TIER_2K", 20, "c1"), true);
    const indice = bd.pedidos.indexOf(SQL_ESCREVER_LIMITES);
    assert.ok(indice >= 0);
    assert.deepEqual(bd.parametros[indice], [TENANT, CANAL, "TIER_2K", 20]);
  });

  it("um `null` significa «nao mexer» e nao «apagar»", async () => {
    const { bd, gestao } = montar();
    await gestao.capacidade(TENANT, PNID, "TIER_10K", null, "c2");
    const indice = bd.pedidos.indexOf(SQL_ESCREVER_LIMITES);
    assert.deepEqual(bd.parametros[indice], [TENANT, CANAL, "TIER_10K", null]);
  });

  it("um tecto que nao e inteiro vai `null`", async () => {
    const { bd, gestao } = montar();
    await gestao.capacidade(TENANT, PNID, null, 2.5, "c3");
    const indice = bd.pedidos.indexOf(SQL_ESCREVER_LIMITES);
    assert.deepEqual(bd.parametros[indice], [TENANT, CANAL, null, null]);
  });

  it("um evento repetido nao escreve", async () => {
    const { bd, gestao } = montar();
    bd.registaNova = false;
    assert.equal(await gestao.capacidade(TENANT, PNID, "TIER_2K", 20, "c4"), false);
    assert.ok(!bd.pedidos.includes(SQL_ESCREVER_LIMITES));
  });

  it("**o template pausa-se localmente**", async () => {
    const { bd, gestao, registo } = montar();
    const pausado = await gestao.qualidadeDoTemplate(
      TENANT,
      PNID,
      "confirmacao",
      "pt_PT",
      "RED",
      "t1",
    );
    assert.equal(pausado, true);
    const indice = bd.pedidos.indexOf(SQL_PAUSAR_TEMPLATE);
    // O idioma vai exacto e nao por prefixo: `pt_PT` e `pt_BR` sao templates
    // diferentes com corpos diferentes.
    assert.deepEqual(bd.parametros[indice], [TENANT, "confirmacao", "pt_PT", "red"]);
    assert.ok(registo.some((l) => l.outcome === "template_pausado"));
  });

  it("um template que nao existe nao se pausa", async () => {
    const { bd, gestao } = montar();
    bd.templateCasa = false;
    assert.equal(
      await gestao.qualidadeDoTemplate(TENANT, PNID, "x", "pt_PT", "RED", "t2"),
      false,
    );
  });
});

describe("o alerta da conta (criterio 8)", () => {
  it("**registra-se e o canal nao muda de estado**", async () => {
    const { bd, gestao, emitidos, registo } = montar();
    const tratado = await gestao.alertaDaConta(
      TENANT,
      PNID,
      "A sua conta tem uma restricao activa.",
      "a1",
    );
    assert.equal(tratado, true);
    // A segunda metade do criterio, e e a que importa: nenhuma escrita a
    // `estado` nem a `motivo_restricao`.
    assert.ok(!bd.pedidos.includes(SQL_RESTRINGIR));
    assert.ok(!bd.pedidos.includes(SQL_REPOR));
    assert.deepEqual(emitidos, []);
    assert.ok(registo.some((l) => l.outcome === "alerta_da_conta"));
  });

  it("**o texto da Meta vai para a base e nao para a linha de registo**", async () => {
    // A lista branca de nove campos nao tem campo de texto livre, e o `outcome`
    // e um identificador. O alerta pode trazer qualquer coisa escrita; a base
    // aceita-o, uma linha de *log* nao.
    const texto = "Numero suspenso por denuncias: contacte o suporte.";
    const { bd, gestao, registo } = montar();
    await gestao.alertaDaConta(TENANT, PNID, texto, "a2");
    const indice = bd.pedidos.indexOf(SQL_REGISTAR_TRANSICAO);
    assert.equal(bd.parametros[indice]?.[4], texto);
    assert.ok(
      !JSON.stringify(registo).includes(texto),
      "o texto da Meta entrou no registo de linha",
    );
  });
});

describe("a utilizacao, pela porta (criterio 7)", () => {
  it("**200 distintos com `TIER_250` avisa e observa a metrica**", async () => {
    const { bd, gestao, metricas, registo } = montar();
    bd.unicos = 200;
    const leitura = await gestao.utilizacao(TENANT, PNID);
    assert.equal(leitura?.racio, 0.8);
    assert.equal(leitura?.avisa, true);
    assert.equal(metricas.ler()[METRICA_UTILIZACAO], 0.8);
    assert.ok(registo.some((l) => l.outcome === "limite_de_mensagens_perto"));
  });

  it("um escalao desconhecido nao observa metrica nenhuma", async () => {
    const { bd, gestao, metricas } = montar();
    bd.canal = {
      estado: "ativo",
      quality_rating: "green",
      messaging_limit: "TIER_2000",
      motivo_restricao: null,
    };
    bd.unicos = 240;
    const leitura = await gestao.utilizacao(TENANT, PNID);
    assert.equal(leitura?.racio, null);
    // «Nao sei» nao entra numa serie: o `-1` continua a dizer «nunca observado».
    assert.equal(metricas.ler()[METRICA_UTILIZACAO], -1);
  });

  it("le o canal e depois os unicos, com o instante", async () => {
    const { bd, gestao } = montar();
    await gestao.utilizacao(TENANT, PNID);
    assert.deepEqual(bd.pedidos, [SQL_CANAL, SQL_UNICOS_FORA_DA_JANELA]);
    assert.deepEqual(bd.parametros[1], [TENANT, PNID, T0.toISOString()]);
  });

  it("sem relogio injectado o instante vai `null` e o `now()` fica a base", async () => {
    const bd = new BaseFalsa();
    const gestao = new GestaoDeCanal({ bd });
    await gestao.utilizacao(TENANT, PNID);
    assert.deepEqual(bd.parametros[1], [TENANT, PNID, null]);
  });
});

describe("os quatro eventos sao a lista fechada", () => {
  it("**sao exactamente os quatro do `gestao_de_canal`**", () => {
    // O `DESTINO_POR_KIND` do `entrada/contrato.ts` manda estes quatro para
    // `gestao_de_canal`, e o `channel_quality_log_evento_ck` da `0014` impoe o
    // mesmo dominio. Tres copias de um dominio divergem no dia em que uma
    // mudar, e e por isso que isto e um teste e nao uma promessa em prosa.
    assert.deepEqual([...EVENTOS_DE_CANAL], [
      "phone_number_quality_update",
      "business_capability_update",
      "account_alerts",
      "message_template_quality_update",
    ]);
  });
});
