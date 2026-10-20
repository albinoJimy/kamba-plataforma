/**
 * O `ChannelAdapter` de saída (KAM-015).
 *
 * Junta o que os outros módulos decidem, e a sua própria contribuição é a
 * **ordem**. Cada passo está onde está por uma razão que custaria uma mensagem,
 * um envio duplicado ou um dado pessoal se estivesse noutro lugar:
 *
 * 1. **Forma** (`decisao.formaInvalida`) — antes de tudo, sem tocar na base nem
 *    na rede. É o critério 7: «4 botões ou 11 linhas falham antes de qualquer
 *    chamada».
 * 2. **Janela, template e categoria do Piloto** (`decisao.decidir`) — uma
 *    leitura da base, duas quando o corpo é um template. Com janela fechada e
 *    conteúdo livre, devolve `WINDOW_CLOSED` **sem chamada HTTP** (critério 1);
 *    o `marketing` é recusado aqui dentro, pela lista de categorias do Piloto,
 *    e não num passo próprio.
 * 3. **O guarda do KAM-018** (`PreSendGuard`) — só para o bot, e **falha
 *    fechada**: sem guarda instalada, levanta em CI (critério 8).
 * 4. **A linha, antes da rede** (`SQL_ENFILEIRAR`) — e é isto que faz a
 *    idempotência. O `ON CONFLICT ... DO NOTHING RETURNING` vazio significa «a
 *    chave já passou», e nesse caso **não há chamada HTTP nenhuma** (critério
 *    2). Enfileirar depois de enviar dava uma mensagem entregue sem linha, que
 *    é pior do que uma linha sem mensagem.
 * 5. **O destinatário** (`ObterDestinatario`) — por BSUID quando existe. Só
 *    agora, porque é a única coisa que precisa do módulo de identidade e não
 *    vale pedi-la para um envio que vai ser recusado.
 * 6. **O *token bucket*** (`limites.pedir`, em ciclo) — depois da linha e antes
 *    da rede. Travar antes de enfileirar fazia a chave ser recusada e o
 *    chamador repetir com uma chave nova, que é perder a idempotência para
 *    poupar uma linha.
 * 7. **A rede, com *backoff*** — três **repetições** (quatro chamadas, ver
 *    `REPETICOES` em `limites.ts`), `130429` e 5xx repetem, `131049` não
 *    (critério 6).
 *
 * São **sete** e a primeira versão desta lista tinha oito, com uma «categoria
 * do Piloto» como passo próprio que o corpo nunca teve — a numeração da lista
 * e a dos comentários do corpo divergiam a partir do segundo. Uma lista de
 * passos que não casa com os passos é pior do que nenhuma.
 *
 * ## O que este adapter não faz
 *
 * Não decide **quem tem a palavra** (é o `mode`, KAM-018, e é o que o guarda
 * consulta); não conta o *free tier* (KAM-023, e entra por porta); não consome
 * os webhooks de template (KAM-016/021, e o que está aqui é a regra de bloqueio
 * que eles accionam); não avisa o dono quando uma mensagem expira (KAM-115);
 * não publica evento de barramento (nenhum critério o pede).
 */

import { Logger, idOpaco } from "../logger/index.ts";
import {
  CATEGORIAS_DO_PILOTO,
  FREE_TIER_DE_SERVICE,
  IDIOMA_BASE,
  WINDOW_CLOSED,
  type Categoria,
  type ClienteDaMeta,
  type ClienteSql,
  type Estado,
  type EstadoDoFreeTier,
  type MotivoDeRecusa,
  type ObterDestinatario,
  type Pedido,
  type PreSendGuard,
  type Pricing,
  type Resultado,
  type Template,
} from "./contrato.ts";
import {
  SQL_AVANCAR_ESTADO,
  SQL_BLOQUEAR_TEMPLATE,
  SQL_ENFILEIRAR,
  SQL_JANELA,
  SQL_MARCAR_ENVIADA,
  SQL_MARCAR_FALHADA,
  SQL_POR_CHAVE,
  SQL_POR_WAMID,
  SQL_TEMPLATE,
} from "./consultas.ts";
import { categoriaDe, decidir, formaInvalida, type Janela } from "./decisao.ts";
import { avancar, ingerir, terminal } from "./estados.ts";
import {
  ESPERA_MAXIMA_DE_DEBITO_MS,
  Limites,
  atrasoMs,
  vaiRepetir,
} from "./limites.ts";
import {
  METRICA_CUSTO,
  METRICA_DURACAO,
  METRICA_ENVIADAS,
  METRICA_JANELA_FECHADA,
  METRICA_TRAVADAS,
  MetricasDaSaida,
} from "./metricas.ts";

/** A variável que diz em que ambiente o processo corre. */
export const VARIAVEL_DO_AMBIENTE = "KAMBA_ENV";

/** O que vai no `error_code` quando não houve código da Meta nenhum. */
export const SEM_CODIGO_NO_REGISTO = "sem_codigo";

/**
 * O `error_code` do registo, a partir do código da Meta.
 *
 * **A gramática do campo não aceita o sinal `-`** (`logger/politica.ts`: um
 * segmento é letras ou um a seis dígitos), e o `CODIGO_SEM_CODIGO` do
 * `cliente.ts` é `-1` — o que ele devolve num *timeout*, numa falha de rede e
 * num `200` sem `wamid`. Em modo estrito, que é o do CI, um `"-1"` fazia o
 * `Logger` **levantar**, e um *timeout* da Meta passava a excepção não tratada
 * no caminho de envio em vez de uma recusa com código. Fora do estrito o campo
 * era descartado — perder o código precisamente na linha em que ele é útil.
 *
 * Qualquer negativo vira `sem_codigo` e não só o `-1`: um código negativo nunca
 * é da Meta, e inventar-lhe um nome por cada valor era pior do que dizer «não
 * houve código».
 */
export function codigoParaRegisto(codigo: number): string {
  return Number.isInteger(codigo) && codigo >= 0 ? String(codigo) : SEM_CODIGO_NO_REGISTO;
}

/** Falta o `PreSendGuard` do KAM-018 e o ambiente não o perdoa. */
export class SemGuardaError extends Error {
  constructor() {
    super(
      "o envio do bot exige o PreSendGuard do KAM-018, e nao ha nenhum " +
        "instalado. O criterio 8 do KAM-015 diz «sem ele, o envio do bot falha " +
        "em ambiente de CI»: um gancho que falte e deixe passar e um gancho que " +
        "nao existe, e o que ele protege e uma conversa em modo dono ou humano " +
        "de ser interrompida pelo assistente (docs/tecnica/01 §10.2).",
    );
    this.name = "SemGuardaError";
  }
}

/** O que o adapter precisa para funcionar. */
export interface Dependencias {
  readonly bd: ClienteSql;
  readonly meta: ClienteDaMeta;
  readonly destinatario: ObterDestinatario;
  /** `null` até o KAM-018 o instalar. Ver `SemGuardaError`. */
  readonly guarda: PreSendGuard | null;
  /** `null` até o KAM-023 o manter. Nesse caso conta-se tudo. */
  readonly freeTier: EstadoDoFreeTier | null;
  readonly log?: Logger;
  readonly metricas?: MetricasDaSaida;
  /** O relógio, por parâmetro. Ver a nota de `limites.ts`. */
  readonly agora?: () => Date;
  /** O aleatório do *jitter*, por parâmetro, para o teste ser determinístico. */
  readonly aleatorio?: () => number;
  /** Como esperar. Porta para o teste não dormir de verdade. */
  readonly dormir?: (ms: number) => Promise<void>;
  readonly ambiente?: Readonly<Record<string, string | undefined>>;
  /**
   * Os tectos de débito. Por omissão, os do módulo.
   *
   * Entra por parâmetro para que um teste possa dar-lhe um tecto absurdo e
   * medir o que acontece a uma espera longa — ver `ESPERA_MAXIMA_DE_DEBITO_MS`.
   * Em produção ninguém o passa.
   */
  readonly limites?: Limites;
}

/** O `ChannelAdapter` de saída. */
export class Saida {
  readonly #bd: ClienteSql;
  readonly #meta: ClienteDaMeta;
  readonly #destinatario: ObterDestinatario;
  readonly #guarda: PreSendGuard | null;
  readonly #freeTier: EstadoDoFreeTier | null;
  readonly #log: Logger | undefined;
  readonly #metricas: MetricasDaSaida;
  readonly #agora: () => Date;
  readonly #aleatorio: () => number;
  readonly #dormir: (ms: number) => Promise<void>;
  readonly #ambiente: Readonly<Record<string, string | undefined>>;
  readonly #limites: Limites;

  constructor(dependencias: Dependencias) {
    this.#bd = dependencias.bd;
    this.#meta = dependencias.meta;
    this.#destinatario = dependencias.destinatario;
    this.#guarda = dependencias.guarda;
    this.#freeTier = dependencias.freeTier;
    this.#log = dependencias.log;
    this.#metricas = dependencias.metricas ?? new MetricasDaSaida();
    this.#agora = dependencias.agora ?? (() => new Date());
    this.#aleatorio = dependencias.aleatorio ?? Math.random;
    this.#dormir =
      dependencias.dormir ??
      ((ms) => new Promise<void>((resolver) => setTimeout(resolver, ms)));
    this.#ambiente = dependencias.ambiente ?? process.env;
    this.#limites = dependencias.limites ?? new Limites();
  }

  get metricas(): MetricasDaSaida {
    return this.#metricas;
  }

  get limites(): Limites {
    return this.#limites;
  }

  /** Envia, pela ordem do módulo. */
  async enviar(pedido: Pedido): Promise<Resultado> {
    const inicio = Date.now();
    try {
      return await this.#enviar(pedido);
    } finally {
      this.#metricas.medir(METRICA_DURACAO, Date.now() - inicio);
    }
  }

  async #enviar(pedido: Pedido): Promise<Resultado> {
    // 1. Forma, sem tocar na base nem na rede.
    const forma = formaInvalida(pedido.corpo);
    if (forma !== null) return this.#recusar(pedido, forma);

    // 2. Janela e template, uma leitura.
    const janela = await this.#janela(pedido);
    const template =
      pedido.corpo.tipo === "template"
        ? await this.#template(pedido.tenantId, pedido.corpo.nome, pedido.corpo.idioma)
        : null;

    const decisao = decidir(pedido.corpo, janela, this.#agora(), template);
    if (!decisao.enviar) return this.#recusar(pedido, decisao.motivo);

    // 3. O guarda do KAM-018, só para o bot, e falha fechada.
    if (pedido.doBot) {
      if (this.#guarda === null) {
        // Em CI **levanta**; fora de CI recusa e conta. A diferença é
        // deliberada: o critério 8 pede que o CI falhe, e um processo de
        // produção que levante a cada envio é pior do que um que recuse e
        // registe — mas nenhum dos dois **envia**.
        if ((this.#ambiente[VARIAVEL_DO_AMBIENTE] ?? "") === "ci") {
          throw new SemGuardaError();
        }
        // O `tenant_id` pode ir ao registo (esta na *allowlist* do
        // `logger/politica.ts`); o `contact_id` **nao**, e por isso nao vai.
        this.#log?.warn({ outcome: "sem_guarda", tenant_id: pedido.tenantId });
        return this.#recusar(pedido, "GUARD_REFUSED");
      }
      if (!(await this.#guarda(pedido))) return this.#recusar(pedido, "GUARD_REFUSED");
    }

    // 4. A linha, **antes** da rede. É isto que faz a idempotência.
    const enfileirada = await this.#enfileirar(pedido, decisao.kind, decisao.templateName);
    if (enfileirada === null) {
      // A chave já tinha passado: **sem chamada HTTP**. Devolve o que existe.
      const anterior = await this.#porChave(pedido.tenantId, pedido.idempotencyKey);
      return {
        ok: true,
        id: anterior?.id ?? "",
        wamid: anterior?.wamid ?? null,
        kind: (anterior?.kind as Categoria | undefined) ?? decisao.kind,
        repetido: true,
      };
    }

    // 5. O destinatário, por BSUID quando existe.
    const para = await this.#destinatario(pedido.tenantId, pedido.contactId);
    if (para.bsuid === null && para.telefone === null) {
      await this.#falhar(pedido.tenantId, enfileirada, null);
      return this.#recusar(pedido, "NO_RECIPIENT");
    }

    // 6. O *token bucket*, depois da linha e antes da rede.
    //
    // **Em ciclo, e não uma espera só.** O `pedir` devolve os milissegundos a
    // esperar e **não consome** quando algum tecto não tem vaga — logo, quem
    // dorme uma vez e envia está a enviar sem ficha. A primeira versão fazia
    // isso, e o efeito mediu-se ao montar o critério 5 na porta da Meta: os
    // dois primeiros envios de um canal saíam no mesmo instante e a janela de
    // 1 s que os apanha via **dezasseis**. O ciclo é o que faz o adapter
    // obedecer à mesma regra que a bateria de `limites.ts` já afirmava —
    // provar a regra numa função pura não prova que quem a chama a respeita.
    for (;;) {
      const espera = this.#limites.pedir(
        pedido.phoneNumberId,
        pedido.tenantId,
        pedido.contactId,
        this.#agora().getTime(),
      );
      if (espera === 0) break;
      // **Uma espera longa é uma recusa, não um sono.** O tecto por minuto do
      // par pode pedir até 60 s, e dormir um minuto aqui prende o chamador, o
      // *job* e a ligação à base por causa de um tecto nosso. O
      // `RATE_LIMITED` é o motivo que o `MOTIVOS_DE_RECUSA` já declarava e que
      // nada devolvia — um valor morto numa lista fechada de dez.
      if (espera > ESPERA_MAXIMA_DE_DEBITO_MS) {
        this.#metricas.contar(METRICA_TRAVADAS, "bucket");
        await this.#falhar(pedido.tenantId, enfileirada, null);
        return this.#recusar(pedido, "RATE_LIMITED");
      }
      // `bucket`: foi o **nosso** tecto que travou. A outra origem é o
      // `130429` da Meta, mais abaixo, e as duas não se somam — ver
      // `metricas.ts`.
      this.#metricas.contar(METRICA_TRAVADAS, "bucket");
      await this.#dormir(espera);
    }

    // 7. A rede, com *backoff*.
    for (let tentativa = 1; ; tentativa += 1) {
      const resposta = await this.#meta.enviar(pedido.phoneNumberId, para, pedido.corpo);
      if (resposta.ok) {
        await this.#bd.query(SQL_MARCAR_ENVIADA, [
          pedido.tenantId,
          enfileirada,
          resposta.wamid,
        ]);
        this.#metricas.contar(METRICA_ENVIADAS, decisao.kind);
        // **O `wamid` não vai em claro para o registo**: leva o número do
        // interlocutor em base64 (`docs/logs.md` §2.1), e a *allowlist* do
        // `logger/politica.ts` recusa um campo que não seja dela. O `idOpaco`
        // é o que o §3.10 do dicionário fixa para isto (`m_` + 32 hexadecimais
        // do SHA-256), e o campo é o `msg_id` — o mesmo par que o
        // `entrada/registo.ts` já usa. É o que o X-11 do gate 6 varre.
        this.#log?.info({
          outcome: "enviada",
          tenant_id: pedido.tenantId,
          msg_id: idOpaco(resposta.wamid),
        });
        return {
          ok: true,
          id: enfileirada,
          wamid: resposta.wamid,
          kind: decisao.kind,
          repetido: false,
        };
      }

      if (!vaiRepetir(resposta.codigo, tentativa)) {
        await this.#falhar(pedido.tenantId, enfileirada, resposta.codigo);
        this.#log?.warn({
          outcome: "envio_recusado",
          tenant_id: pedido.tenantId,
          // `error_code` e **texto** na *allowlist* do logger, nao numero: e
          // um codigo de dominio e nao uma grandeza, e somar codigos de erro
          // nao quer dizer nada. E passa pelo `codigoParaRegisto`, porque o
          // sinal `-` nao cabe na gramatica do campo — ver a funcao.
          error_code: codigoParaRegisto(resposta.codigo),
        });
        return { ok: false, motivo: "SEND_FAILED", codigo: resposta.codigo };
      }

      // `meta`: foi o tecto **dela** que travou, e isso é uma leitura
      // diferente da do nosso balde — um painel que as some não sabe qual dos
      // dois subir ou baixar.
      this.#metricas.contar(METRICA_TRAVADAS, "meta");
      await this.#dormir(atrasoMs(tentativa, resposta.esperar, this.#aleatorio()));
    }
  }

  /**
   * Ingere um `statuses` da Meta: avança o estado e conta o custo.
   *
   * A monotonia é imposta **pela base** (o `antes.state = ANY($4)` do
   * `SQL_AVANCAR_ESTADO`) e não por este código: dois `statuses` concorrentes da
   * mesma mensagem chegam em dois processos, e só a base os serializa.
   *
   * **E o custo calcula-se a partir do `estado_antes` que a base devolve**, não
   * da leitura prévia. A leitura prévia serve para duas coisas e nenhuma delas
   * é o dinheiro: saber que a linha existe, e saber se o `pricing` traz uma
   * categoria que não conhecemos. Calcular o custo a partir dela duplicava-o
   * quando dois `statuses` chegavam juntos — ver a nota do `SQL_AVANCAR_ESTADO`.
   */
  async ingerir(
    tenantId: string,
    wamid: string,
    estado: Estado,
    pricing: Pricing | null,
    phoneNumberId: string,
  ): Promise<{ readonly avancou: boolean; readonly microUsd: number }> {
    const actual = await this.#porWamid(tenantId, wamid);
    if (actual === null) {
      // **Um `statuses` para uma mensagem que não existe, e isso faz barulho.**
      //
      // O caso real não é um `wamid` inventado: é a nossa própria escrita do
      // `wamid` (o `SQL_MARCAR_ENVIADA`) ainda não ter comprometido quando o
      // *webhook* `delivered` chega noutro processo. Devolver `avancou: false`
      // em silêncio deixava a linha em `sent` para sempre e o custo nunca
      // contado — e o `SQL_CUSTO_DO_TENANT` também não a vê, porque filtra por
      // `pricing IS NOT NULL`. Não há aqui fila nem reconciliação que a
      // recupere (é o KAM-022 que liga o envio ao turno), pelo que o mínimo
      // honesto é não perder o acontecimento em silêncio.
      this.#log?.warn({
        outcome: "status_sem_mensagem",
        tenant_id: tenantId,
        msg_id: idOpaco(wamid),
      });
      return { avancou: false, microUsd: 0 };
    }

    const freeTier =
      this.#freeTier === null
        ? null
        : await this.#freeTier(tenantId, phoneNumberId).then((estadoDoTier) => ({
            usadas: estadoDoTier.usadas,
            tecto: estadoDoTier.tecto,
          }));

    // A leitura prévia só serve para desistir cedo: se nem com o estado que
    // acabámos de ler isto avança, não vale uma escrita. **Não é daqui que sai
    // o custo** — ver a nota do método e a do `SQL_AVANCAR_ESTADO`.
    if (!ingerir(actual.state, estado, pricing, freeTier).avancou) {
      return { avancou: false, microUsd: 0 };
    }

    // Os estados de que se pode sair para este, calculados aqui e aplicados
    // pela base. É a mesma regra do `estados.ts`, e a duplicação é deliberada:
    // aqui para a conhecer, lá para ganhar a corrida.
    const permitidos = this.#deOndeSePodeSair(estado);
    const linhas = await this.#bd.query<{ estado_antes: string }>(SQL_AVANCAR_ESTADO, [
      tenantId,
      wamid,
      estado,
      permitidos,
      pricing === null ? null : JSON.stringify(pricing),
    ]);
    // O `UPDATE` não mexeu em nada: outro processo ganhou a corrida. **Não se
    // conta custo**, e é por isso que a contagem está depois e não antes.
    if (linhas.rows.length === 0) return { avancou: false, microUsd: 0 };

    // **O custo sai da transição que de facto aconteceu.** O `estado_antes` é o
    // estado que este `UPDATE` substituiu, lido pela base sob `FOR UPDATE`: com
    // dois `statuses` concorrentes, o segundo vê o estado que o primeiro
    // escreveu e não o que ambos tinham lido. Era exactamente aqui que o custo
    // duplicava.
    // **Sem recurso à leitura prévia.** Um `?? actual.state` aqui tornava o
    // defeito invisível outra vez: em série a leitura prévia é o estado
    // anterior correcto, e o recurso fazia o código passar os testes
    // sequenciais sem nunca usar a palavra da base. Se a consulta devolveu uma
    // linha, ela traz o `estado_antes`; se não trouxesse, a forma da linha
    // estaria errada, e calar isso era esconder um defeito.
    const anterior = linhas.rows[0]?.estado_antes as Estado | undefined;
    if (anterior === undefined) {
      throw new Error(
        "SQL_AVANCAR_ESTADO devolveu uma linha sem `estado_antes`: e de la que " +
          "sai o custo, e adivinha-lo a partir de uma leitura anterior duplica-o " +
          "quando dois statuses chegam juntos",
      );
    }
    const resultado = ingerir(anterior, estado, pricing, freeTier);

    if (resultado.microUsd > 0) this.#metricas.somarCusto(resultado.microUsd);
    if (resultado.categoriaDesconhecida) {
      this.#log?.warn({
        outcome: "pricing_desconhecido",
        tenant_id: tenantId,
        msg_id: idOpaco(wamid),
      });
    }
    return { avancou: true, microUsd: resultado.microUsd };
  }

  /**
   * Bloqueia um template recategorizado para `marketing` (critério 9).
   *
   * Quem consome o webhook `template_category_update` é o KAM-016/021; o que
   * está aqui é a regra que eles accionam. Idempotente — a Meta reenvia — e
   * preserva o **primeiro** instante de bloqueio, que é o que se audita.
   */
  async bloquearTemplate(
    tenantId: string,
    nome: string,
    idioma: string,
    categoriaNova: string,
  ): Promise<boolean> {
    if (CATEGORIAS_DO_PILOTO.includes(categoriaNova as Categoria)) return false;
    const linhas = await this.#bd.query(SQL_BLOQUEAR_TEMPLATE, [
      tenantId,
      nome,
      idioma,
      categoriaNova,
    ]);
    if (linhas.rows.length > 0) {
      // O alerta que o critério 9 pede. O nome do template **não cabe na
      // *allowlist*** do registo — e não é perda: o `outcome` diz o que
      // aconteceu, o `tenant_id` diz a quem, e o nome está na linha da tabela,
      // que é onde se audita. A *allowlist* existe precisamente para que um
      // campo novo não entre por conveniência.
      this.#log?.warn({ outcome: "template_bloqueado", tenant_id: tenantId });
    }
    return linhas.rows.length > 0;
  }

  /** Os estados de que se pode sair para `destino`, para o predicado da base. */
  #deOndeSePodeSair(destino: Estado): string[] {
    const estados: Estado[] = [
      "queued",
      "sent",
      "delivered",
      "read",
      "failed",
      "suppressed_by_human",
    ];
    return estados.filter((de) => !terminal(de) && avancar(de, destino).avancou);
  }

  async #janela(pedido: Pedido): Promise<Janela> {
    const linhas = await this.#bd.query<{ window_expires_at: Date | null }>(SQL_JANELA, [
      pedido.tenantId,
      pedido.conversationId,
    ]);
    const primeira = linhas.rows[0];
    return { expiraEm: primeira?.window_expires_at ?? null };
  }

  async #template(tenantId: string, nome: string, idioma: string): Promise<Template | null> {
    const linhas = await this.#bd.query<{
      name: string;
      lang: string;
      category: string;
      status: string;
      quality: string | null;
      bloqueado_em: Date | null;
    }>(SQL_TEMPLATE, [tenantId, nome, idioma === "" ? IDIOMA_BASE : idioma]);
    const linha = linhas.rows[0];
    if (linha === undefined) return null;
    return {
      name: linha.name,
      lang: linha.lang,
      category: linha.category as Template["category"],
      status: linha.status as Template["status"],
      quality: linha.quality as Template["quality"],
      bloqueadoEm: linha.bloqueado_em,
    };
  }

  async #enfileirar(
    pedido: Pedido,
    kind: Categoria,
    templateName: string | null,
  ): Promise<string | null> {
    const linhas = await this.#bd.query<{ id: string }>(SQL_ENFILEIRAR, [
      pedido.tenantId,
      pedido.channelId,
      pedido.contactId,
      pedido.conversationId,
      pedido.idempotencyKey,
      kind,
      templateName,
    ]);
    return linhas.rows[0]?.id ?? null;
  }

  async #porChave(
    tenantId: string,
    chave: string,
  ): Promise<{ id: string; wamid: string | null; kind: string } | null> {
    const linhas = await this.#bd.query<{ id: string; wamid: string | null; kind: string }>(
      SQL_POR_CHAVE,
      [tenantId, chave],
    );
    return linhas.rows[0] ?? null;
  }

  async #porWamid(
    tenantId: string,
    wamid: string,
  ): Promise<{ id: string; state: Estado; kind: string } | null> {
    const linhas = await this.#bd.query<{ id: string; state: string; kind: string }>(
      SQL_POR_WAMID,
      [tenantId, wamid],
    );
    const linha = linhas.rows[0];
    return linha === undefined
      ? null
      : { id: linha.id, state: linha.state as Estado, kind: linha.kind };
  }

  async #falhar(tenantId: string, id: string, codigo: number | null): Promise<void> {
    await this.#bd.query(SQL_MARCAR_FALHADA, [tenantId, id, codigo]);
  }

  #recusar(pedido: Pedido, motivo: MotivoDeRecusa): Resultado {
    this.#metricas.contar(METRICA_JANELA_FECHADA, motivo);
    // **O motivo vai no `outcome` e não num campo próprio**, porque a
    // *allowlist* do `logger/politica.ts` não tem `motivo` — e está certa em
    // não ter: o motivo **é** o desfecho, e dois campos para a mesma coisa
    // divergiam. Nunca o telefone, nunca o `contact_id`, nunca o `wamid` em
    // claro: é o DoD «Privacidade» e o X-11 do gate 6.
    this.#log?.info({
      outcome: motivo === WINDOW_CLOSED ? "janela_fechada" : `recusado_${motivo.toLowerCase()}`,
      tenant_id: pedido.tenantId,
    });
    return { ok: false, motivo, codigo: null };
  }
}

/** O tecto do *free tier*, reexportado para quem liga a porta. */
export { FREE_TIER_DE_SERVICE, METRICA_CUSTO, categoriaDe };
