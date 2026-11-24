/**
 * A rota interna do guia servida sozinha, para o ensaio de rede do gate 8
 * (`db/tests_lote/test_rota_interna_rede.py`, KAM-239).
 *
 * Abre a porta pela **mesma** `servirRotaInterna` do `../../src/lote.ts`, com o
 * anfitrião e a porta do ambiente, como o processo de lote: o que o ensaio mede é o
 * `listen` do lote, e não uma réplica dele. As portas são duplos que recusam: o
 * ensaio só pede sem a credencial, e um pedido que chegasse a uma delas era um
 * defeito que ele tem de ver (500 em vez de 401).
 *
 *     LOTE_INTERNO_HOST=onboarding-lote-interno LOTE_INTERNO_PORT=3015 \
 *       node tests/apoio/servir_rota_interna.ts
 *
 * Escreve `pronto` com a porta aberta; quem o lança espera por essa linha.
 */

import { criarAppInterna, servirRotaInterna } from "../../src/lote/interno.ts";

const recusa = async (): Promise<never> => {
  throw new Error("o ensaio de rede nao chega as portas");
};

const app = criarAppInterna({
  lista: {
    reserve: recusa,
    release: recusa,
    posicao: recusa,
    validarConvite: recusa,
    recusar: recusa,
    desistir: recusa,
  },
  gates: { marcar: recusa },
  revisao: { abrir: recusa },
  // Obviamente falsa e de baixa entropia, pela razão do `INTERNO_DE_ENSAIO` do X-01.
  credencial: "ensaio-de-rede-da-rota-interna",
});

await servirRotaInterna(app, {
  anfitriao: (process.env["LOTE_INTERNO_HOST"] ?? "").trim() || "127.0.0.1",
  porta: Number(process.env["LOTE_INTERNO_PORT"] ?? "3015"),
});
console.log("pronto");
