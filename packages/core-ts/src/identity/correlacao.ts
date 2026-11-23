/**
 * O pseudónimo do telefone **sem tenant**, e o interruptor que o liga (KAM-208).
 *
 * O `phone_hmac` de `contacts` leva o tenant na mensagem (`hmacDePesquisa`): o
 * mesmo número dá HMAC diferentes em tenants diferentes, e é isso que impede um
 * tenant de reconhecer os clientes de outro. A correlação entre tenants por
 * comprador precisa do contrário — um nome estável do mesmo número em todos os
 * tenants — e por isso é um **segundo** pseudónimo, com chave e domínio
 * próprios, que vive numa tabela que só o `kamba_identity` escreve
 * (`platform.contact_xtenant_pseudonym`, revisão `0087`) e que o lote só
 * compara por uma função que devolve o tenant e uma contagem.
 *
 * Decisões do fundador de 2026-11-21 (bloco do KAM-208):
 *
 * - **D1, o interruptor.** `KAMBA_CORRELACAO_ENTRE_TENANTS=ligada` liga-o; a
 *   omissão, e qualquer outro valor, é desligado. **Em `prod` está trancado no
 *   código**: recusa ligar seja qual for a variável. A base legal do tratamento
 *   cruzado é *(a confirmar por parecer)*, e levantar a tranca é um PR — é aí
 *   que o parecer se anexa. A tranca vale para o cálculo do pseudónimo (aqui) e
 *   para a varredura do lote (`../trust/lote.ts`).
 * - **D3, a chave.** Um segredo próprio no cofre, `pepper_contact_xtenant`, com
 *   anel por `kid` (`<kid>:<base64 de 32 octetos>`, a forma do
 *   `pepper_contact_hmac`), e domínio `kamba.identity.xtenant.v1`. A rotação é
 *   **preguiçosa**: escreve-se sempre sob a versão actual, e só se comparam
 *   pseudónimos do mesmo `kid` — um contacto que não volte a ser resolvido fica
 *   sob a antiga até a retenção o apagar.
 *
 * O que **apaga** não passa pelo interruptor: tirar o número a um contacto,
 * fundi-lo ou apagá-lo apaga o pseudónimo dele com o interruptor desligado,
 * para que desligar nunca deixe um pseudónimo a apontar para quem já não tem o
 * número.
 *
 * **Nenhuma mensagem de erro deste ficheiro contém material de chave nem o
 * telefone.**
 */

import { Buffer } from "node:buffer";
import { createHmac } from "node:crypto";

import {
  type Ambiente,
  EnvSecretProvider,
  type ProcessEnv,
  type SecretProvider,
  SecretAusenteError,
  isAmbiente,
} from "../secrets/index.ts";
import { ChaveMalFormadaError, OCTETOS_DE_CHAVE, lerVersionada } from "./chaves.ts";

/** A variável do interruptor (D1). Não é um segredo. */
export const VARIAVEL_DA_CORRELACAO = "KAMBA_CORRELACAO_ENTRE_TENANTS";
/** O único valor que liga. */
export const VALOR_LIGADA = "ligada";
/** A referência do segredo da chave, no inventário (D3). */
export const REF_CHAVE_DE_CORRELACAO = "pepper_contact_xtenant";
/** Separação de domínio da mensagem do HMAC (D3). */
export const DOMINIO_DA_CORRELACAO = "kamba.identity.xtenant.v1";

/** Dias desde a última resolução ao fim dos quais o pseudónimo se apaga (D4, *proposta*). */
export const DIAS_DE_RETENCAO_DO_PSEUDONIMO = 90;

/**
 * O estado do interruptor. `trancada` é o de `prod` enquanto a tranca do
 * código lá estiver — e diz-se à parte do `desligada` para que quem arranca
 * possa registar que alguém pediu para ligar onde não se liga.
 */
export type EstadoDaCorrelacao = "ligada" | "desligada" | "trancada";

/**
 * Lê o interruptor (D1).
 *
 * `ambiente` é o do processo, já validado por quem chama (o `KAMBA_ENV` da
 * identidade, o `KAMBA_AMBIENTE` do lote). **Em `prod` devolve sempre
 * `trancada` ou `desligada`, nunca `ligada`** — é a tranca, e só um PR a
 * levanta.
 */
export function estadoDaCorrelacao(ambiente: Ambiente, valor: string | undefined): EstadoDaCorrelacao {
  const pedido = (valor ?? "").trim() === VALOR_LIGADA;
  if (!pedido) return "desligada";
  // shortcut: tranca em prod ate o parecer sobre a base legal do tratamento
  // cruzado; revê-se no PR que anexar o parecer (critério 1 do KAM-208).
  if (ambiente === "prod") return "trancada";
  return "ligada";
}

/** O interruptor lido de um ambiente de processo, com o ambiente em `KAMBA_ENV`. */
export function correlacaoDoAmbiente(env: ProcessEnv): EstadoDaCorrelacao {
  const ambiente = (env.KAMBA_ENV ?? "").trim();
  // Um `KAMBA_ENV` em falta ou desconhecido não liga nada: quem o recusa é o
  // `exigirAmbienteDoKeyProvider`, e aqui a resposta segura é «desligada».
  if (!isAmbiente(ambiente)) return "desligada";
  return estadoDaCorrelacao(ambiente, env[VARIAVEL_DA_CORRELACAO]);
}

/** Uma versão da chave do pseudónimo. */
export interface ChaveDeCorrelacao {
  readonly kid: string;
  readonly chave: Uint8Array;
}

/** De onde vem a chave actual do pseudónimo. */
export interface FonteDaCorrelacao {
  /** A versão actual: é sob ela que se escreve (D3). */
  chaveActual(): Promise<ChaveDeCorrelacao>;
}

/** A fonte sobre um `SecretProvider`: o anel de `pepper_contact_xtenant`. */
export class CorrelacaoDoCofre implements FonteDaCorrelacao {
  readonly #segredos: SecretProvider;

  constructor(segredos: SecretProvider) {
    this.#segredos = segredos;
  }

  async chaveActual(): Promise<ChaveDeCorrelacao> {
    const [actual] = await this.#segredos.getRing("pepper_contact_xtenant");
    return lerVersionada(REF_CHAVE_DE_CORRELACAO, actual);
  }
}

/** A fonte do ambiente do processo, que o lançador do cofre enche (ADR-L002). */
export function correlacaoDoAmbienteDoProcesso(ambiente: Ambiente, env?: ProcessEnv): FonteDaCorrelacao {
  return new CorrelacaoDoCofre(
    new EnvSecretProvider(env === undefined ? { ambiente } : { ambiente, env }),
  );
}

/** O interruptor está ligado e a chave não está lá, ou está mal formada. */
export class ChaveDeCorrelacaoEmFaltaError extends Error {
  override readonly name = "ChaveDeCorrelacaoEmFaltaError";

  constructor(motivo: "ausente ou vazia" | "mal formada") {
    super(
      `arranque recusado: ${VARIAVEL_DA_CORRELACAO}=${VALOR_LIGADA} e a chave ` +
        `${REF_CHAVE_DE_CORRELACAO} está ${motivo}`,
    );
  }
}

/** Confere no arranque que a chave existe e tem forma. Ligado sem chave recusa. */
export async function exigirChaveDeCorrelacao(fonte: FonteDaCorrelacao): Promise<void> {
  try {
    await fonte.chaveActual();
  } catch (erro) {
    if (erro instanceof SecretAusenteError) throw new ChaveDeCorrelacaoEmFaltaError("ausente ou vazia");
    if (erro instanceof ChaveMalFormadaError) throw new ChaveDeCorrelacaoEmFaltaError("mal formada");
    throw erro;
  }
}

/**
 * O pseudónimo sem tenant de um telefone **já normalizado** (`normalizarTelefone`).
 *
 * HMAC-SHA256 sobre `kamba.identity.xtenant.v1\0telefone\0<telefone>`. **Não
 * leva o tenant**, que é o ponto; leva o tipo, para que o mesmo valor num outro
 * tipo de identificador, se algum dia houver, não colida com este.
 */
export function pseudonimoSemTenant(chave: Uint8Array, telefone: string): Buffer {
  if (!(chave instanceof Uint8Array) || chave.length !== OCTETOS_DE_CHAVE) {
    throw new ChaveMalFormadaError(REF_CHAVE_DE_CORRELACAO, `tem de ter ${OCTETOS_DE_CHAVE} octetos`);
  }
  if (typeof telefone !== "string" || !/^[1-9][0-9]{7,14}$/.test(telefone)) {
    // Sem o valor na mensagem: é um telefone.
    throw new TypeError("pseudonimoSemTenant: o telefone tem de vir normalizado");
  }
  return createHmac("sha256", chave)
    .update(`${DOMINIO_DA_CORRELACAO}\0telefone\0`, "utf8")
    .update(telefone, "utf8")
    .digest();
}
