/**
 * Publicador de instância única (KAM-005, `docs/tecnica/06` §6.2).
 *
 * Lê o outbox, entrega às filas dos consumidores, arquiva no `events_log` e
 * marca a linha como publicada — nessa ordem, dentro de uma transacção:
 *
 *     BEGIN
 *       linhas = SELECT ... FOR UPDATE SKIP LOCKED
 *       para cada linha, para cada subscrição com finalidade ∈ finalidades:
 *           fila[consumer][particao].add(jobId = event_id)
 *       INSERT events_log ... ON CONFLICT DO NOTHING
 *       UPDATE publicado_at
 *     COMMIT
 *
 * ## A ordem é a garantia, e é esta e não outra
 *
 * O `add` vem **antes** do `COMMIT`. Uma falha pelo meio — *kill -9*, rede,
 * Redis — deixa a linha sem `publicado_at`, e o ciclo seguinte republica-a. É
 * *at-least-once* por construção: o evento pode ir à fila duas vezes, nunca
 * zero. Os duplicados morrem em dois sítios, e os dois são precisos:
 *
 * * `jobId = event_id` no `add` — o BullMQ ignora um *job* com um `jobId` que
 *   já tem. **As garantias do BullMQ estão NÃO VERIFICADO** (`evidencia/E4`
 *   §2.10): a documentação diz que um `jobId` repetido não cria um segundo
 *   *job*, mas isso é afirmação do fornecedor e não medição nossa, e um *job*
 *   já consumido já não está na fila para deduplicar;
 * * a idempotência do consumidor por `(consumer, event_id)` — que é o KAM-006,
 *   e é a que não depende de nada do BullMQ.
 *
 * A ordem inversa (`COMMIT` e depois `add`) perdia eventos: um *kill -9* depois
 * do `COMMIT` deixava a linha publicada e o *job* por criar. É o modo de falha
 * que o outbox existe para não ter.
 *
 * ## Um líder, e as réplicas em espera
 *
 * `pg_try_advisory_lock(7101)` de sessão. Quem o consegue publica; quem não o
 * consegue tenta outra vez no ciclo seguinte. O lock larga-se quando a ligação
 * termina — incluindo quando o processo morre sem avisar — e por isso a réplica
 * assume sem ninguém intervir. O tempo até assumir é, no pior caso, o intervalo
 * do ciclo mais o que o PostgreSQL leva a reparar que a ligação caiu — e um
 * `kill -9` do processo fecha a ligação, pelo que o servidor larga o *lock* sem
 * esperar `tcp_keepalives`. O gate mede **≤ 10 s**, que é o que o critério 5
 * pede; não se afirma aqui que fica «muito abaixo», porque esse número não é
 * medido em sítio nenhum (ANALISE-20, achado 14).
 *
 * ## O que este módulo não faz
 *
 * Não repõe o que o Redis perder — isso é o reconciliador do §6.5, no KAM-006.
 * Não consome nada, não tem DLQ, não cria partições do `events_log`
 * (`db/eventos_particoes.py`). E não registra conteúdo: o *logger* leva códigos
 * e contagens, nunca o envelope (`docs/logs.md`).
 */

import type { Logger } from "../logger/index.ts";

import {
  CANAL_DE_AVISO,
  LOCK_DO_PUBLICADOR,
  SQL_ARQUIVAR,
  SQL_ATRASO,
  SQL_ELEGER,
  SQL_ESCUTAR,
  SQL_LARGAR,
  SQL_MARCAR_PUBLICADO,
  SQL_PENDENTES,
  SQL_RECUAR,
  SQL_SUBSCRICOES,
} from "./consultas.ts";
import { CONVERSORES, type RegistoDeConversores, SemConversorError } from "./conversor.ts";
import { type Envelope, EnvelopeInvalidoError, lerEnvelope } from "./envelope.ts";
import { type Filas, REPETICAO, type Trabalho } from "./filas.ts";
import {
  METRICAS,
  METRICA_ATRASO,
  METRICA_ERROS,
  METRICA_LIDER,
  METRICA_PUBLICADOS,
  type Metricas,
  type Motivo,
} from "./metricas.ts";
import { DestinoInvalidoError, nomeDaFila } from "./particao.ts";
import { PadraoDeTelefoneError, exigirSemTelefone } from "./pii.ts";

/** O mínimo de um cliente SQL. É a forma do `pg.Client`. */
export interface ClienteSql {
  query(
    sql: string,
    parametros?: readonly unknown[],
  ): Promise<{ rows: Record<string, unknown>[]; rowCount: number | null }>;
}

/** Uma linha do outbox por publicar. */
export interface LinhaDoOutbox {
  readonly id: string;
  readonly event_id: string;
  readonly tipo: string;
  readonly versao: number;
  readonly tenant_id: string;
  readonly agregado_tipo: string;
  readonly agregado_id: string;
  readonly particao: number;
  readonly envelope: unknown;
  readonly tentativas: number;
}

/** Uma subscrição activa. */
export interface Subscricao {
  readonly consumer: string;
  readonly tipo: string;
  readonly versao_max: number;
  readonly finalidade: string;
  readonly exige_ordem: boolean;
}

/** O que um ciclo fez. */
export interface ResultadoDoCiclo {
  /** Linhas lidas do outbox. */
  readonly lidas: number;
  /** Linhas marcadas como publicadas. */
  readonly publicadas: number;
  /** *Jobs* entregues (uma linha pode dar vários, um por consumidor). */
  readonly jobs: number;
  /** Linhas que recuaram por uma falha do **lote** (fila ou base em baixo). */
  readonly recuadas: number;
  /**
   * Linhas postas de lado por uma falha **da linha** (envelope ilegível,
   * telefone, partição inválida, versão sem conversor) ou por vir depois de
   * uma dessas no mesmo agregado. O resto do lote seguiu.
   */
  readonly bloqueadas: number;
}

/** Uma entrega a fazer: a fila e o *job*. Calculada antes de qualquer `add`. */
interface Entrega {
  readonly fila: string;
  readonly trabalho: Trabalho;
}

/** Uma linha pronta a publicar, com as suas entregas já calculadas. */
interface Preparada {
  readonly linha: LinhaDoOutbox;
  readonly entregas: Entrega[];
}

/**
 * A chave do agregado, para o corte da fase 1.
 *
 * Leva o `tenant_id`: o `agregado_id` só é único **dentro** do tenant (é o que
 * a chave primária de `evt_agregado_seq` e a unicidade do triplo de
 * `events_outbox` dizem, desde o desvio registado na revisão `0004`). Sem o
 * tenant, uma linha má de A bloqueava o agregado homónimo de B.
 */
function chaveDoAgregado(linha: LinhaDoOutbox): string {
  return `${linha.tenant_id}\u0000${linha.agregado_tipo}\u0000${linha.agregado_id}`;
}

/**
 * O recuo do **outbox**: 1 s, 2 s, 5 s, 15 s, 30 s, e daí para a frente 30 s.
 *
 * Não é a escada do `docs/tecnica/06` §6.4, e isso é deliberado. A escada do
 * §6.4 — 1 s, 5 s, 30 s, 2 min, 10 min, seis tentativas — é a **política da
 * DLQ**: o recuo do *job* no consumidor, e é essa que vai no `add` como
 * `attempts: 6, backoff exponencial 1 s` (`filas.ts`). O recuo do outbox, que
 * o §6.2 só nomeia («`proxima_tentativa_at = now() + backoff(tentativas)`»),
 * é outro problema e tem outro limite.
 *
 * O limite é o critério 4: «Redis parado 60 s com 1 000 eventos emitidos: após
 * o regresso, 100% publicados em ≤ 60 s». Com a escada do §6.4, 60 s de fila
 * em baixo levam o publicador à quarta ou quinta tentativa, e o próximo
 * `proxima_tentativa_at` cai a 2 ou a 10 minutos de distância — isto é, o
 * critério 4 **não se cumpre** com a escada do §6.4, e a contradição entre as
 * duas linhas do documento é um achado deste ticket (ver `docs/eventos.md` §5).
 * Com o tecto em 30 s, o pior caso depois de a fila voltar é 30 s < 60 s, com
 * folga para o `COMMIT` dos lotes.
 *
 * Os valores são **proposta**, calibrada contra o critério 4 e por confirmar
 * com dados de operação: o que se calibra é o tecto, e o sítio onde se mede é
 * `evt_outbox_lag_seconds`.
 */
export const ESCADA_DE_RECUO = [1_000, 2_000, 5_000, 15_000, 30_000] as const;

export function atrasoDaTentativa(tentativas: number): number {
  const indice = Math.min(Math.max(tentativas, 0), ESCADA_DE_RECUO.length - 1);
  return ESCADA_DE_RECUO[indice] as number;
}

/**
 * Os consumidores que recebem este envelope.
 *
 * Duas condições, e as duas vêm do canon:
 *
 * * `subscricao.tipo === envelope.tipo` — o §6.1 dá a `evt_subscricoes` a chave
 *   `(consumer, tipo)`;
 * * `subscricao.finalidade ∈ envelope.finalidades` — o **roteamento por
 *   finalidade** do §7.3. Um consumidor de `marketing` não recebe um evento
 *   emitido só para `transacao`, mesmo que subscreva o tipo. É a limitação de
 *   finalidade escrita em código, e não um filtro no consumidor: um filtro no
 *   consumidor já tinha o dado na mão.
 *
 * Função pura. É aqui que o critério 7 se prova sem base de dados.
 */
export function destinos(
  envelope: Envelope,
  subscricoes: readonly Subscricao[],
): Subscricao[] {
  const finalidades = new Set(envelope.finalidades);
  return subscricoes.filter(
    (s) => s.tipo === envelope.tipo && finalidades.has(s.finalidade),
  );
}

/** Classifica um erro num dos motivos fechados de `metricas.ts`. */
export function motivoDoErro(erro: unknown): Motivo {
  if (erro instanceof SemConversorError) return "sem_conversor";
  if (erro instanceof EnvelopeInvalidoError) return "envelope_invalido";
  if (erro instanceof PadraoDeTelefoneError) return "padrao_de_telefone";
  if (erro instanceof DestinoInvalidoError) return "destino_invalido";
  return "fila_indisponivel";
}

export interface OpcoesDoPublicador {
  /** **Uma ligação**, não um *pool*: o lock consultivo é de sessão. */
  readonly bd: ClienteSql;
  readonly filas: Filas;
  readonly metricas?: Metricas;
  readonly log?: Logger;
  /**
   * Linhas por ciclo. 200 é o valor do `docs/tecnica/06` §6.2.
   *
   * **É este número que domina o atraso do critério 8, e isso foi medido.** A
   * 50 eventos/s, um lote de 200 enche-se a cada 4 s; quando o publicador corre
   * à capacidade, o atraso de um evento é o período do lote, e o p95 medido foi
   * **6,0 s** contra o 1 s *proposto* do critério — com o publicador a publicar
   * tudo, sem perder nada e sem recuos. Baixar o lote baixa o atraso e aumenta
   * o número de transacções; é o parâmetro a calibrar, e a calibração não se
   * faz num portátil com três contentores (`docs/eventos.md` §6).
   */
  readonly lote?: number;
  /** Intervalo do laço quando o outbox está vazio, em ms. 200 é o do §6.2. */
  readonly intervalo?: number;
  readonly conversores?: RegistoDeConversores;
}

/** O publicador pediu para publicar sem ser líder. */
export class SemLiderancaError extends Error {
  constructor() {
    super(
      "este processo nao tem o lock consultivo do publicador: so o lider " +
        "publica (docs/tecnica/06 §6.2)",
    );
    this.name = "SemLiderancaError";
  }
}

export class Publicador {
  readonly #bd: ClienteSql;
  readonly #filas: Filas;
  readonly #metricas: Metricas;
  readonly #log: Logger | undefined;
  readonly #lote: number;
  readonly #intervalo: number;
  readonly #conversores: RegistoDeConversores;
  #lider = false;

  constructor(opcoes: OpcoesDoPublicador) {
    this.#bd = opcoes.bd;
    this.#filas = opcoes.filas;
    this.#metricas = opcoes.metricas ?? METRICAS;
    this.#log = opcoes.log;
    this.#lote = opcoes.lote ?? 200;
    this.#intervalo = opcoes.intervalo ?? 200;
    this.#conversores = opcoes.conversores ?? CONVERSORES;
  }

  get lider(): boolean {
    return this.#lider;
  }

  /** Tenta ficar líder. Idempotente: já líder devolve `true` sem pedir nada. */
  async eleger(): Promise<boolean> {
    if (this.#lider) return true;
    const { rows } = await this.#bd.query(SQL_ELEGER, [LOCK_DO_PUBLICADOR]);
    this.#lider = rows[0]?.lider === true;
    this.#metricas.medir(METRICA_LIDER, this.#lider ? 1 : 0);
    if (this.#lider) await this.#bd.query(SQL_ESCUTAR);
    return this.#lider;
  }

  /**
   * Larga a liderança. No encerramento limpo; um *kill -9* dispensa-o.
   *
   * Engole o erro do `unlock` de propósito: se a ligação já caiu, o servidor
   * larga o *lock* sozinho, e deixar a excepção subir daqui mascarava a causa
   * verdadeira (que é a ligação).
   */
  async largar(): Promise<void> {
    if (!this.#lider) return;
    try {
      await this.#bd.query(SQL_LARGAR, [LOCK_DO_PUBLICADOR]);
    } catch {
      /* ligação perdida: o servidor larga o lock ao fechá-la */
    }
    this.#lider = false;
    this.#metricas.medir(METRICA_LIDER, 0);
  }

  /** Mede e publica o atraso do outbox. Corre a cada ciclo, mesmo sem linhas. */
  async medirAtraso(): Promise<number> {
    const { rows } = await this.#bd.query(SQL_ATRASO);
    const atraso = Number(rows[0]?.atraso ?? 0);
    this.#metricas.medir(METRICA_ATRASO, atraso);
    return atraso;
  }

  /**
   * Um ciclo: um lote, uma transacção, **duas fases**.
   *
   * ## Porque são duas fases, e não uma
   *
   * A primeira versão deste laço entregava linha a linha dentro da transacção,
   * e qualquer falha abortava o lote inteiro: `ROLLBACK`, e as 200 linhas
   * recuavam juntas. A revisão adversarial (ANALISE-20, achado 1) mostrou o que
   * isso faz com uma linha **envenenada** — um envelope ilegível, um telefone
   * no `payload`, uma `particao` fora de 0..15, uma `versao` sem conversor:
   *
   * > a linha má volta a ser a de `id` mais baixo no ciclo seguinte, volta a
   * > derrubar o lote, e as ~199 que partilham o recuo com ela **nunca** são
   * > publicadas. Não vão à fila, não entram no `events_log` — e por isso o
   * > reconciliador do §6.5, que parte do `events_log`, também não as vê.
   *
   * Perda de eventos com o outbox cheio e aparentemente saudável, sem caminho
   * de saída. Por isso:
   *
   * 1. **Fase de preparação, fora da transacção de escrita e sem efeitos:** ler
   *    e validar cada envelope, achar os destinos, converter a versão. O que
   *    falhar fica de lado, com o seu motivo. Nada foi para fila nenhuma.
   * 2. **Fase de entrega:** as linhas boas vão à fila, ao arquivo e ao
   *    `publicado_at`, na mesma transacção. As de lado recuam, em transacção
   *    própria, com o seu motivo contado.
   *
   * ## E a ordem do agregado, que era a razão da fase única
   *
   * Publicar as boas e deixar as más perde a ordem **se as duas forem do mesmo
   * agregado**: a `seq = 3` publicada enquanto a `seq = 2` fica para trás põe o
   * consumidor a ver o futuro antes do passado. O corte é por isso **por
   * agregado**: quando uma linha é posta de lado, tudo o que vem depois dela no
   * mesmo `(tenant_id, agregado_tipo, agregado_id)` espera com ela. Os outros
   * agregados seguem — e é isso que distingue «uma linha má atrasa o seu
   * agregado» de «uma linha má paralisa o outbox».
   */
  async ciclo(): Promise<ResultadoDoCiclo> {
    if (!this.#lider) throw new SemLiderancaError();

    const vazio: ResultadoDoCiclo = {
      lidas: 0,
      publicadas: 0,
      jobs: 0,
      recuadas: 0,
      bloqueadas: 0,
    };
    await this.#bd.query("BEGIN");
    let linhas: LinhaDoOutbox[] = [];
    let boas: Preparada[] = [];
    let adiadas: LinhaDoOutbox[] = [];
    try {
      const pendentes = await this.#bd.query(SQL_PENDENTES, [this.#lote]);
      linhas = pendentes.rows as unknown as LinhaDoOutbox[];
      if (linhas.length === 0) {
        await this.#bd.query("COMMIT");
        return vazio;
      }
      const subscricoes = (await this.#bd.query(SQL_SUBSCRICOES))
        .rows as unknown as Subscricao[];

      // Fase 1: preparar. Síncrona, sem efeitos, e por isso não pode deixar o
      // lote a meio.
      const preparado = this.#preparar(linhas, subscricoes);
      boas = preparado.boas;
      adiadas = preparado.adiadas;

      // Fase 2: entregar o que está bom, **agrupado por fila**.
      //
      // Um `addLote` por fila, e as filas em paralelo. Com um `add` por *job*,
      // um ciclo de 200 linhas fazia 200 idas ao Redis em série e o publicador
      // não acompanhava 50 eventos/s: o p95 do atraso mediu **9,0 s** contra o
      // 1 s do critério 8. A ordem dentro de cada fila é preservada — os
      // *jobs* vão na ordem em que foram preparados, que é a ordem de `id` e
      // portanto a de `seq` do agregado — e filas diferentes são, por desenho,
      // partições diferentes ou consumidores diferentes.
      let jobs = 0;
      const porFila = new Map<string, Trabalho[]>();
      for (const pronta of boas) {
        if (pronta.entregas.length === 0) {
          this.#metricas.contar(METRICA_PUBLICADOS, "sem_destino");
          continue;
        }
        for (const entrega of pronta.entregas) {
          const lote = porFila.get(entrega.fila);
          if (lote === undefined) porFila.set(entrega.fila, [entrega.trabalho]);
          else lote.push(entrega.trabalho);
          jobs += 1;
        }
      }
      await Promise.all(
        [...porFila].map(([fila, trabalhos]) => this.#filas.addLote(fila, trabalhos)),
      );
      this.#metricas.contar(METRICA_PUBLICADOS, "entregue", jobs);

      const ids = boas.map((p) => p.linha.id);
      if (ids.length > 0) {
        await this.#bd.query(SQL_ARQUIVAR, [ids]);
        await this.#bd.query(SQL_MARCAR_PUBLICADO, [ids]);
      }
      await this.#bd.query("COMMIT");
      const bloqueadas = await this.#recuar(adiadas);
      return {
        lidas: linhas.length,
        publicadas: ids.length,
        jobs,
        recuadas: 0,
        bloqueadas,
      };
    } catch (erro) {
      // Chegar aqui é uma falha que **não é de uma linha**: a fila em baixo, a
      // base em baixo. O lote inteiro reverte e recua junto, que é o certo —
      // a causa é a mesma para todas.
      await this.#reverter();
      const motivo = motivoDoErro(erro);
      this.#metricas.contar(METRICA_ERROS, motivo);
      // `error_code` e `outcome` sao da *allowlist* de `docs/tecnica/08` §7.3; o
      // motivo e um dos fechados de `metricas.ts`, nunca um identificador.
      this.#log?.warn({ outcome: "evt_publish_failed", error_code: motivo });
      const recuadas = await this.#recuar(linhas);
      return {
        lidas: linhas.length,
        publicadas: 0,
        jobs: 0,
        recuadas,
        bloqueadas: 0,
      };
    }
  }

  /**
   * Fase 1: separa o lote em «pode ir» e «fica para trás», sem efeitos.
   *
   * O corte é por agregado: a primeira linha que falhe arrasta consigo **tudo
   * o que vem depois dela no mesmo agregado**, porque publicar `seq = 3` com a
   * `seq = 2` para trás é perder a ordem causal. As linhas vêm por `id`
   * crescente (`SQL_PENDENTES`), que é a ordem de escrita e por isso a ordem
   * de `seq` dentro de cada agregado.
   */
  #preparar(
    linhas: readonly LinhaDoOutbox[],
    subscricoes: readonly Subscricao[],
  ): { boas: Preparada[]; adiadas: LinhaDoOutbox[] } {
    const boas: Preparada[] = [];
    const adiadas: LinhaDoOutbox[] = [];
    const agregadosBloqueados = new Set<string>();

    for (const linha of linhas) {
      const agregado = chaveDoAgregado(linha);
      if (agregadosBloqueados.has(agregado)) {
        adiadas.push(linha);
        continue;
      }
      try {
        boas.push({ linha, entregas: this.#entregas(linha, subscricoes) });
      } catch (erro) {
        const motivo = motivoDoErro(erro);
        this.#metricas.contar(METRICA_ERROS, motivo);
        this.#log?.warn({ outcome: "evt_bloqueado", error_code: motivo });
        agregadosBloqueados.add(agregado);
        adiadas.push(linha);
      }
    }
    return { boas, adiadas };
  }

  /**
   * As entregas de uma linha: (fila, *job*) por consumidor. **Não** põe nada na
   * fila — é a fase 1, e lança se a linha não se puder publicar.
   */
  #entregas(
    linha: LinhaDoOutbox,
    subscricoes: readonly Subscricao[],
  ): Entrega[] {
    const envelope = lerEnvelope(linha.envelope);
    // A guarda de PII outra vez, e não por desconfiança do `evt_emitir`: uma
    // linha pode ter entrado por um `INSERT` directo (`kamba_batch`, uma
    // migração, um *replay*), e este é o último ponto antes de o envelope sair
    // da base. Falha fechada: não se publica.
    exigirSemTelefone(envelope.payload, "payload do evento");

    // Sem destino não é erro: o evento arquiva-se e marca-se publicado. Um
    // tipo sem consumidores é o estado normal de metade do catálogo.
    return destinos(envelope, subscricoes).map((alvo) => ({
      fila: nomeDaFila(alvo.consumer, linha.particao),
      trabalho: {
        jobId: envelope.id,
        nome: envelope.tipo,
        dados: {
          envelope: this.#conversores.converter(envelope, alvo.versao_max),
          repeticao: REPETICAO,
        },
      },
    }));
  }

  /** `ROLLBACK` que não esconde o erro original se também ele falhar. */
  async #reverter(): Promise<void> {
    try {
      await this.#bd.query("ROLLBACK");
    } catch {
      // Uma ligação já perdida não aceita `ROLLBACK`, e o servidor desfaz a
      // transacção sozinho quando ela cai. Engolir aqui é o certo: o erro que
      // interessa é o de cima, e este tapava-o.
    }
  }

  /**
   * Recua as linhas do lote, em transacção própria.
   *
   * O atraso é o da escada, pela tentativa **mais alta** do lote: linhas do
   * mesmo lote recuam juntas, porque a razão da falha é a mesma (a fila).
   */
  async #recuar(linhas: readonly LinhaDoOutbox[]): Promise<number> {
    if (linhas.length === 0) return 0;
    const tentativas = Math.max(...linhas.map((l) => Number(l.tentativas)));
    try {
      const { rowCount } = await this.#bd.query(SQL_RECUAR, [
        linhas.map((l) => l.id),
        atrasoDaTentativa(tentativas),
      ]);
      return rowCount ?? 0;
    } catch {
      // A base caiu com a fila. O ciclo seguinte volta a ler as mesmas linhas
      // (nada foi marcado) e tenta outra vez; nada se perde.
      this.#metricas.contar(METRICA_ERROS, "base_indisponivel");
      return 0;
    }
  }

  /**
   * O laço. Corre até `sinal` abortar.
   *
   * Em cada volta: tenta ser líder, mede o atraso, e — se for líder — corre
   * ciclos enquanto o lote vier cheio (um lote cheio quer dizer que há mais).
   * Quem não é líder não publica e espera: é a réplica.
   *
   * O `LISTEN evt_novo` do §6.2 está pedido na eleição; acordar por `NOTIFY`
   * exige um `on("notification")` do *driver*, que é de quem monta o processo
   * (`services/worker-canal/src/publicador.ts`). O intervalo de 200 ms é o
   * limite superior do atraso, não o normal.
   */
  async correr(sinal: AbortSignal): Promise<void> {
    while (!sinal.aborted) {
      try {
        const lider = await this.eleger();
        await this.medirAtraso();
        if (lider) {
          // Enquanto houver trabalho, não se dorme: o intervalo é para quando o
          // outbox está vazio. Com a espera entre ciclos a correr sempre, o
          // atraso de um evento levava o período do lote **mais** o intervalo,
          // e o período do lote já é o que domina (ver `#lote`).
          let resultado = await this.ciclo();
          while (!sinal.aborted && resultado.lidas > 0) {
            resultado = await this.ciclo();
          }
        }
      } catch (erro) {
        this.#metricas.contar(METRICA_ERROS, motivoDoErro(erro));
        this.#log?.excepcao(erro, "evt_ciclo_falhou");
        // **`largar()`, e não `#lider = false`.** Os *advisory locks* de sessão
        // do PostgreSQL são contados por referência: um `pg_try_advisory_lock`
        // na sessão que já o detém devolve `true` e **incrementa** a contagem.
        // Com o simples `#lider = false`, um erro transitório fazia a volta
        // seguinte re-eleger e a contagem subir a 2 — e no encerramento limpo o
        // `largar()` descia a 1 e a sessão continuava a deter o *lock*, pelo que
        // a réplica deixava de assumir em ≤ 10 s (critério 5) e passava a
        // esperar a detecção de ligação morta, que é escala de minutos. Achado
        // da revisão adversarial (ANALISE-20, achado 13).
        await this.largar();
      }
      await esperar(this.#intervalo, sinal);
    }
    await this.largar();
  }
}

/** Espera `ms`, ou menos se o sinal abortar. Sem `setTimeout` pendurado. */
export function esperar(ms: number, sinal: AbortSignal): Promise<void> {
  if (sinal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const temporizador = setTimeout(terminar, ms);
    function terminar(): void {
      clearTimeout(temporizador);
      sinal.removeEventListener("abort", terminar);
      resolve();
    }
    sinal.addEventListener("abort", terminar, { once: true });
  });
}

export { CANAL_DE_AVISO };
