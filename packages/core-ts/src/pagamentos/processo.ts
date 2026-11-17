/**
 * O processo da cobrança da assinatura: os dois *jobs* do KAM-059 e a régua do
 * KAM-058, com a guarda de arranque à cabeça.
 *
 * É o que o KAM-059 deixou com este ticket como credor («Recebido do
 * KAM-059» no bloco): o **agendamento** do `abrirCiclos` e do `acumularSombra`,
 * e a chamada ao `verificarArranque` no arranque do primeiro processo do PAY a
 * ler as *flags* de dinheiro. **O arranque recusa-se no construtor**: um
 * processo que continua depois de a guarda falhar é um processo a correr sem
 * ela (a nota do `arranque.ts`).
 *
 * ## Duas ligações, dois papéis
 *
 * O `abrirCiclos` e a sombra correm como `kamba_pay` — a conta de receita
 * própria só é visível a ele (a política `pay_receita_propria` da `0055`). A
 * régua corre como `kamba_batch` — o único papel que muda `tenants.estado`. Um
 * papel com as duas coisas era um papel com mais do que qualquer das duas
 * precisa.
 *
 * ## A cadência
 *
 * Os *jobs* do KAM-059 correm **uma vez por dia de Luanda** (são idempotentes,
 * e correr mais só custa leituras); a régua corre em **cada volta**, porque a
 * reposição depois de um pagamento tem um alvo de 60 s (critério 3).
 *
 * A sombra só corre com uma taxa: a taxa é «por contrato» e não tem omissão
 * (`comissaoEmSombra`), e fica desligada até a D8 a dar.
 */

import type { ClienteSql } from "../eventos/publicador.ts";
import {
  type ConfiguracaoDaComissao,
  type ContaParaGuarda,
  type EntidadesDaKamba,
  type FlagsDeDinheiro,
  verificarArranque,
} from "./arranque.ts";
import {
  type ContaDeReceita,
  type EmissorDeCobranca,
  type RelatorioDeAbertura,
  abrirCiclos,
  acumularSombra,
  dataEmLuanda,
} from "./billing.ts";
import {
  type MetricasDaRegua,
  type NotificadorDaRegua,
  type RelatorioDaRegua,
  correrRegua,
} from "./regua.ts";
import type { RegistoDeProviders } from "./registo.ts";
import type { Uuid } from "./tipos.ts";

/**
 * O intervalo entre voltas. **Proposta**: metade do alvo de 60 s do critério 3,
 * para que a volta seguinte a um pagamento caia dentro dele com folga para a
 * própria volta.
 */
export const INTERVALO_DA_REGUA_MS = 30_000;

/** Os argumentos do `verificarArranque`, pela ordem dele. */
export type Arranque = {
  readonly flags: FlagsDeDinheiro;
  readonly registo: RegistoDeProviders;
  readonly contas: readonly ContaParaGuarda[];
  readonly daKamba: EntidadesDaKamba;
  readonly comissao: ConfiguracaoDaComissao;
};

/** A sombra da comissão: só com uma taxa escolhida por quem a mede. */
export type ConfiguracaoDaSombra = {
  readonly taxaBps: bigint;
  readonly lote: number;
  readonly tenants: () => Promise<readonly Uuid[]>;
};

export type OpcoesDoProcesso = {
  readonly arranque: Arranque;
  /** Como `kamba_pay`. */
  readonly bdDoPay: ClienteSql;
  /** Como `kamba_batch`. */
  readonly bdDeLote: ClienteSql;
  readonly relogio: () => Date;
  readonly conta: ContaDeReceita;
  readonly emissor: EmissorDeCobranca;
  readonly gerarId: () => Uuid;
  readonly sombra?: ConfiguracaoDaSombra | null;
  readonly notificador?: NotificadorDaRegua;
  readonly metricas?: MetricasDaRegua;
};

export type RelatorioDaVolta = {
  /** `null` quando a abertura já correu hoje. */
  readonly abertura: RelatorioDeAbertura | null;
  /** `null` quando não correu (já correu hoje, ou sem taxa). */
  readonly sombra: number | null;
  /**
   * As falhas da abertura e da sombra. **Não param a régua** (achado 4 da
   * revisão adversarial): uma ligação do `kamba_pay` em baixo não pode atrasar
   * uma suspensão nem uma reposição. O dia só avança com a abertura feita, pelo
   * que a volta seguinte tenta outra vez.
   */
  readonly falhasDosJobs: readonly string[];
  readonly regua: RelatorioDaRegua;
};

function mensagemDe(erro: unknown): string {
  return erro instanceof Error ? erro.message : String(erro);
}

export class ProcessoDaCobranca {
  readonly #o: OpcoesDoProcesso;
  #ultimoDia: string | null = null;

  constructor(opcoes: OpcoesDoProcesso) {
    const a = opcoes.arranque;
    verificarArranque(a.flags, a.registo, a.contas, a.daKamba, a.comissao);
    this.#o = opcoes;
  }

  /** Uma volta: os *jobs* diários se o dia mudou, e a régua sempre. */
  async volta(): Promise<RelatorioDaVolta> {
    const o = this.#o;
    const agora = o.relogio();
    const hoje = dataEmLuanda(agora);
    let abertura: RelatorioDeAbertura | null = null;
    let sombra: number | null = null;
    const falhasDosJobs: string[] = [];
    if (this.#ultimoDia !== hoje) {
      let feitos = true;
      try {
        abertura = await abrirCiclos(o.bdDoPay, {
          agora,
          conta: o.conta,
          emissor: o.emissor,
          gerarId: o.gerarId,
        });
      } catch (erro) {
        feitos = false;
        falhasDosJobs.push(`abertura: ${mensagemDe(erro)}`);
      }
      if (o.sombra !== undefined && o.sombra !== null) {
        try {
          sombra = await acumularSombra(o.bdDoPay, {
            tenants: await o.sombra.tenants(),
            taxaBps: o.sombra.taxaBps,
            lote: o.sombra.lote,
          });
        } catch (erro) {
          feitos = false;
          falhasDosJobs.push(`sombra: ${mensagemDe(erro)}`);
        }
      }
      if (feitos) this.#ultimoDia = hoje;
    }
    const regua = await correrRegua(o.bdDeLote, {
      agora,
      ...(o.notificador === undefined ? {} : { notificador: o.notificador }),
      ...(o.metricas === undefined ? {} : { metricas: o.metricas }),
    });
    return { abertura, sombra, falhasDosJobs, regua };
  }
}

/**
 * Corre o processo de `intervaloMs` em `intervaloMs`, sem voltas sobrepostas:
 * a seguinte agenda-se no fim da anterior. Uma volta que falha não pára as
 * seguintes — a falha vai ao `aoFalhar`. **O relatório de cada volta vai ao
 * `aoRelatar`**: é por ele que as falhas por ciclo, as suspensões adiadas e o
 * `alertaDeSuspensoes` chegam a quem os publica (achado 4 da revisão
 * adversarial — antes deitavam-se fora). Devolve a função que pára.
 */
export function agendar(
  processo: Pick<ProcessoDaCobranca, "volta">,
  intervaloMs: number = INTERVALO_DA_REGUA_MS,
  aoFalhar: (erro: unknown) => void = () => {},
  aoRelatar: (relatorio: RelatorioDaVolta) => void = () => {},
): () => void {
  let parado = false;
  let temporizador: ReturnType<typeof setTimeout> | null = null;
  const seguinte = (): void => {
    if (parado) return;
    temporizador = setTimeout(() => {
      processo
        .volta()
        .then(aoRelatar)
        .catch(aoFalhar)
        .finally(seguinte);
    }, intervaloMs);
  };
  seguinte();
  return () => {
    parado = true;
    if (temporizador !== null) clearTimeout(temporizador);
  };
}
