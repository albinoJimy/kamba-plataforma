/**
 * O tratador dos *webhooks* de gestão de canal (KAM-021).
 *
 * É o que preenche o braço `gestaoDeCanal` do `Encaminhador` que o KAM-013
 * declarou e deixou a registar e mais nada — o `EncaminhadorQueSoRegista` do
 * `services/worker-canal/src/entrada.ts` empurra os quatro eventos para uma
 * lista e o `docstring` dele diz «a gestão de canal está repartida entre
 * KAM-016 e KAM-021».
 *
 * ## A ordem dos passos, e porque é esta
 *
 * Para um `phone_number_quality_update`:
 *
 * 1. **lê o canal** — o `estado` e o `quality_rating` anteriores são o que
 *    decide se há transição, e o `motivo_restricao` é o que decide se se pode
 *    repor;
 * 2. **registra a transição** — e se o `RETURNING` vier vazio, **pára aqui**. É
 *    a idempotência do critério 6, e é da base: o mesmo evento 2× produz uma
 *    linha, logo uma transição, logo um aviso;
 * 3. **escreve a qualidade canónica**, se a Meta mandou um valor que se
 *    reconhece;
 * 4. **restringe ou repõe**, se houver transição de estado;
 * 5. **emite `channel.updated` e esquece o canal na *cache***, e só se o passo
 *    4 mexeu em algo.
 *
 * O passo 2 está antes do 3 de propósito. Se a qualidade se escrevesse
 * primeiro, um evento repetido que chegasse depois de o estado já ter sido
 * reposto reescrevia o `quality_rating` com um valor velho — e a ordem dos
 * `statuses` da Meta não é garantida (CONFIRMADO, `E1` §5). Com o registo à
 * frente, o segundo evento morre na unicidade antes de tocar em nada.
 *
 * **E os cinco passos têm de correr numa transacção, que é de quem chama.** O
 * passo 2 consome a `event_key`; um processo que caia entre ele e o passo 4
 * perde a transição **para sempre**, porque a Meta reenvia e o `ON CONFLICT`
 * deduplica contra a linha que ficou. O `ClienteSql` é por isso a ligação
 * **dentro** da transacção de quem chama — ver a nota da porta 1 no
 * `contrato.ts` —, e é o que o `comConsumo` do KAM-006 dá por desenho.
 *
 * ## O que este módulo **não** faz, e é escopo e não esquecimento
 *
 * * **Não escreve `tenants.estado`** (critério 3). A revisão `0007` retirou o
 *   `UPDATE (estado)` a `kamba_app` de propósito, com a razão escrita lá («o
 *   sujeito da condição não pode ser quem a retira»), e o
 *   `db/tests/test_privilegios.py` prende-o. Nenhum dos papéis que o *worker*
 *   de canal tem pode escrever ali. **A caixa do critério 3 fica vazia**, com
 *   a razão na secção de verificação, e a decisão devolve-se a quem escreveu o
 *   critério.
 * * **Não suspende nada.** Não há caminho nenhum aqui que produza `suspenso`, e
 *   é isso que o teste dos 50 eventos aleatórios afirma. O `suspenso` é de T&S
 *   (KAM-089/097).
 * * **Não cria *tickets*.** Os critérios 4 e 8 pedem «alerta a T&S» e «*ticket*
 *   para T&S», e não existe mecanismo de *ticket* neste repositório. O que
 *   existe são contadores e registo, e é isso que se usa — como o KAM-023 fez
 *   para o aviso do *free tier*. Quem notifica é o KAM-115.
 * * **Não recusa envios.** O critério 9 pede que o KAM-015 honre `restrito`, e
 *   isso vive no `outbound/`: aqui escreve-se o estado, lá lê-se.
 */

import type { Logger } from "../logger/index.ts";

import {
  MOTIVO_DE_QUALIDADE,
  traduzirQualidade,
  type Canal,
  type ClienteSql,
  type Emitir,
  type EventoDeCanal,
  type Invalidar,
  type Transicao,
  type Utilizacao,
} from "./contrato.ts";
import {
  SQL_CANAL,
  SQL_ESCREVER_LIMITES,
  SQL_ESCREVER_QUALIDADE,
  SQL_MARCAR_TEMPLATES,
  SQL_PAUSAR_TEMPLATE,
  SQL_REGISTAR_TRANSICAO,
  SQL_REPOR,
  SQL_RESTRINGIR,
  SQL_UNICOS_FORA_DA_JANELA,
} from "./consultas.ts";
import { accaoDaQualidade, avisaDeAmarelo, utilizacaoDoEscalao } from "./decisao.ts";
import {
  METRICAS_DA_QUALIDADE,
  METRICA_EVENTOS,
  METRICA_RESTRICOES,
  MetricasDaQualidade,
} from "./metricas.ts";

export interface Dependencias {
  readonly bd: ClienteSql;
  /** Quem publica o `channel.updated`. `null` deixa o evento por emitir. */
  readonly emitir?: Emitir | null;
  /** Quem esquece o canal na *cache* do CHR. `null` deixa valer o TTL. */
  readonly invalidar?: Invalidar | null;
  readonly log?: Logger;
  readonly metricas?: MetricasDaQualidade;
  /** O relógio, por parâmetro. `undefined` deixa o `now()` à base. */
  readonly agora?: () => Date;
}

/**
 * O tratador da gestão de canal.
 *
 * O nome é o do **destino** que o `entrada/contrato.ts` declara
 * (`gestao_de_canal`) e não o do ficheiro, de propósito: o tipo `Qualidade` é
 * um dos três valores do rating, e duas coisas com o mesmo nome no mesmo módulo
 * era o que o `verbatimModuleSyntax` recusou — com razão, porque quem lesse
 * `Qualidade` num sítio terceiro não sabia qual das duas era.
 */
export class GestaoDeCanal {
  readonly #bd: ClienteSql;
  readonly #emitir: Emitir | null;
  readonly #invalidar: Invalidar | null;
  readonly #log: Logger | undefined;
  readonly #metricas: MetricasDaQualidade;
  readonly #agora: (() => Date) | undefined;

  constructor(dependencias: Dependencias) {
    this.#bd = dependencias.bd;
    this.#emitir = dependencias.emitir ?? null;
    this.#invalidar = dependencias.invalidar ?? null;
    this.#log = dependencias.log;
    this.#metricas = dependencias.metricas ?? METRICAS_DA_QUALIDADE;
    this.#agora = dependencias.agora;
  }

  /** O instante a passar à base, ou `null` para ela usar o `now()` dela. */
  #instante(): string | null {
    const agora = this.#agora?.();
    return agora === undefined ? null : agora.toISOString();
  }

  /** O canal pelo seu número, ou `null` quando não existe neste contexto. */
  async canal(tenantId: string, phoneNumberId: string): Promise<Canal | null> {
    const linhas = await this.#bd.query<{
      channel_id: string;
      phone_number_id: string;
      estado: string;
      quality_rating: string | null;
      messaging_limit: string | null;
      motivo_restricao: string | null;
    }>(SQL_CANAL, [tenantId, phoneNumberId]);
    const linha = linhas.rows[0];
    if (linha === undefined) {
      // Não é silêncio: um canal que não se encontra é um achado para quem
      // opera, e o `outcome` é a única forma de o dizer dentro dos nove campos
      // que a política de registo permite.
      this.#log?.warn({ outcome: "canal_desconhecido", tenant_id: tenantId });
      return null;
    }
    return {
      tenantId,
      channelId: linha.channel_id,
      phoneNumberId: linha.phone_number_id,
      estado: linha.estado,
      qualityRating: linha.quality_rating,
      messagingLimit: linha.messaging_limit,
      motivoRestricao: linha.motivo_restricao,
    };
  }

  /**
   * Registra uma transição, e diz se foi **esta** a primeira com esta chave.
   *
   * `false` significa «este evento já foi tratado», e quem lê pára. É a
   * idempotência do critério 6, e é da base: o `ON CONFLICT (tenant_id,
   * event_key) DO NOTHING RETURNING` devolve vazio na segunda.
   */
  async #registar(
    canal: Canal,
    evento: EventoDeCanal,
    anterior: string | null,
    bruto: string,
    eventKey: string,
  ): Promise<boolean> {
    const linhas = await this.#bd.query(SQL_REGISTAR_TRANSICAO, [
      canal.tenantId,
      canal.channelId,
      evento,
      anterior,
      bruto,
      eventKey,
      this.#instante(),
    ]);
    const nova = linhas.rows.length > 0;
    if (nova) this.#metricas.contar(METRICA_EVENTOS, evento);
    return nova;
  }

  /**
   * Trata um `phone_number_quality_update` (critérios 1, 2 e 4).
   *
   * O `bruto` é o que a Meta mandou, **tal e qual** — e é isso que vai para o
   * registo. A qualidade canónica, quando se reconhece, vai para o
   * `quality_rating`; quando não, o critério 1 manda registar e não falhar, e é
   * o que acontece.
   */
  async qualidadeDoNumero(
    tenantId: string,
    phoneNumberId: string,
    bruto: string,
    eventKey: string,
  ): Promise<Transicao | null> {
    const canal = await this.canal(tenantId, phoneNumberId);
    if (canal === null) return null;

    const registou = await this.#registar(
      canal,
      "phone_number_quality_update",
      canal.qualityRating,
      bruto,
      eventKey,
    );
    const qualidade = traduzirQualidade(bruto);
    if (!registou) {
      // Evento repetido: nada mudou e nada se anuncia.
      return { registou: false, qualidade, restringiu: false, reposto: false, avisou: false };
    }

    if (qualidade === null) {
      // **Registado como desconhecido, sem falhar** (critério 1). O
      // `quality_rating` não se toca: mudar o estado corrente para um valor que
      // não se compreende era pior do que não o mudar.
      this.#log?.warn({ outcome: "qualidade_desconhecida", tenant_id: tenantId });
      return { registou: true, qualidade: null, restringiu: false, reposto: false, avisou: false };
    }

    await this.#bd.query(SQL_ESCREVER_QUALIDADE, [
      canal.tenantId,
      canal.channelId,
      qualidade,
    ]);
    this.#metricas.observarQualidade(canal.channelId, qualidade);

    const avisou = avisaDeAmarelo(qualidade, canal.qualityRating);
    if (avisou) {
      // «1 alerta a T&S por transição» (critério 4). Não há mecanismo de
      // *ticket* neste repositório: conta-se e registra-se, e quem notifica é o
      // KAM-115. E marcam-se os templates para revisão.
      this.#log?.warn({ outcome: "canal_qualidade_amarela", tenant_id: tenantId });
      await this.#bd.query(SQL_MARCAR_TEMPLATES, [canal.tenantId, qualidade]);
    }

    const accao = accaoDaQualidade(qualidade, canal.estado);
    let restringiu = false;
    let reposto = false;
    if (accao === "restringir") {
      const feito = await this.#bd.query(SQL_RESTRINGIR, [
        canal.tenantId,
        canal.channelId,
      ]);
      restringiu = feito.rows.length > 0;
      if (restringiu) {
        this.#metricas.contar(METRICA_RESTRICOES, MOTIVO_DE_QUALIDADE);
        this.#log?.warn({ outcome: "canal_restrito_quality", tenant_id: tenantId });
      }
    } else if (accao === "repor") {
      const feito = await this.#bd.query(SQL_REPOR, [canal.tenantId, canal.channelId]);
      reposto = feito.rows.length > 0;
      if (reposto) {
        this.#log?.warn({ outcome: "canal_reposto_quality", tenant_id: tenantId });
      }
    }

    if (restringiu || reposto) {
      // **A ordem importa:** o evento primeiro, a *cache* depois. O evento é
      // durável quando a transacção confirmar; a invalidação é de memória e não
      // sobrevive a nada. Invalidar primeiro deixava uma janela em que a
      // *cache* já esqueceu e o evento ainda pode não sair.
      await this.#emitir?.(
        canal.tenantId,
        canal.channelId,
        canal.phoneNumberId,
        MOTIVO_DE_QUALIDADE,
      );
      this.#invalidar?.(canal.channelId);
    }

    return { registou: true, qualidade, restringiu, reposto, avisou };
  }

  /**
   * Trata um `business_capability_update` (critério 5).
   *
   * Persiste o escalão e o tecto de números do portfólio. Os dois são
   * opcionais: a Meta manda o que mudou, e um `null` aqui significa «não
   * mexer» e não «apagar».
   */
  async capacidade(
    tenantId: string,
    phoneNumberId: string,
    escalao: string | null,
    maxNumeros: number | null,
    eventKey: string,
  ): Promise<boolean> {
    const canal = await this.canal(tenantId, phoneNumberId);
    if (canal === null) return false;

    const registou = await this.#registar(
      canal,
      "business_capability_update",
      canal.messagingLimit,
      escalao ?? String(maxNumeros ?? "sem-valor"),
      eventKey,
    );
    if (!registou) return false;

    await this.#bd.query(SQL_ESCREVER_LIMITES, [
      canal.tenantId,
      canal.channelId,
      escalao,
      maxNumeros === null || !Number.isInteger(maxNumeros) ? null : maxNumeros,
    ]);
    return true;
  }

  /**
   * Trata um `message_template_quality_update` (critério 5).
   *
   * Pausa **localmente** o template afectado: a Meta não pausou nada, nós é que
   * deixamos de enviar. O `decidir` do KAM-015 recusa um template cujo `status`
   * não seja `approved`, e é por aí que a pausa tem efeito.
   */
  async qualidadeDoTemplate(
    tenantId: string,
    phoneNumberId: string,
    nome: string,
    idioma: string,
    bruto: string,
    eventKey: string,
  ): Promise<boolean> {
    const canal = await this.canal(tenantId, phoneNumberId);
    if (canal === null) return false;

    const registou = await this.#registar(
      canal,
      "message_template_quality_update",
      null,
      bruto,
      eventKey,
    );
    if (!registou) return false;

    const linhas = await this.#bd.query(SQL_PAUSAR_TEMPLATE, [
      canal.tenantId,
      nome,
      idioma,
      traduzirQualidade(bruto),
    ]);
    const pausado = linhas.rows.length > 0;
    if (pausado) {
      this.#log?.warn({ outcome: "template_pausado", tenant_id: tenantId });
    }
    return pausado;
  }

  /**
   * Trata um `account_alerts` (critério 8).
   *
   * «Cria *ticket* para T&S com o texto da Meta (sem dados pessoais) e o canal
   * **não muda de estado**.» A segunda metade é a que este método garante: não
   * há aqui nenhuma escrita a `estado` nem a `motivo_restricao`.
   *
   * A primeira metade entrega-se como o que o repositório tem: o alerta
   * **conta** e **registra-se**, e o texto da Meta vai para o registo da
   * transição — na coluna `valor_novo`, que é `text` e guarda o que chegou. Não
   * existe mecanismo de *ticket* neste repositório, e criar um a partir de um
   * critério de um ticket de canais era alargar o escopo em silêncio. Quem
   * notifica é o KAM-115.
   *
   * **O texto vai para a base e não para o registo de linha**, e a diferença é
   * a política: a lista branca de nove campos do `logger/politica.ts` não tem
   * campo de texto livre, e o `outcome` é um identificador. O alerta da Meta
   * pode trazer qualquer coisa escrita; a base aceita-o, uma linha de *log* não.
   */
  async alertaDaConta(
    tenantId: string,
    phoneNumberId: string,
    texto: string,
    eventKey: string,
  ): Promise<boolean> {
    const canal = await this.canal(tenantId, phoneNumberId);
    if (canal === null) return false;

    const registou = await this.#registar(
      canal,
      "account_alerts",
      null,
      texto,
      eventKey,
    );
    if (registou) {
      this.#log?.warn({ outcome: "alerta_da_conta", tenant_id: tenantId });
    }
    return registou;
  }

  /**
   * Mede a utilização do escalão de mensagens (critério 7).
   *
   * «Utilizadores únicos contactados por template nas últimas 24 h ÷ limite do
   * escalão»; 200 distintos com `TIER_250` dá `0,8` e dispara alerta.
   *
   * Observa a métrica e devolve a leitura. Um escalão que não se reconhece dá
   * `racio: null` — «não sei» e não «está folgado».
   */
  async utilizacao(tenantId: string, phoneNumberId: string): Promise<Utilizacao | null> {
    const canal = await this.canal(tenantId, phoneNumberId);
    if (canal === null) return null;

    const linhas = await this.#bd.query<{ unicos: number | string }>(
      SQL_UNICOS_FORA_DA_JANELA,
      [tenantId, phoneNumberId, this.#instante()],
    );
    const unicos = Number(linhas.rows[0]?.unicos ?? 0);
    const leitura = utilizacaoDoEscalao(unicos, canal.messagingLimit);
    if (leitura.racio !== null) {
      this.#metricas.observarUtilizacao(canal.channelId, leitura.racio);
    }
    if (leitura.avisa) {
      this.#log?.warn({ outcome: "limite_de_mensagens_perto", tenant_id: tenantId });
    }
    return leitura;
  }
}
