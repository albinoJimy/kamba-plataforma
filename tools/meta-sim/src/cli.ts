#!/usr/bin/env node
/**
 * O CLI do simulador (KAM-024).
 *
 * Seis comandos, e cada um existe por causa de um critério:
 *
 * | Comando | Critério |
 * |---|---|
 * | `gerar` | 1 e 2 — escreve as *fixtures* e as suas assinaturas |
 * | `cobertura` | 2 — o relatório de ≥ 1 *fixture* e ≥ 1 teste por item |
 * | `varrer` | 7 — o *scan* de «0 telefones reais no repositório» |
 * | `sanear` | 7 — converte uma captura real em *fixture* |
 * | `graph` | 5 — levanta o servidor Graph falso |
 * | `assinar` | 4 — o cabeçalho de um corpo, para `curl` à mão |
 *
 * ## Os códigos de saída, e porque é que isso é a parte séria
 *
 * `0` é conforme, `2` é «há achados», `1` é «a ferramenta não conseguiu correr».
 * A distinção não é cosmética: o gate 7 lê o código, e um `varrer` que falhasse
 * com `0` por não ter conseguido ler um ficheiro era um *scan* verde sobre um
 * repositório que ninguém varreu — a armadilha que o `references/` desta skill
 * descreve, e a razão por que `sair()` nunca devolve `0` por omissão.
 *
 * ## O CLI não imprime o que encontra, quando o que encontra é um telefone
 *
 * O `varrer` diz o ficheiro, a linha, a coluna e o **padrão**; não diz o número.
 * Um relatório de CI é público e fica no histórico das execuções: imprimir o
 * número que se acabou de encontrar põe o dado pessoal exactamente onde o
 * critério 7 o quer tirar. Quem corrige abre o ficheiro na linha indicada.
 */

import { readdirSync, readFileSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";

import { assinar, exigirSegredoDeEnsaio, segredoDeEnsaio } from "./assinatura.ts";
import { sanear, varrer } from "./captura.ts";
import { emMarkdown, relatorio } from "./cobertura.ts";
import { texto as textoDoCorpo } from "./corpo.ts";
import { contagemPorItem, todasAsFixtures } from "./fixtures.ts";
import { GraphFalso } from "./graph.ts";
import { confrontar, frase, totalDeclarado, type Medicao } from "./inventario.ts";
import { Gerador } from "./semente.ts";

/** A semente por omissão. Fixa, para que `gerar` sem argumentos seja estável. */
const SEMENTE = "kamba-piloto";

/** O que o varrimento nunca abre. */
const IGNORADOS = new Set([
  "node_modules",
  ".git",
  "dist",
  "build",
  ".venv",
  "__pycache__",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  ".claude",
  "coverage",
]);

/** As extensões que o varrimento lê. Tudo o que não é texto fica de fora. */
const EXTENSOES = new Set([
  ".ts",
  ".js",
  ".mjs",
  ".cjs",
  ".json",
  ".py",
  ".md",
  ".yaml",
  ".yml",
  ".sql",
  ".toml",
  ".sh",
  ".txt",
  ".env",
  ".example",
]);

function extensaoDe(nome: string): string {
  const ponto = nome.lastIndexOf(".");
  return ponto < 0 ? "" : nome.slice(ponto);
}

function* ficheiros(raiz: string): Generator<string> {
  for (const entrada of readdirSync(raiz, { withFileTypes: true })) {
    if (IGNORADOS.has(entrada.name)) continue;
    const caminho = join(raiz, entrada.name);
    if (entrada.isDirectory()) {
      yield* ficheiros(caminho);
      continue;
    }
    if (!entrada.isFile()) continue;
    if (!EXTENSOES.has(extensaoDe(entrada.name))) continue;
    yield caminho;
  }
}

function argumento(argv: readonly string[], nome: string, omissao: string): string {
  const indice = argv.indexOf(`--${nome}`);
  if (indice < 0) return omissao;
  return argv[indice + 1] ?? omissao;
}

/** `gerar`: escreve as *fixtures* e as assinaturas. */
function comandoGerar(argv: readonly string[]): number {
  const semente = argumento(argv, "semente", SEMENTE);
  const saida = resolve(argumento(argv, "saida", "fixtures"));
  const segredo = segredoDeEnsaio(semente);
  exigirSegredoDeEnsaio(segredo);

  mkdirSync(saida, { recursive: true });
  const fixtures = todasAsFixtures(semente, segredo);
  for (const fixture of fixtures) {
    // Os bytes gravados são **os** bytes assinados: escrever o corpo com
    // `JSON.stringify(..., 2)` e guardar a assinatura do compacto dava um par
    // que nenhum GWY aceita, e o erro só aparecia no primeiro teste de contrato.
    writeFileSync(join(saida, `${fixture.nome}.json`), Buffer.from(fixture.bytes));
    writeFileSync(join(saida, `${fixture.nome}.sig`), `${fixture.assinatura}\n`, "utf8");
  }
  process.stdout.write(`[KAM-024] ${fixtures.length} fixtures em ${saida}\n`);
  return 0;
}

/** `cobertura`: o relatório do critério 2. Sai com 2 se houver faltas. */
function comandoCobertura(argv: readonly string[]): number {
  const semente = argumento(argv, "semente", SEMENTE);
  const raiz = resolve(argumento(argv, "testes", join(import.meta.dirname, "..", "tests")));
  const segredo = segredoDeEnsaio(semente);
  const fixtures = todasAsFixtures(semente, segredo);

  const fontes: string[] = [];
  for (const caminho of ficheiros(raiz)) fontes.push(readFileSync(caminho, "utf8"));

  const r = relatorio(contagemPorItem(fixtures), fontes);
  process.stdout.write(`${emMarkdown(r)}\n`);
  if (r.marcasDesconhecidas.length > 0) return 2;
  return r.faltas.length === 0 ? 0 : 2;
}

/**
 * `varrer`: o *scan* do critério 7, confrontado com o inventário.
 *
 * O *scan* conta; o inventário diz o que é tolerável e porquê. Um ficheiro com
 * um número e sem entrada falha; uma entrada com a contagem errada falha nos
 * dois sentidos; uma entrada morta falha. Ver `inventario.ts` para a razão de
 * ser um raquete e não uma isenção.
 */
function comandoVarrer(argv: readonly string[]): number {
  const raizes = argv.filter((a) => !a.startsWith("--"));
  const alvos = raizes.length > 0 ? raizes : ["."];
  // `--cru` imprime os achados sem confrontar, que é como se mede a contagem de
  // uma entrada nova do inventário.
  const cru = argv.includes("--cru");
  const raiz = resolve(".");
  const medicoes: Medicao[] = [];
  let total = 0;
  let lidos = 0;

  for (const alvo of alvos) {
    const caminho = resolve(alvo);
    const info = statSync(caminho);
    const lista = info.isDirectory() ? [...ficheiros(caminho)] : [caminho];
    for (const ficheiro of lista) {
      lidos += 1;
      const achados = varrer(readFileSync(ficheiro, "utf8"));
      if (achados.length === 0) continue;
      total += achados.length;
      // O caminho vai sempre com `/`, para que o inventário seja o mesmo em
      // Windows e no CI. Um inventário com `\` numa máquina e `/` na outra
      // dava «não declarado» para tudo, no sítio onde ninguém olha.
      const relativo = relative(raiz, ficheiro).split(sep).join("/");
      medicoes.push({ ficheiro: relativo, ocorrencias: achados.length });
      if (!cru) continue;
      for (const achado of achados) {
        // Sem o valor: ver a nota do módulo.
        process.stdout.write(
          `${relativo}:${achado.linha}:${achado.coluna}: ` +
            `telefone de forma real (padrao ${achado.padrao})\n`,
        );
      }
    }
  }

  if (lidos === 0) {
    // Zero ficheiros lidos **não** é zero achados: é um varrimento que não
    // aconteceu, e devolver 0 aqui transformava o gate num enfeite.
    process.stderr.write("[KAM-024] varrer: 0 ficheiros lidos — o alvo esta vazio?\n");
    return 1;
  }

  if (cru) {
    process.stdout.write(
      `[KAM-024] varrer --cru: ${lidos} ficheiros, ${total} ocorrencias em ` +
        `${medicoes.length} ficheiros\n`,
    );
    return 0;
  }

  const divergencias = confrontar(medicoes);
  for (const d of divergencias) process.stdout.write(`${frase(d)}\n`);
  process.stdout.write(
    `[KAM-024] varrer: ${lidos} ficheiros, ${total} ocorrencias de forma real, ` +
      `${totalDeclarado()} declaradas no inventario, ${divergencias.length} divergencias\n`,
  );
  return divergencias.length === 0 ? 0 : 2;
}

/** `sanear`: converte uma captura real em *fixture*. */
function comandoSanear(argv: readonly string[]): number {
  const entrada = argv.find((a) => !a.startsWith("--"));
  if (entrada === undefined) {
    process.stderr.write("uso: meta-sim sanear <ficheiro.json> [--semente S] [--saida F]\n");
    return 1;
  }
  const semente = argumento(argv, "semente", `captura/${new Date().toISOString()}`);
  const bruto: unknown = JSON.parse(readFileSync(resolve(entrada), "utf8"));
  const saneamento = sanear(bruto, semente);
  const destino = argumento(argv, "saida", "");
  const conteudo = textoDoCorpo(saneamento.arvore, "espacado");
  if (destino === "") {
    process.stdout.write(`${conteudo}\n`);
  } else {
    writeFileSync(resolve(destino), `${conteudo}\n`, "utf8");
  }
  const categorias = Object.entries(saneamento.substituicoes)
    .map(([nome, quantos]) => `${nome}=${quantos}`)
    .join(" ");
  process.stderr.write(
    `[KAM-024] saneado: ${saneamento.numerosNaEntrada} telefone(s) na entrada, ` +
      `substituicoes ${categorias}\n`,
  );
  return 0;
}

/** `graph`: levanta o servidor Graph falso e fica à escuta. */
async function comandoGraph(argv: readonly string[]): Promise<number> {
  const porta = Number.parseInt(argumento(argv, "porta", "0"), 10);
  const semente = argumento(argv, "semente", SEMENTE);
  const servidor = new GraphFalso(new Gerador(`${semente}/graph`));
  const { base } = await servidor.ouvir(Number.isNaN(porta) ? 0 : porta);
  process.stdout.write(`[KAM-024] graph falso em ${base}\n`);
  // Fica à escuta até o processo ser terminado: é um servidor, e sair aqui
  // fechava-o antes de alguém o usar.
  await new Promise<void>((resolver) => {
    process.on("SIGINT", () => resolver());
    process.on("SIGTERM", () => resolver());
  });
  return 0;
}

/** `assinar`: o cabeçalho de um ficheiro, para um `curl` à mão. */
function comandoAssinar(argv: readonly string[]): number {
  const entrada = argv.find((a) => !a.startsWith("--"));
  if (entrada === undefined) {
    process.stderr.write("uso: meta-sim assinar <ficheiro.json> [--semente S]\n");
    return 1;
  }
  const segredo = segredoDeEnsaio(argumento(argv, "semente", SEMENTE));
  exigirSegredoDeEnsaio(segredo);
  const bytes = new Uint8Array(readFileSync(resolve(entrada)));
  process.stdout.write(`${assinar(bytes, segredo)}\n`);
  return 0;
}

const AJUDA = `meta-sim — simulador de webhooks Meta (KAM-024)

  gerar      [--semente S] [--saida DIR]   escreve as fixtures e as assinaturas
  cobertura  [--semente S] [--testes DIR]  relatorio de cobertura (2 se houver faltas)
  varrer     [caminhos...] [--cru]         scan de telefones reais contra o inventario
  sanear     <ficheiro> [--saida F]        converte uma captura real em fixture
  graph      [--porta P]                   levanta o servidor Graph falso
  assinar    <ficheiro>                    o cabeçalho x-hub-signature-256
`;

async function principal(argv: readonly string[]): Promise<number> {
  const [comando, ...resto] = argv;
  switch (comando) {
    case "gerar":
      return comandoGerar(resto);
    case "cobertura":
      return comandoCobertura(resto);
    case "varrer":
      return comandoVarrer(resto);
    case "sanear":
      return comandoSanear(resto);
    case "graph":
      return comandoGraph(resto);
    case "assinar":
      return comandoAssinar(resto);
    default:
      process.stdout.write(AJUDA);
      return comando === undefined || comando === "--ajuda" || comando === "-h" ? 0 : 1;
  }
}

const codigo = await principal(process.argv.slice(2)).catch((erro: unknown) => {
  // A mensagem de um `NumeroRealError` ou de um `SegredoDeVerdadeError` é a
  // parte útil; o rasto não é, e num deles pode levar o número encontrado.
  process.stderr.write(`[KAM-024] ${erro instanceof Error ? erro.message : String(erro)}\n`);
  return 1;
});
process.exit(codigo);
