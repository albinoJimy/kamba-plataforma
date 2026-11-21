/**
 * A credencial da Meta de cada canal, para o envio da resposta do AGR (KAM-227).
 *
 * O `Saida` do KAM-015 fala com a Graph por uma porta (`ClienteDaMeta`), e o
 * `ClienteDaGraph` precisa do *token* de acesso do canal. Até ao KAM-227 nada o
 * lia: o `tenant_channels.token_ref` era uma referência sem leitor. Este módulo
 * é o leitor, pela ordem que o KAM-016 escreveu ao guardá-lo:
 *
 *     tenant_channels.token_ref        a referência opaca, lida sob a RLS do tenant
 *       → o cofre, pela referência     o criptograma, e não o *token* (cifra.ts)
 *       → decifrarToken(anel, tenant)  com a `kek_token_cliente` do cofre
 *       → new ClienteDaGraph({ token })
 *
 * ## O *token* de um canal não serve o envio de outro tenant
 *
 * Três barreiras, e a terceira é a que não depende de ninguém se lembrar:
 *
 * 1. a leitura da `tenant_channels` corre sob a RLS do tenant do pedido, com o
 *    `tenant_id` também no `WHERE`;
 * 2. o canal é o do **pedido** (`channel_id` **e** `phone_number_id`), e não o
 *    primeiro do tenant;
 * 3. o criptograma tem o tenant no contexto autenticado da cifra
 *    (`contextoDaCifra` do `onboarding/cifra.ts`): uma referência de A copiada
 *    para a linha de B — uma escrita que a base aceita, porque o `GRANT UPDATE
 *    (token_ref)` da `0001` a deixa ao `kamba_app` — **não abre** sob B.
 *
 * ## Um canal sem *token* recusa com motivo próprio
 *
 * `CanalSemCredencialError`, com um de três motivos, e **antes** de o `Saida`
 * gravar a linha da `outbound_messages`: um canal cujo *token* se repõe depois
 * não fica com uma chave gasta. O efeito do consumidor trata-o como desfecho
 * (`sem_credencial`, no `efeito.ts`), e não como erro: nenhuma das seis
 * tentativas do consumo faz aparecer um segredo que o cofre não tem.
 *
 * A KEK em falta **não** é motivo deste canal: é configuração do processo, e
 * sobe como erro. Em `prod` o arranque já recusa sem ela
 * (`services/worker-canal/src/consumidor.ts`).
 *
 * ## O *token* nunca sai daqui
 *
 * Nenhum erro deste ficheiro leva o valor, a referência ou o criptograma —
 * leva o motivo, que é um de três literais. O *token* vive no `ClienteDaGraph`
 * (campo privado) durante um envio, e o `ClienteDaGraph` não regista nada.
 *
 * ## Lê-se o cofre a cada envio
 *
 * Com o `EnvSecretProvider` do Piloto (ADR-L002) é uma leitura do ambiente do
 * processo, e não uma ida à rede. Uma *cache* aqui era um segundo sítio onde o
 * *token* em claro ficava a viver entre envios.
 */

import { ClienteDaGraph } from "../outbound/cliente.ts";
import type { ClienteDaMeta, ClienteSql, Pedido } from "../outbound/contrato.ts";
import { TokenCifradoInvalidoError, anelDaKek, decifrarToken } from "../onboarding/cifra.ts";
// O `id` da KEK vem do ficheiro estreito que o *gate* 9 dispensa.
import { REF_DA_KEK } from "../onboarding/segredos.ts";
import { SecretAusenteError, SecretRefInvalidaError, type SecretProvider } from "../secrets/port.ts";
import { comTenant } from "../tenant_guard/index.ts";

/**
 * A referência do *token* do canal do pedido.
 *
 * O `tenant_id` repete-se no `WHERE` de propósito, como em todas as leituras
 * desta pasta: a RLS é a primeira barreira, e o predicado a segunda.
 */
export const SQL_TOKEN_REF_DO_CANAL = `
  SELECT token_ref
    FROM platform.tenant_channels
   WHERE tenant_id = $1 AND id = $2 AND phone_number_id = $3`;

/**
 * Porque é que um canal não tem credencial. Literais, para a métrica e o
 * registo: nenhum leva a referência.
 */
export const MOTIVOS_SEM_CREDENCIAL = [
  /** O canal do pedido não existe neste tenant (ou o número não é o dele). */
  "sem_canal",
  /** O cofre não tem segredo sob a referência, ou a referência não tem forma. */
  "sem_segredo",
  /** O criptograma não abre: outra KEK, outro tenant, ou conteúdo alterado. */
  "nao_abre",
] as const;
export type MotivoSemCredencial = (typeof MOTIVOS_SEM_CREDENCIAL)[number];

/** O canal do pedido não tem *token* que sirva. Ver a nota do módulo. */
export class CanalSemCredencialError extends Error {
  override readonly name = "CanalSemCredencialError";
  readonly motivo: MotivoSemCredencial;

  constructor(motivo: MotivoSemCredencial) {
    super(`o canal do envio nao tem credencial da Meta: ${motivo}`);
    this.motivo = motivo;
  }
}

/** O canal de um envio, como o `Pedido` do Outbound o diz. */
export type CanalDoEnvio = Pick<Pedido, "tenantId" | "channelId" | "phoneNumberId">;

/**
 * A porta: o cliente da Graph do canal de um envio, lido na ligação do envio.
 *
 * Levanta `CanalSemCredencialError` quando o canal não tem *token* que sirva.
 */
export type ClienteDoCanal = (ligacao: ClienteSql, canal: CanalDoEnvio) => Promise<ClienteDaMeta>;

/** O que a credencial lê do cofre: só leitura, e só as três operações de que precisa. */
export type CofreDeLeitura = Pick<SecretProvider, "get" | "getRing" | "versions">;

export interface OpcoesDaCredencial {
  readonly cofre: CofreDeLeitura;
  /** A base da Graph. Por omissão, a de produção; o servidor falso entra por aqui. */
  readonly base?: string;
  /** O `fetch` do cliente. Porta para os ensaios. */
  readonly buscar?: typeof fetch;
}

/** O cliente da Graph de cada canal, pelo `token_ref` e pela `kek_token_cliente`. */
export function clienteDaGraphPorCanal(o: OpcoesDaCredencial): ClienteDoCanal {
  return async (ligacao, canal) => {
    const { rows } = await comTenant(ligacao, canal.tenantId, () =>
      ligacao.query<{ token_ref: string }>(SQL_TOKEN_REF_DO_CANAL, [
        canal.tenantId,
        canal.channelId,
        canal.phoneNumberId,
      ]),
    );
    const ref = rows[0]?.token_ref;
    if (ref === undefined) throw new CanalSemCredencialError("sem_canal");

    // O anel primeiro: uma KEK em falta é do processo, e sobe como erro.
    const valores = await o.cofre.getRing(REF_DA_KEK); // kamba:secrets-inventory dinamico REF_DA_KEK e a kek_token_cliente, no inventario
    const anel = anelDaKek(valores, await o.cofre.versions(REF_DA_KEK)); // kamba:secrets-inventory dinamico REF_DA_KEK e a kek_token_cliente, no inventario

    let criptograma: string;
    try {
      criptograma = await o.cofre.get(ref); // kamba:secrets-inventory dinamico o token_ref do canal, instancia de meta_client_token
    } catch (erro) {
      if (erro instanceof SecretAusenteError || erro instanceof SecretRefInvalidaError) {
        throw new CanalSemCredencialError("sem_segredo");
      }
      throw erro;
    }

    let token: string;
    try {
      token = decifrarToken(anel, canal.tenantId, criptograma);
    } catch (erro) {
      if (erro instanceof TokenCifradoInvalidoError) throw new CanalSemCredencialError("nao_abre");
      throw erro;
    }
    return new ClienteDaGraph({
      token,
      ...(o.base === undefined ? {} : { base: o.base }),
      ...(o.buscar === undefined ? {} : { buscar: o.buscar }),
    });
  };
}
