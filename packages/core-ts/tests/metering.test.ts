/**
 * O contador do *free tier*: as contas, o flanco, a heurística e a ligação
 * (KAM-023).
 *
 * ## O que esta bateria prova, e o que não pode provar
 *
 * As funções de `custo.ts` são puras e provam-se aqui por inteiro: a
 * estimativa, o rácio, a travessia dos limiares, a suspeita e a divergência.
 * Nenhuma delas precisa de base, e medi-las contra uma base era pagar um
 * contentor para confirmar aritmética.
 *
 * A `Metering` precisa de base, e aqui a base é **falsa**. Isso é deliberado e
 * tem um limite que vale a pena dizer antes de alguém ler as asserções e
 * concluir mais do que elas dizem:
 *
 * > **Um duplo prova que o nosso código chama o que pretendíamos chamar; não
 * > prova que o PostgreSQL faz o que pensamos.** O `FOR UPDATE` do
 * > `SQL_CONTAR`, o `IS DISTINCT FROM` com `NULL`, o `platform.ten_periodo` e a
 * > RLS **não existem** numa base falsa — existem numa real, e é lá que são
 * > provados: `tests_bd/metering.bd.test.ts`, no *gate* 8.
 *
 * O que esta montagem mede, e que a base verdadeira mede pior:
 *
 * 1. **Qual consulta foi chamada, com que parâmetros, e por que ordem.** O
 *    despacho é por **identidade da constante** e não por texto: comparar
 *    `texto === SQL_CONTAR` falha a compilar se a constante desaparecer,
 *    enquanto um `includes("UPDATE")` continuava a casar com outra qualquer.
 * 2. **Que sai um aviso por travessia e não duzentos.** Com o relógio e o
 *    contador na mão, mil e duzentos incrementos são baratos; contra a base
 *    seriam mil e duzentas transacções.
 * 3. **Que o aviso cabe na política de registo.** O `Logger` é o **real**, em
 *    modo estrito — o que recusa um campo fora da *allowlist* de nove. Um
 *    registo falso aqui não provava nada sobre a política; provava que o teste
 *    sabe guardar objectos. É esta asserção que diz que `outcome:
 *    "free_tier_aviso"` é escrevível, e não a nossa opinião sobre ele.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { Logger } from "../src/logger/index.ts";
import { FREE_TIER_DE_SERVICE } from "../src/outbound/index.ts";
import {
  AVISO_EM,
  JANELA_DE_FALHAS,
  MOTIVOS_DE_RESTRICAO,
  SQL_EMITIR_CHANNEL_UPDATED,
  SQL_LEVANTAR_RESTRICAO,
  SQL_MARCAR_RESTRICAO,
  VERSAO_CHANNEL_UPDATED,
  METRICA_ALERTAS,
  METRICA_ESTIMATIVA,
  METRICA_RACIO,
  METRICA_SUSPEITAS,
  Metering,
  MetricaDesconhecidaError,
  MetricasDoFreeTier,
  NIVEIS,
  SQL_CONTAR,
  SQL_ESTADO,
  SQL_FALHAS_RECENTES,
  SQL_RECONCILIAR,
  SufixoInvalidoError,
  divergencia,
  microUsdEstimado,
  nivelAtingido,
  racioDoFreeTier,
  suspeitaDePagamento,
} from "../src/metering/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const OUTRO_TENANT = "99999999-9999-4999-8999-999999999999";
const PNID = "109876543210987";
const T0 = new Date("2026-10-20T12:00:00.000Z");
const CANAL = "22222222-2222-4222-8222-222222222222";
const EVENTO = "01931f3e-0000-7000-8000-000000000001";

/** O micro-dólar da tarifa de `service`, para as contas abaixo não o esconderem. */
const TARIFA_SERVICE = 4_000;

// --------------------------------------------------------------- as contas

describe("as contas do free tier (criterio 4)", () => {
  it("**1.200 mensagens dao 0,80 USD** — a letra do criterio", () => {
    // 1.200 − 1.000 = 200 acima do tecto; 200 × 4 000 micro-dolares = 800 000,
    // que sao 0,80 USD. O criterio escreve este numero, e e este.
    assert.equal(microUsdEstimado(1200), 800_000);
  });

  it("dentro do tecto a estimativa e zero, e no tecto tambem", () => {
    assert.equal(microUsdEstimado(0), 0);
    assert.equal(microUsdEstimado(1), 0);
    assert.equal(microUsdEstimado(999), 0);
    // **No tecto ainda e zero**: as primeiras mil sao gratis, logo a 1.000.ª
    // tambem. E a 1.001.ª que custa, e e o que o `E1` §1 diz por extenso.
    assert.equal(microUsdEstimado(FREE_TIER_DE_SERVICE), 0);
    assert.equal(microUsdEstimado(FREE_TIER_DE_SERVICE + 1), TARIFA_SERVICE);
  });

  it("a estimativa e sempre inteira, em micro-dolares", () => {
    // O §2 do dicionario proibe virgula flutuante em dinheiro. Se algum dia
    // alguem puser a tarifa em dolares aqui, isto apanha-o.
    for (const n of [0, 999, 1000, 1001, 1200, 12_345]) {
      assert.ok(Number.isInteger(microUsdEstimado(n)), `${n} deu fraccionario`);
    }
  });

  it("um contador fraccionario nao inventa um custo fraccionario", () => {
    // Nao deve acontecer — o contador e `integer` na base —, mas se acontecer o
    // truncamento e a escolha conservadora: nao se cobra por uma mensagem que
    // nao existe.
    assert.equal(microUsdEstimado(1200.9), 800_000);
  });

  it("o racio nao se limita a 1, e isso e o que se quer ver", () => {
    assert.equal(racioDoFreeTier(800), 0.8);
    assert.equal(racioDoFreeTier(1000), 1);
    // Limitar a 1 fazia um painel mostrar «100%» tanto para quem acabou de
    // esgotar como para quem vai no dobro.
    assert.equal(racioDoFreeTier(1200), 1.2);
    assert.equal(racioDoFreeTier(2000), 2);
  });

  it("**o aviso e 800, e e derivado do tecto e nao escrito**", () => {
    assert.equal(AVISO_EM, 800);
    // A asserção que importa: se o tecto mudar — e muda por decisao da Meta,
    // nao nossa —, o aviso acompanha-o. Um `800` constante era o numero certo
    // hoje e um defeito silencioso no dia da mudanca.
    assert.equal(AVISO_EM, Math.floor(FREE_TIER_DE_SERVICE * 0.8));
  });
});

// --------------------------------------------------------------- o flanco

describe("o flanco do aviso (criterio 3)", () => {
  it("**o aviso sai na travessia dos 800, e so nela**", () => {
    assert.equal(nivelAtingido(799, 800, false), "aviso");
    // O valor nao basta: ja estar acima nao e atravessar.
    assert.equal(nivelAtingido(800, 801, false), null);
    assert.equal(nivelAtingido(1100, 1101, false), null);
  });

  it("**o esgotado sai na travessia dos 1.000, e so nela**", () => {
    assert.equal(nivelAtingido(999, 1000, false), "esgotado");
    assert.equal(nivelAtingido(1000, 1001, false), null);
  });

  it("um mes inteiro de 1.200 mensagens da **um** aviso e **um** esgotado", () => {
    // E a asserção do «sem repeticao no mesmo mes» sem guardar estado nenhum: o
    // numero 800 e atravessado por exactamente um incremento. Um `usadas >=
    // 800` em vez da travessia dava duzentos avisos.
    const contagem: Record<string, number> = { aviso: 0, esgotado: 0 };
    for (let n = 0; n < 1200; n += 1) {
      const nivel = nivelAtingido(n, n + 1, n === 0);
      if (nivel !== null) contagem[nivel] = (contagem[nivel] ?? 0) + 1;
    }
    assert.deepEqual(contagem, { aviso: 1, esgotado: 1 });
  });

  it("o reinicio mensal poe o `antes` a zero, e nao avisa por isso", () => {
    // Um canal que fechou o mes em 1.500 comeca o seguinte em 1. Sem o
    // `reiniciou`, `antes = 1500` e nenhuma travessia dos 800 era detectada
    // **todo o mes seguinte**.
    assert.equal(nivelAtingido(1500, 1, true), null);
    // E a primeira mensagem de um mes novo nao e um aviso.
    assert.equal(nivelAtingido(0, 1, true), null);
  });

  it("depois do reinicio, a travessia dos 800 volta a ser detectada", () => {
    // O defeito que o `reiniciou` evita, dito pela positiva: com o `antes`
    // normalizado, o mes novo volta a ter o seu aviso.
    assert.equal(nivelAtingido(799, 800, false), "aviso");
  });

  it("**o `reiniciou` normaliza mesmo quando o salto e grande**", () => {
    // Este caso veio da **prova por mutacao**: apagar o `reiniciou ? 0 :` fazia
    // uma mutacao **sobreviver** a todos os outros casos deste grupo. A razao e
    // que o contador da base repoe sempre a `1` (o `THEN 1` do `SQL_CONTAR`), e
    // com `para = 1` nenhum limiar e atravessado venha o `antes` de onde vier —
    // o ramo nao tinha efeito observavel por caminho nenhum.
    //
    // Observavel e: esta funcao e **exportada** para o KAM-081 a reutilizar sem
    // recalcular (criterio 8), e o seu contrato diz «o `reiniciou` poe o
    // `antes` a zero». Um consumidor que aplique um lote — um mes novo que
    // chegue com 900 de uma vez — tem de ver o aviso. Sem a normalizacao,
    // `de = 1500` e nenhuma travessia e detectada, e o canal passava o mes todo
    // sem aviso nenhum.
    assert.equal(nivelAtingido(1500, 900, true), "aviso");
    assert.equal(nivelAtingido(1500, 900, false), null);
  });

  it("um incremento que atravesse os dois devolve o mais grave", () => {
    // Nao acontece com incrementos de um, mas devolver o menos grave era a
    // escolha errada se o tecto e o aviso ficarem a menos de uma mensagem.
    assert.equal(nivelAtingido(700, 1000, false), "esgotado");
  });

  it("os dois niveis sao exactamente a lista fechada", () => {
    assert.deepEqual([...NIVEIS], ["aviso", "esgotado"]);
  });
});

// ------------------------------------------------------------- a suspeita

describe("a suspeita de metodo de pagamento (criterio 5)", () => {
  const cheia = { total: JANELA_DE_FALHAS, falhas: 4 };

  it("**4 falhas em 20, com o tecto esgotado: suspeita**", () => {
    assert.equal(suspeitaDePagamento(1000, cheia), true);
    assert.equal(suspeitaDePagamento(1200, cheia), true);
  });

  it("abaixo do tecto nao e suspeita, nem com a janela toda falhada", () => {
    // O `E1` §1 torna CONFIRMADO que a Meta deixa de entregar **depois** do
    // free tier. Antes do tecto, uma rajada de falhas e outra coisa qualquer —
    // numero invalido, janela fechada, qualidade — e atribui-la ao pagamento
    // era mandar o dono procurar um cartao por causa de um defeito nosso.
    assert.equal(suspeitaDePagamento(999, { total: 20, falhas: 20 }), false);
    assert.equal(suspeitaDePagamento(0, { total: 20, falhas: 20 }), false);
  });

  it("a janela por encher nao e suspeita, nem a 100% de falhas", () => {
    // Uma falha em uma mensagem e 100% de falhas e nao e sinal de nada. Sem
    // este minimo, o primeiro `failed` de um canal recem-esgotado disparava.
    assert.equal(suspeitaDePagamento(1200, { total: 1, falhas: 1 }), false);
    assert.equal(suspeitaDePagamento(1200, { total: 19, falhas: 19 }), false);
  });

  it("3 falhas em 20 fica abaixo do limiar", () => {
    assert.equal(suspeitaDePagamento(1200, { total: 20, falhas: 3 }), false);
  });

  it("uma janela vazia nunca e suspeita", () => {
    assert.equal(suspeitaDePagamento(1200, { total: 0, falhas: 0 }), false);
  });
});

// ---------------------------------------------------------- a divergencia

describe("a divergencia da reconciliacao (criterio 7)", () => {
  it("**sem base de comparacao devolve `null` e nao `Infinity`**", () => {
    // `Infinity` num painel e indistinguivel de uma divergencia enorme. «Nao
    // sei» e informacao melhor do que um numero errado.
    assert.equal(divergencia(10, 0), null);
    assert.equal(divergencia(0, 0), null);
  });

  it("e em valor absoluto: contar a mais e contar a menos sao os dois defeitos", () => {
    // O criterio pede «diverge <= 2%» e nao diz em que sentido. Um sinal fazia
    // um dos dois passar o limiar por ser negativo.
    assert.equal(divergencia(102, 100), 0.02);
    assert.equal(divergencia(98, 100), 0.02);
  });

  it("zero divergencia quando os dois numeros batem", () => {
    assert.equal(divergencia(1200, 1200), 0);
  });
});

// ---------------------------------------------------------------- metricas

describe("as metricas nao levam etiqueta de tenant (OBS-I)", () => {
  it("**um `tenant_id` como sufixo levanta**", () => {
    const metricas = new MetricasDoFreeTier();
    // E a razao escrita de as caixas do criterio 4 ficarem vazias: a chamada
    // nao «degrada», levanta. `docs/seguranca/ameacas_stride.md`, OBS-I.
    assert.throws(
      () => metricas.contar(METRICA_ALERTAS, TENANT),
      SufixoInvalidoError,
    );
    // E a mensagem nomeia os identificadores, para quem a ler saber porque.
    assert.throws(() => metricas.contar(METRICA_ALERTAS, TENANT), /tenant_id/);
  });

  it("uma metrica que nao existe levanta, e um gauge nao se conta", () => {
    const metricas = new MetricasDoFreeTier();
    assert.throws(
      () => metricas.contar("meta_inventada_total"),
      MetricaDesconhecidaError,
    );
    // Os *gauges* nao se incrementam: o racio e um estado, nao um acumulado.
    assert.throws(() => metricas.contar(METRICA_RACIO), MetricaDesconhecidaError);
  });

  it("**o racio e o maximo e a estimativa e a soma**, sobre os canais", () => {
    const metricas = new MetricasDoFreeTier();
    metricas.observar("canal-a", 0.1, 0);
    metricas.observar("canal-b", 1.2, 800_000);
    metricas.observar("canal-c", 0.5, 4_000);
    const lido = metricas.ler();
    // O maximo responde «qual e o canal mais perto do tecto», que e a pergunta
    // que um alerta de 80% faz. A media dava 0,6 e nao dizia que um canal esta
    // no dobro.
    assert.equal(lido[METRICA_RACIO], 1.2);
    // A soma responde «quanto e que isto vai custar». Um maximo dava 800 000 e
    // perdia os outros canais.
    assert.equal(lido[METRICA_ESTIMATIVA], 804_000);
  });

  it("observar o mesmo canal substitui em vez de somar", () => {
    const metricas = new MetricasDoFreeTier();
    metricas.observar("canal-a", 0.5, 4_000);
    metricas.observar("canal-a", 0.6, 8_000);
    // Somar fazia a estimativa crescer a cada mensagem e dizer, ao fim de um
    // mes, a soma de todos os estados intermedios.
    assert.equal(metricas.ler()[METRICA_ESTIMATIVA], 8_000);
    assert.equal(metricas.ler()[METRICA_RACIO], 0.6);
  });

  it("antes da primeira observacao os gauges dizem `-1` e nao zero", () => {
    const metricas = new MetricasDoFreeTier();
    // Um painel que mostre zero nao distingue «nenhuma mensagem» de «o processo
    // nao arrancou».
    assert.equal(metricas.ler()[METRICA_RACIO], -1);
    assert.equal(metricas.ler()[METRICA_ESTIMATIVA], -1);
  });

  it("um valor que nao e finito, ou um custo fraccionario, nao entram", () => {
    const metricas = new MetricasDoFreeTier();
    metricas.observar("canal-a", Number.NaN, 0);
    // Um `NaN` no formato de exposicao faz o Prometheus descartar a recolha
    // **toda**.
    assert.equal(metricas.ler()[METRICA_RACIO], -1);
    // E um custo fraccionario e um erro de unidade em quem chama — alguem
    // passou dolares. Arredonda-lo em silencio era transformar um defeito de
    // conversao num numero plausivel que ninguem volta a questionar.
    metricas.observar("canal-b", 0.5, 0.8);
    assert.equal(metricas.ler()[METRICA_ESTIMATIVA], -1);
  });

  it("a exposicao tem as quatro, com tipo e ajuda, e sem etiqueta de tenant", () => {
    const metricas = new MetricasDoFreeTier();
    metricas.observar("canal-a", 0.8, 0);
    metricas.contar(METRICA_ALERTAS, "aviso");
    metricas.contar(METRICA_SUSPEITAS);
    const texto = metricas.exposicao();
    for (const nome of [
      METRICA_RACIO,
      METRICA_ESTIMATIVA,
      METRICA_ALERTAS,
      METRICA_SUSPEITAS,
    ]) {
      assert.match(texto, new RegExp(`^# HELP ${nome} `, "m"), `sem HELP: ${nome}`);
      assert.match(texto, new RegExp(`^# TYPE ${nome} `, "m"), `sem TYPE: ${nome}`);
    }
    assert.match(texto, /^meta_free_tier_alert_total\{nivel="aviso"\} 1$/m);
    assert.match(texto, /^meta_free_tier_used_ratio 0\.8$/m);
    // A asserção que guarda o OBS-I: nenhum identificador no ficheiro.
    assert.ok(!texto.includes(TENANT), "o tenant apareceu na exposicao");
    assert.ok(!texto.includes(PNID), "o phone_number_id apareceu na exposicao");
  });

  it("as quatro aparecem mesmo sem nada ter acontecido", () => {
    const texto = new MetricasDoFreeTier().exposicao();
    assert.match(texto, /^meta_free_tier_alert_total 0$/m);
    assert.match(texto, /^meta_payment_suspect_total 0$/m);
    assert.match(texto, /^meta_free_tier_used_ratio -1$/m);
    assert.match(texto, /^meta_cost_usd_estimate -1$/m);
  });
});

// ------------------------------------------------------------- a ligacao

/** O período que `platform.ten_periodo` devolveria para o `T0`. */
const MES = "2026-10-01";

/**
 * A base por porta, com um registo do que lhe foi pedido e por que ordem.
 *
 * Despacha por **identidade da constante**, como a `BaseFalsa` do KAM-015 e
 * pela mesma razão: comparar `texto === SQL_CONTAR` falha a compilar se a
 * constante desaparecer.
 *
 * **O que esta classe imita, imita-o mal de propósito.** O `CASE` do reinício e
 * o `IS DISTINCT FROM` estão aqui reescritos em JavaScript, e uma reescrita não
 * prova o SQL — prova que este ficheiro sabe somar. O `FOR UPDATE`, o
 * `platform.ten_periodo` e a RLS não têm equivalente nenhum aqui. O que se
 * prova com ela é **quem chamou o quê, com que parâmetros, e o que se fez com a
 * resposta**; a semântica das consultas prova-se em
 * `tests_bd/metering.bd.test.ts`, contra um PostgreSQL verdadeiro.
 */
class BaseFalsa {
  readonly pedidos: string[] = [];
  readonly parametros: readonly unknown[][] = [];
  /** O canal, por `tenant|pnid`. Ausente = canal que não existe. */
  readonly canais = new Map<string, { usadas: number; mes: string | null }>();
  /** O que o `SQL_FALHAS_RECENTES` devolve. `null` = zero linhas. */
  janela: { total: number; falhas: number } | null = { total: 0, falhas: 0 };
  /** O que o `SQL_RECONCILIAR` devolve. `null` = zero linhas. */
  reconciliacao: { entregues: number; facturaveis: number } | null = null;
  /** O que o `SQL_MARCAR_RESTRICAO` devolve. `null` = zero linhas. */
  marca: { id: string; marcado: boolean; codigos: readonly number[] } | null = null;
  /** `true` quando o `SQL_LEVANTAR_RESTRICAO` encontra a marca. */
  levantou = true;
  /** O `event_id` que o `evt_emitir` devolve. `null` finge a ausencia. */
  eventoId: string | null = EVENTO;

  semear(tenant: string, pnid: string, usadas: number, mes: string | null): void {
    this.canais.set(`${tenant}|${pnid}`, { usadas, mes });
  }

  async query<T>(
    texto: string,
    valores: readonly unknown[] = [],
  ): Promise<{ readonly rows: readonly T[] }> {
    this.pedidos.push(texto);
    (this.parametros as unknown[][]).push([...valores]);
    const chave = `${String(valores[0])}|${String(valores[1])}`;
    const canal = this.canais.get(chave);

    if (texto === SQL_ESTADO) {
      if (canal === undefined) return { rows: [] };
      const usadas = canal.mes === MES ? canal.usadas : 0;
      return { rows: [{ usadas, mes: MES } as unknown as T] };
    }
    if (texto === SQL_CONTAR) {
      if (canal === undefined) return { rows: [] };
      const reiniciou = canal.mes !== MES;
      const antes = canal.usadas;
      canal.usadas = reiniciou ? 1 : canal.usadas + 1;
      canal.mes = MES;
      return {
        rows: [
          {
            usadas_antes: antes,
            reiniciou,
            usadas: canal.usadas,
            mes: MES,
          } as unknown as T,
        ],
      };
    }
    if (texto === SQL_FALHAS_RECENTES) {
      return { rows: this.janela === null ? [] : [this.janela as unknown as T] };
    }
    if (texto === SQL_MARCAR_RESTRICAO) {
      return { rows: this.marca === null ? [] : [this.marca as unknown as T] };
    }
    if (texto === SQL_LEVANTAR_RESTRICAO) {
      return { rows: this.levantou ? [{ id: CANAL } as unknown as T] : [] };
    }
    if (texto === SQL_EMITIR_CHANNEL_UPDATED) {
      return {
        rows:
          this.eventoId === null
            ? [{} as unknown as T]
            : [{ event_id: this.eventoId } as unknown as T],
      };
    }
    if (texto === SQL_RECONCILIAR) {
      return {
        rows: this.reconciliacao === null ? [] : [this.reconciliacao as unknown as T],
      };
    }
    throw new Error(`consulta inesperada: ${texto.slice(0, 60)}`);
  }
}

interface Montagem {
  readonly bd: BaseFalsa;
  readonly metering: Metering;
  readonly metricas: MetricasDoFreeTier;
  readonly registo: Record<string, unknown>[];
}

function montar(): Montagem {
  const bd = new BaseFalsa();
  const metricas = new MetricasDoFreeTier();
  const registo: Record<string, unknown>[] = [];
  // O `Logger` **real** e em modo estrito: e o que recusa um campo fora da
  // *allowlist* de nove. E ele que prova que o aviso deste ticket e
  // escrivivel, e nao a nossa opiniao sobre ele.
  const log = new Logger("gwy", {
    estrito: true,
    relogio: () => T0,
    destino: {
      write: (texto: string) => {
        registo.push(JSON.parse(texto) as Record<string, unknown>);
      },
    },
  });
  const metering = new Metering({ bd, log, metricas, agora: () => T0 });
  return { bd, metering, metricas, registo };
}

describe("o contador, pela porta (criterios 1, 2 e 3)", () => {
  it("**mil e duzentas entregas dao contador 1.200** — a letra do criterio 1", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    let ultima = 0;
    for (let n = 0; n < 1200; n += 1) {
      const contagem = await metering.contar(TENANT, PNID);
      assert.ok(contagem !== null);
      ultima = contagem.usadas;
    }
    assert.equal(ultima, 1200);
    assert.equal((await metering.estado(TENANT, PNID)).usadas, 1200);
  });

  it("**um aviso e um esgotado em 1.200 entregas**, e nenhum repetido", async () => {
    const { bd, metering, metricas, registo } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    const niveis: string[] = [];
    for (let n = 0; n < 1200; n += 1) {
      const contagem = await metering.contar(TENANT, PNID);
      if (contagem?.nivel != null) niveis.push(contagem.nivel);
    }
    assert.deepEqual(niveis, ["aviso", "esgotado"]);
    const lido = metricas.ler();
    assert.equal(lido[`${METRICA_ALERTAS}:aviso`], 1);
    assert.equal(lido[`${METRICA_ALERTAS}:esgotado`], 1);
    // E dois registos, nao mil e duzentos.
    const avisos = registo.filter((l) => String(l.outcome).startsWith("free_tier_"));
    assert.equal(avisos.length, 2);
  });

  it("**o aviso passa a lista branca de nove campos** — e nao leva o canal", async () => {
    const { bd, metering, registo } = montar();
    bd.semear(TENANT, PNID, AVISO_EM - 1, MES);
    await metering.contar(TENANT, PNID);
    const aviso = registo.find((l) => l.outcome === "free_tier_aviso");
    assert.ok(aviso !== undefined, `nao houve aviso: ${JSON.stringify(registo)}`);
    assert.equal(aviso.tenant_id, TENANT);
    // O DoD pede «metricas e alertas sem telefone nem conteudo», e a allowlist
    // nao tem campo para o `phone_number_id`. Quem avisa o dono com os detalhes
    // e o KAM-115, por um canal que nao e o registo.
    assert.ok(!JSON.stringify(aviso).includes(PNID), "o pnid entrou no registo");
  });

  it("o incremento chama o `SQL_CONTAR`, com o tenant, o numero e o instante", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    await metering.contar(TENANT, PNID);
    assert.deepEqual(bd.pedidos, [SQL_CONTAR]);
    assert.deepEqual(bd.parametros[0], [TENANT, PNID, T0.toISOString()]);
  });

  it("sem relogio injectado, o instante vai `null` e o `now()` fica a base", async () => {
    const bd = new BaseFalsa();
    bd.semear(TENANT, PNID, 0, MES);
    const metering = new Metering({ bd });
    await metering.contar(TENANT, PNID);
    // E a razao do `coalesce($3, now())` das consultas: passar `NULL` a secas
    // punha o periodo a `NULL`, e `NULL` nao e um mes.
    assert.deepEqual(bd.parametros[0], [TENANT, PNID, null]);
  });

  it("**o mes virado le `0` sem escrever nada** — o defeito que custava dinheiro", async () => {
    const { bd, metering } = montar();
    // O canal fechou Setembro em 1.500. Ninguem corre um processo mensal para
    // por o contador a zero, logo a coluna ainda tem 1.500 no dia 1 de Outubro.
    bd.semear(TENANT, PNID, 1500, "2026-09-01");
    // Sem o `CASE` do mes, o KAM-015 lia 1.500, concluia «acima do tecto» e
    // contava custo a primeira mensagem de um mes em que ela e gratis.
    assert.equal((await metering.estado(TENANT, PNID)).usadas, 0);
    // E a leitura nao escreveu: continua a ser o `SQL_ESTADO` e so ele.
    assert.deepEqual(bd.pedidos, [SQL_ESTADO]);
  });

  it("a primeira entrega de um mes novo poe o contador a 1, e nao a 0", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 1500, "2026-09-01");
    const contagem = await metering.contar(TENANT, PNID);
    // Por `0` e deixar o incremento para a proxima perdia uma mensagem por mes
    // e por canal — e um erro de uma em mil e exactamente o tamanho que a
    // reconciliacao de 2% do criterio 7 nao distingue de ruido.
    assert.equal(contagem?.usadas, 1);
    assert.equal(contagem?.reiniciou, true);
    assert.equal(contagem?.antes, 0);
    assert.equal(contagem?.mes, MES);
    assert.equal(contagem?.nivel, null);
  });

  it("um canal nunca usado tem `free_tier_month` a `NULL` e conta como mes novo", async () => {
    const { bd, metering } = montar();
    // Um `<>` com `NULL` da `NULL`, que num `CASE WHEN` nao e verdadeiro — e o
    // canal nunca reiniciava, somando o primeiro mes ao nada. Com
    // `IS DISTINCT FROM` o `NULL` conta como «diferente».
    bd.semear(TENANT, PNID, 0, null);
    const contagem = await metering.contar(TENANT, PNID);
    assert.equal(contagem?.usadas, 1);
    assert.equal(contagem?.reiniciou, true);
  });

  it("as metricas sao observadas pelo proprio contador", async () => {
    const { bd, metering, metricas } = montar();
    bd.semear(TENANT, PNID, 1199, MES);
    await metering.contar(TENANT, PNID);
    const lido = metricas.ler();
    // Obrigar quem chama a chamar `observar` depois era deixar a metrica a
    // depender de ele se lembrar.
    assert.equal(lido[METRICA_RACIO], 1.2);
    assert.equal(lido[METRICA_ESTIMATIVA], 800_000);
  });

  it("os contadores de dois tenants nao se misturam", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 10, MES);
    bd.semear(OUTRO_TENANT, PNID, 700, MES);
    await metering.contar(TENANT, PNID);
    assert.equal((await metering.estado(TENANT, PNID)).usadas, 11);
    assert.equal((await metering.estado(OUTRO_TENANT, PNID)).usadas, 700);
    // **O que esta asserção nao prova.** Aqui os dois canais sao duas chaves de
    // um `Map`, e nenhum `Map` tem RLS. O isolamento verdadeiro — que o
    // contexto de A nao ve nem escreve a linha de B — e o X-03, e prova-se
    // contra a base em `tests_bd/metering.bd.test.ts`.
  });
});

describe("o canal que nao existe", () => {
  it("**a leitura devolve o tecto, para se contar custo** e nao o contrario", async () => {
    const { metering, registo } = montar();
    // Devolver `{ usadas: 0 }` era dar mil mensagens gratis a um canal que
    // ninguem conhece, e o custo dessas mil nao aparecia em painel nenhum ate a
    // factura chegar. Zero linhas tambem acontece com o contexto de RLS
    // trocado, e tratar isso como desconto era pior ainda.
    const estado = await metering.estado(TENANT, PNID);
    assert.equal(estado.usadas, FREE_TIER_DE_SERVICE);
    assert.equal(estado.tecto, FREE_TIER_DE_SERVICE);
    // `usadas < tecto` e falso, que e o que faz o `estados.ts` do KAM-015
    // contar o custo.
    assert.ok(!(estado.usadas < estado.tecto));
    // E nao e silencio.
    assert.ok(
      registo.some((l) => l.outcome === "free_tier_canal_desconhecido"),
      "nao registou o canal desconhecido",
    );
  });

  it("o incremento devolve `null`, e nao inventa um contador", async () => {
    const { metering } = montar();
    // Ao contrario da leitura, aqui nao ha nada a escrever, e fingir que se
    // escreveu era perder a entrega em silencio.
    assert.equal(await metering.contar(TENANT, PNID), null);
  });

  it("**a reconciliacao desiste, e nao reporta o tecto como medicao**", async () => {
    const { bd, metering } = montar();
    bd.reconciliacao = { entregues: 0, facturaveis: 0 };
    // Este caso veio da revisao adversarial. O `estado` dobra «nao sei» no
    // tecto de proposito — a porta do KAM-015 tem de devolver um numero —, mas
    // uma agregacao devolve **sempre** uma linha, pelo que o guarda de «zero
    // linhas» nunca dispara aqui. Sem a separacao, um canal desconhecido saia
    // do relatorio como `contador: 1000` contra `entregues: 0`: um numero
    // inventado apresentado como medicao.
    assert.equal(await metering.reconciliar(TENANT, PNID), null);
  });
});

describe("a deteccao, pela porta (criterio 5)", () => {
  it("**tecto esgotado e 4 falhas em 20: suspeita, contada e registada**", async () => {
    const { bd, metering, metricas, registo } = montar();
    bd.semear(TENANT, PNID, 1200, MES);
    bd.janela = { total: 20, falhas: 4 };
    assert.equal(await metering.suspeita(TENANT, PNID), true);
    // Uma heuristica de limiares **propostos** que nao deixe rasto nao se
    // consegue calibrar, e calibra-la e a razao de ela existir assim.
    assert.equal(metricas.ler()[METRICA_SUSPEITAS], 1);
    assert.ok(registo.some((l) => l.outcome === "meta_pagamento_suspeito"));
  });

  it("le o estado e a janela, por essa ordem, e com o tamanho da janela", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 1200, MES);
    bd.janela = { total: 20, falhas: 4 };
    await metering.suspeita(TENANT, PNID);
    assert.deepEqual(bd.pedidos, [SQL_ESTADO, SQL_FALHAS_RECENTES]);
    assert.deepEqual(bd.parametros[1], [TENANT, PNID, JANELA_DE_FALHAS]);
  });

  it("abaixo do tecto nao conta suspeita nenhuma", async () => {
    const { bd, metering, metricas } = montar();
    bd.semear(TENANT, PNID, 999, MES);
    bd.janela = { total: 20, falhas: 20 };
    assert.equal(await metering.suspeita(TENANT, PNID), false);
    assert.equal(metricas.ler()[METRICA_SUSPEITAS], undefined);
  });

  it("uma agregacao sem linhas nao e suspeita", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 1200, MES);
    bd.janela = null;
    assert.equal(await metering.suspeita(TENANT, PNID), false);
  });
});

describe("a reconciliacao, pela porta (criterio 7)", () => {
  it("**mede as duas divergencias, porque o criterio e ambiguo**", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 1200, MES);
    // O `pricing` testemunha as mesmas 1.200 entregas, e a Meta marcou
    // `billable` as 200 que estao acima do tecto. Tudo certo.
    bd.reconciliacao = { entregues: 1200, facturaveis: 200 };
    const r = await metering.reconciliar(TENANT, PNID);
    assert.ok(r !== null);
    assert.equal(r.contador, 1200);
    assert.equal(r.entregues, 1200);
    assert.equal(r.facturaveis, 200);
    assert.equal(r.estimadasFacturaveis, 200);
    // Comparar o contador (1.200) com o `billable` (200) directamente dava 83%
    // de divergencia num canal onde **tudo esta certo**. E por isso que sao
    // duas: a contagem compara-se com a contagem, o facturavel com o
    // facturavel.
    assert.equal(r.divergenciaDaContagem, 0);
    assert.equal(r.divergenciaDoFacturavel, 0);
    assert.equal(r.microUsdEstimado, 800_000);
  });

  it("uma contagem a mais aparece na divergencia da contagem", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 1224, MES);
    bd.reconciliacao = { entregues: 1200, facturaveis: 200 };
    const r = await metering.reconciliar(TENANT, PNID);
    // 24 em 1.200 sao 2%, que e exactamente o limiar proposto do criterio.
    assert.equal(r?.divergenciaDaContagem, 0.02);
  });

  it("um periodo sem linhas devolve `null` em vez de zeros", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 1200, MES);
    bd.reconciliacao = null;
    assert.equal(await metering.reconciliar(TENANT, PNID), null);
  });

  it("**nao recebe periodo nenhum**: o mes e o do contador, pela base", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 1200, MES);
    bd.reconciliacao = { entregues: 1200, facturaveis: 200 };
    await metering.reconciliar(TENANT, PNID);
    assert.deepEqual(bd.pedidos, [SQL_ESTADO, SQL_RECONCILIAR]);
    // O terceiro parametro e o **instante**, nao um intervalo: a consulta
    // deriva o mes com a mesma funcao que decide o do contador. A revisao
    // adversarial mostrou que um intervalo por parametro deixava pedir um mes
    // de que o contador — que e uma coluna, nao uma serie — nao sabe falar.
    assert.deepEqual(bd.parametros[1], [TENANT, PNID, T0.toISOString()]);
  });
});

describe("a marca de restricao, pela porta (criterios 5 e 6)", () => {
  it("**o `event_id` ausente nao se cala**", async () => {
    // O `evt_emitir` devolve o `event_id`, e a sua ausencia significa que o
    // evento pode nao ter chegado ao `events_outbox` — com o canal **ja
    // marcado**, isso e uma marca sem ninguem avisado. E a mesma recusa do
    // `emitirContactMerged` do KAM-014, e e um `throw` e nao um registo porque
    // quem chama tem de poder repetir.
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    bd.marca = { id: CANAL, marcado: true, codigos: [] };
    bd.eventoId = null;
    await assert.rejects(
      () => metering.marcarRestricao(TENANT, PNID, "payment_method", 131049),
      /evt_emitir nao devolveu um event_id/,
    );
  });

  it("marca, emite **uma** vez, e devolve o `event_id`", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    bd.marca = { id: CANAL, marcado: true, codigos: [131049] };
    const r = await metering.marcarRestricao(TENANT, PNID, "payment_method", 131049);
    assert.equal(r?.marcou, true);
    assert.deepEqual([...(r?.codigos ?? [])], [131049]);
    assert.equal(r?.eventoId, EVENTO);
    assert.deepEqual(bd.pedidos, [SQL_MARCAR_RESTRICAO, SQL_EMITIR_CHANNEL_UPDATED]);
    assert.deepEqual(bd.parametros[0], [TENANT, PNID, "payment_method", 131049]);
  });

  it("**um canal ja marcado nao volta a emitir**", async () => {
    // Um evento por mensagem falhada e o contrario de um alerta. O `marcado`
    // vem do `antes` da base, e aqui o fake di-lo `false`.
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    bd.marca = { id: CANAL, marcado: false, codigos: [131049, 130429] };
    const r = await metering.marcarRestricao(TENANT, PNID, "payment_method", 130429);
    assert.equal(r?.marcou, false);
    assert.equal(r?.eventoId, null);
    // E o conjunto de codigos **ainda** volta, porque pode ter crescido: e isso
    // que o criterio 5 quer, e e por isso que isto nao e um `null`.
    assert.deepEqual([...(r?.codigos ?? [])], [131049, 130429]);
    assert.deepEqual(bd.pedidos, [SQL_MARCAR_RESTRICAO]);
  });

  it("o payload do evento tem **exactamente** o que o contrato pede", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    bd.marca = { id: CANAL, marcado: true, codigos: [] };
    await metering.marcarRestricao(TENANT, PNID, "payment_method", null);
    const payload = JSON.parse(String(bd.parametros[1]?.[5])) as Record<string, unknown>;
    // `phone_number_id` e `motivo`, e mais nada. Um campo a mais da um
    // `check_violation` do `evt_emitir` ou, pior, um evento publicado com um
    // campo que nenhum consumidor conhece (KAM-007).
    assert.deepEqual(Object.keys(payload).sort(), ["motivo", "phone_number_id"]);
    assert.equal(payload.motivo, "payment_method");
    // **E nenhum dos dois e PII**: o `phone_number_id` e um identificador opaco
    // da Meta e nao um telefone, como o inventario da `0001` diz por extenso.
    assert.equal(payload.phone_number_id, PNID);
    assert.equal(bd.parametros[1]?.[1], VERSAO_CHANNEL_UPDATED);
  });

  it("um codigo que nao e inteiro vai `null` e nao suja o conjunto", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    bd.marca = { id: CANAL, marcado: true, codigos: [] };
    await metering.marcarRestricao(TENANT, PNID, "payment_method", 1.5);
    assert.equal(bd.parametros[0]?.[3], null);
  });

  it("um canal que nao existe nao se marca", async () => {
    const { metering } = montar();
    assert.equal(
      await metering.marcarRestricao(TENANT, PNID, "payment_method", null),
      null,
    );
  });

  it("levantar um motivo que nao esta posto nao emite nada", async () => {
    const { bd, metering } = montar();
    bd.semear(TENANT, PNID, 0, MES);
    bd.levantou = false;
    assert.equal(await metering.levantarRestricao(TENANT, PNID, "quality"), false);
    assert.deepEqual(bd.pedidos, [SQL_LEVANTAR_RESTRICAO]);
  });

  it("os tres motivos do dominio sao a lista fechada", () => {
    // O `CHECK` da revisao e a ultima barreira e esta lista e a primeira. A
    // `0008` e a `0009` pagaram a licao de as deixar divergir.
    assert.deepEqual([...MOTIVOS_DE_RESTRICAO], [
      "payment_method",
      "quality",
      "policy",
    ]);
  });
});
