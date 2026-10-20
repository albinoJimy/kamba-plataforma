/**
 * O adapter de ponta a ponta, com a base e a Meta por porta (KAM-015).
 *
 * As outras três baterias deste ticket medem funções puras: a matriz de
 * decisão, a monotonia, os tectos. Esta mede a **ordem** — que é a única
 * contribuição própria do `adapter.ts` — e mede-a onde se pode afirmar o que
 * um ensaio contra a base não consegue:
 *
 * 1. **O critério 6 por extenso.** «*Backoff* exponencial com *jitter*, 3
 *    tentativas; `130429` repete, `131049` não.» Contra a base, as respostas da
 *    Meta vêm do `GraphFalso` e dizem `200`; aqui a porta responde o que o
 *    critério manda, e as esperas são observáveis porque o `dormir` também é
 *    porta. **Sem este ficheiro o critério 6 só estava provado ao nível das
 *    funções `vaiRepetir` e `atrasoMs`** — isto é, provado que a regra existe,
 *    não que o adapter a usa.
 * 2. **Quantas chamadas HTTP houve, e em que momento não houve nenhuma.** Os
 *    critérios 1, 2, 7 e 8 têm todos a forma «... **sem** chamada à API», e a
 *    asserção que os prova é um contador a zero.
 * 3. **Que o registo não leva o `wamid` em claro.** É o DoD «Privacidade» e o
 *    X-11 do gate 6. Com o `Logger` real e um destino que captura, a linha
 *    escrita é inspeccionável — e o `msg_id` tem de ser o `m_` + 32
 *    hexadecimais do §3.10, não o `wamid`.
 *
 * ## Porque é que a base é falsa aqui, tendo nós uma real
 *
 * Porque o que se mede é a ordem dos passos, e para isso a base tem de ser
 * **observável**: o teste precisa de saber que a linha foi escrita *antes* da
 * chamada HTTP, e o registo de chamadas de uma porta di-lo. O que uma base
 * falsa **não** pode provar — a idempotência, a unicidade por *tenant*, a
 * monotonia sob concorrência, a RLS — está em
 * `tests_bd/outbound.bd.test.ts`, contra um PostgreSQL verdadeiro, e nenhuma
 * destas asserções a substitui.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { GraphFalso, Gerador as GeradorDeFixtures } from "@kamba/meta-sim";

import { Logger, idOpaco } from "../src/logger/index.ts";
import {
  BASE_DO_BACKOFF_MS,
  MPS_POR_CANAL,
  METRICA_CUSTO,
  METRICA_ENVIADAS,
  METRICA_JANELA_FECHADA,
  METRICA_TRAVADAS,
  SQL_AVANCAR_ESTADO,
  SQL_BLOQUEAR_TEMPLATE,
  SQL_ENFILEIRAR,
  SQL_JANELA,
  SQL_MARCAR_ENVIADA,
  SQL_MARCAR_FALHADA,
  SQL_POR_CHAVE,
  SQL_POR_WAMID,
  SQL_TEMPLATE,
  Saida,
  SemGuardaError,
  TENTATIVAS,
  VARIAVEL_DO_AMBIENTE,
  WINDOW_CLOSED,
  type Corpo,
  type Estado,
  type Pedido,
  type Pricing,
  type RespostaDaMeta,
  type Template,
} from "../src/outbound/index.ts";

const TENANT = "11111111-1111-4111-8111-111111111111";
const CANAL = "22222222-2222-4222-8222-222222222222";
const CONTACTO = "33333333-3333-4333-8333-333333333333";
const CONVERSA = "44444444-4444-4444-8444-444444444444";
const PNID = "109876543210987";
const WAMID = "wamid.HBgMMjQ0OTIzNDU2Nzg5FQIAERgSQTEyMzQ1Njc4OUFCQ0RFRgA=";

const T0 = Date.UTC(2026, 9, 20, 12, 0, 0);

/**
 * Os milissegundos que o **primeiro** envio de cada canal espera, sempre.
 *
 * `Math.ceil(1000 / 15)`. O balde do canal nasce **vazio** (ver a nota do
 * `Balde` em `limites.ts`: nascer cheio fazia uma janela de 1 s ver dezasseis
 * mensagens), logo a primeira ficha só chega 67 ms depois de o balde ser
 * criado — e o balde é criado no primeiro `pedir`, de modo que nenhum avanço do
 * relógio antes disso o enche.
 *
 * **Está aqui como constante e não escondido num `slice`** porque é um custo
 * real do desenho, está escrito no módulo, e um ensaio que o mascarasse deixava
 * de o mostrar a quem lesse. Por isso as esperas do *backoff* medem-se a partir
 * da segunda: a primeira não é do `130429`, é nossa.
 */
const ESPERA_DO_PRIMEIRO_TOKEN = Math.ceil(1000 / 15);

const TEXTO: Corpo = { tipo: "texto", texto: "Bom dia" };

/** Uma linha de `outbound_messages`, como a porta a devolve. */
interface Linha {
  id: string;
  wamid: string | null;
  kind: string;
  state: Estado;
  pricing: Pricing | null;
  error_code: number | null;
}

/**
 * A base por porta, com um registo do que lhe foi pedido e por que ordem.
 *
 * Despacha por **identidade da constante** e não por texto: comparar
 * `texto === SQL_ENFILEIRAR` falha a compilar se a constante desaparecer,
 * enquanto um `includes("INSERT")` continuava a casar com outra consulta
 * qualquer que alguém acrescentasse.
 */
class BaseFalsa {
  /** A sequência de consultas, pela ordem em que chegaram. */
  readonly pedidos: string[] = [];
  readonly linhas = new Map<string, Linha>();
  /** `window_expires_at` da conversa. `null` é «a janela nunca abriu». */
  janela: Date | null = new Date(T0 + 60 * 60 * 1000);
  template: Template | null = null;
  #proximo = 0;

  /** O nome legível de uma consulta, para o registo. */
  #nome(texto: string): string {
    const nomes: readonly [string, string][] = [
      [SQL_JANELA, "janela"],
      [SQL_TEMPLATE, "template"],
      [SQL_ENFILEIRAR, "enfileirar"],
      [SQL_POR_CHAVE, "por_chave"],
      [SQL_MARCAR_ENVIADA, "marcar_enviada"],
      [SQL_MARCAR_FALHADA, "marcar_falhada"],
      [SQL_POR_WAMID, "por_wamid"],
      [SQL_AVANCAR_ESTADO, "avancar_estado"],
      [SQL_BLOQUEAR_TEMPLATE, "bloquear_template"],
    ];
    return nomes.find(([sql]) => sql === texto)?.[1] ?? "desconhecida";
  }

  async query<T>(texto: string, valores: readonly unknown[] = []): Promise<{ rows: readonly T[] }> {
    const nome = this.#nome(texto);
    this.pedidos.push(nome);
    const linhas = (valor: unknown[]): { rows: readonly T[] } => ({
      rows: valor as readonly T[],
    });

    if (nome === "janela") {
      return linhas([{ window_expires_at: this.janela, mode: "bot" }]);
    }
    if (nome === "template") {
      return linhas(
        this.template === null
          ? []
          : [
              {
                name: this.template.name,
                lang: this.template.lang,
                category: this.template.category,
                status: this.template.status,
                quality: this.template.quality,
                bloqueado_em: this.template.bloqueadoEm,
              },
            ],
      );
    }
    if (nome === "enfileirar") {
      const chave = String(valores[4]);
      // O `ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING id`:
      // **vazio** quando a chave já passou, e é disso que o adapter conclui
      // «não chamar a Meta».
      if (this.linhas.has(chave)) return linhas([]);
      this.#proximo += 1;
      const id = `id-${this.#proximo}`;
      this.linhas.set(chave, {
        id,
        wamid: null,
        kind: String(valores[5]),
        state: "queued",
        pricing: null,
        error_code: null,
      });
      return linhas([{ id }]);
    }
    if (nome === "por_chave") {
      const linha = this.linhas.get(String(valores[1]));
      return linhas(linha === undefined ? [] : [linha]);
    }
    if (nome === "marcar_enviada") {
      const linha = this.#porId(String(valores[1]));
      if (linha !== undefined && linha.state === "queued") {
        linha.wamid = String(valores[2]);
        linha.state = "sent";
        return linhas([linha]);
      }
      return linhas([]);
    }
    if (nome === "marcar_falhada") {
      const linha = this.#porId(String(valores[1]));
      if (linha !== undefined && linha.state !== "failed") {
        linha.state = "failed";
        linha.error_code = valores[2] === null ? null : Number(valores[2]);
        return linhas([linha]);
      }
      return linhas([]);
    }
    if (nome === "por_wamid") {
      const linha = [...this.linhas.values()].find((l) => l.wamid === String(valores[1]));
      return linhas(linha === undefined ? [] : [linha]);
    }
    if (nome === "avancar_estado") {
      const linha = [...this.linhas.values()].find((l) => l.wamid === String(valores[1]));
      const permitidos = valores[3] as readonly string[];
      // O `WHERE ... AND state = ANY($4)` da base: é isto que serializa dois
      // `statuses` concorrentes, e a porta imita-o para que o adapter veja o
      // mesmo «zero linhas» que a base lhe daria se perdesse a corrida.
      if (linha === undefined || !permitidos.includes(linha.state)) return linhas([]);
      linha.state = String(valores[2]) as Estado;
      if (valores[4] !== null) linha.pricing = JSON.parse(String(valores[4])) as Pricing;
      return linhas([{ state: linha.state }]);
    }
    if (nome === "bloquear_template") {
      if (this.template === null || this.template.bloqueadoEm !== null) return linhas([]);
      this.template = { ...this.template, bloqueadoEm: new Date(T0) };
      return linhas([{ name: this.template.name }]);
    }
    return linhas([]);
  }

  #porId(id: string): Linha | undefined {
    return [...this.linhas.values()].find((l) => l.id === id);
  }
}

/** A Meta por porta: responde o que o guião disser e conta as chamadas. */
class MetaFalsa {
  chamadas = 0;
  readonly #guiao: RespostaDaMeta[];

  constructor(guiao: readonly RespostaDaMeta[]) {
    this.#guiao = [...guiao];
  }

  readonly enviar = async (): Promise<RespostaDaMeta> => {
    this.chamadas += 1;
    // O último repete-se: um guião de um elemento serve um envio ou dez.
    const resposta = this.#guiao.length > 1 ? this.#guiao.shift() : this.#guiao[0];
    return resposta ?? { ok: true, wamid: WAMID };
  };
}

/** Uma resposta `200`. */
const OK: RespostaDaMeta = { ok: true, wamid: WAMID };

/** Um `130429` (débito excedido), com ou sem `Retry-After`. */
function debito(esperar: number | null = null): RespostaDaMeta {
  return { ok: false, codigo: 130429, estadoHttp: 400, esperar };
}

/** Um `131049` — a Meta não entregou de propósito, e não se repete. */
const FREQUENCIA: RespostaDaMeta = {
  ok: false,
  codigo: 131049,
  estadoHttp: 400,
  esperar: null,
};

/** O que cada ensaio monta: o adapter, as portas e os registos. */
interface Montagem {
  readonly saida: Saida;
  readonly bd: BaseFalsa;
  readonly meta: MetaFalsa;
  /** Cada espera pedida ao `dormir`, em ms, pela ordem. */
  readonly dormiu: number[];
  /** Cada linha JSON que o `Logger` escreveu. */
  readonly registo: Record<string, unknown>[];
}

interface Opcoes {
  readonly guiao?: readonly RespostaDaMeta[];
  readonly guarda?: ((pedido: Pedido) => Promise<boolean>) | null;
  readonly bsuid?: string | null;
  readonly telefone?: string | null;
  readonly aleatorio?: number;
  readonly ambiente?: Record<string, string | undefined>;
  readonly freeTier?: { readonly usadas: number; readonly tecto: number } | null;
}

function montar(opcoes: Opcoes = {}): Montagem {
  const bd = new BaseFalsa();
  const meta = new MetaFalsa(opcoes.guiao ?? [OK]);
  const dormiu: number[] = [];
  const registo: Record<string, unknown>[] = [];
  // O `Logger` **real** e em modo estrito: é o que recusa um campo fora da
  // *allowlist*. Um registo falso aqui não provava nada sobre a política —
  // provava que o teste sabe guardar objectos.
  const log = new Logger("gwy", {
    estrito: true,
    relogio: () => new Date(T0),
    destino: {
      write: (texto: string) => {
        registo.push(JSON.parse(texto) as Record<string, unknown>);
      },
    },
  });
  // O relógio avança 100 ms a cada leitura, e isso é deliberado: com um
  // relógio parado, o balde do canal (que nasce vazio — ver `limites.ts`)
  // nunca enchia e **todos** os envios contavam como travados, misturando a
  // contagem do *token bucket* com a das repetições do `130429`. Com 100 ms
  // por leitura há ficha de sobra e o `outbound_rate_limited_total` fica a
  // medir só o que este ficheiro quer medir.
  let agora = T0;
  const saida = new Saida({
    bd,
    meta: { enviar: meta.enviar },
    destinatario: async () => ({
      bsuid: opcoes.bsuid === undefined ? "BS1" : opcoes.bsuid,
      telefone: opcoes.telefone ?? null,
    }),
    guarda: opcoes.guarda === undefined ? async () => true : opcoes.guarda,
    freeTier:
      opcoes.freeTier === undefined || opcoes.freeTier === null
        ? null
        : async () => opcoes.freeTier as { usadas: number; tecto: number },
    log,
    agora: () => {
      agora += 100;
      return new Date(agora);
    },
    aleatorio: () => opcoes.aleatorio ?? 0,
    dormir: async (ms: number) => {
      dormiu.push(ms);
    },
    ambiente: opcoes.ambiente ?? {},
  });
  return { saida, bd, meta, dormiu, registo };
}

function pedido(troca: Partial<Pedido> = {}): Pedido {
  return {
    tenantId: TENANT,
    channelId: CANAL,
    contactId: CONTACTO,
    conversationId: CONVERSA,
    phoneNumberId: PNID,
    idempotencyKey: "chave-1",
    corpo: TEXTO,
    doBot: false,
    ...troca,
  };
}

describe("o backoff do 130429, de ponta a ponta (criterio 6)", () => {
  it("**tres 130429 e depois um 200: 1 entregue, 0 duplicados** — a letra", async () => {
    // A sequência do critério, exactamente como ele a escreve: «Resposta
    // 130429 do servidor falso 3× seguida de 200: backoff exponencial com
    // jitter, 3 tentativas, 1 mensagem entregue, 0 duplicados».
    //
    // São quatro chamadas, e é isso que fixa a leitura de «3 tentativas» como
    // três **repetições** — ver `REPETICOES` em `limites.ts`. Com três
    // chamadas no total, os três `429` esgotavam-nas e o `200` nunca chegava.
    const { saida, bd, meta, dormiu } = montar({
      guiao: [debito(), debito(), debito(), OK],
    });
    const resultado = await saida.enviar(pedido());

    assert.equal(resultado.ok, true, "1 mensagem entregue");
    assert.equal(resultado.ok === true ? resultado.wamid : "", WAMID);
    assert.equal(meta.chamadas, 4, "tres repeticoes depois da primeira chamada");
    assert.equal(dormiu.slice(1).length, 3, "tres esperas de backoff");
    // «0 duplicados»: **uma** linha, e o estado dela é `sent` e não `failed`.
    assert.equal(bd.linhas.size, 1);
    assert.equal(bd.linhas.get("chave-1")?.state, "sent");
    // E as esperas crescem: 125, 250, 500 com `aleatorio = 0`.
    assert.deepEqual(dormiu.slice(1), [
      BASE_DO_BACKOFF_MS / 2,
      BASE_DO_BACKOFF_MS,
      BASE_DO_BACKOFF_MS * 2,
    ]);
  });

  it("dois 130429 e depois um 200: envia, com tres chamadas e duas esperas", async () => {
    // A letra do critério: «*backoff* exponencial com *jitter*, 3 tentativas».
    // Três chamadas e **duas** esperas, porque não se espera depois da que
    // acerta.
    const { saida, meta, dormiu } = montar({ guiao: [debito(), debito(), OK] });
    const resultado = await saida.enviar(pedido());

    assert.equal(resultado.ok, true);
    assert.equal(resultado.ok === true ? resultado.wamid : "", WAMID);
    assert.equal(meta.chamadas, 3);
    assert.equal(dormiu[0], ESPERA_DO_PRIMEIRO_TOKEN, "a primeira espera e do nosso balde");
    assert.equal(dormiu.slice(1).length, 2, "duas esperas de backoff, nao tres");
  });

  it("as duas esperas crescem exponencialmente, e sao as do BASE_DO_BACKOFF_MS", async () => {
    // Com `aleatorio = 0`, o *jitter* total dá o mínimo de cada intervalo:
    // `base/2`. A progressão é 250 -> 500, logo as esperas são 125 e 250.
    const { saida, dormiu } = montar({ guiao: [debito(), debito(), OK], aleatorio: 0 });
    await saida.enviar(pedido());

    const backoff = dormiu.slice(1);
    assert.deepEqual(backoff, [BASE_DO_BACKOFF_MS / 2, BASE_DO_BACKOFF_MS]);
    assert.ok(backoff[1]! > backoff[0]!, "a segunda espera tem de ser maior");
  });

  it("com aleatorio = 1 as esperas sao o dobro: e o jitter a mexer", async () => {
    // O *jitter* não é enfeite e isto é o que o prova no adapter: a mesma
    // sequência de respostas, dois aleatórios diferentes, duas esperas
    // diferentes. Sem ele, N processos que apanhem o mesmo `130429` voltam
    // todos no mesmo instante.
    const { saida, dormiu } = montar({ guiao: [debito(), debito(), OK], aleatorio: 1 });
    await saida.enviar(pedido());

    assert.deepEqual(dormiu.slice(1), [BASE_DO_BACKOFF_MS, BASE_DO_BACKOFF_MS * 2]);
  });

  it("o 130429 sem fim desiste: quatro chamadas, nunca cinco", async () => {
    const { saida, bd, meta, dormiu } = montar({ guiao: [debito()] });
    const resultado = await saida.enviar(pedido());

    assert.equal(resultado.ok, false);
    assert.equal(resultado.ok === false ? resultado.motivo : "", "SEND_FAILED");
    assert.equal(resultado.ok === false ? resultado.codigo : 0, 130429);
    assert.equal(meta.chamadas, TENTATIVAS);
    assert.equal(dormiu.slice(1).length, TENTATIVAS - 1);
    // E a linha fica `failed` com o código guardado: é o que o painel lê.
    const linha = bd.linhas.get("chave-1");
    assert.equal(linha?.state, "failed");
    assert.equal(linha?.error_code, 130429);
  });

  it("**o 131049 nao repete: uma chamada e so uma**", async () => {
    // A outra metade do critério 6. A Meta não entregou de propósito
    // (frequência por utilizador), e insistir é gastar débito para ser
    // recusado outra vez.
    const { saida, meta, dormiu } = montar({ guiao: [FREQUENCIA] });
    const resultado = await saida.enviar(pedido());

    assert.equal(resultado.ok, false);
    assert.equal(resultado.ok === false ? resultado.codigo : 0, 131049);
    assert.equal(meta.chamadas, 1);
    assert.deepEqual(dormiu.slice(1), [], "nao houve espera de backoff nenhuma");
  });

  it("o Retry-After manda sobre o backoff calculado", async () => {
    // `docs/tecnica/01` §16: respeitar o `Retry-After`. Dois segundos são
    // 2 000 ms de base, e com `aleatorio = 0` a espera é 1 000 — oito vezes a
    // que o `BASE_DO_BACKOFF_MS` daria na primeira tentativa.
    const { saida, dormiu } = montar({ guiao: [debito(2), OK], aleatorio: 0 });
    await saida.enviar(pedido());

    assert.deepEqual(dormiu.slice(1), [1000]);
    assert.ok(dormiu[1]! > BASE_DO_BACKOFF_MS, "um Retry-After ignorado era adivinhar");
  });

  it("**a travagem da Meta conta separada da nossa**", async () => {
    // Recusar sem contar é recusar em silêncio. E contar as duas juntas é
    // quase tão mau: `bucket` diz «o nosso tecto está apertado, pode subir» e
    // `meta` diz «o tecto dela está à frente do nosso, baixa» — decisões
    // opostas a partir do mesmo número. Este envio tem uma de cada: a espera
    // do primeiro *token* e a repetição do `130429`.
    const { saida } = montar({ guiao: [debito(), OK] });
    await saida.enviar(pedido());

    const lido = saida.metricas.ler();
    assert.equal(lido[`${METRICA_TRAVADAS}:bucket`], 1);
    assert.equal(lido[`${METRICA_TRAVADAS}:meta`], 1);
    // E **nenhuma série sem etiqueta**: um contador a somar as duas por baixo
    // era o defeito de volta.
    assert.equal(lido[METRICA_TRAVADAS], undefined);
  });

  it("um envio sem 130429 nao conta nada em meta", async () => {
    const { saida } = montar({ guiao: [OK] });
    await saida.enviar(pedido());

    const lido = saida.metricas.ler();
    assert.equal(lido[`${METRICA_TRAVADAS}:bucket`], 1);
    assert.equal(lido[`${METRICA_TRAVADAS}:meta`], undefined);
  });
});

describe("o debito de 100 envios, medido no servidor falso (criterio 5)", () => {
  /**
   * Cem envios a cem contactos diferentes, com o relógio a avançar **pelo que
   * se dormiu**, e os instantes registados **no `GraphFalso`**.
   *
   * ## Porque é que isto não é o teste de `limites.ts` outra vez
   *
   * A bateria de `limites.ts` já afirma a regra — «100 `pedir` nunca passam de
   * 15 em nenhuma janela de 1 s» — chamando `pedir` em ciclo até dar `0`. O que
   * ela **não** pode afirmar é que quem chama a respeita. E o critério 5 não
   * pede a regra: pede «100 envios em fila nunca excedem 15/s em nenhuma janela
   * de 1 s **medida no servidor falso**».
   *
   * Montar isso apanhou um defeito real: o adapter dormia **uma vez** e
   * enviava. O `pedir` devolve a espera e **não consome** quando um tecto está
   * cheio, pelo que o envio seguinte saía sem ficha — os dois primeiros de cada
   * canal no mesmo instante, e a janela de 1 s que os apanha via **dezasseis**.
   * Provar a regra numa função pura não prova que quem a chama obedece.
   *
   * O relógio avança pelo `dormir` e não pelo `setTimeout` da máquina: com o
   * tempo real, isto levava 6,7 segundos e media o escalonador do Node.
   */
  it("**nunca mais de 15 numa janela de 1 s, e drenam em >= 6,6 s**", async () => {
    const graph = new GraphFalso(new GeradorDeFixtures("outbound-debito"));
    const bd = new BaseFalsa();
    const instantes: number[] = [];
    let agora = T0;
    const saida = new Saida({
      bd,
      meta: {
        enviar: async (phoneNumberId, para, corpo) => {
          // O instante **à entrada do servidor falso**, que é onde o critério
          // manda medir.
          instantes.push(agora);
          const resposta = graph.responder({
            metodo: "POST",
            caminho: `/v23.0/${phoneNumberId}/messages`,
            consulta: {},
            corpo: { to: para.bsuid ?? "", tipo: corpo.tipo },
            cabecalhos: {},
          });
          if (resposta.estado !== 200 || resposta.corpo instanceof Uint8Array) {
            return { ok: false, codigo: 130429, estadoHttp: resposta.estado, esperar: null };
          }
          const mensagens = resposta.corpo.messages as { id: string }[];
          return { ok: true, wamid: mensagens[0]?.id ?? "" };
        },
      },
      destinatario: async () => ({ bsuid: "AO.ENSAIOENSAIOENSAIO0001", telefone: null }),
      guarda: async () => true,
      freeTier: null,
      // O relógio **não** avança na leitura: quem o move é o `dormir`. Com ele
      // a avançar por leitura, o balde enchia por fora do que se esperou e a
      // medição deixava de ser do tecto.
      agora: () => new Date(agora),
      aleatorio: () => 0,
      dormir: async (ms: number) => {
        agora += ms;
      },
      ambiente: {},
    });

    for (let i = 0; i < 100; i += 1) {
      const resultado = await saida.enviar(
        pedido({ contactId: `contacto-${i}`, idempotencyKey: `chave-${i}` }),
      );
      assert.equal(resultado.ok, true, `envio ${i}`);
    }

    // Cem chamadas atendidas pelo servidor falso, e cem linhas: nenhum envio se
    // perdeu nem se duplicou pelo caminho.
    assert.equal(instantes.length, 100);
    assert.equal(graph.envios, 100);
    assert.equal(bd.linhas.size, 100);

    // A asserção do critério, sobre **todas** as janelas de 1 s e não só as
    // alinhadas ao segundo: para cada envio, quantos couberam nos 1000 ms
    // anteriores.
    for (const fim of instantes) {
      const naJanela = instantes.filter((t) => t > fim - 1000 && t <= fim).length;
      assert.ok(
        naJanela <= MPS_POR_CANAL,
        `a janela a terminar em ${fim}ms teve ${naJanela} envios`,
      );
    }

    // «drenam em >= 6,6 s»: 100/15 = 6,67 s, que é o número do próprio
    // critério — e só se obtém com o balde do canal a nascer **vazio**.
    const drenagem = (instantes[99] ?? 0) - T0;
    assert.ok(drenagem >= 6_600, `drenou em ${drenagem}ms, menos do que o criterio pede`);
    assert.ok(drenagem < 7_200, `drenou em ${drenagem}ms, demasiado`);
  });

  it("contactos diferentes nao se travam uns aos outros pelo tecto do par", async () => {
    // O tecto do par (1 mps) nasce **cheio**, e é o que faz a primeira
    // mensagem a cada contacto não esperar um segundo. Sem isso, os cem envios
    // acima levavam 100 s em vez de 6,7 — medido.
    const { saida } = montar();
    await saida.enviar(pedido({ contactId: "a", idempotencyKey: "ka" }));
    await saida.enviar(pedido({ contactId: "b", idempotencyKey: "kb" }));
    assert.equal(saida.limites.paresEmMemoria, 2);
  });
});

describe("a ordem dos passos: onde nao ha chamada HTTP", () => {
  it("a forma recusa-se sem tocar na base nem na rede (criterio 7)", async () => {
    const corpo: Corpo = {
      tipo: "botoes",
      texto: "Escolha",
      botoes: [1, 2, 3, 4].map((n) => ({ id: `b${n}`, titulo: `B${n}` })),
    };
    const { saida, bd, meta } = montar();
    const resultado = await saida.enviar(pedido({ corpo }));

    assert.equal(resultado.ok === false ? resultado.motivo : "", "TOO_MANY_BUTTONS");
    // **Zero** consultas: nem a janela se leu. É o «falham antes de qualquer
    // chamada» do critério 7, e a base conta-se junto com a rede porque uma
    // leitura é tão desperdiçada como um POST.
    assert.deepEqual(bd.pedidos, []);
    assert.equal(meta.chamadas, 0);
  });

  it("a janela fechada da WINDOW_CLOSED sem chamada (criterio 1)", async () => {
    const { saida, bd, meta } = montar();
    bd.janela = new Date(T0 - 1000);
    const resultado = await saida.enviar(pedido());

    assert.equal(resultado.ok === false ? resultado.motivo : "", WINDOW_CLOSED);
    assert.equal(meta.chamadas, 0);
    // Leu a janela e parou: não enfileirou nada.
    assert.deepEqual(bd.pedidos, ["janela"]);
    assert.equal(saida.metricas.ler()[`${METRICA_JANELA_FECHADA}:${WINDOW_CLOSED}`], 1);
  });

  it("a mesma chave duas vezes: uma linha e **uma** chamada (criterio 2)", async () => {
    const { saida, bd, meta } = montar();
    const primeiro = await saida.enviar(pedido());
    const segundo = await saida.enviar(pedido());

    assert.equal(primeiro.ok, true);
    assert.equal(primeiro.ok === true ? primeiro.repetido : true, false);
    assert.equal(segundo.ok, true);
    assert.equal(segundo.ok === true ? segundo.repetido : false, true);
    assert.equal(meta.chamadas, 1, "a segunda chamada e o defeito que isto prende");
    assert.equal(bd.linhas.size, 1);
    // O segundo devolve o `wamid` do primeiro, e não `null`: quem repete tem
    // de poder correlacionar.
    assert.equal(segundo.ok === true ? segundo.wamid : "", WAMID);
  });

  it("**a linha e escrita antes da rede**, e e isso que faz a idempotencia", async () => {
    // Se a ordem fosse ao contrário, uma falha entre o envio e a escrita
    // deixava uma mensagem entregue sem linha — e a repetição mandava-a outra
    // vez. A sequência de consultas é a prova.
    const { saida, bd } = montar();
    await saida.enviar(pedido());

    const posicaoDoInsert = bd.pedidos.indexOf("enfileirar");
    const posicaoDoUpdate = bd.pedidos.indexOf("marcar_enviada");
    assert.ok(posicaoDoInsert >= 0 && posicaoDoUpdate > posicaoDoInsert);
    assert.deepEqual(bd.pedidos, ["janela", "enfileirar", "marcar_enviada"]);
  });

  it("sem destinatario nao ha chamada, e a linha fica failed", async () => {
    const { saida, bd, meta } = montar({ bsuid: null, telefone: null });
    const resultado = await saida.enviar(pedido());

    assert.equal(resultado.ok === false ? resultado.motivo : "", "NO_RECIPIENT");
    assert.equal(meta.chamadas, 0);
    assert.equal(bd.linhas.get("chave-1")?.state, "failed");
  });

  it("o marketing recusa-se no Piloto, sem chamada (criterio 7)", async () => {
    const { saida, bd, meta } = montar();
    bd.template = {
      name: "promo",
      lang: "pt_PT",
      category: "marketing",
      status: "approved",
      quality: "green",
      bloqueadoEm: null,
    };
    const corpo: Corpo = { tipo: "template", nome: "promo", idioma: "pt_PT", parametros: [] };
    const resultado = await saida.enviar(pedido({ corpo }));

    assert.equal(resultado.ok === false ? resultado.motivo : "", "MARKETING_NOT_ALLOWED");
    assert.equal(meta.chamadas, 0);
  });
});

describe("o guarda do KAM-018 falha fechada (criterio 8)", () => {
  it("**sem guarda, em CI, levanta** — e nao envia", async () => {
    const { saida, meta } = montar({
      guarda: null,
      ambiente: { [VARIAVEL_DO_AMBIENTE]: "ci" },
    });
    await assert.rejects(() => saida.enviar(pedido({ doBot: true })), SemGuardaError);
    assert.equal(meta.chamadas, 0);
  });

  it("sem guarda, fora de CI, recusa e conta — e tambem nao envia", async () => {
    // A diferença é deliberada: um processo de produção que levante a cada
    // envio é pior do que um que recuse e registe. Nenhum dos dois **envia**,
    // que é o que o critério protege.
    const { saida, meta, registo } = montar({ guarda: null, ambiente: {} });
    const resultado = await saida.enviar(pedido({ doBot: true }));

    assert.equal(resultado.ok === false ? resultado.motivo : "", "GUARD_REFUSED");
    assert.equal(meta.chamadas, 0);
    assert.ok(registo.some((linha) => linha["outcome"] === "sem_guarda"));
  });

  it("um envio que nao e do bot passa sem guarda: o guarda e so do assistente", async () => {
    const { saida, meta } = montar({
      guarda: null,
      ambiente: { [VARIAVEL_DO_AMBIENTE]: "ci" },
    });
    const resultado = await saida.enviar(pedido({ doBot: false }));

    assert.equal(resultado.ok, true);
    assert.equal(meta.chamadas, 1);
  });

  it("um guarda que diz nao recusa, sem chamada", async () => {
    const { saida, meta } = montar({ guarda: async () => false });
    const resultado = await saida.enviar(pedido({ doBot: true }));

    assert.equal(resultado.ok === false ? resultado.motivo : "", "GUARD_REFUSED");
    assert.equal(meta.chamadas, 0);
  });

  it("um guarda que diz sim deixa passar", async () => {
    const { saida, meta } = montar({ guarda: async () => true });
    assert.equal((await saida.enviar(pedido({ doBot: true }))).ok, true);
    assert.equal(meta.chamadas, 1);
  });
});

describe("o registo nao leva o wamid em claro (DoD «Privacidade»)", () => {
  it("o msg_id e o idOpaco do §3.10, e o wamid nao aparece em sitio nenhum", async () => {
    // O `wamid` leva o número do interlocutor em base64 (`docs/logs.md` §2.1).
    // O que vai ao registo é `m_` + 32 hexadecimais do SHA-256, e é o que o
    // X-11 do gate 6 varre.
    const { saida, registo } = montar();
    await saida.enviar(pedido());

    const enviada = registo.find((linha) => linha["outcome"] === "enviada");
    assert.ok(enviada !== undefined, "o envio tem de registar algo");
    assert.equal(enviada["msg_id"], idOpaco(WAMID));
    assert.match(String(enviada["msg_id"]), /^m_[0-9a-f]{32}$/);
    const tudo = JSON.stringify(registo);
    assert.ok(!tudo.includes(WAMID), "o wamid em claro nao pode estar no registo");
    assert.ok(!tudo.includes(CONTACTO), "o contact_id tambem nao esta na allowlist");
  });

  it("o error_code vai como **texto**, que e o que a allowlist aceita", async () => {
    const { saida, registo } = montar({ guiao: [FREQUENCIA] });
    await saida.enviar(pedido());

    const recusada = registo.find((linha) => linha["outcome"] === "envio_recusado");
    assert.equal(recusada?.["error_code"], "131049");
    assert.equal(typeof recusada?.["error_code"], "string");
  });
});

describe("a ingestao de statuses pelo adapter", () => {
  /** Um envio feito, para haver `wamid` na base. */
  async function comEnvioFeito(opcoes: Opcoes = {}): Promise<Montagem> {
    const montagem = montar(opcoes);
    await montagem.saida.enviar(pedido());
    return montagem;
  }

  function pricing(troca: Partial<Pricing> = {}): Pricing {
    return {
      billable: true,
      pricing_model: "CBP",
      type: "service",
      category: "service",
      ...troca,
    };
  }

  it("um delivered avanca e cobra uma vez", async () => {
    const { saida, bd } = await comEnvioFeito();
    const resultado = await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);

    assert.equal(resultado.avancou, true);
    assert.equal(resultado.microUsd, 4000);
    assert.equal(bd.linhas.get("chave-1")?.state, "delivered");
    assert.equal(saida.metricas.ler()[METRICA_CUSTO], 4000);
  });

  it("o delivered repetido nao avanca nem cobra", async () => {
    const { saida } = await comEnvioFeito();
    await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);
    const segundo = await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);

    assert.equal(segundo.avancou, false);
    assert.equal(segundo.microUsd, 0);
    assert.equal(saida.metricas.ler()[METRICA_CUSTO], 4000);
  });

  it("**um read depois de delivered nao cobra outra vez**", async () => {
    const { saida } = await comEnvioFeito();
    await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);
    const read = await saida.ingerir(TENANT, WAMID, "read", pricing(), PNID);

    assert.equal(read.avancou, true, "o read avanca o estado");
    assert.equal(read.microUsd, 0, "mas nao soma custo: a entrega ja contou");
  });

  it("um read **antes** do delivered cobra, e o delivered seguinte nao", async () => {
    // A Meta entrega os `statuses` sem ordem garantida. Com uma comparação
    // `=== "delivered"` em vez do atravessamento, esta mensagem nunca somava.
    const { saida } = await comEnvioFeito();
    const read = await saida.ingerir(TENANT, WAMID, "read", pricing(), PNID);
    const atrasado = await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);

    assert.equal(read.microUsd, 4000);
    assert.equal(atrasado.avancou, false);
    assert.equal(saida.metricas.ler()[METRICA_CUSTO], 4000);
  });

  it("um wamid que nao existe nao faz nada", async () => {
    const { saida } = await comEnvioFeito();
    const resultado = await saida.ingerir(TENANT, "wamid.NAO_EXISTE", "delivered", null, PNID);
    assert.deepEqual(resultado, { avancou: false, microUsd: 0 });
  });

  it("dentro do free tier um service nao custa", async () => {
    const { saida } = await comEnvioFeito({ freeTier: { usadas: 10, tecto: 1000 } });
    const resultado = await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);

    assert.equal(resultado.avancou, true);
    assert.equal(resultado.microUsd, 0);
    assert.equal(saida.metricas.ler()[METRICA_CUSTO], undefined);
  });

  it("acima do free tier custa", async () => {
    const { saida } = await comEnvioFeito({ freeTier: { usadas: 1000, tecto: 1000 } });
    const resultado = await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);
    assert.equal(resultado.microUsd, 4000);
  });

  it("uma categoria de pricing desconhecida avanca, nao cobra e **avisa**", async () => {
    const { saida, registo } = await comEnvioFeito();
    const resultado = await saida.ingerir(
      TENANT,
      WAMID,
      "delivered",
      pricing({ category: "conversa_nova_da_meta" }),
      PNID,
    );

    assert.equal(resultado.avancou, true);
    assert.equal(resultado.microUsd, 0);
    assert.ok(registo.some((linha) => linha["outcome"] === "pricing_desconhecido"));
  });

  it("um failed depois de delivered fica failed e nao cobra", async () => {
    const { saida, bd } = await comEnvioFeito();
    await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);
    const falhou = await saida.ingerir(TENANT, WAMID, "failed", null, PNID);

    assert.equal(falhou.avancou, true);
    assert.equal(falhou.microUsd, 0);
    assert.equal(bd.linhas.get("chave-1")?.state, "failed");
    // E de `failed` já não se sai.
    const depois = await saida.ingerir(TENANT, WAMID, "delivered", pricing(), PNID);
    assert.equal(depois.avancou, false);
  });
});

describe("o bloqueio de template recategorizado (criterio 9)", () => {
  function comTemplate(): Montagem {
    const montagem = montar();
    montagem.bd.template = {
      name: "confirmacao_de_pedido",
      lang: "pt_PT",
      category: "utility",
      status: "approved",
      quality: "green",
      bloqueadoEm: null,
    };
    return montagem;
  }

  it("recategorizar para marketing bloqueia e avisa", async () => {
    const { saida, bd, registo } = comTemplate();
    const bloqueou = await saida.bloquearTemplate(
      TENANT,
      "confirmacao_de_pedido",
      "pt_PT",
      "marketing",
    );

    assert.equal(bloqueou, true);
    assert.notEqual(bd.template?.bloqueadoEm, null);
    assert.ok(registo.some((linha) => linha["outcome"] === "template_bloqueado"));
  });

  it("e idempotente: a Meta reenvia o webhook", async () => {
    const { saida } = comTemplate();
    assert.equal(
      await saida.bloquearTemplate(TENANT, "confirmacao_de_pedido", "pt_PT", "marketing"),
      true,
    );
    assert.equal(
      await saida.bloquearTemplate(TENANT, "confirmacao_de_pedido", "pt_PT", "marketing"),
      false,
      "a segunda vez nao volta a bloquear nem a avisar",
    );
  });

  it("recategorizar para utility nao bloqueia: esta no Piloto", async () => {
    const { saida, bd } = comTemplate();
    const bloqueou = await saida.bloquearTemplate(
      TENANT,
      "confirmacao_de_pedido",
      "pt_PT",
      "utility",
    );

    assert.equal(bloqueou, false);
    assert.equal(bd.template?.bloqueadoEm, null);
    // E nem chegou à base: a decisão é da lista de categorias do Piloto.
    assert.ok(!bd.pedidos.includes("bloquear_template"));
  });

  it("um template bloqueado deixa de sair", async () => {
    // O bloqueio e a recusa, em sequência, que é o que o critério 9 pede por
    // inteiro: «bloqueia o uso e alerta».
    const montagem = comTemplate();
    await montagem.saida.bloquearTemplate(TENANT, "confirmacao_de_pedido", "pt_PT", "marketing");
    const corpo: Corpo = {
      tipo: "template",
      nome: "confirmacao_de_pedido",
      idioma: "pt_PT",
      parametros: [],
    };
    const resultado = await montagem.saida.enviar(pedido({ corpo, idempotencyKey: "chave-2" }));

    // `MARKETING_NOT_ALLOWED` e não `TEMPLATE_BLOCKED`: o bloqueio mudou a
    // categoria para `marketing`, e é a categoria que morde primeiro. As duas
    // recusam — e o `TEMPLATE_BLOCKED` tem o seu caso na bateria da decisão,
    // onde o template pode ficar `approved` e `utility` com `bloqueado_em`.
    assert.equal(resultado.ok, false);
    assert.equal(montagem.meta.chamadas, 0);
  });
});

describe("as metricas do envio", () => {
  it("um envio conta em outbound_sent_total pela categoria", async () => {
    const { saida } = montar();
    await saida.enviar(pedido());
    assert.equal(saida.metricas.ler()[`${METRICA_ENVIADAS}:service`], 1);
  });

  it("a duracao e medida, e nao fica no -1 de «nunca medido»", async () => {
    const { saida } = montar();
    await saida.enviar(pedido());
    const duracao = saida.metricas.ler()["outbound_latency_ms"];
    assert.ok(typeof duracao === "number" && duracao >= 0, String(duracao));
  });

  it("a duracao e medida **mesmo quando o envio levanta**", async () => {
    // O `finally` do `enviar`. Sem ele, o painel perdia exactamente as
    // execuções que interessam.
    const { saida } = montar({
      guarda: null,
      ambiente: { [VARIAVEL_DO_AMBIENTE]: "ci" },
    });
    await assert.rejects(() => saida.enviar(pedido({ doBot: true })));
    assert.ok((saida.metricas.ler()["outbound_latency_ms"] ?? -1) >= 0);
  });

  it("a exposicao tem as cinco, e o custo **sem etiqueta de tenant**", async () => {
    const { saida } = montar();
    await saida.enviar(pedido());
    const texto = saida.metricas.exposicao();

    for (const nome of [
      METRICA_ENVIADAS,
      METRICA_JANELA_FECHADA,
      METRICA_TRAVADAS,
      METRICA_CUSTO,
      "outbound_latency_ms",
    ]) {
      assert.ok(texto.includes(`# TYPE ${nome} `), nome);
    }
    // A asserção que prende o desenho: o DoD escreve
    // `meta_cost_usd_total{tenant}` e não é implementável — as bibliotecas de
    // métricas recusam por gramática uma etiqueta com UUID, e o `OBS-I`
    // proíbe-a. O por-tenant sai do `SQL_CUSTO_DO_TENANT`.
    assert.ok(!texto.includes("meta_cost_usd_total{"), "nenhuma etiqueta no custo");
    // E a da travagem **leva** etiqueta, com o nome escrito.
    assert.ok(texto.includes(`${METRICA_TRAVADAS}{origem="bucket"}`), texto);
    assert.ok(!texto.includes(TENANT), "nenhum tenant_id na exposicao");
  });
});
