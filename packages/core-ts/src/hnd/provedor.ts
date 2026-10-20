/**
 * O `HandoffProvider` sobre a base e o provedor (KAM-019).
 *
 * Junta a persistência com a conversa com o terceiro, e a sua contribuição
 * própria é a **ordem** — a mesma lição que o `outbound/adapter.ts` do KAM-015
 * escreveu:
 *
 * 1. **A linha antes do terceiro.** O `openHandoff` escreve em `handoffs`
 *    **antes** de criar a conversa no provedor. Ao contrário, uma falha entre
 *    a criação lá e a escrita aqui deixava uma conversa aberta no provedor sem
 *    nada do nosso lado a apontar-lhe — e a repetição criava outra. O
 *    `ON CONFLICT (handoff_id) DO NOTHING RETURNING` vazio é o que diz «já
 *    passou», e nesse caso **não há chamada ao provedor nenhuma** (critério 4).
 * 2. **O espelho é uma fila e não uma chamada.** O `mirrorMessage` enfileira
 *    com `jobId` derivado do `wamid`; a idempotência do critério 3 é a
 *    de-duplicação que a fila já faz, e a reconciliação que o §14 pede é o
 *    recuo dela. Chamar o provedor em linha fazia cada mensagem do cliente
 *    esperar por um terceiro.
 * 3. **O provedor em baixo degrada, não falha.** Se o `abrirConversa` levantar
 *    `ProvedorIndisponivelError`, a passagem fica `degraded` e a abertura vai
 *    para a fila: a linha existe, o painel vê o atraso, e o critério 9 é isso.
 *
 * ## O `setBotMuted` levanta
 *
 * É a única das seis operações que este ticket não pode cumprir. Ver a nota do
 * `contrato.ts`: silenciar o bot é escrever `conversations.mode`, `kamba_app`
 * não tem esse privilégio, e as transições são do KAM-018.
 */

import { Logger } from "../logger/index.ts";
import type { ChannelContext } from "../chr/index.ts";
import { avaliar, type MotivoDeRecusa, type Veredicto } from "./assinatura.ts";
import {
  PROVEDORES,
  ProvedorIndisponivelError,
  SemPrivilegioError,
  type ClienteDoProvedor,
  type ClienteSql,
  type ContaDeAtendimento,
  type EstadoDeHandoff,
  type HandoffAberto,
  type HandoffProvider,
  type HumanEvent,
  type LinhaDeHandoff,
  type MirrorMessage,
  type Outcome,
  type PedidoDeHandoff,
  type Provedor,
} from "./contrato.ts";
import { lerAcontecimento, type Corpo } from "./eventos.ts";
import { ESTADOS_QUE_FECHAM, concluido, estadoDe, outcomeDoProvedor } from "./estados.ts";
import {
  METRICA_HANDOFFS,
  METRICA_PENDENTES,
  METRICA_RECUSAS,
  MetricasDoHnd,
} from "./metricas.ts";
import {
  SQL_ABRIR_HANDOFF,
  SQL_CONTA,
  SQL_FECHAR,
  SQL_GUARDAR_CONTA,
  SQL_HANDOFF_POR_ID,
  SQL_MARCAR_ABERTA,
  SQL_MARCAR_DEGRADADA,
} from "./consultas.ts";

/**
 * A fila do espelho, por porta.
 *
 * `enfileirar` devolve `false` quando o `jobId` já estava na fila — é a
 * de-duplicação que torna o `mirrorMessage` idempotente por `wamid` sem tabela
 * nenhuma. O limite fica dito, e é o mesmo que o `chr/fila.ts` escreveu: um
 * *job* em `failed` **bloqueia** o mesmo `jobId` até sair, pelo que a janela de
 * `removeOnComplete` decide quanto tempo a de-duplicação dura.
 */
export interface FilaDoEspelho {
  enfileirar(jobId: string, carga: Readonly<Record<string, unknown>>): Promise<boolean>;
  /** Quantas mensagens estão à espera. Alimenta a `hnd_mirror_pendentes`. */
  pendentes(): Promise<number>;
}

/** O que o provedor precisa para funcionar. */
export interface Dependencias {
  readonly bd: ClienteSql;
  readonly provedor: ClienteDoProvedor;
  readonly fila: FilaDoEspelho;
  /** A `SecretRef` do *token* do bot, por *tenant*. Nunca o *token*. */
  readonly refDoToken: (tenantId: string) => string;
  /** O `secret` do bot de um *tenant*, para verificar os *callbacks*. */
  readonly segredoDoBot: (tenantId: string) => Promise<string>;
  readonly log?: Logger;
  readonly metricas?: MetricasDoHnd;
  /** Qual provedor. Um hoje; a coluna existe pelo ADR-012. */
  readonly qual?: Provedor;
}

/** O `HandoffProvider` sobre a base e o provedor de atendimento. */
export class Handoff implements HandoffProvider {
  readonly #bd: ClienteSql;
  readonly #provedor: ClienteDoProvedor;
  readonly #fila: FilaDoEspelho;
  readonly #refDoToken: (tenantId: string) => string;
  readonly #segredoDoBot: (tenantId: string) => Promise<string>;
  readonly #log: Logger | undefined;
  readonly #metricas: MetricasDoHnd;
  readonly #qual: Provedor;
  #handler: ((e: HumanEvent) => Promise<void>) | null = null;

  constructor(dependencias: Dependencias) {
    this.#bd = dependencias.bd;
    this.#provedor = dependencias.provedor;
    this.#fila = dependencias.fila;
    this.#refDoToken = dependencias.refDoToken;
    this.#segredoDoBot = dependencias.segredoDoBot;
    this.#log = dependencias.log;
    this.#metricas = dependencias.metricas ?? new MetricasDoHnd();
    this.#qual = dependencias.qual ?? PROVEDORES[0];
  }

  get metricas(): MetricasDoHnd {
    return this.#metricas;
  }

  /**
   * Cria (ou devolve) a conta de atendimento do *tenant*.
   *
   * **A idempotência é da chave `(tenant_id, provedor)`**, e é isso que faz do
   * critério 1 uma propriedade da base. O caminho rápido é uma leitura; só
   * quando não há linha é que se fala com o provedor.
   *
   * **A limitação fica dita, porque é real.** Duas chamadas **concorrentes**
   * para o mesmo *tenant* podem ambas passar a leitura e ambas criar conta no
   * provedor; a segunda perde o `ON CONFLICT` e devolve a linha da primeira, o
   * que deixa uma conta **órfã** no lado dele — um recurso que nenhuma
   * migração nossa pode desfazer, porque não é nosso. Não há aqui como evitá-lo
   * sem um *lock* que a assinatura não permite pedir: a linha precisa dos
   * identificadores que só a criação devolve, pelo que não se pode escrever
   * primeiro. O que se faz é **não o esconder**: conta-se e registra-se, para
   * que a órfã apareça antes de alguém a descobrir no painel do provedor. O
   * critério 1 fala de «chamado 2×», que é o caso sequencial, e esse não
   * duplica nada.
   */
  async ensureAccount(tenantId: string): Promise<ContaDeAtendimento> {
    const existente = await this.#conta(tenantId);
    if (existente !== null) return existente;

    const criada = await this.#provedor.criarConta(tenantId);
    const linhas = await this.#bd.query<{ account_id: string }>(SQL_GUARDAR_CONTA, [
      tenantId,
      this.#qual,
      criada.accountId,
      criada.inboxId,
      criada.botId,
      this.#refDoToken(tenantId),
    ]);
    if (linhas.rows.length === 0) {
      // Outra chamada ganhou. A conta que acabámos de criar no provedor fica
      // **órfã** — ver a nota do método. Não se devolve a nossa: devolve-se a
      // que está na base, que é a única que o resto da plataforma vai usar.
      this.#log?.warn({ outcome: "conta_de_handoff_orfa", tenant_id: tenantId });
      const vencedora = await this.#conta(tenantId);
      if (vencedora === null) {
        throw new Error(
          "o INSERT da conta de handoff nao devolveu linha e a leitura seguinte " +
            "tambem nao: a chave (tenant_id, provedor) conflituou com uma linha " +
            "que a RLS nao deixa ver, o que significa contexto de tenant errado",
        );
      }
      return vencedora;
    }
    return criada;
  }

  /**
   * Espelha uma mensagem no provedor. Idempotente por `wamid`.
   *
   * Enfileira e devolve; não chama o provedor. A fila é a idempotência (o
   * `jobId` **é** o `wamid`) e é a reconciliação do §14 — com o provedor em
   * baixo, as mensagens acumulam e o recuo volta a tentá-las. O `ctx` é o do
   * CHR e é o que traz o *tenant*: o espelho não recebe `tenant_id` solto,
   * porque o `tenant_id` nasce no CHR e nenhum passo seguinte o recebe de fora.
   */
  async mirrorMessage(ctx: ChannelContext, m: MirrorMessage): Promise<void> {
    const aceite = await this.#fila.enfileirar(this.#jobDoEspelho(m.wamid), {
      tenant_id: ctx.tenant_id,
      channel_id: ctx.channel_id,
      wamid: m.wamid,
      direccao: m.direccao,
      wa_type: m.waType,
      texto: m.texto,
      criado_em: m.criadoEm.toISOString(),
    });
    if (!aceite) {
      // Já estava na fila: a terceira chamada com o mesmo `wamid` não produz
      // mensagem nenhuma, que é o critério 3. Não é erro e não se registra como
      // tal — é o mecanismo a funcionar.
      return;
    }
    this.#metricas.medir(METRICA_PENDENTES, await this.#fila.pendentes());
  }

  /** O `jobId` do espelho. É o `wamid`, e é isso que de-duplica. */
  #jobDoEspelho(wamid: string): string {
    return `espelho:${wamid}`;
  }

  /**
   * Abre a passagem. Idempotente por `handoffId`.
   *
   * A ordem está na nota do módulo: linha primeiro, provedor depois. Cinco
   * chamadas concorrentes colidem na chave primária e só uma chega ao
   * `abrirConversa`.
   */
  async openHandoff(pedido: PedidoDeHandoff): Promise<HandoffAberto> {
    const nova = await this.#bd.query<{ handoff_id: string }>(SQL_ABRIR_HANDOFF, [
      pedido.handoffId,
      pedido.tenantId,
      pedido.conversationId,
      pedido.motivo,
    ]);
    if (nova.rows.length === 0) {
      // A passagem já existia: **sem chamada ao provedor**. Devolve o que está.
      const linha = await this.#porId(pedido.tenantId, pedido.handoffId);
      return {
        externalId: linha?.external_id ?? "",
        repetido: true,
        estado: (linha?.status as EstadoDeHandoff | undefined) ?? "waiting",
      };
    }

    const conta = await this.ensureAccount(pedido.tenantId);
    let externalId: string;
    try {
      externalId = await this.#provedor.abrirConversa({
        conta,
        handoffId: pedido.handoffId,
        contactId: pedido.contactId,
        resumo: pedido.resumo,
      });
    } catch (erro) {
      if (!(erro instanceof ProvedorIndisponivelError)) throw erro;
      await this.#bd.query(SQL_MARCAR_DEGRADADA, [pedido.tenantId, pedido.handoffId]);
      await this.#fila.enfileirar(`abertura:${pedido.handoffId}`, {
        tenant_id: pedido.tenantId,
        handoff_id: pedido.handoffId,
        contact_id: pedido.contactId,
        resumo: pedido.resumo,
      });
      this.#metricas.contar(METRICA_HANDOFFS, "degraded");
      this.#log?.warn({ outcome: "handoff_degradado", tenant_id: pedido.tenantId });
      return { externalId: "", repetido: false, estado: "degraded" };
    }

    await this.#bd.query(SQL_MARCAR_ABERTA, [
      pedido.tenantId,
      pedido.handoffId,
      externalId,
      ["waiting", "degraded"],
    ]);
    this.#metricas.contar(METRICA_HANDOFFS, "waiting");
    this.#log?.info({ outcome: "handoff_aberto", tenant_id: pedido.tenantId });
    return { externalId, repetido: false, estado: "waiting" };
  }

  /** **Levanta.** Ver a nota do módulo e a do `contrato.ts`. */
  async setBotMuted(_conversationId: string, _muted: boolean): Promise<void> {
    throw new SemPrivilegioError(
      "setBotMuted",
      "silenciar o bot e escrever `conversations.mode`, e `kamba_app` nao tem " +
        "`UPDATE (mode)` — a revisao `0009` recusou-o por escrito e as " +
        "transicoes de modo sao do KAM-018, que o criterio 8 nomeia",
    );
  }

  onHumanEvent(handler: (e: HumanEvent) => Promise<void>): void {
    this.#handler = handler;
  }

  /**
   * Recebe um *callback* do provedor: autentica, lê e entrega.
   *
   * É o ponto de entrada que o critério 5 descreve, e a ordem é a do custo: o
   * segredo decide-se sem tocar na base, a conta precisa de uma leitura. Um
   * pedido sem segredo nunca chega a consultar nada, que é o que impede o uso
   * do *endpoint* como gerador de carga.
   */
  async receber(
    tenantId: string,
    segredoRecebido: string | null,
    corpo: Corpo,
  ): Promise<Veredicto> {
    const esperado = await this.#segredoDoBot(tenantId);
    const conta = await this.#conta(tenantId);
    const veredicto = avaliar(segredoRecebido, esperado, conta !== null);
    if (!veredicto.aceite) return this.#recusar(tenantId, veredicto.motivo, veredicto);

    const acontecimento = lerAcontecimento(corpo);
    if (acontecimento === null) {
      return this.#recusar(tenantId, "tipo_desconhecido", {
        aceite: false,
        motivo: "tipo_desconhecido",
        estado: 401,
      });
    }

    if (acontecimento.acontecimento === "estado_mudou" && acontecimento.estado !== null) {
      const outcome = outcomeDoProvedor(acontecimento.estado);
      if (outcome !== null) await this.close(acontecimento.handoffId, outcome);
    }
    if (this.#handler !== null) await this.#handler(acontecimento);
    return { aceite: true };
  }

  #recusar(tenantId: string, motivo: MotivoDeRecusa, veredicto: Veredicto): Veredicto {
    this.#metricas.contar(METRICA_RECUSAS, motivo);
    // O `outcome` leva o motivo, que e o que a *allowlist* do registo aceita —
    // nao ha campo `motivo` nela, e esta certa em nao ter: o motivo **e** o
    // desfecho. Nunca o corpo do *callback*, nunca o segredo.
    this.#log?.warn({ outcome: `callback_recusado_${motivo}`, tenant_id: tenantId });
    return veredicto;
  }

  /**
   * Fecha a passagem. O `resolved` duplicado é *no-op* **pela base**.
   *
   * O `WHERE status = ANY($3)` é a monotonia no predicado: o segundo `UPDATE`
   * não casa e devolve zero linhas, e é isso que o critério 7 pede. O *tenant*
   * vem do contexto da sessão porque a assinatura do §11.1 não o tem — ver a
   * nota do `SQL_FECHAR`.
   */
  async close(handoffId: string, outcome: Outcome): Promise<void> {
    const estado = estadoDe(outcome);
    const linhas = await this.#bd.query<{ status: string }>(SQL_FECHAR, [
      handoffId,
      estado,
      [...ESTADOS_QUE_FECHAM],
      null,
    ]);
    if (linhas.rows.length === 0) return;
    this.#metricas.contar(METRICA_HANDOFFS, estado);
  }

  /** `true` quando a passagem já está concluída. */
  async concluida(tenantId: string, handoffId: string): Promise<boolean> {
    const linha = await this.#porId(tenantId, handoffId);
    return linha !== null && concluido(linha.status);
  }

  async #conta(tenantId: string): Promise<ContaDeAtendimento | null> {
    const linhas = await this.#bd.query<{
      account_id: string;
      inbox_id: string;
      bot_id: string;
    }>(SQL_CONTA, [tenantId, this.#qual]);
    const linha = linhas.rows[0];
    return linha === undefined
      ? null
      : {
          accountId: Number(linha.account_id),
          inboxId: Number(linha.inbox_id),
          botId: Number(linha.bot_id),
        };
  }

  async #porId(tenantId: string, handoffId: string): Promise<LinhaDeHandoff | null> {
    const linhas = await this.#bd.query<LinhaDeHandoff>(SQL_HANDOFF_POR_ID, [
      tenantId,
      handoffId,
    ]);
    return linhas.rows[0] ?? null;
  }
}
