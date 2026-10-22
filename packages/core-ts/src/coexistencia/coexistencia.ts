/**
 * A coexistência: histórico, sincronização de 24 h, *echoes* e desligamento
 * (KAM-017).
 *
 * O que este módulo faz, pela ordem dos critérios:
 *
 * 1. **Ingere `history` e `smb_app_state_sync`** — alimenta `contacts` (pela
 *    porta do KAM-008) e as contagens, e **nunca** manda nada ao AGR nem à
 *    saída. Não pode: não tem porta para nenhum dos dois.
 * 2. **Não persiste corpos.** A tabela não tem coluna de texto para conteúdo, e
 *    este módulo conta mensagens sem as ler.
 * 3. **Corre a sincronização** com passos idempotentes, alerta às 12 h e
 *    `falhado` + *offboard* às 24 h, com o relógio por parâmetro.
 * 4. **Trata o 2593109** como `sincronizado_sem_historico`, que é sucesso.
 * 5. **Trata o `account_update`**: os seis motivos passam o canal a `desligado`,
 *    emitem `channel.updated` e contam.
 * 6. **Avisa aos 10 dias** sem *echo* do dono.
 * 7. **Trata o *echo***: compara o `wamid` com `outbound_messages` e entrega o
 *    que é do dono ao tratador do KAM-018.
 * 8. **Respeita o `channel_mode`**: em `cloud_only` não há sincronização nem
 *    *echoes*.
 * 9. **A reconexão repõe** a linha que já lá está, e a unicidade da `0018`
 *    garante que não há segunda.
 *
 * ## A ordem de cada tratador é a mesma, e foi paga
 *
 * **Escrever, emitir, contar.** Nesta ordem, e a razão é um achado da revisão
 * adversarial do KAM-018: a escrita e a emissão vivem na mesma transacção, e
 * com o contador antes da emissão um `evt_emitir` que levante desfaz o `UPDATE`
 * e **não** desfaz o contador em memória. O painel passava a mostrar
 * desligamentos que a base não tem.
 *
 * ## O que este módulo **não** faz
 *
 * * **Não decide o modo predefinido do produto.** O `ext:KAM-100` é quem o
 *   decide, e o relatório não existe — não há `docs/evidencia/KAM-100.md`. A
 *   lógica dos dois modos está cá inteira, e é a mesma: o `01` §10.1 di-lo
 *   («a lógica de saída é a mesma, só muda o §10.2»). O que falta é **um valor
 *   por omissão**, e inventá-lo era escolher pelo relatório.
 * * **Não entrega o aviso ao dono.** Emite o `channel.inactivity_warning` e
 *   pára; a entrega por e-mail ou *push* é **KAM-115**, e o critério 6 di-lo.
 * * **Não detecta o comando `/bot`.** O `EventoDeEntrada` do KAM-013 não leva o
 *   corpo de uma mensagem, e fazê-lo levar punha texto de conversa no contrato
 *   de ingestão — contra o ADR-010, e por uma transição que nenhum dos nove
 *   critérios deste ticket pede. A célula `dono + comando_bot` do KAM-018 fica
 *   sem detector, e isso está na secção de verificação e nas dívidas.
 * * **Não agenda nada.** Não há agendador neste repositório (nasce com o
 *   KAM-071/KAM-078), e o padrão da casa — `abandonarVencidas` do KAM-016,
 *   `pausarPorInactividade` do KAM-018 — é uma função idempotente por predicado
 *   SQL, testável agora e chamável depois. É o que as três varreduras são.
 */

import type { Logger } from "../logger/index.ts";
import { SQL_POR_WAMID } from "../outbound/consultas.ts";
import {
  ALERTA_DE_SINCRONIZACAO_MS,
  CODIGO_SEM_HISTORICO,
  type ClienteSql,
  type Coexistencia,
  type Contacto,
  type Conversa,
  type DesfechoDoEcho,
  type Emitir,
  ESTADO_DESLIGADO,
  type Estado,
  EVENTO_PARTNER_REMOVED,
  INACTIVIDADE_DO_DONO_MS,
  type ModoDoCanal,
  type MotivoDeDesligamento,
  type Passo,
  PRAZO_DE_SINCRONIZACAO_MS,
  type Relogio,
  type ResultadoDaIngestao,
  type ResultadoDaVarredura,
  type ResultadoDoDesligamento,
  type ResultadoDoEcho,
  type Transitar,
  traduzirMotivo,
} from "./contrato.ts";
import {
  SQL_ABRIR,
  SQL_ALERTAR_VENCIDAS,
  SQL_AVISAR_INACTIVOS,
  SQL_CANAL_POR_NUMERO,
  SQL_CONCLUIR,
  SQL_CONCLUIR_SEM_HISTORICO,
  SQL_DESLIGAR_CANAL,
  SQL_FALHAR_VENCIDAS,
  SQL_MARCAR_PASSO,
  SQL_MARCAR_SINCRONIZADO,
  SQL_POR_CANAL,
  SQL_REGISTAR_DESLIGAMENTO,
  SQL_REGISTAR_ECHO,
} from "./consultas.ts";
import {
  METRICA_DESLIGADOS,
  METRICA_ECHOES,
  METRICA_FALHADAS,
  MetricasDaCoexistencia,
} from "./metricas.ts";

/** O canal, como o `SQL_CANAL_POR_NUMERO` o lê. */
export interface CanalResolvido {
  readonly channelId: string;
  readonly channelMode: ModoDoCanal;
  readonly estado: string;
}

/** O que o tratador precisa de receber. Ver as cinco portas do `contrato.ts`. */
export interface Dependencias {
  readonly emitirCanalActualizado: Emitir;
  readonly emitirAviso: Emitir;
  readonly contacto: Contacto;
  readonly conversa: Conversa;
  readonly transitar: Transitar;
  readonly metricas?: MetricasDaCoexistencia;
  readonly log?: Logger;
  readonly agora?: Relogio;
}

/** Um contacto que veio num `smb_app_state_sync`. */
export interface ContactoDoSync {
  readonly bsuid: string | null;
  readonly telefone: string | null;
}

/** Um lote de `history`, já lido do `value` do *webhook*. */
export interface LoteDeHistorico {
  /** Quantas mensagens o lote trazia. **Uma contagem, nunca os corpos.** */
  readonly mensagens: number;
  /** Os interlocutores das conversas do lote, para alimentar `contacts`. */
  readonly contactos: readonly ContactoDoSync[];
  /** Os códigos de erro que o lote trouxe, tal e qual. */
  readonly erros: readonly number[];
}

/** O canal não existe, ou não é deste *tenant*. */
export class CanalDesconhecidoError extends Error {
  constructor(phoneNumberId: string) {
    super(
      "nenhum canal com este phone_number_id neste tenant " +
        `(${phoneNumberId.length} caracteres). O webhook chegou antes do ` +
        "onboarding, ou o numero e de outro tenant.",
    );
    this.name = "CanalDesconhecidoError";
  }
}

/** A base respondeu numa forma que não se consegue ler. */
export class CoexistenciaIlegivelError extends Error {
  constructor(motivo: string) {
    super(`channel_coexistence ilegivel: ${motivo}`);
    this.name = "CoexistenciaIlegivelError";
  }
}

function instante(valor: unknown): Date | null {
  if (valor instanceof Date) {
    // Um `Date` invalido e `NaN` no `getTime`, e **qualquer** comparacao com
    // `NaN` e falsa — o `fail-open` de um caracter que a revisao adversarial do
    // KAM-018 encontrou. Aqui ele vira `null`, que os predicados tratam.
    return Number.isNaN(valor.getTime()) ? null : valor;
  }
  if (typeof valor === "string") {
    const d = new Date(valor);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

function inteiro(valor: unknown): number {
  return typeof valor === "number" && Number.isFinite(valor) ? valor : 0;
}

/**
 * A coexistência de um canal, do lado de quem trata *webhooks*.
 *
 * Todos os métodos recebem o `ClienteSql` de quem chama: a transacção é dele,
 * pela razão que o `qualidade/contrato.ts` escreveu e que vale aqui com mais
 * força — os passos de um `account_update` são registar, desligar e emitir, e
 * com cada um na sua transacção um processo que caia pelo meio perde a
 * transição para sempre (a Meta reenvia, o `ON CONFLICT` da `inbound_events`
 * deduplica, e o canal fica `ativo` com o desligamento registado).
 */
export class Coexistente {
  readonly #emitirCanalActualizado: Emitir;
  readonly #emitirAviso: Emitir;
  readonly #contacto: Contacto;
  readonly #conversa: Conversa;
  readonly #transitar: Transitar;
  readonly #metricas: MetricasDaCoexistencia;
  readonly #log: Logger | undefined;
  readonly #agora: Relogio;

  constructor(dependencias: Dependencias) {
    this.#emitirCanalActualizado = dependencias.emitirCanalActualizado;
    this.#emitirAviso = dependencias.emitirAviso;
    this.#contacto = dependencias.contacto;
    this.#conversa = dependencias.conversa;
    this.#transitar = dependencias.transitar;
    this.#metricas = dependencias.metricas ?? new MetricasDaCoexistencia();
    this.#log = dependencias.log;
    this.#agora = dependencias.agora ?? (() => new Date());
  }

  get metricas(): MetricasDaCoexistencia {
    return this.#metricas;
  }

  /** O canal de um `phone_number_id`, ou `null`. */
  async canal(
    cliente: ClienteSql,
    tenantId: string,
    phoneNumberId: string,
  ): Promise<CanalResolvido | null> {
    const { rows } = await cliente.query<{
      channel_id?: unknown;
      channel_mode?: unknown;
      estado?: unknown;
    }>(SQL_CANAL_POR_NUMERO, [tenantId, phoneNumberId]);
    const linha = rows[0];
    if (linha === undefined) return null;
    const { channel_id: id, channel_mode: modo, estado } = linha;
    if (typeof id !== "string" || typeof modo !== "string" || typeof estado !== "string") {
      throw new CoexistenciaIlegivelError("tenant_channels sem id, modo ou estado");
    }
    return {
      channelId: id,
      channelMode: modo as ModoDoCanal,
      estado,
    };
  }

  /**
   * Abre (ou **repõe**) a sincronização de um canal. É a porta
   * `subscrito → a_sincronizar` do KAM-016.
   *
   * **Em `cloud_only` não faz nada e devolve `null`**, e é o critério 8: «em
   * `cloud_only` não há *job* de sincronização nem *echoes*». Não é uma
   * optimização — um canal `cloud_only` é um número novo e dedicado, que não
   * tem histórico na app para sincronizar.
   *
   * O prazo nasce aqui e fica **em coluna**: é isso que torna o relógio
   * acelerado dos testes possível sem mexer no servidor.
   */
  async abrir(
    cliente: ClienteSql,
    tenantId: string,
    canal: CanalResolvido,
  ): Promise<string | null> {
    if (canal.channelMode !== "coexistencia") {
      this.#log?.info({ outcome: "sincronizacao_dispensada", tenant_id: tenantId });
      return null;
    }
    const agora = this.#agora();
    const prazo = new Date(agora.getTime() + PRAZO_DE_SINCRONIZACAO_MS);
    const { rows } = await cliente.query<{ id?: unknown }>(SQL_ABRIR, [
      tenantId,
      canal.channelId,
      agora,
      prazo,
    ]);
    const id = rows[0]?.id;
    if (typeof id !== "string") {
      throw new CoexistenciaIlegivelError("o INSERT ... ON CONFLICT nao devolveu id");
    }
    return id;
  }

  /** A coexistência de um canal, ou `null` se nunca foi aberta. */
  async ler(
    cliente: ClienteSql,
    tenantId: string,
    channelId: string,
  ): Promise<Coexistencia | null> {
    const { rows } = await cliente.query<Record<string, unknown>>(SQL_POR_CANAL, [
      tenantId,
      channelId,
    ]);
    const l = rows[0];
    if (l === undefined) return null;
    const id = l["id"];
    const estado = l["estado"];
    const iniciado = instante(l["iniciado_em"]);
    const prazo = instante(l["prazo_em"]);
    if (typeof id !== "string" || typeof estado !== "string") {
      throw new CoexistenciaIlegivelError("linha sem id ou sem estado");
    }
    if (iniciado === null || prazo === null) {
      throw new CoexistenciaIlegivelError("iniciado_em ou prazo_em ilegivel");
    }
    const passos = l["passos_feitos"];
    const motivo = l["motivo_desligamento"];
    return {
      id,
      tenantId,
      channelId,
      estado: estado as Estado,
      passosFeitos: Array.isArray(passos) ? (passos as readonly Passo[]) : [],
      iniciadoEm: iniciado,
      prazoEm: prazo,
      alertadoEm: instante(l["alertado_em"]),
      concluidoEm: instante(l["concluido_em"]),
      contactosVistos: inteiro(l["contactos_vistos"]),
      mensagensVistas: inteiro(l["mensagens_vistas"]),
      metaErrorCode: typeof l["meta_error_code"] === "number" ? l["meta_error_code"] : null,
      ultimoEchoEm: instante(l["ultimo_echo_em"]),
      avisadoEm: instante(l["avisado_em"]),
      motivoDesligamento: typeof motivo === "string" ? (motivo as MotivoDeDesligamento) : null,
      desligadoEm: instante(l["desligado_em"]),
    };
  }

  /**
   * Ingere um lote de `history` (critérios 1, 2 e 4).
   *
   * **Nunca** chama o AGR nem a saída, e não pode: este módulo não tem porta
   * para nenhum dos dois. O `jobsParaOAgr: 0` do resultado é a asserção que o
   * critério 1 escreve, e existe para que o teste afirme o número em vez de
   * afirmar a ausência de uma chamada que ninguém declarou.
   *
   * **Os corpos não entram em lado nenhum.** O que chega aqui é uma contagem
   * (`lote.mensagens`) e os interlocutores; o texto fica no `value` do
   * *webhook*, que o KAM-013 não persiste — a `inbound_events` não tem coluna
   * de corpo — e que este módulo nunca lê.
   *
   * **O 2593109 decide antes de tudo** (critério 4): quando o lote traz o
   * código, a sincronização fecha em `sincronizado_sem_historico` e o passo
   * `historico` **não** se marca, porque ele não correu. Fechar e marcar o
   * passo eram duas afirmações contraditórias sobre o mesmo facto.
   */
  async ingerirHistorico(
    cliente: ClienteSql,
    tenantId: string,
    channelId: string,
    lote: LoteDeHistorico,
  ): Promise<ResultadoDaIngestao> {
    if (lote.erros.includes(CODIGO_SEM_HISTORICO)) {
      const estado = await this.#concluirSemHistorico(cliente, tenantId, channelId);
      return {
        contactos: 0,
        mensagens: 0,
        passoConcluido: false,
        estado,
        jobsParaOAgr: 0,
      };
    }
    const contactos = await this.#resolverContactos(tenantId, lote.contactos);
    return this.#marcarPasso(cliente, tenantId, channelId, "historico", {
      contactos,
      mensagens: lote.mensagens,
    });
  }

  /**
   * Ingere um lote de `smb_app_state_sync` (critérios 1 e 2).
   *
   * As mesmas regras do `history`: contactos por `contact_id`, zero *jobs*,
   * zero envios. Este caminho não trata o 2593109 — o erro vem no `history`,
   * que é onde a Meta o põe (`E1` §2).
   */
  async ingerirStateSync(
    cliente: ClienteSql,
    tenantId: string,
    channelId: string,
    contactos: readonly ContactoDoSync[],
  ): Promise<ResultadoDaIngestao> {
    const quantos = await this.#resolverContactos(tenantId, contactos);
    return this.#marcarPasso(cliente, tenantId, channelId, "contactos", {
      contactos: quantos,
      mensagens: 0,
    });
  }

  /**
   * Trata um *echo* (critério 7).
   *
   * A regra é a do critério, e é a que torna o tratamento seguro nos dois lados
   * do **NÃO VERIFICADO L6** (se um envio por API gera *echo*): compara-se o
   * `wamid` com `outbound_messages`. Se lá está, **fomos nós** e ignora-se —
   * não é actividade humana. Se não está, foi o dono a escrever na app.
   *
   * **A comparação é por `(tenant_id, wamid)`** porque é essa a forma do
   * `SQL_POR_WAMID` do KAM-015, e não se relaxa para o `wamid` sozinho mesmo
   * sendo ele globalmente único: uma consulta sem `tenant_id` sob RLS é uma
   * consulta que dá o resultado certo pela razão errada, e deixa de o dar no
   * dia em que alguém a corra com outro papel.
   *
   * **Em `cloud_only` não há *echoes*** (critério 8). Um *echo* que chegue a um
   * canal `cloud_only` não é tráfego normal: regista-se como `sem_conversa`,
   * que é o desfecho que existe para o que não se descarta em silêncio.
   */
  async tratarEcho(
    cliente: ClienteSql,
    tenantId: string,
    canal: CanalResolvido,
    echo: { readonly wamid: string; readonly destinatario: ContactoDoSync },
  ): Promise<ResultadoDoEcho> {
    if (canal.channelMode !== "coexistencia") {
      return this.#contarEcho("sem_conversa", null);
    }
    const { rows } = await cliente.query(SQL_POR_WAMID, [tenantId, echo.wamid]);
    if (rows.length > 0) {
      // Fomos nos. Nao e actividade humana, e **nao** mexe no relogio de
      // inactividade: um bot a responder nao prova que o dono abriu a app.
      this.#log?.info({ outcome: "echo_nosso", tenant_id: tenantId });
      return this.#contarEcho("nosso", null);
    }

    // Foi o dono. O relogio do criterio 6 move-se **antes** de haver conversa,
    // e de proposito: o dono escreveu na app, e isso e actividade dele mesmo
    // que o destinatario nao resolva uma conversa nossa.
    //
    // **O resultado le-se, e nao se descarta.** Se nao houver linha de
    // coexistencia — um canal cuja sincronizacao nunca abriu, ou cuja linha a
    // purga do KAM-071 ja apagou — o relogio nunca avanca, o
    // `SQL_AVISAR_INACTIVOS` nao tem onde o ler, e o aviso dos 10 dias deixa de
    // sair **em silencio**. Era uma falha fechada e muda; agora e fechada e
    // dita. Achado da revisao adversarial.
    const relogio = await cliente.query(SQL_REGISTAR_ECHO, [
      tenantId,
      canal.channelId,
      this.#agora(),
    ]);
    if (relogio.rows.length === 0) {
      this.#log?.warn({ outcome: "echo_sem_coexistencia", tenant_id: tenantId });
    }

    if (echo.destinatario.bsuid === null && echo.destinatario.telefone === null) {
      this.#log?.warn({ outcome: "echo_sem_destinatario", tenant_id: tenantId });
      return this.#contarEcho("sem_conversa", null);
    }
    const { contactId } = await this.#contacto({
      tenantId,
      bsuid: echo.destinatario.bsuid,
      telefone: echo.destinatario.telefone,
    });
    const conversationId = await this.#conversa({
      tenantId,
      contactId,
      channelId: canal.channelId,
    });
    if (conversationId === null) {
      // O dono falou com alguem que o bot nunca atendeu. E o caso normal da
      // coexistencia, e nao ha conversa para transitar — mas conta-se.
      return this.#contarEcho("sem_conversa", null);
    }
    await this.#transitar(tenantId, conversationId);
    return this.#contarEcho("do_dono", conversationId);
  }

  /**
   * Trata um `account_update` com `PARTNER_REMOVED` (critério 5).
   *
   * Os seis motivos passam o canal a `desligado`, emitem `channel.updated` com
   * o motivo e contam. **Repetir o mesmo evento 2× produz 1 transição**, e quem
   * o decide são os dois predicados — o `desligado_em IS NULL` da coexistência
   * e o `estado <> 'desligado'` do canal — e não um `if`: a segunda passagem
   * devolve zero linhas, sob concorrência.
   *
   * Um motivo que não se reconhece **não desliga nada** e devolve
   * `motivo: null`, pela escolha que o `traduzirMotivo` explica: desligar por
   * um valor que não se compreende era deixar a Meta decidir o estado dos
   * nossos canais com uma cadeia que ninguém leu.
   */
  async tratarAccountUpdate(
    cliente: ClienteSql,
    tenantId: string,
    canal: CanalResolvido,
    bruto: { readonly evento: unknown; readonly motivo: unknown },
  ): Promise<ResultadoDoDesligamento> {
    // **O `event` confere-se, e nao so o `reason`.** A constante existia e nao
    // era lida: um `account_update` de outro acontecimento que trouxesse um
    // `reason` reconhecivel desligava o canal. Achado da revisao adversarial —
    // o risco pratico e baixo (o `reason` so vem dentro de
    // `partner_removed_info`), mas uma constante exportada sem consumidor e um
    // nome sem superficie, que e o que o *gate* 3b recusa pelo outro lado.
    if (bruto.evento !== EVENTO_PARTNER_REMOVED) {
      this.#log?.info({ outcome: "evento_ignorado", tenant_id: tenantId });
      return { motivo: null, desligou: false, eventoId: null };
    }
    const motivo = traduzirMotivo(bruto.motivo);
    if (motivo === null) {
      this.#log?.warn({ outcome: "motivo_desconhecido", tenant_id: tenantId });
      return { motivo: null, desligou: false, eventoId: null };
    }
    const agora = this.#agora();

    // **O canal primeiro, e o registo so se ele transitou.** A ordem inversa —
    // registar e depois desligar — tinha um buraco que a revisao adversarial
    // mediu: um canal em `suspenso` ou `encerrado` nao e tocado pelo
    // `SQL_DESLIGAR_CANAL` (e de proposito: uma suspensao e decisao nossa que
    // um *webhook* da Meta nao revoga), mas o registo **ja tinha mordido** — e
    // a funcao devolvia normalmente, pelo que a transacao de quem chama
    // confirmava e ficavam as duas tabelas a discordar sobre se o canal esta
    // desligado. Era precisamente o modo de falhar que este tratador diz
    // prevenir.
    const { rows } = await cliente.query<{ phone_number_id?: unknown }>(
      SQL_DESLIGAR_CANAL,
      [tenantId, canal.channelId, agora],
    );
    const numero = rows[0]?.phone_number_id;
    if (typeof numero !== "string") {
      // Ja estava `desligado`, ou esta `encerrado`/`suspenso`. A **segunda**
      // passagem do criterio 5 acaba aqui: sem transicao, sem registo, sem
      // evento, sem contagem.
      this.#log?.info({ outcome: "desligamento_repetido", tenant_id: tenantId });
      return { motivo, desligou: false, eventoId: null };
    }
    const registo = await cliente.query<{ id?: unknown }>(SQL_REGISTAR_DESLIGAMENTO, [
      tenantId,
      canal.channelId,
      motivo,
      agora,
    ]);
    if (registo.rows.length === 0 && canal.channelMode === "coexistencia") {
      // O canal transitou e a coexistencia nao tinha onde registar. Em
      // `coexistencia` isso **nao e normal** e nao se cala: ou a linha ja
      // estava marcada, ou nunca foi aberta.
      //
      // **Em `cloud_only` e o caminho normal** e nao se avisa: o `abrir`
      // devolve `null` sem inserir nesse modo (criterio 8), pelo que o canal
      // nunca tem linha. A primeira versao nao distinguia, e dava um `warn` por
      // cada `PARTNER_REMOVED` de cada canal `cloud_only` — ruido no sinal que
      // existe para apanhar desalinhamento a serio. Achado da revisao
      // adversarial.
      this.#log?.warn({ outcome: "desligamento_desalinhado", tenant_id: tenantId });
    }
    // Escrever, emitir, contar — nesta ordem. Ver a nota do modulo.
    const eventoId = await this.#emitirCanalActualizado(
      cliente,
      tenantId,
      canal.channelId,
      numero,
      motivo,
    );
    this.#metricas.contar(METRICA_DESLIGADOS, motivo);
    this.#log?.warn({ outcome: motivo, tenant_id: tenantId });
    return { motivo, desligou: true, eventoId };
  }

  /**
   * Alerta as sincronizações que passaram das 12 h e falha as que passaram das
   * 24 h (critério 3).
   *
   * **Uma varredura e não um agendador**, pelo precedente do
   * `abandonarVencidas` do KAM-016 e do `pausarPorInactividade` do KAM-018:
   * não há agendador neste repositório, e ele nasce com o KAM-071/KAM-078.
   * Chamá-la duas vezes seguidas é um *no-op* na segunda, e isso é propriedade
   * dos predicados (`alertado_em IS NULL`, `estado = 'a_sincronizar'`).
   *
   * **Corre sem contexto de *tenant*** — é uma varredura de plataforma, como o
   * contador de onboardings do KAM-016 — e por isso devolve os `tenant_id` de
   * cada linha: quem trata cada uma volta a entrar com contexto para emitir.
   * O `cliente` que entra aqui é o de `kamba_batch`.
   *
   * O *offboard* do critério 3 é o que quem chama faz com os `offboards`: este
   * módulo marca `falhado` e conta, e quem reabre o Embedded Signup é o
   * KAM-093 sobre o `falhado → iniciado` do KAM-016.
   */
  async varrerPrazos(cliente: ClienteSql): Promise<ResultadoDaVarredura> {
    const agora = this.#agora();
    const corteDoAlerta = new Date(agora.getTime() - ALERTA_DE_SINCRONIZACAO_MS);

    const alerta = await cliente.query<{ channel_id?: unknown }>(SQL_ALERTAR_VENCIDAS, [
      corteDoAlerta,
      agora,
    ]);
    const alertados = alerta.rows
      .map((l) => l.channel_id)
      .filter((v): v is string => typeof v === "string");

    const falha = await cliente.query<{ channel_id?: unknown }>(SQL_FALHAR_VENCIDAS, [
      agora,
    ]);
    const falhados = falha.rows
      .map((l) => l.channel_id)
      .filter((v): v is string => typeof v === "string");

    for (const _ of falhados) {
      this.#metricas.contar(METRICA_FALHADAS, "prazo_esgotado");
    }
    if (alertados.length > 0) {
      this.#log?.warn({ outcome: "sincronizacao_em_atraso" });
    }
    if (falhados.length > 0) {
      this.#log?.error({ outcome: "sincronizacao_falhada" });
    }
    // Os mesmos canais: um `falhado` **e** um *offboard* pedido, e devolver as
    // duas listas separadas era sugerir que pode haver um sem o outro.
    return { alertados, falhados, offboards: falhados };
  }

  /**
   * Avisa os canais com 10 dias sem *echo* do dono (critério 6).
   *
   * A heurística é a do `01` §10.5, **e só metade dela se mede**: «sem *echo* e
   * sem acesso ao painel». O painel é KAM-093 e não existe, pelo que não há
   * sinal de acesso a ler — e inventar um era inventar evidência. Está na
   * secção de verificação e nas dívidas.
   *
   * Idempotente pelo `avisado_em IS NULL`, e a janela **reabre** quando chega
   * actividade do dono (o `SQL_REGISTAR_ECHO` põe o carimbo a nulo). Sem isso,
   * um canal avisado uma vez nunca mais era avisado.
   */
  async varrerInactividade(
    cliente: ClienteSql,
    emitirPorTenant: (
      tenantId: string,
      channelId: string,
    ) => Promise<string | null> = async () => null,
  ): Promise<readonly string[]> {
    const agora = this.#agora();
    const corte = new Date(agora.getTime() - INACTIVIDADE_DO_DONO_MS);
    const { rows } = await cliente.query<{
      tenant_id?: unknown;
      channel_id?: unknown;
    }>(SQL_AVISAR_INACTIVOS, [corte, agora]);
    const avisados: string[] = [];
    for (const linha of rows) {
      const tenantId = linha.tenant_id;
      const channelId = linha.channel_id;
      if (typeof tenantId !== "string" || typeof channelId !== "string") continue;
      await emitirPorTenant(tenantId, channelId);
      avisados.push(channelId);
    }
    if (avisados.length > 0) {
      this.#log?.warn({ outcome: "canal_inactivo" });
    }
    return avisados;
  }

  /**
   * Emite o aviso de um canal, com contexto de *tenant*.
   *
   * Separado da varredura porque a varredura corre sem contexto e a emissão
   * precisa dele: o `evt_emitir` escreve na linha de um *tenant*, e a RLS está
   * em `FORCE`.
   */
  async avisar(
    cliente: ClienteSql,
    tenantId: string,
    channelId: string,
    phoneNumberId: string,
  ): Promise<string> {
    return this.#emitirAviso(cliente, tenantId, channelId, phoneNumberId, null);
  }

  // ------------------------------------------------------------------ privados

  async #resolverContactos(
    tenantId: string,
    contactos: readonly ContactoDoSync[],
  ): Promise<number> {
    let quantos = 0;
    for (const c of contactos) {
      if (c.bsuid === null && c.telefone === null) continue;
      // Pela porta do KAM-008: o que fica guardado e o `contact_id`, e o
      // telefone nunca e chave (ADR-010). Um lote de historico de seis meses
      // passa aqui um contacto de cada vez porque a porta e idempotente —
      // `resolveContact` devolve `existente` na segunda — e um lote nao e
      // caminho quente.
      await this.#contacto({ tenantId, bsuid: c.bsuid, telefone: c.telefone });
      quantos += 1;
    }
    return quantos;
  }

  async #marcarPasso(
    cliente: ClienteSql,
    tenantId: string,
    channelId: string,
    passo: Passo,
    contagens: { readonly contactos: number; readonly mensagens: number },
  ): Promise<ResultadoDaIngestao> {
    const { rows } = await cliente.query<{ passos_feitos?: unknown }>(SQL_MARCAR_PASSO, [
      tenantId,
      channelId,
      passo,
      contagens.contactos,
      contagens.mensagens,
      // O relogio, para o `prazo_em > $6`. Entra por parametro como tudo o
      // resto neste modulo: e o que torna o prazo mensurivel com o relogio
      // acelerado que o criterio 3 pede.
      this.#agora(),
    ]);
    if (rows.length === 0) {
      // Ou o passo ja tinha corrido (o *no-op* do criterio 3), ou a
      // sincronizacao ja nao esta em `a_sincronizar`. Nos dois casos nao ha
      // nada a fazer, e le-se o estado para o devolver com verdade.
      const actual = await this.ler(cliente, tenantId, channelId);
      this.#log?.info({ outcome: "passo_repetido", tenant_id: tenantId });
      return {
        contactos: contagens.contactos,
        mensagens: contagens.mensagens,
        passoConcluido: false,
        estado: actual?.estado ?? "a_sincronizar",
        jobsParaOAgr: 0,
      };
    }
    const estado = await this.#concluirSePronto(cliente, tenantId, channelId);
    return {
      contactos: contagens.contactos,
      mensagens: contagens.mensagens,
      passoConcluido: true,
      estado,
      jobsParaOAgr: 0,
    };
  }

  async #concluirSePronto(
    cliente: ClienteSql,
    tenantId: string,
    channelId: string,
  ): Promise<Estado> {
    const agora = this.#agora();
    const { rows } = await cliente.query<{ id?: unknown }>(SQL_CONCLUIR, [
      tenantId,
      channelId,
      agora,
    ]);
    if (rows.length === 0) {
      const actual = await this.ler(cliente, tenantId, channelId);
      return actual?.estado ?? "a_sincronizar";
    }
    await this.#fecharCanal(cliente, tenantId, channelId, agora);
    return "sincronizado";
  }

  async #concluirSemHistorico(
    cliente: ClienteSql,
    tenantId: string,
    channelId: string,
  ): Promise<Estado> {
    const agora = this.#agora();
    const { rows } = await cliente.query<{ id?: unknown }>(SQL_CONCLUIR_SEM_HISTORICO, [
      tenantId,
      channelId,
      agora,
      CODIGO_SEM_HISTORICO,
    ]);
    if (rows.length === 0) {
      const actual = await this.ler(cliente, tenantId, channelId);
      return actual?.estado ?? "a_sincronizar";
    }
    await this.#fecharCanal(cliente, tenantId, channelId, agora);
    // **O codigo nao vai ao registo**, e isso nao e esquecimento: 2593109 tem
    // sete digitos e a politica recusa mais de seis em qualquer campo de texto,
    // tanto no `outcome` como no `error_code`. O que vai e o simbolo.
    this.#log?.info({ outcome: "sincronizado_sem_historico", tenant_id: tenantId });
    return "sincronizado_sem_historico";
  }

  /** Escreve o `coexistence_synced_at` e observa a duração. */
  async #fecharCanal(
    cliente: ClienteSql,
    tenantId: string,
    channelId: string,
    agora: Date,
  ): Promise<void> {
    await cliente.query(SQL_MARCAR_SINCRONIZADO, [tenantId, channelId, agora]);
    const actual = await this.ler(cliente, tenantId, channelId);
    if (actual === null) return;
    const segundos = (agora.getTime() - actual.iniciadoEm.getTime()) / 1_000;
    if (segundos < 0) {
      // So pode vir de um relogio ao contrario entre o `abrir` e o fecho. O
      // `observarDuracao` **levanta** com um negativo, de proposito — mas
      // levantar aqui desfazia a transaccao que acabou de marcar a
      // sincronizacao como concluida, e a sincronizacao ficava presa em
      // `a_sincronizar` ate o prazo cair. Entre perder o histograma de uma
      // sincronizacao e perder a sincronizacao, perde-se o histograma: regista-
      // -se o facto e nao se observa. O `fail-closed` esta na metrica, para
      // quem lhe passe um numero directamente.
      this.#log?.error({ outcome: "duracao_negativa", tenant_id: tenantId });
      return;
    }
    this.#metricas.observarDuracao(segundos);
  }

  #contarEcho(desfecho: DesfechoDoEcho, conversationId: string | null): ResultadoDoEcho {
    this.#metricas.contar(METRICA_ECHOES, desfecho);
    return { desfecho, conversationId };
  }
}
