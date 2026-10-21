/**
 * O teste de arquitectura do MED (KAM-020, critério 8).
 *
 * «O MED não importa módulos de PAY nem de COM (teste de arquitectura): 0
 * caminhos de código que alterem estado de pagamento a partir de uma imagem.»
 *
 * O ADR-013 é o porquê: **uma imagem pode ser um comprovativo de pagamento e
 * nunca é prova.** Um cliente manda a fotografia de um depósito e o pagamento
 * só muda de estado por um evento autenticado do banco ou do facilitador — não
 * por alguém, ou algum modelo, ter olhado para a imagem.
 *
 * ## Porque é que este teste lê a FONTE e não corre código
 *
 * O critério pede «0 caminhos de código», e um teste de comportamento não prova
 * zero caminhos: prova que os caminhos que ele exercita não fazem aquilo. O que
 * prova zero é a **ausência da importação** — se o módulo não pode nomear o
 * PAY, não há caminho possível, e não é preciso confiar em disciplina.
 *
 * É a mesma forma que o `lint_arch` usa para as dependências de `package.json`,
 * e pela mesma razão que o seu `__init__.py` escreve: «uma lista de bloqueio tem
 * de poder correr *antes* de qualquer `pnpm install`». Aqui: antes de qualquer
 * execução.
 *
 * **E o `lint_arch` não cobre isto**, que é a razão de este ficheiro existir: a
 * ferramenta tem `blocklist.py` (dependências de npm), `structure.py`,
 * `names.py` e `conventions.py` — nenhum olha para importações **entre módulos**
 * de `packages/core-ts/src/`. Fica dito aqui para que quem a alargar saiba que
 * este teste pode desaparecer para lá.
 *
 * ## O que este teste vai apanhar, e quando
 *
 * O `pay/` e o `com/` **ainda não existem** em `packages/core-ts/src/` (são
 * KAM-052 e KAM-041 em diante). Um teste que procurasse `from "../pay/..."`
 * passaria hoje por o alvo não existir, e isso não é uma garantia — é um acaso
 * com data de validade. Por isso o teste é escrito ao contrário: enumera as
 * importações que o MED **tem** e exige que cada uma esteja numa lista
 * aprovada. Uma importação nova de qualquer sítio falha aqui, incluindo de um
 * módulo que ainda não nasceu.
 */

import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";

const RAIZ = new URL("../src/med/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

/**
 * Os módulos de que o MED pode depender, e cada um com a razão.
 *
 * **Lista de permissão e não de bloqueio**, pela razão da nota do módulo: uma
 * lista de bloqueio só apanha o que alguém se lembrou de proibir, e o `pay/`
 * ainda não existe para ser proibido.
 */
const PERMITIDOS: Readonly<Record<string, string>> = {
  "../logger/index.ts": "o registo, com a lista branca de nove campos (KAM-068)",
  "../storage/index.ts": "a porta do armazenamento (KAM-011), que o MED consome",
  "../entrada/index.ts": "o vocabulario `WA_TYPES` do webhook (KAM-013)",
};

/** Os módulos cuja importação é o defeito que o critério 8 nomeia. */
const PROIBIDOS = ["pay", "com", "pagamento", "payment"];

function ficheiros(): string[] {
  return readdirSync(RAIZ)
    .filter((nome) => nome.endsWith(".ts"))
    .map((nome) => join(RAIZ, nome));
}

function importacoes(fonte: string): string[] {
  // Apanha `import ... from "x"` e `export ... from "x"`, com e sem `type`.
  const achadas: string[] = [];
  for (const casa of fonte.matchAll(/(?:import|export)[^;]*?from\s+"([^"]+)"/g)) {
    const alvo = casa[1];
    if (alvo !== undefined) achadas.push(alvo);
  }
  return achadas;
}

describe("o MED nao importa PAY nem COM (criterio 8)", () => {
  it("**ha ficheiros para ler**, senao este teste nao prova nada", () => {
    // Um `readdirSync` sobre uma pasta errada devolve lista vazia, e um ciclo
    // sobre lista vazia passa sempre. E o modo de falha mais silencioso que um
    // teste de ficheiros tem, e e a razao deste controlo.
    const lidos = ficheiros();
    assert.ok(lidos.length >= 5, `so ${lidos.length} ficheiros em ${RAIZ}`);
    for (const caminho of lidos) {
      assert.ok(readFileSync(caminho, "utf8").length > 0, caminho);
    }
  });

  it("**cada importacao esta na lista de permissao**", () => {
    // Ao contrario e de proposito: enumerar o que ha e exigir aprovacao apanha
    // uma importacao de um modulo que **ainda nao existe**, e uma lista de
    // bloqueio nao.
    for (const caminho of ficheiros()) {
      const fonte = readFileSync(caminho, "utf8");
      for (const alvo of importacoes(fonte)) {
        // As do proprio modulo (`./x.ts`) sao sempre permitidas: e o modulo a
        // falar consigo.
        if (alvo.startsWith("./")) continue;
        assert.ok(
          alvo in PERMITIDOS,
          `${caminho} importa ${alvo}, que nao esta na lista de permissao do ` +
            "`med.arquitectura.test.ts`. Se a importacao e legitima, acrescente-a " +
            "**com a razao**; se e de PAY ou COM, o criterio 8 do KAM-020 e o " +
            "ADR-013 dizem que nao.",
        );
      }
    }
  });

  it("nenhum ficheiro nomeia PAY nem COM, de nenhuma forma", () => {
    // O teste de cima apanha a importacao; este apanha a mencao — um
    // `await import("../pay/x.ts")` dinamico, por exemplo, que a expressao do
    // outro teste nao ve.
    for (const caminho of ficheiros()) {
      const fonte = readFileSync(caminho, "utf8");
      for (const proibido of PROIBIDOS) {
        assert.ok(
          !fonte.includes(`"../${proibido}/`) && !fonte.includes(`'../${proibido}/`),
          `${caminho} nomeia o modulo ${proibido}`,
        );
      }
    }
  });

  it("**nenhum ficheiro escreve um estado de pagamento**", () => {
    // O criterio pede «0 caminhos de codigo que alterem estado de pagamento a
    // partir de uma imagem». Sem importacao nao ha caminho, e este e o terceiro
    // cinto: nenhuma instrucao SQL deste modulo toca numa tabela de pagamento.
    for (const caminho of ficheiros()) {
      const fonte = readFileSync(caminho, "utf8").toLowerCase();
      for (const tabela of ["payments", "pagamentos", "payment_intents", "settlements"]) {
        assert.ok(!fonte.includes(tabela), `${caminho} menciona a tabela ${tabela}`);
      }
    }
  });

  it("a lista de permissao tem uma razao escrita por entrada", () => {
    // Uma lista de permissao sem razoes torna-se uma lista de tudo o que alguem
    // ja precisou, e e assim que ela deixa de dizer nao.
    for (const [alvo, razao] of Object.entries(PERMITIDOS)) {
      assert.ok(razao.length > 20, `${alvo} nao tem razao escrita`);
    }
  });
});
