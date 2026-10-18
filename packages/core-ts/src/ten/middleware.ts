/**
 * O *middleware* HTTP do TEN (KAM-009, criterios 2, 3 e 7).
 *
 *     403 ENTITLEMENT_DISABLED   o modulo nao esta activo para este tenant
 *     429 LIMIT_EXCEEDED         o tecto do periodo nao chega
 *
 * **Os dois codigos e os dois estados HTTP estao em proposta**, e nao da mesma
 * maneira: ver a nota em `entitlements.ts` sobre `CODIGO_ENTITLEMENT_HTTP`. Em
 * resumo: `LIMIT_EXCEEDED` esta em `docs/tecnica/02` §6.5 mas **sem estado HTTP
 * associado**, e `ENTITLEMENT_DISABLED` nao esta em documento nenhum — o §6.5
 * escreve `ENTITLEMENT_DENIED` para a mesma situacao. O `403` e o `429` sao
 * propostas deste ticket.
 *
 * ## Nao depende de nenhuma framework, e isso e deliberado
 *
 * Devolve `null` para «siga» ou um objecto com estado, corpo e cabecalhos para
 * «pare aqui». Quem o liga ao Hono (`services/gwy`), ao Express ou a um
 * `fetch` handler sao tres linhas de adaptacao do lado do servico:
 *
 *     const recusa = await guardaHttp(bd, pedido, { tenantId }, { modulo: "vendedor" });
 *     if (recusa !== null) return c.json(recusa.corpo, recusa.estado, recusa.cabecalhos);
 *
 * O `packages/core-ts` nao tem o Hono nas dependencias e nao e para ter: um
 * nucleo partilhado que importa uma framework de HTTP obriga todos os servicos
 * a ela, incluindo os que nao servem HTTP (`libs/py-core` tem a mesma regra
 * escrita no `pyproject.toml`).
 *
 * ## O `tenant_id` vem do contexto, e nunca do pedido — criterio 7
 *
 * Este modulo le do `Pedido` **uma** coisa, e esta escrita numa linha so: o
 * cabecalho de idempotencia. Nao le `query`, nao le corpo, e nao ha nenhum
 * caminho pelo qual um cliente possa dizer de que tenant e.
 *
 * O tenant vem do `ContextoDoPedido`, que quem monta e o CHR (`01` §7.2, «o
 * unico sitio onde o `tenant_id` nasce») ou a autenticacao do servico. O
 * `Pedido` e o `ContextoDoPedido` sao argumentos **separados** de proposito: um
 * unico objecto com tudo la dentro deixava a escolha do campo ao programador, e
 * e exactamente essa escolha que nao se quer ter de rever em cada servico.
 *
 * Duas provas disto na bateria, e nenhuma e uma promessa em prosa:
 * `test_o_tenant_vem_do_contexto_e_nao_do_pedido` poe o tenant B na query, no
 * corpo e em tres cabecalhos e confirma que o SQL correu com o tenant A; e
 * `test_o_middleware_nao_le_tenant_nenhum_do_pedido` le **a fonte deste
 * ficheiro** e confirma que nenhuma leitura de `pedido` sai da linha do
 * cabecalho de idempotencia.
 *
 * ## O que este modulo nao faz
 *
 * * **Nao regista nada.** Conta, pelo `metricas.ts`. Uma recusa com o tenant
 *   no registo era o que o X-11 do gate 6 vem procurar.
 * * **Nao abre transaccao.** Recebe o cliente ja com contexto de tenant
 *   (`tenant_guard.comTenant`), e e dentro dessa transaccao que o consumo tem
 *   de cair para ser atomico com o efeito que o motivou.
 * * **Nao inventa um terceiro codigo.** Um pedido que precise de consumir e nao
 *   traga chave de idempotencia e um defeito de quem chama, nao uma resposta de
 *   negocio: levanta `ChaveDeIdempotenciaInvalidaError`. Dar-lhe um `400` com
 *   um codigo novo seria acrescentar ao vocabulario de `02` §6.5 sem documento
 *   nenhum — e essa decisao devolve-se ao dono do `02`.
 */

import {
  CODIGO_ENTITLEMENT_HTTP,
  CODIGO_LIMITE,
  ChaveDeIdempotenciaInvalidaError,
  type CacheDeEntitlements,
  type ClienteSql,
  HTTP_ENTITLEMENT,
  HTTP_LIMITE,
  checkEntitlement,
  consumeLimit,
} from "./entitlements.ts";
import type { MetricasDoTen } from "./metricas.ts";

/** O cabecalho de onde sai a chave de idempotencia, quando nao se diz outro. */
export const CABECALHO_DE_IDEMPOTENCIA = "idempotency-key";

/** O minimo de um pedido HTTP de que este modulo precisa. */
export interface Pedido {
  readonly metodo: string;
  readonly caminho: string;
  /** Nomes em minusculas, como o `Headers` do `fetch` os entrega. */
  readonly cabecalhos: Readonly<Record<string, string>>;
}

/**
 * O contexto do pedido. **E daqui que o tenant vem, e so daqui.**
 *
 * Quem o monta e o CHR ou a autenticacao do servico, antes deste middleware.
 */
export interface ContextoDoPedido {
  readonly tenantId: string;
}

/** Uma recusa pronta a servir. */
export interface Recusa {
  readonly estado: number;
  readonly corpo: {
    readonly error: string;
    readonly modulo?: string;
    readonly key?: string;
  };
  readonly cabecalhos: Readonly<Record<string, string>>;
}

export interface OpcoesDoMiddleware {
  /** O modulo (vertical) que o caminho serve. Obrigatorio. */
  readonly modulo: string;
  /** A chave de limite a consumir. Sem ela, so se verifica o entitlement. */
  readonly chave?: string;
  /** Quanto consumir. 1 por omissao. */
  readonly quantidade?: number;
  /** A chave de idempotencia, quando quem chama a deriva (`02` §6.3). */
  readonly idempotencyKey?: string;
  /** Outro cabecalho de idempotencia que nao o `idempotency-key`. */
  readonly cabecalhoDeIdempotencia?: string;
  /** Tecto de quem chama; so desce (ver `consumeLimit`). */
  readonly limite?: number | null;
  readonly cache?: CacheDeEntitlements;
  readonly metricas?: MetricasDoTen;
  readonly agora?: Date | null;
}

/**
 * Verifica o entitlement e, se houver chave, consome o limite.
 *
 * Pela ordem, e a ordem importa: um tenant sem o modulo activo recebe `403` e
 * **nao** consome nada. Consumir primeiro gastava o tecto de quem nem sequer
 * podia entrar.
 *
 * Devolve `null` quando o pedido pode seguir.
 */
export async function guardaHttp(
  bd: ClienteSql,
  pedido: Pedido,
  contexto: ContextoDoPedido,
  opcoes: OpcoesDoMiddleware,
): Promise<Recusa | null> {
  const tenant = contexto.tenantId;

  const entitlement = await checkEntitlement(bd, tenant, opcoes.modulo, {
    ...(opcoes.cache === undefined ? {} : { cache: opcoes.cache }),
    ...(opcoes.metricas === undefined ? {} : { metricas: opcoes.metricas }),
  });
  if (!entitlement.permitido) {
    return {
      estado: HTTP_ENTITLEMENT,
      corpo: { error: CODIGO_ENTITLEMENT_HTTP, modulo: entitlement.modulo },
      cabecalhos: {},
    };
  }

  if (opcoes.chave === undefined) return null;

  // A unica leitura do pedido que este modulo faz.
  const doCabecalho =
    pedido.cabecalhos[
      (opcoes.cabecalhoDeIdempotencia ?? CABECALHO_DE_IDEMPOTENCIA).toLowerCase()
    ];
  const idempotencyKey = opcoes.idempotencyKey ?? doCabecalho;
  if (typeof idempotencyKey !== "string" || idempotencyKey.trim() === "") {
    throw new ChaveDeIdempotenciaInvalidaError();
  }

  const consumo = await consumeLimit(
    bd,
    tenant,
    opcoes.chave,
    opcoes.quantidade ?? 1,
    idempotencyKey,
    {
      limite: opcoes.limite ?? null,
      agora: opcoes.agora ?? null,
      modulo: opcoes.modulo,
      ...(opcoes.metricas === undefined ? {} : { metricas: opcoes.metricas }),
    },
  );
  if (consumo.aceite) return null;

  // Sem tecto nenhum declarado para a chave nao e «excedeu»: e «nao tem». A
  // `0007` devolve `limite = NULL` nesse caso e o criterio 2 manda negar como
  // entitlement, com `403` — um `429` convidava a tentar outra vez no mes
  // seguinte, e nao ha mes nenhum que crie o entitlement em falta.
  if (consumo.motivo === "sem_entitlement") {
    return {
      estado: HTTP_ENTITLEMENT,
      corpo: { error: CODIGO_ENTITLEMENT_HTTP, modulo: opcoes.modulo, key: opcoes.chave },
      cabecalhos: {},
    };
  }
  return {
    estado: HTTP_LIMITE,
    corpo: { error: CODIGO_LIMITE, key: opcoes.chave },
    // Sem `Retry-After`: o periodo fecha no primeiro dia do mes em
    // `Africa/Luanda` e o numero de segundos ate la nao e desta funcao — vinha
    // de um calculo de calendario que so a base faz (`platform.ten_periodo`), e
    // escreve-lo aqui era a terceira copia do fuso.
    cabecalhos: {},
  };
}
