/**
 * Os adaptadores SQL do passo guiado do ES (KAM-239), sobre a revisão do guia na
 * base.
 *
 *     guiaNaBase         o `RepositorioDoGuia` sobre a `platform.onboarding_guia`,
 *                        como `kamba_app` (o `onboarding-web`)
 *     gatesDoGuiaNaBase  os dois *gates* do guia na `platform.onboarding_gate`,
 *                        como `kamba_batch` (o `onboarding-lote`)
 *     abandonarVencidosNaBase   a volta dos 30 minutos, como `kamba_batch`
 *
 * ## O tenant do caso, antes de tudo (a forma da D1-A do KAM-236)
 *
 * O `kamba_app` é `NOBYPASSRLS`, e a porta do guia fala por `onboarding_id` ou por
 * `phone_number_id`. Cada operação tem por isso os dois tempos do
 * `../inscricao/sql.ts`: uma função `SECURITY DEFINER` diz qual é o caso e o
 * tenant dele — a `registo_tenant_do_caso` da `0084`, ou a
 * `guia_caso_por_phone_number_id` da revisão do guia —, e o `comTenant` desse
 * tenant lê ou escreve a linha pela RLS. Uma ligação do *pool* por operação, pela
 * razão escrita lá.
 *
 * ## As duas varreduras que atravessam tenants (decisão de 2026-11-22)
 *
 * O `porPhoneNumberId` passa pela função acima. O `iniciadosAntesDe` **não corre
 * aqui**: o abandono dos 30 minutos é do processo de lote, como `kamba_batch`
 * (`abandonarVencidosNaBase`), e uma volta por processo do `onboarding-web` era
 * uma volta por réplica. Chamado sobre este adaptador, recusa pelo nome
 * (`VarreduraNoLoteError`) em vez de devolver uma lista vazia, que parecia certa.
 *
 * ## O pré-voo
 *
 * Os sete itens vivem na `onboarding_case.preflight` (o array do bloco do
 * KAM-093, `onboarding_case_preflight_ck`), que o `kamba_app` actualiza desde a
 * `0043`. O `podeAbrir` e a `rota` **não** se guardam: derivam dos itens pela
 * mesma regra do `avaliarPreflight`, para que não possam divergir deles. O
 * instante da avaliação vai no `preflight_at` do guia.
 */

import { comTenant, type ClienteSql } from "../tenant_guard/index.ts";
import {
  linhas,
  numaLigacaoDaInscricao,
  SQL_TENANT_DO_CASO,
  type PoolDaInscricao,
} from "../inscricao/sql.ts";
import {
  DETALHES,
  ESTADOS_DO_GUIA,
  ITENS_DO_PREFLIGHT,
  MOTIVOS_DE_FALHA,
  TIPO_DO_ITEM,
  type EstadoDoGuia,
  type EstadoGuardado,
  type GateDoEs,
  type GatesDoOnboarding,
  type ItemAvaliado,
  type Preflight,
  type RepositorioDoGuia,
} from "./contrato.ts";

// ------------------------------------------------------------------ as instruções

/** A busca pelo número ligado. Só devolve o caso e o tenant, e um só. */
export const SQL_CASO_POR_NUMERO =
  "SELECT id::text AS id, tenant_id::text AS tenant_id FROM platform.guia_caso_por_phone_number_id($1)";

const COLUNAS_DO_GUIA = `g.onboarding_id::text AS onboarding_id, g.estado, g.preflight_at, g.iniciado_at,
  g.motivo, g.tentativa_id, g.phone_number_id, g.waba_id, g.numero_confirmado, g.sincronizado,
  g.actualizado_at, c.preflight`;

/** O guia e o pré-voo do caso, pela RLS. */
export const SQL_LER_GUIA = `SELECT ${COLUNAS_DO_GUIA}
  FROM platform.onboarding_guia g JOIN platform.onboarding_case c ON c.id = g.onboarding_id
 WHERE g.onboarding_id = $1`;

/** O guia nasce em `pre_voo` pelo `DEFAULT`, uma vez. */
export const SQL_ABRIR_GUIA = `INSERT INTO platform.onboarding_guia (onboarding_id, tenant_id)
  VALUES ($1, $2) ON CONFLICT (onboarding_id) DO NOTHING`;

export const SQL_GRAVAR_PREFLIGHT_DO_CASO = "UPDATE platform.onboarding_case SET preflight = $2::jsonb WHERE id = $1";

export const SQL_GRAVAR_PREFLIGHT_DO_GUIA = `UPDATE platform.onboarding_guia
   SET preflight_at = $2, actualizado_at = now() WHERE onboarding_id = $1`;

/**
 * A transição, *compare-and-set* sobre o estado (`$2`). Cada campo opcional vem
 * em par — se veio, e o valor —, porque o `null` é um valor que se escreve (o
 * `iniciar` limpa o `motivo` e o número da tentativa anterior).
 */
export const SQL_TRANSITAR_GUIA = `UPDATE platform.onboarding_guia SET
  estado = $3,
  iniciado_at = CASE WHEN $4::boolean THEN $5::timestamptz ELSE iniciado_at END,
  motivo = CASE WHEN $6::boolean THEN $7::text ELSE motivo END,
  tentativa_id = CASE WHEN $8::boolean THEN $9::text ELSE tentativa_id END,
  phone_number_id = CASE WHEN $10::boolean THEN $11::text ELSE phone_number_id END,
  waba_id = CASE WHEN $12::boolean THEN $13::text ELSE waba_id END,
  numero_confirmado = CASE WHEN $14::boolean THEN $15::boolean ELSE numero_confirmado END,
  sincronizado = CASE WHEN $16::boolean THEN $17::boolean ELSE sincronizado END,
  actualizado_at = now()
 WHERE onboarding_id = $1 AND estado = $2`;

export const SQL_MARCAR_NUMERO = `UPDATE platform.onboarding_guia
   SET numero_confirmado = true, actualizado_at = now() WHERE onboarding_id = $1`;
export const SQL_MARCAR_SINCRONIZADO = `UPDATE platform.onboarding_guia
   SET sincronizado = true, actualizado_at = now() WHERE onboarding_id = $1`;

/**
 * O abandono dos popups vencidos, **como `kamba_batch`**: todos os tenants, numa
 * instrução, *compare-and-set* pelo `estado = 'iniciado'` — um `FINISH` que
 * reclamou o guia entretanto (`iniciado → es_concluido`) já não é apanhado.
 */
export const SQL_ABANDONAR_VENCIDOS = `UPDATE platform.onboarding_guia
   SET estado = 'abandonado', actualizado_at = now()
 WHERE estado = 'iniciado' AND iniciado_at < $1
 RETURNING onboarding_id::text AS onboarding_id`;

/**
 * Um *gate* do guia, como `kamba_batch`. O tenant sai do caso, nunca de quem
 * chama: é a forma do `SQL_MARCAR_GATE` da activação (KAM-094).
 */
export const SQL_MARCAR_GATE_DO_GUIA = `
INSERT INTO platform.onboarding_gate (onboarding_id, tenant_id, gate, ok, evidencia_ref)
SELECT c.id, c.tenant_id, $2, $3, $4 FROM platform.onboarding_case c WHERE c.id = $1
ON CONFLICT (onboarding_id, gate) DO UPDATE SET ok = EXCLUDED.ok, evidencia_ref = EXCLUDED.evidencia_ref
RETURNING onboarding_id`;

// ------------------------------------------------------------------ a leitura

type Linha = Readonly<Record<string, unknown>>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function idValido(id: unknown): id is string {
  return typeof id === "string" && UUID.test(id.toLowerCase());
}

function textoOuNulo(valor: unknown): string | null {
  return typeof valor === "string" && valor !== "" ? valor : null;
}

function instanteOuNulo(valor: unknown): Date | null {
  if (valor === null || valor === undefined) return null;
  return valor instanceof Date ? valor : new Date(String(valor));
}

function deLista<T extends string>(lista: readonly T[], valor: unknown, nome: string): T {
  if (typeof valor === "string" && (lista as readonly string[]).includes(valor)) return valor as T;
  throw new Error(`o ${nome} lido da base nao esta no dominio`);
}

/**
 * Os itens do pré-voo lidos da coluna, ou `null`. Um item fora do domínio é um
 * erro e não um item a menos: a base e o domínio divergiram.
 */
function itensDe(bruto: unknown): readonly ItemAvaliado[] | null {
  if (bruto === null || bruto === undefined) return null;
  const lido: unknown = typeof bruto === "string" ? JSON.parse(bruto) : bruto;
  if (!Array.isArray(lido)) throw new Error("o preflight lido da base nao e uma lista");
  return lido.map((i: unknown) => {
    const item = (typeof i === "object" && i !== null ? i : {}) as Record<string, unknown>;
    const id = deLista(ITENS_DO_PREFLIGHT, item["id"], "item do preflight");
    if (typeof item["ok"] !== "boolean") throw new Error("o item do preflight nao tem ok");
    return {
      id,
      tipo: TIPO_DO_ITEM[id],
      ok: item["ok"],
      detalhe: deLista(DETALHES, item["detalhe"], "detalhe do preflight"),
    };
  });
}

/**
 * O pré-voo a partir dos itens: a regra do `avaliarPreflight`, e só ela. Um
 * `numero_movel` em `fixo_rota_cloud_only` é o que muda a rota e o único item
 * que não bloqueia.
 */
export function preflightDosItens(itens: readonly ItemAvaliado[], avaliadoEm: Date): Preflight {
  const fixo = itens.some((i) => i.id === "numero_movel" && i.detalhe === "fixo_rota_cloud_only");
  return {
    itens,
    podeAbrir: itens.every((i) => i.ok || (i.id === "numero_movel" && i.detalhe === "fixo_rota_cloud_only")),
    rota: fixo ? "cloud_only" : "coexistencia",
    avaliadoEm,
  };
}

function guiaDe(l: Linha): EstadoGuardado {
  const itens = itensDe(l["preflight"]);
  const avaliadoEm = instanteOuNulo(l["preflight_at"]);
  return {
    onboardingId: String(l["onboarding_id"]),
    estado: deLista(ESTADOS_DO_GUIA, l["estado"], "estado do guia"),
    // Sem o instante não há pré-voo deste guia: os itens podiam ser de um
    // escritor anterior à revisão, e o `iniciar` exige um pré-voo avaliado.
    preflight: itens === null || avaliadoEm === null ? null : preflightDosItens(itens, avaliadoEm),
    iniciadoEm: instanteOuNulo(l["iniciado_at"]),
    motivo: l["motivo"] === null || l["motivo"] === undefined ? null : deLista(MOTIVOS_DE_FALHA, l["motivo"], "motivo"),
    tentativaId: textoOuNulo(l["tentativa_id"]),
    phoneNumberId: textoOuNulo(l["phone_number_id"]),
    wabaId: textoOuNulo(l["waba_id"]),
    numeroConfirmado: l["numero_confirmado"] === true,
    sincronizado: l["sincronizado"] === true,
    actualizadoEm: instanteOuNulo(l["actualizado_at"]) ?? new Date(0),
  };
}

function contadas(resposta: unknown): number {
  return Number((resposta as { rowCount?: number | null }).rowCount ?? 0);
}

// ------------------------------------------------------------------ o guia

/** Levantada pela varredura dos 30 minutos fora do processo de lote. Ver a nota do módulo. */
export class VarreduraNoLoteError extends Error {
  override readonly name = "VarreduraNoLoteError";

  constructor() {
    super("o abandono dos popups vencidos corre no processo de lote, como kamba_batch");
  }
}

/** Levantada ao abrir o guia de um caso que não existe. */
export class CasoDoGuiaInexistenteError extends Error {
  override readonly name = "CasoDoGuiaInexistenteError";

  constructor() {
    super("o guia nao abre sem caso");
  }
}

/** O que o `guiaNaBase` precisa: o *pool* do `kamba_app`. */
export interface OpcoesDoGuiaNaBase {
  readonly pool: PoolDaInscricao;
}

/** O `RepositorioDoGuia` sobre a base, como `kamba_app`. Ver a nota do módulo. */
export function guiaNaBase(o: OpcoesDoGuiaNaBase): RepositorioDoGuia {
  const { pool } = o;

  const tenantDe = async (bd: ClienteSql, id: string): Promise<string | null> => {
    if (!idValido(id)) return null;
    const [l] = await linhas(bd, SQL_TENANT_DO_CASO, [id]);
    return textoOuNulo(l?.["tenant_id"]);
  };

  const lerNa = async (tx: ClienteSql, id: string): Promise<EstadoGuardado | null> => {
    const [l] = await linhas(tx, SQL_LER_GUIA, [id]);
    return l === undefined ? null : guiaDe(l);
  };

  /** Corre `trabalho` pela RLS do tenant do caso; `semCaso` se o caso não existe. */
  const noCaso = <T>(id: string, semCaso: T, trabalho: (tx: ClienteSql, tenant: string) => Promise<T>): Promise<T> =>
    numaLigacaoDaInscricao(pool, async (bd) => {
      const tenant = await tenantDe(bd, id);
      return tenant === null ? semCaso : comTenant(bd, tenant, (tx) => trabalho(tx, tenant));
    });

  return {
    ler: (id) => noCaso(id, null, (tx) => lerNa(tx, id)),

    abrir: async (id) => {
      const aberto = await noCaso<EstadoGuardado | null>(id, null, async (tx, tenant) => {
        await tx.query(SQL_ABRIR_GUIA, [id, tenant]);
        return lerNa(tx, id);
      });
      if (aberto === null) throw new CasoDoGuiaInexistenteError();
      return aberto;
    },

    gravarPreflight: async (id, preflight) => {
      await noCaso(id, undefined, async (tx, tenant) => {
        await tx.query(SQL_ABRIR_GUIA, [id, tenant]);
        // Só a forma do bloco: `{ id, tipo, ok, detalhe }` por item.
        const itens = preflight.itens.map((i) => ({ id: i.id, tipo: i.tipo, ok: i.ok, detalhe: i.detalhe }));
        await tx.query(SQL_GRAVAR_PREFLIGHT_DO_CASO, [id, JSON.stringify(itens)]);
        await tx.query(SQL_GRAVAR_PREFLIGHT_DO_GUIA, [id, preflight.avaliadoEm]);
      });
    },

    transitar: (id, de: EstadoDoGuia, para: EstadoDoGuia, campos) =>
      noCaso(id, false, async (tx) => {
        const par = <K extends keyof typeof campos>(k: K): [boolean, unknown] =>
          Object.prototype.hasOwnProperty.call(campos, k) ? [true, campos[k] ?? null] : [false, null];
        const resposta = await tx.query(SQL_TRANSITAR_GUIA, [
          id,
          de,
          para,
          ...par("iniciadoEm"),
          ...par("motivo"),
          ...par("tentativaId"),
          ...par("phoneNumberId"),
          ...par("wabaId"),
          ...par("numeroConfirmado"),
          ...par("sincronizado"),
        ]);
        return contadas(resposta) === 1;
      }),

    marcar: async (id, facto) => {
      await noCaso(id, undefined, async (tx) => {
        await tx.query(facto === "numeroConfirmado" ? SQL_MARCAR_NUMERO : SQL_MARCAR_SINCRONIZADO, [id]);
      });
    },

    iniciadosAntesDe: async () => {
      throw new VarreduraNoLoteError();
    },

    porPhoneNumberId: (phoneNumberId) =>
      numaLigacaoDaInscricao(pool, async (bd) => {
        if (typeof phoneNumberId !== "string" || phoneNumberId === "") return null;
        const [l] = await linhas(bd, SQL_CASO_POR_NUMERO, [phoneNumberId]);
        return textoOuNulo(l?.["id"]);
      }),
  };
}

// ------------------------------------------------------------------ o lado do lote

/**
 * O abandono dos 30 minutos, como `kamba_batch`. Devolve os casos que passaram a
 * `abandonado`. A vaga **não** se devolve aqui: o `release` da lista não muda
 * nada (`lista_espera_vaga_mantida`, KAM-095), e quem a conta é a janela.
 */
export async function abandonarVencidosNaBase(lote: ClienteSql, antes: Date): Promise<readonly string[]> {
  return (await linhas(lote, SQL_ABANDONAR_VENCIDOS, [antes])).map((l) => String(l["onboarding_id"]));
}

/** Levantada quando o *gate* é de um caso que não existe. Falha fechado. */
export class GateSemCasoError extends Error {
  override readonly name = "GateSemCasoError";

  constructor() {
    super("o gate do guia nao se marca sem caso");
  }
}

/**
 * Os dois *gates* do guia na base, como `kamba_batch` (o `kamba_app` só tem
 * `SELECT` na `onboarding_gate`, revisão `0058`). O motivo vai na
 * `evidencia_ref`, que é um identificador curto e nunca texto do dono.
 */
export function gatesDoGuiaNaBase(lote: ClienteSql): GatesDoOnboarding {
  return {
    async marcar(onboardingId: string, gate: GateDoEs, verde: boolean, motivo: string): Promise<void> {
      if (!idValido(onboardingId)) throw new GateSemCasoError();
      const resposta = await lote.query(SQL_MARCAR_GATE_DO_GUIA, [onboardingId, gate, verde, motivo]);
      if (contadas(resposta) !== 1) throw new GateSemCasoError();
    },
  };
}
