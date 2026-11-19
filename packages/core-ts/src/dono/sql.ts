/**
 * Os adaptadores de base do canal do dono (KAM-211): a troca de telefone e o
 * contacto do número verificado.
 *
 * ## O papel é o `kamba_identity`, e só ele
 *
 * A `platform.definir_dono` é `SECURITY DEFINER` e o `EXECUTE` é só do
 * `kamba_identity` (revisão `0070`). Por isso o cliente que estes adaptadores
 * recebem é **uma ligação** desse papel — nunca um *pool* (o `comTenant`
 * recusa-o) e nunca o `kamba_app`, que recebe `42501`. O tenant vai para o
 * `app.tenant_id` da transacção e **não** para a função: ela lê-o só do
 * contexto, e um contacto de outro tenant não se encontra (`23503`).
 *
 * ## O contacto do número novo
 *
 * É o `resolveContact` do KAM-008 só com o telefone — o que o OTP acabou de
 * provar que pertence a quem o pediu. **Só com o telefone não há fusão** (uma
 * fusão precisa de dois identificadores a apontar para contactos diferentes), e
 * por isso um `contact.merged` aqui é uma incoerência: o adaptador recusa em vez
 * de o deixar cair sem ninguém o emitir.
 */

import type { ClienteDeIdentidade, Identidade } from "../identity/contactos.ts";
import type { Telefone } from "../inscricao/identificadores.ts";
import { comTenant, type ClienteSql } from "../tenant_guard/index.ts";
import { ORIGEM_DO_PROVISIONAMENTO, type DefinirDono } from "./provisionamento.ts";
import {
  TrocaDeTelefone,
  type AvisoDaTroca,
  type ContactoDoNumero,
  type OtpDaTroca,
  type TrocaNaBase,
} from "./troca.ts";

/** A origem com que a troca chama a porta. O `CHECK` da `definir_dono`. */
export const ORIGEM_DA_TROCA = "troca_de_telefone";

/**
 * A única escrita do papel. O `::uuid` é explícito: o parâmetro chega como texto
 * e a função só tem a assinatura `(uuid, text)`.
 */
export const SQL_DEFINIR_DONO = "SELECT platform.definir_dono($1::uuid, $2) AS anterior";

/** O resolver devolveu uma fusão onde não pode haver nenhuma. */
export class FusaoNaTrocaError extends Error {
  override readonly name = "FusaoNaTrocaError";

  constructor() {
    // Nem o tenant nem os contactos entram na mensagem.
    super("o contacto do numero verificado resolveu-se por fusao; a troca nao continua");
  }
}

async function definir(
  cliente: ClienteSql,
  tenantId: string,
  contactId: string,
  origem: string,
): Promise<string | null> {
  return comTenant(cliente, tenantId, async (bd) => {
    // O `ClienteSql` do `tenant_guard` devolve `unknown`: a forma e a do `pg`,
    // e le-se sem confiar nela.
    const resposta = (await bd.query(SQL_DEFINIR_DONO, [contactId, origem])) as {
      readonly rows?: readonly { readonly anterior?: unknown }[];
    };
    const anterior = resposta.rows?.[0]?.anterior;
    return anterior === null || anterior === undefined ? null : String(anterior);
  });
}

/**
 * A `TrocaNaBase` da `TrocaDeTelefone`: `definir_dono(contacto,
 * 'troca_de_telefone')` como `kamba_identity`. Devolve o dono que deixou de o
 * ser, ou `null` se não havia nenhum (ou se o contacto já era o dono).
 */
export function trocaNaBase(identidade: ClienteSql): TrocaNaBase {
  return async ({ tenantId, contactId }) => ({
    anterior: await definir(identidade, tenantId, contactId, ORIGEM_DA_TROCA),
  });
}

/**
 * O `DefinirDono` do `efeitoDoProvisionamento`: a mesma porta com a origem
 * `provisionamento`, idempotente e sem trocar um dono vivo (`23505`). Fica aqui
 * ao lado da troca porque é a mesma instrução; quem o liga ao consumidor é o
 * credor do critério «Provisionamento».
 */
export function definirDonoNaBase(identidade: ClienteSql): DefinirDono {
  return async ({ tenantId, contactId }) => {
    await definir(identidade, tenantId, contactId, ORIGEM_DO_PROVISIONAMENTO);
  };
}

/**
 * Uma ligação de um *pool* do `kamba_identity`, pela forma do `pg.PoolClient`.
 * O `release(true)` destrói-a em vez de a devolver. Serve também de
 * `ClienteSql`: o `query` dela devolve um `ResultadoSql`, que é um `unknown`.
 */
export interface LigacaoDoPool extends ClienteDeIdentidade {
  release(destruir?: boolean | Error): void;
}

/** O *pool* do `kamba_identity`, pela forma do `pg.Pool`. */
export interface PoolDeIdentidade {
  connect(): Promise<LigacaoDoPool>;
}

/**
 * Corre `trabalho` numa ligação **só sua**, tirada do *pool* e devolvida no fim.
 *
 * É a razão de este módulo ter uma montagem de processo (KAM-217). Um servidor
 * HTTP atende pedidos concorrentes, e o `comTenant` é uma transacção
 * (`BEGIN`, `app.tenant_id`, a instrução, `COMMIT`). Sobre **uma** ligação
 * partilhada, o `tenant_guard` recusa a segunda transacção enquanto a primeira
 * corre (`LigacaoEmUsoError`): não cruza tenants, mas o dono que chega em
 * segundo recebe um erro. Uma ligação por operação deixa as duas trocas correr
 * ao mesmo tempo, cada uma no seu tenant. Uma ligação que falhou é destruída, e
 * não devolvida, para nenhuma transacção a meio passar ao pedido seguinte.
 */
export async function numaLigacao<T>(
  pool: PoolDeIdentidade,
  trabalho: (ligacao: LigacaoDoPool) => Promise<T>,
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
 * A `TrocaDeTelefone` de um processo que atende pedidos concorrentes (KAM-217):
 * o contacto e a porta com uma ligação do *pool* do `kamba_identity` por
 * operação. É a montagem que o `server.ts` do `onboarding-web` usa, e a que o
 * ensaio contra a base corre.
 */
export function trocaPeloPool(portas: {
  readonly pool: PoolDeIdentidade;
  readonly identidade: Pick<Identidade, "resolveContact">;
  readonly otp: OtpDaTroca;
  readonly avisar: AvisoDaTroca;
  readonly relogio?: () => Date;
}): TrocaDeTelefone {
  const { pool, identidade } = portas;
  return new TrocaDeTelefone({
    otp: portas.otp,
    avisar: portas.avisar,
    contacto: (pedido) => numaLigacao(pool, (ligacao) => contactoDoNumero(identidade, ligacao)(pedido)),
    trocar: (pedido) => numaLigacao(pool, (ligacao) => trocaNaBase(ligacao)(pedido)),
    ...(portas.relogio === undefined ? {} : { relogio: portas.relogio }),
  });
}

/** O `ContactoDoNumero`: o `resolveContact` do KAM-008, só com o telefone. */
export function contactoDoNumero(
  modulo: Pick<Identidade, "resolveContact">,
  identidade: ClienteDeIdentidade,
): ContactoDoNumero {
  return async ({ tenantId, telefone }: { tenantId: string; telefone: Telefone }) => {
    // **Um sitio de chamada do `revelar()`, e fica dito** (a nota do `ComHmac`
    // de `inscricao/identificadores.ts` conta-os): o `resolveContact` cunha o
    // HMAC do contacto com a chave **dele**, noutro espaco que o da inscricao,
    // e por isso precisa do numero em claro. Nao sai daqui para mais lado
    // nenhum, e nao entra em mensagem nem em registo.
    const resolvido = await modulo.resolveContact(identidade, {
      tenantId,
      telefone: telefone.revelar(),
    });
    if (resolvido.evento !== null) throw new FusaoNaTrocaError();
    return { contactId: resolvido.contactId };
  };
}
