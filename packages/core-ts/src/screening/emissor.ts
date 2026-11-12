/**
 * O adaptador da porta `EmissorDeViolacoes` ao *outbox* (KAM-191).
 *
 * A forma é a dos outros produtores deste pacote (`modos/eventos.ts`,
 * `chr/eventos.ts`): mapeia a violação para o payload que o contrato publicado
 * exige, valida-o **antes** de qualquer escrita e chama `platform.evt_emitir`
 * pelo cliente que recebe.
 *
 * **O cliente é o da transacção do produto.** A re-análise abre uma transacção
 * por produto (`PorProduto`), com o contexto do tenant dele, e é nela que o
 * `screen` grava a decisão. Este emissor tem de ser construído sobre esse
 * **mesmo** cliente: é isso que faz a decisão e o evento confirmarem juntos, e
 * uma falha do `evt_emitir` — ou da validação, que corre antes — desfazer a
 * decisão. Um emissor sobre outra ligação confirmava o evento sem a decisão, ou
 * a decisão sem o evento, e a segunda é a violação perdida para sempre que os
 * achados F11 e F12 do KAM-088 fecharam.
 *
 * ## O contrato
 *
 * `contratos/eventos/screening.violation_detected/`, `v1` e `v2`. A `v2` existe
 * porque o *gate* 7 exige que a última versão de cada tipo cubra o domínio
 * inteiro de `finalidades`, e a `v1` porque o `lerEnvelope` fixa esse domínio
 * **por número de versão** (`FINALIDADES_POR_VERSAO`): uma `v1` com as dez
 * finalidades prometia o que o leitor recusa. Emite-se a **`v1`**, como os
 * eventos de catálogo do COM: a finalidade é `transacao`, que a `v1` tem, e uma
 * `v1` lê-se em qualquer subscrição sem conversor.
 *
 * O agregado é o **produto** — `product`, com o `sku` como `id`, o mesmo par do
 * `catalog.product_changed`. A violação fica na linhagem do produto, e o
 * consumidor sabe se o produto mudou antes ou depois dela pelo `seq`.
 *
 * ## Privacidade
 *
 * O payload não leva texto do produto: leva o `sku` (referência), as regras
 * (identificadores da política), a versão da política e o `sha256` do conteúdo
 * decidido — o mesmo resumo da `screening_decision.conteudo_sha256`, em
 * **base32** e não em hexadecimal (ver `sha256EmBase32`). O `tenant_id` vai no envelope, que é o que o `evt_emitir` põe e
 * o que a RLS do *outbox* confere; não se repete no payload, que é o caminho por
 * onde um tenant de outro poderia entrar.
 *
 * **Não suspende ninguém.** Emitir é tudo o que este adaptador faz; a sanção é
 * do KAM-097, que consome o evento.
 */

import type { PayloadScreeningViolationDetected } from "@kamba/contracts";

import { validarPayload } from "../eventos/contratos.ts";
import { comTenant } from "../tenant_guard/index.ts";
import type { DependenciasDoScreen } from "./motor.ts";
import type { EmissorDeViolacoes, PorProduto, Violacao } from "./reanalise.ts";
import { CatalogoSql, type ClienteSql, EscritorSql } from "./sql.ts";

export const TIPO_VIOLACAO = "screening.violation_detected";
export const VERSAO_VIOLACAO = 1;
/** O `const` do `agregado.tipo` nos dois contratos. */
export const AGREGADO_VIOLACAO = "product";
/** P0: nenhum campo liga o evento a uma pessoa. É o `enum` dos contratos. */
export const CLASSE_PII_VIOLACAO = "P0";
export const FINALIDADES_VIOLACAO = ["transacao"] as const;

export const SQL_EMITIR_VIOLACAO = `
  SELECT platform.evt_emitir(
    $1, $2::smallint, $3::uuid, $4, $5, $6::jsonb, $7, $8::text[]
  ) AS event_id
`;

/**
 * A transacção por produto de produção: o `comTenant` sobre a ligação da
 * aplicação (`kamba_app`), com o contexto do tenant do produto.
 *
 * O `EscritorSql` e o `EmissorSql` da re-análise constroem-se sobre **este
 * mesmo** `cliente`: o `comTenant` abre a transacção nele, e é isso que põe a
 * decisão e o evento na mesma — e que faz um erro de qualquer dos dois desfazer
 * os dois. O leitor do catálogo (`CatalogoSql`) vai noutra ligação, a do
 * `kamba_batch`, porque atravessa tenants.
 */
export function porProdutoSql(cliente: ClienteSql): PorProduto {
  return <T>(tenantId: string, trabalho: () => Promise<T>) =>
    comTenant(cliente, tenantId, () => trabalho());
}

/** O alfabeto do base32 do RFC 4648, em minúsculas. Sem `0`, `1`, `8` e `9`. */
const ALFABETO_BASE32 = "abcdefghijklmnopqrstuvwxyz234567";

/**
 * O resumo em base32 (RFC 4648, minúsculas, sem `=`): 52 caracteres para 32
 * octetos.
 *
 * **Não é hexadecimal, e a razão é uma avaria medida** (achado F1 da revisão
 * adversarial). O `evt_emitir` recusa todo o payload que case
 * `\+?244 ?9[0-9]{8}` — a guarda de telefone da revisão `0004` —, e 64
 * hexadecimais casam-na em cerca de um conteúdo em cinquenta mil (estimado:
 * 53 posições × (1/16)⁴ × (10/16)⁸): o produto «vinho tinto 65521» da categoria
 * `moda` dá um resumo em que `244` aparece seguido de um `9` e de mais oito
 * algarismos. A recusa desfazia a decisão, a execução seguinte voltava ao mesmo
 * produto pela mesma ordem, e a re-análise ficava parada nele para sempre — e
 * um tenant conseguia fabricar esse conteúdo de propósito. O alfabeto do base32
 * não tem `9` nem `+`, pelo que **nenhum** resumo casa as duas expressões da
 * guarda, por construção e não por probabilidade.
 */
export function sha256EmBase32(octetos: Uint8Array): string {
  let saida = "";
  let acumulado = 0;
  let bits = 0;
  for (const octeto of octetos) {
    acumulado = (acumulado << 8) | octeto;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      saida += ALFABETO_BASE32[(acumulado >>> bits) & 31];
    }
    acumulado &= (1 << bits) - 1;
  }
  if (bits > 0) saida += ALFABETO_BASE32[(acumulado << (5 - bits)) & 31];
  return saida;
}

/** O payload do contrato, a partir de uma violação. Sem texto do produto. */
export function payloadDaViolacao(violacao: Violacao): PayloadScreeningViolationDetected {
  return {
    sku: violacao.sku,
    regras: [...violacao.regras],
    versao_politica: violacao.versaoPolitica,
    sha256: sha256EmBase32(violacao.conteudoSha256),
  };
}

/**
 * Escreve a violação no *outbox* pelo cliente da transacção do produto.
 *
 * @throws {PayloadInvalidoError} se o payload não bater com o contrato, antes
 *   de qualquer escrita — e, na re-análise, isso desfaz a decisão.
 */
export class EmissorSql implements EmissorDeViolacoes {
  readonly #cliente: ClienteSql;

  constructor(cliente: ClienteSql) {
    this.#cliente = cliente;
  }

  async emitir(violacao: Violacao): Promise<void> {
    const payload = payloadDaViolacao(violacao);
    validarPayload(TIPO_VIOLACAO, VERSAO_VIOLACAO, payload);
    const { rows } = await this.#cliente.query<{ event_id: unknown }>(SQL_EMITIR_VIOLACAO, [
      TIPO_VIOLACAO,
      VERSAO_VIOLACAO,
      violacao.tenantId,
      AGREGADO_VIOLACAO,
      violacao.sku,
      JSON.stringify(payload),
      CLASSE_PII_VIOLACAO,
      [...FINALIDADES_VIOLACAO],
    ]);
    if (typeof rows[0]?.event_id !== "string") {
      throw new Error(
        "platform.evt_emitir nao devolveu um event_id: a violacao pode nao ter " +
          "sido escrita no outbox, e a decisao nao confirma sem ela",
      );
    }
  }
}

/** As ligações e o que a re-análise de produção precisa além delas. */
export interface LigacoesDaReanalise {
  /** A ligação de `kamba_app`: decisões, eventos e a transacção por produto. */
  readonly app: ClienteSql;
  /** A ligação de `kamba_batch`: o catálogo por re-analisar, que atravessa tenants. */
  readonly batch: ClienteSql;
  readonly politica: DependenciasDoScreen["politica"];
  readonly classificador: DependenciasDoScreen["classificador"];
}

/**
 * As dependências de produção do `reanalisar`, montadas num sítio só
 * (achado F3 da revisão adversarial).
 *
 * A garantia «a decisão e o evento na mesma transacção» depende de o
 * `EscritorSql`, o `EmissorSql` e o `porProdutoSql` assentarem na **mesma**
 * ligação. Deixá-la a quem monta o *job* era deixá-la a uma linha que ninguém
 * ensaia: um emissor sobre outra ligação confirmava o evento à parte. Aqui só
 * há um sítio onde a ligação da aplicação entra, e os três usam-na.
 */
export function dependenciasDaReanalise(ligacoes: LigacoesDaReanalise) {
  return {
    politica: ligacoes.politica,
    classificador: ligacoes.classificador,
    escritor: new EscritorSql(ligacoes.app),
    emissor: new EmissorSql(ligacoes.app),
    porProduto: porProdutoSql(ligacoes.app),
    catalogo: new CatalogoSql(ligacoes.batch),
  };
}
