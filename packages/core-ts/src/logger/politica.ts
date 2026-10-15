/**
 * A política de «logs sem conteúdo» (KAM-068, ADR-010, `docs/tecnica/08` §7.3).
 *
 * Este ficheiro é a política; `index.ts` é quem escreve a linha. É o espelho de
 * `libs/py-core/src/kamba_core/logger/politica.py`, e as duas implementações
 * têm de aceitar e recusar **as mesmas coisas**: a paridade confere-se com os
 * vectores de `tests/fixtures/logger_paridade.json`, lidos pelas duas baterias,
 * e com as 1 000 *fixtures* do X-11, cuja saída tem de ser igual byte a byte
 * nas duas linguagens (`make x11`).
 *
 * **Não há redacção parcial.** Um valor ou tem a forma fechada do seu campo, ou
 * o campo é retirado da linha. Não existe campo de texto livre.
 */

import { createHash } from "node:crypto";

/**
 * A *allowlist*, pela ordem em que os campos saem na linha. É **exactamente** a
 * de `docs/tecnica/08` §7.3; acrescentar um campo é um PR revisto pelo
 * Responsável de Segurança (`docs/logs.md` §5).
 */
export const CAMPOS = [
  "ts",
  "level",
  "svc",
  "tenant_id",
  "contact_hmac_prefix",
  "turn_id",
  "msg_id",
  "wa_type",
  "latency_ms",
  "tool",
  "outcome",
  "error_code",
] as const;

/** Campos que o *logger* preenche. Quem chama não os pode dar. */
export const CAMPOS_RESERVADOS = ["ts", "level", "svc"] as const;

/** Campos que quem chama pode dar. */
export const CAMPOS_DE_CHAMADA = [
  "tenant_id",
  "contact_hmac_prefix",
  "turn_id",
  "msg_id",
  "wa_type",
  "latency_ms",
  "tool",
  "outcome",
  "error_code",
] as const;

export const NIVEIS = ["debug", "info", "warn", "error"] as const;

export type Nivel = (typeof NIVEIS)[number];
export type CampoDeChamada = (typeof CAMPOS_DE_CHAMADA)[number];

/**
 * O que uma chamada ao *logger* pode levar. Um campo fora daqui é um **erro de
 * compilação** — ver `Exacto` em `index.ts`, que fecha também o caso do objecto
 * que não é um literal.
 */
export interface CamposDeLog {
  readonly tenant_id?: string;
  readonly contact_hmac_prefix?: string;
  readonly turn_id?: string;
  readonly msg_id?: string;
  readonly wa_type?: string;
  readonly latency_ms?: number;
  readonly tool?: string;
  readonly outcome?: string;
  readonly error_code?: string;
}

/**
 * Tecto de `latency_ms`: oito dígitos (cerca de 27 horas). Um inteiro de nove
 * dígitos começado por 9 tem a forma de um telemóvel angolano.
 */
export const LATENCIA_MAXIMA_MS = 99_999_999;

/**
 * Motivos de rejeição. São o sufixo da métrica, e são **fixos**: o nome do
 * campo recusado nunca entra na métrica, porque um objecto espalhado
 * (`{...corpoDoPedido}`) traz conteúdo nas chaves.
 */
export const MOTIVO_DESCONHECIDO = "campo_desconhecido";
export const MOTIVO_RESERVADO = "campo_reservado";
export const MOTIVO_VALOR = "valor_invalido";
export const MOTIVO_MENSAGEM = "mensagem_livre";
export const MOTIVOS = [
  MOTIVO_DESCONHECIDO,
  MOTIVO_RESERVADO,
  MOTIVO_VALOR,
  MOTIVO_MENSAGEM,
] as const;

/** Campos recusados; o sufixo é o motivo (`log_field_rejected_total:<motivo>`). */
export const METRICA_REJEITADOS = "log_field_rejected_total";
/** Linhas que não se conseguiram escrever no destino. */
export const METRICA_ESCRITA_FALHADA = "log_write_failed_total";

/**
 * Variável de ambiente que liga o modo estrito (o «modo de teste» do ticket):
 * uma rejeição lança em vez de só contar. Nunca em `prod`.
 */
export const VARIAVEL_ESTRITO = "KAMBA_LOG_ESTRITO";

// Todas as formas são ancoradas nas duas pontas. Em Python aplicam-se com
// `fullmatch`, porque lá o `$` aceita um salto de linha no fim.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID_OPACO = /^m_[0-9a-f]{32}$/;
const HMAC_PREFIXO = /^[0-9a-f]{8}$/;
const SVC = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/;

// Um identificador não é «letras, dígitos e sublinhados em qualquer ordem»: isso
// é também a forma de um token e de um `provider_event_id`. É uma sequência de
// **palavras** separadas por `_`, cada uma com letras e, no fim, até três
// dígitos (`http_404`, `v2`, `sha256`); ou um número até seis dígitos. Uma
// cadeia aleatória com dígitos pelo meio (`k3j9x2m1`) não tem esta forma.
const PALAVRA = "[a-z]+[0-9]{0,3}";
const NUMERO = "[0-9]{1,6}";
const IDENTIFICADOR = new RegExp(`^${PALAVRA}(?:_(?:${PALAVRA}|${NUMERO}))*$`);

// `error_code` admite também maiúsculas (`CALLBACK_INVALIDO`), CamelCase
// (`TimeoutError`), o número de um erro da Meta (`131049`) e o ponto — porque
// os ganchos e a ponte de Python põem aqui o nome de um *logger* de biblioteca.
const SEGMENTO = `(?:(?:[a-z]+|[A-Z]+|(?:[A-Z][a-z]+)+)[0-9]{0,3}|${NUMERO})`;
const CODIGO = new RegExp(`^_?${SEGMENTO}(?:[_.]{1,2}${SEGMENTO})*$`);

// O nome de uma classe vem do código e não de quem chama, e os nomes reais têm
// dígitos pelo meio (`OAuth2Error`, `ISO8601Error`). Fica a forma de
// identificador, com no máximo dois grupos de dígitos de até quatro cada.
const CLASSE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const GRUPO_DE_DIGITOS = /[0-9]+/g;
export const CLASSE_COMPRIMENTO_MAXIMO = 64;
// Só letras, com `_` ou `-` entre palavras, e **sem dígitos**: é o que
// distingue `telefone` e `X-Signature` de um identificador de evento.
const NOME_LEGIVEL = /^[A-Za-z]+(?:[_-][A-Za-z]+)*$/;
const NOME_LEGIVEL_MAXIMO = 40;
const BRANCOS = /[ \t\r\n]/g;

/**
 * Um valor de texto leva no máximo seis dígitos **no total**, estejam onde
 * estiverem. Sete já recusam: apanha o telefone, o NIF, o IBAN e a referência
 * de pagamento em qualquer arrumação que caiba no alfabeto de um campo
 * (`923.456.789`, `923456__789`, `a923_b456_c789`), sem precisar de saber o
 * formato de nenhum deles. Os códigos de erro da Meta têm seis dígitos e passam.
 */
const DIGITO = /[0-9]/g;
export const DIGITOS_MAXIMOS = 6;

/** Token de acesso da Meta (`EAA…`) e JWT (`eyJ…`). */
const FORMA_DE_SEGREDO = /EAA[A-Za-z0-9]{16}|eyJ[A-Za-z0-9_]{8}/;

const COMPRIMENTO_MAXIMO: Readonly<Record<string, number>> = {
  svc: 32,
  wa_type: 32,
  tool: 64,
  outcome: 64,
  error_code: 96,
};

function semConteudo(texto: string): boolean {
  if ((texto.match(DIGITO)?.length ?? 0) > DIGITOS_MAXIMOS) {
    return false;
  }
  return !FORMA_DE_SEGREDO.test(texto);
}

function identificador(nome: string, valor: unknown, forma: RegExp): string | null {
  if (typeof valor !== "string") {
    return null;
  }
  const maximo = COMPRIMENTO_MAXIMO[nome] ?? 0;
  if (valor.length < 1 || valor.length > maximo) {
    return null;
  }
  if (!forma.test(valor) || !semConteudo(valor)) {
    return null;
  }
  return valor;
}

function uuid(valor: unknown): string | null {
  if (typeof valor !== "string") {
    return null;
  }
  const minusculas = valor.toLowerCase();
  return UUID.test(minusculas) ? minusculas : null;
}

/**
 * `turn_id` e `msg_id`: um UUID, ou o resultado de `idOpaco`.
 *
 * **Um `wamid` em claro é recusado.** `docs/tecnica/02` define
 * `turn_id = wamid`, e o identificador de mensagem da Meta leva o número do
 * interlocutor codificado em base64 (INDÍCIO: observação comum, sem fonte
 * primária no canon — `docs/logs.md` §2.1). Quem tem um `wamid` regista
 * `idOpaco(wamid)`.
 */
function referenciaDeMensagem(valor: unknown): string | null {
  const canonico = uuid(valor);
  if (canonico !== null) {
    return canonico;
  }
  if (typeof valor === "string" && ID_OPACO.test(valor)) {
    return valor;
  }
  return null;
}

/** O nome do serviço, ou `null` se não tiver a forma de um. */
export function validarSvc(valor: unknown): string | null {
  return identificador("svc", valor, SVC);
}

/**
 * O valor na forma em que sai na linha, ou `null` se for recusado.
 *
 * Nunca chama `String()` nem `toString()` sobre o que recebe: um objecto que
 * não é do tipo esperado é recusado sem lhe correr código nenhum.
 */
export function validar(nome: string, valor: unknown): string | number | null {
  switch (nome) {
    case "tenant_id":
      return uuid(valor);
    case "contact_hmac_prefix":
      return typeof valor === "string" && HMAC_PREFIXO.test(valor) ? valor : null;
    case "turn_id":
    case "msg_id":
      return referenciaDeMensagem(valor);
    case "wa_type":
    case "tool":
    case "outcome":
      return identificador(nome, valor, IDENTIFICADOR);
    case "latency_ms":
      if (
        typeof valor === "number" &&
        Number.isInteger(valor) &&
        valor >= 0 &&
        valor <= LATENCIA_MAXIMA_MS
      ) {
        return valor;
      }
      return null;
    case "error_code":
      return errorCode(valor);
    default:
      return null;
  }
}

function classeValida(classe: unknown): classe is string {
  if (
    typeof classe !== "string" ||
    classe.length < 1 ||
    classe.length > CLASSE_COMPRIMENTO_MAXIMO
  ) {
    return false;
  }
  if (!CLASSE.test(classe) || !semConteudo(classe)) {
    return false;
  }
  const grupos = classe.match(GRUPO_DE_DIGITOS) ?? [];
  return grupos.length <= 2 && grupos.every((grupo) => grupo.length <= 4);
}

/** `<codigo>` ou `<codigo>:<Classe>`, cada parte com a sua forma. */
function errorCode(valor: unknown): string | null {
  if (typeof valor !== "string") {
    return null;
  }
  const maximo = COMPRIMENTO_MAXIMO.error_code ?? 0;
  if (valor.length < 1 || valor.length > maximo) {
    return null;
  }
  const corte = valor.indexOf(":");
  const codigo = corte === -1 ? valor : valor.slice(0, corte);
  if (!CODIGO.test(codigo) || !semConteudo(codigo)) {
    return null;
  }
  if (corte !== -1 && !classeValida(valor.slice(corte + 1))) {
    return null;
  }
  return valor;
}

/**
 * `<codigo>:<Classe>`, ou só o código se a classe não tiver forma de nome.
 *
 * É assim que um erro se regista «por `error_code` e classe» sem haver campo
 * para a classe: a *allowlist* é exacta e não o tem.
 */
export function codigoComClasse(codigo: unknown, classe: unknown): unknown {
  if (typeof codigo !== "string") {
    return codigo;
  }
  if (classeValida(classe)) {
    return `${codigo}:${classe}`;
  }
  return codigo;
}

/**
 * O nome de um campo recusado, para a mensagem do modo estrito. Só se devolve
 * o que é curto e feito de palavras: uma chave que não o seja pode ser
 * conteúdo.
 */
export function nomeLegivel(nome: unknown): string {
  if (
    typeof nome === "string" &&
    nome.length <= NOME_LEGIVEL_MAXIMO &&
    NOME_LEGIVEL.test(nome)
  ) {
    return nome;
  }
  return "<nome ilegivel>";
}

/**
 * Um identificador externo (um `wamid`, um `event_id`) em forma registável:
 * `m_` mais os primeiros 32 caracteres hexadecimais do SHA-256.
 *
 * Serve para **correlacionar** e não é um segredo. **Nunca** se lhe dá um
 * telefone, um NIF ou outra coisa enumerável: um resumo sem chave de um espaço
 * pequeno inverte-se por enumeração (ADR-010).
 */
export function idOpaco(identificador: string): string {
  if (typeof identificador !== "string" || identificador === "") {
    throw new TypeError("idOpaco exige texto nao vazio");
  }
  const resumo = createHash("sha256").update(identificador, "utf8").digest("hex");
  return `m_${resumo.slice(0, 32)}`;
}

/** Quantos caracteres do fim de uma referência ficam visíveis. */
export const REFERENCIA_VISIVEIS = 3;
/** Abaixo deste comprimento a máscara é total. */
export const REFERENCIA_MINIMO = 8;
const MASCARA = "***";

/**
 * Uma referência de pagamento com só os últimos 3 caracteres visíveis.
 *
 * A máscara tem comprimento fixo, para não revelar o da referência. O que não é
 * texto, ou é curto demais, sai todo mascarado.
 */
export function mascararReferencia(referencia: unknown): string {
  if (typeof referencia !== "string") {
    return MASCARA;
  }
  // Por caracteres e não por unidades UTF-16: cortar a meio de um par
  // substituto dava meio carácter, e um resultado diferente do de Python.
  const compacta = Array.from(referencia.replace(BRANCOS, ""));
  if (compacta.length < REFERENCIA_MINIMO) {
    return MASCARA;
  }
  return MASCARA + compacta.slice(-REFERENCIA_VISIVEIS).join("");
}
