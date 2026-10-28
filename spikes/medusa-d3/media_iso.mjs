/**
 * ISO-47..50 — isolamento de media e de URLs assinadas.
 *
 * Corre contra `packages/core-ts/dist/storage`, que e a **porta de producao** do
 * KAM-011 (ADR-014), com `criarStorageFake()`. Isso e o ponto: um teste de
 * isolamento de media escrito dentro deste spike mediria o proprio teste. A
 * mesma bateria do contrato do KAM-011 corre contra um S3 real, e e esta porta
 * que o Catalogo AI (KAM-049) vai usar para as fotos dos produtos.
 *
 * `dist/storage` nao tem dependencias de runtime fora de `node:crypto`, pelo que
 * isto corre na imagem oficial do Node **sem rede e sem `npm install`**.
 *
 * Escreve um JSON em `/saida/media-iso.json`: uma entrada por caso, com
 * `estado` em `passa` / `falha` / `nao_verificado`.
 */

import { writeFileSync } from "node:fs";

const SAIDA = process.env.KAMBA_SPIKE_SAIDA ?? "/saida/media-iso.json";
const TENANT_A = process.env.KAMBA_SPIKE_TENANT_A;
const TENANT_B = process.env.KAMBA_SPIKE_TENANT_B;

const casos = [];

function registar(id, cenario, esperado, estado, observado, evidencia = "") {
  casos.push({ id, superficie: "Media e URLs", cenario, esperado, estado, observado, evidencia });
}

/** Espera uma recusa. Devolver dados e falha; um erro inesperado nao e passe. */
async function recusa(id, cenario, esperado, accao, nomesEsperados) {
  try {
    const devolvido = await accao();
    registar(id, cenario, esperado, "falha", "devolveu dados",
      `devolvido: ${JSON.stringify(devolvido)?.slice(0, 300)}`);
  } catch (erro) {
    const nome = erro?.constructor?.name ?? "Error";
    if (nomesEsperados.includes(nome)) {
      registar(id, cenario, esperado, "passa", "recusado", `${nome}: ${erro.message}`);
    } else {
      registar(id, cenario, esperado, "nao_verificado",
        "erro inesperado no proprio teste", `${nome}: ${erro.message}`);
    }
  }
}

async function principal() {
  if (!TENANT_A || !TENANT_B) {
    registar("ISO-47", "—", "—", "nao_verificado", "nao medido",
      "KAMBA_SPIKE_TENANT_A/B nao chegaram ao contentor");
    writeFileSync(SAIDA, JSON.stringify(casos, null, 2));
    return;
  }

  const { criarStorageFake, novaChave } = await import(
    "/repo/packages/core-ts/dist/storage/index.js"
  );

  const { storage, buscar } = criarStorageFake();
  const ctxA = { tenantId: TENANT_A };
  const ctxB = { tenantId: TENANT_B };

  // B guarda uma foto de produto. Bytes sinteticos; nenhum dado real.
  const chaveB = novaChave(ctxB, "imagem");
  const refB = await storage.put(ctxB, chaveB, new Uint8Array([1, 2, 3, 4]), {
    contentType: "image/jpeg",
    classe: "imagem",
    retainUntil: new Date(Date.now() + 86_400_000),
  });

  // ISO-47: A a ler o objecto de B por referencia.
  await recusa(
    "ISO-47", "ctx de A a ler o objecto de B por referencia",
    "recusada", () => storage.get(ctxA, refB),
    ["ObjectoInexistenteError", "ChaveForaDoTenantError"],
  );

  // ISO-48: a URL assinada para B, resolvida depois de adulterada para o
  // prefixo de A. A URL e um portador: o que se mede e que a assinatura cobre a
  // chave, e que trocar o tenant na chave invalida a assinatura.
  const urlB = await storage.signUrl(ctxB, refB, { ttlSeconds: 60 });
  const urlAdulterada = urlB.replace(`t/${TENANT_B}/`, `t/${TENANT_A}/`);
  if (urlAdulterada === urlB) {
    registar("ISO-48", "URL assinada do objecto de B adulterada para o prefixo de A",
      "recusada (403)", "nao_verificado", "nao medido",
      "a URL assinada nao traz a chave em claro, pelo que nao ha nada para "
      + "adulterar desta forma; o caso precisa de outra sonda");
  } else {
    const resposta = await buscar(urlAdulterada);
    registar("ISO-48", "URL assinada do objecto de B adulterada para o prefixo de A",
      "recusada (403)", resposta.estado === 403 ? "passa" : "falha",
      `estado ${resposta.estado}`,
      resposta.estado === 403
        ? "a assinatura cobre a chave"
        : `a URL adulterada devolveu ${resposta.estado} e ${resposta.corpo.length} byte(s)`);
  }

  // Segunda sonda do ISO-48: A a pedir uma URL assinada para a referencia de B.
  await recusa(
    "ISO-48b", "ctx de A a assinar uma URL para a referencia de B",
    "recusada", () => storage.signUrl(ctxA, refB, { ttlSeconds: 60 }),
    ["ObjectoInexistenteError", "ChaveForaDoTenantError"],
  );

  // ISO-49: A a listar o prefixo de B.
  await recusa(
    "ISO-49", "ctx de A a listar o prefixo do tenant B",
    "ChaveForaDoTenantError", () => storage.list(ctxA, `t/${TENANT_B}/`),
    ["ChaveForaDoTenantError"],
  );

  // ISO-50: A a escrever numa chave cunhada para B.
  await recusa(
    "ISO-50", "ctx de A a escrever numa chave cunhada para B",
    "ChaveForaDoTenantError",
    () => storage.put(ctxA, chaveB, new Uint8Array([9]), {
      contentType: "image/jpeg",
      classe: "imagem",
      retainUntil: new Date(Date.now() + 86_400_000),
    }),
    ["ChaveForaDoTenantError"],
  );

  writeFileSync(SAIDA, JSON.stringify(casos, null, 2));
}

principal().catch((erro) => {
  registar("ISO-47", "arranque do guiao", "—", "nao_verificado",
    "o guiao nao chegou a medir", `${erro?.constructor?.name}: ${erro?.message}`);
  writeFileSync(SAIDA, JSON.stringify(casos, null, 2));
  process.exitCode = 1;
});
