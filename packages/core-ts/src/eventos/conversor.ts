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
 * ## O primeiro conversor, e porque é que ele recusa
 *
 * O KAM-159 trouxe a `v2` dos 38 contratos, e com ela o primeiro conversor:
 * `descerFinalidades`, registado para os 38 tipos.
 *
 * A `v2` difere da `v1` numa coisa só — o domínio de `finalidades` ganhou
 * `partilha_estafeta` e `notificacao_dono`. Descer um envelope que **não** as
 * use é trivial e seguro: muda-se a `versao` e mais nada.
 *
 * Descer um que as use **não se faz**, e o conversor recusa. A tentação é
 * deitá-las fora e entregar o resto, e é exactamente a coisa errada: as
 * `finalidades` são o que o publicador compara com a `finalidade` de cada
 * subscrição (§7.3), pelo que apagar uma muda **quem recebe o evento**. Um
 * consumidor que só aceita `v1` deixaria de ver um evento de partilha com o
 * estafeta, ou vê-lo-ia sem saber que o era. Preferir o bloqueio é o que o
 * §6.6 já manda quando não há conversor nenhum, e a razão é a mesma.
 */

import { FINALIDADES_SO_NA_V2 } from "./envelope.ts";
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

/**
 * Desce um envelope `v2` a `v1`, **ou recusa** (KAM-159).
 *
 * A única diferença entre as duas versões é o domínio de `finalidades`. Se o
 * envelope não usar nenhuma das duas que só a `v2` tem, a conversão é mudar a
 * `versao`. Se usar, lança — ver a nota no topo do ficheiro.
 */
export function descerFinalidades(envelope: Envelope): Envelope {
  const soNaV2 = envelope.finalidades.filter((f) =>
    (FINALIDADES_SO_NA_V2 as readonly string[]).includes(f),
  );
  if (soNaV2.length > 0) {
    throw new ConversaoInvalidaError(
      envelope.tipo,
      2,
      1,
      `usa ${soNaV2.join(", ")}, que a v1 nao tem no dominio. Deita-las fora ` +
        "mudaria quem recebe o evento: as finalidades sao o que o publicador " +
        "compara com a subscricao",
    );
  }
  return { ...envelope, versao: 1 };
}

/**
 * O registo do processo. **Continua vazio**, e isso é deliberado.
 *
 * O KAM-159 escreveu a `v2` dos 38 contratos e o conversor que lhe serve
 * (`descerFinalidades`, acima), mas **não o registou**. A razão está na nota
 * do topo deste ficheiro, escrita pelo KAM-005 e que continua a valer: «quando
 * o primeiro `versao = 2` aparecer, é quem o emitir que o regista, no ticket
 * dele». Hoje **nada emite** `v2` — zero produtores, zero subscrições — e um
 * conversor registado para um salto que ninguém dá é cablagem sem consumidor.
 *
 * Quem emitir a primeira `v2` faz uma linha:
 * `CONVERSORES.registar(tipo, 2, 1, descerFinalidades)`.
 */
export const CONVERSORES = new RegistoDeConversores();
