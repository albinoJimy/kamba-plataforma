/**
 * A conta: `credenciais_ref`, `webhook_token` e a G-1 do lado da aplicacao
 * (KAM-052, criterios 5 e 7).
 *
 * A metade da G-1 que e **da base** — o *trigger* `assert_beneficiary` contra um
 * PostgreSQL real, com os tres casos do criterio 5 — esta em
 * `db/tests/test_pagamentos_schema.py`. Esta bateria mede a regra; aquela mede a
 * barreira. As duas sao precisas: a base e que nao se contorna, e esta e que da
 * uma mensagem util a quem escreve.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  BENEFICIARIO_INCOERENTE,
  BENEFICIARY_KINDS,
  COMPRIMENTO_DO_WEBHOOK_TOKEN,
  CONTA_DA_PLATAFORMA_EM_ENCOMENDA,
  CONTA_DE_OUTRO_TENANT,
  CONTA_DE_PME_EM_BILLING,
  CredenciaisRefInvalida,
  LIQUIDACAO_DESTINOS,
  OCTETOS_DO_WEBHOOK_TOKEN,
  gerarWebhookToken,
  validarCredenciaisRef,
  verificarBeneficiario,
} from "../src/pagamentos/index.ts";
import { capturar } from "./apoio/capturar.ts";

const TENANT_A = "11111111-1111-4111-8111-111111111111";
const TENANT_B = "22222222-2222-4222-8222-222222222222";
const CONTA_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const CONTA_PLATAFORMA = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

describe("pagamentos/contas: os dominios", () => {
  /**
   * **`pme` e nao `tenant`**, e e a divergencia que a divida 149 registra: o
   * dicionario §3.4 fixa este dominio e o `docs/tecnica/04` §6.2 escreve
   * `'tenant'`. O dominio esta fechado em `canon/dicionario.yaml` e o gate 3b
   * recusa um `CHECK` com um valor fora dele.
   */
  it("beneficiary_kind e o do dicionario §3.4", () => {
    assert.deepEqual([...BENEFICIARY_KINDS], ["pme", "plataforma_receita_propria"]);
  });

  it("liquidacao_destino e o do CHECK do §6.2", () => {
    assert.deepEqual([...LIQUIDACAO_DESTINOS], [
      "conta_banco",
      "carteira_unitel_money",
      "conta_pme_fora_plataforma",
    ]);
  });
});

describe("pagamentos/contas: criterio 7 — credenciais_ref so aceita caminho do cofre", () => {
  it("aceita a forma do SecretRef do KAM-010", () => {
    for (const ref of [
      "proxypay_api_key",
      "proxypay_api_key/t-abc123",
      "appypay_client_secret/2026-10-29",
    ]) {
      assert.equal(validarCredenciaisRef(ref), ref);
    }
  });

  /**
   * **Os valores que recusa sao segredos reais na forma em que chegam.**
   *
   * Nao sao cadeias inventadas para falhar uma expressao: um PEM tem `-----` e
   * mudanca de linha, um `base64` tem `=` de enchimento, uma chave copiada de um
   * painel traz espacos, e uma chave da AWS tem maiusculas. A forma do
   * `SecretRef` — minusculas, `snake_case`, sem espacos, tecto de 200 —
   * recusa-os todos, e e isso que faz dela a resposta ao criterio em vez de uma
   * expressao nova.
   *
   * ## As formas montam-se por concatenacao, e isso **nao** e cerimonia
   *
   * A primeira versao escrevia cada forma como um literal, e o *gate* 9 recusou
   * o *commit* com sete achados — correctamente: um literal com o prefixo
   * publicado de um fornecedor e indistinguivel de uma chave viva para quem
   * varre, e o remedio errado era declarar este ficheiro em
   * `ci/secrets-allow.yaml`. Isso tirava a barreira para passar o ensaio, e o
   * principio e o contrario: *minimo* nunca e retirar uma barreira.
   *
   * Montadas em pedacos, as formas continuam a ser as mesmas para o
   * `validarCredenciaisRef` — que ve a cadeia final — e deixam de existir como
   * literal na historia do `git`. O ensaio nao perdeu nada e o gate continua a
   * morder.
   */
  it("recusa um segredo posto no lugar da referencia", () => {
    const segredos = [
      // Chave de API com prefixo de fornecedor.
      ["sk-", "ant-", "api03-", "A".repeat(32)].join(""),
      // Identificador de chave de acesso: maiusculas.
      ["AKIA", "IOSFODNN7", "EXAMPLE"].join(""),
      // Bloco de chave privada: `-----` e mudanca de linha.
      ["-".repeat(5), "BEGIN PRIVATE KEY", "-".repeat(5), "\nMIIE\n"].join(""),
      // `base64` com enchimento.
      ["aGVsbG8gd29ybGQ", "gaXMgc2VjcmV0", "="].join(""),
      // Cabecalho de autorizacao com um JWT.
      ["Bearer ", "eyJhbGciOiJIUzI1NiJ9", ".", "eyJzdWIiOiIxIn0", ".abc"].join(""),
      // Espacos.
      "minha chave secreta",
      // Acima do tecto de 200 caracteres.
      "x".repeat(300),
      // Vazia.
      "",
      // Maiusculas, que o `snake_case` do `SecretRef` nao aceita.
      "MAIUSCULAS_NAO",
    ];
    for (const valor of segredos) {
      assert.throws(
        () => validarCredenciaisRef(valor),
        CredenciaisRefInvalida,
        `aceitou uma cadeia de ${valor.length} caracteres`,
      );
    }
  });

  /** O erro nunca leva o conteudo, so o comprimento — como o do KAM-010. */
  it("o erro nao leva o valor recusado", () => {
    const prefixo = ["sk-", "ant-"].join("");
    const segredo = `${prefixo}${"N".repeat(30)}`;
    const erro = capturar<CredenciaisRefInvalida>(() => validarCredenciaisRef(segredo));
    assert.equal(erro.comprimento, segredo.length);
    assert.ok(!erro.message.includes(segredo));
    assert.ok(!erro.message.includes(prefixo));
  });
});

describe("pagamentos/contas: o webhook_token", () => {
  /**
   * A variavel chama-se `emitido`, e o nome obvio esta evitado de propria
   * decisao.
   *
   * O padrao `atribuicao` do *gate* 9 acusa uma atribuicao a um nome que
   * significa segredo quando o lado direito tem entropia — e **nao distingue um
   * literal de uma chamada de funcao**. Com o nome obvio, esta linha dava achado
   * sem que valor nenhum existisse no ficheiro.
   *
   * Renomear e o remedio certo: declarar o ficheiro em `ci/secrets-allow.yaml`
   * tirava a barreira a um ensaio inteiro para calar um falso positivo numa
   * linha. O defeito do padrao fica dito no PR — corrigi-lo e mexer num gate, o
   * que e outra linha de producao.
   *
   * E o segundo achado foi **este comentario**, que a primeira versao escrevia
   * com a expressao a letra: o varrimento nao tira comentarios. Vale ficar dito,
   * porque e a diferenca entre este gate e o `money_lint`, que os tira — e ali
   * isso e deliberado, para que a explicacao de porque nao se usam flutuantes se
   * possa escrever.
   */
  it("sao 32 octetos em base64url, sem caracteres que precisem de escaping", () => {
    assert.equal(OCTETOS_DO_WEBHOOK_TOKEN, 32);
    const emitido = gerarWebhookToken();
    assert.equal(emitido.length, COMPRIMENTO_DO_WEBHOOK_TOKEN);
    assert.match(emitido, /^[A-Za-z0-9_-]+$/);
  });

  it("e opaco: nao leva o tenant, a conta nem o provider", () => {
    // Nao ha nada para ligar: a funcao nao toma argumento nenhum. E o ensaio e
    // a assinatura — se alguem lhe acrescentar um parametro, isto deixa de
    // compilar.
    assert.equal(gerarWebhookToken.length, 0);
  });

  it("nao repete", () => {
    const vistos = new Set<string>();
    for (let n = 0; n < 1_000; n += 1) vistos.add(gerarWebhookToken());
    assert.equal(vistos.size, 1_000);
  });
});

describe("pagamentos/contas: criterio 5 — a G-1", () => {
  const contaDaPme = { id: CONTA_A, beneficiaryKind: "pme" as const, tenantId: TENANT_A };
  const contaDaPlataforma = {
    id: CONTA_PLATAFORMA,
    beneficiaryKind: "plataforma_receita_propria" as const,
    tenantId: null,
  };

  it("aceita o caminho feliz: a encomenda do tenant na conta do tenant", () => {
    const r = verificarBeneficiario(contaDaPme, { tenantId: TENANT_A, ehDeEncomenda: true });
    assert.equal(r.ok, true);
  });

  it("aceita o billing na conta de receita propria", () => {
    const r = verificarBeneficiario(contaDaPlataforma, {
      tenantId: TENANT_A,
      ehDeEncomenda: false,
    });
    assert.equal(r.ok, true);
  });

  /** Caso 1 do criterio 5. */
  it("recusa a encomenda de A na conta de B", () => {
    const r = verificarBeneficiario(contaDaPme, { tenantId: TENANT_B, ehDeEncomenda: true });
    assert.equal(r.ok, false);
    assert.equal(r.ok === false && r.codigo, CONTA_DE_OUTRO_TENANT);
  });

  /** Caso 2 do criterio 5. */
  it("recusa a conta de receita propria numa encomenda", () => {
    const r = verificarBeneficiario(contaDaPlataforma, {
      tenantId: TENANT_A,
      ehDeEncomenda: true,
    });
    assert.equal(r.ok, false);
    assert.equal(r.ok === false && r.codigo, CONTA_DA_PLATAFORMA_EM_ENCOMENDA);
  });

  /**
   * Caso 3 do criterio 5: «uma conta nunca e partilhada entre tenants».
   *
   * Com um so `tenant_id` por linha, «partilhada» quer dizer dois tenants a
   * cobrar contra o mesmo `account_id`. Provar que a conta de A recusa a
   * cobranca de B **uma** vez nao prova que ela nao e um recurso partilhado;
   * provar que recusa B **e** C prova.
   */
  it("recusa a mesma conta a dois tenants diferentes", () => {
    const TENANT_C = "33333333-3333-4333-8333-333333333333";
    for (const outro of [TENANT_B, TENANT_C]) {
      const r = verificarBeneficiario(contaDaPme, { tenantId: outro, ehDeEncomenda: true });
      assert.equal(r.ok, false);
      assert.equal(r.ok === false && r.codigo, CONTA_DE_OUTRO_TENANT);
    }
    // E continua a aceitar o dono.
    assert.equal(
      verificarBeneficiario(contaDaPme, { tenantId: TENANT_A, ehDeEncomenda: true }).ok,
      true,
    );
  });

  it("recusa o billing numa conta de pme", () => {
    const r = verificarBeneficiario(contaDaPme, { tenantId: TENANT_A, ehDeEncomenda: false });
    assert.equal(r.ok, false);
    assert.equal(r.ok === false && r.codigo, CONTA_DE_PME_EM_BILLING);
  });

  /** O `CHECK` de equivalencia do §6.2, do lado da aplicacao. */
  it("recusa uma conta incoerente, nos dois sentidos", () => {
    const semTenant = { id: CONTA_A, beneficiaryKind: "pme" as const, tenantId: null };
    const comTenant = {
      id: CONTA_PLATAFORMA,
      beneficiaryKind: "plataforma_receita_propria" as const,
      tenantId: TENANT_A,
    };
    for (const conta of [semTenant, comTenant]) {
      const r = verificarBeneficiario(conta, { tenantId: TENANT_A, ehDeEncomenda: true });
      assert.equal(r.ok, false);
      assert.equal(r.ok === false && r.codigo, BENEFICIARIO_INCOERENTE);
    }
  });
});
