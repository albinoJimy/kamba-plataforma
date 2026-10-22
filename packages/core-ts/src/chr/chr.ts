/**
 * O CHR: o que acontece a uma `message` ou a um `echo` depois do KAM-013.
 *
 * É a decisão toda, e é testável sem fila: recebe um `EventoDeEntrada` e
 * devolve o que fez. Quem o liga ao *worker* é
 * `services/worker-canal/src/entrada.ts`, substituindo o braço `chr` do
 * `Encaminhador`.
 *
 * ## A ordem, e cada passo é uma porta
 *
 * 1. **Resolver o canal** (`kamba_resolver`, sem contexto). Desconhecido →
 *    quarentena `canal_desconhecido`, 0 *jobs*, alerta (critério 2).
 * 2. **Guarda do Fluxo B** (ADR-011, em memória, sobre o que o passo 1 trouxe).
 *    Recusado → 0 *jobs*, alerta (critério 5).
 * 3. **Matriz de estados** (§7.2, pelo `tenantGate` do KAM-009). Se não
 *    autoriza `registar_entrada`, não se abre conversa nenhuma; se autoriza
 *    `registar_entrada` e não `processar_entrada`, abre-se a conversa e o AGR
 *    não recebe nada (critério 3).
 * 4. **Resolver o contacto** (`kamba_identity`, com contexto). É aqui que o
 *    BSUID e o telefone convergem no mesmo `contact_id` e que uma fusão emite
 *    `contact.merged` (critério 4).
 * 5. **Abrir a conversa** (`kamba_app`, com contexto). A janela de 24 h abre-se
 *    aqui.
 * 6. **Entregar.** `mode = bot` → AGR; qualquer outro modo, e todo o `echo` →
 *    dono/HND (critério 7). Um `echo` nunca chega ao AGR.
 *
 * **O `tenant_id` nasce no passo 1 e mais nada o produz.** Nenhum dos passos
 * seguintes o recebe de fora: vem sempre do `ChannelContext`, que é o que
 * `docs/tecnica/01` §7.2 exige para a ToolLayer só aceitar o que vier do estado.
 *
 * ## Três ligações, três papéis, e nenhuma faz o trabalho de outra
 *
 * `kamba_resolver` para o passo 1 e para a guarda de arranque; `kamba_identity`
 * para o passo 4; `kamba_app` para o passo 5. É o padrão do `consumidor.ts`,
 * que já abre duas ligações com dois papéis. Dar uma ligação só — a de
 * `kamba_batch`, que vê tudo — resolvia os três passos e era exactamente o que
 * o ADR-015 recusa.
 *
 * ## Este módulo não lança por nada que venha do corpo
 *
 * Um canal desconhecido, uma mensagem sem identidade, um Fluxo B, um estado que
 * recusa: nenhum é erro. O que lança é o que vier da base, que é o que uma
 * retentativa pode resolver — e é assim que o `registo.ts` do KAM-013 distingue
 * «já tratado» de «repetir»: se o braço `chr` lançar, o `processado_at` não é
 * escrito e o *job* volta à fila.
 *
 * ## O que este módulo **não** faz
 *
 * Não envia (KAM-015), não transita modos (KAM-018), não espelha no Chatwoot
 * (KAM-019), não pede consentimento (KAM-022) e **não limita a frequência da
 * mensagem estática**: a célula `suspenso` da matriz diz «uma vez por
 * contacto/24 h», e o que a matriz responde é «pode», não «quantas vezes» — a
 * contagem por contacto é de quem envia (`docs/tecnica/01` §8, e a docstring do
 * `ten/estados.ts` já o escreve). O resultado leva a acção que a matriz
 * autoriza (`saida`) para quem enviar a usar.
 */

import type { EventoDeEntrada, Interlocutor } from "../entrada/explosao.ts";
import { type Accao, type DecisaoDoGate, tenantGate } from "../ten/estados.ts";
import type { ResolvedorDeCanal } from "./canal.ts";
import { abrirConversa, type Conversa } from "./conversas.ts";
import {
  type AgentInvocation,
  type ChannelContext,
  type ClienteDoChr,
  type Desfecho,
  MODO_POR_OMISSAO,
  type Modo,
  type MotivoDoChr,
} from "./contrato.ts";
import { recusaDoFluxoB } from "./fluxo_b.ts";
import { montarInvocacao } from "./invocacao.ts";
import {
  METRICA_EM_QUARENTENA,
  METRICA_RESOLUCOES,
  type MetricasDoChr,
} from "./metricas.ts";

/**
 * Para onde o CHR entrega. Uma porta por destino, como o `Encaminhador` do
 * KAM-013 — e pela mesma razão: o tratador é de outro ticket, e um tratador
 * inventado aqui era desenho sem critério de aceitação.
 */
export interface EntregaDoChr {
  /** O turno vai ao AGR (KAM-025). Idempotente: ver `jobIdDe`. */
  agr(invocacao: AgentInvocation): Promise<void>;
  /**
   * A mensagem vai ao dono ou ao Chatwoot (KAM-018, KAM-019).
   *
   * Recebe o contexto e o modo, e **não** uma invocação: o contrato
   * `agent_invocation` é do AGR, e o que o dono recebe é desenho do KAM-019.
   */
  dono(entrega: {
    readonly contexto: ChannelContext;
    readonly conversationId: string | null;
    readonly contactId: string | null;
    readonly wamid: string;
    readonly modo: Modo | null;
    /**
     * Quem está do outro lado, **só nos `echo`** e `null` numa `message`.
     *
     * Acrescentado pelo KAM-017, e é o mínimo que o faz funcionar. Numa
     * `message` o contacto já vem resolvido no `contactId`; num `echo` o CHR
     * **não** o resolve de propósito — ver a nota do ramo do `echo` em
     * `tratar` —, e o tratador da coexistência precisa do destinatário para
     * saber que conversa transitar. Passá-lo aqui mantém o CHR sem resolver
     * identidade num `echo`, que é a propriedade que aquela nota protege.
     */
    readonly interlocutor?: Interlocutor | null;
  }): Promise<void>;
}

/** Quem põe uma linha na quarentena. É o `porEmQuarentena` do KAM-013. */
export interface Quarentena {
  (evento: EventoDeEntrada, motivo: MotivoDoChr): Promise<void>;
}

/** Quem resolve o contacto. É o `resolveContact` do KAM-008, já com a ligação. */
export interface ResolucaoDeContacto {
  (pedido: {
    readonly tenantId: string;
    readonly bsuid: string | null;
    readonly telefone: string | null;
  }): Promise<{ readonly contactId: string }>;
}

/** O que o CHR escreve no registo. Só campos da *allowlist* (KAM-068). */
export interface Registo {
  (campos: {
    readonly outcome: string;
    readonly msg_id?: string;
    readonly wa_type?: string;
    readonly error_code?: string;
    readonly latency_ms?: number;
  }): void;
}

/** O que aconteceu a um evento no CHR. */
export interface ResultadoDoChr {
  readonly desfecho: Desfecho;
  /** O contexto resolvido, ou `null` se o canal é desconhecido. */
  readonly contexto: ChannelContext | null;
  /**
   * A decisão da matriz que **decidiu este desfecho**, ou `null` se não se
   * chegou lá.
   *
   * Não é sempre a mesma pergunta, e dizer «a de `processar_entrada`» era
   * mentir num caso: num canal `desligado` é a de `registar_entrada`, porque é
   * essa que nega primeiro. Hoje as duas coincidem em `permitido`, e num regime
   * futuro em que `registar_entrada` seja falso e `processar_entrada` verdadeiro
   * deixariam de coincidir. Quem precisa de saber **qual** das duas lê o
   * `desfecho`: `estado_recusou` sem `conversationId` é a primeira, com
   * `conversationId` é a segunda. Achado da revisão adversarial.
   */
  readonly decisao: DecisaoDoGate | null;
  /**
   * A saída automática que a matriz autoriza, ou `null`.
   *
   * É a coluna «Saída automática» do §7.2 em forma de acção: `mensagem_estatica`
   * num tenant ou canal `suspenso`, `mensagem_de_teste` em `pendente`. **Quem
   * envia é KAM-015**, e é lá que vive o «uma vez por contacto/24 h» — o que
   * este campo diz é o que é permitido, não quantas vezes.
   */
  readonly saida: Accao | null;
  readonly conversationId: string | null;
  readonly contactId: string | null;
  /** O *job* entregue ao AGR, ou `null`. Para os testes do critério 6. */
  readonly invocacao: AgentInvocation | null;
  /** O motivo de quarentena, ou `null`. */
  readonly motivo: MotivoDoChr | null;
}

/**
 * Uma transacção com contexto de tenant, sobre a ligação de `kamba_app`.
 *
 * **Não recebe o cliente**, e isso resolve um problema de tipos real: o
 * `comTenant` de `@kamba/core-ts/tenant_guard` declara o seu `ClienteSql` com
 * `query` a devolver `Promise<unknown>` — propositadamente lato, porque não lê
 * nada —, e uma função que receba um cliente **mais estreito** não é atribuível
 * a uma que receba um mais lato. Quem monta o CHR fecha sobre a sua própria
 * ligação e passa-a nos dois sítios, que é o que o `entrada.ts` faz:
 *
 * ```ts
 * comTenant: (tenant, trabalho) => comTenant(bd, tenant, () => trabalho(bd))
 * ```
 *
 * E ganha-se uma propriedade: o CHR não tem ligação nenhuma à mão fora de uma
 * transacção com contexto. Não há como escrever em `conversations` sem passar
 * por aqui.
 */
export type ComTenant = <T>(
  tenant: string,
  trabalho: (cliente: ClienteDoChr) => Promise<T>,
) => Promise<T>;

/** As acções que o CHR pergunta à matriz. */
const REGISTAR: Accao = "registar_entrada";
const PROCESSAR: Accao = "processar_entrada";
const ESTATICA: Accao = "mensagem_estatica";
const TESTE: Accao = "mensagem_de_teste";

/**
 * A saída automática que o regime autoriza, pela ordem do §7.2.
 *
 * `mensagem_estatica` antes de `mensagem_de_teste` porque é a única das duas
 * que a tabela escreve como saída de uma linha (`suspenso`); a mensagem de
 * teste é a nota da linha `pendente`. Num regime que autorize as duas — o
 * `ativo` — não há saída automática a anunciar, e é por isso que esta função só
 * é chamada quando `processar_entrada` **não** é permitido.
 */
function saidaAutomatica(
  estadoTenant: string,
  estadoCanal: string,
): Accao | null {
  if (tenantGate(estadoTenant, estadoCanal, ESTATICA).permitido) return ESTATICA;
  if (tenantGate(estadoTenant, estadoCanal, TESTE).permitido) return TESTE;
  return null;
}

/**
 * O CHR. Uma instância por processo.
 *
 * Não abre ligações nem filas: recebe as portas de quem a constrói, como todo
 * o resto desta biblioteca.
 */
export class Chr {
  readonly #resolvedor: ResolvedorDeCanal;
  readonly #contacto: ResolucaoDeContacto;
  readonly #entrega: EntregaDoChr;
  readonly #quarentena: Quarentena;
  readonly #metricas: MetricasDoChr;
  readonly #registar: Registo | undefined;
  readonly #agora: () => Date;
  readonly #comTenant: ComTenant;

  constructor(opcoes: {
    readonly resolvedor: ResolvedorDeCanal;
    readonly contacto: ResolucaoDeContacto;
    readonly entrega: EntregaDoChr;
    readonly quarentena: Quarentena;
    readonly metricas: MetricasDoChr;
    readonly registar?: Registo;
    readonly agora?: () => Date;
    readonly comTenant: ComTenant;
  }) {
    this.#resolvedor = opcoes.resolvedor;
    this.#contacto = opcoes.contacto;
    this.#entrega = opcoes.entrega;
    this.#quarentena = opcoes.quarentena;
    this.#metricas = opcoes.metricas;
    this.#registar = opcoes.registar;
    this.#agora = opcoes.agora ?? (() => new Date());
    this.#comTenant = opcoes.comTenant;
  }


  /**
   * Trata um evento `message` ou `echo`.
   *
   * @throws o que a base, a identidade ou a entrega lançarem. Nada do corpo
   *   lança: ver a nota do módulo.
   */
  async tratar(evento: EventoDeEntrada): Promise<ResultadoDoChr> {
    // ------------------------------------------------- 1. resolver o canal
    //
    // Um evento sem `phone_number_id` não é um canal desconhecido por acidente:
    // é um `change` cujo `value.metadata` não trouxe o identificador, e sem ele
    // não há pergunta a fazer. Vai à quarentena pelo mesmo motivo, porque o
    // efeito é o mesmo — não se sabe de quem é —, e **não** se chama o
    // resolvedor nem se mede uma resolução que não houve: um `null` a contar
    // como falha de *cache* estragava o `chr_cache_hit_ratio`.
    const phoneNumberId = evento.phoneNumberId;
    let resolvido = null;
    if (phoneNumberId !== null) {
      const inicio = this.#agora().getTime();
      const leitura = await this.#resolvedor.resolver(phoneNumberId);
      this.#metricas.resolucao(this.#agora().getTime() - inicio, leitura.daCache);
      resolvido = leitura.resolvido;
    }

    if (resolvido === null) {
      return this.#paraQuarentena(evento, "canal_desconhecido", null);
    }
    const { contexto, tipoTenant } = resolvido;

    // ------------------------------------------------ 2. guarda do Fluxo B
    const recusa = recusaDoFluxoB(contexto, tipoTenant);
    if (recusa !== null) {
      // **Sem linha de quarentena, e isso é a letra do critério 5**, que pede
      // «0 *jobs*, alerta». O alerta é a métrica e a linha de registo; o
      // `error_code` leva um código da lista fechada deste módulo e não do
      // corpo. Impedir que o caso exista em produção é da guarda de arranque
      // (`verificarArranque`), que corre antes de o processo aceitar trabalho.
      this.#metricas.contar(METRICA_RESOLUCOES, "fluxo_b_recusado");
      this.#registar?.({
        outcome: "chr_fluxo_b_recusado",
        error_code: "fluxo_b_recusado",
        ...(evento.waType === null ? {} : { wa_type: evento.waType }),
      });
      return {
        desfecho: "fluxo_b_recusado",
        contexto,
        decisao: null,
        saida: null,
        conversationId: null,
        contactId: null,
        invocacao: null,
        motivo: null,
      };
    }

    // ----------------------------------------------- 3. matriz de estados
    const registar = tenantGate(contexto.estado_tenant, contexto.estado_canal, REGISTAR);
    if (!registar.permitido) {
      // Um canal `desligado`: a matriz diz que não chega entrada, e se chegou,
      // chegou por um caminho que já não devia existir. Não se abre conversa.
      //
      // O `inbound_events` **já tem** a linha deste evento — foi escrita pelo
      // *worker* do KAM-013, antes de o CHR existir —, e por isso «registar»
      // aqui é a conversa e não o registo de entrada. Está em `docs/chr.md` §4.
      return this.#recusadoPeloEstado(evento, contexto, registar, {
        conversationId: null,
        contactId: null,
      });
    }

    // --------------------------------- 4. e 5. contacto e conversa
    //
    // Um `echo` nunca vai ao AGR: entrega-se ao dono sem contacto nem conversa
    // resolvidos aqui. E o caminho mais estreito que nao inventa identidade — o
    // CHR continua a **nao** resolver contacto num `echo`, e isso e deliberado:
    // o destinatario vem de um campo ***proposta*, NAO VERIFICADO**
    // (`CAMPO_DO_DESTINATARIO`, fixado pelo KAM-017), e quem decide o que fazer
    // com um destinatario que nao resolve e a coexistencia, que o conta em vez
    // de o descartar. O modo transita-se em KAM-018.
    if (evento.kind === "echo") {
      await this.#entrega.dono({
        contexto,
        conversationId: null,
        contactId: null,
        wamid: evento.eventKey,
        modo: null,
        // **O KAM-017 fixou o campo do destinatario**, e passa-se aqui em vez
        // de o resolver: a propriedade que esta nota protege — o CHR nao
        // resolve identidade num `echo` — fica intacta, e quem precisa do
        // contacto (a coexistencia) resolve-o do seu lado, onde ja tem a porta
        // do KAM-008 e sabe o que fazer com um destinatario que nao resolve.
        interlocutor: evento.interlocutor,
      });
      return this.#entregue(evento, contexto, { conversationId: null, contactId: null });
    }

    const interlocutor = evento.interlocutor;
    if (
      interlocutor === null ||
      (interlocutor.bsuid === null && interlocutor.telefone === null)
    ) {
      // Uma `message` sem `from` **e** sem `from_user_id`. Não se pode resolver
      // contacto, e lançar punha o BullMQ a repetir sete dias um corpo que
      // nunca melhora. Ver `MOTIVOS_DO_CHR`.
      return this.#paraQuarentena(evento, "mensagem_sem_identidade", contexto);
    }

    const { contactId } = await this.#contacto({
      tenantId: contexto.tenant_id,
      bsuid: interlocutor.bsuid,
      telefone: interlocutor.telefone,
    });

    const alvo = {
      tenantId: contexto.tenant_id,
      contactId,
      channelId: contexto.channel_id,
    };
    const conversa: Conversa = await this.#comTenant(
      contexto.tenant_id,
      async (cliente) => abrirConversa(cliente, alvo, this.#agora()),
    );

    // --------------------------------------------------------- 6. entregar
    if (conversa.mode !== MODO_POR_OMISSAO) {
      // «Mensagens com `conversations.mode` ≠ `bot` **não** vão ao AGR; vão ao
      // dono/HND» — critério 7, e invariante de `docs/tecnica/01` §10.2. A
      // verificação é **antes** da matriz: uma conversa em modo `humano` não
      // vai ao AGR mesmo num tenant `ativo`, e um canal `suspenso` não muda
      // quem tem a palavra.
      await this.#entrega.dono({
        contexto,
        conversationId: conversa.id,
        contactId,
        wamid: evento.eventKey,
        modo: conversa.mode,
      });
      return this.#entregue(evento, contexto, {
        conversationId: conversa.id,
        contactId,
      });
    }

    const processar = tenantGate(
      contexto.estado_tenant,
      contexto.estado_canal,
      PROCESSAR,
    );
    if (!processar.permitido) {
      // `pendente`, `suspenso` ou `encerrado`: a conversa fica registada e o
      // AGR não recebe nada. A saída automática vai no resultado.
      return this.#recusadoPeloEstado(evento, contexto, processar, {
        conversationId: conversa.id,
        contactId,
      });
    }

    const invocacao = montarInvocacao({
      contexto,
      contactId,
      conversationId: conversa.id,
      wamid: evento.eventKey,
      type: evento.waType ?? "outro",
      modo: conversa.mode,
    });
    await this.#entrega.agr(invocacao);
    this.#metricas.contar(METRICA_RESOLUCOES, "encaminhado");
    this.#registar?.({
      outcome: "chr_encaminhado",
      ...(evento.waType === null ? {} : { wa_type: evento.waType }),
    });
    return {
      desfecho: "encaminhado",
      contexto,
      decisao: processar,
      saida: null,
      conversationId: conversa.id,
      contactId,
      invocacao,
      motivo: null,
    };
  }

  async #paraQuarentena(
    evento: EventoDeEntrada,
    motivo: MotivoDoChr,
    contexto: ChannelContext | null,
  ): Promise<ResultadoDoChr> {
    await this.#quarentena(evento, motivo);
    this.#metricas.contar(METRICA_EM_QUARENTENA, motivo);
    this.#metricas.contar(METRICA_RESOLUCOES, "em_quarentena");
    // O que este módulo escreve é o `outcome` e um `error_code` da sua própria
    // lista fechada — nunca o `phone_number_id` nem o `event_key`, que a
    // *allowlist* do KAM-068 recusa de qualquer forma (erro de compilação).
    this.#registar?.({
      outcome: "chr_em_quarentena",
      error_code: motivo,
      ...(evento.waType === null ? {} : { wa_type: evento.waType }),
    });
    return {
      desfecho: "em_quarentena",
      contexto,
      decisao: null,
      saida: null,
      conversationId: null,
      contactId: null,
      invocacao: null,
      motivo,
    };
  }

  #recusadoPeloEstado(
    evento: EventoDeEntrada,
    contexto: ChannelContext,
    decisao: DecisaoDoGate,
    resto: {
      readonly conversationId: string | null;
      readonly contactId: string | null;
    },
  ): ResultadoDoChr {
    this.#metricas.contar(METRICA_RESOLUCOES, "estado_recusou");
    this.#registar?.({
      outcome: "chr_estado_recusou",
      error_code: `estado_${decisao.regime}`,
      ...(evento.waType === null ? {} : { wa_type: evento.waType }),
    });
    return {
      desfecho: "estado_recusou",
      contexto,
      decisao,
      saida: saidaAutomatica(contexto.estado_tenant, contexto.estado_canal),
      invocacao: null,
      motivo: null,
      ...resto,
    };
  }

  #entregue(
    evento: EventoDeEntrada,
    contexto: ChannelContext,
    resto: {
      readonly conversationId: string | null;
      readonly contactId: string | null;
    },
  ): ResultadoDoChr {
    this.#metricas.contar(METRICA_RESOLUCOES, "entregue_ao_dono");
    this.#registar?.({
      outcome: "chr_entregue_ao_dono",
      ...(evento.waType === null ? {} : { wa_type: evento.waType }),
    });
    return {
      desfecho: "entregue_ao_dono",
      contexto,
      decisao: null,
      saida: null,
      invocacao: null,
      motivo: null,
      ...resto,
    };
  }
}
