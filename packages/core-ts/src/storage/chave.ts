/**
 * Chaves de objecto e a sua relação com o tenant (KAM-011).
 *
 * `t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}` — e mais nenhuma forma. Este
 * ficheiro é a única fonte dessa forma: cunha chaves, valida-as, e responde à
 * única pergunta de isolamento que o armazenamento tem — «esta chave é do tenant
 * deste contexto?» (`docs/tecnica/08` §3.1, camada «Storage»; STO-E e STO-I em
 * `docs/seguranca/ameacas_stride.md` §4.14).
 *
 * A validação é por **lista fechada de caracteres**, não por lista de
 * caracteres proibidos: não há `..`, `//`, `%2f`, espaço, maiúscula nem byte
 * nulo que passe, porque nenhum deles está no alfabeto. Uma chave que não
 * precisa de *escaping* em parte nenhuma — URL, cabeçalho, XML, log — não tem
 * uma segunda leitura que um servidor possa fazer diferente da nossa.
 */

import { randomUUID } from "node:crypto";

import {
  ChaveForaDoTenantError,
  ChaveInvalidaError,
  type Ctx,
  CtxEmFaltaError,
  MetaInvalidaError,
  type ObjectKey,
  TenantInvalidoError,
} from "./port.ts";

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const UUID_CANONICO = new RegExp(`^${UUID}$`);

/**
 * Forma de uma classe: `snake_case` minúsculo, 2 a 32 caracteres.
 *
 * A **lista** de classes não é deste ticket: cada consumidor traz as suas
 * (áudio e imagem no KAM-020, fotos de catálogo no KAM-049, documentos de KYC
 * no KAM-098) e a política de retenção por classe é do KAM-071. Aqui fixa-se só
 * a forma, para que a classe caiba num segmento de chave sem *escaping*.
 */
const CLASSE = "[a-z][a-z0-9_]{1,31}";
const CLASSE_INTEIRA = new RegExp(`^${CLASSE}$`);

/** A forma completa, com os cinco segmentos capturados. */
const CHAVE = new RegExp(`^t/(${UUID})/(${CLASSE})/([0-9]{4})/(0[1-9]|1[0-2])/(${UUID})$`);

/** Alfabeto do resto de um prefixo de listagem, depois de `t/{tenant_id}/`. */
const RESTO_DE_PREFIXO = /^[a-z0-9_/-]*$/;

/** Comprimento máximo de um prefixo de listagem: o de uma chave completa. */
const COMPRIMENTO_MAXIMO = 2 + 36 + 1 + 32 + 1 + 4 + 1 + 2 + 1 + 36;

/** As partes de uma chave válida. */
export interface PartesDaChave {
  readonly tenantId: string;
  readonly classe: string;
  readonly ano: string;
  readonly mes: string;
  readonly id: string;
}

/**
 * O tenant do contexto como UUID canónico, ou lança.
 *
 * Aceita só a forma textual canónica, em minúsculas. Ao contrário do
 * `tenant_guard` — que normaliza a caixa porque o Postgres compara UUID por
 * valor — aqui o tenant vira **texto de uma chave**, e `T/…AB…` e `t/…ab…` são
 * dois prefixos diferentes num servidor de objectos. Recusar a maiúscula é mais
 * barato do que descobrir um tenant com dois prefixos.
 */
export function tenantDoCtx(ctx: Ctx): string {
  const tenant: unknown = (ctx as { tenantId?: unknown } | null | undefined)?.tenantId;
  if (tenant === null || tenant === undefined || tenant === "") {
    throw new CtxEmFaltaError();
  }
  if (typeof tenant !== "string" || !UUID_CANONICO.test(tenant)) {
    throw new TenantInvalidoError(typeof tenant, typeof tenant === "string" ? tenant.length : 0);
  }
  return tenant;
}

/** O prefixo de tudo o que é de um tenant: `t/{tenant_id}/`. */
export function prefixoDoTenant(ctx: Ctx): string {
  return `t/${tenantDoCtx(ctx)}/`;
}

/** Valida a forma de uma classe e devolve-a. */
export function validarClasse(classe: unknown): string {
  if (typeof classe !== "string" || !CLASSE_INTEIRA.test(classe)) {
    throw new MetaInvalidaError(
      "a classe é snake_case minúsculo, de 2 a 32 caracteres, começada por letra",
    );
  }
  return classe;
}

/**
 * Cunha uma chave nova para o tenant do contexto.
 *
 * `{aaaa}/{mm}` são o ano e o mês **UTC** do instante dado (`specs/02` §2:
 * datas em UTC). O `{uuid}` é aleatório (v4): a chave não codifica o contacto,
 * a conversa nem o nome original do ficheiro — nenhum dado pessoal entra numa
 * chave, que aparece em logs e em URLs.
 */
export function novaChave(ctx: Ctx, classe: string, agora: Date = new Date()): ObjectKey {
  const tenant = tenantDoCtx(ctx);
  const c = validarClasse(classe);
  if (!(agora instanceof Date) || Number.isNaN(agora.getTime())) {
    throw new ChaveInvalidaError("o instante de criação não é uma data válida");
  }
  const ano = String(agora.getUTCFullYear()).padStart(4, "0");
  const mes = String(agora.getUTCMonth() + 1).padStart(2, "0");
  return `t/${tenant}/${c}/${ano}/${mes}/${randomUUID()}`;
}

/**
 * Valida a forma de uma chave, sem olhar para o contexto.
 *
 * @throws {ChaveInvalidaError}
 */
export function partesDaChave(key: unknown): PartesDaChave {
  if (typeof key !== "string") {
    throw new ChaveInvalidaError("não é texto");
  }
  const m = CHAVE.exec(key);
  if (m === null) {
    throw new ChaveInvalidaError(
      "esperava t/{tenant_id}/{classe}/{aaaa}/{mm}/{uuid}, em minúsculas",
    );
  }
  return {
    tenantId: m[1] as string,
    classe: m[2] as string,
    ano: m[3] as string,
    mes: m[4] as string,
    id: m[5] as string,
  };
}

/**
 * A pergunta de isolamento: a chave tem a forma canónica **e** é do tenant do
 * contexto?
 *
 * A ordem das recusas é deliberada. O contexto valida-se primeiro — sem tenant
 * não há pergunta. Depois a forma. Só então o dono: uma chave bem formada de
 * outro tenant dá `ChaveForaDoTenantError`, e uma chave mal formada dá
 * `ChaveInvalidaError` mesmo que comece pelo prefixo certo.
 *
 * @param operacao nome da operação, para a mensagem (`get`, `signUrl`, …).
 */
export function chaveDoCtx(ctx: Ctx, key: unknown, operacao: string): PartesDaChave {
  const tenant = tenantDoCtx(ctx);
  const partes = partesDaChave(key);
  if (partes.tenantId !== tenant) {
    throw new ChaveForaDoTenantError(operacao);
  }
  return partes;
}

/**
 * Valida um prefixo de listagem contra o contexto e devolve-o.
 *
 * O prefixo tem de **começar por `t/{ctx.tenantId}/`, com a barra final**.
 * `t/` sozinho, o prefixo vazio e `t/{tenant}` sem barra são recusados: os dois
 * primeiros listam todos os tenants, e o terceiro só não lista outro porque os
 * UUID têm comprimento fixo — uma propriedade verdadeira hoje, e que este
 * módulo não quer como única defesa.
 */
export function prefixoDoCtx(ctx: Ctx, prefix: unknown): string {
  const base = prefixoDoTenant(ctx);
  if (typeof prefix !== "string") {
    throw new ChaveInvalidaError("o prefixo não é texto");
  }
  if (!prefix.startsWith(base)) {
    throw new ChaveForaDoTenantError("list");
  }
  const resto = prefix.slice(base.length);
  if (
    prefix.length > COMPRIMENTO_MAXIMO ||
    !RESTO_DE_PREFIXO.test(resto) ||
    resto.includes("//") ||
    resto.startsWith("/")
  ) {
    throw new ChaveInvalidaError("o prefixo tem caracteres fora de [a-z0-9_/-] ou segmentos vazios");
  }
  return prefix;
}
