/**
 * Identidade de contacto contra um PostgreSQL real (KAM-008).
 *
 * Os critérios de aceitação do ticket, um a um, com o módulo verdadeiro, o
 * papel `kamba_identity` verdadeiro e a RLS ligada. Um ficheiro só, e os testes
 * por ordem: a tabela de versões de chave é **global**, e o ensaio de rotação
 * muda a versão actual para todos — em paralelo, pisavam-se.
 *
 * Quem corre isto é `db/tests_identidade/` (`python db/gate_bd.py --suite
 * tests_identidade`), que depois lê o que fica em `KAMBA_IDENTIDADE_SAIDA`: a
 * lista de canários, para os procurar no *dump* e no registo do servidor.
 */

import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";

import type pg from "pg";

import {
  CONSULTAS,
  CifraInvalidaError,
  ContactoApagadoError,
  ContactoDesconhecidoError,
  DekDestruidaError,
  type EventoContactMerged,
  Identidade,
  KidNaoActualError,
  KidReutilizadoError,
  RotacaoEmCursoError,
  SemChaveActualError,
  hmacDePesquisa,
} from "../src/identity/index.ts";
import {
  ChavesDeTeste,
  ClienteEspiao,
  apagarTenant,
  bsuidDeEnsaio,
  contar,
  criarTenant,
  daquiAUmAno,
  emParalelo,
  fotografia,
  ligar,
  telefoneDeEnsaio,
} from "./apoio.ts";

/** Quantos contactos com canário (critério 2) e quantas chamadas repetidas (critério 3). */
const CANARIOS = 1000;
const CHAMADAS = 10_000;
const LIGACOES = 8;

const chaves = new ChavesDeTeste("k1", ["202609", "202610"]);
let identidade: Identidade;
let admin: pg.Client;
let ligacoes: pg.Client[] = [];
let id: pg.Client;
const tenantsDeEnsaio: string[] = [];

async function novoTenant(rotulo: string): Promise<string> {
  const tenant = await criarTenant(admin, rotulo);
  tenantsDeEnsaio.push(tenant);
  return tenant;
}

async function linhas(sql: string, parametros: unknown[] = []): Promise<Record<string, any>[]> {
  return (await admin.query(sql, parametros)).rows;
}

async function contacto(tenant: string, contactId: string): Promise<Record<string, any>> {
  const [linha] = await linhas(
    "SELECT * FROM platform.contacts WHERE tenant_id = $1 AND contact_id = $2",
    [tenant, contactId],
  );
  assert.ok(linha, "o contacto não existe");
  return linha;
}

async function endpoints(tenant: string, contactId: string): Promise<Record<string, any>[]> {
  return linhas(
    "SELECT * FROM platform.contact_endpoints WHERE tenant_id = $1 AND contact_id = $2 " +
      "ORDER BY tipo, recolhido_at, id",
    [tenant, contactId],
  );
}

/**
 * Um terceiro contacto no mesmo tenant, com BSUID e telefone guardado, e a
 * verificação de que continua exactamente como estava.
 */
async function criarEspectador(tenant: string): Promise<{ intacto: () => Promise<void> }> {
  const bsuid = bsuidDeEnsaio();
  const telefone = telefoneDeEnsaio();
  const expiraAt = daquiAUmAno();
  const { contactId } = await identidade.resolveContact(id, {
    tenantId: tenant,
    bsuid,
    telefone,
    guardarTelefone: { finalidade: "contacto_pedido", expiraAt },
  });
  const antes = JSON.stringify([await contacto(tenant, contactId), await endpoints(tenant, contactId)]);
  return {
    intacto: async () => {
      assert.equal(
        JSON.stringify([await contacto(tenant, contactId), await endpoints(tenant, contactId)]),
        antes,
        "um contacto que não entrou na operação foi alterado",
      );
      assert.deepEqual(await identidade.lerEndpoints(id, tenant, contactId), {
        contactId,
        bsuids: [bsuid],
        telefones: [{ finalidade: "contacto_pedido", telefone, expiraAt }],
      });
      const deks = await linhas(
        "SELECT wrapped_dek FROM platform.contact_deks WHERE tenant_id = $1 AND contact_id = $2",
        [tenant, contactId],
      );
      assert.equal(deks.length, 1);
      assert.notEqual(deks[0]?.wrapped_dek, null, "a DEK do espectador foi destruída");
    },
  };
}

before(async () => {
  admin = await ligar("admin");
  ligacoes = await Promise.all(Array.from({ length: LIGACOES }, () => ligar("identity")));
  id = ligacoes[0] as pg.Client;
  identidade = await chaves.identidade();
});

after(async () => {
  for (const tenant of tenantsDeEnsaio) await apagarTenant(admin, tenant);
  await Promise.all(ligacoes.map((ligacao) => ligacao.end()));
  await admin.end();
});

describe("antes de haver chave", () => {
  test("sem versão actual registada, resolver falha em vez de inventar uma", async () => {
    const [{ n }] = (await linhas(
      "SELECT count(*)::int AS n FROM platform.hmac_key_versions",
    )) as [{ n: number }];
    assert.equal(n, 0, "a suite espera uma base acabada de migrar");
    const tenant = await novoTenant("sem-chave");
    await assert.rejects(
      identidade.resolveContact(id, { tenantId: tenant, bsuid: bsuidDeEnsaio() }),
      SemChaveActualError,
    );
    assert.deepEqual(await contar(admin, tenant), { contactos: 0, endpoints: 0, deks: 0 });
  });

  test("iniciarRotacao regista a primeira versão, e é idempotente", async () => {
    assert.deepEqual(await identidade.iniciarRotacao(id, "k1"), {
      kid: "k1",
      alterado: true,
      anterior: null,
    });
    assert.deepEqual(await identidade.iniciarRotacao(id, "k1"), {
      kid: "k1",
      alterado: false,
      anterior: null,
    });
    assert.deepEqual(await linhas("SELECT kid, estado FROM platform.hmac_key_versions"), [
      { kid: "k1", estado: "actual" },
    ]);
  });

  test("uma versão que o cofre não tem não se regista", async () => {
    await assert.rejects(identidade.iniciarRotacao(id, "k-fantasma"), /cofre não tem a versão/);
    assert.equal((await linhas("SELECT 1 FROM platform.hmac_key_versions")).length, 1);
  });
});

describe("critério 1 — só cifrado, e só em contact_endpoints", () => {
  test("contacts guarda HMAC e versão; BSUID e telefone ficam cifrados com a DEK do contacto", async () => {
    const tenant = await novoTenant("ac1");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const expiraAt = daquiAUmAno();

    const resolvido = await identidade.resolveContact(id, {
      tenantId: tenant,
      bsuid,
      telefone: `+${telefone}`,
      guardarTelefone: { finalidade: "entrega", expiraAt },
    });
    assert.equal(resolvido.desfecho, "criado");
    assert.equal(resolvido.evento, null);

    const chave = await chaves.provedor().getLookupKey("k1");
    const c = await contacto(tenant, resolvido.contactId);
    assert.equal(c.hmac_kid, "k1");
    assert.equal(c.erased_at, null);
    assert.ok(c.phone_hmac.equals(hmacDePesquisa(chave, tenant, "telefone", telefone)));

    const [doBsuid, doTelefone, ...resto] = await endpoints(tenant, resolvido.contactId);
    assert.equal(resto.length, 0);
    assert.ok(doBsuid && doTelefone);
    assert.equal(doBsuid.tipo, "bsuid");
    assert.equal(doBsuid.hmac_kid, "k1");
    assert.ok(doBsuid.bsuid_hmac.equals(hmacDePesquisa(chave, tenant, "bsuid", bsuid)));
    assert.equal(doBsuid.phone_enc, null);
    assert.equal(doTelefone.tipo, "telefone");
    assert.equal(doTelefone.finalidade, "entrega");
    assert.equal(doTelefone.expira_at.getTime(), expiraAt.getTime());
    assert.equal(doTelefone.bsuid_hmac, null);

    // AES-256-GCM: versão, IV de 12 octetos, etiqueta de 16, e o texto cifrado.
    for (const [cifra, claro] of [
      [doBsuid.bsuid_enc as Buffer, bsuid],
      [doTelefone.phone_enc as Buffer, telefone],
    ] as const) {
      assert.equal(cifra[0], 1);
      assert.equal(cifra.length, 1 + 12 + 16 + claro.length);
      assert.equal(cifra.includes(Buffer.from(claro)), false, "o valor está em claro na cifra");
    }

    // Uma DEK por contacto, embrulhada: 32 octetos de chave nunca estão na base.
    const deks = await linhas("SELECT * FROM platform.contact_deks WHERE tenant_id = $1", [tenant]);
    assert.equal(deks.length, 1);
    assert.equal(deks[0]?.contact_id, resolvido.contactId);
    assert.equal(deks[0]?.kek_id, "kek-1");
    assert.equal(deks[0]?.wrapped_dek.length, 1 + 12 + 16 + 32);
    assert.equal(doBsuid.dek_id, deks[0]?.dek_id);
    assert.equal(doTelefone.dek_id, deks[0]?.dek_id);

    // E o caminho de volta: só o módulo, com a DEK, lê o que lá está.
    assert.deepEqual(await identidade.lerEndpoints(id, tenant, resolvido.contactId), {
      contactId: resolvido.contactId,
      bsuids: [bsuid],
      telefones: [{ finalidade: "entrega", telefone, expiraAt }],
    });
  });

  test("sem pedir para guardar, do telefone fica só o HMAC", async () => {
    const tenant = await novoTenant("ac1-hmac");
    const resolvido = await identidade.resolveContact(id, {
      tenantId: tenant,
      bsuid: bsuidDeEnsaio(),
      telefone: telefoneDeEnsaio(),
    });
    const lidos = await endpoints(tenant, resolvido.contactId);
    assert.deepEqual(
      lidos.map((linha) => linha.tipo),
      ["bsuid"],
    );
    assert.equal((await contacto(tenant, resolvido.contactId)).phone_hmac.length, 32);
    assert.deepEqual(
      (await identidade.lerEndpoints(id, tenant, resolvido.contactId)).telefones,
      [],
    );
  });

  test("guardar outra vez renova a linha, não acumula cópias do número", async () => {
    const tenant = await novoTenant("ac1-renova");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const primeiro = new Date(Date.now() + 60_000);
    const segundo = daquiAUmAno();
    for (const expiraAt of [primeiro, segundo]) {
      await identidade.resolveContact(id, {
        tenantId: tenant,
        bsuid,
        telefone,
        guardarTelefone: { finalidade: "entrega", expiraAt },
      });
    }
    const { contactId } = await identidade.resolveContact(id, {
      tenantId: tenant,
      bsuid,
      telefone,
      guardarTelefone: { finalidade: "contacto_pedido", expiraAt: segundo },
    });
    const lidos = await identidade.lerEndpoints(id, tenant, contactId);
    assert.deepEqual(
      lidos.telefones.map((t) => [t.finalidade, t.telefone, t.expiraAt.getTime()]),
      [
        ["entrega", telefone, segundo.getTime()],
        ["contacto_pedido", telefone, segundo.getTime()],
      ],
    );
    assert.deepEqual(await contar(admin, tenant), { contactos: 1, endpoints: 3, deks: 1 });
  });

  test("uma cifra alterada, ou posta noutra linha, não abre", async () => {
    const tenant = await novoTenant("ac1-gcm");
    const um = await identidade.resolveContact(id, { tenantId: tenant, bsuid: bsuidDeEnsaio() });
    const outro = await identidade.resolveContact(id, { tenantId: tenant, bsuid: bsuidDeEnsaio() });
    const [deUm] = await endpoints(tenant, um.contactId);
    const [deOutro] = await endpoints(tenant, outro.contactId);
    assert.ok(deUm && deOutro);
    assert.notEqual(deUm.dek_id, deOutro.dek_id, "dois contactos partilham a DEK");

    // Um octeto trocado no texto cifrado: a etiqueta do GCM recusa.
    const alterada = Buffer.from(deUm.bsuid_enc);
    alterada[alterada.length - 1] = (alterada[alterada.length - 1] ?? 0) ^ 0x01;
    await admin.query("UPDATE platform.contact_endpoints SET bsuid_enc = $1 WHERE id = $2", [
      alterada,
      deUm.id,
    ]);
    await assert.rejects(identidade.lerEndpoints(id, tenant, um.contactId), CifraInvalidaError);

    // A cifra de um contacto, copiada para a linha de outro: outra DEK, não abre.
    await admin.query("UPDATE platform.contact_endpoints SET bsuid_enc = $1 WHERE id = $2", [
      deUm.bsuid_enc,
      deOutro.id,
    ]);
    await assert.rejects(identidade.lerEndpoints(id, tenant, outro.contactId), CifraInvalidaError);

    // O embrulho da DEK de um contacto, posto na DEK de outro: o contexto recusa.
    const [dekDeUm] = await linhas("SELECT wrapped_dek FROM platform.contact_deks WHERE dek_id = $1", [
      deUm.dek_id,
    ]);
    await admin.query("UPDATE platform.contact_deks SET wrapped_dek = $1 WHERE dek_id = $2", [
      dekDeUm?.wrapped_dek,
      deOutro.dek_id,
    ]);
    await assert.rejects(
      identidade.lerEndpoints(id, tenant, outro.contactId),
      /não se consegue desembrulhar/,
    );
  });
});

describe("critério 4 — ordem de resolução, completar e fundir", () => {
  test("o BSUID resolve para o mesmo contacto, com ou sem telefone no pedido", async () => {
    const tenant = await novoTenant("ordem");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const criado = await identidade.resolveContact(id, { tenantId: tenant, bsuid });
    assert.equal(criado.desfecho, "criado");
    const comTelefone = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });
    assert.deepEqual(
      [comTelefone.contactId, comTelefone.desfecho, comTelefone.evento],
      [criado.contactId, "existente", null],
    );
    // E agora o telefone, sozinho, chega ao mesmo contacto.
    const soTelefone = await identidade.resolveContact(id, { tenantId: tenant, telefone });
    assert.deepEqual([soTelefone.contactId, soTelefone.desfecho], [criado.contactId, "existente"]);
    assert.deepEqual(await contar(admin, tenant), { contactos: 1, endpoints: 1, deks: 1 });
  });

  test("um contacto só-telefone que recebe BSUID é completado, não duplicado", async () => {
    const tenant = await novoTenant("completar");
    const telefone = telefoneDeEnsaio();
    const bsuid = bsuidDeEnsaio();
    const soTelefone = await identidade.resolveContact(id, { tenantId: tenant, telefone });
    assert.equal(soTelefone.desfecho, "criado");
    assert.deepEqual(await contar(admin, tenant), { contactos: 1, endpoints: 0, deks: 0 });

    const completado = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });
    assert.deepEqual(
      [completado.contactId, completado.desfecho, completado.evento],
      [soTelefone.contactId, "completado", null],
    );
    // A partir daqui o BSUID, sozinho, chega lá.
    const peloBsuid = await identidade.resolveContact(id, { tenantId: tenant, bsuid });
    assert.deepEqual([peloBsuid.contactId, peloBsuid.desfecho], [soTelefone.contactId, "existente"]);
    assert.deepEqual(await contar(admin, tenant), { contactos: 1, endpoints: 1, deks: 1 });
  });

  test("dois contactos que se revelam o mesmo fundem-se no mais antigo e devolvem contact.merged", async () => {
    const tenant = await novoTenant("fundir");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    // Um espectador no mesmo tenant: a fusão de dois não toca num terceiro.
    const espectador = await criarEspectador(tenant);
    // Primeiro o BSUID (mais antigo), depois o telefone sozinho: dois contactos.
    const a = await identidade.resolveContact(id, { tenantId: tenant, bsuid });
    const p = await identidade.resolveContact(id, {
      tenantId: tenant,
      telefone,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });
    assert.notEqual(a.contactId, p.contactId);
    await admin.query(
      "UPDATE platform.contacts SET criado_at = criado_at - interval '1 hour' WHERE contact_id = $1",
      [a.contactId],
    );

    const fundido = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });

    assert.equal(fundido.desfecho, "fundido");
    assert.equal(fundido.contactId, a.contactId, "não ficou o mais antigo");
    const evento = fundido.evento as EventoContactMerged;
    assert.deepEqual(
      { ...evento, ocorrido_em: "" },
      {
        tipo: "contact.merged",
        tenant_id: tenant,
        ocorrido_em: "",
        payload: { contact_id: a.contactId, merged_contact_id: p.contactId },
      },
    );
    // O evento só tem identificadores opacos: nem telefone, nem BSUID.
    const serializado = JSON.stringify(evento);
    assert.equal(serializado.includes(telefone), false);
    assert.equal(serializado.includes(bsuid), false);

    // O absorvido fica como lápide, sem telefone; tudo o resto passou para quem fica.
    const lapide = await contacto(tenant, p.contactId);
    assert.equal(lapide.merged_into, a.contactId);
    assert.equal(lapide.phone_hmac, null);
    assert.equal(lapide.merged_at.toISOString(), evento.ocorrido_em);
    assert.equal((await endpoints(tenant, p.contactId)).length, 0);
    assert.deepEqual(await identidade.lerEndpoints(id, tenant, a.contactId), {
      contactId: a.contactId,
      bsuids: [bsuid],
      telefones: [
        { finalidade: "entrega", telefone, expiraAt: (await endpoints(tenant, a.contactId))[1]?.expira_at },
      ],
    });
    // Quem ainda tiver o `contact_id` antigo chega ao novo.
    assert.equal((await identidade.lerEndpoints(id, tenant, p.contactId)).contactId, a.contactId);

    // Repetir não volta a fundir nem a devolver o evento (KAM-014: «1 vez em 10»).
    for (let i = 0; i < 10; i += 1) {
      const outraVez = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });
      assert.deepEqual(
        [outraVez.contactId, outraVez.desfecho, outraVez.evento],
        [a.contactId, "existente", null],
      );
    }
    for (const pedido of [{ bsuid }, { telefone }]) {
      const r = await identidade.resolveContact(id, { tenantId: tenant, ...pedido });
      assert.equal(r.contactId, a.contactId);
    }
    assert.equal((await contar(admin, tenant)).contactos, 3);
    await espectador.intacto();
  });

  test("ao fundir, quem tem o BSUID larga o número antigo e a cifra que tinha dele", async () => {
    const tenant = await novoTenant("fundir-com-numero-antigo");
    const bsuid = bsuidDeEnsaio();
    const [antigo, novo] = [telefoneDeEnsaio(), telefoneDeEnsaio()];
    const guardar = { finalidade: "entrega" as const, expiraAt: daquiAUmAno() };
    const a = await identidade.resolveContact(id, {
      tenantId: tenant, bsuid, telefone: antigo, guardarTelefone: guardar,
    });
    const p = await identidade.resolveContact(id, {
      tenantId: tenant, telefone: novo, guardarTelefone: guardar,
    });

    const fundido = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone: novo });

    assert.equal(fundido.desfecho, "fundido");
    assert.deepEqual([fundido.contactId, fundido.evento?.payload.merged_contact_id], [a.contactId, p.contactId]);
    // Fica com o número novo, e só com a cifra do novo.
    const chave = await chaves.provedor().getLookupKey("k1");
    assert.ok(
      (await contacto(tenant, a.contactId)).phone_hmac.equals(
        hmacDePesquisa(chave, tenant, "telefone", novo),
      ),
    );
    assert.deepEqual(
      (await identidade.lerEndpoints(id, tenant, a.contactId)).telefones.map((t) => t.telefone),
      [novo],
    );
    // O número antigo já não é dele: resolve para alguém novo.
    const peloAntigo = await identidade.resolveContact(id, { tenantId: tenant, telefone: antigo });
    assert.equal(peloAntigo.desfecho, "criado");
    assert.notEqual(peloAntigo.contactId, a.contactId);
  });

  test("fica o mais antigo mesmo quando o mais antigo é o do telefone", async () => {
    const tenant = await novoTenant("fundir-telefone-antigo");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const p = await identidade.resolveContact(id, { tenantId: tenant, telefone });
    const a = await identidade.resolveContact(id, { tenantId: tenant, bsuid });
    await admin.query(
      "UPDATE platform.contacts SET criado_at = criado_at - interval '1 hour' WHERE contact_id = $1",
      [p.contactId],
    );
    const fundido = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });
    assert.equal(fundido.contactId, p.contactId);
    assert.deepEqual(fundido.evento?.payload, {
      contact_id: p.contactId,
      merged_contact_id: a.contactId,
    });
    assert.equal((await contacto(tenant, a.contactId)).merged_into, p.contactId);
    assert.deepEqual((await identidade.lerEndpoints(id, tenant, p.contactId)).bsuids, [bsuid]);
    assert.equal((await contacto(tenant, p.contactId)).phone_hmac.length, 32);
  });

  test("os ganchos correm dentro da fusão, com a ligação e os dois contactos", async () => {
    const tenant = await novoTenant("gancho");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const a = await identidade.resolveContact(id, { tenantId: tenant, bsuid });
    const p = await identidade.resolveContact(id, { tenantId: tenant, telefone });
    const vistos: unknown[] = [];
    const retirar = identidade.onContactMerge(async ({ cliente, tenantId, de, para }) => {
      // Dentro da transacção: a lápide já lá está, e ainda não foi confirmada.
      const { rows } = await cliente.query(
        "SELECT merged_into, current_setting('app.tenant_id') AS contexto " +
          "FROM platform.contacts WHERE contact_id = $1",
        [de],
      );
      vistos.push({ tenantId, de, para, linha: rows[0] });
    });
    try {
      const fundido = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });
      const para = fundido.contactId;
      const de = para === a.contactId ? p.contactId : a.contactId;
      assert.deepEqual(vistos, [
        { tenantId: tenant, de, para, linha: { merged_into: para, contexto: tenant } },
      ]);
    } finally {
      retirar();
    }
  });

  test("fusão com falha a meio: rollback completo, e a seguir funde como se nada fosse", async () => {
    const tenant = await novoTenant("rollback");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    await identidade.resolveContact(id, { tenantId: tenant, bsuid });
    await identidade.resolveContact(id, {
      tenantId: tenant,
      telefone,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });
    const antes = await fotografia(admin, tenant);

    // 1. Um gancho que falha (o de `conversations`, por exemplo).
    const retirar = identidade.onContactMerge(async () => {
      throw new Error("o gancho não conseguiu migrar as conversas");
    });
    try {
      await assert.rejects(
        identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone }),
        /não conseguiu migrar/,
      );
    } finally {
      retirar();
    }
    assert.equal(await fotografia(admin, tenant), antes, "o gancho falhou e ficou meia fusão");

    // 2. A base a falhar em cada uma das instruções da fusão, uma de cada vez.
    for (const instrucao of [
      CONSULTAS.MOVER_ENDPOINTS,
      CONSULTAS.MOVER_DEKS,
      CONSULTAS.MARCAR_FUNDIDO,
      CONSULTAS.DEFINIR_TELEFONE,
    ]) {
      const espiao = new ClienteEspiao(id);
      espiao.falharEm = instrucao;
      await assert.rejects(
        identidade.resolveContact(espiao, { tenantId: tenant, bsuid, telefone }),
        /falha de ensaio/,
      );
      assert.equal(espiao.vistas.at(-1)?.sql, "ROLLBACK");
      assert.equal(await fotografia(admin, tenant), antes, `meia fusão depois de ${instrucao}`);
    }

    // 3. Sem falha, a mesma chamada funde.
    const fundido = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });
    assert.equal(fundido.desfecho, "fundido");
    assert.notEqual(await fotografia(admin, tenant), antes);
  });

  test("um número que mudou de mãos não funde duas pessoas", async () => {
    const tenant = await novoTenant("reatribuido");
    const telefone = telefoneDeEnsaio();
    const [bsuidAntigo, bsuidNovo] = [bsuidDeEnsaio(), bsuidDeEnsaio()];
    const antigo = await identidade.resolveContact(id, {
      tenantId: tenant,
      bsuid: bsuidAntigo,
      telefone,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });

    // Outro BSUID aparece com o mesmo número: é outra pessoa.
    const novo = await identidade.resolveContact(id, { tenantId: tenant, bsuid: bsuidNovo, telefone });
    assert.equal(novo.desfecho, "criado");
    assert.equal(novo.evento, null);
    assert.notEqual(novo.contactId, antigo.contactId);

    // O antigo titular perdeu o número — o HMAC e a cifra — e mais nada.
    const doAntigo = await contacto(tenant, antigo.contactId);
    assert.equal(doAntigo.phone_hmac, null);
    assert.equal(doAntigo.merged_into, null);
    assert.deepEqual(await identidade.lerEndpoints(id, tenant, antigo.contactId), {
      contactId: antigo.contactId,
      bsuids: [bsuidAntigo],
      telefones: [],
    });
    const peloTelefone = await identidade.resolveContact(id, { tenantId: tenant, telefone });
    assert.equal(peloTelefone.contactId, novo.contactId);

    // E o mesmo quando o novo titular já existia sem número.
    const terceiro = bsuidDeEnsaio();
    const semNumero = await identidade.resolveContact(id, { tenantId: tenant, bsuid: terceiro });
    const comNumero = await identidade.resolveContact(id, { tenantId: tenant, bsuid: terceiro, telefone });
    assert.deepEqual(
      [comNumero.contactId, comNumero.desfecho, comNumero.evento],
      [semNumero.contactId, "existente", null],
    );
    assert.equal((await contacto(tenant, novo.contactId)).phone_hmac, null);
  });

  test("um contacto que troca de número fica só com o novo", async () => {
    const tenant = await novoTenant("troca");
    const bsuid = bsuidDeEnsaio();
    const [velho, novo] = [telefoneDeEnsaio(), telefoneDeEnsaio()];
    const { contactId } = await identidade.resolveContact(id, {
      tenantId: tenant,
      bsuid,
      telefone: velho,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });
    await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone: novo });
    // A cifra do número velho foi-se com ele: não é dele, e não se guarda.
    assert.deepEqual((await identidade.lerEndpoints(id, tenant, contactId)).telefones, []);
    assert.equal(
      (await identidade.resolveContact(id, { tenantId: tenant, telefone: novo })).contactId,
      contactId,
    );
    const peloVelho = await identidade.resolveContact(id, { tenantId: tenant, telefone: velho });
    assert.notEqual(peloVelho.contactId, contactId);
    assert.equal(peloVelho.desfecho, "criado");
  });
});

describe("isolamento de tenant — o teste cruzado", () => {
  test("o mesmo BSUID e o mesmo telefone em dois tenants são dois contactos, sem nada em comum", async () => {
    const [tenantA, tenantB] = [await novoTenant("iso-a"), await novoTenant("iso-b")];
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const pedido = {
      bsuid,
      telefone,
      guardarTelefone: { finalidade: "entrega" as const, expiraAt: daquiAUmAno() },
    };
    const emA = await identidade.resolveContact(id, { tenantId: tenantA, ...pedido });
    const emB = await identidade.resolveContact(id, { tenantId: tenantB, ...pedido });
    assert.notEqual(emA.contactId, emB.contactId);
    assert.deepEqual([emA.desfecho, emB.desfecho], ["criado", "criado"]);

    // Nem os HMAC coincidem: quem leia a base inteira não liga os dois.
    const [deA] = await endpoints(tenantA, emA.contactId);
    const [deB] = await endpoints(tenantB, emB.contactId);
    assert.ok(deA && deB);
    assert.equal(deA.bsuid_hmac.equals(deB.bsuid_hmac), false);
    assert.equal(
      (await contacto(tenantA, emA.contactId)).phone_hmac.equals(
        (await contacto(tenantB, emB.contactId)).phone_hmac,
      ),
      false,
    );

    // Com o contexto de B, o contacto de A não existe: nem para ler, nem para apagar.
    await assert.rejects(
      identidade.lerEndpoints(id, tenantB, emA.contactId),
      ContactoDesconhecidoError,
    );
    await assert.rejects(
      identidade.eraseContact(id, tenantB, emA.contactId),
      ContactoDesconhecidoError,
    );
    assert.deepEqual(await contar(admin, tenantA), { contactos: 1, endpoints: 2, deks: 1 });

    // Apagar em A não toca em B.
    await identidade.eraseContact(id, tenantA, emA.contactId);
    assert.deepEqual((await identidade.lerEndpoints(id, tenantB, emB.contactId)).bsuids, [bsuid]);
    assert.equal(
      (await identidade.resolveContact(id, { tenantId: tenantB, bsuid })).contactId,
      emB.contactId,
    );
  });

  test("a ligação de identidade, depois de servir um tenant, não vê nada sem contexto", async () => {
    const tenant = await novoTenant("iso-contexto");
    await identidade.resolveContact(id, { tenantId: tenant, bsuid: bsuidDeEnsaio() });
    for (const tabela of ["contacts", "contact_endpoints", "contact_deks"]) {
      const { rows } = await id.query(`SELECT count(*)::int AS n FROM platform.${tabela}`);
      assert.equal(rows[0]?.n, 0, `${tabela} visível sem contexto`);
    }
  });

  test("com o papel da aplicação, o módulo não resolve nem lê", async () => {
    const tenant = await novoTenant("iso-app");
    const { contactId } = await identidade.resolveContact(id, {
      tenantId: tenant,
      bsuid: bsuidDeEnsaio(),
    });
    const app = await ligar("app");
    try {
      await assert.rejects(
        identidade.resolveContact(app, { tenantId: tenant, bsuid: bsuidDeEnsaio() }),
        { code: "42501" },
      );
      await assert.rejects(identidade.lerEndpoints(app, tenant, contactId), { code: "42501" });
      await assert.rejects(identidade.eraseContact(app, tenant, contactId), { code: "42501" });
      // O que a aplicação consegue: o `contact_id` do seu tenant, e só ele.
      await app.query("BEGIN");
      await app.query("SELECT set_config('app.tenant_id', $1, true)", [tenant]);
      const { rows } = await app.query("SELECT contact_id FROM platform.contacts");
      await app.query("ROLLBACK");
      assert.deepEqual(rows, [{ contact_id: contactId }]);
    } finally {
      await app.end();
    }
    assert.deepEqual(await contar(admin, tenant), { contactos: 1, endpoints: 1, deks: 1 });
  });
});

describe("critério 6 — eraseContact", () => {
  test("ponta a ponta: endpoints apagados, DEK destruída, e o BSUID original é alguém novo", async () => {
    const tenant = await novoTenant("apagar");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    // Um espectador no mesmo tenant: apagar um titular não toca noutro.
    const espectador = await criarEspectador(tenant);
    const { contactId } = await identidade.resolveContact(id, {
      tenantId: tenant,
      bsuid,
      telefone,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });
    // Guarda-se o que um *backup* teria: as linhas cifradas, tal como estão.
    const copia = await endpoints(tenant, contactId);
    assert.equal(copia.length, 2);

    const apagado = await identidade.eraseContact(id, tenant, contactId);

    assert.deepEqual(
      { ...apagado, apagadoEm: null },
      { contactId, jaApagado: false, endpointsApagados: 2, deksDestruidas: 1, apagadoEm: null },
    );
    const c = await contacto(tenant, contactId);
    assert.equal(c.erased_at.getTime(), apagado.apagadoEm.getTime());
    assert.equal(c.phone_hmac, null);
    assert.equal(c.hmac_kid, null);
    assert.equal((await endpoints(tenant, contactId)).length, 0);
    const [dek, ...outras] = await linhas(
      "SELECT wrapped_dek, destroyed_at FROM platform.contact_deks " +
        "WHERE tenant_id = $1 AND contact_id = $2",
      [tenant, contactId],
    );
    assert.equal(outras.length, 0);
    assert.equal(dek?.wrapped_dek, null);
    assert.ok(dek?.destroyed_at instanceof Date);

    // A tentativa de decifrar falha.
    await assert.rejects(identidade.lerEndpoints(id, tenant, contactId), ContactoApagadoError);
    // Mesmo repondo as linhas cifradas de uma cópia: a chave de dados já não existe.
    for (const linha of copia) {
      await admin.query(
        "INSERT INTO platform.contact_endpoints (id, tenant_id, contact_id, tipo, bsuid_hmac, " +
          "hmac_kid, bsuid_enc, phone_enc, dek_id, finalidade, recolhido_at, expira_at) " +
          "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
        [
          linha.id, linha.tenant_id, linha.contact_id, linha.tipo, linha.bsuid_hmac,
          linha.hmac_kid, linha.bsuid_enc, linha.phone_enc, linha.dek_id, linha.finalidade,
          linha.recolhido_at, linha.expira_at,
        ],
      );
    }
    await assert.rejects(identidade.lerEndpoints(id, tenant, contactId), DekDestruidaError);
    await admin.query(
      "DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND contact_id = $2",
      [tenant, contactId],
    );

    // O BSUID original, e o telefone, geram um contacto novo.
    const novo = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });
    assert.equal(novo.desfecho, "criado");
    assert.notEqual(novo.contactId, contactId);
    assert.equal((await contacto(tenant, contactId)).merged_into, null);

    // Apagar outra vez não muda nada, nem toca no contacto novo.
    const outraVez = await identidade.eraseContact(id, tenant, contactId);
    assert.deepEqual(
      [outraVez.jaApagado, outraVez.endpointsApagados, outraVez.deksDestruidas],
      [true, 0, 0],
    );
    assert.equal(outraVez.apagadoEm.getTime(), apagado.apagadoEm.getTime());
    assert.deepEqual((await identidade.lerEndpoints(id, tenant, novo.contactId)).bsuids, [bsuid]);
    await espectador.intacto();
  });

  test("um telefone fora do prazo não se serve, mesmo antes de a purga o apagar", async () => {
    const tenant = await novoTenant("prazo");
    const telefone = telefoneDeEnsaio();
    const { contactId } = await identidade.resolveContact(id, {
      tenantId: tenant,
      bsuid: bsuidDeEnsaio(),
      telefone,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });
    assert.equal((await identidade.lerEndpoints(id, tenant, contactId)).telefones.length, 1);
    await admin.query(
      "UPDATE platform.contact_endpoints SET expira_at = now() - interval '1 second' " +
        "WHERE tenant_id = $1 AND tipo = 'telefone'",
      [tenant],
    );
    const lidos = await identidade.lerEndpoints(id, tenant, contactId);
    assert.deepEqual(lidos.telefones, []);
    assert.equal(lidos.bsuids.length, 1, "o BSUID não tem prazo e continua a servir-se");
  });

  test("apagar um contacto absorvido apaga quem o absorveu, com todas as DEK", async () => {
    const tenant = await novoTenant("apagar-fundido");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const a = await identidade.resolveContact(id, { tenantId: tenant, bsuid });
    const p = await identidade.resolveContact(id, {
      tenantId: tenant,
      telefone,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });
    const fundido = await identidade.resolveContact(id, { tenantId: tenant, bsuid, telefone });
    const absorvido = fundido.contactId === a.contactId ? p.contactId : a.contactId;
    assert.equal((await contar(admin, tenant)).deks, 2);

    const apagado = await identidade.eraseContact(id, tenant, absorvido);

    assert.equal(apagado.contactId, fundido.contactId);
    assert.deepEqual([apagado.endpointsApagados, apagado.deksDestruidas], [2, 2]);
    assert.deepEqual(
      await linhas(
        "SELECT count(*)::int AS vivas FROM platform.contact_deks " +
          "WHERE tenant_id = $1 AND wrapped_dek IS NOT NULL",
        [tenant],
      ),
      [{ vivas: 0 }],
    );
    await assert.rejects(identidade.lerEndpoints(id, tenant, absorvido), ContactoApagadoError);
  });

  test("um contacto que não existe é um erro, não um apagamento vazio", async () => {
    const tenant = await novoTenant("apagar-nada");
    await assert.rejects(
      identidade.eraseContact(id, tenant, "0b6f1d2e-3c4a-4b5c-8d6e-7f8091a2b3c4"),
      ContactoDesconhecidoError,
    );
  });
});

describe("critério 2 — canários", () => {
  test(`${CANARIOS} contactos com BSUID e telefone canário: nada em claro no que vai para a base`, async () => {
    const tenant = await criarTenant(admin, "canarios");
    const canarios: string[] = [];
    const pares = Array.from({ length: CANARIOS }, () => {
      const par = { bsuid: bsuidDeEnsaio("CANARIO"), telefone: telefoneDeEnsaio() };
      canarios.push(par.bsuid, par.telefone);
      return par;
    });
    const espioes = ligacoes.map((ligacao) => new ClienteEspiao(ligacao));
    const eventos: unknown[] = [];
    const resolvidos = new Set<string>();

    let espiao = 0;
    const porLigacao = new Map<pg.Client, ClienteEspiao>(
      ligacoes.map((ligacao) => [ligacao, espioes[espiao++] as ClienteEspiao]),
    );
    // Durante este ensaio o servidor regista **todas** as instruções, com os
    // parâmetros: se um canário fosse em claro para a base, ficava no registo
    // do PostgreSQL, que é onde a suite o vai procurar a seguir.
    await admin.query("ALTER SYSTEM SET log_statement = 'all'");
    await admin.query("SELECT pg_reload_conf()");
    try {
      for (const ligacao of ligacoes) {
        let ligado = false;
        for (let espera = 0; espera < 100 && !ligado; espera += 1) {
          const { rows } = await ligacao.query("SHOW log_statement");
          ligado = rows[0]?.log_statement === "all";
          if (!ligado) await new Promise((resolver) => setTimeout(resolver, 50));
        }
        assert.ok(ligado, "o servidor não passou a registar as instruções");
      }
      await emParalelo(ligacoes, pares, async (ligacao, par) => {
        const r = await identidade.resolveContact(porLigacao.get(ligacao) as ClienteEspiao, {
          tenantId: tenant,
          bsuid: par.bsuid,
          telefone: par.telefone,
          guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
        });
        resolvidos.add(r.contactId);
        if (r.evento !== null) eventos.push(r.evento);
      });
    } finally {
      await admin.query("ALTER SYSTEM RESET log_statement");
      await admin.query("SELECT pg_reload_conf()");
    }

    // Primeiro deixa-se o que a suite vai procurar no *dump* e no registo do
    // servidor: os canários, e um valor que **tem** de lá estar (o controlo). Se
    // uma asserção abaixo falhar, quem procura de fora procura na mesma — e
    // falha por ter encontrado o canário, não por lhe faltar a lista.
    const [controlo] = await linhas(
      "SELECT encode(bsuid_hmac, 'hex') AS hmac FROM platform.contact_endpoints " +
        "WHERE tenant_id = $1 AND tipo = 'bsuid' ORDER BY id LIMIT 1",
      [tenant],
    );
    const saida = process.env.KAMBA_IDENTIDADE_SAIDA ?? "";
    assert.notEqual(saida, "", "KAMBA_IDENTIDADE_SAIDA não está definida");
    writeFileSync(
      join(saida, "canarios.json"),
      JSON.stringify({ tenant, contactos: CANARIOS, canarios, controlo: controlo?.hmac }),
    );

    assert.equal(resolvidos.size, CANARIOS);
    assert.deepEqual(await contar(admin, tenant), {
      contactos: CANARIOS,
      endpoints: 2 * CANARIOS,
      deks: CANARIOS,
    });
    assert.deepEqual(eventos, []);

    // Tudo o que este processo mandou para a base, texto e parâmetros.
    const enviado = espioes.map((e) => e.emTexto()).join("\n");
    assert.ok(enviado.includes(tenant), "o espião não viu as instruções");
    for (const canario of canarios) {
      assert.equal(enviado.includes(canario), false, "um canário foi em claro para a base");
    }
  });

  test("fundir, ler, rodar e apagar com canários: nada em claro no que vai para a base, nem nos erros", async () => {
    // O ensaio de cima só passa pelo caminho «criar». Este passa pelos outros,
    // com o espião: é onde um BSUID ou um telefone podia escapar por um
    // parâmetro ou por uma mensagem de erro.
    const tenant = await novoTenant("canarios-caminhos");
    const espiao = new ClienteEspiao(id);
    const [bsuid, telefone, outro] = [bsuidDeEnsaio("CANARIO"), telefoneDeEnsaio(), telefoneDeEnsaio()];
    const mensagens: string[] = [];
    const guardar = { finalidade: "entrega" as const, expiraAt: daquiAUmAno() };

    const a = await identidade.resolveContact(espiao, { tenantId: tenant, bsuid });
    await identidade.resolveContact(espiao, { tenantId: tenant, telefone, guardarTelefone: guardar });
    const fundido = await identidade.resolveContact(espiao, { tenantId: tenant, bsuid, telefone });
    assert.equal(fundido.desfecho, "fundido");
    await identidade.resolveContact(espiao, { tenantId: tenant, bsuid, telefone: outro, guardarTelefone: guardar });
    assert.deepEqual((await identidade.lerEndpoints(espiao, tenant, a.contactId)).bsuids, [bsuid]);
    await identidade.rekeyLookup(espiao, tenant, "k1");
    const falha = new ClienteEspiao(id);
    falha.falharEm = CONSULTAS.CRIAR_ENDPOINT_BSUID;
    for (const pedido of [
      () => identidade.resolveContact(falha, { tenantId: tenant, bsuid: `${bsuid}x`, telefone }),
      () => identidade.resolveContact(espiao, { tenantId: tenant, bsuid: ` ${bsuid}` }),
      () => identidade.resolveContact(espiao, { tenantId: tenant, telefone: `${telefone} ` }),
    ]) {
      await pedido().catch((erro: unknown) => mensagens.push(String(erro), JSON.stringify(erro)));
    }
    assert.equal(mensagens.length, 6);
    await identidade.eraseContact(espiao, tenant, fundido.contactId);

    const visto = [espiao.emTexto(), falha.emTexto(), JSON.stringify(fundido.evento), ...mensagens].join("\n");
    assert.ok(visto.includes(tenant));
    for (const canario of [bsuid, telefone, outro]) {
      for (const forma of [canario, Buffer.from(canario).toString("hex"), Buffer.from(canario).toString("base64")]) {
        assert.equal(visto.includes(forma), false, "um identificador saiu em claro");
      }
    }
  });
});

describe("critérios 3 e 5 — idempotência e rotação", () => {
  let tenant = "";
  const bsuids: string[] = [];
  const contactos = new Map<string, string>();

  test(`${CHAMADAS} BSUID aleatórios, resolvidos em paralelo: um contacto cada`, async () => {
    tenant = await novoTenant("idempotencia");
    for (let i = 0; i < CHAMADAS; i += 1) bsuids.push(bsuidDeEnsaio());
    await emParalelo(ligacoes, bsuids, async (ligacao, bsuid) => {
      const r = await identidade.resolveContact(ligacao, { tenantId: tenant, bsuid });
      assert.equal(r.desfecho, "criado");
      contactos.set(bsuid, r.contactId);
    });
    assert.equal(new Set(contactos.values()).size, CHAMADAS);
    assert.deepEqual(await contar(admin, tenant), {
      contactos: CHAMADAS,
      endpoints: CHAMADAS,
      deks: CHAMADAS,
    });
  });

  test(`${CHAMADAS} chamadas repetidas devolvem o mesmo contact_id, e não criam nada`, async () => {
    const baralhados = [...bsuids].sort(() => Math.random() - 0.5);
    let diferentes = 0;
    await emParalelo(ligacoes, baralhados, async (ligacao, bsuid) => {
      const r = await identidade.resolveContact(ligacao, { tenantId: tenant, bsuid });
      if (r.contactId !== contactos.get(bsuid) || r.desfecho !== "existente") diferentes += 1;
    });
    assert.equal(diferentes, 0);
    assert.deepEqual(await contar(admin, tenant), {
      contactos: CHAMADAS,
      endpoints: CHAMADAS,
      deks: CHAMADAS,
    });
  });

  test("oito pedidos simultâneos pelo mesmo contacto novo criam um só", async () => {
    const corrida = await novoTenant("corrida");
    for (let volta = 0; volta < 25; volta += 1) {
      const bsuid = bsuidDeEnsaio();
      const telefone = telefoneDeEnsaio();
      const resolvidos = await Promise.all(
        ligacoes.map((ligacao) =>
          identidade.resolveContact(ligacao, { tenantId: corrida, bsuid, telefone }),
        ),
      );
      assert.equal(new Set(resolvidos.map((r) => r.contactId)).size, 1);
      assert.equal(resolvidos.filter((r) => r.desfecho === "criado").length, 1);
    }
    assert.deepEqual(await contar(admin, corrida), { contactos: 25, endpoints: 25, deks: 25 });
  });

  test("rekeyLookup recusa uma versão que não é a actual", async () => {
    chaves.rodar("k2");
    await assert.rejects(identidade.rekeyLookup(id, tenant, "k2", { lote: 500 }), KidNaoActualError);
    const [{ n }] = (await linhas(
      "SELECT count(*)::int AS n FROM platform.contact_endpoints WHERE tenant_id = $1 AND hmac_kid <> 'k1'",
      [tenant],
    )) as [{ n: number }];
    assert.equal(n, 0);
  });

  test("durante a janela, a pesquisa tenta a chave actual e a anterior", async () => {
    const dosCifrados = await novoTenant("janela-com-cifra");
    assert.deepEqual(await identidade.iniciarRotacao(id, "k2"), {
      kid: "k2",
      alterado: true,
      anterior: "k1",
    });
    assert.deepEqual(
      await linhas("SELECT kid, estado FROM platform.hmac_key_versions ORDER BY kid"),
      [
        { kid: "k1", estado: "anterior" },
        { kid: "k2", estado: "actual" },
      ],
    );
    // Rodar **para** a versão anterior é recusado: está registada, o cofre ainda a
    // tem, e levava as linhas já rodadas de volta para a chave que se quer retirar.
    await assert.rejects(identidade.rekeyLookup(id, tenant, "k1", { lote: 500 }), KidNaoActualError);
    assert.deepEqual(
      await linhas(
        "SELECT DISTINCT hmac_kid FROM platform.contact_endpoints WHERE tenant_id = $1",
        [tenant],
      ),
      [{ hmac_kid: "k1" }],
    );
    // Uma segunda rotação por cima desta é recusada: deixava linhas sem chave que as lesse.
    await assert.rejects(identidade.iniciarRotacao(id, "k1"), RotacaoEmCursoError);

    // Nenhuma linha foi ainda rodada, e todas continuam a resolver.
    const amostra = bsuids.slice(0, 200);
    for (const bsuid of amostra) {
      const r = await identidade.resolveContact(id, { tenantId: tenant, bsuid });
      assert.deepEqual([r.contactId, r.desfecho], [contactos.get(bsuid), "existente"]);
    }
    // E quem foi visto subiu para a chave nova, sem esperar pelo *job*.
    const [{ subidas }] = (await linhas(
      "SELECT count(*)::int AS subidas FROM platform.contact_endpoints " +
        "WHERE tenant_id = $1 AND hmac_kid = 'k2'",
      [tenant],
    )) as [{ subidas: number }];
    assert.equal(subidas, amostra.length);
    // Rever, na janela, um contacto com telefone guardado: o HMAC sobe para a
    // chave nova e a cifra **fica** — é o mesmo número, não uma troca.
    const comCifra = { bsuid: bsuidDeEnsaio(), telefone: telefoneDeEnsaio() };
    const daJanela = await identidade.resolveContact(id, {
      tenantId: dosCifrados,
      ...comCifra,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });
    await admin.query(
      "UPDATE platform.contacts SET hmac_kid = 'k1', phone_hmac = $3 WHERE tenant_id = $1 AND contact_id = $2",
      [
        dosCifrados,
        daJanela.contactId,
        hmacDePesquisa(await chaves.provedor().getLookupKey("k1"), dosCifrados, "telefone", comCifra.telefone),
      ],
    );
    const revisto = await identidade.resolveContact(id, { tenantId: dosCifrados, ...comCifra });
    assert.deepEqual([revisto.contactId, revisto.desfecho], [daJanela.contactId, "existente"]);
    assert.equal((await contacto(dosCifrados, daJanela.contactId)).hmac_kid, "k2");
    assert.deepEqual(
      (await identidade.lerEndpoints(id, dosCifrados, daJanela.contactId)).telefones.map((t) => t.telefone),
      [comCifra.telefone],
    );

    // Um contacto novo nasce já sob a chave nova.
    const novo = await identidade.resolveContact(id, { tenantId: tenant, bsuid: bsuidDeEnsaio() });
    assert.equal((await endpoints(tenant, novo.contactId))[0]?.hmac_kid, "k2");
    await apagarContacto(tenant, novo.contactId);
  });

  test("rekeyLookup é retomável: interrompido a meio, continua de onde ficou", async () => {
    const parcial = await identidade.rekeyLookup(id, tenant, "k2", { lote: 500, maximoDeLotes: 3 });
    assert.deepEqual(
      [parcial.bsuidsRodados, parcial.lotes, parcial.completo, parcial.porRodar.bsuids],
      [1500, 3, false, CHAMADAS - 200 - 1500],
    );
    // A meio da rotação, rodados e por rodar resolvem todos.
    for (const bsuid of [...bsuids.slice(0, 50), ...bsuids.slice(-50)]) {
      const r = await identidade.resolveContact(id, { tenantId: tenant, bsuid });
      assert.equal(r.contactId, contactos.get(bsuid));
    }
    const resto = await identidade.rekeyLookup(id, tenant, "k2", { lote: 500 });
    assert.equal(resto.completo, true);
    assert.deepEqual(resto.porRodar, { bsuids: 0, telefones: 0 });
    assert.ok(resto.bsuidsRodados > 0 && resto.bsuidsRodados <= CHAMADAS - 200 - 1500);
  });

  test("no fim, 100% das linhas têm a versão nova — e o HMAC é o da chave nova", async () => {
    assert.deepEqual(
      await linhas(
        "SELECT hmac_kid, count(*)::int AS n FROM platform.contact_endpoints " +
          "WHERE tenant_id = $1 GROUP BY hmac_kid",
        [tenant],
      ),
      [{ hmac_kid: "k2", n: CHAMADAS }],
    );
    const chaveNova = await chaves.provedor().getLookupKey("k2");
    const chaveVelha = await chaves.provedor().getLookupKey("k1");
    const amostra = [...bsuids.slice(0, 100), ...bsuids.slice(5000, 5100), ...bsuids.slice(-100)];
    for (const bsuid of amostra) {
      const [linha] = await endpoints(tenant, contactos.get(bsuid) as string);
      assert.ok(linha);
      assert.ok(linha.bsuid_hmac.equals(hmacDePesquisa(chaveNova, tenant, "bsuid", bsuid)));
      assert.equal(linha.bsuid_hmac.equals(hmacDePesquisa(chaveVelha, tenant, "bsuid", bsuid)), false);
    }
  });

  test("rekeyLookup é idempotente: outra vez sobre um tenant completo não muda nada", async () => {
    const antes = await fotografiaDosHmac(tenant);
    const repetido = await identidade.rekeyLookup(id, tenant, "k2", { lote: 500 });
    assert.deepEqual(
      [repetido.bsuidsRodados, repetido.telefonesRodados, repetido.completo],
      [0, 0, true],
    );
    assert.equal(await fotografiaDosHmac(tenant), antes);
  });

  test("depois de concluir, a chave antiga já não é precisa para resolver", async () => {
    assert.equal(await identidade.concluirRotacao(id), "k1");
    assert.equal(await identidade.concluirRotacao(id), null);
    chaves.esquecerAnterior();
    await assert.rejects(chaves.provedor().getLookupKey("k1"), /cofre não tem a versão/);
    let diferentes = 0;
    const amostra = [...bsuids.slice(0, 250), ...bsuids.slice(-250)];
    await emParalelo(ligacoes, amostra, async (ligacao, bsuid) => {
      const r = await identidade.resolveContact(ligacao, { tenantId: tenant, bsuid });
      if (r.contactId !== contactos.get(bsuid) || r.desfecho !== "existente") diferentes += 1;
    });
    assert.equal(diferentes, 0);
    assert.equal((await contar(admin, tenant)).contactos, CHAMADAS);
    // Uma versão que já existiu não volta a ser a actual.
    chaves.rodar("k1");
    await assert.rejects(identidade.iniciarRotacao(id, "k1"), KidReutilizadoError);
    chaves.desfazerRodar();
  });

  test("o telefone também roda: com cifra recalcula-se; sem cifra mantém-se ou larga-se", async () => {
    const dosTelefones = await novoTenant("rodar-telefones");
    const comCifra = { bsuid: bsuidDeEnsaio(), telefone: telefoneDeEnsaio() };
    const semCifra = { telefone: telefoneDeEnsaio() };
    const a = await identidade.resolveContact(id, {
      tenantId: dosTelefones,
      ...comCifra,
      guardarTelefone: { finalidade: "entrega", expiraAt: daquiAUmAno() },
    });
    const b = await identidade.resolveContact(id, { tenantId: dosTelefones, ...semCifra });

    chaves.rodar("k3");
    await identidade.iniciarRotacao(id, "k3");

    const manter = await identidade.rekeyLookup(id, dosTelefones, "k3", { lote: 1 });
    assert.deepEqual(
      [manter.bsuidsRodados, manter.telefonesRodados, manter.telefonesLargados, manter.completo],
      [1, 1, 0, false],
    );
    assert.deepEqual(manter.porRodar, { bsuids: 0, telefones: 1 });
    assert.equal((await contacto(dosTelefones, a.contactId)).hmac_kid, "k3");
    // O que ficou sob a chave antiga continua a ser encontrado, e sobe quando é visto.
    assert.equal((await contacto(dosTelefones, b.contactId)).hmac_kid, "k2");
    const visto = await identidade.resolveContact(id, { tenantId: dosTelefones, ...semCifra });
    assert.equal(visto.contactId, b.contactId);
    assert.equal((await contacto(dosTelefones, b.contactId)).hmac_kid, "k3");

    // `largar`: o passo final, para o que nunca mais foi visto.
    const c = await identidade.resolveContact(id, { tenantId: dosTelefones, telefone: telefoneDeEnsaio() });
    await admin.query(
      "UPDATE platform.contacts SET hmac_kid = 'k2' WHERE tenant_id = $1 AND contact_id = $2",
      [dosTelefones, c.contactId],
    );
    const largar = await identidade.rekeyLookup(id, dosTelefones, "k3", { telefonesSemCifra: "largar" });
    assert.deepEqual([largar.telefonesLargados, largar.completo], [1, true]);
    assert.equal((await contacto(dosTelefones, c.contactId)).phone_hmac, null);
    assert.equal((await contacto(dosTelefones, a.contactId)).phone_hmac.length, 32);
    assert.equal(
      (await identidade.resolveContact(id, { tenantId: dosTelefones, telefone: comCifra.telefone }))
        .contactId,
      a.contactId,
    );
    assert.equal(await identidade.concluirRotacao(id), "k2");
  });

  test("uma rotação espera por quem está a resolver: o mesmo BSUID nunca fica com dois contactos", async () => {
    // Achado 1 da revisão adversarial. Um pedido que já leu «a actual é k3»
    // pára antes de escrever; a rotação para k4 começa; outro pedido pelo mesmo
    // BSUID chega a seguir. Sem a tranca partilhada sobre as versões, o
    // primeiro escrevia sob k3, o segundo sob k4, e ficavam dois contactos.
    const daCorrida = await novoTenant("corrida-com-rotacao");
    const bsuid = bsuidDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const [ligacaoA, ligacaoB, ligacaoC] = ligacoes as [pg.Client, pg.Client, pg.Client];
    chaves.rodar("k4");

    const lento = new ClienteEspiao(ligacaoA);
    lento.pararAntesDe = CONSULTAS.CRIAR_CONTACTO;
    const primeiro = identidade.resolveContact(lento, { tenantId: daCorrida, bsuid, telefone });
    await lento.parado;

    let rodou = false;
    const rotacao = identidade.iniciarRotacao(ligacaoB, "k4").then((resultado) => {
      rodou = true;
      return resultado;
    });
    await new Promise((resolver) => setTimeout(resolver, 500));
    assert.equal(rodou, false, "a rotação não esperou pelo pedido em curso");

    lento.continuar();
    const [doPrimeiro, daRotacao] = await Promise.all([primeiro, rotacao]);
    assert.deepEqual([daRotacao.kid, daRotacao.alterado, daRotacao.anterior], ["k4", true, "k3"]);
    assert.equal(doPrimeiro.desfecho, "criado");

    const segundo = await identidade.resolveContact(ligacaoC, { tenantId: daCorrida, bsuid, telefone });
    assert.deepEqual([segundo.contactId, segundo.desfecho], [doPrimeiro.contactId, "existente"]);
    assert.deepEqual(await contar(admin, daCorrida), { contactos: 1, endpoints: 1, deks: 1 });

    // E o contrário: um pedido que chega **durante** a rotação espera por ela e
    // já escreve sob a versão nova.
    assert.equal(await identidade.concluirRotacao(id), "k3");
    chaves.esquecerAnterior();
    chaves.rodar("k5");
    await ligacaoB.query("BEGIN");
    await ligacaoB.query(CONSULTAS.KIDS_VIVOS_TRANCADOS);
    let resolveu = false;
    const outroBsuid = bsuidDeEnsaio();
    const durante = identidade
      .resolveContact(ligacaoC, { tenantId: daCorrida, bsuid: outroBsuid })
      .then((resultado) => {
        resolveu = true;
        return resultado;
      });
    await new Promise((resolver) => setTimeout(resolver, 500));
    assert.equal(resolveu, false, "o pedido não esperou pela rotação em curso");
    await ligacaoB.query(CONSULTAS.DESPROMOVER_ACTUAL);
    await ligacaoB.query(CONSULTAS.REGISTAR_ACTUAL, ["k5"]);
    await ligacaoB.query("COMMIT");
    const depois = await durante;
    assert.equal((await endpoints(daCorrida, depois.contactId))[0]?.hmac_kid, "k5");
    assert.equal(await identidade.concluirRotacao(id), "k4");
    chaves.esquecerAnterior();
  });

  async function apagarContacto(doTenant: string, contactId: string): Promise<void> {
    await admin.query("DELETE FROM platform.contact_endpoints WHERE tenant_id = $1 AND contact_id = $2", [
      doTenant,
      contactId,
    ]);
    await admin.query("DELETE FROM platform.contact_deks WHERE tenant_id = $1 AND contact_id = $2", [
      doTenant,
      contactId,
    ]);
    await admin.query("DELETE FROM platform.contacts WHERE tenant_id = $1 AND contact_id = $2", [
      doTenant,
      contactId,
    ]);
  }

  async function fotografiaDosHmac(doTenant: string): Promise<string> {
    const [linha] = await linhas(
      "SELECT md5(string_agg(id::text || hmac_kid || encode(bsuid_hmac, 'hex'), ',' ORDER BY id)) AS resumo " +
        "FROM platform.contact_endpoints WHERE tenant_id = $1",
      [doTenant],
    );
    return String(linha?.resumo);
  }
});
