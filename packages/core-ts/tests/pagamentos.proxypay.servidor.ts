/**
 * Um servidor ProxyPay **falso**, local, para os ensaios do KAM-056.
 *
 * Nao e o *sandbox* e nao finge ser: o ticket proibe tocar no fornecedor sem
 * contrato (`ext:KAM-103`). Imita as rotas que o `evidencia/E2` §1.2 da como
 * CONFIRMADO — `POST /reference_ids`, `PUT /references/{id}` idempotente pelo
 * id, `GET /payments`, `DELETE /payments/{id}`, `Token` no RPS e `Bearer` no OPG,
 * `Idempotency-Key` — e as formas que o E2 **nao** fixa sao
 * as mesmas hipoteses que o `verify.ts` lista. Uma divergencia entre este
 * servidor e o fornecedor so aparece no *sandbox*; e por isso que a corrida la
 * fica devolvida, e nao dada por feita.
 *
 * Escuta em `127.0.0.1` numa porta efemera. As chaves sao literais de ensaio,
 * sem forma de chave de fornecedor nenhum.
 *
 * **O que este falso nao imita, dito:** a cache do `Idempotency-Key` nao
 * expira (no fornecedor sao 5 min); quem mede a janela e o adaptador, que nao
 * repete o POST depois dela. E implementa o `DELETE /references/{id}`, que e
 * NAO VERIFICADO — o ensaio do `cancelCharge` mede o adaptador, nao a rota.
 *
 * Os numeros OPG sao **ficticios, com o prefixo 999**: os do *sandbox* estao no
 * E2 e nao se repetem aqui.
 */

import { type IncomingMessage, type ServerResponse, createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

export type ContaNoServidor = {
  /** A chave corrente: autentica os pedidos e assina os callbacks. */
  readonly chave: string;
  readonly referencias: Map<string, { amount: string; end_datetime: string; custom_fields: Record<string, string> }>;
  readonly pagamentos: Map<string, Record<string, unknown>>;
  readonly reconhecidos: Set<string>;
};

export type FalhaDoServidor = "rate_limit" | "resposta_perdida" | "erro_no_delete" | null;

/** Os desfechos OPG por numero ficticio. Qualquer outro e recusado com 2010. */
export const OPG_ACEITA = "999000000";
export const OPG_TIMEOUT = "999002004";
export const OPG_RECUSA = "999003000";

type Transaccao = { id: string; status: string; code: number | null; amount: unknown };

export class ServidorProxyPay {
  readonly contas = new Map<string, ContaNoServidor>();
  readonly opgTokens = new Set<string>();
  readonly transaccoes = new Map<string, Transaccao>();
  readonly idempotencia = new Map<string, string>();
  /** Cada pedido que chegou, por ordem: `METODO caminho`. */
  readonly registo: string[] = [];
  /** Quantas referencias **novas** os `PUT` criaram. Serve o caso 7. */
  criacoes = 0;
  /** Quantas transaccoes OPG novas se criaram. */
  criacoesOpg = 0;
  #proximoId = 100_000_000;
  #falha: FalhaDoServidor = null;
  #servidor: Server | undefined;
  #base = "";

  get base(): string {
    return this.#base;
  }

  conta(chave: string): ContaNoServidor {
    let conta = this.contas.get(chave);
    if (conta === undefined) {
      conta = { chave, referencias: new Map(), pagamentos: new Map(), reconhecidos: new Set() };
      this.contas.set(chave, conta);
    }
    return conta;
  }

  programar(falha: FalhaDoServidor): void {
    this.#falha = falha;
  }

  /**
   * Um pagamento chega a fila de uma conta, como o *Mock Payment* do sandbox.
   * Devolve o objecto do pagamento; o corpo do callback e o JSON dele.
   */
  pagar(chave: string, p: {
    readonly id: string;
    readonly referencia: string;
    readonly amount: string;
    readonly datetime: string;
    readonly charge?: string;
    readonly fee?: string | null;
  }): Record<string, unknown> {
    const conta = this.conta(chave);
    const charge = p.charge ?? conta.referencias.get(p.referencia)?.custom_fields.charge;
    const pagamento: Record<string, unknown> = {
      id: p.id,
      reference_id: p.referencia,
      amount: p.amount,
      datetime: p.datetime,
      custom_fields: charge === undefined ? {} : { charge },
      entity_id: "00000",
      ...(p.fee === null ? {} : { fee: p.fee ?? "15.00" }),
      terminal_type: "ATM",
      terminal_transaction_id: "SINTETICO-1",
      terminal_location: "SINTETICO",
      terminal_id: "SINTETICO-T1",
    };
    conta.pagamentos.set(p.id, pagamento);
    conta.reconhecidos.delete(p.id);
    return pagamento;
  }

  /** O que esta na fila de uma conta, por reconhecer. */
  fila(chave: string): string[] {
    const conta = this.conta(chave);
    return [...conta.pagamentos.keys()].filter((id) => !conta.reconhecidos.has(id));
  }

  async iniciar(): Promise<void> {
    this.#servidor = createServer((pedido, resposta) => {
      void this.#tratar(pedido, resposta);
    });
    await new Promise<void>((resolver) => this.#servidor?.listen(0, "127.0.0.1", resolver));
    const endereco = this.#servidor.address() as AddressInfo;
    this.#base = `http://127.0.0.1:${endereco.port}`;
  }

  async fechar(): Promise<void> {
    const servidor = this.#servidor;
    if (servidor === undefined) return;
    servidor.closeAllConnections();
    await new Promise<void>((resolver) => servidor.close(() => resolver()));
  }

  async #tratar(pedido: IncomingMessage, resposta: ServerResponse): Promise<void> {
    const partes: Buffer[] = [];
    for await (const parte of pedido) partes.push(parte as Buffer);
    const bruto = Buffer.concat(partes).toString("utf8");
    const url = new URL(pedido.url ?? "/", "http://x");
    const caminho = url.pathname.replace(/\/+$/, "");
    const metodo = pedido.method ?? "GET";
    this.registo.push(`${metodo} ${caminho}`);

    const falha = this.#falha;
    if (falha === "rate_limit") {
      this.#falha = null;
      return _responder(resposta, 429, { erro: "demasiados pedidos" });
    }

    const autorizacao = pedido.headers.authorization ?? "";
    const segmentos = caminho.split("/");

    if (segmentos[1] === "opg") {
      if (!autorizacao.startsWith("Bearer ") || !this.opgTokens.has(autorizacao.slice(7))) {
        return _responder(resposta, 401, { erro: "OPG exige Bearer" });
      }
      return this.#opg(metodo, segmentos, pedido, bruto, resposta);
    }

    const conta = autorizacao.startsWith("Token ") ? this.contas.get(autorizacao.slice(6)) : undefined;
    if (conta === undefined) return _responder(resposta, 401, { erro: "RPS exige Token" });

    if (metodo === "POST" && caminho === "/reference_ids") {
      this.#proximoId += 1;
      return _responder(resposta, 200, `${this.#proximoId}`);
    }
    if (metodo === "PUT" && segmentos[1] === "references" && segmentos.length === 3) {
      const corpo = JSON.parse(bruto) as { amount?: unknown; end_datetime?: unknown; custom_fields?: Record<string, string> };
      if (typeof corpo.amount !== "string" || typeof corpo.end_datetime !== "string") {
        return _responder(resposta, 422, { erro: "amount e end_datetime" });
      }
      const id = segmentos[2] ?? "";
      if (!conta.referencias.has(id)) this.criacoes += 1;
      conta.referencias.set(id, {
        amount: corpo.amount,
        end_datetime: corpo.end_datetime,
        custom_fields: corpo.custom_fields ?? {},
      });
      if (falha === "resposta_perdida") {
        // **Processou e perdeu a resposta**: a referencia existe, e o cliente
        // ve a ligacao a cair.
        this.#falha = null;
        resposta.socket?.destroy();
        return;
      }
      resposta.writeHead(204).end();
      return;
    }
    if (metodo === "DELETE" && segmentos[1] === "references" && segmentos.length === 3) {
      const existia = conta.referencias.delete(segmentos[2] ?? "");
      return existia ? void resposta.writeHead(204).end() : _responder(resposta, 404, { erro: "desconhecida" });
    }
    if (metodo === "GET" && caminho === "/payments") {
      const n = Number.parseInt(url.searchParams.get("n") ?? "100", 10);
      const fila = [...conta.pagamentos.entries()]
        .filter(([id]) => !conta.reconhecidos.has(id))
        .slice(0, n)
        .map(([, p]) => p);
      return _responder(resposta, 200, fila);
    }
    if (metodo === "DELETE" && segmentos[1] === "payments" && segmentos.length === 3) {
      if (falha === "erro_no_delete") {
        this.#falha = null;
        return _responder(resposta, 503, { erro: "indisponivel" });
      }
      const id = segmentos[2] ?? "";
      if (!conta.pagamentos.has(id)) return _responder(resposta, 404, { erro: "desconhecido" });
      conta.reconhecidos.add(id);
      resposta.writeHead(204).end();
      return;
    }
    return _responder(resposta, 404, { erro: `rota desconhecida: ${metodo} ${caminho}` });
  }

  #opg(
    metodo: string,
    segmentos: string[],
    pedido: IncomingMessage,
    bruto: string,
    resposta: ServerResponse,
  ): void {
    if (metodo === "POST" && segmentos.length === 4 && segmentos[3] === "transactions") {
      const corpo = JSON.parse(bruto) as { type?: unknown; pos_id?: unknown; mobile?: unknown; amount?: unknown };
      if (corpo.type !== "payment" || typeof corpo.pos_id !== "string") {
        return _responder(resposta, 422, { erro: "type e pos_id" });
      }
      const chave = pedido.headers["idempotency-key"];
      const repetida = typeof chave === "string" ? this.idempotencia.get(chave) : undefined;
      if (repetida !== undefined) {
        return _responder(resposta, 200, this.transaccoes.get(repetida));
      }
      this.#proximoId += 1;
      const movel = `${corpo.mobile}`;
      const desfecho: [string, number | null] =
        movel === OPG_ACEITA ? ["accepted", null]
        : movel === OPG_TIMEOUT ? ["rejected", 2004]
        : movel === OPG_RECUSA ? ["rejected", 3000]
        : ["rejected", 2010];
      const transaccao: Transaccao = { id: `${this.#proximoId}`, status: desfecho[0], code: desfecho[1], amount: corpo.amount };
      this.transaccoes.set(transaccao.id, transaccao);
      this.criacoesOpg += 1;
      if (typeof chave === "string") this.idempotencia.set(chave, transaccao.id);
      if (this.#falha === "resposta_perdida") {
        this.#falha = null;
        resposta.socket?.destroy();
        return;
      }
      return _responder(resposta, 201, transaccao);
    }
    if (metodo === "GET" && segmentos.length === 5 && segmentos[3] === "transactions") {
      const transaccao = this.transaccoes.get(segmentos[4] ?? "");
      return transaccao === undefined ? _responder(resposta, 404, { erro: "desconhecida" }) : _responder(resposta, 200, transaccao);
    }
    return _responder(resposta, 404, { erro: "rota OPG desconhecida" });
  }
}

function _responder(resposta: ServerResponse, estado: number, carga: unknown): void {
  const bruto = Buffer.from(typeof carga === "string" ? carga : JSON.stringify(carga), "utf8");
  resposta.writeHead(estado, { "Content-Type": "application/json", "Content-Length": bruto.length });
  resposta.end(bruto);
}
