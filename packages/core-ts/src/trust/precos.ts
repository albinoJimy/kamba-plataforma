/**
 * A varredura do preço anómalo (KAM-209): o `avaliarPreco` do KAM-097 sobre
 * cada oferta publicada, contra as referências da plataforma.
 *
 * ## A fonte das referências: `plataforma/1`
 *
 * Decisão do fundador de 2026-11-21. As referências de uma oferta são os
 * preços das ofertas **publicadas**, de preço **fixo**, da **mesma moeda e
 * categoria**, de **outros** tenants — nunca do próprio, para que uma loja com
 * vinte produtos não faça a sua própria mediana. Quem as lê é o `kamba_batch`,
 * o papel auditado que atravessa tenants (`SQL_OFERTAS_DE_PRECO_FIXO`), e cada
 * corrida deixa a sua linha `batch.run` no `audit_log` (`CicloDoTrust`). O nome
 * da fonte e a versão da política vão no detalhe do sinal (`fonte`,
 * `versao_politica`): mudar o que conta como referência é mudar o `/1`.
 *
 * ## O que o sinal diz, e o que não diz
 *
 * O `sku` da oferta **deste** tenant e quantas referências a avaliaram
 * (`contagem`). Nunca a mediana, nem um preço, nem qual tenant: a correlação
 * entre tenants sai como contagem, como a da foto repetida (KAM-200).
 *
 * ## Os limiares e o peso são os do KAM-097, *proposta*
 *
 * `referenciasMinimas` (20), `precoMinimoDaMediana` (1%) e
 * `precoMaximoDaMediana` (100×), da `POLITICA_DE_RISCO`; o peso do
 * `preco_anomalo` é 5 e a severidade `baixa`. Nada disto mudou neste ticket.
 *
 * ## Uma vez por preço
 *
 * A chave do sinal (`ref_evento`) é derivada do tenant, do `sku`, da categoria,
 * da moeda e do preço (`refDoPreco`): a mesma oferta ao mesmo preço sinaliza
 * uma vez, e o mesmo produto com outro preço é outra avaliação. As chaves já
 * gravadas lêem-se antes (`SQL_PRECOS_JA_SINALIZADOS`), para que uma oferta
 * anómala que nada mudou não volte à escada em cada volta.
 *
 * ## As ofertas sem categoria
 *
 * As que já estavam publicadas antes da revisão `0088` ficam nulas e **não se
 * avaliam** (decisão do fundador de 2026-11-21: a guarda vale só na
 * publicação). A varredura conta-as (`semCategoria`), e a contagem vai na linha
 * de auditoria da corrida e no resultado da volta.
 */

import { createHash } from "node:crypto";

import type { OpcoesDoTrust } from "./efeito.ts";
import { avaliaPreco, eCategoriaDeProduto } from "./categorias.ts";
import { POLITICA_DE_RISCO, avaliarPreco } from "./regras.ts";
import { ServicoDeTrust } from "./servico.ts";
import {
  RepositorioDeTrustSql,
  SQL_OFERTAS_DE_PRECO_FIXO,
  SQL_OFERTAS_SEM_CATEGORIA,
  SQL_PRECOS_JA_SINALIZADOS,
  type ClienteSql,
} from "./sql.ts";

/** O nome e a versão da fonte das referências. Ver a nota do módulo. */
export const FONTE_DAS_REFERENCIAS = "plataforma/1";

export interface ResultadoDosPrecos {
  /** Os `preco_anomalo` novos. */
  readonly sinais: number;
  /** As ofertas publicadas sem categoria, que não se avaliaram. */
  readonly semCategoria: number;
}

interface Oferta {
  readonly tenantId: string;
  readonly sku: string;
  readonly categoria: string;
  readonly currency: string;
  readonly precoMinor: number;
}

/**
 * A chave do sinal de um preço: um `uuid` dos primeiros 16 octetos do SHA-256
 * de «tenant, sku, categoria, moeda, preço», com os bits de versão (8) e de
 * variante do RFC 9562, como o `refDaJanela`.
 */
export function refDoPreco(o: Omit<Oferta, "precoMinor"> & { readonly precoMinor: number | bigint }): string {
  const h = createHash("sha256")
    .update(`kamba/trust/preco_anomalo/v1\0${o.tenantId}\0${o.sku}\0${o.categoria}\0${o.currency}\0${o.precoMinor}`, "utf8")
    .digest();
  h[6] = ((h[6] ?? 0) & 0x0f) | 0x80;
  h[8] = ((h[8] ?? 0) & 0x3f) | 0x80;
  const x = h.subarray(0, 16).toString("hex");
  return `${x.slice(0, 8)}-${x.slice(8, 12)}-${x.slice(12, 16)}-${x.slice(16, 20)}-${x.slice(20, 32)}`;
}

/**
 * Uma linha da consulta, ou `null` se não se avalia: categoria fora da lista
 * ou que não se avalia (a `outra`), ou um preço que não cabe num inteiro
 * seguro — 9×10¹⁵ cêntimos não é um preço, e não entra nem como referência.
 */
function lerOferta(l: Readonly<Record<string, unknown>>): Oferta | null {
  const categoria = l["categoria"];
  if (!eCategoriaDeProduto(categoria) || !avaliaPreco(categoria)) return null;
  const preco = Number(String(l["preco_minor"]));
  if (!Number.isSafeInteger(preco)) return null;
  return {
    tenantId: String(l["tenant_id"]),
    sku: String(l["sku"]),
    categoria,
    currency: String(l["currency"]),
    precoMinor: preco,
  };
}

/** Uma volta da varredura. Corre como `kamba_batch`, na transacção de quem chama. */
export async function varrerPrecos(bd: ClienteSql, o: OpcoesDoTrust = {}): Promise<ResultadoDosPrecos> {
  const p = o.politica ?? POLITICA_DE_RISCO;
  const agora = (o.relogio ?? (() => new Date()))();
  const servico = new ServicoDeTrust({
    repositorio: new RepositorioDeTrustSql(bd, "lote"),
    politica: p,
    relogio: () => agora,
    ...(o.contadores === undefined ? {} : { contadores: o.contadores }),
  });

  const grupos = new Map<string, Oferta[]>();
  for (const l of (await bd.query(SQL_OFERTAS_DE_PRECO_FIXO)).rows) {
    const oferta = lerOferta(l);
    if (oferta === null) continue;
    const chave = `${oferta.categoria}\0${oferta.currency}`;
    const grupo = grupos.get(chave);
    if (grupo === undefined) grupos.set(chave, [oferta]);
    else grupo.push(oferta);
  }
  const jaSinalizados = new Set(
    (await bd.query(SQL_PRECOS_JA_SINALIZADOS)).rows.map((l) => String(l["ref_evento"])),
  );

  let sinais = 0;
  for (const grupo of grupos.values()) {
    const porTenant = new Map<string, Oferta[]>();
    for (const oferta of grupo) {
      const proprias = porTenant.get(oferta.tenantId);
      if (proprias === undefined) porTenant.set(oferta.tenantId, [oferta]);
      else proprias.push(oferta);
    }
    for (const [tenantId, proprias] of porTenant) {
      // As referências de um tenant são as ofertas do grupo que não são dele.
      const referencias = grupo.filter((r) => r.tenantId !== tenantId).map((r) => r.precoMinor);
      for (const oferta of proprias) {
        if (avaliarPreco(oferta.precoMinor, referencias, p) !== "anomalo") continue;
        const ref = refDoPreco(oferta);
        if (jaSinalizados.has(ref)) continue;
        const r = await servico.sinalizar({
          tenantId,
          tipo: "preco_anomalo",
          refEvento: ref,
          detalhe: {
            sku: oferta.sku,
            contagem: referencias.length,
            fonte: FONTE_DAS_REFERENCIAS,
            versao_politica: p.versao,
          },
          ocorridoEm: agora,
        });
        if (!r.repetido) sinais++;
      }
    }
  }

  const n = (await bd.query(SQL_OFERTAS_SEM_CATEGORIA)).rows[0]?.["n"];
  const semCategoria = typeof n === "number" ? n : Number.parseInt(String(n ?? "0"), 10);
  return { sinais, semCategoria: Number.isSafeInteger(semCategoria) ? semCategoria : 0 };
}
