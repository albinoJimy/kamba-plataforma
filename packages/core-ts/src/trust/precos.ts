/**
 * A varredura do preço anómalo (KAM-209): o `avaliarPreco` do KAM-097 sobre
 * cada oferta publicada, contra as referências da plataforma.
 *
 * ## A fonte das referências: `plataforma/1`
 *
 * Decisões do fundador de 2026-11-21 e de 2026-11-22. As referências de uma
 * oferta são os preços das ofertas **publicadas**, de preço **fixo**, da
 * **mesma moeda e categoria**, de **outros** tenants — e as vinte têm de vir de
 * pelo menos **três lojas distintas** (`LOJAS_MINIMAS_DAS_REFERENCIAS`,
 * *proposta*): uma loja sozinha, com vinte ofertas a 1 Kz, não fixa a mediana
 * de ninguém. Abaixo de três lojas a oferta **não se avalia**, e a varredura
 * conta-a (`poucasLojas`). Avaliam-se as publicadas de preço fixo **e** as
 * `a_partir_de` (o mínimo, contra a mesma mediana); o `sob_consulta` não tem
 * preço. Quem as lê é o `kamba_batch`, o papel auditado que atravessa tenants
 * (`SQL_OFERTAS_COM_PRECO`), e cada corrida deixa a sua linha `batch.run` no
 * `audit_log` (`CicloDoTrust`). O nome da fonte e a versão da política vão no
 * detalhe do sinal (`fonte`, `versao_politica`): mudar o que conta como
 * referência é mudar o `/1`.
 *
 * ## Um sinal por loja e por janela de 30 dias
 *
 * Decisão do fundador de 2026-11-22. A chave do sinal é a do `refDaJanela`
 * («este tenant, `preco_anomalo`, esta janela de 30 dias»), e o detalhe leva
 * quantos SKUs a volta achou anómalos (`contagem`). O peso 5 do KAM-097 conta,
 * assim, no máximo uma vez por janela: **o sinal nunca sanciona sozinho** (o
 * aviso automático pede 30). Uma loja com doze SKUs fora do intervalo, ou um
 * dono que muda o preço doze vezes, é um sinal e não doze. A primeira volta da
 * janela fixa a contagem: a `ts_signal` é *append-only*, e as voltas seguintes
 * da mesma janela não a reescrevem.
 *
 * ## O que o sinal diz, e o que não diz
 *
 * Quantos SKUs **deste** tenant ficaram fora do intervalo. Nunca a mediana,
 * nem um preço, nem qual tenant é referência: a correlação entre tenants sai
 * como contagem, como a da foto repetida (KAM-200).
 *
 * ## Os limiares e o peso são os do KAM-097, *proposta*
 *
 * `referenciasMinimas` (20), `precoMinimoDaMediana` (1%) e
 * `precoMaximoDaMediana` (100×), da `POLITICA_DE_RISCO`; o peso do
 * `preco_anomalo` é 5 e a severidade `baixa`. Nada disto mudou neste ticket.
 *
 * ## As ofertas que não se avaliam, e porquê
 *
 * As que já estavam publicadas antes da revisão `0088` ficam sem categoria e
 * não se avaliam (decisão do fundador de 2026-11-21: a guarda vale só na
 * publicação), e as que têm vinte referências de menos de três lojas também
 * não. A varredura conta as duas (`semCategoria`, `poucasLojas`): saem no
 * `ts_ofertas_nao_avaliadas{motivo}` do `/metrics` do processo de lote, no
 * resultado da volta, e no `payload_hash` da linha de auditoria da corrida.
 */

import { refDaJanela, type OpcoesDoTrust } from "./efeito.ts";
import { avaliaPreco, eCategoriaDeProduto } from "./categorias.ts";
import { POLITICA_DE_RISCO, avaliarPreco } from "./regras.ts";
import { ServicoDeTrust } from "./servico.ts";
import {
  RepositorioDeTrustSql,
  SQL_OFERTAS_COM_PRECO,
  SQL_OFERTAS_SEM_CATEGORIA,
  SQL_PRECOS_JA_SINALIZADOS,
  type ClienteSql,
} from "./sql.ts";

/** O nome e a versão da fonte das referências. Ver a nota do módulo. */
export const FONTE_DAS_REFERENCIAS = "plataforma/1";

/** As lojas distintas de onde as referências têm de vir (*proposta*, decisão de 2026-11-22). */
export const LOJAS_MINIMAS_DAS_REFERENCIAS = 3;

/** A janela de um sinal de preço: um por loja em cada uma (decisão de 2026-11-22). */
export const DIAS_DA_JANELA_DO_PRECO = 30;

export interface ResultadoDosPrecos {
  /** Os `preco_anomalo` novos: no máximo um por loja e por janela. */
  readonly sinais: number;
  /** As ofertas publicadas sem categoria, que não se avaliaram. */
  readonly semCategoria: number;
  /** As ofertas com vinte referências de menos de três lojas, que não se avaliaram. */
  readonly poucasLojas: number;
}

interface Oferta {
  readonly tenantId: string;
  readonly sku: string;
  readonly categoria: string;
  readonly currency: string;
  readonly precoMinor: number;
  /** Só as de preço fixo são referência; as `a_partir_de` avaliam-se e não contam. */
  readonly referencia: boolean;
}

/** A chave do sinal de preço de um tenant na janela de `agora`. */
export function refDoPreco(tenantId: string, agora: Date): string {
  return refDaJanela(tenantId, "preco_anomalo", agora, DIAS_DA_JANELA_DO_PRECO);
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
    referencia: l["preco_tipo"] === "fixo",
  };
}

function inteiro(v: unknown): number {
  const n = typeof v === "number" ? v : Number.parseInt(String(v ?? "0"), 10);
  return Number.isSafeInteger(n) ? n : 0;
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
  for (const l of (await bd.query(SQL_OFERTAS_COM_PRECO)).rows) {
    const oferta = lerOferta(l);
    if (oferta === null) continue;
    const chave = `${oferta.categoria}\0${oferta.currency}`;
    const grupo = grupos.get(chave);
    if (grupo === undefined) grupos.set(chave, [oferta]);
    else grupo.push(oferta);
  }

  /** Quantos SKUs anómalos, por tenant, em todas as categorias. */
  const anomalos = new Map<string, number>();
  let poucasLojas = 0;
  for (const grupo of grupos.values()) {
    const porTenant = new Map<string, Oferta[]>();
    for (const oferta of grupo) {
      const proprias = porTenant.get(oferta.tenantId);
      if (proprias === undefined) porTenant.set(oferta.tenantId, [oferta]);
      else proprias.push(oferta);
    }
    for (const [tenantId, proprias] of porTenant) {
      // As referências de um tenant são as ofertas de preço fixo do grupo que
      // não são dele. Ordenadas uma vez aqui: a `mediana` do `avaliarPreco`
      // copia e ordena a cada chamada, e sobre uma lista já ordenada isso é
      // linear em vez de n·log n por oferta (achado 5 da revisão adversarial).
      const outras = grupo.filter((r) => r.referencia && r.tenantId !== tenantId);
      const lojas = new Set(outras.map((r) => r.tenantId)).size;
      if (outras.length >= p.referenciasMinimas && lojas < LOJAS_MINIMAS_DAS_REFERENCIAS) {
        poucasLojas += proprias.length;
        continue;
      }
      const referencias = outras.map((r) => r.precoMinor).sort((a, b) => a - b);
      for (const oferta of proprias) {
        if (avaliarPreco(oferta.precoMinor, referencias, p) === "anomalo") {
          anomalos.set(tenantId, (anomalos.get(tenantId) ?? 0) + 1);
        }
      }
    }
  }

  // Um sinal por loja e por janela. As chaves desta janela que já existem
  // lêem-se antes, para que uma loja já sinalizada não volte à escada em cada
  // volta da hora.
  const chaves = [...anomalos.keys()].map((t) => refDoPreco(t, agora));
  const jaSinalizados = new Set(
    chaves.length === 0
      ? []
      : (await bd.query(SQL_PRECOS_JA_SINALIZADOS, [chaves])).rows.map((l) => String(l["ref_evento"])),
  );
  let sinais = 0;
  for (const [tenantId, contagem] of anomalos) {
    const ref = refDoPreco(tenantId, agora);
    if (jaSinalizados.has(ref)) continue;
    const r = await servico.sinalizar({
      tenantId,
      tipo: "preco_anomalo",
      refEvento: ref,
      detalhe: { contagem, fonte: FONTE_DAS_REFERENCIAS, versao_politica: p.versao },
      ocorridoEm: agora,
    });
    if (!r.repetido) sinais++;
  }

  const semCategoria = inteiro((await bd.query(SQL_OFERTAS_SEM_CATEGORIA)).rows[0]?.["n"]);
  return { sinais, semCategoria, poucasLojas };
}
