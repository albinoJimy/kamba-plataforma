/**
 * O inventário de números de **forma** real, e porque é que o critério 7 não se
 * cumpre sem ele (KAM-024).
 *
 * O critério pede «o repositório fica com 0 telefones reais (scan)». Corri o
 * *scan* sobre o repositório antes de escrever isto: **89 ocorrências em 24
 * ficheiros**. Nenhuma é um descuido. Todas são *fixtures* de redacção de PII —
 * `tools/log_policy`, `tools/contract_diff`, `packages/core-ts/src/eventos/pii`,
 * os dois *loggers*, as suites de `evt_emitir` — e existem para que o detector
 * **dispare**.
 *
 * Isso obriga a ler o critério com cuidado, porque as duas leituras dão
 * respostas opostas:
 *
 * - «0 cadeias com a forma de um número angolano» é **insatisfazível**, e
 *   satisfazê-la destruía o que vale mais: um redactor testado só com números
 *   do `999` nunca prova que apanha um `+244 9…`, que é precisamente o que
 *   existe para apanhar. A caixa ficava marcada e a protecção ficava pior;
 * - «0 números que pertençam a uma pessoa real» é o que o DoD quer dizer
 *   («0 telefones reais **ou dados pessoais**; capturas saneadas»), e é
 *   verificável — mas não por expressão regular, porque nenhuma expressão
 *   distingue um número atribuído de um sequencial.
 *
 * ## O que torna a segunda leitura verificável: um raquete, não uma isenção
 *
 * A tentação é isentar `tests/`. É exactamente o que a skill desta casa nomeia
 * como cumprir em espírito e não à letra — «um canário numa *fixture* falha o PR»
 * não está cumprido se a pasta do canário for uma área permitida. Uma pasta
 * isenta cresce em silêncio, e no dia em que alguém colar uma captura real num
 * teste o *scan* fica verde.
 *
 * O inventário é o contrário disso, e a diferença está em três propriedades:
 *
 * 1. **Conta.** Cada entrada diz quantas ocorrências aquele ficheiro tem. Uma a
 *    mais falha, **mesmo num ficheiro já inventariado** — que é o caso que a
 *    pasta isenta deixava passar.
 * 2. **Explica.** Cada entrada diz porquê, e a razão tem de nomear o que o
 *    número está a testar. Uma entrada sem razão é um defeito do inventário.
 * 3. **Não fica para trás.** Uma entrada que já não corresponde — o ficheiro
 *    perdeu o número, ou desapareceu — também falha. Um inventário com entradas
 *    mortas é um inventário que ninguém releu.
 *
 * Um ficheiro fora do inventário com uma só ocorrência falha o *scan*. É isso
 * que o torna uma salvaguarda, e é a razão por que a caixa do critério 7 se
 * pode marcar com esta leitura escrita por extenso ao lado.
 *
 * ## Porque é TypeScript e não YAML
 *
 * Porque o `numeros.ts` já explica porque é que este pacote não traz um quarto
 * leitor de YAML ao repositório, e porque uma lista com razões em prosa lê-se
 * melhor com os comentários onde eles pertencem.
 */

/** Uma entrada do inventário. */
export interface Entrada {
  /** O caminho, relativo à raiz do repositório, com `/`. */
  readonly ficheiro: string;
  /** Quantas ocorrências aquele ficheiro tem. Exacto, não um tecto. */
  readonly ocorrencias: number;
  /** O que o número está a testar. Sem isto a entrada é um defeito. */
  readonly razao: string;
}

/**
 * Os ficheiros que levam números de forma real, medidos em 2026-10-20 com
 * `meta-sim varrer`.
 *
 * As contagens **não foram escritas à mão**: saíram do próprio *scan*. Quem
 * mexer num destes ficheiros corre `meta-sim varrer` e actualiza o número, que
 * é a única maneira de a contagem continuar a querer dizer algo.
 */
export const INVENTARIO: readonly Entrada[] = [
  // --- Os detectores de PII, que têm de disparar ---------------------------
  {
    ficheiro: "packages/core-ts/src/eventos/pii.ts",
    ocorrencias: 1,
    razao:
      "o exemplo na docstring do padrao que o guarda de platform.evt_emitir usa; " +
      "um exemplo que nao casasse o proprio padrao enganava quem o lesse",
  },
  {
    ficheiro: "packages/core-ts/src/identity/cripto.ts",
    ocorrencias: 2,
    razao: "o exemplo de E.164 na docstring da normalizacao de telefone (KAM-006)",
  },
  {
    ficheiro: "tools/contract_diff/cli.py",
    ocorrencias: 1,
    razao: "o exemplo de achado que o gate 7 imprime, na ajuda do comando",
  },
  {
    ficheiro: "tools/contract_diff/tests/test_pii.py",
    ocorrencias: 7,
    razao:
      "controlo positivo do gate 7: sem um numero de forma angolana a suite nao " +
      "prova que o detector o ve, e um zero sobre uma entrada limpa nao diz nada",
  },
  {
    ficheiro: "packages/core-ts/tests/avisos.test.ts",
    ocorrencias: 2,
    razao:
      "os nomes de loja do varrimento de 200 avisos do KAM-115, criterio 5: o " +
      "aviso ao dono mascara corridas de sete ou mais digitos no nome da loja " +
      "porque «Loja do Ze 923 456 789» e um nome plausivel em Luanda, e sem " +
      "numeros de forma real o teste provava que a mascara apanha numeros que " +
      "nao se parecem com telefones — que e o contrario do que ela existe para " +
      "fazer. Nenhum pertence a ninguem: sao sequenciais a partir do prefixo " +
      "movel, como os das outras entradas desta lista",
  },
  {
    ficheiro: "db/tests_agr/test_checkpointer.py",
    ocorrencias: 3,
    razao:
      "o controlo positivo do criterio 2 do KAM-026: o estado do checkpointer " +
      "vai em `msgpack` para uma coluna `bytea`, pelo que uma busca por texto " +
      "devolve **zero** com um telefone la dentro. O varrimento desserializa, e " +
      "so prova alguma coisa depois de se mostrar que encontra o que la esta — " +
      "pelo que o ensaio semeia um numero e exige que o encontre. Sao **tres** " +
      "formas e nao uma: a internacional que o criterio escreve, a mesma sem o " +
      "`+`, e a **local** com espacos, que e a que um cliente angolano escreve " +
      "no WhatsApp e que a primeira versao da expressao nao apanhava. Nenhum " +
      "pertence a ninguem: sao sequenciais a partir do prefixo movel, como os " +
      "das outras entradas desta lista",
  },
  {
    ficheiro: "tools/log_policy/tests/test_x11.py",
    ocorrencias: 6,
    razao:
      "a suite X-11 de docs/tecnica/08 §3.7: 1 000 chamadas com telefones reais " +
      "pelos dois loggers, e a saida de Python tem de ser igual a de TypeScript",
  },
  // --- Os dois loggers e a sua paridade ------------------------------------
  {
    ficheiro: "packages/core-ts/tests/logger.test.ts",
    ocorrencias: 4,
    razao: "controlo positivo da redaccao do logger de TypeScript (KAM-068)",
  },
  {
    ficheiro: "libs/py-core/tests/test_logger.py",
    ocorrencias: 3,
    razao: "controlo positivo da redaccao do logger de Python (KAM-068)",
  },
  {
    ficheiro: "libs/py-core/tests/test_logger_ponte.py",
    ocorrencias: 1,
    razao: "a ponte entre os dois loggers, pela mesma razao",
  },
  {
    ficheiro: "packages/core-ts/tests/fixtures/logger_paridade.json",
    ocorrencias: 5,
    razao:
      "as entradas da paridade byte a byte entre os dois loggers; e JSON e nao " +
      "leva comentario, e por isso a razao vive aqui",
  },
  // --- Os contratos de evento e o guarda de PII ----------------------------
  {
    ficheiro: "packages/core-ts/tests/eventos.pii.test.ts",
    ocorrencias: 6,
    razao: "controlo positivo do guarda de PII dos envelopes (KAM-007)",
  },
  {
    ficheiro: "packages/core-ts/tests/eventos.envelope.test.ts",
    ocorrencias: 2,
    razao: "um envelope que o guarda tem de recusar",
  },
  {
    ficheiro: "packages/core-ts/tests/eventos.publicador.test.ts",
    ocorrencias: 2,
    razao: "o publicador recusa publicar um payload com telefone",
  },
  {
    ficheiro: "packages/core-ts/tests/fixtures/eventos_pii.json",
    ocorrencias: 9,
    razao:
      "as nove formas que o detector de PII tem de apanhar, incluindo as que " +
      "casam por pouco; e JSON e nao leva comentario",
  },
  {
    ficheiro: "db/tests/test_eventos_schema.py",
    ocorrencias: 9,
    razao: "o guarda de platform.evt_emitir recusa no lado da base (KAM-007)",
  },
  {
    ficheiro: "db/tests_eventos/test_publicador.py",
    ocorrencias: 2,
    razao: "o mesmo, pelo lado do publicador a correr contra a base",
  },
  // --- A entrada de canal --------------------------------------------------
  {
    ficheiro: "packages/core-ts/tests/entrada.explosao.test.ts",
    ocorrencias: 2,
    razao:
      "a explosao de um corpo da Meta com a forma que o trafego tem; os wamid " +
      "do KAM-013 contem o numero, e e isso que o idOpaco fecha",
  },
  {
    ficheiro: "packages/core-ts/tests/entrada.registo.test.ts",
    ocorrencias: 1,
    razao: "o registo da entrada nao escreve o telefone que recebeu",
  },
  {
    ficheiro: "packages/core-ts/tests/identity.cripto.test.ts",
    ocorrencias: 2,
    razao:
      "os dois E.164 que a normalizacao tem de recusar: um dos EUA e um com " +
      "zero a cabeca, que sao os casos de fronteira do KAM-006",
  },
  {
    ficheiro: "services/gwy/tests/webhook.test.ts",
    ocorrencias: 1,
    razao:
      "o canario do criterio 9 do KAM-013: 1 000 pedidos com telefones reais " +
      "nos logs tem de dar 0 achados, e um canario ficticio nao provava nada",
  },
  // --- Desenho -------------------------------------------------------------
  {
    ficheiro: "docs/tecnica/05_Indice_Pesquisa_Motor_Atencao.md",
    ocorrencias: 3,
    razao:
      "os tres numeros de exemplo do desenho do indice de pesquisa; o prefixo " +
      "900 nao e atribuido a nenhuma operadora angolana",
  },
  // --- Este ticket ---------------------------------------------------------
  {
    ficheiro: "tools/meta-sim/tests/captura.test.ts",
    ocorrencias: 12,
    razao:
      "a captura «real» que o saneador tem de limpar, e o scan que tem de a " +
      "detectar; sem numeros de forma real estes testes nao testavam nada",
  },
  {
    ficheiro: "tools/meta-sim/tests/simulador.test.ts",
    ocorrencias: 5,
    razao: "o controlo positivo de telefonesReais e de exigirFicticios",
  },
];

/** O que o *scan* mediu num ficheiro. */
export interface Medicao {
  readonly ficheiro: string;
  readonly ocorrencias: number;
}

/** Uma divergência entre o inventário e o que o *scan* mediu. */
export interface Divergencia {
  readonly ficheiro: string;
  readonly tipo: "nao_declarado" | "a_mais" | "a_menos" | "entrada_morta" | "sem_razao";
  readonly declaradas: number;
  readonly medidas: number;
  readonly razao: string;
}

/** A frase de uma divergência, para o relatório do CI. */
export function frase(d: Divergencia): string {
  switch (d.tipo) {
    case "nao_declarado":
      return `${d.ficheiro}: ${d.medidas} numero(s) de forma real e nenhuma entrada no inventario`;
    case "a_mais":
      return `${d.ficheiro}: ${d.medidas} numero(s) e o inventario declara ${d.declaradas}`;
    case "a_menos":
      return (
        `${d.ficheiro}: ${d.medidas} numero(s) e o inventario declara ${d.declaradas} — ` +
        "baixe a contagem, senao o inventario deixa de contar"
      );
    case "entrada_morta":
      return `${d.ficheiro}: declarado no inventario e sem numero nenhum (ou o ficheiro desapareceu)`;
    case "sem_razao":
      return `${d.ficheiro}: a entrada do inventario nao diz porque e que o numero esta la`;
  }
}

/** O comprimento mínimo de uma razão. Uma palavra não é uma razão. */
const RAZAO_MINIMA = 30;

/**
 * Confronta o inventário com o que o *scan* mediu.
 *
 * `medicoes` traz **só** os ficheiros com ocorrências; um ficheiro declarado que
 * não apareça lá é uma entrada morta, e é por isso que a comparação é nos dois
 * sentidos e não só num.
 */
export function confrontar(
  medicoes: readonly Medicao[],
  inventario: readonly Entrada[] = INVENTARIO,
): readonly Divergencia[] {
  const divergencias: Divergencia[] = [];
  const declarado = new Map(inventario.map((e) => [e.ficheiro, e]));
  const medido = new Map(medicoes.map((m) => [m.ficheiro, m.ocorrencias]));

  for (const entrada of inventario) {
    if (entrada.razao.trim().length < RAZAO_MINIMA) {
      divergencias.push({
        ficheiro: entrada.ficheiro,
        tipo: "sem_razao",
        declaradas: entrada.ocorrencias,
        medidas: medido.get(entrada.ficheiro) ?? 0,
        razao: entrada.razao,
      });
    }
  }

  for (const [ficheiro, ocorrencias] of medido) {
    const entrada = declarado.get(ficheiro);
    if (entrada === undefined) {
      divergencias.push({ ficheiro, tipo: "nao_declarado", declaradas: 0, medidas: ocorrencias, razao: "" });
      continue;
    }
    if (ocorrencias > entrada.ocorrencias) {
      divergencias.push({
        ficheiro,
        tipo: "a_mais",
        declaradas: entrada.ocorrencias,
        medidas: ocorrencias,
        razao: entrada.razao,
      });
    } else if (ocorrencias < entrada.ocorrencias) {
      divergencias.push({
        ficheiro,
        tipo: "a_menos",
        declaradas: entrada.ocorrencias,
        medidas: ocorrencias,
        razao: entrada.razao,
      });
    }
  }

  for (const entrada of inventario) {
    if (!medido.has(entrada.ficheiro)) {
      divergencias.push({
        ficheiro: entrada.ficheiro,
        tipo: "entrada_morta",
        declaradas: entrada.ocorrencias,
        medidas: 0,
        razao: entrada.razao,
      });
    }
  }

  // Comparação de cadeias e **não** `localeCompare`: o `localeCompare` depende
  // do locale e do ICU do *runner*, e a ordem desta lista vai para a evidência.
  // Um diff que mude de máquina para máquina é um diff que ninguém lê.
  const antes = (x: string, y: string): number => (x < y ? -1 : x > y ? 1 : 0);
  return divergencias.sort(
    (a, b) => antes(a.ficheiro, b.ficheiro) || antes(a.tipo, b.tipo),
  );
}

/** O total declarado. Para o relatório, e para ver se sobe. */
export function totalDeclarado(inventario: readonly Entrada[] = INVENTARIO): number {
  return inventario.reduce((soma, e) => soma + e.ocorrencias, 0);
}
