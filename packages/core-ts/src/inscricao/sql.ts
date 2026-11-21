/**
 * Os adaptadores SQL da inscrição (KAM-236): o caso, o desafio do OTP e os
 * contadores, como `kamba_app`, sobre a revisão `0084`.
 *
 *     casosNaBase        o `RepositorioDeCasos` sobre a `platform.onboarding_case`
 *     otpNaBase          o `RepositorioDeOtp` sobre a `platform.onboarding_otp`
 *     contadoresNaBase   os `Contadores` sobre a `platform.onboarding_contador`
 *
 * ## O tenant do caso, antes de tudo (decisão do fundador de 2026-11-21, D1-A)
 *
 * O `kamba_app` é `NOBYPASSRLS`, e a `tenant_iso` da `onboarding_case` só lhe
 * mostra o tenant do contexto. Mas as portas da inscrição falam por
 * `onboarding_id`, por chave de idempotência ou por HMAC — nunca por tenant,
 * porque **ainda não há tenant**: o `tenant_id` é pré-alocado e único por caso.
 * Por isso cada operação tem dois tempos:
 *
 *     1. uma das cinco funções `SECURITY DEFINER` da `0084` diz qual é o caso e
 *        o tenant dele — e mais nada: nem a fase, nem o NIF, nem o telefone;
 *     2. o `comTenant` desse tenant lê ou escreve a linha **pela RLS**.
 *
 * O segundo tempo volta a filtrar pelo `id`, e o que a função devolveu é só
 * um endereço: uma linha que mudou entre os dois tempos (um caso que morreu)
 * lê-se como está agora, e o adaptador volta a aplicar o predicado do porto
 * (`faseViva`) ao que leu.
 *
 * ## Uma ligação por operação
 *
 * Pela razão do `../dono/sql.ts` (`numaLigacao`): o servidor atende pedidos
 * concorrentes, e o `tenant_guard` recusa a segunda transacção numa ligação
 * partilhada. Uma ligação que falhou destrói-se em vez de voltar ao *pool*.
 *
 * ## A cifra
 *
 * O `nif_enc`, o `phone_enc` e o `email_enc` escrevem-se uma vez, no `INSERT`,
 * com o `id` e o `tenant_id` pré-alocados aqui: o contexto autenticado de cada
 * cifra leva o caso (ver `./telefone_do_caso.ts`). A porta `CifraDoCaso` é o
 * que este módulo pede; quem a monta escolhe as chaves.
 */

import { randomUUID } from "node:crypto";

import type { ClienteSql } from "../screening/sql.ts";
import { comTenant } from "../tenant_guard/index.ts";

import {
  CasoDuplicadoError,
  ChaveReutilizadaError,
  FASES,
  FLAGS,
  ORIGENS,
  faseViva,
  type Caso,
  type CasoNovo,
  type Contadores,
  type DesafioGuardado,
  type Fase,
  type Flag,
  type RepositorioDeCasos,
  type RepositorioDeOtp,
} from "./contrato.ts";
import type { Email, Nif } from "./identificadores.ts";
import { INSTANTES_POR_CHAVE } from "./memoria.ts";
import type { CasoDoTelefone } from "./telefone_do_caso.ts";
import { Telefone } from "./identificadores.ts";

/** Uma ligação de um *pool* `pg`: o `release(true)` destrói-a. */
export interface LigacaoDaInscricao extends ClienteSql {
  release(destruir?: boolean | Error): void;
}

/** O *pool* do `kamba_app`, pela forma do `pg.Pool`. */
export interface PoolDaInscricao {
  connect(): Promise<LigacaoDaInscricao>;
}

/** Corre `trabalho` numa ligação só sua. Ver a nota do módulo. */
export async function numaLigacaoDaInscricao<T>(
  pool: PoolDaInscricao,
  trabalho: (ligacao: LigacaoDaInscricao) => Promise<T>,
): Promise<T> {
  const ligacao = await pool.connect();
  let destruir = false;
  try {
    return await trabalho(ligacao);
  } catch (erro) {
    destruir = true;
    throw erro;
  } finally {
    ligacao.release(destruir);
  }
}

/**
 * As cifras das três colunas do caso. **O valor em claro só entra aqui**, e o
 * `abrirTelefone` devolve `null` em vez de lançar, pela razão do `telefoneDe`.
 */
export interface CifraDoCaso {
  nif(caso: CasoDoTelefone, nif: Nif): Buffer;
  telefone(caso: CasoDoTelefone, telefone: Telefone): Buffer;
  email(caso: CasoDoTelefone, email: Email): Buffer;
  abrirTelefone(caso: CasoDoTelefone, cifra: Uint8Array): string | null;
}

// ------------------------------------------------------------------ as instruções

/** As cinco buscas da `0084`. Só devolvem o caso e o tenant, ou uma contagem. */
export const SQL_TENANT_DO_CASO = "SELECT platform.registo_tenant_do_caso($1::uuid)::text AS tenant_id";
export const SQL_CASO_POR_CHAVE =
  "SELECT id::text AS id, tenant_id::text AS tenant_id FROM platform.registo_caso_por_chave($1)";
export const SQL_CASO_VIVO_POR_NIF =
  "SELECT id::text AS id, tenant_id::text AS tenant_id FROM platform.registo_caso_vivo_por_nif($1)";
export const SQL_CASOS_VIVOS_POR_TELEFONE =
  "SELECT id::text AS id, tenant_id::text AS tenant_id FROM platform.registo_casos_vivos_por_telefone($1)";
export const SQL_CONTAR_POR_DISPOSITIVO = "SELECT platform.registo_contar_por_dispositivo($1, $2) AS n";

const COLUNAS_DO_CASO = `id::text AS id, tenant_id::text AS tenant_id, fase, origem, nome_negocio,
  categoria_declarada, encode(nif_hmac, 'hex') AS nif_hmac, encode(phone_hmac, 'hex') AS phone_hmac,
  encode(device_hash, 'hex') AS device_hash, encode(ip_prefix_hash, 'hex') AS ip_prefix_hash, flags,
  owner_active_seconds, criado_at`;

/** O caso, pela RLS. O `id = $1` é a busca; o tenant é o do contexto. */
export const SQL_LER_CASO = `SELECT ${COLUNAS_DO_CASO} FROM platform.onboarding_case WHERE id = $1`;

/** O `phone_enc` do caso, pela RLS. */
export const SQL_PHONE_ENC = "SELECT phone_enc FROM platform.onboarding_case WHERE id = $1";

/**
 * O caso novo, com as três cifras e a chave de idempotência. A `fase` nasce
 * `registo` pelo `DEFAULT`, e o `criado_at` pelo da base.
 */
export const SQL_CRIAR_CASO = `
  INSERT INTO platform.onboarding_case
    (id, tenant_id, origem, nome_negocio, categoria_declarada, nif_enc, nif_hmac, phone_enc, phone_hmac,
     email_enc, device_hash, ip_prefix_hash, flags, chave_idem)
  VALUES ($1, $2, $3, $4, $5, $6, decode($7, 'hex'), $8, decode($9, 'hex'), $10,
          decode($11, 'hex'), decode($12, 'hex'), $13::text[], $14)
  RETURNING ${COLUNAS_DO_CASO}`;

export const SQL_MARCAR_FASE = "UPDATE platform.onboarding_case SET fase = $2 WHERE id = $1 RETURNING id";

export const SQL_ACRESCENTAR_FLAG = `
  UPDATE platform.onboarding_case
     SET flags = CASE WHEN $2 = ANY (flags) THEN flags ELSE array_append(flags, $2) END
   WHERE id = $1 RETURNING id`;

export const SQL_ACUMULAR_ACTIVO = `
  UPDATE platform.onboarding_case SET owner_active_seconds = owner_active_seconds + $2
   WHERE id = $1 RETURNING owner_active_seconds`;

/** Os dois índices únicos que um `INSERT` do caso pode bater. */
const INDICE_DO_NIF = "onboarding_nif_vivo";
const INDICE_DA_CHAVE = "onboarding_case_chave_idem_uq";

// ------------------------------------------------------------------ a leitura

type Linha = Readonly<Record<string, unknown>>;

async function linhas(bd: ClienteSql, sql: string, parametros: readonly unknown[]): Promise<readonly Linha[]> {
  const { rows } = await bd.query<Linha>(sql, parametros);
  return rows;
}

function textoOuNulo(valor: unknown): string | null {
  return typeof valor === "string" && valor !== "" ? valor : null;
}

function instante(valor: unknown): Date {
  return valor instanceof Date ? valor : new Date(String(valor));
}

/** Um valor de uma lista fechada, ou um erro: a base e o domínio divergiram. */
function deLista<T extends string>(lista: readonly T[], valor: unknown, nome: string): T {
  if (typeof valor === "string" && (lista as readonly string[]).includes(valor)) return valor as T;
  throw new Error(`o ${nome} lido da base nao esta no dominio`);
}

function casoDe(l: Linha): Caso {
  const flags = Array.isArray(l["flags"]) ? l["flags"] : [];
  return {
    id: String(l["id"]),
    tenantId: String(l["tenant_id"]),
    fase: deLista(FASES, l["fase"], "fase"),
    origem: deLista(ORIGENS, l["origem"], "origem"),
    nomeNegocio: String(l["nome_negocio"]),
    categoriaDeclarada: String(l["categoria_declarada"]),
    nifHmac: String(l["nif_hmac"]),
    telefoneHmac: String(l["phone_hmac"]),
    dispositivoHmac: textoOuNulo(l["device_hash"]),
    redeHmac: textoOuNulo(l["ip_prefix_hash"]),
    flags: flags.map((f) => deLista(FLAGS, f, "flag")),
    activoSegundos: Number(l["owner_active_seconds"]),
    criadoEm: instante(l["criado_at"]),
  };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const HMAC = /^[0-9a-f]{64}$/;

/** Um `onboarding_id` que não é UUID não se procura: a base dava `22P02`. */
function idValido(id: string): boolean {
  return typeof id === "string" && UUID.test(id.toLowerCase());
}

function codigoPg(erro: unknown): { code?: string; constraint?: string } {
  return typeof erro === "object" && erro !== null ? (erro as { code?: string; constraint?: string }) : {};
}

// ------------------------------------------------------------------ os casos

/** O que o `casosNaBase` precisa para montar. */
export interface OpcoesDosCasos {
  readonly pool: PoolDaInscricao;
  readonly cifra: CifraDoCaso;
  /** O anel do *pepper* da inscrição: o `telefoneDe` volta a cunhar o `Telefone`. */
  readonly anelDoPepper: readonly (Uint8Array | null)[];
}

/** O `RepositorioDeCasos` sobre a base. Ver a nota do módulo. */
export function casosNaBase(o: OpcoesDosCasos): RepositorioDeCasos {
  const { pool, cifra } = o;

  /** O tenant de um caso, pela função; `null` se o caso não existe. */
  const tenantDe = async (bd: ClienteSql, id: string): Promise<string | null> => {
    if (!idValido(id)) return null;
    const [l] = await linhas(bd, SQL_TENANT_DO_CASO, [id]);
    return textoOuNulo(l?.["tenant_id"]);
  };

  /** Lê o caso `id` do tenant `tenant`, pela RLS. */
  const ler = (bd: ClienteSql, tenant: string, id: string): Promise<Caso | null> =>
    comTenant(bd, tenant, async (tx) => {
      const [l] = await linhas(tx, SQL_LER_CASO, [id]);
      return l === undefined ? null : casoDe(l);
    });

  /** Os casos de pares `(id, tenant)` que uma busca devolveu, um a um. */
  const lerPares = async (bd: ClienteSql, pares: readonly Linha[]): Promise<Caso[]> => {
    const casos: Caso[] = [];
    for (const par of pares) {
      const caso = await ler(bd, String(par["tenant_id"]), String(par["id"]));
      if (caso !== null) casos.push(caso);
    }
    return casos;
  };

  /** Escreve no caso `id` pela RLS do seu tenant; `null` se o caso não existe. */
  const noCaso = <T>(id: string, trabalho: (tx: ClienteSql) => Promise<T>): Promise<T | null> =>
    numaLigacaoDaInscricao(pool, async (bd) => {
      const tenant = await tenantDe(bd, id);
      return tenant === null ? null : comTenant(bd, tenant, trabalho);
    });

  const porChave = (chave: string): Promise<Caso | null> =>
    numaLigacaoDaInscricao(pool, async (bd) => {
      if (typeof chave !== "string" || chave === "") return null;
      const [par] = await linhas(bd, SQL_CASO_POR_CHAVE, [chave]);
      return par === undefined ? null : ler(bd, String(par["tenant_id"]), String(par["id"]));
    });

  const porNifHmac = (hmac: string): Promise<Caso | null> =>
    numaLigacaoDaInscricao(pool, async (bd) => {
      if (!HMAC.test(hmac)) return null;
      const pares = await linhas(bd, SQL_CASO_VIVO_POR_NIF, [hmac]);
      // O índice único dá no máximo um vivo. O `faseViva` repete o predicado
      // sobre o que a RLS leu: o caso pode ter morrido entre os dois tempos.
      const [caso] = (await lerPares(bd, pares)).filter((c) => faseViva(c.fase));
      return caso ?? null;
    });

  return {
    porId: (id) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        const tenant = await tenantDe(bd, id);
        return tenant === null ? null : ler(bd, tenant, id);
      }),

    telefoneDe: (id) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        const tenant = await tenantDe(bd, id);
        if (tenant === null) return null;
        const enc = await comTenant(bd, tenant, async (tx) => (await linhas(tx, SQL_PHONE_ENC, [id]))[0]?.["phone_enc"]);
        if (!(enc instanceof Uint8Array)) return null;
        const claro = cifra.abrirTelefone({ tenantId: tenant, onboardingId: id }, enc);
        if (claro === null) return null;
        try {
          return new Telefone(claro, o.anelDoPepper);
        } catch {
          return null;
        }
      }),

    porChave,
    porNifHmac,

    porTelefoneHmac: (hmac) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        if (!HMAC.test(hmac)) return [];
        const pares = await linhas(bd, SQL_CASOS_VIVOS_POR_TELEFONE, [hmac]);
        return (await lerPares(bd, pares)).filter((c) => faseViva(c.fase));
      }),

    contarPorDispositivo: (hmac, desde) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        if (!HMAC.test(hmac)) return 0;
        const [l] = await linhas(bd, SQL_CONTAR_POR_DISPOSITIVO, [hmac, desde]);
        return Number(l?.["n"] ?? 0);
      }),

    async criar(novo: CasoNovo, chave: string) {
      const repetir = async (): Promise<{ readonly caso: Caso; readonly repetido: boolean } | null> => {
        const jaCriado = await porChave(chave);
        if (jaCriado === null) return null;
        // **A chave prende-se ao corpo**, como no duplo: ver `ChaveReutilizadaError`.
        if (jaCriado.nifHmac !== novo.nif.hmac) throw new ChaveReutilizadaError();
        return { caso: jaCriado, repetido: true };
      };

      const jaCriado = await repetir();
      if (jaCriado !== null) return jaCriado;
      if ((await porNifHmac(novo.nif.hmac)) !== null) throw new CasoDuplicadoError();

      // O `id` pré-aloca-se aqui e não no `DEFAULT`: as três cifras levam-no no
      // contexto autenticado, e precisam dele antes de a linha existir.
      const id = randomUUID();
      const caso: CasoDoTelefone = { tenantId: novo.tenantId, onboardingId: id };
      const valores = [
        id,
        novo.tenantId,
        novo.origem,
        novo.nomeNegocio,
        novo.categoriaDeclarada,
        cifra.nif(caso, novo.nif),
        novo.nif.hmac,
        cifra.telefone(caso, novo.telefone),
        novo.telefone.hmac,
        novo.email === null ? null : cifra.email(caso, novo.email),
        novo.dispositivoHmac,
        novo.redeHmac,
        [...novo.flags],
        chave,
      ];
      try {
        const criado = await numaLigacaoDaInscricao(pool, (bd) =>
          comTenant(bd, novo.tenantId, async (tx) => {
            const [l] = await linhas(tx, SQL_CRIAR_CASO, valores);
            if (l === undefined) throw new Error("o INSERT do caso nao devolveu a linha");
            return casoDe(l);
          }),
        );
        return { caso: criado, repetido: false };
      } catch (erro) {
        const { code, constraint } = codigoPg(erro);
        if (code !== "23505") throw erro;
        // **A corrida de dois pedidos**, com o índice a decidir. Pelo NIF: o
        // outro criou o caso vivo primeiro, e o `Registo` recupera. Pela chave:
        // o outro pedido é este repetido, e responde-se o que ele criou.
        if (constraint === INDICE_DO_NIF) throw new CasoDuplicadoError();
        if (constraint === INDICE_DA_CHAVE) {
          const outro = await repetir();
          if (outro !== null) return outro;
        }
        throw erro;
      }
    },

    async marcarFase(id: string, fase: Fase) {
      const r = await noCaso(id, (tx) => linhas(tx, SQL_MARCAR_FASE, [id, fase]));
      return r !== null && r.length > 0;
    },

    async acrescentarFlag(id: string, flag: Flag) {
      const r = await noCaso(id, (tx) => linhas(tx, SQL_ACRESCENTAR_FLAG, [id, flag]));
      return r !== null && r.length > 0;
    },

    async acumularActivo(id: string, segundos: number) {
      const somar = Math.max(0, Math.trunc(Number.isFinite(segundos) ? segundos : 0));
      const r = await noCaso(id, (tx) => linhas(tx, SQL_ACUMULAR_ACTIVO, [id, somar]));
      return r === null || r[0] === undefined ? 0 : Number(r[0]["owner_active_seconds"]);
    },
  };
}

// ------------------------------------------------------------------ o desafio do OTP

/** Guarda o desafio, substituindo o que lá estiver e voltando a pô-lo por usar. */
export const SQL_GUARDAR_DESAFIO = `
  INSERT INTO platform.onboarding_otp (onboarding_id, tenant_id, codigo_hmac, expira_at, tentativas)
  VALUES ($1, $2, $3, $4, $5)
  ON CONFLICT (onboarding_id) DO UPDATE
     SET codigo_hmac = EXCLUDED.codigo_hmac, expira_at = EXCLUDED.expira_at,
         tentativas = EXCLUDED.tentativas, usado_at = NULL`;

/** Um desafio usado não se lê: é o «apagado» da porta. */
export const SQL_DESAFIO_ACTUAL = `
  SELECT codigo_hmac, expira_at, tentativas FROM platform.onboarding_otp
   WHERE onboarding_id = $1 AND usado_at IS NULL`;

export const SQL_SOMAR_TENTATIVA = `
  UPDATE platform.onboarding_otp SET tentativas = tentativas + 1
   WHERE onboarding_id = $1 AND usado_at IS NULL RETURNING tentativas`;

/**
 * O `apagar` da porta **não apaga** (dicionário §2: «estado, nunca `DELETE`»;
 * o `kamba_app` não tem `DELETE` em tabela nenhuma): marca o desafio usado.
 */
export const SQL_APAGAR_DESAFIO = `
  UPDATE platform.onboarding_otp SET usado_at = now()
   WHERE onboarding_id = $1 AND usado_at IS NULL`;

/**
 * O `RepositorioDeOtp` sobre a base: um desafio por caso, na RLS do tenant do
 * caso. Um `onboarding_id` que não existe não guarda nada (a FK recusava-o, e
 * é o caso que manda), e lê-se como «sem desafio».
 */
export function otpNaBase(pool: PoolDaInscricao): RepositorioDeOtp {
  const noCaso = <T>(id: string, trabalho: (tx: ClienteSql, tenant: string) => Promise<T>): Promise<T | null> =>
    numaLigacaoDaInscricao(pool, async (bd) => {
      if (!idValido(id)) return null;
      const [l] = await linhas(bd, SQL_TENANT_DO_CASO, [id]);
      const tenant = textoOuNulo(l?.["tenant_id"]);
      return tenant === null ? null : comTenant(bd, tenant, (tx) => trabalho(tx, tenant));
    });

  return {
    async guardar(d: DesafioGuardado) {
      await noCaso(d.onboardingId, async (tx, tenant) => {
        await tx.query(SQL_GUARDAR_DESAFIO, [d.onboardingId, tenant, d.codigoHmac, d.expiraEm, d.tentativas]);
      });
    },
    async actual(onboardingId: string) {
      const r = await noCaso(onboardingId, (tx) => linhas(tx, SQL_DESAFIO_ACTUAL, [onboardingId]));
      const l = r?.[0];
      if (l === undefined) return null;
      return {
        onboardingId,
        codigoHmac: String(l["codigo_hmac"]),
        expiraEm: instante(l["expira_at"]),
        tentativas: Number(l["tentativas"]),
      };
    },
    async somarTentativa(onboardingId: string) {
      const r = await noCaso(onboardingId, (tx) => linhas(tx, SQL_SOMAR_TENTATIVA, [onboardingId]));
      const l = r?.[0];
      return l === undefined ? null : Number(l["tentativas"]);
    },
    async apagar(onboardingId: string) {
      await noCaso(onboardingId, async (tx) => {
        await tx.query(SQL_APAGAR_DESAFIO, [onboardingId]);
      });
    },
  };
}

// ------------------------------------------------------------------ os contadores

/**
 * Quanto tempo uma chave parada fica antes de a retenção a apagar (a classe
 * `contadores_do_registo`, como lote: o `kamba_app` não apaga linhas). A maior
 * janela perguntada é a do orçamento e a do dispositivo (24 h); uma hora de folga.
 */
export const PARADA_MS = 25 * 3_600_000;

/**
 * Anota `em` e poda pela janela de quem anota, **numa instrução**: o `ON
 * CONFLICT DO UPDATE` tranca a linha, e duas anotações concorrentes da mesma
 * chave somam-se. O tecto corta os mais antigos, como o duplo.
 */
export const SQL_ANOTAR = `
  INSERT INTO platform.onboarding_contador AS c (chave, instantes, actualizado_at)
  VALUES ($1, ARRAY[$2::timestamptz], $2)
  ON CONFLICT (chave) DO UPDATE
     SET instantes = (
           SELECT coalesce(array_agg(t ORDER BY t), '{}')
             FROM (SELECT t FROM unnest(array_append(c.instantes, $2::timestamptz)) AS t
                    WHERE t > $3::timestamptz
                    ORDER BY t DESC LIMIT ${INSTANTES_POR_CHAVE}) AS vivos),
         actualizado_at = greatest(c.actualizado_at, $2)
  RETURNING cardinality(instantes) AS n`;

/** Quantos há na janela. **Não escreve nada** (ver o duplo). */
export const SQL_CONTAR = `
  SELECT count(*)::integer AS n
    FROM platform.onboarding_contador c, unnest(c.instantes) AS t
   WHERE c.chave = $1 AND t > $2::timestamptz`;

/** O último registado, sem janela (ver o duplo). */
export const SQL_ULTIMO = `
  SELECT (SELECT max(t) FROM unnest(c.instantes) AS t) AS ultimo
    FROM platform.onboarding_contador c WHERE c.chave = $1`;

/** A linha, garantida, para o `trocarUltimo` a trancar. */
export const SQL_GARANTIR_CHAVE = `
  INSERT INTO platform.onboarding_contador (chave, instantes, actualizado_at)
  VALUES ($1, '{}', $2) ON CONFLICT (chave) DO NOTHING`;

export const SQL_TRANCAR_ULTIMO = `
  SELECT (SELECT max(t) FROM unnest(c.instantes) AS t) AS ultimo
    FROM platform.onboarding_contador c WHERE c.chave = $1 FOR UPDATE`;

export const SQL_SO_ESTE = `
  UPDATE platform.onboarding_contador SET instantes = ARRAY[$2::timestamptz], actualizado_at = $2
   WHERE chave = $1`;

/**
 * Os `Contadores` sobre a base. **Sem tenant** (a tabela não tem), e sem
 * `comTenant`: o `anotar`, o `contar` e o `ultimo` são uma instrução cada, e o
 * `trocarUltimo` é uma transacção com a linha trancada — a atomicidade que a
 * porta exige (`./contrato.ts`). **Não apaga nada**: as chaves paradas há mais
 * de `PARADA_MS` saem pela retenção, como lote.
 */
export function contadoresNaBase(pool: PoolDaInscricao): Contadores {
  return {
    anotar: (chave, em, janelaMs) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        const [l] = await linhas(bd, SQL_ANOTAR, [chave, em, new Date(em.getTime() - janelaMs)]);
        return Number(l?.["n"] ?? 0);
      }),
    contar: (chave, em, janelaMs) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        const [l] = await linhas(bd, SQL_CONTAR, [chave, new Date(em.getTime() - janelaMs)]);
        return Number(l?.["n"] ?? 0);
      }),
    ultimo: (chave) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        const [l] = await linhas(bd, SQL_ULTIMO, [chave]);
        return l === undefined || l["ultimo"] === null || l["ultimo"] === undefined ? null : instante(l["ultimo"]);
      }),
    trocarUltimo: (chave, em) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        await bd.query("BEGIN");
        try {
          await bd.query(SQL_GARANTIR_CHAVE, [chave, em]);
          const [l] = await linhas(bd, SQL_TRANCAR_ULTIMO, [chave]);
          await bd.query(SQL_SO_ESTE, [chave, em]);
          await bd.query("COMMIT");
          return l === undefined || l["ultimo"] === null || l["ultimo"] === undefined ? null : instante(l["ultimo"]);
        } catch (erro) {
          await bd.query("ROLLBACK").catch(() => undefined);
          throw erro;
        }
      }),
  };
}
