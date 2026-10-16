/**
 * Conversor de versão de envelope — o gancho, vazio (KAM-005, `docs/tecnica/06` §6.6).
 *
 * O §6.6 manda: campo novo **opcional** mantém a `versao`; qualquer mudança de
 * significado, remoção ou tipo sobe a `versao`. O produtor emite a nova versão
 * e o publicador entrega a cada consumidor a versão que ele **declara**
 * (`evt_subscricoes.versao_max`), convertendo pelo caminho. Sem conversor, o
 * evento **não se descarta**: fica por publicar, com alerta.
 *
 * Hoje o registo está **vazio**, e é isso que o ticket pede («conversor de
 * versão (gancho vazio)»). Vazio não quer dizer inerte: com o registo vazio,
 * um evento `versao = 2` para um consumidor com `versao_max = 1` faz
 * `converter` lançar `SemConversorError`, e o publicador trata isso como o §6.2
 * manda — não publica, conta o erro, e deixa a linha no outbox. É a diferença
 * entre «não há conversor» e «ignora-se a versão desconhecida», e o §6.6 diz
 * explicitamente que a segunda perde dados em silêncio.
 *
 * ## O que um conversor tem de preservar
 *
 * «via conversor registado que preserva `id` e `agregado.seq`» (§6.6). Não é um
 * conselho: se o `id` mudar, a deduplicação por `jobId = event_id` deixa de
 * funcionar e o consumidor processa o mesmo facto duas vezes; se o
 * `agregado.seq` mudar, a ordem causal quebra. `registar` **recusa** um
 * conversor que não os preserve — verificado no momento da conversão, sobre o
 * resultado real, e não por confiança.
 *
 * ## O que não há aqui
 *
 * Nenhum conversor. Quando o primeiro `versao = 2` aparecer, é quem o emitir
 * que o registra, no ticket dele, com o teste de ida e volta. O catálogo de
 * schemas e o teste de compatibilidade são o KAM-007.
 */

import type { Envelope } from "./envelope.ts";

/** Transforma um envelope de `de` em `para`. Síncrono: é uma projecção. */
export type Conversor = (envelope: Envelope) => Envelope;

/** Não há conversor registado para este salto de versão. */
export class SemConversorError extends Error {
  readonly tipo: string;
  readonly de: number;
  readonly para: number;

  constructor(tipo: string, de: number, para: number) {
    super(
      `sem conversor de \`${tipo}\` v${de} para v${para}: o evento NAO e ` +
        "descartado (docs/tecnica/06 §6.6). Fica no outbox, com alerta",
    );
    this.name = "SemConversorError";
    this.tipo = tipo;
    this.de = de;
    this.para = para;
  }
}

/** Um conversor registado devolveu um envelope que perdeu `id` ou `seq`. */
export class ConversaoInvalidaError extends Error {
  constructor(tipo: string, de: number, para: number, motivo: string) {
    super(
      `conversor de \`${tipo}\` v${de} para v${para} e invalido: ${motivo}. ` +
        "Um conversor preserva `id` e `agregado.seq` (docs/tecnica/06 §6.6)",
    );
    this.name = "ConversaoInvalidaError";
  }
}

function chave(tipo: string, de: number, para: number): string {
  return `${tipo}:${de}->${para}`;
}

/**
 * Registo de conversores. Começa vazio, e é instância para que um teste possa
 * ter o seu sem contaminar o do processo.
 */
export class RegistoDeConversores {
  readonly #conversores = new Map<string, Conversor>();

  /** Quantos conversores estão registados. Zero, hoje. */
  get tamanho(): number {
    return this.#conversores.size;
  }

  registar(tipo: string, de: number, para: number, conversor: Conversor): void {
    if (!Number.isInteger(de) || !Number.isInteger(para) || de <= para) {
      throw new ConversaoInvalidaError(
        tipo,
        de,
        para,
        "converte-se para **baixo**: `de` tem de ser maior que `para`",
      );
    }
    this.#conversores.set(chave(tipo, de, para), conversor);
  }

  tem(tipo: string, de: number, para: number): boolean {
    return this.#conversores.has(chave(tipo, de, para));
  }

  /**
   * Converte, ou lança.
   *
   * `de <= para` devolve o envelope como está: o consumidor aceita esta versão
   * e mais altas, pelo que não há nada a converter. Só se converte para baixo.
   */
  converter(envelope: Envelope, para: number): Envelope {
    const de = envelope.versao;
    if (de <= para) return envelope;
    const conversor = this.#conversores.get(chave(envelope.tipo, de, para));
    if (conversor === undefined) {
      throw new SemConversorError(envelope.tipo, de, para);
    }
    const convertido = conversor(envelope);
    if (convertido.id !== envelope.id) {
      throw new ConversaoInvalidaError(
        envelope.tipo,
        de,
        para,
        "mudou o `id`, e a deduplicacao por jobId deixa de valer",
      );
    }
    if (convertido.agregado.seq !== envelope.agregado.seq) {
      throw new ConversaoInvalidaError(
        envelope.tipo,
        de,
        para,
        "mudou o `agregado.seq`, e a ordem causal quebra",
      );
    }
    if (convertido.versao !== para) {
      throw new ConversaoInvalidaError(
        envelope.tipo,
        de,
        para,
        `devolveu \`versao\` ${convertido.versao}`,
      );
    }
    return convertido;
  }
}

/** O registo do processo. **Vazio** — ver a nota no topo do ficheiro. */
export const CONVERSORES = new RegistoDeConversores();
