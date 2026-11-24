/**
 * A escrita numa referência **fixa** do cofre (KAM-250, `ADR-L002` §6 e §7).
 *
 * Espelho de `libs/py-core/src/kamba_core/secrets/escrita.py`.
 *
 * ## Porque não é o `cunhar` do `escrita.ts`
 *
 * O `cunhar(familia, valor)` do KAM-016 inventa um sufixo **aleatório** e devolve a
 * referência, que a base guarda. As chaves virtuais do LiteLLM são o contrário: a
 * referência é conhecida de antemão — `litellm_virtual_key/<tenant_id>` e
 * `litellm_screening_key`, como o `ops/secrets-inventory.yaml` as declara —,
 * porque quem as lê (o AGR) só sabe o tenant; e o KAM-250 proíbe guardar o que
 * quer que seja na base da plataforma. A operação é outra: `gravar(ref, valor)`.
 *
 * ## Onde escreve
 *
 * Decisão do fundador de 2026-11-24 (bloco do KAM-250, opção 1): num projecto
 * Doppler **só das chaves virtuais**, com um *token* de escrita limitado a esse
 * projecto (`doppler_llm_chaves_escrita`). O `DopplerGravador` recusa, além
 * disso, qualquer referência fora das famílias que lhe dão — uma segunda barreira,
 * do lado do cliente, contra um erro de programação; a primeira é o limite do
 * *token*, que é do servidor.
 *
 * A forma da API de escrita do Doppler é **NÃO VERIFICADO** (não há conta): o que
 * falta confirmar está em `A_CONFIRMAR_ESCRITA`, e tudo o que depende da forma do
 * pedido está em `corpoDoPedido` e no URL de `gravar`.
 */

import { nomeDaVariavel } from "./env.ts";
import {
  AmbienteErradoError,
  type Ambiente,
  CofreInacessivelError,
  type SecretRef,
  familiaDaRef,
  validarRef,
} from "./port.ts";
import type { RespostaHttp } from "./doppler.ts";

/** As famílias que vivem no projecto das chaves virtuais. */
export const FAMILIAS_DAS_CHAVES_DO_LLM = ["litellm_virtual_key", "litellm_screening_key"] as const;

/** O nome do projecto Doppler das chaves, quando o ambiente não o diz. ***Proposta***. */
export const PROJECTO_DAS_CHAVES_POR_OMISSAO = "kamba-llm-chaves";

/** A variável que nomeia o projecto. Não é segredo: é configuração. */
export const VARIAVEL_DO_PROJECTO = "KAMBA_LLM_CHAVES_PROJECTO";

/** O que falta confirmar na escrita, e onde. */
export const A_CONFIRMAR_ESCRITA = {
  caminho:
    "caminho e método do pedido que cria ou actualiza segredos de uma configuração — docs.doppler.com, referência da API (secrets / update)",
  corpo:
    "forma do corpo; `corpoDoPedido` assume {project, config, secrets: {NOME: valor}} — docs.doppler.com",
  resposta: "o código de sucesso; este adaptador aceita só 200 — docs.doppler.com",
  nomes:
    "a regra de nomes de segredo; o gravador escreve o nome em maiúsculas (o hex do tenant_id incluído) e o leitor Python aceita as duas caixas — docs.doppler.com",
  limiteDoToken:
    "que um service token de escrita fica limitado ao projecto e à configuração para que foi emitido — E4 §2.14 di-lo em resumo",
} as const;

/** A referência pedida não é de uma família que este gravador escreve. */
export class FamiliaNaoGravavelError extends Error {
  override readonly name = "FamiliaNaoGravavelError";
  readonly familia: string;

  constructor(familia: string) {
    super(
      `o gravador não escreve a família ${JSON.stringify(familia)}: só as chaves ` +
        "virtuais do LiteLLM vivem no projecto dele (decisão do fundador, KAM-250)",
    );
    this.familia = familia;
  }
}

/** A porta de escrita numa referência fixa. */
export interface GravadorDeSegredo {
  readonly nome: string;
  readonly ambiente: Ambiente;
  /**
   * Escreve `valor` em `ref`. **Nunca** põe o valor numa mensagem de erro.
   *
   * @throws {SecretRefInvalidaError} se `ref` não tem forma de referência.
   * @throws {FamiliaNaoGravavelError} se a família não é deste gravador.
   * @throws {CofreInacessivelError} se o cofre recusa ou não responde.
   */
  gravar(ref: SecretRef, valor: string): Promise<void>;
}

/** Pedido HTTP de escrita, reduzido ao que este adaptador faz. */
export interface PedidoHttpDeEscrita {
  readonly url: string;
  readonly cabecalhos: Readonly<Record<string, string>>;
  readonly corpo: string;
}

/** Transporte de escrita injectado. */
export type TransporteDeEscrita = (pedido: PedidoHttpDeEscrita) => Promise<RespostaHttp>;

/** O corpo do pedido. **NÃO VERIFICADO** (`A_CONFIRMAR_ESCRITA.corpo`). */
export function corpoDoPedido(projecto: string, config: string, nome: string, valor: string): string {
  return JSON.stringify({ project: projecto, config, secrets: { [nome]: valor } });
}

/** Opções de construção. */
export interface DopplerGravadorOpcoes {
  readonly ambiente: Ambiente;
  readonly projecto: string;
  /** Tem de ser igual a `ambiente`, pela razão do `DopplerSecretProvider`. */
  readonly config: string;
  /** *Service token* de escrita. Nunca aparece em mensagem de erro. */
  readonly tokenServico: string;
  readonly transporte: TransporteDeEscrita;
  readonly familias?: readonly string[];
  readonly baseUrl?: string;
}

/** Escreve numa configuração de um projecto Doppler, só nas famílias dadas. */
export class DopplerGravador implements GravadorDeSegredo {
  readonly nome = "doppler";
  readonly ambiente: Ambiente;
  readonly projecto: string;
  readonly config: string;
  readonly #token: string;
  readonly #transporte: TransporteDeEscrita;
  readonly #familias: ReadonlySet<string>;
  readonly #baseUrl: string;

  constructor(o: DopplerGravadorOpcoes) {
    if (o.config !== o.ambiente) throw new AmbienteErradoError("doppler", o.ambiente, o.config);
    if (o.tokenServico.trim() === "") {
      throw new CofreInacessivelError("doppler", "service token de escrita não configurado");
    }
    const familias = o.familias ?? FAMILIAS_DAS_CHAVES_DO_LLM;
    if (familias.length === 0) throw new Error("um gravador sem famílias não escreve nada");
    this.ambiente = o.ambiente;
    this.projecto = o.projecto;
    this.config = o.config;
    this.#token = o.tokenServico;
    this.#transporte = o.transporte;
    this.#familias = new Set(familias);
    this.#baseUrl = (o.baseUrl ?? "https://api.doppler.com").replace(/\/+$/, "");
  }

  async gravar(ref: SecretRef, valor: string): Promise<void> {
    const r = validarRef(ref);
    const familia = familiaDaRef(r);
    if (!this.#familias.has(familia)) throw new FamiliaNaoGravavelError(familia);
    if (typeof valor !== "string" || valor.trim() === "") {
      throw new Error(`valor vazio para ${r}: o gravador não apaga segredos`);
    }
    let resposta: RespostaHttp;
    try {
      resposta = await this.#transporte({
        // `A_CONFIRMAR_ESCRITA.caminho`.
        url: `${this.#baseUrl}/v3/configs/config/secrets`,
        cabecalhos: {
          authorization: `Bearer ${this.#token}`,
          accept: "application/json",
          "content-type": "application/json",
        },
        // Em maiúsculas: `A_CONFIRMAR_ESCRITA.nomes`.
        corpo: corpoDoPedido(this.projecto, this.config, nomeDaVariavel(r).toUpperCase(), valor),
      });
    } catch (erro) {
      // Só o nome da classe atravessa: a mensagem de uma biblioteca de rede pode
      // trazer o URL, os cabeçalhos ou o corpo — que leva o valor.
      const nome = erro instanceof Error ? erro.name : typeof erro;
      throw new CofreInacessivelError(this.nome, `transporte falhou: ${nome}`);
    }
    if (resposta.status === 401 || resposta.status === 403) {
      throw new CofreInacessivelError(
        this.nome,
        `credencial de escrita recusada (HTTP ${resposta.status}) para ${this.projecto}/${this.config}`,
      );
    }
    if (resposta.status !== 200) {
      // Sem o corpo: uma resposta de erro pode ecoar o pedido.
      throw new CofreInacessivelError(this.nome, `escrita falhou: HTTP ${resposta.status}`);
    }
  }
}
