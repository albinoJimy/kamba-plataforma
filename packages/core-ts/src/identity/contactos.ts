/**
 * O serviço de identidade de contacto (KAM-008, ADR-010).
 *
 * Resolve um BSUID ou um telefone para um `contact_id` aleatório, e é o único
 * código que lê `contact_endpoints` e `contact_deks`. Fora daqui, o resto da
 * plataforma só conhece o `contact_id`.
 *
 *     const identidade = await Identidade.arrancar({ chaves });
 *     const { contactId, evento } = await identidade.resolveContact(cliente, {
 *       tenantId, bsuid, telefone,
 *     });
 *     if (evento !== null) await emitir(evento); // quem emite é quem chama (KAM-014)
 *
 * ## O cliente
 *
 * `cliente` é **uma ligação** de `kamba_identity` — nunca um *pool*, e nunca
 * `kamba_app`, que não tem privilégio para ler o cofre. Cada operação abre a sua
 * transacção com o contexto do tenant (`comTenant`, KAM-004): o papel não
 * contorna a RLS, e uma operação nunca vê mais do que um tenant.
 *
 * ## Resolução (`docs/tecnica/01` §6.3)
 *
 * 1. Por **BSUID**: HMAC sob a chave actual e sob a anterior.
 * 2. Por **telefone**: idem.
 * 3. Nada encontrado: **cria**.
 *
 * E quando as duas pesquisas encontram coisas diferentes:
 *
 * - o contacto do telefone **não tem BSUID** — é a mesma pessoa, vista primeiro
 *   só pelo número: **fundem-se**, fica o mais antigo, e a operação devolve o
 *   evento `contact.merged`;
 * - o contacto do telefone **tem outro BSUID** — são duas pessoas, e o número
 *   mudou de mãos (o BSUID é único por utilizador e portfólio, `E1` §3): o
 *   telefone passa para quem o traz agora, e o antigo titular perde-o. **Não se
 *   fundem.** Esta regra não está em nenhum documento do conjunto: é *proposta*
 *   deste ticket, e está em `docs/identidade.md` §4.
 *
 * ## O que este módulo não faz
 *
 * Não regista nada (nem o tenant, nem o contacto, nem o erro), não emite
 * eventos, não trata consentimento (KAM-022) nem a purga por `expira_at`
 * (KAM-071). Os erros que lança **nunca** levam um BSUID nem um telefone.
 */

import { Buffer } from "node:buffer";
import { randomUUID } from "node:crypto";

import { Contadores, comTenant, normalizarTenant } from "../tenant_guard/index.ts";
import type { ProcessEnv } from "../secrets/index.ts";
import {
  type KeyProvider,
  epocaValida,
  EpocaInvalidaError,
  exigirKeyProviderDeCofre,
  kidValido,
} from "./chaves.ts";
import * as SQL from "./consultas.ts";
import {
  type CampoCifrado,
  cifrar,
  contextoDaCifra,
  contextoDoEmbrulho,
  decifrar,
  hmacDePesquisa,
  normalizarBsuid,
  normalizarTelefone,
  normalizarUuid,
  novaDek,
  sujeitoRefDe,
} from "./cripto.ts";

/** Uma linha devolvida pelo *driver*. */
export type Linha = Readonly<Record<string, unknown>>;

/** O resultado de uma instrução, na forma do `pg`. */
export interface ResultadoSql {
  readonly rows: readonly Linha[];
  readonly rowCount?: number | null;
}

/**
 * O mínimo de um cliente SQL de que o módulo precisa: a forma do `pg.Client`.
 *
 * Os erros do *driver* têm de trazer o SQLSTATE em `code` (o `pg` traz): é por
 * ele que se reconhece a corrida entre dois pedidos pelo mesmo contacto.
 */
export interface ClienteDeIdentidade {
  query(sql: string, parametros?: readonly unknown[]): Promise<ResultadoSql>;
}

/** Finalidades para que um telefone pode ser guardado (`contact_endpoints.finalidade`). */
export const FINALIDADES = ["pagamento_express", "entrega", "contacto_pedido"] as const;
export type Finalidade = (typeof FINALIDADES)[number];

/** Contadores do módulo. Só números: nenhum leva tenant nem contacto. */
export const CONTADORES_DE_IDENTIDADE = new Contadores();
export const METRICA_RESOLVER = "identity_resolve_total";
export const METRICA_APAGAR = "identity_erase_total";
export const METRICA_LER = "identity_endpoints_read_total";
export const METRICA_RODAR = "identity_rekey_rows_total";
export const METRICA_REPETICOES = "identity_tx_retry_total";

/** Tentativas de uma operação antes de desistir de uma corrida. */
export const TENTATIVAS = 5;
/** Linhas por transacção em `rekeyLookup`, por omissão (*proposta*). */
export const LOTE_DE_ROTACAO = 200;
const LOTE_MAXIMO = 1000;
/** Saltos máximos numa cadeia de fusões (A absorvido por B, B por C…). */
const CADEIA_MAXIMA = 16;
const UUID_ZERO = "00000000-0000-0000-0000-000000000000";

const VIOLACAO_DE_UNICIDADE = "23505";
const ABRACO_MORTAL = "40P01";
const FALHA_DE_SERIALIZACAO = "40001";

/** O pedido não traz BSUID nem telefone. */
export class PedidoSemIdentificadorError extends Error {
  override readonly name = "PedidoSemIdentificadorError";

  constructor() {
    super("resolveContact precisa de um BSUID ou de um telefone");
  }
}

/** Pediu-se para guardar o telefone sem dizer para quê ou até quando. */
export class RetencaoInvalidaError extends Error {
  override readonly name = "RetencaoInvalidaError";

  constructor(motivo: string) {
    super(`guardar o telefone exige finalidade e prazo: ${motivo}`);
  }
}

/** Não há versão `actual` em `hmac_key_versions`: falta `iniciarRotacao`. */
export class SemChaveActualError extends Error {
  override readonly name = "SemChaveActualError";

  constructor() {
    super(
      "não há versão actual da chave de pesquisa registada; " +
        "registe a primeira com iniciarRotacao(kid)",
    );
  }
}

/** A versão pedida não é a `actual`. */
export class KidNaoActualError extends Error {
  override readonly name = "KidNaoActualError";
  readonly kid: string;

  constructor(kid: string) {
    super(`a versão ${JSON.stringify(kid)} não é a actual; inicie a rotação primeiro`);
    this.kid = kid;
  }
}

/** Há uma rotação por concluir: a versão anterior ainda está viva. */
export class RotacaoEmCursoError extends Error {
  override readonly name = "RotacaoEmCursoError";
  readonly anterior: string;

  constructor(anterior: string) {
    super(
      `a versão ${JSON.stringify(anterior)} ainda é a anterior; conclua essa rotação ` +
        "(concluirRotacao) antes de iniciar outra",
    );
    this.anterior = anterior;
  }
}

/** Um `kid` já usado não volta a ser a versão actual. */
export class KidReutilizadoError extends Error {
  override readonly name = "KidReutilizadoError";
  readonly kid: string;

  constructor(kid: string) {
    super(`a versão ${JSON.stringify(kid)} já existiu; uma versão nova tem um kid novo`);
    this.kid = kid;
  }
}

/** O `kid` não tem forma de identificador. */
export class KidInvalidoError extends Error {
  override readonly name = "KidInvalidoError";

  constructor() {
    super("o kid tem de ser minúsculas, algarismos, `_`, `.` ou `-` (1 a 63 caracteres)");
  }
}

/** O contacto não existe neste tenant. */
export class ContactoDesconhecidoError extends Error {
  override readonly name = "ContactoDesconhecidoError";

  constructor() {
    super("o contacto não existe neste tenant");
  }
}

/** O contacto foi apagado a pedido do titular: já não há endpoints para ler. */
export class ContactoApagadoError extends Error {
  override readonly name = "ContactoApagadoError";

  constructor() {
    super("o contacto foi apagado: os endpoints e a chave de dados já não existem");
  }
}

/** A DEK foi destruída: a cifra que ainda exista (numa cópia, por exemplo) não abre. */
export class DekDestruidaError extends Error {
  override readonly name = "DekDestruidaError";

  constructor() {
    super("a chave de dados deste contacto foi destruída; a cifra já não se abre");
  }
}

/** A base está num estado que o módulo não sabe resolver sem escolher por alguém. */
export class IdentidadeInconsistenteError extends Error {
  override readonly name = "IdentidadeInconsistenteError";

  constructor(motivo: string) {
    super(`identidade inconsistente: ${motivo}`);
  }
}

/** O cliente não devolve resultados na forma do `pg`, ou é um *pool*. */
export class ClienteInvalidoError extends Error {
  override readonly name = "ClienteInvalidoError";

  constructor(motivo: string) {
    super(`cliente SQL inválido: ${motivo}`);
  }
}

/** Sinal interno: o que se leu mudou antes de se trancar. Repete-se a operação. */
class Repetir extends Error {
  override readonly name = "Repetir";
}

/**
 * O pedido de `resolveContact`.
 *
 * `bsuid` e `telefone` têm de vir de uma **fonte autenticada** — o webhook da
 * Meta, com a assinatura conferida —, nunca de texto que um utilizador escreveu.
 * Um telefone num pedido tira-o a quem o tinha: com um número escrito à mão numa
 * conversa, qualquer pessoa tirava o número a outra.
 */
export interface PedidoDeResolucao {
  readonly tenantId: string;
  /** O BSUID que a Meta mandou (`user_id`, `from_user_id`). */
  readonly bsuid?: string | null | undefined;
  /** O telefone em E.164, com ou sem `+` (`wa_id`, `from`). */
  readonly telefone?: string | null | undefined;
  /**
   * Só quando há necessidade operacional de voltar a ler o número (`phone_enc`
   * «só se existir e for necessário», dicionário §3.1). Sem isto, do telefone
   * fica apenas o HMAC, que serve para o reconhecer e não para o ler.
   */
  readonly guardarTelefone?:
    | {
        readonly finalidade: Finalidade;
        /** Fim da retenção. **Não há omissão**: os prazos estão por confirmar por parecer. */
        readonly expiraAt: Date;
      }
    | undefined;
}

/**
 * O que a fusão devolve a quem emite (KAM-014, por KAM-005).
 *
 * Só os campos do envelope do dicionário §3.5 que este módulo conhece: `id`,
 * `versao`, `agregado`, `seq` e `trace_id` são de quem emite. A forma do
 * `payload` é *proposta* até o KAM-007 lhe dar *schema*. Só `contact_id`: nunca
 * telefone nem BSUID (`docs/tecnica/06` §7.1).
 */
export interface EventoContactMerged {
  readonly tipo: "contact.merged";
  readonly tenant_id: string;
  readonly ocorrido_em: string;
  readonly payload: {
    /** O contacto que ficou (o mais antigo). */
    readonly contact_id: string;
    /** O contacto absorvido; a sua linha fica como lápide. */
    readonly merged_contact_id: string;
  };
}

export type Desfecho = "criado" | "existente" | "completado" | "fundido";

export interface ContactoResolvido {
  readonly tenantId: string;
  readonly contactId: string;
  readonly desfecho: Desfecho;
  /** Não nulo só quando esta chamada fundiu dois contactos. */
  readonly evento: EventoContactMerged | null;
}

/** O que um gancho de fusão recebe. Corre **dentro** da transacção da fusão. */
export interface ContextoDeFusao {
  /** A ligação da fusão, com a transacção aberta e o contexto do tenant definido. */
  readonly cliente: ClienteDeIdentidade;
  readonly tenantId: string;
  /** O contacto absorvido. */
  readonly de: string;
  /** O contacto que fica. */
  readonly para: string;
}

/**
 * Um gancho de fusão: migra para `para` o que pertencia a `de`.
 *
 * Se lançar, **a fusão inteira é desfeita**. Só deve escrever pela ligação que
 * recebe: a transacção pode ser repetida depois de uma corrida, e um efeito fora
 * da base (um pedido HTTP, uma mensagem) repetia-se com ela.
 */
export type GanchoDeFusao = (contexto: ContextoDeFusao) => Promise<void>;

export interface ResultadoDoApagamento {
  /** O contacto apagado: o que foi pedido, ou o que o tinha absorvido. */
  readonly contactId: string;
  /** `true` se já estava apagado e esta chamada não mudou nada. */
  readonly jaApagado: boolean;
  readonly endpointsApagados: number;
  readonly deksDestruidas: number;
  readonly apagadoEm: Date;
}

export interface EndpointsDoContacto {
  readonly contactId: string;
  readonly bsuids: readonly string[];
  readonly telefones: readonly {
    readonly finalidade: Finalidade;
    readonly telefone: string;
    readonly expiraAt: Date;
  }[];
}

export interface OpcoesDeRotacao {
  /** Linhas por transacção. Por omissão, `LOTE_DE_ROTACAO`. */
  readonly lote?: number;
  /** Pára depois de N transacções, com o que falta em `porRodar`. Para retomar depois. */
  readonly maximoDeLotes?: number;
  /**
   * O que fazer ao HMAC de um telefone de que não há cifra para o recalcular.
   *
   * `manter` (omissão): fica sob a chave antiga; continua a ser encontrado
   * enquanto ela for a `anterior`, e sobe para a nova quando o número voltar a
   * aparecer. `largar`: apaga-se o HMAC — o contacto deixa de ser reconhecido
   * por esse número. É o passo final antes de retirar a chave antiga.
   */
  readonly telefonesSemCifra?: "manter" | "largar";
}

export interface ResultadoDaRotacao {
  readonly kid: string;
  readonly bsuidsRodados: number;
  readonly telefonesRodados: number;
  readonly telefonesLargados: number;
  /** O que ainda não está sob `kid` depois desta chamada. */
  readonly porRodar: { readonly bsuids: number; readonly telefones: number };
  readonly completo: boolean;
  readonly lotes: number;
}

export interface ResultadoDeIniciarRotacao {
  readonly kid: string;
  /** `false` se `kid` já era a versão actual. */
  readonly alterado: boolean;
  readonly anterior: string | null;
}

export interface OpcoesDeIdentidade {
  readonly chaves: KeyProvider;
  /** Por omissão, `process.env`. Só se lê `KAMBA_ENV`. */
  readonly env?: ProcessEnv;
  /** Relógio injectável, para os testes. */
  readonly agora?: () => Date;
}

interface EstadoDoContacto {
  readonly id: string;
  readonly criadoAt: Date;
  readonly erasedAt: Date | null;
  readonly mergedInto: string | null;
  readonly phoneHmac: Buffer | null;
  readonly hmacKid: string | null;
}

interface KidsVivos {
  readonly actual: string;
  readonly anterior: string | null;
}

function texto(linha: Linha, coluna: string): string {
  const valor = linha[coluna];
  if (typeof valor !== "string") {
    throw new ClienteInvalidoError(`a coluna ${coluna} não veio como texto`);
  }
  return valor;
}

function textoOuNulo(linha: Linha, coluna: string): string | null {
  return linha[coluna] === null || linha[coluna] === undefined ? null : texto(linha, coluna);
}

function octetos(linha: Linha, coluna: string): Buffer {
  const valor = linha[coluna];
  if (!(valor instanceof Uint8Array)) {
    throw new ClienteInvalidoError(`a coluna ${coluna} não veio como octetos`);
  }
  return Buffer.from(valor);
}

function octetosOuNulo(linha: Linha, coluna: string): Buffer | null {
  return linha[coluna] === null || linha[coluna] === undefined ? null : octetos(linha, coluna);
}

function instante(linha: Linha, coluna: string): Date {
  const valor = linha[coluna];
  if (!(valor instanceof Date) || Number.isNaN(valor.getTime())) {
    throw new ClienteInvalidoError(`a coluna ${coluna} não veio como data`);
  }
  return valor;
}

function instanteOuNulo(linha: Linha, coluna: string): Date | null {
  return linha[coluna] === null || linha[coluna] === undefined ? null : instante(linha, coluna);
}

async function consultar(
  cliente: ClienteDeIdentidade,
  sql: string,
  parametros: readonly unknown[] = [],
): Promise<readonly Linha[]> {
  const resultado = await cliente.query(sql, parametros);
  if (resultado === null || typeof resultado !== "object" || !Array.isArray(resultado.rows)) {
    throw new ClienteInvalidoError("o resultado não tem `rows`");
  }
  return resultado.rows;
}

async function executar(
  cliente: ClienteDeIdentidade,
  sql: string,
  parametros: readonly unknown[] = [],
): Promise<number> {
  const resultado = await cliente.query(sql, parametros);
  const afectadas = resultado?.rowCount;
  if (typeof afectadas !== "number") {
    throw new ClienteInvalidoError("o resultado não tem `rowCount`");
  }
  return afectadas;
}

function repetivel(erro: unknown): boolean {
  if (erro instanceof Repetir) return true;
  const codigo = (erro as { code?: unknown } | null)?.code;
  return (
    codigo === VIOLACAO_DE_UNICIDADE ||
    codigo === ABRACO_MORTAL ||
    codigo === FALHA_DE_SERIALIZACAO
  );
}

function iguais(a: Uint8Array | null, b: Uint8Array | null): boolean {
  if (a === null || b === null) return a === b;
  return Buffer.from(a).equals(Buffer.from(b));
}

function estadoDe(linha: Linha): EstadoDoContacto {
  return {
    id: texto(linha, "contact_id"),
    criadoAt: instante(linha, "criado_at"),
    erasedAt: instanteOuNulo(linha, "erased_at"),
    mergedInto: textoOuNulo(linha, "merged_into"),
    phoneHmac: octetosOuNulo(linha, "phone_hmac"),
    hmacKid: textoOuNulo(linha, "hmac_kid"),
  };
}

/** O mais antigo fica; em empate, o de `contact_id` menor. Determinístico. */
function maisAntigoPrimeiro(
  a: EstadoDoContacto,
  b: EstadoDoContacto,
): [EstadoDoContacto, EstadoDoContacto] {
  const diferenca = a.criadoAt.getTime() - b.criadoAt.getTime();
  if (diferenca !== 0) return diferenca < 0 ? [a, b] : [b, a];
  return a.id < b.id ? [a, b] : [b, a];
}

/** O serviço. Obtém-se por `Identidade.arrancar`, que recusa chaves de ambiente em `prod`. */
export class Identidade {
  readonly #chaves: KeyProvider;
  readonly #agora: () => Date;
  readonly #ganchos = new Set<GanchoDeFusao>();

  private constructor(chaves: KeyProvider, agora: () => Date) {
    this.#chaves = chaves;
    this.#agora = agora;
  }

  /**
   * Arranca o serviço, ou recusa.
   *
   * @throws {KeyProviderDeAmbienteError} em `KAMBA_ENV=prod` com chaves de ambiente.
   * @throws {AmbienteDeIdentidadeError} se `KAMBA_ENV` faltar ou não bater com o provedor.
   */
  static async arrancar(opcoes: OpcoesDeIdentidade): Promise<Identidade> {
    exigirKeyProviderDeCofre(opcoes.chaves, opcoes.env ?? process.env);
    return new Identidade(opcoes.chaves, opcoes.agora ?? (() => new Date()));
  }

  /**
   * Regista um gancho de fusão. Devolve a função que o retira.
   *
   * `conversations` (KAM-014) e os *checkpoints* (KAM-026) registam aqui o que
   * migra os seus dados para o contacto que fica.
   */
  onContactMerge(gancho: GanchoDeFusao): () => void {
    this.#ganchos.add(gancho);
    return () => {
      this.#ganchos.delete(gancho);
    };
  }

  /**
   * `sujeito_ref` de um contacto numa época (`YYYYMM`): 16 octetos.
   *
   * Determinístico dentro da época; entre épocas a chave é outra.
   */
  async sujeitoRef(contactId: string, epoca: string): Promise<Buffer> {
    if (!epocaValida(epoca)) throw new EpocaInvalidaError();
    const canonico = normalizarUuid(contactId, "contact_id");
    return sujeitoRefDe(await this.#chaves.getEpochKey(epoca), canonico);
  }

  /**
   * BSUID e/ou telefone → `contact_id`. Idempotente.
   *
   * Uma transacção por chamada. Uma corrida entre dois pedidos pelo mesmo
   * contacto novo resolve-se repetindo: o segundo encontra o que o primeiro criou.
   */
  async resolveContact(
    cliente: ClienteDeIdentidade,
    pedido: PedidoDeResolucao,
  ): Promise<ContactoResolvido> {
    const tenant = normalizarTenant(pedido.tenantId);
    const bsuid =
      pedido.bsuid === undefined || pedido.bsuid === null ? null : normalizarBsuid(pedido.bsuid);
    const telefone =
      pedido.telefone === undefined || pedido.telefone === null
        ? null
        : normalizarTelefone(pedido.telefone);
    if (bsuid === null && telefone === null) throw new PedidoSemIdentificadorError();
    const guardar = this.#validarRetencao(pedido, telefone);

    const resolvido = await this.#comRepeticao(() =>
      comTenant(cliente, tenant, () => this.#resolver(cliente, tenant, bsuid, telefone, guardar)),
    );
    CONTADORES_DE_IDENTIDADE.incrementar(`${METRICA_RESOLVER}:${resolvido.desfecho}`);
    return resolvido;
  }

  /**
   * Apaga um contacto a pedido do titular (*crypto-shredding*). Idempotente.
   *
   * Apaga os endpoints, destrói as DEK e o HMAC do telefone, e data o
   * apagamento. O `contact_id` fica — as encomendas e o *ledger* referem-no — mas
   * deixa de ser alguém: nada o liga a um BSUID ou a um número, e o mesmo BSUID
   * volta a resolver para um contacto **novo**.
   *
   * Se o contacto pedido foi absorvido numa fusão, apaga-se quem o absorveu: o
   * titular é a mesma pessoa.
   */
  async eraseContact(
    cliente: ClienteDeIdentidade,
    tenantId: string,
    contactId: string,
  ): Promise<ResultadoDoApagamento> {
    const tenant = normalizarTenant(tenantId);
    const pedido = normalizarUuid(contactId, "contact_id");
    const resultado = await this.#comRepeticao(() =>
      comTenant(cliente, tenant, async () => {
        const alvo = await this.#trancarVivo(cliente, tenant, pedido);
        if (alvo.erasedAt !== null) {
          return {
            contactId: alvo.id,
            jaApagado: true,
            endpointsApagados: 0,
            deksDestruidas: 0,
            apagadoEm: alvo.erasedAt,
          };
        }
        const endpointsApagados = await executar(cliente, SQL.APAGAR_ENDPOINTS, [tenant, alvo.id]);
        const deksDestruidas = await executar(cliente, SQL.DESTRUIR_DEKS, [tenant, alvo.id]);
        const [marcado] = await consultar(cliente, SQL.MARCAR_APAGADO, [tenant, alvo.id]);
        if (marcado === undefined) throw new Repetir();
        return {
          contactId: alvo.id,
          jaApagado: false,
          endpointsApagados,
          deksDestruidas,
          apagadoEm: instante(marcado, "erased_at"),
        };
      }),
    );
    if (!resultado.jaApagado) CONTADORES_DE_IDENTIDADE.incrementar(METRICA_APAGAR);
    return resultado;
  }

  /**
   * Decifra os endpoints de um contacto, **em memória**, para quem tem de enviar.
   *
   * O resultado não se guarda nem se regista (`docs/tecnica/01` §6.3, ponto 5).
   *
   * @throws {ContactoApagadoError} se o contacto foi apagado.
   * @throws {DekDestruidaError} se há cifra mas a chave de dados já não existe.
   */
  async lerEndpoints(
    cliente: ClienteDeIdentidade,
    tenantId: string,
    contactId: string,
  ): Promise<EndpointsDoContacto> {
    const tenant = normalizarTenant(tenantId);
    const pedido = normalizarUuid(contactId, "contact_id");
    const lidos = await comTenant(cliente, tenant, async () => {
      const alvo = await this.#seguirFusoes(cliente, tenant, pedido);
      const linhas = await consultar(cliente, SQL.ENDPOINTS_DO_CONTACTO, [tenant, alvo.id]);
      if (linhas.some((linha) => linha.wrapped_dek === null)) throw new DekDestruidaError();
      if (alvo.erasedAt !== null) throw new ContactoApagadoError();

      const deks = new Map<string, Uint8Array>();
      const bsuids: string[] = [];
      const telefones: { finalidade: Finalidade; telefone: string; expiraAt: Date }[] = [];
      try {
        for (const linha of linhas) {
          const dekId = texto(linha, "dek_id");
          let dek = deks.get(dekId);
          if (dek === undefined) {
            dek = await this.#chaves.unwrapDek(
              octetos(linha, "wrapped_dek"),
              texto(linha, "kek_id"),
              contextoDoEmbrulho(tenant, dekId),
            );
            deks.set(dekId, dek);
          }
          if (texto(linha, "tipo") === "bsuid") {
            bsuids.push(this.#abrir(dek, linha, "bsuid_enc", tenant, dekId));
          } else {
            telefones.push({
              finalidade: texto(linha, "finalidade") as Finalidade,
              telefone: this.#abrir(dek, linha, "phone_enc", tenant, dekId),
              expiraAt: instante(linha, "expira_at"),
            });
          }
        }
      } finally {
        for (const dek of deks.values()) dek.fill(0);
      }
      return { contactId: alvo.id, bsuids, telefones };
    });
    CONTADORES_DE_IDENTIDADE.incrementar(METRICA_LER);
    return lidos;
  }

  /**
   * Regista `kid` como a versão actual da chave de pesquisa. Idempotente.
   *
   * A que era actual passa a anterior, e a pesquisa passa a tentar as duas. A
   * chave tem de **já existir no cofre**: trocar a versão actual por uma que o
   * cofre não serve parava todas as resoluções.
   *
   * Sem contexto de tenant: `hmac_key_versions` é global.
   */
  async iniciarRotacao(
    cliente: ClienteDeIdentidade,
    kid: string,
  ): Promise<ResultadoDeIniciarRotacao> {
    if (!kidValido(kid)) throw new KidInvalidoError();
    await this.#chaves.getLookupKey(kid);
    return this.#comRepeticao(() =>
      emTransaccao(cliente, async () => {
        const vivos = await consultar(cliente, SQL.KIDS_VIVOS_TRANCADOS);
        const actual = vivos.find((linha) => linha.estado === "actual");
        const anterior = vivos.find((linha) => linha.estado === "anterior");
        if (actual !== undefined && texto(actual, "kid") === kid) {
          return {
            kid,
            alterado: false,
            anterior: anterior === undefined ? null : texto(anterior, "kid"),
          };
        }
        if (anterior !== undefined) throw new RotacaoEmCursoError(texto(anterior, "kid"));
        const existente = await consultar(cliente, SQL.ESTADO_DO_KID, [kid]);
        if (existente.length > 0) throw new KidReutilizadoError(kid);
        if (actual !== undefined) await executar(cliente, SQL.DESPROMOVER_ACTUAL);
        await executar(cliente, SQL.REGISTAR_ACTUAL, [kid]);
        return { kid, alterado: true, anterior: actual === undefined ? null : texto(actual, "kid") };
      }),
    );
  }

  /**
   * Retira a versão anterior: a pesquisa deixa de a tentar. Idempotente.
   *
   * **Não confere** que já não há linhas sob essa versão: este papel não vê mais
   * do que um tenant de cada vez. Quem chama (o *job* do KAM-072) corre
   * `rekeyLookup` em todos os tenants e só depois conclui. Devolve o `kid`
   * retirado, ou `null` se não havia nenhum.
   */
  async concluirRotacao(cliente: ClienteDeIdentidade): Promise<string | null> {
    return emTransaccao(cliente, async () => {
      const [retirada] = await consultar(cliente, SQL.RETIRAR_ANTERIOR);
      return retirada === undefined ? null : texto(retirada, "kid");
    });
  }

  /**
   * Recalcula, para um tenant, os HMAC de pesquisa sob a versão `kid`.
   *
   * O HMAC de um BSUID recalcula-se a partir de `bsuid_enc`: não é preciso a
   * chave antiga, nem que o utilizador volte a escrever. Trabalha por lotes, uma
   * transacção por lote, e selecciona sempre «o que ainda não está sob `kid`» —
   * por isso é **retomável** (uma interrupção perde, no máximo, o lote em curso)
   * e **idempotente** (correr outra vez sobre um tenant completo não muda nada).
   */
  async rekeyLookup(
    cliente: ClienteDeIdentidade,
    tenantId: string,
    kid: string,
    opcoes: OpcoesDeRotacao = {},
  ): Promise<ResultadoDaRotacao> {
    const tenant = normalizarTenant(tenantId);
    if (!kidValido(kid)) throw new KidInvalidoError();
    const lote = opcoes.lote ?? LOTE_DE_ROTACAO;
    if (!Number.isInteger(lote) || lote < 1 || lote > LOTE_MAXIMO) {
      throw new RangeError(`o lote tem de ser um inteiro entre 1 e ${LOTE_MAXIMO}`);
    }
    const maximo = opcoes.maximoDeLotes ?? Number.POSITIVE_INFINITY;
    if (!(maximo >= 1)) throw new RangeError("maximoDeLotes tem de ser pelo menos 1");
    const largar = opcoes.telefonesSemCifra === "largar";
    const chave = await this.#chaves.getLookupKey(kid);

    let lotes = 0;
    let bsuidsRodados = 0;
    let telefonesRodados = 0;
    let telefonesLargados = 0;

    let acabou = false;
    while (!acabou && lotes < maximo) {
      const feitos = await comTenant(cliente, tenant, async () => {
        await this.#exigirActual(cliente, kid);
        const linhas = await consultar(cliente, SQL.BSUID_POR_RODAR, [tenant, kid, lote]);
        const deks = new Map<string, Uint8Array>();
        try {
          for (const linha of linhas) {
            const dek = await this.#dekDaLinha(deks, linha, tenant);
            const bsuid = this.#abrir(dek, linha, "bsuid_enc", tenant, texto(linha, "dek_id"));
            await executar(cliente, SQL.ACTUALIZAR_HMAC_DO_BSUID, [
              tenant,
              texto(linha, "id"),
              hmacDePesquisa(chave, tenant, "bsuid", bsuid),
              kid,
            ]);
          }
        } finally {
          for (const dek of deks.values()) dek.fill(0);
        }
        return linhas.length;
      });
      lotes += 1;
      bsuidsRodados += feitos;
      acabou = feitos < lote;
    }

    let cursor = UUID_ZERO;
    let acabaramOsTelefones = !acabou;
    while (!acabaramOsTelefones && lotes < maximo) {
      const passo = await comTenant(cliente, tenant, async () => {
        await this.#exigirActual(cliente, kid);
        const linhas = await consultar(cliente, SQL.TELEFONES_POR_RODAR, [
          tenant,
          kid,
          lote,
          cursor,
        ]);
        let rodados = 0;
        let largados = 0;
        let ultimo = cursor;
        for (const linha of linhas) {
          const contacto = texto(linha, "contact_id");
          ultimo = contacto;
          const [cifra] = await consultar(cliente, SQL.CIFRA_DO_TELEFONE, [tenant, contacto]);
          if (cifra !== undefined) {
            const dekId = texto(cifra, "dek_id");
            const dek = await this.#chaves.unwrapDek(
              octetos(cifra, "wrapped_dek"),
              texto(cifra, "kek_id"),
              contextoDoEmbrulho(tenant, dekId),
            );
            try {
              const telefone = this.#abrir(dek, cifra, "phone_enc", tenant, dekId);
              await executar(cliente, SQL.DEFINIR_TELEFONE, [
                tenant,
                contacto,
                hmacDePesquisa(chave, tenant, "telefone", telefone),
                kid,
              ]);
            } finally {
              dek.fill(0);
            }
            rodados += 1;
          } else if (largar) {
            await executar(cliente, SQL.LIMPAR_TELEFONE, [tenant, contacto]);
            largados += 1;
          }
        }
        return { vistos: linhas.length, rodados, largados, ultimo };
      });
      lotes += 1;
      telefonesRodados += passo.rodados;
      telefonesLargados += passo.largados;
      cursor = passo.ultimo;
      acabaramOsTelefones = passo.vistos < lote;
    }

    const porRodar = await comTenant(cliente, tenant, async () => {
      const [contagem] = await consultar(cliente, SQL.CONTAR_POR_RODAR, [tenant, kid]);
      if (contagem === undefined) throw new ClienteInvalidoError("a contagem veio vazia");
      return {
        bsuids: Number(contagem.bsuids),
        telefones: Number(contagem.telefones),
      };
    });
    for (let i = 0; i < bsuidsRodados + telefonesRodados; i += 1) {
      CONTADORES_DE_IDENTIDADE.incrementar(METRICA_RODAR);
    }
    return {
      kid,
      bsuidsRodados,
      telefonesRodados,
      telefonesLargados,
      porRodar,
      completo: porRodar.bsuids === 0 && porRodar.telefones === 0,
      lotes,
    };
  }

  // --------------------------------------------------------------- interno

  #validarRetencao(
    pedido: PedidoDeResolucao,
    telefone: string | null,
  ): { finalidade: Finalidade; expiraAt: Date } | null {
    const guardar = pedido.guardarTelefone;
    if (guardar === undefined) return null;
    if (telefone === null) throw new RetencaoInvalidaError("não há telefone no pedido");
    if (!FINALIDADES.includes(guardar.finalidade)) {
      throw new RetencaoInvalidaError("a finalidade não é uma das previstas");
    }
    const expira = guardar.expiraAt;
    if (!(expira instanceof Date) || Number.isNaN(expira.getTime())) {
      throw new RetencaoInvalidaError("o prazo não é uma data");
    }
    if (expira.getTime() <= this.#agora().getTime()) {
      throw new RetencaoInvalidaError("o prazo já passou");
    }
    return { finalidade: guardar.finalidade, expiraAt: expira };
  }

  async #comRepeticao<T>(operacao: () => Promise<T>): Promise<T> {
    for (let tentativa = 1; ; tentativa += 1) {
      try {
        return await operacao();
      } catch (erro) {
        if (!repetivel(erro)) throw erro;
        if (tentativa >= TENTATIVAS) {
          if (erro instanceof Repetir) {
            throw new IdentidadeInconsistenteError(
              `a operação não estabilizou em ${TENTATIVAS} tentativas`,
            );
          }
          throw erro;
        }
        CONTADORES_DE_IDENTIDADE.incrementar(METRICA_REPETICOES);
      }
    }
  }

  async #kidsVivos(cliente: ClienteDeIdentidade): Promise<KidsVivos> {
    let linhas = await consultar(cliente, SQL.KIDS_VIVOS);
    if (!linhas.some((linha) => linha.estado === "actual")) {
      // Se esta leitura esteve à espera de uma rotação, o que ela devolve é a
      // versão que **era** a actual, já como anterior — a nova nasceu depois
      // do instantâneo. Lê-se outra vez, agora com a rotação confirmada.
      linhas = await consultar(cliente, SQL.KIDS_VIVOS);
    }
    const actual = linhas.find((linha) => linha.estado === "actual");
    const anterior = linhas.find((linha) => linha.estado === "anterior");
    if (actual === undefined) throw new SemChaveActualError();
    return {
      actual: texto(actual, "kid"),
      anterior: anterior === undefined ? null : texto(anterior, "kid"),
    };
  }

  async #exigirActual(cliente: ClienteDeIdentidade, kid: string): Promise<void> {
    const [linha] = await consultar(cliente, SQL.ESTADO_DO_KID, [kid]);
    if (linha === undefined || linha.estado !== "actual") throw new KidNaoActualError(kid);
  }

  /** Tranca os contactos pedidos e devolve o estado de cada um, por `contact_id`. */
  async #trancar(
    cliente: ClienteDeIdentidade,
    tenant: string,
    ids: readonly string[],
  ): Promise<Map<string, EstadoDoContacto>> {
    const estados = new Map<string, EstadoDoContacto>();
    if (ids.length === 0) return estados;
    const ordenados = [...new Set(ids)].sort();
    for (const linha of await consultar(cliente, SQL.TRANCAR_CONTACTOS, [tenant, ordenados])) {
      const estado = estadoDe(linha);
      estados.set(estado.id, estado);
    }
    return estados;
  }

  /** O contacto pedido, ou quem o absorveu, **trancado**. */
  async #trancarVivo(
    cliente: ClienteDeIdentidade,
    tenant: string,
    contactId: string,
  ): Promise<EstadoDoContacto> {
    let procurado = contactId;
    for (let salto = 0; salto < CADEIA_MAXIMA; salto += 1) {
      const estado = (await this.#trancar(cliente, tenant, [procurado])).get(procurado);
      if (estado === undefined) throw new ContactoDesconhecidoError();
      if (estado.mergedInto === null) return estado;
      procurado = estado.mergedInto;
    }
    throw new IdentidadeInconsistenteError("cadeia de fusões demasiado longa");
  }

  /** O contacto pedido, ou quem o absorveu, sem trancar. */
  async #seguirFusoes(
    cliente: ClienteDeIdentidade,
    tenant: string,
    contactId: string,
  ): Promise<{ id: string; erasedAt: Date | null }> {
    let procurado = contactId;
    for (let salto = 0; salto < CADEIA_MAXIMA; salto += 1) {
      const [linha] = await consultar(cliente, SQL.CONTACTO, [tenant, procurado]);
      if (linha === undefined) throw new ContactoDesconhecidoError();
      const para = textoOuNulo(linha, "merged_into");
      if (para === null) {
        return { id: texto(linha, "contact_id"), erasedAt: instanteOuNulo(linha, "erased_at") };
      }
      procurado = para;
    }
    throw new IdentidadeInconsistenteError("cadeia de fusões demasiado longa");
  }

  #abrir(
    dek: Uint8Array,
    linha: Linha,
    campo: CampoCifrado,
    tenant: string,
    dekId: string,
  ): string {
    return decifrar(dek, octetos(linha, campo), contextoDaCifra(tenant, dekId, campo));
  }

  async #dekDaLinha(
    deks: Map<string, Uint8Array>,
    linha: Linha,
    tenant: string,
  ): Promise<Uint8Array> {
    const dekId = texto(linha, "dek_id");
    const conhecida = deks.get(dekId);
    if (conhecida !== undefined) return conhecida;
    if (linha.wrapped_dek === null) throw new DekDestruidaError();
    const dek = await this.#chaves.unwrapDek(
      octetos(linha, "wrapped_dek"),
      texto(linha, "kek_id"),
      contextoDoEmbrulho(tenant, dekId),
    );
    deks.set(dekId, dek);
    return dek;
  }

  /** A DEK viva do contacto; cria-a se ainda não tiver nenhuma. */
  async #dekDoContacto(
    cliente: ClienteDeIdentidade,
    tenant: string,
    contactId: string,
  ): Promise<{ dekId: string; dek: Uint8Array }> {
    const [viva] = await consultar(cliente, SQL.DEK_VIVA, [tenant, contactId]);
    if (viva !== undefined) {
      const dekId = texto(viva, "dek_id");
      const dek = await this.#chaves.unwrapDek(
        octetos(viva, "wrapped_dek"),
        texto(viva, "kek_id"),
        contextoDoEmbrulho(tenant, dekId),
      );
      return { dekId, dek };
    }
    const dekId = randomUUID();
    const dek = novaDek();
    const { embrulho, kekId } = await this.#chaves.wrapDek(dek, contextoDoEmbrulho(tenant, dekId));
    await executar(cliente, SQL.CRIAR_DEK, [
      dekId,
      tenant,
      contactId,
      Buffer.from(embrulho),
      kekId,
    ]);
    return { dekId, dek };
  }

  async #resolver(
    cliente: ClienteDeIdentidade,
    tenant: string,
    bsuid: string | null,
    telefone: string | null,
    guardar: { finalidade: Finalidade; expiraAt: Date } | null,
  ): Promise<ContactoResolvido> {
    const kids = await this.#kidsVivos(cliente);
    const chaveActual = await this.#chaves.getLookupKey(kids.actual);
    const chaveAnterior =
      kids.anterior === null ? null : await this.#chaves.getLookupKey(kids.anterior);

    // --- 1. e 2. Pesquisar, sob a chave actual e sob a anterior.
    const hmacDoBsuid = bsuid === null ? null : hmacDePesquisa(chaveActual, tenant, "bsuid", bsuid);
    const hmacDoTelefone =
      telefone === null ? null : hmacDePesquisa(chaveActual, tenant, "telefone", telefone);
    const hmacAnteriorDoTelefone =
      telefone === null || chaveAnterior === null
        ? null
        : hmacDePesquisa(chaveAnterior, tenant, "telefone", telefone);

    let endpoint: { id: string; contacto: string; kid: string } | null = null;
    if (bsuid !== null) {
      const linhas = await consultar(cliente, SQL.ENDPOINT_POR_BSUID, [
        tenant,
        kids.actual,
        hmacDoBsuid,
        kids.anterior,
        chaveAnterior === null ? null : hmacDePesquisa(chaveAnterior, tenant, "bsuid", bsuid),
      ]);
      if (new Set(linhas.map((linha) => texto(linha, "contact_id"))).size > 1) {
        throw new IdentidadeInconsistenteError("o mesmo BSUID resolve para dois contactos");
      }
      const preferida =
        linhas.find((linha) => linha.hmac_kid === kids.actual) ?? linhas[0];
      if (preferida !== undefined) {
        endpoint = {
          id: texto(preferida, "id"),
          contacto: texto(preferida, "contact_id"),
          kid: texto(preferida, "hmac_kid"),
        };
      }
    }

    let doTelefone: string | null = null;
    if (telefone !== null) {
      const linhas = await consultar(cliente, SQL.CONTACTO_POR_TELEFONE, [
        tenant,
        kids.actual,
        hmacDoTelefone,
        kids.anterior,
        hmacAnteriorDoTelefone,
      ]);
      if (new Set(linhas.map((linha) => texto(linha, "contact_id"))).size > 1) {
        throw new IdentidadeInconsistenteError("o mesmo telefone resolve para dois contactos");
      }
      const [encontrada] = linhas;
      if (encontrada !== undefined) doTelefone = texto(encontrada, "contact_id");
    }

    // --- Trancar o que se encontrou, e confirmar que continua a ser verdade.
    const encontrados = [endpoint?.contacto, doTelefone].filter(
      (id): id is string => typeof id === "string",
    );
    const estados = await this.#trancar(cliente, tenant, encontrados);
    for (const id of encontrados) {
      const estado = estados.get(id);
      if (estado === undefined || estado.erasedAt !== null || estado.mergedInto !== null) {
        // Apagado ou fundido entre a pesquisa e a tranca: a pesquisa já não vale.
        throw new Repetir();
      }
    }
    const a = endpoint === null ? null : (estados.get(endpoint.contacto) ?? null);
    const p = doTelefone === null ? null : (estados.get(doTelefone) ?? null);
    if (
      p !== null &&
      !(
        (p.hmacKid === kids.actual && iguais(p.phoneHmac, hmacDoTelefone)) ||
        (p.hmacKid === kids.anterior && iguais(p.phoneHmac, hmacAnteriorDoTelefone))
      )
    ) {
      // O contacto perdeu ou trocou de número entre a pesquisa e a tranca.
      throw new Repetir();
    }

    // --- 3. Decidir.
    let contacto: string;
    let desfecho: Desfecho;
    let evento: EventoContactMerged | null = null;
    /** O HMAC de telefone que `contacto` tem neste momento da transacção. */
    let telefoneDoContacto: { hmac: Buffer; kid: string } | null = null;
    const telefoneDe = (estado: EstadoDoContacto): { hmac: Buffer; kid: string } | null =>
      estado.phoneHmac === null || estado.hmacKid === null
        ? null
        : { hmac: estado.phoneHmac, kid: estado.hmacKid };

    if (a !== null && p !== null && a.id !== p.id) {
      const outraPessoa =
        (await consultar(cliente, SQL.TEM_BSUID, [tenant, p.id])).length > 0;
      if (outraPessoa) {
        // O número mudou de mãos: quem o tinha perde-o, e nada mais se toca.
        await this.#tirarTelefone(cliente, tenant, p.id);
        contacto = a.id;
        desfecho = "existente";
        telefoneDoContacto = telefoneDe(a);
      } else {
        evento = await this.#fundir(cliente, tenant, a, p);
        contacto = evento.payload.contact_id;
        desfecho = "fundido";
        // Quem fica, fica com o telefone que estava em `p` — tal como estava.
        telefoneDoContacto = telefoneDe(p);
      }
    } else if (a !== null) {
      contacto = a.id;
      desfecho = "existente";
      telefoneDoContacto = telefoneDe(a);
    } else if (p !== null) {
      if (bsuid === null) {
        contacto = p.id;
        desfecho = "existente";
        telefoneDoContacto = telefoneDe(p);
      } else if ((await consultar(cliente, SQL.TEM_BSUID, [tenant, p.id])).length > 0) {
        // Outro BSUID com este número: outra pessoa. O antigo titular perde-o.
        await this.#tirarTelefone(cliente, tenant, p.id);
        contacto = await this.#criar(cliente, tenant);
        desfecho = "criado";
      } else {
        // Um contacto só-telefone recebe o seu BSUID: completa-se.
        contacto = p.id;
        desfecho = "completado";
        telefoneDoContacto = telefoneDe(p);
      }
    } else {
      contacto = await this.#criar(cliente, tenant);
      desfecho = "criado";
    }

    // --- O BSUID: criar o endpoint que falta, ou subi-lo para a chave actual.
    if (bsuid !== null && hmacDoBsuid !== null) {
      if (endpoint === null) {
        const { dekId, dek } = await this.#dekDoContacto(cliente, tenant, contacto);
        try {
          await executar(cliente, SQL.CRIAR_ENDPOINT_BSUID, [
            tenant,
            contacto,
            hmacDoBsuid,
            kids.actual,
            cifrar(dek, bsuid, contextoDaCifra(tenant, dekId, "bsuid_enc")),
            dekId,
          ]);
        } finally {
          dek.fill(0);
        }
      } else if (endpoint.kid !== kids.actual) {
        await executar(cliente, SQL.ACTUALIZAR_HMAC_DO_BSUID, [
          tenant,
          endpoint.id,
          hmacDoBsuid,
          kids.actual,
        ]);
      }
    }

    // --- O telefone: o contacto fica com o HMAC do número que trouxe, sob a
    // chave actual. Se tinha outro número, esse deixou de ser dele: vai o HMAC e
    // vai a cifra que houvesse.
    if (telefone !== null && hmacDoTelefone !== null) {
      const jaTem =
        telefoneDoContacto !== null &&
        telefoneDoContacto.kid === kids.actual &&
        iguais(telefoneDoContacto.hmac, hmacDoTelefone);
      if (!jaTem) {
        const eOMesmoNumero =
          telefoneDoContacto !== null &&
          hmacAnteriorDoTelefone !== null &&
          telefoneDoContacto.kid === kids.anterior &&
          iguais(telefoneDoContacto.hmac, hmacAnteriorDoTelefone);
        if (telefoneDoContacto !== null && !eOMesmoNumero) {
          await executar(cliente, SQL.APAGAR_TELEFONES, [tenant, contacto]);
        }
        await executar(cliente, SQL.DEFINIR_TELEFONE, [
          tenant,
          contacto,
          hmacDoTelefone,
          kids.actual,
        ]);
      }
      if (guardar !== null) {
        const { dekId, dek } = await this.#dekDoContacto(cliente, tenant, contacto);
        try {
          await executar(cliente, SQL.GUARDAR_TELEFONE, [
            tenant,
            contacto,
            cifrar(dek, telefone, contextoDaCifra(tenant, dekId, "phone_enc")),
            dekId,
            guardar.finalidade,
            guardar.expiraAt,
          ]);
        } finally {
          dek.fill(0);
        }
      }
    }

    return { tenantId: tenant, contactId: contacto, desfecho, evento };
  }

  async #criar(cliente: ClienteDeIdentidade, tenant: string): Promise<string> {
    const [criado] = await consultar(cliente, SQL.CRIAR_CONTACTO, [tenant, null, null]);
    if (criado === undefined) throw new ClienteInvalidoError("o INSERT não devolveu o contacto");
    return texto(criado, "contact_id");
  }

  /** O contacto deixa de ter este número: vai o HMAC e vai a cifra. */
  async #tirarTelefone(
    cliente: ClienteDeIdentidade,
    tenant: string,
    contactId: string,
  ): Promise<void> {
    await executar(cliente, SQL.APAGAR_TELEFONES, [tenant, contactId]);
    await executar(cliente, SQL.LIMPAR_TELEFONE, [tenant, contactId]);
  }

  /**
   * Funde `a` (encontrado pelo BSUID) com `p` (encontrado pelo telefone, e sem BSUID).
   *
   * Tudo na transacção de quem chama: se um gancho falhar, nada disto fica.
   */
  async #fundir(
    cliente: ClienteDeIdentidade,
    tenant: string,
    a: EstadoDoContacto,
    p: EstadoDoContacto,
  ): Promise<EventoContactMerged> {
    const [fica, sai] = maisAntigoPrimeiro(a, p);
    // O número que `a` tivesse não é o deste pedido (esse está em `p`): deixou
    // de ser dele, e a cifra que houvesse não pode seguir para quem fica.
    if (a.phoneHmac !== null) await this.#tirarTelefone(cliente, tenant, a.id);
    await executar(cliente, SQL.MOVER_ENDPOINTS, [tenant, sai.id, fica.id]);
    await executar(cliente, SQL.MOVER_DEKS, [tenant, sai.id, fica.id]);
    const [lapide] = await consultar(cliente, SQL.MARCAR_FUNDIDO, [tenant, sai.id, fica.id]);
    if (lapide === undefined) throw new Repetir();
    if (sai.id === p.id && p.phoneHmac !== null && p.hmacKid !== null) {
      // O telefone estava no absorvido: passa, tal como está, para quem fica.
      await executar(cliente, SQL.DEFINIR_TELEFONE, [tenant, fica.id, p.phoneHmac, p.hmacKid]);
    }
    for (const gancho of this.#ganchos) {
      await gancho({ cliente, tenantId: tenant, de: sai.id, para: fica.id });
    }
    return {
      tipo: "contact.merged",
      tenant_id: tenant,
      ocorrido_em: instante(lapide, "merged_at").toISOString(),
      payload: { contact_id: fica.id, merged_contact_id: sai.id },
    };
  }
}

/** Uma transacção sem contexto de tenant, para a tabela global de versões de chave. */
async function emTransaccao<T>(cliente: ClienteDeIdentidade, trabalho: () => Promise<T>): Promise<T> {
  const forma = cliente as unknown as Record<string, unknown>;
  if (
    typeof forma.totalCount === "number" ||
    typeof forma.idleCount === "number" ||
    typeof forma.waitingCount === "number"
  ) {
    throw new ClienteInvalidoError("parece um pool, e não uma ligação");
  }
  await cliente.query("BEGIN");
  try {
    const resultado = await trabalho();
    await cliente.query("COMMIT");
    return resultado;
  } catch (erro) {
    try {
      await cliente.query("ROLLBACK");
    } catch {
      // O erro que interessa a quem chama é o primeiro.
    }
    throw erro;
  }
}
