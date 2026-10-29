/**
 * A maquina de `payment_accounts.estado` (KAM-052, criterio 8).
 *
 * O criterio pede tres coisas e as tres tem ensaio nomeado:
 *
 *     funcao pura                      `test_e_pura`
 *     `nao_iniciado -> ativo` rejeitada  `test_nao_iniciado_para_ativo_e_rejeitada`
 *     `teste_sandbox_ok -> ativo` exige  `test_sandbox_para_ativo_exige_o_sinal`
 *     o sinal
 *
 * E uma quarta que o criterio nao pede e sem a qual os tres nao valem muito: que
 * a tabela de arestas seja **exactamente** a do diagrama do §10.2, nem uma a
 * mais. Uma aresta a mais e um caminho de ciclo de vida que ninguem desenhou.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ESTADOS_DA_CONTA,
  ESTADOS_QUE_OCUPAM,
  GATILHOS,
  SINAL_EM_FALTA,
  TRANSICAO_INEXISTENTE,
  type EstadoDaConta,
  type Gatilho,
  podeCobrar,
  transitar,
} from "../src/pagamentos/index.ts";

/** O diagrama do §10.2, transcrito. E a fonte contra a qual a tabela se mede. */
const DIAGRAMA: readonly [EstadoDaConta, Gatilho, EstadoDaConta][] = [
  ["nao_iniciado", "docs_recolhidos", "docs_recolhidos"],
  ["docs_recolhidos", "pedido_ao_banco", "banco_em_curso"],
  ["banco_em_curso", "servicos_emis_contratados", "facilitador_em_curso"],
  ["facilitador_em_curso", "contrato_assinado", "credenciais_recebidas"],
  ["credenciais_recebidas", "sandbox_e_pagamento_de_teste", "teste_sandbox_ok"],
  ["teste_sandbox_ok", "primeira_cobranca_conciliada", "ativo"],
  ["ativo", "fraude_divergencia_ou_pedido", "suspenso"],
  ["suspenso", "regularizacao", "ativo"],
  ["ativo", "encerramento", "revogado"],
];

const SINAIS_COMPLETOS = { primeiraCobrancaRealConciliada: true } as const;

describe("pagamentos/estados: o dominio", () => {
  it("sao os nove estados do CHECK do §6.2", () => {
    assert.equal(ESTADOS_DA_CONTA.length, 9);
    assert.deepEqual(
      [...ESTADOS_DA_CONTA].sort(),
      [
        "ativo",
        "banco_em_curso",
        "credenciais_recebidas",
        "docs_recolhidos",
        "facilitador_em_curso",
        "nao_iniciado",
        "revogado",
        "suspenso",
        "teste_sandbox_ok",
      ],
    );
  });

  it("sao os nove gatilhos do diagrama", () => {
    assert.equal(GATILHOS.length, 9);
  });
});

describe("pagamentos/estados: a tabela e a do diagrama do §10.2", () => {
  it("todas as arestas do diagrama existem", () => {
    for (const [de, gatilho, para] of DIAGRAMA) {
      const r = transitar(de, gatilho, SINAIS_COMPLETOS);
      assert.equal(r.ok, true, `${de} --${gatilho}--> ${para} nao existe`);
      assert.equal(r.ok && r.estado, para);
    }
  });

  /**
   * **E nenhuma a mais.** Percorre o produto cartesiano dos nove estados pelos
   * nove gatilhos — 81 pares — e exige que os 72 que o diagrama nao tem sejam
   * recusados.
   */
  it("e nenhuma a mais: os outros 72 pares sao recusados", () => {
    const doDiagrama = new Set(DIAGRAMA.map(([de, g]) => `${de}|${g}`));
    let recusados = 0;
    for (const estado of ESTADOS_DA_CONTA) {
      for (const gatilho of GATILHOS) {
        if (doDiagrama.has(`${estado}|${gatilho}`)) continue;
        const r = transitar(estado, gatilho, SINAIS_COMPLETOS);
        assert.equal(r.ok, false, `${estado} --${gatilho}--> existe e nao devia`);
        assert.equal(r.ok === false && r.codigo, TRANSICAO_INEXISTENTE);
        recusados += 1;
      }
    }
    assert.equal(recusados, 81 - DIAGRAMA.length);
    assert.equal(recusados, 72);
  });
});

describe("pagamentos/estados: criterio 8", () => {
  it("nao_iniciado para ativo e rejeitada", () => {
    // Pelos dois gatilhos que poderiam parecer levar la.
    for (const gatilho of ["primeira_cobranca_conciliada", "regularizacao"] as const) {
      const r = transitar("nao_iniciado", gatilho, SINAIS_COMPLETOS);
      assert.equal(r.ok, false);
      assert.equal(r.ok === false && r.codigo, TRANSICAO_INEXISTENTE);
    }
  });

  it("teste_sandbox_ok para ativo exige o sinal da primeira cobranca real", () => {
    const sem = transitar("teste_sandbox_ok", "primeira_cobranca_conciliada");
    assert.equal(sem.ok, false);
    assert.equal(sem.ok === false && sem.codigo, SINAL_EM_FALTA);

    const comFalso = transitar("teste_sandbox_ok", "primeira_cobranca_conciliada", {
      primeiraCobrancaRealConciliada: false,
    });
    assert.equal(comFalso.ok, false);
    assert.equal(comFalso.ok === false && comFalso.codigo, SINAL_EM_FALTA);

    const com = transitar("teste_sandbox_ok", "primeira_cobranca_conciliada", SINAIS_COMPLETOS);
    assert.equal(com.ok, true);
    assert.equal(com.ok && com.estado, "ativo");
  });

  /**
   * O sinal e exigido **so** nessa aresta.
   *
   * Importa porque o contrario — exigi-lo em todas — seria uma barreira que
   * parecia mais apertada e tornava o `suspenso -> ativo` da regularizacao
   * impossivel sem uma cobranca nova, o que travaria uma PME regularizada.
   */
  it("e e exigido so nessa aresta: a regularizacao nao o pede", () => {
    const r = transitar("suspenso", "regularizacao");
    assert.equal(r.ok, true);
    assert.equal(r.ok && r.estado, "ativo");
  });

  it("e pura: o mesmo trio da sempre o mesmo resultado", () => {
    const uma = transitar("ativo", "encerramento");
    const outra = transitar("ativo", "encerramento");
    assert.deepEqual(uma, outra);
    // E nao guarda estado entre chamadas: depois de encerrar, `ativo` continua
    // a aceitar o que aceitava.
    assert.equal(transitar("ativo", "fraude_divergencia_ou_pedido").ok, true);
  });
});

describe("pagamentos/estados: o terminal e a lacuna do diagrama", () => {
  it("revogado e terminal", () => {
    for (const gatilho of GATILHOS) {
      assert.equal(transitar("revogado", gatilho, SINAIS_COMPLETOS).ok, false);
    }
  });

  /**
   * **A lacuna do §10.2, fixada por ensaio em vez de corrigida por invencao.**
   *
   * `suspenso --> revogado` nao existe no diagrama. Lido a letra, uma conta
   * suspensa por fraude tem de passar por `ativo` — por uma regularizacao —
   * antes de poder ser encerrada, que e a ordem contraria a que o caso pede.
   *
   * Este ensaio **nao afirma que o comportamento esta certo**: afirma que o
   * modulo segue o diagrama, e fica vermelho no dia em que alguem acrescentar a
   * aresta sem passar pelo documento. Divida documental 152.
   */
  it("suspenso nao vai a revogado, e isso e a lacuna do diagrama (divida 152)", () => {
    const r = transitar("suspenso", "encerramento");
    assert.equal(r.ok, false);
    assert.equal(r.ok === false && r.codigo, TRANSICAO_INEXISTENTE);
  });
});

describe("pagamentos/estados: quem pode cobrar", () => {
  it("so o ativo cobra", () => {
    for (const estado of ESTADOS_DA_CONTA) {
      assert.equal(podeCobrar(estado), estado === "ativo");
    }
  });

  /**
   * Mas **dois** estados ocupam o indice unico parcial.
   *
   * `payment_accounts_um_ativo` tem `WHERE estado IN ('ativo','teste_sandbox_ok')`
   * (§6.2): uma conta em sandbox ja reserva o par `(tenant_id, provider)`, para
   * que ninguem comece uma segunda integracao do mesmo facilitador enquanto a
   * primeira esta a ser testada. Nao e o mesmo que poder cobrar, e confundir os
   * dois conjuntos era deixar uma conta de sandbox emitir cobrancas reais.
   */
  it("mas dois ocupam o indice unico parcial", () => {
    assert.deepEqual([...ESTADOS_QUE_OCUPAM], ["ativo", "teste_sandbox_ok"]);
  });
});
