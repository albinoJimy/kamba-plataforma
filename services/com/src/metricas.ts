/**
 * As métricas do COM, em formato Prometheus (KAM-178, critério 8).
 *
 * ```text
 * com_repo_filtro_em_falta_total{filtro}  counter  consultas recusadas pelo repo-base
 * com_repo_consultas_total{filtro}        counter  consultas que passaram a barreira
 * ```
 *
 * Os dois nomes são do dicionário §3.39 e **já existiam**: o KAM-042 declarou-os
 * no `repo-base/index.ts` e escreveu, no próprio ficheiro e no dicionário, que
 * «hoje vivem em memória e nenhum *endpoint* os lê», com a exposição «do ticket
 * que der ao COM uma superfície de métricas» — e **sem credor atribuído**. Este
 * módulo é esse credor. O `shortcut:` daquele ficheiro está riscado por ele.
 *
 * ## É um ficheiro de exposição e não um segundo sítio onde se conta
 *
 * Quem conta é o `repoBase`, nos `CONTADORES` que ele já tem. Este módulo
 * **lê-os**, e é a separação que impede a classe de defeito que o dicionário
 * nomeia noutro eixo: dois contadores para a mesma coisa, a divergir. Por isso
 * não há aqui nenhum `contar`.
 *
 * A forma é a do `packages/core-ts/src/ten/metricas.ts` — «quem serve as
 * métricas de um processo serve-as todas do mesmo modo» —, com as três
 * propriedades que importam:
 *
 *   1. **as séries aparecem sempre, mesmo a zero.** Um painel que mostre «sem
 *      dados» não distingue «ninguém foi recusado» de «o processo não arrancou»;
 *   2. **o `tenant_id` não entra em etiqueta nenhuma** (`OBS-I` de
 *      `docs/seguranca/ameacas_stride.md`): a única etiqueta é o `filtro`, cujo
 *      domínio é fechado em dois (`tenant`, `merchant`) pelos `FILTROS` do
 *      repo-base. Com um domínio fechado em dois não há tecto de séries a
 *      impor — é a diferença face ao `ten`, cujas chaves crescem com os
 *      tickets;
 *   3. **o corpo é texto e não JSON.** O `Content-Type` do formato de exposição
 *      é `text/plain; version=0.0.4`, e um `application/json` fazia o
 *      *scraper* recusar a resposta.
 */

import { CONTADORES, FILTROS, type Filtro } from "./repo-base/index.ts";
import {
  METRICA_CONSULTAS,
  METRICA_FILTRO_EM_FALTA,
} from "./repo-base/index.ts";

/** O `Content-Type` do formato de exposição. */
export const TIPO_DE_CONTEUDO = "text/plain; version=0.0.4; charset=utf-8";

/** O nome da etiqueta das duas métricas. É o filtro do repo-base. */
export const ETIQUETA = "filtro";

const AJUDA: readonly (readonly [string, string, string])[] = [
  [
    METRICA_FILTRO_EM_FALTA,
    "counter",
    "Consultas recusadas pelo repo-base por nao nomearem o filtro, por filtro.",
  ],
  [
    METRICA_CONSULTAS,
    "counter",
    "Consultas que passaram a barreira do repo-base, por filtro.",
  ],
];

/** Os dois mapas dos `CONTADORES`, pelo nome da métrica a que pertencem. */
function mapaDe(metrica: string): Map<Filtro, number> {
  return metrica === METRICA_FILTRO_EM_FALTA
    ? CONTADORES.filtroEmFalta
    : CONTADORES.consultas;
}

/**
 * As duas métricas no formato de exposição do Prometheus.
 *
 * Quatro séries sempre — duas métricas × dois filtros —, porque os `FILTROS`
 * são uma lista fechada e um painel precisa de ver o zero.
 */
export function exposicao(): string {
  const linhas: string[] = [];
  for (const [nome, tipo, ajuda] of AJUDA) {
    linhas.push(`# HELP ${nome} ${ajuda}`);
    linhas.push(`# TYPE ${nome} ${tipo}`);
    const mapa = mapaDe(nome);
    for (const filtro of FILTROS) {
      linhas.push(`${nome}{${ETIQUETA}="${filtro}"} ${mapa.get(filtro) ?? 0}`);
    }
  }
  return `${linhas.join("\n")}\n`;
}
