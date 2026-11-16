/**
 * A lista de espera contra um PostgreSQL real, pelo código TypeScript (KAM-095).
 *
 * **O que só aqui se prova**, e é a razão de este ficheiro existir (achado da
 * revisão adversarial): o `db/tests/test_lista_espera_schema.py` executa as
 * constantes de SQL do módulo, mas reimplementa a transacção em Python — o
 * `ListaSql.emTransaccao` e a ordem dos parâmetros do `transitar` nunca corriam
 * contra a base. Aqui corre o `ListaSql` e a `ListaDeEspera` verdadeiros, com o
 * `kamba_batch` verdadeiro:
 *
 * 1. **Vinte reservas de casos novos ao mesmo tempo, com uma vaga, dão uma.** E o
 *    controlo: o mesmo conjunto com a tranca tapada (o `SQL_TRANCAR` trocado por
 *    um `SELECT 1`) dá mais do que uma — é o que diz que o ensaio sabe ver o
 *    defeito. Uma pausa depois do `SQL_A_FRENTE`, nas duas corridas, põe as vinte
 *    leituras na mesma janela.
 * 2. **A ordem dos parâmetros do `transitar`**: um convite, uma expiração e uma
 *    desistência pelo serviço, e cada coluna lida da base.
 *
 * Nada aqui é um dado real: os NIF e telefones são bytes aleatórios.
 */

import assert from "node:assert/strict";
import { createHash, randomBytes } from "node:crypto";
import { after, before, describe, it } from "node:test";

import pg from "pg";

import { BASE_DESCARTAVEL, ligar } from "./apoio.ts";
import {
  AvisosDaListaEmMemoria,
  type ConjuntoSql,
  ListaDeEspera,
  ListaSql,
} from "../src/capacidade/index.ts";
import { SQL_A_FRENTE, SQL_TRANCAR } from "../src/capacidade/sql.ts";

function exigir(nome: string): string {
  const valor = process.env[nome] ?? "";
  if (valor === "") throw new Error(`a variável de ambiente ${nome} não está definida`);
  return valor;
}

/** Um `pg.Pool` do `kamba_batch`, só sobre a base descartável. */
function conjuntoDoLote(): pg.Pool {
  const base = exigir("KAMBA_DB_NAME");
  if (base !== BASE_DESCARTAVEL) throw new Error(`KAMBA_DB_NAME não é ${BASE_DESCARTAVEL}`);
  return new pg.Pool({
    host: process.env.KAMBA_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.KAMBA_DB_PORT ?? "5432"),
    database: base,
    user: "kamba_batch",
    password: exigir("KAMBA_SECRET_DB_BATCH_PASSWORD"),
    application_name: "kamba-capacidade-teste",
    max: 25,
  });
}

const espera = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/**
 * O conjunto, com a pausa depois do `SQL_A_FRENTE` e, se `semTranca`, com o
 * `SQL_TRANCAR` tapado. É a única diferença entre as duas corridas.
 */
function instrumentado(c: pg.Pool, semTranca: boolean): ConjuntoSql {
  const embrulhar = (cliente: pg.PoolClient) => ({
    query: async (texto: string, valores?: readonly unknown[]) => {
      const r = await cliente.query(semTranca && texto === SQL_TRANCAR ? "SELECT 1" : texto, valores as unknown[]);
      if (texto === SQL_A_FRENTE) await espera(150);
      return r;
    },
    release: (erro?: Error | boolean) => cliente.release(erro),
  });
  return {
    query: (texto: string, valores?: readonly unknown[]) => c.query(texto, valores as unknown[]),
    connect: async () => embrulhar(await c.connect()),
  } as unknown as ConjuntoSql;
}

let admin: pg.Client;
let lote: pg.Pool;
const criados: string[] = [];

async function onboarding(fase = "aguarda_es"): Promise<string> {
  const r = await admin.query<{ id: string }>(
    `INSERT INTO platform.onboarding_case
       (fase, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac)
     VALUES ($1, 'convite', 'Loja de ensaio', 'alimentar', $2, $3, $2, $4)
     RETURNING id`,
    [fase, randomBytes(40), randomBytes(32), randomBytes(32)],
  );
  criados.push(r.rows[0]!.id);
  return r.rows[0]!.id;
}

async function limpar(): Promise<void> {
  await admin.query("DELETE FROM platform.waitlist_entry");
  await admin.query("UPDATE platform.onboarding_capacity SET es_max_por_7d = 1");
}

function lista(conjunto: ConjuntoSql, aviso = new AvisosDaListaEmMemoria()): ListaDeEspera {
  return new ListaDeEspera({ repositorio: new ListaSql(conjunto), aviso, origem: "https://onboarding.exemplo.test" });
}

async function corrida(semTranca: boolean): Promise<number> {
  await limpar();
  const ids = await Promise.all(Array.from({ length: 20 }, () => onboarding()));
  const l = lista(instrumentado(lote, semTranca));
  const r = await Promise.all(ids.map((id) => l.reserve(id)));
  return r.filter((x) => x === "granted").length;
}

describe("a lista de espera contra a base", () => {
  before(async () => {
    admin = await ligar("admin");
    lote = conjuntoDoLote();
  });

  after(async () => {
    await admin.query("DELETE FROM platform.waitlist_entry WHERE onboarding_id = ANY($1::uuid[])", [criados]);
    await admin.query("DELETE FROM platform.onboarding_case WHERE id = ANY($1::uuid[])", [criados]);
    await admin.query("UPDATE platform.onboarding_capacity SET es_max_por_7d = 10");
    await lote.end();
    await admin.end();
  });

  it("vinte reservas de casos novos com uma vaga dão uma; sem a tranca do adaptador, mais", async (t) => {
    const comTranca = await corrida(false);
    const semTranca = await corrida(true);
    t.diagnostic(`[KAM-095] reserva: com tranca ${comTranca} concedida(s), sem tranca ${semTranca}`);
    assert.equal(comTranca, 1);
    assert.ok(semTranca > 1, `sem a tranca deram-se ${semTranca}: o controlo não viu o defeito`);
  });

  it("convite, expiração e desistência pelo serviço escrevem cada coluna no sítio dela", async () => {
    await limpar();
    const [a, b] = [await onboarding(), await onboarding()];
    const aviso = new AvisosDaListaEmMemoria();
    const l = lista(lote as unknown as ConjuntoSql, aviso);
    assert.equal(await l.reserve(a), "granted");
    assert.equal(await l.reserve(b), "lista_espera");
    const ler = async (id: string) =>
      (
        await admin.query(
          `SELECT estado, tentativas, convite_hash, convidado_em, convite_expira_em, concluido_em, na_fila_desde
             FROM platform.waitlist_entry WHERE onboarding_id = $1`,
          [id],
        )
      ).rows[0];
    // A vaga de A sai da janela: o promover convida B.
    await admin.query(
      "UPDATE platform.waitlist_entry SET concluido_em = now() - interval '8 days' WHERE onboarding_id = $1",
      [a],
    );
    const antes = await ler(b);
    assert.equal(await l.promover(), 1);
    const convidado = await ler(b);
    const c = new URL(aviso.enviados[0]!.ligacao).searchParams.get("convite")!;
    assert.equal(convidado.estado, "convidado");
    assert.equal(Buffer.from(convidado.convite_hash).toString("hex"), createHash("sha256").update(c).digest("hex"));
    assert.equal(convidado.convite_expira_em.getTime() - convidado.convidado_em.getTime(), 48 * 3_600_000);
    assert.equal(convidado.na_fila_desde.getTime(), antes.na_fila_desde.getTime(), "o convite não mexe na ordem");
    assert.equal(convidado.tentativas, 0);
    assert.equal(convidado.concluido_em, null);
    // O convite vence: B vai para o fim, com uma tentativa, e é convidado outra vez.
    await admin.query(
      `UPDATE platform.waitlist_entry SET convidado_em = now() - interval '3 days',
         convite_expira_em = now() - interval '1 hour' WHERE onboarding_id = $1`,
      [b],
    );
    assert.equal(await l.expirarVencidos(), 1);
    const depois = await ler(b);
    assert.equal(depois.tentativas, 1);
    assert.ok(depois.na_fila_desde.getTime() > antes.na_fila_desde.getTime(), "voltou ao fim");
    assert.equal(depois.estado, "convidado");
    // Desiste com o convite na mão: gasta-o, e o convite apaga-se.
    await l.desistir(b);
    const fim = await ler(b);
    assert.equal(fim.estado, "desistiu");
    assert.equal(fim.tentativas, 2);
    assert.equal(fim.convite_hash, null);
    assert.equal(fim.convite_expira_em, null);
  });
});
