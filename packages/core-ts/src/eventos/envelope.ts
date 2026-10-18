/**
 * Envelope de evento v1 — forma, leitura e validação (KAM-005, ADR-009).
 *
 * O envelope **constrói-se em SQL**, dentro de `platform.evt_emitir`, na mesma
 * transacção que o dado (`docs/tecnica/06` §6.1). Este módulo não o constrói: se
 * o construísse, haveria duas fontes para a mesma forma e divergiriam no
 * primeiro campo novo — foi exactamente esse o defeito que o dicionário
 * canónico existe para evitar. O que este módulo faz é **ler** e **recusar**:
 *
 *     lerEnvelope(linha.envelope)   →  Envelope, ou lança
 *
 * Porque é que a leitura precisa de validação, se foi a base que escreveu: o
 * `events_outbox.envelope` é `jsonb` e um `INSERT` directo — por `kamba_batch`,
 * por uma migração, por um *replay* operacional — não passa por `evt_emitir`.
 * O publicador é o último sítio antes de o envelope sair para fora da base, e
 * **falha fechada**: um envelope que não se reconhece não se publica.
 *
 * ## Os catorze campos, e a dúvida que ficou fechada
 *
 * O dicionário §3.5 («Envelope») nomeava nove: `id`, `tipo`, `versao`,
 * `tenant_id`, `agregado`, `seq`, `trace_id`, `ocorrido_em`, `payload`. O
 * `jsonb_build_object` de `docs/tecnica/06` §6.1 escreve **catorze** chaves de
 * topo e põe o `seq` **dentro** de `agregado`. A emenda 1.9 acrescentou os seis
 * que faltavam (`registado_em`, `produtor`, `correlacao_id`, `causa_id`,
 * `classe_pii`, `finalidades`) e deixou em aberto se o contrato v1 publicado
 * teria nove ou catorze.
 *
 * **A emenda 1.11 (KAM-007) fechou-a em catorze, e não por preferência:** um
 * `v1.schema.json` com `additionalProperties: false` e nove campos de topo
 * recusava todos os envelopes reais. Os contratos de `contratos/eventos/` têm
 * exactamente esta lista.
 *
 * ## Privacidade
 *
 * Nada de PII P2 no envelope: a referência a uma pessoa é `contact_id` e mais
 * nada (ADR-010, `docs/tecnica/06` §7.1). A guarda de nomes de campo está em
 * `pii.ts` e corre sobre o `payload` inteiro; o *lint* dos **schemas** de
 * evento é o KAM-007.
 */

/** Classe de dado pessoal do envelope (`docs/tecnica/06` §7.1). */
export const CLASSES_PII = ["P0", "P1", "P2"] as const;
export type ClassePii = (typeof CLASSES_PII)[number];

/**
 * Finalidades de uso (`consent_event.purpose`, dicionário §3.1, emenda 1.16).
 *
 * Lista fechada: o roteamento do publicador compara a `finalidade` de uma
 * subscrição com estas, e uma finalidade que não esteja aqui nunca recebe
 * nada — o que é o comportamento certo (falha fechada), mas tem de ser dito.
 *
 * **São dez desde o KAM-159**, e são a união de duas listas que existiam e se
 * cruzavam numa só. As duas últimas vêm do dicionário e eram, até aqui,
 * **impossíveis de emitir**: o `enum` dos contratos era fechado e não as
 * tinha. Entram com a `v2` dos 38 contratos.
 *
 * A ordem é a do dicionário, e isso importa: um gate compara esta lista com o
 * domínio canónico, e a comparação é de conjuntos — mas quem lê compara à
 * vista.
 */
export const FINALIDADES = [
  "transacao",
  "atendimento",
  "marketing",
  "analytics_agregado",
  "melhoria_servico",
  "sugestoes_patrocinadas",
  "partilha_loja",
  "partilha_parceiros",
  "partilha_estafeta",
  "notificacao_dono",
] as const;

/**
 * As que só a `v2` do envelope aceita (KAM-159).
 *
 * Um envelope `v2` que as use **não se consegue representar** numa `v1`: o
 * `enum` da `v1` não as tem. É o que o conversor de versão usa para recusar
 * em vez de as deitar fora — ver `conversor.ts`.
 */
export const FINALIDADES_SO_NA_V2 = [
  "partilha_estafeta",
  "notificacao_dono",
] as const;
export type Finalidade = (typeof FINALIDADES)[number];

/** O agregado a que o evento pertence. A ordem causal é o `seq`. */
export interface Agregado {
  readonly tipo: string;
  readonly id: string;
  readonly seq: number;
}

/** Envelope v1. Os **catorze** campos de topo do `docs/tecnica/06` §6.1. */
export interface Envelope {
  readonly id: string;
  readonly tipo: string;
  readonly versao: number;
  readonly tenant_id: string;
  readonly ocorrido_em: string;
  readonly registado_em: string;
  readonly produtor: string | null;
  readonly agregado: Agregado;
  readonly correlacao_id: string | null;
  readonly causa_id: string | null;
  readonly trace_id: string | null;
  readonly classe_pii: ClassePii;
  readonly finalidades: readonly string[];
  readonly payload: Readonly<Record<string, unknown>>;
}

/** Os campos de topo que um envelope v1 tem. Nem um a mais, nem um a menos. */
export const CAMPOS_DO_ENVELOPE = [
  "id",
  "tipo",
  "versao",
  "tenant_id",
  "ocorrido_em",
  "registado_em",
  "produtor",
  "agregado",
  "correlacao_id",
  "causa_id",
  "trace_id",
  "classe_pii",
  "finalidades",
  "payload",
] as const;

/** Um envelope que não se reconhece. Não se publica. */
export class EnvelopeInvalidoError extends Error {
  constructor(motivo: string) {
    super(`envelope invalido: ${motivo}`);
    this.name = "EnvelopeInvalidoError";
  }
}

const UUID_CANONICO =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
/** `familia.verbo`, minúsculas (dicionário §3.5). */
const TIPO_DE_EVENTO = /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/;

function texto(valor: unknown, campo: string): string {
  if (typeof valor !== "string" || valor === "") {
    throw new EnvelopeInvalidoError(`\`${campo}\` tem de ser texto nao vazio`);
  }
  return valor;
}

function textoOuNulo(valor: unknown, campo: string): string | null {
  if (valor === null || valor === undefined) return null;
  return texto(valor, campo);
}

function uuid(valor: unknown, campo: string): string {
  const bruto = texto(valor, campo);
  if (!UUID_CANONICO.test(bruto)) {
    throw new EnvelopeInvalidoError(`\`${campo}\` nao e um UUID canonico`);
  }
  return bruto;
}

function uuidOuNulo(valor: unknown, campo: string): string | null {
  if (valor === null || valor === undefined) return null;
  return uuid(valor, campo);
}

function inteiro(valor: unknown, campo: string, minimo: number): number {
  if (typeof valor !== "number" || !Number.isInteger(valor) || valor < minimo) {
    throw new EnvelopeInvalidoError(
      `\`${campo}\` tem de ser um inteiro >= ${minimo}`,
    );
  }
  return valor;
}

function objecto(valor: unknown, campo: string): Record<string, unknown> {
  if (
    typeof valor !== "object" ||
    valor === null ||
    Array.isArray(valor)
  ) {
    throw new EnvelopeInvalidoError(`\`${campo}\` tem de ser um objecto`);
  }
  return valor as Record<string, unknown>;
}

/**
 * Lê e valida um envelope v1.
 *
 * Aceita o objecto já desserializado (o que o `pg` devolve de uma coluna
 * `jsonb`) ou o texto JSON. Recusa, pela ordem: JSON ilegível, campo de topo
 * desconhecido, campo em falta, tipo errado, `finalidades` vazio ou com um
 * valor que não é texto.
 *
 * **Um campo de topo a mais é recusado**, e não ignorado: um produtor que
 * comece a escrever um campo novo sem subir a `versao` é um contrato quebrado
 * em silêncio, que é precisamente o que o §6.6 proíbe. Campo novo **opcional**
 * mantém a versão — mas opcional quer dizer declarado aqui, não desconhecido.
 */
export function lerEnvelope(valor: unknown): Envelope {
  let cru: unknown = valor;
  if (typeof cru === "string") {
    try {
      cru = JSON.parse(cru);
    } catch {
      throw new EnvelopeInvalidoError("nao e JSON");
    }
  }
  const bruto = objecto(cru, "envelope");

  const conhecidos = new Set<string>(CAMPOS_DO_ENVELOPE);
  const demais = Object.keys(bruto).filter((chave) => !conhecidos.has(chave));
  if (demais.length > 0) {
    throw new EnvelopeInvalidoError(
      `campo(s) de topo desconhecido(s): ${demais.sort().join(", ")}`,
    );
  }

  const agregado = objecto(bruto.agregado, "agregado");
  const classe = texto(bruto.classe_pii, "classe_pii");
  if (!(CLASSES_PII as readonly string[]).includes(classe)) {
    throw new EnvelopeInvalidoError(`\`classe_pii\` desconhecida: ${classe}`);
  }
  if (classe === "P2") {
    throw new EnvelopeInvalidoError(
      "`classe_pii` P2 e proibida no envelope (docs/tecnica/06 §7.1)",
    );
  }

  const finalidades = bruto.finalidades;
  if (!Array.isArray(finalidades) || finalidades.length === 0) {
    throw new EnvelopeInvalidoError("`finalidades` tem de ter ao menos uma");
  }
  const finais = finalidades.map((f, i) => texto(f, `finalidades[${i}]`));

  const tipo = texto(bruto.tipo, "tipo");
  if (!TIPO_DE_EVENTO.test(tipo)) {
    throw new EnvelopeInvalidoError(
      `\`tipo\` tem de ser \`familia.verbo\` em minusculas: ${tipo}`,
    );
  }

  return {
    id: uuid(bruto.id, "id"),
    tipo,
    versao: inteiro(bruto.versao, "versao", 1),
    tenant_id: uuid(bruto.tenant_id, "tenant_id"),
    ocorrido_em: texto(bruto.ocorrido_em, "ocorrido_em"),
    registado_em: texto(bruto.registado_em, "registado_em"),
    produtor: textoOuNulo(bruto.produtor, "produtor"),
    agregado: {
      tipo: texto(agregado.tipo, "agregado.tipo"),
      id: texto(agregado.id, "agregado.id"),
      seq: inteiro(agregado.seq, "agregado.seq", 1),
    },
    correlacao_id: uuidOuNulo(bruto.correlacao_id, "correlacao_id"),
    causa_id: uuidOuNulo(bruto.causa_id, "causa_id"),
    trace_id: textoOuNulo(bruto.trace_id, "trace_id"),
    classe_pii: classe as ClassePii,
    finalidades: finais,
    payload: objecto(bruto.payload, "payload"),
  };
}
