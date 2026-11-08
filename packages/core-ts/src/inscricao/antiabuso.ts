/**
 * O anti-abuso da inscrição: prova de trabalho, *honeypot*, tempo mínimo e
 * limites por rede e por dispositivo (KAM-086, critérios 7 e 8).
 *
 * «Anti-bot por defeito sem scripts de terceiros: prova de trabalho adaptativa,
 * *honeypot* e tempo mínimo de preenchimento (3 s, *proposta*); CAPTCHA externo
 * só com D12/parecer.»
 *
 * ## «Sem scripts de terceiros» é uma restrição de arquitectura, não um gosto
 *
 * Um reCAPTCHA ou um Turnstile põem um `<script>` de outro domínio na página de
 * registo. Isso tem três custos que este ticket não pode pagar: parte a CSP
 * estrita que os *Detalhes Técnicos* exigem; manda o IP e o `User-Agent` de cada
 * dono angolano para um terceiro, que é uma transferência internacional de dados
 * pessoais sem base legal estabelecida (**D12**, e *a confirmar por parecer*);
 * e põe a porta de entrada do produto a depender de um domínio que pode estar
 * bloqueado. Daí a prova de trabalho: custa ao atacante e não custa privacidade.
 *
 * ## O desafio é assinado, e é isso que faz o tempo mínimo significar algo
 *
 * É a parte do desenho que vale a pena ler antes do código. O tempo mínimo de
 * preenchimento só é uma barreira se o **instante de início** for nosso. Um
 * campo escondido com `abertoEm` que o cliente devolve é um campo que o cliente
 * escolhe, e um bot escreve lá três segundos atrás. Por isso o `emitidoEm` vai
 * **dentro** do desafio, debaixo de um HMAC nosso: o cliente pode repeti-lo, não
 * pode alterá-lo.
 *
 * O mesmo HMAC resolve o problema de o desafio não precisar de estado. Guardar
 * desafios emitidos numa tabela dava a um atacante uma maneira de nos encher a
 * memória pedindo desafios — o inverso do que ele devia conseguir.
 *
 * ## A dificuldade é adaptativa, e sobe com a **rede** e não com o cliente
 *
 * Um bot que vê a dificuldade subir muda de cliente, não de rede: trocar de
 * `User-Agent` é uma linha e trocar de prefixo de IP custa dinheiro. Por isso o
 * que faz a dificuldade subir é a contagem recente no `ip_prefix_hash`, que é
 * também a chave do limite do critério 7.
 *
 * **O que isto não faz:** não trava um atacante com cinquenta prefixos, e o
 * ensaio adversarial (a) do bloco mede exactamente isso — mil registos em
 * sessenta segundos a partir de cinquenta prefixos. O que trava esse é o
 * **limite por prefixo**, e a prova de trabalho só lhe encarece cada tentativa.
 * Dizer isto por escrito é a diferença entre uma barreira e a sensação de uma.
 *
 * ## Os limites são ***propostas***
 *
 * Cinco casos por hora e por prefixo (do ensaio adversarial (a)) e três casos
 * por 24 h e por dispositivo (do critério 8). Nenhum sai de medição: saem do
 * próprio bloco, e calibram-se no Piloto com a distribuição real de registos
 * por rede — que hoje não existe.
 */

import { createHmac, createHash, randomBytes, timingSafeEqual } from "node:crypto";

import type { Contadores, Relogio } from "./contrato.ts";
import { OCTETOS_DE_HMAC } from "./identificadores.ts";

/** Separador de domínio dos desafios. Versionado. */
export const DOMINIO_DO_DESAFIO = "kamba/onboarding/pow/v1";

/** Separador de domínio da prova. **Diferente do do desafio** — ver `#resumo`. */
export const DOMINIO_DA_PROVA = "kamba/onboarding/pow-prova/v1";

/** Bits de dificuldade de base. *Proposta*. */
export const DIFICULDADE_BASE = 12;

/** Tecto da dificuldade, em bits. *Proposta*. Acima disto um telefone antigo desiste. */
export const DIFICULDADE_MAXIMA = 20;

/** Segundos mínimos de preenchimento. *Proposta* do critério 7. */
export const SEGUNDOS_MINIMOS = 3;

/**
 * Validade de um desafio, em segundos. ***Proposta***: dez minutos.
 *
 * **Eram trinta, e os trinta eram o segundo metade de um achado.** O desafio é
 * reutilizável — não há registo de `nonce` gasto, e pô-lo exigia estado que um
 * atacante consegue encher —, pelo que a sua validade é exactamente a janela
 * em que uma prova de trabalho resolvida compra submissões ilimitadas. Trinta
 * minutos tornavam a escada de dificuldade decorativa; dez continuam a dar
 * folga a um dono que preenche o formulário com calma, e cortam a janela a um
 * terço. A outra metade do achado é a prisão à rede — ver `DOMINIO_DO_DESAFIO`.
 */
export const VALIDADE_DO_DESAFIO_S = 600;

/** Casos por hora e por prefixo de IP. *Proposta* do ensaio adversarial (a). */
export const CASOS_POR_REDE = 5;

/** A janela do limite por rede, em milissegundos. Uma hora. */
export const JANELA_DA_REDE_MS = 3_600_000;

/** Casos por 24 h e por dispositivo. *Proposta* do critério 8. */
export const CASOS_POR_DISPOSITIVO = 3;

/** A janela do limite por dispositivo, em milissegundos. */
export const JANELA_DO_DISPOSITIVO_MS = 86_400_000;

/** As chaves de contagem deste módulo. Prefixadas para não colidirem com o `./otp.ts`. */
export const CHAVES = {
  rede: (redeHmac: string): string => `abuso:rede:${redeHmac}`,
  dispositivo: (dispositivoHmac: string): string => `abuso:dispositivo:${dispositivoHmac}`,
} as const;

/** Porque é que uma submissão foi recusada. Lista fechada; nenhum valor é um dado. */
export const RECUSAS = [
  "desafio_invalido",
  "desafio_de_outra_rede",
  "desafio_expirado",
  "prova_invalida",
  "depressa",
  "honeypot",
  "limite_de_rede",
] as const;

export type Recusa = (typeof RECUSAS)[number];

/** Levantado quando uma submissão não passa o anti-abuso. */
export class AbusoError extends Error {
  override readonly name = "AbusoError";
  readonly recusa: Recusa;

  constructor(recusa: Recusa) {
    super(`submissao recusada pelo anti-abuso: ${recusa}`);
    this.recusa = recusa;
  }
}

/** O que o cliente recebe para preencher o formulário. */
export interface DesafioEmitido {
  /** O desafio assinado, opaco para o cliente. Volta tal como veio. */
  readonly desafio: string;
  /** Os bits que a prova tem de ter a zero. O cliente precisa dele para procurar. */
  readonly dificuldade: number;
  /** O nome do campo que tem de voltar vazio. Ver `NOME_DO_HONEYPOT`. */
  readonly honeypot: string;
}

/**
 * O nome do campo *honeypot*.
 *
 * Parece um campo a sério de propósito: um bot que preencha «todos os campos de
 * texto» preenche-o, e um bot que ignore campos chamados `honeypot` não o
 * preenche. O campo é escondido por CSS e não por `type="hidden"` — um
 * `hidden` é trivial de reconhecer. **O campo é rotulado** — um campo sem
 * rótulo chama a atenção de um bot —, e o que o esconde de um leitor de ecrã é
 * o `aria-hidden="true"` da caixa que o envolve, mais o `tabindex="-1"`. (A
 * primeira versão desta nota dizia que «a página não o rotula», e a página
 * rotula-o: a propriedade mantém-se, a razão escrita estava errada, e é ela que
 * um *refactor* lê ao decidir se pode mexer no `aria-hidden`. Achado da revisão
 * adversarial.)
 *
 * **E é um campo só e não três** por essa mesma razão: cada *honeypot* é uma
 * armadilha a mais para uma pessoa com leitor de ecrã, e a barreira que trava
 * bots a sério é a prova de trabalho.
 */
export const NOME_DO_HONEYPOT = "empresa_alternativa";

/** Opções do anti-abuso. Todos os limiares são ***propostas***. */
export interface OpcoesDeAntiAbuso {
  readonly contadores: Contadores;
  /** A chave **actual** do anel do `pepper_onboarding_ident`. */
  readonly chave: Uint8Array;
  readonly relogio?: Relogio;
  readonly dificuldadeBase?: number;
  readonly dificuldadeMaxima?: number;
  readonly segundosMinimos?: number;
  readonly casosPorRede?: number;
  readonly casosPorDispositivo?: number;
}

/** O que uma submissão traz do formulário. */
export interface Submissao {
  readonly desafio: string;
  readonly solucao: string;
  /** O valor do campo `NOME_DO_HONEYPOT`. Tem de ser vazio ou ausente. */
  readonly honeypot?: string | undefined;
  readonly redeHmac: string | null;
  readonly dispositivoHmac: string | null;
}

/** O que um desafio diz, depois de verificado. */
interface DesafioLido {
  readonly nonce: string;
  readonly emitidoEm: Date;
  readonly dificuldade: number;
}

/**
 * O texto assinado de um desafio. **Leva a rede**, e não levava.
 *
 * Sem o `redeHmac` dentro, um desafio emitido para uma rede limpa — ou para uma
 * rede que não se percebe, onde a dificuldade é a base — servia em **qualquer**
 * rede durante a validade inteira. A escada de dificuldade do critério 7 ficava
 * decorativa: um SHA-256 de 2¹² tentativas comprava meia hora de submissões em
 * qualquer prefixo, mesmo nos que já tinham subido para 20 bits. Achado da
 * revisão adversarial.
 *
 * `-` é o `redeHmac` ausente, e é um valor e não uma omissão: um desafio emitido
 * sem rede reconhecível só serve onde a rede também não se reconhece.
 */
function partesDoDesafio(
  nonce: string,
  segundos: number,
  dificuldade: number,
  redeHmac: string | null,
): string {
  return `${nonce}.${segundos}.${dificuldade}.${redeHmac ?? "-"}`;
}

function assinar(chave: Uint8Array, dominio: string, texto: string): Buffer {
  return createHmac("sha256", chave).update(`${dominio}\0`, "utf8").update(texto, "utf8").digest();
}

/**
 * Quantos bits à cabeça de `resumo` estão a zero.
 *
 * Bits e não hexadecimais: a dificuldade cresce por factores de dois e não de
 * dezesseis, e uma escada de dezesseis em dezesseis salta de quatro mil tentativas
 * para sessenta e cinco mil sem nada pelo meio.
 */
export function zerosACabeca(resumo: Uint8Array): number {
  let bits = 0;
  for (const octeto of resumo) {
    if (octeto === 0) {
      bits += 8;
      continue;
    }
    bits += Math.clz32(octeto) - 24;
    break;
  }
  return bits;
}

/** O resumo que a prova tem de satisfazer. Exportada porque um cliente precisa dela. */
export function resumoDaProva(desafio: string, solucao: string): Buffer {
  // Domínio **diferente** do da assinatura do desafio, e com a mesma chave
  // nenhuma: este resumo não leva segredo, porque o cliente tem de o conseguir
  // calcular. Se levasse o mesmo domínio da assinatura, uma prova válida era
  // uma oracle sobre o HMAC do desafio.
  return createHash("sha256")
    .update(`${DOMINIO_DA_PROVA}\0`, "utf8")
    .update(desafio, "utf8")
    .update("\u0000", "utf8")
    .update(solucao, "utf8")
    .digest();
}

/**
 * Procura uma solução para o desafio. **É código de cliente**, e está aqui porquê.
 *
 * O cliente a sério é o JavaScript da página, que é do `services/onboarding-web`.
 * Esta função existe para que a bateria possa submeter formulários válidos: sem
 * ela, cada ensaio reimplementava a busca, e um ensaio que a reimplementasse com
 * outro domínio passava a provar que o verificador aceita o que ele próprio
 * calcula. Uma só implementação, usada pelos dois lados, é o que torna a prova
 * uma prova.
 */
export function resolverDesafio(desafio: string, dificuldade: number, tecto = 1 << 26): string {
  for (let tentativa = 0; tentativa < tecto; tentativa += 1) {
    const solucao = String(tentativa);
    if (zerosACabeca(resumoDaProva(desafio, solucao)) >= dificuldade) return solucao;
  }
  throw new Error(`nao encontrei solucao com ${dificuldade} bits em ${tecto} tentativas`);
}

/** O anti-abuso. */
export class AntiAbuso {
  readonly #contadores: Contadores;
  readonly #chave: Uint8Array;
  readonly #relogio: Relogio;
  readonly dificuldadeBase: number;
  readonly dificuldadeMaxima: number;
  readonly segundosMinimos: number;
  readonly casosPorRede: number;
  readonly casosPorDispositivo: number;

  constructor(opcoes: OpcoesDeAntiAbuso) {
    this.#contadores = opcoes.contadores;
    this.#chave = opcoes.chave;
    this.#relogio = opcoes.relogio ?? ((): Date => new Date());
    this.dificuldadeBase = opcoes.dificuldadeBase ?? DIFICULDADE_BASE;
    this.dificuldadeMaxima = opcoes.dificuldadeMaxima ?? DIFICULDADE_MAXIMA;
    this.segundosMinimos = opcoes.segundosMinimos ?? SEGUNDOS_MINIMOS;
    this.casosPorRede = opcoes.casosPorRede ?? CASOS_POR_REDE;
    this.casosPorDispositivo = opcoes.casosPorDispositivo ?? CASOS_POR_DISPOSITIVO;
  }

  /**
   * A dificuldade para esta rede, agora.
   *
   * Sobe um bit por cada duplicação de registos recentes no prefixo, com tecto.
   * Uma rede sem registos nenhuns paga a base, que é o caso do dono normal.
   */
  async dificuldadePara(redeHmac: string | null): Promise<number> {
    if (redeHmac === null) return this.dificuldadeBase;
    const recentes = await this.#contadores.contar(
      CHAVES.rede(redeHmac),
      this.#relogio(),
      JANELA_DA_REDE_MS,
    );
    const subida = recentes <= 0 ? 0 : Math.floor(Math.log2(recentes + 1));
    return Math.min(this.dificuldadeBase + subida, this.dificuldadeMaxima);
  }

  /** Emite um desafio para esta rede. */
  async emitir(redeHmac: string | null): Promise<DesafioEmitido> {
    const dificuldade = await this.dificuldadePara(redeHmac);
    const nonce = randomBytes(8).toString("base64url");
    const segundos = Math.floor(this.#relogio().getTime() / 1000);
    const texto = partesDoDesafio(nonce, segundos, dificuldade, redeHmac);
    const assinatura = assinar(this.#chave, DOMINIO_DO_DESAFIO, texto).toString("base64url");
    return { desafio: `${texto}.${assinatura}`, dificuldade, honeypot: NOME_DO_HONEYPOT };
  }

  /**
   * Verifica uma submissão, ou lança.
   *
   * A ordem é do mais barato para o mais caro, com uma excepção deliberada: o
   * *honeypot* vem **antes** da prova de trabalho. Um bot que preencheu o
   * *honeypot* já se denunciou, e fazê-lo gastar a verificação de um SHA-256
   * antes de o recusar é trabalho nosso ao serviço dele.
   *
   * **Não registra nada.** Quem consome a quota é o `./registo.ts`, depois de
   * saber que vai criar o caso — porque é o caso criado que o critério conta
   * («nenhum prefixo cria > 5 casos/h»), e não a tentativa. Contar tentativas
   * aqui dava a um atacante a maneira de esgotar a quota de uma rede inteira
   * sem criar caso nenhum, que é uma recusa de serviço a um bairro.
   */
  async verificar(submissao: Submissao): Promise<DesafioLido> {
    if (typeof submissao.honeypot === "string" && submissao.honeypot.trim() !== "") {
      throw new AbusoError("honeypot");
    }
    const lido = this.#lerDesafio(submissao.desafio, submissao.redeHmac);
    const agora = this.#relogio();
    const decorridoMs = agora.getTime() - lido.emitidoEm.getTime();
    if (decorridoMs > VALIDADE_DO_DESAFIO_S * 1000) throw new AbusoError("desafio_expirado");
    // Um `decorridoMs` negativo é um desafio do futuro: só acontece se o relógio
    // do servidor andou atrás, e tratá-lo como «depressa» é a resposta certa —
    // nunca como válido.
    if (decorridoMs < this.segundosMinimos * 1000) throw new AbusoError("depressa");

    if (typeof submissao.solucao !== "string" || submissao.solucao.length > 64) {
      throw new AbusoError("prova_invalida");
    }
    const bits = zerosACabeca(resumoDaProva(submissao.desafio, submissao.solucao));
    if (bits < lido.dificuldade) throw new AbusoError("prova_invalida");

    if (submissao.redeHmac !== null) {
      const naRede = await this.#contadores.contar(
        CHAVES.rede(submissao.redeHmac),
        agora,
        JANELA_DA_REDE_MS,
      );
      if (naRede >= this.casosPorRede) throw new AbusoError("limite_de_rede");
    }
    return lido;
  }

  /**
   * Consome a quota de um caso criado.
   *
   * Chamado pelo `./registo.ts` **depois** de o caso existir, e devolve quantos
   * casos este dispositivo abriu na janela — que é o número do critério 8.
   */
  async consumir(
    redeHmac: string | null,
    dispositivoHmac: string | null,
  ): Promise<{ readonly naRede: number; readonly noDispositivo: number }> {
    const agora = this.#relogio();
    const naRede =
      redeHmac === null
        ? 0
        : await this.#contadores.anotar(CHAVES.rede(redeHmac), agora, JANELA_DA_REDE_MS);
    const noDispositivo =
      dispositivoHmac === null
        ? 0
        : await this.#contadores.anotar(
            CHAVES.dispositivo(dispositivoHmac),
            agora,
            JANELA_DO_DISPOSITIVO_MS,
          );
    return { naRede, noDispositivo };
  }

  /** Lê e autentica um desafio, ou lança. */
  /**
   * Lê e autentica um desafio, ou lança.
   *
   * `redeHmac` é a rede **do pedido**: o desafio só vale na rede para que foi
   * emitido, e é isso que torna a escada de dificuldade real. Ver
   * `partesDoDesafio`.
   */
  #lerDesafio(bruto: unknown, redeHmac: string | null): DesafioLido {
    if (typeof bruto !== "string" || bruto.length === 0 || bruto.length > 256) {
      throw new AbusoError("desafio_invalido");
    }
    const campos = bruto.split(".");
    if (campos.length !== 5) throw new AbusoError("desafio_invalido");
    const [nonce, segundos, dificuldade, rede, assinatura] = campos as [
      string,
      string,
      string,
      string,
      string,
    ];
    if (!/^[0-9]{1,15}$/.test(segundos) || !/^[0-9]{1,2}$/.test(dificuldade)) {
      throw new AbusoError("desafio_invalido");
    }
    if (rede !== (redeHmac ?? "-")) throw new AbusoError("desafio_de_outra_rede");
    const recebida = Buffer.from(assinatura, "base64url");
    if (recebida.length !== OCTETOS_DE_HMAC) throw new AbusoError("desafio_invalido");
    const esperada = assinar(
      this.#chave,
      DOMINIO_DO_DESAFIO,
      partesDoDesafio(nonce, Number(segundos), Number(dificuldade), redeHmac),
    );
    if (!timingSafeEqual(esperada, recebida)) throw new AbusoError("desafio_invalido");
    const instante = Number(segundos) * 1000;
    if (!Number.isSafeInteger(instante)) throw new AbusoError("desafio_invalido");
    return { nonce, emitidoEm: new Date(instante), dificuldade: Number(dificuldade) };
  }
}
