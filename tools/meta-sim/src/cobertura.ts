/**
 * O relatório de cobertura: ≥ 1 *fixture* e ≥ 1 teste por tipo e por campo
 * (KAM-024, critério 2).
 *
 * O critério pede «um relatório de cobertura prova ≥ 1 *fixture* e ≥ 1 teste por
 * tipo e campo (100%)». São duas afirmações diferentes sobre cada item, e
 * medem-se de formas diferentes:
 *
 * - **a *fixture*** mede-se por construção: o simulador gera-a, e o relatório
 *   conta o que gerou. Uma *fixture* que não se consiga gerar é um erro, não um
 *   zero na tabela;
 * - **o teste** mede-se pelos **ficheiros de teste**, e não por contagem que o
 *   próprio relatório acumule. Um registo em memória conta o que correu nesta
 *   execução — e um `--test-name-pattern` que filtre metade dos testes dava um
 *   relatório a 50% ou, pior, um relatório a 100% construído por testes que
 *   nenhuma máquina voltou a correr.
 *
 * ## A marca, e porque é que é uma convenção e não magia
 *
 * Cada teste que cubra um item leva `[cobertura:<item>]` no nome. O relatório lê
 * os ficheiros de teste, extrai as marcas, e compara-as com a lista de itens.
 * A ligação é verificável nas duas direcções, que é o que a torna útil:
 *
 * - um item **sem** marca aparece como falta, e o relatório falha;
 * - uma marca com um item que **não existe** é erro — senão um `[cobertura:txt]`
 *   mal escrito dava, ao mesmo tempo, um teste que parece contar e um item
 *   descoberto, e o relatório ficava a 94% sem ninguém saber porquê.
 *
 * ## A lista de itens é a do critério, à letra
 *
 * Dezasseis tipos e onze campos. O `interactive` conta **duas** vezes porque o
 * critério o escreve com as duas variantes entre parênteses, e `statuses` conta
 * **quatro** pela mesma razão. Contá-los como um era cumprir em espírito e não à
 * letra: um simulador que só gerasse `button_reply` teria 100% numa tabela que
 * não olhava para o `list_reply`.
 */

import { CAMPOS, type Campo } from "./campos.ts";
import { ESTADOS } from "./estados.ts";
import { TIPOS, VARIANTES_INTERACTIVAS } from "./mensagens.ts";

/** O prefixo da marca que um teste põe no nome. */
export const MARCA = "cobertura:";

/** A expressão que encontra as marcas num ficheiro de teste. */
const PADRAO_DA_MARCA = /\[cobertura:([a-z0-9_:]+)\]/g;

/**
 * Os dezasseis itens da dimensão «tipo», pela ordem do critério.
 *
 * `interactive` entra pelas duas variantes e não pelo nome do tipo; `statuses`
 * entra pelos quatro estados. É a letra do critério.
 */
export const TIPOS_COBERTOS: readonly string[] = [
  ...TIPOS.filter((t) => t !== "interactive"),
  ...VARIANTES_INTERACTIVAS.map((v) => `interactive:${v}`),
  ...ESTADOS.map((e) => `statuses:${e}`),
  "history",
];

/** Os onze itens da dimensão «campo». */
export const CAMPOS_COBERTOS: readonly Campo[] = CAMPOS;

/** As duas dimensões. */
export const DIMENSOES = ["tipo", "campo"] as const;
export type Dimensao = (typeof DIMENSOES)[number];

/** Um item de cobertura: a sua dimensão e o seu nome. */
export interface Item {
  readonly dimensao: Dimensao;
  readonly nome: string;
  /** O nome como aparece numa marca: `tipo:text`, `campo:messages`. */
  readonly marca: string;
}

/** Todos os itens das duas dimensões. */
export const ITENS: readonly Item[] = [
  ...TIPOS_COBERTOS.map((nome) => ({ dimensao: "tipo" as const, nome, marca: `tipo:${nome}` })),
  ...CAMPOS_COBERTOS.map((nome) => ({ dimensao: "campo" as const, nome, marca: `campo:${nome}` })),
];

/** A linha do relatório para um item. */
export interface Linha {
  readonly item: Item;
  readonly fixtures: number;
  readonly testes: number;
}

/** O relatório inteiro. */
export interface Relatorio {
  readonly linhas: readonly Linha[];
  /** Itens com 0 *fixtures* ou 0 testes. O critério pede esta lista vazia. */
  readonly faltas: readonly Linha[];
  /** Marcas encontradas que não correspondem a item nenhum. */
  readonly marcasDesconhecidas: readonly string[];
  /** A percentagem de itens com ≥ 1 *fixture* **e** ≥ 1 teste. */
  readonly percentagem: number;
}

/** As marcas de um ficheiro de teste. */
export function marcasEm(fonte: string): readonly string[] {
  const achadas: string[] = [];
  const padrao = new RegExp(PADRAO_DA_MARCA.source, PADRAO_DA_MARCA.flags);
  for (;;) {
    const achado = padrao.exec(fonte);
    if (achado === null) break;
    const marca = achado[1];
    if (marca !== undefined) achadas.push(marca);
  }
  return achadas;
}

/**
 * Monta o relatório.
 *
 * `fixturesPorItem` vem de quem gerou as *fixtures* (o `cli.ts` gera-as todas e
 * conta); `fontesDeTeste` são os ficheiros de teste, pelo seu conteúdo. As duas
 * entradas são dados, e não ficheiros a ler: assim o relatório é testável sem
 * tocar no disco, e a leitura do disco é do `cli.ts`, onde pertence.
 */
export function relatorio(
  fixturesPorItem: Readonly<Record<string, number>>,
  fontesDeTeste: readonly string[],
): Relatorio {
  const porMarca = new Map<string, number>();
  const desconhecidas = new Set<string>();
  const conhecidas = new Set(ITENS.map((i) => i.marca));

  for (const fonte of fontesDeTeste) {
    for (const marca of marcasEm(fonte)) {
      if (!conhecidas.has(marca)) {
        desconhecidas.add(marca);
        continue;
      }
      porMarca.set(marca, (porMarca.get(marca) ?? 0) + 1);
    }
  }

  const linhas = ITENS.map((item) => ({
    item,
    fixtures: fixturesPorItem[item.marca] ?? 0,
    testes: porMarca.get(item.marca) ?? 0,
  }));
  const faltas = linhas.filter((l) => l.fixtures === 0 || l.testes === 0);
  return {
    linhas,
    faltas,
    marcasDesconhecidas: [...desconhecidas].sort(),
    percentagem: linhas.length === 0 ? 0 : ((linhas.length - faltas.length) / linhas.length) * 100,
  };
}

/**
 * O relatório em texto, para `docs/evidencia/KAM-024.md`.
 *
 * Tabela Markdown com os números, e **a lista das faltas por extenso**. Um
 * relatório que só diga «94%» não serve de evidência: quem o lê tem de saber
 * qual é o item que falta, para poder decidir se a caixa fica vazia.
 */
export function emMarkdown(r: Relatorio): string {
  const linhas: string[] = [];
  linhas.push("| Dimensão | Item | Fixtures | Testes |");
  linhas.push("|---|---|---:|---:|");
  for (const l of r.linhas) {
    linhas.push(`| ${l.item.dimensao} | \`${l.item.nome}\` | ${l.fixtures} | ${l.testes} |`);
  }
  linhas.push("");
  linhas.push(`**Cobertura: ${r.percentagem.toFixed(1)}%** (${r.linhas.length - r.faltas.length}/${r.linhas.length} itens com ≥ 1 fixture e ≥ 1 teste).`);
  if (r.faltas.length > 0) {
    linhas.push("");
    linhas.push("Faltas:");
    for (const f of r.faltas) {
      const razao = [f.fixtures === 0 ? "0 fixtures" : null, f.testes === 0 ? "0 testes" : null]
        .filter((x): x is string => x !== null)
        .join(" e ");
      linhas.push(`- \`${f.item.marca}\`: ${razao}`);
    }
  }
  if (r.marcasDesconhecidas.length > 0) {
    linhas.push("");
    linhas.push(
      `Marcas desconhecidas (erro): ${r.marcasDesconhecidas.map((m) => `\`${m}\``).join(", ")}`,
    );
  }
  return linhas.join("\n");
}
