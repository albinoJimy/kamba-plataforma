/**
 * Passa as *fixtures* do X-11 pelo *logger* em TypeScript (KAM-068).
 *
 *     node packages/core-ts/tests/x11_conduzir.ts <fixtures.json> <saida.log> <contadores.json>
 *
 * É o espelho de `tools/log_policy/conduzir.py`. Os dois fazem a mesma chamada
 * por *fixture*, com o mesmo relógio parado, e escrevem **uma linha por
 * *fixture***: o `make x11` compara a saída dos dois byte a byte, e os
 * contadores de rejeição também.
 *
 * Não é um teste (`*.test.ts`): é corrido pelo `make x11`, no gate 6. Vive em
 * `tests/` para ser verificado pelo `tsc` como o resto e para não entrar no
 * `dist/` do pacote.
 */

import { readFileSync, writeFileSync } from "node:fs";

import { CONTADORES, Logger } from "../src/logger/index.ts";

interface Fixture {
  chamada: {
    nivel: unknown;
    posicionais: unknown[];
    campos: Record<string, unknown>;
    erro: { classe: string; mensagem: string } | null;
    codigo: unknown;
  };
}

const RELOGIO_PARADO = new Date("2026-01-01T00:00:00.000Z");
const SERVICO = "x11";

function erroComClasse(classe: string, mensagem: string): Error {
  const Classe = { [classe]: class extends Error {} }[classe] as new (m: string) => Error;
  return new Classe(mensagem);
}

export function conduzir(fixtures: readonly Fixture[]): [string, Record<string, number>] {
  let texto = "";
  const registo = new Logger(SERVICO, {
    destino: {
      write(pedaco: string): void {
        texto += pedaco;
      },
    },
    relogio: () => RELOGIO_PARADO,
    estrito: false,
  });
  CONTADORES.repor();
  for (const { chamada } of fixtures) {
    if (chamada.erro !== null) {
      registo.excepcao(
        erroComClasse(chamada.erro.classe, chamada.erro.mensagem),
        chamada.codigo as string,
        chamada.campos as never,
      );
    } else {
      registo.registar(chamada.nivel, chamada.posicionais, chamada.campos);
    }
  }
  const contadores = CONTADORES.ler();
  CONTADORES.repor();
  return [texto, contadores];
}

/** As chaves por ordem, como o `json.dumps(sort_keys=True)` do lado Python. */
function contadoresOrdenados(contadores: Record<string, number>): string {
  const ordenados = Object.keys(contadores)
    .sort()
    .map((nome) => `${JSON.stringify(nome)}: ${contadores[nome]}`);
  return `{${ordenados.join(", ")}}\n`;
}

function principal(argumentos: readonly string[]): number {
  const [fixtures, saida, contadores] = argumentos;
  if (fixtures === undefined || saida === undefined || contadores === undefined) {
    return 2;
  }
  const dados = JSON.parse(readFileSync(fixtures, "utf8")) as Fixture[];
  const [texto, contagem] = conduzir(dados);
  writeFileSync(saida, texto, "utf8");
  writeFileSync(contadores, contadoresOrdenados(contagem), "utf8");
  return 0;
}

if (import.meta.main) {
  process.exitCode = principal(process.argv.slice(2));
}
