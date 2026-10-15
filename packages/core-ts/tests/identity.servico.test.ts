/**
 * O serviço de identidade, sem base de dados (KAM-008).
 *
 * O comportamento contra o PostgreSQL — resolver, fundir, rodar, apagar — está
 * em `tests_bd/identity.bd.test.ts`, que corre no gate 8. Aqui fica o que **não
 * depende da base** ou que a base real não deixa ensaiar: o que o serviço
 * recusa antes de lhe tocar, a política de repetição, as defesas contra um
 * estado que não devia existir, `sujeito_ref`, e as regras do SQL e do registo.
 */

import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { test } from "node:test";

import { EnvKeyProvider, gerarChaveVersionada } from "../src/identity/chaves.ts";
import * as SQL from "../src/identity/consultas.ts";
import {
  CONTADORES_DE_IDENTIDADE,
  type ClienteDeIdentidade,
  ClienteInvalidoError,
  ContactoDesconhecidoError,
  Identidade,
  IdentidadeInconsistenteError,
  KidInvalidoError,
  METRICA_REPETICOES,
  METRICA_RESOLVER,
  PedidoSemIdentificadorError,
  type ResultadoSql,
  RetencaoInvalidaError,
  TENTATIVAS,
} from "../src/identity/contactos.ts";
import { IdentificadorInvalidoError, sujeitoRefDe } from "../src/identity/cripto.ts";
import {
  ContextoEmFaltaError,
  PoolRecusadoError,
  TenantInvalidoError,
} from "../src/tenant_guard/index.ts";
import { ambienteDeChaves } from "./identity.ambiente.ts";

const TENANT = "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4";
const CONTACTO = "2d8b3f40-5e6c-4d7e-af80-9b0c1d2e3f40";
const OUTRO = "3e9c4051-6f7d-4e8f-b091-0c1d2e3f4051";
const AGORA = new Date("2026-10-12T10:00:00Z");

const EPOCA_10 = randomBytes(32).toString("base64");
const ENV = ambienteDeChaves({
  ambiente: "dev",
  pesquisa: [gerarChaveVersionada("k1")],
  kek: [gerarChaveVersionada("kek-1")],
  epocas: { "202609": randomBytes(32).toString("base64"), "202610": EPOCA_10 },
});

async function servico(): Promise<Identidade> {
  return Identidade.arrancar({
    chaves: new EnvKeyProvider({ ambiente: "dev", env: ENV }),
    env: ENV,
    agora: () => AGORA,
  });
}

type Resposta = ResultadoSql | Error | ((parametros: readonly unknown[]) => ResultadoSql);

/** Um cliente com respostas escritas à mão, por texto da instrução. */
class ClienteDeGuiao implements ClienteDeIdentidade {
  readonly vistas: string[] = [];
  readonly guiao = new Map<string, Resposta>();

  async query(sql: string, parametros: readonly unknown[] = []): Promise<ResultadoSql> {
    this.vistas.push(sql);
    const resposta = this.guiao.get(sql);
    if (resposta === undefined) return { rows: [], rowCount: 0 };
    if (resposta instanceof Error) throw resposta;
    return typeof resposta === "function" ? resposta(parametros) : resposta;
  }

  vezes(sql: string): number {
    return this.vistas.filter((vista) => vista === sql).length;
  }
}

function comChave(): ClienteDeGuiao {
  const cliente = new ClienteDeGuiao();
  cliente.guiao.set(SQL.KIDS_VIVOS, { rows: [{ kid: "k1", estado: "actual" }] });
  return cliente;
}

function erroSql(code: string): Error {
  return Object.assign(new Error(`erro de ensaio ${code}`), { code });
}

// ----------------------------------------------- o que se recusa antes da base

test("resolveContact exige um BSUID ou um telefone", async () => {
  const identidade = await servico();
  const cliente = new ClienteDeGuiao();
  for (const pedido of [{}, { bsuid: null }, { bsuid: undefined, telefone: null }]) {
    await assert.rejects(
      identidade.resolveContact(cliente, { tenantId: TENANT, ...pedido }),
      PedidoSemIdentificadorError,
    );
  }
  assert.deepEqual(cliente.vistas, [], "tocou na base antes de validar");
});

test("identificadores com forma inválida são recusados sem tocar na base nem ser repetidos", async () => {
  const identidade = await servico();
  const cliente = new ClienteDeGuiao();
  const casos = [
    { bsuid: "AO. com espaço" },
    { telefone: "999 123 456 789" },
    { bsuid: "AO.123", telefone: "nove-nove-nove" },
  ];
  for (const pedido of casos) {
    await assert.rejects(
      identidade.resolveContact(cliente, { tenantId: TENANT, ...pedido }),
      (erro: unknown) => {
        assert.ok(erro instanceof IdentificadorInvalidoError);
        for (const valor of Object.values(pedido)) {
          if (!/^AO\.123$/.test(valor)) assert.equal(erro.message.includes(valor), false);
        }
        return true;
      },
    );
  }
  assert.deepEqual(cliente.vistas, []);
});

test("sem tenant, ou com um tenant que não é UUID, nada corre", async () => {
  const identidade = await servico();
  const cliente = new ClienteDeGuiao();
  await assert.rejects(
    identidade.resolveContact(cliente, { tenantId: "", bsuid: "AO.123" }),
    ContextoEmFaltaError,
  );
  await assert.rejects(
    identidade.resolveContact(cliente, { tenantId: "loja-da-esquina", bsuid: "AO.123" }),
    TenantInvalidoError,
  );
  await assert.rejects(identidade.eraseContact(cliente, "x", CONTACTO), TenantInvalidoError);
  await assert.rejects(identidade.lerEndpoints(cliente, "x", CONTACTO), TenantInvalidoError);
  await assert.rejects(identidade.rekeyLookup(cliente, "x", "k1"), TenantInvalidoError);
  await assert.rejects(identidade.eraseContact(cliente, TENANT, "x"), IdentificadorInvalidoError);
  await assert.rejects(identidade.lerEndpoints(cliente, TENANT, "x"), IdentificadorInvalidoError);
  assert.deepEqual(cliente.vistas, []);
});

test("guardar o telefone exige telefone, finalidade prevista e um prazo no futuro", async () => {
  const identidade = await servico();
  const cliente = new ClienteDeGuiao();
  const futuro = new Date(AGORA.getTime() + 1000);
  const maus = [
    { bsuid: "AO.123", guardarTelefone: { finalidade: "entrega", expiraAt: futuro } },
    { telefone: "999123456789", guardarTelefone: { finalidade: "marketing", expiraAt: futuro } },
    { telefone: "999123456789", guardarTelefone: { finalidade: "entrega", expiraAt: AGORA } },
    {
      telefone: "999123456789",
      guardarTelefone: { finalidade: "entrega", expiraAt: new Date(AGORA.getTime() - 1) },
    },
    {
      telefone: "999123456789",
      guardarTelefone: { finalidade: "entrega", expiraAt: new Date("não é data") },
    },
    {
      telefone: "999123456789",
      guardarTelefone: { finalidade: "entrega", expiraAt: "2099-01-01" },
    },
  ];
  for (const pedido of maus) {
    await assert.rejects(
      identidade.resolveContact(cliente, { tenantId: TENANT, ...pedido } as never),
      RetencaoInvalidaError,
      JSON.stringify(pedido.guardarTelefone),
    );
  }
  assert.deepEqual(cliente.vistas, []);
});

test("um pool, ou um cliente que não devolve linhas, é recusado", async () => {
  const identidade = await servico();
  const pool = Object.assign(new ClienteDeGuiao(), { totalCount: 4 });
  await assert.rejects(
    identidade.resolveContact(pool, { tenantId: TENANT, bsuid: "AO.123" }),
    PoolRecusadoError,
  );
  await assert.rejects(identidade.iniciarRotacao(pool, "k1"), ClienteInvalidoError);
  await assert.rejects(identidade.concluirRotacao(pool), ClienteInvalidoError);
  assert.deepEqual(pool.vistas, []);

  const semLinhas = new ClienteDeGuiao();
  semLinhas.guiao.set(SQL.KIDS_VIVOS, {} as ResultadoSql);
  await assert.rejects(
    identidade.resolveContact(semLinhas, { tenantId: TENANT, bsuid: "AO.123" }),
    ClienteInvalidoError,
  );
  assert.equal(semLinhas.vistas.at(-1), "ROLLBACK");
});

test("rekeyLookup e iniciarRotacao validam o kid e o lote antes de tocar na base", async () => {
  const identidade = await servico();
  const cliente = new ClienteDeGuiao();
  await assert.rejects(identidade.rekeyLookup(cliente, TENANT, "K1"), KidInvalidoError);
  await assert.rejects(identidade.iniciarRotacao(cliente, "com espaço"), KidInvalidoError);
  for (const lote of [0, -1, 1.5, 1001, Number.NaN]) {
    await assert.rejects(identidade.rekeyLookup(cliente, TENANT, "k1", { lote }), RangeError);
  }
  await assert.rejects(
    identidade.rekeyLookup(cliente, TENANT, "k1", { maximoDeLotes: 0 }),
    RangeError,
  );
  // Uma versão que o cofre não tem: nem chega a abrir transacção.
  await assert.rejects(identidade.rekeyLookup(cliente, TENANT, "k9"), /cofre não tem a versão/);
  assert.deepEqual(cliente.vistas, []);
});

// ------------------------------------------------------ a política de repetição

test("uma corrida (violação de unicidade) repete a transacção, e à segunda passa", async () => {
  const identidade = await servico();
  const cliente = comChave();
  let tentativa = 0;
  cliente.guiao.set(SQL.CRIAR_CONTACTO, () => {
    tentativa += 1;
    if (tentativa === 1) throw erroSql("23505");
    return { rows: [{ contact_id: CONTACTO, criado_at: AGORA }] };
  });
  cliente.guiao.set(SQL.DEFINIR_TELEFONE, { rows: [], rowCount: 1 });
  const antes = CONTADORES_DE_IDENTIDADE.ler();
  const resolvido = await identidade.resolveContact(cliente, {
    tenantId: TENANT,
    telefone: "999123456789",
  });
  assert.deepEqual([resolvido.contactId, resolvido.desfecho], [CONTACTO, "criado"]);
  assert.deepEqual(
    cliente.vistas.filter((v) => ["BEGIN", "ROLLBACK", "COMMIT"].includes(v)),
    ["BEGIN", "ROLLBACK", "BEGIN", "COMMIT"],
  );
  const depois = CONTADORES_DE_IDENTIDADE.ler();
  assert.equal((depois[METRICA_REPETICOES] ?? 0) - (antes[METRICA_REPETICOES] ?? 0), 1);
  assert.equal(
    (depois[`${METRICA_RESOLVER}:criado`] ?? 0) - (antes[`${METRICA_RESOLVER}:criado`] ?? 0),
    1,
  );
});

test("abraço mortal e falha de serialização também se repetem", async () => {
  const identidade = await servico();
  for (const codigo of ["40P01", "40001"]) {
    const cliente = comChave();
    let tentativa = 0;
    cliente.guiao.set(SQL.CRIAR_CONTACTO, () => {
      tentativa += 1;
      if (tentativa === 1) throw erroSql(codigo);
      return { rows: [{ contact_id: CONTACTO, criado_at: AGORA }] };
    });
    cliente.guiao.set(SQL.DEFINIR_TELEFONE, { rows: [], rowCount: 1 });
    await identidade.resolveContact(cliente, { tenantId: TENANT, telefone: "999123456789" });
    assert.equal(cliente.vezes("BEGIN"), 2, codigo);
  }
});

test(`uma corrida que não acaba desiste ao fim de ${TENTATIVAS} tentativas, com o erro da base`, async () => {
  const identidade = await servico();
  const cliente = comChave();
  cliente.guiao.set(SQL.CRIAR_CONTACTO, erroSql("23505"));
  await assert.rejects(
    identidade.resolveContact(cliente, { tenantId: TENANT, telefone: "999123456789" }),
    { code: "23505" },
  );
  assert.equal(cliente.vezes("BEGIN"), TENTATIVAS);
  assert.equal(cliente.vezes("ROLLBACK"), TENTATIVAS);
  assert.equal(cliente.vezes("COMMIT"), 0);
});

test("um erro que não é corrida não se repete", async () => {
  const identidade = await servico();
  const cliente = comChave();
  cliente.guiao.set(SQL.CRIAR_CONTACTO, erroSql("23503"));
  await assert.rejects(
    identidade.resolveContact(cliente, { tenantId: TENANT, telefone: "999123456789" }),
    { code: "23503" },
  );
  assert.equal(cliente.vezes("BEGIN"), 1);
});

test("um contacto apagado entre a pesquisa e a tranca faz repetir; se não estabiliza, é inconsistência", async () => {
  const identidade = await servico();
  const cliente = comChave();
  cliente.guiao.set(SQL.ENDPOINT_POR_BSUID, {
    rows: [{ id: OUTRO, contact_id: CONTACTO, hmac_kid: "k1" }],
  });
  cliente.guiao.set(SQL.TRANCAR_CONTACTOS, {
    rows: [
      {
        contact_id: CONTACTO,
        criado_at: AGORA,
        erased_at: AGORA,
        merged_into: null,
        phone_hmac: null,
        hmac_kid: null,
      },
    ],
  });
  await assert.rejects(
    identidade.resolveContact(cliente, { tenantId: TENANT, bsuid: "AO.123" }),
    IdentidadeInconsistenteError,
  );
  assert.equal(cliente.vezes(SQL.TRANCAR_CONTACTOS), TENTATIVAS);
  assert.equal(cliente.vezes(SQL.CRIAR_ENDPOINT_BSUID), 0, "escreveu num contacto apagado");
});

test("um contacto que desapareceu, ou foi absorvido, entre a pesquisa e a tranca também", async () => {
  const identidade = await servico();
  const absorvido = {
    contact_id: CONTACTO,
    criado_at: AGORA,
    erased_at: null,
    merged_into: OUTRO,
    phone_hmac: null,
    hmac_kid: null,
  };
  for (const tranca of [{ rows: [] }, { rows: [absorvido] }]) {
    const cliente = comChave();
    cliente.guiao.set(SQL.ENDPOINT_POR_BSUID, {
      rows: [{ id: OUTRO, contact_id: CONTACTO, hmac_kid: "k1" }],
    });
    cliente.guiao.set(SQL.TRANCAR_CONTACTOS, tranca);
    await assert.rejects(
      identidade.resolveContact(cliente, { tenantId: TENANT, bsuid: "AO.123" }),
      IdentidadeInconsistenteError,
    );
    assert.equal(cliente.vezes("COMMIT"), 0);
  }
});

test("um contacto que trocou de número entre a pesquisa e a tranca faz repetir", async () => {
  const identidade = await servico();
  const cliente = comChave();
  cliente.guiao.set(SQL.CONTACTO_POR_TELEFONE, {
    rows: [{ contact_id: CONTACTO, hmac_kid: "k1" }],
  });
  cliente.guiao.set(SQL.TRANCAR_CONTACTOS, {
    rows: [
      {
        contact_id: CONTACTO,
        criado_at: AGORA,
        erased_at: null,
        merged_into: null,
        phone_hmac: Buffer.alloc(32, 9), // já não é o HMAC do número pedido
        hmac_kid: "k1",
      },
    ],
  });
  await assert.rejects(
    identidade.resolveContact(cliente, { tenantId: TENANT, telefone: "999123456789" }),
    IdentidadeInconsistenteError,
  );
  assert.equal(cliente.vezes(SQL.TRANCAR_CONTACTOS), TENTATIVAS);
});

// --------------------------------------- estados que não deviam existir

test("o mesmo BSUID, ou o mesmo telefone, a resolver para dois contactos é erro e não escolha", async () => {
  const identidade = await servico();
  const doBsuid = comChave();
  doBsuid.guiao.set(SQL.ENDPOINT_POR_BSUID, {
    rows: [
      { id: OUTRO, contact_id: CONTACTO, hmac_kid: "k1" },
      { id: CONTACTO, contact_id: OUTRO, hmac_kid: "k0" },
    ],
  });
  await assert.rejects(
    identidade.resolveContact(doBsuid, { tenantId: TENANT, bsuid: "AO.123" }),
    /o mesmo BSUID resolve para dois contactos/,
  );
  const doTelefone = comChave();
  doTelefone.guiao.set(SQL.CONTACTO_POR_TELEFONE, {
    rows: [
      { contact_id: CONTACTO, hmac_kid: "k1" },
      { contact_id: OUTRO, hmac_kid: "k0" },
    ],
  });
  await assert.rejects(
    identidade.resolveContact(doTelefone, { tenantId: TENANT, telefone: "999123456789" }),
    /o mesmo telefone resolve para dois contactos/,
  );
  for (const cliente of [doBsuid, doTelefone]) {
    assert.equal(cliente.vezes("BEGIN"), 1, "uma inconsistência não se repete");
    assert.equal(cliente.vistas.at(-1), "ROLLBACK");
  }
});

test("uma cadeia de fusões sem fim é recusada, a ler e a apagar", async () => {
  const identidade = await servico();
  const cliente = new ClienteDeGuiao();
  const elo = { contact_id: CONTACTO, criado_at: AGORA, erased_at: null, merged_into: OUTRO };
  cliente.guiao.set(SQL.CONTACTO, { rows: [elo] });
  cliente.guiao.set(SQL.TRANCAR_CONTACTOS, (parametros) => ({
    rows: [{ ...elo, contact_id: (parametros[1] as string[])[0], phone_hmac: null, hmac_kid: null }],
  }));
  await assert.rejects(identidade.lerEndpoints(cliente, TENANT, CONTACTO), /cadeia de fusões/);
  await assert.rejects(identidade.eraseContact(cliente, TENANT, CONTACTO), /cadeia de fusões/);
  assert.equal(cliente.vezes(SQL.APAGAR_ENDPOINTS), 0);
});

test("ler ou apagar um contacto que não existe é ContactoDesconhecidoError", async () => {
  const identidade = await servico();
  const cliente = new ClienteDeGuiao();
  await assert.rejects(identidade.lerEndpoints(cliente, TENANT, CONTACTO), ContactoDesconhecidoError);
  await assert.rejects(identidade.eraseContact(cliente, TENANT, CONTACTO), ContactoDesconhecidoError);
});

test("uma coluna que não vem com o tipo esperado é recusada, em vez de seguir como texto", async () => {
  const identidade = await servico();
  const casos: [string, ResultadoSql][] = [
    [SQL.KIDS_VIVOS, { rows: [{ kid: 7, estado: "actual" }] }],
    [SQL.ENDPOINT_POR_BSUID, { rows: [{ id: OUTRO, contact_id: null, hmac_kid: "k1" }] }],
  ];
  for (const [instrucao, resposta] of casos) {
    const cliente = comChave();
    cliente.guiao.set(instrucao, resposta);
    await assert.rejects(
      identidade.resolveContact(cliente, { tenantId: TENANT, bsuid: "AO.123" }),
      ClienteInvalidoError,
      instrucao,
    );
  }
  // Datas e octetos: o que o `pg` devolve, e não o que um *driver* mal configurado devolveria.
  const mauEstado = {
    contact_id: CONTACTO,
    criado_at: "2026-10-12",
    erased_at: null,
    merged_into: null,
    phone_hmac: null,
    hmac_kid: null,
  };
  const cliente = comChave();
  cliente.guiao.set(SQL.ENDPOINT_POR_BSUID, {
    rows: [{ id: OUTRO, contact_id: CONTACTO, hmac_kid: "k1" }],
  });
  cliente.guiao.set(SQL.TRANCAR_CONTACTOS, { rows: [mauEstado] });
  await assert.rejects(
    identidade.resolveContact(cliente, { tenantId: TENANT, bsuid: "AO.123" }),
    ClienteInvalidoError,
  );
  cliente.guiao.set(SQL.TRANCAR_CONTACTOS, {
    rows: [{ ...mauEstado, criado_at: AGORA, phone_hmac: "em texto", hmac_kid: "k1" }],
  });
  await assert.rejects(
    identidade.resolveContact(cliente, { tenantId: TENANT, bsuid: "AO.123" }),
    ClienteInvalidoError,
  );
  // Uma escrita sem `rowCount` também: o serviço conta o que apagou.
  const semContagem = new ClienteDeGuiao();
  semContagem.guiao.set(SQL.TRANCAR_CONTACTOS, {
    rows: [{ ...mauEstado, criado_at: AGORA }],
  });
  semContagem.guiao.set(SQL.APAGAR_ENDPOINTS, { rows: [] });
  await assert.rejects(identidade.eraseContact(semContagem, TENANT, CONTACTO), ClienteInvalidoError);
});

// ----------------------------------------------------------------- sujeito_ref

test("critério 7: sujeito_ref é determinístico dentro do mês e diferente entre meses", async () => {
  const identidade = await servico();
  const [a, b] = [
    await identidade.sujeitoRef(CONTACTO, "202610"),
    await identidade.sujeitoRef(CONTACTO, "202610"),
  ];
  assert.equal(a.length, 16);
  assert.ok(a.equals(b), "o mesmo contacto no mesmo mês deu dois pseudónimos");
  const outroMes = await identidade.sujeitoRef(CONTACTO, "202609");
  assert.equal(a.equals(outroMes), false, "o pseudónimo liga-se entre meses");
  const outroContacto = await identidade.sujeitoRef(OUTRO, "202610");
  assert.equal(a.equals(outroContacto), false);
  // E é exactamente trunc16(HMAC(K_época, contact_id)), com a chave do cofre.
  const chave = Buffer.from(EPOCA_10, "base64");
  assert.ok(a.equals(sujeitoRefDe(chave, CONTACTO)));
});

test("sujeito_ref recusa uma época mal escrita, uma época sem chave e o que não é contact_id", async () => {
  const identidade = await servico();
  await assert.rejects(identidade.sujeitoRef(CONTACTO, "2026-10"), /YYYYMM/);
  await assert.rejects(identidade.sujeitoRef(CONTACTO, "202611"), /cofre não tem a versão/);
  await assert.rejects(identidade.sujeitoRef("999123456789", "202610"), IdentificadorInvalidoError);
});

// ---------------------------------------------------------------------- ganchos

test("onContactMerge devolve a função que retira o gancho", async () => {
  const identidade = await servico();
  const retirar = identidade.onContactMerge(async () => {});
  assert.equal(typeof retirar, "function");
  retirar();
  retirar(); // retirar duas vezes não é erro
});

// --------------------------------------------------- as regras do SQL e do registo

const TABELAS_DE_TENANT = ["contacts", "contact_endpoints", "contact_deks"];

test("todo o SQL do módulo usa só parâmetros ligados, e só as quatro tabelas de identidade", () => {
  const instrucoes = Object.entries(SQL.TODAS);
  assert.ok(instrucoes.length >= 30);
  // Nenhuma constante exportada ficou fora da lista que este teste percorre.
  const exportadas = Object.keys(SQL).filter((nome) => nome !== "TODAS").sort();
  assert.deepEqual(Object.keys(SQL.TODAS).sort(), exportadas);

  for (const [nome, sql] of instrucoes) {
    assert.equal(typeof sql, "string", nome);
    // Sem literais de texto para além dos domínios fechados do próprio schema.
    const literais = sql.match(/'[^']*'/g) ?? [];
    for (const literal of literais) {
      assert.ok(
        ["'actual'", "'anterior'", "'retirada'", "'bsuid'", "'telefone'"].includes(literal),
        `${nome}: literal inesperado ${literal}`,
      );
    }
    const tabelas = [...sql.matchAll(/platform\.([a-z_]+)/g)].map((m) => m[1]);
    for (const tabela of tabelas) {
      assert.ok(
        [...TABELAS_DE_TENANT, "hmac_key_versions"].includes(String(tabela)),
        `${nome}: toca em platform.${tabela}`,
      );
    }
    // Os parâmetros são $1…$n, sem saltos.
    const numeros = [...new Set([...sql.matchAll(/\$(\d+)/g)].map((m) => Number(m[1])))].sort(
      (a, b) => a - b,
    );
    assert.deepEqual(numeros, numeros.map((_, i) => i + 1), `${nome}: parâmetros com saltos`);
  }
});

test("toda a instrução sobre uma tabela de tenant filtra (ou escreve) o tenant_id em $1", () => {
  for (const [nome, sql] of Object.entries(SQL.TODAS)) {
    const tocaEmTenant = TABELAS_DE_TENANT.some((tabela) => sql.includes(`platform.${tabela} `));
    if (!tocaEmTenant) continue;
    if (sql.startsWith("INSERT")) {
      assert.match(sql, /\(([a-z_]+, )?tenant_id[,)]/, `${nome}: INSERT sem tenant_id`);
      continue;
    }
    // Uma vez por cada tabela de tenant referida (as subconsultas também).
    const referencias = [...sql.matchAll(/platform\.(contacts|contact_endpoints|contact_deks) /g)].length;
    const filtros = [...sql.matchAll(/tenant_id = (\$1|e\.tenant_id)/g)].length;
    assert.ok(filtros >= referencias, `${nome}: ${referencias} tabela(s), ${filtros} filtro(s) de tenant`);
    assert.match(sql, /tenant_id = \$1/, `${nome}: sem tenant_id = $1`);
  }
});

test("o módulo não regista nada: nem console, nem saída do processo, nem um logger", () => {
  // O «linter de logging» do ticket, à medida deste módulo: o *logger* com
  // lista de campos permitidos é do KAM-068, e até lá a regra aqui é zero.
  const pasta = new URL("../src/identity/", import.meta.url);
  const ficheiros = readdirSync(pasta).filter((nome) => nome.endsWith(".ts"));
  assert.deepEqual(ficheiros.sort(), ["chaves.ts", "consultas.ts", "contactos.ts", "cripto.ts", "index.ts"]);
  for (const ficheiro of ficheiros) {
    const fonte = readFileSync(new URL(ficheiro, pasta), "utf8");
    const codigo = fonte
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .split("\n")
      .filter((linha) => !linha.trim().startsWith("//"))
      .join("\n");
    for (const proibido of [
      /\bconsole\s*\./,
      /process\.(stdout|stderr)/,
      /\blogger\b/i,
      /\bdebuglog\b/,
      /from "node:util"/,
    ]) {
      assert.equal(proibido.test(codigo), false, `${ficheiro}: ${proibido}`);
    }
  }
});

test("os contadores do módulo só têm números, e os nomes não levam tenant nem contacto", async () => {
  const identidade = await servico();
  const cliente = comChave();
  cliente.guiao.set(SQL.CRIAR_CONTACTO, { rows: [{ contact_id: CONTACTO, criado_at: AGORA }] });
  cliente.guiao.set(SQL.DEFINIR_TELEFONE, { rows: [], rowCount: 1 });
  await identidade.resolveContact(cliente, { tenantId: TENANT, telefone: "999123456789" });
  for (const [nome, valor] of Object.entries(CONTADORES_DE_IDENTIDADE.ler())) {
    assert.equal(typeof valor, "number");
    assert.match(nome, /^identity_[a-z_]+(:[a-z]+)?$/);
  }
});
