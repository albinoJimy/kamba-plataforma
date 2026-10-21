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
import {
  ESTADO_DE_RECUSA,
  avaliar,
  type MotivoDeRecusa,
  type Veredicto,
} from "./assinatura.ts";
import {
  PROVEDORES,
  ProvedorIndisponivelError,
  SemPrivilegioError,
  type ClienteDoProvedor,
  type ProvisionadorDoProvedor,
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
  /**
   * O provisionamento, **separado** do cliente de execução.
   *
   * Duas portas e não uma porque o `../docs/tecnica/08` §3.6 exige que o
   * *token* da Platform API só exista no serviço de *provisioning*: um objecto
   * que atenda conversas não pode ter o poder de criar contas.
   */
  readonly provisionador: ProvisionadorDoProvedor;
  readonly fila: FilaDoEspelho;
  /** A `SecretRef` do *token* do bot, por *tenant*. Nunca o *token*. */
  readonly refDoTokenDoBot: (tenantId: string) => string;
  /**
   * A `SecretRef` do *token* do utilizador da conta, por *tenant*.
   *
   * Duas referências porque são dois alcances: o do bot abre e fecha conversas,
   * o do utilizador cria *inboxes* e **contactos** — e o spike mediu que o do
   * bot responde 401 a criar um contacto, que é o que a conversa precisa.
   */
  readonly refDoTokenDoUtilizador: (tenantId: string) => string;
  /**
   * Guarda um segredo no cofre, pela sua referência.
   *
   * **Existe porque sem ele os dois *tokens* perdiam-se.** O provedor mostra o
   * `access_token` de um utilizador e de um bot **uma única vez**, no corpo da
   * criação; a primeira versão deste módulo não os capturava, pelo que nenhuma
   * operação posterior os podia usar. Esta porta é a que os leva ao cofre, e é
   * o único sítio deste ficheiro por onde um *token* em claro passa.
   */
  readonly guardarSegredo: (ref: string, segredo: string) => Promise<void>;
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
  readonly #provisionador: ProvisionadorDoProvedor;
  readonly #fila: FilaDoEspelho;
  readonly #refDoTokenDoBot: (tenantId: string) => string;
  readonly #refDoTokenDoUtilizador: (tenantId: string) => string;
  readonly #guardarSegredo: (ref: string, segredo: string) => Promise<void>;
  readonly #segredoDoBot: (tenantId: string) => Promise<string>;
  readonly #log: Logger | undefined;
  readonly #metricas: MetricasDoHnd;
  readonly #qual: Provedor;
  #handler: ((e: HumanEvent) => Promise<void>) | null = null;

  constructor(dependencias: Dependencias) {
    this.#bd = dependencias.bd;
    this.#provedor = dependencias.provedor;
    this.#provisionador = dependencias.provisionador;
    this.#fila = dependencias.fila;
    this.#refDoTokenDoBot = dependencias.refDoTokenDoBot;
    this.#refDoTokenDoUtilizador = dependencias.refDoTokenDoUtilizador;
    this.#guardarSegredo = dependencias.guardarSegredo;
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

    const criada = await this.#provisionador.criarConta(tenantId);
    // **Os segredos vão para o cofre antes de a linha existir.** A ordem é
    // deliberada: se isto falhar, não há linha e a conta fica órfã no provedor
    // — que é mau, mas visível e já contado abaixo. Ao contrário, uma linha
    // cujas `SecretRef` não têm nada atrás fazia **todas** as operações
    // seguintes falharem sem dizer porquê, e a passagem seguinte degradava
    // para uma fila que nunca drenaria.
    const refDoBot = this.#refDoTokenDoBot(tenantId);
    const refDoUtilizador = this.#refDoTokenDoUtilizador(tenantId);
    await this.#guardarSegredo(refDoBot, criada.tokenDoBot);
    await this.#guardarSegredo(refDoUtilizador, criada.tokenDoUtilizador);

    const linhas = await this.#bd.query<{ account_id: string }>(SQL_GUARDAR_CONTA, [
      tenantId,
      this.#qual,
      criada.conta.accountId,
      criada.conta.inboxId,
      criada.conta.botId,
      criada.conta.providerUserId,
      refDoBot,
      refDoUtilizador,
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
    return criada.conta;
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
        chaveDoContacto: pedido.chaveDoContacto,
        resumo: pedido.resumo,
      });
    } catch (erro) {
      if (!(erro instanceof ProvedorIndisponivelError)) throw erro;
      await this.#bd.query(SQL_MARCAR_DEGRADADA, [pedido.tenantId, pedido.handoffId]);
      await this.#fila.enfileirar(`abertura:${pedido.handoffId}`, {
        tenant_id: pedido.tenantId,
        handoff_id: pedido.handoffId,
        // A chave **opaca** e nunca o nosso `contact_id`. Ver a nota do
        // `PedidoDeHandoff`: a carga de uma fila e um sitio de onde um
        // identificador sai mais facilmente do que entrou.
        chave_do_contacto: pedido.chaveDoContacto,
        resumo: pedido.resumo,
      });
      this.#metricas.contar(METRICA_HANDOFFS, "degraded");
      this.#log?.warn({ outcome: "handoff_degradado", tenant_id: pedido.tenantId });
      return { externalId: "", repetido: false, estado: "degraded" };
    }

    // **O resultado le-se, e a primeira versao descartava-o.** O
    // `SQL_MARCAR_ABERTA` tem `AND status = ANY($4)`: se um
    // `conversation_status_changed` com `resolved` chegou entre a escrita da
    // linha e a volta do `abrirConversa` — e a janela e uma chamada HTTP a um
    // terceiro, com 10 s de tecto —, o `UPDATE` nao casa. Descartar as linhas
    // fazia tres coisas erradas de uma vez: dizia ao chamador que a passagem
    // estava `waiting` quando ela estava `resumed`, contava uma passagem
    // aberta que ja tinha fechado, e deixava a conversa criada no provedor
    // **sem nada a aponta-la**, sem um unico aviso.
    const marcada = await this.#bd.query<{ status: string }>(SQL_MARCAR_ABERTA, [
      pedido.tenantId,
      pedido.handoffId,
      externalId,
      ["waiting", "degraded"],
    ]);
    if (marcada.rows.length === 0) {
      // A passagem saiu de `waiting`/`degraded` enquanto o provedor respondia.
      // Devolve-se o `externalId` — ele existe e e o que correlaciona com a
      // conversa la fora — e o estado **verdadeiro**, lido da base.
      const linha = await this.#porId(pedido.tenantId, pedido.handoffId);
      this.#log?.warn({
        outcome: "handoff_aberto_fora_de_tempo",
        tenant_id: pedido.tenantId,
      });
      return {
        externalId,
        repetido: false,
        estado: (linha?.status as EstadoDeHandoff | undefined) ?? "waiting",
      };
    }
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
   * pedido **sem** segredo é recusado antes de qualquer I/O, que é o que
   * impede o uso do *endpoint* como gerador de carga. Um pedido **com** segredo
   * errado custa uma ida ao cofre e um `SELECT`, e isso é inevitável: para
   * saber que está errado é preciso saber qual era o certo.
   */
  async receber(
    tenantId: string,
    segredoRecebido: string | null,
    corpo: Corpo,
  ): Promise<Veredicto> {
    // **Sem segredo recusa-se aqui, antes de qualquer I/O**, e isto e a
    // correccao de um defeito. A nota desta funcao dizia que «um pedido sem
    // segredo nunca chega a consultar nada» e era falso: ia ao cofre **e**
    // fazia um `SELECT` antes de avaliar, pelo que o *endpoint* era utilizavel
    // como amplificador — um pedido vazio custava-nos duas idas a servicos.
    // Agora e verdade, e ha teste a afirmar que nada foi consultado.
    if (segredoRecebido === null || segredoRecebido.length === 0) {
      return this.#recusar(tenantId, "sem_secret", {
        aceite: false,
        motivo: "sem_secret",
        estado: ESTADO_DE_RECUSA,
      });
    }
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
      // **O `resolver` vai, e a primeira versao perdia-o.** O identificador do
      // agente era lido do *callback*, posto no `HumanEvent` e descartado: o
      // `close` passava `null` em `$4` sempre, pelo que o `COALESCE` era um
      // *no-op* e a coluna `resolver` nunca era escrita por caminho nenhum. A
      // cablagem estava feita de ponta a ponta menos um fio.
      if (outcome !== null) {
        await this.#fechar(acontecimento.handoffId, outcome, acontecimento.resolver);
      }
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
    await this.#fechar(handoffId, outcome, null);
  }

  /**
   * O fecho propriamente dito, com o `resolver` quando se sabe quem foi.
   *
   * **Privado e com um terceiro argumento** para não alterar a costura que o
   * ADR-012 fixa: o `close(handoffId, outcome)` do `../docs/tecnica/01` §11.1
   * continua a ser o que a porta expõe, e o `receber` — que é o único sítio
   * onde o identificador do agente existe — chama esta.
   *
   * **Zero linhas deixou de ser silêncio.** A primeira versão fazia `return`
   * sem contar nem registar nada, e nesse caminho cabiam duas coisas muito
   * diferentes: o `resolved` duplicado, que é o critério 7 e é benigno, e um
   * fecho que não casou por outra razão — que deixava a passagem em `waiting`
   * para sempre, no painel do SLA como atrasada, e respondia 200 ao provedor,
   * que pára de reenviar. Agora regista-se; a consulta é a mesma, o que muda é
   * ficar rasto.
   */
  async #fechar(
    handoffId: string,
    outcome: Outcome,
    resolver: string | null,
  ): Promise<void> {
    const estado = estadoDe(outcome);
    const linhas = await this.#bd.query<{ status: string }>(SQL_FECHAR, [
      handoffId,
      estado,
      [...ESTADOS_QUE_FECHAM],
      resolver,
    ]);
    if (linhas.rows.length === 0) {
      this.#log?.info({ outcome: "handoff_fecho_sem_efeito" });
      return;
    }
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
      provider_user_id: string;
    }>(SQL_CONTA, [tenantId, this.#qual]);
    const linha = linhas.rows[0];
    return linha === undefined
      ? null
      : {
          accountId: Number(linha.account_id),
          inboxId: Number(linha.inbox_id),
          botId: Number(linha.bot_id),
          providerUserId: Number(linha.provider_user_id),
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
