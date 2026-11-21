/**
 * A inscrição contra a base (KAM-236): o registo, o OTP, os contadores e as
 * revogações do painel sobre a revisão `0084`, como `kamba_app`.
 *
 * ```text
 * reinicio      o registo cria o caso por um processo; outro processo, sobre
 *               outro pool, acerta o codigo, conclui o OTP e reconhece a
 *               mesma chave de idempotencia
 * cifra         o nif_enc, o phone_enc e o email_enc abrem com o caso certo, e
 *               o nif_enc nao abre como email_enc
 * isolamento    o kamba_app nao le o caso de outro tenant pela tabela; as
 *               funcoes so devolvem o caso e o tenant
 * contadores    vinte anotacoes concorrentes de dois processos somam vinte; o
 *               trocarUltimo concorrente devolve null uma vez
 * revogacoes    uma sessao revogada continua revogada depois do reinicio, e o
 *               corte de um tenant nao toca o outro
 * ```
 *
 * Os números são fictícios, com 999, e os NIF de ensaio não são de ninguém.
 */

import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { after, before, describe, it } from "node:test";

import pg from "pg";

import { BASE_DESCARTAVEL } from "./apoio.ts";
import {
  AntiAbuso,
  Otp,
  OtpPorSmsLocal,
  Registo,
  SEGUNDOS_MINIMOS,
  anelDoTelefone,
  anelDosDados,
  casosNaBase,
  cifraDoCaso,
  contadoresNaBase,
  cunharToken,
  decifrarDadoDoCaso,
  decifrarTelefoneDoCaso,
  lerReferencia,
  otpNaBase,
  resolverDesafio,
  type PoolDaInscricao,
  type PedidoDeRegisto,
} from "../src/inscricao/index.ts";
import { FakeSmsProvider } from "../src/sms/index.ts";
import { comTenant } from "../src/tenant_guard/index.ts";
import { RevogacoesNaBase } from "../../../services/onboarding-web/src/painel/revogacoes_sql.ts";
import { novaSessao } from "../../../services/onboarding-web/src/painel/sessao.ts";

const PEPPER = randomBytes(32);
const ASSINATURA = randomBytes(32);
const PEPPER_DO_DESTINO = randomBytes(32);
const ANEL_DO_TELEFONE = anelDoTelefone([`tel-1:${randomBytes(32).toString("base64")}`, null]);
const ANEL_DOS_DADOS = anelDosDados("kek_dados_do_caso", [`dad-1:${randomBytes(32).toString("base64")}`, null]);

/** Um NIF de ensaio, novo por corrida: dez algarismos e duas letras. */
function nifDeEnsaio(): string {
  return `5419${String(Math.floor(Math.random() * 1e6)).padStart(6, "0")}KB`;
}

/** Um telefone fictício com 999, novo por corrida. */
function telefoneDeEnsaio(): string {
  return `+244 999 ${String(Math.floor(Math.random() * 1e6)).padStart(6, "0")}`;
}

function exigir(nome: string): string {
  const valor = process.env[nome] ?? "";
  if (valor === "") throw new Error(`a variável de ambiente ${nome} não está definida`);
  return valor;
}

function configuracao(papel: "app" | "admin"): pg.ClientConfig {
  const base = exigir("KAMBA_DB_NAME");
  if (base !== BASE_DESCARTAVEL) throw new Error(`KAMBA_DB_NAME não é ${BASE_DESCARTAVEL}`);
  return {
    host: process.env.KAMBA_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.KAMBA_DB_PORT ?? "5432"),
    database: base,
    user: papel === "app" ? "kamba_app" : exigir("POSTGRES_USER"),
    password: exigir(papel === "app" ? "KAMBA_SECRET_DB_APP_PASSWORD" : "POSTGRES_PASSWORD"),
    application_name: `kamba-inscricao-teste:${papel}`,
  };
}

function poolDaApp(): pg.Pool {
  return new pg.Pool({ ...configuracao("app"), max: 6 });
}

let admin: pg.Client;
const pools: pg.Pool[] = [];
const casosCriados: string[] = [];
const chavesDosContadores: string[] = [];
const tenantsDasRevogacoes: string[] = [];

function novoPool(): pg.Pool {
  const pool = poolDaApp();
  pools.push(pool);
  return pool;
}

/** Um processo do `onboarding-web`: o registo e o OTP sobre um *pool* seu. */
function processo(pool: pg.Pool) {
  const p = pool as unknown as PoolDaInscricao;
  let agora = Date.now();
  const relogio = (): Date => new Date(agora);
  const contadores = contadoresNaBase(p);
  const sms = new FakeSmsProvider({ relogio });
  const otp = new Otp({
    repositorio: otpNaBase(p),
    contadores,
    provedor: new OtpPorSmsLocal({ sms, pepperDoDestino: PEPPER_DO_DESTINO }),
    chave: PEPPER,
    relogio,
  });
  const casos = casosNaBase({ pool: p, cifra: cifraDoCaso(ANEL_DO_TELEFONE, ANEL_DOS_DADOS), anelDoPepper: [PEPPER, null] });
  const registo = new Registo({
    repositorio: casos,
    antiabuso: new AntiAbuso({ contadores, chave: PEPPER, relogio, dificuldadeBase: 4 }),
    otp,
    anelDoPepper: [PEPPER, null],
    anelDoToken: [ASSINATURA, null],
    anelDaSessao: [ASSINATURA, null],
    relogio,
  });
  return {
    registo,
    otp,
    casos,
    contadores,
    sms,
    relogio,
    avancar: (ms: number) => {
      agora += ms;
    },
  };
}

type Processo = ReturnType<typeof processo>;

async function pedido(m: Processo, campos: { nif: string; telefone: string; chave: string; email?: string }): Promise<PedidoDeRegisto> {
  const emitido = await m.registo.desafioPara(undefined);
  m.avancar(SEGUNDOS_MINIMOS * 1000);
  return {
    token: cunharToken("convite", new Date(m.relogio().getTime() + 86_400_000), ASSINATURA, m.relogio),
    nomeNegocio: "Loja de ensaio",
    categoria: "mercearia",
    nif: campos.nif,
    telefone: campos.telefone,
    email: campos.email,
    chaveDeIdempotencia: campos.chave,
    desafio: emitido.desafio,
    solucao: resolverDesafio(emitido.desafio, emitido.dificuldade),
  } as PedidoDeRegisto;
}

/** O código do último SMS do `fake`. */
function ultimoCodigo(m: Processo): string {
  const envio = m.sms.enviados.at(-1);
  const codigo = envio?.corpo.match(/[0-9]{6}/)?.[0];
  if (codigo === undefined) throw new Error("o fake nao tem codigo");
  return codigo;
}

before(async () => {
  admin = new pg.Client(configuracao("admin"));
  await admin.connect();
});

after(async () => {
  // O administrador é o dono das tabelas: o `kamba_app` não apaga casos.
  if (casosCriados.length > 0) {
    await admin.query("DELETE FROM platform.onboarding_otp WHERE onboarding_id = ANY ($1::uuid[])", [casosCriados]);
    await admin.query("DELETE FROM platform.onboarding_case WHERE id = ANY ($1::uuid[])", [casosCriados]);
  }
  await admin.query("DELETE FROM platform.onboarding_contador WHERE chave = ANY ($1::text[])", [chavesDosContadores]);
  await admin.query("DELETE FROM platform.painel_revogacao WHERE tenant_id = ANY ($1::uuid[])", [tenantsDasRevogacoes]);
  for (const pool of pools) await pool.end().catch(() => undefined);
  await admin.end();
});

describe("a inscrição na base (KAM-236)", () => {
  it("KAM-236: o registo cria o caso num processo e outro processo acerta o código, conclui e reconhece a chave", async () => {
    const nif = nifDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const chave = `kam-236-${randomUUID()}`;

    const primeiro = processo(novoPool());
    const aceite = await primeiro.registo.inscrever(
      await pedido(primeiro, { nif, telefone, chave, email: "ensaio@exemplo.invalid" }),
    );
    const id = lerReferencia("ticket", aceite.referencia, [ASSINATURA, null], primeiro.relogio);
    casosCriados.push(id);
    const codigo = ultimoCodigo(primeiro);

    const linha = (
      await admin.query<{ fase: string; tenant_id: string; chave_idem: string; nif_enc: Buffer; phone_enc: Buffer; email_enc: Buffer }>(
        "SELECT fase, tenant_id::text AS tenant_id, chave_idem, nif_enc, phone_enc, email_enc FROM platform.onboarding_case WHERE id = $1",
        [id],
      )
    ).rows[0];
    assert.ok(linha, "o caso esta na base");
    assert.equal(linha.fase, "otp_pendente");
    assert.equal(linha.chave_idem, chave);
    const caso = { tenantId: linha.tenant_id, onboardingId: id };
    assert.equal(decifrarDadoDoCaso(ANEL_DOS_DADOS, caso, "nif_enc", linha.nif_enc), nif);
    assert.equal(decifrarDadoDoCaso(ANEL_DOS_DADOS, caso, "email_enc", linha.email_enc), "ensaio@exemplo.invalid");
    assert.equal(decifrarTelefoneDoCaso(ANEL_DO_TELEFONE, caso, linha.phone_enc).revelar(), telefone.replace(/ /g, ""));
    assert.throws(() => decifrarDadoDoCaso(ANEL_DOS_DADOS, caso, "email_enc", linha.nif_enc), "o nif_enc nao abre como email_enc");
    const outroCaso = { tenantId: linha.tenant_id, onboardingId: randomUUID() };
    assert.throws(() => decifrarDadoDoCaso(ANEL_DOS_DADOS, outroCaso, "nif_enc", linha.nif_enc), "nem noutro caso");

    // **O reinício**: o primeiro processo morre, e o segundo nasce sobre outro pool.
    await pools[pools.length - 1]!.end();
    pools.pop();
    const segundo = processo(novoPool());
    assert.equal((await segundo.casos.porId(id))?.tenantId, linha.tenant_id, "o caso sobrevive");
    assert.equal((await segundo.casos.telefoneDe(id))?.revelar(), telefone.replace(/ /g, ""), "o telefone abre");
    assert.equal(await segundo.otp.verificar(id, codigo), "acertou", "o desafio sobrevive");
    assert.equal(await segundo.registo.concluirOtp(id), true);
    assert.equal((await segundo.casos.porId(id))?.fase, "kyc_pendente");

    // A mesma chave, depois do reinício: não cria um segundo caso.
    const repetido = await segundo.registo.inscrever(await pedido(segundo, { nif, telefone, chave }));
    assert.equal(lerReferencia("ticket", repetido.referencia, [ASSINATURA, null], segundo.relogio), id);
    // E outra chave com o mesmo NIF recupera, pela função, em vez de duplicar.
    await segundo.registo.inscrever(await pedido(segundo, { nif, telefone, chave: `kam-236-${randomUUID()}` }));
    const n = await admin.query("SELECT 1 FROM platform.onboarding_case WHERE nif_hmac = (SELECT nif_hmac FROM platform.onboarding_case WHERE id = $1)", [id]);
    assert.equal(n.rowCount, 1, "um caso so");
  });

  it("KAM-236: o kamba_app não lê o caso de outro tenant pela tabela, e as funções só devolvem o caso e o tenant", async () => {
    const m = processo(novoPool());
    const nif = nifDeEnsaio();
    const telefone = telefoneDeEnsaio();
    const aceite = await m.registo.inscrever(await pedido(m, { nif, telefone, chave: `kam-236-${randomUUID()}` }));
    const id = lerReferencia("ticket", aceite.referencia, [ASSINATURA, null], m.relogio);
    casosCriados.push(id);
    const [ligacao] = [await pools.at(-1)!.connect()];
    try {
      const semContexto = await ligacao.query("SELECT count(*)::int AS n FROM platform.onboarding_case WHERE id = $1", [id]);
      assert.equal(semContexto.rows[0].n, 0, "sem contexto, zero linhas");
      const outro = await comTenant(ligacao, randomUUID(), (tx) =>
        tx.query<{ n: number }>("SELECT count(*)::int AS n FROM platform.onboarding_case WHERE id = $1", [id]),
      );
      assert.equal(outro.rows[0]?.n, 0, "com o contexto de outro tenant, zero linhas");
      const caso = await m.casos.porId(id);
      const porNif = await ligacao.query("SELECT * FROM platform.registo_caso_vivo_por_nif($1)", [caso!.nifHmac]);
      assert.deepEqual(porNif.fields.map((f) => f.name), ["id", "tenant_id"], "so o caso e o tenant");
      assert.equal(porNif.rowCount, 1);
      const porTelefone = await ligacao.query("SELECT * FROM platform.registo_casos_vivos_por_telefone($1)", [caso!.telefoneHmac]);
      assert.deepEqual(porTelefone.fields.map((f) => f.name), ["id", "tenant_id"]);
    } finally {
      ligacao.release();
    }
    // Um caso morto deixa de se encontrar pelo NIF.
    await m.casos.marcarFase(id, "abandonado");
    assert.equal(await m.casos.porNifHmac((await m.casos.porId(id))!.nifHmac), null);
  });

  it("KAM-236: vinte anotações de dois processos somam vinte, e o trocarUltimo concorrente devolve null uma vez", async () => {
    const [a, b] = [contadoresNaBase(novoPool() as unknown as PoolDaInscricao), contadoresNaBase(novoPool() as unknown as PoolDaInscricao)];
    const chave = `ensaio:${randomUUID()}`;
    const batida = `ensaio-batida:${randomUUID()}`;
    chavesDosContadores.push(chave, batida);
    const em = new Date();
    await Promise.all(Array.from({ length: 20 }, (_, i) => (i % 2 === 0 ? a : b).anotar(chave, new Date(em.getTime() + i), 3_600_000)));
    assert.equal(await a.contar(chave, new Date(em.getTime() + 100), 3_600_000), 20);
    assert.equal((await b.ultimo(chave))?.getTime(), em.getTime() + 19);
    // Uma janela mais curta não apaga o que a mais longa conta (ver o duplo).
    assert.equal(await b.contar(chave, new Date(em.getTime() + 100), 50), 20);
    const anteriores = await Promise.all(
      Array.from({ length: 10 }, (_, i) => (i % 2 === 0 ? a : b).trocarUltimo(batida, new Date(em.getTime() + i * 1000))),
    );
    assert.equal(anteriores.filter((x) => x === null).length, 1, "so a primeira nao tem anterior");
  });

  it("KAM-236: uma sessão revogada continua revogada depois do reinício, e o corte de um tenant não toca o outro", async () => {
    const [tenantA, tenantB] = [randomUUID(), randomUUID()];
    tenantsDasRevogacoes.push(tenantA, tenantB);
    const agora = Math.floor(Date.now() / 1000);
    const sA = novaSessao(tenantA, randomUUID(), new Date(agora * 1000));
    const sB = novaSessao(tenantB, randomUUID(), new Date(agora * 1000));
    await new RevogacoesNaBase(novoPool() as unknown as PoolDaInscricao).revogar(sA);
    const depois = new RevogacoesNaBase(novoPool() as unknown as PoolDaInscricao);
    assert.equal(await depois.revogada(sA), true, "a revogacao sobrevive");
    assert.equal(await depois.revogada(sB), false);
    await depois.revogarDoTenant(tenantB, agora);
    await depois.revogarDoTenant(tenantB, agora - 10);
    assert.equal(await depois.revogada(sB), true, "o corte so sobe");
    const sA2 = novaSessao(tenantA, randomUUID(), new Date(agora * 1000));
    assert.equal(await depois.revogada(sA2), false, "o corte de B nao toca A");
  });
});
