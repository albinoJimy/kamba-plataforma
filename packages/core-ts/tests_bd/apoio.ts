/**
 * Apoio dos testes de identidade contra um PostgreSQL real (KAM-008).
 *
 * Estes testes **não correm no gate 4**: precisam da base descartável que
 * `db/gate_bd.py --suite tests_identidade` levanta, com os papéis criados e as
 * migrações em `head`. Quem os corre é `db/tests_identidade/`, que também lê o
 * que eles deixam (os canários e a cobertura).
 *
 * Nada aqui é um dado real: os BSUID são `AO.CANARIO…`/`AO.ENSAIO…` e os
 * telefones usam o indicativo `999`, que a UIT não atribui a nenhum país.
 */

import { randomBytes, randomInt, randomUUID } from "node:crypto";

import pg from "pg";

import {
  type ClienteDeIdentidade,
  EnvKeyProvider,
  Identidade,
  type ResultadoSql,
  gerarChaveVersionada,
} from "../src/identity/index.ts";
import {
  ambienteDeChaves,
  definirPesquisa,
  esquecerPesquisaAnterior,
  rodarPesquisa,
} from "../tests/identity.ambiente.ts";

/** A base em que estes testes aceitam correr. O mesmo trinco de `db/tests/base.py`. */
export const BASE_DESCARTAVEL = "kamba_gate8";

export type Papel = "admin" | "identity" | "app" | "batch" | "resolver";

const VARIAVEL_DA_SENHA: Record<Papel, string> = {
  admin: "POSTGRES_PASSWORD",
  identity: "KAMBA_SECRET_DB_IDENTITY_PASSWORD",
  app: "KAMBA_SECRET_DB_APP_PASSWORD",
  batch: "KAMBA_SECRET_DB_BATCH_PASSWORD",
  // KAM-014: o papel do CHR. E o unico que responde
  // `phone_number_id -> tenant` antes de haver contexto.
  resolver: "KAMBA_SECRET_DB_RESOLVER_PASSWORD",
};

const UTILIZADOR: Record<Exclude<Papel, "admin">, string> = {
  identity: "kamba_identity",
  app: "kamba_app",
  batch: "kamba_batch",
  resolver: "kamba_resolver",
};

function exigir(nome: string): string {
  const valor = process.env[nome] ?? "";
  if (valor === "") {
    throw new Error(`a variável de ambiente ${nome} não está definida`);
  }
  return valor;
}

/** Abre uma ligação com o papel pedido. Recusa qualquer base que não seja a descartável. */
export async function ligar(papel: Papel): Promise<pg.Client> {
  const base = exigir("KAMBA_DB_NAME");
  if (base !== BASE_DESCARTAVEL) {
    throw new Error(
      `KAMBA_DB_NAME não é ${BASE_DESCARTAVEL}: estes testes escrevem e apagam, ` +
        "e só correm contra a base descartável do gate",
    );
  }
  const cliente = new pg.Client({
    host: process.env.KAMBA_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.KAMBA_DB_PORT ?? "5432"),
    database: base,
    user: papel === "admin" ? exigir("POSTGRES_USER") : UTILIZADOR[papel],
    password: exigir(VARIAVEL_DA_SENHA[papel]),
    application_name: `kamba-identidade-teste:${papel}`,
  });
  await cliente.connect();
  return cliente;
}

/**
 * O ambiente de chaves dos testes: um objecto que se pode alterar a meio, para
 * ensaiar a rotação sem tocar em `process.env`.
 */
export class ChavesDeTeste {
  readonly env: Record<string, string>;

  constructor(kid: string, epocas: readonly string[] = []) {
    this.env = ambienteDeChaves({
      ambiente: "dev",
      pesquisa: [gerarChaveVersionada(kid)],
      kek: [gerarChaveVersionada("kek-1")],
      epocas: Object.fromEntries(
        epocas.map((epoca) => [epoca, randomBytes(32).toString("base64")]),
      ),
    });
  }

  /** O cofre passa a ter `kid` como versão actual; a que era actual fica como anterior. */
  rodar(kid: string): void {
    rodarPesquisa(this.env, gerarChaveVersionada(kid));
  }

  /** O cofre deixa de ter a versão anterior. */
  esquecerAnterior(): void {
    esquecerPesquisaAnterior(this.env);
  }

  /** Desfaz um `rodar`: a que era anterior volta a ser a actual, e não fica anterior. */
  desfazerRodar(): void {
    const anterior = esquecerPesquisaAnterior(this.env);
    if (anterior !== undefined) definirPesquisa(this.env, anterior);
  }

  provedor(): EnvKeyProvider {
    return new EnvKeyProvider({ ambiente: "dev", env: this.env });
  }

  async identidade(): Promise<Identidade> {
    return Identidade.arrancar({ chaves: this.provedor(), env: this.env });
  }
}

/** Cria um tenant de ensaio (como administrador) e devolve o `id`. */
export async function criarTenant(admin: pg.Client, rotulo: string): Promise<string> {
  const id = randomUUID();
  await admin.query("INSERT INTO platform.tenants (id, tipo, nome) VALUES ($1, 'pme', $2)", [
    id,
    `Loja de ensaio ${rotulo} ${id.slice(0, 8)}`,
  ]);
  return id;
}

/**
 * Cria um canal de ensaio e devolve o `id` e o `phone_number_id` (KAM-014).
 *
 * O `phone_number_id` e unico em toda a plataforma
 * (`tenant_channels_phone_number_id_uq`, revisao `0001`), e e isso que torna a
 * resolucao deterministica: nao ha duas linhas onde escolher.
 */
export async function criarCanal(
  admin: pg.Client,
  tenant: string,
  troca: {
    readonly vertical?: string;
    readonly origem?: string;
    readonly estado?: string;
    readonly channelMode?: string;
  } = {},
): Promise<{ readonly id: string; readonly phoneNumberId: string }> {
  const phoneNumberId = `pnid-${randomUUID()}`;
  const { rows } = await admin.query(
    "INSERT INTO platform.tenant_channels " +
      "(tenant_id, waba_id, phone_number_id, channel_mode, vertical, origem, estado, token_ref) " +
      "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id::text AS id",
    [
      tenant,
      `waba-${randomUUID().slice(0, 8)}`,
      phoneNumberId,
      troca.channelMode ?? "coexistencia",
      troca.vertical ?? "vendedor",
      troca.origem ?? "pme",
      troca.estado ?? "ativo",
      `ref-opaca/${randomUUID()}`,
    ],
  );
  return { id: (rows[0] as { id: string }).id, phoneNumberId };
}

/** As conversas de um tenant, vistas pelo administrador. */
export async function conversasDe(
  admin: pg.Client,
  tenant: string,
): Promise<
  readonly {
    readonly id: string;
    readonly contact_id: string;
    readonly channel_id: string;
    readonly mode: string;
    readonly last_inbound_at: Date | null;
    readonly window_expires_at: Date | null;
    readonly last_human_activity_at: Date | null;
  }[]
> {
  const { rows } = await admin.query(
    "SELECT id::text AS id, contact_id::text AS contact_id, " +
      "channel_id::text AS channel_id, mode, last_inbound_at, window_expires_at, " +
      "last_human_activity_at FROM platform.conversations " +
      "WHERE tenant_id = $1 ORDER BY channel_id, id",
    [tenant],
  );
  return rows as never;
}

/** Apaga tudo o que um tenant de ensaio tem, pela ordem das FK. */
export async function apagarTenant(admin: pg.Client, tenant: string): Promise<void> {
  await admin.query("UPDATE platform.tenants SET owner_contact_id = NULL WHERE id = $1", [tenant]);
  // KAM-014: antes dos contactos e dos canais, que ela referencia.
  await admin.query("DELETE FROM platform.conversations WHERE tenant_id = $1", [tenant]);
  await admin.query("DELETE FROM platform.unrouted_events WHERE motivo IN ('canal_desconhecido', 'mensagem_sem_identidade')");
  await admin.query("DELETE FROM platform.tenant_channels WHERE tenant_id = $1", [tenant]);
  await admin.query("DELETE FROM platform.contact_endpoints WHERE tenant_id = $1", [tenant]);
  await admin.query("DELETE FROM platform.contact_deks WHERE tenant_id = $1", [tenant]);
  await admin.query(
    "UPDATE platform.contacts SET merged_into = NULL, merged_at = NULL WHERE tenant_id = $1",
    [tenant],
  );
  await admin.query("DELETE FROM platform.contacts WHERE tenant_id = $1", [tenant]);
  await admin.query("DELETE FROM platform.tenants WHERE id = $1", [tenant]);
}

const ALFABETO = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

function alfanumerico(comprimento: number): string {
  let saida = "";
  for (let i = 0; i < comprimento; i += 1) saida += ALFABETO[randomInt(ALFABETO.length)];
  return saida;
}

/** Um BSUID sintético com a forma que a Meta documenta (`E1` §3): `AO.` + alfanuméricos. */
export function bsuidDeEnsaio(marca = "ENSAIO"): string {
  return `AO.${marca}${alfanumerico(24)}`;
}

/** Um telefone sintético: indicativo `999` (não atribuído) e nove algarismos. */
export function telefoneDeEnsaio(): string {
  return `999${String(randomInt(100_000_000, 999_999_999))}`;
}

/** Um prazo de retenção no futuro, para os testes que guardam o telefone. */
export function daquiAUmAno(): Date {
  return new Date(Date.now() + 365 * 24 * 60 * 60 * 1000);
}

/** Uma instrução vista pelo espião: o texto e os parâmetros, tal como foram para a base. */
export interface Vista {
  readonly sql: string;
  readonly parametros: readonly unknown[];
}

/**
 * Um cliente que regista tudo o que passa para a base, e que pode falhar de
 * propósito numa instrução escolhida — é assim que se ensaia a «falha a meio».
 */
export class ClienteEspiao implements ClienteDeIdentidade {
  readonly vistas: Vista[] = [];
  /** Se definido, a instrução com este texto exacto lança em vez de correr. */
  falharEm: string | null = null;
  /**
   * Se definido, a instrução com este texto pára **antes** de ir para a base,
   * até `continuar()` ser chamado. `parado` resolve quando lá chegou.
   */
  pararAntesDe: string | null = null;
  readonly parado: Promise<void>;
  #chegou: () => void = () => {};
  #largar: () => void = () => {};
  readonly #espera: Promise<void>;
  readonly #cliente: pg.Client;

  constructor(cliente: pg.Client) {
    this.#cliente = cliente;
    this.parado = new Promise((resolver) => {
      this.#chegou = resolver;
    });
    this.#espera = new Promise((resolver) => {
      this.#largar = resolver;
    });
  }

  /** Deixa seguir a instrução que estava parada em `pararAntesDe`. */
  continuar(): void {
    this.#largar();
  }

  async query(sql: string, parametros: readonly unknown[] = []): Promise<ResultadoSql> {
    this.vistas.push({ sql, parametros });
    if (this.falharEm !== null && sql === this.falharEm) {
      throw new Error("falha de ensaio a meio da transacção");
    }
    if (this.pararAntesDe !== null && sql === this.pararAntesDe) {
      this.pararAntesDe = null;
      this.#chegou();
      await this.#espera;
    }
    return this.#cliente.query(sql, [...parametros]);
  }

  /** Tudo o que foi para a base, como texto: é aqui que se procura um canário. */
  emTexto(): string {
    return this.vistas
      .map(({ sql, parametros }) =>
        [
          sql,
          ...parametros.map((p) =>
            p instanceof Uint8Array ? Buffer.from(p).toString("latin1") : String(p),
          ),
        ].join("\u0000"),
      )
      .join("\n");
  }
}

/** Contagens das tabelas de identidade de um tenant, vistas pelo administrador. */
export async function contar(
  admin: pg.Client,
  tenant: string,
): Promise<{ contactos: number; endpoints: number; deks: number }> {
  const { rows } = await admin.query(
    "SELECT " +
      "(SELECT count(*) FROM platform.contacts WHERE tenant_id = $1)::int AS contactos, " +
      "(SELECT count(*) FROM platform.contact_endpoints WHERE tenant_id = $1)::int AS endpoints, " +
      "(SELECT count(*) FROM platform.contact_deks WHERE tenant_id = $1)::int AS deks",
    [tenant],
  );
  return rows[0] as { contactos: number; endpoints: number; deks: number };
}

/** Uma fotografia das três tabelas de um tenant, para comparar antes e depois. */
export async function fotografia(admin: pg.Client, tenant: string): Promise<string> {
  const partes: string[] = [];
  for (const [tabela, ordem] of [
    ["contacts", "contact_id"],
    ["contact_deks", "dek_id"],
    ["contact_endpoints", "id"],
  ] as const) {
    const { rows } = await admin.query(
      `SELECT * FROM platform.${tabela} WHERE tenant_id = $1 ORDER BY ${ordem}`,
      [tenant],
    );
    partes.push(
      JSON.stringify(rows, (_chave, valor: unknown) =>
        valor !== null &&
        typeof valor === "object" &&
        (valor as { type?: unknown }).type === "Buffer"
          ? Buffer.from((valor as { data: number[] }).data).toString("hex")
          : valor,
      ),
    );
  }
  return partes.join("\n");
}

/** Corre `trabalho` sobre `itens` com `n` execuções em paralelo, cada uma com o seu cliente. */
export async function emParalelo<T>(
  clientes: readonly pg.Client[],
  itens: readonly T[],
  trabalho: (cliente: pg.Client, item: T, indice: number) => Promise<void>,
): Promise<void> {
  let proximo = 0;
  await Promise.all(
    clientes.map(async (cliente) => {
      for (;;) {
        const indice = proximo;
        proximo += 1;
        const item = itens[indice];
        if (item === undefined) return;
        await trabalho(cliente, item, indice);
      }
    }),
  );
}
