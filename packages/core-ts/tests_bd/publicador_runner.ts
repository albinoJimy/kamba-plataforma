/**
 * O publicador, como processo, para a suite do gate (KAM-005).
 *
 * Não é um teste: é o programa que `db/tests_eventos/` lança, mata e volta a
 * lançar. Faz o mesmo que `services/worker-canal/src/publicador.ts` sem o
 * servidor HTTP — a suite lê as métricas pela base e pela fila, não por
 * `/metrics`, e abrir uma porta dentro do gate só dava uma porta a colidir
 * quando há dois processos a disputar a liderança (critério 5).
 *
 *     KAMBA_PUBLICADOR_DB_URL   ligação ao PostgreSQL, como `kamba_batch`
 *     KAMBA_QUEUE_URL           ligação à fila
 *     KAMBA_PUB_ROTULO          nome deste processo nas linhas que escreve
 *     KAMBA_PUB_REGISTO         ficheiro onde escreve essas linhas (uma por
 *                               acontecimento, em JSON). Sem ele, não escreve
 *     KAMBA_PUB_PARAR_APOS_ADD  quando é `1`, pára **entre o `add` e o
 *                               `COMMIT`** e fica assim para sempre: é a janela
 *                               que o critério 3 manda interromper com `kill -9`
 *     KAMBA_PUB_INTERVALO       ms entre ciclos (omissão: 200, o do §6.2)
 *
 * Escreve uma linha por acontecimento **num ficheiro**, em JSON, para a *suite*
 * poder ler o que aconteceu sem adivinhar por temporizações — ver `dizer`, que
 * explica porque é um ficheiro e não o `stdout`.
 */

import { Publicador } from "../src/eventos/publicador.ts";
import type { Filas, Trabalho } from "../src/eventos/filas.ts";
import { FilasBullmq } from "../src/eventos/filas_bullmq.ts";
import { METRICAS } from "../src/eventos/metricas.ts";
import { Client } from "pg";
import { appendFileSync } from "node:fs";

const ROTULO = process.env.KAMBA_PUB_ROTULO ?? "pub";
const REGISTO = process.env.KAMBA_PUB_REGISTO ?? "";

/**
 * Uma linha JSON por acontecimento, **num ficheiro** e não no `stdout`.
 *
 * O `log-lint` do *gate* 2 proíbe escrita directa no `stdout`/`stderr` fora do
 * *logger* — e tem razão: é assim que conteúdo escapa ao filtro de campos. Mas
 * o *logger* do repositório tem uma *allowlist* de campos sem onde pôr
 * «publiquei sete *jobs* na fila `evt.agr.p3`», e a *suite* precisa de ler o
 * que aconteceu sem o inferir de temporizações. A saída é um ficheiro: não é
 * `stdout`, não passa por lado nenhum que o *logger* devesse filtrar, e é
 * `db/tests_eventos/node.py` que diz onde fica.
 *
 * Nada do que vai aqui é conteúdo: nomes de fila, `jobId` (que é o `event_id`)
 * e contagens.
 */
function dizer(dados: Record<string, unknown>): void {
  const linha = `${JSON.stringify({ pub: ROTULO, ...dados })}\n`;
  if (REGISTO !== "") appendFileSync(REGISTO, linha, "utf8");
}

function exigir(nome: string): string {
  const valor = (process.env[nome] ?? "").trim();
  if (valor === "") throw new Error(`${nome} em falta`);
  return valor;
}

/**
 * Filas que param depois do primeiro `add` **bem-sucedido**.
 *
 * O *job* vai para a fila de verdade; o que não acontece é o `COMMIT`. É
 * exactamente o estado em que um `kill -9` deixa o publicador, e a promessa do
 * critério 3 é que o ciclo seguinte republica e a fila fica com **um** *job*.
 */
class FilasQueParam implements Filas {
  readonly #filas: Filas;

  constructor(filas: Filas) {
    this.#filas = filas;
  }

  async addLote(nome: string, trabalhos: readonly Trabalho[]): Promise<void> {
    await this.#filas.addLote(nome, trabalhos);
    dizer({
      evento: "parado_depois_do_add",
      fila: nome,
      jobs: trabalhos.length,
    });
    // Para sempre: quem interrompe é o `kill -9` da suite.
    await new Promise(() => {});
  }

  async fechar(): Promise<void> {
    await this.#filas.fechar();
  }
}

const bd = new Client({ connectionString: exigir("KAMBA_PUBLICADOR_DB_URL") });
await bd.connect();
const bullmq = new FilasBullmq({ url: exigir("KAMBA_QUEUE_URL") });
const parar = process.env.KAMBA_PUB_PARAR_APOS_ADD === "1";
const filas: Filas = parar ? new FilasQueParam(bullmq) : bullmq;
const intervalo = Number(process.env.KAMBA_PUB_INTERVALO ?? "200");

const paragem = new AbortController();
for (const sinal of ["SIGTERM", "SIGINT"] as const) {
  process.on(sinal, () => {
    dizer({ evento: "paragem_pedida" });
    paragem.abort();
  });
}

const publicador = new Publicador({ bd, filas, metricas: METRICAS, intervalo });
dizer({ evento: "arrancou", intervalo, parar });

// A liderança diz-se na primeira volta, para a suite não ter de esperar às
// cegas pelo critério 5.
let anunciada: boolean | null = null;
const vigia = setInterval(() => {
  if (publicador.lider !== anunciada) {
    anunciada = publicador.lider;
    dizer({ evento: "lideranca", lider: anunciada });
  }
}, 50);

try {
  await publicador.correr(paragem.signal);
} finally {
  clearInterval(vigia);
  dizer({ evento: "terminou", metricas: METRICAS.ler() });
  await filas.fechar();
  await bd.end();
}
