/**
 * A tabela de transições dos modos da conversa (KAM-018, critério 1).
 *
 * **O teste é exaustivo e não uma amostra**, e é isso que o critério pede: as
 * **trinta e duas** células — quatro modos × oito gatilhos — são afirmadas uma a
 * uma contra uma tabela escrita à mão neste ficheiro, e não derivada da
 * `TABELA` do módulo. Uma expectativa derivada da implementação prova que a
 * implementação é igual a si mesma.
 *
 * Três propriedades que só um teste exaustivo dá:
 *
 * 1. nenhum par (modo, gatilho) fica sem decisão escrita;
 * 2. o conjunto das células que **transitam** é exactamente o de
 *    `docs/tecnica/01` §10.2 mais as duas declaradas (o `dono → humano` do
 *    diagrama e o `pausada → humano` de `E1` §4);
 * 3. **qualquer outra transição é rejeitada** — e «qualquer outra» é o
 *    complemento das 32, que só se pode afirmar enumerando.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  GATILHOS,
  type Gatilho,
  MODOS,
  type Modo,
  SILENCIO_DO_DONO_MS,
  TABELA,
  celulasQueTransitam,
  origensDe,
  silencioExpirou,
  transitar,
} from "../src/modos/index.ts";

const T0 = new Date("2026-11-02T14:00:00.000Z");

/** Muito antes de `T0`: o dono está calado há mais de `silencio_dono_min`. */
const SILENCIO_LONGO = new Date(T0.getTime() - SILENCIO_DO_DONO_MS - 1);
/** Há um instante: o dono acabou de falar. */
const SILENCIO_CURTO = new Date(T0.getTime() - 1);

/**
 * O que **cada uma** das 32 células faz. Escrita à mão, a partir de
 * `docs/tecnica/01` §10.2 e do critério 1, e não derivada da `TABELA`.
 *
 * `"→<modo>"` transita, `"-"` é sem efeito, `"x"` é rejeitada. A forma curta é
 * deliberada: assim a tabela cabe no ecrã e lê-se como a do documento, que é o
 * que permite conferi-las lado a lado.
 *
 * O contexto usado é `SILENCIO_LONGO` — o dono calado há muito —, que é o que
 * torna a célula `dono + cliente_escreveu` uma transição. O caso contrário tem
 * teste próprio, mais abaixo.
 */
const ESPERADO: Readonly<Record<Modo, Readonly<Record<Gatilho, string>>>> = {
  bot: {
    echo_do_dono: "→dono",
    cliente_escreveu: "-",
    comando_bot: "-",
    handoff_pedido: "→humano",
    handoff_resolvido: "x",
    opt_out: "→pausada",
    sem_humano_24h: "x",
    cliente_reactivou: "x",
  },
  dono: {
    echo_do_dono: "-",
    cliente_escreveu: "→bot",
    comando_bot: "→bot",
    handoff_pedido: "→humano",
    handoff_resolvido: "x",
    opt_out: "→pausada",
    sem_humano_24h: "x",
    cliente_reactivou: "x",
  },
  humano: {
    echo_do_dono: "-",
    cliente_escreveu: "-",
    comando_bot: "x",
    handoff_pedido: "-",
    handoff_resolvido: "→bot",
    opt_out: "→pausada",
    sem_humano_24h: "→pausada",
    cliente_reactivou: "x",
  },
  pausada: {
    echo_do_dono: "-",
    cliente_escreveu: "-",
    comando_bot: "x",
    handoff_pedido: "→humano",
    handoff_resolvido: "x",
    opt_out: "-",
    sem_humano_24h: "x",
    cliente_reactivou: "→bot",
  },
};

function comoTexto(modo: Modo, gatilho: Gatilho, ultima: Date | null): string {
  const resposta = transitar({ mode: modo, ultimaActividadeHumana: ultima }, gatilho, T0);
  if (resposta.tipo === "rejeitada") return "x";
  if (resposta.tipo === "sem_efeito") return "-";
  return `→${resposta.para}`;
}

describe("as 32 celulas da tabela (criterio 1)", () => {
  it("sao 4 modos x 8 gatilhos, e a tabela tem-nas todas", () => {
    assert.equal(MODOS.length, 4);
    assert.equal(GATILHOS.length, 8);
    let celulas = 0;
    for (const modo of MODOS) {
      for (const gatilho of GATILHOS) {
        assert.ok(TABELA[modo][gatilho] !== undefined, `${modo}/${gatilho}`);
        celulas += 1;
      }
    }
    assert.equal(celulas, 32);
  });

  // **Uma asserção por célula**, com o nome do par na mensagem: quando uma
  // falhar, o que se lê é «dono/comando_bot: esperado →bot, deu x» e não «a
  // tabela está errada».
  for (const modo of MODOS) {
    for (const gatilho of GATILHOS) {
      it(`${modo} + ${gatilho} = ${ESPERADO[modo][gatilho]}`, () => {
        assert.equal(
          comoTexto(modo, gatilho, SILENCIO_LONGO),
          ESPERADO[modo][gatilho],
          `${modo}/${gatilho}`,
        );
      });
    }
  }

  it("nenhuma celula aponta para o proprio modo", () => {
    // **Este teste substitui duas guardas inalcançáveis**, e a prova por mutação
    // foi quem o pediu: o `transitar` tinha um
    // `if (celula.para === estado.mode) return sem_efeito` e o `origensDe` um
    // `de !== para`, e apagar os dois não fazia nenhum teste falhar — porque
    // nenhuma célula da tabela aponta para o próprio modo. O «não acontece
    // nada» escreve-se `para: null`, e é isso que torna o `opt_out` repetido
    // idempotente sem chave nenhuma.
    //
    // O invariante passou a ser afirmado em vez de defendido. Se ele cair, duas
    // coisas quebram de uma vez: o `origensDe` devolve o modo de destino como
    // origem válida, e o `UPDATE` casa uma linha que já está no destino —
    // contando e publicando uma transição que não aconteceu.
    for (const modo of MODOS) {
      for (const gatilho of GATILHOS) {
        assert.notEqual(
          TABELA[modo][gatilho].para,
          modo,
          `${modo}/${gatilho}: uma celula que aponta para o proprio modo escreve-se \`para: null\``,
        );
      }
    }
  });

  it("qualquer outra transicao e rejeitada: o complemento das 32 e vazio", () => {
    // O que isto afirma é que **não há** par (modo, gatilho) fora dos 32, e que
    // nenhum dos 32 transita para um modo que o `ESPERADO` não nomeie. É o
    // «qualquer outra» do critério, e só se consegue dizer por enumeração.
    const transitam = celulasQueTransitam();
    for (const { de, gatilho, para } of transitam) {
      assert.equal(ESPERADO[de][gatilho], `→${para}`, `${de}/${gatilho}`);
    }
    const esperadasQueTransitam = MODOS.flatMap((de) =>
      GATILHOS.filter((g) => ESPERADO[de][g].startsWith("→")).map((g) => `${de}/${g}`),
    );
    assert.equal(transitam.length, esperadasQueTransitam.length);
  });
});

describe("de onde vem cada transicao", () => {
  it("as doze transicoes, com a fonte de cada uma", () => {
    // A `fonte` de cada célula é o que permite auditar as duas que vão além do
    // critério 1. Se alguém acrescentar uma célula `invariante` que transite,
    // este teste falha — e é o que se quer: uma transição sem fonte escrita é
    // uma transição inventada.
    const porFonte = new Map<string, string[]>();
    for (const { de, gatilho, para, fonte } of celulasQueTransitam()) {
      const lista = porFonte.get(fonte) ?? [];
      lista.push(`${de}+${gatilho}→${para}`);
      porFonte.set(fonte, lista);
    }
    assert.deepEqual(
      [...porFonte.keys()].sort(),
      ["01§10.2 diagrama", "01§10.2 tabela", "E1§4"],
      "nenhuma transicao pode ter fonte `invariante`",
    );
    assert.deepEqual(porFonte.get("01§10.2 diagrama"), ["dono+handoff_pedido→humano"]);
    assert.deepEqual(porFonte.get("E1§4"), ["pausada+handoff_pedido→humano"]);
    // As dez da tabela do §10.2 e do critério 1.
    assert.deepEqual((porFonte.get("01§10.2 tabela") ?? []).sort(), [
      "bot+echo_do_dono→dono",
      "bot+handoff_pedido→humano",
      "bot+opt_out→pausada",
      "dono+cliente_escreveu→bot",
      "dono+comando_bot→bot",
      "dono+opt_out→pausada",
      "humano+handoff_resolvido→bot",
      "humano+opt_out→pausada",
      "humano+sem_humano_24h→pausada",
      "pausada+cliente_reactivou→bot",
    ]);
  });

  it("o `qualquer -> pausada` do criterio cobre os tres modos que nao sao `pausada`", () => {
    // O critério escreve «qualquer→`pausada` por opt-out», e o diagrama só tem
    // duas das três arestas. Resolve-se a favor do critério: os três.
    assert.deepEqual([...origensDe("opt_out", "pausada")].sort(), [
      "bot",
      "dono",
      "humano",
    ]);
  });

  it("o `sem_humano_24h` so sai de `humano`", () => {
    // «24 h sem humano **após handoff**»: em `bot` e em `dono` não há *handoff*
    // de que contar, e é por isso que o «qualquer» do critério não se lê aqui.
    assert.deepEqual([...origensDe("sem_humano_24h", "pausada")], ["humano"]);
  });
});

describe("o silencio do dono (criterio 1)", () => {
  it("sao 30 minutos, o numero do §10.2", () => {
    assert.equal(SILENCIO_DO_DONO_MS, 30 * 60 * 1000);
  });

  it("o dono acabou de falar: o cliente nao devolve a palavra ao bot", () => {
    assert.equal(comoTexto("dono", "cliente_escreveu", SILENCIO_CURTO), "-");
  });

  it("exactamente 30 minutos devolve a palavra: o limite e inclusivo", () => {
    const limite = new Date(T0.getTime() - SILENCIO_DO_DONO_MS);
    assert.equal(comoTexto("dono", "cliente_escreveu", limite), "→bot");
    // Um milissegundo a menos não.
    const quase = new Date(T0.getTime() - SILENCIO_DO_DONO_MS + 1);
    assert.equal(comoTexto("dono", "cliente_escreveu", quase), "-");
  });

  it("sem actividade humana registada, o silencio conta como expirado", () => {
    // Ver a nota de `silencioExpirou`: uma conversa em `dono` sem instante de
    // onde contar devolve a palavra ao assistente em vez de ficar presa.
    assert.equal(silencioExpirou({ mode: "dono", ultimaActividadeHumana: null }, T0), true);
    assert.equal(comoTexto("dono", "cliente_escreveu", null), "→bot");
  });

  it("o `comando_bot` devolve a palavra sem esperar pelo silencio", () => {
    // É a outra metade da linha `dono → bot` do §10.2: «**ou** o dono envia o
    // comando `/bot`». Se o comando esperasse pelo silêncio, o dono não tinha
    // forma de devolver a conversa ao bot imediatamente.
    assert.equal(comoTexto("dono", "comando_bot", SILENCIO_CURTO), "→bot");
  });
});

describe("origensDe: o predicado que a base aplica", () => {
  it("nao inclui o modo de destino", () => {
    // Senão o `UPDATE` casava uma linha que já estava no destino, e uma
    // transição inexistente era contada e publicada.
    for (const gatilho of GATILHOS) {
      for (const para of MODOS) {
        assert.ok(!origensDe(gatilho, para).includes(para), `${gatilho}/${para}`);
      }
    }
  });

  it("so inclui os modos cuja celula aponta para esse destino", () => {
    // **Não é «todos os modos menos o destino».** Um `opt_out` concorrente com
    // um `handoff_pedido` não se deve poder aplicar sobre o resultado do outro.
    assert.deepEqual([...origensDe("handoff_resolvido", "bot")], ["humano"]);
    assert.deepEqual([...origensDe("cliente_reactivou", "bot")], ["pausada"]);
    assert.deepEqual([...origensDe("echo_do_dono", "dono")], ["bot"]);
    assert.deepEqual([...origensDe("handoff_pedido", "humano")].sort(), [
      "bot",
      "dono",
      "pausada",
    ]);
  });

  it("um gatilho que nao chega a esse destino devolve lista vazia", () => {
    assert.deepEqual([...origensDe("cliente_escreveu", "humano")], []);
    assert.deepEqual([...origensDe("opt_out", "bot")], []);
  });
});
