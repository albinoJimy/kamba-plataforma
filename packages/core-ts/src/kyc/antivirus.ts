/**
 * O antivírus do *pipeline*: o protocolo `INSTREAM` do `clamd` (KAM-087,
 * critério 1).
 *
 * O ClamAV é GPL-2.0 e corre como **processo à parte**, falado por TCP: não se
 * liga nem se distribui, que é o «usados só internamente» da DoD. A conversa é
 * a documentada: `zINSTREAM\0`, o ficheiro em pedaços de 4 octetos de tamanho
 * em *big-endian* mais os dados, quatro zeros a fechar, e uma resposta
 * `stream: OK` ou `stream: <assinatura> FOUND`.
 *
 * **Falha fechada.** Uma ligação recusada, um tempo esgotado, uma resposta
 * `ERROR` ou uma que não se reconhece **lançam** — nunca devolvem «limpo».
 *
 * O que está medido é o protocolo contra um servidor falso no próprio ensaio.
 * Contra um `clamd` real é **NÃO VERIFICADO**: não corre no CI.
 */

import { connect } from "node:net";

import type { Antivirus, VeredictoDoAntivirus } from "./contrato.ts";

/** O tamanho de cada pedaço enviado. Abaixo do `StreamMaxLength` por omissão. */
export const PEDACO = 64 * 1024;

export class AntivirusIndisponivelError extends Error {
  override readonly name = "AntivirusIndisponivelError";
  constructor(motivo: string) {
    super(`antivirus indisponivel: ${motivo}`);
  }
}

/** Interpreta a resposta do `clamd`. Exportada para o ensaio. */
export function veredictoDe(resposta: string): VeredictoDoAntivirus {
  const r = resposta.replace(/\0/g, "").trim();
  if (r === "stream: OK") return { limpo: true };
  const m = /^stream: (.{1,200}) FOUND$/.exec(r);
  if (m) return { limpo: false, assinatura: m[1]! };
  throw new AntivirusIndisponivelError("resposta nao reconhecida");
}

export class AntivirusClamd implements Antivirus {
  readonly #host: string;
  readonly #porta: number;
  readonly #tempoMs: number;

  constructor(o: { readonly host: string; readonly porta: number; readonly tempoMs?: number }) {
    this.#host = o.host;
    this.#porta = o.porta;
    this.#tempoMs = o.tempoMs ?? 30_000;
  }

  verificar(bytes: Uint8Array): Promise<VeredictoDoAntivirus> {
    return new Promise((resolver, rejeitar) => {
      const partes: Buffer[] = [];
      const s = connect({ host: this.#host, port: this.#porta });
      s.setTimeout(this.#tempoMs, () => s.destroy(new AntivirusIndisponivelError("tempo esgotado")));
      s.on("error", (e) =>
        rejeitar(e instanceof AntivirusIndisponivelError ? e : new AntivirusIndisponivelError("ligacao")),
      );
      s.on("data", (d: Buffer) => partes.push(d));
      s.on("end", () => {
        try {
          resolver(veredictoDe(Buffer.concat(partes).toString("latin1")));
        } catch (e) {
          rejeitar(e);
        }
      });
      s.on("connect", () => {
        s.write("zINSTREAM\0");
        for (let i = 0; i < bytes.length; i += PEDACO) {
          const pedaco = bytes.subarray(i, i + PEDACO);
          const tamanho = Buffer.alloc(4);
          tamanho.writeUInt32BE(pedaco.length, 0);
          s.write(tamanho);
          s.write(pedaco);
        }
        s.end(Buffer.alloc(4));
      });
    });
  }
}
