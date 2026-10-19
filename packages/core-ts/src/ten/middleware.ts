/**
 * O *middleware* HTTP do TEN (KAM-009, criterios 2, 3 e 7).
 *
 *     403 ENTITLEMENT_DISABLED   o modulo nao esta activo para este tenant
 *     403 LIMIT_EXCEEDED         o tecto **por pedido** nao chega (nao reabre)
 *     429 LIMIT_EXCEEDED         o balde do periodo nao chega (reabre no mes)
 *
 * ## A chave de idempotencia e **derivada**, e nao a do cabecalho
 *
 * O cabecalho `Idempotency-Key` e de quem chama, e a chave de idempotencia
 * decide o **ambito da desduplicacao** — que e do servidor. Aceitar o
 * cabecalho tal como vem era deixar o cliente escolher o que conta como «o
 * mesmo pedido». Aqui o cabecalho entra como **um componente** de
 * `derivarChaveDeIdempotencia`, atras do tenant, do modulo e da chave de
 * limite; a chave que chega a `platform.ten_consumir` e o `sha256` dos
 * quatro. A quantidade fica de fora de proposito — ver a nota na funcao.
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
  HTTP_TECTO,
  checkCeiling,
  checkEntitlement,
  consumeLimit,
  derivarChaveDeIdempotencia,
} from "./entitlements.ts";
import { normalizarTenant } from "../tenant_guard/index.ts";

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
  /**
   * A chave de limite a **consumir** (um balde por periodo). Sem ela, so se
   * verifica o entitlement. Uma chave que o registo marque
   * `x-kamba-consumivel: false` levanta — e o `tecto` que serve essas.
   */
  readonly chave?: string;
  /** Quanto consumir. 1 por omissao. */
  readonly quantidade?: number;
  /**
   * Um tecto **por pedido** a verificar: a chave e o valor deste pedido.
   *
   * Verifica-se **antes** do consumo, e e essa a ordem que importa: um pedido
   * que nao cabe no tecto nao pode ter gasto o balde do mes a descobri-lo.
   * Nao escreve nada (`checkCeiling`).
   */
  readonly tecto?: { readonly chave: string; readonly valor: number };
  /**
   * A chave de idempotencia de quem chama (`02` §6.3), quando ha uma melhor
   * do que o cabecalho — por exemplo a derivada do `cart_id`. Ganha ao
   * cabecalho, e, tal como ele, e **um componente** da chave efectiva e nao a
   * chave inteira.
   */
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
 * Verifica o entitlement, depois o tecto do pedido, depois consome o limite.
 *
 * **A ordem e a decisao.** Tres passos, e cada um protege o seguinte:
 *
 * 1. `checkEntitlement` — um tenant sem o modulo activo recebe `403` e **nao**
 *    consome nada. Consumir primeiro gastava o tecto de quem nem sequer podia
 *    entrar.
 * 2. `checkCeiling` — um pedido que nao cabe no tecto por pedido recebe `403`
 *    e **tambem** nao consome nada. Esta e a ordem que a revisao adversarial
 *    exigiu: a verificacao do tecto nao escreve, e descobrir que um pedido de
 *    50 000 Kz nao passa depois de ja ter gasto o balde mensal e pagar duas
 *    vezes pelo mesmo erro.
 * 3. `consumeLimit` — so aqui se escreve, e so para baldes por periodo.
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

  if (opcoes.tecto !== undefined) {
    const cabimento = await checkCeiling(bd, tenant, opcoes.tecto.chave, opcoes.tecto.valor, {
      modulo: opcoes.modulo,
      ...(opcoes.metricas === undefined ? {} : { metricas: opcoes.metricas }),
    });
    if (!cabimento.cabe) {
      // Sem tecto declarado e falta de entitlement, como no consumo: a `0007`
      // e o `SQL_TECTO` dizem a mesma coisa com `NULL`, e o criterio 2 manda
      // negar como entitlement.
      if (cabimento.motivo === "sem_entitlement") {
        return {
          estado: HTTP_ENTITLEMENT,
          corpo: {
            error: CODIGO_ENTITLEMENT_HTTP,
            modulo: opcoes.modulo,
            key: cabimento.chave,
          },
          cabecalhos: {},
        };
      }
      // `403` e nao `429`: um tecto por pedido nao reabre no mes seguinte, e
      // um `429` convidava a repetir um pedido que sera sempre recusado. Ver
      // `HTTP_TECTO`.
      return {
        estado: HTTP_TECTO,
        corpo: { error: CODIGO_LIMITE, key: cabimento.chave },
        cabecalhos: {},
      };
    }
  }

  if (opcoes.chave === undefined) return null;

  // A unica leitura do pedido que este modulo faz.
  const doCabecalho =
    pedido.cabecalhos[
      (opcoes.cabecalhoDeIdempotencia ?? CABECALHO_DE_IDEMPOTENCIA).toLowerCase()
    ];
  const bruta = opcoes.idempotencyKey ?? doCabecalho;
  if (typeof bruta !== "string" || bruta.trim() === "") {
    throw new ChaveDeIdempotenciaInvalidaError();
  }
  // **A chave que vai a base e derivada, e nao a que o cliente mandou.** O que
  // vem no cabecalho e o ultimo componente; os tres primeiros sao do servidor.
  // Ver `derivarChaveDeIdempotencia`, incluindo a razao por que a quantidade
  // **nao** entra (ela e a impressao digital do `KA002`, e po-la aqui
  // desarmava-o).
  const idempotencyKey = derivarChaveDeIdempotencia(
    "ten.v1",
    normalizarTenant(tenant),
    opcoes.modulo,
    opcoes.chave,
    bruta,
  );

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
