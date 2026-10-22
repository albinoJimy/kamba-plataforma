/**
 * A máquina de modos da conversa (KAM-018).
 *
 * Quem tem a palavra numa conversa — `bot`, `dono`, `humano` ou `pausada` — e
 * quem a pode passar a quem. A tabela está em `transicoes.ts`, o SQL em
 * `consultas.ts`, e o que este ficheiro acrescenta é a **ordem** e o *lock*:
 *
 * 1. **uma transacção com contexto de tenant** (`ComTenant`), porque a
 *    `conversations` tem RLS `FORCE` e porque um `pg_advisory_xact_lock` fora de
 *    uma transacção é largado na instrução seguinte;
 * 2. **o *lock* da conversa** — `pg_advisory_xact_lock(hash(tenant_id,
 *    contact_id))`, a chave que o critério 2 escreve;
 * 3. **ler** o modo e a última actividade humana;
 * 4. **decidir** pela tabela (`transitar`), que é pura;
 * 5. **escrever**, com o predicado da tabela no `WHERE` — quem perde a corrida
 *    escreve zero linhas e **não** emite evento;
 * 6. **emitir** `conversation.mode_changed`, na mesma transacção.
 *
 * O passo 2 antes do 3 é a única ordem que serve, e é o que o §10.3 descreve: a
 * verificação pré-envio (`guarda.ts`) toma o **mesmo** *lock*, pelo que dentro
 * da secção crítica ou a transição corre inteira antes do guarda, ou o
 * contrário. É isso que faz «0 mensagens do bot depois de o *echo* estar
 * registado» ser uma propriedade e não uma probabilidade.
 *
 * ## O que esta máquina não faz
 *
 * **Não detecta gatilhos.** O `echo_do_dono` e o `comando_bot` chegam por
 * `smb_message_echoes` e isso é coexistência, KAM-017; o «PARAR» é KAM-022, que
 * chama o `onOptOut`; o `conversation_status_changed=resolved` é KAM-019; o
 * `handoff_pedido` vem do grafo, KAM-034. Esta máquina **recebe** gatilhos.
 *
 * **Não espelha nada no Chatwoot.** O `setBotMuted` do `HandoffProvider` é
 * KAM-019 e continua a levantar `SemPrivilegioError`; o que deixava de o
 * impedir é o privilégio que a revisão `0016` concede, mas ligá-lo é alterar o
 * provedor desse ticket. Ver `docs/modos-conversa.md`.
 *
 * **Não envia mensagem nenhuma.** O aviso ao cliente de que a conversa está
 * pausada é KAM-022; o `/bot` é uma mensagem que o **dono** escreve.
 *
 * ## Uma instância por processo
 *
 * Não abre ligações nem filas: recebe as portas de quem a constrói, como todo o
 * resto desta biblioteca.
 */

import { Logger } from "../logger/index.ts";
import {
  type ClienteSql,
  type ComTenant,
  type EmitirModoMudado,
  type EstadoDaConversa,
  type Gatilho,
  MODOS,
  type Modo,
  type Resposta,
  type ResultadoDaMudanca,
  SEM_HUMANO_MS,
} from "./contrato.ts";
import {
  SQL_CONTACTO_DA_CONVERSA,
  SQL_CONVERSAS_DO_CONTACTO,
  SQL_CONVERSA_PARA_MODO,
  SQL_MUDAR_MODO,
  SQL_PAUSAR_POR_INACTIVIDADE,
  SQL_REGISTAR_ACTIVIDADE_HUMANA,
  SQL_TRANCAR_CONVERSA,
} from "./consultas.ts";
import { emitirModoMudado, threadIdDe } from "./eventos.ts";
import {
  METRICA_REJEITADAS,
  METRICA_TRANSICOES,
  MetricasDosModos,
} from "./metricas.ts";
import { origensDe, transitar } from "./transicoes.ts";

/**
 * Os gatilhos que **são** actividade humana, e que por isso escrevem
 * `last_human_activity_at`.
 *
 * Três, e a lista é mais curta do que parece à primeira vista:
 *
 * - `echo_do_dono` — o dono escreveu na app. É actividade humana por definição,
 *   e é a que adia o `silencio_dono_min`;
 * - `comando_bot` — o dono escreveu `/bot`. Também é ele a escrever, e por isso
 *   conta: a conversa volta ao bot **e** o instante fica registado, o que faz o
 *   `PreSendGuard` suprimir uma resposta de um turno que já estava a correr
 *   quando o `/bot` chegou;
 * - `handoff_resolvido` — uma pessoa fechou o atendimento no Chatwoot.
 *
 * **O `handoff_pedido` não está aqui**, e é a decisão que custa mais a explicar.
 * Quem pede o *handoff* é o grafo ou o cliente — ninguém humano agiu —, e
 * escrever `last_human_activity_at` nesse momento tornava a coluna «o instante
 * em que uma pessoa passou a ter a palavra» em vez de «a última actividade
 * humana», que é o que o seu nome diz e o que o guarda compara. A consequência é
 * que uma conversa que passa a `humano` e onde ninguém responde fica com a
 * coluna a `NULL`; o relógio das 24 h conta então de `handoffs.opened_at`, e é
 * por isso que o `SQL_PAUSAR_POR_INACTIVIDADE` tem aquele `COALESCE`.
 *
 * **E o `cliente_escreveu` também não**: escreveu o cliente, que não é o humano
 * de que este invariante fala. Pô-lo aqui fazia cada mensagem do cliente adiar o
 * silêncio do dono — e a conversa nunca voltava ao bot, que é o contrário do que
 * a célula `dono + cliente_escreveu` existe para fazer.
 */
export const GATILHOS_DE_ACTIVIDADE_HUMANA: readonly Gatilho[] = [
  "echo_do_dono",
  "comando_bot",
  "handoff_resolvido",
];

/** A conversa não veio da base na forma esperada. */
export class ConversaIlegivelError extends Error {
  constructor(motivo: string) {
    super(
      `platform.conversations nao respondeu na forma esperada: ${motivo}. ` +
        "As consultas sao `SQL_CONTACTO_DA_CONVERSA`, `SQL_CONVERSA_PARA_MODO` e `SQL_CONVERSAS_DO_CONTACTO`.",
    );
    this.name = "ConversaIlegivelError";
  }
}

/** Pediu-se o modo de uma conversa que não existe neste tenant. */
export class ConversaDesconhecidaError extends Error {
  constructor() {
    super(
      "nao ha conversa com este id neste tenant: a RLS ja filtra por " +
        "`app.tenant_id`, pelo que zero linhas significa «nao e deste tenant» " +
        "ou «nao existe», e as duas tratam-se da mesma maneira",
    );
    this.name = "ConversaDesconhecidaError";
  }
}

const MODOS_CONHECIDOS: readonly string[] = MODOS;

function modoDaLinha(valor: unknown): Modo {
  if (typeof valor !== "string" || !MODOS_CONHECIDOS.includes(valor)) {
    // Um modo que o código não conhece **para** aqui, e não é tratado como o
    // mais parecido: é a mesma decisão que o `conversaDaLinha` do
    // `chr/conversas.ts` tomou, e pela mesma razão — adivinhar o modo era
    // arriscar pôr a conversa em `bot` e deixar o assistente interromper uma
    // pessoa (`docs/tecnica/01` §10.2).
    throw new ConversaIlegivelError(`modo desconhecido ${JSON.stringify(valor)}`);
  }
  return valor as Modo;
}

function tempoDaLinha(valor: unknown): Date | null {
  if (valor === null || valor === undefined) return null;
  if (valor instanceof Date) return valor;
  if (typeof valor === "string") {
    const data = new Date(valor);
    if (!Number.isNaN(data.getTime())) return data;
  }
  throw new ConversaIlegivelError("`last_human_activity_at` nao veio como data");
}

/** O que a máquina precisa para funcionar. */
export interface Dependencias {
  readonly comTenant: ComTenant;
  /**
   * `null` deixa a máquina a funcionar **sem emitir** `conversation.mode_changed`.
   *
   * É o que as baterias do *gate* 4 usam, porque uma base falsa não tem
   * `platform.evt_emitir`. Em produção passa-se `emitirModoMudado`, que é a
   * omissão desta propriedade quando ela não é dada — ver o construtor.
   */
  readonly emitir?: EmitirModoMudado | null;
  readonly metricas?: MetricasDosModos;
  readonly log?: Logger;
  /** O relógio, por parâmetro. Os testes da tabela precisam de o fixar. */
  readonly agora?: () => Date;
}

/** O resultado do *job* das 24 h. */
export interface ResultadoDaInactividade {
  /** Quantas conversas passaram a `pausada` **nesta** passagem. */
  readonly pausadas: number;
  /** Os `conversation_id`, pela ordem em que a base os devolveu. */
  readonly ids: readonly string[];
  /** Os `event_id` emitidos, um por conversa pausada. Vazio sem porta. */
  readonly eventos: readonly string[];
}

/** A máquina de modos. Uma instância por processo. */
export class MaquinaDeModos {
  readonly #comTenant: ComTenant;
  readonly #emitir: EmitirModoMudado | null;
  readonly #metricas: MetricasDosModos;
  readonly #log: Logger | undefined;
  readonly #agora: () => Date;

  constructor(dependencias: Dependencias) {
    this.#comTenant = dependencias.comTenant;
    this.#emitir =
      dependencias.emitir === undefined ? emitirModoMudado : dependencias.emitir;
    this.#metricas = dependencias.metricas ?? new MetricasDosModos();
    this.#log = dependencias.log;
    this.#agora = dependencias.agora ?? (() => new Date());
  }

  get metricas(): MetricasDosModos {
    return this.#metricas;
  }

  /**
   * Dispara um gatilho sobre uma conversa. É a entrada única da máquina.
   *
   * Abre a transacção, toma o *lock*, lê, decide, escreve e emite — pela ordem
   * da nota do módulo. Nunca lança por o gatilho não fazer sentido: uma
   * transição rejeitada é um resultado com `resposta.tipo === "rejeitada"`, e
   * conta-se em `conv_mode_rejected_total`. Lança quando a conversa não existe
   * (`ConversaDesconhecidaError`) ou quando a base responde numa forma que não
   * se consegue ler (`ConversaIlegivelError`): as duas são defeitos de quem
   * chama ou da base, não tráfego.
   */
  async disparar(
    alvo: { readonly tenantId: string; readonly conversationId: string },
    gatilho: Gatilho,
  ): Promise<ResultadoDaMudanca> {
    return this.#comTenant(alvo.tenantId, async (cliente) => {
      // Só o `contact_id`, que é a chave do *lock* e que quem chama não tem (a
      // porta `MudarModo` do `ConsentGate` dá o `conversation_id` e mais nada).
      // **Não** se lê o modo aqui: ver `SQL_CONTACTO_DA_CONVERSA`.
      const contactId = await this.#lerContacto(
        cliente,
        alvo.tenantId,
        alvo.conversationId,
      );
      await this.#trancar(cliente, alvo.tenantId, contactId);
      // A leitura que **decide**, e é agora: um modo lido antes do *lock*
      // podia já estar velho quando o *lock* chegasse, e decidir com ele era
      // decidir fora da secção crítica — precisamente o que o *lock* existe
      // para impedir. Com duas transições concorrentes a decidirem as duas
      // sobre `bot`, a segunda perdia pelo predicado do `UPDATE` (o desfecho
      // certo pela razão errada) e `conv_mode_transitions_total` contava uma
      // transição que não aconteceu.
      const estado = await this.#lerEstado(
        cliente,
        alvo.tenantId,
        alvo.conversationId,
      );
      return this.#aplicar(
        cliente,
        alvo.tenantId,
        alvo.conversationId,
        contactId,
        estado,
        gatilho,
      );
    });
  }

  /**
   * O cliente pediu para parar: todas as conversas dele passam a `pausada`
   * (critério 7).
   *
   * **Por contacto e não por conversa**, e é o que o critério escreve —
   * `onOptOut(contact)`. Um contacto pode ter conversa em mais de um canal do
   * mesmo tenant, e um «PARAR» é do titular dos dados e não de um canal: pausar
   * só a conversa onde ele escreveu deixava o assistente a falar com ele no
   * outro número da mesma loja.
   *
   * **Uma transacção e um *lock* para todas**, e é aqui que a escolha da chave
   * do *lock* se paga: `hash(tenant_id, contact_id)` trava as conversas todas
   * do contacto de uma vez. Com uma chave por conversa, o `onOptOut` pausava-as
   * uma a uma com uma janela entre cada par, e um turno do bot que começasse no
   * meio apanhava uma conversa ainda em `bot`.
   *
   * **Idempotente sem chave de idempotência**, e a razão é a tabela: a célula
   * `pausada + opt_out` é `sem_efeito`. Repetir o «PARAR» devolve N resultados
   * com `mudou: false` e não escreve nada — não há coluna de controlo a manter
   * nem evento repetido no outbox. A detecção do «PARAR» é KAM-022, e é ela que
   * tem a sua própria chave (`consent_event`, a prova *append-only*).
   */
  async onOptOut(alvo: {
    readonly tenantId: string;
    readonly contactId: string;
  }): Promise<readonly ResultadoDaMudanca[]> {
    return this.#comTenant(alvo.tenantId, async (cliente) => {
      await this.#trancar(cliente, alvo.tenantId, alvo.contactId);
      const resultado = await cliente.query(SQL_CONVERSAS_DO_CONTACTO, [
        alvo.tenantId,
        alvo.contactId,
      ]);
      const saida: ResultadoDaMudanca[] = [];
      for (const linha of resultado.rows) {
        const id = linha.id;
        if (typeof id !== "string" || id === "") {
          throw new ConversaIlegivelError("o `id` da conversa nao veio como texto");
        }
        const estado: EstadoDaConversa = {
          mode: modoDaLinha(linha.mode),
          ultimaActividadeHumana: tempoDaLinha(linha.last_human_activity_at),
        };
        saida.push(
          await this.#aplicar(
            cliente,
            alvo.tenantId,
            id,
            alvo.contactId,
            estado,
            "opt_out",
          ),
        );
      }
      return saida;
    });
  }

  /**
   * O *job* das 24 h: pausa as conversas que ficaram em atendimento humano sem
   * humano nenhum (critério 7).
   *
   * **Idempotente pelo predicado**, não por uma marca escrita: ver
   * `SQL_PAUSAR_POR_INACTIVIDADE`. Correr duas vezes seguidas pausa N e depois
   * 0.
   *
   * **É uma função e não um *job* agendado**, pela decisão que a `0005` já
   * escreveu para a retenção do outbox: «uma função é testável agora e chamável
   * depois». O agendador nasce com KAM-071/KAM-078. O que se entrega aqui é o
   * efeito, com o seu teste de repetição.
   *
   * Corre por **tenant**, e isso não é limitação: a `conversations` tem RLS
   * `FORCE` com a política `tenant_iso`, pelo que uma passagem global exigia
   * `kamba_batch` (que contorna a RLS) e esse papel não é deste caminho. Quem
   * agendar o *job* itera os tenants activos, que é o que o KAM-071 já tem de
   * fazer para a retenção.
   */
  async pausarPorInactividade(tenantId: string): Promise<ResultadoDaInactividade> {
    const origens = origensDe("sem_humano_24h", "pausada");
    const limite = new Date(this.#agora().getTime() - SEM_HUMANO_MS);
    return this.#comTenant(tenantId, async (cliente) => {
      const resultado = await cliente.query(SQL_PAUSAR_POR_INACTIVIDADE, [
        tenantId,
        limite,
        origens,
        "pausada",
      ]);
      const ids: string[] = [];
      const eventos: string[] = [];
      for (const linha of resultado.rows) {
        const id = linha.id;
        const contactId = linha.contact_id;
        if (typeof id !== "string" || typeof contactId !== "string") {
          throw new ConversaIlegivelError(
            "o `id` ou o `contact_id` da conversa pausada nao veio como texto",
          );
        }
        ids.push(id);
        const eventoId = await this.#emitirSeHouverPorta(
          cliente,
          tenantId,
          id,
          contactId,
          "pausada",
        );
        // Depois da emissão, pela razão do `#aplicar`: um contador em memória
        // não é desfeito com a transacção.
        this.#metricas.contar(METRICA_TRANSICOES, "sem_humano_24h");
        if (eventoId !== null) eventos.push(eventoId);
      }
      if (ids.length > 0) {
        this.#log?.info({ outcome: "modo_pausado_por_inactividade", tenant_id: tenantId });
      }
      return { pausadas: ids.length, ids, eventos };
    });
  }

  /**
   * A porta `MudarModo` que o `ConsentGate` do KAM-022 espera.
   *
   * O `consentimento/contrato.ts` declara-a assim —
   * `(tenantId, conversationId, modo: "humano" | "pausada") => Promise<void>` —
   * e a `0015` deixou-a **por ligar** com a razão escrita: «quem a ligar é quem
   * tiver o privilégio, e este módulo não o tem». O privilégio é o da revisão
   * `0016`, e quem o tem é esta máquina.
   *
   * A porta pede um **modo** e a máquina recebe **gatilhos**, e a tradução é a
   * das duas acções do gate (`consentimento/decisao.ts`):
   *
   * | o gate decide | porta pede | gatilho |
   * |---|---|---|
   * | `passar_a_humano` | `humano` | `handoff_pedido` |
   * | `registar_revogacao` (o «PARAR») | `pausada` | `opt_out` |
   *
   * **Devolve `void` e engole o resultado**, e isso é a assinatura da porta e
   * não uma escolha deste módulo: o gate já escreveu o que decidiu nos campos
   * `passaAHumano` e `pausaAConversa` do seu resultado, e uma transição que a
   * tabela recuse fica contada em `conv_mode_rejected_total` e registada — não
   * lança, porque uma transição rejeitada é um **resultado** e não um erro. Um
   * `PARAR` registado com prova *append-only* e um aviso já enviado não deve
   * ser desfeito por a conversa estar num modo de que a tabela não sai.
   *
   * **E a conversa que não existe também não o desfaz.** O `disparar` lança
   * `ConversaDesconhecidaError` nesse caso, e a porta apanha-a: o gate chama
   * esta porta **depois** da prova e do aviso, e deixar a excepção subir fazia
   * o `tratar` falhar com os dois já escritos. Qualquer outro erro sobe — ver o
   * corpo.
   */
  portaDoConsentGate(): (
    tenantId: string,
    conversationId: string,
    modo: "humano" | "pausada",
  ) => Promise<void> {
    return async (tenantId, conversationId, modo) => {
      const gatilho: Gatilho = modo === "humano" ? "handoff_pedido" : "opt_out";
      try {
        await this.disparar({ tenantId, conversationId }, gatilho);
      } catch (erro) {
        // **Uma conversa que não existe não desfaz um «PARAR» já registado.**
        //
        // O `disparar` **lança** `ConversaDesconhecidaError` quando a conversa
        // não é deste tenant ou já não existe — a retenção do KAM-071 pode
        // tê-la purgado entre a mensagem e esta chamada —, e o `ConsentGate`
        // chama esta porta **depois** de escrever a prova *append-only* e de
        // enviar o aviso. Deixar a excepção subir fazia o `tratar` falhar com a
        // prova escrita e a mensagem enviada, e o *job* repetia-se sobre um
        // estado que nunca vai melhorar: a conversa não volta a existir. É o
        // mesmo raciocínio do `mensagem_sem_identidade` do KAM-014.
        //
        // Só esta. Qualquer outro erro — a base indisponível, um modo que o
        // código não conhece (`ConversaIlegivelError`) — **sobe**: são defeitos
        // nossos ou da base, e calá-los era o que esta decisão não quer.
        if (!(erro instanceof ConversaDesconhecidaError)) throw erro;
        this.#log?.warn({ outcome: "modo_sem_conversa", tenant_id: tenantId });
      }
    };
  }

  // ------------------------------------------------------------------ privado

  async #trancar(cliente: ClienteSql, tenantId: string, contactId: string): Promise<void> {
    await cliente.query(SQL_TRANCAR_CONVERSA, [tenantId, contactId]);
  }

  /** O contacto da conversa, para a chave do *lock*. Corre antes de trancar. */
  async #lerContacto(
    cliente: ClienteSql,
    tenantId: string,
    conversationId: string,
  ): Promise<string> {
    const resultado = await cliente.query(SQL_CONTACTO_DA_CONVERSA, [
      tenantId,
      conversationId,
    ]);
    const linha = resultado.rows[0];
    if (linha === undefined) throw new ConversaDesconhecidaError();
    const contactId = linha.contact_id;
    if (typeof contactId !== "string" || contactId === "") {
      throw new ConversaIlegivelError("o `contact_id` nao veio como texto");
    }
    return contactId;
  }

  /** O modo e a actividade humana. **Só** depois de o *lock* estar tomado. */
  async #lerEstado(
    cliente: ClienteSql,
    tenantId: string,
    conversationId: string,
  ): Promise<EstadoDaConversa> {
    const resultado = await cliente.query(SQL_CONVERSA_PARA_MODO, [
      tenantId,
      conversationId,
    ]);
    const linha = resultado.rows[0];
    if (linha === undefined) throw new ConversaDesconhecidaError();
    return {
      mode: modoDaLinha(linha.mode),
      ultimaActividadeHumana: tempoDaLinha(linha.last_human_activity_at),
    };
  }

  /** Decide, escreve e emite. Assume a transacção aberta e o *lock* tomado. */
  async #aplicar(
    cliente: ClienteSql,
    tenantId: string,
    conversationId: string,
    contactId: string,
    estado: EstadoDaConversa,
    gatilho: Gatilho,
  ): Promise<ResultadoDaMudanca> {
    const agora = this.#agora();
    const resposta = transitar(estado, gatilho, agora);
    const actividade = GATILHOS_DE_ACTIVIDADE_HUMANA.includes(gatilho) ? agora : null;

    if (resposta.tipo === "rejeitada") {
      this.#metricas.contar(METRICA_REJEITADAS, gatilho);
      // **Um gatilho rejeitado não escreve nada**, nem a actividade humana: um
      // `comando_bot` sobre uma conversa em `humano` é um gatilho mal ligado, e
      // registar actividade humana a partir dele adiava as 24 h por causa de um
      // defeito nosso.
      //
      // **O gatilho NÃO entra no `outcome`, e isso foi um defeito medido.** A
      // primeira versão escrevia `modo_rejeitado_${gatilho}`, e um dos oito
      // gatilhos — o `sem_humano_24h` — não cabe na gramática do campo: um
      // segmento é letras com até três dígitos **no fim**, ou um número, e
      // `24h` não é nenhum dos dois (`logger/politica.ts`). Em modo estrito,
      // que é o do CI, o `Logger` **levanta** — e uma transição rejeitada, que
      // é um resultado normal desta função, passava a excepção não tratada no
      // caminho de um *webhook*. É a mesma armadilha que o
      // `codigoParaRegisto` do `outbound/adapter.ts` já pagou com o `-1`.
      //
      // O gatilho não se perde: está na etiqueta de
      // `conv_mode_rejected_total`, que é onde se conta e onde a lista é
      // fechada. Dois sítios para a mesma informação divergiam, e um deles
      // levantava.
      this.#log?.warn({ outcome: "modo_rejeitado", tenant_id: tenantId });
      return this.#semMudanca(resposta, estado.mode);
    }

    if (resposta.tipo === "sem_efeito") {
      if (actividade === null) return this.#semMudanca(resposta, estado.mode);
      // O caso do dono a continuar a falar numa conversa já em `dono`. Não há
      // transição e há escrita — ver `SQL_REGISTAR_ACTIVIDADE_HUMANA`.
      const escrito = await cliente.query(SQL_REGISTAR_ACTIVIDADE_HUMANA, [
        tenantId,
        conversationId,
        actividade,
      ]);
      const linha = escrito.rows[0];
      if (linha === undefined) throw new ConversaDesconhecidaError();
      return {
        resposta,
        modo: modoDaLinha(linha.mode),
        // `mudou` é sobre o **modo**, e o modo não mudou. A escrita da
        // actividade humana não é uma transição e não se conta como uma.
        mudou: false,
        ganhou: true,
        eventoId: null,
      };
    }

    const origens = origensDe(gatilho, resposta.para);
    const escrito = await cliente.query(SQL_MUDAR_MODO, [
      tenantId,
      conversationId,
      resposta.para,
      origens,
      actividade,
    ]);
    const linha = escrito.rows[0];
    if (linha === undefined) {
      // Zero linhas: outro processo transitou primeiro. **Não se emite evento
      // e não se conta transição** — é a mesma leitura do `SQL_AVANCAR_ESTADO`
      // do KAM-015, e é o que impede duas mudanças publicadas para uma
      // transição. O modo que se devolve é o que a leitura trouxe, e pode já
      // não ser o actual: quem precisar do actual lê outra vez, e quem chama
      // tem o `ganhou: false` para saber que não é a sua palavra.
      this.#log?.info({ outcome: "modo_corrida_perdida", tenant_id: tenantId });
      return { resposta, modo: estado.mode, mudou: false, ganhou: false, eventoId: null };
    }
    const modoAntes = modoDaLinha(linha.modo_antes);
    const modoDepois = modoDaLinha(linha.modo_depois);
    const eventoId = await this.#emitirSeHouverPorta(
      cliente,
      tenantId,
      conversationId,
      contactId,
      modoDepois,
    );
    // **Conta-se e registra-se DEPOIS da emissão, e a ordem é o ponto.** As
    // duas escritas vivem na mesma transacção: se a emissão levantar, o
    // `UPDATE` é desfeito e a transição não aconteceu. Um contador em memória
    // **não** é desfeito com ela, pelo que contar antes deixava
    // `conv_mode_transitions_total` a afirmar transições que a base nunca
    // guardou — e o painel a mentir por cima, que é o defeito que o
    // `SQL_AVANCAR_ESTADO` do KAM-015 já ensinou a não repetir do lado do
    // custo. Há bateria que faz a porta de emissão levantar.
    this.#metricas.contar(METRICA_TRANSICOES, gatilho);
    this.#log?.info({ outcome: `modo_${modoAntes}_para_${modoDepois}`, tenant_id: tenantId });
    return { resposta, modo: modoDepois, mudou: true, ganhou: true, eventoId };
  }

  #semMudanca(resposta: Resposta, modo: Modo): ResultadoDaMudanca {
    return { resposta, modo, mudou: false, ganhou: true, eventoId: null };
  }

  async #emitirSeHouverPorta(
    cliente: ClienteSql,
    tenantId: string,
    conversationId: string,
    contactId: string,
    modo: Modo,
  ): Promise<string | null> {
    if (this.#emitir === null) return null;
    return this.#emitir(
      cliente,
      tenantId,
      conversationId,
      threadIdDe(tenantId, contactId),
      modo,
    );
  }
}
