/**
 * O critério 8: a reconciliação nocturna classifica órfãos e recursos em falta
 * (KAM-091).
 *
 * O critério pede quatro comportamentos distintos, e os quatro estão medidos:
 *
 * 1. compara `tenants` ≠ `encerrado` com o que está lá fora;
 * 2. classifica `orfao_externo` e `externo_em_falta`;
 * 3. compensa automaticamente **só** órfãos de casos `cancelado` há > 24 h;
 * 4. e **apenas** os criados por esta saga (etiqueta).
 *
 * As 3 e 4 são duas condições e não uma, e o `compensavel` é exportado para que
 * cada uma possa ser medida a negar **sozinha**. Um predicado composto testado
 * só pelo caso verdadeiro passa com qualquer das condições apagada — é a
 * armadilha que este ficheiro existe para não ter.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  HORAS_PARA_COMPENSAR,
  Metricas,
  classificar,
  compensavel,
  reconciliar,
  type Caso,
  type Divergencia,
  type EsperadoDoTenant,
  type RecursoInventariado,
} from "../src/provisioning/index.ts";

const TENANT_A = "11111111-1111-4111-8111-111111111111";
const TENANT_B = "22222222-2222-4222-8222-222222222222";

function orfao(parcial: Partial<Divergencia> = {}): Divergencia {
  return {
    classe: "orfao_externo",
    recurso: "chave_llm",
    ref: "k-1",
    tenantId: TENANT_A,
    nosso: true,
    compensado: false,
    ...parcial,
  };
}

describe("a classificacao, pura e nas duas direccoes", () => {
  it("um recurso que ninguem reclama e `orfao_externo`", () => {
    const foraDeCa: RecursoInventariado[] = [
      { recurso: "chave_llm", ref: "k-orfa", tenantId: null, nosso: true },
    ];
    const divergencias = classificar(foraDeCa, []);
    assert.equal(divergencias.length, 1);
    assert.equal(divergencias[0]?.classe, "orfao_externo");
    assert.equal(divergencias[0]?.ref, "k-orfa");
  });

  it("um recurso que um tenant vivo tem como `concluido` e que nao esta la e `externo_em_falta`", () => {
    const esperado: EsperadoDoTenant[] = [
      { tenantId: TENANT_A, refs: [{ recurso: "chave_llm", ref: "k-1" }] },
    ];
    const divergencias = classificar([], esperado);
    assert.equal(divergencias.length, 1);
    assert.equal(divergencias[0]?.classe, "externo_em_falta");
    assert.equal(divergencias[0]?.tenantId, TENANT_A);
  });

  /**
   * **O caminho legítimo**: o que está dos dois lados não é divergência.
   *
   * Sem isto, uma função que classificasse tudo como divergência passava os dois
   * ensaios acima.
   */
  it("um recurso presente nos dois lados nao e divergencia nenhuma", () => {
    const foraDeCa: RecursoInventariado[] = [
      { recurso: "chave_llm", ref: "k-1", tenantId: TENANT_A, nosso: true },
    ];
    const esperado: EsperadoDoTenant[] = [
      { tenantId: TENANT_A, refs: [{ recurso: "chave_llm", ref: "k-1" }] },
    ];
    assert.deepEqual(classificar(foraDeCa, esperado), []);
  });

  /**
   * **«Recurso não criado por nós é ignorado»**, que o critério pede por
   * palavras — e o que «ignorado» significa aqui é *classificado e não
   * compensado*, não *invisível*.
   *
   * Classificá-lo é certo: a equipa quer ver na reconciliação que há uma conta
   * no Chatwoot que não é de tenant nenhum. O que não se pode é apagá-la — e
   * isso é o `compensavel`, medido abaixo.
   */
  it("um recurso que nao e nosso e visto, classificado e marcado `nosso: false`", () => {
    const foraDeCa: RecursoInventariado[] = [
      { recurso: "conta_atendimento", ref: "conta-da-equipa", tenantId: null, nosso: false },
    ];
    const divergencias = classificar(foraDeCa, []);
    assert.equal(divergencias.length, 1);
    assert.equal(divergencias[0]?.nosso, false);
  });

  /**
   * **A janela do critério 4, vista do outro lado.**
   *
   * Um recurso de um tenant **vivo** que ainda não está no `provisioning_step`
   * não é órfão: é a saga a meio de registar o que acabou de criar. As duas
   * correm à mesma hora numa noite com falha injectada, e classificá-lo como
   * órfão fazia a reconciliação apagar o que a saga acabou de criar.
   */
  it("um recurso de tenant vivo ainda sem linha `concluido` NAO e orfao", () => {
    const foraDeCa: RecursoInventariado[] = [
      { recurso: "chave_llm", ref: "k-recem-criada", tenantId: TENANT_A, nosso: true },
    ];
    // O tenant está vivo, mas o `provisioning_step` ainda não tem esta ref.
    const esperado: EsperadoDoTenant[] = [{ tenantId: TENANT_A, refs: [] }];
    assert.deepEqual(classificar(foraDeCa, esperado), []);
  });

  it("um recurso de tenant que nao esta vivo e orfao, mesmo trazendo `tenant_id`", () => {
    const foraDeCa: RecursoInventariado[] = [
      { recurso: "chave_llm", ref: "k-de-encerrado", tenantId: TENANT_B, nosso: true },
    ];
    const esperado: EsperadoDoTenant[] = [{ tenantId: TENANT_A, refs: [] }];
    const divergencias = classificar(foraDeCa, esperado);
    assert.equal(divergencias.length, 1);
    assert.equal(divergencias[0]?.classe, "orfao_externo");
    assert.equal(divergencias[0]?.tenantId, TENANT_B);
  });

  it("as duas classes aparecem na mesma passagem sem se confundirem", () => {
    const foraDeCa: RecursoInventariado[] = [
      { recurso: "chave_llm", ref: "k-orfa", tenantId: null, nosso: true },
    ];
    const esperado: EsperadoDoTenant[] = [
      { tenantId: TENANT_A, refs: [{ recurso: "canal_comercio", ref: "canal-em-falta" }] },
    ];
    const divergencias = classificar(foraDeCa, esperado);
    assert.equal(divergencias.filter((d) => d.classe === "orfao_externo").length, 1);
    assert.equal(divergencias.filter((d) => d.classe === "externo_em_falta").length, 1);
  });
});

describe("as tres condicoes da compensacao automatica, cada uma a negar sozinha", () => {
  const cancelados = new Set([TENANT_A]);

  it("as tres satisfeitas: compensa", () => {
    assert.equal(compensavel(orfao(), cancelados), true);
  });

  it("nega so a classe: um `externo_em_falta` nunca se compensa", () => {
    assert.equal(compensavel(orfao({ classe: "externo_em_falta" }), cancelados), false);
  });

  it("nega so a etiqueta: um recurso que nao e nosso nunca se compensa", () => {
    assert.equal(compensavel(orfao({ nosso: false }), cancelados), false);
  });

  it("nega so o caso cancelado: um tenant que nao esta cancelado ha >24h nao se compensa", () => {
    assert.equal(compensavel(orfao({ tenantId: TENANT_B }), cancelados), false);
  });

  it("nega so o tenant conhecido: sem `tenant_id` nao ha caso para datar", () => {
    assert.equal(compensavel(orfao({ tenantId: null }), cancelados), false);
  });

  it("o limiar e 24 horas, e e *proposta*", () => {
    assert.equal(HORAS_PARA_COMPENSAR, 24);
  });
});

describe("a reconciliacao nocturna inteira", () => {
  function montarRec(opcoes: {
    foraDeCa: readonly RecursoInventariado[];
    esperado: readonly EsperadoDoTenant[];
    cancelados?: readonly string[];
    falharCompensacao?: boolean;
  }) {
    const compensados: RecursoInventariado[] = [];
    const metricas = new Metricas();
    const casos = (opcoes.cancelados ?? []).map(
      (tenantId): Caso => ({
        onboardingId: `ob-${tenantId}`,
        tenantId,
        plano: "piloto",
        vertical: "vendedor",
      }),
    );
    return {
      compensados,
      metricas,
      dependencias: {
        casos: {
          porId: async () => null,
          canceladosHaMaisDe: async () => casos,
          vivos: async () => [],
        },
        inventario: { listar: async () => opcoes.foraDeCa },
        esperado: async () => opcoes.esperado,
        compensarOrfao: async (r: RecursoInventariado) => {
          if (opcoes.falharCompensacao === true) throw new Error("provedor_indisponivel");
          compensados.push(r);
        },
        metricas,
      },
    };
  }

  /** O critério 3 pede «a reconciliação nocturna seguinte reporta 0 órfãos». */
  it("sem divergencias reporta zero orfaos e zero em falta", async () => {
    const r = montarRec({
      foraDeCa: [{ recurso: "chave_llm", ref: "k-1", tenantId: TENANT_A, nosso: true }],
      esperado: [{ tenantId: TENANT_A, refs: [{ recurso: "chave_llm", ref: "k-1" }] }],
    });
    const relatorio = await reconciliar(r.dependencias as never);
    assert.equal(relatorio.orfaos, 0);
    assert.equal(relatorio.emFalta, 0);
    assert.equal(relatorio.compensados, 0);
  });

  it("um orfao semeado e detectado e compensado quando o caso esta cancelado ha >24h", async () => {
    const r = montarRec({
      foraDeCa: [{ recurso: "chave_llm", ref: "k-orfa", tenantId: TENANT_A, nosso: true }],
      esperado: [],
      cancelados: [TENANT_A],
    });
    const relatorio = await reconciliar(r.dependencias as never);

    assert.equal(relatorio.compensados, 1);
    assert.deepEqual(
      r.compensados.map((c) => c.ref),
      ["k-orfa"],
    );
    // **Zero órfãos no relatório**: o que foi compensado deixou de ser órfão
    // pendente, e é esse número que o critério de saída do epic conta a zero por
    // catorze noites.
    assert.equal(relatorio.orfaos, 0);
  });

  it("um orfao que nao e nosso e reportado e NAO e compensado", async () => {
    const r = montarRec({
      foraDeCa: [
        { recurso: "conta_atendimento", ref: "conta-da-equipa", tenantId: TENANT_A, nosso: false },
      ],
      esperado: [],
      cancelados: [TENANT_A],
    });
    const relatorio = await reconciliar(r.dependencias as never);

    assert.deepEqual(r.compensados, [], "compensou um recurso que a saga nao criou");
    assert.equal(relatorio.orfaos, 1, "um orfao que nao e nosso tem de ficar visivel");
  });

  it("um orfao de caso que nao esta cancelado ha >24h e reportado e nao compensado", async () => {
    const r = montarRec({
      foraDeCa: [{ recurso: "chave_llm", ref: "k-orfa", tenantId: TENANT_A, nosso: true }],
      esperado: [],
      cancelados: [],
    });
    const relatorio = await reconciliar(r.dependencias as never);
    assert.deepEqual(r.compensados, []);
    assert.equal(relatorio.orfaos, 1);
  });

  it("um recurso em falta e reportado e nunca compensado", async () => {
    const r = montarRec({
      foraDeCa: [],
      esperado: [{ tenantId: TENANT_A, refs: [{ recurso: "canal_comercio", ref: "canal-1" }] }],
      cancelados: [TENANT_A],
    });
    const relatorio = await reconciliar(r.dependencias as never);
    assert.equal(relatorio.emFalta, 1);
    assert.deepEqual(r.compensados, [], "tentou compensar um recurso que nao esta la");
  });

  /**
   * Uma compensação que falha **não** pára as outras, ao contrário da
   * compensação da saga. A diferença é que estes órfãos são independentes: são
   * de casos diferentes, sem ordem entre si, e nenhum é a credencial com que
   * outro se desfaz.
   */
  it("uma compensacao que falha nao impede as outras e o orfao fica reportado", async () => {
    const r = montarRec({
      foraDeCa: [
        { recurso: "chave_llm", ref: "k-1", tenantId: TENANT_A, nosso: true },
        { recurso: "canal_comercio", ref: "c-1", tenantId: TENANT_A, nosso: true },
      ],
      esperado: [],
      cancelados: [TENANT_A],
      falharCompensacao: true,
    });
    const relatorio = await reconciliar(r.dependencias as never);
    assert.equal(relatorio.compensados, 0);
    assert.equal(relatorio.orfaos, 2, "uma falha escondeu o segundo orfao");
  });

  it("as duas series de `saga_orfaos` sao escritas, incluindo a que fica a zero", async () => {
    const r = montarRec({
      foraDeCa: [{ recurso: "chave_llm", ref: "k-orfa", tenantId: null, nosso: true }],
      esperado: [],
    });
    await reconciliar(r.dependencias as never);

    assert.equal(r.metricas.valor('saga_orfaos{classe="orfao_externo"}'), 1);
    // **Zero e não ausente.** Uma série que desaparece fica no último valor em
    // qualquer painel que a tenha visto.
    assert.equal(r.metricas.valor('saga_orfaos{classe="externo_em_falta"}'), 0);
  });

  it("antes da primeira reconciliacao, `saga_orfaos` vale -1 e nao 0", () => {
    const m = new Metricas();
    assert.equal(m.valor('saga_orfaos{classe="orfao_externo"}'), -1);
    // «Não sei» não é «zero»: um `0` antes de alguém olhar satisfazia o critério
    // de saída do epic («0 órfãos em 14 noites») sem medir nada.
  });
});
