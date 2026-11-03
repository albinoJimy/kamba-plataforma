/**
 * G2–G7, a parte que o *worker* decide (KAM-053).
 *
 * O que estes ensaios defendem, e que não se lê na tabela do §5 sem pensar:
 *
 *     a ORDEM            o G7 vem antes do G6, e invertê-los transforma toda a
 *                        reentrega de um callback num caso de reembolso
 *     o valor «a mais»   o F-02 diz «a menos ou a mais»; um `>=` deixava passar
 *                        metade
 *     o que não se sabe  quando o facilitador não devolve a entidade, a segunda
 *                        metade do G2 **não se avalia** em vez de se adivinhar
 *     a escrita          `pagamento_recebido` primeiro, em todos os veredictos
 *                        que o têm: o facto antes do juízo
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ESTADOS_QUE_ACEITAM,
  GATES_DO_WORKER,
  type CobrancaParaGates,
  type ContaParaGates,
  type DestinoDoEvento,
  type EntradaDosGates,
  avaliarGates,
  escritasDoVeredicto,
  reciboDoVeredicto,
} from "../src/pagamentos/index.ts";
import type { VerifiedEvent } from "../src/pagamentos/index.ts";

const CONTA: ContaParaGates = {
  accountId: "9c3d1a7e-0000-4000-8000-000000000001",
  entidade: "00123",
  posId: "pos-1",
};

const COBRANCA: CobrancaParaGates = {
  chargeId: "aaaaaaaa-0000-4000-8000-000000000001",
  accountId: CONTA.accountId,
  referencia: "REF123456789",
  amountMinor: 1_250_000n,
  currency: "AOA",
  estado: "emitida",
};

const EVENTO: VerifiedEvent = {
  providerEventId: "ev-1",
  referencia: "REF123456789",
  valor: 1_250_000n,
  currency: "AOA",
  authnMethod: "hmac",
  ocorridoEm: "2026-11-02T10:00:00.000Z",
};

function entrada(extra: Partial<EntradaDosGates> = {}): EntradaDosGates {
  return {
    evento: EVENTO,
    conta: CONTA,
    cobranca: COBRANCA,
    jaRegistado: false,
    ...extra,
  };
}

describe("gates do worker: o caminho que confirma", () => {
  it("test_g2_a_g7_cumpridos_confirmam", () => {
    assert.deepEqual(avaliarGates(entrada()), { tipo: "confirmado" });
  });

  it("test_os_tres_estados_que_aceitam_confirmam", () => {
    for (const estado of ESTADOS_QUE_ACEITAM) {
      assert.deepEqual(
        avaliarGates(
          entrada({ cobranca: { ...COBRANCA, estado } }),
        ),
        { tipo: "confirmado" },
        `o estado ${estado} tem de aceitar (G6)`,
      );
    }
  });

  it("test_a_lista_dos_gates_e_a_do_§5", () => {
    // O G1 é do *handler* e o G8 é do KAM-054 — ver o cabeçalho do módulo. Que
    // esta lista tenha **seis** e não oito é uma afirmação sobre o escopo, e
    // por isso tem ensaio.
    assert.deepEqual(GATES_DO_WORKER, ["G2", "G3", "G4", "G5", "G6", "G7"]);
  });
});

describe("gates do worker: a ordem do G7 antes do G6", () => {
  it("test_uma_reentrega_sobre_uma_cobranca_paga_e_duplicado_e_nao_duplo", () => {
    // **É o ensaio que justifica a ordem.** A reentrega de um callback cujo
    // pagamento já confirmou tem a cobrança em `paga` — isto é, falha G6. O
    // §7.2 manda o F-01 («200, sem efeito», recibo `duplicado`) e **não** o
    // F-08 (pagamento duplo, que abre um `refund_cases`). Avaliar G6 primeiro
    // transformava toda a reentrega num caso de reembolso.
    const veredicto = avaliarGates(
      entrada({ cobranca: { ...COBRANCA, estado: "paga" }, jaRegistado: true }),
    );
    assert.deepEqual(veredicto, { tipo: "duplicado" });
    assert.deepEqual(escritasDoVeredicto(veredicto), []);
    assert.equal(reciboDoVeredicto(veredicto), "duplicado");
  });

  it("test_um_segundo_pagamento_real_sobre_uma_paga_e_duplo", () => {
    // O F-08 a sério: entrega **nova** (`jaRegistado: false`) sobre uma
    // cobrança já paga. É o caso que abre `refund_cases` (KAM-054), e é o que
    // tem de se distinguir do de cima.
    const veredicto = avaliarGates(
      entrada({ cobranca: { ...COBRANCA, estado: "paga" } }),
    );
    assert.deepEqual(veredicto, { tipo: "duplo", gate: "G6" });
    assert.deepEqual(
      escritasDoVeredicto(veredicto).map((e) => e.tipo),
      ["pagamento_recebido", "pagamento_duplicado"],
    );
  });

  it("test_o_g3_vem_antes_de_todos", () => {
    // Sem cobrança nenhum dos outros tem com o que comparar — e `orfao` é um
    // veredicto diferente de `divergente`: o §8 diz «**não reconhecer** no
    // facilitador», porque o pagamento pode ser de outra integração da PME.
    const veredicto = avaliarGates(
      entrada({ cobranca: null, jaRegistado: true }),
    );
    assert.deepEqual(veredicto, { tipo: "orfao" });
    // **Nada vai para o ledger**, e a revisão adversarial mostrou porquê: o
    // `pagamento_orfao` é impossível de escrever (um órfão não tem cobrança, e
    // a porta exige um `charge_id` visível numa coluna `NOT NULL` com FK).
    // Prescrever uma escrita impossível era pior do que não prescrever
    // nenhuma: o *worker* que a seguisse abortava a transacção e repetia o
    // callback para sempre. O registo é o recibo e o alerta.
    assert.deepEqual(escritasDoVeredicto(veredicto), []);
    assert.equal(reciboDoVeredicto(veredicto), "ignorado");
  });
});

describe("gates do worker: as divergências", () => {
  it("test_g2_conta_diferente_da_cobranca", () => {
    assert.deepEqual(
      avaliarGates(
        entrada({
          conta: { ...CONTA, accountId: "9c3d1a7e-0000-4000-8000-00000000000f" },
        }),
      ),
      {
        tipo: "divergente",
        gate: "G2",
        motivo: "entidade_divergente",
        estadoDaCobranca: "emitida",
      },
    );
  });

  it("test_g2_entidade_do_evento_diferente_da_conta", () => {
    assert.deepEqual(avaliarGates(entrada({ destino: { entidade: "00999" } })), {
      tipo: "divergente",
      gate: "G2",
      motivo: "entidade_divergente",
      estadoDaCobranca: "emitida",
    });
  });

  it("test_g2_sem_entidade_no_evento_nao_se_avalia_a_segunda_metade", () => {
    // **O que não se sabe não se adivinha.** O §3.2 diz que não todos os
    // facilitadores devolvem a entidade; tratar a ausência como divergência
    // reprovava pagamentos genuínos, e tratá-la como igualdade afirmava o que
    // não se mediu. A primeira metade do G2 — a conta do *token* — basta-se.
    const semEntidade: readonly (DestinoDoEvento | undefined)[] = [
      undefined,
      {},
      { entidade: null },
      { posId: null },
    ];
    for (const destino of semEntidade) {
      // O `destino` e omitido quando e `undefined`, e nao passado como
      // `undefined`: `exactOptionalPropertyTypes` distingue as duas coisas, e e
      // a distincao que importa aqui — «o facilitador nao devolveu a entidade»
      // nao e «devolveu `undefined`».
      const extra = destino === undefined ? {} : { destino };
      assert.deepEqual(
        avaliarGates(entrada(extra)),
        { tipo: "confirmado" },
        `destino ${JSON.stringify(destino)} nao e divergencia`,
      );
    }
  });

  it("test_g4_valor_a_menos_e_a_mais_sao_os_dois_divergencia", () => {
    // F-02: «a menos **ou a mais**». Um `>=` deixava passar metade, e um
    // pagamento a mais sem registo é dinheiro de um cliente que ninguém
    // reconciliou.
    for (const valor of [1_249_999n, 1_250_001n]) {
      assert.deepEqual(
        avaliarGates(entrada({ evento: { ...EVENTO, valor } })),
        {
          tipo: "divergente",
          gate: "G4",
          motivo: "valor_divergente",
          estadoDaCobranca: "emitida",
        },
        `o valor ${valor} tem de ser divergencia`,
      );
    }
  });

  it("test_g4_moeda_diferente_de_aoa_e_divergencia", () => {
    assert.deepEqual(
      avaliarGates(
        entrada({ evento: { ...EVENTO, currency: "USD" as never } }),
      ),
      {
        tipo: "divergente",
        gate: "G4",
        motivo: "valor_divergente",
        estadoDaCobranca: "emitida",
      },
    );
  });

  it("test_g5_referencia_diferente_e_divergencia", () => {
    assert.deepEqual(
      avaliarGates(entrada({ evento: { ...EVENTO, referencia: "REF000000000" } })),
      {
        tipo: "divergente",
        gate: "G5",
        motivo: "referencia_divergente",
        estadoDaCobranca: "emitida",
      },
    );
  });

  it("test_g5_nao_se_aplica_a_uma_cobranca_sem_referencia", () => {
    // Um `express_push` não tem referência (a coluna é anulável no §6.2), e não
    // há nada para comparar. Comparar `null` com o que o evento trouxe dava
    // divergência em todo o pagamento por *push*.
    assert.deepEqual(
      avaliarGates(entrada({ cobranca: { ...COBRANCA, referencia: null } })),
      { tipo: "confirmado" },
    );
  });

  it("test_a_divergencia_escreve_o_facto_antes_do_juizo", () => {
    const veredicto = avaliarGates(
      entrada({ evento: { ...EVENTO, valor: 1n } }),
    );
    assert.deepEqual(
      escritasDoVeredicto(veredicto).map((e) => [e.tipo, e.decisao]),
      [
        ["pagamento_recebido", "informativo"],
        ["pagamento_divergente", "rejeitada"],
      ],
    );
  });

  it("test_fora_de_emitida_a_divergencia_escreve_so_o_facto", () => {
    // **Uma correcção da revisão adversarial.** O `pagamento_divergente` é
    // aresta do §7.1 **só** a partir de `emitida` (dívida 163). A primeira
    // versão prescrevia-o sempre, e a consequência está medida: a partir de
    // `aguarda_cliente` ou de `pendente_confirmacao` a porta levanta
    // `check_violation` e **reverte a transacção inteira** — incluindo o
    // `pagamento_recebido` que a precede. Isto é, o facto perdia-se por causa
    // da decisão.
    //
    // Onde a aresta não existe, fica o facto. O veredicto continua a dizer
    // `divergente`, pelo que ops é alertado do mesmo modo.
    for (const estado of ["aguarda_cliente", "pendente_confirmacao"]) {
      const veredicto = avaliarGates(
        entrada({
          cobranca: { ...COBRANCA, estado },
          evento: { ...EVENTO, valor: 1n },
        }),
      );
      assert.equal(veredicto.tipo, "divergente");
      assert.deepEqual(
        escritasDoVeredicto(veredicto).map((e) => e.tipo),
        ["pagamento_recebido"],
        `a partir de ${estado} o §7.1 não desenha a aresta da divergência`,
      );
    }
  });

  it("test_os_motivos_sao_os_nomes_do_motivo_falha", () => {
    // Os três são valores do domínio `payment_charges.motivo_falha` do §6.2, e
    // não uma lista paralela: o que o *worker* decide é o que a porta escreve
    // na cobrança. Duas listas com os mesmos significados é como nasce uma
    // divergência de vocabulário — a lição do dicionário §3.
    const motivos = new Set<string>();
    for (const entradaMa of [
      entrada({ evento: { ...EVENTO, valor: 1n } }),
      entrada({ evento: { ...EVENTO, referencia: "X" } }),
      entrada({ destino: { entidade: "00999" } }),
    ]) {
      const veredicto = avaliarGates(entradaMa);
      if (veredicto.tipo === "divergente") {
        motivos.add(veredicto.motivo);
        assert.equal(
          veredicto.estadoDaCobranca,
          "emitida",
          "o veredicto leva o estado, que é o que decide se a decisão se escreve",
        );
      }
    }
    assert.deepEqual(
      [...motivos].sort(),
      ["entidade_divergente", "referencia_divergente", "valor_divergente"],
    );
  });
});

describe("gates do worker: o pagamento tardio", () => {
  it("test_uma_cobranca_expirada_da_tardio_e_nao_confirmado", () => {
    // O §7.1 desenha `expirada --> paga: pagamento tardio autenticado`, e o
    // §6.6 do documento 03 põe condições que **este módulo não conhece** — se a
    // reserva se consegue refazer. O veredicto diz `tardio` e passa a decisão
    // ao COM em vez de a tomar.
    const veredicto = avaliarGates(
      entrada({ cobranca: { ...COBRANCA, estado: "expirada" } }),
    );
    assert.deepEqual(veredicto, { tipo: "tardio" });
    // E escreve **só o facto**: a confirmação vem depois, se o COM a mandar.
    assert.deepEqual(
      escritasDoVeredicto(veredicto).map((e) => e.tipo),
      ["pagamento_recebido"],
    );
    assert.equal(reciboDoVeredicto(veredicto), "processado");
  });

  it("test_os_estados_terminais_dao_duplo_e_nao_tardio", () => {
    for (const estado of ["cancelada", "reembolsada", "falhada", "paga"]) {
      const veredicto = avaliarGates(
        entrada({ cobranca: { ...COBRANCA, estado } }),
      );
      assert.deepEqual(
        veredicto,
        { tipo: "duplo", gate: "G6" },
        `o estado ${estado} nao e um pagamento tardio`,
      );
    }
  });
});

describe("gates do worker: nenhum veredicto escreve paga directamente", () => {
  it("test_nenhuma_escrita_e_um_update_de_estado", () => {
    // **A afirmação central do ticket, vista deste lado.** O que o *worker*
    // produz são tipos de evento para a porta — nunca um estado. Se alguma
    // destas listas trouxesse `paga`, havia um caminho em que o estado se
    // escrevia a partir do veredicto em vez de ser projectado por `next_state`.
    const todos = [
      avaliarGates(entrada()),
      avaliarGates(entrada({ jaRegistado: true })),
      avaliarGates(entrada({ cobranca: null })),
      avaliarGates(entrada({ evento: { ...EVENTO, valor: 1n } })),
      avaliarGates(entrada({ cobranca: { ...COBRANCA, estado: "expirada" } })),
      avaliarGates(entrada({ cobranca: { ...COBRANCA, estado: "paga" } })),
      avaliarGates(
        entrada({
          cobranca: { ...COBRANCA, estado: "aguarda_cliente" },
          evento: { ...EVENTO, valor: 1n },
        }),
      ),
    ];
    for (const veredicto of todos) {
      for (const escrita of escritasDoVeredicto(veredicto)) {
        assert.notEqual(escrita.tipo, "paga");
        assert.ok(
          escrita.tipo.startsWith("pagamento_"),
          `${escrita.tipo} nao e um tipo de evento do ledger`,
        );
      }
    }
  });

  it("test_so_o_veredicto_confirmado_produz_pagamento_confirmado", () => {
    const todos = [
      ["confirmado", avaliarGates(entrada())],
      ["duplicado", avaliarGates(entrada({ jaRegistado: true }))],
      ["orfao", avaliarGates(entrada({ cobranca: null }))],
      ["divergente", avaliarGates(entrada({ evento: { ...EVENTO, valor: 1n } }))],
      ["tardio", avaliarGates(entrada({ cobranca: { ...COBRANCA, estado: "expirada" } }))],
      ["duplo", avaliarGates(entrada({ cobranca: { ...COBRANCA, estado: "paga" } }))],
    ] as const;
    for (const [nome, veredicto] of todos) {
      const confirma = escritasDoVeredicto(veredicto).some(
        (e) => e.tipo === "pagamento_confirmado",
      );
      assert.equal(
        confirma,
        nome === "confirmado",
        `o veredicto ${nome} ${confirma ? "confirma" : "nao confirma"} e devia ser o contrario`,
      );
    }
  });
});
