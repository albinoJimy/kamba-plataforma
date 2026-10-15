/**
 * A porta `KeyProvider` e a sua implementação sobre a porta de segredos (KAM-008).
 *
 * O módulo de identidade precisa de três famílias de chave, e **nenhuma vive na
 * base de dados**:
 *
 * | Chave | Para quê | Referência no inventário |
 * |---|---|---|
 * | de pesquisa (`kid`) | HMAC do BSUID e do telefone | `pepper_contact_hmac` |
 * | de época (`YYYYMM`) | `sujeito_ref` das tabelas analíticas | `sujeito_epoch_key/<YYYYMM>` |
 * | KEK | embrulhar a DEK de cada contacto | `kek_contact_dek` |
 *
 * `SecretsKeyProvider` implementa a porta sobre um `SecretProvider` do KAM-010:
 * trocar de cofre é trocar o provedor de segredos, e a porta de chaves não muda.
 *
 * ## Forma dos valores (*proposta*)
 *
 * As chaves de pesquisa e a KEK guardam-se como `<kid>:<base64>`, com 32 octetos
 * depois de descodificar. O `kid` vai **dentro** do valor para que a
 * correspondência entre versão e chave não dependa de uma segunda tabela que
 * pudesse divergir do cofre: o anel `[actual, anterior]` do `SecretProvider`
 * chega, e cada entrada diz que versão é. A chave de época é só o `base64`.
 *
 * ## Produção
 *
 * O critério de aceitação do ticket é literal: com `KAMBA_ENV=prod`, o arranque
 * falha se as chaves vierem do ambiente do processo. `exigirKeyProviderDeCofre`
 * é essa verificação, e `Identidade.arrancar` chama-a sempre — não há forma de
 * obter o serviço sem passar por ela.
 *
 * **Nenhuma mensagem de erro deste ficheiro contém material de chave.**
 */

import { Buffer } from "node:buffer";
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

import {
  type Ambiente,
  EnvSecretProvider,
  type ProcessEnv,
  SecretAusenteError,
  type SecretProvider,
  isAmbiente,
} from "../secrets/index.ts";

/** Referência das chaves de pesquisa (o *pepper* do `docs/tecnica/08` §5). */
export const REF_CHAVE_DE_PESQUISA = "pepper_contact_hmac";
/** Referência da KEK que embrulha as DEK por contacto. */
export const REF_KEK = "kek_contact_dek";
/** Família das chaves de época; a instância é a época `YYYYMM`. */
export const REF_CHAVE_DE_EPOCA = "sujeito_epoch_key";

/** Variável que diz em que ambiente o processo corre. */
export const VARIAVEL_DE_AMBIENTE = "KAMBA_ENV";

/** Octetos de todas as chaves deste módulo (AES-256, HMAC-SHA256). */
export const OCTETOS_DE_CHAVE = 32;

const KID = /^[a-z0-9][a-z0-9_.-]{0,62}$/;
const EPOCA = /^[0-9]{4}(0[1-9]|1[0-2])$/;
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

/** Versão de formato do embrulho de uma DEK. */
const VERSAO_DO_EMBRULHO = 1;
const OCTETOS_DE_IV = 12;
const OCTETOS_DE_ETIQUETA = 16;

/** O `kid` pedido não existe no cofre (nem como actual, nem como anterior). */
export class ChaveDesconhecidaError extends Error {
  override readonly name = "ChaveDesconhecidaError";
  readonly ref: string;
  readonly kid: string;

  constructor(ref: string, kid: string) {
    super(`o cofre não tem a versão ${JSON.stringify(kid)} de ${ref}`);
    this.ref = ref;
    this.kid = kid;
  }
}

/** O valor guardado no cofre não tem a forma de uma chave. Nunca diz o valor. */
export class ChaveMalFormadaError extends Error {
  override readonly name = "ChaveMalFormadaError";
  readonly ref: string;

  constructor(ref: string, motivo: string) {
    super(`a chave ${ref} está mal formada no cofre: ${motivo}`);
    this.ref = ref;
  }
}

/** A época não é `YYYYMM`. */
export class EpocaInvalidaError extends Error {
  override readonly name = "EpocaInvalidaError";

  constructor() {
    super("a época tem de ser YYYYMM (por exemplo 202610)");
  }
}

/** O embrulho de uma DEK não abre: KEK errada, contexto errado ou conteúdo alterado. */
export class EmbrulhoInvalidoError extends Error {
  override readonly name = "EmbrulhoInvalidoError";

  constructor(motivo: string) {
    super(`a DEK não se consegue desembrulhar: ${motivo}`);
  }
}

/** Em `prod`, as chaves não vêm do ambiente do processo. */
export class KeyProviderDeAmbienteError extends Error {
  override readonly name = "KeyProviderDeAmbienteError";
  readonly provedor: string;

  constructor(provedor: string) {
    super(
      `arranque recusado: em prod o KeyProvider não pode ser o de ambiente ` +
        `(provedor ${provedor}); as chaves de identidade vêm do cofre`,
    );
    this.provedor = provedor;
  }
}

/** `KAMBA_ENV` em falta, inválida, ou diferente do ambiente do provedor. */
export class AmbienteDeIdentidadeError extends Error {
  override readonly name = "AmbienteDeIdentidadeError";

  constructor(motivo: string) {
    super(`arranque recusado: ${motivo}`);
  }
}

/** Uma DEK embrulhada, e a versão da KEK que a embrulhou. */
export interface DekEmbrulhada {
  readonly embrulho: Uint8Array;
  readonly kekId: string;
}

/**
 * A porta.
 *
 * Quem a implementa garante três coisas: as chaves têm 32 octetos; pedir uma
 * versão que não existe é um erro, nunca uma chave por omissão; e nenhum erro
 * leva material de chave.
 */
export interface KeyProvider {
  /** Nome curto, para mensagens: `secrets:env`, `secrets:doppler`. */
  readonly nome: string;
  /** Ambiente para que o provedor está configurado. */
  readonly ambiente: Ambiente;
  /** `true` se as chaves vêm do ambiente do processo. Em `prod` é recusado. */
  readonly deAmbiente: boolean;

  /** A chave de pesquisa da versão `kid`. */
  getLookupKey(kid: string): Promise<Uint8Array>;
  /** A chave da época `YYYYMM`. */
  getEpochKey(epoca: string): Promise<Uint8Array>;
  /**
   * Embrulha uma DEK com a KEK actual.
   *
   * `contexto` é autenticado e não é cifrado: tem de ser o mesmo ao
   * desembrulhar. O módulo passa-lhe o tenant e o `dek_id`, pelo que um
   * embrulho copiado para a linha de outro contacto não abre.
   */
  wrapDek(dek: Uint8Array, contexto: Uint8Array): Promise<DekEmbrulhada>;
  /** Desembrulha com a KEK da versão `kekId`. */
  unwrapDek(embrulho: Uint8Array, kekId: string, contexto: Uint8Array): Promise<Uint8Array>;
}

/** `true` se `kid` tem a forma de um identificador de versão. */
export function kidValido(kid: unknown): kid is string {
  return typeof kid === "string" && KID.test(kid);
}

/** `true` se `epoca` é `YYYYMM`. */
export function epocaValida(epoca: unknown): epoca is string {
  return typeof epoca === "string" && EPOCA.test(epoca);
}

/** A época (`YYYYMM`, em UTC) de um instante. */
export function epocaDe(instante: Date): string {
  if (!(instante instanceof Date) || Number.isNaN(instante.getTime())) {
    throw new EpocaInvalidaError();
  }
  const mes = String(instante.getUTCMonth() + 1).padStart(2, "0");
  return `${instante.getUTCFullYear()}${mes}`;
}

function descodificarChave(ref: string, texto: string): Buffer {
  if (!BASE64.test(texto) || texto.length % 4 !== 0) {
    throw new ChaveMalFormadaError(ref, "não é base64");
  }
  const chave = Buffer.from(texto, "base64");
  if (chave.length !== OCTETOS_DE_CHAVE) {
    throw new ChaveMalFormadaError(
      ref,
      `tem ${chave.length} octetos e são precisos ${OCTETOS_DE_CHAVE}`,
    );
  }
  return chave;
}

/** Separa `<kid>:<base64>`. A mensagem de erro nunca repete o valor. */
function lerVersionada(ref: string, valor: string): { kid: string; chave: Buffer } {
  const corte = valor.indexOf(":");
  if (corte === -1) {
    throw new ChaveMalFormadaError(ref, "falta a versão (esperava <kid>:<base64>)");
  }
  const kid = valor.slice(0, corte);
  if (!kidValido(kid)) {
    throw new ChaveMalFormadaError(ref, "a versão não tem forma de identificador");
  }
  return { kid, chave: descodificarChave(ref, valor.slice(corte + 1)) };
}

/** Opções de `SecretsKeyProvider`. */
export interface SecretsKeyProviderOpcoes {
  /** O provedor de segredos (KAM-010) de onde as chaves vêm. */
  readonly segredos: SecretProvider;
}

/**
 * `KeyProvider` sobre um `SecretProvider`.
 *
 * Não guarda chaves em memória entre chamadas: pede-as ao provedor de segredos
 * de cada vez, e quem quiser a janela de tolerância do KAM-010 dá-lhe uma
 * `Secrets`... que não é um `SecretProvider`. Fica dito: a cache de chaves é uma
 * decisão por tomar (ver `docs/identidade.md` §8), e não se toma aqui por omissão.
 */
export class SecretsKeyProvider implements KeyProvider {
  readonly nome: string;
  readonly ambiente: Ambiente;
  readonly deAmbiente: boolean;
  readonly #segredos: SecretProvider;

  constructor(opcoes: SecretsKeyProviderOpcoes) {
    this.#segredos = opcoes.segredos;
    this.nome = `secrets:${opcoes.segredos.nome}`;
    this.ambiente = opcoes.segredos.ambiente;
    this.deAmbiente = opcoes.segredos.nome === "env";
  }

  /** As versões vivas de uma chave versionada: a actual primeiro. */
  async #anel(ref: string): Promise<{ kid: string; chave: Buffer }[]> {
    const [actual, anterior] =
      ref === REF_KEK
        ? await this.#segredos.getRing("kek_contact_dek")
        : await this.#segredos.getRing("pepper_contact_hmac");
    const versoes = [lerVersionada(ref, actual)];
    if (anterior !== null) versoes.push(lerVersionada(ref, anterior));
    if (versoes.length === 2 && versoes[0]?.kid === versoes[1]?.kid) {
      // Duas chaves com o mesmo `kid` tornavam o HMAC de uma linha ambíguo.
      throw new ChaveMalFormadaError(ref, "a versão actual e a anterior têm o mesmo kid");
    }
    return versoes;
  }

  async #versao(ref: string, kid: string): Promise<Buffer> {
    if (!kidValido(kid)) throw new ChaveDesconhecidaError(ref, String(kid).slice(0, 64));
    const encontrada = (await this.#anel(ref)).find((versao) => versao.kid === kid);
    if (encontrada === undefined) throw new ChaveDesconhecidaError(ref, kid);
    return encontrada.chave;
  }

  async getLookupKey(kid: string): Promise<Uint8Array> {
    return this.#versao(REF_CHAVE_DE_PESQUISA, kid);
  }

  async getEpochKey(epoca: string): Promise<Uint8Array> {
    if (!epocaValida(epoca)) throw new EpocaInvalidaError();
    const ref = `${REF_CHAVE_DE_EPOCA}/${epoca}`;
    let valor: string;
    try {
      // A instância é a época, validada acima; a família está no inventário.
      valor = await this.#segredos.get(ref); // kamba:secrets-inventory dinamico a instancia e a epoca YYYYMM, ja validada
    } catch (erro) {
      if (erro instanceof SecretAusenteError) {
        // Uma época sem chave é uma época cuja chave foi destruída (ou nunca
        // criada): não há pseudónimo a calcular, e não se inventa uma chave.
        throw new ChaveDesconhecidaError(REF_CHAVE_DE_EPOCA, epoca);
      }
      throw erro;
    }
    return descodificarChave(ref, valor);
  }

  async wrapDek(dek: Uint8Array, contexto: Uint8Array): Promise<DekEmbrulhada> {
    if (dek.length !== OCTETOS_DE_CHAVE) {
      throw new EmbrulhoInvalidoError(`a DEK tem de ter ${OCTETOS_DE_CHAVE} octetos`);
    }
    const [actual] = await this.#anel(REF_KEK);
    if (actual === undefined) throw new ChaveMalFormadaError(REF_KEK, "anel vazio");
    const iv = randomBytes(OCTETOS_DE_IV);
    const cifra = createCipheriv("aes-256-gcm", actual.chave, iv);
    cifra.setAAD(contexto);
    const corpo = Buffer.concat([cifra.update(dek), cifra.final()]);
    return {
      embrulho: Buffer.concat([
        Buffer.from([VERSAO_DO_EMBRULHO]),
        iv,
        cifra.getAuthTag(),
        corpo,
      ]),
      kekId: actual.kid,
    };
  }

  async unwrapDek(
    embrulho: Uint8Array,
    kekId: string,
    contexto: Uint8Array,
  ): Promise<Uint8Array> {
    const kek = await this.#versao(REF_KEK, kekId);
    const minimo = 1 + OCTETOS_DE_IV + OCTETOS_DE_ETIQUETA + OCTETOS_DE_CHAVE;
    if (embrulho.length !== minimo || embrulho[0] !== VERSAO_DO_EMBRULHO) {
      throw new EmbrulhoInvalidoError("formato desconhecido");
    }
    const dados = Buffer.from(embrulho);
    const iv = dados.subarray(1, 1 + OCTETOS_DE_IV);
    const etiqueta = dados.subarray(1 + OCTETOS_DE_IV, 1 + OCTETOS_DE_IV + OCTETOS_DE_ETIQUETA);
    const corpo = dados.subarray(1 + OCTETOS_DE_IV + OCTETOS_DE_ETIQUETA);
    const decifra = createDecipheriv("aes-256-gcm", kek, iv);
    decifra.setAAD(contexto);
    decifra.setAuthTag(etiqueta);
    try {
      return Buffer.concat([decifra.update(corpo), decifra.final()]);
    } catch {
      // O erro do Node não diz nada de útil, e não se propaga: o que importa a
      // quem chama é que a DEK não abriu.
      throw new EmbrulhoInvalidoError("a autenticação falhou");
    }
  }
}

/** Opções de `EnvKeyProvider`. */
export interface EnvKeyProviderOpcoes {
  readonly ambiente: Ambiente;
  /** O ambiente a ler. Por omissão, `process.env`. */
  readonly env?: ProcessEnv;
}

/**
 * O `KeyProvider` de ambiente: as chaves vêm de `KAMBA_SECRET_*`.
 *
 * Para `dev` e para os testes. Em `prod` é recusado por
 * `exigirKeyProviderDeCofre`, que é a letra do critério de aceitação.
 */
export class EnvKeyProvider extends SecretsKeyProvider {
  constructor(opcoes: EnvKeyProviderOpcoes) {
    super({
      segredos: new EnvSecretProvider(
        opcoes.env === undefined
          ? { ambiente: opcoes.ambiente }
          : { ambiente: opcoes.ambiente, env: opcoes.env },
      ),
    });
  }
}

/**
 * Recusa o arranque quando as chaves não podem ser as que são.
 *
 * Três recusas, todas fechadas:
 *
 * 1. `KAMBA_ENV` em falta ou fora de `dev`/`staging`/`prod`. Uma variável
 *    esquecida não pode valer como «não é produção»: era a forma de um
 *    `prod` mal configurado arrancar com chaves de ambiente.
 * 2. `KAMBA_ENV` diferente do ambiente do provedor: chaves de `dev` em `prod`,
 *    ou o contrário.
 * 3. `KAMBA_ENV=prod` com um provedor de ambiente — o critério do ticket.
 *
 * Devolve o ambiente, para quem o quiser registar.
 */
export function exigirKeyProviderDeCofre(
  chaves: KeyProvider,
  env: ProcessEnv = process.env,
): Ambiente {
  const declarado = (env[VARIAVEL_DE_AMBIENTE] ?? "").trim();
  if (!isAmbiente(declarado)) {
    throw new AmbienteDeIdentidadeError(
      `${VARIAVEL_DE_AMBIENTE} tem de ser dev, staging ou prod`,
    );
  }
  if (chaves.ambiente !== declarado) {
    throw new AmbienteDeIdentidadeError(
      `${VARIAVEL_DE_AMBIENTE} é ${declarado} e o KeyProvider (${chaves.nome}) ` +
        `está configurado para ${chaves.ambiente}`,
    );
  }
  if (declarado === "prod" && chaves.deAmbiente) {
    throw new KeyProviderDeAmbienteError(chaves.nome);
  }
  return declarado;
}

/**
 * Gera uma chave nova na forma `<kid>:<base64>`, para quem provisiona o cofre.
 *
 * Não escreve em lado nenhum: devolve o texto, e quem o chama entrega-o ao
 * cofre. Existe para que ninguém tenha de inventar a forma do valor à mão.
 */
export function gerarChaveVersionada(kid: string): string {
  if (!kidValido(kid)) {
    throw new ChaveMalFormadaError("(nova)", "a versão não tem forma de identificador");
  }
  return `${kid}:${randomBytes(OCTETOS_DE_CHAVE).toString("base64")}`;
}
