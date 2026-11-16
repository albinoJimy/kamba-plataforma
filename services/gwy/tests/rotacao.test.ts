/**
 * A rotação do Meta App Secret no GWY (KAM-072, critério 1), com *webhooks*
 * simulados e o relógio avançado.
 *
 * O `createApp` recebe o anel por função (`anel: () => …`), e em produção o
 * `server.ts` relê-o do cofre de 60 em 60 s. Aqui a função lê o anel do
 * `CofreEmMemoria` através de `valoresVivos`, com um relógio que o ensaio
 * avança: é a mesma ligação, sem o laço.
 *
 * O que se prova, pela ordem de uma rotação real (RB-K07 §3.1):
 *
 * 1. o cofre roda **antes** do painel da Meta: durante a janela, um corpo
 *    assinado com o segredo antigo e outro com o novo dão 200;
 * 2. revogada a anterior, o corpo assinado com o antigo dá **401** — e não entra
 *    na fila;
 * 3. a Meta re-entrega o mesmo corpo, assinado com o segredo novo, e ele entra:
 *    a recuperação é a re-entrega (até sete dias, `evidencia/E1` §5), e não um
 *    mecanismo nosso. Se a Meta re-assina com o segredo novo é **NÃO
 *    VERIFICADO**; o ensaio modela o caso em que sim.
 *
 * Nenhum segredo é literal: saem todos do `gerarValor()`.
 */

import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { describe, it } from "node:test";

import { FILA_ENTRADA, PREFIXO_DA_ASSINATURA } from "@kamba/core-ts/entrada";
import { FilasEmMemoria } from "@kamba/core-ts/eventos";
import {
  type Anel,
  CofreEmMemoria,
  DIA_MS,
  RegistoEmMemoria,
  Rotador,
  gerarValor,
  valoresVivos,
} from "@kamba/core-ts/keyring";
import { Logger } from "@kamba/core-ts/logger";

import { createApp } from "../src/app.ts";
import { SERVICE } from "../src/meta.ts";
import { REF_DO_APP_SECRET } from "../src/segredos.ts";
import { CAMINHO } from "../src/webhook.ts";

const T0 = new Date("2026-11-16T10:00:00.000Z");
const PNID = "123456789012345";
// `VERIFICACAO` e nao `TOKEN`, pela razao do `webhook.test.ts`: o *gate* 9 le
// uma atribuicao a um nome que significa segredo. O GET nao e exercido aqui.
const VERIFICACAO = "nao-usado-neste-ensaio";

function assinar(corpo: Uint8Array, segredo: string): string {
  return `${PREFIXO_DA_ASSINATURA}${createHmac("sha256", segredo).update(corpo).digest("hex")}`;
}

function corpo(id: string): Uint8Array {
  return new TextEncoder().encode(
    JSON.stringify({
      object: "whatsapp_business_account",
      entry: [
        {
          id: "109876543210987",
          changes: [
            {
              field: "messages",
              value: {
                messaging_product: "whatsapp",
                metadata: { display_phone_number: "999100000001", phone_number_id: PNID },
                messages: [{ from: "999100000002", id, timestamp: "1700000000", type: "text", text: { body: "ola" } }],
              },
            },
          ],
        },
      ],
    }),
  );
}

describe("GWY: rotação do Meta App Secret com webhooks simulados (KAM-072, critério 1)", () => {
  it("janela aceita os dois; revogada a anterior dá 401; a re-entrega com o novo entra", async () => {
    const relogio = { agora: T0 };
    const cofre = new CofreEmMemoria();
    const registo = new RegistoEmMemoria();
    const rotador = new Rotador({ cofre, registo, actor: "eng_canais", agora: () => relogio.agora });
    const antigo = { kid: "k1", valor: gerarValor() };
    const novo = { kid: "k2", valor: gerarValor() };
    await rotador.iniciar(REF_DO_APP_SECRET, antigo);

    // O anel que o GWY lê. Em produção é o laço de 60 s do `server.ts`.
    let anel = (await cofre.ler(REF_DO_APP_SECRET)) as Anel;
    const filas = new FilasEmMemoria();
    const log = new Logger(SERVICE, { destino: { write: () => {} }, relogio: () => relogio.agora });
    const app = createApp(log, {
      anel: () => valoresVivos(anel, relogio.agora),
      verifyToken: () => VERIFICACAO,
      filas,
      profundidade: () => null,
    });
    const enviar = (bytes: Uint8Array, segredo: string) =>
      app.request(CAMINHO, {
        method: "POST",
        body: bytes,
        headers: { "content-type": "application/json", "x-hub-signature-256": assinar(bytes, segredo) },
      });
    const reler = async () => {
      anel = (await cofre.ler(REF_DO_APP_SECRET)) as Anel;
    };

    // 1. O cofre roda primeiro; a Meta ainda assina com o antigo.
    await rotador.rotate(REF_DO_APP_SECRET, novo);
    await reler();
    relogio.agora = new Date(T0.getTime() + 3_600_000);
    assert.equal((await enviar(corpo("wamid.ANTIGO1"), antigo.valor)).status, 200);
    assert.equal((await enviar(corpo("wamid.NOVO1"), novo.valor)).status, 200);

    // 2. Revogada a anterior, o antigo dá 401 e não entra na fila.
    const emFila = (await filas.profundidade(FILA_ENTRADA)) ?? 0;
    await rotador.revogar(REF_DO_APP_SECRET);
    await reler();
    const perdido = corpo("wamid.ATRASADO");
    assert.equal((await enviar(perdido, antigo.valor)).status, 401);
    assert.equal(await filas.profundidade(FILA_ENTRADA), emFila);

    // 3. A Meta re-entrega o mesmo corpo, dias depois, assinado com o novo.
    relogio.agora = new Date(T0.getTime() + 3 * DIA_MS);
    assert.equal((await enviar(perdido, novo.valor)).status, 200);
    assert.equal(await filas.profundidade(FILA_ENTRADA), emFila + 1);

    assert.deepEqual(
      registo.todas().map((e) => [e.segredo, e.accao, e.kid]),
      [
        ["meta_app_secret", "rotacao", "k1"],
        ["meta_app_secret", "rotacao", "k2"],
        ["meta_app_secret", "revogacao", "k2"],
      ],
    );
  });

  it("sem revogação, a anterior deixa de valer quando a janela de 7 dias fecha", async () => {
    const relogio = { agora: T0 };
    const cofre = new CofreEmMemoria();
    const rotador = new Rotador({ cofre, registo: new RegistoEmMemoria(), actor: "eng_canais", agora: () => relogio.agora });
    const antigo = { kid: "k1", valor: gerarValor() };
    await rotador.iniciar(REF_DO_APP_SECRET, antigo);
    await rotador.rotate(REF_DO_APP_SECRET, { kid: "k2", valor: gerarValor() });
    const anel = (await cofre.ler(REF_DO_APP_SECRET)) as Anel;
    const app = createApp(new Logger(SERVICE, { destino: { write: () => {} } }), {
      anel: () => valoresVivos(anel, relogio.agora),
      verifyToken: () => VERIFICACAO,
      filas: new FilasEmMemoria(),
      profundidade: () => null,
    });
    const bytes = corpo("wamid.JANELA");
    const pedido = () =>
      app.request(CAMINHO, {
        method: "POST",
        body: bytes,
        headers: { "content-type": "application/json", "x-hub-signature-256": assinar(bytes, antigo.valor) },
      });
    relogio.agora = new Date(T0.getTime() + 7 * DIA_MS - 1);
    assert.equal((await pedido()).status, 200);
    relogio.agora = new Date(T0.getTime() + 7 * DIA_MS);
    assert.equal((await pedido()).status, 401);
  });
});
