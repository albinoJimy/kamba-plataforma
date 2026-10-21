/**
 * O pipeline de recepção de mídia (KAM-020).
 *
 * ## A ordem dos passos, e porque é esta
 *
 * ```text
 * 1. traduz o `wa_type` em classe          — sem classe, nada do resto faz sentido
 * 2. RESERVA a linha em `pendente`         — e é aqui que a idempotência acontece
 * 3. resolve o `media_id` num URL          — a Meta, primeira de duas chamadas
 * 4. descarrega os bytes                   — a Meta, e é a que pode falhar
 * 5. corre a *allowlist* no tipo REAL      — e não no anunciado
 * 6. `put` no armazenamento                — o objecto, com a chave do tenant
 * 7. marca `armazenado` com o que se soube — content_type, size, sha256, ref
 * ```
 *
 * **O passo 2 vem antes de falar com a Meta, e é a decisão central deste
 * módulo.** Os três valores da chave (`tenant_id`, `wamid`, `media_id`) vêm
 * todos da mensagem, pelo que a linha se pode escrever sem gastar uma chamada:
 * o segundo chamador perde o `ON CONFLICT` e **devolve o que está** sem
 * descarregar nada. É o contrário do `ensureAccount` do HND, que precisava de
 * identificadores que só a criação no provedor devolve — e que por isso deixa
 * recurso órfão numa corrida. Aqui o pior que sobra é uma linha em `pendente`,
 * que é nossa e que o KAM-071 vê.
 *
 * **O passo 5 corre no tipo da resposta e não no anunciado**, e isso é o
 * critério 4 a ser levado a sério: um `image/png` que o webhook anuncia e que
 * chega como outra coisa é exactamente o caso que a *allowlist* existe para
 * apanhar. O anúncio serve só para recusar cedo e poupar a descarga.
 *
 * **O passo 6 vem antes do 7**, e a ordem importa pela mesma razão que a nota
 * privada do HND vinha depois da conversa: se o `put` falhar, não há
 * `storage_ref` e a linha fica em `pendente` — recuperável. Se fosse ao
 * contrário, a linha dizia `armazenado` e apontava para um objecto que não
 * existe, e o consumidor pedia `signUrl` de nada. A `media_assets_armazenado_ck`
 * da revisão impede essa linha de existir, mas a ordem é o que impede a
 * tentativa.
 *
 * ## O que este módulo não importa, e é por construção
 *
 * **Nada de `pay/` nem de `com/`** (critério 8): «uma imagem pode ser um
 * comprovativo de pagamento e **nunca é prova**» (ADR-013). O teste de
 * arquitectura afirma-o, e a forma de o cumprir não é disciplina — é não haver
 * a importação.
 *
 * ## O URL da Meta
 *
 * Vive numa variável local e morre com a chamada. **Não entra na base** (não há
 * coluna), **não entra no registo** (a lista branca do *logger* tem nove campos
 * e nenhum é um URL) e **não entra em excepção**: as mensagens de erro levam o
 * caminho e não a URL, pela mesma regra que o cliente do Chatwoot segue — uma
 * base mal configurada pode ter credenciais na URL.
 */

import { Logger } from "../logger/index.ts";
import { novaChave, TTL_MAXIMO_S } from "../storage/index.ts";
import {
  LIMITES_POR_OMISSAO,
  RESPOSTAS,
  classeDe,
  recusar,
  type LimiteDaClasse,
} from "./classes.ts";
import {
  MidiaIndisponivelError,
  type AvisarAgr,
  type Classe,
  type ClienteDeMidia,
  type ClienteSql,
  type Ctx,
  type LinhaDeMidia,
  type OnTranscribed,
  type PedidoDeMidia,
  type ResultadoDeMidia,
  type StorageProvider,
} from "./contrato.ts";
import {
  METRICA_BYTES,
  METRICA_DESCARGA_MS,
  METRICA_REJEICOES,
  MetricasDoMed,
} from "./metricas.ts";
import {
  SQL_MARCAR_ARMAZENADO,
  SQL_MARCAR_DESFECHO,
  SQL_POR_ASSET,
  SQL_POR_ORIGEM,
  SQL_RESERVAR,
} from "./consultas.ts";

/**
 * Quantas vezes se tenta a descarga.
 *
 * **Três tentativas, não três repetições**, e a diferença é de uma chamada. O
 * critério 6 diz «3 tentativas com *backoff*; depois `estado='falhou'`», e
 * lê-se à letra: três idas à Meta e não quatro. Não se repete a releitura que o
 * critério 6 do KAM-015 obrigou — lá o texto contradizia-se na própria
 * aritmética («três `130429` e um `200` em três chamadas»), e aqui não há
 * contradição que force outra leitura.
 */
export const TENTATIVAS = 3;

/**
 * A espera entre tentativas, em ms, e o factor de crescimento.
 *
 * **Proposta**, e calibra onde tudo o mais deste ticket calibra: a API de mídia
 * da Meta não tem evidência nenhuma no `E1`, nem códigos de erro nem limites de
 * ritmo. O que a escolha protege é a janela de 24 h — um *backoff* que somasse
 * minutos fazia o cliente esperar por uma resposta a um áudio que ninguém tinha
 * ouvido, e o critério 6 manda avisar o AGR precisamente para que ele peça o
 * reenvio em vez de o cliente ficar à espera.
 */
export const ESPERA_INICIAL_MS = 250;
export const FACTOR_DE_ESPERA = 3;

/**
 * Quanto tempo um objecto de áudio fica, em ms.
 *
 * Vinte e quatro horas, e **conta da criação** (critério 7). É a única leitura
 * auto-consistente: o `docs/tecnica/08` §7.5 diz «apagar o blob após sucesso
 * (alvo ≤ 24 h; limite de erro 72 h)», e contar da transcrição faz o prazo
 * **nunca chegar** quando a transcrição nunca tem sucesso — que é precisamente
 * o caso em que o áudio não devia ficar.
 */
export const RETENCAO_DE_AUDIO_MS = 24 * 60 * 60 * 1000;

/** O TTL de um URL interno. O máximo que a porta do KAM-011 permite. */
export const TTL_DA_URL_INTERNA_S = TTL_MAXIMO_S;

/** O prefixo da referência interna que os consumidores guardam. */
export const PREFIXO_INTERNO = "media://";

export interface Dependencias {
  readonly bd: ClienteSql;
  readonly armazenamento: StorageProvider;
  readonly midia: ClienteDeMidia;
  /** O sinal ao AGR quando a descarga falha de vez. */
  readonly avisarAgr: AvisarAgr;
  /** O gancho que agenda a eliminação do blob depois da transcrição. */
  readonly onTranscribed?: OnTranscribed;
  readonly limites?: Readonly<Record<Classe, LimiteDaClasse>>;
  readonly log?: Logger;
  readonly metricas?: MetricasDoMed;
  /** O relógio. Porta para que um teste não espere tempo real. */
  readonly agora?: () => Date;
  /** A espera entre tentativas. Porta pela mesma razão. */
  readonly dormir?: (ms: number) => Promise<void>;
}

/** O MED: recebe mídia e emite URL interna. */
export class Med {
  readonly #bd: ClienteSql;
  readonly #armazenamento: StorageProvider;
  readonly #midia: ClienteDeMidia;
  readonly #avisarAgr: AvisarAgr;
  readonly #onTranscribed: OnTranscribed | undefined;
  readonly #limites: Readonly<Record<Classe, LimiteDaClasse>>;
  readonly #log: Logger | undefined;
  readonly #metricas: MetricasDoMed;
  readonly #agora: () => Date;
  readonly #dormir: (ms: number) => Promise<void>;

  constructor(dependencias: Dependencias) {
    this.#bd = dependencias.bd;
    this.#armazenamento = dependencias.armazenamento;
    this.#midia = dependencias.midia;
    this.#avisarAgr = dependencias.avisarAgr;
    this.#onTranscribed = dependencias.onTranscribed;
    this.#limites = dependencias.limites ?? LIMITES_POR_OMISSAO;
    this.#log = dependencias.log;
    this.#metricas = dependencias.metricas ?? new MetricasDoMed();
    this.#agora = dependencias.agora ?? (() => new Date());
    this.#dormir =
      dependencias.dormir ??
      ((ms) => new Promise<void>((resolver) => setTimeout(resolver, ms)));
  }

  get metricas(): MetricasDoMed {
    return this.#metricas;
  }

  /**
   * Recebe um objecto de mídia: descarrega, valida, armazena e registra.
   *
   * Ver a nota do módulo para a ordem dos sete passos e para a razão de cada
   * uma.
   */
  async receber(pedido: PedidoDeMidia): Promise<ResultadoDeMidia> {
    const ctx: Ctx = { tenantId: pedido.tenantId };
    const classe = classeDe(pedido.waType);
    if (classe === null) {
      // **Não se reserva linha para o que não é mídia.** Uma linha com classe
      // inventada não passava o `media_assets_classe_ck`, e uma tabela de mídia
      // com entradas de `location` ou de `text` dizia uma coisa falsa sobre o
      // que ela guarda.
      this.#metricas.contar(METRICA_REJEICOES, "classe_desconhecida");
      this.#log?.warn({
        outcome: "media_classe_desconhecida",
        tenant_id: pedido.tenantId,
        wa_type: pedido.waType,
      });
      return {
        estado: "rejeitado",
        assetId: "",
        motivo: "classe_desconhecida",
        resposta: RESPOSTAS.classe_desconhecida,
      };
    }

    // **Passo 2: a reserva, e é aqui que a idempotência acontece.**
    const reserva = await this.#bd.query<{ asset_id: string }>(SQL_RESERVAR, [
      pedido.tenantId,
      pedido.contactId,
      pedido.conversationId,
      pedido.wamid,
      pedido.mediaId,
      classe,
    ]);
    const linha = reserva.rows[0];
    if (linha === undefined) {
      // Já existia: **sem chamada à Meta e sem `put`**. Devolve o que está.
      return this.#comoEsta(pedido, classe);
    }
    const assetId = linha.asset_id;

    // O que o webhook **anuncia** serve só para recusar cedo e poupar a
    // descarga. O que vale é o tipo da resposta — ver o passo 5.
    if (pedido.contentTypeAnunciado !== undefined) {
      const cedo = recusar(classe, pedido.contentTypeAnunciado, 0, this.#limites);
      if (cedo === "tipo_nao_permitido") {
        return await this.#rejeitar(pedido, assetId, cedo);
      }
    }

    let bytes: Uint8Array;
    let contentType: string;
    try {
      const descarregada = await this.#descarregarComTentativas(pedido);
      bytes = descarregada.bytes;
      contentType = descarregada.contentType;
    } catch (erro) {
      if (!(erro instanceof MidiaIndisponivelError)) throw erro;
      return await this.#falhar(pedido, assetId, classe);
    }

    // **Passo 5: a *allowlist* no tipo REAL e no tamanho REAL.**
    const motivo = recusar(classe, contentType, bytes.byteLength, this.#limites);
    if (motivo !== null) {
      // O `recusar` devolve tres motivos e aqui so dois podem chegar: a
      // `classe_desconhecida` ja saiu no primeiro passo, antes de haver linha.
      // A asserçao e explicita em vez de um `as`: se o `recusar` ganhar um
      // quarto motivo, isto **nao** compila, que e o que se quer.
      if (motivo === "classe_desconhecida") {
        throw new Error(
          "a classe desconhecida nao pode chegar aqui: ela sai no primeiro " +
            "passo, antes de a linha existir",
        );
      }
      return await this.#rejeitar(pedido, assetId, motivo);
    }

    // **Passo 6: o `put`.** A chave vem do `novaChave` da porta e leva o
    // *tenant* no primeiro segmento, que é o que torna o prefixo por tenant uma
    // propriedade do armazenamento e não do nosso código.
    const agora = this.#agora();
    const chave = novaChave(ctx, classe, agora);
    const retainUntil =
      classe === "media_audio"
        ? new Date(agora.getTime() + RETENCAO_DE_AUDIO_MS)
        : null;
    const ref = await this.#armazenamento.put(ctx, chave, bytes, {
      contentType,
      classe,
      // A porta exige o `retainUntil`. Para as classes sem prazo curto passa-se
      // uma data distante: a política de retenção por classe é do KAM-071, e
      // inventar aqui um prazo para fotos de catálogo — que «vivem enquanto o
      // catálogo viver», diz o bloco — era apagá-las sem ninguém decidir.
      retainUntil: retainUntil ?? new Date(agora.getTime() + 100 * 365 * 24 * 3600 * 1000),
    });

    // **Passo 7.** O `sha256` vem do `put` e não se recalcula: o que importa é
    // o resumo do que **ficou** armazenado.
    const marcada = await this.#bd.query<{ asset_id: string }>(SQL_MARCAR_ARMAZENADO, [
      pedido.tenantId,
      assetId,
      contentType,
      ref.tamanho,
      ref.sha256,
      ref.key,
      retainUntil,
    ]);
    if (marcada.rows.length === 0) {
      // Outro tratou a linha entre a reserva e aqui. **Não se apaga o objecto**:
      // ele está lá e o resumo di-lo; o que se faz é devolver o que está, e
      // deixar rasto para que o objecto a mais apareça antes de alguém o
      // descobrir na factura.
      this.#log?.warn({
        outcome: "media_marcacao_sem_efeito",
        tenant_id: pedido.tenantId,
      });
      return this.#comoEsta(pedido, classe);
    }

    this.#metricas.contar(METRICA_BYTES, classe, ref.tamanho);
    this.#log?.info({ outcome: "media_armazenada", tenant_id: pedido.tenantId });
    return {
      estado: "armazenado",
      assetId,
      referencia: `${PREFIXO_INTERNO}${assetId}`,
      repetido: false,
    };
  }

  /**
   * Um URL interno assinado para um `asset_id` (critério 5).
   *
   * **O `ctx` é o que decide, e é o que faz o X-08.** A chave do objecto leva o
   * *tenant* no primeiro segmento e a porta do KAM-011 recusa assinar uma chave
   * fora do *tenant* do `ctx` (`ChaveForaDoTenantError`) — pelo que um pedido
   * com o contexto de outra PME não passa, e não passa por verificação nossa:
   * passa pela porta, que tem bateria de contrato própria.
   *
   * O TTL é o `TTL_MAXIMO_S` da porta, que é 300 s — o mesmo número que o
   * critério 5 pede («≤ 300 s») e que o `docs/tecnica/08` §3.8 fixa («TTL ≤ 5
   * min»). **Não se escreve 300 aqui**: lê-se de lá, para que mudar o limite
   * seja um sítio e não dois.
   */
  async urlInterna(tenantId: string, assetId: string): Promise<string | null> {
    const ctx: Ctx = { tenantId };
    const linhas = await this.#bd.query<LinhaDeMidia>(SQL_POR_ASSET, [tenantId, assetId]);
    const linha = linhas.rows[0];
    if (linha === undefined || linha.storage_ref === null) return null;
    return await this.#armazenamento.signUrl(
      ctx,
      { key: linha.storage_ref, tamanho: 0, sha256: linha.sha256 },
      { ttlSeconds: TTL_DA_URL_INTERNA_S },
    );
  }

  /**
   * Avisa que um objecto foi transcrito, e agenda a eliminação do blob.
   *
   * O MED **agenda** e não apaga: a purga é KAM-071. O que este método promete é
   * que o gancho corre com a chave certa — sem ela, quem purga não sabe o que
   * apagar.
   */
  async transcrito(tenantId: string, assetId: string): Promise<void> {
    if (this.#onTranscribed === undefined) return;
    const linhas = await this.#bd.query<LinhaDeMidia>(SQL_POR_ASSET, [tenantId, assetId]);
    const linha = linhas.rows[0];
    if (linha === undefined || linha.storage_ref === null) return;
    await this.#onTranscribed({ assetId, tenantId, storageRef: linha.storage_ref });
  }

  /**
   * As três tentativas, com *backoff*.
   *
   * **Só a `MidiaIndisponivelError` se repete.** Uma `MidiaInesperadaError` é um
   * pedido nosso errado e repeti-la nunca melhora — é a mesma distinção que o
   * cliente do Chatwoot faz, e vale pela mesma razão: uma fila que repetisse um
   * 4xx nunca drenava.
   */
  async #descarregarComTentativas(
    pedido: PedidoDeMidia,
  ): Promise<{ bytes: Uint8Array; contentType: string }> {
    let espera = ESPERA_INICIAL_MS;
    let ultima: unknown;
    for (let tentativa = 1; tentativa <= TENTATIVAS; tentativa += 1) {
      const comeco = this.#agora().getTime();
      try {
        const resolvida = await this.#midia.resolver(pedido.tenantId, pedido.mediaId);
        const descarregada = await this.#midia.descarregar(pedido.tenantId, resolvida);
        this.#metricas.medir(METRICA_DESCARGA_MS, this.#agora().getTime() - comeco);
        return descarregada;
      } catch (erro) {
        if (!(erro instanceof MidiaIndisponivelError)) throw erro;
        ultima = erro;
        // **A medição faz-se mesmo quando falha**, e é de propósito: uma
        // descarga que demora e falha é o sinal mais útil que esta métrica dá,
        // e medir só os sucessos fazia um painel verde num dia em que nada
        // chegou.
        this.#metricas.medir(METRICA_DESCARGA_MS, this.#agora().getTime() - comeco);
        if (tentativa < TENTATIVAS) {
          await this.#dormir(espera);
          espera *= FACTOR_DE_ESPERA;
        }
      }
    }
    throw ultima instanceof Error
      ? ultima
      : new MidiaIndisponivelError("sem causa registada");
  }

  /** O que está na base, para quando a reserva perdeu o conflito. */
  async #comoEsta(pedido: PedidoDeMidia, classe: Classe): Promise<ResultadoDeMidia> {
    const linhas = await this.#bd.query<LinhaDeMidia>(SQL_POR_ORIGEM, [
      pedido.tenantId,
      pedido.wamid,
      pedido.mediaId,
    ]);
    const linha = linhas.rows[0];
    if (linha === undefined) {
      // A reserva perdeu o conflito e a leitura seguinte não encontra nada: a
      // `media_assets_origem_uq` conflituou com uma linha que a RLS não deixa
      // ver, o que significa contexto de *tenant* errado. É a mesma asserção
      // que o `ensureAccount` do HND faz, e pela mesma razão: silenciar isto
      // fazia um furo de contexto parecer uma mídia perdida.
      throw new Error(
        "a reserva de midia nao devolveu linha e a leitura seguinte tambem " +
          "nao: a chave (tenant_id, wamid, media_id) conflituou com uma linha " +
          "que a RLS nao deixa ver, o que significa contexto de tenant errado",
      );
    }
    if (linha.estado === "armazenado") {
      return {
        estado: "armazenado",
        assetId: linha.asset_id,
        referencia: `${PREFIXO_INTERNO}${linha.asset_id}`,
        repetido: true,
      };
    }
    if (linha.estado === "rejeitado") {
      // **Não se sabe qual foi o motivo**, e a base não o guarda: a coluna
      // `estado` tem quatro valores e nenhum deles é o motivo. Devolve-se a
      // resposta genérica, e a razão de não haver coluna de motivo é a mesma
      // que o `handoffs.motivo` tem de haver — lá o motivo é texto de uma
      // pessoa, aqui é uma de três etiquetas que a métrica já conta.
      return {
        estado: "rejeitado",
        assetId: linha.asset_id,
        motivo: "tipo_nao_permitido",
        resposta: RESPOSTAS.tipo_nao_permitido,
      };
    }
    if (linha.estado === "falhou") {
      return { estado: "falhou", assetId: linha.asset_id, tentativas: TENTATIVAS };
    }
    // `pendente`: outro está a tratar, ou ficou a meio. Não se refaz o trabalho
    // dele — devolver `falhou` era mentir, e repetir a descarga era o que a
    // reserva existe para evitar.
    void classe;
    return { estado: "falhou", assetId: linha.asset_id, tentativas: 0 };
  }

  async #rejeitar(
    pedido: PedidoDeMidia,
    assetId: string,
    motivo: "tipo_nao_permitido" | "tamanho_excedido",
  ): Promise<ResultadoDeMidia> {
    await this.#bd.query(SQL_MARCAR_DESFECHO, [pedido.tenantId, assetId, "rejeitado"]);
    this.#metricas.contar(METRICA_REJEICOES, motivo);
    // **Sem o tipo nem o tamanho no registo**: a lista branca do *logger* não
    // os tem, e o que o painel precisa de saber está na métrica.
    this.#log?.warn({
      outcome: `media_rejeitada_${motivo}`,
      tenant_id: pedido.tenantId,
    });
    return { estado: "rejeitado", assetId, motivo, resposta: RESPOSTAS[motivo] };
  }

  async #falhar(
    pedido: PedidoDeMidia,
    assetId: string,
    classe: Classe,
  ): Promise<ResultadoDeMidia> {
    await this.#bd.query(SQL_MARCAR_DESFECHO, [pedido.tenantId, assetId, "falhou"]);
    // **O sinal ao AGR é o critério 6**, e vem depois de a linha ficar
    // `falhou`: se o aviso falhar, o estado está gravado e alguém o vê; ao
    // contrário, o AGR pedia o reenvio de algo que a nossa base ainda dizia
    // estar a caminho.
    await this.#avisarAgr({
      tenantId: pedido.tenantId,
      conversationId: pedido.conversationId,
      wamid: pedido.wamid,
      classe,
    });
    this.#log?.warn({
      outcome: "media_descarga_falhou",
      tenant_id: pedido.tenantId,
    });
    return { estado: "falhou", assetId, tentativas: TENTATIVAS };
  }
}
