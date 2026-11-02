/**
 * O *handler* genérico `POST /hooks/pay/{provider}/{webhook_token}` (KAM-053).
 *
 * Corre no serviço `pay` atrás do GWY. **O serviço `pay` não existe nesta
 * árvore** — os cinco são `agr`, `com`, `gwy`, `onboarding-web` e
 * `worker-canal` —, e é a dívida documental 148, que o KAM-052 abriu quando pôs
 * o `pay-core` aqui em vez de em `services/pay/`. Este módulo segue a mesma
 * decisão por consistência e por uma razão que não é só essa: o que ele
 * entrega é uma **fábrica de rotas** sobre portas, e é essa forma que deixa o
 * serviço montá-lo quando existir sem o reescrever.
 *
 * ## A ordem é o ticket, e não uma preferência
 *
 * O `../docs/tecnica/04` §5.1 escreve o fluxo e a ordem é vinculativa:
 *
 *     acct    = accounts.by_webhook_token(token)   # 404 uniforme se não resolver
 *     receipt = inbox.insert(...)                  # DURÁVEL antes de qualquer 2xx
 *     evs     = provider.verifyCallback(raw, acct) # G1
 *     return 200                                   # o resto é assíncrono
 *
 * **O `inbox.insert` vem antes do `verifyCallback`**, e isso parece errado à
 * primeira vista — porque é gravar o que ainda não se sabe se é genuíno. É
 * deliberado, e as duas razões são diferentes:
 *
 * * um 2xx dado antes da gravação perde o callback se o processo morrer entre a
 *   resposta e a escrita, e o facilitador já não o repete;
 * * uma entrega com HMAC inválido é **exactamente** o que se quer guardado: o
 *   F-05 do §7.2 alerta sobre «falhas de HMAC por conta, por hora», e sem a
 *   linha no *inbox* não há o que contar.
 *
 * ## O que este *handler* **não** faz, e é metade do seu valor
 *
 * Não escreve no ledger. O §5.1 põe isso no `worker(receipt)`, que corre
 * **depois** do 2xx, como `kamba_app`, com o contexto do tenant já resolvido do
 * *token* — e é por isso que o papel `kamba_pay_hooks` não tem `EXECUTE` na
 * `append_payment_event`: a RLS recusar-lhe-ia a cobrança de qualquer forma.
 *
 * Não decide nada a partir do corpo. Para os facilitadores **sem assinatura**
 * (OPG, EMIS, MoMenu) o §5 é explícito: «o callback é apenas uma **dica**», o
 * PAY executa `status()` e só então avalia G2–G7. Este módulo marca a entrega
 * como `ignorado` e devolve 200 — e o que não faz é tratar uma dica como
 * confirmação.
 *
 * ## Os três códigos, e porque são estes
 *
 *     404   *token* desconhecido. **Uniforme**: o mesmo corpo e o mesmo tempo
 *           que um *token* conhecido levaria, porque a diferença é um oráculo
 *           para quem varre *tokens*. A entrega grava-se com `account_id` nulo
 *     401   HMAC inválido. `inbox.estado = 'hmac_invalido'`, `authn_ok = false`,
 *           e **zero** linhas no ledger
 *     200   tudo o resto, incluindo um corpo que o adaptador não entende: o
 *           facilitador não tem de repetir o que já ficou durável
 */

import { AuthError } from "./tipos.ts";
import type { Minor, Moeda, RawHttpCallback, VerifiedEvent } from "./tipos.ts";
import type { Uuid } from "./tipos.ts";

/** O caminho do §5.1, com os dois segmentos. */
export const CAMINHO_DO_HOOK = "/hooks/pay/:provider/:webhook_token";

/** `callback_ack_ms`, a métrica do §14 («2xx p99 < 500 ms»). */
export const METRICA_ACK = "callback_ack_ms";

/** `payment_events_total{tipo}`, a métrica do DoD. Emitida pelo *worker*. */
export const METRICA_EVENTOS = "payment_events_total";

/** O alerta do F-05: HMAC inválido por conta. */
export const ALERTA_HMAC = "pay_hmac_invalido";

/** O corpo do 404, **igual** para todo o *token* que não resolve. */
export const CORPO_DO_404 = { recibo: "token_desconhecido" } as const;

/** Tecto do corpo, em octetos. Acima disto nem se grava: ver `TECTO_DO_CORPO`. */
export const TECTO_DO_CORPO = 64 * 1024;

/**
 * Os estados de `payment_callbacks_inbox` que este *handler* escreve.
 *
 * O `processado` e o `duplicado` são do *worker*, não deste caminho: aqui a
 * entrega está no máximo `recebido`, e quem a processa é quem a marca.
 */
export type EstadoDaEntrega =
  | "recebido"
  | "hmac_invalido"
  | "token_desconhecido"
  | "ignorado"
  | "erro";

/** A conta que o *token* resolve, pela `platform.resolve_webhook_token`. */
export type ContaDoToken = {
  readonly accountId: Uuid;
  readonly tenantId: Uuid | null;
  readonly provider: string;
  readonly entidade: string | null;
  readonly posId: string | null;
  readonly estado: string;
};

/**
 * O *inbox*, como porta.
 *
 * `inserir` devolve o identificador da linha — o `receipt` do §5.1 — e tem de
 * ser **durável** quando a promessa resolve. Uma implementação que o fizesse em
 * memória e escrevesse depois cumpria a assinatura e quebrava o ticket, e é por
 * isso que está escrito aqui e não só no comentário da revisão.
 */
export type Inbox = {
  inserir(entrega: {
    readonly accountId: Uuid | null;
    readonly corpo: Uint8Array;
    readonly corpoHash: Uint8Array;
    readonly cabecalhos: Readonly<Record<string, string>>;
    // `| undefined` explicito: o `exactOptionalPropertyTypes` do
    // `tsconfig` desta arvore distingue «ausente» de «presente e
    // undefined», e quem chama passa o `sourceIp` de um pedido que pode
    // nao o ter. Medido no gate 1.
    readonly sourceIp?: string | undefined;
    readonly estado: EstadoDaEntrega;
  }): Promise<bigint>;
  marcar(
    recibo: bigint,
    estado: EstadoDaEntrega,
    campos?: { readonly authnOk?: boolean; readonly erro?: string },
  ): Promise<void>;
};

/** O que o *handler* precisa de um adaptador, e nada mais. */
export type AdaptadorDoHook = {
  /** `none` e o callback é dica: segue por `status_pull` (§5). */
  readonly callbackAuth: "hmac" | "none" | "desconhecido";
  verifyCallback(
    raw: RawHttpCallback,
    conta: ContaDoToken,
  ): Promise<readonly VerifiedEvent[]>;
};

/** O que fica para o *worker*, depois do 2xx. */
export type TrabalhoDoWorker = {
  readonly recibo: bigint;
  readonly conta: ContaDoToken;
  readonly eventos: readonly VerifiedEvent[];
  /** `true` quando o callback é só uma dica e o estado se puxa (§5). */
  readonly porConsulta: boolean;
};

export type DependenciasDoHook = {
  readonly inbox: Inbox;
  resolverToken(token: string): Promise<ContaDoToken | null>;
  adaptador(provider: string): AdaptadorDoHook | null;
  /**
   * Encaminha o trabalho para o *worker*. **Não é esperado antes do 2xx**: o
   * §5.1 põe-no depois, e o que garante que nada se perde é o *inbox* já
   * gravado — não a entrega deste encaminhamento.
   */
  encaminhar(trabalho: TrabalhoDoWorker): void;
  /**
   * O parametro chama-se `medida` e nao `valor`: o `money_lint` do gate 2 le
   * `valor: number` como um montante tipado `number` e recusa-o — com razao,
   * porque e assim que um IEEE-754 entra num caminho de dinheiro. Aqui sao
   * milissegundos, e o nome e que tem de o dizer.
   */
  medir?(metrica: string, medida: number, etiquetas?: Record<string, string>): void;
  alertar?(alerta: string, detalhe: Record<string, unknown>): void;
  sha256(corpo: Uint8Array): Uint8Array;
  /** `| undefined` explicito: `exactOptionalPropertyTypes` (ver `Inbox`). */
  readonly agora?: (() => number) | undefined;
};

export type PedidoDoHook = {
  readonly provider: string;
  readonly token: string;
  readonly corpo: Uint8Array;
  readonly cabecalhos: Readonly<Record<string, string>>;
  readonly sourceIp?: string;
};

export type RespostaDoHook = {
  readonly estado: 200 | 401 | 404 | 413;
  readonly corpo: Readonly<Record<string, unknown>>;
};

/** O recibo que o 200 devolve. Não revela nada sobre a conta. */
const CORPO_DO_200 = { recibo: "recebido" } as const;

/**
 * Atende um callback. Devolve o que o HTTP deve responder.
 *
 * Separado do *framework* de propósito: o que o critério 7 mede — a ordem, os
 * três códigos, o `authn_ok` e as zero linhas no ledger — não depende de Hono
 * nenhum, e um ensaio que levantasse um servidor para o medir media também o
 * servidor. O que **precisa** de HTTP a sério é o p99 do ack, e esse levanta-o.
 */
export async function atenderCallback(
  pedido: PedidoDoHook,
  deps: DependenciasDoHook,
): Promise<RespostaDoHook> {
  const relogio = deps.agora ?? (() => Date.now());
  const inicio = relogio();
  const terminar = (resposta: RespostaDoHook): RespostaDoHook => {
    deps.medir?.(METRICA_ACK, relogio() - inicio, {
      estado: String(resposta.estado),
      provider: pedido.provider,
    });
    return resposta;
  };

  // O tecto vem **antes** da gravação, e é a única coisa que vem antes dela.
  // Um corpo de megabytes não é uma entrega de um facilitador: é uma via para
  // encher a tabela que o §5.1 manda tornar durável, e guardá-lo seria usar a
  // própria prova como munição.
  if (pedido.corpo.byteLength > TECTO_DO_CORPO) {
    return terminar({ estado: 413, corpo: { recibo: "corpo_grande" } });
  }

  const corpoHash = deps.sha256(pedido.corpo);
  const conta = await deps.resolverToken(pedido.token);

  // ------------------------------------------------- *token* desconhecido
  if (conta === null) {
    // **Grava, e só depois responde 404.** Guardar a entrega de um *token* que
    // não existe é o que torna um varrimento de *tokens* auditável — sem esta
    // linha, o 404 uniforme não deixa rasto nenhum.
    await deps.inbox.inserir({
      accountId: null,
      corpo: pedido.corpo,
      corpoHash,
      cabecalhos: redigir(pedido.cabecalhos),
      sourceIp: pedido.sourceIp,
      estado: "token_desconhecido",
    });
    return terminar({ estado: 404, corpo: CORPO_DO_404 });
  }

  // --------------------------------------------- a gravação, antes do 2xx
  const recibo = await deps.inbox.inserir({
    accountId: conta.accountId,
    corpo: pedido.corpo,
    corpoHash,
    cabecalhos: redigir(pedido.cabecalhos),
    sourceIp: pedido.sourceIp,
    estado: "recebido",
  });

  const adaptador = deps.adaptador(pedido.provider);
  if (adaptador === null) {
    // O corpo já está durável; o facilitador não tem de repetir. O que fica é
    // uma entrega em `erro` para ops, e não um 5xx que gera reentregas.
    await deps.inbox.marcar(recibo, "erro", {
      erro: `sem adaptador para ${pedido.provider}`,
    });
    return terminar({ estado: 200, corpo: CORPO_DO_200 });
  }

  // ------------------------------------- sem assinatura, o callback é dica
  if (adaptador.callbackAuth !== "hmac") {
    // §5: «Facilitadores sem assinatura (OPG, EMIS, MoMenu): o callback é
    // apenas uma **dica**; o PAY executa `status()` e só então avalia G2–G7.»
    //
    // O `authn_ok` fica **nulo** e não `false`: `false` diria «foi verificado e
    // falhou», e aqui não houve verificação nenhuma. A diferença conta no
    // alerta do F-05, que é sobre HMAC inválido e não sobre falta de HMAC.
    await deps.inbox.marcar(recibo, "ignorado");
    deps.encaminhar({ recibo, conta, eventos: [], porConsulta: true });
    return terminar({ estado: 200, corpo: CORPO_DO_200 });
  }

  // ---------------------------------------------------------------- G1
  let eventos: readonly VerifiedEvent[];
  try {
    eventos = await adaptador.verifyCallback(
      { corpo: pedido.corpo, cabecalhos: pedido.cabecalhos },
      conta,
    );
  } catch (erro) {
    if (erro instanceof AuthError) {
      await deps.inbox.marcar(recibo, "hmac_invalido", { authnOk: false });
      deps.alertar?.(ALERTA_HMAC, {
        account_id: conta.accountId,
        provider: pedido.provider,
      });
      // **Nada é encaminhado.** É isto que faz as «zero linhas em
      // payment_events» do critério 7 ser uma propriedade do caminho e não uma
      // consequência de o ledger recusar depois.
      return terminar({ estado: 401, corpo: { recibo: "hmac_invalido" } });
    }
    await deps.inbox.marcar(recibo, "erro", { erro: mensagem(erro) });
    return terminar({ estado: 200, corpo: CORPO_DO_200 });
  }

  deps.encaminhar({ recibo, conta, eventos, porConsulta: false });
  return terminar({ estado: 200, corpo: CORPO_DO_200 });
}

/**
 * Cabeçalhos **sem segredos**, que é o que o §6.2 escreve sobre a coluna.
 *
 * A lista é de **inclusão** e não de exclusão, e a diferença é a que importa:
 * uma lista de exclusão guarda tudo o que alguém não se lembrou de proibir, e o
 * cabeçalho de assinatura de um facilitador novo entra por aí. O que se guarda
 * é o que serve para depurar uma entrega, e mais nada.
 */
export const CABECALHOS_GUARDADOS = [
  "content-type",
  "content-length",
  "user-agent",
  "x-request-id",
  "x-forwarded-for",
] as const;

export function redigir(
  cabecalhos: Readonly<Record<string, string>>,
): Readonly<Record<string, string>> {
  const guardados: Record<string, string> = {};
  for (const [nome, valor] of Object.entries(cabecalhos)) {
    const chave = nome.toLowerCase();
    if ((CABECALHOS_GUARDADOS as readonly string[]).includes(chave)) {
      guardados[chave] = valor;
    }
  }
  return guardados;
}

function mensagem(erro: unknown): string {
  return erro instanceof Error ? erro.message : String(erro);
}

/**
 * A chamada à porta do ledger, pelo *worker*, com os argumentos pela ordem da
 * `platform.append_payment_event`.
 *
 * Existe aqui — e não como cadeia de SQL no serviço — para que a suite de base
 * de dados possa exercitar **este** texto em vez de uma cópia dele, como a do
 * KAM-043 faz com o `consultas.ts`. Uma cópia prova que a cópia funciona.
 */
export const SQL_APPEND_PAYMENT_EVENT = `
  SELECT event_id, sequencia, row_hash, estado_novo, outbox_event_id
    FROM platform.append_payment_event(
      p_charge_id => $1, p_tipo_evento => $2, p_account_id => $3,
      p_valor_minor => $4, p_authn_method => $5, p_authn_ok => $6,
      p_decisao => $7, p_motivo => $8, p_actor_kind => $9, p_actor_id => $10,
      p_provider_event_id => $11, p_payload => $12, p_ocorrido_at => $13)
`;

/** A resolução do *token*, pelo papel estreito e sem contexto de tenant. */
export const SQL_RESOLVE_WEBHOOK_TOKEN = `
  SELECT account_id, tenant_id, provider, entidade, pos_id, estado
    FROM platform.resolve_webhook_token($1)
`;

/** A gravação do §5.1, durável antes do 2xx. */
export const SQL_INBOX_INSERT = `
  INSERT INTO platform.payment_callbacks_inbox
    (account_id, body, body_hash, headers, source_ip, estado)
  VALUES ($1, $2, $3, $4, $5, $6)
  RETURNING id
`;

/** A marcação. **Só as quatro colunas que o `GRANT` por coluna concede.** */
export const SQL_INBOX_MARK = `
  UPDATE platform.payment_callbacks_inbox
     SET estado = $2, authn_ok = $3, erro = $4, processado_at = now()
   WHERE id = $1
`;

/** O tipo de evento de *outbox*, do mapa que o KAM-055 enche. */
export const SQL_OUTBOX_MAP = `
  SELECT evt_tipo, evt_versao FROM platform.payment_outbox_map
   WHERE tipo_evento = $1 AND authn_method = $2
`;

/**
 * Os nomes que a suite de base de dados lê deste módulo, nos dois sentidos.
 *
 * Nos **dois** sentidos: uma cadeia aqui que nenhum ensaio exercite é uma
 * cadeia que nunca correu contra um PostgreSQL, e o que o gate 4 mede sobre ela
 * é se o ficheiro compila.
 */
export const CADEIAS_EXERCITADAS = [
  "SQL_APPEND_PAYMENT_EVENT",
  "SQL_RESOLVE_WEBHOOK_TOKEN",
  "SQL_INBOX_INSERT",
  "SQL_INBOX_MARK",
  "SQL_OUTBOX_MAP",
] as const;

/** Os tipos de evento que o *worker* escreve, por veredicto de G2–G7. */
export type VeredictoDoWorker = "confirmado" | "divergente" | "orfao" | "duplicado";

/** O que o §5.1 manda o *worker* escrever, por veredicto. */
export const EVENTOS_DO_WORKER: Readonly<
  Record<VeredictoDoWorker, readonly string[]>
> = {
  // «append_payment_event('pagamento_recebido', …)» e depois a decisão.
  confirmado: ["pagamento_recebido", "pagamento_confirmado"],
  divergente: ["pagamento_recebido", "pagamento_divergente"],
  // G3: «não confirma, não reconhece no facilitador». O facto fica.
  orfao: ["pagamento_orfao"],
  // G7: «recibo duplicado (200, sem efeito)» — nada entra no ledger, porque o
  // `payment_events_entrega_uq` já o tem.
  duplicado: [],
} as const;

export type { Minor, Moeda };
