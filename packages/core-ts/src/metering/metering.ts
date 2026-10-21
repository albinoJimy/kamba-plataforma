/**
 * O contador do *free tier* e a detecção do método de pagamento (KAM-023).
 *
 * É este módulo que preenche a porta `EstadoDoFreeTier` que o KAM-015 declarou
 * e deixou a `null` — «`null` até o KAM-023 o manter», diz o `Dependencias` do
 * adapter. As duas metades da mesma coluna vivem aqui: quem **lê** o contador
 * (`estado`) e quem o **escreve** (`contar`).
 *
 * ## Quem chama o `contar`, e porque é que não é este módulo a decidir quando
 *
 * O `contar` não inspecciona estados nem `pricing`. É accionado por quem já
 * sabe que houve entrega de uma *service*: o `Saida.ingerir` do KAM-015, que
 * decide a transição sob `FOR UPDATE` e devolve `entregou`. Essa é a única
 * fonte de verdade sobre «**esta** chegada foi a que entregou», porque a Meta
 * reenvia os `statuses` sem ordem garantida e com entrega concorrente
 * (CONFIRMADO, `E1` §5).
 *
 * É daí que vem a idempotência do critério 2 sem uma única linha de código
 * sobre `wamid` neste ficheiro: três repetições do mesmo `delivered` produzem
 * **uma** transição na base, logo **uma** chamada a `contar`, logo `+1`. Se
 * este módulo relesse o estado para decidir sozinho, reabria exactamente a
 * corrida que o `SQL_AVANCAR_ESTADO` fechou — e desta vez no contador em vez de
 * no custo, onde o KAM-015 já a pagou uma vez.
 *
 * ## O que este módulo **não** faz, e é escopo e não esquecimento
 *
 * * **Não avisa o dono.** O canal alternativo é o KAM-115, que nomeia este
 *   ticket como emissor. Aqui conta-se e registra-se; quem notifica é ele.
 * * **Não lê `config/meta_rates.yaml`.** O critério 4 manda ler dali, e lê-se —
 *   em Python, no `TestTarifas` de `db/tests_outbound/`, que compara o YAML com
 *   as constantes de `tarifas.ts` **como texto**. Acrescentar um leitor de YAML
 *   a `packages/core-ts` era trazer uma dependência de terceiros ao caminho de
 *   produção para ler quatro números que mudam uma vez por trimestre; a razão
 *   está escrita no cabeçalho do próprio YAML e no `tarifas.ts`, e é do
 *   KAM-015.
 */

import type { Logger } from "../logger/index.ts";
import { FREE_TIER_DE_SERVICE } from "../outbound/index.ts";

import { validarPayload } from "../eventos/contratos.ts";

import {
  AGREGADO_CHANNEL_UPDATED,
  JANELA_DE_FALHAS,
  TIPO_CHANNEL_UPDATED,
  VERSAO_CHANNEL_UPDATED,
  type ClienteSql,
  type Contagem,
  type MotivoDeRestricao,
  type Reconciliacao,
  type Restricao,
} from "./contrato.ts";
import {
  SQL_CONTAR,
  SQL_EMITIR_CHANNEL_UPDATED,
  SQL_ESTADO,
  SQL_FALHAS_RECENTES,
  SQL_LEVANTAR_RESTRICAO,
  SQL_MARCAR_RESTRICAO,
  SQL_RECONCILIAR,
} from "./consultas.ts";
import {
  divergencia,
  microUsdEstimado,
  nivelAtingido,
  racioDoFreeTier,
  suspeitaDePagamento,
} from "./custo.ts";
import {
  METRICA_ALERTAS,
  METRICA_SUSPEITAS,
  METRICAS_DO_FREE_TIER,
  MetricasDoFreeTier,
} from "./metricas.ts";

export interface Dependencias {
  readonly bd: ClienteSql;
  readonly log?: Logger;
  readonly metricas?: MetricasDoFreeTier;
  /** O relógio, por parâmetro. `undefined` deixa o `now()` à base. */
  readonly agora?: () => Date;
}

/**
 * O que o `estado` devolve para um canal que não existe.
 *
 * **É o tecto, e isso faz com que se conte custo.** A escolha é a que o
 * `estados.ts` do KAM-015 já escreveu para o `freeTier` a `null`: «subestimar o
 * custo é pior do que sobrestimar, porque uma factura maior do que o painel é
 * uma surpresa e o contrário é uma folga».
 *
 * Devolver `{ usadas: 0 }` era o contrário: um canal desconhecido ganhava mil
 * mensagens grátis que ninguém lhe deu, e o custo dessas mil não aparecia em
 * painel nenhum até a factura chegar. Zero linhas acontece quando o canal não
 * existe, quando é de outro *tenant*, e — o caso que importa — quando o
 * contexto de RLS está trocado: a política devolve vazio em vez de erro, e
 * tratar vazio como «zero usadas» era transformar um contexto errado em
 * desconto.
 */
const DESCONHECIDO = {
  usadas: FREE_TIER_DE_SERVICE,
  tecto: FREE_TIER_DE_SERVICE,
} as const;

/** O contador do *free tier* de um canal. */
export class Metering {
  readonly #bd: ClienteSql;
  readonly #log: Logger | undefined;
  readonly #metricas: MetricasDoFreeTier;
  readonly #agora: (() => Date) | undefined;

  constructor(dependencias: Dependencias) {
    this.#bd = dependencias.bd;
    this.#log = dependencias.log;
    this.#metricas = dependencias.metricas ?? METRICAS_DO_FREE_TIER;
    this.#agora = dependencias.agora;
  }

  /** O instante a passar à base, ou `null` para ela usar o `now()` dela. */
  #instante(): string | null {
    const agora = this.#agora?.();
    return agora === undefined ? null : agora.toISOString();
  }

  /**
   * Quantas *service* já foram entregues neste canal e neste mês.
   *
   * Tem a forma exacta da porta `EstadoDoFreeTier` do KAM-015, e é para lá que
   * vai: `new Saida({ ..., freeTier: (t, p) => metering.estado(t, p) })`.
   *
   * O mês é da base (`platform.ten_periodo`) e a leitura já devolve `0` quando
   * o mês virou sem ninguém ter escrito — ver a nota do `SQL_ESTADO`, que é
   * onde está o defeito que isso evita.
   */
  async estado(
    tenantId: string,
    phoneNumberId: string,
  ): Promise<{ readonly usadas: number; readonly tecto: number }> {
    const usadas = await this.#contador(tenantId, phoneNumberId);
    return usadas === null
      ? DESCONHECIDO
      : { usadas, tecto: FREE_TIER_DE_SERVICE };
  }

  /**
   * O contador do canal, ou `null` quando o canal não existe.
   *
   * **Existe para separar «não sei» de «mil», e a separação importa.** O
   * `estado` dobra o «não sei» no tecto de propósito, porque a porta do
   * KAM-015 tem de devolver um número e o conservador é contar custo. Mas a
   * reconciliação não pode fazer o mesmo: uma agregação devolve **sempre** uma
   * linha, logo o guarda de «zero linhas» nunca dispara lá, e um canal
   * desconhecido saía do relatório como `contador: 1000` contra `entregues: 0`
   * — um número inventado apresentado como medição. Com o `null`, a
   * reconciliação desiste em vez de inventar.
   */
  async #contador(tenantId: string, phoneNumberId: string): Promise<number | null> {
    const linhas = await this.#bd.query<{ usadas: number | string }>(SQL_ESTADO, [
      tenantId,
      phoneNumberId,
      this.#instante(),
    ]);
    const linha = linhas.rows[0];
    if (linha === undefined) {
      // Não é silêncio: um canal que não se encontra é um achado para quem
      // opera, e o `outcome` é a única forma de o dizer dentro dos nove campos
      // que a política de registo permite.
      this.#log?.warn({ outcome: "free_tier_canal_desconhecido", tenant_id: tenantId });
      return null;
    }
    return Number(linha.usadas);
  }

  /**
   * Conta uma *service* entregue, e diz se este incremento atravessou um
   * limiar.
   *
   * Devolve `null` para um canal que não existe — e aí **não** se inventa um
   * contador: ao contrário do `estado`, onde o conservador é assumir o tecto,
   * aqui não há nada a escrever e fingir que se escreveu era perder a entrega
   * em silêncio.
   *
   * As métricas são observadas aqui e não em quem chama, porque é aqui que o
   * valor novo do contador existe; obrigar o chamador a chamar `observar`
   * depois era deixar a métrica a depender de ele se lembrar.
   */
  async contar(tenantId: string, phoneNumberId: string): Promise<Contagem | null> {
    const linhas = await this.#bd.query<{
      usadas_antes: number | string;
      reiniciou: boolean;
      usadas: number | string;
      // `string` e não `Date`: a consulta devolve-o em `to_char`. Ver a nota do
      // `consultas.ts` — receber um `Date` daqui custava um dia de erro na
      // fronteira do mês em qualquer processo que não corresse em UTC.
      mes: string;
    }>(SQL_CONTAR, [tenantId, phoneNumberId, this.#instante()]);
    const linha = linhas.rows[0];
    if (linha === undefined) {
      this.#log?.warn({ outcome: "free_tier_canal_desconhecido", tenant_id: tenantId });
      return null;
    }

    const antesCru = Number(linha.usadas_antes);
    const usadas = Number(linha.usadas);
    const reiniciou = linha.reiniciou;
    const nivel = nivelAtingido(antesCru, usadas, reiniciou);

    this.#metricas.observar(
      phoneNumberId,
      racioDoFreeTier(usadas),
      microUsdEstimado(usadas),
    );

    if (nivel !== null) {
      this.#metricas.contar(METRICA_ALERTAS, nivel);
      // **O aviso não nomeia o canal, e isso é a política e não um descuido.**
      // Os nove campos que o `logger/politica.ts` permite a quem chama não
      // incluem `phone_number_id`, e o DoD deste ticket pede «métricas e
      // alertas sem telefone nem conteúdo». Quem avisa o dono com os detalhes é
      // o KAM-115, por um canal que não é o registo.
      this.#log?.warn({ outcome: `free_tier_${nivel}`, tenant_id: tenantId });
    }

    return {
      usadas,
      antes: reiniciou ? 0 : antesCru,
      mes: linha.mes,
      reiniciou,
      nivel,
    };
  }

  /**
   * `true` quando a taxa de falhas recentes sugere falta de método de pagamento
   * (critério 5).
   *
   * Lê a janela da base e decide com a regra pura de `custo.ts`. Conta a
   * suspeita antes de a devolver: uma heurística de limiares **propostos** que
   * não deixe rasto não se consegue calibrar, e calibrá-la é a razão de ela
   * existir assim em vez de comparar com um código de erro — que é NÃO
   * VERIFICADO.
   *
   * **Não marca nada e não emite evento.** A marca (`motivo_restricao`) e o
   * `channel.updated` do critério 6 precisam de uma coluna que não existe, e
   * entram com a revisão `0013`.
   */
  async suspeita(tenantId: string, phoneNumberId: string): Promise<boolean> {
    const { usadas } = await this.estado(tenantId, phoneNumberId);
    const linhas = await this.#bd.query<{
      total: number | string;
      falhas: number | string;
    }>(SQL_FALHAS_RECENTES, [tenantId, phoneNumberId, JANELA_DE_FALHAS]);
    const linha = linhas.rows[0];
    // Sem linha a janela é vazia, e uma janela vazia nunca é suspeita: é o
    // mínimo do `total >= 20` aplicado ao caso em que a agregação não devolveu
    // nada.
    if (linha === undefined) return false;

    const janela = { total: Number(linha.total), falhas: Number(linha.falhas) };
    if (!suspeitaDePagamento(usadas, janela)) return false;

    this.#metricas.contar(METRICA_SUSPEITAS);
    this.#log?.warn({ outcome: "meta_pagamento_suspeito", tenant_id: tenantId });
    return true;
  }

  /**
   * Marca o canal com um motivo de restrição e emite `channel.updated`
   * (critério 6; revisão `0013`).
   *
   * Guarda também o código de erro que a Meta devolveu, se houver (critério 5).
   * As duas coisas numa instrução: separar deixava uma janela em que o canal
   * está marcado e o código que o justificou não está guardado, e é essa a
   * janela que interessa a quem for calibrar a heurística.
   *
   * **O evento sai uma vez por restrição, e não uma por mensagem falhada.** A
   * Meta reenvia os `statuses` e a heurística volta a disparar enquanto a taxa
   * se mantiver; quem decide é o `marcado` que a base devolve do `antes`, sob
   * `FOR UPDATE`. Sob concorrência, um dos processos vê `NULL` e só esse emite.
   *
   * **O `payload` valida-se contra o contrato antes de qualquer escrita.** É a
   * regra do KAM-007, e a razão é a do `chr/eventos.ts`: um campo a mais dá um
   * `check_violation` do `evt_emitir` ou, pior, um evento publicado com um
   * campo que nenhum consumidor conhece. O contrato de `channel.updated` pede
   * exactamente `phone_number_id` e `motivo` — e **nenhum dos dois é PII**: o
   * `phone_number_id` é um identificador opaco da Meta e não um telefone, como
   * o inventário da `0001` diz por extenso.
   *
   * Devolve `null` para um canal que não existe: não há nada a marcar, e
   * inventar uma marca era pior do que não a fazer.
   */
  async marcarRestricao(
    tenantId: string,
    phoneNumberId: string,
    motivo: MotivoDeRestricao,
    codigo: number | null,
  ): Promise<Restricao | null> {
    const linhas = await this.#bd.query<{
      id: string;
      marcado: boolean;
      codigos: readonly number[] | null;
    }>(SQL_MARCAR_RESTRICAO, [
      tenantId,
      phoneNumberId,
      motivo,
      codigo === null || !Number.isInteger(codigo) ? null : codigo,
    ]);
    const linha = linhas.rows[0];
    if (linha === undefined) {
      this.#log?.warn({ outcome: "free_tier_canal_desconhecido", tenant_id: tenantId });
      return null;
    }

    const codigos = linha.codigos ?? [];
    if (!linha.marcado) {
      // Já estava marcado. O conjunto de códigos pode ter crescido — e é por
      // isso que isto não é um `return null` —, mas não há restrição nova para
      // anunciar.
      return { marcou: false, codigos, eventoId: null };
    }

    const eventoId = await this.#emitirCanalActualizado(tenantId, linha.id, phoneNumberId, motivo);
    this.#log?.warn({ outcome: `canal_restrito_${motivo}`, tenant_id: tenantId });
    return { marcou: true, codigos, eventoId };
  }

  /**
   * Levanta a restrição de um canal, e emite `channel.updated` (critério 6).
   *
   * O critério diz «remover o motivo exige estado `delivered` posterior ou
   * limpeza manual registada». Este é o primeiro caminho: quem chama é quem viu
   * uma entrega **nova**, e uma entrega é a única coisa que desmente a
   * suspeita — a Meta voltou a entregar.
   *
   * **Levanta só o motivo que lhe dão.** Um canal restrito por qualidade
   * (KAM-021) continua a entregar mensagens, pelo que uma entrega não é prova
   * de que a qualidade melhorou; limpar a marca de outro ticket ao passar era
   * apagar uma decisão que não é nossa.
   *
   * Devolve `false` quando não havia esta marca para levantar, e nesse caso
   * **não emite nada**: um `channel.updated` por cada entrega de um canal
   * saudável era um evento por mensagem.
   */
  async levantarRestricao(
    tenantId: string,
    phoneNumberId: string,
    motivo: MotivoDeRestricao,
  ): Promise<boolean> {
    const linhas = await this.#bd.query<{ id: string }>(SQL_LEVANTAR_RESTRICAO, [
      tenantId,
      phoneNumberId,
      motivo,
    ]);
    const linha = linhas.rows[0];
    if (linha === undefined) return false;

    await this.#emitirCanalActualizado(tenantId, linha.id, phoneNumberId, motivo);
    this.#log?.warn({ outcome: `canal_liberto_${motivo}`, tenant_id: tenantId });
    return true;
  }

  /**
   * Emite o `channel.updated` e devolve o `event_id`.
   *
   * Numa função e não na cadeia repetida duas vezes, porque a parte que importa
   * é a recusa: **o `event_id` ausente não se cala.** O `evt_emitir` devolve-o,
   * e a sua ausência significa que o evento pode não ter chegado ao
   * `events_outbox` — com o canal **já marcado**, isso é uma marca sem ninguém
   * avisado. É a mesma recusa do `emitirContactMerged` do KAM-014, e a razão de
   * ela ser um `throw` e não um registo é que quem chama tem de poder repetir.
   */
  async #emitirCanalActualizado(
    tenantId: string,
    channelId: string,
    phoneNumberId: string,
    motivo: MotivoDeRestricao,
  ): Promise<string> {
    const payload = { phone_number_id: phoneNumberId, motivo };
    validarPayload(TIPO_CHANNEL_UPDATED, VERSAO_CHANNEL_UPDATED, payload);
    const emissao = await this.#bd.query<{ event_id: string }>(
      SQL_EMITIR_CHANNEL_UPDATED,
      [
        TIPO_CHANNEL_UPDATED,
        VERSAO_CHANNEL_UPDATED,
        tenantId,
        AGREGADO_CHANNEL_UPDATED,
        channelId,
        JSON.stringify(payload),
      ],
    );
    const eventoId = emissao.rows[0]?.event_id;
    if (typeof eventoId !== "string") {
      throw new Error(
        "platform.evt_emitir nao devolveu um event_id: o channel.updated pode " +
          "nao ter sido escrito no outbox, e a marca do canal ficaria sem " +
          "ninguem avisado",
      );
    }
    return eventoId;
  }

  /**
   * Compara o nosso contador com o que o `pricing` testemunha (critério 7).
   *
   * É o instrumento do critério de saída, não o critério: ele pede «ao fim de 1
   * mês real» e uma divergência ≤ 2%, e um mês real não cabe num PR. O que
   * existe aqui é o que torna a medição possível quando o mês houver, e as
   * **duas** divergências que a pergunta ambígua do critério admite — ver a
   * nota de `Reconciliacao`.
   *
   * **Reconcilia o mês corrente, e só esse — não há outro que possa
   * reconciliar.** O `free_tier_used` é uma coluna e não uma série: quando o
   * mês vira, o valor anterior desaparece. A primeira versão aceitava um
   * período por parâmetro e, pedida sobre um mês passado, comparava um contador
   * reposto a zero com as entregas desse mês — 100% de divergência num canal
   * onde tudo estava certo. Tirar o parâmetro não é uma limitação nova: é
   * deixar de prometer o que nunca foi possível.
   *
   * O mês sai da mesma função que decide o do contador, com o mesmo instante.
   */
  async reconciliar(
    tenantId: string,
    phoneNumberId: string,
  ): Promise<Reconciliacao | null> {
    const usadas = await this.#contador(tenantId, phoneNumberId);
    // Um canal que não existe não se reconcilia. Ver a nota do `#contador`: o
    // guarda de «zero linhas», abaixo, nunca o apanharia — uma agregação
    // devolve sempre uma linha.
    if (usadas === null) return null;
    const linhas = await this.#bd.query<{
      entregues: number | string;
      facturaveis: number | string;
    }>(SQL_RECONCILIAR, [tenantId, phoneNumberId, this.#instante()]);
    const linha = linhas.rows[0];
    if (linha === undefined) return null;

    const entregues = Number(linha.entregues);
    const facturaveis = Number(linha.facturaveis);
    const estimadasFacturaveis = Math.max(0, usadas - FREE_TIER_DE_SERVICE);

    return {
      contador: usadas,
      entregues,
      facturaveis,
      estimadasFacturaveis,
      divergenciaDaContagem: divergencia(usadas, entregues),
      divergenciaDoFacturavel: divergencia(estimadasFacturaveis, facturaveis),
      microUsdEstimado: microUsdEstimado(usadas),
    };
  }
}
