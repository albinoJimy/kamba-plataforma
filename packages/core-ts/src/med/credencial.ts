/**
 * O *token* do canal que recebeu a midia, para o `ClienteDeMidiaDaGraph` (KAM-231).
 *
 * E o caminho que o `resposta/credencial.ts` do KAM-227 escreveu para o envio,
 * pela mesma ordem, e com uma diferenca so: o canal chega pela **conversa**.
 *
 *     conversations.channel_id -> tenant_channels.token_ref   sob a RLS do tenant
 *       -> o cofre, pela referencia                            o criptograma
 *       -> decifrarToken(anel, tenant)                         com a `kek_token_cliente`
 *
 * ## Porque a conversa, e nao o primeiro canal do tenant
 *
 * O `PedidoDeMidia` nao traz o canal, e o `media_id` e do numero que recebeu a
 * mensagem: o *token* de outro canal do mesmo tenant pode nao o ver. A conversa
 * e do pedido (`conversationId`), e a `conversations` guarda o `channel_id` com
 * chave estrangeira composta para a `tenant_channels` (`0009`): a juncao nao
 * atravessa tenants nem com a RLS desligada.
 *
 * ## Tres barreiras, como no envio
 *
 * 1. a leitura corre sob a RLS do tenant — **quem a da e o `bd` recebido**, que
 *    tem de pôr o contexto (o `entrada.ts` passa um `ClienteSql` que abre um
 *    `comTenant` por instrucao);
 * 2. o `tenant_id` repete-se no `WHERE`;
 * 3. o criptograma tem o tenant no contexto autenticado da cifra: uma
 *    referencia de A copiada para a linha de B nao abre sob B.
 *
 * ## Um canal sem *token* e recusa definitiva
 *
 * `MidiaInesperadaError`, com o motivo (um de tres literais, os do envio), e
 * nunca a referencia: nenhuma das tres tentativas do MED faz aparecer um
 * segredo que o cofre nao tem. A KEK em falta **nao** e motivo do canal: e
 * configuracao do processo, e sobe como o erro do cofre — em `staging` e
 * `prod` o arranque do `entrada.ts` ja recusa sem ela.
 */

import { TokenCifradoInvalidoError, anelDaKek, decifrarToken } from "../onboarding/cifra.ts";
// O `id` da KEK vem do ficheiro estreito que o *gate* 9 dispensa.
import { REF_DA_KEK } from "../onboarding/segredos.ts";
import { SecretAusenteError, SecretRefInvalidaError, type SecretProvider } from "../secrets/port.ts";
import { MidiaInesperadaError, type ClienteSql } from "./contrato.ts";
import type { TokenDoCanal } from "./graph.ts";

/**
 * A referencia do *token* do canal da conversa.
 *
 * O `tenant_id` repete-se no `WHERE` e na juncao de proposito: a RLS e a
 * primeira barreira, e o predicado a segunda.
 */
export const SQL_TOKEN_REF_DA_CONVERSA = `
  SELECT tc.token_ref
    FROM platform.conversations c
    JOIN platform.tenant_channels tc
      ON tc.tenant_id = c.tenant_id AND tc.id = c.channel_id
   WHERE c.tenant_id = $1 AND c.id = $2`;

/** O que a credencial le do cofre: so leitura, e so as tres operacoes de que precisa. */
export type CofreDaMidia = Pick<SecretProvider, "get" | "getRing" | "versions">;

export interface OpcoesDoTokenDaConversa {
  readonly cofre: CofreDaMidia;
  /** A base, **ja com o contexto do tenant** posto por quem a passa. */
  readonly bd: ClienteSql;
  /** A conversa do `PedidoDeMidia`. */
  readonly conversationId: string;
}

/** O *token* do canal da conversa, lido a cada pedido. Ver a nota do modulo. */
export function tokenDaConversa(o: OpcoesDoTokenDaConversa): TokenDoCanal {
  return async (tenantId) => {
    const { rows } = await o.bd.query<{ token_ref: string }>(SQL_TOKEN_REF_DA_CONVERSA, [
      tenantId,
      o.conversationId,
    ]);
    const ref = rows[0]?.token_ref;
    if (ref === undefined) throw new MidiaInesperadaError("sem credencial do canal: sem_canal");

    // O anel primeiro: uma KEK em falta e do processo, e sobe como erro.
    const valores = await o.cofre.getRing(REF_DA_KEK); // kamba:secrets-inventory dinamico REF_DA_KEK e a kek_token_cliente, no inventario
    const anel = anelDaKek(valores, await o.cofre.versions(REF_DA_KEK)); // kamba:secrets-inventory dinamico REF_DA_KEK e a kek_token_cliente, no inventario

    let criptograma: string;
    try {
      criptograma = await o.cofre.get(ref); // kamba:secrets-inventory dinamico o token_ref do canal, instancia de meta_client_token
    } catch (erro) {
      if (erro instanceof SecretAusenteError || erro instanceof SecretRefInvalidaError) {
        throw new MidiaInesperadaError("sem credencial do canal: sem_segredo");
      }
      throw erro;
    }

    try {
      return decifrarToken(anel, tenantId, criptograma);
    } catch (erro) {
      if (erro instanceof TokenCifradoInvalidoError) {
        throw new MidiaInesperadaError("sem credencial do canal: nao_abre");
      }
      throw erro;
    }
  };
}
